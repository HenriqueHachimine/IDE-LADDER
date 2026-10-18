"""Cliente LDP: pedidos com retransmissao idempotente e transferencia transacional."""
from __future__ import annotations

import random
import struct
import time
from dataclasses import dataclass
from typing import Callable

from ..core import isa
from ..core.crc import crc32
from ..core.image import decode
from ..core.isa import ImageError
from .frames import FrameParser, encode
from .protocol import ERROR_FLAG, ERROR_TEXT, RESPONSE_FLAG, Cmd, DevState, ProtoError
from .snapshot import DeviceInfo, DeviceStatus, Snapshot
from .transport import Transport, TransportError


class CommError(Exception):
    """Falha de comunicacao (timeout, porta, desconexao)."""


class DeviceError(Exception):
    """O dispositivo respondeu com erro."""

    def __init__(self, cmd: int, code: int, detail: bytes = b""):
        self.cmd, self.code, self.detail = cmd, code, detail
        name = ProtoError(code).name if code in ProtoError._value2member_map_ else str(code)
        text = ERROR_TEXT.get(code, "erro desconhecido")
        extra = ""
        if code == ProtoError.IMAGE_INVALID and len(detail) >= 5:
            img_code, index = struct.unpack_from("<Bi", detail)
            img = ImageError(img_code).name if img_code in ImageError._value2member_map_ else img_code
            extra = f" ({img}, instrucao {index})"
        super().__init__(f"{Cmd(cmd).name if cmd in Cmd._value2member_map_ else cmd}: {name} - {text}{extra}")


@dataclass
class DownloadResult:
    build_id: int
    crc: int
    bytes_sent: int
    chunks: int
    retries: int


class DeviceClient:
    def __init__(self, transport: Transport, timeout: float = 0.3, retries: int = 3):
        self.transport = transport
        self.timeout = timeout
        self.retries = retries
        self.parser = FrameParser()
        # Sequencia inicial aleatoria: evita confundir o cache de idempotencia do
        # dispositivo com o de uma sessao anterior.
        self.seq = random.randrange(256)
        self.retry_count = 0
        # Observador do trafego (monitor serial do simulador da placa):
        # on_traffic(direcao "TX"/"RX"/"ERR"/"RETRY", comando, seq, bytes do quadro)
        self.on_traffic: Callable[[str, str, int, int], None] | None = None

    def _trace(self, direction: str, cmd: int, nbytes: int) -> None:
        if self.on_traffic is not None:
            name = Cmd(cmd).name if cmd in Cmd._value2member_map_ else str(cmd)
            self.on_traffic(direction, name, self.seq, nbytes)

    def close(self) -> None:
        self.transport.close()

    # ---------------------------------------------------------------- base
    def request(self, cmd: int, payload: bytes = b"", timeout: float | None = None) -> bytes:
        self.seq = (self.seq + 1) & 0xFF
        frame = encode(cmd, self.seq, 0, payload)
        wait = self.timeout if timeout is None else timeout
        for attempt in range(self.retries + 1):
            if attempt:
                self.retry_count += 1
                self._trace("RETRY", cmd, len(frame))
            try:
                self.transport.write(frame)
                self._trace("TX", cmd, len(frame))
                deadline = time.monotonic() + wait
                while (left := deadline - time.monotonic()) > 0:
                    for f in self.parser.feed(self.transport.read(left)):
                        if f.seq != self.seq or f.type != (cmd | RESPONSE_FLAG):
                            continue  # resposta atrasada de outro pedido
                        if f.flags & ERROR_FLAG:
                            self._trace("ERR", cmd, len(f.payload))
                            raise DeviceError(cmd, f.payload[0] if f.payload else 0, f.payload[1:])
                        self._trace("RX", cmd, len(f.payload))
                        return f.payload
            except TransportError as exc:
                raise CommError(str(exc)) from exc
        raise CommError(f"sem resposta do dispositivo ({Cmd(cmd).name}, {self.retries + 1} tentativas)")

    # -------------------------------------------------------------- comandos
    def info(self) -> DeviceInfo:
        return DeviceInfo.parse(self.request(Cmd.INFO))

    def status(self) -> DeviceStatus:
        return DeviceStatus.parse(self.request(Cmd.STATUS))

    def set_mode(self, run: bool) -> DevState:
        return DevState(self.request(Cmd.SET_MODE, bytes([1 if run else 0]))[0])

    def clear_fault(self) -> DevState:
        return DevState(self.request(Cmd.CLEAR_FAULT)[0])

    def read_io(self) -> tuple[DevState, int, int, int]:
        state, inputs, q, qc = struct.unpack("<BHHH", self.request(Cmd.READ_IO))
        return DevState(state), inputs, q, qc

    def read_vars(self) -> Snapshot:
        return Snapshot.parse(self.request(Cmd.READ_VARS))

    def write_marker(self, index: int, value: bool) -> None:
        self.request(Cmd.WRITE_MARKER, struct.pack("<HB", index, 1 if value else 0))

    def test_begin(self) -> None:
        self.request(Cmd.TEST_BEGIN)

    def test_scan(self, inputs: int, dt_ms: int) -> Snapshot:
        return Snapshot.parse(self.request(Cmd.TEST_SCAN, struct.pack("<HI", inputs, dt_ms)))

    def sim_set_inputs(self, mask: int) -> None:
        self.request(Cmd.SIM_SET_INPUTS, struct.pack("<H", mask))

    # --------------------------------------------------------- transferencia
    def check_compatible(self, image: bytes, info: DeviceInfo | None = None) -> DeviceInfo:
        info = info or self.info()
        prog = decode(image)  # nunca envia imagem invalida
        if info.fmt_major != isa.FORMAT_MAJOR or info.fmt_minor < isa.FORMAT_MINOR:
            raise CommError(f"firmware suporta LDRB {info.fmt_major}.{info.fmt_minor}; "
                            f"a IDE gera {isa.FORMAT_MAJOR}.{isa.FORMAT_MINOR}. Atualize o firmware.")
        if prog.n_inputs > info.n_inputs or prog.n_outputs > info.n_outputs:
            raise CommError(f"o programa usa {prog.n_inputs} entradas/{prog.n_outputs} saidas; "
                            f"o dispositivo tem {info.n_inputs}/{info.n_outputs}")
        if len(image) > info.max_image:
            raise CommError("programa maior que a memoria do dispositivo")
        return info

    def download(self, image: bytes, progress: Callable[[int, int], None] | None = None,
                 stop_if_running: bool = False) -> DownloadResult:
        """Transfere, valida e ativa o programa. Falhas preservam o programa anterior."""
        info = self.check_compatible(image)
        st = self.status()
        if st.state == DevState.RUN:
            if not stop_if_running:
                raise CommError("o dispositivo esta em RUN; coloque em STOP antes de transferir")
            self.set_mode(False)
        elif st.state == DevState.FAULT:
            raise CommError("o dispositivo esta em FAULT; limpe a falha antes de transferir")
        retries_before = self.retry_count
        reply = self.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(image), crc32(image)))
        chunk = min(struct.unpack("<H", reply)[0], info.max_chunk)
        sent = chunks = 0
        try:
            while sent < len(image):
                part = image[sent:sent + chunk]
                (received,) = struct.unpack("<I", self.request(Cmd.LOAD_CHUNK, struct.pack("<I", sent) + part))
                if received != sent + len(part):
                    raise CommError(f"confirmacao inesperada: dispositivo recebeu {received} bytes")
                sent = received
                chunks += 1
                if progress:
                    progress(sent, len(image))
            self.request(Cmd.LOAD_END, timeout=1.0)
            build_id, crc = struct.unpack("<II", self.request(Cmd.LOAD_COMMIT, timeout=3.0))
        except Exception:
            try:
                self.request(Cmd.LOAD_ABORT)
            except (CommError, DeviceError):
                pass
            raise
        expected = decode(image)
        if build_id != expected.build_id or crc != crc32(image[:-4]):
            raise CommError("o programa ativo no dispositivo nao corresponde ao enviado")
        final = self.status()
        if final.build_id != build_id or not final.has_program:
            raise CommError("verificacao final falhou: STATUS nao confirma o novo programa")
        return DownloadResult(build_id, crc, sent, chunks, self.retry_count - retries_before)
