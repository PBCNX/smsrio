package ph.pbcnx.smsrio;

/** Byte transport implemented by the host (Android UsbDeviceConnection, tests). */
public interface Transport {
    void write(byte[] data, int timeoutMs);

    byte[] read(int maxLength, int timeoutMs);
}
