# Desktop — `ladderide`

Pacotes em `src/ladderide/`:

- `core/isa.py` — carrega `shared/specifications/isa.json` (opcodes, áreas, limites, erros).
- `core/image.py` — `Program`, `encode`, `decode` (validação normativa), `build_image`.
- `core/asm.py` — listagem textual LIL: `assemble`, `disassemble`.
- `core/vm.py` — `LadderVM`: `scan()`, ou `begin_scan()` / `step()` / `end_scan()` para passo a passo; `dump_line()`.
- `core/crc.py` — CRC-32 e CRC-16/MODBUS.

Testes: `python -m pytest -q` (ver `docs/testing.md`).

Interface gráfica (PySide6), modelo de projeto, compilador e simulador: Etapa 4.
