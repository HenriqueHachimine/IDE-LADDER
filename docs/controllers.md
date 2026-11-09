# Controladores do CLP

Ao criar um projeto (Arquivo → Novo), você escolhe o controlador numa lista
agrupada por família (como o "Select Processor Type" do RSLogix 500). Ele
define quantas entradas e saídas o projeto tem, quantas variáveis pode usar
(memórias M, temporizadores, contadores e registradores N) e o tamanho do
programa (instruções e redes). O controlador fica
gravado no projeto (`target.device`) e pode ser trocado em Programa →
Propriedades. Ao trocar, as quantidades acima do novo limite são reduzidas.

O compilador confere os limites:

- entradas, saídas, memórias M e registradores N configurados acima do limite
  do controlador são **erro**;
- temporizador ou contador com número acima do limite (ex.: `T2` num
  controlador com 2 temporizadores, `T0` e `T1`) é **erro**;
- programa com mais instruções ou redes do que a memória do controlador é
  **erro** ("memória de programa esgotada no 1747-L531");
- controlador que não existe nesta instalação é **aviso**, e valem os limites
  gerais da IDE.

## Controladores incluídos

| Controlador | Entradas | Saídas | M | Temporizadores | Contadores | N | Placa real |
|---|---|---|---|---|---|---|---|
| ESP32 Relay X8 (placa do projeto) | 8 | 8 | 256 | 32 | 32 | 64 | sim |
| Somente simulação (16 E/S) | 16 | 16 | 256 | 32 | 32 | 64 | não |
| Personalizado | até 16 | até 16 | até 256 | 32 | 32 | até 64 | não |
| Arduino UNO (ATmega328P) | 8 | 8 | 64 | 8 | 8 | 16 | não (512 instruções, 64 redes) |
| Arduino Mega 2560 | 16 | 16 | 256 | 32 | 32 | 64 | não |

Os controladores Arduino usam os mesmos pinos da aba Placa (UNO: relés em
D2–D9, entradas em A0–A5, D10 e D11; Mega: relés em D22–D37, entradas em
D38–D53). Ao abrir um projeto com um deles (ou com a ESP32), a aba Placa passa
a simular essa placa, se estiver desligada.

### WEG CLIC-02 e Omron CP1E (CLP real pela serial)

| Família | Modelos | E/S | Memória | Ligação com a IDE |
|---|---|---|---|---|
| WEG CLIC-02 | 12HR-D, 12HT-D | 8E / 4S | 300 linhas, 63 M, 31 T, 31 C | Modbus RTU, RS-485 (módulo CLW-02/MBUS 3RD) |
| WEG CLIC-02 | 20HR-D, 20HT-D, 20HR-12D, 20HR-A | 12E / 8S | idem | idem |
| WEG CLIC-02 | 20VR-D, 20VT-D | 12E / 8S | idem | RS-485 incorporada |
| WEG CLIC-02 | 10HR-A | 6E / 4S | idem | módulo CLW-02/MBUS 3RD |
| Omron CP1E tipo E | E10, E14, E20, E30, E40 | 6/4 a 24/16 | 2K passos | só USB (CX-Programmer): somente simulação |
| Omron CP1E tipo E(S) | E14S, E20S, E30S, E40S | 8/6 a 24/16 | 2K passos | Host Link, RS-232C |
| Omron CP1E tipo N | N14, N20, N30, N40 | 8/6 a 24/16 | 8K passos | Host Link, RS-232C |
| Omron CP1E tipo N(S1) | N30S1, N40S1 | 18/12, 24/16 | 8K passos | Host Link, RS-232C (+ RS-485) |
| Omron CP1E tipo NA | NA20 | 12/8 + 2 EA / 1 SA | 8K passos | Host Link, RS-232C |

Cada CP1E vem em três versões: `DR-A` (saída a relé, alimentação 100-240 Vca), `DT-D` (transistor NPN,
24 Vcc) e `DT1-D` (transistor PNP, 24 Vcc). Na lista do novo projeto ficam em dois grupos, "tipo E" e
"tipo N / NA".

Fontes: manual do CLIC-02 (WEG 10009280784, cap. 4.2 e 10) e manual do CP1E (Omron W480,
seções 5-1, 6-1 e 14-1). Os modelos de 60 pontos do CP1E (36E/24S) passam dos limites da IDE (32
entradas) e ficaram de fora.

**Módulos de expansão** (Programa → Módulos de expansão, ou o botão na aba CLP real). As E/S do
projeto passam a ser as do CPU mais as dos módulos, na ordem em que estão encaixados; no programa, as
entradas dos módulos vêm depois das do CPU (ex.: 12HR-D + 1 módulo: `I1.0`..`I1.3` = X01..X04) e as
saídas idem. O diálogo mostra o endereço de cada módulo na IDE e no CLP, e não deixa passar das regras:

- **CLIC-02**: até 3 módulos digitais de 4E/4S (CLW-02/8ER-D, 8ET-D, 8ER-A, 8ER-24A). No CLIC-02 as
  entradas dos módulos são X01..X0C e as saídas Y01..Y0C. Na ligação, a IDE lê X (registrador
  0x0611), escreve M11..M1C (0x0609) e o programa ponte ganha as linhas `M11 → Y01` ... `M1C → Y0C`.
- **CP1E**: até 3 unidades CP1W (8ED, 8ER/8ET/8ET1, 16ER/ET/ET1, 20EDR1/EDT/EDT1, 32ER/ET/ET1,
  40EDR/EDT/EDT1), só nos CPUs de 30 e 40 pontos e no NA20. Cada unidade recebe os canais seguintes
  aos do CPU (CIO m para entradas, CIO n para saídas, seção 6-1-4).
- A IDE aceita até 32 entradas e 32 saídas (`ide_limits` em `isa.json`); combinações acima disso são
  recusadas. A placa ESP32/Arduino continua com 16 de cada.

**Processo → CLP real.** Os dois fabricantes gravam o programa dentro do CLP só com o próprio
software (Clic02 Edit, CX-Programmer), por um formato que os manuais não publicam. O que os manuais
documentam é o acesso às variáveis e ao modo de operação pela serial, e é isso que a IDE usa: o
programa LADDER compilado roda na IDE e o CLP real é o cartão de E/S. **Transmitir e executar**
compila, conecta e põe a simulação para rodar em 1×; a cada ciclo (50 ms por padrão) a IDE lê as
entradas do CLP e escreve as saídas do programa. Ao desconectar, as saídas do CLP são desligadas;
se a comunicação cair, as entradas voltam a 0 e a IDE tenta de novo a cada segundo.

- **CLIC-02** (Modbus RTU escravo, padrão 38400 8N2): no CLP, `CONFIG` com `REMOTE I/O = N` e `ID`
  de 1 a 99. Grave nele uma vez, pelo Clic02 Edit, o *programa ponte* `M01 → Q01` ... `M08 → Q08`
  (o CLIC-02 só comanda as saídas pelo próprio programa). A IDE lê `I01..I0C` (registrador 0x0610),
  escreve `M01..M08` (0x0608), lê `Q01..Q08` (0x0613) e muda RUN/STOP (0x0100).
- **CP1E** (Host Link modo C, padrão 9600 7E2, unidade 0): porta RS-232C em Host Link, CLP sem
  programa (ou com um que não use CIO 100/101). A IDE põe o CP1E em MONITOR (`SC`), lê as entradas
  em CIO 0 e 1 (`RR`, 12 bits por canal) e escreve as saídas em CIO 100 e 101 (`WR`, 8 bits por canal).

O código está em `comm/plc_serial.py` (protocolos), `sim/plc_link.py` (troca de dados) e
`ui/plc_panel.py` (painel).

### Allen-Bradley (SLC 500, MicroLogix 1000)

A lista traz os processadores do RSLogix 500, com o mesmo texto:

- **SLC 500 modular**: 1747-L553, L552, L551 (5/05, OS500, Ethernet + RS-232),
  L543, L542B, L541, L542A (5/04, OS401/OS400, DH+ + RS-232), L532C/D, L531,
  L532B, L532 (5/03, OS302/OS301/OS300, DH-485 + RS-232), L524 (5/02) e
  L514, L511 (5/01).
- **MicroLogix 1000** (Bul.1761): básico (10E/6S), DH-485/HDSlave (16E/12S) e
  Analog (20E/12S).
- **SLC 500 fixo**: 1747-L20x (12E/8S), L30x (18E/12S) e L40x (24E/16S), com o
  tipo de entrada (VCA, CC consumidora/fornecedora) e de saída (relé, triac,
  transistor).

E/S por família: 5/05 tem 16/16, 5/04 tem 12/12, 5/03, 5/02 e 5/01 têm 8/8.

**Mais de 16 entradas.** A placa, o protocolo LDP e o firmware usam máscaras de
16 bits (`limits.max_inputs` em `isa.json`). A IDE aceita até 32 entradas
(`ide_limits.max_inputs`) no compilador, no simulador, nos ambientes e no C++
gerado, para os controladores somente de simulação (L30: 18, L40: 24, MicroLogix
Analog: 20). A imagem de um projeto desses não é aceita pela placa (a validação
do lado da placa continua em 16), e os controladores com placa (ESP32, Arduino)
continuam com no máximo 16.

As entradas e saídas do projeto são sempre exatamente as do controlador (o CLP
real tem a quantidade da CPU ou do módulo): em Editar → Propriedades do projeto esses
campos ficam travados, trocar o controlador troca as E/S, e um projeto salvo
com outras quantidades é ajustado ao abrir (a barra de status avisa; salve para
manter). Só o *Personalizado* deixa escolher as quantidades. O Simulador de E/S
mostra no título as quantidades em uso (ex.: `24E / 16S` no 1747-L40A).

A memória real (1K a 64K palavras) é escalada para a IDE: cada 1K vale 32
instruções, 4 redes, 4 memórias M, meio temporizador, meio contador e 1
registrador N. Há um mínimo de 64 instruções, 16 redes, 16 memórias M, 4
temporizadores, 4 contadores e 4 registradores N, para os modelos de 1K e 4K
continuarem utilizáveis. Assim, 64K corresponde aos limites da ISA (2048
instruções e 256 redes) e o 1747-L531 (8K) fica com 256 instruções em 32
redes.

Os Allen-Bradley não têm placa real neste projeto: são somente simulação.

Os limites da ESP32 Relay X8 são os do firmware deste projeto (os mesmos da
ISA, `shared/specifications/isa.json`). A placa recusa, na transferência,
programas com mais entradas ou saídas do que ela tem (erro `INCOMPATIBLE`),
por isso o perfil "Somente simulação" serve para estudar sem a placa.

## Acrescentar um controlador

Crie `~/.ladderide/controladores.json` (no Windows,
`C:\Users\<usuário>\.ladderide\controladores.json`) com uma lista no mesmo
formato de `shared/specifications/controllers.json`:

```json
{
  "controllers": [
    {
      "id": "didatico-4x2",
      "name": "CLP didatico 4E/2S",
      "description": "Exercicio com poucos recursos.",
      "inputs": 4, "outputs": 2, "markers": 8,
      "timers": 2, "counters": 1, "words": 4,
      "scan_period_ms": 10, "hardware": false,
      "instructions": 256, "rungs": 32,
      "family": "Didático", "spec": "4E/2S, programa pequeno"
    }
  ]
}
```

Campos opcionais: `instructions` e `rungs` (memória de programa), `family`
(grupo na lista), `catalog`, `spec` (texto da coluna Tipo), `cpu`, `memory_k`,
`os`, `ports` (portas de comunicação), `board` (perfil da aba Placa) e `link` (`clic02` ou
`hostlink`: protocolo da aba Processo → CLP real).
Valores acima dos limites da ISA são reduzidos a esses limites. Um `id` igual
ao de um controlador incluído substitui o incluído. O arquivo é lido sempre
que a lista é aberta; se estiver inválido, é ignorado.

Um controlador novo **não** cria firmware para outra placa: para gravar numa
placa diferente da ESP32 Relay X8, o firmware precisa ser adaptado
(`firmware/src/board_config.h` e `io_board.cpp`).
