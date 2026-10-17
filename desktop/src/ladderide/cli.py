"""Ferramenta de linha de comando (testes de hardware, evidencias, automacao).

    python -m ladderide.cli ports
    python -m ladderide.cli compile projeto.ladproj [-o saida.ldrb] [--lil saida.lil]
    python -m ladderide.cli cpp projeto.ladproj [-o programa.cpp]
    python -m ladderide.cli --port COM5 info|status|run|stop|clear-fault
    python -m ladderide.cli --port COM5 download projeto.ladproj [--stop]
    python -m ladderide.cli --port COM5 monitor [--interval 0.2] [--count N]
    python -m ladderide.cli --port COM5 equivalence [--vectors shared/test-vectors/scan]
    (no Linux a porta e /dev/ttyUSB0 ou /dev/ttyACM0; use --virtual para o dispositivo virtual)
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from .comm import CommError, DeviceClient, DeviceError, SerialTransport, TcpTransport, list_serial_ports
from .comm.equivalence import load_scan_vectors, run_vector_on_device
from .comm.protocol import FAULT_TEXT
from .comm.virtual import ROOT, start_virtual_device, virtual_storage_path
from .compiler import compile_project
from .model import Project


def _client(args) -> DeviceClient:
    if args.virtual:
        storage = Path(args.virtual_storage) if args.virtual_storage else virtual_storage_path()
        storage.parent.mkdir(parents=True, exist_ok=True)
        return DeviceClient(start_virtual_device(storage), timeout=0.5)
    if args.host:
        return DeviceClient(TcpTransport(args.host, args.tcp_port))
    if not args.port:
        raise SystemExit("informe --port COMx, --host ou --virtual")
    return DeviceClient(SerialTransport(args.port, args.baud))


def _compile(path: str):
    project = Project.load(path)
    result = compile_project(project)
    for d in result.diagnostics:
        print(f"  {d}")
    if not result.ok:
        raise SystemExit("compilacao falhou")
    return project, result


def _bits(mask: int, n: int) -> str:
    return " ".join("1" if mask >> k & 1 else "0" for k in range(n))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ladderide.cli", description="Ferramentas do CLP LADDER ESP32")
    ap.add_argument("--port", help="porta serial (ex.: COM5 no Windows, /dev/ttyUSB0 no Linux)")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--host", help="endereco TCP do dispositivo")
    ap.add_argument("--tcp-port", type=int, default=5020)
    ap.add_argument("--virtual", action="store_true", help="usa o dispositivo virtual (PC)")
    ap.add_argument("--virtual-storage", default=None, help="arquivo da flash virtual")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports")
    c = sub.add_parser("compile")
    c.add_argument("project")
    c.add_argument("-o", "--output")
    c.add_argument("--lil")
    for name in ("info", "status", "run", "stop", "clear-fault"):
        sub.add_parser(name)
    d = sub.add_parser("download")
    d.add_argument("project")
    d.add_argument("--stop", action="store_true", help="coloca em STOP se estiver em RUN")
    m = sub.add_parser("monitor")
    m.add_argument("--interval", type=float, default=0.2)
    m.add_argument("--count", type=int, default=0)
    v = sub.add_parser("verify", help="verifica o programa para o ESP32 (VM C do firmware, limites da placa)")
    v.add_argument("project")
    v.add_argument("--scans", type=int, default=400, help="varreduras comparadas simulador x firmware")
    il = sub.add_parser("il", help="converte o diagrama em blocos de instrucao (lista IL por rede)")
    il.add_argument("project")
    il.add_argument("-o", "--output")
    cp = sub.add_parser("cpp", help="traduz o diagrama para C++ (nao precisa compilar)")
    cp.add_argument("project")
    cp.add_argument("-o", "--output")
    e = sub.add_parser("equivalence")
    e.add_argument("--vectors", default=str(ROOT / "shared" / "test-vectors" / "scan"))
    args = ap.parse_args(argv)

    if args.cmd == "ports":
        for dev, desc in list_serial_ports():
            print(f"{dev}\t{desc}")
        return 0
    if args.cmd == "compile":
        _, r = _compile(args.project)
        print(f"OK: {len(r.program.code)} instrucoes, {len(r.image)} bytes, build_id 0x{r.build_id:08x}")
        if args.output:
            Path(args.output).write_bytes(r.image)
        if args.lil:
            Path(args.lil).write_text(r.lil, encoding="utf-8")
        return 0
    if args.cmd == "cpp":
        from .codegen import generate_cpp
        code = generate_cpp(Project.load(args.project))
        if args.output:
            Path(args.output).write_text(code.text, encoding="utf-8")
        else:
            print(code.text, end="")
        if code.errors:
            print(f"{code.errors} erro(s) no diagrama (marcados com ERRO no codigo)", file=sys.stderr)
        return 1 if code.errors else 0
    if args.cmd in ("verify", "il"):
        from .verify import il_blocks, il_text, verify_for_esp32
        project, r = _compile(args.project)
        if args.cmd == "verify":
            report = verify_for_esp32(project, r, scans=args.scans)
            print(report.as_text())
            return 0 if report.ok else 1
        text = il_text(il_blocks(project, r), f"{project.name} (id 0x{r.build_id:08x})")
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0

    try:
        client = _client(args)
    except CommError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    try:
        return _device_command(client, args)
    except (CommError, DeviceError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    finally:
        client.close()


def _device_command(client: DeviceClient, args) -> int:
    if args.cmd == "info":
        i = client.info()
        print(f"firmware {i.firmware} | hardware {i.hardware} | protocolo {i.protocol} | "
              f"LDRB {i.fmt_major}.{i.fmt_minor} | E/S {i.n_inputs}/{i.n_outputs} | "
              f"varredura {i.scan_period_ms} ms | programa max {i.max_image} B")
    elif args.cmd == "status":
        s = client.status()
        print(f"estado {s.state.name} | falha {s.fault.name} ({FAULT_TEXT[s.fault]}) | programa "
              f"{'0x%08x' % s.build_id if s.has_program else 'nenhum'} | varreduras {s.scan_count} | "
              f"execucao {s.last_exec_us} us (max {s.max_exec_us}) | intervalo max {s.max_interval_us} us | "
              f"atrasos {s.overruns} | ligado ha {s.uptime_ms / 1000:.1f} s")
    elif args.cmd == "run":
        print(client.set_mode(True).name)
    elif args.cmd == "stop":
        print(client.set_mode(False).name)
    elif args.cmd == "clear-fault":
        print(client.clear_fault().name)
    elif args.cmd == "download":
        _, r = _compile(args.project)
        t0 = time.monotonic()
        res = client.download(r.image, stop_if_running=args.stop,
                              progress=lambda a, b: print(f"\r  {a}/{b} bytes", end="", flush=True))
        print(f"\nOK: {res.bytes_sent} bytes em {res.chunks} blocos, {res.retries} retransmissoes, "
              f"{time.monotonic() - t0:.2f} s; build_id 0x{res.build_id:08x}, CRC 0x{res.crc:08x}")
    elif args.cmd == "monitor":
        n = 0
        while args.count == 0 or n < args.count:
            s = client.read_vars()
            stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            timers = " ".join(f"T{k}={t.acc}{'*' if t.dn else ''}" for k, t in enumerate(s.timers))
            counters = " ".join(f"C{k}={c.acc}{'*' if c.dn else ''}" for k, c in enumerate(s.counters))
            print(f"{stamp} {s.state.name:<5} scan={s.scan_count:<8} I=[{_bits(s.inputs, 8)}] "
                  f"Q=[{_bits(s.q_logical, 8)}] cmd=[{_bits(s.q_commanded, 8)}] {timers} {counters}")
            n += 1
            time.sleep(args.interval)
    elif args.cmd == "equivalence":
        cases = load_scan_vectors(Path(args.vectors))
        failed = 0
        for case in cases:
            r = run_vector_on_device(client, case)
            print(f"{'OK  ' if r.ok else 'FALHA'} {r.name} ({r.scans} varreduras)")
            for n, exp, got in r.mismatches[:3]:
                print(f"     varredura {n}\n       esperado: {exp}\n       obtido:   {got}")
            failed += not r.ok
        print(f"{len(cases) - failed}/{len(cases)} vetores identicos ao simulador")
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
