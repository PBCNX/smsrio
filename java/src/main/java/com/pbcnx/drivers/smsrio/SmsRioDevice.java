// Copyright (C) 2026 The SMSRio Open Driver Authors
// SPDX-License-Identifier: GPL-2.0-or-later
// smsrio-pbcnx

package com.pbcnx.drivers.smsrio;

/**
 * Control-plane driver for Siano Rio. The app reads TS from the bulk endpoint
 * and can hand each transfer to {@link SmsStream}, or use {@link #nextTs} which
 * strips the Siano framing for it.
 *
 * <p>Replies, statistics and the stream all arrive on <em>one</em> bulk-IN
 * endpoint.  That makes this class single-reader: call {@link #nextTs} and
 * {@link #statistics()} from the same thread, or protect them with one lock in
 * the app.  Two threads reading the endpoint will each take transfers the other
 * wanted - a statistics reply consumed by the stream reader is simply lost, and
 * the poll then times out.
 */
public final class SmsRioDevice {
    /**
     * Visible provenance marker: searchable attribution, not telemetry. It
     * performs no network or device I/O and changes no protocol bytes.
     */
    public static final String PROVENANCE = "smsrio-pbcnx";

    /**
     * Replies arrive interleaved with stream transfers; keep what we skip.
     *
     * Big enough to hold a whole reply's worth of stream (a 2 s reply at 8 Mbps
     * can sit behind hundreds of transfers).  Overflow is counted in
     * {@link #droppedTransfers()}, never silent.
     */
    private static final int PENDING_LIMIT = 512;
    private static final int REQUEST_TIMEOUT_MS = 2000;

    private final Transport transport;
    private final int source;
    private final int alignment;
    private final java.util.ArrayDeque<SmsProtocol.Message> pending =
            new java.util.ArrayDeque<>();
    private int dropped;

    public SmsRioDevice(Transport transport) {
        this(transport, 0, SmsProtocol.DEFAULT_ALIGNMENT);
    }

    public SmsRioDevice(Transport transport, int source) {
        this(transport, source, SmsProtocol.DEFAULT_ALIGNMENT);
    }

    public SmsRioDevice(Transport transport, int source, int alignment) {
        this.transport = transport;
        this.source = source;
        this.alignment = alignment;
    }

    private void send(int type, byte[] payload) {
        transport.write(SmsProtocol.build(type, source, SmsProtocol.HIF_TASK, payload, 0), 2000);
    }

    private byte[] request(int type, byte[] payload, int expected) {
        return request(type, payload, expected, REQUEST_TIMEOUT_MS);
    }

    private byte[] request(int type, byte[] payload, int expected, int timeoutMs) {
        send(type, payload);
        // Wall-clock deadline.  Counting attempts used to give up on a busy
        // stream long before the timeout, which is exactly when the app polls
        // statistics - one poll every 500 ms while playing.
        long deadline = System.currentTimeMillis() + timeoutMs;
        while (true) {
            long remaining = deadline - System.currentTimeMillis();
            if (remaining <= 0) {
                break;
            }
            byte[] data = transport.read(16384, (int) Math.min(remaining, 250));
            if (data == null || data.length < 8) {
                continue;
            }
            SmsProtocol.Message message;
            try {
                message = SmsProtocol.parse(data, alignment);
            } catch (IllegalArgumentException error) {
                continue;
            }
            if (message.type == expected) {
                return message.payload;
            }
            if (pending.size() < PENDING_LIMIT) {
                pending.addLast(message);
            } else {
                dropped++;
            }
        }
        throw new IllegalStateException("no response to " + type);
    }

    public String version() {
        return version(REQUEST_TIMEOUT_MS);
    }

    /** Version with an explicit budget in ms; the retry after a lost first read uses a short one. */
    public String version(int timeoutMs) {
        byte[] payload = request(SmsProtocol.VERSION_REQ, new byte[0], SmsProtocol.VERSION_RES, timeoutMs);
        String text = new String(payload, java.nio.charset.StandardCharsets.US_ASCII);
        return text.replace("\0", "").trim();
    }

    /**
     * The chip's version, or "" only after a second read also fails.
     *
     * <p>The first request after an open can lose its reply on a warm chip: on the Pi (2026-11-20)
     * the first 0x01f7 read timed out at 2 s and the retry answered in 0.01 s. Reading that as
     * "blank ROM" makes {@link #bringUp} upload over a warm chip, which is the forced upload that
     * wedges this firmware. One cheap retry comes before the verdict, never after it.
     */
    private String versionOrBlank() {
        try {
            return version();
        } catch (RuntimeException first) {
            try {
                return version(1000);
            } catch (RuntimeException second) {
                return "";
            }
        }
    }

    public void setMode(int mode) {
        request(SmsProtocol.INIT_REQ, littleEndian(mode), SmsProtocol.INIT_RES);
    }

    public void setMode() {
        setMode(SmsProtocol.MODE_ISDBT_BDA);
    }

    /**
     * The warm rung of the recovery ladder: re-select the mode on the firmware already in RAM.
     *
     * <p>No version probe and no upload. After a TS-interface wedge the chip can stop answering
     * 0x01f7, and a failed probe is read as "blank ROM" - which uploads over a warm chip and wedges
     * it for real (measured on the Pi, 2026-11-20). A blank chip is the fresh-handle rung's job, and
     * only that rung uploads.
     */
    public void reinit() {
        setMode();
    }

    /**
     * Adds a PID filter. The firmware does not answer this request (Linux sends
     * it and carries on), so it is not a request/response round trip.
     */
    public void addPid(int pid) {
        send(SmsProtocol.ADD_PID_REQ, littleEndian(pid));
    }

    /**
     * Tunes to a centre frequency given in kHz. The wire field is Hz: a capture
     * of a working Linux run carries 599,143,000 for 599.143 MHz.
     */
    public void tune(int frequencyKhz) {
        request(SmsProtocol.TUNE_REQ,
                littleEndian(frequencyKhz * 1000, SmsProtocol.BW_ISDBT_13SEG, 12000000, 0),
                SmsProtocol.TUNE_RES);
    }

    /**
     * Brings a device up: reads the version, uploads the image when the unit
     * is cold (no answer or ROM firmware), then selects ISDB-T BDA mode.
     *
     * @param image vendor {@code isdbt_rio.inp}, or null to skip the upload
     * @return the version string reported after bring-up
     */
    public String bringUp(byte[] image) {
        return bringUp(image, false);
    }

    /**
     * Brings a device up. With {@code force} the image is uploaded even when the
     * resident firmware answers: that is the state-3 recovery, where the RAM
     * state is exactly what must be rebuilt. Without it, a warm unit skips the
     * upload.
     *
     * @param image vendor {@code isdbt_rio.inp}, or null to skip the upload
     * @param force true to upload over a resident firmware (the recovery path)
     * @return the version string reported after bring-up
     */
    public String bringUp(byte[] image, boolean force) {
        String version;
        try {
            version = versionOrBlank();
        } catch (RuntimeException error) {
            version = "";
        }
        if (force && image != null) {
            uploadFirmware(image);
            // The restarted firmware needs a moment before it answers; Python
            // waits 0.5 s here too. Reading too early looked like "ROM".
            try {
                Thread.sleep(500);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
            }
            version = version();
        } else if (version.isEmpty() || version.toUpperCase().contains("ROM")) {
            if (image == null) {
                throw new IllegalStateException(
                        "cold device needs the vendor isdbt_rio.inp image");
            }
            uploadFirmware(image);
            // The restarted firmware needs a moment before it answers; Python
            // waits 0.5 s here too. Reading too early looked like "ROM".
            try {
                Thread.sleep(500);
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
            }
            version = version();
        }
        setMode();
        return version;
    }

    /**
     * Uploads the firmware image: data chunks, validity, trigger.  Mirrors the
     * Linux family-2 loader; the device restarts itself afterwards and answers
     * the version request with the new firmware string.
     */
    public void uploadFirmware(byte[] image) {
        SmsFirmware head = SmsFirmware.parse(image);
        byte[] payload = SmsFirmware.payload(image);
        uploadPayload(head, payload);
    }

    /** Upload sequence after validation; package-private so SelfTest can fake
     *  the header/payload without a vendor image. */
    void uploadPayload(SmsFirmware head, byte[] payload) {
        int address = head.address;
        for (int offset = 0; offset < payload.length; offset += SmsFirmware.CHUNK) {
            int size = Math.min(SmsFirmware.CHUNK, payload.length - offset);
            byte[] body = new byte[4 + size];
            body[0] = (byte) address;
            body[1] = (byte) (address >> 8);
            body[2] = (byte) (address >> 16);
            body[3] = (byte) (address >> 24);
            System.arraycopy(payload, offset, body, 4, size);
            request(SmsProtocol.DATA_DOWNLOAD_REQ, body, SmsProtocol.DATA_DOWNLOAD_RES);
            address += size;
        }
        request(SmsProtocol.DATA_VALIDITY_REQ,
                littleEndian(head.address, head.length, 0),
                SmsProtocol.DATA_VALIDITY_RES);
        request(SmsProtocol.DOWNLOAD_TRIGGER_REQ,
                littleEndian(head.address, 6, 0x200, 0, 4),
                SmsProtocol.DOWNLOAD_TRIGGER_RES);
    }

    /** ISDB-T statistics; needs a tuned device. */
    public Statistics statistics() {        byte[] payload = request(SmsProtocol.STATISTICS_EX_REQ, new byte[0],
                SmsProtocol.STATISTICS_EX_RES);
        if (payload.length < 48) {
            throw new IllegalStateException("short statistics " + payload.length);
        }
        return new Statistics(payload);
    }

    /**
     * ISDB-T TMCC from the same 653 statistics (one message, no extra USB request), or null when
     * the reply is too short to carry it. Read it idle: it takes the shared endpoint.
     */
    public Tmcc tmcc() {
        byte[] payload = request(SmsProtocol.STATISTICS_EX_REQ, new byte[0],
                SmsProtocol.STATISTICS_EX_RES);
        return Tmcc.parse(payload);
    }

    /** One message, or null when nothing arrived inside the timeout. */
    public synchronized SmsProtocol.Message readMessage(int timeoutMs) {
        if (!pending.isEmpty()) {
            return pending.removeFirst();
        }
        byte[] data = transport.read(16384, timeoutMs);
        if (data == null || data.length < 8) {
            return null;
        }
        try {
            return SmsProtocol.parse(data, alignment);
        } catch (IllegalArgumentException error) {
            return null;
        }
    }

    /**
     * Stream transfers thrown away because the pending buffer was full.
     *
     * Non-zero means the reply lagged further behind the stream than the buffer
     * holds.  It is the only place this driver can lose stream data, so expose
     * it instead of losing packets quietly.
     */
    public int droppedTransfers() {
        return dropped;
    }

    /** Next TS payload (3,760 bytes), or null for a timeout or other message. */
    public byte[] nextTs(int timeoutMs) {
        SmsProtocol.Message message = readMessage(timeoutMs);
        if (message == null) {
            return null;
        }
        if (message.type != SmsProtocol.DAB_CHANNEL
                && message.type != SmsProtocol.DVBT_BDA_DATA) {
            return null;
        }
        return message.payload;
    }

    private static byte[] littleEndian(int... values) {
        byte[] data = new byte[values.length * 4];
        for (int index = 0; index < values.length; index++) {
            data[index * 4] = (byte) values[index];
            data[index * 4 + 1] = (byte) (values[index] >> 8);
            data[index * 4 + 2] = (byte) (values[index] >> 16);
            data[index * 4 + 3] = (byte) (values[index] >> 24);
        }
        return data;
    }

    /** Field layout from {@code struct sms_isdbt_stats_ex}, after request_result. */
    public static final class Statistics {
        public final boolean rfLocked;
        public final boolean demodLocked;
        public final boolean externalLna;
        /** dB */
        public final int snr;
        /** dBm */
        public final int rssi;
        /** In-band power, dBm. */
        public final int power;
        /** Hz */
        public final int carrierOffset;
        /** Hz */
        public final long frequency;
        /** MHz */
        public final int bandwidth;

        Statistics(byte[] data) {
            this.rfLocked = SmsProtocol.word(data, 3) != 0;
            this.demodLocked = SmsProtocol.word(data, 4) != 0;
            this.externalLna = SmsProtocol.word(data, 5) != 0;
            this.snr = SmsProtocol.word(data, 6);
            this.rssi = SmsProtocol.word(data, 7);
            this.power = SmsProtocol.word(data, 8);
            this.carrierOffset = SmsProtocol.word(data, 9);
            this.frequency = SmsProtocol.word(data, 10) & 0xFFFFFFFFL;
            this.bandwidth = SmsProtocol.word(data, 11);
        }

        @Override
        public String toString() {
            return "rf=" + rfLocked + " demod=" + demodLocked + " snr=" + snr
                    + " dB rssi=" + rssi + " dBm power=" + power + " dBm offset="
                    + carrierOffset + " Hz @ " + frequency + " Hz";
        }
    }
}
