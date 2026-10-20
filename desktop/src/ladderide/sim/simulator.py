"""Simulador offline: envolve a LadderVM com estados, entradas virtuais e tempo.

O tempo e virtual: cada varredura avanca exatamente `period_ms`, e `advance()`
converte o tempo real decorrido (multiplicado pela velocidade) em varreduras.
Acelerar nao muda o resultado: o programa e o processo veem os mesmos passos
de `period_ms`, so que mais deles por segundo de relogio. Assim a simulacao e reprodutivel e identica a sequencia que o firmware
executaria com o mesmo periodo.
"""
from __future__ import annotations

import math
import time
from enum import Enum
from typing import Protocol

from ..compiler.compiler import CompileResult
from ..core.vm import LadderVM


class Plant(Protocol):
    """Processo fisico simulado ligado ao CLP (ver ladderide.envs).

    owned_inputs: mascara das entradas que o processo controla (sensores e
    botoes desenhados no ambiente); as demais continuam no painel de E/S.
    """
    @property
    def owned_inputs(self) -> int: ...
    def input_bits(self) -> int: ...
    def advance(self, dt_ms: int, outputs: int) -> None: ...
    def reset(self) -> None: ...


class SimState(Enum):
    STOPPED = "PARADO"
    RUNNING = "EXECUTANDO"
    PAUSED = "PAUSADO"


class Simulator:
    MAX_SCANS_PER_ADVANCE = 2000

    def __init__(self, result: CompileResult, period_ms: int = 10):
        if not result.ok:
            raise ValueError("programa com erros nao pode ser simulado")
        self.result = result
        self.program = result.program
        self.vm = LadderVM(self.program)
        self.period_ms = max(1, int(period_ms))
        self.state = SimState.STOPPED
        self.inputs = 0
        self.virtual_ms = 0
        self._budget = 0.0
        self.actual_speed = 0.0          # media movel do tempo simulado / tempo real
        self.limited = False             # True se o PC nao acompanhou a velocidade pedida
        self.last_error: str | None = None
        self.plant: Plant | None = None

    # ------------------------------------------------------------- processo
    def attach_plant(self, plant: Plant | None) -> None:
        self.plant = plant
        if plant is not None:
            plant.reset()

    def effective_inputs(self) -> int:
        """Entradas vistas pelo programa: painel + processo simulado."""
        if self.plant is None:
            return self.inputs
        owned = self.plant.owned_inputs
        return (self.inputs & ~owned) | (self.plant.input_bits() & owned)

    def _after_scan(self) -> None:
        if self.plant is not None:
            self.plant.advance(self.period_ms, self.vm.outputs)

    # ------------------------------------------------------------- estados
    def start(self) -> None:
        if self.state == SimState.STOPPED:
            self.vm.reset()
            self.virtual_ms = 0
            self._budget = 0.0
            if self.plant is not None:
                self.plant.reset()
        self.state = SimState.RUNNING
        self.actual_speed = 0.0
        self.limited = False

    def pause(self) -> None:
        if self.state == SimState.RUNNING:
            self.state = SimState.PAUSED

    def stop(self) -> None:
        self.state = SimState.STOPPED
        self._budget = 0.0

    def reset(self) -> None:
        """Reinicia a simulacao (partida a frio) mantendo as entradas."""
        self.vm.reset()
        self.virtual_ms = 0
        self._budget = 0.0
        if self.plant is not None:
            self.plant.reset()
        if self.state == SimState.RUNNING:
            return
        self.state = SimState.PAUSED

    # -------------------------------------------------------------- entradas
    def set_input(self, index: int, value: bool) -> None:
        if value:
            self.inputs |= 1 << index
        else:
            self.inputs &= ~(1 << index)

    def input(self, index: int) -> bool:
        return bool(self.inputs >> index & 1)

    # -------------------------------------------------------------- execucao
    def _ensure_active(self) -> None:
        if self.state == SimState.STOPPED:
            self.vm.reset()
            self.virtual_ms = 0
            self.state = SimState.PAUSED
            if self.plant is not None:
                self.plant.reset()

    def scan_once(self) -> None:
        """Executa uma varredura completa (ou termina a varredura em andamento)."""
        self._ensure_active()
        if self.vm.in_scan:
            while self.vm.step():
                pass
            self.vm.end_scan()
        else:
            self._time_step()
            self.vm.scan(self.effective_inputs(), self.period_ms)
        self._after_scan()

    def step_instruction(self) -> int | None:
        """Executa uma instrucao. Retorna o pc executado ou None se a varredura terminou."""
        self._ensure_active()
        if not self.vm.in_scan:
            self._time_step()
            self.vm.begin_scan(self.effective_inputs(), self.period_ms)
            if not self.program.code:
                self.vm.end_scan()
                self._after_scan()
                return None
        pc = self.vm.pc
        more = self.vm.step()
        if not more:
            self.vm.end_scan()
            self._after_scan()
        return pc

    def _time_step(self) -> None:
        if not self.vm.first_scan:
            self.virtual_ms += self.period_ms

    def advance(self, wall_ms: float, speed: float = 1.0, work_ms: float | None = None) -> int:
        """Converte tempo real em varreduras (modo continuo). Retorna quantas rodaram.

        speed: multiplicador do tempo (math.inf = o mais rapido que o PC conseguir).
        work_ms: limite de tempo de CPU desta chamada, para a interface nao travar;
        o atraso que nao couber e descartado (a simulacao fica mais lenta, nunca errada).
        """
        if self.state != SimState.RUNNING:
            return 0
        deadline = None if work_ms is None else time.perf_counter() + work_ms / 1000
        unlimited = math.isinf(speed)
        if not unlimited:
            self._budget += wall_ms * speed
        n = 0
        if self.vm.first_scan and not self.vm.in_scan:
            self.scan_once()
            n += 1
        cut = False
        while unlimited or self._budget >= self.period_ms:
            if n >= self.MAX_SCANS_PER_ADVANCE or (deadline is not None and n % 8 == 0
                                                   and time.perf_counter() >= deadline):
                cut = True
                break
            self.scan_once()
            if not unlimited:
                self._budget -= self.period_ms
            n += 1
        if cut:
            self._budget = 0.0
        self.limited = cut and not unlimited
        if wall_ms > 0:
            inst = n * self.period_ms / wall_ms
            self.actual_speed = inst if self.actual_speed == 0 else self.actual_speed * 0.8 + inst * 0.2
        return n

    # ------------------------------------------------------------ consulta
    @property
    def active(self) -> bool:
        return self.state != SimState.STOPPED

    @property
    def logical_outputs(self) -> int:
        return self.vm.outputs

    @property
    def physical_outputs(self) -> int:
        """O que o firmware comandaria aos reles: Q em RUN/pausa, estado seguro parado."""
        return self.vm.outputs if self.active else self.program.safe_outputs

    def element_power(self, element_id: str) -> bool:
        pc = self.result.element_pc.get(element_id)
        return pc is not None and self.vm.power[pc]

    def branch_power(self, parallel_id: str) -> bool:
        pc = self.result.branch_end_pc.get(parallel_id)
        return pc is not None and self.vm.power[pc]

    def operand_value(self, element_id: str) -> bool | None:
        ref = self.result.element_operand.get(element_id)
        return None if ref is None else self.vm.read_bit(*ref)

    def word_value(self, area: int, index: int) -> int | None:
        try:
            return self.vm.read_word(area, index)
        except (IndexError, ValueError):
            return None

    def block_values(self, element_id: str) -> list[int | None] | None:
        refs = self.result.element_words.get(element_id)
        return None if refs is None else [self.word_value(*r) for r in refs]

    def timer_state(self, index: int) -> dict | None:
        if not 0 <= index < len(self.vm.timers):
            return None
        t = self.vm.timers[index]
        return {"acc": t.acc, "bits": {"EN": t.en, "TT": t.tt, "DN": t.dn}}

    def counter_state(self, index: int) -> dict | None:
        if not 0 <= index < len(self.vm.counters):
            return None
        c = self.vm.counters[index]
        return {"acc": c.acc, "bits": {"DN": c.dn, "OV": c.ov, "UN": c.un}}

    @property
    def current_element(self) -> str | None:
        """Elemento da proxima instrucao no modo passo a passo."""
        if not self.vm.in_scan or self.vm.pc >= len(self.result.pc_element):
            return None
        return self.result.pc_element[self.vm.pc]
