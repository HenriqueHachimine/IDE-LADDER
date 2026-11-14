"""Convergencia de esteiras: duas filas de acumulo com batente disputando uma linha principal."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..registry import register
from ..transport import Belt, Item, blade, carton, emitter_box, remover_box

LANE_A, LANE_B = 250.0, 110.0
BELT_W = 52.0
X0, X_END = 40.0, 700.0
BLADE = 280.0                         # batentes no fim das duas filas
MERGE_X = 440.0                       # onde a diagonal de B despeja na linha principal
LONG_X = BLADE - 3 * 51.0 - 12        # fotocelula de fila longa (atras da 3a caixa)
BOX_L = 50.0
ACC_V, MAIN_V = 100.0, 200.0
P0 = QPointF(BLADE, LANE_B)
P1 = QPointF(MERGE_X, LANE_A)
DIAG = math.hypot(P1.x() - P0.x(), P1.y() - P0.y())
ANGLE = math.degrees(math.atan2(P1.y() - P0.y(), P1.x() - P0.x()))
ZONE_END = MERGE_X + BOX_L / 2 + 8    # a juncao fica livre quando a traseira passa daqui
OVERFLOW_S = 4.0                      # caixa esperando lugar na fila por mais que isso: alarme
BURST, BURST_GAP, BURST_PAUSE = 6, 0.6, (14.0, 20.0)   # A: lotes de 6 caixas a cada 14..20 s
ARRIVAL_B = (2.4, 4.4)                # B: uma caixa a cada 2,4..4,4 s


@register
class MergeEnvironment(Environment):
    id = "convergencia"
    name = "Convergência de esteiras"
    description = ("Duas filas de acúmulo (A reta, B pela diagonal) alimentam a mesma linha principal. Cada fila tem "
                   "um batente no fim: com Q0.3/Q0.4 ele abaixa e a primeira caixa sai (I0.1/I0.2 desligam quando ela "
                   "passou; então o batente deve subir, antes da próxima). A zona da junção (I0.5) vai do batente A até "
                   "logo depois do ponto onde a diagonal despeja: só solte uma caixa com ela livre, senão as caixas "
                   "batem. Com as duas caixas esperando, alterne as filas. A fila A recebe lotes de caixas; I0.3/I0.4 "
                   "ficam cobertos quando a fila passou de 3 caixas (acenda Q0.7 se ficar assim por 1 s). Se uma fila "
                   "chega até o emissor, a linha anterior para (alarme). O botão EXPEDIÇÃO PARADA segura as caixas no "
                   "fim da linha principal.")
    example = "ambientes/convergencia.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("BAT_A", "I0.1", "Caixa_No_Batente_A", "Caixa parada no batente A"),
        IOPoint("BAT_B", "I0.2", "Caixa_No_Batente_B", "Caixa parada no batente B"),
        IOPoint("LONGA_A", "I0.3", "Fila_A_Longa", "Fotocélula atrás da 3ª caixa da fila A"),
        IOPoint("LONGA_B", "I0.4", "Fila_B_Longa", "Fotocélula atrás da 3ª caixa da fila B"),
        IOPoint("JUNCAO", "I0.5", "Juncao_Ocupada", "Cortina de luz: caixa na zona da junção"),
    ]
    outputs = [
        IOPoint("ESTEIRA_A", "Q0.0", "Esteira_A", "Esteira de acúmulo A"),
        IOPoint("ESTEIRA_B", "Q0.1", "Esteira_B", "Esteira de acúmulo B"),
        IOPoint("PRINCIPAL", "Q0.2", "Esteira_Principal", "Linha principal e diagonal de B"),
        IOPoint("LIBERA_A", "Q0.3", "Libera_A", "Abaixa o batente A"),
        IOPoint("LIBERA_B", "Q0.4", "Libera_B", "Abaixa o batente B"),
        IOPoint("EMISSOR", "Q0.5", "Emissores", "Emissores das duas filas"),
        IOPoint("LUZ", "Q0.6", "Luz_Operando", "Lâmpada operando"),
        IOPoint("LUZ_FILA", "Q0.7", "Luz_Fila_Longa", "Lâmpada de aviso: fila longa"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(3)
        self.acc = {"A": Belt(X0, BLADE, ACC_V), "B": Belt(X0, BLADE, ACC_V)}
        self.main = Belt(BLADE, X_END, MAIN_V)
        self.diag = Belt(0.0, DIAG + BOX_L / 2, MAIN_V)
        self.next_s = {"A": 0.0, "B": 0.4}          # tempo ate a proxima caixa chegar em cada fila
        self.blocked_s = {"A": 0.0, "B": 0.0}
        self.flags: dict[str, str] = {}
        self.served = {"A": 0, "B": 0}
        self.emitted = {"A": 0, "B": 0}
        self.lost_s = 0.0
        self.hold = False
        self.burst = BURST

    def _interval(self, lane: str) -> float:
        """A recebe lotes (BURST caixas seguidas, depois uma pausa); B recebe caixas soltas."""
        if lane == "B":
            return self.rng.uniform(*ARRIVAL_B)
        self.burst -= 1
        if self.burst > 0:
            return BURST_GAP
        self.burst = BURST
        return self.rng.uniform(*BURST_PAUSE)

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def on_control(self, key: str, down: bool) -> None:
        if key == "EXPED" and down:
            self.hold = not self.hold

    def is_pressed(self, key: str) -> bool:
        return self.hold if key == "EXPED" else super().is_pressed(key)

    # ------------------------------------------------------------- fisica
    def _blade_hit(self, lane: str, items: list[Item]) -> None:
        if any(i.back < BLADE - 0.5 and i.x > BLADE + 0.5 for i in items):
            self._flag(f"blade{lane}", f"O batente {lane} subiu embaixo de uma caixa")

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        run_main = bool(out["PRINCIPAL"])
        for lane in "AB":
            belt = self.acc[lane]
            # chegadas no tempo: sem lugar no inicio da fila, a caixa espera (a linha anterior para)
            if out["EMISSOR"]:
                self.next_s[lane] -= dt
                if self.next_s[lane] <= 0:
                    if belt.clear_from(belt.x0 - BOX_L / 2, BOX_L / 2 + 1):
                        belt.items.append(Item(belt.x0, BOX_L, 0 if lane == "A" else 1))
                        self.emitted[lane] += 1
                        self.next_s[lane] = self._interval(lane)
                        self.blocked_s[lane] = 0.0
                    elif self.hold:                 # a parada da expedicao nao conta contra o programa
                        self.blocked_s[lane] = 0.0
                    else:
                        self.blocked_s[lane] += dt
                        if self.blocked_s[lane] > OVERFLOW_S:
                            self.lost_s += dt
                            self._flag(f"over{lane}", f"A fila {lane} chegou ao emissor: a linha anterior parou")
            down = bool(out["LIBERA_" + lane])
            if not down:
                if lane == "A":
                    self._blade_hit("A", belt.items + [i for i in self.main.items if i.data.get("lane") == "A"])
                else:                       # na diagonal a traseira passa do batente quando x > 50
                    self._blade_hit("B", belt.items + [Item(BLADE + i.x, BOX_L) for i in self.diag.items])
            # caixa que passa do batente segue para a linha principal (A) ou para a diagonal (B)
            if down and run_main:
                for it in list(belt.items):
                    if it.x >= BLADE:
                        if lane == "A" and self.main.clear_from(BLADE, 3):
                            belt.items.remove(it)
                            it.data["lane"] = "A"
                            self.main.items.append(it)
                        elif lane == "B" and self.diag.clear_from(0.0, 3):
                            belt.items.remove(it)
                            it.data["lane"] = "B"
                            it.x = 0.0
                            self.diag.items.append(it)
            stop = BLADE
            if lane == "A":
                stop = min([BLADE] + [i.back - 1.0 for i in self.main.items if i.back < BLADE + 1])
            else:
                stop = min([BLADE] + [BLADE + i.back - 1.0 for i in self.diag.items if i.back < 1])
            belt.move(dt, bool(out["ESTEIRA_" + lane]), stop=stop)
        # linha principal: a expedicao parada segura as caixas no fim
        end = X_END - 2 if self.hold else X_END + BOX_L
        self.main.move(dt, run_main, end=end)
        for it in self.main.take(lambda i: i.x >= X_END + BOX_L - 1):
            self.served[it.data.get("lane", "A")] += 1
        # diagonal: despeja a caixa de B na linha principal
        self.diag.move(dt, run_main, end=DIAG + BOX_L / 2)
        for it in self.diag.take(lambda i: i.x >= DIAG + BOX_L / 2 - 0.5):
            x = MERGE_X + BOX_L / 2
            if any(o.back < x + 2 and o.x > x - BOX_L - 2 for o in self.main.items):
                self._flag("crash", "Colisão na junção: a caixa de B caiu sobre outra caixa")
            it.x = x
            self.main.items.append(it)

    def sensors(self) -> dict[str, bool]:
        zone = any(i.back < ZONE_END for i in self.main.items) or bool(self.diag.items)
        bat_a = self.acc["A"].at(BLADE - 0.5) or any(i.covers(BLADE - 0.5) for i in self.main.items)
        bat_b = self.acc["B"].at(BLADE - 0.5) or any(i.x < BOX_L - 0.5 for i in self.diag.items)
        return {"BAT_A": bat_a, "BAT_B": bat_b,
                "LONGA_A": self.acc["A"].at(LONG_X), "LONGA_B": self.acc["B"].at(LONG_X), "JUNCAO": zone}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Expedidas de A: {self.served['A']} | de B: {self.served['B']}",
                f"Na fila A: {len(self.acc['A'].items)} | B: {len(self.acc['B'].items)} | "
                f"emitidas A {self.emitted['A']}, B {self.emitted['B']}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (16, 412, 150, 30), "EXPED": (176, 412, 170, 30)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out, sens = self.out, self.sensors()
        floor = QRectF(8, 8, 704, 322)
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(floor, 8, 8)
        draw.text(p, 18, 20, "VISTA DE CIMA", 7, True, draw.MUTED)
        run_main = bool(out.get("PRINCIPAL"))
        # diagonal de B (por baixo da linha principal)
        p.save()
        p.translate(P0)
        p.rotate(ANGLE)
        draw.conveyor(p, QRectF(-BELT_W / 2, -BELT_W / 2, DIAG + BELT_W / 2, BELT_W), self.diag.offset, run_main)
        p.restore()
        for lane, y in (("A", LANE_A), ("B", LANE_B)):
            draw.conveyor(p, QRectF(X0, y - BELT_W / 2, BLADE - X0, BELT_W), self.acc[lane].offset,
                          bool(out.get("ESTEIRA_" + lane)))
        draw.conveyor(p, QRectF(BLADE, LANE_A - BELT_W / 2, X_END - BLADE, BELT_W), self.main.offset, run_main)
        # zona da juncao
        p.setPen(QPen(QColor("#f59e0b") if sens["JUNCAO"] else QColor("#94a3b8"), 1.6, Qt.DashLine))
        p.setBrush(QColor(245, 158, 11, 40) if sens["JUNCAO"] else QColor(0, 0, 0, 0))
        p.drawRect(QRectF(BLADE + 2, LANE_A - BELT_W / 2 - 4, ZONE_END - BLADE - 2, BELT_W + 8))
        p.setBrush(QColor(0, 0, 0, 0))
        for lane, y in (("A", LANE_A), ("B", LANE_B)):
            emitter_box(p, QRectF(10, y - BELT_W / 2 - 6, 34, BELT_W + 12), bool(out.get("EMISSOR")), "")
            draw.text(p, 16, y - BELT_W / 2 - 18, lane, 9, True, draw.INK)
        remover_box(p, QRectF(X_END - 4, LANE_A - BELT_W / 2 - 6, 16, BELT_W + 12), "")
        colors = {0: "#c08a4a", 1: "#5b8fc9"}
        for lane, y in (("A", LANE_A), ("B", LANE_B)):
            for it in self.acc[lane].items:
                r = QRectF(it.back, y - 20, BOX_L, 40)
                if r.right() > X0 - 2:
                    carton(p, r.intersected(QRectF(X0 - 2, 0, 800, 800)), colors[it.kind], lane)
        for it in self.main.items:
            carton(p, QRectF(it.back, LANE_A - 20, BOX_L, 40), colors[it.kind], "A" if it.kind == 0 else "B")
        for it in self.diag.items:
            p.save()
            p.translate(P0)
            p.rotate(ANGLE)
            p.translate(it.center, 0)
            p.rotate(-ANGLE * min(1.0, max(0.0, it.center / DIAG)))
            carton(p, QRectF(-BOX_L / 2, -20, BOX_L, 40), colors[1], "B")
            p.restore()
        # batentes e sensores
        for lane, y in (("A", LANE_A), ("B", LANE_B)):
            down = bool(out.get("LIBERA_" + lane))
            blade(p, BLADE + 2, y - BELT_W / 2 - 4, y + BELT_W / 2 + 4, not down)
            draw.beam(p, QPointF(LONG_X, y - BELT_W / 2 - 4), QPointF(LONG_X, y + BELT_W / 2 + 4),
                      sens["LONGA_" + lane])
        draw.tag(p, BLADE - 70, LANE_A + BELT_W / 2 + 16, "I0.1 batente A", sens["BAT_A"])
        draw.tag(p, BLADE - 70, LANE_B - BELT_W / 2 - 16, "I0.2 batente B", sens["BAT_B"])
        draw.tag(p, BLADE + 8, LANE_A + BELT_W / 2 + 16, "Q0.3 libera A", out.get("LIBERA_A", False))
        draw.tag(p, BLADE + 8, LANE_B - BELT_W / 2 - 16, "Q0.4 libera B", out.get("LIBERA_B", False))
        draw.tag(p, LONG_X - 30, LANE_A + BELT_W / 2 + 40, "I0.3 fila A longa", sens["LONGA_A"])
        draw.tag(p, LONG_X - 30, LANE_B + BELT_W / 2 + 16, "I0.4 fila B longa", sens["LONGA_B"])
        draw.tag(p, 50, LANE_A + BELT_W / 2 + 16, "Q0.0 A", out.get("ESTEIRA_A", False))
        draw.tag(p, 50, LANE_B - BELT_W / 2 - 16, "Q0.1 B", out.get("ESTEIRA_B", False))
        draw.tag(p, 100, LANE_B - BELT_W / 2 - 16, "Q0.5 emissores", out.get("EMISSOR", False))
        draw.tag(p, MERGE_X - 40, LANE_A + BELT_W / 2 + 16, "I0.5 junção", sens["JUNCAO"])
        draw.tag(p, 560, LANE_A + BELT_W / 2 + 16, "Q0.2 principal", run_main)
        draw.text(p, 600, LANE_A - BELT_W / 2 - 16, "EXPEDIÇÃO →", 7, True, draw.MUTED, w=90)
        if self.hold:
            draw.metal(p, QRectF(X_END - 4, LANE_A - BELT_W / 2 - 6, 8, BELT_W + 12), "#dc2626", 2)
        # painel
        panel = QRectF(356, 336, 356, 116)
        draw.card(p, panel, "Painel")
        draw.lcd(p, QRectF(366, 362, 76, 38), str(self.served["A"]), "#fbbf24", "de A")
        draw.lcd(p, QRectF(450, 362, 76, 38), str(self.served["B"]), "#60a5fa", "de B")
        draw.lcd(p, QRectF(534, 362, 76, 38), f"{self.lost_s:.0f}", "#f87171", "s parado")
        draw.stack_light(p, 660, 352, [(bool(self.flags), draw.RED), (bool(out.get("LUZ_FILA")), draw.AMBER),
                                        (bool(out.get("LUZ")), draw.GREEN)])
        draw.tag(p, 366, 420, "Q0.6 operando", out.get("LUZ", False))
        draw.tag(p, 470, 420, "Q0.7 fila longa", out.get("LUZ_FILA", False))
        draw.switch(p, QRectF(16, 412, 150, 30), "LIGA I0.0", self.is_pressed("LIGA"))
        draw.push_button(p, QRectF(176, 412, 170, 30), "EXPEDIÇÃO PARADA", self.hold, draw.RED)
        hint = QRectF(16, 336, 330, 70)
        draw.card(p, hint, "Filas")
        for k, lane in enumerate("AB"):
            n = len(self.acc[lane].items)
            draw.text(p, 28, 362 + k * 20, f"Fila {lane}: {n} caixa(s)", 8, True, draw.INK, w=140)
            draw.bar(p, QRectF(170, 356 + k * 20, 160, 12), min(1.0, n / 5), "#f59e0b" if n >= 4 else draw.GREEN)
