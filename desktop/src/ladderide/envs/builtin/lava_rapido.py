"""Lava-rapido de portico: receitas como mascara de bits, passadas do portico e conferencia do servico pago."""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..registry import register

TRAVEL_S = 5.0                # o portico percorre o carro em 5 s
PROGRAMS = {1: ("Simples", 15.0), 2: ("Completo", 25.0), 3: ("Premium", 35.0)}
PASSES = [("Pré-lavagem", frozenset({"AGUA"})), ("Shampoo e escovas", frozenset({"AGUA", "SHAMPOO", "ESCOVAS"})),
          ("Enxágue", frozenset({"AGUA"})), ("Cera", frozenset({"CERA"})), ("Secagem", frozenset({"SECADOR"})),
          ("Secagem 2", frozenset({"SECADOR"}))]
MASKS = {1: 0b000111, 2: 0b010111, 3: 0b111111}
ACTIONS = ("AGUA", "SHAMPOO", "ESCOVAS", "CERA", "SECADOR")
CAR_SPEED = 60.0              # px/s
STOP_X, PORTAL_X0, PORTAL_X1 = 360.0, 210.0, 460.0
PROGRAM_WORD = 0


@register
class CarWashEnvironment(Environment):
    id = "lava_rapido"
    name = "Lava-rápido de pórtico"
    description = ("O carro entra com o semáforo verde (Q0.7) e para na posição (I0.1). O cliente paga e escolhe o "
                   "programa: o código vai para N0 (1 Simples, 2 Completo, 3 Premium) e I0.0 dá um pulso. Cada "
                   "programa é uma lista de passadas do pórtico (5 s de uma ponta à outra): 1 pré-lavagem (água), 2 "
                   "shampoo com escovas (e água), 3 enxágue, 4 cera, 5 e 6 secagem. Simples = 1+2+3, Completo = "
                   "1+2+3+5, Premium = todas. Depois o pórtico volta à origem e o verde libera a saída. O ambiente "
                   "confere se o carro recebeu exatamente o que foi pago. Escovas a seco riscam a pintura.")
    example = "ambientes/lava_rapido.ladproj"
    size = (720, 420)
    inputs = [
        IOPoint("PAGO", "I0.0", "Pagamento_OK", "Pulso: pagamento aprovado (programa em N0)"),
        IOPoint("POSICAO", "I0.1", "Carro_Posicionado", "Carro parado na posição de lavagem"),
        IOPoint("ORIGEM", "I0.2", "Portico_Origem", "Pórtico na origem (frente do carro)"),
        IOPoint("FIM", "I0.3", "Portico_Fim", "Pórtico no fim (traseira do carro)"),
        IOPoint("EMERG", "I0.4", "Emergencia", "Emergência com trava (NF)", SWITCH, normally_closed=True),
    ]
    outputs = [
        IOPoint("FRENTE", "Q0.0", "Portico_Avanca", "Pórtico: avança (para a traseira)"),
        IOPoint("TRAS", "Q0.1", "Portico_Recua", "Pórtico: recua (para a frente)"),
        IOPoint("AGUA", "Q0.2", "Agua", "Bomba de água de alta pressão"),
        IOPoint("SHAMPOO", "Q0.3", "Shampoo", "Dosador de shampoo"),
        IOPoint("ESCOVAS", "Q0.4", "Escovas", "Motor das escovas"),
        IOPoint("CERA", "Q0.5", "Cera", "Aplicação de cera"),
        IOPoint("SECADOR", "Q0.6", "Secador", "Ventiladores de secagem"),
        IOPoint("VERDE", "Q0.7", "Semaforo_Verde", "Semáforo verde (vermelho desligado)"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(31)
        self.auto = getattr(self, "auto", True)
        self.portal = 0.0                 # 0 origem, 1 fim
        self.car_x: float | None = None
        self.car_state = ""
        self.car_color = "#2563eb"
        self.program = 0
        self.pay_ms = 0
        self.next_car_ms = 1000
        self.pending = 1                  # programa que o proximo cliente vai pagar
        self.passes: list[frozenset] = []
        self._travel: dict[str, int] = {}
        self._travel_ms = 0
        self._from = "ORIGEM"
        self.flags: dict[str, str] = {}
        self.washed = self.wrong = 0
        self.revenue = 0.0
        self.waste_ms = 0
        self.brush_angle = 0.0
        self.drops: list[list[float]] = []
        self.wetness = 0.0
        self.foam = 0.0
        self.shine = 0.0
        self._pay_at = 0

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def input_words(self) -> dict[int, int]:
        return {PROGRAM_WORD: self.program}

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.auto = not self.auto
        elif key == "CARRO" and self.car_x is None:
            self._new_car()
        elif key in ("P1", "P2", "P3"):
            self.pending = int(key[1])
            if self.car_state == "posicionado" and self.program == 0:
                self._pay(self.pending)

    def press(self, key: str, down: bool) -> None:
        if key in ("AUTO", "CARRO", "P1", "P2", "P3"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _new_car(self) -> None:
        self.car_x = -180.0
        self.car_state = "chegando"
        self.car_color = self.rng.choice(["#dc2626", "#2563eb", "#16a34a", "#f8fafc", "#facc15", "#111827"])
        self.passes = []
        self.wetness = self.foam = self.shine = 0.0

    def _pay(self, prog: int) -> None:
        self.program = prog
        self.pay_ms = 300
        self.revenue += PROGRAMS[prog][1]

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        self.pay_ms = max(0, self.pay_ms - dt_ms)
        if self.auto and self.car_x is None and now >= self.next_car_ms:
            self._new_car()
            self.pending = self.rng.choice([1, 2, 3])
        # portico
        fwd, back = out["FRENTE"], out["TRAS"]
        if fwd and back:
            self._flag("both", "Pórtico comandado para avançar e recuar ao mesmo tempo")
        moving = (fwd != back)
        if moving and self.is_pressed("EMERG"):
            self._flag("emerg", "Pórtico andou com a emergência acionada")
        if moving and self.car_x is not None and self.car_state != "posicionado" and self.car_state != "lavando":
            self._flag("hit", "Pórtico andou com o carro fora da posição")
        old = self.portal
        if fwd and not back:
            self.portal = min(1.0, self.portal + dt / TRAVEL_S)
        elif back and not fwd:
            self.portal = max(0.0, self.portal - dt / TRAVEL_S)
        active = {a for a in ACTIONS if out[a]}
        if out["ESCOVAS"] and not (out["AGUA"] or out["SHAMPOO"]):
            self._flag("dry", "Escovas girando sem água: riscam a pintura")
        stopped = self.portal == old
        self.waste_ms = self.waste_ms + dt_ms if (stopped and (out["AGUA"] or out["SHAMPOO"] or out["CERA"])) else 0
        if self.waste_ms > 3000:
            self._flag("waste", "Água ou produtos ligados com o pórtico parado (desperdício)")
        if self.car_x is None and active:
            self._flag("empty", "Lavagem ligada sem carro no box")
        # registro das passadas: viagem de uma ponta a outra e o que ficou ligado (>= 90% do tempo)
        if not stopped:
            if self.car_state == "posicionado" and self.program:
                self.car_state = "lavando"
            self._travel_ms += dt_ms
            for a in active:
                self._travel[a] = self._travel.get(a, 0) + dt_ms
        arrived = (old < 1.0 <= self.portal) or (old > 0.0 >= self.portal)
        if arrived:
            sig = frozenset(a for a, ms in self._travel.items() if ms >= 0.9 * self._travel_ms)
            if sig and self.car_x is not None:
                self.passes.append(sig)
            self._travel, self._travel_ms = {}, 0
        # efeitos (desenho)
        if out["ESCOVAS"]:
            self.brush_angle += 12 * dt
        if out["AGUA"]:
            self.wetness = min(1.0, self.wetness + dt)
        else:
            self.wetness = max(0.0, self.wetness - (0.4 if out["SECADOR"] else 0.02) * dt)
        self.foam = min(1.0, self.foam + dt) if out["SHAMPOO"] else max(0.0, self.foam - (0.6 if out["AGUA"] else 0) * dt)
        if out["CERA"]:
            self.shine = min(1.0, self.shine + 0.4 * dt)
        if active & {"AGUA", "SHAMPOO", "CERA", "SECADOR"} and self.rng.random() < 0.8:
            self.drops.append([0.0, self.rng.uniform(-1, 1)])
        self.drops = [[t + dt, x] for t, x in self.drops if t < 0.4][-60:]
        # carro e cliente
        green = out["VERDE"]
        if self.car_x is not None:
            if self.car_state == "chegando":
                if self.car_x < 40 or green:
                    self.car_x = min(STOP_X, self.car_x + CAR_SPEED * dt)
                    if self.car_x >= 120 and self.portal > 0.02:
                        self._flag("enter", "Semáforo verde com o pórtico fora da origem: o carro bateu nele")
                if self.car_x >= STOP_X:
                    self.car_state = "posicionado"
                    self.pay_ms = 0
                    self._pay_at = now + 2000
            elif self.car_state == "posicionado" and self.program == 0 and now >= self._pay_at \
                    and self.auto:
                self._pay(self.pending)
            elif self.car_state in ("posicionado", "lavando") and green and self.program:
                expected = [PASSES[k][1] for k in range(6) if MASKS[self.program] >> k & 1]
                if self.passes == expected:
                    self.washed += 1
                else:
                    self.wrong += 1
                    self._flag("service", "O carro saiu sem receber exatamente o programa pago (passadas faltando, "
                                          "a mais ou fora de ordem)")
                if self.portal > 0.02:
                    self._flag("exit", "Semáforo verde com o pórtico fora da origem")
                self.car_state = "saindo"
            elif self.car_state == "saindo":
                self.car_x += CAR_SPEED * dt
                if self.car_x > 900:
                    self.car_x = None
                    self.car_state = ""
                    self.program = 0
                    self.next_car_ms = now + 3000

    def sensors(self) -> dict[str, bool]:
        return {"PAGO": self.pay_ms > 0, "POSICAO": self.car_state in ("posicionado", "lavando"),
                "ORIGEM": self.portal <= 0.0, "FIM": self.portal >= 1.0}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        name = PROGRAMS[self.program][0] if self.program else "-"
        return [f"Programa N0 = {self.program} ({name}) | passadas feitas: {len(self.passes)} | pórtico "
                f"{self.portal * 100:.0f}%",
                f"Carros lavados: {self.washed} | serviço errado: {self.wrong} | caixa R$ {self.revenue:.2f}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"P1": (520, 300, 190, 26), "P2": (520, 330, 190, 26), "P3": (520, 360, 190, 26),
                "CARRO": (14, 380, 130, 28), "AUTO": (150, 380, 150, 28), "EMERG": (306, 380, 160, 28)}

    def _car(self, p: QPainter, x: float) -> None:
        y = 300
        body = QRectF(x - 170, y - 34, 170, 34)
        c = QColor(self.car_color)
        if self.wetness > 0:
            c = draw.mix(c, c.darker(140), self.wetness * 0.5)
        p.setPen(QPen(QColor("#0f172a"), 1.2))
        p.setBrush(c)
        p.drawRoundedRect(body, 10, 10)
        roof = QRectF(x - 130, y - 62, 90, 32)
        p.drawRoundedRect(roof, 10, 10)
        p.setBrush(QColor(186, 230, 253, 200))
        p.drawRoundedRect(roof.adjusted(8, 6, -8, -4), 4, 4)
        for wx in (x - 140, x - 36):
            p.setBrush(QColor("#111827"))
            p.drawEllipse(QPointF(wx, y), 16, 16)
            p.setBrush(QColor("#9ca3af"))
            p.drawEllipse(QPointF(wx, y), 7, 7)
        if self.foam > 0.05:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, int(200 * self.foam)))
            for k in range(14):
                p.drawEllipse(QPointF(x - 160 + k * 12, y - 34 - (k % 3) * 4), 8, 6)
        if self.shine > 0.1:
            p.setPen(QPen(QColor(255, 255, 255, int(200 * self.shine)), 2))
            p.drawLine(QPointF(x - 150, y - 26), QPointF(x - 60, y - 26))

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 420)
        draw.ground(p, 316, 720, 420)
        out = self.out
        sens = self.sensors()
        # box (trilhos do portico)
        p.setPen(QPen(QColor("#475569"), 4))
        p.drawLine(QPointF(PORTAL_X0 - 40, 120), QPointF(PORTAL_X1 + 40, 120))
        if self.car_x is not None:
            self._car(p, self.car_x)
        # portico
        px = PORTAL_X0 + (PORTAL_X1 - PORTAL_X0) * self.portal
        for x in (px - 46, px + 46):
            draw.metal(p, QRectF(x - 6, 120, 12, 196), "#1d4ed8", 2, vertical=True)
        draw.metal(p, QRectF(px - 56, 110, 112, 18), "#1e3a8a", 4)
        # escova (vista de lado: rolo)
        brush = QRectF(px - 16, 140, 32, 150)
        p.setPen(QPen(QColor("#1e293b"), 1))
        p.setBrush(QColor("#7c3aed") if out.get("ESCOVAS") else QColor("#a78bfa"))
        p.drawRoundedRect(brush, 12, 12)
        p.setPen(QPen(QColor(255, 255, 255, 120), 2))
        for k in range(8):
            yy = brush.top() + ((k * 20 + self.brush_angle * 30) % brush.height())
            p.drawLine(QPointF(brush.left() + 3, yy), QPointF(brush.right() - 3, yy + 4))
        # jatos
        col = QColor("#38bdf8")
        if out.get("SHAMPOO"):
            col = QColor("#f0abfc")
        if out.get("CERA"):
            col = QColor("#fbbf24")
        if out.get("SECADOR"):
            col = QColor(255, 255, 255, 160)
        p.setPen(Qt.NoPen)
        for t, x in self.drops:
            p.setBrush(col)
            p.drawEllipse(QPointF(px + x * 40, 130 + t * 400), 2.5, 3.5)
        # semaforo
        post = QRectF(60, 140, 22, 46)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(post, 5, 5)
        draw.lamp(p, QPointF(71, 152), 7, not out.get("VERDE", False), draw.RED)
        draw.lamp(p, QPointF(71, 174), 7, bool(out.get("VERDE")), draw.GREEN)
        draw.metal(p, QRectF(69, 186, 4, 130), "#475569", 1, vertical=True)
        draw.tag(p, 88, 160, "Q0.7 verde", out.get("VERDE", False))
        # sensores
        draw.tag(p, PORTAL_X0 - 60, 100, "I0.2 origem", sens["ORIGEM"])
        draw.tag(p, PORTAL_X1 - 20, 100, "I0.3 fim", sens["FIM"])
        draw.beam(p, QPointF(STOP_X + 4, 250), QPointF(STOP_X + 4, 316), sens["POSICAO"])
        draw.tag(p, STOP_X + 10, 236, "I0.1 posição", sens["POSICAO"])
        # saidas
        draw.card(p, QRectF(8, 8, 300, 84), "Pórtico")
        labels = [("Q0.0 avança", "FRENTE"), ("Q0.1 recua", "TRAS"), ("Q0.2 água", "AGUA"), ("Q0.3 shampoo", "SHAMPOO"),
                  ("Q0.4 escovas", "ESCOVAS"), ("Q0.5 cera", "CERA"), ("Q0.6 secador", "SECADOR")]
        for k, (label, key) in enumerate(labels):
            draw.tag(p, 16 + (k % 3) * 98, 40 + (k // 3) * 20, label, out.get(key, False))
        # terminal de pagamento
        draw.card(p, QRectF(512, 8, 200, 404), "Terminal de pagamento")
        prog = self.program
        draw.lcd(p, QRectF(522, 36, 180, 36), PROGRAMS[prog][0] if prog else "--", "#4ade80", "N0 programa")
        draw.tag(p, 522, 86, "I0.0 pago", sens["PAGO"])
        draw.text(p, 522, 110, "Passadas", 7.5, True, draw.MUTED, w=180)
        needed = [k for k in range(6) if prog and MASKS[prog] >> k & 1]
        for k, (name, _) in enumerate(PASSES):
            y = 128 + k * 22
            draw.text(p, 522, y, f"{k + 1}. {name}", 7.5, True, draw.INK if k in needed else QColor("#cbd5e1"), w=150)
            if k in needed:
                draw.lamp(p, QPointF(694, y), 5, needed.index(k) < len(self.passes), draw.GREEN)
        for k, key in enumerate(("P1", "P2", "P3")):
            name, price = PROGRAMS[k + 1]
            draw.push_button(p, QRectF(520, 300 + k * 30, 190, 26), f"{name}  R$ {price:.0f}",
                             self.pending == k + 1, draw.BLUE if self.pending == k + 1 else QColor("#94a3b8"))
        draw.text(p, 522, 398, f"Lavados {self.washed} | errados {self.wrong}", 7.5, True, w=180)
        draw.push_button(p, QRectF(14, 380, 130, 28), "Chegar carro", False, draw.BLUE)
        draw.switch(p, QRectF(150, 380, 150, 28), "Clientes automáticos", self.auto)
        draw.switch(p, QRectF(306, 380, 160, 28), "EMERGÊNCIA I0.4", self.is_pressed("EMERG"))
