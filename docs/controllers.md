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
real tem a quantidade da CPU ou do módulo): em Programa → Propriedades esses
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

Nenhum deles tem placa real neste projeto: são somente simulação.

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
`os`, `ports` (portas de comunicação) e `board` (perfil da aba Placa).
Valores acima dos limites da ISA são reduzidos a esses limites. Um `id` igual
ao de um controlador incluído substitui o incluído. O arquivo é lido sempre
que a lista é aberta; se estiver inválido, é ignorado.

Um controlador novo **não** cria firmware para outra placa: para gravar numa
placa diferente da ESP32 Relay X8, o firmware precisa ser adaptado
(`firmware/src/board_config.h` e `io_board.cpp`).
