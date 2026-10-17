"""Conversao do diagrama LADDER em blocos de instrucao (lista de instrucoes).

Cada rede vira um bloco com as instrucoes que o compilador gerou para ela,
na ordem em que o interpretador do ESP32 as executa. As instrucoes sao as
mesmas da imagem LDRB; o bloco apenas acrescenta simbolos, indentacao dos
ramos paralelos e uma explicacao de cada linha.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..compiler.compiler import CompileResult
from ..core.asm import format_operand
from ..core.isa import Area, Op
from ..model.project import Project

DESCRIPTION = {
    "SOR": "inicio da rede: resultado logico (RLO) = 1",
    "EOR": "fim da rede",
    "XIC": "contato NA: RLO = RLO E bit",
    "XIO": "contato NF: RLO = RLO E NAO bit",
    "NOT": "inverte o RLO",
    "BST": "abre ramificacao paralela (guarda o RLO)",
    "NXB": "proximo ramo paralelo",
    "BND": "fecha a ramificacao: RLO = OU dos ramos",
    "OTE": "bobina: bit = RLO",
    "OTL": "SET: liga o bit se RLO = 1",
    "OTU": "RESET: desliga o bit se RLO = 1",
    "TON": "temporizador com retardo na energizacao",
    "TOF": "temporizador com retardo na desenergizacao",
    "RTO": "temporizador retentivo",
    "CTU": "contador crescente (borda de subida)",
    "CTD": "contador decrescente (borda de subida)",
    "RES": "zera temporizador/contador se RLO = 1",
}


@dataclass
class ILLine:
    pc: int
    mnemonic: str
    operand: str = ""
    symbol: str = ""
    description: str = ""
    element_id: str | None = None
    depth: int = 0


@dataclass
class ILBlock:
    rung: int
    comment: str = ""
    lines: list[ILLine] = field(default_factory=list)


def _symbol(project: Project, result: CompileResult, area: int, index: int, operand: str) -> str:
    if area == Area.TIMER:
        name = result.timer_names.get(index, operand)
    elif area == Area.COUNTER:
        name = result.counter_names.get(index, operand)
    else:
        name = project.symbol_for(operand) or ""
        if not name and "." in operand and operand[0] in "TC":
            base, bit = operand.split(".", 1)          # T0.DN -> Atraso_Partida.DN
            parent = project.symbol_for(base)
            name = f"{parent}.{bit}" if parent else ""
    return "" if name == operand else name


def il_blocks(project: Project, result: CompileResult) -> list[ILBlock]:
    """Um bloco por rede. Requer compilacao sem erros."""
    if not result.ok:
        return []
    blocks: list[ILBlock] = []
    depth = 0
    for pc, ins in enumerate(result.program.code):
        op = Op(ins.op).name
        if op == "SOR":
            r = ins.index
            blocks.append(ILBlock(r, project.rungs[r].comment if r < len(project.rungs) else ""))
            depth = 0
        if op in ("NXB", "BND"):
            depth -= 1
        operand = "" if ins.area == Area.NONE else format_operand(ins.area, ins.index)
        line = ILLine(pc, op, operand,
                      _symbol(project, result, ins.area, ins.index, operand) if operand else "",
                      DESCRIPTION.get(op, ""),
                      result.pc_element[pc] if pc < len(result.pc_element) else None, max(depth, 0))
        if op in ("TON", "TOF", "RTO"):
            line.description += f", PRE {result.program.timers[ins.index].preset_ms} ms"
        elif op in ("CTU", "CTD"):
            line.description += f", PRE {result.program.counters[ins.index].preset}"
        blocks[-1].lines.append(line)
        if op in ("BST", "NXB"):
            depth += 1
    return blocks


def il_text(blocks: list[ILBlock], header: str = "") -> str:
    out = [f"// {header}"] if header else []
    for b in blocks:
        out.append("")
        out.append(f"// ===== Rede {b.rung}" + (f" - {b.comment}" if b.comment else "") + " =====")
        for ln in b.lines:
            code = f"{'  ' * ln.depth}{ln.mnemonic:<4} {ln.operand}".rstrip()
            note = ln.symbol + (" - " if ln.symbol else "") + ln.description
            out.append(f"{ln.pc:04d}  {code:<24}// {note}")
    return "\n".join(out) + "\n"
