"""Dialogos de edicao de elemento e de propriedades do projeto."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout, QWidget)

from ..core import isa
from ..model.controllers import apply_controller, controller_by_id, default_controller, load_controllers
from ..model.project import (COMPARE_KINDS, MATH_KINDS, Coil, CompareBox, Contact, CounterBox, MathBox,
                             Project, ResetBox, TimerBox, default_operands)

KIND_CHOICES = {
    Contact: [("XIC", "Normalmente aberto (NA / XIC)"), ("XIO", "Normalmente fechado (NF / XIO)")],
    Coil: [("OTE", "Bobina comum (OTE)"), ("OTL", "SET / liga e mantem (OTL)"), ("OTU", "RESET / desliga (OTU)")],
    TimerBox: [("TON", "TON - retardo na energizacao"), ("TOF", "TOF - retardo na desenergizacao"),
               ("RTO", "RTO - retentivo")],
    CounterBox: [("CTU", "CTU - crescente"), ("CTD", "CTD - decrescente")],
    CompareBox: [("EQU", "EQU - igual (A = B)"), ("NEQ", "NEQ - diferente (A \u2260 B)"), ("LES", "LES - menor (A < B)"),
                 ("GRT", "GRT - maior (A > B)"), ("LEQ", "LEQ - menor ou igual (A \u2264 B)"),
                 ("GEQ", "GEQ - maior ou igual (A \u2265 B)"), ("LIM", "LIM - teste de limite (faixa)"),
                 ("MEQ", "MEQ - comparacao com mascara")],
    MathBox: [("ADD", "ADD - soma"), ("SUB", "SUB - subtracao"), ("MUL", "MUL - multiplicacao"),
              ("DIV", "DIV - divisao inteira"), ("SQR", "SQR - raiz quadrada"), ("NEG", "NEG - troca o sinal"),
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


class ElementDialog(QDialog):
    def __init__(self, node, project: Project, parent=None):
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
        self.operand.addItems(operand_suggestions(node, project))
        self.operand.setCurrentText(node.operand)
        form.addRow("Operando (endereco ou simbolo):", self.operand)
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
        help_text = QLabel("Enderecos: I0.0-I1.7 entradas, Q0.0-Q1.7 saidas, M0.0-M31.7 memorias,\n"
                           "Tn / Cn temporizador e contador, Tn.DN / Cn.DN bit de conclusao,\n"
                           "S0.0 primeira varredura, S0.3 relogio de 1 s.")
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
        form.addRow("Instrucao:", self.kind)
        self.fields_box = QWidget()
        self.fields_form = QFormLayout(self.fields_box)
        self.fields_form.setContentsMargins(0, 0, 0, 0)
        form.addRow(self.fields_box)
        self.fields: list[QComboBox] = []
        self._fill_fields(list(node.operands))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        help_text = QLabel(
            "Operandos: constante (123, -5, 0x1F), registrador N0-N{last}, Tn.ACC / Tn.PRE, Cn.ACC / Cn.PRE,\n"
            "IW0 (entradas como numero) ou QW0 (saidas). Destino: N ou QW0. Valores inteiros de 32 bits;\n"
            "S0.4 liga em estouro/operacao invalida, S0.5 com resultado zero, S0.6 com resultado negativo."
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
        self.node.operand = self.operand.currentText().strip()
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
        return "Controlador desconhecido nesta instalacao: valem os limites gerais da IDE."
    kind = "Placa real com firmware do projeto." if ctrl.hardware else "Sem placa: somente simulacao."
    return f"{ctrl.description}\n\nLimites: {ctrl.summary()}.\n{kind}"


class NewProjectDialog(QDialog):
    """Novo projeto: nome e controlador do CLP (define as quantidades de E/S e de variaveis)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Novo projeto")
        self.setMinimumWidth(480)
        form = QFormLayout()
        self.name = QLineEdit("Novo projeto")
        self.controller = _controller_combo(default_controller().id)
        form.addRow("Nome:", self.name)
        form.addRow("Controlador:", self.controller)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setObjectName("muted")
        self.controller.currentIndexChanged.connect(self._update)
        self._update()
        hint = QLabel("O controlador limita as entradas, as saidas e a quantidade de memorias, temporizadores, "
                      "contadores e registradores. Pode ser trocado depois em Programa > Propriedades.")
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(self.details)
        box.addWidget(hint)
        box.addWidget(buttons)
        self.adjustSize()

    def _update(self) -> None:
        self.details.setText(_controller_text(controller_by_id(self.controller.currentData())))

    def project(self) -> Project:
        p = Project(name=self.name.text().strip() or "Novo projeto")
        ctrl = controller_by_id(self.controller.currentData())
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
        form.addRow("Versao:", self.version)
        form.addRow("Descricao:", self.description)
        self.controller = _controller_combo(project.target.device)
        self.controller_info = QLabel()
        self.controller_info.setWordWrap(True)
        self.controller_info.setObjectName("muted")
        form.addRow("Controlador:", self.controller)
        self.n_inputs = self._spin(1, isa.MAX_INPUTS, io.n_inputs)
        self.n_outputs = self._spin(1, isa.MAX_OUTPUTS, io.n_outputs)
        self.n_markers = self._spin(0, isa.MAX_MARKERS, io.n_markers)
        self.n_words = self._spin(0, isa.MAX_WORDS, io.n_words)
        self.period = self._spin(1, 1000, io.scan_period_ms)
        self.period.setSuffix(" ms")
        form.addRow("Entradas digitais:", self.n_inputs)
        form.addRow("Saidas (reles):", self.n_outputs)
        form.addRow("Memorias M:", self.n_markers)
        form.addRow("Registradores N (inteiros):", self.n_words)
        form.addRow("Periodo de varredura:", self.period)
        safe = QGroupBox("Estado seguro das saidas em STOP/FAULT (marcado = energizado)")
        grid = QGridLayout(safe)
        self.safe: list[QCheckBox] = []
        for k in range(isa.MAX_OUTPUTS):
            cb = QCheckBox(f"Q{k // 8}.{k % 8}")
            cb.setChecked(bool(io.safe_outputs >> k & 1))
            grid.addWidget(cb, k // 8, k % 8)
            self.safe.append(cb)
        self.controller.currentIndexChanged.connect(self._controller_changed)
        self._controller_changed()
        warn = QLabel("Atencao: desenergizar nem sempre e o estado seguro da carga. "
                      "Defina conforme a aplicacao.")
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

    def _controller_changed(self) -> None:
        """Os maximos dos campos passam a ser os do controlador; valores acima sao reduzidos."""
        ctrl = controller_by_id(self.controller.currentData())
        self.controller_info.setText(_controller_text(ctrl))
        limits = ((self.n_inputs, ctrl.inputs if ctrl else isa.MAX_INPUTS),
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
