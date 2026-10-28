"""Painel "Processo": onde o programa LADDER age, um de cada vez.

Ambiente animado, Factory IO e Placa (ESP32/Arduino virtual) sao alternativas:
o programa comanda um processo de cada vez. Em vez de tres abas soltas, um
seletor no topo escolhe o processo e mostra o painel correspondente, com uma
frase dizendo para que serve. O selo de cada opcao mostra o que esta ativo.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel, QPushButton, QScrollArea, QStackedWidget,
                               QVBoxLayout, QWidget)

PAGES = {
    "env": ("Ambiente animado",
            "Processo desenhado na IDE (semáforo, silo, portão...) comandado pela simulação."),
    "fio": ("Factory IO",
            "Cena 3D do Factory IO ligada à simulação pelo driver Modbus TCP/IP Server."),
    "board": ("Placa ESP32 / Arduino",
              "O firmware do CLP rodando no PC como a placa real: transferência, RUN/STOP e relés."),
}


SCROLLED = {"fio"}


class _CurrentPageStack(QStackedWidget):
    """Tamanho minimo so da pagina visivel: a pagina mais alta nao prende a altura do painel."""

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()


class ProcessPanel(QWidget):
    pageChanged = Signal(str)

    def __init__(self, panels: dict[str, QWidget], parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 0)
        layout.setSpacing(4)
        bar = QHBoxLayout()
        bar.setSpacing(0)
        bar.addWidget(QLabel("Processo:  "))
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        self.status: dict[str, str] = {}
        keys = list(PAGES)
        for i, key in enumerate(keys):
            b = QPushButton(PAGES[key][0])
            b.setCheckable(True)
            b.setObjectName("segment")
            b.setProperty("pos", "first" if i == 0 else "last" if i == len(keys) - 1 else "middle")
            b.setToolTip(PAGES[key][1])
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            self.group.addButton(b)
            self.buttons[key] = b
            self._fit(b)
            bar.addWidget(b)
        bar.addSpacing(12)
        self.description = QLabel()
        self.description.setObjectName("muted")
        self.description.setWordWrap(True)
        bar.addWidget(self.description, 1)
        layout.addLayout(bar)
        self.stack = _CurrentPageStack()
        self.pages: dict[str, int] = {}
        for key in keys:
            page = panels[key]
            if key in SCROLLED:                      # tabelas longas rolam; cena e placa se ajustam
                page = QScrollArea()
                page.setWidget(panels[key])
                page.setWidgetResizable(True)
                page.setFrameShape(QScrollArea.NoFrame)
                page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.pages[key] = self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)
        self.current = ""
        self.show_page("env")

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self.stack.setCurrentIndex(self.pages[key])
        self.stack.updateGeometry()
        self.buttons[key].setChecked(True)
        self.description.setText(PAGES[key][1])
        if key != self.current:
            self.current = key
            self.pageChanged.emit(key)

    def set_status(self, key: str, text: str) -> None:
        """Selo curto na opcao (ex.: "conectado"): mostra o que esta ativo sem abrir a pagina."""
        if self.status.get(key, "") == text:
            return
        self.status[key] = text
        self.buttons[key].setText(PAGES[key][0] + (f"  ● {text}" if text else ""))
        self._fit(self.buttons[key])

    @staticmethod
    def _fit(b: QPushButton) -> None:
        """Largura do segmento = texto + margens do estilo (a folha de estilo nao entra no sizeHint)."""
        bold = QFont(b.font())
        bold.setBold(True)                           # o segmento escolhido fica em negrito
        b.setFixedWidth(QFontMetrics(bold).horizontalAdvance(b.text()) + 36)
