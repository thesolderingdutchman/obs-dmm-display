# DMM Display

A small Flask-based display server for reading measurements from a supported multimeter and exposing them over HTTP for a local overlay or dashboard.

## Current status

### UT161B

- Uses HID USB communication.
- The current implementation sends initialization requests and then polls for live measurement packets.

### UT8802E (WIP)

- The parser and driver structure are implemented but not verified.
- The driver attempts to open a real CP2110-based USB/UART connection when the meter is available.
- If no compatible device is present, the app stays disconnected instead of crashing.
- A packet-hex fallback is also available for testing the parser without hardware.

#### Logging for 8802E

Run the following command to log every frame's hex (plus the decoded mode byte, so we know which capture is which) to a file.

```bash
DMM_8802E_CAPTURE_LOG=ut8802e_capture.log DMM_MODE=ut8802e python dmm.py
```

Switch the meter to hFE (or SCR, or whichever mode you want the code for), let it log a few readings.log. Each line shows the mode byte plus the full frame hex.

#### Optional 8802E test input

If you have a packet captured from the instrument, you can feed it in as hex:

```bash
DMM_MODE=ut8802e DMM_8802E_PACKET_HEX=0201000000000000 python dmm.py
```

This is useful for validating the parsing logic without needing the device connected.

## API

The app exposes a simple JSON endpoint:

- `http://127.0.0.1:8080/data`

The payload contains the latest normalized measurement, for example:

```json
{
  "value": "12.34",
  "unit": "V",
  "mode": "DCV",
  "range": ""
}
```

## Installation

1. Install the native HID library (required by both `pycp2110` and `hid`):
   - **Debian/Ubuntu:** `sudo apt install libhidapi-hidraw0`
   - **Fedora:** `sudo dnf install hidapi`
   - **Arch:** `sudo pacman -S hidapi`
   - **macOS:** `brew install hidapi`
   - **Windows:** no separate install needed — a prebuilt binary is bundled

2. Create and activate a virtual environment:

```bash
   python3 -m venv .venv

   # macOS/Linux
   source .venv/bin/activate
   # Windows (cmd)
   .venv\Scripts\activate
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
```

3. Install Python dependencies:

```bash
   pip install -r requirements.txt
```

4. **Linux only:** the multimeter's USB device usually isn't accessible to a
   non-root user by default. Add a udev rule (see
   https://github.com/libusb/hidapi/blob/master/udev/) or run with `sudo`
   for testing.

## Running the tool

Run the app with a single selected meter mode at startup:

- `DMM_MODE=ut161b python dmm.py`
- `DMM_MODE=ut8802e python dmm.py`

## Development

Run the tests with:

```bash
python -m unittest discover -s tests -v
```

## Acknowledgments

This project's architecture and parts of its code are adapted from:

- [mbraune/ut161b](https://github.com/mbraune/ut161b) (MIT License)
- [philpagel/ut8803e](https://github.com/philpagel/ut8803e) (BSD-3-Clause License)

See `LICENSE.md` for the full license texts.
