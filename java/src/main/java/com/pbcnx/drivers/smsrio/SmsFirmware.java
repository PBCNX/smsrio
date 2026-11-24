// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;

/**
 * Vendor firmware image handling for Siano Rio.
 *
 * The image ({@code isdbt_rio.inp}) starts with three little-endian words -
 * checksum, payload length and load address - followed by the payload. It is
 * vendor material: the driver never bundles it and the app supplies it.
 */
public final class SmsFirmware {
    public static final int HEADER = 12;
    public static final int SIZE = 91048;
    public static final int CHUNK = 240;
    /** SHA-256 of the exact 91,048-byte vendor image. */
    public static final String SHA256 =
            "777c9ba2ce44db9e0a90f7207167e9095cc0223be2b2af599f645f1c73d76b14";

    public final int checksum;
    public final int length;
    public final int address;

    SmsFirmware(int checksum, int length, int address) {
        this.checksum = checksum;
        this.length = length;
        this.address = address;
    }

    /** Parses and validates the header, exact size and SHA-256 of the image. */
    public static SmsFirmware parse(byte[] image) {
        if (image == null || image.length != SIZE) {
            throw new IllegalArgumentException(
                    "expected " + SIZE + " bytes, got " + (image == null ? -1 : image.length));
        }
        if (!SHA256.equalsIgnoreCase(sha256(image))) {
            throw new IllegalArgumentException("wrong isdbt_rio.inp SHA-256");
        }
        int checksum = SmsProtocol.word(image, 0);
        int length = SmsProtocol.word(image, 1);
        int address = SmsProtocol.word(image, 2);
        if (length != SIZE - HEADER) {
            throw new IllegalArgumentException("bad payload length " + length);
        }
        return new SmsFirmware(checksum, length, address);
    }

    /** Bytes of the payload, without the header. */
    public static byte[] payload(byte[] image) {
        SmsFirmware header = parse(image);
        byte[] payload = new byte[header.length];
        System.arraycopy(image, HEADER, payload, 0, header.length);
        return payload;
    }

    private static String sha256(byte[] image) {
        try {
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(image);
            StringBuilder out = new StringBuilder(digest.length * 2);
            for (byte value : digest) {
                out.append(String.format("%02x", value & 0xFF));
            }
            return out.toString();
        } catch (NoSuchAlgorithmException error) {
            throw new IllegalStateException("SHA-256 unavailable", error);
        }
    }
}
