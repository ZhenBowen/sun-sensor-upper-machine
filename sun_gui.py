from __future__ import annotations

from datetime import datetime
from pathlib import Path
import struct
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sun_host import SerialThread, SunHost, available_serial_ports
from sun_logger import SunCsvLogger
from sun_models import CalibrationContext, TelemetryStats
from sun_monitor import SunMonitorWidget


class SunMainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Sun Sensor Upper Machine")
        self.resize(1400, 900)
        self.host = SunHost(self)
        self.logger = SunCsvLogger()
        self.latest_stats = TelemetryStats()
        self.log_dir = Path(__file__).resolve().parent / "logs"
        self._last_error_dialog_time = 0.0
        self._error_dialog_interval_s = 5.0
        self._last_telemetry_time = 0.0
        self._data_timeout_s = 5.0
        self._capture_pending = False
        self._build_ui()
        self._connect_signals()
        self._timeout_timer = QTimer(self)
        self._timeout_timer.timeout.connect(self._check_timeout)
        self._timeout_timer.start(2000)
        self.refresh_ports()
        self.statusBar().showMessage("Ready")

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.addWidget(self._build_connection_box())

        splitter = QSplitter(Qt.Horizontal)
        self.monitor = SunMonitorWidget()
        splitter.addWidget(self.monitor)
        splitter.addWidget(self._build_side_panel())
        splitter.setSizes([980, 420])
        root.addWidget(splitter, 1)
        self.setCentralWidget(central)

        refresh_action = QAction("Refresh Ports", self)
        refresh_action.triggered.connect(self.refresh_ports)
        self.addAction(refresh_action)

    def _build_connection_box(self) -> QGroupBox:
        box = QGroupBox("Connection")
        layout = QHBoxLayout(box)

        self.source_combo = QComboBox()
        self.source_combo.addItem("Simulator: normal", "sim_normal")
        self.source_combo.addItem("Simulator: CRC error", "sim_crc")
        self.source_combo.addItem("Simulator: drop frame", "sim_drop")
        self.source_combo.addItem("Serial / USB-RS485", "serial")

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItem("Recommended 32-byte", "recommended")
        self.protocol_combo.addItem("EB90 26-byte (original)", "eb90")
        self.protocol_combo.addItem("EB90 18-byte (test)", "eb90_test")

        self.port_combo = QComboBox()
        self.refresh_button = QPushButton("Refresh")
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "57600", "38400", "9600"])
        self.node_spin = QSpinBox()
        self.node_spin.setRange(0, 255)
        self.node_spin.setValue(1)
        self.rate_spin = QSpinBox()
        self.rate_spin.setRange(1, 100)
        self.rate_spin.setValue(10)
        self.acquisition_combo = QComboBox()
        self.acquisition_combo.addItem("自动采集", "continuous")
        self.acquisition_combo.addItem("逐点采集", "on_demand")
        self.capture_button = QPushButton("采集")
        self.capture_button.setEnabled(False)
        self.connect_button = QPushButton("Connect")

        layout.addWidget(QLabel("Source"))
        layout.addWidget(self.source_combo)
        layout.addWidget(QLabel("Protocol"))
        layout.addWidget(self.protocol_combo)
        layout.addWidget(QLabel("Port"))
        layout.addWidget(self.port_combo)
        layout.addWidget(self.refresh_button)
        layout.addWidget(QLabel("Baud"))
        layout.addWidget(self.baud_combo)
        layout.addWidget(QLabel("Node"))
        layout.addWidget(self.node_spin)
        layout.addWidget(QLabel("Hz"))
        layout.addWidget(self.rate_spin)
        layout.addWidget(QLabel("Mode"))
        layout.addWidget(self.acquisition_combo)
        layout.addWidget(self.capture_button)
        layout.addStretch(1)
        layout.addWidget(self.connect_button)
        return box

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._build_logging_box())
        layout.addWidget(self._build_calibration_box())
        layout.addWidget(self._build_command_box())
        layout.addWidget(self._build_event_box(), 1)
        return panel

    def _build_logging_box(self) -> QGroupBox:
        box = QGroupBox("CSV Logging")
        layout = QGridLayout(box)
        self.log_dir_edit = QLineEdit(str(self.log_dir))
        self.browse_log_button = QPushButton("Browse")
        self.log_button = QPushButton("Start Logging")
        self.log_status_label = QLabel("not logging")
        self.log_rows_label = QLabel("rows: 0")

        layout.addWidget(QLabel("Directory"), 0, 0)
        layout.addWidget(self.log_dir_edit, 0, 1)
        layout.addWidget(self.browse_log_button, 0, 2)
        layout.addWidget(self.log_button, 1, 0)
        layout.addWidget(self.log_status_label, 1, 1, 1, 2)
        layout.addWidget(self.log_rows_label, 2, 0, 1, 3)
        return box

    def _build_calibration_box(self) -> QGroupBox:
        box = QGroupBox("Calibration Context")
        layout = QFormLayout(box)
        self.alpha_ref_edit = QLineEdit("0.0")
        self.beta_ref_edit = QLineEdit("0.0")
        self.test_point_edit = QLineEdit("P001")
        self.comment_edit = QLineEdit("")
        layout.addRow("alpha_ref_deg", self.alpha_ref_edit)
        layout.addRow("beta_ref_deg", self.beta_ref_edit)
        layout.addRow("test_point", self.test_point_edit)
        layout.addRow("comment", self.comment_edit)
        return box

    def _build_command_box(self) -> QGroupBox:
        box = QGroupBox("Reserved Commands")
        layout = QGridLayout(box)
        self.raw_hex_edit = QLineEdit("eb 90 11 00 8c")
        self.raw_send_button = QPushButton("Send Raw Hex")
        self.query_button = QPushButton("Query Telemetry")
        self.rate10_button = QPushButton("Set 10 Hz")
        self.cal_on_button = QPushButton("Cal Mode On")
        self.cal_off_button = QPushButton("Cal Mode Off")
        self.reset_button = QPushButton("Reset Device")
        layout.addWidget(QLabel("Raw Hex"), 0, 0)
        layout.addWidget(self.raw_hex_edit, 0, 1)
        layout.addWidget(self.raw_send_button, 1, 0, 1, 2)
        layout.addWidget(self.query_button, 2, 0)
        layout.addWidget(self.rate10_button, 2, 1)
        layout.addWidget(self.cal_on_button, 3, 0)
        layout.addWidget(self.cal_off_button, 3, 1)
        layout.addWidget(self.reset_button, 4, 0, 1, 2)
        return box

    def _build_event_box(self) -> QGroupBox:
        box = QGroupBox("Event Log")
        layout = QVBoxLayout(box)
        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumBlockCount(500)
        layout.addWidget(self.event_log)
        return box

    def _connect_signals(self) -> None:
        self.refresh_button.clicked.connect(self.refresh_ports)
        self.connect_button.clicked.connect(self.toggle_connection)
        self.browse_log_button.clicked.connect(self.choose_log_dir)
        self.log_button.clicked.connect(self.toggle_logging)
        self.acquire_combo_changed()

        self.host.telemetry_received.connect(self.on_telemetry)
        self.host.stats_updated.connect(self.on_stats)
        self.host.status_changed.connect(self.on_status)
        self.host.error_occurred.connect(self.on_error)

        self.query_button.clicked.connect(lambda: self.send_command(0x01, b""))
        self.rate10_button.clicked.connect(lambda: self.send_command(0x02, struct.pack("<H", 10)))
        self.cal_on_button.clicked.connect(lambda: self.send_command(0x04, b"\x01"))
        self.cal_off_button.clicked.connect(lambda: self.send_command(0x04, b"\x00"))
        self.reset_button.clicked.connect(lambda: self.send_command(0x06, b""))
        self.raw_send_button.clicked.connect(self.send_raw_hex)
        self.acquisition_combo.currentIndexChanged.connect(self.acquire_combo_changed)
        self.capture_button.clicked.connect(self.capture_point)

    def refresh_ports(self) -> None:
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = available_serial_ports()
        self.port_combo.addItems(ports if ports else ["COM1"])
        if current:
            index = self.port_combo.findText(current)
            if index >= 0:
                self.port_combo.setCurrentIndex(index)
        self.append_event(f"Ports refreshed: {', '.join(ports) if ports else 'none detected'}")

    def toggle_connection(self) -> None:
        if self.host.is_running:
            self.host.stop()
            self.connect_button.setText("Connect")
            self.statusBar().showMessage("Disconnected")
            return

        source = self.source_combo.currentData()
        node_id = self.node_spin.value()
        if source == "serial":
            port = self.port_combo.currentText().strip()
            baudrate = int(self.baud_combo.currentText())
            protocol = self.protocol_combo.currentData()
            if not port:
                QMessageBox.warning(self, "No port", "Select a serial port first.")
                return
            self.host.start_serial(port=port, baudrate=baudrate, protocol=protocol)
        else:
            mode_map = {
                "sim_normal": "normal",
                "sim_crc": "crc_error",
                "sim_drop": "drop_frame",
            }
            protocol = self.protocol_combo.currentData()
            self.host.start_simulator(node_id=node_id, rate_hz=float(self.rate_spin.value()), mode=mode_map[source], protocol=protocol)

        self.monitor.clear()
        self.connect_button.setText("Disconnect")

    def choose_log_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select log directory", self.log_dir_edit.text())
        if selected:
            self.log_dir_edit.setText(selected)

    def toggle_logging(self) -> None:
        if self.logger.is_active:
            self.logger.stop()
            self.log_button.setText("Start Logging")
            self.log_status_label.setText("not logging")
            self.append_event("CSV logging stopped")
            return

        directory = Path(self.log_dir_edit.text()).expanduser()
        filename = f"sun_sensor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = directory / filename
        try:
            self.logger.start(path)
        except Exception as exc:
            QMessageBox.critical(self, "CSV error", str(exc))
            return
        self.log_button.setText("Stop Logging")
        self.log_status_label.setText(str(path))
        self.log_rows_label.setText("rows: 0")
        self.append_event(f"CSV logging started: {path}")

    def on_stats(self, stats: TelemetryStats) -> None:
        self.latest_stats = stats

    def on_telemetry(self, telemetry) -> None:
        if self.acquisition_combo.currentData() == "on_demand":
            if not self._capture_pending:
                return
            self._capture_pending = False
        self._last_telemetry_time = time.monotonic()
        self.monitor.update_telemetry(telemetry, self.latest_stats)
        if self.logger.is_active:
            try:
                self.logger.write(telemetry, self.latest_stats, self.current_calibration())
                self.log_rows_label.setText(f"rows: {self.logger.rows_written}")
            except Exception as exc:
                self.logger.stop()
                self.log_button.setText("Start Logging")
                self.log_status_label.setText("logging stopped by error")
                self.on_error(f"CSV write failed: {exc}")
        self.statusBar().showMessage(
            f"alpha={telemetry.spot_x:.4f} beta={telemetry.spot_y:.4f} sun={telemetry.sun_present} rate={self.latest_stats.frame_rate_hz:.2f} Hz"
        )

    def on_status(self, message: str) -> None:
        self.append_event(message)
        self.statusBar().showMessage(message)

    def on_error(self, message: str) -> None:
        self.append_event(f"ERROR: {message}")
        self.statusBar().showMessage(f"ERROR: {message}")
        self.connect_button.setText("Connect" if not self.host.is_running else "Disconnect")
        now = time.monotonic()
        if now - self._last_error_dialog_time >= self._error_dialog_interval_s:
            self._last_error_dialog_time = now
            QMessageBox.warning(self, "Sun upper machine error", message)

    def send_command(self, cmd_id: int, payload: bytes) -> None:
        node_id = self.node_spin.value()
        try:
            data = self.host.send_command(node_id=node_id, cmd_id=cmd_id, payload=payload)
        except Exception as exc:
            self.on_error(str(exc))
            return
        self.append_event(f"Command 0x{cmd_id:02X}: {data.hex(' ')}")

    def send_raw_hex(self) -> None:
        try:
            data = self.host.send_raw_hex(self.raw_hex_edit.text())
        except Exception as exc:
            self.on_error(str(exc))
            return
        self.append_event(f"Raw hex: {data.hex(' ').upper()}")

    def capture_point(self) -> None:
        if not self.host.is_running:
            self.append_event("采集: 未连接")
            return
        self._capture_pending = True
        if isinstance(self.host._thread, SerialThread):
            self.send_command(0x01, b"")
        self.append_event("采集: 等待数据...")

    def acquire_combo_changed(self) -> None:
        on_demand = self.acquisition_combo.currentData() == "on_demand"
        self.capture_button.setEnabled(on_demand)

    def current_calibration(self) -> CalibrationContext:
        return CalibrationContext(
            alpha_ref_deg=self._float_from_edit(self.alpha_ref_edit, 0.0),
            beta_ref_deg=self._float_from_edit(self.beta_ref_edit, 0.0),
            test_point=self.test_point_edit.text().strip(),
            comment=self.comment_edit.text().strip(),
        )

    def append_event(self, message: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.event_log.appendPlainText(f"[{stamp}] {message}")

    def _check_timeout(self) -> None:
        if not self.host.is_running:
            return
        if self._last_telemetry_time <= 0:
            return
        elapsed = time.monotonic() - self._last_telemetry_time
        if elapsed >= self._data_timeout_s:
            self.statusBar().showMessage(f"WARNING: no telemetry data for {elapsed:.1f} seconds")

    @staticmethod
    def _float_from_edit(edit: QLineEdit, default: float) -> float:
        try:
            return float(edit.text().strip())
        except ValueError:
            return default

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API name
        self.host.stop()
        self.logger.stop()
        event.accept()
