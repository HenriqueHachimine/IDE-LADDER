"""Teste diferencial: programas e imagens aleatorias nas VMs Python e C.

Semente fixa para reprodutibilidade. Para uma rodada mais longa:
    LADDER_FUZZ_ITER=2000 python -m pytest tests/test_fuzz_equivalence.py
"""
from __future__ import annotations

import os
import random
import struct

import pytest

from ladderide.core import (CounterDef, ImageValidationError, Instruction, LadderVM, Program,
                            TimerDef, build_image, decode)
from ladderide.core.crc import crc32
from ladderide.core import isa
from ladderide.core.isa import Area, CounterType, Op, TimerType

ITER = int(os.environ.get("LADDER_FUZZ_ITER", "150"))
DT_CHOICES = [0, 1, 5, 10, 10, 10, 37, 100, 999, 1000, 4294967295]
# constantes que exercitam limites: zero, sinais, saturacao, BCD valido/invalido, raizes
CONST_POOL = [0, 1, -1, 2, 3, 7, -7, 9, 10, 100, 255, 256, 1234, 0x9876, 0x1A, 99999999, 100000000,
              46340, 46341, 2147483647, -2147483648, -2147483647, 65535, -65536, 0x0F, -0x10]
COMPARE = [Op.EQU, Op.NEQ, Op.LES, Op.GRT, Op.LEQ, Op.GEQ, Op.LIM, Op.MEQ]
MATH = [Op.ADD, Op.SUB, Op.MUL, Op.DIV, Op.SQR, Op.NEG, Op.TOD, Op.FRD]


class ProgramGenerator:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def program(self) -> Program:
        r = self.rng
        p = Program(n_inputs=8, n_outputs=8, n_markers=r.choice([0, 8, 16, 32]))
        p.timers = [TimerDef(r.choice(list(TimerType)), r.choice([0, 10, 30, 100, 250]))
                    for _ in range(r.randint(0, 4))]
        p.counters = [CounterDef(r.choice(list(CounterType)), r.randint(0, 5))
                      for _ in range(r.randint(0, 4))]
        p.n_words = r.choice([0, 0, 2, 6])
        p.constants = r.sample(CONST_POOL, r.randint(0, 8)) if p.n_words else []
        self.p = p
        self.timer_free = list(range(len(p.timers)))
        self.counter_free = list(range(len(p.counters)))
        r.shuffle(self.timer_free)
        r.shuffle(self.counter_free)
        code: list[Instruction] = []
        for rung in range(r.randint(1, 8)):
            code.append(Instruction(Op.SOR, Area.NONE, rung))
            self.series(code, depth=0)
            outputs = [self.output() for _ in range(r.choice([1, 1, 2, 3]))]
            if len(outputs) == 1:
                code += outputs[0]
            else:
                code.append(Instruction(Op.BST))
                for k, out in enumerate(outputs):
                    if k:
                        code.append(Instruction(Op.NXB))
                    code += out
                code.append(Instruction(Op.BND))
            code.append(Instruction(Op.EOR))
        p.code = code
        return p

    def readable(self) -> tuple[int, int]:
        r, p = self.rng, self.p
        options = [(Area.I, 8), (Area.Q, 8), (Area.S, isa.NUM_SYSTEM_BITS)]
        if p.n_markers:
            options.append((Area.M, p.n_markers))
        if p.timers:
            options += [(a, len(p.timers)) for a in (Area.T_EN, Area.T_TT, Area.T_DN)]
        if p.counters:
            options += [(a, len(p.counters)) for a in (Area.C_DN, Area.C_OV, Area.C_UN)]
        area, size = r.choice(options)
        return area, r.randrange(size)

    def word_read(self) -> tuple[int, int]:
        r, p = self.rng, self.p
        options = [(Area.N, p.n_words), (Area.IW, 1), (Area.QW, 1)]
        if p.constants:
            options += [(Area.K, len(p.constants))] * 3
        if p.timers:
            options += [(Area.T_ACC, len(p.timers)), (Area.T_PRE, len(p.timers))]
        if p.counters:
            options += [(Area.C_ACC, len(p.counters)), (Area.C_PRE, len(p.counters))]
        area, size = r.choice(options)
        return area, r.randrange(size)

    def word_instr(self, op: Op) -> list[Instruction]:
        """Instrucao de palavra com os operandos adicionais em ARG."""
        refs = [self.word_read() for _ in range(1 + len(isa.ARG_CLASSES[op]))]
        if op in isa.MATH_OPS:                 # o ultimo e o destino: N ou QW
            refs[-1] = (Area.N, self.rng.randrange(self.p.n_words)) if self.rng.random() < 0.85 else (Area.QW, 0)
        return [Instruction(op, *refs[0])] + [Instruction(Op.ARG, *ref) for ref in refs[1:]]

    def series(self, code: list[Instruction], depth: int) -> None:
        r = self.rng
        for _ in range(r.randint(0, 3)):
            kind = r.random()
            if self.p.n_words and kind < 0.2:
                code += self.word_instr(r.choice(COMPARE))
            elif kind < 0.65 or depth >= 3:
                area, index = self.readable()
                code.append(Instruction(r.choice([Op.XIC, Op.XIO]), area, index))
            elif kind < 0.92:
                code.append(Instruction(Op.BST))
                for k in range(r.randint(1, 3)):
                    if k:
                        code.append(Instruction(Op.NXB))
                    self.series(code, depth + 1)
                code.append(Instruction(Op.BND))
            else:
                code.append(Instruction(Op.NOT))

    def output(self) -> list[Instruction]:
        r, p = self.rng, self.p
        if p.n_words and r.random() < 0.35:
            return self.word_instr(r.choice(MATH))
        return [self.single_output()]

    def single_output(self) -> Instruction:
        r, p = self.rng, self.p
        choice = r.random()
        if choice < 0.2 and self.timer_free:
            k = self.timer_free.pop()
            return Instruction({0: Op.TON, 1: Op.TOF, 2: Op.RTO}[p.timers[k].type], Area.TIMER, k)
        if choice < 0.4 and self.counter_free:
            k = self.counter_free.pop()
            return Instruction(Op.CTU if p.counters[k].type == CounterType.UP else Op.CTD, Area.COUNTER, k)
        if choice < 0.5 and (p.timers or p.counters):
            if p.timers and (not p.counters or r.random() < 0.5):
                return Instruction(Op.RES, Area.TIMER, r.randrange(len(p.timers)))
            return Instruction(Op.RES, Area.COUNTER, r.randrange(len(p.counters)))
        area = Area.M if p.n_markers and r.random() < 0.4 else Area.Q
        size = p.n_markers if area == Area.M else 8
        return Instruction(r.choice([Op.OTE, Op.OTE, Op.OTL, Op.OTU]), area, r.randrange(size))


def random_scans(rng: random.Random, n: int) -> list[tuple[int, int]]:
    inputs, scans = 0, []
    for _ in range(n):
        if rng.random() < 0.3:
            inputs ^= 1 << rng.randrange(8)
        scans.append((rng.choice(DT_CHOICES), inputs))
    return scans


def python_trace(image: bytes, scans: list[tuple[int, int]]) -> list[str]:
    vm = LadderVM(decode(image))
    lines = []
    for dt, inputs in scans:
        vm.scan(inputs, dt)
        lines.append(vm.dump_line())
    return lines


def test_fuzz_random_programs(c_vm):
    rng = random.Random(20261016)
    gen = ProgramGenerator(rng)
    for it in range(ITER):
        image = build_image(gen.program())
        scans = random_scans(rng, 80)
        py = python_trace(image, scans)
        c = c_vm.run(image, scans)
        assert c.error is None
        for n, (a, b) in enumerate(zip(py, c.lines, strict=True), start=1):
            assert a == b, f"iteração {it}, varredura {n}\n  py: {a}\n  c : {b}"


def test_fuzz_mutated_images(c_vm):
    """Imagens corrompidas: as duas implementacoes devem concordar no veredito."""
    rng = random.Random(4242)
    gen = ProgramGenerator(rng)
    accepted = 0
    for it in range(ITER * 2):
        data = bytearray(build_image(gen.program()))
        for _ in range(rng.randint(1, 3)):
            data[rng.randrange(len(data))] = rng.randrange(256)
        if rng.random() < 0.8:
            struct.pack_into("<I", data, len(data) - 4, crc32(bytes(data[:-4])))
        data = bytes(data)
        try:
            decode(data)
            py_err = None
        except ImageValidationError as exc:
            py_err = (exc.code.value, exc.index)
        scans = random_scans(rng, 20)
        c = c_vm.run(data, scans)
        assert c.error == py_err, f"iteração {it}: python={py_err} c={c.error} imagem={data.hex()}"
        if py_err is None:
            accepted += 1
            assert python_trace(data, scans) == c.lines, f"iteração {it}: traco divergente"
    assert accepted > 0, "nenhuma mutação valida exercitou a execução"


@pytest.mark.parametrize("n", [0, 1, 7, 100])
def test_crc_against_c(c_vm, n):
    data = bytes(random.Random(n).randrange(256) for _ in range(n))
    from ladderide.core.crc import crc16_modbus
    assert c_vm.crc(data) == (crc32(data), crc16_modbus(data))
