// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio.android;

import android.hardware.usb.UsbConstants;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
import android.hardware.usb.UsbManager;

import java.util.Arrays;

import com.pbcnx.drivers.smsrio.Transport;

/**
 * Android's USB host API as a {@link Transport}: one {@code UsbDeviceConnection} for every
 * transfer.
 *
 * <p>No root and no {@code /dev/bus/usb}: the app framework grants the device through its own
 * permission flow, and this class assumes that permission was already granted. The endpoints are
 * the Siano ones: bulk OUT {@code 0x02} for commands and bulk IN {@code 0x81} for replies and the
 * TS stream.</p>
 */
public final class UsbTransport implements Transport {

    private static final int EP_OUT = 0x02;
    private static final int EP_IN = 0x81;
    private static final int CLEAR_FEATURE = 0x01;
    private static final int ENDPOINT_HALT = 0x00;
    private static final int TIMEOUT_MS = 1000;

    private final UsbDeviceConnection connection;
    private final UsbInterface claimed;
    private final UsbEndpoint out;
    private final UsbEndpoint in;
    private volatile boolean closed;

    private UsbTransport(UsbDeviceConnection connection, UsbInterface claimed,
                         UsbEndpoint out, UsbEndpoint in) {
        this.connection = connection;
        this.claimed = claimed;
        this.out = out;
        this.in = in;
    }

    /** Opens and claims the device. The caller must already hold the USB permission. */
    public static UsbTransport open(UsbManager manager, UsbDevice device) {
        if (device == null) {
            throw new IllegalStateException("no USB device");
        }
        UsbDeviceConnection connection = manager.openDevice(device);
        if (connection == null) {
            throw new IllegalStateException("openDevice() failed (no USB permission?)");
        }
        // Logged, not configured: setting the configuration on a device the framework already
        // configured can disturb the endpoints, and "unconfigured" is a guess, not a measurement.
        // The claim and the two clear_halts below are the documented path.
        android.util.Log.i("SmsRio", "usb: open " + device.getDeviceName() + " "
                + device.getVendorId() + ":" + device.getProductId()
                + " interfaces " + device.getInterfaceCount());
        UsbEndpoint out = null;
        UsbEndpoint in = null;
        UsbInterface claimed = null;
        for (int index = 0; index < device.getInterfaceCount(); index++) {
            UsbInterface candidate = device.getInterface(index);
            UsbEndpoint candidateOut = null;
            UsbEndpoint candidateIn = null;
            for (int e = 0; e < candidate.getEndpointCount(); e++) {
                UsbEndpoint endpoint = candidate.getEndpoint(e);
                if (endpoint.getType() != UsbConstants.USB_ENDPOINT_XFER_BULK) {
                    continue;
                }
                if (endpoint.getDirection() == UsbConstants.USB_DIR_OUT
                        && endpoint.getAddress() == EP_OUT) {
                    candidateOut = endpoint;
                }
                if (endpoint.getDirection() == UsbConstants.USB_DIR_IN
                        && endpoint.getAddress() == EP_IN) {
                    candidateIn = endpoint;
                }
            }
            if (candidateOut == null || candidateIn == null) {
                continue;
            }
            if (!connection.claimInterface(candidate, true)) {
                connection.close();
                throw new IllegalStateException("claimInterface(" + candidate.getId() + ") failed");
            }
            claimed = candidate;
            out = candidateOut;
            in = candidateIn;
            break;
        }
        if (claimed == null) {
            connection.close();
            throw new IllegalStateException("bulk endpoints 0x02 OUT / 0x81 IN not found");
        }
        UsbTransport transport = new UsbTransport(connection, claimed, out, in);
        android.util.Log.i("SmsRio", "usb: claimed interface " + claimed.getId()
                + " out 0x" + Integer.toHexString(out.getAddress())
                + " in 0x" + Integer.toHexString(in.getAddress())
                + " fd " + connection.getFileDescriptor());
        // The working Android driver cleared both halts on open; a cancelled bulk read on Windows
        // leaves the pipe stalled, and the same recovery is valid here.
        transport.clearHalt(out.getAddress());
        transport.clearHalt(in.getAddress());
        return transport;
    }

    @Override
    public void write(byte[] data, int timeoutMs) {
        if (closed) {
            throw new IllegalStateException("transport closed");
        }
        int sent = connection.bulkTransfer(out, data, data.length, timeoutMs);
        if (sent != data.length) {
            // -1 on the first write of a session has one friendly cause worth one retry: a halted
            // OUT endpoint left by a previous holder of the device. Clear it and try once more
            // before failing the bring-up (a host's 2026-11-23 report: bulk OUT -1 of 252).
            android.util.Log.w("SmsRio", "usb: bulk OUT " + sent + " of " + data.length
                    + " on 0x" + Integer.toHexString(out.getAddress())
                    + " - clearing the halt, retrying once");
            clearHalt(out.getAddress());
            try {
                Thread.sleep(50);
            } catch (InterruptedException interrupted) {
                Thread.currentThread().interrupt();
            }
            sent = connection.bulkTransfer(out, data, data.length, timeoutMs);
        }
        if (sent != data.length) {
            throw new IllegalStateException("bulk OUT " + sent + " of " + data.length
                    + " (endpoint 0x" + Integer.toHexString(out.getAddress())
                    + ", fd " + connection.getFileDescriptor() + ")");
        }
    }

    @Override
    public byte[] read(int maxLength, int timeoutMs) {
        if (closed) {
            return null;
        }
        byte[] buffer = new byte[maxLength];
        int count = connection.bulkTransfer(in, buffer, buffer.length, timeoutMs);
        if (count <= 0) {
            return null;
        }
        return Arrays.copyOf(buffer, count);
    }

    @Override
    public void close() {
        if (closed) {
            return;
        }
        closed = true;
        try {
            connection.releaseInterface(claimed);
        } catch (RuntimeException ignored) {
            // the device may already be gone
        }
        try {
            connection.close();
        } catch (RuntimeException ignored) {
            // as above
        }
    }

    private void clearHalt(int endpoint) {
        try {
            connection.controlTransfer(0x02, CLEAR_FEATURE, ENDPOINT_HALT, endpoint,
                    null, 0, TIMEOUT_MS);
        } catch (RuntimeException ignored) {
            // not fatal: the transfer still runs without a cleared halt
        }
    }
}


