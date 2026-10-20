#!/usr/bin/env python3
"""Gera a distribuicao da IDE com PyInstaller para o sistema atual (Windows ou Linux).

Uso (no sistema de destino; o PyInstaller nao faz compilacao cruzada):
    python -m pip install pyinstaller
    python scripts/build_app.py

Saida: dist/LadderIDE/ (executavel LadderIDE.exe ou LadderIDE). No Linux tambem
gera dist/LadderIDE-linux-<arq>.tar.gz com icone, atalho de menu (.desktop) e
install.sh. Inclui especificacoes, exemplos, a VM C e o dispositivo virtual
pre-compilados (requer gcc no momento do empacotamento), os exemplos Arduino
pre-compilados para o simulador da placa (g++) e, se o PlatformIO estiver
instalado, o firmware compilado com o esptool para gravar a placa pela IDE.
O instalador do Windows sai de scripts/build_installer.py.
"""
from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop" / "src"))

DESKTOP_ENTRY = """[Desktop Entry]
Type=Application
Name=LadderIDE
GenericName=IDE LADDER para CLP com ESP32
Comment=Editor, simulador e transferencia de programas LADDER
Exec={exec} %f
Icon={icon}
Terminal=false
Categories=Development;Education;Electronics;
MimeType=application/x-ladderide-project;
"""

INSTALL_SH = """#!/bin/sh
# Registra a LadderIDE no menu de aplicativos do usuario (sem root).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$APPS"
sed -e "s#@EXEC@#$DIR/LadderIDE#" -e "s#@ICON@#$DIR/ladderide.png#" "$DIR/ladderide.desktop.in" \\
    > "$APPS/ladderide.desktop"
chmod +x "$DIR/LadderIDE"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" || true
echo "LadderIDE instalada no menu. Para usar a porta serial do ESP32:"
echo "  sudo usermod -aG dialout $USER   (depois saia e entre na sessao)"
"""


def make_icon(path: Path) -> None:
    """Icone 256x256 desenhado com Qt (trilhos, contato e bobina)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841 - precisa existir
    img = QImage(256, 256, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#1e293b"))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(QRectF(8, 8, 240, 240), 44, 44)
    pen = QPen(QColor("#e2e8f0"), 14, Qt.SolidLine, Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(48, 52), QPointF(48, 204))
    p.drawLine(QPointF(208, 52), QPointF(208, 204))
    p.setPen(QPen(QColor("#22c55e"), 10, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(48, 128), QPointF(92, 128))
    p.drawLine(QPointF(92, 100), QPointF(92, 156))
    p.drawLine(QPointF(118, 100), QPointF(118, 156))
    p.drawLine(QPointF(118, 128), QPointF(148, 128))
    p.drawArc(QRectF(146, 104, 30, 48), 100 * 16, 160 * 16)
    p.drawArc(QRectF(160, 104, 30, 48), -80 * 16, 160 * 16)
    p.drawLine(QPointF(190, 128), QPointF(208, 128))
    p.end()
    img.save(str(path))


def firmware_and_esptool(sep: str) -> list[str]:
    """Firmware compilado (pio) e esptool como executavel separado, para 'Gravar firmware na placa'."""
    from ladderide.comm import flasher
    pio = shutil.which("pio") or shutil.which("platformio")
    if pio is None and not (flasher.PIO_BUILD / "firmware.bin").exists():
        print("AVISO: PlatformIO nao encontrado: a instalacao nao vai gravar o firmware na placa")
        return []
    if pio is not None:
        code = subprocess.call([pio, "run", "-e", "esp32dev", "-d", str(ROOT / "firmware")])
        if code != 0:
            raise SystemExit("falha ao compilar o firmware (pio run -e esp32dev)")
    bundle = flasher.write_bundle(ROOT / "build" / "firmware_bin")
    args = ["--add-data", f"{bundle}{sep}firmware/bin"]
    tool_dir = flasher.PIO_ESPTOOL.parent
    if not flasher.PIO_ESPTOOL.exists():
        print("AVISO: esptool do PlatformIO nao encontrado: a instalacao nao vai gravar o firmware na placa")
        return args
    # esptool (GPL-2.0) vai como programa separado, com a licenca e a origem ao lado
    tools = ROOT / "build" / "tools"
    code = subprocess.call([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console", "--name", "esptool",
        "--distpath", str(tools), "--workpath", str(ROOT / "build" / "pyinstaller_esptool"),
        "--specpath", str(ROOT / "build"), "--paths", str(tool_dir),
        "--add-data", f"{tool_dir / 'esptool' / 'targets' / 'stub_flasher'}{sep}esptool/targets/stub_flasher",
        str(flasher.PIO_ESPTOOL)])
    if code != 0:
        raise SystemExit("falha ao empacotar o esptool")
    shutil.copyfile(tool_dir / "LICENSE", tools / "esptool-LICENSE.txt")
    (tools / "esptool-LEIA.txt").write_text(
        "esptool.exe: esptool.py 4.5.1 (Espressif Systems, GPL-2.0-or-later), empacotado sem alteracoes\n"
        "a partir do pacote tool-esptoolpy do PlatformIO. Codigo-fonte: https://github.com/espressif/esptool\n",
        encoding="utf-8")
    exe = tools / f"esptool{'.exe' if sys.platform == 'win32' else ''}"
    return args + ["--add-binary", f"{exe}{sep}tools", "--add-data", f"{tools / 'esptool-LICENSE.txt'}{sep}tools",
                   "--add-data", f"{tools / 'esptool-LEIA.txt'}{sep}tools"]


def make_ico(png: Path) -> Path:
    """Icone .ico para o executavel do Windows (o mesmo desenho do .png)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication, QImage
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841
    ico = png.with_suffix(".ico")
    QImage(str(png)).save(str(ico), "ICO")
    return ico


def main() -> int:
    from ladderide.comm.sketch import build_sketch, list_sketches
    from ladderide.comm.virtual import host_tool

    device = host_tool("virtual_device", rebuild=True)
    runner = host_tool("lv_host_runner", rebuild=True)      # VM C usada em "Verificar para ESP32"
    sketches = [build_sketch(name, rebuild=True) for name in list_sketches()]   # simulador da placa
    launcher = ROOT / "build" / "launcher.py"
    launcher.parent.mkdir(exist_ok=True)
    launcher.write_text("import sys\nfrom ladderide.__main__ import main\nsys.exit(main())\n", encoding="utf-8")
    icon = ROOT / "build" / "ladderide.png"
    make_icon(icon)
    ico = make_ico(icon) if sys.platform == "win32" else None
    sep = os.pathsep                                        # ";" no Windows, ":" no Linux
    extra = firmware_and_esptool(sep)
    for exe in sketches:
        extra += ["--add-binary", f"{exe}{sep}build/host"]
    cmd = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
        "--name", "LadderIDE",
        "--distpath", str(ROOT / "dist"), "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT / "desktop" / "src"),
        "--add-data", f"{ROOT / 'shared' / 'specifications'}{sep}shared/specifications",
        "--add-data", f"{ROOT / 'examples'}{sep}examples",
        "--add-binary", f"{device}{sep}build/host",
        "--add-binary", f"{runner}{sep}build/host",
        "--add-data", f"{ROOT / 'firmware' / 'src' / 'board_config.h'}{sep}firmware/src",
        *extra,
        "--collect-submodules", "ladderide.envs.builtin",     # ambientes carregados dinamicamente
        "--icon", str(ico) if ico else "NONE",
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtQml",
        str(launcher),
    ]
    print(" ".join(cmd))
    code = subprocess.call(cmd)
    if code != 0 or not sys.platform.startswith("linux"):
        return code

    dist = ROOT / "dist" / "LadderIDE"
    (dist / "ladderide.png").write_bytes(icon.read_bytes())
    (dist / "ladderide.desktop.in").write_text(DESKTOP_ENTRY.format(exec="@EXEC@", icon="@ICON@"), encoding="utf-8")
    install = dist / "install.sh"
    install.write_text(INSTALL_SH, encoding="utf-8", newline="\n")
    install.chmod(install.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    archive = ROOT / "dist" / f"LadderIDE-linux-{platform.machine()}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(dist, arcname="LadderIDE")
    print(f"Pacote Linux: {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
