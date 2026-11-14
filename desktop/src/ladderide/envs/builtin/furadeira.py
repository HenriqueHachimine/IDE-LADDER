"""Furadeira automatica: sequencia de etapas, furacao com quebra-cavaco, refrigeracao e vida da ferramenta."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

CLAMP_S = 0.4                 # fixador: avanca/recua em 0,4 s (mola no retorno)
DRILL_DOWN, DRILL_UP = 0.5, 0.8   # curso/s: desce em 2 s, sobe em 1,25 s
SURFACE = 0.55                # a broca toca a peca em 55% do curso
THROUGH = 0.97                # furo passante a partir de 97% (o sensor B1 atua em 98%)
CHIP_LIMIT = 0.20             # cavaco acumulado (fracao do curso) que trava e quebra a broca
SPIN_UP, SPIN_DOWN = 2.0, 1.0     # mandril: 0,5 s para acelerar e 1 s para parar
EJECT_S = 0.3
FEED_S = 0.8                  # o magazine solta a proxima peca em 0,8 s
DWELL_OK_S = 0.3              # tempo no fundo do furo para tirar a rebarba
WEAR_DULL = 30.0              # desgaste (furos equivalentes) em que a broca fica cega
WEAR_DRY = 3.0                # furo sem refrigeracao gasta 3x mais
DEPTH_WORD, TOOL_WORD = 0, 1  # N0 = posicao da ponta (decimos de mm), N1 = numero da broca montada


@register
class DrillEnvironment(Environment):
    id = "furadeira"
    name = "Furadeira automática (sequência)"
    description = ("Ciclo por etapas: fixar (A+), ligar mandril e refrigeração, descer a broca (B+), esperar no "
                   "fundo, subir (B-), soltar (A-) e ejetar (C+ / C-). A ponta da broca aparece em N0 (décimos de mm: "
                   "toca a peça em 550 e atravessa em 970). O cavaco entope o furo: é preciso subir acima da peça a "
                   "cada 14 mm (quebra-cavaco), senão a broca quebra. Sem refrigeração (Q0.6) a broca gasta 3x mais; "
                   "com 30 furos equivalentes fica cega e faz rebarba. 'Trocar broca' monta uma nova (só com a "
                   "emergência acionada) e soma 1 em N1, para o programa zerar a contagem de furos.")
    example = "ambientes/furadeira.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("PARTIDA", "I0.0", "Partida", "Botão PARTIDA do ciclo (NA)", BUTTON),
        IOPoint("EMERG", "I0.1", "Emergencia", "Emergência com trava (NF: lê 1 quando liberada)", SWITCH,
                normally_closed=True),
        IOPoint("PECA", "I0.2", "Peca_Presente", "Peça na posição de furar"),
        IOPoint("A1", "I0.3", "Fixador_Avancado", "Fixador avançado (peça presa)"),
        IOPoint("B0", "I0.4", "Broca_Em_Cima", "Broca recuada (em cima)"),
        IOPoint("B1", "I0.5", "Broca_Embaixo", "Broca no fim do furo"),
        IOPoint("C0", "I0.6", "Ejetor_Recuado", "Ejetor recuado"),
        IOPoint("C1", "I0.7", "Ejetor_Avancado", "Ejetor avançado"),
    ]
    outputs = [
        IOPoint("FIX", "Q0.0", "Fixador", "Válvula do fixador (A+; mola recua)"),
        IOPoint("DESCE", "Q0.1", "Broca_Desce", "Válvula da broca: desce (B+)"),
        IOPoint("SOBE", "Q0.2", "Broca_Sobe", "Válvula da broca: sobe (B-)"),
        IOPoint("MOTOR", "Q0.3", "Motor_Mandril", "Motor do mandril"),
        IOPoint("EJETOR", "Q0.4", "Ejetor", "Válvula do ejetor (C+; mola recua)"),
        IOPoint("CICLO", "Q0.5", "Lampada_Ciclo", "Lâmpada CICLO EM ANDAMENTO"),
        IOPoint("REFRIG", "Q0.6", "Refrigeracao", "Bomba de fluido de corte"),
        IOPoint("TROCAR", "Q0.7", "Lampada_Trocar_Broca", "Lâmpada TROCAR BROCA"),
    ]

    def reset(self) -> None:
        self.clamp = 0.0
        self.drill = 0.0                  # 0 = em cima, 1 = fim do furo
        self.spindle = 0.0
        self.spin_angle = 0.0
        self.eject = 0.0
        self.piece = True
        self.depth = 0.0                  # profundidade furada na peca atual (0..1)
        self.dwell = 0.0
        self.feed_t = 0.0
        self.ejected_piece_x: float | None = None
        self.ejected_ok = True
        self.good = 0
        self.defects = 0
        self.broken = False
        self.broken_by_chips = False
        self.chips = 0.0
        self.dry_cut = 0.0                # curso cortado sem refrigeracao na peca atual
        self.dull_holes = 0
        self.spun = False
        self.eject_crash = False
        self.released_inside = False
        self.both_ms = 0
        self.emergency_moves = 0
        self.wear = getattr(self, "wear", 0.0)
        self.tool_no = getattr(self, "tool_no", 1)
        self.holes_on_tool = getattr(self, "holes_on_tool", 0)
        self.drops: list[list[float]] = []
        self.flying: list[list[float]] = []
        self._seed = 7

    def _rand(self) -> float:
        self._seed = (self._seed * 1103515245 + 12345) & 0x7FFFFFFF
        return self._seed / 0x7FFFFFFF

    def input_words(self) -> dict[int, int]:
        return {DEPTH_WORD: round(self.drill * 1000), TOOL_WORD: self.tool_no}

    def on_control(self, key: str, down: bool) -> None:
        if down and key == "TROCAR_BROCA" and self.is_pressed("EMERG") and self.drill <= 0.02:
            self.tool_no += 1
            self.wear = 0.0
            self.holes_on_tool = 0
            self.broken = False
            self.broken_by_chips = False

    def press(self, key: str, down: bool) -> None:
        if key == "TROCAR_BROCA":
            self.on_control(key, down)
        else:
            super().press(key, down)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        self.clamp = approach(self.clamp, 1.0 if out["FIX"] else 0.0, 1 / CLAMP_S, 1 / CLAMP_S, dt)
        self.spindle = approach(self.spindle, 1.0 if out["MOTOR"] else 0.0, SPIN_UP, SPIN_DOWN, dt)
        self.spin_angle += self.spindle * 40 * dt
        down, up = out["DESCE"], out["SOBE"]
        self.both_ms = self.both_ms + dt_ms if (down and up) else 0
        if self.is_pressed("EMERG") and (down or out["MOTOR"] or out["EJETOR"]):
            self.emergency_moves += 1
        old = self.drill
        dull = self.wear >= WEAR_DULL
        speed_down = DRILL_DOWN * (0.5 if (dull and self.drill > SURFACE) else 1.0)
        if down and not up and not self.broken:
            self.drill = min(1.0, self.drill + speed_down * dt)
        elif up and not down:
            self.drill = max(0.0, self.drill - DRILL_UP * dt)
        bottom = SURFACE + self.depth * (THROUGH - SURFACE)       # fundo atual do furo
        cutting = self.piece and self.drill > SURFACE and self.drill > old and self.drill > bottom
        if cutting:
            if self.spindle < 0.9:
                self.broken = True                   # broca parada contra a peca
                self.drill = old
            elif self.clamp < 0.95 and self.drill > SURFACE + 0.01:
                self.spun = True                     # a peca gira sem o fixador
            else:
                cut = self.drill - max(old, bottom)
                self.chips += cut
                if not out["REFRIG"]:
                    self.dry_cut += cut
                if self.chips > CHIP_LIMIT:          # cavaco entupiu o canal da broca
                    self.broken = self.broken_by_chips = True
                    self.drill = old
                else:
                    self.depth = max(self.depth, min(1.0, (self.drill - SURFACE) / (THROUGH - SURFACE)))
                    if self._rand() < 0.6:
                        a = self._rand() * math.pi
                        self.flying.append([0.0, math.cos(a) * 60, -abs(math.sin(a)) * 70])
        if self.drill < SURFACE - 0.02:
            self.chips = 0.0                         # subiu acima da peca: o cavaco sai
        if self.piece and self.drill >= THROUGH and self.spindle >= 0.9:
            self.dwell += dt
        if self.piece and self.clamp < 0.5 and self.drill > SURFACE + 0.02 and self.depth > 0:
            self.released_inside = True
        # fluido de corte e cavacos (so desenho)
        if out["REFRIG"] and self._rand() < 0.5:
            self.drops.append([0.0, (self._rand() - 0.5) * 10])
        self.drops = [[t + dt, x] for t, x in self.drops if t < 0.5][-40:]
        self.flying = [[t + dt, vx, vy] for t, vx, vy in self.flying if t < 0.5][-30:]
        # ejetor: empurra a peca para a rampa de saida
        self.eject = approach(self.eject, 1.0 if out["EJETOR"] else 0.0, 1 / EJECT_S, 1 / EJECT_S, dt)
        if self.eject > 0.3 and self.piece:
            if self.clamp > 0.1 or self.drill > SURFACE:
                self.eject_crash = True
            elif self.eject > 0.9:
                self._finish_piece()
        if self.ejected_piece_x is not None:
            self.ejected_piece_x += 160 * dt
            if self.ejected_piece_x > 140:
                self.ejected_piece_x = None
        # magazine: a proxima peca cai com o ejetor recuado
        if not self.piece and self.eject < 0.02:
            self.feed_t += dt
            if self.feed_t >= FEED_S:
                self.piece, self.depth, self.dwell, self.feed_t, self.dry_cut = True, 0.0, 0.0, 0.0, 0.0
        else:
            self.feed_t = 0.0

    def _finish_piece(self) -> None:
        drilled = self.depth > 0
        if drilled:
            wet = max(0.0, (THROUGH - SURFACE) - self.dry_cut) / (THROUGH - SURFACE)
            dull_before = self.wear >= WEAR_DULL
            self.wear += wet * 1.0 + (1 - wet) * WEAR_DRY
            self.holes_on_tool += 1
            if dull_before:
                self.dull_holes += 1
        ok = self.depth >= 0.99 and self.dwell >= DWELL_OK_S and not (drilled and self.wear > WEAR_DULL + 1e-9
                                                                    and self.dull_holes)
        self.good += ok
        self.defects += not ok
        self.ejected_ok = ok
        self.piece = False
        self.ejected_piece_x = 0.0

    def sensors(self) -> dict[str, bool]:
        return {"PECA": self.piece, "A1": self.clamp >= 0.98, "B0": self.drill <= 0.02, "B1": self.drill >= 0.98,
                "C0": self.eject <= 0.02, "C1": self.eject >= 0.98}

    def alarms(self) -> list[str]:
        out = []
        if self.broken_by_chips:
            out.append("A broca quebrou: o cavaco entupiu o furo. Suba acima da peça a cada 14 mm (quebra-cavaco)")
        elif self.broken:
            out.append("A broca quebrou: desceu na peça com o mandril parado (ligue o motor antes de descer)")
        if self.spun:
            out.append("A peça girou: furou sem o fixador avançado (espere o sensor I0.3)")
        if self.eject_crash:
            out.append("O ejetor bateu na peça presa ou na broca: solte o fixador e suba a broca antes de ejetar")
        if self.released_inside:
            out.append("O fixador soltou com a broca dentro da peça")
        if self.both_ms > 0:
            out.append("Válvulas de descer e subir a broca ligadas ao mesmo tempo")
        if self.emergency_moves:
            out.append("Movimento comandado com a emergência acionada")
        if self.dull_holes:
            out.append(f"{self.dull_holes} furo(s) feitos com a broca cega (rebarba): conte os furos e peça a troca")
        return out

    def stats(self) -> list[str]:
        return [f"Peças boas: {self.good} | com defeito: {self.defects} | broca nº {self.tool_no}: "
                f"{self.holes_on_tool} furos, desgaste {min(100, self.wear / WEAR_DULL * 100):.0f}%",
                f"Broca: N0 = {round(self.drill * 1000)} | furo atual: {self.depth * 100:.0f}% | "
                f"cavaco {self.chips / CHIP_LIMIT * 100:.0f}% | mandril {self.spindle * 100:.0f}%"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"PARTIDA": (20, 342, 150, 30), "EMERG": (20, 378, 150, 28), "TROCAR_BROCA": (20, 414, 150, 28)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        draw.ground(p, 400, 720, 460)
        sens = self.sensors()
        out = self.out
        # bancada
        bench = QRectF(200, 330, 360, 22)
        draw.metal(p, QRectF(220, 352, 18, 48), "#475569", 2, vertical=True)
        draw.metal(p, QRectF(522, 352, 18, 48), "#475569", 2, vertical=True)
        draw.shadow(p, bench, 3, 3)
        draw.metal(p, bench, "#64748b", 3)
        # coluna
        draw.metal(p, QRectF(486, 30, 30, 300), "#475569", 3, vertical=True)
        draw.metal(p, QRectF(470, 20, 62, 20), "#334155", 4)
        # cabecote com motor
        head_y = 70 + 150 * self.drill
        head = QRectF(330, head_y - 48, 170, 50)
        draw.shadow(p, head, 6, 3)
        draw.metal(p, head, "#1d4ed8" if out.get("MOTOR") else "#334155", 6)
        draw.text(p, 340, head_y - 34, "MANDRIL", 7, True, draw.WHITE)
        draw.tag(p, 340, head_y - 14, "Q0.3 motor", out.get("MOTOR", False))
        draw.fan(p, QPointF(470, head_y - 23), 15, self.spin_angle, out.get("MOTOR", False))
        # broca: a ponta toca a peca em SURFACE
        bx = 380
        tip_len = 270 - (70 + 150 * SURFACE)
        chuck = QRectF(bx - 12, head_y + 2, 24, 16)
        draw.metal(p, chuck, "#94a3b8", 3, vertical=True)
        tip = head_y + 18 + tip_len - 18 if not self.broken else head_y + 18 + (tip_len - 18) * 0.45
        g = QLinearGradient(bx - 4, 0, bx + 4, 0)
        g.setColorAt(0, QColor("#94a3b8"))
        g.setColorAt(0.5, QColor("#f1f5f9") if self.wear < WEAR_DULL else QColor("#a16207"))
        g.setColorAt(1, QColor("#64748b"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawRect(QRectF(bx - 4, head_y + 18, 8, tip - head_y - 18))
        if not self.broken:
            p.drawPolygon(QPolygonF([QPointF(bx - 4, tip), QPointF(bx + 4, tip), QPointF(bx, tip + 6)]))
        else:
            p.setPen(QPen(draw.RED, 2))
            p.drawLine(QPointF(bx - 6, tip), QPointF(bx + 6, tip + 4))
        p.setPen(QPen(QColor("#475569"), 1.2))
        off = (self.spin_angle % 1.0) * 8
        y = head_y + 20 + off
        while y < tip - 2:
            p.drawLine(QPointF(bx - 4, y), QPointF(bx + 4, y + 3))
            y += 8
        # fluido de corte
        if out.get("REFRIG"):
            noz = QPointF(bx + 34, head_y + 18)
            p.setPen(QPen(QColor("#334155"), 3))
            p.drawLine(QPointF(bx + 40, head_y), noz)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(56, 189, 248, 190))
            for t, x in self.drops:
                f = t / 0.5
                p.drawEllipse(QPointF(noz.x() + (bx + 4 - noz.x()) * f + x * 0.3, noz.y() + (270 - noz.y()) * f), 2, 2.6)
        # peca e furo em corte
        piece = QRectF(330, 270, 100, 60)
        if self.piece:
            g = QLinearGradient(piece.topLeft(), piece.bottomLeft())
            g.setColorAt(0, QColor("#cbd5e1"))
            g.setColorAt(1, QColor("#64748b"))
            p.setPen(QPen(QColor("#334155"), 1.2))
            p.setBrush(g)
            p.drawRect(piece)
            if self.depth > 0:
                p.fillRect(QRectF(bx - 5, piece.top(), 10, piece.height() * self.depth), QColor("#1e293b"))
            if self.chips > 0:
                frac = self.chips / CHIP_LIMIT
                col = draw.mix(QColor("#f59e0b"), QColor("#dc2626"), frac)
                fill = piece.height() * self.depth
                p.fillRect(QRectF(bx - 5, piece.top() + fill * (1 - min(1.0, frac)), 10, fill * min(1.0, frac)), col)
        p.setPen(QPen(QColor("#b45309"), 1.5))
        for t, vx, vy in self.flying:
            c = QPointF(bx + vx * t, 268 + vy * t + 200 * t * t)
            p.drawArc(QRectF(c.x() - 3, c.y() - 3, 6, 6), 0, 270 * 16)
        # magazine de pecas (esquerda, acima do fixador)
        mag = QRectF(256, 150, 52, 110)
        p.setPen(QPen(QColor("#334155"), 1.5))
        p.setBrush(QColor(226, 232, 240, 160))
        p.drawRect(mag)
        for k in range(4):
            r = QRectF(mag.left() + 4, mag.bottom() - 20 - k * 22, mag.width() - 8, 18)
            draw.metal(p, r, "#94a3b8", 2)
        draw.text(p, mag.left() - 2, mag.top() - 10, "magazine", 7, True, draw.MUTED)
        # fixador A (sobre a peca, da esquerda)
        tip_a = draw.cylinder(p, QRectF(206, 276, 62, 22), self.clamp, stroke=50)
        draw.metal(p, QRectF(tip_a.x(), 270, 10, 34), "#0f766e", 2)
        draw.text(p, 206, 264, "Fixador A", 7, True)
        # ejetor C (rente a bancada)
        tip_c = draw.cylinder(p, QRectF(206, 306, 62, 18), self.eject, stroke=150)
        draw.metal(p, QRectF(tip_c.x(), 304, 6, 24), "#be123c", 1)
        draw.text(p, 140, 316, "Ejetor C", 7, True, w=64)
        # rampa e caixa de saida
        p.setPen(QPen(QColor("#334155"), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(560, 332), QPointF(640, 372))
        box = QRectF(630, 360, 76, 40)
        draw.metal(p, box, "#a16207", 4)
        draw.ctext(p, box.center().x(), box.center().y(), f"{self.good} ok / {self.defects}", 7.5, True, draw.WHITE, 76)
        if self.ejected_piece_x is not None:
            x = 560 + self.ejected_piece_x * 0.55
            r = QRectF(x, 300 + self.ejected_piece_x * 0.3, 44, 26)
            draw.metal(p, r, "#94a3b8" if self.ejected_ok else "#f87171", 2)
        # sensores e valvulas
        draw.tag(p, 522, 70, "I0.4 B0", sens["B0"])
        draw.tag(p, 522, 220, "I0.5 B1", sens["B1"])
        draw.tag(p, 522, 112, "Q0.1 desce", out.get("DESCE", False))
        draw.tag(p, 522, 134, "Q0.2 sobe", out.get("SOBE", False))
        draw.tag(p, 522, 156, "Q0.6 refrig.", out.get("REFRIG", False))
        draw.tag(p, 436, 288, "I0.2 peça", sens["PECA"])
        draw.tag(p, 206, 362, "Q0.0 fixa", out.get("FIX", False))
        draw.tag(p, 278, 362, "I0.3 A1", sens["A1"])
        draw.tag(p, 206, 384, "Q0.4 ejeta", out.get("EJETOR", False))
        draw.tag(p, 278, 384, "I0.6 C0", sens["C0"])
        draw.tag(p, 340, 384, "I0.7 C1", sens["C1"])
        # regua de profundidade (N0)
        rx = 616
        draw.card(p, QRectF(600, 14, 108, 330), "N0 broca")
        top_y, h = 50, 240
        p.setPen(QPen(QColor("#94a3b8"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRect(QRectF(rx, top_y, 14, h))
        p.fillRect(QRectF(rx, top_y, 14, h * self.drill), QColor("#3b82f6"))
        for v, lbl, col in ((550, "peça", "#b45309"), (970, "fim", "#16a34a")):
            y = top_y + h * v / 1000
            p.setPen(QPen(QColor(col), 2))
            p.drawLine(QPointF(rx - 4, y), QPointF(rx + 18, y))
            draw.text(p, rx + 22, y, f"{v} {lbl}", 6.5, True, QColor(col), w=60)
        draw.lcd(p, QRectF(608, 300, 92, 34), f"{round(self.drill * 1000):4d}", "#60a5fa", "N0")
        # painel
        draw.card(p, QRectF(14, 14, 176, 316), "Painel")
        draw.lamp(p, QPointF(34, 50), 8, out.get("CICLO", False), draw.GREEN)
        draw.text(p, 48, 50, "CICLO Q0.5", 7.5, True)
        draw.lamp(p, QPointF(34, 76), 8, out.get("TROCAR", False), draw.AMBER)
        draw.text(p, 48, 76, "TROCAR BROCA Q0.7", 7.5, True)
        draw.lcd(p, QRectF(24, 96, 74, 30), f"{self.good:3d}", "#4ade80", "BOAS")
        draw.lcd(p, QRectF(106, 96, 74, 30), f"{self.defects:3d}", "#f87171", "DEFEITO")
        draw.text(p, 24, 146, f"Broca nº {self.tool_no} (N1)", 8, True)
        draw.text(p, 24, 166, f"Furos nesta broca: {self.holes_on_tool}", 7.5, False, draw.MUTED)
        wear = min(1.0, self.wear / WEAR_DULL)
        draw.text(p, 24, 186, "Desgaste", 7, True, draw.MUTED)
        draw.bar(p, QRectF(24, 196, 156, 9), wear, draw.mix(draw.GREEN, draw.RED, wear))
        draw.text(p, 24, 222, "Cavaco no furo", 7, True, draw.MUTED)
        chips = min(1.0, self.chips / CHIP_LIMIT)
        draw.bar(p, QRectF(24, 232, 156, 9), chips, draw.mix(draw.AMBER, draw.RED, chips))
        draw.text(p, 24, 258, "Mandril", 7, True, draw.MUTED)
        draw.bar(p, QRectF(24, 268, 156, 9), self.spindle, draw.BLUE)
        if self.broken:
            draw.plate(p, QRectF(24, 292, 156, 24), "BROCA QUEBRADA", "#b91c1c")
        draw.push_button(p, QRectF(20, 342, 150, 30), "PARTIDA I0.0", self.is_pressed("PARTIDA"), draw.GREEN)
        draw.switch(p, QRectF(20, 378, 150, 28), "EMERGÊNCIA I0.1", self.is_pressed("EMERG"))
        draw.push_button(p, QRectF(20, 414, 150, 28), "Trocar broca", False, draw.AMBER)
