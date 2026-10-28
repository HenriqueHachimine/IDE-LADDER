"""Gravar o C++ gerado direto na placa (ESP32, Arduino UNO, Arduino Mega) com o PlatformIO.

O C++ do diagrama (codegen/cpp.py) vira o programa da placa, sem o
interpretador do CLP: monta-se um projeto PlatformIO em
~/.ladderide/gravar_cpp/<placa> com

    src/programa.cpp    o C++ gerado (secao #ifdef ARDUINO: setup/loop e monitor serial)
    src/io_board.*      E/S da placa: na ESP32, o mesmo io_board.cpp do firmware
                        (74HC595/74HC165); no UNO e no Mega, um gerado aqui, com os
                        pinos da aba Placa (comm/board_profiles.py)

e roda `pio run` (compilar) ou `pio run -t upload --upload-port COMx` (gravar).
Na primeira vez o PlatformIO baixa o compilador da placa (atmelavr ou
espressif32). A pasta fica guardada para as proximas gravacoes serem rapidas.

Gravar o C++ substitui o firmware do CLP: depois disso a IDE nao transfere
programas para a placa ate o firmware ser gravado de novo (Gravar firmware).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from ..codegen.cpp import generate_cpp
from ..model.project import Project
from .board_profiles import PROFILES, BoardProfile
from .virtual import FIRMWARE

WORK_DIR = Path.home() / ".ladderide" / "gravar_cpp"


class UploadError(Exception):
    pass


@dataclass(frozen=True)
class Target:
    board: str                      # perfil da aba Placa
    platform: str                   # plataforma do PlatformIO
    pio_board: str
    note: str

    @property
    def profile(self) -> BoardProfile:
        return PROFILES[self.board]


TARGETS: dict[str, Target] = {
    "esp32-relay": Target("esp32-relay", "espressif32@6.9.0", "esp32dev",
                          "Se a placa não entrar em gravação sozinha: segure BOOT, aperte e solte RST, solte BOOT."),
    "arduino-uno": Target("arduino-uno", "atmelavr", "uno",
                          "Relés nos pinos D2 a D9 e entradas em A0 a A5, D10 e D11 (com pull-up interno)."),
    "arduino-mega": Target("arduino-mega", "atmelavr", "megaatmega2560",
                           "Relés nos pinos D22 a D37 e entradas em D38 a D53 (com pull-up interno)."),
}


def _pio_candidates() -> list[Path]:
    """Lugares comuns do pio fora do PATH (atalho do menu no Linux nao carrega ~/.local/bin)."""
    home = Path.home()
    exe = ".exe" if sys.platform == "win32" else ""
    return [home / ".platformio" / "penv" / ("Scripts" if sys.platform == "win32" else "bin") / f"pio{exe}",
            home / ".local" / "bin" / "pio"]


def pio_command() -> list[str]:
    """Como chamar o PlatformIO: o executavel no PATH, o do instalador do PlatformIO ou o modulo Python."""
    for name in ("pio", "platformio"):
        found = shutil.which(name)
        if found:
            return [found]
    for path in _pio_candidates():
        if path.is_file():
            return [str(path)]
    if not getattr(sys, "frozen", False) and importlib.util.find_spec("platformio") is not None:
        return [sys.executable, "-m", "platformio"]
    raise UploadError("PlatformIO não encontrado. Instale com:  python -m pip install platformio  "
                      "(Linux: pipx install platformio) e abra a IDE de novo")


def check(project: Project, board: str) -> list[str]:
    """Problemas que impedem gravar o projeto nesta placa (vazio = pode gravar)."""
    target = TARGETS.get(board)
    if target is None:
        return [f"placa desconhecida: {board}"]
    prof, io = target.profile, project.io
    problems = []
    if io.n_inputs > prof.n_inputs:
        problems.append(f"o projeto tem {io.n_inputs} entradas e a {prof.name} tem {prof.n_inputs}")
    if io.n_outputs > prof.max_relays:
        problems.append(f"o projeto tem {io.n_outputs} saídas e a {prof.name} aceita até {prof.max_relays} relés")
    code = generate_cpp(project)
    if code.errors:
        problems.append(f"o diagrama tem {code.errors} erro(s): corrija antes de gravar")
    return problems


def avr_io_board(profile: BoardProfile, relays: int) -> str:
    """io_board.cpp do Arduino: rele k no pino relay_pins[k], entrada k em input_pins[k]."""
    def pin(name: str) -> str:                    # "D10" -> 10 (o Arduino nao define D10); "A0" fica
        return name[1:] if name.startswith("D") else name
    relay_pins = ", ".join(pin(p) for p in profile.relay_pins[:relays])
    input_pins = ", ".join(pin(p) for p in profile.input_pins[:profile.n_inputs])
    return "\n".join([
        f"// E/S do {profile.name} para o C++ gerado pela LadderIDE (mesmos pinos da aba Placa).",
        "// Modulos de rele comuns acionam em nivel baixo; entradas com pull-up interno e chave",
        "// ligada ao GND (fechada = 1). Ajuste os dois #define se a sua montagem for diferente.",
        "#include <Arduino.h>",
        '#include "io_board.h"',
        "",
        "#define RELAY_ACTIVE_LOW 1",
        "#define INPUT_ACTIVE_LOW 1",
        "",
        f"static const uint8_t RELAY_PINS[] = {{{relay_pins}}};",
        f"static const uint8_t INPUT_PINS[] = {{{input_pins}}};",
        "static const uint8_t N_RELAYS = sizeof(RELAY_PINS);",
        "static const uint8_t N_INPUTS = sizeof(INPUT_PINS);",
        "static uint16_t last_inputs = 0;",
        "",
        "static void relay_write(uint8_t pin, bool on) {",
        "    digitalWrite(pin, (on != (RELAY_ACTIVE_LOW != 0)) ? HIGH : LOW);",
        "}",
        "",
        "void io_board_begin(void) {",
        "    for (uint8_t k = 0; k < N_RELAYS; k++) {     // desligado antes de virar saida",
        "        relay_write(RELAY_PINS[k], false);",
        "        pinMode(RELAY_PINS[k], OUTPUT);",
        "    }",
        "    for (uint8_t k = 0; k < N_INPUTS; k++) pinMode(INPUT_PINS[k], INPUT_PULLUP);",
        "}",
        "",
        "uint16_t io_board_transfer(uint16_t outputs) {",
        "    for (uint8_t k = 0; k < N_RELAYS; k++) relay_write(RELAY_PINS[k], (outputs >> k) & 1u);",
        "    uint16_t in = 0;",
        "    for (uint8_t k = 0; k < N_INPUTS; k++) {",
        "        bool level = digitalRead(INPUT_PINS[k]) == HIGH;",
        "        if (level != (INPUT_ACTIVE_LOW != 0)) in |= (uint16_t)(1u << k);",
        "    }",
        "    last_inputs = in;",
        "    return in;",
        "}",
        "",
        "uint16_t io_board_last_inputs(void) { return last_inputs; }",
        ""])


def platformio_ini(target: Target) -> str:
    return "\n".join([
        "; Projeto gerado pela LadderIDE (Gravar C++ na placa). Sera sobrescrito na proxima gravacao.",
        "[env:placa]",
        f"platform = {target.platform}",
        f"board = {target.pio_board}",
        "framework = arduino",
        "monitor_speed = 115200",
        ""])


def write_project(project: Project, board: str, folder: Path | None = None) -> Path:
    """Monta o projeto PlatformIO da placa e devolve a pasta."""
    problems = check(project, board)
    if problems:
        raise UploadError("; ".join(problems))
    target = TARGETS[board]
    folder = folder or WORK_DIR / board
    src = folder / "src"
    src.mkdir(parents=True, exist_ok=True)
    for old in src.iterdir():                     # so arquivos gerados aqui
        if old.is_file():
            old.unlink()
    (folder / "platformio.ini").write_text(platformio_ini(target), encoding="utf-8")
    (src / "programa.cpp").write_text(generate_cpp(project).text, encoding="utf-8")
    fw_src = FIRMWARE / "src"
    header = fw_src / "io_board.h"
    if not header.exists():
        raise UploadError(f"arquivos do firmware não encontrados em {fw_src}")
    shutil.copy2(header, src / "io_board.h")
    if board == "esp32-relay":
        shutil.copy2(fw_src / "io_board.cpp", src / "io_board.cpp")
        shutil.copy2(fw_src / "board_config.h", src / "board_config.h")
    else:
        (src / "io_board.cpp").write_text(avr_io_board(target.profile, project.io.n_outputs), encoding="utf-8")
    return folder


def build_command(folder: Path, upload: bool = False, port: str | None = None) -> list[str]:
    cmd = pio_command() + ["run", "-d", str(folder)]
    if upload:
        cmd += ["-t", "upload"]
        if port:
            cmd += ["--upload-port", port]
    return cmd
