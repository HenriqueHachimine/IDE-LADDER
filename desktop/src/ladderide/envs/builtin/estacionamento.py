"""Estacionamento com cancelas, lacos detectores e painel de vagas (contagem nos registradores N)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..registry import register

CAPACITY = 12
VAGAS_WORD = 0                    # N0: vagas livres calculadas pelo programa (mostradas no painel)
LANE_SPEED = 110.0                # px/s nas pistas
CAR_PX = 40.0
GATE_S = 1.0                      # cancela sobe/desce em 1 s
ENTRY_ARM, EXIT_ARM = 180.0, 480.0
ENTRY_STOP, EXIT_STOP = 172.0, 472.0
ENTRY_WAIT, EXIT_WAIT = 128.0, 428.0    # faixa de espera antes do laco (o proximo so avanca com o laco livre)
ENTRY_LOOP, EXIT_LOOP = (140.0, 212.0), (440.0, 512.0)
GIVE_UP_MS = 12000
MISMATCH_MS = 3000
LANE_Y = 330.0


@dataclass
class Car:
    s: float                  # frente do carro na pista (px)
    state: str                # chegando, entrando, estacionado, saindo, partindo, desistindo
    color: str
    wait_ms: int = 0
    pressed_ms: int = -1
    spot: int = -1
    leave_at_ms: int = 0


@register
class ParkingEnvironment(Environment):
    id = "estacionamento"
    name = "Estacionamento com contagem de vagas"
    description = ("12 vagas. O motorista para no laço de entrada e aperta o botão do ticket; a cancela deve abrir "
                   "só se houver vaga e fechar depois que o carro sair de cima do laço. Na saída ele valida o "
                   "cartão. O programa conta os carros (entrada soma, saída subtrai) e escreve as vagas livres em "
                   "N0, mostradas no painel; LIVRE e LOTADO sinalizam a entrada. Com o estacionamento cheio o "
                   "motorista desiste depois de 12 s.")
    example = "ambientes/estacionamento.ladproj"
    inputs = [
        IOPoint("TICKET", "I0.0", "Botao_Ticket", "Botão do ticket na entrada", BUTTON),
        IOPoint("LACO_E", "I0.1", "Laco_Entrada", "Laço detector sob a cancela de entrada"),
        IOPoint("VALIDA", "I0.2", "Cartao_Validado", "Cartão validado na saída", BUTTON),
        IOPoint("LACO_S", "I0.3", "Laco_Saida", "Laço detector sob a cancela de saída"),
        IOPoint("ZERAR", "I0.4", "Zerar_Contagem", "Botão de manutenção: zera a contagem", BUTTON),
    ]
    outputs = [
        IOPoint("CANC_E", "Q0.0", "Cancela_Entrada", "Abre a cancela de entrada"),
        IOPoint("CANC_S", "Q0.1", "Cancela_Saida", "Abre a cancela de saída"),
        IOPoint("LIVRE", "Q0.2", "Painel_Livre", "Painel LIVRE (verde)"),
        IOPoint("LOTADO", "Q0.3", "Painel_Lotado", "Painel LOTADO (vermelho)"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(11)
        self.auto = getattr(self, "auto", True)
        self.cars: list[Car] = []
        self.spots: list[Car | None] = [None] * CAPACITY
        self.gate = {"CANC_E": 0.0, "CANC_S": 0.0}
        self.next_arrival_ms = 500
        self.inside = 0
        self.displayed: int | None = None
        self.n_words = 64
        self.mismatch_ms = 0
        self.mismatch_seen: tuple[int, int] | None = None
        self.entered = self.left = self.gave_up = 0
        self.overfull = 0
        self.gate_hit = False
        self.both_lamps_ms = 0
        self._driver_press: dict[str, int] = {}

    def configure(self, n_inputs: int, n_outputs: int, n_words: int) -> bool:
        self.n_words = n_words
        return False

    def advance_words(self, n: list[int]) -> None:
        self.displayed = n[VAGAS_WORD] if len(n) > VAGAS_WORD else None

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
        queue = [c for c in self.cars if c.state in ("chegando",)]
        if len(queue) < 3:
            self.cars.append(Car(-30.0 - 50 * len(queue), "chegando",
                                 self.rng.choice(["#2563eb", "#dc2626", "#16a34a", "#7c3aed", "#0891b2",
                                                  "#ea580c", "#be123c", "#4d7c0f"])))

    def _driver(self, key: str) -> None:
        """O motorista aperta o botao por 0,3 s."""
        self.operator[key] = True
        self.clicked.add(key)
        self._driver_press[key] = self.time_ms + 300

    def _on_loop(self, loop: tuple[float, float], lane: str) -> bool:
        return any(c.state in lane and c.s >= loop[0] and c.s - CAR_PX <= loop[1] for c in self.cars)

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
            self.next_arrival_ms = now + int(self.rng.uniform(3000, 8000))
        self.both_lamps_ms = self.both_lamps_ms + dt_ms if (out["LIVRE"] and out["LOTADO"]) else 0
        step = LANE_SPEED * dt
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
        for car in self.cars:
            if car.state == "entrando":
                car.s += step
                if car.s - CAR_PX > ENTRY_LOOP[1] + 8:          # saiu de cima do laco: esta dentro
                    if self.inside >= CAPACITY:
                        self.overfull += 1
                    self.inside += 1
                    self.entered += 1
                    free = [i for i, s in enumerate(self.spots) if s is None]
                    car.state = "estacionado"
                    if free:
                        car.spot = self.rng.choice(free)
                        self.spots[car.spot] = car
                    car.leave_at_ms = now + int(self.rng.uniform(40000, 90000))
            elif car.state == "desistindo":
                car.s -= step
            elif car.state == "estacionado" and now >= car.leave_at_ms:
                exiting = [c for c in self.cars if c.state == "saindo"]
                if len(exiting) < 2:
                    if car.spot >= 0:
                        self.spots[car.spot] = None
                    car.state, car.s, car.wait_ms, car.pressed_ms = "saindo", 360.0 - 50 * len(exiting), 0, -1
        exit_queue = sorted((c for c in self.cars if c.state == "saindo"), key=lambda c: -c.s)
        exit_busy = self.gate["CANC_S"] > 0.05 or any(
            c.state == "partindo" and c.s - CAR_PX <= EXIT_LOOP[1] + 8 for c in self.cars)
        for k, car in enumerate(exit_queue):
            if k == 0 and self.gate["CANC_S"] >= 0.9 and car.s >= EXIT_STOP - 0.5:
                car.state = "partindo"
                continue
            head_limit = EXIT_STOP if (not exit_busy or car.s > EXIT_WAIT) else EXIT_WAIT
            limit = head_limit if k == 0 else exit_queue[k - 1].s - CAR_PX - 10
            car.s = min(limit, car.s + step)
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
                    self.left += 1
        self.cars = [c for c in self.cars if not (c.state == "partindo" and c.s > 700)
                     and not (c.state == "desistindo" and c.s < -60)]
        real_free = CAPACITY - self.inside
        wrong = self.displayed is not None and self.displayed != real_free
        self.mismatch_ms = self.mismatch_ms + dt_ms if wrong else 0
        if self.mismatch_ms > MISMATCH_MS and self.mismatch_seen is None:
            self.mismatch_seen = (self.displayed, real_free)

    def sensors(self) -> dict[str, bool]:
        return {"LACO_E": self._on_loop(ENTRY_LOOP, ("chegando", "entrando", "desistindo")),
                "LACO_S": self._on_loop(EXIT_LOOP, ("saindo", "partindo"))}

    def alarms(self) -> list[str]:
        out = []
        if self.overfull:
            out.append("Entrou carro com o estacionamento lotado: abra a cancela só se houver vaga")
        if self.gate_hit:
            out.append("A cancela desceu sobre um carro: espere o laço liberar")
        if self.mismatch_seen is not None:
            shown, real = self.mismatch_seen
            out.append(f"Contagem errada: o painel (N0) mostrou {shown} vaga(s) quando havia {real}")
        if self.both_lamps_ms > 0:
            out.append("LIVRE e LOTADO acesos ao mesmo tempo")
        return out

    def stats(self) -> list[str]:
        shown = "--" if self.displayed is None else str(self.displayed)
        info = [f"Carros dentro: {self.inside}/{CAPACITY} | painel N0: {shown} vagas",
                f"Entraram: {self.entered} | saíram: {self.left} | desistiram (lotado): {self.gave_up}"]
        if self.n_words <= VAGAS_WORD:
            info.append("O painel precisa do registrador N0: escolha um controlador com registradores N.")
        return info

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"CHEGAR": (16, 380, 130, 28), "AUTO": (160, 380, 150, 28), "ZERAR": (494, 380, 130, 28)}

    def _car(self, p: QPainter, x: float, y: float, color: str, vertical: bool = False) -> None:
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor(color))
        r = QRectF(x, y, 22, CAR_PX - 4) if vertical else QRectF(x - CAR_PX, y - 11, CAR_PX - 4, 22)
        p.drawRoundedRect(r, 5, 5)
        p.setBrush(QColor("#bae6fd"))
        if vertical:
            p.drawRect(QRectF(x + 4, y + 6, 14, 7))
        else:
            p.drawRect(QRectF(x - 14, y - 7, 7, 14))

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#e5e7eb"))
        # patio e vagas
        p.fillRect(QRectF(150, 30, 360, 170), QColor("#9ca3af"))
        for k in range(CAPACITY):
            col, row = k % 6, k // 6
            r = QRectF(160 + col * 58, 40 + row * 82, 44, 66)
            p.setPen(QPen(draw.WHITE, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            car = self.spots[k]
            if car is not None:
                self._car(p, r.left() + 11, r.top() + 14, car.color, vertical=True)
        draw.text(p, 160, 22, f"Pátio: {self.inside} carro(s)", 8, True, draw.MUTED, w=200)
        # pistas
        p.fillRect(QRectF(0, LANE_Y - 18, 300, 36), QColor("#4b5563"))
        p.fillRect(QRectF(340, LANE_Y - 18, 300, 36), QColor("#4b5563"))
        p.setPen(QPen(QColor("#4b5563"), 30))
        p.drawLine(QPointF(270, LANE_Y), QPointF(270, 200))
        p.drawLine(QPointF(370, 200), QPointF(370, LANE_Y))
        for loop, key in ((ENTRY_LOOP, "LACO_E"), (EXIT_LOOP, "LACO_S")):
            on = self.sensors()[key]
            p.setPen(QPen(QColor("#f59e0b") if on else QColor("#d1d5db"), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(loop[0], LANE_Y - 14, loop[1] - loop[0], 28))
        for car in self.cars:
            if car.state in ("chegando", "entrando", "desistindo") and car.s < 300:
                self._car(p, car.s, LANE_Y, car.color)
            elif car.state in ("saindo", "partindo") and car.s > 340:
                self._car(p, car.s, LANE_Y, car.color)
        # cancelas (vista de cima): fechada atravessa a pista; aberta fica ao lado da pista
        for key, x, addr in (("CANC_E", ENTRY_ARM, "Q0.0"), ("CANC_S", EXIT_ARM, "Q0.1")):
            frac = self.gate[key]
            pivot = QPointF(x, LANE_Y + 22)
            ang = math.radians(90 * frac)
            tip = QPointF(pivot.x() + 44 * math.sin(ang), pivot.y() - 44 * math.cos(ang))
            p.setPen(QPen(QColor("#b91c1c"), 5, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(pivot, tip)
            p.setPen(QPen(draw.WHITE, 5, Qt.DotLine, Qt.FlatCap))
            p.drawLine(pivot, tip)
            p.setBrush(QColor("#1f2937"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(pivot, 4, 4)
            draw.tag(p, x - 18, LANE_Y + 40, f"{addr} {'aberta' if frac >= 0.9 else 'fechada'}",
                     self.out.get(key, False))
        draw.tag(p, ENTRY_LOOP[0], LANE_Y - 30, "I0.1 laço", self.sensors()["LACO_E"])
        draw.tag(p, EXIT_LOOP[0], LANE_Y - 30, "I0.3 laço", self.sensors()["LACO_S"])
        draw.tag(p, 40, LANE_Y - 30, "I0.0 ticket", self.is_pressed("TICKET"))
        draw.tag(p, EXIT_LOOP[1] + 14, LANE_Y - 30, "I0.2 cartão", self.is_pressed("VALIDA"))
        draw.text(p, 10, LANE_Y + 62, "entrada →", 8, True, draw.MUTED, w=90)
        draw.text(p, 560, LANE_Y + 62, "saída →", 8, True, draw.MUTED, w=80)
        # painel de vagas
        board = QRectF(16, 40, 120, 120)
        p.setPen(QPen(QColor("#111827"), 2))
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(board, 8, 8)
        draw.text(p, board.center().x(), board.top() + 16, "VAGAS", 8, True, QColor("#9ca3af"),
                  Qt.AlignHCenter | Qt.AlignVCenter, 100)
        shown = "--" if self.displayed is None else str(self.displayed)
        draw.text(p, board.center().x(), board.top() + 50, shown, 26, True, QColor("#fbbf24"),
                  Qt.AlignHCenter | Qt.AlignVCenter, 110, 44)
        draw.text(p, board.center().x(), board.top() + 76, "N0", 7, True, QColor("#9ca3af"),
                  Qt.AlignHCenter | Qt.AlignVCenter, 100)
        draw.lamp(p, QPointF(board.left() + 30, board.bottom() - 18), 9, self.out.get("LIVRE", False), draw.GREEN)
        draw.lamp(p, QPointF(board.right() - 30, board.bottom() - 18), 9, self.out.get("LOTADO", False), draw.RED)
        draw.text(p, 20, board.bottom() + 12, "LIVRE Q0.2", 7, True, w=60)
        draw.text(p, 76, board.bottom() + 12, "LOTADO Q0.3", 7, True, w=70)
        draw.push_button(p, QRectF(16, 380, 130, 28), "Chegar carro", False, QColor("#2563eb"))
        draw.switch(p, QRectF(160, 380, 150, 28), "Fluxo automático", self.auto)
        draw.push_button(p, QRectF(494, 380, 130, 28), "ZERAR  I0.4", self.is_pressed("ZERAR"), draw.AMBER)
