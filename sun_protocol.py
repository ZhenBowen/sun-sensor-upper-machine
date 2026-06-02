from __future__ import annotations

import struct
from typing import List, Optional

from sun_models import SpotTelemetry, SunTelemetry, TelemetryStats


SOF = b"\x55\xAA"
SOF_VALUE = 0xAA55
PROTOCOL_VERSION = 1
MSG_TYPE_TELEMETRY = 0x01
MSG_TYPE_COMMAND = 0x80
TELEMETRY_PAYLOAD_LEN = 24
TELEMETRY_FRAME_LEN = 2 + 4 + TELEMETRY_PAYLOAD_LEN + 2
MAX_PAYLOAD_LEN = 128
EB90_SOF = b"\xEB\x90"
EB90_FRAME_LEN = 26

_HEADER_STRUCT = struct.Struct("<HBBBB")
_PAYLOAD_STRUCT = struct.Struct("<HIHHHHhhhBBH")
_EB90_SPOT_STRUCT = struct.Struct(">f f")


class ProtocolError(ValueError):
    pass


class BadCrcError(ProtocolError):
    pass


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


def pack_telemetry(telemetry: SunTelemetry) -> bytes:
    payload = _PAYLOAD_STRUCT.pack(
        telemetry.seq & 0xFFFF,
        telemetry.timestamp_ms & 0xFFFFFFFF,
        telemetry.adc_vax1 & 0xFFFF,
        telemetry.adc_vax2 & 0xFFFF,
        telemetry.adc_vay1 & 0xFFFF,
        telemetry.adc_vay2 & 0xFFFF,
        int(telemetry.alpha_cdeg),
        int(telemetry.beta_cdeg),
        int(telemetry.temp_centi_c),
        telemetry.sun_present & 0xFF,
        telemetry.saturation_flag & 0xFF,
        telemetry.status_word & 0xFFFF,
    )
    body = bytes(
        [
            telemetry.version & 0xFF,
            telemetry.msg_type & 0xFF,
            telemetry.node_id & 0xFF,
            len(payload),
        ]
    ) + payload
    crc = crc16_modbus(body)
    return SOF + body + struct.pack("<H", crc)


def parse_telemetry_frame(frame: bytes) -> SunTelemetry:
    if len(frame) < 8:
        raise ProtocolError("frame too short")

    sof, version, msg_type, node_id, payload_len = _HEADER_STRUCT.unpack(frame[:6])
    if sof != SOF_VALUE:
        raise ProtocolError("invalid sof")
    if msg_type != MSG_TYPE_TELEMETRY:
        raise ProtocolError("invalid telemetry message type")
    if payload_len != TELEMETRY_PAYLOAD_LEN:
        raise ProtocolError(f"unsupported payload length: {payload_len}")

    expected_len = 2 + 4 + payload_len + 2
    if len(frame) != expected_len:
        raise ProtocolError(f"invalid frame length: {len(frame)}")

    expected_crc = crc16_modbus(frame[2:-2])
    actual_crc = struct.unpack("<H", frame[-2:])[0]
    if actual_crc != expected_crc:
        raise BadCrcError(f"bad crc: expected 0x{expected_crc:04X}, got 0x{actual_crc:04X}")

    payload = frame[6:-2]
    (
        seq,
        timestamp_ms,
        adc_vax1,
        adc_vax2,
        adc_vay1,
        adc_vay2,
        alpha_cdeg,
        beta_cdeg,
        temp_centi_c,
        sun_present,
        saturation_flag,
        status_word,
    ) = _PAYLOAD_STRUCT.unpack(payload)

    return SunTelemetry(
        version=version,
        msg_type=msg_type,
        node_id=node_id,
        seq=seq,
        timestamp_ms=timestamp_ms,
        adc_vax1=adc_vax1,
        adc_vax2=adc_vax2,
        adc_vay1=adc_vay1,
        adc_vay2=adc_vay2,
        alpha_cdeg=alpha_cdeg,
        beta_cdeg=beta_cdeg,
        temp_centi_c=temp_centi_c,
        sun_present=sun_present,
        saturation_flag=saturation_flag,
        status_word=status_word,
    )


def parse_eb90_frame(frame: bytes) -> SpotTelemetry:
    if len(frame) != EB90_FRAME_LEN:
        raise ProtocolError(f"invalid EB90 frame length: {len(frame)}")
    if frame[:2] != EB90_SOF:
        raise ProtocolError("invalid EB90 header")

    expected_checksum = sum(frame[:-1]) & 0xFF
    actual_checksum = frame[-1]
    if actual_checksum != expected_checksum:
        raise BadCrcError(
            f"bad EB90 checksum: expected 0x{expected_checksum:02X}, got 0x{actual_checksum:02X}"
        )

    sun_present = frame[2]
    x, y = _EB90_SPOT_STRUCT.unpack(frame[3:11])
    return SpotTelemetry(
        sun_present=sun_present,
        x=x,
        y=y,
        raw_frame_hex=frame.hex(" ").upper(),
    )


def pack_eb90_frame(sun_present: int, x: float, y: float, tail: bytes | None = None) -> bytes:
    tail_bytes = tail if tail is not None else b"\x00" * (EB90_FRAME_LEN - 12)
    if len(tail_bytes) != EB90_FRAME_LEN - 12:
        raise ValueError(f"EB90 tail must be {EB90_FRAME_LEN - 12} bytes")
    body = EB90_SOF + bytes([sun_present & 0xFF]) + _EB90_SPOT_STRUCT.pack(float(x), float(y)) + tail_bytes
    return body + bytes([sum(body) & 0xFF])


def hex_text_to_bytes(text: str) -> bytes:
    compact = "".join(text.strip().replace(",", " ").split())
    if len(compact) % 2:
        raise ValueError("hex string must contain an even number of digits")
    try:
        return bytes.fromhex(compact)
    except ValueError as exc:
        raise ValueError("hex string contains non-hex characters") from exc


def pack_command(node_id: int, cmd_id: int, payload: bytes = b"", version: int = PROTOCOL_VERSION) -> bytes:
    if len(payload) > 255:
        raise ValueError("command payload is too long")
    body = bytes(
        [
            version & 0xFF,
            MSG_TYPE_COMMAND,
            node_id & 0xFF,
            cmd_id & 0xFF,
            len(payload) & 0xFF,
        ]
    ) + payload
    crc = crc16_modbus(body)
    return SOF + body + struct.pack("<H", crc)


class TelemetryParser:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.crc_error_count = 0
        self.frame_error_count = 0
        self.drop_count = 0
        self.frame_count = 0
        self.byte_count = 0
        self._last_seq: Optional[int] = None

    def feed(self, data: bytes) -> List[SunTelemetry]:
        if not data:
            return []
        self.byte_count += len(data)
        self._buffer.extend(data)
        parsed: List[SunTelemetry] = []

        while True:
            start = self._buffer.find(SOF)
            if start < 0:
                if self._buffer[-1:] == SOF[:1]:
                    del self._buffer[:-1]
                else:
                    self._buffer.clear()
                break
            if start > 0:
                del self._buffer[:start]

            if len(self._buffer) < 6:
                break

            payload_len = self._buffer[5]
            if payload_len > MAX_PAYLOAD_LEN:
                self.frame_error_count += 1
                del self._buffer[0]
                continue

            frame_len = 2 + 4 + payload_len + 2
            if len(self._buffer) < frame_len:
                break

            frame = bytes(self._buffer[:frame_len])
            try:
                telemetry = parse_telemetry_frame(frame)
            except BadCrcError:
                self.crc_error_count += 1
                del self._buffer[0]
                continue
            except ProtocolError:
                self.frame_error_count += 1
                del self._buffer[0]
                continue

            del self._buffer[:frame_len]
            self._update_drop_count(telemetry.seq)
            self.frame_count += 1
            parsed.append(telemetry)

        return parsed

    def stats(self, frame_rate_hz: float = 0.0) -> TelemetryStats:
        return TelemetryStats(
            frame_rate_hz=frame_rate_hz,
            drop_count=self.drop_count,
            crc_error_count=self.crc_error_count,
            frame_count=self.frame_count,
            byte_count=self.byte_count,
        )

    def _update_drop_count(self, seq: int) -> None:
        if self._last_seq is None:
            self._last_seq = seq
            return
        expected = (self._last_seq + 1) & 0xFFFF
        if seq != expected:
            self.drop_count += (seq - expected) & 0xFFFF
        self._last_seq = seq


class EB90Parser:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.crc_error_count = 0
        self.frame_error_count = 0
        self.drop_count = 0
        self.frame_count = 0
        self.byte_count = 0

    def feed(self, data: bytes) -> List[SpotTelemetry]:
        if not data:
            return []
        self.byte_count += len(data)
        self._buffer.extend(data)
        parsed: List[SpotTelemetry] = []

        while True:
            start = self._buffer.find(EB90_SOF)
            if start < 0:
                if self._buffer[-1:] == EB90_SOF[:1]:
                    del self._buffer[:-1]
                else:
                    self._buffer.clear()
                break
            if start > 0:
                del self._buffer[:start]
            if len(self._buffer) < EB90_FRAME_LEN:
                break

            frame = bytes(self._buffer[:EB90_FRAME_LEN])
            try:
                telemetry = parse_eb90_frame(frame)
            except BadCrcError:
                self.crc_error_count += 1
                del self._buffer[0]
                continue
            except ProtocolError:
                self.frame_error_count += 1
                del self._buffer[0]
                continue

            del self._buffer[:EB90_FRAME_LEN]
            self.frame_count += 1
            parsed.append(telemetry)

        return parsed

    def stats(self, frame_rate_hz: float = 0.0) -> TelemetryStats:
        return TelemetryStats(
            frame_rate_hz=frame_rate_hz,
            drop_count=self.drop_count,
            crc_error_count=self.crc_error_count,
            frame_count=self.frame_count,
            byte_count=self.byte_count,
        )
