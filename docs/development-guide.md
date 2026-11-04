# Guia de desenvolvimento, plano e organização da equipe

## 1. Ambiente

| Ferramenta | Versão usada | Uso |
|---|---|---|
| Python | 3.11 | Desktop, scripts |
| PySide6 | 6.12 | interface |
| pyserial | 3.5 | comunicação serial |
| pytest | 8+ | testes |
| gcc | 6.3 (MinGW) ou qualquer C99 | VM C, dispositivo virtual, autotestes |
| PlatformIO Core | 6.2 (espressif32 6.9.0) | firmware |
| PyInstaller | 6.22 | executável Windows |

```powershell
python -m pip install -e "desktop[gui,comm,dev]" platformio pyinstaller
```

## 2. Etapas, entregas e critérios de aceite

| Etapa | Entregas | Critério de aceite | Situação |
|---|---|---|---|
| 1 Análise | requisitos, referências, ADRs | `docs/analysis.md` revisado pelo grupo | ✅ (pendências abertas) |
| 2 Especificação | spec LADDER, LDRB, LIL, vetores | toda regra coberta por vetor | ✅ |
| 3 Motor | VMs Python e C, testes diferenciais | vetores + fuzzing sem divergência | ✅ |
| 4 Simulador Desktop | modelo, compilador, editor, simulador | criar a demonstração só pela interface; testes de UI | ✅ |
| 5 Firmware | HAL ESP32, varredura, estados | compila sem avisos; ensaios H0–H3, H8, H12, H13 | ✅ código / ⏳ hardware |
| 6 Comunicação | LDP, transferência transacional | testes de falha no dispositivo virtual; H10 | ✅ virtual / ⏳ hardware |
| 7 Monitor | monitor online, reconexão | testes de UI com dispositivo virtual; H11 | ✅ virtual / ⏳ hardware |
| 8 Integração | replay dos vetores no dispositivo, roteiro de hardware | H9 18/18; H1–H14 com evidências | ✅ virtual / ⏳ hardware |
| 9 Entrega | README, relatório, manual, executável | instalação reproduzida em máquina limpa; relatório com contribuições reais | ✅ documentos / ⏳ revisão do grupo |

## 3. Responsabilidades (adaptar ao número de integrantes)

| Papel | Módulos | Critério de aceite das tarefas |
|---|---|---|
| Diretor de execução | integração, revisão, prazos, `docs/report` | todo PR revisado; `main` sempre verde |
| Editor e projetos | `ui/`, `model/` | operações cobertas por `test_ui.py` |
| Compilador e simulador | `compiler/`, `sim/`, `core/` | diagnósticos com rede/elemento; equivalência mantida |
| Firmware | `firmware/src`, `plc_core` | `pio run` sem avisos; ensaios H1–H3, H8, H12 |
| Comunicação e monitor | `comm/`, `ldp_frame`, `plc_runtime` | `test_comm.py`; ensaios H9–H11 |
| Testes e documentação | vetores, roteiros, relatório | resultados registrados com evidência |

Dependências: spec → (VMs, compilador) → simulador; protocolo → (firmware,
`comm`) → monitor; hardware confirmado → ensaios.

## 4. Convenções

- Nomes no código em inglês; documentação e mensagens em português.
- Python tipado nas interfaces públicas; C99 com `-Wall -Wextra -Werror`, sem
  alocação dinâmica no firmware.
- Branches `feature/<etapa>-<assunto>`; PR com revisão; `main` verde.
- Commits no imperativo, com prefixo de área.
- Mudança de semântica/formato/protocolo: spec → JSON → vetores → as duas
  implementações, no mesmo PR (`CONTRIBUTING.md`).
- Versionamento semântico: Desktop/firmware; LDRB e LDP têm versões próprias.
- Padrões de projeto: siga os já usados (`docs/design-patterns.md`). Por exemplo, um
  processo externo novo é um adaptador de `Plant`; um meio de comunicação novo é um `Transport`.

## 5. Como estender

- **Nova instrução:** `isa.json` (opcode, classe de operando) → spec → vetor →
  `vm.py` e `ladder_vm.c` → `compiler.py`, `importer.py`, `ui/symbols.py`,
  paleta. Incremente `minor` do LDRB.
- **Nova placa:** `firmware/src/board_config.h` (e `io_board.cpp` se o
  hardware de E/S for diferente).
- **Novo processo externo** (outro simulador 3D, outro protocolo): implemente o
  protocolo `Plant` (`sim/simulator.py`), como `FactoryIOLink` (ADR 0007).
- **Wi-Fi/TCP:** implementar uma HAL de envio por socket no firmware; o
  Desktop já tem `TcpTransport`.
