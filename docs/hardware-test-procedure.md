# Roteiro de testes no hardware real

> **Situação:** nenhum destes ensaios foi executado ainda. O desenvolvimento
> foi feito sem acesso à placa; tudo o que está marcado como verificado no
> projeto foi verificado no simulador e no dispositivo virtual. Preencha as
> colunas **Observado**, **Data/quem** e **Evidência** ao executar. Não marque
> como aprovado um ensaio sem evidência (foto, vídeo ou log).

## Preparação

1. Gravar o firmware: `cd firmware && pio run -t upload --upload-port COMx`
   (ver `docs/hardware-setup.md`).
2. Alimentar a placa conforme a serigrafia (VERIFICAR a faixa de tensão).
3. Usar cargas de teste de baixa tensão (LEDs com resistor, lâmpadas 12/24 V) ou
   apenas observar os LEDs/clique dos relés. **Não ligar cargas de rede elétrica.**
4. Entradas: aplicar o nível de acionamento da placa (VERIFICAR: 5/12/24 V; NPN/PNP)
   com um botão ou jumper.
5. Registrar os logs com a CLI, por exemplo:
   `python -m ladderide.cli --port COM5 monitor --count 50 > evidencias/H3.txt`

## Ensaios

| ID | Objetivo | Procedimento | Esperado | Observado | Data/quem | Evidência |
|---|---|---|---|---|---|---|
| H0 | Comunicação e identificação | `cli --port COMx info` e `status` | firmware 1.0.0, hardware esp32-relay-x8-303e32dc812, E/S 8/8, estado STOP. O ESP32 **não** reinicia ao abrir a porta | | | |
| H1 | Mapeamento e polaridade das **entradas** | Transferir `examples/hardware/espelho_entradas.ladproj`, RUN; acionar I0.0…I0.7 uma por vez | Cada entrada Ik liga somente o relé k; com a entrada solta o relé desliga | | | |
| H2 | Mapeamento e polaridade das **saídas** | Transferir `examples/hardware/teste_reles.ladproj`, RUN, manter I0.0 ativo | Relés 1→8 ligam um por vez, 1 s cada, em ordem, e o ciclo recomeça | | | |
| H3 | Estado na energização | Desligar e ligar a placa observando os relés | Nenhum relé pulsa durante o boot; após o boot, estado STOP, relés desligados | | | |
| H4 | Lógica combinacional | `examples/combinational/portas_logicas.ladproj`; tabela verdade A=I0.0, B=I0.1 | Q0.0 AND, Q0.1 OR, Q0.2 NOT A, Q0.3 XOR, Q0.4 NAND; I0.2 SET / I0.3 RESET em Q0.5 | | | |
| H5 | TON e TOF | `examples/demo/demonstracao.ladproj`: pulsar Partida; medir com cronômetro/vídeo | Q0.1 liga 2 s após Q0.0; Q0.2 desliga 3 s após Parada (tolerância: ±1 varredura + jitter, ver §Critérios) | | | |
| H6 | Contagem | Demonstração: com motor ligado, 5 pulsos em I0.2; depois I0.3 | Q0.3 liga no 5º pulso; segurar I0.2 não conta duas vezes; I0.3 zera | | | |
| H7 | SET/RESET | Portas lógicas: I0.2 e I0.3 | Q0.5 mantém após soltar I0.2; RESET prevalece se ambos ativos | | | |
| H8 | STOP | Em RUN com relés ligados: `cli stop` ou botão STOP | Todos os relés vão ao estado seguro (desligados) imediatamente | | | |
| H9 | Equivalência no dispositivo | `cli --port COMx equivalence` | `18/18 vetores idênticos ao simulador` (relés permanecem desligados) | | | |
| H10 | Transferência com falha | Iniciar `cli download` e desconectar o cabo USB no meio; reconectar; `status` | Programa anterior preservado (mesmo build_id); estado STOP | | | |
| H11 | Desconexão do monitor | Na IDE, monitor ligado; desconectar o USB; reconectar | IDE indica "Comunicação perdida", reconecta sozinha; o CLP **continua em RUN** durante a desconexão | | | |
| H12 | Reinício durante RUN | Pressionar RST da placa em RUN | Volta em STOP (AUTORUN=0), programa preservado | | | |
| H13 | Tempo de varredura | `cli status` após 1 min em RUN com a demonstração | exec_max < 1 ms, intervalo máx < 20 ms, atrasos ≈ 0 | | | |
| H14 | Modbus RTU (opcional) | Mestre Modbus (ex.: QModMaster) no RS-485, endereço 11, 9600 8N1, FC02 0..7 | Entradas lidas corretamente; FC05 retorna exceção 01 | | | |

## Critérios de tolerância

- Estados lógicos, contagens e ordem de eventos: **idênticos** ao simulador.
- Tempos: `|medido − preset| ≤ período de varredura (10 ms) + jitter medido
  (intervalo máx − 10 ms) + erro do instrumento de medida`. Com cronômetro
  manual, considere ±200 ms de erro humano; prefira vídeo a 60 fps (±17 ms).
- Equivalência H9: tolerância zero (a VM recebe o mesmo `dt`).

## Se algo falhar

| Sintoma | Provável causa | Ajuste |
|---|---|---|
| Relé k liga quando deveria ser j | `OUT_MAP` | `firmware/src/board_config.h` |
| Relés invertidos (ligados em STOP) | `RELAY_ACTIVE_LOW` | idem |
| Entradas invertidas ou trocadas | `INPUT_ACTIVE_LOW`, `IN_MAP` | idem |
| Entradas atrasadas/erradas | latch 595/165 compartilhado | revisar `io_board_transfer` |
| ESP32 reinicia ao conectar | DTR/RTS | conferir versão do pyserial/driver |

Após qualquer ajuste: regravar, repetir H1–H3 e registrar no `CHANGELOG.md`.
