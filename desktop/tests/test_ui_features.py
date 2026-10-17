"""Interface: ambiente de simulacao, blocos de instrucao e verificacao para o ESP32."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import ROOT  # noqa: E402
from ladderide.ui import main_window as mw  # noqa: E402

PORTAO = ROOT / "examples" / "ambientes" / "portao.ladproj"


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Discard)
    w = mw.MainWindow()
    w.show()
    yield app, w
    w.dirty = False
    w.session.close()
    w.close()


def test_project_environment_drives_simulation(window):
    app, w = window
    w.file_open(str(PORTAO))
    assert w.env_panel.env is not None and w.env_panel.env.id == "portao"
    w.sim_run()
    io = w.sim_panel.io
    assert not io.input_buttons[3].isEnabled()           # LS1 pertence ao ambiente
    assert io.input_buttons[6].isEnabled()               # I0.6 livre continua no painel
    env = w.env_panel.env
    env.press("OPEN", True)
    for _ in range(20):
        w.sim.scan_once()
    env.press("OPEN", False)
    for _ in range(100):
        w.sim.scan_once()
    w._update_live()
    assert env.pos > 5 and w.sim.vm.outputs & 1          # motor subindo
    assert w.env_panel.table.item(6, 3).text() == "1"    # Q0.0 na tabela do ambiente
    w.sim_stop()


def test_changing_environment_marks_project_and_adds_symbols(window):
    app, w = window
    idx = w.env_panel.combo.findData("silo")
    w.env_panel.combo.setCurrentIndex(idx)
    assert w.project.environment == "silo" and w.dirty
    w.add_environment_symbols()
    names = {s.name for s in w.project.symbols}
    assert {"Start", "Stop", "Sensor_Presenca", "Valvula"} <= names
    w.undo()
    assert not any(s.name == "Valvula" for s in w.project.symbols)


def test_il_blocks_panel_syncs_with_diagram(window):
    app, w = window
    w.file_open(str(PORTAO))
    w.show_il_blocks()
    app.processEvents()
    panel = w.il_panel
    assert panel.tree.topLevelItemCount() == len(w.project.rungs)
    assert "Rede 0" in panel.tree.topLevelItem(0).text(0)
    contact = w.project.rungs[1].condition[1]
    w.view.select(contact.id)
    assert [it.text(1).strip() for it in panel.tree.selectedItems()] == ["XIC"]
    panel._clicked(panel.items_by_element[w.project.rungs[0].outputs[0].id][0])
    assert w.view.selection == w.project.rungs[0].outputs[0].id
    w.sim_run()
    w.sim.scan_once()
    w._update_live()
    assert panel._last_power is not None


def test_verify_action_opens_report(window, monkeypatch):
    app, w = window
    w.file_open(str(PORTAO))
    shown = []
    monkeypatch.setattr(mw.VerifyDialog, "exec", lambda self: shown.append(self.report))
    w.verify_esp32()
    assert shown and shown[0].ok
    assert w.result is not None and w.result.ok


def test_dark_theme_switches_at_runtime(window, monkeypatch):
    from ladderide.ui import symbols, theme
    app, w = window
    saved = []
    monkeypatch.setattr(theme, "save_mode", saved.append)     # nao grava preferencia do usuario
    w.file_open(str(PORTAO))
    light_label = symbols.LABEL.name()
    try:
        w.set_theme("dark")
        assert theme.is_dark() and saved == ["dark"]
        assert w.theme_actions["dark"].isChecked()
        assert symbols.LABEL.name() != light_label                # cores compartilhadas mudam no lugar
        assert theme.colors["BG"] in app.styleSheet()
        assert w.view.items_by_id                                  # cena reconstruida
        w.toggle_theme()
        assert not theme.is_dark() and symbols.LABEL.name() == light_label
    finally:
        theme.apply_theme(app, "light")
