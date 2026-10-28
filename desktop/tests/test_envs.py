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
    assert {"silo", "semaforo", "portao", "elevador", "garrafas", "compressores", "misturador"} <= ids
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


# ---------------------------------------------------------------- fisica realista
def test_physics_helpers():
    from ladderide.envs.physics import IDM, DelayLine, approach, torricelli
    assert approach(0, 10, 5, 1, 1.0) == 5 and approach(10, 0, 5, 1, 1.0) == 9
    assert torricelli(0.25) == 0.5
    line = DelayLine(0.3)
    line.push(2.0)
    assert line.advance(0.2) == 0 and line.in_flight == 2.0 and line.advance(0.1) == 2.0
    idm = IDM()
    assert idm.accel(0, None) == pytest.approx(idm.a)              # parte com aceleracao maxima
    assert idm.accel(idm.v0, 5.0, idm.v0) < -idm.b                  # obstaculo perto: freia forte


def test_silo_inertia_transport_delay_and_torricelli():
    from ladderide.envs.builtin import silo as s
    env = create("silo")
    run = {"MOTOR": True, "VALVE": False, "RUN": True, "FILL": False, "FULL": False}
    for _ in range(100):
        env.step(10, run)
    assert env.belt_v == pytest.approx(s.BELT_SPEED)
    x0 = env.boxes[0].x
    stop = dict(run, MOTOR=False)
    steps = 0
    while env.belt_v > 0:
        env.step(10, stop)
        steps += 1
    assert 3.0 < env.boxes[0].x - x0 < 6.0 and steps > 10           # inercia: anda ~4,5 px depois de desligar
    env.reset()
    env.silo = s.SILO_CAPACITY
    for _ in range(100):
        env.step(10, dict(stop, VALVE=True))
    full_rate = env.spilled
    env.reset()
    env.silo = 0.25 * s.SILO_CAPACITY
    for _ in range(100):
        env.step(10, dict(stop, VALVE=True))
    assert env.spilled == pytest.approx(full_rate * 0.5, rel=0.15)  # Q ~ sqrt(nivel)
    env.reset()
    env.step(10, dict(stop, VALVE=True))
    for _ in range(20):
        env.step(10, stop)                                          # valvula ja fechada...
    assert env.falling.in_flight > 0 or env.spilled > 0             # ...mas o produto ainda cai


def test_silo_example_overfills_slightly_but_within_tolerance():
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "silo.ladproj"), [(100, "START", True), (200, "START", False)],
                                 120000)
    assert alarms == set() and env.shipped_full >= 10
    assert 100 <= env.last_fill <= 110                               # produto em queda passa um pouco do nivel


def test_traffic_cars_accelerate_and_example_has_no_red_runners():
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "semaforo.ladproj"), [], 120000)
    assert alarms == set() and env.red_runners == 0 and env.hits == 0
    car = next(iter(env.cars["NS"] + env.cars["LO"]), None)
    assert car is None or car.v <= 14.0                             # nunca acima de ~50 km/h


def test_traffic_without_yellow_and_all_red_causes_collision():
    p = Project.load(EXAMPLES / "semaforo.ladproj")
    for rung in p.rungs:                                             # amarelo e vermelho geral -> 0,1 s
        for out in rung.outputs:
            if getattr(out, "operand", "").startswith(("Fase_Todos_Vermelho", "Fase_NS_Amarelo",
                                                         "Fase_LO_Amarelo")):
                out.preset = 100
    _, alarms, _ = closed_loop(p, [], 180000)
    assert any("colisao" in a for a in alarms)


def test_gate_overrun_hysteresis_and_reversal_alarm():
    from ladderide.envs.builtin import portao as g
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "portao.ladproj"), [(100, "OPEN", True), (200, "OPEN", False)],
                                 12000)
    assert g.LS1_ON <= env.pos < 100 and env.v == 0 and alarms == set()   # para com ~1,5% de inercia
    # exemplo: veiculo durante o fechamento -> para, espera e reabre sem reversao brusca
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "portao.ladproj"),
                                 [(100, "OPEN", True), (200, "OPEN", False), (10000, "CLOSE", True),
                                  (10100, "CLOSE", False), (12000, "VEHICLE", True)], 24000)
    assert env.sensors()["LS1"] and env.reversals == 0 and not env.hit_vehicle and alarms == set()
    # logica ingenua: fotocelula manda subir direto -> reversao com o portao em movimento
    naive = Project.load(EXAMPLES / "portao.ladproj")
    naive.rungs[0].condition[0].branches[2] = [Contact("XIC", "Fotocelula")]
    _, alarms, _ = closed_loop(naive, [(100, "OPEN", True), (200, "OPEN", False), (10000, "CLOSE", True),
                                       (10100, "CLOSE", False), (12000, "VEHICLE", True)], 16000)
    assert any("reversao" in a for a in alarms)


# ------------------------------------------------------------ elevador
def _press(t, key):
    return [(t, key, True), (t + 200, key, False)]


def test_elevator_example_serves_calls_with_door_closed_while_moving():
    actions = _press(500, "CALL3") + _press(2000, "CALL2") + _press(30000, "CALL1") + _press(31000, "CALL4")
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "elevador.ladproj"), actions, 90000)
    assert alarms == set()
    assert len(env.waits) == 4 and not env.pending
    assert abs(env.y - 3 * 3.0) < 0.10                       # parou no 4o andar, dentro da zona de porta
    assert env.last_level_cm is not None and abs(env.last_level_cm) < 6


def test_elevator_without_floor_stop_hits_buffer_and_moving_open_door_is_detected():
    from ladderide.model import Parallel
    runaway = Project(environment="elevador", rungs=[
        Rung([Parallel([[Contact("XIC", "I0.3")], [Contact("XIC", "Q0.0")]])], [Coil("OTE", "Q0.0")]),
        Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.2")])])
    env, alarms, _ = closed_loop(runaway, _press(100, "CALL1") + _press(300, "CALL4"), 25000)
    assert any("para-choque" in a for a in alarms)
    assert any("porta aberta" in a for a in alarms)


# ------------------------------------------------------------ garrafas
def test_bottle_line_example_fills_inspects_and_boxes_both_sizes():
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "garrafas.ladproj"), _press(100, "START"), 60000)
    assert alarms == set() and env.boxes_shipped >= 1 and env.packed_small >= 12 and env.scrap == 0
    big = [(100, "LARGE", True), (150, "LARGE", False)] + _press(300, "START")
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "garrafas.ladproj"), big, 90000)
    assert alarms == set() and env.packed_large >= 6 and env.packed_small == 0


def test_bottle_line_rejects_wrong_fill_and_detects_bad_logic():
    project = Project.load(EXAMPLES / "garrafas.ladproj")
    timer = next(o for r in project.rungs for o in r.outputs if getattr(o, "operand", "") == "Tempo_Pequena")
    timer.preset = 1600                                      # 0,4 L em garrafa de 0,5 L: 80%
    env, alarms, _ = closed_loop(project, _press(100, "START"), 40000)
    assert env.scrap >= 3 and env.bad_packed == 0 and alarms == set()
    naive = Project(environment="garrafas", rungs=[
        Rung([Contact("XIC", "I0.1")], [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.1")])])
    env, alarms, _ = closed_loop(naive, (), 30000)
    assert any("derramados" in a for a in alarms) and any("6 garrafas" in a or "quebraram" in a for a in alarms)


# -------------------------------------------------------- compressores
def test_compressor_example_alternates_lead_and_keeps_pressure():
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "compressores.ladproj"), _press(100, "START"), 180000)
    assert alarms == set()
    assert env.run_ms[0] > 30000 and env.run_ms[1] > 30000      # desgaste dividido entre os dois
    assert 85 <= env.psi <= 125


def test_compressor_takes_over_when_thermal_trips_and_naive_logic_alarms():
    project = Project.load(EXAMPLES / "compressores.ladproj")
    env, alarms, _ = closed_loop(project, _press(100, "START") + [(20000, "FAULT1", True)], 120000)
    assert env.forced[0] and env.psi >= 85 and not any("60 psi" in a for a in alarms)
    naive = Project(environment="compressores", rungs=[
        Rung([Contact("XIC", "I0.1")], [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.1")])])
    env, alarms, _ = closed_loop(naive, (), 120000)
    assert any("simultanea" in a for a in alarms) and any("seguranca" in a for a in alarms)
    assert any("condensado" in a for a in alarms)


# ----------------------------------------------------------- misturador
def test_batch_mixer_example_makes_good_batches():
    env, alarms, _ = closed_loop(Project.load(EXAMPLES / "misturador.ladproj"), _press(100, "START"), 120000)
    assert alarms == set() and env.good >= 2 and not env.bad


def test_batch_mixer_detects_dry_heating_unstirred_and_overflow():
    naive = Project(environment="misturador", rungs=[
        Rung([Contact("XIC", "I0.1")], [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.4")])])
    env, alarms, _ = closed_loop(naive, (), 40000)
    assert any("abaixo do nível" in a for a in alarms)
    assert any("sem o misturador" in a for a in alarms)
    assert any("transbordou" in a for a in alarms)


def test_io_simulator_follows_the_controller_and_switch_types():
    from ladderide.envs.builtin.simulador_es import bcd_digits, bcd_encode
    env = create("simulador_es")
    assert env.configure(16, 12, 64) and (len(env.inputs), len(env.outputs)) == (16, 12)
    assert env.inputs[15].address == "I1.7" and env.outputs[11].address == "Q1.3"
    assert not env.configure(16, 12, 64)                       # nada mudou
    plant = EnvironmentPlant(env)
    assert plant.owned_inputs == 0xFFFF
    assert env.types[3] == "pb_nc" and plant.input_values()["I3"]       # pulsador NF solto le 1
    env.press("I0", True)
    assert plant.input_values()["I0"]
    env.press("I0", False)
    assert not plant.input_values()["I0"]                     # pulsador volta sozinho
    env.press("T0", True)
    env.press("T0", False)                                    # etiqueta: pulsador NA -> pulsador NF
    assert env.types[0] == "pb_nc" and env.inputs[0].normally_closed
    env.press("T0", True)                                     # -> chave NA (com trava)
    env.press("I0", True)
    env.press("I0", False)
    assert plant.input_values()["I0"]
    env.configure(4, 2, 1)                                    # controlador menor: menos pontos, sem BCD
    assert (len(env.inputs), len(env.outputs), env.has_bcd, env.input_words()) == (4, 2, False, {})
    assert bcd_encode(1234) == 0x1234 and bcd_digits(0x0A07) == [0, 10, 0, 7]


def test_io_simulator_example_runs_bcd_through_frd_and_tod():
    project = Project.load(EXAMPLES / "simulador_es.ladproj")
    actions = [(0, "D0+", True), (0, "D3-", True), (100, "I2", True)]   # thumbwheel 1009 e botoeira 02
    env, alarms, sim = closed_loop(project, actions, total_ms=300)
    assert not alarms and env.thumbwheel == 1009
    assert sim.vm.n[0] == 0x1009 and sim.vm.n[2] == 1009 and env.display_word == 0x1009
    assert env.out["Q2"] and not env.out["Q0"]
