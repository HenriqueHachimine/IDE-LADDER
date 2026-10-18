# Exemplos para o ESP32

Programas independentes para a placa ESP32 Relay X8. Gravar um exemplo
**substitui o firmware do CLP** na placa. Para voltar ao CLP (e usar a IDE para
transferir programas), grave o ambiente `esp32dev` de novo.

Os exemplos usam as mesmas rotinas de E/S do firmware (`src/io_board.cpp`) e a
mesma configuração (`src/board_config.h`): pinos dos 74HC595/74HC165,
polaridade e mapeamento. Se a placa for diferente, altere só o `board_config.h`.

Comandos (na pasta `firmware/`):

```powershell
pio run -e exemplo_teste_placa -t upload --upload-port COM5   # grava o exemplo
pio device monitor -b 115200                                   # monitor serial
pio run -e esp32dev -t upload --upload-port COM5               # volta ao firmware do CLP
```

No Linux, a porta é `/dev/ttyUSB0` ou `/dev/ttyACM0`.

| Exemplo | Ambiente PlatformIO | O que faz |
|---|---|---|
| `teste_placa/` | `exemplo_teste_placa` | Teste da placa pelo monitor serial: `1`–`8` liga/desliga OUT1–OUT8, `a` desliga todos, `c` aciona um relé por vez (0,5 s cada), `m` espelha cada entrada INk no relé OUTk, `s` mostra o estado e `h` mostra a ajuda. Imprime as entradas e saídas sempre que mudam. |
| `ladder_portao/` | `exemplo_ladder_portao` | O programa LADDER do portão de garagem (`examples/ambientes/portao.ladproj`) convertido em C++ pela IDE (painel Código C++ ou `ladderide.cli cpp`), rodando direto no ESP32 a cada 10 ms. Entradas I0.0 Abrir, I0.1 Fechar, I0.2 Parar (NF), I0.3/I0.4 fins de curso, I0.5 fotocélula; saídas Q0.0 sobe, Q0.1 desce, Q0.2–Q0.4 lâmpadas. |

Para gerar o C++ de outro projeto e usá-lo no lugar do portão:

```powershell
python -m ladderide.cli cpp meu_projeto.ladproj -o ..\firmware\examples\ladder_portao\portao.cpp
```

Situação: os dois exemplos **compilam** para o ESP32 (`pio run`), sem avisos,
mas **ainda não foram gravados nem testados na placa**. O caminho oficial do
projeto continua sendo o firmware do CLP, que recebe o programa pela IDE
(transferência, RUN/STOP e monitor online). O exemplo em C++ não tem
transferência, monitor nem estado seguro em falha: ele serve para mostrar
como o diagrama vira código para o microcontrolador.
