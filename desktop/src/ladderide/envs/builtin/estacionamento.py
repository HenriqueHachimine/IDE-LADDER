"""Estacionamento de dois pisos: cancelas, lacos, rampa com deteccao de sentido e paineis de vagas (registradores N)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..registry import register

PER_FLOOR = 8
CAPACITY = 2 * PER_FLOOR
WORDS = {"total": 0, 1: 1, 2: 2}  # N0 vagas livres no total, N1 no piso 1, N2 no piso 2 (escritos pelo programa)
LANE_SPEED = 110.0                # px/s nas pistas
INSIDE_SPEED = 90.0               # px/s dentro do estacionamento
CAR_PX = 40.0
GATE_S = 1.0                      # cancela sobe/desce em 1 s
ENTRY_ARM, EXIT_ARM = 180.0, 480.0
ENTRY_STOP, EXIT_STOP = 172.0, 472.0
ENTRY_WAIT, EXIT_WAIT = 128.0, 428.0    # faixa de espera antes do laco (o proximo so avanca com o laco livre)
ENTRY_LOOP, EXIT_LOOP = (140.0, 212.0), (440.0, 512.0)
GIVE_UP_MS = 12000
MISMATCH_MS = 3000
LANE_Y = 414.0
AISLE_Y = 214.0
TURN_IN, TURN_OUT = 262.0, 314.0        # onde os carros saem da pista de entrada / entram na de saida
RAMP = (330.0, 400.0)                   # rampa entre os pisos (x)
LOOP_A, LOOP_B = (338.0, 356.0), (374.0, 392.0)
RAMP_MID = 365.0
TOP_Y, BOTTOM_Y = 122.0, 326.0         # centro das vagas de cima e de baixo
SPOTS = {1: [(x, TOP_Y) for x in (48, 104, 160, 216, 272)] + [(x, BOTTOM_Y) for x in (48, 104, 160)],
         2: [(x, TOP_Y) for x in (450, 520, 590, 660)] + [(x, BOTTOM_Y) for x in (450, 520, 590, 660)]}


@dataclass
class Car:
    s: float                  # frente do carro na pista (px) enquanto esta na entrada/saida
    state: str                # chegando, entrando, dentro, estacionado, voltando, saindo, partindo, desistindo
    color: str
    wait_ms: int = 0
    pressed_ms: int = -1
    spot: tuple[int, int] | None = None
    leave_at_ms: int = 0
    x: float = 0.0
    y: float = 0.0
    angle: float = 0.0        # graus, 0 = para a direita
    floor: int = 1
    path: list[tuple[float, float]] = field(default_factory=list)
    searched: bool = False


@register
class ParkingEnvironment(Environment):
    id = "estacionamento"
    name = "Estacionamento de dois pisos"
    description = ("16 vagas em dois pisos ligados por uma rampa. O motorista para no laço de entrada e aperta o "
                   "ticket; a cancela abre só com vaga e fecha depois que o carro sai do laço. Na saída ele valida "
                   "o cartão. Na rampa há dois laços: A (lado do piso 1) e B (lado do piso 2) — A antes de B é um "
                   "carro subindo, B antes de A, descendo. O programa mantém as vagas livres em N0 (total), N1 (piso "
                   "1) e N2 (piso 2), mostradas nos painéis (nunca negativas: um carro do piso 2 a caminho da saída passa pelo piso 1). Com PISO 1 LOTADO (Q0.4) aceso os motoristas sobem "
                   "direto; sem ele, quem não acha vaga roda o piso 1 procurando.")
    example = "ambientes/estacionamento.ladproj"
    size = (720, 470)
    inputs = [
        IOPoint("TICKET", "I0.0", "Botao_Ticket", "Botão do ticket na entrada", BUTTON),
        IOPoint("LACO_E", "I0.1", "Laco_Entrada", "Laço detector sob a cancela de entrada"),
        IOPoint("VALIDA", "I0.2", "Cartao_Validado", "Cartão validado na saída", BUTTON),
        IOPoint("LACO_S", "I0.3", "Laco_Saida", "Laço detector sob a cancela de saída"),
        IOPoint("ZERAR", "I0.4", "Zerar_Contagem", "Botão de manutenção: zera a contagem", BUTTON),
        IOPoint("LACO_A", "I0.5", "Rampa_Laco_A", "Rampa: laço A (lado do piso 1)"),
        IOPoint("LACO_B", "I0.6", "Rampa_Laco_B", "Rampa: laço B (lado do piso 2)"),
    ]
    outputs = [
        IOPoint("CANC_E", "Q0.0", "Cancela_Entrada", "Abre a cancela de entrada"),
        IOPoint("CANC_S", "Q0.1", "Cancela_Saida", "Abre a cancela de saída"),
        IOPoint("LIVRE", "Q0.2", "Painel_Livre", "Painel LIVRE (verde)"),
        IOPoint("LOTADO", "Q0.3", "Painel_Lotado", "Painel LOTADO (vermelho)"),
        IOPoint("PISO1", "Q0.4", "Piso1_Lotado", "Painel PISO 1 LOTADO: suba para o piso 2"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(11)
        self.auto = getattr(self, "auto", True)
        self.cars: list[Car] = []
        self.spots: dict[tuple[int, int], Car | None] = {(f, k): None for f in (1, 2) for k in range(PER_FLOOR)}
        self.gate = {"CANC_E": 0.0, "CANC_S": 0.0}
        self.next_arrival_ms = 500
        self.inside = 0
        self.occ = {1: 0, 2: 0}
        self.displayed: dict = {"total": None, 1: None, 2: None}
        self.n_words = 64
        self.mismatch_ms = 0
        self.mismatch_seen: tuple[str, int, int] | None = None
        self.entered = self.left = self.gave_up = 0
        self.searches = 0
        self.overfull = 0
        self.gate_hit = False
        self.both_lamps_ms = 0
        self.ramp_up = self.ramp_down = 0
        self._driver_press: dict[str, int] = {}

    def configure(self, n_inputs: int, n_outputs: int, n_words: int) -> bool:
        self.n_words = n_words
        return False

    def advance_words(self, n: list[int]) -> None:
        self.displayed = {k: (n[w] if len(n) > w else None) for k, w in WORDS.items()}

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.auto = not self.auto
        elif key == "CHEGAR":
            self._arrive()

    def press(self, key: str, down: bool) -> None:
        if key in ("AUTO", "CHEGAR"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _arrive(self) -> None:
        queue = [c for c in self.cars if c.state == "chegando"]
        if len(queue) < 3:
            self.cars.append(Car(-30.0 - 50 * len(queue), "chegando",
                                 self.rng.choice(["#2563eb", "#dc2626", "#16a34a", "#7c3aed", "#0891b2",
                                                  "#ea580c", "#be123c", "#4d7c0f", "#f8fafc", "#facc15"])))

    def _driver(self, key: str) -> None:
        """O motorista aperta o botao por 0,3 s."""
        self.operator[key] = True
        self.clicked.add(key)
        self._driver_press[key] = self.time_ms + 300

    def _on_loop(self, loop: tuple[float, float], lane: tuple[str, ...]) -> bool:
        return any(c.state in lane and c.s >= loop[0] and c.s - CAR_PX <= loop[1] for c in self.cars)

    # --------------------------------------------------------- dentro do patio
    def _free(self, floor: int) -> list[tuple[int, int]]:
        return [k for k, c in self.spots.items() if k[0] == floor and c is None]

    @staticmethod
    def _spot_xy(spot: tuple[int, int]) -> tuple[float, float]:
        floor, k = spot
        return SPOTS[floor][k]

    def _route_to(self, car: Car, spot: tuple[int, int], via_search: bool = False) -> None:
        self.spots[spot] = car
        car.spot = spot
        sx, sy = self._spot_xy(spot)
        path = [(TURN_IN, AISLE_Y)]
        if via_search:
            path += [(30, AISLE_Y), (300, AISLE_Y)]
        if spot[0] == 2:
            path += [(RAMP[1] + 20, AISLE_Y)]
        path += [(sx, AISLE_Y), (sx, sy)]
        car.path = path

    def _decide(self, car: Car) -> None:
        """O motorista chega ao corredor do piso 1 e escolhe para onde ir."""
        free1, free2 = self._free(1), self._free(2)
        if self.out.get("PISO1") and free2:
            self._route_to(car, self.rng.choice(free2))
        elif free1:
            self._route_to(car, self.rng.choice(free1))
        elif free2:                                   # rodou o piso 1 procurando e subiu
            car.searched = True
            self.searches += 1
            self._route_to(car, self.rng.choice(free2), via_search=True)
        else:
            car.path = [(TURN_IN, AISLE_Y), (30, AISLE_Y), (300, AISLE_Y), (TURN_IN, AISLE_Y)]

    def _ramp_busy(self, me: Car) -> bool:
        return any(c is not me and c.state in ("dentro", "voltando") and RAMP[0] - 10 <= c.x <= RAMP[1] + 10
                   and abs(c.y - AISLE_Y) < 20 for c in self.cars)

    def _move(self, car: Car, dt: float) -> bool:
        """Anda pelo caminho; True quando chegou ao fim."""
        dist = INSIDE_SPEED * dt
        while dist > 0 and car.path:
            tx, ty = car.path[0]
            enters_ramp = not (RAMP[0] - 10 <= car.x <= RAMP[1] + 10) and min(car.x, tx) < RAMP[1] and \
                max(car.x, tx) > RAMP[0] and abs(car.y - AISLE_Y) < 1
            if enters_ramp and self._ramp_busy(car):
                return False
            dx, dy = tx - car.x, ty - car.y
            d = math.hypot(dx, dy)
            if d > 1e-6:
                car.angle = math.degrees(math.atan2(dy, dx))
            if d <= dist:
                old_x = car.x
                car.x, car.y = tx, ty
                car.path.pop(0)
                dist -= d
            else:
                old_x = car.x
                car.x += dx / d * dist
                car.y += dy / d * dist
                dist = 0
            if abs(car.y - AISLE_Y) < 1:
                if old_x < RAMP_MID <= car.x:
                    self._change_floor(car, 2)
                elif old_x > RAMP_MID >= car.x:
                    self._change_floor(car, 1)
        return not car.path

    def _change_floor(self, car: Car, floor: int) -> None:
        if car.floor != floor:
            self.occ[car.floor] -= 1
            self.occ[floor] += 1
            car.floor = floor
            if floor == 2:
                self.ramp_up += 1
            else:
                self.ramp_down += 1

    def _ramp_loop(self, loop: tuple[float, float]) -> bool:
        for c in self.cars:
            if c.state not in ("dentro", "voltando") or abs(c.y - AISLE_Y) > 12:
                continue
            ca = math.radians(c.angle)
            tail = c.x - math.cos(ca) * CAR_PX
            if min(c.x, tail) <= loop[1] and max(c.x, tail) >= loop[0]:
                return True
        return False

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        for key, until in list(self._driver_press.items()):
            if now >= until:
                self.operator[key] = False
                del self._driver_press[key]
        for key in ("CANC_E", "CANC_S"):
            target = 1.0 if out[key] else 0.0
            old = self.gate[key]
            self.gate[key] = min(1.0, old + dt / GATE_S) if target > old else max(0.0, old - dt / GATE_S)
            arm = ENTRY_ARM if key == "CANC_E" else EXIT_ARM
            lane = ("chegando", "entrando", "desistindo") if key == "CANC_E" else ("saindo", "partindo")
            if self.gate[key] < old and self.gate[key] < 0.6 and \
                    any(c.state in lane and c.s >= arm and c.s - CAR_PX <= arm for c in self.cars):
                self.gate_hit = True
        if self.auto and now >= self.next_arrival_ms:
            self._arrive()
            self.next_arrival_ms = now + int(self.rng.uniform(2500, 6500))
        self.both_lamps_ms = self.both_lamps_ms + dt_ms if (out["LIVRE"] and out["LOTADO"]) else 0
        step = LANE_SPEED * dt
        # ---- pista de entrada
        entry_queue = sorted((c for c in self.cars if c.state == "chegando"), key=lambda c: -c.s)
        entry_busy = self.gate["CANC_E"] > 0.05 or any(
            c.state == "entrando" and c.s - CAR_PX <= ENTRY_LOOP[1] + 8 for c in self.cars)
        for k, car in enumerate(entry_queue):
            head_limit = ENTRY_STOP if (not entry_busy or car.s > ENTRY_WAIT) else ENTRY_WAIT
            limit = head_limit if k == 0 else entry_queue[k - 1].s - CAR_PX - 10
            if k == 0 and self.gate["CANC_E"] >= 0.9 and car.s >= ENTRY_STOP - 0.5:
                car.state = "entrando"
                continue
            car.s = min(limit, car.s + step)
            if k == 0 and car.s >= ENTRY_STOP - 0.5:
                car.wait_ms += dt_ms
                if car.wait_ms >= 1000 and (car.pressed_ms < 0 or now - car.pressed_ms >= 3000):
                    car.pressed_ms = now
                    self._driver("TICKET")
                if car.wait_ms >= GIVE_UP_MS:
                    car.state = "desistindo"
                    self.gave_up += 1
        for car in list(self.cars):
            if car.state == "entrando":
                was_on = car.s - CAR_PX <= ENTRY_LOOP[1] + 8
                car.s = min(TURN_IN, car.s + step)
                if was_on and car.s - CAR_PX > ENTRY_LOOP[1] + 8:     # saiu de cima do laco: esta dentro
                    if self.inside >= CAPACITY:
                        self.overfull += 1
                    self.inside += 1
                    self.occ[1] += 1
                    self.entered += 1
                if car.s >= TURN_IN:
                    car.state, car.x, car.y, car.angle, car.floor = "dentro", TURN_IN, LANE_Y, -90.0, 1
                    car.path = [(TURN_IN, AISLE_Y)]
            elif car.state == "dentro":
                if car.spot is None and car.y <= AISLE_Y + 0.5 and abs(car.x - TURN_IN) < 1 and len(car.path) == 0:
                    self._decide(car)
                if self._move(car, dt):
                    if car.spot is None:
                        self._decide(car)
                    else:
                        car.state = "estacionado"
                        car.leave_at_ms = now + int(self.rng.uniform(50000, 110000))
            elif car.state == "desistindo":
                car.s -= step
            elif car.state == "estacionado" and now >= car.leave_at_ms:
                sx, sy = car.x, car.y
                path = [(sx, AISLE_Y)]
                if car.spot[0] == 2:
                    path += [(RAMP[1] + 20, AISLE_Y)]
                path += [(TURN_OUT, AISLE_Y), (TURN_OUT, LANE_Y)]
                self.spots[car.spot] = None
                car.state, car.path = "voltando", path
            elif car.state == "voltando":
                at_end = not car.path
                if at_end or self._move(car, dt):
                    blocked = any(c.state == "saindo" and c.s < TURN_OUT + CAR_PX + 12 for c in self.cars)
                    if not blocked:
                        car.state, car.s, car.wait_ms, car.pressed_ms = "saindo", TURN_OUT, 0, -1
        # ---- pista de saida
        exit_queue = sorted((c for c in self.cars if c.state == "saindo"), key=lambda c: -c.s)
        exit_busy = self.gate["CANC_S"] > 0.05 or any(
            c.state == "partindo" and c.s - CAR_PX <= EXIT_LOOP[1] + 8 for c in self.cars)
        for k, car in enumerate(exit_queue):
            if k == 0 and self.gate["CANC_S"] >= 0.9 and car.s >= EXIT_STOP - 0.5:
                car.state = "partindo"
                continue
            head_limit = EXIT_STOP if (not exit_busy or car.s > EXIT_WAIT) else EXIT_WAIT
            limit = head_limit if k == 0 else exit_queue[k - 1].s - CAR_PX - 10
            car.s = max(car.s, min(limit, car.s + step))
            if k == 0 and car.s >= EXIT_STOP - 0.5:
                car.wait_ms += dt_ms
                if car.wait_ms >= 1000 and (car.pressed_ms < 0 or now - car.pressed_ms >= 3000):
                    car.pressed_ms = now
                    self._driver("VALIDA")
        for car in self.cars:
            if car.state == "partindo":
                was_on = car.s - CAR_PX <= EXIT_LOOP[1] + 8
                car.s += step
                if was_on and car.s - CAR_PX > EXIT_LOOP[1] + 8:
                    self.inside -= 1
                    self.occ[car.floor] -= 1
                    self.left += 1
        self.cars = [c for c in self.cars if not (c.state == "partindo" and c.s > 760)
                     and not (c.state == "desistindo" and c.s < -60)]
        # ---- paineis
        real = {"total": CAPACITY - self.inside, 1: max(0, PER_FLOOR - self.occ[1]), 2: max(0, PER_FLOOR - self.occ[2])}
        wrong = next((k for k in real if self.displayed[k] is not None and self.displayed[k] != real[k]), None)
        self.mismatch_ms = self.mismatch_ms + dt_ms if wrong is not None else 0
        if self.mismatch_ms > MISMATCH_MS and self.mismatch_seen is None:
            self.mismatch_seen = ({"total": "N0", 1: "N1", 2: "N2"}[wrong], self.displayed[wrong], real[wrong])

    def sensors(self) -> dict[str, bool]:
        return {"LACO_E": self._on_loop(ENTRY_LOOP, ("chegando", "entrando", "desistindo")),
                "LACO_S": self._on_loop(EXIT_LOOP, ("saindo", "partindo")),
                "LACO_A": self._ramp_loop(LOOP_A), "LACO_B": self._ramp_loop(LOOP_B)}

    def alarms(self) -> list[str]:
        out = []
        if self.overfull:
            out.append("Entrou carro com o estacionamento lotado: abra a cancela só se houver vaga")
        if self.gate_hit:
            out.append("A cancela desceu sobre um carro: espere o laço liberar")
        if self.mismatch_seen is not None:
            word, shown, real = self.mismatch_seen
            out.append(f"Contagem errada: o painel ({word}) mostrou {shown} vaga(s) quando havia {real}")
        if self.searches:
            out.append(f"{self.searches} motorista(s) rodaram o piso 1 lotado procurando vaga: acenda PISO 1 "
                       "LOTADO (Q0.4)")
        if self.both_lamps_ms > 0:
            out.append("LIVRE e LOTADO acesos ao mesmo tempo")
        return out

    def stats(self) -> list[str]:
        def show(k):
            return "--" if self.displayed[k] is None else str(self.displayed[k])
        info = [f"Carros: piso 1 {self.occ[1]}, piso 2 {self.occ[2]} ({self.inside}/{CAPACITY}) | painéis: N0 "
                f"{show('total')}, N1 {show(1)}, N2 {show(2)}",
                f"Entraram: {self.entered} | saíram: {self.left} | desistiram: {self.gave_up} | rampa: "
                f"{self.ramp_up} subidas, {self.ramp_down} descidas"]
        if self.n_words <= WORDS[2]:
            info.append("Os painéis precisam dos registradores N0 a N2: escolha um controlador com registradores N.")
        return info

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"CHEGAR": (14, 14, 120, 26), "AUTO": (140, 14, 140, 26), "ZERAR": (586, 14, 120, 26)}

    def _car(self, p: QPainter, x: float, y: float, angle: float, color: str) -> None:
        p.save()
        p.translate(x, y)
        p.rotate(angle)
        body = QRectF(-CAR_PX + 2, -11, CAR_PX - 4, 22)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(15, 23, 42, 60))
        p.drawRoundedRect(body.translated(2, 2), 6, 6)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor(color))
        p.drawRoundedRect(body, 6, 6)
        p.setBrush(QColor(15, 23, 42, 160))
        p.drawRoundedRect(QRectF(-12, -8, 7, 16), 2, 2)
        p.drawRoundedRect(QRectF(-CAR_PX + 6, -8, 5, 16), 2, 2)
        p.setBrush(QColor("#fef9c3"))
        p.drawEllipse(QPointF(-3, -7), 1.8, 1.8)
        p.drawEllipse(QPointF(-3, 7), 1.8, 1.8)
        p.restore()

    def _board(self, p: QPainter, rect: QRectF, title: str, key, word: str) -> None:
        shown = "--" if self.displayed[key] is None else str(self.displayed[key])
        draw.lcd(p, rect, shown, "#fbbf24", f"{title} ({word})")

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 470, "#e2e8f0", "#cbd5e1")
        sens = self.sensors()
        # pisos
        for floor, rect, title in ((1, QRectF(12, 48, 324, 334), "PISO 1 (térreo)"),
                                   (2, QRectF(394, 48, 314, 334), "PISO 2 (superior)")):
            draw.shadow(p, rect, 6, 4)
            p.setPen(QPen(QColor("#334155"), 1.5))
            p.setBrush(QColor("#9ca3af") if floor == 1 else QColor("#a8b3c2"))
            p.drawRoundedRect(rect, 6, 6)
            draw.text(p, rect.left() + 8, rect.top() + 16, title, 8, True, QColor("#1e293b"))
            p.fillRect(QRectF(rect.left() + 4, AISLE_Y - 22, rect.width() - 8, 44), QColor("#6b7280"))
            p.setPen(QPen(QColor("#fde68a"), 1.5, Qt.DashLine))
            p.drawLine(QPointF(rect.left() + 10, AISLE_Y), QPointF(rect.right() - 10, AISLE_Y))
            for k in range(PER_FLOOR):
                sx, sy = self._spot_xy((floor, k))
                r = QRectF(sx - 25, sy - 38, 50, 76)
                p.setPen(QPen(draw.WHITE, 2))
                p.setBrush(Qt.NoBrush)
                p.drawLine(r.topLeft(), r.bottomLeft())
                p.drawLine(r.topRight(), r.bottomRight())
                bottom_row = sy > AISLE_Y
                p.drawLine(r.topLeft() if bottom_row else r.bottomLeft(), r.topRight() if bottom_row else r.bottomRight())
                if self.spots[(floor, k)] is None:
                    draw.ctext(p, sx, sy, "P", 12, True, QColor(255, 255, 255, 90), 30)
        # rampa
        ramp = QRectF(RAMP[0] - 2, AISLE_Y - 22, RAMP[1] - RAMP[0] + 4, 44)
        p.fillRect(ramp, QColor("#57534e"))
        p.setPen(QPen(QColor("#a8a29e"), 2))
        for x in range(int(RAMP[0]), int(RAMP[1]), 8):
            p.drawLine(QPointF(x, AISLE_Y - 20), QPointF(x + 6, AISLE_Y + 20))
        draw.ctext(p, (RAMP[0] + RAMP[1]) / 2, AISLE_Y - 34, "RAMPA", 7, True, draw.MUTED, 60)
        for loop, key, addr, dy in ((LOOP_A, "LACO_A", "I0.5 A", 40), (LOOP_B, "LACO_B", "I0.6 B", 62)):
            p.setPen(QPen(QColor("#f59e0b") if sens[key] else QColor("#e5e7eb"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(loop[0], AISLE_Y - 18, loop[1] - loop[0], 36))
            draw.tag(p, loop[0] - 10, AISLE_Y + dy, addr, sens[key])
        # pistas de entrada e saida
        p.fillRect(QRectF(0, LANE_Y - 20, 720, 40), QColor("#4b5563"))
        p.fillRect(QRectF(TURN_IN - 20, AISLE_Y, 40, LANE_Y - AISLE_Y), QColor("#6b7280"))
        p.fillRect(QRectF(TURN_OUT - 20, AISLE_Y, 40, LANE_Y - AISLE_Y), QColor("#6b7280"))
        p.setPen(QPen(QColor("#fde68a"), 1.5, Qt.DashLine))
        p.drawLine(QPointF(0, LANE_Y), QPointF(TURN_IN - 22, LANE_Y))
        p.drawLine(QPointF(TURN_OUT + 22, LANE_Y), QPointF(720, LANE_Y))
        for loop, key in ((ENTRY_LOOP, "LACO_E"), (EXIT_LOOP, "LACO_S")):
            p.setPen(QPen(QColor("#f59e0b") if sens[key] else QColor("#d1d5db"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(loop[0], LANE_Y - 15, loop[1] - loop[0], 30))
        # carros
        for car in self.cars:
            if car.state in ("chegando", "entrando", "desistindo", "saindo", "partindo"):
                self._car(p, car.s, LANE_Y, 180.0 if car.state == "desistindo" else 0.0, car.color)
            else:
                self._car(p, car.x, car.y, car.angle, car.color)
        # cancelas (vista de cima)
        for key, x, addr in (("CANC_E", ENTRY_ARM, "Q0.0"), ("CANC_S", EXIT_ARM, "Q0.1")):
            frac = self.gate[key]
            pivot = QPointF(x, LANE_Y + 24)
            ang = math.radians(90 * frac)
            tip = QPointF(pivot.x() + 46 * math.sin(ang), pivot.y() - 46 * math.cos(ang))
            p.setPen(QPen(QColor("#b91c1c"), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pivot, tip)
            p.setPen(QPen(draw.WHITE, 5, Qt.DotLine, Qt.FlatCap))
            p.drawLine(pivot, tip)
            draw.metal(p, QRectF(pivot.x() - 7, pivot.y() - 5, 14, 12), "#334155", 2)
            draw.tag(p, x + 12, LANE_Y + 40, f"{addr} {'aberta' if frac >= 0.9 else 'fechada'}", self.out.get(key, False))
        draw.tag(p, ENTRY_LOOP[0] - 70, LANE_Y + 40, "I0.1 laço", sens["LACO_E"])
        draw.tag(p, EXIT_LOOP[0] - 70, LANE_Y + 40, "I0.3 laço", sens["LACO_S"])
        draw.tag(p, 14, LANE_Y + 40, "I0.0 ticket", self.is_pressed("TICKET"))
        draw.tag(p, 560, LANE_Y + 40, "I0.2 cartão", self.is_pressed("VALIDA"))
        # paineis
        self._board(p, QRectF(290, 8, 100, 36), "VAGAS", "total", "N0")
        self._board(p, QRectF(150, 50, 74, 30), "PISO 1", 1, "N1")
        self._board(p, QRectF(560, 50, 74, 30), "PISO 2", 2, "N2")
        draw.lamp(p, QPointF(404, 18), 6, self.out.get("LIVRE", False), draw.GREEN)
        draw.text(p, 414, 18, "LIVRE Q0.2", 7, True, w=70)
        draw.lamp(p, QPointF(404, 36), 6, self.out.get("LOTADO", False), draw.RED)
        draw.text(p, 414, 36, "LOTADO Q0.3", 7, True, w=70)
        sign = QRectF(40, 244, 96, 30)
        on = self.out.get("PISO1", False)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(sign, 4, 4)
        draw.ctext(p, sign.center().x(), sign.top() + 10, "PISO 1 LOTADO", 6.5, True,
                   QColor("#f87171") if on else QColor("#3f3f46"), 96)
        draw.ctext(p, sign.center().x(), sign.top() + 22, "suba ➜ Q0.4", 6.5, True,
                   QColor("#fbbf24") if on else QColor("#3f3f46"), 96)
        draw.push_button(p, QRectF(14, 14, 120, 26), "Chegar carro", False, QColor("#2563eb"))
        draw.switch(p, QRectF(140, 14, 140, 26), "Fluxo automático", self.auto)
        draw.push_button(p, QRectF(586, 14, 120, 26), "ZERAR I0.4", self.is_pressed("ZERAR"), draw.AMBER)
