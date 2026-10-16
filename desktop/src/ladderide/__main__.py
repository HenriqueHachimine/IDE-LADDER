"""Ponto de entrada: python -m ladderide [projeto.ladproj]"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 nao esta instalado. Rode:  python -m pip install PySide6", file=sys.stderr)
        return 1
    from .ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("LadderIDE")
    app.setOrganizationName("CLP-ESP32")
    window = MainWindow()
    if len(argv) > 1:
        window.file_open(argv[1])
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
