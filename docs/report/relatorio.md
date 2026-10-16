# Plataforma de programação LADDER para CLP baseado em ESP32

**Disciplina:** Controladores Lógicos Programáveis — [PREENCHER: instituição, curso, professor]
**Integrantes:** [PREENCHER]
**Data:** [PREENCHER]

> Itens marcados **[PREENCHER]** dependem do grupo (nomes, divisão real de
> tarefas, resultados no hardware, evidências). Não substitua por conteúdo
> fictício: a seção 11 deve registrar apenas ensaios efetivamente executados.

## Resumo

Este trabalho apresenta uma plataforma completa para programação de um CLP
didático baseado em ESP32 com oito saídas a relé: uma IDE para Windows com
editor gráfico LADDER, compilador, simulador e monitor online, e um firmware
interpretador. O diagrama é compilado para um bytecode compacto (LDRB, até
8,7 KiB), executado por duas máquinas virtuais — uma em Python, no simulador,
e uma em C, no firmware — que seguem uma única especificação formal e são
comparadas varredura a varredura por testes diferenciais. A transferência é
transacional, com CRC e validação no dispositivo antes da ativação. A lógica
do dispositivo foi escrita em C portátil, o que permitiu testá-la no PC por
meio de um "dispositivo virtual". [PREENCHER: uma frase com o resultado dos
ensaios na placa.]

## 1. Introdução e objetivos

O objetivo é permitir que estudantes criem programas LADDER, validem a lógica
em simulação e os executem em hardware real, observando o comportamento no
monitor. Requisitos centrais: edição visual por arrastar e soltar; instruções
NA, NF, bobina, SET, RESET, TON, TOF, RTO, CTU, CTD e RES; simulação idêntica
ao hardware; transferência segura; monitor online; documentação para
continuidade por outras turmas. A análise completa está em `docs/analysis.md`.

## 2. Fundamentação teórica

**CLP.** Controlador digital que executa ciclicamente: lê as entradas para uma
imagem de processo, avalia o programa e atualiza as saídas. O determinismo do
ciclo é o que diferencia um CLP de um microcontrolador programado ad hoc.

**LADDER (IEC 61131-3).** Linguagem gráfica derivada de diagramas de relés:
contatos em série realizam E lógico, em paralelo OU, contatos normalmente
fechados realizam a negação; bobinas escrevem o resultado. Temporizadores
(TON, TOF, retentivo) e contadores são blocos com estado interno. Este
trabalho usa a nomenclatura XIC/XIO/OTE/OTL/OTU/RES, comum em controladores
Allen-Bradley, explicando na interface a correspondência com NA/NF/SET/RESET.

**Ordem de avaliação.** Redes são avaliadas de cima para baixo, da esquerda
para a direita; escritas têm efeito imediato para as redes seguintes. Essa
regra explica, por exemplo, por que duas bobinas no mesmo endereço resultam
no valor da última.

## 3. Arquitetura do sistema

Ver `docs/architecture.md`. Três partes: (i) Desktop em Python + PySide6
(pacotes `core`, `model`, `compiler`, `sim`, `comm`, `ui`, `cli`); (ii)
firmware em C/C++ (bibliotecas portáteis `ladder_vm` e `plc_core` + camada
específica do ESP32); (iii) contratos compartilhados (`isa.json`,
`protocol.json`, vetores de teste). Decisões registradas nos ADRs 0001–0006.

## 4. Modelo intermediário

O projeto (`.ladproj`, JSON versionado) representa cada rede como árvore
série/paralelo — o editor só permite estruturas válidas. O compilador gera a
imagem **LDRB v1.0** (`docs/intermediate-format.md`): cabeçalho de 32 bytes,
tabelas de temporizadores e contadores, instruções de 4 bytes (opcode, área,
índice) e CRC-32. A validação tem ordem normativa idêntica no Desktop e no
firmware, garantindo o mesmo código de erro para a mesma imagem. Há também
uma forma textual (LIL) para exportação, importação e testes.

## 5. Funcionamento do interpretador

A avaliação usa um registrador RLO (resultado lógico) e uma pilha de ramos:
`SOR` inicia a rede com RLO = 1; `XIC/XIO` fazem E com o bit ou seu
complemento; `BST/NXB/BND` acumulam o OU dos ramos; instruções de saída não
alteram o RLO. Após cada instrução, o RLO é registrado em `power[pc]`, usado
para animar o fluxo de energia no simulador e no monitor. Não há laços nem
saltos: o tempo de execução é limitado pelo número de instruções (≤ 2048).

## 6. Ciclo de varredura

No dispositivo (tarefa FreeRTOS, período de 10 ms com `vTaskDelayUntil`):
leitura das entradas (74HC165), cálculo de `dt` em milissegundos com resto em
microssegundos (`esp_timer`), avaliação das redes, escrita das saídas
(74HC595), estatísticas e watchdog (varredura > 50 ms → FAULT). Em STOP,
FAULT e durante a carga, as saídas vão para o estado seguro configurável.
A VM não lê relógio: recebe `dt`, o que torna a simulação determinística.

## 7. Temporizadores e contadores

Especificação formal com pseudocódigo em `docs/ladder-specification.md` §5.
Unidade 1 ms, soma saturada no preset, sem estouro. A varredura que habilita
um temporizador não acumula; o atraso efetivo fica entre PRE e PRE + 1
período. TOF mantém DN por PRE ms após a desabilitação; reabilitação zera o
acumulado. RTO preserva o acumulado até RES. Contadores contam bordas de
subida (com memória de borda que o RES não apaga, evitando contagem espúria
com a entrada mantida); CTU termina em ACC ≥ PRE, CTD parte do preset e
termina em ACC ≤ 0; limites de 32 bits saturam com OV/UN.

## 8. Protocolo de comunicação

LDP v1 (`docs/communication-protocol.md`): quadros binários com CRC-16,
número de sequência e cache de idempotência, permitindo retransmissão segura.
A transferência é transacional: blocos para uma área de staging, verificação
de tamanho e CRC-32, validação completa da imagem, verificação de E/S,
gravação atômica em LittleFS e ativação; qualquer falha preserva o programa
anterior. Modbus RTU é oferecido apenas para leitura por supervisórios.

## 9. Integração com o ESP32

Placa ESP32 com 8 relés acionados por 74HC595 e 8 entradas optoacopladas lidas
por 74HC165; mapeamentos e polaridades obtidos do projeto de referência
(MIT, Oliver Dippel) e isolados em `board_config.h`. Inicialização segura:
`/OE` desativado até carregar "todos desligados". Firmware compilado com
PlatformIO (espressif32 6.9.0): RAM 13,7%, flash 23,8%.
[PREENCHER: confirmação dos mapeamentos e polaridades na placa do grupo.]

## 10. Metodologia de desenvolvimento

Desenvolvimento incremental em nove etapas, cada uma encerrada com código,
testes, documentação e commit (`docs/development-guide.md`, histórico Git).
Especificação antes da implementação; vetores de teste compartilhados como
contrato executável; geração automática dos headers C a partir dos JSON.
[PREENCHER: como o grupo se organizou, reuniões, revisão de código.]

Uso de ferramentas de IA: [PREENCHER: declarar conforme as regras da
disciplina — por exemplo, que um assistente de programação foi usado para
gerar código e documentação revisados pelo grupo.]

## 11. Estratégia e resultados dos testes

Estratégia em `docs/testing.md`. Resultados obtidos em 2026-10-16
(Windows 11, Python 3.11.9, gcc 6.3.0):

| Conjunto | Resultado |
|---|---|
| Suíte automatizada (núcleo, compilador, simulador, interface, comunicação) | 207 testes aprovados |
| Equivalência VM Python × VM C | 18 vetores + 150 programas aleatórios × 80 varreduras + 300 imagens corrompidas, sem divergência |
| Sensibilidade dos testes | defeito injetado no TOF da VM C detectado por 3 testes |
| Vetores executados no firmware (dispositivo virtual, `TEST_SCAN`) | 18/18 idênticos |
| Falhas de comunicação (dispositivo virtual) | CRC errado, imagem inválida, blocos fora de ordem, retransmissão, queda de energia na carga, timeout, incompatibilidade, watchdog, flash corrompida: comportamento conforme especificado |
| Firmware ESP32 | compila sem avisos |
| Ensaios na placa (H0–H14, `docs/hardware-test-procedure.md`) | [PREENCHER: resultados observados e evidências] |
| Demonstração final (`docs/demo-script.md`) | [PREENCHER] |

## 12. Divisão das tarefas

[PREENCHER com o trabalho realmente realizado por cada integrante. Sugestão
de papéis em `docs/development-guide.md` §3.]

| Integrante | Responsabilidades | Principais entregas |
|---|---|---|
| [PREENCHER] | | |

## 13. Limitações e melhorias futuras

- Ensaios no hardware pendentes até o fechamento deste documento [atualizar].
- Sem memória retentiva entre partidas (STOP→RUN é partida a frio).
- Wi-Fi/TCP: o Desktop tem o transporte, o firmware ainda não.
- Não há forçamento de E/S nem edição online (com o CLP em RUN).
- Sem instruções de comparação, aritmética ou detecção de borda (ONS) — a ISA
  prevê extensão por versão menor.
- A placa não mede o estado real dos contatos dos relés.
- Não é um CLP de segurança.

## 14. Referências

- IEC 61131-3:2013. Programmable controllers — Part 3: Programming languages.
- ROCKWELL AUTOMATION. Logix 5000 Controllers General Instructions Reference Manual (publicação 1756-RM003).
- PETRUZELLA, F. D. Programmable Logic Controllers. McGraw-Hill.
- FRANCHI, C. M.; CAMARGO, V. L. A. Controladores Lógicos Programáveis: Sistemas Discretos. Érica.
- ESPRESSIF SYSTEMS. ESP32 Technical Reference Manual; ESP-IDF Programming Guide.
- MODBUS ORGANIZATION. MODBUS Application Protocol Specification V1.1b3; MODBUS over Serial Line Specification and Implementation Guide V1.02.
- Folhas de dados 74HC595 (registrador de deslocamento com latch) e 74HC165 (registrador paralelo-série).
- littlefs-project/littlefs (GitHub).
- Qt for Python (PySide6) — documentação oficial.
- multigcs/esp32_relay_x8_modbus_303e32dc812 (GitHub, MIT).
- Pedrofrac/Trabalho-Final-CLP (GitHub).
[PREENCHER: completar com edição/ano das obras efetivamente consultadas, no padrão da instituição.]

## 15. Apêndices e evidências

- A: especificação LADDER (`docs/ladder-specification.md`)
- B: formato LDRB (`docs/intermediate-format.md`) e protocolo (`docs/communication-protocol.md`)
- C: roteiro e resultados de hardware (`docs/hardware-test-procedure.md`) [PREENCHER evidências]
- D: roteiro da demonstração (`docs/demo-script.md`) [PREENCHER: link do vídeo]
- E: saída de `python -m pytest -q` e de `python -m ladderide.cli --port COMx equivalence`
