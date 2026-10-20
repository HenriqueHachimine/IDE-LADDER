"""Compilador: modelo de projeto -> imagem LDRB + mapa de depuracao.

Verifica simbolos, operandos, faixas de enderecos, acionamento unico de
temporizadores/contadores, estrutura das redes e limites da ISA. So produz
imagem quando nao ha erros; a imagem gerada ainda passa pela mesma validacao
executada no firmware (image.decode), garantindo que nada invalido seja
transferido.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from datetime import datetime

from ..core import isa
from ..core.asm import disassemble, format_operand, parse_constant, parse_operand
from ..core.crc import crc32
from ..core.image import (CounterDef, ImageValidationError, Instruction, Program, TimerDef, decode,
                          encode)
from ..core.isa import Area, CounterType, Op, TimerType
from ..model.project import (Coil, CompareBox, Contact, CounterBox, MathBox, NotOp, Parallel, Project,
                             ResetBox, Rung, TimerBox)

COMPILER_VERSION = "1.0.0"
TARGET_FORMAT = f"LDRB {isa.FORMAT_MAJOR}.{isa.FORMAT_MINOR}"
_SYMBOL_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,31}$")
_ADDRESS_LIKE = re.compile(r"^([IQMS]\d+\.\d+|[TC]\d+(\.\w+)?|N\d+|[IQ]W\d+|K\d+)$", re.IGNORECASE)
_WORD_NAMES = {"N": "registrador", "K": "constante", "T_ACC": "ACC de temporizador", "T_PRE": "PRE de temporizador",
               "C_ACC": "ACC de contador", "C_PRE": "PRE de contador", "IW": "entradas", "QW": "saidas"}


@dataclass
class Diagnostic:
    severity: str            # "erro" | "aviso"
    message: str
    rung: int | None = None
    element_id: str | None = None

    def __str__(self) -> str:
        where = f"Rede {self.rung}: " if self.rung is not None else ""
        return f"{self.severity.upper()}: {where}{self.message}"


@dataclass
class CompileResult:
    diagnostics: list[Diagnostic] = field(default_factory=list)
    program: Program | None = None
    image: bytes | None = None
    lil: str = ""
    build_id: int = 0
    element_pc: dict[str, int] = field(default_factory=dict)       # elemento -> instrucao
    branch_end_pc: dict[str, int] = field(default_factory=dict)    # paralelo -> BND
    element_operand: dict[str, tuple[int, int]] = field(default_factory=dict)
    element_words: dict[str, list[tuple[int, int]]] = field(default_factory=dict)  # bloco -> operandos
    rung_pcs: list[tuple[int, int]] = field(default_factory=list)  # (SOR, EOR) por rede
    pc_element: list[str | None] = field(default_factory=list)     # instrucao -> elemento
    pc_rung: list[int] = field(default_factory=list)
    timer_names: dict[int, str] = field(default_factory=dict)
    counter_names: dict[int, str] = field(default_factory=dict)

    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "erro"]

    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == "aviso"]

    @property
    def ok(self) -> bool:
        return self.image is not None and not self.errors


class _Compiler:
    def __init__(self, project: Project):
        self.p = project
        self.r = CompileResult()
        self.code: list[Instruction] = []
        self.symbols: dict[str, tuple[int, int]] = {}
        self.timers: dict[int, tuple[int, int, str]] = {}    # idx -> (tipo, preset, id)
        self.counters: dict[int, tuple[int, int, str]] = {}
        self.box_index: dict[str, int] = {}
        self.constants: list[int] = []
        self.qw_writers: list[tuple[int, MathBox]] = []
        self.rung = 0
        self.controller = None
        self.max_timers, self.max_counters = isa.MAX_TIMERS, isa.MAX_COUNTERS

    # ---------------------------------------------------------- diagnostico
    def error(self, msg: str, element=None, rung: int | None = -1) -> None:
        self.r.diagnostics.append(Diagnostic("erro", msg, self.rung if rung == -1 else rung,
                                             element.id if element is not None else None))

    def warn(self, msg: str, element=None, rung: int | None = -1) -> None:
        self.r.diagnostics.append(Diagnostic("aviso", msg, self.rung if rung == -1 else rung,
                                             element.id if element is not None else None))

    # ----------------------------------------------------------- controlador
    def check_controller(self) -> None:
        """Quantidades do projeto dentro dos limites do controlador escolhido."""
        from ..model.controllers import controller_for
        ctrl = self.controller = controller_for(self.p)
        if ctrl is None:
            self.warn(f"controlador desconhecido ({self.p.target.device!r}): usando os limites gerais da IDE",
                      rung=None)
            return
        self.max_timers, self.max_counters = ctrl.timers, ctrl.counters
        io = self.p.io
        for what, used, limit in (("entradas", io.n_inputs, ctrl.inputs), ("saidas", io.n_outputs, ctrl.outputs),
                                  ("memorias M", io.n_markers, ctrl.markers),
                                  ("registradores N", io.n_words, ctrl.words)):
            if used > limit:
                self.error(f"o controlador {ctrl.name} tem {limit} {what}; o projeto esta configurado com "
                           f"{used} (ajuste em Programa > Propriedades)", rung=None)

    # -------------------------------------------------------------- simbolos
    def load_symbols(self) -> None:
        for s in self.p.symbols:
            name = s.name.strip()
            if not _SYMBOL_NAME.match(name) or _ADDRESS_LIKE.match(name):
                self.error(f"nome de simbolo invalido: {s.name!r} (use letras, numeros e _; "
                           f"nao pode parecer um endereco)", rung=None)
                continue
            if name.upper() in self.symbols:
                self.error(f"simbolo duplicado: {name}", rung=None)
                continue
            try:
                self.symbols[name.upper()] = parse_operand(s.address)
            except ValueError:
                self.error(f"simbolo {name}: endereco invalido {s.address!r}", rung=None)

    def resolve(self, text: str, element) -> tuple[int, int] | None:
        t = text.strip()
        if not t:
            self.error("operando vazio", element)
            return None
        key = t.upper()
        if key in self.symbols:
            return self.symbols[key]
        if "." in key:  # Simbolo.DN para simbolos de temporizador/contador
            base, fld = key.rsplit(".", 1)
            if base in self.symbols:
                area, index = self.symbols[base]
                if area in (Area.TIMER, Area.COUNTER):
                    try:
                        return parse_operand(f"{'T' if area == Area.TIMER else 'C'}{index}.{fld}")
                    except ValueError:
                        pass
        try:
            return parse_operand(t)
        except ValueError:
            if _SYMBOL_NAME.match(t):
                self.error(f"variavel nao declarada: {t}", element)
            else:
                self.error(f"operando invalido: {t}", element)
            return None

    def resolve_word(self, text: str, element, write: bool) -> tuple[int, int] | None:
        """Operando numerico: constante, Nk, Tn.ACC/PRE, Cn.ACC/PRE, IW0, QW0 ou simbolo."""
        t = text.strip()
        try:
            value = parse_constant(t)
        except ValueError as exc:
            self.error(str(exc), element)
            return None
        if value is not None:
            if write:
                self.error(f"o destino nao pode ser uma constante ({t})", element)
                return None
            if value not in self.constants:
                if len(self.constants) >= isa.MAX_CONSTANTS:
                    self.error(f"constantes diferentes demais (maximo {isa.MAX_CONSTANTS})", element)
                    return None
                self.constants.append(value)
            return Area.K, self.constants.index(value)
        ref = self.resolve(t, element)
        if ref is None:
            return None
        area, index = ref
        allowed = isa.WORD_WRITE_AREAS if write else isa.WORD_READ_AREAS
        if area not in allowed:
            what = "N ou QW0" if write else "constante, N, Tn.ACC, Tn.PRE, Cn.ACC, Cn.PRE, IW0 ou QW0"
            self.error(f"{t}: {'destino' if write else 'operando'} numerico precisa ser {what}", element)
            return None
        if area == Area.N and index >= self.p.io.n_words:
            self.error(f"{t}: registrador fora da faixa configurada (N0 a N{self.p.io.n_words - 1})", element)
            return None
        if area in (Area.IW, Area.QW) and index != 0:
            self.error(f"{t}: so existe {Area(area).name}0", element)
            return None
        if area in (Area.T_ACC, Area.T_PRE) and index not in self.timers:
            self.error(f"T{index} e usado mas nenhuma instrucao TON/TOF/RTO o aciona", element)
            return None
        if area in (Area.C_ACC, Area.C_PRE) and index not in self.counters:
            self.error(f"C{index} e usado mas nenhuma instrucao CTU/CTD o aciona", element)
            return None
        return area, index

    def word_block(self, node, write_last: bool) -> list[tuple[int, int]] | None:
        refs = []
        for k, text in enumerate(node.operands):
            ref = self.resolve_word(text, node, write_last and k == len(node.operands) - 1)
            if ref is None:
                return None
            refs.append(ref)
        if len(refs) != 1 + len(isa.ARG_CLASSES[Op[node.kind]]):
            self.error(f"{node.kind} exige {1 + len(isa.ARG_CLASSES[Op[node.kind]])} operandos", node)
            return None
        self.r.element_words[node.id] = refs
        return refs

    def emit_word(self, node, refs: list[tuple[int, int]]) -> None:
        self.emit(Op[node.kind], *refs[0], node)
        for ref in refs[1:]:
            self.emit(Op.ARG, *ref, node)

    def check_range(self, area: int, index: int, element, text: str) -> bool:
        io = self.p.io
        limit = {Area.I: io.n_inputs, Area.Q: io.n_outputs, Area.M: io.n_markers,
                 Area.S: isa.NUM_SYSTEM_BITS}.get(area)
        if limit is None:
            timer = area in (Area.TIMER, Area.T_EN, Area.T_TT, Area.T_DN, Area.T_ACC, Area.T_PRE)
            limit = self.max_timers if timer else self.max_counters
        if index >= limit:
            self.error(f"{text}: endereco fora da faixa configurada (limite {limit})", element)
            return False
        return True

    # ---------------------------------------------- 1a passada: acionamentos
    def collect_drivers(self) -> None:
        for self.rung, rung in enumerate(self.p.rungs):
            for out in rung.outputs:
                if isinstance(out, TimerBox):
                    self._driver(out, Area.TIMER, self.timers, TimerType[out.kind], "temporizador")
                elif isinstance(out, CounterBox):
                    ctype = CounterType.UP if out.kind == "CTU" else CounterType.DOWN
                    self._driver(out, Area.COUNTER, self.counters, ctype, "contador")

    def _driver(self, box, area, table, type_code, what) -> None:
        ref = self.resolve(box.operand, box)
        if ref is None:
            return
        if ref[0] != area:
            self.error(f"{box.kind} exige um {what} ({'Tn' if area == Area.TIMER else 'Cn'}), "
                       f"recebeu {box.operand}", box)
            return
        index = ref[1]
        if not self.check_range(area, index, box, box.operand):
            return
        if not 0 <= box.preset <= isa.MAX_PRESET:
            self.error(f"preset fora da faixa (0 a {isa.MAX_PRESET})", box)
            return
        if index in table:
            self.error(f"{box.operand} ja e acionado por outra instrucao "
                       f"(cada {what} admite uma unica instrucao)", box)
            return
        table[index] = (type_code, box.preset, box.id)
        self.box_index[box.id] = index
        if area == Area.TIMER:
            self.r.timer_names[index] = self.p.symbol_for(f"T{index}") or f"T{index}"
            if 0 < box.preset < self.p.io.scan_period_ms:
                self.warn(f"preset de {box.preset} ms menor que o periodo de varredura "
                          f"({self.p.io.scan_period_ms} ms)", box)
        else:
            self.r.counter_names[index] = self.p.symbol_for(f"C{index}") or f"C{index}"

    # --------------------------------------------------------- 2a passada
    def emit(self, op: Op, area: int = Area.NONE, index: int = 0, element=None) -> int:
        pc = len(self.code)
        self.code.append(Instruction(op, area, index))
        self.r.pc_element.append(element.id if element is not None else None)
        self.r.pc_rung.append(self.rung)
        if element is not None and op not in (Op.BST, Op.NXB, Op.ARG):
            self.r.element_pc[element.id] = pc
        return pc

    def compile_rungs(self) -> None:
        if not self.p.rungs:
            self.warn("programa sem redes", rung=None)
        for self.rung, rung in enumerate(self.p.rungs):
            self.compile_rung(rung)

    def compile_rung(self, rung: Rung) -> None:
        if not rung.outputs:
            self.error("rede sem saida (adicione bobina, temporizador, contador, RES ou bloco matematico)")
        sor = self.emit(Op.SOR, Area.NONE, self.rung)
        self.series(rung.condition, depth=0)
        outs = rung.outputs
        if len(outs) == 1:
            self.output(outs[0])
        elif outs:
            self.check_depth(1, outs[0])
            self.emit(Op.BST)
            for k, out in enumerate(outs):
                if k:
                    self.emit(Op.NXB)
                self.output(out)
            self.emit(Op.BND)
        eor = self.emit(Op.EOR)
        self.r.rung_pcs.append((sor, eor))

    def check_depth(self, depth: int, element) -> bool:
        if depth > isa.MAX_BRANCH_DEPTH:
            self.error(f"ramificacoes aninhadas demais (maximo {isa.MAX_BRANCH_DEPTH})", element)
            return False
        return True

    def series(self, nodes: list, depth: int) -> None:
        for node in nodes:
            if isinstance(node, Contact):
                ref = self.resolve(node.operand, node)
                if ref and self.check_bit_read(ref, node):
                    self.r.element_operand[node.id] = ref
                    self.emit(Op[node.kind], ref[0], ref[1], node)
                else:
                    self.emit(Op[node.kind], Area.S, isa.SYSTEM_BITS["ALWAYS_OFF"], node)  # placeholder
            elif isinstance(node, CompareBox):
                refs = self.word_block(node, write_last=False)
                if refs:
                    self.emit_word(node, refs)
                else:
                    self.emit(Op.XIC, Area.S, isa.SYSTEM_BITS["ALWAYS_OFF"], node)  # placeholder
            elif isinstance(node, NotOp):
                self.emit(Op.NOT, element=node)
            elif isinstance(node, Parallel):
                if not self.check_depth(depth + 1, node):
                    continue
                self.emit(Op.BST, element=node)
                for k, branch in enumerate(node.branches):
                    if k:
                        self.emit(Op.NXB, element=node)
                    if not branch:
                        self.warn("ramo paralelo vazio: conduz sempre (curto-circuito)", node)
                    self.series(branch, depth + 1)
                self.r.branch_end_pc[node.id] = self.emit(Op.BND, element=node)
            else:  # pragma: no cover - o modelo impede
                self.error("elemento de saida dentro da condicao", node)

    def check_bit_read(self, ref: tuple[int, int], node) -> bool:
        area, index = ref
        if area not in isa.BIT_READ_AREAS:
            hint = " (para comparar valores use EQU, GRT, LIM...)" if area in isa.WORD_READ_AREAS else ""
            self.error(f"contato precisa de um bit (ex.: I0.0, M1.2, T0.DN), recebeu {node.operand}{hint}", node)
            return False
        if not self.check_range(area, index, node, node.operand):
            return False
        if area in (Area.T_EN, Area.T_TT, Area.T_DN) and index not in self.timers:
            self.error(f"T{index} e usado mas nenhuma instrucao TON/TOF/RTO o aciona", node)
            return False
        if area in (Area.C_DN, Area.C_OV, Area.C_UN) and index not in self.counters:
            self.error(f"C{index} e usado mas nenhuma instrucao CTU/CTD o aciona", node)
            return False
        return True

    def output(self, out) -> None:
        if isinstance(out, Coil):
            ref = self.resolve(out.operand, out)
            if ref is None:
                return
            if ref[0] not in isa.BIT_WRITE_AREAS:
                self.error(f"bobina so pode escrever em Q ou M, recebeu {out.operand}", out)
                return
            if self.check_range(ref[0], ref[1], out, out.operand):
                self.r.element_operand[out.id] = ref
                self.emit(Op[out.kind], ref[0], ref[1], out)
        elif isinstance(out, (TimerBox, CounterBox)):
            # Operando ja resolvido (e erros ja relatados) em collect_drivers.
            if out.id in self.box_index:
                area = Area.TIMER if isinstance(out, TimerBox) else Area.COUNTER
                self.emit(Op[out.kind], area, self.box_index[out.id], out)
        elif isinstance(out, MathBox):
            refs = self.word_block(out, write_last=True)
            if refs:
                self.emit_word(out, refs)
                if refs[-1][0] == Area.QW:
                    self.qw_writers.append((self.rung, out))
        elif isinstance(out, ResetBox):
            ref = self.resolve(out.operand, out)
            if ref is None:
                return
            area, index = ref
            if area not in (Area.TIMER, Area.COUNTER):
                self.error(f"RES exige um temporizador ou contador (Tn/Cn), recebeu {out.operand}", out)
                return
            table = self.timers if area == Area.TIMER else self.counters
            if index not in table:
                self.error(f"RES em {format_operand(area, index)}, que nao e acionado por nenhuma instrucao", out)
                return
            self.emit(Op.RES, area, index, out)

    # ------------------------------------------------------------ avisos
    def coil_warnings(self) -> None:
        writers: dict[tuple[int, int], list[tuple[int, Coil]]] = {}
        for r_index, node, _ in self.p.walk():
            if isinstance(node, Coil) and node.id in self.r.element_operand:
                writers.setdefault(self.r.element_operand[node.id], []).append((r_index, node))
        for ref, items in writers.items():
            kinds = {c.kind for _, c in items}
            name = format_operand(*ref)
            ote = [x for x in items if x[1].kind == "OTE"]
            if len(ote) > 1:
                for r_index, coil in ote[1:]:
                    self.warn(f"bobina {name} duplicada: vale a ultima escrita da varredura", coil, r_index)
            if "OTE" in kinds and kinds & {"OTL", "OTU"}:
                r_index, coil = ote[0]
                self.warn(f"{name} usado em bobina comum e em SET/RESET", coil, r_index)
        coils_q = any(ref[0] == Area.Q for ref in writers)
        if self.qw_writers and coils_q:
            r_index, box = self.qw_writers[0]
            self.warn("QW0 grava todas as saidas Q de uma vez e tambem ha bobinas em Q: "
                      "vale a ultima escrita da varredura", box, r_index)

    # ------------------------------------------------------------- imagem
    def build(self) -> None:
        if self.r.errors:
            return
        if len(self.code) > isa.MAX_INSTRUCTIONS:
            self.error(f"programa grande demais: {len(self.code)} instrucoes (maximo {isa.MAX_INSTRUCTIONS})", rung=None)
            return
        if len(self.p.rungs) > isa.MAX_RUNGS:
            self.error(f"redes demais (maximo {isa.MAX_RUNGS})", rung=None)
            return
        io = self.p.io
        n_t = max(self.timers) + 1 if self.timers else 0
        n_c = max(self.counters) + 1 if self.counters else 0
        prog = Program(
            n_inputs=io.n_inputs, n_outputs=io.n_outputs, n_markers=io.n_markers, n_words=io.n_words,
            constants=list(self.constants),
            timers=[TimerDef(*self.timers[k][:2]) if k in self.timers else TimerDef(TimerType.TON, 0)
                    for k in range(n_t)],
            counters=[CounterDef(*self.counters[k][:2]) if k in self.counters else CounterDef(CounterType.UP, 0)
                      for k in range(n_c)],
            code=self.code, safe_outputs=io.safe_outputs & ((1 << io.n_outputs) - 1),
        )
        body = encode(prog)
        prog.build_id = crc32(body[isa.HEADER_SIZE:-isa.CRC_SIZE]
                              + struct.pack("<HHHH", io.n_inputs, io.n_outputs, io.n_markers, io.n_words))
        image = encode(prog)
        try:
            self.r.program = decode(image)
        except ImageValidationError as exc:  # pragma: no cover - indica bug do compilador
            self.error(f"erro interno do compilador: imagem rejeitada ({exc})", rung=None)
            return
        self.r.image = image
        self.r.build_id = prog.build_id
        self.r.lil = (f"; {self.p.name} - gerado por LadderIDE compilador {COMPILER_VERSION}\n"
                      + disassemble(self.r.program))


def compile_project(project: Project) -> CompileResult:
    c = _Compiler(project)
    io = project.io
    if not (1 <= io.n_inputs <= isa.MAX_INPUTS and 1 <= io.n_outputs <= isa.MAX_OUTPUTS
            and 0 <= io.n_markers <= isa.MAX_MARKERS and 0 <= io.n_words <= isa.MAX_WORDS):
        c.error("configuracao de E/S fora dos limites", rung=None)
        return c.r
    c.check_controller()
    c.load_symbols()
    c.collect_drivers()
    c.compile_rungs()
    c.coil_warnings()
    c.build()
    if c.r.ok:
        project.build = {
            "compiler_version": COMPILER_VERSION, "format": TARGET_FORMAT,
            "build_id": f"0x{c.r.build_id:08x}", "size": len(c.r.image),
            "instructions": len(c.code), "date": datetime.now().isoformat(timespec="seconds"),
        }
    return c.r
