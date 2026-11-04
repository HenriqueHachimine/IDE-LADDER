"""Ponte do simulador com o Factory IO pelo driver "Modbus TCP/IP Server".

O Factory IO e o servidor (escravo Modbus); a IDE e o cliente:

    sensores da cena   -> Inputs (ou Coils)  -> FC02/FC01 -> entradas I0.0...
    valores analogicos -> Input Registers (ou Holding) -> FC04/FC03 -> registradores N (a partir de input_reg_to)
    saidas Q0.0...     -> FC15 -> Coils                    -> atuadores da cena
    registradores N (a partir de holding_from) -> FC16 -> Holding Registers -> atuadores analogicos

Uma thread troca os dados a cada `poll_ms` e guarda o ultimo valor lido; o
simulador so le e escreve esses valores (protocolo Plant), entao a varredura
nunca espera pela rede. O Factory IO roda em tempo real, por isso a simulacao
ligada a ele deve rodar a 1x (a interface trava a velocidade).

Seguranca: ao desconectar, a ponte escreve 0 em todas as coils e holding
registers; se a conexao cair, as entradas e os registradores lidos voltam a 0
ate reconectar.

Opcoes do driver (docs.factoryio.com/manual/drivers/modbus-server): Write Digital
(Inputs ou Coils) e Write Register (Input ou Holding Registers) dizem onde o
Factory IO escreve os sensores; a IDE le de la. Read Digital e Read Register
precisam ser Coils e Holding Registers: um cliente Modbus nao consegue escrever
em Inputs nem em Input Registers. Scale: o Factory IO multiplica o valor
analogico pela escala antes de enviar (3,14 com escala 100 vira 314); a IDE
mostra o valor bruto e o dividido pela escala. O driver aceita ate 256 pontos
digitais e 64 registradores de cada lado.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, fields
from typing import Callable

from ..comm.modbus_tcp import ModbusError, ModbusTcpClient

SENSOR_TABLES = {"inputs": "Inputs (FC02)", "coils": "Coils (FC01)"}            # Write Digital
REGISTER_TABLES = {"input": "Input Registers (FC04)", "holding": "Holding Registers (FC03)"}   # Write Register
RETRY_S = 1.0
MAX_BITS = 256          # Digital Inputs/Outputs do driver (maximo do Factory IO)
MAX_REGS = 64           # Register Inputs/Outputs do driver


@dataclass
class FactoryIOConfig:
    host: str = "127.0.0.1"
    port: int = 502
    unit: int = 1                 # Slave ID configurado no driver do Factory IO
    sensor_table: str = "inputs"  # onde o Factory IO escreve os sensores ("Write Digital")
    sensor_offset: int = 0
    n_sensors: int = 8            # Input k -> I0.k
    actuator_offset: int = 0      # atuadores sempre em Coils ("Read Digital" = Coils)
    n_actuators: int = 8          # Q0.k -> Coil k
    poll_ms: int = 20
    input_reg_offset: int = 0     # Input Reg k -> N(input_reg_to + k)
    n_input_regs: int = 0
    input_reg_to: int = 0
    holding_offset: int = 0       # N(holding_from + k) -> Holding Reg k
    n_holding_regs: int = 0
    holding_from: int = 8
    register_table: str = "input"  # onde o Factory IO escreve os valores analogicos ("Write Register")
    scale: float = 1.0             # "Scale" do driver (so para exibir o valor de engenharia)
    auto_connect: bool = False     # conectar ao abrir a IDE ("Auto connect")

    def validate(self, max_inputs: int = 16, max_outputs: int = 16, max_words: int = 32) -> list[str]:
        """max_*: E/S e registradores N do projeto (pontos alem disso ficam sem endereco no CLP)."""
        errors = []
        if not self.host.strip():
            errors.append("informe o endereço do PC com o Factory IO")
        if not 1 <= self.port <= 65535:
            errors.append("porta TCP invalida")
        if not 0 <= self.unit <= 255:
            errors.append("Slave ID deve estar entre 0 e 255")
        if self.sensor_table not in SENSOR_TABLES:
            errors.append("tabela de sensores invalida")
        if self.register_table not in REGISTER_TABLES:
            errors.append("tabela de registradores invalida")
        if not 0 <= self.n_sensors <= MAX_BITS or not 0 <= self.n_actuators <= MAX_BITS:
            errors.append(f"o driver do Factory IO vai até {MAX_BITS} pontos digitais de cada lado")
        if not 0 <= self.n_input_regs <= MAX_REGS or not 0 <= self.n_holding_regs <= MAX_REGS:
            errors.append(f"o driver do Factory IO vai até {MAX_REGS} registradores de cada lado")
        if not self.scale > 0:
            errors.append("a escala deve ser maior que zero")
        if not (self.n_sensors or self.n_actuators or self.n_input_regs or self.n_holding_regs):
            errors.append("nada a trocar: informe entradas, coils ou registradores")
        for offset, n in ((self.sensor_offset, self.n_sensors), (self.actuator_offset, self.n_actuators),
                          (self.input_reg_offset, self.n_input_regs), (self.holding_offset, self.n_holding_regs)):
            if not 0 <= offset <= 65535 - n:
                errors.append("endereço inicial inválido")
                break
        if (self.sensor_table == "coils" and self.n_sensors and self.n_actuators
                and self.sensor_offset < self.actuator_offset + self.n_actuators
                and self.actuator_offset < self.sensor_offset + self.n_sensors):
            errors.append("sensores e atuadores nas Coils com endereços sobrepostos")
        if (self.register_table == "holding" and self.n_input_regs and self.n_holding_regs
                and self.input_reg_offset < self.holding_offset + self.n_holding_regs
                and self.holding_offset < self.input_reg_offset + self.n_input_regs):
            errors.append("registradores de sensores e de atuadores nos Holding Registers com endereços sobrepostos")
        if self.n_input_regs and not 0 <= self.input_reg_to <= max_words - self.n_input_regs:
            errors.append(f"os registradores de entrada não cabem em N0..N{max_words - 1}")
        if self.n_holding_regs and not 0 <= self.holding_from <= max_words - self.n_holding_regs:
            errors.append(f"os holding registers não cabem em N0..N{max_words - 1}")
        if (self.n_input_regs and self.n_holding_regs
                and self.input_reg_to < self.holding_from + self.n_holding_regs
                and self.holding_from < self.input_reg_to + self.n_input_regs):
            errors.append("registradores N de entrada e de saída sobrepostos")
        if not 5 <= self.poll_ms <= 1000:
            errors.append("intervalo de troca deve ficar entre 5 e 1000 ms")
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "FactoryIOConfig":
        cfg = cls()
        for f in fields(cls):
            if f.name in data:
                try:
                    setattr(cfg, f.name, type(getattr(cfg, f.name))(data[f.name]))
                except (TypeError, ValueError):
                    pass
        return cfg


class FactoryIOLink:
    """Plant do simulador ligado ao Factory IO (ver ladderide.sim.simulator.Plant)."""

    def __init__(self, config: FactoryIOConfig,
                 client_factory: Callable[[FactoryIOConfig], ModbusTcpClient] | None = None):
        self.config = config
        self._factory = client_factory or (lambda c: ModbusTcpClient(c.host, c.port, c.unit, timeout=1.0))
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._sensors = 0
        self._outputs = 0
        self._in_regs = [0] * config.n_input_regs
        self._out_regs = [0] * config.n_holding_regs
        self.connected = False
        self.error: str | None = None
        self.cycles = 0               # trocas completas (leitura + escrita)
        self.cycle_ms = 0.0           # duracao da ultima troca
        self.drops = 0                # quedas de uma conexao que estava ativa

    # -------------------------------------------------------------- Plant
    @property
    def owned_inputs(self) -> int:
        return (1 << self.config.n_sensors) - 1

    def input_bits(self) -> int:
        with self._lock:
            return self._sensors

    def input_words(self) -> dict[int, int]:
        """Registradores N escritos pelo processo antes de cada varredura (Input Reg k -> N)."""
        with self._lock:
            return {self.config.input_reg_to + k: v for k, v in enumerate(self._in_regs)}

    def advance(self, dt_ms: int, outputs: int) -> None:
        self.show_outputs(outputs)

    def advance_words(self, words: list[int]) -> None:
        """Registradores N do programa depois da varredura (N -> Holding Reg k)."""
        self.show_words(words)

    def reset(self) -> None:
        self.show_outputs(0)
        self.show_words([])

    def show_outputs(self, outputs: int) -> None:
        """Saidas a enviar na proxima troca (tambem com a simulacao pausada ou parada)."""
        with self._lock:
            self._outputs = outputs & ((1 << self.config.n_actuators) - 1)

    def show_words(self, words: list[int]) -> None:
        """Registradores N a enviar aos holding registers; lista vazia = tudo 0 (parado)."""
        c = self.config
        values = [words[c.holding_from + k] if c.holding_from + k < len(words) else 0
                  for k in range(c.n_holding_regs)]
        with self._lock:
            self._out_regs = values

    @property
    def outputs(self) -> int:
        with self._lock:
            return self._outputs

    @property
    def input_regs(self) -> list[int]:
        with self._lock:
            return list(self._in_regs)

    @property
    def holding_regs(self) -> list[int]:
        with self._lock:
            return list(self._out_regs)

    # ------------------------------------------------------------- thread
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="factoryio-link", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Encerra a troca; antes de fechar, desliga todos os atuadores no Factory IO."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def wait_connected(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected and self.cycles > 0:
                return True
            if self.error and not self.running:
                return False
            time.sleep(0.01)
        return self.connected

    def exchange(self, client: ModbusTcpClient) -> None:
        """Uma troca completa: le sensores e registradores de entrada, escreve saidas e holding."""
        c = self.config
        t0 = time.perf_counter()
        sensors = 0
        if c.n_sensors:
            read = client.read_discrete_inputs if c.sensor_table == "inputs" else client.read_coils
            for k, v in enumerate(read(c.sensor_offset, c.n_sensors)):
                sensors |= int(v) << k
        read_regs = client.read_input_registers if c.register_table == "input" else client.read_holding_registers
        in_regs = read_regs(c.input_reg_offset, c.n_input_regs) if c.n_input_regs else []
        with self._lock:
            self._sensors = sensors
            self._in_regs = in_regs
            outputs = self._outputs
            out_regs = list(self._out_regs)
        if c.n_actuators:
            client.write_coils(c.actuator_offset, [bool(outputs >> k & 1) for k in range(c.n_actuators)])
        if c.n_holding_regs:
            client.write_registers(c.holding_offset, out_regs)
        self.cycle_ms = (time.perf_counter() - t0) * 1000
        self.cycles += 1

    def _lost(self, client: ModbusTcpClient, message: str) -> None:
        client.close()
        with self._lock:
            self._sensors = 0          # sem dados do processo: sensores desativados
            self._in_regs = [0] * self.config.n_input_regs
        if self.connected:
            self.drops += 1
        self.connected = False
        self.error = message

    def _run(self) -> None:
        client = self._factory(self.config)
        period = self.config.poll_ms / 1000
        try:
            while not self._stop.is_set():
                if not client.connected:
                    try:
                        client.connect()
                    except ModbusError as exc:
                        self._lost(client, str(exc))
                        self._stop.wait(RETRY_S)
                        continue
                t0 = time.monotonic()
                try:
                    self.exchange(client)
                except ModbusError as exc:
                    self._lost(client, str(exc))
                    self._stop.wait(RETRY_S)
                    continue
                self.connected = True
                self.error = None
                self._stop.wait(max(0.0, period - (time.monotonic() - t0)))
        finally:
            c = self.config
            if client.connected:
                try:
                    if c.n_actuators:
                        client.write_coils(c.actuator_offset, [False] * c.n_actuators)
                    if c.n_holding_regs:
                        client.write_registers(c.holding_offset, [0] * c.n_holding_regs)
                except ModbusError:
                    pass
            client.close()
            self.connected = False


def probe(config: FactoryIOConfig, client_factory: Callable[[FactoryIOConfig], ModbusTcpClient] | None = None,
          timeout: float = 1.5) -> tuple[bool, str]:
    """Testar conexao: conecta, le o primeiro sensor (ou registrador) e fecha. Nao escreve nada."""
    client = (client_factory or (lambda c: ModbusTcpClient(c.host, c.port, c.unit, timeout=timeout)))(config)
    c = config
    try:
        client.connect()
        if c.n_sensors:
            read = client.read_discrete_inputs if c.sensor_table == "inputs" else client.read_coils
            read(c.sensor_offset, c.n_sensors)
            what = f"{c.n_sensors} sensor(es) lidos"
        elif c.n_input_regs:
            read = client.read_input_registers if c.register_table == "input" else client.read_holding_registers
            read(c.input_reg_offset, c.n_input_regs)
            what = f"{c.n_input_regs} registrador(es) lidos"
        else:
            what = "conexão aberta"
        return True, f"O Factory IO respondeu em {c.host}:{c.port} (Slave ID {c.unit}): {what}."
    except ModbusError as exc:
        return False, str(exc)
    finally:
        client.close()
