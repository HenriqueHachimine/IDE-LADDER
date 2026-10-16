# Protocolo de comunicação Desktop ↔ ESP32 — LDP v0.1 (rascunho)

> **Estado:** contrato proposto na Etapa 1; será implementado e testado na
> Etapa 6. Mudanças até lá devem atualizar este documento primeiro.

## 1. Meios físicos

| Meio | Uso | Situação |
|---|---|---|
| USB-C → UART0 do ESP32 (115 200 bps, 8N1) | programação, transferência, monitor | **principal** |
| Wi-Fi, TCP porta 5020 | mesmos quadros LDP sobre TCP | extensão (Etapa 7+) |
| RS-485 (UART2, GPIO18/19, DE no GPIO32) | **Modbus RTU escravo, somente leitura** para supervisórios | opcional |

Modbus é usado **apenas** para monitoramento por terceiros (entradas, saídas,
acumuladores). A transferência de programas usa exclusivamente o LDP: Modbus
não tem semântica transacional para carga e ativação de programa.

### 1.1 Cuidados específicos da UART0

- O conversor USB-serial da placa normalmente liga **DTR/RTS a EN/GPIO0**
  (auto-reset). Abrir a porta com DTR/RTS ativos **reinicia o ESP32**. O Desktop
  deve abrir a porta com `dtr=False, rts=False` (pyserial: configurar antes de
  `open()`). *Pendente confirmar no hardware.*
- A ROM do ESP32 imprime mensagens de boot em 115 200 bps na UART0. O
  firmware desliga logs na UART0 após o boot; o enquadramento abaixo descarta
  qualquer lixo até o próximo cabeçalho válido.

## 2. Quadro

```
+------+------+-----+------+-----+-------+--------+-----------+-----------+
| 0xA5 | 0x5A | ver | type | seq | flags | len16  | payload   | crc16     |
+------+------+-----+------+-----+-------+--------+-----------+-----------+
   1      1     1     1      1     1       2 (LE)   0..1024     2 (LE)
```

- `ver` = 1. `crc16` = CRC-16/MODBUS sobre `ver … payload`.
- Resposta: `type | 0x80`, mesmo `seq`. `flags` bit 0 = erro; nesse caso
  `payload = [codigo_erro u8, detalhe...]`.
- Quadro com CRC inválido, `len > 1024` ou cabeçalho truncado por mais de
  100 ms é descartado **sem resposta** (o Desktop detecta por timeout).
- **Idempotência:** o dispositivo guarda a última resposta; um pedido com o
  mesmo `seq` do anterior é respondido novamente **sem reexecutar** (seguro
  para retransmissões após timeout).

Temporização do Desktop: timeout de resposta 300 ms; até 3 retransmissões;
falha → estado "desconectado" na interface.

## 3. Comandos

| type | Nome | Payload do pedido | Resposta | Estados permitidos |
|---|---|---|---|---|
| 0x01 | INFO | — | versões de firmware/protocolo/LDRB, id do hardware, nº de E/S, limites | todos |
| 0x02 | STATUS | — | estado, código de falha, `build_id` e CRC do programa ativo, nº de varreduras, tempo de varredura (último/máx), *uptime* | todos |
| 0x03 | SET_MODE | u8: 0 STOP, 1 RUN | estado resultante | RUN exige programa válido e sem FAULT |
| 0x04 | CLEAR_FAULT | — | estado | FAULT → STOP |
| 0x10 | LOAD_BEGIN | u32 tamanho, u32 crc32, u32 build_id | tamanho máximo de bloco | STOP → PROGRAM_LOADING |
| 0x11 | LOAD_CHUNK | u32 offset, dados | próximo offset esperado | PROGRAM_LOADING |
| 0x12 | LOAD_END | — | OK, ou erro + código LDRB + índice | PROGRAM_LOADING |
| 0x13 | LOAD_COMMIT | — | `build_id`, CRC ativo | após LOAD_END OK |
| 0x14 | LOAD_ABORT | — | estado | PROGRAM_LOADING → STOP |
| 0x20 | READ_IO | — | máscaras I, Q lógicas, Q comandadas ao hardware, estado | todos |
| 0x21 | READ_VARS | u16 offset, u16 qtd por seção | M, temporizadores, contadores, `power[]` paginados | todos |
| 0x22 | WRITE_MARKER | u16 índice, u8 valor | — | RUN/STOP; **somente área M** |

Não há comando para forçar entradas ou saídas físicas na v1 (separação entre
monitoramento e controle; ver `docs/architecture.md`).

## 4. Transferência transacional

```
Desktop                                   ESP32
  INFO  ─────────────────────────────────▶  confere versão LDRB/E/S
  SET_MODE STOP ─────────────────────────▶  saídas → estado seguro
  LOAD_BEGIN(size, crc, id) ─────────────▶  PROGRAM_LOADING, buffer de staging zerado
  LOAD_CHUNK(0, …) ──────────────────────▶  grava no staging, responde próximo offset
  …                                         (offset repetido = reconfirmado; fora de ordem = erro BAD_OFFSET)
  LOAD_END ──────────────────────────────▶  confere tamanho e CRC-32; lv_image_validate();
                                            confere n_inputs/n_outputs ≤ hardware
  LOAD_COMMIT ───────────────────────────▶  grava /prog.new, fsync, renomeia → /prog.bin,
                                            ativa; estado STOP
  STATUS ────────────────────────────────▶  Desktop confirma build_id e CRC
```

- O programa ativo **só é substituído no COMMIT**; qualquer falha anterior
  (timeout, CRC, validação, desconexão) mantém o programa anterior.
- Sessão de carga sem tráfego por 5 s → aborto automático, volta a STOP.
- Reinício do ESP32 durante a carga: o staging (RAM) é perdido; o programa
  anterior em flash permanece.

## 5. Códigos de erro do protocolo

| Código | Nome | Significado |
|---|---|---|
| 1 | UNKNOWN_COMMAND | `type` desconhecido |
| 2 | BAD_LENGTH | payload com tamanho errado |
| 3 | BAD_STATE | comando não permitido no estado atual |
| 4 | NO_PROGRAM | RUN sem programa válido |
| 5 | LOAD_TOO_LARGE | tamanho > `LV_MAX_IMAGE_SIZE` |
| 6 | BAD_OFFSET | bloco fora de ordem ou além do tamanho |
| 7 | IMAGE_CRC | CRC-32 recebido ≠ declarado |
| 8 | IMAGE_INVALID | validação LDRB falhou (detalhe: código + índice) |
| 9 | INCOMPATIBLE | programa usa mais E/S que o hardware |
| 10 | STORAGE | falha de gravação em flash |
| 11 | FAULT_ACTIVE | comando bloqueado por falha ativa |

## 6. Modbus RTU (opcional, somente leitura)

| Tabela | Endereços | Conteúdo |
|---|---|---|
| Discrete inputs (FC02) | 0–7 | entradas I0.0–I0.7 |
| Coils (FC01, só leitura) | 0–7 | saídas lógicas Q0.0–Q0.7 |
| Input registers (FC04) | 0 | estado (0 STOP, 1 RUN, 2 LOADING, 3 FAULT) |
| | 1–2 | nº de varreduras (u32) |
| | 100+2n | ACC do temporizador n (u32, ms) |
| | 200+2n | ACC do contador n (i32) |

Escritas Modbus (FC05/06/15/16) respondem exceção 01 (função ilegal) na v1.
