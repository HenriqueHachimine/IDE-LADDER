# Hardware de referência

> **Estado:** levantamento a partir do repositório
> `multigcs/esp32_relay_x8_modbus_303e32dc812` (MIT, © 2026 Oliver Dippel).
> **Nada aqui foi verificado na placa do grupo ainda.** Itens marcados ⚠ devem
> ser confirmados com multímetro/teste antes da Etapa 5.

## 1. Placa

Placa com módulo ESP32-WROOM (32E presumido), 8 relés SRD-05VDC-SL-C
(contato 10 A 250 VCA / 10 A 30 VCC, conforme serigrafia), 8 entradas
optoacopladas, transceptor RS-485, USB-C (conversor USB-serial) e entrada de
alimentação marcada 9–24 V ⚠.

## 2. Mapeamento (código de referência)

| Função | GPIO | Observação |
|---|---|---|
| 74HC595 SER (dados dos relés) | 33 | |
| 74HC595 SCK / 74HC165 CLK | 26 | relógio compartilhado |
| 74HC595 RCK / 74HC165 SH/LD | 25 | latch compartilhado ⚠ |
| 74HC595 /OE | 13 | ativo em 0; manter em 1 até carregar o padrão seguro |
| 74HC165 QH (entradas) | 27 | |
| RS-485 RX / TX | 18 / 19 | UART2 |
| RS-485 DE/RE | 32 | 1 = transmitir |

Permutações (índice do bit no registrador de deslocamento → canal lógico):

```c
outMapping[8] = {7, 6, 5, 4, 3, 2, 1, 0};  // relés
inMapping[8]  = {6, 4, 2, 0, 1, 3, 5, 7};  // entradas
```

Polaridades observadas no código de referência:

- **Saídas:** o bit escrito no 74HC595 é **invertido** (`!(val_out & bit)`),
  ou seja, nível 0 no pino do registrador = relé energizado ⚠.
- **Entradas:** leitura em 0 = entrada ativa (optoacoplador puxa para GND) ⚠.

Sequência segura de inicialização (a manter no firmware): `/OE = 1` →
deslocar padrão "todos desligados" → pulso de latch → `/OE = 0`.
Entre a energização e esse ponto, as saídas do 74HC595 ficam em alta
impedância; o estado do relé nesse intervalo depende dos resistores da placa ⚠
(verificar se algum relé pulsa no boot).

GPIOs de *strapping* (0, 2, 5, 12, 15) não são usados pelos sinais acima.

## 3. Pendências a confirmar na placa

1. Modelo exato (foto da serigrafia, versão da PCB) e chip USB-serial
   (CH340/CP2102) — define driver no Windows e circuito de auto-reset.
2. Polaridade real dos relés e das entradas (teste: ligar um relé por vez;
   aplicar tensão em cada entrada).
3. Faixa de tensão das entradas optoacopladas (5 V? 12 V? 24 V?) e se são
   NPN/PNP.
4. Se o latch compartilhado 595/165 lê as entradas corretamente na mesma
   sequência de deslocamento.
5. Comportamento dos relés durante boot/reset (osciloscópio ou LED de teste).
6. Corrente da fonte para os 8 relés acionados simultaneamente (~70 mA cada).

## 4. Riscos com cargas reais

- Este equipamento **não é um CLP de segurança** e não possui certificação.
  Não use para funções de parada de emergência ou proteção de pessoas.
- Use cargas de baixa tensão (LEDs, lâmpadas 12/24 V) nas demonstrações.
  Cargas de rede elétrica exigem supervisão do professor, gabinete fechado e
  proteção adequada.
- O estado seguro configurável (`safe_outputs`) apenas define o comando aos
  relés em STOP/FAULT; não cobre falha do próprio ESP32, da fonte ou de um
  relé colado. Intertravamentos críticos devem ser elétricos.
