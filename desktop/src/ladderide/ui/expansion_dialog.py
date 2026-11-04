"""Dialogo "Modulos de expansao": encaixar modulos de E/S no CLP do projeto.

Lista os modulos encaixados (na ordem do barramento), deixa acrescentar os que
servem no CPU, remover e mudar a ordem, e mostra as E/S totais e os enderecos de
cada modulo na IDE (I/Q) e no CLP (X/Y no CLIC-02, canais CIO no CP1E). Regras
em model/expansions.py.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.asm import format_operand
from ..core.isa import Area
from ..model import expansions
from . import theme


def _span(area: Area, first: int, count: int) -> str:
    if not count:
        return ""
    return f"{format_operand(area, first)} a {format_operand(area, first + count - 1)}"


class ExpansionDialog(QDialog):
    def __init__(self, ctrl, ids: list[str], parent=None):
        super().__init__(parent)
        self.ctrl = ctrl
        self.setWindowTitle("Módulos de expansão")
        self.setMinimumWidth(720)
        box = QVBoxLayout(self)
        head = QLabel()
        head.setWordWrap(True)
        head.setTextFormat(Qt.RichText)
        n = getattr(ctrl, "max_expansions", 0) if ctrl is not None else 0
        name = ctrl.name if ctrl is not None else "Controlador desconhecido"
        if n:
            head.setText(f"<b>{name}</b>: {ctrl.inputs} entradas e {ctrl.outputs} saídas no CPU; aceita até "
                         f"<b>{n} módulos</b>. As E/S dos módulos vêm depois das do CPU, na ordem em que estão "
                         "encaixados.")
        else:
            head.setText(f"<b>{name}</b> não aceita módulos de expansão. No CLIC-02 todos os modelos aceitam; "
                         "no CP1E, só os CPUs de 30 e 40 pontos e o NA20 (manual W480, 6-1-3).")
        box.addWidget(head)

        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMinimumHeight(120)
        self.list.currentRowChanged.connect(self._update_buttons)
        row.addWidget(self.list, 1)
        side = QVBoxLayout()
        self.catalog = QComboBox()
        for m in expansions.compatible(ctrl):
            self.catalog.addItem(m.label, m.id)
        side.addWidget(self.catalog)
        self.add_btn = QPushButton("Adicionar")
        self.add_btn.clicked.connect(self._add)
        self.remove_btn = QPushButton("Remover")
        self.remove_btn.clicked.connect(self._remove)
        self.up_btn = QPushButton("Subir")
        self.up_btn.clicked.connect(lambda: self._move(-1))
        self.down_btn = QPushButton("Descer")
        self.down_btn.clicked.connect(lambda: self._move(1))
        for b in (self.add_btn, self.remove_btn, self.up_btn, self.down_btn):
            side.addWidget(b)
        side.addStretch(1)
        row.addLayout(side)
        box.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Módulo", "Entradas na IDE", "No CLP", "Saídas na IDE", "No CLP"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(130)
        box.addWidget(self.table)
        self.total = QLabel()
        self.total.setWordWrap(True)
        box.addWidget(self.total)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        box.addWidget(self.buttons)
        for i in ids:
            if i in expansions.BY_ID:
                self._append(expansions.BY_ID[i])
        self._refresh()

    # ------------------------------------------------------------ lista
    def modules(self) -> list[expansions.Expansion]:
        return [expansions.BY_ID[self.list.item(k).data(Qt.UserRole)] for k in range(self.list.count())]

    def ids(self) -> list[str]:
        return [m.id for m in self.modules()]

    def _append(self, m: expansions.Expansion) -> None:
        item = QListWidgetItem(m.label)
        item.setData(Qt.UserRole, m.id)
        self.list.addItem(item)

    def _add(self) -> None:
        mid = self.catalog.currentData()
        if mid:
            self._append(expansions.BY_ID[mid])
            self.list.setCurrentRow(self.list.count() - 1)
            self._refresh()

    def _remove(self) -> None:
        row = self.list.currentRow()
        if row >= 0:
            self.list.takeItem(row)
            self._refresh()

    def _move(self, delta: int) -> None:
        row = self.list.currentRow()
        to = row + delta
        if row < 0 or not 0 <= to < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(to, item)
        self.list.setCurrentRow(to)
        self._refresh()

    def _update_buttons(self, *_args) -> None:
        row = self.list.currentRow()
        limit = getattr(self.ctrl, "max_expansions", 0) if self.ctrl is not None else 0
        self.add_btn.setEnabled(self.catalog.count() > 0 and self.list.count() < limit)
        self.catalog.setEnabled(self.add_btn.isEnabled())
        self.remove_btn.setEnabled(row >= 0)
        self.up_btn.setEnabled(row > 0)
        self.down_btn.setEnabled(0 <= row < self.list.count() - 1)

    def _refresh(self) -> None:
        mods = self.modules()
        problems = expansions.problems(self.ctrl, mods)
        rows = expansions.addresses(self.ctrl, mods) if self.ctrl is not None and not problems else []
        self.table.setRowCount(len(rows))
        for r, a in enumerate(rows):
            m = a["module"]
            for c, text in enumerate((m.catalog, _span(Area.I, a["in_first"], m.inputs), a["plc_in"],
                                      _span(Area.Q, a["out_first"], m.outputs), a["plc_out"])):
                self.table.setItem(r, c, QTableWidgetItem(text or "-"))
        if self.ctrl is not None:
            n_in, n_out = expansions.total_io(self.ctrl, mods)
            text = (f"Total do projeto: <b>{n_in} entradas</b> ({self.ctrl.inputs} do CPU + {n_in - self.ctrl.inputs}"
                    f" dos módulos) e <b>{n_out} saídas</b> ({self.ctrl.outputs} + {n_out - self.ctrl.outputs}).")
        else:
            text = ""
        if problems:
            text += f"<br><span style='color:{theme.colors['DANGER']}'>" + "; ".join(problems).capitalize() + ".</span>"
        self.total.setText(text)
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(not problems)
        self._update_buttons()
