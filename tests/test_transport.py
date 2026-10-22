import struct
import unittest

from smsrio.transport import (MSG_DAB_CHANNEL, MSG_GET_STATISTICS_EX_REQ,
                              MSG_GET_STATISTICS_EX_RES, MSG_TUNE_REQ,
                              MSG_TUNE_RES, SmsDevice, TransportError)


class FakeUsb:
    def __init__(self, replies=()):
        self.writes = []
        self.replies = list(replies)

    def write(self, endpoint, data, timeout):
        self.writes.append((endpoint, bytes(data)))

    def read(self, endpoint, size, timeout):
        if not self.replies:
            raise TransportError("empty")
        return self.replies.pop(0)


def message(msg_type, payload=b""):
    return struct.pack("<HBBHH", msg_type, 11, 0, 8 + len(payload), 0) + payload


class TransportTest(unittest.TestCase):
    def test_send_header(self):
        usb = FakeUsb()
        device = SmsDevice(usb)
        payload = struct.pack("<IIII", 599143, 8, 12000000, 0)
        device.send(MSG_TUNE_REQ, payload)
        endpoint, data = usb.writes[0]
        msg_type, src, dst, length, flags = struct.unpack("<HBBHH", data[:8])
        self.assertEqual(msg_type, MSG_TUNE_REQ)
        self.assertEqual(dst, 11)
        self.assertEqual(length, 24)
        self.assertEqual(data[8:], payload)

    def test_request_skips_notifications(self):
        usb = FakeUsb([message(805), message(MSG_TUNE_RES, b"\x00" * 4)])
        device = SmsDevice(usb)
        body = device.request(MSG_TUNE_REQ, b"\x00" * 16, MSG_TUNE_RES)
        self.assertEqual(len(body), 4)

    def test_bad_length_rejected(self):
        usb = FakeUsb([b"\x01\x02\x03"])
        device = SmsDevice(usb)
        with self.assertRaises(TransportError):
            device.receive()

    def test_split_payload_at_512(self):
        # A real streaming transfer: header at 0, zeros at 504, TS at 512.
        payload = bytes([0x47]) + bytes(3759)
        frame = struct.pack("<HBBHH", MSG_DAB_CHANNEL, 0, 1, 3768, 0x000D)
        transfer = (frame + bytes(504 - 8) + bytes(8) + payload)
        self.assertEqual(len(transfer), 4272)
        device = SmsDevice(FakeUsb([transfer]))
        device.alignment = 504
        msg_type, src, dst, body = device.receive()
        self.assertEqual(msg_type, MSG_DAB_CHANNEL)
        self.assertEqual(len(body), 3760)
        self.assertEqual(body[:1], b"\x47")

    def test_tune_sends_hz(self):
        usb = FakeUsb()
        device = SmsDevice(usb)
        device.send(MSG_TUNE_REQ, struct.pack("<IIII", 509143 * 1000, 8, 12000000, 0))
        frequency = struct.unpack("<I", usb.writes[0][1][8:12])[0]
        self.assertEqual(frequency, 509143000)

    def test_request_keeps_skipped_data(self):
        # A statistics poll that runs into a TS transfer must not lose it.
        payload = bytes([0x47]) + bytes(3759)
        frame = struct.pack("<HBBHH", MSG_DAB_CHANNEL, 0, 1, 3768, 0x000D)
        transfer = frame + bytes(504 - 8) + bytes(8) + payload
        usb = FakeUsb([transfer, message(MSG_GET_STATISTICS_EX_RES, b"\x00" * 288)])
        device = SmsDevice(usb)
        device.alignment = 504
        body = device.request(MSG_GET_STATISTICS_EX_REQ, b"", MSG_GET_STATISTICS_EX_RES)
        self.assertEqual(len(body), 288)
        kept = device.read_message()
        self.assertEqual(kept[0], MSG_DAB_CHANNEL)
        self.assertEqual(len(kept[3]), 3760)


if __name__ == "__main__":
    unittest.main()
