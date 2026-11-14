"""Separacao por peso: balanca dinamica, fila FIFO de palavras e transferidor de correntes."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..registry import register
from ..transport import Belt, Emitter, Item, carton, emitter_box, remover_box

LANE = 180.0
BELT_W = 52.0
X0, X_END = 40.0, 700.0
SCALE_X0, SCALE_X1 = 230.0, 310.0     # plataforma da balanca (80 px; a caixa tem 50)
ST = 520.0                            # centro do transferidor
ST_BEAM = ST + 22.0                   # fotocelula do transferidor (caixa centrada quando a frente chega nela)
BOX_L = 50.0
CROSS_V = 130.0                       # velocidade do transferidor (px/s)
CROSS_OUT = 48.0                      # deslocamento lateral em que a caixa sai do transferidor para a rampa
CHUTE = 70.0                          # comprimento das rampas ate as caixas coletoras
MARGIN = 15.0                         # I0.1 so liga com a caixa 15 px para dentro da plataforma
SETTLE_S = 0.5                        # tempo parado para o peso estabilizar
LIGHT, OK, HEAVY = 0, 1, 2
WEIGHT_RANGE = {LIGHT: (380, 440), OK: (465, 535), HEAVY: (560, 620)}
NAMES = {LIGHT: "leve", OK: "no peso", HEAVY: "pesada"}
QUEUE_WORDS = range(20, 25)           # N20..N24 desenhados no painel (fila do exemplo)


@register
class WeightSortingEnvironment(Environment):
    id = "separacao_peso"
    name = "Separação por peso"
    description = ("Caixas leves (abaixo de 450 g), no peso e pesadas (acima de 550 g) chegam misturadas. A balança "
                   "recebe uma caixa por vez (a seguinte espera na entrada) e a leitura N0, em gramas, só fica estável "
                   "(I0.2) com a caixa inteira sobre a plataforma (I0.1) e a esteira da balança parada por meio segundo. Entre a balança e o transferidor de correntes ficam "
                   "várias caixas já pesadas: o programa guarda a classe de cada uma numa fila (FIFO) e, quando a caixa chega "
                   "ao transferidor (I0.3), consulta a primeira da fila. Q0.3 leva a caixa para a rampa das leves, "
                   "Q0.4 para a das pesadas; as boas seguem para a expedição. Para a caixa centrada, pare a esteira "
                   "de desvio enquanto o transferidor trabalha.")
    example = "ambientes/separacao_peso.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("BALANCA", "I0.1", "Caixa_Na_Balanca", "Caixa inteira sobre a plataforma da balança"),
        IOPoint("ESTAVEL", "I0.2", "Peso_Estavel", "Leitura da balança estável (N0 vale)"),
        IOPoint("ESTACAO", "I0.3", "Caixa_No_Transferidor", "Fotocélula: caixa centrada no transferidor"),
    ]
    outputs = [
        IOPoint("ENTRADA", "Q0.0", "Esteira_Entrada", "Esteira de entrada"),
        IOPoint("PESAGEM", "Q0.1", "Esteira_Balanca", "Esteira da balança"),
        IOPoint("DESVIO", "Q0.2", "Esteira_Desvio", "Esteira até o transferidor e a expedição"),
        IOPoint("LEVES", "Q0.3", "Transfere_Leves", "Transferidor: leva a caixa para a rampa das leves"),
        IOPoint("PESADAS", "Q0.4", "Transfere_Pesadas", "Transferidor: leva a caixa para a rampa das pesadas"),
        IOPoint("EMISSOR", "Q0.5", "Emissor", "Emissor de caixas"),
        IOPoint("LUZ", "Q0.6", "Luz_Operando", "Lâmpada operando"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(11)
        self.entry = Belt(X0, SCALE_X0, 100.0)
        self.scale = Belt(SCALE_X0, SCALE_X1, 100.0)
        self.sort = Belt(SCALE_X1, X_END, 100.0)
        self.emitter = Emitter(self.rng, (60.0, 200.0))
        self.cross: list[Item] = []          # caixas sobre o transferidor (data["dy"]: <0 leves, >0 pesadas)
        self.chutes: dict[int, list[Item]] = {LIGHT: [], HEAVY: []}
        self.flags: dict[str, str] = {}
        self.done = {LIGHT: 0, OK: 0, HEAVY: 0}
        self.wrong = 0
        self.emitted = 0
        self.still_s = 0.0
        self.reading = 0.0
        self.queue = [0] * len(QUEUE_WORDS)
        self.chain = 0.0

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def _deliver(self, it: Item, where: int) -> None:
        if it.kind == where:
            self.done[where] += 1
            return
        self.wrong += 1
        dest = {LIGHT: "a rampa das leves", OK: "a expedição", HEAVY: "a rampa das pesadas"}[where]
        self._flag(f"wrong{it.kind}{where}", f"Caixa {NAMES[it.kind]} foi para {dest}")

    # ------------------------------------------------------------- balanca
    def _on_platform(self) -> list[tuple[Item, float]]:
        """Caixas que tocam a plataforma e a fracao do peso de cada uma sobre ela."""
        out = []
        for it in self.scale.items + self.sort.items:
            ov = min(it.x, SCALE_X1) - max(it.back, SCALE_X0)
            if ov > 0:
                out.append((it, ov / it.length))
        return out

    def _full(self) -> Item | None:
        """A caixa sozinha e inteira na plataforma, ja 15 px para dentro (a seguinte espera fora dela)."""
        on = self._on_platform()
        if len(on) == 1 and on[0][1] >= 0.999 and on[0][0].back >= SCALE_X0 + MARGIN:
            return on[0][0]
        return None

    @staticmethod
    def _limit(nxt: Belt, edge: float) -> float:
        """Fim do trecho, ou a traseira da caixa que ainda esta passando para a esteira seguinte."""
        return min([edge] + [i.back - 3.0 for i in nxt.items if i.back < edge + 3.0])

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        if out["EMISSOR"] and self.emitter.ready(self.entry, BOX_L):
            kind = self.rng.choices((LIGHT, OK, HEAVY), (1, 2, 1))[0]
            it = Item(0.0, BOX_L, kind, {"w": self.rng.uniform(*WEIGHT_RANGE[kind])})
            self.emitter.emit(self.entry, it)
            self.emitted += 1
        # transferidor de correntes
        up, down = bool(out["LEVES"]), bool(out["PESADAS"])
        if up and down:
            self._flag("both", "Transferidor ligado nos dois sentidos ao mesmo tempo")
        v = (-CROSS_V if up else 0.0) + (CROSS_V if down else 0.0)
        if v:
            self.chain += abs(v) * dt
            for it in self.sort.take(lambda i: abs(i.center - ST) < 30):
                if abs(it.center - ST) > 12:
                    self._flag("offc", "O transferidor pegou uma caixa fora do centro (a esteira não parou a tempo)")
                it.data["dy"] = 0.0
                self.cross.append(it)
            if self.cross and out["DESVIO"]:
                self._flag("drag", "A esteira de desvio andou com uma caixa sobre o transferidor em movimento")
        for it in list(self.cross):
            it.data["dy"] += v * dt
            dy = it.data["dy"]
            if abs(dy) >= CROSS_OUT:
                self.cross.remove(it)
                lane = LIGHT if dy < 0 else HEAVY
                it.data["s"] = 0.0
                self.chutes[lane].append(it)
        for lane, items in self.chutes.items():
            for it in list(items):
                it.data["s"] = min(CHUTE, it.data["s"] + 160.0 * dt)
                if it.data["s"] >= CHUTE:
                    items.remove(it)
                    self._deliver(it, lane)
        # esteira de desvio: o transferidor ocupado segura so as caixas de tras dele
        items = self.sort.items
        behind = [i for i in items if self.cross and i.x <= ST - 29]
        self.sort.items = [i for i in items if i not in behind]
        self.sort.move(dt, bool(out["DESVIO"]), end=X_END + BOX_L, gap=3.0)
        if behind:
            ahead, self.sort.items = self.sort.items, behind
            off = self.sort.offset
            self.sort.move(dt, bool(out["DESVIO"]), stop=ST - 31, gap=3.0)
            self.sort.offset = off
            self.sort.items = ahead + behind
        for it in self.sort.take(lambda i: i.x >= X_END + BOX_L - 1):
            self._deliver(it, OK)
        # esteira da balanca: passa a caixa para a de desvio
        if out["PESAGEM"]:
            for it in list(self.scale.items):
                if it.x >= SCALE_X1 and out["DESVIO"] and self.sort.clear_from(SCALE_X1, 3):
                    if not it.data.get("weighed"):
                        self._flag("unw", "Caixa passou pela balança sem pesagem estável")
                    self.scale.items.remove(it)
                    self.sort.items.append(it)
        self.scale.move(dt, bool(out["PESAGEM"]), stop=self._limit(self.sort, SCALE_X1))
        if out["PESAGEM"] and out["ENTRADA"]:
            for it in list(self.entry.items):
                if it.x >= SCALE_X0 and not self.scale.items and not self._on_platform():
                    self.entry.items.remove(it)
                    self.scale.items.append(it)
        self.entry.move(dt, bool(out["ENTRADA"]), stop=SCALE_X0)
        # leitura da balanca
        full = self._full()
        if full is not None and not out["PESAGEM"]:
            self.still_s += dt
        else:
            self.still_s = 0.0
        if full is not None and self.still_s >= SETTLE_S:
            full.data["weighed"] = True
        total = sum(it.data["w"] * f for it, f in self._on_platform())
        if total:
            amp = 45.0 if self.still_s == 0 else 45.0 * math.exp(-self.still_s / 0.12)
            total += amp * math.sin(37.0 * self.still_s + 0.11 * self.scale.offset + 1.7 * self.emitted)
        self.reading = max(0.0, total)

    def sensors(self) -> dict[str, bool]:
        on = any(i.covers(ST_BEAM) for i in self.sort.items) or any(abs(i.data["dy"]) < CROSS_OUT
                                                                    for i in self.cross)
        return {"BALANCA": self._full() is not None, "ESTAVEL": self._full() is not None and self.still_s >= SETTLE_S,
                "ESTACAO": on}

    def input_words(self) -> dict[int, int]:
        return {0: round(self.reading)}

    def advance_words(self, n: list[int]) -> None:
        self.queue = [n[i] if len(n) > i else 0 for i in QUEUE_WORDS]

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Leves: {self.done[LIGHT]} | no peso: {self.done[OK]} | pesadas: {self.done[HEAVY]} | "
                f"no lugar errado: {self.wrong}",
                f"Caixas emitidas: {self.emitted} | balança: {round(self.reading)} g"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (16, 412, 150, 30)}

    def _rollers(self, p: QPainter, r: QRectF, offset: float) -> None:
        draw.metal(p, r, "#94a3b8", 3)
        p.setPen(QPen(QColor("#475569"), 2))
        y = r.top() + 4 + (offset % 10)
        while y < r.bottom() - 2:
            p.drawLine(QPointF(r.left() + 3, y), QPointF(r.right() - 3, y))
            y += 10

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out, sens = self.out, self.sensors()
        floor = QRectF(8, 8, 704, 322)
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(floor, 8, 8)
        draw.text(p, 18, 20, "VISTA DE CIMA", 7, True, draw.MUTED)
        top = LANE - BELT_W / 2
        bot = LANE + BELT_W / 2
        colors = {LIGHT: "#e7c48f", OK: "#c08a4a", HEAVY: "#7c4a1e"}
        letters = {LIGHT: "L", OK: "OK", HEAVY: "P"}
        # rampas e caixas coletoras
        up_r = QRectF(ST - 30, top - CHUTE - 4, 60, CHUTE + 4)
        dn_r = QRectF(ST - 30, bot, 60, CHUTE + 4)
        self._rollers(p, up_r, -self.chain)
        self._rollers(p, dn_r, self.chain)
        for r, label, n in ((QRectF(ST - 44, up_r.top() - 30, 88, 30), "LEVES", self.done[LIGHT]),
                            (QRectF(ST - 44, dn_r.bottom(), 88, 30), "PESADAS", self.done[HEAVY])):
            draw.metal(p, r, "#1e3a8a", 4)
            draw.ctext(p, r.center().x(), r.center().y(), f"{label}  {n}", 7, True, draw.WHITE, w=r.width())
        # esteiras e balanca
        draw.conveyor(p, QRectF(X0, top, SCALE_X0 - X0, BELT_W), self.entry.offset, bool(out.get("ENTRADA")))
        draw.conveyor(p, QRectF(SCALE_X0, top, SCALE_X1 - SCALE_X0, BELT_W), self.scale.offset,
                      bool(out.get("PESAGEM")))
        draw.conveyor(p, QRectF(SCALE_X1, top, X_END - SCALE_X1, BELT_W), self.sort.offset, bool(out.get("DESVIO")))
        p.setPen(QPen(QColor("#f59e0b"), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(SCALE_X0 + 1, top - 3, SCALE_X1 - SCALE_X0 - 2, BELT_W + 6))
        # transferidor de correntes
        zone = QRectF(ST - 30, top, 60, BELT_W)
        draw.metal(p, zone, "#475569", 3)
        act = bool(out.get("LEVES")) or bool(out.get("PESADAS"))
        p.setPen(QPen(QColor("#fbbf24") if act else QColor("#94a3b8"), 2.4))
        for i in range(4):
            x = zone.left() + 9 + i * 14
            p.drawLine(QPointF(x, zone.top() + 3), QPointF(x, zone.bottom() - 3))
            p.setPen(QPen(QColor("#0f172a"), 1.2))
            k = (self.chain % 8)
            y = zone.top() + 3 + k
            while y < zone.bottom() - 3:
                p.drawLine(QPointF(x - 2, y), QPointF(x + 2, y))
                y += 8
            p.setPen(QPen(QColor("#fbbf24") if act else QColor("#94a3b8"), 2.4))
        emitter_box(p, QRectF(10, top - 6, 34, BELT_W + 12), bool(out.get("EMISSOR")), "")
        remover_box(p, QRectF(X_END - 4, top - 6, 16, BELT_W + 12), "")
        # caixas
        for it in self.entry.items + self.scale.items + self.sort.items:
            r = QRectF(it.back, LANE - 20, BOX_L, 40)
            if r.right() > X0 - 2:
                carton(p, r.intersected(QRectF(X0 - 2, 0, 800, 800)), colors[it.kind], letters[it.kind])
        for it in self.cross:
            carton(p, QRectF(it.back, LANE - 20 + it.data["dy"], BOX_L, 40), colors[it.kind], letters[it.kind])
        for lane, items in self.chutes.items():
            for it in items:
                s = it.data["s"]
                y = top - CROSS_OUT + 6 - s if lane == LIGHT else bot + CROSS_OUT - 46 + s
                y = max(up_r.top() - 20, y) if lane == LIGHT else min(dn_r.bottom() - 20, y)
                carton(p, QRectF(ST - 20, y, 40, 40), colors[it.kind], letters[it.kind])
        # sensores e etiquetas
        draw.beam(p, QPointF(ST_BEAM, top - 6), QPointF(ST_BEAM, bot + 6), sens["ESTACAO"])
        draw.tag(p, ST + 38, top - 16, "I0.3 transferidor", sens["ESTACAO"])
        draw.tag(p, ST + 38, top - 40, "Q0.3 p/ leves", out.get("LEVES", False))
        draw.tag(p, ST + 38, bot + 40, "Q0.4 p/ pesadas", out.get("PESADAS", False))
        draw.tag(p, ST + 38, bot + 16, "Q0.2 desvio", out.get("DESVIO", False))
        draw.tag(p, SCALE_X0 - 6, top - 40, "I0.1 na balança", sens["BALANCA"])
        draw.tag(p, SCALE_X0 - 6, top - 16, "I0.2 estável", sens["ESTAVEL"])
        draw.tag(p, SCALE_X0 - 6, bot + 16, "Q0.1 balança", out.get("PESAGEM", False))
        draw.tag(p, 70, bot + 16, "Q0.0 entrada", out.get("ENTRADA", False))
        draw.tag(p, 50, top - 16, "Q0.5 emissor", out.get("EMISSOR", False))
        draw.lcd(p, QRectF(SCALE_X0 + 2, bot + 34, 76, 38), str(round(self.reading)),
                 "#4ade80" if sens["ESTAVEL"] else "#facc15", "N0 peso (g)")
        draw.text(p, 604, bot + 70, "EXPEDIÇÃO →", 7, True, draw.MUTED, w=80)
        # painel: fila do programa (N20..N24) e contagens
        panel = QRectF(356, 336, 356, 116)
        draw.card(p, panel, "Painel")
        draw.text(p, 366, 364, "Fila N20 … N24 (1 no peso, 2 leve, 3 pesada)", 7, True, draw.MUTED, w=330)
        names = {0: "", 1: "OK", 2: "L", 3: "P"}
        for k, v in enumerate(self.queue):
            r = QRectF(366 + k * 40, 374, 34, 24)
            p.setPen(QPen(QColor("#334155"), 1))
            p.setBrush(QColor("#7c3aed") if v else QColor("#f8fafc"))
            p.drawRoundedRect(r, 3, 3)
            draw.ctext(p, r.center().x(), r.center().y(), names.get(v, str(v)) or "0", 7, True,
                       draw.WHITE if v else draw.MUTED, w=34)
            draw.ctext(p, r.center().x(), r.bottom() + 8, f"N{20 + k}", 6.5, False, draw.MUTED, w=34)
        draw.lcd(p, QRectF(570, 362, 66, 38), str(self.done[OK]), "#4ade80", "expedidas")
        draw.lcd(p, QRectF(570, 406, 66, 38), str(self.wrong), "#f87171", "erradas")
        draw.stack_light(p, 670, 352, [(bool(self.flags), draw.RED), (bool(out.get("LUZ")), draw.GREEN)])
        draw.tag(p, 366, 432, "Q0.6 operando", out.get("LUZ", False))
        # vista lateral da balanca
        side = QRectF(16, 336, 330, 70)
        draw.card(p, side, "Balança (vista lateral)")
        base = side.bottom() - 10
        scale = 1.6
        cx = side.center().x()
        plat = QRectF(cx - (SCALE_X1 - SCALE_X0) / 2 * scale, base, (SCALE_X1 - SCALE_X0) * scale, 5)
        p.setPen(QPen(QColor("#1f2937"), 3))
        p.drawLine(QPointF(side.left() + 8, base), QPointF(plat.left() - 2, base))
        p.drawLine(QPointF(plat.right() + 2, base), QPointF(side.right() - 8, base))
        draw.metal(p, plat, "#f59e0b", 1)
        mid = (SCALE_X0 + SCALE_X1) / 2
        for it in self.entry.items + self.scale.items + self.sort.items:
            x = cx + (it.back - mid) * scale
            if side.left() + 4 < x and x + BOX_L * scale < side.right() - 4:
                h = 16 + (it.data["w"] - 380) / 240 * 14
                carton(p, QRectF(x, base - h, BOX_L * scale, h), colors[it.kind], f"{round(it.data['w'])} g",
                       tape=False)
        draw.switch(p, QRectF(16, 412, 150, 30), "LIGA I0.0", self.is_pressed("LIGA"))
