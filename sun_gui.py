from __future__ import annotations

from datetime import datetime
from pathlib import Path
import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QAction,
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
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from sun_host import SerialThread, SimulatorThread, SunHost, available_serial_ports
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
        self._raw_byte_count = 0
        self._raw_logged_first = False
        self._acquiring = False
        self._auto_sent = 0
        self._acq_timer = QTimer(self)
        self._acq_timer.timeout.connect(self._on_acq_timer)
        self._build_ui()
        self._connect_signals()
        self._timeout_timer = QTimer(self)
        self._timeout_timer.timeout.connect(self._check_timeout)
        self._timeout_timer.start(2000)
        self.refresh_ports()
        self._update_mode_ui()
        self.statusBar().showMessage("Ready")

    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.addWidget(self._build_connection_box())
        root.addWidget(self._build_acquisition_box())

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
        layout.addStretch(1)
        layout.addWidget(self.connect_button)
        return box

    def _build_acquisition_box(self) -> QGroupBox:
        box = QGroupBox("Acquisition")
        layout = QHBoxLayout(box)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Single", "single")
        self.mode_combo.addItem("Auto", "auto")

        self.freq_spin = QSpinBox()
        self.freq_spin.setRange(1, 1000)
        self.freq_spin.setValue(10)
        self.freq_spin.setSuffix(" Hz")

        self.count_spin = QSpinBox()
        self.count_spin.setRange(0, 99999)
        self.count_spin.setValue(0)
        self.count_spin.setSpecialValueText("Unlimited")

        self.command_edit = QLineEdit("00 10 01 11")

        self.send_stop_button = QPushButton("Send")

        layout.addWidget(QLabel("Mode"))
        layout.addWidget(self.mode_combo)
        layout.addWidget(QLabel("Freq"))
        layout.addWidget(self.freq_spin)
        layout.addWidget(QLabel("Count"))
        layout.addWidget(self.count_spin)
        layout.addWidget(QLabel("(0=\u221e)"))
        layout.addWidget(QLabel("Command"))
        layout.addWidget(self.command_edit, 1)
        layout.addWidget(self.send_stop_button)
        return box

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addWidget(self._build_logging_box())
        layout.addWidget(self._build_calibration_box())
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
        self.send_stop_button.clicked.connect(self.toggle_acquisition)
        self.mode_combo.currentIndexChanged.connect(self._update_mode_ui)
        self.source_combo.currentIndexChanged.connect(self._update_source_ui)

        self.host.telemetry_received.connect(self.on_telemetry)
        self.host.stats_updated.connect(self.on_stats)
        self.host.status_changed.connect(self.on_status)
        self.host.error_occurred.connect(self.on_error)
        self.host.raw_bytes_received.connect(self.on_raw_bytes)

    def _update_mode_ui(self) -> None:
        is_auto = self.mode_combo.currentData() == "auto"
        self.freq_spin.setEnabled(is_auto)
        self.count_spin.setEnabled(is_auto)

    def _update_source_ui(self) -> None:
        is_serial = self.source_combo.currentData() == "serial"
        self.port_combo.setEnabled(is_serial)
        self.baud_combo.setEnabled(is_serial)
        self.refresh_button.setEnabled(is_serial)

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
            self._stop_acquisition()
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
            mode_str = mode_map[source]
            is_auto = self.mode_combo.currentData() == "auto"
            if is_auto:
                self.host.start_simulator(node_id=node_id, rate_hz=float(self.freq_spin.value()), mode=mode_str, protocol=protocol, continuous=True)
            else:
                self.host.start_simulator(node_id=node_id, rate_hz=float(self.freq_spin.value()), mode=mode_str, protocol=protocol, continuous=False)

        self.monitor.clear()
        self._raw_byte_count = 0
        self._raw_logged_first = False
        self.connect_button.setText("Disconnect")

    def toggle_acquisition(self) -> None:
        if not self.host.is_running:
            QMessageBox.information(self, "Not connected", "Connect to a source first.")
            return

        if self._acquiring:
            self._stop_acquisition()
            return

        mode = self.mode_combo.currentData()
        if mode == "single":
            self._trigger_single()
        else:
            self._start_auto()

    def _trigger_single(self) -> None:
        if isinstance(self.host._thread, SimulatorThread):
            self.host.trigger_single()
            self.append_event("Single: triggered simulator frame")
        else:
            try:
                data = self.host.send_raw_hex(self.command_edit.text())
                self.append_event(f"Single: sent {data.hex(' ').upper()}")
            except Exception as exc:
                self.on_error(str(exc))

    def _start_auto(self) -> None:
        freq = max(self.freq_spin.value(), 1)
        self._auto_sent = 0
        self._acquiring = True
        self.send_stop_button.setText("Stop")
        self.mode_combo.setEnabled(False)
        self.freq_spin.setEnabled(False)
        self.count_spin.setEnabled(False)
        self.command_edit.setEnabled(False)
        self.source_combo.setEnabled(False)
        self.protocol_combo.setEnabled(False)
        self.connect_button.setEnabled(False)

        if isinstance(self.host._thread, SimulatorThread):
            self.append_event(f"Auto: simulator continuous at {freq} Hz")
        else:
            try:
                data = self.host.send_raw_hex(self.command_edit.text())
                self.append_event(f"Auto: started, first command sent ({data.hex(' ').upper()})")
            except Exception as exc:
                self.on_error(str(exc))
                self._stop_acquisition()
                return

        interval_ms = max(10, int(1000.0 / freq))
        self._acq_timer.start(interval_ms)

    def _stop_acquisition(self) -> None:
        self._acq_timer.stop()
        self._acquiring = False
        self.send_stop_button.setText("Send")
        self.mode_combo.setEnabled(True)
        self.command_edit.setEnabled(True)
        self.source_combo.setEnabled(True)
        self.protocol_combo.setEnabled(True)
        self.connect_button.setEnabled(True)
        self._update_mode_ui()

        if isinstance(self.host._thread, SimulatorThread):
            pass
        else:
            self.append_event(f"Auto: stopped after {self._auto_sent} commands")

    def _on_acq_timer(self) -> None:
        if not self.host.is_running:
            self._stop_acquisition()
            return

        target = self.count_spin.value()
        if target > 0 and self._auto_sent >= target:
            self._stop_acquisition()
            return

        if isinstance(self.host._thread, SimulatorThread):
            self.host.trigger_single()
        else:
            try:
                self.host.send_raw_hex(self.command_edit.text())
            except Exception as exc:
                self.on_error(str(exc))
                self._stop_acquisition()
                return

        self._auto_sent += 1

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

    def on_raw_bytes(self, data: bytes) -> None:
        self._raw_byte_count += len(data)
        if not self._raw_logged_first:
            self._raw_logged_first = True
            self.append_event(f"收到原始数据: {data.hex(' ').upper()[:60]}... (共{len(data)}字节)")

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
        self._stop_acquisition()
        self.host.stop()
        self.logger.stop()
        event.accept()