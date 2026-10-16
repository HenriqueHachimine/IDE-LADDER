"""Equivalencia simulador x dispositivo: executa vetores no dispositivo (TEST_SCAN).

O dispositivo roda a VM do firmware com as mesmas entradas e o mesmo dt que a
VM do Desktop; os estados completos sao comparados varredura a varredura
(tolerancia zero). As saidas fisicas permanecem no estado seguro (STOP).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..core import LadderVM, assemble, build_image, decode
from ..core.asm import parse_operand
from .client import DeviceClient


@dataclass
class VectorResult:
    name: str
    scans: int
    mismatches: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.mismatches


def expand_steps(steps: list[dict]) -> list[tuple[int, int]]:
    inputs, scans = 0, []
    for step in steps:
        for name, value in step.get("inputs", {}).items():
            _, index = parse_operand(name)
            inputs = inputs | (1 << index) if value else inputs & ~(1 << index)
        scans += [(step.get("dt", 10), inputs)] * step.get("repeat", 1)
    return scans


def load_scan_vectors(directory: Path) -> list[dict]:
    cases = []
    for path in sorted(Path(directory).glob("*.json")):
        cases += json.loads(path.read_text(encoding="utf-8"))
    return cases


def run_vector_on_device(client: DeviceClient, case: dict) -> VectorResult:
    image = build_image(assemble("\n".join(case["program"])))
    client.download(image, stop_if_running=True)
    client.test_begin()
    vm = LadderVM(decode(image))
    scans = expand_steps(case["steps"])
    result = VectorResult(case["name"], len(scans))
    for n, (dt, inputs) in enumerate(scans, start=1):
        vm.scan(inputs, dt)
        device = client.test_scan(inputs, dt).dump_line()
        expected = vm.dump_line()
        if device != expected:
            result.mismatches.append((n, expected, device))
    return result
