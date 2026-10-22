"""What does the device actually reply to one data-download chunk?"""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smsrio import firmware
from smsrio.cli import open_device

IMAGE = r"D:\Profile\Documents\Claude\pbcnx-isdbt\branches\TUNERAPP\vendor\firmware\isdbt_rio.inp"

device = open_device(0)
image = firmware.load(IMAGE)
checksum, length, start = struct.unpack("<III", image[:12])
payload = image[12:12 + length]
print("image %d bytes, payload %d, start 0x%08x" % (len(image), length, start))


def drain(seconds):
    deadline = time.time() + seconds
    seen = 0
    while time.time() < deadline:
        try:
            message = device.receive(400)
        except Exception:
            continue
        print("   type 0x%04x src %d dst %d payload %d bytes %s"
              % (message[0], message[1], message[2], len(message[3]),
                 message[3][:16].hex()), flush=True)
        seen += 1
    return seen


print("version request:")
device.send(0x01F7)
drain(1.0)

print("first data chunk (%d bytes):" % firmware.CHUNK)
body = struct.pack("<I", start) + payload[:firmware.CHUNK]
device.send(firmware.MSG_DATA_DOWNLOAD_REQ, body)
print("replies: %d" % drain(2.5))
device.close()
