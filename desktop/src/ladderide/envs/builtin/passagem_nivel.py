"""Passagem de nivel ferroviaria: trens nos dois sentidos, luzes alternadas, sino e cancela."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import Environment, IOPoint
from ..physics import IDM
from ..registry import register

TRAIN_SPEED = 22.0          # m/s (~80 km/h): do sensor de aproximacao ate a passagem em ~18 s
TRAIN_LEN = 120.0           # m
SENSOR_AT = 400.0           # sensores de aproximacao a 400 m de cada lado
ISLAND = 15.0               # sensor de ilha: +-15 m em volta da passagem
GATE_S = 6.0                # a cancela leva 6 s para descer ou subir
WARN_BEFORE_GATE_MS = 3000  # luzes piscando ao menos 3 s antes de a cancela descer
STOP_LINE, GATE_Y = 14.0, 9.0   # posicoes na rodovia (m antes dos trilhos)
CROSS_HALF = 5.0            # largura da faixa dos trilhos (m para cada lado)
CAR_LEN = 4.5
AUTO_FIRST_MS, AUTO_EVERY_MS = 8000, 45000
X_SCALE, Y_SCALE = 0.6, 1.4     # px por metro no desenho
TRACK_Y, ROAD_X = 190.0, 320.0


@dataclass
class Car:
    y: float                 # frente do carro (m ate os trilhos; diminui ao avancar)
    v: float
    color: str
    stopped_ms: int = 0


@register
class LevelCrossingEnvironment(Environment):
    id = "passagem_nivel"
    name = "Passagem de nível ferroviária"
    description = ("Trens chegam pelos dois lados a 80 km/h. O sensor de aproximação do lado de onde o trem vem "
                   "atua ~18 s antes da passagem; o do outro lado atua quando ele vai embora e deve ser ignorado. "
                   "As luzes piscam alternadas, o sino toca e, depois de 3 s de aviso, a cancela desce (6 s). "
                   "Os carros param diante das luzes; a cancela só sobe quando o trem deixa o sensor de ilha. "
                   "Os botões chamam trens; 'Automático' manda um trem a cada 45 s.")
    example = "ambientes/passagem_nivel.ladproj"
    inputs = [
        IOPoint("SW", "I0.0", "Sensor_Oeste", "Aproximação pelo oeste (400 m)"),
        IOPoint("SI", "I0.1", "Sensor_Ilha", "Trem sobre a passagem (+-15 m)"),
        IOPoint("SE", "I0.2", "Sensor_Leste", "Aproximação pelo leste (400 m)"),
        IOPoint("DOWN", "I0.3", "Cancela_Abaixada", "Fim de curso: cancela abaixada"),
        IOPoint("UP", "I0.4", "Cancela_Levantada", "Fim de curso: cancela levantada"),
    ]
    outputs = [
        IOPoint("LUZ_E", "Q0.0", "Luz_Esquerda", "Luz vermelha esquerda"),
        IOPoint("LUZ_D", "Q0.1", "Luz_Direita", "Luz vermelha direita"),
        IOPoint("SINO", "Q0.2", "Sino", "Sino de alerta"),
        IOPoint("ABAIXA", "Q0.3", "Cancela_Abaixa", "Motor da cancela: abaixar"),
        IOPoint("LEVANTA", "Q0.4", "Cancela_Levanta", "Motor da cancela: levantar"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(7)
        self.auto = getattr(self, "auto", True)
        self.train_x: float | None = None     # frente do trem (m; 0 = passagem)
        self.train_dir = 1
        self.next_auto_ms = AUTO_FIRST_MS
        self.auto_dir = 1
        self.gate = 0.0                        # 0 = levantada, 1 = abaixada
        self.cars: list[Car] = []
        self.next_car_ms = 1500
        self.idm = IDM(v0=12.0, a=2.0, b=3.0, s0=2.0, T=1.0)
        self.light_on_ms = {"LUZ_E": 0, "LUZ_D": 0}
        self.both_lights_ms = 0
        self.last_light_ms = -10**9
        self.warn_start_ms: int | None = None
        self.gate_started_ms: int | None = None
        self.gate_down_ms: int | None = None
        self._arrived = False
        self.trains = 0
        self.cars_crossed = 0
        self.max_wait_ms = 0
        self.margin_s: float | None = None
        self.no_train_ms = 0
        self.collision = False
        self.open_arrivals = 0
        self.early_gate = 0
        self.gate_hit_car = False
        self.raised_on_train = False
        self.both_motor_ms = 0
        self.not_flashing = False

    # ---------------------------------------------------------- operador
    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.auto = not self.auto
        elif key in ("TREM_O", "TREM_L") and self.train_x is None:
            self._spawn_train(1 if key == "TREM_O" else -1)

    def press(self, key: str, down: bool) -> None:
        if key in ("AUTO", "TREM_O", "TREM_L"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _spawn_train(self, direction: int) -> None:
        self.train_dir = direction
        self.train_x = -direction * (SENSOR_AT + 120.0)
        self._arrived = False

    # ------------------------------------------------------------- fisica
    def _train_span(self) -> tuple[float, float] | None:
        if self.train_x is None:
            return None
        rear = self.train_x - self.train_dir * TRAIN_LEN
        return min(rear, self.train_x), max(rear, self.train_x)

    def _covers(self, a: float, b: float) -> bool:
        span = self._train_span()
        return span is not None and span[0] <= b and span[1] >= a

    @property
    def warning(self) -> bool:
        return self.time_ms - self.last_light_ms <= 1200

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        # trens
        if self.auto and self.train_x is None and now >= self.next_auto_ms:
            self._spawn_train(self.auto_dir)
            self.auto_dir = -self.auto_dir
            self.next_auto_ms = now + AUTO_EVERY_MS
        if self.train_x is not None:
            self.train_x += self.train_dir * TRAIN_SPEED * dt
            if not self._arrived and self._covers(-ISLAND, ISLAND):
                self._arrived = True
                self.trains += 1
                if self.gate < 0.98:
                    self.open_arrivals += 1
                self.margin_s = None if self.gate_down_ms is None else (now - self.gate_down_ms) / 1000
            span = self._train_span()
            if span[0] > SENSOR_AT + 150 or span[1] < -SENSOR_AT - 150:
                self.train_x = None
        # luzes
        for key in ("LUZ_E", "LUZ_D"):
            self.light_on_ms[key] = self.light_on_ms[key] + dt_ms if out[key] else 0
            if out[key]:
                self.last_light_ms = now
        self.both_lights_ms = self.both_lights_ms + dt_ms if (out["LUZ_E"] and out["LUZ_D"]) else 0
        if self.both_lights_ms > 600 or max(self.light_on_ms.values()) > 1500:
            self.not_flashing = True
        if self.warning and self.warn_start_ms is None:
            self.warn_start_ms = now
        elif not self.warning:
            self.warn_start_ms = None
        # cancela
        down, up = out["ABAIXA"], out["LEVANTA"]
        self.both_motor_ms = self.both_motor_ms + dt_ms if (down and up) else 0
        old = self.gate
        if down and not up:
            self.gate = min(1.0, self.gate + dt / GATE_S)
        elif up and not down:
            self.gate = max(0.0, self.gate - dt / GATE_S)
        if self.gate > old and old <= 0.02:
            self.gate_started_ms = now
            if self.warn_start_ms is None or now - self.warn_start_ms < WARN_BEFORE_GATE_MS - 50:
                self.early_gate += 1
        if self.gate < old and self._covers(-ISLAND, ISLAND):
            self.raised_on_train = True
        if self.gate >= 0.98 and self.gate_down_ms is None:
            self.gate_down_ms = now
        elif self.gate < 0.98:
            self.gate_down_ms = None
        idle = self.train_x is None and (self.warning or self.gate > 0.02)
        self.no_train_ms = self.no_train_ms + dt_ms if idle else 0
        self._cars(dt, dt_ms)

    def _cars(self, dt: float, dt_ms: int) -> None:
        now = self.time_ms
        if now >= self.next_car_ms:
            if not self.cars or self.cars[-1].y < 140:
                self.cars.append(Car(160.0, 12.0, self.rng.choice(["#2563eb", "#dc2626", "#16a34a", "#7c3aed",
                                                                   "#0891b2", "#ea580c"])))
            self.next_car_ms = now + int(self.rng.uniform(3000, 7000))
        lowering = self.gate > 0.15
        for k, car in enumerate(self.cars):
            obstacle = None
            if k > 0:
                ahead = self.cars[k - 1]
                obstacle = ahead.y + CAR_LEN
            stop_dist = car.v * car.v / (2 * 4.0)
            if car.y > STOP_LINE and (self.warning or lowering) and car.y - STOP_LINE > stop_dist - 0.5:
                obstacle = STOP_LINE if obstacle is None else max(obstacle, STOP_LINE)
            gap = None if obstacle is None else car.y - obstacle
            acc = self.idm.accel(car.v, gap, car.v - (self.cars[k - 1].v if k > 0 and gap is not None
                                                     and obstacle != STOP_LINE else 0.0))
            car.v = max(0.0, car.v + acc * dt)
            car.y -= car.v * dt
            if car.v < 0.5 and car.y > 0:
                car.stopped_ms += dt_ms
                self.max_wait_ms = max(self.max_wait_ms, car.stopped_ms)
            # cancela descendo sobre o carro (a cancela fica do lado da chegada)
            if car.y <= GATE_Y <= car.y + CAR_LEN and self.gate > 0.55:
                self.gate_hit_car = True
            if self._covers(-6.0, 6.0) and car.y <= CROSS_HALF and car.y + CAR_LEN >= -CROSS_HALF:
                self.collision = True
        crossed = [c for c in self.cars if c.y < -60]
        self.cars_crossed += len(crossed)
        self.cars = [c for c in self.cars if c.y >= -60]

    def sensors(self) -> dict[str, bool]:
        return {"SW": self._covers(-SENSOR_AT - 2, -SENSOR_AT + 2), "SE": self._covers(SENSOR_AT - 2, SENSOR_AT + 2),
                "SI": self._covers(-ISLAND, ISLAND), "DOWN": self.gate >= 0.98, "UP": self.gate <= 0.02}

    def alarms(self) -> list[str]:
        out = []
        if self.collision:
            out.append("COLISÃO: o trem atingiu um carro na passagem")
        if self.open_arrivals:
            out.append("O trem chegou à passagem com a cancela aberta")
        if self.early_gate:
            out.append("A cancela começou a descer sem 3 s de aviso das luzes (carros podem ficar presos)")
        if self.gate_hit_car:
            out.append("A cancela desceu sobre um carro")
        if self.raised_on_train:
            out.append("A cancela subiu com o trem ainda na passagem (sensor de ilha I0.1)")
        if self.not_flashing:
            out.append("As luzes devem piscar alternadas (uma acesa, a outra apagada)")
        if self.both_motor_ms > 0:
            out.append("Motor da cancela comandado para abaixar e levantar ao mesmo tempo")
        if self.no_train_ms > 15000:
            out.append("Sinalização ou cancela fechada há mais de 15 s sem trem: o sensor da saída foi "
                       "confundido com um trem chegando?")
        return out

    def stats(self) -> list[str]:
        margin = "-" if self.margin_s is None else f"{self.margin_s:.1f} s"
        return [f"Trens: {self.trains} | carros que cruzaram: {self.cars_crossed} | maior espera: "
                f"{self.max_wait_ms / 1000:.0f} s",
                f"Cancela abaixada antes da chegada do último trem: {margin}"
                + (" | Automático" if self.auto else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"TREM_O": (16, 360, 130, 28), "TREM_L": (494, 360, 130, 28), "AUTO": (16, 20, 130, 28)}

    def _x(self, m: float) -> float:
        return ROAD_X + m * X_SCALE

    def _y(self, m: float) -> float:
        return TRACK_Y + m * Y_SCALE

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#d9f99d"))
        # rodovia
        p.fillRect(QRectF(ROAD_X - 18, 0, 36, 420), QColor("#6b7280"))
        p.setPen(QPen(QColor("#fde047"), 2, Qt.DashLine))
        p.drawLine(QPointF(ROAD_X, 0), QPointF(ROAD_X, 420))
        p.setPen(QPen(draw.WHITE, 3))
        p.drawLine(QPointF(ROAD_X - 18, self._y(STOP_LINE)), QPointF(ROAD_X + 18, self._y(STOP_LINE)))
        # trilhos
        p.fillRect(QRectF(0, TRACK_Y - 12, 640, 24), QColor("#a8a29e"))
        p.setPen(QPen(QColor("#57534e"), 3))
        for k in range(0, 640, 14):
            p.drawLine(QPointF(k, TRACK_Y - 11), QPointF(k, TRACK_Y + 11))
        p.setPen(QPen(QColor("#1c1917"), 2.5))
        p.drawLine(QPointF(0, TRACK_Y - 6), QPointF(640, TRACK_Y - 6))
        p.drawLine(QPointF(0, TRACK_Y + 6), QPointF(640, TRACK_Y + 6))
        sens = self.sensors()
        # sensores
        for key, m, label in (("SW", -SENSOR_AT, "I0.0 oeste"), ("SE", SENSOR_AT, "I0.2 leste")):
            x = self._x(m)
            draw.sensor(p, QRectF(x - 5, TRACK_Y - 30, 10, 16), sens[key])
            draw.tag(p, x - 30, TRACK_Y - 42, label, sens[key])
        p.setPen(QPen(QColor(245, 158, 11, 200) if sens["SI"] else QColor(30, 41, 59, 90), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(self._x(-ISLAND), TRACK_Y - 15, ISLAND * 2 * X_SCALE, 30))
        draw.tag(p, ROAD_X + 24, TRACK_Y - 30, "I0.1 ilha", sens["SI"])
        # carros
        for car in self.cars:
            r = QRectF(ROAD_X - 2, self._y(car.y), 14, CAR_LEN * Y_SCALE + 2)
            if r.top() > 420:
                continue
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor(car.color))
            p.drawRoundedRect(r, 3, 3)
        # trem
        span = self._train_span()
        if span is not None:
            x0, x1 = self._x(span[0]), self._x(span[1])
            p.setPen(QPen(QColor("#0f172a"), 1.2))
            p.setBrush(QColor("#b91c1c"))
            p.drawRoundedRect(QRectF(x0, TRACK_Y - 11, x1 - x0, 22), 5, 5)
            p.setPen(QPen(QColor("#fecaca"), 1))
            x = x0 + 12
            while x < x1 - 6:
                p.drawLine(QPointF(x, TRACK_Y - 11), QPointF(x, TRACK_Y + 11))
                x += 18
        # cancela (do lado de quem chega, ao sul)
        pivot = QPointF(ROAD_X + 34, self._y(GATE_Y))
        ang = math.radians(90 * (1 - self.gate))
        end = QPointF(pivot.x() - math.cos(ang) * 58, pivot.y() - math.sin(ang) * 58)
        p.setPen(QPen(QColor("#dc2626"), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(pivot, end)
        p.setPen(QPen(draw.WHITE, 6, Qt.DotLine, Qt.FlatCap))
        p.drawLine(pivot, end)
        p.setBrush(QColor("#1e293b"))
        p.setPen(Qt.NoPen)
        p.drawEllipse(pivot, 5, 5)
        # sinal de luzes
        post = QPointF(ROAD_X + 70, self._y(GATE_Y + 4))
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(QRectF(post.x() - 26, post.y() - 14, 52, 28), 12, 12)
        draw.lamp(p, QPointF(post.x() - 12, post.y()), 8, self.out.get("LUZ_E", False), draw.RED)
        draw.lamp(p, QPointF(post.x() + 12, post.y()), 8, self.out.get("LUZ_D", False), draw.RED)
        draw.tag(p, post.x() + 34, post.y() - 10, "Q0.0 / Q0.1", self.out.get("LUZ_E", False) or self.out.get("LUZ_D", False))
        draw.tag(p, post.x() + 34, post.y() + 12, "Q0.2 sino", self.out.get("SINO", False))
        if self.out.get("SINO"):
            draw.text(p, post.x() - 30, post.y() - 26, "♪ blém blém", 8, True, QColor("#b45309"), w=90)
        draw.tag(p, 400, 300, "Q0.3 abaixa", self.out.get("ABAIXA", False))
        draw.tag(p, 400, 322, "Q0.4 levanta", self.out.get("LEVANTA", False))
        draw.tag(p, 400, 344, "I0.3 abaixada", sens["DOWN"])
        draw.tag(p, 400, 366, "I0.4 levantada", sens["UP"])
        draw.push_button(p, QRectF(16, 360, 130, 28), "Trem do oeste", False, QColor("#b91c1c"))
        draw.push_button(p, QRectF(494, 360, 130, 28), "Trem do leste", False, QColor("#b91c1c"))
        draw.switch(p, QRectF(16, 20, 130, 28), "Automático", self.auto)
