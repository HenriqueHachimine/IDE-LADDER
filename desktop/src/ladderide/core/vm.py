"""Maquina virtual LADDER de referencia (simulador do Desktop).

Implementa a semantica normativa de docs/ladder-specification.md. A VM C do
firmware (firmware/lib/ladder_vm/ladder_vm.c) implementa a mesma especificacao;
as duas sao comparadas varredura a varredura pelos testes de equivalencia
(desktop/tests/test_equivalence.py), usando `dump_line()` como formato comum.

A VM nao conhece tempo real: cada varredura recebe `dt_ms`, o tempo decorrido
desde a varredura anterior. Assim a simulacao e deterministica e reproduzivel.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import isa
from .image import Program
from .isa import Area, CounterType, Op

UINT32_MASK = isa.UINT32_MASK


@dataclass
class TimerState:
    acc: int = 0
    en: bool = False
    tt: bool = False
    dn: bool = False

    @property
    def flags(self) -> int:
        return int(self.en) | int(self.tt) << 1 | int(self.dn) << 2


@dataclass
class CounterState:
    acc: int = 0
    dn: bool = False
    ov: bool = False
    un: bool = False
    prev: bool = False  # memoria de borda (estado do RLO na execucao anterior)

    @property
    def flags(self) -> int:
        return int(self.dn) | int(self.ov) << 1 | int(self.un) << 2 | int(self.prev) << 3


def _sat_add(acc: int, dt: int, pre: int) -> int:
    return pre if dt >= pre - acc else acc + dt


class LadderVM:
    def __init__(self, program: Program):
        self.program = program
        self.code = program.code
        self.reset()

    # ------------------------------------------------------------------ estado
    def reset(self) -> None:
        """Partida a frio (transicao STOP -> RUN)."""
        p = self.program
        self.i = [False] * p.n_inputs
        self.q = [False] * p.n_outputs
        self.m = [False] * p.n_markers
        self.timers = [TimerState() for _ in p.timers]
        self.counters = [CounterState() for _ in p.counters]
        for c, cdef in zip(self.counters, p.counters):
            self._counter_reset(c, cdef.type, cdef.preset)
        self.power = [False] * len(self.code)
        self.scan_count = 0
        self.first_scan = True
        self.sec_phase = 0
        self.pc = 0
        self.dt = 0
        self.rlo = False
        self.stack: list[list[bool]] = []  # [entry, acumulador OR]
        self.in_scan = False

    @staticmethod
    def _counter_reset(c: CounterState, ctype: int, preset: int) -> None:
        if ctype == CounterType.UP:
            c.acc = 0
            c.dn = c.acc >= preset
        else:
            c.acc = preset
            c.dn = c.acc <= 0
        c.ov = c.un = False

    # ---------------------------------------------------------------- leitura
    def system_bit(self, index: int) -> bool:
        if index == isa.SYSTEM_BITS["FIRST_SCAN"]:
            return self.first_scan
        if index == isa.SYSTEM_BITS["ALWAYS_ON"]:
            return True
        if index == isa.SYSTEM_BITS["CLOCK_1S"]:
            return self.sec_phase < 500
        return False

    def read_bit(self, area: int, index: int) -> bool:
        if area == Area.I:
            return self.i[index]
        if area == Area.Q:
            return self.q[index]
        if area == Area.M:
            return self.m[index]
        if area == Area.S:
            return self.system_bit(index)
        if area == Area.T_EN:
            return self.timers[index].en
        if area == Area.T_TT:
            return self.timers[index].tt
        if area == Area.T_DN:
            return self.timers[index].dn
        if area == Area.C_DN:
            return self.counters[index].dn
        if area == Area.C_OV:
            return self.counters[index].ov
        if area == Area.C_UN:
            return self.counters[index].un
        raise ValueError(f"area nao legivel: {area}")

    def _write_bit(self, area: int, index: int, value: bool) -> None:
        (self.q if area == Area.Q else self.m)[index] = value

    @property
    def outputs(self) -> int:
        return sum(1 << k for k, v in enumerate(self.q) if v)

    # -------------------------------------------------------------- execucao
    def begin_scan(self, inputs: int, dt_ms: int) -> None:
        """Fases 1-2 do ciclo: congela a imagem de entradas e a base de tempo."""
        dt = 0 if self.first_scan else dt_ms & UINT32_MASK
        self.dt = dt
        if not self.first_scan:
            self.sec_phase = (self.sec_phase + dt % 1000) % 1000
        self.i = [bool(inputs >> k & 1) for k in range(self.program.n_inputs)]
        self.pc = 0
        self.in_scan = True

    def step(self) -> bool:
        """Executa uma instrucao. Retorna False quando a varredura terminou."""
        if self.pc >= len(self.code):
            return False
        ins = self.code[self.pc]
        self._execute(ins.op, ins.area, ins.index)
        self.power[self.pc] = self.rlo
        self.pc += 1
        return self.pc < len(self.code)

    def end_scan(self) -> int:
        """Fases finais: contabiliza a varredura e devolve a imagem de saidas."""
        self.in_scan = False
        self.first_scan = False
        self.scan_count = (self.scan_count + 1) & UINT32_MASK
        return self.outputs

    def scan(self, inputs: int, dt_ms: int) -> int:
        self.begin_scan(inputs, dt_ms)
        while self.step():
            pass
        return self.end_scan()

    def _execute(self, op: int, area: int, index: int) -> None:
        if op == Op.SOR:
            self.rlo = True
            self.stack.clear()
        elif op == Op.EOR:
            pass
        elif op == Op.XIC:
            self.rlo = self.rlo and self.read_bit(area, index)
        elif op == Op.XIO:
            self.rlo = self.rlo and not self.read_bit(area, index)
        elif op == Op.NOT:
            self.rlo = not self.rlo
        elif op == Op.BST:
            self.stack.append([self.rlo, False])
        elif op == Op.NXB:
            top = self.stack[-1]
            top[1] = top[1] or self.rlo
            self.rlo = top[0]
        elif op == Op.BND:
            entry, acc = self.stack.pop()
            self.rlo = acc or self.rlo
        elif op == Op.OTE:
            self._write_bit(area, index, self.rlo)
        elif op == Op.OTL:
            if self.rlo:
                self._write_bit(area, index, True)
        elif op == Op.OTU:
            if self.rlo:
                self._write_bit(area, index, False)
        elif op in (Op.TON, Op.TOF, Op.RTO):
            self._timer(op, self.timers[index], self.program.timers[index].preset_ms)
        elif op in (Op.CTU, Op.CTD):
            self._counter(op, self.counters[index], self.program.counters[index].preset)
        elif op == Op.RES:
            if not self.rlo:
                pass
            elif area == Area.TIMER:
                t = self.timers[index]
                t.acc, t.en, t.tt, t.dn = 0, False, False, False
            else:
                cdef = self.program.counters[index]
                self._counter_reset(self.counters[index], cdef.type, cdef.preset)
        else:  # pragma: no cover - a validacao da imagem impede
            raise ValueError(f"opcode invalido: {op}")

    def _timer(self, op: int, t: TimerState, pre: int) -> None:
        rlo = self.rlo
        prev = t.en
        t.en = rlo
        if op == Op.TON:
            if rlo:
                if prev and not t.dn:
                    t.acc = _sat_add(t.acc, self.dt, pre)
                t.dn = t.acc >= pre
                t.tt = not t.dn
            else:
                t.acc, t.dn, t.tt = 0, False, False
        elif op == Op.TOF:
            if rlo:
                t.acc, t.dn, t.tt = 0, True, False
            elif t.dn:
                if not prev:
                    t.acc = _sat_add(t.acc, self.dt, pre)
                if t.acc >= pre:
                    t.dn, t.tt = False, False
                else:
                    t.tt = True
            else:
                t.tt = False
        else:  # RTO
            if rlo:
                if prev and not t.dn:
                    t.acc = _sat_add(t.acc, self.dt, pre)
                t.dn = t.acc >= pre
                t.tt = not t.dn
            else:
                t.tt = False

    def _counter(self, op: int, c: CounterState, pre: int) -> None:
        edge = self.rlo and not c.prev
        c.prev = self.rlo
        if op == Op.CTU:
            if edge:
                if c.acc == isa.INT32_MAX:
                    c.ov = True
                else:
                    c.acc += 1
            c.dn = c.acc >= pre
        else:
            if edge:
                if c.acc == isa.INT32_MIN:
                    c.un = True
                else:
                    c.acc -= 1
            c.dn = c.acc <= 0

    # ------------------------------------------------------------- diagnostico
    def dump_line(self) -> str:
        """Estado completo em texto canonico, identico ao do executor C de testes."""
        def bits_hex(bits: list[bool]) -> str:
            out = []
            for b in range(0, len(bits), 8):
                out.append(f"{sum(1 << k for k, v in enumerate(bits[b:b + 8]) if v):02x}")
            return "".join(out)

        t = ",".join(f"{s.acc}/{s.flags:x}" for s in self.timers)
        c = ",".join(f"{s.acc}/{s.flags:x}" for s in self.counters)
        return (f"S={self.scan_count} Q={self.outputs:04x} M={bits_hex(self.m)} "
                f"T={t} C={c} P={bits_hex(self.power)}")
