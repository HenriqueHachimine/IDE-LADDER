"""Importacao de listagens LIL (ou imagens LDRB) para o modelo grafico.

Aceita a estrutura gerada pelo compilador: em cada rede, uma condicao formada
por contatos, NOT e ramos BST/NXB/BND, seguida das saidas (uma unica, varias em
serie ou um grupo BST/NXB/BND contendo apenas saidas). Saidas em serie sao
equivalentes a saidas em paralelo, pois instrucoes de saida nao alteram o RLO.
"""
from __future__ import annotations

import struct

from ..core.asm import assemble, format_operand
from ..core.image import Instruction, Program, decode, encode
from ..core import isa
from ..core.isa import Area, CounterType, Op, TimerType
from ..model.controllers import default_controller, load_controllers
from ..model.project import (Coil, CompareBox, Contact, CounterBox, IOConfig, MathBox, NotOp, Parallel, Project,
                             ResetBox, Rung, TimerBox)

_OUTPUT_OPS = {Op.OTE, Op.OTL, Op.OTU, Op.TON, Op.TOF, Op.RTO, Op.CTU, Op.CTD, Op.RES} | set(isa.MATH_OPS)


class ImportError_(ValueError):
    pass


def import_lil(text: str, name: str = "Importado") -> Project:
    prog = assemble(text)
    try:                                # mesma validacao de uma imagem recebida (operandos, limites, presets)
        checked = decode(encode(prog), isa.IDE_MAX_INPUTS, isa.IDE_MAX_OUTPUTS)
    except struct.error as exc:
        raise ImportError_(f"valor fora da faixa na listagem: {exc}") from None
    return program_to_project(checked, name)


def import_image(data: bytes, name: str = "Importado") -> Project:
    return program_to_project(decode(data, isa.IDE_MAX_INPUTS, isa.IDE_MAX_OUTPUTS), name)


def program_to_project(prog: Program, name: str) -> Project:
    p = Project(name=name, io=IOConfig(n_inputs=prog.n_inputs, n_outputs=prog.n_outputs, n_markers=prog.n_markers,
                                       n_words=prog.n_words, safe_outputs=prog.safe_outputs), rungs=[])
    p.target.device = _controller_for_io(prog.n_inputs, prog.n_outputs)
    rungs: list[list[Instruction]] = []
    current: list[Instruction] | None = None
    for ins in prog.code:
        if ins.op == Op.SOR:
            current = []
        elif ins.op == Op.EOR:
            if current is None:
                raise ImportError_("EOR sem SOR")
            rungs.append(current)
            current = None
        elif current is None:
            raise ImportError_("instrução fora de rede")
        else:
            current.append(ins)
    if current is not None:
        raise ImportError_("rede sem EOR")
    for k, body in enumerate(rungs):
        parser = _RungParser(body, prog, k)
        p.rungs.append(parser.parse())
    if not p.rungs:
        p.rungs.append(Rung())
    return p


def _controller_for_io(n_inputs: int, n_outputs: int) -> str:
    """Controlador que nao corta as E/S do programa importado."""
    default = default_controller()
    if (default.inputs, default.outputs) == (n_inputs, n_outputs):
        return default.id
    if n_inputs > 16 or n_outputs > 16:                 # o Personalizado vai ate 16 E/S
        for c in load_controllers():
            if (c.inputs, c.outputs) == (n_inputs, n_outputs):
                return c.id
    return "personalizado"


class _RungParser:
    def __init__(self, body: list[Instruction], prog: Program, rung: int):
        self.body, self.prog, self.rung, self.pos = body, prog, rung, 0

    def fail(self, msg: str):
        raise ImportError_(f"rede {self.rung}, instrução {self.pos}: {msg}")

    def peek(self, offset: int = 0) -> Instruction | None:
        k = self.pos + offset
        return self.body[k] if k < len(self.body) else None

    def skip_variable_inits(self) -> None:
        """Valores iniciais que o compilador poe no inicio da rede 0: nao viram diagrama."""
        first = self.peek(1)
        if (self.peek() is None or self.peek().op != Op.BST or first is None or first.op != Op.XIC
                or (first.area, first.index) != (Area.S, isa.SYSTEM_BITS["FIRST_SCAN"])):
            return
        k = 2
        while (ins := self.peek(k)) is not None and ins.op in (Op.OTL, Op.MOV, Op.ARG):
            k += 1
        after = self.peek(k + 1)
        if self.peek(k) is not None and self.peek(k).op == Op.NXB and after is not None and after.op == Op.BND:
            self.pos += k + 2

    def parse(self) -> Rung:
        self.skip_variable_inits()
        cond = self.series(top=True)
        outputs = self.outputs()
        if self.pos != len(self.body):
            self.fail("estrutura não suportada pelo editor gráfico")
        return Rung(cond, outputs)

    def series(self, top: bool) -> list:
        nodes = []
        while (ins := self.peek()) is not None:
            op = Op(ins.op)
            if op in (Op.XIC, Op.XIO):
                nodes.append(Contact(op.name, format_operand(ins.area, ins.index)))
                self.pos += 1
            elif op in isa.COMPARE_OPS:
                nodes.append(CompareBox(op.name, self.word_operands()))
            elif op == Op.NOT:
                nodes.append(NotOp())
                self.pos += 1
            elif op == Op.BST:
                nxt = self.peek(1)
                if top and nxt is not None and Op(nxt.op) in _OUTPUT_OPS:
                    break  # grupo de saidas
                self.pos += 1
                branches = [self.series(top=False)]
                while (sep := self.peek()) is not None and sep.op == Op.NXB:
                    self.pos += 1
                    branches.append(self.series(top=False))
                if (end := self.peek()) is None or end.op != Op.BND:
                    self.fail("BND esperado")
                self.pos += 1
                nodes.append(Parallel(branches))
            elif op in (Op.NXB, Op.BND) and not top:
                break
            elif op in _OUTPUT_OPS and top:
                break
            else:
                self.fail(f"{op.name} inesperado")
        return nodes

    def word_operands(self) -> list[str]:
        """Operando da instrucao atual e os ARG seguintes (blocos de comparacao e matematica)."""
        ins = self.peek()
        self.pos += 1
        refs = [format_operand(ins.area, ins.index, self.prog.constants)]
        while (arg := self.peek()) is not None and arg.op == Op.ARG:
            refs.append(format_operand(arg.area, arg.index, self.prog.constants))
            self.pos += 1
        return refs

    def outputs(self) -> list:
        outs = []
        ins = self.peek()
        if ins is not None and ins.op == Op.BST:
            self.pos += 1
            while True:
                outs.append(self.output())
                sep = self.peek()
                if sep is not None and sep.op == Op.NXB:
                    self.pos += 1
                    continue
                if sep is not None and sep.op == Op.BND:
                    self.pos += 1
                    break
                self.fail("grupo de saídas mal formado")
        while (ins := self.peek()) is not None and Op(ins.op) in _OUTPUT_OPS:
            outs.append(self.output())
        return outs

    def output(self):
        ins = self.peek()
        if ins is None or Op(ins.op) not in _OUTPUT_OPS:
            self.fail("saída esperada")
        op = Op(ins.op)
        if op in isa.MATH_OPS:
            return MathBox(op.name, self.word_operands())
        self.pos += 1
        operand = format_operand(ins.area, ins.index)
        if op in (Op.OTE, Op.OTL, Op.OTU):
            return Coil(op.name, operand)
        if op in (Op.TON, Op.TOF, Op.RTO):
            t = self.prog.timers[ins.index]
            if TimerType(t.type).name != op.name:
                self.fail(f"{op.name} em T{ins.index}, declarado como {TimerType(t.type).name}")
            return TimerBox(TimerType(t.type).name, operand, t.preset_ms)
        if op in (Op.CTU, Op.CTD):
            c = self.prog.counters[ins.index]
            if ("CTU" if c.type == CounterType.UP else "CTD") != op.name:
                self.fail(f"{op.name} em C{ins.index}, declarado com outro tipo")
            return CounterBox("CTU" if c.type == CounterType.UP else "CTD", operand, c.preset)
        if ins.area not in (Area.TIMER, Area.COUNTER):
            self.fail("RES com operando inválido")
        return ResetBox(operand)
