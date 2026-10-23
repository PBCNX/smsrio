"""Wait for a replug, then run the A/B measurement end to end.

    python tools/siano_run.py --firmware vendor/firmware/isdbt_rio.inp \
        --freq 599143 --seconds 20

It arms, waits for the device address to change (a physical replug), then runs
capture A with statistics polling every 500 ms and capture B with none, and
finally reports per-PID CC errors for both.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smsrio.cli import open_device  # noqa: E402
from smsrio.device import SmsRio  # noqa: E402
from smsrio.transport import devices  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def addresses():
    try:
        return [(d.bus, d.address) for d in devices()]
    except Exception:
        return []


def wait_for_replug(timeout=240):
    before = addresses()
    print("current device(s): %s" % before, flush=True)
    print(">>> replug the Siano now <<<", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(0.2)
        now = addresses()
        if now and now != before:
            print("replug seen: %s" % now, flush=True)
            # let the ROM finish enumerating before the first request
            time.sleep(2.0)
            return True
    print("no replug seen", flush=True)
    return False


def capture(label, poll_ms, seconds, freq, firmware, out):
    device = open_device(0)
    rio = SmsRio(device, lambda message: print("    " + message, flush=True))
    sink = open(out, "wb")
    polls = 0
    packets = 0
    try:
        rio.bring_up(firmware)
        rio.tune(freq)
        status = rio.wait_lock(timeout=8)
        print("[%s] lock=%s power=%s"
              % (label, bool(status and status["demod_locked"]),
                 status["power"] if status else "?"), flush=True)
        if not (status and status["demod_locked"]):
            return None
        started = time.time()
        last_poll = started
        while time.time() - started < seconds:
            if poll_ms and (time.time() - last_poll) * 1000 >= poll_ms:
                try:
                    rio.status()
                    polls += 1
                except Exception as error:
                    print("    poll failed: %s" % error, flush=True)
                last_poll = time.time()
            data = rio.read_ts()
            if data:
                sink.write(data)
                packets += len(data) // 188
    finally:
        sink.close()
        device.close()
    print("[%s] %d packets, %d polls, dropped=%d"
          % (label, packets, polls, getattr(device, "dropped", 0)), flush=True)
    return packets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--freq", type=int, default=599143)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--firmware", required=True)
    args = parser.parse_args()

    if not wait_for_replug():
        return 1

    a = os.path.join(REPO, "..", ".tmp", "siano_a.ts")
    b = os.path.join(REPO, "..", ".tmp", "siano_b.ts")
    first = capture("A poll 500ms", 500, args.seconds, args.freq, args.firmware, a)
    if first is None:
        print("A did not lock - stopping", flush=True)
        return 1
    capture("B no poll", 0, args.seconds, args.freq, args.firmware, b)

    os.system('python "%s" "%s" "%s"'
              % (os.path.join(REPO, "..", "tools", "ts_cc.py"), a, b))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
