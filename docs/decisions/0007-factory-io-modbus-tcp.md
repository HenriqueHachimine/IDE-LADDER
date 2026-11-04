# ADR 0007 — Integração com o Factory IO por Modbus TCP, no simulador

**Estado:** aceita (2026-10-20)

## Contexto
O grupo quer controlar cenas 3D do Factory IO (versão 2.2.3 no laboratório) com o
programa LADDER. Nessa versão, o Factory IO oferece:
- **OPC DA** (Classic), que só funciona no Windows, depende de DCOM e exige um servidor
  OPC intermediário. O OPC UA só chegou na 2.3.2.
- **Modbus TCP/IP Server e Client.**

O firmware não aceita entradas externas: o LDP não tem comando para forçar entradas, e o
Modbus RTU é somente leitura. Essa é uma decisão de segurança.

## Decisão
- Usar o driver **Modbus TCP/IP Server** do Factory IO. A IDE é o cliente: lê os sensores
  (FC02 ou FC01) e escreve os atuadores (FC15).
- Implementar um cliente Modbus TCP mínimo, só com a biblioteca padrão
  (`comm/modbus_tcp.py`), mantendo o núcleo sem dependências externas.
- Ligar o Factory IO ao **simulador** como mais um processo `Plant`
  (`sim/factoryio.py`, padrão Adapter). Uma thread troca os dados a cada 20 ms e a
  varredura só lê e escreve os últimos valores, sem esperar pela rede.
- Com o Factory IO conectado, a velocidade da simulação fica travada em 1×, porque a
  cena roda em tempo real.
- Comportamento seguro:
  - sem conexão, as entradas do processo valem 0;
  - ao desconectar, a IDE escreve 0 em todas as coils dos atuadores;
  - parada e pausa enviam as saídas do estado parado.
- Não alterar o firmware.

## Consequências
- Controle de cenas do Factory IO sem software intermediário e sem mudar o simulador
  (`Simulator` continua conhecendo apenas `Plant`).
- Testado com um servidor que imita o driver (`tests/test_factoryio.py`). Em
  2026-10-20, a comunicação foi conferida com o Factory IO instalado no PC do grupo:
  leitura dos sensores e escrita de uma coil pela CLI.
- A troca pela rede adiciona alguns milissegundos de atraso. A simulação continua
  correta, mas deixa de ser reprodutível varredura a varredura.
- Ficam de fora:
  - registradores analógicos;
  - o dispositivo virtual e o ESP32 real: exigiriam um modo de entradas remotas no
    firmware, que é uma decisão de segurança à parte.
- Guia de uso: `docs/factory-io.md`.
