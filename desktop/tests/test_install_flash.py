"""Gravacao do firmware pela IDE e instalador do Windows (sem placa e sem mexer no registro)."""
from __future__ import annotations

import importlib.util
import json
import zipfile

import pytest

from conftest import ROOT
from ladderide.comm import flasher


def test_flash_command_matches_platformio_upload(tmp_path, monkeypatch):
    """Mesmos parametros do 'pio run -t upload' (modo detalhado do PlatformIO)."""
    for _, name in flasher.LAYOUT:
        (tmp_path / name).write_bytes(b"\xe9" + name.encode())
    monkeypatch.setattr(flasher, "BUNDLE_DIR", tmp_path)
    (tmp_path / "flash.json").write_text(json.dumps({"version": "1.0.0", "hardware": "hw",
                                                     "parts": [[o, n] for o, n in flasher.LAYOUT]}))
    bundle = flasher.find_firmware()
    assert bundle.source == "incluido na instalacao"
    monkeypatch.setattr(flasher, "esptool_command", lambda: ["esptool"])
    cmd = flasher.flash_command("COM5", bundle)
    assert cmd[:20] == ["esptool", "--chip", "esp32", "--port", "COM5", "--baud", "460800", "--before",
                        "default_reset", "--after", "hard_reset", "write_flash", "-z", "--flash_mode", "dio",
                        "--flash_freq", "40m", "--flash_size", "4MB", "0x1000"]
    assert [c for c in cmd if c.startswith("0x")] == ["0x1000", "0x8000", "0xe000", "0x10000"]
    assert cmd[-1].endswith("firmware.bin")
    (tmp_path / "boot_app0.bin").unlink()
    with pytest.raises(flasher.FlashError, match="boot_app0"):
        flasher.find_firmware()


def test_write_bundle_creates_manifest(tmp_path, monkeypatch):
    src = tmp_path / "src"
    src.mkdir()
    files = []
    for off, name in flasher.LAYOUT:
        (src / name).write_bytes(name.encode())
        files.append((off, src / name))
    monkeypatch.setattr(flasher, "find_firmware", lambda: flasher.FirmwareBundle(files, "1.2.3", "placa"))
    out = flasher.write_bundle(tmp_path / "bin")
    manifest = json.loads((out / "flash.json").read_text())
    assert manifest["parts"] == [[o, n] for o, n in flasher.LAYOUT] and manifest["version"] == "1.2.3"
    assert manifest["baud"] == 460800 and len(manifest["sha256"]) == 4


def test_progress_lines():
    assert flasher.parse_progress("Writing at 0x00010000... (37 %)") == 37
    assert flasher.parse_progress("Wrote 17 bytes (100 %)") is None


@pytest.fixture
def setup_module(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("ladderide_setup", ROOT / "installer" / "ladderide_setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    payload = tmp_path / "payload.zip"
    with zipfile.ZipFile(payload, "w") as z:
        z.writestr("LadderIDE/LadderIDE.exe", b"MZ ide")
        z.writestr("LadderIDE/Desinstalar.exe", b"MZ uninstall")
        z.writestr("LadderIDE/_internal/shared/isa.json", "{}")
        z.writestr("LadderIDE/ladderide-version.json", json.dumps({"version": "9.9.9"}))
    monkeypatch.setattr(mod, "resource", lambda name: tmp_path / name)
    return mod


def test_installer_installs_upgrades_and_uninstalls(setup_module, tmp_path):
    target = tmp_path / "Programs" / "LadderIDE"
    steps = []
    manifest = setup_module.install(target, shortcuts=False, desktop=False, registry=False, associate=False,
                                    progress=lambda pct, text: steps.append(pct))
    assert manifest["version"] == "9.9.9" and steps[-1] == 100
    assert (target / "LadderIDE.exe").read_bytes() == b"MZ ide"
    assert (target / "_internal" / "shared" / "isa.json").exists() and (target / setup_module.MARKER).exists()
    (target / "sobra-da-versao-antiga.txt").write_text("x")
    setup_module.install(target, shortcuts=False, desktop=False, registry=False, associate=False)  # atualizacao
    assert not (target / "sobra-da-versao-antiga.txt").exists()
    setup_module.uninstall(target)
    assert not target.exists()


def test_installer_refuses_foreign_folder(setup_module, tmp_path):
    foreign = tmp_path / "Documentos"
    foreign.mkdir()
    (foreign / "trabalho.docx").write_text("importante")
    with pytest.raises(RuntimeError, match="nao e uma instalacao"):
        setup_module.install(foreign, shortcuts=False, desktop=False, registry=False, associate=False)
    with pytest.raises(RuntimeError, match="nao e uma instalacao"):
        setup_module.uninstall(foreign)
    assert (foreign / "trabalho.docx").read_text() == "importante"
