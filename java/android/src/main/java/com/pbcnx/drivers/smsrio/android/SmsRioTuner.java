// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio.android;

import android.content.Context;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;

import com.pbcnx.drivers.smsrio.Listener;
import com.pbcnx.drivers.smsrio.SmsRio;
import com.pbcnx.drivers.smsrio.Status;
import com.pbcnx.tuner.ScanListener;
import com.pbcnx.tuner.Tmcc;
import com.pbcnx.tuner.Tuner;
import com.pbcnx.tuner.TunerException;
import com.pbcnx.tuner.TunerStatus;

/**
 * The Siano Rio behind the door ({@code com.pbcnx.tuner.contract:1.0.0}).
 *
 * <p>One call maps to one {@link SmsRio} call. The two translations worth knowing:</p>
 *
 * <ul>
 *   <li><b>TMCC</b>: the core keeps the demod's own numbering (mode 1/2/3, guard 1..4, interleaving is a
 *       <em>depth</em> 0/1/2/4). The door's record is canonical: mode 0/1/2, guard 0..3, interleaving an
 *       <em>index</em> (3 = I4). The conversion is here, once.</li>
 *   <li><b>reader arming</b>: the core arms its reader on the first {@code tune()}, not in {@code open()}
 *       (measured: 1,021 ms to the first lock on a phone, 907-1,024 ms per zap). The door's optional
 *       {@code start()} is therefore a no-op, and {@code open()} only does the bring-up.</li>
 * </ul>
 *
 * <p>{@code resume(UsbDevice)} is the state-2 path, and on this chip it is a <b>cold</b> chip: the Siano
 * loses its firmware on every replug, so the image is uploaded there before the first tune
 * (TUNER-CONTRACT 1.4, the clause this line added).</p>
 */
public final class SmsRioTuner implements Tuner {

    private final Context context;
    private final byte[] firmware;
    private final Listener sink;
    private final int[] lastKhz = { 0 };

    private UsbDevice device;
    private UsbManager manager;
    private SmsRio driver;

    public SmsRioTuner(Context context, UsbDevice device, byte[] firmware, Listener sink) {
        this.context = context;
        this.device = device;
        this.firmware = firmware;
        this.sink = sink;
    }

    /** The door's only throwing method: claim the device, bring the chip up (upload only when blank). */
    @Override
    public void open() throws TunerException {
        if (driver != null) {
            throw new TunerException("already open");
        }
        manager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
        if (manager == null) {
            throw new TunerException("no UsbManager on this context");
        }
        if (device == null) {
            throw new TunerException("no Siano device (187f:0600)");
        }
        if (!manager.hasPermission(device)) {
            throw new TunerException("USB permission not held for " + device.getDeviceName());
        }
        SmsRio opened;
        try {
            opened = SmsRioAndroid.open(manager, device);
        } catch (RuntimeException error) {
            throw new TunerException("cannot open " + device.getDeviceName(), error);
        }
        if (!opened.start(firmware, sink)) {
            String reason = opened.lastError();
            opened.close();
            throw new TunerException("bring-up failed: " + reason);
        }
        driver = opened;
    }

    @Override
    public boolean tune(int khz) {
        SmsRio current = driver;
        if (current == null) {
            return false;
        }
        boolean locked = current.tune(khz);
        if (locked) {
            lastKhz[0] = khz;
        }
        return locked;
    }

    /** A channel change on the live handle: the same path as {@link #tune(int)} - no bring-up. */
    @Override
    public boolean zap(int khz) {
        return tune(khz);
    }

    @Override
    public TunerStatus status() {
        SmsRio current = driver;
        Status reading = current == null ? null : current.status();
        if (reading == null) {
            return new TunerStatus(false, -1, -1, -1);
        }
        int snr = Double.isNaN(reading.snrDb) ? -1 : (int) Math.round(reading.snrDb);
        return new TunerStatus(reading.locked, reading.strengthPercent,
                reading.qualityPercent, snr);
    }

    @Override
    public Tmcc tmcc() {
        SmsRio current = driver;
        return current == null ? null : canonical(current.tmcc());
    }

    @Override
    public Tmcc tmccSettled(int attempts, long delayMs) {
        for (int attempt = 0; attempt < Math.max(attempts, 1); attempt++) {
            SmsRio current = driver;
            if (current != null) {
                com.pbcnx.drivers.smsrio.Tmcc settled = current.tmccSettled();
                if (settled != null) {
                    return canonical(settled);
                }
            }
            if (attempt + 1 < attempts && delayMs > 0) {
                try {
                    Thread.sleep(delayMs);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                    return null;
                }
            }
        }
        return null;
    }

    /** The warm rung: re-init in place, never an upload. A blank chip is {@link #resume(UsbDevice)}'s job. */
    @Override
    public boolean recover() {
        SmsRio current = driver;
        return current != null && current.recover(firmware);
    }

    @Override
    public void suspend() {
        SmsRio current = driver;
        driver = null;
        if (current != null) {
            current.close();
        }
    }

    /**
     * The device returned: open the new handle, upload (this chip comes back blank), re-tune. Throws only
     * when the new handle cannot be opened or brought up.
     */
    @Override
    public boolean resume(UsbDevice renewed) throws TunerException {
        if (renewed == null) {
            throw new TunerException("resume needs the device from the attach broadcast");
        }
        if (manager == null) {
            manager = (UsbManager) context.getSystemService(Context.USB_SERVICE);
        }
        if (manager == null || !manager.hasPermission(renewed)) {
            throw new TunerException("permission not held for " + renewed.getDeviceName());
        }
        SmsRio rebuilt;
        try {
            rebuilt = SmsRioAndroid.open(manager, renewed);
        } catch (RuntimeException error) {
            throw new TunerException("cannot reopen " + renewed.getDeviceName(), error);
        }
        if (!rebuilt.start(firmware, sink)) {
            String reason = rebuilt.lastError();
            rebuilt.close();
            throw new TunerException("rebuild failed: " + reason);
        }
        device = renewed;
        driver = rebuilt;
        return lastKhz[0] == 0 || rebuilt.tune(lastKhz[0]);
    }

    /**
     * One channel at a time; the verdict is the STREAM (bytes arriving), not the lock word - the family rule.
     * The reader is armed by the first {@code tune()}; consecutive tunes re-arm it.
     */
    @Override
    public void scan(int startKhz, int stopKhz, int stepKhz, int secondsPerChannel, ScanListener listener) {
        if (stepKhz <= 0) {
            throw new IllegalArgumentException("step must be > 0");
        }
        int total = 0;
        int found = 0;
        for (int khz = startKhz; khz <= stopKhz; khz += stepKhz) {
            total++;
            boolean locked = tune(khz);
            long before = driver == null ? 0 : driver.packets();
            sleep(Math.max(1, secondsPerChannel) * 1000L);
            long after = driver == null ? 0 : driver.packets();
            boolean streamed = after > before;
            boolean verdict = locked && streamed;
            if (verdict) {
                found++;
            }
            if (listener != null) {
                listener.onFrequency(khz, verdict, status());
            }
        }
        if (listener != null) {
            listener.onDone(found, total);
        }
    }

    @Override
    public void close() {
        SmsRio current = driver;
        driver = null;
        if (current != null) {
            current.close();
        }
    }

    /** Depth (0/1/2/4) to index (0/1/2/3); anything else is unread (-1). */
    static int interleavingIndex(int depth) {
        switch (depth) {
            case 0: return 0;
            case 1: return 1;
            case 2: return 2;
            case 4: return 3;
            default: return -1;
        }
    }

    /** The core's record, in the door's canonical numbering. */
    static Tmcc canonical(com.pbcnx.drivers.smsrio.Tmcc record) {
        if (record == null) {
            return null;
        }
        Tmcc.Layer[] layers = new Tmcc.Layer[3];
        for (int index = 0; index < layers.length; index++) {
            com.pbcnx.drivers.smsrio.Tmcc.Layer source =
                    index < record.layers.length ? record.layers[index] : null;
            if (source == null || !source.present) {
                layers[index] = new Tmcc.Layer(0, -1, -1, -1);
                continue;
            }
            int codeRate = source.codeRate == 0xFF ? -1 : source.codeRate;
            layers[index] = new Tmcc.Layer(source.segments, source.constellation, codeRate,
                    interleavingIndex(source.interleaving));
        }
        int ewbs = record.ews == null ? -1 : (record.ews ? 1 : 0);
        int mode = record.valid ? record.mode - 1 : -1;
        int guard = record.valid ? record.guard - 1 : -1;
        return new Tmcc(mode, guard, record.partial, ewbs, layers);
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
        }
    }
}
