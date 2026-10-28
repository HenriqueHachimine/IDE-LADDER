"""Importacao de listagens LIL (ou imagens LDRB) para o modelo grafico.

Aceita a estrutura gerada pelo compilador: em cada rede, uma condicao formada
por contatos, NOT e ramos BST/NXB/BND, seguida das saidas (uma unica, varias em
serie ou um grupo BST/NXB/BND contendo apenas saidas). Saidas em serie sao
equivalentes a saidas em paralelo, pois instrucoes de saida nao alteram o RLO.
"""
from __future__ import annotations

from ..core.asm import assemble, format_operand
from ..core.image import Instruction, Program, decode
from ..core import isa
from ..core.isa import Area, CounterType, Op, TimerType
from ..model.project import (Coil, Contact, CounterBox, IOConfig, NotOp, Parallel, Project,
                             ResetBox, Rung, TimerBox)

_OUTPUT_OPS = {Op.OTE, Op.OTL, Op.OTU, Op.TON, Op.TOF, Op.RTO, Op.CTU, Op.CTD, Op.RES}


class ImportError_(ValueError):
    pass


def import_lil(text: str, name: str = "Importado") -> Project:
    return program_to_project(assemble(text), name)


def import_image(data: bytes, name: str = "Importado") -> Project:
    return program_to_project(decode(data, isa.IDE_MAX_INPUTS), name)


def program_to_project(prog: Program, name: str) -> Project:
    p = Project(name=name, io=IOConfig(prog.n_inputs, prog.n_outputs, prog.n_markers,
                                       prog.safe_outputs), rungs=[])
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


class _RungParser:
    def __init__(self, body: list[Instruction], prog: Program, rung: int):
        self.body, self.prog, self.rung, self.pos = body, prog, rung, 0

    def fail(self, msg: str):
        raise ImportError_(f"rede {self.rung}, instrução {self.pos}: {msg}")

    def peek(self, offset: int = 0) -> Instruction | None:
        k = self.pos + offset
        return self.body[k] if k < len(self.body) else None

    def parse(self) -> Rung:
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
        self.pos += 1
        op = Op(ins.op)
        operand = format_operand(ins.area, ins.index)
        if op in (Op.OTE, Op.OTL, Op.OTU):
            return Coil(op.name, operand)
        if op in (Op.TON, Op.TOF, Op.RTO):
            t = self.prog.timers[ins.index]
            return TimerBox(TimerType(t.type).name, operand, t.preset_ms)
        if op in (Op.CTU, Op.CTD):
            c = self.prog.counters[ins.index]
            return CounterBox("CTU" if c.type == CounterType.UP else "CTD", operand, c.preset)
        if ins.area not in (Area.TIMER, Area.COUNTER):
            self.fail("RES com operando inválido")
        return ResetBox(operand)
