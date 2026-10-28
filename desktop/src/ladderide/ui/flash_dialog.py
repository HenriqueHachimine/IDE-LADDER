"""Dialogo 'Gravar firmware na placa': grava o firmware do CLP no ESP32 pela USB."""
from __future__ import annotations

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
                               QVBoxLayout)

from ..comm.flasher import FlashError, find_firmware, flash_command, parse_progress
from ..comm.transport import list_serial_ports
from .fonts import mono_font


class FlashDialog(QDialog):
    def __init__(self, before_flash=None, parent=None):
        """before_flash: chamado antes de gravar (a IDE fecha a conexao com a placa, se houver)."""
        super().__init__(parent)
        self.setWindowTitle("Gravar firmware na placa")
        self.setMinimumSize(620, 460)
        self.before_flash = before_flash
        self.process: QProcess | None = None
        self.bundle = None
        layout = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        row = QHBoxLayout()
        row.addWidget(QLabel("Porta:"))
        self.port = QComboBox()
        self.port.setEditable(True)
        self.port.setMinimumWidth(260)
        row.addWidget(self.port, 1)
        self.refresh_btn = QPushButton("Atualizar")
        self.refresh_btn.clicked.connect(self.refresh_ports)
        row.addWidget(self.refresh_btn)
        layout.addLayout(row)
        note = QLabel("A gravação substitui o firmware da placa e leva menos de um minuto. Se a placa não "
                      "entrar em modo de gravação sozinha, segure BOOT, aperte e solte RST, e solte BOOT. "
                      "O programa LADDER gravado antes continua na memória; se ele for de uma versão antiga "
                      "da IDE, a placa fica em FAULT até você transferir o programa de novo.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        layout.addWidget(self.progress)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(8.5))
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.flash_btn = QPushButton("Gravar")
        self.flash_btn.clicked.connect(self.start)
        self.close_btn = QPushButton("Fechar")
        self.close_btn.clicked.connect(self.reject)
        buttons.addWidget(self.flash_btn)
        buttons.addWidget(self.close_btn)
        layout.addLayout(buttons)
        self.refresh_ports()
        try:
            self.bundle = find_firmware()
            self.info.setText(f"Firmware {self.bundle.version} para {self.bundle.hardware} "
                              f"({self.bundle.source}).")
        except FlashError as exc:
            self.info.setText(f"<b>Não e possível gravar:</b> {exc}")
            self.flash_btn.setEnabled(False)

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

    def start(self) -> None:
        port = self.selected_port()
        if not port or self.bundle is None:
            self.log.appendPlainText("Escolha a porta da placa (ex.: COM5 ou /dev/ttyUSB0).")
            return
        try:
            cmd = flash_command(port, self.bundle)
        except FlashError as exc:
            self.log.appendPlainText(str(exc))
            return
        if self.before_flash is not None:
            self.before_flash()
        self.log.clear()
        self.log.appendPlainText(" ".join(cmd) + "\n")
        self.progress.setValue(0)
        self.segment = 0
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._output)
        self.process.finished.connect(self._finished)
        self.process.errorOccurred.connect(lambda _e: self.log.appendPlainText(
            f"Não foi possível iniciar o esptool: {self.process.errorString()}"))
        self.flash_btn.setEnabled(False)
        self.close_btn.setEnabled(False)
        self.process.start(cmd[0], cmd[1:])

    def _output(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace").replace("\r", "\n")
        for line in text.splitlines():
            if not line.strip():
                continue
            pct = parse_progress(line)
            if pct is not None:                    # 4 arquivos: cada um e uma parte da barra
                n = len(self.bundle.files)
                self.progress.setValue(int((self.segment * 100 + pct) / n))
                if pct == 100:
                    self.segment = min(self.segment + 1, n - 1)
                continue
            self.log.appendPlainText(line)

    def _finished(self, code: int, _status) -> None:
        self.flash_btn.setEnabled(True)
        self.close_btn.setEnabled(True)
        if code == 0:
            self.progress.setValue(100)
            self.log.appendPlainText("\nFirmware gravado. A placa reiniciou; conecte pela aba Dispositivo e "
                                     "transfira o programa.")
        else:
            self.log.appendPlainText(f"\nA gravação falhou (código {code}). Confira a porta, o cabo USB e o "
                                     "modo de gravação (BOOT + RST).")

    def reject(self) -> None:
        if self.process is not None and self.process.state() != QProcess.NotRunning:
            return                                  # nao fecha no meio da gravacao
        super().reject()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape and self.process is not None and \
                self.process.state() != QProcess.NotRunning:
            return
        super().keyPressEvent(event)
