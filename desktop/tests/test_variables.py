"""Variaveis de memoria (boolean, inteira, float) e aritmetica em float.

O float tem de dar o mesmo resultado no simulador, na VM em C do firmware e no C++ gerado.
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess

import pytest

from ladderide.codegen import generate_cpp
from ladderide.compiler import compile_project, import_lil
from ladderide.core import LadderVM, isa
from ladderide.core.asm import disassemble, parse_float_constant
from ladderide.core.image import decode
from ladderide.core.isa import Area
from ladderide.model import variables
from ladderide.model.project import (CompareBox, Coil, Contact, IOConfig, MathBox, Project, ProjectFormatError, Rung,
                                     Symbol, Variable)
from ladderide.sim.simulator import Simulator

CXX = shutil.which("g++")
FLOATS = ["0.0", "1.5", "-2.25", "0.1", "1e10", "-3e38", "3e38", "1e-30", "0.5", "2.5", "-0.5", "16777217.0"]
INTS = ["0", "1", "-1", "7", "2147483647", "-2147483648"]


def rung(kind: str, operands: list[str], *contacts: str) -> Rung:
    return Rung([Contact("XIC", c) for c in contacts], [MathBox(kind, operands)])


def run(project: Project, scans: int = 1) -> LadderVM:
    result = compile_project(project)
    assert result.ok, [str(d) for d in result.errors]
    vm = LadderVM(decode(result.image))
    for _ in range(scans):
        vm.scan(0, 10)
    return vm


def project_with(*rungs: Rung, variables_: list[Variable] | None = None) -> Project:
    return Project(rungs=list(rungs), variables=variables_ or [])


# ------------------------------------------------------------------- semantica do float
def test_float_arithmetic_and_rounding_to_integer():
    vm = run(project_with(rung("ADD", ["1.5", "2.25", "F0"]), rung("MOV", ["F0", "N1"]), rung("MOV", ["-2.5", "N2"]),
                          rung("MOV", ["N1", "F3"]), rung("DIV", ["1.0", "4", "F4"])))
    assert vm.read_word(Area.F, 0) == 3.75
    assert vm.n[1] == 4 and vm.n[2] == -3                 # metade afasta de zero
    assert vm.read_word(Area.F, 3) == 4.0 and vm.read_word(Area.F, 4) == 0.25


@pytest.mark.parametrize("operands,expected,ov", [
    (["1.0", "0.0", "F0"], isa.FLOAT_MAX, True), (["-1.0", "0.0", "F0"], -isa.FLOAT_MAX, True),
])
def test_float_division_by_zero_saturates(operands, expected, ov):
    vm = run(project_with(rung("DIV", operands)))
    assert vm.read_word(Area.F, 0) == expected and vm.math_ov is ov


def test_float_overflow_saturates_and_sets_math_ov():
    vm = run(project_with(rung("MUL", ["3e38", "3e38", "F0"])))
    assert vm.read_word(Area.F, 0) == isa.FLOAT_MAX and vm.math_ov


def test_float_to_integer_saturates():
    vm = run(project_with(rung("MOV", ["3e38", "N0"])))
    assert vm.n[0] == isa.INT32_MAX and vm.math_ov


def test_negative_square_root_uses_magnitude_and_sets_overflow():
    vm = run(project_with(rung("SQR", ["-16.0", "F0"])))
    assert vm.read_word(Area.F, 0) == 4.0 and vm.math_ov


def test_float_precision_is_32_bits():
    vm = run(project_with(rung("ADD", ["16777216.0", "1.0", "F0"])))
    assert vm.read_word(Area.F, 0) == 16777216.0


def test_compare_mixes_integer_and_float():
    p = project_with(Rung([CompareBox("GRT", ["1.5", "1"])], [Coil("OTE", "Q0.0")]),
                     Rung([CompareBox("LIM", ["1", "1.5", "2"])], [Coil("OTE", "Q0.1")]),
                     Rung([CompareBox("LES", ["1.5", "1"])], [Coil("OTE", "Q0.2")]))
    assert run(p).outputs == 0b011


@pytest.mark.parametrize("box", [CompareBox("MEQ", ["1.5", "1", "1"]), MathBox("TOD", ["F0", "N0"]),
                                 MathBox("FRD", ["N0", "F0"])])
def test_integer_only_blocks_refuse_float(box):
    r = Rung([box], [Coil("OTE", "Q0.0")]) if isinstance(box, CompareBox) else Rung([], [box])
    result = compile_project(project_with(r))
    assert not result.ok and "inteiros" in str(result.errors[0])


def test_float_constant_parsing():
    assert parse_float_constant("1.5") == 1.5 and parse_float_constant("2e3") == 2000.0
    assert parse_float_constant("5") is None and parse_float_constant("E5") is None
    with pytest.raises(ValueError):
        parse_float_constant("1e39")


def test_float_register_address_cannot_be_a_symbol_name():
    p = project_with(rung("MOV", ["1", "N0"]))
    p.symbols.append(Symbol("F1", "N3"))
    assert not compile_project(p).ok


def test_listing_round_trip_keeps_float_operands():
    p = project_with(rung("ADD", ["F0", "1.5", "F1"]))
    result = compile_project(p)
    imported = import_lil(disassemble(result.program))
    assert imported.rungs[0].outputs[0].operands == ["F0", "1.5", "F1"]


# ------------------------------------------------------------------------ tabela
def typed_project() -> Project:
    return project_with(rung("MOV", ["Limite", "N0"]),
                        variables_=[Variable("Ligado", "boolean", "1"), Variable("Limite", "integer", "42"),
                                    Variable("Ganho", "float", "1,5"), Variable("Zero", "float", "")])


def test_addresses_come_from_the_end_of_each_area_and_skip_used_ones():
    p = typed_project()
    p.symbols.append(Symbol("Reservado", f"N{p.io.n_words - 1}"))
    table = variables.addresses(p)
    last = p.io.n_words - 2
    assert table == {"Ligado": f"M{(p.io.n_markers - 1) // 8}.{(p.io.n_markers - 1) % 8}", "Limite": f"N{last}",
                     "Ganho": f"F{last - 1}", "Zero": f"F{last - 2}"}


def test_initial_values_apply_on_the_first_scan():
    vm = run(typed_project())
    table = variables.addresses(typed_project())
    assert vm.n[0] == 42 and vm.read_word(Area.F, int(table["Ganho"][1:])) == 1.5
    assert vm.m[typed_project().io.n_markers - 1]


def test_values_go_back_to_initial_on_every_start():
    p = typed_project()
    p.rungs.append(rung("ADD", ["Limite", "1", "Limite"]))
    result = compile_project(p)
    assert result.ok, result.errors
    sim = Simulator(result, 10)
    sim.start()
    for _ in range(5):
        sim.scan_once()
    index = int(variables.addresses(p)["Limite"][1:])
    assert sim.vm.n[index] == 47
    sim.stop()
    sim.start()
    sim.scan_once()
    assert sim.vm.n[index] == 43


def test_initial_values_do_not_change_rung_numbering_or_first_rung_logic():
    p = project_with(Rung([Contact("XIO", "I0.0")], [Coil("OTE", "Q0.0")]), variables_=[Variable("V", "integer", "1")])
    result = compile_project(p)
    assert result.program.n_rungs == 1 and run(p).outputs == 1


def test_import_ignores_generated_initial_values():
    result = compile_project(typed_project())
    assert import_lil(disassemble(result.program)).rungs[0].outputs[0].kind == "MOV"


@pytest.mark.parametrize("variable", [Variable("1ruim"), Variable("N5"), Variable("F5"), Variable("X", "integer", "abc"),
                                      Variable("X", "float", "x"), Variable("X", "boolean", "2")])
def test_invalid_variable_is_a_compile_error(variable):
    assert not compile_project(project_with(rung("MOV", ["1", "N0"]), variables_=[variable])).ok


def test_duplicate_of_a_symbol_name_is_a_compile_error():
    p = project_with(rung("MOV", ["1", "N0"]), variables_=[Variable("Motor")])
    p.symbols.append(Symbol("Motor", "Q0.0"))
    assert not compile_project(p).ok


def test_running_out_of_registers_is_a_compile_error():
    p = Project(io=IOConfig(n_words=1), rungs=[rung("MOV", ["1", "N0"])],
                variables=[Variable("A"), Variable("B")])
    errors = compile_project(p).errors
    assert errors and "livres" in str(errors[0])


def test_variables_survive_save_and_load(tmp_path):
    path = tmp_path / "v.ladproj"
    typed_project().save(path)
    assert [vars(v) for v in Project.load(path).variables] == [vars(v) for v in typed_project().variables]


def test_old_project_without_variables_still_loads():
    data = project_with(rung("MOV", ["1", "N0"])).to_dict()
    del data["variables"]
    assert Project.from_dict(data).variables == []


def test_invalid_variable_type_in_file_is_refused():
    data = typed_project().to_dict()
    data["variables"][0]["type"] = "texto"
    with pytest.raises(ProjectFormatError):
        Project.from_dict(data)


# -------------------------------------------------------------------- equivalencia
def random_float_project(rng: random.Random) -> Project:
    p = Project(io=IOConfig(n_inputs=8, n_outputs=8, n_markers=16, n_words=8))
    reads = [f"F{k}" for k in range(4)] + [f"N{k}" for k in range(4)] + FLOATS + INTS
    writes = [f"F{k}" for k in range(4)] + [f"N{k}" for k in range(4)]
    p.rungs = []
    for _ in range(rng.randint(2, 8)):
        cond: list = []
        if rng.random() < 0.5:
            cond.append(Contact("XIC", f"I0.{rng.randrange(8)}"))
        if rng.random() < 0.5:
            kind = rng.choice(["EQU", "NEQ", "LES", "GRT", "LEQ", "GEQ"])
            cond.append(CompareBox(kind, [rng.choice(reads), rng.choice(FLOATS)]))
        two = rng.choice(["ADD", "SUB", "MUL", "DIV"])
        one = rng.choice(["SQR", "NEG", "MOV"])
        out = (MathBox(two, [rng.choice(reads), rng.choice(reads), rng.choice(writes)]) if rng.random() < 0.6
               else MathBox(one, [rng.choice(reads), rng.choice(writes)]))
        p.rungs.append(Rung(cond, [out, Coil("OTE", f"Q0.{rng.randrange(8)}")]))
    p.variables = [Variable("Gv", "float", rng.choice(["1.5", "-0.25", ""])), Variable("Iv", "integer", rng.choice(["7", ""])),
                   Variable("Bv", "boolean", rng.choice(["1", "0"]))]
    return p


def scans_for(rng: random.Random, count: int = 30) -> list[tuple[int, int]]:
    return [(rng.randrange(256), rng.choice([0, 1, 10, 100])) for _ in range(count)]


@pytest.mark.parametrize("seed", range(40))
def test_python_and_firmware_c_agree_on_float(c_vm, seed):
    rng = random.Random(seed)
    result = compile_project(random_float_project(rng))
    assert result.ok, [str(d) for d in result.errors]
    scans = scans_for(rng)
    run_c = c_vm.run(result.image, [(dt, inputs) for inputs, dt in scans])
    assert run_c.error is None
    vm = LadderVM(decode(result.image))
    expected = []
    for inputs, dt in scans:
        vm.scan(inputs, dt)
        expected.append(vm.dump_line())
    assert run_c.lines == expected


@pytest.mark.skipif(CXX is None, reason="sem g++")
def test_generated_cpp_agrees_with_the_simulator_on_float(tmp_path):
    rng = random.Random(7)
    sources, cases = [], []
    for k in range(25):
        project = random_float_project(rng)
        result = compile_project(project)
        assert result.ok
        sources.append(generate_cpp(project, namespace=f"p{k}", arduino=False).text.replace("#include <stdint.h>\n", ""))
        cases.append((project, result, scans_for(rng)))
    main = ["#include <stdint.h>", "#include <stdio.h>", *sources, "int main() {"]
    for k, (project, _, scans) in enumerate(cases):
        main.append(f"  p{k}::plc_start();")
        for inputs, dt in scans:
            main.append(f'  printf("%x", (unsigned)p{k}::plc_scan({inputs}, {dt}));')
            main += [f'  printf(" %d", (int)p{k}::N[{n}]);' for n in range(project.io.n_words)]
            main.append(f'  printf(" %d%d%d\\n", p{k}::MATH_OV, p{k}::MATH_ZERO, p{k}::MATH_SIGN);')
    main += ["  return 0;", "}"]
    src, exe = tmp_path / "t.cpp", tmp_path / "t.exe"
    src.write_text("\n".join(main), encoding="utf-8")
    subprocess.run([CXX, "-std=gnu++11", "-O1", str(src), "-o", str(exe), "-lm"], check=True, capture_output=True, text=True)
    got = subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout.splitlines()
    expected = []
    for _, result, scans in cases:
        vm = LadderVM(decode(result.image))
        for inputs, dt in scans:
            vm.scan(inputs, dt)
            flags = f"{int(vm.math_ov)}{int(vm.math_zero)}{int(vm.math_sign)}"
            expected.append(f"{vm.outputs:x} " + " ".join(str(v) for v in vm.n) + f" {flags}")
    assert got == expected


# ------------------------------------------------------------------------- interface
def main_window():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from ladderide.ui.main_window import MainWindow
    QApplication.instance() or QApplication([])
    return MainWindow(persist_layout=False)


def test_panel_adds_edits_and_refuses_invalid_values():
    w = main_window()
    w.variable_add()
    assert [v.name for v in w.project.variables] == ["Var1"]
    panel = w.variables_panel
    panel.table.item(0, 0).setText("Temperatura")
    assert w.project.variables[0].name == "Temperatura"
    panel.table.cellWidget(0, 1).setCurrentIndex(2)
    panel.table.cellWidget(0, 1).activated.emit(2)
    assert w.project.variables[0].type == "float"
    assert w.variables_panel.table.item(0, 3).text().startswith("F")
    panel = w.variables_panel
    panel.table.item(0, 2).setText("1,5")
    assert w.project.variables[0].initial == "1,5"
    panel.table.item(0, 2).setText("abc")
    assert w.project.variables[0].initial == "1,5" and panel.table.item(0, 2).text() == "1,5"
    panel.table.item(0, 0).setText("N3")
    assert w.project.variables[0].name == "Temperatura"
    w.undo()
    assert w.project.variables[0].initial == ""
    w.dirty = False


def test_changing_type_clears_an_initial_value_that_no_longer_fits():
    w = main_window()
    w.variable_add()
    w.on_variable_edited(0, "initial", "42")
    w.on_variable_edited(0, "type", "boolean")
    assert w.project.variables[0].type == "boolean" and w.project.variables[0].initial == ""
    w.dirty = False


def test_symbol_and_variable_names_cannot_collide():
    w = main_window()
    w.project.symbols.append(Symbol("Motor", "Q0.0"))
    w.variable_add()
    w.on_variable_edited(0, "name", "motor")
    assert w.project.variables[0].name == "Var1"
    w.dirty = False


def test_io_panel_shows_typed_values_during_simulation():
    w = main_window()
    w.project.rungs = [rung("MOV", ["1.5", "Ganho"])]
    w.project.variables = [Variable("Ganho", "float")]
    w.refresh()
    w.sim_run()
    w.sim.advance(20, 1.0)
    w._update_live()
    table = w.sim_panel.io.variables
    row = next(r for r in range(table.rowCount()) if table.item(r, 0).text() == "Ganho")
    assert table.item(row, 2).text() == "1.5"
    w.sim_stop()
    w.dirty = False


def test_variables_table_is_locked_during_simulation():
    w = main_window()
    w.project.rungs = [rung("MOV", ["1", "N0"])]
    w.refresh()
    w.sim_run()
    assert not w.variables_panel.isEnabled()
    w.sim_stop()
    assert w.variables_panel.isEnabled()
    w.dirty = False
