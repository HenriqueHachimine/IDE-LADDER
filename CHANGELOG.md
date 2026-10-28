# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento semântico. A versão 1.0.0 fica reservada para depois dos
ensaios na placa real.

## [Não lançado]

### Corrigido
- Trocar o controlador em Programa → Propriedades só reduzia as E/S: ao passar de um de 8 E/S
  para um de 16, o projeto (e o Simulador de E/S) ficava com 8. Agora as E/S do projeto são sempre
  as do controlador: campos travados em Propriedades (menos no Personalizado) e projetos salvos com
  outras quantidades ajustados ao abrir; o Simulador de E/S mostra as quantidades no título.
- Painel Factory IO: a partir do 9º sensor/atuador o endereço aparecia como `I0.8`, `Q0.9`; agora
  `I1.0`, `Q1.1`.
- Revisão visual (auditoria de UX/UI): textos da interface, ambientes e mensagens com acentuação;
  botões padrão do Qt em português; setas das caixas numéricas e das listas desenhadas pelo tema;
  velocidade "1x (tempo real)" inteira na barra; selos de estado com cores do tema (o selo
  EXECUTANDO ofuscava no tema escuro); verde de sucesso e texto desabilitado com mais contraste;
  entradas comandadas por ambiente/Factory IO legíveis e com dica de quem comanda; grade de
  entradas que se adapta à largura do painel; nomes longos no diagrama quebram em duas linhas
  quando cabem, e a dica mostra nome e endereço.
- C++ gerado: numa rede com várias saídas, quando uma saída alterava um bit lido pela condição
  (ex.: `XIC Q0.0` → `OTU Q0.0` e `OTE Q0.1`), a condição era recalculada depois da alteração e o
  resultado divergia do CLP. Agora a condição é guardada antes, como no interpretador.
- Renomear um símbolo na tabela de símbolos deixava o diagrama com o nome antigo. Agora os
  operandos acompanham o novo nome (inclusive `Nome.DN`, `Nome.ACC`).

### Adicionado
- **Gravar C++ na placa** (Dispositivo, e botão na aba Código C++): compila o C++ do diagrama com
  o PlatformIO e grava no ESP32, Arduino UNO ou Mega pela USB. No UNO/Mega, um `io_board` gerado
  usa os pinos da aba Placa; o monitor serial usa `PLC_PRINTF`/`PLC_TEXT`, com os textos na flash
  no AVR (o UNO compila com 541 de 2048 bytes de RAM no exemplo do Simulador de E/S).
- **Factory IO: configuração do driver** espelhando a página do Modbus TCP/IP Server: Auto
  connect, Write/Read Digital, Write Register (Input ou Holding Registers, FC04/FC03), Read
  Register, Scale (valor bruto e de engenharia na tabela), Offset/Count até 256 pontos digitais e
  64 registradores, conferência ao editar, botão Padrão e **Testar** (lê uma vez sem escrever).
- **Controladores com mais de 16 entradas na simulação** (1747-L30 com 18, L40 com 24, MicroLogix
  Analog com 20): a IDE aceita até 32 entradas; a placa e o protocolo continuam em 16.
- **Novo projeto com lista de processadores** agrupada por família, como no RSLogix 500:
  placa do projeto e simulação, Arduino UNO e Mega 2560, Allen-Bradley SLC 500 modular
  (1747-L511 a L553, 5/01 a 5/05), MicroLogix 1000 e SLC 500 fixo (L20, L30, L40). Cada um
  limita E/S, variáveis e a memória de programa (instruções e redes); o compilador acusa
  "memória de programa esgotada". Os controladores Arduino/ESP32 ajustam a aba Placa.
- **Ambiente Simulador de E/S e BCD** (como o I/O Simulator e o BCD Simulator do LogixPro): uma
  botoeira por entrada e uma lâmpada por saída do controlador do projeto, botoeiras com tipo
  trocável (pulsador NA/NF, chave NA/NF), thumbwheel BCD em N0 e display BCD de N1. Ambientes
  podem se adaptar ao controlador (`configure`) e trocar registradores N com o simulador.
- **Ajuda > Guia do usuário** (Ctrl+F1, também no Sobre): guia ilustrado com as telas da IDE
  (janela, novo projeto, edição, símbolos, C++, blocos IL, simulação com ambiente, Factory IO,
  placa ESP32 e Arduino Mega, dispositivo, verificação, comunicação, tema escuro), sumário,
  busca e clique na imagem para ver em tamanho real. Conteúdo em `ladderide/help/`, incluído no
  instalador.
- **Ajuda > Como funciona a comunicação** (Shift+F1, também no Sobre): mapa clicável e ao vivo
  do caminho do programa (editor, compilador, simulador, ambiente, Factory IO, cliente LDP,
  transporte, firmware, relés, Modbus RTU), quadro LDP desenhado com exemplo real, tabelas de
  comandos e erros do `protocol.json`, sequência da transferência, mapeamento Modbus TCP do
  Factory IO e log do tráfego LDP.
- Arduino Mega no simulador da placa redesenhado: proporção da placa real, conectores na ordem
  da serigrafia com corpo plástico, ATmega2560 a 45°, 16U2, ICSP, regulador, e pinos dos relés
  (D22…) e das entradas (D38–D53) destacados; os fios saem pela borda sem cruzar o conector.
- Painel **Processo**: Ambiente animado, Factory IO e Placa ESP32/Arduino num só painel, com
  seletor e selo do que está ativo (antes eram três abas, embora só um seja usado por vez).
- Simulador da placa: escolha entre ESP32 Relay (1 a 8 relés), Arduino UNO (1 a 8) e Arduino
  Mega 2560 (1 a 16), cada uma desenhada (placa, pinos, módulo de relés, fios e botões de
  entrada). O dispositivo virtual aceita `--inputs`, `--outputs` e `--hardware`; o painel avisa
  quando o projeto tem mais E/S que a placa e oferece ajustar o projeto. Arduino só na simulação.
- Factory IO: a coluna Simbolo do painel é editável (duplo clique). Cria, renomeia ou remove o
  símbolo do endereço, atualizando o diagrama; a porta do driver vai no comentário.
- Relatório reestruturado segundo a ABNT (NBR 14724, 6024, 6028, 6023): capa, folha de rosto,
  resumo/abstract, listas, sumário, seções numeradas, quadros com fonte e referências;
  conteúdo atualizado (blocos numéricos, ambientes, Factory IO, padrões de projeto, 338 testes).
  `docs/report/build_docx.js` gera `relatorio.docx` formatado a partir de `relatorio.md`.
- Documentação dos padrões de projeto usados (`docs/design-patterns.md`: Adapter, Strategy,
  Template Method, Composite, Interpreter, Observer, Memento, Command, Facade, Factory Method,
  Registry/Plugin, máquina de estados, camadas e HAL) e ADR 0007 (Factory IO por Modbus TCP).
- Factory IO: a tabela do painel lista todas as portas do driver (Inputs, Input Regs, Coils,
  Holding Regs) com o endereço no CLP, o símbolo e o valor ao vivo; os registradores analógicos
  vão e vêm dos registradores N (FC04/FC16). No diagrama LADDER, duplo clique no endereço de um
  elemento (ou "Alterar endereço..." no botão direito) abre a escolha rápida do endereço, com a
  porta do Factory IO de cada um.
- Ligação com o Factory IO (Simulação → Factory IO): o simulador vira cliente Modbus TCP do driver
  *Modbus TCP/IP Server* e troca sensores (Inputs ou Coils → I) e atuadores (Q → Coils) a cada
  20 ms. Velocidade travada em 1× enquanto conectado, reconexão automática, sensores em 0 sem
  conexão e atuadores desligados ao desconectar. Comando `ladderide.cli factoryio` para
  diagnóstico. Cliente Modbus TCP próprio, sem dependências (`docs/factory-io.md`). Exemplo
  `examples/factoryio/esteira_lote.ladproj` (esteira com lote de 5 caixas e alarme de
  atolamento). Ainda não testado com o Factory IO real.
- Velocidade da simulação ajustável: valor digitado de 0,01× a 1000× ou "max", predefinições até
  100×, barra deslizante no painel Simulador, seletor na barra de ferramentas e atalhos
  Ctrl+. / Ctrl+, / Ctrl+;. O painel mostra a velocidade real e avisa quando o PC não acompanha
  (o resultado não muda, só fica mais lento). A velocidade fica salva entre sessões.
- Instalador do Windows (`scripts/build_installer.py` → `LadderIDE-Setup-<versão>.exe`): instala
  por usuário sem administrador, atalhos, associação de `.ladproj`, desinstalador; inclui os
  exemplos Arduino pré-compilados e o firmware com o esptool.
- Dispositivo → Gravar firmware na placa: grava o firmware do CLP pela USB com o esptool, com os
  mesmos parâmetros do `pio run -t upload`. Ainda não testado com a placa real.
- Escolha do controlador ao criar o projeto (ESP32 Relay X8, Somente simulação com 16 E/S,
  Personalizado), que limita entradas, saídas, memórias, temporizadores, contadores e
  registradores; o compilador confere os limites. Controladores do usuário em
  `~/.ladderide/controladores.json` (`docs/controllers.md`).
- Blocos de comparação (EQU, NEQ, LES, GRT, LEQ, GEQ, LIM, MEQ) e de matemática (ADD, SUB, MUL,
  DIV, SQR, NEG, TOD, FRD), com registradores `N0`–`N63` (inteiros de 32 bits), constantes,
  `Tn.ACC/PRE`, `Cn.ACC/PRE`, `IW0`/`QW0` e os bits S0.4 (estouro), S0.5 (zero), S0.6 (negativo).
  Paleta, diálogo, desenho com valores ao vivo, monitor de variáveis, blocos de instrução,
  C++ gerado e as duas VMs (Python e firmware), conferidas por vetores e fuzzing diferencial.
  Exemplo em `examples/math/blocos_numericos.ladproj`.
- **Formato LDRB 2.0** (cabeçalho de 36 bytes, tabela de constantes, instrução `ARG`) e projeto
  `.ladproj` versão 2. O firmware precisa ser regravado, e o programa transferido de novo, porque
  imagens 1.x são rejeitadas.
- Ambientes de simulação como plugins (`ladderide.envs`): silo de envase,
  semáforo de cruzamento e portão de garagem, com alarmes de erros de lógica,
  projetos de exemplo em `examples/ambientes/` e descoberta de ambientes do
  usuário em `~/.ladderide/ambientes/`.
- Verificação para o ESP32 (F9 e `ladderide.cli verify`): validação pela VM C
  do firmware, equivalência simulador × firmware, limites da placa e tempo de
  varredura medido no dispositivo.
- Blocos de instrução (F12 e `ladderide.cli il`): lista de instruções por rede,
  sincronizada com o diagrama e animada na simulação.
- Exemplos do ESP32 narram no monitor serial o que acontece: o `teste_placa` confirma cada
  comando e mostra cada entrada e relé que muda; o sketch gerado do LADDER (`ladder_portao`
  e qualquer projeto exportado em C++) lista entradas/saídas com os comentários dos símbolos e
  mostra cada mudança de entrada, temporizador, contador e saída (`s` = estado, `h` = ajuda).
  O modo sketch recompila mesmo com o exemplo ainda aberto em outra janela da IDE.
- Placa ESP32 roda os exemplos Arduino no PC (modo sketch): `firmware/test/host/arduino_sim`
  imita pinos, tempo e Serial, com 74HC595/74HC165 simulados no nível dos sinais; o sketch
  usa o `io_board.cpp` do firmware, o monitor serial mostra a saída e envia comandos.
- Exemplos para o ESP32 em `firmware/examples/` (ambientes PlatformIO
  `exemplo_teste_placa` e `exemplo_ladder_portao`): teste da placa pelo monitor serial e o
  programa do portão convertido em C++ rodando direto na placa. Compilam com `pio run`;
  não testados na placa. O C++ gerado passou a incluir `Arduino.h` e a evitar nomes de
  macros do Arduino.
- Simulador da placa ESP32 (painel Placa ESP32, Ctrl+Shift+E): liga o dispositivo virtual
  (firmware C no PC), desenha relés, entradas, GPIOs e os níveis elétricos nos registradores
  conforme `board_config.h`, lista toda a configuração com os itens a verificar e mostra o
  tráfego LDP (monitor serial) e o estado do firmware; reinício da placa virtual.
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
