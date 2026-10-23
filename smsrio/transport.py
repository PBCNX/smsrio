"""USB transport for Siano Rio (187F:0600).

Messages are an 8-byte little-endian header followed by a payload:
``<type u16><src u8><dst u8><length u16><flags u16>``. Control responses and
the transport stream share the bulk-IN endpoint; a streaming transfer is a
504-byte pad, the 8-byte header, then 20 TS packets at offset 512 (see
stream.py).
"""
import os
import struct
import sys
import time

VID = 0x187F
PID_RIO = 0x0600

EP_IN = 0x81
EP_OUT = 0x02

HIF_TASK = 11

MSG_VERSION_REQ = 503
MSG_VERSION_RES = 504
MSG_INIT_REQ = 578
MSG_INIT_RES = 579
MSG_ADD_PID_REQ = 601
MSG_ADD_PID_RES = 602
MSG_GET_STATISTICS_REQ = 615
MSG_GET_STATISTICS_RES = 616
MSG_GET_STATISTICS_EX_REQ = 653
MSG_GET_STATISTICS_EX_RES = 654
MSG_DAB_CHANNEL = 607
MSG_DVBT_BDA_DATA = 693
MSG_TUNE_REQ = 776
MSG_TUNE_RES = 777

# Message types that carry MPEG-TS on the bulk-IN endpoint.  This firmware
# (ISDBT 07.03.58.0 RIO) uses MSG_SMS_DAB_CHANNEL; older captures show
# MSG_SMS_DVBT_BDA_DATA for the same 512 + 20 x 188 layout.
DATA_TYPES = (MSG_DAB_CHANNEL, MSG_DVBT_BDA_DATA)

DEVICE_MODE_ISDBT_BDA = 7
BW_ISDBT_13SEG = 8

# MSG_HDR_FLAG_SPLIT_MSG: the device pushes the real header inside the
# transfer, at (alignment + (flags >> 8 & 3)), because the USB DMA needs the
# payload page aligned.  Alignment is max_packet_size - sizeof(header).
FLAG_SPLIT_MSG = 4
HEADER = 8


class TransportError(RuntimeError):
    pass


def _signed(value):
    return value - (1 << 32) if value >= (1 << 31) else value


def _alignment(usb_device):
    """max_packet_size - 8: where the split payload starts on a wire transfer."""
    try:
        for config in usb_device:
            for interface in config:
                for endpoint in interface:
                    if endpoint.bEndpointAddress == EP_IN:
                        return endpoint.wMaxPacketSize - HEADER
    except Exception:
        pass
    return 512 - HEADER


def _pyusb():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    vendor = os.path.join(root, "vendor")
    if os.path.isdir(os.path.join(vendor, "usb")) and vendor not in sys.path:
        sys.path.insert(0, vendor)
    import usb.util

    return usb.util


def backend():
    _pyusb()
    import usb.backend.libusb1 as libusb1

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bundled = os.path.join(root, "vendor", "windows", "x64", "libusb-1.0.dll")
    chosen = os.environ.get("SMSRIO_LIBUSB")
    if chosen:
        return libusb1.get_backend(find_library=lambda name: chosen)
    if os.name == "nt" and os.path.exists(bundled):
        return libusb1.get_backend(find_library=lambda name: bundled)
    return libusb1.get_backend()


def devices():
    _pyusb()
    import usb.core

    handle = backend()
    if handle is None:
        raise TransportError("libusb backend unavailable")
    return list(usb.core.find(find_all=True, idVendor=VID, backend=handle))


class SmsDevice:
    # Replies arrive interleaved with stream transfers and indications.  A
    # request keeps the messages it is not waiting for so the reader can still
    # deliver them, instead of throwing away a TS transfer per poll.
    #
    # The buffer has to cover a whole reply's worth of stream: at 8 Mbps a
    # 2 s reply can be behind ~500 transfers of 2 KB.  512 keeps that without
    # holding tens of megabytes on a phone.  Anything beyond it is counted in
    # ``dropped`` - silent loss is what must not happen.
    PENDING_LIMIT = 512

    def __init__(self, usb_device, timeout=2000, log=None):
        self.usb = usb_device
        self.timeout = timeout
        self.log = log or (lambda message: None)
        self.alignment = 0
        self.pending = []
        self.dropped = 0

    def open(self):
        try:
            self.usb.set_configuration()
        except Exception:
            pass
        util = _pyusb()
        util.claim_interface(self.usb, 0)
        # No clear_halt here: on a freshly enumerated ROM it is a needless
        # request, and a halt that matters later is recovered per read.
        try:
            self.alignment = _alignment(self.usb)
        except Exception:
            self.alignment = 512 - HEADER
        return self

    def close(self):
        try:
            _pyusb().release_interface(self.usb, 0)
        except Exception:
            pass

    def send(self, msg_type, payload=b"", src=0, dst=HIF_TASK, flags=0):
        body = struct.pack("<HBBHH", msg_type, src, dst, 8 + len(payload), flags)
        self.usb.write(EP_OUT, body + payload, self.timeout)

    def _decode(self, data):
        """Split-aware header parse; returns (type, src, dst, body) or None.

        On a split transfer the header stays at offset 0 on the wire and the
        payload is pushed to ``alignment + 8``  (the kernel copies the header
        into the buffer after the URB completes, which is why the copy point
        reads as zeros in a capture).
        """
        if len(data) < HEADER:
            return None
        msg_type, src, dst, length, flags = struct.unpack("<HBBHH", data[:HEADER])
        start = HEADER
        if flags & FLAG_SPLIT_MSG:
            start = self.alignment + ((flags >> 8) & 3) + HEADER
        if length < HEADER or start + length - HEADER > len(data):
            return None
        return msg_type, src, dst, data[start:start + length - HEADER]

    def _read(self, size, timeout):
        """One bulk read, recovering from a halted endpoint once.

        A cancelled bulk read - a timeout on Windows is a cancellation - leaves
        the IN pipe stalled, and from then on every read fails *instantly*
        instead of waiting.  That is what turns one late reply into a device
        that answers nothing until it is unplugged.  clear_halt costs one
        request and fixes it.
        """
        try:
            return bytes(self.usb.read(EP_IN, size, timeout))
        except Exception as error:
            try:
                self.usb.clear_halt(EP_IN)
                return bytes(self.usb.read(EP_IN, size, timeout))
            except Exception:
                raise TransportError(str(error))

    def receive(self, timeout=None):
        data = self._read(16384, timeout or self.timeout)
        decoded = self._decode(data)
        if decoded is None:
            raise TransportError("malformed message")
        return decoded

    def read_message(self, timeout=300):
        """Next message, or None on timeout; used by the streaming loop."""
        if self.pending:
            return self.pending.pop(0)
        try:
            data = self._read(16384, timeout)
        except Exception:
            return None
        return self._decode(data)

    def request(self, msg_type, payload, expected, timeout=None):
        """Send a request and return the matching reply payload.

        The reply arrives on the same bulk-IN endpoint as the stream, so it can
        sit behind any number of TS transfers.  Two rules matter here:

        * the timeout is wall-clock, not a fixed number of messages.  Charging
          every skipped transfer against it made a poll fail on a busy stream
          even though only milliseconds had passed;
        * every transfer that is not the reply is kept, in order, in
          ``pending`` so the reader still delivers it.  A poll must cost zero
          packets.
        """
        self.send(msg_type, payload)
        budget = self.timeout if timeout is None else timeout
        deadline = time.monotonic() + budget / 1000.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                # One read with the whole remaining budget: cancelling a bulk
                # read to re-issue it can lose the reply on Windows, and the
                # caller only gets here when the device is idle or the reply is
                # genuinely late.
                message = self.receive(remaining * 1000)
            except TransportError:
                continue
            if message[0] == expected:
                return message[3]
            if len(self.pending) < self.PENDING_LIMIT:
                self.pending.append(message)
            else:
                self.dropped += 1
        raise TransportError("no response to 0x%04x" % msg_type)

    def version(self):
        body = self.request(MSG_VERSION_REQ, b"", MSG_VERSION_RES)
        return body.decode("ascii", "replace").strip("\x00").strip()

    def set_mode(self, mode=DEVICE_MODE_ISDBT_BDA):
        return self.request(MSG_INIT_REQ, struct.pack("<I", mode), MSG_INIT_RES)

    def add_pid(self, pid):
        """Add a PID filter.

        The device does not answer this request - Linux sends it and carries
        on - so do not block waiting for MSG_SMS_ADD_PID_FILTER_RES either.
        """
        self.send(MSG_ADD_PID_REQ, struct.pack("<I", pid))

    def tune(self, frequency_khz, bandwidth=BW_ISDBT_13SEG, segment=0):
        """Tune to a frequency given in kHz.

        The wire field is Hz: the Linux capture shows 599,143,000 for
        599.143 MHz, and a kHz value tunes a thousand times too low.
        """
        payload = struct.pack("<IIII", frequency_khz * 1000, bandwidth,
                              12000000, segment)
        return self.request(MSG_TUNE_REQ, payload, MSG_TUNE_RES)

    def statistics(self):
        """ISDB-T statistics: lock, SNR, power, frequency."""
        body = self.request(MSG_GET_STATISTICS_EX_REQ, b"",
                            MSG_GET_STATISTICS_EX_RES)
        values = struct.unpack("<%dI" % (len(body) // 4),
                               body[:len(body) // 4 * 4])
        if len(values) < 12:
            raise TransportError("short statistics")
        # layout: request_result, statistics_type, full_size, is_rf_locked,
        # is_demod_locked, is_external_lna_on, SNR, RSSI, in_band_pwr, ...
        return {
            "rf_locked": bool(values[3]),
            "demod_locked": bool(values[4]),
            "lna": bool(values[5]),
            "snr": _signed(values[6]),
            "rssi": _signed(values[7]),
            "power": _signed(values[8]),
            "carrier_offset": _signed(values[9]),
            "frequency": values[10],
            "bandwidth": values[11],
        }

    def read_stream(self, size=8192, timeout=300):
        return self._read(size, timeout)