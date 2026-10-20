"""Modelo de projeto independente da interface grafica.

Uma rede (Rung) e uma arvore serie/paralelo de contatos seguida de uma ou mais
saidas em paralelo. A interface manipula este modelo; o compilador, o
simulador e a transferencia trabalham a partir dele.

Formato de arquivo (.ladproj, JSON) documentado em docs/project-format.md.
"""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Union

PROJECT_FORMAT = "ladderide-project"
PROJECT_FORMAT_VERSION = 2

# Blocos de comparacao (vao na condicao, como contatos) e de matematica (vao nas
# saidas). Cada tipo tem uma lista fixa de operandos; o nome aparece no editor.
COMPARE_KINDS: dict[str, tuple[str, ...]] = {
    "EQU": ("A", "B"), "NEQ": ("A", "B"), "LES": ("A", "B"), "GRT": ("A", "B"),
    "LEQ": ("A", "B"), "GEQ": ("A", "B"),
    "LIM": ("Limite inferior", "Teste", "Limite superior"),
    "MEQ": ("Origem", "Mascara", "Comparar"),
}
MATH_KINDS: dict[str, tuple[str, ...]] = {
    "ADD": ("A", "B", "Destino"), "SUB": ("A", "B", "Destino"), "MUL": ("A", "B", "Destino"),
    "DIV": ("A", "B", "Destino"),
    "SQR": ("Origem", "Destino"), "NEG": ("Origem", "Destino"),
    "TOD": ("Origem", "Destino"), "FRD": ("Origem", "Destino"),
}
DEFAULT_OPERANDS: dict[str, list[str]] = {
    "LIM": ["0", "N0", "100"], "MEQ": ["N0", "0xFF", "0"],
    "ADD": ["N0", "1", "N0"], "SUB": ["N0", "1", "N0"], "MUL": ["N0", "2", "N1"], "DIV": ["N0", "2", "N1"],
    "SQR": ["N0", "N1"], "NEG": ["N0", "N1"], "TOD": ["N0", "N1"], "FRD": ["N0", "N1"],
}


def default_operands(kind: str) -> list[str]:
    return list(DEFAULT_OPERANDS.get(kind, ["N0", "0"]))

_ids = itertools.count(1)


def new_id() -> str:
    return f"e{next(_ids)}"


# ----------------------------------------------------------------- elementos
@dataclass(eq=False)
class Contact:
    kind: str = "XIC"            # XIC (NA) | XIO (NF)
    operand: str = "I0.0"
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class NotOp:
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class Parallel:
    branches: list[list["CondNode"]] = field(default_factory=lambda: [[], []])
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class CompareBox:
    """Comparacao (EQU, NEQ, LES, GRT, LEQ, GEQ, LIM, MEQ): conduz quando a condicao e verdadeira."""
    kind: str = "EQU"
    operands: list[str] = field(default_factory=lambda: ["N0", "0"])
    id: str = field(default_factory=new_id)


CondNode = Union[Contact, NotOp, Parallel, CompareBox]


@dataclass(eq=False)
class Coil:
    kind: str = "OTE"            # OTE | OTL (SET) | OTU (RESET)
    operand: str = "Q0.0"
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class TimerBox:
    kind: str = "TON"            # TON | TOF | RTO
    operand: str = "T0"
    preset: int = 1000           # ms
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class CounterBox:
    kind: str = "CTU"            # CTU | CTD
    operand: str = "C0"
    preset: int = 3
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class ResetBox:
    operand: str = "T0"
    id: str = field(default_factory=new_id)


@dataclass(eq=False)
class MathBox:
    """Matematica (ADD, SUB, MUL, DIV, SQR, NEG, TOD, FRD): executa quando a rede conduz."""
    kind: str = "ADD"
    operands: list[str] = field(default_factory=lambda: ["N0", "1", "N0"])
    id: str = field(default_factory=new_id)


OutputNode = Union[Coil, TimerBox, CounterBox, ResetBox, MathBox]
Node = Union[CondNode, OutputNode]


@dataclass(eq=False)
class Rung:
    condition: list[CondNode] = field(default_factory=list)
    outputs: list[OutputNode] = field(default_factory=list)
    comment: str = ""
    id: str = field(default_factory=new_id)


# ------------------------------------------------------------------ projeto
@dataclass
class Symbol:
    name: str
    address: str
    comment: str = ""


@dataclass
class IOConfig:
    n_inputs: int = 8
    n_outputs: int = 8
    n_markers: int = 64
    n_words: int = 32            # registradores N (inteiros de 32 bits)
    safe_outputs: int = 0        # bit k = estado do rele k em STOP/FAULT
    scan_period_ms: int = 10


@dataclass
class TargetConfig:
    device: str = "esp32-relay-x8"
    transport: str = "serial"    # serial | tcp
    port: str = ""
    baudrate: int = 115200
    host: str = ""
    tcp_port: int = 5020


@dataclass
class Project:
    name: str = "Novo projeto"
    description: str = ""
    version: str = "0.1.0"
    io: IOConfig = field(default_factory=IOConfig)
    target: TargetConfig = field(default_factory=TargetConfig)
    symbols: list[Symbol] = field(default_factory=list)
    rungs: list[Rung] = field(default_factory=lambda: [Rung()])
    history: list[dict] = field(default_factory=list)
    build: dict = field(default_factory=dict)
    environment: str = ""          # ambiente de simulacao associado (ladderide.envs), opcional
    created: str = field(default_factory=lambda: _now())
    modified: str = field(default_factory=lambda: _now())

    # ------------------------------------------------------------ busca
    def walk(self) -> Iterator[tuple[int, Node, list]]:
        """Percorre todos os elementos: (indice da rede, no, lista que o contem)."""
        for r_index, rung in enumerate(self.rungs):
            yield from _walk_series(r_index, rung.condition)
            for out in rung.outputs:
                yield r_index, out, rung.outputs

    def find(self, element_id: str) -> tuple[int, Node, list] | None:
        for item in self.walk():
            if item[1].id == element_id:
                return item
        return None

    def find_parent_parallel(self, element_id: str) -> tuple[Parallel, list] | None:
        """Retorna (paralelo, ramo) que contem diretamente o elemento."""
        for rung in self.rungs:
            hit = _find_parallel(rung.condition, element_id)
            if hit:
                return hit
        return None

    def rung_index_of(self, rung_id: str) -> int | None:
        for k, rung in enumerate(self.rungs):
            if rung.id == rung_id:
                return k
        return None

    def symbol_for(self, address: str) -> str | None:
        for s in self.symbols:
            if s.address.strip().upper() == address.strip().upper():
                return s.name
        return None

    # ------------------------------------------------------- persistencia
    def to_dict(self) -> dict:
        return {
            "format": PROJECT_FORMAT,
            "format_version": PROJECT_FORMAT_VERSION,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "created": self.created,
            "modified": self.modified,
            "io": vars(self.io).copy(),
            "target": vars(self.target).copy(),
            "symbols": [vars(s).copy() for s in self.symbols],
            "rungs": [_rung_to_dict(r) for r in self.rungs],
            "history": list(self.history),
            "build": dict(self.build),
            "environment": self.environment,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Project":
        data = migrate(data)
        p = cls(
            name=data.get("name", "Sem nome"),
            description=data.get("description", ""),
            version=data.get("version", "0.1.0"),
            io=IOConfig(**data.get("io", {})),
            target=TargetConfig(**data.get("target", {})),
            symbols=[Symbol(**s) for s in data.get("symbols", [])],
            rungs=[_rung_from_dict(r) for r in data.get("rungs", [])],
            history=list(data.get("history", [])),
            build=dict(data.get("build", {})),
            environment=str(data.get("environment", "")),
            created=data.get("created", _now()),
            modified=data.get("modified", _now()),
        )
        return p

    def save(self, path: str | Path, note: str = "salvo") -> None:
        self.modified = _now()
        self.history.append({"date": self.modified, "action": note, "rungs": len(self.rungs)})
        del self.history[:-50]
        Path(path).write_text(json.dumps(self.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ProjectFormatError(f"arquivo nao e JSON valido: {exc}") from None
        return cls.from_dict(data)


class ProjectFormatError(ValueError):
    pass


def migrate(data: dict) -> dict:
    """Converte arquivos de versoes anteriores para a versao atual."""
    if data.get("format") != PROJECT_FORMAT:
        raise ProjectFormatError("arquivo nao e um projeto LadderIDE")
    version = data.get("format_version")
    if not isinstance(version, int) or version < 1:
        raise ProjectFormatError(f"versao de formato invalida: {version!r}")
    if version > PROJECT_FORMAT_VERSION:
        raise ProjectFormatError(
            f"projeto criado por versao mais nova (formato {version}); atualize a IDE")
    if version == 1:            # v2: registradores N e blocos de comparacao/matematica (so adicoes)
        data = dict(data, format_version=2)
    return data


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _walk_series(r_index: int, series: list) -> Iterator[tuple[int, Node, list]]:
    for node in series:
        yield r_index, node, series
        if isinstance(node, Parallel):
            for branch in node.branches:
                yield from _walk_series(r_index, branch)


def _find_parallel(series: list, element_id: str) -> tuple[Parallel, list] | None:
    for node in series:
        if isinstance(node, Parallel):
            for branch in node.branches:
                if any(n.id == element_id for n in branch):
                    return node, branch
                hit = _find_parallel(branch, element_id)
                if hit:
                    return hit
    return None


# ------------------------------------------------------------ (de)serializacao
def node_to_dict(node: Node) -> dict:
    if isinstance(node, Contact):
        return {"type": "contact", "kind": node.kind, "operand": node.operand}
    if isinstance(node, NotOp):
        return {"type": "not"}
    if isinstance(node, Parallel):
        return {"type": "parallel", "branches": [[node_to_dict(n) for n in b] for b in node.branches]}
    if isinstance(node, Coil):
        return {"type": "coil", "kind": node.kind, "operand": node.operand}
    if isinstance(node, TimerBox):
        return {"type": "timer", "kind": node.kind, "operand": node.operand, "preset": node.preset}
    if isinstance(node, CounterBox):
        return {"type": "counter", "kind": node.kind, "operand": node.operand, "preset": node.preset}
    if isinstance(node, ResetBox):
        return {"type": "reset", "operand": node.operand}
    if isinstance(node, CompareBox):
        return {"type": "compare", "kind": node.kind, "operands": list(node.operands)}
    if isinstance(node, MathBox):
        return {"type": "math", "kind": node.kind, "operands": list(node.operands)}
    raise TypeError(node)


def node_from_dict(d: dict) -> Node:
    t = d.get("type")
    if t == "contact":
        kind = d.get("kind", "XIC")
        if kind not in ("XIC", "XIO"):
            raise ProjectFormatError(f"contato invalido: {kind}")
        return Contact(kind, str(d.get("operand", "")))
    if t == "not":
        return NotOp()
    if t == "parallel":
        return Parallel([[node_from_dict(n) for n in b] for b in d.get("branches", [])])
    if t == "coil":
        kind = d.get("kind", "OTE")
        if kind not in ("OTE", "OTL", "OTU"):
            raise ProjectFormatError(f"bobina invalida: {kind}")
        return Coil(kind, str(d.get("operand", "")))
    if t == "timer":
        kind = d.get("kind", "TON")
        if kind not in ("TON", "TOF", "RTO"):
            raise ProjectFormatError(f"temporizador invalido: {kind}")
        return TimerBox(kind, str(d.get("operand", "")), int(d.get("preset", 0)))
    if t == "counter":
        kind = d.get("kind", "CTU")
        if kind not in ("CTU", "CTD"):
            raise ProjectFormatError(f"contador invalido: {kind}")
        return CounterBox(kind, str(d.get("operand", "")), int(d.get("preset", 0)))
    if t == "reset":
        return ResetBox(str(d.get("operand", "")))
    if t in ("compare", "math"):
        kinds = COMPARE_KINDS if t == "compare" else MATH_KINDS
        kind = d.get("kind", "")
        if kind not in kinds:
            raise ProjectFormatError(f"bloco invalido: {kind}")
        operands = [str(x) for x in d.get("operands", [])]
        if len(operands) != len(kinds[kind]):
            raise ProjectFormatError(f"{kind} exige {len(kinds[kind])} operandos")
        return (CompareBox if t == "compare" else MathBox)(kind, operands)
    raise ProjectFormatError(f"tipo de elemento desconhecido: {t!r}")


def _rung_to_dict(r: Rung) -> dict:
    return {"comment": r.comment,
            "condition": [node_to_dict(n) for n in r.condition],
            "outputs": [node_to_dict(n) for n in r.outputs]}


def _rung_from_dict(d: dict) -> Rung:
    cond = [node_from_dict(n) for n in d.get("condition", [])]
    outs = [node_from_dict(n) for n in d.get("outputs", [])]
    for n in cond:
        if not isinstance(n, (Contact, NotOp, Parallel, CompareBox)):
            raise ProjectFormatError("saida dentro da condicao da rede")
    for n in outs:
        if not isinstance(n, (Coil, TimerBox, CounterBox, ResetBox, MathBox)):
            raise ProjectFormatError("contato na lista de saidas da rede")
    return Rung(cond, outs, d.get("comment", ""))
