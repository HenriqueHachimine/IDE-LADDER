# ADR 0001 — Desktop em Python 3.11 + PySide6

**Estado:** aceita (2026-10-16)

## Contexto
O Desktop precisa de um editor gráfico com arrastar-e-soltar, simulador,
comunicação serial, testes automatizados e distribuição no Windows, mantido
por estudantes de turmas futuras.

## Alternativas

| Opção | Editor gráfico | Serial/rede | Testes | Distribuição | Continuidade acadêmica |
|---|---|---|---|---|---|
| **Python + PySide6 (Qt)** | Qt Graphics View: cenas com itens, zoom, seleção, arrastar — ideal para diagramas | pyserial, sockets | pytest | PyInstaller (.exe) | Python é ensinado cedo; código curto |
| C# + WPF/WinForms | Bom (Canvas WPF), mais código manual | System.IO.Ports | xUnit | excelente | Requer .NET SDK (não instalado na máquina atual); menos familiar |
| Java + Swing/JavaFX | Swing envelhecido; JavaFX ok | jSerialComm | JUnit | jlink/instalador | O projeto anterior usa Swing, mas não há código reaproveitável (análise §2.2) |
| Electron/TypeScript | Excelente (SVG/canvas) | módulo nativo `serialport` exige recompilação | Jest | instalador grande | Duas linguagens; empacotamento complexo |
| C++ + Qt | Igual ao PySide6 | QtSerialPort | GoogleTest | windeployqt | Curva de aprendizado alta |

## Decisão
Python 3.11 + PySide6 (LGPL, uso como biblioteca dinâmica é compatível com
licença MIT do projeto).

## Consequências
- O núcleo (`core`, `model`, `compiler`, `sim`, `comm`) é Python puro e
  testável sem interface.
- Desempenho medido (2026-10-16, Python 3.11, notebook de desenvolvimento):
  ≈ 1,9 milhão de instruções/s; um programa com o máximo de 2 043 instruções
  leva ≈ 1,05 ms por varredura — folga de ~10× para a varredura de 10 ms.
- Distribuição por PyInstaller (executável ~100 MB por causa do Qt).
