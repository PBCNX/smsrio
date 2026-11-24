# Changelog

## 0.2.0 — 2026-11-24

- Recovery is a contract: a detach closes the handle, polls for the stick, rebuilds the session and keeps the same
  output file; a locked-but-silent stick is recovered in place first, then by a fresh handle, and only then asks for
  the cable. `recover` reports which rung worked.
- `play` supervises itself (`--supervise-seconds`), so a pull during a recording no longer ends the run.
- TMCC: mode, guard interval, partial reception, the layers and the EWBS bit, from the demodulator's own statistics;
  an undecoded block is refused instead of printed as a plausible channel.
- `scan`: one line per channel, and a channel counts only when packets actually arrive.
- A stuck, silent channel now gets one hint instead of a traceback: unplug and replug (a USB reset does not clear the
  chip's RAM).
- A wrong or truncated firmware image, a missing image, a busy device and a missing stick each print one line and
  exit non-zero.
- Java: the core, an Android transport, and a provider for the tuner door (`com.pbcnx.tuner`), with the TMCC record in
  the canonical numbering.

## 0.1.1 — 2026-11-04

- macOS and Linux measurements; the writer-thread sink and `--drop-null`.

## 0.1.0 — 2026-10-20

- First working protocol: firmware upload, tune, lock, MPEG-TS read.
