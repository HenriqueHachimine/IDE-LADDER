#!/usr/bin/env python3
"""Gera os projetos de exemplo em examples/ a partir do modelo (reprodutivel).

Uso: python scripts/make_examples.py [prefixo]
     (ex.: "ambientes/" gera somente os exemplos dos ambientes de simulacao)
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


def env_project(env_id: str, name: str, description: str) -> Project:
    """Projeto ligado a um ambiente, com os simbolos dos pontos de E/S dele."""
    from ladderide.envs import get
    env = get(env_id)
    p = Project(name=name, description=description, environment=env_id)
    p.symbols = [Symbol(pt.label, pt.address, pt.description) for pt in env.inputs + env.outputs]
    return p


def silo() -> Project:
    p = env_project("silo", "Silo de envase", (
        "Esteira para com a caixa sob o bico, enche ate o sensor de nivel e segue. A caixa cheia e "
        "memorizada (M0.0) porque o sensor de nivel deixa de ve-la quando ela anda, enquanto a fotocelula "
        "continua interrompida ate a caixa sair. Stop e NF: o programa usa contato NA (XIC)."))
    p.symbols.append(Symbol("Caixa_Cheia", "M0.0", "caixa sob o bico ja foi enchida"))
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Start")], [Contact("XIC", "Lampada_Run")]]), Contact("XIC", "Stop")],
             [Coil("OTE", "Lampada_Run")], "Liga/desliga o processo (selo)"),
        Rung([Contact("XIC", "Sensor_Nivel")], [Coil("OTL", "Caixa_Cheia")],
             "Memoriza caixa cheia (o sensor de nivel para de ver a caixa quando ela anda)"),
        Rung([Contact("XIO", "Sensor_Presenca")], [Coil("OTU", "Caixa_Cheia")],
             "Feixe livre: a caixa cheia saiu, espera a proxima"),
        Rung([Contact("XIC", "Lampada_Run"),
              Parallel([[Contact("XIO", "Sensor_Presenca")], [Contact("XIC", "Caixa_Cheia")]])],
             [Coil("OTE", "Motor_Esteira")], "Esteira anda sem caixa no bico ou com a caixa cheia"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Sensor_Presenca"), Contact("XIO", "Caixa_Cheia")],
             [Coil("OTE", "Valvula"), Coil("OTE", "Lampada_Fill")], "Enche a caixa posicionada"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Caixa_Cheia")], [Coil("OTE", "Lampada_Full")],
             "Sinaliza caixa cheia"),
    ]
    return p


def traffic_light() -> Project:
    p = env_project("semaforo", "Semaforo de cruzamento", (
        "Ciclo por tempo com valores de engenharia de trafego: verde 8 s, amarelo 3 s (50 km/h) e "
        "vermelho geral 2 s para o cruzamento esvaziar. Pedestres (1,3 m/s, ~10 s para atravessar) so "
        "iniciam a travessia nos 2 primeiros segundos da fase, para terminar antes do verde conflitante."))
    p.symbols += [Symbol("Fase_NS_Verde", "T0", "8 s"), Symbol("Fase_NS_Amarelo", "T1", "3 s"),
                  Symbol("Fase_Todos_Vermelho1", "T2", "2 s"), Symbol("Fase_LO_Verde", "T3", "8 s"),
                  Symbol("Fase_LO_Amarelo", "T4", "3 s"), Symbol("Fase_Todos_Vermelho2", "T5", "2 s"),
                  Symbol("Janela_Pedestre_LO", "T6", "2 s no inicio do verde NS"),
                  Symbol("Janela_Pedestre_NS", "T7", "2 s no inicio do verde LO"),
                  Symbol("Pedido_NS", "M0.0", "pedestre pediu travessia da via NS"),
                  Symbol("Pedido_LO", "M0.1", "pedestre pediu travessia da via LO")]
    verde_ns = [Contact("XIO", "Fase_NS_Verde.DN")]
    verde_lo = [Contact("XIC", "Fase_Todos_Vermelho1.DN"), Contact("XIO", "Fase_LO_Verde.DN")]
    p.rungs = [
        Rung([Contact("XIO", "Fase_Todos_Vermelho2.DN")], [TimerBox("TON", "Fase_NS_Verde", 8000)],
             "Sequenciador: cada fase comeca quando a anterior termina"),
        Rung([Contact("XIC", "Fase_NS_Verde.DN")], [TimerBox("TON", "Fase_NS_Amarelo", 3000)]),
        Rung([Contact("XIC", "Fase_NS_Amarelo.DN")], [TimerBox("TON", "Fase_Todos_Vermelho1", 2000)]),
        Rung([Contact("XIC", "Fase_Todos_Vermelho1.DN")], [TimerBox("TON", "Fase_LO_Verde", 8000)]),
        Rung([Contact("XIC", "Fase_LO_Verde.DN")], [TimerBox("TON", "Fase_LO_Amarelo", 3000)]),
        Rung([Contact("XIC", "Fase_LO_Amarelo.DN")], [TimerBox("TON", "Fase_Todos_Vermelho2", 2000)],
             "Fim do ciclo: reinicia a fase 1"),
        Rung(list(verde_ns), [Coil("OTE", "Verde_NS")], "Via Norte-Sul"),
        Rung([Contact("XIC", "Fase_NS_Verde.DN"), Contact("XIO", "Fase_NS_Amarelo.DN")], [Coil("OTE", "Amarelo_NS")]),
        Rung([Contact("XIC", "Fase_NS_Amarelo.DN")], [Coil("OTE", "Vermelho_NS")]),
        Rung(list(verde_lo), [Coil("OTE", "Verde_LO")], "Via Leste-Oeste"),
        Rung([Contact("XIC", "Fase_LO_Verde.DN"), Contact("XIO", "Fase_LO_Amarelo.DN")], [Coil("OTE", "Amarelo_LO")]),
        Rung([Parallel([[Contact("XIO", "Fase_Todos_Vermelho1.DN")], [Contact("XIC", "Fase_LO_Amarelo.DN")]])],
             [Coil("OTE", "Vermelho_LO")]),
        Rung([Contact("XIC", "Botao_Pedestre_NS")], [Coil("OTL", "Pedido_NS")], "Pedestres: memoriza o pedido"),
        Rung([Contact("XIC", "Botao_Pedestre_LO")], [Coil("OTL", "Pedido_LO")]),
        Rung(list(verde_ns), [TimerBox("TON", "Janela_Pedestre_LO", 2000)],
             "Janela de 2 s para iniciar a travessia (o resto do verde e o tempo de terminar)"),
        Rung([Contact("XIC", "Fase_Todos_Vermelho1.DN"), Contact("XIO", "Fase_LO_Verde.DN")],
             [TimerBox("TON", "Janela_Pedestre_NS", 2000)]),
        Rung([Contact("XIO", "Fase_NS_Verde.DN"), Contact("XIO", "Janela_Pedestre_LO.DN"),
              Parallel([[Contact("XIC", "Pedido_LO")], [Contact("XIC", "Pedestre_LO")]])],
             [Coil("OTE", "Pedestre_LO")], "Atravessa a via LO (parada) no inicio do verde NS"),
        Rung([Contact("XIC", "Pedestre_LO")], [Coil("OTU", "Pedido_LO")], "Pedido atendido"),
        Rung([Contact("XIC", "Fase_Todos_Vermelho1.DN"), Contact("XIO", "Fase_LO_Verde.DN"),
              Contact("XIO", "Janela_Pedestre_NS.DN"),
              Parallel([[Contact("XIC", "Pedido_NS")], [Contact("XIC", "Pedestre_NS")]])],
             [Coil("OTE", "Pedestre_NS")], "Atravessa a via NS (parada) no inicio do verde LO"),
        Rung([Contact("XIC", "Pedestre_NS")], [Coil("OTU", "Pedido_NS")]),
    ]
    return p


def garage_door() -> Project:
    p = env_project("portao", "Portao de garagem", (
        "Abre/fecha com selo, para nos fins de curso, intertravamento sobe/desce e, se a fotocelula "
        "detectar um veiculo durante o fechamento, para o motor e so reabre depois de 0,6 s (o portao tem "
        "inercia: inverter com ele em movimento danifica o redutor)."))
    p.symbols.append(Symbol("Espera_Reversao", "T0", "0,6 s parado antes de reabrir"))
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Abrir")], [Contact("XIC", "Motor_Sobe")],
                        [Contact("XIC", "Espera_Reversao.DN")]]),
              Contact("XIC", "Parar"), Contact("XIO", "Fim_Curso_Aberto"), Contact("XIO", "Motor_Desce")],
             [Coil("OTE", "Motor_Sobe")], "Abrir (selo); reabre sozinho depois da espera da fotocelula"),
        Rung([Parallel([[Contact("XIC", "Fechar")], [Contact("XIC", "Motor_Desce")]]), Contact("XIC", "Parar"),
              Contact("XIO", "Fim_Curso_Fechado"), Contact("XIO", "Motor_Sobe"), Contact("XIO", "Fotocelula")],
             [Coil("OTE", "Motor_Desce")], "Fechar (selo) com intertravamento; a fotocelula para o motor"),
        Rung([Contact("XIC", "Fotocelula"), Contact("XIO", "Fim_Curso_Aberto"), Contact("XIO", "Motor_Desce"),
              Contact("XIO", "Motor_Sobe")], [TimerBox("TON", "Espera_Reversao", 600)],
             "Veiculo detectado: espera o portao parar antes de reabrir"),
        Rung([Contact("XIO", "Fim_Curso_Aberto"), Contact("XIO", "Fim_Curso_Fechado")],
             [Coil("OTE", "Lampada_Entreaberto")], "Sinalizacao"),
        Rung([Contact("XIC", "Fim_Curso_Aberto")], [Coil("OTE", "Lampada_Aberto")]),
        Rung([Contact("XIC", "Fim_Curso_Fechado")], [Coil("OTE", "Lampada_Fechado")]),
    ]
    return p


def main() -> int:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    targets = {"demo/demonstracao.ladproj": demo, "combinational/portas_logicas.ladproj": combinational,
               "timers/temporizadores.ladproj": timers, "counters/contadores.ladproj": counters,
               "hardware/teste_reles.ladproj": relay_chase, "hardware/espelho_entradas.ladproj": input_mirror,
               "ambientes/silo.ladproj": silo, "ambientes/semaforo.ladproj": traffic_light,
               "ambientes/portao.ladproj": garage_door}
    for rel, make in targets.items():
        if not rel.startswith(prefix):
            continue
        project = make()
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
