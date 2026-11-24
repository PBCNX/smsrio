// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

import java.util.concurrent.BlockingQueue;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.TimeUnit;

/**
 * Siano SMS-series Rio ({@code 187f:0600}) user-space driver.
 *
 * <p>Owns the bulk-IN endpoint: one reader thread takes the stream, one feeder thread hands whole
 * 188-byte packets to the {@link Listener}. Replies, statistics and the stream share the endpoint,
 * so every control request is serialized with the reader through one lock.</p>
 *
 * <p>Statistics are <b>not</b> polled during playback: a 500 ms poll measured 5-10 CC per 10 s on
 * the 2026-11-04 DTA-115 run, while no-poll captures were 0/0. The host asks
 * {@link #readStatus()} when it is not streaming and keeps {@link #status()} for the UI.</p>
 *
 * <p>This core imports no Android or host class; the Android adapter supplies {@link Transport}.
 * The provenance marker is {@link #PROVENANCE} - visible attribution, never telemetry.</p>
 *
 * <p>Quality is the shared packet metric ({@link QualityMeter}: 5 s window, TEI/CC-based); the
 * firmware's own SNR and RSSI stay under their names, and the SNR-derived percentage is kept in
 * {@link Status#snrQualityPercent} for a host that wants it.</p>
 */
public final class SmsRio {

    /** Visible provenance/attribution string; no network, no device identifier, no protocol bytes. */
    public static final String PROVENANCE = "smsrio-pbcnx";

    public static final int VID = 0x187F;
    public static final int PID = 0x0600;

    private static final int TS_PACKET = 188;
    /**
     * About 240 KB of stream (64 x 3,760 bytes): roughly 110 ms at the 17.3 Mbps DTA-115 mux,
     * enough to ride out a slow consumer without stalling the USB read.
     */
    private static final int QUEUE_CHUNKS = 64;

    private final Transport transport;
    private final SmsRioDevice device;
    private final Log log;
    private final QualityMeter quality = new QualityMeter(5.0);
    private final Object ioLock = new Object();
    private final BlockingQueue<byte[]> queue = new LinkedBlockingQueue<>(QUEUE_CHUNKS);
    private final Status live = new Status();

    private volatile Listener listener;
    private volatile Status snapshot;
    private volatile boolean ready;
    private volatile boolean running;
    private volatile boolean paused;
    private volatile boolean stoppedByCaller;
    private volatile int currentKhz;
    private volatile String lastError;
    private volatile long packets;
    private volatile long dropped;
    private volatile long badSync;

    private Thread reader;
    private Thread feeder;

    public SmsRio(Transport transport, Log log) {
        this.transport = transport;
        this.device = new SmsRioDevice(transport);
        this.log = log == null ? Log.NONE : log;
    }

    public String name() {
        return "Siano SMS-series Rio";
    }

    public boolean isReady() {
        return ready;
    }

    public int currentKhz() {
        return currentKhz;
    }

    public String lastError() {
        return lastError;
    }

    public long packets() {
        return packets;
    }

    /** Chunks dropped because the bounded queue was full (stale stream, never silent). */
    public long dropped() {
        return dropped;
    }

    /** Stream payloads thrown away because they were not a whole number of TS packets. */
    public long badSync() {
        return badSync;
    }

    /** The last meter snapshot, or null before the first read. Quality is live. */
    public Status status() {
        Status base = snapshot;
        if (base == null) {
            return null;
        }
        Status copy = new Status();
        copy.copyFrom(base);
        double percent = quality.percent();
        copy.qualityPercent = percent < 0 ? -1 : (int) Math.round(percent);
        return copy;
    }

    /**
     * Brings the device up (cold: uploads the vendor image; warm: skips it) and selects ISDB-T BDA
     * mode. The reader starts on the first {@link #tune(int)}, not here.
     */
    public synchronized boolean start(byte[] firmwareImage, Listener target) {
        if (ready) {
            return true;
        }
        listener = target;
        lastError = null;
        try {
            String version = device.bringUp(firmwareImage);
            device.addPid(0x2000);
            log.info("firmware: " + version);
            ready = true;
            return true;
        } catch (RuntimeException error) {
            lastError = "bring-up failed: " + error.getMessage();
            if (target != null) {
                target.onError(lastError);
            }
            return false;
        }
    }

    /** Tunes kHz, waits up to 5 s for demod lock, then starts the reader and feeder threads. */
    public synchronized boolean tune(int khz) {        if (!ready) {
            lastError = "not started";
            return false;
        }
        pauseReader();
        try {
            boolean locked = false;
            synchronized (ioLock) {
                device.tune(khz);
                long deadline = System.currentTimeMillis() + 5000;
                while (System.currentTimeMillis() < deadline) {
                    Status status = readStatusLocked();
                    if (status.locked) {
                        locked = true;
                        break;
                    }
                    sleep(300);
                }
            }
            currentKhz = khz;
            lastError = locked ? null : "no lock on " + khz + " kHz";
            startReader();
            return locked;
        } catch (RuntimeException error) {
            lastError = "tune failed: " + error.getMessage();
            return false;
        } finally {
            paused = false;
        }
    }

    /**
     * State-3 recovery: warm re-init ({@link SmsRioDevice#reinit()}: set_mode only, no version
     * probe, no upload), then re-tune the last frequency.
     *
     * <p>Why no probe and no forced image: measured 2026-11-20 on the Pi, a version probe that
     * times out reads as "blank ROM" and an upload over a warm chip restarts the firmware and
     * leaves it unresponsive to the next tune. The image belongs to the fresh-handle path, where
     * the chip really did come back blank.
     */
    public synchronized boolean recover(byte[] firmwareImage) {
        pauseReader();
        try {
            synchronized (ioLock) {
                device.reinit();
            }
            ready = true;
            log.info("recovered: warm re-init");
        } catch (RuntimeException error) {
            lastError = "recover failed: " + error.getMessage();
            return false;
        } finally {
            paused = false;
        }
        return currentKhz > 0 ? tune(currentKhz) : true;
    }

    /**
     * One statistics read. USB work, so the host calls it when it is not playing; it blocks the
     * reader for the length of the request.
     */
    public Status readStatus() {
        synchronized (ioLock) {
            return readStatusLocked();
        }
    }

    /** TMCC from the same 653 message the statistics use; null when the reply is too short. */
    public Tmcc tmcc() {
        synchronized (ioLock) {
            return device.tmcc();
        }
    }

    /**
     * The family's settled codeword: TMCC read twice, and only the second returned when the two
     * agree. A transient after a switch must not become a display - it returns null instead, and
     * the caller says why ("did not settle") rather than showing a channel it is not on.
     */
    public Tmcc tmccSettled() {
        Tmcc first = tmcc();
        if (first == null || !first.valid) {
            return null;
        }
        Tmcc second = tmcc();
        if (second == null || !second.valid) {
            return null;
        }
        return first.sameChannel(second) ? second : null;
    }

    private Status readStatusLocked() {
        SmsRioDevice.Statistics stats = device.statistics();
        live.locked = stats.demodLocked;
        live.snrDb = stats.snr;
        live.rawStrength = stats.rssi;
        live.dbm = stats.power;
        live.strengthPercent = clamp(100 + stats.power);
        live.snrQualityPercent = clamp(stats.snr * 10);
        double qualityPercent = quality.percent();
        live.qualityPercent = qualityPercent < 0 ? -1 : (int) Math.round(qualityPercent);
        Status copy = new Status();
        copy.copyFrom(live);
        snapshot = copy;
        return copy;
    }

    /** Stops the threads and leaves the USB handle open, so a later tune can reuse it. */
    public synchronized void stop() {
        stoppedByCaller = true;
        running = false;
        paused = true;
        Thread r = reader;
        Thread f = feeder;
        reader = null;
        feeder = null;
        join(r);
        join(f);
        queue.clear();
        ready = false;
    }

    /** Stops the threads and releases the USB handle. Safe to call twice. */
    public void close() {
        stop();
        transport.close();
    }

    public String counters() {
        return "packets " + packets + ", dropped " + dropped + ", badSync " + badSync;
    }

    private void startReader() {
        if (running) {
            return;
        }
        running = true;
        stoppedByCaller = false;
        reader = new Thread(this::readerLoop, "SmsRio-USB");
        feeder = new Thread(this::feedLoop, "SmsRio-Feed");
        reader.start();
        feeder.start();
    }

    private void pauseReader() {
        paused = true;
        synchronized (ioLock) {
            // wait for a read in flight; the reader re-checks paused under the lock
        }
    }

    /**
     * USB reader: never parses. Payloads go to the bounded queue; a full queue drops the oldest
     * chunk and counts it, so a slow consumer cannot stall the endpoint.
     */
    private void readerLoop() {
        while (running) {
            if (paused) {
                sleep(20);
                continue;
            }
            byte[] payload;
            synchronized (ioLock) {
                if (paused) {
                    continue;
                }
                payload = device.nextTs(500);
            }
            if (payload == null) {
                continue;
            }
            if (payload.length == 0 || payload.length % TS_PACKET != 0 || payload[0] != 0x47) {
                badSync++;
                continue;
            }
            if (!queue.offer(payload)) {
                queue.poll();
                queue.offer(payload);
                dropped++;
            }
        }
    }

    private void feedLoop() {
        while (running) {
            byte[] payload;
            try {
                payload = queue.poll(100, TimeUnit.MILLISECONDS);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
                break;
            }
            if (payload == null) {
                continue;
            }
            quality.feed(payload);
            Listener target = listener;
            if (target != null) {
                packets += payload.length / TS_PACKET;
                target.onData(payload, payload.length);
            }
        }
        Listener target = listener;
        if (target != null && !stoppedByCaller) {
            target.onEnd();
        }
    }

    private static int clamp(int value) {
        return Math.max(0, Math.min(100, value));
    }

    private static void join(Thread thread) {
        if (thread == null) {
            return;
        }
        try {
            thread.join(1500);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
        }
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
        }
    }
}
