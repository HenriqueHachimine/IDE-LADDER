"""Primitivas de desenho reutilizaveis pelos ambientes (QPainter)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

INK = QColor("#1e293b")
MUTED = QColor("#64748b")
GREEN = QColor("#16a34a")
RED = QColor("#dc2626")
AMBER = QColor("#f59e0b")
STEEL = QColor("#94a3b8")
WHITE = QColor("#ffffff")


def font(size: float, bold: bool = False) -> QFont:
    from ..ui.fonts import ui_font
    return ui_font(size, bold)


def text(p: QPainter, x: float, y: float, s: str, size: float = 8, bold: bool = False, color: QColor = INK,
         align=Qt.AlignLeft | Qt.AlignVCenter, w: float = 200, h: float = 16) -> None:
    p.setFont(font(size, bold))
    p.setPen(color)
    if align & Qt.AlignHCenter:
        x -= w / 2
    elif align & Qt.AlignRight:
        x -= w
    p.drawText(QRectF(x, y - h / 2, w, h), align, s)


def tag(p: QPainter, x: float, y: float, address: str, active: bool | None = None) -> None:
    """Etiqueta com o endereco do CLP (ex.: I0.3), verde quando ativa."""
    p.setFont(font(7, True))
    w = p.fontMetrics().horizontalAdvance(address) + 10
    r = QRectF(x, y - 8, w, 16)
    p.setPen(Qt.NoPen)
    p.setBrush(GREEN if active else QColor(15, 23, 42, 200))
    p.drawRoundedRect(r, 4, 4)
    p.setPen(WHITE)
    p.drawText(r, Qt.AlignCenter, address)
    p.setBrush(Qt.NoBrush)


def lamp(p: QPainter, c: QPointF, r: float, on: bool, color: QColor) -> None:
    if on:
        glow = QColor(color)
        glow.setAlpha(70)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, r * 1.6, r * 1.6)
    grad = QLinearGradient(c.x(), c.y() - r, c.x(), c.y() + r)
    base = QColor(color) if on else QColor(color).darker(330)
    grad.setColorAt(0, base.lighter(150))
    grad.setColorAt(1, base)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor("#0f172a"), 1.2))
    p.drawEllipse(c, r, r)
    p.setBrush(Qt.NoBrush)


def push_button(p: QPainter, rect: QRectF, label: str, pressed: bool, color: QColor) -> None:
    p.setPen(QPen(QColor("#334155"), 1))
    p.setBrush(QColor("#e2e8f0"))
    p.drawRoundedRect(rect, 6, 6)
    c = QPointF(rect.left() + rect.height() / 2 + 2, rect.center().y())
    r = rect.height() * 0.32
    p.setBrush(color.darker(140) if pressed else color)
    p.setPen(QPen(color.darker(170), 2))
    p.drawEllipse(c, r if not pressed else r * 0.86, r if not pressed else r * 0.86)
    text(p, c.x() + r + 6, rect.center().y(), label, 8, True, INK, w=rect.width() - 2 * r - 10)
    p.setBrush(Qt.NoBrush)


def switch(p: QPainter, rect: QRectF, label: str, on: bool) -> None:
    p.setPen(QPen(QColor("#334155"), 1))
    p.setBrush(QColor("#e2e8f0"))
    p.drawRoundedRect(rect, 6, 6)
    track = QRectF(rect.left() + 6, rect.center().y() - 7, 28, 14)
    p.setBrush(GREEN if on else STEEL)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(track, 7, 7)
    p.setBrush(WHITE)
    p.drawEllipse(QPointF(track.right() - 7 if on else track.left() + 7, track.center().y()), 5.5, 5.5)
    text(p, track.right() + 6, rect.center().y(), label, 8, True, INK, w=rect.width() - 40)


def sensor(p: QPainter, rect: QRectF, active: bool, vertical: bool = True) -> None:
    """Sensor indutivo/optico: corpo cilindrico com LED na ponta."""
    p.setPen(QPen(QColor("#0f172a"), 1))
    grad = QLinearGradient(rect.topLeft(), rect.topRight() if vertical else rect.bottomLeft())
    grad.setColorAt(0, QColor("#60a5fa"))
    grad.setColorAt(1, QColor("#1d4ed8"))
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(rect, 3, 3)
    tip = QRectF(rect.left(), rect.bottom() - 6, rect.width(), 6) if vertical else \
        QRectF(rect.right() - 6, rect.top(), 6, rect.height())
    p.setBrush(AMBER if active else QColor("#78350f"))
    p.drawRect(tip)
    p.setBrush(Qt.NoBrush)


def beam(p: QPainter, a: QPointF, b: QPointF, active: bool) -> None:
    pen = QPen(QColor(245, 158, 11, 220) if active else QColor(148, 163, 184, 110), 2, Qt.DashLine)
    p.setPen(pen)
    p.drawLine(a, b)


def motor(p: QPainter, c: QPointF, r: float, on: bool, angle: float, label: str = "M") -> None:
    p.setPen(QPen(QColor("#0f172a"), 1.2))
    p.setBrush(QColor("#1d4ed8") if on else QColor("#475569"))
    p.drawRoundedRect(QRectF(c.x() - r * 1.5, c.y() - r, r * 2.4, r * 2), 5, 5)
    p.setBrush(QColor("#e2e8f0"))
    p.drawEllipse(c, r * 0.75, r * 0.75)
    p.setPen(QPen(GREEN if on else QColor("#334155"), 2.5))
    for k in range(3):
        a = angle + k * 2 * math.pi / 3
        p.drawLine(c, QPointF(c.x() + math.cos(a) * r * 0.65, c.y() + math.sin(a) * r * 0.65))
    text(p, c.x() - r * 1.5 + 4, c.y() - r + 8, label, 7, True, WHITE)


def arrow(p: QPainter, c: QPointF, size: float, up: bool, on: bool) -> None:
    s = size / 2
    pts = [QPointF(c.x(), c.y() - s), QPointF(c.x() + s, c.y() + s * 0.2), QPointF(c.x() - s, c.y() + s * 0.2)] \
        if up else [QPointF(c.x(), c.y() + s), QPointF(c.x() + s, c.y() - s * 0.2), QPointF(c.x() - s, c.y() - s * 0.2)]
    p.setPen(Qt.NoPen)
    p.setBrush(GREEN if on else QColor("#475569"))
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(Qt.NoBrush)


def panel(p: QPainter, rect: QRectF, title: str = "") -> None:
    p.setPen(QPen(QColor("#475569"), 1.2))
    p.setBrush(QColor("#f1f5f9"))
    p.drawRoundedRect(rect, 8, 8)
    if title:
        text(p, rect.left() + 10, rect.top() + 12, title, 7.5, True, MUTED)
    p.setBrush(Qt.NoBrush)


def rounded_path(rect: QRectF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path
