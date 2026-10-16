"""Geometria do diagrama LADDER (sem Qt), em unidades de grade.

Cada contato ocupa 1x1; um paralelo ocupa a largura do maior ramo mais as
margens das juncoes; saidas ficam alinhadas em uma coluna a direita.
O layout tambem produz os "slots" onde elementos podem ser soltos e as
"chaves de energia" que a visualizacao usa para colorir fios.

Chaves de energia: ("rail",) trilho esquerdo; ("elem", id) RLO apos o
elemento; ("bnd", id) resultado OR de um paralelo; None = fio de retorno.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..model.project import Contact, NotOp, Parallel, Project, Rung

MARGIN = 0.25        # espaco entre juncao vertical e o primeiro elemento do ramo
OUT_W = 1.3          # largura de uma saida
BUS = 0.3            # barramento vertical antes das saidas
RUNG_GAP = 0.5
SLOT_W = 0.34


@dataclass
class PlacedElem:
    node: object
    rung: int
    x: float
    y: float
    w: float = 1.0
    h: float = 1.0
    in_key: tuple | None = None
    kind: str = ""


@dataclass
class Wire:
    x1: float
    y1: float
    x2: float
    y2: float
    key: tuple | None


@dataclass
class Slot:
    kind: str                  # "cond" | "out" | "newrung"
    rung: int
    container: list | None
    index: int
    rect: tuple[float, float, float, float]
    priority: int = 1

    def contains(self, x: float, y: float) -> bool:
        rx, ry, rw, rh = self.rect
        return rx <= x <= rx + rw and ry <= y <= ry + rh


@dataclass
class RungBox:
    index: int
    rung: Rung
    y: float
    h: float


@dataclass
class Layout:
    elems: list[PlacedElem] = field(default_factory=list)
    wires: list[Wire] = field(default_factory=list)
    slots: list[Slot] = field(default_factory=list)
    rungs: list[RungBox] = field(default_factory=list)
    out_x: float = 4.0
    rail_right: float = 6.0
    height: float = 1.0

    def slot_at(self, x: float, y: float, category: str) -> Slot | None:
        hits = [s for s in self.slots if s.contains(x, y) and (s.kind == category or s.kind == "newrung")]
        if not hits:
            return None
        hits.sort(key=lambda s: (-s.priority, s.rect[2] * s.rect[3]))
        return hits[0]

    def elem_by_id(self, element_id: str) -> PlacedElem | None:
        for e in self.elems:
            if e.node.id == element_id:
                return e
        return None


def measure(node) -> tuple[float, float]:
    if isinstance(node, (Contact, NotOp)):
        return 1.0, 1.0
    if isinstance(node, Parallel):
        sizes = [measure_series(b) for b in node.branches]
        return max(w for w, _ in sizes) + 2 * MARGIN, sum(h for _, h in sizes)
    raise TypeError(node)


def measure_series(nodes: list) -> tuple[float, float]:
    if not nodes:
        return 1.0, 1.0
    sizes = [measure(n) for n in nodes]
    return sum(w for w, _ in sizes), max(max(h for _, h in sizes), 1.0)


def build_layout(project: Project) -> Layout:
    lay = Layout()
    widths = [measure_series(r.condition)[0] for r in project.rungs]
    lay.out_x = max([4.0] + [w + 0.6 for w in widths])
    lay.rail_right = lay.out_x + OUT_W + 0.3
    y = 0.0
    for r_index, rung in enumerate(project.rungs):
        y = _place_rung(lay, r_index, rung, y) + RUNG_GAP
    lay.slots.append(Slot("newrung", len(project.rungs), None, 0, (-1.0, y - RUNG_GAP / 2, lay.rail_right + 1.0, 1.5), 0))
    lay.height = y + 1.0
    return lay


def _place_rung(lay: Layout, r_index: int, rung: Rung, y0: float) -> float:
    _, cond_h = measure_series(rung.condition)
    n_out = len(rung.outputs)
    h = max(cond_h, n_out, 1.0)
    lay.rungs.append(RungBox(r_index, rung, y0, h))
    # Area da rede inteira: solta no fim da condicao / fim das saidas (prioridade baixa)
    lay.slots.append(Slot("cond", r_index, rung.condition, len(rung.condition), (0.0, y0, lay.out_x - BUS, h), 0))
    lay.slots.append(Slot("out", r_index, rung.outputs, n_out, (lay.out_x - BUS, y0, OUT_W + BUS, h), 0))

    end_x, key = _place_series(lay, r_index, rung.condition, 0.0, y0, ("rail",))
    mid = y0 + 0.5
    bus_x = lay.out_x - BUS
    lay.wires.append(Wire(end_x, mid, bus_x, mid, key))
    if n_out == 0:
        lay.wires.append(Wire(bus_x, mid, lay.out_x + OUT_W, mid, key))
        lay.slots.append(Slot("out", r_index, rung.outputs, 0, (lay.out_x, y0, OUT_W, 1.0), 2))
    else:
        if n_out > 1:
            lay.wires.append(Wire(bus_x, mid, bus_x, y0 + n_out - 0.5, key))
        for k, out in enumerate(rung.outputs):
            oy = y0 + k
            lay.wires.append(Wire(bus_x, oy + 0.5, lay.out_x, oy + 0.5, key))
            lay.elems.append(PlacedElem(out, r_index, lay.out_x, oy, OUT_W, 1.0, key, type(out).__name__))
            lay.wires.append(Wire(lay.out_x + OUT_W, oy + 0.5, lay.rail_right, oy + 0.5, None))
        for k in range(n_out + 1):
            lay.slots.append(Slot("out", r_index, rung.outputs, k, (lay.out_x, y0 + k - 0.2, OUT_W, 0.4), 2))
    if n_out == 0:
        lay.wires.append(Wire(lay.out_x + OUT_W, mid, lay.rail_right, mid, None))
    return y0 + h


def _place_series(lay: Layout, r_index: int, nodes: list, x: float, y: float, key) -> tuple[float, tuple]:
    if not nodes:
        lay.wires.append(Wire(x, y + 0.5, x + 1.0, y + 0.5, key))
        lay.slots.append(Slot("cond", r_index, nodes, 0, (x, y, 1.0, 1.0), 2))
        return x + 1.0, key
    cur = x
    for i, node in enumerate(nodes):
        lay.slots.append(Slot("cond", r_index, nodes, i, (cur - SLOT_W / 2, y, SLOT_W, 1.0), 3))
        if isinstance(node, Parallel):
            w, h = measure(node)
            lay.elems.append(PlacedElem(node, r_index, cur, y, w, h, key, "Parallel"))
            by = y
            first_mid = last_mid = y + 0.5
            for branch in node.branches:
                bw, bh = measure_series(branch)
                last_mid = by + 0.5
                lay.wires.append(Wire(cur, last_mid, cur + MARGIN, last_mid, key))
                ex, bkey = _place_series(lay, r_index, branch, cur + MARGIN, by, key)
                lay.wires.append(Wire(ex, last_mid, cur + w, last_mid, bkey))
                by += bh
            lay.wires.append(Wire(cur, first_mid, cur, last_mid, key))
            lay.wires.append(Wire(cur + w, first_mid, cur + w, last_mid, ("bnd", node.id)))
            key = ("bnd", node.id)
            cur += w
        else:
            lay.elems.append(PlacedElem(node, r_index, cur, y, 1.0, 1.0, key, type(node).__name__))
            key = ("elem", node.id)
            cur += 1.0
    lay.slots.append(Slot("cond", r_index, nodes, len(nodes), (cur - SLOT_W / 2, y, SLOT_W, 1.0), 3))
    return cur, key
