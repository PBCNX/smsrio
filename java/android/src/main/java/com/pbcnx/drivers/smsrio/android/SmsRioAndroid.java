// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio.android;

import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbManager;

import com.pbcnx.drivers.smsrio.SmsRio;

/** Android entry point: opens the device and returns a ready-to-start {@link SmsRio}. */
public final class SmsRioAndroid {

    private SmsRioAndroid() {
    }

    /**
     * Opens the stick over Android's USB host API. The caller must already hold the USB
     * permission for {@code device}; pass the returned driver to the host's source wrapper.
     */
    public static SmsRio open(UsbManager manager, UsbDevice device) {
        UsbTransport transport = UsbTransport.open(manager, device);
        return new SmsRio(transport, message -> android.util.Log.i("SmsRio", message));
    }
}
