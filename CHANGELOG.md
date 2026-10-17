# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento semântico. A versão 1.0.0 fica reservada para depois dos
ensaios na placa real.

## [Não lançado]

### Adicionado
- Ambientes de simulação como plugins (`ladderide.envs`): silo de envase,
  semáforo de cruzamento e portão de garagem, com alarmes de erros de lógica,
  projetos de exemplo em `examples/ambientes/` e descoberta de ambientes do
  usuário em `~/.ladderide/ambientes/`.
- Verificação para o ESP32 (F9 e `ladderide.cli verify`): validação pela VM C
  do firmware, equivalência simulador × firmware, limites da placa e tempo de
  varredura medido no dispositivo.
- Blocos de instrução (F12 e `ladderide.cli il`): lista de instruções por rede,
  sincronizada com o diagrama e animada na simulação.
- Novos ambientes: elevador de 4 andares, linha de garrafas (enchimento, inspeção, rejeitor e
  encaixotamento), central de ar comprimido (dois compressores, pressostatos, térmicos e dreno) e
  misturador de batelada (fluxômetros, termostato, agitação e descarga), com programas de exemplo
  e testes em malha fechada.
- Código C++ (Ctrl+F7, painel ao lado dos blocos de instrução e
  `ladderide.cli cpp`): o diagrama traduzido para C++ legível a cada edição,
  sem precisar compilar, com erros marcados nas redes. O teste
  `test_codegen_cpp.py` compila o código com g++ e compara com o simulador
  varredura a varredura.
- Visual renovado: tema próprio, ícones, redes em cartões.
- Tema escuro (Exibir → Tema: claro, escuro ou seguir o Windows; Ctrl+Shift+T),
  aplicado sem reiniciar e lembrado entre sessões.

### Alterado
- Suporte a Linux: fontes com alternativas (DejaVu, Noto, Ubuntu...),
  `scripts/build_app.py` gera o executável no Windows e no Linux (com
  `.tar.gz`, ícone, atalho de menu e `install.sh`), documentação de instalação
  e de acesso à porta serial (`dialout`). O dispositivo virtual em C passou a
  compilar no Linux (`_POSIX_C_SOURCE`, `nanosleep`). A suíte de testes roda nos
  dois sistemas.
- Física realista nos ambientes (`envs/physics.py`): inércia da esteira,
  fotocélula física, válvula com atraso, vazão de Torricelli e produto em queda
  no silo; veículos com IDM, zona de dilema no amarelo e pedestres a 1,3 m/s
  no semáforo; inércia, gravidade, histerese dos fins de curso e alarme de
  reversão no portão. Exemplos ajustados a esses efeitos.
- Disposição da tela revisada com um agente de UX: a janela cabe em 1366×768
  (antes exigia 1402 px de altura); colunas laterais com altura total;
  Ambiente embaixo do diagrama (cena e Simulador visíveis juntos); três barras
  de ferramentas pelo fluxo de trabalho; paleta oculta na simulação; menu
  Dispositivo com Verificar, Transferir, RUN, STOP e Monitor online; selo de
  modo e estado do ESP32 na barra de status; layout salvo, com "Restaurar
  layout padrão".
- Travar layout (Exibir → Travar layout, Ctrl+Alt+L, cadeado na barra de
  status): painéis e barras fixos, inclusive tamanhos; estado salvo.

### Corrigido
- Travamento ao arrastar um elemento para outra rede (a edição era aplicada
  dentro do evento de soltar, durante o laço de arrastar do Windows).

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
