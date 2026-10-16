# Como contribuir

1. Crie uma branch `feature/<etapa>-<assunto>` a partir de `main`.
2. Rode `python -m pytest -q` em `desktop/` antes de abrir o *pull request*.
3. Peça revisão de outro integrante; `main` deve permanecer sempre verde.
4. Atualize a documentação afetada e o `CHANGELOG.md` no mesmo PR.

## Alterando a semântica, a ISA ou o formato LDRB

A equivalência entre simulador e firmware depende de mudar tudo junto:

1. `docs/ladder-specification.md` e/ou `docs/intermediate-format.md`;
2. `shared/specifications/isa.json` → rode `python scripts/gen_isa_header.py`;
3. vetores em `shared/test-vectors/` (um caso para cada regra nova);
4. `desktop/src/ladderide/core/` **e** `firmware/lib/ladder_vm/`;
5. se o layout mudar: incremente `minor` (compatível) ou `major` (incompatível).

Nunca "conserte" um vetor para fazê-lo passar sem antes confirmar na
especificação qual comportamento é o correto.

## Estilo

Ver `docs/development-guide.md` §4.
