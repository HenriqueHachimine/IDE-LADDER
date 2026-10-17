"""Janela com o relatorio de verificacao do programa para o ESP32."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from ..verify.esp32 import ERROR, INFO, OK, SKIP, WARN, VerifyReport
from . import theme

STYLE = {OK: ("✔", "#15803d"), WARN: ("⚠", "#b45309"), ERROR: ("✖", "#b91c1c"),
         SKIP: ("–", "#64748b"), INFO: ("i", "#2563eb")}


class VerifyDialog(QDialog):
    def __init__(self, report: VerifyReport, parent=None):
        super().__init__(parent)
        self.report = report
        self.setWindowTitle("Verificacao para o ESP32")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        banner = QLabel(report.summary())
        bg, fg = (("#fee2e2", "#991b1b") if report.errors else
                  ("#fef3c7", "#92400e") if report.warnings else ("#dcfce7", "#166534"))
        banner.setStyleSheet(f"background:{bg}; color:{fg}; font-weight:600; font-size:11pt; "
                             "padding:10px; border-radius:8px;")
        layout.addWidget(banner)
        sub = QLabel(f"Placa: {report.board.hardware}, firmware {report.board.firmware} "
                     f"({report.board.inputs} entradas, {report.board.outputs} reles, varredura "
                     f"{report.board.scan_period_ms} ms, watchdog {report.board.watchdog_us // 1000} ms).")
        sub.setWordWrap(True)
        sub.setObjectName("muted")
        layout.addWidget(sub)
        self.table = QTableWidget(len(report.checks), 3)
        self.table.setHorizontalHeaderLabels(["", "Verificacao", "Resultado"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 30)
        for row, c in enumerate(report.checks):
            icon, color = STYLE.get(c.status, ("?", "#000"))
            cells = [QTableWidgetItem(icon), QTableWidgetItem(c.title), QTableWidgetItem(c.detail)]
            cells[0].setForeground(QColor(color))
            cells[0].setTextAlignment(Qt.AlignCenter)
            cells[1].setForeground(QColor(color) if c.status in (ERROR, WARN) else theme.color("TEXT"))
            cells[1].setToolTip(c.status)
            for col, cell in enumerate(cells):
                if col:
                    cell.setTextAlignment(Qt.AlignLeft | Qt.AlignTop)
                self.table.setItem(row, col, cell)
        layout.addWidget(self.table, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        copy = QPushButton("Copiar relatorio")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(report.as_text()))
        buttons.addButton(copy, QDialogButtonBox.ActionRole)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.table.resizeRowsToContents()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.table.resizeRowsToContents()
