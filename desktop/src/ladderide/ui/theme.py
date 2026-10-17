"""Tema visual da IDE: estilo Fusion, paleta clara e folha de estilo (QSS)."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

BG = "#eef2f7"          # fundo das areas de trabalho
SURFACE = "#ffffff"     # paineis e cartoes
SURFACE_ALT = "#f8fafc"
BORDER = "#d8e0ea"
TEXT = "#0f172a"
MUTED = "#64748b"
ACCENT = "#2563eb"
ACCENT_SOFT = "#dbeafe"
SUCCESS = "#16a34a"
DANGER = "#dc2626"

QSS = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {TEXT}; }}
QToolTip {{ background: {TEXT}; color: white; border: none; padding: 5px 8px; border-radius: 4px; }}

QMenuBar {{ background: {SURFACE}; border-bottom: 1px solid {BORDER}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu {{ background: {SURFACE}; border: 1px solid {BORDER}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT_SOFT}; color: {ACCENT}; }}
QMenu::item:disabled {{ color: #a3b1c2; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolBar {{ background: {SURFACE}; border: none; border-bottom: 1px solid {BORDER}; padding: 4px 6px; spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {BORDER}; margin: 4px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 4px 7px; background: transparent; }}
QToolButton:hover {{ background: #f1f5f9; border-color: {BORDER}; }}
QToolButton:pressed, QToolButton:checked {{ background: {ACCENT_SOFT}; border-color: #93c5fd; }}
QToolButton:disabled {{ color: #a3b1c2; }}

QDockWidget {{ titlebar-close-icon: none; font-weight: 600; }}
QDockWidget::title {{ background: {SURFACE}; padding: 7px 10px; border-bottom: 1px solid {BORDER};
                      text-align: left; }}
QDockWidget > QWidget {{ background: {SURFACE}; }}

QGroupBox {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 8px; margin-top: 14px;
             padding: 10px 6px 6px 6px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; }}

QPushButton {{ background: {SURFACE}; border: 1px solid #c7d2df; border-radius: 6px; padding: 5px 12px; }}
QPushButton:hover {{ background: #f1f5f9; border-color: #94a3b8; }}
QPushButton:pressed {{ background: #e2e8f0; }}
QPushButton:disabled {{ color: #a3b1c2; background: {SURFACE_ALT}; border-color: {BORDER}; }}
QPushButton:checked {{ background: {SUCCESS}; color: white; border-color: #15803d; font-weight: 600; }}
QPushButton#primary {{ background: {ACCENT}; color: white; border-color: #1d4ed8; font-weight: 600; }}
QPushButton#primary:hover {{ background: #1d4ed8; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: {SURFACE}; border: 1px solid #c7d2df;
             border-radius: 6px; padding: 4px 6px; selection-background-color: {ACCENT}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {SURFACE}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_SOFT};
             selection-color: {TEXT}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {BORDER}; background: {SURFACE}; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; margin-right: 2px; color: {MUTED};
               border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {TEXT}; }}
QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}

QTableWidget, QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 6px;
             gridline-color: #edf1f6; selection-background-color: {ACCENT_SOFT}; selection-color: {TEXT};
             alternate-background-color: {SURFACE_ALT}; }}
QListWidget::item {{ padding: 4px 6px; }}
QHeaderView::section {{ background: {SURFACE_ALT}; color: {MUTED}; border: none; border-bottom: 1px solid {BORDER};
             padding: 5px 6px; font-weight: 600; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: #c3cedb; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: #94a3b8; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {SURFACE}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar QLabel {{ padding: 0 8px; }}
QCheckBox {{ spacing: 6px; }}
QLabel#sectionTitle {{ color: {MUTED}; font-weight: 600; padding-top: 6px; }}
QLabel#stateBadge {{ border-radius: 9px; padding: 2px 10px; font-weight: 600; background: #e2e8f0; color: #334155; }}
QGraphicsView {{ border: none; background: {BG}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    font = QFont("Segoe UI", 9)
    app.setFont(font)
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor(SURFACE_ALT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ToolTipBase, QColor(TEXT))
    pal.setColor(QPalette.ToolTipText, QColor("white"))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
