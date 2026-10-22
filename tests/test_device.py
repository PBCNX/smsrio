import unittest

from smsrio.device import SmsRio
from smsrio.stream import HEADER, PACKETS_PER_TRANSFER
from smsrio.transport import MSG_DVBT_BDA_DATA


class FakeDevice:
    def __init__(self, transfer=b""):
        self.calls = []
        self.transfer = transfer

    def version(self):
        self.calls.append(("version",))
        return "ISDBT 07.03.58.0 RIO"

    def set_mode(self, mode=7):
        self.calls.append(("mode", mode))

    def add_pid(self, pid):
        self.calls.append(("pid", pid))

    def tune(self, frequency_khz, **kwargs):
        self.calls.append(("tune", frequency_khz))

    def read_message(self, timeout=300):
        data, self.transfer = self.transfer, b""
        return (MSG_DVBT_BDA_DATA, 11, 0, data) if data else None


class DeviceTest(unittest.TestCase):
    def test_bring_up_and_tune(self):
        fake = FakeDevice()
        rio = SmsRio(fake)
        self.assertIn("ISDBT", rio.bring_up())
        rio.tune(599143)
        self.assertEqual(fake.calls[1], ("mode", 7))
        self.assertEqual(fake.calls[2], ("pid", 0x2000))
        self.assertEqual(fake.calls[3], ("tune", 599143))

    def test_read_ts_returns_payload(self):
        packet = bytes([0x47]) + bytes(187)
        fake = FakeDevice(packet * PACKETS_PER_TRANSFER)
        rio = SmsRio(fake)
        data = rio.read_ts()
        self.assertEqual(len(data), PACKETS_PER_TRANSFER * 188)
        self.assertEqual(data[:1], b"\x47")

    def test_read_ts_skips_other_messages(self):
        fake = FakeDevice()
        fake.transfer = b""
        rio = SmsRio(fake)
        self.assertEqual(rio.read_ts(), b"")


if __name__ == "__main__":
    unittest.main()
