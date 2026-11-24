# Copyright (C) 2026 The SMSRio Open Driver Authors
# SPDX-License-Identifier: GPL-2.0-or-later
# smsrio-pbcnx

"""Rebuild the session after a detach; never revive a dead handle.

The family recovery standard (2026-11-20): a handle that saw a detach is dead,
even if the kernel still lists it.  Close it, poll for the device, open a fresh
one, bring up (upload only if it came back blank), re-tune the last frequency,
and keep writing to the same sink.

The wedge (state 3) is different from a detach (state 2):
  * a detach is a transport error plus the device gone from the bus;
  * a wedge is a present device, a locked demod and no TS.
The wedge's software step here is a warm re-init (`reinit()`: re-select the mode,
no version probe, no upload - a failed probe on this chip reads as "blank" and an
upload over a warm chip wedges it, measured 2026-11-20), then a fresh handle, and
the image only if that handle came back blank.  A libusb reset is NOT enough
(measured 2026-11-20); the cable is the guarantee.
"""
import time

from .device import SmsRio
from .transport import PID_RIO, SmsDevice, devices

POLL_SECONDS = 0.5


def find_rio():
    """The first Siano Rio on the bus, or None."""
    for device in devices():
        if device.idProduct == PID_RIO:
            return device
    return None


def wait_for_rio(window_seconds, log, poll_seconds=POLL_SECONDS):
    """Poll for the stick; returns (device, attempts) or (None, attempts)."""
    if window_seconds <= 0:
        return find_rio(), 1
    deadline = time.monotonic() + window_seconds
    attempts = 0
    while time.monotonic() < deadline:
        attempts += 1
        device = find_rio()
        if device is not None:
            return device, attempts
        log("waiting (%d): no Siano Rio (187f:0600) found" % attempts)
        time.sleep(poll_seconds)
    return None, attempts


def reopen(device, firmware_path, frequency_khz, log):
    """A fresh handle: open, bring up (upload only if blank), tune."""
    rio = SmsRio(SmsDevice(device).open(), log)
    rio.bring_up(firmware_path)
    rio.tune(frequency_khz)
    return rio


def supervise(rio, firmware_path, frequency_khz, window_seconds, log):
    """Close the dead handle, then poll/reopen until the window is spent.

    A stale bus entry may appear first (macOS lists the old address for a moment after a
    replug); a failed reopen is therefore **retried**, not fatal — the IT9175's "poll, ignore
    a failed bring-up, give up only when the budget is spent" rule. Measured 2026-11-20 on the
    Mac: the first reopen after the pull hit a stale entry and died with EPIPE.
    """
    try:
        rio.device.close()
    except Exception:
        pass
    deadline = time.monotonic() + max(window_seconds, 0.0)
    attempts = 0
    while True:
        remaining = deadline - time.monotonic()
        device, tries = wait_for_rio(max(remaining, 0.0), log)
        attempts += tries
        if device is None:
            return None
        log("device back after %d attempt(s)" % attempts)
        try:
            fresh = reopen(device, firmware_path, frequency_khz, log)
        except Exception as error:
            log("reopen failed: %s" % error)
            if time.monotonic() >= deadline:
                return None
            time.sleep(POLL_SECONDS)
            continue
        log("rebuilt: %d kHz again" % frequency_khz)
        return fresh


def stream_packets(rio, seconds):
    """Count TS packets for a short verification window."""
    packets = 0
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        packets += len(rio.read_ts()) // 188
    return packets


def recover(rio, frequency_khz, log, check_seconds=4.0, window_seconds=5.0):
    """State-3 ladder: warm re-init -> fresh handle -> None (the caller prints the hint).

    There is **no forced-upload step**: measured 2026-11-20 on the bench, uploading over a
    warm/wedged Siano restarts the firmware and leaves it unresponsive to the next tune. A
    warm re-init (`reinit()`, no probe) clears the TS-interface wedge; a fresh handle clears
    the rest; the image is uploaded only when the chip really came back blank, which
    `bring_up(None)` in the fresh-handle path does by itself.

    The check window is 4 s on purpose: the Siano's first TS transfer arrives ~1.9 s after the
    tune (measured 2026-10-21 and again on 2026-11-20 — a 1.5 s window reported a false
    "still no TS" on a device that was already streaming).
    """
    try:
        rio.reinit()
        rio.tune(frequency_khz)
        if stream_packets(rio, check_seconds):
            log("recovered: warm re-init")
            return rio
        log("warm re-init: still no TS")
    except Exception as error:
        log("warm re-init failed: %s" % error)
    fresh = supervise(rio, None, frequency_khz, window_seconds, log)
    if fresh is None:
        return None
    try:
        if stream_packets(fresh, check_seconds):
            log("recovered: fresh handle")
            return fresh
        log("fresh handle: still no TS")
    except Exception as error:
        log("fresh handle failed: %s" % error)
    return None
