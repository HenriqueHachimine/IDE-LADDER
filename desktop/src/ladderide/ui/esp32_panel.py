"""Simulador da placa ESP32: a placa de 8 reles desenhada a partir de board_config.h.

A placa e "ligada" no dispositivo virtual, que executa o mesmo codigo C do
firmware (plc_core + ladder_vm) no PC e conversa com a IDE pelo protocolo
LDP, como a placa real faz pela USB. O desenho mostra o que o firmware
comanda: reles, niveis eletricos nos registradores 74HC595/74HC165 (com a
polaridade e a permutacao configuradas), entradas optoacopladas e os GPIOs
usados. Conectado a uma placa real, o mesmo painel mostra o estado lido dela.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QPlainTextEdit,
                               QPushButton, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..comm.board import BoardConfig, load_board_config
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
        self.setMinimumSize(QSize(450, 215))
        self.setMouseTracking(True)
        self._hover: int | None = None

    def sizeHint(self) -> QSize:
        return QSize(900, 430)

    # ------------------------------------------------------------ geometria
    def _transform(self) -> tuple[float, float, float]:
        s = min(self.width() / W, self.height() / H)
        return s, (self.width() - W * s) / 2, (self.height() - H * s) / 2

    def input_rect(self, k: int) -> QRectF:
        return QRectF(IN_X0 + k * IN_SLOT, 282, IN_SLOT - 4, 142)

    def _logical(self, pos) -> QPointF:
        s, ox, oy = self._transform()
        return QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)

    def _input_at(self, pos) -> int | None:
        p = self._logical(pos)
        return next((k for k in range(8) if self.input_rect(k).contains(p)), None)

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
            self._relay(p, k)
            self._input(p, k)
        self._esp32(p)
        self._registers(p)
        self._usb(p)
        self._power_and_modbus(p)
        color = QColor(STATE_COLORS.get(self.state, "#64748b"))   # estado informado pelo firmware
        badge = QRectF(14, 14, 128, 28)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(badge, 7, 7)
        self._text(p, badge, self.badge or f"FIRMWARE: {self.state}", 8, True, QColor("white"), Qt.AlignCenter)
        if on and self.oe_disabled:
            self._text(p, QRectF(300, 160, 300, 14), "/OE = 1: saidas do 74HC595 desabilitadas (reles soltos)",
                       7, True, QColor("#fde68a"))
        if not on:
            p.setBrush(QColor(15, 23, 42, 150))
            p.drawRoundedRect(QRectF(4, 4, W - 8, H - 8), 10, 10)
            self._text(p, QRectF(0, 0, W, H), "Placa desligada\nClique em 'Ligar'", 16, True,
                       QColor("white"), Qt.AlignCenter)
        p.end()

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
                ("74HC595  -> reles", 300.0, self._raw_levels(self.raw595) or cfg.shift_out_levels(self.outputs),
                 [f"Q0.{c}" for c in cfg.out_map], "nivel no pino"),
                ("74HC165  <- entradas", 300.0 + width + 12,
                 self._raw_levels(self.raw165) or cfg.shift_in_levels(self.inputs),
                 [f"I0.{c}" for c in cfg.in_map], "nivel lido")):
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
                       f"posicao 0..7: {sub} (0/1)", 6.5, False, QColor("#94a3b8"))

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
    """

    def __init__(self, session, device_panel, transfer, parent=None):
        super().__init__(parent)
        self.session = session
        self.device_panel = device_panel
        self.transfer = transfer
        self.config = load_board_config()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("Firmware do CLP (programa LADDER)", None)
        for name in list_sketches():
            self.mode.addItem(f"Exemplo Arduino: {name}", name)
        self.mode.setToolTip("O que roda na placa simulada: o firmware do CLP ou um exemplo de firmware/examples")
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
        self.tabs.addTab(self._config_tab(), "Configuracao")
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
        self._update_buttons()

    @property
    def sketch_mode(self) -> bool:
        return self.mode.currentData() is not None

    # ----------------------------------------------------------- abas
    def _config_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        note = QLabel(f"Lido de {self.config.source}. Em amarelo: valores marcados VERIFICAR no arquivo "
                      "(confirmar na placa real, docs/hardware-setup.md).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        v.addWidget(note)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Definicao", "Valor", "O que faz"])
        self.tree.setRootIsDecorated(True)
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        v.addWidget(self.tree, 1)
        open_btn = QPushButton("Abrir board_config.h")
        open_btn.clicked.connect(self._open_config)
        v.addWidget(open_btn, 0, Qt.AlignLeft)
        self._fill_config()
        return w

    def _fill_config(self) -> None:
        self.tree.clear()
        bold = QFont(self.font())
        bold.setBold(True)
        mono = mono_font(9)
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
        top = QTreeWidgetItem(["Reles: Qk -> 74HC595 -> nivel para ligar"])
        top.setFont(0, bold)
        top.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(top)
        level_on = "0 (ativo em 0)" if self.config.relay_active_low else "1"
        for k in range(8):
            pos = self.config.out_map.index(k) if k in self.config.out_map else k
            top.addChild(QTreeWidgetItem([f"Q0.{k} / K{k + 1}", f"pos {pos}", f"nivel {level_on} energiza o rele"]))
        top.setFirstColumnSpanned(True)
        top = QTreeWidgetItem(["Entradas: 74HC165 -> Ik"])
        top.setFont(0, bold)
        top.setFirstColumnSpanned(True)
        self.tree.addTopLevelItem(top)
        level_in = "0" if self.config.input_active_low else "1"
        for k in range(8):
            pos = self.config.in_map.index(k) if k in self.config.in_map else k
            top.addChild(QTreeWidgetItem([f"I0.{k}", f"pos {pos}", f"le {level_in} quando a entrada esta ativa"]))
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
        self.show_periodic = QCheckBox("Mostrar leituras periodicas (STATUS / READ_VARS)")
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
                                 else "liga sempre em STOP (padrao seguro)"))
        for lbl in (self.fw_device, self.fw_program, self.fw_scan, self.fw_uptime, self.fw_boot):
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Placa:", self.fw_device)
        form.addRow("Programa:", self.fw_program)
        form.addRow("Varredura:", self.fw_scan)
        form.addRow("Ligada ha:", self.fw_uptime)
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
        self.board.update()

    def on_connected(self, info) -> None:
        if self.sketch_mode:
            return
        self.board.powered = True
        self.board.virtual = self.session.is_virtual
        self.fw_device.setText(f"{info.hardware}, firmware {info.firmware}\nprotocolo LDP {info.protocol}, "
                               f"LDRB {info.fmt_major}.{info.fmt_minor}, E/S {info.n_inputs}/{info.n_outputs}, "
                               f"imagem ate {info.max_image} bytes")
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
        self.fw_scan.setText(f"{st.scan_count} varreduras a cada {st.scan_period_ms} ms\nexecucao "
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
        arrow = {"TX": "PC  -> ESP32", "RX": "PC <-  ESP32", "ERR": "PC <-  ESP32 ERRO",
                 "RETRY": "PC  -> ESP32 (repete)"}.get(direction, direction)
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
            self._log("--", "ERRO de compilacao:")
            self.log.appendPlainText(error)
            self._reset_board_view()
            self.board.badge = "ERRO DE COMPILACAO"
            self.board.update()
            self._update_buttons()
            return
        bridge = self._bridge
        try:
            self.sketch = SketchProcess(exe, bridge.serial.emit, bridge.board.emit, bridge.exited.emit)
        except OSError as exc:
            self._log("--", f"nao foi possivel iniciar o sketch: {exc}")
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
                                "(74HC595/74HC165 no nivel dos sinais)")
        self.fw_scan.setText("-")
        self.fw_uptime.setText("-")
        self._log("--", "sketch iniciado: saida da Serial abaixo")
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
            self._log("--", f"o sketch terminou (codigo {code})")
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
        sketch = self.sketch_mode
        for w in (self.send_edit, self.send_btn, self.send_newline):
            w.setEnabled(sketch and self.sketch is not None)
        self.show_periodic.setVisible(not sketch)
        self.serial_note.setText(
            "Saida da Serial do sketch (USB a 115200 bit/s). Digite abaixo para enviar comandos." if sketch else
            "Quadros do protocolo LDP trocados com a placa (o mesmo que trafega pela USB-serial).")
        if sketch:
            running = self.sketch is not None or self._building
            self.power_btn.setText("Desligar placa" if running else "Ligar (compilar e rodar)")
            for b in (self.transfer_btn, self.run_btn, self.stop_btn):
                b.setEnabled(False)
            self.reset_btn.setEnabled(self.sketch is not None)
            self.hint.setText("O exemplo roda no PC com o io_board.cpp do firmware; os registradores mostram os "
                              "niveis gerados pelo proprio codigo. Clique nas entradas IN1..IN8.")
            return
        dp = self.device_panel
        on = dp.connected
        st = dp.last_status.state if (on and dp.last_status) else None
        busy = on or self.session.auto_reconnect
        self.power_btn.setText("Desligar placa" if busy else "Ligar ESP32 virtual")
        self.transfer_btn.setEnabled(on)
        self.run_btn.setEnabled(on and st == DevState.STOP)
        self.stop_btn.setEnabled(on and st == DevState.RUN)
        self.reset_btn.setEnabled(on and self.session.is_virtual)
        if not on:
            self.hint.setText("A placa virtual roda o mesmo codigo C do firmware no PC e fala LDP com a IDE.")
        elif self.session.is_virtual:
            self.hint.setText("Placa virtual: clique nas entradas I0.x da placa para liga-las.")
        else:
            self.hint.setText("Placa real conectada: o desenho mostra o que o firmware comanda e le.")

    def theme_changed(self) -> None:
        self._fill_config()
        self.board.update()
