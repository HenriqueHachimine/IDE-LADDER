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
        assert c.inputs <= isa.MAX_INPUTS and c.outputs <= isa.MAX_OUTPUTS and c.words <= isa.MAX_WORDS


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
    assert (big.inputs, big.outputs, big.words) == (isa.MAX_INPUTS, isa.MAX_OUTPUTS, isa.MAX_WORDS)

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
    assert dlg.controller.currentData() == "esp32-relay-x8" and "8 entradas" in dlg.details.text()
    dlg.controller.setCurrentIndex(dlg.controller.findData("simulacao-16"))
    dlg.name.setText("Estudo")
    p = dlg.project()
    assert (p.name, p.target.device, p.io.n_inputs, p.io.n_outputs) == ("Estudo", "simulacao-16", 16, 16)

    props = ProjectDialog(p)
    props.controller.setCurrentIndex(props.controller.findData("esp32-relay-x8"))
    assert props.n_inputs.maximum() == 8 and props.n_inputs.value() == 8      # reduzido ao limite
    props.apply()
    assert (p.target.device, p.io.n_inputs, p.io.n_outputs) == ("esp32-relay-x8", 8, 8)
