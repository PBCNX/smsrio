package ph.pbcnx.smsrio;

/** Siano message framing: {@code <type u16><src u8><dst u8><length u16><flags u16>}. */
public final class SmsProtocol {
    public static final int HIF_TASK = 11;

    public static final int VERSION_REQ = 503;
    public static final int VERSION_RES = 504;
    public static final int INIT_REQ = 578;
    public static final int INIT_RES = 579;
    public static final int ADD_PID_REQ = 601;
    public static final int ADD_PID_RES = 602;
    public static final int STATISTICS_REQ = 615;
    public static final int STATISTICS_RES = 616;
    public static final int STATISTICS_EX_REQ = 653;
    public static final int STATISTICS_EX_RES = 654;
    public static final int DAB_CHANNEL = 607;
    public static final int DVBT_BDA_DATA = 693;
    public static final int TUNE_REQ = 776;
    public static final int TUNE_RES = 777;

    public static final int DATA_DOWNLOAD_REQ = 660;
    public static final int DATA_DOWNLOAD_RES = 661;
    public static final int DATA_VALIDITY_REQ = 662;
    public static final int DATA_VALIDITY_RES = 663;
    public static final int DOWNLOAD_TRIGGER_REQ = 664;
    public static final int DOWNLOAD_TRIGGER_RES = 665;

    public static final int MODE_ISDBT_BDA = 7;
    public static final int BW_ISDBT_13SEG = 8;

    /** MSG_HDR_FLAG_SPLIT_MSG: the real header sits inside the transfer. */
    public static final int FLAG_SPLIT_MSG = 4;
    /** max_packet_size (512) - header size: where split headers land. */
    public static final int DEFAULT_ALIGNMENT = 504;

    private SmsProtocol() {
    }

    public static byte[] build(int type, int source, int destination, byte[] payload, int flags) {
        int size = payload == null ? 0 : payload.length;
        byte[] frame = new byte[8 + size];
        frame[0] = (byte) type;
        frame[1] = (byte) (type >> 8);
        frame[2] = (byte) source;
        frame[3] = (byte) destination;
        frame[4] = (byte) (8 + size);
        frame[5] = (byte) ((8 + size) >> 8);
        frame[6] = (byte) flags;
        frame[7] = (byte) (flags >> 8);
        if (payload != null) {
            System.arraycopy(payload, 0, frame, 8, size);
        }
        return frame;
    }

    public static final class Message {
        public final int type;
        public final int source;
        public final int destination;
        public final int flags;
        public final byte[] payload;

        Message(int type, int source, int destination, int flags, byte[] payload) {
            this.type = type;
            this.source = source;
            this.destination = destination;
            this.flags = flags;
            this.payload = payload;
        }
    }

    public static Message parse(byte[] data) {
        return parse(data, DEFAULT_ALIGNMENT);
    }

    /**
     * Parses one message. Streaming transfers set {@code FLAG_SPLIT_MSG}: the
     * header stays at offset 0 on the wire and the payload is pushed to
     * {@code alignment + 8}, because the kernel copies the header into the
     * buffer only after the URB completes.
     */
    public static Message parse(byte[] data, int alignment) {
        if (data.length < 8) {
            throw new IllegalArgumentException("short message");
        }
        int type = (data[0] & 0xFF) | ((data[1] & 0xFF) << 8);
        int source = data[2] & 0xFF;
        int destination = data[3] & 0xFF;
        int length = (data[4] & 0xFF) | ((data[5] & 0xFF) << 8);
        int flags = (data[6] & 0xFF) | ((data[7] & 0xFF) << 8);
        int start = 8;
        if ((flags & FLAG_SPLIT_MSG) != 0) {
            start = alignment + ((flags >> 8) & 3) + 8;
        }
        if (length < 8 || start + length - 8 > data.length) {
            throw new IllegalArgumentException("bad length " + length);
        }
        byte[] payload = new byte[length - 8];
        System.arraycopy(data, start, payload, 0, payload.length);
        return new Message(type, source, destination, flags, payload);
    }

    public static int word(byte[] data, int index) {
        int offset = index * 4;
        return (data[offset] & 0xFF) | ((data[offset + 1] & 0xFF) << 8)
                | ((data[offset + 2] & 0xFF) << 16) | ((data[offset + 3] & 0xFF) << 24);
    }
}
