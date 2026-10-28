"""Central de ar comprimido: dois compressores, pressostatos com diferencial, dreno e reles termicos."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import approach
from ..registry import register

K_PSI = 5.0                  # psi por unidade de ar (capacidade do reservatorio)
COMP_FLOW = 1.0              # unidades/s de cada compressor em plena rotacao
MAX_DEMAND = 1.5             # consumo da fabrica com 100% a 100 psi
LEAK = 0.01                  # vazamentos
DRAIN_FLOW = 0.6             # ar perdido pelo dreno aberto
SPIN_UP_S, SPIN_DOWN_S = 1.5, 2.0
PE1_ON, PE1_OFF = 100.0, 120.0   # pressostato 1: fecha <= 100, abre >= 120 psi
PE2_ON, PE2_OFF = 90.0, 110.0    # pressostato 2: fecha <= 90, abre >= 110 psi
SAFETY_PSI = 140.0           # valvula de seguranca
LOW_PSI = 60.0
WATER_PER_UNIT = 100 / 120   # % do coletor por unidade de ar comprimido (cheio em ~2 min de um compressor)
DRAIN_RATE = 25.0            # %/s removidos com o dreno aberto
MAX_STARTS = 6               # partidas por minuto toleradas pelo motor
COOL_S = 30.0                # rele termico rearma sozinho depois de esfriar
SIMULTANEOUS_S = 0.5         # duas partidas mais proximas que isso = pico de corrente


@register
class AirCompressorEnvironment(Environment):
    id = "compressores"
    name = "Central de ar comprimido"
    description = ("Dois compressores alimentam o reservatorio que abastece a fabrica (consumo ajustável). "
                   "Pressostato 1 (I0.2) fecha em 100 psi e abre em 120 psi; pressostato 2 (I0.3) fecha em 90 "
                   "e abre em 110. Os relés termicos (I0.4, I0.5, NF) desarmam com mais de 6 partidas por minuto "
                   "e rearmam após 30 s. Partir os dois motores juntos causa pico de corrente; a água condensada "
                   "precisa ser drenada (Q0.2), mas o dreno também perde ar. Alterne o compressor lider.")
    example = "ambientes/compressores.ladproj"
    inputs = [
        IOPoint("START", "I0.0", "Start", "Botão de partida (NA)", BUTTON),
        IOPoint("STOP", "I0.1", "Stop", "Botão de parada (NF: lê 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("PE1", "I0.2", "Pressostato_1", "Fechado abaixo de 100 psi (abre em 120 psi)"),
        IOPoint("PE2", "I0.3", "Pressostato_2", "Fechado abaixo de 90 psi (abre em 110 psi)"),
        IOPoint("TRIP1", "I0.4", "Termico_1", "Relé termico do motor 1 (NF: 1 = normal)", normally_closed=True),
        IOPoint("TRIP2", "I0.5", "Termico_2", "Relé termico do motor 2 (NF: 1 = normal)", normally_closed=True),
    ]
    outputs = [
        IOPoint("M1", "Q0.0", "Motor_1", "Contator do compressor 1"),
        IOPoint("M2", "Q0.1", "Motor_2", "Contator do compressor 2"),
        IOPoint("DRAIN", "Q0.2", "Valvula_Dreno", "Válvula solenoide de dreno do condensado"),
        IOPoint("RUN", "Q0.3", "Lampada_Run", "Lampada RUN"),
        IOPoint("FAULT", "Q0.4", "Lampada_Falha", "Lampada de falha (termico desarmado)"),
    ]

    def reset(self) -> None:
        self.psi = 0.0
        self.demand = 0.4
        self.speed = [0.0, 0.0]
        self.angle = [0.0, 0.0]
        self.pe = [True, True]
        self.water = 10.0
        self.starts: list[list[int]] = [[], []]          # instantes de partida (ms)
        self.run_ms = [0, 0]
        self.tripped = [False, False]
        self.forced = [False, False]                   # falha simulada pelo usuario
        self.trip_count = [0, 0]
        self.cool_ms = [0, 0]
        self.was_on = [False, False]
        self.simultaneous = 0
        self.safety_opened = 0
        self.low_events = 0
        self.water_alarm = False
        self.reached = False
        self._safety = False
        self._low = False

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "DEMAND_UP":
            self.demand = min(1.0, round(self.demand + 0.1, 2))
        elif key == "DEMAND_DOWN":
            self.demand = max(0.0, round(self.demand - 0.1, 2))
        elif key in ("FAULT1", "FAULT2"):
            k = int(key[-1]) - 1
            self.forced[k] = not self.forced[k]

    def press(self, key: str, down: bool) -> None:
        if key in ("DEMAND_UP", "DEMAND_DOWN", "FAULT1", "FAULT2"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        cmd = [out["M1"], out["M2"]]
        q_in = 0.0
        for k in range(2):
            powered = cmd[k] and not self.tripped[k] and not self.forced[k]
            if powered and not self.was_on[k]:
                self.starts[k].append(self.time_ms)
                other = self.starts[1 - k]
                if other and self.time_ms - other[-1] < SIMULTANEOUS_S * 1000:
                    self.simultaneous += 1
            self.was_on[k] = powered
            self.starts[k] = [t for t in self.starts[k] if self.time_ms - t < 60000]
            if len(self.starts[k]) > MAX_STARTS and not self.tripped[k]:
                self.tripped[k] = True                 # aquecimento por partidas sucessivas
                self.trip_count[k] += 1
                self.cool_ms[k] = 0
            if self.tripped[k] and not powered:
                self.cool_ms[k] += dt_ms
                if self.cool_ms[k] >= COOL_S * 1000:
                    self.tripped[k] = False
                    self.starts[k].clear()
            self.speed[k] = approach(self.speed[k], 1.0 if powered else 0.0, 1 / SPIN_UP_S, 1 / SPIN_DOWN_S, dt)
            self.angle[k] += self.speed[k] * 12 * dt
            if powered:
                self.run_ms[k] += dt_ms
            q_in += COMP_FLOW * self.speed[k]
        orifice = math.sqrt(max(0.0, self.psi) / 100.0)
        q_out = (self.demand * MAX_DEMAND + LEAK + (DRAIN_FLOW if out["DRAIN"] else 0.0)) * orifice
        self.psi = max(0.0, self.psi + K_PSI * (q_in - q_out) * dt)
        safety = self.psi >= SAFETY_PSI
        if safety:
            self.psi = SAFETY_PSI
            if not self._safety:
                self.safety_opened += 1
        self._safety = safety
        if self.psi >= PE1_ON:
            self.reached = True
        low = self.reached and self.psi < LOW_PSI and self.demand > 0
        if low and not self._low:
            self.low_events += 1
        self._low = low
        # pressostatos com diferencial (histerese mecanica)
        for k, (on, off) in enumerate(((PE1_ON, PE1_OFF), (PE2_ON, PE2_OFF))):
            if self.psi <= on:
                self.pe[k] = True
            elif self.psi >= off:
                self.pe[k] = False
        self.water = min(120.0, self.water + WATER_PER_UNIT * q_in * dt)
        if out["DRAIN"]:
            self.water = max(0.0, self.water - DRAIN_RATE * dt)
        if self.water >= 100:
            self.water_alarm = True

    def sensors(self) -> dict[str, bool]:
        return {"PE1": self.pe[0], "PE2": self.pe[1],
                "TRIP1": self.tripped[0] or self.forced[0], "TRIP2": self.tripped[1] or self.forced[1]}

    def alarms(self) -> list[str]:
        out = []
        if self.simultaneous:
            out.append(f"{self.simultaneous} partida(s) simultanea(s) dos dois motores: pico de corrente "
                       f"(escalone as partidas)")
        for k in range(2):
            if self.trip_count[k]:
                out.append(f"Motor {k + 1} desarmou por excesso de partidas ({self.trip_count[k]}x)")
        if self.safety_opened:
            out.append("A válvula de seguranca abriu (140 psi): compressor ligado sem controle de pressão")
        if self.low_events:
            out.append("Pressão abaixo de 60 psi: a fabrica ficou sem ar")
        if self.water_alarm:
            out.append("Reservatorio cheio de condensado: acione o dreno periodicamente")
        return out

    def stats(self) -> list[str]:
        return [f"Pressão: {self.psi:.1f} psi | consumo {self.demand * 100:.0f}% | condensado {self.water:.0f}%",
                f"Motor 1: {len(self.starts[0])} partidas/min, {self.run_ms[0] / 1000:.0f} s ligado | "
                f"Motor 2: {len(self.starts[1])} partidas/min, {self.run_ms[1] / 1000:.0f} s ligado"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"START": (22, 150, 120, 28), "STOP": (22, 184, 120, 28),
                "DEMAND_DOWN": (296, 372, 30, 26), "DEMAND_UP": (424, 372, 30, 26),
                "FAULT1": (170, 372, 100, 26), "FAULT2": (460, 372, 100, 26)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        out, sens = self.out, self.sensors()
        p.fillRect(QRectF(0, 0, 640, 300), QColor("#f1ede8"))
        p.setPen(QPen(QColor("#e2d9cf"), 1))
        for y in range(12, 300, 18):                 # parede de tijolos
            off = 0 if (y // 18) % 2 else 22
            for x in range(-off, 640, 44):
                p.drawRect(QRectF(x, y, 44, 18))
        p.fillRect(QRectF(0, 300, 640, 120), QColor("#9ca3af"))
        # reservatorio
        tank = QRectF(180, 200, 380, 110)
        grad = QLinearGradient(0, tank.top(), 0, tank.bottom())
        grad.setColorAt(0, QColor("#e5e7eb"))
        grad.setColorAt(0.5, QColor("#f9fafb"))
        grad.setColorAt(1, QColor("#9ca3af"))
        p.setPen(QPen(QColor("#4b5563"), 1.5))
        p.setBrush(grad)
        p.drawRoundedRect(tank, 55, 55)
        water_h = min(1.0, self.water / 100) * 30
        p.fillRect(QRectF(tank.left() + 50, tank.bottom() - 6 - water_h, tank.width() - 100, water_h),
                   QColor(59, 130, 246, 120))
        draw.text(p, tank.center().x(), tank.top() + 22, f"{self.psi:5.1f} psi", 13, True, draw.INK,
                  Qt.AlignHCenter | Qt.AlignVCenter, 160, 24)
        self._gauge(p, QPointF(tank.center().x(), tank.top() + 62), 26)
        # compressores sobre o reservatorio
        for k, cx in enumerate((270, 470)):
            self._compressor(p, QPointF(cx, 150), k, out[f"M{k + 1}"])
        # pressostatos
        for k, (x, addr, txt) in enumerate(((178, "I0.2", "PE1 100/120"), (562, "I0.3", "PE2 90/110"))):
            box = QRectF(x - 22 if k == 0 else x - 6, 230, 28, 22)
            p.setPen(QPen(QColor("#1e3a8a"), 1))
            p.setBrush(QColor("#93c5fd"))
            p.drawRect(box)
            draw.text(p, box.center().x(), box.center().y(), f"PE{k + 1}", 7, True, draw.INK,
                      Qt.AlignHCenter | Qt.AlignVCenter, 28)
            tx = box.left() - 40 if k == 0 else 640 - 112
            draw.tag(p, tx, box.bottom() + 14, f"{addr} {txt}", sens[f"PE{k + 1}"])
        # dreno
        dv = QPointF(tank.center().x() + 120, tank.bottom() + 6)
        p.setPen(QPen(QColor("#374151"), 1))
        p.setBrush(QColor("#2563eb") if out["DRAIN"] else QColor("#6b7280"))
        p.drawRect(QRectF(dv.x() - 8, dv.y(), 16, 12))
        if out["DRAIN"]:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(59, 130, 246, 180))
            for j in range(3):
                p.drawEllipse(QPointF(dv.x(), dv.y() + 20 + j * 10 + (self.time_ms / 40) % 10), 2.5, 3.5)
        draw.tag(p, dv.x() + 14, dv.y() + 8, f"Q0.2 dreno | água {self.water:.0f}%", out["DRAIN"])
        # consumo e falhas simuladas
        draw.text(p, 375, 385, f"consumo {self.demand * 100:.0f}%", 8, True, draw.INK,
                  Qt.AlignHCenter | Qt.AlignVCenter, 96)
        for key, r in self.controls().items():
            if key.startswith("DEMAND"):
                rect = QRectF(*r)
                p.setPen(QPen(QColor("#334155"), 1))
                p.setBrush(QColor("#e2e8f0"))
                p.drawRoundedRect(rect, 4, 4)
                draw.text(p, rect.center().x(), rect.center().y(), "-" if key.endswith("DOWN") else "+", 12,
                          True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 30)
        draw.switch(p, QRectF(*self.controls()["FAULT1"]), "falha M1", self.forced[0])
        draw.switch(p, QRectF(*self.controls()["FAULT2"]), "falha M2", self.forced[1])
        # painel
        draw.panel(p, QRectF(12, 20, 140, 230), "AR COMPRIMIDO")
        for k, (key, label, color, addr) in enumerate((("RUN", "RUN", draw.GREEN, "Q0.3"),
                                                      ("FAULT", "FALHA", draw.RED, "Q0.4"))):
            yy = 50 + k * 34
            draw.lamp(p, QPointF(32, yy), 10, out[key], color)
            draw.text(p, 48, yy - 6, label, 7.5, True)
            draw.tag(p, 48, yy + 8, addr, out[key])
        draw.push_button(p, QRectF(22, 150, 120, 28), "START I0.0", self.is_pressed("START"), draw.GREEN)
        draw.push_button(p, QRectF(22, 184, 120, 28), "STOP I0.1 (NF)", self.is_pressed("STOP"), draw.RED)
        draw.text(p, 22, 228, "Termicos: I0.4 / I0.5", 7, False, draw.MUTED)

    def _gauge(self, p: QPainter, c: QPointF, r: float) -> None:
        p.setPen(QPen(QColor("#1f2937"), 1.5))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(c, r, r)
        p.setPen(QPen(draw.RED, 3))
        for lo, hi in ((SAFETY_PSI - 10, 160),):
            a0 = 225 - lo / 160 * 270
            p.drawArc(QRectF(c.x() - r + 4, c.y() - r + 4, 2 * r - 8, 2 * r - 8), int((a0 - (hi - lo) / 160 * 270) * 16),
                      int((hi - lo) / 160 * 270 * 16))
        ang = math.radians(225 - min(160.0, self.psi) / 160 * 270)
        p.setPen(QPen(QColor("#111827"), 2))
        p.drawLine(c, QPointF(c.x() + math.cos(ang) * (r - 6), c.y() - math.sin(ang) * (r - 6)))

    def _compressor(self, p: QPainter, c: QPointF, k: int, cmd: bool) -> None:
        tripped = self.tripped[k] or self.forced[k]
        body = QRectF(c.x() - 62, c.y() - 34, 124, 60)
        p.setPen(QPen(QColor("#78350f"), 1.2))
        p.setBrush(QColor("#f59e0b") if not tripped else QColor("#9ca3af"))
        p.drawRoundedRect(body, 10, 10)
        for j in range(5):                              # aletas do cilindro
            p.drawLine(QPointF(body.left() + 54, body.top() + 8 + j * 9), QPointF(body.right() - 8, body.top() + 8 + j * 9))
        wheel = QPointF(body.left() + 26, body.center().y())
        p.setBrush(QColor("#374151"))
        p.drawEllipse(wheel, 22, 22)
        p.setPen(QPen(QColor("#d1d5db"), 3))
        for j in range(4):
            a = self.angle[k] + j * math.pi / 2
            p.drawLine(wheel, QPointF(wheel.x() + math.cos(a) * 18, wheel.y() + math.sin(a) * 18))
        draw.text(p, c.x(), body.top() - 22, f"MOTOR {k + 1}", 8, True, draw.INK,
                  Qt.AlignHCenter | Qt.AlignVCenter, 120)
        draw.tag(p, c.x() - 30, body.top() - 8, f"Q0.{k}", cmd)
        trip_addr = f"I0.{4 + k}"
        draw.tag(p, c.x() + 4, body.top() - 8, f"{trip_addr} {'DESARMADO' if tripped else 'termico ok'}",
                 not tripped)
