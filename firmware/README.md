# Firmware ESP32

```powershell
python -m pip install platformio
pio run                                  # compila
pio run -t upload --upload-port COM5     # grava
```

| Pasta | Conteúdo |
|---|---|
| `lib/ladder_vm/` | C99 portátil: `ladder_vm.c` (interpretador), `lv_image.c` (validação LDRB), `lv_crc.c`, `ladder_isa.h` (**gerado** de `isa.json`) |
| `lib/plc_core/` | C99 portátil: `plc_runtime.c` (estados, carga transacional, varredura, watchdog, comandos), `ldp_frame.c` (quadros), `modbus_rtu.c`, `ldp_protocol.h` (**gerado** de `protocol.json`) |
| `src/` | Específico do ESP32: `main.cpp` (HAL, tarefas FreeRTOS), `io_board.cpp` (74HC595/74HC165), `storage.cpp` (LittleFS atômico), `board_config.h` (pinos, polaridade, mapeamentos) |
| `test/host/` | Para o PC: `virtual_device.c` (dispositivo virtual), `lv_host_runner.c` (executor da VM), `plc_core_selftest.c` (autoteste) — compilados pelos testes do Desktop |

Memória (compilação de 2026-10-16): RAM 44 760 B (13,7%), flash 312 205 B (23,8%).
Estrutura `lv_vm_t` 1 092 B; imagens de programa até 8 740 B (staging + ativa).

Os headers gerados são atualizados com `python scripts/gen_isa_header.py`.
Para outra placa, altere `src/board_config.h`. Testes no hardware:
`docs/hardware-test-procedure.md`.
