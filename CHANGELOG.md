# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/);
versionamento semântico.

## [0.1.0] — 2026-10-16

### Adicionado
- Etapa 1: análise de requisitos, avaliação dos projetos de referência, ADRs 0001–0005.
- Etapa 2: especificação semântica LADDER v1.0, formato LDRB v1.0, listagem LIL,
  rascunho do protocolo LDP v0.1, documentação do hardware de referência.
- Etapa 3: núcleo Python (`ladderide.core`: ISA, LDRB, montador, VM) e núcleo C
  do firmware (`ladder_vm`: VM, validação, CRC), gerador do header C a partir
  de `isa.json`, vetores de teste compartilhados e testes diferenciais.
