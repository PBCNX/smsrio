"""A/B test: does polling statistics cost TS packets?

    python tools/siano_ab.py --label a --poll 500 --seconds 20 --freq 599143
    python tools/siano_ab.py --label b --poll 0   --seconds 20 --freq 599143
    python tools/ts_cc.py .tmp/siano_a.ts .tmp/siano_b.ts

Same device, same mux, same duration; the only difference is whether
``statistics()`` runs every ``--poll`` milliseconds between reads.  Compare the
per-PID CC errors: if A is dirty and B is clean, the poll is what breaks the
stream.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smsrio.cli import open_device  # noqa: E402
from smsrio.device import SmsRio  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run")
    parser.add_argument("--poll", type=int, default=0,
                        help="statistics polling interval in ms, 0 = never")
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--freq", type=int, default=599143)
    parser.add_argument("--timeout", type=float, default=8)
    parser.add_argument("--firmware")
    parser.add_argument("--out")
    args = parser.parse_args()

    out = args.out or (".tmp/siano_%s.ts" % args.label)
    device = open_device(0)
    rio = SmsRio(device, lambda message: print("   " + message, flush=True))
    sink = open(out, "wb")
    polls = 0
    packets = 0
    try:
        rio.bring_up(args.firmware)
        rio.tune(args.freq)
        status = rio.wait_lock(timeout=args.timeout)
        locked = bool(status and status["demod_locked"])
        print("[%s] lock=%s power=%s snr=%s poll=%d ms"
              % (args.label, locked,
                 status["power"] if status else "?", status["snr"] if status else "?",
                 args.poll), flush=True)
        if not locked:
            print("[%s] no lock - stopping" % args.label, flush=True)
            return 1

        started = time.time()
        last_poll = started
        while time.time() - started < args.seconds:
            if args.poll and (time.time() - last_poll) * 1000 >= args.poll:
                try:
                    rio.status()
                    polls += 1
                except Exception as error:
                    print("   poll failed: %s" % error, flush=True)
                last_poll = time.time()
            data = rio.read_ts()
            if data:
                sink.write(data)
                packets += len(data) // 188
    finally:
        sink.close()
        device.close()

    print("[%s] %d packets, %d polls, dropped=%d -> %s"
          % (args.label, packets, polls, getattr(device, "dropped", 0), out),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
