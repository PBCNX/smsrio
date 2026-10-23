# smsrio — Java core (Android)

Pure-JVM Siano Rio driver: firmware loader, message control plane, statistics
and the TS stream framer. No Android dependency; the app supplies a `Transport`
over `UsbDeviceConnection` and owns the USB endpoint read loop.

## API

```java
SmsRioDevice device = new SmsRioDevice(transport);

// cold or warm unit in one call: version, firmware upload if needed, mode
byte[] image = readAsset("isdbt_rio.inp");   // vendor material, user supplied
String version = device.bringUp(image);      // "ISDBT 07.03.58.0 RIO"

device.addPid(0x2000);                       // all PIDs (601), no reply
device.tune(509143);                         // kHz, 13-segment (776)

SmsRioDevice.Statistics status = device.statistics();
if (status.demodLocked) { /* snr, power, carrierOffset, frequency */ }

byte[] ts = device.nextTs(500);              // 3,760 bytes = 20 TS packets
```

`Transport` is `write(byte[], int timeoutMs)` and `read(int maxLength, int
timeoutMs)` over the command endpoint pair (`0x02` out, `0x81` in). A transfer
that returns `null`/empty means a timeout, not an error.

On a warm unit no firmware is needed; `bringUp(null)` then only sets the mode.
The loader mirrors Linux: 240-byte chunks at the image's load address, then
validity, then trigger.

Stream contract: a streaming transfer is 4,272 bytes — 504 bytes of padding, an
8-byte header (`607` `DAB_CHANNEL` on this firmware, `693` on older ones) and
20 × 188-byte TS packets at offset 512. `nextTs` does the framing for you;
`SmsStream` remains for raw transfers and resynchronises if the phase is wrong.

## Test

```bash
javac --release 8 -d out $(find src -name '*.java')
java -cp out ph.pbcnx.smsrio.SelfTest
```

Expected: `smsrio java self-test: OK`. The self-test needs no device. Set
`JAVA_HOME` (or put its `bin` on `PATH`) if `javac` is not found.

## Status

The wire constants, message framing, statistics layout, pending-queue behaviour
and TS framer match the Python driver, and `SelfTest` covers them. These
differences remain, mostly on the cold-boot path:

* `bringUp(image)` reads the version before uploading. Python skips that probe
  when the caller supplies an image, because on a cold ROM the 2 s timeout is a
  cancelled read that can leave the IN pipe halted; Java still pays it. On a warm
  unit given an image, Python uploads anyway and Java does not.
* After the upload Java reads the version immediately; Python waits 0.5 s for
  the device to restart first.
* `request()` reads in 250 ms slices, where Python uses one read for the whole
  budget; Python's comment says cancelling a read to re-issue it can lose the
  reply on Windows.
* `SmsFirmware` validates only that the header length fits the array. Python
  requires exactly 91,048 bytes and the vendor image's SHA-256;
  `SmsFirmware.SIZE` is declared but never checked.
* `version()` trims trailing NUL bytes only; Python trims NULs and whitespace at
  both ends.

`SelfTest` does not exercise `bringUp`, the image check or the resync path, so it
does not prove parity - it proves the control-plane bytes, the pending queue and
the stream framing.

The Java path has not been run on an Android device, so the host `Transport`
implementation is still unexercised. The source compiles with `--release 8`
against the bench JDK and `SelfTest` passes (2026-10-23).
