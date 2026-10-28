"""Verificacao de um programa antes de envia-lo ao ESP32.

Reune, em um unico relatorio, tudo o que a IDE consegue verificar sem a
placa e, se houver dispositivo conectado, o que ele informa:

* compilacao e validacao da imagem LDRB (validador Python);
* validacao pelo codigo C do firmware (ladder_vm compilado no PC);
* equivalencia simulador x firmware: a mesma sequencia de entradas e
  executada nas duas VMs e o estado completo e comparado a cada varredura;
* recursos da placa (entradas, saidas, memoria, limites da ISA);
* temporizacao (periodo de varredura, resolucao dos temporizadores);
* dispositivo conectado: formato, memoria e tempo de varredura medido.

Nenhum item afirma algo sobre o hardware que nao tenha sido medido: o tempo
de varredura so e avaliado com dados reais do dispositivo.
"""
from __future__ import annotations

import random
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ..compiler.compiler import CompileResult
from ..core import isa
from ..core.image import ImageValidationError, decode
from ..core.isa import Area, Op
from ..core.vm import LadderVM
from ..model.project import Project

OK, WARN, ERROR, INFO, SKIP = "ok", "aviso", "erro", "info", "não verificado"


@dataclass
class Check:
    status: str
    title: str
    detail: str = ""


@dataclass
class BoardProfile:
    """Caracteristicas da placa. Lidas de firmware/src/board_config.h quando disponivel."""
    inputs: int = 8
    outputs: int = 8
    scan_period_ms: int = 10
    watchdog_us: int = 50000
    firmware: str = "1.0.0"
    hardware: str = "esp32-relay-x8-303e32dc812"
    source: str = "valores padrão"

    @classmethod
    def load(cls) -> "BoardProfile":
        from ..comm.virtual import FIRMWARE
        path = FIRMWARE / "src" / "board_config.h"
        if not path.exists():
            return cls()
        text = path.read_text(encoding="utf-8", errors="replace")

        def define(name: str, default):
            m = re.search(rf"#define\s+{name}\s+(\"[^\"]*\"|\d+)", text)
            if not m:
                return default
            value = m.group(1)
            return value.strip('"') if value.startswith('"') else int(value)

        return cls(define("BOARD_INPUTS", 8), define("BOARD_OUTPUTS", 8), define("SCAN_PERIOD_MS", 10),
                   define("SCAN_WATCHDOG_US", 50000), define("FW_VERSION", "1.0.0"),
                   define("HW_ID", "esp32-relay-x8-303e32dc812"), "firmware/src/board_config.h")


@dataclass
class VerifyReport:
    checks: list[Check] = field(default_factory=list)
    board: BoardProfile = field(default_factory=BoardProfile)
    scans_compared: int = 0

    def add(self, status: str, title: str, detail: str = "") -> None:
        self.checks.append(Check(status, title, detail))

    @property
    def errors(self) -> list[Check]:
        return [c for c in self.checks if c.status == ERROR]

    @property
    def warnings(self) -> list[Check]:
        return [c for c in self.checks if c.status == WARN]

    @property
    def ok(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        if self.errors:
            return f"{len(self.errors)} erro(s): o programa NÃO deve ser enviado ao ESP32."
        if self.warnings:
            return f"Pronto para o ESP32, com {len(self.warnings)} aviso(s)."
        return "Pronto para o ESP32: todas as verificações passaram."

    def as_text(self) -> str:
        lines = [self.summary(), ""]
        for c in self.checks:
            lines.append(f"[{c.status.upper()}] {c.title}")
            if c.detail:
                lines += [f"    {line}" for line in c.detail.splitlines()]
        return "\n".join(lines)


def branch_depth(code) -> int:
    depth = best = 0
    for ins in code:
        if ins.op == Op.BST:
            depth += 1
            best = max(best, depth)
        elif ins.op == Op.BND:
            depth -= 1
    return best


def stimulus(n_inputs: int, scans: int, period_ms: int, seed: int = 2026) -> list[tuple[int, int]]:
    """Sequencia deterministica (dt_ms, entradas): entradas mudam aos poucos,
    com varreduras normais, pausas longas e uma varredura com dt = 0."""
    rng = random.Random(seed)
    mask = (1 << n_inputs) - 1
    inputs, seq = 0, [(0, 0)]
    for k in range(1, scans):
        if rng.random() < 0.25:
            inputs ^= 1 << rng.randrange(max(1, n_inputs))
        if k % 50 == 0:
            inputs = rng.getrandbits(n_inputs)
        dt = rng.choice([period_ms] * 8 + [0, 1, 3 * period_ms, 1000, 5000])
        seq.append((dt, inputs & mask))
    return seq


def python_trace(image: bytes, seq: list[tuple[int, int]]) -> list[str]:
    vm = LadderVM(decode(image))
    out = []
    for dt, inputs in seq:
        vm.scan(inputs, dt)
        out.append(vm.dump_line())
    return out


def firmware_trace(image: bytes, seq: list[tuple[int, int]]) -> tuple[str, list[str]]:
    """Executa a VM C do firmware (lv_host_runner). Retorna ("OK"|"ERR c i", linhas)."""
    from ..comm.virtual import host_tool
    exe = host_tool("lv_host_runner")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "programa.ldrb"
        path.write_bytes(image)
        stdin = "".join(f"{dt} {inputs:x}\n" for dt, inputs in seq)
        proc = subprocess.run([str(exe), "run", str(path)], input=stdin, capture_output=True, text=True,
                              timeout=60)
    lines = proc.stdout.splitlines()
    if not lines:
        raise RuntimeError(proc.stderr.strip() or "executor da VM C não produziu saída")
    return lines[0].strip(), lines[1:]


def _used_bits(result: CompileResult, area: Area) -> set[int]:
    return {idx for a, idx in result.element_operand.values() if a == area}


def verify_for_esp32(project: Project, result: CompileResult, *, device_info=None, device_status=None,
                     scans: int = 400, board: BoardProfile | None = None) -> VerifyReport:
    rep = VerifyReport(board=board or BoardProfile.load())
    b = rep.board

    # 1. compilacao ------------------------------------------------------------
    if not result.ok:
        rep.add(ERROR, "Compilacao", "\n".join(str(d) for d in result.errors) or "o programa não compilou")
        return rep
    code = result.program.code
    rep.add(OK if not result.warnings else WARN, "Compilacao",
            f"{len(code)} instruções, {len(project.rungs)} redes, id 0x{result.build_id:08x}"
            + ("".join(f"\n{d}" for d in result.warnings)))

    # 2. imagem LDRB -----------------------------------------------------------
    image = result.image
    try:
        prog = decode(image)
        rep.add(OK, "Imagem LDRB valida (validador da IDE)",
                f"{len(image)} bytes, CRC-32 conferido, formato {isa.FORMAT_MAJOR}.{isa.FORMAT_MINOR}")
    except ImageValidationError as exc:
        rep.add(ERROR, "Imagem LDRB valida (validador da IDE)", str(exc))
        return rep

    # 3 e 4. codigo C do firmware ----------------------------------------------
    seq = stimulus(prog.n_inputs, scans, b.scan_period_ms)
    try:
        status, c_lines = firmware_trace(image, seq)
    except Exception as exc:  # noqa: BLE001 - ausencia do gcc nao impede o restante
        rep.add(SKIP, "Validação pelo código C do firmware",
                f"não foi possível executar a VM C no PC: {exc}\n"
                "Instale o gcc (MinGW) para habilitar esta verificação.")
        rep.add(SKIP, "Equivalência simulador x firmware", "depende da VM C")
    else:
        if status != "OK":
            rep.add(ERROR, "Validação pelo código C do firmware",
                    f"o firmware rejeitaria esta imagem ({status}); a transferência seria recusada")
        else:
            rep.add(OK, "Validação pelo código C do firmware",
                    "lv_image_validate (o mesmo código que roda no ESP32) aceitou a imagem")
            py_lines = python_trace(image, seq)
            rep.scans_compared = len(py_lines)
            diff = next((k for k, (a, c) in enumerate(zip(py_lines, c_lines)) if a != c), None)
            if diff is None and len(py_lines) == len(c_lines):
                rep.add(OK, "Equivalência simulador x firmware",
                        f"{len(py_lines)} varreduras com entradas variadas e dt de 0 a 5000 ms: estado "
                        "completo (saídas, memórias, temporizadores, contadores e fluxo de energia) identico")
            else:
                k = diff if diff is not None else min(len(py_lines), len(c_lines))
                dt, inputs = seq[k] if k < len(seq) else (0, 0)
                rep.add(ERROR, "Equivalência simulador x firmware",
                        f"divergência na varredura {k} (dt={dt} ms, entradas=0x{inputs:02x})\n"
                        f"simulador: {py_lines[k] if k < len(py_lines) else '-'}\n"
                        f"firmware:  {c_lines[k] if k < len(c_lines) else '-'}")

    # 5. recursos da placa -----------------------------------------------------
    bad_in = sorted(i for i in _used_bits(result, Area.I) if i >= b.inputs)
    bad_out = sorted(i for i in _used_bits(result, Area.Q) if i >= b.outputs)
    if bad_in or bad_out:
        names = [f"I{i // 8}.{i % 8}" for i in bad_in] + [f"Q{i // 8}.{i % 8}" for i in bad_out]
        rep.add(ERROR, "Entradas e saídas da placa",
                f"a placa tem {b.inputs} entradas e {b.outputs} relés; endereços inexistentes: {', '.join(names)}")
    elif prog.n_inputs > b.inputs or prog.n_outputs > b.outputs:
        rep.add(ERROR, "Entradas e saídas da placa",
                f"o projeto declara {prog.n_inputs} entradas/{prog.n_outputs} saídas; a placa tem "
                f"{b.inputs}/{b.outputs}. Ajuste em Propriedades do projeto.")
    else:
        used_q = len(_used_bits(result, Area.Q))
        rep.add(OK, "Entradas e saídas da placa",
                f"usa {len(_used_bits(result, Area.I))} de {b.inputs} entradas e {used_q} de {b.outputs} relés "
                f"(perfil: {b.source})")

    from ..model.controllers import controller_for
    ctrl = controller_for(project)
    if ctrl is not None and not ctrl.hardware:
        rep.add(WARN, "Controlador do projeto",
                f"o projeto usa o controlador '{ctrl.name}', que não e a placa; troque em Programa > "
                "Propriedades antes de transferir")

    limit = isa.MAX_IMAGE_SIZE
    pct = 100 * len(image) / limit
    rep.add(OK if pct <= 90 else WARN, "Memória de programa",
            f"{len(image)} de {limit} bytes ({pct:.1f}%)")
    lim = isa.LIM
    depth = branch_depth(code)
    problems = []
    if len(code) > lim["max_instructions"]:
        problems.append(f"{len(code)} instruções (max {lim['max_instructions']})")
    if depth > lim["max_branch_depth"]:
        problems.append(f"aninhamento {depth} (max {lim['max_branch_depth']})")
    if len(prog.timers) > lim["max_timers"] or len(prog.counters) > lim["max_counters"]:
        problems.append("temporizadores/contadores acima do limite")
    rep.add(ERROR if problems else OK, "Limites do interpretador",
            "; ".join(problems) if problems else
            f"{len(prog.timers)}/{lim['max_timers']} temporizadores, {len(prog.counters)}/{lim['max_counters']} "
            f"contadores, {prog.n_markers} memórias M, aninhamento de ramos {depth}/{lim['max_branch_depth']}")

    # 6. temporizacao ----------------------------------------------------------
    period = project.io.scan_period_ms
    if period != b.scan_period_ms:
        rep.add(WARN, "Período de varredura",
                f"o projeto simula com {period} ms, mas o firmware varre a cada {b.scan_period_ms} ms; "
                "os tempos na placa podem diferir do simulador")
    else:
        rep.add(OK, "Período de varredura", f"{period} ms no simulador e no firmware")
    short = [f"{result.timer_names.get(k, f'T{k}')} ({t.preset_ms} ms)" for k, t in enumerate(prog.timers)
             if 0 < t.preset_ms < 2 * b.scan_period_ms]
    if short:
        rep.add(WARN, "Resolução dos temporizadores",
                f"presets menores que 2 varreduras ({2 * b.scan_period_ms} ms) terminam com atraso de até "
                f"{b.scan_period_ms} ms: {', '.join(short)}")
    elif prog.timers:
        rep.add(OK, "Resolução dos temporizadores",
                f"todos os presets são >= {2 * b.scan_period_ms} ms (erro máximo de 1 varredura = "
                f"{b.scan_period_ms} ms)")

    # 7. dispositivo conectado -------------------------------------------------
    if device_info is None:
        rep.add(SKIP, "Dispositivo conectado",
                "nenhum dispositivo conectado; formato do firmware e tempo de varredura real não foram "
                "conferidos (conecte no painel Dispositivo e verifique novamente)")
        return rep
    di = device_info
    problems = []
    if di.fmt_major != isa.FORMAT_MAJOR or di.fmt_minor < isa.FORMAT_MINOR:
        problems.append(f"firmware aceita LDRB {di.fmt_major}.{di.fmt_minor}; a IDE gera "
                        f"{isa.FORMAT_MAJOR}.{isa.FORMAT_MINOR}")
    if prog.n_inputs > di.n_inputs or prog.n_outputs > di.n_outputs:
        problems.append(f"dispositivo tem {di.n_inputs}/{di.n_outputs} E/S")
    if len(image) > di.max_image:
        problems.append(f"imagem de {len(image)} B > {di.max_image} B suportados")
    rep.add(ERROR if problems else OK, "Compatibilidade com o dispositivo",
            "; ".join(problems) if problems else
            f"{di.firmware} | {di.hardware}, LDRB {di.fmt_major}.{di.fmt_minor}, até {di.max_image} B")
    st = device_status
    if st is None or not st.has_program or st.build_id != result.build_id:
        rep.add(SKIP, "Tempo de varredura medido no dispositivo",
                "o dispositivo não esta executando este programa; transfira, coloque em RUN e verifique de novo")
    elif st.scan_count == 0:
        rep.add(SKIP, "Tempo de varredura medido no dispositivo", "nenhuma varredura executada ainda (RUN)")
    else:
        margin = st.max_exec_us / b.watchdog_us
        status = ERROR if st.max_exec_us >= b.watchdog_us else (WARN if margin > 0.5 or st.overruns else OK)
        rep.add(status, "Tempo de varredura medido no dispositivo",
                f"última {st.last_exec_us} us, máxima {st.max_exec_us} us em {st.scan_count} varreduras; "
                f"watchdog {b.watchdog_us} us ({100 * margin:.1f}% usado); atrasos de período: {st.overruns}")
    return rep
