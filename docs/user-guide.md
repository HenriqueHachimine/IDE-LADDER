# Manual do usuário — LadderIDE

## 1. Instalação

A IDE roda no **Windows** e no **Linux**.

**Executável:** gere com `python scripts/build_app.py` no próprio sistema.
- Windows: copie a pasta `dist\LadderIDE` e execute `LadderIDE.exe`.
- Linux: descompacte `LadderIDE-linux-x86_64.tar.gz`, execute `./LadderIDE`
  ou rode `./install.sh` para criar o atalho no menu de aplicativos.

**A partir do código (Windows):**

```powershell
python -m pip install -e "desktop[gui,comm,dev]"
python -m ladderide examples\demo\demonstracao.ladproj
```

**A partir do código (Linux, Debian/Ubuntu):**

```bash
sudo apt install python3-venv build-essential libxcb-cursor0
python3 -m venv .venv && . .venv/bin/activate
python -m pip install -e "desktop[gui,comm,dev]"
python -m ladderide examples/demo/demonstracao.ladproj
```

O dispositivo virtual, a verificação para ESP32 e os testes de equivalência
precisam de `gcc` no PATH (MinGW no Windows, `build-essential` no Linux). O
executável já traz essas partes compiladas.

**Porta serial no Linux:** o ESP32 aparece como `/dev/ttyUSB0` (CP210x/CH340)
ou `/dev/ttyACM0`. Seu usuário precisa estar no grupo `dialout`: rode
`sudo usermod -aG dialout $USER` e depois saia e entre de novo na sessão. Se
a janela não abrir no Wayland, tente `QT_QPA_PLATFORM=xcb python -m ladderide`.

## 2. Tela

```
+------------+--------------------------------+---------------------------+
| Instrucoes | DIAGRAMA LADDER                | Simulador | Dispositivo | |
| (paleta)   |                                | Blocos IL | Codigo C++    |
|            +--------------------------------+  (altura total)           |
|            | Mensagens | Simbolos | Ambiente|                           |
+------------+--------------------------------+---------------------------+
| EDICAO / SIMULACAO / ONLINE   compilacao   simulacao   ESP32: estado    |
+--------------------------------------------------------------------------+
```

- **Barras de ferramentas**, na ordem do trabalho: *Edição* (arquivo, desfazer,
  nova rede, zoom), *Simulação* (código C++, compilar, executar... parar, ambiente) e
  *Dispositivo* (verificar ESP32, transferir, blocos de instrução).
- **Instruções** (esquerda): arraste para o diagrama ou clique para inserir
  depois do elemento selecionado. Some sozinha durante a simulação e o
  monitor online, porque nesses modos o programa não pode ser editado.
- **Diagrama** (centro): redes numeradas entre os trilhos.
- **Direita** (abas): Simulador (entradas, saídas, temporizadores, monitor de
  variáveis), Dispositivo, Blocos de instrução e Código C++.
- **Embaixo do diagrama** (abas): Mensagens, Símbolos e Ambiente. O ambiente
  fica embaixo para a cena e o painel Simulador ficarem visíveis juntos.
- **Barra de status:** o selo mostra o modo atual (EDIÇÃO, SIMULAÇÃO ou
  ONLINE) e, à direita, o estado do ESP32.

Os painéis podem ser arrastados, soltos como janelas ou fechados; a posição
é lembrada. **Exibir → Painéis** reabre um painel fechado e **Exibir →
Restaurar layout padrão** volta à organização original.

**Travar layout** (Exibir → Travar layout, **Ctrl+Alt+L** ou o cadeado no
canto da barra de status): depois de arrumar a tela, trave-a. Travado, os
painéis não podem ser arrastados, desacoplados, fechados ou redimensionados, e
as barras de ferramentas ficam fixas. Se a janela mudar de tamanho, só o diagrama
se ajusta. Destrave pelo mesmo comando. O estado e o layout ficam salvos.

**Tema:** em **Exibir → Tema**, escolha Claro, Escuro ou Seguir o Windows.
O atalho **Ctrl+Shift+T** alterna entre claro e escuro. A escolha fica salva
para as próximas aberturas.

## 3. Editando

| Ação | Como |
|---|---|
| Inserir | Arrastar da paleta até a área destacada em azul (entre contatos, num ramo, na coluna de saídas ou abaixo da última rede para criar outra) |
| Mover | Arrastar o elemento para outro ponto |
| Editar operando/preset/tipo | Duplo clique ou Enter |
| Ramo paralelo (OU) | Arrastar "Paralelo" entre contatos, ou botão direito → Envolver em ramo paralelo / Adicionar ramo |
| Excluir | Delete (elemento ou rede selecionada pelo número) |
| Redes | Botão direito no número: inserir acima/abaixo, comentário, excluir; Ctrl+R nova rede |
| Desfazer/Refazer | Ctrl+Z / Ctrl+Y |
| Zoom | Ctrl+roda do mouse, Ctrl++ / Ctrl+-, Ctrl+0 |

Operandos: endereços (`I0.0`–`I1.7`, `Q0.0`–`Q1.7`, `M0.0`–`M31.7`, `T0`, `C0`,
`T0.DN`, `C0.DN`, `S0.0` primeira varredura, `S0.3` relógio 1 s) ou nomes da aba
**Variáveis** (ex.: `Partida` → `I0.0`; `Atraso.DN` se `Atraso` → `T0`).

Equivalências: XIC = contato NA, XIO = contato NF, OTL = SET, OTU = RESET.
Cada temporizador/contador é acionado por **uma** instrução TON/TOF/RTO/CTU/CTD;
`RES` pode aparecer várias vezes. Semântica completa:
`docs/ladder-specification.md` (F1 mostra um resumo).

## 4. Código C++ (Ctrl+F7) e compilar (F7)

O painel **Código C++** mostra o diagrama traduzido para C++ **antes de
compilar**: ele é refeito a cada edição. Cada rede vira uma linha (ou um
pequeno bloco) com o mesmo nome dos símbolos: contatos em série viram `&&`,
ramos paralelos `||`, contato NF e NOT `!`, bobinas atribuições, SET/RESET
`if (...) X = true/false`, e temporizadores/contadores chamadas como
`TON(Atraso, Motor, dt)`. Exemplo:

```cpp
// ===== Rede 0 - Liga/desliga o processo (selo) =====
Lampada_Run = (Start || Lampada_Run) && Stop;
```

Erros do diagrama aparecem no código como comentários `// ERRO` na rede, e o
operando inválido vira `false`. Clicar numa linha seleciona a rede no
diagrama, e selecionar um elemento destaca a rede no código. **Copiar código**
e **Salvar .cpp** exportam o arquivo completo (runtime dos temporizadores e
contadores, variáveis, `plc_start()` e `plc_scan()`).

O ESP32 continua executando o programa compilado em bytecode pelo
interpretador do firmware; o C++ é a mesma lógica escrita de outra forma. Um
teste automático compila o C++ gerado com g++ e confere, varredura a varredura,
que ele produz os mesmos estados do simulador (exemplos e projetos aleatórios).
O trecho `#ifdef ARDUINO` no fim do arquivo é um ponto de partida para usar o
código como sketch junto com `firmware/src/io_board.cpp`; ele não foi testado
na placa. Esse sketch escreve no monitor serial (115200 bit/s) a lista de
entradas, saídas e temporizadores com os comentários dos símbolos e, a cada
varredura, o que mudou: entradas, temporizadores (começou a contar, DN),
contadores e saídas, com o tempo desde a partida. `s` mostra o estado completo
e `h` a ajuda.

### Compilar (F7)

Erros e avisos aparecem em **Mensagens** com a rede; clique para selecionar o
elemento (destacado em vermelho). Programas com erro não são simulados nem
transferidos. Arquivo → Exportar gera a listagem LIL (texto) ou a imagem LDRB.

## 5. Simular

| Tecla | Ação |
|---|---|
| F5 | Executar continuamente (velocidade 0,1× a 10×) |
| F6 | Pausar |
| F10 | Uma varredura |
| F11 | Uma instrução (destaque laranja na instrução atual) |
| Ctrl+F5 | Reiniciar (partida a frio) |
| Shift+F5 | Parar e voltar à edição |

Verde = energizado. Contatos com preenchimento verde estão "fechados" pelo
valor do operando. Caixas mostram PRE, ACC e bits. Entradas: botões de
retenção ou, marcando "Botões pulsadores", momentâneos. O tempo é virtual
(cada varredura avança o período configurado em Propriedades do projeto).

### Ambientes de simulação (Ctrl+E)

No painel **Ambiente** (embaixo do diagrama), escolha um processo animado: silo de envase, semáforo
de cruzamento, portão de garagem, elevador de 4 andares, linha de garrafas, central de ar
comprimido ou misturador de batelada. O programa controla o processo: as saídas
Q acionam motores, válvulas e lâmpadas, e os sensores do processo alimentam as
entradas I. Clique nos botões desenhados no ambiente. **Criar símbolos no
projeto** adiciona os nomes dos pontos de E/S, e **Abrir programa exemplo**
carrega uma solução. Erros de lógica aparecem como alarmes vermelhos sobre o
desenho. Para criar novos ambientes, veja `docs/simulation-environments.md`.

### Blocos de instrução (F12)

Mostra o diagrama convertido em lista de instruções (IL), um bloco por rede,
na ordem exata em que o ESP32 executa: mnemônico, operando, símbolo e o que
a instrução faz. Clicar numa linha seleciona o elemento no diagrama e vice-versa.
Na simulação, as linhas ficam verdes quando o resultado lógico é 1, e no passo
a passo (F11) a próxima instrução fica destacada. **Copiar texto** e
**Salvar .il** exportam a lista.

## 6. Verificar para o ESP32 (F9)

Antes de transferir, **Programa → Verificar para ESP32** gera um relatório:

| Verificação | O que confere |
|---|---|
| Compilação e imagem LDRB | erros, CRC e formato |
| Validação pelo código C do firmware | o mesmo `lv_image_validate` do ESP32, compilado no PC, aceita a imagem |
| Equivalência simulador × firmware | 400 varreduras com entradas variadas: estado completo idêntico nas duas VMs |
| Entradas e saídas da placa | endereços dentro das 8 entradas e 8 relés (`firmware/src/board_config.h`) |
| Memória e limites | bytes usados, instruções, temporizadores, contadores, aninhamento |
| Temporização | período de varredura do projeto × firmware; presets curtos demais |
| Dispositivo conectado | formato do firmware e **tempo de varredura medido** comparado ao watchdog |

Sem placa conectada, o tempo de varredura real aparece como "não verificado":
a IDE não estima esse valor. As verificações que dependem da VM C precisam
do gcc (MinGW). No executável da IDE, essa VM já vem incluída.

## 7. Dispositivo

1. Aba **Dispositivo** (direita) → Meio: Serial (escolha a COM) ou Dispositivo virtual → **Conectar**.
2. **Transferir programa** (F8): compila, confirma se o CLP estiver em RUN,
   envia em blocos com CRC, o firmware valida e só então substitui o programa.
   Falhas preservam o programa anterior.
3. **RUN / STOP / Limpar falha** (também no menu **Dispositivo**, junto com
   Verificar, Transferir e Monitor online).
4. **Monitor online**: lê o dispositivo a cada 200 ms. O diagrama só é animado
   se o programa no dispositivo for igual ao projeto aberto (mesmo build_id).
   "Lógico" = resultado do programa; "Comandado" = enviado aos relés. A placa
   não mede o estado físico dos contatos.

Em caso de perda de comunicação, a IDE mostra o aviso e tenta reconectar a
cada 2 s. O CLP continua executando sem a IDE.

### Simulador da placa ESP32 (Ctrl+Shift+E)

O painel **Placa ESP32** (embaixo do diagrama) desenha a placa de 8 relés e
mostra como o firmware está configurado. **Ligar ESP32 virtual** inicia o
dispositivo virtual: o mesmo código C do firmware (`plc_core` + `ladder_vm`)
compilado para o PC, conversando com a IDE pelo protocolo LDP como a placa real
faz pela USB. Depois é o mesmo fluxo da placa: **Transferir programa**, **RUN**,
**STOP** e **Reiniciar placa** (o firmware inicia de novo, carrega o programa da
"flash" e, com `AUTORUN_ON_BOOT = 0`, fica em STOP).

- **Placa:** desenhada como a placa de referência (foto e etiqueta do repositório
  `multigcs/esp32_relay_x8_modbus_303e32dc812`): relés OUT1–OUT8 com bornes NC/COM/NO,
  contato móvel e LED, LEDs PWR/RX/TX (RX/TX piscam com o tráfego LDP), entradas optoacopladas
  (clique nelas para ligar/desligar), GPIOs usados pelo ESP32 e os
  registradores 74HC595 (relés) e 74HC165 (entradas). Os registradores mostram
  o **nível elétrico** de cada posição já com a polaridade (ativo em 0) e a
  permutação `OUT_MAP`/`IN_MAP`, e cada relé/entrada indica a posição
  correspondente.
- **Configuração:** todas as definições de `firmware/src/board_config.h`
  agrupadas (pinos, polaridade, mapeamento, RS-485/Modbus, varredura, partida),
  com a explicação de cada uma; os valores marcados `VERIFICAR` aparecem em
  amarelo. Para outra placa, altere esse arquivo (botão **Abrir board_config.h**).
- **Monitor serial:** os quadros LDP trocados com a placa (comando, sequência e
  tamanho); as leituras periódicas ficam ocultas até marcar a opção.
- **Firmware:** versão, programa gravado (build_id, CRC), número de
  varreduras, tempo de execução e há quanto tempo a placa está ligada.

**Exemplos Arduino:** a lista no topo do painel também roda os exemplos de
`firmware/examples/` (por exemplo `teste_placa`, o teste da placa pelo monitor
serial). A IDE compila o exemplo para o PC junto com o `io_board.cpp` do
firmware e uma camada que imita o Arduino; os 74HC595/74HC165 são simulados no
nível dos sinais (clock, latch, /OE), então a placa desenhada mostra os níveis
gerados pelo próprio código. O monitor serial mostra o que o sketch imprime e
envia o que você digitar. Os dois exemplos narram o que acontece: cada comando
recebido, cada troca de modo, cada entrada que muda e cada relé que liga ou
desliga, com o tempo em milissegundos. Detalhes e limites: `firmware/examples/README.md`.

Conectado a uma placa real (aba Dispositivo), o mesmo painel mostra o que o
firmware comanda e lê; nesse caso as entradas vêm dos bornes, não de cliques.
O simulador não reproduz a eletrônica (tempos dos relés, ruído, alimentação):
os níveis mostrados são os calculados a partir de `board_config.h`.

## 8. Linha de comando

```powershell
python -m ladderide.cli ports
python -m ladderide.cli --port COM5 info
python -m ladderide.cli --port COM5 download examples\demo\demonstracao.ladproj --stop
python -m ladderide.cli --port COM5 run
python -m ladderide.cli --port COM5 monitor --count 20
python -m ladderide.cli --port COM5 equivalence
python -m ladderide.cli --virtual status          # dispositivo virtual
python -m ladderide.cli verify projeto.ladproj      # verificacao para o ESP32 (codigo de saida 1 se houver erro)
python -m ladderide.cli il projeto.ladproj -o projeto.il   # blocos de instrucao
python -m ladderide.cli cpp projeto.ladproj -o projeto.cpp # codigo C++ (nao precisa compilar)
```

## 9. Segurança

Este equipamento não é um CLP de segurança. Defina o estado seguro das saídas
(Propriedades do projeto) conforme a carga; desenergizar nem sempre é seguro.
Use cargas de baixa tensão nas aulas.
