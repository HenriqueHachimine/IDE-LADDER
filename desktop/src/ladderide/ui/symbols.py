"""Desenho dos simbolos LADDER (usado no diagrama e nos icones da paleta)."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap

from .theme import themed

# (cor no tema claro, cor no tema escuro)
ENERGIZED = themed((22, 163, 74), (34, 197, 94))
DEENERGIZED = themed((148, 163, 184), (100, 116, 139))
NEUTRAL = themed((51, 65, 85), (203, 213, 225))
CLOSED_FILL = themed((22, 163, 74, 60), (34, 197, 94, 70))
COIL_ON_FILL = themed((22, 163, 74, 45), (34, 197, 94, 55))
SELECTED_FILL = themed((37, 99, 235, 28), (96, 165, 250, 45))
SELECTED_BORDER = themed((37, 99, 235), (96, 165, 250))
ERROR_FILL = themed((220, 38, 38, 40), (248, 113, 113, 60))
CURRENT_BORDER = themed((234, 88, 12), (251, 146, 60))
LABEL = themed((15, 23, 42), (226, 232, 240))
SUBLABEL = themed((100, 116, 139), (148, 163, 184))
BOX_FILL = themed((255, 255, 255), (21, 30, 46))
TIMER_HEAD = (themed((224, 231, 255), (49, 46, 129)), themed((55, 48, 163), (199, 210, 254)))
COUNTER_HEAD = (themed((254, 243, 199), (120, 53, 15)), themed((146, 64, 14), (253, 230, 138)))
DONE_OFF = themed((203, 213, 225), (71, 85, 105))


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


def _font(size: float, bold: bool = False, family: str = "Segoe UI") -> QFont:
    f = QFont(family, 1)
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


def _labels(p: QPainter, r: QRectF, st: SymbolState, top: float, bottom: float) -> None:
    if st.label:
        avail = r.width() - 6
        size = 8.5
        p.setFont(_font(size, True))
        while size > 7 and p.fontMetrics().horizontalAdvance(st.label) > avail:
            size -= 0.5
            p.setFont(_font(size, True))
        p.setPen(LABEL)
        p.drawText(QRectF(r.left() + 3, r.top(), avail, top - r.top() - 2), Qt.AlignHCenter | Qt.AlignBottom,
                   p.fontMetrics().elidedText(st.label, Qt.ElideRight, int(avail)))
    if st.sublabel:
        p.setFont(_font(7.5, False, "Consolas"))
        p.setPen(SUBLABEL)
        p.drawText(QRectF(r.left(), bottom + 2, r.width(), r.bottom() - bottom), Qt.AlignHCenter | Qt.AlignTop,
                   st.sublabel)


def paint_symbol(p: QPainter, kind: str, r: QRectF, st: SymbolState) -> None:
    """kind: XIC, XIO, NOT, OTE, OTL, OTU, TON, TOF, RTO, CTU, CTD, RES, PAR."""
    p.setRenderHint(QPainter.Antialiasing, True)
    mid = r.center().y()
    w = r.width()
    if kind in ("XIC", "XIO"):
        bh = r.height() * 0.2
        x1, x2 = r.left() + w * 0.40, r.left() + w * 0.60
        if st.closed:
            p.setPen(Qt.NoPen)
            p.setBrush(CLOSED_FILL)
            p.drawRoundedRect(QRectF(x1 - 3, mid - bh - 3, x2 - x1 + 6, 2 * bh + 6), 3, 3)
            p.setBrush(Qt.NoBrush)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(x1, mid))
        p.setPen(_pen(st.power_in, 2.6))
        p.drawLine(QPointF(x1, mid - bh), QPointF(x1, mid + bh))
        p.setPen(_pen(st.power_out, 2.6))
        p.drawLine(QPointF(x2, mid - bh), QPointF(x2, mid + bh))
        p.setPen(_pen(st.power_out))
        p.drawLine(QPointF(x2, mid), QPointF(r.right(), mid))
        if kind == "XIO":
            pen = _pen(st.power_out, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawLine(QPointF(x1 - 4, mid + bh), QPointF(x2 + 4, mid - bh))
        _labels(p, r, st, mid - bh - 2, mid + bh + 1)
    elif kind == "NOT":
        bw, bh = w * 0.42, r.height() * 0.34
        box = QRectF(r.center().x() - bw / 2, mid - bh / 2, bw, bh)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(box.left(), mid))
        p.setPen(_pen(st.power_out, 1.6))
        p.setBrush(BOX_FILL)
        p.drawRoundedRect(box, 3, 3)
        p.setBrush(Qt.NoBrush)
        p.setPen(_pen(st.power_out))
        p.drawLine(QPointF(box.right(), mid), QPointF(r.right(), mid))
        p.setPen(LABEL)
        p.setFont(_font(7.5, True))
        p.drawText(box, Qt.AlignCenter, "NOT")
    elif kind in ("OTE", "OTL", "OTU", "RES"):
        rad = min(r.height() * 0.22, w * 0.14)
        cx = r.center().x()
        arc = QRectF(cx - rad, mid - rad, 2 * rad, 2 * rad)
        if st.power_in:
            p.setPen(Qt.NoPen)
            p.setBrush(COIL_ON_FILL)
            p.drawEllipse(arc.adjusted(-1, -1, 1, 1))
            p.setBrush(Qt.NoBrush)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(cx - rad - 1, mid))
        pen = _pen(st.power_in, 2.4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(arc.adjusted(-2, 0, -2, 0), 115 * 16, 130 * 16)
        p.drawArc(arc.adjusted(2, 0, 2, 0), -65 * 16, 130 * 16)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(cx + rad + 1, mid), QPointF(r.right(), mid))
        letter = {"OTL": "S", "OTU": "R", "RES": "RES"}.get(kind, "")
        if letter:
            p.setPen(LABEL)
            p.setFont(_font(7 if kind == "RES" else 9.5, True))
            p.drawText(arc.adjusted(-6, 0, 6, 0), Qt.AlignCenter, letter)
        _labels(p, r, st, mid - rad - 1, mid + rad + 1)
    elif kind in ("TON", "TOF", "RTO", "CTU", "CTD"):
        is_timer = kind in ("TON", "TOF", "RTO")
        head_bg, head_fg = TIMER_HEAD if is_timer else COUNTER_HEAD
        box = QRectF(r.left() + w * 0.08, r.top() + 3, w * 0.84, r.height() - 6)
        p.setPen(_pen(st.power_in))
        p.drawLine(QPointF(r.left(), mid), QPointF(box.left(), mid))
        p.setPen(QPen(color_for(st.power_in), 1.4 if not st.power_in else 2.2))
        p.setBrush(BOX_FILL)
        p.drawRoundedRect(box, 5, 5)
        head_h = min(15.0, box.height() * 0.3)
        head = QRectF(box.left() + 1, box.top() + 1, box.width() - 2, head_h)
        p.setPen(Qt.NoPen)
        p.setBrush(head_bg)
        p.drawRoundedRect(head, 4, 4)
        p.drawRect(head.adjusted(0, head_h / 2, 0, 0))
        p.setBrush(Qt.NoBrush)
        p.setPen(head_fg)
        p.setFont(_font(7.5, True))
        p.drawText(head.adjusted(5, 0, -14, 0), Qt.AlignLeft | Qt.AlignVCenter, kind)
        if st.done is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(ENERGIZED if st.done else DONE_OFF)
            p.drawEllipse(QPointF(head.right() - 7, head.center().y()), 3.8, 3.8)
            p.setBrush(Qt.NoBrush)
        body_top = head.bottom() + 1
        line_h = max(10.0, (box.bottom() - body_top - 2) / 3)
        if st.label:
            p.setPen(LABEL)
            p.setFont(_font(8, True))
            p.drawText(QRectF(box.left() + 5, body_top, box.width() - 10, line_h), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(st.label, Qt.ElideRight, int(box.width() - 10)))
        p.setFont(_font(7.5, False, "Consolas"))
        p.setPen(SUBLABEL)
        if st.lines:
            p.drawText(QRectF(box.left() + 5, body_top + line_h, box.width() - 10, line_h),
                       Qt.AlignLeft | Qt.AlignVCenter, st.lines[0])
        if len(st.lines) > 1:
            p.setPen(LABEL)
            p.drawText(QRectF(box.left() + 5, body_top + 2 * line_h, box.width() - 10, line_h),
                       Qt.AlignLeft | Qt.AlignVCenter, st.lines[1])
        if len(st.lines) > 2 and st.lines[2]:
            p.setPen(ENERGIZED)
            p.setFont(_font(7, True))
            p.drawText(QRectF(box.left() + 5, body_top + 2 * line_h, box.width() - 10, line_h),
                       Qt.AlignRight | Qt.AlignVCenter, st.lines[2])
    elif kind == "PAR":
        p.setPen(_pen(None))
        p.drawLine(QPointF(r.left() + 3, r.top() + 6), QPointF(r.left() + 3, r.bottom() - 6))
        p.drawLine(QPointF(r.right() - 3, r.top() + 6), QPointF(r.right() - 3, r.bottom() - 6))
        p.drawLine(QPointF(r.left(), r.top() + 6), QPointF(r.right(), r.top() + 6))
        p.drawLine(QPointF(r.left() + 3, r.bottom() - 6), QPointF(r.right() - 3, r.bottom() - 6))


def tool_icon(kind: str) -> QIcon:
    pix = QPixmap(112, 68)
    pix.setDevicePixelRatio(2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    if kind in ("TON", "TOF", "RTO", "CTU", "CTD"):
        p.setRenderHint(QPainter.Antialiasing, True)
        head_bg, head_fg = TIMER_HEAD if kind in ("TON", "TOF", "RTO") else COUNTER_HEAD
        p.setPen(QPen(NEUTRAL, 2))
        p.drawLine(QPointF(1, 17), QPointF(10, 17))
        p.drawLine(QPointF(46, 17), QPointF(55, 17))
        box = QRectF(10, 4, 36, 26)
        p.setPen(QPen(head_fg, 1.4))
        p.setBrush(head_bg)
        p.drawRoundedRect(box, 4, 4)
        p.setPen(head_fg)
        p.setFont(_font(8, True))
        p.drawText(box, Qt.AlignCenter, kind)
    elif kind == "RUNG":
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(NEUTRAL, 2.5))
        p.drawLine(QPointF(6, 4), QPointF(6, 30))
        p.drawLine(QPointF(50, 4), QPointF(50, 30))
        p.setPen(QPen(SELECTED_BORDER, 2))
        p.drawLine(QPointF(6, 17), QPointF(50, 17))
    elif kind == "PAR":
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(NEUTRAL, 2))
        p.drawLine(QPointF(1, 10), QPointF(55, 10))
        p.drawLine(QPointF(10, 10), QPointF(10, 25))
        p.drawLine(QPointF(46, 10), QPointF(46, 25))
        p.drawLine(QPointF(10, 25), QPointF(46, 25))
        p.setPen(QPen(SELECTED_BORDER, 2, Qt.DotLine))
        p.drawLine(QPointF(20, 25), QPointF(36, 25))
    else:
        paint_symbol(p, kind, QRectF(1, 1, 54, 32), SymbolState())
    p.end()
    return QIcon(pix)
