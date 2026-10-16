#!/usr/bin/env python3
"""Gera firmware/lib/ladder_vm/ladder_isa.h a partir de shared/specifications/isa.json.

Uso:
    python scripts/gen_isa_header.py          # regrava o header
    python scripts/gen_isa_header.py --check  # falha se o header estiver desatualizado
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "shared" / "specifications" / "isa.json"
HEADER_PATH = ROOT / "firmware" / "lib" / "ladder_vm" / "ladder_isa.h"

OPERAND_CLASSES = ["none", "bit_read", "bit_write", "timer", "counter", "timer_or_counter"]


def render(spec: dict) -> str:
    f, lim = spec["format"], spec["limits"]
    out = [
        "/* ARQUIVO GERADO por scripts/gen_isa_header.py a partir de",
        " * shared/specifications/isa.json. NAO EDITE MANUALMENTE. */",
        "#ifndef LADDER_ISA_H",
        "#define LADDER_ISA_H",
        "",
        f"#define LV_FMT_MAGIC \"{f['magic']}\"",
        f"#define LV_FMT_MAJOR {f['major']}u",
        f"#define LV_FMT_MINOR {f['minor']}u",
        f"#define LV_HEADER_SIZE {f['header_size']}u",
        f"#define LV_TIMER_ENTRY_SIZE {f['timer_entry_size']}u",
        f"#define LV_COUNTER_ENTRY_SIZE {f['counter_entry_size']}u",
        f"#define LV_INSTRUCTION_SIZE {f['instruction_size']}u",
        f"#define LV_CRC_SIZE {f['crc_size']}u",
        "",
    ]
    for key, value in lim.items():
        out.append(f"#define LV_{key.upper()} {value}u")
    out += [
        "#define LV_MAX_IMAGE_SIZE (LV_HEADER_SIZE + LV_MAX_TIMERS * LV_TIMER_ENTRY_SIZE + \\",
        "    LV_MAX_COUNTERS * LV_COUNTER_ENTRY_SIZE + LV_MAX_INSTRUCTIONS * LV_INSTRUCTION_SIZE + LV_CRC_SIZE)",
        "",
        "/* Areas de operando */",
    ]
    out += [f"#define LV_AREA_{a['name']} {a['code']}u" for a in spec["areas"]]
    out += ["", "/* Bits de sistema (area S) */"]
    out += [f"#define LV_SYS_{s['name']} {s['index']}u" for s in spec["system_bits"]]
    out += ["", "/* Opcodes */"]
    out += [f"#define LV_OP_{o['name']} {o['code']}u" for o in spec["opcodes"]]
    out += ["", "/* Tipos de temporizador e contador */"]
    out += [f"#define LV_TIMER_{t['name']} {t['code']}u" for t in spec["timer_types"]]
    out += [f"#define LV_COUNTER_{t['name']} {t['code']}u" for t in spec["counter_types"]]
    out += ["", "/* Codigos de erro de validacao de imagem */", "typedef enum {"]
    out += [f"    LV_ERR_{e['name']} = {e['code']}," for e in spec["image_errors"]]
    out += ["} lv_image_error_t;", "", "/* Classes de operando */", "typedef enum {"]
    out += [f"    LV_OPERAND_{c.upper()} = {k}," for k, c in enumerate(OPERAND_CLASSES)]
    out += ["    LV_OPERAND_INVALID = -1", "} lv_operand_class_t;", "",
            "static inline lv_operand_class_t lv_operand_class(unsigned opcode)", "{",
            "    switch (opcode) {"]
    for o in spec["opcodes"]:
        out.append(f"    case LV_OP_{o['name']}: return LV_OPERAND_{o['operand'].upper()};")
    out += ["    default: return LV_OPERAND_INVALID;", "    }", "}", "",
            "static inline const char *lv_opcode_name(unsigned opcode)", "{", "    switch (opcode) {"]
    for o in spec["opcodes"]:
        out.append(f"    case LV_OP_{o['name']}: return \"{o['name']}\";")
    out += ["    default: return \"?\";", "    }", "}", "", "#endif /* LADDER_ISA_H */", ""]
    return "\n".join(out)


def main() -> int:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    text = render(spec)
    if "--check" in sys.argv:
        current = HEADER_PATH.read_text(encoding="utf-8") if HEADER_PATH.exists() else ""
        if current != text:
            print(f"{HEADER_PATH} desatualizado; rode scripts/gen_isa_header.py", file=sys.stderr)
            return 1
        print("ladder_isa.h em dia")
        return 0
    HEADER_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEADER_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(f"gerado {HEADER_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
