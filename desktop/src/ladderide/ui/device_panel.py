"""Painel do dispositivo: conexao, transferencia, RUN/STOP e monitor online.

Toda a comunicacao roda em uma thread de trabalho (DeviceSession); a interface
recebe resultados por sinais Qt e nunca bloqueia esperando o dispositivo.
"""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from ..comm import (CommError, DeviceClient, DeviceError, ProcessTransport, SerialTransport, TcpTransport,
                    TransportError, list_serial_ports)
from ..comm.protocol import FAULT_TEXT, DevState
from ..comm.virtual import BuildError, start_virtual_device, virtual_storage_path
from . import theme
from .io_panel import IOPanel

STORAGE_OVERRIDE: Path | None = None   # usado pelos testes para isolar a "flash" virtual

STATE_STYLE = {
    "STOP": "background:#b45309; color:white;",
    "RUN": "background:#15803d; color:white;",
    "PROGRAM_LOADING": "background:#2563eb; color:white;",
    "FAULT": "background:#dc2626; color:white;",
    "DESCONECTADO": "background:#64748b; color:white;",
}


class DeviceSession(QObject):
    connected = Signal(object)            # DeviceInfo
    disconnected = Signal(str)
    snapshot = Signal(object)             # Snapshot
    status = Signal(object)               # DeviceStatus
    progress = Signal(int, int)
    jobDone = Signal(str, object)
    jobFailed = Signal(str, str)
    traffic = Signal(str, str, int, int)  # direcao, comando, seq, bytes (monitor serial)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.client: DeviceClient | None = None
        self.factory: Callable[[], object] | None = None
        self.is_virtual = False
        self.auto_reconnect = False
        self._jobs: queue.Queue = queue.Queue()
        self._busy = threading.Event()
        self._poll_pending = threading.Event()
        threading.Thread(target=self._worker, daemon=True).start()

    # ------------------------------------------------------------ worker
    def _worker(self) -> None:
        while True:
            tag, fn = self._jobs.get()
            self._busy.set()
            try:
                result = fn()
                self.jobDone.emit(tag, result)
            except (CommError, TransportError) as exc:
                self._lost(str(exc))
                self.jobFailed.emit(tag, str(exc))
            except DeviceError as exc:
                self.jobFailed.emit(tag, str(exc))
            except (BuildError, OSError, ValueError) as exc:
                self.jobFailed.emit(tag, str(exc))
            finally:
                if tag == "poll":
                    self._poll_pending.clear()
                self._busy.clear()

    def _lost(self, reason: str) -> None:
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None
            self.disconnected.emit(reason)

    def submit(self, tag: str, fn: Callable[[], object]) -> None:
        self._jobs.put((tag, fn))

    # ------------------------------------------------------------ comandos
    def open(self, factory: Callable[[], object], virtual: bool) -> None:
        self.factory = factory
        self.is_virtual = virtual
        self.auto_reconnect = True
        self.submit("connect", self._do_connect)

    def _do_connect(self):
        if self.client is not None:
            self.client.close()
            self.client = None
        transport = self.factory()
        client = DeviceClient(transport, timeout=0.4 if not isinstance(transport, ProcessTransport) else 0.6)
        client.on_traffic = self.traffic.emit
        try:
            info = client.wait_ready() if isinstance(transport, ProcessTransport) else client.info()
        except Exception:
            client.close()
            raise
        self.client = client
        self.connected.emit(info)
        return info

    def close(self) -> None:
        self.auto_reconnect = False
        self.submit("close", lambda: self._lost("desconectado pelo usuário"))

    def run_on_client(self, tag: str, fn: Callable[[DeviceClient], object]) -> None:
        def job():
            if self.client is None:
                raise CommError("dispositivo desconectado")
            return fn(self.client)
        self.submit(tag, job)

    def poll(self) -> None:
        """Chamado pelo timer da interface: le estado e variaveis, ou tenta reconectar."""
        if self._poll_pending.is_set():
            return
        self._poll_pending.set()
        if self.client is None:
            if self.auto_reconnect and self.factory is not None:
                self.submit("poll", self._try_reconnect)
            else:
                self._poll_pending.clear()
            return

        def job():
            if self.client is None:
                return None
            st = self.client.status()
            self.status.emit(st)
            snap = self.client.read_vars()
            self.snapshot.emit(snap)
            return snap
        self.submit("poll", job)

    def _try_reconnect(self):
        try:
            return self._do_connect()
        except (CommError, TransportError, OSError):
            return None


class DevicePanel(QWidget):
    transferRequested = Signal()
    monitorToggled = Signal(bool)

    def __init__(self, session: DeviceSession, parent=None):
        super().__init__(parent)
        self.session = session
        self.virtual_args: list[str] = []   # placa simulada (E/S e nome), escolhida no painel Placa
        layout = QVBoxLayout(self)

        conn = QGroupBox("Conexão")
        form = QFormLayout(conn)
        self.kind = QComboBox()
        self.kind.addItems(["Serial (USB)", "Dispositivo virtual (PC)", "TCP/Wi-Fi"])
        form.addRow("Meio:", self.kind)
        self.stack = QStackedWidget()
        serial_w = QWidget()
        row = QHBoxLayout(serial_w)
        row.setContentsMargins(0, 0, 0, 0)
        self.port = QComboBox()
        self.port.setEditable(True)
        refresh = QPushButton("Atualizar")
        refresh.clicked.connect(self.refresh_ports)
        self.baud = QComboBox()
        self.baud.addItems(["115200", "230400", "460800", "921600"])
        row.addWidget(self.port, 1)
        row.addWidget(self.baud)
        row.addWidget(refresh)
        virtual_w = QLabel("Executa o firmware compilado para o PC\n(build/virtual_flash.ldrb)")
        tcp_w = QWidget()
        row = QHBoxLayout(tcp_w)
        row.setContentsMargins(0, 0, 0, 0)
        self.host = QLineEdit()
        self.host.setPlaceholderText("192.168.0.50")
        self.tcp_port = QSpinBox()
        self.tcp_port.setRange(1, 65535)
        self.tcp_port.setValue(5020)
        row.addWidget(self.host, 1)
        row.addWidget(self.tcp_port)
        for w in (serial_w, virtual_w, tcp_w):
            self.stack.addWidget(w)
        self.kind.currentIndexChanged.connect(self.stack.setCurrentIndex)
        form.addRow(self.stack)
        buttons = QHBoxLayout()
        self.connect_btn = QPushButton("Conectar")
        self.connect_btn.clicked.connect(self.toggle_connection)
        self.link = QLabel("Desconectado")
        buttons.addWidget(self.connect_btn)
        buttons.addWidget(self.link, 1)
        form.addRow(buttons)
        layout.addWidget(conn)

        dev = QGroupBox("Dispositivo")
        dform = QFormLayout(dev)
        self.state = QLabel("DESCONECTADO")
        self.state.setStyleSheet("padding:4px; font-weight:bold; " + STATE_STYLE["DESCONECTADO"])
        self.info = QLabel("-")
        self.info.setWordWrap(True)
        self.program = QLabel("-")
        self.program.setWordWrap(True)
        self.timing = QLabel("-")
        dform.addRow("Estado:", self.state)
        dform.addRow("Firmware:", self.info)
        dform.addRow("Programa:", self.program)
        dform.addRow("Varredura:", self.timing)
        row = QHBoxLayout()
        self.transfer_btn = QPushButton("Transferir programa")
        self.transfer_btn.setObjectName("primary")
        self.run_btn = QPushButton("RUN")
        self.stop_btn = QPushButton("STOP")
        self.clear_btn = QPushButton("Limpar falha")
        self.transfer_btn.clicked.connect(self.transferRequested.emit)
        self.run_btn.clicked.connect(lambda: self.session.run_on_client("mode", lambda c: c.set_mode(True)))
        self.stop_btn.clicked.connect(lambda: self.session.run_on_client("mode", lambda c: c.set_mode(False)))
        self.clear_btn.clicked.connect(lambda: self.session.run_on_client("mode", lambda c: c.clear_fault()))
        for b in (self.transfer_btn, self.run_btn, self.stop_btn, self.clear_btn):
            row.addWidget(b)
        dform.addRow(row)
        self.monitor = QCheckBox("Monitor online (atualiza a cada 200 ms)")
        self.monitor.toggled.connect(self.monitorToggled.emit)
        dform.addRow(self.monitor)
        layout.addWidget(dev)

        self.io = IOPanel(show_commanded=True)
        self.io.set_inputs_editable(False)
        self.io.inputChanged.connect(self._sim_input)
        note = QLabel("Comandado = enviado aos relés (estado físico não medido).")
        note.setToolTip("\"Comandado\" e o que o firmware enviou aos relés. A placa não tem realimentação: "
                        "o estado físico dos contatos NÃO e medido.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        layout.addWidget(note)
        layout.addWidget(self.io, 1)

        self.connected = False
        self.device_info = None
        self.last_status = None
        session.connected.connect(self.on_connected)
        session.disconnected.connect(self.on_disconnected)
        session.status.connect(self.on_status)
        self.refresh_ports()
        self._update_buttons()

    # -------------------------------------------------------------- conexao
    def refresh_ports(self) -> None:
        current = self.port.currentText()
        self.port.clear()
        for dev, desc in list_serial_ports():
            self.port.addItem(dev, desc)
            self.port.setItemData(self.port.count() - 1, desc)
        if current:
            self.port.setCurrentText(current)

    def factory(self) -> tuple[Callable[[], object], bool]:
        kind = self.kind.currentIndex()
        if kind == 0:
            port, baud = self.port.currentText().strip(), int(self.baud.currentText())
            return (lambda: SerialTransport(port, baud)), False
        if kind == 1:
            storage = virtual_storage_path() if STORAGE_OVERRIDE is None else STORAGE_OVERRIDE
            args = list(self.virtual_args)
            return (lambda: start_virtual_device(Path(storage), *args)), True
        host, port = self.host.text().strip(), self.tcp_port.value()
        return (lambda: TcpTransport(host, port)), False

    KINDS = ["serial", "virtual", "tcp"]

    def load_target(self, target) -> None:
        """Preenche a conexao a partir da configuracao salva no projeto."""
        if self.connected or self.session.auto_reconnect:
            return
        self.kind.setCurrentIndex(self.KINDS.index(target.transport) if target.transport in self.KINDS else 0)
        if target.port:
            self.port.setCurrentText(target.port)
        self.baud.setCurrentText(str(target.baudrate))
        self.host.setText(target.host)
        self.tcp_port.setValue(target.tcp_port)

    def store_target(self, target) -> bool:
        """Grava a conexao atual no projeto. Retorna True se algo mudou."""
        values = {"transport": self.KINDS[self.kind.currentIndex()], "port": self.port.currentText().strip(),
                  "baudrate": int(self.baud.currentText()), "host": self.host.text().strip(),
                  "tcp_port": self.tcp_port.value()}
        changed = any(getattr(target, k) != v for k, v in values.items())
        for k, v in values.items():
            setattr(target, k, v)
        return changed

    def toggle_connection(self) -> None:
        if self.connected or self.session.auto_reconnect:
            self.monitor.setChecked(False)
            self.session.close()
            self.connected = False
            self.link.setText("Desconectado")
            self._set_state("DESCONECTADO")
        else:
            fn, virtual = self.factory()
            self.link.setText("Conectando...")
            self.session.open(fn, virtual)
        self._update_buttons()

    def on_connected(self, info) -> None:
        self.connected = True
        self.device_info = info
        self.link.setText("Conectado" + (" (virtual)" if self.session.is_virtual else ""))
        self.link.setStyleSheet(f"color:{theme.colors['SUCCESS']}; font-weight:bold;")
        self.info.setText(f"{info.firmware} | {info.hardware}\nLDRB {info.fmt_major}.{info.fmt_minor}, "
                          f"E/S {info.n_inputs}/{info.n_outputs}, varredura {info.scan_period_ms} ms")
        self.io.set_inputs_editable(self.session.is_virtual)
        self._update_buttons()
        self.session.run_on_client("status", lambda c: self.session.status.emit(c.status()))

    def on_disconnected(self, reason: str) -> None:
        self.connected = False
        if self.session.auto_reconnect:
            self.link.setText(f"Comunicação perdida: {reason}. Tentando reconectar...")
        else:
            self.link.setText("Desconectado")
        self.link.setStyleSheet("color:#dc2626; font-weight:bold;")
        self._set_state("DESCONECTADO")
        self._update_buttons()

    def _set_state(self, name: str) -> None:
        self.state.setText(name)
        self.state.setStyleSheet("padding:4px; font-weight:bold; " + STATE_STYLE.get(name, ""))

    def on_status(self, st) -> None:
        self.last_status = st
        name = st.state.name
        if st.state == DevState.FAULT:
            name = f"FAULT"
            self.program.setToolTip(FAULT_TEXT.get(st.fault, ""))
        self._set_state(name)
        fault = f"\nFalha: {FAULT_TEXT.get(st.fault, st.fault)}" if st.fault else ""
        self.program.setText((f"build_id 0x{st.build_id:08x}" if st.has_program else "nenhum") + fault
                             + (self._match_text(st) if st.has_program else ""))
        self.timing.setText(f"{st.scan_count} varreduras; execução {st.last_exec_us} us (max {st.max_exec_us}); "
                            f"intervalo max {st.max_interval_us / 1000:.1f} ms; atrasos {st.overruns}")
        self._update_buttons()

    expected_build_id: int | None = None

    def _match_text(self, st) -> str:
        if self.expected_build_id is None:
            return "\n(projeto não compilado)"
        return "\nIgual ao projeto aberto" if st.build_id == self.expected_build_id else \
            "\nDIFERENTE do projeto aberto (transfira para monitorar o diagrama)"

    def _update_buttons(self) -> None:
        on = self.connected
        st = self.last_status.state if (on and self.last_status) else None
        self.transfer_btn.setEnabled(on)
        self.run_btn.setEnabled(on and st == DevState.STOP)
        self.stop_btn.setEnabled(on and st == DevState.RUN)
        self.clear_btn.setEnabled(on and st == DevState.FAULT)
        self.connect_btn.setText("Desconectar" if (on or self.session.auto_reconnect) else "Conectar")
        for w in (self.kind, self.stack):
            w.setEnabled(not (on or self.session.auto_reconnect))

    def _sim_input(self, index: int, value: bool) -> None:
        if not self.session.is_virtual:
            return
        mask = sum(1 << k for k, b in enumerate(self.io.input_buttons) if b.isChecked())
        self.session.run_on_client("sim_inputs", lambda c: c.sim_set_inputs(mask))
