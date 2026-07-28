# Based on/inspired by https://github.com/mbraune/ut161b/tree/main
import time
from typing import Any, Dict, Optional

import hid

VID = 0x1A86
PID = 0xE429


def handle_request(device: Any, cmd: int):
    cmd &= 0xFF
    sum_val = (0xAB + 0xCD + 0x03 + cmd) & 0xFFFF
    sum0 = (sum_val & 0xFF00) >> 8
    sum1 = sum_val & 0x00FF
    request_command = [0x00, 0x06, 0xAB, 0xCD, 0x03, cmd, sum0, sum1]
    device.write(request_command)
    time.sleep(0.05)
    response = device.read(64, 1000)
    return response[0:64]


def normalize_measurement(value: str, unit: str, mode: str, range_value: str = "") -> Dict[str, Any]:
    return {
        "value": value,
        "unit": unit,
        "mode": mode,
        "range": range_value,
    }


def parse_packet(packet: bytes) -> Optional[Dict[str, Any]]:
    if len(packet) < 20 or packet[0] < 0x13:
        return None

    mode_map = {
        0x00: "ACV",
        0x01: "ACmV",
        0x02: "DCV",
        0x03: "DCmV",
        0x04: "FREQ",
        0x05: "Duty",
        0x06: "RES",
        0x07: "Cont",
        0x08: "Diode",
        0x09: "CAP",
        0x0C: "DCµA",
        0x0D: "ACµA",
        0x0E: "DCmA",
        0x0F: "ACmA",
        0x10: "DCA",
        0x11: "ACA",
    }

    mode = packet[4]
    range_flag = packet[5]
    value_str = bytes(packet[6:13]).decode("ascii", errors="ignore").rstrip("\x00").strip()
    unit_raw = bytes(packet[15:18]).decode("ascii", errors="ignore")

    if mode in (0x00, 0x02):
        unit = "V"
    elif mode in (0x01, 0x03):
        unit = "mV"
    elif mode == 0x04:
        unit = "Hz"
    elif mode == 0x06:
        unit_map = {0x30: "Ω", 0x31: "kΩ", 0x32: "kΩ", 0x33: "kΩ", 0x34: "MΩ", 0x35: "MΩ"}
        unit = unit_map.get(range_flag, "?Ω")
    elif mode == 0x07:
        unit = "Ω"
    elif mode == 0x08:
        unit = "V"
    elif mode == 0x09:
        unit = "nF"
    elif mode in (0x0C, 0x0D):
        unit = "µA"
    elif mode in (0x0E, 0x0F):
        unit = "mA"
    elif mode in (0x10, 0x11):
        unit = "A"
    else:
        unit = unit_raw.strip()

    return normalize_measurement(value_str, unit, mode_map.get(mode, f"UNKNOWN (0x{mode:02x})"), str(range_flag))


class Driver:
    worker_interval = 0.3  # polled via handle_request, not hardware-paced

    def __init__(self) -> None:
        self.device: Optional[Any] = None

    def connect(self) -> None:
        self.device = hid.device()
        self.device.open(VID, PID)
        print("[Hardware] UT161B detected. Sending initialization...")
        handle_request(self.device, 0x5F)
        time.sleep(0.1)
        handle_request(self.device, 0x30)
        time.sleep(0.3)
        handle_request(self.device, 0x42)
        time.sleep(0.2)
        print("[Hardware] UT161B streaming live metrics successfully!")

    def close(self) -> None:
        if self.device is not None:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None

    def read_measurement(self) -> Optional[Dict[str, Any]]:
        if self.device is None:
            self.connect()
        resp = handle_request(self.device, 0x5E)
        if not resp or len(resp) == 0:
            raise RuntimeError("Multimeter response timed out (DMM turned off)")
        return parse_packet(resp)
