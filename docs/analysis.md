# Etapa 1 — Análise de requisitos, referências e riscos

Data: 2026-10-16.

## 1. Requisitos e principais dificuldades técnicas

### Funcionais (resumo)
Editor LADDER gráfico com arrastar-e-soltar; projeto persistente; compilação
com erros por rede/elemento; simulador (contínuo, passo a passo, pausa, reset,
entradas virtuais); transferência transacional com CRC; firmware interpretador
com STOP/RUN/LOADING/FAULT; monitor online; instruções XIC, XIO, OTE, OTL,
OTU, série/paralelo, NOT, TON, TOF, RTO, CTU, CTD, RES.

### Não funcionais
Equivalência simulador × firmware; determinismo; memória limitada do ESP32;
segurança operacional (estado seguro, validação de tudo que chega);
manutenibilidade por turmas futuras; distribuição simples no Windows.

### Dificuldades (em ordem de risco)

| # | Dificuldade | Como a arquitetura trata |
|---|---|---|
| 1 | **Equivalência simulador × hardware.** Dois interpretadores divergem silenciosamente (ordem de avaliação, bordas, arredondamento de tempo). | Bytecode único; VM sem relógio (recebe `dt`); comparação do estado completo a cada varredura, por vetores e *fuzzing* diferencial (ADR 0002). |
| 2 | **Editor gráfico com ramificações.** É a parte de maior esforço; editores livres (grade de células) geram diagramas inválidos. | Modelo em árvore série/paralelo — só permite estruturas válidas; Qt Graphics View. |
| 3 | **Semântica de temporizadores.** Quando o tempo começa a contar, o que acontece no reset, saturação. | Especificação formal com pseudocódigo e vetores (`docs/ladder-specification.md`). |
| 4 | **Transferência confiável pela USB** (reset por DTR/RTS, lixo do boot ROM na UART0, perdas). | Quadros com CRC e ressincronização, `seq` idempotente, staging + commit atômico. |
| 5 | **Hardware não confirmado** (polaridades, mapeamento, comportamento no boot). | Camada `io_board` isolada e configurável; checklist em `docs/hardware-setup.md`. |
| 6 | **Distinguir estado lógico × físico.** A placa não tem realimentação dos relés. | Monitor mostra "comandado" e "não observado"; nunca "relé ligado". |

## 2. Avaliação dos projetos de referência

### 2.1 `multigcs/esp32_relay_x8_modbus_303e32dc812` — hardware
- **Conteúdo:** um `main.ino` (≈ 230 linhas), `platformio.ini` (Arduino,
  `esp32dev`), fotos da placa. Licença MIT.
- **Útil:** mapeamento de GPIOs, uso de 74HC595/74HC165, permutações de bits,
  polaridades, sequência de `/OE`, CRC-16 Modbus, pinos do RS-485.
- **Limitações:** Modbus parcial e não conforme (trata FC02 como leitura de
  *coils*, quadro fixo de 10 bytes, sem *timeout* de quadro), `delay()` no
  laço, servidor web bloqueante, nenhuma lógica de CLP.
- **Decisão:** **aproveitar** o mapeamento e a sequência de inicialização
  (com atribuição, MIT); **reescrever** o restante.

### 2.2 `Pedrofrac/Trabalho-Final-CLP` — projeto acadêmico anterior (IFTM)
- **Conteúdo:** simulador Java/Swing (~10 mil linhas) com IL e LADDER visual,
  cenários (semáforo, batelada), instalador. O README declara MIT, mas **não
  há arquivo LICENSE** no repositório.
- **Útil:** referência didática de interface (paleta por categorias, cores de
  energização, painel de E/S com `I0.x`/`Q0.x`, exibição de Acc/Pre nos blocos)
  e exemplos de exercícios.
- **Limitações:** a execução está acoplada às telas (`HomePg.java` com 1 200
  linhas; interpretador com estado estático global); temporização ligada ao
  *timer* da interface (100 ms); semântica não especificada (ex.: contadores
  "na borda de descida"); sem testes automatizados; sem formato intermediário
  nem comunicação com hardware.
- **Decisão:** **não reutilizar código**. Manter a convenção de endereços
  `I0.0/Q0.0/M`, Tn, Cn (familiar para a turma) e inspirar a interface.
  Exemplos podem ser portados para LIL citando a fonte, após confirmar a
  licença com os autores.

### 2.3 `andre-m-t/ladder-web`
- **Não acessível:** o GitHub responde 404 (repositório privado, renomeado ou
  removido) em 2026-10-16. **Pendente:** obter acesso ou o endereço correto.

## 3. Decisões tomadas nesta etapa

| ADR | Decisão |
|---|---|
| [0001](decisions/0001-desktop-python-pyside6.md) | Desktop em Python 3.11 + PySide6 |
| [0002](decisions/0002-bytecode-vm-equivalencia.md) | Bytecode LDRB + duas VMs pequenas verificadas por testes diferenciais |
| [0003](decisions/0003-firmware-arduino-platformio.md) | Firmware Arduino-ESP32 via PlatformIO, núcleo em C99 portátil |
| [0004](decisions/0004-protocolo-ldp.md) | Protocolo próprio (LDP) na USB; Modbus RTU só leitura |
| [0005](decisions/0005-tempo-por-dt.md) | Tempo entra na VM como `dt` inteiro em ms |
| [0006](decisions/0006-plc-core-portavel-dispositivo-virtual.md) | Lógica do dispositivo em C portátil + dispositivo virtual (Etapa 5) |

## 4. Riscos e informações a confirmar

| # | Item | Responsável sugerido | Bloqueia |
|---|---|---|---|
| 1 | Modelo/versão da placa, chip USB-serial, polaridades, faixa de tensão das entradas | firmware | Etapa 5 |
| 2 | Número de integrantes e nomes (divisão de tarefas, LICENSE, relatório) | diretor de execução | Etapa 9 |
| 3 | Acesso ao `ladder-web` | diretor | — |
| 4 | Licença do projeto Pedrofrac (para portar exemplos) | documentação | exemplos |
| 5 | Comportamento desejado no boot: STOP (padrão proposto) ou RUN automático | professor | Etapa 5 |
| 6 | Política de estado seguro por saída exigida pelo laboratório | professor | Etapa 5 |
| 7 | Prazo final e datas das entregas parciais | diretor | planejamento |
| 8 | Repositório público no GitHub (conta/organização) — ainda não criado | diretor | publicação |
| 9 | Disponibilidade de Wi-Fi no laboratório (TCP é opcional) | comunicação | Etapa 7+ |
