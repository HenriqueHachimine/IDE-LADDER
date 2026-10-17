#!/usr/bin/env python3
"""Gera a distribuicao Windows da IDE com PyInstaller (pasta dist/LadderIDE).

Uso:
    python -m pip install pyinstaller
    python scripts/build_windows.py

Inclui: especificacoes (isa.json/protocol.json), exemplos e o dispositivo
virtual pre-compilado (requer gcc no momento do empacotamento).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop" / "src"))


def main() -> int:
    from ladderide.comm.virtual import host_tool

    device = host_tool("virtual_device", rebuild=True)
    runner = host_tool("lv_host_runner", rebuild=True)      # VM C usada em "Verificar para ESP32"
    launcher = ROOT / "build" / "launcher.py"
    launcher.parent.mkdir(exist_ok=True)
    launcher.write_text("import sys\nfrom ladderide.__main__ import main\nsys.exit(main())\n", encoding="utf-8")
    sep = ";" if sys.platform == "win32" else ":"
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
        "--collect-submodules", "ladderide.envs.builtin",     # ambientes carregados dinamicamente
        "--exclude-module", "PySide6.QtWebEngineCore", "--exclude-module", "PySide6.QtWebEngineWidgets",
        "--exclude-module", "PySide6.QtQuick", "--exclude-module", "PySide6.QtQml",
        str(launcher),
    ]
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
