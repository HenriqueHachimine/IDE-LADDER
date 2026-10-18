"""Traducao do diagrama LADDER para C++ legivel.

O codigo e gerado direto do modelo do projeto, sem exigir compilacao: cada
rede vira uma ou mais linhas de C++ (contatos em serie = &&, ramos paralelos
= ||, NOT = !). Erros do diagrama aparecem como comentarios na rede e o
operando invalido vira `false`, de modo que o arquivo continua compilavel.

O ESP32 executa a imagem LDRB pelo interpretador do firmware; o C++ gerado
reproduz a mesma logica, na mesma ordem de varredura e com a mesma semantica
de temporizadores e contadores (core/vm.py). A equivalencia e conferida por
tests/test_codegen_cpp.py, que compila o C++ e compara varredura a varredura
com o simulador.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from ..compiler.compiler import COMPILER_VERSION, _Compiler
from ..core import isa
from ..core.asm import format_operand
from ..core.isa import Area, CounterType, TimerType
from ..model.project import Coil, Contact, CounterBox, NotOp, Parallel, Project, ResetBox, TimerBox

_CPP_KEYWORDS = set("""alignas alignof and and_eq asm auto bitand bitor bool break case catch char char16_t
char32_t class compl const constexpr const_cast continue decltype default delete do double dynamic_cast
else enum explicit export extern false float for friend goto if inline int long mutable namespace new
noexcept not not_eq nullptr operator or or_eq private protected public register reinterpret_cast return
short signed sizeof static static_assert static_cast struct switch template this thread_local throw true
try typedef typeid typename union unsigned using virtual void volatile wchar_t while xor xor_eq""".split())
_RUNTIME_NAMES = {"I", "Q", "M", "T", "C", "Timer", "Counter", "TON", "TOF", "RTO", "CTU", "CTD", "RES",
                  "FIRST_SCAN", "CLOCK_1S", "clock_phase", "sat_add", "counter_reset", "plc_start",
                  "plc_scan", "setup", "loop", "dt", "dt_ms", "inputs", "outputs", "k", "main", "NULL",
                  "HIGH", "LOW", "INPUT", "OUTPUT", "millis", "delay", "uint8_t", "uint16_t", "uint32_t",
                  "int32_t", "INT32_MAX", "INT32_MIN", "SCAN_PERIOD_MS", "IN_LABEL", "OUT_LABEL",
                  "TIMER_LABEL", "COUNTER_LABEL", "print_help", "print_state", "report_changes", "stamp"}
# macros e nomes globais do Arduino/ESP32 (o arquivo tambem compila como sketch)
_ARDUINO_NAMES = {"bit", "min", "max", "abs", "round", "constrain", "sq", "PI", "HEX", "DEC", "BIN",
                  "OCT", "LED_BUILTIN", "word", "byte", "boolean", "Serial", "Serial1", "Serial2",
                  "digitalRead", "digitalWrite", "pinMode", "micros", "radians", "degrees", "lowByte",
                  "highByte", "bitRead", "bitSet", "bitClear", "bitWrite", "interrupts", "noInterrupts",
                  "CHANGE", "FALLING", "RISING", "INPUT_PULLUP", "io_board_begin", "io_board_transfer"}
RESERVED = _CPP_KEYWORDS | _RUNTIME_NAMES | _ARDUINO_NAMES
_ARDUINO_BINARY = re.compile(r"^B[01]{1,8}$")      # constantes B0..B11111111 de binary.h

RUNTIME = r"""// ---------------------------------------------------------------------------
// Runtime minimo: mesma semantica do interpretador do ESP32
// (docs/ladder-specification.md). Tempos em milissegundos.
// ---------------------------------------------------------------------------
struct Timer {
    uint32_t pre;                     // preset (ms)
    uint32_t acc;                     // tempo acumulado (ms)
    bool en, tt, dn;                  // habilitado, temporizando, concluido
};

struct Counter {
    int32_t pre;                      // preset
    bool down;                        // true = CTD (decrescente)
    int32_t acc;                      // valor atual
    bool dn, ov, un, prev;            // concluido, estouro, subfluxo, memoria de borda
};

static inline uint32_t sat_add(uint32_t acc, uint32_t dt, uint32_t pre) {
    return dt >= pre - acc ? pre : acc + dt;
}

// Retardo na energizacao: DN liga quando a entrada fica ligada por PRE ms.
static inline void TON(Timer &t, bool in, uint32_t dt) {
    bool prev = t.en;
    t.en = in;
    if (in) {
        if (prev && !t.dn) t.acc = sat_add(t.acc, dt, t.pre);
        t.dn = t.acc >= t.pre;
        t.tt = !t.dn;
    } else {
        t.acc = 0; t.dn = false; t.tt = false;
    }
}

// Retardo na desenergizacao: DN desliga PRE ms depois que a entrada desliga.
static inline void TOF(Timer &t, bool in, uint32_t dt) {
    bool prev = t.en;
    t.en = in;
    if (in) {
        t.acc = 0; t.dn = true; t.tt = false;
    } else if (t.dn) {
        if (!prev) t.acc = sat_add(t.acc, dt, t.pre);
        if (t.acc >= t.pre) { t.dn = false; t.tt = false; }
        else t.tt = true;
    } else {
        t.tt = false;
    }
}

// Retentivo: acumula enquanto a entrada esta ligada e so zera com RES.
static inline void RTO(Timer &t, bool in, uint32_t dt) {
    bool prev = t.en;
    t.en = in;
    if (in) {
        if (prev && !t.dn) t.acc = sat_add(t.acc, dt, t.pre);
        t.dn = t.acc >= t.pre;
        t.tt = !t.dn;
    } else {
        t.tt = false;
    }
}

static inline void counter_reset(Counter &c) {
    c.acc = c.down ? c.pre : 0;
    c.dn = c.down ? c.acc <= 0 : c.acc >= c.pre;
    c.ov = false; c.un = false;
}

// Contador crescente: soma 1 na borda de subida da entrada.
static inline void CTU(Counter &c, bool in) {
    bool edge = in && !c.prev;
    c.prev = in;
    if (edge) { if (c.acc == INT32_MAX) c.ov = true; else c.acc++; }
    c.dn = c.acc >= c.pre;
}

// Contador decrescente: subtrai 1 na borda de subida da entrada.
static inline void CTD(Counter &c, bool in) {
    bool edge = in && !c.prev;
    c.prev = in;
    if (edge) { if (c.acc == INT32_MIN) c.un = true; else c.acc--; }
    c.dn = c.acc <= 0;
}

static inline void RES(Timer &t) { t.acc = 0; t.en = false; t.tt = false; t.dn = false; }
static inline void RES(Counter &c) { counter_reset(c); }
"""


@dataclass
class CppCode:
    text: str
    rung_lines: list[tuple[int, int]] = field(default_factory=list)   # (primeira, ultima) linha 0-based
    rung_first_element: list[str | None] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0

    def rung_at_line(self, line: int) -> int | None:
        for k, (a, b) in enumerate(self.rung_lines):
            if a <= line <= b:
                return k
        return None


class _E:
    """Expressao booleana com precedencia: 0 atomo, 1 negacao, 2 E, 3 OU."""
    __slots__ = ("text", "prec", "neg_of")

    def __init__(self, text: str, prec: int = 0, neg_of: "_E | None" = None):
        self.text, self.prec, self.neg_of = text, prec, neg_of


_FALSE = _E("false")


def _wrap(e: _E, prec: int) -> str:
    return f"({e.text})" if e.prec > prec else e.text


def _and(a: _E | None, b: _E | None) -> _E | None:
    if a is None:
        return b
    if b is None:
        return a
    if a is _FALSE or b is _FALSE:
        return _FALSE
    return _E(f"{_wrap(a, 2)} && {_wrap(b, 2)}", 2)


def _or(items: list[_E | None]) -> _E | None:
    if any(x is None for x in items):
        return None                                  # um ramo sempre conduz
    items = [x for x in items if x is not _FALSE]
    if not items:
        return _FALSE
    if len(items) == 1:
        return items[0]
    return _E(" || ".join(_wrap(x, 1) for x in items), 3)   # (a && b) || c: explicito


def _not(a: _E | None) -> _E | None:
    if a is None:
        return _FALSE
    if a is _FALSE:
        return None
    if a.neg_of is not None:
        return a.neg_of
    return _E(f"!{_wrap(a, 1)}", 1, a)


def _has_not(nodes: list) -> bool:
    for n in nodes:
        if isinstance(n, NotOp):
            return True
        if isinstance(n, Parallel) and any(_has_not(b) for b in n.branches):
            return True
    return False


def _drop_unused_temps(lines: list[str], n_temps: int) -> list[str]:
    """Remove auxiliares que a simplificacao tornou desnecessarias (ex.: ramo que sempre conduz)."""
    lines = list(lines)
    changed = True
    while changed:
        changed = False
        for k in range(min(n_temps, len(lines))):
            if not lines[k].startswith("bool "):
                continue
            name = lines[k].split()[1]
            pattern = re.compile(r"\b" + re.escape(name) + r"\b")
            if not any(pattern.search(ln) for j, ln in enumerate(lines) if j != k):
                lines[k] = ""
                changed = True
    return [ln for k, ln in enumerate(lines) if k >= n_temps or ln]


class _Gen:
    def __init__(self, project: Project):
        self.p = project
        c = _Compiler(project)
        io = project.io
        self.io_ok = (1 <= io.n_inputs <= isa.MAX_INPUTS and 1 <= io.n_outputs <= isa.MAX_OUTPUTS
                      and 0 <= io.n_markers <= isa.MAX_MARKERS)
        if self.io_ok:
            c.load_symbols()
            c.collect_drivers()
            c.compile_rungs()
            c.coil_warnings()
        else:
            c.error("configuracao de E/S fora dos limites", rung=None)
        self.c = c
        self.used_names: set[str] = set()
        self.bit_names: dict[tuple[int, int], str] = {}
        self.timer_names: dict[int, str] = {}
        self.counter_names: dict[int, str] = {}
        self.error_ids = {d.element_id for d in c.r.errors if d.element_id}
        self._name_symbols()

    # ------------------------------------------------------------- nomes
    def _unique(self, base: str) -> str:
        name = base
        while name in RESERVED or name in self.used_names or _ARDUINO_BINARY.match(name):
            name += "_"
        self.used_names.add(name)
        return name

    def _name_symbols(self) -> None:
        io = self.p.io
        limits = {Area.I: io.n_inputs, Area.Q: io.n_outputs, Area.M: io.n_markers}
        for name, (area, index) in self.c.symbols.items():
            sym = next(s.name.strip() for s in self.p.symbols if s.name.strip().upper() == name)
            if area in limits and index < limits[area]:
                self.bit_names.setdefault((area, index), self._unique(sym))
            elif area == Area.TIMER and index in self.c.timers:
                self.timer_names.setdefault(index, self._unique(sym))
            elif area == Area.COUNTER and index in self.c.counters:
                self.counter_names.setdefault(index, self._unique(sym))
        for index in sorted(self.c.timers):
            self.timer_names.setdefault(index, self._unique(f"T{index}"))
        for index in sorted(self.c.counters):
            self.counter_names.setdefault(index, self._unique(f"C{index}"))

    def bit(self, area: int, index: int) -> _E:
        if area in (Area.I, Area.Q, Area.M):
            if (area, index) not in self.bit_names:
                self.bit_names[(area, index)] = self._unique(format_operand(area, index).replace(".", "_"))
            return _E(self.bit_names[(area, index)])
        if area == Area.S:
            name = {v: k for k, v in isa.SYSTEM_BITS.items()}.get(index, "ALWAYS_OFF")
            return {"ALWAYS_ON": None, "ALWAYS_OFF": _FALSE}.get(name, _E(name))
        fld = Area(area).name.split("_")[1].lower()
        names = self.timer_names if area in (Area.T_EN, Area.T_TT, Area.T_DN) else self.counter_names
        return _E(f"{names[index]}.{fld}")

    # ---------------------------------------------------------- expressoes
    def series(self, nodes: list, cur: _E | None, temps: list[str]) -> _E | None:
        for node in nodes:
            if isinstance(node, Contact):
                ins = self._ins(node)
                term = _FALSE if ins is None or node.id in self.error_ids else self.bit(ins.area, ins.index)
                cur = _and(cur, term if node.kind == "XIC" else _not(term))
            elif isinstance(node, NotOp):
                cur = _not(cur)
            elif isinstance(node, Parallel):
                if not any(_has_not(b) for b in node.branches):
                    cur = _and(cur, _or([self.series(b, None, temps) for b in node.branches]))
                else:                                # NOT no ramo: cada ramo parte do valor de entrada
                    if cur is not None and cur.prec > 0:
                        cur = self._temp(cur, temps, "ramo")
                    cur = _or([self.series(b, cur, temps) for b in node.branches])
        return cur

    def _temp(self, e: _E, temps: list[str], base: str) -> _E:
        k = 1
        while f"{base}{k}" in self.used_names or f"{base}{k}" in RESERVED:
            k += 1
        name = f"{base}{k}"
        self.used_names.add(name)
        temps.append(f"bool {name} = {e.text};")
        return _E(name)

    def _ins(self, element):
        pc = self.c.r.element_pc.get(element.id)
        return self.c.code[pc] if pc is not None else None

    # --------------------------------------------------------------- redes
    def rung_body(self, rung) -> list[str]:
        temps: list[str] = []
        cond = self.series(rung.condition, None, temps)
        if len(rung.outputs) > 1 and cond is not None and cond.prec > 0:
            cond = self._temp(cond, temps, "rlo")
        text = "true" if cond is None else cond.text
        lines = list(temps)
        for out in rung.outputs:
            ins = self._ins(out)
            if ins is None:
                lines.append(f"// {self._describe(out)}: nao gerado (corrija o erro acima)")
                continue
            if isinstance(out, Coil):
                name = self.bit(ins.area, ins.index).text
                if out.kind == "OTE":
                    lines.append(f"{name} = {text};")
                else:
                    value = "true" if out.kind == "OTL" else "false"
                    tag = "SET" if out.kind == "OTL" else "RESET"
                    lines.append(f"{name} = {value};  // {tag}" if cond is None
                                 else f"if ({text}) {name} = {value};  // {tag}")
            elif isinstance(out, TimerBox):
                lines.append(f"{out.kind}({self.timer_names[ins.index]}, {text}, dt);")
            elif isinstance(out, CounterBox):
                lines.append(f"{out.kind}({self.counter_names[ins.index]}, {text});")
            elif isinstance(out, ResetBox):
                names = self.timer_names if ins.area == Area.TIMER else self.counter_names
                call = f"RES({names[ins.index]});"
                lines.append(call if cond is None else f"if ({text}) {call}")
        if not rung.outputs:
            lines.append("// rede sem saida")
        lines = _drop_unused_temps(lines, len(temps))
        if any(ln.startswith("bool ") for ln in lines):
            return ["{"] + ["    " + ln for ln in lines] + ["}"]
        return lines

    @staticmethod
    def _describe(out) -> str:
        return f"{getattr(out, 'kind', 'RES')} {out.operand}"

    # ------------------------------------------------------------ arquivo
    def generate(self, namespace: str | None, arduino: bool) -> CppCode:
        p, io, c = self.p, self.p.io, self.c
        rung_code = [self.rung_body(r) for r in p.rungs] if self.io_ok else []
        out: list[str] = []
        errors, warnings = c.r.errors, c.r.warnings
        out += [f"// {p.name} - codigo C++ gerado pela LadderIDE {COMPILER_VERSION} a partir do diagrama LADDER",
                "//",
                "// Gerado direto do diagrama (nao precisa compilar antes). O ESP32 executa o",
                "// mesmo programa compilado em bytecode (imagem LDRB) pelo interpretador do",
                "// firmware; este arquivo mostra a mesma logica em C++: mesma ordem das redes e",
                "// mesma semantica de temporizadores e contadores.",
                f"// Situacao: {len(errors)} erro(s), {len(warnings)} aviso(s)."
                + ("" if not errors else " Operandos com erro aparecem como 'false'."),
                ""]
        for d in [d for d in c.r.diagnostics if d.rung is None]:
            out.append(f"// {d.severity.upper()}: {d.message}")
        if arduino:
            out += ["#ifdef ARDUINO", "#include <Arduino.h>", "#endif"]
        out += ["#include <stdint.h>", ""]
        if namespace:
            out += [f"namespace {namespace} {{", ""]
        out += RUNTIME.splitlines() + [""]

        out += ["// ---------------------------------------------------------------------------",
                f"// Imagem de E/S: {io.n_inputs} entradas, {io.n_outputs} saidas (reles), {io.n_markers} memorias",
                "// ---------------------------------------------------------------------------",
                f"static bool I[{io.n_inputs}];" + "  // entradas (lidas no inicio da varredura)",
                f"static bool Q[{io.n_outputs}];" + "  // saidas (aplicadas no fim da varredura)"]
        if io.n_markers:
            out.append(f"static bool M[{io.n_markers}];  // memorias internas")
        n_t = max(c.timers) + 1 if c.timers else 0
        n_c = max(c.counters) + 1 if c.counters else 0
        if n_t:
            presets = ", ".join(f"{{{c.timers[k][1] if k in c.timers else 0}u, 0u, false, false, false}}"
                                for k in range(n_t))
            out.append(f"static Timer T[{n_t}] = {{{presets}}};  // presets em ms")
        if n_c:
            init = ", ".join(f"{{{c.counters[k][1]}, {'true' if c.counters[k][0] == CounterType.DOWN else 'false'}, "
                             "0, false, false, false, false}" if k in c.counters
                             else "{0, false, 0, false, false, false, false}" for k in range(n_c))
            out.append(f"static Counter C[{n_c}] = {{{init}}};")
        out += ["static bool FIRST_SCAN = true;       // 1 so na primeira varredura",
                "static bool CLOCK_1S = true;         // relogio de 1 s (500 ms ligado)",
                "static uint32_t clock_phase = 0;", ""]

        # Simbolos (aliases): todos os declarados e enderecos usados sem nome.
        alias = []
        for (area, index), name in sorted(self.bit_names.items()):
            arr = Area(area).name
            alias.append((f"static bool &{name} = {arr}[{index}];", format_operand(area, index)))
        for index, name in sorted(self.timer_names.items()):
            kind = TimerType(c.timers[index][0]).name
            alias.append((f"static Timer &{name} = T[{index}];", f"T{index} {kind} {c.timers[index][1]} ms"))
        for index, name in sorted(self.counter_names.items()):
            kind = "CTU" if c.counters[index][0] == CounterType.UP else "CTD"
            alias.append((f"static Counter &{name} = C[{index}];", f"C{index} {kind} {c.counters[index][1]}"))
        if alias:
            out.append("// Variaveis (nome do simbolo -> endereco do CLP)")
            width = max(len(a) for a, _ in alias)
            for decl, note in alias:
                comment = next((s.comment for s in p.symbols if s.address.strip().upper() == note.split()[0]
                                and s.comment), "")
                out.append(f"{decl:<{width}}  // {note}" + (f" - {comment}" if comment else ""))
            out.append("")

        out += ["// Partida a frio (STOP -> RUN): zera memorias, saidas, temporizadores e contadores.",
                "void plc_start() {",
                f"    for (int k = 0; k < {io.n_inputs}; k++) I[k] = false;",
                f"    for (int k = 0; k < {io.n_outputs}; k++) Q[k] = false;"]
        if io.n_markers:
            out.append(f"    for (int k = 0; k < {io.n_markers}; k++) M[k] = false;")
        if n_t:
            out.append(f"    for (int k = 0; k < {n_t}; k++) RES(T[k]);")
        if n_c:
            out.append(f"    for (int k = 0; k < {n_c}; k++) {{ counter_reset(C[k]); C[k].prev = false; }}")
        out += ["    FIRST_SCAN = true;", "    clock_phase = 0;", "}", "",
                "// Uma varredura: le as entradas, executa as redes em ordem e devolve as saidas.",
                "// dt_ms = tempo desde a varredura anterior (ignorado na primeira).",
                "uint16_t plc_scan(uint16_t inputs, uint32_t dt_ms) {",
                "    uint32_t dt = FIRST_SCAN ? 0 : dt_ms;",
                "    if (!FIRST_SCAN) clock_phase = (clock_phase + dt % 1000u) % 1000u;",
                "    CLOCK_1S = clock_phase < 500u;",
                f"    for (int k = 0; k < {io.n_inputs}; k++) I[k] = (inputs >> k) & 1u;"]
        rung_lines, first_el = [], []
        diag_by_rung: dict[int, list] = {}
        for d in c.r.diagnostics:
            if d.rung is not None:
                diag_by_rung.setdefault(d.rung, []).append(d)
        for k, (rung, body) in enumerate(zip(p.rungs, rung_code)):
            out.append("")
            start = len(out)
            out.append(f"    // ===== Rede {k}" + (f" - {rung.comment}" if rung.comment else "") + " =====")
            for d in diag_by_rung.get(k, []):
                out.append(f"    // {d.severity.upper()}: {d.message}")
            out += ["    " + ln for ln in body]
            rung_lines.append((start, len(out) - 1))
            nodes = rung.condition + rung.outputs
            first_el.append(nodes[0].id if nodes else None)
        out += ["",
                "    FIRST_SCAN = false;",
                "    uint16_t outputs = 0;",
                f"    for (int k = 0; k < {io.n_outputs}; k++) if (Q[k]) outputs |= (uint16_t)(1u << k);",
                "    return outputs;",
                "}"]
        if namespace:
            out += ["", f"}}  // namespace {namespace}"]
        if arduino:
            out += [""] + self.sketch(namespace)
        return CppCode("\n".join(out) + "\n", rung_lines, first_el, len(errors), len(warnings))

    def sketch(self, namespace: str | None) -> list[str]:
        """Secao #ifdef ARDUINO: roda o programa na placa e narra no monitor serial o que muda."""
        p, io, c = self.p, self.p.io, self.c
        ns = f"{namespace}::" if namespace else ""
        n_t = max(c.timers) + 1 if c.timers else 0
        n_c = max(c.counters) + 1 if c.counters else 0
        by_addr = {s.address.strip().upper(): s for s in p.symbols if s.name.strip()}

        def label(addr: str) -> str:
            sym = by_addr.get(addr)
            return _ascii(f"{addr} {sym.name.strip()}" if sym else addr)

        ins = [label(format_operand(Area.I, k)) for k in range(io.n_inputs)]
        outs = [label(format_operand(Area.Q, k)) for k in range(io.n_outputs)]
        timers = [label(f"T{k}") for k in range(n_t)]
        counters = [label(f"C{k}") for k in range(n_c)]
        w = max(len(x) for x in ins + outs + timers + counters)

        def table(name: str, items: list[str]) -> str:
            return f"static const char *const {name}[{len(items)}] = {{{', '.join(_c_str(x) for x in items)}}};"

        help_lines = [f"=== {_ascii(p.name)}: programa LADDER rodando no ESP32 ===",
                      f"{len(p.rungs)} rede(s), varredura a cada {io.scan_period_ms} ms. Entradas, saidas e temporizadores:"]
        used = sorted({(a, i) for a, i in self.bit_names if a != Area.M})
        for area, index in used:
            addr = format_operand(area, index)
            sym = by_addr.get(addr)
            help_lines.append(f"  {label(addr):<{w}}" + (f"  {_ascii(sym.comment)}" if sym and sym.comment else ""))
        for index in sorted(c.timers):
            kind, pre = TimerType(c.timers[index][0]).name, c.timers[index][1]
            help_lines.append(f"  {timers[index]:<{w}}  {kind} {pre} ms")
        for index in sorted(c.counters):
            kind = "CTU" if c.counters[index][0] == CounterType.UP else "CTD"
            help_lines.append(f"  {counters[index]:<{w}}  {kind} preset {c.counters[index][1]}")
        help_lines.append("Cada mudanca aparece aqui. Comandos: s = estado completo | h = ajuda")

        s: list[str] = [
            "#ifdef ARDUINO",
            "// Uso como sketch para a placa (compile junto com firmware/src/io_board.cpp, que",
            "// faz a leitura das entradas e o acionamento dos reles). Exemplo nao validado",
            "// na placa: o caminho oficial e transferir o programa pela IDE.",
            "// Monitor serial a 115200 bit/s: mostra cada entrada, saida, temporizador e",
            "// contador que muda. Comandos: s = estado completo, h = ajuda.",
            '#include "io_board.h"',
            "",
            f"static const uint32_t SCAN_PERIOD_MS = {io.scan_period_ms};",
            "",
            "// Nomes mostrados no monitor serial (endereco e simbolo)",
            table("IN_LABEL", ins),
            table("OUT_LABEL", outs)]
        if n_t:
            s.append(table("TIMER_LABEL", timers))
        if n_c:
            s.append(table("COUNTER_LABEL", counters))
        s += ["",
              "static void stamp() { Serial.printf(\"[%8lu ms] \", (unsigned long)millis()); }",
              "",
              "static void print_help() {",
              "    Serial.println();"]
        s += [f"    Serial.println({_c_str(line)});" for line in help_lines]
        s += ["}",
              "",
              "static void print_state(uint16_t inputs, uint16_t outputs) {",
              "    stamp();",
              "    Serial.println(\"estado atual:\");",
              f"    for (int k = 0; k < {io.n_inputs}; k++)",
              f"        Serial.printf(\"  %-{w}s  %s\\n\", IN_LABEL[k], (inputs >> k) & 1u ? \"1\" : \"0\");",
              f"    for (int k = 0; k < {io.n_outputs}; k++)",
              f"        Serial.printf(\"  %-{w}s  %s\\n\", OUT_LABEL[k], (outputs >> k) & 1u ? \"1 (rele ligado)\" : \"0\");"]
        for index in sorted(c.timers):
            s.append(f"    Serial.printf(\"  %-{w}s  %lu/%lu ms%s\\n\", TIMER_LABEL[{index}], "
                     f"(unsigned long){ns}T[{index}].acc, (unsigned long){ns}T[{index}].pre, "
                     f"{ns}T[{index}].dn ? \" DN\" : \"\");")
        for index in sorted(c.counters):
            s.append(f"    Serial.printf(\"  %-{w}s  %ld/%ld%s\\n\", COUNTER_LABEL[{index}], "
                     f"(long){ns}C[{index}].acc, (long){ns}C[{index}].pre, {ns}C[{index}].dn ? \" DN\" : \"\");")
        s += ["}",
              "",
              "// Compara com a varredura anterior e escreve o que mudou: entradas (causa),",
              "// temporizadores e contadores, e por fim as saidas (efeito).",
              "static void report_changes(uint16_t inputs, uint16_t outputs, bool quiet) {",
              "    static uint16_t last_in = 0, last_out = 0;"]
        if n_t:
            s.append(f"    static bool last_tt[{n_t}], last_dn[{n_t}];")
        if n_c:
            s.append(f"    static int32_t last_acc[{n_c}];")
            s.append(f"    static bool last_cdn[{n_c}];")
        s += [f"    for (int k = 0; k < {io.n_inputs}; k++) {{",
              "        bool on = (inputs >> k) & 1u;",
              "        if (!quiet && on != (bool)((last_in >> k) & 1u)) {",
              "            stamp();",
              "            Serial.printf(\"entrada %s %s\\n\", IN_LABEL[k], on ? \"LIGOU\" : \"desligou\");",
              "        }",
              "    }"]
        for index in sorted(c.timers):
            t = f"{ns}T[{index}]"
            s += [f"    if (!quiet && {t}.tt && !last_tt[{index}]) {{",
                  "        stamp();",
                  f"        Serial.printf(\"temporizador %s comecou a contar (%lu ms)\\n\", TIMER_LABEL[{index}], "
                  f"(unsigned long){t}.pre);",
                  "    }",
                  f"    if (!quiet && {t}.dn != last_dn[{index}]) {{",
                  "        stamp();",
                  f"        Serial.printf(\"temporizador %s: DN %s\\n\", TIMER_LABEL[{index}], {t}.dn ? \"LIGOU\" : \"desligou\");",
                  "    }",
                  f"    last_tt[{index}] = {t}.tt;",
                  f"    last_dn[{index}] = {t}.dn;"]
        for index in sorted(c.counters):
            k = f"{ns}C[{index}]"
            s += [f"    if (!quiet && {k}.acc != last_acc[{index}]) {{",
                  "        stamp();",
                  f"        Serial.printf(\"contador %s = %ld (preset %ld)\\n\", COUNTER_LABEL[{index}], (long){k}.acc, "
                  f"(long){k}.pre);",
                  "    }",
                  f"    if (!quiet && {k}.dn != last_cdn[{index}]) {{",
                  "        stamp();",
                  f"        Serial.printf(\"contador %s: DN %s\\n\", COUNTER_LABEL[{index}], {k}.dn ? \"LIGOU\" : \"desligou\");",
                  "    }",
                  f"    last_acc[{index}] = {k}.acc;",
                  f"    last_cdn[{index}] = {k}.dn;"]
        s += [f"    for (int k = 0; k < {io.n_outputs}; k++) {{",
              "        bool on = (outputs >> k) & 1u;",
              "        if (!quiet && on != (bool)((last_out >> k) & 1u)) {",
              "            stamp();",
              "            Serial.printf(\"saida   %s %s\\n\", OUT_LABEL[k], on ? \"LIGOU (rele energizado)\" : \"desligou\");",
              "        }",
              "    }",
              "    last_in = inputs;",
              "    last_out = outputs;",
              "}",
              "",
              "void setup() {",
              "    io_board_begin();",
              "    Serial.begin(115200);",
              "    delay(300);",
              f"    {ns}plc_start();",
              "    print_help();",
              "}",
              "",
              "void loop() {",
              "    static uint32_t last = millis();",
              "    static uint16_t inputs = 0, outputs = 0;",
              "    static bool started = false;",
              "    while (Serial.available() > 0) {",
              "        int ch = Serial.read();",
              "        if (ch == 's') print_state(inputs, outputs);",
              "        else if (ch == 'h' || ch == '?') print_help();",
              "    }",
              "    uint32_t now = millis();",
              "    if (now - last < SCAN_PERIOD_MS) return;",
              "    uint32_t dt = now - last;",
              "    last = now;",
              "    inputs = io_board_transfer(outputs);  // aplica saidas e le entradas",
              f"    outputs = {ns}plc_scan(inputs, dt);",
              "    report_changes(inputs, outputs, !started);",
              "    if (!started) print_state(inputs, outputs);  // estado depois da primeira varredura",
              "    started = true;",
              "}",
              "#endif"]
        return s


def _ascii(text: str) -> str:
    """Texto para o monitor serial: sem acentos e sem quebras de linha."""
    flat = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(flat.split())


def _c_str(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("??", "?\\?") + '"'


def generate_cpp(project: Project, *, namespace: str | None = None, arduino: bool = True) -> CppCode:
    """Gera o C++ equivalente ao diagrama. Funciona mesmo com erros (marcados em comentarios)."""
    return _Gen(project).generate(namespace, arduino)
