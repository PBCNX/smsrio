// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

/** Small logging seam: the host maps it to its own log, the JVM build to nothing. */
public interface Log {

    void info(String message);

    Log NONE = message -> {
    };
}
