"""CLP real: WEG CLIC-02 (Modbus RTU) e Omron CP1E (Host Link) com escravos falsos na serial."""
from __future__ import annotations

import time

import pytest

from ladderide.comm.plc_serial import (CLIC_INPUTS, CLIC_MARKERS, CLIC_MODEL, CLIC_OUTPUTS, CLIC_RUN, ClicModbus,
                                       OmronHostLink, PlcError, hostlink_fcs, hostlink_frame)
from ladderide.core.crc import crc16_modbus
from ladderide.model.controllers import controller_by_id, load_controllers
from ladderide.sim.plc_link import PlcLink, PlcLinkConfig, plc_command, probe


class FakeLine:
    """Serial falsa: cada write gera a resposta do escravo, entregue pelos reads."""

    def __init__(self, slave):
        self.slave = slave
        self.rx = b""
        self.sent: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.sent.append(data)
        self.rx += self.slave(data)

    def read(self, size: int, timeout: float) -> bytes:
        out, self.rx = self.rx[:size], self.rx[size:]
        return out

    def flush_input(self) -> None:
        self.rx = b""

    def close(self) -> None:
        self.closed = True


class FakeClic:
    """CLIC-02 escravo Modbus: programa ponte M01..M08 -> Q01..Q08 quando em RUN."""

    def __init__(self, unit: int = 1):
        self.unit = unit
        self.regs = {CLIC_RUN: 0, CLIC_MODEL: 0x30, CLIC_MARKERS: 0, CLIC_INPUTS: 0, CLIC_OUTPUTS: 0}
        self.silent = False

    def _reply(self, pdu: bytes) -> bytes:
        frame = bytes([self.unit]) + pdu
        crc = crc16_modbus(frame)
        return frame + bytes([crc & 0xFF, crc >> 8])

    def __call__(self, frame: bytes) -> bytes:
        if self.silent or frame[0] != self.unit:
            return b""
        assert crc16_modbus(frame[:-2]) == frame[-2] | frame[-1] << 8
        fc, addr = frame[1], frame[2] << 8 | frame[3]
        if fc == 0x03:
            count = frame[5]
            data = b"".join(self.regs.get(addr + i, 0).to_bytes(2, "big") for i in range(count))
            return self._reply(bytes([0x03, len(data)]) + data)
        if fc == 0x06:
            if addr in (CLIC_INPUTS, CLIC_OUTPUTS, CLIC_MODEL):
                return self._reply(bytes([0x86, 0x51]))
            self.regs[addr] = frame[4] << 8 | frame[5]
            self.regs[CLIC_OUTPUTS] = self.regs[CLIC_MARKERS] & 0xFF if self.regs[CLIC_RUN] else 0
            return self._reply(frame[1:6])
        if fc == 0x10:                                 # escrita de varias words (M01.. e M11..)
            count = frame[5]
            for i in range(count):
                self.regs[addr + i] = frame[7 + 2 * i] << 8 | frame[8 + 2 * i]
            self.regs[CLIC_OUTPUTS] = self.regs[CLIC_MARKERS] & 0xFF if self.regs[CLIC_RUN] else 0
            return self._reply(frame[1:6])
        return self._reply(bytes([fc | 0x80, 0x51]))


class FakeCp1e:
    """CP1E em Host Link: canais CIO e modo (00 PROGRAM, 02 MONITOR, 03 RUN)."""

    def __init__(self, unit: int = 0):
        self.unit = unit
        self.cio = {0: 0, 1: 0, 100: 0, 101: 0}
        self.mode = 0x00

    def _reply(self, header: str, end: str, data: str = "") -> bytes:
        body = f"@{self.unit:02d}{header}{end}{data}"
        return (body + hostlink_fcs(body) + "*\r").encode()

    def __call__(self, frame: bytes) -> bytes:
        text = frame.decode()
        assert text.endswith("*\r") and hostlink_fcs(text[:-4]) == text[-4:-2]
        if int(text[1:3]) != self.unit:
            return b""
        header, body = text[3:5], text[5:-4]
        if header == "RR":
            word, count = int(body[:4]), int(body[4:8])
            return self._reply(header, "00", "".join(f"{self.cio.get(word + i, 0):04X}" for i in range(count)))
        if header == "WR":
            word = int(body[:4])
            for i in range(len(body[4:]) // 4):
                self.cio[word + i] = int(body[4 + 4 * i:8 + 4 * i], 16)
            return self._reply(header, "00")
        if header == "SC":
            self.mode = {"00": 0, "02": 3, "03": 2}[body]
            return self._reply(header, "00")
        if header == "MS":
            return self._reply(header, "00", f"{self.mode:02X}00")
        return self._reply(header, "16")


# ------------------------------------------------------------------ protocolos
def test_clic_driver_reads_inputs_and_writes_markers():
    slave = FakeClic(unit=3)
    d = ClicModbus(FakeLine(slave), unit=3)
    assert d.identify() == "CLW-02/20VR-D"
    slave.regs[CLIC_INPUTS] = 0b1000_0000_0101
    assert d.read_inputs(12) == 0b1000_0000_0101
    assert d.read_inputs(8) == 0b0101               # so os pontos do projeto
    d.enter_online()
    assert d.mode() == "RUN"
    d.write_outputs(8, 0b1010_0001)
    assert slave.regs[CLIC_MARKERS] == 0b1010_0001  # M01, M06, M08
    assert d.read_outputs(8) == 0b1010_0001         # o programa ponte copiou para Q
    d.set_run(False)
    assert d.mode() == "STOP"


def test_clic_frames_match_manual_example():
    """Manual do CLIC-02 (10.4): leitura de 1 word no endereco 0003 do escravo 01 = 01 03 00 03 00 01 CRC."""
    line = FakeLine(FakeClic(unit=1))
    ClicModbus(line, unit=1).read_words(0x0003)
    frame = line.sent[0]
    assert frame[:6] == bytes.fromhex("010300030001")
    assert frame[6] | frame[7] << 8 == crc16_modbus(frame[:6])


def test_clic_errors():
    slave = FakeClic()
    d = ClicModbus(FakeLine(slave), unit=1, timeout=0.05)
    with pytest.raises(PlcError, match="telegrama inválido"):
        d.write_word(CLIC_INPUTS, 1)                # entradas sao so leitura
    slave.silent = True
    with pytest.raises(PlcError, match="não respondeu"):
        d.read_inputs(8)
    bad = FakeLine(lambda f: bytes([1, 3, 2, 0, 0, 0, 0]))
    with pytest.raises(PlcError, match="CRC"):
        ClicModbus(bad, unit=1, timeout=0.05).read_inputs(8)


def test_hostlink_frame_and_fcs():
    assert hostlink_frame(0, "RR", "00000001") == b"@00RR0000000141*\r"
    assert hostlink_fcs("@00RR00000001") == "41"


def test_cp1e_driver_uses_cio_allocation():
    plc = FakeCp1e()
    d = OmronHostLink(FakeLine(plc))
    plc.cio[0] = 0b1000_0000_0001                   # 0.00 e 0.11
    plc.cio[1] = 0b10_0001                          # 1.00 e 1.05
    assert d.read_inputs(18) == 0b1000_0000_0001 | (0b10_0001 << 12)
    d.enter_online()
    assert d.mode() == "MONITOR"
    d.write_outputs(12, 0b1001_1000_0001)           # 100.00, 100.07, 101.00, 101.03
    assert plc.cio[100] == 0b1000_0001 and plc.cio[101] == 0b1001
    assert d.read_outputs(12) == 0b1001_1000_0001
    d.set_run(False)
    assert d.mode() == "PROGRAM"


def test_cp1e_end_code_error():
    d = OmronHostLink(FakeLine(FakeCp1e()))
    with pytest.raises(PlcError, match="comando não suportado"):
        d.command("XX")
    with pytest.raises(PlcError, match="não respondeu"):
        OmronHostLink(FakeLine(FakeCp1e(unit=5)), unit=1, timeout=0.05).mode()


# ------------------------------------------------------------------ ponte
def _wait(cond, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.mark.parametrize("driver,slave_cls", [("clic02", FakeClic), ("hostlink", FakeCp1e)])
def test_link_exchanges_and_turns_outputs_off(driver, slave_cls):
    slave = slave_cls()
    cfg = PlcLinkConfig(port="COMX", n_inputs=8, n_outputs=4, poll_ms=20)
    cfg.use_defaults(driver)
    link = PlcLink(cfg, line_factory=lambda c: FakeLine(slave))
    link.start()
    try:
        assert link.wait_connected()
        if driver == "clic02":
            slave.regs[CLIC_INPUTS] = 0b101
        else:
            slave.cio[0] = 0b101
        assert _wait(lambda: link.input_bits() == 0b101)
        link.advance(10, 0b1011)
        assert _wait(lambda: link.plc_outputs == 0b1011)
        assert link.plc_mode in ("RUN", "MONITOR")
    finally:
        link.stop()
    out = slave.regs[CLIC_MARKERS] if driver == "clic02" else slave.cio[100]
    assert out == 0                                 # saidas desligadas ao desconectar
    assert not link.connected


def test_link_reconnects_after_silence():
    slave = FakeClic()
    cfg = PlcLinkConfig(port="COMX", poll_ms=20)
    link = PlcLink(cfg, line_factory=lambda c: FakeLine(slave))
    link.start()
    try:
        assert link.wait_connected()
        slave.regs[CLIC_INPUTS] = 1
        assert _wait(lambda: link.input_bits() == 1)
        slave.silent = True
        assert _wait(lambda: not link.connected)
        assert link.input_bits() == 0               # sem dados: entradas desligadas
        slave.silent = False
        assert _wait(lambda: link.connected, 4.0)
    finally:
        link.stop()


def test_probe_and_command():
    slave = FakeCp1e()
    slave.cio[0] = 0b11
    cfg = PlcLinkConfig(port="COMX")
    cfg.use_defaults("hostlink")
    ok, text = probe(cfg, line_factory=lambda c: FakeLine(slave))
    assert ok and "PROGRAM" in text and "0, 1" in text
    assert slave.cio[100] == 0                      # testar nao escreve
    assert plc_command(cfg, lambda d: (d.set_run(True), d.mode())[1], lambda c: FakeLine(slave)) == "MONITOR"
    ok, text = probe(PlcLinkConfig(port="COMX", unit=9), line_factory=lambda c: FakeLine(FakeClic(unit=1)))
    assert not ok and "não respondeu" in text


def test_config_validation_and_defaults():
    cfg = PlcLinkConfig()
    assert any("porta" in e for e in cfg.validate())
    cfg.port = "COM3"
    assert cfg.validate() == []
    cfg.use_defaults("hostlink")
    assert (cfg.baudrate, cfg.framing, cfg.unit) == (9600, "7E2", 0)
    cfg.unit = 40
    assert any("0 a 31" in e for e in cfg.validate())
    assert PlcLinkConfig.from_dict(cfg.to_dict()) == cfg


# ------------------------------------------------------------------ controladores
def test_weg_and_omron_controllers_listed():
    ids = [c.id for c in load_controllers()]
    for cid in ("clw-02-20vr-d", "clw-02-12hr-d", "clw-02-10hr-a", "cp1e-e20sdr-a", "cp1e-n40dr-a", "cp1e-e10dr-a"):
        assert cid in ids
    vr = controller_by_id("clw-02-20vr-d")
    assert (vr.inputs, vr.outputs, vr.link, vr.family) == (12, 8, "clic02", "WEG CLIC-02")
    assert vr.markers == 63 and vr.timers == 31
    n40 = controller_by_id("cp1e-n40dr-a")
    assert (n40.inputs, n40.outputs, n40.link, n40.family) == (24, 16, "hostlink", "Omron CP1E tipo N / NA")
    assert controller_by_id("cp1e-e10dr-a").link == ""      # so USB: sem ligacao com a IDE
    # aparecem junto com os outros, na ordem: Arduino, WEG, Omron, Allen-Bradley
    families = list(dict.fromkeys(c.family for c in load_controllers()))
    assert families.index("WEG CLIC-02") == families.index("Arduino") + 1
    assert families.index("Omron CP1E tipo E") == families.index("WEG CLIC-02") + 1
    assert families.index("Omron CP1E tipo N / NA") == families.index("WEG CLIC-02") + 2
