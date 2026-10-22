"""Does the ROM acknowledge a chunk only when the next message arrives?"""
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


def chunk(index):
    body = struct.pack("<I", start + index * firmware.CHUNK) + \
        payload[index * firmware.CHUNK:(index + 1) * firmware.CHUNK]
    device.send(firmware.MSG_DATA_DOWNLOAD_REQ, body)


def drain(seconds):
    deadline = time.time() + seconds
    types = []
    while time.time() < deadline:
        try:
            message = device.receive(300)
        except Exception:
            continue
        types.append(message[0])
    return types


print("send 4 chunks back to back, then listen:")
for index in range(4):
    chunk(index)
print("   replies:", [hex(t) for t in drain(3.0)])

print("send one more, listen again:")
chunk(4)
print("   replies:", [hex(t) for t in drain(2.0)])

device.close()
