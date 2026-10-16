"""Os exemplos versionados compilam e se comportam como documentado."""
from __future__ import annotations

import pytest

from conftest import ROOT
from ladderide.compiler import compile_project
from ladderide.model import Project
from ladderide.sim import Simulator

EXAMPLES = sorted((ROOT / "examples").rglob("*.ladproj"))


@pytest.mark.parametrize("path", EXAMPLES, ids=[p.stem for p in EXAMPLES])
def test_example_compiles_without_warnings(path):
    r = compile_project(Project.load(path))
    assert r.ok and not r.warnings, [str(d) for d in r.diagnostics]
    lil = path.with_suffix(".lil")
    assert lil.exists() and r.lil.splitlines()[1:] == lil.read_text(encoding="utf-8").splitlines()[1:]


def run(sim: Simulator, ms: int) -> None:
    for _ in range(ms // sim.period_ms):
        sim.scan_once()


def test_relay_chase_lights_one_relay_per_second():
    sim = Simulator(compile_project(Project.load(ROOT / "examples/hardware/teste_reles.ladproj")))
    sim.set_input(0, True)
    seen = []
    for second in range(9):
        run(sim, 500)                   # meio de cada janela de 1 s
        seen.append(sim.vm.outputs)
        run(sim, 500)
    assert seen[:8] == [1 << k for k in range(8)]
    assert seen[8] == 1                 # ciclo reinicia
    sim.set_input(0, False)
    run(sim, 100)
    assert sim.vm.outputs == 0


def test_input_mirror():
    sim = Simulator(compile_project(Project.load(ROOT / "examples/hardware/espelho_entradas.ladproj")))
    for k in range(8):
        sim.inputs = 1 << k
        sim.scan_once()
        assert sim.vm.outputs == 1 << k


def test_demo_scenario():
    """Roteiro da demonstracao (docs/demo-script.md), passos 8-9, no simulador."""
    sim = Simulator(compile_project(Project.load(ROOT / "examples/demo/demonstracao.ladproj")))
    q = lambda k: bool(sim.vm.outputs >> k & 1)  # noqa: E731
    sim.set_input(0, True)
    run(sim, 50)
    sim.set_input(0, False)
    assert q(0) and q(2) and not q(1)          # motor e ventilador ligados, TON contando
    run(sim, 2000)
    assert q(1)                                # 2 s depois: em regime
    for _ in range(5):                         # 5 pecas
        sim.set_input(2, True)
        run(sim, 50)
        sim.set_input(2, False)
        run(sim, 50)
    assert q(3)                                # lote completo
    sim.set_input(1, True)                     # parada
    run(sim, 50)
    sim.set_input(1, False)
    assert not q(0) and q(2)                   # ventilador continua (TOF)
    run(sim, 3000)
    assert not q(2)
    sim.set_input(3, True)                     # zera contagem
    run(sim, 20)
    assert not q(3)
