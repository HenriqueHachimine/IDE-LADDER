# Protocolo de comunicação Desktop ↔ ESP32 — LDP v1

Implementação: firmware `firmware/lib/plc_core/` (`ldp_frame.c`, `plc_runtime.c`),
Desktop `desktop/src/ladderide/comm/`. Constantes: `shared/specifications/protocol.json`
(gera `ldp_protocol.h`). Verificado pelos testes `desktop/tests/test_comm.py`
contra o dispositivo virtual (o mesmo código C do firmware rodando no PC).

## 1. Meios físicos

| Meio | Uso | Situação |
|---|---|---|
| USB-C → UART0 (115 200 bps, 8N1) | transferência, controle, monitor | implementado |
| Processo local (stdin/stdout) | dispositivo virtual para testes e aulas sem placa | implementado |
| TCP (mesmos quadros) | transporte pronto no Desktop (`TcpTransport`) | **firmware ainda não implementa Wi-Fi** |
| RS-485 (UART2) | Modbus RTU **somente leitura** para supervisórios | implementado (não testado em hardware) |

Modbus **não** é usado para transferir programas (não tem semântica de carga,
validação e ativação). Ver §7.

### 1.1 Cuidados com a UART0

- Abrir a porta com DTR/RTS ativos reinicia o ESP32 (circuito de auto-reset).
  `SerialTransport` configura `dtr=False, rts=False` **antes** de abrir.
- A ROM imprime mensagens no boot; o firmware desliga os logs
  (`CORE_DEBUG_LEVEL=0`, `esp_log_level_set(NONE)`) e o analisador descarta
  bytes até o próximo cabeçalho válido.

## 2. Quadro

```
A5 5A | ver | type | seq | flags | len (u16 LE) | payload (0..1024) | crc16 (LE)
```

- `ver` = 1. CRC-16/MODBUS sobre `ver … payload`.
- Resposta: `type | 0x80`, mesmo `seq`. `flags` bit 0 = erro, com
  `payload = [código u8, detalhe...]`.
- Quadros com CRC errado, versão diferente, `len > 1024` ou pausa > 100 ms no
  meio são descartados **sem resposta**; o Desktop detecta por timeout.
- **Idempotência:** o dispositivo guarda a última resposta. Pedido com o mesmo
  `seq` e `type` do anterior é respondido de novo **sem reexecutar**. O Desktop
  inicia `seq` em valor aleatório e reenvia com o mesmo `seq` após timeout
  (timeout 300–600 ms, 3 retransmissões).

## 3. Comandos (todos os inteiros little-endian)

| type | Nome | Pedido | Resposta |
|---|---|---|---|
| 0x01 | INFO | — | `u8 protocolo, u8 ldrb_major, u8 ldrb_minor, u8 n_in, u8 n_out, u16 max_imagem, u16 max_bloco, u16 periodo_ms, str firmware, str hardware` (str = u8 tamanho + ASCII) |
| 0x02 | STATUS | — | `u8 estado, u8 falha, u8 tem_programa, u8 modo_teste, u32 build_id, u32 crc, u32 varreduras, u32 exec_us, u32 exec_max_us, u32 atrasos, u32 uptime_ms, u16 periodo_ms, u32 intervalo_max_us` |
| 0x03 | SET_MODE | `u8 0=STOP 1=RUN` | `u8 estado` |
| 0x04 | CLEAR_FAULT | — | `u8 estado` |
| 0x10 | LOAD_BEGIN | `u32 tamanho, u32 crc32` | `u16 max_bloco` |
| 0x11 | LOAD_CHUNK | `u32 offset, dados (≤ 512)` | `u32 bytes_recebidos` |
| 0x12 | LOAD_END | — | vazio (validado) |
| 0x13 | LOAD_COMMIT | — | `u32 build_id, u32 crc` |
| 0x14 | LOAD_ABORT | — | `u8 estado` |
| 0x20 | READ_IO | — | `u8 estado, u16 entradas, u16 Q_lógico, u16 Q_comandado` |
| 0x21 | READ_VARS | — | instantâneo (§4) |
| 0x22 | WRITE_MARKER | `u16 índice, u8 valor` | vazio — **somente área M** |
| 0x30 | TEST_BEGIN | — | vazio — partida a frio da VM em modo teste (exige STOP) |
| 0x31 | TEST_SCAN | `u16 entradas, u32 dt_ms` | instantâneo (§4) após uma varredura |
| 0x7E | SIM_SET_INPUTS | `u16 entradas` | vazio — **só no dispositivo virtual** |

Estados permitidos: RUN exige programa válido e não estar em FAULT; carga
exige STOP; TEST_* exigem STOP (as saídas físicas permanecem no estado seguro).
Não existe comando para forçar entradas ou saídas físicas.

## 4. Instantâneo (READ_VARS / TEST_SCAN), ≤ 630 bytes

```
u8 estado, u8 falha, u32 varreduras, u16 entradas, u16 Q_lógico, u16 Q_comandado,
u32 build_id, u32 crc, u8 modo_teste, u8 reservado,
u16 n_M,  ceil(n_M/8) bytes de bits M
u8 n_T,   n_T × (u32 ACC, u8 EN|TT<<1|DN<<2)
u8 n_C,   n_C × (i32 ACC, u8 DN|OV<<1|UN<<2|borda<<3)
u16 n_instr, ceil(n_instr/8) bytes de energia por instrução (RLO)
```

O Desktop converte o instantâneo para o mesmo texto de `LadderVM.dump_line()`
(`Snapshot.dump_line`) para as comparações de equivalência.

## 5. Transferência transacional

```
INFO        → confere versão LDRB e nº de E/S (o cliente recusa antes de enviar)
STATUS      → se RUN: SET_MODE STOP (com confirmação do usuário)
LOAD_BEGIN  → PROGRAM_LOADING; staging em RAM
LOAD_CHUNK* → blocos sequenciais; reenvio do último bloco é aceito; fora de ordem → BAD_OFFSET
LOAD_END    → tamanho completo? CRC-32 confere? lv_image_validate()? E/S compatíveis?
LOAD_COMMIT → grava /prog.new, renomeia sobre /prog.bin (atômico), ativa; estado STOP
STATUS      → o Desktop confirma build_id e CRC
```

- O programa ativo só muda no COMMIT; qualquer falha anterior o preserva
  (testes: CRC errado, imagem inválida, queda de energia no meio da carga).
- Sessão de carga sem tráfego por 5 s volta a STOP automaticamente.
- Em falha, o cliente envia LOAD_ABORT (melhor esforço).

## 6. Códigos de erro

| Código | Nome | Significado |
|---|---|---|
| 1 | UNKNOWN_COMMAND | comando desconhecido |
| 2 | BAD_LENGTH | payload com tamanho inválido |
| 3 | BAD_STATE | comando não permitido no estado atual |
| 4 | NO_PROGRAM | não há programa válido |
| 5 | LOAD_TOO_LARGE | programa maior que 8 740 bytes |
| 6 | BAD_OFFSET | bloco fora de ordem / transferência incompleta |
| 7 | IMAGE_CRC | CRC-32 do programa recebido não confere |
| 8 | IMAGE_INVALID | validação LDRB falhou (detalhe: `u8 código LDRB, i32 índice`) |
| 9 | INCOMPATIBLE | programa usa mais E/S que o hardware |
| 10 | STORAGE | falha ao gravar na flash |
| 11 | FAULT_ACTIVE | dispositivo em FAULT |
| 12 | BAD_ARGUMENT | argumento fora da faixa |

Falhas do dispositivo (`STATUS.falha`): 1 SCAN_TIMEOUT (varredura > 50 ms),
2 PROGRAM_CORRUPT (programa na flash inválido no boot), 3 INTERNAL.

## 7. Modbus RTU (RS-485, somente leitura)

Endereço 11, 9 600 bps 8N1 (`firmware/src/board_config.h`).

| Função | Endereços | Conteúdo |
|---|---|---|
| FC01 coils | 0–7 | saídas lógicas Q0.0–Q0.7 |
| FC02 discrete inputs | 0–7 | entradas I0.0–I0.7 |
| FC04 input registers | 0 | estado (0 STOP, 1 RUN, 2 LOADING, 3 FAULT) |
| | 1–2 | nº de varreduras (u32, palavra alta primeiro) |
| | 100+2n, 101+2n | ACC do temporizador n (u32, ms) |
| | 200+2n, 201+2n | ACC do contador n (i32) |

Demais funções: exceção 01. Endereço fora da faixa: exceção 02.
