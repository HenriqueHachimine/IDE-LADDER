"""Modulos de expansao (CLIC-02 e CP1E): regras dos manuais, E/S do projeto, enderecos e troca de dados."""
from __future__ import annotations

import os

import pytest

from ladderide.comm.plc_serial import (CLIC_EXP_OUTPUTS, CLIC_INPUTS, CLIC_MARKERS, ClicModbus, OmronHostLink,
                                       ponte_clic)
from ladderide.model import expansions as ex
from ladderide.model.controllers import apply_controller, controller_by_id, match_controller_io
from ladderide.model.project import Project
from test_plc_link import FakeClic, FakeCp1e, FakeLine


def mods(*ids):
    return [ex.BY_ID[i] for i in ids]


def test_rules_from_manuals():
    clic = controller_by_id("clw-02-12hr-d")
    assert (clic.expansion_bus, clic.max_expansions) == ("clic02", 3)
    assert ex.problems(clic, mods("clw-02-8er-d", "clw-02-8et-d", "clw-02-8er-a")) == []
    assert any("no máximo 3" in e for e in ex.problems(clic, mods(*["clw-02-8er-d"] * 4)))
    assert any("não encaixa" in e for e in ex.problems(clic, mods("cp1w-8ed")))
    # CP1E: so 30/40 pontos e NA20 aceitam (W480 6-1-3)
    assert controller_by_id("cp1e-n20dr-a").max_expansions == 0
    assert controller_by_id("cp1e-e20sdr-a").max_expansions == 0
    assert controller_by_id("cp1e-na20dr-a").max_expansions == 3
    n40 = controller_by_id("cp1e-n40dr-a")
    assert ex.problems(n40, mods("cp1w-8ed")) == []                     # 32 entradas: cabe
    assert any("entradas passam" in e for e in ex.problems(n40, mods("cp1w-20edr1")))   # 36
    assert any("saídas passam" in e for e in ex.problems(n40, mods("cp1w-32er")))       # 48
    assert ex.compatible(controller_by_id("cp1e-n14dr-a")) == []


def test_project_io_follows_modules_and_survives_save(tmp_path):
    p = Project()
    apply_controller(p, controller_by_id("clw-02-20vr-d"))
    p.target.expansions = ["clw-02-8er-d", "clw-02-8et-d"]
    assert match_controller_io(p)
    assert (p.io.n_inputs, p.io.n_outputs) == (20, 16)
    path = tmp_path / "exp.ladproj"
    p.save(path)
    q = Project.load(path)
    assert q.target.expansions == ["clw-02-8er-d", "clw-02-8et-d"]
    assert not match_controller_io(q)
    # trocar para um CPU que nao aceita: modulos saem e as E/S voltam as do CPU
    apply_controller(q, controller_by_id("cp1e-n20dr-a"))
    assert q.target.expansions == [] and (q.io.n_inputs, q.io.n_outputs) == (12, 8)


def test_addresses_in_ide_and_plc():
    rows = ex.addresses(controller_by_id("cp1e-n30dr-a"), mods("cp1w-8ed", "cp1w-20edr1", "cp1w-8er"))
    assert [(r["plc_in"], r["plc_out"]) for r in rows] == [
        ("CIO 2.00 a 2.07", ""), ("CIO 3.00 a 3.11", "CIO 102.00 a 102.07"), ("", "CIO 103.00 a 103.07")]
    assert [(r["in_first"], r["out_first"]) for r in rows] == [(18, 12), (26, 12), (38, 20)]
    rows = ex.addresses(controller_by_id("clw-02-12hr-d"), mods("clw-02-8er-d", "clw-02-8er-d"))
    assert [(r["plc_in"], r["plc_out"]) for r in rows] == [("X01 a X04", "Y01 a Y04"), ("X05 a X08", "Y05 a Y08")]


def test_clic_driver_with_modules():
    slave = FakeClic()
    slave.regs[CLIC_INPUTS + 1] = 0b1001          # X01 e X04
    slave.regs[CLIC_INPUTS] = 0b11                # I01 e I02
    d = ClicModbus(FakeLine(slave))
    d.modules = [(4, 4), (4, 4)]
    assert d.read_inputs(16) == 0b11 | 0b1001 << 8           # 8 do CPU (12HR-D) + X01..X08
    d.write_outputs(12, 0b0101 | 0b1100_0000 << 4)            # Q01, Q03 e Y03, Y04... (4 do CPU + 8)
    assert slave.regs[CLIC_MARKERS] == 0b0101                 # M01..M04
    assert slave.regs[CLIC_MARKERS + 1] == 0b1100_0000 >> 0   # M11.. -> Y01..
    slave.regs[CLIC_EXP_OUTPUTS] = 0b10
    slave.regs[CLIC_EXP_OUTPUTS + 1] = 0b1
    assert d.read_outputs(12) == 0b1 | 0b10 << 4
    assert ponte_clic(4, 8)[-1] == "M18 -> Y08" and ponte_clic(4, 8)[4] == "M11 -> Y01"


def test_cp1e_driver_with_modules():
    plc = FakeCp1e()
    plc.cio.update({0: 0b1, 1: 0b100000, 2: 0b1000_0000, 3: 0b1, 102: 0})
    d = OmronHostLink(FakeLine(plc))
    d.modules = [(8, 0), (12, 8)]                 # N30 (18/12) + 8ED + 20EDR1
    assert d.segments(38, False) == [12, 6, 8, 12]
    assert d.read_inputs(38) == 0b1 | 0b100000 << 12 | 0b1000_0000 << 18 | 0b1 << 26
    d.write_outputs(20, 1 | 1 << 11 | 1 << 12 | 1 << 19)
    assert (plc.cio[100], plc.cio[101], plc.cio[102]) == (0b1, 0b1000, 0b1000_0001)
    assert d.read_outputs(20) == 1 | 1 << 11 | 1 << 12 | 1 << 19


def test_compiles_and_generates_cpp_with_more_than_16_outputs():
    from ladderide.codegen.cpp import generate_cpp
    from ladderide.compiler import compile_project
    from ladderide.model import Coil, Contact, Rung
    p = Project()
    apply_controller(p, controller_by_id("cp1e-n40dr-a"))
    p.target.expansions = []
    p.io.n_inputs, p.io.n_outputs = 24, 16
    apply_controller(p, controller_by_id("cp1e-e30sdr-a"))
    p.target.expansions = ["cp1w-16er"]
    match_controller_io(p)
    assert (p.io.n_inputs, p.io.n_outputs) == (18, 28)
    p.rungs = [Rung([Contact("XIC", "I2.1")], [Coil("OTE", "Q3.3")])]     # entrada 17, saida 27
    r = compile_project(p)
    assert r.ok, [str(d) for d in r.errors]
    code = generate_cpp(p).text
    assert "uint32_t plc_scan(uint32_t inputs" in code


def test_expansion_dialog():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication, QDialogButtonBox
    from ladderide.ui.expansion_dialog import ExpansionDialog
    QApplication.instance() or QApplication([])
    dlg = ExpansionDialog(controller_by_id("clw-02-20vr-d"), ["clw-02-8er-d"])
    assert dlg.ids() == ["clw-02-8er-d"]
    dlg.catalog.setCurrentIndex(dlg.catalog.findData("clw-02-8et-d"))
    dlg.add_btn.click()
    assert dlg.ids() == ["clw-02-8er-d", "clw-02-8et-d"]
    assert "20 entradas" in dlg.total.text() and "16 saídas" in dlg.total.text()
    assert dlg.table.rowCount() == 2 and dlg.table.item(1, 2).text() == "X05 a X08"
    dlg.add_btn.click()                                    # 3o modulo: 24 saidas, ainda cabe (limite 32)
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    assert not dlg.add_btn.isEnabled()                     # CLIC-02 aceita 3
    dlg.list.setCurrentRow(2)
    dlg.up_btn.click()
    assert dlg.ids()[1] == "clw-02-8et-d"
    none = ExpansionDialog(controller_by_id("cp1e-n20dr-a"), [])
    assert not none.add_btn.isEnabled() and "não aceita" in none.findChildren(type(none.total))[0].text()
