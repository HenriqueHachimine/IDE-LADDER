"""Painel do simulador offline."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QComboBox, QFormLayout, QGridLayout, QLabel, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from ..sim.simulator import SimState, Simulator
from .io_panel import IOPanel

SPEEDS = [("0,1x", 0.1), ("0,25x", 0.25), ("0,5x", 0.5), ("1x (tempo real)", 1.0), ("2x", 2.0),
          ("5x", 5.0), ("10x", 10.0)]


class SimPanel(QWidget):
    def __init__(self, actions: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        bar = QGridLayout()
        bar.setSpacing(4)
        for k, key in enumerate(("sim_run", "sim_pause", "sim_stop", "sim_scan", "sim_step", "sim_reset")):
            b = QToolButton()
            b.setDefaultAction(actions[key])
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setIconSize(QSize(18, 18))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            bar.addWidget(b, k // 3, k % 3)
        layout.addLayout(bar)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.speed = QComboBox()
        for text, value in SPEEDS:
            self.speed.addItem(text, value)
        self.speed.setCurrentIndex(3)
        self.state = QLabel("PARADO")
        self.state.setObjectName("stateBadge")
        self.scans = QLabel("0")
        self.vtime = QLabel("0,000 s")
        self.pc = QLabel("-")
        form.addRow("Velocidade:", self.speed)
        form.addRow("Estado:", self.state)
        form.addRow("Varreduras:", self.scans)
        form.addRow("Tempo simulado:", self.vtime)
        form.addRow("Proxima instrucao:", self.pc)
        layout.addLayout(form)
        self.io = IOPanel(show_commanded=False)
        layout.addWidget(self.io, 1)

    def _badge(self, bg: str | None, fg: str | None) -> None:
        self.state.setStyleSheet(f"background:{bg}; color:{fg};" if bg else "")

    @property
    def speed_factor(self) -> float:
        return float(self.speed.currentData())

    def refresh(self, sim: Simulator | None) -> None:
        if sim is None:
            self.state.setText("sem programa compilado")
            self._badge(None, None)
            self.scans.setText("0")
            self.vtime.setText("0,000 s")
            self.pc.setText("-")
            self.io.update_values(None, None, None, lambda i: None, lambda i: None, lambda a, i: None)
            return
        vm = sim.vm
        text = sim.state.value
        if sim.state != SimState.STOPPED and vm.in_scan:
            text += " (no meio da varredura)"
        self.state.setText(text)
        self._badge(*{SimState.RUNNING: ("#dcfce7", "#166534"), SimState.PAUSED: ("#fef3c7", "#92400e")}
                    .get(sim.state, (None, None)))
        self.scans.setText(str(vm.scan_count))
        self.vtime.setText(f"{sim.virtual_ms / 1000:.3f} s".replace(".", ","))
        if vm.in_scan and vm.pc < len(sim.program.code):
            from ..core.asm import format_operand
            from ..core.isa import Area, Op
            ins = sim.program.code[vm.pc]
            operand = "" if ins.area == Area.NONE else " " + format_operand(ins.area, ins.index)
            self.pc.setText(f"#{vm.pc}  {Op(ins.op).name}{operand}  (rede {sim.result.pc_rung[vm.pc]})")
        else:
            self.pc.setText("-")
        self.io.update_values(sim.effective_inputs(), sim.physical_outputs, None, sim.timer_state, sim.counter_state,
                              lambda a, i: sim.vm.read_bit(a, i) if sim.active else None)
