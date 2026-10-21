"""Ponte com o Factory IO: cliente Modbus TCP e FactoryIOLink contra um servidor falso.

FakeFactoryIO imita o driver "Modbus TCP/IP Server" do Factory IO: os sensores
da cena ficam nas Inputs (discrete inputs), os atuadores sao lidos das Coils, e
so responde ao Slave ID configurado (como na versao 2.2.3).
"""
from __future__ import annotations

import socket
import socketserver
import struct
import threading
import time

import pytest

from ladderide.comm.modbus_tcp import ModbusError, ModbusTcpClient, pack_bits, unpack_bits
from ladderide.compiler import compile_project
from ladderide.core.asm import parse_operand
from ladderide.model import Coil, Contact, Project, Rung
from ladderide.sim import SimState, Simulator
from ladderide.sim.factoryio import FactoryIOConfig, FactoryIOLink


class FakeFactoryIO:
    def __init__(self, unit: int = 1, size: int = 64, port: int = 0):
        self.unit = unit
        self.clients: list[socket.socket] = []
        self.inputs = [False] * size
        self.coils = [False] * size
        self.input_regs = [0] * 16
        self.holding = [0] * 16
        self.requests: list[int] = []
        fake = self

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                sock = self.request
                fake.clients.append(sock)
                while True:
                    try:
                        header = _recv(sock, 7)
                        tid, _, length, unit = struct.unpack(">HHHB", header)
                        pdu = _recv(sock, length - 1)
                    except (ConnectionError, OSError):
                        return
                    if unit != fake.unit:
                        continue                     # Factory IO 2.2.3 ignora outro Slave ID
                    reply = fake.process(pdu)
                    sock.sendall(struct.pack(">HHHB", tid, 0, len(reply) + 1, unit) + reply)

        class Server(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        self.server = Server(("127.0.0.1", port), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def process(self, pdu: bytes) -> bytes:
        fc = pdu[0]
        self.requests.append(fc)
        if fc in (1, 2):
            addr, count = struct.unpack(">HH", pdu[1:5])
            table = self.coils if fc == 1 else self.inputs
            if addr + count > len(table):
                return bytes([fc | 0x80, 2])
            data = pack_bits(table[addr:addr + count])
            return bytes([fc, len(data)]) + data
        if fc == 4:
            addr, count = struct.unpack(">HH", pdu[1:5])
            if addr + count > len(self.input_regs):
                return bytes([fc | 0x80, 2])
            return bytes([fc, 2 * count]) + struct.pack(f">{count}H", *self.input_regs[addr:addr + count])
        if fc == 16:
            addr, count, _ = struct.unpack(">HHB", pdu[1:6])
            if addr + count > len(self.holding):
                return bytes([fc | 0x80, 2])
            self.holding[addr:addr + count] = list(struct.unpack(f">{count}H", pdu[6:6 + 2 * count]))
            return pdu[:5]
        if fc == 15:
            addr, count, _ = struct.unpack(">HHB", pdu[1:6])
            if addr + count > len(self.coils):
                return bytes([fc | 0x80, 2])
            self.coils[addr:addr + count] = unpack_bits(pdu[6:], count)
            return pdu[:5]
        return bytes([fc | 0x80, 1])

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        for sock in self.clients:             # derruba as conexoes abertas (Factory IO fechado)
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()


def _recv(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError
        buf += chunk
    return buf


@pytest.fixture
def fio():
    server = FakeFactoryIO()
    yield server
    server.close()


def wait_for(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------- cliente
def test_bits_pack_little_endian_per_byte():
    values = [True, False, True] + [False] * 6 + [True]
    assert pack_bits(values) == bytes([0b101, 0b10])
    assert unpack_bits(pack_bits(values), len(values)) == values


def test_client_reads_inputs_and_writes_coils(fio):
    fio.inputs[3] = fio.inputs[9] = True
    c = ModbusTcpClient("127.0.0.1", fio.port)
    c.connect()
    try:
        assert c.read_discrete_inputs(0, 12) == [k in (3, 9) for k in range(12)]
        c.write_coils(4, [True, False, True])
        assert fio.coils[4:7] == [True, False, True]
        assert c.read_coils(4, 3) == [True, False, True]
    finally:
        c.close()


def test_client_reports_exception_and_keeps_connection(fio):
    c = ModbusTcpClient("127.0.0.1", fio.port)
    c.connect()
    with pytest.raises(ModbusError) as exc:
        c.read_discrete_inputs(60, 10)
    assert exc.value.code == 2 and "fora da faixa" in str(exc.value)
    assert c.read_discrete_inputs(0, 1) == [False]
    c.close()


def test_client_wrong_unit_times_out(fio):
    c = ModbusTcpClient("127.0.0.1", fio.port, unit=7, timeout=0.2)
    c.connect()
    with pytest.raises(ModbusError, match="tempo esgotado"):
        c.read_discrete_inputs(0, 1)
    assert not c.connected


def test_client_connection_refused():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    with pytest.raises(ModbusError, match="sem conexao"):
        ModbusTcpClient("127.0.0.1", port, timeout=0.5).connect()


# ------------------------------------------------------------------- ponte
def test_config_validation_and_roundtrip():
    assert FactoryIOConfig().validate() == []
    bad = FactoryIOConfig(host="", n_sensors=20, sensor_table="coils", sensor_offset=0, actuator_offset=4,
                          poll_ms=1)
    errors = " | ".join(bad.validate(max_inputs=16))
    assert "endereco do PC" in errors and "16 entradas" in errors and "sobrepostos" in errors
    assert "intervalo" in errors
    cfg = FactoryIOConfig.from_dict({"host": "10.0.0.5", "port": "5020", "n_sensors": 4, "lixo": 1})
    assert (cfg.host, cfg.port, cfg.n_sensors) == ("10.0.0.5", 5020, 4)
    assert FactoryIOConfig.from_dict(cfg.to_dict()) == cfg


def test_client_registers(fio):
    fio.input_regs[2:4] = [1234, 65535]
    c = ModbusTcpClient("127.0.0.1", fio.port)
    c.connect()
    try:
        assert c.read_input_registers(2, 2) == [1234, 65535]
        c.write_registers(1, [7, -5, 70000])                   # fora de 0..65535 e limitado
        assert fio.holding[1:4] == [7, 0, 65535]
    finally:
        c.close()


def test_registers_validation():
    cfg = FactoryIOConfig(n_input_regs=1, input_reg_to=31, n_holding_regs=3, holding_from=30)
    errors = " | ".join(cfg.validate(max_words=32))
    assert "holding registers nao cabem" in errors and "sobrepostos" in errors
    assert FactoryIOConfig(n_sensors=9, n_input_regs=1, n_holding_regs=3).validate(max_inputs=8) == []


def test_simulator_exchanges_analog_registers(fio):
    """Input Reg 0 -> N0; o programa copia N0 para N9 (MOV com ADD 0) -> Holding Reg 1."""
    from ladderide.model.project import MathBox
    p = Project(name="Analogico")
    p.rungs = [Rung([], [MathBox("ADD", ["N0", "5", "N9"])])]
    result = compile_project(p)
    assert result.ok, [str(d) for d in result.diagnostics]
    cfg = FactoryIOConfig(port=fio.port, n_sensors=0, n_actuators=0, n_input_regs=1, input_reg_to=0,
                          n_holding_regs=2, holding_from=8, poll_ms=5)
    link = FactoryIOLink(cfg)
    sim = Simulator(result)
    sim.attach_plant(link)
    fio.input_regs[0] = 500
    link.start()
    try:
        assert link.wait_connected()
        assert wait_for(lambda: link.input_regs == [500])
        sim.start()
        sim.scan_once()
        assert sim.vm.n[0] == 500 and sim.vm.n[9] == 505
        assert wait_for(lambda: fio.holding[:2] == [0, 505])
        sim.stop()
        link.show_words([])                                      # parado: holding registers em 0
        assert wait_for(lambda: fio.holding[:2] == [0, 0])
        sim.start()
        sim.scan_once()
        assert wait_for(lambda: fio.holding[1] == 505)
    finally:
        link.stop()
    assert fio.holding[:2] == [0, 0]                             # desconectar zera os holding


def test_link_maps_sensors_and_outputs_with_offsets(fio):
    cfg = FactoryIOConfig(port=fio.port, sensor_offset=10, n_sensors=4, actuator_offset=20, n_actuators=3,
                          poll_ms=5)
    link = FactoryIOLink(cfg)
    fio.inputs[11] = fio.inputs[13] = True
    link.start()
    try:
        assert link.wait_connected()
        assert wait_for(lambda: link.input_bits() == 0b1010)
        assert link.owned_inputs == 0b1111
        link.advance(10, 0b1111_0101)                 # bits alem de n_actuators sao ignorados
        assert wait_for(lambda: fio.coils[20:23] == [True, False, True])
        assert not any(fio.coils[:20]) and not any(fio.coils[23:])
    finally:
        link.stop()
    assert fio.coils[20:23] == [False] * 3          # desconectar desliga os atuadores
    assert not link.connected


def test_link_sensors_from_coils(fio):
    cfg = FactoryIOConfig(port=fio.port, sensor_table="coils", sensor_offset=8, n_sensors=2, n_actuators=0,
                          poll_ms=5)
    fio.coils[9] = True
    link = FactoryIOLink(cfg)
    link.start()
    try:
        assert wait_for(lambda: link.input_bits() == 0b10)
        assert 15 not in fio.requests                # sem atuadores, nada e escrito
    finally:
        link.stop()


def test_link_reconnects_and_clears_inputs_while_offline():
    first = FakeFactoryIO()
    port = first.port
    first.inputs[0] = True
    link = FactoryIOLink(FactoryIOConfig(port=port, n_sensors=1, n_actuators=1, poll_ms=5))
    link.start()
    try:
        assert wait_for(lambda: link.input_bits() == 1)
        first.close()
        assert wait_for(lambda: not link.connected and link.error is not None)
        assert link.input_bits() == 0
        assert link.drops == 1
        second = FakeFactoryIO(port=port)             # Factory IO aberto de novo
        second.inputs[0] = True
        try:
            assert wait_for(lambda: link.connected and link.input_bits() == 1)
            assert link.error is None
        finally:
            link.stop()
            second.close()
    finally:
        link.stop()


def test_link_reports_address_error(fio):
    link = FactoryIOLink(FactoryIOConfig(port=fio.port, sensor_offset=60, n_sensors=8, poll_ms=5))
    link.start()
    try:
        assert wait_for(lambda: link.error is not None)
        assert "fora da faixa" in link.error and not link.connected
    finally:
        link.stop()


def test_simulator_drives_factoryio_scene(fio):
    """Selo de partida: botao Liga (sensor 0) liga o motor (Q0.0) na cena; Desliga (sensor 1) para."""
    p = Project(name="Esteira")
    p.rungs =[Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.0")]),
               Rung([Contact("XIC", "I0.1")], [Coil("OTU", "Q0.0")])]
    result = compile_project(p)
    assert result.ok, [str(d) for d in result.diagnostics]
    link = FactoryIOLink(FactoryIOConfig(port=fio.port, n_sensors=2, n_actuators=1, poll_ms=5))
    sim = Simulator(result)
    sim.attach_plant(link)
    sim.set_input(0, False)
    link.start()
    try:
        assert link.wait_connected()
        sim.start()

        def run_until(cond):
            def step():
                sim.scan_once()
                return cond()
            return wait_for(step)

        fio.inputs[0] = True                               # operador aperta Liga na cena
        assert run_until(lambda: fio.coils[0])
        fio.inputs[0] = False
        assert wait_for(lambda: link.input_bits() & 1 == 0)
        sim.set_input(0, True)                            # painel de E/S nao manda em entrada do processo
        assert sim.effective_inputs() & 1 == 0
        fio.inputs[1] = True                               # Desliga
        assert run_until(lambda: not fio.coils[0])
        assert sim.state == SimState.RUNNING
    finally:
        link.stop()


def test_cli_factoryio_reads_and_writes(fio, capsys):
    from ladderide.cli import main
    fio.inputs[1] = True
    assert main(["factoryio", "127.0.0.1", "--mb-port", str(fio.port), "--sensors", "3", "--actuators", "4",
                 "--set", "0110"]) == 0
    out = capsys.readouterr().out
    assert "sensores=[0 1 0]" in out and "atuadores=[0 1 1 0]" in out
    assert fio.coils[:4] == [False, True, True, False]
    assert main(["factoryio", "--mb-port", str(fio.port), "--set", "12"]) == 2
    assert main(["factoryio", "--mb-port", str(fio.port), "--sensor-offset", "60"]) == 2
    assert "fora da faixa" in capsys.readouterr().err


def test_example_conveyor_batch_and_jam_over_modbus(fio):
    """examples/factoryio/esteira_lote.ladproj contra o servidor falso: lote de 5 caixas e atolamento."""
    from conftest import ROOT
    result = compile_project(Project.load(ROOT / "examples" / "factoryio" / "esteira_lote.ladproj"))
    assert result.ok
    link = FactoryIOLink(FactoryIOConfig(port=fio.port, n_sensors=4, n_actuators=4, poll_ms=5))
    sim = Simulator(result)
    sim.attach_plant(link)
    link.start()
    START, STOP, ENTRY, EXIT = range(4)
    CONVEYOR, EMITTER, START_LIGHT, LOT_LIGHT = range(4)

    def scans(n=1, until=None, sync=True):
        """Varre o programa; sync espera cada troca completa com a cena antes da proxima varredura."""
        for _ in range(n):
            before = link.cycles
            sim.scan_once()
            if sync:
                assert wait_for(lambda: link.cycles >= before + 2)
            if until is not None and until():
                return True
        return until is None

    try:
        assert link.wait_connected()
        sim.start()
        fio.inputs[STOP] = True                         # Stop NF solto
        scans(3)
        assert not fio.coils[CONVEYOR]
        fio.inputs[START] = True
        assert scans(5, lambda: fio.coils[CONVEYOR] and fio.coils[START_LIGHT] and fio.coils[EMITTER])
        fio.inputs[START] = False
        for box in range(5):                            # cada caixa: entra, sai pelo sensor de saida
            fio.inputs[ENTRY] = True
            assert scans(5, lambda: not fio.coils[EMITTER])
            fio.inputs[ENTRY] = False
            fio.inputs[EXIT] = True
            scans(2)
            fio.inputs[EXIT] = False
            scans(2)
        assert not fio.coils[CONVEYOR] and fio.coils[LOT_LIGHT]     # lote completo
        assert sim.vm.counters[0].acc == 5

        fio.inputs[START] = True                        # novo lote
        assert scans(5, lambda: fio.coils[CONVEYOR] and not fio.coils[LOT_LIGHT])
        fio.inputs[START] = False
        fio.inputs[EXIT] = True                         # caixa presa na saida por mais de 4 s
        scans(3)
        scans(400, sync=False)                          # 4 s de tempo simulado
        assert scans(3, lambda: not fio.coils[CONVEYOR])
        assert sim.vm.read_bit(*parse_operand("M0.1"))  # alarme memorizado
        lights = set()
        for _ in range(12):                             # 1,2 s simulados: o S0.3 troca de estado
            scans(10, sync=False)
            scans(1)
            lights.add(fio.coils[LOT_LIGHT])
        assert lights == {True, False}                  # lampada piscando

        fio.inputs[EXIT] = False
        fio.inputs[STOP] = False                        # Parada desliga o sistema
        assert scans(5, lambda: not fio.coils[START_LIGHT])
    finally:
        link.stop()
