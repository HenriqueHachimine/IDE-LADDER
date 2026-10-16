"""Dialogos de edicao de elemento e de propriedades do projeto."""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
                               QGroupBox, QLabel, QLineEdit, QPlainTextEdit, QSpinBox, QVBoxLayout)

from ..core import isa
from ..model.project import Coil, Contact, CounterBox, Project, ResetBox, TimerBox

KIND_CHOICES = {
    Contact: [("XIC", "Normalmente aberto (NA / XIC)"), ("XIO", "Normalmente fechado (NF / XIO)")],
    Coil: [("OTE", "Bobina comum (OTE)"), ("OTL", "SET / liga e mantem (OTL)"), ("OTU", "RESET / desliga (OTU)")],
    TimerBox: [("TON", "TON - retardo na energizacao"), ("TOF", "TOF - retardo na desenergizacao"),
               ("RTO", "RTO - retentivo")],
    CounterBox: [("CTU", "CTU - crescente"), ("CTD", "CTD - decrescente")],
}


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
        self.setWindowTitle("Editar elemento")
        form = QFormLayout()
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
        help_text.setStyleSheet("color: #64748b;")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(help_text)
        box.addWidget(buttons)

    def _update_seconds(self) -> None:
        self.seconds.setText(f"= {self.preset.value() / 1000:.3f} s")

    def apply(self) -> None:
        if self.kind is not None:
            self.node.kind = self.kind.currentData()
        self.node.operand = self.operand.currentText().strip()
        if self.preset is not None:
            self.node.preset = self.preset.value()


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
        self.n_inputs = self._spin(1, isa.MAX_INPUTS, io.n_inputs)
        self.n_outputs = self._spin(1, isa.MAX_OUTPUTS, io.n_outputs)
        self.n_markers = self._spin(0, isa.MAX_MARKERS, io.n_markers)
        self.period = self._spin(1, 1000, io.scan_period_ms)
        self.period.setSuffix(" ms")
        form.addRow("Entradas digitais:", self.n_inputs)
        form.addRow("Saidas (reles):", self.n_outputs)
        form.addRow("Memorias M:", self.n_markers)
        form.addRow("Periodo de varredura:", self.period)
        safe = QGroupBox("Estado seguro das saidas em STOP/FAULT (marcado = energizado)")
        grid = QGridLayout(safe)
        self.safe: list[QCheckBox] = []
        for k in range(isa.MAX_OUTPUTS):
            cb = QCheckBox(f"Q{k // 8}.{k % 8}")
            cb.setChecked(bool(io.safe_outputs >> k & 1))
            grid.addWidget(cb, k // 8, k % 8)
            self.safe.append(cb)
        warn = QLabel("Atencao: desenergizar nem sempre e o estado seguro da carga. "
                      "Defina conforme a aplicacao.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #b45309;")
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        box = QVBoxLayout(self)
        box.addLayout(form)
        box.addWidget(safe)
        box.addWidget(warn)
        box.addWidget(buttons)

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
        p.io.n_inputs = self.n_inputs.value()
        p.io.n_outputs = self.n_outputs.value()
        p.io.n_markers = self.n_markers.value()
        p.io.scan_period_ms = self.period.value()
        mask = sum(1 << k for k, cb in enumerate(self.safe) if cb.isChecked())
        p.io.safe_outputs = mask & ((1 << p.io.n_outputs) - 1)
