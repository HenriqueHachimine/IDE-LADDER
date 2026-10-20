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


def test_cpp_panel_shows_code_before_compiling(window):
    from PySide6.QtGui import QTextCursor
    app, w = window
    w.file_open(str(PORTAO))
    assert w.result is None                                     # nada compilado ainda
    w.show_cpp()
    app.processEvents()
    panel = w.cpp_panel
    assert "uint16_t plc_scan(" in panel.text and "// ===== Rede 0" in panel.text
    assert panel.code.errors == 0
    # editar o diagrama atualiza o C++ na hora, sem compilar
    contact = next(n for _, n, _ in w.project.walk() if hasattr(n, "operand") and n.kind == "XIC")
    old = contact.operand
    contact.operand = "Nao_Existe"
    w.modified()
    assert "// ERRO: variavel nao declarada: Nao_Existe" in panel.text
    contact.operand = old
    w.modified()
    assert "ERRO" not in panel.text
    # diagrama -> codigo: a rede do elemento selecionado fica destacada
    w.view.select(w.project.rungs[1].outputs[0].id)
    sel = panel.editor.extraSelections()
    doc = panel.editor.document()
    lines = (doc.findBlock(sel[0].cursor.selectionStart()).blockNumber(),
             doc.findBlock(sel[0].cursor.selectionEnd()).blockNumber())
    assert lines == panel.code.rung_lines[1]
    # codigo -> diagrama: clicar numa linha seleciona a rede correspondente
    first, _ = panel.code.rung_lines[2]
    panel.editor.setTextCursor(QTextCursor(panel.editor.document().findBlockByNumber(first + 1)))
    assert w.view.selection == panel.code.rung_first_element[2]


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


def test_layout_fits_laptop_screen_and_follows_work_mode(window):
    app, w = window
    assert w.minimumSizeHint().height() <= 700                  # cabe em 1366x768
    buttons = [tb.widgetForAction(act) for tb in w.toolbars for act in tb.actions() if not act.isSeparator()]
    texts = [b for b in buttons if isinstance(b, mw.QToolButton) and b.toolButtonStyle() == mw.Qt.ToolButtonTextBesideIcon]
    assert len(texts) == 6                                      # demais acoes: so icone (cabe em 1366 px)
    assert w.env_dock.objectName() == "dock_env" and w.dockWidgetArea(w.env_dock) == mw.Qt.BottomDockWidgetArea
    w.file_open(str(PORTAO))
    assert w.status_mode.text() == "EDICAO" and w.palette_dock.isVisible()
    w.sim_run()
    assert w.status_mode.text() == "SIMULACAO" and not w.palette_dock.isVisible()
    w.sim_stop()
    w._update_actions()
    assert w.status_mode.text() == "EDICAO" and w.palette_dock.isVisible()
    menu = [a.text() for a in w.device_menu.actions()]
    assert "Verificar para ESP32" in menu and "Monitor online" in menu
    assert not w.actions_["dev_run"].isEnabled()                 # sem dispositivo conectado
    assert w.status_device.text() == "ESP32: desconectado"
    w.palette_dock.hide()
    w.reset_layout()
    assert w.palette_dock.isVisible()


def test_layout_lock_freezes_panels_and_persists(window, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDockWidget
    app, w = window
    w.resize(1400, 860)
    app.processEvents()
    ini = str(tmp_path / "ladderide.ini")
    monkeypatch.setattr(mw.MainWindow, "_settings", lambda self: QSettings(ini, QSettings.IniFormat))

    w.actions_["layout_lock"].trigger()                       # trava pelo menu/cadeado
    assert w.layout_locked and w.actions_["layout_lock"].isChecked()
    assert all(d.features() == QDockWidget.NoDockWidgetFeatures for d in w._docks())
    assert not any(tb.isMovable() for tb in w.toolbars)
    assert not w.palette_dock.toggleViewAction().isEnabled()
    assert not w.actions_["layout_reset"].isEnabled()
    assert w.sim_dock.minimumWidth() == w.sim_dock.maximumWidth() == w.sim_dock.width()
    height = w.msgs_dock.height()
    w.resizeDocks([w.msgs_dock], [height + 80], mw.Qt.Vertical)  # divisoria/redimensionamento sem efeito
    app.processEvents()
    assert w.msgs_dock.height() == height

    w.set_layout_locked(False)
    assert all(d.features() == mw.MainWindow.DOCK_FEATURES for d in w._docks())
    assert all(tb.isMovable() for tb in w.toolbars)
    assert w.sim_dock.minimumWidth() < w.sim_dock.maximumWidth()
    w.resizeDocks([w.msgs_dock], [height + 80], mw.Qt.Vertical)
    app.processEvents()
    assert w.msgs_dock.height() > height                         # destravado volta a redimensionar

    w.persist_layout = True                                   # grava a preferencia e o layout
    w.set_layout_locked(True)
    w.dirty = False
    w.session.close()
    w2 = mw.MainWindow(persist_layout=True)
    try:
        assert w2.layout_locked and w2.actions_["layout_lock"].isChecked()
    finally:
        w2.session.close()
        w2.persist_layout = False
        w2.close()
    w.persist_layout = False


def test_compare_and_math_blocks_from_palette_show_live_values(window, monkeypatch):
    """Blocos da paleta: comparacao na condicao, matematica nas saidas, valores na simulacao."""
    from ladderide.model.project import CompareBox, Contact, MathBox, Project
    from ladderide.ui import dialogs
    app, w = window
    monkeypatch.setattr(dialogs.ElementDialog, "exec", lambda self: True)   # aceita o padrao
    w.set_project(Project(name="blocos"), None)
    rung = w.project.rungs[0]
    w.view.select(("rung", 0))
    w.tool_clicked("XIC")                                 # I0.0
    w.tool_clicked("ADD")                                 # N0 = N0 + 1
    w.view.select(rung.condition[0].id)
    w.tool_clicked("GRT")                                 # N0 > 0, depois do contato
    assert [type(n) for n in rung.condition] == [Contact, CompareBox]
    assert isinstance(rung.outputs[0], MathBox) and rung.outputs[0].operands == ["N0", "1", "N0"]
    rung.condition[1].operands = ["N0", "-1"]              # sempre verdadeiro com N0 >= 0
    assert w.compile()
    w.sim_run()
    w.sim.set_input(0, True)
    for _ in range(4):
        w.sim.scan_once()
    w._update_live()
    item = w.view.items_by_id[rung.outputs[0].id]
    assert item.state.rows[0] == ("A", "N0=4") and item.state.rows[2] == ("→", "N0=4")
    assert w.view.items_by_id[rung.condition[1].id].state.power_out is True
    names = [w.sim_panel.io.variables.item(r, 1).text() for r in range(w.sim_panel.io.variables.rowCount())]
    values = [w.sim_panel.io.variables.item(r, 2).text() for r in range(w.sim_panel.io.variables.rowCount())]
    assert values[names.index("N0")] == "4"
    w.sim_stop()
