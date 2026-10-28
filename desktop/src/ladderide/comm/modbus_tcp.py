"""Cliente Modbus TCP minimo (so biblioteca padrao), usado para ligar o simulador ao Factory IO.

Implementa apenas o que a ponte precisa: FC01 (ler coils), FC02 (ler entradas
discretas), FC04 (ler registradores de entrada), FC15 (escrever varias coils) e
FC16 (escrever varios registradores). Quadro Modbus TCP:

    MBAP: u16 transacao, u16 protocolo (0), u16 tamanho (unidade + PDU), u8 unidade
    PDU:  u8 funcao, dados (big-endian)

Resposta de excecao: funcao | 0x80 seguida de um codigo (EXCEPTION_TEXT).
"""
from __future__ import annotations

import socket
import struct

READ_COILS = 0x01
READ_DISCRETE_INPUTS = 0x02
READ_HOLDING_REGISTERS = 0x03
READ_INPUT_REGISTERS = 0x04
WRITE_MULTIPLE_COILS = 0x0F
WRITE_MULTIPLE_REGISTERS = 0x10
MAX_READ_BITS = 2000
MAX_WRITE_BITS = 1968
MAX_READ_REGS = 125
MAX_WRITE_REGS = 123

EXCEPTION_TEXT = {
    1: "função não suportada pelo servidor",
    2: "endereço fora da faixa configurada no servidor",
    3: "valor inválido",
    4: "falha no servidor",
    6: "servidor ocupado",
    10: "caminho de gateway indisponível",
    11: "dispositivo de destino não respondeu (confira o Slave ID)",
}


class ModbusError(OSError):
    """Falha de comunicacao ou resposta de excecao do servidor."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


def pack_bits(values: list[bool]) -> bytes:
    out = bytearray((len(values) + 7) // 8)
    for k, v in enumerate(values):
        if v:
            out[k // 8] |= 1 << (k % 8)
    return bytes(out)


def unpack_bits(data: bytes, count: int) -> list[bool]:
    return [bool(data[k // 8] >> (k % 8) & 1) for k in range(count)]


class ModbusTcpClient:
    def __init__(self, host: str, port: int = 502, unit: int = 1, timeout: float = 1.0):
        self.host = host
        self.port = port
        self.unit = unit
        self.timeout = timeout
        self._sock: socket.socket | None = None
        self._tid = 0

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as exc:
            raise ModbusError(f"sem conexão com {self.host}:{self.port} ({exc.strerror or exc})") from exc
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None

    # ------------------------------------------------------------- funcoes
    def read_coils(self, address: int, count: int) -> list[bool]:
        return self._read_bits(READ_COILS, address, count)

    def read_discrete_inputs(self, address: int, count: int) -> list[bool]:
        return self._read_bits(READ_DISCRETE_INPUTS, address, count)

    def write_coils(self, address: int, values: list[bool]) -> None:
        if not 1 <= len(values) <= MAX_WRITE_BITS:
            raise ValueError(f"quantidade de coils invalida: {len(values)}")
        data = pack_bits(values)
        pdu = struct.pack(">BHHB", WRITE_MULTIPLE_COILS, address, len(values), len(data)) + data
        reply = self._request(pdu)
        if len(reply) != 5 or struct.unpack(">HH", reply[1:]) != (address, len(values)):
            raise ModbusError("resposta FC15 inesperada")

    def read_input_registers(self, address: int, count: int) -> list[int]:
        """FC04: registradores de entrada (0..65535)."""
        return self._read_regs(READ_INPUT_REGISTERS, address, count)

    def read_holding_registers(self, address: int, count: int) -> list[int]:
        """FC03: holding registers (0..65535)."""
        return self._read_regs(READ_HOLDING_REGISTERS, address, count)

    def _read_regs(self, function: int, address: int, count: int) -> list[int]:
        if not 1 <= count <= MAX_READ_REGS:
            raise ValueError(f"quantidade de registradores invalida: {count}")
        reply = self._request(struct.pack(">BHH", function, address, count))
        if len(reply) != 2 + 2 * count or reply[1] != 2 * count:
            raise ModbusError(f"resposta FC{function:02d} com tamanho inesperado")
        return list(struct.unpack(f">{count}H", reply[2:]))

    def write_registers(self, address: int, values: list[int]) -> None:
        """FC16: escreve registradores (holding); valores fora de 0..65535 sao limitados."""
        if not 1 <= len(values) <= MAX_WRITE_REGS:
            raise ValueError(f"quantidade de registradores invalida: {len(values)}")
        data = struct.pack(f">{len(values)}H", *(min(0xFFFF, max(0, int(v))) for v in values))
        pdu = struct.pack(">BHHB", WRITE_MULTIPLE_REGISTERS, address, len(values), len(data)) + data
        reply = self._request(pdu)
        if len(reply) != 5 or struct.unpack(">HH", reply[1:]) != (address, len(values)):
            raise ModbusError("resposta FC16 inesperada")

    def _read_bits(self, function: int, address: int, count: int) -> list[bool]:
        if not 1 <= count <= MAX_READ_BITS:
            raise ValueError(f"quantidade de bits invalida: {count}")
        reply = self._request(struct.pack(">BHH", function, address, count))
        size = (count + 7) // 8
        if len(reply) != 2 + size or reply[1] != size:
            raise ModbusError(f"resposta FC{function:02d} com tamanho inesperado")
        return unpack_bits(reply[2:], count)

    # ---------------------------------------------------------- transporte
    def _request(self, pdu: bytes) -> bytes:
        if self._sock is None:
            raise ModbusError("não conectado")
        self._tid = (self._tid + 1) & 0xFFFF
        frame = struct.pack(">HHHB", self._tid, 0, len(pdu) + 1, self.unit) + pdu
        try:
            self._sock.sendall(frame)
            header = self._recv(7)
            tid, proto, length, unit = struct.unpack(">HHHB", header)
            if proto != 0 or not 2 <= length <= 254:
                raise ModbusError("cabecalho Modbus TCP inválido")
            reply = self._recv(length - 1)
        except socket.timeout as exc:
            self.close()
            raise ModbusError("o servidor não respondeu (tempo esgotado)") from exc
        except ModbusError:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise ModbusError(f"conexão perdida ({exc.strerror or exc})") from exc
        if tid != self._tid or unit != self.unit:
            self.close()
            raise ModbusError("resposta fora de sequência")
        if reply[0] == pdu[0] | 0x80:
            code = reply[1] if len(reply) > 1 else 0
            raise ModbusError(f"exceção {code}: {EXCEPTION_TEXT.get(code, 'desconhecida')}", code)
        if reply[0] != pdu[0]:
            self.close()
            raise ModbusError("resposta de outra função")
        return reply

    def _recv(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise ModbusError("o servidor fechou a conexão")
            buf += chunk
        return buf
