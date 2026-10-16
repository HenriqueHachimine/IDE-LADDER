"""Comunicacao Desktop <-> firmware usando o dispositivo virtual (codigo C real do firmware)."""
from __future__ import annotations

import os
import struct
import subprocess
import time

import pytest

from conftest import ROOT, VECTORS
from ladderide.comm import (CommError, DevState, DeviceClient, DeviceError, Fault, ProtoError, Snapshot)
from ladderide.comm.equivalence import load_scan_vectors, run_vector_on_device
from ladderide.comm.frames import FrameParser, encode
from ladderide.comm.monitor import MonitorSource
from ladderide.comm.protocol import Cmd
from ladderide.comm.virtual import BuildError, host_tool, start_virtual_device
from ladderide.compiler import compile_project
from ladderide.core import assemble, build_image, encode as encode_image
from ladderide.core.crc import crc32
from ladderide.model import Project

DEMO = ROOT / "examples" / "demo" / "demonstracao.ladproj"


# ------------------------------------------------------------------- quadros
def test_frame_roundtrip_split_and_garbage():
    frame = encode(0x21, 5, 0, b"\x01\x02\x03")
    p = FrameParser()
    stream = b"\x00\xa5\x13" + frame + encode(0x02, 6)
    frames = []
    for k in range(len(stream)):
        frames += p.feed(stream[k:k + 1])
    assert [(f.type, f.seq, f.payload) for f in frames] == [(0x21, 5, b"\x01\x02\x03"), (0x02, 6, b"")]
    bad = bytearray(frame)
    bad[-1] ^= 0xFF
    assert FrameParser().feed(bytes(bad) + frame)[0].seq == 5


def test_frame_timeout_discards_partial():
    t = [0.0]
    p = FrameParser(clock=lambda: t[0])
    frame = encode(1, 1)
    assert p.feed(frame[:5]) == []
    t[0] = 1.0
    assert p.feed(frame[5:]) == []
    assert len(p.feed(frame)) == 1


def test_c_selftest():
    try:
        exe = host_tool("plc_core_selftest")
    except BuildError as exc:
        if os.environ.get("LADDER_REQUIRE_C") == "1":
            pytest.fail(str(exc))
        pytest.skip(str(exc))
    proc = subprocess.run([str(exe)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# ----------------------------------------------------- dispositivo virtual
@pytest.fixture
def device(tmp_path):
    try:
        host_tool("virtual_device")
    except BuildError as exc:
        if os.environ.get("LADDER_REQUIRE_C") == "1":
            pytest.fail(str(exc))
        pytest.skip(str(exc))
    storage = tmp_path / "flash.ldrb"
    clients: list[DeviceClient] = []

    def start(*extra: str) -> DeviceClient:
        c = DeviceClient(start_virtual_device(storage, *extra), timeout=0.5)
        clients.append(c)
        c.info()  # espera o processo ficar pronto
        return c

    start.storage = storage
    yield start
    for c in clients:
        c.close()


def demo_image() -> bytes:
    r = compile_project(Project.load(DEMO))
    assert r.ok
    return r.image


def wait_scans(client: DeviceClient, n: int = 5) -> Snapshot:
    first = client.read_vars().scan_count
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        snap = client.read_vars()
        if snap.scan_count >= first + n:
            return snap
        time.sleep(0.02)
    raise AssertionError("dispositivo nao esta varrendo")


def test_info_and_empty_device(device):
    c = device()
    info = c.info()
    assert (info.n_inputs, info.n_outputs, info.fmt_major) == (8, 8, 1)
    st = c.status()
    assert st.state == DevState.STOP and not st.has_program
    with pytest.raises(DeviceError) as e:
        c.set_mode(True)
    assert e.value.code == ProtoError.NO_PROGRAM


def test_download_run_monitor_stop_and_persist(device):
    c = device()
    image = demo_image()
    progress = []
    res = c.download(image, progress=lambda a, b: progress.append((a, b)))
    assert progress[-1] == (len(image), len(image))
    st = c.status()
    assert st.has_program and st.build_id == res.build_id and st.state == DevState.STOP

    assert c.set_mode(True) == DevState.RUN
    c.sim_set_inputs(0b0001)                       # Partida
    wait_scans(c)
    c.sim_set_inputs(0b0000)
    snap = wait_scans(c)
    assert snap.q_logical & 1 and snap.q_commanded & 1   # selo manteve o motor
    # monitor: energia do contato de selo vinda do dispositivo
    r = compile_project(Project.load(DEMO))
    src = MonitorSource(snap, r)
    motor_contact = r.pc_element[4]                # SOR, BST, XIC Partida, NXB, XIC Motor
    assert src.element_power(motor_contact) and src.operand_value(motor_contact)
    assert src.branch_power(r.pc_element[5])       # BND do paralelo energizado
    assert src.timer_state(0)["acc"] > 0

    c.sim_set_inputs(0b0010)                       # Parada
    snap = wait_scans(c)
    assert not snap.q_logical & 1
    assert c.set_mode(False) == DevState.STOP
    assert c.read_vars().q_commanded == 0          # estado seguro

    # reinicio do dispositivo: programa persiste, volta em STOP
    c.transport.kill()
    c2 = device()
    st2 = c2.status()
    assert st2.has_program and st2.build_id == res.build_id and st2.state == DevState.STOP


def test_download_refused_in_run_unless_requested(device):
    c = device()
    c.download(demo_image())
    c.set_mode(True)
    with pytest.raises(CommError, match="RUN"):
        c.download(demo_image())
    c.download(demo_image(), stop_if_running=True)
    assert c.status().state == DevState.STOP


def test_corrupted_and_invalid_transfers_keep_old_program(device):
    c = device()
    good = demo_image()
    c.download(good)
    old = c.status().build_id
    # CRC declarado errado
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(good), crc32(good) ^ 1))
    c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 0) + good[:512])
    with pytest.raises(DeviceError) as e:
        c.request(Cmd.LOAD_END)
    assert e.value.code == ProtoError.IMAGE_CRC
    with pytest.raises(DeviceError) as e:
        c.request(Cmd.LOAD_COMMIT)
    assert e.value.code == ProtoError.BAD_STATE
    c.request(Cmd.LOAD_ABORT)
    # imagem estruturalmente invalida (CRC correto): rejeitada pela validacao do firmware
    bad = encode_image(assemble("SOR\nBND\nEOR"))
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(bad), crc32(bad)))
    c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 0) + bad)
    with pytest.raises(DeviceError) as e:
        c.request(Cmd.LOAD_END)
    assert e.value.code == ProtoError.IMAGE_INVALID and "BRANCH_ERROR" in str(e.value)
    c.request(Cmd.LOAD_ABORT)
    # o cliente nunca envia imagem invalida
    with pytest.raises(Exception):
        c.download(bad)
    assert c.status().build_id == old and c.status().state == DevState.STOP


def test_out_of_order_and_repeated_chunks(device):
    c = device()
    image = demo_image()
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(image), crc32(image)))
    with pytest.raises(DeviceError) as e:
        c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 100) + image[100:150])
    assert e.value.code == ProtoError.BAD_OFFSET
    first = struct.pack("<I", 0) + image[:100]
    assert struct.unpack("<I", c.request(Cmd.LOAD_CHUNK, first))[0] == 100
    # mesmo bloco reenviado como novo pedido (ex.: ACK perdido): aceito sem duplicar
    assert struct.unpack("<I", c.request(Cmd.LOAD_CHUNK, first))[0] == 100
    c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 100) + image[100:])
    c.request(Cmd.LOAD_END)
    c.request(Cmd.LOAD_COMMIT)
    assert c.status().has_program


def test_retransmission_is_idempotent(device):
    c = device()
    image = demo_image()
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(image), crc32(image)))
    c.seq = (c.seq + 1) & 0xFF
    frame = encode(Cmd.LOAD_CHUNK, c.seq, 0, struct.pack("<I", 0) + image[:64])
    c.transport.write(frame)
    c.transport.write(frame)                       # repeticao identica (mesmo seq)
    time.sleep(0.2)
    replies = [f for f in c.parser.feed(c.transport.read(0.5)) if f.seq == c.seq]
    assert len(replies) == 2 and replies[0].payload == replies[1].payload == struct.pack("<I", 64)
    assert struct.unpack("<I", c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 64) + image[64:]))[0] == len(image)


def test_power_loss_during_transfer(device):
    c = device()
    c.download(demo_image())
    old = c.status().build_id
    other = build_image(assemble("SOR\nXIC I0.0\nOTE Q0.0\nEOR"))
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(other), crc32(other)))
    c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 0) + other[:20])
    c.transport.kill()                             # "queda de energia" no meio da carga
    c2 = device()
    st = c2.status()
    assert st.has_program and st.build_id == old and st.state == DevState.STOP


def test_load_session_timeout(device):
    c = device()
    image = demo_image()
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(image), crc32(image)))
    assert c.status().state == DevState.PROGRAM_LOADING
    time.sleep(5.3)
    assert c.status().state == DevState.STOP


def test_incompatible_program_rejected(device):
    c = device()
    big = assemble(".inputs 16\nSOR\nXIC I1.7\nOTE Q0.0\nEOR")
    image = build_image(big)
    with pytest.raises(CommError, match="16 entradas"):
        c.download(image)
    c.request(Cmd.LOAD_BEGIN, struct.pack("<II", len(image), crc32(image)))
    c.request(Cmd.LOAD_CHUNK, struct.pack("<I", 0) + image)
    with pytest.raises(DeviceError) as e:
        c.request(Cmd.LOAD_END)
    assert e.value.code == ProtoError.INCOMPATIBLE


def test_watchdog_fault_and_clear(device):
    c = device("--watchdog-us", "0")
    c.download(demo_image())
    c.set_mode(True)
    time.sleep(0.1)
    st = c.status()
    assert st.state == DevState.FAULT and st.fault == Fault.SCAN_TIMEOUT
    assert c.read_vars().q_commanded == 0
    with pytest.raises(DeviceError) as e:
        c.set_mode(True)
    assert e.value.code == ProtoError.FAULT_ACTIVE
    assert c.clear_fault() == DevState.STOP


def test_corrupted_flash_boots_in_fault(device):
    c = device()
    c.download(demo_image())
    c.transport.kill()
    data = bytearray(device.storage.read_bytes())
    data[40] ^= 0xFF
    device.storage.write_bytes(bytes(data))
    c2 = device()
    st = c2.status()
    assert st.state == DevState.FAULT and st.fault == Fault.PROGRAM_CORRUPT and not st.has_program


def test_autorun(device):
    c = device()
    c.download(demo_image())
    c.transport.kill()
    c2 = device("--autorun")
    assert c2.status().state == DevState.RUN


def test_device_disconnected_raises(device):
    c = device()
    c.transport.kill()
    with pytest.raises(CommError):
        c.status()


def test_unknown_command_and_bad_length(device):
    c = device()
    with pytest.raises(DeviceError) as e:
        c.request(0x55)
    assert e.value.code == ProtoError.UNKNOWN_COMMAND
    with pytest.raises(DeviceError) as e:
        c.request(Cmd.SET_MODE, b"\x01\x02")
    assert e.value.code == ProtoError.BAD_LENGTH


def test_write_marker(device):
    c = device()
    c.download(build_image(assemble(".markers 8\nSOR\nXIC M0.3\nOTE Q0.2\nEOR")))
    c.set_mode(True)
    c.write_marker(3, True)
    snap = wait_scans(c)
    assert snap.markers[3] and snap.q_logical & 0b100
    with pytest.raises(DeviceError):
        c.write_marker(99, True)


# ------------------------------------------------ equivalencia no dispositivo
def test_all_vectors_on_virtual_device(device):
    c = device()
    for case in load_scan_vectors(VECTORS / "scan"):
        result = run_vector_on_device(c, case)
        assert result.ok, (case["name"], result.mismatches[:1])
