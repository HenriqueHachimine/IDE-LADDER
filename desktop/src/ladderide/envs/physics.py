"""Utilidades de fisica para os ambientes (sem Qt, deterministicas).

Todos os ambientes integram com passo fixo dt (o periodo de varredura, em tempo
virtual), entao os resultados sao reproduziveis e testaveis.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass


def approach(value: float, target: float, rate_up: float, rate_down: float, dt: float) -> float:
    """Aproxima value de target com taxas maximas (unidades/s) diferentes para subir e descer.
    Modela inercia simples: aceleracao/frenagem limitadas de motores e atuadores."""
    if target > value:
        return min(target, value + rate_up * dt)
    return max(target, value - rate_down * dt)


def torricelli(level_fraction: float) -> float:
    """Vazao relativa de um recipiente que escoa por gravidade: Q ~ sqrt(altura)."""
    return math.sqrt(max(0.0, min(1.0, level_fraction)))


class DelayLine:
    """Atraso de transporte (ex.: produto em queda livre entre a valvula e a caixa)."""

    def __init__(self, delay_s: float):
        self.delay_s = delay_s
        self.items: deque[list[float]] = deque()    # [tempo restante, quantidade]

    def push(self, amount: float) -> None:
        if amount > 0:
            self.items.append([self.delay_s, amount])

    def advance(self, dt: float) -> float:
        """Avanca dt e retorna a quantidade que chegou ao destino neste passo."""
        arrived = 0.0
        for item in self.items:
            item[0] -= dt
        while self.items and self.items[0][0] <= 0:
            arrived += self.items.popleft()[1]
        return arrived

    @property
    def in_flight(self) -> float:
        return sum(a for _, a in self.items)

    def clear(self) -> None:
        self.items.clear()


@dataclass
class IDM:
    """Intelligent Driver Model (Treiber et al., 2000): aceleracao de um veiculo
    seguindo outro (ou parando diante de um obstaculo). Unidades: m e s."""
    v0: float = 13.9        # velocidade desejada (50 km/h)
    T: float = 1.2          # intervalo de tempo seguro
    a: float = 1.5          # aceleracao maxima
    b: float = 2.0          # desaceleracao confortavel
    s0: float = 2.0         # distancia minima parado
    b_max: float = 9.0      # frenagem maxima fisica

    def accel(self, v: float, gap: float | None, dv: float = 0.0) -> float:
        """gap: distancia livre ate o obstaculo (None = via livre); dv = v - v_lider."""
        free = 1.0 - (v / self.v0) ** 4
        if gap is None:
            return self.a * free
        s_star = self.s0 + max(0.0, v * self.T + v * dv / (2 * math.sqrt(self.a * self.b)))
        acc = self.a * (free - (s_star / max(gap, 0.1)) ** 2)
        return max(-self.b_max, acc)

    def stopping_distance(self, v: float, decel: float | None = None) -> float:
        return v * v / (2 * (decel or self.b))
