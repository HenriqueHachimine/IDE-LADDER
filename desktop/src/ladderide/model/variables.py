"""Variaveis de memoria (boolean, inteira, float): enderecos automaticos e valores iniciais.

Boolean ocupa um bit M; inteira e float ocupam um registrador do banco N (Nk e Fk sao o
mesmo registrador, lido como inteiro ou como float). Os enderecos sao distribuidos do fim
de cada area para o inicio, pulando o que o programa e a tabela de simbolos ja usam.
"""
from __future__ import annotations

import re

from ..core.asm import parse_constant, parse_float_constant
from .project import MathBox, CompareBox, Project, Variable

_BIT = re.compile(r"^M(\d+)\.(\d+)$")
_WORD = re.compile(r"^[NF](\d+)$")
_TRUE, _FALSE = {"1", "TRUE", "VERDADEIRO", "SIM", "LIGADO"}, {"", "0", "FALSE", "FALSO", "NAO", "NÃO", "DESLIGADO"}


def _used(project: Project) -> tuple[set[int], set[int]]:
    """Bits M e registradores usados por simbolos e diretamente no diagrama."""
    texts = [s.address for s in project.symbols]
    for _, node, _ in project.walk():
        if isinstance(node, (CompareBox, MathBox)):
            texts += node.operands
        elif hasattr(node, "operand"):
            texts.append(node.operand)
    bits, words = set(), set()
    for text in texts:
        t = text.strip().upper()
        if m := _BIT.match(t):
            bits.add(int(m[1]) * 8 + int(m[2]))
        elif m := _WORD.match(t):
            words.add(int(m[1]))
    return bits, words


def addresses(project: Project) -> dict[str, str]:
    """Nome da variavel -> endereco. Sem espaco na area, o endereco fica vazio."""
    bits, words = _used(project)
    next_bit, next_word = project.io.n_markers - 1, project.io.n_words - 1
    result: dict[str, str] = {}
    for v in project.variables:
        if v.type == "boolean":
            while next_bit in bits:
                next_bit -= 1
            result[v.name] = f"M{next_bit // 8}.{next_bit % 8}" if next_bit >= 0 else ""
            next_bit -= 1
        else:
            while next_word in words:
                next_word -= 1
            result[v.name] = f"{'F' if v.type == 'float' else 'N'}{next_word}" if next_word >= 0 else ""
            next_word -= 1
    return result


def initial_value(v: Variable) -> bool | int | float:
    """Valor inicial ja no tipo da variavel; ValueError com a explicacao se for invalido."""
    text = v.initial.strip()
    if v.type == "boolean":
        key = text.upper()
        if key not in _TRUE | _FALSE:
            raise ValueError(f"{v.name}: valor inicial de boolean deve ser 0 ou 1 (recebeu {text})")
        return key in _TRUE
    if v.type == "integer":
        value = parse_constant(text or "0")
        if value is None:
            raise ValueError(f"{v.name}: valor inicial inteiro inválido: {text}")
        return value
    text = (text or "0").replace(",", ".")
    number = parse_float_constant(text if re.search(r"[.eE]", text) else text + ".0")
    if number is None:
        raise ValueError(f"{v.name}: valor inicial float inválido: {text}")
    return number
