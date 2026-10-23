# Siano Rio protocol notes

Derived from the Linux `smsusb`, `smscoreapi` and `smsdvb` sources and from a
`usbmon` capture of a working Linux run. The Linux code is GPL-2.0 reference
material; no source is copied into this project's files.

## USB

| | |
|---|---|
| USB ID | `187F:0600` |
| Interface | one vendor-specific interface (class 255), one alternate setting |
| Endpoints | bulk OUT `0x02` (commands/data), bulk IN `0x81` (responses and TS) |
| Max packet | 512 bytes on both endpoints |
| Transfer unit | one Siano message per bulk transfer on the command path |

## Message format

Every message begins with an 8-byte header:

```
u16 msg_type
u8  msg_src_id
u8  msg_dst_id
u16 msg_length    /* whole message, header included */
u16 msg_flags
```

Fields are little-endian. The vendor BDA client sends `src = 201`
(`DVBT_BDA_CONTROL_MSG_ID`) and `dst = 11` (`HIF_TASK`), and the device answers
from 11 to 201. This driver sends `src = 0`; the device accepts it, and replies
are matched on message type, so `src`/`dst` are not inspected.

### Split messages

Streaming transfers set `MSG_HDR_FLAG_SPLIT_MSG` (`0x0004`). The header stays at
offset 0 on the wire; the payload is pushed to
`alignment + ((flags >> 8) & 3) + 8`, where `alignment = max_packet_size - 8 =
504`. That gives the 512-byte prefix:

```
4272-byte transfer = 504 pad | 8 bytes | 3,760 bytes = 20 TS packets
```

`msg_length` is 3,768 (header + payload) and does not count the padding. The
kernel copies the header from offset 0 to offset 504 *after* the URB completes,
which is why a `usbmon` capture shows zeros at 504 while the payload is already
at 512. A parser must therefore read the header at 0 and the payload at 512;
re-reading the header at 504 against a capture yields a zero length.

The streaming message type depends on the firmware build:

| type | name | seen on |
|---|---|---|
| `607` | `MSG_SMS_DAB_CHANNEL` | this unit, `ISDBT 07.03.58.0 RIO` |
| `693` | `MSG_SMS_DVBT_BDA_DATA` | the Linux capture of the same stick |

Both carry the same 3,760-byte payload, so a driver should accept either.

## Bring-up

1. Open the interface and allocate the bulk endpoints.
2. Query the version (`503`). A cold stick answers nothing or reports ROM; load
   `isdbt_rio.inp` with the download sequence (`660` data, validity `662`,
   trigger `664`), and the device restarts itself and answers
   `ISDBT 07.03.58.0 RIO`. The reload messages (`702`/`704`) are declared in
   `firmware.py` but never sent: on this unit the trigger alone restarts it,
   which is the sequence that was validated.
3. Select the mode (`578`, `DEVICE_MODE_ISDBT_BDA = 7`) → `579`.
4. Add a PID filter (`601`, `u32 pid`). The firmware does **not** answer this;
   Linux sends it and carries on, so neither should a host driver.
5. Tune (`776`): `u32 frequency_Hz, u32 bandwidth, u32 12000000, u32 segment`
   → `777`. **The frequency field is Hz, not kHz.** The captured working run
   sends `0x23B63258` = 599,143,000 for 599.143 MHz; sending 599143 tunes a
   thousand times too low and the statistics echo that lower value back. The
   Python and Java APIs take kHz and multiply by 1000.
   `bandwidth = 8` is `BW_ISDBT_13SEG`.
6. Do not wait for a stream command. The device starts pushing TS on its own
   about two seconds after tune: it needs to acquire the signal first. The
   capture locks at 1.0 s and the first transfer arrives at 1.9 s after
   `TUNE_RES`.

## Live validation (Windows, libusb, 2026-10-21)

Tuned to 509.143 MHz (13-segment ISDB-T, 6 MHz):

```
status: rf locked, demod locked, SNR 6 dB, in-band -79 dBm, offset -7.8 kHz
stream: 6,256,640 bytes in 10 s = 33,280 packets, 0 sync errors, 5.0 Mbps
tables: PAT 1680/1683/1688 -> PMT 1210/1130/8137, each H.264 (27) + audio (3)
```

Re-checked 2026-10-23 from the saved capture in `.tmp` (the stick was not on the
bus): 33,280 of 33,280 packets sync at 188-byte boundaries, 0 CC errors, 0 TEI;
PAT programs 1680/1683/1688 point at PMT PIDs 1210/1130/8137, each carrying
`0x1B` (H.264) and `0x03` (audio). That is analysis of the existing file, not a
new measurement.

599.143 MHz, the frequency used for the Linux capture, was off the air that
day: in-band power sat at the noise floor (-90 dBm) and the demod never locked.
A band sweep found real signal elsewhere, so check power before assuming a
driver fault.

## Statistics

`MSG_SMS_GET_STATISTICS_EX_REQ` (`653`) → `654`, payload 288 bytes: a `u32`
request result followed by `struct sms_isdbt_stats_ex`. Word offsets:

| word | field |
|---|---|
| 0 | request result |
| 1 | statistics type (5 on Rio) |
| 2 | full size (284) |
| 3 | `is_rf_locked` |
| 4 | `is_demod_locked` (the lock that matters) |
| 5 | `is_external_lna_on` |
| 6 | SNR, dB |
| 7 | RSSI, dBm |
| 8 | in-band power, dBm |
| 9 | carrier offset, Hz |
| 10 | frequency, Hz (echoes the tune request) |
| 11 | bandwidth, MHz (6 for ISDB-T) |

The statistics response interleaves with TS transfers on the same endpoint, so
the read loop must parse every message and skip the ones it is not waiting for.
A working lock in the capture reads in-band power ≈ -48 dBm at 599.143 MHz; the
noise floor with no antenna connected is ≈ -90 dBm and RSSI stays near -53 dBm.

## Open questions

1. `MSG_SMS_SET_OUTPUT_MODE_REQ` (`584`) is not used by the Linux driver and
   appears to do nothing on this firmware: empty and `u32 0/1/2` payloads get no
   response and do not start or stop the stream.
2. Whether the Rio expects any RF gain setup beyond `is_external_lna_on`; the
   Linux board entry for Rio sets no mtu, no crystal and no GPIOs.

## Reference

Linux mainline: `drivers/media/usb/siano/smsusb.c`,
`drivers/media/common/siano/smscoreapi.c`, `smscoreapi.h`, `sms-cards.c`,
`smsdvb-main.c`.
