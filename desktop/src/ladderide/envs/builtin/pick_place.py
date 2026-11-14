"""Pick & place XY: eixos por setpoint, coordenadas calculadas pelo indice da vaga."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..registry import register
from ..transport import Belt, Emitter, Item, carton, emitter_box

OX, OY = 40.0, 60.0           # origem (0, 0) dos eixos no desenho; 1 mm = 1 px
X_MAX, Y_MAX = 540, 300
PICK = (90, 150)              # fim da esteira de pecas
SLOT_X, SLOT_Y = (330, 420, 510), (100, 200)
PALLET = QRectF(OX + 280, OY + 50, 280, 200)
V_MAX, ACC = 400.0, 1500.0    # mm/s, mm/s2
Z_S = 0.6
TOL = 1.0
GRAB = 8.0                    # distancia maxima entre ventosa e peca/vaga
PART = 40.0
SWAP_OUT, SWAP_IN = 1.5, 3.5  # s: pallet cheio sai, vazio chega
X_WORD, Y_WORD, SPX_WORD, SPY_WORD = 0, 1, 10, 11


class Axis:
    def __init__(self) -> None:
        self.pos = 0.0
        self.v = 0.0

    def step(self, sp: float, dt: float) -> None:
        d = sp - self.pos
        want = math.copysign(min(V_MAX, math.sqrt(2 * ACC * abs(d))), d) if abs(d) > 0.05 else 0.0
        dv = max(-ACC * dt, min(ACC * dt, want - self.v))
        self.v += dv
        nxt = self.pos + self.v * dt
        if (sp - self.pos) * (sp - nxt) <= 0:          # passaria do alvo: para nele
            nxt, self.v = sp, 0.0
        self.pos = nxt

    @property
    def moving(self) -> bool:
        return abs(self.v) > 0.5


@register
class PickPlaceEnvironment(Environment):
    id = "pick_place"
    name = "Pick & place XY"
    description = ("Um pórtico tira as peças do fim da esteira e monta um pallet de 3 x 2. Os eixos X e Y são "
                   "servoposicionados: o programa escreve o destino em N10 (X) e N11 (Y), em mm, e lê a posição em N0 "
                   "e N1; I0.1 indica eixo parado no destino. O Z é pneumático (Q0.1 desce) e a ventosa (Q0.2) só "
                   "pega com o Z embaixo sobre a peça. Coleta em X 90, Y 150; vagas em X 330/420/510 e Y 100/200. "
                   "Pallet com 6 peças: a esteira de pallets (Q0.3) leva embora e traz um vazio.")
    example = "ambientes/pick_place.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("POS", "I0.1", "Em_Posicao", "Eixos X e Y parados no destino"),
        IOPoint("ZC", "I0.2", "Z_Em_Cima", "Eixo Z recolhido"),
        IOPoint("ZB", "I0.3", "Z_Embaixo", "Eixo Z estendido"),
        IOPoint("PRESA", "I0.4", "Peca_Presa", "Vácuo: peça presa na ventosa"),
        IOPoint("PECA", "I0.5", "Peca_Na_Coleta", "Peça parada no fim da esteira"),
        IOPoint("PALLET", "I0.6", "Pallet_Presente", "Pallet vazio ou em montagem no lugar"),
    ]
    outputs = [
        IOPoint("ESTEIRA", "Q0.0", "Esteira_Pecas", "Esteira de peças"),
        IOPoint("DESCE", "Q0.1", "Z_Desce", "Eixo Z: desce"),
        IOPoint("VACUO", "Q0.2", "Ventosa", "Ventosa (vácuo)"),
        IOPoint("PALLETS", "Q0.3", "Esteira_Pallets", "Esteira de pallets (troca o pallet)"),
        IOPoint("LUZ", "Q0.4", "Luz_Operando", "Lâmpada operando"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(9)
        self.ax, self.ay = Axis(), Axis()
        self.sp = [0, 0]
        self.z = 0.0
        self.belt = Belt(-60.0, PICK[0] + PART / 2, 120.0)
        self.emitter = Emitter(self.rng, (20.0, 90.0))
        self.held: int | None = None      # cor da peca presa
        self.slots: dict[tuple[int, int], int] = {}
        self.pallet_y = 0.0               # deslocamento do pallet na troca (0 = no lugar)
        self.swap_t: float | None = None
        self.pallet = True
        self.shipped = 0
        self.placed = 0
        self.flags: dict[str, str] = {}
        self._vac = False

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def _slot_near(self) -> tuple[int, int] | None:
        for i, x in enumerate(SLOT_X):
            for j, y in enumerate(SLOT_Y):
                if abs(self.ax.pos - x) <= GRAB and abs(self.ay.pos - y) <= GRAB:
                    return i, j
        return None

    def _part_at_pick(self) -> Item | None:
        for it in self.belt.items:
            if abs(it.center - PICK[0]) < 2 and it.x >= self.belt.x1 - 0.5:
                return it
        return None

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        if self.out.get("ESTEIRA") and self.emitter.ready(self.belt, PART):
            self.emitter.emit(self.belt, Item(0, PART, self.rng.randrange(3)))
        self.belt.move(dt, bool(out["ESTEIRA"]), end=self.belt.x1)
        # eixos X/Y
        sx, sy = self.sp
        if not (0 <= sx <= X_MAX and 0 <= sy <= Y_MAX):
            self._flag("range", f"Destino fora do curso (X 0..{X_MAX}, Y 0..{Y_MAX} mm)")
            sx, sy = max(0, min(X_MAX, sx)), max(0, min(Y_MAX, sy))
        old = (self.ax.pos, self.ay.pos)
        self.ax.step(sx, dt)
        self.ay.step(sy, dt)
        moved = abs(self.ax.pos - old[0]) + abs(self.ay.pos - old[1]) > 0.01
        if moved and self.z > 0.05:
            self._flag("zdown", "Eixos X/Y em movimento com o Z abaixado")
        # eixo Z
        was = self.z
        self.z = max(0.0, min(1.0, self.z + (dt if out["DESCE"] else -dt) / Z_S))
        slot = self._slot_near()
        if self.held is not None and was < 0.95 <= self.z and slot is not None and slot in self.slots:
            self._flag("stack", "Peça colocada em cima de outra: a vaga já estava ocupada")
        # ventosa
        vac = bool(out["VACUO"])
        if vac and self.held is None and self.z >= 0.98:
            part = self._part_at_pick()
            if part is not None and abs(self.ax.pos - PICK[0]) <= GRAB and abs(self.ay.pos - PICK[1]) <= GRAB:
                self.belt.items.remove(part)
                self.held = part.kind
        if self._vac and not vac and self.held is not None:
            if self.z < 0.95:
                self._flag("drop", "A ventosa soltou a peça no ar")
            elif slot is None or not self.pallet or self.pallet_y:
                self._flag("off", "Peça solta fora de uma vaga do pallet")
            elif slot not in self.slots:
                self.slots[slot] = self.held
                self.placed += 1
            self.held = None
        self._vac = vac
        # pallet
        if out["PALLETS"]:
            self.swap_t = (self.swap_t or 0.0) + dt
            self.pallet_y = min(260.0, self.swap_t / SWAP_OUT * 260.0) if self.pallet else 0.0
            if self.pallet and self.swap_t >= SWAP_OUT:
                if len(self.slots) < 6:
                    self._flag("ship", "Pallet incompleto levado embora")
                else:
                    self.shipped += 1
                self.slots = {}
                self.pallet = False
            if not self.pallet and self.swap_t >= SWAP_IN:
                self.pallet, self.pallet_y = True, 0.0
            if self.z > 0.3 and self.ax.pos > PALLET.left() - OX - 10:
                self._flag("swapz", "Pallet em movimento com o Z abaixado sobre ele")
        elif self.pallet:
            self.swap_t = None

    def sensors(self) -> dict[str, bool]:
        at = (abs(self.ax.pos - self.sp[0]) <= TOL and abs(self.ay.pos - self.sp[1]) <= TOL
              and not self.ax.moving and not self.ay.moving)
        return {"POS": at, "ZC": self.z <= 0.02, "ZB": self.z >= 0.98, "PRESA": self.held is not None,
                "PECA": self._part_at_pick() is not None, "PALLET": self.pallet and self.pallet_y == 0}

    def input_words(self) -> dict[int, int]:
        return {X_WORD: round(self.ax.pos), Y_WORD: round(self.ay.pos)}

    def advance_words(self, n: list[int]) -> None:
        if len(n) > SPY_WORD:
            self.sp = [n[SPX_WORD], n[SPY_WORD]]

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Peças no pallet: {len(self.slots)}/6 | colocadas: {self.placed} | pallets completos: {self.shipped}",
                f"X {self.ax.pos:.0f} Y {self.ay.pos:.0f} mm | destino N10={self.sp[0]} N11={self.sp[1]}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (16, 412, 150, 30)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out, sens = self.out, self.sensors()
        colors = ("#2563eb", "#16a34a", "#dc2626")
        cell = QRectF(10, 30, 600, 372)
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(cell, 8, 8)
        # esteira de pecas
        by = OY + PICK[1]
        draw.conveyor(p, QRectF(14, by - 26, OX + self.belt.x1 - 14, 52), self.belt.offset, bool(out.get("ESTEIRA")))
        emitter_box(p, QRectF(12, by - 32, 18, 64), bool(out.get("ESTEIRA")), "")
        for it in self.belt.items:
            if it.x + OX > 30:
                r = QRectF(OX + it.back, by - PART / 2, PART, PART)
                carton(p, r.intersected(QRectF(30, 0, 800, 800)), colors[it.kind], tape=False)
        draw.tag(p, OX + 30, by + 40, "Q0.0 esteira", out.get("ESTEIRA", False))
        draw.tag(p, OX + 30, by - 40, "I0.5 peça", sens["PECA"])
        # esteira de pallets e pallet
        rail = QRectF(PALLET.left() - 8, 36, PALLET.width() + 16, 360)
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#1f2937"))
        p.drawRoundedRect(rail, 4, 4)
        y = rail.top() + 6 + (self.pallet_y % 18)
        while y < rail.bottom() - 4:
            draw.metal(p, QRectF(rail.left() + 4, y, rail.width() - 8, 8), "#9ca3af", 3)
            y += 18
        if self.pallet:
            pr = PALLET.translated(0, self.pallet_y)
            draw.shadow(p, pr, 3, 3)
            p.setPen(QPen(QColor("#713f12"), 1.2))
            p.setBrush(QColor("#c8a165"))
            p.drawRect(pr)
            p.setPen(QPen(QColor("#a47a3f"), 1))
            for k in range(1, 7):
                yy = pr.top() + pr.height() * k / 7
                p.drawLine(QPointF(pr.left(), yy), QPointF(pr.right(), yy))
            for i, x in enumerate(SLOT_X):
                for j, y in enumerate(SLOT_Y):
                    r = QRectF(OX + x - 24, OY + y - 24 + self.pallet_y, 48, 48)
                    p.setPen(QPen(QColor("#fde68a"), 1.4))
                    p.setBrush(QColor(120, 53, 15, 70))
                    p.drawRoundedRect(r, 3, 3)
                    if (i, j) in self.slots:
                        carton(p, r.adjusted(4, 4, -4, -4), colors[self.slots[(i, j)]], tape=False)
                    draw.ctext(p, r.center().x(), r.bottom() + 8, str(j * 3 + i), 7, True, QColor("#fef3c7"), w=20)
        draw.tag(p, PALLET.left() + 4, 388, "Q0.3 pallets", out.get("PALLETS", False))
        draw.tag(p, PALLET.left() + 110, 388, "I0.6 pallet", sens["PALLET"])
        # portico
        gx, gy = OX + self.ax.pos, OY + self.ay.pos
        draw.metal(p, QRectF(OX - 14, 40, X_MAX + 28, 10), "#475569", 2)
        draw.metal(p, QRectF(OX - 14, OY + Y_MAX + 14, X_MAX + 28, 10), "#475569", 2)
        draw.metal(p, QRectF(gx - 7, 44, 14, Y_MAX + 46), "#f59e0b", 3, vertical=True)
        size = 30 - 8 * self.z
        draw.shadow(p, QRectF(gx - size / 2, gy - size / 2, size, size), 4, 2 + 6 * (1 - self.z))
        draw.metal(p, QRectF(gx - size / 2, gy - size / 2, size, size), "#334155", 4)
        if self.held is not None:
            carton(p, QRectF(gx - 16, gy - 16, 32, 32), colors[self.held], tape=False)
        p.setPen(QPen(QColor("#fbbf24") if out.get("VACUO") else QColor("#94a3b8"), 2))
        p.drawEllipse(QPointF(gx, gy), 6, 6)
        sx, sy = self.sp
        p.setPen(QPen(QColor("#7c3aed"), 1.5))
        p.drawLine(QPointF(OX + sx - 8, OY + sy), QPointF(OX + sx + 8, OY + sy))
        p.drawLine(QPointF(OX + sx, OY + sy - 8), QPointF(OX + sx, OY + sy + 8))
        # painel lateral
        side = QRectF(618, 30, 94, 372)
        draw.card(p, side, "Eixos")
        draw.lcd(p, QRectF(624, 56, 82, 32), f"{self.ax.pos:.0f}", "#fbbf24", "X N0")
        draw.lcd(p, QRectF(624, 94, 82, 32), f"{self.ay.pos:.0f}", "#fbbf24", "Y N1")
        draw.lcd(p, QRectF(624, 132, 82, 32), str(self.sp[0]), "#c084fc", "destino N10")
        draw.lcd(p, QRectF(624, 170, 82, 32), str(self.sp[1]), "#c084fc", "destino N11")
        draw.tag(p, 624, 216, "I0.1 em posição", sens["POS"])
        zr = QRectF(640, 236, 50, 90)
        draw.metal(p, QRectF(zr.left(), zr.top(), zr.width(), 10), "#475569", 2)
        tip = draw.cylinder(p, QRectF(zr.center().x() - 9, zr.top() + 10, 18, 30), self.z, horizontal=False,
                            stroke=40)
        draw.metal(p, QRectF(tip.x() - 12, tip.y(), 24, 6), "#fbbf24" if out.get("VACUO") else "#64748b", 2)
        if self.held is not None:
            carton(p, QRectF(tip.x() - 11, tip.y() + 6, 22, 12), colors[self.held], tape=False)
        draw.tag(p, 624, 340, "Q0.1 Z", out.get("DESCE", False))
        draw.tag(p, 668, 340, "Q0.2", out.get("VACUO", False))
        draw.tag(p, 624, 362, "I0.2", sens["ZC"])
        draw.tag(p, 660, 362, "I0.3", sens["ZB"])
        draw.tag(p, 624, 384, "I0.4 presa", sens["PRESA"])
        # base
        draw.switch(p, QRectF(16, 412, 150, 30), "LIGA I0.0", self.is_pressed("LIGA"))
        draw.lcd(p, QRectF(184, 410, 90, 36), f"{len(self.slots)}/6", "#4ade80", "no pallet")
        draw.lcd(p, QRectF(282, 410, 90, 36), str(self.shipped), "#fbbf24", "pallets prontos")
        draw.stack_light(p, 400, 412, [(bool(self.flags), draw.RED), (bool(out.get("LUZ")), draw.GREEN)], 12)
        draw.tag(p, 420, 428, "Q0.4 operando", out.get("LUZ", False))
