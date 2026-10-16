"""Desenho dos simbolos LADDER (usado no diagrama e nos icones da paleta)."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

ENERGIZED = QColor(22, 163, 74)
DEENERGIZED = QColor(120, 120, 120)
NEUTRAL = QColor(35, 35, 35)
CLOSED_FILL = QColor(22, 163, 74, 70)
SELECTED_FILL = QColor(59, 130, 246, 45)
SELECTED_BORDER = QColor(37, 99, 235)
ERROR_FILL = QColor(220, 38, 38, 45)
CURRENT_BORDER = QColor(234, 88, 12)
LABEL = QColor(30, 41, 59)
SUBLABEL = QColor(100, 116, 139)


@dataclass
class SymbolState:
    """Estado visual. power_* = None significa modo edicao (sem energia)."""
    power_in: bool | None = None
    power_out: bool | None = None
    closed: bool | None = None       # contato conduzindo pelo valor do operando
    label: str = ""
    sublabel: str = ""
    lines: tuple[str, ...] = ()      # texto interno das caixas
    done: bool | None = None         # bit DN de temporizador/contador


def color_for(power: bool | None) -> QColor:
    if power is None:
        return NEUTRAL
    return ENERGIZED if power else DEENERGIZED


def _pen(power: bool | None, width: float = 2.0) -> QPen:
    pen = QPen(color_for(power), width + (1.0 if power else 0.0))
    pen.setCapStyle(Qt.FlatCap)
    return pen


def _labels(p: QPainter, r: QRectF, st: SymbolState, top: float, bottom: float) -> None:
    if st.label:
        f = QFont("Segoe UI", 8)
        f.setBold(True)
        p.setFont(f)
        p.setPen(LABEL)
        p.drawText(QRectF(r.left(), r.top(), r.width(), top - r.top()), Qt.AlignHCenter | Qt.AlignBottom,
                   p.fontMetrics().elidedText(st.label, Qt.ElideRight, int(r.width())))
    if st.sublabel:
        p.setFont(QFont("Segoe UI", 7))
        p.setPen(SUBLABEL)
        p.drawText(QRectF(r.left(), bottom, r.width(), r.bottom() - bottom), Qt.AlignHCenter | Qt.AlignTop,
                   st.sublabel)


def paint_symbol(p: QPainter, kind: str, r: QRectF, st: SymbolState) -> None:
    """kind: XIC, XIO, NOT, OTE, OTL, OTU, TON, TOF, RTO, CTU, CTD, RES, PAR."""
    p.setRenderHint(QPainter.Antialiasing, True)
    mid = r.center().y()
    w = r.width()
    if kind in ("XIC", "XIO"):
        bh = r.height() * 0.24
        x1, x2 = r.left() + w * 0.38, r.left() + w * 0.62
        if st.closed:
            p.fillRect(QRectF(x1, mid - bh, x2 - x1, 2 * bh), CLOSED_FILL)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(x1, mid))
        p.drawLine(QPointF(x1, mid - bh), QPointF(x1, mid + bh))
        p.setPen(_pen(st.power_out))
        p.drawLine(QPointF(x2, mid - bh), QPointF(x2, mid + bh))
        p.drawLine(QPointF(x2, mid), QPointF(r.right(), mid))
        if kind == "XIO":
            p.setPen(_pen(st.power_out, 1.6))
            p.drawLine(QPointF(x1 - 3, mid + bh), QPointF(x2 + 3, mid - bh))
        _labels(p, r, st, mid - bh - 1, mid + bh + 1)
    elif kind == "NOT":
        bw, bh = w * 0.42, r.height() * 0.36
        box = QRectF(r.center().x() - bw / 2, mid - bh / 2, bw, bh)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(box.left(), mid))
        p.setPen(_pen(st.power_out))
        p.drawRect(box)
        p.drawLine(QPointF(box.right(), mid), QPointF(r.right(), mid))
        p.setFont(QFont("Segoe UI", 7, QFont.Bold))
        p.drawText(box, Qt.AlignCenter, "NOT")
    elif kind in ("OTE", "OTL", "OTU", "RES"):
        rad = min(r.height() * 0.24, w * 0.16)
        cx = r.center().x()
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(cx - rad, mid))
        p.setPen(_pen(st.power_in))
        arc = QRectF(cx - rad, mid - rad, 2 * rad, 2 * rad)
        p.drawArc(arc.adjusted(-2, 0, -2, 0), 110 * 16, 140 * 16)
        p.drawArc(arc.adjusted(2, 0, 2, 0), -70 * 16, 140 * 16)
        p.setPen(NEUTRAL if st.power_in is None else color_for(st.power_in))
        p.drawLine(QPointF(cx + rad, mid), QPointF(r.right(), mid))
        letter = {"OTL": "S", "OTU": "R", "RES": "RES"}.get(kind, "")
        if letter:
            p.setFont(QFont("Segoe UI", 7 if kind == "RES" else 9, QFont.Bold))
            p.drawText(arc.adjusted(-6, 0, 6, 0), Qt.AlignCenter, letter)
        _labels(p, r, st, mid - rad - 1, mid + rad + 1)
    elif kind in ("TON", "TOF", "RTO", "CTU", "CTD"):
        box = QRectF(r.left() + w * 0.1, r.top() + 3, w * 0.8, r.height() - 6)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(box.left(), mid))
        p.setPen(QPen(color_for(st.power_in), 1.5))
        p.setBrush(QColor(255, 255, 255))
        p.drawRect(box)
        p.setBrush(Qt.NoBrush)
        if st.done is not None:
            p.setBrush(ENERGIZED if st.done else QColor(203, 213, 225))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(box.right() - 7, box.top() + 7), 4, 4)
            p.setBrush(Qt.NoBrush)
        p.setPen(LABEL)
        f = QFont("Segoe UI", 7)
        f.setBold(True)
        p.setFont(f)
        title = f"{kind}  {st.label}" if st.label else kind
        p.drawText(QRectF(box.left() + 3, box.top() + 1, box.width() - 14, 13), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(title, Qt.ElideRight, int(box.width() - 14)))
        p.setFont(QFont("Segoe UI", 7))
        for k, line in enumerate(st.lines[:3]):
            p.drawText(QRectF(box.left() + 3, box.top() + 14 + k * 12, box.width() - 4, 12),
                       Qt.AlignLeft | Qt.AlignVCenter, line)
    elif kind == "PAR":
        p.setPen(_pen(None))
        p.drawLine(QPointF(r.left() + 3, r.top() + 6), QPointF(r.left() + 3, r.bottom() - 6))
        p.drawLine(QPointF(r.right() - 3, r.top() + 6), QPointF(r.right() - 3, r.bottom() - 6))
        p.drawLine(QPointF(r.left(), r.top() + 6), QPointF(r.right(), r.top() + 6))
        p.drawLine(QPointF(r.left() + 3, r.bottom() - 6), QPointF(r.right() - 3, r.bottom() - 6))


def tool_icon(kind: str) -> QIcon:
    pix = QPixmap(56, 34)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    paint_symbol(p, kind if kind != "RUNG" else "PAR", QRectF(1, 1, 54, 32),
                 SymbolState(lines=("PRE",) if kind in ("TON", "TOF", "RTO", "CTU", "CTD") else ()))
    p.end()
    return QIcon(pix)
