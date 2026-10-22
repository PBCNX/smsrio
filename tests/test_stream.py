import unittest

from smsrio.stream import HEADER, PACKETS_PER_TRANSFER, TRANSFER, SmsStream


def transfer(marker=0):
    packet = bytes([0x47]) + bytes([marker]) * 187
    return bytes([0xAA]) * HEADER + packet * PACKETS_PER_TRANSFER


class StreamTest(unittest.TestCase):
    def test_one_transfer(self):
        stream = SmsStream()
        data = stream.feed(transfer(1))
        self.assertEqual(len(data), PACKETS_PER_TRANSFER * 188)
        self.assertEqual(data[:1], b"\x47")

    def test_partial_transfer_is_held(self):
        stream = SmsStream()
        self.assertEqual(stream.feed(transfer()[:TRANSFER - 1]), b"")
        rest = transfer()[TRANSFER - 1:]
        self.assertEqual(len(stream.feed(rest)), PACKETS_PER_TRANSFER * 188)

    def test_header_bytes_are_not_emitted(self):
        stream = SmsStream()
        data = stream.feed(transfer(0xEE))
        self.assertNotIn(0xAA, data)


if __name__ == "__main__":
    unittest.main()
