"""Listagem textual LIL (Ladder Intermediate Listing) <-> Program.

LIL e a forma legivel do formato binario LDRB: uma instrucao por linha, mais
diretivas de declaracao. E usada nos vetores de teste compartilhados, na
exportacao documentada e na depuracao. Sintaxe em docs/intermediate-format.md.

    .inputs 8
    .outputs 8
    .markers 16
    .timer T0 TON 1500
    .counter C0 UP 3
    SOR
    XIC I0.0
    BST
    XIC Q0.0
    NXB
    XIC M0.1
    BND
    XIO I0.1
    OTE Q0.0
    EOR
"""
from __future__ import annotations

import re

from .image import CounterDef, Instruction, Program, TimerDef
from .isa import Area, CounterType, Op, TimerType


class AsmError(ValueError):
    def __init__(self, line: int, message: str):
        self.line = line
        super().__init__(f"linha {line}: {message}")


_BYTE_BIT = re.compile(r"^([IQMS])(\d+)\.([0-7])$")
_ELEM_BIT = re.compile(r"^([TC])(\d+)\.(EN|TT|DN|OV|UN)$")
_ELEM = re.compile(r"^([TC])(\d+)$")
_BIT_AREAS = {"I": Area.I, "Q": Area.Q, "M": Area.M, "S": Area.S}
_ELEM_BIT_AREAS = {
    ("T", "EN"): Area.T_EN, ("T", "TT"): Area.T_TT, ("T", "DN"): Area.T_DN,
    ("C", "DN"): Area.C_DN, ("C", "OV"): Area.C_OV, ("C", "UN"): Area.C_UN,
}
_NO_OPERAND = {Op.SOR, Op.EOR, Op.NOT, Op.BST, Op.NXB, Op.BND}


def parse_operand(text: str) -> tuple[int, int]:
    """Converte 'I0.3', 'T2.DN', 'C1' etc. em (area, index)."""
    t = text.strip().upper()
    if m := _BYTE_BIT.match(t):
        return _BIT_AREAS[m[1]], int(m[2]) * 8 + int(m[3])
    if m := _ELEM_BIT.match(t):
        area = _ELEM_BIT_AREAS.get((m[1], m[3]))
        if area is None:
            raise ValueError(f"campo {m[3]} nao existe em {m[1]}")
        return area, int(m[2])
    if m := _ELEM.match(t):
        return (Area.TIMER if m[1] == "T" else Area.COUNTER), int(m[2])
    raise ValueError(f"operando invalido: {text!r}")


def format_operand(area: int, index: int) -> str:
    area = Area(area)
    if area in (Area.I, Area.Q, Area.M, Area.S):
        return f"{area.name}{index // 8}.{index % 8}"
    if area == Area.TIMER:
        return f"T{index}"
    if area == Area.COUNTER:
        return f"C{index}"
    prefix, field = area.name.split("_")
    return f"{prefix}{index}.{field}"


def _parse_int(text: str) -> int:
    return int(text, 0)


def assemble(source: str) -> Program:
    p = Program(n_markers=0)
    timers: dict[int, TimerDef] = {}
    counters: dict[int, CounterDef] = {}
    for lineno, raw in enumerate(source.splitlines(), start=1):
        line = re.split(r"[;#]", raw, maxsplit=1)[0].strip()
        if not line:
            continue
        parts = line.split()
        head = parts[0].upper()
        try:
            if head.startswith("."):
                _directive(p, timers, counters, head, parts[1:])
                continue
            try:
                op = Op[head]
            except KeyError:
                raise ValueError(f"instrucao desconhecida: {parts[0]}") from None
            if op in _NO_OPERAND:
                if len(parts) != 1:
                    raise ValueError(f"{op.name} nao recebe operando")
                index = p.n_rungs if op == Op.SOR else 0
                p.code.append(Instruction(op, Area.NONE, index))
            else:
                if len(parts) != 2:
                    raise ValueError(f"{op.name} exige exatamente um operando")
                area, index = parse_operand(parts[1])
                p.code.append(Instruction(op, area, index))
        except ValueError as exc:
            raise AsmError(lineno, str(exc)) from None
    for kind, table, target in (("T", timers, p.timers), ("C", counters, p.counters)):
        if sorted(table) != list(range(len(table))):
            raise AsmError(0, f"declaracoes {kind} devem ser contiguas a partir de {kind}0")
        target.extend(table[k] for k in range(len(table)))
    return p


def _directive(p: Program, timers: dict, counters: dict, head: str, args: list[str]) -> None:
    if head in (".INPUTS", ".OUTPUTS", ".MARKERS", ".SAFE_OUTPUTS", ".BUILD_ID"):
        if len(args) != 1:
            raise ValueError(f"{head} exige um valor")
        attr = {".INPUTS": "n_inputs", ".OUTPUTS": "n_outputs", ".MARKERS": "n_markers",
                ".SAFE_OUTPUTS": "safe_outputs", ".BUILD_ID": "build_id"}[head]
        setattr(p, attr, _parse_int(args[0]))
    elif head in (".TIMER", ".COUNTER"):
        if len(args) != 3:
            raise ValueError(f"{head} <nome> <tipo> <preset>")
        area, index = parse_operand(args[0])
        if head == ".TIMER":
            if area != Area.TIMER:
                raise ValueError("nome de temporizador deve ser Tn")
            timers[index] = TimerDef(TimerType[args[1].upper()], _parse_int(args[2]))
        else:
            if area != Area.COUNTER:
                raise ValueError("nome de contador deve ser Cn")
            counters[index] = CounterDef(CounterType[args[1].upper()], _parse_int(args[2]))
    else:
        raise ValueError(f"diretiva desconhecida: {head}")


def disassemble(p: Program) -> str:
    lines = [f".inputs {p.n_inputs}", f".outputs {p.n_outputs}", f".markers {p.n_markers}",
             f".safe_outputs 0x{p.safe_outputs:04x}", f".build_id 0x{p.build_id:08x}"]
    lines += [f".timer T{k} {TimerType(t.type).name} {t.preset_ms}" for k, t in enumerate(p.timers)]
    lines += [f".counter C{k} {CounterType(c.type).name} {c.preset}" for k, c in enumerate(p.counters)]
    for ins in p.code:
        op = Op(ins.op)
        if op == Op.SOR:
            lines.append(f"SOR ; rede {ins.index}")
        elif op in _NO_OPERAND:
            lines.append(op.name)
        else:
            lines.append(f"{op.name} {format_operand(ins.area, ins.index)}")
    return "\n".join(lines) + "\n"
