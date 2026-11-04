"""Dialogo 'Gravar C++ na placa': compila o C++ do diagrama com o PlatformIO e grava pela USB."""
from __future__ import annotations

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
                               QVBoxLayout)

from ..comm.cpp_upload import TARGETS, UploadError, build_command, check, write_project
from ..comm.transport import list_serial_ports
from ..model.project import Project
from .fonts import mono_font


class CppUploadDialog(QDialog):
    def __init__(self, project: Project, board: str = "esp32-relay", before_upload=None, parent=None):
        """board: placa sugerida (a do controlador ou a da aba Placa). before_upload: chamado antes de
        gravar (a IDE fecha a conexao com a placa, se houver, para liberar a porta)."""
        super().__init__(parent)
        self.setWindowTitle("Gravar C++ na placa")
        self.setMinimumSize(680, 520)
        self.project = project
        self.before_upload = before_upload
        self.process: QProcess | None = None
        self.uploading = False
        layout = QVBoxLayout(self)
        intro = QLabel("Compila o C++ gerado do diagrama (aba Código C++) e grava direto na placa pela USB, "
                       "com o PlatformIO. A placa passa a rodar o programa sozinha; o monitor serial "
                       "(115200 bit/s) mostra cada entrada, saída, temporizador e contador que muda.")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.board = QComboBox()
        for target in TARGETS.values():
            self.board.addItem(target.profile.name, target.board)
        self.board.setCurrentIndex(max(0, self.board.findData(board)))
        self.board.currentIndexChanged.connect(self._update)
        form.addRow("Placa:", self.board)
        port_row = QHBoxLayout()
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.setMinimumWidth(260)
        port_row.addWidget(self.port, 1)
        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        port_row.addWidget(self.refresh_btn)
        form.addRow("Porta:", port_row)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        warn = QLabel("Atenção: o C++ substitui o firmware do CLP. Depois disso a IDE não transfere programas "
                      "para a placa até você gravar o firmware de novo (Dispositivo > Gravar firmware na "
                      "placa, só ESP32). Na primeira gravação de cada tipo de placa, o PlatformIO baixa o "
                      "compilador (pode levar alguns minutos).")
        warn.setWordWrap(True)
        warn.setObjectName("warn")
        layout.addWidget(warn)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(8.5))
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.build_btn = QPushButton("Compilar")
        self.build_btn.setToolTip("Só compila, sem gravar (confere se o programa cabe na placa)")
        self.build_btn.clicked.connect(lambda: self.start(upload=False))
        self.upload_btn = QPushButton("Gravar")
        self.upload_btn.setDefault(True)
        self.upload_btn.clicked.connect(lambda: self.start(upload=True))
        self.close_btn = QPushButton("Fechar")
        self.close_btn.clicked.connect(self.reject)
        for b in (self.build_btn, self.upload_btn, self.close_btn):
            buttons.addWidget(b)
        layout.addLayout(buttons)
        self.refresh_ports()
        self._update()

    # ------------------------------------------------------------- estado
    def selected_board(self) -> str:
        return self.board.currentData()

    def problems(self) -> list[str]:
        return check(self.project, self.selected_board())

    def _update(self) -> None:
        target = TARGETS[self.selected_board()]
        problems = self.problems()
        if problems:
            self.status.setText("<b>Não dá para gravar nesta placa:</b> " + "; ".join(problems) + ".")
            self.status.setObjectName("danger")
        else:
            io = self.project.io
            self.status.setText(f"{io.n_inputs} entradas e {io.n_outputs} saídas. {target.note}")
            self.status.setObjectName("muted")
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self._buttons()

    def _buttons(self) -> None:
        running = self.process is not None and self.process.state() != QProcess.NotRunning
        ok = not running and not self.problems()
        self.build_btn.setEnabled(ok)
        self.upload_btn.setEnabled(ok)
        self.close_btn.setEnabled(not running)
        self.board.setEnabled(not running)

    def refresh_ports(self) -> None:
        current = self.port.currentText()
        self.port.clear()
        for device, description in list_serial_ports():
            self.port.addItem(f"{device}  {description}", device)
        if current:
            index = self.port.findData(current.split()[0])
            if index >= 0:
                self.port.setCurrentIndex(index)

    def selected_port(self) -> str:
        data = self.port.currentData()
        return data if data else self.port.currentText().split()[0] if self.port.currentText().strip() else ""

    # ----------------------------------------------------------- execucao
    def command(self, upload: bool) -> list[str]:
        folder = write_project(self.project, self.selected_board())
        return build_command(folder, upload, self.selected_port() if upload else None)

    def start(self, upload: bool) -> None:
        port = self.selected_port()
        if upload and not port:
            self.log.appendPlainText("Escolha a porta da placa (ex.: COM5).")
            return
        try:
            cmd = self.command(upload)
        except UploadError as exc:
            self.log.appendPlainText(str(exc))
            return
        if upload and self.before_upload is not None:
            self.before_upload()
        self.uploading = upload
        self.log.clear()
        self.log.appendPlainText(" ".join(cmd) + "\n")
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(lambda _e: self.log.appendPlainText(
            f"Não foi possível iniciar o PlatformIO: {self.process.errorString()}"))
        self.process.start(cmd[0], cmd[1:])
        self._buttons()

    def _output(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace").replace("\r", "\n")
        for line in text.splitlines():
            if line.strip():
                self.log.appendPlainText(line)

    def _finished(self, code: int, _status) -> None:
        self._buttons()
        name = TARGETS[self.selected_board()].profile.name
        if code != 0:
            self.log.appendPlainText(f"\nFalhou (código {code}). Confira as mensagens acima"
                                     + (", a porta e o cabo USB." if self.uploading else "."))
        elif self.uploading:
            self.log.appendPlainText(f"\nPrograma gravado na {name}. Abra um monitor serial a 115200 bit/s "
                                     "para acompanhar (s = estado completo, h = ajuda).")
        else:
            self.log.appendPlainText(f"\nCompilado para a {name}. Use Gravar para enviar à placa.")

    def reject(self) -> None:
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            return                                  # nao fecha no meio da gravacao
        super().reject()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self.process is not None and \
                self.process.state() != QProcess.NotRunning:
            return
        super().keyPressEvent(event)
