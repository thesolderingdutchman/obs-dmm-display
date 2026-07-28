import unittest
from unittest.mock import patch

from drivers import ut8802e
from drivers.ut161b import parse_packet as parse_ut161b_packet
from drivers.ut8802e import parse_packet as parse_ut8802e_packet


def make_frame(mode, low_bcd, mid_bcd, high_digit, decimals, status=0):
    """
    Build a native 8-byte UT8802E frame.

        AC mode low mid high decimals status checksum
    """
    frame = bytes(
        [
            0xAC,
            mode,
            low_bcd,
            mid_bcd,
            high_digit,
            ord(str(decimals)),
            status,
        ]
    )
    checksum = sum(frame) & 0x7F
    return frame + bytes([checksum])


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

    def test_parse_positive_voltage(self):
        # 12.34 V on 20 V range
        frame = make_frame(
            mode=0x04,
            low_bcd=0x34,
            mid_bcd=0x12,
            high_digit=0x00,
            decimals=2,
        )

        result = parse_ut8802e_packet(frame)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "DCV")
        self.assertEqual(result["value"], "12.34")
        self.assertEqual(result["unit"], "V")
        self.assertEqual(result["range"], "20V")

    def test_parse_negative_voltage(self):
        frame = make_frame(
            mode=0x04,
            low_bcd=0x34,
            mid_bcd=0x12,
            high_digit=0x00,
            decimals=2,
            status=0x80,
        )

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "-12.34")

    def test_overload_status_bit(self):
        frame = make_frame(
            mode=0x04,
            low_bcd=0x34,
            mid_bcd=0x12,
            high_digit=0x00,
            decimals=2,
            status=0x40,
        )

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "OL")
        self.assertEqual(result["mode"], "DCV")

    def test_bad_checksum(self):
        frame = bytearray(make_frame(0x04, 0x34, 0x12, 0x00, 2))
        frame[-1] ^= 0x01

        self.assertIsNone(parse_ut8802e_packet(bytes(frame)))

    def test_bad_magic(self):
        frame = bytearray(make_frame(0x04, 0x34, 0x12, 0x00, 2))
        frame[0] = 0x00

        self.assertIsNone(parse_ut8802e_packet(bytes(frame)))

    def test_invalid_bcd_returns_overload(self):
        frame = make_frame(
            mode=0x04,
            low_bcd=0xFA,      # invalid BCD
            mid_bcd=0x12,
            high_digit=0x00,
            decimals=2,
        )

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "OL")

    def test_invalid_high_digit_returns_overload(self):
        frame = make_frame(
            mode=0x04,
            low_bcd=0x34,
            mid_bcd=0x12,
            high_digit=0x0F,
            decimals=2,
        )

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "OL")

    def test_out_of_range_count_returns_overload(self):
        # Raw count = 99999 (>19999 display limit)
        frame = make_frame(
            mode=0x04,
            low_bcd=0x99,
            mid_bcd=0x99,
            high_digit=0x09,
            decimals=0,
        )

        result = parse_ut8802e_packet(frame)

        self.assertEqual(result["value"], "OL")

    def test_unknown_mode(self):
        frame = make_frame(
            mode=0x99,
            low_bcd=0x34,
            mid_bcd=0x12,
            high_digit=0x00,
            decimals=2,
        )

        result = parse_ut8802e_packet(frame)

        self.assertIsNotNone(result)
        self.assertEqual(result["mode"], "UNKNOWN (0x99)")
        self.assertEqual(result["value"], "12.34")

    def test_ut8802e_driver_returns_none_when_connect_fails(self):
        driver = ut8802e.Driver()

        with patch.object(
            driver.transport,
            "connect",
            side_effect=RuntimeError("no device"),
        ):
            self.assertIsNone(driver.read_measurement())
            self.assertFalse(driver.connected)


if __name__ == "__main__":
    unittest.main()