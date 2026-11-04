"""Cruzamento com semaforos: via Norte-Sul e via Leste-Oeste, pedestres e sensores de veiculo."""
from __future__ import annotations

import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import IDM
from ..registry import register

ROAD_NS = (270.0, 370.0)        # x da via Norte-Sul
ROAD_LO = (160.0, 260.0)        # y da via Leste-Oeste
LANE_NS_X = 295.0               # faixa sentido sul
LANE_LO_Y = 235.0               # faixa sentido leste
STOP_NS = ROAD_LO[0] - 30       # linha de retencao (frente do carro), antes da faixa de pedestres
STOP_LO = ROAD_NS[0] - 30
CROSSWALK_NS = (ROAD_LO[0] - 26, ROAD_LO[0] - 4)   # faixa de pedestres sobre a via NS (y)
CROSSWALK_LO = (ROAD_NS[0] - 26, ROAD_NS[0] - 4)   # faixa de pedestres sobre a via LO (x)
PX_PER_M = 9.0                  # escala do desenho
CAR_L, CAR_W = 40.0, 20.0       # 4,4 m x 2,2 m
END_NS, END_LO = 470.0, 690.0
SENSOR_ZONE = 150.0             # laco indutivo de ~17 m antes da linha
YELLOW_MAX_DECEL = 3.5          # m/s^2: acima disso o motorista segue no amarelo (zona de dilema)
PED_SPEED = 1.3                 # m/s
PED_PATH = 120.0                # px percorridos na travessia (via + calcadas)
DRIVER = IDM()


@dataclass
class Car:
    s: float                    # posicao da frente ao longo da faixa (px)
    color: QColor
    v: float = 0.0              # m/s
    go: bool | None = None      # decisao no amarelo (None = ainda nao decidiu)
    waited_ms: int = 0


@register
class TrafficLightEnvironment(Environment):
    id = "semaforo"
    name = "Semáforo de cruzamento"
    description = ("Controle os semáforos da via Norte-Sul (NS) e Leste-Oeste (LO). Os carros aceleram e freiam "
                   "como motoristas reais (modelo IDM, 50 km/h): no amarelo, quem não consegue parar segue em "
                   "frente, por isso o vermelho geral precisa dar tempo de o cruzamento esvaziar. Os sensores "
                   "indicam carros esperando; os pedestres (1,3 m/s) pedem travessia pelos botões.")
    example = "ambientes/semaforo.ladproj"
    inputs = [
        IOPoint("PED_NS", "I0.0", "Botao_Pedestre_NS", "Pedestre pede para atravessar a via NS", BUTTON),
        IOPoint("PED_LO", "I0.1", "Botao_Pedestre_LO", "Pedestre pede para atravessar a via LO", BUTTON),
        IOPoint("CAR_NS", "I0.2", "Sensor_Carro_NS", "Carro aguardando na via NS"),
        IOPoint("CAR_LO", "I0.3", "Sensor_Carro_LO", "Carro aguardando na via LO"),
    ]
    outputs = [
        IOPoint("RED_NS", "Q0.0", "Vermelho_NS", "Vermelho da via Norte-Sul"),
        IOPoint("YEL_NS", "Q0.1", "Amarelo_NS", "Amarelo da via Norte-Sul"),
        IOPoint("GRN_NS", "Q0.2", "Verde_NS", "Verde da via Norte-Sul"),
        IOPoint("WALK_NS", "Q0.3", "Pedestre_NS", "Travessia de pedestres sobre a via NS liberada"),
        IOPoint("RED_LO", "Q0.4", "Vermelho_LO", "Vermelho da via Leste-Oeste"),
        IOPoint("YEL_LO", "Q0.5", "Amarelo_LO", "Amarelo da via Leste-Oeste"),
        IOPoint("GRN_LO", "Q0.6", "Verde_LO", "Verde da via Leste-Oeste"),
        IOPoint("WALK_LO", "Q0.7", "Pedestre_LO", "Travessia de pedestres sobre a via LO liberada"),
    ]
    COLORS = ["#2563eb", "#dc2626", "#7c3aed", "#0891b2", "#ea580c", "#4b5563", "#16a34a"]

    def reset(self) -> None:
        self.rng = random.Random(7)
        self.cars = {"NS": [], "LO": []}
        self.next_arrival = {"NS": 500, "LO": 1500}
        self.passed = {"NS": 0, "LO": 0}
        self.max_wait = {"NS": 0, "LO": 0}
        self.waiting_ped = {"NS": False, "LO": False}
        self.crossing = {"NS": -1.0, "LO": -1.0}   # progresso da travessia 0..1 (-1 = ninguem)
        self._button_prev = {"NS": False, "LO": False}
        self.collisions = 0
        self._colliding = False
        self.hits = 0
        self._hitting = {"NS": False, "LO": False}
        self.conflict_ms = 0
        self.ped_conflict_ms = 0
        self.dark_ms = 0
        self.red_runners = 0

    # ------------------------------------------------------------- fisica
    def _ped_blocks_lane(self, d: str) -> bool:
        """Pedestre sobre a faixa da via d, ainda antes de passar da pista dos carros."""
        f = self.crossing[d]
        if f < 0:
            return False
        pos = -10 + f * PED_PATH                    # deslocamento a partir da borda da via
        lane = (LANE_NS_X - ROAD_NS[0]) if d == "NS" else (LANE_LO_Y - ROAD_LO[0])
        return pos < lane + CAR_W / 2 + 8

    def _signal_obstacle(self, d: str, out: dict[str, bool], car: Car) -> float | None:
        """Distancia (px) ate onde o carro precisa parar por causa do sinal, ou None."""
        stop = STOP_NS if d == "NS" else STOP_LO
        if car.s > stop:
            return None
        if out[f"GRN_{d}"] and not out[f"RED_{d}"] and not out[f"YEL_{d}"]:
            car.go = None                           # verde: nada a decidir
            return None
        if car.go is None:
            dist_m = (stop - car.s) / PX_PER_M
            needed = car.v * car.v / (2 * max(dist_m, 0.01))
            if out[f"YEL_{d}"] and not out[f"RED_{d}"]:
                car.go = needed > YELLOW_MAX_DECEL       # amarelo: segue se nao der para parar com conforto
            else:
                car.go = needed > 0.9 * DRIVER.b_max     # vermelho repentino: so segue se fisicamente nao para
        if car.go:
            return None
        return stop - car.s

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for d in ("NS", "LO"):
            cars = self.cars[d]
            self.next_arrival[d] -= dt_ms
            if self.next_arrival[d] <= 0:
                if not cars or cars[-1].s - CAR_L > -40 + DRIVER.s0 * PX_PER_M + 10:
                    cars.append(Car(-40.0, QColor(self.rng.choice(self.COLORS)), v=0.8 * DRIVER.v0))
                    self.next_arrival[d] = self.rng.randint(4000, 9000)   # ~550 veiculos/h por faixa
            stop = STOP_NS if d == "NS" else STOP_LO
            walk_edge = (CROSSWALK_NS[0] if d == "NS" else CROSSWALK_LO[0]) - 2
            for k, car in enumerate(cars):
                gaps = []
                if k > 0:                            # carro da frente (IDM)
                    lead = cars[k - 1]
                    gaps.append(((lead.s - CAR_L - car.s) / PX_PER_M, car.v - lead.v))
                sig = self._signal_obstacle(d, out, car)
                if sig is not None:                  # linha de retencao: obstaculo parado
                    gaps.append((sig / PX_PER_M + DRIVER.s0, car.v))
                if self._ped_blocks_lane(d) and car.s <= walk_edge + 1:
                    gaps.append(((walk_edge - car.s) / PX_PER_M + DRIVER.s0 * 0.5, car.v))
                if gaps:
                    acc = min(DRIVER.accel(car.v, g, dv) for g, dv in gaps)
                else:
                    acc = DRIVER.accel(car.v, None)
                was_before = car.s <= stop
                car.v = max(0.0, car.v + acc * dt)
                car.s += car.v * dt * PX_PER_M
                if sig is not None and car.s > stop:   # parou na linha: nao avanca por erro numerico
                    car.s, car.v = stop, 0.0
                if was_before and car.s > stop and out[f"RED_{d}"] and not out[f"YEL_{d}"]:
                    self.red_runners += 1            # cruzou a linha ja no vermelho (decidiu seguir no amarelo)
                if car.v < 0.5 and car.s <= stop:
                    car.waited_ms += dt_ms
                    self.max_wait[d] = max(self.max_wait[d], car.waited_ms)
            end = END_NS if d == "NS" else END_LO
            while cars and cars[0].s - CAR_L > end:
                cars.pop(0)
                self.passed[d] += 1
            # pedestres
            pressed = self.is_pressed(f"PED_{d}")
            if pressed and not self._button_prev[d]:      # um pedido por toque no botao
                self.waiting_ped[d] = True
            self._button_prev[d] = pressed
            if self.crossing[d] >= 0:
                self.crossing[d] += PED_SPEED * PX_PER_M * dt / PED_PATH
                if self.crossing[d] >= 1:
                    self.crossing[d] = -1.0
            elif self.waiting_ped[d] and out[f"WALK_{d}"]:
                self.waiting_ped[d] = False
                self.crossing[d] = 0.0
            # atropelamento: carro sobre a faixa enquanto o pedestre esta na pista dele
            lo_w, hi_w = CROSSWALK_NS if d == "NS" else CROSSWALK_LO
            on_walk = any(c.s > lo_w and c.s - CAR_L < hi_w for c in cars)
            f = self.crossing[d]
            in_lane = False
            if f >= 0:
                pos = -10 + f * PED_PATH
                lane = (LANE_NS_X - ROAD_NS[0]) if d == "NS" else (LANE_LO_Y - ROAD_LO[0])
                in_lane = abs(pos - lane) < CAR_W / 2 + 3
            hit = on_walk and in_lane
            if hit and not self._hitting[d]:
                self.hits += 1
            self._hitting[d] = hit
        # colisao no cruzamento
        ns_in = any(c.s > ROAD_LO[0] and c.s - CAR_L < ROAD_LO[1] for c in self.cars["NS"])
        lo_in = any(c.s > ROAD_NS[0] and c.s - CAR_L < ROAD_NS[1] for c in self.cars["LO"])
        if ns_in and lo_in and not self._colliding:
            self.collisions += 1
        self._colliding = ns_in and lo_in
        go_ns = out["GRN_NS"] or out["YEL_NS"]
        go_lo = out["GRN_LO"] or out["YEL_LO"]
        self.conflict_ms = self.conflict_ms + dt_ms if (go_ns and go_lo) else 0
        walk_bad = (out["WALK_NS"] and go_ns) or (out["WALK_LO"] and go_lo)
        self.ped_conflict_ms = self.ped_conflict_ms + dt_ms if walk_bad else 0
        dark = not any(out[f"{c}_NS"] for c in ("RED", "YEL", "GRN")) or \
            not any(out[f"{c}_LO"] for c in ("RED", "YEL", "GRN"))
        self.dark_ms = self.dark_ms + dt_ms if dark else 0

    def sensors(self) -> dict[str, bool]:
        res = {}
        for d in ("NS", "LO"):
            stop = STOP_NS if d == "NS" else STOP_LO
            res[f"CAR_{d}"] = any(stop - SENSOR_ZONE <= c.s <= stop for c in self.cars[d])
        return res

    def alarms(self) -> list[str]:
        out = []
        if self.conflict_ms > 0:
            out.append("PERIGO: as duas vias estão liberadas (verde/amarelo) ao mesmo tempo")
        if self.ped_conflict_ms > 0:
            out.append("PERIGO: travessia de pedestres liberada com carros passando na mesma via")
        if self.collisions:
            out.append(f"{self.collisions} colisao(oes) no cruzamento")
        if self.hits:
            out.append(f"{self.hits} pedestre(s) atropelado(s): carro passou pela faixa com pedestre na pista")
        if self.dark_ms > 500:
            out.append("Um dos semáforos esta apagado")
        for d in ("NS", "LO"):
            if self.out.get(f"RED_{d}") and self.out.get(f"GRN_{d}"):
                out.append(f"Semáforo {d} com vermelho e verde acesos juntos")
        return out

    def stats(self) -> list[str]:
        return [f"Carros que passaram: NS {self.passed['NS']}, LO {self.passed['LO']}",
                f"Maior espera: NS {self.max_wait['NS'] / 1000:.1f} s, LO {self.max_wait['LO'] / 1000:.1f} s"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"PED_NS": (420, 112, 118, 26), "PED_LO": (20, 340, 118, 26)}

    def _head(self, p: QPainter, x: float, y: float, d: str, horizontal: bool) -> None:
        out = self.out
        w, h = (84, 30) if horizontal else (30, 84)
        p.setPen(QPen(QColor("#0f172a"), 1.2))
        p.setBrush(QColor("#1e293b"))
        p.drawRoundedRect(QRectF(x, y, w, h), 6, 6)
        for k, (key, color) in enumerate((("RED", draw.RED), ("YEL", draw.AMBER), ("GRN", draw.GREEN))):
            c = QPointF(x + 15 + k * 27, y + 15) if horizontal else QPointF(x + 15, y + 15 + k * 27)
            draw.lamp(p, c, 10, out[f"{key}_{d}"], color)

    def _pedestrian_light(self, p: QPainter, x: float, y: float, d: str) -> None:
        on = self.out[f"WALK_{d}"]
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#1e293b"))
        p.drawRoundedRect(QRectF(x, y, 26, 26), 4, 4)
        color = draw.GREEN if on else draw.RED
        p.setPen(QPen(color, 2.4))
        cx, cy = x + 13, y + 13
        p.drawEllipse(QPointF(cx, cy - 7), 2.5, 2.5)
        p.drawLine(QPointF(cx, cy - 4), QPointF(cx, cy + 4))
        if on:
            p.drawLine(QPointF(cx, cy + 4), QPointF(cx - 4, cy + 10))
            p.drawLine(QPointF(cx, cy + 4), QPointF(cx + 4, cy + 10))
            p.drawLine(QPointF(cx - 5, cy - 1), QPointF(cx + 5, cy + 1))
        else:
            p.drawLine(QPointF(cx, cy + 4), QPointF(cx - 2, cy + 10))
            p.drawLine(QPointF(cx, cy + 4), QPointF(cx + 2, cy + 10))
            p.drawLine(QPointF(cx - 5, cy - 2), QPointF(cx + 5, cy - 2))

    def _car(self, p: QPainter, rect: QRectF, color: QColor) -> None:
        p.setPen(QPen(color.darker(160), 1))
        p.setBrush(color)
        p.drawRoundedRect(rect, 5, 5)
        p.setBrush(QColor(203, 213, 225, 220))
        inner = rect.adjusted(4, 4, -4, -4)
        p.drawRoundedRect(inner, 3, 3)

    def _person(self, p: QPainter, x: float, y: float, color: QColor) -> None:
        p.setPen(QPen(color, 2.2))
        p.drawEllipse(QPointF(x, y - 7), 3, 3)
        p.drawLine(QPointF(x, y - 4), QPointF(x, y + 4))
        p.drawLine(QPointF(x, y + 4), QPointF(x - 3, y + 10))
        p.drawLine(QPointF(x, y + 4), QPointF(x + 3, y + 10))

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        out, sens = self.out, self.sensors()
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#86efac").darker(115))
        for r in (QRectF(0, 0, ROAD_NS[0], ROAD_LO[0]), QRectF(ROAD_NS[1], 0, 640, ROAD_LO[0]),
                  QRectF(0, ROAD_LO[1], ROAD_NS[0], 420), QRectF(ROAD_NS[1], ROAD_LO[1], 640, 420)):
            p.fillRect(r.adjusted(4, 4, -4, -4), QColor("#bbf7d0"))
        road = QColor("#475569")
        p.fillRect(QRectF(ROAD_NS[0], 0, ROAD_NS[1] - ROAD_NS[0], 420), road)
        p.fillRect(QRectF(0, ROAD_LO[0], 640, ROAD_LO[1] - ROAD_LO[0]), road)
        # faixas centrais e de pedestres
        p.setPen(QPen(QColor("#facc15"), 2, Qt.DashLine))
        mid_x, mid_y = sum(ROAD_NS) / 2, sum(ROAD_LO) / 2
        p.drawLine(QPointF(mid_x, 0), QPointF(mid_x, ROAD_LO[0] - 30))
        p.drawLine(QPointF(mid_x, ROAD_LO[1] + 30), QPointF(mid_x, 420))
        p.drawLine(QPointF(0, mid_y), QPointF(ROAD_NS[0] - 30, mid_y))
        p.drawLine(QPointF(ROAD_NS[1] + 30, mid_y), QPointF(640, mid_y))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#f8fafc"))
        for k in range(6):                       # faixa sobre a via NS (ao norte do cruzamento)
            p.drawRect(QRectF(ROAD_NS[0] + 4 + k * 16, ROAD_LO[0] - 26, 9, 22))
        for k in range(6):                       # faixa sobre a via LO (a oeste do cruzamento)
            p.drawRect(QRectF(ROAD_NS[0] - 26, ROAD_LO[0] + 4 + k * 16, 22, 9))
        p.setPen(QPen(QColor("#f8fafc"), 3))
        p.drawLine(QPointF(ROAD_NS[0], STOP_NS + 2), QPointF(mid_x, STOP_NS + 2))
        p.drawLine(QPointF(STOP_LO + 2, mid_y), QPointF(STOP_LO + 2, ROAD_LO[1]))

        # carros
        for c in self.cars["NS"]:
            self._car(p, QRectF(LANE_NS_X - CAR_W / 2, c.s - CAR_L, CAR_W, CAR_L), c.color)
        for c in self.cars["LO"]:
            self._car(p, QRectF(c.s - CAR_L, LANE_LO_Y - CAR_W / 2, CAR_L, CAR_W), c.color)

        # pedestres atravessando
        for d in ("NS", "LO"):
            if self.crossing[d] >= 0:
                f = self.crossing[d]
                if d == "NS":
                    self._person(p, ROAD_NS[0] - 10 + f * (ROAD_NS[1] - ROAD_NS[0] + 20), ROAD_LO[0] - 15,
                                 QColor("#0f172a"))
                else:
                    self._person(p, ROAD_NS[0] - 15, ROAD_LO[0] - 10 + f * (ROAD_LO[1] - ROAD_LO[0] + 20),
                                 QColor("#0f172a"))
            if self.waiting_ped[d]:
                x, y = (ROAD_NS[0] - 16, ROAD_LO[0] - 40) if d == "NS" else (ROAD_NS[0] - 40, ROAD_LO[0] - 14)
                self._person(p, x, y, QColor("#b91c1c"))

        # semaforos
        self._head(p, ROAD_NS[1] + 10, ROAD_LO[0] - 98, "NS", False)
        draw.text(p, ROAD_NS[1] + 46, ROAD_LO[0] - 90, "Via NS", 8, True)
        draw.tag(p, ROAD_NS[1] + 46, ROAD_LO[0] - 72, "Q0.0-Q0.2")
        self._head(p, ROAD_NS[0] - 120, ROAD_LO[1] + 10, "LO", True)
        draw.text(p, ROAD_NS[0] - 120, ROAD_LO[1] + 52, "Via LO", 8, True)
        draw.tag(p, ROAD_NS[0] - 120, ROAD_LO[1] + 68, "Q0.4-Q0.6")
        self._pedestrian_light(p, ROAD_NS[0] - 34, ROAD_LO[0] - 60, "NS")
        draw.tag(p, ROAD_NS[0] - 80, ROAD_LO[0] - 47, "Q0.3", out["WALK_NS"])
        self._pedestrian_light(p, ROAD_NS[0] - 30, ROAD_LO[1] + 8, "LO")
        draw.tag(p, ROAD_NS[0] - 30, ROAD_LO[1] + 46, "Q0.7", out["WALK_LO"])

        # sensores de veiculo (laco indutivo)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(draw.AMBER if sens["CAR_NS"] else QColor("#94a3b8"), 2, Qt.DashLine))
        p.drawRect(QRectF(LANE_NS_X - 16, STOP_NS - SENSOR_ZONE, 32, SENSOR_ZONE))
        draw.tag(p, LANE_NS_X - 60, 30, "I0.2", sens["CAR_NS"])
        p.setPen(QPen(draw.AMBER if sens["CAR_LO"] else QColor("#94a3b8"), 2, Qt.DashLine))
        p.drawRect(QRectF(STOP_LO - SENSOR_ZONE, LANE_LO_Y - 16, SENSOR_ZONE, 32))
        draw.tag(p, 20, ROAD_LO[1] + 14, "I0.3", sens["CAR_LO"])

        # botoes de pedestre
        draw.push_button(p, QRectF(420, 112, 118, 26), "Pedestre I0.0", self.is_pressed("PED_NS"), draw.AMBER)
        draw.push_button(p, QRectF(20, 340, 118, 26), "Pedestre I0.1", self.is_pressed("PED_LO"), draw.AMBER)
