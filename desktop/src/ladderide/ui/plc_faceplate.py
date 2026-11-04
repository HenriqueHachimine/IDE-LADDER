"""Desenho do CLP real na aba Processo > CLP real, parecido com o equipamento.

WEG CLIC-02 (como a foto do CLW-02/12HR-D): caixa bege, bornes escuros com os nomes
impressos (+ - I1.. A1..) e os textos "DC 24V" / "INPUT 8 x DC(...)", faixa azul CLIC 02,
display LCD cinza (com luz de fundo conectado: a tela de estado I, Z, Q e dia/hora),
teclado azul em losango (setas no meio, DEL/SEL/ESC/OK nas diagonais), tampa de
expansao e as saidas embaixo ("OUTPUT 4 x RELAY/8A", rele em pares Q1 Q1...).

Omron CP1E: caixa grafite, blocos de bornes em duas fileiras desencontradas sob
tampas, linhas de indicadores IN (canais 0 e 1) e OUT (canais 100 e 101) com LEDs
laranja numerados, LEDs de operacao (POWER, RUN, ERR/ALM, INH, PRPHL, BKUP),
tampa da porta USB, conector RS-232C de 9 pinos e tampa do slot de opcao.

O desenho e feito numa tela virtual de tamanho fixo e escalado para o widget.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPolygonF, QRadialGradient
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import theme

WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")      # como o display do CLIC-02


def _font(px: float, bold: bool = False, mono: bool = False) -> QFont:
    f = QFont("Consolas" if mono else "Segoe UI")
    f.setPixelSize(max(1, int(round(px))))
    f.setBold(bold)
    return f


def _vgrad(rect: QRectF, top: str, bottom: str) -> QLinearGradient:
    g = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    g.setColorAt(0, QColor(top))
    g.setColorAt(1, QColor(bottom))
    return g


def _text(p: QPainter, rect: QRectF, text: str, px: float, color: str, bold: bool = False,
          align=Qt.AlignCenter, mono: bool = False) -> None:
    p.setFont(_font(px, bold, mono))
    p.setPen(QColor(color))
    p.drawText(rect, align, text)


def _screw(p: QPainter, cx: float, cy: float, r: float) -> None:
    """Parafuso do borne: cabeca prateada com fenda em cruz."""
    g = QRadialGradient(QPointF(cx - r * 0.35, cy - r * 0.35), r * 1.4)
    g.setColorAt(0, QColor("#f4f5f6"))
    g.setColorAt(1, QColor("#8b9097"))
    p.setPen(QPen(QColor("#3f4246"), 1))
    p.setBrush(g)
    p.drawEllipse(QPointF(cx, cy), r, r)
    p.setPen(QPen(QColor("#4b4f55"), max(1.0, r * 0.18)))
    p.drawLine(QPointF(cx - r * 0.6, cy), QPointF(cx + r * 0.6, cy))
    p.drawLine(QPointF(cx, cy - r * 0.6), QPointF(cx, cy + r * 0.6))


def _wire(p: QPainter, x: float, y0: float, y1: float, color: str, w: float = 6) -> None:
    p.setPen(QPen(QColor("#1f2124"), w + 2, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(x, y0), QPointF(x, y1))
    p.setPen(QPen(QColor(color), w, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(x, y0), QPointF(x, y1))


def _led(p: QPainter, rect: QRectF, on: bool, color: str, off: str = "#4a4d52") -> None:
    p.setPen(QPen(QColor("#151618"), 0.8))
    if on:
        g = QRadialGradient(rect.center(), max(rect.width(), rect.height()))
        g.setColorAt(0, QColor("#fff7d6"))
        g.setColorAt(0.35, QColor(color))
        g.setColorAt(1, QColor(color).darker(130))
        p.setBrush(g)
    else:
        p.setBrush(QColor(off))
    p.drawRoundedRect(rect, 1.5, 1.5)


def _din_rail(p: QPainter, width: float, y: float) -> None:
    rail = QRectF(0, y - 17, width, 34)
    p.setPen(Qt.NoPen)
    p.setBrush(_vgrad(rail, "#d5d8dc", "#8e9399"))
    p.drawRect(rail)
    p.setBrush(QColor("#6f747a"))
    x = 14.0
    while x < width:
        p.drawRoundedRect(QRectF(x, y - 4, 22, 8), 4, 4)
        x += 46


class PlcFaceplate(QWidget):
    """CLP desenhado com as entradas e saidas ao vivo."""

    SIZES = {"hostlink": (960, 440)}           # CLIC-02: largura conforme os bornes (_canvas)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.style_key = "clic02"
        self.catalog = ""
        self.n_in, self.n_out = 8, 4
        self.inputs = self.outputs = 0
        self.mode = ""
        self.connected = False
        self.error = False
        self.unit = 1
        self.modules: list[tuple[str, int, int]] = []   # (catalogo, entradas, saidas) dos modulos de expansao
        self.setMinimumSize(360, 190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_state(self, **kw) -> None:
        changed = False
        for k, v in kw.items():
            if getattr(self, k) != v:
                setattr(self, k, v)
                changed = True
        if changed:
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        p.fillRect(self.rect(), theme.color("SURFACE"))
        total = (self.n_in, self.n_out)
        self.n_in = total[0] - sum(m[1] for m in self.modules)      # o CPU e desenhado so com as E/S dele
        self.n_out = total[1] - sum(m[2] for m in self.modules)
        try:
            cw, vh = self._canvas()
            widths = [self._module_width(m) for m in self.modules]
            vw = cw + sum(widths)
            s = min(self.width() / vw, self.height() / vh)
            p.translate((self.width() - vw * s) / 2, (self.height() - vh * s) / 2)
            p.scale(s, s)
            if self.style_key == "hostlink":                   # CP1E: chapa de montagem e trilho DIN
                plate = QRectF(0, 0, vw, vh)
                p.setPen(Qt.NoPen)
                p.setBrush(_vgrad(plate, "#d9dde2", "#c3c9cf") if not theme.is_dark()
                           else _vgrad(plate, "#2c3443", "#222936"))
                p.drawRoundedRect(plate, 10, 10)
                p.setClipRect(plate)
                _din_rail(p, vw, vh / 2)
                self._paint_cp1e(p)
            else:
                self._paint_clic(p)
            # modulos de expansao encaixados a direita, na ordem
            x, k_in, k_out = cw, self.n_in, self.n_out
            word_in, word_out = -(-self.n_in // 12), 100 + -(-self.n_out // 8)
            ex = ey = 0
            for (name, m_in, m_out), w in zip(self.modules, widths):
                p.save()
                p.translate(x, 0)
                if self.style_key == "hostlink":
                    self._paint_cp1w(p, name, m_in, m_out, w, vh, k_in, k_out, word_in, word_out)
                else:
                    self._paint_clic_module(p, name, m_in, m_out, w, vh, k_in, k_out, ex, ey)
                p.restore()
                x += w
                k_in, k_out = k_in + m_in, k_out + m_out
                word_in, word_out = word_in + -(-m_in // 12), word_out + -(-m_out // 8)
                ex, ey = ex + m_in, ey + m_out
        finally:
            self.n_in, self.n_out = total
        p.end()

    def _module_width(self, module) -> float:
        _name, m_in, m_out = module
        if self.style_key != "hostlink":
            return 214.0
        pts = m_in + m_out
        return 210.0 if pts <= 8 else 300.0 if pts <= 20 else 430.0

    # ================================================================ modulos
    def _paint_clic_module(self, p: QPainter, name: str, m_in: int, m_out: int, w: float, H: float,
                           k_in: int, k_out: int, ex: int, ey: int) -> None:
        """Modulo CLW-02/8E..: 4 entradas (X) em cima, 4 saidas (Y) embaixo, LED de estado."""
        ink = "#2b2a25"
        relay = "8ET" not in name
        ac = name.endswith("-A") or name.endswith("24A")
        body = QRectF(-6, 12, w - 10, H - 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 38))
        p.drawRoundedRect(body.translated(4, 6), 12, 12)
        p.setPen(QPen(QColor("#bdb59c"), 1.5))
        p.setBrush(_vgrad(body, "#ebe5d3", "#d9d2bc"))
        p.drawRoundedRect(body, 12, 12)

        def sockets(xs: list[float], y: float) -> None:
            for cx in xs:
                hole = QRectF(cx - 11, y - 11, 22, 22)
                p.setPen(QPen(QColor("#b3ab92"), 1))
                p.setBrush(_vgrad(hole, "#c9c2ab", "#e4dec9"))
                p.drawRoundedRect(hole, 4, 4)
                g = QRadialGradient(QPointF(cx - 2.5, y - 2.5), 10)
                g.setColorAt(0, QColor("#5a6056"))
                g.setColorAt(1, QColor("#14170f"))
                p.setPen(QPen(QColor("#0d0f0b"), 1))
                p.setBrush(g)
                p.drawEllipse(QPointF(cx, y), 7.5, 7.5)
                p.setPen(QPen(QColor("#8a9183"), 1.4))
                p.drawLine(QPointF(cx - 4.5, y), QPointF(cx + 4.5, y))

        top = (["L", "N"] if ac else ["+", "-"]) + [f"X{ex + k + 1:X}" for k in range(m_in)]
        band = QRectF(body.left() + 10, 22, body.width() - 20, 66)
        p.setPen(QPen(QColor("#c8c0a8"), 1))
        p.setBrush(_vgrad(band, "#e2dcc8", "#d6cfb8"))
        p.drawRoundedRect(band, 8, 8)
        step = (band.width() - 8) / len(top)
        xs = [band.left() + 4 + step * (i + 0.5) for i in range(len(top))]
        for x, label in zip(xs, top):
            _text(p, QRectF(x - step / 2, 26, step, 16), label, 11, ink, True)
        sockets(xs, 60)
        _text(p, QRectF(band.left(), 98, band.width(), 16), f"INPUT {m_in} x {'AC' if ac else 'DC'}", 11, ink, True)

        face = QRectF(body.left() + 10, 124, body.width() - 20, 214)
        p.setPen(QPen(QColor("#c4bca4"), 1.2))
        p.setBrush(_vgrad(face, "#f4f0e3", "#e4dec9"))
        p.drawRoundedRect(face, 10, 10)
        _text(p, QRectF(face.left(), face.top() + 12, face.width(), 20), name, 13, ink, True)
        _text(p, QRectF(face.left(), face.top() + 32, face.width(), 16), "I/O EXPANSION", 10.5, "#6b6b65", True)
        _led(p, QRectF(face.center().x() - 8, face.top() + 56, 16, 8), self.connected, "#36d65c", "#b9b3a0")
        _text(p, QRectF(face.left(), face.top() + 66, face.width(), 14), "STATUS", 9.5, "#6b6b65", True)
        for r, (title, count, first, bits) in enumerate((("X", m_in, ex, self.inputs >> k_in),
                                                         ("Y", m_out, ey, self.outputs >> k_out))):
            y = face.top() + 104 + r * 52
            cell = (face.width() - 30) / max(count, 1)
            for k in range(count):
                cx = face.left() + 15 + cell * (k + 0.5)
                on = bool(bits >> k & 1)
                _text(p, QRectF(cx - cell / 2, y - 18, cell, 14), f"{title}{first + k + 1:X}", 10, ink, True)
                _led(p, QRectF(cx - 8, y, 16, 9), on, "#36d65c" if title == "X" else "#ff9a1f", "#b9b3a0")

        out = f"OUTPUT {m_out} x {'RELAY' if relay else 'TRANSISTOR'}"
        _text(p, QRectF(face.left(), 344, face.width(), 18), out, 11, ink, True)
        pins = [f"Y{ey + k + 1:X}" for k in range(m_out) for _ in ((0, 1) if relay else (0,))]
        if not relay:
            pins = ["V+", "0V"] + pins
        band = QRectF(body.left() + 10, 366, body.width() - 20, 52)
        p.setPen(QPen(QColor("#c8c0a8"), 1))
        p.setBrush(_vgrad(band, "#d6cfb8", "#e2dcc8"))
        p.drawRoundedRect(band, 8, 8)
        step = (band.width() - 8) / len(pins)
        xs = [band.left() + 4 + step * (i + 0.5) for i in range(len(pins))]
        sockets(xs, 384)
        i = 0
        while i < len(pins):
            j = i
            while j + 1 < len(pins) and pins[j + 1] == pins[i]:
                j += 1
            _text(p, QRectF(xs[i] - step / 2, 400, xs[j] - xs[i] + step, 16), pins[i], 10.5, ink, True)
            i = j + 1

    def _paint_cp1w(self, p: QPainter, name: str, m_in: int, m_out: int, w: float, H: float,
                    k_in: int, k_out: int, word_in: int, word_out: int) -> None:
        """Unidade de expansao CP1W: bornes, indicadores IN/OUT dos canais m e n, cabo ate o CPU."""
        p.setPen(QPen(QColor("#2a2c30"), 1))
        p.setBrush(_vgrad(QRectF(-34, 196, 44, 30), "#7d838b", "#555a61"))
        p.drawRect(QRectF(-34, 202, 44, 18))                   # cabo de conexao com a unidade anterior
        body = QRectF(10, 24, w - 26, 392)
        p.setPen(QPen(QColor("#0f1011"), 1.5))
        p.setBrush(_vgrad(body, "#3b3f45", "#26292d"))
        p.drawRoundedRect(body, 8, 8)
        if m_in:
            names = ["COM"] + [f"{k % 12:02d}" for k in range(m_in)]
            wires = {0: "#111827"}
            wires.update({1 + k: "#9aa1aa" for k in range(m_in)})
            self._terminal_block(p, QRectF(body.left() + 8, 30, body.width() - 16, 92), names, wires, 0)
            groups = [(f"CH {word_in + k0 // 12}", k0, min(12, m_in - k0)) for k0 in range(0, m_in, 12)]
            self._indicators(p, QRectF(body.left() + 8, 128, body.width() - 16, 38), "IN", groups,
                             self.inputs >> k_in)
        _text(p, QRectF(body.left(), 182, body.width(), 26), name, 17, "#f2f3f5", True)
        _text(p, QRectF(body.left(), 208, body.width(), 18), "EXPANSION I/O UNIT", 11, "#aeb4bc", True)
        _led(p, QRectF(body.center().x() - 8, 236, 16, 8), self.connected, "#36d65c")
        _text(p, QRectF(body.left(), 246, body.width(), 14), "POWER", 9.5, "#aeb4bc", True)
        if m_out:
            groups = [(f"CH {word_out + k0 // 8}", k0, min(8, m_out - k0)) for k0 in range(0, m_out, 8)]
            self._indicators(p, QRectF(body.left() + 8, 292, body.width() - 16, 38), "OUT", groups,
                             self.outputs >> k_out)
            names, bits = [], []
            for k0 in range(0, m_out, 4):
                names.append("COM")
                bits.append(None)
                for k in range(k0, min(k0 + 4, m_out)):
                    names.append(f"{k % 8:02d}")
                    bits.append(k)
            wires = {i: ("#f59e0b" if (self.outputs >> (k_out + k)) & 1 else "#9aa1aa") if k is not None
                     else "#111827" for i, k in enumerate(bits)}
            self._terminal_block(p, QRectF(body.left() + 8, 336, body.width() - 16, 76), names, wires, 440)

    # ================================================================ CLIC-02
    def _clic_io(self) -> tuple[bool, list[str], list[str], str, str]:
        """(alimentacao CC?, bornes de alimentacao, nomes das entradas, texto da alimentacao, texto das entradas)."""
        dc = not self.catalog.endswith("-A")
        power = ["+", "-"] if dc else ["L", "N"]
        analog = {8: 2, 12: 4}.get(self.n_in, 0) if dc else 0      # A1.. nas ultimas entradas (0~10 V)
        names = [f"I{k + 1:X}" for k in range(self.n_in - analog)] + [f"A{k + 1}" for k in range(analog)]
        volts = "DC 12V" if self.catalog.endswith("12D") else "DC 24V" if dc else "AC 100~240V"
        if analog:
            ain = "A1,A2" if analog == 2 else "A1~A4"
            text = f"INPUT {self.n_in} x DC({ain} 0~10V)"
        else:
            text = f"INPUT {self.n_in} x {'DC' if dc else 'AC'}"
        return dc, power, names, volts, text

    def _canvas(self) -> tuple[float, float]:
        if self.style_key == "hostlink":
            return self.SIZES["hostlink"]
        _dc, power, names, _v, _t = self._clic_io()
        return max(430.0, 96 + 31 * (len(power) + len(names) + 1)), 440.0

    def _paint_clic(self, p: QPainter) -> None:
        """WEG CLIC-02 como na foto do CLW-02/12HR-D: caixa bege, bornes escuros, faixa azul CLIC 02,
        LCD cinza, teclado azul em losango e bornes de saida embaixo."""
        relay = "T" not in self.catalog.split("/")[-1][:4] if self.catalog else True
        _dc, power, names, volts, in_text = self._clic_io()
        W, H = self._canvas()
        ink = "#2b2a25"
        body = QRectF(12, 12, W - 24, H - 24)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 38))
        p.drawRoundedRect(body.translated(4, 6), 14, 14)
        p.setPen(QPen(QColor("#bdb59c"), 1.5))
        p.setBrush(_vgrad(body, "#ebe5d3", "#d9d2bc"))
        p.drawRoundedRect(body, 14, 14)

        def socket_row(cx_list: list[float], y: float) -> None:
            for cx in cx_list:
                hole = QRectF(cx - 12, y - 12, 24, 24)
                p.setPen(QPen(QColor("#b3ab92"), 1))
                p.setBrush(_vgrad(hole, "#c9c2ab", "#e4dec9"))
                p.drawRoundedRect(hole, 4, 4)
                g = QRadialGradient(QPointF(cx - 2.5, y - 2.5), 11)
                g.setColorAt(0, QColor("#5a6056"))
                g.setColorAt(1, QColor("#14170f"))
                p.setPen(QPen(QColor("#0d0f0b"), 1))
                p.setBrush(g)
                p.drawEllipse(QPointF(cx, y), 8.5, 8.5)
                p.setPen(QPen(QColor("#8a9183"), 1.6))
                p.drawLine(QPointF(cx - 5, y), QPointF(cx + 5, y))

        # ---- bornes de cima: alimentacao, um espaco, entradas
        slot = (W - 96) / (len(power) + len(names) + 1)
        band = QRectF(26, 22, W - 52, 66)
        p.setPen(QPen(QColor("#c8c0a8"), 1))
        p.setBrush(_vgrad(band, "#e2dcc8", "#d6cfb8"))
        p.drawRoundedRect(band, 8, 8)
        xs = [48 + slot * (i + 0.5) for i in range(len(power))]
        xs += [48 + slot * (len(power) + 1 + i + 0.5) for i in range(len(names))]
        for x, name in zip(xs, power + names):
            _text(p, QRectF(x - slot / 2, 26, slot, 16), name, 12, ink, True)
        socket_row(xs, 60)
        p.setPen(QPen(QColor("#c2baa1"), 1.2))
        p.drawLine(QPointF(26, 96), QPointF(W - 26, 96))
        _text(p, QRectF(xs[0] - 10, 100, slot * 3, 16), volts, 11.5, ink, True, Qt.AlignLeft | Qt.AlignVCenter)
        _text(p, QRectF(xs[len(power)] - 10, 100, W - xs[len(power)], 16), in_text, 11.5, ink, True,
              Qt.AlignLeft | Qt.AlignVCenter)

        # ---- painel frontal elevado
        face = QRectF(26, 124, W - 52, 214)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 30))
        p.drawRoundedRect(face.translated(2, 4), 12, 12)
        p.setPen(QPen(QColor("#c4bca4"), 1.2))
        p.setBrush(_vgrad(face, "#f4f0e3", "#e4dec9"))
        p.drawRoundedRect(face, 12, 12)

        lcd_w = min(face.width() * 0.52, 300)
        # faixa azul com a marca e o nome CLIC 02
        banner = QRectF(face.left() + 12, face.top() + 10, lcd_w, 30)
        p.setPen(QPen(QColor("#174a8c"), 1))
        p.setBrush(_vgrad(banner, "#3478c8", "#1d559f"))
        p.drawRoundedRect(banner, 4, 4)
        tag = QRectF(banner.left() + 5, banner.top() + 4, 46, 22)
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(tag, 3, 3)
        _text(p, tag, "WEG", 15, "#1d4f9a", True)
        f = _font(23, True)
        f.setItalic(True)
        p.setFont(f)
        name_rect = QRectF(tag.right() + 10, banner.top(), banner.width() - 70, banner.height())
        p.setPen(QColor("#0d2c57"))
        p.drawText(name_rect.translated(1.2, 1.2), Qt.AlignLeft | Qt.AlignVCenter, "CLIC")
        p.setPen(QColor("#ffd21f"))
        p.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, "CLIC")
        clic_w = p.fontMetrics().horizontalAdvance("CLIC")
        _text(p, QRectF(name_rect.left() + clic_w + 3, banner.top() + 2, 30, 14), "02", 12, "#ffffff", True,
              Qt.AlignLeft | Qt.AlignVCenter)

        # display LCD (cinza; com luz de fundo quando o CLP esta conectado)
        lcd = QRectF(face.left() + 12, banner.bottom() + 10, lcd_w, 112)
        p.setPen(QPen(QColor("#6e7064"), 1.5))
        p.setBrush(QColor("#a9ac9d"))
        p.drawRoundedRect(lcd, 3, 3)
        glass = lcd.adjusted(6, 6, -6, -6)
        lit = self.connected
        p.setPen(Qt.NoPen)
        p.setBrush(_vgrad(glass, "#d9e6ad", "#bfd087") if lit else _vgrad(glass, "#c8cbbb", "#b3b7a5"))
        p.drawRect(glass)
        lcd_ink = "#1e2a10" if lit else "#3d4236"
        lcd_bg = "#d3e1a2" if lit else "#c1c4b3"
        lh = glass.height() / 4
        cw = glass.width() / 16
        p.setFont(_font(lh * 0.66, True, True))
        now = time.localtime()
        mode = (self.mode or "STOP")[:4]
        screen = [("I", [f"{k + 1:X}" for k in range(self.n_in)], self.inputs),
                  ("Z", ["1", "2", "3", "4"], 0),
                  ("Q", [f"{k + 1:X}" for k in range(self.n_out)], self.outputs)]
        if lit or self.mode:                               # desligado: display vazio, como na foto
            for r, (title, chars, bits) in enumerate(screen):
                y = glass.top() + r * lh
                for c, ch in enumerate([title, "."] + chars):
                    cell = QRectF(glass.left() + 3 + c * cw, y + 2, cw * 0.94, lh - 4)
                    on = c >= 2 and bits >> (c - 2) & 1
                    if on:
                        p.fillRect(cell, QColor(lcd_ink))
                    p.setPen(QColor(lcd_bg if on else lcd_ink))
                    p.drawText(cell, Qt.AlignCenter, ch)
            p.setPen(QColor(lcd_ink))
            p.drawText(QRectF(glass.left() + 3, glass.top() + 3 * lh, glass.width() - 6, lh), Qt.AlignVCenter,
                       f"{mode:<5}{WEEKDAYS[now.tm_wday]} {now.tm_hour:02d}:{now.tm_min:02d}")

        # modelo embaixo do display
        p.setFont(_font(14, True))
        model = self.catalog or "CLW-02"
        p.setPen(QColor(ink))
        p.drawText(QRectF(lcd.left() + 2, lcd.bottom() + 8, lcd_w, 20), Qt.AlignLeft | Qt.AlignVCenter, model)
        mw = p.fontMetrics().horizontalAdvance(model)
        f = _font(13, True)
        f.setItalic(True)
        p.setFont(f)
        p.setPen(QColor("#e8862a"))
        p.drawText(QRectF(lcd.left() + mw + 8, lcd.bottom() + 8, 40, 20), Qt.AlignLeft | Qt.AlignVCenter, "3rd")

        # teclado azul em losango: setas no meio, DEL/SEL/ESC/OK nas diagonais
        pad_left = lcd.right() + 12
        pad_w = face.right() - 12 - pad_left
        c = QPointF(pad_left + pad_w / 2, lcd.center().y() - 10)
        d = min(26.0, pad_w / 5.6)

        def blue_key(center: QPointF, w: float, h: float, angle: float, label: str = "",
                     arrow: tuple | None = None) -> None:
            p.save()
            p.translate(center)
            p.rotate(angle)
            r = QRectF(-w / 2, -h / 2, w, h)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 50))
            p.drawRoundedRect(r.translated(1.2, 2), 5, 5)
            p.setPen(QPen(QColor("#1d4f8f"), 1))
            p.setBrush(_vgrad(r, "#6aa6e6", "#2d68b4"))
            p.drawRoundedRect(r, 5, 5)
            p.rotate(-angle)
            if label:
                _text(p, QRectF(-w / 2, -h / 2, w, h), label, d * 0.4, "#ffffff", True)
            if arrow:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ffffff"))
                p.drawPolygon(QPolygonF([QPointF(a * d / 26, b * d / 26) for a, b in arrow]))
            p.restore()

        k = d * 0.92
        for (sx, sy), angle, label in (((-1, -1), 45, "DEL"), ((1, -1), -45, "SEL"),
                                       ((-1, 1), -45, "ESC"), ((1, 1), 45, "OK")):
            blue_key(c + QPointF(sx * d * 1.6, sy * d * 1.6), k * 1.7, k, angle, label)
        for (dx, dy), arrow in (((0, -1), ((0, -9), (-8, 2), (-3, 2), (-3, 8), (3, 8), (3, 2), (8, 2))),
                                ((-1, 0), ((-9, 0), (2, -8), (2, -3), (8, -3), (8, 3), (2, 3), (2, 8))),
                                ((1, 0), ((9, 0), (-2, -8), (-2, -3), (-8, -3), (-8, 3), (-2, 3), (-2, 8))),
                                ((0, 1), ((0, 9), (-8, -2), (-3, -2), (-3, -8), (3, -8), (3, -2), (8, -2)))):
            blue_key(c + QPointF(dx * d, dy * d), k, k, 45, arrow=arrow)

        # tampa da porta de expansao/programacao
        cover = QRectF(pad_left + 4, lcd.bottom() + 6, pad_w - 8, face.bottom() - lcd.bottom() - 18)
        p.setPen(QPen(QColor("#c4bca4"), 1))
        p.setBrush(_vgrad(cover, "#e9e3d0", "#dcd5bf"))
        p.drawRoundedRect(cover, 4, 4)
        p.setPen(QPen(QColor("#bdb59c"), 1))
        p.drawLine(QPointF(cover.left() + 8, cover.center().y()), QPointF(cover.right() - 8, cover.center().y()))

        # ---- saidas: texto e bornes embaixo (rele em pares)
        out_text = f"OUTPUT {self.n_out} x RELAY/8A" if relay else f"OUTPUT {self.n_out} x TRANSISTOR/0.5A"
        _text(p, QRectF(36, 344, W - 72, 18), out_text, 12, ink, True, Qt.AlignLeft | Qt.AlignVCenter)
        if relay:
            pins = [(f"Q{k + 1}", k) for k in range(self.n_out) for _ in (0, 1)]
        else:
            pins = [("V+", None), ("0V", None)] + [(f"Q{k + 1}", k) for k in range(self.n_out)]
        band = QRectF(26, 366, W - 52, 52)
        p.setPen(QPen(QColor("#c8c0a8"), 1))
        p.setBrush(_vgrad(band, "#d6cfb8", "#e2dcc8"))
        p.drawRoundedRect(band, 8, 8)
        step = (W - 96) / len(pins)
        xs = [48 + step * (i + 0.5) for i in range(len(pins))]
        socket_row(xs, 384)
        groups: list[list] = []
        for i, (name, _k) in enumerate(pins):
            if groups and groups[-1][0] == name:
                groups[-1][2] = i
            else:
                groups.append([name, i, i])
        for name, a, b in groups:
            x0, x1 = xs[a] - step / 2, xs[b] + step / 2
            _text(p, QRectF(x0, 400, x1 - x0, 16), name, 12, ink, True)

    # ================================================================ CP1E
    def _terminal_block(self, p: QPainter, block: QRectF, names: list[str], wires: dict[int, str],
                        wire_to: float) -> None:
        """Bornes em duas fileiras desencontradas (como no CP1E); wires: indice -> cor do fio."""
        p.setPen(QPen(QColor("#1a1b1d"), 1))
        p.setBrush(_vgrad(block, "#5c6168", "#454950"))
        p.drawRoundedRect(block, 4, 4)
        cols = (len(names) + 1) // 2
        step = (block.width() - 20) / (cols + 0.5)
        up_y, low_y = block.top() + 32, block.top() + 70

        def pos(i: int) -> QPointF:
            col = i // 2
            return QPointF(block.left() + 10 + step * (col + (0.5 if i % 2 else 0.0)) + step / 2,
                           up_y if i % 2 else low_y)

        for i, color in wires.items():
            c = pos(i)
            _wire(p, c.x(), c.y(), wire_to, color, 4)
        for i, name in enumerate(names):
            c = pos(i)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#232427"))
            p.drawRoundedRect(QRectF(c.x() - 12, c.y() - 12, 24, 24), 2, 2)
            _screw(p, c.x(), c.y(), 9)
            _text(p, QRectF(c.x() - step / 2, c.y() - 27, step, 13), name, 10, "#e8eaed", True)

    def _indicators(self, p: QPainter, rect: QRectF, title: str, groups: list[tuple[str, int, int]],
                    bits: int) -> None:
        """Linha de indicadores: grupos (canal, primeiro bit, quantidade) com LEDs numerados."""
        p.setPen(QPen(QColor("#121315"), 1))
        p.setBrush(QColor("#1c1e21"))
        p.drawRoundedRect(rect, 3, 3)
        _text(p, QRectF(rect.left() + 6, rect.top(), 40, rect.height()), title, 13, "#f2f3f5", True,
              Qt.AlignLeft | Qt.AlignVCenter)
        cell = min(26.0, (rect.width() - 56) / max(1, sum(n for _c, _k, n in groups) + len(groups) - 1))
        x = rect.left() + 50
        for channel, k0, n in groups:
            _text(p, QRectF(x, rect.top() + 1, cell * n, 11), channel, 9, "#9da3ab", True)
            for k in range(n):
                cx = x + k * cell
                _text(p, QRectF(cx, rect.top() + 11, cell, 11), f"{k:02d}", 9, "#d5d8dc")
                _led(p, QRectF(cx + cell * 0.22, rect.top() + 25, cell * 0.56, 7), bool(bits >> (k0 + k) & 1),
                     "#ff9a1f")
            x += cell * (n + 1)

    def _paint_cp1e(self, p: QPainter) -> None:
        body = QRectF(40, 24, 880, 392)
        p.setPen(QPen(QColor("#0f1011"), 1.5))
        p.setBrush(_vgrad(body, "#3b3f45", "#26292d"))
        p.drawRoundedRect(body, 8, 8)

        # ---- bornes de entrada (em cima)
        in_names = ["L1", "L2/N", "COM"] + [f"{k % 12:02d}" for k in range(self.n_in)]
        wires = {0: "#8b5a2b", 1: "#1d4ed8", 2: "#111827"}
        wires.update({3 + k: "#9aa1aa" for k in range(self.n_in)})
        self._terminal_block(p, QRectF(52, 30, 856, 92), in_names, wires, 0)
        in_groups = [(f"CH {k0 // 12}", k0, min(12, self.n_in - k0)) for k0 in range(0, self.n_in, 12)]
        self._indicators(p, QRectF(330, 128, 578, 38), "IN", in_groups, self.inputs)

        # ---- centro: tampa USB, LEDs de operacao, nome, RS-232C, slot de opcao
        cover = QRectF(56, 132, 150, 160)
        p.setPen(QPen(QColor("#15161a"), 1))
        p.setBrush(_vgrad(cover, "#474b52", "#33363b"))
        p.drawRoundedRect(cover, 5, 5)
        p.setPen(QPen(QColor("#5d626a"), 1))
        p.drawLine(QPointF(cover.left() + 8, cover.top() + 10), QPointF(cover.right() - 8, cover.top() + 10))
        usb = QRectF(cover.left() + 52, cover.top() + 50, 46, 40)
        p.setPen(QPen(QColor("#9aa0a8"), 2))
        p.setBrush(QColor("#1a1b1e"))
        p.drawRoundedRect(usb, 6, 6)
        p.setBrush(QColor("#c6cbd1"))
        p.setPen(Qt.NoPen)
        p.drawRect(QRectF(usb.left() + 12, usb.top() + 12, 22, 16))
        _text(p, QRectF(cover.left(), usb.bottom() + 6, cover.width(), 16), "PERIPHERAL", 11, "#d5d8dc", True)
        _text(p, QRectF(cover.left(), usb.bottom() + 22, cover.width(), 16), "USB", 11, "#9da3ab")

        running = self.mode in ("RUN", "MONITOR")
        leds = [("POWER", self.connected, "#36d65c"), ("RUN", running, "#36d65c"),
                ("ERR/ALM", self.error, "#ff3b30"), ("INH", False, "#ffb020"),
                ("PRPHL", self.connected and running, "#ffb020"), ("BKUP", False, "#ffb020")]
        for i, (name, on, color) in enumerate(leds):
            y = 176 + i * 22
            _led(p, QRectF(222, y + 4, 16, 8), on, color)
            _text(p, QRectF(244, y, 90, 16), name, 11, "#e8eaed", True, Qt.AlignLeft | Qt.AlignVCenter)
        _text(p, QRectF(222, 138, 110, 26), "CP1E", 24, "#f2f3f5", True, Qt.AlignLeft | Qt.AlignVCenter)

        _text(p, QRectF(350, 176, 220, 18), "CPU Unit", 12, "#aeb4bc", False, Qt.AlignLeft | Qt.AlignVCenter)
        _text(p, QRectF(350, 196, 240, 22), self.catalog or "CP1E", 17, "#f2f3f5", True,
              Qt.AlignLeft | Qt.AlignVCenter)
        _text(p, QRectF(350, 222, 240, 18), "100-240 VAC  50/60 Hz" if self.catalog.endswith("-A") else "24 VDC",
              11, "#aeb4bc", False, Qt.AlignLeft | Qt.AlignVCenter)

        model = self.catalog.split("-")[1] if self.catalog.count("-") >= 2 else ""
        has_serial = not model or model.startswith("N") or "S" in model[3:]      # E..S e N tem RS-232C
        if has_serial:
            _text(p, QRectF(610, 176, 120, 16), "RS-232C", 11, "#e8eaed", True)
            shell = QPolygonF([QPointF(622, 196), QPointF(718, 196), QPointF(710, 236), QPointF(630, 236)])
            p.setPen(QPen(QColor("#5a5f66"), 1))
            p.setBrush(_vgrad(QRectF(620, 196, 100, 40), "#dfe3e8", "#9ca3ab"))
            p.drawPolygon(shell)
            inner = QPolygonF([QPointF(630, 202), QPointF(710, 202), QPointF(704, 230), QPointF(636, 230)])
            p.setBrush(QColor("#2a2c30"))
            p.drawPolygon(inner)
            p.setBrush(QColor("#d9b45a"))
            p.setPen(Qt.NoPen)
            for j in range(5):
                p.drawEllipse(QPointF(642 + j * 14, 210), 2.6, 2.6)
            for j in range(4):
                p.drawEllipse(QPointF(649 + j * 14, 222), 2.6, 2.6)
            for sx in (608, 732):
                _screw(p, sx, 216, 6)
        if self.catalog.startswith(("CP1E-N30", "CP1E-N40", "CP1E-N60", "CP1E-NA20")):
            slot = QRectF(756, 172, 146, 112)
            p.setPen(QPen(QColor("#15161a"), 1))
            p.setBrush(_vgrad(slot, "#43474e", "#30333a"))
            p.drawRoundedRect(slot, 4, 4)
            _text(p, slot, "OPTION BOARD", 11, "#9da3ab", True)

        # ---- indicadores e bornes de saida (embaixo)
        out_groups = [(f"CH {100 + k0 // 8}", k0, min(8, self.n_out - k0)) for k0 in range(0, self.n_out, 8)]
        self._indicators(p, QRectF(330, 292, 578, 38), "OUT", out_groups, self.outputs)
        out_names, out_bits = ["+", "-"], [None, None]
        for k0 in range(0, self.n_out, 4):
            out_names.append("COM")
            out_bits.append(None)
            for k in range(k0, min(k0 + 4, self.n_out)):
                out_names.append(f"{k % 8:02d}")
                out_bits.append(k)
        wires = {i: ("#f59e0b" if self.outputs >> k & 1 else "#9aa1aa") if k is not None else "#111827"
                 for i, k in enumerate(out_bits) if i >= 2}
        self._terminal_block(p, QRectF(52, 336, 856, 76), out_names, wires, 440)
