"""Verificacao para o ESP32 e blocos de instrucao."""
from __future__ import annotations

from types import SimpleNamespace

from conftest import ROOT
from ladderide.compiler import compile_project
from ladderide.comm.virtual import BuildError
from ladderide.model import Coil, Contact, Parallel, Project, Rung, TimerBox
from ladderide.verify import esp32, il_blocks, il_text, verify_for_esp32
from ladderide.verify.esp32 import ERROR, OK, SKIP, WARN, BoardProfile

DEMO = ROOT / "examples" / "ambientes" / "portao.ladproj"


def statuses(rep):
    return {c.title: c.status for c in rep.checks}


def test_board_profile_is_read_from_firmware_config():
    b = BoardProfile.load()
    assert (b.inputs, b.outputs, b.scan_period_ms, b.watchdog_us) == (8, 8, 10, 50000)
    assert b.source.endswith("board_config.h")


def test_valid_program_passes_all_offline_checks(c_vm):  # c_vm: pula sem gcc
    p = Project.load(DEMO)
    rep = verify_for_esp32(p, compile_project(p))
    st = statuses(rep)
    assert rep.ok and not rep.errors
    assert st["Validacao pelo codigo C do firmware"] == OK
    assert st["Equivalencia simulador x firmware"] == OK and rep.scans_compared == 400
    assert st["Dispositivo conectado"] == SKIP          # nada medido sem placa


def test_addresses_beyond_the_board_are_errors():
    p = Project(rungs=[Rung([Contact("XIC", "I1.0")], [Coil("OTE", "Q1.1")])])
    p.io.n_inputs = p.io.n_outputs = 16
    rep = verify_for_esp32(p, compile_project(p))
    assert statuses(rep)["Entradas e saidas da placa"] == ERROR
    assert "I1.0" in rep.as_text() and "Q1.1" in rep.as_text()
    assert not rep.ok


def test_timing_warnings():
    p = Project(rungs=[Rung([Contact("XIC", "I0.0")], [TimerBox("TON", "T0", 15)])])
    p.io.scan_period_ms = 20
    rep = verify_for_esp32(p, compile_project(p))
    st = statuses(rep)
    assert st["Periodo de varredura"] == WARN and st["Resolucao dos temporizadores"] == WARN
    assert rep.ok                                        # avisos nao bloqueiam


def test_divergence_between_vms_is_reported(monkeypatch):
    p = Project.load(DEMO)
    real = esp32.firmware_trace

    def corrupted(image, seq):
        status, lines = real(image, seq)
        lines[37] = lines[37].replace("Q=", "Q=f")
        return status, lines
    monkeypatch.setattr(esp32, "firmware_trace", corrupted)
    rep = verify_for_esp32(p, compile_project(p))
    assert statuses(rep)["Equivalencia simulador x firmware"] == ERROR
    assert "varredura 37" in rep.as_text()


def test_missing_c_compiler_is_reported_as_not_verified(monkeypatch):
    def no_gcc(image, seq):
        raise BuildError("compilador C 'gcc' nao encontrado")
    monkeypatch.setattr(esp32, "firmware_trace", no_gcc)
    p = Project.load(DEMO)
    rep = verify_for_esp32(p, compile_project(p))
    assert statuses(rep)["Validacao pelo codigo C do firmware"] == SKIP and rep.ok


def test_device_measurements_are_checked_against_watchdog():
    p = Project.load(DEMO)
    r = compile_project(p)
    info = SimpleNamespace(fmt_major=1, fmt_minor=0, n_inputs=8, n_outputs=8, max_image=8740,
                           firmware="1.0.0", hardware="x")
    ok = SimpleNamespace(has_program=True, build_id=r.build_id, scan_count=100, last_exec_us=120,
                         max_exec_us=180, overruns=0)
    slow = SimpleNamespace(**{**vars(ok), "max_exec_us": 60000})
    assert statuses(verify_for_esp32(p, r, device_info=info, device_status=ok))[
        "Tempo de varredura medido no dispositivo"] == OK
    rep = verify_for_esp32(p, r, device_info=info, device_status=slow)
    assert statuses(rep)["Tempo de varredura medido no dispositivo"] == ERROR
    old = SimpleNamespace(**{**vars(info), "fmt_major": 2})
    assert statuses(verify_for_esp32(p, r, device_info=old))["Compatibilidade com o dispositivo"] == ERROR


def test_il_blocks_follow_rungs_and_branches():
    p = Project(rungs=[
        Rung([Parallel([[Contact("XIC", "Partida")], [Contact("XIC", "Q0.0")]]), Contact("XIO", "I0.1")],
             [Coil("OTE", "Q0.0")], "Selo"),
        Rung([Contact("XIC", "Q0.0")], [TimerBox("TON", "T0", 2000)]),
    ])
    from ladderide.model import Symbol
    p.symbols = [Symbol("Partida", "I0.0"), Symbol("Motor", "Q0.0"), Symbol("Atraso", "T0")]
    r = compile_project(p)
    blocks = il_blocks(p, r)
    assert [b.rung for b in blocks] == [0, 1] and blocks[0].comment == "Selo"
    flat = [ln for b in blocks for ln in b.lines]
    assert [ln.pc for ln in flat] == list(range(len(r.program.code)))      # todas, na ordem do ESP32
    xic = next(ln for ln in flat if ln.operand == "I0.0")
    assert xic.mnemonic == "XIC" and xic.symbol == "Partida" and xic.depth == 1
    assert xic.element_id == p.rungs[0].condition[0].branches[0][0].id
    ton = next(ln for ln in flat if ln.mnemonic == "TON")
    assert ton.symbol == "Atraso" and "PRE 2000 ms" in ton.description
    text = il_text(blocks)
    assert "// ===== Rede 0 - Selo =====" in text and "XIC  I0.0" in text


def test_il_blocks_need_a_valid_program():
    p = Project(rungs=[Rung([Contact("XIC", "Inexistente")], [Coil("OTE", "Q0.0")])])
    assert il_blocks(p, compile_project(p)) == []
