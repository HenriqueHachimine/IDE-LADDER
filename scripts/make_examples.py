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
from ladderide.model.project import CompareBox, MathBox  # noqa: E402


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


def elevator() -> Project:
    p = env_project("elevador", "Elevador de 4 andares", (
        "Chamadas registradas nas lampadas (SET), posicao memorizada pelo ultimo sensor de andar, "
        "direcao mantida enquanto houver chamadas no mesmo sentido e parada em qualquer andar com "
        "chamada. A porta fica aberta 3 s; como nao ha sensor de porta, o TOF Porta_Fechando espera "
        "2,8 s (fechador leva 2,5 s) antes de liberar o motor."))
    p.symbols += [Symbol(f"Pos_{k + 1}", f"M0.{k}", f"ultimo andar visto: {k + 1}") for k in range(4)]
    p.symbols += [Symbol("Chamada_Acima", "M0.4", "ha chamada acima da posicao"),
                  Symbol("Chamada_Abaixo", "M0.5", "ha chamada abaixo da posicao"),
                  Symbol("Subindo", "M0.6", "sentido de viagem: subida"),
                  Symbol("Descendo", "M0.7", "sentido de viagem: descida"),
                  Symbol("Parar_Aqui", "M1.0", "cabine num andar com chamada"),
                  Symbol("Atendendo", "M1.1", "porta aberta atendendo o andar"),
                  Symbol("Tempo_Porta", "T0", "porta aberta 3 s"),
                  Symbol("Porta_Fechando", "T1", "TOF: porta ainda nao fechou (2,8 s)")]
    andar = [f"Andar_{k + 1}" for k in range(4)]
    lamp = [f"Lampada_{k + 1}" for k in range(4)]
    pos = [f"Pos_{k + 1}" for k in range(4)]

    def any_of(names):
        return [Parallel([[Contact("XIC", n)] for n in names])] if len(names) > 1 else [Contact("XIC", names[0])]

    rungs = []
    for k in range(4):
        rungs.append(Rung([Contact("XIC", f"Chamada_{k + 1}")], [Coil("OTL", lamp[k])],
                          "Registra as chamadas (a lampada e a memoria)" if k == 0 else ""))
    for k in range(4):
        rungs.append(Rung([Contact("XIC", andar[k])],
                          [Coil("OTL", pos[k])] + [Coil("OTU", pos[j]) for j in range(4) if j != k],
                          "Memoriza o ultimo andar visto" if k == 0 else ""))
    rungs.append(Rung([Parallel([[Contact("XIC", pos[k])] + any_of(lamp[k + 1:]) for k in range(3)])],
                      [Coil("OTE", "Chamada_Acima")], "Ha chamadas acima / abaixo da posicao"))
    rungs.append(Rung([Parallel([[Contact("XIC", pos[k])] + any_of(lamp[:k]) for k in range(3, 0, -1)])],
                      [Coil("OTE", "Chamada_Abaixo")]))
    rungs.append(Rung([Parallel([[Contact("XIC", andar[k]), Contact("XIC", lamp[k])] for k in range(4)])],
                      [Coil("OTE", "Parar_Aqui")], "Cabine num andar com chamada"))
    rungs.append(Rung([Contact("XIC", "Parar_Aqui"), Contact("XIO", "Motor_Sobe"), Contact("XIO", "Motor_Desce")],
                      [Coil("OTL", "Atendendo")], "Chegou: atende o andar"))
    rungs.append(Rung([Contact("XIC", "Atendendo")],
                      [Coil("OTE", "Abrir_Porta"), TimerBox("TON", "Tempo_Porta", 3000)], "Porta aberta por 3 s"))
    for k in range(4):
        rungs.append(Rung([Contact("XIC", "Atendendo"), Contact("XIC", andar[k])], [Coil("OTU", lamp[k])],
                          "Apaga a chamada atendida" if k == 0 else ""))
    rungs.append(Rung([Contact("XIC", "Tempo_Porta.DN")], [Coil("OTU", "Atendendo")]))
    rungs.append(Rung([Contact("XIC", "Abrir_Porta")], [TimerBox("TOF", "Porta_Fechando", 2800)],
                      "Sem sensor de porta: espera o fechador (2,5 s) com folga"))
    rungs.append(Rung([Contact("XIC", "Chamada_Acima"), Contact("XIO", "Descendo")], [Coil("OTL", "Subindo")],
                      "Sentido de viagem: mantem enquanto houver chamadas no mesmo sentido"))
    rungs.append(Rung([Contact("XIO", "Chamada_Acima")], [Coil("OTU", "Subindo")]))
    rungs.append(Rung([Contact("XIC", "Chamada_Abaixo"), Contact("XIO", "Subindo")], [Coil("OTL", "Descendo")]))
    rungs.append(Rung([Contact("XIO", "Chamada_Abaixo")], [Coil("OTU", "Descendo")]))
    rungs.append(Rung([Contact("XIC", "Subindo"), Contact("XIO", "Parar_Aqui"), Contact("XIO", "Atendendo"),
                       Contact("XIO", "Porta_Fechando.DN"), Contact("XIO", "Motor_Desce")],
                      [Coil("OTE", "Motor_Sobe")], "Motor com intertravamento e porta fechada"))
    rungs.append(Rung([Contact("XIC", "Descendo"), Contact("XIO", "Parar_Aqui"), Contact("XIO", "Atendendo"),
                       Contact("XIO", "Porta_Fechando.DN"), Contact("XIO", "Motor_Sobe")],
                      [Coil("OTE", "Motor_Desce")]))
    p.rungs = rungs
    return p


def bottle_line() -> Project:
    p = env_project("garrafas", "Linha de garrafas", (
        "Para a garrafa sob o bico e enche por tempo (RTO: pequena 2 s, grande 4 s a 0,25 L/s; retentivo "
        "para nao encher de novo depois de um STOP). Rejeita garrafa fora do nivel na inspecao. Conta 6 "
        "garrafas por caixa (CTU) e troca a caixa; a esteira de garrafas so anda com caixa posicionada."))
    p.symbols += [Symbol("Tempo_Pequena", "T0", "2 s = 0,5 L"), Symbol("Tempo_Grande", "T1", "4 s = 1 L"),
                  Symbol("Garrafas_Caixa", "C0", "6 garrafas por caixa"),
                  Symbol("Cheia", "M0.0", "garrafa sob o bico ja foi enchida")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Start")], [Contact("XIC", "Lampada_Run")]]), Contact("XIC", "Stop")],
             [Coil("OTE", "Lampada_Run")], "Liga/desliga (selo)"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Garrafa_No_Bico"), Contact("XIO", "Cheia"),
              Contact("XIO", "Seletor_Grande")], [TimerBox("RTO", "Tempo_Pequena", 2000)],
             "Tempo de enchimento conforme o tamanho"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Garrafa_No_Bico"), Contact("XIO", "Cheia"),
              Contact("XIC", "Seletor_Grande")], [TimerBox("RTO", "Tempo_Grande", 4000)]),
        Rung([Parallel([[Contact("XIC", "Tempo_Pequena.DN")], [Contact("XIC", "Tempo_Grande.DN")]])],
             [Coil("OTE", "Cheia")], "Garrafa cheia"),
        Rung([Contact("XIO", "Garrafa_No_Bico")], [ResetBox("Tempo_Pequena"), ResetBox("Tempo_Grande")],
             "Garrafa saiu: prepara a proxima"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Garrafa_No_Bico"), Contact("XIO", "Cheia")],
             [Coil("OTE", "Valvula_Enchimento")], "Enche"),
        Rung([Contact("XIC", "Lampada_Run"), Parallel([[Contact("XIO", "Garrafa_No_Bico")], [Contact("XIC", "Cheia")]]),
              Contact("XIC", "Caixa_Posicionada"), Contact("XIO", "Garrafas_Caixa.DN")],
             [Coil("OTE", "Esteira_Garrafas")], "Esteira: para para encher e sem caixa"),
        Rung([Contact("XIC", "Garrafa_Inspecao"), Contact("XIO", "Nivel_OK")], [Coil("OTE", "Rejeitor")],
             "Inspecao: garrafa fora do nivel vai para o refugo"),
        Rung([Contact("XIC", "Garrafa_Na_Caixa")], [CounterBox("CTU", "Garrafas_Caixa", 6)],
             "Conta as garrafas na caixa"),
        Rung([Contact("XIC", "Lampada_Run"),
              Parallel([[Contact("XIC", "Garrafas_Caixa.DN")], [Contact("XIO", "Caixa_Posicionada")]])],
             [Coil("OTE", "Esteira_Caixas")], "Caixa completa sai; a proxima vem ate o sensor"),
        Rung([Contact("XIO", "Caixa_Posicionada")], [ResetBox("Garrafas_Caixa")], "Caixa nova: zera a contagem"),
    ]
    return p


def air_compressors() -> Project:
    p = env_project("compressores", "Central de ar comprimido", (
        "O pressostato 1 chama o compressor lider e o 2 o reserva; o lider alterna a cada ciclo (pulso na "
        "subida do pressostato 1) para dividir o desgaste. O reserva so parte 2 s depois do lider (sem pico "
        "de corrente) e assume se o termico do outro desarmar. Dreno: 1,5 s a cada 30 s."))
    p.symbols += [Symbol("PE1_Anterior", "M0.0", "pressostato 1 na varredura anterior"),
                  Symbol("Pulso_PE1", "M0.1", "subida do pressostato 1 (uma varredura)"),
                  Symbol("Lider_2", "M0.2", "1 = compressor 2 e o lider"),
                  Symbol("Partida_Escalonada", "T0", "2 s entre as partidas"),
                  Symbol("Intervalo_Dreno", "T1", "30 s"), Symbol("Tempo_Dreno", "T2", "1,5 s")]

    def motor(me: str, other_trip: str, lead_when: str, comment: str = "") -> Rung:
        lag_when = "XIO" if lead_when == "XIC" else "XIC"
        return Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", f"Termico_{me}"),
                     Parallel([[Contact("XIC", "Pressostato_1"), Contact(lead_when, "Lider_2")],
                               [Contact("XIC", "Pressostato_2"), Contact(lag_when, "Lider_2"),
                                Contact("XIC", "Partida_Escalonada.DN")],
                               [Contact("XIC", "Pressostato_1"), Contact("XIO", other_trip)]])],
                    [Coil("OTE", f"Motor_{me}")], comment)

    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Start")], [Contact("XIC", "Lampada_Run")]]), Contact("XIC", "Stop")],
             [Coil("OTE", "Lampada_Run")], "Liga/desliga (selo)"),
        Rung([Contact("XIC", "Pressostato_1"), Contact("XIO", "PE1_Anterior")], [Coil("OTE", "Pulso_PE1")],
             "Pulso na subida do pressostato 1"),
        Rung([Parallel([[Contact("XIC", "Pulso_PE1"), Contact("XIO", "Lider_2")],
                        [Contact("XIO", "Pulso_PE1"), Contact("XIC", "Lider_2")]])],
             [Coil("OTE", "Lider_2")], "Alterna o lider a cada ciclo (flip-flop)"),
        Rung([Contact("XIC", "Pressostato_1")], [Coil("OTE", "PE1_Anterior")]),
        Rung([Parallel([[Contact("XIC", "Motor_1")], [Contact("XIC", "Motor_2")]])],
             [TimerBox("TON", "Partida_Escalonada", 2000)], "Reserva so parte 2 s depois do lider"),
        motor("1", "Termico_2", "XIO", "Compressores: lider pelo PE1, reserva pelo PE2, assume se o outro desarmar"),
        motor("2", "Termico_1", "XIC"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIO", "Tempo_Dreno.DN")],
             [TimerBox("TON", "Intervalo_Dreno", 30000)], "Dreno do condensado: 1,5 s a cada 30 s"),
        Rung([Contact("XIC", "Intervalo_Dreno.DN")],
             [Coil("OTE", "Valvula_Dreno"), TimerBox("TON", "Tempo_Dreno", 1500)]),
        Rung([Parallel([[Contact("XIO", "Termico_1")], [Contact("XIO", "Termico_2")]])],
             [Coil("OTE", "Lampada_Falha")], "Sinaliza termico desarmado"),
    ]
    return p


def batch_mixer() -> Project:
    p = env_project("misturador", "Misturador de batelada", (
        "Doses contadas pelos fluxometros (CTU 40 L de A, depois 30 L de B), agitacao e aquecimento ate "
        "o termostato, 5 s de mistura na temperatura e descarga ate o nivel baixo mais 2 s. Repete "
        "enquanto RUN estiver ligado."))
    p.symbols += [Symbol("Litros_A", "C0", "40 L do produto A"), Symbol("Litros_B", "C1", "30 L do produto B"),
                  Symbol("Temperatura_OK", "M0.0", "lote ja chegou a 40 degC"),
                  Symbol("Descarregando", "M0.1", "descarga do lote"),
                  Symbol("Tempo_Mistura", "T0", "5 s misturando na temperatura"),
                  Symbol("Fim_Descarga", "T1", "2 s depois do nivel baixo")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Start")], [Contact("XIC", "Lampada_Run")]]), Contact("XIC", "Stop")],
             [Coil("OTE", "Lampada_Run")], "Liga/desliga (selo)"),
        Rung([Contact("XIC", "Fluxometro_1")], [CounterBox("CTU", "Litros_A", 40)], "Dosagem pelos fluxometros"),
        Rung([Contact("XIC", "Fluxometro_2")], [CounterBox("CTU", "Litros_B", 30)]),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIO", "Litros_A.DN"), Contact("XIO", "Descarregando")],
             [Coil("OTE", "Bomba_1")], "Produto A, depois produto B"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Litros_A.DN"), Contact("XIO", "Litros_B.DN"),
              Contact("XIO", "Descarregando")], [Coil("OTE", "Bomba_2")]),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Litros_B.DN"), Contact("XIO", "Descarregando")],
             [Coil("OTE", "Misturador")], "Agita depois da dosagem"),
        Rung([Contact("XIC", "Misturador"), Contact("XIC", "Nivel_Baixo"), Contact("XIO", "Termostato")],
             [Coil("OTE", "Aquecedor")], "Aquece so com agitacao e resistencia coberta"),
        Rung([Contact("XIC", "Misturador"), Contact("XIC", "Termostato")], [Coil("OTL", "Temperatura_OK")]),
        Rung([Contact("XIC", "Misturador"), Contact("XIC", "Temperatura_OK")],
             [TimerBox("TON", "Tempo_Mistura", 5000)], "Mistura 5 s na temperatura"),
        Rung([Contact("XIC", "Tempo_Mistura.DN")], [Coil("OTL", "Descarregando")], "Descarrega o lote"),
        Rung([Contact("XIC", "Lampada_Run"), Contact("XIC", "Descarregando"), Contact("XIO", "Fim_Descarga.DN")],
             [Coil("OTE", "Bomba_Saida")]),
        Rung([Contact("XIC", "Descarregando"), Contact("XIO", "Nivel_Baixo")],
             [TimerBox("TON", "Fim_Descarga", 2000)], "Abaixo do nivel baixo restam ~10 L: mais 2 s e o tanque esvazia"),
        Rung([Contact("XIC", "Fim_Descarga.DN")],
             [Coil("OTU", "Descarregando"), Coil("OTU", "Temperatura_OK"), ResetBox("Litros_A"),
              ResetBox("Litros_B")], "Fim do lote: prepara o proximo"),
        Rung([Contact("XIC", "Nivel_Alto")], [Coil("OTE", "Lampada_Cheio")], "Sinalizacao"),
    ]
    return p


def star_delta() -> Project:
    p = env_project("estrela_triangulo", "Partida estrela-triangulo", (
        "Intertravamento e temporizacao: K1 com selo; K2 (estrela) por 5 s; tempo morto de 100 ms para o K2 "
        "abrir (os contatores levam 40 ms) e so entao K3 (triangulo). K2 e K3 se bloqueiam mutuamente. O rele "
        "termico (NF) derruba tudo e acende FALHA."))
    p.symbols += [Symbol("Tempo_Estrela", "T0", "5 s em estrela"),
                  Symbol("Tempo_Morto", "T1", "100 ms entre abrir K2 e fechar K3")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Liga")], [Contact("XIC", "Contator_K1")]]), Contact("XIC", "Desliga"),
              Contact("XIC", "Rele_Termico")], [Coil("OTE", "Contator_K1")], "K1 com selo; DESLIGA e termico sao NF"),
        Rung([Contact("XIC", "Contator_K1")], [TimerBox("TON", "Tempo_Estrela", 5000)], "Tempo em estrela"),
        Rung([Contact("XIC", "Contator_K1"), Contact("XIO", "Tempo_Estrela.DN"), Contact("XIO", "Contator_K3_Triangulo")],
             [Coil("OTE", "Contator_K2_Estrela")], "Estrela, intertravada com o triangulo"),
        Rung([Contact("XIC", "Tempo_Estrela.DN")], [TimerBox("TON", "Tempo_Morto", 100)],
             "Tempo morto: o K2 abre em 40 ms (arco) antes de o K3 fechar"),
        Rung([Contact("XIC", "Contator_K1"), Contact("XIC", "Tempo_Morto.DN"), Contact("XIO", "Contator_K2_Estrela")],
             [Coil("OTE", "Contator_K3_Triangulo")], "Triangulo, intertravado com a estrela"),
        Rung([Contact("XIC", "Contator_K3_Triangulo")], [Coil("OTE", "Lampada_Ligado")], "Sinalizacao"),
        Rung([Contact("XIO", "Rele_Termico")], [Coil("OTE", "Lampada_Falha")]),
    ]
    return p


def two_hand_press() -> Project:
    p = env_project("prensa", "Prensa com comando bimanual", (
        "Logica de seguranca: os dois botoes precisam ser acionados em ate 0,5 s (T0 conta desde o primeiro), "
        "mantidos durante a descida e soltos antes do proximo golpe (anti-repeticao, M0.0). Soltar uma mao, "
        "chegar ao PMI ou interromper a cortina faz o martelo subir."))
    p.symbols += [Symbol("Rearmado", "M0.0", "os dois botoes foram soltos desde o ultimo golpe"),
                  Symbol("Ciclo", "M0.1", "golpe em andamento (descida)"),
                  Symbol("Retorno", "M0.2", "martelo voltando ao PMS"),
                  Symbol("Simultaneidade", "T0", "0,5 s desde o primeiro botao")]
    both = [Contact("XIC", "Botao_Esquerdo"), Contact("XIC", "Botao_Direito")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Botao_Esquerdo")], [Contact("XIC", "Botao_Direito")]])],
             [TimerBox("TON", "Simultaneidade", 500)], "Conta o tempo desde que a primeira mao apertou"),
        Rung([Contact("XIO", "Botao_Esquerdo"), Contact("XIO", "Botao_Direito")], [Coil("OTL", "Rearmado")],
             "Anti-repeticao: so rearma com as duas maos soltas"),
        Rung([*both, Contact("XIO", "Simultaneidade.DN"), Contact("XIC", "Rearmado"), Contact("XIC", "PMS"),
              Contact("XIC", "Cortina_Luz"), Contact("XIC", "Emergencia"), Contact("XIO", "Retorno")],
             [Coil("OTL", "Ciclo"), Coil("OTU", "Rearmado")], "Inicio do golpe: simultaneo, rearmado e no PMS"),
        Rung([Contact("XIC", "Ciclo"),
              Parallel([[Contact("XIC", "PMI")], [Contact("XIO", "Botao_Esquerdo")], [Contact("XIO", "Botao_Direito")],
                        [Contact("XIO", "Cortina_Luz")], [Contact("XIO", "Emergencia")]])],
             [Coil("OTL", "Retorno"), Coil("OTU", "Ciclo")], "Fim do golpe ou condicao insegura: volta"),
        Rung([Contact("XIC", "Ciclo"), *both, Contact("XIC", "Cortina_Luz"), Contact("XIC", "Emergencia"),
              Contact("XIO", "PMI")], [Coil("OTE", "Valvula_Desce")], "Desce so com as duas maos e zona livre"),
        Rung([Contact("XIC", "Retorno"), Contact("XIC", "Emergencia"), Contact("XIO", "PMS")],
             [Coil("OTE", "Valvula_Sobe")], "Sobe ate o PMS"),
        Rung([Contact("XIC", "Retorno"), Contact("XIC", "PMS")], [Coil("OTU", "Retorno")]),
        Rung([Contact("XIC", "PMS"), Contact("XIC", "Rearmado"), Contact("XIC", "Cortina_Luz"),
              Contact("XIC", "Emergencia"), Contact("XIO", "Ciclo")], [Coil("OTE", "Lampada_Pronta")],
             "Pronta para o proximo golpe"),
    ]
    return p


def drill() -> Project:
    p = env_project("furadeira", "Furadeira automatica", (
        "Sequencia por etapas (estilo Grafcet): cada etapa e um bit M ligado com OTL e desligado pela "
        "transicao seguinte (OTU). E1 fixa, E2 desce com o mandril, E3 espera 0,5 s no fundo, E4 sobe, E5 "
        "solta e espera 0,6 s, E6 ejeta, E7 recua o ejetor. As saidas sao combinacoes das etapas; a emergencia "
        "corta mandril, descida e ejetor, mas mantem a peca presa."))
    steps = [("Etapa_1_Fixar", "M0.1"), ("Etapa_2_Descer", "M0.2"), ("Etapa_3_Fundo", "M0.3"),
             ("Etapa_4_Subir", "M0.4"), ("Etapa_5_Soltar", "M0.5"), ("Etapa_6_Ejetar", "M0.6"),
             ("Etapa_7_Recuar", "M0.7")]
    p.symbols += [Symbol(n, a, "etapa da sequencia") for n, a in steps]
    p.symbols += [Symbol("Tempo_Fundo", "T0", "0,5 s no fundo do furo"),
                  Symbol("Tempo_Soltar", "T1", "0,6 s para o fixador recuar (sem sensor)")]
    e = [n for n, _ in steps]

    def go(cond, frm, to, comment=""):
        return Rung([Contact("XIC", frm), *cond], [Coil("OTL", to), Coil("OTU", frm)], comment)

    p.rungs = [
        Rung([Contact("XIC", "Partida"), Contact("XIC", "Emergencia"), Contact("XIC", "Peca_Presente"),
              Contact("XIC", "Broca_Em_Cima"), Contact("XIC", "Ejetor_Recuado"), *[Contact("XIO", n) for n in e]],
             [Coil("OTL", e[0])], "Etapa inicial: partida com a maquina em repouso"),
        go([Contact("XIC", "Fixador_Avancado")], e[0], e[1], "Transicoes: sensor de fim de curso de cada cilindro"),
        go([Contact("XIC", "Broca_Embaixo")], e[1], e[2]),
        Rung([Contact("XIC", e[2])], [TimerBox("TON", "Tempo_Fundo", 500)], "Espera no fundo (tira a rebarba)"),
        go([Contact("XIC", "Tempo_Fundo.DN")], e[2], e[3]),
        go([Contact("XIC", "Broca_Em_Cima")], e[3], e[4]),
        Rung([Contact("XIC", e[4])], [TimerBox("TON", "Tempo_Soltar", 600)], "Fixador recua pela mola"),
        go([Contact("XIC", "Tempo_Soltar.DN")], e[4], e[5]),
        go([Contact("XIC", "Ejetor_Avancado")], e[5], e[6]),
        Rung([Contact("XIC", e[6]), Contact("XIC", "Ejetor_Recuado")], [Coil("OTU", e[6])], "Fim do ciclo"),
        Rung([Parallel([[Contact("XIC", e[k])] for k in range(4)])], [Coil("OTE", "Fixador")],
             "Saidas a partir das etapas"),
        Rung([Parallel([[Contact("XIC", e[k])] for k in (1, 2, 3)]), Contact("XIC", "Emergencia")],
             [Coil("OTE", "Motor_Mandril")]),
        Rung([Contact("XIC", e[1]), Contact("XIC", "Emergencia")], [Coil("OTE", "Broca_Desce")]),
        Rung([Contact("XIC", e[3])], [Coil("OTE", "Broca_Sobe")]),
        Rung([Contact("XIC", e[5]), Contact("XIC", "Emergencia")], [Coil("OTE", "Ejetor")]),
        Rung([Parallel([[Contact("XIC", n)] for n in e])], [Coil("OTE", "Lampada_Ciclo")]),
    ]
    return p


def level_crossing() -> Project:
    p = env_project("passagem_nivel", "Passagem de nivel", (
        "Memoria de sentido: o primeiro sensor de aproximacao que atua define de onde o trem vem (M0.0/M0.1). "
        "Quando o trem deixa a ilha, o alerta termina e o sensor do lado de saida passa a ser ignorado ate o "
        "trem passar por ele (M0.2-M0.5), senao ele seria confundido com um novo trem. Luzes alternadas pelo "
        "relogio S0.3, sino ate a cancela abaixar e 3 s de aviso antes de descer."))
    p.symbols += [Symbol("Vindo_Oeste", "M0.0", "trem chegando pelo oeste"),
                  Symbol("Vindo_Leste", "M0.1", "trem chegando pelo leste"),
                  Symbol("Ignora_Leste", "M0.2", "trem indo embora pelo leste"),
                  Symbol("Ignora_Oeste", "M0.3", "trem indo embora pelo oeste"),
                  Symbol("Viu_Leste", "M0.4", "o trem que vai embora chegou ao sensor leste"),
                  Symbol("Viu_Oeste", "M0.5", "o trem que vai embora chegou ao sensor oeste"),
                  Symbol("Trem_Na_Ilha", "M0.6", "o trem ja chegou a passagem"),
                  Symbol("Alerta", "M0.7", "passagem fechada para os carros"),
                  Symbol("Aviso", "T0", "3 s de luzes antes de a cancela descer")]
    p.rungs = [
        Rung([Contact("XIC", "Sensor_Oeste"), Contact("XIO", "Ignora_Oeste"), Contact("XIO", "Vindo_Leste")],
             [Coil("OTL", "Vindo_Oeste")], "O primeiro sensor que atua define o sentido"),
        Rung([Contact("XIC", "Sensor_Leste"), Contact("XIO", "Ignora_Leste"), Contact("XIO", "Vindo_Oeste")],
             [Coil("OTL", "Vindo_Leste")]),
        Rung([Parallel([[Contact("XIC", "Vindo_Oeste")], [Contact("XIC", "Vindo_Leste")]])], [Coil("OTE", "Alerta")]),
        Rung([Contact("XIC", "Alerta"), Contact("XIC", "Sensor_Ilha")], [Coil("OTL", "Trem_Na_Ilha")],
             "O trem chegou a passagem"),
        Rung([Contact("XIC", "Trem_Na_Ilha"), Contact("XIO", "Sensor_Ilha"), Contact("XIC", "Vindo_Oeste")],
             [Coil("OTL", "Ignora_Leste")], "Saiu da ilha: ignora o sensor do lado para onde ele vai"),
        Rung([Contact("XIC", "Trem_Na_Ilha"), Contact("XIO", "Sensor_Ilha"), Contact("XIC", "Vindo_Leste")],
             [Coil("OTL", "Ignora_Oeste")]),
        Rung([Contact("XIC", "Trem_Na_Ilha"), Contact("XIO", "Sensor_Ilha")],
             [Coil("OTU", "Vindo_Oeste"), Coil("OTU", "Vindo_Leste"), Coil("OTU", "Trem_Na_Ilha")],
             "Passagem livre: fim do alerta"),
        Rung([Contact("XIC", "Ignora_Leste"), Contact("XIC", "Sensor_Leste")], [Coil("OTL", "Viu_Leste")],
             "O trem que vai embora passa pelo sensor do outro lado"),
        Rung([Contact("XIC", "Viu_Leste"), Contact("XIO", "Sensor_Leste")],
             [Coil("OTU", "Ignora_Leste"), Coil("OTU", "Viu_Leste")], "e o libera quando termina de passar"),
        Rung([Contact("XIC", "Ignora_Oeste"), Contact("XIC", "Sensor_Oeste")], [Coil("OTL", "Viu_Oeste")]),
        Rung([Contact("XIC", "Viu_Oeste"), Contact("XIO", "Sensor_Oeste")],
             [Coil("OTU", "Ignora_Oeste"), Coil("OTU", "Viu_Oeste")]),
        Rung([Contact("XIC", "Alerta"), Contact("XIC", "S0.3")], [Coil("OTE", "Luz_Esquerda")],
             "Luzes alternadas pelo relogio de 1 s"),
        Rung([Contact("XIC", "Alerta"), Contact("XIO", "S0.3")], [Coil("OTE", "Luz_Direita")]),
        Rung([Contact("XIC", "Alerta"), Contact("XIO", "Cancela_Abaixada")], [Coil("OTE", "Sino")],
             "Sino ate a cancela abaixar"),
        Rung([Contact("XIC", "Alerta")], [TimerBox("TON", "Aviso", 3000)], "3 s de aviso"),
        Rung([Contact("XIC", "Alerta"), Contact("XIC", "Aviso.DN"), Contact("XIO", "Cancela_Abaixada")],
             [Coil("OTE", "Cancela_Abaixa")], "Cancela desce depois do aviso"),
        Rung([Contact("XIO", "Alerta"), Contact("XIO", "Cancela_Levantada")], [Coil("OTE", "Cancela_Levanta")],
             "e sobe quando o trem deixa a ilha"),
    ]
    return p


def parking() -> Project:
    p = env_project("estacionamento", "Estacionamento", (
        "Contagem com aritmetica: N1 (ocupadas) soma 1 quando um carro termina de passar pelo laco de entrada com a "
        "cancela aberta (borda de descida do laco) e subtrai 1 na saida. N0 = 12 - N1 vai para o painel. A cancela "
        "de entrada so abre com vaga (LES) e fica aberta ate o carro sair do laco, para nao descer sobre ele."))
    p.symbols += [Symbol("Vagas_Livres", "N0", "vagas livres (painel)"), Symbol("Ocupadas", "N1", "carros dentro"),
                  Symbol("Laco_E_Anterior", "M0.0", "laco de entrada na varredura anterior"),
                  Symbol("Laco_S_Anterior", "M0.1", "laco de saida na varredura anterior"),
                  Symbol("Abre_Entrada", "M0.2", "carro autorizado a entrar"),
                  Symbol("Abre_Saida", "M0.3", "carro autorizado a sair")]
    p.rungs = [
        Rung([Contact("XIC", "Botao_Ticket"), Contact("XIC", "Laco_Entrada"), CompareBox("LES", ["Ocupadas", "12"])],
             [Coil("OTL", "Abre_Entrada")], "Ticket com carro no laco e vaga disponivel"),
        Rung([Contact("XIO", "Laco_Entrada"), Contact("XIC", "Laco_E_Anterior"), Contact("XIC", "Abre_Entrada")],
             [MathBox("ADD", ["Ocupadas", "1", "Ocupadas"]), Coil("OTU", "Abre_Entrada")],
             "O carro terminou de passar: conta e fecha"),
        Rung([Contact("XIC", "Laco_Entrada")], [Coil("OTE", "Laco_E_Anterior")]),
        Rung([Contact("XIC", "Cartao_Validado"), Contact("XIC", "Laco_Saida")], [Coil("OTL", "Abre_Saida")],
             "Cartao validado com carro no laco de saida"),
        Rung([Contact("XIO", "Laco_Saida"), Contact("XIC", "Laco_S_Anterior"), Contact("XIC", "Abre_Saida")],
             [MathBox("SUB", ["Ocupadas", "1", "Ocupadas"]), Coil("OTU", "Abre_Saida")]),
        Rung([Contact("XIC", "Laco_Saida")], [Coil("OTE", "Laco_S_Anterior")]),
        Rung([Contact("XIC", "Zerar_Contagem")], [MathBox("MOV", ["0", "Ocupadas"])], "Manutencao: patio vazio"),
        Rung([], [MathBox("SUB", ["12", "Ocupadas", "Vagas_Livres"])], "Vagas livres no painel"),
        Rung([CompareBox("LES", ["Ocupadas", "12"])], [Coil("OTE", "Painel_Livre")]),
        Rung([CompareBox("GEQ", ["Ocupadas", "12"])], [Coil("OTE", "Painel_Lotado")]),
        Rung([Contact("XIC", "Abre_Entrada")], [Coil("OTE", "Cancela_Entrada")]),
        Rung([Contact("XIC", "Abre_Saida")], [Coil("OTE", "Cancela_Saida")]),
    ]
    return p


def sorter() -> Project:
    p = env_project("seletor_pecas", "Separacao de pecas", (
        "Registrador de deslocamento: a cada pulso do encoder (borda de subida) N0 e N1 sao multiplicados por 2 "
        "(deslocam um bit) e o bit 0 recebe o que a inspecao ve agora (metal em N0, alta em N1). O bit k "
        "corresponde a peca que esta k passos depois da inspecao: o desviador A testa o bit 3 de N0 (MEQ com "
        "mascara 8) e o B o bit 6 de N1 (mascara 64). Subtrair 128 mantem so 7 bits."))
    p.symbols += [Symbol("Reg_Metal", "N0", "bit k = peca metalica k passos depois da inspecao"),
                  Symbol("Reg_Alta", "N1", "bit k = peca plastica alta k passos depois da inspecao"),
                  Symbol("Encoder_Anterior", "M0.0", "encoder na varredura anterior"),
                  Symbol("Pulso", "M0.1", "borda de subida do encoder (uma varredura)")]
    p.rungs = [
        Rung([Contact("XIC", "Liga")], [Coil("OTE", "Motor_Esteira"), Coil("OTE", "Lampada_Run")], "Esteira"),
        Rung([Contact("XIC", "Encoder"), Contact("XIO", "Encoder_Anterior")], [Coil("OTE", "Pulso")],
             "Um pulso por passo da esteira"),
        Rung([Contact("XIC", "Encoder")], [Coil("OTE", "Encoder_Anterior")]),
        Rung([Contact("XIC", "Pulso")], [MathBox("MUL", ["Reg_Metal", "2", "Reg_Metal"]),
                                         MathBox("MUL", ["Reg_Alta", "2", "Reg_Alta"])],
             "Desloca: cada peca anda um bit"),
        Rung([Contact("XIC", "Pulso"), Contact("XIC", "Sensor_Metal")], [MathBox("ADD", ["Reg_Metal", "1", "Reg_Metal"])],
             "Bit 0 = peca que esta na inspecao agora"),
        Rung([Contact("XIC", "Pulso"), Contact("XIC", "Sensor_Altura")], [MathBox("ADD", ["Reg_Alta", "1", "Reg_Alta"])]),
        Rung([CompareBox("GEQ", ["Reg_Metal", "128"])], [MathBox("SUB", ["Reg_Metal", "128", "Reg_Metal"])],
             "Descarta o que passou do ultimo desviador"),
        Rung([CompareBox("GEQ", ["Reg_Alta", "128"])], [MathBox("SUB", ["Reg_Alta", "128", "Reg_Alta"])]),
        Rung([Contact("XIC", "Encoder"), CompareBox("MEQ", ["Reg_Metal", "8", "8"])], [Coil("OTE", "Desviador_A")],
             "Peca metalica 3 passos depois: desvia durante meio passo"),
        Rung([Contact("XIC", "Encoder"), CompareBox("MEQ", ["Reg_Alta", "64", "64"])], [Coil("OTE", "Desviador_B")],
             "Peca alta 6 passos depois"),
    ]
    return p


def gas_detection() -> Project:
    p = env_project("detector_gas", "Deteccao de gas 2 de 3", (
        "Votacao 2 de 3 em logica combinacional (tres ramos em paralelo) e gestao de alarme: o disparo fica "
        "travado (OTL), a sirene toca ate RECONHECER, a lampada pisca enquanto nao reconhecido e fica fixa depois, "
        "e a valvula so reabre com REARMAR quando menos de 2 detectores estiverem em alarme. Um detector sozinho so "
        "liga o exaustor (pre-alarme); discordancia por 10 s acende FALHA DE DETECTOR."))
    p.symbols += [Symbol("Voto_2de3", "M0.0", "dois ou mais detectores em alarme"),
                  Symbol("Disparo", "M0.1", "disparo travado ate o rearme"),
                  Symbol("Reconhecido", "M0.2", "alarme reconhecido pelo operador"),
                  Symbol("Discordancia", "T0", "10 s com detectores discordando"),
                  Symbol("Sem_Fluxo", "T1", "4 s com o exaustor ligado e sem fluxo")]
    d = ["Detector_1", "Detector_2", "Detector_3"]
    any_det = Parallel([[Contact("XIC", n)] for n in d])
    p.rungs = [
        Rung([Parallel([[Contact("XIC", d[0]), Contact("XIC", d[1])], [Contact("XIC", d[0]), Contact("XIC", d[2])],
                        [Contact("XIC", d[1]), Contact("XIC", d[2])]])], [Coil("OTE", "Voto_2de3")],
             "Votacao 2 de 3"),
        Rung([Contact("XIC", "Voto_2de3"), Contact("XIO", "Disparo")], [Coil("OTL", "Disparo"), Coil("OTU", "Reconhecido")],
             "Novo disparo: trava e pede reconhecimento"),
        Rung([Contact("XIC", "Reconhecer"), Contact("XIC", "Disparo")], [Coil("OTL", "Reconhecido")]),
        Rung([Contact("XIC", "Rearmar"), Contact("XIO", "Voto_2de3"), Contact("XIC", "Disparo")],
             [Coil("OTU", "Disparo"), Coil("OTU", "Reconhecido")], "Rearme so com o gas abaixo do alarme"),
        Rung([Contact("XIO", "Disparo")], [Coil("OTE", "Valvula_Gas")], "Valvula energizada para abrir (falha segura)"),
        Rung([Parallel([[Contact("XIC", "Disparo")], [Parallel([[Contact("XIC", n)] for n in d])]])],
             [Coil("OTE", "Exaustor")], "Exaustor no pre-alarme (um detector) e no disparo"),
        Rung([Contact("XIC", "Disparo"), Contact("XIO", "Reconhecido")], [Coil("OTE", "Sirene")]),
        Rung([Parallel([[Contact("XIC", "Disparo"), Contact("XIO", "Reconhecido"), Contact("XIC", "S0.3")],
                        [Contact("XIC", "Disparo"), Contact("XIC", "Reconhecido")], [Contact("XIC", "Teste_Lampadas")]])],
             [Coil("OTE", "Luz_Alarme")], "Pisca sem reconhecer, fixa depois"),
        Rung([Parallel([[any_det, Contact("XIO", "Voto_2de3")],
                        [Contact("XIC", "Voto_2de3"),
                         Parallel([[Contact("XIO", n)] for n in d])]])],
             [TimerBox("TON", "Discordancia", 10000)], "Um detector diferente dos outros por 10 s"),
        Rung([Parallel([[Contact("XIC", "Discordancia.DN")], [Contact("XIC", "Teste_Lampadas")]])],
             [Coil("OTE", "Luz_Falha_Detector")]),
        Rung([Contact("XIC", "Exaustor"), Contact("XIO", "Fluxo_Exaustao")], [TimerBox("TON", "Sem_Fluxo", 4000)],
             "Exaustor sem fluxo no duto"),
        Rung([Parallel([[Contact("XIC", "Sem_Fluxo.DN")], [Contact("XIC", "Teste_Lampadas")]])],
             [Coil("OTE", "Luz_Falha_Exaustor")]),
    ]
    return p


def scale() -> Project:
    p = env_project("balanca", "Dosagem por balanca", (
        "Aritmetica com setpoint: a balanca escreve o peso (N0) e o alvo (N1). Grossa ate N1-200, fina ate "
        "N1-Preacao. Com o peso estavel, Erro = Peso - Setpoint e Preacao += Erro (corte antecipado adaptativo, "
        "limitado de 0 a 60 g). OK se o erro estiver dentro de +-2% (LIM); depois de 1 s a esteira troca o "
        "recipiente."))
    p.symbols += [Symbol("Peso", "N0", "peso na balanca (g), escrito pela balanca"),
                  Symbol("Setpoint", "N1", "alvo (g), escrito pela balanca"),
                  Symbol("Corte_Grossa", "N2", "Setpoint - 200"), Symbol("Preacao", "N3", "produto ainda no ar (g)"),
                  Symbol("Corte_Fina", "N4", "Setpoint - Preacao"), Symbol("Erro", "N5", "Peso final - Setpoint"),
                  Symbol("Tolerancia", "N6", "2% do setpoint"), Symbol("Tolerancia_Neg", "N7", "-2% do setpoint"),
                  Symbol("Automatico", "M0.0", "ciclo automatico ligado"), Symbol("Dosando", "M0.1", "enchendo"),
                  Symbol("Pesado", "M0.2", "recipiente pesado e avaliado"), Symbol("Exibe", "T0", "1 s mostrando o resultado")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Partida")], [Contact("XIC", "Automatico")]]), Contact("XIC", "Parada")],
             [Coil("OTE", "Automatico")], "Liga/desliga (selo); PARADA e NF"),
        Rung([Contact("XIC", "S0.0")], [MathBox("MOV", ["8", "Preacao"])], "Primeira varredura: corte inicial de 8 g"),
        Rung([], [MathBox("SUB", ["Setpoint", "200", "Corte_Grossa"]), MathBox("SUB", ["Setpoint", "Preacao", "Corte_Fina"]),
                  MathBox("DIV", ["Setpoint", "50", "Tolerancia"]), MathBox("NEG", ["Tolerancia", "Tolerancia_Neg"])],
             "Pontos de corte e tolerancia"),
        Rung([Contact("XIC", "Automatico"), Contact("XIC", "Recipiente_Posicionado"), Contact("XIC", "Peso_Estavel"),
              Contact("XIO", "Pesado"), Contact("XIO", "Dosando"), CompareBox("LES", ["Peso", "5"])],
             [Coil("OTL", "Dosando")], "Recipiente vazio parado sob o bico"),
        Rung([Contact("XIC", "Dosando"), Contact("XIC", "Automatico"), CompareBox("LES", ["Peso", "Corte_Grossa"])],
             [Coil("OTE", "Valvula_Grossa")], "Grossa ate 200 g antes do alvo"),
        Rung([Contact("XIC", "Dosando"), Contact("XIC", "Automatico"), CompareBox("LES", ["Peso", "Corte_Fina"])],
             [Coil("OTE", "Valvula_Fina")], "Fina ate o corte antecipado"),
        Rung([Contact("XIC", "Dosando"), CompareBox("GEQ", ["Peso", "Corte_Fina"]), Contact("XIC", "Peso_Estavel")],
             [MathBox("SUB", ["Peso", "Setpoint", "Erro"]), MathBox("ADD", ["Preacao", "Erro", "Preacao"]),
              Coil("OTL", "Pesado"), Coil("OTU", "Dosando")], "Produto assentado: mede o erro e corrige o corte"),
        Rung([CompareBox("LES", ["Preacao", "0"])], [MathBox("MOV", ["0", "Preacao"])], "Corte entre 0 e 60 g"),
        Rung([CompareBox("GRT", ["Preacao", "60"])], [MathBox("MOV", ["60", "Preacao"])]),
        Rung([Contact("XIC", "Pesado"), CompareBox("LIM", ["Tolerancia_Neg", "Erro", "Tolerancia"])],
             [Coil("OTE", "Lampada_OK")], "Dentro de +-2%"),
        Rung([Contact("XIC", "Pesado"), Contact("XIO", "Lampada_OK")], [Coil("OTE", "Lampada_Rejeito")]),
        Rung([Contact("XIC", "Pesado")], [TimerBox("TON", "Exibe", 1000)]),
        Rung([Contact("XIC", "Automatico"), Contact("XIO", "Dosando"),
              Parallel([[Contact("XIC", "Exibe.DN")], [Contact("XIO", "Recipiente_Posicionado")]])],
             [Coil("OTE", "Esteira")], "Troca o recipiente"),
        Rung([Contact("XIO", "Recipiente_Posicionado")], [Coil("OTU", "Pesado")], "O recipiente saiu"),
    ]
    return p


def numeric_blocks() -> Project:
    p = Project(name="Blocos numericos", version="1.0.0", description=(
        "Contagem de pecas em lotes de 6 usando os blocos de comparacao (EQU, NEQ, LES, GRT, LEQ, GEQ, LIM, "
        "MEQ) e de matematica (ADD, SUB, MUL, DIV, SQR, NEG, TOD, FRD). Os resultados ficam nos "
        "registradores N, vistos no monitor de variaveis."))
    p.symbols = [
        Symbol("Sensor_Peca", "I0.0", "Sensor de passagem de peca"),
        Symbol("Zera", "I0.1", "Botao para zerar a contagem"),
        Symbol("Liga", "I0.2", "Chave liga esteira"),
        Symbol("Esteira", "Q0.0", "Motor da esteira (para com 5 lotes)"),
        Symbol("Lote_Fechado", "Q0.1", "Lote de 6 pecas completo"),
        Symbol("Inicio_Lote", "Q0.2", "Primeiras pecas do lote (1 a 3)"),
        Symbol("Meta", "Q0.3", "5 lotes ou mais"),
        Symbol("Dois_Botoes", "Q0.4", "I0.4 e I0.5 juntos (MEQ com mascara)"),
        Symbol("Erro_BCD", "Q0.5", "TOD seguido de FRD nao devolveu o valor (nunca deve ligar)"),
        Symbol("Pecas", "C0", "CTU - pecas contadas"),
        Symbol("Lotes", "N0", "Lotes completos = Pecas / 6"),
        Symbol("Pecas_Lotes", "N1", "Pecas nos lotes completos = Lotes x 6"),
        Symbol("Resto", "N2", "Pecas do lote atual = Pecas - Pecas_Lotes"),
        Symbol("Raiz", "N3", "Raiz quadrada da contagem"),
        Symbol("Falta", "N4", "-Resto (negativo: pecas ja colocadas no lote)"),
        Symbol("Pecas_BCD", "N5", "Contagem em BCD (para um display)"),
        Symbol("Pecas_Volta", "N6", "BCD convertido de volta para inteiro"),
        Symbol("Proximo_Lote", "N7", "Numero do proximo lote = Lotes + 1"),
    ]
    p.rungs = [
        Rung([Contact("XIC", "Sensor_Peca")], [CounterBox("CTU", "Pecas", 1000)], "Conta pecas"),
        Rung([Contact("XIC", "Zera")], [ResetBox("Pecas")], "Zera a contagem"),
        Rung([], [MathBox("DIV", ["Pecas.ACC", "6", "Lotes"]), MathBox("MUL", ["Lotes", "6", "Pecas_Lotes"]),
                  MathBox("SUB", ["Pecas.ACC", "Pecas_Lotes", "Resto"]), MathBox("ADD", ["Lotes", "1", "Proximo_Lote"])],
             "Lotes e resto: DIV, MUL, SUB e ADD a cada varredura"),
        Rung([CompareBox("EQU", ["Resto", "0"]), CompareBox("GRT", ["Pecas.ACC", "0"])], [Coil("OTE", "Lote_Fechado")],
             "Lote fechado: resto zero com alguma peca contada"),
        Rung([Contact("XIC", "Liga"), CompareBox("LES", ["Lotes", "5"])], [Coil("OTE", "Esteira")],
             "Esteira liga com a chave enquanto houver menos de 5 lotes"),
        Rung([CompareBox("LIM", ["1", "Resto", "3"])], [Coil("OTE", "Inicio_Lote")], "Resto entre 1 e 3"),
        Rung([CompareBox("GEQ", ["Lotes", "5"])], [Coil("OTE", "Meta")], "Meta de 5 lotes"),
        Rung([CompareBox("MEQ", ["IW0", "0x30", "0x30"])], [Coil("OTE", "Dois_Botoes")],
             "Mascara 0x30: so I0.4 e I0.5 importam"),
        Rung([], [MathBox("SQR", ["Pecas.ACC", "Raiz"]), MathBox("NEG", ["Resto", "Falta"])], "Raiz e sinal"),
        Rung([], [MathBox("TOD", ["Pecas.ACC", "Pecas_BCD"]), MathBox("FRD", ["Pecas_BCD", "Pecas_Volta"])],
             "Conversao para BCD e de volta"),
        Rung([Parallel([[CompareBox("NEQ", ["Pecas_Volta", "Pecas.ACC"])], [CompareBox("LEQ", ["Raiz", "-1"])]])],
             [Coil("OTE", "Erro_BCD")], "Conferencia: nunca deve ligar"),
    ]
    return p


def factoryio_conveyor() -> Project:
    """Cena do Factory IO: emissor -> esteira -> removedor, com sensores na entrada e na saida."""
    p = Project(name="Factory IO - esteira com lote", version="1.0.0", description=(
        "Exemplo para o Factory IO (driver Modbus TCP/IP Server, ver docs/factory-io.md). Partida liga o "
        "sistema (selo), o emissor solta caixas com a entrada livre, a esteira leva ate a saida e cada caixa "
        "e contada. Com 5 caixas a esteira para e acende Lote_Completo; Partida comeca outro lote. Caixa "
        "parada na saida por 4 s com a esteira ligada e atolamento: para tudo e a lampada pisca ate Partida. "
        "Parada e NF (Stop do Factory IO): sem conexao a entrada le 0 e o sistema desliga."))
    p.symbols = [
        Symbol("Partida", "I0.0", "Input 0 - Start Button (NA)"),
        Symbol("Parada", "I0.1", "Input 1 - Stop Button (NF: le 1 quando solto)"),
        Symbol("Sensor_Entrada", "I0.2", "Input 2 - Diffuse Sensor no inicio da esteira"),
        Symbol("Sensor_Saida", "I0.3", "Input 3 - Diffuse Sensor no fim da esteira"),
        Symbol("Esteira", "Q0.0", "Coil 0 - Belt Conveyor"),
        Symbol("Emissor", "Q0.1", "Coil 1 - Emitter (caixas)"),
        Symbol("Luz_Partida", "Q0.2", "Coil 2 - Start Button Light (sistema ligado)"),
        Symbol("Luz_Lote", "Q0.3", "Coil 3 - Light Indicator (lote completo; pisca no atolamento)"),
        Symbol("Ligado", "M0.0", "Sistema ligado (selo)"),
        Symbol("Atolado", "M0.1", "Alarme de atolamento memorizado"),
        Symbol("Tempo_Atolamento", "T0", "TON 4 s com caixa parada no sensor de saida"),
        Symbol("Caixas", "C0", "CTU 5 caixas por lote"),
    ]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Partida")], [Contact("XIC", "Ligado")]]), Contact("XIC", "Parada")],
             [Coil("OTE", "Ligado")], "Selo: Partida liga, Parada (NF) desliga"),
        Rung([Contact("XIC", "Ligado")], [Coil("OTE", "Luz_Partida")], "Lampada do botao Partida"),
        Rung([Contact("XIC", "Partida")], [ResetBox("Caixas"), Coil("OTU", "Atolado")],
             "Partida comeca um lote novo e reconhece o alarme"),
        Rung([Contact("XIC", "Ligado"), Contact("XIO", "Caixas.DN"), Contact("XIO", "Atolado")],
             [Coil("OTE", "Esteira")], "Esteira anda ate completar o lote"),
        Rung([Contact("XIC", "Esteira"), Contact("XIO", "Sensor_Entrada")], [Coil("OTE", "Emissor")],
             "Nova caixa so com a entrada livre"),
        Rung([Contact("XIC", "Esteira"), Contact("XIC", "Sensor_Saida")], [CounterBox("CTU", "Caixas", 5)],
             "Conta as caixas que chegam a saida"),
        Rung([Contact("XIC", "Esteira"), Contact("XIC", "Sensor_Saida")],
             [TimerBox("TON", "Tempo_Atolamento", 4000)], "Caixa parada na saida com a esteira ligada"),
        Rung([Contact("XIC", "Tempo_Atolamento.DN")], [Coil("OTL", "Atolado")], "Memoriza o atolamento"),
        Rung([Parallel([[Contact("XIC", "Caixas.DN")], [Contact("XIC", "Atolado"), Contact("XIC", "S0.3")]])],
             [Coil("OTE", "Luz_Lote")], "Lote completo (fixa) ou atolamento (pisca 1 Hz)"),
    ]
    return p


def main() -> int:
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    targets = {"demo/demonstracao.ladproj": demo, "combinational/portas_logicas.ladproj": combinational,
               "timers/temporizadores.ladproj": timers, "counters/contadores.ladproj": counters,
               "hardware/teste_reles.ladproj": relay_chase, "hardware/espelho_entradas.ladproj": input_mirror,
               "ambientes/silo.ladproj": silo, "ambientes/semaforo.ladproj": traffic_light,
               "ambientes/portao.ladproj": garage_door, "ambientes/elevador.ladproj": elevator,
               "ambientes/garrafas.ladproj": bottle_line, "ambientes/compressores.ladproj": air_compressors,
               "ambientes/misturador.ladproj": batch_mixer, "math/blocos_numericos.ladproj": numeric_blocks,
               "factoryio/esteira_lote.ladproj": factoryio_conveyor,
               "ambientes/estrela_triangulo.ladproj": star_delta, "ambientes/prensa.ladproj": two_hand_press,
               "ambientes/furadeira.ladproj": drill, "ambientes/passagem_nivel.ladproj": level_crossing,
               "ambientes/estacionamento.ladproj": parking, "ambientes/seletor_pecas.ladproj": sorter,
               "ambientes/detector_gas.ladproj": gas_detection, "ambientes/balanca.ladproj": scale}
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
