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
from ladderide.envs.builtin.detector_gas import ALARM as ALARM_LEVEL  # noqa: E402
from ladderide.model import Coil, Contact, Parallel, Project, Rung, TimerBox  # noqa: E402
from ladderide.model.project import CompareBox  # noqa: E402
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


# ------------------------------------------------- ambientes com estilos de logica diferentes
def test_star_delta_reverses_after_motor_stops_and_detects_shorts():
    p = Project.load(EXAMPLES / "estrela_triangulo.ladproj")
    env, alarms, _ = closed_loop(p, [(100, "LIGA_H", True), (200, "LIGA_H", False)], 9000)
    assert alarms == set() and env.starts[1] == 1 and env.connection == "triangulo" and env.last_peak < 2.5
    rev = [(100, "LIGA_H", True), (200, "LIGA_H", False), (9000, "LIGA_A", True), (9100, "LIGA_A", False)]
    env, alarms, _ = closed_loop(p, rev, 30000)               # espera parar e parte no outro sentido
    assert alarms == set() and env.starts == {1: 1, -1: 1} and env.w < -0.9 and env.plugging == 0
    for fault in ("SOBRECARGA", "FALTA_FASE"):
        env, alarms, sim = closed_loop(p, [(100, "LIGA_H", True), (200, "LIGA_H", False), (9000, fault, True)], 30000)
        assert alarms == set() and sim.vm.outputs == 0b100000                   # so FALHA acesa
    def program(*rungs):
        return Project(environment="estrela_triangulo", rungs=list(rungs))
    reverse = [Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.0"), Coil("OTU", "Q0.1")]),
               Rung([Contact("XIC", "I0.1")], [Coil("OTL", "Q0.1"), Coil("OTU", "Q0.0")])]
    star = Rung([Parallel([[Contact("XIC", "Q0.0")], [Contact("XIC", "Q0.1")]])], [Coil("OTE", "Q0.2")])
    _, alarms, _ = closed_loop(program(*reverse, star), rev, 12000)        # sem tempo morto entre K1 e K4
    assert any("K1 e K4 fecharam juntos" in a for a in alarms)
    dead_time = [Rung([Contact("XIC", "I0.0")], [Coil("OTU", "Q0.1"), Coil("OTL", "M0.0")]),
                 Rung([Contact("XIC", "I0.1")], [Coil("OTU", "Q0.0"), Coil("OTL", "M0.1")]),
                 Rung([Contact("XIO", "Q0.0"), Contact("XIO", "Q0.1")], [TimerBox("TON", "T0", 200)]),
                 Rung([Contact("XIC", "M0.0"), Contact("XIC", "T0.DN")], [Coil("OTL", "Q0.0"), Coil("OTU", "M0.0")]),
                 Rung([Contact("XIC", "M0.1"), Contact("XIC", "T0.DN")], [Coil("OTL", "Q0.1"), Coil("OTU", "M0.1")])]
    _, alarms, _ = closed_loop(program(*dead_time, star), rev, 12000)      # nao espera o motor parar
    assert any("Reversão com o motor girando" in a for a in alarms)
    assert not any("CURTO" in a for a in alarms)
    same_scan = program(Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.0"), Coil("OTL", "Q0.2")]),
                        Rung([Contact("XIC", "I0.5")], [Coil("OTU", "Q0.2"), Coil("OTL", "Q0.3")]))
    _, alarms, _ = closed_loop(same_scan, [(100, "LIGA_H", True), (200, "LIGA_H", False)], 6000)
    assert any("K2 (estrela) e K3" in a for a in alarms)


def test_two_hand_press_needs_simultaneous_hands_and_release():
    p = Project.load(EXAMPLES / "prensa.ladproj")
    actions = [(100, "AMBAS", True), (5000, "AMBAS", True), (6000, "AMBAS", True),   # golpe, solta, golpe
               (11000, "ESQ", True), (11800, "DIR", True)]                          # 800 ms: recusado
    env, alarms, _ = closed_loop(p, actions, 16000)
    assert env.strokes == 2 and alarms == set()
    env, alarms, _ = closed_loop(p, [(100, "AMBAS", True), (1200, "MAO", True)], 4000)   # mao no meio do golpe
    assert env.strokes == 0 and env.pos < 5 and alarms == set()                        # voltou antes de chegar
    one_hand = Project(environment="prensa", rungs=[Rung([Contact("XIC", "I0.0")],
                                                         [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.4")])])
    _, alarms, _ = closed_loop(one_hand, [(100, "ESQ", True), (200, "MAO", True)], 3000)
    assert any("sem as duas" in a for a in alarms) and any("PERIGO" in a for a in alarms)


def test_press_monitors_stuck_valve_lubricates_and_slows_in_setup_mode():
    p = Project.load(EXAMPLES / "prensa.ladproj")
    strokes = [a for k in range(25) for a in ((100 + k * 6000, "AMBAS", True), (4600 + k * 6000, "AMBAS", True))]
    env, alarms, _ = closed_loop(p, strokes, 151000)
    assert env.strokes == 25 and env.lube_total == 1 and alarms == set()
    stuck = [(100, "AMBAS", True), (4600, "AMBAS", True), (6000, "TRAVADA", True), (7000, "AMBAS", True),
             (9000, "AMBAS", True), (10000, "TRAVADA", True), (11000, "EMERG", True), (11500, "EMERG", True),
             (12000, "AMBAS", True), (16500, "AMBAS", True)]
    env, alarms, sim = closed_loop(p, stuck, 18000)    # travada: bloqueia; depois do rearme volta a golpear
    assert env.strokes == 2 and env.uncommanded == 0 and alarms == set()
    env, alarms, _ = closed_loop(p, [(50, "AJUSTE", True), (100, "AMBAS", True)], 12000)
    assert env.strokes == 1 and alarms == set()
    naive = Project(environment="prensa", rungs=[
        Rung([Contact("XIC", "I0.0"), Contact("XIC", "I0.1"), Contact("XIO", "I0.4")], [Coil("OTE", "Q0.0")]),
        Rung([Contact("XIC", "I0.5")], [Coil("OTE", "Q0.4")]),                      # seguranca sempre ligada
        Rung([Contact("XIC", "I0.4"), Contact("XIO", "I0.0")], [Coil("OTL", "Q0.1")]),
        Rung([Contact("XIC", "I0.3")], [Coil("OTU", "Q0.1")])])
    _, alarms, _ = closed_loop(naive, [(100, "AMBAS", True), (4000, "AMBAS", True), (8000, "TRAVADA", True)], 12000)
    assert any("desceu sem comando" in a for a in alarms) and any("sem a lâmpada FALHA" in a for a in alarms)


def test_drill_sequence_makes_good_parts_and_breaks_bit_without_spindle():
    p = Project.load(EXAMPLES / "furadeira.ladproj")
    env, alarms, _ = closed_loop(p, [(100, "PARTIDA", True), (200, "PARTIDA", False), (12000, "PARTIDA", True),
                                     (12100, "PARTIDA", False)], 24000)
    assert env.good == 2 and env.defects == 0 and alarms == set()
    bad = Project(environment="furadeira", rungs=[Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.1")])])
    _, alarms, _ = closed_loop(bad, [(100, "PARTIDA", True), (200, "PARTIDA", False)], 3000)
    assert any("mandril parado" in a for a in alarms)
    no_peck = Project(environment="furadeira", rungs=[
        Rung([Contact("XIC", "I0.0")], [Coil("OTL", "Q0.0"), Coil("OTL", "Q0.3"), Coil("OTL", "Q0.6")]),
        Rung([Contact("XIC", "I0.3")], [Coil("OTE", "Q0.1")])])
    _, alarms, _ = closed_loop(no_peck, [(100, "PARTIDA", True), (200, "PARTIDA", False)], 5000)
    assert any("cavaco entupiu" in a for a in alarms)


def test_drill_counts_tool_life_and_resets_on_new_bit():
    p = Project.load(EXAMPLES / "furadeira.ladproj")
    acts = [a for k in range(27) for a in ((100 + k * 13000, "PARTIDA", True), (200 + k * 13000, "PARTIDA", False))]
    t = 100 + 27 * 13000
    acts += [(t, "EMERG", True), (t + 200, "TROCAR_BROCA", True), (t + 400, "EMERG", True),
             (t + 1000, "PARTIDA", True), (t + 1100, "PARTIDA", False)]
    env, alarms, sim = closed_loop(p, acts, t + 14000)
    assert env.good == 26 and env.defects == 0 and env.tool_no == 2 and alarms == set()   # 25, troca, mais 1
    assert sim.vm.n[3] == 2
    dry = Project.load(EXAMPLES / "furadeira.ladproj")                     # sem fluido de corte
    dry.rungs = [r for r in dry.rungs if not any(getattr(c, "operand", "") == "Refrigeracao" for c in r.outputs)]
    acts = [a for k in range(12) for a in ((100 + k * 13000, "PARTIDA", True), (200 + k * 13000, "PARTIDA", False))]
    env, alarms, _ = closed_loop(dry, acts, 12 * 13000)
    assert any("broca cega" in a for a in alarms) and env.defects >= 1


def test_level_crossing_handles_both_directions_and_ignores_leaving_train():
    p = Project.load(EXAMPLES / "passagem_nivel.ladproj")
    env, alarms, _ = closed_loop(p, total_ms=200000)
    assert env.train_count >= 6 and alarms == set() and env.min_margin_s > 3 and env.cars_crossed > 20
    env, alarms, sim = closed_loop(p, [(0, "AUTO", True), (1000, "TREM_1O", True), (6000, "TREM_2L", True)], 60000)
    assert env.train_count == 2 and alarms == set()                     # dois trens: painel OUTRO TREM
    no_memory = Project(environment="passagem_nivel", rungs=[
        Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.1"), Coil("OTE", "Q0.3")])])
    _, alarms, _ = closed_loop(no_memory, total_ms=40000)
    assert any("piscar alternadas" in a for a in alarms) and any("3 s de aviso" in a for a in alarms)


def test_level_crossing_needs_both_tracks_and_the_other_train_sign():
    one_track = Project.load(EXAMPLES / "passagem_nivel.ladproj")        # so a logica da via 1
    one_track.rungs = [r for r in one_track.rungs if not any("_2" in getattr(n, "operand", "")
                                                              for n in r.condition + r.outputs)]
    _, alarms, _ = closed_loop(one_track, [(0, "AUTO", True), (1000, "TREM_2O", True)], 40000)
    assert any("cancela aberta" in a for a in alarms)
    no_sign = Project.load(EXAMPLES / "passagem_nivel.ladproj")
    no_sign.rungs = [r for r in no_sign.rungs if not any(getattr(c, "operand", "") == "Painel_Outro_Trem"
                                                         for c in r.outputs)]
    _, alarms, _ = closed_loop(no_sign, [(0, "AUTO", True), (1000, "TREM_1O", True), (6000, "TREM_2L", True)], 30000)
    assert any("OUTRO TREM" in a for a in alarms)


def test_parking_counts_cars_and_shows_free_spaces_in_n0():
    env, alarms, sim = closed_loop(Project.load(EXAMPLES / "estacionamento.ladproj"), total_ms=300000)
    assert alarms == set() and env.entered > 40 and env.gave_up > 0           # lotou e recusou carros
    assert env.ramp_up > 15 and env.ramp_down > 5 and env.searches == 0
    assert sim.vm.n[0] == 16 - env.inside == env.displayed["total"]
    no_count = Project(environment="estacionamento", rungs=[Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")])])
    _, alarms, _ = closed_loop(no_count, total_ms=40000)
    assert any("Contagem errada" in a for a in alarms)


def test_parking_ramp_direction_and_floor_full_sign():
    p = Project.load(EXAMPLES / "estacionamento.ladproj")
    no_ramp = Project.load(EXAMPLES / "estacionamento.ladproj")             # nao acompanha a rampa
    no_ramp.rungs = [r for r in no_ramp.rungs if not any("Rampa" in getattr(n, "operand", "") for n in r.condition)]
    _, alarms, _ = closed_loop(no_ramp, total_ms=150000)
    assert any("(N1)" in a or "(N2)" in a for a in alarms)
    no_sign = Project.load(EXAMPLES / "estacionamento.ladproj")
    no_sign.rungs = [r for r in no_sign.rungs if not any(getattr(c, "operand", "") == "Piso1_Lotado" for c in r.outputs)]
    env, alarms, _ = closed_loop(no_sign, total_ms=150000)
    assert env.searches > 0 and any("PISO 1 LOTADO" in a for a in alarms)


def test_sorter_shift_register_sends_each_part_to_its_bin():
    p = Project.load(EXAMPLES / "seletor_pecas.ladproj")
    env, alarms, _ = closed_loop(p, [(100, "LIGA", True)], 40000)
    assert alarms == set() and env.wrong == 0 and all(sum(env.bins[b].values()) > 5 for b in "ABCD")
    no_register = Project(environment="seletor_pecas", rungs=[
        Rung([Contact("XIC", "I0.0")], [Coil("OTE", "Q0.0")]), Rung([Contact("XIC", "I0.3")], [Coil("OTE", "Q0.1")])])
    _, alarms, _ = closed_loop(no_register, [(100, "LIGA", True)], 20000)
    assert any("destino errado" in a for a in alarms)


def test_sorter_bins_follow_the_operator_choice_and_stop_when_full():
    p = Project.load(EXAMPLES / "seletor_pecas.ladproj")
    for choice in ({"A": 1, "B": 1, "C": 4}, {"A": 4, "B": 0, "C": 3}, {"A": 0, "B": 0, "C": 0}):
        env = create("seletor_pecas")
        env.config = dict(choice)
        result = compile_project(p)
        sim = Simulator(result, 10)
        sim.attach_plant(EnvironmentPlant(env))
        sim.start()
        env.press("LIGA", True)
        for _ in range(3000):
            sim.scan_once()
        assert env.alarms() == [] and env.config == choice
        for b in "ABC":                                     # cada caixa so recebe o tipo escolhido
            assert all(n == 0 for k, n in env.bins[b].items() if k != choice[b])
    env, alarms, sim = closed_loop(p, [(100, "LIGA", True)], 40000)
    assert sim.vm.outputs >> 5 & 1 and not sim.vm.outputs & 1          # caixa cheia: TROCAR e esteira parada
    acts = [(100, "LIGA", True), (40000, "TROCADAS", True), (40100, "TROCADAS", False),
            (45000, "CFG_A", True), (45000, "CFG_A", False), (52000, "CFG_C", True), (52000, "CFG_C", False)]
    env, alarms, _ = closed_loop(p, acts, 70000)                      # troca o tipo com a esteira andando
    assert alarms == set() and env.swaps == 1 and env.config == {"A": 2, "B": 3, "C": 3}


def test_gas_detection_votes_two_of_three_and_needs_reset():
    p = Project.load(EXAMPLES / "detector_gas.ladproj")
    acts = [(2000, "VAZAMENTO_GRANDE", True), (10000, "RECONHECER", True), (10100, "RECONHECER", False),
            (12000, "VAZAMENTO_GRANDE", True), (20000, "REARMAR", True), (20100, "REARMAR", False),
            (60000, "REARMAR", True), (60100, "REARMAR", False)]
    env, alarms, sim = closed_loop(p, acts, 64000)                 # rearme cedo recusado; depois da purga reabre
    assert alarms == set() and env.trips == 1 and env.peak < 30 and sim.vm.outputs >> 1 & 1
    env, alarms, _ = closed_loop(p, [(2000, "VAZAMENTO", True)], 120000)   # pre-alarme segura o vazamento pequeno
    assert alarms == set() and env.trips == 0 and env.peak < ALARM_LEVEL
    env, alarms, sim = closed_loop(p, [(1000, "FALHA_D3", True)], 30000)    # descalibrado: sinaliza e produz
    assert alarms == set() and env.trips == 0 and sim.vm.outputs >> 4 & 1 and sim.vm.outputs >> 1 & 1
    env, alarms, _ = closed_loop(p, [(500, "FALHA_D2", True), (2000, "VAZAMENTO_GRANDE", True)], 15000)
    assert alarms == set() and env.trips == 1                       # 1 de 2 com os detectores bons
    auto_reopen = Project(environment="detector_gas", rungs=[Rung([CompareBox("LES", ["N0", "200"])],
                                                                  [Coil("OTE", "Q0.1")])])
    _, alarms, _ = closed_loop(auto_reopen, [(1000, "VAZAMENTO_GRANDE", True), (6000, "VAZAMENTO_GRANDE", True)],
                               40000)
    assert any("REARMAR" in a for a in alarms)


def test_gas_detection_strict_two_of_three_fails_with_a_dead_detector():
    strict = Project.load(EXAMPLES / "detector_gas.ladproj")      # sem degradar para 1 de 2
    strict.rungs = [r for r in strict.rungs if not any(getattr(o, "operands", ["", ""])[:2] == ["1", "Votos_Necessarios"]
                                                       for o in r.outputs)]
    _, alarms, _ = closed_loop(strict, [(500, "FALHA_D2", True), (2000, "VAZAMENTO_GRANDE", True)], 15000)
    assert any("mais de 25%" in a for a in alarms)
    no_purge = Project.load(EXAMPLES / "detector_gas.ladproj")
    for r in no_purge.rungs:
        r.condition = [n for n in r.condition if getattr(n, "operand", "") != "Purga.DN"]
    acts = [(2000, "VAZAMENTO_GRANDE", True), (12000, "VAZAMENTO_GRANDE", True), (20000, "REARMAR", True),
            (20100, "REARMAR", False)]
    _, alarms, _ = closed_loop(no_purge, acts, 24000)
    assert any("purga" in a for a in alarms)


def test_scale_doses_within_tolerance_with_adaptive_preact():
    p = Project.load(EXAMPLES / "balanca.ladproj")
    for key, (a, b) in (("R1", (400, 100)), ("R2", (250, 250)), ("R3", (800, 50))):
        env, alarms, sim = closed_loop(p, [(0, key, True), (100, "PARTIDA", True), (200, "PARTIDA", False)], 90000)
        assert alarms == set() and env.targets() == (a, b) and env.ok >= 5 and env.bad <= 1
        assert env.rejected_bad == env.bad and env.shipped_bad == 0                 # so o primeiro, rejeitado
        assert abs(env.last[0]) <= 0.02 * a and sim.vm.n[6] > 8                      # corte antecipado de A
    acts = [(100, "PARTIDA", True), (200, "PARTIDA", False), (30000, "R3", True), (60000, "R2", True)]
    env, alarms, _ = closed_loop(p, acts, 90000)                                    # troca de receita
    assert alarms == set() and env.ok >= 6
    spill = Project(environment="balanca", rungs=[Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.2")])])
    _, alarms, _ = closed_loop(spill, total_ms=5000)
    assert any("derramado" in a for a in alarms)


def test_scale_needs_tare_and_reject_station():
    no_tare = Project.load(EXAMPLES / "balanca.ladproj")
    for r in no_tare.rungs:
        for o in r.outputs:
            if getattr(o, "operands", None) == ["Peso", "Tara"]:
                o.operands = ["0", "Tara"]
    _, alarms, _ = closed_loop(no_tare, [(100, "PARTIDA", True), (200, "PARTIDA", False)], 60000)
    assert any("tara" in a for a in alarms)
    no_reject = Project.load(EXAMPLES / "balanca.ladproj")
    for r in no_reject.rungs:
        r.outputs = [c for c in r.outputs if getattr(c, "operand", "") != "Rejeitador"]
    _, alarms, _ = closed_loop(no_reject, [(100, "PARTIDA", True), (200, "PARTIDA", False)], 20000)
    assert any("expedição" in a for a in alarms)


def test_greenhouse_bands_keep_climate_for_days_with_rain_and_wind():
    env, alarms, sim = closed_loop(Project.load(EXAMPLES / "estufa.ladproj"), [(0, "AUTO", True)], 2 * 240000 + 5000)
    assert alarms == set() and env.in_band_ms > 0.65 * env.time_ms                # 2 dias, chuva e vento no 1o
    assert sim.vm.n[2] == env.hour and abs(sim.vm.n[0] - env.T * 10) <= 5
    assert 35 <= env.soil <= 65 and env.pump_ms > 0 and env.growth > 0.4           # irrigou e as plantas cresceram
    wasteful = Project(environment="estufa", rungs=[Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Q0.0"), Coil("OTE", "Q0.2")])])
    _, alarms, _ = closed_loop(wasteful, total_ms=120000)
    assert any("desperdício" in a for a in alarms) and any("chuva" in a for a in alarms)


def test_greenhouse_irrigation_respects_noon_and_dry_tank():
    always = Project(environment="estufa", rungs=[Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Q0.7")])])
    _, alarms, _ = closed_loop(always, total_ms=100000)
    assert any("sol forte" in a for a in alarms) and any("a seco" in a for a in alarms)


def test_overhead_crane_homes_counts_encoder_and_stops_at_stations():
    calls = [(15000, "CH3"), (30000, "CH5"), (45000, "CH1"), (60000, "CH4"), (75000, "CH2")]
    acts = [a for t, k in calls for a in ((t, k, True), (t + 200, k, False))]
    env, alarms, sim = closed_loop(Project.load(EXAMPLES / "ponte_rolante.ladproj"), acts, 90000)
    assert alarms == set() and env.arrivals == 5 and env.last_error <= 10       # dos dois sentidos
    assert abs(sim.vm.n[0] * 10 - env.x) <= 10                                   # contagem = posicao real
    runaway = Project(environment="ponte_rolante", rungs=[
        Rung([Contact("XIC", "I0.6")], [Coil("OTL", "Q0.0"), Coil("OTL", "Q0.3")]),
        Rung([Contact("XIC", "Q0.0")], [Coil("OTE", "Q0.4")])])
    _, alarms, _ = closed_loop(runaway, [(100, "CH5", True), (300, "CH5", False)], 15000)
    assert any("batente" in a for a in alarms) and any("andando" in a for a in alarms)


def test_vending_machine_charges_gives_change_and_refunds():
    p = Project.load(EXAMPLES / "venda.ladproj")
    buy = [(500, "C100", True), (700, "C100", True), (900, "C100", True), (3000, "BOT_A", True), (3100, "BOT_A", False)]
    env, alarms, sim = closed_loop(p, buy, 9000)                      # R$ 3,00 por uma lata de R$ 2,50
    assert alarms == set() and env.sales == 1 and env.returned == 50 and sim.vm.n[0] == 0
    sold_out = []
    for k in range(3):                                                # o suco tem 2 no estoque
        t = 500 + k * 8000
        sold_out += [(t + d, "C100", True) for d in (0, 200, 400, 600)] + [(t + 2500, "BOT_B", True),
                                                                          (t + 2600, "BOT_B", False)]
    env, alarms, sim = closed_loop(p, sold_out, 30000)
    assert alarms == set() and env.sales == 2 and env.stock["B"] == 0
    assert sim.vm.n[0] == env.inserted - env.returned - env.delivered > 0    # tubo vazio: o resto fica no credito
    no_stop = Project(environment="venda", rungs=[Rung([Contact("XIC", "I0.3")], [Coil("OTL", "Q0.0")])])
    _, alarms, _ = closed_loop(no_stop, [(500, "BOT_A", True), (600, "BOT_A", False)], 8000)
    assert any("dois produtos" in a for a in alarms) and any("prejuízo" in a for a in alarms)
