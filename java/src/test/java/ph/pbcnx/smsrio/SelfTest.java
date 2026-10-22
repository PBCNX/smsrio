package ph.pbcnx.smsrio;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

/** Dependency-free checks: fake transport, message frames, statistics and stream framing. */
public final class SelfTest {
    private SelfTest() {
    }

    private static final class Fake implements Transport {
        final List<byte[]> writes = new ArrayList<>();
        final List<byte[]> replies = new ArrayList<>();

        public void write(byte[] data, int timeoutMs) {
            writes.add(data);
        }

        public byte[] read(int maxLength, int timeoutMs) {
            return replies.isEmpty() ? new byte[0] : replies.remove(0);
        }
    }

    public static void main(String[] args) {
        Fake fake = new Fake();
        SmsRioDevice device = new SmsRioDevice(fake);

        fake.replies.add(reply(SmsProtocol.VERSION_RES, "ISDBT 07.03.58.0 RIO".getBytes(StandardCharsets.US_ASCII)));
        String version = device.version();
        check(version.equals("ISDBT 07.03.58.0 RIO"), "version: " + version);

        fake.replies.add(reply(SmsProtocol.INIT_RES, new byte[0]));
        fake.replies.add(reply(SmsProtocol.TUNE_RES, new byte[0]));
        device.setMode();
        device.addPid(0x2000);
        device.tune(599143);

        check(frameType(fake.writes.get(0)) == SmsProtocol.VERSION_REQ, "version req");
        check(frameType(fake.writes.get(1)) == SmsProtocol.INIT_REQ, "init req");
        check(frameType(fake.writes.get(2)) == SmsProtocol.ADD_PID_REQ, "pid req, no reply consumed");
        check(frameType(fake.writes.get(3)) == SmsProtocol.TUNE_REQ, "tune req");

        byte[] tune = fake.writes.get(3);
        check((tune[4] & 0xFF) == 24, "tune length " + (tune[4] & 0xFF));
        int frequency = (tune[8] & 0xFF) | ((tune[9] & 0xFF) << 8)
                | ((tune[10] & 0xFF) << 16) | ((tune[11] & 0xFF) << 24);
        check(frequency == 599143000, "frequency Hz " + frequency);

        // statistics: the device echoes the tuned frequency at word 10
        byte[] stats = new byte[288];
        putWord(stats, 1, 5);
        putWord(stats, 2, 284);
        putWord(stats, 3, 1);
        putWord(stats, 4, 1);
        putWord(stats, 6, 30);
        putWord(stats, 7, -49);
        putWord(stats, 8, -48);
        putWord(stats, 9, -5385);
        putWord(stats, 10, 599143000);
        putWord(stats, 11, 6);
        fake.replies.add(reply(SmsProtocol.STATISTICS_EX_RES, stats));
        SmsRioDevice.Statistics reading = device.statistics();
        check(reading.demodLocked && reading.rfLocked, "lock " + reading);
        check(reading.snr == 30, "snr " + reading.snr);
        check(reading.power == -48, "power " + reading.power);
        check(reading.frequency == 599143000L, "stats frequency " + reading.frequency);
        check(reading.bandwidth == 6, "bandwidth " + reading.bandwidth);

        // split-message framing: header stays at 0 on the wire, payload at 512
        byte[] packet = new byte[188];
        Arrays.fill(packet, (byte) 0x00);
        packet[0] = 0x47;
        byte[] streamTransfer = new byte[SmsStream.TRANSFER];
        for (int index = 0; index < SmsStream.PACKETS; index++) {
            System.arraycopy(packet, 0, streamTransfer, SmsStream.HEADER + index * 188, 188);
        }
        byte[] head = SmsProtocol.build(SmsProtocol.DAB_CHANNEL, 0, 1,
                new byte[3760], SmsProtocol.FLAG_SPLIT_MSG | 0x0009);
        System.arraycopy(head, 0, streamTransfer, 0, 8);
        fake.replies.add(streamTransfer);
        byte[] ts = device.nextTs(500);
        check(ts != null && ts.length == 3760, "nextTs length " + (ts == null ? -1 : ts.length));
        check(ts[0] == 0x47 && ts[188] == 0x47, "nextTs sync");

        // a statistics poll that runs into a TS transfer must not drop it
        Fake interleaved = new Fake();
        SmsRioDevice poller = new SmsRioDevice(interleaved);
        byte[] statsBody = new byte[288];
        putWord(statsBody, 4, 1);
        interleaved.replies.add(streamTransfer);
        interleaved.replies.add(reply(SmsProtocol.STATISTICS_EX_RES, statsBody));
        poller.statistics();
        check(poller.nextTs(0) != null, "skipped TS transfer is kept");

        // and a poll behind a *busy* stream: 40 transfers before the reply used
        // to exhaust the old eight-attempt budget even though no time passed
        Fake busy = new Fake();
        SmsRioDevice busyPoller = new SmsRioDevice(busy);
        for (int index = 0; index < 40; index++) {
            busy.replies.add(streamTransfer);
        }
        busy.replies.add(reply(SmsProtocol.STATISTICS_EX_RES, statsBody));
        busyPoller.statistics();
        int kept = 0;
        while (busyPoller.nextTs(0) != null) {
            kept++;
        }
        check(kept == 40, "busy poll kept " + kept + " of 40 transfers");
        check(busyPoller.droppedTransfers() == 0, "busy poll dropped nothing");

        SmsStream stream = new SmsStream();
        byte[] spanned = stream.feed(streamTransfer);
        check(spanned.length == 3760, "stream length " + spanned.length);
        int syncs = 0;
        for (int index = 0; index < spanned.length; index += 188) {
            if (spanned[index] == 0x47) {
                syncs++;
            }
        }
        check(syncs == 20, "syncs " + syncs);

        // firmware loader: chunks, validity, trigger
        int start = 0x00040260;
        byte[] image = new byte[SmsFirmware.HEADER + 480];
        putWord(image, 0, 0x1234);
        putWord(image, 1, 480);
        putWord(image, 2, start);
        Fake cold = new Fake();
        SmsRioDevice coldDevice = new SmsRioDevice(cold);
        cold.replies.add(reply(SmsProtocol.DATA_DOWNLOAD_RES, new byte[0]));
        cold.replies.add(reply(SmsProtocol.DATA_DOWNLOAD_RES, new byte[0]));
        cold.replies.add(reply(SmsProtocol.DATA_VALIDITY_RES, new byte[0]));
        cold.replies.add(reply(SmsProtocol.DOWNLOAD_TRIGGER_RES, new byte[0]));
        coldDevice.uploadFirmware(image);
        check(cold.writes.size() == 4, "upload writes " + cold.writes.size());
        check(frameType(cold.writes.get(0)) == SmsProtocol.DATA_DOWNLOAD_REQ, "chunk req");
        check(SmsProtocol.word(cold.writes.get(0), 2) == start, "chunk 0 address");
        check((cold.writes.get(0)[4] & 0xFF) == 8 + 4 + 240, "chunk 0 length");
        check(SmsProtocol.word(cold.writes.get(1), 2) == start + 240, "chunk 1 address");
        check(frameType(cold.writes.get(2)) == SmsProtocol.DATA_VALIDITY_REQ, "validity");
        check(SmsProtocol.word(cold.writes.get(2), 2) == start, "validity address");
        check(SmsProtocol.word(cold.writes.get(2), 3) == 480, "validity length");
        check(frameType(cold.writes.get(3)) == SmsProtocol.DOWNLOAD_TRIGGER_REQ, "trigger");
        check(SmsProtocol.word(cold.writes.get(3), 2) == start, "trigger address");
        check(SmsProtocol.word(cold.writes.get(3), 3) == 6, "trigger mode");
        check(SmsProtocol.word(cold.writes.get(3), 4) == 0x200, "trigger block");

        System.out.println("smsrio java self-test: OK");
    }

    private static void putWord(byte[] data, int index, int value) {
        data[index * 4] = (byte) value;
        data[index * 4 + 1] = (byte) (value >> 8);
        data[index * 4 + 2] = (byte) (value >> 16);
        data[index * 4 + 3] = (byte) (value >> 24);
    }

    private static byte[] reply(int type, byte[] payload) {
        return SmsProtocol.build(type, SmsProtocol.HIF_TASK, 0, payload, 0);
    }

    private static int frameType(byte[] frame) {
        return (frame[0] & 0xFF) | ((frame[1] & 0xFF) << 8);
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }
}
