"""Interface: painel Factory IO ligado a simulacao (servidor Modbus falso)."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ladderide.model import Coil, Contact, Project, Rung, Symbol  # noqa: E402
from ladderide.ui import main_window as mw  # noqa: E402
from test_factoryio import FakeFactoryIO, wait_for  # noqa: E402


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Discard)
    w = mw.MainWindow()
    w.show()
    server = FakeFactoryIO()
    yield app, w, server
    w.dirty = False
    w.fio_panel.shutdown()
    w.session.close()
    w.close()
    server.close()


def table_rows(table):
    return [[table.item(r, c).text() for c in range(4)] for r in range(table.rowCount())]


def pump(app, cond, timeout=3.0):
    def step():
        app.processEvents()
        return cond()
    return wait_for(step, timeout)


def test_factoryio_panel_drives_simulation_and_locks_speed(window):
    app, w, fio = window
    p = Project(name="Esteira")
    p.rungs = [Rung([Contact("XIC", "I0.0"), Contact("XIO", "I0.1")], [Coil("OTE", "Q0.2")])]
    p.symbols = [Symbol("Liga", "I0.0"), Symbol("Esteira", "Q0.2")]
    w.set_project(p, None)
    w.sim_panel.set_speed(10.0)
    panel = w.fio_panel
    panel.port.setValue(fio.port)
    panel.n_sensors.setValue(2)
    panel.n_actuators.setValue(4)
    assert panel.n_sensors.maximum() == 16                     # portas alem do projeto ficam sem endereco

    w.actions_["factoryio"].trigger()
    assert w.fio_dock.isVisible()
    panel.connect_btn.click()
    assert panel.linked and not panel.host.isEnabled()
    assert w.sim_panel.speed_factor == 1.0 and not w.toolbar_speed.isEnabled()
    assert pump(app, lambda: panel.link.connected)

    w.sim_run()
    assert w.sim.plant is panel.link
    assert not w.sim_panel.io.input_buttons[0].isEnabled()     # I0.0 vem da cena
    assert w.sim_panel.io.input_buttons[2].isEnabled()         # I0.2 continua no painel
    fio.inputs[0] = True
    assert pump(app, lambda: (w.tick(), fio.coils[2])[1])
    w.device_tick()
    assert "Conectado" in panel.status.text()
    ins, outs = table_rows(panel.in_table), table_rows(panel.out_table)
    assert ins[0] == ["Input 0", "I0.0", "Liga", "1"] and ins[1][3] == "0" and len(ins) == 2
    assert outs[2] == ["Coil 2", "Q0.2", "Esteira", "1"] and len(outs) == 4

    w.sim_stop()                                                # parada: estado seguro na cena
    w._update_live()
    assert pump(app, lambda: not fio.coils[2])

    w.sim_run()
    assert pump(app, lambda: (w.tick(), fio.coils[2])[1])
    panel.connect_btn.click()                                   # desconectar desliga os atuadores
    assert not panel.linked and not any(fio.coils[:4])
    assert w.sim.plant is None                                  # sem ambiente escolhido
    assert w.sim_panel.speed_factor == 10.0 and w.toolbar_speed.isEnabled()
    w.sim_stop()


def test_factoryio_table_lists_all_driver_ports(window):
    """As portas do driver (9 Inputs, 1 Input Reg, 4 Coils, 3 Holding Regs) aparecem na tabela."""
    app, w, fio = window
    p = Project(name="Portas")
    p.rungs = [Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")])]
    p.symbols = [Symbol("Nivel", "N0"), Symbol("Velocidade", "N8")]
    w.set_project(p, None)                                      # controlador de 8 E/S
    panel = w.fio_panel
    panel.port.setValue(fio.port)
    panel.n_sensors.setValue(9)
    panel.n_input_regs.setValue(1)
    panel.n_actuators.setValue(4)
    panel.n_holding_regs.setValue(3)
    ins, outs = table_rows(panel.in_table), table_rows(panel.out_table)   # como a janela do driver
    assert [r[0] for r in ins] == [f"Input {k}" for k in range(9)] + ["Input Reg 0"]
    assert [r[0] for r in outs] == [f"Coil {k}" for k in range(4)] + [f"Holding Reg {k}" for k in range(3)]
    assert ins[8][1:3] == ["-", "sem endereco no projeto"]                # Input 8: projeto tem 8 entradas
    assert ins[9][1:3] == ["N0", "Nivel"] and outs[4][1:3] == ["N8", "Velocidade"]
    fio.input_regs[0] = 321
    panel.connect_btn.click()
    assert panel.linked
    assert pump(app, lambda: (w.device_tick(), panel.in_table.item(9, 3).text() == "321")[1])
    panel.connect_btn.click()


def test_factoryio_panel_rejects_invalid_config(window):
    app, w, fio = window
    panel = w.fio_panel
    panel.n_sensors.setValue(0)
    panel.n_actuators.setValue(0)
    panel.connect_btn.click()
    assert not panel.linked and "nada a trocar" in panel.status.text()


def test_address_editing_in_ladder_shows_factoryio_ports(window):
    """Duplo clique no endereco do elemento abre a escolha rapida, com as portas do Factory IO."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from ladderide.ui.ladder_view import ElementItem
    app, w, fio = window
    p = Project(name="Enderecos")
    contact = Contact("XIC", "Esteira")
    p.rungs = [Rung([contact], [Coil("OTE", "Q0.2")])]
    p.symbols = [Symbol("Esteira", "Q0.0"), Symbol("Sensor_Fim", "I0.3")]
    w.set_project(p, None)
    w.fio_panel.n_sensors.setValue(9)
    assert w.fio_panel.port_names()["I0.3"] == "Input 3"

    popup = w.edit_address(contact.id)
    texts = [popup.combo.itemText(k) for k in range(popup.combo.count())]
    assert any(t.startswith("Sensor_Fim") and "I0.3" in t and "Input 3 (Factory IO)" in t for t in texts)
    assert any(t.startswith("Q0.0") and "Esteira" in t and "Coil 0 (Factory IO)" in t for t in texts)
    popup.combo.setCurrentIndex(next(k for k, t in enumerate(texts) if t.startswith("I0.3")))
    popup.accept_value()
    assert w.project.rungs[0].condition[0].operand == "I0.3" and w.dirty
    w.undo()
    assert w.project.rungs[0].condition[0].operand == "Esteira"

    popup = w.edit_address(w.project.rungs[0].condition[0].id)
    popup.combo.setCurrentText("I0.5")                          # endereco digitado
    popup.accept_value()
    assert w.project.rungs[0].condition[0].operand == "I0.5"

    seen = []                                                   # duplo clique: endereco x resto do elemento
    w.view.addressRequested.connect(lambda eid, pos: seen.append(("addr", eid)))
    w.view.editRequested.disconnect()
    w.view.editRequested.connect(lambda eid: seen.append(("edit", eid)))
    app.processEvents()
    item = next(i for i in w.view.items_by_id.values() if isinstance(i, ElementItem) and i.kind == "XIC")
    r = item.rect
    for y_frac in (0.85, 0.3):
        pt = w.view.mapFromScene(r.center().x(), r.top() + y_frac * r.height())
        QTest.mouseDClick(w.view.viewport(), Qt.LeftButton, Qt.NoModifier, pt)
    assert [s[0] for s in seen] == ["addr", "edit"]
