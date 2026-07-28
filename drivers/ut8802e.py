"""UNI-T UT8802E USB/HID driver.

The UT8802E uses fixed eight-byte UART frames behind a Silicon Labs CP2110
USB/HID bridge.  It does not use the variable-length AB CD framing used by the
UT8803E.
"""

import os
import struct
import time
from typing import Any, Dict, Optional

import hid


CAPTURE_LOG_PATH = os.environ.get("DMM_8802E_CAPTURE_LOG")
FRAME_MAGIC = 0xAC
FRAME_LENGTH = 8
FRAME_WAIT_SECONDS = 0.45
STALE_MEASUREMENT_SECONDS = 0.75
CP2110_VID = 0x10C4
CP2110_PID = 0xEA80
REPORT_UART_ENABLE = 0x41
REPORT_PURGE_FIFOS = 0x43
REPORT_UART_CONFIG = 0x50
STATUS_OVERLOAD = 0x40


# mode code: (display mode, display unit, selected range)
MODE_INFO = {
    # DC voltage
    0x01: ("DCmV", "mV", "200mV"),
    0x03: ("DCV", "V", "2V"),
    0x04: ("DCV", "V", "20V"),
    0x05: ("DCV", "V", "200V"),
    0x06: ("DCV", "V", "1000V"),
    # AC voltage
    0x09: ("ACV", "V", "2V"),
    0x0A: ("ACV", "V", "20V"),
    0x0B: ("ACV", "V", "200V"),
    0x0C: ("ACV", "V", "750V"),
    # DC current
    0x0D: ("DCµA", "µA", "200µA"),
    0x0E: ("DCmA", "mA", "2mA"),
    0x11: ("DCmA", "mA", "20mA"),
    0x12: ("DCmA", "mA", "200mA"),
    0x16: ("DCA", "A", "20A"),
    # AC current
    0x10: ("ACmA", "mA", "2mA"),
    0x13: ("ACmA", "mA", "20mA"),
    0x14: ("ACmA", "mA", "200mA"),
    0x18: ("ACA", "A", "20A"),
    # Resistance
    0x19: ("RES", "Ω", "200Ω"),
    0x1A: ("RES", "kΩ", "2kΩ"),
    0x1B: ("RES", "kΩ", "20kΩ"),
    0x1C: ("RES", "kΩ", "200kΩ"),
    0x1D: ("RES", "MΩ", "2MΩ"),
    0x1F: ("RES", "MΩ", "200MΩ"),
    # Other functions
    0x22: ("Duty", "%", ""),
    0x23: ("Diode", "V", ""),
    0x24: ("Cont", "Ω", ""),
    0x25: ("hFE", "", ""),
    0x27: ("CAP", "nF", ""),
    0x28: ("CAP", "µF", ""),
    0x29: ("CAP", "mF", ""),
    0x2A: ("SCR", "V", ""),
    0x2B: ("FREQ", "Hz", ""),
    0x2C: ("FREQ", "kHz", ""),
    0x2D: ("FREQ", "MHz", ""),
}


def log_capture(frame: bytes) -> None:
    if not CAPTURE_LOG_PATH:
        return
    line = f"{time.strftime('%H:%M:%S')} frame={frame.hex()}\n"
    try:
        with open(CAPTURE_LOG_PATH, "a", encoding="utf-8") as capture_file:
            capture_file.write(line)
    except Exception as exc:
        print(f"[Capture] failed to write {CAPTURE_LOG_PATH}: {exc}")


def log_raw_report(report: bytes) -> None:
    if not CAPTURE_LOG_PATH:
        return
    line = f"{time.strftime('%H:%M:%S')} hid_report={report.hex()}\n"
    try:
        with open(CAPTURE_LOG_PATH, "a", encoding="utf-8") as capture_file:
            capture_file.write(line)
    except Exception as exc:
        print(f"[Capture] failed to write {CAPTURE_LOG_PATH}: {exc}")


def verify_checksum(frame: bytes) -> bool:
    """UT8802E checksum is the low seven bits of the first seven bytes."""
    return (
        len(frame) == FRAME_LENGTH
        and frame[0] == FRAME_MAGIC
        and (sum(frame[:7]) & 0x7F) == frame[7]
    )


def _decode_bcd(value: int) -> Optional[int]:
    high = (value >> 4) & 0x0F
    low = value & 0x0F
    if high > 9 or low > 9:
        return None
    return high * 10 + low


def parse_packet(frame: bytes) -> Optional[Dict[str, Any]]:
    """Decode one native UT8802E eight-byte measurement frame."""
    if len(frame) != FRAME_LENGTH or frame[0] != FRAME_MAGIC:
        return None
    if not verify_checksum(frame):
        print("[Hardware] UT8802E checksum mismatch, dropping packet")
        return None

    mode_name, unit, range_name = MODE_INFO.get(
        frame[1],
        (f"UNKNOWN (0x{frame[1]:02x})", "", ""),
    )

    # Captured UT8802E packets set bit 6 of the status byte when the
    # input is open/over-range. The digit bytes still contain a changing
    # numeric pattern in that state and must not be displayed.
    if frame[6] & STATUS_OVERLOAD:
        return {
            "value": "OL",
            "unit": unit,
            "mode": mode_name,
            "range": range_name,
        }

    low_digits = _decode_bcd(frame[2])
    middle_digits = _decode_bcd(frame[3])
    high_digit = frame[4] & 0x0F
    decimal_places = frame[5] - ord("0")

    # The meter uses a non-numeric digit pattern for an open input/overload.
    # It can also encode the first count above its 19,999-count display range.
    # Both cases must be shown as OL instead of retaining the previous reading.
    invalid_digits = (
        low_digits is None
        or middle_digits is None
        or high_digit > 9
        or not 0 <= decimal_places <= 9
    )
    raw_value = 0
    if not invalid_digits:
        raw_value = low_digits + middle_digits * 100 + high_digit * 10000

    if invalid_digits or raw_value > 19999:
        return {
            "value": "OL",
            "unit": unit,
            "mode": mode_name,
            "range": range_name,
        }

    numeric_value = raw_value / (10 ** decimal_places)
    if frame[6] & 0x80:
        numeric_value = -numeric_value

    value_text = f"{numeric_value:.{decimal_places}f}"

    return {
        "value": value_text,
        "unit": unit,
        "mode": mode_name,
        "range": range_name,
    }


class CP2110Transport:
    def __init__(self) -> None:
        self.device: Optional[Any] = None
        self._buffer = bytearray()

    def connect(self) -> None:
        if self.device is not None:
            return
        if not hasattr(hid, "device"):
            raise RuntimeError(
                "Wrong 'hid' package loaded. Uninstall packages 'hid' and "
                "'pycp2110'; keep the 'hidapi' wheel installed."
            )

        self.device = hid.device()
        self.device.open(CP2110_VID, CP2110_PID)

        # CP2110 UART configuration: 9600 baud, 8 data bits, no parity,
        # one stop bit, no flow control. This follows Silicon Labs AN434
        # and pySerial's cython-hidapi CP2110 backend.
        uart_config = struct.pack(
            ">BLBBBB",
            REPORT_UART_CONFIG,
            9600,
            0x00,
            0x00,
            0x03,
            0x00,
        )
        self.device.send_feature_report(uart_config)
        self.device.send_feature_report(
            bytes((REPORT_UART_ENABLE, 0x01))
        )
        self.device.send_feature_report(
            bytes((REPORT_PURGE_FIFOS, 0x03))
        )
        print("[Hardware] UT8802E transport connected")

    def close(self) -> None:
        if self.device is None:
            return
        try:
            self.device.send_feature_report(
                bytes((REPORT_PURGE_FIFOS, 0x03))
            )
        except Exception:
            pass
        try:
            self.device.close()
        except Exception:
            pass
        self.device = None
        self._buffer.clear()

    def read_packet(self) -> Optional[bytes]:
        if self.device is None:
            try:
                self.connect()
            except Exception as exc:
                print(f"[Hardware] UT8802E connection failed: {exc}")
                return None

        # A CP2110 report begins with the exact UART payload length. cython-
        # hidapi returns only the bytes received, unlike the old pyhidapi
        # wrapper which exposed a 64-byte buffer containing stale tail data.
        # Collect short reports until one complete eight-byte DMM frame exists.
        deadline = time.monotonic() + FRAME_WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                report = self.device.read(64, timeout_ms=100)
            except Exception as exc:
                print(f"[Hardware] UT8802E read failed: {exc}")
                self.close()
                return None

            if report:
                report = bytes(report)
                log_raw_report(report)

                byte_count = report[0]
                if not 1 <= byte_count <= 63:
                    print(
                        f"[Hardware] UT8802E invalid CP2110 report length: "
                        f"{byte_count}"
                    )
                    continue
                if len(report) < byte_count + 1:
                    print(
                        f"[Hardware] UT8802E truncated CP2110 report: "
                        f"header says {byte_count}, HIDAPI returned only "
                        f"{len(report) - 1} payload bytes"
                    )
                    continue

                # On Windows, HIDAPI can return the complete 64-byte input
                # buffer even when the CP2110 header announces fewer UART
                # bytes. The tail is padding/stale memory and must be ignored.
                self._buffer.extend(report[1 : byte_count + 1])

            while len(self._buffer) >= FRAME_LENGTH:
                try:
                    start = self._buffer.index(FRAME_MAGIC)
                except ValueError:
                    self._buffer.clear()
                    break

                if start:
                    del self._buffer[:start]
                if len(self._buffer) < FRAME_LENGTH:
                    break

                frame = bytes(self._buffer[:FRAME_LENGTH])
                log_capture(frame)
                if verify_checksum(frame):
                    del self._buffer[:FRAME_LENGTH]
                    return frame

                # A stray 0xAC was found. Shift and search for the next frame.
                del self._buffer[0]

        return None


class Driver:
    worker_interval = 0  # read_measurement() blocks internally on the hardware frame

    def __init__(self, packet_source: Optional[Any] = None) -> None:
        self.packet_source = packet_source
        self.connected = False
        self.transport = CP2110Transport()
        self.last_measurement: Optional[Dict[str, Any]] = None
        self.last_measurement_at: Optional[float] = None

    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            self.transport.connect()
        except Exception as exc:
            self.connected = False
            print(f"[Hardware] UT8802E connection failed: {exc}")
            return False

        self.connected = True
        print("[Hardware] UT8802E driver ready. Waiting for packets...")
        return True

    def close(self) -> None:
        self.connected = False
        self.transport.close()

    def read_measurement(self) -> Optional[Dict[str, Any]]:
        if not self.connected and not self.connect():
            return None

        if self.packet_source is not None:
            frame = self.packet_source()
        else:
            frame = self.transport.read_packet()

        if not frame:
            if self.packet_source is None and self.transport.device is None:
                self.connected = False
                return None
            if (
                self.last_measurement is not None
                and self.last_measurement_at is not None
                and time.monotonic() - self.last_measurement_at
                >= STALE_MEASUREMENT_SECONDS
            ):
                stale_measurement = dict(self.last_measurement)
                stale_measurement["value"] = "OL"
                return stale_measurement
            return self.last_measurement

        measurement = parse_packet(frame)
        if measurement is not None:
            self.last_measurement = measurement
            self.last_measurement_at = time.monotonic()
        return self.last_measurement


def build_packet_source() -> Optional[Any]:
    packet_hex = os.environ.get("DMM_8802E_PACKET_HEX")
    if not packet_hex:
        return None
    return lambda: bytes.fromhex(packet_hex)
