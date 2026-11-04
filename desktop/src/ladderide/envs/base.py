"""Contrato dos ambientes de simulacao (processos fisicos ligados ao CLP).

Um ambiente e uma classe que herda de Environment e e registrada com
@register. Ele so conhece NOMES de pontos de E/S; quem traduz nomes em bits
do CLP e o EnvironmentPlant. O simulador conhece apenas o protocolo Plant
(ladderide.sim.simulator), e a interface apenas chama paint()/control_at().
Assim, criar um ambiente novo nao exige alterar o simulador nem a janela.

Ciclo a cada varredura do simulador (tempo virtual, deterministico):
    entradas do CLP  <- sensores do processo + botoes do operador
    varredura do programa
    processo.step(dt, saidas do CLP)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ..core.asm import parse_operand
from ..core.isa import Area

SENSOR, BUTTON, SWITCH = "sensor", "button", "switch"


@dataclass(frozen=True)
class IOPoint:
    """Ponto de E/S do ambiente.

    key: nome interno usado pelo ambiente; address: endereco no CLP (I0.0, Q0.3);
    label: nome exibido e sugerido como simbolo; kind (entradas): sensor (o
    processo decide), button (pulsador do operador) ou switch (chave com trava);
    normally_closed: o contato fisico e NF (ex.: botao de parada).
    """
    key: str
    address: str
    label: str
    description: str = ""
    kind: str = SENSOR
    normally_closed: bool = False


class Environment(ABC):
    """Classe base. Subclasses definem metadados, E/S, fisica e desenho."""
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    example: ClassVar[str] = ""                 # projeto de exemplo, relativo a examples/
    size: ClassVar[tuple[int, int]] = (640, 420)  # sistema de coordenadas do desenho
    inputs: ClassVar[list[IOPoint]] = []
    outputs: ClassVar[list[IOPoint]] = []

    def __init__(self) -> None:
        self.operator: dict[str, bool] = {}     # botoes/chaves do operador
        self.out: dict[str, bool] = {p.key: False for p in self.outputs}
        self.time_ms = 0
        self.reset()

    # ------------------------------------------------------------ fisica
    @abstractmethod
    def reset(self) -> None:
        """Volta o processo ao estado inicial (chamado na partida a frio)."""

    @abstractmethod
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        """Avanca o processo dt_ms com as saidas do CLP (por nome)."""

    @abstractmethod
    def sensors(self) -> dict[str, bool]:
        """Estado fisico dos sensores (por nome), antes da logica NA/NF."""

    def configure(self, n_inputs: int, n_outputs: int, n_words: int) -> bool:
        """Quantidades de E/S e de registradores N do projeto. Ambientes que se adaptam ao
        controlador (ex.: simulador de E/S) refazem os pontos e devolvem True."""
        return False

    def input_words(self) -> dict[int, int]:
        """Registradores N escritos pelo processo antes de cada varredura (indice -> valor)."""
        return {}

    def advance_words(self, n: list[int]) -> None:
        """Registradores N depois de cada varredura (ex.: um display)."""

    def alarms(self) -> list[str]:
        """Situacoes perigosas ou erradas provocadas pela logica do usuario."""
        return []

    def stats(self) -> list[str]:
        """Contadores informativos exibidos no painel (ex.: caixas cheias)."""
        return []

    # --------------------------------------------------------- operador
    def press(self, key: str, down: bool) -> None:
        point = next((p for p in self.inputs if p.key == key), None)
        if point is None:
            return
        if point.kind == SWITCH:
            if down:
                self.operator[key] = not self.operator.get(key, False)
        elif point.kind == BUTTON:
            self.operator[key] = down
        else:
            self.on_control(key, down)

    def on_control(self, key: str, down: bool) -> None:
        """Controles extras do ambiente que nao sao entradas (ex.: colocar um veiculo)."""

    def is_pressed(self, key: str) -> bool:
        return self.operator.get(key, False)

    # ---------------------------------------------------------- desenho
    @abstractmethod
    def paint(self, p) -> None:
        """Desenha o processo com um QPainter ja escalado para self.size."""

    def control_at(self, x: float, y: float) -> str | None:
        """Nome do controle clicavel em (x, y), em coordenadas de self.size."""
        for key, (rx, ry, rw, rh) in self.controls().items():
            if rx <= x <= rx + rw and ry <= y <= ry + rh:
                return key
        return None

    def controls(self) -> dict[str, tuple[float, float, float, float]]:
        """Areas clicaveis: chave -> (x, y, largura, altura)."""
        return {}


def _bit(address: str, area: Area) -> int:
    a, index = parse_operand(address)
    if a != area:
        raise ValueError(f"{address}: esperado endereço {area.name}")
    return index


class EnvironmentPlant:
    """Adapta um Environment ao protocolo Plant do simulador (bits do CLP)."""

    def __init__(self, env: Environment):
        self.env = env
        self.in_bits = {p.key: _bit(p.address, Area.I) for p in env.inputs}
        self.out_bits = {p.key: _bit(p.address, Area.Q) for p in env.outputs}
        self._owned = 0
        for b in self.in_bits.values():
            self._owned |= 1 << b

    @property
    def owned_inputs(self) -> int:
        return self._owned

    def input_values(self) -> dict[str, bool]:
        """Nivel logico de cada entrada como o CLP o le (ja com NA/NF)."""
        env = self.env
        phys = env.sensors()
        values = {}
        for p in env.inputs:
            actuated = env.is_pressed(p.key) if p.kind in (BUTTON, SWITCH) else bool(phys.get(p.key, False))
            values[p.key] = (not actuated) if p.normally_closed else actuated
        return values

    def input_bits(self) -> int:
        bits = 0
        for key, value in self.input_values().items():
            if value:
                bits |= 1 << self.in_bits[key]
        return bits

    def decode_outputs(self, outputs: int) -> dict[str, bool]:
        return {key: bool(outputs >> b & 1) for key, b in self.out_bits.items()}

    def advance(self, dt_ms: int, outputs: int) -> None:
        out = self.decode_outputs(outputs)
        self.env.out = out
        self.env.time_ms += dt_ms
        self.env.step(dt_ms, out)

    def input_words(self) -> dict[int, int]:
        return self.env.input_words()

    def advance_words(self, n: list[int]) -> None:
        self.env.advance_words(n)

    def reset(self) -> None:
        self.env.operator.clear()
        self.env.out = {p.key: False for p in self.env.outputs}
        self.env.time_ms = 0
        self.env.reset()

    def show_outputs(self, outputs: int) -> None:
        """Atualiza apenas o desenho (ex.: simulacao pausada ou parada)."""
        self.env.out = self.decode_outputs(outputs)
