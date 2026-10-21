# Plataforma de programação LADDER para CLP baseado em ESP32

<!--
Fonte do relatório. O arquivo Word formatado pela ABNT (NBR 14724) é gerado com:
    cd docs/report && npm install docx@9 && node build_docx.js
Convenções deste arquivo (lidas pelo gerador):
  ## TÍTULO            seção primária (nova página); sem número = elemento pré/pós-textual
  ### 1.1 Título       seção secundária;  #### 1.1.1 Título  seção terciária
  Quadro N – título    legenda acima de uma tabela;  "Fonte: ..." logo abaixo dela
  [PREENCHER ...]      informação que só o grupo pode dar (fica destacada em amarelo)
-->

**Instituição:** [PREENCHER: nome da instituição]
**Curso:** [PREENCHER: curso]
**Disciplina:** Controladores Lógicos Programáveis
**Professor:** [PREENCHER: nome do professor]
**Autores:** [PREENCHER: nomes dos integrantes]
**Local:** [PREENCHER: cidade]
**Ano:** 2026

## RESUMO

Este trabalho apresenta uma plataforma completa para a programação de um Controlador Lógico Programável (CLP) didático baseado no microcontrolador ESP32, com oito saídas a relé. A plataforma é composta por um ambiente de desenvolvimento integrado (IDE) para computador, com editor gráfico da linguagem LADDER, compilador, simulador e monitor online, e por um firmware interpretador para a placa. O diagrama é compilado para um código intermediário compacto (formato LDRB), executado por duas máquinas virtuais, uma em Python, no simulador, e outra em C, no firmware, que seguem uma única especificação formal e são comparadas varredura a varredura por testes diferenciais. A transferência do programa é transacional, com verificação de integridade e validação no dispositivo antes da ativação, de modo que uma falha nunca deixa a placa sem programa válido. A lógica do dispositivo foi escrita em C portátil sobre uma camada de abstração de hardware, o que permitiu testá-la no computador por meio de um dispositivo virtual. O simulador controla processos animados internos e cenas 3D do software Factory IO, por meio do protocolo Modbus TCP. O código foi organizado segundo padrões de projeto consagrados, como Adapter, Strategy, Template Method e Composite. A suíte automatizada reúne 338 testes aprovados. [PREENCHER: uma frase com o resultado dos ensaios na placa real.]

**Palavras-chave:** controlador lógico programável; LADDER; ESP32; máquina virtual; Modbus; Factory IO.

## ABSTRACT

This work presents a complete platform for programming an educational Programmable Logic Controller (PLC) based on the ESP32 microcontroller with eight relay outputs. The platform consists of a desktop integrated development environment (IDE), with a graphical LADDER editor, compiler, simulator and online monitor, and of an interpreter firmware for the board. The diagram is compiled into a compact intermediate code (LDRB format) executed by two virtual machines, one in Python, in the simulator, and one in C, in the firmware, which follow a single formal specification and are compared scan by scan through differential tests. Program download is transactional, with integrity checks and on-device validation before activation, so a failure never leaves the board without a valid program. The device logic was written in portable C over a hardware abstraction layer, which allowed it to be tested on the computer through a virtual device. The simulator drives internal animated processes and Factory IO 3D scenes through the Modbus TCP protocol. The code follows well-known design patterns such as Adapter, Strategy, Template Method and Composite. The automated suite comprises 338 passing tests. [PREENCHER: one sentence with the results of the tests on the real board.]

**Keywords:** programmable logic controller; LADDER; ESP32; virtual machine; Modbus; Factory IO.

## LISTA DE QUADROS

## LISTA DE ABREVIATURAS E SIGLAS

| Sigla | Significado |
|---|---|
| ADR | *Architecture Decision Record* (registro de decisão de arquitetura) |
| CLP | Controlador Lógico Programável |
| CRC | *Cyclic Redundancy Check* (verificação cíclica de redundância) |
| E/S | Entradas e saídas |
| HAL | *Hardware Abstraction Layer* (camada de abstração de hardware) |
| IDE | *Integrated Development Environment* (ambiente de desenvolvimento integrado) |
| IEC | *International Electrotechnical Commission* |
| LDP | Protocolo de comunicação do projeto (*LADDER Device Protocol*) |
| LDRB | Formato binário do programa compilado (*LADDER Bytecode*) |
| LIL | Forma textual do programa compilado (lista de instruções) |
| OPC | *Open Platform Communications* |
| RLO | Resultado lógico da operação |
| TCP | *Transmission Control Protocol* |
| VM | Máquina virtual |

## SUMÁRIO

## 1 INTRODUÇÃO

O CLP é o equipamento central da automação industrial, e o seu ensino depende de prática: escrever programas, testá-los e observar o efeito em um processo. Equipamentos comerciais são caros e os softwares de programação são proprietários, o que limita as atividades em sala de aula. Este trabalho propõe uma alternativa de baixo custo baseada em uma placa ESP32 com oito relés, acompanhada de um software próprio de programação e simulação.

### 1.1 Objetivo geral

Desenvolver uma plataforma que permita a estudantes criar programas em LADDER, validar a lógica em simulação e executá-los em hardware real, observando o comportamento no monitor online.

### 1.2 Objetivos específicos

- Implementar um editor gráfico LADDER com arrastar e soltar, ramos paralelos, símbolos e desfazer/refazer.
- Oferecer as instruções NA, NF, bobina, SET, RESET, TON, TOF, RTO, CTU, CTD e RES, além de blocos de comparação e matemática.
- Garantir que a simulação seja idêntica à execução no hardware.
- Transferir programas de forma segura, sem deixar a placa em estado inválido.
- Permitir testar a lógica em processos simulados, inclusive no Factory IO.
- Documentar o sistema para que outras turmas possam continuá-lo.

### 1.3 Organização do trabalho

A seção 2 apresenta a fundamentação teórica. As seções 3 e 4 descrevem a arquitetura e os padrões de projeto. As seções 5 a 9 detalham o modelo intermediário, o interpretador, a comunicação, a simulação e a integração com o ESP32. As seções 10 a 12 tratam da metodologia, dos testes e da divisão das tarefas, e a seção 13 apresenta as conclusões.

## 2 FUNDAMENTAÇÃO TEÓRICA

### 2.1 Controlador lógico programável

O CLP é um controlador digital que executa um ciclo contínuo: lê as entradas para uma imagem de processo, avalia o programa e atualiza as saídas (PETRUZELLA, [PREENCHER: ano da edição consultada]). O determinismo desse ciclo é o que diferencia um CLP de um microcontrolador programado sem essa disciplina.

### 2.2 Linguagem LADDER

LADDER é uma das linguagens padronizadas pela norma IEC 61131-3 (IEC, 2013). É uma linguagem gráfica derivada dos diagramas de relés: contatos em série realizam o E lógico, contatos em paralelo realizam o OU e contatos normalmente fechados realizam a negação. Bobinas escrevem o resultado, enquanto temporizadores e contadores são blocos com estado interno. Este trabalho usa a nomenclatura XIC, XIO, OTE, OTL, OTU e RES, comum em controladores Allen-Bradley, e a interface explica a correspondência com NA, NF, SET e RESET.

### 2.3 Ordem de avaliação

As redes são avaliadas de cima para baixo e da esquerda para a direita, e cada escrita tem efeito imediato para as redes seguintes. Essa regra explica, por exemplo, por que duas bobinas no mesmo endereço resultam no valor da última.

### 2.4 Protocolo Modbus

Modbus é um protocolo de comunicação industrial do tipo mestre-escravo, com funções para ler e escrever bits (coils e entradas discretas) e registradores (MODBUS ORGANIZATION, 2012). Neste trabalho, ele aparece em duas formas: Modbus RTU sobre RS-485, para leitura do CLP por supervisórios, e Modbus TCP, para a troca de dados entre o simulador e o Factory IO.

### 2.5 Padrões de projeto

Padrões de projeto são soluções reutilizáveis para problemas recorrentes de projeto de software orientado a objetos, catalogadas por Gamma et al. (1995) em padrões criacionais, estruturais e comportamentais. Usá-los dá nomes comuns às soluções e facilita a manutenção e a extensão do código.

## 3 ARQUITETURA DO SISTEMA

### 3.1 Visão geral

O sistema tem três partes: o Desktop, em Python com a biblioteca gráfica PySide6; o firmware, em C/C++ para o ESP32; e os contratos compartilhados entre os dois. Os contratos são a especificação da ISA (`isa.json`), do protocolo (`protocol.json`) e os vetores de teste. As decisões de arquitetura estão registradas em sete ADRs no repositório.

### 3.2 Desktop

O Desktop é dividido em pacotes com responsabilidades separadas, apresentados no Quadro 1. Os pacotes de regras (`core`, `model`, `compiler`, `sim` e `comm`) não dependem da interface gráfica, o que permite usá-los também na linha de comando e nos testes.

Quadro 1 – Pacotes do Desktop

| Pacote | Responsabilidade |
|---|---|
| core | ISA, formato LDRB, montador LIL, máquina virtual de referência e CRC |
| model | Projeto versionado; redes em árvore série/paralelo; operações de edição |
| compiler | Validação, geração do LDRB e mapa entre instruções e elementos do diagrama |
| sim | Simulador com tempo virtual e ponte com o Factory IO |
| envs | Ambientes de simulação animados, carregados como plugins |
| comm | Protocolo LDP, transportes, transferência, monitor e cliente Modbus TCP |
| codegen e verify | Tradução para C++ e verificação no código C do firmware |
| ui | Janela, diagrama, paleta e painéis |
| cli | Linha de comando para hardware, evidências e diagnóstico |

Fonte: Elaborado pelos autores (2026).

### 3.3 Firmware

A lógica do dispositivo fica nas bibliotecas portáteis `ladder_vm` (máquina virtual, validação e CRC) e `plc_core` (estados, carga transacional, varredura, protocolo e Modbus), escritas em C99. O acesso ao hardware passa por uma camada de abstração, implementada para o ESP32 (registradores 74HC595 e 74HC165, sistema de arquivos LittleFS, FreeRTOS) e para o dispositivo virtual que roda no computador.

## 4 PADRÕES DE PROJETO

O código foi organizado segundo padrões de projeto do catálogo de Gamma et al. (1995) e padrões de arquitetura descritos por Fowler (2002). O Quadro 2 resume onde cada padrão é usado. O documento `docs/design-patterns.md` traz os diagramas e as referências ao código.

Quadro 2 – Padrões de projeto empregados

| Padrão | Onde | Problema resolvido |
|---|---|---|
| Adapter | EnvironmentPlant, FactoryIOLink, MonitorSource | Ligar fontes diferentes ao simulador e ao diagrama sem modificá-los |
| Strategy | Transport (serial, TCP, processo) | Trocar o meio de comunicação sem mudar o protocolo |
| Template Method | Environment | Ambientes novos implementam apenas a física e o desenho |
| Composite | Rung e Parallel | Ramos paralelos aninhados tratados de forma uniforme |
| Interpreter | LadderVM e ladder_vm | Executar o programa compilado no PC e no ESP32 |
| Observer | Sinais do Qt | Vários componentes de tela reagindo ao mesmo estado |
| Memento | Desfazer e refazer | Restaurar estados anteriores do projeto |
| Command | QAction | O mesmo comando no menu, na barra e no atalho |
| Facade | compile_project, DeviceClient | Esconder etapas internas atrás de uma chamada simples |
| Factory Method | create, node_from_dict | Recriar objetos a partir do projeto salvo |
| Registry e Plugin | Ambientes de simulação | Novos ambientes sem alterar a IDE |
| Camadas e HAL | Pacotes do Desktop, plc_hal_t | Regras independentes da interface e do hardware |

Fonte: Elaborado pelos autores (2026).

O padrão Adapter foi o que permitiu integrar o Factory IO sem alterar o simulador: o simulador conhece apenas a interface de processo físico (`Plant`), e o Factory IO passou a ser mais um adaptador dessa interface, como os ambientes internos.

## 5 MODELO INTERMEDIÁRIO

O projeto é salvo em JSON versionado e representa cada rede como uma árvore série/paralelo; o editor só permite estruturas válidas. O compilador gera a imagem LDRB, descrita no documento `docs/intermediate-format.md`: cabeçalho de 32 bytes, tabelas de temporizadores e contadores, instruções de 4 bytes (código da operação, área e índice) e CRC-32. A validação segue uma ordem normativa idêntica no Desktop e no firmware, o que garante o mesmo código de erro para a mesma imagem. Há também uma forma textual (LIL) para exportação, importação e testes.

## 6 INTERPRETADOR E CICLO DE VARREDURA

### 6.1 Interpretador

A avaliação usa um registrador de resultado lógico (RLO) e uma pilha de ramos. A instrução `SOR` inicia a rede com RLO igual a 1. As instruções `XIC` e `XIO` fazem o E com o bit ou com o seu complemento. `BST`, `NXB` e `BND` acumulam o OU dos ramos, e as instruções de saída não alteram o RLO. Depois de cada instrução, o RLO é registrado, e esse registro anima o fluxo de energia no simulador e no monitor. Não há laços nem saltos, então o tempo de execução é limitado pelo número de instruções.

### 6.2 Ciclo de varredura

No dispositivo, uma tarefa do FreeRTOS executa a varredura a cada 10 ms:
1. lê as entradas pelo 74HC165;
2. calcula o intervalo de tempo decorrido;
3. avalia as redes;
4. escreve as saídas pelo 74HC595;
5. atualiza as estatísticas e o watchdog.

Uma varredura acima de 50 ms leva ao estado de falha. Em parada, em falha e durante a carga de programa, as saídas vão para um estado seguro configurável. A máquina virtual não lê o relógio, mas recebe o intervalo de tempo como parâmetro, o que torna a simulação determinística.

### 6.3 Temporizadores e contadores

A especificação formal está em `docs/ladder-specification.md`. A unidade de tempo é 1 ms, com soma saturada no valor de preset. A varredura que habilita um temporizador não acumula tempo, então o atraso efetivo fica entre o preset e o preset mais um período. O TOF mantém o bit DN pelo tempo programado após a desabilitação, e o RTO preserva o acumulado até a instrução RES. Os contadores contam bordas de subida, e os limites de 32 bits saturam com indicação de estouro.

## 7 COMUNICAÇÃO

### 7.1 Protocolo LDP

O protocolo LDP usa quadros binários com CRC-16, número de sequência e cache de idempotência, o que permite retransmitir com segurança. A transferência é transacional:
1. os blocos vão para uma área temporária;
2. o dispositivo verifica o tamanho e o CRC-32;
3. valida a imagem completa e as E/S;
4. grava de forma atômica no LittleFS;
5. ativa o novo programa.

Qualquer falha preserva o programa anterior.

### 7.2 Modbus RTU

O firmware oferece um escravo Modbus RTU somente leitura na interface RS-485, para que supervisórios leiam entradas, saídas, estado e acumuladores. A transferência de programas não usa Modbus.

## 8 SIMULAÇÃO

### 8.1 Simulador

O simulador executa o mesmo código intermediário do firmware com tempo virtual. Funciona em modo contínuo, por varredura ou passo a passo, com velocidade ajustável de 0,01 a 1000 vezes o tempo real. Acelerar não altera o resultado: o programa vê os mesmos passos de 10 ms, apenas mais deles por segundo.

### 8.2 Ambientes de simulação

Sete processos animados (silo de envase, semáforo, portão de garagem, elevador, linha de garrafas, central de ar comprimido e misturador de batelada) são controlados pelo programa do usuário. Cada um tem física simples e alarmes que indicam erros de lógica, como produto derramado ou motor acionado nos dois sentidos.

### 8.3 Integração com o Factory IO

O Factory IO é um simulador 3D de plantas industriais usado no ensino de automação. Na versão disponível no laboratório (2.2.3), ele se comunica por OPC DA ou por Modbus TCP. O OPC DA depende de DCOM e de um servidor intermediário, e o OPC UA só existe a partir da versão 2.3.2. Por isso, a integração usa o driver Modbus TCP/IP Server do Factory IO (REAL GAMES, [2025?]).

A IDE atua como cliente:
- lê os sensores da cena (função 02) e os entrega ao programa como entradas;
- escreve as saídas do programa nos atuadores da cena (função 15).

Uma thread separada faz a troca a cada 20 ms, para que a varredura não espere pela rede. Enquanto conectado, o simulador roda em tempo real, porque a cena do Factory IO também roda. Como medidas de segurança:
- sem conexão, as entradas valem zero;
- ao desconectar, todos os atuadores são desligados.

O exemplo `examples/factoryio/esteira_lote.ladproj` controla uma esteira com contagem de lotes e alarme de atolamento.

## 9 INTEGRAÇÃO COM O ESP32

A placa usa um ESP32 com oito relés acionados por um registrador 74HC595 e oito entradas optoacopladas lidas por um 74HC165. Os mapeamentos e as polaridades foram obtidos do projeto de referência e ficam isolados em um único arquivo de configuração (`board_config.h`). Na inicialização, as saídas permanecem desabilitadas até o registrador ser carregado com todos os relés desligados. O firmware é compilado com o PlatformIO. [PREENCHER: confirmação dos mapeamentos e das polaridades na placa do grupo.]

## 10 METODOLOGIA

O desenvolvimento foi incremental, em etapas encerradas com código, testes, documentação e registro no Git. As especificações foram escritas antes da implementação, e os vetores de teste compartilhados serviram como contrato executável entre o Desktop e o firmware. Os arquivos de cabeçalho em C são gerados automaticamente a partir das especificações em JSON. [PREENCHER: como o grupo se organizou, reuniões e revisão de código.]

Uso de ferramentas de inteligência artificial: [PREENCHER: declarar conforme as regras da disciplina, por exemplo, que um assistente de programação foi usado para gerar código e documentação revisados pelo grupo.]

## 11 TESTES E RESULTADOS

A estratégia de testes está em `docs/testing.md`. O Quadro 3 resume os resultados obtidos.

Quadro 3 – Resultados dos testes

| Conjunto | Resultado |
|---|---|
| Suíte automatizada (20/10/2026; Windows 11, Python 3.11.9, gcc 6.3.0) | 338 testes aprovados |
| Equivalência entre as VMs em Python e em C (16/10/2026) | 18 vetores, 150 programas aleatórios com 80 varreduras e 300 imagens corrompidas, sem divergência |
| Sensibilidade dos testes (16/10/2026) | Defeito injetado no TOF da VM em C detectado por 3 testes |
| Falhas de comunicação no dispositivo virtual | CRC errado, imagem inválida, blocos fora de ordem, retransmissão, queda de energia na carga, timeout, watchdog e flash corrompida: comportamento conforme especificado |
| Comunicação com o Factory IO (20/10/2026) | Leitura dos sensores e escrita de atuador confirmadas com o Factory IO instalado no computador do grupo |
| Firmware para o ESP32 | Compila sem avisos |
| Ensaios na placa (roteiro H0 a H14) | [PREENCHER: resultados observados e evidências] |
| Demonstração final | [PREENCHER] |

Fonte: Elaborado pelos autores (2026).

## 12 DIVISÃO DAS TAREFAS

[PREENCHER com o trabalho realmente realizado por cada integrante.]

Quadro 4 – Divisão das tarefas

| Integrante | Responsabilidades | Principais entregas |
|---|---|---|
| [PREENCHER] | [PREENCHER] | [PREENCHER] |

Fonte: Elaborado pelos autores (2026).

## 13 CONCLUSÃO

A plataforma atingiu os objetivos propostos no computador. A edição, a compilação, a simulação, a transferência transacional e o monitor funcionam e são verificados por testes automatizados. A equivalência entre o simulador e o firmware é garantida pela mesma especificação e por testes diferenciais. A integração com o Factory IO amplia o uso didático, permitindo testar programas em cenas 3D. [PREENCHER: conclusão sobre os ensaios na placa real.]

Limitações e trabalhos futuros:
- concluir e documentar os ensaios no hardware;
- não há memória retentiva entre partidas (a passagem de STOP para RUN é uma partida a frio);
- o Desktop já tem o transporte TCP, mas o firmware ainda não usa Wi-Fi;
- não há forçamento de E/S nem edição com o CLP em execução;
- a integração com o Factory IO troca apenas sinais digitais e funciona somente com o simulador;
- a placa não mede o estado real dos contatos dos relés;
- o sistema não é um CLP de segurança.

## REFERÊNCIAS

ESPRESSIF SYSTEMS. **ESP32 technical reference manual**. [S. l.]: Espressif Systems, [PREENCHER: ano da versão consultada]. Disponível em: https://www.espressif.com/en/support/documents/technical-documents. Acesso em: [PREENCHER: data].

FOWLER, M. **Patterns of enterprise application architecture**. Boston: Addison-Wesley, 2002.

FRANCHI, C. M.; CAMARGO, V. L. A. **Controladores lógicos programáveis**: sistemas discretos. São Paulo: Érica, [PREENCHER: edição e ano consultados].

GAMMA, E.; HELM, R.; JOHNSON, R.; VLISSIDES, J. **Design patterns**: elements of reusable object-oriented software. Reading: Addison-Wesley, 1995.

INTERNATIONAL ELECTROTECHNICAL COMMISSION. **IEC 61131-3**: programmable controllers – part 3: programming languages. 3. ed. Geneva: IEC, 2013.

MODBUS ORGANIZATION. **MODBUS application protocol specification V1.1b3**. [S. l.]: Modbus Organization, 2012. Disponível em: https://modbus.org/specs.php. Acesso em: [PREENCHER: data].

PETRUZELLA, F. D. **Programmable logic controllers**. New York: McGraw-Hill, [PREENCHER: edição e ano consultados].

REAL GAMES. **Factory I/O manual**: drivers. [S. l.]: Real Games, [2025?]. Disponível em: https://docs.factoryio.com/manual/drivers/. Acesso em: 20 out. 2026.

ROCKWELL AUTOMATION. **Logix 5000 controllers general instructions reference manual**: publicação 1756-RM003. Milwaukee: Rockwell Automation, [PREENCHER: ano da versão consultada].

THE QT COMPANY. **Qt for Python documentation**. [S. l.], [PREENCHER: ano]. Disponível em: https://doc.qt.io/qtforpython-6/. Acesso em: [PREENCHER: data].

## APÊNDICE A – DOCUMENTOS TÉCNICOS DO REPOSITÓRIO

- Especificação LADDER: `docs/ladder-specification.md`.
- Formato LDRB: `docs/intermediate-format.md`.
- Protocolo de comunicação: `docs/communication-protocol.md`.
- Arquitetura: `docs/architecture.md`.
- Padrões de projeto: `docs/design-patterns.md`.
- Integração com o Factory IO: `docs/factory-io.md`.
- Registros de decisão: `docs/decisions/`.
- Roteiro e resultados dos ensaios de hardware: `docs/hardware-test-procedure.md` [PREENCHER: evidências].
- Roteiro da demonstração: `docs/demo-script.md` [PREENCHER: link do vídeo].
