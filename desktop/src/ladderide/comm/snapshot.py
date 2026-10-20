"""Decodificacao das respostas INFO, STATUS e do instantaneo READ_VARS/TEST_SCAN."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .protocol import DevState, Fault


@dataclass
class DeviceInfo:
    protocol: int
    fmt_major: int
    fmt_minor: int
    n_inputs: int
    n_outputs: int
    max_image: int
    max_chunk: int
    scan_period_ms: int
    firmware: str
    hardware: str

    @classmethod
    def parse(cls, b: bytes) -> "DeviceInfo":
        proto, fmaj, fmin, ni, no, max_img, max_chunk, period = struct.unpack_from("<BBBBBHHH", b, 0)
        o = 11
        fw_len = b[o]
        fw = b[o + 1:o + 1 + fw_len].decode("ascii", "replace")
        o += 1 + fw_len
        hw_len = b[o]
        hw = b[o + 1:o + 1 + hw_len].decode("ascii", "replace")
        return cls(proto, fmaj, fmin, ni, no, max_img, max_chunk, period, fw, hw)


@dataclass
class DeviceStatus:
    state: DevState
    fault: Fault
    has_program: bool
    test_mode: bool
    build_id: int
    program_crc: int
    scan_count: int
    last_exec_us: int
    max_exec_us: int
    overruns: int
    uptime_ms: int
    scan_period_ms: int
    max_interval_us: int

    @classmethod
    def parse(cls, b: bytes) -> "DeviceStatus":
        (state, fault, has, test, build, crc, scans, last, mx, over, up, period,
         max_int) = struct.unpack_from("<BBBBIIIIIIIHI", b, 0)
        return cls(DevState(state), Fault(fault), bool(has), bool(test), build, crc, scans, last, mx, over,
                   up, period, max_int)


@dataclass
class TimerSnap:
    acc: int
    en: bool
    tt: bool
    dn: bool


@dataclass
class CounterSnap:
    acc: int
    dn: bool
    ov: bool
    un: bool
    prev: bool


@dataclass
class Snapshot:
    state: DevState
    fault: Fault
    scan_count: int
    inputs: int
    q_logical: int
    q_commanded: int
    build_id: int
    program_crc: int
    test_mode: bool
    n_markers: int
    markers: list[bool] = field(default_factory=list)
    timers: list[TimerSnap] = field(default_factory=list)
    counters: list[CounterSnap] = field(default_factory=list)
    power: list[bool] = field(default_factory=list)
    words: list[int] = field(default_factory=list)       # registradores N
    math_flags: int = 0                                  # bit0 S0.4 estouro, bit1 S0.5 zero, bit2 S0.6 negativo

    @classmethod
    def parse(cls, b: bytes) -> "Snapshot":
        (state, fault, scans, inputs, q, qc, build, crc, test, _res, nm) = struct.unpack_from("<BBIHHHIIBBH", b, 0)
        o = 24
        mbytes = b[o:o + (nm + 7) // 8]
        o += (nm + 7) // 8
        markers = [bool(mbytes[k // 8] >> (k % 8) & 1) for k in range(nm)]
        nt = b[o]
        o += 1
        timers = []
        for _ in range(nt):
            acc, flags = struct.unpack_from("<IB", b, o)
            o += 5
            timers.append(TimerSnap(acc, bool(flags & 1), bool(flags & 2), bool(flags & 4)))
        nc = b[o]
        o += 1
        counters = []
        for _ in range(nc):
            acc, flags = struct.unpack_from("<iB", b, o)
            o += 5
            counters.append(CounterSnap(acc, bool(flags & 1), bool(flags & 2), bool(flags & 4), bool(flags & 8)))
        (ni,) = struct.unpack_from("<H", b, o)
        o += 2
        pbytes = b[o:o + (ni + 7) // 8]
        power = [bool(pbytes[k // 8] >> (k % 8) & 1) for k in range(ni)]
        o += (ni + 7) // 8
        words, flags = [], 0
        if o < len(b):                                   # firmware com LDRB 2 acrescenta N e os bits da matematica
            nw = b[o]
            words = list(struct.unpack_from(f"<{nw}i", b, o + 1))
            flags = b[o + 1 + 4 * nw]
        return cls(DevState(state), Fault(fault), scans, inputs, q, qc, build, crc, bool(test), nm,
                   markers, timers, counters, power, words, flags)

    def dump_line(self) -> str:
        """Mesmo formato de LadderVM.dump_line() (comparacao de equivalencia)."""
        def bits_hex(bits: list[bool]) -> str:
            return "".join(f"{sum(1 << k for k, v in enumerate(bits[b:b + 8]) if v):02x}"
                           for b in range(0, len(bits), 8))
        t = ",".join(f"{s.acc}/{int(s.en) | int(s.tt) << 1 | int(s.dn) << 2:x}" for s in self.timers)
        c = ",".join(f"{s.acc}/{int(s.dn) | int(s.ov) << 1 | int(s.un) << 2 | int(s.prev) << 3:x}"
                     for s in self.counters)
        n = ",".join(str(v) for v in self.words)
        return (f"S={self.scan_count} Q={self.q_logical:04x} M={bits_hex(self.markers)} "
                f"T={t} C={c} N={n} F={self.math_flags:x} P={bits_hex(self.power)}")
