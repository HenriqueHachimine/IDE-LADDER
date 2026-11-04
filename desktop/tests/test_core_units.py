"""Testes unitarios do nucleo que nao dependem da VM C."""
from __future__ import annotations

import subprocess
import sys

import pytest

from conftest import ROOT
from ladderide.core import (AsmError, LadderVM, Program, assemble, build_image, decode, disassemble)
from ladderide.core.asm import format_operand, parse_operand
from ladderide.core.crc import crc16_modbus, crc32
from ladderide.core.isa import INT32_MAX, INT32_MIN, MAX_IMAGE_SIZE, Area, Op


def test_crc_check_values():
    assert crc32(b"123456789") == 0xCBF43926
    assert crc16_modbus(b"123456789") == 0x4B37


def test_isa_header_in_sync():
    proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "gen_isa_header.py"), "--check"],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("text,expected", [
    ("I0.0", (Area.I, 0)), ("I1.7", (Area.I, 15)), ("q0.3", (Area.Q, 3)), ("M31.7", (Area.M, 255)),
    ("S0.3", (Area.S, 3)), ("T4.DN", (Area.T_DN, 4)), ("C2.OV", (Area.C_OV, 2)),
    ("T31", (Area.TIMER, 31)), ("C0", (Area.COUNTER, 0)),
])
def test_operand_roundtrip(text, expected):
    assert parse_operand(text) == expected
    assert format_operand(*expected) == text.upper()


@pytest.mark.parametrize("bad", ["I0.8", "X0.0", "T0.OV", "C1.EN", "Q", "M0"])
def test_operand_invalid(bad):
    with pytest.raises(ValueError):
        parse_operand(bad)


def test_assemble_disassemble_roundtrip():
    src = """
    .inputs 8
    .outputs 8
    .markers 16
    .safe_outputs 0x0001
    .timer T0 TON 1500
    .timer T1 TOF 200
    .counter C0 DOWN 4
    SOR
    XIC I0.0   ; comentario
    BST
    XIO Q0.0
    NXB
    XIC M1.2
    NOT
    BND
    TON T0
    EOR
    SOR
    XIC T0.DN
    BST
    TOF T1
    NXB
    CTD C0
    NXB
    RES C0
    BND
    EOR
    """
    p = assemble(src)
    image = build_image(p)
    again = decode(build_image(assemble(disassemble(decode(image)))))
    assert again == decode(image)


def test_assembler_errors_report_line():
    with pytest.raises(AsmError) as info:
        assemble("SOR\nFOO I0.0\nEOR")
    assert info.value.line == 2
    with pytest.raises(AsmError):
        assemble(".timer T1 TON 10\nSOR\nEOR")  # T0 ausente


def test_largest_program_fits_limit():
    code = []
    for rung in range(256):
        code.append((Op.SOR, Area.NONE, rung))
        code += [(Op.XIC, Area.I, 0)] * 5
        code.append((Op.OTE, Area.Q, 0))
        code.append((Op.EOR, Area.NONE, 0))
    from ladderide.core.image import Instruction
    p = Program(code=[Instruction(*c) for c in code])
    image = build_image(p)
    assert len(image) <= MAX_IMAGE_SIZE


def test_counter_overflow_and_underflow_saturate():
    """Inatingivel por contagem real; forcamos o estado para verificar a regra."""
    p = assemble(".counter C0 UP 5\n.counter C1 DOWN 5\nSOR\nXIC I0.0\nBST\nCTU C0\nNXB\nCTD C1\nBND\nEOR")
    vm = LadderVM(decode(build_image(p)))
    vm.counters[0].acc = INT32_MAX
    vm.counters[1].acc = INT32_MIN
    vm.scan(1, 10)
    assert (vm.counters[0].acc, vm.counters[0].ov) == (INT32_MAX, True)
    assert (vm.counters[1].acc, vm.counters[1].un) == (INT32_MIN, True)


def test_step_mode_matches_full_scan():
    src = ".timer T0 TON 20\nSOR\nXIC I0.0\nTON T0\nEOR\nSOR\nXIC T0.DN\nOTE Q0.0\nEOR"
    prog = decode(build_image(assemble(src)))
    a, b = LadderVM(prog), LadderVM(prog)
    for inputs in [1, 1, 1, 1, 0, 1]:
        a.scan(inputs, 10)
        b.begin_scan(inputs, 10)
        visited = [b.pc]
        while b.step():
            visited.append(b.pc)
        b.end_scan()
        assert visited == list(range(len(prog.code)))
        assert a.dump_line() == b.dump_line()


def test_reset_restores_cold_start():
    p = assemble(".markers 8\n.counter C0 DOWN 3\nSOR\nXIC I0.0\nOTL M0.0\nCTD C0\nEOR")
    vm = LadderVM(decode(build_image(p)))
    fresh = vm.dump_line()
    vm.scan(1, 10)
    vm.scan(0, 10)
    assert vm.m[0] and vm.counters[0].acc == 2
    vm.reset()
    assert vm.dump_line() == fresh
    assert vm.counters[0] == vm.counters[0].__class__(acc=3)


def test_speed_text_parsing_and_format():
    import math
    from ladderide.ui.speed_control import MAX_SPEED, format_speed, parse_speed
    assert parse_speed("3") == 3.0 and parse_speed(" 2,5x ") == 2.5 and parse_speed("0.5 X") == 0.5
    assert parse_speed("Max") == math.inf and parse_speed("1x (tempo real)") == 1.0
    assert parse_speed("abc") is None and parse_speed("0") is None and parse_speed("-2") is None
    assert parse_speed("99999") == MAX_SPEED
    assert [format_speed(v) for v in (0.25, 1.0, 3.5, 12.5, 250.0, math.inf)] == \
        ["0,25x", "1x", "3,5x", "12,5x", "250x", "Máxima"]
