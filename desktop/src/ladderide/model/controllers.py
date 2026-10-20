"""Controladores (CPU do CLP) que o projeto pode usar.

Cada controlador limita entradas, saidas e a quantidade de variaveis: memorias
M, temporizadores, contadores e registradores N. A lista vem de
shared/specifications/controllers.json e, se existir, de
~/.ladderide/controladores.json (controladores do usuario). Os limites nunca
passam dos da ISA, que e o que o firmware e as VMs suportam.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..core import isa
from .project import Project

SPEC_PATH = isa.ISA_PATH.with_name("controllers.json")
USER_PATH = Path.home() / ".ladderide" / "controladores.json"


@dataclass(frozen=True)
class Controller:
    id: str
    name: str
    description: str = ""
    inputs: int = 8
    outputs: int = 8
    markers: int = isa.MAX_MARKERS
    timers: int = isa.MAX_TIMERS
    counters: int = isa.MAX_COUNTERS
    words: int = isa.MAX_WORDS
    scan_period_ms: int = 10
    hardware: bool = False          # existe placa/firmware real para ele
    custom: bool = False            # quantidades escolhidas pelo usuario
    source: str = "padrao"

    @classmethod
    def from_dict(cls, d: dict, source: str) -> "Controller":
        def limit(key: str, maximum: int, minimum: int = 0) -> int:
            return max(minimum, min(int(d.get(key, maximum)), maximum))
        return cls(str(d["id"]), str(d.get("name", d["id"])), str(d.get("description", "")),
                   limit("inputs", isa.MAX_INPUTS, 1), limit("outputs", isa.MAX_OUTPUTS, 1),
                   limit("markers", isa.MAX_MARKERS), limit("timers", isa.MAX_TIMERS),
                   limit("counters", isa.MAX_COUNTERS), limit("words", isa.MAX_WORDS),
                   max(1, int(d.get("scan_period_ms", 10))), bool(d.get("hardware", False)),
                   bool(d.get("custom", False)), source)

    def summary(self) -> str:
        return (f"{self.inputs} entradas, {self.outputs} saidas, {self.markers} memorias M, "
                f"{self.timers} temporizadores, {self.counters} contadores, {self.words} registradores N")


def _read(path: Path, source: str) -> tuple[list[Controller], str | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("controllers", []) if isinstance(data, dict) else data
    default = data.get("default") if isinstance(data, dict) else None
    return [Controller.from_dict(d, source) for d in items], default


def load_controllers() -> list[Controller]:
    """Controladores do projeto seguidos dos do usuario (um id repetido substitui o anterior)."""
    found: dict[str, Controller] = {}
    try:
        for c in _read(SPEC_PATH, "padrao")[0]:
            found[c.id] = c
    except (OSError, ValueError, KeyError, TypeError):
        pass
    try:
        for c in _read(USER_PATH, str(USER_PATH))[0]:
            found[c.id] = c
    except (OSError, ValueError, KeyError, TypeError):
        pass                        # arquivo do usuario ausente ou invalido: ignora
    if not found:
        fallback = Controller("esp32-relay-x8", "ESP32 Relay X8 (placa do projeto)", inputs=8, outputs=8,
                              hardware=True)
        found[fallback.id] = fallback
    return list(found.values())


def default_controller() -> Controller:
    controllers = load_controllers()
    try:
        default = _read(SPEC_PATH, "padrao")[1]
    except (OSError, ValueError, KeyError, TypeError):
        default = None
    return next((c for c in controllers if c.id == default), controllers[0])


def controller_by_id(controller_id: str) -> Controller | None:
    return next((c for c in load_controllers() if c.id == controller_id), None)


def controller_for(project: Project) -> Controller | None:
    return controller_by_id(project.target.device)


def apply_controller(project: Project, ctrl: Controller, *, fill: bool = True) -> None:
    """Associa o controlador ao projeto e ajusta as quantidades aos limites dele.

    fill=True (projeto novo): usa todas as entradas/saidas do controlador.
    fill=False (troca de controlador): so reduz o que passar do limite."""
    io = project.io
    project.target.device = ctrl.id
    if fill:
        io.n_inputs, io.n_outputs = ctrl.inputs, ctrl.outputs
        io.n_markers = min(64, ctrl.markers)
        io.n_words = min(32, ctrl.words)
        io.scan_period_ms = ctrl.scan_period_ms
    else:
        io.n_inputs = min(io.n_inputs, ctrl.inputs)
        io.n_outputs = min(io.n_outputs, ctrl.outputs)
        io.n_markers = min(io.n_markers, ctrl.markers)
        io.n_words = min(io.n_words, ctrl.words)
    io.safe_outputs &= (1 << io.n_outputs) - 1
