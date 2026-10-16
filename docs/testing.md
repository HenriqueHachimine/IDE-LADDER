# Estratégia de testes

## 1. Como executar

```powershell
cd desktop
python -m pytest -q                       # tudo (VM C compilada automaticamente com gcc)
$env:LADDER_FUZZ_ITER=2000; python -m pytest tests/test_fuzz_equivalence.py   # fuzzing longo
python ..\scripts\gen_isa_header.py --check
```

Sem `gcc` no PATH, os testes que usam a VM C são **pulados** (aparecem como
`skipped`). Na CI, `LADDER_REQUIRE_C=1` transforma a ausência em falha.

## 2. Camadas

| Camada | Arquivo | O que garante |
|---|---|---|
| Unitários do núcleo | `desktop/tests/test_core_units.py` | CRC (valores de referência), operandos, montador ↔ desmontador, limite de tamanho, saturação de contadores, modo passo a passo ≡ varredura completa, partida a frio, header C em dia |
| Vetores de especificação | `desktop/tests/test_vectors.py` + `shared/test-vectors/` | Cada regra da spec com resultado esperado escrito à mão, verificado na VM Python **e** comparado varredura a varredura com a VM C |
| Erros de imagem | `shared/test-vectors/image-errors.json` | Mesmo código de erro e índice no Desktop e no firmware |
| Diferencial aleatório | `desktop/tests/test_fuzz_equivalence.py` | Programas aleatórios (ramos aninhados, temporizadores, contadores, RES, dt extremos) e imagens corrompidas: Python ≡ C |
| Comunicação | Etapa 6 | desconexão, porta indisponível, CRC errado, timeout, repetição de `seq`, reset durante carga (transporte simulado + hardware) |
| Hardware | Etapa 8 | roteiro com resultado esperado × observado e evidências (fotos/vídeo/logs) |

## 3. Equivalência simulador × hardware

1. **Determinística (automática):** dada a mesma sequência `(entradas, dt)`,
   as VMs Python e C devem produzir `dump_line` idênticos. Tolerância: **zero**.
2. **No dispositivo (Etapa 8):** o firmware terá um modo de *replay* que
   executa a VM com uma sequência `(entradas, dt)` recebida pelo protocolo em
   vez das entradas físicas e do relógio, e devolve os estados. Assim, os
   mesmos vetores rodam no ESP32 real, também com tolerância zero.
3. **Em tempo real:** comparando o monitor online com o simulador para os
   mesmos estímulos físicos, a tolerância para eventos temporizados é
   `período de varredura + jitter máximo medido` (meta: 10 ms + 2 ms).
   Contagens, estados lógicos e ordem de eventos devem ser idênticos.

## 4. Registro de resultados

| Data | Escopo | Resultado |
|---|---|---|
| 2026-10-16 | Etapa 1–3 (núcleo), Windows 11, Python 3.11.9, gcc 6.3.0 (MinGW) | 139 testes aprovados; fuzzing 150 programas × 80 varreduras + 300 imagens mutadas sem divergência; bug injetado no TOF da VM C detectado (3 falhas) e revertido |
