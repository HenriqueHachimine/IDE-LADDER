"""Painel de E/S e variaveis, compartilhado pelo simulador e pelo monitor online."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QGridLayout, QGroupBox, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.asm import format_operand, parse_operand
from ..core.isa import Area
from ..model.project import Project

LED_ON = "background:#16a34a; border:1px solid #14532d;"
LED_OFF = "background:#e2e8f0; border:1px solid #94a3b8;"
LED_UNKNOWN = "background:#f8fafc; border:1px dashed #94a3b8;"


class Led(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self.set(False)

    def set(self, value: bool | None) -> None:
        style = LED_UNKNOWN if value is None else (LED_ON if value else LED_OFF)
        self.setStyleSheet(f"border-radius:8px; {style}")


class IOPanel(QWidget):
    inputChanged = Signal(int, bool)

    def __init__(self, show_commanded: bool = False, parent=None):
        super().__init__(parent)
        self.show_commanded = show_commanded
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.inputs_box = QGroupBox("Entradas")
        self.inputs_grid = QGridLayout(self.inputs_box)
        self.momentary = QCheckBox("Botoes pulsadores (soltar desliga)")
        self.outputs_box = QGroupBox("Saidas")
        self.outputs_grid = QGridLayout(self.outputs_box)
        self.elements = QTableWidget(0, 4)
        self.elements.setHorizontalHeaderLabels(["Elemento", "PRE", "ACC", "Bits"])
        self.variables = QTableWidget(0, 3)
        self.variables.setHorizontalHeaderLabels(["Variavel", "Endereco", "Valor"])
        for t in (self.elements, self.variables):
            t.verticalHeader().hide()
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            t.setMinimumHeight(110)
            t.setAlternatingRowColors(True)
            t.setShowGrid(False)
        layout.addWidget(self.inputs_box)
        layout.addWidget(self.momentary)
        layout.addWidget(self.outputs_box)
        title = QLabel("Temporizadores e contadores")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(self.elements, 1)
        title = QLabel("Variaveis")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        layout.addWidget(self.variables, 1)
        self.input_buttons: list[QPushButton] = []
        self.out_leds: list[Led] = []
        self.cmd_leds: list[Led] = []
        self.element_rows: list[tuple[str, int]] = []
        self.var_rows: list[tuple[int, int]] = []
        self.editable = True

    @staticmethod
    def _clear(grid: QGridLayout) -> None:
        while grid.count():
            w = grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()

    def configure(self, project: Project, result=None) -> None:
        io = project.io
        self._clear(self.inputs_grid)
        self._clear(self.outputs_grid)
        self.input_buttons, self.out_leds, self.cmd_leds = [], [], []
        for k in range(io.n_inputs):
            addr = f"I{k // 8}.{k % 8}"
            name = project.symbol_for(addr)
            b = QPushButton(f"{addr}\n{name}" if name else addr)
            b.setCheckable(True)
            b.setMinimumHeight(42)
            b.pressed.connect(lambda k=k: self._pressed(k))
            b.released.connect(lambda k=k: self._released(k))
            b.toggled.connect(lambda v, k=k: self._toggled(k, v))
            self.inputs_grid.addWidget(b, k // 4, k % 4)
            self.input_buttons.append(b)
        if self.show_commanded:
            self.outputs_grid.addWidget(QLabel("Logico"), 0, 1)
            self.outputs_grid.addWidget(QLabel("Comandado"), 0, 2)
        for k in range(io.n_outputs):
            addr = f"Q{k // 8}.{k % 8}"
            name = project.symbol_for(addr)
            row = k + 1
            self.outputs_grid.addWidget(QLabel(f"{addr}  {name or ''}"), row, 0)
            led = Led()
            self.outputs_grid.addWidget(led, row, 1)
            self.out_leds.append(led)
            if self.show_commanded:
                cmd = Led()
                self.outputs_grid.addWidget(cmd, row, 2)
                self.cmd_leds.append(cmd)
        # temporizadores e contadores
        self.element_rows = []
        if result is not None and result.ok:
            for idx in sorted(result.timer_names):
                self.element_rows.append(("T", idx))
            for idx in sorted(result.counter_names):
                self.element_rows.append(("C", idx))
        self.elements.setRowCount(len(self.element_rows))
        for row, (kind, idx) in enumerate(self.element_rows):
            names = result.timer_names if kind == "T" else result.counter_names
            label = names[idx] if names[idx] == f"{kind}{idx}" else f"{names[idx]} ({kind}{idx})"
            self.elements.setItem(row, 0, QTableWidgetItem(label))
            defs = result.program.timers if kind == "T" else result.program.counters
            pre = defs[idx].preset_ms if kind == "T" else defs[idx].preset
            self.elements.setItem(row, 1, QTableWidgetItem(f"{pre}{' ms' if kind == 'T' else ''}"))
            for col in (2, 3):
                self.elements.setItem(row, col, QTableWidgetItem("-"))
        # variaveis: simbolos de bit + memorias usadas no programa
        refs: dict[tuple[int, int], str] = {}
        for s in project.symbols:
            try:
                ref = parse_operand(s.address)
            except ValueError:
                continue
            if ref[0] in (Area.I, Area.Q, Area.M):
                refs[ref] = s.name
        if result is not None and result.ok:
            for ref in result.element_operand.values():
                if ref[0] == Area.M:
                    refs.setdefault(ref, "")
        self.var_rows = sorted(refs, key=lambda r: (r[0], r[1]))
        self.variables.setRowCount(len(self.var_rows))
        for row, ref in enumerate(self.var_rows):
            self.variables.setItem(row, 0, QTableWidgetItem(refs[ref]))
            self.variables.setItem(row, 1, QTableWidgetItem(format_operand(*ref)))
            self.variables.setItem(row, 2, QTableWidgetItem("-"))

    # --------------------------------------------------------- entradas
    def set_inputs_editable(self, editable: bool) -> None:
        self.editable = editable
        self.momentary.setVisible(editable)
        for b in self.input_buttons:
            b.setEnabled(editable)

    def _pressed(self, k: int) -> None:
        if self.momentary.isChecked() and self.editable:
            self.input_buttons[k].setChecked(True)

    def _released(self, k: int) -> None:
        if self.momentary.isChecked() and self.editable:
            self.input_buttons[k].setChecked(False)

    def _toggled(self, k: int, value: bool) -> None:
        if self.editable:
            self.inputChanged.emit(k, value)

    # --------------------------------------------------------- valores
    def update_values(self, inputs: int | None, outputs: int | None, commanded: int | None,
                      timer: Callable[[int], dict | None], counter: Callable[[int], dict | None],
                      read: Callable[[int, int], bool | None]) -> None:
        for k, b in enumerate(self.input_buttons):
            if not self.editable and inputs is not None:
                b.blockSignals(True)
                b.setChecked(bool(inputs >> k & 1))
                b.blockSignals(False)
        for k, led in enumerate(self.out_leds):
            led.set(None if outputs is None else bool(outputs >> k & 1))
        for k, led in enumerate(self.cmd_leds):
            led.set(None if commanded is None else bool(commanded >> k & 1))
        for row, (kind, idx) in enumerate(self.element_rows):
            data = timer(idx) if kind == "T" else counter(idx)
            if data is None:
                acc, bits = "-", "-"
            else:
                acc = f"{data['acc']}{' ms' if kind == 'T' else ''}"
                bits = " ".join(f"{n}={int(v)}" for n, v in data["bits"].items())
            self.elements.item(row, 2).setText(acc)
            self.elements.item(row, 3).setText(bits)
        for row, ref in enumerate(self.var_rows):
            v = read(*ref)
            self.variables.item(row, 2).setText("-" if v is None else str(int(v)))
