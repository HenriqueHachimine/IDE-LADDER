"""Ambientes de simulacao: registro, plugins externos e malha fechada com os programas exemplo."""
from __future__ import annotations

import os
import textwrap

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from conftest import ROOT  # noqa: E402
from ladderide.compiler import compile_project  # noqa: E402
from ladderide.envs import EnvironmentPlant, available, create, discover, get  # noqa: E402
from ladderide.envs import registry  # noqa: E402
from ladderide.model import Coil, Contact, Project, Rung  # noqa: E402
from ladderide.sim.simulator import Simulator  # noqa: E402

EXAMPLES = ROOT / "examples" / "ambientes"


def closed_loop(project: Project, actions=(), total_ms=60000, env_id=None):
    """Executa o programa ligado ao ambiente; actions = [(t_ms, controle, pressionado)]."""
    result = compile_project(project)
    assert result.ok, result.errors
    env = create(env_id or project.environment)
    sim = Simulator(result, 10)
    sim.attach_plant(EnvironmentPlant(env))
    sim.start()
    alarms: set[str] = set()
    for t in range(0, total_ms, 10):
        for at, key, down in actions:
            if at == t:
                env.press(key, down)
        sim.scan_once()
        alarms.update(env.alarms())
    return env, alarms, sim


def test_builtin_environments_are_registered_with_valid_io():
    ids = {cls.id for cls in available()}
    assert {"silo", "semaforo", "portao"} <= ids
    for cls in available():
        env = cls()
        plant = EnvironmentPlant(env)          # enderecos validos (I/Q) e sem bits repetidos
        assert len(set(plant.in_bits.values())) == len(env.inputs)
        assert len(set(plant.out_bits.values())) == len(env.outputs)
        assert (EXAMPLES.parent / cls.example).exists()


def test_user_plugin_is_discovered_without_changing_the_ide(tmp_path):
    (tmp_path / "lampada.py").write_text(textwrap.dedent('''
        from ladderide.envs import Environment, IOPoint, register, BUTTON

        @register
        class Lampada(Environment):
            id = "teste_lampada"
            name = "Lampada de teste"
            inputs = [IOPoint("B", "I0.0", "Botao", kind=BUTTON)]
            outputs = [IOPoint("L", "Q0.0", "Lampada")]
            def reset(self): self.on_ms = 0
            def step(self, dt, out): self.on_ms += dt if out["L"] else 0
            def sensors(self): return {}
            def paint(self, p): pass
    '''), encoding="utf-8")
    (tmp_path / "quebrado.py").write_text("raise RuntimeError('plugin com defeito')", encoding="utf-8")
    discover(extra_dirs=[tmp_path])
    assert get("teste_lampada") is not None
    assert any("quebrado.py" in e for e in registry.load_errors)   # erro relatado, IDE continua
    p = Project(rungs=[Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")])])
    env, alarms, _ = closed_loop(p, [(100, "B", True), (600, "B", False)], 1000, env_id="teste_lampada")
    assert 490 <= env.on_ms <= 510


def test_silo_example_fills_boxes_without_spilling():
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "silo.ladproj"), [(100, "START", True), (200, "START", False)])
    assert env.shipped_full >= 5 and env.shipped_partial == 0
    assert alarms == set()


def test_silo_stop_is_normally_closed_and_bad_logic_spills():
    p = Project.load(EXAMPLES / "silo.ladproj")
    env, _, sim = closed_loop(p, [(100, "START", True), (200, "START", False), (3000, "STOP", True),
                                  (3100, "STOP", False)], 5000)
    assert not sim.vm.outputs & 0b1                     # STOP (NF) desligou a esteira
    bad = Project(environment="silo", rungs=[Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Q0.1")])])
    _, alarms, _ = closed_loop(bad, total_ms=3000)
    assert any("derramado" in a for a in alarms)


def test_traffic_light_example_is_safe_and_serves_pedestrians():
    actions = [(3000, "PED_NS", True), (3100, "PED_NS", False), (5000, "PED_LO", True), (5100, "PED_LO", False)]
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "semaforo.ladproj"), actions, 60000)
    assert alarms == set()
    assert env.passed["NS"] > 5 and env.passed["LO"] > 5
    assert not env.waiting_ped["NS"] and not env.waiting_ped["LO"]


def test_traffic_light_detects_simultaneous_greens():
    bad = Project(environment="semaforo", rungs=[
        Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Q0.2"), Coil("OTE", "Q0.6")])])
    _, alarms, _ = closed_loop(bad, total_ms=20000)
    assert any("ao mesmo tempo" in a for a in alarms)
    assert any("colisao" in a for a in alarms)


def test_garage_door_cycles_and_reopens_for_vehicle():
    p = Project.load(EXAMPLES / "portao.ladproj")
    env, alarms, _ = closed_loop(p, [(100, "OPEN", True), (200, "OPEN", False), (10000, "CLOSE", True),
                                     (10100, "CLOSE", False)], 20000)
    assert env.cycles == 1 and env.sensors()["LS2"] and alarms == set()
    env, alarms, _ = closed_loop(p, [(100, "OPEN", True), (200, "OPEN", False), (10000, "CLOSE", True),
                                     (10100, "CLOSE", False), (12000, "VEHICLE", True)], 22000)
    assert env.sensors()["LS1"] and not env.hit_vehicle and alarms == set()


def test_garage_door_without_interlock_raises_alarm():
    bad = Project(environment="portao", rungs=[Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Q0.0"),
                                                                              Coil("OTE", "Q0.1")])])
    _, alarms, _ = closed_loop(bad, total_ms=500)
    assert any("subir e descer" in a for a in alarms)


def test_environment_inputs_override_panel_only_for_owned_bits():
    p = Project.load(EXAMPLES / "portao.ladproj")
    result = compile_project(p)
    sim = Simulator(result, 10)
    sim.attach_plant(EnvironmentPlant(create("portao")))
    sim.set_input(7, True)                      # I0.7 nao pertence ao ambiente
    sim.set_input(4, False)                     # I0.4 (LS2) pertence: o processo decide
    eff = sim.effective_inputs()
    assert eff >> 7 & 1 and eff >> 4 & 1        # portao fechado -> LS2 = 1
    assert eff >> 2 & 1                         # PARAR e NF: le 1 quando solto


def test_paint_runs_for_every_environment():
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    for cls in available():
        env = cls()
        img = QImage(*env.size, QImage.Format_ARGB32)
        p = QPainter(img)
        env.paint(p)
        p.end()
