"""Interface: aba Processo > CLP real comandando um CLIC-02 / CP1E falso pela serial."""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ladderide.comm.plc_serial import CLIC_INPUTS, CLIC_MARKERS  # noqa: E402
from ladderide.model import Coil, Contact, Project, Rung  # noqa: E402
from ladderide.model.controllers import apply_controller, controller_by_id  # noqa: E402
from ladderide.sim.simulator import SimState  # noqa: E402
from ladderide.ui import main_window as mw  # noqa: E402
from ladderide.ui.dialogs import NewProjectDialog  # noqa: E402
from test_factoryio import wait_for  # noqa: E402
from test_plc_link import FakeClic, FakeCp1e, FakeLine  # noqa: E402


@pytest.fixture
def window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: mw.QMessageBox.Discard)
    w = mw.MainWindow()
    w.show()
    yield app, w
    w.dirty = False
    w.plc_panel.shutdown()
    w.session.close()
    w.close()


def pump(app, cond, timeout=3.0):
    def step():
        app.processEvents()
        return cond()
    return wait_for(step, timeout)


def project_for(controller_id: str) -> Project:
    p = Project(name="Esteira")
    apply_controller(p, controller_by_id(controller_id))
    p.rungs = [Rung([Contact("XIC", "I0.0"), Contact("XIO", "I0.1")], [Coil("OTE", "Q0.2")])]
    return p


def test_transfer_runs_program_with_clic02_io(window):
    app, w = window
    slave = FakeClic(unit=1)
    w.set_project(project_for("clw-02-20vr-d"), None)
    panel = w.plc_panel
    assert panel.driver.currentData() == "clic02"            # o protocolo segue o controlador do projeto
    assert (panel.baud.currentData(), panel.framing.currentData()) == (38400, "8N2")
    assert "CLW-02/20VR-D" in panel.header.text()
    assert (panel.face.n_in, panel.face.n_out) == (12, 8)
    panel.line_factory = lambda c: FakeLine(slave)
    panel.port.setEditText("COM7")

    panel.transfer_btn.click()
    assert panel.linked and w.sim is not None and w.sim.state == SimState.RUNNING
    assert w.process_panel.current == "plc"
    assert w._plant() is panel.link
    assert not w.sim_panel.speed.isEnabled()                  # CLP real roda em tempo real
    assert pump(app, lambda: panel.link.connected)

    slave.regs[CLIC_INPUTS] = 0b01                             # I01 ligado no CLIC-02
    assert pump(app, lambda: slave.regs[CLIC_MARKERS] == 0b100)   # Q0.2 -> M03 -> Q03
    assert pump(app, lambda: panel.face.outputs == 0b100 and panel.face.inputs == 0b01)
    slave.regs[CLIC_INPUTS] = 0b11                             # I02 desliga a esteira
    assert pump(app, lambda: slave.regs[CLIC_MARKERS] == 0)
    w._update_process_status()
    assert "conectado" in w.process_panel.buttons["plc"].text()

    slave.regs[CLIC_INPUTS] = 0b01
    assert pump(app, lambda: slave.regs[CLIC_MARKERS] == 0b100)
    panel.connect_btn.click()                                  # desconectar desliga as saidas
    assert not panel.linked and slave.regs[CLIC_MARKERS] == 0
    assert w.sim_panel.speed.isEnabled()


def test_cp1e_project_selects_hostlink_and_draws(window):
    app, w = window
    w.set_project(project_for("cp1e-n30dr-a"), None)
    panel = w.plc_panel
    assert panel.driver.currentData() == "hostlink"
    assert (panel.baud.currentData(), panel.framing.currentData(), panel.unit.value()) == (9600, "7E2", 0)
    plc = FakeCp1e()
    panel.line_factory = lambda c: FakeLine(plc)
    panel.port.setEditText("COM4")
    panel.test_btn.click()
    assert pump(app, lambda: "respondeu" in panel.status.text())
    assert plc.cio[100] == 0
    w.process_panel.show_page("plc")
    image = panel.face.grab()                                  # desenha sem erro
    assert image.width() > 300


def test_controller_without_link_explains(window):
    _app, w = window
    w.set_project(project_for("cp1e-e10dr-a"), None)
    assert "sem ligação com CLP real" in w.plc_panel.header.text()


def test_new_project_dialog_lists_weg_and_omron():
    QApplication.instance() or QApplication([])
    dlg = NewProjectDialog()
    families = [dlg.list.topLevelItem(i).text(0) for i in range(dlg.list.topLevelItemCount())]
    assert "WEG CLIC-02" in families and "Omron CP1E tipo E" in families
    dlg.select("clw-02-20vr-d")
    assert dlg.selected_id() == "clw-02-20vr-d"


def test_expansions_reach_panel_drawing_and_link(window, monkeypatch):
    app, w = window
    p = project_for("clw-02-12hr-d")
    p.rungs = [Rung([Contact("XIC", "I1.0")], [Coil("OTE", "Q0.4")])]     # X01 do modulo -> Y01 do modulo
    w.set_project(p, None)

    class FakeDialog:
        def __init__(self, ctrl, ids, parent=None):
            pass

        def exec(self):
            return True

        def ids(self):
            return ["clw-02-8er-d"]
    import ladderide.ui.expansion_dialog as ed
    monkeypatch.setattr(ed, "ExpansionDialog", FakeDialog)
    w.actions_["expansions"].trigger()
    assert w.project.target.expansions == ["clw-02-8er-d"]
    assert (w.project.io.n_inputs, w.project.io.n_outputs) == (12, 8)
    panel = w.plc_panel
    assert "CLW-02/8ER-D" in panel.modules_label.text()
    assert panel.face.modules == [("CLW-02/8ER-D", 4, 4)]
    assert panel.config().modules == [[4, 4]]
    assert "M11 -> Y01" in panel.help.text()

    slave = FakeClic()
    panel.line_factory = lambda c: FakeLine(slave)
    panel.port.setEditText("COM7")
    panel.transfer_btn.click()
    assert pump(app, lambda: panel.link.connected)
    slave.regs[CLIC_INPUTS + 1] = 0b1                                  # X01
    assert pump(app, lambda: slave.regs.get(CLIC_MARKERS + 1, 0) == 0b1)   # M11 -> Y01
    panel.connect_btn.click()
    w.sim_stop()                                                       # editar so fora da simulacao
    w.undo()
    assert w.project.target.expansions == [] and w.project.io.n_inputs == 8
