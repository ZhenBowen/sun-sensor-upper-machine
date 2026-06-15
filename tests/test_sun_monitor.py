import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PyQt5.QtWidgets import QApplication

from sun_models import SunTelemetry
from sun_monitor import SunMonitorWidget


class TestSunMonitorWidget(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(sys.argv)

    def test_widget_has_three_plots(self):
        widget = SunMonitorWidget()

        plots = [
            widget.xy_plot,
            widget.trend_plot,
            widget.current_plot,
        ]
        self.assertEqual(len(plots), 3)
        for plot in plots:
            self.assertIsNotNone(plot)

    def test_current_plot_has_four_curves(self):
        widget = SunMonitorWidget()

        self.assertEqual(len(widget.current_curves), 4)
        for curve in widget.current_curves:
            self.assertIsNotNone(curve)

    def test_update_telemetry_populates_current_curves(self):
        widget = SunMonitorWidget()
        telemetry = SunTelemetry(
            adc_vax1=1000,
            adc_vax2=1100,
            adc_vay1=1200,
            adc_vay2=1300,
            alpha_cdeg=1234,
            beta_cdeg=-567,
        )

        widget.update_telemetry(telemetry, widget.latest_stats)

        for curve in widget.current_curves:
            data = curve.getData()
            self.assertIsNotNone(data)
            self.assertEqual(len(data[0]), 1)
