# ADR 0004 — Protocolo próprio (LDP) na USB; Modbus RTU somente leitura

**Estado:** aceita (2026-10-16)

## Contexto
É preciso transferir programas com integridade e ativação controlada, e
monitorar variáveis. A placa tem USB (UART0) e RS-485.

## Decisão
- Transferência, controle de modo e monitor pelo **LDP** (quadros binários com
  CRC-16, `seq` idempotente, carga em staging + commit), especificado em
  `docs/communication-protocol.md`. O mesmo quadro poderá trafegar em TCP.
- **Modbus RTU** no RS-485 apenas para leitura por supervisórios. Modbus não
  define carga/validação/ativação de programa; usá-lo para isso exigiria um
  protocolo próprio encapsulado de qualquer forma.

## Consequências
- O Desktop não depende de bibliotecas Modbus.
- O RS-485 fica livre para integração futura com SCADA sem afetar a IDE.
