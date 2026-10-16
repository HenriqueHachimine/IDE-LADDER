"""Codificacao e analise incremental de quadros LDP (espelha ldp_frame.c)."""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass

from ..core.crc import crc16_modbus
from .protocol import FRAME_TIMEOUT_MS, MAX_PAYLOAD, SOF, VERSION


@dataclass(frozen=True)
class Frame:
    type: int
    seq: int
    flags: int
    payload: bytes


def encode(type_: int, seq: int, flags: int = 0, payload: bytes = b"") -> bytes:
    if len(payload) > MAX_PAYLOAD:
        raise ValueError("payload grande demais")
    body = struct.pack("<BBBBH", VERSION, type_, seq & 0xFF, flags, len(payload)) + payload
    return SOF + body + struct.pack("<H", crc16_modbus(body))


class FrameParser:
    """Recebe bytes em pedacos arbitrarios e devolve quadros validos."""

    def __init__(self, clock=time.monotonic):
        self._buf = bytearray()
        self._clock = clock
        self._last = 0.0

    def reset(self) -> None:
        self._buf.clear()

    def feed(self, data: bytes) -> list[Frame]:
        now = self._clock()
        if self._buf and (now - self._last) * 1000 > FRAME_TIMEOUT_MS:
            self._buf.clear()
        self._last = now
        self._buf += data
        frames = []
        while True:
            start = self._buf.find(SOF)
            if start < 0:
                # guarda um eventual primeiro byte de SOF no fim
                del self._buf[:-1 if self._buf[-1:] == SOF[:1] else len(self._buf)]
                return frames
            del self._buf[:start]
            if len(self._buf) < 8:
                return frames
            ver, type_, seq, flags, length = struct.unpack_from("<BBBBH", self._buf, 2)
            if length > MAX_PAYLOAD:
                del self._buf[:2]
                continue
            total = 8 + length + 2
            if len(self._buf) < total:
                return frames
            body = bytes(self._buf[2:8 + length])
            (crc,) = struct.unpack_from("<H", self._buf, 8 + length)
            if crc != crc16_modbus(body) or ver != VERSION:
                del self._buf[:2]
                continue
            frames.append(Frame(type_, seq, flags, bytes(self._buf[8:8 + length])))
            del self._buf[:total]
