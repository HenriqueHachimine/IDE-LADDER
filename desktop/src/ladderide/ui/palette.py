"""Paleta de instrucoes: arraste para o diagrama ou clique para inserir apos a selecao."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QSize, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QApplication, QGroupBox, QLabel, QScrollArea, QToolButton, QVBoxLayout,
                               QGridLayout, QWidget)

from .ladder_view import MIME_TOOL
from .symbols import tool_icon

GROUPS = [
    ("Contatos", [("XIC", "NA", "Contato normalmente aberto (XIC): conduz quando o bit = 1"),
                  ("XIO", "NF", "Contato normalmente fechado (XIO): conduz quando o bit = 0"),
                  ("NOT", "NOT", "Inverte o resultado logico ate este ponto")]),
    ("Ramificacao", [("PAR", "Paralelo", "Ramificacao paralela (logica OU). Solte entre contatos")]),
    ("Bobinas", [("OTE", "Bobina", "Bobina comum: bit = resultado da rede"),
                 ("OTL", "SET", "Bobina SET (OTL): liga e mantem"),
                 ("OTU", "RESET", "Bobina RESET (OTU): desliga")]),
    ("Temporizadores", [("TON", "TON", "Retardo na energizacao"),
                        ("TOF", "TOF", "Retardo na desenergizacao"),
                        ("RTO", "RTO", "Retardo retentivo (acumula; zera com RES)")]),
    ("Contadores", [("CTU", "CTU", "Contador crescente (borda de subida)"),
                    ("CTD", "CTD", "Contador decrescente (borda de subida)"),
                    ("RES", "RES", "Reset de temporizador ou contador")]),
    ("Comparacao", [("EQU", "EQU", "Igual: conduz se A = B"),
                    ("NEQ", "NEQ", "Diferente: conduz se A \u2260 B"),
                    ("LES", "LES", "Menor: conduz se A < B"),
                    ("GRT", "GRT", "Maior: conduz se A > B"),
                    ("LEQ", "LEQ", "Menor ou igual: conduz se A \u2264 B"),
                    ("GEQ", "GEQ", "Maior ou igual: conduz se A \u2265 B"),
                    ("LIM", "LIM", "Teste de limite: conduz se inferior \u2264 teste \u2264 superior"),
                    ("MEQ", "MEQ", "Comparacao com mascara: (origem AND mascara) = (comparar AND mascara)")]),
    ("Matematica", [("ADD", "ADD", "Soma: destino = A + B"),
                    ("SUB", "SUB", "Subtracao: destino = A - B"),
                    ("MUL", "MUL", "Multiplicacao: destino = A \u00d7 B"),
                    ("DIV", "DIV", "Divisao inteira: destino = A \u00f7 B"),
                    ("SQR", "SQR", "Raiz quadrada (arredondada)"),
                    ("NEG", "NEG", "Troca o sinal: destino = -origem"),
                    ("TOD", "TOD", "Converte inteiro para BCD"),
                    ("FRD", "FRD", "Converte BCD para inteiro")]),
]


class ToolButton(QToolButton):
    def __init__(self, tool: str, text: str, tip: str, parent=None):
        super().__init__(parent)
        self.tool = tool
        self.setText(text)
        self.setToolTip(tip + "\n\nArraste para o diagrama ou clique para inserir apos a selecao.")
        self.setIcon(tool_icon(tool))
        self.setIconSize(QSize(44, 27))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setAutoRaise(True)
        self.setMinimumWidth(56)
        self._press = None

    def mousePressEvent(self, event) -> None:
        self._press = event.position()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press is not None and event.buttons() & Qt.LeftButton
                and (event.position() - self._press).manhattanLength() > QApplication.startDragDistance()):
            self._press = None
            self.setDown(False)
            mime = QMimeData()
            mime.setData(MIME_TOOL, self.tool.encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(self.icon().pixmap(56, 34))
            drag.exec(Qt.CopyAction)
            return
        super().mouseMoveEvent(event)


class Palette(QScrollArea):
    toolClicked = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        self.buttons: list[ToolButton] = []
        for title, tools in GROUPS:
            box = QGroupBox(title)
            grid = QGridLayout(box)
            grid.setContentsMargins(4, 6, 4, 4)
            grid.setSpacing(2)
            for k, (tool, text, tip) in enumerate(tools):
                b = ToolButton(tool, text, tip)
                b.clicked.connect(lambda _=False, t=tool: self.toolClicked.emit(t))
                grid.addWidget(b, k // 3, k % 3)
                self.buttons.append(b)
            layout.addWidget(box)
        hint = QLabel("Arraste para o diagrama ou clique para inserir apos o elemento selecionado. "
                      "Nova rede: Ctrl+R.")
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        layout.addWidget(hint)
        layout.addStretch(1)
        self.setWidget(body)

    def theme_changed(self) -> None:
        for b in self.buttons:
            b.setIcon(tool_icon(b.tool))

    def set_enabled(self, enabled: bool) -> None:
        for b in self.buttons:
            b.setEnabled(enabled)
