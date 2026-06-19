from __future__ import annotations

from collections import deque
import threading
import time
from typing import Optional

from PyQt5.QtCore import QObject, QThread, pyqtSignal

from sun_protocol import EB90Parser, EB90TestParser, TelemetryParser, hex_text_to_bytes, pack_command
from sun_simulator import SunSimulator

try:
    import serial
    from serial.tools import list_ports
    import serial.rs485 as _rs485

    SERIAL_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on local environment
    serial = None
    list_ports = None
    _rs485 = None
    SERIAL_AVAILABLE = False


class RateMeter:
    def __init__(self, window_s: float = 2.0) -> None:
        self.window_s = window_s
        self._times: deque[float] = deque()

    def mark(self) -> float:
        now = time.monotonic()
        self._times.append(now)
        while self._times and now - self._times[0] > self.window_s:
            self._times.popleft()
        if len(self._times) < 2:
            return 0.0
        duration = self._times[-1] - self._times[0]
        if duration <= 0:
            return 0.0
        return (len(self._times) - 1) / duration


class _TelemetryThread(QThread):
    telemetry_received = pyqtSignal(object)
    stats_updated = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    raw_bytes_received = pyqtSignal(bytes)

    def __init__(self) -> None:
        super().__init__()
        self._running = False

    def stop(self) -> None:
        self._running = False


class SimulatorThread(_TelemetryThread):
    def __init__(self, node_id: int = 1, rate_hz: float = 10.0, mode: str = "normal", protocol: str = "recommended", continuous: bool = True) -> None:
        super().__init__()
        self.node_id = node_id
        self.rate_hz = rate_hz
        self.mode = mode
        self.protocol = protocol
        self._continuous = continuous
        self._trigger = threading.Event()

    def trigger(self) -> None:
        self._trigger.set()

    def run(self) -> None:
        self._running = True
        simulator = SunSimulator(node_id=self.node_id, rate_hz=self.rate_hz, mode=self.mode)
        parser = self._make_parser()
        meter = RateMeter()
        mode_desc = "continuous" if self._continuous else "single-shot"
        self.status_changed.emit(f"Simulator ready ({mode_desc}, {self.rate_hz:.1f} Hz, protocol={self.protocol})")

        if self._continuous:
            self._run_continuous(simulator, parser, meter)
        else:
            self._run_single_shot(simulator, parser, meter)

        self.status_changed.emit("Simulator stopped")

    def _run_continuous(self, simulator: SunSimulator, parser, meter: RateMeter) -> None:
        interval_ms = max(1, int(round(1000.0 / max(self.rate_hz, 0.1))))
        while self._running:
            self._generate_one(simulator, parser, meter)
            self.msleep(interval_ms)

    def _run_single_shot(self, simulator: SunSimulator, parser, meter: RateMeter) -> None:
        while self._running:
            self._trigger.wait(timeout=0.5)
            if not self._running:
                break
            if self._trigger.is_set():
                self._trigger.clear()
                self._generate_one(simulator, parser, meter)

    def _generate_one(self, simulator: SunSimulator, parser, meter: RateMeter) -> None:
        if self.protocol == "eb90_test":
            frame = simulator.next_eb90_test_frame()
        else:
            frame = simulator.next_frame()
        self.raw_bytes_received.emit(frame)
        for telemetry in parser.feed(frame):
            rate = meter.mark()
            stats = parser.stats(frame_rate_hz=rate)
            self.stats_updated.emit(stats)
            self.telemetry_received.emit(telemetry)

    def _make_parser(self):
        if self.protocol == "eb90":
            return EB90Parser()
        if self.protocol == "eb90_test":
            return EB90TestParser()
        return TelemetryParser()


class SerialThread(_TelemetryThread):
    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout_s: float = 0.1,
        protocol: str = "recommended",
    ) -> None:
        super().__init__()
        self.port = port
        self.baudrate = baudrate
        self.timeout_s = timeout_s
        self.protocol = protocol
        self._serial = None
        self._rs485_manual = False

    def run(self) -> None:
        if not SERIAL_AVAILABLE:
            self.error_occurred.emit("pyserial is not installed")
            return

        self._running = True
        parser = self._make_parser()
        meter = RateMeter()
        try:
            self._serial = serial.Serial(self.port, self.baudrate, timeout=self.timeout_s)
            if _rs485 is not None:
                self._serial.rs485_mode = _rs485.RS485Settings(
                    rts_level_for_tx=True,
                    rts_level_for_rx=False,
                    delay_before_tx=None,
                    delay_before_rx=None,
                )
                self._rs485_manual = False
            else:
                self._serial.rts = False
                self._rs485_manual = True
            self.status_changed.emit(
                f"Serial opened: {self.port} @ {self.baudrate}, protocol={self.protocol}"
                + (" (RS485 auto)" if not self._rs485_manual else " (RS485 manual)")
            )
            while self._running:
                waiting = getattr(self._serial, "in_waiting", 0)
                data = self._serial.read(waiting if waiting > 0 else 1)
                if not data:
                    continue
                self.raw_bytes_received.emit(data)
                for telemetry in parser.feed(data):
                    rate = meter.mark()
                    stats = parser.stats(frame_rate_hz=rate)
                    self.stats_updated.emit(stats)
                    self.telemetry_received.emit(telemetry)
        except Exception as exc:  # pragma: no cover - hardware dependent
            self.error_occurred.emit(str(exc))
        finally:
            try:
                if self._serial is not None and self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None
                self.status_changed.emit("Serial stopped")

    def send(self, data: bytes) -> None:
        if self._serial is None or not self._serial.is_open:
            raise RuntimeError("serial port is not open")
        if self._rs485_manual:
            self._serial.rts = True
        self._serial.write(data)
        self._serial.flush()
        if self._rs485_manual:
            self._serial.rts = False

    def stop(self) -> None:
        self._running = False
        try:
            if self._serial is not None:
                self._serial.cancel_read()
        except Exception:
            pass

    def _make_parser(self):
            if self.protocol == "eb90":
                return EB90Parser()
            if self.protocol == "eb90_test":
                return EB90TestParser()
            return TelemetryParser()


class SunHost(QObject):
    telemetry_received = pyqtSignal(object)
    stats_updated = pyqtSignal(object)
    status_changed = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    raw_bytes_received = pyqtSignal(bytes)

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._thread: Optional[_TelemetryThread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_simulator(self, node_id: int = 1, rate_hz: float = 10.0, mode: str = "normal", protocol: str = "recommended", continuous: bool = True) -> None:
        self.stop()
        self._thread = SimulatorThread(node_id=node_id, rate_hz=rate_hz, mode=mode, protocol=protocol, continuous=continuous)
        self._connect_thread_signals(self._thread)
        self._thread.start()

    def start_serial(self, port: str, baudrate: int = 115200, protocol: str = "recommended") -> None:
        self.stop()
        self._thread = SerialThread(port=port, baudrate=baudrate, protocol=protocol)
        self._connect_thread_signals(self._thread)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._thread.stop()
        self._thread.wait(2000)
        self._thread = None

    def send_command(self, node_id: int, cmd_id: int, payload: bytes = b"") -> bytes:
        data = pack_command(node_id=node_id, cmd_id=cmd_id, payload=payload)
        if isinstance(self._thread, SerialThread) and self._thread.isRunning():
            self._thread.send(data)
            self.status_changed.emit(f"Command sent: 0x{cmd_id:02X}")
        else:
            self.status_changed.emit(f"Command built but not sent: 0x{cmd_id:02X}")
        return data

    def send_raw_hex(self, text: str) -> bytes:
        data = hex_text_to_bytes(text)
        if isinstance(self._thread, SerialThread) and self._thread.isRunning():
            self._thread.send(data)
            self.status_changed.emit(f"Raw hex sent: {data.hex(' ').upper()}")
        else:
            self.status_changed.emit(f"Raw hex built but not sent: {data.hex(' ').upper()}")
        return data

    def trigger_single(self) -> None:
        if isinstance(self._thread, SimulatorThread) and self._thread.isRunning():
            self._thread.trigger()

    def _connect_thread_signals(self, thread: _TelemetryThread) -> None:
        thread.telemetry_received.connect(self.telemetry_received)
        thread.stats_updated.connect(self.stats_updated)
        thread.status_changed.connect(self.status_changed)
        thread.error_occurred.connect(self.error_occurred)
        thread.raw_bytes_received.connect(self.raw_bytes_received)


def available_serial_ports() -> list[str]:
    if not SERIAL_AVAILABLE or list_ports is None:
        return []
    return [item.device for item in list_ports.comports()]
