"""Codificacao, decodificacao e validacao de imagens de programa LDRB v2.

A ordem das verificacoes em `decode` e normativa (docs/intermediate-format.md,
secao "Validacao") e e reproduzida passo a passo em firmware/lib/ladder_vm/lv_image.c,
para que o Desktop e o ESP32 rejeitem uma imagem com o mesmo codigo de erro.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import isa
from .crc import crc32
from .isa import Area, CounterType, ImageError, Op, TimerType

_HEADER = struct.Struct("<4sBBHIBBHBBHHHIIHH")
_ENTRY = struct.Struct("<B3sI")
_INSTR = struct.Struct("<BBH")
_CONST = struct.Struct("<i")
assert _HEADER.size == isa.HEADER_SIZE
assert _ENTRY.size == isa.TIMER_ENTRY_SIZE == isa.COUNTER_ENTRY_SIZE
assert _INSTR.size == isa.INSTRUCTION_SIZE
assert _CONST.size == isa.CONSTANT_ENTRY_SIZE


@dataclass(frozen=True)
class Instruction:
    op: int
    area: int = Area.NONE
    index: int = 0


@dataclass(frozen=True)
class TimerDef:
    type: int
    preset_ms: int


@dataclass(frozen=True)
class CounterDef:
    type: int
    preset: int


@dataclass
class Program:
    n_inputs: int = 8
    n_outputs: int = 8
    n_markers: int = 0
    n_words: int = 0
    timers: list[TimerDef] = field(default_factory=list)
    counters: list[CounterDef] = field(default_factory=list)
    constants: list[int] = field(default_factory=list)   # tabela de constantes (inteiros de 32 bits com sinal)
    code: list[Instruction] = field(default_factory=list)
    safe_outputs: int = 0
    build_id: int = 0

    @property
    def n_rungs(self) -> int:
        return sum(1 for ins in self.code if ins.op == Op.SOR)


class ImageValidationError(Exception):
    def __init__(self, code: ImageError, index: int = -1, detail: str = ""):
        self.code = ImageError(code)
        self.index = index
        self.detail = detail
        where = f" (instrucao {index})" if index >= 0 else ""
        super().__init__(f"{self.code.name}{where}: {detail}" if detail else f"{self.code.name}{where}")


def encode(program: Program, *, n_rungs: int | None = None, flags: int = 0) -> bytes:
    """Serializa sem validar (os testes usam isso para montar imagens invalidas)."""
    body = bytearray()
    for t in program.timers:
        body += _ENTRY.pack(t.type, b"\0\0\0", t.preset_ms)
    for c in program.counters:
        body += _ENTRY.pack(c.type, b"\0\0\0", c.preset)
    for value in program.constants:
        body += _CONST.pack(value)
    for ins in program.code:
        body += _INSTR.pack(ins.op, ins.area, ins.index)
    total = isa.HEADER_SIZE + len(body) + isa.CRC_SIZE
    header = _HEADER.pack(
        isa.MAGIC, isa.FORMAT_MAJOR, isa.FORMAT_MINOR, isa.HEADER_SIZE, total,
        program.n_inputs, program.n_outputs, program.n_markers,
        len(program.timers), len(program.counters),
        program.n_rungs if n_rungs is None else n_rungs,
        len(program.code), program.safe_outputs, program.build_id, flags,
        program.n_words, len(program.constants),
    )
    data = header + bytes(body)
    return data + struct.pack("<I", crc32(data))


def build_image(program: Program) -> bytes:
    """Serializa e garante que o resultado passa pela mesma validacao do firmware."""
    data = encode(program)
    decode(data)
    return data


def area_size(area: int, p: Program) -> int:
    return {
        Area.I: p.n_inputs, Area.Q: p.n_outputs, Area.M: p.n_markers, Area.S: isa.NUM_SYSTEM_BITS,
        Area.T_EN: len(p.timers), Area.T_TT: len(p.timers), Area.T_DN: len(p.timers),
        Area.C_DN: len(p.counters), Area.C_OV: len(p.counters), Area.C_UN: len(p.counters),
        Area.TIMER: len(p.timers), Area.COUNTER: len(p.counters),
        Area.N: p.n_words, Area.K: len(p.constants),
        Area.T_ACC: len(p.timers), Area.T_PRE: len(p.timers),
        Area.C_ACC: len(p.counters), Area.C_PRE: len(p.counters),
        Area.IW: 1, Area.QW: 1,
    }.get(area, 0)


def _operand_ok(cls: str, op: Op, area: int, index: int, p: Program) -> bool:
    if cls == "none":
        return area == Area.NONE and (index == 0 or op == Op.SOR)
    if cls == "bit_read":
        allowed = isa.BIT_READ_AREAS
    elif cls == "bit_write":
        allowed = isa.BIT_WRITE_AREAS
    elif cls == "word_read":
        allowed = isa.WORD_READ_AREAS
    elif cls == "word_write":
        allowed = isa.WORD_WRITE_AREAS
    elif cls == "timer":
        allowed = {Area.TIMER}
    elif cls == "counter":
        allowed = {Area.COUNTER}
    else:  # timer_or_counter
        allowed = {Area.TIMER, Area.COUNTER}
    return area in allowed and index < area_size(area, p)


def decode(data: bytes, max_inputs: int = isa.MAX_INPUTS) -> Program:
    """Valida e decodifica uma imagem. Lanca ImageValidationError no primeiro erro."""
    E = ImageError
    n = len(data)
    if n < isa.HEADER_SIZE:
        raise ImageValidationError(E.TOO_SHORT)
    (magic, major, minor, header_size, total_size, n_in, n_out, n_mark, n_tim, n_cnt,
     n_rungs, n_instr, safe_out, build_id, flags, n_words, n_const) = _HEADER.unpack_from(data, 0)
    if magic != isa.MAGIC:
        raise ImageValidationError(E.BAD_MAGIC)
    if major != isa.FORMAT_MAJOR or minor > isa.FORMAT_MINOR:
        raise ImageValidationError(E.UNSUPPORTED_VERSION, detail=f"{major}.{minor}")
    if header_size != isa.HEADER_SIZE:
        raise ImageValidationError(E.BAD_HEADER_SIZE)
    if total_size != n:
        raise ImageValidationError(E.SIZE_MISMATCH, detail=f"total_size={total_size}, buffer={n}")
    if n > isa.MAX_IMAGE_SIZE:
        raise ImageValidationError(E.LIMIT_EXCEEDED, detail="imagem maior que o maximo")
    (stored_crc,) = struct.unpack_from("<I", data, n - isa.CRC_SIZE)
    if crc32(data[: n - isa.CRC_SIZE]) != stored_crc:
        raise ImageValidationError(E.BAD_CRC)
    if flags != 0:
        raise ImageValidationError(E.RESERVED_NONZERO, detail="flags")
    if (n_in > max_inputs or n_out > isa.MAX_OUTPUTS or n_mark > isa.MAX_MARKERS
            or n_tim > isa.MAX_TIMERS or n_cnt > isa.MAX_COUNTERS
            or n_rungs > isa.MAX_RUNGS or n_instr > isa.MAX_INSTRUCTIONS
            or n_words > isa.MAX_WORDS or n_const > isa.MAX_CONSTANTS):
        raise ImageValidationError(E.LIMIT_EXCEEDED)
    expected = (isa.HEADER_SIZE + n_tim * isa.TIMER_ENTRY_SIZE + n_cnt * isa.COUNTER_ENTRY_SIZE
                + n_const * isa.CONSTANT_ENTRY_SIZE + n_instr * isa.INSTRUCTION_SIZE + isa.CRC_SIZE)
    if expected != total_size:
        raise ImageValidationError(E.SIZE_MISMATCH, detail="contagens nao conferem com o tamanho")
    if safe_out >> n_out:
        raise ImageValidationError(E.RESERVED_NONZERO, detail="safe_outputs fora de n_outputs")

    p = Program(n_inputs=n_in, n_outputs=n_out, n_markers=n_mark, n_words=n_words, safe_outputs=safe_out,
                build_id=build_id)
    off = isa.HEADER_SIZE
    for i in range(n_tim):
        ttype, reserved, preset = _ENTRY.unpack_from(data, off)
        off += _ENTRY.size
        if ttype not in TimerType._value2member_map_ or reserved != b"\0\0\0" or preset > isa.MAX_PRESET:
            raise ImageValidationError(E.BAD_TIMER_TABLE, detail=f"T{i}")
        p.timers.append(TimerDef(ttype, preset))
    for i in range(n_cnt):
        ctype, reserved, preset = _ENTRY.unpack_from(data, off)
        off += _ENTRY.size
        if ctype not in CounterType._value2member_map_ or reserved != b"\0\0\0" or preset > isa.MAX_PRESET:
            raise ImageValidationError(E.BAD_COUNTER_TABLE, detail=f"C{i}")
        p.counters.append(CounterDef(ctype, preset))
    for _ in range(n_const):
        p.constants.append(_CONST.unpack_from(data, off)[0])
        off += _CONST.size

    in_rung = False
    rung = 0
    depth = 0
    timer_driven = [False] * n_tim
    counter_driven = [False] * n_cnt
    pending: list[str] = []          # classes dos ARG que ainda faltam para a instrucao anterior
    for i in range(n_instr):
        opcode, area, index = _INSTR.unpack_from(data, off)
        off += _INSTR.size
        if opcode not in Op._value2member_map_:
            raise ImageValidationError(E.BAD_OPCODE, i)
        op = Op(opcode)
        if in_rung == (op == Op.SOR):
            raise ImageValidationError(E.BAD_STRUCTURE, i, "SOR/EOR fora de ordem")
        if bool(pending) != (op == Op.ARG):
            raise ImageValidationError(E.BAD_STRUCTURE, i, "ARG fora de lugar ou operando faltando")
        cls = pending.pop(0) if op == Op.ARG else isa.OPERAND_CLASS[op]
        if not _operand_ok(cls, op, area, index, p):
            raise ImageValidationError(E.BAD_OPERAND, i)
        pending.extend(isa.ARG_CLASSES[op])
        if op == Op.SOR:
            if index != rung or rung >= n_rungs:
                raise ImageValidationError(E.BAD_STRUCTURE, i, "numeracao de rede")
            in_rung, depth = True, 0
        elif op == Op.EOR:
            if depth != 0:
                raise ImageValidationError(E.BRANCH_ERROR, i)
            in_rung = False
            rung += 1
        elif op == Op.BST:
            if depth >= isa.MAX_BRANCH_DEPTH:
                raise ImageValidationError(E.BRANCH_ERROR, i)
            depth += 1
        elif op in (Op.NXB, Op.BND):
            if depth == 0:
                raise ImageValidationError(E.BRANCH_ERROR, i)
            if op == Op.BND:
                depth -= 1
        elif op in (Op.TON, Op.TOF, Op.RTO):
            if isa.TIMER_OPCODE[TimerType(p.timers[index].type)] != op:
                raise ImageValidationError(E.TYPE_MISMATCH, i)
            if timer_driven[index]:
                raise ImageValidationError(E.DUPLICATE_DRIVER, i)
            timer_driven[index] = True
        elif op in (Op.CTU, Op.CTD):
            if isa.COUNTER_OPCODE[CounterType(p.counters[index].type)] != op:
                raise ImageValidationError(E.TYPE_MISMATCH, i)
            if counter_driven[index]:
                raise ImageValidationError(E.DUPLICATE_DRIVER, i)
            counter_driven[index] = True
        p.code.append(Instruction(op, area, index))
    if in_rung or rung != n_rungs:
        raise ImageValidationError(E.BAD_STRUCTURE, n_instr, "programa termina fora de rede")
    return p
