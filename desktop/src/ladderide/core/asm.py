"""Listagem textual LIL (Ladder Intermediate Listing) <-> Program.

LIL e a forma legivel do formato binario LDRB: uma instrucao por linha, mais
diretivas de declaracao. E usada nos vetores de teste compartilhados, na
exportacao documentada e na depuracao. Sintaxe em docs/intermediate-format.md.

    .inputs 8
    .outputs 8
    .markers 16
    .timer T0 TON 1500
    .counter C0 UP 3
    .words 4
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
    SOR
    GRT C0.ACC 2          ; forma curta: GRT C0.ACC + ARG 2
    ADD N0 1 N0           ; ADD N0 / ARG 1 / ARG N0
    EOR

Constantes inteiras (123, -5, 0x1F, 0b101) viram entradas da tabela de
constantes da imagem; a listagem as mostra pelo valor.
"""
from __future__ import annotations

import re

from . import isa
from .image import CounterDef, Instruction, Program, TimerDef
from .isa import Area, CounterType, Op, TimerType


class AsmError(ValueError):
    def __init__(self, line: int, message: str):
        self.line = line
        super().__init__(f"linha {line}: {message}")


_BYTE_BIT = re.compile(r"^([IQMS])(\d+)\.([0-7])$")
_ELEM_BIT = re.compile(r"^([TC])(\d+)\.(EN|TT|DN|OV|UN)$")
_ELEM = re.compile(r"^([TC])(\d+)$")
_ELEM_WORD = re.compile(r"^([TC])(\d+)\.(ACC|PRE)$")
_WORD = re.compile(r"^N(\d+)$")
_IO_WORD = re.compile(r"^([IQ])W(\d+)$")
_ELEM_WORD_AREAS = {("T", "ACC"): Area.T_ACC, ("T", "PRE"): Area.T_PRE,
                    ("C", "ACC"): Area.C_ACC, ("C", "PRE"): Area.C_PRE}
_BIT_AREAS = {"I": Area.I, "Q": Area.Q, "M": Area.M, "S": Area.S}
_ELEM_BIT_AREAS = {
    ("T", "EN"): Area.T_EN, ("T", "TT"): Area.T_TT, ("T", "DN"): Area.T_DN,
    ("C", "DN"): Area.C_DN, ("C", "OV"): Area.C_OV, ("C", "UN"): Area.C_UN,
}
_NO_OPERAND = {Op.SOR, Op.EOR, Op.NOT, Op.BST, Op.NXB, Op.BND}


def parse_constant(text: str) -> int | None:
    """Constante inteira (123, -5, 0x1F, 0b101) como int32, ou None se nao for constante.

    Valores de 2^31 a 2^32-1 (mascaras em hexadecimal) viram o padrao de bits com sinal."""
    t = text.strip().replace("_", "")
    if not re.fullmatch(r"[+-]?(0[xX][0-9A-Fa-f]+|0[bB][01]+|\d+)", t):
        return None
    value = int(t, 0)
    if not isa.INT32_MIN <= value <= isa.UINT32_MASK:
        raise ValueError(f"constante fora de 32 bits: {text}")
    return value - (1 << 32) if value > isa.INT32_MAX else value


def parse_operand(text: str) -> tuple[int, int]:
    """Converte 'I0.3', 'T2.DN', 'C1', 'N4', 'T0.ACC', 'IW0' etc. em (area, index)."""
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
    if m := _ELEM_WORD.match(t):
        return _ELEM_WORD_AREAS[(m[1], m[3])], int(m[2])
    if m := _WORD.match(t):
        return Area.N, int(m[1])
    if m := _IO_WORD.match(t):
        return (Area.IW if m[1] == "I" else Area.QW), int(m[2])
    raise ValueError(f"operando invalido: {text!r}")


def format_operand(area: int, index: int, constants: list[int] | None = None) -> str:
    area = Area(area)
    if area in (Area.I, Area.Q, Area.M, Area.S):
        return f"{area.name}{index // 8}.{index % 8}"
    if area == Area.N:
        return f"N{index}"
    if area == Area.K:
        return str(constants[index]) if constants is not None and index < len(constants) else f"K{index}"
    if area in (Area.IW, Area.QW):
        return f"{area.name}{index}"
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

    def operand(text: str) -> tuple[int, int]:
        value = parse_constant(text)
        if value is None:
            return parse_operand(text)
        if value not in p.constants:
            p.constants.append(value)
        return Area.K, p.constants.index(value)

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
                n_ops = 1 + len(isa.ARG_CLASSES[op])
                args = [a for a in re.split(r"[\s,]+", line.split(None, 1)[1] if len(parts) > 1 else "") if a]
                if len(args) not in (1, n_ops):
                    raise ValueError(f"{op.name} exige {n_ops} operando(s)" if n_ops > 1
                                     else f"{op.name} exige exatamente um operando")
                for k, text in enumerate(args):          # forma curta: ADD N0 1 N1 = ADD + ARG + ARG
                    area, index = operand(text)
                    p.code.append(Instruction(op if k == 0 else Op.ARG, area, index))
        except ValueError as exc:
            raise AsmError(lineno, str(exc)) from None
    for kind, table, target in (("T", timers, p.timers), ("C", counters, p.counters)):
        if sorted(table) != list(range(len(table))):
            raise AsmError(0, f"declaracoes {kind} devem ser contiguas a partir de {kind}0")
        target.extend(table[k] for k in range(len(table)))
    return p


def _directive(p: Program, timers: dict, counters: dict, head: str, args: list[str]) -> None:
    if head in (".INPUTS", ".OUTPUTS", ".MARKERS", ".WORDS", ".SAFE_OUTPUTS", ".BUILD_ID"):
        if len(args) != 1:
            raise ValueError(f"{head} exige um valor")
        attr = {".INPUTS": "n_inputs", ".OUTPUTS": "n_outputs", ".MARKERS": "n_markers", ".WORDS": "n_words",
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
    lines = [f".inputs {p.n_inputs}", f".outputs {p.n_outputs}", f".markers {p.n_markers}", f".words {p.n_words}",
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
            lines.append(f"{op.name} {format_operand(ins.area, ins.index, p.constants)}")
    return "\n".join(lines) + "\n"
