"""Dialogos de edicao de elemento e de propriedades do projeto."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QGridLayout,
                               QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import isa
from ..model.controllers import apply_controller, controller_by_id, default_controller, load_controllers
from ..model.project import (COMPARE_KINDS, MATH_KINDS, Coil, CompareBox, Contact, CounterBox, MathBox,
                             Project, ResetBox, TimerBox, default_operands)

KIND_CHOICES = {
    Contact: [("XIC", "Normalmente aberto (NA / XIC)"), ("XIO", "Normalmente fechado (NF / XIO)")],
    Coil: [("OTE", "Bobina comum (OTE)"), ("OTL", "SET / liga e mantém (OTL)"), ("OTU", "RESET / desliga (OTU)")],
    TimerBox: [("TON", "TON - retardo na energização"), ("TOF", "TOF - retardo na desenergização"),
               ("RTO", "RTO - retentivo")],
    CounterBox: [("CTU", "CTU - crescente"), ("CTD", "CTD - decrescente")],
    CompareBox: [("EQU", "EQU - igual (A = B)"), ("NEQ", "NEQ - diferente (A \u2260 B)"), ("LES", "LES - menor (A < B)"),
                 ("GRT", "GRT - maior (A > B)"), ("LEQ", "LEQ - menor ou igual (A \u2264 B)"),
                 ("GEQ", "GEQ - maior ou igual (A \u2265 B)"), ("LIM", "LIM - teste de limite (faixa)"),
                 ("MEQ", "MEQ - comparação com máscara")],
    MathBox: [("ADD", "ADD - soma"), ("SUB", "SUB - subtração"), ("MUL", "MUL - multiplicação"),
              ("DIV", "DIV - divisão inteira"), ("SQR", "SQR - raiz quadrada"), ("NEG", "NEG - troca o sinal"),
              ("TOD", "TOD - inteiro para BCD"), ("FRD", "FRD - BCD para inteiro")],
}


def word_suggestions(project: Project, write: bool) -> list[str]:
    """Operandos numericos: simbolos de N, registradores, ACC/PRE em uso e as palavras de E/S."""
    words = [s.name for s in project.symbols if s.address.strip().upper().startswith("N")]
    words += [f"N{k}" for k in range(min(project.io.n_words, 16))]
    if write:
        return words + ["QW0"]
    for _, node, _ in project.walk():
        if isinstance(node, (TimerBox, CounterBox)) and node.operand.strip():
            words += [f"{node.operand.strip()}.ACC", f"{node.operand.strip()}.PRE"]
    return words + ["IW0", "QW0", "0", "1", "10", "100"]


def operand_suggestions(node, project: Project) -> list[str]:
    io = project.io
    bits_i = [f"I{k // 8}.{k % 8}" for k in range(io.n_inputs)]
    bits_q = [f"Q{k // 8}.{k % 8}" for k in range(io.n_outputs)]
    bits_m = [f"M{k // 8}.{k % 8}" for k in range(min(io.n_markers, 64))]
    timers = [f"T{k}" for k in range(8)]
    counters = [f"C{k}" for k in range(8)]
    syms = [s.name for s in project.symbols]
    if isinstance(node, Contact):
        extra = [f"T{k}.DN" for k in range(4)] + [f"C{k}.DN" for k in range(4)] + ["S0.0", "S0.3"]
        return syms + bits_i + bits_q + bits_m + extra
    if isinstance(node, Coil):
        return syms + bits_q + bits_m
    if isinstance(node, TimerBox):
        return [s.name for s in project.symbols if s.address.upper().startswith("T")] + timers
    if isinstance(node, CounterBox):
        return [s.name for s in project.symbols if s.address.upper().startswith("C")] + counters
    if isinstance(node, ResetBox):
        return syms + timers + counters
    return syms


def operand_choices(node, project: Project, ports: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """(texto exibido, operando): cada sugestao com o simbolo/endereco e a porta do Factory IO ligada a ela."""
    ports = {k.upper(): v for k, v in (ports or {}).items()}
    by_name = {s.name.upper(): s.address.strip().upper() for s in project.symbols}
    by_addr = {s.address.strip().upper(): s.name for s in project.symbols}
    choices = []
    for value in operand_suggestions(node, project):
        addr = by_name.get(value.upper(), value.upper())
        parts = [value]
        parts.append(addr if value.upper() in by_name else by_addr.get(addr, ""))
        if addr in ports:
            parts.append(f"{ports[addr]} (Factory IO)")
        choices.append(("  \u00b7  ".join(p for p in parts if p), value))
    return choices


def fill_operand_combo(combo: QComboBox, node, project: Project, ports: dict[str, str] | None = None) -> None:
    combo.clear()
    for text, value in operand_choices(node, project, ports):
        combo.addItem(text, value)
    combo.setCurrentText(getattr(node, "operand", ""))


def combo_operand(combo: QComboBox) -> str:
    """Operando escolhido: o valor do item da lista ou o texto digitado."""
    text = combo.currentText().strip()
    index = combo.findText(text)
    return combo.itemData(index) if index >= 0 and combo.itemData(index) else text


class AddressPopup(QFrame):
    """Escolha rapida do endereco de um elemento, aberta sobre o proprio diagrama."""

    def __init__(self, node, project: Project, ports: dict[str, str] | None, on_accept, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setFrameShape(QFrame.StyledPanel)
        self.on_accept = on_accept
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        title = QLabel("Endereço (ou símbolo) - Enter confirma, Esc cancela")
        title.setObjectName("muted")
        layout.addWidget(title)
        self.combo = QComboBox()
        self.combo.setEditable(True)
        self.combo.setInsertPolicy(QComboBox.NoInsert)
        self.combo.setMinimumWidth(320)
        self.combo.setMaxVisibleItems(16)
        fill_operand_combo(self.combo, node, project, ports)
        self.combo.activated.connect(lambda _i: self.accept_value())
        self.combo.lineEdit().returnPressed.connect(self.accept_value)
        layout.addWidget(self.combo)
        self.combo.lineEdit().selectAll()
        self.combo.setFocus()

    def accept_value(self) -> None:
        value = combo_operand(self.combo)
        self.close()
        if value:
            self.on_accept(value)


class ElementDialog(QDialog):
    def __init__(self, node, project: Project, parent=None, ports: dict[str, str] | None = None):
        super().__init__(parent)
        self.node = node
        self.project = project
        self.setWindowTitle("Editar elemento")
        form = QFormLayout()
        if isinstance(node, (CompareBox, MathBox)):
            self._build_block(form)
            return
        self.kind = None
        if type(node) in KIND_CHOICES:
            self.kind = QComboBox()
            for code, text in KIND_CHOICES[type(node)]:
                self.kind.addItem(text, code)
            self.kind.setCurrentIndex(max(0, self.kind.findData(node.kind)))
            form.addRow("Tipo:", self.kind)
        self.operand = QComboBox()
        self.operand.setEditable(True)
        self.operand.setInsertPolicy(QComboBox.NoInsert)
        fill_operand_combo(self.operand, node, project, ports)
        form.addRow("Operando (endereço ou símbolo):", self.operand)
        self.preset = None
        if isinstance(node, (TimerBox, CounterBox)):
            self.preset = QSpinBox()
            self.preset.setRange(0, isa.MAX_PRESET)
            self.preset.setValue(node.preset)
            if isinstance(node, TimerBox):
                self.preset.setSuffix(" ms")
                self.preset.setSingleStep(100)
                self.seconds = QLabel()
                self.preset.valueChanged.connect(self._update_seconds)
                self._update_seconds()
                form.addRow("Preset:", self.preset)
                form.addRow("", self.seconds)
            else:
                form.addRow("Preset (contagens):", self.preset)
        help_text = QLabel("Endereços: I0.0-I1.7 entradas, Q0.0-Q1.7 saídas, M0.0-M31.7 memórias,\n"
                           "Tn / Cn temporizador e contador, Tn.DN / Cn.DN bit de conclusão,\n"
                           "S0.0 primeira varredura, S0.3 relógio de 1 s.")
        help_text.setObjectName("muted")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(help_text)
        box.addWidget(buttons)

    # ---------------------------------------------- comparacao / matematica
    def _build_block(self, form: QFormLayout) -> None:
        node = self.node
        self.kind = QComboBox()
        for code, text in KIND_CHOICES[type(node)]:
            self.kind.addItem(text, code)
        self.kind.setCurrentIndex(max(0, self.kind.findData(node.kind)))
        form.addRow("Instrução:", self.kind)
        self.fields_box = QWidget()
        self.fields_form = QFormLayout(self.fields_box)
        self.fields_form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.fields_box)
        self.fields: list[QComboBox] = []
        self._fill_fields(list(node.operands))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        help_text = QLabel(
            "Operandos: constante (123, -5, 0x1F), registrador N0-N{last}, Tn.ACC / Tn.PRE, Cn.ACC / Cn.PRE,\n"
            "IW0 (entradas como número) ou QW0 (saídas). Destino: N ou QW0. Valores inteiros de 32 bits;\n"
            "S0.4 liga em estouro/operação inválida, S0.5 com resultado zero, S0.6 com resultado negativo."
            .replace("{last}", str(max(0, self.project.io.n_words - 1))))
        help_text.setObjectName("muted")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(help_text)
        box.addWidget(buttons)
        self.operand = self.preset = None

    def _roles(self, kind: str) -> tuple[str, ...]:
        return (COMPARE_KINDS if isinstance(self.node, CompareBox) else MATH_KINDS)[kind]

    def _fill_fields(self, values: list[str]) -> None:
        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self.fields = []
        roles = self._roles(self.kind.currentData())
        for k, role in enumerate(roles):
            write = isinstance(self.node, MathBox) and k == len(roles) - 1
            combo = QComboBox()
            combo.setEditable(True)
            combo.addItems(word_suggestions(self.project, write))
            combo.setCurrentText(values[k] if k < len(values) else "")
            self.fields_form.addRow(f"{role}:", combo)
            self.fields.append(combo)

    def _kind_changed(self) -> None:
        current = [f.currentText().strip() for f in self.fields]
        kind = self.kind.currentData()
        if len(current) != len(self._roles(kind)):     # muda a quantidade de operandos: usa o padrao
            current = default_operands(kind)
        self._fill_fields(current)

    def _update_seconds(self) -> None:
        self.seconds.setText(f"= {self.preset.value() / 1000:.3f} s")

    def apply(self) -> None:
        if isinstance(self.node, (CompareBox, MathBox)):
            self.node.kind = self.kind.currentData()
            self.node.operands = [f.currentText().strip() for f in self.fields]
            return
        if self.kind is not None:
            self.node.kind = self.kind.currentData()
        self.node.operand = combo_operand(self.operand)
        if self.preset is not None:
            self.node.preset = self.preset.value()


def _controller_combo(selected: str) -> QComboBox:
    combo = QComboBox()
    for c in load_controllers():
        combo.addItem(c.name, c.id)
    index = combo.findData(selected)
    if index < 0:                                     # projeto com controlador que nao existe nesta IDE
        combo.addItem(f"{selected} (desconhecido)", selected)
        index = combo.count() - 1
    combo.setCurrentIndex(index)
    return combo


def _controller_text(ctrl) -> str:
    if ctrl is None:
        return "Controlador desconhecido nesta instalação: valem os limites gerais da IDE."
    kind = "Placa real com firmware do projeto." if ctrl.hardware else "Sem placa: somente simulação."
    ports = f"\nPortas de comunicação: {ctrl.ports}." if ctrl.ports else ""
    return f"{ctrl.description}\n\nLimites: {ctrl.summary()}.{ports}\n{kind}"


class NewProjectDialog(QDialog):
    """Novo projeto: nome e controlador do CLP, escolhido numa lista por familia (como o
    "Select Processor Type" do RSLogix 500). O controlador define as E/S e a memoria."""

    COLUMNS = ("Processador", "Tipo", "E/S na IDE", "Programa")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Novo projeto")
        self.resize(820, 620)
        form = QFormLayout()
        self.name = QLineEdit("Novo projeto")
        form.addRow("Nome:", self.name)
        self.list = QTreeWidget()
        self.list.setHeaderLabels(self.COLUMNS)
        self.list.setRootIsDecorated(False)
        self.list.setUniformRowHeights(True)
        self.list.setAlternatingRowColors(True)
        groups: dict[str, QTreeWidgetItem] = {}
        for c in load_controllers():
            group = groups.get(c.family)
            if group is None:
                group = groups[c.family] = QTreeWidgetItem(self.list, [c.family])
                group.setFirstColumnSpanned(True)
                group.setFlags(Qt.ItemIsEnabled)
                font = group.font(0)
                font.setBold(True)
                group.setFont(0, font)
            row = QTreeWidgetItem(group, [c.label, c.spec, f"{c.inputs}E / {c.outputs}S",
                                          f"{c.instructions} instr. / {c.rungs} redes"])
            row.setData(0, Qt.UserRole, c.id)
            row.setToolTip(0, c.name)
        self.list.expandAll()
        for col in range(len(self.COLUMNS)):
            self.list.resizeColumnToContents(col)
        self.list.setColumnWidth(0, max(self.list.columnWidth(0), 150))
        self.list.currentItemChanged.connect(lambda *_: self._update())
        self.list.itemDoubleClicked.connect(lambda item, _c: item.data(0, Qt.UserRole) and self.accept())
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setObjectName("muted")
        self.details.setMinimumHeight(96)
        self.details.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        hint = QLabel("O controlador limita as entradas e saídas, a quantidade de memórias, temporizadores, "
                      "contadores e registradores e o tamanho do programa. Pode ser trocado depois em "
                      "Programa > Propriedades.")
        hint.setWordWrap(True)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(QLabel("<b>Tipo de processador</b>"))
        box.addWidget(self.list, 1)
        box.addWidget(self.details)
        box.addWidget(hint)
        box.addWidget(self.buttons)
        self.select(default_controller().id)

    def _rows(self):
        for g in range(self.list.topLevelItemCount()):
            group = self.list.topLevelItem(g)
            for k in range(group.childCount()):
                yield group.child(k)

    def select(self, controller_id: str) -> bool:
        for row in self._rows():
            if row.data(0, Qt.UserRole) == controller_id:
                self.list.setCurrentItem(row)
                return True
        return False

    def selected_id(self) -> str | None:
        item = self.list.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _update(self) -> None:
        cid = self.selected_id()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(bool(cid))
        self.details.setText(_controller_text(controller_by_id(cid)) if cid else "Escolha um processador na lista.")

    def project(self) -> Project:
        p = Project(name=self.name.text().strip() or "Novo projeto")
        ctrl = controller_by_id(self.selected_id() or "")
        if ctrl is not None:
            apply_controller(p, ctrl)
        return p


class ProjectDialog(QDialog):
    def __init__(self, project: Project, parent=None):
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("Propriedades do projeto")
        io = project.io
        form = QFormLayout()
        self.name = QLineEdit(project.name)
        self.version = QLineEdit(project.version)
        self.description = QPlainTextEdit(project.description)
        self.description.setFixedHeight(70)
        form.addRow("Nome:", self.name)
        form.addRow("Versão:", self.version)
        form.addRow("Descrição:", self.description)
        self.controller = _controller_combo(project.target.device)
        self.controller_info = QLabel()
        self.controller_info.setWordWrap(True)
        self.controller_info.setObjectName("muted")
        form.addRow("Controlador:", self.controller)
        self.n_inputs = self._spin(1, isa.IDE_MAX_INPUTS, io.n_inputs)
        self.n_outputs = self._spin(1, isa.MAX_OUTPUTS, io.n_outputs)
        self.n_markers = self._spin(0, isa.MAX_MARKERS, io.n_markers)
        self.n_words = self._spin(0, isa.MAX_WORDS, io.n_words)
        self.period = self._spin(1, 1000, io.scan_period_ms)
        self.period.setSuffix(" ms")
        form.addRow("Entradas digitais:", self.n_inputs)
        form.addRow("Saídas (relés):", self.n_outputs)
        form.addRow("Memórias M:", self.n_markers)
        form.addRow("Registradores N (inteiros):", self.n_words)
        form.addRow("Período de varredura:", self.period)
        safe = QGroupBox("Estado seguro das saídas em STOP/FAULT (marcado = energizado)")
        grid = QGridLayout(safe)
        self.safe: list[QCheckBox] = []
        for k in range(isa.MAX_OUTPUTS):
            cb = QCheckBox(f"Q{k // 8}.{k % 8}")
            cb.setChecked(bool(io.safe_outputs >> k & 1))
            grid.addWidget(cb, k // 8, k % 8)
            self.safe.append(cb)
        self.controller.currentIndexChanged.connect(self._controller_changed)
        self._controller_changed()
        warn = QLabel("Atenção: desenergizar nem sempre e o estado seguro da carga. "
                      "Defina conforme a aplicação.")
        warn.setWordWrap(True)
        warn.setObjectName("warn")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(self.controller_info)
        box.addWidget(safe)
        box.addWidget(warn)
        box.addWidget(buttons)
        self.setMinimumWidth(560)
        self.adjustSize()

    def _controller_changed(self, *_args) -> None:
        """Os maximos dos campos passam a ser os do controlador; valores acima sao reduzidos.
        Entradas e saidas sao exatamente as do controlador, como num CLP real, em que a
        quantidade de E/S e da CPU/modulo: os campos ficam travados (menos no Personalizado)."""
        ctrl = controller_by_id(self.controller.currentData())
        self.controller_info.setText(_controller_text(ctrl))
        fixed = ctrl is not None and not ctrl.custom
        if fixed:
            self.n_inputs.setMaximum(ctrl.inputs)
            self.n_outputs.setMaximum(ctrl.outputs)
            self.n_inputs.setValue(ctrl.inputs)
            self.n_outputs.setValue(ctrl.outputs)
        for spin in (self.n_inputs, self.n_outputs):
            spin.setEnabled(not fixed)
            spin.setToolTip("Definido pelo controlador (escolha Personalizado para mudar)" if fixed else "")
        limits = ((self.n_inputs, ctrl.inputs if ctrl else isa.IDE_MAX_INPUTS),
                  (self.n_outputs, ctrl.outputs if ctrl else isa.MAX_OUTPUTS),
                  (self.n_markers, ctrl.markers if ctrl else isa.MAX_MARKERS),
                  (self.n_words, ctrl.words if ctrl else isa.MAX_WORDS))
        for spin, limit in limits:
            spin.setMaximum(limit)
            spin.setSuffix(f"  (max. {limit})")
        n_out = self.n_outputs.maximum()
        for k, cb in enumerate(self.safe if hasattr(self, "safe") else []):
            cb.setVisible(k < n_out)              # so as saidas que o controlador tem

    @staticmethod
    def _spin(lo: int, hi: int, value: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(lo, hi)
        s.setValue(value)
        return s

    def apply(self) -> None:
        p = self.project
        p.name = self.name.text().strip() or "Sem nome"
        p.version = self.version.text().strip()
        p.description = self.description.toPlainText()
        p.target.device = self.controller.currentData()
        p.io.n_inputs = self.n_inputs.value()
        p.io.n_outputs = self.n_outputs.value()
        p.io.n_markers = self.n_markers.value()
        p.io.n_words = self.n_words.value()
        p.io.scan_period_ms = self.period.value()
        mask = sum(1 << k for k, cb in enumerate(self.safe) if cb.isChecked())
        p.io.safe_outputs = mask & ((1 << p.io.n_outputs) - 1)
