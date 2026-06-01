import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sun_models import SunTelemetry
from sun_protocol import (
    TELEMETRY_FRAME_LEN,
    TelemetryParser,
    crc16_modbus,
    pack_command,
    pack_telemetry,
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


if __name__ == "__main__":
    unittest.main()
