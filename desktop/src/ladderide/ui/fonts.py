"""Fontes com alternativas por sistema: Segoe UI/Consolas no Windows, equivalentes no Linux."""
from __future__ import annotations

from PySide6.QtGui import QFont

UI_FAMILIES = ["Segoe UI", "Noto Sans", "Ubuntu", "Cantarell", "DejaVu Sans", "Liberation Sans", "Arial",
               "sans-serif"]
MONO_FAMILIES = ["Consolas", "DejaVu Sans Mono", "Ubuntu Mono", "Liberation Mono", "Noto Mono",
                 "Courier New", "monospace"]


def ui_font(size: float, bold: bool = False, italic: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(UI_FAMILIES)
    f.setPointSizeF(size)
    f.setBold(bold)
    f.setItalic(italic)
    return f


def mono_font(size: float, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(MONO_FAMILIES)
    f.setStyleHint(QFont.Monospace)
    f.setPointSizeF(size)
    f.setBold(bold)
    return f
