#!/usr/bin/env python3
"""Gera os projetos de exemplo em examples/ a partir do modelo (reprodutivel).

Uso: python scripts/make_examples.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop" / "src"))

from ladderide.compiler import compile_project  # noqa: E402
from ladderide.model import (Coil, Contact, CounterBox, NotOp, Parallel, Project, ResetBox, Rung,  # noqa: E402
                             Symbol, TimerBox)


def demo() -> Project:
    p = Project(name="Demonstracao", version="1.0.0", description=(
        "Roteiro da demonstracao final: selo de partida/parada (NA/NF), TON, TOF, contagem com CTU e RES."))
    p.symbols = [
        Symbol("Partida", "I0.0", "Botao de partida (NA)"),
        Symbol("Parada", "I0.1", "Botao de parada (NA, usado como contato NF no programa)"),
        Symbol("Sensor_Peca", "I0.2", "Sensor de passagem de peca"),
        Symbol("Zera_Contagem", "I0.3", "Botao para zerar a contagem"),
        Symbol("Motor", "Q0.0", "Rele 1 - motor"),
        Symbol("Em_Regime", "Q0.1", "Rele 2 - sinaliza 2 s apos a partida (TON)"),
        Symbol("Ventilador", "Q0.2", "Rele 3 - permanece 3 s apos parar (TOF)"),
        Symbol("Lote_Completo", "Q0.3", "Rele 4 - 5 pecas contadas"),
        Symbol("Alarme_Pisca", "Q0.4", "Rele 5 - pisca com lote completo"),
        Symbol("Atraso_Partida", "T0", "TON 2 s"),
        Symbol("Pos_Ventilacao", "T1", "TOF 3 s"),
        Symbol("Pecas", "C0", "CTU 5 pecas"),
    ]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Partida")], [Contact("XIC", "Motor")]]), Contact("XIO", "Parada")],
             [Coil("OTE", "Motor")], "Selo partida/parada"),
        Rung([Contact("XIC", "Motor")], [TimerBox("TON", "Atraso_Partida", 2000)], "Atraso de 2 s"),
        Rung([Contact("XIC", "Atraso_Partida.DN")], [Coil("OTE", "Em_Regime")], "Motor em regime"),
        Rung([Contact("XIC", "Motor")], [TimerBox("TOF", "Pos_Ventilacao", 3000)], "Pos-ventilacao"),
        Rung([Contact("XIC", "Pos_Ventilacao.DN")], [Coil("OTE", "Ventilador")]),
        Rung([Contact("XIC", "Motor"), Contact("XIC", "Sensor_Peca")], [CounterBox("CTU", "Pecas", 5)],
             "Conta pecas com motor ligado"),
        Rung([Contact("XIC", "Pecas.DN")], [Coil("OTE", "Lote_Completo")]),
        Rung([Contact("XIC", "Zera_Contagem")], [ResetBox("Pecas")], "Zera a contagem"),
        Rung([Contact("XIC", "Lote_Completo"), Contact("XIC", "S0.3")], [Coil("OTE", "Alarme_Pisca")],
             "Pisca 1 Hz"),
    ]
    return p


def combinational() -> Project:
    p = Project(name="Portas logicas", description="AND, OR, NOT, XOR, NAND e SET/RESET com contatos.")
    p.symbols = [Symbol("A", "I0.0"), Symbol("B", "I0.1")]
    a, b = (lambda: Contact("XIC", "A")), (lambda: Contact("XIC", "B"))
    na, nb = (lambda: Contact("XIO", "A")), (lambda: Contact("XIO", "B"))
    p.rungs = [
        Rung([a(), b()], [Coil("OTE", "Q0.0")], "AND"),
        Rung([Parallel([[a()], [b()]])], [Coil("OTE", "Q0.1")], "OR"),
        Rung([na()], [Coil("OTE", "Q0.2")], "NOT A (contato NF)"),
        Rung([Parallel([[a(), nb()], [na(), b()]])], [Coil("OTE", "Q0.3")], "XOR"),
        Rung([a(), b(), NotOp()], [Coil("OTE", "Q0.4")], "NAND"),
        Rung([Contact("XIC", "I0.2")], [Coil("OTL", "Q0.5")], "SET"),
        Rung([Contact("XIC", "I0.3")], [Coil("OTU", "Q0.5")], "RESET (vence por estar depois)"),
    ]
    return p


def timers() -> Project:
    p = Project(name="Temporizadores", description="TON, TOF e RTO com RES.")
    p.rungs = [
        Rung([Contact("XIC", "I0.0")], [TimerBox("TON", "T0", 1000)], "TON 1 s"),
        Rung([Contact("XIC", "T0.DN")], [Coil("OTE", "Q0.0")]),
        Rung([Contact("XIC", "I0.1")], [TimerBox("TOF", "T1", 1500)], "TOF 1,5 s"),
        Rung([Contact("XIC", "T1.DN")], [Coil("OTE", "Q0.1")]),
        Rung([Contact("XIC", "I0.2")], [TimerBox("RTO", "T2", 3000)], "RTO 3 s (acumula)"),
        Rung([Contact("XIC", "T2.DN")], [Coil("OTE", "Q0.2")]),
        Rung([Contact("XIC", "I0.3")], [ResetBox("T2")], "Zera o RTO"),
        Rung([Contact("XIO", "T3.DN")], [TimerBox("TON", "T3", 500)], "Oscilador 0,5 s"),
        Rung([Contact("XIC", "T3.DN")], [CounterBox("CTU", "C0", 1000000)]),
        Rung([Contact("XIC", "S0.3")], [Coil("OTE", "Q0.3")], "Relogio de sistema 1 Hz"),
    ]
    return p


def counters() -> Project:
    p = Project(name="Contadores", description="CTU, CTD e reset.")
    p.rungs = [
        Rung([Contact("XIC", "I0.0")], [CounterBox("CTU", "C0", 3)], "Conta 3 pulsos"),
        Rung([Contact("XIC", "C0.DN")], [Coil("OTE", "Q0.0")]),
        Rung([Contact("XIC", "I0.1")], [CounterBox("CTD", "C1", 4)], "Decrementa de 4 ate 0"),
        Rung([Contact("XIC", "C1.DN")], [Coil("OTE", "Q0.1")]),
        Rung([Contact("XIC", "I0.2")], [ResetBox("C0"), ResetBox("C1")], "Reset dos dois contadores"),
    ]
    return p


def relay_chase() -> Project:
    """Teste de hardware: liga um rele por vez, 1 s cada, em sequencia (Q0.0 ... Q0.7)."""
    p = Project(name="Teste de reles", description=(
        "Liga cada rele por 1 s, em sequencia, enquanto I0.0 estiver ativo. Verifica mapeamento e polaridade "
        "das 8 saidas (docs/hardware-test-procedure.md, ensaio H2)."))
    p.rungs = [Rung([Contact("XIC", "I0.0"), Contact("XIO", "T7.DN")], [TimerBox("TON", "T0", 1000)],
                    "T0..T7 em cascata; T7 reinicia o ciclo")]
    for k in range(1, 8):
        p.rungs.append(Rung([Contact("XIC", f"T{k - 1}.DN")], [TimerBox("TON", f"T{k}", 1000)]))
    p.rungs.append(Rung([Contact("XIC", "I0.0"), Contact("XIO", "T0.DN")], [Coil("OTE", "Q0.0")]))
    for k in range(1, 8):
        p.rungs.append(Rung([Contact("XIC", f"T{k - 1}.DN"), Contact("XIO", f"T{k}.DN")],
                            [Coil("OTE", f"Q0.{k}")]))
    return p


def input_mirror() -> Project:
    """Teste de hardware: cada entrada Ik aciona o rele Qk."""
    p = Project(name="Espelho de entradas", description=(
        "Ik -> Qk. Verifica mapeamento e polaridade das 8 entradas (ensaio H1)."))
    p.rungs = [Rung([Contact("XIC", f"I0.{k}")], [Coil("OTE", f"Q0.{k}")]) for k in range(8)]
    return p


def main() -> int:
    targets = {"demo/demonstracao.ladproj": demo(), "combinational/portas_logicas.ladproj": combinational(),
               "timers/temporizadores.ladproj": timers(), "counters/contadores.ladproj": counters(),
               "hardware/teste_reles.ladproj": relay_chase(), "hardware/espelho_entradas.ladproj": input_mirror()}
    for rel, project in targets.items():
        result = compile_project(project)
        if not result.ok:
            print(f"{rel}: ERROS", *result.errors, sep="\n  ")
            return 1
        path = ROOT / "examples" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        project.history.clear()
        project.save(path, note="gerado por scripts/make_examples.py")
        (path.with_suffix(".lil")).write_text(result.lil, encoding="utf-8")
        print(f"{rel}: {len(result.program.code)} instrucoes, {len(result.warnings)} aviso(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
