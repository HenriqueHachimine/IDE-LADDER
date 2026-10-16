"""Adaptador do instantaneo do dispositivo para a interface LiveSource da view.

So e usado quando o build_id do dispositivo e igual ao do projeto compilado;
caso contrario os indices de instrucao nao correspondem ao diagrama.
"""
from __future__ import annotations

from ..compiler.compiler import CompileResult
from ..core.isa import Area
from .snapshot import Snapshot


class MonitorSource:
    def __init__(self, snapshot: Snapshot, result: CompileResult):
        self.s = snapshot
        self.r = result

    def element_power(self, element_id: str) -> bool:
        pc = self.r.element_pc.get(element_id)
        return pc is not None and pc < len(self.s.power) and self.s.power[pc]

    def branch_power(self, parallel_id: str) -> bool:
        pc = self.r.branch_end_pc.get(parallel_id)
        return pc is not None and pc < len(self.s.power) and self.s.power[pc]

    def read_bit(self, area: int, index: int) -> bool | None:
        s = self.s
        if area == Area.I:
            return bool(s.inputs >> index & 1)
        if area == Area.Q:
            return bool(s.q_logical >> index & 1)
        if area == Area.M:
            return s.markers[index] if index < len(s.markers) else None
        if area in (Area.T_EN, Area.T_TT, Area.T_DN) and index < len(s.timers):
            t = s.timers[index]
            return {Area.T_EN: t.en, Area.T_TT: t.tt, Area.T_DN: t.dn}[area]
        if area in (Area.C_DN, Area.C_OV, Area.C_UN) and index < len(s.counters):
            c = s.counters[index]
            return {Area.C_DN: c.dn, Area.C_OV: c.ov, Area.C_UN: c.un}[area]
        return None  # bits de sistema nao sao transmitidos

    def operand_value(self, element_id: str) -> bool | None:
        ref = self.r.element_operand.get(element_id)
        return None if ref is None else self.read_bit(*ref)

    def timer_state(self, index: int) -> dict | None:
        if not 0 <= index < len(self.s.timers):
            return None
        t = self.s.timers[index]
        return {"acc": t.acc, "bits": {"EN": t.en, "TT": t.tt, "DN": t.dn}}

    def counter_state(self, index: int) -> dict | None:
        if not 0 <= index < len(self.s.counters):
            return None
        c = self.s.counters[index]
        return {"acc": c.acc, "bits": {"DN": c.dn, "OV": c.ov, "UN": c.un}}

    @property
    def current_element(self) -> str | None:
        return None
