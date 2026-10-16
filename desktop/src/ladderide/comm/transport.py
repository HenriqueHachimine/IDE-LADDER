"""Transportes de bytes: serial (USB), TCP e processo local (dispositivo virtual)."""
from __future__ import annotations

import queue
import socket
import subprocess
import threading
from abc import ABC, abstractmethod


class TransportError(OSError):
    pass


class Transport(ABC):
    description = ""

    @abstractmethod
    def write(self, data: bytes) -> None: ...

    @abstractmethod
    def read(self, timeout: float) -> bytes:
        """Bytes disponiveis (espera ate `timeout` s pelo primeiro). b'' se nada chegou."""

    @abstractmethod
    def close(self) -> None: ...


class SerialTransport(Transport):
    def __init__(self, port: str, baudrate: int = 115200):
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise TransportError("pyserial nao instalado: python -m pip install pyserial") from exc
        self.description = f"{port} @ {baudrate}"
        s = serial.Serial()
        s.port = port
        s.baudrate = baudrate
        s.timeout = 0
        # DTR/RTS costumam estar ligados a EN/GPIO0: ativa-los reinicia o ESP32.
        s.dtr = False
        s.rts = False
        try:
            s.open()
        except (serial.SerialException, OSError) as exc:
            raise TransportError(f"nao foi possivel abrir {port}: {exc}") from exc
        self._s = s

    def write(self, data: bytes) -> None:
        try:
            self._s.write(data)
        except Exception as exc:  # serial.SerialException derivada de IOError
            raise TransportError(f"falha de escrita: {exc}") from exc

    def read(self, timeout: float) -> bytes:
        try:
            self._s.timeout = timeout
            first = self._s.read(1)
            if not first:
                return b""
            self._s.timeout = 0
            return first + self._s.read(self._s.in_waiting or 0)
        except Exception as exc:
            raise TransportError(f"falha de leitura: {exc}") from exc

    def close(self) -> None:
        try:
            self._s.close()
        except Exception:
            pass


class TcpTransport(Transport):
    def __init__(self, host: str, port: int = 5020, connect_timeout: float = 3.0):
        self.description = f"tcp://{host}:{port}"
        try:
            self._sock = socket.create_connection((host, port), timeout=connect_timeout)
        except OSError as exc:
            raise TransportError(f"nao foi possivel conectar a {host}:{port}: {exc}") from exc

    def write(self, data: bytes) -> None:
        try:
            self._sock.sendall(data)
        except OSError as exc:
            raise TransportError(str(exc)) from exc

    def read(self, timeout: float) -> bytes:
        self._sock.settimeout(timeout)
        try:
            data = self._sock.recv(4096)
        except socket.timeout:
            return b""
        except OSError as exc:
            raise TransportError(str(exc)) from exc
        if not data:
            raise TransportError("conexao encerrada pelo dispositivo")
        return data

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass


class ProcessTransport(Transport):
    """Fala com um processo pela entrada/saida padrao (dispositivo virtual)."""

    def __init__(self, argv: list[str]):
        self.description = "dispositivo virtual"
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          stderr=subprocess.DEVNULL, bufsize=0)
        except OSError as exc:
            raise TransportError(f"nao foi possivel iniciar {argv[0]}: {exc}") from exc
        self._q: queue.Queue[bytes] = queue.Queue()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        out = self._proc.stdout
        while True:
            try:
                data = out.read(4096)  # bufsize=0: le o que estiver disponivel no pipe
            except (OSError, ValueError):
                data = b""
            if not data:
                self._q.put(b"")  # sinal de fim
                return
            self._q.put(data)

    def write(self, data: bytes) -> None:
        if self._proc.poll() is not None:
            raise TransportError("dispositivo virtual encerrado")
        try:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()
        except (OSError, ValueError) as exc:
            raise TransportError(str(exc)) from exc

    def read(self, timeout: float) -> bytes:
        try:
            data = self._q.get(timeout=timeout)
        except queue.Empty:
            return b""
        if data == b"":
            self._q.put(b"")
            raise TransportError("dispositivo virtual encerrado")
        chunks = [data]
        while not self._q.empty():
            more = self._q.get_nowait()
            if more == b"":
                self._q.put(b"")
                break
            chunks.append(more)
        return b"".join(chunks)

    def kill(self) -> None:
        """Simula queda de energia/reinicio abrupto."""
        self._proc.kill()
        self._proc.wait()

    def close(self) -> None:
        try:
            self._proc.stdin.close()
        except OSError:
            pass
        try:
            self._proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.kill()


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description) for p in sorted(list_ports.comports(), key=lambda p: p.device)]
