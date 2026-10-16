# CLP LADDER com ESP32

IDE LADDER para Windows (editor, compilador, simulador, transferência e monitor)
e firmware interpretador para uma placa ESP32 com 8 relés, desenvolvidos como
trabalho final da disciplina de Controladores Lógicos Programáveis.

> **Situação (v0.1.0, 2026-10-16):** Etapas 1–3 concluídas — especificação,
> formato intermediário e motor de execução (Python e C) com testes de
> equivalência. Interface gráfica, firmware de hardware, comunicação e monitor
> **ainda não existem**; veja o [plano](docs/development-guide.md).

## Funcionalidades

| Funcionalidade | Situação |
|---|---|
| Especificação formal das instruções e do ciclo de varredura | ✅ [spec](docs/ladder-specification.md) |
| Formato binário LDRB + listagem textual LIL | ✅ [formato](docs/intermediate-format.md) |
| VM de referência (simulador) com execução por varredura e passo a passo | ✅ núcleo, sem interface |
| VM C para o ESP32 (C99 portátil) | ✅ testada no PC; não testada no ESP32 |
| Equivalência Python × C (vetores + fuzzing) | ✅ |
| Editor gráfico, projeto, compilador com diagnósticos | Etapa 4 |
| Firmware com E/S, STOP/RUN/FAULT | Etapa 5 |
| Transferência transacional (protocolo LDP) | Etapa 6 — [rascunho](docs/communication-protocol.md) |
| Monitor online | Etapa 7 |

Instruções: XIC/XIO (contato NA/NF), NOT, ramos paralelos, OTE, OTL (SET),
OTU (RESET), TON, TOF, RTO, CTU, CTD, RES.

## Arquitetura

O Desktop compila o diagrama para um bytecode compacto (LDRB). O mesmo bytecode
é executado pela VM Python do simulador e pela VM C do ESP32, que seguem a
mesma especificação e são comparadas varredura a varredura nos testes.
Detalhes em [docs/architecture.md](docs/architecture.md).

```
desktop/          IDE (Python): src/ladderide/core = ISA, LDRB, montador, VM
firmware/         ESP32 (PlatformIO): lib/ladder_vm = VM C, validação, CRC
shared/           isa.json (fonte única) e vetores de teste
docs/             especificações, arquitetura, ADRs, testes, hardware
scripts/          geração do header C a partir do isa.json
```

## Requisitos

- Windows 10/11, Python ≥ 3.11, `pip install pytest`
- `gcc` no PATH para os testes de equivalência (MinGW no Windows)
- Hardware (a partir da Etapa 5): placa ESP32 8 relés —
  ver [docs/hardware-setup.md](docs/hardware-setup.md)

## Executar os testes

```powershell
cd desktop
python -m pip install pytest
python -m pytest -q
```

## Experimentar o núcleo

```python
from ladderide.core import assemble, build_image, decode, LadderVM

src = """
.timer T0 TON 1000
SOR
XIC I0.0
TON T0
EOR
SOR
XIC T0.DN
OTE Q0.0
EOR
"""
image = build_image(assemble(src))      # bytes LDRB validados (CRC incluso)
vm = LadderVM(decode(image))
for _ in range(102):
    vm.scan(inputs=0b1, dt_ms=10)       # I0.0 ligado, varredura de 10 ms
print(vm.timers[0], bin(vm.outputs))
```
(execute dentro de `desktop/` após `$env:PYTHONPATH="src"` no PowerShell)

## Contribuir

Veja [CONTRIBUTING.md](CONTRIBUTING.md) e
[docs/development-guide.md](docs/development-guide.md).

## Limitações conhecidas

- Sem interface gráfica, comunicação ou firmware de hardware nesta versão.
- Sem memória retentiva entre partidas (STOP→RUN é partida a frio).
- Não é um CLP de segurança; não use para funções de proteção de pessoas.
- Mapeamento de hardware ainda não confirmado na placa do grupo.

## Créditos e referências

- Mapeamento da placa baseado em
  [multigcs/esp32_relay_x8_modbus_303e32dc812](https://github.com/multigcs/esp32_relay_x8_modbus_303e32dc812)
  (MIT, © 2026 Oliver Dippel).
- Projeto acadêmico anterior (IFTM) usado como referência de interface:
  [Pedrofrac/Trabalho-Final-CLP](https://github.com/Pedrofrac/Trabalho-Final-CLP).
- Nomenclatura XIC/XIO/OTE/OTL/OTU/TON/TOF/RTO/CTU/CTD/RES inspirada na
  família Allen-Bradley; semântica própria definida na especificação.

Licença: [MIT](LICENSE).
