import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sun_models import SunTelemetry
from sun_protocol import (
    EB90Parser,
    EB90TestParser,
    EB90_FRAME_LEN,
    EB90_TEST_FRAME_LEN,
    TELEMETRY_FRAME_LEN,
    TelemetryParser,
    crc16_modbus,
    hex_text_to_bytes,
    pack_eb90_frame,
    pack_eb90_test_frame,
    pack_command,
    pack_telemetry,
    parse_eb90_frame,
    parse_eb90_test_frame,
    parse_telemetry_frame,
)


class TestSunProtocol(unittest.TestCase):
    def sample_telemetry(self, seq=7):
        return SunTelemetry(
            version=1,
            msg_type=0x01,
            node_id=3,
            seq=seq,
            timestamp_ms=123456,
            adc_vax1=1200,
            adc_vax2=1500,
            adc_vay1=1300,
            adc_vay2=1600,
            alpha_cdeg=1234,
            beta_cdeg=-567,
            temp_centi_c=2645,
            sun_present=1,
            saturation_flag=0,
            status_word=0x0003,
        )

    def test_crc16_modbus_known_vector(self):
        self.assertEqual(crc16_modbus(b"123456789"), 0x4B37)

    def test_parse_valid_telemetry_frame(self):
        source = self.sample_telemetry()
        frame = pack_telemetry(source)
        self.assertEqual(len(frame), TELEMETRY_FRAME_LEN)

        parsed = parse_telemetry_frame(frame)

        self.assertEqual(parsed.node_id, 3)
        self.assertEqual(parsed.seq, 7)
        self.assertEqual(parsed.timestamp_ms, 123456)
        self.assertEqual(parsed.adc_vax1, 1200)
        self.assertEqual(parsed.adc_vax2, 1500)
        self.assertEqual(parsed.adc_vay1, 1300)
        self.assertEqual(parsed.adc_vay2, 1600)
        self.assertAlmostEqual(parsed.alpha_deg, 12.34)
        self.assertAlmostEqual(parsed.beta_deg, -5.67)
        self.assertAlmostEqual(parsed.temp_c, 26.45)
        self.assertTrue(parsed.valid_flag)
        self.assertTrue(parsed.status_flags["SUN_PRESENT"])

    def test_parser_handles_split_frame(self):
        frame = pack_telemetry(self.sample_telemetry())
        parser = TelemetryParser()

        self.assertEqual(parser.feed(frame[:9]), [])
        parsed = parser.feed(frame[9:])

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].seq, 7)

    def test_parser_handles_sticky_frames(self):
        frame_a = pack_telemetry(self.sample_telemetry(seq=10))
        frame_b = pack_telemetry(self.sample_telemetry(seq=11))
        parser = TelemetryParser()

        parsed = parser.feed(frame_a + frame_b)

        self.assertEqual([item.seq for item in parsed], [10, 11])
        self.assertEqual(parser.drop_count, 0)

    def test_parser_discards_noise_before_sof(self):
        frame = pack_telemetry(self.sample_telemetry(seq=21))
        parser = TelemetryParser()

        parsed = parser.feed(b"noise" + frame)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].seq, 21)

    def test_parser_rejects_bad_crc(self):
        frame = bytearray(pack_telemetry(self.sample_telemetry()))
        frame[-1] ^= 0xFF
        parser = TelemetryParser()

        parsed = parser.feed(bytes(frame))

        self.assertEqual(parsed, [])
        self.assertEqual(parser.crc_error_count, 1)

    def test_parser_counts_dropped_frames_and_wraparound(self):
        parser = TelemetryParser()
        frames = b"".join(
            [
                pack_telemetry(self.sample_telemetry(seq=65534)),
                pack_telemetry(self.sample_telemetry(seq=65535)),
                pack_telemetry(self.sample_telemetry(seq=0)),
                pack_telemetry(self.sample_telemetry(seq=3)),
            ]
        )

        parsed = parser.feed(frames)

        self.assertEqual([item.seq for item in parsed], [65534, 65535, 0, 3])
        self.assertEqual(parser.drop_count, 2)

    def test_pack_command_uses_expected_header_and_crc(self):
        command = pack_command(node_id=2, cmd_id=0x02, payload=b"\x0A\x00")

        self.assertEqual(command[:2], b"\x55\xAA")
        self.assertEqual(command[2], 1)
        self.assertEqual(command[3], 0x80)
        self.assertEqual(command[4], 2)
        self.assertEqual(command[5], 0x02)
        self.assertEqual(command[6], 2)
        expected_crc = crc16_modbus(command[2:-2])
        actual_crc = int.from_bytes(command[-2:], "little")
        self.assertEqual(actual_crc, expected_crc)

    def test_parse_eb90_example_frame_extracts_spot_xy(self):
        frame = hex_text_to_bytes(
            "EB 90 00 00 00 00 00 00 00 00 00 00 19 00 32 00 51 00 45 1C 08 00 11 00 00 91"
        )

        parsed = parse_eb90_frame(frame)

        self.assertEqual(len(frame), EB90_FRAME_LEN)
        self.assertEqual(parsed.sun_present, 0)
        self.assertAlmostEqual(parsed.x, 0.0)
        self.assertAlmostEqual(parsed.y, 0.0)
        self.assertEqual(parsed.raw_frame_hex, frame.hex(" ").upper())

    def test_pack_and_parse_eb90_frame_with_sun_present(self):
        frame = pack_eb90_frame(sun_present=1, x=12.5, y=-3.25)

        parsed = parse_eb90_frame(frame)

        self.assertEqual(frame[:3], b"\xEB\x90\x01")
        self.assertAlmostEqual(parsed.x, 12.5)
        self.assertAlmostEqual(parsed.y, -3.25)
        self.assertTrue(parsed.valid_flag)

    def test_eb90_parser_handles_split_sticky_and_noise(self):
        frame_a = pack_eb90_frame(sun_present=1, x=1.25, y=2.5)
        frame_b = pack_eb90_frame(sun_present=0, x=-4.0, y=8.0)
        parser = EB90Parser()

        self.assertEqual(parser.feed(b"noise" + frame_a[:7]), [])
        parsed = parser.feed(frame_a[7:] + frame_b)

        self.assertEqual(len(parsed), 2)
        self.assertAlmostEqual(parsed[0].x, 1.25)
        self.assertAlmostEqual(parsed[0].y, 2.5)
        self.assertEqual(parsed[1].sun_present, 0)
        self.assertAlmostEqual(parsed[1].x, -4.0)
        self.assertAlmostEqual(parsed[1].y, 8.0)

    def test_eb90_parser_rejects_bad_checksum(self):
        frame = bytearray(pack_eb90_frame(sun_present=1, x=1.0, y=2.0))
        frame[-1] ^= 0xFF
        parser = EB90Parser()

        parsed = parser.feed(bytes(frame))

        self.assertEqual(parsed, [])
        self.assertEqual(parser.crc_error_count, 1)

def test_hex_text_to_bytes_accepts_spaces_and_commas(self):
        self.assertEqual(hex_text_to_bytes("eb 90, 11 00 8c"), b"\xEB\x90\x11\x00\x8C")


class TestEB90TestProtocol(unittest.TestCase):
    def test_pack_and_parse_round_trip(self):
        frame = pack_eb90_test_frame(
            sun_present=1, alpha=12.5, beta=-3.25,
            adc_vax1=2327, adc_vax2=2330, adc_vay1=2347, adc_vay2=2328,
        )
        self.assertEqual(len(frame), EB90_TEST_FRAME_LEN)
        self.assertEqual(frame[0], 1)
        checksum = sum(frame[:-1]) & 0xFF
        self.assertEqual(frame[-1], checksum)

        parsed = parse_eb90_test_frame(frame)
        self.assertEqual(parsed.sun_present, 1)
        self.assertAlmostEqual(parsed.x, 12.5, places=4)
        self.assertAlmostEqual(parsed.y, -3.25, places=4)
        self.assertEqual(parsed.adc_vax1, 2327)
        self.assertEqual(parsed.adc_vax2, 2330)
        self.assertEqual(parsed.adc_vay1, 2347)
        self.assertEqual(parsed.adc_vay2, 2328)

    def test_parse_rejects_bad_checksum(self):
        frame = bytearray(pack_eb90_test_frame(
            sun_present=1, alpha=1.0, beta=2.0,
            adc_vax1=100, adc_vax2=200, adc_vay1=300, adc_vay2=400,
        ))
        frame[-1] ^= 0xFF
        parser = EB90TestParser()

        parsed = parser.feed(bytes(frame))

        self.assertEqual(parsed, [])
        self.assertEqual(parser.crc_error_count, 1)

    def test_parser_handles_sticky_frames(self):
        frame_a = pack_eb90_test_frame(
            sun_present=1, alpha=1.25, beta=2.5,
            adc_vax1=100, adc_vax2=200, adc_vay1=300, adc_vay2=400,
        )
        frame_b = pack_eb90_test_frame(
            sun_present=0, alpha=-4.0, beta=8.0,
            adc_vax1=500, adc_vax2=600, adc_vay1=700, adc_vay2=800,
        )
        parser = EB90TestParser()

        parsed = parser.feed(frame_a + frame_b)

        self.assertEqual(len(parsed), 2)
        self.assertAlmostEqual(parsed[0].x, 1.25, places=3)
        self.assertAlmostEqual(parsed[0].y, 2.5, places=3)
        self.assertAlmostEqual(parsed[1].x, -4.0, places=3)

    def test_parser_rejects_invalid_sun_present(self):
        frame = bytearray(pack_eb90_test_frame(
            sun_present=1, alpha=0.0, beta=0.0,
            adc_vax1=0, adc_vax2=0, adc_vay1=0, adc_vay2=0,
        ))
        frame[0] = 0x05
        frame[-1] = sum(frame[:-1]) & 0xFF
        parser = EB90TestParser()

        parsed = parser.feed(bytes(frame))

        self.assertEqual(len(parsed), 0)
        self.assertEqual(parser.frame_error_count, 1)

    def test_parser_recovers_from_noise(self):
        good_frame = pack_eb90_test_frame(
            sun_present=1, alpha=5.0, beta=-2.0,
            adc_vax1=111, adc_vax2=222, adc_vay1=333, adc_vay2=444,
        )
        parser = EB90TestParser()

        parsed = parser.feed(b"\x00\x00\x00" + good_frame)

        self.assertEqual(len(parsed), 1)
        self.assertAlmostEqual(parsed[0].x, 5.0, places=3)


if __name__ == "__main__":
    unittest.main()
