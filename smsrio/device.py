# Copyright (C) 2026 The SMSRio Open Driver Authors
# SPDX-License-Identifier: GPL-2.0-or-later
# smsrio-pbcnx

"""Bring-up and streaming for Siano Rio."""
import time
from collections import Counter

from . import firmware
from .transport import DATA_TYPES, TransportError


class SmsRio:
    def __init__(self, device, log=None):
        self.device = device
        self.log = log or (lambda message: None)
        # Instrumentation only: what the reader saw, and what it threw away.
        self.discarded = Counter()
        self.ts_messages = 0
        self.ts_bytes = 0
        # The last transport error seen by read_ts; the supervisor keys on it,
        # never on "no data" (an empty channel is not a detach).
        self.last_error = None

    def _version_or_blank(self):
        """The chip's version, or "" only after a second read also fails.

        The first request after an open can lose its reply on a warm chip: on
        the Pi (2026-11-20) the first 0x01f7 read timed out at 2 s and the retry
        answered in 0.01 s.  Reading that as "blank ROM" makes bring_up upload
        over a warm chip, which is the forced upload that wedges this firmware.
        So one cheap retry comes before the verdict, never after it.
        """
        try:
            return self.device.version()
        except TransportError as error:
            first = str(error)
        try:
            return self.device.version(timeout=1000)
        except TransportError:
            self.log("version read failed twice (%s); treating the chip as blank" % first)
            return ""

    def bring_up(self, firmware_path=None, mode=None):
        version = ""
        if firmware_path is None:
            version = self._version_or_blank()

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

    def reinit(self):
        """The warm rung: re-select the mode on the firmware already in RAM.

        No version probe and no upload.  After a TS-interface wedge the chip can
        stop answering 0x01f7, and a failed probe is read as "blank ROM" - which
        uploads over a warm chip and wedges it for real (measured on the Pi,
        2026-11-20: the probe failed, the upload ran, the next tune was silent).
        A blank chip is the fresh-handle rung's job, and only it uploads.
        """
        self.device.set_mode()
        return True

    def tune(self, frequency_khz):
        self.device.add_pid(0x2000)
        self.device.tune(frequency_khz)
        self.log("tuned to %d kHz" % frequency_khz)
        return True

    def wait_lock(self, timeout=8.0, interval=0.3):
        """Poll statistics until the demod locks; returns the last reading."""
        deadline = time.monotonic() + timeout
        status = None
        while time.monotonic() < deadline:
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
        """Next TS payload; a transport error is remembered in last_error."""
        try:
            message = self.device.read_message(timeout)
        except Exception as error:
            self.last_error = error
            return b""
        if getattr(self.device, "last_read_error", None) is not None:
            self.last_error = self.device.last_read_error
            self.device.last_read_error = None
            return b""
        self.last_error = None
        if not message:
            return b""
        msg_type, src, dst, body = message
        if msg_type not in DATA_TYPES:
            self.discarded[msg_type] += 1
            return b""
        self.ts_messages += 1
        self.ts_bytes += len(body)
        return body
