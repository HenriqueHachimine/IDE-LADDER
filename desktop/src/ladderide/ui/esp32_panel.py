"""Simulador da placa: ESP32 Relay (desenhada a partir de board_config.h), Arduino UNO ou Mega.

A placa e "ligada" no dispositivo virtual, que executa o mesmo codigo C do
firmware (plc_core + ladder_vm) no PC e conversa com a IDE pelo protocolo
LDP, como a placa real faz pela USB. O desenho mostra o que o firmware
comanda: reles, niveis eletricos nos registradores 74HC595/74HC165 (com a
polaridade e a permutacao configuradas), entradas optoacopladas e os GPIOs
usados. Conectado a uma placa real, o mesmo painel mostra o estado lido dela.

A placa simulada pode ser trocada (comm/board_profiles.py): a ESP32 com 1 a 8
reles, ou um Arduino UNO / Mega com um modulo de reles. O dispositivo virtual e
iniciado com as entradas e saidas da placa escolhida.
"""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSpinBox, QSplitter, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..comm.board import BoardConfig, load_board_config
from ..comm.board_profiles import ESP32, PROFILES, BoardProfile, get_profile
from ..comm.sketch import SketchProcess, build_sketch, list_sketches
from ..comm.virtual import BuildError
from ..comm.protocol import FAULT_TEXT, DevState
from .fonts import mono_font, ui_font
from .theme import themed

W, H = 900.0, 430.0
RELAY_X0, RELAY_SLOT = 150.0, 91.0      # 8 reles ao longo da borda de cima (como na placa)
IN_X0, IN_SLOT = 300.0, 72.5            # 8 entradas optoacopladas na borda de baixo
PERIODIC = {"STATUS", "READ_VARS", "READ_IO"}
VERIFY_BG = themed("#fef3c7", "#4a3a12")
STATE_COLORS = {"RUN": "#16a34a", "STOP": "#f59e0b", "FAULT": "#dc2626", "PROGRAM_LOADING": "#2563eb",
                "DESLIGADA": "#64748b", "SKETCH": "#7c3aed", "COMPILANDO": "#2563eb"}
SILK = QColor("#e0f2fe")                 # serigrafia branca sobre a placa azul
MUTED_SILK = QColor("#93c5fd")
TERMINAL = QColor("#22a06b")
# Arduino: placa a esquerda, botoes das entradas embaixo dela, modulo de reles a direita
ARD_BOARD = QRectF(26, 44, 404, 258)
ARD_INPUTS = QRectF(20, 312, 416, 110)
ARD_MODULE = QRectF(452, 8, 440, 414)
# Mega 2560: placa mais comprida (101 x 53 mm), modulo de reles um pouco mais estreito
MEGA_PITCH, MEGA_ROW = 12.5, 11.5      # passo dos conectores desenhados do Mega
MEGA_LAYOUT = (QRectF(26, 46, 474, 250), QRectF(20, 312, 480, 110), QRectF(516, 8, 376, 414))
WIRE_ON, WIRE_OFF = QColor("#f59e0b"), QColor("#94a3b8")
MODE_TIP = "O que roda na placa simulada: o firmware do CLP ou um exemplo de firmware/examples"


class BoardView(QWidget):
    """Desenho da placa ESP32 Relay X8 (layout da foto do repositorio de referencia).

    Coordenadas logicas W x H, escaladas para o widget. Os estados vem do
    firmware (saidas comandadas e entradas lidas); os niveis eletricos dos
    registradores sao calculados a partir de board_config.h.
    """
    inputClicked = Signal(int)

    def __init__(self, config: BoardConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.powered = False
        self.virtual = False
        self.state = "DESLIGADA"
        self.outputs = 0
        self.inputs = 0
        self.names: dict[str, str] = {}
        self.rx_until = 0.0              # LEDs RX/TX do conversor USB-serial piscam com o trafego
        self.tx_until = 0.0
        self.raw595: int | None = None   # niveis vindos do 74HC595/165 simulados (modo sketch)
        self.raw165: int | None = None
        self.oe_disabled = False
        self.badge = ""                  # texto do selo (padrao: estado do firmware)
        self.profile: BoardProfile = ESP32
        self.relays = ESP32.default_relays
        self._pins: dict[str, QPointF] = {}   # posicao de cada pino desenhado (para os fios)
        self.setMinimumSize(QSize(450, 215))
        self.setMouseTracking(True)
        self._hover: int | None = None

    def sizeHint(self) -> QSize:
        return QSize(900, 430)

    # ------------------------------------------------------------ geometria
    def _transform(self) -> tuple[float, float, float]:
        s = min(self.width() / W, self.height() / H)
        return s, (self.width() - W * s) / 2, (self.height() - H * s) / 2

    def set_board(self, profile: BoardProfile, relays: int) -> None:
        self.profile = profile
        self.relays = profile.clamp_relays(relays)
        self.outputs &= (1 << self.relays) - 1
        self.inputs &= (1 << profile.n_inputs) - 1
        self.update()

    @property
    def is_esp32(self) -> bool:
        return self.profile.id == ESP32.id

    def input_rect(self, k: int) -> QRectF:
        if self.is_esp32:
            return QRectF(IN_X0 + k * IN_SLOT, 282, IN_SLOT - 4, 142)
        area = self._layout()[1]
        rows = math.ceil(self.profile.n_inputs / 8)
        w, h = area.width() / 8, area.height() / rows
        return QRectF(area.left() + (k % 8) * w + 2, area.top() + (k // 8) * h + 2, w - 4, h - 4)

    def _layout(self) -> tuple[QRectF, QRectF, QRectF]:
        """Placa, area dos botoes de entrada e modulo de reles do Arduino escolhido."""
        return MEGA_LAYOUT if self.profile.id == "arduino-mega" else (ARD_BOARD, ARD_INPUTS, ARD_MODULE)

    def _logical(self, pos) -> QPointF:
        s, ox, oy = self._transform()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _input_at(self, pos) -> int | None:
        p = self._logical(pos)
        return next((k for k in range(self.profile.n_inputs) if self.input_rect(k).contains(p)), None)

    def mousePressEvent(self, event) -> None:
        k = self._input_at(event.position())
        if k is not None and self.powered and self.virtual:
            self.inputClicked.emit(k)

    def mouseMoveEvent(self, event) -> None:
        k = self._input_at(event.position())
        clickable = k is not None and self.powered and self.virtual
        self.setCursor(Qt.PointingHandCursor if clickable else Qt.ArrowCursor)
        if k != self._hover:
            self._hover = k
            self.update()

    # --------------------------------------------------------------- desenho
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s, ox, oy = self._transform()
        p.translate(ox, oy)
        p.scale(s, s)
        on = self.powered
        if self.is_esp32:
            self._paint_esp32(p)
        else:
            self._paint_arduino(p)
        color = QColor(STATE_COLORS.get(self.state, "#64748b"))   # estado informado pelo firmware
        badge = QRectF(14, 14, 128, 28) if self.is_esp32 else QRectF(26, 8, 170, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(badge, 7, 7)
        self._text(p, badge, self.badge or f"FIRMWARE: {self.state}", 8, True, QColor("white"), Qt.AlignCenter)
        if on and self.oe_disabled:
            self._text(p, QRectF(300, 160, 300, 14), "/OE = 1: saídas do 74HC595 desabilitadas (relés soltos)",
                       7, True, QColor("#fde68a"))
        if not on:
            p.setBrush(QColor(15, 23, 42, 150))
            p.drawRoundedRect(QRectF(4, 4, W - 8, H - 8), 10, 10)
            self._text(p, QRectF(0, 0, W, H), "Placa desligada\nClique em 'Ligar'", 16, True,
                       QColor("white"), Qt.AlignCenter)
        p.end()

    def _paint_esp32(self, p) -> None:
        on = self.powered
        grad = QLinearGradient(0, 0, 0, H)                         # placa azul
        grad.setColorAt(0, QColor("#1d4ed8") if on else QColor("#3b4a6b"))
        grad.setColorAt(1, QColor("#1e3a8a") if on else QColor("#2b3550"))
        p.setPen(QPen(QColor("#172554"), 2))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(4, 4, W - 8, H - 8), 10, 10)
        p.setBrush(QColor("#d6d3d1"))
        p.setPen(Qt.NoPen)
        for x, y in ((18, 56), (W - 18, 56), (18, H - 18), (W - 18, H - 18)):
            p.drawEllipse(QPointF(x, y), 6, 6)
        for k in range(8):
            if k < self.relays:
                self._relay(p, k)
            else:
                self._empty_relay(p, k)
            self._input(p, k)
        self._esp32(p)
        self._registers(p)
        self._usb(p)
        self._power_and_modbus(p)

    @staticmethod
    def _text(p, rect, text, size, bold=False, color=SILK, align=Qt.AlignLeft | Qt.AlignVCenter,
              mono=False) -> None:
        p.setFont(mono_font(size, bold) if mono else ui_font(size, bold))
        p.setPen(color)
        p.drawText(rect, align, text)

    def _led(self, p, c: QPointF, lit: bool, color: QColor, r: float = 5) -> None:
        if lit:
            glow = QColor(color)
            glow.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(c, r * 2, r * 2)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(color if lit else QColor(color).darker(350))
        p.drawEllipse(c, r, r)

    def _terminal(self, p, rect: QRectF, screws: int) -> list[QPointF]:
        p.setPen(QPen(QColor("#065f46"), 1))
        p.setBrush(TERMINAL)
        p.drawRect(rect)
        centers = []
        for j in range(screws):
            c = QPointF(rect.left() + rect.width() * (j + 0.5) / screws, rect.center().y())
            p.setBrush(QColor("#9ca3af"))
            p.drawEllipse(c, 5.5, 5.5)
            p.setPen(QPen(QColor("#4b5563"), 1.2))
            p.drawLine(QPointF(c.x() - 3, c.y()), QPointF(c.x() + 3, c.y()))
            p.setPen(QPen(QColor("#065f46"), 1))
            centers.append(c)
        return centers

    def _relay(self, p, k: int) -> None:
        x0 = RELAY_X0 + k * RELAY_SLOT
        on = self.powered and bool(self.outputs >> k & 1)
        screws = self._terminal(p, QRectF(x0 + 10, 8, RELAY_SLOT - 24, 24), 3)
        for c, label in zip(screws, ("NC", "COM", "NO")):           # ordem da etiqueta da placa
            self._text(p, QRectF(c.x() - 14, 33, 28, 10), label, 5.5, True, SILK, Qt.AlignCenter)
        body = QRectF(x0 + 8, 46, RELAY_SLOT - 20, 66)
        p.setPen(QPen(QColor("#1e3a8a"), 1))
        p.setBrush(QColor("#2563eb"))
        p.drawRoundedRect(body, 3, 3)
        self._text(p, QRectF(body.left(), body.top() + 2, body.width(), 11), "SRD-05VDC", 5.5, True,
                   QColor("#bfdbfe"), Qt.AlignCenter)
        nc = QPointF(body.left() + 14, body.top() + 24)
        no = QPointF(body.right() - 14, body.top() + 24)
        com = QPointF(body.center().x(), body.bottom() - 10)
        p.setPen(QPen(QColor("#e0e7ff"), 1.5))
        for pt in (nc, no):
            p.drawLine(QPointF(pt.x(), pt.y() - 7), pt)
        p.setPen(QPen(QColor("#fde047") if on else QColor("#e0e7ff"), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(com, no if on else nc)                           # contato movel: COM-NO quando energizado
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e0e7ff"))
        p.drawEllipse(com, 2.5, 2.5)
        self._led(p, QPointF(x0 + 18, 124), on, QColor("#ef4444"), 4)
        self._text(p, QRectF(x0 + 26, 117, RELAY_SLOT - 30, 14), f"OUT{k + 1}", 7.5, True,
                   QColor("#fde68a") if on else SILK)
        self._text(p, QRectF(x0, 132, RELAY_SLOT - 6, 12), f"Q0.{k}  {self.names.get(f'Q0.{k}', '')}"[:18], 6.5,
                   False, SILK, Qt.AlignCenter)
        pos = self.config.out_map.index(k) if k in self.config.out_map else k
        self._text(p, QRectF(x0, 144, RELAY_SLOT - 6, 11), f"595 pos {pos}", 6, False, MUTED_SILK, Qt.AlignCenter)

    def _empty_relay(self, p, k: int) -> None:
        """Posicao sem rele (versoes X1/X2/X4 da placa): so a marca na serigrafia."""
        x0 = RELAY_X0 + k * RELAY_SLOT
        p.setPen(QPen(MUTED_SILK, 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(x0 + 8, 46, RELAY_SLOT - 20, 66), 3, 3)
        self._text(p, QRectF(x0, 70, RELAY_SLOT - 6, 14), f"K{k + 1}", 7.5, True, MUTED_SILK, Qt.AlignCenter)
        self._text(p, QRectF(x0, 84, RELAY_SLOT - 6, 12), "sem relé", 6, False, MUTED_SILK, Qt.AlignCenter)

    def _input(self, p, k: int) -> None:
        r = self.input_rect(k)
        active = self.powered and bool(self.inputs >> k & 1)
        if self._hover == k and self.powered and self.virtual:
            p.setPen(QPen(QColor("#fde68a"), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 6, 6)
        pos = self.config.in_map.index(k) if k in self.config.in_map else k
        self._text(p, QRectF(r.left(), r.top() + 2, r.width(), 11), f"165 pos {pos}", 6, False, MUTED_SILK,
                   Qt.AlignCenter)
        for j in range(2):                                          # dois optoacopladores por entrada
            opto = QRectF(r.center().x() - 13, r.top() + 16 + j * 22, 26, 16)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#111827"))
            p.drawRect(opto)
        self._led(p, QPointF(r.center().x(), r.top() + 66), active, QColor("#22c55e"), 4)
        self._text(p, QRectF(r.left(), r.top() + 74, r.width(), 13), f"IN{k + 1}", 7.5, True,
                   QColor("#bbf7d0") if active else SILK, Qt.AlignCenter)
        self._text(p, QRectF(r.left() - 2, r.top() + 87, r.width() + 4, 11),
                   f"I0.{k} {self.names.get(f'I0.{k}', '')}"[:14], 6, False, SILK, Qt.AlignCenter)
        self._text(p, QRectF(r.left(), r.top() + 98, r.width(), 10), "5-24V  +  -", 5.5, False, MUTED_SILK,
                   Qt.AlignCenter)
        self._terminal(p, QRectF(r.left() + 8, r.bottom() - 30, r.width() - 16, 26), 2)

    def _esp32(self, p) -> None:
        mod = QRectF(14, 160, 110, 110)                              # modulo com a antena para a esquerda
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#1e293b"))
        p.drawRect(mod)
        p.setPen(QPen(QColor("#fbbf24"), 1.6))
        pts = []
        for k in range(6):
            y = mod.top() + 8 + k * 16
            pts += [QPointF(mod.left() + 6, y), QPointF(mod.left() + 26, y), QPointF(mod.left() + 26, y + 8),
                    QPointF(mod.left() + 6, y + 8)]
        p.drawPolyline(pts)
        can = QRectF(mod.left() + 32, mod.top() + 6, mod.width() - 38, mod.height() - 12)
        grad = QLinearGradient(can.topLeft(), can.bottomRight())
        grad.setColorAt(0, QColor("#e5e7eb"))
        grad.setColorAt(1, QColor("#9ca3af"))
        p.setPen(QPen(QColor("#6b7280"), 1))
        p.setBrush(grad)
        p.drawRect(can)
        self._text(p, can.adjusted(3, 3, -3, -3), f"ESP32\nWROOM\n\nCLP\nv{self.config.value('FW_VERSION', '?')}",
                   8, True, QColor("#1f2937"), Qt.AlignCenter)
        cfg = self.config
        pins = [("PIN_595_SER", "SER  > 595"), ("PIN_SR_CLK", "CLK  > 595/165"),
                ("PIN_SR_LATCH", "LATCH> 595/165"), ("PIN_595_OE", "/OE  > 595"), ("PIN_165_QH", "QH   < 165"),
                ("PIN_RS485_RX", "RX   < RS-485"), ("PIN_RS485_TX", "TX   > RS-485"),
                ("PIN_RS485_DE", "DE   > RS-485")]
        y = 162.0
        for name, text in pins:
            gpio = cfg.value(name)
            if gpio is None:
                continue
            item = next(i for i in cfg.items if i.name == name)
            color = QColor("#fde68a") if item.verify else SILK
            self._text(p, QRectF(mod.right() + 6, y, 160, 13), f"GPIO{gpio:<2} {text}", 6.5, False, color, mono=True)
            y += 13.5

    def _registers(self, p) -> None:
        cfg = self.config
        width = (W - 14 - 300) / 2 - 6
        for title, x, levels, labels, sub in (
                ("74HC595  -> relés", 300.0, self._raw_levels(self.raw595) or cfg.shift_out_levels(self.outputs),
                 [f"Q0.{c}" for c in cfg.out_map], "nível no pino"),
                ("74HC165  <- entradas", 300.0 + width + 12,
                 self._raw_levels(self.raw165) or cfg.shift_in_levels(self.inputs),
                 [f"I0.{c}" for c in cfg.in_map], "nível lido")):
            chip = QRectF(x, 176, width, 70)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#111827"))
            p.drawRoundedRect(chip, 4, 4)
            p.setBrush(QColor("#9ca3af"))
            for k in range(8):
                px = chip.left() + 10 + k * (chip.width() - 20) / 7
                p.drawRect(QRectF(px - 2, chip.top() - 4, 4, 4))
                p.drawRect(QRectF(px - 2, chip.bottom(), 4, 4))
            self._text(p, QRectF(chip.left() + 6, chip.top() + 2, chip.width(), 14), title, 7.5, True,
                       QColor("white"))
            cell_w = (chip.width() - 12) / 8
            for k, level in enumerate(levels):
                r = QRectF(chip.left() + 6 + k * cell_w, chip.top() + 18, cell_w - 3, 22)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#22c55e") if (level and self.powered) else QColor("#334155"))
                p.drawRoundedRect(r, 3, 3)
                self._text(p, r, str(level) if self.powered else "-", 9, True, QColor("white"), Qt.AlignCenter,
                           mono=True)
                self._text(p, QRectF(r.left() - 4, r.bottom() + 1, r.width() + 8, 12), labels[k], 6.5, False,
                           QColor("#cbd5e1"), Qt.AlignCenter)
            self._text(p, QRectF(chip.left() + 6, chip.bottom() - 13, chip.width(), 12),
                       f"posição 0..7: {sub} (0/1)", 6.5, False, QColor("#94a3b8"))

    @staticmethod
    def _raw_levels(raw: int | None) -> list[int] | None:
        """Byte do registrador simulado -> nivel por posicao (posicao 0 = bit 7, o primeiro deslocado)."""
        return None if raw is None else [(raw >> (7 - i)) & 1 for i in range(8)]

    def _usb(self, p) -> None:
        now = time.monotonic()
        usb = QRectF(40, 386, 40, 30)
        p.setPen(QPen(QColor("#475569"), 1))
        p.setBrush(QColor("#cbd5e1"))
        p.drawRoundedRect(usb, 6, 6)
        self._text(p, QRectF(30, 368, 70, 14), "USB-C", 7, True, SILK, Qt.AlignCenter)
        for j, (label, lit, color) in enumerate((("PWR", self.powered, QColor("#ef4444")),
                                                 ("RX", self.powered and now < self.rx_until, QColor("#22c55e")),
                                                 ("TX", self.powered and now < self.tx_until, QColor("#f59e0b")))):
            self._led(p, QPointF(18 + j * 22, 330), lit, color, 3.5)
            self._text(p, QRectF(8 + j * 22, 338, 22, 10), label, 5.5, True, SILK, Qt.AlignCenter)
        for j, label in enumerate(("BOOT", "RST")):
            b = QRectF(90 + j * 30, 392, 18, 18)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#d1d5db"))
            p.drawRect(b)
            p.setBrush(QColor("#111827"))
            p.drawEllipse(b.center(), 5, 5)
            self._text(p, QRectF(b.left() - 8, b.top() - 13, 34, 11), label, 5.5, True, SILK, Qt.AlignCenter)
        self._text(p, QRectF(8, 352, 140, 12), f"LDP {self.config.value('LDP_BAUD', 115200)} bit/s", 6, False,
                   MUTED_SILK)

    def _power_and_modbus(self, p) -> None:
        cfg = self.config
        chip = QRectF(160, 300, 44, 24)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#111827"))
        p.drawRect(chip)
        self._text(p, chip, "RS-485", 6.5, True, QColor("white"), Qt.AlignCenter)
        enabled = cfg.value("MODBUS_ENABLED", 0)
        txt = (f"Modbus end. {cfg.value('MODBUS_ADDRESS', '?')}\n{cfg.value('MODBUS_BAUD', '?')} bit/s"
               if enabled else "Modbus desabilitado")
        self._text(p, QRectF(208, 298, 90, 28), txt, 6, False, SILK)
        self._terminal(p, QRectF(160, 368, 50, 26), 2)
        self._text(p, QRectF(150, 396, 70, 22), "MODBUS\nA   B", 6, True, SILK, Qt.AlignCenter)
        self._terminal(p, QRectF(232, 368, 50, 26), 2)
        self._text(p, QRectF(222, 396, 70, 22), "POWER 9-24V\n+   -", 6, True, SILK, Qt.AlignCenter)

    # ------------------------------------------------------------- Arduino
    def _paint_arduino(self, p) -> None:
        """Arduino UNO ou Mega ligado a um modulo de reles; entradas como botoes embaixo da placa."""
        self._pins = {}
        mega = self.profile.id == "arduino-mega"
        self._arduino_board(p, mega)
        connector = self._relay_module(p)
        self._arduino_inputs(p)
        for k in range(self.relays):                                 # fios: pino -> IN k do modulo
            start, end = self._pins.get(self.profile.relay_pins[k]), connector.get(k)
            if start is None or end is None:
                continue
            on = self.powered and bool(self.outputs >> k & 1)
            path_pen = QPen(WIRE_ON if on else WIRE_OFF, 2.2 if on else 1.4)
            path_pen.setCapStyle(Qt.RoundCap)
            p.setPen(path_pen)
            p.setBrush(Qt.NoBrush)
            bump = -30
            if mega:                                                 # sai pela borda, sem cruzar o conector duplo
                start = QPointF(self._layout()[0].right() + 1, start.y() + (2 if k % 2 else -2))
                bump = 0
            mid = (start.x() + end.x()) / 2
            path = QPainterPath(start)
            path.cubicTo(QPointF(mid, start.y() + bump), QPointF(mid, end.y()), end)
            p.drawPath(path)

    def _arduino_board(self, p, mega: bool) -> None:
        on = self.powered
        b = self._layout()[0]
        grad = QLinearGradient(b.topLeft(), b.bottomLeft())
        grad.setColorAt(0, QColor("#0f8f99") if on else QColor("#41656a"))
        grad.setColorAt(1, QColor("#00646c") if on else QColor("#2f4a4e"))
        p.setPen(QPen(QColor("#004a50"), 2))
        p.setBrush(grad)
        p.drawRoundedRect(b, 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e5e7eb"))
        for x, y in ((b.left() + 14, b.top() + 14), (b.left() + 14, b.bottom() - 14)):   # longe dos conectores
            p.drawEllipse(QPointF(x, y), 4.5, 4.5)
        usb = QRectF(b.left() - 16, b.top() + 34, 60, 46)            # conector USB-B
        g = QLinearGradient(usb.topLeft(), usb.bottomLeft())
        g.setColorAt(0, QColor("#f1f5f9"))
        g.setColorAt(1, QColor("#94a3b8"))
        p.setPen(QPen(QColor("#475569"), 1))
        p.setBrush(g)
        p.drawRect(usb)
        self._text(p, usb, "USB", 7, True, QColor("#334155"), Qt.AlignCenter)
        jack = QRectF(b.left() - 12, b.bottom() - 74, 52, 42)         # alimentacao 7-12 V
        p.setBrush(QColor("#111827"))
        p.drawRect(jack)
        p.setBrush(QColor("#374151"))
        p.drawEllipse(jack.center(), 9, 9)
        self._text(p, QRectF(jack.right() + 4, jack.center().y() - 6, 40, 12), "7-12V", 6, True, SILK)
        if mega:
            self._mega_details(p, b)
            return
        now = time.monotonic()
        for j, (label, lit, color) in enumerate((("ON", on, QColor("#22c55e")),
                                                 ("TX", on and now < self.tx_until, QColor("#f59e0b")),
                                                 ("RX", on and now < self.rx_until, QColor("#f59e0b")))):
            c = QPointF(b.left() + 76, b.top() + 104 + j * 15)
            self._led(p, c, lit, color, 3)
            self._text(p, QRectF(c.x() + 7, c.y() - 6, 22, 12), label, 5.5, True, SILK)
        reset = QRectF(b.left() + 64, b.top() + 40, 16, 16)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#d1d5db"))
        p.drawRect(reset)
        p.setBrush(QColor("#b91c1c"))
        p.drawEllipse(reset.center(), 4.5, 4.5)
        self._text(p, QRectF(reset.left() - 8, reset.bottom() + 1, 34, 10), "RESET", 5, True, SILK, Qt.AlignCenter)
        crystal = QRectF(b.left() + 110, b.top() + 150, 30, 12)
        p.setPen(QPen(QColor("#6b7280"), 1))
        p.setBrush(QColor("#d1d5db"))
        p.drawRoundedRect(crystal, 6, 6)
        self._text(p, QRectF(crystal.left() - 4, crystal.bottom() + 1, 40, 10), "16 MHz", 5, False, SILK,
                   Qt.AlignCenter)
        logo = QFont(ui_font(15, True))
        logo.setItalic(True)
        p.setFont(logo)
        p.setPen(QColor("white"))
        p.drawText(QRectF(b.left() + 100, b.top() + 54, 200, 26), Qt.AlignLeft | Qt.AlignVCenter, "ARDUINO")
        self._text(p, QRectF(b.left() + 100, b.top() + 78, 220, 20), "UNO", 11, True, QColor("white"))
        self._uno_headers(p, b)
        chip = QRectF(b.left() + 196, b.top() + 168, 170, 34)         # ATmega328P (DIP-28)
        p.setPen(QPen(QColor("#9ca3af"), 1))
        p.setBrush(QColor("#9ca3af"))
        for j in range(14):
            x = chip.left() + 8 + j * (chip.width() - 16) / 13
            p.drawRect(QRectF(x - 2, chip.top() - 5, 4, 5))
            p.drawRect(QRectF(x - 2, chip.bottom(), 4, 5))
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#1f2937"))
        p.drawRect(chip)
        p.setBrush(QColor("#111827"))
        p.drawChord(QRectF(chip.left() - 7, chip.center().y() - 7, 14, 14), -90 * 16, 180 * 16)
        self._text(p, chip, "ATMEGA328P", 8, True, QColor("#e5e7eb"), Qt.AlignCenter)

    def _mega_details(self, p, b: QRectF) -> None:
        """Componentes do Mega 2560 R3 nas posicoes da placa real: 16U2 perto do USB,
        ATmega2560 girado 45 graus no centro, ICSP, regulador e capacitores perto do jack."""
        on = self.powered
        reset = QRectF(b.left() + 64, b.top() + 8, 16, 16)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#d1d5db"))
        p.drawRect(reset)
        p.setBrush(QColor("#b91c1c"))
        p.drawEllipse(reset.center(), 4.5, 4.5)
        self._text(p, QRectF(reset.left() - 8, reset.bottom() + 1, 32, 10), "RESET", 5, True, SILK, Qt.AlignCenter)
        u2 = QRectF(b.left() + 54, b.top() + 92, 24, 24)               # ATmega16U2: conversor USB-serial
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#1f2937"))
        p.drawRect(u2)
        self._text(p, u2, "16U2", 4.5, True, QColor("#d1d5db"), Qt.AlignCenter)
        now = time.monotonic()
        for j, (label, lit, color) in enumerate((("TX", on and now < self.tx_until, QColor("#f59e0b")),
                                                 ("RX", on and now < self.rx_until, QColor("#f59e0b")),
                                                 ("ON", on, QColor("#22c55e")))):
            c = QPointF(b.left() + 96, b.top() + 96 + j * 13)
            self._led(p, c, lit, color, 3)
            self._text(p, QRectF(c.x() + 6, c.y() - 6, 22, 12), label, 5.5, True, SILK)
        reg = QRectF(b.left() + 90, b.bottom() - 62, 22, 14)            # regulador 5 V
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#9ca3af"))
        p.drawRect(QRectF(reg.left() + 2, reg.top() - 5, reg.width() - 4, 5))
        p.setBrush(QColor("#111827"))
        p.drawRect(reg)
        for j in range(2):                                              # capacitores eletroliticos
            c = QPointF(b.left() + 130 + j * 20, b.bottom() - 56)
            p.setPen(QPen(QColor("#334155"), 1))
            p.setBrush(QColor("#cbd5e1"))
            p.drawEllipse(c, 7.5, 7.5)
            p.setBrush(QColor("#64748b"))
            p.drawPie(QRectF(c.x() - 7.5, c.y() - 7.5, 15, 15), 60 * 16, 60 * 16)
        crystal = QRectF(b.left() + 174, b.top() + 168, 30, 12)
        p.setPen(QPen(QColor("#6b7280"), 1))
        p.setBrush(QColor("#d1d5db"))
        p.drawRoundedRect(crystal, 6, 6)
        self._text(p, QRectF(crystal.left() - 4, crystal.bottom() + 1, 40, 10), "16 MHz", 5, False, SILK,
                   Qt.AlignCenter)
        logo = QFont(ui_font(15, True))
        logo.setItalic(True)
        p.setFont(logo)
        p.setPen(QColor("white"))
        p.drawText(QRectF(b.left() + 96, b.top() + 44, 200, 24), Qt.AlignLeft | Qt.AlignVCenter, "ARDUINO")
        self._text(p, QRectF(b.left() + 96, b.top() + 66, 160, 18), "MEGA 2560", 10, True, QColor("white"))
        p.save()                                                        # ATmega2560 (TQFP-100) a 45 graus
        p.translate(b.left() + 262, b.top() + 140)
        p.rotate(45)
        chip = QRectF(-34, -34, 68, 68)
        p.setPen(QPen(QColor("#9ca3af"), 1))
        for j in range(16):
            t = -28 + j * 56 / 15
            p.drawLine(QPointF(t, -39), QPointF(t, -34))
            p.drawLine(QPointF(t, 34), QPointF(t, 39))
            p.drawLine(QPointF(-39, t), QPointF(-34, t))
            p.drawLine(QPointF(34, t), QPointF(39, t))
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#1f2937"))
        p.drawRect(chip)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#374151"))
        p.drawEllipse(QPointF(-25, -25), 3, 3)                          # marca do pino 1
        self._text(p, chip, "ATMEGA\n2560", 7, True, QColor("#e5e7eb"), Qt.AlignCenter)
        p.restore()
        icsp = QPointF(b.right() - 128, b.top() + 128)                  # ICSP 2 x 3
        self._housing(p, QRectF(icsp.x() - 7, icsp.y() - 7, 27, 40))
        for r in range(3):
            for c in range(2):
                self._header_pin(p, QPointF(icsp.x() + c * 13, icsp.y() + r * 13), f"ICSP{r}{c}", "")
        self._text(p, QRectF(icsp.x() - 8, icsp.y() + 34, 30, 10), "ICSP", 5, True, SILK, Qt.AlignCenter)
        self._mega_headers(p, b)

    def _header_pin(self, p, c: QPointF, name: str, label: str, below: bool = True, label_w: float = 16) -> None:
        """Um pino do conector: aceso em laranja (saida ligada) ou verde (entrada ativa)."""
        self._pins[name] = c
        rk = self.profile.relay_pins.index(name) if name in self.profile.relay_pins else None
        ik = self.profile.input_pins.index(name) if name in self.profile.input_pins else None
        used = (rk is not None and rk < self.relays) or ik is not None
        lit = self.powered and ((rk is not None and rk < self.relays and self.outputs >> rk & 1)
                                or (ik is not None and self.inputs >> ik & 1))
        fill = QColor("#f59e0b") if lit and rk is not None else QColor("#22c55e") if lit else QColor("#111827")
        p.setPen(QPen(QColor("#fde68a") if used else QColor("#0f172a"), 1.2 if used else 1))
        p.setBrush(QColor("#1f2937"))
        p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
        p.setPen(Qt.NoPen)
        p.setBrush(fill if used else QColor("#a8a29e"))
        p.drawEllipse(c, 2.6 if not used else 3.2, 2.6 if not used else 3.2)
        if label:
            y = c.y() + 6 if below else c.y() - 16
            self._text(p, QRectF(c.x() - label_w / 2, y, label_w, 10), label, 5, used, QColor("#fde68a") if used
                       else SILK, Qt.AlignCenter)

    def _uno_headers(self, p, b: QRectF) -> None:
        pitch = 17.0
        x0 = b.right() - 22
        for k in range(14):                                          # D0 na ponta direita, como na placa
            self._header_pin(p, QPointF(x0 - k * pitch, b.top() + 14), f"D{k}", str(k))
        self._text(p, QRectF(x0 - 13 * pitch - 8, b.top() + 30, 13 * pitch + 16, 11), "DIGITAL (PWM ~)", 6, True,
                   SILK, Qt.AlignCenter)
        power = ["IOREF", "RESET", "3V3", "5V", "GND", "GND", "VIN"]
        for j, name in enumerate(power):
            self._header_pin(p, QPointF(b.left() + 110 + j * pitch, b.bottom() - 14), name, "", below=False)
        self._text(p, QRectF(b.left() + 100, b.bottom() - 40, 7 * pitch + 10, 11), "POWER", 6, True, SILK,
                   Qt.AlignCenter)
        for j in range(6):
            self._header_pin(p, QPointF(b.right() - 22 - (5 - j) * pitch, b.bottom() - 14), f"A{j}", f"A{j}",
                             below=False)
        self._text(p, QRectF(b.right() - 22 - 5 * pitch - 8, b.bottom() - 46, 5 * pitch + 16, 11), "ANALOG IN", 6,
                   True, SILK, Qt.AlignCenter)

    def _housing(self, p, rect: QRectF) -> None:
        """Corpo plastico preto de um conector de pinos."""
        p.setPen(QPen(QColor("#020617"), 1))
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(rect, 2, 2)

    def _header_row(self, p, x0: float, y: float, pins: list[tuple[str, str]], below: bool) -> float:
        """Conector em linha com a caixa preta; retorna o x do ultimo pino."""
        pitch = MEGA_PITCH
        x1 = x0 + (len(pins) - 1) * pitch
        self._housing(p, QRectF(x0 - 6.5, y - 6.5, x1 - x0 + 13, 13))
        for j, (name, label) in enumerate(pins):
            self._header_pin(p, QPointF(x0 + j * pitch, y), name, label, below=below, label_w=13)
        return x1

    def _mega_headers(self, p, b: QRectF) -> None:
        """Conectores na ordem da serigrafia do Mega 2560 R3."""
        gap = MEGA_PITCH + 6
        y = b.top() + 14
        top = [("SCL", ""), ("SDA", ""), ("AREF", ""), ("GND", "")] + [(f"D{k}", str(k)) for k in range(13, 7, -1)]
        x = b.left() + 92
        x_pwm = x
        x = self._header_row(p, x, y, top, True) + gap
        x = self._header_row(p, x, y, [(f"D{k}", str(k)) for k in range(7, -1, -1)], True)
        self._text(p, QRectF(x_pwm, y + 16, x - x_pwm, 10), "DIGITAL  PWM ~", 5.5, True, SILK, Qt.AlignCenter)
        x0 = x + gap
        x = self._header_row(p, x0, y, [(f"D{k}", str(k)) for k in range(14, 22)], True)
        self._text(p, QRectF(x0 - 6, y + 16, x - x0 + 12, 10), "COMUNICAÇÃO", 5.5, True, SILK, Qt.AlignCenter)
        y = b.bottom() - 14
        x0 = b.left() + 100
        power = ["NC", "IOREF", "RESET", "3V3", "5V", "GND", "GND", "VIN"]
        x = self._header_row(p, x0, y, [(n, "") for n in power], False)
        self._text(p, QRectF(x0 - 6, y - 26, x - x0 + 12, 10), "POWER", 5.5, True, SILK, Qt.AlignCenter)
        x0 = x + gap
        x = self._header_row(p, x0, y, [(f"A{k}", str(k)) for k in range(8)], False) + gap
        x = self._header_row(p, x, y, [(f"A{k}", str(k)) for k in range(8, 16)], False)
        self._text(p, QRectF(x0, y - 26, x - x0, 10), "ANALOG IN", 5.5, True, SILK, Qt.AlignCenter)
        # conector duplo na ponta: 5V, D22..D53 aos pares, GND
        cols = (b.right() - 30, b.right() - 17)
        row_y = [b.top() + 30 + r * MEGA_ROW for r in range(18)]
        self._housing(p, QRectF(cols[0] - 6.5, row_y[0] - 6.5, cols[1] - cols[0] + 13, row_y[-1] - row_y[0] + 13))
        for r, ry in enumerate(row_y):
            if r in (0, 17):
                label = "5V" if r == 0 else "GND"
                names = (f"{label}_{r}a", f"{label}_{r}b")
            else:
                pin = 22 + 2 * (r - 1)
                label, names = f"{pin}/{pin + 1}", (f"D{pin}", f"D{pin + 1}")
            for side in range(2):
                self._header_pin(p, QPointF(cols[side], ry), names[side], "")
            self._text(p, QRectF(cols[0] - 30, ry - 5, 22, 10), label, 4.5, False, SILK,
                       Qt.AlignRight | Qt.AlignVCenter)
        # o que o programa usa: reles em D22.. e entradas em D38..D53
        groups = [(1, (self.relays + 1) // 2, WIRE_ON, "RELÉS"),
                  (9, 16, QColor("#22c55e"), "ENTRADAS")]
        for first, last, color, caption in groups:
            y0, y1 = row_y[first] - 5, row_y[last] + 5
            x = cols[0] - 36
            p.setPen(QPen(color, 2.2, Qt.SolidLine, Qt.FlatCap))
            p.drawLine(QPointF(x, y0), QPointF(x, y1))
            p.drawLine(QPointF(x, y0), QPointF(x + 4, y0))
            p.drawLine(QPointF(x, y1), QPointF(x + 4, y1))
            p.save()
            p.translate(x - 4, (y0 + y1) / 2)
            p.rotate(-90)
            self._text(p, QRectF(-60, -8, 120, 8), caption, 5, True, color, Qt.AlignCenter)
            p.restore()

    def _relay_module(self, p) -> dict[int, QPointF]:
        """Modulo de N reles (rele, LED, borne NC/COM/NO). Retorna a posicao do pino IN k."""
        m = self._layout()[2]
        n = self.relays
        p.setPen(QPen(QColor("#172554"), 2))
        p.setBrush(QColor("#1d4ed8") if self.powered else QColor("#3b4a6b"))
        p.drawRoundedRect(m, 8, 8)
        self._text(p, QRectF(m.left() + 12, m.top() + 6, m.width() - 24, 18),
                   f"Módulo de {n} relé{'s' if n > 1 else ''} 5 V", 9, True, SILK)
        pins = ["VCC", "GND"] + [f"IN{k + 1}" for k in range(n)]
        pitch = min(17.0, (m.height() - 50) / len(pins))
        connector = {}
        for j, name in enumerate(pins):
            c = QPointF(m.left() + 14, m.top() + 38 + j * pitch)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#111827"))
            p.drawRect(QRectF(c.x() - 5, c.y() - 5, 10, 10))
            p.setBrush(QColor("#d6d3d1"))
            p.drawEllipse(c, 2.6, 2.6)
            self._text(p, QRectF(c.x() + 8, c.y() - 5, 30, 10), name, 5.5, True, SILK)
            if j >= 2:
                connector[j - 2] = c
        area = QRectF(m.left() + 54, m.top() + 30, m.width() - 62, m.height() - 38)
        cols = min(4, n) if n > 4 else min(2, n)                     # ate 4 reles: grade 2 x 2, maior
        rows = math.ceil(n / cols)
        cw, ch = area.width() / cols, min(180.0, area.height() / rows)
        top = area.top() + (area.height() - ch * rows) / 2           # grade centrada no modulo
        for k in range(n):
            cell = QRectF(area.left() + (k % cols) * cw, top + (k // cols) * ch, cw - 6, ch - 6)
            self._module_relay(p, cell, k)
        return connector

    def _module_relay(self, p, cell: QRectF, k: int) -> None:
        on = self.powered and bool(self.outputs >> k & 1)
        p.setPen(QPen(QColor("#1e3a8a"), 1))
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(cell, 5, 5)
        compact = cell.height() < 90
        term_h = 14 if compact else 20
        screws = self._terminal(p, QRectF(cell.left() + 8, cell.top() + 4, cell.width() - 16, term_h), 3)
        if not compact:
            for c, label in zip(screws, ("NC", "COM", "NO")):
                self._text(p, QRectF(c.x() - 14, cell.top() + 4 + term_h, 28, 9), label, 5, True, SILK,
                           Qt.AlignCenter)
        top = cell.top() + term_h + (8 if compact else 16)
        body = QRectF(cell.left() + 10, top, cell.width() * 0.55, cell.bottom() - top - (18 if compact else 30))
        p.setPen(QPen(QColor("#1e3a8a"), 1))
        p.setBrush(QColor("#2563eb"))
        p.drawRoundedRect(body, 3, 3)
        if body.height() > 30:
            self._text(p, QRectF(body.left(), body.top() + 1, body.width(), 10), "SRD-05VDC", 4.8, True,
                       QColor("#bfdbfe"), Qt.AlignCenter)
        nc = QPointF(body.left() + body.width() * 0.25, body.center().y() - 2)
        no = QPointF(body.right() - body.width() * 0.25, body.center().y() - 2)
        com = QPointF(body.center().x(), body.bottom() - 5)
        p.setPen(QPen(QColor("#fde047") if on else QColor("#e0e7ff"), 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(com, no if on else nc)                            # contato movel: COM-NO quando energizado
        self._led(p, QPointF(body.right() + 12, body.top() + 8), on, QColor("#ef4444"), 3.5)
        self._text(p, QRectF(body.right() + 4, body.top() + 14, cell.right() - body.right() - 4, 13), f"K{k + 1}",
                   8, True, QColor("#fde68a") if on else SILK)
        name = self.names.get(f"Q0.{k}", "")
        self._text(p, QRectF(cell.left() + 4, cell.bottom() - (16 if compact else 28), cell.width() - 8, 12),
                   f"Q0.{k}  {name}"[:20], 6, False, SILK, Qt.AlignCenter)
        if not compact:
            self._text(p, QRectF(cell.left() + 4, cell.bottom() - 15, cell.width() - 8, 11),
                       f"pino {self.profile.relay_pins[k]}", 5.5, False, MUTED_SILK, Qt.AlignCenter)

    def _arduino_inputs(self, p) -> None:
        area = self._layout()[1]
        self._text(p, QRectF(area.left(), area.top() - 11, area.width(), 10),
                   "Entradas (botões ligados aos pinos; clique para acionar)", 6, True, QColor("#64748b"))
        for k in range(self.profile.n_inputs):
            r = self.input_rect(k)
            active = self.powered and bool(self.inputs >> k & 1)
            hover = self._hover == k and self.powered and self.virtual
            p.setPen(QPen(QColor("#fde68a") if hover else QColor("#334155"), 1.5 if hover else 1))
            p.setBrush(QColor("#14532d") if active else QColor("#1e293b"))
            p.drawRoundedRect(r, 6, 6)
            compact = r.height() < 60
            self._led(p, QPointF(r.left() + 10, r.top() + 10), active, QColor("#22c55e"), 3.5)
            self._text(p, QRectF(r.left() + 16, r.top() + 3, r.width() - 18, 14), f"IN{k + 1}", 7, True,
                       QColor("#bbf7d0") if active else SILK)
            self._text(p, QRectF(r.left() + 2, r.top() + 18, r.width() - 4, 11),
                       f"I0.{k}  {self.profile.input_pins[k]}", 5.5, False, MUTED_SILK, Qt.AlignCenter)
            name = self.names.get(f"I0.{k}", "")
            if name:
                self._text(p, QRectF(r.left() + 2, r.top() + (30 if compact else 34), r.width() - 4, 11), name[:11],
                           5.5, False, SILK, Qt.AlignCenter)
            if not compact:
                btn = QRectF(r.center().x() - 11, r.bottom() - 30, 22, 22)
                p.setPen(QPen(QColor("#0f172a"), 1))
                p.setBrush(QColor("#d1d5db"))
                p.drawRect(btn)
                p.setBrush(QColor("#16a34a") if active else QColor("#374151"))
                p.drawEllipse(btn.center(), 7, 7)


class _SketchBridge(QObject):
    """Leva os eventos do processo do sketch (thread de leitura) para a interface."""
    serial = Signal(bytes)
    board = Signal(object)
    exited = Signal(int)
    built = Signal(object, str)          # executavel (ou None) e mensagem de erro


class Esp32Panel(QWidget):
    """Painel com a placa, a configuracao do firmware e o monitor serial.

    Dois modos: o firmware do CLP (dispositivo virtual, recebe o programa LADDER
    pela IDE) ou um exemplo Arduino de firmware/examples compilado para o PC.
    A placa (ESP32, Arduino UNO ou Mega) e o numero de reles sao escolhidos no topo.
    """
    boardChanged = Signal(str, int)          # id da placa, numero de reles
    adaptRequested = Signal(int, int)        # entradas e saidas que o projeto deve usar

    def __init__(self, session, device_panel, transfer, parent=None):
        super().__init__(parent)
        self.session = session
        self.device_panel = device_panel
        self.transfer = transfer
        self.config = load_board_config()
        self.profile: BoardProfile = ESP32
        self.relays = ESP32.default_relays
        self.project_io = (ESP32.n_inputs, ESP32.default_relays)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        board_row = QHBoxLayout()
        self.board_combo = QComboBox()
        for prof in PROFILES.values():
            self.board_combo.addItem(prof.name, prof.id)
            self.board_combo.setItemData(self.board_combo.count() - 1, prof.description, Qt.ToolTipRole)
        self.board_combo.setToolTip("Placa simulada. Desligue a placa para trocar.")
        self.relays_spin = QSpinBox()
        self.relays_spin.setToolTip("Quantos relés a placa (ou o módulo de relés) tem. Desligue a placa para trocar.")
        self.io_warning = QLabel()
        self.io_warning.setWordWrap(True)
        self.io_warning.setObjectName("warn")
        self.adapt_btn = QPushButton("Ajustar projeto à placa")
        self.adapt_btn.setToolTip("Reduz as entradas e saídas do projeto para as da placa (pode ser desfeito)")
        self.adapt_btn.clicked.connect(self._request_adapt)
        board_row.addWidget(QLabel("Placa:"))
        board_row.addWidget(self.board_combo)
        board_row.addWidget(QLabel("Relés:"))
        board_row.addWidget(self.relays_spin)
        board_row.addWidget(self.io_warning, 1)
        board_row.addWidget(self.adapt_btn)
        layout.addLayout(board_row)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("Firmware do CLP (programa LADDER)", None)
        for name in list_sketches():
            self.mode.addItem(f"Exemplo Arduino: {name}", name)
        self.mode.setToolTip(MODE_TIP)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        row.addWidget(self.mode)
        self.power_btn = QPushButton("Ligar ESP32 virtual")
        self.power_btn.setObjectName("primary")
        self.transfer_btn = QPushButton("Transferir programa")
        self.run_btn = QPushButton("RUN")
        self.stop_btn = QPushButton("STOP")
        self.reset_btn = QPushButton("Reiniciar placa")
        self.reset_btn.setToolTip("Desliga e liga a placa virtual: o firmware inicia de novo e carrega o "
                                  "programa gravado na flash (em STOP se AUTORUN_ON_BOOT = 0)")
        self.power_btn.clicked.connect(self.toggle_power)
        self.transfer_btn.clicked.connect(lambda: self.transfer())
        self.run_btn.clicked.connect(lambda: self.session.run_on_client("mode", lambda c: c.set_mode(True)))
        self.stop_btn.clicked.connect(lambda: self.session.run_on_client("mode", lambda c: c.set_mode(False)))
        self.reset_btn.clicked.connect(self.reset_board)
        for b in (self.power_btn, self.transfer_btn, self.run_btn, self.stop_btn, self.reset_btn):
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        self.hint = QLabel()                             # linha propria: nao estica a barra de botoes
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

        split = QSplitter(Qt.Horizontal)
        self.board = BoardView(self.config)
        self.board.inputClicked.connect(self.toggle_input)
        split.addWidget(self.board)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._config_tab(), "Configuração")
        self.tabs.addTab(self._serial_tab(), "Monitor serial")
        self.tabs.addTab(self._firmware_tab(), "Firmware")
        split.addWidget(self.tabs)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 2)
        self.split = split
        self._sized = False
        layout.addWidget(split, 1)

        session.connected.connect(self.on_connected)
        session.disconnected.connect(self.on_disconnected)
        session.status.connect(self.on_status)
        session.traffic.connect(self.on_traffic)
        self._reset_pending = False
        self.sketch: SketchProcess | None = None
        self.sketch_name = ""
        self.sketch_inputs = 0
        self._building = False
        self._bridge = _SketchBridge()
        self._bridge.serial.connect(self._sketch_serial)
        self._bridge.board.connect(self._sketch_board)
        self._bridge.exited.connect(self._sketch_exited)
        self._bridge.built.connect(self._sketch_built)
        self.board_combo.currentIndexChanged.connect(
            lambda: self.set_board(self.board_combo.currentData(), get_profile(self.board_combo.currentData())
                                   .default_relays))
        self.relays_spin.valueChanged.connect(lambda n: self.set_board(self.profile.id, n))
        self.set_board(ESP32.id, ESP32.default_relays, emit=False)

    # ----------------------------------------------------------- placa
    @property
    def short_name(self) -> str:
        return {"esp32-relay": "ESP32", "arduino-uno": "Arduino UNO", "arduino-mega": "Arduino Mega"}.get(
            self.profile.id, self.profile.name)

    def set_board(self, board_id: str, relays: int, emit: bool = True) -> None:
        """Troca a placa simulada (so com a placa desligada; ligada, os controles ficam bloqueados)."""
        profile = get_profile(board_id)
        relays = profile.clamp_relays(relays)
        if profile.id == self.profile.id and relays == self.relays and getattr(self, "_board_ready", False):
            return
        self.profile, self.relays = profile, relays
        self._board_ready = True
        self.board_combo.blockSignals(True)
        self.relays_spin.blockSignals(True)
        self.board_combo.setCurrentIndex(max(0, self.board_combo.findData(profile.id)))
        self.relays_spin.setRange(profile.min_relays, profile.max_relays)
        self.relays_spin.setValue(relays)
        self.board_combo.blockSignals(False)
        self.relays_spin.blockSignals(False)
        self.board.set_board(profile, relays)
        self.device_panel.virtual_args = profile.virtual_args(relays)
        esp32 = profile.id == ESP32.id
        if not esp32 and self.sketch_mode:
            self.mode.setCurrentIndex(0)                     # exemplos Arduino usam o io_board da ESP32
        self.mode.setEnabled(esp32)
        self.mode.setToolTip(MODE_TIP if esp32 else
                             "Os exemplos de firmware/examples são da placa ESP32 (74HC595/74HC165)")
        self._fill_config()
        self._check_io()
        self._update_buttons()
        if emit:
            self.boardChanged.emit(profile.id, relays)

    def _check_io(self) -> None:
        n_in, n_out = self.project_io
        problems = []
        if n_out > self.relays:
            problems.append(f"{n_out} saídas para {self.relays} relé{'s' if self.relays > 1 else ''}")
        if n_in > self.profile.n_inputs:
            problems.append(f"{n_in} entradas para {self.profile.n_inputs}")
        self.io_warning.setText(("O projeto tem " + " e ".join(problems) + ": a placa recusa a transferência.")
                                if problems else "")
        self.adapt_btn.setVisible(bool(problems))

    def _request_adapt(self) -> None:
        n_in, n_out = self.project_io
        self.adaptRequested.emit(min(n_in, self.profile.n_inputs), min(n_out, self.relays))

    @property
    def sketch_mode(self) -> bool:
        return self.mode.currentData() is not None

    # ----------------------------------------------------------- abas
    def _config_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.config_note = QLabel()
        self.config_note.setWordWrap(True)
        self.config_note.setObjectName("muted")
        v.addWidget(self.config_note)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Definição", "Valor", "O que faz"])
        self.tree.setRootIsDecorated(True)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        v.addWidget(self.tree, 1)
        self.open_cfg_btn = QPushButton("Abrir board_config.h")
        self.open_cfg_btn.clicked.connect(self._open_config)
        v.addWidget(self.open_cfg_btn, 0, Qt.AlignLeft)
        self._fill_config()
        return w

    def _fill_config(self) -> None:
        self.tree.clear()
        bold = QFont(self.font())
        bold.setBold(True)
        mono = mono_font(9)
        esp32 = self.profile.id == ESP32.id
        self.open_cfg_btn.setVisible(esp32)
        if not esp32:
            self.config_note.setText(f"{self.profile.description} Pinos usados com {self.relays} "
                                     f"relé{'s' if self.relays > 1 else ''}:")
            top = QTreeWidgetItem(["Placa"])
            top.setFont(0, bold)
            top.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(top)
            for name, value, what in (("Microcontrolador", self.profile.mcu, ""),
                                      ("Relés", str(self.relays), f"de {self.profile.min_relays} a "
                                                                  f"{self.profile.max_relays} no módulo"),
                                      ("Entradas", str(self.profile.n_inputs), "botões ligados aos pinos"),
                                      ("Firmware", "dispositivo virtual", "o mesmo firmware do CLP rodando no PC")):
                top.addChild(QTreeWidgetItem([name, value, what]))
            for title, prefix in (("Relés: Qk -> pino -> módulo", "Q"), ("Entradas: pino -> Ik", "I")):
                top = QTreeWidgetItem([title])
                top.setFont(0, bold)
                top.setFirstColumnSpanned(True)
                self.tree.addTopLevelItem(top)
                for addr, pin, what in self.profile.pin_map(self.relays):
                    if addr.startswith(prefix):
                        child = QTreeWidgetItem([addr, pin, what])
                        child.setFont(0, mono)
                        child.setFont(1, mono)
                        top.addChild(child)
            self.tree.expandAll()
            return
        self.config_note.setText(f"Lido de {self.config.source}. Em amarelo: valores marcados VERIFICAR no "
                                 "arquivo (confirmar na placa real, docs/hardware-setup.md).")
        for group, items in self.config.grouped():
            top = QTreeWidgetItem([group])
            top.setFont(0, bold)
            top.setFirstColumnSpanned(True)
            self.tree.addTopLevelItem(top)
            for it in items:
                child = QTreeWidgetItem([it.name, it.value, it.description or it.comment])
                child.setFont(0, mono)
                child.setFont(1, mono)
                tip = it.comment or it.description
                for col in range(3):
                    child.setToolTip(col, tip)
                    if it.verify:
                        child.setBackground(col, QBrush(VERIFY_BG))
                top.addChild(child)
            top.setFirstColumnSpanned(True)
        # mapeamento explicito: canal logico -> posicao e nivel eletrico
        top = QTreeWidgetItem(["Relés: Qk -> 74HC595 -> nível para ligar"])
        top.setFont(0, bold)
        top.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(top)
        level_on = "0 (ativo em 0)" if self.config.relay_active_low else "1"
        for k in range(self.relays):
            pos = self.config.out_map.index(k) if k in self.config.out_map else k
            top.addChild(QTreeWidgetItem([f"Q0.{k} / K{k + 1}", f"pos {pos}", f"nível {level_on} energiza o relé"]))
        top.setFirstColumnSpanned(True)
        top = QTreeWidgetItem(["Entradas: 74HC165 -> Ik"])
        top.setFont(0, bold)
        top.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(top)
        level_in = "0" if self.config.input_active_low else "1"
        for k in range(8):
            pos = self.config.in_map.index(k) if k in self.config.in_map else k
            top.addChild(QTreeWidgetItem([f"I0.{k}", f"pos {pos}", f"lê {level_in} quando a entrada está ativa"]))
        top.setFirstColumnSpanned(True)
        self.tree.expandAll()

    def _open_config(self) -> None:
        from ..comm.virtual import FIRMWARE
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(FIRMWARE / "src" / "board_config.h")))

    def _serial_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        self.serial_note = QLabel()
        self.serial_note.setWordWrap(True)
        self.serial_note.setObjectName("muted")
        v.addWidget(self.serial_note)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(600)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.log.setFont(mono_font(8.5))
        v.addWidget(self.log, 1)
        row = QHBoxLayout()
        self.show_periodic = QCheckBox("Mostrar leituras periódicas (STATUS / READ_VARS)")
        clear = QPushButton("Limpar")
        clear.clicked.connect(self.log.clear)
        row.addWidget(self.show_periodic, 1)
        row.addWidget(clear)
        v.addLayout(row)
        send_row = QHBoxLayout()
        self.send_edit = QLineEdit()
        self.send_edit.setPlaceholderText("Texto para a Serial do sketch (ex.: 1, c, m, h) e Enter")
        self.send_edit.returnPressed.connect(self.send_text)
        self.send_newline = QCheckBox("+ \\n")
        self.send_newline.setToolTip("Acrescenta fim de linha ao enviar")
        self.send_btn = QPushButton("Enviar")
        self.send_btn.clicked.connect(self.send_text)
        send_row.addWidget(self.send_edit, 1)
        send_row.addWidget(self.send_newline)
        send_row.addWidget(self.send_btn)
        v.addLayout(send_row)
        return w

    def _firmware_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.fw_device = QLabel("-")
        self.fw_program = QLabel("-")
        self.fw_scan = QLabel("-")
        self.fw_uptime = QLabel("-")
        self.fw_boot = QLabel(f"AUTORUN_ON_BOOT = {self.config.value('AUTORUN_ON_BOOT', 0)}: "
                              + ("entra em RUN ao ligar" if self.config.value("AUTORUN_ON_BOOT", 0)
                                 else "liga sempre em STOP (padrão seguro)"))
        for lbl in (self.fw_device, self.fw_program, self.fw_scan, self.fw_uptime, self.fw_boot):
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Placa:", self.fw_device)
        form.addRow("Programa:", self.fw_program)
        form.addRow("Varredura:", self.fw_scan)
        form.addRow("Ligada há:", self.fw_uptime)
        form.addRow("Partida:", self.fw_boot)
        return w

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized and self.split.width() > 200:        # placa com ~70% da largura
            self._sized = True
            total = self.split.width()
            self.split.setSizes([int(total * 0.7), total - int(total * 0.7)])

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if not self._sized and self.isVisible():
            self.showEvent(event)

    # -------------------------------------------------------- comandos
    def toggle_power(self) -> None:
        if self.sketch_mode:
            if self.sketch is not None or self._building:
                self.stop_sketch()
            else:
                self.start_sketch()
            self._update_buttons()
            return
        dp = self.device_panel
        if dp.connected or self.session.auto_reconnect:
            dp.toggle_connection()
        else:
            dp.kind.setCurrentIndex(1)                       # dispositivo virtual
            self._log("--", "ligando a placa virtual (firmware compilado para o PC)...")
            dp.toggle_connection()
        self._update_buttons()

    def reset_board(self) -> None:
        if self.sketch_mode:
            if self.sketch is not None:
                self._log("--", "RESET: o sketch reinicia (setup() de novo)")
                self.stop_sketch()
                self.start_sketch()
            return
        if not (self.device_panel.connected and self.session.is_virtual):
            return
        self._log("--", "RESET: placa desligada e ligada de novo")
        self._reset_pending = True
        self.device_panel.toggle_connection()
        QTimer.singleShot(400, self._power_back_on)

    def _power_back_on(self) -> None:
        if self._reset_pending and not self.device_panel.connected:
            self._reset_pending = False
            self.device_panel.kind.setCurrentIndex(1)
            self.device_panel.toggle_connection()

    def toggle_input(self, k: int) -> None:
        if self.sketch_mode:
            if self.sketch is not None:
                self.sketch_inputs ^= 1 << k                 # borne acionado: o 74HC165 simulado le na proxima carga
                self.sketch.set_inputs(self.sketch_inputs)
                self.board.inputs = self.sketch_inputs
                self.board.update()
            return
        buttons = self.device_panel.io.input_buttons
        if k < len(buttons) and buttons[k].isEnabled():
            buttons[k].click()                               # mesmo caminho do painel Dispositivo
            self.board.inputs ^= 1 << k                      # resposta imediata; o snapshot confirma
            self.board.update()

    # -------------------------------------------------------- eventos
    def set_project(self, project) -> None:
        names = {}
        for s in project.symbols:
            names.setdefault(s.address.strip().upper(), s.name)
        self.board.names = names
        self.project_io = (project.io.n_inputs, project.io.n_outputs)
        self._check_io()
        self.board.update()

    def on_connected(self, info) -> None:
        if self.sketch_mode:
            return
        self.board.powered = True
        self.board.virtual = self.session.is_virtual
        self.fw_device.setText(f"{info.hardware}, firmware {info.firmware}\nprotocolo LDP {info.protocol}, "
                               f"LDRB {info.fmt_major}.{info.fmt_minor}, E/S {info.n_inputs}/{info.n_outputs}, "
                               f"imagem até {info.max_image} bytes")
        kind = "virtual (firmware no PC)" if self.session.is_virtual else "real"
        self._log("--", f"BOOT placa {kind}: {info.hardware} firmware {info.firmware}, "
                        f"varredura {info.scan_period_ms} ms, E/S {info.n_inputs}/{info.n_outputs}")
        self._update_buttons()
        self.board.update()

    def on_disconnected(self, reason: str) -> None:
        if self.sketch_mode:
            return
        self.board.powered = False
        self.board.state = "DESLIGADA"
        self._log("--", f"desconectada: {reason}")
        self._update_buttons()
        self.board.update()

    def on_status(self, st) -> None:
        if self.sketch_mode:
            return
        name = st.state.name
        if self.board.state != name and self.board.powered:
            self._log("--", f"estado do firmware: {name}" +
                      (f" ({FAULT_TEXT.get(st.fault, st.fault)})" if st.state == DevState.FAULT else ""))
        self.board.state = name
        self.fw_program.setText(f"build_id 0x{st.build_id:08x}, CRC 0x{st.program_crc:08x}"
                                if st.has_program else "nenhum programa na flash")
        self.fw_scan.setText(f"{st.scan_count} varreduras a cada {st.scan_period_ms} ms\nexecução "
                             f"{st.last_exec_us} us (max {st.max_exec_us} us), atrasos {st.overruns}")
        self.fw_uptime.setText(f"{st.uptime_ms / 1000:.1f} s")
        self._update_buttons()
        self.board.update()

    def on_snapshot(self, snap) -> None:
        if self.sketch_mode:
            return
        self.board.outputs = snap.q_commanded
        self.board.inputs = snap.inputs
        self.board.update()

    def on_traffic(self, direction: str, cmd: str, seq: int, nbytes: int) -> None:
        if self.sketch_mode:
            return
        now = time.monotonic()
        if direction in ("TX", "RETRY"):
            self.board.rx_until = now + 0.08          # a placa recebe o que o PC transmite
        else:
            self.board.tx_until = now + 0.08
        self.board.update()
        QTimer.singleShot(100, self.board.update)
        if cmd in PERIODIC and not self.show_periodic.isChecked():
            return
        board = "ESP32" if self.profile.id == ESP32.id else "placa"
        arrow = {"TX": f"PC  -> {board}", "RX": f"PC <-  {board}", "ERR": f"PC <-  {board} ERRO",
                 "RETRY": f"PC  -> {board} (repete)"}.get(direction, direction)
        self._log(arrow, f"{cmd:<14} seq {seq:3d}  {nbytes} B")

    def _log(self, who: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log.appendPlainText(f"{stamp}  {who:<22} {text}")

    # ------------------------------------------------------ modo sketch
    def _mode_changed(self) -> None:
        if self.sketch is not None or self._building:
            self.stop_sketch()
        if self.sketch_mode and (self.device_panel.connected or self.session.auto_reconnect):
            self.device_panel.toggle_connection()           # a placa simulada roda uma coisa por vez
        self._reset_board_view()
        self._update_buttons()

    def _reset_board_view(self) -> None:
        b = self.board
        b.powered = False
        b.state = "DESLIGADA"
        b.badge = ""
        b.raw595 = b.raw165 = None
        b.oe_disabled = False
        b.outputs = b.inputs = 0
        b.virtual = False
        b.update()

    def start_sketch(self) -> None:
        name = self.mode.currentData()
        if self.device_panel.connected or self.session.auto_reconnect:
            self.device_panel.toggle_connection()
        self._building = True
        self.sketch_name = name
        self.board.badge = "COMPILANDO..."
        self.board.state = "COMPILANDO"
        self.board.update()
        self.log.clear()
        self._log("--", f"compilando firmware/examples/{name} para o PC (g++ + io_board.cpp + simulador Arduino)...")
        bridge = self._bridge

        def work():
            try:
                bridge.built.emit(build_sketch(name), "")
            except (BuildError, OSError) as exc:
                bridge.built.emit(None, str(exc))
        threading.Thread(target=work, daemon=True).start()
        self._update_buttons()

    def _sketch_built(self, exe, error: str) -> None:
        self._building = False
        if not self.sketch_mode or self.mode.currentData() != self.sketch_name:
            self._update_buttons()
            return
        if exe is None:
            self._log("--", "ERRO de compilação:")
            self.log.appendPlainText(error)
            self._reset_board_view()
            self.board.badge = "ERRO DE COMPILAÇÃO"
            self.board.update()
            self._update_buttons()
            return
        bridge = self._bridge
        try:
            self.sketch = SketchProcess(exe, bridge.serial.emit, bridge.board.emit, bridge.exited.emit)
        except OSError as exc:
            self._log("--", f"não foi possível iniciar o sketch: {exc}")
            self._update_buttons()
            return
        self.sketch_inputs = 0
        self.sketch.set_inputs(0)
        b = self.board
        b.powered = True
        b.virtual = True
        b.state = "SKETCH"
        b.badge = f"SKETCH: {self.sketch_name}"
        b.inputs = 0
        self.fw_device.setText(f"Exemplo Arduino '{self.sketch_name}' compilado para o PC")
        self.fw_program.setText(f"firmware/examples/{self.sketch_name} + src/io_board.cpp + simulador Arduino "
                                "(74HC595/74HC165 no nível dos sinais)")
        self.fw_scan.setText("-")
        self.fw_uptime.setText("-")
        self._log("--", "sketch iniciado: saída da Serial abaixo")
        self._update_buttons()
        b.update()

    def stop_sketch(self) -> None:
        self._building = False
        if self.sketch is not None:
            proc, self.sketch = self.sketch, None
            proc.close()
            self._log("--", "sketch encerrado")
        self._reset_board_view()

    def _sketch_serial(self, data: bytes) -> None:
        self.board.tx_until = time.monotonic() + 0.08
        QTimer.singleShot(100, self.board.update)
        cursor = self.log.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(data.decode("utf-8", "replace").replace("\r\n", "\n"))
        self.log.setTextCursor(cursor)
        self.log.ensureCursorVisible()

    def _sketch_board(self, st) -> None:
        if self.sketch is None:
            return
        b = self.board
        b.outputs = st.relays
        b.raw595 = st.q595
        b.raw165 = st.load165
        b.oe_disabled = bool(st.oe)
        b.update()

    def _sketch_exited(self, code: int) -> None:
        if self.sketch is not None:
            self.sketch = None
            self._log("--", f"o sketch terminou (código {code})")
            self._reset_board_view()
            self._update_buttons()

    def send_text(self) -> None:
        if self.sketch is None:
            return
        text = self.send_edit.text()
        data = text.encode("utf-8") + (b"\n" if self.send_newline.isChecked() else b"")
        if data:
            self.sketch.send_serial(data)
            self.board.rx_until = time.monotonic() + 0.08
            QTimer.singleShot(100, self.board.update)
            self.board.update()
        self.send_edit.clear()

    def shutdown(self) -> None:
        if self.sketch is not None:
            self.sketch.close()
            self.sketch = None

    def _update_buttons(self) -> None:
        if not hasattr(self, "log"):
            return                                           # ainda montando o painel
        sketch = self.sketch_mode
        busy_board = (self.sketch is not None or self._building or self.device_panel.connected
                      or self.session.auto_reconnect)
        for w in (self.board_combo, self.relays_spin):
            w.setEnabled(not busy_board)
        for w in (self.send_edit, self.send_btn, self.send_newline):
            w.setEnabled(sketch and self.sketch is not None)
        self.show_periodic.setVisible(not sketch)
        self.serial_note.setText(
            "Saída da Serial do sketch (USB a 115200 bit/s). Digite abaixo para enviar comandos." if sketch else
            "Quadros do protocolo LDP trocados com a placa (o mesmo que trafega pela USB-serial).")
        if sketch:
            running = self.sketch is not None or self._building
            self.power_btn.setText("Desligar placa" if running else "Ligar (compilar e rodar)")
            for b in (self.transfer_btn, self.run_btn, self.stop_btn):
                b.setEnabled(False)
            self.reset_btn.setEnabled(self.sketch is not None)
            self.hint.setText("O exemplo roda no PC com o io_board.cpp do firmware; os registradores mostram os "
                              "níveis gerados pelo próprio código. Clique nas entradas IN1..IN8.")
            return
        dp = self.device_panel
        on = dp.connected
        st = dp.last_status.state if (on and dp.last_status) else None
        busy = on or self.session.auto_reconnect
        self.power_btn.setText("Desligar placa" if busy else f"Ligar {self.short_name} virtual")
        self.transfer_btn.setEnabled(on)
        self.run_btn.setEnabled(on and st == DevState.STOP)
        self.stop_btn.setEnabled(on and st == DevState.RUN)
        self.reset_btn.setEnabled(on and self.session.is_virtual)
        if not on and self.profile.id != ESP32.id:
            self.hint.setText(f"Somente simulação: o firmware do CLP roda no PC com as E/S do {self.short_name} "
                              f"({self.profile.n_inputs} entradas, {self.relays} relé{'s' if self.relays > 1 else ''}"
                              "). Não há firmware para gravar num Arduino real.")
        elif not on:
            self.hint.setText("A placa virtual roda o mesmo código C do firmware no PC e fala LDP com a IDE.")
        elif self.session.is_virtual:
            self.hint.setText("Placa virtual: clique nas entradas I0.x da placa para liga-las.")
        else:
            self.hint.setText("Placa real conectada: o desenho mostra o que o firmware comanda e lê.")

    def theme_changed(self) -> None:
        self._fill_config()
        self.board.update()
