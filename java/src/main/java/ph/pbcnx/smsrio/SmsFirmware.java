package ph.pbcnx.smsrio;

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

    public final int checksum;
    public final int length;
    public final int address;

    private SmsFirmware(int checksum, int length, int address) {
        this.checksum = checksum;
        this.length = length;
        this.address = address;
    }

    /** Parses and validates the image header. */
    public static SmsFirmware parse(byte[] image) {
        if (image == null || image.length < HEADER) {
            throw new IllegalArgumentException("image shorter than its header");
        }
        int checksum = SmsProtocol.word(image, 0);
        int length = SmsProtocol.word(image, 1);
        int address = SmsProtocol.word(image, 2);
        if (length <= 0 || HEADER + length > image.length) {
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
}
