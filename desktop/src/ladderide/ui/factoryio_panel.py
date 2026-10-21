"""Painel da ligacao com o Factory IO (driver Modbus TCP/IP Server).

Layout espelhando a janela do driver no Factory IO: sensores (Inputs e Input Regs)
a esquerda, atuadores (Coils e Holding Regs) a direita, cada porta com o endereco
no CLP, o simbolo e o valor ao vivo. A conexao fica numa barra compacta em cima e
as quantidades/enderecos das portas num dialogo ("Configurar portas...").
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..sim.factoryio import MAX_BITS, MAX_REGS, SENSOR_TABLES, FactoryIOConfig, FactoryIOLink

DRIVER_HINT = ("No Factory IO: File > Drivers > Modbus TCP/IP Server. Use o IP e o Slave ID mostrados no topo "
               "do driver e as mesmas quantidades de Inputs, Coils, Input Regs e Holding Regs. Coloque a cena "
               "em RUN e conecte. Enquanto conectado, a simulacao fica em 1x (o Factory IO roda em tempo real).")
GREEN, AMBER, GRAY, RED = "#16a34a", "#d97706", "#64748b", "#dc2626"


def _spin(lo: int, hi: int, tip: str, prefix: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setToolTip(tip)
    if prefix:
        s.setPrefix(prefix)
    return s


def _port_table(tip: str) -> QTableWidget:
    t = QTableWidget(0, 4)
    t.setHorizontalHeaderLabels(["Porta", "CLP", "Simbolo", "Valor"])
    t.verticalHeader().hide()
    t.verticalHeader().setDefaultSectionSize(22)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionMode(QTableWidget.NoSelection)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    h = t.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    h.setSectionResizeMode(2, QHeaderView.Stretch)
    t.setToolTip(tip)
    return t


class PortsDialog(QDialog):
    """Quantidades e enderecos das portas do driver (os campos pertencem ao painel)."""

    def __init__(self, panel: "FactoryIOPanel"):
        super().__init__(panel)
        self.setWindowTitle("Factory IO - portas do driver")
        layout = QVBoxLayout(self)
        hint = QLabel("Use as mesmas quantidades configuradas no driver Modbus TCP/IP Server do Factory IO.")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        row = QHBoxLayout()
        sensors = QGroupBox("Sensores (Factory IO → CLP)")
        form = QFormLayout(sensors)
        form.addRow("Inputs:", panel.n_sensors)
        form.addRow("Primeiro Input:", panel.sensor_offset)
        form.addRow("Sensores em:", panel.sensor_table)
        form.addRow("Input Regs:", panel.n_input_regs)
        form.addRow("Primeiro Input Reg:", panel.input_reg_offset)
        form.addRow("Input Regs vao para:", panel.input_reg_to)
        row.addWidget(sensors)
        actuators = QGroupBox("Atuadores (CLP → Factory IO)")
        form = QFormLayout(actuators)
        form.addRow("Coils:", panel.n_actuators)
        form.addRow("Primeira Coil:", panel.actuator_offset)
        form.addRow("Holding Regs:", panel.n_holding_regs)
        form.addRow("Primeiro Holding Reg:", panel.holding_offset)
        form.addRow("Holding Regs vem de:", panel.holding_from)
        row.addWidget(actuators)
        layout.addLayout(row)
        form = QFormLayout()
        form.addRow("Troca de dados a cada:", panel.poll)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)


class FactoryIOPanel(QWidget):
    linkChanged = Signal(object)          # FactoryIOLink conectado ou None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.link: FactoryIOLink | None = None
        self.max_inputs = 16
        self.max_outputs = 16
        self.max_words = 32
        self.symbols: dict[str, str] = {}       # endereco -> nome do simbolo no projeto
        self._error_text = ""

        # campos das portas (exibidos no dialogo "Configurar portas...")
        self.sensor_table = QComboBox()
        for key, text in SENSOR_TABLES.items():
            self.sensor_table.addItem(text, key)
        self.sensor_table.setToolTip("Onde o Factory IO escreve os sensores (opcao Write Digital do driver)")
        self.n_sensors = _spin(0, MAX_BITS, "Quantos Inputs o driver tem (Input k -> I0.k)")
        self.sensor_offset = _spin(0, 65535, "Endereco do primeiro Input")
        self.n_input_regs = _spin(0, MAX_REGS, "Quantos Input Regs o driver tem")
        self.input_reg_offset = _spin(0, 65535, "Endereco do primeiro Input Reg")
        self.input_reg_to = _spin(0, 63, "Registrador N que recebe o primeiro Input Reg", "N")
        self.n_actuators = _spin(0, MAX_BITS, "Quantas Coils o driver tem (Q0.k -> Coil k)")
        self.actuator_offset = _spin(0, 65535, "Endereco da primeira Coil")
        self.n_holding_regs = _spin(0, MAX_REGS, "Quantos Holding Regs o driver tem")
        self.holding_offset = _spin(0, 65535, "Endereco do primeiro Holding Reg")
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
        self.port = _spin(1, 65535, "Porta TCP do driver (padrao 502)")
        self.unit = _spin(0, 255, "Slave ID mostrado no driver do Factory IO")
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.clicked.connect(self.toggle)
        self.ports_btn = QPushButton("Configurar portas...")
        self.ports_btn.setToolTip("Quantidades e enderecos de Inputs, Coils, Input Regs e Holding Regs")
        self.ports_btn.clicked.connect(self.ports_dialog.exec)
        for label, w in (("IP:", self.host), ("Porta:", self.port), ("Slave ID:", self.unit)):
            bar.addWidget(QLabel(label))
            bar.addWidget(w)
        bar.addWidget(self.connect_btn)
        self.status = QLabel()
        bar.addWidget(self.status, 1)
        bar.addWidget(self.ports_btn)
        layout.addLayout(bar)

        tables = QHBoxLayout()               # como a janela do driver: sensores | atuadores
        tables.setSpacing(8)
        self.in_table = _port_table("Sensores: o Factory IO escreve, o programa le")
        self.out_table = _port_table("Atuadores: o programa escreve, o Factory IO le")
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

        self.sensor_table.currentIndexChanged.connect(self._fill_table)
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
            self.holding_offset.value(), self.n_holding_regs.value(), self.holding_from.value())

    def set_config(self, cfg: FactoryIOConfig) -> None:
        self.host.setText(cfg.host)
        self.port.setValue(cfg.port)
        self.unit.setValue(cfg.unit)
        self.poll.setValue(cfg.poll_ms)
        self.sensor_table.setCurrentIndex(max(0, self.sensor_table.findData(cfg.sensor_table)))
        for spin, value in zip(self._spins(), (cfg.sensor_offset, cfg.n_sensors, cfg.actuator_offset,
                                               cfg.n_actuators, cfg.input_reg_offset, cfg.n_input_regs,
                                               cfg.input_reg_to, cfg.holding_offset, cfg.n_holding_regs,
                                               cfg.holding_from)):
            spin.setValue(value)
        self._fill_table()

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
        ins = [(f"{table} {c.sensor_offset + k}", f"I0.{k}" if k < self.max_inputs else "", "in")
               for k in range(c.n_sensors)]
        ins += [(f"Input Reg {c.input_reg_offset + k}",
                 f"N{c.input_reg_to + k}" if c.input_reg_to + k < self.max_words else "", "inreg")
                for k in range(c.n_input_regs)]
        outs = [(f"Coil {c.actuator_offset + k}", f"Q0.{k}" if k < self.max_outputs else "", "out")
                for k in range(c.n_actuators)]
        outs += [(f"Holding Reg {c.holding_offset + k}",
                  f"N{c.holding_from + k}" if c.holding_from + k < self.max_words else "", "hold")
                 for k in range(c.n_holding_regs)]
        return ins, outs

    def port_names(self) -> dict[str, str]:
        """Endereco do CLP -> porta do Factory IO (ex.: "I0.3" -> "Input 3"), para o editor LADDER."""
        ins, outs = self._ports()
        return {addr: port for port, addr, _ in ins + outs if addr}

    def _fill_table(self, *_args) -> None:
        ins, outs = self._ports()
        self._kinds = {}
        for table, rows in ((self.in_table, ins), (self.out_table, outs)):
            table.setRowCount(len(rows))
            self._kinds[id(table)] = [kind for _, _, kind in rows]
            for r, (port, addr, _) in enumerate(rows):
                cells = (port, addr, self.symbols.get(addr, ""), "-") if addr else \
                    (port, "-", "sem endereco no projeto", "-")
                for col, text in enumerate(cells):
                    item = QTableWidgetItem(text)
                    if col == 3:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if not addr:
                        item.setForeground(QColor("#94a3b8"))
                        item.setToolTip("O controlador do projeto nao tem esse ponto. Para usar todas as portas, "
                                        "escolha um controlador com mais E/S (ex.: Somente simulacao, 16 E/S).")
                    table.setItem(r, col, item)
        self._show_values()

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
                item.setText(str(v))
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
            self._error_text = "Nao conectado: " + "; ".join(errors)
            self.refresh_status()
            return errors
        self._error_text = ""
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
        for w in (self.host, self.port, self.unit, self.poll, self.sensor_table, *self._spins()):
            w.setEnabled(on)
        self.connect_btn.setText("Desconectar" if not on else "Conectar")

    def _set_status(self, color: str, text: str, detail: str = "") -> None:
        self.status.setText(f'<span style="color:{color}">●</span> {text}')
        self.status.setToolTip((detail + "\n\n" if detail else "") + DRIVER_HINT)

    def refresh_status(self) -> None:
        link = self.link
        if link is None:
            if self._error_text:
                self._set_status(RED, self._error_text)
            else:
                self._set_status(GRAY, "Desconectado")
        elif link.connected:
            c = link.config
            self._set_status(GREEN, f"Conectado a {c.host}:{c.port} - troca em {link.cycle_ms:.1f} ms"
                             + (f" ({link.drops} queda(s))" if link.drops else ""))
        else:
            detail = link.error or ""
            if link.error and "sem conexao" in link.error:
                detail += ("\nUse o IP mostrado no topo do driver do Factory IO (depende do Network adapter "
                           "escolhido) ou escolha o adaptador loopback para usar 127.0.0.1.")
            self._set_status(AMBER, f"Tentando conectar a {link.config.host}:{link.config.port}..."
                             + (f" - {link.error}" if link.error else ""), detail)
        self._show_values()
