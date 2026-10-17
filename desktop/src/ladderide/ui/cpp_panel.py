"""Painel 'Codigo C++': o diagrama traduzido para C++ enquanto o usuario edita (antes de compilar)."""
from __future__ import annotations

import re

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QSyntaxHighlighter, QTextCharFormat, QTextCursor, QTextFormat
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextEdit,
                               QVBoxLayout, QWidget)

from ..codegen import generate_cpp
from .fonts import mono_font
from .theme import themed

KEYWORD = themed("#7c3aed", "#c4b5fd")
TYPE = themed("#0369a1", "#7dd3fc")
FUNCTION = themed("#b45309", "#fcd34d")
NUMBER = themed("#047857", "#6ee7b7")
COMMENT = themed("#64748b", "#94a3b8")
PREPROC = themed("#9d174d", "#f9a8d4")
ERROR = themed("#dc2626", "#f87171")
WARNING = themed("#b45309", "#fbbf24")
RUNG_BG = themed("#eef2ff", "#1e2a4a")

_KEYWORDS = r"\b(if|else|for|return|static|inline|struct|void|true|false|namespace|const)\b"
_TYPES = r"\b(bool|int|uint8_t|uint16_t|uint32_t|int32_t|Timer|Counter)\b"
_FUNCS = r"\b(TON|TOF|RTO|CTU|CTD|RES|plc_scan|plc_start|counter_reset|sat_add|setup|loop)\b(?=\s*\()"


class CppHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        self.rules: list[tuple[re.Pattern, QColor, bool]] = [
            (re.compile(_KEYWORDS), KEYWORD, True),
            (re.compile(_TYPES), TYPE, False),
            (re.compile(_FUNCS), FUNCTION, True),
            (re.compile(r"\b\d+u?\b"), NUMBER, False),
        ]

    def _fmt(self, color: QColor, bold: bool = False) -> QTextCharFormat:
        f = QTextCharFormat()
        f.setForeground(color)
        if bold:
            f.setFontWeight(700)
        return f

    def highlightBlock(self, text: str) -> None:
        stripped = text.lstrip()
        if stripped.startswith("#"):
            self.setFormat(0, len(text), self._fmt(PREPROC))
            return
        code_end = text.find("//")
        code = text if code_end < 0 else text[:code_end]
        for pattern, color, bold in self.rules:
            for m in pattern.finditer(code):
                self.setFormat(m.start(), m.end() - m.start(), self._fmt(color, bold))
        if code_end >= 0:
            comment = text[code_end:]
            if comment.startswith("// ERRO"):
                fmt = self._fmt(ERROR, True)
            elif comment.startswith("// AVISO"):
                fmt = self._fmt(WARNING, True)
            elif comment.startswith("// =====") or comment.startswith("// -----"):
                fmt = self._fmt(COMMENT, True)
            else:
                fmt = self._fmt(COMMENT)
                fmt.setFontItalic(True)
            self.setFormat(code_end, len(comment), fmt)


class CppPanel(QWidget):
    elementActivated = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setObjectName("muted")
        layout.addWidget(self.info)
        self.editor = QPlainTextEdit()
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setFont(mono_font(9))
        self.editor.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.editor.cursorPositionChanged.connect(self._cursor_moved)
        self.highlighter = CppHighlighter(self.editor.document())
        layout.addWidget(self.editor, 1)
        row = QHBoxLayout()
        self.copy_btn = QPushButton("Copiar codigo")
        self.save_btn = QPushButton("Salvar .cpp...")
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        self.save_btn.clicked.connect(self._save)
        row.addWidget(self.copy_btn)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        layout.addLayout(row)
        self.project = None
        self.code = None
        self.text = ""
        self._key = None
        self._syncing = False
        self._rung = None

    # ------------------------------------------------------------ conteudo
    def set_project(self, project, force: bool = False) -> None:
        """Regera o C++ a partir do diagrama (rapido; nao depende da compilacao)."""
        self.project = project
        code = generate_cpp(project)
        if not force and code.text == self.text:
            self.code = code
            return
        self.code = code
        self.text = code.text
        bar = self.editor.verticalScrollBar()
        pos = bar.value()
        self._syncing = True
        self.editor.setPlainText(code.text)
        self._syncing = False
        bar.setValue(pos)
        if code.errors:
            status = (f"{code.errors} erro(s) no diagrama: as linhas afetadas estao marcadas com ERRO e o "
                      "operando invalido aparece como false.")
        else:
            status = "Sem erros." + (f" {code.warnings} aviso(s)." if code.warnings else "")
        self.info.setText(f"Traducao do diagrama para C++, atualizada a cada edicao (nao precisa compilar). "
                          f"{len(code.rung_lines)} redes. {status} Clique numa linha para localizar a rede.")
        self._paint_rung(self._rung)

    def theme_changed(self) -> None:
        self.highlighter.rehighlight()
        self._paint_rung(self._rung)

    # ---------------------------------------------------------- navegacao
    def highlight(self, element_id) -> None:
        """Destaca as linhas da rede do elemento selecionado no diagrama."""
        rung = None
        if isinstance(element_id, tuple) and len(element_id) == 2 and element_id[0] == "rung":
            rung = element_id[1]                       # rede inteira selecionada
        elif isinstance(element_id, str) and self.project is not None:
            hit = self.project.find(element_id)
            if hit is not None:
                rung = hit[0]
            else:
                rung = self.project.rung_index_of(element_id)
        self._paint_rung(rung, scroll=True)

    def _paint_rung(self, rung, scroll: bool = False) -> None:
        self._rung = rung
        sels = []
        if self.code is not None and rung is not None and rung < len(self.code.rung_lines):
            first, last = self.code.rung_lines[rung]
            doc = self.editor.document()
            sel = QTextEdit.ExtraSelection()
            sel.format.setBackground(RUNG_BG)
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            cur = QTextCursor(doc.findBlockByNumber(first))
            cur.movePosition(QTextCursor.NextBlock, QTextCursor.KeepAnchor, last - first)
            cur.movePosition(QTextCursor.EndOfBlock, QTextCursor.KeepAnchor)
            sel.cursor = cur
            sels.append(sel)
            if scroll:                                 # rede no alto da area visivel
                self.editor.verticalScrollBar().setValue(max(0, first - 1))
        self.editor.setExtraSelections(sels)

    def _cursor_moved(self) -> None:
        if self._syncing or self.code is None:
            return
        rung = self.code.rung_at_line(self.editor.textCursor().blockNumber())
        if rung is None:
            return
        self._paint_rung(rung)
        element = self.code.rung_first_element[rung]
        if element:
            self.elementActivated.emit(element)

    def _save(self) -> None:
        name = (self.project.name if self.project else "programa").strip() or "programa"
        safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name)
        path, _ = QFileDialog.getSaveFileName(self, "Salvar codigo C++", f"{safe}.cpp", "Codigo C++ (*.cpp)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text)
