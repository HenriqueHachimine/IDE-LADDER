"""Esteiras, caixas e emissores para as cenas de manuseio de materiais (sem Qt na fisica).

Cada esteira e um trecho reto com coordenada propria (pixels ao longo do
sentido de transporte). As caixas guardam a posicao da FRENTE; a seguinte para
encostada na anterior (acumulo), e um batente opcional segura a primeira.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from . import draw


@dataclass
class Item:
    x: float                      # frente da caixa na esteira atual
    length: float = 50.0
    kind: int = 0                 # tipo (cada cena da o significado)
    data: dict = field(default_factory=dict)

    @property
    def back(self) -> float:
        return self.x - self.length

    @property
    def center(self) -> float:
        return self.x - self.length / 2

    def covers(self, pos: float) -> bool:
        return self.back < pos < self.x


class Belt:
    """Trecho de esteira: move as caixas com acumulo e batente."""

    def __init__(self, x0: float, x1: float, speed: float = 100.0):
        self.x0, self.x1, self.speed = x0, x1, speed
        self.items: list[Item] = []
        self.offset = 0.0           # deslocamento da correia (animacao, encoder)

    def move(self, dt: float, running: bool, stop: float | None = None, end: float | None = None,
             gap: float = 1.0) -> float:
        """Avanca as caixas; stop = batente (nenhuma frente passa dele), end = fim fisico.
        Retorna o deslocamento da correia neste passo."""
        if not running:
            return 0.0
        d = self.speed * dt
        self.offset += d
        limit = min(v for v in (stop, end, float("inf")) if v is not None)
        for it in sorted(self.items, key=lambda i: -i.x):
            if it.x < limit:
                it.x = min(limit, it.x + d)
            limit = it.back - gap
        return d

    def at(self, pos: float) -> bool:
        return any(i.covers(pos) for i in self.items)

    def clear_from(self, pos: float, length: float = 0.0) -> bool:
        """Nenhuma caixa ocupa [pos - length, pos + length]."""
        return not any(i.back < pos + length and i.x > pos - length for i in self.items)

    def take(self, pred) -> list[Item]:
        out = [i for i in self.items if pred(i)]
        self.items = [i for i in self.items if not pred(i)]
        return out


class Emitter:
    """Solta caixas no inicio de uma esteira com espacamento variavel (deterministico)."""

    def __init__(self, rng, gap: tuple[float, float] = (30.0, 120.0)):
        self.rng = rng
        self.gap = gap
        self.need = rng.uniform(*gap)

    def ready(self, belt: Belt, length: float) -> bool:
        first = min((i.back for i in belt.items), default=float("inf"))
        return first - belt.x0 >= self.need

    def emit(self, belt: Belt, item: Item) -> None:
        item.x = belt.x0
        belt.items.append(item)
        self.need = self.rng.uniform(*self.gap)


# ---------------------------------------------------------------- desenho
def carton(p: QPainter, r: QRectF, color: str = "#c08a4a", label: str = "", tape: bool = True,
           highlight: bool = False) -> None:
    """Caixa de papelao vista de cima (fita no meio)."""
    c = QColor(color)
    draw.shadow(p, r, 2, 2)
    p.setPen(QPen(c.darker(190), 1.2 if not highlight else 2.2))
    if highlight:
        p.setPen(QPen(QColor("#7c3aed"), 2.2))
    p.setBrush(c)
    p.drawRoundedRect(r, 2, 2)
    if tape:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 70))
        if r.width() >= r.height():
            p.drawRect(QRectF(r.left() + 2, r.center().y() - 2.5, r.width() - 4, 5))
        else:
            p.drawRect(QRectF(r.center().x() - 2.5, r.top() + 2, 5, r.height() - 4))
    if label:
        draw.ctext(p, r.center().x(), r.center().y(), label, 7, True, QColor("#1c1917"), w=r.width())
    p.setBrush(Qt.NoBrush)


def vbelt(p: QPainter, rect: QRectF, offset: float, running: bool) -> None:
    """Esteira vertical (a correia anda para cima): desenha uma esteira girada."""
    p.save()
    p.translate(rect.left(), rect.bottom())
    p.rotate(-90)
    draw.conveyor(p, QRectF(0, 0, rect.height(), rect.width()), offset, running)
    p.restore()


def blade(p: QPainter, x: float, y0: float, y1: float, raised: bool) -> None:
    """Batente (stop blade) atravessando a esteira; levantado segura as caixas."""
    if raised:
        draw.metal(p, QRectF(x - 3, y0, 6, y1 - y0), "#dc2626", 1, vertical=True)
    else:
        p.setPen(QPen(QColor("#64748b"), 1, Qt.DashLine))
        p.drawLine(QPointF(x, y0), QPointF(x, y1))


def emitter_box(p: QPainter, r: QRectF, on: bool, label: str = "EMISSOR") -> None:
    draw.metal(p, r, "#0e7490" if on else "#475569", 4)
    draw.ctext(p, r.center().x(), r.center().y(), label, 6.5, True, draw.WHITE, w=r.width())


def remover_box(p: QPainter, r: QRectF, label: str = "SAÍDA") -> None:
    draw.metal(p, r, "#334155", 4)
    draw.ctext(p, r.center().x(), r.center().y(), label, 6.5, True, draw.WHITE, w=r.width())
