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
        self._sample = deque(maxlen=max_points)
        self._spot_x = deque(maxlen=max_points)
        self._spot_y = deque(maxlen=max_points)
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
            "x",
            "y",
            "sun_present",
            "frame_rate_hz",
            "drop_count",
            "crc_error_count",
            "raw_frame_hex",
        ]
        for row, name in enumerate(fields):
            telemetry_layout.addWidget(QLabel(name), row, 0)
            label = QLabel("--")
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            telemetry_layout.addWidget(label, row, 1)
            self.value_labels[name] = label

        status_box = QGroupBox("Spot Status")
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
        self.xy_plot = pg.PlotWidget(title="Spot Position X-Y")
        self.xy_plot.setLabel("left", "y")
        self.xy_plot.setLabel("bottom", "x")
        self.xy_plot.showGrid(x=True, y=True, alpha=0.3)
        self.xy_plot.setAspectLocked(True)
        self.xy_curve = self.xy_plot.plot(
            pen=None,
            symbol="o",
            symbolSize=7,
            symbolBrush=pg.mkBrush("#E4572E"),
            name="spot",
        )

        self.trend_plot = pg.PlotWidget(title="Spot X/Y Trend")
        self.trend_plot.setLabel("left", "position")
        self.trend_plot.setLabel("bottom", "sample")
        self.x_curve = self.trend_plot.plot(pen=pg.mkPen("#E4572E", width=2), name="x")
        self.y_curve = self.trend_plot.plot(pen=pg.mkPen("#17BEBB", width=2), name="y")
        self.trend_plot.addLegend()

        plot_layout.addWidget(self.xy_plot, 0, 0)
        plot_layout.addWidget(self.trend_plot, 1, 0)
        splitter.addWidget(plot_panel)
        splitter.setSizes([260, 600])

    def update_telemetry(self, telemetry: SunTelemetry, stats: TelemetryStats) -> None:
        values = {
            "seq": str(telemetry.seq),
            "x": f"{telemetry.spot_x:.6f}",
            "y": f"{telemetry.spot_y:.6f}",
            "sun_present": "yes" if telemetry.sun_present else "no",
            "frame_rate_hz": f"{stats.frame_rate_hz:.2f}",
            "drop_count": str(stats.drop_count),
            "crc_error_count": str(stats.crc_error_count),
            "raw_frame_hex": telemetry.raw_frame_hex,
        }
        for name, value in values.items():
            self.value_labels[name].setText(value)

        status_lines = [
            f"sun_present = {telemetry.sun_present}",
            f"x = {telemetry.spot_x:.6f}",
            f"y = {telemetry.spot_y:.6f}",
        ]
        for name, value in telemetry.status_flags.items():
            status_lines.append(f"{name}: {'yes' if value else 'no'}")
        self.status_text.setPlainText("\n".join(status_lines))

        self._append_plot_data(telemetry)
        self._refresh_plots()

    def clear(self) -> None:
        self._index = 0
        self._sample.clear()
        self._spot_x.clear()
        self._spot_y.clear()
        self._refresh_plots()

    def _append_plot_data(self, telemetry: SunTelemetry) -> None:
        self._index += 1
        self._sample.append(self._index)
        self._spot_x.append(telemetry.spot_x)
        self._spot_y.append(telemetry.spot_y)

    def _refresh_plots(self) -> None:
        samples = list(self._sample)
        spot_x = list(self._spot_x)
        spot_y = list(self._spot_y)
        self.xy_curve.setData(spot_x, spot_y)
        self.x_curve.setData(samples, spot_x)
        self.y_curve.setData(samples, spot_y)
