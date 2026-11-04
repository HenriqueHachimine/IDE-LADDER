"""Comunicacao serial com CLPs comerciais: WEG CLIC-02 (Modbus RTU) e Omron CP1E (Host Link).

Os dois fabricantes gravam o programa do usuario com o proprio software (Clic02 Edit e
CX-Programmer), por um protocolo que os manuais nao documentam. O que os manuais
documentam e o acesso as variaveis e ao modo de operacao pela porta serial, e e isso
que a IDE usa: o programa LADDER roda na IDE e o CLP real entra como cartao de E/S
(entradas lidas, saidas escritas a cada ciclo), como no Factory IO.

WEG CLIC-02 (manual 10009280784, cap. 10 "Slave Modbus RTU"), RS-485, padrao 38400 8N2:
    0x0100  RUN/STOP (FC03/06)          0x0101  modelo (FC03)
    0x0608  M01..M10 (FC03/06/10)       0x0609  M11..M20 (FC03/06/10)
    0x0610  I01..I0C (FC03)             0x0611  X01..X0C, entradas dos modulos de expansao (FC03)
    0x0612  Y01..Y0C, saidas dos modulos (FC03)   0x0613  Q01..Q08 (FC03)
    O CLIC-02 so aceita comandar as saidas pelo proprio programa: grave nele, uma vez,
    o programa ponte M01 -> Q01 ... M08 -> Q08 e, com modulos de expansao,
    M11 -> Y01 ... M1C -> Y0C (ver ponte_clic). A IDE escreve M01..M08 e M11..M1C.

Omron CP1E (manual W480, secoes 5-1 e 14-1), RS-232C, Host Link (modo C), padrao 9600 7E2:
    entradas  CIO 0.00..0.11, CIO 1.00..1.11 (12 bits por canal)
    saidas    CIO 100.00..100.07, CIO 101.00..101.07 (8 bits por canal)
    Unidades de expansao CP1W (secao 6-1-4) recebem os canais seguintes aos do CPU, na ordem.
    Comandos: RR (le canais CIO), WR (escreve), SC (muda o modo), MS (le o status).
    A IDE poe o CP1E em MONITOR: o CLP atualiza as saidas fisicas com o que for escrito em
    CIO 100/101 (o programa do CLP nao deve usar essas saidas; deixe-o vazio).
"""
from __future__ import annotations

import time
from typing import Callable, Protocol

from ..core.crc import crc16_modbus

FRAMINGS = {"8N2": (8, "N", 2), "8E1": (8, "E", 1), "8O1": (8, "O", 1), "8N1": (8, "N", 1),
            "7E2": (7, "E", 2), "7E1": (7, "E", 1), "7O2": (7, "O", 2), "8E2": (8, "E", 2)}
BAUDRATES = (4800, 9600, 19200, 38400, 57600, 115200)

CLIC_RUN = 0x0100
CLIC_MODEL = 0x0101
CLIC_MARKERS = 0x0608      # M01..M10; 0x0609 = M11..M20
CLIC_INPUTS = 0x0610       # I01..I0C; 0x0611 = X01..X0C (expansao)
CLIC_EXP_OUTPUTS = 0x0612  # Y01..Y0C (expansao)
CLIC_OUTPUTS = 0x0613      # Q01..Q08
CLIC_MODELS = {0x30: "CLW-02/20VR-D", 0x70: "CLW-02/20VR-12D", 0x34: "CLW-02/20VT-D", 0x74: "CLW-02/20VT-12D"}
CLIC_EXCEPTIONS = {0x51: "telegrama inválido", 0x52: "CLP em RUN, comando não permitido",
                   0x53: "CLP protegido por senha", 0x54: "valor fora da faixa", 0x55: "erro de ROM do CLIC-02",
                   0x56: "o CLIC-02 não tem relógio", 0x57: "outro erro", 0x58: "comando não combina com o modo do CLIC-02",
                   0x59: "erro de identificação (Brand ID)"}
PONTE_CLIC = [f"M{k:02X} -> Q{k:02X}" for k in range(1, 9)]


def ponte_clic(n_outputs: int, n_exp_outputs: int = 0) -> list[str]:
    """Linhas do programa ponte do CLIC-02: M01.. -> Q01.. e, com expansao, M11.. -> Y01.."""
    return PONTE_CLIC[:n_outputs] + [f"M{0x11 + k:02X} -> Y{k + 1:02X}" for k in range(n_exp_outputs)]

CP1E_IN_BITS = 12          # bits usados por canal de entrada (CIO 0, CIO 1)
CP1E_OUT_BITS = 8          # bits usados por canal de saida (CIO 100, CIO 101)
CP1E_OUT_WORD = 100
HOSTLINK_MODES = {"program": "00", "monitor": "02", "run": "03"}
HOSTLINK_END_CODES = {"01": "não executável em RUN", "02": "não executável em MONITOR", "04": "endereço fora da faixa",
                      "0B": "não executável em PROGRAM", "13": "erro de FCS", "14": "erro de formato",
                      "15": "dado inválido", "16": "comando não suportado", "18": "quadro grande demais",
                      "A3": "FCS errado na transmissão", "A8": "tamanho de dados errado"}


class PlcError(Exception):
    pass


class Line(Protocol):
    """Porta serial (pyserial) ou falsa nos testes."""
    def write(self, data: bytes) -> None: ...
    def read(self, size: int, timeout: float) -> bytes: ...
    def flush_input(self) -> None: ...
    def close(self) -> None: ...


class SerialLine:
    def __init__(self, port: str, baudrate: int, framing: str):
        try:
            import serial
        except ImportError as exc:  # pragma: no cover
            raise PlcError("pyserial não instalado: python -m pip install pyserial") from exc
        bits, parity, stop = FRAMINGS[framing]
        s = serial.Serial()
        s.port, s.baudrate, s.bytesize, s.parity, s.stopbits = port, baudrate, bits, parity, stop
        s.timeout = 0
        s.dtr = s.rts = False
        try:
            s.open()
        except (serial.SerialException, OSError) as exc:
            raise PlcError(f"não foi possível abrir {port}: {exc}") from exc
        self._s = s

    def write(self, data: bytes) -> None:
        try:
            self._s.write(data)
        except Exception as exc:  # serial.SerialException
            raise PlcError(f"falha de escrita na serial: {exc}") from exc

    def read(self, size: int, timeout: float) -> bytes:
        try:
            self._s.timeout = timeout
            return self._s.read(size)
        except Exception as exc:
            raise PlcError(f"falha de leitura na serial: {exc}") from exc

    def flush_input(self) -> None:
        try:
            self._s.reset_input_buffer()
        except Exception:
            pass

    def close(self) -> None:
        try:
            self._s.close()
        except Exception:
            pass


def _read_exact(line: Line, n: int, deadline: float) -> bytes:
    data = b""
    while len(data) < n:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        data += line.read(n - len(data), left)
    return data


def _mask(n: int) -> int:
    return (1 << max(0, n)) - 1


class PlcDriver:
    """Operacoes comuns aos CLPs: a ponte (sim.plc_link) so usa estas.

    n = entradas (ou saidas) do projeto. `modules` = (entradas, saidas) de cada modulo de
    expansao, na ordem; os pontos dos modulos vem depois dos do CPU (n - soma dos modulos)."""
    name = ""
    modules: list[tuple[int, int]] = []

    def _cpu(self, n: int, outputs: bool) -> int:
        return n - sum(m[1 if outputs else 0] for m in self.modules)

    def read_inputs(self, n: int) -> int: raise NotImplementedError
    def write_outputs(self, n: int, mask: int) -> None: raise NotImplementedError
    def read_outputs(self, n: int) -> int: raise NotImplementedError
    def enter_online(self) -> None: raise NotImplementedError
    def set_run(self, run: bool) -> None: raise NotImplementedError
    def mode(self) -> str: raise NotImplementedError
    def identify(self) -> str: raise NotImplementedError

    def close(self) -> None:
        self.line.close()


# ============================================================ WEG CLIC-02
class ClicModbus(PlcDriver):
    name = "WEG CLIC-02 (Modbus RTU)"

    def __init__(self, line: Line, unit: int = 1, timeout: float = 0.5):
        self.line, self.unit, self.timeout = line, unit, timeout

    def _transact(self, pdu: bytes, expected: int | None) -> bytes:
        """Envia um telegrama e devolve a PDU da resposta (sem endereco e CRC)."""
        frame = bytes([self.unit]) + pdu
        crc = crc16_modbus(frame)
        self.line.flush_input()
        self.line.write(frame + bytes([crc & 0xFF, crc >> 8]))
        deadline = time.monotonic() + self.timeout
        head = _read_exact(self.line, 2, deadline)
        if len(head) < 2:
            raise PlcError(f"o CLIC-02 (ID {self.unit}) não respondeu: confira cabo RS-485, ID e velocidade")
        if head[1] & 0x80:
            rest = _read_exact(self.line, 3, deadline)
            body = head + rest
            self._check_crc(body)
            code = rest[0] if rest else 0
            raise PlcError(f"CLIC-02 recusou o comando: {CLIC_EXCEPTIONS.get(code, f'exceção 0x{code:02X}')}")
        if expected is None:                      # leitura: o 3o byte diz quantos dados vem
            count = _read_exact(self.line, 1, deadline)
            if not count:
                raise PlcError("resposta incompleta do CLIC-02")
            rest = count + _read_exact(self.line, count[0] + 2, deadline)
        else:
            rest = _read_exact(self.line, expected - 2, deadline)
        body = head + rest
        self._check_crc(body)
        if body[0] != self.unit or body[1] != pdu[0]:
            raise PlcError("resposta de outro escravo ou de outro comando")
        return body[1:-2]

    @staticmethod
    def _check_crc(body: bytes) -> None:
        if len(body) < 4:
            raise PlcError("resposta incompleta do CLIC-02")
        crc = crc16_modbus(body[:-2])
        if body[-2] != crc & 0xFF or body[-1] != crc >> 8:
            raise PlcError("CRC errado na resposta do CLIC-02 (ruído ou velocidade diferente)")

    def read_words(self, address: int, count: int = 1) -> list[int]:
        pdu = self._transact(bytes([0x03, address >> 8, address & 0xFF, 0, count]), None)
        data = pdu[2:]
        if len(data) != 2 * count:
            raise PlcError("quantidade de dados errada na resposta do CLIC-02")
        return [data[2 * i] << 8 | data[2 * i + 1] for i in range(count)]

    def write_word(self, address: int, value: int) -> None:
        self._transact(bytes([0x06, address >> 8, address & 0xFF, value >> 8 & 0xFF, value & 0xFF]), 8)

    def write_words(self, address: int, values: list[int]) -> None:
        data = b"".join((v & 0xFFFF).to_bytes(2, "big") for v in values)
        self._transact(bytes([0x10, address >> 8, address & 0xFF, 0, len(values), len(data)]) + data, 8)

    def read_inputs(self, n: int) -> int:
        cpu = self._cpu(n, False)
        if not self.modules:
            return self.read_words(CLIC_INPUTS)[0] & _mask(n)
        i, x = self.read_words(CLIC_INPUTS, 2)                 # I01..I0C e X01..X0C
        return (i & _mask(cpu)) | (x & _mask(n - cpu)) << cpu

    def write_outputs(self, n: int, mask: int) -> None:
        cpu = self._cpu(n, True)
        if not self.modules:
            self.write_word(CLIC_MARKERS, mask & _mask(n))
            return
        self.write_words(CLIC_MARKERS, [mask & _mask(cpu), mask >> cpu & _mask(n - cpu)])   # M01.. e M11..

    def read_outputs(self, n: int) -> int:
        cpu = self._cpu(n, True)
        if not self.modules:
            return self.read_words(CLIC_OUTPUTS)[0] & _mask(n)
        y, q = self.read_words(CLIC_EXP_OUTPUTS, 2)            # Y01..Y0C e Q01..Q08
        return (q & _mask(cpu)) | (y & _mask(n - cpu)) << cpu

    def enter_online(self) -> None:
        self.set_run(True)                        # o programa ponte precisa estar em RUN

    def set_run(self, run: bool) -> None:
        self.write_word(CLIC_RUN, 1 if run else 0)

    def mode(self) -> str:
        return "RUN" if self.read_words(CLIC_RUN)[0] & 1 else "STOP"

    def identify(self) -> str:
        code = self.read_words(CLIC_MODEL)[0]
        return CLIC_MODELS.get(code & 0xFF, f"CLIC-02 (código 0x{code:02X})")


# ============================================================ Omron CP1E
def hostlink_fcs(text: str) -> str:
    fcs = 0
    for ch in text:
        fcs ^= ord(ch)
    return f"{fcs:02X}"


def hostlink_frame(unit: int, header: str, text: str = "") -> bytes:
    body = f"@{unit:02d}{header}{text}"
    return (body + hostlink_fcs(body) + "*\r").encode("ascii")


class OmronHostLink(PlcDriver):
    name = "Omron CP1E (Host Link)"

    def __init__(self, line: Line, unit: int = 0, timeout: float = 0.8):
        self.line, self.unit, self.timeout = line, unit, timeout

    def command(self, header: str, text: str = "") -> str:
        """Envia um comando modo C e devolve os dados da resposta (depois do codigo de fim)."""
        self.line.flush_input()
        self.line.write(hostlink_frame(self.unit, header, text))
        deadline = time.monotonic() + self.timeout
        reply = b""
        while not reply.endswith(b"*\r"):
            if time.monotonic() >= deadline:
                break
            reply += self.line.read(1, max(0.0, deadline - time.monotonic()))   # termina em "*\r"
            if len(reply) > 512:
                break
        if not reply:
            raise PlcError(f"o CP1E (unidade {self.unit}) não respondeu: confira cabo RS-232C, "
                           "porta em Host Link, número da unidade e velocidade")
        text_r = reply.decode("ascii", "replace")
        if not text_r.endswith("*\r") or len(text_r) < 11:
            raise PlcError("resposta incompleta do CP1E")
        body, fcs = text_r[:-4], text_r[-4:-2]
        if hostlink_fcs(body) != fcs.upper():
            raise PlcError("FCS errado na resposta do CP1E (ruído ou formato serial diferente)")
        if body[1:3] != f"{self.unit:02d}" or body[3:5] != header:
            raise PlcError("resposta de outra unidade ou de outro comando")
        end = body[5:7]
        if end != "00":
            raise PlcError(f"CP1E recusou {header}: {HOSTLINK_END_CODES.get(end, f'código {end}')}")
        return body[7:]

    def read_cio(self, word: int, count: int = 1) -> list[int]:
        data = self.command("RR", f"{word:04d}{count:04d}")
        if len(data) != 4 * count:
            raise PlcError("quantidade de dados errada na resposta do CP1E")
        return [int(data[4 * i:4 * i + 4], 16) for i in range(count)]

    def write_cio(self, word: int, values: list[int]) -> None:
        self.command("WR", f"{word:04d}" + "".join(f"{v & 0xFFFF:04X}" for v in values))

    def segments(self, n: int, outputs: bool) -> list[int]:
        """Bits usados em cada canal, a partir de CIO 0 (ou CIO 100): os do CPU e depois os de
        cada modulo, que comeca sempre num canal novo (W480, 6-1-4)."""
        per = CP1E_OUT_BITS if outputs else CP1E_IN_BITS
        segs: list[int] = []
        for count in [self._cpu(n, outputs)] + [m[1 if outputs else 0] for m in self.modules]:
            while count > 0:
                segs.append(min(per, count))
                count -= per
        return segs

    def _gather(self, words: list[int], segs: list[int]) -> int:
        mask, shift = 0, 0
        for w, bits in zip(words, segs):
            mask |= (w & _mask(bits)) << shift
            shift += bits
        return mask

    def read_inputs(self, n: int) -> int:
        segs = self.segments(n, False)
        return self._gather(self.read_cio(0, len(segs)), segs)

    def write_outputs(self, n: int, mask: int) -> None:
        values, shift = [], 0
        for bits in self.segments(n, True):
            values.append(mask >> shift & _mask(bits))
            shift += bits
        self.write_cio(CP1E_OUT_WORD, values)

    def read_outputs(self, n: int) -> int:
        segs = self.segments(n, True)
        return self._gather(self.read_cio(CP1E_OUT_WORD, len(segs)), segs)

    def enter_online(self) -> None:
        if self.mode() != "MONITOR":
            self.command("SC", HOSTLINK_MODES["monitor"])

    def set_run(self, run: bool) -> None:
        self.command("SC", HOSTLINK_MODES["monitor" if run else "program"])

    def mode(self) -> str:
        status = int(self.command("MS")[:2], 16)
        return {0: "PROGRAM", 2: "RUN", 3: "MONITOR"}.get(status & 0x03, "?")

    def identify(self) -> str:
        return f"CP1E unidade {self.unit:02d}, modo {self.mode()}"


DRIVERS: dict[str, tuple[str, Callable[[Line, int], PlcDriver]]] = {
    "clic02": ("WEG CLIC-02 (Modbus RTU, RS-485)", lambda line, unit: ClicModbus(line, unit)),
    "hostlink": ("Omron CP1E (Host Link, RS-232C)", lambda line, unit: OmronHostLink(line, unit)),
}
DEFAULTS = {"clic02": {"baudrate": 38400, "framing": "8N2", "unit": 1},
            "hostlink": {"baudrate": 9600, "framing": "7E2", "unit": 0}}
