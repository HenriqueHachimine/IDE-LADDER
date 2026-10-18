"""Simulador da placa ESP32: a placa de 8 reles desenhada a partir de board_config.h.

A placa e "ligada" no dispositivo virtual, que executa o mesmo codigo C do
firmware (plc_core + ladder_vm) no PC e conversa com a IDE pelo protocolo
LDP, como a placa real faz pela USB. O desenho mostra o que o firmware
comanda: reles, niveis eletricos nos registradores 74HC595/74HC165 (com a
polaridade e a permutacao configuradas), entradas optoacopladas e os GPIOs
usados. Conectado a uma placa real, o mesmo painel mostra o estado lido dela.
"""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QDesktopServices, QFont, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QPlainTextEdit,
                               QPushButton, QSplitter, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
                               QWidget)

from ..comm.board import BoardConfig, load_board_config
from ..comm.protocol import FAULT_TEXT, DevState
from .fonts import mono_font, ui_font
from .theme import themed

W, H = 900.0, 430.0
RELAY_X0, SLOT = 300.0, 72.0
PERIODIC = {"STATUS", "READ_VARS", "READ_IO"}
VERIFY_BG = themed("#fef3c7", "#4a3a12")
STATE_COLORS = {"RUN": "#16a34a", "STOP": "#f59e0b", "FAULT": "#dc2626", "PROGRAM_LOADING": "#2563eb",
                "DESLIGADA": "#64748b"}


class BoardView(QWidget):
    """Desenho da placa. Coordenadas logicas W x H, escaladas para o widget."""
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
        return QRectF(RELAY_X0 + k * SLOT, 290, SLOT - 4, 124)

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
        cfg = self.config
        # placa de circuito impresso
        grad = QLinearGradient(0, 0, 0, H)
        grad.setColorAt(0, QColor("#1f6f43") if on else QColor("#3f4f45"))
        grad.setColorAt(1, QColor("#14532d") if on else QColor("#2f3a33"))
        p.setPen(QPen(QColor("#0b2e1a"), 2))
        p.setBrush(grad)
        p.drawRoundedRect(QRectF(4, 4, W - 8, H - 8), 14, 14)
        p.setBrush(QColor("#d6d3d1"))
        p.setPen(Qt.NoPen)
        for x, y in ((22, 22), (W - 22, 22), (22, H - 22), (W - 22, H - 22)):
            p.drawEllipse(QPointF(x, y), 7, 7)
        self._usb_and_power(p)
        self._esp32(p)
        self._registers(p)
        for k in range(8):
            self._relay(p, k)
            self._input(p, k)
        self._rs485(p)
        # estado do firmware (informado pelo dispositivo, nao e um LED da placa)
        color = QColor(STATE_COLORS.get(self.state, "#64748b"))
        badge = QRectF(44, 18, 196, 30)
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawRoundedRect(badge, 8, 8)
        self._text(p, badge, f"FIRMWARE: {self.state}", 10, True, QColor("white"), Qt.AlignCenter)
        if not on:
            p.setBrush(QColor(15, 23, 42, 150))
            p.drawRoundedRect(QRectF(4, 4, W - 8, H - 8), 14, 14)
            self._text(p, QRectF(0, 0, W, H), "Placa desligada\nClique em 'Ligar ESP32 virtual'", 16, True,
                       QColor("white"), Qt.AlignCenter)
        p.end()

    @staticmethod
    def _text(p, rect, text, size, bold=False, color=QColor("white"), align=Qt.AlignLeft | Qt.AlignVCenter,
              mono=False) -> None:
        p.setFont(mono_font(size, bold) if mono else ui_font(size, bold))
        p.setPen(color)
        p.drawText(rect, align, text)

    def _usb_and_power(self, p) -> None:
        p.setPen(QPen(QColor("#475569"), 1))
        p.setBrush(QColor("#cbd5e1"))
        p.drawRoundedRect(QRectF(4, 70, 34, 40), 5, 5)
        self._text(p, QRectF(4, 112, 60, 14), "USB-C", 7, True)
        self._text(p, QRectF(4, 126, 120, 14), f"LDP {self.config.value('LDP_BAUD', 115200)} bit/s", 7)
        self._led(p, QPointF(56, 80), self.powered, QColor("#ef4444"))
        self._text(p, QRectF(64, 73, 40, 14), "PWR", 7, True)

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

    def _esp32(self, p) -> None:
        mod = QRectF(70, 150, 150, 190)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#1e293b"))
        p.drawRect(mod)
        p.setPen(QPen(QColor("#fbbf24"), 2))                      # antena impressa
        x, y = mod.left() + 12, mod.top() + 10
        pts = []
        for k in range(9):
            pts += [QPointF(x + k * 14, y), QPointF(x + k * 14, y + 24), QPointF(x + k * 14 + 7, y + 24),
                    QPointF(x + k * 14 + 7, y)]
        p.drawPolyline(pts)
        can = QRectF(mod.left() + 10, mod.top() + 44, mod.width() - 20, mod.height() - 54)
        grad = QLinearGradient(can.topLeft(), can.bottomRight())
        grad.setColorAt(0, QColor("#e5e7eb"))
        grad.setColorAt(1, QColor("#9ca3af"))
        p.setPen(QPen(QColor("#6b7280"), 1))
        p.setBrush(grad)
        p.drawRect(can)
        self._text(p, can.adjusted(6, 6, -6, -6), "ESP32-WROOM-32\n\nfirmware CLP\n" +
                   f"v{self.config.value('FW_VERSION', '?')}", 9, True, QColor("#1f2937"),
                   Qt.AlignHCenter | Qt.AlignTop)
        # GPIOs usados (serigrafia)
        cfg = self.config
        pins = [("PIN_595_SER", "SER  -> 595"), ("PIN_SR_CLK", "CLK  -> 595/165"),
                ("PIN_SR_LATCH", "LATCH-> 595/165"), ("PIN_595_OE", "/OE  -> 595"),
                ("PIN_165_QH", "QH   <- 165"), ("PIN_RS485_RX", "RX   <- RS-485"),
                ("PIN_RS485_TX", "TX   -> RS-485"), ("PIN_RS485_DE", "DE   -> RS-485")]
        y = 152.0
        for name, text in pins:
            gpio = cfg.value(name)
            if gpio is None:
                continue
            item = next(i for i in cfg.items if i.name == name)
            color = QColor("#fde68a") if item.verify else QColor("#e2e8f0")
            p.setPen(QPen(QColor("#a7f3d0"), 1))
            p.drawLine(QPointF(mod.right(), y + 6), QPointF(mod.right() + 6, y + 6))
            self._text(p, QRectF(mod.right() + 8, y, 160, 14), f"GPIO{gpio:<2} {text}", 7, False, color,
                       mono=True)
            y += 16

    def _registers(self, p) -> None:
        cfg = self.config
        for title, x, levels, labels, sub in (
                ("74HC595  saidas", RELAY_X0, cfg.shift_out_levels(self.outputs),
                 [f"Q0.{c}" for c in cfg.out_map], "nivel no pino (0/1)"),
                ("74HC165  entradas", RELAY_X0 + 4 * SLOT + 2, cfg.shift_in_levels(self.inputs),
                 [f"I0.{c}" for c in cfg.in_map], "nivel lido (0/1)")):
            chip = QRectF(x, 196, 4 * SLOT - 6, 70)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#111827"))
            p.drawRoundedRect(chip, 4, 4)
            p.setBrush(QColor("#6b7280"))
            for k in range(8):                                     # perninhas
                px = chip.left() + 10 + k * (chip.width() - 20) / 7
                p.drawRect(QRectF(px - 2, chip.top() - 5, 4, 5))
                p.drawRect(QRectF(px - 2, chip.bottom(), 4, 5))
            self._text(p, QRectF(chip.left() + 6, chip.top() + 2, chip.width(), 14), title, 7.5, True)
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
                       f"posicao 0..7 -> {sub}", 6.5, False, QColor("#94a3b8"))

    def _relay(self, p, k: int) -> None:
        x0 = RELAY_X0 + k * SLOT
        on = self.powered and bool(self.outputs >> k & 1)
        # borne NO / COM / NC
        term = QRectF(x0 + 4, 14, SLOT - 12, 22)
        p.setPen(QPen(QColor("#065f46"), 1))
        p.setBrush(QColor("#10b981"))
        p.drawRect(term)
        for j, label in enumerate(("NO", "C", "NC")):
            c = QPointF(term.left() + 10 + j * (term.width() - 20) / 2, term.center().y())
            p.setBrush(QColor("#9ca3af"))
            p.drawEllipse(c, 6, 6)
            self._text(p, QRectF(c.x() - 12, term.bottom() + 1, 24, 10), label, 6, True, QColor("#d1fae5"),
                       Qt.AlignCenter)
        # rele
        body = QRectF(x0 + 6, 50, SLOT - 16, 64)
        p.setPen(QPen(QColor("#1e3a8a"), 1))
        p.setBrush(QColor("#2563eb"))
        p.drawRoundedRect(body, 3, 3)
        self._text(p, QRectF(body.left(), body.top() + 2, body.width(), 12), f"K{k + 1}", 8, True,
                   QColor("white"), Qt.AlignCenter)
        com = QPointF(body.center().x(), body.bottom() - 10)
        no = QPointF(body.left() + 10, body.top() + 22)
        nc = QPointF(body.right() - 10, body.top() + 22)
        p.setPen(QPen(QColor("#e0e7ff"), 1.5))
        for pt in (no, nc):
            p.drawLine(QPointF(pt.x(), pt.y() - 6), pt)
        p.setPen(QPen(QColor("#fde047") if on else QColor("#e0e7ff"), 2.4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(com, no if on else nc)                        # contato movel
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#e0e7ff"))
        p.drawEllipse(com, 2.5, 2.5)
        self._led(p, QPointF(x0 + SLOT / 2 - 2, 128), on, QColor("#ef4444"), 4.5)
        name = self.names.get(f"Q0.{k}", "")
        self._text(p, QRectF(x0, 138, SLOT - 4, 14), f"Q0.{k}", 8, True, QColor("#fde68a") if on else
                   QColor("white"), Qt.AlignCenter)
        self._text(p, QRectF(x0 - 2, 152, SLOT, 12), name[:12], 6.5, False, QColor("#d1fae5"), Qt.AlignCenter)
        pos = self.config.out_map.index(k) if k in self.config.out_map else k
        self._text(p, QRectF(x0, 164, SLOT - 4, 12), f"595 pos {pos}", 6.5, False, QColor("#94a3b8"),
                   Qt.AlignCenter)

    def _input(self, p, k: int) -> None:
        r = self.input_rect(k)
        active = self.powered and bool(self.inputs >> k & 1)
        if self._hover == k and self.powered and self.virtual:
            p.setPen(QPen(QColor("#fde68a"), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 6, 6)
        pos = self.config.in_map.index(k) if k in self.config.in_map else k
        self._text(p, QRectF(r.left(), r.top() + 2, r.width(), 12), f"165 pos {pos}", 6.5, False,
                   QColor("#94a3b8"), Qt.AlignCenter)
        opto = QRectF(r.center().x() - 16, r.top() + 22, 32, 20)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#f8fafc"))
        p.drawRect(opto)
        self._text(p, opto, "PC817", 6, True, QColor("#111827"), Qt.AlignCenter)
        self._led(p, QPointF(r.center().x(), r.top() + 54), active, QColor("#22c55e"), 4.5)
        self._text(p, QRectF(r.left(), r.top() + 62, r.width(), 14), f"I0.{k}", 8, True,
                   QColor("#bbf7d0") if active else QColor("white"), Qt.AlignCenter)
        self._text(p, QRectF(r.left() - 2, r.top() + 76, r.width() + 4, 12), self.names.get(f"I0.{k}", "")[:12],
                   6.5, False, QColor("#d1fae5"), Qt.AlignCenter)
        term = QRectF(r.left() + 12, r.bottom() - 26, r.width() - 24, 22)
        p.setPen(QPen(QColor("#065f46"), 1))
        p.setBrush(QColor("#10b981"))
        p.drawRect(term)
        for j in range(2):
            p.setBrush(QColor("#9ca3af"))
            p.drawEllipse(QPointF(term.left() + 10 + j * (term.width() - 20), term.center().y()), 6, 6)

    def _rs485(self, p) -> None:
        box = QRectF(70, 358, 190, 52)
        chip = QRectF(box.left(), box.top() + 6, 54, 30)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#111827"))
        p.drawRect(chip)
        self._text(p, chip, "RS-485", 7, True, QColor("white"), Qt.AlignCenter)
        cfg = self.config
        enabled = cfg.value("MODBUS_ENABLED", 0)
        txt = (f"Modbus RTU end. {cfg.value('MODBUS_ADDRESS', '?')}\n{cfg.value('MODBUS_BAUD', '?')} bit/s"
               if enabled else "Modbus desabilitado")
        self._text(p, QRectF(chip.right() + 6, box.top() + 2, 140, 36), txt, 7, False, QColor("#e2e8f0"))
        term = QRectF(box.left(), box.bottom() - 10, 70, 14)
        self._text(p, term, "A  B  GND", 6.5, True, QColor("#d1fae5"))


class Esp32Panel(QWidget):
    """Painel com a placa, a configuracao do firmware e o monitor serial."""

    def __init__(self, session, device_panel, transfer, parent=None):
        super().__init__(parent)
        self.session = session
        self.device_panel = device_panel
        self.transfer = transfer
        self.config = load_board_config()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        row = QHBoxLayout()
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
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        row.addWidget(self.hint, 1)
        layout.addLayout(row)

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
        self._update_buttons()

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
        note = QLabel("Quadros do protocolo LDP trocados com a placa (o mesmo que trafega pela USB-serial).")
        note.setWordWrap(True)
        note.setObjectName("muted")
        v.addWidget(note)
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
        dp = self.device_panel
        if dp.connected or self.session.auto_reconnect:
            dp.toggle_connection()
        else:
            dp.kind.setCurrentIndex(1)                       # dispositivo virtual
            self._log("--", "ligando a placa virtual (firmware compilado para o PC)...")
            dp.toggle_connection()
        self._update_buttons()

    def reset_board(self) -> None:
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
        self.board.powered = False
        self.board.state = "DESLIGADA"
        self._log("--", f"desconectada: {reason}")
        self._update_buttons()
        self.board.update()

    def on_status(self, st) -> None:
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
        self.board.outputs = snap.q_commanded
        self.board.inputs = snap.inputs
        self.board.update()

    def on_traffic(self, direction: str, cmd: str, seq: int, nbytes: int) -> None:
        if cmd in PERIODIC and not self.show_periodic.isChecked():
            return
        arrow = {"TX": "PC  -> ESP32", "RX": "PC <-  ESP32", "ERR": "PC <-  ESP32 ERRO",
                 "RETRY": "PC  -> ESP32 (repete)"}.get(direction, direction)
        self._log(arrow, f"{cmd:<14} seq {seq:3d}  {nbytes} B")

    def _log(self, who: str, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log.appendPlainText(f"{stamp}  {who:<22} {text}")

    def _update_buttons(self) -> None:
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
