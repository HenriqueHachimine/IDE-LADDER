"""Exemplos Arduino da placa (firmware/examples) rodando no PC, para o simulador da IDE.

O sketch e compilado com g++ junto com src/io_board.cpp (o mesmo codigo de E/S
do firmware) e com firmware/test/host/arduino_sim, que imita o Arduino:
pinos digitais, tempo e Serial. Os GPIOs dos registradores ligam um 74HC595 e
um 74HC165 simulados no nivel de clock/latch, configurados por board_config.h.
O processo conversa com a IDE por linhas de texto (ver arduino_sim.cpp).
"""
from __future__ import annotations

import os
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


def build_sketch(name: str, rebuild: bool = False) -> Path:
    """Compila firmware/examples/<name> para o PC. Recompila so se algo mudou."""
    folder = EXAMPLES / name
    exe = BUILD / f"sketch_{name}{EXE_SUFFIX}"
    if getattr(sys, "frozen", False) or not folder.is_dir():
        if exe.exists():
            return exe
        raise BuildError(f"exemplo '{name}' nao encontrado")
    sources = sorted(folder.glob("*.cpp")) + [FIRMWARE / "src" / "io_board.cpp", SIM_DIR / "arduino_sim.cpp"]
    deps = sources + list(folder.glob("*.h")) + [SIM_DIR / "Arduino.h", FIRMWARE / "src" / "board_config.h",
                                                 FIRMWARE / "src" / "io_board.h"]
    if exe.exists() and not rebuild and exe.stat().st_mtime >= max(p.stat().st_mtime for p in deps):
        return exe
    BUILD.mkdir(parents=True, exist_ok=True)
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
