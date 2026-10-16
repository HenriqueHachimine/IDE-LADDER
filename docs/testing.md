# Estratégia e resultados de testes

## 1. Como executar

```powershell
python -m pip install -e "desktop[gui,comm,dev]"
cd desktop
python -m pytest -q                         # tudo (gcc no PATH para as partes em C)
$env:LADDER_FUZZ_ITER=2000; python -m pytest tests/test_fuzz_equivalence.py
python ..\scripts\gen_isa_header.py --check
cd ..\firmware; pio run                     # compilação do firmware ESP32
```

Sem `gcc`, os testes que usam código C são pulados; na CI
`LADDER_REQUIRE_C=1` transforma a ausência em falha. Os testes de interface
usam `QT_QPA_PLATFORM=offscreen`.

## 2. Camadas

| Camada | Arquivo | O que garante |
|---|---|---|
| Unitários do núcleo | `test_core_units.py` | CRC, operandos, montador, limites, saturação, passo a passo ≡ varredura, partida a frio, headers gerados em dia |
| Vetores da especificação | `test_vectors.py` + `shared/test-vectors/scan` | 18 cenários (contatos, selo, ramos, NOT, SET/RESET, bobina duplicada, bits de sistema, TON/TOF/RTO, RES na mesma varredura, CTU/CTD, presets 0, dt extremo) verificados na VM Python e comparados varredura a varredura com a VM C |
| Erros de imagem | `shared/test-vectors/image-errors.json` | 37 casos: mesmo código e índice no Desktop e no firmware |
| Diferencial aleatório | `test_fuzz_equivalence.py` | 150 programas aleatórios × 80 varreduras e 300 imagens corrompidas: Python ≡ C |
| Modelo, compilador, simulador | `test_compiler_model_sim.py` | Diagnósticos por rede/elemento (13 tipos de erro, 4 avisos), importação LIL, persistência, edição, tempo virtual, estado seguro |
| Exemplos | `test_examples.py` | Todos os exemplos compilam sem avisos; teste de relés, espelho de entradas e roteiro da demonstração no simulador |
| Interface | `test_ui.py`, `test_ui_device.py` | Inserir por clique e por arrastar, mover, desfazer, erros destacados, simulação; conectar ao dispositivo virtual, transferir, RUN, monitor animando o diagrama, STOP, perda de comunicação e reconexão |
| Comunicação | `test_comm.py` | Quadros (lixo, divisão, CRC, timeout), autoteste C (parser + Modbus), e contra o dispositivo virtual: transferência, persistência após reinício, recusa em RUN, CRC errado, imagem inválida, blocos fora de ordem e repetidos, retransmissão idempotente, queda de energia no meio da carga, timeout de sessão, programa incompatível, watchdog/FAULT, flash corrompida, autorun, dispositivo desconectado, comandos inválidos, escrita de memória, **todos os vetores executados no dispositivo** |
| Firmware ESP32 | `pio run` (CI) | Compila sem avisos no código do projeto |
| Hardware | `docs/hardware-test-procedure.md` | Ensaios H0–H14 — **pendentes** |

## 3. Equivalência simulador × hardware

1. **PC (automático):** VM Python × VM C: tolerância zero, vetores + fuzzing.
2. **Firmware (automático no dispositivo virtual, manual na placa):** os mesmos
   vetores rodam pelo comando `TEST_SCAN`, que executa a VM do firmware com as
   entradas e o `dt` fornecidos (`python -m ladderide.cli --port COMx equivalence`).
   Tolerância zero.
3. **Tempo real:** eventos temporizados: `período + jitter medido + erro do
   instrumento` (detalhes em `hardware-test-procedure.md`).

## 4. Registro de resultados

| Data | Escopo | Ambiente | Resultado |
|---|---|---|---|
| 2026-10-16 | Etapas 1–3 | Windows 11, Python 3.11.9, gcc 6.3.0 (MinGW) | 139 testes aprovados; bug injetado no TOF da VM C detectado (3 falhas) e revertido |
| 2026-10-16 | Etapa 4 | + PySide6 6.12.0 (offscreen) | 176 testes aprovados |
| 2026-10-16 | Etapas 5–7 | + PlatformIO 6.2.0, espressif32 6.9.0 | 207 testes aprovados; firmware compila sem avisos (RAM 13,7%, flash 23,8%); `cli --virtual equivalence`: 18/18 |
| 2026-10-16 | Distribuição | PyInstaller 6.22.3 | `LadderIDE.exe --smoke-test`: compila a demonstração (build_id 0x3bab0b1e) e conversa com o dispositivo virtual embutido |
| — | Hardware (H0–H14) | placa do grupo | **não executado** |
| — | CI GitHub Actions | ubuntu/windows | **não executada** (repositório remoto ainda não criado) |
