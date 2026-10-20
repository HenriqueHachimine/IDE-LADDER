#!/usr/bin/env python3
"""Gera o instalador do Windows: dist/LadderIDE-Setup-<versao>.exe.

Uso (no Windows, com PyInstaller, gcc/g++ e, para gravar a placa pela IDE, PlatformIO):
    python -m pip install pyinstaller
    python scripts/build_installer.py            # empacota a IDE e monta o instalador
    python scripts/build_installer.py --skip-app # reaproveita dist/LadderIDE ja gerado

O instalador (installer/ladderide_setup.py) e um unico .exe com a IDE dentro.
Instala por usuario, sem administrador: pasta em %LOCALAPPDATA%\\Programs, atalhos,
associacao de .ladproj e desinstalador em "Aplicativos instalados".
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
APP_DIR = DIST / "LadderIDE"
WORK = ROOT / "build" / "installer"
SETUP_SRC = ROOT / "installer" / "ladderide_setup.py"


def version() -> str:
    text = (ROOT / "desktop" / "pyproject.toml").read_text(encoding="utf-8")
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)[1]


def pyinstaller(*args: str) -> None:
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
           "--workpath", str(WORK / "pyinstaller"), "--specpath", str(WORK), *args]
    if subprocess.call(cmd) != 0:
        raise SystemExit("falha no PyInstaller: " + " ".join(cmd))


def main() -> int:
    if sys.platform != "win32":
        print("O instalador e so para Windows. No Linux use scripts/build_app.py (gera um .tar.gz).")
        return 1
    if "--skip-app" not in sys.argv:
        if subprocess.call([sys.executable, str(ROOT / "scripts" / "build_app.py")]) != 0:
            return 1
    if not (APP_DIR / "LadderIDE.exe").exists():
        raise SystemExit("dist/LadderIDE/LadderIDE.exe nao existe; rode sem --skip-app")
    ver = version()
    ico = ROOT / "build" / "ladderide.ico"
    WORK.mkdir(parents=True, exist_ok=True)
    sep = ";"

    # 1. desinstalador (o mesmo programa, sem a IDE dentro), copiado para a pasta da IDE
    pyinstaller("--name", "Desinstalar", "--distpath", str(WORK), "--icon", str(ico),
                "--add-data", f"{ico}{sep}.", str(SETUP_SRC))
    shutil.copyfile(WORK / "Desinstalar.exe", APP_DIR / "Desinstalar.exe")
    (APP_DIR / "ladderide-version.json").write_text(
        json.dumps({"version": ver, "built": datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")

    # 2. payload: a pasta da IDE inteira
    payload = WORK / "payload.zip"
    files = [p for p in APP_DIR.rglob("*") if p.is_file()]
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for p in files:
            z.write(p, "LadderIDE/" + p.relative_to(APP_DIR).as_posix())
    print(f"payload: {len(files)} arquivos, {payload.stat().st_size / 1e6:.1f} MB")

    # 3. instalador com o payload dentro
    name = f"LadderIDE-Setup-{ver}"
    pyinstaller("--name", name, "--distpath", str(DIST), "--icon", str(ico),
                "--add-data", f"{payload}{sep}.", "--add-data", f"{ico}{sep}.", str(SETUP_SRC))
    out = DIST / f"{name}.exe"
    print(f"Instalador: {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
