"""Exemplos Arduino da placa (firmware/examples) rodando no PC, para o simulador da IDE.

O sketch e compilado com g++ junto com src/io_board.cpp (o mesmo codigo de E/S
do firmware) e com firmware/test/host/arduino_sim, que imita o Arduino:
pinos digitais, tempo e Serial. Os GPIOs dos registradores ligam um 74HC595 e
um 74HC165 simulados no nivel de clock/latch, configurados por board_config.h.
O processo conversa com a IDE por linhas de texto (ver arduino_sim.cpp).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .virtual import BUILD, EXE_SUFFIX, FIRMWARE, BuildError

EXAMPLES = FIRMWARE / "examples"
SIM_DIR = FIRMWARE / "test" / "host" / "arduino_sim"


def list_sketches() -> list[str]:
    """Exemplos disponiveis (pastas de firmware/examples com arquivos .cpp)."""
    if not EXAMPLES.is_dir():
        return []
    return sorted(d.name for d in EXAMPLES.iterdir() if d.is_dir() and any(d.glob("*.cpp")))


def _cxx() -> str:
    for name in (os.environ.get("CXX"), "g++", "c++", "clang++"):
        if name and shutil.which(name):
            return name
    raise BuildError("compilador C++ nao encontrado (instale o MinGW/g++)")


def _builds(name: str) -> list[Path]:
    """Executaveis ja compilados do exemplo (sketch_<name>.exe antigo ou sketch_<name>_<hash>.exe)."""
    pattern = re.compile(rf"sketch_{re.escape(name)}(_[0-9a-f]{{10}})?{re.escape(EXE_SUFFIX)}")
    return [p for p in BUILD.glob("sketch_*") if pattern.fullmatch(p.name)] if BUILD.is_dir() else []


def build_sketch(name: str, rebuild: bool = False) -> Path:
    """Compila firmware/examples/<name> para o PC. Recompila so se algo mudou.

    O executavel leva no nome um hash das fontes: no Windows um sketch em uso
    (outra janela da IDE com a placa ligada) nao pode ser sobrescrito, entao
    cada versao do codigo vira um arquivo novo e as antigas sao apagadas quando
    estiverem livres.
    """
    folder = EXAMPLES / name
    if getattr(sys, "frozen", False) or not folder.is_dir():
        found = sorted(_builds(name), key=lambda p: p.stat().st_mtime)
        if found:
            return found[-1]
        raise BuildError(f"exemplo '{name}' nao encontrado")
    sources = sorted(folder.glob("*.cpp")) + [FIRMWARE / "src" / "io_board.cpp", SIM_DIR / "arduino_sim.cpp"]
    deps = sources + sorted(folder.glob("*.h")) + [SIM_DIR / "Arduino.h", FIRMWARE / "src" / "board_config.h",
                                                   FIRMWARE / "src" / "io_board.h"]
    digest = hashlib.sha1(b"".join(p.read_bytes() for p in deps)).hexdigest()[:10]
    exe = BUILD / f"sketch_{name}_{digest}{EXE_SUFFIX}"
    if exe.exists() and not rebuild:
        return exe
    BUILD.mkdir(parents=True, exist_ok=True)
    for old in _builds(name):
        try:
            old.unlink()
        except OSError:
            pass                                    # em uso: fica para a proxima vez
    cmd = [_cxx(), "-std=gnu++11", "-O1", "-Wall", "-DARDUINO=10819", "-DARDUINO_SIM=1",
           f"-I{SIM_DIR}", f"-I{FIRMWARE / 'src'}", f"-I{folder}", *map(str, sources), "-o", str(exe)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise BuildError(proc.stderr.strip() or proc.stdout.strip())
    return exe


@dataclass
class BoardState:
    relays: int          # canais de rele energizados (bit k = OUTk+1)
    oe: int              # nivel do /OE do 74HC595 (1 = saidas desabilitadas)
    q595: int            # byte nas saidas Q7..Q0 do 74HC595 (nivel eletrico)
    load165: int         # ultimo byte carregado no 74HC165 (nivel eletrico, bit 7 = primeiro lido)
    clock_edges: int


class SketchProcess:
    """Processo do sketch. Os callbacks sao chamados na thread de leitura."""

    def __init__(self, exe: Path, on_serial: Callable[[bytes], None], on_board: Callable[[BoardState], None],
                 on_exit: Callable[[int], None]):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, bufsize=0, creationflags=flags)
        self._lock = threading.Lock()
        self.on_serial, self.on_board, self.on_exit = on_serial, on_board, on_exit
        self.booted = threading.Event()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for raw in iter(self._proc.stdout.readline, b""):
            line = raw.decode("ascii", "replace").strip()
            if line == "BOOT":
                self.booted.set()
            elif line.startswith("SER "):
                try:
                    self.on_serial(bytes.fromhex(line[4:]))
                except ValueError:
                    pass
            elif line.startswith("BRD "):
                parts = line.split()
                if len(parts) == 6:
                    self.on_board(BoardState(int(parts[1], 16), int(parts[2]), int(parts[3], 16),
                                             int(parts[4], 16), int(parts[5])))
        self.on_exit(self._proc.wait())

    def _send(self, text: str) -> None:
        with self._lock:
            if self._proc.poll() is not None:
                return
            try:
                self._proc.stdin.write(text.encode("ascii"))
                self._proc.stdin.flush()
            except (OSError, ValueError):
                pass

    def send_serial(self, data: bytes) -> None:
        if data:
            self._send(f"SER {data.hex()}\n")

    def set_inputs(self, mask: int) -> None:
        self._send(f"IN {mask & 0xFFFF:x}\n")

    @property
    def running(self) -> bool:
        return self._proc.poll() is None

    def close(self) -> None:
        with self._lock:
            try:
                self._proc.stdin.close()            # o sketch encerra ao perder a entrada
            except OSError:
                pass
        try:
            self._proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            self._proc.kill()
