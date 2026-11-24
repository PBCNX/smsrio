# How to use the Siano Rio driver

This guide is for anyone who has the stick and wants to watch or record TV with it. You do not need to be a
programmer. Follow the numbered steps in order.

---

## 1. What you need

1. The stick itself. It is sold as the **Siano MDTV Receiver** and contains the **Siano SMS-series Rio** chip. Its USB
   ID is `187f:0600`.
2. A computer running Windows, Linux or macOS with **Python 3.9 or newer**. Typing `python --version` should show that
   number, or higher.
3. The **firmware file** for this stick. The stick is blank when it is first plugged in, and this file is what brings it
   to life. Section 2 tells you exactly where to put it.
4. The driver itself: this repository, downloaded as a ZIP or cloned with git.

You do **not** need to run `pip install`. Everything the driver needs to talk to the stick is already in the folder.

---

## 2. Where to put the firmware file

This file is the manufacturer's, and this repository never ships it. You get it from vendor software you already have
(the app that came with the stick): find its file — it is **91,048 bytes** — copy it somewhere you will remember, and
tell the driver where it is. The driver looks for it in this order and stops at the first one it finds:

1. **On the command line, for one run.** Add `--firmware PATH` **after** the command name; it wins over the other two.

   ```powershell
   python -m smsrio play --firmware "C:\Users\you\Downloads\isdbt_rio.inp" --freq 485143 --out capture.ts
   ```

2. **In an environment variable, for every run.** Set `SMSRIO_FIRMWARE` to the full path of the file.

   ```powershell
   setx SMSRIO_FIRMWARE "C:\Users\you\Downloads\isdbt_rio.inp"
   ```

   ```bash
   export SMSRIO_FIRMWARE="$HOME/Downloads/isdbt_rio.inp"
   ```

   On Windows you can also use *System properties → Environment Variables*. `setx` only affects terminals you open
   afterwards; close the window and open a new one.

3. **In the driver's own folder, as the default.** Put the file at the top of this repository, named exactly
   `isdbt_rio.inp`. Nothing else needs to be set, and every command will find it.

**On Android** there is no file path: the app supplies the image itself. It asks the user for the file once, keeps it,
and passes it to the driver when it opens the stick.

The driver checks the file before it uses it: the image must be **91,048 bytes** with a known **SHA-256 fingerprint**.
A file that does not match is refused, not written to the stick. If that happens you see one line:

```text
smsrio: not the expected 91,048-byte isdbt_rio.inp
```

**You can do a little without this file.** `--version` and `list` work without it. Tuning and playing need it, because
the stick cannot receive until it has been loaded.

---

## 3. Install

Open a terminal in the folder you downloaded, and stay in that folder for every command in this guide.

### Windows

Windows needs two different things, and one is not the other: **Zadig** tells Windows which driver to use for the
stick, and **libusb** is the library the driver itself loads. Do both.

1. Plug in the stick.
2. Download **Zadig** from <https://zadig.akeo.ie/> and run it.
3. In Zadig, open the drop-down list, choose the device whose USB ID is `187f:0600`.
4. Set the driver on the right to **WinUSB** and click **Install Driver**. Wait for "The driver was installed
   successfully".
5. Unplug the stick and plug it in again. You do this only once.
6. Get **libusb** from <https://libusb.info> (Downloads → Windows), and unzip it. You need the file `libusb-1.0.dll`
   from the 64-bit folder.
7. Put that file where the driver looks for it. The simplest way is to point the driver at it:

   ```powershell
   setx SMSRIO_LIBUSB "C:\path\to\libusb-1.0.dll"
   ```

   (Copying `libusb-1.0.dll` next to `python.exe` works too, and needs no variable.) Close the terminal and open a new
   one, because `setx` only affects terminals opened afterwards.
8. Run `python -m smsrio list` (section 4). You should see the stick, or `no 187f devices found` if it is not plugged
   in. Either answer means libusb was found; the error in section 8 means it was not.

### Linux

1. Copy the rule that lets your user reach the stick without being root:

   ```bash
   sudo cp udev/99-smsrio.rules /etc/udev/rules.d/
   sudo udevadm control --reload
   sudo udevadm trigger
   ```

2. Unplug the stick and plug it in again.
3. If you are connected over SSH (no desktop session logged in), add your user to the `plugdev` group with
   `sudo usermod -aG plugdev $USER`, then log out and back in.

   If your distribution loads its own driver for this stick (`smsusb`), the driver cannot claim it. Blacklist that
   module once, then replug:

   ```bash
   echo 'blacklist smsusb' | sudo tee /etc/modprobe.d/blacklist-siano.conf
   sudo modprobe -r smsusb
   ```

### macOS

1. Install libusb with Homebrew: `brew install libusb`.
2. On an Apple Silicon Mac, use an arm64 build of Python. A Python running under Rosetta will report that the USB
   backend is missing.

---

## 4. First run

Two commands tell you whether everything is in place. Run them in this order.

1. **Check the version.**

   ```bash
   python -m smsrio --version
   ```

   A good answer is one line:

   ```text
   smsrio 0.2.0 (smsrio-pbcnx)
   ```

2. **Find the stick.**

   ```bash
   python -m smsrio list
   ```

   A good answer names the stick and its address, for example:

   ```text
   187f:0600  bus 1 addr 5  supported
   ```

   If it says `no 187f devices found`, the stick is not plugged in, or Windows has not been told to use WinUSB for it
   (section 3). If it says the USB backend is unavailable, do step 6 of section 3.

---

## 5. Watch or record

The stick tunes to one channel at a time. A frequency is given in kHz, so `485143` means 485.143 MHz.

1. **Tune and see if there is a signal.**

   ```bash
   python -m smsrio status --freq 485143
   ```

   A good answer includes the firmware version, `rf: True`, `demod: True` and a signal-to-noise reading:

   ```text
   version:    ISDBT 07.03.58.0 RIO
   rf:         True
   demod:      True
   snr:        22 dB
   rssi:       -42 dBm
   in-band:    -56 dBm
   carrier:    -4332 Hz
   frequency:  485143000 Hz
   bandwidth:  6 MHz
   ```

   `demod: False` means the channel is empty or the signal is too weak where you are. Try another frequency, move the
   antenna, or use `python -m smsrio scan --start 473143 --stop 509143 --step 6000 --seconds 2` to look across the band.

2. **Record 30 seconds to a file.**

   ```bash
   python -m smsrio play --freq 485143 --seconds 30 --out capture.ts
   ```

   You get `capture.ts` in the current folder. Any player that reads MPEG-TS can open it. Press `Ctrl-C` to stop early.

3. **Watch live in VLC, over UDP.** In one terminal:

   ```bash
   python -m smsrio play --freq 485143 --udp 127.0.0.1:1234
   ```

   And in a second terminal, or in VLC's *Open Network Stream* box:

   ```bash
   vlc udp://@:1234
   ```

   The picture appears in VLC within a few seconds. Stop the first command with `Ctrl-C` and VLC stops on its own.

4. **If your player stutters**, add `--live`. It drops a little data rather than pausing the stick, which keeps the
   picture moving on a slow computer.

   ```bash
   python -m smsrio play --freq 485143 --udp 127.0.0.1:1234 --live
   ```

5. **If you pull the stick during a recording**, the driver notices, waits ten seconds for it to come back, rebuilds the
   session and keeps writing the same file. If it does not come back, it says so once and stops.

---

## 6. TV signal info

Broadcasters describe how their signal is built. The stick reads that description from the air, and `tmcc` prints it:

```bash
python -m smsrio tmcc --freq 485143
```

You get one line that starts like this (the values depend on the channel):

```text
485143 kHz tmcc mode 8K (3) guard 1/4 (4) partial 1 layers 2 L0:QPSK 1seg code 2/3 (1) I4 L1:QPSK 12seg code 2/3 (1) I4
```

- **mode** — how many carriers the channel uses (2K, 4K or 8K). It is a property of the broadcast, not something you
  choose.
- **guard** — the spacing between carriers, shown as a fraction such as `1/4`. Larger guards survive echoes better,
  which matters in cities and in moving vehicles.
- **partial** — `1` means the channel also carries a small low-resolution service for phones, alongside the main
  program.
- **L0 / L1 / L2** — the layers of the channel. Each layer has a modulation (how densely the signal is packed), a
  number of segments (how much of the channel it occupies), a code rate (how much error correction it carries) and an
  interleave depth.

If it says `tmcc not decoded yet`, the stick has a signal but has not read the description yet. Tune again, and give
it a second or two.

---

## 7. Android

The same driver exists for Android as a small Java library, so an app can list, tune and play without writing the USB
protocol itself. The app opens the stick through the provider, hands it the firmware image (section 2), tunes a
frequency, and receives the video stream as it arrives. `java/` holds the core and the Android adapter; `README.md`
shows the four lines of Java an app needs. Nothing in this folder has to be built to use the command line on a
computer.

---

## 8. When something goes wrong

Each of these is the exact first line the driver prints, what it means, and what to do about it.

| What you see | What it means | What to do |
|---|---|---|
| `smsrio: transport error: libusb backend unavailable` | Your computer has no USB library the driver can use. | Windows: get `libusb-1.0.dll` from <https://libusb.info> and set `SMSRIO_LIBUSB` to its path (section 3, steps 6-7). macOS: `brew install libusb`. Linux: install `libusb-1.0-0`. |
| `smsrio: no Siano Rio (187f:0600) found; bind it to WinUSB first` | The stick is not visible to the driver. | Plug it in. On Windows, bind it to WinUSB with Zadig first. On Linux, install the udev rule and replug. |
| `smsrio: cannot claim the Siano Rio device: ...` | Another program is using the stick, or your user is not allowed to. | Close other TV programs. On Linux, install the udev rule (section 3) and replug; over SSH add your user to `plugdev`. If a kernel driver holds it, blacklist it (section 3, Linux). |
| `smsrio: Siano firmware not found at <path>; supply the vendor isdbt_rio.inp` | The firmware file is missing, or the driver looked in the wrong place. | Section 2: the three places it looks, in order. |
| `smsrio: not the expected 91,048-byte isdbt_rio.inp` | The file exists but it is not the image this stick needs. | Check that you copied the file from the vendor app for this stick, and that the copy is complete. |
| `485143 kHz tmcc not decoded yet (no layer segments ...)` | There is a signal, but the transmission parameters have not been read yet. | Tune again and give it a second. If it persists, the channel is very weak. |
| `no statistics from the device` | The stick stopped answering. | Unplug it, plug it in again and retry. |
| `locked but no TS for <n> s - the recovery was tried ...` | The stick is locked but is not delivering video, and the recovery ladder could not fix it. | Unplug the stick and plug it in again: a reset in software does not clear the chip's memory. |
| `no lock on ...` in a recording's log | A channel change landed on an empty channel. | Try another frequency; the recording continues. |

---

## 9. Getting help

Open an issue at <https://github.com/PBCNX/smsrio/issues>. Please say which command you ran, what it printed, and
whether `python -m smsrio list` finds the stick. That last answer tells us whether the problem is the stick or the
computer.
