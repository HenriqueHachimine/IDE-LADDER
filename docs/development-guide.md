# Guia de desenvolvimento, plano incremental e organização da equipe

## 1. Ambiente

| Ferramenta | Versão mínima | Uso |
|---|---|---|
| Python | 3.11 | Desktop e scripts |
| pytest | 8 | testes |
| gcc (MinGW no Windows, ou Linux) | qualquer C99 | compilar a VM C para testes |
| PySide6 | 6.6 | interface (a partir da Etapa 4) |
| pyserial | 3.5 | comunicação (Etapa 6) |
| PlatformIO Core | 6 | firmware (Etapa 5) |

## 2. Plano incremental e critérios de aceite

Regra geral: nenhuma etapa termina sem código funcional, testes, documentação
atualizada e commit.

| Etapa | Entregas | Critérios de aceite | Situação |
|---|---|---|---|
| 1 Análise | requisitos, referências, ADRs, riscos | `docs/analysis.md` revisado pelo grupo; pendências com responsável | ✅ entregue (pendências abertas) |
| 2 Especificação | spec LADDER, formato LDRB, LIL, protocolo (rascunho), vetores | toda regra da spec coberta por ≥ 1 vetor | ✅ |
| 3 Motor de execução | `core` (Python) + `ladder_vm` (C) + testes diferenciais | vetores e fuzzing sem divergência; build C com `-Wall -Wextra -Werror` | ✅ |
| 4 Simulador Desktop | modelo de projeto (JSON versionado), compilador com diagnósticos por rede/elemento, editor gráfico, painel de simulação | criar o programa de demonstração só pela interface; salvar/abrir; compilar; simular contínuo e passo a passo com realce de energia; testes de modelo/compilador | próxima |
| 5 Firmware | `io_board`, `scan_task`, `plc_state`, `program_mgr` (programa embutido para teste) | 8 relés acionados individualmente; 8 entradas lidas; varredura de 10 ms medida; STOP leva às saídas seguras | requer hardware confirmado |
| 6 Comunicação | LDP no firmware e no Desktop; transferência transacional | testes de falha da seção 9.3 do enunciado (transporte simulado) + carga real com CRC conferido | |
| 7 Monitor online | leitura periódica, realce no diagrama, lógico × comandado, reconexão | atualização ≥ 5 Hz; indicação de desconexão < 1 s | |
| 8 Integração | replay de vetores no ESP32, roteiro de hardware, demonstração | todos os vetores idênticos no ESP32; roteiro com evidências | |
| 9 Entrega | README, relatório, contribuições, release | instalação reproduzida em máquina limpa | |

## 3. Divisão de responsabilidades (adaptar ao tamanho do grupo)

| Papel | Módulos | Depende de |
|---|---|---|
| Diretor de execução / arquitetura | integração, revisão de PRs, ADRs, prazos | — |
| Editor gráfico e projetos | `ui`, `model` (persistência) | `model`, `compiler` |
| Compilador, modelo e simulador | `model`, `compiler`, `sim`, `core` | spec |
| Firmware | `io_board`, `scan_task`, `plc_state`, `program_mgr` | `ladder_vm`, hardware |
| Comunicação e monitor | `comm` (Desktop), `proto`/`monitor` (firmware) | LDP, `program_mgr` |
| Testes, documentação e relatório | vetores, roteiro de hardware, `docs/report` | todos |

Com 3 pessoas: (diretor + compilador/simulador), (editor + monitor no Desktop),
(firmware + comunicação no firmware); testes e documentação são de todos.

## 4. Convenções

- **Código** em inglês (nomes); **documentação e mensagens ao usuário** em
  português.
- Python: tipagem nas assinaturas públicas, `ruff` como linter (a configurar
  na Etapa 4). C: C99, `-Wall -Wextra -Werror`, sem alocação dinâmica no
  caminho da varredura.
- Branches: `main` sempre verde; trabalho em `feature/<etapa>-<assunto>`;
  integração por *pull request* com revisão de outro integrante.
- Commits: imperativo, em português, prefixados pela área
  (`core:`, `firmware:`, `docs:`, `ui:`…).
- Mudança de semântica ou formato: spec → vetores → as duas VMs, no mesmo PR
  (ver `CONTRIBUTING.md`).
- Versionamento semântico do Desktop e do firmware; formato LDRB com versão
  própria (`docs/intermediate-format.md` §5).
