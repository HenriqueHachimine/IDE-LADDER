"""Primitivas de desenho reutilizaveis pelos ambientes (QPainter).

Estilo comum: fundo em degrade, cartoes com sombra suave, pecas metalicas com
brilho, cores de seguranca (amarelo/preto, vermelho) e etiquetas com o endereco
do CLP que ficam verdes quando o ponto esta ativo.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF,
                           QRadialGradient)

INK = QColor("#1e293b")
MUTED = QColor("#64748b")
GREEN = QColor("#16a34a")
RED = QColor("#dc2626")
AMBER = QColor("#f59e0b")
BLUE = QColor("#2563eb")
CYAN = QColor("#0891b2")
STEEL = QColor("#94a3b8")
WHITE = QColor("#ffffff")
DARK = QColor("#0f172a")
WATER = QColor("#38bdf8")


def font(size: float, bold: bool = False) -> QFont:
    from ..ui.fonts import ui_font
    return ui_font(size, bold)


def mono(size: float, bold: bool = True) -> QFont:
    from ..ui.fonts import mono_font
    return mono_font(size, bold)


def text(p: QPainter, x: float, y: float, s: str, size: float = 8, bold: bool = False, color: QColor = INK,
         align=Qt.AlignLeft | Qt.AlignVCenter, w: float = 200, h: float = 16) -> None:
    p.setFont(font(size, bold))
    p.setPen(color)
    if align & Qt.AlignHCenter:
        x -= w / 2
    elif align & Qt.AlignRight:
        x -= w
    p.drawText(QRectF(x, y - h / 2, w, h), align, s)


def ctext(p: QPainter, x: float, y: float, s: str, size: float = 8, bold: bool = False, color: QColor = INK,
          w: float = 200) -> None:
    """Texto centralizado em (x, y)."""
    text(p, x, y, s, size, bold, color, Qt.AlignHCenter | Qt.AlignVCenter, w)


# ------------------------------------------------------------------ cena
def background(p: QPainter, w: float, h: float, top: str = "#eef3f8", bottom: str = "#dbe3ec") -> None:
    """Fundo em degrade vertical (todos os ambientes chamam antes de desenhar)."""
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bottom))
    p.fillRect(QRectF(0, 0, w, h), QBrush(g))


def sky(p: QPainter, w: float, h: float, day: float = 1.0) -> None:
    """Ceu para cenas externas: day 1 = meio-dia, 0 = noite."""
    p.setRenderHint(QPainter.Antialiasing)
    day = max(0.0, min(1.0, day))
    top = _mix(QColor("#0b1730"), QColor("#7cc4f5"), day)
    bottom = _mix(QColor("#263a5e"), QColor("#e6f3fb"), day)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, top)
    g.setColorAt(1, bottom)
    p.fillRect(QRectF(0, 0, w, h), QBrush(g))


def ground(p: QPainter, y: float, w: float, h: float, color: str = "#9aa7b4", hazard_edge: bool = False) -> None:
    """Piso de concreto da fabrica a partir da altura y."""
    g = QLinearGradient(0, y, 0, h)
    g.setColorAt(0, QColor(color))
    g.setColorAt(1, QColor(color).darker(125))
    p.fillRect(QRectF(0, y, w, h - y), QBrush(g))
    p.setPen(QPen(QColor(255, 255, 255, 60), 1))
    p.drawLine(QPointF(0, y + 0.5), QPointF(w, y + 0.5))
    if hazard_edge:
        hazard(p, QRectF(0, y, w, 5))


def grass(p: QPainter, y: float, w: float, h: float) -> None:
    g = QLinearGradient(0, y, 0, h)
    g.setColorAt(0, QColor("#7fb069"))
    g.setColorAt(1, QColor("#4d7c3a"))
    p.fillRect(QRectF(0, y, w, h - y), QBrush(g))


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def mix(a: QColor, b: QColor, t: float) -> QColor:
    """Cor intermediaria entre a (t = 0) e b (t = 1)."""
    return _mix(a, b, max(0.0, min(1.0, t)))


def shadow(p: QPainter, rect: QRectF, radius: float = 8, depth: float = 4) -> None:
    """Sombra suave (algumas camadas translucidas) sob um retangulo."""
    p.setPen(Qt.NoPen)
    for k in range(3, 0, -1):
        p.setBrush(QColor(15, 23, 42, 14 + 6 * (3 - k)))
        d = depth * k / 3
        p.drawRoundedRect(rect.adjusted(-k + d * 0.3, d, k + d * 0.3, d + k * 0.6), radius + k, radius + k)
    p.setBrush(Qt.NoBrush)


def card(p: QPainter, rect: QRectF, title: str = "", accent: QColor | None = None, dark: bool = False) -> None:
    """Cartao com sombra e faixa de titulo (paineis de operacao, indicadores)."""
    shadow(p, rect, 8, 4)
    p.setPen(QPen(QColor("#334155") if dark else QColor("#cbd5e1"), 1))
    p.setBrush(QColor("#1e293b") if dark else QColor("#ffffff"))
    p.drawRoundedRect(rect, 8, 8)
    if title:
        p.save()
        p.setClipPath(rounded_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), 8))
        p.fillRect(QRectF(rect.left(), rect.top(), rect.width(), 20),
                   accent or (QColor("#334155") if dark else QColor("#e2e8f0")))
        p.restore()
        text(p, rect.left() + 9, rect.top() + 10, title.upper(), 7, True,
             WHITE if (accent is not None or dark) else MUTED, w=rect.width() - 12)
    p.setBrush(Qt.NoBrush)


def panel(p: QPainter, rect: QRectF, title: str = "") -> None:
    card(p, rect, title)


def hazard(p: QPainter, rect: QRectF, stripe: float = 8) -> None:
    """Faixa zebrada amarela e preta (protecoes, batentes, cancelas)."""
    p.save()
    p.setClipRect(rect)
    p.fillRect(rect, QColor("#facc15"))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#111827"))
    x = rect.left() - rect.height()
    while x < rect.right() + rect.height():
        p.drawPolygon(QPolygonF([QPointF(x, rect.bottom()), QPointF(x + stripe, rect.bottom()),
                                 QPointF(x + stripe + rect.height(), rect.top()), QPointF(x + rect.height(), rect.top())]))
        x += stripe * 2
    p.restore()


def metal(p: QPainter, rect: QRectF, color: QColor | str = "#94a3b8", radius: float = 3,
          vertical: bool = False, outline: bool = True) -> None:
    """Peca metalica com brilho (eixo do degrade transversal ao comprimento)."""
    c = QColor(color)
    g = QLinearGradient(rect.left(), rect.top(), rect.right(), rect.top()) if vertical else \
        QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
    g.setColorAt(0, c.darker(115))
    g.setColorAt(0.35, c.lighter(135))
    g.setColorAt(1, c.darker(150))
    p.setPen(QPen(c.darker(220), 1) if outline else Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, radius, radius)
    p.setBrush(Qt.NoBrush)


def plate(p: QPainter, rect: QRectF, label: str, color: QColor | str = "#1e293b", fg: QColor = WHITE,
          size: float = 7.5) -> None:
    """Placa de identificacao."""
    c = QColor(color)
    p.setPen(QPen(c.darker(150), 1))
    p.setBrush(c)
    p.drawRoundedRect(rect, 3, 3)
    p.setFont(font(size, True))
    p.setPen(fg)
    p.drawText(rect, Qt.AlignCenter, label)
    p.setBrush(Qt.NoBrush)


# --------------------------------------------------------- E/S do CLP
def tag(p: QPainter, x: float, y: float, address: str, active: bool | None = None) -> None:
    """Etiqueta com o endereco do CLP (ex.: I0.3), verde quando ativa."""
    p.setFont(font(7, True))
    w = p.fontMetrics().horizontalAdvance(address) + 12
    r = QRectF(x, y - 8, w, 16)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(15, 23, 42, 40))
    p.drawRoundedRect(r.translated(0, 1.2), 4, 4)
    if active:
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#22c55e"))
        g.setColorAt(1, QColor("#15803d"))
        p.setBrush(QBrush(g))
    else:
        p.setBrush(QColor(30, 41, 59, 215))
    p.drawRoundedRect(r, 4, 4)
    dot = QPointF(r.left() + 5, r.center().y())
    p.setBrush(QColor("#bbf7d0") if active else QColor("#64748b"))
    p.drawEllipse(dot, 1.8, 1.8)
    p.setPen(WHITE)
    p.drawText(r.adjusted(5, 0, 0, 0), Qt.AlignCenter, address)
    p.setBrush(Qt.NoBrush)


def lamp(p: QPainter, c: QPointF, r: float, on: bool, color: QColor) -> None:
    """Sinaleiro com aro cromado; aceso tem halo e brilho."""
    if on:
        glow = QRadialGradient(c, r * 2.2)
        col = QColor(color)
        col.setAlpha(120)
        glow.setColorAt(0, col)
        col.setAlpha(0)
        glow.setColorAt(1, col)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(c, r * 2.2, r * 2.2)
    ring = QLinearGradient(c.x(), c.y() - r * 1.25, c.x(), c.y() + r * 1.25)
    ring.setColorAt(0, QColor("#e2e8f0"))
    ring.setColorAt(1, QColor("#475569"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(ring))
    p.drawEllipse(c, r * 1.22, r * 1.22)
    grad = QRadialGradient(QPointF(c.x() - r * 0.35, c.y() - r * 0.4), r * 1.3)
    base = QColor(color) if on else QColor(color).darker(330)
    grad.setColorAt(0, base.lighter(170 if on else 130))
    grad.setColorAt(1, base)
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor("#0f172a"), 1))
    p.drawEllipse(c, r, r)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 120 if on else 45))
    p.drawEllipse(QPointF(c.x() - r * 0.35, c.y() - r * 0.4), r * 0.3, r * 0.22)
    p.setBrush(Qt.NoBrush)


def push_button(p: QPainter, rect: QRectF, label: str, pressed: bool, color: QColor) -> None:
    shadow(p, rect, 6, 2.5)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor("#f8fafc"))
    g.setColorAt(1, QColor("#dbe2ea"))
    p.setPen(QPen(QColor("#94a3b8"), 1))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, 6, 6)
    c = QPointF(rect.left() + rect.height() / 2 + 2, rect.center().y())
    r = rect.height() * 0.33
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#334155"))
    p.drawEllipse(c, r * 1.18, r * 1.18)
    rr = r * (0.86 if pressed else 1.0)
    bg = QRadialGradient(QPointF(c.x() - rr * 0.3, c.y() - rr * 0.35), rr * 1.4)
    col = QColor(color).darker(140) if pressed else QColor(color)
    bg.setColorAt(0, col.lighter(150))
    bg.setColorAt(1, col.darker(115))
    p.setBrush(QBrush(bg))
    p.setPen(QPen(col.darker(170), 1))
    p.drawEllipse(c, rr, rr)
    text(p, c.x() + r + 7, rect.center().y(), label, 8, True, INK, w=rect.width() - 2 * r - 12)
    p.setBrush(Qt.NoBrush)


def switch(p: QPainter, rect: QRectF, label: str, on: bool) -> None:
    shadow(p, rect, 6, 2.5)
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor("#f8fafc"))
    g.setColorAt(1, QColor("#dbe2ea"))
    p.setPen(QPen(QColor("#94a3b8"), 1))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, 6, 6)
    track = QRectF(rect.left() + 6, rect.center().y() - 7, 28, 14)
    p.setBrush(GREEN if on else STEEL)
    p.setPen(QPen(QColor(15, 23, 42, 60), 1))
    p.drawRoundedRect(track, 7, 7)
    knob = QPointF(track.right() - 7 if on else track.left() + 7, track.center().y())
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(15, 23, 42, 60))
    p.drawEllipse(knob + QPointF(0, 1), 5.5, 5.5)
    p.setBrush(WHITE)
    p.drawEllipse(knob, 5.5, 5.5)
    text(p, track.right() + 6, rect.center().y(), label, 8, True, INK, w=rect.width() - 40)


def selector(p: QPainter, rect: QRectF, label: str, options: list[str], index: int) -> None:
    """Chave seletora de varias posicoes (clique troca a posicao)."""
    shadow(p, rect, 6, 2.5)
    p.setPen(QPen(QColor("#94a3b8"), 1))
    p.setBrush(QColor("#f1f5f9"))
    p.drawRoundedRect(rect, 6, 6)
    c = QPointF(rect.left() + rect.height() / 2 + 2, rect.center().y())
    r = rect.height() * 0.36
    p.setBrush(QColor("#1e293b"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(c, r, r)
    n = max(1, len(options))
    a = math.radians(-135 + 270 * index / max(1, n - 1)) if n > 1 else 0
    p.setPen(QPen(WHITE, 2.5, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(c, QPointF(c.x() + math.sin(a) * r * 0.8, c.y() - math.cos(a) * r * 0.8))
    text(p, c.x() + r + 7, rect.center().y() - 6, label, 7, True, MUTED, w=rect.width() - 2 * r - 12)
    text(p, c.x() + r + 7, rect.center().y() + 6, options[index] if options else "", 8, True, INK,
         w=rect.width() - 2 * r - 12)


def sensor(p: QPainter, rect: QRectF, active: bool, vertical: bool = True) -> None:
    """Sensor indutivo/optico: corpo cilindrico rosqueado com LED na ponta."""
    p.setPen(QPen(QColor("#0f172a"), 1))
    grad = QLinearGradient(rect.topLeft(), rect.topRight() if vertical else rect.bottomLeft())
    grad.setColorAt(0, QColor("#93c5fd"))
    grad.setColorAt(0.4, QColor("#3b82f6"))
    grad.setColorAt(1, QColor("#1e3a8a"))
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(rect, 3, 3)
    p.setPen(QPen(QColor(15, 23, 42, 70), 1))
    if vertical:
        for y in range(int(rect.top()) + 4, int(rect.bottom()) - 7, 3):
            p.drawLine(QPointF(rect.left() + 1, y), QPointF(rect.right() - 1, y))
    else:
        for x in range(int(rect.left()) + 4, int(rect.right()) - 7, 3):
            p.drawLine(QPointF(x, rect.top() + 1), QPointF(x, rect.bottom() - 1))
    tip = QRectF(rect.left(), rect.bottom() - 6, rect.width(), 6) if vertical else \
        QRectF(rect.right() - 6, rect.top(), 6, rect.height())
    p.setPen(QPen(QColor("#0f172a"), 1))
    p.setBrush(AMBER if active else QColor("#78350f"))
    p.drawRect(tip)
    if active:
        glow = QColor(AMBER)
        glow.setAlpha(80)
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(tip.center(), 7, 7)
    p.setBrush(Qt.NoBrush)


def beam(p: QPainter, a: QPointF, b: QPointF, active: bool) -> None:
    if active:
        p.setPen(QPen(QColor(239, 68, 68, 70), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(a, b)
    pen = QPen(QColor(239, 68, 68, 230) if active else QColor(148, 163, 184, 120), 1.6, Qt.DashLine)
    p.setPen(pen)
    p.drawLine(a, b)


def motor(p: QPainter, c: QPointF, r: float, on: bool, angle: float, label: str = "M") -> None:
    """Motor eletrico com aletas, caixa de ligacao e ventoinha girando."""
    body = QRectF(c.x() - r * 1.5, c.y() - r, r * 2.4, r * 2)
    shadow(p, body, 5, 3)
    metal(p, body, "#1d4ed8" if on else "#475569", 5)
    p.setPen(QPen(QColor(15, 23, 42, 70), 1))
    for k in range(1, 6):
        y = body.top() + body.height() * k / 6
        p.drawLine(QPointF(body.left() + 3, y), QPointF(body.left() + r * 0.55, y))
    p.setBrush(QColor("#e2e8f0"))
    p.setPen(QPen(QColor("#0f172a"), 1.2))
    p.drawEllipse(c, r * 0.75, r * 0.75)
    p.setPen(QPen(GREEN if on else QColor("#334155"), 2.5, Qt.SolidLine, Qt.RoundCap))
    for k in range(3):
        a = angle + k * 2 * math.pi / 3
        p.drawLine(c, QPointF(c.x() + math.cos(a) * r * 0.65, c.y() + math.sin(a) * r * 0.65))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0f172a"))
    p.drawEllipse(c, r * 0.12, r * 0.12)
    text(p, c.x() - r * 1.5 + 4, c.y() - r + 8, label, 7, True, WHITE)


def arrow(p: QPainter, c: QPointF, size: float, up: bool, on: bool) -> None:
    s = size / 2
    pts = [QPointF(c.x(), c.y() - s), QPointF(c.x() + s, c.y() + s * 0.2), QPointF(c.x() - s, c.y() + s * 0.2)] \
        if up else [QPointF(c.x(), c.y() + s), QPointF(c.x() + s, c.y() - s * 0.2), QPointF(c.x() - s, c.y() - s * 0.2)]
    p.setPen(Qt.NoPen)
    p.setBrush(GREEN if on else QColor("#475569"))
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(Qt.NoBrush)


def harrow(p: QPainter, c: QPointF, size: float, right: bool, on: bool, color: QColor = GREEN) -> None:
    """Seta horizontal (sentido de movimento)."""
    s = size / 2
    d = 1 if right else -1
    pts = [QPointF(c.x() + d * s, c.y()), QPointF(c.x() - d * s * 0.2, c.y() - s), QPointF(c.x() - d * s * 0.2, c.y() + s)]
    p.setPen(Qt.NoPen)
    p.setBrush(color if on else QColor("#475569"))
    p.drawPolygon(QPolygonF(pts))
    p.setBrush(Qt.NoBrush)


# ---------------------------------------------------------- processo
def pipe(p: QPainter, pts: list[QPointF], width: float = 8, flow: float | None = None,
         fluid: QColor = WATER, color: QColor | str = "#94a3b8") -> None:
    """Tubulacao; com flow (fase, em pixels) desenha o fluido correndo."""
    if len(pts) < 2:
        return
    path = QPainterPath(pts[0])
    for q in pts[1:]:
        path.lineTo(q)
    c = QColor(color)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(c.darker(170), width + 2, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
    p.drawPath(path)
    p.setPen(QPen(c, width, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
    p.drawPath(path)
    p.setPen(QPen(c.lighter(140), max(1.0, width * 0.25), Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
    p.drawPath(path.translated(0, -width * 0.18))
    if flow is not None:
        f = QColor(fluid)
        p.setPen(QPen(f, max(2.0, width * 0.5), Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin))
        p.drawPath(path)
        pen = QPen(f.lighter(150), max(1.5, width * 0.3), Qt.CustomDashLine, Qt.FlatCap, Qt.MiterJoin)
        pen.setDashPattern([2, 3])
        pen.setDashOffset(-flow / max(1.0, width * 0.3))
        p.setPen(pen)
        p.drawPath(path)


def tank(p: QPainter, rect: QRectF, level: float, liquid: QColor = WATER, marks: bool = True,
         wave: float = 0.0) -> None:
    """Tanque de aco inox com visor; level de 0 a 1."""
    shadow(p, rect, 10, 4)
    metal(p, rect, "#cbd5e1", 10, vertical=True)
    inner = rect.adjusted(6, 6, -6, -6)
    p.setPen(QPen(QColor("#475569"), 1))
    p.setBrush(QColor("#f1f5f9"))
    p.drawRoundedRect(inner, 6, 6)
    lv = max(0.0, min(1.0, level))
    if lv > 0:
        top = inner.bottom() - inner.height() * lv
        path = QPainterPath()
        path.moveTo(inner.left(), inner.bottom())
        path.lineTo(inner.left(), top)
        n = 12
        for k in range(n + 1):
            x = inner.left() + inner.width() * k / n
            path.lineTo(x, top + math.sin(wave + k * 0.9) * (1.6 if lv < 0.99 else 0))
        path.lineTo(inner.right(), inner.bottom())
        path.closeSubpath()
        clip = QPainterPath()
        clip.addRoundedRect(inner, 6, 6)
        g = QLinearGradient(inner.left(), 0, inner.right(), 0)
        g.setColorAt(0, QColor(liquid).darker(115))
        g.setColorAt(0.4, QColor(liquid).lighter(120))
        g.setColorAt(1, QColor(liquid).darker(130))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawPath(path.intersected(clip))
    if marks:
        p.setPen(QPen(QColor(15, 23, 42, 110), 1))
        for k in range(1, 10):
            y = inner.bottom() - inner.height() * k / 10
            p.drawLine(QPointF(inner.right() - (8 if k % 5 == 0 else 4), y), QPointF(inner.right(), y))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(255, 255, 255, 70))
    p.drawRoundedRect(QRectF(inner.left() + 4, inner.top() + 4, 5, inner.height() - 8), 2, 2)
    p.setBrush(Qt.NoBrush)


def valve(p: QPainter, c: QPointF, size: float, opened: bool, vertical: bool = False, label: str = "") -> None:
    """Valvula solenoide (gravata) com atuador; verde aberta, cinza fechada."""
    s = size / 2
    col = GREEN if opened else QColor("#64748b")
    if vertical:
        a = [QPointF(c.x() - s, c.y() - s), QPointF(c.x() + s, c.y() - s), QPointF(c.x(), c.y())]
        b = [QPointF(c.x() - s, c.y() + s), QPointF(c.x() + s, c.y() + s), QPointF(c.x(), c.y())]
        stem_to = QPointF(c.x() + s * 1.6, c.y())
    else:
        a = [QPointF(c.x() - s, c.y() - s), QPointF(c.x() - s, c.y() + s), QPointF(c.x(), c.y())]
        b = [QPointF(c.x() + s, c.y() - s), QPointF(c.x() + s, c.y() + s), QPointF(c.x(), c.y())]
        stem_to = QPointF(c.x(), c.y() - s * 1.6)
    p.setPen(QPen(QColor("#0f172a"), 1.2))
    p.drawLine(c, stem_to)
    p.setBrush(col)
    p.drawPolygon(QPolygonF(a))
    p.drawPolygon(QPolygonF(b))
    act = QRectF(stem_to.x() - s * 0.6, stem_to.y() - s * 0.5, s * 1.2, s)
    metal(p, act, "#1e293b" if not opened else "#166534", 2)
    if label:
        text(p, c.x() + s + 4, c.y() + (s + 6 if not vertical else 0), label, 7, True, MUTED, w=80)
    p.setBrush(Qt.NoBrush)


def fan(p: QPainter, c: QPointF, r: float, angle: float, on: bool) -> None:
    """Ventilador/exaustor em grade circular."""
    p.setPen(QPen(QColor("#334155"), 2))
    p.setBrush(QColor("#e2e8f0"))
    p.drawEllipse(c, r, r)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#0ea5e9") if on else QColor("#64748b"))
    for k in range(4):
        a = angle + k * math.pi / 2
        blade = QPainterPath(c)
        blade.cubicTo(QPointF(c.x() + math.cos(a - 0.5) * r * 0.9, c.y() + math.sin(a - 0.5) * r * 0.9),
                      QPointF(c.x() + math.cos(a + 0.2) * r * 0.95, c.y() + math.sin(a + 0.2) * r * 0.95), c)
        p.drawPath(blade)
    p.setBrush(QColor("#0f172a"))
    p.drawEllipse(c, r * 0.14, r * 0.14)
    p.setPen(QPen(QColor(51, 65, 85, 120), 1))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(c, r * 0.62, r * 0.62)


def stack_light(p: QPainter, x: float, y: float, states: list[tuple[bool, QColor]], seg: float = 14) -> None:
    """Coluna luminosa (andon); states de cima para baixo."""
    n = len(states)
    metal(p, QRectF(x - 2, y + n * seg, 4, 18), "#475569", 1, vertical=True)
    for k, (on, col) in enumerate(states):
        r = QRectF(x - seg * 0.55, y + k * seg, seg * 1.1, seg - 1)
        c = QColor(col) if on else QColor(col).darker(320)
        g = QLinearGradient(r.left(), 0, r.right(), 0)
        g.setColorAt(0, c.darker(120))
        g.setColorAt(0.4, c.lighter(150 if on else 110))
        g.setColorAt(1, c.darker(140))
        p.setPen(QPen(QColor("#0f172a"), 0.8))
        p.setBrush(QBrush(g))
        p.drawRoundedRect(r, 2, 2)
        if on:
            glow = QColor(col)
            glow.setAlpha(55)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(r.center(), seg * 1.2, seg * 0.85)
    metal(p, QRectF(x - seg * 0.6, y - 4, seg * 1.2, 5), "#334155", 2)
    p.setBrush(Qt.NoBrush)


def conveyor(p: QPainter, rect: QRectF, offset: float, running: bool) -> None:
    """Esteira de correia com roletes; offset (pixels) anima as taliscas."""
    r = rect.height() / 2
    shadow(p, rect, r, 3)
    p.setPen(QPen(QColor("#0f172a"), 1))
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor("#475569"))
    g.setColorAt(0.5, QColor("#1f2937"))
    g.setColorAt(1, QColor("#374151"))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, r, r)
    p.save()
    p.setClipRect(rect.adjusted(r, 0, -r, 0))
    p.setPen(QPen(QColor("#9ca3af") if running else QColor("#6b7280"), 1.3))
    step = 14.0
    x = rect.left() + (offset % step)
    while x < rect.right():
        p.drawLine(QPointF(x, rect.top() + 1), QPointF(x, rect.top() + 3.5))
        x += step
    p.restore()
    for cx in (rect.left() + r, rect.right() - r):
        p.setBrush(QColor("#cbd5e1"))
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.drawEllipse(QPointF(cx, rect.center().y()), r * 0.62, r * 0.62)
        a = offset / max(1.0, r) if running else offset / max(1.0, r)
        p.drawLine(QPointF(cx, rect.center().y()),
                   QPointF(cx + math.cos(a) * r * 0.6, rect.center().y() + math.sin(a) * r * 0.6))
    p.setBrush(Qt.NoBrush)


def cylinder(p: QPainter, rect: QRectF, ext: float, horizontal: bool = True, reverse: bool = False,
             stroke: float | None = None, color: str = "#cbd5e1") -> QPointF:
    """Cilindro pneumatico: camisa em rect e haste estendida ext (0..1) por stroke pixels.
    Retorna a ponta da haste. reverse = haste sai para a esquerda/para cima."""
    ext = max(0.0, min(1.0, ext))
    if horizontal:
        stroke = rect.width() if stroke is None else stroke
        rod_h = rect.height() * 0.32
        if not reverse:
            x0 = rect.right() - 6
            tip = QPointF(rect.right() + ext * stroke, rect.center().y())
            rod = QRectF(x0, rect.center().y() - rod_h / 2, tip.x() - x0, rod_h)
        else:
            x0 = rect.left() + 6
            tip = QPointF(rect.left() - ext * stroke, rect.center().y())
            rod = QRectF(tip.x(), rect.center().y() - rod_h / 2, x0 - tip.x(), rod_h)
        metal(p, rod, "#e5e7eb", 1)
        metal(p, rect, color, 3)
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#475569"))
        for x in (rect.left() + 2, rect.right() - 6):
            p.drawRect(QRectF(x, rect.top() - 1, 4, rect.height() + 2))
    else:
        stroke = rect.height() if stroke is None else stroke
        rod_w = rect.width() * 0.32
        if not reverse:
            y0 = rect.bottom() - 6
            tip = QPointF(rect.center().x(), rect.bottom() + ext * stroke)
            rod = QRectF(rect.center().x() - rod_w / 2, y0, rod_w, tip.y() - y0)
        else:
            y0 = rect.top() + 6
            tip = QPointF(rect.center().x(), rect.top() - ext * stroke)
            rod = QRectF(rect.center().x() - rod_w / 2, tip.y(), rod_w, y0 - tip.y())
        metal(p, rod, "#e5e7eb", 1, vertical=True)
        metal(p, rect, color, 3, vertical=True)
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#475569"))
        for y in (rect.top() + 2, rect.bottom() - 6):
            p.drawRect(QRectF(rect.left() - 1, y, rect.width() + 2, 4))
    p.setBrush(Qt.NoBrush)
    return tip


# ---------------------------------------------------------- indicadores
def lcd(p: QPainter, rect: QRectF, value: str, color: QColor | str = "#4ade80", label: str = "",
        size: float | None = None) -> None:
    """Display digital (fundo escuro, digitos monoespacados)."""
    shadow(p, rect, 5, 2)
    p.setPen(QPen(QColor("#020617"), 1.2))
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor("#0b1220"))
    g.setColorAt(1, QColor("#111c2e"))
    p.setBrush(QBrush(g))
    p.drawRoundedRect(rect, 5, 5)
    col = QColor(color)
    fs = size or max(7.0, rect.height() * 0.42)
    if label:
        text(p, rect.left() + 6, rect.top() + 8, label, 6.5, True, QColor("#64748b"), w=rect.width() - 8)
        r = rect.adjusted(4, 10, -6, 0)
    else:
        r = rect.adjusted(4, 0, -6, 0)
    p.setFont(mono(fs, True))
    ghost = QColor(col)
    ghost.setAlpha(28)
    p.setPen(ghost)
    p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, "8" * len(value.replace(".", "").replace(",", "")))
    p.setPen(col)
    p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, value)


def gauge(p: QPainter, c: QPointF, r: float, value: float, vmin: float, vmax: float, label: str = "",
          unit: str = "", zones: list[tuple[float, float, QColor | str]] = (), fmt: str = "{:.0f}",
          ticks: int = 6) -> None:
    """Manometro/indicador analogico de 240 graus com faixas coloridas."""
    shadow(p, QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), r, 3)
    ring = QLinearGradient(c.x(), c.y() - r, c.x(), c.y() + r)
    ring.setColorAt(0, QColor("#e2e8f0"))
    ring.setColorAt(1, QColor("#64748b"))
    p.setPen(QPen(QColor("#334155"), 1))
    p.setBrush(QBrush(ring))
    p.drawEllipse(c, r, r)
    p.setBrush(QColor("#ffffff"))
    p.drawEllipse(c, r * 0.9, r * 0.9)
    span = max(1e-9, vmax - vmin)

    def ang(v: float) -> float:
        return math.radians(210 - 240 * (max(vmin, min(vmax, v)) - vmin) / span)

    arc = QRectF(c.x() - r * 0.74, c.y() - r * 0.74, r * 1.48, r * 1.48)
    for a, b, col in zones:
        p.setPen(QPen(QColor(col), r * 0.1, Qt.SolidLine, Qt.FlatCap))
        a0, a1 = math.degrees(ang(a)), math.degrees(ang(b))
        p.drawArc(arc, int(a1 * 16), int((a0 - a1) * 16))
    p.setPen(QPen(QColor("#334155"), 1.2))
    for k in range(ticks + 1):
        a = ang(vmin + span * k / ticks)
        p.drawLine(QPointF(c.x() + math.cos(a) * r * 0.8, c.y() - math.sin(a) * r * 0.8),
                   QPointF(c.x() + math.cos(a) * r * 0.88, c.y() - math.sin(a) * r * 0.88))
    a = ang(value)
    p.setPen(QPen(RED, max(1.5, r * 0.06), Qt.SolidLine, Qt.RoundCap))
    p.drawLine(c, QPointF(c.x() + math.cos(a) * r * 0.78, c.y() - math.sin(a) * r * 0.78))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#1e293b"))
    p.drawEllipse(c, r * 0.09, r * 0.09)
    ctext(p, c.x(), c.y() + r * 0.42, (fmt.format(value) + (" " + unit if unit else "")), max(6.5, r * 0.2), True,
          INK, w=r * 2)
    if label:
        ctext(p, c.x(), c.y() + r + 9, label, 7, True, MUTED, w=r * 3)
    p.setBrush(Qt.NoBrush)


def bar(p: QPainter, rect: QRectF, frac: float, color: QColor | str = GREEN, vertical: bool = False,
        marks: list[tuple[float, QColor | str]] = ()) -> None:
    """Barra de nivel/progresso com marcas (limites, setpoint)."""
    frac = max(0.0, min(1.0, frac))
    p.setPen(QPen(QColor("#94a3b8"), 1))
    p.setBrush(QColor("#e2e8f0"))
    p.drawRoundedRect(rect, 3, 3)
    if vertical:
        fill = QRectF(rect.left(), rect.bottom() - rect.height() * frac, rect.width(), rect.height() * frac)
    else:
        fill = QRectF(rect.left(), rect.top(), rect.width() * frac, rect.height())
    if frac > 0:
        c = QColor(color)
        g = QLinearGradient(rect.topLeft(), rect.topRight() if vertical else rect.bottomLeft())
        g.setColorAt(0, c.lighter(125))
        g.setColorAt(1, c.darker(115))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(g))
        p.drawRoundedRect(fill, 3, 3)
    for f, col in marks:
        p.setPen(QPen(QColor(col), 2))
        if vertical:
            y = rect.bottom() - rect.height() * f
            p.drawLine(QPointF(rect.left() - 3, y), QPointF(rect.right() + 3, y))
        else:
            x = rect.left() + rect.width() * f
            p.drawLine(QPointF(x, rect.top() - 3), QPointF(x, rect.bottom() + 3))
    p.setBrush(Qt.NoBrush)


def trend(p: QPainter, rect: QRectF, series: list[tuple[list[float], QColor | str]], vmin: float, vmax: float,
          title: str = "", lines: list[tuple[float, QColor | str]] = (), span: int | None = None) -> None:
    """Grafico de tendencia (registrador) com as ultimas amostras de cada serie."""
    card(p, rect, title)
    top = rect.top() + (22 if title else 6)
    plot = QRectF(rect.left() + 6, top, rect.width() - 12, rect.bottom() - top - 6)
    p.setPen(QPen(QColor("#e2e8f0"), 1))
    for k in range(1, 4):
        y = plot.top() + plot.height() * k / 4
        p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
    rng = max(1e-9, vmax - vmin)

    def y_of(v: float) -> float:
        return plot.bottom() - plot.height() * (max(vmin, min(vmax, v)) - vmin) / rng

    for v, col in lines:
        pen = QPen(QColor(col), 1, Qt.DashLine)
        p.setPen(pen)
        p.drawLine(QPointF(plot.left(), y_of(v)), QPointF(plot.right(), y_of(v)))
    for values, col in series:
        n = span or max(2, len(values))
        if len(values) < 2:
            continue
        path = QPainterPath()
        for k, v in enumerate(values[-n:]):
            x = plot.left() + plot.width() * k / (n - 1)
            pt = QPointF(x, y_of(v))
            path.moveTo(pt) if k == 0 else path.lineTo(pt)
        p.setPen(QPen(QColor(col), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def rounded_path(rect: QRectF, r: float) -> QPainterPath:
    path = QPainterPath()
    path.addRoundedRect(rect, r, r)
    return path
