"""Controlador do CLP escolhido no projeto: limita E/S e quantidade de variaveis."""
from __future__ import annotations

import json
import os

import pytest

from ladderide.compiler import compile_project
from ladderide.core import isa
from ladderide.model import controllers
from ladderide.model.controllers import apply_controller, controller_by_id, default_controller, load_controllers
from ladderide.model.project import Coil, Contact, Project, Rung, TimerBox


def test_builtin_controllers_respect_isa_limits():
    items = {c.id: c for c in load_controllers()}
    assert {"esp32-relay-x8", "simulacao-16", "personalizado"} <= set(items)
    board = items["esp32-relay-x8"]
    assert (board.inputs, board.outputs, board.hardware) == (8, 8, True)
    assert default_controller().id == "esp32-relay-x8"
    for c in items.values():
        assert c.inputs <= isa.IDE_MAX_INPUTS and c.outputs <= isa.MAX_OUTPUTS and c.words <= isa.MAX_WORDS
        if c.hardware or c.board:                         # placas reais/simuladas: limite do protocolo
            assert c.inputs <= isa.MAX_INPUTS


def test_user_controller_file_adds_and_limits(tmp_path, monkeypatch):
    path = tmp_path / "controladores.json"
    path.write_text(json.dumps({"controllers": [
        {"id": "didatico", "name": "Didatico", "inputs": 4, "outputs": 2, "markers": 8, "timers": 2,
         "counters": 1, "words": 4},
        {"id": "exagerado", "name": "Exagerado", "inputs": 99, "outputs": 99, "words": 1000}]}), encoding="utf-8")
    monkeypatch.setattr(controllers, "USER_PATH", path)
    small = controller_by_id("didatico")
    assert (small.inputs, small.outputs, small.timers, small.source) == (4, 2, 2, str(path))
    big = controller_by_id("exagerado")
    assert (big.inputs, big.outputs, big.words) == (isa.IDE_MAX_INPUTS, isa.MAX_OUTPUTS, isa.MAX_WORDS)

    p = Project()
    apply_controller(p, small)
    assert (p.io.n_inputs, p.io.n_outputs, p.io.n_markers, p.io.n_words, p.target.device) == (4, 2, 8, 4, "didatico")
    p.rungs = [Rung([Contact("XIC", "I0.0")], [TimerBox("TON", "T1", 100)]),
               Rung([Contact("XIC", "T1.DN")], [Coil("OTE", "Q0.1")])]
    assert compile_project(p).ok
    p.rungs[0].outputs[0].operand = "T2"                  # o controlador so tem T0 e T1
    p.rungs[1].condition[0].operand = "T2.DN"
    assert any("limite 2" in str(d) for d in compile_project(p).errors)
    p.rungs[0].outputs[0].operand = "T1"
    p.rungs[1].condition[0].operand = "T1.DN"
    p.io.n_inputs = 8                                     # editado a mao acima do limite
    errors = [str(d) for d in compile_project(p).errors]
    assert any("tem 4 entradas" in e for e in errors), errors


def test_switching_controller_only_shrinks():
    p = Project()
    apply_controller(p, controller_by_id("simulacao-16"))
    assert (p.io.n_inputs, p.io.n_outputs) == (16, 16)
    p.io.safe_outputs = 0xFFFF
    apply_controller(p, controller_by_id("esp32-relay-x8"), fill=False)
    assert (p.io.n_inputs, p.io.n_outputs, p.io.safe_outputs) == (8, 8, 0xFF)


def test_unknown_controller_is_a_warning():
    p = Project()
    p.target.device = "nao-existe"
    p.rungs = [Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")])]
    r = compile_project(p)
    assert r.ok and any("controlador desconhecido" in str(d) for d in r.warnings)


def test_new_project_dialog_applies_the_chosen_controller(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.dialogs import NewProjectDialog, ProjectDialog
    QApplication.instance() or QApplication([])
    dlg = NewProjectDialog()
    assert dlg.selected_id() == "esp32-relay-x8" and "8 entradas" in dlg.details.text()
    assert dlg.select("simulacao-16")
    dlg.name.setText("Estudo")
    p = dlg.project()
    assert (p.name, p.target.device, p.io.n_inputs, p.io.n_outputs) == ("Estudo", "simulacao-16", 16, 16)

    props = ProjectDialog(p)
    props.controller.setCurrentIndex(props.controller.findData("esp32-relay-x8"))
    assert props.n_inputs.maximum() == 8 and props.n_inputs.value() == 8      # reduzido ao limite
    props.apply()
    assert (p.target.device, p.io.n_inputs, p.io.n_outputs) == ("esp32-relay-x8", 8, 8)


SLC = [("1747-L553", "5/05", 64, "OS500"), ("1747-L552", "5/05", 32, "OS500"), ("1747-L551", "5/05", 16, "OS500"),
       ("1747-L543", "5/04", 64, "OS401"), ("1747-L542B", "5/04", 32, "OS401"), ("1747-L541", "5/04", 16, "OS401"),
       ("1747-L542A", "5/04", 24, "OS400"), ("1747-L532C/D", "5/03", 16, "OS302"), ("1747-L531", "5/03", 8, "OS302"),
       ("1747-L532B", "5/03", 16, "OS301"), ("1747-L532", "5/03", 16, "OS300"), ("1747-L524", "5/02", 4, ""),
       ("1747-L514", "5/01", 4, ""), ("1747-L511", "5/01", 1, "")]


def _scaled(c):
    k = c.memory_k
    return (max(64, 32 * k), max(16, 4 * k), max(16, 4 * k), max(4, k // 2), max(4, k // 2), max(4, k))


def test_slc500_processors_scale_with_memory():
    slc = [c for c in load_controllers() if c.family == "Allen-Bradley SLC 500 modular"]
    assert [(c.catalog, c.cpu, c.memory_k, c.os) for c in slc] == SLC
    io = {"5/05": 16, "5/04": 12, "5/03": 8, "5/02": 8, "5/01": 8}
    for c in slc:
        assert (c.inputs, c.outputs) == (io[c.cpu], io[c.cpu])
        assert (c.instructions, c.rungs, c.markers, c.timers, c.counters, c.words) == _scaled(c)
        assert c.ports and not c.hardware and c.memory_text == f"{c.memory_k}K Mem."
    big = controller_by_id("1747-l553")
    assert (big.instructions, big.rungs, big.spec) == (isa.MAX_INSTRUCTIONS, isa.MAX_RUNGS, "5/05 CPU 64K Mem. OS500")
    tiny = controller_by_id("1747-l511")                  # 1K: minimo utilizavel
    assert (tiny.instructions, tiny.rungs, tiny.timers) == (64, 16, 4)


def test_fixed_slc500_and_micrologix_have_their_io():
    items = load_controllers()
    fixed = {c.catalog: c for c in items if c.family == "Allen-Bradley SLC 500 fixo"}
    assert len(fixed) == 20
    assert fixed["1747-L20R"].spec == "12-240 VAC In, 8-RLY Out"
    assert (fixed["1747-L20A"].inputs, fixed["1747-L20A"].outputs) == (12, 8)
    assert (fixed["1747-L30L"].inputs, fixed["1747-L30L"].outputs) == (18, 12)
    assert fixed["1747-L40E"].spec == "24-DC SNK In, 16-TRANS SRC Out"
    assert (fixed["1747-L40E"].inputs, fixed["1747-L40E"].outputs) == (24, 16)
    micro = [c for c in items if c.family == "Allen-Bradley MicroLogix 1000"]
    assert [c.spec for c in micro] == ["MicroLogix1000 Analog", "MicroLogix1000 DH-485/HDSlave", "MicroLogix1000"]
    assert all(c.catalog == "Bul.1761" for c in micro) and len({c.id for c in micro}) == 3
    assert (micro[0].inputs, micro[2].inputs, micro[2].outputs) == (20, 10, 6)
    for c in items:
        assert c.inputs <= isa.IDE_MAX_INPUTS and c.outputs <= isa.MAX_OUTPUTS
        assert c.instructions <= isa.MAX_INSTRUCTIONS and c.rungs <= isa.MAX_RUNGS


def test_arduino_controllers_match_the_board_profiles():
    from ladderide.comm.board_profiles import PROFILES
    for cid, board in (("arduino-uno", "arduino-uno"), ("arduino-mega", "arduino-mega"),
                       ("esp32-relay-x8", "esp32-relay")):
        c = controller_by_id(cid)
        profile = PROFILES[board]
        assert c.board == board and (c.inputs, c.outputs) == (profile.n_inputs, profile.max_relays)
    uno = controller_by_id("arduino-uno")
    assert uno.family == "Arduino" and uno.instructions < isa.MAX_INSTRUCTIONS and "D2 a D9" in uno.description


def test_program_memory_of_the_processor_is_enforced():
    small = controller_by_id("1747-l531")                 # 8K: 32 redes, 256 instrucoes
    p = Project()
    apply_controller(p, small)
    assert (p.io.n_inputs, p.io.n_outputs, p.io.n_markers, p.io.n_words) == (8, 8, 32, 8)
    p.rungs = [Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")]) for _ in range(small.rungs)]
    assert compile_project(p).ok
    p.rungs.append(Rung([Contact("XIC", "I0.1")], [Coil("OTE", "Q0.1")]))
    errors = [str(d) for d in compile_project(p).errors]
    assert any("redes demais no 1747-L531" in e for e in errors), errors
    p.rungs = [Rung([Contact("XIC", f"I0.{k % 8}") for k in range(8)], [Coil("OTE", "Q0.0")]) for _ in range(30)]
    errors = [str(d) for d in compile_project(p).errors]
    assert any("memória de programa esgotada no 1747-L531" in e for e in errors), errors
    apply_controller(p, controller_by_id("1747-l553"), fill=False)
    assert compile_project(p).ok                          # 64K comporta o mesmo programa


def test_new_project_dialog_lists_processors_by_family():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.dialogs import NewProjectDialog
    QApplication.instance() or QApplication([])
    dlg = NewProjectDialog()
    groups = [dlg.list.topLevelItem(k).text(0) for k in range(dlg.list.topLevelItemCount())]
    assert groups == ["Placa do projeto e simulação", "Arduino", "Allen-Bradley SLC 500 modular",
                      "Allen-Bradley MicroLogix 1000", "Allen-Bradley SLC 500 fixo"]
    rows = {r.text(0): r.text(1) for r in dlg._rows()}
    assert rows["1747-L553"] == "5/05 CPU 64K Mem. OS500" and rows["1747-L511"] == "5/01 CPU 1K Mem."
    assert rows["1747-L40P"] == "24-230 VAC In, 16-Triac Out"
    assert dlg.select("1747-l531")
    assert "DH-485" in dlg.details.text() and "256 instruções" in dlg.details.text()
    p = dlg.project()
    assert (p.target.device, p.io.n_inputs, p.io.n_outputs, p.io.n_markers) == ("1747-l531", 8, 8, 32)
    dlg.list.setCurrentItem(dlg.list.topLevelItem(1))     # cabecalho de grupo: nada escolhido
    assert dlg.selected_id() is None or dlg.selected_id() == "1747-l531"


def test_controller_with_24_inputs_simulates_but_board_refuses():
    from ladderide.codegen.cpp import generate_cpp
    from ladderide.core.image import ImageValidationError, decode
    from ladderide.envs import EnvironmentPlant, create
    from ladderide.sim.simulator import Simulator
    p = Project()
    apply_controller(p, controller_by_id("1747-l40a"))
    assert (p.io.n_inputs, p.io.n_outputs) == (24, 16)
    p.rungs = [Rung([Contact("XIC", "I2.7")], [Coil("OTE", "Q1.7")])]
    r = compile_project(p)
    assert r.ok, [str(d) for d in r.diagnostics]
    with pytest.raises(ImageValidationError):
        decode(r.image)                                   # validacao da placa/protocolo: ate 16
    env = create("simulador_es")
    sim = Simulator(r, 10)
    sim.attach_plant(EnvironmentPlant(env))
    env.configure(24, 16, p.io.n_words)
    sim.attach_plant(EnvironmentPlant(env))
    sim.start()
    env.press("T23", True)                                # pulsador NA -> NF: le 1 solto
    sim.scan_once()
    assert len(env.inputs) == 24 and sim.vm.outputs >> 15 & 1
    code = generate_cpp(p).text
    assert "plc_scan(uint32_t inputs" in code


def test_properties_switching_controller_takes_its_io():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.dialogs import ProjectDialog
    QApplication.instance() or QApplication([])
    p = Project()
    apply_controller(p, controller_by_id("esp32-relay-x8"))
    dlg = ProjectDialog(p)
    assert dlg.n_inputs.value() == 8                      # abrir nao muda nada
    dlg.controller.setCurrentIndex(dlg.controller.findData("1747-l40a"))
    assert (dlg.n_inputs.value(), dlg.n_outputs.value()) == (24, 16)
    dlg.controller.setCurrentIndex(dlg.controller.findData("1747-l553"))
    assert (dlg.n_inputs.value(), dlg.n_outputs.value()) == (16, 16)
    dlg.apply()
    assert (p.target.device, p.io.n_inputs, p.io.n_outputs) == ("1747-l553", 16, 16)


def test_project_io_always_matches_the_controller():
    from ladderide.model.controllers import match_controller_io
    p = Project()
    apply_controller(p, controller_by_id("1747-l553"))
    p.io.n_inputs, p.io.n_outputs, p.io.safe_outputs = 8, 8, 0xFF     # salvo antes, com menos E/S
    assert match_controller_io(p) and (p.io.n_inputs, p.io.n_outputs) == (16, 16)
    assert not match_controller_io(p)
    apply_controller(p, controller_by_id("personalizado"))
    p.io.n_inputs = 5
    assert not match_controller_io(p) and p.io.n_inputs == 5             # Personalizado: escolha livre


def test_properties_lock_io_to_the_controller():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.dialogs import ProjectDialog
    QApplication.instance() or QApplication([])
    p = Project()
    apply_controller(p, controller_by_id("1747-l542a"))
    p.io.n_inputs = 4                                                      # projeto antigo
    dlg = ProjectDialog(p)
    assert (dlg.n_inputs.value(), dlg.n_outputs.value()) == (12, 12) and not dlg.n_inputs.isEnabled()
    dlg.controller.setCurrentIndex(dlg.controller.findData("personalizado"))
    assert dlg.n_inputs.isEnabled()
