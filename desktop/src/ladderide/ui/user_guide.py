"""Ajuda > Guia do usuario: o guia com as imagens das telas, dentro da IDE.

O conteudo fica em ladderide/help/guia_usuario.html (imagens em help/img). O
sumario sai dos <h2>/<h3> com <a name>, a busca destaca o texto no documento e
as imagens largas acompanham a largura do painel ({W} no HTML); clicar numa
imagem abre em tamanho real.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QImage, QPixmap, QTextDocument
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QSplitter,
                               QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

HELP_DIR = Path(__file__).resolve().parents[1] / "help"
GUIDE = HELP_DIR / "guia_usuario.html"
HEADING = re.compile(r'<h([23])><a name="([^"]+)"></a>(.*?)</h\1>', re.S)
IMAGE = re.compile(r'<img src="([^"]+)"([^>]*)>')


def load_guide() -> str:
    try:
        return GUIDE.read_text(encoding="utf-8")
    except OSError:
        return "<h2>Guia do usuário</h2><p>Arquivo do guia não encontrado nesta instalação.</p>"


def headings(text: str) -> list[tuple[int, str, str]]:
    """(nivel, ancora, titulo) de cada secao do guia, na ordem."""
    return [(int(level), anchor, html.unescape(re.sub(r"<[^>]+>", "", title)).strip())
            for level, anchor, title in HEADING.findall(text)]


class _GuideBrowser(QTextBrowser):
    """Reduz as imagens largas com suavizacao (o QTextBrowser so estica os pixels)."""

    def __init__(self):
        super().__init__()
        self.target_width = 0
        self._cache: dict[tuple[str, int], QImage] = {}

    def loadResource(self, kind, url):
        if kind == QTextDocument.ImageResource and self.target_width:
            image = QImage(str(HELP_DIR / url.toString()))
            dpr = self.devicePixelRatioF()
            px = int(self.target_width * dpr)
            if not image.isNull() and image.width() > px:
                key = (url.toString(), px)
                if key not in self._cache:
                    small = image.scaledToWidth(px, Qt.SmoothTransformation)
                    small.setDevicePixelRatio(dpr)
                    self._cache[key] = small
                return self._cache[key]
        return super().loadResource(kind, url)


class ImageDialog(QDialog):
    """Imagem do guia em tamanho real (clique numa imagem)."""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Guia do usuário - {path.stem}")
        label = QLabel()
        label.setPixmap(QPixmap(str(path)))
        area = QScrollArea()
        area.setWidget(label)
        layout = QVBoxLayout(self)
        layout.addWidget(area)
        size = label.pixmap().deviceIndependentSize().toSize()
        if self.screen() is not None:
            size = size.boundedTo(self.screen().availableGeometry().size() * 0.9)
        self.resize(size.width() + 40, size.height() + 40)


class UserGuideDialog(QDialog):
    """Janela nao modal com sumario, busca e o guia ilustrado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Guia do usuário")
        self.resize(1100, 760)
        self.source = load_guide()
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumWidth(200)
        parent_item = None
        for level, anchor, title in headings(self.source):
            item = QTreeWidgetItem([title])
            item.setData(0, Qt.UserRole, anchor)
            if level == 3 and parent_item is not None:
                parent_item.addChild(item)
            else:
                self.tree.addTopLevelItem(item)
                parent_item = item
        self.tree.expandAll()
        self.tree.itemClicked.connect(lambda item, _col: self.go(item.data(0, Qt.UserRole)))
        self.view = _GuideBrowser()
        self.view.setSearchPaths([str(HELP_DIR)])
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar no guia (Enter: próxima ocorrência)")
        self.search.setClearButtonEnabled(True)
        self.search.returnPressed.connect(self.find_next)
        self.search.textChanged.connect(lambda _t: self.find_next(restart=True))
        self.found = QLabel()
        self.found.setObjectName("muted")
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>Sumário</b>"))
        lv.addWidget(self.tree, 1)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.view)
        split.setStretchFactor(1, 1)
        split.setSizes([240, 860])
        bar = QHBoxLayout()
        bar.addWidget(self.search, 1)
        bar.addWidget(self.found)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(split, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self._width = 0
        self._relayout = QTimer(self)                 # refaz a largura das imagens ao redimensionar
        self._relayout.setSingleShot(True)
        self._relayout.timeout.connect(self.render)
        self.render()

    # ------------------------------------------------------------ conteudo
    def image_width(self) -> int:
        return max(320, min(1100, self.view.viewport().width() - 40))

    def render(self) -> None:
        width = self.image_width()
        if width == self._width:
            return
        self._width = width
        pos = self.view.verticalScrollBar().value()
        self.view.target_width = width
        page = IMAGE.sub(r'<a href="zoom:\1"><img src="\1"\2></a>', self.source)   # clique amplia
        self.view.setHtml(page.replace("{W}", str(width)))
        self.view.verticalScrollBar().setValue(pos)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout.start(120)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._relayout.start(0)

    def go(self, anchor: str) -> None:
        self.view.scrollToAnchor(anchor)

    def _link(self, url: QUrl) -> None:
        if url.scheme() == "zoom":
            ImageDialog(HELP_DIR / url.path(), self).show()
        elif url.fragment() and not url.path():
            self.go(url.fragment())

    def find_next(self, restart: bool = False) -> bool:
        text = self.search.text().strip()
        if not text:
            self.found.setText("")
            return False
        if restart:
            self.view.moveCursor(self.view.textCursor().MoveOperation.Start)
        ok = self.view.find(text)
        if not ok:                                    # chegou ao fim: recomeca do inicio
            self.view.moveCursor(self.view.textCursor().MoveOperation.Start)
            ok = self.view.find(text)
        self.found.setText("" if ok else "nada encontrado")
        return ok
