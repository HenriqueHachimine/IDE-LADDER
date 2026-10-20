"""Testes da interface em modo offscreen (sem janela visivel)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import ROOT  # noqa: E402
from ladderide.model import Coil, Contact, Parallel, Project, TimerBox  # noqa: E402
from ladderide.ui import main_window as mw  # noqa: E402
from ladderide.ui.layout import build_layout  # noqa: E402

DEMO = ROOT / "examples" / "demo" / "demonstracao.ladproj"


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, monkeypatch):
    monkeypatch.setattr(mw.ElementDialog, "exec", lambda self: 0)   # nao abre dialogos modais
    w = mw.MainWindow()
    w.dirty = False
    yield w
    w.dirty = False
    w.close()


def test_layout_slots_and_power_keys():
    p = Project.load(DEMO)
    lay = build_layout(p)
    assert len(lay.rungs) == len(p.rungs)
    first = p.rungs[0]
    par = first.condition[0]
    keys = {w.key for w in lay.wires}
    assert ("bnd", par.id) in keys and ("rail",) in keys
    # ha slot de condicao dentro de cada ramo e na coluna de saidas
    assert any(s.container is par.branches[1] for s in lay.slots)
    assert any(s.kind == "out" and s.container is first.outputs for s in lay.slots)
    assert lay.slot_at(-0.5, lay.height - 1.2, "cond").kind == "newrung"


def test_build_program_by_clicks_and_simulate(window):
    w = window
    w.tool_clicked("XIC")
    w.tool_clicked("XIO")
    w.tool_clicked("OTE")
    rung = w.project.rungs[0]
    assert [type(n) for n in rung.condition] == [Contact, Contact] and isinstance(rung.outputs[0], Coil)
    rung.condition[1].operand = "I0.1"
    assert w.compile(), [str(d) for d in w.result.diagnostics]
    w.sim_run()
    w.on_input(0, True)
    w.sim.advance(30)
    assert w.sim.vm.q[0]
    assert w.view.readonly and not w.actions_["delete"].isEnabled()
    w.on_input(1, True)
    w.sim.advance(30)
    assert not w.sim.vm.q[0]
    w.sim_stop()
    assert not w.view.readonly


def test_drop_tools_into_slots(window):
    w = window
    lay = w.view.layout_
    cond_slot = lay.slot_at(0.3, 0.5, "cond")
    w.on_drop("tool", "XIC", cond_slot)
    out_slot = lay.slot_at(lay.out_x + 0.5, 0.5, "out")
    w.on_drop("tool", "TON", out_slot)
    rung = w.project.rungs[0]
    assert isinstance(rung.condition[0], Contact) and isinstance(rung.outputs[0], TimerBox)
    # paralelo em volta do contato e novo contato no ramo vazio
    w.on_view_action("wrap", rung.condition[0].id)
    par = w.project.rungs[0].condition[0]
    assert isinstance(par, Parallel)
    empty_branch_slot = next(s for s in w.view.layout_.slots if s.container is par.branches[1])
    w.on_drop("tool", "XIO", empty_branch_slot)
    assert isinstance(w.project.rungs[0].condition[0].branches[1][0], Contact)
    # solta em "nova rede"
    new_slot = next(s for s in w.view.layout_.slots if s.kind == "newrung")
    w.on_drop("tool", "OTE", new_slot)
    assert len(w.project.rungs) == 2 and isinstance(w.project.rungs[1].outputs[0], Coil)
    # tipo errado no destino nao altera o projeto
    before = w.project.to_dict()["rungs"]
    w.on_drop("tool", "OTE", next(s for s in w.view.layout_.slots if s.kind == "cond" and s.priority == 3))
    assert w.project.to_dict()["rungs"] == before


def test_move_undo_redo(window):
    w = window
    w.tool_clicked("XIC")
    w.tool_clicked("XIO")
    w.tool_clicked("OTE")
    a, b = w.project.rungs[0].condition
    slot = next(s for s in w.view.layout_.slots
                if s.container is w.project.rungs[0].condition and s.index == 0 and s.priority == 3)
    w.on_drop("move", b.id, slot)
    assert [n.kind for n in w.project.rungs[0].condition] == ["XIO", "XIC"]
    w.undo()
    assert [n.kind for n in w.project.rungs[0].condition] == ["XIC", "XIO"]
    w.redo()
    assert [n.kind for n in w.project.rungs[0].condition] == ["XIO", "XIC"]
    w.view.select(w.project.rungs[0].condition[0].id)
    w.delete_selected()
    assert len(w.project.rungs[0].condition) == 1


def test_open_demo_compile_and_step(window, tmp_path):
    w = window
    w.file_open(str(DEMO))
    assert w.compile()
    w.sim_step()
    w.sim_step()
    assert w.sim.vm.pc == 2 and w.view.items_by_id[w.sim.current_element].current
    w.sim_scan()
    assert w.sim.vm.scan_count == 1
    w.sim_stop()
    out = tmp_path / "copia.ladproj"
    w.path = str(out)
    assert w.file_save() and out.exists()


def test_compile_error_highlights_element(window):
    w = window
    w.tool_clicked("XIC")
    w.tool_clicked("OTE")
    bad = w.project.rungs[0].condition[0]
    bad.operand = "NaoExiste"
    assert not w.compile()
    assert w.view.items_by_id[bad.id].has_error
    item = w.messages.item(0)
    w.on_message(item)
    assert w.view.selection == bad.id


def test_speed_shortcuts_change_simulation_speed(window):
    w = window
    panel = w.sim_panel
    assert panel.speed_factor == 1.0
    w.actions_["sim_faster"].trigger()
    w.actions_["sim_faster"].trigger()
    assert panel.speed_factor == 5.0
    for _ in range(20):
        w.actions_["sim_faster"].trigger()
    assert panel.speed_factor == float("inf")
    w.actions_["sim_slower"].trigger()
    assert panel.speed_factor == 100.0
    w.actions_["sim_realtime"].trigger()
    assert panel.speed_factor == 1.0
    w.tool_clicked("XIC")
    w.tool_clicked("OTE")
    assert w.compile()
    w.sim_run()
    panel.set_speed(20.0)
    w.sim.advance(100, panel.speed_factor)
    panel.refresh(w.sim)
    assert w.sim.virtual_ms >= 1990 and panel.real_speed.text().startswith("20")
    w.sim_stop()


def test_speed_can_be_typed_or_dragged_and_stays_in_sync(window):
    w = window
    model = w.sim_panel.speed_model
    w.toolbar_speed.lineEdit().setText("3,5x")
    w.toolbar_speed.lineEdit().editingFinished.emit()
    assert model.value == 3.5 and w.sim_panel.speed.currentText() == "3,5x"
    w.sim_panel.speed.lineEdit().setText("banana")              # invalido: volta ao valor atual
    w.sim_panel.speed.lineEdit().editingFinished.emit()
    assert model.value == 3.5 and w.sim_panel.speed.currentText() == "3,5x"
    w.sim_panel.speed.lineEdit().setText("max")
    w.sim_panel.speed.lineEdit().editingFinished.emit()
    assert model.value == float("inf") and w.toolbar_speed.currentText() == "Maxima"
    slider = w.sim_panel.speed_slider
    slider.slider.setValue(slider.position(1.0))
    assert model.value == 1.0 and w.toolbar_speed.currentText() == "1x (tempo real)"
    slider.slider.setValue(slider.STEPS)
    assert model.value == 100.0
    model.set(7.0)                                             # entre predefinicoes: atalhos seguem
    w.actions_["sim_faster"].trigger()
    assert model.value == 10.0
    model.set(7.0)
    w.actions_["sim_slower"].trigger()
    assert model.value == 5.0
