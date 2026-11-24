// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

import java.util.ArrayDeque;
import java.util.HashMap;

/**
 * Shared quality metric: clean-packet percentage over a sliding window.
 *
 * <p>Studio definition (2026-11-18, the same in every driver line): quality % is
 * {@code 100 * clean / total} over a sliding window, default 5 s. A packet is not clean if its
 * transport_error_indicator is set or it breaks the continuity counter on its PID. A repeated
 * continuity counter is not a break. PID 0x1FFF (null) and adaptation-only packets are skipped,
 * as are buffers that do not start a packet with 0x47.</p>
 *
 * <p>This is the packet-based Q. The firmware's own SNR (dB) and RSSI (dBm) come from the
 * statistics message and stay under their own names; this meter never touches USB. The feeder
 * thread is the only writer; {@link #percent()} may be called from the host thread.</p>
 */
public final class QualityMeter {

    public static final int TS_PACKET = 188;
    public static final int NULL_PID = 0x1FFF;

    private static final class Entry {
        final long when;
        final long clean;
        final long total;

        Entry(long when, long clean, long total) {
            this.when = when;
            this.clean = clean;
            this.total = total;
        }
    }

    private final long windowNanos;
    private final ArrayDeque<Entry> entries = new ArrayDeque<>();
    private final HashMap<Integer, Integer> lastCc = new HashMap<>();
    private long startNanos = -1;
    private long clean;
    private long total;

    public QualityMeter() {
        this(5.0);
    }

    public QualityMeter(double windowSeconds) {
        windowNanos = (long) (Math.max(0.1, windowSeconds) * 1e9);
    }

    /** Counts one buffer of whole packets, timestamped now. */
    public synchronized void feed(byte[] data) {
        feed(data, System.nanoTime());
    }

    /** Same, with an explicit clock for tests. */
    synchronized void feed(byte[] data, long nowNanos) {
        if (data == null) {
            return;
        }
        int limit = data.length - data.length % TS_PACKET;
        if (limit <= 0) {
            return;
        }
        if (startNanos < 0) {
            startNanos = nowNanos;
        }
        long addedClean = 0;
        long addedTotal = 0;
        for (int offset = 0; offset < limit; offset += TS_PACKET) {
            if ((data[offset] & 0xFF) != 0x47) {
                continue;
            }
            int pid = ((data[offset + 1] & 0x1F) << 8) | (data[offset + 2] & 0xFF);
            if (pid == NULL_PID) {
                continue;
            }
            int afc = (data[offset + 3] >> 4) & 0x3;
            if (afc == 0 || afc == 2) {  // reserved, or adaptation field only
                continue;
            }
            addedTotal++;
            if ((data[offset + 1] & 0x80) != 0) {  // transport_error_indicator
                continue;
            }
            int cc = data[offset + 3] & 0x0F;
            Integer last = lastCc.put(pid, cc);
            if (last != null && cc != last && cc != ((last + 1) & 0x0F)) {
                continue;
            }
            addedClean++;
        }
        clean += addedClean;
        total += addedTotal;
        entries.addLast(new Entry(nowNanos, addedClean, addedTotal));
        purge(nowNanos);
    }

    private void purge(long now) {
        long cutoff = now - windowNanos;
        while (!entries.isEmpty() && entries.peekFirst().when < cutoff) {
            Entry entry = entries.removeFirst();
            clean -= entry.clean;
            total -= entry.total;
        }
    }

    /** 0-100, or -1.0 before the first full window or with no counted packet. */
    public synchronized double percent() {
        return percentAt(System.nanoTime());
    }

    /** Same as {@link #percent()}, with an explicit clock for tests. */
    synchronized double percentAt(long nowNanos) {
        purge(nowNanos);
        if (total <= 0 || startNanos < 0 || nowNanos - startNanos < windowNanos) {
            return -1.0;
        }
        return 100.0 * clean / total;
    }

    public synchronized long clean() {
        return clean;
    }

    public synchronized long total() {
        return total;
    }

    public synchronized void reset() {
        entries.clear();
        lastCc.clear();
        startNanos = -1;
        clean = 0;
        total = 0;
    }
}
