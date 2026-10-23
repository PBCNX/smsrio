# smsrio - START HERE

User-space driver for the Siano SMS-series Rio ISDB-T tuner (`187F:0600`), part
of the `sticks` workspace. Python for Windows/macOS/Linux through libusb; a
dependency-free Java core for Android in `java/`. GPL-2.0.

This file is the brief. `README.md` is for users, `docs/protocol.md` for the
wire format, `java/README.md` for the Android core.

## Bench state - 2026-10-23

* **The stick is not on the bus.** `python -m smsrio list` prints
  `no 187f devices found`. Nothing in this repo can be re-proved against
  hardware today; every hardware statement below is dated.
* **Python 3.14.3**: `python -m unittest discover -s tests` -> 18 tests, OK.
* **Java**: a JDK is installed on the bench but not on `PATH`. With
  `JAVA_HOME` set, `javac --release 8` compiles the source and `SelfTest`
  passes (verified 2026-10-23). See "Java parity" below.
* **Last hardware session**: 2026-10-21, Windows + libusb, 509.143 MHz.

## What is proven

### Control path

Every message is an 8-byte header `<type u16><src u8><dst u8><length u16><flags
u16>` (little-endian), `dst = 11` (`HIF_TASK`). This driver sends `src = 0`; the
vendor BDA client sends 201. Replies are matched on type only.

| request | reply | payload | notes |
|---|---|---|---|
| version `503` | `504` | empty | ASCII, e.g. `ISDBT 07.03.58.0 RIO`; a cold ROM stays silent |
| init `578` | `579` | `u32 mode` | `7` = `DEVICE_MODE_ISDBT_BDA` |
| add PID `601` | **none** | `u32 pid` | firmware does not answer; do not wait |
| tune `776` | `777` | `u32 Hz, u32 bandwidth, u32 12000000, u32 segment` | `bandwidth = 8` = 13-segment; **wire is Hz** |
| statistics `653` | `654` | 288 B | 12 words used, below |
| data | - | - | `607` on this firmware, `693` on older captures |

Statistics word offsets, signed for words 6-9: 0 result, 1 type (5), 2 full size
(284), 3 rf locked, 4 **demod locked**, 5 external LNA, 6 SNR dB, 7 RSSI dBm,
8 in-band power dBm, 9 carrier offset Hz, 10 frequency Hz (echoes the request),
11 bandwidth MHz. The driver only requires the first 12 words (48 bytes).

The Python/Java API takes **kHz** and multiplies by 1000. Sending 599143 on the
wire tunes a thousand times too low, and the statistics echo that lower value
back - a convincing false negative.

### Framing

```
4,272-byte transfer = 504 pad | 8-byte header | 3,760 bytes = 20 x 188 TS
```

The header stays at offset 0 on the wire; payload starts at 512. `msg_length` is
3,768 (header + payload) and does not count the padding. A split transfer has
`flags & 0x0004`, and the payload offset is `alignment + ((flags >> 8) & 3) + 8`,
where `alignment = max_packet_size - 8 = 504`. A `usbmon` capture shows zeros at
504 because the kernel copies the header there only after the URB completes;
never parse the header at 504.

### Firmware load

`isdbt_rio.inp` is 91,048 bytes: 12-byte header (checksum, payload 91,036,
start `0x40260`) plus payload. SHA-256
`777c9ba2ce44db9e0a90f7207167e9095cc0223be2b2af599f645f1c73d76b14`; `load()`
refuses anything else. The private tree tracks it at `vendor/firmware/`;
the public snapshot withholds it.

Upload is serial, one chunk at a time: 240-byte chunks carrying a `u32`
destination address (message `660`, ack `661`), then validity `662`
(start, length, 0, ack `663`), then trigger `664`
(start, 6, 0x200, 0, 4, ack `665`). The device restarts itself; the driver waits
0.5 s and reads the version. Messages `702`/`704` are declared but **never sent**
- the trigger alone is the sequence that was validated.

### The validated run - 2026-10-21, Windows

509.143 MHz, 13-segment ISDB-T, 6 MHz:

```
status: rf locked, demod locked, SNR 6 dB, in-band -79 dBm, offset -7.8 kHz
stream: 6,256,640 bytes in 10 s = 33,280 packets, 0 sync errors, 5.0 Mbps
tables: PAT 1680/1683/1688 -> PMT 1210/1130/8137, each H.264 (27) + audio (3)
```

599.143 MHz - the frequency of the Linux capture - was **off the air that day**
(noise floor, no lock). A sweep found real signal at 509.143. So do not treat a
failure at 599.143 as a driver fault; check in-band power first.

The saved capture `.tmp/siano_live.ts` is exactly 6,256,640 bytes. On 2026-10-23
it was re-checked as a file, not as a new run: 33,280 packets, every 188-byte
boundary is `0x47`, 0 CC errors, 0 TEI, and the PAT/PMT map above. That is the
strongest evidence still reproducible without the stick.

### What was never verified

macOS and Linux have not been run. The Java core has not been run on Android.
Only Windows + libusb has streamed TS from this driver.

## Commands

```bash
cd smsrio
python -m smsrio list
python -m smsrio status --freq 509143      # lock, SNR, in-band power
python -m smsrio probe  --freq 509143
python -m smsrio play   --freq 509143 --out capture.ts --seconds 10
python -m unittest discover -s tests
```

* `--freq` is **kHz**. `status` exits 0 locked, 2 no demod lock, 1 no statistics.
* `play --out -` writes to stdout; `--udp HOST:PORT` streams UDP.
* Firmware lookup order: `--firmware PATH`, `SMSRIO_FIRMWARE`, `<repo>/isdbt_rio.inp`,
  `<repo>/vendor/firmware/isdbt_rio.inp` (private tree only).
* Windows needs the stick bound to WinUSB (Zadig) first; the driver picks the
  bundled `vendor/windows/x64/libusb-1.0.dll`, `SMSRIO_LIBUSB` overrides it.
* Java self-test (the JDK is not on `PATH`; set `JAVA_HOME` first; needs no
  device):
  `& "$env:JAVA_HOME\bin\javac.exe" --release 8 -d java\out (Get-ChildItem java\src -Recurse -Filter *.java).FullName`
  then `& "$env:JAVA_HOME\bin\java.exe" -cp java\out ph.pbcnx.smsrio.SelfTest`
  -> `smsrio java self-test: OK`.

## Closed - do not re-open

* **No "start streaming" command.** The device starts pushing TS itself about
  2 s after `TUNE_RES`; the capture locked at 1.0 s and the first transfer
  arrived at 1.9 s. `MSG_SMS_SET_OUTPUT_MODE` (`584`) does nothing here.
* **`607` is correct on this firmware.** Older captures use `693`; both carry
  the same 3,760-byte payload and the driver accepts either. Do not "fix" 607.
* **The prefix is 504 pad + 8 header.** It is not an opaque 512-byte header, and
  the header is not at 504 on the wire.
* **Clearing halts at open** was removed: it is a needless request on a fresh
  ROM, and a halt that matters is recovered per read instead. Keep it removed and
  keep the per-read recovery.
* **Short read windows for ROM acks** were a dead end on a healthy ROM. One read
  with the whole budget per chunk is what works; do not reintroduce 80 ms polls.
* **Do not probe the version before uploading** when the caller supplies an
  image. A cold ROM's 2 s timeout is a cancelled read that can halt IN and make
  the upload look dead.
* **One chunk at a time.** Pipelining (`window = 8`) starved the ack path.
* **702/704 are not part of this sequence.**
* **A statistics poll must cost zero TS packets.** Skipped messages go on a
  bounded queue (`PENDING_LIMIT = 512`) and are returned by the next read;
  overflow increments `dropped`/`droppedTransfers()` and is never silent.
* **No features.** This driver works. Anything new needs a reason and hardware.

## Traps

* Statistics replies, indications and TS share bulk-IN `0x81`. **Single reader**:
  `nextTs`/`read_ts` and `statistics` from one thread, or one lock. Two readers
  each take transfers the other wanted, and the poll then times out.
* `read_ts()` returns `b""` for non-data messages; a statistics *reply* is
  consumed by `statistics()`, not by the stream reader.
* On Windows a timed-out bulk read can leave IN halted, after which every read
  fails instantly. `_read` clears the halt once and retries - do not remove it.
* `open_device()` claims interface 0. `close()` releases it; open one handle per
  run in the CLI.
* `python -m smsrio play` without `--seconds` runs until interrupted.
* `.tmp/` is scratch: captures, probes and old images. Never commit `.ts`,
  `.pcap` or `.inp`; `release.ps1` withholds `*.inp`, `*.ts`, `*.pcap` and
  `*firmware*.bin`, and the public snapshot is currently 48 files with no leak.
* Never run `release.ps1` against `public` as a test. Use a throwaway clone with
  the two `git push` lines replaced by `echo`.

## Java parity

Read `java/src` alongside `smsrio/`. What matches: message constants and header
build/parse, split payload at 512, statistics layout and signedness, the pending
queue (limit 512, counted drops), the 4,272/3,760 stream framer, and the 240-byte
chunk / validity / trigger upload bytes.

What does **not** match:

1. `bringUp(image)` reads the version before uploading; Python skips that probe
   whenever an image is supplied (see "Closed" above). Java still pays the 2 s
   cancelled read on a cold unit. Conversely, on a warm unit given an image,
   Python uploads anyway and Java does not.
2. After the upload Java reads the version immediately; Python sleeps 0.5 s for
   the restart first.
3. `request()` reads in 250 ms slices; Python uses one read for the whole budget
   (`14419be`). The Java comment gives no reason for the cap, and Python's
   comment says cancelling a read to re-issue it can lose the reply on Windows.
4. Image validation: `SmsFirmware` checks only that `HEADER + length` fits the
   array. Python requires exactly 91,048 bytes and the SHA-256. `SmsFirmware.SIZE`
   is declared but never checked.
5. `version()` trims trailing NULs only; Python trims NULs and whitespace at both
   ends.
6. `SmsStream.resync` accepts a lone final `0x47`; Python requires two
   consecutive sync bytes and excludes the last offset.
7. Python `tune()` also sends `add_pid(0x2000)`; Java `tune()` does not, so the
   app must call `addPid(0x2000)` first (the README example does).

`SelfTest` proves the control-plane bytes (version, init, PID, tune Hz),
statistics fields, split parsing, the pending queue under a busy stream, the
stream framer and the firmware frame addresses/lengths/trigger. It does **not**
exercise `bringUp`, the cold path, image size/hash checking, resync, version
trimming or the overflow counter - so it does not prove parity.

## Next, in order

1. **Java parity**: a JDK is available, so fix at least items 1, 2 and 4 (cold
   path and image check), compile with `--release 8`, run `SelfTest`, and add
   tests for `bringUp` and the image check.
2. **If the stick returns**: confirm `status` at a frequency known to be on air,
   then record date, packets, sync/CC errors and bitrate in `README.md` and
   `docs/protocol.md` - as a new measurement, with its date.
3. Keep the README numbers equal to what the code does. If a number changes,
   change it in `README.md`, `docs/protocol.md` and this file in the same commit.
4. Nothing else. No features without a reason.

## Rules for this repo

* **GPL-2.0.** Do not copy code into the MIT trees (`it9308`, `it9309`); facts
  and values are fine. Do not take MIT code into this tree.
* **Vendor material stays private.** `vendor/firmware/isdbt_rio.inp` is tracked
  in the private tree only; never `git push public main` (the release snapshot
  withholds it).
* **The device is absent.** Do not restate 2026-10-21 measurements as fresh ones;
  date every hardware claim.
* **Measure, do not infer.** A capture is evidence; a model is not.
* `coordination/` and `.tmp/` are local notes, not repo content.

## Map

| path | role |
|---|---|
| `smsrio/transport.py` | USB open, message send/receive, split parse, requests, statistics |
| `smsrio/firmware.py` | image lookup/validation and the family-2 upload |
| `smsrio/device.py` | bring-up, tune, lock polling, `read_ts` |
| `smsrio/stream.py` | 4,272-byte transfer framer |
| `smsrio/cli.py` | `list`, `status`, `probe`, `play` |
| `tests/` | 5 files, 18 tests, no hardware |
| `tools/` | 5 one-off probes (upload, pipeline, recover, A/B, replug runner) |
| `java/src` | Android core: `SmsRioDevice`, `SmsProtocol`, `SmsStream`, `SmsFirmware`, `SelfTest` |
| `docs/protocol.md` | wire format, bring-up, statistics, capture evidence |
