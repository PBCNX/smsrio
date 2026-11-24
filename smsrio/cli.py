# Copyright (C) 2026 The SMSRio Open Driver Authors
# SPDX-License-Identifier: GPL-2.0-or-later
# smsrio-pbcnx

"""Command line interface for Siano Rio."""
import argparse
import json
import queue
import socket
import sys
import threading
import time

from . import PROVENANCE, __version__
from .device import SmsRio
from .quality import QualityMeter
from .supervisor import find_rio, recover, stream_packets, supervise
from .tmcc import format_line
from .transport import PID_RIO, SmsDevice, TransportError, devices


class DeviceLost(Exception):
    """A scan lost the device; the caller prints one line and exits non-zero."""


def open_device(index=0):
    found = [d for d in devices() if d.idProduct == PID_RIO]
    if not found:
        raise SystemExit("no Siano Rio (187f:0600) found; bind it to WinUSB first")
    if index >= len(found):
        raise SystemExit("only %d device(s) found" % len(found))
    try:
        return SmsDevice(found[index]).open()
    except Exception as exc:
        text = str(exc)
        lowered = text.lower()
        if "busy" in lowered or "claim" in lowered or "access" in lowered:
            raise SystemExit("cannot claim the Siano Rio device: %s" % text)
        raise SystemExit("cannot open the Siano Rio device: %s" % text)


def log_stderr(message):
    """Human messages belong on stderr; stdout is only TS when --out is -."""
    print(message, file=sys.stderr)


def no_ts_hint(packets, locked, seconds):
    """The hint after the software ladder failed: the cable is the only reset."""
    if packets or not locked:
        return None
    span = "%g s" % seconds if seconds else "the run"
    return ("locked but no TS for %s - the recovery was tried (warm re-init, then a fresh "
            "handle); unplug/replug the stick (a USB reset does not clear firmware RAM)" % span)


def cmd_list(args):
    found = False
    for device in devices():
        found = True
        supported = "supported" if device.idProduct == PID_RIO else "unsupported"
        print("187f:%04x  bus %s addr %s  %s" % (
            device.idProduct, device.bus, device.address, supported))
    if not found:
        print("no 187f devices found")
    return 0


def cmd_probe(args):
    device = open_device(args.index)
    try:
        rio = SmsRio(device, print)
        version = rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        total = 0
        for _ in range(20):
            total += len(rio.read_ts())
            if total > 100000:
                break
        print("firmware: %s" % version)
        if status:
            print("rf: %s demod: %s snr: %d dB power: %d dBm offset: %d Hz"
                  % (status["rf_locked"], status["demod_locked"], status["snr"],
                     status["power"], status["carrier_offset"]))
        else:
            print("status: no statistics")
        print("ts: %d bytes" % total)
        return 0
    finally:
        device.close()


def cmd_status(args):
    device = open_device(args.index)
    try:
        rio = SmsRio(device, print)
        rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        if not status:
            print("no statistics from the device")
            return 1
        print("version:    %s" % device.version())
        print("rf:         %s" % status["rf_locked"])
        print("demod:      %s" % status["demod_locked"])
        print("snr:        %d dB" % status["snr"])
        print("rssi:       %d dBm" % status["rssi"])
        print("in-band:    %d dBm" % status["power"])
        print("carrier:    %d Hz" % status["carrier_offset"])
        print("frequency:  %d Hz" % status["frequency"])
        print("bandwidth:  %d MHz" % status["bandwidth"])
        return 0 if status["demod_locked"] else 2
    finally:
        device.close()


def cmd_tmcc(args):
    device = open_device(args.index)
    try:
        rio = SmsRio(device, print)
        rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        record = status.get("tmcc") if status else None
        locked = bool(status and status["demod_locked"])
        valid = bool(record and record.get("valid"))
        if not valid:
            print(format_line(args.freq, record), file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({
                "freq": args.freq,
                "lock": locked,
                "strength": strength_percent(status["power"]) if status else None,
                "tmcc": record,
            }, indent=2, sort_keys=True))
        else:
            print(format_line(args.freq, record))
            if args.raw and record:
                print("raw: " + " ".join(str(word) for word in record["raw"]))
        return 0 if locked else 2
    finally:
        device.close()


def scan_channels(rio, start, stop, step, seconds, out=print):
    """Tune each channel, count the packets that actually arrive, one line each."""
    if step <= 0:
        raise ValueError("step must be > 0")
    found = 0
    for khz in range(start, stop + 1, step):
        try:
            rio.tune(khz)
            status = rio.wait_lock(timeout=min(seconds, 3.0))
        except TransportError:
            if find_rio() is None:
                raise DeviceLost("device lost during scan")
            status = None
        deadline = time.monotonic() + seconds
        packets = 0
        while time.monotonic() < deadline:
            data = rio.read_ts(timeout=300)
            if rio.last_error is not None and find_rio() is None:
                raise DeviceLost("device lost during scan")
            packets += len(data) // 188
        if status is None:
            try:
                status = rio.status()
            except TransportError:
                status = None
        locked = bool(status and status.get("demod_locked")) and packets > 0
        strength = strength_percent(status["power"]) if status else None
        out("%d kHz %s strength %s" % (
            khz, "LOCK" if locked else "no lock",
            strength if strength is not None else "n/a"))
        found += 1 if locked else 0
    return found


def cmd_scan(args):
    device = open_device(args.index)
    try:
        rio = SmsRio(device, lambda message: None)
        rio.bring_up(args.firmware)
        found = scan_channels(rio, args.start, args.stop, args.step, args.seconds)
        return 0 if found else 1
    except DeviceLost as error:
        print(str(error), file=sys.stderr)
        return 1
    finally:
        device.close()


def cmd_recover(args):
    """State-3 ladder: warm re-init, then a fresh handle; the cable only if both fail."""
    device = open_device(args.index)
    fresh = None
    rio = None
    try:
        rio = SmsRio(device, log_stderr)
        fresh = recover(rio, args.freq, log_stderr)
        if fresh is None:
            print("recover failed; unplug and replug the stick "
                  "(a USB reset does not clear firmware RAM)", file=sys.stderr)
            return 1
        status = fresh.wait_lock(timeout=args.timeout)
        packets = stream_packets(fresh, args.seconds)
        locked = bool(status and status["demod_locked"])
        print("recover: lock %s, %d packets in %g s"
              % (locked, packets, args.seconds), file=sys.stderr)
        return 0 if locked and packets else 1
    finally:
        if fresh is not None and fresh is not rio:
            fresh.device.close()
        device.close()


class Sink:
    """Writes TS on its own thread, so a slow consumer cannot stall USB reads.
    Lossless mode (default) blocks when the bounded queue is full: captures keep
    every byte, order preserved. Live mode drops the oldest chunk instead, for
    players that would rather lose a little than pause the dongle.
    """

    def __init__(self, path=None, udp=None, drop_null=False, live=False, queue_size=64):
        self.file = None
        self.sock = None
        self.addr = None
        self.drop_null = drop_null
        self.live = live
        self.dropped = 0
        self.queue = queue.Queue(maxsize=max(1, queue_size))
        if udp:
            host, _, port = udp.rpartition(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addr = (host or "127.0.0.1", int(port))
        elif path and path != "-":
            self.file = open(path, "wb")
        else:
            self.file = sys.stdout.buffer
        self.thread = threading.Thread(target=self._run, name="smsrio-sink", daemon=True)
        self.thread.start()

    def write(self, data):
        if self.drop_null:
            data = strip_null_packets(data)
        if not data:
            return
        if not self.live:
            self.queue.put(data)
            return
        while True:
            try:
                self.queue.put_nowait(data)
                return
            except queue.Full:
                try:
                    self.queue.get_nowait()
                    self.dropped += 1
                except queue.Empty:
                    pass

    def _run(self):
        while True:
            data = self.queue.get()
            if data is None:
                return
            try:
                self._emit(data)
            except Exception:
                # A dead stdout/socket must not hang the producer.
                pass

    def _emit(self, data):
        if self.sock:
            for i in range(0, len(data), 1316):
                self.sock.sendto(data[i:i + 1316], self.addr)
        else:
            self.file.write(data)
            self.file.flush()

    def close(self):
        if self.thread.is_alive():
            if self.live:
                while True:
                    try:
                        self.queue.put_nowait(None)
                        break
                    except queue.Full:
                        try:
                            self.queue.get_nowait()
                            self.dropped += 1
                        except queue.Empty:
                            pass
            else:
                self.queue.put(None)
            self.thread.join()
        if self.file and self.file is not sys.stdout.buffer:
            self.file.close()
        if self.sock:
            self.sock.close()


def strip_null_packets(data):
    """Remove 188-byte null packets (PID 0x1FFF) from a TS body."""
    if len(data) % 188:
        return data
    out = bytearray()
    for offset in range(0, len(data), 188):
        packet = data[offset:offset + 188]
        if packet[0] == 0x47:
            pid = ((packet[1] & 0x1F) << 8) | packet[2]
            if pid == 0x1FFF:
                continue
        out += packet
    return bytes(out)


def strength_percent(power):
    """The shared strength scale: 0-100 from in-band power in dBm."""
    return max(0, min(100, 100 + int(power)))


def status_line(packets, locked, strength, quality):
    """The player contract line, exactly: ts packets N lock True|False strength S quality Q."""
    strength_text = "n/a" if strength is None else str(strength)
    quality_text = "n/a" if quality is None else str(quality)
    return ("ts packets %d lock %s strength %s quality %s"
            % (packets, "True" if locked else "False", strength_text, quality_text))


def cmd_play(args):
    device = open_device(args.index)
    sink = Sink(args.out, args.udp, drop_null=args.drop_null, live=args.live)
    meter = QualityMeter(args.quality_window)
    interval = args.status_interval
    next_status = time.monotonic() + interval if interval else None
    rio = None
    try:
        rio = SmsRio(device, log_stderr)
        rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        if status and status["demod_locked"]:
            print("locked: snr %d dB, in-band %d dBm"
                  % (status["snr"], status["power"]), file=sys.stderr)
        else:
            print("no lock: in-band %s dBm - check the antenna"
                  % (status["power"] if status else "?"), file=sys.stderr)
        started = time.time()
        packets = 0
        last_data = time.monotonic()
        last_presence = last_data
        errors = 0
        recovered = False
        while not args.seconds or time.time() - started < args.seconds:
            data = rio.read_ts()
            now = time.monotonic()
            if data:
                meter.feed(data)
                sink.write(data)
                packets += len(data) // 188
                last_data = now
                errors = 0
                recovered = False
            else:
                errors = errors + 1 if rio.last_error is not None else 0
                lost = errors >= 3
                if not lost and (errors or now - last_data > 1.5):
                    if now - last_presence >= 1.0:
                        last_presence = now
                        lost = find_rio() is None
                if lost:
                    # A detach is silence AND absence (LME's rule): the read may fail
                    # (Windows/Linux) or just time out while the device is gone (macOS/Android).
                    print("stream lost (%s); waiting for the dongle"
                          % (rio.last_error or "device gone"), file=sys.stderr)
                    fresh = supervise(rio, args.firmware, args.freq,
                                      args.supervise_seconds, log_stderr)
                    if fresh is None:
                        print("reconnect failed after %g s; unplug and replug the stick"
                              % args.supervise_seconds, file=sys.stderr)
                        return 1
                    rio = fresh
                    status = rio.wait_lock(timeout=args.timeout)
                    last_data = time.monotonic()
                    last_presence = last_data
                    errors = 0
                    recovered = False
                    next_status = time.monotonic() + interval if interval else None
                elif (args.stall_seconds and not recovered
                      and now - last_data > args.stall_seconds
                      and status and status.get("demod_locked")
                      and find_rio() is not None):
                    # The wedge: present and locked, no TS. Ladder: warm -> fresh handle.
                    print("locked but no TS for %g s; recovering"
                          % args.stall_seconds, file=sys.stderr)
                    try:
                        fresh = recover(rio, args.freq, log_stderr)
                    except Exception as error:
                        print("recover failed (%s)" % error, file=sys.stderr)
                        fresh = None
                    if fresh is None:
                        print("recover failed; unplug and replug the stick "
                              "(a USB reset does not clear firmware RAM)", file=sys.stderr)
                    else:
                        rio = fresh
                        status = rio.wait_lock(timeout=args.timeout)
                    recovered = True
                    last_data = time.monotonic()
            if next_status is not None:
                now = time.monotonic()
                if now >= next_status:
                    try:
                        stats = rio.status()
                    except TransportError:
                        stats = None
                    quality = meter.percent()
                    quality_value = None if quality is None else int(round(quality))
                    if stats:
                        line = status_line(packets, stats["demod_locked"],
                                           strength_percent(stats["power"]),
                                           quality_value)
                    else:
                        line = status_line(packets, False, None, quality_value)
                    print(line, file=sys.stderr)
                    next_status = now + interval
        print("wrote %d packets" % packets, file=sys.stderr)
        hint = no_ts_hint(packets, bool(status and status["demod_locked"]), args.seconds)
        if hint:
            print(hint, file=sys.stderr)
        if args.stats:
            print("counters: " + " ".join(
                "%s=%s" % item for item in sorted(rio.device.counters.items())),
                file=sys.stderr)
            print("ts: messages=%d bytes=%d" % (rio.ts_messages, rio.ts_bytes),
                  file=sys.stderr)
            clean, counted = meter.counts()
            quality = meter.percent()
            if quality is None:
                print("quality: n/a (unknown until a %.1f s window fills)"
                      % meter.window, file=sys.stderr)
            else:
                print("quality: %.1f%% (%d/%d clean packets over %.1f s)"
                      % (quality, clean, counted, meter.window),
                      file=sys.stderr)
            if sink.dropped:
                print("sink: dropped %d stale chunk(s)" % sink.dropped, file=sys.stderr)
            if rio.discarded:
                print("discarded: " + " ".join(
                    "%s=%s" % item for item in sorted(rio.discarded.items())),
                    file=sys.stderr)
        return 0
    finally:
        sink.close()
        if rio is not None:
            rio.device.close()
        else:
            device.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="smsrio", description=__doc__)
    parser.add_argument("--version", action="version",
                        version="smsrio %s (%s)" % (__version__, PROVENANCE))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list 187f devices")
    p.set_defaults(func=cmd_list)

    for name, func, text in (("probe", cmd_probe, "bring up, tune and read TS"),
                             ("status", cmd_status, "lock, SNR and in-band power"),
                             ("play", cmd_play, "stream MPEG-TS")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--index", type=int, default=0)
        p.add_argument("--freq", type=int, default=599143, help="kHz")
        p.add_argument("--firmware", metavar="PATH")
        p.add_argument("--timeout", type=float, default=5.0,
                       help="seconds to wait for lock")
        p.set_defaults(func=func)
        if name == "play":
            p.add_argument("--out", default="-", help="file, - for stdout")
            p.add_argument("--udp", help="HOST:PORT")
            p.add_argument("--seconds", type=float, default=0)
            p.add_argument("--stats", action="store_true",
                           help="print transport counters and quality at the end")
            p.add_argument("--status-interval", type=float, default=0.0,
                           help="seconds between status lines on stderr (0 = off)")
            p.add_argument("--quality-window", type=float, default=5.0,
                           help="seconds in the quality window (default 5.0)")
            p.add_argument("--drop-null", action="store_true",
                           help="drop MPEG-TS null packets (PID 0x1FFF)")
            p.add_argument("--live", action="store_true",
                           help="drop stale chunks instead of stalling USB")
            p.add_argument("--supervise-seconds", type=float, default=10.0,
                           help="reconnect window after a detach (0 = off)")
            p.add_argument("--stall-seconds", type=float, default=3.0,
                           help="locked + no TS seconds before the recover (0 = off)")

    p = sub.add_parser("tmcc", help="ISDB-T TMCC from the 653 statistics")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--freq", type=int, default=599143, help="kHz")
    p.add_argument("--firmware", metavar="PATH")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="seconds to wait for lock")
    p.add_argument("--json", action="store_true")
    p.add_argument("--raw", action="store_true",
                   help="print the raw field words")
    p.set_defaults(func=cmd_tmcc)

    p = sub.add_parser("scan", help="scan a frequency range, one line per channel")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--start", type=int, default=473143, help="kHz")
    p.add_argument("--stop", type=int, default=509143, help="kHz")
    p.add_argument("--step", type=int, default=6000, help="kHz")
    p.add_argument("--seconds", type=float, default=2.0,
                   help="seconds per channel")
    p.add_argument("--firmware", metavar="PATH")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("recover",
                       help="state-3 recovery: warm re-init, then a fresh handle")
    p.add_argument("--index", type=int, default=0)
    p.add_argument("--freq", type=int, default=599143, help="kHz")
    p.add_argument("--timeout", type=float, default=8.0,
                   help="seconds to wait for lock")
    p.add_argument("--seconds", type=float, default=2.0,
                   help="seconds of TS to verify the recovery")
    p.set_defaults(func=cmd_recover)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except TransportError as error:
        print("smsrio: transport error: %s" % error, file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print("smsrio: %s" % error, file=sys.stderr)
        return 1
    except ValueError as error:
        # A wrong or truncated firmware image is a user mistake, not a crash: one line, exit 1.
        print("smsrio: %s" % error, file=sys.stderr)
        return 1
    except Exception as error:
        if type(error).__name__ in ("USBError", "USBTimeoutError"):
            print("smsrio: USB error: %s" % error, file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())


