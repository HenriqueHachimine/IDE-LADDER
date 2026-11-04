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
    monkeypatch.setattr(mw.QMessageBox, "warning", lambda *a, **k: messages.append(a[1:]))
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
    assert wait_for(app, lambda: any("concluída" in str(m) for m in w.messages_shown)), w.messages_shown
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


def test_esp32_board_simulator_runs_firmware_and_shows_pins(window):
    app, w = window
    w.file_open(str(ROOT / "examples" / "ambientes" / "portao.ladproj"))
    w.show_esp32()
    board_panel = w.esp32_panel
    board_panel.set_board("esp32-relay", 8)                     # placa do projeto (independe da escolha salva)
    cfg = board_panel.config
    assert cfg.value("PIN_595_SER") == 33 and cfg.out_map == [7, 6, 5, 4, 3, 2, 1, 0]
    assert any(i.verify for i in cfg.items)                     # valores a confirmar na placa real
    board_panel.power_btn.click()                               # liga a placa virtual
    assert wait_for(app, lambda: board_panel.board.powered and w.device_panel.last_status is not None)
    assert board_panel.board.virtual and board_panel.board.state == "STOP"
    assert "BOOT" in board_panel.log.toPlainText()
    board_panel.transfer_btn.click()
    assert wait_for(app, lambda: w.device_panel.last_status.has_program
                    and w.device_panel.last_status.build_id == w.result.build_id)
    assert "LOAD_COMMIT" in board_panel.log.toPlainText()       # monitor serial mostra o protocolo
    board_panel.run_btn.click()
    assert wait_for(app, lambda: board_panel.board.state == "RUN")
    board_panel.toggle_input(2)                                 # Parar (NF): fechado
    board_panel.toggle_input(0)                                 # Abrir
    assert wait_for(app, lambda: board_panel.board.outputs & 1)  # rele K1 (Motor_Sobe) energizado
    levels = cfg.shift_out_levels(board_panel.board.outputs)
    assert levels[cfg.out_map.index(0)] == 0                    # ativo em 0 no 74HC595
    assert board_panel.board.names["Q0.0"] == "Motor_Sobe"
    board_panel.reset_btn.click()                               # reinicia: firmware volta em STOP
    assert wait_for(app, lambda: board_panel.board.powered and board_panel.board.state == "STOP", 10)


def test_board_config_parser_reads_defines_arrays_and_comments():
    from ladderide.comm.board import parse_board_config
    cfg = parse_board_config(
        "/* Polaridade (VERIFICAR) */\n#define RELAY_ACTIVE_LOW 0\n#define INPUT_ACTIVE_LOW 1\n\n"
        "#define PIN_595_SER 4 /* dados */\nstatic const uint8_t OUT_MAP[8] = {0, 1, 2, 3, 4, 5, 6, 7};\n")
    assert cfg.value("PIN_595_SER") == 4 and cfg.out_map == list(range(8))
    assert [i.verify for i in cfg.items[:2]] == [True, True]
    assert cfg.shift_out_levels(0b1) == [1, 0, 0, 0, 0, 0, 0, 0]   # ativo em 1
    assert cfg.shift_in_levels(0b1)[cfg.in_map.index(0)] == 0      # ativo em 0


def test_esp32_board_runs_arduino_example_sketch(window):
    """Modo sketch: o exemplo teste_placa roda no PC com o io_board.cpp do firmware."""
    from ladderide.comm.sketch import list_sketches
    app, w = window
    if "teste_placa" not in list_sketches():
        pytest.skip("exemplo teste_placa ausente")
    panel = w.esp32_panel
    w.show_esp32()
    panel.mode.setCurrentIndex(panel.mode.findData("teste_placa"))
    panel.power_btn.click()                                      # compila e roda o sketch
    assert wait_for(app, lambda: panel.sketch is not None and "=== Teste da placa" in panel.log.toPlainText(), 60)
    assert panel.board.badge == "SKETCH: teste_placa" and not panel.transfer_btn.isEnabled()
    panel.send_edit.setText("1")                                 # comando da Serial: liga OUT1
    panel.send_text()
    assert wait_for(app, lambda: panel.board.outputs == 1 and panel.board.raw595 is not None)
    cfg = panel.config
    assert panel.board._raw_levels(panel.board.raw595)[cfg.out_map.index(0)] == 0   # ativo em 0, vindo do codigo
    panel.toggle_input(2)                                        # borne IN3
    panel.send_edit.setText("m")                                 # espelho: IN3 -> OUT3
    panel.send_text()
    assert wait_for(app, lambda: panel.board.outputs == 0b100)
    log = panel.log.toPlainText()                                # o monitor narra cada passo
    assert "comando '1': OUT1 -> ligar" in log and "rele    OUT1 LIGOU" in log
    assert wait_for(app, lambda: "rele    OUT3 LIGOU" in panel.log.toPlainText())
    log = panel.log.toPlainText()
    assert "entrada IN3 LIGOU" in log and "modo manual -> espelho" in log and "rele    OUT1 desligou" in log
    panel.mode.setCurrentIndex(0)                                # volta ao firmware: encerra o sketch
    assert panel.sketch is None and not panel.board.powered


def test_board_panel_switches_to_arduino_uno_with_fewer_relays(window):
    """Placa Arduino UNO com 4 reles: o firmware virtual sobe com 8 entradas e 4 saidas."""
    app, w = window
    w.file_open(str(ROOT / "examples" / "timers" / "temporizadores.ladproj"))   # usa Q0.0..Q0.3
    w.show_esp32()
    panel = w.esp32_panel
    try:
        panel.set_board("arduino-uno", 4)
        assert panel.relays_spin.maximum() == 8 and panel.board.relays == 4
        assert w.device_panel.virtual_args[-1] == "virtual-arduino-uno-x4"
        assert not panel.mode.isEnabled()                       # exemplos Arduino sao da placa ESP32
        assert "4 relés" in panel.io_warning.text() and panel.adapt_btn.isVisibleTo(panel)
        panel.adapt_btn.click()                                 # projeto passa a ter 4 saidas
        assert w.project.io.n_outputs == 4 and panel.io_warning.text() == ""
        panel.power_btn.click()
        assert wait_for(app, lambda: panel.board.powered and w.device_panel.last_status is not None)
        assert w.device_panel.device_info.hardware == "virtual-arduino-uno-x4"
        assert (w.device_panel.device_info.n_inputs, w.device_panel.device_info.n_outputs) == (8, 4)
        assert not panel.board_combo.isEnabled()                # placa ligada: nao troca
        panel.transfer_btn.click()
        assert wait_for(app, lambda: w.device_panel.last_status.has_program)
        panel.run_btn.click()
        assert wait_for(app, lambda: panel.board.state == "RUN")
        panel.toggle_input(0)                                   # I0.0 -> TON de 1 s -> Q0.0
        assert wait_for(app, lambda: panel.board.outputs & 1)   # K1 do modulo (pino D2)
        w.undo()                                                # Ctrl+Z volta as 8 saidas do projeto
    finally:
        w.session.close()
        wait_for(app, lambda: not w.device_panel.connected, 2)
        panel.set_board("esp32-relay", 8)


def test_board_profiles_pins_and_virtual_args():
    from ladderide.comm.board_profiles import PROFILES, get_profile
    mega = PROFILES["arduino-mega"]
    assert mega.clamp_relays(40) == 16 and mega.clamp_relays(0) == 1
    assert mega.virtual_args(12) == ["--inputs", "16", "--outputs", "12", "--hardware", "virtual-arduino-mega-x12"]
    rows = mega.pin_map(2)
    assert rows[:2] == [("Q0.0", "D22", "relé K1"), ("Q0.1", "D23", "relé K2")] and rows[-1][:2] == ("I0.15", "D53")
    uno = get_profile("arduino-uno")
    assert uno.relay_pins[0] == "D2" and uno.input_pins[:2] == ("A0", "A1") and not uno.hardware
    assert get_profile("nao-existe").id == "esp32-relay"
    assert get_profile("esp32-relay").hardware_id(8) == "virtual-esp32-relay-x8"   # mesmo nome de antes


def test_board_view_draws_arduino_pins_relays_and_inputs():
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QImage
    from ladderide.comm.board import load_board_config
    from ladderide.comm.board_profiles import PROFILES
    from ladderide.ui.esp32_panel import BoardView
    QApplication.instance() or QApplication([])
    view = BoardView(load_board_config())
    view.set_board(PROFILES["arduino-mega"], 12)
    view.powered = view.virtual = True
    view.resize(1800, 860)                                         # escala 2: testa a conversao do clique
    view.render(QImage(1800, 860, QImage.Format_ARGB32))
    assert {"D22", "D33", "D38", "D53"} <= set(view._pins)        # reles em D22.., entradas em D38..
    assert view._input_at(view.input_rect(15).center()) is None   # coordenadas logicas, nao do widget
    s, ox, oy = view._transform()
    center = view.input_rect(15).center()
    assert view._input_at(QPointF(ox + center.x() * s, oy + center.y() * s)) == 15
    view.outputs = 0xFFFF
    view.set_board(PROFILES["arduino-uno"], 20)                    # limita a 8 reles e corta as saidas
    assert view.relays == 8 and view.outputs == 0xFF
