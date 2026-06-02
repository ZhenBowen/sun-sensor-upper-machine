from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Dict


STATUS_BITS = {
    0: "VALID",
    1: "SUN_PRESENT",
    2: "SATURATED",
    3: "LOW_SIGNAL",
    4: "ADC_ERROR",
    5: "TEMP_WARNING",
    6: "CALIBRATION_MODE",
    7: "PARAM_ERROR",
}


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class SunTelemetry:
    version: int = 1
    msg_type: int = 0x01
    node_id: int = 1
    seq: int = 0
    timestamp_ms: int = 0
    adc_vax1: int = 0
    adc_vax2: int = 0
    adc_vay1: int = 0
    adc_vay2: int = 0
    alpha_cdeg: int = 0
    beta_cdeg: int = 0
    temp_centi_c: int = 0
    sun_present: int = 0
    saturation_flag: int = 0
    status_word: int = 0
    received_time_ms: int = field(default_factory=now_ms)
    raw_frame_hex: str = ""

    @property
    def alpha_deg(self) -> float:
        return self.alpha_cdeg / 100.0

    @property
    def beta_deg(self) -> float:
        return self.beta_cdeg / 100.0

    @property
    def temp_c(self) -> float:
        return self.temp_centi_c / 100.0

    @property
    def valid_flag(self) -> bool:
        return bool(self.status_word & 0x0001)

    @property
    def signal_sum(self) -> int:
        return self.adc_vax1 + self.adc_vax2 + self.adc_vay1 + self.adc_vay2

    @property
    def rx(self) -> float:
        denom = self.adc_vax1 + self.adc_vax2
        if denom <= 0:
            return 0.0
        return (self.adc_vax2 - self.adc_vax1) / denom

    @property
    def ry(self) -> float:
        denom = self.adc_vay1 + self.adc_vay2
        if denom <= 0:
            return 0.0
        return (self.adc_vay2 - self.adc_vay1) / denom

    @property
    def status_flags(self) -> Dict[str, bool]:
        return {name: bool(self.status_word & (1 << bit)) for bit, name in STATUS_BITS.items()}

    @property
    def spot_x(self) -> float:
        return self.alpha_deg

    @property
    def spot_y(self) -> float:
        return self.beta_deg


@dataclass(frozen=True)
class SpotTelemetry:
    sun_present: int
    x: float
    y: float
    raw_frame_hex: str = ""
    seq: int = 0
    node_id: int = 0
    timestamp_ms: int = 0
    status_word: int = 0
    saturation_flag: int = 0
    received_time_ms: int = field(default_factory=now_ms)

    @property
    def spot_x(self) -> float:
        return self.x

    @property
    def spot_y(self) -> float:
        return self.y

    @property
    def alpha_deg(self) -> float:
        return self.x

    @property
    def beta_deg(self) -> float:
        return self.y

    @property
    def temp_c(self) -> float:
        return 0.0

    @property
    def adc_vax1(self) -> int:
        return 0

    @property
    def adc_vax2(self) -> int:
        return 0

    @property
    def adc_vay1(self) -> int:
        return 0

    @property
    def adc_vay2(self) -> int:
        return 0

    @property
    def valid_flag(self) -> bool:
        return bool(self.sun_present)

    @property
    def signal_sum(self) -> int:
        return 0

    @property
    def rx(self) -> float:
        return self.x

    @property
    def ry(self) -> float:
        return self.y

    @property
    def status_flags(self) -> Dict[str, bool]:
        return {
            "VALID": bool(self.sun_present),
            "SUN_PRESENT": bool(self.sun_present),
            "SATURATED": False,
            "LOW_SIGNAL": not bool(self.sun_present),
            "ADC_ERROR": False,
            "TEMP_WARNING": False,
            "CALIBRATION_MODE": False,
            "PARAM_ERROR": False,
        }


@dataclass
class TelemetryStats:
    frame_rate_hz: float = 0.0
    drop_count: int = 0
    crc_error_count: int = 0
    frame_count: int = 0
    byte_count: int = 0


@dataclass
class CalibrationContext:
    alpha_ref_deg: float = 0.0
    beta_ref_deg: float = 0.0
    test_point: str = ""
    comment: str = ""
