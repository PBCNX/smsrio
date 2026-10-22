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

Expected: `smsrio java self-test: OK`. The self-test needs no device.

## Status

Validated against the Python driver byte for byte; the live stream was proven on
Windows at 509.143 MHz (33,280 packets, 0 sync errors). The Java path has not yet
been run on an Android device.
