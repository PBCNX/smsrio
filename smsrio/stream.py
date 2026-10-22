"""Siano Rio stream framing.

Every streaming bulk transfer is 4,272 bytes: a 512-byte header followed by
3,760 bytes = 20 complete MPEG-TS packets. Verified against a 28 MB capture:
6,365/6,365 transfers had 0x47 at offset 512 and all 127,300 packet syncs were
aligned.
"""
TS_PACKET = 188
PACKETS_PER_TRANSFER = 20
HEADER = 512
TRANSFER = HEADER + PACKETS_PER_TRANSFER * TS_PACKET


class SmsStream:
    """Splits bulk transfers into TS packets, tolerating partial transfers."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer += data
        packets = bytearray()
        while len(self.buffer) >= TRANSFER:
            transfer = bytes(self.buffer[:TRANSFER])
            del self.buffer[:TRANSFER]
            body = transfer[HEADER:]
            if body[:1] != b"\x47":
                body = self._resync(body)
                if not body:
                    continue
            packets += body
        return bytes(packets)

    @staticmethod
    def _resync(body):
        for offset in range(len(body) - TS_PACKET):
            if body[offset] == 0x47 and body[offset + TS_PACKET] == 0x47:
                end = offset + (len(body) - offset) // TS_PACKET * TS_PACKET
                return body[offset:end]
        return b""
