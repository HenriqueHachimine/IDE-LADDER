"""Passagem de nivel em linha dupla: trens nos dois sentidos e nas duas vias, luzes, sino, cancelas e aviso."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import Environment, IOPoint
from ..physics import IDM
from ..registry import register

SENSOR_AT = 400.0           # sensores de aproximacao a 400 m de cada lado
ISLAND = 15.0               # sensor de ilha: +-15 m em volta da passagem
GATE_S = 6.0                # as cancelas levam 6 s para descer ou subir
WARN_BEFORE_GATE_MS = 3000  # luzes piscando ao menos 3 s antes de a cancela descer
TRACK_D = {1: 4.5, 2: -4.5}  # posicao das vias na rodovia (m a partir do centro da passagem)
STOP_LINE, GATE_D = 16.0, 11.0  # distancias na rodovia (m antes do centro)
CROSS_HALF = 9.0            # faixa das duas vias (m para cada lado)
CAR_LEN = 4.5
KINDS = {"passageiros": (30.0, 140.0, "#1d4ed8"), "carga": (18.0, 250.0, "#7c2d12")}  # m/s, comprimento, cor
AUTO = {1: (8000, 50000, "passageiros"), 2: (30000, 80000, "carga")}  # primeiro, intervalo, tipo
X_SCALE, Y_SCALE = 0.68, 4.2     # px por metro no desenho (trilho / rodovia)
CENTER_Y, ROAD_X = 214.0, 360.0
LANE = {1: 9.0, -1: -9.0}        # mao de direcao: +1 vem do sul (sobe na tela), -1 vem do norte


@dataclass
class Train:
    track: int
    x: float                 # frente do trem (m; 0 = passagem)
    direction: int
    speed: float
    length: float
    color: str
    arrived: bool = False
    detected_ms: int | None = None   # quando a frente passou pelo sensor de aproximacao


@dataclass
class Car:
    d: float                 # frente do carro: distancia ate o centro da passagem (diminui ao avancar)
    v: float
    lane: int
    color: str
    stopped_ms: int = 0


@register
class LevelCrossingEnvironment(Environment):
    id = "passagem_nivel"
    name = "Passagem de nível em linha dupla"
    description = ("Duas vias, trens nos dois sentidos: passageiros a 108 km/h (140 m) e carga a 65 km/h (250 m). "
                   "Cada via tem sensores de aproximação a 400 m (o do lado de saída atua quando o trem vai embora e "
                   "deve ser ignorado) e de ilha. Luzes alternadas, sino e, depois de 3 s de aviso, as duas cancelas "
                   "descem juntas (6 s). Com trens nas duas vias acenda o painel OUTRO TREM; a cancela só sobe com "
                   "as duas vias livres e nenhum trem chegando. Carros nas duas mãos param diante das luzes.")
    example = "ambientes/passagem_nivel.ladproj"
    size = (720, 470)
    inputs = [
        IOPoint("SW1", "I0.0", "Via1_Oeste", "Via 1: aproximação pelo oeste (400 m)"),
        IOPoint("SI1", "I0.1", "Via1_Ilha", "Via 1: trem sobre a passagem (+-15 m)"),
        IOPoint("SE1", "I0.2", "Via1_Leste", "Via 1: aproximação pelo leste (400 m)"),
        IOPoint("DOWN", "I0.3", "Cancela_Abaixada", "Fim de curso: cancelas abaixadas"),
        IOPoint("UP", "I0.4", "Cancela_Levantada", "Fim de curso: cancelas levantadas"),
        IOPoint("SW2", "I0.5", "Via2_Oeste", "Via 2: aproximação pelo oeste (400 m)"),
        IOPoint("SI2", "I0.6", "Via2_Ilha", "Via 2: trem sobre a passagem (+-15 m)"),
        IOPoint("SE2", "I0.7", "Via2_Leste", "Via 2: aproximação pelo leste (400 m)"),
    ]
    outputs = [
        IOPoint("LUZ_E", "Q0.0", "Luz_Esquerda", "Luz vermelha esquerda"),
        IOPoint("LUZ_D", "Q0.1", "Luz_Direita", "Luz vermelha direita"),
        IOPoint("SINO", "Q0.2", "Sino", "Sino de alerta"),
        IOPoint("ABAIXA", "Q0.3", "Cancela_Abaixa", "Motor das cancelas: abaixar"),
        IOPoint("LEVANTA", "Q0.4", "Cancela_Levanta", "Motor das cancelas: levantar"),
        IOPoint("OUTRO", "Q0.5", "Painel_Outro_Trem", "Painel luminoso OUTRO TREM"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(7)
        self.auto = getattr(self, "auto", True)
        self.trains: dict[int, Train | None] = {1: None, 2: None}
        self.next_auto_ms = {k: v[0] for k, v in AUTO.items()}
        self.auto_dir = {1: 1, 2: -1}
        self.gate = 0.0                        # 0 = levantada, 1 = abaixada
        self.cars: dict[int, list[Car]] = {1: [], -1: []}
        self.next_car_ms = {1: 1500, -1: 3500}
        self.idm = IDM(v0=12.0, a=2.0, b=3.0, s0=2.0, T=1.0)
        self.light_on_ms = {"LUZ_E": 0, "LUZ_D": 0}
        self.both_lights_ms = 0
        self.last_light_ms = -10**9
        self.warn_start_ms: int | None = None
        self.gate_down_ms: int | None = None
        self.train_count = 0
        self.cars_crossed = 0
        self.max_wait_ms = 0
        self.margin_s: float | None = None
        self.min_margin_s: float | None = None
        self.no_train_ms = 0
        self.two_trains_ms = 0
        self.sign_missing = False
        self.sign_ms = 0
        self.collision = False
        self.open_arrivals = 0
        self.early_gate = 0
        self.gate_hit_car = False
        self.raised_on_train = False
        self.raised_approaching = False
        self.both_motor_ms = 0
        self.not_flashing = False
        self.bell_phase = 0.0

    # ---------------------------------------------------------- operador
    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.auto = not self.auto
        elif key.startswith("TREM_"):          # TREM_1O, TREM_1L, TREM_2O, TREM_2L
            track = int(key[5])
            if self.trains[track] is None:
                self._spawn(track, 1 if key[6] == "O" else -1, "passageiros" if track == 1 else "carga")

    def press(self, key: str, down: bool) -> None:
        if key == "AUTO" or key.startswith("TREM_"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _spawn(self, track: int, direction: int, kind: str) -> None:
        speed, length, color = KINDS[kind]
        self.trains[track] = Train(track, -direction * (SENSOR_AT + 120.0), direction, speed, length, color)

    # ------------------------------------------------------------- fisica
    @staticmethod
    def _span(t: Train) -> tuple[float, float]:
        rear = t.x - t.direction * t.length
        return min(rear, t.x), max(rear, t.x)

    def _covers(self, track: int, a: float, b: float) -> bool:
        t = self.trains[track]
        if t is None:
            return False
        lo, hi = self._span(t)
        return lo <= b and hi >= a

    def _approaching(self, t: Train) -> bool:
        """Trem entre o sensor de aproximacao e a passagem, ainda sem ter chegado."""
        return not t.arrived and abs(t.x) <= SENSOR_AT + 2

    @property
    def warning(self) -> bool:
        return self.time_ms - self.last_light_ms <= 1200

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        for track, (_, every, kind) in AUTO.items():
            if self.auto and self.trains[track] is None and now >= self.next_auto_ms[track]:
                self._spawn(track, self.auto_dir[track], kind)
                self.auto_dir[track] = -self.auto_dir[track]
                self.next_auto_ms[track] = now + every
        for track, t in self.trains.items():
            if t is None:
                continue
            t.x += t.direction * t.speed * dt
            if t.detected_ms is None and abs(t.x) <= SENSOR_AT + 2:
                t.detected_ms = now
            if not t.arrived and self._covers(track, -ISLAND, ISLAND):
                t.arrived = True
                self.train_count += 1
                if self.gate < 0.98:
                    self.open_arrivals += 1
                self.margin_s = None if self.gate_down_ms is None else (now - self.gate_down_ms) / 1000
                if self.margin_s is not None:
                    self.min_margin_s = self.margin_s if self.min_margin_s is None else min(self.min_margin_s,
                                                                                            self.margin_s)
            lo, hi = self._span(t)
            if lo > SENSOR_AT + 150 or hi < -SENSOR_AT - 150:
                self.trains[track] = None
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
        if out["SINO"]:
            self.bell_phase += dt * 4
        # painel OUTRO TREM: dois trens na zona de aproximacao/passagem ao mesmo tempo
        in_zone = [t for t in self.trains.values() if t is not None and
                   ((not t.arrived and abs(t.x) <= SENSOR_AT + 2) or self._covers(t.track, -ISLAND, ISLAND))]
        both = len(in_zone) == 2 and any(not t.arrived for t in in_zone)
        self.two_trains_ms = self.two_trains_ms + dt_ms if both else 0
        if self.two_trains_ms > 2000 and not out["OUTRO"]:
            self.sign_missing = True
        self.sign_ms = self.sign_ms + dt_ms if (out["OUTRO"] and not in_zone) else 0
        # cancelas
        down, up = out["ABAIXA"], out["LEVANTA"]
        self.both_motor_ms = self.both_motor_ms + dt_ms if (down and up) else 0
        old = self.gate
        if down and not up:
            self.gate = min(1.0, self.gate + dt / GATE_S)
        elif up and not down:
            self.gate = max(0.0, self.gate - dt / GATE_S)
        if self.gate > old and old <= 0.02:
            if self.warn_start_ms is None or now - self.warn_start_ms < WARN_BEFORE_GATE_MS - 50:
                self.early_gate += 1
        if self.gate < old:
            if any(self._covers(k, -ISLAND, ISLAND) for k in (1, 2)):
                self.raised_on_train = True
            if any(t is not None and self._approaching(t) and now - t.detected_ms > 500 for t in self.trains.values()):
                self.raised_approaching = True
        if self.gate >= 0.98 and self.gate_down_ms is None:
            self.gate_down_ms = now
        elif self.gate < 0.98:
            self.gate_down_ms = None
        no_train = all(t is None for t in self.trains.values())
        idle = no_train and (self.warning or self.gate > 0.02)
        self.no_train_ms = self.no_train_ms + dt_ms if idle else 0
        for lane in (1, -1):
            self._cars(lane, dt, dt_ms)

    def _cars(self, lane: int, dt: float, dt_ms: int) -> None:
        now = self.time_ms
        cars = self.cars[lane]
        if now >= self.next_car_ms[lane]:
            if not cars or cars[-1].d < 75:
                cars.append(Car(90.0, 12.0, lane, self.rng.choice(["#2563eb", "#dc2626", "#16a34a", "#7c3aed",
                                                                   "#0891b2", "#ea580c", "#f8fafc", "#facc15"])))
            self.next_car_ms[lane] = now + int(self.rng.uniform(3500, 8000))
        lowering = self.gate > 0.15
        for k, car in enumerate(cars):
            obstacle = None
            if k > 0:
                obstacle = cars[k - 1].d + CAR_LEN
            stop_dist = car.v * car.v / (2 * 4.0)
            if car.d > STOP_LINE and (self.warning or lowering) and car.d - STOP_LINE > stop_dist - 0.5:
                obstacle = STOP_LINE if obstacle is None else max(obstacle, STOP_LINE)
            gap = None if obstacle is None else car.d - obstacle
            dv = car.v - cars[k - 1].v if (k > 0 and gap is not None and obstacle != STOP_LINE) else 0.0
            acc = self.idm.accel(car.v, gap, dv)
            if obstacle == STOP_LINE and gap is not None and gap > 0.3:
                acc = min(acc, -car.v * car.v / (2 * gap) * 1.15)     # freia para parar na faixa
            car.v = max(0.0, car.v + acc * dt)
            car.d -= car.v * dt
            if car.v < 0.5 and car.d > 0:
                car.stopped_ms += dt_ms
                self.max_wait_ms = max(self.max_wait_ms, car.stopped_ms)
            if car.d <= GATE_D <= car.d + CAR_LEN and self.gate > 0.55:
                self.gate_hit_car = True
            for track, td in TRACK_D.items():
                pos = td * lane                      # a via 1 fica antes para quem vem do sul
                if self._covers(track, -6.0, 6.0) and car.d <= pos + 2 and car.d + CAR_LEN >= pos - 2:
                    self.collision = True
        crossed = [c for c in cars if c.d < -60]
        self.cars_crossed += len(crossed)
        self.cars[lane] = [c for c in cars if c.d >= -60]

    def sensors(self) -> dict[str, bool]:
        s = {"DOWN": self.gate >= 0.98, "UP": self.gate <= 0.02}
        for track in (1, 2):
            s[f"SW{track}"] = self._covers(track, -SENSOR_AT - 2, -SENSOR_AT + 2)
            s[f"SE{track}"] = self._covers(track, SENSOR_AT - 2, SENSOR_AT + 2)
            s[f"SI{track}"] = self._covers(track, -ISLAND, ISLAND)
        return s

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
            out.append("A cancela subiu com um trem ainda na passagem (sensores de ilha I0.1 e I0.6)")
        if self.raised_approaching:
            out.append("A cancela subiu com outro trem chegando: espere as duas vias ficarem livres")
        if self.sign_missing:
            out.append("Dois trens na zona sem o painel OUTRO TREM (Q0.5) aceso")
        if self.sign_ms > 3000:
            out.append("Painel OUTRO TREM aceso sem trem nenhum")
        if self.not_flashing:
            out.append("As luzes devem piscar alternadas (uma acesa, a outra apagada)")
        if self.both_motor_ms > 0:
            out.append("Motor da cancela comandado para abaixar e levantar ao mesmo tempo")
        if self.no_train_ms > 15000:
            out.append("Sinalização ou cancela fechada há mais de 15 s sem trem: o sensor da saída foi "
                       "confundido com um trem chegando?")
        return out

    def stats(self) -> list[str]:
        margin = "-" if self.min_margin_s is None else f"{self.min_margin_s:.1f} s"
        return [f"Trens: {self.train_count} | carros que cruzaram: {self.cars_crossed} | maior espera: "
                f"{self.max_wait_ms / 1000:.0f} s",
                f"Menor folga entre a cancela abaixar e o trem chegar: {margin}" + (" | Automático" if self.auto else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"TREM_1O": (14, 404, 120, 26), "TREM_2O": (14, 434, 120, 26), "TREM_1L": (586, 404, 120, 26),
                "TREM_2L": (586, 434, 120, 26), "AUTO": (14, 14, 130, 28)}

    def _x(self, m: float) -> float:
        return ROAD_X + m * X_SCALE

    def _y(self, d: float) -> float:
        return CENTER_Y + d * Y_SCALE

    def _track_y(self, track: int) -> float:
        return self._y(TRACK_D[track])

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 470)
        draw.grass(p, 0, 720, 470)
        sens = self.sensors()
        # arvores
        for k, (x, y) in enumerate(((70, 80), (120, 330), (560, 70), (650, 320), (230, 60), (480, 350), (40, 280),
                                    (680, 130))):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(20, 83, 45, 60))
            p.drawEllipse(QPointF(x + 4, y + 4), 18, 18)
            g = QLinearGradient(x - 16, y - 16, x + 16, y + 16)
            g.setColorAt(0, QColor("#4ade80"))
            g.setColorAt(1, QColor("#166534"))
            p.setBrush(g)
            p.drawEllipse(QPointF(x, y), 17 - k % 3 * 2, 17 - k % 3 * 2)
        # rodovia
        road = QRectF(ROAD_X - 26, 0, 52, 470)
        g = QLinearGradient(road.topLeft(), road.topRight())
        g.setColorAt(0, QColor("#4b5563"))
        g.setColorAt(0.5, QColor("#6b7280"))
        g.setColorAt(1, QColor("#4b5563"))
        p.fillRect(road, g)
        p.setPen(QPen(QColor("#fde047"), 2, Qt.DashLine))
        p.drawLine(QPointF(ROAD_X, 0), QPointF(ROAD_X, 470))
        p.setPen(QPen(draw.WHITE, 3))
        for lane in (1, -1):
            y = self._y(STOP_LINE * lane)
            x0 = ROAD_X if lane == 1 else ROAD_X - 26
            p.drawLine(QPointF(x0, y), QPointF(x0 + 26, y))
        # vias (lastro, dormentes e trilhos)
        for track in (1, 2):
            ty = self._track_y(track)
            p.fillRect(QRectF(0, ty - 11, 720, 22), QColor("#a8a29e"))
            p.setPen(QPen(QColor("#57534e"), 3))
            for k in range(0, 720, 12):
                p.drawLine(QPointF(k, ty - 9), QPointF(k, ty + 9))
            p.setPen(QPen(QColor("#1c1917"), 2.2))
            p.drawLine(QPointF(0, ty - 5), QPointF(720, ty - 5))
            p.drawLine(QPointF(0, ty + 5), QPointF(720, ty + 5))
            draw.text(p, 8, ty, f"via {track}", 7, True, draw.WHITE, w=40)
        # sensores
        for track in (1, 2):
            ty = self._track_y(track)
            for key, m, side in ((f"SW{track}", -SENSOR_AT, "oeste"), (f"SE{track}", SENSOR_AT, "leste")):
                x = self._x(m)
                yy = ty + 12 if track == 1 else ty - 24
                draw.sensor(p, QRectF(x - 5, yy, 10, 12), sens[key], vertical=True)
                addr = next(pt.address for pt in self.inputs if pt.key == key)
                draw.tag(p, x + 8, yy + 6, addr, sens[key])
            p.setPen(QPen(QColor(245, 158, 11, 220) if sens[f"SI{track}"] else QColor(30, 41, 59, 90), 1.5,
                          Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(self._x(-ISLAND), ty - 11, ISLAND * 2 * X_SCALE, 22))
        draw.tag(p, ROAD_X - 100, self._track_y(1) + 22, "I0.1 ilha 1", sens["SI1"])
        draw.tag(p, ROAD_X - 100, self._track_y(2) - 20, "I0.6 ilha 2", sens["SI2"])
        # carros (vista de cima)
        for lane, cars in self.cars.items():
            for car in cars:
                d = car.d * lane
                y0 = self._y(d)
                h = CAR_LEN * Y_SCALE
                r = QRectF(ROAD_X + LANE[lane] - 7, y0 if lane == 1 else y0 - h, 14, h)
                if r.bottom() < -20 or r.top() > 490:
                    continue
                draw.shadow(p, r, 3, 2)
                p.setPen(QPen(QColor("#0f172a"), 1))
                p.setBrush(QColor(car.color))
                p.drawRoundedRect(r, 4, 4)
                glass = QRectF(r.left() + 2, (r.top() + 3) if lane == 1 else (r.bottom() - 7), 10, 4)
                p.setBrush(QColor(15, 23, 42, 150))
                p.drawRoundedRect(glass, 1.5, 1.5)
        # trens
        for track, t in self.trains.items():
            if t is None:
                continue
            ty = self._track_y(track)
            lo, hi = self._span(t)
            x0, x1 = self._x(lo), self._x(hi)
            n = max(1, round(t.length / 25))
            seg = (x1 - x0) / n
            for k in range(n):
                car = QRectF(x0 + k * seg + 1, ty - 9, seg - 2, 18)
                draw.shadow(p, car, 3, 2)
                draw.metal(p, car, t.color, 3)
                if t.color == KINDS["passageiros"][2]:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor("#fde68a"))
                    for w in range(3):
                        p.drawRect(QRectF(car.left() + 4 + w * (seg - 8) / 3, ty - 2, (seg - 8) / 3 - 3, 4))
            head = QPointF(self._x(t.x), ty)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(254, 240, 138, 120))
            p.drawEllipse(QPointF(head.x() + t.direction * 10, ty), 10, 7)
        # cancelas (uma por mao, do lado de quem chega) e sinais
        for lane in (1, -1):
            pivot = QPointF(ROAD_X + 34 * lane, self._y(GATE_D * lane))
            ang = math.radians(90 * (1 - self.gate))
            length = 28
            end = QPointF(pivot.x() - lane * math.cos(ang) * length, pivot.y() - lane * math.sin(ang) * length)
            p.setPen(QPen(QColor("#dc2626"), 6, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pivot, end)
            p.setPen(QPen(draw.WHITE, 6, Qt.DotLine, Qt.FlatCap))
            p.drawLine(pivot, end)
            draw.metal(p, QRectF(pivot.x() - 6, pivot.y() - 6, 12, 12), "#334155", 3)
            post = QPointF(ROAD_X + 70 * lane, self._y((GATE_D + 6) * lane))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#111827"))
            p.drawRoundedRect(QRectF(post.x() - 22, post.y() - 11, 44, 22), 10, 10)
            draw.lamp(p, QPointF(post.x() - 10, post.y()), 6.5, self.out.get("LUZ_E", False), draw.RED)
            draw.lamp(p, QPointF(post.x() + 10, post.y()), 6.5, self.out.get("LUZ_D", False), draw.RED)
            # cruz de santo andre
            c = QPointF(post.x(), post.y() + 22 * lane)
            p.setPen(QPen(QColor("#b91c1c"), 4, Qt.SolidLine, Qt.FlatCap))
            p.drawLine(QPointF(c.x() - 11, c.y() - 7), QPointF(c.x() + 11, c.y() + 7))
            p.drawLine(QPointF(c.x() - 11, c.y() + 7), QPointF(c.x() + 11, c.y() - 7))
            p.setPen(QPen(draw.WHITE, 1.4, Qt.DashLine, Qt.FlatCap))
            p.drawLine(QPointF(c.x() - 11, c.y() - 7), QPointF(c.x() + 11, c.y() + 7))
            p.drawLine(QPointF(c.x() - 11, c.y() + 7), QPointF(c.x() + 11, c.y() - 7))
        # painel OUTRO TREM
        sign = QRectF(ROAD_X + 82, self._y(GATE_D + 22) - 2, 76, 22)
        on = self.out.get("OUTRO", False)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(sign, 4, 4)
        blink = on and (self.time_ms // 500) % 2 == 0
        draw.ctext(p, sign.center().x(), sign.center().y(), "OUTRO TREM", 7.5, True,
                   QColor("#fbbf24") if blink else QColor("#3f3f46"), 76)
        if self.out.get("SINO"):
            for k in range(3):
                a = self.bell_phase + k
                draw.text(p, ROAD_X + 100 + k * 14, self._y(-GATE_D - 22) + math.sin(a) * 3, "♪", 10, True,
                          QColor("#b45309"), w=20)
        # painel de saidas
        card = QRectF(150, 404, 420, 56)
        draw.card(p, card)
        out = self.out
        for k, (addr, name, key) in enumerate((("Q0.0", "luz E", "LUZ_E"), ("Q0.1", "luz D", "LUZ_D"),
                                               ("Q0.2", "sino", "SINO"), ("Q0.5", "outro trem", "OUTRO"))):
            draw.tag(p, 160 + k * 100, 418, f"{addr} {name}", out.get(key, False))
        draw.tag(p, 160, 444, "Q0.3 abaixa", out.get("ABAIXA", False))
        draw.tag(p, 260, 444, "Q0.4 levanta", out.get("LEVANTA", False))
        draw.tag(p, 360, 444, "I0.3 abaixada", sens["DOWN"])
        draw.tag(p, 460, 444, "I0.4 levantada", sens["UP"])
        draw.push_button(p, QRectF(14, 404, 120, 26), "Via 1 → leste", False, QColor("#1d4ed8"))
        draw.push_button(p, QRectF(14, 434, 120, 26), "Via 2 → leste", False, QColor("#7c2d12"))
        draw.push_button(p, QRectF(586, 404, 120, 26), "Via 1 ← oeste", False, QColor("#1d4ed8"))
        draw.push_button(p, QRectF(586, 434, 120, 26), "Via 2 ← oeste", False, QColor("#7c2d12"))
        draw.switch(p, QRectF(14, 14, 130, 28), "Automático", self.auto)
