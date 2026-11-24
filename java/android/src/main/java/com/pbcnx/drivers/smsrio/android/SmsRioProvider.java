// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio.android;

import android.content.Context;
import android.hardware.usb.UsbDevice;

import com.pbcnx.drivers.smsrio.Listener;
import com.pbcnx.tuner.TsReader;
import com.pbcnx.tuner.Tuner;
import com.pbcnx.tuner.TunerProvider;

/**
 * The door's provider: the one class a host loads.
 *
 * <p>{@code open(Context, UsbDevice, byte[] firmware, TsReader.Listener)} returns a {@link Tuner}; it does
 * not claim the device - {@link Tuner#open()} does, and that is the door's only throwing method. The image is
 * required for a blank chip (the Siano loses its firmware on every replug) and ignored when the unit is warm.</p>
 */
public final class SmsRioProvider implements TunerProvider {

    @Override
    public Tuner open(Context context, UsbDevice device, byte[] firmware, TsReader.Listener listener) {
        Listener sink = listener == null ? null : new Listener() {
            @Override
            public void onData(byte[] ts, int length) {
                listener.onData(ts, length);
            }

            @Override
            public void onError(String reason) {
                android.util.Log.w("SmsRio", reason == null ? "stream error" : reason);
            }

            @Override
            public void onEnd() {
            }
        };
        return new SmsRioTuner(context, device, firmware, sink);
    }
}
