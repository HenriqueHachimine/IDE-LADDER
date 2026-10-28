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
    assert "// ERRO: variável não declarada: Nao_Existe" in panel.text
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
    assert w.env_dock.objectName() == "dock_process" and w.dockWidgetArea(w.env_dock) == mw.Qt.BottomDockWidgetArea
    w.file_open(str(PORTAO))
    assert w.status_mode.text() == "EDIÇÃO" and w.palette_dock.isVisible()
    w.sim_run()
    assert w.status_mode.text() == "SIMULAÇÃO" and not w.palette_dock.isVisible()
    w.sim_stop()
    w._update_actions()
    assert w.status_mode.text() == "EDIÇÃO" and w.palette_dock.isVisible()
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


def test_process_panel_shows_one_process_at_a_time(window):
    """Ambiente, Factory IO e Placa ficam num painel so, com seletor: um processo por vez."""
    app, w = window
    panel = w.process_panel
    assert w.env_dock is w.fio_dock is w.esp32_dock is w.process_dock
    for show, key in ((w.show_factoryio, "fio"), (w.show_esp32, "board"), (w.show_environment, "env")):
        show()
        assert panel.current == key and panel.buttons[key].isChecked()
        assert panel.stack.currentIndex() == panel.pages[key]
    w.file_open(str(PORTAO))                                     # projeto com ambiente: abre nele
    w._update_process_status()
    assert panel.current == "env" and "em uso" in panel.buttons["env"].text()
    assert panel.buttons["fio"].text() == "Factory IO"           # nada conectado: sem selo


def test_comm_guide_shows_live_paths_and_traffic(window):
    """Ajuda > Como funciona a comunicação: mapa ao vivo, tabelas do protocol.json e tráfego LDP."""
    from ladderide.comm.protocol import SPEC
    app, w = window
    menu = next(a.menu() for a in w.menuBar().actions() if a.menu() and "Aj" in a.text())
    assert w.actions_["comm_guide"] in menu.actions()
    w.file_open(str(PORTAO))
    w.compile()
    w.sim_run()
    w.actions_["comm_guide"].trigger()
    d = w.comm_guide
    d.refresh()
    assert {"compiler", "sim", "env", "e_plant"} <= d.map.active
    assert not {"fio", "client", "e_ldp"} & d.map.active          # nada conectado
    assert d.tabs.count() == 5
    rows = sorted(t.rowCount() for t in d.tabs.widget(1).findChildren(mw.QTableWidget))
    assert rows == sorted([len(SPEC["commands"]), len(SPEC["errors"])])   # comandos e erros
    d.map.select("e_fio")
    assert "Modbus TCP" in d.details.toPlainText()
    w.session.traffic.emit("TX", "LOAD_BEGIN", 7, 18)
    w.session.traffic.emit("TX", "STATUS", 8, 10)                 # leitura periódica: oculta no log
    assert "LOAD_BEGIN" in d.log.toPlainText() and "STATUS" not in d.log.toPlainText()
    assert d.counts["TX"] == 2
    w.sim_stop()
    d.close()


def test_user_guide_has_screens_toc_and_search(window):
    """Ajuda > Guia do usuário: sumário das seções, imagens das telas, busca e ampliação."""
    import re
    from PySide6.QtCore import QUrl
    from ladderide.ui import user_guide as ug
    app, w = window
    menu = next(a.menu() for a in w.menuBar().actions() if a.menu() and "Aj" in a.text())
    assert w.actions_["user_guide"] in menu.actions()
    source = ug.load_guide()
    images = re.findall(r'<img src="([^"]+)"', source)
    assert len(images) >= 15
    assert all((ug.HELP_DIR / img).is_file() for img in images)            # toda imagem citada existe
    w.actions_["user_guide"].trigger()
    d = w.user_guide
    app.processEvents()
    tops = [d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount())]
    assert tops[0] == "1. A janela principal" and any("Factory IO" in d.tree.topLevelItem(i).child(j).text(0)
                                                     for i in range(len(tops))
                                                     for j in range(d.tree.topLevelItem(i).childCount()))
    d.search.setText("Modbus TCP")
    assert d.found.text() == ""                                             # encontrado
    d.search.setText("xyz-nao-existe")
    assert d.found.text() == "nada encontrado"
    d._link(QUrl("zoom:" + images[0]))
    zoom = d.findChildren(ug.ImageDialog)
    assert zoom and not zoom[0].findChild(mw.QLabel).pixmap().isNull()
    d.close()


def test_opening_project_adjusts_io_and_io_simulator_to_controller(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ladderide.model.controllers import apply_controller, controller_by_id
    from ladderide.model.project import Coil, Contact, Project, Rung
    from ladderide.ui import main_window as mw
    QApplication.instance() or QApplication([])
    p = Project(name="Antigo")
    apply_controller(p, controller_by_id("1747-l40a"))
    p.io.n_inputs, p.io.n_outputs = 8, 8                                  # E/S diferentes do controlador
    p.environment = "simulador_es"
    p.rungs = [Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")])]
    path = tmp_path / "antigo.ladproj"
    p.save(path)
    w = mw.MainWindow(persist_layout=False)
    w.file_open(str(path))
    env = w.env_panel.env
    assert (w.project.io.n_inputs, w.project.io.n_outputs) == (24, 16) and w.dirty
    assert (len(env.inputs), len(env.outputs)) == (24, 16)
    assert "24 entradas" in w.statusBar().currentMessage()
    w.dirty = False
    w.close()
