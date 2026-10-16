# ADR 0002 — Bytecode LDRB e duas VMs verificadas por testes diferenciais

**Estado:** aceita (2026-10-16)

## Contexto
O requisito proíbe "dois interpretadores independentes com comportamentos
diferentes". O simulador roda em Python no Windows; o firmware em C no ESP32.

## Alternativas
1. **Uma única implementação C**, carregada no Desktop por `ctypes` (DLL).
   Elimina divergência por construção, mas exige compilar DLL de 64 bits para
   Windows (o MinGW disponível é 32 bits), complica o empacotamento, e a
   execução passo a passo (por instrução) precisaria de API adicional.
2. **Interpretar a árvore do diagrama no Desktop** e bytecode no firmware —
   rejeitada: são semânticas diferentes por natureza.
3. **Mesmo bytecode, duas VMs pequenas, verificação diferencial contínua.**

## Decisão
Opção 3, com estes controles:

- Constantes geradas de uma única fonte (`isa.json` → `ladder_isa.h`, com
  teste que falha se o header estiver desatualizado).
- VMs mínimas (≈ 250 linhas cada), com a mesma estrutura de código.
- Formato canônico de estado (`dump_line`) contendo **todo** o estado
  observável, incluindo a memória de borda e o fluxo de energia por instrução.
- Vetores escritos à mão para cada regra da especificação +
  *fuzzing* diferencial de programas aleatórios e de imagens corrompidas,
  rodando em todo `pytest` (VM C compilada para o PC).
- Prova de sensibilidade: um bug injetado no TOF da VM C (2026-10-16) foi
  detectado pelo fuzzing e pelos vetores.

A opção 1 continua possível no futuro sem mudar formato nem testes.

## Consequências
- Toda mudança de semântica exige alterar spec, vetores e as duas VMs no mesmo
  commit — documentado em `CONTRIBUTING.md`.
