// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

/** Byte transport implemented by the host (Android UsbDeviceConnection, tests). */
public interface Transport {
    void write(byte[] data, int timeoutMs);

    byte[] read(int maxLength, int timeoutMs);

    /** Releases the USB handle; the core calls it from {@link SmsRio#close()}. */
    default void close() {
    }
}
