# smsrio — Siano SMS-series Rio ISDB-T dongle (`187f:0600`)

User-space driver for the ISDB-T dongle sold as the **Siano MDTV Receiver** (Siano SMS-series Rio). It speaks the
dongle's own USB protocol, uploads its firmware, tunes, and streams MPEG-TS to a file, stdout or UDP; it also reads
the multiplex's transmission parameters (TMCC) from the demodulator's own statistics. Python over libusb (pyusb is
vendored, so there is nothing to install); a dependency-free Java core for Android lives in `java`.

**Our own code, no vendor code.**

## Device

| | |
|---|---|
| USB ID | `187f:0600` |
| Chip | Siano SMS-series Rio ISDB-T demodulator, 6 MHz raster |
| Endpoints | `0x02` OUT commands, `0x81` IN responses **and** MPEG-TS |
| Status | lock, SNR, RSSI, in-band dBm and carrier offset, from the demod's own statistics |
| TMCC | mode, guard interval, partial reception, layers (modulation, code rate, interleave, segments) and the EWBS bit |
| Stream | 20 × 188-byte TS packets per transfer, payload at offset 512 |

## Platforms

Windows (WinUSB), Linux (a Raspberry Pi 5, over SSH) and macOS (Intel) are measured on hardware, including the
recovery suite: cold start, a 20 s stream, three wedge-and-recover cycles, a mid-stream detach with a rebuild, and
an absent stick. Android is measured as a library: this package's provider has opened a stick inside a host app
on Android 14. The adapter under `java/android/` implements the host's tuner contract (`com.pbcnx.tuner`), which
the host application provides; the core under `java/src/` has no dependency at all. No kernel driver is involved: libusb over WinUSB on Windows, udev on Linux, libusb on macOS.

## Install

From a checkout — pyusb is vendored, so no `pip install` is needed.

```bash
python -m smsrio --version      # smsrio 0.2.0 (smsrio-pbcnx)
python -m smsrio list           # finds the 187f devices present
```

- **Windows**: bind the dongle to WinUSB with [Zadig](https://zadig.akeo.ie/) and replug it, then get
  `libusb-1.0.dll` from <https://libusb.info> and set `SMSRIO_LIBUSB` to its full path (or copy it next to
  `python.exe`). Zadig is the device binding; libusb is the library the driver loads.
- **Linux**: `sudo cp udev/99-smsrio.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger`,
  then replug. The rule grants `uaccess` plus group `plugdev` (needed over SSH, where there is no logind seat).
- **macOS**: install libusb (`brew install libusb`); on Apple Silicon use an arm64 Python and libusb.

**Firmware.** The image is not in this repository — it is vendor material. Supply your own with `--firmware PATH`
or `SMSRIO_FIRMWARE`; it is checked for size (91,048 bytes) and SHA-256 before use. `--version` and `list` work
without it; anything that opens the stick needs it.

## Use

```bash
python -m smsrio list
python -m smsrio status --freq 485143
python -m smsrio tmcc   --freq 485143
python -m smsrio play   --freq 485143 --seconds 30 --out capture.ts
python -m smsrio play   --freq 485143 --udp 127.0.0.1:1234 --live
```

`status` prints the demodulator's readings, `tmcc` the transmission parameters, `scan` sweeps a band (one line per
channel, a channel counts only when packets arrive), and `recover` walks the recovery ladder on a locked-but-silent
stick. `play` supervises the session: a pull is detected, the stick is polled for, reopened, brought up and
re-tuned, and the same file keeps being written.

Android / JVM:

```java
Tuner tuner = new SmsRioProvider().open(context, device, firmware, listener);
tuner.open();
tuner.tune(485143);
```

## License

GPL-2.0-or-later — see `LICENSE`. `NOTICE` lists what is not ours.

