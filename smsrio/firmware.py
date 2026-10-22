"""Siano Rio firmware: a 12-byte header (checksum, length, start) and payload.

Upload follows smscore's family-2 sequence: data chunks, validity, trigger.
"""
import hashlib
import os
import struct
import time

from .transport import TransportError

SIZE = 91048
PAYLOAD = SIZE - 12
SHA256 = "777c9ba2ce44db9e0a90f7207167e9095cc0223be2b2af599f645f1c73d76b14"

MSG_DATA_DOWNLOAD_REQ = 660
MSG_DATA_DOWNLOAD_RES = 661
MSG_DATA_VALIDITY_REQ = 662
MSG_DATA_VALIDITY_RES = 663
MSG_DOWNLOAD_TRIGGER_REQ = 664
MSG_DOWNLOAD_TRIGGER_RES = 665
MSG_RELOAD_START_REQ = 702
MSG_RELOAD_START_RES = 703
MSG_RELOAD_EXEC_REQ = 704
MSG_RELOAD_EXEC_RES = 705

CHUNK = 240


def find(path=None):
    if path:
        return path
    env = os.environ.get("SMSRIO_FIRMWARE")
    if env:
        return env
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, "isdbt_rio.inp")


def load(path=None):
    path = find(path)
    if not os.path.exists(path):
        raise FileNotFoundError(
            "Siano firmware not found at %s; supply the vendor isdbt_rio.inp" % path)
    image = open(path, "rb").read()
    if len(image) != SIZE or hashlib.sha256(image).hexdigest() != SHA256:
        raise ValueError("not the expected 91,048-byte isdbt_rio.inp")
    checksum, length, start = struct.unpack("<III", image[:12])
    if length != PAYLOAD:
        raise ValueError("bad payload length %d" % length)
    return image


def _expect(device, expected, timeout=2000):
    """Read until the expected reply arrives.

    One read with the whole remaining budget, which is what the verified
    loader did.  Short read windows were an experiment on a wedged device and
    they do not work here: on a healthy ROM the ack arrives promptly and a
    long read returns it.
    """
    deadline = time.monotonic() + timeout / 1000.0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TransportError("no response to 0x%04x" % expected)
        try:
            message = device.receive(remaining * 1000)
        except TransportError:
            continue
        if message[0] == expected:
            return message[3]


def upload(device, image, log=None, window=1):
    """Upload the image and start it.

    One chunk at a time, each acknowledged before the next is sent: measured on
    hardware, this ROM answers every chunk within ~150 ms that way.  Two
    earlier designs failed and are worth not repeating:

    * sending a chunk and waiting with a single long read timeout (2-4 s) never
      saw the reply, even though it was queued - short read windows are what
      work on Windows;
    * sending many chunks before reading anything (`window=8`) starved the
      acknowledgement path and the upload stalled at the first reply.
    """
    log = log or (lambda message: None)
    checksum, length, start = struct.unpack("<III", image[:12])
    payload = image[12:12 + length]
    address = start
    log("uploading %d bytes to 0x%08x" % (length, start))

    outstanding = 0
    for offset in range(0, length, CHUNK):
        chunk = payload[offset:offset + CHUNK]
        device.send(MSG_DATA_DOWNLOAD_REQ, struct.pack("<I", address) + chunk)
        address += len(chunk)
        outstanding += 1
        if outstanding >= window:
            _expect(device, MSG_DATA_DOWNLOAD_RES, timeout=3000)
            outstanding -= 1

    while outstanding:
        _expect(device, MSG_DATA_DOWNLOAD_RES, timeout=3000)
        outstanding -= 1

    device.request(MSG_DATA_VALIDITY_REQ, struct.pack("<III", start, length, 0),
                   MSG_DATA_VALIDITY_RES, timeout=2000)
    device.request(MSG_DOWNLOAD_TRIGGER_REQ,
                   struct.pack("<IIIII", start, 6, 0x200, 0, 4),
                   MSG_DOWNLOAD_TRIGGER_RES, timeout=2000)
    log("firmware uploaded")
    return True
