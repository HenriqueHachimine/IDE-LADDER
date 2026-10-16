# Vetores de teste compartilhados

Estes arquivos são a referência executável da especificação
(`docs/ladder-specification.md`). Cada vetor é executado:

1. na VM Python do simulador Desktop, verificando as expectativas (`expect`); e
2. na VM C do firmware, compilada para o PC (`firmware/test/host`), comparando
   o estado completo após **cada** varredura com o da VM Python.

Quem roda: `desktop/tests/test_vectors.py` (veja `docs/testing.md`).

## `scan/*.json` — comportamento de execução

```json
{
  "name": "identificador",
  "description": "o que o vetor demonstra",
  "program": ["linhas LIL", "..."],
  "steps": [
    {"inputs": {"I0.0": 1}, "dt": 10, "repeat": 3, "expect": {"Q0.0": 1, "T0.ACC": 20}}
  ]
}
```

- `inputs`: alterações nas entradas; o valor persiste nos passos seguintes.
- `dt`: tempo (ms) decorrido desde a varredura anterior; padrão 10.
  A primeira varredura após a partida sempre usa `dt = 0` (regra da VM).
- `repeat`: número de varreduras do passo (padrão 1). `expect` é verificado
  após a última.
- Chaves de `expect`: qualquer operando de bit (`I0.0`, `Q0.1`, `M0.0`, `S0.0`,
  `T0.DN`, `T0.TT`, `T0.EN`, `C0.DN`, `C0.OV`, `C0.UN`), `Tn.ACC`, `Cn.ACC` e
  `SCAN` (contador de varreduras).

## `image-errors.json` — validação de imagens

Cada caso monta um programa LIL (sem validar), aplica mutações nos bytes e
espera um código de erro e índice de instrução idênticos no Desktop e no
firmware. Mutações: `truncate` (novo tamanho), `append` (hex), `patch`
(lista de `{"offset", "hex"}`; offset negativo conta do fim), `fix_crc`
(recalcula o CRC após as mutações).
