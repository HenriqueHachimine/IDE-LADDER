"""Modelo: renomear simbolos atualiza os operandos do programa."""
from __future__ import annotations

import pytest

from ladderide.model import Coil, Contact, Project, Rung, Symbol
from ladderide.model.project import CounterBox, MathBox, Parallel


def make_project() -> Project:
    p = Project()
    p.rungs = [Rung([Parallel([[Contact("XIC", "liga")], [Contact("XIC", "Caixas.DN")]])],
                    [CounterBox("CTU", "Caixas", 5), MathBox("ADD", ["Total", "1", "Total"])]),
               Rung([Contact("XIC", "Ligado")], [Coil("OTE", "Q0.0")])]
    p.symbols = [Symbol("Liga", "I0.0"), Symbol("Caixas", "C0"), Symbol("Total", "N0")]
    return p


def test_rename_updates_operands_inside_branches_and_suffixes():
    p = make_project()
    p.set_symbol_name("C0", "Lote")
    p.set_symbol_name("i0.0", "Partida")
    p.set_symbol_name("N0", "Contagem")
    cond = p.rungs[0].condition[0].branches
    assert cond[0][0].operand == "Partida" and cond[1][0].operand == "Lote.DN"
    assert p.rungs[0].outputs[0].operand == "Lote"
    assert p.rungs[0].outputs[1].operands == ["Contagem", "1", "Contagem"]
    assert p.rungs[1].condition[0].operand == "Ligado"        # nome que so comeca igual nao muda


def test_new_name_and_removal():
    p = make_project()
    p.set_symbol_name("Q0.0", "Esteira", "Coil 0 (Factory IO)")
    assert p.symbols[-1] == Symbol("Esteira", "Q0.0", "Coil 0 (Factory IO)")
    p.set_symbol_name("C0", "")
    assert p.symbol_for("C0") is None
    assert p.rungs[0].outputs[0].operand == "C0"
    assert p.rungs[0].condition[0].branches[1][0].operand == "C0.DN"


@pytest.mark.parametrize("name", ["Total", "total", "Q0.1", "2x", "com espaco"])
def test_invalid_or_repeated_names_are_rejected(name):
    p = make_project()
    with pytest.raises(ValueError):
        p.set_symbol_name("I0.0", name)
    assert p.symbols[0].name == "Liga"
