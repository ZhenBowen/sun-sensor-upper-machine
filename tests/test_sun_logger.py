import csv
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sun_logger import CSV_FIELDS, SunCsvLogger
from sun_models import CalibrationContext, SunTelemetry, TelemetryStats


class TestSunLogger(unittest.TestCase):
    def test_logger_writes_header_and_one_row(self):
        telemetry = SunTelemetry(
            version=1,
            msg_type=0x01,
            node_id=1,
            seq=42,
            timestamp_ms=5000,
            adc_vax1=1000,
            adc_vax2=1100,
            adc_vay1=1200,
            adc_vay2=1300,
            alpha_cdeg=1250,
            beta_cdeg=-250,
            temp_centi_c=3025,
            sun_present=1,
            saturation_flag=0,
            status_word=0x0003,
        )
        stats = TelemetryStats(frame_rate_hz=9.95, drop_count=2, crc_error_count=1)
        calibration = CalibrationContext(
            alpha_ref_deg=10.0,
            beta_ref_deg=-5.0,
            test_point="P001",
            comment="room_temp_sweep",
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sun.csv"
            logger = SunCsvLogger()
            logger.start(path)
            logger.write(telemetry, stats, calibration)
            logger.stop()

            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(CSV_FIELDS, list(rows[0].keys()))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["seq"], "42")
        self.assertEqual(rows[0]["status_word"], "0x0003")
        self.assertEqual(rows[0]["valid_flag"], "1")
        self.assertEqual(rows[0]["alpha_deg"], "12.50")
        self.assertEqual(rows[0]["beta_deg"], "-2.50")
        self.assertEqual(rows[0]["temp_c"], "30.25")
        self.assertEqual(rows[0]["alpha_ref_deg"], "10.00")
        self.assertEqual(rows[0]["beta_ref_deg"], "-5.00")
        self.assertEqual(rows[0]["test_point"], "P001")
        self.assertEqual(rows[0]["comment"], "room_temp_sweep")


if __name__ == "__main__":
    unittest.main()

