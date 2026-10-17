"""Ponto de entrada: python -m ladderide [projeto.ladproj]

--smoke-test <arquivo>: abre o projeto, compila, verifica o dispositivo virtual,
grava o resultado no arquivo e encerra (verificacao automatica da distribuicao).
"""
from __future__ import annotations

import sys


def _smoke_test(window, out_path: str) -> None:
    lines = []
    try:
        ok = window.compile()
        lines.append(f"compile {'OK' if ok else 'ERRO'} build_id=0x{window.result.build_id:08x}")
        from .comm import DeviceClient
        from .comm.virtual import start_virtual_device, virtual_storage_path
        client = DeviceClient(start_virtual_device(virtual_storage_path()), timeout=1.0)
        info = client.info()
        lines.append(f"virtual OK firmware={info.firmware}")
        client.close()
    except Exception as exc:  # noqa: BLE001 - relatorio de diagnostico
        lines.append(f"FALHA {type(exc).__name__}: {exc}")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    smoke_out = None
    if "--smoke-test" in argv:
        k = argv.index("--smoke-test")
        smoke_out = argv[k + 1]
        del argv[k:k + 2]
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("PySide6 nao esta instalado. Rode:  python -m pip install PySide6", file=sys.stderr)
        return 1
    from .ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("LadderIDE")
    app.setOrganizationName("CLP-ESP32")
    from .ui.theme import apply_theme
    apply_theme(app)
    window = MainWindow()
    if len(argv) > 1:
        window.file_open(argv[1])
    window.show()
    if smoke_out:
        def finish():
            _smoke_test(window, smoke_out)
            window.dirty = False
            app.quit()
        QTimer.singleShot(300, finish)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
