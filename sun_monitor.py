from __future__ import annotations

from collections import deque
from typing import Dict

from PyQt5.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from PyQt5.QtCore import Qt
import pyqtgraph as pg

from sun_models import STATUS_BITS, SunTelemetry, TelemetryStats


class SunMonitorWidget(QWidget):
    def __init__(self, parent: QWidget | None = None, max_points: int = 600) -> None:
        super().__init__(parent)
        self.max_points = max_points
        self._index = 0
        self._x = deque(maxlen=max_points)
        self._alpha = deque(maxlen=max_points)
        self._beta = deque(maxlen=max_points)
        self._temp = deque(maxlen=max_points)
        self._adc = {
            "adc_vax1": deque(maxlen=max_points),
            "adc_vax2": deque(maxlen=max_points),
            "adc_vay1": deque(maxlen=max_points),
            "adc_vay2": deque(maxlen=max_points),
        }
        self.value_labels: Dict[str, QLabel] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        pg.setConfigOptions(antialias=True)
        root = QVBoxLayout(self)
        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter)

        top = QWidget()
        top_layout = QGridLayout(top)
        telemetry_box = QGroupBox("Current Telemetry")
        telemetry_layout = QGridLayout(telemetry_box)
        fields = [
            "seq",
            "node_id",
            "timestamp_ms",
            "alpha_deg",
            "beta_deg",
            "temp_c",
            "sun_present",
            "saturation_flag",
            "status_word",
            "frame_rate_hz",
            "drop_count",
            "crc_error_count",
            "signal_sum",
            "rx",
            "ry",
        ]
        for row, name in enumerate(fields):
            telemetry_layout.addWidget(QLabel(name), row, 0)
            label = QLabel("--")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            telemetry_layout.addWidget(label, row, 1)
            self.value_labels[name] = label

        status_box = QGroupBox("Status Bits")
        status_layout = QVBoxLayout(status_box)
        self.status_text = QPlainTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumBlockCount(100)
        status_layout.addWidget(self.status_text)

        top_layout.addWidget(telemetry_box, 0, 0)
        top_layout.addWidget(status_box, 0, 1)
        splitter.addWidget(top)

        plot_panel = QWidget()
        plot_layout = QGridLayout(plot_panel)
        self.angle_plot = pg.PlotWidget(title="Angle Trend")
        self.angle_plot.setLabel("left", "deg")
        self.angle_plot.setLabel("bottom", "sample")
        self.alpha_curve = self.angle_plot.plot(pen=pg.mkPen("#E4572E", width=2), name="alpha")
        self.beta_curve = self.angle_plot.plot(pen=pg.mkPen("#17BEBB", width=2), name="beta")
        self.angle_plot.addLegend()

        self.adc_plot = pg.PlotWidget(title="ADC Trend")
        self.adc_plot.setLabel("left", "ADC")
        self.adc_plot.setLabel("bottom", "sample")
        self.adc_curves = {
            "adc_vax1": self.adc_plot.plot(pen=pg.mkPen("#1B998B", width=1), name="VAX1"),
            "adc_vax2": self.adc_plot.plot(pen=pg.mkPen("#F46036", width=1), name="VAX2"),
            "adc_vay1": self.adc_plot.plot(pen=pg.mkPen("#2E86AB", width=1), name="VAY1"),
            "adc_vay2": self.adc_plot.plot(pen=pg.mkPen("#F6AE2D", width=1), name="VAY2"),
        }
        self.adc_plot.addLegend()

        self.temp_plot = pg.PlotWidget(title="Temperature Trend")
        self.temp_plot.setLabel("left", "degC")
        self.temp_plot.setLabel("bottom", "sample")
        self.temp_curve = self.temp_plot.plot(pen=pg.mkPen("#6A4C93", width=2), name="temp")

        plot_layout.addWidget(self.angle_plot, 0, 0)
        plot_layout.addWidget(self.adc_plot, 1, 0)
        plot_layout.addWidget(self.temp_plot, 2, 0)
        splitter.addWidget(plot_panel)
        splitter.setSizes([260, 600])

    def update_telemetry(self, telemetry: SunTelemetry, stats: TelemetryStats) -> None:
        values = {
            "seq": str(telemetry.seq),
            "node_id": str(telemetry.node_id),
            "timestamp_ms": str(telemetry.timestamp_ms),
            "alpha_deg": f"{telemetry.alpha_deg:.2f}",
            "beta_deg": f"{telemetry.beta_deg:.2f}",
            "temp_c": f"{telemetry.temp_c:.2f}",
            "sun_present": "yes" if telemetry.sun_present else "no",
            "saturation_flag": "yes" if telemetry.saturation_flag else "no",
            "status_word": f"0x{telemetry.status_word:04X}",
            "frame_rate_hz": f"{stats.frame_rate_hz:.2f}",
            "drop_count": str(stats.drop_count),
            "crc_error_count": str(stats.crc_error_count),
            "signal_sum": str(telemetry.signal_sum),
            "rx": f"{telemetry.rx:.4f}",
            "ry": f"{telemetry.ry:.4f}",
        }
        for name, value in values.items():
            self.value_labels[name].setText(value)

        status_lines = [f"status_word = 0x{telemetry.status_word:04X}"]
        for bit, name in STATUS_BITS.items():
            status_lines.append(f"{name}: {'yes' if telemetry.status_word & (1 << bit) else 'no'}")
        self.status_text.setPlainText("\n".join(status_lines))

        self._append_plot_data(telemetry)
        self._refresh_plots()

    def clear(self) -> None:
        self._index = 0
        self._x.clear()
        self._alpha.clear()
        self._beta.clear()
        self._temp.clear()
        for series in self._adc.values():
            series.clear()
        self._refresh_plots()

    def _append_plot_data(self, telemetry: SunTelemetry) -> None:
        self._index += 1
        self._x.append(self._index)
        self._alpha.append(telemetry.alpha_deg)
        self._beta.append(telemetry.beta_deg)
        self._temp.append(telemetry.temp_c)
        self._adc["adc_vax1"].append(telemetry.adc_vax1)
        self._adc["adc_vax2"].append(telemetry.adc_vax2)
        self._adc["adc_vay1"].append(telemetry.adc_vay1)
        self._adc["adc_vay2"].append(telemetry.adc_vay2)

    def _refresh_plots(self) -> None:
        x = list(self._x)
        self.alpha_curve.setData(x, list(self._alpha))
        self.beta_curve.setData(x, list(self._beta))
        self.temp_curve.setData(x, list(self._temp))
        for name, curve in self.adc_curves.items():
            curve.setData(x, list(self._adc[name]))
