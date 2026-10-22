"""Bring-up and streaming for Siano Rio."""
import time

from . import firmware
from .stream import SmsStream
from .transport import DATA_TYPES, SmsDevice, TransportError


class SmsRio:
    def __init__(self, device, log=None):
        self.device = device
        self.log = log or (lambda message: None)
        self.stream = SmsStream()

    def bring_up(self, firmware_path=None, mode=None):
        version = ""
        if firmware_path is None:
            try:
                version = self.device.version()
            except TransportError:
                version = ""

        # A cold ROM does not answer a version request, and waiting for that
        # answer costs a cancelled 2 s read which can leave the IN pipe halted -
        # after which the upload looks dead.  When the caller supplies an image,
        # go straight to the upload, as the vendor sequence does.
        if firmware_path is not None or not version or "ROM" in version.upper():
            image = firmware.load(firmware_path)
            firmware.upload(self.device, image, self.log)
            time.sleep(0.5)
            try:
                version = self.device.version()
            except TransportError:
                version = "ROM"

        self.log("firmware: %s" % version)
        self.device.set_mode() if mode is None else self.device.set_mode(mode)
        return version

    def tune(self, frequency_khz):
        self.device.add_pid(0x2000)
        self.device.tune(frequency_khz)
        self.log("tuned to %d kHz" % frequency_khz)
        return True

    def wait_lock(self, timeout=8.0, interval=0.3):
        """Poll statistics until the demod locks; returns the last reading."""
        deadline = time.time() + timeout
        status = None
        while time.time() < deadline:
            try:
                status = self.device.statistics()
            except TransportError:
                status = None
            if status and status.get("demod_locked"):
                return status
            time.sleep(interval)
        return status

    def status(self):
        return self.device.statistics()

    def read_ts(self, timeout=300):
        """Next TS payload; other messages (statistics, indications) are skipped."""
        try:
            message = self.device.read_message(timeout)
        except Exception:
            return b""
        if not message:
            return b""
        msg_type, src, dst, body = message
        return body if msg_type in DATA_TYPES else b""
