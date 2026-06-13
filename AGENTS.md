# Sun Sensor Upper Machine — Agent Guide

## Quick start
```powershell
# Run GUI
python run_sun_gui.py

# Run all tests (unittest, not pytest)
python tests\run_tests.py

# Single test file
python -m unittest tests\test_sun_protocol.py -v
```

## Architecture (single-module, no package)
| File | Role |
|---|---|
| `run_sun_gui.py` | Entry point: creates QApplication, instantiates SunMainWindow |
| `sun_gui.py` | Main window, connection/logging/calibration/command panels |
| `sun_host.py` | QThread wrappers (SimulatorThread, SerialThread), relays signals via SunHost |
| `sun_protocol.py` | Frame format, CRC-16/Modbus, TelemetryParser/EB90Parser byte-stream parsers |
| `sun_monitor.py` | pyqtgraph real-time plots + telemetry value/status display |
| `sun_logger.py` | CSV logger (utf-8-sig BOM, flushes every 10 rows) |
| `sun_models.py` | Data classes: SunTelemetry, SpotTelemetry, TelemetryStats, CalibrationContext |
| `sun_simulator.py` | Simulated SunTelemetry generator (normal/crc_error/drop_frame modes) |
| `tests/run_tests.py` | Test discover runner |

## Key conventions & quirks

- using "D:\Anaconda3\envs\py311\python.exe"

- All files use `from __future__ import annotations`
- Every frame parse path goes through `TelemetryParser.feed(bytes) -> List[SunTelemetry]` or `EB90Parser.feed(bytes) -> List[SpotTelemetry]`
- Two protocol modes: `"recommended"` (32-byte, SOF 0x55AA, CRC-16/Modbus) and `"eb90"` (26-byte, SOF 0xEB90, simple checksum)
- pyserial is **guarded import** (`SERIAL_AVAILABLE` flag); tests and simulator work without it
- Simulator outputs real binary frames via `pack_telemetry` — the same parser as real serial
- No `requirements.txt` exists; install deps: `PyQt5`, `pyqtgraph`, `pyserial`
- Python 3.11+ union syntax (`QWidget \| None`) used in some files; `Optional[]` others
- GUI tests need `QT_QPA_PLATFORM=offscreen` env var (set in test file)
- CSV field order is frozen in `sun_logger.py:CSV_FIELDS` — do not change column names

## Known bugs (from code review) — fix before new work
1. `sun_simulator.py` `drop_frame` mode: `_seq` advances by 3 instead of 2, dropping 2 frames per trigger instead of 1. Fix: move increment after the normal `seq = self._seq; self._seq += 1`, then add extra `+1` only in the drop condition.
2. `sun_gui.py` `toggle_connection()` sets button text before thread starts; on serial open failure, button stays "Disconnect". Fix: in `on_error()`, reset button if `not self.host.is_running`.

## Style notes
- Qt camelCase methods use `# noqa: N802`
- Type annotations preferred; avoid bare dict/object passing
- New features should add test cases in the `tests/` directory
