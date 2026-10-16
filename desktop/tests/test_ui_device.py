"""Interface + dispositivo virtual: conexao, transferencia, RUN e monitor online."""
from __future__ import annotations

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from conftest import ROOT  # noqa: E402
from ladderide.comm.protocol import DevState  # noqa: E402
from ladderide.comm.virtual import BuildError, host_tool  # noqa: E402
from ladderide.ui import device_panel as dp  # noqa: E402
from ladderide.ui import main_window as mw  # noqa: E402

DEMO = ROOT / "examples" / "demo" / "demonstracao.ladproj"


def wait_for(app, cond, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def window(tmp_path, monkeypatch):
    try:
        host_tool("virtual_device")
    except BuildError as exc:
        pytest.skip(str(exc))
    app = QApplication.instance() or QApplication([])
    messages = []
    monkeypatch.setattr(mw.QMessageBox, "information", lambda *a, **k: messages.append(a[1:]))
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a, **k: messages.append(a[1:]))
    monkeypatch.setattr(mw.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(dp, "STORAGE_OVERRIDE", tmp_path / "flash.ldrb")   # flash virtual isolada
    w = mw.MainWindow()
    w.file_open(str(DEMO))
    w.messages_shown = messages
    yield app, w
    w.dirty = False
    w.session.close()
    wait_for(app, lambda: not w.device_panel.connected, 2)
    w.close()


def test_connect_transfer_run_and_monitor(window):
    app, w = window
    panel = w.device_panel
    panel.kind.setCurrentIndex(1)                         # dispositivo virtual
    panel.toggle_connection()
    assert wait_for(app, lambda: panel.connected and panel.last_status is not None)
    assert panel.last_status.state == DevState.STOP and not panel.last_status.has_program

    w.device_transfer()
    assert wait_for(app, lambda: any("concluida" in str(m) for m in w.messages_shown)), w.messages_shown
    assert wait_for(app, lambda: panel.last_status.has_program
                    and panel.last_status.build_id == w.result.build_id)
    assert "Igual ao projeto" in panel.program.text()

    panel.run_btn.click()
    assert wait_for(app, lambda: panel.last_status.state == DevState.RUN)
    panel.monitor.setChecked(True)
    panel.io.input_buttons[0].setChecked(True)            # Partida (entrada simulada)
    assert wait_for(app, lambda: w.last_snapshot is not None and w.last_snapshot.q_logical & 1)
    panel.io.input_buttons[0].setChecked(False)
    assert wait_for(app, lambda: w.last_snapshot.inputs == 0 and w.last_snapshot.q_logical & 1)

    # o diagrama mostra a energia vinda do dispositivo
    motor_coil = w.project.rungs[0].outputs[0]
    assert wait_for(app, lambda: w.view.items_by_id[motor_coil.id].state.power_in is True)
    assert "16a34a" in panel.io.out_leds[0].styleSheet() and "16a34a" in panel.io.cmd_leds[0].styleSheet()
    # tabela de temporizadores/contadores preenchida com valores do dispositivo
    assert panel.io.elements.rowCount() == 3
    assert wait_for(app, lambda: panel.io.elements.item(0, 2).text().endswith(" ms")
                    and panel.io.elements.item(0, 2).text() != "0 ms")

    # editar o projeto invalida o mapeamento: sem sobreposicao
    w.push_undo()
    w.project.rungs[1].outputs[0].preset = 999
    w.modified()
    assert w._monitor_source() is None
    w.undo()

    panel.stop_btn.click()
    assert wait_for(app, lambda: panel.last_status.state == DevState.STOP)
    assert wait_for(app, lambda: w.last_snapshot.q_commanded == 0)


def test_transfer_with_errors_is_blocked(window, monkeypatch):
    app, w = window
    panel = w.device_panel
    panel.kind.setCurrentIndex(1)
    panel.toggle_connection()
    assert wait_for(app, lambda: panel.connected and panel.last_status is not None)
    w.project.rungs[0].condition[1].operand = "Inexistente"
    w.modified()
    warnings = []
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: warnings.append(a[1:]))
    w.device_transfer()
    assert warnings and "erros" in warnings[0][1]
    assert not panel.last_status.has_program


def test_lost_device_reports_disconnection(window):
    app, w = window
    panel = w.device_panel
    panel.kind.setCurrentIndex(1)
    panel.toggle_connection()
    assert wait_for(app, lambda: panel.connected)
    w.session.client.transport.kill()
    panel.monitor.setChecked(True)
    assert wait_for(app, lambda: not panel.connected)
    assert "perdida" in panel.link.text() or "reconectar" in panel.link.text()
    # reconexao automatica (o dispositivo virtual e reiniciado pela fabrica)
    assert wait_for(app, lambda: panel.connected, timeout=10)
