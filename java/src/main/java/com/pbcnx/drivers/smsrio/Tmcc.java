// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

/**
 * ISDB-T TMCC as the Siano's 653 statistics message reports it.
 *
 * <p>The demod has already parsed TMCC: these are the demod's own values, not a register block we
 * decode. Layout from the kernel {@code struct sms_isdbt_stats_ex} (GPL-2.0-or-later) and the
 * layer blocks, validated against the live 479/485/497 records (2026-11-20) and the the reference set / IT9308
 * reference set. Unknown stays {@code null} in the labels, never 0.</p>
 *
 * <p>The family validity gate (the IT9175 zero trap): an undecoded block reads as zeros, which
 * decodes into a plausible 2K / 1/32 picture with no layers. A reading is a channel only when the
 * mode and guard are known and 1..13 segments are claimed by present layers.</p>
 */
public final class Tmcc {

    public static final int MODE = 12;
    public static final int MODEM_STATE = 13;
    public static final int GUARD = 14;
    public static final int SYSTEM = 15;
    public static final int PARTIAL = 16;
    public static final int LAYERS = 17;
    public static final int SEGMENTS = 18;
    public static final int TUNE_BW = 19;
    public static final int LAYER_BASE = 20;
    public static final int LAYER_STRIDE = 12;
    /** ews_alert_active: present on the Siano's 653, absent on some siblings. */
    public static final int EWS = 59;

    private static final int CODE_RATE = 0;
    private static final int CONSTELLATION = 1;
    private static final int BER = 2;
    private static final int TI_LDEPTH_I = 9;
    private static final int NUMBER_OF_SEGMENTS = 10;
    private static final int TMCC_ERRORS = 11;
    private static final int UNUSED = 255;

    public final int mode;
    public final int guard;
    public final boolean partial;
    public final int numLayers;
    public final int segmentNumber;
    public final boolean valid;
    public final Boolean ews;
    public final Layer[] layers;

    /** One layer's TMCC block; {@code present} is the demod's "this layer exists" word. */
    public static final class Layer {
        public final int index;
        public final int codeRate;
        public final int constellation;
        public final int ber;
        public final int interleaving;
        public final int segments;
        public final int tmccErrors;
        public final boolean present;

        Layer(int index, int codeRate, int constellation, int ber, int interleaving,
              int segments, int tmccErrors, boolean present) {
            this.index = index;
            this.codeRate = codeRate;
            this.constellation = constellation;
            this.ber = ber;
            this.interleaving = interleaving;
            this.segments = segments;
            this.tmccErrors = tmccErrors;
            this.present = present;
        }
    }

    private Tmcc(int mode, int guard, boolean partial, int numLayers, int segmentNumber,
                 boolean valid, Boolean ews, Layer[] layers) {
        this.mode = mode;
        this.guard = guard;
        this.partial = partial;
        this.numLayers = numLayers;
        this.segmentNumber = segmentNumber;
        this.valid = valid;
        this.ews = ews;
        this.layers = layers;
    }

    /** Parses the 654 body; null when it is too short to carry TMCC. */
    public static Tmcc parse(byte[] body) {
        if (body == null || body.length < 20 * 4) {
            return null;
        }
        int mode = SmsProtocol.word(body, MODE);
        int guard = SmsProtocol.word(body, GUARD);
        int numLayers = SmsProtocol.word(body, LAYERS);
        Layer[] layers = new Layer[3];
        int claimed = 0;
        for (int index = 0; index < 3; index++) {
            int base = LAYER_BASE + index * LAYER_STRIDE;
            if (base * 4 + LAYER_STRIDE * 4 > body.length) {
                layers[index] = null;
                continue;
            }
            int codeRate = SmsProtocol.word(body, base + CODE_RATE);
            int constellation = SmsProtocol.word(body, base + CONSTELLATION);
            int interleaving = SmsProtocol.word(body, base + TI_LDEPTH_I);
            int segments = SmsProtocol.word(body, base + NUMBER_OF_SEGMENTS);
            boolean present = codeRate != UNUSED && segments > 0 && index < numLayers;
            if (present) {
                claimed += segments;
            }
            layers[index] = new Layer(index, codeRate, constellation,
                    SmsProtocol.word(body, base + BER), interleaving, segments,
                    SmsProtocol.word(body, base + TMCC_ERRORS), present);
        }
        Boolean ews = null;
        boolean valid = modeLabel(mode) != null && guardLabel(guard) != null
                && claimed >= 1 && claimed <= 13;
        if (valid && (EWS + 1) * 4 <= body.length) {
            ews = SmsProtocol.word(body, EWS) != 0;
        }
        return new Tmcc(mode, guard, SmsProtocol.word(body, PARTIAL) != 0, numLayers,
                SmsProtocol.word(body, SEGMENTS), valid, ews, layers);
    }

    public static String modeLabel(int mode) {
        switch (mode) {
            case 1: return "2K";
            case 2: return "4K";
            case 3: return "8K";
            default: return null;
        }
    }

    public static String guardLabel(int guard) {
        switch (guard) {
            case 1: return "1/32";
            case 2: return "1/16";
            case 3: return "1/8";
            case 4: return "1/4";
            default: return null;
        }
    }

    public static String constellationLabel(int value) {
        switch (value) {
            case 0: return "QPSK";
            case 1: return "16QAM";
            case 2: return "64QAM";
            case 3: return "DQPSK";
            default: return null;
        }
    }

    public static String codeRateLabel(int value) {
        switch (value) {
            case 0: return "1/2";
            case 1: return "2/3";
            case 2: return "3/4";
            case 3: return "5/6";
            case 4: return "7/8";
            default: return null;
        }
    }

    public static String interleaveLabel(int value) {
        switch (value) {
            case 0: return "I0";
            case 1: return "I1";
            case 2: return "I2";
            case 4: return "I4";
            default: return null;
        }
    }

    /** True when two readings describe the same channel layout (the "settled" comparison). */
    public boolean sameChannel(Tmcc other) {
        if (other == null || mode != other.mode || guard != other.guard
                || partial != other.partial || numLayers != other.numLayers) {
            return false;
        }
        for (int index = 0; index < layers.length; index++) {
            Layer mine = layers[index];
            Layer theirs = other.layers[index];
            if (mine == null || theirs == null) {
                if (mine != theirs) {
                    return false;
                }
                continue;
            }
            if (mine.present != theirs.present || mine.segments != theirs.segments
                    || mine.codeRate != theirs.codeRate
                    || mine.constellation != theirs.constellation
                    || mine.interleaving != theirs.interleaving) {
                return false;
            }
        }
        return true;
    }

    /** An unknown label prints "?" like the Python side, never the word null. */
    private static String orQuestion(String label) {
        return label == null ? "?" : label;
    }

    /** One display line: label and index together, never a bare number. */
    public String line(int khz) {
        if (!valid) {
            return khz + " kHz tmcc not decoded yet (no layer segments - the demod has not "
                    + "decoded TMCC on this channel)";
        }
        StringBuilder text = new StringBuilder();
        text.append(khz).append(" kHz tmcc mode ").append(modeLabel(mode))
                .append(" (").append(mode).append(") guard ").append(guardLabel(guard))
                .append(" (").append(guard).append(") partial ").append(partial ? 1 : 0)
                .append(" layers ").append(numLayers);
        if (ews != null) {
            text.append(" ews ").append(ews ? 1 : 0);
        }
        for (Layer layer : layers) {
            if (layer == null || !layer.present) {
                continue;
            }
            text.append(" L").append(layer.index).append(':')
                    .append(orQuestion(constellationLabel(layer.constellation))).append(' ')
                    .append(layer.segments).append("seg code ")
                    .append(orQuestion(codeRateLabel(layer.codeRate))).append(" (")
                    .append(layer.codeRate).append(") ")
                    .append(orQuestion(interleaveLabel(layer.interleaving)));
        }
        return text.toString();
    }
}


