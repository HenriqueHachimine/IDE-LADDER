"""Painel Variaveis: variaveis de memoria boolean, inteira e float, com endereco automatico."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..model import variables
from ..model.project import VARIABLE_TYPES, Project

COL_NAME, COL_TYPE, COL_INITIAL, COL_ADDRESS, COL_COMMENT = range(5)
FIELDS = {COL_NAME: "name", COL_INITIAL: "initial", COL_COMMENT: "comment"}


class VariablesPanel(QWidget):
    edited = Signal(int, str, str)      # linha, campo do Variable, novo valor
    addRequested = Signal()
    removeRequested = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.add_btn = QPushButton("Adicionar variável")
        self.remove_btn = QPushButton("Remover selecionada")
        self.add_btn.clicked.connect(self.addRequested)
        self.remove_btn.clicked.connect(lambda: self.removeRequested.emit(self.table.currentRow()))
        hint = QLabel("Use o nome no diagrama. O valor volta ao inicial a cada partida; guarde valores com o bloco MOV.")
        hint.setObjectName("hint")
        row.addWidget(self.add_btn)
        row.addWidget(self.remove_btn)
        row.addWidget(hint, 1)
        layout.addLayout(row)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nome", "Tipo", "Valor inicial", "Endereço", "Comentário"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.cellChanged.connect(self._cell_changed)
        layout.addWidget(self.table)

    def load(self, project: Project) -> None:
        table = variables.addresses(project)
        self.table.blockSignals(True)
        self.table.setRowCount(len(project.variables))
        for row, v in enumerate(project.variables):
            self.table.setItem(row, COL_NAME, QTableWidgetItem(v.name))
            self.table.setCellWidget(row, COL_TYPE, self._type_combo(row, v.type))
            self.table.setItem(row, COL_INITIAL, QTableWidgetItem(v.initial))
            address = QTableWidgetItem(table.get(v.name) or "sem espaço")
            address.setFlags(address.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, COL_ADDRESS, address)
            self.table.setItem(row, COL_COMMENT, QTableWidgetItem(v.comment))
        self.table.blockSignals(False)

    def _type_combo(self, row: int, current: str) -> QComboBox:
        combo = QComboBox()
        for key, label in VARIABLE_TYPES.items():
            combo.addItem(label, key)
        combo.setCurrentIndex(combo.findData(current))
        combo.activated.connect(lambda _=0, r=row, c=combo: self.edited.emit(r, "type", c.currentData()))
        return combo

    def _cell_changed(self, row: int, col: int) -> None:
        if col in FIELDS:
            self.edited.emit(row, FIELDS[col], self.table.item(row, col).text().strip())

    def set_editable(self, editable: bool) -> None:
        self.setEnabled(editable)
