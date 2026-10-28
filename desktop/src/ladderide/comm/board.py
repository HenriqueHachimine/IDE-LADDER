"""Configuracao da placa ESP32 lida de firmware/src/board_config.h.

O simulador da placa usa estes dados para mostrar como o firmware esta
configurado: pinos dos registradores de deslocamento, polaridade dos reles e
das entradas, permutacao bit do registrador <-> canal logico, RS-485 e
parametros do CLP. Nada aqui e medido na placa: sao os valores do arquivo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_DEFINE = re.compile(r'^\s*#define\s+([A-Z_][A-Z0-9_]*)\s+("[^"]*"|-?\d+)\s*(?:/\*(.*?)\*/)?\s*$')
_ARRAY = re.compile(r'^\s*static\s+const\s+\w+\s+([A-Z_][A-Z0-9_]*)\s*\[\d*\]\s*=\s*\{([^}]*)\}\s*;')

# grupo e explicacao de cada definicao conhecida
KNOWN = {
    "FW_VERSION": ("Identificacao", "Versão do firmware informada a IDE (comando INFO)"),
    "HW_ID": ("Identificacao", "Identificador da placa"),
    "PIN_595_SER": ("Registradores de deslocamento", "GPIO de dados serie dos relés (74HC595 SER)"),
    "PIN_SR_CLK": ("Registradores de deslocamento", "GPIO de relogio compartilhado (595 SCK / 165 CLK)"),
    "PIN_SR_LATCH": ("Registradores de deslocamento", "GPIO de latch compartilhado (595 RCK / 165 SH/LD)"),
    "PIN_595_OE": ("Registradores de deslocamento", "GPIO de /OE do 74HC595 (0 = saídas habilitadas)"),
    "PIN_165_QH": ("Registradores de deslocamento", "GPIO que lê a saída serie das entradas (74HC165 QH)"),
    "RELAY_ACTIVE_LOW": ("Polaridade", "1 = nível 0 no 595 energiza o relé"),
    "INPUT_ACTIVE_LOW": ("Polaridade", "1 = entrada ativa lê nível 0 (optoacoplador puxa para GND)"),
    "OUT_MAP": ("Mapeamento", "Posição no 74HC595 -> saída Qk"),
    "IN_MAP": ("Mapeamento", "Posição no 74HC165 -> entrada Ik"),
    "BOARD_INPUTS": ("Mapeamento", "Entradas digitais da placa"),
    "BOARD_OUTPUTS": ("Mapeamento", "Saídas a relé da placa"),
    "MODBUS_ENABLED": ("RS-485 / Modbus", "Modbus RTU somente leitura habilitado"),
    "PIN_RS485_RX": ("RS-485 / Modbus", "GPIO RX do transceptor RS-485 (UART2)"),
    "PIN_RS485_TX": ("RS-485 / Modbus", "GPIO TX do transceptor RS-485 (UART2)"),
    "PIN_RS485_DE": ("RS-485 / Modbus", "GPIO DE/RE do transceptor (1 = transmitir)"),
    "MODBUS_ADDRESS": ("RS-485 / Modbus", "Endereço Modbus da placa"),
    "MODBUS_BAUD": ("RS-485 / Modbus", "Velocidade do barramento RS-485 (bit/s)"),
    "LDP_BAUD": ("CLP", "Velocidade da USB-serial com a IDE (bit/s)"),
    "SCAN_PERIOD_MS": ("CLP", "Período da varredura (ms)"),
    "SCAN_WATCHDOG_US": ("CLP", "Tempo máximo de uma varredura antes de FAULT (us)"),
    "AUTORUN_ON_BOOT": ("CLP", "1 = entra em RUN ao ligar; 0 = sempre inicia em STOP"),
}
GROUP_ORDER = ["Identificacao", "Registradores de deslocamento", "Polaridade", "Mapeamento", "RS-485 / Modbus",
               "CLP", "Outros"]


@dataclass
class BoardItem:
    name: str
    value: str
    group: str
    description: str
    comment: str = ""

    @property
    def verify(self) -> bool:
        """Valor marcado no arquivo para confirmar na placa real."""
        return "VERIFICAR" in self.comment.upper()


@dataclass
class BoardConfig:
    items: list[BoardItem] = field(default_factory=list)
    source: str = "valores padrão"

    def value(self, name: str, default=None):
        item = next((i for i in self.items if i.name == name), None)
        if item is None:
            return default
        v = item.value
        if v.startswith("{"):
            return [int(x) for x in v.strip("{}").split(",") if x.strip()]
        if v.startswith('"'):
            return v.strip('"')
        return int(v)

    # -------------------------------------------------- atalhos usados na placa
    @property
    def out_map(self) -> list[int]:
        return self.value("OUT_MAP", [7, 6, 5, 4, 3, 2, 1, 0])

    @property
    def in_map(self) -> list[int]:
        return self.value("IN_MAP", [6, 4, 2, 0, 1, 3, 5, 7])

    @property
    def relay_active_low(self) -> bool:
        return bool(self.value("RELAY_ACTIVE_LOW", 1))

    @property
    def input_active_low(self) -> bool:
        return bool(self.value("INPUT_ACTIVE_LOW", 1))

    def pin(self, name: str) -> int | None:
        return self.value(name)

    def shift_out_levels(self, outputs: int) -> list[int]:
        """Nivel eletrico (0/1) em cada posicao do 74HC595 para a palavra de saidas Q."""
        levels = []
        for channel in self.out_map:
            on = bool(outputs >> channel & 1)
            levels.append(int(not on) if self.relay_active_low else int(on))
        return levels

    def shift_in_levels(self, inputs: int) -> list[int]:
        """Nivel eletrico em cada posicao do 74HC165 para a palavra de entradas I."""
        levels = []
        for channel in self.in_map:
            active = bool(inputs >> channel & 1)
            levels.append(int(not active) if self.input_active_low else int(active))
        return levels

    def grouped(self) -> list[tuple[str, list[BoardItem]]]:
        groups = {g: [] for g in GROUP_ORDER}
        for item in self.items:
            groups.setdefault(item.group, []).append(item)
        return [(g, items) for g, items in groups.items() if items]


def parse_board_config(text: str, source: str = "") -> BoardConfig:
    """Le as definicoes e tabelas de board_config.h com os comentarios de cada uma."""
    items: list[BoardItem] = []
    pending = ""           # comentario de bloco imediatamente acima da definicao
    block: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if block is not None:
            block.append(stripped.rstrip("*/").lstrip("* "))
            if "*/" in stripped:
                pending, block = " ".join(x for x in block if x), None
            continue
        if stripped.startswith("/*") and not stripped.startswith("/**/"):
            body = stripped[2:]
            if "*/" in body:
                pending = body.split("*/")[0].strip()
            else:
                block = [body.strip()]
            continue
        if not stripped:
            pending = ""
            continue
        m = _DEFINE.match(line)
        a = _ARRAY.match(line)
        if m:
            name, value, inline = m.group(1), m.group(2), (m.group(3) or "").strip()
        elif a:
            name, value, inline = a.group(1), "{" + ", ".join(x.strip() for x in a.group(2).split(",")) + "}", ""
        else:
            continue
        if name.endswith("_H") and name.startswith("BOARD_CONFIG"):
            continue
        group, desc = KNOWN.get(name, ("Outros", ""))
        comment = inline or pending
        items.append(BoardItem(name, value, group, desc, comment))
    return BoardConfig(items, source or "board_config.h")


def load_board_config(path: Path | None = None) -> BoardConfig:
    from .virtual import FIRMWARE
    path = path or FIRMWARE / "src" / "board_config.h"
    if not path.exists():
        return BoardConfig()
    return parse_board_config(path.read_text(encoding="utf-8", errors="replace"), "firmware/src/board_config.h")
