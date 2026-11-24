// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

/** What the driver reports back to its host. */
public interface Listener {

    /** Whole 188-byte packets, already aligned; valid only for the duration of the call. */
    void onData(byte[] ts, int length);

    /** Bring-up, tune or the stream failed; the driver keeps running where it can. */
    void onError(String reason);

    /** The stream ended by itself, not because the host called stop(). */
    void onEnd();
}
