"""Ponte rolante com encoder incremental: referenciamento, contagem de posicao e aproximacao lenta."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

STATIONS = [400.0, 1200.0, 2000.0, 2800.0, 3600.0]   # mm
PITCH = 20.0                  # encoder: um ciclo a cada 20 mm (10 mm em 1, 10 mm em 0)
FAST, SLOW = 400.0, 80.0      # mm/s
ACCEL, DECEL = 400.0, 800.0   # mm/s^2 acelerando e reduzindo com o motor
BRAKE, COAST = 1500.0, 150.0  # mm/s^2 com o freio e solta (sem motor nem freio)
END_LEFT, END_RIGHT = -100.0, 3900.0   # batentes
TOLERANCE = 20.0              # parada aceita a +-20 mm da estacao
START_X = 2130.0
PX0, PX = 40.0, 0.14          # desenho: 0 mm em x = 40, 0,14 px/mm
RAIL_Y = 70.0


@register
class OverheadCraneEnvironment(Environment):
    id = "ponte_rolante"
    name = "Ponte rolante com encoder"
    description = ("A ponte liga sem saber onde está: é preciso referenciar (andar para a esquerda até a chave de "
                   "origem em 0 mm). O encoder alterna 1 e 0 a cada 10 mm, sem indicar o sentido: o programa conta as "
                   "bordas lembrando o sentido do último movimento (cada borda = 10 mm; a 400 mm/s são 25 ms entre "
                   "bordas, mais que a varredura de 10 ms). As estações 1 a 5 "
                   "ficam em 400, 1200, 2000, 2800 e 3600 mm. Em alta (400 mm/s) o freio deixa a ponte andar ~5 cm; "
                   "em baixa (80 mm/s) só ~2 mm. Para ser aceita, a parada precisa ficar a ±20 mm da estação. "
                   "Inverter com a ponte andando confunde a contagem.")
    example = "ambientes/ponte_rolante.ladproj"
    inputs = [
        IOPoint("ENCODER", "I0.0", "Encoder", "Encoder incremental (1 ciclo / 20 mm)"),
        IOPoint("HOME", "I0.1", "Origem", "Chave de origem (posição 0 mm)"),
        IOPoint("CH1", "I0.2", "Chama_1", "Botão chamar estação 1", BUTTON),
        IOPoint("CH2", "I0.3", "Chama_2", "Botão chamar estação 2", BUTTON),
        IOPoint("CH3", "I0.4", "Chama_3", "Botão chamar estação 3", BUTTON),
        IOPoint("CH4", "I0.5", "Chama_4", "Botão chamar estação 4", BUTTON),
        IOPoint("CH5", "I0.6", "Chama_5", "Botão chamar estação 5", BUTTON),
        IOPoint("EMERG", "I0.7", "Emergencia", "Emergência com trava (NF: lê 1 quando liberada)", SWITCH,
                normally_closed=True),
    ]
    outputs = [
        IOPoint("DIR", "Q0.0", "Motor_Direita", "Motor de translação: direita"),
        IOPoint("ESQ", "Q0.1", "Motor_Esquerda", "Motor de translação: esquerda"),
        IOPoint("LENTA", "Q0.2", "Velocidade_Lenta", "Velocidade baixa (aproximação)"),
        IOPoint("FREIO", "Q0.3", "Libera_Freio", "Solta o freio (sem energia o freio atua)"),
        IOPoint("POSICAO", "Q0.4", "Lampada_Em_Posicao", "Lâmpada EM POSIÇÃO"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(9)
        self.auto = getattr(self, "auto", False)
        self.x = START_X
        self.v = 0.0
        self.sway = 0.0
        self.sway_v = 0.0
        self.crash_speed = 0.0
        self.both_ms = 0
        self.drag_ms = 0
        self.dragged = False
        self.bad_stop: float | None = None
        self.moving_lamp = False
        self.emergency_moves = 0
        self.arrivals = 0
        self.last_error: float | None = None
        self._lamp = False
        self.next_auto_ms = 4000
        self._driver_press: dict[str, int] = {}

    def on_control(self, key: str, down: bool) -> None:
        if down and key == "AUTO":
            self.auto = not self.auto

    def press(self, key: str, down: bool) -> None:
        if key == "AUTO":
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _nearest(self) -> float:
        return min(abs(self.x - s) for s in [0.0, *STATIONS])

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        for key, until in list(self._driver_press.items()):
            if now >= until:
                self.operator[key] = False
                del self._driver_press[key]
        if self.auto and now >= self.next_auto_ms and abs(self.v) < 1 and out["POSICAO"]:
            key = f"CH{self.rng.randint(1, 5)}"
            self.operator[key] = True
            self.clicked.add(key)
            self._driver_press[key] = now + 300
            self.next_auto_ms = now + 8000
        right, left = out["DIR"], out["ESQ"]
        self.both_ms = self.both_ms + dt_ms if (right and left) else 0
        cmd = 0 if right == left else (1 if right else -1)
        brake_free = out["FREIO"]
        old_v = self.v
        if cmd and self.is_pressed("EMERG") and abs(self.v) > 5:
            self.emergency_moves += 1
        if cmd and not brake_free:                       # motor contra o freio
            self.drag_ms += dt_ms
            self.v = approach(self.v, 0.0, BRAKE, BRAKE, dt)
        elif cmd:
            self.drag_ms = 0
            target = cmd * (SLOW if out["LENTA"] else FAST)
            rate_up = ACCEL if abs(target) > abs(self.v) and target * self.v >= 0 else DECEL
            self.v = approach(self.v, target, rate_up, rate_up, dt)
        else:
            self.drag_ms = 0
            decel = COAST if brake_free else BRAKE
            self.v = approach(self.v, 0.0, decel, decel, dt)
        if self.drag_ms > 300:
            self.dragged = True
        self.x += self.v * dt
        for end in (END_LEFT, END_RIGHT):
            if (self.x <= END_LEFT and end == END_LEFT) or (self.x >= END_RIGHT and end == END_RIGHT):
                if abs(self.v) > 30:
                    self.crash_speed = max(self.crash_speed, abs(self.v))
                self.x, self.v = end, 0.0
        # balanco da carga (pendulo de 1,5 m, amortecido)
        accel = (self.v - old_v) / dt if dt else 0.0
        self.sway_v += (-9.81 / 1.5 * self.sway - accel / 1000 / 1.5 - 0.6 * self.sway_v) * dt
        self.sway += self.sway_v * dt
        # lampada em posicao
        lamp = out["POSICAO"]
        if lamp and not self._lamp and abs(self.v) < 5:
            error = self._nearest()
            self.last_error = error
            if error > TOLERANCE and self.bad_stop is None:
                self.bad_stop = error
            elif error <= TOLERANCE and self.x > 200:
                self.arrivals += 1
        if lamp and abs(self.v) > 50:
            self.moving_lamp = True
        self._lamp = lamp

    def sensors(self) -> dict[str, bool]:
        return {"ENCODER": (self.x % PITCH) < PITCH / 2, "HOME": self.x <= 0.0}

    def alarms(self) -> list[str]:
        out = []
        if self.crash_speed:
            out.append(f"A ponte bateu no batente a {self.crash_speed:.0f} mm/s")
        if self.both_ms > 0:
            out.append("Motor comandado para a direita e a esquerda ao mesmo tempo")
        if self.dragged:
            out.append("Motor ligado com o freio aplicado: solte o freio (Q0.3) junto com o motor")
        if self.bad_stop is not None:
            out.append(f"EM POSIÇÃO com a ponte a {self.bad_stop:.0f} mm da estação (tolerância ±20 mm)")
        if self.moving_lamp:
            out.append("Lâmpada EM POSIÇÃO acesa com a ponte andando")
        if self.emergency_moves:
            out.append("A ponte andou com a emergência acionada")
        return out

    def stats(self) -> list[str]:
        err = "-" if self.last_error is None else f"{self.last_error:.0f} mm"
        return [f"Posição real: {self.x:.0f} mm | velocidade {self.v:+.0f} mm/s",
                f"Chegadas às estações: {self.arrivals} | erro da última parada: {err}"
                + (" | Automático" if self.auto else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        c = {f"CH{k + 1}": (self._px(s) - 40, 330, 80, 28) for k, s in enumerate(STATIONS)}
        c.update({"EMERG": (16, 372, 150, 28), "AUTO": (474, 372, 150, 28)})
        return c

    def _px(self, mm: float) -> float:
        return PX0 + mm * PX

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f1f5f9"))
        # galpao: pilares, viga de rolamento e piso
        p.fillRect(QRectF(0, 300, 640, 20), QColor("#94a3b8"))
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#475569"))
        p.drawRect(QRectF(self._px(END_LEFT) - 14, RAIL_Y - 10, self._px(END_RIGHT) - self._px(END_LEFT) + 28, 10))
        for end in (END_LEFT, END_RIGHT):
            p.setBrush(QColor("#1e293b"))
            p.drawRect(QRectF(self._px(end) - (12 if end == END_LEFT else -2), RAIL_Y - 22, 10, 22))
        # estacoes no piso
        for k, s in enumerate(STATIONS):
            x = self._px(s)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#fde68a"))
            p.drawRect(QRectF(x - 24, 276, 48, 24))
            draw.text(p, x, 288, f"E{k + 1}", 8, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 40)
            draw.text(p, x, 312, f"{s:.0f} mm", 7, False, draw.MUTED, Qt.AlignHCenter | Qt.AlignVCenter, 70)
        # chave de origem
        sens = self.sensors()
        hx = self._px(0)
        p.setBrush(draw.GREEN if sens["HOME"] else QColor("#64748b"))
        p.drawRect(QRectF(hx - 4, RAIL_Y + 2, 8, 12))
        draw.tag(p, hx - 6, RAIL_Y + 26, "I0.1 origem", sens["HOME"])
        # carro da ponte, cabo e carga
        cx = self._px(self.x)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#f59e0b"))
        p.drawRoundedRect(QRectF(cx - 30, RAIL_Y - 4, 60, 24), 4, 4)
        hook = QPointF(cx + 150 * math.sin(self.sway), RAIL_Y + 20 + 150 * math.cos(self.sway))
        p.setPen(QPen(QColor("#334155"), 2))
        p.drawLine(QPointF(cx, RAIL_Y + 20), hook)
        p.setBrush(QColor("#7c3aed"))
        p.drawRect(QRectF(hook.x() - 22, hook.y(), 44, 34))
        # motor, freio, encoder
        moving = self.out.get("DIR") or self.out.get("ESQ")
        draw.text(p, cx, RAIL_Y + 8, "▶" if self.out.get("DIR") else ("◀" if self.out.get("ESQ") else "■"), 9, True,
                  draw.WHITE if moving else QColor("#78350f"), Qt.AlignHCenter | Qt.AlignVCenter, 40)
        ec = QPointF(cx + 22, RAIL_Y - 18)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawEllipse(ec, 7, 7)
        p.setBrush(draw.GREEN if sens["ENCODER"] else QColor("#475569"))
        p.drawEllipse(ec, 3, 3)
        # painel de estado
        draw.tag(p, 16, 120, "I0.0 encoder", sens["ENCODER"])
        draw.tag(p, 16, 142, "Q0.0 direita", self.out.get("DIR", False))
        draw.tag(p, 16, 164, "Q0.1 esquerda", self.out.get("ESQ", False))
        draw.tag(p, 16, 186, "Q0.2 lenta", self.out.get("LENTA", False))
        draw.tag(p, 16, 208, "Q0.3 solta freio", self.out.get("FREIO", False))
        draw.lamp(p, QPointF(560, 130), 10, self.out.get("POSICAO", False), draw.GREEN)
        draw.text(p, 498, 154, "EM POSIÇÃO Q0.4", 8, True, w=130)
        draw.text(p, 470, 190, f"{self.x:.0f} mm", 12, True, draw.INK, w=150, h=22)
        draw.text(p, 470, 210, "posição real", 7, False, draw.MUTED, w=150)
        for k, s in enumerate(STATIONS):
            draw.push_button(p, QRectF(self._px(s) - 40, 330, 80, 28), f"E{k + 1} I0.{k + 2}", self.is_pressed(f"CH{k + 1}"),
                             QColor("#2563eb"))
        draw.switch(p, QRectF(16, 372, 150, 28), "EMERGÊNCIA I0.7", self.is_pressed("EMERG"))
        draw.switch(p, QRectF(474, 372, 150, 28), "Automático", self.auto)
