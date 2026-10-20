"""Gravacao do firmware do CLP na placa ESP32 pela IDE (sem PlatformIO).

Usa o esptool como programa separado, com os mesmos parametros do
`pio run -e esp32dev -t upload` (conferidos no modo detalhado do PlatformIO):

    esptool --chip esp32 --port COMx --baud 460800 --before default_reset
            --after hard_reset write_flash -z --flash_mode dio --flash_freq 40m
            --flash_size 4MB 0x1000 bootloader.bin 0x8000 partitions.bin
            0xe000 boot_app0.bin 0x10000 firmware.bin

Na instalacao, os quatro arquivos e o esptool.exe vem junto com a IDE
(firmware/bin e tools/). Na pasta do projeto, usa a ultima compilacao do
PlatformIO (firmware/.pio/build/esp32dev) e o esptool do PlatformIO.
A gravacao nao apaga a particao de dados: o programa LADDER gravado antes
continua la (e, se for de um formato antigo, o firmware entra em FAULT ate a
proxima transferencia).
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .virtual import EXE_SUFFIX, FIRMWARE, ROOT

LAYOUT = [(0x1000, "bootloader.bin"), (0x8000, "partitions.bin"), (0xE000, "boot_app0.bin"),
          (0x10000, "firmware.bin")]
FLASH_ARGS = {"chip": "esp32", "baud": 460800, "flash_mode": "dio", "flash_freq": "40m", "flash_size": "4MB"}
BUNDLE_DIR = ROOT / "firmware" / "bin"                  # na instalacao
PIO_BUILD = FIRMWARE / ".pio" / "build" / "esp32dev"     # na pasta do projeto
PIO_HOME = Path.home() / ".platformio" / "packages"
BOOT_APP0 = PIO_HOME / "framework-arduinoespressif32" / "tools" / "partitions" / "boot_app0.bin"
PIO_ESPTOOL = PIO_HOME / "tool-esptoolpy" / "esptool.py"


class FlashError(RuntimeError):
    pass


@dataclass
class FirmwareBundle:
    files: list[tuple[int, Path]]
    version: str = "?"
    hardware: str = "?"
    source: str = ""
    sha256: dict[str, str] = field(default_factory=dict)

    def describe(self) -> str:
        parts = ", ".join(f"{p.name} em 0x{off:x}" for off, p in self.files)
        return f"firmware {self.version} ({self.hardware}), {self.source}: {parts}"


def _board_defines() -> tuple[str, str]:
    path = FIRMWARE / "src" / "board_config.h"
    if not path.exists():
        return "?", "?"
    text = path.read_text(encoding="utf-8", errors="replace")
    get = (lambda n: (re.search(rf'#define\s+{n}\s+"([^"]*)"', text) or [None, "?"])[1])
    return get("FW_VERSION"), get("HW_ID")


def find_firmware() -> FirmwareBundle:
    """Arquivos do firmware: os empacotados com a IDE ou a ultima compilacao do PlatformIO."""
    manifest = BUNDLE_DIR / "flash.json"
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        files = [(int(off), BUNDLE_DIR / name) for off, name in data["parts"]]
        missing = [p.name for _, p in files if not p.exists()]
        if missing:
            raise FlashError(f"instalacao incompleta: faltam {', '.join(missing)}")
        return FirmwareBundle(files, data.get("version", "?"), data.get("hardware", "?"), "incluido na instalacao",
                              data.get("sha256", {}))
    files = [(off, BOOT_APP0 if name == "boot_app0.bin" else PIO_BUILD / name) for off, name in LAYOUT]
    missing = [str(p) for _, p in files if not p.exists()]
    if missing:
        raise FlashError("firmware nao compilado. Na pasta firmware/, rode:  pio run -e esp32dev\n"
                         "Faltam: " + ", ".join(missing))
    version, hardware = _board_defines()
    return FirmwareBundle(files, version, hardware, "compilado pelo PlatformIO")


def esptool_command() -> list[str]:
    """Como chamar o esptool: o executavel instalado, o modulo Python ou o do PlatformIO."""
    bundled = ROOT / "tools" / f"esptool{EXE_SUFFIX}"
    if bundled.exists():
        return [str(bundled)]
    if getattr(sys, "frozen", False):
        raise FlashError("esptool nao incluido nesta instalacao")
    try:
        import esptool  # noqa: F401
        return [sys.executable, "-m", "esptool"]
    except ImportError:
        pass
    if PIO_ESPTOOL.exists():
        return [sys.executable, str(PIO_ESPTOOL)]
    if shutil.which("esptool"):
        return ["esptool"]
    raise FlashError("esptool nao encontrado (instale com:  python -m pip install esptool)")


def flash_command(port: str, bundle: FirmwareBundle, baud: int | None = None) -> list[str]:
    a = FLASH_ARGS
    cmd = esptool_command() + [
        "--chip", a["chip"], "--port", port, "--baud", str(baud or a["baud"]),
        "--before", "default_reset", "--after", "hard_reset", "write_flash", "-z",
        "--flash_mode", a["flash_mode"], "--flash_freq", a["flash_freq"], "--flash_size", a["flash_size"]]
    for off, path in bundle.files:
        cmd += [f"0x{off:x}", str(path)]
    return cmd


def write_bundle(target: Path) -> Path:
    """Copia o firmware compilado para `target` com o manifesto flash.json (usado no empacotamento)."""
    bundle = find_firmware()
    target.mkdir(parents=True, exist_ok=True)
    parts, sums = [], {}
    for off, path in bundle.files:
        dest = target / path.name
        shutil.copyfile(path, dest)
        parts.append([off, path.name])
        sums[path.name] = hashlib.sha256(dest.read_bytes()).hexdigest()
    manifest = {"version": bundle.version, "hardware": bundle.hardware, "parts": parts, "sha256": sums,
                **FLASH_ARGS}
    (target / "flash.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return target


_PROGRESS = re.compile(r"\((\d+)\s*%\)")


def parse_progress(line: str) -> int | None:
    """Porcentagem das linhas 'Writing at 0x... (37 %)' do esptool."""
    m = _PROGRESS.search(line)
    return int(m[1]) if m and "Writing" in line else None
