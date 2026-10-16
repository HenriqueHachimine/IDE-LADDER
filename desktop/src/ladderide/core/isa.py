"""Conjunto de instrucoes (ISA) carregado de shared/specifications/isa.json.

O JSON e a fonte unica da verdade; o firmware usa um header C gerado a partir
do mesmo arquivo (scripts/gen_isa_header.py). Este modulo apenas expoe os
valores como enums e constantes Python.
"""
from __future__ import annotations

import json
import os
import sys
from enum import IntEnum
from pathlib import Path


def _find_isa_json() -> Path:
    override = os.environ.get("LADDERIDE_ISA_JSON")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):  # executavel PyInstaller: dados ao lado do pacote
        return Path(sys._MEIPASS) / "shared" / "specifications" / "isa.json"
    # desktop/src/ladderide/core/isa.py -> raiz do repositorio
    return Path(__file__).resolve().parents[4] / "shared" / "specifications" / "isa.json"


ISA_PATH = _find_isa_json()
with open(ISA_PATH, encoding="utf-8") as _f:
    SPEC = json.load(_f)

Op = IntEnum("Op", {o["name"]: o["code"] for o in SPEC["opcodes"]})
Area = IntEnum("Area", {a["name"]: a["code"] for a in SPEC["areas"]})
ImageError = IntEnum("ImageError", {e["name"]: e["code"] for e in SPEC["image_errors"]})
TimerType = IntEnum("TimerType", {t["name"]: t["code"] for t in SPEC["timer_types"]})
CounterType = IntEnum("CounterType", {t["name"]: t["code"] for t in SPEC["counter_types"]})

OPERAND_CLASS: dict[Op, str] = {Op[o["name"]]: o["operand"] for o in SPEC["opcodes"]}
TIMER_OPCODE: dict[TimerType, Op] = {TimerType[t["name"]]: Op[t["opcode"]] for t in SPEC["timer_types"]}
COUNTER_OPCODE: dict[CounterType, Op] = {CounterType[t["name"]]: Op[t["opcode"]] for t in SPEC["counter_types"]}
SYSTEM_BITS: dict[str, int] = {s["name"]: s["index"] for s in SPEC["system_bits"]}

FMT = SPEC["format"]
MAGIC: bytes = FMT["magic"].encode("ascii")
FORMAT_MAJOR: int = FMT["major"]
FORMAT_MINOR: int = FMT["minor"]
HEADER_SIZE: int = FMT["header_size"]
TIMER_ENTRY_SIZE: int = FMT["timer_entry_size"]
COUNTER_ENTRY_SIZE: int = FMT["counter_entry_size"]
INSTRUCTION_SIZE: int = FMT["instruction_size"]
CRC_SIZE: int = FMT["crc_size"]

LIM = SPEC["limits"]
MAX_INPUTS: int = LIM["max_inputs"]
MAX_OUTPUTS: int = LIM["max_outputs"]
MAX_MARKERS: int = LIM["max_markers"]
MAX_TIMERS: int = LIM["max_timers"]
MAX_COUNTERS: int = LIM["max_counters"]
MAX_RUNGS: int = LIM["max_rungs"]
MAX_INSTRUCTIONS: int = LIM["max_instructions"]
MAX_BRANCH_DEPTH: int = LIM["max_branch_depth"]
MAX_PRESET: int = LIM["max_preset"]
NUM_SYSTEM_BITS: int = LIM["system_bits"]
MAX_IMAGE_SIZE: int = (
    HEADER_SIZE
    + MAX_TIMERS * TIMER_ENTRY_SIZE
    + MAX_COUNTERS * COUNTER_ENTRY_SIZE
    + MAX_INSTRUCTIONS * INSTRUCTION_SIZE
    + CRC_SIZE
)

INT32_MIN = -(2**31)
INT32_MAX = 2**31 - 1
UINT32_MASK = 0xFFFFFFFF

BIT_READ_AREAS = frozenset(
    {Area.I, Area.Q, Area.M, Area.S, Area.T_EN, Area.T_TT, Area.T_DN, Area.C_DN, Area.C_OV, Area.C_UN}
)
BIT_WRITE_AREAS = frozenset({Area.Q, Area.M})
