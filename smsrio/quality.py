# Copyright (C) 2026 The SMSRio Open Driver Authors
# SPDX-License-Identifier: GPL-2.0-or-later
# smsrio-pbcnx

"""Shared quality metric: clean-packet percentage over a sliding window.

Studio definition (2026-11-18, the same in every driver line): quality % is
100 * clean / total over a sliding window, default 5 s. A packet is not clean
if its transport_error_indicator is set or it breaks the continuity counter on
its PID. A repeated continuity counter is not a break. PID 0x1FFF (null) and
adaptation-only packets are skipped, as are packets that do not start with 0x47.

The result is None (unknown) until the meter has been fed for a full window, and
when no packet is counted; a partial window does not report a percentage. The
Java core uses -1 for the same unknown, because `Status` is an int object.

This is the packet-based Q. The firmware's own SNR (dB) and RSSI (dBm) come
from the statistics message and stay under their own names; this meter never
touches USB.
"""
import time
from collections import deque

TS_PACKET = 188
NULL_PID = 0x1FFF


class QualityMeter:
    """Feed whole TS packets (a 3,760-byte stream payload is 20 of them)."""

    def __init__(self, window_seconds=5.0, clock=time.monotonic):
        self.window = float(window_seconds)
        self._clock = clock
        self._entries = deque()  # (timestamp, clean, total)
        self._last_cc = {}       # pid -> last continuity counter
        self._started = None
        self.clean = 0
        self.total = 0

    def feed(self, data, now=None):
        """Count one buffer of whole packets; ``now`` exists for tests."""
        if not data:
            return
        if len(data) % TS_PACKET:
            data = data[:len(data) // TS_PACKET * TS_PACKET]
        when = self._clock() if now is None else now
        if self._started is None:
            self._started = when
        clean = 0
        total = 0
        for offset in range(0, len(data), TS_PACKET):
            packet = data[offset:offset + TS_PACKET]
            if packet[0] != 0x47:
                continue
            pid = ((packet[1] & 0x1F) << 8) | packet[2]
            if pid == NULL_PID:
                continue
            afc = (packet[3] >> 4) & 0x3
            if afc == 0 or afc == 2:  # reserved, or adaptation field only
                continue
            total += 1
            if packet[1] & 0x80:      # transport_error_indicator
                continue
            cc = packet[3] & 0x0F
            last = self._last_cc.get(pid)
            self._last_cc[pid] = cc
            if last is not None and cc != last and cc != ((last + 1) & 0x0F):
                continue
            clean += 1
        self.clean += clean
        self.total += total
        self._entries.append((when, clean, total))
        self._purge(when)

    def _purge(self, now):
        cutoff = now - self.window
        while self._entries and self._entries[0][0] < cutoff:
            _, clean, total = self._entries.popleft()
            self.clean -= clean
            self.total -= total

    def percent(self, now=None):
        """0-100, or None before the first full window or with no counted packet."""
        when = self._clock() if now is None else now
        self._purge(when)
        if (self.total <= 0 or self._started is None
                or (when - self._started) < self.window):
            return None
        return 100.0 * self.clean / self.total

    def counts(self):
        self._purge(self._clock())
        return self.clean, self.total

    def reset(self):
        self._entries.clear()
        self._last_cc.clear()
        self._started = None
        self.clean = 0
        self.total = 0
