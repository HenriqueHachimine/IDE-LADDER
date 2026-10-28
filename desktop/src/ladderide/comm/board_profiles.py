"""Placas que o simulador de placa da IDE sabe desenhar e simular.

Cada perfil diz quantos reles a placa aceita, quantas entradas tem e em quais
pinos ficam. O dispositivo virtual (firmware no PC) e iniciado com essas
quantidades (`virtual_args`), entao o CLP simulado responde como a placa
escolhida. Somente a ESP32 tem firmware real neste projeto; as placas Arduino
existem apenas na simulacao.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BoardProfile:
    id: str
    name: str
    mcu: str
    min_relays: int
    max_relays: int
    default_relays: int
    n_inputs: int
    relay_pins: tuple[str, ...]      # pino que aciona o rele k (IN k+1 do modulo)
    input_pins: tuple[str, ...]      # pino lido pela entrada k
    hardware: bool                   # existe firmware para a placa real
    description: str

    def clamp_relays(self, n: int) -> int:
        return max(self.min_relays, min(self.max_relays, int(n)))

    def hardware_id(self, relays: int) -> str:
        return f"virtual-{self.id}-x{self.clamp_relays(relays)}"

    def virtual_args(self, relays: int) -> list[str]:
        """Argumentos do dispositivo virtual para simular esta placa com `relays` reles."""
        return ["--inputs", str(self.n_inputs), "--outputs", str(self.clamp_relays(relays)),
                "--hardware", self.hardware_id(relays)]

    def pin_map(self, relays: int) -> list[tuple[str, str, str]]:
        """(endereco no CLP, pino, funcao) de cada rele e entrada usados."""
        rows = [(f"Q0.{k}", self.relay_pins[k], f"relé K{k + 1}") for k in range(self.clamp_relays(relays))]
        rows += [(f"I0.{k}", self.input_pins[k], f"entrada IN{k + 1}") for k in range(self.n_inputs)]
        return rows


ESP32 = BoardProfile(
    id="esp32-relay", name="ESP32 Relay (placa do projeto)", mcu="ESP32-WROOM-32",
    min_relays=1, max_relays=8, default_relays=8, n_inputs=8,
    relay_pins=tuple(f"74HC595 Q{k}" for k in range(8)),
    input_pins=tuple(f"74HC165 D{k}" for k in range(8)),
    hardware=True,
    description="ESP32 com relés no 74HC595 e entradas optoacopladas no 74HC165 (versões X1 a X8). "
                "Tem firmware real: transferência, RUN/STOP e monitor pela USB.")

ARDUINO_UNO = BoardProfile(
    id="arduino-uno", name="Arduino UNO", mcu="ATmega328P",
    min_relays=1, max_relays=8, default_relays=8, n_inputs=8,
    relay_pins=tuple(f"D{p}" for p in range(2, 10)),
    input_pins=("A0", "A1", "A2", "A3", "A4", "A5", "D10", "D11"),
    hardware=False,
    description="Arduino UNO com módulo de relés nos pinos D2 a D9 e entradas em A0 a A5, D10 e D11. "
                "Somente simulação: o firmware do CLP não foi portado para o ATmega328P.")

ARDUINO_MEGA = BoardProfile(
    id="arduino-mega", name="Arduino Mega 2560", mcu="ATmega2560",
    min_relays=1, max_relays=16, default_relays=8, n_inputs=16,
    relay_pins=tuple(f"D{p}" for p in range(22, 38)),
    input_pins=tuple(f"D{p}" for p in range(38, 54)),
    hardware=False,
    description="Arduino Mega 2560 com módulo de relés nos pinos D22 a D37 e entradas em D38 a D53. "
                "Somente simulação: o firmware do CLP não foi portado para o ATmega2560.")

PROFILES: dict[str, BoardProfile] = {p.id: p for p in (ESP32, ARDUINO_UNO, ARDUINO_MEGA)}
DEFAULT = ESP32.id


def get_profile(board_id: str | None) -> BoardProfile:
    return PROFILES.get(board_id or "", PROFILES[DEFAULT])
