"""Ponte do simulador com um CLP real (WEG CLIC-02 ou Omron CP1E) pela serial.

O programa LADDER compilado roda na IDE; o CLP real e o cartao de E/S:

    entradas fisicas do CLP -> leitura a cada ciclo -> entradas I do programa
    saidas Q do programa    -> escrita a cada ciclo -> saidas fisicas do CLP

Uma thread troca os dados a cada `poll_ms` (como a ponte do Factory IO), entao a
varredura nunca espera pela serial. Os protocolos e enderecos estao em
ladderide.comm.plc_serial.

Seguranca: ao desconectar, a ponte desliga todas as saidas do CLP; se a
comunicacao cair, as entradas voltam a 0 ate reconectar (o programa ve o
processo parado) e a ponte tenta de novo a cada segundo.
"""
from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Callable

from ..comm.plc_serial import BAUDRATES, DEFAULTS, DRIVERS, FRAMINGS, Line, PlcDriver, PlcError, SerialLine

RETRY_S = 1.0


@dataclass
class PlcLinkConfig:
    driver: str = "clic02"        # clic02 | hostlink (ver plc_serial.DRIVERS)
    port: str = ""
    baudrate: int = 38400
    framing: str = "8N2"
    unit: int = 1                 # ID Modbus do CLIC-02 ou numero da unidade Host Link do CP1E
    n_inputs: int = 8
    n_outputs: int = 4
    poll_ms: int = 50
    online_mode: bool = True      # ao conectar: CLIC-02 em RUN, CP1E em MONITOR
    modules: list = field(default_factory=list)   # [entradas, saidas] de cada modulo de expansao, em ordem

    def validate(self) -> list[str]:
        errors = []
        if self.driver not in DRIVERS:
            errors.append("protocolo do CLP inválido")
        if not self.port.strip():
            errors.append("escolha a porta serial do cabo do CLP")
        if self.baudrate not in BAUDRATES:
            errors.append("velocidade inválida")
        if self.framing not in FRAMINGS:
            errors.append("formato serial inválido")
        if self.driver == "clic02" and not 1 <= self.unit <= 99:
            errors.append("o ID do CLIC-02 vai de 1 a 99 (CONFIG > ID no CLP)")
        if self.driver == "hostlink" and not 0 <= self.unit <= 31:
            errors.append("a unidade Host Link vai de 0 a 31")
        if not 0 < self.n_inputs <= 32 or not 0 < self.n_outputs <= 32:
            errors.append("quantidade de E/S inválida")
        if (sum(m[0] for m in self.modules) >= self.n_inputs
                or sum(m[1] for m in self.modules) >= self.n_outputs):    # o CPU tem ao menos 1 de cada
            errors.append("módulos de expansão não conferem com as E/S do projeto")
        if not 20 <= self.poll_ms <= 1000:
            errors.append("intervalo de troca deve ficar entre 20 e 1000 ms")
        return errors

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "PlcLinkConfig":
        cfg = cls()
        for f in fields(cls):
            if f.name in data:
                try:
                    setattr(cfg, f.name, type(getattr(cfg, f.name))(data[f.name]))
                except (TypeError, ValueError):
                    pass
        return cfg

    def use_defaults(self, driver: str) -> None:
        """Padroes de fabrica do protocolo (manual): CLIC-02 38400 8N2 ID 1, CP1E 9600 7E2 unidade 0."""
        self.driver = driver
        for k, v in DEFAULTS.get(driver, {}).items():
            setattr(self, k, v)


def open_driver(config: PlcLinkConfig, line_factory: Callable[[PlcLinkConfig], Line] | None = None) -> PlcDriver:
    line = (line_factory or (lambda c: SerialLine(c.port, c.baudrate, c.framing)))(config)
    driver = DRIVERS[config.driver][1](line, config.unit)
    driver.modules = [(int(a), int(b)) for a, b in config.modules]
    return driver


class PlcLink:
    """Plant do simulador ligado a um CLP real (ver ladderide.sim.simulator.Plant)."""

    def __init__(self, config: PlcLinkConfig, line_factory: Callable[[PlcLinkConfig], Line] | None = None):
        self.config = config
        self._line_factory = line_factory
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._inputs = 0
        self._outputs = 0
        self.plc_outputs = 0          # saidas lidas de volta do CLP (o que os LEDs dele mostram)
        self.plc_mode = ""
        self.model = ""
        self.connected = False
        self.error: str | None = None
        self.cycles = 0
        self.cycle_ms = 0.0
        self.drops = 0
        self._want_run: bool | None = None

    # -------------------------------------------------------------- Plant
    @property
    def owned_inputs(self) -> int:
        return (1 << self.config.n_inputs) - 1

    def input_bits(self) -> int:
        with self._lock:
            return self._inputs

    def advance(self, dt_ms: int, outputs: int) -> None:
        self.show_outputs(outputs)

    def reset(self) -> None:
        self.show_outputs(0)

    def show_outputs(self, outputs: int) -> None:
        with self._lock:
            self._outputs = outputs & ((1 << self.config.n_outputs) - 1)

    @property
    def outputs(self) -> int:
        with self._lock:
            return self._outputs

    # ------------------------------------------------------------- thread
    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop = threading.Event()          # um por thread: uma anterior que nao encerrou nao revive
        self._thread = threading.Thread(target=self._run, args=(self._stop,), name="plc-link", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 3.0) -> None:
        """Encerra a troca; antes de fechar, desliga todas as saidas do CLP."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    def wait_connected(self, timeout: float = 3.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.connected and self.cycles > 0:
                return True
            time.sleep(0.01)
        return self.connected

    def exchange(self, driver: PlcDriver) -> None:
        """Uma troca: le as entradas, escreve as saidas e le de volta as saidas do CLP."""
        c = self.config
        t0 = time.perf_counter()
        inputs = driver.read_inputs(c.n_inputs)
        with self._lock:
            self._inputs = inputs
            outputs = self._outputs
        driver.write_outputs(c.n_outputs, outputs)
        self.plc_outputs = driver.read_outputs(c.n_outputs)
        self.cycle_ms = (time.perf_counter() - t0) * 1000
        self.cycles += 1

    def _lost(self, driver: PlcDriver | None, message: str) -> None:
        if driver is not None:
            driver.close()
        with self._lock:
            self._inputs = 0
        if self.connected:
            self.drops += 1
        self.connected = False
        self.error = message

    def _run(self, stop: threading.Event) -> None:
        driver: PlcDriver | None = None
        period = self.config.poll_ms / 1000
        try:
            while not stop.is_set():
                if driver is None:
                    try:
                        driver = open_driver(self.config, self._line_factory)
                        self.model = driver.identify()
                        if self.config.online_mode:
                            driver.enter_online()
                        self.plc_mode = driver.mode()
                    except PlcError as exc:
                        self._lost(driver, str(exc))
                        driver = None
                        stop.wait(RETRY_S)
                        continue
                t0 = time.monotonic()
                try:
                    want, self._want_run = self._want_run, None
                    if want is not None:
                        driver.set_run(want)
                        self.plc_mode = driver.mode()
                    self.exchange(driver)
                    if self.cycles % 20 == 1:
                        self.plc_mode = driver.mode()
                except PlcError as exc:
                    self._lost(driver, str(exc))
                    driver = None
                    stop.wait(RETRY_S)
                    continue
                self.connected = True
                self.error = None
                stop.wait(max(0.0, period - (time.monotonic() - t0)))
        finally:
            if driver is not None:
                try:
                    driver.write_outputs(self.config.n_outputs, 0)
                except PlcError:
                    pass
                driver.close()
            self.connected = False

    def request_run(self, run: bool) -> None:
        """RUN/STOP no CLP pedido pela interface: a thread executa entre duas trocas."""
        self._want_run = run


def plc_command(config: PlcLinkConfig, action: Callable[[PlcDriver], str],
                line_factory: Callable[[PlcLinkConfig], Line] | None = None) -> str:
    """Comando avulso (RUN/STOP) numa conexao propria, com a ponte desligada."""
    driver = open_driver(config, line_factory)
    try:
        return action(driver)
    finally:
        driver.close()


def probe(config: PlcLinkConfig, line_factory: Callable[[PlcLinkConfig], Line] | None = None) -> tuple[bool, str]:
    """Testar: abre a porta, identifica o CLP e le as entradas. Nao escreve nada."""
    try:
        driver = open_driver(config, line_factory)
    except PlcError as exc:
        return False, str(exc)
    try:
        model = driver.identify()
        mode = driver.mode()
        inputs = driver.read_inputs(config.n_inputs)
        on = [str(k) for k in range(config.n_inputs) if inputs >> k & 1]
        return True, (f"{model} respondeu em {config.port} ({config.baudrate} {config.framing}), modo {mode}. "
                      f"Entradas ligadas: {', '.join(on) if on else 'nenhuma'}.")
    except PlcError as exc:
        return False, str(exc)
    finally:
        driver.close()
