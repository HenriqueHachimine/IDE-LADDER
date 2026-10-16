# Formato intermediário — LDRB v1.0 e listagem LIL

O compilador do Desktop gera uma **imagem binária LDRB** (*Ladder Binary*),
transferida ao ESP32 e executada pelas duas VMs. A forma textual equivalente,
**LIL** (*Ladder Intermediate Listing*), serve para testes, depuração e
exportação. Constantes numéricas: `shared/specifications/isa.json`.

## 1. Por que bytecode de instruções fixas

- Execução direta, sem alocação dinâmica nem árvore em memória no ESP32.
- Validação estática simples e completa (sem laços/saltos ⇒ tempo limitado).
- Instruções correspondem 1:1 aos elementos gráficos ⇒ o vetor `power[]`
  mapeia diretamente para o realce do diagrama no simulador e no monitor.
- Tamanho máximo: 32 + 32·8 + 32·8 + 2048·4 + 4 = **8 740 bytes**.

## 2. Layout binário (little-endian)

### 2.1 Cabeçalho (32 bytes)

| Offset | Tipo | Campo | Regras |
|---|---|---|---|
| 0 | char[4] | `magic` | `"LDRB"` |
| 4 | u8 | `fmt_major` | = 1 (incompatível se diferente) |
| 5 | u8 | `fmt_minor` | ≤ versão menor suportada pelo leitor |
| 6 | u16 | `header_size` | = 32 |
| 8 | u32 | `total_size` | tamanho total da imagem, incluindo CRC |
| 12 | u8 | `n_inputs` | ≤ 16 |
| 13 | u8 | `n_outputs` | ≤ 16 |
| 14 | u16 | `n_markers` | ≤ 256 |
| 16 | u8 | `n_timers` | ≤ 32 |
| 17 | u8 | `n_counters` | ≤ 32 |
| 18 | u16 | `n_rungs` | ≤ 256; igual ao número de `SOR` |
| 20 | u16 | `n_instr` | ≤ 2048 |
| 22 | u16 | `safe_outputs` | estado dos relés em STOP/FAULT; bits ≥ `n_outputs` devem ser 0 |
| 24 | u32 | `build_id` | identificador livre da compilação (o Desktop usa para casar projeto × dispositivo) |
| 28 | u32 | `flags` | reservado, = 0 |

### 2.2 Tabelas (8 bytes por entrada)

Temporizadores (`n_timers` entradas), depois contadores (`n_counters` entradas):

| Offset | Tipo | Campo |
|---|---|---|
| 0 | u8 | tipo — temporizador: 0 TON, 1 TOF, 2 RTO; contador: 0 UP, 1 DOWN |
| 1 | u8[3] | reservado = 0 |
| 4 | u32 | preset (ms ou contagens), ≤ 2 147 483 647 |

### 2.3 Código (`n_instr` × 4 bytes)

| Offset | Tipo | Campo |
|---|---|---|
| 0 | u8 | opcode |
| 1 | u8 | área do operando |
| 2 | u16 | índice do operando (para `SOR`: número da rede) |

### 2.4 CRC

4 bytes finais: CRC-32/ISO-HDLC (o do zlib) de todos os bytes anteriores.

## 3. Opcodes e áreas

| Opcode | Mnemônico | Classe de operando |
|---|---|---|
| 0x01 | SOR | nenhum (índice = nº da rede) |
| 0x02 | EOR | nenhum |
| 0x10 | XIC | bit legível |
| 0x11 | XIO | bit legível |
| 0x12 | NOT | nenhum |
| 0x20 | BST | nenhum |
| 0x21 | NXB | nenhum |
| 0x22 | BND | nenhum |
| 0x30 | OTE | bit gravável |
| 0x31 | OTL | bit gravável |
| 0x32 | OTU | bit gravável |
| 0x40 | TON | temporizador |
| 0x41 | TOF | temporizador |
| 0x42 | RTO | temporizador |
| 0x48 | CTU | contador |
| 0x49 | CTD | contador |
| 0x50 | RES | temporizador ou contador |

Áreas: 0 NONE, 1 I, 2 Q, 3 M, 4 S, 5 T_EN, 6 T_TT, 7 T_DN, 8 C_DN, 9 C_OV,
10 C_UN, 11 TIMER, 12 COUNTER. Bit legível = áreas 1–10; bit gravável = 2–3.
Operando "nenhum" exige área 0 e índice 0 (exceto `SOR`).

## 4. Validação (ordem normativa)

Desktop (`image.py::decode`) e firmware (`lv_image.c::lv_image_validate`)
executam **exatamente esta sequência** e param no primeiro erro, de modo que a
mesma imagem é rejeitada com o mesmo código nos dois lados (verificado pelos
casos de `shared/test-vectors/image-errors.json` e pelo fuzzing de mutações).

1. `len < 32` → `TOO_SHORT`
2. `magic` → `BAD_MAGIC`
3. `fmt_major ≠ 1` ou `fmt_minor > suportada` → `UNSUPPORTED_VERSION`
4. `header_size ≠ 32` → `BAD_HEADER_SIZE`
5. `total_size ≠ len` → `SIZE_MISMATCH`
6. `len > 8740` → `LIMIT_EXCEEDED`
7. CRC-32 → `BAD_CRC`
8. `flags ≠ 0` → `RESERVED_NONZERO`
9. contagens acima dos limites → `LIMIT_EXCEEDED`
10. `32 + 8·(n_timers + n_counters) + 4·n_instr + 4 ≠ total_size` → `SIZE_MISMATCH`
11. `safe_outputs >> n_outputs ≠ 0` → `RESERVED_NONZERO`
12. cada temporizador: tipo > 2, reservado ≠ 0 ou preset > máx → `BAD_TIMER_TABLE`
13. cada contador: tipo > 1, reservado ≠ 0 ou preset > máx → `BAD_COUNTER_TABLE`
14. para cada instrução `i`, nesta ordem:
    1. opcode desconhecido → `BAD_OPCODE`
    2. `SOR` dentro de rede, ou outra instrução fora de rede → `BAD_STRUCTURE`
    3. classe/área/índice do operando inválidos → `BAD_OPERAND`
    4. `SOR` com índice ≠ nº da rede atual ou rede ≥ `n_rungs` → `BAD_STRUCTURE`;
       `EOR` com ramo aberto → `BRANCH_ERROR`; `BST` na profundidade 8 →
       `BRANCH_ERROR`; `NXB`/`BND` sem ramo aberto → `BRANCH_ERROR`
    5. TON/TOF/RTO/CTU/CTD diferente do tipo declarado → `TYPE_MISMATCH`;
       elemento já acionado por outra instrução → `DUPLICATE_DRIVER`
15. termina dentro de rede, ou nº de redes ≠ `n_rungs` → `BAD_STRUCTURE`
    (índice = `n_instr`)

O erro informa o índice da instrução (ou −1 quando não se refere a uma).

## 5. Compatibilidade de versões

- Mudança **menor** (`fmt_minor`+1): somente adições que um leitor antigo pode
  rejeitar com segurança (novos opcodes, novas áreas). Leitores aceitam
  `minor ≤` o seu; o Desktop consulta a versão do firmware (comando `INFO`)
  e se recusa a enviar imagens mais novas.
- Mudança **maior**: layout incompatível; exige atualização de firmware.
- O arquivo de projeto do Desktop é versionado separadamente (Etapa 4).

## 6. Listagem LIL

Uma instrução por linha; comentários com `;` ou `#`; maiúsculas/minúsculas
indiferentes. `SOR` é numerado automaticamente.

```
.inputs 8                 ; n_inputs (padrão 8)
.outputs 8                ; n_outputs (padrão 8)
.markers 16               ; n_markers (padrão 0)
.safe_outputs 0x0000      ; estado seguro dos relés
.build_id 0x00000000
.timer T0 TON 1500        ; Tn tipo preset_ms  (T0..Tn contíguos)
.counter C0 UP 3          ; Cn UP|DOWN preset   (C0..Cn contíguos)

SOR                       ; rede 0: Q0.0 = (I0.0 OR Q0.0) AND NOT I0.1
BST
XIC I0.0
NXB
XIC Q0.0
BND
XIO I0.1
OTE Q0.0
EOR
```

Implementação: `desktop/src/ladderide/core/asm.py` (`assemble`/`disassemble`).
