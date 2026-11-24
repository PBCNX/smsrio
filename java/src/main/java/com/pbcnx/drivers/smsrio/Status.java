// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

/** Demodulator measurements; the host maps this to its own meter struct. */
public final class Status {

    public boolean locked;

    /**
     * Driver-specific raw strength. On this line it is RSSI in dBm; another line may put a raw
     * register word here, so the host must not assume one unit - {@link #strengthPercent} is the
     * comparable value.
     */
    public int rawStrength = -1;

    /** 0-100, from the in-band power. */
    public int strengthPercent = -1;

    /** Shared quality metric: 0-100 over the 5 s window, or -1 before the first full window. */
    public int qualityPercent = -1;

    /** The older SNR-derived quality (0-100), kept under its own name. */
    public int snrQualityPercent = -1;

    /** dB; NaN before the first read. */
    public double snrDb = Double.NaN;

    /** In-band power, dBm; {@link Integer#MIN_VALUE} when unknown (the host's sentinel). */
    public int dbm = Integer.MIN_VALUE;

    public void copyFrom(Status other) {
        locked = other.locked;
        rawStrength = other.rawStrength;
        strengthPercent = other.strengthPercent;
        qualityPercent = other.qualityPercent;
        snrQualityPercent = other.snrQualityPercent;
        snrDb = other.snrDb;
        dbm = other.dbm;
    }
}
