# Based on/inspired by https://github.com/philpagel/ut8803e
import os
import time
from typing import Any, Dict, Optional
import cp2110

# Set DMM_8802E_CAPTURE_LOG=/path/to/file.log to append every raw frame's hex to
# that file, tagged with its mode byte. Useful for capturing packets for modes
# that aren't mapped yet (e.g. put the meter in hFE mode, take a reading, then
# check the log for the mode byte it used).
CAPTURE_LOG_PATH = os.environ.get("DMM_8802E_CAPTURE_LOG")


def log_capture(frame: bytes) -> None:
    if not CAPTURE_LOG_PATH:
        return
    mode_byte = f"0x{frame[3]:02x}" if len(frame) > 3 else "?"
    line = f"{time.strftime('%H:%M:%S')} mode={mode_byte} frame={frame.hex()}\n"
    try:
        with open(CAPTURE_LOG_PATH, "a") as f:
            f.write(line)
    except Exception as exc:
        print(f"[Capture] failed to write {CAPTURE_LOG_PATH}: {exc}")

class CP2110Transport:
    def __init__(self) -> None:
        self.device = None
        self._buffer = bytearray()

    def connect(self) -> None:
        if self.device is not None:
            return
        self.device = cp2110.CP2110Device()
        self.device.set_uart_config(
            cp2110.UARTConfig(
                baud=9600,
                parity=cp2110.PARITY.NONE,
                flow_control=cp2110.FLOW_CONTROL.DISABLED,
                data_bits=cp2110.DATA_BITS.EIGHT,
                stop_bits=cp2110.STOP_BITS.SHORT,
            )
        )
        self.device.enable_uart()
        print("[Hardware] UT8802E transport connected")

    def close(self) -> None:
        if self.device is None:
            return
        try:
            self.device.purge_fifos()
            self.device.close()
        except Exception:
            pass
        self.device = None

    def read_packet(self) -> Optional[bytes]:
        """Returns a full frame: signature(2) + length(1) + payload + checksum(2)."""
        if self.device is None:
            try:
                self.connect()
            except Exception as exc:
                print(f"[Hardware] UT8802E connection failed: {exc}")
                return None

        try:
            self._buffer.extend(self.device.read(64))
        except Exception as exc:
            print(f"[Hardware] UT8802E read failed: {exc}")
            self.close()
            return None

        if len(self._buffer) < 16:
            return None
        start = self._buffer.find(b"\xab\xcd")
        if start < 0:
            self._buffer.clear()
            return None
        if start > 0:
            del self._buffer[:start]
        if len(self._buffer) < 16:
            return None

        packet_length = self._buffer[2]
        frame_length = packet_length + 3
        if len(self._buffer) < frame_length:
            return None

        frame = bytes(self._buffer[:frame_length])
        del self._buffer[:frame_length]
        return frame


def normalize_measurement(
    value: str, unit: str, mode: str, range_value: str = "", flags: Optional[list] = None
) -> Dict[str, Any]:
    result = {
        "value": value,
        "unit": unit,
        "mode": mode,
        "range": range_value,
    }
    if flags:
        result["flags"] = flags
    return result


# Unit/range strings depend on mode AND range together, not mode alone (e.g. ACV
# range 0 = mV, range 1 = V, ...). Ported from the reference UT8803E device where
# the mode lines up 1:1 with this driver's mode_code. NOT YET VERIFIED against a
# real UT8802E capture.
# 
# TODO: Should sanity-check a few readings against the display.
#
# DCA (0x06) and ACA (0x07) are intentionally left out: the reference splits DC/AC
# current into three separate modes (µA/mA/A) rather than one mode with multiple
# ranges, so there's no direct table to port. These fall back to unit_map above.
MODE_RANGE_TABLE = {
    0x00: {"units": ["mV", "V", "V", "V", "V"], "ranges": ["600mV", "6V", "60V", "600V", "750V"]},
    0x01: {"units": ["mV", "V", "V", "V", "V"], "ranges": ["600mV", "6V", "60V", "600V", "1000V"]},
    0x02: {"units": ["Ω", "kΩ", "kΩ", "kΩ", "MΩ", "MΩ"], "ranges": ["600Ω", "6kΩ", "60kΩ", "600kΩ", "6MΩ", "60MΩ"]},
    0x03: {"units": [""], "ranges": ["NA"]},
    0x04: {"units": ["ΔV"], "ranges": ["NA"]},
    0x05: {
        "units": ["nF", "nF", "F", "µF", "µF", "µF", "mF"],
        "ranges": ["6nF", "60nF", "600nF", "6µF", "60µF", "600µF", "6mF"],
    },
    0x08: {
        "units": ["Hz", "kHz", "kHz", "kHz", "MHz", "MHz"],
        "ranges": ["600Hz", "6kHz", "60kHz", "600kHz", "6MHz", "20MHz"],
    },
    0x09: {"units": ["%"] * 6, "ranges": ["600Hz", "6kHz", "60kHz", "600kHz", "6MHz", "20MHz"]},
}


def decode_range_index(range_code: int) -> Optional[int]:
    """The range byte is an ASCII digit ('0'-'9'), same encoding as the reference
    device's PaddedString range field — not a raw binary index."""
    ch = chr(range_code)
    return int(ch) if ch.isdigit() else None


def verify_checksum(frame: bytes) -> bool:
    """Checksum = sum of all bytes except the trailing 2-byte checksum, mod 65536."""
    if len(frame) < 5:
        return False
    computed = sum(frame[:-2]) & 0xFFFF
    received = int.from_bytes(frame[-2:], "big")
    return computed == received


def parse_packet(frame: bytes) -> Optional[Dict[str, Any]]:
    # `frame` is the full frame from CP2110Transport: signature(2) + length(1) + payload + checksum(2).
    if len(frame) < 21 or frame[0:2] != b"\xab\xcd":
        return None

    if not verify_checksum(frame):
        print("[Hardware] UT8802E checksum mismatch, dropping packet")
        return None

    payload = frame[3:-2]
    if len(payload) < 16 or payload[0] != 0x02:
        return None

    mode_code = payload[1]
    range_code = payload[2]
    value_str = bytes(payload[3:9]).decode("ascii", errors="ignore").rstrip("\x00").strip()
    stat = payload[9:16]

    mode_map = {
        0x00: "ACV",
        0x01: "DCV",
        0x02: "RES",
        0x03: "Cont",
        0x04: "Diode",
        0x05: "CAP",
        0x06: "DCA",
        0x07: "ACA",
        0x08: "FREQ",
        0x09: "Duty",
    }
    # Flat fallback unit map, used for modes not covered by MODE_RANGE_TABLE below
    # (currently DCA/ACA — see note on MODE_RANGE_TABLE for why).
    unit_map = {
        0x00: "V",
        0x01: "V",
        0x02: "Ω",
        0x03: "Ω",
        0x04: "V",
        0x05: "nF",
        0x06: "A",
        0x07: "A",
        0x08: "Hz",
        0x09: "%",
    }

    overload = bool(stat[2] & 0x04)
    hold = bool(stat[2] & 0x01)
    error = bool(stat[3] & 0x04)
    manual_range = bool(stat[3] & 0x02)
    rel = bool(stat[3] & 0x01)
    is_max = bool(stat[4] & 0x02)
    is_min = bool(stat[4] & 0x01)

    if error:
        value_str = "Err"
    elif overload:
        value_str = "OL"

    if not value_str:
        return None

    flags = []
    if hold:
        flags.append("hold")
    if rel:
        flags.append("rel")
    if manual_range:
        flags.append("manual")
    if is_max:
        flags.append("max")
    if is_min:
        flags.append("min")

    mode_name = mode_map.get(mode_code, f"UNKNOWN (0x{mode_code:02x})")
    unit = unit_map.get(mode_code, "")
    range_str = chr(range_code) if range_code else ""

    table_entry = MODE_RANGE_TABLE.get(mode_code)
    idx = decode_range_index(range_code)
    if table_entry is not None and idx is not None:
        if idx < len(table_entry["units"]):
            unit = table_entry["units"][idx]
        if idx < len(table_entry["ranges"]):
            range_str = table_entry["ranges"][idx]

    return normalize_measurement(value_str, unit, mode_name, range_str, flags)


class Driver:
    worker_interval = 0  # read_measurement() blocks internally on the hardware frame

    def __init__(self, packet_source: Optional[Any] = None) -> None:
        self.packet_source = packet_source
        self.connected = False
        self.transport = CP2110Transport()

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

        # If a packet source is provided (for testing), use it to get a packet.
        # NOTE: test packets via DMM_8802E_PACKET_HEX must now include the
        # signature(2) + length(1) + checksum(2) framing, since parse_packet
        # expects a full frame just like the real transport returns.
        if self.packet_source is not None:
            packet = self.packet_source()
            if not packet:
                return None
            return parse_packet(packet)

        # If no packet source is provided, read from the actual transport (the CP2110 device).
        packet = self.transport.read_packet()
        if not packet:
            time.sleep(0.1)
            return None

        log_capture(packet)
        return parse_packet(packet)


# This is for testing purposes: optionally you can pass a DMM_8802E_PACKET_HEX environment variable to simulate a packet for testing without the actual device.
def build_packet_source() -> Optional[Any]:
    packet_hex = os.environ.get("DMM_8802E_PACKET_HEX")
    if not packet_hex:
        return None
    return lambda: bytes.fromhex(packet_hex)
