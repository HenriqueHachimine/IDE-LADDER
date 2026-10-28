# Ligação com o Factory IO (Modbus TCP)

O simulador da IDE pode controlar uma cena 3D do [Factory IO](https://factoryio.com)
em vez de um ambiente interno. A ligação usa o driver **Modbus TCP/IP Server** do
Factory IO: ele é o servidor (escravo), e a IDE é o cliente.

```
Factory IO (Modbus TCP/IP Server)                         LadderIDE (simulador)
  sensores da cena      -> Inputs 0..n        --- FC02 --->  I0.0 ... I0.(n-1)
  valores analogicos    -> Input Regs 0..r    --- FC04 --->  N(inicial) ...
  atuadores da cena     <- Coils 0..m         <-- FC15 ----  Q0.0 ... Q0.(m-1)
  atuadores analogicos  <- Holding Regs 0..h  <-- FC16 ----  N(inicial) ...
```

No painel **Factory IO**, a tabela lista **todas as portas do driver** na ordem em que o
Factory IO as mostra (`Input`, `Input Reg`, `Coil`, `Holding Reg`). Cada linha tem o
endereço correspondente no CLP, o símbolo do projeto e o valor ao vivo. Portas além das
E/S do controlador do projeto aparecem como "sem endereço no projeto": por exemplo, o
`Input 8` num projeto ESP32 de 8 entradas. Para usá-las, escolha um controlador com mais
E/S (*Somente simulação*, 16 E/S).

A coluna **Simbolo** é editável. Dê duplo clique (ou F2) e digite o nome do ponto, por
exemplo `Sensor_Saida`. O endereço sem símbolo ganha um novo símbolo, com a porta do Factory
IO no comentário. Renomear troca o nome em todo o diagrama, inclusive em `Caixas.DN`. Apagar o
nome remove o símbolo e devolve o endereço aos elementos. Nomes inválidos ou repetidos são
recusados. A edição fica bloqueada durante a simulação e pode ser desfeita com Ctrl+Z.

Os registradores analógicos são inteiros de 0 a 65535 e vão para os registradores `N` do
programa, usados com os blocos de comparação e matemática. Por padrão, `Input Reg 0 → N0`
e `N8 → Holding Reg 0`; os dois pontos de partida são ajustáveis na aba *Registradores*. O
programa não deve escrever nos `N` que recebem Input Regs, porque eles são sobrescritos
antes de cada varredura.

## Endereços no diagrama LADDER

Para escolher o endereço de um contato, bobina, temporizador ou contador:
- dê **duplo clique no endereço** escrito embaixo do elemento (ex.: `Q0.0`), ou
- clique com o botão direito e escolha **Alterar endereço...**.

Abre uma lista com os símbolos e endereços. Cada item mostra também a porta do Factory IO
ligada a ele, por exemplo `I0.3 · Sensor_Fim · Input 3 (Factory IO)`. Escolha um item ou
digite o endereço e tecle Enter. O duplo clique no resto do elemento continua abrindo o
diálogo completo, que traz as mesmas sugestões.

> **Situação:** testado contra um servidor Modbus que imita o driver do Factory IO
> (`desktop/tests/test_factoryio.py`). **Ainda não foi testado com o Factory IO de verdade.**

## Requisitos

- Factory IO **Modbus & OPC Edition** ou **Ultimate Edition**, que são as que têm os drivers Modbus.
  Funciona desde a 2.2.3; ver as diferenças de versão abaixo.
- O PC com o Factory IO acessível pela rede, ou o mesmo PC (`127.0.0.1`). Libere a porta
  502 no firewall se forem PCs diferentes.

## 1. Configurar o Factory IO

1. Abra a cena e vá em **File → Drivers** e escolha **Modbus TCP/IP Server**.
2. Em **Configuration**:
   - **Network adapter:** a placa de rede que a IDE vai usar (*loopback* se for o mesmo PC).
   - **Port:** 502. **Slave ID:** o mesmo da IDE (padrão da IDE: 1).
   - **Write Digital = Inputs** (os sensores vão para as entradas discretas) ou Coils.
   - **Read Digital = Coils** (os atuadores são lidos das coils, que a IDE escreve).
   - **Write Register = Input Registers** ou Holding Registers (valores analógicos dos sensores).
   - **Read Register = Holding Registers** (valores analógicos dos atuadores).
   - **Scale:** o Factory IO multiplica o valor analógico pela escala (3,14 com escala 100 vira 314).
   - **Digital Inputs / Digital Outputs:** Offset e Count (até 256 de cada lado).
   - **Register Inputs / Register Outputs:** Offset e Count (até 64 de cada lado).

   *Read Digital* e *Read Register* precisam ser Coils e Holding Registers: um cliente
   Modbus (a IDE) não consegue escrever em Inputs nem em Input Registers.
3. Arraste cada **sensor** da cena para `Input k`. Ele vira `I0.k` no programa.
4. Arraste cada **atuador** para `Coil k`. Ele é comandado por `Q0.k`.
5. Coloque a cena em **RUN** (F5 no Factory IO).

O ponto Modbus `k` corresponde ao bit `k` do CLP, contado a partir do endereço
inicial configurado nos dois lados.

## 2. Conectar a IDE

1. **Simulação → Factory IO (Modbus TCP)...** abre o painel *Factory IO*.
2. Na barra do painel, preencha o **IP** (o *Host* mostrado no topo do driver;
   `127.0.0.1` com o adaptador *loopback*), a **Porta** e o **Slave ID**. **Testar** abre a
   conexão, lê os sensores uma vez e fecha, sem escrever nada na cena.
3. **Configurar driver...** abre as opções na mesma ordem e com os mesmos nomes da página
   *Configuration* do driver: *Auto connect*, *Write/Read Digital*, *Write/Read Register*,
   *Scale* e, para cada tabela, *Offset* e *Count*, com o endereço do CLP correspondente
   (I0.0..., Q0.0..., N...). O diálogo confere a configuração enquanto você edita, e
   **Padrão** volta aos valores padrão da IDE. Portas além das E/S do controlador do projeto
   aparecem na tabela "sem endereço no projeto".
4. Clique em **Conectar**. O painel mostra o estado, o tempo de cada troca e os valores de
   sensores e atuadores. Com *Scale* diferente de 1, os registradores aparecem como
   `314 (3.14)`: o valor bruto, que o programa usa, e o dividido pela escala.
5. Execute a simulação (F5). As entradas que vêm da cena ficam travadas no painel de E/S;
   as demais continuam manuais.

As configurações ficam salvas entre sessões. Com **Auto connect** marcado, a IDE conecta
sozinha ao abrir e, conectada, tenta de novo a cada 1 s se o Factory IO fechar.

## Exemplo: esteira com lote (`examples/factoryio/esteira_lote.ladproj`)

**Cena** (monte numa cena vazia, com peças da paleta do Factory IO):

```
 [Emitter] ──> ════════ Belt Conveyor ════════ ──> [Remover]
               ↑ Diffuse Sensor          ↑ Diffuse Sensor
                 (entrada)                 (saída)
 Painel: Start Button (com luz) · Stop Button · Light Indicator
```

**Ligações no driver** (arraste cada tag para o ponto):

| Ponto Modbus | Tag do Factory IO | Programa |
|---|---|---|
| Input 0 | Start Button | `I0.0` Partida (NA) |
| Input 1 | Stop Button | `I0.1` Parada (**NF**: lê 1 solto) |
| Input 2 | Diffuse Sensor da entrada | `I0.2` Sensor_Entrada |
| Input 3 | Diffuse Sensor da saída | `I0.3` Sensor_Saida |
| Coil 0 | Belt Conveyor | `Q0.0` Esteira |
| Coil 1 | Emitter | `Q0.1` Emissor |
| Coil 2 | Start Button (Light) | `Q0.2` Luz_Partida |
| Coil 3 | Light Indicator | `Q0.3` Luz_Lote |

Na IDE, use **4 sensores e 4 atuadores**.

**Funcionamento:**
- **Partida** liga o sistema (selo) e acende a luz do botão.
- O emissor solta uma caixa sempre que a entrada está livre, e a esteira a leva até o removedor.
- Cada caixa que passa pelo sensor de saída é contada. Com **5 caixas**, a esteira para e o
  Light Indicator acende. Partida começa outro lote.
- Se uma caixa ficar **4 s** no sensor de saída com a esteira ligada, é atolamento: a esteira
  para e a lâmpada pisca até apertar Partida. Para testar, tire o Remover da cena ou segure
  uma caixa com o mouse.
- **Parada** desliga tudo. Como o Stop é NF, uma queda da conexão (entradas em 0) também
  desliga o sistema.

> Confira no driver o valor do Stop Button com ele solto. Se ler 0, o botão está como NA:
> troque o contato `XIC Parada` da rede 0 por `XIO Parada`.

## Comportamento

| Situação | O que acontece |
|---|---|
| Conectado | A cada 20 ms (ajustável de 5 a 1000 ms): lê os sensores (FC02 ou FC01) e escreve as saídas (FC15). A varredura nunca espera pela rede. |
| Velocidade | Fica travada em **1×** enquanto conectado, porque o Factory IO roda em tempo real (a 2.2.3 não tem escala de tempo). A velocidade anterior volta ao desconectar. |
| Simulação parada ou pausada | A cena recebe as saídas do estado parado (o estado seguro do projeto). |
| Ambiente interno | Fica desligado enquanto o Factory IO estiver conectado. |
| Queda de conexão | Os sensores vistos pelo programa vão a 0, o painel mostra o erro e a IDE tenta reconectar a cada 1 s. |
| Desconectar ou fechar a IDE | Escreve 0 em todas as coils dos atuadores antes de fechar. |

Se a IDE for encerrada à força ou a rede cair, o Factory IO mantém o último valor das
coils. Pare a cena nesses casos.

## Diagnóstico pela linha de comando

```powershell
python -m ladderide.cli factoryio 127.0.0.1 --unit 1 --sensors 8 --actuators 8 --count 0
python -m ladderide.cli factoryio --set 1010        # liga Q0.0 e Q0.2 (Coils 0 e 2)
```

O comando mostra os sensores e as coils dos atuadores. Mensagens comuns:

| Mensagem | Causa provável |
|---|---|
| `sem conexao com ...` | **Endereço diferente do Host do driver**: o Factory IO só escuta no IP do *Network adapter* escolhido (ex.: `192.168.56.1` de um adaptador virtual); use esse IP na IDE ou escolha o adaptador *loopback* para usar `127.0.0.1`. Também: Factory IO fechado, driver errado (Client em vez de Server) ou firewall |
| `tempo esgotado` | **Slave ID diferente** (a 2.2.3 não responde a outro ID) |
| `excecao 2: endereco fora da faixa` | Quantidade de Digital Inputs/Outputs do driver menor que a pedida |

## Diferenças entre versões do Factory IO

Segundo as [notas de versão](https://docs.factoryio.com/release-notes/):

- **2.2.3:** o servidor só responde ao Slave ID configurado. Não há mensagens de erro Modbus no
  console nem escala de tempo.
- **2.3.0:** mensagens de erro Modbus no console (`app.log_to_console = 1`) e escala de tempo
  de 0,1× a 4×. A IDE continua em 1×.
- **2.5.6:** o servidor também responde aos IDs 0 e 255.

## Limitações

- Registradores tratados como inteiros sem sinal de 16 bits (0 a 65535). A conversão de
  escala (*Scale*) é a configurada no driver do Factory IO.
- Liga o **simulador** da IDE. O dispositivo virtual e o ESP32 real não participam: o
  firmware não aceita entradas externas (ver `docs/communication-protocol.md`).
- A troca pela rede introduz alguns milissegundos de atraso entre a cena e o programa. A
  simulação continua correta, mas deixa de ser reprodutível varredura a varredura.
