"""Infraestrutura compartilhada dos testes.

O fixture `c_vm` compila a VM C do firmware para o computador (gcc ou $CC) e
oferece funcoes para executa-la. Sem compilador, os testes de equivalencia
sao pulados -- a menos que LADDER_REQUIRE_C=1 (usado na CI), quando falham.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VECTORS = ROOT / "shared" / "test-vectors"
VM_DIR = ROOT / "firmware" / "lib" / "ladder_vm"
RUNNER_SRC = ROOT / "firmware" / "test" / "host" / "lv_host_runner.c"
BUILD_DIR = ROOT / "build" / "host"


@dataclass
class CRunResult:
    error: tuple[int, int] | None  # (codigo, indice) se a imagem foi rejeitada
    lines: list[str]


class CVM:
    def __init__(self, exe: Path, workdir: Path):
        self.exe = exe
        self.workdir = workdir
        self._n = 0

    def run(self, image: bytes, scans: list[tuple[int, int]]) -> CRunResult:
        self._n += 1
        path = self.workdir / f"img{self._n}.ldrb"
        path.write_bytes(image)
        stdin = "".join(f"{dt} {inputs:x}\n" for dt, inputs in scans)
        proc = subprocess.run([str(self.exe), "run", str(path)], input=stdin,
                              capture_output=True, text=True, timeout=60)
        out = proc.stdout.splitlines()
        if proc.returncode == 2:
            _, code, index = out[0].split()
            return CRunResult((int(code), int(index)), [])
        if proc.returncode != 0 or out[0] != "OK":
            raise RuntimeError(f"executor C falhou: {proc.returncode} {proc.stderr}")
        return CRunResult(None, out[1:])

    def crc(self, data: bytes) -> tuple[int, int]:
        proc = subprocess.run([str(self.exe), "crc", data.hex()], capture_output=True, text=True, check=True)
        c32, c16 = proc.stdout.split()
        return int(c32, 16), int(c16, 16)


def _compile_runner() -> Path:
    cc = os.environ.get("CC", "gcc")
    if shutil.which(cc) is None:
        raise FileNotFoundError(cc)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    exe = BUILD_DIR / ("lv_host_runner.exe" if sys.platform == "win32" else "lv_host_runner")
    sources = sorted(str(p) for p in VM_DIR.glob("*.c")) + [str(RUNNER_SRC)]
    cmd = [cc, "-std=c99", "-Wall", "-Wextra", "-Werror", "-O2", f"-I{VM_DIR}", *sources, "-o", str(exe)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return exe


@pytest.fixture(scope="session")
def c_vm(tmp_path_factory) -> CVM:
    try:
        exe = _compile_runner()
    except FileNotFoundError:
        if os.environ.get("LADDER_REQUIRE_C") == "1":
            pytest.fail("compilador C nao encontrado e LADDER_REQUIRE_C=1")
        pytest.skip("compilador C (gcc) nao encontrado; testes de equivalencia pulados")
    except subprocess.CalledProcessError as exc:
        pytest.fail(f"falha ao compilar a VM C:\n{exc.stderr}")
    return CVM(exe, tmp_path_factory.mktemp("cvm"))


def load_json(relative: str):
    return json.loads((VECTORS / relative).read_text(encoding="utf-8"))
