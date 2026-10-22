"""A statistics poll must not cost a single TS packet.

The firmware interleaves stream transfers, indications and replies on one bulk
IN endpoint, so a request that waits for its reply has to keep everything else
it reads.  These tests pin that down: every skipped TS transfer comes back, in
order, before anything read later.
"""
import struct
import unittest

from smsrio.transport import (MSG_DAB_CHANNEL, MSG_GET_STATISTICS_EX_REQ,
                              MSG_GET_STATISTICS_EX_RES, SmsDevice)


def message(msg_type, payload=b""):
    return struct.pack("<HBBHH", msg_type, 11, 0, 8 + len(payload), 0) + payload


def ts_message(pid, counter_seed):
    """A plausible stream transfer: 21 TS packets with distinct bytes."""
    body = bytearray()
    for index in range(21):
        packet = bytearray(188)
        packet[0] = 0x47
        packet[1] = (pid >> 8) & 0x1F
        packet[2] = pid & 0xFF
        packet[3] = (index + counter_seed) & 0x0F
        packet[4:188] = bytes([(pid + index) & 0xFF]) * 184
        body += packet
    return message(MSG_DAB_CHANNEL, bytes(body))


class FakeUsb:
    def __init__(self, replies, pad=None):
        self.writes = []
        self.replies = list(replies)
        self.pad = pad

    def write(self, endpoint, data, timeout):
        self.writes.append((endpoint, bytes(data)))

    def read(self, endpoint, size, timeout):
        if not self.replies:
            raise OSError("timeout")
        return self.replies.pop(0)


class PendingQueueTest(unittest.TestCase):
    def setUp(self):
        self.ts_a = ts_message(0x100, 1)
        self.ts_b = ts_message(0x100, 8)
        self.stats = message(MSG_GET_STATISTICS_EX_RES,
                             struct.pack("<12I", *[
                                 value & 0xFFFFFFFF for value in
                                 (0, 1, 48, 1, 1, 0, 30, -75, -80, 0,
                                  599143000, 6)]))

    def test_statistics_keeps_the_stream_it_skips(self):
        # two stream transfers, then the statistics reply
        usb = FakeUsb([self.ts_a, self.ts_b, self.stats])
        device = SmsDevice(usb)
        values = device.statistics()
        self.assertTrue(values["demod_locked"])
        # nothing was dropped, and both come out in arrival order
        self.assertEqual(device.read_message(), (MSG_DAB_CHANNEL, 11, 0,
                                                 self.ts_a[8:]))
        self.assertEqual(device.read_message(), (MSG_DAB_CHANNEL, 11, 0,
                                                 self.ts_b[8:]))

    def test_the_stream_after_the_poll_is_unaffected(self):
        usb = FakeUsb([self.ts_a, self.stats, self.ts_b])
        device = SmsDevice(usb)
        device.statistics()
        first = device.read_message()
        second = device.read_message()
        self.assertEqual(first[3], self.ts_a[8:])
        self.assertEqual(second[3], self.ts_b[8:])

    def test_poll_costs_no_packets_across_many_polls(self):
        # 20 polls, each behind 40 stream transfers, with the reader draining
        # between polls as it does in the real loop: every transfer survives.
        transfers = []
        for poll in range(20):
            for index in range(40):
                transfers.append(ts_message(0x100, poll))
            transfers.append(self.stats)
        usb = FakeUsb(transfers)
        device = SmsDevice(usb)
        delivered = 0
        for _ in range(20):
            device.statistics()
            while device.pending:
                device.read_message()
                delivered += 1
        self.assertEqual(delivered, 800)
        self.assertEqual(device.dropped, 0)

    def test_overflow_is_counted_not_silent(self):
        # The queue is bounded.  If a reply lags further behind the stream than
        # the buffer holds, the driver must say so rather than lose packets
        # quietly - this is the only place stream data can be dropped.
        over = 5
        usb = FakeUsb([ts_message(0x100, 0)] * (SmsDevice.PENDING_LIMIT + over)
                      + [self.stats])
        device = SmsDevice(usb)
        device.statistics()
        self.assertEqual(len(device.pending), SmsDevice.PENDING_LIMIT)
        self.assertEqual(device.dropped, over)


if __name__ == "__main__":
    unittest.main()
