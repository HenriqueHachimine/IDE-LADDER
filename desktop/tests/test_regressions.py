"""Regressoes dos bugs registrados em docs/bugs-corrigidos.md (o codigo do item aparece em cada teste)."""
from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
import threading
from pathlib import Path

import pytest

from ladderide.codegen import generate_cpp
from ladderide.comm.modbus_tcp import ModbusError, ModbusTcpClient
from ladderide.comm.frames import FrameParser, encode
from ladderide.comm.plc_serial import ClicModbus, PlcError, _hex, crc16_modbus
from ladderide.compiler import compile_project, import_image, import_lil
from ladderide.core.asm import disassemble, parse_constant
from ladderide.envs import EnvironmentPlant, create, registry
from ladderide.model.controllers import controller_by_id, match_controller_io
from ladderide.model.edit import next_free_element
from ladderide.model.project import (CompareBox, Coil, Contact, MathBox, Parallel, Project, ProjectFormatError, Rung,
                                     Symbol, TimerBox)
from ladderide.sim.factoryio import FactoryIOConfig, FactoryIOLink
from ladderide.sim.simulator import Simulator
from ladderide.verify.esp32 import SKIP, VerifyReport


def latch_project() -> Project:
    return Project(rungs=[Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.0")])])


# ---------------------------------------------------------------- simulador e ambientes
def test_s1_click_shorter_than_a_scan_is_seen():
    result = compile_project(latch_project())
    assert result.ok
    env = create("simulador_es")
    sim = Simulator(result, 10)
    sim.attach_plant(EnvironmentPlant(env))
    sim.start()
    sim.advance(30, 0.01)
    env.press("I0", True)
    sim.advance(30, 0.01)
    env.press("I0", False)                      # soltou sem nenhuma varredura no meio
    assert not sim.vm.q[0]
    for _ in range(50):
        sim.advance(30, 0.01)
    assert sim.vm.q[0]


def test_s2_cold_start_keeps_latching_switches():
    env = create("garrafas")
    plant = EnvironmentPlant(env)
    env.press("LARGE", True)
    assert env.is_pressed("LARGE")
    plant.reset()
    assert env.is_pressed("LARGE")


def test_s3_elevator_call_at_open_door_is_not_pending():
    env = create("elevador")
    env.door = 1.0
    env.press("CALL1", True)
    assert env.pending == {}


def test_s4_on_control_receives_controls_that_are_not_inputs():
    env = create("silo")
    calls = []
    env.on_control = lambda key, down: calls.append((key, down))
    env.press("VEICULO", True)
    assert calls == [("VEICULO", True)]


def test_s5_plugin_with_dataclass_loads(tmp_path):
    (tmp_path / "carro.py").write_text(textwrap.dedent('''
        from __future__ import annotations
        from dataclasses import dataclass
        from ladderide.envs import Environment, register

        @dataclass
        class Dados:
            valor: int = 0

        @register
        class Carro(Environment):
            id = "plugin_carro"
            name = "carro"
            def reset(self): self.dados = Dados()
            def step(self, dt, out): pass
            def sensors(self): return {}
            def paint(self, p): pass
    '''), encoding="utf-8")
    registry.discover(extra_dirs=[tmp_path])
    try:
        assert registry.get("plugin_carro") is not None
    finally:
        registry._REGISTRY.pop("plugin_carro", None)


def test_s6_broken_plugin_is_listed_and_does_not_break_the_panel():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.envs import Environment, register
    from ladderide.ui.env_panel import EnvironmentPanel
    QApplication.instance() or QApplication([])

    @register
    class Broken(Environment):
        id, name = "plugin_ruim", "ruim"
        def reset(self): raise RuntimeError("defeito")
        def step(self, dt, out): pass
        def sensors(self): return {}
        def paint(self, p): pass

    try:
        panel = EnvironmentPanel()
        assert panel.combo.findData("plugin_ruim") < 0
        assert any("plugin_ruim" in e for e in registry.load_errors)
    finally:
        registry._REGISTRY.pop("plugin_ruim", None)
        registry.load_errors[:] = [e for e in registry.load_errors if "plugin_ruim" not in e]


def test_s7_invalid_host_is_a_modbus_error():
    with pytest.raises(ModbusError):
        ModbusTcpClient("fabrica..local", 502).connect()


def test_s8_malformed_plc_answer_is_a_plc_error():
    for text in ("", "XY"):
        with pytest.raises(PlcError):
            _hex(text)


def test_s9_restart_after_slow_stop_does_not_revive_old_thread():
    release = threading.Event()

    class SlowClient:
        connected = False
        def connect(self):
            release.wait(5)
            raise ModbusError("sem servidor")
        def close(self): pass

    link = FactoryIOLink(FactoryIOConfig(), client_factory=lambda c: SlowClient())
    link.start()
    first_stop = link._stop
    link.stop(timeout=0.01)
    link.start()
    try:
        assert first_stop.is_set() and link._stop is not first_stop and not link._stop.is_set()
    finally:
        release.set()
        link.stop()


def test_s10_speed_is_limited_by_cpu_time_when_the_interface_gives_it():
    result = compile_project(latch_project())
    sim = Simulator(result, 10)
    sim.start()
    assert sim.advance(30, 1000.0, work_ms=2000) >= 3000


def test_s11_speed_reading_is_steady_at_low_speed():
    result = compile_project(latch_project())
    sim = Simulator(result, 10)
    sim.start()
    readings = []
    for _ in range(600):
        sim.advance(30, 0.01)
        if sim.actual_speed:
            readings.append(sim.actual_speed)
    assert readings and all(0.005 <= r <= 0.02 for r in readings)


# ------------------------------------------------------------------- C++ gerado e nucleo
def cpp_of(project: Project) -> str:
    return generate_cpp(project).text


@pytest.mark.parametrize("name", ["PB0", "A0", "SDA", "UINT8_MAX", "init", "map", "time", "y1", "int16_t", "Serial3"])
def test_c1_symbol_with_a_board_global_name_is_renamed(name):
    p = latch_project()
    p.symbols.append(Symbol(name, "I0.0"))
    assert f"static bool &{name}_ = I[0];" in cpp_of(p)


def test_c1_timer_without_symbol_does_not_use_esp32_touch_pin_name():
    p = Project(rungs=[Rung([Contact("XIC", "I0.0")], [TimerBox("TON", "T0", 100)])])
    text = cpp_of(p)
    assert "static Timer &T0_ = T[0];" in text and "static Timer &T0 " not in text


def test_c1_address_names_stay_readable():
    assert "Q0_0" in cpp_of(latch_project()) and "Q0_0_" not in cpp_of(latch_project())


def test_c2_comments_cannot_break_the_generated_file():
    p = latch_project()
    p.name = "linha 1\nint quebrado"
    p.rungs[0].comment = "rede\nB = true;"
    p.symbols += [Symbol("A", "I0.0", "pasta C:\\"), Symbol("B", "Q0.0")]
    text = cpp_of(p)
    for line in text.splitlines():
        assert not line.rstrip().endswith("\\")
    assert "\nint quebrado" not in text and "\nB = true;" not in text
    gpp = shutil.which("g++")
    if gpp:
        run = subprocess.run([gpp, "-fsyntax-only", "-x", "c++", "-"], input=generate_cpp(p, arduino=False).text,
                             capture_output=True, text=True)
        assert run.returncode == 0, run.stderr


def test_c3_generate_with_no_io_does_not_raise():
    p = Project()
    p.io.n_inputs = p.io.n_outputs = 0
    assert "ERRO" in cpp_of(p).upper() or cpp_of(p)


def test_c4_empty_parallel_conducts_like_the_vm():
    p = Project(rungs=[Rung([Parallel(branches=[])], [Coil("OTE", "Q0.0")])])
    assert "Q0_0 = true;" in generate_cpp(p, arduino=False).text


def test_c5_input_word_with_bit_31_is_a_negative_int32():
    p = Project(rungs=[Rung([CompareBox("GRT", ["IW0", "0"])], [Coil("OTE", "Q0.0")])])
    p.target.device = "__desconhecido__"           # sem limite de controlador: 32 E/S
    p.io.n_inputs = p.io.n_outputs = 32
    result = compile_project(p)
    assert result.ok, result.errors
    sim = Simulator(result, 10)
    sim.inputs = 1 << 31
    sim.start()
    sim.advance(10, 1.0)
    assert not sim.vm.q[0]


def test_c6_underscore_name_is_not_a_constant():
    assert parse_constant("_5") is None
    assert parse_constant("1_000") == 1000 and parse_constant("0xFF_FF") == 0xFFFF


def test_c7_summary_mentions_items_not_verified():
    rep = VerifyReport()
    rep.add(SKIP, "Dispositivo conectado")
    assert "não verificado" in rep.summary() and "todas as verificações" not in rep.summary()


# ---------------------------------------------------------------------- porta digitada
@pytest.mark.parametrize("typed", ["COM9", "COM10"])
def test_u1_typed_port_wins_over_the_list(monkeypatch, typed):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    import ladderide.ui.cpp_upload_dialog as upload
    QApplication.instance() or QApplication([])
    monkeypatch.setattr(upload, "list_serial_ports", lambda: [("COM1", "A"), ("COM3", "B")])
    p = latch_project()
    p.target.device = "personalizado"
    dialog = upload.CppUploadDialog(p, "esp32-relay")
    assert dialog.selected_port() == "COM1"
    dialog.port.setEditText(typed)
    assert dialog.selected_port() == typed
    dialog.refresh_ports()
    assert dialog.selected_port() == typed


# ------------------------------------------------------------------- nucleo e modelo
def word_project() -> Project:
    p = Project(rungs=[Rung([CompareBox("GRT", ["N0", "1"])], [MathBox("ADD", ["N0", "1", "N0"]), Coil("OTE", "Q0.0")])])
    p.io.safe_outputs = 0b101
    return p


def test_k1_import_keeps_safe_outputs_and_words():
    result = compile_project(word_project())
    assert result.ok, result.errors
    imported = import_lil(disassemble(result.program))
    assert imported.io.safe_outputs == 0b101 and imported.io.n_words == word_project().io.n_words


def test_k2_build_id_depends_on_safe_outputs():
    a, b = latch_project(), latch_project()
    b.io.safe_outputs = 1
    assert compile_project(a).build_id != compile_project(b).build_id


def test_k3_decimal_constant_must_fit_int32():
    with pytest.raises(ValueError):
        parse_constant("3000000000")
    assert parse_constant("0xFFFFFFFF") == -1 and parse_constant("007") == 7


def test_k4_import_understands_compare_and_math_blocks():
    result = compile_project(word_project())
    rung = import_lil(disassemble(result.program)).rungs[0]
    assert isinstance(rung.condition[0], CompareBox) and rung.condition[0].operands == ["N0", "1"]
    assert isinstance(rung.outputs[0], MathBox) and rung.outputs[0].operands == ["N0", "1", "N0"]


def test_k5_import_does_not_cut_io_to_the_default_controller():
    p = Project(rungs=[Rung([Contact("XIC", "I1.7")], [Coil("OTE", "Q1.7")])])
    p.target.device = "simulacao-16"
    p.io.n_inputs = p.io.n_outputs = 16
    result = compile_project(p)
    assert result.ok, result.errors
    imported = import_image(result.image)
    match_controller_io(imported)
    assert (imported.io.n_inputs, imported.io.n_outputs) == (16, 16) and compile_project(imported).ok


@pytest.mark.parametrize("text", [".timer T0 FOO 10\nSOR 0\nEOR\n", "SOR 0\nXIC I0.0\nTON T5\nEOR\n",
                                  "SOR 0\nXIC I0.0\nOTE I0.0\nEOR\n", "SOR 0\nXIC I99.0\nOTE Q0.0\nEOR\n"])
def test_k6_invalid_listing_is_refused_with_a_handled_error(text):
    with pytest.raises(ValueError):
        import_lil(text)


@pytest.mark.parametrize("content", ["[]", '{"format": "x"', "[" * 100000], ids=["raiz", "json", "aninhado"])
def test_k8_corrupted_file_is_a_format_error(tmp_path, content):
    path = tmp_path / "ruim.ladproj"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        Project.load(path)


def test_k8_wrong_field_types_are_refused_on_load():
    data = latch_project().to_dict()
    data["io"]["n_markers"] = "64"
    with pytest.raises(ProjectFormatError):
        Project.from_dict(data)


def test_k8_failed_save_keeps_the_previous_file(tmp_path):
    path = tmp_path / "p.ladproj"
    p = latch_project()
    p.save(path)
    before = path.read_bytes()
    p.name = "\udc80"
    with pytest.raises(UnicodeEncodeError):
        p.save(path)
    assert path.read_bytes() == before


def test_k8_file_with_utf8_bom_opens(tmp_path):
    path = tmp_path / "bom.ladproj"
    latch_project().save(path)
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert Project.load(path).rungs


def test_k10_next_free_element_understands_symbols():
    p = Project(rungs=[Rung([Contact("XIC", "I0.0")], [TimerBox("TON", "Atraso", 100)])])
    p.symbols.append(Symbol("Atraso", "T0"))
    assert next_free_element(p, "T") == "T1"


def test_k11_small_cp1e_do_not_accept_expansions():
    for cid in ("cp1e-e10dt1-d", "cp1e-e14dt1-d", "cp1e-e20dt1-d", "cp1e-e14sdt1-d", "cp1e-e20sdt1-d",
                "cp1e-n14dt1-d", "cp1e-n20dt1-d"):
        assert controller_by_id(cid).max_expansions == 0


def main_window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow(persist_layout=False)


@pytest.mark.parametrize("name", ["", "Q0.0", "Parada"])
def test_k9_invalid_rename_in_symbol_table_is_refused(name):
    w = main_window()
    w.project.rungs = [Rung([Contact("XIC", "Partida")], [Coil("OTE", "Q0.0")])]
    w.project.symbols[:] = [Symbol("Partida", "I0.0"), Symbol("Parada", "I0.1")]
    w.refresh()
    w.symbols.item(0, 0).setText(name)
    assert w.project.symbols[0].name == "Partida" and w.project.rungs[0].condition[0].operand == "Partida"
    assert w.symbols.item(0, 0).text() == "Partida" and not w.undo_stack
    w.dirty = False


def test_k12_refused_edit_keeps_redo_and_clean_state():
    from ladderide.model import edit
    w = main_window()
    w.redo_stack.append(w.project.to_dict())
    w.dirty = False

    def refuse():
        raise edit.EditError("recusada")

    assert not w.apply_edit(refuse)
    assert len(w.redo_stack) == 1 and not w.dirty


# ----------------------------------------------------------------------- comunicacao
def test_m3_frame_timeout_is_not_renewed_by_empty_reads():
    now = [0.0]
    parser = FrameParser(clock=lambda: now[0])
    frame = encode(0x01, 1, 0, b"")
    parser.feed(frame[:3])
    for _ in range(6):
        now[0] += 0.06
        parser.feed(b"")
    assert parser.feed(frame[3:]) == []


def test_m4_cli_with_no_vectors_fails(tmp_path, capsys):
    from ladderide.cli import main
    code = main(["--virtual", "--virtual-storage", str(tmp_path / "flash.bin"),
                 "equivalence", "--vectors", str(tmp_path / "nada")])
    assert code == 2 and "ERRO" in capsys.readouterr().err


def test_m5_cli_with_missing_project_is_an_error_not_a_traceback(tmp_path, capsys):
    from ladderide.cli import main
    assert main(["compile", str(tmp_path / "nao_existe.ladproj")]) == 2
    assert "ERRO" in capsys.readouterr().err


def test_m7_board_config_accepts_common_c_forms():
    from ladderide.comm.board import parse_board_config
    cfg = parse_board_config("""
#define RS485_RX 0x21
#define RS485_TX 33 // comentario
#define SCAN_WATCHDOG_US 50000UL
static const uint8_t OUT_MAP[BOARD_OUTPUTS] = {0x00, 1, 2};
""")
    assert cfg.value("RS485_RX") == 33 and cfg.value("RS485_TX") == 33 and cfg.value("SCAN_WATCHDOG_US") == 50000
    assert cfg.out_map == [0, 1, 2]


class FakeSerialLine:
    def __init__(self, answer: bytes):
        self.answer = bytearray(answer)
    def flush_input(self): pass
    def write(self, data): pass
    def read(self, n, timeout):
        out, self.answer[:n] = bytes(self.answer[:n]), b""
        return out
    def close(self): pass


def with_crc(body: bytes) -> bytes:
    crc = crc16_modbus(body)
    return body + bytes([crc & 0xFF, crc >> 8])


def test_m9_clic02_checks_slave_and_write_echo():
    other_slave = ClicModbus(FakeSerialLine(with_crc(bytes([7, 0x83, 2]))), unit=1, timeout=0.05)
    with pytest.raises(PlcError, match="outro escravo"):
        other_slave.read_words(0x100, 1)
    wrong_echo = ClicModbus(FakeSerialLine(with_crc(bytes([1, 6, 0, 9, 0, 1]))), unit=1, timeout=0.05)
    with pytest.raises(PlcError, match="diferente"):
        wrong_echo.write_word(0x100, 1)


# ------------------------------------------------------------------- interface
def window_with_rungs(n: int = 2):
    w = main_window()
    w.project.rungs = [Rung([Contact("XIC", "I0.0")], [Coil("OTE", f"Q0.{k}")]) for k in range(n)]
    w.refresh()
    return w


def test_u2_delete_and_enter_only_act_on_the_diagram():
    from PySide6.QtCore import Qt
    w = main_window()
    for key in ("delete", "edit"):
        assert w.actions_[key].shortcutContext() == Qt.WidgetWithChildrenShortcut
        assert w.actions_[key] in w.view.actions()


def test_u3_editing_is_blocked_while_monitoring():
    w = window_with_rungs()
    w.on_monitor_toggled(True)
    assert w.view.readonly and not w.actions_["delete"].isEnabled() and not w._can_edit()
    w.on_monitor_toggled(False)
    assert not w.view.readonly and w._can_edit()


def test_u4_selection_is_cleared_after_deleting_a_rung():
    w = window_with_rungs()
    w.view.select(("rung", 1))
    w.delete_selected()
    assert w.view.selection is None and len(w.project.rungs) == 1
    w.delete_selected()
    assert len(w.project.rungs) == 1
    w.dirty = False


def test_u5_symbol_outside_the_io_range_is_ignored_by_the_panel():
    w = window_with_rungs(1)
    w.project.symbols.append(Symbol("Longe", "I99.0"))
    w.refresh()
    assert not any(ref == (1, 99 * 8) for ref in w.sim_panel.io.var_rows)
    w.dirty = False


def test_u6_failed_save_as_keeps_the_previous_path(monkeypatch, tmp_path):
    import ladderide.ui.main_window as mw
    w = window_with_rungs(1)
    bad = str(tmp_path / "pasta_que_nao_existe" / "x.ladproj")
    monkeypatch.setattr(mw.QFileDialog, "getSaveFileName", lambda *a, **k: (bad, ""))
    monkeypatch.setattr(mw.QMessageBox, "critical", lambda *a, **k: None)
    assert not w.file_save_as() and w.path is None
    w.dirty = False


def test_u7_undo_keeps_the_chosen_environment():
    w = window_with_rungs(1)
    w.push_undo()
    w.project.environment = "silo"
    w.undo()
    assert w.project.environment == "silo"
    w.dirty = False


def test_u8_new_symbols_get_free_addresses():
    w = window_with_rungs(1)
    w.symbol_add()
    w.symbol_add()
    assert [s.address for s in w.project.symbols[-2:]] == ["M0.0", "M0.1"]
    w.dirty = False


def test_u9_refused_transfer_is_not_a_connection_loss():
    from ladderide.comm import CommError, TransferRefused
    assert issubclass(TransferRefused, CommError)
    source = (Path(__file__).parents[1] / "src/ladderide/ui/device_panel.py").read_text(encoding="utf-8")
    assert source.index("except TransferRefused") < source.index("except (CommError, TransportError)")


def test_u10_stale_board_build_does_not_start_the_sketch():
    w = main_window()
    panel = w.esp32_panel
    panel._building = False
    panel.sketch = None
    panel._sketch_built("nao_existe.exe", "")
    assert panel.sketch is None


def test_u11_corrupted_rung_comment_and_empty_branch_are_refused():
    data = latch_project().to_dict()
    data["rungs"][0]["comment"] = 5
    with pytest.raises(ProjectFormatError):
        Project.from_dict(data)
    data = latch_project().to_dict()
    data["rungs"][0]["condition"] = [{"type": "parallel", "branches": []}]
    with pytest.raises(ProjectFormatError):
        Project.from_dict(data)
