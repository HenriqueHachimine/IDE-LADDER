"""Modelo de projeto, edicao, compilador, importador e simulador."""
from __future__ import annotations

import pytest

from ladderide.compiler import compile_project, import_lil
from ladderide.core import LadderVM, decode
from ladderide.core.asm import assemble
from ladderide.model import (Coil, Contact, CounterBox, NotOp, Parallel, Project, ProjectFormatError,
                             ResetBox, Rung, Symbol, TimerBox)
from ladderide.model import edit
from ladderide.sim import SimState, Simulator


def seal_project() -> Project:
    p = Project(name="Selo")
    p.symbols = [Symbol("Liga", "I0.0"), Symbol("Desliga", "I0.1"), Symbol("Motor", "Q0.0"),
                 Symbol("Atraso", "T0")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Liga")], [Contact("XIC", "Motor")]]), Contact("XIO", "Desliga")],
             [Coil("OTE", "Motor")]),
        Rung([Contact("XIC", "Motor")], [TimerBox("TON", "Atraso", 100)]),
        Rung([Contact("XIC", "Atraso.DN")], [Coil("OTE", "Q0.1"), CounterBox("CTU", "C0", 2)]),
        Rung([Contact("XIC", "I0.2")], [ResetBox("C0")]),
    ]
    return p


def messages(result):
    return [str(d) for d in result.diagnostics]


# ----------------------------------------------------------------- compilador
def test_compile_matches_hand_written_lil():
    r = compile_project(seal_project())
    assert r.ok, messages(r)
    expected = assemble("""
        .inputs 8
        .outputs 8
        .markers 64
        .timer T0 TON 100
        .counter C0 UP 2
        SOR
        BST
        XIC I0.0
        NXB
        XIC Q0.0
        BND
        XIO I0.1
        OTE Q0.0
        EOR
        SOR
        XIC Q0.0
        TON T0
        EOR
        SOR
        XIC T0.DN
        BST
        OTE Q0.1
        NXB
        CTU C0
        BND
        EOR
        SOR
        XIC I0.2
        RES C0
        EOR
    """)
    assert r.program.code == expected.code
    assert r.program.timers == expected.timers and r.program.counters == expected.counters
    assert decode(r.image).build_id == r.build_id != 0


def test_build_id_is_deterministic():
    assert compile_project(seal_project()).build_id == compile_project(seal_project()).build_id
    p = seal_project()
    p.rungs[1].outputs[0].preset = 200
    assert compile_project(p).build_id != compile_project(seal_project()).build_id


@pytest.mark.parametrize("mutate,fragment", [
    (lambda p: setattr(p.rungs[0].condition[1], "operand", "Parar"), "variável não declarada: Parar"),
    (lambda p: setattr(p.rungs[0].condition[1], "operand", ""), "operando vazio"),
    (lambda p: setattr(p.rungs[0].condition[1], "operand", "I1.0"), "fora da faixa"),
    (lambda p: setattr(p.rungs[0].outputs[0], "operand", "I0.3"), "bobina só pode escrever em Q ou M"),
    (lambda p: setattr(p.rungs[1].outputs[0], "operand", "C1"), "TON exige um temporizador"),
    (lambda p: p.rungs[3].outputs.append(TimerBox("TOF", "T0", 5)), "T0 já e acionado"),
    (lambda p: setattr(p.rungs[3].outputs[0], "operand", "C5"), "RES em C5, que não e acionado"),
    (lambda p: setattr(p.rungs[2].condition[0], "operand", "T3.DN"), "T3 e usado mas nenhuma"),
    (lambda p: setattr(p.rungs[1].outputs[0], "preset", -1), "preset fora da faixa"),
    (lambda p: p.rungs.append(Rung([Contact("XIC", "I0.0")], [])), "rede sem saída"),
    (lambda p: p.symbols.append(Symbol("Liga", "I0.5")), "símbolo duplicado"),
    (lambda p: p.symbols.append(Symbol("I0.5", "I0.5")), "nome de símbolo inválido"),
    (lambda p: p.symbols.append(Symbol("Xis", "Z9")), "endereço inválido"),
])
def test_compile_errors_point_to_problem(mutate, fragment):
    p = seal_project()
    mutate(p)
    r = compile_project(p)
    assert not r.ok and r.image is None
    assert any(fragment in str(d) for d in r.errors), messages(r)


def test_error_carries_rung_and_element():
    p = seal_project()
    bad = p.rungs[2].condition[0]
    bad.operand = "Inexistente"
    r = compile_project(p)
    err = r.errors[0]
    assert (err.rung, err.element_id) == (2, bad.id)


def test_warnings_do_not_block():
    p = seal_project()
    p.rungs.append(Rung([Contact("XIC", "I0.3")], [Coil("OTE", "Q0.0")]))           # bobina duplicada
    p.rungs.append(Rung([Contact("XIC", "I0.4")], [Coil("OTL", "Q0.0")]))           # mistura OTE/OTL
    p.rungs.append(Rung([Parallel([[Contact("XIC", "I0.5")], []])], [Coil("OTE", "M0.0")]))
    p.rungs.append(Rung([Contact("XIC", "I0.6")], [TimerBox("TON", "T1", 5)]))
    r = compile_project(p)
    assert r.ok, messages(r)
    text = " | ".join(messages(r))
    for fragment in ("duplicada", "SET/RESET", "ramo paralelo vazio", "menor que o período"):
        assert fragment in text


def test_branch_depth_limit():
    inner: list = [Contact("XIC", "I0.0")]
    for _ in range(9):
        inner = [Parallel([inner, [Contact("XIC", "I0.1")]])]
    p = Project(rungs=[Rung(inner, [Coil("OTE", "Q0.0")])])
    r = compile_project(p)
    assert any("aninhadas demais" in str(d) for d in r.errors)


# --------------------------------------------------------------- importador
def test_import_roundtrip():
    r = compile_project(seal_project())
    imported = import_lil(r.lil)
    r2 = compile_project(imported)
    assert r2.ok, messages(r2)
    assert r2.program.code == r.program.code


def test_import_series_outputs():
    p = import_lil("SOR\nXIC I0.0\nOTE Q0.0\nOTL Q0.1\nEOR")
    assert [type(o) for o in p.rungs[0].outputs] == [Coil, Coil]


def test_import_rejects_unsupported_structure():
    from ladderide.compiler import ImportError_
    with pytest.raises(ImportError_):
        import_lil("SOR\nOTE Q0.0\nXIC I0.0\nOTE Q0.1\nEOR")


# ----------------------------------------------------------- modelo e edicao
def test_project_save_load_roundtrip(tmp_path):
    p = seal_project()
    path = tmp_path / "x.ladproj"
    p.save(path)
    q = Project.load(path)
    assert q.to_dict()["rungs"] == p.to_dict()["rungs"]
    assert q.symbols == p.symbols and q.history[-1]["action"] == "salvo"
    assert compile_project(q).build_id == compile_project(p).build_id


def test_project_rejects_future_version(tmp_path):
    data = seal_project().to_dict()
    data["format_version"] = 99
    with pytest.raises(ProjectFormatError):
        Project.from_dict(data)
    with pytest.raises(ProjectFormatError):
        Project.from_dict({"format": "outra-coisa"})


def test_edit_operations_keep_tree_valid():
    p = Project(rungs=[Rung()])
    rung = p.rungs[0]
    a, b = Contact("XIC", "I0.0"), Contact("XIC", "I0.1")
    edit.insert(p, rung.condition, 0, a)
    edit.insert(p, rung.condition, 1, b)
    edit.insert(p, rung.outputs, 0, Coil())
    with pytest.raises(edit.EditError):
        edit.insert(p, rung.outputs, 0, Contact())
    with pytest.raises(edit.EditError):
        edit.insert(p, rung.condition, 0, Coil())
    par = edit.wrap_in_parallel(p, b.id)
    assert rung.condition == [a, par] and par.branches == [[b], []]
    c = Contact("XIO", "I0.2")
    edit.insert(p, par.branches[1], 0, c)
    edit.add_branch(p, c.id)
    assert len(par.branches) == 3
    edit.remove_branch(p, c.id)
    assert par.branches == [[b], []]
    edit.remove(p, b.id)
    assert par.branches == [[], []]          # ramos vazios = fio (curto)
    r = compile_project(p)
    assert r.ok and any("ramo paralelo vazio" in str(d) for d in r.warnings)


def test_move_and_self_containment():
    a, b, c = Contact("XIC", "I0.0"), Contact("XIC", "I0.1"), Contact("XIC", "I0.2")
    par = Parallel([[b], [c]])
    p = Project(rungs=[Rung([a, par], [Coil()])])
    edit.move(p, a.id, par.branches[0], 1)
    assert p.rungs[0].condition == [par] and par.branches[0] == [b, a]
    with pytest.raises(edit.EditError):
        edit.move(p, par.id, par.branches[1], 0)
    edit.move(p, c.id, p.rungs[0].condition, 0)   # ramo 2 vazio continua
    assert p.rungs[0].condition[0] is c
    with pytest.raises(edit.EditError):
        edit.move(p, c.id, p.rungs[0].outputs, 0)


def test_normalize_collapses_single_branch():
    a = Contact("XIC", "I0.0")
    par = Parallel([[a], [Contact("XIC", "I0.1")]])
    p = Project(rungs=[Rung([par], [Coil()])])
    edit.remove_branch(p, par.branches[1][0].id)
    assert p.rungs[0].condition == [a]


# ---------------------------------------------------------------- simulador
def test_simulator_matches_vm_and_virtual_time():
    r = compile_project(seal_project())
    sim = Simulator(r, period_ms=10)
    sim.start()
    sim.set_input(0, True)
    sim.advance(10, 1.0)            # primeira varredura + 1
    sim.set_input(0, False)
    sim.advance(200, 1.0)
    assert sim.vm.q[0] and sim.vm.timers[0].dn and sim.vm.q[1]
    assert sim.virtual_ms == 10 * (sim.vm.scan_count - 1)

    ref = LadderVM(r.program)
    ref.scan(1, 0)
    ref.scan(1, 10)
    for _ in range(sim.vm.scan_count - 2):
        ref.scan(0, 10)
    assert ref.dump_line() == sim.vm.dump_line()


def test_simulator_step_mode_and_power():
    r = compile_project(seal_project())
    sim = Simulator(r)
    sim.set_input(0, True)
    executed = []
    while True:
        pc = sim.step_instruction()
        if pc is None or not sim.vm.in_scan:
            executed.append(pc)
            break
        executed.append(pc)
    assert executed == list(range(len(r.program.code)))
    liga_id = r.pc_element[2]   # instrucao 2 = XIC Liga (SOR, BST, XIC)
    assert sim.element_power(liga_id) and sim.operand_value(liga_id) is True
    assert sim.state == SimState.PAUSED


def test_simulator_stop_uses_safe_outputs():
    p = seal_project()
    p.io.safe_outputs = 0b10
    sim = Simulator(compile_project(p))
    sim.start()
    sim.set_input(0, True)
    sim.advance(20)
    assert sim.physical_outputs & 1
    sim.stop()
    assert sim.physical_outputs == 0b10


def test_simulator_refuses_invalid_program():
    p = seal_project()
    p.rungs[0].outputs.clear()
    with pytest.raises(ValueError):
        Simulator(compile_project(p))


def test_not_element_compiles():
    p = Project(rungs=[Rung([Contact("XIC", "I0.0"), NotOp()], [Coil()])])
    r = compile_project(p)
    sim = Simulator(r)
    sim.scan_once()
    assert sim.vm.q[0]


def test_speed_changes_wall_clock_not_result():
    """Acelerar so muda quantas varreduras rodam por segundo; o resultado e o mesmo."""
    r = compile_project(seal_project())
    lines = []
    for speed in (1.0, 50.0):
        sim = Simulator(r, period_ms=10)
        sim.start()
        sim.set_input(0, True)
        sim.advance(10, 1.0)
        sim.set_input(0, False)
        while sim.virtual_ms < 3000:
            sim.advance(30 / speed if speed > 1 else 30, speed)
        lines.append((sim.virtual_ms, sim.vm.dump_line()))
    assert lines[0] == lines[1]
    sim = Simulator(r, period_ms=10)
    sim.start()
    assert sim.advance(30, 100.0) == 301 and sim.actual_speed == pytest.approx(100.3, abs=0.1)
    assert not sim.limited


def test_speed_limited_by_cpu_budget():
    import math
    sim = Simulator(compile_project(seal_project()), period_ms=10)
    sim.start()
    n = sim.advance(30, 1000.0, work_ms=0)     # sem tempo de CPU: roda a primeira e corta o resto
    assert n < 3000 and sim.limited and sim._budget == 0.0
    n = sim.advance(30, math.inf, work_ms=5)   # maxima: o quanto couber em 5 ms
    assert 0 < n <= Simulator.MAX_SCANS_PER_ADVANCE and not sim.limited
