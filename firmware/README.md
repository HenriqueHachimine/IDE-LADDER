# Firmware ESP32

Situação: apenas o núcleo portátil existe.

- `lib/ladder_vm/` — C99 sem dependências de Arduino:
  - `ladder_isa.h` — **gerado** por `scripts/gen_isa_header.py`; não editar.
  - `lv_image.c/.h` — validação de imagens LDRB (mesma ordem do Desktop).
  - `ladder_vm.c/.h` — interpretador sem alocação dinâmica. RAM medida em
    alvo de 32 bits (gcc): `lv_vm_t` = 1 092 B, `lv_program_t` = 344 B, mais a
    imagem (≤ 8 740 B).
  - `lv_crc.c/.h` — CRC-32 e CRC-16/MODBUS.
- `test/host/lv_host_runner.c` — executor para o PC, usado pelos testes de
  equivalência do Desktop (compilado automaticamente pelo pytest).

Compilação manual no PC:

```sh
gcc -std=c99 -Wall -Wextra -Werror -O2 -Ilib/ladder_vm lib/ladder_vm/*.c test/host/lv_host_runner.c -o lv_host_runner
```

Projeto PlatformIO (`platformio.ini`, `src/` com E/S, varredura, estados,
protocolo): Etapa 5, após confirmar o hardware (`docs/hardware-setup.md`).
