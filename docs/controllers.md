# Controladores do CLP

Ao criar um projeto (Arquivo → Novo), você escolhe o controlador. Ele define
quantas entradas e saídas o projeto tem e quantas variáveis pode usar:
memórias M, temporizadores, contadores e registradores N. O controlador fica
gravado no projeto (`target.device`) e pode ser trocado em Programa →
Propriedades. Ao trocar, as quantidades acima do novo limite são reduzidas.

O compilador confere os limites:

- entradas, saídas, memórias M e registradores N configurados acima do limite
  do controlador são **erro**;
- temporizador ou contador com número acima do limite (ex.: `T2` num
  controlador com 2 temporizadores, `T0` e `T1`) é **erro**;
- controlador que não existe nesta instalação é **aviso**, e valem os limites
  gerais da IDE.

## Controladores incluídos

| Controlador | Entradas | Saídas | M | Temporizadores | Contadores | N | Placa real |
|---|---|---|---|---|---|---|---|
| ESP32 Relay X8 (placa do projeto) | 8 | 8 | 256 | 32 | 32 | 64 | sim |
| Somente simulação (16 E/S) | 16 | 16 | 256 | 32 | 32 | 64 | não |
| Personalizado | até 16 | até 16 | até 256 | 32 | 32 | até 64 | não |

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
      "scan_period_ms": 10, "hardware": false
    }
  ]
}
```

Valores acima dos limites da ISA são reduzidos a esses limites. Um `id` igual
ao de um controlador incluído substitui o incluído. O arquivo é lido sempre
que a lista é aberta; se estiver inválido, é ignorado.

Um controlador novo **não** cria firmware para outra placa: para gravar numa
placa diferente da ESP32 Relay X8, o firmware precisa ser adaptado
(`firmware/src/board_config.h` e `io_board.cpp`).
