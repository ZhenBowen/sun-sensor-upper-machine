from __future__ import annotations

import math
import random
from dataclasses import dataclass

from sun_models import SunTelemetry
from sun_protocol import pack_eb90_test_frame, pack_telemetry


@dataclass
class SunSimulator:
    node_id: int = 1
    rate_hz: float = 10.0
    mode: str = "normal"
    crc_error_every: int = 25
    drop_frame_every: int = 40
    seed: int = 20260601

    def __post_init__(self) -> None:
        self._seq = 0
        self._frame_index = 0
        self._timestamp_ms = 0
        self._rng = random.Random(self.seed)

    def next_telemetry(self) -> SunTelemetry:
        self._frame_index += 1

        seq = self._seq
        self._seq = (self._seq + 1) & 0xFFFF
        if self.mode == "drop_frame" and self.drop_frame_every > 0 and self._frame_index % self.drop_frame_every == 0:
            self._seq = (self._seq + 1) & 0xFFFF
        self._timestamp_ms += int(round(1000.0 / max(self.rate_hz, 0.1)))

        t = self._frame_index / max(self.rate_hz, 0.1)
        alpha = 30.0 * math.sin(t * 0.45)
        beta = 20.0 * math.cos(t * 0.35)
        temp = 25.0 + 2.0 * math.sin(t / 20.0)

        noise = lambda: self._rng.uniform(-8.0, 8.0)
        adc_vax1 = self._clip_adc(1800.0 - alpha * 10.0 + noise())
        adc_vax2 = self._clip_adc(1800.0 + alpha * 10.0 + noise())
        adc_vay1 = self._clip_adc(1800.0 - beta * 10.0 + noise())
        adc_vay2 = self._clip_adc(1800.0 + beta * 10.0 + noise())

        saturation = int(max(adc_vax1, adc_vax2, adc_vay1, adc_vay2) >= 4095)
        status_word = 0x0001 | 0x0002
        if saturation:
            status_word |= 0x0004

        return SunTelemetry(
            version=1,
            msg_type=0x01,
            node_id=self.node_id,
            seq=seq,
            timestamp_ms=self._timestamp_ms,
            adc_vax1=adc_vax1,
            adc_vax2=adc_vax2,
            adc_vay1=adc_vay1,
            adc_vay2=adc_vay2,
            alpha_cdeg=int(round(alpha * 100.0)),
            beta_cdeg=int(round(beta * 100.0)),
            temp_centi_c=int(round(temp * 100.0)),
            sun_present=1,
            saturation_flag=saturation,
            status_word=status_word,
        )

    def next_frame(self) -> bytes:
        telemetry = self.next_telemetry()
        frame = bytearray(pack_telemetry(telemetry))
        if self.mode == "crc_error" and self.crc_error_every > 0 and self._frame_index % self.crc_error_every == 0:
            frame[-1] ^= 0xFF
        return bytes(frame)

    def next_eb90_test_frame(self) -> bytes:
        telemetry = self.next_telemetry()
        frame = bytearray(
            pack_eb90_test_frame(
                sun_present=telemetry.sun_present & 0x01,
                alpha=telemetry.alpha_deg,
                beta=telemetry.beta_deg,
                adc_vax1=telemetry.adc_vax1,
                adc_vax2=telemetry.adc_vax2,
                adc_vay1=telemetry.adc_vay1,
                adc_vay2=telemetry.adc_vay2,
            )
        )
        if self.mode == "crc_error" and self.crc_error_every > 0 and self._frame_index % self.crc_error_every == 0:
            frame[-1] ^= 0xFF
        return bytes(frame)

    @staticmethod
    def _clip_adc(value: float) -> int:
        return max(0, min(4095, int(round(value))))
