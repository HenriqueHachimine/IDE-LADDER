# ADR 0006 — Lógica do dispositivo em C portátil e dispositivo virtual

**Estado:** aceita (2026-10-16)

## Contexto
O desenvolvimento ocorreu sem acesso contínuo à placa. Protocolo, carga
transacional, estados e watchdog precisam de testes automatizados, inclusive
de falhas difíceis de provocar no hardware (queda de energia no meio da
gravação, CRC errado, retransmissões).

## Decisão
- Toda a lógica do dispositivo fica em `firmware/lib/plc_core` (C99, sem
  Arduino), acessando o hardware por uma interface `plc_hal_t` (entradas,
  saídas, armazenamento, envio, relógio).
- O firmware ESP32 (`firmware/src`) implementa a HAL com 74HC595/74HC165,
  LittleFS, UART e `esp_timer`.
- Um **dispositivo virtual** (`firmware/test/host/virtual_device.c`) implementa
  a HAL no PC (arquivo como flash, stdin/stdout como serial, entradas
  simuladas) e é usado pelos testes do Desktop, pela IDE e pela CLI.

## Consequências
- 19 testes de comunicação exercitam o código real do firmware, incluindo
  "queda de energia" (processo encerrado) e flash corrompida.
- A IDE pode ser usada em aula sem placa.
- O que **não** é coberto pelo dispositivo virtual: temporização real do
  FreeRTOS, drivers de E/S, LittleFS e UART do ESP32 — cobertos pelo roteiro
  `docs/hardware-test-procedure.md`.
