"""Finish a firmware upload the ROM is already waiting for."""
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smsrio import firmware
from smsrio.cli import open_device

IMAGE = r"D:\Profile\Documents\Claude\pbcnx-isdbt\branches\TUNERAPP\vendor\firmware\isdbt_rio.inp"
TIMEOUT = 4000

device = open_device(0)
image = firmware.load(IMAGE)
checksum, length, start = struct.unpack("<III", image[:12])
payload = image[12:12 + length]
print("payload %d bytes to 0x%08x, timeout %d ms" % (length, start, TIMEOUT), flush=True)

address = start
sent = 0
started = time.time()
for offset in range(0, length, firmware.CHUNK):
    chunk = payload[offset:offset + firmware.CHUNK]
    body = struct.pack("<I", address) + chunk
    try:
        device.request(firmware.MSG_DATA_DOWNLOAD_REQ, body,
                       firmware.MSG_DATA_DOWNLOAD_RES, timeout=TIMEOUT)
    except Exception as error:
        print("chunk %d failed at 0x%08x: %s" % (sent, address, error), flush=True)
        break
    address += len(chunk)
    sent += 1
    if sent % 50 == 0:
        print("   %d chunks, %.1f s" % (sent, time.time() - started), flush=True)

print("sent %d of %d chunks in %.1f s" % (sent, (length + firmware.CHUNK - 1) // firmware.CHUNK,
                                          time.time() - started), flush=True)

if sent == (length + firmware.CHUNK - 1) // firmware.CHUNK:
    device.request(firmware.MSG_DATA_VALIDITY_REQ,
                   struct.pack("<III", start, length, 0),
                   firmware.MSG_DATA_VALIDITY_RES, timeout=TIMEOUT)
    print("validity ok", flush=True)
    device.request(firmware.MSG_DOWNLOAD_TRIGGER_REQ,
                   struct.pack("<IIIII", start, 6, 0x200, 0, 4),
                   firmware.MSG_DOWNLOAD_TRIGGER_RES, timeout=TIMEOUT)
    print("trigger ok", flush=True)
    time.sleep(1.0)

device.send(0x01F7)
try:
    message = device.receive(2000)
    print("version type 0x%04x payload %s" % (message[0], message[3][:32]))
except Exception as error:
    print("version request still silent:", type(error).__name__)
device.close()
