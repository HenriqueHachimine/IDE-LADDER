"""Painel da ligacao com o Factory IO (driver Modbus TCP/IP Server).

Layout espelhando a janela do driver no Factory IO: sensores (Inputs e Input Regs)
a esquerda, atuadores (Coils e Holding Regs) a direita, cada porta com o endereco
no CLP, o simbolo (editavel: duplo clique) e o valor ao vivo. A conexao fica numa barra compacta em cima
(IP, porta, Slave ID, Conectar, Testar) e as opcoes do driver num dialogo ("Configurar driver..."), na
mesma ordem e com os mesmos nomes da pagina de configuracao do driver no Factory IO
(docs.factoryio.com/manual/drivers/modbus-server).
"""
from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
                               QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.asm import format_operand
from ..core.isa import Area
from ..sim.factoryio import (MAX_BITS, MAX_REGS, REGISTER_TABLES, SENSOR_TABLES, FactoryIOConfig, FactoryIOLink,
                             probe)

DRIVER_HINT = ("No Factory IO: File > Drivers > Modbus TCP/IP Server. Use o IP e o Slave ID mostrados no topo "
               "do driver e as mesmas opções e quantidades (Configurar driver...). Coloque a cena em RUN e "
               "conecte. Enquanto conectado, a simulação fica em 1x (o Factory IO roda em tempo real).")
STEPS = ("<b>No Factory IO</b>: <i>File &gt; Drivers</i>, escolha <b>Modbus TCP/IP Server</b> e clique em "
         "<b>Configuration</b>. Preencha aqui os mesmos valores, campo a campo:"
         "<ol style='margin-left:-20px'>"
         "<li><b>Network adapter</b>: o IP que aparece em <b>Host</b> vai no campo IP da IDE "
         "(adaptador <i>Loopback</i> = 127.0.0.1, Factory IO no mesmo PC).</li>"
         "<li><b>Port</b> e <b>Slave ID</b>: os mesmos dos dois lados (porta padrão 502).</li>"
         "<li><b>Write Digital</b> / <b>Write Register</b>: onde o Factory IO escreve os sensores.</li>"
         "<li><b>Read Digital</b> = Coils e <b>Read Register</b> = Holding Registers (únicos que a IDE "
         "consegue escrever).</li>"
         "<li><b>Digital Inputs/Outputs</b> e <b>Register Inputs/Outputs</b>: mesmo Offset e Count.</li>"
         "</ol>")
PROBE_HINT = ("\nConfira o IP (Host do driver, depende do Network adapter), a Port, o Slave ID e se a cena "
              "está em RUN.")
GREEN, AMBER, GRAY, RED = "#15803d", "#b45309", "#64748b", "#dc2626"


def _spin(lo: int, hi: int, tip: str, prefix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setToolTip(tip)
    if prefix:
        s.setPrefix(prefix)
    return s


def _port_table(tip: str) -> QTableWidget:
    t = QTableWidget(0, 4)
    t.setHorizontalHeaderLabels(["Porta", "CLP", "Símbolo", "Valor"])
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(22)
    t.setEditTriggers(QTableWidget.DoubleClicked | QTableWidget.EditKeyPressed)   # so a coluna Simbolo
    t.setSelectionMode(QTableWidget.SingleSelection)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    h.setSectionResizeMode(2, QHeaderView.Stretch)
    t.setToolTip(tip)
    return t


class PortsDialog(QDialog):
    """Opcoes do driver na ordem da pagina de configuracao do Factory IO (os campos pertencem ao painel)."""

    def __init__(self, panel: "FactoryIOPanel"):
        super().__init__(panel)
        self.panel = panel
        self.setWindowTitle("Factory IO - configuração do driver Modbus TCP/IP Server")
        layout = QVBoxLayout(self)
        steps = QLabel(STEPS)
        steps.setWordWrap(True)
        steps.setObjectName("muted")
        layout.addWidget(steps)

        columns = QHBoxLayout()                       # duas colunas: cabe em telas de 768 px de altura
        left, right = QVBoxLayout(), QVBoxLayout()
        columns.addLayout(left, 1)
        columns.addLayout(right, 1)
        server = QGroupBox("Servidor (topo do driver)")
        form = QFormLayout(server)
        form.addRow("Host, Port, Slave ID:", QLabel("na barra do painel"))
        form.addRow(panel.auto_connect)
        left.addWidget(server)

        options = QGroupBox("Opções do driver")
        form = QFormLayout(options)
        form.addRow("Write Digital (sensores):", panel.sensor_table)
        form.addRow("Read Digital (atuadores):", panel.read_digital)
        form.addRow("Write Register (sensores):", panel.register_table)
        form.addRow("Read Register (atuadores):", panel.read_register)
        form.addRow("Scale:", panel.scale)
        left.addWidget(options)
        left.addStretch(1)

        ports = QGroupBox(f"Portas (até {MAX_BITS} digitais e {MAX_REGS} registradores de cada lado)")
        grid = QGridLayout(ports)
        for col, text in enumerate(("", "Offset", "Count", "No CLP")):
            grid.addWidget(QLabel(f"<b>{text}</b>"), 0, col)
        rows = (("Digital Inputs (sensores)", panel.sensor_offset, panel.n_sensors, QLabel("I0.0, I0.1...")),
                ("Digital Outputs (atuadores)", panel.actuator_offset, panel.n_actuators, QLabel("Q0.0, Q0.1...")),
                ("Register Inputs (sensores)", panel.input_reg_offset, panel.n_input_regs, panel.input_reg_to),
                ("Register Outputs (atuadores)", panel.holding_offset, panel.n_holding_regs, panel.holding_from))
        for r, (text, offset, count, plc) in enumerate(rows, 1):
            grid.addWidget(QLabel(text), r, 0)
            grid.addWidget(offset, r, 1)
            grid.addWidget(count, r, 2)
            grid.addWidget(plc, r, 3)
        right.addWidget(ports)
        form = QFormLayout()
        form.addRow("Troca de dados a cada:", panel.poll)
        right.addLayout(form)
        right.addStretch(1)
        layout.addLayout(columns)
        self.check = QLabel()
        self.check.setWordWrap(True)
        layout.addWidget(self.check)
        buttons = QDialogButtonBox(QDialogButtonBox.RestoreDefaults | QDialogButtonBox.Close)
        defaults = buttons.button(QDialogButtonBox.RestoreDefaults)
        defaults.setText("Padrão")
        defaults.setToolTip("Volta as opções e portas ao padrão da IDE (8 Inputs, 8 Coils, sem registradores), "
                            "mantendo IP, porta e Slave ID")
        defaults.clicked.connect(panel.restore_defaults)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.update_check()

    def update_check(self) -> None:
        """Erros da configuracao atual, conferidos enquanto o usuario edita."""
        p = self.panel
        errors = p.config().validate(p.max_inputs, p.max_outputs, p.max_words)
        self.check.setText("Configuração válida." if not errors else "<b>Corrija:</b> " + "; ".join(errors) + ".")
        self.check.setObjectName("muted" if not errors else "danger")
        self.check.style().unpolish(self.check)
        self.check.style().polish(self.check)


class FactoryIOPanel(QWidget):
    linkChanged = Signal(object)          # FactoryIOLink conectado ou None
    symbolEdited = Signal(str, str, str)  # endereco no CLP, novo nome ("" = sem nome), porta do Factory IO
    configChanged = Signal(object)        # FactoryIOConfig (a janela guarda para a proxima sessao)
    _probed = Signal(bool, str)           # resultado do Testar (emitido na thread do teste)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.link: FactoryIOLink | None = None
        self.max_inputs = 16
        self.max_outputs = 16
        self.max_words = 32
        self.symbols: dict[str, str] = {}       # endereco -> nome do simbolo no projeto
        self._error_text = ""
        self._probe: tuple[str, str, str] | None = None   # (cor, texto, detalhe) do ultimo Testar
        self._filling = False
        self.symbols_editable = True

        # campos das portas (exibidos no dialogo "Configurar portas...")
        self.sensor_table = QComboBox()
        for key, text in SENSOR_TABLES.items():
            self.sensor_table.addItem(text, key)
        self.sensor_table.setToolTip("Onde o Factory IO escreve os sensores (opção Write Digital do driver)")
        self.register_table = QComboBox()
        for key, text in REGISTER_TABLES.items():
            self.register_table.addItem(text, key)
        self.register_table.setToolTip("Onde o Factory IO escreve os valores analógicos (opção Write Register)")
        self.read_digital = QComboBox()
        self.read_digital.addItem("Coils (FC15)")
        self.read_digital.setEnabled(False)
        self.read_digital.setToolTip("No driver, deixe Read Digital = Coils: um cliente Modbus não consegue "
                                     "escrever em Inputs")
        self.read_register = QComboBox()
        self.read_register.addItem("Holding Registers (FC16)")
        self.read_register.setEnabled(False)
        self.read_register.setToolTip("No driver, deixe Read Register = Holding Registers: um cliente Modbus "
                                      "não consegue escrever em Input Registers")
        self.scale = QDoubleSpinBox()
        self.scale.setRange(0.001, 100000)
        self.scale.setDecimals(3)
        self.scale.setToolTip("Mesma Scale do driver: o Factory IO envia valor × escala (3,14 com escala 100 = "
                              "314). A tabela mostra o valor bruto e o dividido pela escala; o programa usa o bruto.")
        self.auto_connect = QCheckBox("Auto connect: conectar ao abrir a IDE (e tentar de novo se cair)")
        self.auto_connect.setToolTip("Como a opção Auto connect do driver: a IDE conecta sozinha ao abrir; "
                                     "conectada, tenta de novo a cada 1 s se o Factory IO fechar")
        self.n_sensors = _spin(0, MAX_BITS, "Count de Digital Inputs no driver (Input k -> I0.k)")
        self.sensor_offset = _spin(0, 65535, "Endereço do primeiro Input")
        self.n_input_regs = _spin(0, MAX_REGS, "Quantos Input Regs o driver tem")
        self.input_reg_offset = _spin(0, 65535, "Endereço do primeiro Input Reg")
        self.input_reg_to = _spin(0, 63, "Registrador N que recebe o primeiro Input Reg", "N")
        self.n_actuators = _spin(0, MAX_BITS, "Count de Digital Outputs no driver (Q0.k -> Coil k)")
        self.actuator_offset = _spin(0, 65535, "Endereço da primeira Coil")
        self.n_holding_regs = _spin(0, MAX_REGS, "Quantos Holding Regs o driver tem")
        self.holding_offset = _spin(0, 65535, "Endereço do primeiro Holding Reg")
        self.holding_from = _spin(0, 63, "Registrador N enviado ao primeiro Holding Reg", "N")
        self.poll = _spin(5, 1000, "Intervalo entre trocas de dados")
        self.poll.setSuffix(" ms")
        self.ports_dialog = PortsDialog(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)
        bar = QHBoxLayout()                  # conexao: uma linha compacta
        bar.setSpacing(6)
        self.host = QLineEdit()
        self.host.setPlaceholderText("IP do driver")
        self.host.setToolTip("IP mostrado no topo do driver Modbus TCP/IP Server do Factory IO")
        self.host.setMaximumWidth(150)
        self.port = _spin(1, 65535, "Port do driver (padrão 502)")
        self.unit = _spin(0, 255, "Slave ID do driver do Factory IO")
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.clicked.connect(self.toggle)
        self.test_btn = QPushButton("Testar")
        self.test_btn.setToolTip("Testa a conexão: abre, lê os sensores uma vez e fecha (não escreve nada na cena)")
        self.test_btn.clicked.connect(self.test_connection)
        self._probed.connect(self._show_probe)
        self.ports_btn = QPushButton("Configurar driver...")
        self.ports_btn.setToolTip("Opções do driver (Write/Read Digital e Register, Scale, Auto connect) e portas "
                                  "(Offset e Count de Inputs, Coils, Input Regs e Holding Regs)")
        self.ports_btn.clicked.connect(self._edit_driver)
        for label, w in (("IP:", self.host), ("Porta:", self.port), ("Slave ID:", self.unit)):
            bar.addWidget(QLabel(label))
            bar.addWidget(w)
        bar.addWidget(self.connect_btn)
        bar.addWidget(self.test_btn)
        self.status = QLabel()
        bar.addWidget(self.status, 1)
        bar.addWidget(self.ports_btn)
        layout.addLayout(bar)

        tables = QHBoxLayout()               # como a janela do driver: sensores | atuadores
        tables.setSpacing(8)
        self.in_table = _port_table("Sensores: o Factory IO escreve, o programa lê")
        self.out_table = _port_table("Atuadores: o programa escreve, o Factory IO lê")
        for title, table in (("SENSORES  (Factory IO → CLP)", self.in_table),
                             ("ATUADORES  (CLP → Factory IO)", self.out_table)):
            col = QVBoxLayout()
            col.setSpacing(2)
            head = QLabel(title)
            head.setObjectName("sectionTitle")
            col.addWidget(head)
            col.addWidget(table, 1)
            tables.addLayout(col, 1)
        layout.addLayout(tables, 1)

        for table in (self.in_table, self.out_table):
            table.itemChanged.connect(self._on_item_changed)
        self.sensor_table.currentIndexChanged.connect(self._fill_table)
        self.register_table.currentIndexChanged.connect(self._fill_table)
        self.scale.valueChanged.connect(self._fill_table)
        for w in self._spins():
            w.valueChanged.connect(self._fill_table)
        self.set_config(FactoryIOConfig())
        self.refresh_status()

    def _spins(self) -> tuple[QSpinBox, ...]:
        return (self.sensor_offset, self.n_sensors, self.actuator_offset, self.n_actuators, self.input_reg_offset,
                self.n_input_regs, self.input_reg_to, self.holding_offset, self.n_holding_regs, self.holding_from)

    # ------------------------------------------------------------- config
    def config(self) -> FactoryIOConfig:
        return FactoryIOConfig(
            self.host.text().strip() or "127.0.0.1", self.port.value(), self.unit.value(),
            self.sensor_table.currentData(), self.sensor_offset.value(), self.n_sensors.value(),
            self.actuator_offset.value(), self.n_actuators.value(), self.poll.value(),
            self.input_reg_offset.value(), self.n_input_regs.value(), self.input_reg_to.value(),
            self.holding_offset.value(), self.n_holding_regs.value(), self.holding_from.value(),
            self.register_table.currentData(), self.scale.value(), self.auto_connect.isChecked())

    def set_config(self, cfg: FactoryIOConfig) -> None:
        self.host.setText(cfg.host)
        self.port.setValue(cfg.port)
        self.unit.setValue(cfg.unit)
        self.poll.setValue(cfg.poll_ms)
        self.sensor_table.setCurrentIndex(max(0, self.sensor_table.findData(cfg.sensor_table)))
        self.register_table.setCurrentIndex(max(0, self.register_table.findData(cfg.register_table)))
        self.scale.setValue(cfg.scale)
        self.auto_connect.setChecked(cfg.auto_connect)
        for spin, value in zip(self._spins(), (cfg.sensor_offset, cfg.n_sensors, cfg.actuator_offset,
                                               cfg.n_actuators, cfg.input_reg_offset, cfg.n_input_regs,
                                               cfg.input_reg_to, cfg.holding_offset, cfg.n_holding_regs,
                                               cfg.holding_from)):
            spin.setValue(value)
        self._fill_table()

    def restore_defaults(self) -> None:
        """Botao Padrao do dialogo: opcoes e portas padrao, mantendo IP, porta e Slave ID."""
        self.set_config(FactoryIOConfig(self.host.text().strip() or "127.0.0.1", self.port.value(),
                                        self.unit.value()))
        self.ports_dialog.update_check()

    def _edit_driver(self) -> None:
        self.ports_dialog.exec()
        self.configChanged.emit(self.config())

    def set_limits(self, n_inputs: int, n_outputs: int, n_words: int = 32) -> None:
        """E/S e registradores N do projeto: portas alem disso aparecem sem endereco no CLP."""
        self.max_inputs, self.max_outputs, self.max_words = n_inputs, n_outputs, n_words
        self.input_reg_to.setMaximum(max(0, n_words - 1))
        self.holding_from.setMaximum(max(0, n_words - 1))
        self._fill_table()

    def set_symbols(self, symbols: dict[str, str]) -> None:
        """Nomes dos simbolos do projeto (endereco -> nome), exibidos nas tabelas."""
        self.symbols = {k.strip().upper(): v for k, v in symbols.items()}
        self._fill_table()

    # ------------------------------------------------------------- tabelas
    def _ports(self) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
        """(sensores, atuadores): listas de (porta no Factory IO, endereco no CLP ou "", tipo)."""
        c = self.config()
        table = "Input" if c.sensor_table == "inputs" else "Coil"
        regs = "Input Reg" if c.register_table == "input" else "Holding Reg"
        ins = [(f"{table} {c.sensor_offset + k}", format_operand(Area.I, k) if k < self.max_inputs else "", "in")
               for k in range(c.n_sensors)]
        ins += [(f"{regs} {c.input_reg_offset + k}",
                 f"N{c.input_reg_to + k}" if c.input_reg_to + k < self.max_words else "", "inreg")
                for k in range(c.n_input_regs)]
        outs = [(f"Coil {c.actuator_offset + k}", format_operand(Area.Q, k) if k < self.max_outputs else "", "out")
                for k in range(c.n_actuators)]
        outs += [(f"Holding Reg {c.holding_offset + k}",
                  f"N{c.holding_from + k}" if c.holding_from + k < self.max_words else "", "hold")
                 for k in range(c.n_holding_regs)]
        return ins, outs

    def set_symbols_editable(self, on: bool) -> None:
        """Os nomes so mudam fora da simulacao (o programa nao muda enquanto roda)."""
        if on != self.symbols_editable:
            self.symbols_editable = on
            self._fill_table()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._filling or item.column() != 2:
            return
        table = item.tableWidget()
        port, addr = table.item(item.row(), 0).text(), table.item(item.row(), 1).text()
        name = item.text().strip()
        if name != self.symbols.get(addr, ""):       # fora do sinal: a tabela e refeita em seguida
            QTimer.singleShot(0, lambda: self.symbolEdited.emit(addr, name, port))

    def port_names(self) -> dict[str, str]:
        """Endereco do CLP -> porta do Factory IO (ex.: "I0.3" -> "Input 3"), para o editor LADDER."""
        ins, outs = self._ports()
        return {addr: port for port, addr, _ in ins + outs if addr}

    def _fill_table(self, *_args) -> None:
        ins, outs = self._ports()
        self._kinds = {}
        self._filling = True
        for table, rows in ((self.in_table, ins), (self.out_table, outs)):
            table.setRowCount(len(rows))
            self._kinds[id(table)] = [kind for _, _, kind in rows]
            for r, (port, addr, _) in enumerate(rows):
                cells = (port, addr, self.symbols.get(addr, ""), "-") if addr else \
                    (port, "-", "sem endereço no projeto", "-")
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if col == 2 and addr and self.symbols_editable:
                        item.setToolTip(f"Duplo clique para dar nome a {addr} (apagar o nome remove o símbolo). "
                                        "O nome muda também no diagrama LADDER.")
                    else:
                        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    if col == 3:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if not addr:
                        item.setForeground(QColor("#94a3b8"))
                        item.setToolTip("O controlador do projeto não tem esse ponto. Para usar todas as portas, "
                                        "escolha um controlador com mais E/S (ex.: Somente simulação, 16 E/S).")
                    table.setItem(r, col, item)
        self._filling = False
        self._show_values()
        dialog = getattr(self, "ports_dialog", None)
        if dialog is not None and dialog.isVisible():
            dialog.update_check()

    def _show_values(self) -> None:
        link = self.link
        live = link is not None and link.connected
        values = {"in": [], "out": [], "inreg": [], "hold": []}
        if live:
            c = link.config
            values["in"] = [link.input_bits() >> k & 1 for k in range(c.n_sensors)]
            values["out"] = [link.outputs >> k & 1 for k in range(c.n_actuators)]
            values["inreg"] = link.input_regs
            values["hold"] = link.holding_regs
        for table in (self.in_table, self.out_table):
            seen = {"in": 0, "out": 0, "inreg": 0, "hold": 0}
            for r, kind in enumerate(getattr(self, "_kinds", {}).get(id(table), [])):
                k = seen[kind]
                seen[kind] += 1
                item = table.item(r, 3)
                if item is None:
                    continue
                if not live or k >= len(values[kind]):
                    item.setText("-")
                    item.setForeground(QColor(GRAY))
                    continue
                v = values[kind][k]
                scale = link.config.scale
                item.setText(f"{v} ({v / scale:g})" if kind in ("inreg", "hold") and scale != 1 else str(v))
                item.setForeground(QColor(GREEN) if v else QColor(GRAY))

    # ------------------------------------------------------------- ligacao
    @property
    def linked(self) -> bool:
        return self.link is not None

    def toggle(self) -> None:
        if self.link is None:
            self.connect_link()
        else:
            self.disconnect_link()

    def connect_link(self) -> list[str]:
        if self.link is not None:
            return []
        cfg = self.config()
        errors = cfg.validate(self.max_inputs, self.max_outputs, self.max_words)
        if errors:
            self._error_text = "Não conectado: " + "; ".join(errors)
            self.refresh_status()
            return errors
        self._error_text = ""
        self._probe = None
        self.link = FactoryIOLink(cfg)
        self.link.start()
        self._set_editable(False)
        self.linkChanged.emit(self.link)
        self.refresh_status()
        return []

    def disconnect_link(self) -> None:
        if self.link is None:
            return
        link, self.link = self.link, None
        link.stop()                          # escreve 0 nas coils e holding registers antes de fechar
        self._set_editable(True)
        self.linkChanged.emit(None)
        self.refresh_status()

    def shutdown(self) -> None:
        self.disconnect_link()

    def _set_editable(self, on: bool) -> None:
        for w in (self.host, self.port, self.unit, self.poll, self.sensor_table, self.register_table, self.scale,
                  self.test_btn, *self._spins()):
            w.setEnabled(on)
        self.connect_btn.setText("Desconectar" if not on else "Conectar")

    def test_connection(self) -> None:
        """Testar: conecta uma vez em outra thread (a interface nao trava) e mostra o resultado."""
        cfg = self.config()
        self.test_btn.setEnabled(False)
        self._probe = (AMBER, f"Testando {cfg.host}:{cfg.port}...", "")
        self.refresh_status()
        threading.Thread(target=lambda: self._probed.emit(*probe(cfg)), daemon=True,
                         name="factoryio-probe").start()

    def _show_probe(self, ok: bool, text: str) -> None:
        self.test_btn.setEnabled(self.link is None)
        self._error_text = ""
        self._probe = (GREEN, "Teste OK: " + text, "") if ok else (RED, "Teste falhou: " + text, text + PROBE_HINT)
        self.refresh_status()

    def _set_status(self, color: str, text: str, detail: str = "") -> None:
        self.status.setText(f'<span style="color:{color}">●</span> {text}')
        self.status.setToolTip((detail + "\n\n" if detail else "") + DRIVER_HINT)

    def refresh_status(self) -> None:
        link = self.link
        if link is None:
            if self._error_text:
                self._set_status(RED, self._error_text)
            elif self._probe is not None:            # resultado do Testar fica ate a proxima conexao
                self._set_status(*self._probe)
            else:
                self._set_status(GRAY, "Desconectado")
        elif link.connected:
            c = link.config
            self._set_status(GREEN, f"Conectado a {c.host}:{c.port} - troca em {link.cycle_ms:.1f} ms"
                             + (f" ({link.drops} queda(s))" if link.drops else ""))
        else:
            detail = link.error or ""
            if link.error and "sem conexão" in link.error:   # texto vem de sim/factoryio.py
                detail += ("\nUse o IP mostrado no topo do driver do Factory IO (depende do Network adapter "
                           "escolhido) ou escolha o adaptador loopback para usar 127.0.0.1.")
            self._set_status(AMBER, f"Tentando conectar a {link.config.host}:{link.config.port}..."
                             + (f" - {link.error}" if link.error else ""), detail)
        self._show_values()
