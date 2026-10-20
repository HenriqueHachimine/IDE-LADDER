"""Painel do simulador offline."""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QFormLayout, QGridLayout, QLabel, QSizePolicy, QToolButton, QVBoxLayout,
                               QWidget)

from ..sim.simulator import SimState, Simulator
from .io_panel import IOPanel
from .speed_control import SpeedCombo, SpeedModel, SpeedSlider, format_speed


class SimPanel(QWidget):
    def __init__(self, actions: dict, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        bar = QGridLayout()                 # uma linha compacta (os mesmos comandos estao na barra e nas F5-F11)
        bar.setSpacing(2)
        for k, key in enumerate(("sim_run", "sim_pause", "sim_stop", "sim_scan", "sim_step", "sim_reset")):
            b = QToolButton()
            b.setDefaultAction(actions[key])
            b.setToolButtonStyle(Qt.ToolButtonIconOnly)
            b.setIconSize(QSize(20, 20))
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            bar.addWidget(b, 0, k)
        layout.addLayout(bar)
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.speed_model = SpeedModel(1.0, self)
        self.speed = SpeedCombo(self.speed_model)
        self.speed_slider = SpeedSlider(self.speed_model)
        self.state = QLabel("PARADO")
        self.state.setObjectName("stateBadge")
        self.scans = QLabel("0")
        self.vtime = QLabel("0,000 s")
        self.real_speed = QLabel("-")
        self.real_speed.setToolTip("Quanto o tempo simulado esta andando por segundo de relogio. Se ficar "
                                   "abaixo do pedido, o PC nao acompanha; o resultado continua o mesmo, "
                                   "so mais devagar.")
        self.pc = QLabel("-")
        form.addRow("Velocidade:", self.speed)
        form.addRow("", self.speed_slider)
        form.addRow("Estado:", self.state)
        form.addRow("Varreduras:", self.scans)
        form.addRow("Tempo simulado:", self.vtime)
        form.addRow("Velocidade real:", self.real_speed)
        form.addRow("Proxima instrucao:", self.pc)
        layout.addLayout(form)
        self.io = IOPanel(show_commanded=False)
        layout.addWidget(self.io, 1)

    def _badge(self, bg: str | None, fg: str | None) -> None:
        self.state.setStyleSheet(f"background:{bg}; color:{fg};" if bg else "")

    @property
    def speed_factor(self) -> float:
        return self.speed_model.value

    def change_speed(self, steps: int) -> None:
        self.speed_model.step(steps)

    def set_speed(self, value: float) -> None:
        self.speed_model.set(value)

    def _show_real_speed(self, sim: Simulator) -> None:
        if sim.state != SimState.RUNNING or sim.actual_speed <= 0:
            self.real_speed.setText("-")
            self.real_speed.setStyleSheet("")
            return
        text = format_speed(sim.actual_speed)
        slow = sim.limited and sim.actual_speed < 0.9 * self.speed_factor
        self.real_speed.setText(text + ("  (limite do PC)" if slow else ""))
        self.real_speed.setStyleSheet("color:#b45309;" if slow else "")

    def refresh(self, sim: Simulator | None) -> None:
        if sim is None:
            self.state.setText("sem programa compilado")
            self._badge(None, None)
            self.scans.setText("0")
            self.vtime.setText("0,000 s")
            self.real_speed.setText("-")
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
        self._show_real_speed(sim)
        if vm.in_scan and vm.pc < len(sim.program.code):
            from ..core.asm import format_operand
            from ..core.isa import Area, Op
            ins = sim.program.code[vm.pc]
            operand = "" if ins.area == Area.NONE else " " + format_operand(ins.area, ins.index,
                                                                                sim.program.constants)
            self.pc.setText(f"#{vm.pc}  {Op(ins.op).name}{operand}  (rede {sim.result.pc_rung[vm.pc]})")
        else:
            self.pc.setText("-")
        self.io.update_values(sim.effective_inputs(), sim.physical_outputs, None, sim.timer_state, sim.counter_state,
                              lambda a, i: sim.vm.read_bit(a, i) if sim.active else None,
                              lambda a, i: sim.word_value(a, i) if sim.active else None)
