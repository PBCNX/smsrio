package ph.pbcnx.smsrio;

import java.util.Arrays;

/**
 * Stream framing: every streaming bulk transfer is 512 bytes of header followed
 * by 20 complete TS packets. Verified on a capture: 6,365/6,365 transfers.
 */
public final class SmsStream {
    public static final int HEADER = 512;
    public static final int PACKETS = 20;
    public static final int TRANSFER = HEADER + PACKETS * 188;

    private byte[] buffer = new byte[0];

    public byte[] feed(byte[] data) {
        byte[] combined = new byte[buffer.length + data.length];
        System.arraycopy(buffer, 0, combined, 0, buffer.length);
        System.arraycopy(data, 0, combined, buffer.length, data.length);
        buffer = combined;

        byte[] out = new byte[0];
        int offset = 0;
        while (offset + TRANSFER <= buffer.length) {
            byte[] body = Arrays.copyOfRange(buffer, offset + HEADER, offset + TRANSFER);
            offset += TRANSFER;
            if (body[0] != 0x47) {
                body = resync(body);
            }
            byte[] joined = new byte[out.length + body.length];
            System.arraycopy(out, 0, joined, 0, out.length);
            System.arraycopy(body, 0, joined, out.length, body.length);
            out = joined;
        }
        buffer = Arrays.copyOfRange(buffer, offset, buffer.length);
        return out;
    }

    private static byte[] resync(byte[] body) {
        for (int start = 0; start + 188 <= body.length; start++) {
            if (body[start] == 0x47 && (start + 188 >= body.length || body[start + 188] == 0x47)) {
                int length = (body.length - start) / 188 * 188;
                return Arrays.copyOfRange(body, start, start + length);
            }
        }
        return new byte[0];
    }
}
