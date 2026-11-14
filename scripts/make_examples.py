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
    p = env_project("estrela_triangulo", "Partida estrela-triangulo reversivel", (
        "Intertravamentos e tempos mortos: o ultimo botao de sentido vence (OTL/OTU). K1 e K4 se bloqueiam, so "
        "fecham com o motor parado (I0.6) e depois de 150 ms com os dois abertos (os contatores abrem em 40 ms). "
        "A estrela dura ate o sensor de rotacao (I0.5); o K3 so fecha 100 ms depois de o K2 abrir. Termico e "
        "falta de fase (NF) param tudo e acendem FALHA; partida que nao chega a rotacao em 12 s e abortada."))
    p.symbols += [Symbol("Pedido_Horario", "M0.0", "ultimo pedido: sentido horario"),
                  Symbol("Pedido_Anti", "M0.1", "ultimo pedido: sentido anti-horario"),
                  Symbol("Falha", "M0.2", "termico desarmado ou falta de fase"),
                  Symbol("Em_Linha", "M0.3", "K1 ou K4 ligado"),
                  Symbol("Em_Triangulo", "M0.4", "motor ja atingiu a rotacao em estrela"),
                  Symbol("Linha_Livre", "T0", "150 ms com K1 e K4 abertos"),
                  Symbol("Tempo_Morto", "T1", "100 ms entre abrir K2 e fechar K3"),
                  Symbol("Tempo_Estrela", "T2", "12 s maximo em estrela")]
    p.rungs = [
        Rung([Parallel([[Contact("XIO", "Rele_Termico")], [Contact("XIO", "Rele_Falta_Fase")]])],
             [Coil("OTE", "Falha")], "Reles NF: 0 = desarmado (termico) ou sem uma fase"),
        Rung([Contact("XIC", "Falha")], [Coil("OTE", "Lampada_Falha")]),
        Rung([Contact("XIC", "Liga_Horario"), Contact("XIO", "Falha")],
             [Coil("OTL", "Pedido_Horario"), Coil("OTU", "Pedido_Anti")], "O ultimo botao de sentido vence"),
        Rung([Contact("XIC", "Liga_Anti_Horario"), Contact("XIO", "Falha")],
             [Coil("OTL", "Pedido_Anti"), Coil("OTU", "Pedido_Horario")]),
        Rung([Parallel([[Contact("XIO", "Desliga")], [Contact("XIC", "Falha")], [Contact("XIC", "Tempo_Estrela.DN")]])],
             [Coil("OTU", "Pedido_Horario"), Coil("OTU", "Pedido_Anti")],
             "Desliga (NF), falha ou partida que nao completou: para"),
        Rung([Contact("XIO", "K1_Horario"), Contact("XIO", "K4_Anti_Horario")], [TimerBox("TON", "Linha_Livre", 150)],
             "Tempo morto entre os contatores de linha"),
        Rung([Contact("XIC", "Pedido_Horario"), Contact("XIO", "K4_Anti_Horario"),
              Parallel([[Contact("XIC", "Motor_Parado"), Contact("XIC", "Linha_Livre.DN")], [Contact("XIC", "K1_Horario")]])],
             [Coil("OTE", "K1_Horario")], "K1: parte so com o motor parado; selo pelo proprio K1"),
        Rung([Contact("XIC", "Pedido_Anti"), Contact("XIO", "K1_Horario"),
              Parallel([[Contact("XIC", "Motor_Parado"), Contact("XIC", "Linha_Livre.DN")],
                        [Contact("XIC", "K4_Anti_Horario")]])],
             [Coil("OTE", "K4_Anti_Horario")], "K4: idem, intertravado com o K1"),
        Rung([Parallel([[Contact("XIC", "K1_Horario")], [Contact("XIC", "K4_Anti_Horario")]])], [Coil("OTE", "Em_Linha")]),
        Rung([Contact("XIC", "Em_Linha"), Contact("XIC", "Rotacao_Nominal")], [Coil("OTL", "Em_Triangulo")],
             "Passa para triangulo quando a estrela chega a 85% da rotacao"),
        Rung([Contact("XIO", "Em_Linha")], [Coil("OTU", "Em_Triangulo")]),
        Rung([Contact("XIC", "Em_Linha"), Contact("XIO", "Em_Triangulo"), Contact("XIO", "K3_Triangulo")],
             [Coil("OTE", "K2_Estrela")], "Estrela, intertravada com o triangulo"),
        Rung([Contact("XIC", "Em_Linha"), Contact("XIO", "Em_Triangulo")], [TimerBox("TON", "Tempo_Estrela", 12000)],
             "Partida que nao chega a rotacao em 12 s e abortada"),
        Rung([Contact("XIC", "Em_Triangulo"), Contact("XIO", "K2_Estrela")], [TimerBox("TON", "Tempo_Morto", 100)],
             "Tempo morto: o K2 abre em 40 ms antes de o K3 fechar"),
        Rung([Contact("XIC", "Em_Linha"), Contact("XIC", "Tempo_Morto.DN"), Contact("XIO", "K2_Estrela")],
             [Coil("OTE", "K3_Triangulo")], "Triangulo, intertravado com a estrela"),
        Rung([Contact("XIC", "K3_Triangulo")], [Coil("OTE", "Lampada_Ligado")], "Sinalizacao"),
    ]
    return p


def two_hand_press() -> Project:
    p = env_project("prensa", "Prensa hidraulica bimanual", (
        "Logica de seguranca: os dois botoes em ate 0,5 s (T0 conta desde o primeiro), mantidos durante a descida "
        "e soltos antes do proximo golpe (anti-repeticao). A descida liga DESCE e a valvula de seguranca juntas. "
        "Monitoramento: com DESCE desligada o carretel tem de voltar ao repouso (I0.7) em 200 ms, senao a falha "
        "e travada, a seguranca fica desligada e FALHA acende ate a emergencia ser acionada e liberada. Modo "
        "ajuste liga a velocidade lenta. A cada 20 golpes a bomba lubrifica 2 s com o martelo no PMS."))
    p.symbols += [Symbol("Rearmado", "M0.0", "os dois botoes foram soltos desde o ultimo golpe"),
                  Symbol("Ciclo", "M0.1", "golpe em andamento (descida)"),
                  Symbol("Retorno", "M0.2", "martelo voltando ao PMS"),
                  Symbol("Falha_Valvula", "M0.3", "carretel da DESCE nao voltou ao repouso"),
                  Symbol("Lubrificar", "M0.4", "20 golpes desde a ultima lubrificacao"),
                  Symbol("Simultaneidade", "T0", "0,5 s desde o primeiro botao"),
                  Symbol("Monitor_Valvula", "T1", "200 ms para o carretel voltar"),
                  Symbol("Tempo_Lubrificacao", "T2", "2 s de bomba"),
                  Symbol("Golpes_Lubrificacao", "C0", "golpes desde a lubrificacao")]

    def both():
        return [Contact("XIC", "Botao_Esquerdo"), Contact("XIC", "Botao_Direito")]

    def safe():
        return [Contact("XIC", "Cortina_Luz"), Contact("XIC", "Emergencia"), Contact("XIO", "Falha_Valvula")]

    p.rungs = [
        Rung([Contact("XIO", "Valvula_Desce"), Contact("XIO", "Valvula_Repouso")],
             [TimerBox("TON", "Monitor_Valvula", 200)], "Monitoramento: DESCE desligada e carretel fora do repouso"),
        Rung([Contact("XIC", "Monitor_Valvula.DN")], [Coil("OTL", "Falha_Valvula")]),
        Rung([Contact("XIO", "Emergencia"), Contact("XIC", "Valvula_Repouso")], [Coil("OTU", "Falha_Valvula")],
             "Rearme da falha: acionar a emergencia (com a valvula ja em repouso)"),
        Rung([Contact("XIC", "Falha_Valvula")], [Coil("OTE", "Lampada_Falha")]),
        Rung([Parallel([[Contact("XIC", "Botao_Esquerdo")], [Contact("XIC", "Botao_Direito")]])],
             [TimerBox("TON", "Simultaneidade", 500)], "Conta o tempo desde que a primeira mao apertou"),
        Rung([Contact("XIO", "Botao_Esquerdo"), Contact("XIO", "Botao_Direito")], [Coil("OTL", "Rearmado")],
             "Anti-repeticao: so rearma com as duas maos soltas"),
        Rung([*both(), Contact("XIO", "Simultaneidade.DN"), Contact("XIC", "Rearmado"), Contact("XIC", "PMS"),
              *safe(), Contact("XIO", "Retorno"), Contact("XIO", "Bomba_Lubrificacao")],
             [Coil("OTL", "Ciclo"), Coil("OTU", "Rearmado")],
             "Inicio do golpe: simultaneo, rearmado, no PMS, seguro e sem lubrificar"),
        Rung([Contact("XIC", "Ciclo"),
              Parallel([[Contact("XIC", "PMI")], [Contact("XIO", "Botao_Esquerdo")], [Contact("XIO", "Botao_Direito")],
                        [Contact("XIO", "Cortina_Luz")], [Contact("XIO", "Emergencia")], [Contact("XIC", "Falha_Valvula")]])],
             [Coil("OTL", "Retorno"), Coil("OTU", "Ciclo")], "Fim do golpe ou condicao insegura: volta"),
        Rung([Contact("XIC", "Ciclo"), *both(), *safe(), Contact("XIO", "PMI")],
             [Coil("OTE", "Valvula_Desce"), Coil("OTE", "Valvula_Seguranca")],
             "Desce com as DUAS valvulas em serie, so com as maos e a zona livre"),
        Rung([Contact("XIC", "Modo_Ajuste")], [Coil("OTE", "Velocidade_Lenta")], "Modo ajuste: velocidade lenta"),
        Rung([Contact("XIC", "Retorno"), Contact("XIC", "Emergencia"), Contact("XIO", "PMS")],
             [Coil("OTE", "Valvula_Sobe")], "Sobe ate o PMS"),
        Rung([Contact("XIC", "Retorno"), Contact("XIC", "PMS")], [Coil("OTU", "Retorno")]),
        Rung([Contact("XIC", "PMI")], [CounterBox("CTU", "Golpes_Lubrificacao", 20)], "Conta os golpes"),
        Rung([Contact("XIC", "Golpes_Lubrificacao.DN"), Contact("XIC", "PMS"), Contact("XIO", "Ciclo")],
             [Coil("OTE", "Bomba_Lubrificacao")], "A cada 20 golpes lubrifica com o martelo em cima"),
        Rung([Contact("XIC", "Bomba_Lubrificacao")], [TimerBox("TON", "Tempo_Lubrificacao", 2000)]),
        Rung([Contact("XIC", "Tempo_Lubrificacao.DN")], [ResetBox("Golpes_Lubrificacao")]),
        Rung([Contact("XIC", "PMS"), Contact("XIC", "Rearmado"), *safe(), Contact("XIO", "Ciclo"),
              Contact("XIO", "Bomba_Lubrificacao")], [Coil("OTE", "Lampada_Pronta")], "Pronta para o proximo golpe"),
    ]
    return p


def drill() -> Project:
    p = env_project("furadeira", "Furadeira automatica", (
        "Sequencia por etapas (estilo Grafcet) com laco: cada etapa e um bit M ligado com OTL e desligado pela "
        "transicao seguinte. E2 desce ate o alvo do quebra-cavaco (N2, comeca 14 mm abaixo da superficie: 690); "
        "ao chegar, E8 sobe acima da peca (N0 <= 500), soma 140 ao alvo e volta para E2, ate o fim de curso B1. "
        "Mandril e refrigeracao ligados nas etapas de corte. Vida da ferramenta: C0 conta os furos; com 25 acende "
        "TROCAR BROCA e nao parte mais. Uma broca nova muda N1 (diferente da copia N3): zera C0."))
    steps = [("Etapa_1_Fixar", "M0.1"), ("Etapa_2_Descer", "M0.2"), ("Etapa_3_Fundo", "M0.3"),
             ("Etapa_4_Subir", "M0.4"), ("Etapa_5_Soltar", "M0.5"), ("Etapa_6_Ejetar", "M0.6"),
             ("Etapa_7_Recuar", "M0.7"), ("Etapa_8_Cavaco", "M1.0")]
    p.symbols += [Symbol(n, a, "etapa da sequencia") for n, a in steps]
    p.symbols += [Symbol("Posicao_Broca", "N0", "ponta da broca em decimos de mm (escrito pela maquina)"),
                  Symbol("Broca_Montada", "N1", "numero da broca montada (escrito pela maquina)"),
                  Symbol("Alvo", "N2", "proxima profundidade do quebra-cavaco"),
                  Symbol("Broca_Contada", "N3", "broca cujos furos o C0 esta contando"),
                  Symbol("Tempo_Fundo", "T0", "0,5 s no fundo do furo"),
                  Symbol("Tempo_Soltar", "T1", "0,6 s para o fixador recuar (sem sensor)"),
                  Symbol("Furos", "C0", "furos feitos com a broca atual")]
    e = [n for n, _ in steps]

    def go(cond, frm, to, comment="", extra=()):
        return Rung([Contact("XIC", frm), *cond], [*extra, Coil("OTL", to), Coil("OTU", frm)], comment)

    p.rungs = [
        Rung([CompareBox("NEQ", ["Broca_Montada", "Broca_Contada"])],
             [ResetBox("Furos"), MathBox("MOV", ["Broca_Montada", "Broca_Contada"])],
             "Broca nova (N1 mudou): zera a contagem de furos"),
        Rung([Contact("XIC", "Partida"), Contact("XIC", "Emergencia"), Contact("XIC", "Peca_Presente"),
              Contact("XIC", "Broca_Em_Cima"), Contact("XIC", "Ejetor_Recuado"), Contact("XIO", "Furos.DN"),
              *[Contact("XIO", n) for n in e]],
             [MathBox("MOV", ["690", "Alvo"]), Coil("OTL", e[0])],
             "Etapa inicial: maquina em repouso e broca com vida; primeiro alvo 14 mm abaixo da peca"),
        go([Contact("XIC", "Fixador_Avancado")], e[0], e[1], "Transicoes: sensores dos cilindros e posicao N0"),
        go([Contact("XIC", "Broca_Embaixo")], e[1], e[2], "Furo pronto: fim de curso B1"),
        go([CompareBox("GEQ", ["Posicao_Broca", "Alvo"]), Contact("XIO", "Broca_Embaixo")], e[1], e[7],
           "Chegou ao alvo: sobe para tirar o cavaco e aprofunda o alvo",
           [MathBox("ADD", ["Alvo", "140", "Alvo"])]),
        go([CompareBox("LEQ", ["Posicao_Broca", "500"])], e[7], e[1], "Acima da peca: volta a descer"),
        Rung([Contact("XIC", e[2])], [TimerBox("TON", "Tempo_Fundo", 500), CounterBox("CTU", "Furos", 25)],
             "Espera no fundo e conta o furo"),
        go([Contact("XIC", "Tempo_Fundo.DN")], e[2], e[3]),
        go([Contact("XIC", "Broca_Em_Cima")], e[3], e[4]),
        Rung([Contact("XIC", e[4])], [TimerBox("TON", "Tempo_Soltar", 600)], "Fixador recua pela mola"),
        go([Contact("XIC", "Tempo_Soltar.DN")], e[4], e[5]),
        go([Contact("XIC", "Ejetor_Avancado")], e[5], e[6]),
        Rung([Contact("XIC", e[6]), Contact("XIC", "Ejetor_Recuado")], [Coil("OTU", e[6])], "Fim do ciclo"),
        Rung([Parallel([[Contact("XIC", e[k])] for k in (0, 1, 2, 3, 7)])], [Coil("OTE", "Fixador")],
             "Saidas a partir das etapas"),
        Rung([Parallel([[Contact("XIC", e[k])] for k in (1, 2, 3, 7)]), Contact("XIC", "Emergencia")],
             [Coil("OTE", "Motor_Mandril")]),
        Rung([Parallel([[Contact("XIC", e[k])] for k in (1, 2, 7)]), Contact("XIC", "Emergencia")],
             [Coil("OTE", "Refrigeracao")]),
        Rung([Contact("XIC", e[1]), Contact("XIC", "Emergencia")], [Coil("OTE", "Broca_Desce")]),
        Rung([Parallel([[Contact("XIC", e[3])], [Contact("XIC", e[7])]])], [Coil("OTE", "Broca_Sobe")]),
        Rung([Contact("XIC", e[5]), Contact("XIC", "Emergencia")], [Coil("OTE", "Ejetor")]),
        Rung([Parallel([[Contact("XIC", n)] for n in e])], [Coil("OTE", "Lampada_Ciclo")]),
        Rung([Contact("XIC", "Furos.DN")], [Coil("OTE", "Lampada_Trocar_Broca")], "Vida da ferramenta"),
    ]
    return p


def level_crossing() -> Project:
    p = env_project("passagem_nivel", "Passagem de nivel em linha dupla", (
        "Memoria de sentido por via: o primeiro sensor de aproximacao que atua define de onde o trem vem. Quando o "
        "trem deixa a ilha, a via fica livre e o sensor do lado de saida e ignorado ate o trem passar por ele, "
        "senao seria confundido com um novo trem. A logica de uma via e repetida para a outra (bits M0.x e M1.x). "
        "Alerta = via 1 ou via 2 ocupada; OUTRO TREM = as duas. Luzes alternadas pelo relogio S0.3, sino ate a "
        "cancela abaixar, 3 s de aviso antes de descer e so sobe com as duas vias livres."))
    p.symbols += [Symbol("Alerta", "M2.0", "alguma via ocupada"), Symbol("Aviso", "T0", "3 s de luzes antes de descer")]
    p.rungs = []
    for k, byte in ((1, 0), (2, 1)):
        names = ["Vindo_Oeste", "Vindo_Leste", "Ignora_Leste", "Ignora_Oeste", "Viu_Leste", "Viu_Oeste", "Na_Ilha",
                 "Ocupada"]
        notes = ["trem chegando pelo oeste", "trem chegando pelo leste", "trem indo embora pelo leste",
                 "trem indo embora pelo oeste", "o trem que vai embora chegou ao sensor leste",
                 "o trem que vai embora chegou ao sensor oeste", "o trem ja chegou a passagem", "via ocupada"]
        p.symbols += [Symbol(f"{n}_{k}", f"M{byte}.{b}", f"via {k}: {c}") for b, (n, c) in enumerate(zip(names, notes))]
        W, I, E = f"Via{k}_Oeste", f"Via{k}_Ilha", f"Via{k}_Leste"

        def m(name, k=k):
            return f"{name}_{k}"

        p.rungs += [
            Rung([Contact("XIC", W), Contact("XIO", m("Ignora_Oeste")), Contact("XIO", m("Vindo_Leste"))],
                 [Coil("OTL", m("Vindo_Oeste"))], f"VIA {k}: o primeiro sensor que atua define o sentido"),
            Rung([Contact("XIC", E), Contact("XIO", m("Ignora_Leste")), Contact("XIO", m("Vindo_Oeste"))],
                 [Coil("OTL", m("Vindo_Leste"))]),
            Rung([Parallel([[Contact("XIC", m("Vindo_Oeste"))], [Contact("XIC", m("Vindo_Leste"))]])],
                 [Coil("OTE", m("Ocupada"))]),
            Rung([Contact("XIC", m("Ocupada")), Contact("XIC", I)], [Coil("OTL", m("Na_Ilha"))],
                 "O trem chegou a passagem"),
            Rung([Contact("XIC", m("Na_Ilha")), Contact("XIO", I), Contact("XIC", m("Vindo_Oeste"))],
                 [Coil("OTL", m("Ignora_Leste"))], "Saiu da ilha: ignora o sensor do lado para onde ele vai"),
            Rung([Contact("XIC", m("Na_Ilha")), Contact("XIO", I), Contact("XIC", m("Vindo_Leste"))],
                 [Coil("OTL", m("Ignora_Oeste"))]),
            Rung([Contact("XIC", m("Na_Ilha")), Contact("XIO", I)],
                 [Coil("OTU", m("Vindo_Oeste")), Coil("OTU", m("Vindo_Leste")), Coil("OTU", m("Na_Ilha"))],
                 "Via livre"),
            Rung([Contact("XIC", m("Ignora_Leste")), Contact("XIC", E)], [Coil("OTL", m("Viu_Leste"))],
                 "O trem que vai embora passa pelo sensor do outro lado e o libera quando termina"),
            Rung([Contact("XIC", m("Viu_Leste")), Contact("XIO", E)],
                 [Coil("OTU", m("Ignora_Leste")), Coil("OTU", m("Viu_Leste"))]),
            Rung([Contact("XIC", m("Ignora_Oeste")), Contact("XIC", W)], [Coil("OTL", m("Viu_Oeste"))]),
            Rung([Contact("XIC", m("Viu_Oeste")), Contact("XIO", W)],
                 [Coil("OTU", m("Ignora_Oeste")), Coil("OTU", m("Viu_Oeste"))]),
        ]
    p.rungs += [
        Rung([Parallel([[Contact("XIC", "Ocupada_1")], [Contact("XIC", "Ocupada_2")]])], [Coil("OTE", "Alerta")],
             "PASSAGEM: alerta com qualquer via ocupada"),
        Rung([Contact("XIC", "Ocupada_1"), Contact("XIC", "Ocupada_2")], [Coil("OTE", "Painel_Outro_Trem")],
             "Dois trens: painel OUTRO TREM"),
        Rung([Contact("XIC", "Alerta"), Contact("XIC", "S0.3")], [Coil("OTE", "Luz_Esquerda")],
             "Luzes alternadas pelo relogio de 1 s"),
        Rung([Contact("XIC", "Alerta"), Contact("XIO", "S0.3")], [Coil("OTE", "Luz_Direita")]),
        Rung([Contact("XIC", "Alerta"), Contact("XIO", "Cancela_Abaixada")], [Coil("OTE", "Sino")],
             "Sino ate a cancela abaixar"),
        Rung([Contact("XIC", "Alerta")], [TimerBox("TON", "Aviso", 3000)], "3 s de aviso"),
        Rung([Contact("XIC", "Alerta"), Contact("XIC", "Aviso.DN"), Contact("XIO", "Cancela_Abaixada")],
             [Coil("OTE", "Cancela_Abaixa")], "Cancelas descem depois do aviso"),
        Rung([Contact("XIO", "Alerta"), Contact("XIO", "Cancela_Levantada")], [Coil("OTE", "Cancela_Levanta")],
             "Sobem so com as duas vias livres"),
    ]
    return p


def parking() -> Project:
    p = env_project("estacionamento", "Estacionamento de dois pisos", (
        "Contagem com aritmetica e deteccao de sentido. Entrada: quando o carro termina de passar pelo laco com a "
        "cancela aberta (borda de descida) soma 1 no total (N3) e no piso 1 (N4); a saida subtrai. Rampa: o laco "
        "que atua primeiro diz o sentido (A antes de B = subindo, B antes de A = descendo); quando o carro libera o "
        "ultimo laco o carro passa de um piso para o outro (N4/N5). Vagas livres: N0 = 16 - N3, N1 = 8 - N4, "
        "N2 = 8 - N5 (sem negativo). PISO 1 LOTADO com N4 >= 8."))
    p.symbols += [Symbol("Vagas_Livres", "N0", "vagas livres no total (painel da entrada)"),
                  Symbol("Livres_Piso1", "N1", "vagas livres no piso 1 (painel)"),
                  Symbol("Livres_Piso2", "N2", "vagas livres no piso 2 (painel)"),
                  Symbol("Ocupadas", "N3", "carros dentro"), Symbol("Carros_Piso1", "N4", "carros no piso 1"),
                  Symbol("Carros_Piso2", "N5", "carros no piso 2"),
                  Symbol("Laco_E_Anterior", "M0.0", "laco de entrada na varredura anterior"),
                  Symbol("Laco_S_Anterior", "M0.1", "laco de saida na varredura anterior"),
                  Symbol("Abre_Entrada", "M0.2", "carro autorizado a entrar"),
                  Symbol("Abre_Saida", "M0.3", "carro autorizado a sair"),
                  Symbol("Subindo", "M0.4", "carro na rampa: o laco A atuou primeiro"),
                  Symbol("Descendo", "M0.5", "carro na rampa: o laco B atuou primeiro"),
                  Symbol("Laco_A_Anterior", "M0.6", "laco A na varredura anterior"),
                  Symbol("Laco_B_Anterior", "M0.7", "laco B na varredura anterior")]
    p.rungs = [
        Rung([Contact("XIC", "Botao_Ticket"), Contact("XIC", "Laco_Entrada"), CompareBox("LES", ["Ocupadas", "16"])],
             [Coil("OTL", "Abre_Entrada")], "ENTRADA: ticket com carro no laco e vaga disponivel"),
        Rung([Contact("XIO", "Laco_Entrada"), Contact("XIC", "Laco_E_Anterior"), Contact("XIC", "Abre_Entrada")],
             [MathBox("ADD", ["Ocupadas", "1", "Ocupadas"]), MathBox("ADD", ["Carros_Piso1", "1", "Carros_Piso1"]),
              Coil("OTU", "Abre_Entrada")], "O carro terminou de passar: conta no total e no piso 1, e fecha"),
        Rung([Contact("XIC", "Laco_Entrada")], [Coil("OTE", "Laco_E_Anterior")]),
        Rung([Contact("XIC", "Cartao_Validado"), Contact("XIC", "Laco_Saida")], [Coil("OTL", "Abre_Saida")],
             "SAIDA: cartao validado com carro no laco (sai sempre pelo piso 1)"),
        Rung([Contact("XIO", "Laco_Saida"), Contact("XIC", "Laco_S_Anterior"), Contact("XIC", "Abre_Saida")],
             [MathBox("SUB", ["Ocupadas", "1", "Ocupadas"]), MathBox("SUB", ["Carros_Piso1", "1", "Carros_Piso1"]),
              Coil("OTU", "Abre_Saida")]),
        Rung([Contact("XIC", "Laco_Saida")], [Coil("OTE", "Laco_S_Anterior")]),
        Rung([Contact("XIC", "Rampa_Laco_A"), Contact("XIO", "Rampa_Laco_B"), Contact("XIO", "Descendo")],
             [Coil("OTL", "Subindo")], "RAMPA: o primeiro laco que atua define o sentido"),
        Rung([Contact("XIC", "Rampa_Laco_B"), Contact("XIO", "Rampa_Laco_A"), Contact("XIO", "Subindo")],
             [Coil("OTL", "Descendo")]),
        Rung([Contact("XIC", "Subindo"), Contact("XIO", "Rampa_Laco_B"), Contact("XIC", "Laco_B_Anterior"),
              Contact("XIO", "Rampa_Laco_A")],
             [MathBox("SUB", ["Carros_Piso1", "1", "Carros_Piso1"]), MathBox("ADD", ["Carros_Piso2", "1", "Carros_Piso2"]),
              Coil("OTU", "Subindo")], "Subiu: liberou o laco B (o ultimo)"),
        Rung([Contact("XIC", "Descendo"), Contact("XIO", "Rampa_Laco_A"), Contact("XIC", "Laco_A_Anterior"),
              Contact("XIO", "Rampa_Laco_B")],
             [MathBox("SUB", ["Carros_Piso2", "1", "Carros_Piso2"]), MathBox("ADD", ["Carros_Piso1", "1", "Carros_Piso1"]),
              Coil("OTU", "Descendo")], "Desceu: liberou o laco A (o ultimo)"),
        Rung([Contact("XIC", "Rampa_Laco_A")], [Coil("OTE", "Laco_A_Anterior")]),
        Rung([Contact("XIC", "Rampa_Laco_B")], [Coil("OTE", "Laco_B_Anterior")]),
        Rung([Contact("XIC", "Zerar_Contagem")], [MathBox("MOV", ["0", "Ocupadas"]), MathBox("MOV", ["0", "Carros_Piso1"]),
                                                  MathBox("MOV", ["0", "Carros_Piso2"])], "Manutencao: patio vazio"),
        Rung([], [MathBox("SUB", ["16", "Ocupadas", "Vagas_Livres"]), MathBox("SUB", ["8", "Carros_Piso1", "Livres_Piso1"]),
                  MathBox("SUB", ["8", "Carros_Piso2", "Livres_Piso2"])], "PAINEIS: vagas livres"),
        Rung([CompareBox("LES", ["Livres_Piso1", "0"])], [MathBox("MOV", ["0", "Livres_Piso1"])],
             "Carros de passagem (saindo ou trocando de piso): o painel nao mostra negativo"),
        Rung([CompareBox("LES", ["Livres_Piso2", "0"])], [MathBox("MOV", ["0", "Livres_Piso2"])]),
        Rung([CompareBox("LES", ["Ocupadas", "16"])], [Coil("OTE", "Painel_Livre")]),
        Rung([CompareBox("GEQ", ["Ocupadas", "16"])], [Coil("OTE", "Painel_Lotado")]),
        Rung([CompareBox("GEQ", ["Carros_Piso1", "8"])], [Coil("OTE", "Piso1_Lotado")], "Piso 1 cheio: mande subir"),
        Rung([Contact("XIC", "Abre_Entrada")], [Coil("OTE", "Cancela_Entrada")]),
        Rung([Contact("XIC", "Abre_Saida")], [Coil("OTE", "Cancela_Saida")]),
    ]
    return p


def sorter() -> Project:
    p = env_project("seletor_pecas", "Separacao de pecas configuravel", (
        "Registrador de deslocamento de palavras (FIFO): N20..N31 guardam o codigo da peca que esta 0..11 passos "
        "depois da inspecao. A cada pulso do encoder cada palavra passa para a seguinte (MOV, da ultima para a "
        "primeira) e N20 recebe o codigo da peca na inspecao: 1 + 2 se for plastica + 1 se for baixa (0 = vazio). "
        "Cada desviador compara a sua posicao com o tipo escolhido para a caixa (N10, N11, N12) e apaga o codigo "
        "ao desviar. C1-C3 contam as pecas de cada caixa; com 10 numa delas a esteira para e TROCAR acende ate o "
        "botao CAIXAS TROCADAS."))
    p.symbols += [Symbol("Tipo_Caixa_A", "N10", "tipo escolhido para a caixa A"),
                  Symbol("Tipo_Caixa_B", "N11", "tipo escolhido para a caixa B"),
                  Symbol("Tipo_Caixa_C", "N12", "tipo escolhido para a caixa C"),
                  Symbol("Encoder_Anterior", "M0.0", "encoder na varredura anterior"),
                  Symbol("Pulso", "M0.1", "borda de subida do encoder (uma varredura)"),
                  Symbol("Caixa_Cheia", "M0.2", "alguma caixa com 10 pecas"),
                  Symbol("Desviou_A", "M0.3", "caixa A recebeu a peca deste passo"),
                  Symbol("Desviou_B", "M0.4", "caixa B recebeu a peca deste passo"),
                  Symbol("Desviou_C", "M0.5", "caixa C recebeu a peca deste passo"),
                  Symbol("Pecas_A", "C1", "pecas na caixa A"), Symbol("Pecas_B", "C2", "pecas na caixa B"),
                  Symbol("Pecas_C", "C3", "pecas na caixa C")]
    p.symbols += [Symbol(f"Passo_{k}", f"N{20 + k}", f"codigo da peca {k} passos depois da inspecao")
                  for k in range(12)]
    shift = [MathBox("MOV", [f"Passo_{k - 1}", f"Passo_{k}"]) for k in range(11, 0, -1)]
    p.rungs = [
        Rung([Contact("XIC", "Liga"), Contact("XIO", "Caixa_Cheia")],
             [Coil("OTE", "Motor_Esteira"), Coil("OTE", "Lampada_Run")], "Esteira para com uma caixa cheia"),
        Rung([Contact("XIC", "Encoder"), Contact("XIO", "Encoder_Anterior")], [Coil("OTE", "Pulso")],
             "Um pulso por passo da esteira"),
        Rung([Contact("XIC", "Encoder")], [Coil("OTE", "Encoder_Anterior")]),
        Rung([Contact("XIC", "Pulso")], [*shift, MathBox("MOV", ["0", "Passo_0"])],
             "Desloca: cada codigo anda uma palavra (da ultima para a primeira)"),
        Rung([Contact("XIC", "Pulso"), Contact("XIC", "Peca_Inspecao")], [MathBox("MOV", ["1", "Passo_0"])],
             "Codigo da peca na inspecao: 1 + 2 (plastica) + 1 (baixa)"),
        Rung([Contact("XIC", "Pulso"), Contact("XIC", "Peca_Inspecao"), Contact("XIO", "Sensor_Metal")],
             [MathBox("ADD", ["Passo_0", "2", "Passo_0"])]),
        Rung([Contact("XIC", "Pulso"), Contact("XIC", "Peca_Inspecao"), Contact("XIO", "Sensor_Altura")],
             [MathBox("ADD", ["Passo_0", "1", "Passo_0"])]),
    ]
    for b, k in (("A", 4), ("B", 7), ("C", 10)):
        p.rungs.append(Rung([Contact("XIC", "Pulso"), Contact("XIC", f"Desviou_{b}")],
                            [MathBox("MOV", ["0", f"Passo_{k}"]), Coil("OTU", f"Desviou_{b}")],
                            "Peca desviada sai do registrador (a palavra ja andou um passo)" if b == "A" else ""))
    for b, k, out, counter in (("A", 3, "Desviador_A", "Pecas_A"), ("B", 6, "Desviador_B", "Pecas_B"),
                               ("C", 9, "Desviador_C", "Pecas_C")):
        p.rungs += [
            Rung([Contact("XIC", "Encoder"), CompareBox("NEQ", [f"Passo_{k}", "0"]),
                  CompareBox("EQU", [f"Passo_{k}", f"Tipo_Caixa_{b}"])], [Coil("OTE", out)],
                 f"Caixa {b}: a peca {k} passos depois e do tipo escolhido" if b == "A" else ""),
            Rung([Contact("XIC", out)], [CounterBox("CTU", counter, 10), Coil("OTL", f"Desviou_{b}")]),
        ]
    p.rungs += [
        Rung([Parallel([[Contact("XIC", "Pecas_A.DN")], [Contact("XIC", "Pecas_B.DN")], [Contact("XIC", "Pecas_C.DN")]])],
             [Coil("OTE", "Caixa_Cheia"), Coil("OTE", "Lampada_Trocar")], "Caixa cheia: para e pede a troca"),
        Rung([Contact("XIC", "Caixas_Trocadas")], [ResetBox("Pecas_A"), ResetBox("Pecas_B"), ResetBox("Pecas_C")],
             "Operador trocou as caixas"),
    ]
    return p


def gas_detection() -> Project:
    p = env_project("detector_gas", "Deteccao de gas analogica 2 de 3", (
        "Votacao analogica degradavel e gestao de alarme. Mediana dos tres detectores (N3) por comparacoes; um "
        "detector com leitura abaixo da faixa (laco aberto) ou a mais de 10% do LIE da mediana por 10 s e marcado "
        "com defeito e sai da votacao. Votos contam os detectores bons acima de 10% (pre-alarme) e 20% (alarme); "
        "sao precisos 2 votos, ou 1 se houver detector com defeito (2 de 3 vira 1 de 2). Pre-alarme liga a "
        "exaustao alta por pelo menos 60 s (TOF). Disparo trava, fecha a valvula, toca a sirene ate RECONHECER; "
        "REARMAR so depois de 30 s de purga em alta com o gas abaixo de 10%."))
    names = ["Mediana", "Dif_D1", "Dif_D2", "Dif_D3", "Votos_Alarme", "Votos_Pre", "Votos_Necessarios", "Num_Falhas"]
    p.symbols += [Symbol("Leitura_D1", "N0", "D1 em %LIE x10"), Symbol("Leitura_D2", "N1", "D2 em %LIE x10"),
                  Symbol("Leitura_D3", "N2", "D3 em %LIE x10")]
    p.symbols += [Symbol(n, f"N{3 + k}", "") for k, n in enumerate(names)]
    p.symbols += [Symbol("Falha_D1", "M0.0", "D1 com defeito"), Symbol("Falha_D2", "M0.1", "D2 com defeito"),
                  Symbol("Falha_D3", "M0.2", "D3 com defeito"), Symbol("Disparo", "M0.3", "disparo travado"),
                  Symbol("Reconhecido", "M0.4", "alarme reconhecido"), Symbol("Pre_Alarme", "M0.5", "pre-alarme"),
                  Symbol("Discord_D1", "T0", ""), Symbol("Discord_D2", "T1", ""), Symbol("Discord_D3", "T2", ""),
                  Symbol("Exaustao_Pre", "T3", "TOF 60 s de exaustao alta"), Symbol("Purga", "T4", "30 s de purga"),
                  Symbol("Sem_Fluxo", "T5", "4 s sem fluxo no duto")]
    det = [("Leitura_D1", "Dif_D1", "Falha_D1", "Discord_D1"), ("Leitura_D2", "Dif_D2", "Falha_D2", "Discord_D2"),
           ("Leitura_D3", "Dif_D3", "Falha_D3", "Discord_D3")]
    r = [Rung([], [MathBox("MOV", ["Leitura_D3", "Mediana"])], "MEDIANA: comeca com D3 e troca se D1 ou D2 estiver no meio")]
    for me, a, b in (("Leitura_D1", "Leitura_D2", "Leitura_D3"), ("Leitura_D2", "Leitura_D1", "Leitura_D3")):
        r.append(Rung([Parallel([[CompareBox("GEQ", [me, a]), CompareBox("LEQ", [me, b])],
                                 [CompareBox("LEQ", [me, a]), CompareBox("GEQ", [me, b])]])],
                      [MathBox("MOV", [me, "Mediana"])]))
    for k, (val, dif, fault, timer) in enumerate(det):
        r += [
            Rung([], [MathBox("SUB", [val, "Mediana", dif])], "DEFEITOS: distancia ate a mediana" if k == 0 else ""),
            Rung([Parallel([[CompareBox("LES", [dif, "-100"])], [CompareBox("GRT", [dif, "100"])]])],
                 [TimerBox("TON", timer, 10000)], "Longe da mediana por 10 s: descalibrado" if k == 0 else ""),
            Rung([Parallel([[Contact("XIC", f"{timer}.DN")], [CompareBox("LES", [val, "-50"])]])],
                 [Coil("OTL", fault)], "Abaixo da faixa: laco 4-20 mA aberto" if k == 0 else ""),
            Rung([Contact("XIC", "Rearmar"), CompareBox("GEQ", [val, "-50"]), CompareBox("LIM", ["-100", dif, "100"])],
                 [Coil("OTU", fault)], "Rearmar limpa o defeito que sumiu" if k == 0 else ""),
        ]
    r += [Rung([], [MathBox("MOV", ["0", "Votos_Alarme"]), MathBox("MOV", ["0", "Votos_Pre"]),
                    MathBox("MOV", ["0", "Num_Falhas"])], "VOTACAO: so detectores bons votam")]
    for k, (val, dif, fault, timer) in enumerate(det):
        r += [Rung([Contact("XIO", fault), CompareBox("GEQ", [val, "200"])],
                   [MathBox("ADD", ["Votos_Alarme", "1", "Votos_Alarme"])]),
              Rung([Contact("XIO", fault), CompareBox("GEQ", [val, "100"])],
                   [MathBox("ADD", ["Votos_Pre", "1", "Votos_Pre"])]),
              Rung([Contact("XIC", fault)], [MathBox("ADD", ["Num_Falhas", "1", "Num_Falhas"])])]
    r += [
        Rung([], [MathBox("MOV", ["2", "Votos_Necessarios"])], "2 de 3; com defeito, 1 de 2"),
        Rung([CompareBox("GEQ", ["Num_Falhas", "1"])], [MathBox("MOV", ["1", "Votos_Necessarios"])]),
        Rung([CompareBox("GEQ", ["Votos_Pre", "Votos_Necessarios"])], [Coil("OTE", "Pre_Alarme")], "PRE-ALARME"),
        Rung([Contact("XIC", "Pre_Alarme")], [TimerBox("TOF", "Exaustao_Pre", 60000)]),
        Rung([CompareBox("GEQ", ["Votos_Alarme", "Votos_Necessarios"]), Contact("XIO", "Disparo")],
             [Coil("OTL", "Disparo"), Coil("OTU", "Reconhecido")], "DISPARO: trava e pede reconhecimento"),
        Rung([Contact("XIC", "Reconhecer"), Contact("XIC", "Disparo")], [Coil("OTL", "Reconhecido")]),
        Rung([Contact("XIC", "Disparo"), Contact("XIC", "Exaustor_Alta"), CompareBox("LES", ["Votos_Pre", "1"])],
             [TimerBox("TON", "Purga", 30000)], "Purga: exaustao alta com o gas abaixo de 10%"),
        Rung([Contact("XIC", "Rearmar"), Contact("XIC", "Purga.DN"),
              CompareBox("LES", ["Votos_Alarme", "Votos_Necessarios"])],
             [Coil("OTU", "Disparo"), Coil("OTU", "Reconhecido")], "Rearme so depois da purga"),
        Rung([Contact("XIO", "Disparo")], [Coil("OTE", "Valvula_Gas")], "SAIDAS: valvula energizada para abrir"),
        Rung([Contact("XIC", "S0.1")], [Coil("OTE", "Exaustor")], "Ventilacao continua em baixa"),
        Rung([Parallel([[Contact("XIC", "Exaustao_Pre.DN")], [Contact("XIC", "Disparo")]])],
             [Coil("OTE", "Exaustor_Alta")]),
        Rung([Contact("XIC", "Disparo"), Contact("XIO", "Reconhecido")], [Coil("OTE", "Sirene")]),
        Rung([Parallel([[Contact("XIC", "Disparo"), Contact("XIO", "Reconhecido"), Contact("XIC", "S0.3")],
                        [Contact("XIC", "Disparo"), Contact("XIC", "Reconhecido")], [Contact("XIC", "Teste_Lampadas")]])],
             [Coil("OTE", "Luz_Alarme")], "Pisca sem reconhecer, fixa depois"),
        Rung([Parallel([[Contact("XIC", "Pre_Alarme")], [Contact("XIC", "Teste_Lampadas")]])],
             [Coil("OTE", "Luz_Pre_Alarme")]),
        Rung([Parallel([[Contact("XIC", "Falha_D1")], [Contact("XIC", "Falha_D2")], [Contact("XIC", "Falha_D3")],
                        [Contact("XIC", "Teste_Lampadas")]])], [Coil("OTE", "Luz_Falha_Detector")]),
        Rung([Contact("XIO", "Fluxo_Exaustao")], [TimerBox("TON", "Sem_Fluxo", 4000)], "Exaustor sem fluxo no duto"),
        Rung([Parallel([[Contact("XIC", "Sem_Fluxo.DN")], [Contact("XIC", "Teste_Lampadas")]])],
             [Coil("OTE", "Luz_Falha_Exaustor")]),
    ]
    p.rungs = r
    return p


def scale() -> Project:
    p = env_project("balanca", "Dosagem por receita", (
        "Aritmetica com setpoint e tara. Com o recipiente vazio parado, guarda a tara (N3) e calcula o alvo bruto "
        "de A (N4 = tara + N1). A: grossa ate 150 g antes, fina ate o corte antecipado (N6). Assentado, mede o erro "
        "de A, corrige o corte e calcula o alvo bruto de B (peso atual + N2). B: uma valvula ate o seu corte (N10). "
        "Erros dentro de 2% (minimo 3 g, LIM) acendem OK; senao REJEITO e o rejeitador empurra o recipiente quando "
        "ele passa por I0.4."))
    words = [("Tara", "peso do recipiente vazio"), ("Alvo_A_Bruto", "tara + alvo de A"),
             ("Corte_Grossa", "150 g antes do alvo de A"), ("Preacao_A", "A ainda no ar (g)"),
             ("Corte_Fina", "alvo bruto de A - preacao"), ("Erro_A", "erro de A"),
             ("Alvo_B_Bruto", "peso depois de A + alvo de B"), ("Preacao_B", "B ainda no ar (g)"),
             ("Corte_B", "alvo bruto de B - preacao"), ("Erro_B", "erro de B"), ("Tol_A", "2% de A, min 3 g"),
             ("Tol_B", "2% de B, min 3 g"), ("Tol_A_Neg", ""), ("Tol_B_Neg", "")]
    p.symbols += [Symbol("Peso", "N0", "peso bruto (g), escrito pela balanca"),
                  Symbol("Alvo_A", "N1", "alvo de A (g), da receita"), Symbol("Alvo_B", "N2", "alvo de B (g), da receita")]
    p.symbols += [Symbol(n, f"N{3 + k}", c) for k, (n, c) in enumerate(words)]
    p.symbols += [Symbol("Automatico", "M0.0", "ciclo automatico ligado"), Symbol("Dosando_A", "M0.1", ""),
                  Symbol("Dosando_B", "M0.2", ""), Symbol("Pesado", "M0.3", "recipiente pesado e avaliado"),
                  Symbol("Rejeitar", "M0.4", "o recipiente avaliado precisa ser rejeitado"),
                  Symbol("Empurrando", "M0.5", "rejeitador acionado"),
                  Symbol("Exibe", "T0", "1 s mostrando o resultado"), Symbol("Tempo_Empurra", "T1", "0,4 s de rejeitador")]
    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Partida")], [Contact("XIC", "Automatico")]]), Contact("XIC", "Parada")],
             [Coil("OTE", "Automatico")], "Liga/desliga (selo); PARADA e NF"),
        Rung([Contact("XIC", "S0.0")], [MathBox("MOV", ["8", "Preacao_A"]), MathBox("MOV", ["8", "Preacao_B"])],
             "Primeira varredura: cortes iniciais"),
        Rung([], [MathBox("DIV", ["Alvo_A", "50", "Tol_A"]), MathBox("DIV", ["Alvo_B", "50", "Tol_B"])],
             "Tolerancias: 2% (minimo 3 g)"),
        Rung([CompareBox("LES", ["Tol_A", "3"])], [MathBox("MOV", ["3", "Tol_A"])]),
        Rung([CompareBox("LES", ["Tol_B", "3"])], [MathBox("MOV", ["3", "Tol_B"])]),
        Rung([], [MathBox("NEG", ["Tol_A", "Tol_A_Neg"]), MathBox("NEG", ["Tol_B", "Tol_B_Neg"])]),
        Rung([Contact("XIC", "Automatico"), Contact("XIC", "Recipiente_Posicionado"), Contact("XIC", "Peso_Estavel"),
              Contact("XIO", "Pesado"), Contact("XIO", "Dosando_A"), Contact("XIO", "Dosando_B")],
             [MathBox("MOV", ["Peso", "Tara"]), MathBox("ADD", ["Tara", "Alvo_A", "Alvo_A_Bruto"]),
              MathBox("SUB", ["Alvo_A_Bruto", "150", "Corte_Grossa"]),
              MathBox("SUB", ["Alvo_A_Bruto", "Preacao_A", "Corte_Fina"]), Coil("OTL", "Dosando_A")],
             "TARA: recipiente vazio parado; alvo bruto e cortes de A"),
        Rung([], [MathBox("SUB", ["Alvo_A_Bruto", "150", "Corte_Grossa"]),
                  MathBox("SUB", ["Alvo_A_Bruto", "Preacao_A", "Corte_Fina"]),
                  MathBox("SUB", ["Alvo_B_Bruto", "Preacao_B", "Corte_B"])], "Pontos de corte"),
        Rung([Contact("XIC", "Dosando_A"), Contact("XIC", "Automatico"), CompareBox("LES", ["Peso", "Corte_Grossa"])],
             [Coil("OTE", "Valvula_A_Grossa")], "INGREDIENTE A: grossa e fina"),
        Rung([Contact("XIC", "Dosando_A"), Contact("XIC", "Automatico"), CompareBox("LES", ["Peso", "Corte_Fina"])],
             [Coil("OTE", "Valvula_A_Fina")]),
        Rung([Contact("XIC", "Dosando_A"), CompareBox("GEQ", ["Peso", "Corte_Fina"]), Contact("XIC", "Peso_Estavel")],
             [MathBox("SUB", ["Peso", "Alvo_A_Bruto", "Erro_A"]), MathBox("ADD", ["Preacao_A", "Erro_A", "Preacao_A"]),
              MathBox("ADD", ["Peso", "Alvo_B", "Alvo_B_Bruto"]),
              MathBox("SUB", ["Alvo_B_Bruto", "Preacao_B", "Corte_B"]), Coil("OTU", "Dosando_A"), Coil("OTL", "Dosando_B")],
             "A assentado: erro, novo corte e alvo bruto de B (o corte de B ja nesta varredura)"),
        Rung([Contact("XIC", "Dosando_B"), Contact("XIC", "Automatico"), CompareBox("LES", ["Peso", "Corte_B"])],
             [Coil("OTE", "Valvula_B")], "INGREDIENTE B"),
        Rung([Contact("XIC", "Dosando_B"), CompareBox("GEQ", ["Peso", "Corte_B"]), Contact("XIC", "Peso_Estavel")],
             [MathBox("SUB", ["Peso", "Alvo_B_Bruto", "Erro_B"]), MathBox("ADD", ["Preacao_B", "Erro_B", "Preacao_B"]),
              Coil("OTU", "Dosando_B"), Coil("OTL", "Pesado")], "B assentado: erro e novo corte"),
        Rung([CompareBox("LES", ["Preacao_A", "0"])], [MathBox("MOV", ["0", "Preacao_A"])], "Cortes entre 0 e 60 / 30 g"),
        Rung([CompareBox("GRT", ["Preacao_A", "60"])], [MathBox("MOV", ["60", "Preacao_A"])]),
        Rung([CompareBox("LES", ["Preacao_B", "0"])], [MathBox("MOV", ["0", "Preacao_B"])]),
        Rung([CompareBox("GRT", ["Preacao_B", "30"])], [MathBox("MOV", ["30", "Preacao_B"])]),
        Rung([Contact("XIC", "Pesado"), CompareBox("LIM", ["Tol_A_Neg", "Erro_A", "Tol_A"]),
              CompareBox("LIM", ["Tol_B_Neg", "Erro_B", "Tol_B"])], [Coil("OTE", "Lampada_OK")],
             "AVALIACAO: os dois ingredientes dentro da tolerancia"),
        Rung([Contact("XIC", "Pesado"), Contact("XIO", "Lampada_OK")], [Coil("OTE", "Lampada_Rejeito"),
                                                                        Coil("OTL", "Rejeitar")]),
        Rung([Contact("XIC", "Pesado")], [TimerBox("TON", "Exibe", 1000)]),
        Rung([Contact("XIC", "Automatico"), Contact("XIO", "Dosando_A"), Contact("XIO", "Dosando_B"),
              Parallel([[Contact("XIC", "Exibe.DN")], [Contact("XIO", "Recipiente_Posicionado")]])],
             [Coil("OTE", "Esteira")], "Troca o recipiente"),
        Rung([Contact("XIO", "Recipiente_Posicionado")], [Coil("OTU", "Pesado")], "O recipiente saiu da balanca"),
        Rung([Contact("XIC", "Rejeitar"), Contact("XIC", "Recipiente_Rejeito")],
             [Coil("OTL", "Empurrando"), Coil("OTU", "Rejeitar")], "REJEITO: empurra quando ele chega a I0.4"),
        Rung([Contact("XIC", "Empurrando")], [Coil("OTE", "Rejeitador"), TimerBox("TON", "Tempo_Empurra", 400)]),
        Rung([Contact("XIC", "Tempo_Empurra.DN")], [Coil("OTU", "Empurrando")]),
    ]
    return p


def greenhouse() -> Project:
    p = env_project("estufa", "Estufa agricola com irrigacao", (
        "Controle por faixas com histerese: cada atuador liga num limite e desliga em outro (OTL com LES/GRT, OTU "
        "do outro lado), para nao ficar ligando e desligando. Aquecedor 19-21 degC, exaustor 27-25 degC, janela "
        "26-23,5 degC (fechada com chuva ou vento), nebulizador abaixo de 60% de umidade com calor. A iluminacao "
        "suplementar usa a hora do dia (LIM 18..21 em N2). Umidade acima de 85% com calor liga o exaustor. "
        "Irrigacao: faixa do solo 40-60% (N3), bloqueada das 11 h as 14:59 (LIM 11..14) salvo com o solo abaixo de "
        "25%, e nunca com o reservatorio baixo."))
    p.symbols += [Symbol("Temperatura", "N0", "decimos de degC, escrito pela estufa"),
                  Symbol("Umidade", "N1", "%, escrito pela estufa"), Symbol("Hora", "N2", "0 a 23, escrito pela estufa"),
                  Symbol("Aquecer", "M0.0", "faixa do aquecedor"), Symbol("Ventilar", "M0.1", "faixa do exaustor"),
                  Symbol("Abrir", "M0.2", "faixa da janela"), Symbol("Nebulizar", "M0.3", "faixa do nebulizador"),
                  Symbol("Desumidificar", "M0.4", "umidade alta com calor: renovar o ar"),
                  Symbol("Umidade_Solo", "N3", "%, escrito pela estufa"),
                  Symbol("Irrigar", "M0.5", "faixa da irrigacao"), Symbol("Sol_Forte", "M0.6", "11 h as 14:59")]
    weather = Parallel([[Contact("XIC", "Sensor_Chuva")], [Contact("XIC", "Sensor_Vento")]])
    p.rungs = [
        Rung([CompareBox("LES", ["Temperatura", "190"])], [Coil("OTL", "Aquecer")], "Aquecedor: liga abaixo de 19 degC"),
        Rung([CompareBox("GRT", ["Temperatura", "210"])], [Coil("OTU", "Aquecer")], "e desliga acima de 21 degC"),
        Rung([CompareBox("GRT", ["Temperatura", "270"])], [Coil("OTL", "Ventilar")], "Exaustor: 27 degC liga, 25 desliga"),
        Rung([CompareBox("LES", ["Temperatura", "250"])], [Coil("OTU", "Ventilar")]),
        Rung([CompareBox("GRT", ["Temperatura", "260"])], [Coil("OTL", "Abrir")], "Janela: 26 degC abre, 23,5 fecha"),
        Rung([CompareBox("LES", ["Temperatura", "235"])], [Coil("OTU", "Abrir")]),
        Rung([CompareBox("LES", ["Umidade", "60"]), CompareBox("GRT", ["Temperatura", "220"])], [Coil("OTL", "Nebulizar")],
             "Nebulizador: ar seco e quente"),
        Rung([Parallel([[CompareBox("GRT", ["Umidade", "75"])], [CompareBox("LES", ["Temperatura", "200"])]])],
             [Coil("OTU", "Nebulizar")]),
        Rung([Contact("XIC", "Automatico"), Contact("XIC", "Aquecer"), Contact("XIO", "Ventilar")],
             [Coil("OTE", "Aquecedor")], "Saidas (so no automatico); nunca aquecer ventilando"),
        Rung([CompareBox("GRT", ["Umidade", "85"]), CompareBox("GRT", ["Temperatura", "220"])],
             [Coil("OTL", "Desumidificar")], "Desumidificar: acima de 85% com calor, ate 75%"),
        Rung([Parallel([[CompareBox("LES", ["Umidade", "75"])], [CompareBox("LES", ["Temperatura", "200"])]])],
             [Coil("OTU", "Desumidificar")]),
        Rung([Contact("XIC", "Automatico"), Parallel([[Contact("XIC", "Ventilar")], [Contact("XIC", "Desumidificar")]]),
              Contact("XIO", "Aquecer")], [Coil("OTE", "Exaustor")]),
        Rung([Contact("XIC", "Automatico"), Contact("XIC", "Abrir"), Contact("XIO", "Sensor_Chuva"),
              Contact("XIO", "Sensor_Vento"), Contact("XIO", "Janela_Aberta")], [Coil("OTE", "Janela_Abre")],
             "Janela abre so sem chuva e sem vento"),
        Rung([Parallel([[Contact("XIO", "Automatico")], [Contact("XIO", "Abrir")], [weather]]),
              Contact("XIO", "Janela_Fechada"), Contact("XIO", "Janela_Abre")], [Coil("OTE", "Janela_Fecha")],
             "e fecha fora da faixa, com chuva, com vento ou no manual"),
        Rung([Contact("XIC", "Automatico"), Contact("XIC", "Nebulizar")], [Coil("OTE", "Nebulizador")]),
        Rung([Contact("XIC", "Automatico"), CompareBox("LIM", ["18", "Hora", "21"])], [Coil("OTE", "Iluminacao")],
             "Fotoperiodo: 18 h as 21 h"),
        Rung([CompareBox("LES", ["Umidade_Solo", "40"])], [Coil("OTL", "Irrigar")], "Irrigacao: 40% liga, 60% desliga"),
        Rung([CompareBox("GRT", ["Umidade_Solo", "60"])], [Coil("OTU", "Irrigar")]),
        Rung([CompareBox("LIM", ["11", "Hora", "14"])], [Coil("OTE", "Sol_Forte")], "Sol forte: 11 h as 14:59"),
        Rung([Contact("XIC", "Automatico"), Contact("XIC", "Irrigar"), Contact("XIO", "Reservatorio_Baixo"),
              Parallel([[Contact("XIO", "Sol_Forte")], [CompareBox("LES", ["Umidade_Solo", "25"])]])],
             [Coil("OTE", "Bomba_Irrigacao")], "Bomba: fora do sol forte (ou solo muito seco) e com agua"),
        Rung([Parallel([[CompareBox("GRT", ["Temperatura", "350"])], [CompareBox("LES", ["Temperatura", "80"])],
                        [CompareBox("GRT", ["Umidade", "90"])], [CompareBox("LES", ["Umidade_Solo", "20"])],
                        [Contact("XIC", "Reservatorio_Baixo")]])], [Coil("OTE", "Alarme")],
             "Alarme fora dos limites ou reservatorio baixo"),
    ]
    return p


def overhead_crane() -> Project:
    p = env_project("ponte_rolante", "Ponte rolante com guincho", (
        "Posicionamento por encoder mais sequencia de transporte. Conta as duas bordas do encoder (10 mm cada) pelo "
        "sentido do ultimo movimento; ao ligar, referencia na chave de origem. Tarefa: E1 vai a estacao de origem "
        "(N10 convertido em posicao), E2 espera 3 s o balanco e desce ate apoiar, E3 liga o eletroima ate a carga "
        "prender, E4 sobe ao topo, E5 vai ao destino (N11), E6 espera e desce, E7 solta, E8 sobe vazio. A translacao "
        "so anda nas etapas E1/E5 (gancho no topo). Sem chapa na origem a tarefa aborta e a lampada pisca."))
    p.symbols += [Symbol("Posicao", "N0", "posicao em passos de 10 mm"), Symbol("Destino", "N1", "posicao da estacao alvo"),
                  Symbol("Diferenca", "N2", "Destino - Posicao"),
                  Symbol("Estacao_Origem", "N10", "1 a 5, escolhida no painel"),
                  Symbol("Estacao_Destino", "N11", "1 a 5, escolhida no painel"),
                  Symbol("Referenciado", "M0.0", "origem encontrada"),
                  Symbol("Encoder_Anterior", "M0.1", "encoder na varredura anterior"),
                  Symbol("Pulso", "M0.2", "borda do encoder (subida ou descida)"),
                  Symbol("Sentido_Direita", "M0.3", "ultimo movimento para a direita"),
                  Symbol("Erro", "M0.4", "tarefa abortada"), Symbol("Andar", "M0.5", "translacao liberada"),
                  Symbol("No_Alvo", "M0.6", "parada na estacao alvo"),
                  Symbol("Parada", "T0", "0,4 s com o motor desligado"), Symbol("Assenta", "T1", "3 s de espera do balanco"),
                  Symbol("Prende", "T2", "0,5 s de eletroima"), Symbol("Solta", "T3", "0,5 s sem eletroima")]
    steps = [("E0_Livre", "M1.0"), ("E1_Ir_Origem", "M1.1"), ("E2_Descer_Pegar", "M1.2"), ("E3_Pegar", "M1.3"),
             ("E4_Subir_Carga", "M1.4"), ("E5_Ir_Destino", "M1.5"), ("E6_Descer_Pousar", "M1.6"), ("E7_Soltar", "M1.7"),
             ("E8_Subir_Vazio", "M2.0")]
    p.symbols += [Symbol(n, a, "etapa da tarefa") for n, a in steps]
    e = [n for n, _ in steps]

    def go(cond, frm, to, comment="", extra=()):
        return Rung([Contact("XIC", frm), *cond], [*extra, Coil("OTL", to), Coil("OTU", frm)], comment)

    def table(step, word, comment):
        rungs = []
        for k, pos in enumerate((40, 120, 200, 280, 360)):
            rungs.append(Rung([Contact("XIC", step), CompareBox("EQU", [word, str(k + 1)])],
                              [MathBox("MOV", [str(pos), "Destino"])], comment if k == 0 else ""))
        return rungs

    p.rungs = [
        Rung([Parallel([[Contact("XIC", "Encoder"), Contact("XIO", "Encoder_Anterior")],
                        [Contact("XIO", "Encoder"), Contact("XIC", "Encoder_Anterior")]])], [Coil("OTE", "Pulso")],
             "ENCODER: borda de subida ou de descida = 10 mm"),
        Rung([Contact("XIC", "Encoder")], [Coil("OTE", "Encoder_Anterior")]),
        Rung([Contact("XIC", "Motor_Direita")], [Coil("OTL", "Sentido_Direita")], "Lembra o sentido do movimento"),
        Rung([Contact("XIC", "Motor_Esquerda")], [Coil("OTU", "Sentido_Direita")]),
        Rung([Contact("XIC", "Pulso"), Contact("XIC", "Sentido_Direita")], [MathBox("ADD", ["Posicao", "1", "Posicao"])],
             "Conta a posicao"),
        Rung([Contact("XIC", "Pulso"), Contact("XIO", "Sentido_Direita")], [MathBox("SUB", ["Posicao", "1", "Posicao"])]),
        Rung([Contact("XIC", "Origem"), Contact("XIO", "Referenciado")],
             [MathBox("MOV", ["0", "Posicao"]), MathBox("MOV", ["0", "Destino"]), Coil("OTL", "Referenciado"),
              Coil("OTL", e[0])], "Referenciamento: origem = 0 mm"),
        go([Contact("XIC", "Iniciar"), Contact("XIC", "Referenciado"), Contact("XIC", "Gancho_Topo")], e[0], e[1],
           "TAREFA: INICIAR com o gancho no topo", [Coil("OTU", "Erro")]),
        go([Contact("XIC", "Gancho_Topo")], e[4], e[5],
           "Carga no topo: vai ao destino (antes da tabela, para o alvo ja mudar nesta varredura)"),
        *table(e[1], "Estacao_Origem", "Estacao de origem em posicao (passos de 10 mm)"),
        *table(e[5], "Estacao_Destino", "Estacao de destino em posicao"),
        Rung([], [MathBox("SUB", ["Destino", "Posicao", "Diferenca"])], "Quanto falta"),
        Rung([CompareBox("EQU", ["Diferenca", "0"]), Contact("XIC", "Parada.DN")], [Coil("OTE", "No_Alvo")],
             "Parada na estacao"),
        go([Contact("XIC", "No_Alvo")], e[1], e[2]),
        Rung([Parallel([[Contact("XIC", e[2])], [Contact("XIC", e[6])]])], [TimerBox("TON", "Assenta", 3000)],
             "Espera o balanco parar antes de descer"),
        go([Contact("XIO", "Carga_Sob_Gancho")], e[2], e[0], "Sem chapa na origem: aborta", [Coil("OTL", "Erro")]),
        go([Contact("XIC", "Gancho_Apoiado"), Contact("XIC", "Assenta.DN")], e[2], e[3], "Apoiou na chapa"),
        Rung([Contact("XIC", e[3])], [TimerBox("TON", "Prende", 500)]),
        go([Contact("XIC", "Prende.DN"), Contact("XIC", "Carga_Presa")], e[3], e[4], "Eletroima segurando"),
        go([Contact("XIC", "No_Alvo")], e[5], e[6]),
        go([Contact("XIC", "Gancho_Apoiado"), Contact("XIC", "Assenta.DN")], e[6], e[7], "Chapa apoiada no destino"),
        Rung([Contact("XIC", e[7])], [TimerBox("TON", "Solta", 500)]),
        go([Contact("XIC", "Solta.DN"), Contact("XIO", "Carga_Presa")], e[7], e[8]),
        go([Contact("XIC", "Gancho_Topo")], e[8], e[0], "Fim da tarefa"),
        Rung([Contact("XIC", "Emergencia"), Contact("XIC", "Gancho_Topo"),
              Parallel([[Contact("XIC", e[1])], [Contact("XIC", e[5])], [Contact("XIO", "Referenciado")]])],
             [Coil("OTE", "Andar")], "TRANSLACAO: so nas etapas de viagem e com o gancho no topo"),
        Rung([Contact("XIO", "Motor_Direita"), Contact("XIO", "Motor_Esquerda")], [TimerBox("TON", "Parada", 400)],
             "So parte (ou inverte) depois de parada"),
        Rung([Contact("XIC", "Andar"), Contact("XIC", "Referenciado"), CompareBox("GRT", ["Diferenca", "0"]),
              Parallel([[Contact("XIC", "Parada.DN")], [Contact("XIC", "Motor_Direita")]]), Contact("XIO", "Motor_Esquerda")],
             [Coil("OTE", "Motor_Direita")], "Destino a direita"),
        Rung([Contact("XIC", "Andar"), Contact("XIO", "Motor_Direita"),
              Parallel([[Contact("XIC", "Parada.DN")], [Contact("XIC", "Motor_Esquerda")]]),
              Parallel([[Contact("XIO", "Referenciado")],
                        [Contact("XIC", "Referenciado"), CompareBox("LES", ["Diferenca", "0"])]])],
             [Coil("OTE", "Motor_Esquerda")], "Destino a esquerda ou procurando a origem"),
        Rung([Contact("XIC", "Referenciado"), CompareBox("LIM", ["-20", "Diferenca", "20"])],
             [Coil("OTE", "Velocidade_Lenta")], "A menos de 200 mm: lenta"),
        Rung([Parallel([[Contact("XIC", "Motor_Direita")], [Contact("XIC", "Motor_Esquerda")]])],
             [Coil("OTE", "Libera_Freio")], "Freio solto so com o motor ligado"),
        Rung([Contact("XIC", "Emergencia"), Parallel([[Contact("XIC", e[2])], [Contact("XIC", e[6])]]),
              Contact("XIC", "Assenta.DN"), Contact("XIO", "Gancho_Apoiado")], [Coil("OTE", "Guincho_Desce")],
             "GUINCHO: desce ate apoiar"),
        Rung([Contact("XIC", "Emergencia"), Parallel([[Contact("XIC", e[4])], [Contact("XIC", e[8])]]),
              Contact("XIO", "Gancho_Topo")], [Coil("OTE", "Guincho_Sobe")], "sobe ate o topo"),
        Rung([Parallel([[Contact("XIC", e[3])], [Contact("XIC", e[4])], [Contact("XIC", e[5])], [Contact("XIC", e[6])]])],
             [Coil("OTE", "Eletroima")], "Eletroima de pegar ate pousar"),
        Rung([Contact("XIC", e[0]), Parallel([[Contact("XIO", "Erro")], [Contact("XIC", "S0.3")]])],
             [Coil("OTE", "Lampada_Pronta")], "Pronta (pisca depois de um erro)"),
    ]
    return p


def vending() -> Project:
    p = env_project("venda", "Maquina de venda", (
        "Maquina de estados com dinheiro e registradores. Cada pulso de moeda soma ao credito (N0). A tecla chega "
        "em N4: com a maquina livre, a porta fechada, credito >= preco (N1..N3) e troco garantido (ou valor exato) "
        "a venda comeca; N4 e sempre zerado depois de lido. A espiral para no sensor de queda, o preco e "
        "descontado e o troco sai por um gerador de pulsos: antes de cada pulso escolhe a moeda (R$ 0,50 se o "
        "credito permitir e o tubo tiver, senao R$ 0,25) e cada pulso desconta o seu valor. Para quando o credito "
        "zera ou nao da mais para pagar. Sem queda em 3 s: esgotado, devolve o credito."))
    p.symbols += [Symbol("Credito", "N0", "credito em centavos (display)"),
                  Symbol("Preco_1", "N1", "preco da lata"), Symbol("Preco_2", "N2", "preco do suco"),
                  Symbol("Preco_3", "N3", "preco da agua"), Symbol("Tecla", "N4", "produto escolhido (0 = nenhum)"),
                  Symbol("M25_Anterior", "M0.0", ""), Symbol("M50_Anterior", "M0.1", ""),
                  Symbol("M100_Anterior", "M0.2", ""),
                  Symbol("Vendendo_1", "M0.3", ""), Symbol("Vendendo_2", "M0.4", ""), Symbol("Vendendo_3", "M0.5", ""),
                  Symbol("Devolvendo", "M0.6", "pagando o troco"), Symbol("Queda_Anterior", "M0.7", ""),
                  Symbol("Esgotou", "M1.0", "a espiral girou vazia"), Symbol("Usar_50", "M1.1", "proxima moeda: 0,50"),
                  Symbol("Ej25_Anterior", "M1.2", ""), Symbol("Ej50_Anterior", "M1.3", ""),
                  Symbol("Livre", "M1.4", "sem venda e sem troco em andamento"),
                  Symbol("Pode_Pagar", "M1.5", "ha moeda para devolver parte do credito"),
                  Symbol("Tempo_Espiral", "T0", "3 s esperando o produto cair"),
                  Symbol("Pulso_Troco", "T1", "150 ms com o ejetor desligado"),
                  Symbol("Pausa_Troco", "T2", "150 ms com o ejetor ligado"),
                  Symbol("Aviso_Esgotado", "T3", "5 s com a lampada ESGOTADO")]
    sales = [("1", "Espiral_A"), ("2", "Espiral_B"), ("3", "Espiral_C")]
    rungs = []
    for coin, prev, value in (("Moeda_25", "M25_Anterior", "25"), ("Moeda_50", "M50_Anterior", "50"),
                              ("Moeda_100", "M100_Anterior", "100")):
        rungs += [Rung([Contact("XIC", coin), Contact("XIO", prev)], [MathBox("ADD", ["Credito", value, "Credito"])],
                       "MOEDAS: cada pulso soma ao credito" if value == "25" else ""),
                  Rung([Contact("XIC", coin)], [Coil("OTE", prev)])]
    rungs.append(Rung([Contact("XIO", "Vendendo_1"), Contact("XIO", "Vendendo_2"), Contact("XIO", "Vendendo_3"),
                       Contact("XIO", "Devolvendo")], [Coil("OTE", "Livre")]))
    for k, _ in sales:
        rungs.append(Rung([Contact("XIC", "Livre"), Contact("XIO", "Porta_Servico"), CompareBox("EQU", ["Tecla", k]),
                           CompareBox("GEQ", ["Credito", f"Preco_{k}"]),
                           Parallel([[Contact("XIO", "Tubo_25_Vazio")], [CompareBox("EQU", ["Credito", f"Preco_{k}"])]])],
                          [Coil("OTL", f"Vendendo_{k}")],
                          "TECLADO: venda com credito, porta fechada e troco garantido" if k == "1" else ""))
    rungs.append(Rung([CompareBox("NEQ", ["Tecla", "0"])], [MathBox("MOV", ["0", "Tecla"])], "Tecla lida: zera N4"))
    for k, spiral in sales:
        rungs.append(Rung([Contact("XIC", "Sensor_Queda"), Contact("XIO", "Queda_Anterior"),
                           Contact("XIC", f"Vendendo_{k}")],
                          [MathBox("SUB", ["Credito", f"Preco_{k}", "Credito"]), Coil("OTU", f"Vendendo_{k}"),
                           Coil("OTL", "Devolvendo")], "O produto caiu: desconta e paga o troco" if k == "1" else ""))
    rungs.append(Rung([Contact("XIC", "Sensor_Queda")], [Coil("OTE", "Queda_Anterior")]))
    for k, spiral in sales:
        rungs.append(Rung([Contact("XIC", f"Vendendo_{k}")], [Coil("OTE", spiral)], "Espirais" if k == "1" else ""))
    rungs += [
        Rung([Contact("XIO", "Livre"), Contact("XIO", "Devolvendo")], [TimerBox("TON", "Tempo_Espiral", 3000)],
             "Sem queda em 3 s: esgotado, devolve o credito"),
        Rung([Contact("XIC", "Tempo_Espiral.DN")],
             [Coil("OTU", "Vendendo_1"), Coil("OTU", "Vendendo_2"), Coil("OTU", "Vendendo_3"),
              Coil("OTL", "Devolvendo"), Coil("OTL", "Esgotou")]),
        Rung([Contact("XIC", "Esgotou")], [TimerBox("TON", "Aviso_Esgotado", 5000)]),
        Rung([Contact("XIC", "Aviso_Esgotado.DN")], [Coil("OTU", "Esgotou")]),
        Rung([Contact("XIC", "Devolver"), Contact("XIC", "Livre")], [Coil("OTL", "Devolvendo")],
             "Devolver: paga todo o credito"),
        Rung([Parallel([[CompareBox("GEQ", ["Credito", "50"]), Contact("XIO", "Tubo_50_Vazio")],
                        [CompareBox("GEQ", ["Credito", "25"]), Contact("XIO", "Tubo_25_Vazio")]])],
             [Coil("OTE", "Pode_Pagar")], "TROCO: ainda da para devolver alguma moeda?"),
        Rung([Contact("XIC", "Devolvendo"), Contact("XIO", "Pode_Pagar"), Contact("XIO", "Ejetor_25"),
              Contact("XIO", "Ejetor_50")], [Coil("OTU", "Devolvendo")],
             "Troco pago (ou sem moeda: o resto fica no credito)"),
        Rung([Contact("XIC", "Devolvendo"), Contact("XIC", "Pode_Pagar"), Contact("XIO", "Pausa_Troco.DN")],
             [TimerBox("TON", "Pulso_Troco", 150)], "Gerador de pulsos"),
        Rung([Contact("XIC", "Pulso_Troco.DN")], [TimerBox("TON", "Pausa_Troco", 150)]),
        Rung([Contact("XIO", "Pulso_Troco.DN")], [Coil("OTU", "Usar_50")],
             "Antes de cada pulso escolhe a moeda: a maior que couber"),
        Rung([Contact("XIO", "Pulso_Troco.DN"), CompareBox("GEQ", ["Credito", "50"]), Contact("XIO", "Tubo_50_Vazio")],
             [Coil("OTL", "Usar_50")]),
        Rung([Contact("XIC", "Pulso_Troco.DN"), Contact("XIC", "Usar_50")], [Coil("OTE", "Ejetor_50")]),
        Rung([Contact("XIC", "Pulso_Troco.DN"), Contact("XIO", "Usar_50"), Contact("XIO", "Tubo_25_Vazio")],
             [Coil("OTE", "Ejetor_25")]),
        Rung([Contact("XIC", "Ejetor_50"), Contact("XIO", "Ej50_Anterior")], [MathBox("SUB", ["Credito", "50", "Credito"])],
             "Cada moeda devolvida sai do credito"),
        Rung([Contact("XIC", "Ejetor_50")], [Coil("OTE", "Ej50_Anterior")]),
        Rung([Contact("XIC", "Ejetor_25"), Contact("XIO", "Ej25_Anterior")], [MathBox("SUB", ["Credito", "25", "Credito"])]),
        Rung([Contact("XIC", "Ejetor_25")], [Coil("OTE", "Ej25_Anterior")]),
        Rung([Contact("XIC", "Livre"), Contact("XIO", "Porta_Servico")], [Coil("OTE", "Lampada_Pronto")], "Lampadas"),
        Rung([Contact("XIC", "Esgotou")], [Coil("OTE", "Lampada_Esgotado")]),
        Rung([Contact("XIC", "Tubo_25_Vazio")], [Coil("OTE", "Lampada_Sem_Troco")]),
    ]
    p.rungs = rungs
    return p


def level_pi() -> Project:
    p = env_project("nivel_pi", "Controle de nivel PI", (
        "Malha fechada com aritmetica inteira. A cada 200 ms (oscilador T0): Erro = SP - Nivel; P = Erro / 5 "
        "(Kp = 0,2 %/mm); o integral acumula o erro (N5) e vale N5 / 1000 (Ti = 40 s). Anti-windup por integracao "
        "condicional: com a saida saturada (N8 fora de 0..100) so acumula o erro que tira da saturacao; o acumulador "
        "tambem fica entre 0 e 100000. Saida = P + I limitada a 0..100% em N1. "
        "A bomba de alimentacao para no nivel alto; a de consumo desliga no nivel baixo e so volta acima de 300 mm."))
    p.symbols += [Symbol("Nivel", "N0", "mm, escrito pelo tanque"), Symbol("Valvula", "N1", "abertura 0..100% (saida)"),
                  Symbol("Setpoint", "N2", "mm, escolhido pelo operador"), Symbol("Erro", "N3", "SP - nivel (mm)"),
                  Symbol("Parcela_P", "N4", "Kp x erro (%)"), Symbol("Acumulado", "N5", "soma dos erros"),
                  Symbol("Parcela_I", "N6", "Acumulado / 1000 (%)"), Symbol("Saida", "N7", "saida limitada a 0..100"),
                  Symbol("Saida_Bruta", "N8", "P + I antes do limite"),
                  Symbol("Amostra", "T0", "periodo do controlador: 200 ms"),
                  Symbol("Consumo_Liberado", "M0.0", "tanque com agua para o consumo")]
    p.rungs = [
        Rung([Contact("XIC", "S0.0")], [MathBox("MOV", ["50000", "Acumulado"])], "Partida: integral em 50%"),
        Rung([Contact("XIO", "Amostra.DN")], [TimerBox("TON", "Amostra", 200)], "Periodo de amostragem: 200 ms"),
        Rung([], [MathBox("SUB", ["Setpoint", "Nivel", "Erro"]), MathBox("DIV", ["Erro", "5", "Parcela_P"])],
             "Erro e parcela proporcional"),
        Rung([Contact("XIC", "Amostra.DN"), Contact("XIC", "Automatico"),
              Parallel([[CompareBox("LIM", ["0", "Saida_Bruta", "100"])],
                        [CompareBox("GRT", ["Saida_Bruta", "100"]), CompareBox("LES", ["Erro", "0"])],
                        [CompareBox("LES", ["Saida_Bruta", "0"]), CompareBox("GRT", ["Erro", "0"])]])],
             [MathBox("ADD", ["Acumulado", "Erro", "Acumulado"])],
             "Integral: soma o erro a cada amostra, mas nao com a saida saturada (integracao condicional)"),
        Rung([CompareBox("GRT", ["Acumulado", "100000"])], [MathBox("MOV", ["100000", "Acumulado"])],
             "O integral fica entre 0 e 100%"),
        Rung([CompareBox("LES", ["Acumulado", "0"])], [MathBox("MOV", ["0", "Acumulado"])]),
        Rung([], [MathBox("DIV", ["Acumulado", "1000", "Parcela_I"]),
                  MathBox("ADD", ["Parcela_P", "Parcela_I", "Saida_Bruta"]), MathBox("MOV", ["Saida_Bruta", "Saida"])],
             "Saida = P + I"),
        Rung([CompareBox("GRT", ["Saida", "100"])], [MathBox("MOV", ["100", "Saida"])], "Limita a saida em 0..100%"),
        Rung([CompareBox("LES", ["Saida", "0"])], [MathBox("MOV", ["0", "Saida"])]),
        Rung([Contact("XIC", "Automatico")], [MathBox("MOV", ["Saida", "Valvula"])], "Automatico: PI na valvula"),
        Rung([Contact("XIO", "Automatico")], [MathBox("MOV", ["0", "Valvula"])], "Manual: valvula fechada"),
        Rung([Contact("XIC", "Automatico"), Contact("XIO", "Nivel_Alto")], [Coil("OTE", "Bomba_Alimentacao")],
             "Protecoes: alimentacao para no nivel alto"),
        Rung([Contact("XIC", "Nivel_Baixo")], [Coil("OTU", "Consumo_Liberado")], "Consumo desliga no nivel baixo"),
        Rung([CompareBox("GRT", ["Nivel", "300"])], [Coil("OTL", "Consumo_Liberado")], "e volta acima de 300 mm"),
        Rung([Contact("XIC", "Consumo_Liberado")], [Coil("OTE", "Bomba_Consumo")]),
        Rung([Contact("XIC", "Nivel_Alto")], [Coil("OTE", "Alarme_Alto")], "Sinalizacao"),
        Rung([Contact("XIC", "Nivel_Baixo")], [Coil("OTE", "Alarme_Baixo")]),
    ]
    return p


def palletizer() -> Project:
    p = env_project("paletizador", "Paletizador de camadas", (
        "Contadores aninhados: C0 conta as caixas da fila (3, borda de descida da fotocelula), C1 as filas da camada "
        "(2) e C2 as camadas do pallet (4). Fila completa: a esteira para e o empurrador leva a fila para a placa; "
        "a cada fila empurrada C0 zera e C1 conta. Segunda fila: C2 conta a camada (assim a proxima caixa ja entra "
        "com a amarracao da camada seguinte: girador ligado quando C2.ACC e impar, MEQ com mascara 1), a placa abre "
        "800 ms sobre a pilha alinhada e o elevador desce ate alinhar de novo. Quarta camada: desce ao fundo, troca "
        "o pallet (6 s) e sobe o vazio ate alinhar."))
    p.symbols += [Symbol("Caixas", "C0", "caixas na fila"), Symbol("Filas", "C1", "filas na placa"),
                  Symbol("Camadas", "C2", "camadas no pallet"),
                  Symbol("Empurrando", "M0.0", "empurrador levando a fila"), Symbol("Abrindo", "M0.1", "placa aberta"),
                  Symbol("Descer_Camada", "M0.2", "descendo uma camada"), Symbol("Foto_Anterior", "M0.3", ""),
                  Symbol("Pallet_Pronto", "M0.4", "quatro camadas: trocar o pallet"),
                  Symbol("Subir_Pallet", "M0.5", "levando o pallet vazio ate a placa"),
                  Symbol("Tempo_Placa", "T0", "800 ms de placa aberta"), Symbol("Troca_Pallet", "T1", "6 s de esteira")]
    p.rungs = [
        Rung([Contact("XIC", "S0.0")], [Coil("OTL", "Subir_Pallet")], "Partida: alinha o pallet com a placa"),
        Rung([Contact("XIO", "Caixa_Entrando"), Contact("XIC", "Foto_Anterior")], [CounterBox("CTU", "Caixas", 3)],
             "CAIXAS: conta quando a caixa termina de entrar na mesa"),
        Rung([Contact("XIC", "Caixa_Entrando")], [Coil("OTE", "Foto_Anterior")]),
        Rung([Contact("XIC", "Liga"), Contact("XIO", "Caixas.DN"), Contact("XIO", "Empurrando"),
              Contact("XIC", "Empurrador_Recuado")], [Coil("OTE", "Esteira_Entrada")], "Esteira ate completar a fila"),
        Rung([CompareBox("MEQ", ["Camadas.ACC", "1", "1"])], [Coil("OTE", "Girador")],
             "Amarracao: camadas pares (C2.ACC impar) com as caixas giradas"),
        Rung([Contact("XIC", "Caixas.DN"), Contact("XIO", "Filas.DN"), Contact("XIO", "Camadas.DN"),
              Contact("XIC", "Placa_Fechada"), Contact("XIC", "Empurrador_Recuado"), Contact("XIO", "Esteira_Entrada")],
             [Coil("OTL", "Empurrando")], "FILAS: fila completa, lugar na placa e pallet ainda nao completo"),
        Rung([Contact("XIC", "Empurrando")], [Coil("OTE", "Empurrador")]),
        Rung([Contact("XIC", "Empurrando"), Contact("XIC", "Empurrador_Avancado")],
             [Coil("OTU", "Empurrando"), ResetBox("Caixas"), CounterBox("CTU", "Filas", 2)], "Empurrou: conta a fila"),
        Rung([Contact("XIC", "Filas.DN")], [CounterBox("CTU", "Camadas", 4)], "CAMADAS: segunda fila forma a camada"),
        Rung([Contact("XIC", "Filas.DN"), Contact("XIC", "Pilha_Alinhada"), Contact("XIC", "Empurrador_Recuado"),
              Contact("XIO", "Descer_Camada")], [Coil("OTL", "Abrindo")], "Pilha alinhada: abre a placa"),
        Rung([Contact("XIC", "Abrindo")], [Coil("OTE", "Abre_Placa"), TimerBox("TON", "Tempo_Placa", 800)]),
        Rung([Contact("XIC", "Tempo_Placa.DN"), Contact("XIO", "Camadas.DN")],
             [Coil("OTL", "Descer_Camada")], "Camada solta: desce uma camada"),
        Rung([Contact("XIC", "Tempo_Placa.DN"), Contact("XIC", "Camadas.DN")], [Coil("OTL", "Pallet_Pronto")],
             "Quarta camada: pallet pronto"),
        Rung([Contact("XIC", "Tempo_Placa.DN")], [Coil("OTU", "Abrindo"), ResetBox("Filas")]),
        Rung([Contact("XIC", "Descer_Camada"), Contact("XIC", "Placa_Fechada"), Contact("XIC", "Pilha_Alinhada")],
             [Coil("OTU", "Descer_Camada")], "Desceu ate alinhar de novo"),
        Rung([Contact("XIC", "Pallet_Pronto"), Contact("XIC", "Elevador_Embaixo")], [TimerBox("TON", "Troca_Pallet", 6000)],
             "PALLET: no fundo, troca pelo vazio"),
        Rung([Contact("XIC", "Troca_Pallet.DN"), Contact("XIC", "Pallet_Presente")],
             [Coil("OTU", "Pallet_Pronto"), ResetBox("Camadas"), Coil("OTL", "Subir_Pallet")]),
        Rung([Contact("XIC", "Subir_Pallet"), Contact("XIC", "Pilha_Alinhada")], [Coil("OTU", "Subir_Pallet")],
             "Pallet vazio alinhado"),
        Rung([Contact("XIC", "Pallet_Pronto"), Contact("XIC", "Elevador_Embaixo"), Contact("XIO", "Troca_Pallet.DN")],
             [Coil("OTE", "Esteira_Pallets")]),
        Rung([Parallel([[Contact("XIC", "Descer_Camada"), Contact("XIC", "Placa_Fechada"), Contact("XIO", "Pilha_Alinhada")],
                        [Contact("XIC", "Pallet_Pronto"), Contact("XIC", "Placa_Fechada"), Contact("XIO", "Elevador_Embaixo")]])],
             [Coil("OTE", "Elevador_Desce")], "ELEVADOR"),
        Rung([Contact("XIC", "Subir_Pallet"), Contact("XIC", "Pallet_Presente"), Contact("XIO", "Pilha_Alinhada"),
              Contact("XIO", "Pallet_Pronto")], [Coil("OTE", "Elevador_Sobe")]),
        Rung([Contact("XIC", "Pallet_Pronto")], [Coil("OTE", "Lampada_Completo")]),
    ]
    return p


def furnace() -> Project:
    p = env_project("forno_rampa", "Forno com rampa e patamar", (
        "Gerador de perfil e controle proporcional ao tempo. O setpoint e calculado em decimos de grau (N2) e muda a "
        "cada 100 ms: +10 (10 degC/s) na rampa 1 ate 6000, patamar de 20 s, +5 (5 degC/s) na rampa 2 ate 8500, "
        "patamar de 30 s e -8 (8 degC/s) no resfriamento ate 3000. N1 = N2 / 10 vai para o forno. Potencia: "
        "Duty = Erro x 25 ms + (SP - 25) / 2 (antecipacao da perda) e a resistencia 1 fica ligada enquanto o ACC do ciclo de 1 s (T1) for menor "
        "que o Duty; a 2 ajuda com erro acima de 20 degC. No resfriamento o ventilador usa o mesmo ciclo com o erro "
        "negativo. A porta fica travada durante o ciclo e acima de 200 degC."))
    p.symbols += [Symbol("Temperatura", "N0", "termopar (degC)"), Symbol("Setpoint", "N1", "perfil (degC)"),
                  Symbol("SP_x10", "N2", "perfil em decimos de grau"), Symbol("Erro", "N3", "setpoint - temperatura"),
                  Symbol("Duty", "N4", "ms ligados por ciclo de 1 s"), Symbol("Duty_Frio", "N5", "ms de ventilador"),
                  Symbol("Antecipacao", "N6", "potencia para segurar a temperatura (ms)"),
                  Symbol("Ciclo", "M0.0", "ciclo em andamento"), Symbol("Rampa_1", "M0.1", "20 -> 600 degC"),
                  Symbol("Patamar_1", "M0.2", "600 degC"), Symbol("Rampa_2", "M0.3", "600 -> 850 degC"),
                  Symbol("Patamar_2", "M0.4", "850 degC (tempera)"), Symbol("Resfriamento", "M0.5", "850 -> 300 degC"),
                  Symbol("Fim", "M0.6", "ciclo terminado"),
                  Symbol("Tick", "T0", "100 ms do gerador de perfil"), Symbol("Ciclo_PWM", "T1", "ciclo de 1 s"),
                  Symbol("Tempo_P1", "T2", "20 s"), Symbol("Tempo_P2", "T3", "30 s")]
    steps = ["Rampa_1", "Patamar_1", "Rampa_2", "Patamar_2", "Resfriamento"]
    p.rungs = [
        Rung([Contact("XIC", "Partida"), Contact("XIC", "Porta_Fechada"), Contact("XIC", "Termostato"),
              Contact("XIO", "Ciclo")],
             [MathBox("MUL", ["Temperatura", "10", "SP_x10"]), Coil("OTL", "Ciclo"), Coil("OTL", "Rampa_1"),
              Coil("OTU", "Fim")], "PARTIDA: o perfil comeca na temperatura atual"),
        Rung([Parallel([[Contact("XIO", "Parada")], [Contact("XIO", "Termostato")]])],
             [*[Coil("OTU", s) for s in steps], Coil("OTU", "Ciclo")], "PARADA (NF) ou sobretemperatura"),
        Rung([Contact("XIO", "Tick.DN")], [TimerBox("TON", "Tick", 100)], "Gerador de perfil: um passo a cada 100 ms"),
        Rung([Contact("XIC", "Tick.DN"), Contact("XIC", "Rampa_1")], [MathBox("ADD", ["SP_x10", "10", "SP_x10"])],
             "Rampa 1: 10 degC/s"),
        Rung([Contact("XIC", "Rampa_1"), CompareBox("GEQ", ["SP_x10", "6000"])],
             [MathBox("MOV", ["6000", "SP_x10"]), Coil("OTU", "Rampa_1"), Coil("OTL", "Patamar_1")]),
        Rung([Contact("XIC", "Patamar_1")], [TimerBox("TON", "Tempo_P1", 20000)], "Patamar 1: 20 s"),
        Rung([Contact("XIC", "Tempo_P1.DN")], [Coil("OTU", "Patamar_1"), Coil("OTL", "Rampa_2")]),
        Rung([Contact("XIC", "Tick.DN"), Contact("XIC", "Rampa_2")], [MathBox("ADD", ["SP_x10", "5", "SP_x10"])],
             "Rampa 2: 5 degC/s"),
        Rung([Contact("XIC", "Rampa_2"), CompareBox("GEQ", ["SP_x10", "8500"])],
             [MathBox("MOV", ["8500", "SP_x10"]), Coil("OTU", "Rampa_2"), Coil("OTL", "Patamar_2")]),
        Rung([Contact("XIC", "Patamar_2")], [TimerBox("TON", "Tempo_P2", 30000)], "Patamar 2 (tempera): 30 s"),
        Rung([Contact("XIC", "Tempo_P2.DN")], [Coil("OTU", "Patamar_2"), Coil("OTL", "Resfriamento")]),
        Rung([Contact("XIC", "Tick.DN"), Contact("XIC", "Resfriamento")], [MathBox("SUB", ["SP_x10", "8", "SP_x10"])],
             "Resfriamento: 8 degC/s"),
        Rung([Contact("XIC", "Resfriamento"), CompareBox("LEQ", ["SP_x10", "3000"])],
             [MathBox("MOV", ["3000", "SP_x10"]), Coil("OTU", "Resfriamento"), Coil("OTU", "Ciclo"), Coil("OTL", "Fim")]),
        Rung([], [MathBox("DIV", ["SP_x10", "10", "Setpoint"]), MathBox("SUB", ["Setpoint", "Temperatura", "Erro"]),
                  MathBox("MUL", ["Erro", "25", "Duty"]), MathBox("NEG", ["Duty", "Duty_Frio"]),
                  MathBox("SUB", ["Setpoint", "25", "Antecipacao"]), MathBox("DIV", ["Antecipacao", "2", "Antecipacao"]),
                  MathBox("ADD", ["Duty", "Antecipacao", "Duty"])],
             "CONTROLE: 25 ms por degC de erro + antecipacao da perda pelas paredes ((SP - 25) / 2)"),
        Rung([Contact("XIO", "Ciclo_PWM.DN")], [TimerBox("TON", "Ciclo_PWM", 1000)], "Ciclo de 1 s"),
        Rung([Contact("XIC", "Ciclo"), Contact("XIO", "Resfriamento"), Contact("XIC", "Porta_Fechada"),
              Contact("XIC", "Termostato"), CompareBox("LES", ["Ciclo_PWM.ACC", "Duty"])],
             [Coil("OTE", "Resistencia_1")], "Resistencia 1: ligada uma fracao do ciclo"),
        Rung([Contact("XIC", "Ciclo"), Contact("XIO", "Resfriamento"), Contact("XIC", "Porta_Fechada"),
              Contact("XIC", "Termostato"), CompareBox("GRT", ["Erro", "20"])], [Coil("OTE", "Resistencia_2")],
             "Resistencia 2: reforco com erro grande"),
        Rung([Parallel([[Contact("XIC", "Resfriamento"), CompareBox("LES", ["Ciclo_PWM.ACC", "Duty_Frio"])],
                        [Contact("XIC", "Fim"), CompareBox("GEQ", ["Temperatura", "190"])]])],
             [Coil("OTE", "Ventilador")], "Ventilador proporcional no resfriamento; depois, ate 190 degC"),
        Rung([Parallel([[Contact("XIC", "Ciclo")], [CompareBox("GEQ", ["Temperatura", "200"])]])],
             [Coil("OTE", "Trava_Porta")], "Porta travada no ciclo e acima de 200 degC"),
        Rung([Contact("XIC", "Ciclo")], [Coil("OTE", "Lampada_Ciclo")], "Sinalizacao"),
        Rung([Contact("XIO", "Porta_Fechada")], [Coil("OTU", "Fim")]),
        Rung([Contact("XIC", "Fim"), CompareBox("LES", ["Temperatura", "200"])], [Coil("OTE", "Lampada_Fim")]),
        Rung([Parallel([[Contact("XIO", "Termostato")],
                        [Contact("XIC", "Ventilador"), Contact("XIO", "Fluxo_Ventilador")]])],
             [Coil("OTE", "Lampada_Alarme")]),
    ]
    return p


def demand_control() -> Project:
    p = env_project("demanda_energia", "Controle de demanda", (
        "Projecao e corte por estagios. Projecao = (Energia + Potencia x Restante) / 120 = media que a janela vai "
        "fechar se nada mudar. A cada 4 s o estagio de corte (N5) sobe se a projecao passar de 97% do contrato e "
        "desce abaixo de 88%. Estagio 1 corta o aquecedor, 2 e 3 os ar-condicionados (rodizio: a cada janela muda "
        "qual sai primeiro) e 4 o compressor; a bomba nunca e cortada. Cada carga cortada tem tempo maximo "
        "desligada e tempo minimo ligada (ar 25 s / 12 s, compressor 20 s / 10 s, aquecedor 100 s / 15 s): ela "
        "volta por pouco tempo e e cortada de novo, ficando perto do limite de conforto sem recarregar tudo."))
    p.symbols += [Symbol("Potencia", "N0", "kW agora"), Symbol("Energia", "N1", "kW.s na janela"),
                  Symbol("Restante", "N2", "s ate o fim da janela"), Symbol("Contrato", "N3", "kW contratados"),
                  Symbol("Projecao", "N4", "media prevista para o fim da janela"), Symbol("Estagio", "N5", "0 a 4"),
                  Symbol("Limite_Alto", "N6", "97% do contrato"), Symbol("Limite_Baixo", "N7", "88% do contrato"),
                  Symbol("Calculo", "N8", "auxiliar"),
                  Symbol("Vez_AC2", "M0.0", "nesta janela o AC2 sai primeiro"), Symbol("Sinc_Anterior", "M0.1", ""),
                  Symbol("Troca_Rodizio", "M0.2", "auxiliar da troca do rodizio"),
                  Symbol("Passo", "T0", "4 s entre mudancas de estagio")]
    loads = [("AC1", "Pede_AC1", "Ar_Cond_1", 25000, 12000, "M1"), ("AC2", "Pede_AC2", "Ar_Cond_2", 25000, 12000, "M2"),
             ("Comp", "Pede_Compressor", "Compressor", 20000, 10000, "M3"),
             ("Aq", "Pede_Aquecedor", "Aquecedor", 100000, 15000, "M4")]
    timer = 1
    for name, _, _, off_ms, on_ms, byte in loads:
        p.symbols += [Symbol(f"Corta_{name}", f"{byte}.0", f"estagio pede o corte de {name}"),
                      Symbol(f"Devolve_{name}", f"{byte}.1", f"{name} de volta pelo tempo minimo"),
                      Symbol(f"Max_{name}", f"T{timer}", f"{off_ms // 1000} s no maximo desligado"),
                      Symbol(f"Min_{name}", f"T{timer + 1}", f"{on_ms // 1000} s no minimo ligado")]
        timer += 2
    rungs = [
        Rung([], [MathBox("MUL", ["Potencia", "Restante", "Calculo"]), MathBox("ADD", ["Calculo", "Energia", "Calculo"]),
                  MathBox("DIV", ["Calculo", "120", "Projecao"])], "PROJECAO da media no fim da janela"),
        Rung([], [MathBox("MUL", ["Contrato", "97", "Limite_Alto"]), MathBox("DIV", ["Limite_Alto", "100", "Limite_Alto"]),
                  MathBox("MUL", ["Contrato", "88", "Limite_Baixo"]), MathBox("DIV", ["Limite_Baixo", "100", "Limite_Baixo"])],
             "Faixa de atuacao: 88% a 97% do contrato"),
        Rung([Contact("XIO", "Passo.DN")], [TimerBox("TON", "Passo", 4000)], "ESTAGIOS: um passo a cada 4 s"),
        Rung([Contact("XIC", "Passo.DN"), CompareBox("GRT", ["Projecao", "Limite_Alto"]), CompareBox("LES", ["Estagio", "4"])],
             [MathBox("ADD", ["Estagio", "1", "Estagio"])], "Projecao alta: corta mais uma carga"),
        Rung([Contact("XIC", "Passo.DN"), CompareBox("LES", ["Projecao", "Limite_Baixo"]), CompareBox("GRT", ["Estagio", "0"])],
             [MathBox("SUB", ["Estagio", "1", "Estagio"])], "Projecao baixa: devolve uma carga"),
        Rung([Contact("XIC", "Pulso_Sincronismo"), Contact("XIO", "Sinc_Anterior")], [Coil("OTL", "Troca_Rodizio")],
             "RODIZIO: troca qual ar-condicionado sai primeiro a cada janela"),
        Rung([Contact("XIC", "Troca_Rodizio"), Contact("XIC", "Vez_AC2")], [Coil("OTU", "Vez_AC2"), Coil("OTU", "Troca_Rodizio")]),
        Rung([Contact("XIC", "Troca_Rodizio"), Contact("XIO", "Vez_AC2")], [Coil("OTL", "Vez_AC2"), Coil("OTU", "Troca_Rodizio")]),
        Rung([Contact("XIC", "Pulso_Sincronismo")], [Coil("OTE", "Sinc_Anterior")]),
        Rung([CompareBox("GEQ", ["Estagio", "1"])], [Coil("OTE", "Corta_Aq")], "PRIORIDADES de corte"),
        Rung([Parallel([[CompareBox("GEQ", ["Estagio", "3"])],
                        [CompareBox("GEQ", ["Estagio", "2"]), Contact("XIO", "Vez_AC2")]])], [Coil("OTE", "Corta_AC1")]),
        Rung([Parallel([[CompareBox("GEQ", ["Estagio", "3"])],
                        [CompareBox("GEQ", ["Estagio", "2"]), Contact("XIC", "Vez_AC2")]])], [Coil("OTE", "Corta_AC2")]),
        Rung([CompareBox("GEQ", ["Estagio", "4"])], [Coil("OTE", "Corta_Comp")]),
    ]
    for k, (name, req, out, _, _, _) in enumerate(loads):
        off_ms, on_ms = loads[k][3], loads[k][4]
        first = k == 0
        rungs += [
            Rung([Contact("XIC", req), Contact("XIC", f"Corta_{name}"), Contact("XIO", f"Devolve_{name}")],
                 [TimerBox("TON", f"Max_{name}", off_ms)],
                 "TEMPO MAXIMO desligada e MINIMO ligada (a carga volta um pouco e sai de novo)" if first else ""),
            Rung([Contact("XIC", f"Max_{name}.DN")], [Coil("OTL", f"Devolve_{name}")]),
            Rung([Contact("XIC", f"Devolve_{name}")], [TimerBox("TON", f"Min_{name}", on_ms)]),
            Rung([Contact("XIC", f"Min_{name}.DN")], [Coil("OTU", f"Devolve_{name}")]),
            Rung([Contact("XIC", req), Parallel([[Contact("XIO", f"Corta_{name}")], [Contact("XIC", f"Devolve_{name}")]])],
                 [Coil("OTE", out)], "SAIDA: pedido do termostato e nao cortada" if first else ""),
        ]
    rungs += [
        Rung([Contact("XIC", "Pede_Bomba")], [Coil("OTE", "Bomba")], "Bomba nunca e cortada"),
        Rung([CompareBox("GRT", ["Projecao", "Contrato"])], [Coil("OTE", "Lampada_Demanda")], "Sinalizacao"),
        Rung([CompareBox("GRT", ["Estagio", "0"])], [Coil("OTE", "Lampada_Corte")]),
    ]
    p.rungs = rungs
    return p


def transfer_switch() -> Project:
    p = env_project("gerador_qta", "Transferencia rede/gerador", (
        "Supervisao com filtros, retentativas e intertravamento. A rede so e considerada ausente depois de 3 s sem "
        "ela (T0) e estavel depois de 10 s com ela (T1). Sem rede estavel o gerador e pedido: combustivel ligado e "
        "arranque por no maximo 5 s (T2), descanso de 5 s (T3) e nova tentativa; C0 conta as tentativas e na "
        "terceira sem pegar bloqueia ate o REARME. Transferencia: KG so fecha com a tensao do gerador estavel, o "
        "contato auxiliar do KR aberto e 1 s de tempo morto (T4); KR so fecha com o KG aberto e 1 s de tempo morto "
        "(T5). Na volta da rede o gerador sai da carga e gira 10 s sem carga (T6) antes de parar."))
    p.symbols += [Symbol("Rede_Estavel", "M0.0", "rede presente ha 10 s"), Symbol("Pedir_Gerador", "M0.1", ""),
                  Symbol("Descanso", "M0.2", "pausa entre tentativas de partida"),
                  Symbol("Bloqueio", "M0.3", "falha de partida (3 tentativas)"),
                  Symbol("Resfriando", "M0.4", "gerador girando sem carga antes de parar"),
                  Symbol("Falta", "T0", "3 s sem rede"), Symbol("Volta", "T1", "10 s com rede"),
                  Symbol("Tentativa", "T2", "5 s de arranque no maximo"), Symbol("Pausa", "T3", "5 s de descanso"),
                  Symbol("Morto_KR", "T4", "1 s com KR aberto"), Symbol("Morto_KG", "T5", "1 s com KG aberto"),
                  Symbol("Resfria", "T6", "10 s sem carga"), Symbol("Tentativas", "C0", "tentativas de partida")]
    p.rungs = [
        Rung([Contact("XIO", "Rede_OK")], [TimerBox("TON", "Falta", 3000)], "FILTROS da rede: 3 s para falta"),
        Rung([Contact("XIC", "Rede_OK")], [TimerBox("TON", "Volta", 10000)], "e 10 s para estabilidade"),
        Rung([Parallel([[Contact("XIC", "Volta.DN")], [Contact("XIC", "S0.0"), Contact("XIC", "Rede_OK")]])],
             [Coil("OTL", "Rede_Estavel")]),
        Rung([Contact("XIC", "Falta.DN")], [Coil("OTU", "Rede_Estavel")]),
        Rung([Contact("XIC", "Automatico"), Contact("XIO", "Rede_Estavel"), Contact("XIO", "Bloqueio")],
             [Coil("OTL", "Pedir_Gerador"), Coil("OTU", "Resfriando")], "PEDIDO do gerador"),
        Rung([Contact("XIC", "Pedir_Gerador"), Contact("XIC", "Rede_Estavel"), Contact("XIC", "KR_Fechado")],
             [Coil("OTU", "Pedir_Gerador"), Coil("OTL", "Resfriando")], "Carga de volta na rede: resfria o motor"),
        Rung([Contact("XIC", "Resfriando")], [TimerBox("TON", "Resfria", 10000)]),
        Rung([Contact("XIC", "Resfria.DN")], [Coil("OTU", "Resfriando")]),
        Rung([Contact("XIC", "Pedir_Gerador"), Contact("XIO", "Gerador_Girando"), Contact("XIO", "Descanso"),
              Contact("XIO", "Bloqueio")], [Coil("OTE", "Motor_Partida"), TimerBox("TON", "Tentativa", 5000)],
             "PARTIDA: arranque ate o motor girar, no maximo 5 s"),
        Rung([Contact("XIC", "Tentativa.DN")], [Coil("OTL", "Descanso"), CounterBox("CTU", "Tentativas", 3)],
             "Nao pegou: descansa e conta a tentativa"),
        Rung([Contact("XIC", "Descanso")], [TimerBox("TON", "Pausa", 5000)]),
        Rung([Contact("XIC", "Pausa.DN")], [Coil("OTU", "Descanso")]),
        Rung([Contact("XIC", "Tentativas.DN")], [Coil("OTL", "Bloqueio"), Coil("OTU", "Pedir_Gerador")],
             "Terceira tentativa sem sucesso: bloqueio"),
        Rung([Contact("XIC", "Gerador_Girando")], [ResetBox("Tentativas")], "Pegou: zera as tentativas"),
        Rung([Contact("XIC", "Rearme")], [Coil("OTU", "Bloqueio"), ResetBox("Tentativas"), Coil("OTU", "Descanso")],
             "Rearme da falha de partida"),
        Rung([Parallel([[Contact("XIC", "Pedir_Gerador")], [Contact("XIC", "Resfriando")]]), Contact("XIO", "Bloqueio")],
             [Coil("OTE", "Solenoide_Combustivel")], "Combustivel com o gerador pedido ou resfriando"),
        Rung([Contact("XIO", "Contator_KR"), Contact("XIO", "KR_Fechado")], [TimerBox("TON", "Morto_KR", 1000)],
             "TRANSFERENCIA: tempo morto depois de cada contator abrir de verdade"),
        Rung([Contact("XIO", "Contator_KG"), Contact("XIO", "KG_Fechado")], [TimerBox("TON", "Morto_KG", 1000)]),
        Rung([Contact("XIC", "Pedir_Gerador"), Contact("XIO", "Rede_Estavel"), Contact("XIC", "Gerador_Tensao_OK"),
              Contact("XIO", "KR_Fechado"), Contact("XIC", "Morto_KR.DN")], [Coil("OTE", "Contator_KG")],
             "KG: gerador estavel, KR aberto (auxiliar) e tempo morto"),
        Rung([Contact("XIC", "Rede_Estavel"), Contact("XIO", "Contator_KG"), Contact("XIO", "KG_Fechado"),
              Contact("XIC", "Morto_KG.DN")], [Coil("OTE", "Contator_KR")], "KR: rede estavel, KG aberto e tempo morto"),
        Rung([Contact("XIC", "KR_Fechado")], [Coil("OTE", "Lampada_Rede")], "SINALIZACAO"),
        Rung([Contact("XIC", "KG_Fechado")], [Coil("OTE", "Lampada_Gerador")]),
        Rung([Parallel([[Contact("XIC", "Bloqueio")], [Contact("XIC", "Combustivel_Baixo")],
                        [Contact("XIC", "Pedir_Gerador"), Contact("XIC", "KR_Fechado"), Contact("XIO", "Contator_KR")]])],
             [Coil("OTE", "Lampada_Falha")], "Falha: partida, combustivel ou KR que nao abre"),
        Rung([Contact("XIC", "Lampada_Falha"), Contact("XIC", "S0.3")], [Coil("OTE", "Buzina")]),
    ]
    return p


def canal_lock() -> Project:
    p = env_project("eclusa", "Eclusa de navegacao", (
        "Permissivos e equalizacao. Duas sequencias: DESCER (barco a montante) D1 fecha a comporta de jusante e "
        "enche ate o nivel de montante, D2 abre montante, D3 sinal verde ate o barco parar na camara (N1 = 2), D4 "
        "fecha montante, D5 esvazia ate o nivel de jusante, D6 abre jusante, D7 espera o barco sair (N1 = 0). SUBIR "
        "faz o espelho. Permissivos em cada saida: encher so com jusante fechada, esvaziar so com montante fechada, "
        "abrir uma comporta so com o nivel igualado e a outra fechada, verde so com a comporta toda aberta. Com "
        "barcos dos dois lados, atende o lado contrario ao ultimo."))
    p.symbols += [Symbol("Nivel_Camara", "N0", "cm"), Symbol("Ocupacao", "N1", "0 vazia, 1 passando, 2 parado"),
                  Symbol("Livre", "M0.0", "eclusa sem missao"), Symbol("Ultimo_Desceu", "M0.1", "ultimo barco desceu")]
    d = [f"D{k}" for k in range(1, 8)]
    u = [f"U{k}" for k in range(1, 8)]
    p.symbols += [Symbol(n, f"M1.{k}", "descer: etapa") for k, n in enumerate(d)]
    p.symbols += [Symbol(n, f"M2.{k}", "subir: etapa") for k, n in enumerate(u)]

    def go(cond, frm, to, comment=""):
        return Rung([Contact("XIC", frm), *cond], [Coil("OTL", to), Coil("OTU", frm)], comment)

    p.rungs = [
        Rung([Contact("XIO", n) for n in d + u], [Coil("OTE", "Livre")], "MISSOES"),
        Rung([Contact("XIC", "Livre"), Contact("XIC", "Barco_Montante"),
              Parallel([[Contact("XIO", "Barco_Jusante")], [Contact("XIO", "Ultimo_Desceu")]])],
             [Coil("OTL", d[0]), Coil("OTL", "Ultimo_Desceu")], "Barco a montante (alterna com jusante)"),
        Rung([Contact("XIC", "Livre"), Contact("XIC", "Barco_Jusante"),
              Parallel([[Contact("XIO", "Barco_Montante")], [Contact("XIC", "Ultimo_Desceu")]])],
             [Coil("OTL", u[0]), Coil("OTU", "Ultimo_Desceu")], "Barco a jusante"),
        go([Contact("XIC", "Jusante_Fechada"), Contact("XIC", "Nivel_Igual_Montante")], d[0], d[1],
           "DESCER: jusante fechada e nivel de montante"),
        go([Contact("XIC", "Montante_Aberta")], d[1], d[2]),
        go([CompareBox("EQU", ["Ocupacao", "2"])], d[2], d[3], "Barco parado na camara"),
        go([Contact("XIC", "Montante_Fechada")], d[3], d[4]),
        go([Contact("XIC", "Nivel_Igual_Jusante")], d[4], d[5]),
        go([Contact("XIC", "Jusante_Aberta")], d[5], d[6]),
        Rung([Contact("XIC", d[6]), CompareBox("EQU", ["Ocupacao", "0"])], [Coil("OTU", d[6])], "Barco saiu"),
        go([Contact("XIC", "Montante_Fechada"), Contact("XIC", "Nivel_Igual_Jusante")], u[0], u[1],
           "SUBIR: montante fechada e nivel de jusante"),
        go([Contact("XIC", "Jusante_Aberta")], u[1], u[2]),
        go([CompareBox("EQU", ["Ocupacao", "2"])], u[2], u[3]),
        go([Contact("XIC", "Jusante_Fechada")], u[3], u[4]),
        go([Contact("XIC", "Nivel_Igual_Montante")], u[4], u[5]),
        go([Contact("XIC", "Montante_Aberta")], u[5], u[6]),
        Rung([Contact("XIC", u[6]), CompareBox("EQU", ["Ocupacao", "0"])], [Coil("OTU", u[6])]),
        Rung([Parallel([[Contact("XIC", d[0]), Contact("XIO", "Jusante_Fechada")], [Contact("XIC", u[3])]]),
              Contact("XIO", "Abre_Jusante")], [Coil("OTE", "Fecha_Jusante")], "SAIDAS com permissivos"),
        Rung([Parallel([[Contact("XIC", u[0]), Contact("XIO", "Montante_Fechada")], [Contact("XIC", d[3])]]),
              Contact("XIO", "Abre_Montante")], [Coil("OTE", "Fecha_Montante")]),
        Rung([Parallel([[Contact("XIC", d[0])], [Contact("XIC", u[4])]]), Contact("XIC", "Jusante_Fechada"),
              Contact("XIO", "Nivel_Igual_Montante"), Contact("XIO", "Valvula_Esvaziamento")],
             [Coil("OTE", "Valvula_Enchimento")], "Encher: so com a jusante fechada"),
        Rung([Parallel([[Contact("XIC", u[0])], [Contact("XIC", d[4])]]), Contact("XIC", "Montante_Fechada"),
              Contact("XIO", "Nivel_Igual_Jusante")], [Coil("OTE", "Valvula_Esvaziamento")],
             "Esvaziar: so com a montante fechada"),
        Rung([Parallel([[Contact("XIC", d[1])], [Contact("XIC", u[5])]]), Contact("XIC", "Nivel_Igual_Montante"),
              Contact("XIC", "Jusante_Fechada"), Contact("XIO", "Montante_Aberta")], [Coil("OTE", "Abre_Montante")],
             "Abrir: nivel igualado e a outra comporta fechada"),
        Rung([Parallel([[Contact("XIC", d[5])], [Contact("XIC", u[1])]]), Contact("XIC", "Nivel_Igual_Jusante"),
              Contact("XIC", "Montante_Fechada"), Contact("XIO", "Jusante_Aberta")], [Coil("OTE", "Abre_Jusante")]),
        Rung([Contact("XIC", d[2]), Contact("XIC", "Montante_Aberta"), CompareBox("EQU", ["Ocupacao", "0"])],
             [Coil("OTE", "Verde_Montante")], "Verde: comporta toda aberta e camara vazia"),
        Rung([Contact("XIC", u[2]), Contact("XIC", "Jusante_Aberta"), CompareBox("EQU", ["Ocupacao", "0"])],
             [Coil("OTE", "Verde_Jusante")]),
    ]
    return p


def car_wash() -> Project:
    p = env_project("lava_rapido", "Lava-rapido de portico", (
        "Receita como mascara de bits. No pagamento a tabela converte o programa (N0) na receita (N1): Simples = 7 "
        "(passadas 1, 2, 3), Completo = 23 (1, 2, 3, 5), Premium = 63 (todas). N2 guarda o bit da passada atual "
        "(1, 2, 4 ... 32): MEQ Receita Passo Passo diz se ela faz parte da receita; se nao fizer, MUL por 2 pula para "
        "a proxima. Cada passada leva o portico de uma ponta a outra (o sentido alterna) com as acoes daquele bit; ao "
        "chegar, Passo dobra. Passo acima de 32: volta o portico a origem e o verde libera a saida."))
    p.symbols += [Symbol("Programa", "N0", "1 Simples, 2 Completo, 3 Premium (do terminal)"),
                  Symbol("Receita", "N1", "mascara das passadas"), Symbol("Passo", "N2", "bit da passada atual"),
                  Symbol("Rodando", "M0.0", "lavagem em andamento"), Symbol("Indo", "M0.1", "passada avancando"),
                  Symbol("Voltando", "M0.2", "passada recuando"), Symbol("Terminou", "M0.3", "todas as passadas feitas"),
                  Symbol("Ativo", "M0.4", "a passada atual faz parte da receita"),
                  Symbol("Movendo", "M0.5", "portico numa passada")]
    p.rungs = [
        Rung([Contact("XIC", "Pagamento_OK"), Contact("XIC", "Carro_Posicionado"), Contact("XIC", "Portico_Origem"),
              Contact("XIO", "Rodando"), Contact("XIO", "Terminou")],
             [Coil("OTL", "Rodando"), MathBox("MOV", ["1", "Passo"])], "INICIO: pago, carro na posicao, portico na origem"),
        Rung([Contact("XIC", "Rodando"), CompareBox("EQU", ["Programa", "1"])], [MathBox("MOV", ["7", "Receita"])],
             "RECEITAS como mascara de bits"),
        Rung([Contact("XIC", "Rodando"), CompareBox("EQU", ["Programa", "2"])], [MathBox("MOV", ["23", "Receita"])]),
        Rung([Contact("XIC", "Rodando"), CompareBox("EQU", ["Programa", "3"])], [MathBox("MOV", ["63", "Receita"])]),
        Rung([CompareBox("MEQ", ["Receita", "Passo", "Passo"])], [Coil("OTE", "Ativo")],
             "A passada atual esta na receita?"),
        Rung([Contact("XIC", "Rodando"), Contact("XIO", "Ativo"), Contact("XIO", "Indo"), Contact("XIO", "Voltando"),
              CompareBox("LEQ", ["Passo", "32"])], [MathBox("MUL", ["Passo", "2", "Passo"])], "Nao esta: pula"),
        Rung([Contact("XIC", "Rodando"), Contact("XIC", "Ativo"), Contact("XIO", "Indo"), Contact("XIO", "Voltando"),
              Contact("XIC", "Portico_Origem")], [Coil("OTL", "Indo")], "PASSADAS: o sentido depende de onde esta"),
        Rung([Contact("XIC", "Rodando"), Contact("XIC", "Ativo"), Contact("XIO", "Indo"), Contact("XIO", "Voltando"),
              Contact("XIC", "Portico_Fim")], [Coil("OTL", "Voltando")]),
        Rung([Contact("XIC", "Indo"), Contact("XIC", "Portico_Fim")],
             [Coil("OTU", "Indo"), MathBox("MUL", ["Passo", "2", "Passo"])], "Chegou: proxima passada"),
        Rung([Contact("XIC", "Voltando"), Contact("XIC", "Portico_Origem")],
             [Coil("OTU", "Voltando"), MathBox("MUL", ["Passo", "2", "Passo"])]),
        Rung([Contact("XIC", "Rodando"), CompareBox("GRT", ["Passo", "32"])],
             [Coil("OTU", "Rodando"), Coil("OTL", "Terminou")], "Todas as passadas da receita"),
        Rung([Parallel([[Contact("XIC", "Indo")], [Contact("XIC", "Voltando")]])], [Coil("OTE", "Movendo")]),
        Rung([Contact("XIC", "Indo"), Contact("XIC", "Emergencia")], [Coil("OTE", "Portico_Avanca")], "MOVIMENTO"),
        Rung([Parallel([[Contact("XIC", "Voltando")], [Contact("XIC", "Terminou"), Contact("XIO", "Portico_Origem")]]),
              Contact("XIC", "Emergencia")], [Coil("OTE", "Portico_Recua")], "Recua na passada ou para voltar a origem"),
        Rung([Contact("XIC", "Movendo"), Parallel([[CompareBox("EQU", ["Passo", "1"])], [CompareBox("EQU", ["Passo", "2"])],
                                                   [CompareBox("EQU", ["Passo", "4"])]])],
             [Coil("OTE", "Agua")], "ACOES de cada passada"),
        Rung([Contact("XIC", "Movendo"), CompareBox("EQU", ["Passo", "2"])], [Coil("OTE", "Shampoo"), Coil("OTE", "Escovas")]),
        Rung([Contact("XIC", "Movendo"), CompareBox("EQU", ["Passo", "8"])], [Coil("OTE", "Cera")]),
        Rung([Contact("XIC", "Movendo"), CompareBox("GEQ", ["Passo", "16"])], [Coil("OTE", "Secador")]),
        Rung([Contact("XIC", "Portico_Origem"), Contact("XIO", "Rodando"),
              Parallel([[Contact("XIO", "Carro_Posicionado")], [Contact("XIC", "Terminou")]])],
             [Coil("OTE", "Semaforo_Verde")], "SEMAFORO: entra ou sai com o portico na origem"),
        Rung([Contact("XIC", "Terminou"), Contact("XIO", "Carro_Posicionado")], [Coil("OTU", "Terminou")], "Carro saiu"),
    ]
    return p


def height_sorting() -> Project:
    p = env_project("separacao_altura", "Separacao por altura", (
        "Rastreamento com registrador de deslocamento sincronizado pelo encoder. Enquanto a caixa passa pela "
        "estacao, o sensor alto memoriza se ela e alta; quando ela termina de passar (borda de descida do sensor "
        "baixo), uma caixa alta marca o bit 0 de N5. Cada pulso do encoder (20 px de esteira) multiplica N5 por 2 "
        "(so 13 bits: acima de 8191 subtrai 8192), e a marcacao vem depois do deslocamento. Com a caixa no centro "
        "do desviador a marca esta perto do bit 11: a janela dos bits 9, 10 e 11 liga o desviador um pouco antes "
        "da caixa chegar e so desliga depois que ela passou."))
    p.symbols += [Symbol("Registro", "N5", "rastreamento: bit k = caixa alta k pulsos depois da estacao"),
                  Symbol("Pulso", "M0.5", "borda de subida do encoder"),
                  Symbol("Alta_Lida", "M0.0", "caixa alta em leitura"),
                  Symbol("Baixo_Anterior", "M0.1", "sensor baixo na varredura anterior"),
                  Symbol("Encoder_Anterior", "M0.2", "encoder na varredura anterior"),
                  Symbol("Fim_Leitura", "M0.6", "borda de descida do sensor baixo"),
                  Symbol("Altas_Lidas", "N6", "altas identificadas"), Symbol("Baixas_Lidas", "N7", "baixas identificadas"),
                  Symbol("Altas_Fim", "N8", "altas no fim"), Symbol("Baixas_Fim", "N9", "baixas no fim"),
                  Symbol("Fim_Altas_Ant", "M1.0", "borda do fim das altas"),
                  Symbol("Fim_Baixas_Ant", "M1.1", "borda do fim das baixas")]
    p.rungs = [
        Rung([Contact("XIC", "Liga")],
             [Coil("OTE", "Esteira_Entrada"), Coil("OTE", "Esteira_Altas"), Coil("OTE", "Esteira_Baixas"),
              Coil("OTE", "Emissor"), Coil("OTE", "Luz_Operando")], "Liga a linha"),
        Rung([Contact("XIC", "Sensor_Baixo"), Contact("XIC", "Sensor_Alto")], [Coil("OTL", "Alta_Lida")],
             "LEITURA: o sensor alto viu a caixa em algum momento"),
        Rung([Contact("XIO", "Sensor_Baixo"), Contact("XIC", "Baixo_Anterior")], [Coil("OTE", "Fim_Leitura")],
             "A caixa terminou de passar pela estacao"),
        Rung([Contact("XIC", "Encoder"), Contact("XIO", "Encoder_Anterior")], [Coil("OTE", "Pulso")],
             "Borda de subida do encoder: um pulso a cada 20 px"),
        Rung([Contact("XIC", "Pulso")], [MathBox("MUL", ["Registro", "2", "Registro"])],
             "DESLOCAMENTO: a marca anda um bit junto com a caixa"),
        Rung([Contact("XIC", "Pulso"), CompareBox("GEQ", ["Registro", "8192"])],
             [MathBox("SUB", ["Registro", "8192", "Registro"])], "So 13 bits"),
        Rung([Contact("XIC", "Fim_Leitura"), Contact("XIC", "Alta_Lida")],
             [MathBox("ADD", ["Registro", "1", "Registro"]), MathBox("ADD", ["Altas_Lidas", "1", "Altas_Lidas"]),
              Coil("OTU", "Alta_Lida")], "Caixa alta: marca o bit 0 (depois do deslocamento)"),
        Rung([Contact("XIC", "Fim_Leitura"), Contact("XIO", "Alta_Lida")],
             [MathBox("ADD", ["Baixas_Lidas", "1", "Baixas_Lidas"])], "Caixa baixa"),
        Rung([Parallel([[CompareBox("MEQ", ["Registro", "1024", "1024"])],
                        [CompareBox("MEQ", ["Registro", "2048", "2048"])],
                        [CompareBox("MEQ", ["Registro", "512", "512"])]])],
             [Coil("OTE", "Desviador")], "JANELA do desviador: bits 9, 10 e 11"),
        Rung([Contact("XIC", "Sensor_Baixo")], [Coil("OTE", "Baixo_Anterior")], "Imagens anteriores"),
        Rung([Contact("XIC", "Encoder")], [Coil("OTE", "Encoder_Anterior")]),
        Rung([Contact("XIC", "Fim_Altas"), Contact("XIO", "Fim_Altas_Ant")],
             [MathBox("ADD", ["Altas_Fim", "1", "Altas_Fim"])], "VERIFICACAO: chegadas no fim de cada esteira"),
        Rung([Contact("XIC", "Fim_Altas")], [Coil("OTE", "Fim_Altas_Ant")]),
        Rung([Contact("XIC", "Fim_Baixas"), Contact("XIO", "Fim_Baixas_Ant")],
             [MathBox("ADD", ["Baixas_Fim", "1", "Baixas_Fim"])]),
        Rung([Contact("XIC", "Fim_Baixas")], [Coil("OTE", "Fim_Baixas_Ant")]),
    ]
    return p


def pick_place() -> Project:
    p = env_project("pick_place", "Pick & place XY", (
        "Coordenadas calculadas e etapas numa palavra. Etapa (N3) guarda o passo do ciclo: 0 espera, 1 vai a "
        "coleta, 2 desce, 3 pega, 4 sobe, 5 vai a vaga, 6 desce, 7 solta, 8 sobe, 9 e 10 trocam o pallet. A vaga "
        "vem do Indice (N2, 0 a 5): Linha = Indice / 3, Coluna = Indice - Linha x 3, X = 330 + Coluna x 90 e "
        "Y = 100 + Linha x 100. Depois de mudar o destino o programa espera 300 ms (o eixo comeca a andar) antes de "
        "olhar Em_Posicao; o Z so desce com X e Y parados e os eixos so andam com o Z em cima."))
    p.symbols += [Symbol("Indice", "N2", "vaga atual do pallet (0 a 5)"), Symbol("Etapa", "N3", "passo do ciclo"),
                  Symbol("Linha", "N4", "linha da vaga"), Symbol("Coluna", "N5", "coluna da vaga"),
                  Symbol("Destino_X", "N10", "setpoint do eixo X (mm)"),
                  Symbol("Destino_Y", "N11", "setpoint do eixo Y (mm)"),
                  Symbol("Partiu_Coleta", "T0", "espera o eixo sair rumo a coleta"),
                  Symbol("Partiu_Vaga", "T1", "espera o eixo sair rumo a vaga"),
                  Symbol("Soltando", "T2", "tempo para o vacuo acabar")]

    def step(n, *cond):
        return [CompareBox("EQU", ["Etapa", str(n)]), *cond]

    def go(n):
        return MathBox("MOV", [str(n), "Etapa"])

    p.rungs = [
        Rung([Contact("XIC", "Liga")], [Coil("OTE", "Luz_Operando")], "Liga"),
        Rung([Contact("XIC", "Liga"), Contact("XIO", "Peca_Na_Coleta")], [Coil("OTE", "Esteira_Pecas")],
             "Esteira traz a proxima peca ate a coleta"),
        Rung(step(0, Contact("XIC", "Liga"), Contact("XIC", "Peca_Na_Coleta"), Contact("XIC", "Pallet_Presente"),
                  Contact("XIC", "Z_Em_Cima")),
             [MathBox("MOV", ["90", "Destino_X"]), MathBox("MOV", ["150", "Destino_Y"]), go(1)],
             "0 -> 1: destino = coleta (X 90, Y 150)"),
        Rung(step(1), [TimerBox("TON", "Partiu_Coleta", 300)]),
        Rung(step(1, Contact("XIC", "Partiu_Coleta.DN"), Contact("XIC", "Em_Posicao")), [go(2)],
             "1 -> 2: parado sobre a peca"),
        Rung(step(2, Contact("XIC", "Z_Embaixo")), [go(3)], "2 -> 3: Z embaixo"),
        Rung(step(3, Contact("XIC", "Peca_Presa")), [go(4)], "3 -> 4: vacuo pegou"),
        Rung(step(4, Contact("XIC", "Z_Em_Cima")),
             [MathBox("DIV", ["Indice", "3", "Linha"]), MathBox("MUL", ["Linha", "3", "Coluna"]),
              MathBox("SUB", ["Indice", "Coluna", "Coluna"]), MathBox("MUL", ["Coluna", "90", "Destino_X"]),
              MathBox("ADD", ["Destino_X", "330", "Destino_X"]), MathBox("MUL", ["Linha", "100", "Destino_Y"]),
              MathBox("ADD", ["Destino_Y", "100", "Destino_Y"]), go(5)],
             "4 -> 5: COORDENADAS da vaga pelo indice"),
        Rung(step(5), [TimerBox("TON", "Partiu_Vaga", 300)]),
        Rung(step(5, Contact("XIC", "Partiu_Vaga.DN"), Contact("XIC", "Em_Posicao")), [go(6)],
             "5 -> 6: parado sobre a vaga"),
        Rung(step(6, Contact("XIC", "Z_Embaixo")), [go(7)], "6 -> 7: Z embaixo"),
        Rung(step(7), [TimerBox("TON", "Soltando", 300)]),
        Rung(step(7, Contact("XIC", "Soltando.DN")), [go(8)], "7 -> 8: peca solta"),
        Rung(step(8, Contact("XIC", "Z_Em_Cima")), [MathBox("ADD", ["Indice", "1", "Indice"])],
             "8: vaga feita"),
        Rung(step(8, Contact("XIC", "Z_Em_Cima"), CompareBox("GEQ", ["Indice", "6"])), [go(9)],
             "Pallet cheio: troca"),
        Rung(step(8, Contact("XIC", "Z_Em_Cima"), CompareBox("LES", ["Indice", "6"])), [go(0)]),
        Rung(step(9, Contact("XIO", "Pallet_Presente")), [go(10)], "9 -> 10: o pallet cheio saiu"),
        Rung(step(10, Contact("XIC", "Pallet_Presente")), [MathBox("MOV", ["0", "Indice"]), go(0)],
             "10 -> 0: pallet vazio no lugar"),
        Rung([Parallel([[CompareBox("LIM", ["2", "Etapa", "3"])], [CompareBox("LIM", ["6", "Etapa", "7"])]])],
             [Coil("OTE", "Z_Desce")], "SAIDAS: Z desce nas etapas 2, 3, 6 e 7"),
        Rung([CompareBox("LIM", ["3", "Etapa", "6"])], [Coil("OTE", "Ventosa")], "Ventosa da pega ate descer na vaga"),
        Rung([CompareBox("LIM", ["9", "Etapa", "10"])], [Coil("OTE", "Esteira_Pallets")], "Troca do pallet"),
    ]
    return p


def warehouse() -> Project:
    p = env_project("armazem", "Armazem automatico", (
        "Mapa de ocupacao e etapas com transicoes em ordem inversa. Ocupacao (N20) tem um bit por celula: a "
        "celula n vale 2^(n-1), que a tabela do inicio poe em Peso conforme o Destino. Livre (N12) e a primeira "
        "celula com o bit em 0 (MEQ Ocupacao Peso_n 0, de 15 para 1: a ultima escrita vence); 0 = cheio. As "
        "transicoes estao escritas da ultima etapa para a primeira: a etapa que acabou de comecar so e testada na "
        "varredura seguinte, quando Em_Posicao ja corresponde ao destino novo. Guardar: etapas 1 a 8; retirar o "
        "pedido de N1: etapas 21 a 28. Pedidos tem prioridade."))
    p.symbols += [Symbol("Pedido_Operador", "N1", "celula pedida (o programa zera ao aceitar)"),
                  Symbol("Etapa", "N3", "passo do ciclo"), Symbol("Destino", "N10", "posicao do transelevador"),
                  Symbol("Livre", "N12", "primeira celula livre (0 = cheio)"),
                  Symbol("Peso", "N13", "bit da celula de Destino"), Symbol("Ocupacao", "N20", "um bit por celula")]

    def step(n, *cond):
        return [CompareBox("EQU", ["Etapa", str(n)]), *cond]

    def go(n):
        return MathBox("MOV", [str(n), "Etapa"])

    rungs = []
    for n in range(1, 16):
        rungs.append(Rung([CompareBox("EQU", ["Destino", str(n)])], [MathBox("MOV", [str(1 << (n - 1)), "Peso"])],
                          "TABELA: peso (bit) da celula de destino" if n == 1 else ""))
    rungs.append(Rung([], [MathBox("MOV", ["0", "Livre"])], "PRIMEIRA CELULA LIVRE (de 15 para 1)"))
    for n in range(15, 0, -1):
        rungs.append(Rung([CompareBox("MEQ", ["Ocupacao", str(1 << (n - 1)), "0"])], [MathBox("MOV", [str(n), "Livre"])]))
    rungs += [
        Rung(step(28, Contact("XIC", "Garfo_Centro")), [go(0)], "RETIRAR (transicoes da ultima para a primeira)"),
        Rung(step(27, Contact("XIC", "Garfo_Embaixo")), [go(28)], "27: desceu, caixa na saida"),
        Rung(step(26, Contact("XIC", "Garfo_Estendido")), [go(27)]),
        Rung(step(25, Contact("XIC", "Em_Posicao"), Contact("XIC", "Saida_Livre")), [go(26)]),
        Rung(step(24, Contact("XIC", "Garfo_Centro")),
             [MathBox("SUB", ["Ocupacao", "Peso", "Ocupacao"]), MathBox("MOV", ["16", "Destino"]), go(25)],
             "24: caixa no garfo, celula vazia; vai para a saida"),
        Rung(step(23, Contact("XIC", "Garfo_Em_Cima")), [go(24)]),
        Rung(step(22, Contact("XIC", "Garfo_Estendido")), [go(23)]),
        Rung(step(21, Contact("XIC", "Em_Posicao")), [go(22)]),
        Rung(step(8, Contact("XIC", "Garfo_Centro")), [go(0)], "GUARDAR"),
        Rung(step(7, Contact("XIC", "Garfo_Embaixo")), [MathBox("ADD", ["Ocupacao", "Peso", "Ocupacao"]), go(8)],
             "7: caixa deixada na celula: marca ocupada"),
        Rung(step(6, Contact("XIC", "Garfo_Estendido")), [go(7)]),
        Rung(step(5, Contact("XIC", "Em_Posicao")), [go(6)]),
        Rung(step(4, Contact("XIC", "Garfo_Centro")), [MathBox("MOV", ["Livre", "Destino"]), go(5)],
             "4: caixa no garfo; vai para a primeira celula livre"),
        Rung(step(3, Contact("XIC", "Garfo_Em_Cima")), [go(4)]),
        Rung(step(2, Contact("XIC", "Garfo_Estendido")), [go(3)]),
        Rung(step(1, Contact("XIC", "Em_Posicao")), [go(2)]),
        Rung(step(0, Contact("XIC", "Liga"), CompareBox("GRT", ["Pedido_Operador", "0"])),
             [MathBox("MOV", ["Pedido_Operador", "Destino"]), MathBox("MOV", ["0", "Pedido_Operador"]), go(21)],
             "0: pedido do operador primeiro"),
        Rung(step(0, Contact("XIC", "Liga"), Contact("XIC", "Caixa_Na_Entrada"), CompareBox("GRT", ["Livre", "0"])),
             [MathBox("MOV", ["0", "Destino"]), go(1)], "0: caixa esperando e lugar livre"),
        Rung([Parallel([[CompareBox("LIM", ["2", "Etapa", "3"])], [CompareBox("LIM", ["6", "Etapa", "7"])],
                        [CompareBox("LIM", ["22", "Etapa", "23"])], [CompareBox("LIM", ["26", "Etapa", "27"])]])],
             [Coil("OTE", "Garfo_Avanca")], "SAIDAS: garfo avanca para pegar (2-3) e para deixar (6-7)"),
        Rung([Parallel([[CompareBox("LIM", ["3", "Etapa", "6"])], [CompareBox("LIM", ["23", "Etapa", "26"])]])],
             [Coil("OTE", "Garfo_Sobe")], "Garfo alto da pega ate deixar"),
        Rung([Contact("XIC", "Liga")], [Coil("OTE", "Esteira_Entrada"), Coil("OTE", "Esteira_Saida"),
                                        Coil("OTE", "Luz_Operando")]),
        Rung([CompareBox("EQU", ["Livre", "0"])], [Coil("OTE", "Luz_Cheio")], "Armazem cheio"),
    ]
    p.rungs = rungs
    return p


def weight_sorting() -> Project:
    p = env_project("separacao_peso", "Separacao por peso", (
        "Fila FIFO de palavras feita com MOV. A esteira da balanca para com a caixa inteira na plataforma; com o "
        "peso estavel a classe (1 no peso, 2 leve, 3 pesada) entra no primeiro lugar vazio da fila N20..N24. As "
        "entradas na fila estao escritas do ultimo lugar para o primeiro: assim so o primeiro vazio recebe a classe. "
        "N20 e a caixa que chega ao transferidor: com ela no lugar a esteira de desvio para (se nao for boa) e o "
        "transferidor leva a caixa para a rampa certa. Quando a fotocelula do transferidor desliga a caixa saiu: "
        "a fila anda (N21 -> N20, ..., 0 -> N24). Com a fila cheia a caixa espera na balanca."))
    p.symbols += [Symbol("Peso", "N0", "peso na balanca (g)"), Symbol("Classe", "N10", "classe da caixa pesada"),
                  Symbol("Fila_1", "N20", "classe da caixa que chega ao transferidor"),
                  Symbol("Fila_2", "N21", ""), Symbol("Fila_3", "N22", ""), Symbol("Fila_4", "N23", ""),
                  Symbol("Fila_5", "N24", "ultimo lugar da fila"),
                  Symbol("Pesar", "M0.0", "pesagem valida nesta varredura"),
                  Symbol("Pesada", "M0.1", "a caixa na balanca ja entrou na fila"),
                  Symbol("Balanca_Anterior", "M0.2", "caixa na balanca na varredura anterior"),
                  Symbol("Transf_Anterior", "M0.3", "caixa no transferidor na varredura anterior"),
                  Symbol("Saiu", "M0.4", "a caixa deixou o transferidor")]
    p.rungs = [
        Rung([Contact("XIC", "Liga")], [Coil("OTE", "Esteira_Entrada"), Coil("OTE", "Emissor"),
                                        Coil("OTE", "Luz_Operando")], "Liga a linha"),
        Rung([Contact("XIC", "Liga"), Parallel([[Contact("XIO", "Caixa_Na_Balanca")], [Contact("XIC", "Pesada")]])],
             [Coil("OTE", "Esteira_Balanca")], "BALANCA: para com a caixa ainda nao pesada sobre a plataforma"),
        Rung([Contact("XIC", "Caixa_Na_Balanca"), Contact("XIC", "Peso_Estavel"), Contact("XIO", "Pesada"),
              CompareBox("EQU", ["Fila_5", "0"])], [Coil("OTE", "Pesar")], "Peso estavel e lugar na fila"),
        Rung([Contact("XIC", "Pesar")], [MathBox("MOV", ["1", "Classe"])], "CLASSE: 1 no peso"),
        Rung([Contact("XIC", "Pesar"), CompareBox("LES", ["Peso", "450"])], [MathBox("MOV", ["2", "Classe"])],
             "2 leve (abaixo de 450 g)"),
        Rung([Contact("XIC", "Pesar"), CompareBox("GRT", ["Peso", "550"])], [MathBox("MOV", ["3", "Classe"])],
             "3 pesada (acima de 550 g)"),
        Rung([Contact("XIO", "Caixa_No_Transferidor"), Contact("XIC", "Transf_Anterior")], [Coil("OTE", "Saiu")],
             "SAIDA DA FILA: a caixa deixou o transferidor"),
        Rung([Contact("XIC", "Saiu")],
             [MathBox("MOV", ["Fila_2", "Fila_1"]), MathBox("MOV", ["Fila_3", "Fila_2"]),
              MathBox("MOV", ["Fila_4", "Fila_3"]), MathBox("MOV", ["Fila_5", "Fila_4"]),
              MathBox("MOV", ["0", "Fila_5"])], "A fila anda um lugar"),
        Rung([Contact("XIC", "Pesar"), CompareBox("NEQ", ["Fila_4", "0"]), CompareBox("EQU", ["Fila_5", "0"])],
             [MathBox("MOV", ["Classe", "Fila_5"])], "ENTRADA NA FILA: primeiro lugar vazio (do ultimo para o primeiro)"),
        Rung([Contact("XIC", "Pesar"), CompareBox("NEQ", ["Fila_3", "0"]), CompareBox("EQU", ["Fila_4", "0"])],
             [MathBox("MOV", ["Classe", "Fila_4"])]),
        Rung([Contact("XIC", "Pesar"), CompareBox("NEQ", ["Fila_2", "0"]), CompareBox("EQU", ["Fila_3", "0"])],
             [MathBox("MOV", ["Classe", "Fila_3"])]),
        Rung([Contact("XIC", "Pesar"), CompareBox("NEQ", ["Fila_1", "0"]), CompareBox("EQU", ["Fila_2", "0"])],
             [MathBox("MOV", ["Classe", "Fila_2"])]),
        Rung([Contact("XIC", "Pesar"), CompareBox("EQU", ["Fila_1", "0"])], [MathBox("MOV", ["Classe", "Fila_1"])]),
        Rung([Contact("XIC", "Pesar")], [Coil("OTL", "Pesada")], "A caixa ja esta na fila: pode seguir"),
        Rung([Contact("XIO", "Caixa_Na_Balanca"), Contact("XIC", "Balanca_Anterior")], [Coil("OTU", "Pesada")],
             "Saiu da balanca: a proxima ainda nao foi pesada"),
        Rung([Contact("XIC", "Liga"),
              Parallel([[Contact("XIO", "Caixa_No_Transferidor")], [CompareBox("EQU", ["Fila_1", "1"])]])],
             [Coil("OTE", "Esteira_Desvio")], "DESVIO: so anda se a caixa no transferidor for boa"),
        Rung([Contact("XIC", "Caixa_No_Transferidor"), CompareBox("EQU", ["Fila_1", "2"])],
             [Coil("OTE", "Transfere_Leves")], "Transferidor: leves para cima"),
        Rung([Contact("XIC", "Caixa_No_Transferidor"), CompareBox("EQU", ["Fila_1", "3"])],
             [Coil("OTE", "Transfere_Pesadas")], "pesadas para baixo"),
        Rung([Contact("XIC", "Caixa_Na_Balanca")], [Coil("OTE", "Balanca_Anterior")], "Imagens anteriores"),
        Rung([Contact("XIC", "Caixa_No_Transferidor")], [Coil("OTE", "Transf_Anterior")]),
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
               "ambientes/detector_gas.ladproj": gas_detection, "ambientes/balanca.ladproj": scale,
               "ambientes/estufa.ladproj": greenhouse, "ambientes/ponte_rolante.ladproj": overhead_crane,
               "ambientes/venda.ladproj": vending,
               "ambientes/nivel_pi.ladproj": level_pi,
               "ambientes/paletizador.ladproj": palletizer,
               "ambientes/forno_rampa.ladproj": furnace,
               "ambientes/demanda_energia.ladproj": demand_control,
               "ambientes/gerador_qta.ladproj": transfer_switch,
               "ambientes/eclusa.ladproj": canal_lock,
               "ambientes/lava_rapido.ladproj": car_wash,
               "ambientes/separacao_altura.ladproj": height_sorting,
               "ambientes/pick_place.ladproj": pick_place,
               "ambientes/armazem.ladproj": warehouse,
               "ambientes/separacao_peso.ladproj": weight_sorting}
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
