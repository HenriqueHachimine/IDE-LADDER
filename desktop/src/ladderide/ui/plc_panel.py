"""Painel "CLP real" (aba Processo): o programa da IDE comandando um WEG CLIC-02 ou um Omron CP1E.

A esquerda, o CLP desenhado como o equipamento (ui/plc_faceplate.py) com as entradas
e saidas ao vivo; a direita, a porta serial, o protocolo e os botoes Conectar, Testar, RUN/STOP e "Transmitir e executar" (compila, conecta
e poe a simulacao para rodar com as E/S do CLP). Protocolos em comm/plc_serial.py,
troca de dados em sim/plc_link.py.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QScrollArea, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..comm.plc_serial import BAUDRATES, DRIVERS, FRAMINGS, ponte_clic
from ..comm.transport import list_serial_ports
from ..sim.plc_link import PlcLink, PlcLinkConfig, plc_command, probe
from . import theme
from .icons import make_icon
from .plc_faceplate import PlcFaceplate

GREEN, AMBER, GRAY, RED = "#15803d", "#b45309", "#64748b", "#dc2626"
HELP = {
    "clic02": ("<b>WEG CLIC-02</b> (Modbus RTU pela RS-485 dos modelos 20VR-D/20VT-D ou do módulo "
               "CLW-02/MBUS 3RD; conversor USB/RS-485 no PC):<ol style='margin-left:-20px'>"
               "<li>No CLIC-02: <i>CONFIG</i>, <b>REMOTE I/O = N</b> e <b>ID</b> de 1 a 99 (o mesmo daqui). "
               "Padrão da porta: 38400, 8N2.</li>"
               "<li>Grave no CLIC-02, uma vez, pelo Clic02 Edit, o <b>programa ponte</b>: uma linha por saída, "
               "<b>{ponte}</b>. A IDE escreve M01 a M08 e o CLIC-02 copia para as saídas.</li>"
               "<li>Clique <b>Transmitir e executar</b>: a IDE põe o CLIC-02 em RUN, lê I01... e comanda as "
               "saídas com o seu programa LADDER.</li></ol>"),
    "hostlink": ("<b>Omron CP1E</b> (Host Link pela RS-232C dos modelos S e N; cabo RS-232C ou conversor "
                 "USB/RS-232C):<ol style='margin-left:-20px'>"
                 "<li>No CX-Programmer, Configurações do CLP, porta RS-232C: modo <b>Host Link</b>, "
                 "9600, 7-2-E, unidade 0 (os padrões de fábrica).</li>"
                 "<li>Deixe o CP1E <b>sem programa</b> (ou com um que não use CIO 100/101): a IDE escreve as "
                 "saídas direto em CIO 100.00...</li>"
                 "<li>Clique <b>Transmitir e executar</b>: a IDE põe o CP1E em MONITOR, lê CIO 0/1 e "
                 "comanda CIO 100/101 com o seu programa LADDER.</li></ol>"),
}
NO_LINK = ("sem ligação com CLP real: escolha um WEG CLIC-02 ou um Omron CP1E com RS-232C em "
           "Programa &gt; Propriedades, ou o protocolo ao lado.")
PILLS = {"ok": ("OK_BG", "OK_FG"), "warn": ("WARN_BG", "WARN_FG"), "err": ("ERR_BG", "ERR_FG"),
         "idle": ("BADGE_BG", "BADGE_FG")}


class PlcPanel(QWidget):
    linkChanged = Signal(object)          # PlcLink conectado ou None
    transferRequested = Signal()          # compilar, conectar e executar
    configChanged = Signal(object)
    expansionsRequested = Signal()        # abrir o dialogo de modulos de expansao
    _probed = Signal(bool, str)
    _commanded = Signal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.link: PlcLink | None = None
        self.line_factory = None              # testes: serial falsa (ver sim.plc_link.open_driver)
        self.n_in, self.n_out = 8, 4
        self.modules: list = []               # model.expansions.Expansion do projeto, em ordem
        self.controller_link = ""
        self._busy = False
        self._message = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 4)
        outer.setSpacing(6)
        # barra: controlador do projeto, selo de estado e as acoes principais
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.header = QLabel()
        self.header.setTextFormat(Qt.RichText)
        self.header.setWordWrap(True)
        bar.addWidget(self.header, 1)
        self.pill = QLabel()
        self.pill.setAlignment(Qt.AlignCenter)
        bar.addWidget(self.pill, 0, Qt.AlignVCenter)
        bar.addSpacing(6)
        self.test_btn = QPushButton("Testar")
        self.test_btn.setToolTip("Identifica o CLP e lê as entradas, sem escrever nada")
        self.test_btn.clicked.connect(self.test_link)
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.setToolTip("Liga a troca de E/S com o CLP (sem iniciar a simulação)")
        self.connect_btn.clicked.connect(self.toggle_link)
        self.transfer_btn = QPushButton(make_icon("transfer"), "  Transmitir e executar")
        self.transfer_btn.setObjectName("primary")
        self.transfer_btn.setToolTip("Compila o programa, conecta ao CLP e executa: as entradas vêm do CLP e "
                                     "as saídas do programa vão para o CLP")
        self.transfer_btn.clicked.connect(self.transferRequested.emit)
        for btn in (self.test_btn, self.connect_btn, self.transfer_btn):
            bar.addWidget(btn)
        outer.addLayout(bar)

        body = QHBoxLayout()
        body.setSpacing(10)
        self.face = PlcFaceplate()
        body.addWidget(self.face, 1)

        side = QWidget()
        right = QVBoxLayout(side)
        right.setContentsMargins(0, 0, 4, 0)
        right.setSpacing(8)
        box = QGroupBox("Comunicação")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        def caption(text: str, row: int, col: int, span: int = 1) -> None:
            label = QLabel(text)
            label.setObjectName("muted")
            grid.addWidget(label, row, col, 1, span)
            grid.setRowMinimumHeight(row, 18)
        self.driver = QComboBox()
        for key, (label, _f) in DRIVERS.items():
            self.driver.addItem(label, key)
        self.driver.currentIndexChanged.connect(self._driver_changed)
        caption("Protocolo", 0, 0, 2)
        grid.addWidget(self.driver, 1, 0, 1, 2)
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.lineEdit().setPlaceholderText("COM3, /dev/ttyUSB0...")
        self.refresh_btn = QToolButton()
        self.refresh_btn.setText("↻")
        self.refresh_btn.setToolTip("Procura de novo as portas seriais (cabo USB/RS-485 ou USB/RS-232C)")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        caption("Porta serial", 2, 0, 2)
        port_row = QHBoxLayout()
        port_row.setSpacing(4)
        port_row.addWidget(self.port, 1)
        port_row.addWidget(self.refresh_btn)
        grid.addLayout(port_row, 3, 0, 1, 2)
        self.baud = QComboBox()
        for b in BAUDRATES:
            self.baud.addItem(str(b), b)
        self.framing = QComboBox()
        for f in FRAMINGS:
            self.framing.addItem(f, f)
        self.framing.setToolTip("Bits de dados, paridade (N/E/O) e bits de parada")
        caption("Velocidade", 4, 0)
        caption("Formato", 4, 1)
        grid.addWidget(self.baud, 5, 0)
        grid.addWidget(self.framing, 5, 1)
        self.unit = QSpinBox()
        self.poll = QSpinBox()
        self.poll.setRange(20, 1000)
        self.poll.setSuffix(" ms")
        self.poll.setToolTip("Intervalo entre duas trocas (leitura das entradas e escrita das saídas)")
        caption("ID / unidade", 6, 0)
        caption("Ciclo de troca", 6, 1)
        grid.addWidget(self.unit, 7, 0)
        grid.addWidget(self.poll, 7, 1)
        self.defaults_btn = QPushButton("Padrão de fábrica")
        self.defaults_btn.setToolTip("Velocidade, formato e endereço de fábrica do CLP escolhido")
        self.defaults_btn.clicked.connect(self._use_defaults)
        grid.setRowMinimumHeight(8, 8)
        grid.addWidget(self.defaults_btn, 9, 0, 1, 2)
        right.addWidget(box)

        modes = QGroupBox("Modo do CLP")
        row = QHBoxLayout(modes)
        row.setSpacing(6)
        self.run_btn = QPushButton(make_icon("run"), " RUN")
        self.run_btn.setToolTip("Põe o CLP em RUN (CP1E: MONITOR)")
        self.run_btn.clicked.connect(lambda: self.set_plc_run(True))
        self.stop_btn = QPushButton(make_icon("stop"), " STOP")
        self.stop_btn.setToolTip("Põe o CLP em STOP (CP1E: PROGRAM): as saídas desligam")
        self.stop_btn.clicked.connect(lambda: self.set_plc_run(False))
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        right.addWidget(modes)

        exp = QGroupBox("Módulos de expansão")
        exp_box = QVBoxLayout(exp)
        self.modules_label = QLabel()
        self.modules_label.setWordWrap(True)
        self.modules_label.setObjectName("muted")
        exp_box.addWidget(self.modules_label)
        self.modules_btn = QPushButton("Encaixar módulos...")
        self.modules_btn.setToolTip("Acrescenta módulos de E/S ao CLP do projeto (Programa > Módulos de expansão)")
        self.modules_btn.clicked.connect(self.expansionsRequested.emit)
        exp_box.addWidget(self.modules_btn)
        right.addWidget(exp)

        self.help_btn = QToolButton()
        self.help_btn.setText("Como ligar o CLP")
        self.help_btn.setCheckable(True)
        self.help_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.help_btn.setArrowType(Qt.RightArrow)
        self.help_btn.toggled.connect(self._toggle_help)
        right.addWidget(self.help_btn)
        self.help = QLabel()
        self.help.setWordWrap(True)
        self.help.setTextFormat(Qt.RichText)
        self.help.setObjectName("muted")
        self.help.setVisible(False)
        right.addWidget(self.help)
        right.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(300)
        for combo in (self.driver, self.port, self.baud, self.framing):
            combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(5)
        body.addWidget(scroll)
        outer.addLayout(body, 1)

        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setObjectName("muted")
        outer.addWidget(self.status)
        self._pill_state = ("Desconectado", "idle")

        self._probed.connect(self._on_probed)
        self._commanded.connect(self._on_probed)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.refresh_status)
        self.refresh_ports()
        self.set_config(PlcLinkConfig())
        self._update_header(None)

    # ------------------------------------------------------------ config
    def config(self) -> PlcLinkConfig:
        return PlcLinkConfig(driver=self.driver.currentData(), port=self.port_name(),
                             baudrate=int(self.baud.currentData()), framing=self.framing.currentData(),
                             unit=self.unit.value(), n_inputs=self.n_in, n_outputs=self.n_out,
                             poll_ms=self.poll.value(), modules=[[m.inputs, m.outputs] for m in self.modules])

    def set_config(self, cfg: PlcLinkConfig) -> None:
        self.driver.blockSignals(True)
        self.driver.setCurrentIndex(max(0, self.driver.findData(cfg.driver)))
        self.driver.blockSignals(False)
        self._unit_range()
        if cfg.port:
            i = self.port.findData(cfg.port)
            if i >= 0:
                self.port.setCurrentIndex(i)
            else:
                self.port.setEditText(cfg.port)
        self.baud.setCurrentIndex(max(0, self.baud.findData(cfg.baudrate)))
        self.framing.setCurrentIndex(max(0, self.framing.findData(cfg.framing)))
        self.unit.setValue(cfg.unit)
        self.poll.setValue(cfg.poll_ms)
        self._driver_visuals()

    def _unit_range(self) -> None:
        clic = self.driver.currentData() == "clic02"
        self.unit.setRange(*((1, 99) if clic else (0, 31)))
        self.unit.setToolTip("ID do CLIC-02 (CONFIG > ID), 1 a 99" if clic else
                             "Número da unidade Host Link do CP1E (Configurações do CLP), 0 a 31")

    def _driver_changed(self) -> None:
        self._unit_range()
        self._use_defaults()

    def _use_defaults(self) -> None:
        cfg = self.config()
        cfg.use_defaults(self.driver.currentData())
        self.baud.setCurrentIndex(max(0, self.baud.findData(cfg.baudrate)))
        self.framing.setCurrentIndex(max(0, self.framing.findData(cfg.framing)))
        self.unit.setValue(cfg.unit)
        self._driver_visuals()
        self.configChanged.emit(self.config())

    def _driver_visuals(self) -> None:
        key = self.driver.currentData()
        exp_out = sum(m.outputs for m in self.modules)
        bridge = ", ".join(ponte_clic(self.n_out - exp_out, exp_out)) if key == "clic02" else ""
        self.help.setText(HELP[key].format(ponte=bridge))
        self.face.set_state(style_key=key, unit=self.unit.value())

    def refresh_ports(self) -> None:
        current = self.port.currentText().split(" ")[0]
        self.port.clear()
        for device, desc in list_serial_ports():
            self.port.addItem(f"{device}  {desc}" if desc and desc != "n/a" else device, device)
        if current:
            i = self.port.findData(current)
            if i >= 0:
                self.port.setCurrentIndex(i)
            else:
                self.port.setEditText(current)

    def port_name(self) -> str:
        parts = self.port.currentText().split()     # o texto manda: COM10 digitado com COM1 na lista
        return parts[0] if parts else ""

    # ------------------------------------------------------------ projeto
    def set_project(self, n_inputs: int, n_outputs: int, controller=None, modules=None) -> None:
        """E/S, controlador e modulos de expansao do projeto: o protocolo segue o controlador."""
        self.n_in, self.n_out = n_inputs, n_outputs
        self.modules = list(modules or [])
        limit = getattr(controller, "max_expansions", 0) if controller is not None else 0
        if self.modules:
            self.modules_label.setText(", ".join(m.catalog for m in self.modules)
                                       + f" ({len(self.modules)} de {limit}).")
        else:
            self.modules_label.setText(f"Nenhum módulo. Este CPU aceita até {limit}." if limit else
                                       "O controlador do projeto não aceita módulos de expansão.")
        self.accepts_modules = bool(limit)
        self.modules_btn.setEnabled(self.accepts_modules and self.link is None)
        link = getattr(controller, "link", "") if controller is not None else ""
        if link and link != self.controller_link and self.link is None:
            self.driver.setCurrentIndex(max(0, self.driver.findData(link)))
        if self.link is None:                       # conectado: o protocolo so muda ao desconectar
            self.controller_link = link
        self.face.set_state(n_in=n_inputs, n_out=n_outputs,
                            catalog=getattr(controller, "catalog", "") if controller is not None else "",
                            modules=[(m.catalog, m.inputs, m.outputs) for m in self.modules])
        if self.link is not None:                   # ajusta a troca sem desconectar
            self.link.config.n_inputs, self.link.config.n_outputs = n_inputs, n_outputs
        self._update_header(controller)
        self._driver_visuals()

    def _update_header(self, controller) -> None:
        sub = theme.colors["SUBTLE"]
        if controller is not None and getattr(controller, "link", "") in DRIVERS:
            protocol = DRIVERS[controller.link][0].split("(")[-1].rstrip(")")
            self.header.setText(f"<span style='font-size:13pt; font-weight:600'>{controller.name}</span><br>"
                                f"<span style='color:{sub}'>{self.n_in} entradas · {self.n_out} saídas · "
                                f"{protocol}</span>")
            self.header.setToolTip(f"Portas: {controller.ports}")
        else:
            name = controller.name if controller is not None else "Projeto"
            self.header.setText(f"<span style='font-size:13pt; font-weight:600'>{name}</span><br>"
                                f"<span style='color:{theme.colors['WARN']}'>{NO_LINK}</span>")
        self._set_pill(*self._pill_state)

    def _set_pill(self, text: str, kind: str) -> None:
        """Selo de estado ao lado dos botoes (cores do tema)."""
        self._pill_state = (text, kind)
        bg, fg = (theme.colors[k] for k in PILLS[kind])
        self.pill.setText(f"●  {text}")
        self.pill.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:11px; padding:3px 12px; "
                                "font-weight:600;")

    def _toggle_help(self, on: bool) -> None:
        self.help.setVisible(on)
        self.help_btn.setArrowType(Qt.DownArrow if on else Qt.RightArrow)

    # ------------------------------------------------------------ ligacao
    @property
    def linked(self) -> bool:
        return self.link is not None

    def toggle_link(self) -> None:
        if self.link is None:
            self.connect_link()
        else:
            self.disconnect_link()

    def connect_link(self) -> bool:
        if self.link is not None:
            return True
        cfg = self.config()
        errors = cfg.validate()
        if errors:
            self._show("; ".join(errors).capitalize() + ".", RED)
            return False
        self.link = PlcLink(cfg, self.line_factory)
        self.link.start()
        self._message = ""
        self.timer.start()
        self._set_editing(False)
        self.configChanged.emit(cfg)
        self.linkChanged.emit(self.link)
        self.refresh_status()
        return True

    def disconnect_link(self) -> None:
        if self.link is None:
            return
        link, self.link = self.link, None
        link.stop()                                 # desliga as saidas do CLP antes de fechar
        self.timer.stop()
        self._set_editing(True)
        self.face.set_state(connected=False, inputs=0, outputs=0, mode="", error=False)
        self.linkChanged.emit(None)
        self._set_pill("Desconectado", "idle")
        self._show("Desconectado. As saídas do CLP foram desligadas.", GRAY)

    def _set_editing(self, editing: bool) -> None:
        for w in (self.driver, self.port, self.refresh_btn, self.baud, self.framing, self.unit, self.poll,
                  self.defaults_btn, self.test_btn):
            w.setEnabled(editing)
        self.modules_btn.setEnabled(editing and getattr(self, "accepts_modules", False))
        self.connect_btn.setText("Conectar" if editing else "Desconectar")
        self.transfer_btn.setEnabled(editing)

    def test_link(self) -> None:
        if self._busy:
            return
        cfg = self.config()
        errors = cfg.validate()
        if errors:
            self._show("; ".join(errors).capitalize() + ".", RED)
            return
        self._busy = True
        self._set_pill("Testando", "warn")
        self._show(f"Testando {cfg.port}...", AMBER)
        threading.Thread(target=lambda: self._probed.emit(*probe(cfg, self.line_factory)), daemon=True).start()

    def set_plc_run(self, run: bool) -> None:
        if self.link is not None:
            self.link.request_run(run)
            self._show(f"{'RUN' if run else 'STOP'} enviado ao CLP.", GRAY)
            return
        if self._busy:
            return
        cfg = self.config()
        if not cfg.port:
            self._show("Escolha a porta serial do cabo do CLP.", RED)
            return
        self._busy = True

        def work() -> None:
            try:
                mode = plc_command(cfg, lambda d: (d.set_run(run), d.mode())[1], self.line_factory)
                self._commanded.emit(True, f"CLP em {mode}.")
            except Exception as exc:                # PlcError ou falha de porta
                self._commanded.emit(False, str(exc))
        threading.Thread(target=work, daemon=True).start()

    def _on_probed(self, ok: bool, text: str) -> None:
        self._busy = False
        if self.link is None:
            self._set_pill("CLP respondeu" if ok else "Sem resposta", "ok" if ok else "err")
        self._show(text, GREEN if ok else RED)

    def _show(self, text: str, color: str) -> None:
        self._message = text
        self.status.setText(f"<span style='color:{color}'>{text}</span>")

    def refresh_status(self) -> None:
        link = self.link
        if link is None:
            return
        self.face.set_state(connected=link.connected, inputs=link.input_bits() if link.connected else 0,
                            outputs=link.plc_outputs if link.connected else 0, mode=link.plc_mode,
                            error=bool(link.error), unit=link.config.unit)
        self.face.update()                          # relogio do display do CLIC-02
        if link.connected:
            self._set_pill(f"Conectado · {link.plc_mode}" if link.plc_mode else "Conectado", "ok")
            self.status.setText(f"<span style='color:{GREEN}'>Conectado: {link.model}, modo {link.plc_mode}, "
                                f"ciclo {link.cycle_ms:.0f} ms, {link.cycles} trocas"
                                f"{f', {link.drops} queda(s)' if link.drops else ''}.</span>")
        else:
            self._set_pill("Sem resposta" if link.error else "Conectando", "err" if link.error else "warn")
            self.status.setText(f"<span style='color:{AMBER}'>Conectando a {link.config.port}..."
                                f"{f' {link.error}' if link.error else ''}</span>")

    def status_text(self) -> str:
        link = self.link
        return "" if link is None else "conectado" if link.connected else "conectando"

    def shutdown(self) -> None:
        if self.link is not None:
            self.link.stop()
            self.link = None
