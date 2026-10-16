# Especificação semântica LADDER — v1.0 (normativa)

Este documento é a **referência** para o simulador do Desktop
(`desktop/src/ladderide/core/vm.py`) e para o interpretador do firmware
(`firmware/lib/ladder_vm/ladder_vm.c`). Qualquer mudança de comportamento
começa aqui, depois nos vetores de `shared/test-vectors/` e só então no código.
Os códigos numéricos (opcodes, áreas, erros) estão em
`shared/specifications/isa.json`.

## 1. Modelo de memória

| Área | Sintaxe | Tamanho (v1) | Escrita pelo programa | Observações |
|---|---|---|---|---|
| Entradas | `I0.0`…`I1.7` | `n_inputs` ≤ 16 | não | Imagem congelada no início da varredura |
| Saídas | `Q0.0`…`Q1.7` | `n_outputs` ≤ 16 | sim | Imagem; copiada para os relés no fim da varredura |
| Marcadores | `M0.0`…`M31.7` | `n_markers` ≤ 256 | sim | Memória interna, não retentiva |
| Sistema | `S0.0`…`S0.3` | 4 | não | Ver §1.1 |
| Temporizadores | `Tn`, `Tn.EN`, `Tn.TT`, `Tn.DN`, `Tn.ACC` | ≤ 32 | por instrução | ACC em ms |
| Contadores | `Cn`, `Cn.DN`, `Cn.OV`, `Cn.UN`, `Cn.ACC` | ≤ 32 | por instrução | ACC inteiro de 32 bits com sinal |

Endereço `X<byte>.<bit>` corresponde ao índice linear `byte*8 + bit`.

### 1.1 Bits de sistema

| Bit | Nome | Valor |
|---|---|---|
| `S0.0` | FIRST_SCAN | 1 apenas durante a primeira varredura após a partida a frio |
| `S0.1` | ALWAYS_ON | sempre 1 |
| `S0.2` | ALWAYS_OFF | sempre 0 |
| `S0.3` | CLOCK_1S | `fase < 500`, onde `fase` (ms, 0–999) avança `dt mod 1000` a cada varredura, exceto a primeira |

## 2. Ciclo de varredura

Uma varredura recebe a máscara de entradas físicas e `dt` = milissegundos
decorridos desde o início da varredura anterior (tempo monotônico medido pelo
hospedeiro: `esp_timer` no ESP32, tempo virtual no simulador).

1. **Base de tempo:** se for a primeira varredura após a partida a frio, `dt := 0`.
   Caso contrário, `fase := (fase + dt mod 1000) mod 1000`.
2. **Imagem de entradas:** `I[k] := bit k da máscara`, para `k < n_inputs`.
   As entradas **não mudam** durante a varredura.
3. **Avaliação:** as instruções são executadas em ordem, da primeira à última
   (redes em ordem crescente; dentro da rede, na ordem da listagem).
   Toda escrita (bobina, temporizador, contador, RES) tem efeito **imediato**:
   instruções posteriores na mesma varredura enxergam o novo valor; anteriores,
   só na próxima varredura.
4. Após cada instrução, `power[pc] := RLO` (usado para animar o fluxo de energia).
5. **Fim:** `FIRST_SCAN := 0`, `scan_count := scan_count + 1 (mod 2³²)`;
   a máscara de saídas é `Q[0..n_outputs-1]`.

As fases de E/S física (leitura das entradas antes, escrita dos relés depois,
publicação para o monitor, medição do tempo de varredura) pertencem ao
hospedeiro, não à VM — ver `docs/architecture.md`.

### 2.1 Partida a frio (STOP → RUN, carga de programa, energização)

`I`, `Q`, `M` := 0; todos os temporizadores := `{ACC=0, EN=TT=DN=0}`;
contadores UP := `{ACC=0}`, DOWN := `{ACC=PRE}`, `DN` recalculado, `OV=UN=0`,
memória de borda := 0; `scan_count := 0`; `FIRST_SCAN := 1`; `fase := 0`.

Na v1 **não há memória retentiva entre partidas**: bits travados por OTL,
acumuladores RTO e contadores voltam ao estado inicial em toda transição para
RUN. (Retentividade em flash é uma extensão planejada.)

### 2.2 STOP e FAULT

A VM não é executada. O estado da VM permanece congelado para inspeção.
As saídas físicas vão para o **estado seguro** (§6). Ao voltar para RUN ocorre
partida a frio.

## 3. Avaliação lógica: RLO e ramificações

`RLO` (*result of logic operation*) é o "fluxo de energia" na posição atual da rede.

| Instrução | Efeito |
|---|---|
| `SOR` | `RLO := 1` (trilho esquerdo); pilha de ramos esvaziada |
| `XIC b` | contato NA: `RLO := RLO AND b` |
| `XIO b` | contato NF: `RLO := RLO AND NOT b` |
| `NOT` | `RLO := NOT RLO` |
| `BST` | empilha `{entrada := RLO, acumulado := 0}`; RLO inalterado |
| `NXB` | `topo.acumulado := topo.acumulado OR RLO`; `RLO := topo.entrada` |
| `BND` | `RLO := topo.acumulado OR RLO`; desempilha |
| `EOR` | nada (a validação garante pilha vazia) |

Série = AND, paralelo = OR, contato NF/NOT = negação. Profundidade máxima de
aninhamento: 8.

**Instruções de saída não alteram o RLO.** Assim, várias saídas podem ficar em
paralelo (`BST OTE Q0.0 NXB TON T0 BND`) recebendo a mesma condição.

## 4. Bobinas

| Instrução | Efeito |
|---|---|
| `OTE b` | `b := RLO` (bobina convencional) |
| `OTL b` | se `RLO`: `b := 1` (SET/latch); senão nada |
| `OTU b` | se `RLO`: `b := 0` (RESET/unlatch); senão nada |

Destinos permitidos: `Q` e `M`.

**Bobinas duplicadas e endereços compartilhados.** São permitidas e executadas
sequencialmente: vale a última escrita da varredura; redes intermediárias veem
o valor escrito até ali (vetor `bobina_duplicada_ordem_sequencial`). O
compilador do Desktop emitirá **aviso** para mais de uma `OTE` no mesmo
endereço e para mistura de `OTE` com `OTL/OTU`.

**SET e RESET no mesmo endereço e na mesma varredura:** prevalece a instrução
executada por último (vetor `set_reset_mesmo_endereco`). Para "RESET
prioritário", coloque o `OTU` depois do `OTL`.

## 5. Temporizadores e contadores

Unidade: **1 ms**. Preset: 0 a 2 147 483 647 ms (≈ 24,8 dias). `ACC` nunca
excede o preset (soma saturada: `ACC := min(ACC + dt, PRE)`, sem estouro).
Cada temporizador/contador é declarado com um tipo e pode ser acionado por
**no máximo uma** instrução TON/TOF/RTO/CTU/CTD (a validação rejeita
duplicatas); `RES` pode aparecer quantas vezes for necessário.

**Precisão.** O tempo só é observado nas varreduras. A varredura que habilita o
temporizador não acumula (o temporizador ainda não estava habilitado no início
do intervalo); portanto o atraso efetivo fica entre `PRE` e `PRE + período de
varredura`. Com varredura de 10 ms, um TON de 100 ms conclui na 11ª varredura
habilitada (vetor `ton_basico`).

Notação: `prev := EN` (valor da execução anterior); depois `EN := RLO`.

### 5.1 TON — retardo na energização

```
se RLO:
    se prev e não DN: ACC := min(ACC + dt, PRE)
    DN := (ACC >= PRE);  TT := não DN
senão:
    ACC := 0; DN := 0; TT := 0
```
Preset 0: DN = 1 na primeira varredura habilitada.

### 5.2 TOF — retardo na desenergização

```
se RLO:
    ACC := 0; DN := 1; TT := 0
senão se DN:
    se não prev: ACC := min(ACC + dt, PRE)     # a varredura da queda não acumula
    se ACC >= PRE: DN := 0; TT := 0
    senão: TT := 1
senão:
    TT := 0
```
Reativação durante a temporização: `ACC := 0`, `DN` permanece 1. Após concluir,
`ACC` permanece igual ao preset até a próxima habilitação. Na partida a frio com
RLO = 0, DN = 0 (nada a temporizar).

### 5.3 RTO — retardo retentivo

```
se RLO:
    se prev e não DN: ACC := min(ACC + dt, PRE)
    DN := (ACC >= PRE);  TT := não DN
senão:
    TT := 0          # ACC e DN preservados
```
Só `RES` (ou a partida a frio) zera `ACC` e `DN`. A varredura de reabilitação
não acumula (vetor `rto_retencao_e_reset`).

### 5.4 CTU / CTD — contadores por borda de subida

Contagem **por borda de subida** do RLO; nível mantido não conta de novo.
Cada contador guarda a memória de borda `prev` (inicia em 0 — uma entrada já
ativa na primeira varredura conta uma vez; vetor `ctu_entrada_ativa_na_partida`).

```
borda := RLO e não prev;  prev := RLO
CTU (tipo UP):   se borda: se ACC = 2³¹-1: OV := 1  senão ACC := ACC + 1
                 DN := (ACC >= PRE)
CTD (tipo DOWN): se borda: se ACC = -2³¹: UN := 1   senão ACC := ACC - 1
                 DN := (ACC <= 0)
```
O contador UP continua contando acima do preset; o DOWN continua abaixo de zero
(valores negativos). Nos limites de 32 bits, o valor satura e o bit OV/UN é
ligado (só são apagados por RES/partida a frio).

### 5.5 RES — reset

Executa somente se `RLO = 1`.

| Alvo | Efeito |
|---|---|
| TON, TOF, RTO | `ACC := 0; EN := 0; TT := 0; DN := 0` |
| Contador UP | `ACC := 0; OV := UN := 0; DN := (0 >= PRE)` |
| Contador DOWN | `ACC := PRE; OV := UN := 0; DN := (PRE <= 0)` |

`RES` **não** altera a memória de borda do contador: se a entrada de contagem
continuar ativa após o reset, não há nova contagem (vetor
`ctu_borda_e_reset_com_entrada_mantida`). Como `EN := 0`, um TON ainda
habilitado recomeça na varredura seguinte sem acumular aquele intervalo.

**Reset na mesma varredura** de outra instrução do mesmo elemento: vale a
ordem de execução (vetores `res_contador_mesma_varredura` e
`res_temporizador_mesma_varredura`).

## 6. Saídas seguras e estados do dispositivo

A imagem do programa contém `safe_outputs` (bit k = valor do relé k em
STOP/FAULT). Padrão do compilador: todos 0 (desenergizados). Sem programa
válido, o firmware usa todos 0. **Desenergizar não é seguro para toda carga** —
o projetista deve escolher o estado seguro de acordo com a aplicação
(ver `docs/hardware-setup.md`, "Riscos").

Estados do dispositivo (detalhados em `docs/architecture.md`): `STOP`, `RUN`,
`PROGRAM_LOADING`, `FAULT`.

## 7. Casos extremos e erros

- A VM executa apenas imagens aprovadas pela validação
  (`docs/intermediate-format.md` §4); não há erros de execução possíveis em um
  programa válido: não existem laços, saltos, divisão ou acesso indireto, e o
  tempo de execução é limitado por `n_instr ≤ 2048`.
- `dt` é um inteiro sem sinal de 32 bits; valores enormes saturam os
  acumuladores no preset (vetor `ton_preset_zero_e_dt_grande`).
- Violações de tempo de varredura (watchdog) são tratadas pelo hospedeiro, que
  leva o dispositivo a FAULT.

## 8. Ficha por instrução

| Instrução | Operando | Parâmetros | Estado interno | RLO após | Borda | Reset |
|---|---|---|---|---|---|---|
| XIC/XIO | bit legível | — | — | RLO∧b / RLO∧¬b | — | — |
| NOT | — | — | — | ¬RLO | — | — |
| BST/NXB/BND | — | — | pilha de ramos | §3 | — | — |
| OTE/OTL/OTU | Q ou M | — | o bit | inalterado | — | — |
| TON/TOF/RTO | Tn | PRE (ms), tipo | ACC, EN, TT, DN | inalterado | usa `prev = EN` | RES §5.5 |
| CTU/CTD | Cn | PRE, tipo | ACC, DN, OV, UN, prev | inalterado | subida do RLO | RES §5.5 |
| RES | Tn ou Cn | — | — | inalterado | nível (RLO=1) | — |
