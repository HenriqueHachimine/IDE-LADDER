# ADR 0003 — Firmware em Arduino-ESP32 via PlatformIO, núcleo em C99

**Estado:** aceita (2026-10-16)

## Contexto
O firmware precisa de tarefas periódicas, UART, flash e GPIO; a equipe tem
experiência variada; o projeto de referência usa PlatformIO + Arduino.

## Alternativas
- **ESP-IDF puro:** controle total, CMake, mais verboso; curva maior.
- **Arduino IDE:** simples, mas sem estrutura de bibliotecas/testes adequada.
- **PlatformIO + framework Arduino-ESP32:** API Arduino sobre ESP-IDF
  (FreeRTOS, `esp_timer`, LittleFS disponíveis), bibliotecas locais em `lib/`,
  build reprodutível por linha de comando/CI.

## Decisão
PlatformIO + Arduino-ESP32. A VM, a validação e os CRCs ficam em
`firmware/lib/ladder_vm` em **C99 puro**, sem dependência de Arduino, para
compilarem também no PC (testes de equivalência).

## Consequências
- Código dependente de hardware isolado em `firmware/src/`.
- APIs do ESP-IDF (`esp_timer_get_time`, `xTaskDelayUntil`) usadas onde o
  Arduino não oferece determinismo.
