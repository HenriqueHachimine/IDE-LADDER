"""Modulos de expansao de E/S dos CLPs reais (WEG CLIC-02 e Omron CP1E).

O projeto guarda os modulos em `target.expansions` (ids, na ordem em que estao
encaixados no CLP). As E/S do projeto passam a ser as do CPU mais as dos modulos:
no programa, as entradas dos modulos vem depois das do CPU (I), e as saidas
depois das do CPU (Q), na ordem dos modulos.

WEG CLIC-02 (manual 10009280784, cap. 7.1 e 11): ate 3 modulos digitais de 4
entradas e 4 saidas (CLW-02/8ER-A, 8ER-D, 8ET-D, 8ER-24A). No CLIC-02 as entradas
dos modulos sao X01..X0C e as saidas Y01..Y0C, em grupos de 4 por modulo.

Omron CP1E (manual W480, secoes 6-1-3 e 6-1-4): ate 3 unidades CP1W nos CPUs de
30 e 40 pontos e no NA20; os de 10, 14 e 20 pontos nao aceitam expansao. Cada
unidade recebe os canais seguintes aos do CPU (CIO m para entradas, 12 bits por
canal; CIO n para saidas, 8 bits por canal); unidade sem entradas (ou sem saidas)
nao gasta canal de entrada (ou de saida).
"""
from __future__ import annotations

from dataclasses import dataclass

from ..core import isa


@dataclass(frozen=True)
class Expansion:
    id: str
    catalog: str
    bus: str              # clic02 | cp1w (o mesmo de Controller.expansion_bus)
    inputs: int
    outputs: int
    spec: str

    @property
    def label(self) -> str:
        io = " + ".join(t for t in (f"{self.inputs}E" if self.inputs else "",
                                    f"{self.outputs}S" if self.outputs else "") if t)
        return f"{self.catalog}  ({io}, {self.spec})"


def _clic(cat: str, spec: str) -> Expansion:
    return Expansion(cat.lower().replace("/", "-"), cat, "clic02", 4, 4, spec)


def _cp1w(cat: str, n_in: int, n_out: int, spec: str) -> Expansion:
    return Expansion(cat.lower(), cat, "cp1w", n_in, n_out, spec)


CATALOG: list[Expansion] = [
    _clic("CLW-02/8ER-D", "24 Vcc, saídas a relé"),
    _clic("CLW-02/8ET-D", "24 Vcc, saídas a transistor"),
    _clic("CLW-02/8ER-A", "100-240 Vca, saídas a relé"),
    _clic("CLW-02/8ER-24A", "24 Vca, saídas a relé"),
    _cp1w("CP1W-8ED", 8, 0, "entradas 24 Vcc"),
    _cp1w("CP1W-8ER", 0, 8, "saídas a relé"),
    _cp1w("CP1W-8ET", 0, 8, "saídas a transistor NPN"),
    _cp1w("CP1W-8ET1", 0, 8, "saídas a transistor PNP"),
    _cp1w("CP1W-16ER", 0, 16, "saídas a relé"),
    _cp1w("CP1W-16ET", 0, 16, "saídas a transistor NPN"),
    _cp1w("CP1W-16ET1", 0, 16, "saídas a transistor PNP"),
    _cp1w("CP1W-20EDR1", 12, 8, "saídas a relé"),
    _cp1w("CP1W-20EDT", 12, 8, "saídas a transistor NPN"),
    _cp1w("CP1W-20EDT1", 12, 8, "saídas a transistor PNP"),
    _cp1w("CP1W-32ER", 0, 32, "saídas a relé"),
    _cp1w("CP1W-32ET", 0, 32, "saídas a transistor NPN"),
    _cp1w("CP1W-32ET1", 0, 32, "saídas a transistor PNP"),
    _cp1w("CP1W-40EDR", 24, 16, "saídas a relé"),
    _cp1w("CP1W-40EDT", 24, 16, "saídas a transistor NPN"),
    _cp1w("CP1W-40EDT1", 24, 16, "saídas a transistor PNP"),
]
BY_ID = {e.id: e for e in CATALOG}


def compatible(ctrl) -> list[Expansion]:
    """Modulos que encaixam no controlador (vazio se ele nao aceita expansao)."""
    if ctrl is None or not getattr(ctrl, "max_expansions", 0):
        return []
    return [e for e in CATALOG if e.bus == ctrl.expansion_bus]


def total_io(ctrl, modules: list[Expansion]) -> tuple[int, int]:
    return (ctrl.inputs + sum(m.inputs for m in modules), ctrl.outputs + sum(m.outputs for m in modules))


def problems(ctrl, modules: list[Expansion]) -> list[str]:
    """Por que a combinacao CPU + modulos nao vale (lista vazia = vale)."""
    if not modules:
        return []
    if ctrl is None or not getattr(ctrl, "max_expansions", 0):
        name = ctrl.label if ctrl is not None else "este controlador"
        return [f"{name} não aceita módulos de expansão"]
    errors = []
    if len(modules) > ctrl.max_expansions:
        errors.append(f"{ctrl.label} aceita no máximo {ctrl.max_expansions} módulos")
    wrong = [m.catalog for m in modules if m.bus != ctrl.expansion_bus]
    if wrong:
        errors.append(f"{', '.join(wrong)} não encaixa no {ctrl.label}")
    n_in, n_out = total_io(ctrl, modules)
    if n_in > isa.IDE_MAX_INPUTS:
        errors.append(f"{n_in} entradas passam do limite da IDE ({isa.IDE_MAX_INPUTS})")
    if n_out > isa.IDE_MAX_OUTPUTS:
        errors.append(f"{n_out} saídas passam do limite da IDE ({isa.IDE_MAX_OUTPUTS})")
    return errors


def valid_modules(ctrl, ids: list[str]) -> list[Expansion]:
    """Os modulos de `ids` que cabem no controlador, na ordem (para quando o controlador muda)."""
    kept: list[Expansion] = []
    for i in ids:
        m = BY_ID.get(i)
        if m is not None and not problems(ctrl, kept + [m]):
            kept.append(m)
    return kept


def project_modules(project) -> list[Expansion]:
    return [BY_ID[i] for i in getattr(project.target, "expansions", []) if i in BY_ID]


def _cio_range(word: int, count: int, per: int) -> str:
    last = count - 1
    return f"CIO {word}.00 a {word + last // per}.{last % per:02d}"


def addresses(ctrl, modules: list[Expansion]) -> list[dict]:
    """Enderecos de cada modulo: na IDE (indices das entradas/saidas do projeto) e no CLP.

    Cada item: {"module", "in_first", "out_first", "plc_in", "plc_out"} (in_first/out_first = indice
    da primeira entrada/saida do modulo no projeto; plc_* = texto como aparece no CLP)."""
    rows = []
    k_in, k_out = ctrl.inputs, ctrl.outputs
    word_in = -(-ctrl.inputs // 12)                 # CP1E: canal seguinte aos do CPU
    word_out = 100 + -(-ctrl.outputs // 8)
    x = y = 0                                       # CLIC-02: X01.. e Y01..
    for m in modules:
        if m.bus == "clic02":
            plc_in = f"X{x + 1:02X} a X{x + m.inputs:02X}" if m.inputs else ""
            plc_out = f"Y{y + 1:02X} a Y{y + m.outputs:02X}" if m.outputs else ""
            x, y = x + m.inputs, y + m.outputs
        else:
            plc_in = _cio_range(word_in, m.inputs, 12) if m.inputs else ""
            plc_out = _cio_range(word_out, m.outputs, 8) if m.outputs else ""
            word_in += -(-m.inputs // 12)
            word_out += -(-m.outputs // 8)
        rows.append({"module": m, "in_first": k_in, "out_first": k_out, "plc_in": plc_in, "plc_out": plc_out})
        k_in, k_out = k_in + m.inputs, k_out + m.outputs
    return rows
