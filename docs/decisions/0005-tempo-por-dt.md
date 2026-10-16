# ADR 0005 — Tempo entra na VM como `dt` inteiro em milissegundos

**Estado:** aceita (2026-10-16)

## Contexto
Temporizadores precisam de base monotônica e de resultados idênticos no PC e
no ESP32.

## Decisão
- A VM não lê relógio. Cada varredura recebe `dt` (u32, ms) desde a anterior;
  a primeira varredura usa `dt = 0`.
- Firmware: `dt` derivado de `esp_timer_get_time()` (µs, monotônico),
  acumulando o resto em µs para não perder frações.
- Simulador: tempo virtual (período configurável) ou real (medido com
  `time.monotonic_ns`).
- Acumuladores em ms inteiros com soma saturada no preset.

## Consequências
- Para a mesma sequência (entradas, `dt`), PC e ESP32 produzem estados
  idênticos bit a bit. Diferenças entre hardware e simulação passam a vir
  apenas da sequência de `dt` reais (jitter de varredura), quantificável:
  tolerância de comparação = 1 período de varredura + jitter medido
  (ver `docs/testing.md`).
- Resolução de 1 ms; temporizadores mais finos que o período de varredura não
  fazem sentido e o compilador emitirá aviso para preset < período.
