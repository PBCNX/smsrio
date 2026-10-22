# smsrio

User-space driver for Siano Rio ISDB-T tuners (`187F:0600`), for Windows, macOS
and Linux through libusb. Python now; a Java core for Android follows the same
protocol notes.

## Status

| | |
|---|---|
| Control path | version `503`, init mode `578`, PID filter `601`, tune `776` (Hz) |
| Stream framing | 4,272-byte transfer = 504 pad + 8-byte header + 20 × 188 TS |
| Data message | `607` (`DAB_CHANNEL`) on this firmware, `693` on older captures |
| Validation | live 509.143 MHz: 33,280 packets, 0 sync errors, 5.0 Mbps, PAT/PMT, H.264 + audio |
| Hardware | working on Windows through libusb |

The device streams by itself once the demod locks, roughly two seconds after a
tune. There is no "start streaming" command.

## Usage

```bash
python -m smsrio list
python -m smsrio status --freq 509143      # lock, SNR, in-band power
python -m smsrio probe  --freq 509143
python -m smsrio play   --freq 509143 --out capture.ts --seconds 10
```

`status` exits 0 when locked, 2 when the demod does not lock. A locked mux reads
about -48 to -80 dBm in-band; a noise floor of about -90 dBm at every frequency
means nothing is being received at that frequency.

## Firmware

The Rio firmware (`isdbt_rio.inp`, 91,048 bytes) is vendor material and is not
distributed. A unit that already runs firmware needs nothing; a cold unit needs
the image supplied by the user.

## Test

```bash
python -m unittest discover -s tests
```

## Licence

GPL-2.0 (see `LICENSE`). The vendored pieces keep their own licences:
`vendor/usb` is pyusb (BSD-3-Clause) and `vendor/windows/x64/libusb-1.0.dll`
is libusb (LGPL-2.1), both with their licence text alongside.
