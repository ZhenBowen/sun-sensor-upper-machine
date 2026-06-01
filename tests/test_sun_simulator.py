import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sun_protocol import TelemetryParser
from sun_simulator import SunSimulator


class TestSunSimulator(unittest.TestCase):
    def test_simulator_frame_can_be_parsed_by_protocol_parser(self):
        simulator = SunSimulator(node_id=4, rate_hz=10.0, mode="normal")
        frame = simulator.next_frame()
        parser = TelemetryParser()

        parsed = parser.feed(frame)

        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].node_id, 4)
        self.assertTrue(-75.0 <= parsed[0].alpha_deg <= 75.0)
        self.assertTrue(-75.0 <= parsed[0].beta_deg <= 75.0)
        self.assertGreater(parsed[0].signal_sum, 0)

    def test_crc_error_mode_periodically_generates_bad_crc(self):
        simulator = SunSimulator(node_id=1, rate_hz=10.0, mode="crc_error", crc_error_every=2)
        parser = TelemetryParser()

        parser.feed(simulator.next_frame())
        parser.feed(simulator.next_frame())

        self.assertEqual(parser.frame_count, 1)
        self.assertEqual(parser.crc_error_count, 1)


if __name__ == "__main__":
    unittest.main()
