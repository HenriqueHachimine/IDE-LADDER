# Desktop — `ladderide`

```powershell
python -m pip install -e ".[gui,comm,dev]"
python -m ladderide            # IDE
python -m ladderide.cli --help # linha de comando
python -m pytest -q            # testes
```

| Pacote | Conteúdo |
|---|---|
| `core/` | `isa.py` (lê `shared/specifications/isa.json`), `image.py` (LDRB), `asm.py` (LIL), `vm.py` (VM de referência), `crc.py` |
| `model/` | `project.py` (projeto `.ladproj`), `edit.py` (operações de edição) |
| `compiler/` | `compiler.py` (modelo → LDRB + diagnósticos + mapa de depuração), `importer.py` (LIL/LDRB → modelo) |
| `sim/` | `simulator.py` (tempo virtual, contínuo/varredura/passo) |
| `comm/` | `frames.py`, `transport.py` (serial/TCP/processo), `client.py` (pedidos, transferência), `snapshot.py`, `monitor.py`, `equivalence.py`, `virtual.py` (dispositivo virtual) |
| `ui/` | `main_window.py`, `ladder_view.py`, `layout.py`, `symbols.py`, `palette.py`, `sim_panel.py`, `device_panel.py`, `io_panel.py`, `dialogs.py` |
| `cli.py` | linha de comando |

Regra de arquitetura: só `ui/` importa PySide6, e nenhuma regra de execução
LADDER fica em `ui/`.
