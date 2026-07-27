import unittest
from unittest.mock import patch

from drivers import ut8802e
from drivers.ut161b import parse_packet as parse_ut161b_packet
from drivers.ut8802e import parse_packet as parse_ut8802e_packet


def build_frame(payload: bytes) -> bytes:
    """Build a full UT8802E frame: signature(2) + length(1) + payload + checksum(2)."""
    length = len(payload) + 2
    header = b"\xab\xcd" + bytes([length])
    checksum = sum(header + payload) & 0xFFFF
    return header + payload + checksum.to_bytes(2, "big")


def build_payload(mode: int, range_digit: str, value: bytes, stat: bytes = bytes(7)) -> bytes:
    assert len(value) == 6 and len(stat) == 7
    return bytes([0x02, mode, ord(range_digit)]) + value + stat


class DmmParserTests(unittest.TestCase):
    def test_parse_ut161b_packet(self):
        packet = bytearray(64)
        packet[0] = 0x13
        packet[4] = 0x02
        packet[5] = 0x30
        packet[6:13] = b"12.34\x00"
        packet[15:18] = b"V\x00\x00"

        result = parse_ut161b_packet(bytes(packet))

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "DCV")
        self.assertEqual(result["value"], "12.34")
        self.assertEqual(result["unit"], "V")

    def test_parse_ut8802e_packet(self):
        # mode=0x01 (DCV), range digit '1' -> table index 1 -> unit "V", range "6V"
        payload = build_payload(mode=0x01, range_digit="1", value=b"12.34\x00")
        frame = build_frame(payload)

        result = parse_ut8802e_packet(frame)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "DCV")
        self.assertEqual(result["value"], "12.34")
        self.assertEqual(result["unit"], "V")
        self.assertEqual(result["range"], "6V")
        self.assertNotIn("flags", result)  # no status flags set

    def test_parse_ut8802e_packet_range_scaling(self):
        # Same mode, range digit '0' -> table index 0 -> unit "mV", not "V"
        payload = build_payload(mode=0x01, range_digit="0", value=b"600.0\x00")
        frame = build_frame(payload)

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["unit"], "mV")
        self.assertEqual(result["range"], "600mV")

    def test_parse_ut8802e_packet_rejects_bad_checksum(self):
        payload = build_payload(mode=0x01, range_digit="1", value=b"12.34\x00")
        frame = bytearray(build_frame(payload))
        frame[-1] ^= 0xFF  # corrupt checksum byte

        self.assertIsNone(parse_ut8802e_packet(bytes(frame)))

    def test_parse_ut8802e_packet_rejects_bad_signature(self):
        payload = build_payload(mode=0x01, range_digit="1", value=b"12.34\x00")
        frame = bytearray(build_frame(payload))
        frame[0] = 0x00

        self.assertIsNone(parse_ut8802e_packet(bytes(frame)))

    def test_parse_ut8802e_packet_overload_flag(self):
        stat = bytearray(7)
        stat[2] = 0x04  # OL bit
        payload = build_payload(mode=0x01, range_digit="1", value=b"12.34\x00", stat=bytes(stat))
        frame = build_frame(payload)

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "OL")

    def test_parse_ut8802e_packet_error_flag(self):
        stat = bytearray(7)
        stat[3] = 0x04  # err bit
        payload = build_payload(mode=0x01, range_digit="1", value=b"12.34\x00", stat=bytes(stat))
        frame = build_frame(payload)

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "Err")

    def test_parse_ut8802e_packet_hold_and_rel_flags(self):
        stat = bytearray(7)
        stat[2] = 0x01  # hold bit
        stat[3] = 0x01  # rel bit
        payload = build_payload(mode=0x01, range_digit="1", value=b"12.34\x00", stat=bytes(stat))
        frame = build_frame(payload)

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["flags"], ["hold", "rel"])

    def test_parse_ut8802e_real_capture_acv(self):
        # Real packet from https://techbotch.org/blog/ut8803e-bench-meter/ —
        # confirmed via their own construct-based parser: mode=0, range='1',
        # value="+0.206", checksum=1082 (0x043a). Same protocol family as our
        # UT8802E, so this validates our framing/checksum math against real bytes.
        frame = bytes.fromhex("abcd120200312b302e323036303030303c3030043a")
        result = parse_ut8802e_packet(frame)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "ACV")
        self.assertEqual(result["value"], "+0.206")

    def test_parse_ut8802e_real_capture_dcv(self):
        # Real packet from the same blog post's battery test (DC voltage, ~1.5V).
        frame = bytes([0xab, 0xcd, 0x12, 0x02, 0x01]) + b"1+1.4950100<00" + bytes([0x04]) + b"G"
        result = parse_ut8802e_packet(frame)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "DCV")
        self.assertEqual(result["value"], "+1.495")

    def test_ut8802e_driver_returns_none_when_connect_fails(self):
        driver = ut8802e.Driver()
        with patch.object(driver.transport, "connect", side_effect=RuntimeError("no device")):
            self.assertIsNone(driver.read_measurement())
            self.assertFalse(driver.connected)


if __name__ == "__main__":
    unittest.main()