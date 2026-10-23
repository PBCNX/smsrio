# smsrio

User-space driver for Siano Rio ISDB-T tuners (`187F:0600`), for Windows, macOS
and Linux through libusb. Python package now; a dependency-free Java core for
Android is in `java/` (same protocol, not yet run on a device).

## Status

| | |
|---|---|
| Control path | version `503`, init mode `578`, PID filter `601`, tune `776` (wire value in Hz) |
| Stream framing | 4,272-byte transfer = 504 pad + 8-byte header + 20 × 188 TS |
| Data message | `607` (`DAB_CHANNEL`) on this firmware, `693` on older captures |
| Validation | 2026-10-21, live 509.143 MHz: 33,280 packets, 0 sync errors, 5.0 Mbps, PAT/PMT, H.264 + audio |
| Hardware | validated on Windows through libusb; macOS and Linux untested |

The device streams by itself once the demod locks, roughly two seconds after a
tune. There is no "start streaming" command.

The stick was last on the bus on 2026-10-21; the validation figures are from
that run and have not been re-measured since.

## Usage

```bash
python -m smsrio list
python -m smsrio status --freq 509143      # lock, SNR, in-band power
python -m smsrio probe  --freq 509143
python -m smsrio play   --freq 509143 --out capture.ts --seconds 10
```

`--freq` is kHz (`509143` is 509.143 MHz); the wire field is Hz and the driver
multiplies. `play` writes a file, stdout (`--out -`) or UDP (`--udp HOST:PORT`).

`status` exits 0 when locked, 2 when the demod does not lock, and 1 when the
device returns no statistics at all. A locked mux reads about -48 to -80 dBm
in-band; a noise floor of about -90 dBm at every frequency means nothing is
being received at that frequency.

## Firmware

The Rio firmware (`isdbt_rio.inp`, 91,048 bytes, SHA-256
`777c9ba2ce44db9e0a90f7207167e9095cc0223be2b2af599f645f1c73d76b14`) is vendor
material and is not distributed. A unit that already runs firmware needs
nothing. A cold unit needs the image, looked up in this order:

1. an explicit path: `--firmware PATH`
2. the `SMSRIO_FIRMWARE` environment variable
3. `<repo>/isdbt_rio.inp`
4. `<repo>/vendor/firmware/isdbt_rio.inp` (present only in the private tree)

The loader refuses an image that is not exactly 91,048 bytes with that hash.

## Test

```bash
python -m unittest discover -s tests
```

The Java core has its own dependency-free self-test; see [`java/README.md`](java/README.md).

## Licence

GPL-2.0 (see `LICENSE`). The vendored pieces keep their own licences:
`vendor/usb` is pyusb (BSD-3-Clause) and `vendor/windows/x64/libusb-1.0.dll`
is libusb (LGPL-2.1), both with their licence text alongside.
