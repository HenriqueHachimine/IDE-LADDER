"""Operacoes de edicao sobre o modelo (usadas pela interface e pelos testes).

Todas mantem o invariante: condicoes contem apenas contatos/NOT/paralelos e a
lista de saidas apenas bobinas, temporizadores, contadores e RES. Apos cada
operacao a arvore e normalizada (paralelos com um unico ramo sao desfeitos).
"""
from __future__ import annotations

from .project import (COMPARE_KINDS, MATH_KINDS, CompareBox, CondNode, Contact, CounterBox, MathBox, Node,
                      NotOp, OutputNode, Parallel, Project, ResetBox, Rung, TimerBox, Coil, default_operands)

COND_TYPES = (Contact, NotOp, Parallel, CompareBox)
OUTPUT_TYPES = (Coil, TimerBox, CounterBox, ResetBox, MathBox)


class EditError(ValueError):
    pass


def is_output_list(project: Project, container: list) -> bool:
    return any(container is r.outputs for r in project.rungs)


def insert(project: Project, container: list, index: int, node: Node) -> None:
    if is_output_list(project, container):
        if not isinstance(node, OUTPUT_TYPES):
            raise EditError("apenas bobinas, temporizadores, contadores, RES e blocos matematicos vao na "
                            "coluna de saidas")
    elif not isinstance(node, COND_TYPES):
        raise EditError("saidas devem ficar no fim da rede, a direita")
    container.insert(max(0, min(index, len(container))), node)
    normalize(project)


def remove(project: Project, element_id: str) -> Node:
    hit = project.find(element_id)
    if hit is None:
        raise EditError("elemento nao encontrado")
    _, node, container = hit
    container.remove(node)
    normalize(project)
    return node


def move(project: Project, element_id: str, container: list, index: int) -> None:
    hit = project.find(element_id)
    if hit is None:
        raise EditError("elemento nao encontrado")
    _, node, old = hit
    if isinstance(node, Parallel) and _contains_list(node, container):
        raise EditError("um ramo nao pode ser movido para dentro de si mesmo")
    target_is_output = is_output_list(project, container)
    if target_is_output != isinstance(node, OUTPUT_TYPES):
        raise EditError("destino incompativel com o tipo do elemento")
    old_index = old.index(node)
    if old is container and old_index < index:
        index -= 1
    old.remove(node)
    container.insert(max(0, min(index, len(container))), node)
    normalize(project)


def wrap_in_parallel(project: Project, element_id: str) -> Parallel:
    hit = project.find(element_id)
    if hit is None:
        raise EditError("elemento nao encontrado")
    _, node, container = hit
    if not isinstance(node, COND_TYPES):
        raise EditError("somente contatos e comparacoes podem receber ramo paralelo")
    par = Parallel([[node], []])
    container[container.index(node)] = par
    return par


def add_branch(project: Project, element_id: str) -> None:
    node = project.find(element_id)
    if node and isinstance(node[1], Parallel):
        node[1].branches.append([])
        return
    hit = project.find_parent_parallel(element_id)
    if hit is None:
        raise EditError("o elemento nao esta em uma ramificacao paralela")
    hit[0].branches.append([])


def remove_branch(project: Project, element_id: str) -> None:
    hit = project.find_parent_parallel(element_id)
    if hit is None:
        raise EditError("o elemento nao esta em uma ramificacao paralela")
    par, branch = hit
    par.branches.remove(branch)
    normalize(project)


def add_rung(project: Project, index: int | None = None) -> Rung:
    rung = Rung()
    project.rungs.insert(len(project.rungs) if index is None else index, rung)
    return rung


def remove_rung(project: Project, rung_index: int) -> None:
    del project.rungs[rung_index]


def normalize(project: Project) -> None:
    for rung in project.rungs:
        _normalize_series(rung.condition)


def _normalize_series(series: list[CondNode]) -> None:
    k = 0
    while k < len(series):
        node = series[k]
        if isinstance(node, Parallel):
            for branch in node.branches:
                _normalize_series(branch)
            if not node.branches:
                del series[k]
                continue
            if len(node.branches) == 1:
                series[k:k + 1] = node.branches[0]
                continue
        k += 1


def _contains_list(par: Parallel, target: list) -> bool:
    for branch in par.branches:
        if branch is target:
            return True
        for n in branch:
            if isinstance(n, Parallel) and _contains_list(n, target):
                return True
    return False


def output_node_for_tool(tool: str) -> OutputNode | None:
    if tool in MATH_KINDS:
        return MathBox(tool, default_operands(tool))
    return {
        "OTE": lambda: Coil("OTE"), "OTL": lambda: Coil("OTL"), "OTU": lambda: Coil("OTU"),
        "TON": lambda: TimerBox("TON"), "TOF": lambda: TimerBox("TOF"), "RTO": lambda: TimerBox("RTO"),
        "CTU": lambda: CounterBox("CTU"), "CTD": lambda: CounterBox("CTD"), "RES": lambda: ResetBox(),
    }.get(tool, lambda: None)()


def cond_node_for_tool(tool: str) -> CondNode | None:
    if tool in COMPARE_KINDS:
        return CompareBox(tool, default_operands(tool))
    return {
        "XIC": lambda: Contact("XIC"), "XIO": lambda: Contact("XIO"), "NOT": lambda: NotOp(),
        "PAR": lambda: Parallel(),
    }.get(tool, lambda: None)()


def next_free_element(project: Project, prefix: str) -> str:
    """Primeiro Tn/Cn ainda nao acionado por nenhuma instrucao."""
    used = set()
    for _, node, _ in project.walk():
        if isinstance(node, (TimerBox, CounterBox)):
            used.add(node.operand.strip().upper())
    for k in range(32):
        if f"{prefix}{k}" not in used:
            return f"{prefix}{k}"
    return f"{prefix}0"
