# Formato de projeto `.ladproj` (versão 1)

Arquivo JSON UTF-8, legível e versionável no Git. Implementação:
`desktop/src/ladderide/model/project.py`.

```json
{
  "format": "ladderide-project",
  "format_version": 1,
  "name": "Demonstracao",
  "description": "texto livre",
  "version": "1.0.0",
  "created": "2026-10-16T10:00:00",
  "modified": "2026-10-16T11:00:00",
  "io": {"n_inputs": 8, "n_outputs": 8, "n_markers": 64, "safe_outputs": 0, "scan_period_ms": 10},
  "target": {"device": "esp32-relay-x8", "transport": "serial", "port": "COM5", "baudrate": 115200,
             "host": "", "tcp_port": 5020},
  "symbols": [{"name": "Partida", "address": "I0.0", "comment": "botao NA"}],
  "rungs": [
    {"comment": "Selo",
     "condition": [
        {"type": "parallel", "branches": [
            [{"type": "contact", "kind": "XIC", "operand": "Partida"}],
            [{"type": "contact", "kind": "XIC", "operand": "Motor"}]]},
        {"type": "contact", "kind": "XIO", "operand": "Parada"}],
     "outputs": [{"type": "coil", "kind": "OTE", "operand": "Motor"}]}
  ],
  "history": [{"date": "2026-10-16T11:00:00", "action": "salvo", "rungs": 9}],
  "build": {"compiler_version": "1.0.0", "format": "LDRB 1.0", "build_id": "0x3bab0b1e",
            "size": 232, "instructions": 43, "date": "2026-10-16T11:00:00"}
}
```

## Elementos

| `type` | Campos | Onde |
|---|---|---|
| `contact` | `kind`: `XIC` (NA) ou `XIO` (NF); `operand` | condição |
| `not` | — | condição |
| `parallel` | `branches`: lista de listas de elementos de condição | condição |
| `coil` | `kind`: `OTE`, `OTL` (SET), `OTU` (RESET); `operand` | saídas |
| `timer` | `kind`: `TON`, `TOF`, `RTO`; `operand` (`Tn` ou símbolo); `preset` (ms) | saídas |
| `counter` | `kind`: `CTU`, `CTD`; `operand` (`Cn` ou símbolo); `preset` | saídas |
| `reset` | `operand` (`Tn`/`Cn` ou símbolo) | saídas |

Operandos aceitam endereço (`I0.0`, `M3.1`, `T0.DN`…), nome de símbolo, ou
`Simbolo.CAMPO` quando o símbolo aponta para `Tn`/`Cn` (ex.: `Atraso.DN`).
Nomes de símbolo: letras, dígitos e `_`, até 32 caracteres, sem parecer um
endereço; comparação sem diferenciar maiúsculas.

Os temporizadores e contadores não são declarados à parte: o tipo e o preset vêm
da instrução TON/TOF/RTO/CTU/CTD que os aciona (exatamente uma por elemento).

## Versões

`format_version` é verificado ao abrir: versões futuras são recusadas com
mensagem clara; versões antigas passam por `migrate()` (hoje só existe a 1).
`history` guarda as últimas 50 gravações; `build` registra a última compilação
bem-sucedida.
