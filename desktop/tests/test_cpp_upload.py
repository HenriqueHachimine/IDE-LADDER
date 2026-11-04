"""Gravar o C++ gerado na placa (ESP32, Arduino UNO, Mega): projeto PlatformIO e dialogo."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from conftest import ROOT
from ladderide.codegen.cpp import generate_cpp
from ladderide.comm import cpp_upload
from ladderide.comm.cpp_upload import TARGETS, UploadError, avr_io_board, build_command, check, write_project
from ladderide.model.controllers import apply_controller, controller_by_id
from ladderide.model.project import Coil, Contact, Project, Rung

EXAMPLE = ROOT / "examples" / "ambientes" / "simulador_es.ladproj"


def test_projects_for_each_board(tmp_path):
    project = Project.load(EXAMPLE)
    for board in TARGETS:
        folder = write_project(project, board, tmp_path / board)
        src = folder / "src"
        ini = (folder / "platformio.ini").read_text(encoding="utf-8")
        assert f"board = {TARGETS[board].pio_board}" in ini and "framework = arduino" in ini
        assert (src / "programa.cpp").read_text(encoding="utf-8") == generate_cpp(project).text
        assert (src / "io_board.h").exists() and (src / "io_board.cpp").exists()
    assert (tmp_path / "esp32-relay" / "src" / "board_config.h").exists()     # 74HC595/165 do firmware
    uno = (tmp_path / "arduino-uno" / "src" / "io_board.cpp").read_text(encoding="utf-8")
    assert "RELAY_PINS[] = {2, 3, 4, 5, 6, 7, 8, 9}" in uno and "INPUT_PINS[] = {A0, A1, A2, A3, A4, A5, 10, 11}" in uno
    mega = avr_io_board(TARGETS["arduino-mega"].profile, 16)
    assert "RELAY_PINS[] = {22, 23" in mega and "37}" in mega and "INPUT_PINS[] = {38" in mega


def test_sketch_prints_portably_on_avr():
    code = generate_cpp(Project.load(EXAMPLE)).text
    sketch = code[code.rindex("#ifdef ARDUINO"):]
    assert "Serial.printf(" not in sketch.replace("#define PLC_PRINTF(...) Serial.printf(__VA_ARGS__)", "")
    assert "PLC_PRINTF(" in sketch and "Serial.println(PLC_TEXT(" in sketch and "vsnprintf_P" in sketch


def test_project_must_fit_the_board(tmp_path):
    big = Project()
    apply_controller(big, controller_by_id("1747-l40a"))          # 24 entradas
    big.rungs = [Rung([Contact("XIC", "I2.0")], [Coil("OTE", "Q1.0")])]
    problems = check(big, "arduino-uno")
    assert any("24 entradas" in p for p in problems) and any("16 saídas" in p for p in problems)
    with pytest.raises(UploadError):
        write_project(big, "arduino-uno", tmp_path / "x")
    bad = Project()
    bad.rungs = [Rung([Contact("XIC", "")], [Coil("OTE", "Q0.0")])]
    assert any("erro" in p for p in check(bad, "esp32-relay"))
    assert check(big, "nada") == ["placa desconhecida: nada"]


def test_build_command(monkeypatch, tmp_path):
    monkeypatch.setattr(cpp_upload, "pio_command", lambda: ["pio"])
    assert build_command(tmp_path) == ["pio", "run", "-d", str(tmp_path)]
    assert build_command(tmp_path, True, "COM7") == ["pio", "run", "-d", str(tmp_path), "-t", "upload",
                                                       "--upload-port", "COM7"]


def test_dialog_suggests_board_and_blocks_incompatible_project(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.cpp_upload_dialog import CppUploadDialog
    QApplication.instance() or QApplication([])
    monkeypatch.setattr("ladderide.ui.cpp_upload_dialog.list_serial_ports", lambda: [("COM9", "USB-SERIAL CH340")])
    dlg = CppUploadDialog(Project.load(EXAMPLE), "arduino-uno")
    assert dlg.selected_board() == "arduino-uno" and dlg.selected_port() == "COM9"
    assert dlg.upload_btn.isEnabled() and "D2 a D9" in dlg.status.text()
    big = Project()
    apply_controller(big, controller_by_id("arduino-mega"))
    big.rungs = [Rung([Contact("XIC", "I1.7")], [Coil("OTE", "Q1.7")])]
    dlg = CppUploadDialog(big, "arduino-uno")
    assert not dlg.upload_btn.isEnabled() and "16 entradas" in dlg.status.text()
    dlg.board.setCurrentIndex(dlg.board.findData("arduino-mega"))
    assert dlg.upload_btn.isEnabled()


@pytest.mark.skipif(not shutil.which("pio"), reason="PlatformIO não instalado")
def test_uno_build_fits_in_2kb_ram(tmp_path):
    home = os.path.expanduser("~/.platformio/platforms/atmelavr")
    if not os.path.isdir(home):
        pytest.skip("plataforma atmelavr do PlatformIO não instalada")
    folder = write_project(Project.load(EXAMPLE), "arduino-uno", tmp_path / "uno")
    proc = subprocess.run(build_command(folder), capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert "RAM:" in proc.stdout


def test_pio_found_outside_path(monkeypatch, tmp_path):
    monkeypatch.setattr(cpp_upload.shutil, "which", lambda name: None)
    monkeypatch.setattr(cpp_upload.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(cpp_upload.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(UploadError, match="PlatformIO não encontrado"):
        cpp_upload.pio_command()
    pio = cpp_upload._pio_candidates()[1]                 # ~/.local/bin/pio (pipx no Linux)
    pio.parent.mkdir(parents=True)
    pio.write_text("")
    assert cpp_upload.pio_command() == [str(pio)]
