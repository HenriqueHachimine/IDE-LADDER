"""Icones da barra de ferramentas, desenhados com QPainter (sem arquivos externos)."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK = QColor("#334155")
BLUE = QColor("#2563eb")
GREEN = QColor("#16a34a")
RED = QColor("#dc2626")
AMBER = QColor("#d97706")


def _arrow_arc(p: QPainter, r: QRectF, start: float, span: float, color: QColor, head_at_end: bool = True) -> None:
    p.setPen(QPen(color, 2.0, Qt.SolidLine, Qt.RoundCap))
    p.drawArc(r, int(start * 16), int(span * 16))
    ang = math.radians(start + (span if head_at_end else 0))
    cx, cy, rad = r.center().x(), r.center().y(), r.width() / 2
    tip = QPointF(cx + rad * math.cos(ang), cy - rad * math.sin(ang))
    # tangente no sentido do arco
    sgn = 1 if span > 0 else -1
    tx, ty = -math.sin(ang) * sgn, -math.cos(ang) * sgn
    nx, ny = -ty, tx
    p.setPen(Qt.NoPen)
    p.setBrush(color)
    p.drawPolygon(QPolygonF([tip + QPointF(tx * 4, ty * 4), tip + QPointF(nx * 3.5, ny * 3.5),
                             tip - QPointF(nx * 3.5, ny * 3.5)]))
    p.setBrush(Qt.NoBrush)


def _draw(name: str, p: QPainter) -> None:
    pen = QPen(INK, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    if name == "new":
        path = QPainterPath()
        path.moveTo(5, 2.5); path.lineTo(13, 2.5); path.lineTo(17, 6.5); path.lineTo(17, 19.5)
        path.lineTo(5, 19.5); path.closeSubpath()
        p.setBrush(QColor("white")); p.drawPath(path)
        p.setPen(QPen(BLUE, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(11, 10), QPointF(11, 16)); p.drawLine(QPointF(8, 13), QPointF(14, 13))
    elif name == "open":
        p.setBrush(QColor("#fde68a")); p.setPen(QPen(AMBER, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        path = QPainterPath()
        path.moveTo(2.5, 5); path.lineTo(8, 5); path.lineTo(10, 7); path.lineTo(18.5, 7); path.lineTo(18.5, 18)
        path.lineTo(2.5, 18); path.closeSubpath()
        p.drawPath(path)
        p.setBrush(QColor("#fbbf24"))
        path = QPainterPath()
        path.moveTo(2.5, 18); path.lineTo(5.5, 10); path.lineTo(20.5, 10); path.lineTo(18.5, 18); path.closeSubpath()
        p.drawPath(path)
    elif name == "save":
        p.setBrush(QColor("#dbeafe")); p.setPen(QPen(BLUE, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawRoundedRect(QRectF(3, 3, 16, 16), 2, 2)
        p.setBrush(QColor("white")); p.drawRect(QRectF(6.5, 3, 9, 5.5))
        p.setBrush(BLUE); p.drawRect(QRectF(7, 12, 8, 7))
    elif name in ("undo", "redo"):
        if name == "undo":
            _arrow_arc(p, QRectF(5, 5, 13, 12), 0, 200, INK)
        else:
            _arrow_arc(p, QRectF(4, 5, 13, 12), 180, -200, INK)
    elif name == "compile":
        p.setBrush(QColor("#dcfce7")); p.setPen(QPen(GREEN, 1.6))
        p.drawEllipse(QRectF(2.5, 2.5, 17, 17))
        p.setPen(QPen(GREEN, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(7, 11.5), QPointF(10, 14.5), QPointF(15.5, 8)]))
    elif name == "run":
        p.setPen(Qt.NoPen); p.setBrush(GREEN)
        p.drawPolygon(QPolygonF([QPointF(6, 3.5), QPointF(18.5, 11), QPointF(6, 18.5)]))
    elif name == "pause":
        p.setPen(Qt.NoPen); p.setBrush(AMBER)
        p.drawRoundedRect(QRectF(5.5, 4, 4, 14), 1, 1); p.drawRoundedRect(QRectF(12.5, 4, 4, 14), 1, 1)
    elif name == "stop":
        p.setPen(Qt.NoPen); p.setBrush(RED)
        p.drawRoundedRect(QRectF(5, 5, 12, 12), 2, 2)
    elif name == "scan":
        _arrow_arc(p, QRectF(3.5, 3.5, 15, 15), 90, -300, BLUE)
        p.setPen(QPen(BLUE, 1)); f = p.font(); f.setPointSizeF(6.5); f.setBold(True); p.setFont(f)
        p.drawText(QRectF(3.5, 3.5, 15, 15), Qt.AlignCenter, "1")
    elif name == "step":
        p.setPen(Qt.NoPen); p.setBrush(BLUE)
        p.drawPolygon(QPolygonF([QPointF(4, 5), QPointF(13, 11), QPointF(4, 17)]))
        p.drawRoundedRect(QRectF(14.5, 5, 3, 12), 1, 1)
    elif name == "reset":
        _arrow_arc(p, QRectF(4, 4, 14, 14), 60, 280, INK)
    elif name in ("zoom_in", "zoom_out"):
        p.setPen(QPen(INK, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.drawEllipse(QRectF(3, 3, 12, 12))
        p.drawLine(QPointF(13.5, 13.5), QPointF(19, 19))
        p.drawLine(QPointF(6.5, 9), QPointF(11.5, 9))
        if name == "zoom_in":
            p.drawLine(QPointF(9, 6.5), QPointF(9, 11.5))
    elif name == "transfer":
        p.setPen(QPen(INK, 1.5)); p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(QRectF(4, 13, 14, 6), 1.5, 1.5)
        p.setPen(QPen(BLUE, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(11, 2.5), QPointF(11, 10.5))
        p.drawPolyline(QPolygonF([QPointF(7.5, 7.5), QPointF(11, 11), QPointF(14.5, 7.5)]))
    elif name == "rung":
        p.setPen(QPen(INK, 1.8, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(3, 3), QPointF(3, 19)); p.drawLine(QPointF(19, 3), QPointF(19, 19))
        p.setPen(QPen(BLUE, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(3, 11), QPointF(19, 11))
    elif name == "verify":
        p.setPen(QPen(INK, 1.4)); p.setBrush(QColor("#1e293b"))
        p.drawRoundedRect(QRectF(4, 4, 14, 14), 2, 2)
        p.setPen(QPen(INK, 1.4))
        for k in range(3):
            y = 7 + k * 4
            p.drawLine(QPointF(1.5, y), QPointF(4, y)); p.drawLine(QPointF(18, y), QPointF(20.5, y))
        p.setPen(QPen(QColor("#4ade80"), 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(QPolygonF([QPointF(7.5, 11), QPointF(10, 13.5), QPointF(14.5, 8.5)]))
    elif name == "il":
        p.setPen(QPen(INK, 1.4)); p.setBrush(QColor("white"))
        p.drawRoundedRect(QRectF(3, 3, 16, 16), 2, 2)
        p.setPen(QPen(BLUE, 1.8, Qt.SolidLine, Qt.RoundCap))
        for k, w in enumerate((8, 6, 9)):
            y = 7.5 + k * 3.5
            p.drawLine(QPointF(6, y), QPointF(6 + w, y))
    elif name == "env":
        p.setPen(QPen(INK, 1.3)); p.setBrush(QColor("#e0f2fe"))
        p.drawRoundedRect(QRectF(2.5, 3.5, 17, 15), 2, 2)
        p.setBrush(QColor("#f97316")); p.setPen(Qt.NoPen)
        p.drawRect(QRectF(4, 14, 14, 3))
        p.setBrush(QColor("#fde68a")); p.setPen(QPen(QColor("#92400e"), 1))
        p.drawRect(QRectF(6, 9.5, 5, 4.5))
        p.setBrush(GREEN); p.setPen(Qt.NoPen)
        p.drawEllipse(QPointF(16, 7.5), 2, 2)
    elif name == "delete":
        p.setPen(QPen(RED, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(6, 6), QPointF(16, 16)); p.drawLine(QPointF(16, 6), QPointF(6, 16))


def make_icon(name: str) -> QIcon:
    icon = QIcon()
    for scale in (1, 2):
        pix = QPixmap(22 * scale, 22 * scale)
        pix.setDevicePixelRatio(scale)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        _draw(name, p)
        p.end()
        icon.addPixmap(pix)
    return icon
