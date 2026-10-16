# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento semântico. A versão 1.0.0 fica reservada para depois dos
ensaios na placa real.

## [0.9.0] — 2026-10-16

### Adicionado
- Etapa 4: modelo de projeto `.ladproj` versionado, compilador com
  diagnósticos por rede/elemento, importador LIL/LDRB, simulador com tempo
  virtual (contínuo, por varredura, passo a passo), interface PySide6 com
  paleta de arrastar e soltar, fluxo de energia, símbolos, desfazer/refazer.
- Etapas 5–7: `plc_core` portátil (estados, carga transacional, varredura,
  watchdog, LDP, Modbus RTU somente leitura); firmware Arduino/PlatformIO
  (74HC595/74HC165, LittleFS atômico, FreeRTOS); dispositivo virtual;
  transportes serial/TCP/processo; cliente com retransmissão idempotente;
  painel do dispositivo e monitor online com reconexão; CLI.
- Etapa 8: execução dos vetores no dispositivo (`TEST_SCAN`), roteiro de
  ensaios de hardware, programas de teste de relés e entradas.
- Etapa 9: manual do usuário, roteiro da demonstração, relatório (com campos
  a preencher pelo grupo), executável Windows (PyInstaller) com `--smoke-test`.

### Pendente
- Ensaios H0–H14 na placa; confirmação de mapeamentos e polaridades.
- Execução da CI no GitHub (repositório remoto).

## [0.1.0] — 2026-10-16

### Adicionado
- Etapas 1–3: análise, ADRs, especificação LADDER, formato LDRB/LIL, VMs
  Python e C, vetores compartilhados e testes diferenciais.
