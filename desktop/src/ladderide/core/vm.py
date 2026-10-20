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


def _to_i32(value: int) -> int:
    """Padrao de 32 bits interpretado como inteiro com sinal."""
    value &= UINT32_MASK
    return value - (1 << 32) if value & 0x80000000 else value


def isqrt_round(x: int) -> int:
    """Raiz quadrada inteira de x >= 0, arredondada para o inteiro mais proximo.

    Algoritmo bit a bit, o mesmo do firmware (sem ponto flutuante)."""
    r = 0
    bit = 1 << 32
    while bit > x:
        bit >>= 2
    while bit:
        if x >= r + bit:
            x -= r + bit
            r = (r >> 1) + bit
        else:
            r >>= 1
        bit >>= 2
    return r + 1 if x > r else r          # x agora e o resto n - r*r


def compare(op: int, a: int, b: int, c: int = 0) -> bool:
    """Resultado das instrucoes de comparacao (docs/ladder-specification.md, secao 9)."""
    if op == Op.EQU:
        return a == b
    if op == Op.NEQ:
        return a != b
    if op == Op.LES:
        return a < b
    if op == Op.GRT:
        return a > b
    if op == Op.LEQ:
        return a <= b
    if op == Op.GEQ:
        return a >= b
    if op == Op.LIM:                      # a = limite inferior, b = teste, c = limite superior
        return a <= b <= c if a <= c else (b >= a or b <= c)
    if op == Op.MEQ:                      # a = origem, b = mascara, c = comparar
        return (a & b & UINT32_MASK) == (c & b & UINT32_MASK)
    raise ValueError(f"nao e comparacao: {op}")


def math_result(op: int, a: int, b: int = 0) -> tuple[int | None, bool]:
    """(resultado, estouro) das instrucoes matematicas; resultado None = destino inalterado."""
    if op == Op.ADD:
        r = a + b
    elif op == Op.SUB:
        r = a - b
    elif op == Op.MUL:
        r = a * b
    elif op == Op.NEG:
        r = -a
    elif op == Op.DIV:
        if b == 0:
            return (isa.INT32_MAX if a >= 0 else isa.INT32_MIN), True
        q = abs(a) // abs(b)              # truncado em direcao a zero, como em C
        r = -q if (a < 0) != (b < 0) else q
    elif op == Op.SQR:
        return isqrt_round(abs(a)), a < 0
    elif op == Op.TOD:
        if not 0 <= a <= 99999999:
            return None, True
        bcd = 0
        for shift, digit in enumerate(reversed(str(a))):
            bcd |= int(digit) << (4 * shift)
        return _to_i32(bcd), False
    elif op == Op.FRD:
        raw = a & UINT32_MASK
        digits = [(raw >> (4 * k)) & 0xF for k in range(8)]
        if any(d > 9 for d in digits):
            return None, True
        return sum(d * 10 ** k for k, d in enumerate(digits)), False
    else:
        raise ValueError(f"nao e instrucao matematica: {op}")
    if r > isa.INT32_MAX:
        return isa.INT32_MAX, True
    if r < isa.INT32_MIN:
        return isa.INT32_MIN, True
    return r, False


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
        self.n = [0] * p.n_words
        self.math_ov = self.math_zero = self.math_sign = False
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
        if index == isa.SYSTEM_BITS["MATH_OV"]:
            return self.math_ov
        if index == isa.SYSTEM_BITS["MATH_ZERO"]:
            return self.math_zero
        if index == isa.SYSTEM_BITS["MATH_SIGN"]:
            return self.math_sign
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

    def read_word(self, area: int, index: int) -> int:
        if area == Area.N:
            return self.n[index]
        if area == Area.K:
            return self.program.constants[index]
        if area == Area.T_ACC:
            return self.timers[index].acc
        if area == Area.T_PRE:
            return self.program.timers[index].preset_ms
        if area == Area.C_ACC:
            return self.counters[index].acc
        if area == Area.C_PRE:
            return self.program.counters[index].preset
        if area == Area.IW:
            return sum(1 << k for k, v in enumerate(self.i) if v)
        if area == Area.QW:
            return self.outputs
        raise ValueError(f"area nao e palavra: {area}")

    def _write_word(self, area: int, index: int, value: int) -> bool:
        """Grava o resultado; devolve True se o valor nao coube no destino (QW)."""
        if area == Area.N:
            self.n[index] = value
            return False
        n_out = self.program.n_outputs           # QW: bit k -> Qk
        for k in range(n_out):
            self.q[k] = bool(value >> k & 1)
        return not 0 <= value < (1 << n_out)

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
        if ins.op in isa.COMPARE_OPS or ins.op in isa.MATH_OPS:
            self._execute_word(ins)
        else:
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
        elif op in (Op.EOR, Op.ARG):
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

    def _execute_word(self, ins) -> None:
        """Comparacao ou matematica; os demais operandos estao nas instrucoes ARG seguintes."""
        n_args = len(isa.ARG_CLASSES[ins.op])
        refs = [(ins.area, ins.index)] + [(a.area, a.index) for a in self.code[self.pc + 1:self.pc + 1 + n_args]]
        if ins.op in isa.COMPARE_OPS:
            values = [self.read_word(*r) for r in refs]
            self.rlo = self.rlo and compare(ins.op, *values)
            return
        if not self.rlo:
            return
        result, overflow = math_result(ins.op, *[self.read_word(*r) for r in refs[:-1]])
        if result is None:
            self.math_ov, self.math_zero, self.math_sign = True, False, False
            return
        overflow |= self._write_word(*refs[-1], result)
        self.math_ov, self.math_zero, self.math_sign = overflow, result == 0, result < 0

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
        n = ",".join(str(v) for v in self.n)
        f = int(self.math_ov) | int(self.math_zero) << 1 | int(self.math_sign) << 2
        return (f"S={self.scan_count} Q={self.outputs:04x} M={bits_hex(self.m)} "
                f"T={t} C={c} N={n} F={f:x} P={bits_hex(self.power)}")
