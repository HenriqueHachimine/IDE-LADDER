"""Tema visual da IDE: estilo Fusion, paletas clara e escura e folha de estilo (QSS).

Modos: "light", "dark" ou "system" (segue o Windows). As cores usadas no
desenho (diagrama, simbolos, paineis) sao objetos QColor criados com themed();
ao trocar o tema eles sao alterados no proprio objeto, entao todo modulo que
os importou passa a desenhar com a nova cor no proximo repaint.
"""
from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from .fonts import ui_font

MODES = {"light": "Claro", "dark": "Escuro", "system": "Seguir o Windows"}

LIGHT = {
    "BG": "#eef2f7", "SURFACE": "#ffffff", "SURFACE_ALT": "#f8fafc", "BORDER": "#d8e0ea",
    "TEXT": "#0f172a", "MUTED": "#64748b", "SUBTLE": "#475569", "DISABLED": "#a3b1c2",
    "ACCENT": "#2563eb", "ACCENT_HOVER": "#1d4ed8", "ACCENT_SOFT": "#dbeafe", "ACCENT_BORDER": "#93c5fd",
    "HOVER": "#f1f5f9", "PRESSED": "#e2e8f0", "INPUT_BORDER": "#c7d2df", "INPUT_HOVER": "#94a3b8",
    "GRID": "#edf1f6", "SCROLL": "#c3cedb", "SCROLL_HOVER": "#94a3b8",
    "SUCCESS": "#16a34a", "SUCCESS_BORDER": "#15803d", "WARN": "#b45309", "DANGER": "#b91c1c",
    "BADGE_BG": "#e2e8f0", "BADGE_FG": "#334155",
    "LED_OFF": "#e2e8f0", "LED_OFF_BORDER": "#94a3b8", "LED_UNKNOWN": "#f8fafc",
    "TOOLTIP_BG": "#0f172a", "TOOLTIP_FG": "#ffffff",
}
DARK = {
    "BG": "#0b1120", "SURFACE": "#151e2e", "SURFACE_ALT": "#1a2436", "BORDER": "#2a3649",
    "TEXT": "#e2e8f0", "MUTED": "#94a3b8", "SUBTLE": "#a5b4c8", "DISABLED": "#55637a",
    "ACCENT": "#3b82f6", "ACCENT_HOVER": "#2563eb", "ACCENT_SOFT": "#1e3a5f", "ACCENT_BORDER": "#3b82f6",
    "HOVER": "#1f2a3d", "PRESSED": "#26344b", "INPUT_BORDER": "#334155", "INPUT_HOVER": "#475569",
    "GRID": "#1f2a3b", "SCROLL": "#334155", "SCROLL_HOVER": "#475569",
    "SUCCESS": "#16a34a", "SUCCESS_BORDER": "#22c55e", "WARN": "#f59e0b", "DANGER": "#f87171",
    "BADGE_BG": "#26344b", "BADGE_FG": "#cbd5e1",
    "LED_OFF": "#26344b", "LED_OFF_BORDER": "#475569", "LED_UNKNOWN": "#151e2e",
    "TOOLTIP_BG": "#e2e8f0", "TOOLTIP_FG": "#0f172a",
}

current_mode = "light"      # escolha do usuario
current_name = "light"      # tema efetivo (light/dark)
colors: dict[str, str] = dict(LIGHT)
_themed: list[tuple[QColor, QColor, QColor]] = []


def themed(light, dark) -> QColor:
    """Cor que acompanha o tema. Aceita o que QColor aceita (nome, RGB, RGBA)."""
    lc = QColor(*light) if isinstance(light, tuple) else QColor(light)
    dc = QColor(*dark) if isinstance(dark, tuple) else QColor(dark)
    c = QColor(dc if current_name == "dark" else lc)
    _themed.append((c, lc, dc))
    return c


def color(key: str) -> QColor:
    return QColor(colors[key])


def is_dark() -> bool:
    return current_name == "dark"


def build_qss(c: dict[str, str]) -> str:
    return f"""
QMainWindow, QDialog {{ background: {c['BG']}; }}
QWidget {{ color: {c['TEXT']}; }}
QToolTip {{ background: {c['TOOLTIP_BG']}; color: {c['TOOLTIP_FG']}; border: none; padding: 5px 8px;
            border-radius: 4px; }}

QMenuBar {{ background: {c['SURFACE']}; border-bottom: 1px solid {c['BORDER']}; padding: 2px 4px; }}
QMenuBar::item {{ padding: 4px 10px; border-radius: 4px; background: transparent; }}
QMenuBar::item:selected {{ background: {c['ACCENT_SOFT']}; color: {c['ACCENT']}; }}
QMenu {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']}; padding: 4px; border-radius: 6px; }}
QMenu::item {{ padding: 6px 28px 6px 14px; border-radius: 4px; }}
QMenu::item:selected {{ background: {c['ACCENT_SOFT']}; color: {c['TEXT']}; }}
QMenu::item:disabled {{ color: {c['DISABLED']}; }}
QMenu::separator {{ height: 1px; background: {c['BORDER']}; margin: 4px 8px; }}

QToolBar {{ background: {c['SURFACE']}; border: none; border-bottom: 1px solid {c['BORDER']}; padding: 4px 6px;
            spacing: 2px; }}
QToolBar::separator {{ width: 1px; background: {c['BORDER']}; margin: 4px 6px; }}
QToolButton {{ border: 1px solid transparent; border-radius: 6px; padding: 4px 7px; background: transparent; }}
QToolButton:hover {{ background: {c['HOVER']}; border-color: {c['BORDER']}; }}
QToolButton:pressed, QToolButton:checked {{ background: {c['ACCENT_SOFT']}; border-color: {c['ACCENT_BORDER']}; }}
QToolButton:disabled {{ color: {c['DISABLED']}; }}

QDockWidget {{ font-weight: 600; }}
QDockWidget::title {{ background: {c['SURFACE']}; padding: 7px 10px; border-bottom: 1px solid {c['BORDER']};
                      text-align: left; }}
QDockWidget > QWidget {{ background: {c['SURFACE']}; }}

QGroupBox {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']}; border-radius: 8px; margin-top: 14px;
             padding: 10px 6px 6px 6px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {c['MUTED']}; }}

QPushButton {{ background: {c['SURFACE']}; border: 1px solid {c['INPUT_BORDER']}; border-radius: 6px;
               padding: 5px 12px; }}
QPushButton:hover {{ background: {c['HOVER']}; border-color: {c['INPUT_HOVER']}; }}
QPushButton:pressed {{ background: {c['PRESSED']}; }}
QPushButton:disabled {{ color: {c['DISABLED']}; background: {c['SURFACE_ALT']}; border-color: {c['BORDER']}; }}
QPushButton:checked {{ background: {c['SUCCESS']}; color: white; border-color: {c['SUCCESS_BORDER']};
                       font-weight: 600; }}
QPushButton#primary {{ background: {c['ACCENT']}; color: white; border-color: {c['ACCENT_HOVER']};
                       font-weight: 600; }}
QPushButton#primary:hover {{ background: {c['ACCENT_HOVER']}; }}

QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{ background: {c['SURFACE']};
             border: 1px solid {c['INPUT_BORDER']}; border-radius: 6px; padding: 4px 6px;
             selection-background-color: {c['ACCENT']}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {c['ACCENT']}; }}
QComboBox QAbstractItemView {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
             selection-background-color: {c['ACCENT_SOFT']}; selection-color: {c['TEXT']}; }}
QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {c['INPUT_HOVER']}; border-radius: 3px;
             background: {c['SURFACE']}; }}
QCheckBox::indicator:checked {{ background: {c['ACCENT']}; border-color: {c['ACCENT']}; }}

QTabWidget::pane {{ border: none; border-top: 1px solid {c['BORDER']}; background: {c['SURFACE']}; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; margin-right: 2px; color: {c['MUTED']};
               border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['ACCENT']}; border-bottom: 2px solid {c['ACCENT']}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {c['TEXT']}; }}
QMainWindow::separator {{ background: {c['BORDER']}; width: 1px; height: 1px; }}

QTableWidget, QListWidget, QTreeWidget {{ background: {c['SURFACE']}; border: 1px solid {c['BORDER']};
             border-radius: 6px; gridline-color: {c['GRID']}; selection-background-color: {c['ACCENT_SOFT']};
             selection-color: {c['TEXT']}; alternate-background-color: {c['SURFACE_ALT']}; }}
QListWidget::item {{ padding: 4px 6px; }}
QHeaderView::section {{ background: {c['SURFACE_ALT']}; color: {c['MUTED']}; border: none;
             border-bottom: 1px solid {c['BORDER']}; padding: 5px 6px; font-weight: 600; }}
QTableCornerButton::section {{ background: {c['SURFACE_ALT']}; border: none; }}

QScrollArea {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle {{ background: {c['SCROLL']}; border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: {c['SCROLL_HOVER']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {c['SURFACE']}; border-top: 1px solid {c['BORDER']}; color: {c['MUTED']}; }}
QStatusBar QLabel {{ padding: 0 8px; }}
QCheckBox {{ spacing: 6px; }}
QLabel#sectionTitle {{ color: {c['MUTED']}; font-weight: 600; padding-top: 6px; }}
QLabel#muted {{ color: {c['SUBTLE']}; }}
QLabel#hint {{ color: {c['MUTED']}; font-size: 8pt; padding: 4px; }}
QLabel#warn {{ color: {c['WARN']}; }}
QLabel#danger {{ color: {c['DANGER']}; }}
QLabel#stats {{ color: {c['TEXT']}; font-weight: 600; }}
QLabel#stateBadge {{ border-radius: 9px; padding: 2px 10px; font-weight: 600; background: {c['BADGE_BG']};
                     color: {c['BADGE_FG']}; }}
QGraphicsView {{ border: none; background: {c['BG']}; }}
"""


def _palette(c: dict[str, str]) -> QPalette:
    pal = QPalette()
    roles = {QPalette.Window: "BG", QPalette.Base: "SURFACE", QPalette.AlternateBase: "SURFACE_ALT",
             QPalette.Text: "TEXT", QPalette.WindowText: "TEXT", QPalette.Button: "SURFACE",
             QPalette.ButtonText: "TEXT", QPalette.Highlight: "ACCENT", QPalette.ToolTipBase: "TOOLTIP_BG",
             QPalette.ToolTipText: "TOOLTIP_FG", QPalette.PlaceholderText: "MUTED", QPalette.Mid: "BORDER",
             QPalette.Dark: "BORDER", QPalette.Light: "SURFACE"}
    for role, key in roles.items():
        pal.setColor(role, QColor(c[key]))
    pal.setColor(QPalette.HighlightedText, QColor("white"))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(c["DISABLED"]))
    return pal


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except AttributeError:          # Qt < 6.5
        return False


def resolve(mode: str) -> str:
    if mode == "system":
        return "dark" if system_is_dark() else "light"
    return "dark" if mode == "dark" else "light"


def apply_theme(app: QApplication, mode: str | None = None) -> str:
    """Aplica o modo (light/dark/system). Retorna o tema efetivo."""
    global current_mode, current_name
    current_mode = mode or current_mode
    current_name = resolve(current_mode)
    colors.clear()
    colors.update(DARK if current_name == "dark" else LIGHT)
    for c, lc, dc in _themed:
        c.setRgba((dc if current_name == "dark" else lc).rgba())
    app.setStyle("Fusion")
    app.setFont(ui_font(9))
    app.setPalette(_palette(colors))
    app.setStyleSheet(build_qss(colors))
    return current_name


def load_mode() -> str:
    mode = QSettings("CLP-ESP32", "LadderIDE").value("ui/theme", "light")
    return mode if mode in MODES else "light"


def save_mode(mode: str) -> None:
    QSettings("CLP-ESP32", "LadderIDE").setValue("ui/theme", mode)
