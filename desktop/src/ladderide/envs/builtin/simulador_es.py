"""Simulador de E/S: botoeiras, lampadas e BCD (como o I/O Simulator e o BCD Simulator do LogixPro).

Diferente dos outros ambientes, a quantidade de pontos vem do controlador do
projeto (configure): uma botoeira por entrada e uma lampada por saida, em
colunas de 8 (I0, I1, I2..., Q0, Q1), ate 32 entradas (ex.: 1747-L40, 24). Cada botoeira troca de tipo ao clicar na
etiqueta ao lado dela: pulsador NA, pulsador NF, chave NA ou chave NF.

BCD: a chave thumbwheel de 4 digitos escreve em N0 o valor em BCD (cada digito
em 4 bits, como os bits I:5/00-15 do LogixPro); converta com FRD. O display le
N1 em BCD; escreva nele com TOD. Exige ao menos 2 registradores N.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from ...core import isa
from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..registry import register

TYPES = ("pb_no", "pb_nc", "sw_no", "sw_nc")        # ordem do clique na etiqueta
TYPE_TAG = {"pb_no": "P NA", "pb_nc": "P NF", "sw_no": "C NA", "sw_nc": "C NF"}
TYPE_TEXT = {"pb_no": "Pulsador NA", "pb_nc": "Pulsador NF", "sw_no": "Chave NA (com trava)",
             "sw_nc": "Chave NF (com trava)"}
DEFAULT_TYPES = ("pb_no", "pb_no", "pb_no", "pb_nc")   # as demais comecam como chave NA

TITLE_H = 24
TOP = 34                       # topo das colunas (abaixo do titulo)
ROWS_H = 300                   # altura da area de pontos
SLOT = 8                       # pontos por coluna (um byte: I0, I1, Q0, Q1)
IN_W, OUT_W, BCD_W, GAP = 112, 84, 168, 6
BCD_IN, BCD_OUT = 0, 1         # N0 (thumbwheel) e N1 (display)

PANEL = QColor("#fdfbe6")
FRAME = QColor("#4c1d95")
TITLE = QColor("#1d4ed8")
BOX = QColor("#111827")
WIRE_ON = QColor("#16a34a")
DISPLAY = QColor("#7f1d1d")
SEGMENT = QColor("#facc15")


def _address(area: str, k: int) -> str:
    return f"{area}{k // 8}.{k % 8}"


def bcd_encode(value: int) -> int:
    """0..9999 -> BCD (ex.: 1234 -> 0x1234)."""
    word = 0
    for shift in range(0, 16, 4):
        word |= (value % 10) << shift
        value //= 10
    return word


def bcd_digits(word: int) -> list[int]:
    """Os 4 nibbles do word, do milhar para a unidade (nibble > 9 nao e BCD valido)."""
    return [(word >> shift) & 0xF for shift in (12, 8, 4, 0)]


@register
class IOSimulatorEnvironment(Environment):
    id = "simulador_es"
    name = "Simulador de E/S (botoeiras, lâmpadas e BCD)"
    description = ("Uma botoeira por entrada e uma lâmpada por saída do controlador do projeto (troque o "
                   "controlador e a quantidade muda). Clique na etiqueta ao lado da botoeira para trocar o tipo: "
                   "pulsador NA, pulsador NF, chave NA ou chave NF. A thumbwheel escreve N0 em BCD (converta "
                   "com FRD) e o display mostra N1 em BCD (escreva com TOD).")
    example = "ambientes/simulador_es.ladproj"

    def __init__(self) -> None:
        self.n_in, self.n_out, self.n_words = 8, 8, 32
        self.types = [DEFAULT_TYPES[k] if k < len(DEFAULT_TYPES) else "sw_no"
                      for k in range(isa.IDE_MAX_INPUTS)]
        self.digits = [0, 0, 0, 0]               # thumbwheel, do milhar para a unidade
        self.display_word = 0
        self._build()
        super().__init__()

    # ------------------------------------------------------- configuracao
    @property
    def has_bcd(self) -> bool:
        return self.n_words > BCD_OUT

    def configure(self, n_inputs: int, n_outputs: int, n_words: int) -> bool:
        io = (max(1, min(isa.IDE_MAX_INPUTS, n_inputs)), max(1, min(isa.MAX_OUTPUTS, n_outputs)), max(0, n_words))
        if io == (self.n_in, self.n_out, self.n_words):
            return False
        self.n_in, self.n_out, self.n_words = io
        self._build()
        self.out = {p.key: self.out.get(p.key, False) for p in self.outputs}
        keys = {p.key for p in self.inputs}
        self.operator = {k: v for k, v in self.operator.items() if k in keys}
        return True

    def _build(self) -> None:
        self.inputs = [self._input(k) for k in range(self.n_in)]
        self.outputs = [IOPoint(f"Q{k}", _address("Q", k), f"Lampada_{k:02d}", f"Lâmpada {k:02d}")
                        for k in range(self.n_out)]
        self.in_cols = (self.n_in + SLOT - 1) // SLOT
        self.out_cols = (self.n_out + SLOT - 1) // SLOT
        self.io_w = self.in_cols * IN_W + self.out_cols * OUT_W
        width = 8 + self.io_w + (GAP + 2 * BCD_W if self.has_bcd else 0) + 8
        self.size = (width, TOP + ROWS_H + 8)

    def _input(self, k: int) -> IOPoint:
        t = self.types[k]
        return IOPoint(f"I{k}", _address("I", k), f"Botoeira_{k:02d}", TYPE_TEXT[t],
                       BUTTON if t.startswith("pb") else SWITCH, normally_closed=t.endswith("nc"))

    def set_type(self, k: int, kind: str) -> None:
        self.types[k] = kind
        self.operator[f"I{k}"] = False
        self.inputs = [self._input(j) for j in range(self.n_in)]

    # ------------------------------------------------------------- fisica
    def reset(self) -> None:
        self.display_word = 0

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        pass

    def sensors(self) -> dict[str, bool]:
        return {}

    @property
    def thumbwheel(self) -> int:
        d = self.digits
        return d[0] * 1000 + d[1] * 100 + d[2] * 10 + d[3]

    def input_words(self) -> dict[int, int]:
        return {BCD_IN: bcd_encode(self.thumbwheel)} if self.has_bcd else {}

    def advance_words(self, n: list[int]) -> None:
        if self.has_bcd and len(n) > BCD_OUT:
            self.display_word = n[BCD_OUT] & 0xFFFF

    def stats(self) -> list[str]:
        if not self.has_bcd:
            return ["BCD desligado: o projeto precisa de ao menos 2 registradores N (N0 e N1)."]
        return [f"Thumbwheel {self.thumbwheel:04d} -> N0 = 0x{bcd_encode(self.thumbwheel):04X} (BCD)",
                f"Display <- N1 = 0x{self.display_word:04X}"]

    # ----------------------------------------------------------- operador
    def press(self, key: str, down: bool) -> None:
        if key.startswith("T"):                  # etiqueta: proximo tipo
            if down:
                k = int(key[1:])
                self.set_type(k, TYPES[(TYPES.index(self.types[k]) + 1) % len(TYPES)])
        elif key.startswith("D"):                # thumbwheel: D<digito><+|->
            if down:
                i, step = int(key[1]), 1 if key[2] == "+" else -1
                self.digits[i] = (self.digits[i] + step) % 10
        else:
            super().press(key, down)

    def controls(self) -> dict[str, tuple[float, float, float, float]]:
        areas = {}
        for k in range(self.n_in):
            x, y = self._in_cell(k)
            areas[f"T{k}"] = (x + 4, y + 9, 30, 20)
            areas[f"I{k}"] = (x + 36, y + 2, 40, 34)
        if self.has_bcd:
            for i in range(4):
                r = self._digit_rect(i)
                areas[f"D{i}+"] = (r.x(), r.y() - 12, r.width(), 12)
                areas[f"D{i}-"] = (r.x(), r.bottom(), r.width(), 12)
        return areas

    # ---------------------------------------------------------- geometria
    @staticmethod
    def _row_h() -> float:
        return ROWS_H / SLOT

    def _in_cell(self, k: int) -> tuple[float, float]:
        return 8 + (k // SLOT) * IN_W, TOP + (k % SLOT) * self._row_h()

    def _out_cell(self, k: int) -> tuple[float, float]:
        return 8 + self.in_cols * IN_W + (k // SLOT) * OUT_W, TOP + (k % SLOT) * self._row_h()

    def _bcd_x(self, which: int) -> float:
        return 8 + self.io_w + GAP + which * BCD_W

    def _digit_rect(self, i: int, which: int = 0) -> QRectF:
        x = self._bcd_x(which) + 12 + i * 26
        return QRectF(x, TOP + 22, 22, 28)

    # ------------------------------------------------------------- desenho
    def paint(self, p: QPainter) -> None:
        w, h = self.size
        p.fillRect(QRectF(0, 0, w, h), FRAME)
        self._title(p, QRectF(4, 4, self.io_w + 8, TITLE_H - 4),          # quantidades do controlador
                    f"Simulador de E/S  {self.n_in}E / {self.n_out}S")
        values = self._logical_inputs()
        for k in range(self.n_in):
            if k % SLOT == 0:
                self._column(p, *self._in_cell(k), IN_W, f"I{k // 8}")
            self._input_row(p, k, values.get(f"I{k}", False))
        for k in range(self.n_out):
            if k % SLOT == 0:
                self._column(p, *self._out_cell(k), OUT_W, f"Q{k // 8}")
            self._output_row(p, k)
        if self.has_bcd:
            x = self._bcd_x(0)
            self._title(p, QRectF(x, 4, 2 * BCD_W - 4, TITLE_H - 4), "Simulador BCD")
            self._bcd_panel(p, 0, bcd_encode(self.thumbwheel), "N0 (entrada)")
            self._bcd_panel(p, 1, self.display_word, "N1 (display)")

    def _logical_inputs(self) -> dict[str, bool]:
        """Nivel lido pelo CLP (ja com NA/NF), para acender a etiqueta do endereco."""
        out = {}
        for pt in self.inputs:
            actuated = self.is_pressed(pt.key)
            out[pt.key] = (not actuated) if pt.normally_closed else actuated
        return out

    @staticmethod
    def _title(p: QPainter, rect: QRectF, text: str) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(TITLE)
        p.drawRect(rect)
        draw.text(p, rect.center().x(), rect.center().y(), text, 9, True, draw.WHITE, Qt.AlignCenter)

    @staticmethod
    def _column(p: QPainter, x: float, y: float, width: float, title: str) -> None:
        r = QRectF(x + 2, y - 8, width - 4, ROWS_H + 10)
        p.setPen(Qt.NoPen)
        p.setBrush(PANEL)
        p.drawRect(r)
        tag = QRectF(r.right() - 30, r.top() + 1, 26, 12)
        p.setBrush(BOX)
        p.drawRect(tag)
        draw.text(p, tag.center().x(), tag.center().y(), title, 7, True, draw.WHITE, Qt.AlignCenter)

    @staticmethod
    def _address_box(p: QPainter, x: float, y: float, text: str, on: bool) -> None:
        r = QRectF(x, y - 8, 30, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(WIRE_ON if on else BOX)
        p.drawRect(r)
        draw.text(p, r.center().x(), r.center().y(), text, 7, True, draw.WHITE, Qt.AlignCenter)

    def _input_row(self, p: QPainter, k: int, value: bool) -> None:
        x, y = self._in_cell(k)
        cy = y + self._row_h() / 2 + 2
        kind = self.types[k]
        tag = QRectF(x + 4, cy - 9, 30, 18)               # etiqueta do tipo (clique troca)
        p.setPen(QPen(draw.MUTED, 1))
        p.setBrush(QColor("#ede9fe") if kind.startswith("pb") else QColor("#e0f2fe"))
        p.drawRoundedRect(tag, 3, 3)
        draw.text(p, tag.center().x(), tag.center().y(), TYPE_TAG[kind], 6, True, draw.INK, Qt.AlignCenter)
        pressed = self.is_pressed(f"I{k}")
        closed = pressed != kind.endswith("nc")             # contato fisico fechado (conduzindo)
        self._contact(p, QRectF(x + 38, cy - 14, 36, 24), kind, pressed, closed)
        self._address_box(p, x + 78, cy, _address("I", k), value)

    @staticmethod
    def _contact(p: QPainter, r: QRectF, kind: str, pressed: bool, closed: bool) -> None:
        left, right = QPointF(r.left() + 4, r.bottom() - 4), QPointF(r.right() - 4, r.bottom() - 4)
        color = WIRE_ON if closed else draw.INK
        p.setPen(QPen(color, 1.6))
        p.setBrush(PANEL)
        p.drawLine(QPointF(r.left() - 2, left.y()), QPointF(left.x() - 3, left.y()))
        p.drawLine(QPointF(right.x() + 3, right.y()), QPointF(r.right() + 2, right.y()))
        p.drawEllipse(left, 3, 3)
        p.drawEllipse(right, 3, 3)
        if kind.startswith("pb"):                           # pulsador: barra com haste
            if kind == "pb_no":                             # NA: barra acima, encosta ao apertar
                bar_y = left.y() - 3 if pressed else left.y() - 10
            else:                                           # NF: barra por baixo, afasta ao apertar
                bar_y = left.y() + 11 if pressed else left.y() + 5
            p.drawLine(QPointF(left.x() - 2, bar_y), QPointF(right.x() + 2, bar_y))
            mid = (left.x() + right.x()) / 2
            p.drawLine(QPointF(mid, bar_y), QPointF(mid, r.top()))
            p.drawLine(QPointF(mid - 5, r.top()), QPointF(mid + 5, r.top()))
        else:                                               # chave: alavanca articulada na esquerda
            end = QPointF(right.x(), right.y() - 3) if closed else QPointF(right.x() - 3, r.top() + 2)
            p.drawLine(QPointF(left.x() + 2, left.y() - 2), end)
        p.setBrush(Qt.NoBrush)

    def _output_row(self, p: QPainter, k: int) -> None:
        x, y = self._out_cell(k)
        cy = y + self._row_h() / 2 + 2
        on = self.out.get(f"Q{k}", False)
        draw.lamp(p, QPointF(x + 22, cy), 9, on, SEGMENT)
        self._address_box(p, x + 46, cy, _address("Q", k), on)

    def _bcd_panel(self, p: QPainter, which: int, word: int, title: str) -> None:
        x0 = self._bcd_x(which)
        panel = QRectF(x0, TOP - 8, BCD_W - 4, ROWS_H + 10)
        p.setPen(Qt.NoPen)
        p.setBrush(PANEL)
        p.drawRect(panel)
        draw.text(p, x0 + 6, TOP + 2, title, 7, True, draw.MUTED)
        digits = bcd_digits(word)
        if which == 0:
            for i, d in enumerate(digits):
                r = self._digit_rect(i)
                p.setPen(QPen(draw.MUTED, 1))
                p.setBrush(draw.WHITE)
                p.drawRect(r)
                draw.text(p, r.center().x(), r.center().y(), str(d), 13, True, draw.INK, Qt.AlignCenter)
                for up, yy in ((True, r.top() - 6), (False, r.bottom() + 6)):
                    draw.arrow(p, QPointF(r.center().x(), yy), 8, up, False)
        else:
            box = QRectF(x0 + 8, TOP + 18, 4 * 26 + 4, 36)
            p.setPen(QPen(QColor("#450a0a"), 1.5))
            p.setBrush(DISPLAY)
            p.drawRect(box)
            for i, d in enumerate(digits):
                r = self._digit_rect(i, 1)
                draw.text(p, r.center().x(), r.center().y(), str(d) if d <= 9 else "-", 17, True,
                          SEGMENT, Qt.AlignCenter)
        bits_top, bit_h = TOP + 66, (ROWS_H - 66) / 16
        label_x = panel.right() - 34
        for b in range(16):
            on = bool(word >> b & 1)
            digit = 3 - b // 4                              # unidade = bits 0-3
            r = self._digit_rect(digit, which)
            wx = r.left() + 4 + (b % 4) * 4.5
            yy = bits_top + b * bit_h + bit_h / 2
            p.setPen(QPen(WIRE_ON if on else draw.MUTED, 1.4 if on else 1))
            p.drawLine(QPointF(wx, r.bottom() + 14), QPointF(wx, yy))
            p.drawLine(QPointF(wx, yy), QPointF(label_x, yy))
            self._address_box(p, label_x, yy, f"{b:02d}", on)
