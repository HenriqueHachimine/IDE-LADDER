"""Dosagem por receita em balanca: tara, dois ingredientes, corte antecipado e rejeicao (registradores N)."""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import DelayLine, History, approach
from ..registry import register

COARSE, FINE, LIQUID = 300.0, 25.0, 40.0   # g/s: A grossa, A fina, B
VALVE_S = 0.1                     # valvulas abrem e fecham em 0,1 s
FALL_A, FALL_B = 0.3, 0.2         # tempo de queda do bico ao recipiente
FILTER_S = 0.1                    # filtro da celula de carga
STABLE_RATE, STABLE_MS = 3.0, 500     # estavel: menos de 3 g/s por 0,5 s
BELT_SPEED, BELT_ACCEL = 250.0, 4000.0  # mm/s e mm/s^2 (para em ~8 mm)
SPACING = 500.0                   # mm entre recipientes
SENSOR_MM = 12.0                  # janela do sensor de recipiente
SCALE_MM = 60.0                   # o recipiente esta sobre a balanca
REJECT_AT, REJECT_WIN = 250.0, 45.0   # estacao de rejeito (mm depois da balanca)
PUSH_S = 0.15
TARE = (40, 70)                   # peso do recipiente vazio (g)
RECIPES = {"R1": ("Receita 1", 400, 100), "R2": ("Receita 2", 250, 250), "R3": ("Receita 3", 800, 50)}
PESO_WORD, ALVO_A_WORD, ALVO_B_WORD = 0, 1, 2


def tolerance(target: float) -> float:
    """2% do alvo, no minimo 3 g."""
    return max(3.0, 0.02 * target)


class Can:
    def __init__(self, x: float, tare: float):
        self.x = x
        self.tare = tare
        self.a = 0.0
        self.b = 0.0
        self.cand_a: set[int] = set()         # receitas validas: ao parar sob o bico e quando o produto caiu
        self.cand_b: set[int] = set()
        self.good: bool | None = None
        self.rejected = False
        self.drop = 0.0           # animacao da queda no rejeito
        self.counted = False      # ja contado como expedido fora da tolerancia

    @property
    def gross(self) -> float:
        return self.tare + self.a + self.b


@register
class ScaleEnvironment(Environment):
    id = "balanca"
    name = "Dosagem por receita em balança"
    description = ("Cada recipiente vazio pesa de 40 a 70 g (tara). A balança escreve o peso bruto em N0 e a receita "
                   "escolhida os alvos líquidos em N1 (ingrediente A, granulado) e N2 (B, líquido). A enche rápido "
                   "pela válvula grossa (300 g/s) e termina pela fina (25 g/s); B tem uma válvula (40 g/s). O "
                   "produto leva tempo caindo: feche antes (corte antecipado) e corrija pelo erro de cada recipiente. "
                   "Tolerância de 2% (mínimo 3 g) em cada ingrediente. Recipientes fora dela precisam ser empurrados "
                   "pelo rejeitador (Q0.6) quando passam pelo sensor I0.4.")
    example = "ambientes/balanca.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("PARTIDA", "I0.0", "Partida", "Botão PARTIDA (NA)", BUTTON),
        IOPoint("PARADA", "I0.1", "Parada", "Botão PARADA (NF: lê 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("RECIPIENTE", "I0.2", "Recipiente_Posicionado", "Recipiente sob os bicos"),
        IOPoint("ESTAVEL", "I0.3", "Peso_Estavel", "Balança estável (peso parado)"),
        IOPoint("NO_REJEITO", "I0.4", "Recipiente_Rejeito", "Recipiente na estação de rejeito"),
    ]
    outputs = [
        IOPoint("GROSSA", "Q0.0", "Valvula_A_Grossa", "Ingrediente A: válvula grossa (rápida)"),
        IOPoint("FINA", "Q0.1", "Valvula_A_Fina", "Ingrediente A: válvula fina (lenta)"),
        IOPoint("ESTEIRA", "Q0.2", "Esteira", "Esteira dos recipientes"),
        IOPoint("OK", "Q0.3", "Lampada_OK", "Lâmpada PESO OK"),
        IOPoint("REJEITO", "Q0.4", "Lampada_Rejeito", "Lâmpada FORA DA TOLERÂNCIA"),
        IOPoint("VALV_B", "Q0.5", "Valvula_B", "Ingrediente B: válvula do líquido"),
        IOPoint("EMPURRA", "Q0.6", "Rejeitador", "Cilindro rejeitador"),
    ]

    def reset(self) -> None:
        self.recipe = getattr(self, "recipe", "R1")
        self.rng = random.Random(3)
        self.cans: list[Can] = [self._new_can(-SPACING), self._new_can(-2 * SPACING)]
        self.v = 0.0
        self.belt_pos = 0.0
        self.valves = {"GROSSA": 0.0, "FINA": 0.0, "VALV_B": 0.0}
        self.air_a = DelayLine(FALL_A)
        self.air_b = DelayLine(FALL_B)
        self.reading = 0.0
        self.stable_ms = 0
        self.spilled = 0.0
        self.ok = self.bad = 0
        self.rejected_bad = self.shipped_bad = self.rejected_good = 0
        self.last: tuple[float, float] | None = None       # erros do ultimo recipiente (A, B)
        self.overflow = False
        self.wrong_ok = False
        self.pusher = 0.0
        self.n_words = 64
        self.trend = History(160, 100, 1)

    def _new_can(self, x: float) -> Can:
        return Can(x, self.rng.uniform(*TARE))

    def configure(self, n_inputs: int, n_outputs: int, n_words: int) -> bool:
        self.n_words = n_words
        return False

    def targets(self) -> tuple[int, int]:
        _, a, b = RECIPES[self.recipe]
        return a, b

    def input_words(self) -> dict[int, int]:
        a, b = self.targets()
        return {PESO_WORD: round(self.reading), ALVO_A_WORD: a, ALVO_B_WORD: b}

    def on_control(self, key: str, down: bool) -> None:
        if down and key in RECIPES:
            self.recipe = key

    def press(self, key: str, down: bool) -> None:
        if key in RECIPES:
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _under_spout(self) -> Can | None:
        return next((c for c in self.cans if abs(c.x) <= 15.0 and not c.rejected), None)

    def _on_scale(self) -> Can | None:
        return next((c for c in self.cans if abs(c.x) <= SCALE_MM and not c.rejected), None)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for key in self.valves:
            self.valves[key] = approach(self.valves[key], 1.0 if out[key] else 0.0, 1 / VALVE_S, 1 / VALVE_S, dt)
        self.air_a.push((COARSE * self.valves["GROSSA"] + FINE * self.valves["FINA"]) * dt)
        self.air_b.push(LIQUID * self.valves["VALV_B"] * dt)
        landed_a, landed_b = self.air_a.advance(dt), self.air_b.advance(dt)
        can = self._under_spout()
        if landed_a or landed_b:
            if can is not None:
                ta, tb = self.targets()
                if landed_a and can.a == 0:
                    can.cand_a.add(ta)
                    can.cand_b.add(tb)
                if landed_b and can.b == 0:
                    can.cand_b.add(tb)
                can.a += landed_a
                can.b += landed_b
            else:
                self.spilled += landed_a + landed_b
        before = {id(c): abs(c.x) <= SCALE_MM for c in self.cans}
        self.v = approach(self.v, BELT_SPEED if out["ESTEIRA"] else 0.0, BELT_ACCEL, BELT_ACCEL, dt)
        self.belt_pos += self.v * dt
        for c in self.cans:
            if not c.rejected:
                c.x += self.v * dt
            else:
                c.drop += dt
        for c in self.cans:                              # recipiente saindo da balanca: resultado
            if before[id(c)] and abs(c.x) > SCALE_MM and c.x > 0 and c.good is None and c.a + c.b > 1.0:
                ta = min(c.cand_a or {self.targets()[0]}, key=lambda t: abs(c.a - t))
                tb = min(c.cand_b or {self.targets()[1]}, key=lambda t: abs(c.b - t))
                ea, eb = c.a - ta, c.b - tb
                self.last = (ea, eb)
                c.good = abs(ea) <= tolerance(ta) and abs(eb) <= tolerance(tb)
                self.ok += c.good
                self.bad += not c.good
                if out["OK"] and not c.good:
                    self.wrong_ok = True
        # rejeitador
        self.pusher = approach(self.pusher, 1.0 if out["EMPURRA"] else 0.0, 1 / PUSH_S, 1 / PUSH_S, dt)
        for c in self.cans:
            if not c.rejected and self.pusher > 0.6 and abs(c.x - REJECT_AT) <= REJECT_WIN:
                c.rejected = True
                if c.good is False:
                    self.rejected_bad += 1
                elif c.good:
                    self.rejected_good += 1
            if not c.rejected and c.good is False and c.x > REJECT_AT + REJECT_WIN and not c.counted:
                c.counted = True
                self.shipped_bad += 1
        if self.cans and self.cans[-1].x > -2 * SPACING + 1:
            self.cans.append(self._new_can(self.cans[-1].x - SPACING))
        self.cans = [c for c in self.cans if c.x < 700 and c.drop < 0.6]
        stopped = self._under_spout()
        if stopped is not None and abs(self.v) < 1.0 and not stopped.cand_a:
            stopped.cand_a.add(self.targets()[0])
            stopped.cand_b.add(self.targets()[1])
        on_scale = self._on_scale()
        weight = on_scale.gross if on_scale is not None else 0.0
        old = self.reading
        self.reading += (weight - self.reading) * min(1.0, dt / FILTER_S)
        rate = abs(self.reading - old) / dt if dt else 0.0
        self.stable_ms = self.stable_ms + dt_ms if rate < STABLE_RATE and abs(self.v) < 1.0 else 0
        limit = 1.3 * (max(on_scale.cand_a or {0}) + max(on_scale.cand_b or {0})) + 50 if on_scale else 0
        if on_scale is not None and on_scale.cand_a and on_scale.a + on_scale.b > limit:
            self.overflow = True
        self.trend.add(dt_ms, self.reading)

    def sensors(self) -> dict[str, bool]:
        return {"RECIPIENTE": any(abs(c.x) <= SENSOR_MM and not c.rejected for c in self.cans),
                "ESTAVEL": self.stable_ms >= STABLE_MS,
                "NO_REJEITO": any(abs(c.x - REJECT_AT) <= SENSOR_MM and not c.rejected for c in self.cans)}

    def alarms(self) -> list[str]:
        out = []
        if self.spilled > 5.0:
            out.append("Produto derramado: válvula aberta sem recipiente sob o bico ou com a esteira andando")
        if self.overflow:
            out.append("O recipiente transbordou (mais de 130% da receita)")
        if self.wrong_ok:
            out.append("A lâmpada OK acendeu para um recipiente fora da tolerância")
        if self.shipped_bad:
            out.append("Recipiente fora da tolerância seguiu para a expedição: acione o rejeitador quando ele "
                       "passar por I0.4")
        if self.rejected_good:
            out.append("Recipiente bom foi rejeitado")
        if self.ok + self.bad >= 6 and self.bad * 2 > self.ok + self.bad:
            out.append("Mais da metade dos recipientes fora da tolerância: a tara (peso do recipiente vazio) foi "
                       "descontada?")
        return out

    def stats(self) -> list[str]:
        name, a, b = RECIPES[self.recipe]
        err = "-" if self.last is None else f"A {self.last[0]:+.1f} g, B {self.last[1]:+.1f} g"
        info = [f"{name}: A {a} g + B {b} g | último erro: {err}",
                f"Bons: {self.ok} | fora da tolerância: {self.bad} (rejeitados {self.rejected_bad}) | "
                f"balança N0 = {round(self.reading)} g"]
        if self.n_words <= ALVO_B_WORD:
            info.append("A balança precisa dos registradores N0 a N2: escolha um controlador com registradores N.")
        return info

    # ------------------------------------------------------------ desenho
    def controls(self):
        c = {"PARTIDA": (14, 352, 130, 28), "PARADA": (14, 386, 130, 28)}
        for k, key in enumerate(RECIPES):
            c[key] = (14, 236 + k * 32, 130, 28)
        return c

    def _can(self, p: QPainter, x: float, c: Can) -> None:
        y = 300 + (c.drop * 160 if c.rejected else 0)
        body = QRectF(x - 18, y - 46, 36, 46)
        g = QLinearGradient(body.topLeft(), body.topRight())
        g.setColorAt(0, QColor("#cbd5e1"))
        g.setColorAt(0.4, QColor("#f8fafc"))
        g.setColorAt(1, QColor("#94a3b8"))
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(g)
        p.drawRoundedRect(body, 3, 3)
        cap = 950.0
        ha = min(1.0, c.a / cap) * 40
        hb = min(1.0, c.b / cap) * 40
        inner = body.adjusted(3, 3, -3, -3)
        if ha > 0:
            p.fillRect(QRectF(inner.left(), inner.bottom() - ha, inner.width(), ha), QColor("#b45309"))
        if hb > 0:
            p.fillRect(QRectF(inner.left(), inner.bottom() - ha - hb, inner.width(), hb), QColor(56, 189, 248, 220))
        if c.good is not None:
            draw.lamp(p, QPointF(x, y - 54), 4, True, draw.GREEN if c.good else draw.RED)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        draw.ground(p, 400, 720, 460)
        out = self.out
        sens = self.sensors()
        sx = 330.0                                   # bicos e balanca
        # silo A (granulado)
        silo = QPolygonF([QPointF(sx - 120, 30), QPointF(sx - 40, 30), QPointF(sx - 40, 110), QPointF(sx - 70, 140),
                          QPointF(sx - 90, 140), QPointF(sx - 120, 110)])
        g = QLinearGradient(sx - 120, 0, sx - 40, 0)
        g.setColorAt(0, QColor("#94a3b8"))
        g.setColorAt(0.4, QColor("#e2e8f0"))
        g.setColorAt(1, QColor("#64748b"))
        p.setPen(QPen(QColor("#334155"), 1.5))
        p.setBrush(g)
        p.drawPolygon(silo)
        p.fillRect(QRectF(sx - 116, 60, 72, 50), QColor(180, 83, 9, 200))
        draw.ctext(p, sx - 80, 44, "A granulado", 7, True, draw.INK, 80)
        draw.pipe(p, [QPointF(sx - 80, 140), QPointF(sx - 80, 176), QPointF(sx - 12, 176), QPointF(sx - 12, 214)], 8,
                  None, color="#cbd5e1")
        draw.valve(p, QPointF(sx - 60, 176), 14, out.get("GROSSA", False))
        draw.tag(p, sx - 150, 210, "Q0.0 grossa", out.get("GROSSA", False))
        draw.pipe(p, [QPointF(sx - 100, 140), QPointF(sx - 100, 160)], 4, None, color="#cbd5e1")
        draw.valve(p, QPointF(sx - 100, 166), 10, out.get("FINA", False), vertical=True)
        draw.pipe(p, [QPointF(sx - 100, 172), QPointF(sx - 100, 176)], 4, None, color="#cbd5e1")
        draw.tag(p, sx - 150, 232, "Q0.1 fina", out.get("FINA", False))
        # tanque B (liquido)
        draw.tank(p, QRectF(sx + 40, 30, 80, 110), 0.7, QColor("#38bdf8"), wave=self.time_ms / 300)
        draw.ctext(p, sx + 80, 22, "B líquido", 7, True, draw.INK, 80)
        draw.pipe(p, [QPointF(sx + 80, 140), QPointF(sx + 80, 176), QPointF(sx + 12, 176), QPointF(sx + 12, 214)], 6,
                  self.time_ms / 20 if self.valves["VALV_B"] > 0.3 else None, QColor("#38bdf8"))
        draw.valve(p, QPointF(sx + 50, 176), 14, out.get("VALV_B", False))
        draw.tag(p, sx + 40, 196, "Q0.5 B", out.get("VALV_B", False))
        # jatos em queda
        if self.air_a.in_flight > 0.2:
            p.setPen(QPen(QColor("#b45309"), 2, Qt.DotLine))
            for k in range(3):
                p.drawLine(QPointF(sx - 14 + k * 2, 216), QPointF(sx - 14 + k * 2, 254))
        if self.air_b.in_flight > 0.2:
            p.setPen(QPen(QColor(56, 189, 248, 220), 3))
            p.drawLine(QPointF(sx + 12, 216), QPointF(sx + 8, 254))
        # esteira, balanca e recipientes
        belt = QRectF(150, 300, 560, 16)
        draw.conveyor(p, belt, self.belt_pos * 0.4, self.v > 1)
        plat = QRectF(sx - 40, 316, 80, 14)
        draw.metal(p, plat, "#475569", 2)
        draw.metal(p, QRectF(sx - 10, 330, 20, 40), "#334155", 2, vertical=True)
        draw.lcd(p, QRectF(sx - 52, 370, 104, 28), f"{round(self.reading):5d} g", "#4ade80", "N0")
        for c in self.cans:
            x = sx + c.x * 0.48
            if 150 < x < 712 or c.rejected:
                self._can(p, x, c)
        draw.sensor(p, QRectF(sx - 64, 262, 10, 16), sens["RECIPIENTE"], vertical=False)
        draw.tag(p, sx - 140, 270, "I0.2 recipiente", sens["RECIPIENTE"])
        draw.tag(p, sx + 60, 384, "I0.3 estável", sens["ESTAVEL"])
        draw.tag(p, 600, 334, "Q0.2 esteira", out.get("ESTEIRA", False))
        # rejeito
        rx = sx + REJECT_AT * 0.48
        tip = draw.cylinder(p, QRectF(rx - 9, 214, 18, 34), self.pusher, horizontal=False, stroke=30)
        draw.metal(p, QRectF(rx - 16, tip.y() - 2, 32, 6), "#be123c", 2)
        draw.tag(p, rx + 14, 222, "Q0.6 rejeitador", out.get("EMPURRA", False))
        draw.sensor(p, QRectF(rx + 22, 262, 10, 16), sens["NO_REJEITO"], vertical=False)
        draw.tag(p, rx + 36, 270, "I0.4", sens["NO_REJEITO"])
        bin_r = QRectF(rx - 30, 404, 60, 44)
        draw.metal(p, bin_r, "#7f1d1d", 4)
        draw.ctext(p, rx, bin_r.center().y(), f"rejeito {self.rejected_bad + self.rejected_good}", 7, True,
                   draw.WHITE, 60)
        draw.text(p, 660, 284, "expedição →", 7, True, draw.MUTED, w=70)
        # receita
        draw.card(p, QRectF(8, 14, 142, 212), "Receita")
        name, a, b = RECIPES[self.recipe]
        draw.lcd(p, QRectF(18, 42, 122, 30), f"{a:4d} g", "#fbbf24", "A alvo (N1)")
        draw.lcd(p, QRectF(18, 78, 122, 30), f"{b:4d} g", "#38bdf8", "B alvo (N2)")
        draw.lamp(p, QPointF(30, 128), 7, out.get("OK", False), draw.GREEN)
        draw.text(p, 42, 128, "OK Q0.3", 7, True, w=50)
        draw.lamp(p, QPointF(94, 128), 7, out.get("REJEITO", False), draw.RED)
        draw.text(p, 106, 128, "Q0.4", 7, True, w=40)
        if self.last is not None:
            draw.text(p, 18, 152, f"Erro A {self.last[0]:+.1f} g", 7.5, True,
                      draw.GREEN if abs(self.last[0]) <= tolerance(a) else draw.RED, w=130)
            draw.text(p, 18, 170, f"Erro B {self.last[1]:+.1f} g", 7.5, True,
                      draw.GREEN if abs(self.last[1]) <= tolerance(b) else draw.RED, w=130)
        draw.text(p, 18, 194, f"Bons {self.ok} | fora {self.bad}", 7.5, True, draw.INK, w=130)
        draw.text(p, 18, 212, f"Tolerância ±{tolerance(a):.0f} / ±{tolerance(b):.0f} g", 6.5, False, draw.MUTED,
                  w=130)
        for k, (key, (label, ra, rb)) in enumerate(RECIPES.items()):
            draw.push_button(p, QRectF(14, 236 + k * 32, 130, 28), f"{label.split()[1]}: {ra}+{rb} g",
                             self.recipe == key, draw.BLUE if self.recipe == key else QColor("#94a3b8"))
        draw.push_button(p, QRectF(14, 352, 130, 28), "PARTIDA I0.0", self.is_pressed("PARTIDA"), draw.GREEN)
        draw.push_button(p, QRectF(14, 386, 130, 28), "PARADA I0.1", self.is_pressed("PARADA"), draw.RED)
        # tendencia do peso
        draw.trend(p, QRectF(470, 14, 240, 150), [(self.trend.series(0), "#16a34a")], 0, 1400,
                   "Peso bruto N0 (g)", [(sum(self.targets()) + 55, "#94a3b8")], 160)
