"""Compila e inicia o dispositivo virtual (firmware/test/host/virtual_device.c).

O dispositivo virtual executa o mesmo codigo C do firmware (plc_core +
ladder_vm) no PC. Permite testar transferencia e monitor sem a placa.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..core.isa import ISA_PATH
from .transport import ProcessTransport

ROOT = ISA_PATH.parents[2]
FIRMWARE = ROOT / "firmware"
BUILD = ROOT / "build" / "host"
EXE_SUFFIX = ".exe" if sys.platform == "win32" else ""


class BuildError(RuntimeError):
    pass


def host_tool(name: str, rebuild: bool = False) -> Path:
    """Caminho do executavel `name` (compila com gcc/$CC se necessario ou desatualizado)."""
    exe = BUILD / f"{name}{EXE_SUFFIX}"
    sources = (sorted((FIRMWARE / "lib" / "ladder_vm").glob("*.c"))
               + sorted((FIRMWARE / "lib" / "plc_core").glob("*.c"))
               + [FIRMWARE / "test" / "host" / f"{name}.c"])
    headers = list((FIRMWARE / "lib").rglob("*.h"))
    if exe.exists() and not rebuild:
        newest = max(p.stat().st_mtime for p in sources + headers)
        if exe.stat().st_mtime >= newest:
            return exe
    cc = os.environ.get("CC", "gcc")
    if shutil.which(cc) is None:
        raise BuildError(f"compilador C '{cc}' nao encontrado (instale o MinGW/gcc)")
    BUILD.mkdir(parents=True, exist_ok=True)
    cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O2",
           f"-I{FIRMWARE / 'lib' / 'ladder_vm'}", f"-I{FIRMWARE / 'lib' / 'plc_core'}",
           *map(str, sources), "-o", str(exe)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BuildError(proc.stderr)
    return exe


def start_virtual_device(storage: Path, *extra: str) -> ProcessTransport:
    exe = host_tool("virtual_device")
    return ProcessTransport([str(exe), str(storage), *extra])
