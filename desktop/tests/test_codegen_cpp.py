"""C++ gerado do diagrama: compila com g++ e reproduz o simulador varredura a varredura.

Todos os projetos (exemplos e projetos aleatorios) vao para um unico programa,
cada um em seu namespace, para compilar uma vez so. Sem g++ os testes de
execucao sao pulados.
"""
from __future__ import annotations

import os
import random
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from ladderide.codegen import generate_cpp
from ladderide.compiler import compile_project
from ladderide.core import LadderVM
from ladderide.model.project import (COMPARE_KINDS, MATH_KINDS, Coil, CompareBox, Contact, CounterBox, IOConfig,
                                     MathBox, NotOp, Parallel, Project, ResetBox, Rung, Symbol, TimerBox)

ROOT = Path(__file__).resolve().parents[2]
CXX = shutil.which("g++") or shutil.which("c++") or shutil.which("clang++")
DT_CHOICES = [0, 1, 5, 10, 10, 10, 37, 100, 999, 1000, 4294967295]
# nomes que colidem com C++ ou com o runtime gerado: o gerador precisa renomear
AWKWARD_NAMES = ["loop", "dt", "Timer", "int", "rlo1", "ramo1", "outputs", "k", "setup", "plc_scan", "TON",
                 "ADD", "store", "N", "MEQ"]
CONSTANTS = ["0", "1", "-1", "3", "-7", "10", "255", "256", "1234", "0x9876", "0x1A", "99999999", "46341",
             "2147483647", "-2147483648", "0x0F"]


class ProjectGenerator:
    def __init__(self, rng: random.Random):
        self.rng = rng

    def project(self) -> Project:
        r = self.rng
        p = Project(name="aleatorio", io=IOConfig(n_inputs=8, n_outputs=8, n_markers=r.choice([0, 8, 16]),
                                                  n_words=r.choice([0, 4, 4, 8])))
        n_rungs = r.randint(1, 7)
        self.timers = [(k, r.choice(["TON", "TOF", "RTO"]), r.choice([0, 10, 30, 100, 250])) for k in range(r.randint(0, 3))]
        self.counters = [(k, r.choice(["CTU", "CTD"]), r.randint(0, 5)) for k in range(r.randint(0, 3))]
        self.names: dict[str, str] = {}
        pool = list(AWKWARD_NAMES) + [f"Sinal_{k}" for k in range(8)]
        r.shuffle(pool)
        addresses = ([f"I0.{k}" for k in range(8)] + [f"Q0.{k}" for k in range(8)]
                     + [f"T{k}" for k, *_ in self.timers] + [f"C{k}" for k, *_ in self.counters])
        if p.io.n_markers:
            addresses += [f"M0.{k}" for k in range(8)]
        addresses += [f"N{k}" for k in range(p.io.n_words)]
        for addr in r.sample(addresses, min(len(addresses), r.randint(0, 6))):
            name = pool.pop()
            p.symbols.append(Symbol(name, addr))
            self.names[addr] = name
        self.p = p
        owners = {("T", k): r.randrange(n_rungs) for k, *_ in self.timers}
        owners.update({("C", k): r.randrange(n_rungs) for k, *_ in self.counters})
        p.rungs = []
        for idx in range(n_rungs):
            outs = []
            for k, kind, pre in self.timers:
                if owners[("T", k)] == idx:
                    outs.append(TimerBox(kind, self.ref(f"T{k}"), pre))
            for k, kind, pre in self.counters:
                if owners[("C", k)] == idx:
                    outs.append(CounterBox(kind, self.ref(f"C{k}"), pre))
            for _ in range(r.choice([0, 1, 1, 2]) if outs else r.choice([1, 1, 2, 3])):
                outs.append(self.output())
            r.shuffle(outs)
            p.rungs.append(Rung(self.series(0), outs, f"rede {idx}"))
        return p

    def ref(self, addr: str) -> str:
        if addr in self.names and self.rng.random() < 0.7:
            return self.names[addr]
        return addr

    def readable(self) -> str:
        r = self.rng
        options = [f"I0.{r.randrange(8)}", f"Q0.{r.randrange(8)}", f"S0.{r.randrange(4)}"]
        if self.p.io.n_markers:
            options.append(f"M0.{r.randrange(8)}")
        if self.timers:
            k = r.choice(self.timers)[0]
            options.append(f"T{k}.{r.choice(['EN', 'TT', 'DN'])}")
        if self.counters:
            k = r.choice(self.counters)[0]
            options.append(f"C{k}.{r.choice(['DN', 'OV', 'UN'])}")
        addr = r.choice(options)
        base = addr.split(".")[0] if addr[0] in "TC" else addr
        if addr[0] in "TC" and base in self.names and r.random() < 0.6:
            return f"{self.names[base]}.{addr.split('.')[1]}"
        return self.ref(addr)

    def word(self, write: bool = False) -> str:
        r = self.rng
        options = [f"N{r.randrange(self.p.io.n_words)}"] * 3 + ["QW0"]
        if not write:
            options += [r.choice(CONSTANTS) for _ in range(3)] + ["IW0", "QW0"]
            options += [f"T{k}.{r.choice(['ACC', 'PRE'])}" for k, *_ in self.timers]
            options += [f"C{k}.{r.choice(['ACC', 'PRE'])}" for k, *_ in self.counters]
        text = r.choice(options)
        base = text.split(".")[0]
        if base in self.names and r.random() < 0.6:
            return self.names[base] + text[len(base):]
        return text

    def series(self, depth: int) -> list:
        r = self.rng
        nodes = []
        for _ in range(r.randint(0, 3)):
            kind = r.random()
            if self.p.io.n_words and kind < 0.2:
                op = r.choice(list(COMPARE_KINDS))
                nodes.append(CompareBox(op, [self.word() for _ in COMPARE_KINDS[op]]))
            elif kind < 0.6 or depth >= 3:
                nodes.append(Contact(r.choice(["XIC", "XIO"]), self.readable()))
            elif kind < 0.88:
                nodes.append(Parallel([self.series(depth + 1) for _ in range(r.randint(2, 3))]))
            else:
                nodes.append(NotOp())
        return nodes

    def output(self):
        r = self.rng
        if self.p.io.n_words and r.random() < 0.3:
            op = r.choice(list(MATH_KINDS))
            n = len(MATH_KINDS[op])
            return MathBox(op, [self.word() for _ in range(n - 1)] + [self.word(write=True)])
        if r.random() < 0.15 and (self.timers or self.counters):
            items = [f"T{k}" for k, *_ in self.timers] + [f"C{k}" for k, *_ in self.counters]
            return ResetBox(self.ref(r.choice(items)))
        area = "M" if self.p.io.n_markers and r.random() < 0.4 else "Q"
        return Coil(r.choice(["OTE", "OTE", "OTL", "OTU"]), self.ref(f"{area}0.{r.randrange(8)}"))


def random_scans(rng: random.Random, n: int) -> list[tuple[int, int]]:
    inputs, scans = 0, []
    for _ in range(n):
        if rng.random() < 0.3:
            inputs ^= 1 << rng.randrange(8)
        scans.append((rng.choice(DT_CHOICES), inputs))
    return scans


def python_trace(project: Project, scans) -> list[str]:
    result = compile_project(project)
    assert result.ok, [str(d) for d in result.errors]
    vm = LadderVM(result.program)
    lines = []
    for dt, inputs in scans:
        vm.scan(inputs, dt)
        lines.append(" ".join(f for f in vm.dump_line().split() if f[:2] not in ("S=", "P=")))
    return lines


def dump_function(project: Project) -> str:
    """Imprime o estado no mesmo formato de LadderVM.dump_line (sem S= e P=)."""
    prog = compile_project(project).program
    lines = ['    printf("Q=%04x M=", (unsigned)q);']
    n_m = prog.n_markers
    for b in range(0, n_m, 8):
        bits = " | ".join(f"(M[{b + k}] << {k})" for k in range(min(8, n_m - b)))
        lines.append(f'    printf("%02x", (unsigned)({bits}));')
    lines.append('    printf(" T=");')
    for k in range(len(prog.timers)):
        sep = "," if k else ""
        lines.append(f'    printf("{sep}%lu/%x", (unsigned long)T[{k}].acc, '
                     f'(unsigned)(T[{k}].en | T[{k}].tt << 1 | T[{k}].dn << 2));')
    lines.append('    printf(" C=");')
    for k in range(len(prog.counters)):
        sep = "," if k else ""
        lines.append(f'    printf("{sep}%ld/%x", (long)C[{k}].acc, '
                     f'(unsigned)(C[{k}].dn | C[{k}].ov << 1 | C[{k}].un << 2 | C[{k}].prev << 3));')
    uses_words = "MATH_OV" in generate_cpp(project, arduino=False).text
    lines.append('    printf(" N=");')
    for k in range(prog.n_words):
        sep = "," if k else ""
        lines.append(f'    printf("{sep}%ld", (long)N[{k}]);' if uses_words else f'    printf("{sep}0");')
    lines.append('    printf(" F=%x", (unsigned)(MATH_OV | MATH_ZERO << 1 | MATH_SIGN << 2));' if uses_words
                 else '    printf(" F=0");')
    lines.append('    printf("\\n");')
    return "void dump(uint16_t q) {\n" + "\n".join(lines) + "\n}\n"


def example_projects() -> list[tuple[str, Project]]:
    out = []
    for path in sorted((ROOT / "examples").rglob("*.ladproj")):
        if path.parent.name == "demo":
            continue                      # o arquivo de demonstracao e editado a mao durante as aulas
        out.append((path.stem, Project.load(path)))
    return out


def run_cpp(projects: list[Project], scans: list[list[tuple[int, int]]], workdir: Path) -> list[list[str]]:
    parts = ["#include <stdio.h>", "#include <stdint.h>"]
    for k, project in enumerate(projects):
        code = generate_cpp(project, namespace=f"p{k}", arduino=False).text
        code = code.replace("#include <stdint.h>\n", "")
        parts.append(code.replace(f"}}  // namespace p{k}", dump_function(project) + f"}}  // namespace p{k}"))
    parts.append("int main() {\n    int prog; unsigned long dt; unsigned inputs;\n"
                 "    while (scanf(\"%d %lu %u\", &prog, &dt, &inputs) == 3) {\n        switch (prog) {")
    for k in range(len(projects)):
        parts.append(f"        case {k}: if (inputs > 0xFFFFu) p{k}::plc_start(); "
                     f"else p{k}::dump(p{k}::plc_scan((uint16_t)inputs, (uint32_t)dt)); break;")
    parts.append("        }\n    }\n    return 0;\n}\n")
    src = workdir / "ladder_cpp.cpp"
    exe = workdir / "ladder_cpp.exe"
    src.write_text("\n".join(parts), encoding="utf-8")
    proc = subprocess.run([CXX, "-std=c++11", "-Wall", "-Wextra", "-O1", "-o", str(exe), str(src)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[:4000]
    warnings = [ln for ln in proc.stderr.splitlines() if "warning" in ln]
    assert not warnings, "\n".join(warnings[:20])
    stdin = []
    for k, seq in enumerate(scans):
        stdin.append(f"{k} 0 70000")             # entradas > 16 bits = partida
        stdin += [f"{k} {dt} {inputs}" for dt, inputs in seq]
    run = subprocess.run([str(exe)], input="\n".join(stdin) + "\n", capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    lines = run.stdout.splitlines()
    out, pos = [], 0
    for seq in scans:
        out.append(lines[pos:pos + len(seq)])
        pos += len(seq)
    return out


# ------------------------------------------------------------------- texto
def test_cpp_reads_like_the_diagram():
    p = Project(name="Selo", symbols=[Symbol("Start", "I0.0"), Symbol("Stop", "I0.1"), Symbol("Motor", "Q0.0"),
                                      Symbol("Atraso", "T0")])
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Start")], [Contact("XIC", "Motor")]]), Contact("XIO", "Stop")],
             [Coil("OTE", "Motor")], "selo"),
        Rung([Contact("XIC", "Motor")], [TimerBox("TON", "Atraso", 1500), Coil("OTL", "Q0.1")]),
        Rung([Contact("XIC", "Atraso.DN")], [ResetBox("Atraso")]),
    ]
    code = generate_cpp(p)
    assert code.errors == 0
    assert "Motor = (Start || Motor) && !Stop;" in code.text
    assert "TON(Atraso, Motor, dt);" in code.text
    assert "if (Motor) Q0_1 = true;  // SET" in code.text
    assert "if (Atraso.dn) RES(Atraso);" in code.text
    assert "static bool &Start = I[0];" in code.text
    assert "static Timer T[1] = {{1500u, 0u, false, false, false}};" in code.text
    assert "// ===== Rede 0 - selo =====" in code.text
    assert len(code.rung_lines) == 3
    first, last = code.rung_lines[0]
    assert "Rede 0" in code.text.splitlines()[first]
    assert code.rung_at_line(last) == 0


def test_cpp_is_generated_even_with_errors():
    """O codigo aparece antes de compilar, mesmo com o diagrama incompleto."""
    p = Project(name="Com erro")
    p.rungs = [Rung([Contact("XIC", "Botao_Inexistente")], [Coil("OTE", "Q0.0")]), Rung([Contact("XIC", "I0.1")], [])]
    code = generate_cpp(p)
    assert code.errors >= 2
    assert "// ERRO: variável não declarada: Botao_Inexistente" in code.text
    assert "Q0_0 = false;" in code.text
    assert "// rede sem saida" in code.text


def test_cpp_renames_names_that_clash_with_cpp():
    p = Project(symbols=[Symbol("loop", "I0.0"), Symbol("int", "Q0.0")])
    p.rungs = [Rung([Contact("XIC", "loop")], [Coil("OTE", "int")])]
    text = generate_cpp(p).text
    assert "static bool &loop_ = I[0];" in text
    assert "int_ = loop_;" in text


def test_not_inside_parallel_uses_entry_value():
    p = Project()
    p.rungs = [Rung([Contact("XIC", "I0.0"), Contact("XIC", "I0.1"),
                     Parallel([[Contact("XIC", "I0.2"), NotOp()], [Contact("XIC", "I0.3")]])],
                    [Coil("OTE", "Q0.0")])]
    text = generate_cpp(p).text
    assert "bool ramo1 = I0_0 && I0_1;" in text
    assert "Q0_0 = !(ramo1 && I0_2) || (ramo1 && I0_3);" in text


# ---------------------------------------------------------------- execucao
@pytest.mark.skipif(CXX is None, reason="sem compilador C++ (g++)")
def test_generated_cpp_matches_simulator(tmp_path):
    rng = random.Random(20261017)
    gen = ProjectGenerator(rng)
    projects = [p for _, p in example_projects()]
    projects += [gen.project() for _ in range(int(os.environ.get("LADDER_CPP_PROJECTS", "80")))]
    scans = [random_scans(rng, 120) for _ in projects]
    cpp = run_cpp(projects, scans, tmp_path)
    for k, (project, seq, got) in enumerate(zip(projects, scans, cpp)):
        expected = python_trace(project, seq)
        for n, (a, b) in enumerate(zip(expected, got, strict=True), start=1):
            assert a == b, f"projeto {k} ({project.name}), varredura {n}\n  sim: {a}\n  c++: {b}"


def test_cpp_sketch_section_includes_arduino_and_avoids_arduino_macros():
    p = Project(symbols=[Symbol("bit", "I0.0"), Symbol("B1", "Q0.0")])
    p.rungs = [Rung([Contact("XIC", "bit")], [Coil("OTE", "B1")])]
    text = generate_cpp(p).text
    assert text.index("#include <Arduino.h>") < text.index("#include <stdint.h>")
    assert "B1_ = bit_;" in text


def test_firmware_example_is_in_sync_with_the_generator():
    """firmware/examples/ladder_portao/portao.cpp e exatamente o que a IDE gera do projeto do portao."""
    example = ROOT / "firmware" / "examples" / "ladder_portao" / "portao.cpp"
    project = Project.load(ROOT / "examples" / "ambientes" / "portao.ladproj")
    assert example.read_text(encoding="utf-8") == generate_cpp(project).text, (
        "regenere com: python -m ladderide.cli cpp examples/ambientes/portao.ladproj "
        "-o firmware/examples/ladder_portao/portao.cpp")


class _SerialLog:
    """Junta o que o sketch escreve na Serial; wait() espera um trecho aparecer."""

    def __init__(self):
        import threading
        self.text, self.cond = "", threading.Condition()

    def __call__(self, data: bytes) -> None:
        with self.cond:
            self.text += data.decode("utf-8", "replace")
            self.cond.notify_all()

    def wait(self, part: str, timeout: float = 5.0, since: int = 0) -> bool:
        with self.cond:
            return self.cond.wait_for(lambda: part in self.text[since:], timeout)


def _run_sketch(exe, log):
    from ladderide.comm.sketch import SketchProcess
    return SketchProcess(exe, log, lambda state: None, lambda code: None)


@pytest.mark.skipif(CXX is None, reason="g++ nao encontrado")
def test_generated_sketch_reports_every_change_on_serial():
    """O sketch gerado narra no monitor serial cada entrada, temporizador e saida que muda."""
    from ladderide.comm.sketch import build_sketch
    log = _SerialLog()
    proc = _run_sketch(build_sketch("ladder_portao"), log)
    try:
        assert log.wait("=== Portao de garagem: programa LADDER rodando no ESP32 ===")
        assert log.wait("estado atual:")                                  # depois da primeira varredura
        assert "I0.2 Parar" in log.text and "Botao PARAR (NF: le 1 quando solto)" in log.text
        proc.set_inputs(0b10100)                                          # Parar solto + fim de curso fechado
        assert log.wait("entrada I0.2 Parar LIGOU") and log.wait("saida   Q0.4 Lampada_Fechado LIGOU")
        proc.set_inputs(0b10101)                                          # + botao Abrir
        assert log.wait("entrada I0.0 Abrir LIGOU") and log.wait("saida   Q0.0 Motor_Sobe LIGOU")
        proc.set_inputs(0b00100)                                          # saiu do fim de curso
        assert log.wait("saida   Q0.2 Lampada_Entreaberto LIGOU")
        proc.send_serial(b"s")
        assert log.wait("T0 Espera_Reversao")
        assert log.text.index("entrada I0.0 Abrir LIGOU") < log.text.index("saida   Q0.0 Motor_Sobe LIGOU")
    finally:
        proc.close()


@pytest.mark.skipif(CXX is None, reason="g++ nao encontrado")
def test_generated_sketch_with_timers_and_counters_compiles_and_runs(tmp_path):
    """A secao Arduino de projetos com temporizadores e contadores compila sem avisos e roda no simulador."""
    from ladderide.comm import sketch
    rng = random.Random(7)
    gen = ProjectGenerator(rng)
    project = gen.project()
    while not (gen.timers and gen.counters):
        project = gen.project()
    (tmp_path / "prog.cpp").write_text(generate_cpp(project).text, encoding="utf-8")
    exe = tmp_path / "prog.exe"
    cmd = [CXX, "-std=gnu++11", "-O1", "-Wall", "-Werror", "-DARDUINO=10819", "-DARDUINO_SIM=1",
           f"-I{sketch.SIM_DIR}", f"-I{sketch.FIRMWARE / 'src'}", str(tmp_path / "prog.cpp"),
           str(sketch.FIRMWARE / "src" / "io_board.cpp"), str(sketch.SIM_DIR / "arduino_sim.cpp"), "-o", str(exe)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    log = _SerialLog()
    proc = _run_sketch(exe, log)
    try:
        assert log.wait("estado atual:")
        proc.set_inputs(0xFF)
        assert log.wait("entrada I0.7")
        start = len(log.text)
        proc.send_serial(b"s")
        assert log.wait("estado atual:", since=start)
        tables = [ln for ln in generate_cpp(project).text.splitlines()
                  if ln.startswith(("static const char *const TIMER_LABEL", "static const char *const COUNTER_LABEL"))]
        assert len(tables) == 2
        for label in re.findall(r'"([^"]+)"', "".join(tables)):            # temporizadores e contadores no estado
            assert log.wait(f"  {label} ", since=start), label
    finally:
        proc.close()


@pytest.mark.skipif(CXX is None, reason="sem compilador C++ (g++)")
def test_condition_is_kept_when_an_output_changes_what_it_reads(tmp_path):
    """O CLP calcula a condicao uma vez; o C++ nao pode reavaliar depois de uma saida mudar o operando."""
    p = Project(io=IOConfig(n_words=2))
    p.rungs = [Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.0")]),
               Rung([Contact("XIC", "Q0.0")], [Coil("OTU", "Q0.0"), Coil("OTE", "Q0.1")]),
               Rung([CompareBox("LES", ["N0", "3"])], [MathBox("ADD", ["N0", "1", "N0"]), Coil("OTE", "Q0.2")])]
    text = generate_cpp(p, arduino=False).text
    assert "bool rlo1 = Q0_0;" in text and "Q0_1 = rlo1;" in text
    seq = [(10, 1), (10, 0), (10, 0), (10, 0), (10, 0)]
    assert run_cpp([p], [seq], tmp_path)[0] == python_trace(p, seq)


def test_cpp_compare_and_math_read_like_the_diagram():
    p = Project(symbols=[Symbol("Pecas", "C0"), Symbol("Total", "N2")])
    p.rungs = [Rung([Contact("XIC", "I0.0")], [CounterBox("CTU", "Pecas", 10)]),
               Rung([CompareBox("GEQ", ["Pecas.ACC", "3"]), CompareBox("LIM", ["0", "Total", "100"])],
                    [MathBox("MUL", ["Pecas.ACC", "-2147483648", "Total"])]),
               Rung([Contact("XIC", "S0.4")], [MathBox("TOD", ["Total", "QW0"])])]
    code = generate_cpp(p)
    assert code.errors == 0, code.text
    assert "static int32_t &Total = N[2];" in code.text
    assert "if (Pecas.acc >= 3 && LIM(0, Total, 100)) store(Total, MUL(Pecas.acc, INT32_MIN));" in code.text \
        or "if ((Pecas.acc >= 3) && LIM(0, Total, 100)) store(Total, MUL(Pecas.acc, INT32_MIN));" in code.text
    assert "if (MATH_OV) store_QW(TOD(Total));" in code.text
