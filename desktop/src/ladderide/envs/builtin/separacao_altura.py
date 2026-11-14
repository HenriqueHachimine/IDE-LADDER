"""Separacao por altura: rastreamento com registrador de deslocamento sincronizado pelo encoder."""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..registry import register
from ..transport import Belt, Emitter, Item, carton, emitter_box, remover_box, vbelt

LANE = 210.0                  # eixo da esteira de entrada (y)
BELT_W = 52.0
X0, X_END = 40.0, 700.0
SENSOR_X = 220.0              # estacao de altura
DECIDE_X = 465.0              # centro do desviador de rodas
DIV_X0, DIV_X1 = 432.0, 498.0
UP_LEN = 150.0                # esteira das altas (sobe na tela)
STEP = 10.0                   # o encoder muda a cada 10 px (um pulso a cada 20 px)
BOX_L = 50.0
REG_BITS = 12                 # bits de N5 desenhados sob a esteira
TRACK_WORD = 5
JAM_S = 4.0


@register
class HeightSortingEnvironment(Environment):
    id = "separacao_altura"
    name = "Separação por altura"
    description = ("Caixas baixas e altas chegam misturadas. Na estação de altura (I0.1 vê toda caixa, I0.2 só as "
                   "altas) o programa descobre o tipo, mas o desviador de rodas fica 245 px adiante e entre os dois "
                   "cabem até 3 caixas: é preciso rastrear. O encoder da esteira (I0.3) dá um pulso a cada 20 px; um "
                   "registrador de deslocamento em N5 (cada pulso desloca um bit) leva a informação junto com a caixa. "
                   "Com o desviador (Q0.1) ligado quando a caixa passa pelo centro dele, ela vai para a esteira das "
                   "altas; desligado, segue reto. O registrador N5 aparece sob a esteira.")
    example = "ambientes/separacao_altura.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("BAIXO", "I0.1", "Sensor_Baixo", "Sensor de altura baixo (vê toda caixa)"),
        IOPoint("ALTO", "I0.2", "Sensor_Alto", "Sensor de altura alto (só caixas altas)"),
        IOPoint("ENC", "I0.3", "Encoder", "Encoder da esteira (um pulso a cada 20 px)"),
        IOPoint("FIM_A", "I0.4", "Fim_Altas", "Caixa no fim da esteira das altas"),
        IOPoint("FIM_B", "I0.5", "Fim_Baixas", "Caixa no fim da esteira das baixas"),
    ]
    outputs = [
        IOPoint("ESTEIRA", "Q0.0", "Esteira_Entrada", "Esteira de entrada"),
        IOPoint("DESVIA", "Q0.1", "Desviador", "Desviador de rodas: para a esteira das altas"),
        IOPoint("SAIDA_A", "Q0.2", "Esteira_Altas", "Esteira das caixas altas"),
        IOPoint("SAIDA_B", "Q0.3", "Esteira_Baixas", "Esteira das caixas baixas"),
        IOPoint("EMISSOR", "Q0.4", "Emissor", "Emissor de caixas"),
        IOPoint("LUZ", "Q0.5", "Luz_Operando", "Lâmpada operando"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(5)
        self.entry = Belt(X0, X_END, 100.0)
        self.straight = Belt(DIV_X1, X_END, 100.0)
        self.up = Belt(0.0, UP_LEN, 100.0)
        self.emitter = Emitter(self.rng, (40.0, 150.0))
        self.flags: dict[str, str] = {}
        self.ok = {0: 0, 1: 0}
        self.wrong = 0
        self.held: Item | None = None
        self.held_s = 0.0
        self.track = 0
        self._div = False
        self.emitted = 0

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def _judge(self, it: Item, up: bool) -> None:
        if it.kind == 1 and not up:
            self.wrong += 1
            self._flag("tall", "Caixa alta seguiu reto para a esteira das baixas")
        elif it.kind == 0 and up:
            self.wrong += 1
            self._flag("low", "Caixa baixa desviada para a esteira das altas")
        else:
            self.ok[it.kind] += 1

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        div = bool(out["DESVIA"])
        if div != self._div and any(abs(i.center - DECIDE_X) < 8 for i in self.entry.items):
            self._flag("toggle", "O desviador mudou com uma caixa no meio da transferência")
        self._div = div
        if out["EMISSOR"] and self.emitter.ready(self.entry, BOX_L):
            self.emitter.emit(self.entry, Item(0.0, BOX_L, int(self.rng.random() < 0.5)))
            self.emitted += 1
        # transferencia para as altas bloqueada: a caixa fica no desviador
        if self.held is not None and self.up.clear_from(0.0, BOX_L):
            self.entry.items.remove(self.held)
            self.held.x = BOX_L / 2
            self.up.items.append(self.held)
            self.held = None
            self.held_s = 0.0
        stop = None
        if self.held is not None:
            stop = self.held.x
            if out["ESTEIRA"]:
                self.held_s += dt
                if self.held_s > JAM_S:
                    self._flag("jamA", "Caixa presa no desviador: a esteira das altas está parada ou cheia")
        if not out["SAIDA_B"] or not self.straight.clear_from(DIV_X1, 2):
            stop = DIV_X1 if stop is None else min(stop, DIV_X1)
        before = {id(i): i.center for i in self.entry.items}
        self.entry.move(dt, bool(out["ESTEIRA"]), stop=stop)
        for it in list(self.entry.items):
            c0 = before.get(id(it), it.center)
            if c0 < DECIDE_X <= it.center and it is not self.held:
                it.data["up"] = div
                self._judge(it, div)
                if div:
                    if self.up.clear_from(0.0, BOX_L):
                        self.entry.items.remove(it)
                        it.x = BOX_L / 2
                        self.up.items.append(it)
                    else:
                        it.x = DECIDE_X + BOX_L / 2
                        self.held = it
            if it in self.entry.items and it is not self.held and it.x >= DIV_X1 and out["SAIDA_B"]:
                self.entry.items.remove(it)
                self.straight.items.append(it)
        self.straight.move(dt, bool(out["SAIDA_B"]), end=X_END + BOX_L)
        self.straight.take(lambda i: i.x >= X_END + BOX_L - 1)
        self.up.move(dt, bool(out["SAIDA_A"]), end=UP_LEN + BOX_L)
        self.up.take(lambda i: i.x >= UP_LEN + BOX_L - 1)

    def sensors(self) -> dict[str, bool]:
        tall = any(i.covers(SENSOR_X) and i.kind == 1 for i in self.entry.items)
        return {"BAIXO": self.entry.at(SENSOR_X), "ALTO": tall,
                "ENC": int(self.entry.offset // STEP) % 2 == 1,
                "FIM_A": self.up.at(UP_LEN - 10), "FIM_B": self.straight.at(X_END - 10)}

    def advance_words(self, n: list[int]) -> None:
        self.track = n[TRACK_WORD] if len(n) > TRACK_WORD else 0

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Altas separadas: {self.ok[1]} | baixas: {self.ok[0]} | no lugar errado: {self.wrong}",
                f"Caixas emitidas: {self.emitted} | N5 = {self.track & 0xFFFF:#06x}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (16, 412, 150, 30)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out, sens = self.out, self.sensors()
        floor = QRectF(8, 28, 704, 300)
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(floor, 8, 8)
        draw.text(p, 18, 40, "VISTA DE CIMA", 7, True, draw.MUTED)
        top = LANE - BELT_W / 2
        draw.conveyor(p, QRectF(X0, top, DIV_X0 - X0, BELT_W), self.entry.offset, bool(out.get("ESTEIRA")))
        draw.conveyor(p, QRectF(DIV_X1, top, X_END - DIV_X1, BELT_W), self.straight.offset, bool(out.get("SAIDA_B")))
        cx = DECIDE_X
        vbelt(p, QRectF(cx - BELT_W / 2, LANE - BELT_W / 2 - UP_LEN, BELT_W, UP_LEN), self.up.offset,
              bool(out.get("SAIDA_A")))
        # desviador de rodas
        zone = QRectF(DIV_X0, top, DIV_X1 - DIV_X0, BELT_W)
        draw.metal(p, zone, "#475569", 3)
        on = bool(out.get("DESVIA"))
        p.setPen(QPen(QColor("#fbbf24") if on else QColor("#cbd5e1"), 3))
        for i in range(3):
            for j in range(3):
                c = QPointF(zone.left() + 12 + i * 21, zone.top() + 10 + j * 16)
                d = QPointF(0, -6) if on else QPointF(6, 0)
                p.drawLine(c - d, c + d)
        emitter_box(p, QRectF(10, top - 6, 34, BELT_W + 12), bool(out.get("EMISSOR")), "")
        remover_box(p, QRectF(X_END - 4, top - 6, 16, BELT_W + 12), "")
        remover_box(p, QRectF(cx - BELT_W / 2 - 6, LANE - BELT_W / 2 - UP_LEN - 14, BELT_W + 12, 14), "")
        # caixas
        colors = {0: "#d6a565", 1: "#9a5b20"}
        for it in self.entry.items + self.straight.items:
            r = QRectF(it.back, LANE - 20, BOX_L, 40)
            if r.right() > X0 - 2:
                carton(p, r.intersected(QRectF(X0 - 2, 0, 800, 800)), colors[it.kind], "A" if it.kind else "B")
        for it in self.up.items:
            y = LANE - it.x
            carton(p, QRectF(cx - 20, y, 40, BOX_L), colors[it.kind], "A" if it.kind else "B")
        # estacao de altura e encoder
        draw.beam(p, QPointF(SENSOR_X, top - 8), QPointF(SENSOR_X, top + BELT_W + 8), sens["BAIXO"])
        draw.tag(p, SENSOR_X - 56, top - 18, "I0.1 baixo", sens["BAIXO"])
        draw.tag(p, SENSOR_X + 4, top - 18, "I0.2 alto", sens["ALTO"])
        enc = QPointF(SENSOR_X - 70, top + BELT_W + 18)
        draw.motor(p, enc, 9, sens["ENC"], self.entry.offset / 12, "")
        draw.tag(p, enc.x() + 14, enc.y(), "I0.3 encoder", sens["ENC"])
        draw.tag(p, 50, top - 18, "Q0.4 emissor", out.get("EMISSOR", False))
        draw.tag(p, 120, top + BELT_W + 18 + 22, "Q0.0 entrada", out.get("ESTEIRA", False))
        draw.tag(p, DIV_X0 - 6, top + BELT_W + 12, "Q0.1 desviador", on)
        draw.tag(p, cx + 32, LANE - UP_LEN + 10, "Q0.2 altas", out.get("SAIDA_A", False))
        draw.tag(p, cx + 32, LANE - UP_LEN + 32, "I0.4 fim", sens["FIM_A"])
        draw.tag(p, 590, top + BELT_W + 12, "Q0.3 baixas", out.get("SAIDA_B", False))
        draw.tag(p, 590, top - 18, "I0.5 fim", sens["FIM_B"])
        # registrador N5 sob a esteira: bit k fica onde a informacao esta agora
        y = top + BELT_W + 46
        draw.text(p, SENSOR_X, y - 14, "N5: bit 11 na estação ... bit 0 no desviador", 7, True, draw.MUTED, w=260)
        span = (DECIDE_X - 25 - SENSOR_X) / (REG_BITS - 1)
        for k in range(REG_BITS):
            x = SENSOR_X + (REG_BITS - 1 - k) * span
            bit = self.track >> k & 1
            r = QRectF(x - 9, y, 18, 16)
            p.setPen(QPen(QColor("#334155"), 1))
            p.setBrush(QColor("#7c3aed") if bit else QColor("#f8fafc"))
            p.drawRoundedRect(r, 3, 3)
            draw.ctext(p, r.center().x(), r.center().y(), str(bit), 7, True, draw.WHITE if bit else draw.MUTED, w=18)
        # vista lateral da estacao
        side = QRectF(16, 336, 330, 70)
        draw.card(p, side, "Estação de altura (vista lateral)")
        base = side.bottom() - 8
        p.setPen(QPen(QColor("#1f2937"), 3))
        p.drawLine(QPointF(side.left() + 8, base), QPointF(side.right() - 8, base))
        scale = (side.width() - 20) / 260.0
        for it in self.entry.items:
            if SENSOR_X - 130 < it.center < SENSOR_X + 130:
                x = side.center().x() + (it.back - SENSOR_X) * scale
                h = 34 if it.kind else 18
                carton(p, QRectF(x, base - h, BOX_L * scale, h), colors[it.kind], tape=False)
        sx = side.center().x()
        draw.beam(p, QPointF(sx - 30, base - 10), QPointF(sx + 30, base - 10), sens["BAIXO"])
        draw.beam(p, QPointF(sx - 30, base - 28), QPointF(sx + 30, base - 28), sens["ALTO"])
        draw.text(p, side.left() + 10, base - 10, "I0.1", 7, True, draw.MUTED, w=40)
        draw.text(p, side.left() + 10, base - 28, "I0.2", 7, True, draw.MUTED, w=40)
        # painel
        panel = QRectF(356, 336, 356, 116)
        draw.card(p, panel, "Painel")
        draw.lcd(p, QRectF(366, 362, 76, 38), str(self.ok[1]), "#c084fc", "altas")
        draw.lcd(p, QRectF(450, 362, 76, 38), str(self.ok[0]), "#4ade80", "baixas")
        draw.lcd(p, QRectF(534, 362, 76, 38), str(self.wrong), "#f87171", "erradas")
        draw.stack_light(p, 660, 352, [(bool(self.flags), draw.RED), (bool(out.get("LUZ")), draw.GREEN)])
        draw.tag(p, 366, 420, "Q0.5 operando", out.get("LUZ", False))
        draw.switch(p, QRectF(16, 412, 150, 30), "LIGA I0.0", self.is_pressed("LIGA"))
