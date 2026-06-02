from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import time
from typing import Optional, TextIO

from sun_models import CalibrationContext, SunTelemetry, TelemetryStats


CSV_FIELDS = [
    "pc_time_iso",
    "pc_time_ms",
    "seq",
    "node_id",
    "timestamp_ms",
    "adc_vax1",
    "adc_vax2",
    "adc_vay1",
    "adc_vay2",
    "alpha_deg",
    "beta_deg",
    "x",
    "y",
    "temp_c",
    "sun_present",
    "saturation_flag",
    "status_word",
    "valid_flag",
    "signal_sum",
    "rx",
    "ry",
    "frame_rate_hz",
    "drop_count",
    "crc_error_count",
    "alpha_ref_deg",
    "beta_ref_deg",
    "test_point",
    "comment",
    "raw_frame_hex",
]


class SunCsvLogger:
    FLUSH_INTERVAL = 10

    def __init__(self) -> None:
        self._handle: Optional[TextIO] = None
        self._writer: Optional[csv.DictWriter] = None
        self.path: Optional[Path] = None
        self.rows_written = 0
        self._rows_since_flush = 0

    @property
    def is_active(self) -> bool:
        return self._writer is not None and self._handle is not None

    def start(self, path: str | Path) -> Path:
        if self.is_active:
            self.stop()
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8-sig", newline="")
        self._writer = csv.DictWriter(self._handle, fieldnames=CSV_FIELDS)
        self._writer.writeheader()
        self._handle.flush()
        self.rows_written = 0
        self._rows_since_flush = 0
        return self.path

    def write(
        self,
        telemetry: SunTelemetry,
        stats: TelemetryStats,
        calibration: CalibrationContext,
    ) -> None:
        if self._writer is None or self._handle is None:
            raise RuntimeError("CSV logger is not active")

        row = {
            "pc_time_iso": datetime.now().isoformat(timespec="milliseconds"),
            "pc_time_ms": str(int(time.time() * 1000)),
            "seq": str(telemetry.seq),
            "node_id": str(telemetry.node_id),
            "timestamp_ms": str(telemetry.timestamp_ms),
            "adc_vax1": str(telemetry.adc_vax1),
            "adc_vax2": str(telemetry.adc_vax2),
            "adc_vay1": str(telemetry.adc_vay1),
            "adc_vay2": str(telemetry.adc_vay2),
            "alpha_deg": f"{telemetry.alpha_deg:.2f}",
            "beta_deg": f"{telemetry.beta_deg:.2f}",
            "x": f"{telemetry.spot_x:.6f}",
            "y": f"{telemetry.spot_y:.6f}",
            "temp_c": f"{telemetry.temp_c:.2f}",
            "sun_present": str(int(bool(telemetry.sun_present))),
            "saturation_flag": str(int(bool(telemetry.saturation_flag))),
            "status_word": f"0x{telemetry.status_word:04X}",
            "valid_flag": str(int(telemetry.valid_flag)),
            "signal_sum": str(telemetry.signal_sum),
            "rx": f"{telemetry.rx:.6f}",
            "ry": f"{telemetry.ry:.6f}",
            "frame_rate_hz": f"{stats.frame_rate_hz:.2f}",
            "drop_count": str(stats.drop_count),
            "crc_error_count": str(stats.crc_error_count),
            "alpha_ref_deg": f"{calibration.alpha_ref_deg:.2f}",
            "beta_ref_deg": f"{calibration.beta_ref_deg:.2f}",
            "test_point": calibration.test_point,
            "comment": calibration.comment,
            "raw_frame_hex": telemetry.raw_frame_hex,
        }
        self._writer.writerow(row)
        self.rows_written += 1
        self._rows_since_flush += 1
        if self._rows_since_flush >= self.FLUSH_INTERVAL:
            self._handle.flush()
            self._rows_since_flush = 0

    def stop(self) -> None:
        if self._handle is not None:
            self._handle.flush()
            self._handle.close()
        self._handle = None
        self._writer = None
