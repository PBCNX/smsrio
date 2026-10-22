"""Command line interface for Siano Rio."""
import argparse
import socket
import sys
import time

from . import __version__
from .device import SmsRio
from .transport import PID_RIO, SmsDevice, devices


def open_device(index=0):
    found = [d for d in devices() if d.idProduct == PID_RIO]
    if not found:
        raise SystemExit("no Siano Rio (187f:0600) found; bind it to WinUSB first")
    if index >= len(found):
        raise SystemExit("only %d device(s) found" % len(found))
    return SmsDevice(found[index]).open()


def cmd_list(args):
    found = False
    for device in devices():
        found = True
        supported = "supported" if device.idProduct == PID_RIO else "unsupported"
        print("187f:%04x  bus %s addr %s  %s" % (
            device.idProduct, device.bus, device.address, supported))
    if not found:
        print("no 187f devices found")
    return 0


def cmd_probe(args):
    device = open_device(args.index)
    try:
        rio = SmsRio(device, print)
        version = rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        total = 0
        for _ in range(20):
            total += len(rio.read_ts())
            if total > 100000:
                break
        print("firmware: %s" % version)
        if status:
            print("rf: %s demod: %s snr: %d dB power: %d dBm offset: %d Hz"
                  % (status["rf_locked"], status["demod_locked"], status["snr"],
                     status["power"], status["carrier_offset"]))
        else:
            print("status: no statistics")
        print("ts: %d bytes" % total)
        return 0
    finally:
        device.close()


def cmd_status(args):
    device = open_device(args.index)
    try:
        rio = SmsRio(device, print)
        rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        if not status:
            print("no statistics from the device")
            return 1
        print("version:    %s" % device.version())
        print("rf:         %s" % status["rf_locked"])
        print("demod:      %s" % status["demod_locked"])
        print("snr:        %d dB" % status["snr"])
        print("rssi:       %d dBm" % status["rssi"])
        print("in-band:    %d dBm" % status["power"])
        print("carrier:    %d Hz" % status["carrier_offset"])
        print("frequency:  %d Hz" % status["frequency"])
        print("bandwidth:  %d MHz" % status["bandwidth"])
        return 0 if status["demod_locked"] else 2
    finally:
        device.close()


class Sink:
    def __init__(self, path=None, udp=None):
        self.file = None
        self.sock = None
        self.addr = None
        if udp:
            host, _, port = udp.rpartition(":")
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.addr = (host or "127.0.0.1", int(port))
        elif path and path != "-":
            self.file = open(path, "wb")
        else:
            self.file = sys.stdout.buffer

    def write(self, data):
        if self.sock:
            for i in range(0, len(data), 1316):
                self.sock.sendto(data[i:i + 1316], self.addr)
        else:
            self.file.write(data)
            self.file.flush()

    def close(self):
        if self.file and self.file is not sys.stdout.buffer:
            self.file.close()
        if self.sock:
            self.sock.close()


def cmd_play(args):
    device = open_device(args.index)
    sink = Sink(args.out, args.udp)
    try:
        rio = SmsRio(device, print)
        rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        if status and status["demod_locked"]:
            print("locked: snr %d dB, in-band %d dBm"
                  % (status["snr"], status["power"]), file=sys.stderr)
        else:
            print("no lock: in-band %s dBm - check the antenna"
                  % (status["power"] if status else "?"), file=sys.stderr)
        started = time.time()
        packets = 0
        while not args.seconds or time.time() - started < args.seconds:
            data = rio.read_ts()
            if data:
                sink.write(data)
                packets += len(data) // 188
        print("wrote %d packets" % packets, file=sys.stderr)
        return 0
    finally:
        sink.close()
        device.close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="smsrio", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list", help="list 187f devices")
    p.set_defaults(func=cmd_list)

    for name, func, text in (("probe", cmd_probe, "bring up, tune and read TS"),
                             ("status", cmd_status, "lock, SNR and in-band power"),
                             ("play", cmd_play, "stream MPEG-TS")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--index", type=int, default=0)
        p.add_argument("--freq", type=int, default=599143, help="kHz")
        p.add_argument("--firmware", metavar="PATH")
        p.add_argument("--timeout", type=float, default=5.0,
                       help="seconds to wait for lock")
        p.set_defaults(func=func)
        if name == "play":
            p.add_argument("--out", default="-", help="file, - for stdout")
            p.add_argument("--udp", help="HOST:PORT")
            p.add_argument("--seconds", type=float, default=0)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
