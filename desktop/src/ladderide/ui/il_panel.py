"""Painel 'Blocos de instrucao': o diagrama LADDER convertido em lista de instrucoes por rede."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..verify.il_blocks import il_blocks, il_text

POWER_ON = QColor("#15803d")
POWER_OFF = QColor("#64748b")
CURRENT_BG = QColor("#ffedd5")
BLOCK_BG = QColor("#eef2ff")


class ILPanel(QWidget):
    elementActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color:#475569;")
        layout.addWidget(self.info)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["#", "Instrucao", "Operando", "Simbolo", "O que faz"])
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        h = self.tree.header()
        for col in range(4):
            h.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(4, QHeaderView.Stretch)
        self.tree.itemClicked.connect(self._clicked)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.expand_btn = QPushButton("Expandir tudo")
        self.collapse_btn = QPushButton("Recolher tudo")
        self.copy_btn = QPushButton("Copiar texto")
        self.save_btn = QPushButton("Salvar .il...")
        self.expand_btn.clicked.connect(self.tree.expandAll)
        self.collapse_btn.clicked.connect(self.tree.collapseAll)
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        self.save_btn.clicked.connect(self._save)
        for b in (self.expand_btn, self.collapse_btn, self.copy_btn, self.save_btn):
            row.addWidget(b)
        row.addStretch(1)
        layout.addLayout(row)
        self.mono = QFont("Consolas", 9)
        self.line_items: list[QTreeWidgetItem] = []      # indice = pc
        self.items_by_element: dict[str, list[QTreeWidgetItem]] = {}
        self.text = ""
        self._last_power: list | None = None
        self._last_pc: int | None = None
        self.set_program(None, None)

    # ------------------------------------------------------------ conteudo
    def set_program(self, project, result) -> None:
        self.tree.clear()
        self.line_items, self.items_by_element = [], {}
        self._last_power = self._last_pc = None
        if project is None or result is None or not result.ok:
            self.text = ""
            self.info.setText("Corrija os erros de compilacao para ver os blocos de instrucao."
                              if result is not None else "Os blocos aparecem aqui depois da compilacao.")
            for b in (self.copy_btn, self.save_btn):
                b.setEnabled(False)
            return
        blocks = il_blocks(project, result)
        self.text = il_text(blocks, f"{project.name} - lista de instrucoes gerada pela LadderIDE "
                                    f"(id 0x{result.build_id:08x})")
        self.info.setText(f"{len(blocks)} blocos (um por rede), {len(result.program.code)} instrucoes - "
                          "exatamente o que o ESP32 executa, na mesma ordem. Clique numa linha para "
                          "localizar o elemento no diagrama.")
        bold = QFont(self.font())
        bold.setBold(True)
        for b in blocks:
            title = f"Rede {b.rung}" + (f"  -  {b.comment}" if b.comment else "")
            top = QTreeWidgetItem([title])
            top.setFirstColumnSpanned(True)
            top.setFont(0, bold)
            for col in range(5):
                top.setBackground(col, QBrush(BLOCK_BG))
            top.setData(0, Qt.UserRole, None)
            self.tree.addTopLevelItem(top)
            for ln in b.lines:
                item = QTreeWidgetItem([f"{ln.pc:04d}", "  " * ln.depth + ln.mnemonic, ln.operand, ln.symbol,
                                        ln.description])
                for col in (0, 1, 2):
                    item.setFont(col, self.mono)
                item.setData(0, Qt.UserRole, ln.element_id)
                item.setToolTip(4, ln.description)
                top.addChild(item)
                self.line_items.append(item)
                if ln.element_id:
                    self.items_by_element.setdefault(ln.element_id, []).append(item)
            top.setFirstColumnSpanned(True)
        self.tree.expandAll()
        for b in (self.copy_btn, self.save_btn):
            b.setEnabled(True)

    def _clicked(self, item: QTreeWidgetItem) -> None:
        element_id = item.data(0, Qt.UserRole)
        if element_id:
            self.elementActivated.emit(element_id)

    def highlight(self, element_id) -> None:
        items = self.items_by_element.get(element_id, []) if isinstance(element_id, str) else []
        self.tree.blockSignals(True)
        self.tree.clearSelection()
        for it in items:
            it.setSelected(True)
        if items:
            self.tree.scrollToItem(items[0])
        self.tree.blockSignals(False)

    def update_live(self, power: list | None, pc: int | None) -> None:
        """Pinta cada instrucao com o RLO (verde = 1) e destaca a proxima no passo a passo."""
        if not self.line_items:
            return
        power = list(power) if power is not None else None
        if power == self._last_power and pc == self._last_pc:
            return
        self._last_power, self._last_pc = power, pc
        for k, item in enumerate(self.line_items):
            if power is None:
                color = QColor("#0f172a")
            else:
                color = POWER_ON if k < len(power) and power[k] else POWER_OFF
            for col in (1, 2, 3):
                item.setForeground(col, color)
            bg = QBrush(CURRENT_BG) if k == pc else QBrush()
            for col in range(5):
                item.setBackground(col, bg)
        if pc is not None and 0 <= pc < len(self.line_items):
            self.tree.scrollToItem(self.line_items[pc])

    def _save(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar lista de instrucoes", "", "Lista de instrucoes (*.il)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text)
