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


def render_protocol(spec: dict) -> str:
    out = [
        "/* ARQUIVO GERADO por scripts/gen_isa_header.py a partir de",
        " * shared/specifications/protocol.json. NAO EDITE MANUALMENTE. */",
        "#ifndef LDP_PROTOCOL_H",
        "#define LDP_PROTOCOL_H",
        "",
        f"#define LDP_VERSION {spec['version']}u",
        f"#define LDP_SOF0 0x{spec['sof'][0]:02X}u",
        f"#define LDP_SOF1 0x{spec['sof'][1]:02X}u",
        f"#define LDP_MAX_PAYLOAD {spec['max_payload']}u",
        f"#define LDP_MAX_CHUNK {spec['max_chunk']}u",
        f"#define LDP_FRAME_TIMEOUT_MS {spec['frame_timeout_ms']}u",
        f"#define LDP_LOAD_SESSION_TIMEOUT_MS {spec['load_session_timeout_ms']}u",
        f"#define LDP_RESPONSE_FLAG 0x{spec['response_flag']:02X}u",
        f"#define LDP_ERROR_FLAG 0x{spec['error_flag']:02X}u",
        "",
    ]
    out += [f"#define LDP_CMD_{c['name']} {c['code']}u" for c in spec["commands"]]
    out.append("")
    out += [f"#define LDP_ERR_{e['name']} {e['code']}u" for e in spec["errors"]]
    out.append("")
    out += [f"#define PLC_STATE_{s['name']} {s['code']}u" for s in spec["states"]]
    out.append("")
    out += [f"#define PLC_FAULT_{f['name']} {f['code']}u" for f in spec["faults"]]
    out += ["", "#endif /* LDP_PROTOCOL_H */", ""]
    return "\n".join(out)


TARGETS = [
    (SPEC_PATH, HEADER_PATH, render),
    (ROOT / "shared" / "specifications" / "protocol.json",
     ROOT / "firmware" / "lib" / "plc_core" / "ldp_protocol.h", render_protocol),
]


def main() -> int:
    stale = 0
    for spec_path, header_path, renderer in TARGETS:
        text = renderer(json.loads(spec_path.read_text(encoding="utf-8")))
        if "--check" in sys.argv:
            current = header_path.read_text(encoding="utf-8") if header_path.exists() else ""
            if current != text:
                print(f"{header_path} desatualizado; rode scripts/gen_isa_header.py", file=sys.stderr)
                stale += 1
            continue
        header_path.parent.mkdir(parents=True, exist_ok=True)
        header_path.write_text(text, encoding="utf-8", newline="\n")
        print(f"gerado {header_path.relative_to(ROOT)}")
    if "--check" in sys.argv and not stale:
        print("headers gerados em dia")
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
