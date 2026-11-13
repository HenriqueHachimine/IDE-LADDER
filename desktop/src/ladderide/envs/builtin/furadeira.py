"""Furadeira automatica: sequencia de etapas com cilindros pneumaticos e mandril."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

CLAMP_S = 0.4                 # fixador: avanca/recua em 0,4 s (mola no retorno)
DRILL_DOWN, DRILL_UP = 0.5, 0.8   # curso/s: desce em 2 s, sobe em 1,25 s
SURFACE = 0.55                # a broca toca a peca em 55% do curso
THROUGH = 0.97                # furo passante a partir de 97% (o sensor B1 atua em 98%)
SPIN_UP, SPIN_DOWN = 2.0, 1.0     # mandril: 0,5 s para acelerar e 1 s para parar
EJECT_S = 0.3
FEED_S = 0.8                  # o magazine solta a proxima peca em 0,8 s
DWELL_OK_S = 0.3              # tempo no fundo do furo para tirar a rebarba


@register
class DrillEnvironment(Environment):
    id = "furadeira"
    name = "Furadeira automática (sequência)"
    description = ("Ciclo por etapas: fixar a peça (A+), ligar o mandril e descer a broca (B+), esperar no fundo, "
                   "subir (B-), soltar (A-) e ejetar (C+ / C-). Cada etapa termina pelo sensor do cilindro. Descer "
                   "com o mandril parado quebra a broca; furar sem fixar gira a peça; ejetar com a peça presa bate "
                   "o ejetor. O magazine coloca a próxima peça depois que o ejetor volta.")
    example = "ambientes/furadeira.ladproj"
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
        self.good = 0
        self.defects = 0
        self.broken = False
        self.spun = False
        self.eject_crash = False
        self.released_inside = False
        self.both_ms = 0
        self.emergency_moves = 0

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
        if down and not up and not self.broken:
            self.drill = min(1.0, self.drill + DRILL_DOWN * dt)
        elif up and not down:
            self.drill = max(0.0, self.drill - DRILL_UP * dt)
        cutting = self.piece and self.drill > SURFACE and self.drill > old
        if cutting:
            if self.spindle < 0.9:
                self.broken = True                   # broca parada contra a peca
                self.drill = old
            elif self.clamp < 0.95:
                self.spun = True                     # a peca gira sem o fixador
            else:
                self.depth = max(self.depth, min(1.0, (self.drill - SURFACE) / (THROUGH - SURFACE)))
        if self.piece and self.drill >= THROUGH and self.spindle >= 0.9:
            self.dwell += dt
        if self.piece and self.clamp < 0.5 and self.drill > SURFACE + 0.02 and self.depth > 0:
            self.released_inside = True
        # ejetor: empurra a peca para a rampa de saida
        self.eject = approach(self.eject, 1.0 if out["EJETOR"] else 0.0, 1 / EJECT_S, 1 / EJECT_S, dt)
        if self.eject > 0.3 and self.piece:
            if self.clamp > 0.1 or self.drill > SURFACE:
                self.eject_crash = True
            elif self.eject > 0.9:
                ok = self.depth >= 0.99 and self.dwell >= DWELL_OK_S
                self.good += ok
                self.defects += not ok
                self.piece = False
                self.ejected_piece_x = 0.0
        if self.ejected_piece_x is not None:
            self.ejected_piece_x += 160 * dt
            if self.ejected_piece_x > 140:
                self.ejected_piece_x = None
        # magazine: a proxima peca cai com o ejetor recuado
        if not self.piece and self.eject < 0.02:
            self.feed_t += dt
            if self.feed_t >= FEED_S:
                self.piece, self.depth, self.dwell, self.feed_t = True, 0.0, 0.0, 0.0
        else:
            self.feed_t = 0.0

    def sensors(self) -> dict[str, bool]:
        return {"PECA": self.piece, "A1": self.clamp >= 0.98, "B0": self.drill <= 0.02, "B1": self.drill >= 0.98,
                "C0": self.eject <= 0.02, "C1": self.eject >= 0.98}

    def alarms(self) -> list[str]:
        out = []
        if self.broken:
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
        return out

    def stats(self) -> list[str]:
        return [f"Peças boas: {self.good} | com defeito (furo raso ou rebarba): {self.defects}",
                f"Broca: {self.drill * 100:.0f}% do curso | furo atual: {self.depth * 100:.0f}% | "
                f"mandril {self.spindle * 100:.0f}%"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"PARTIDA": (24, 330, 140, 30), "EMERG": (24, 370, 140, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f8fafc"))
        sens = self.sensors()
        out = self.out
        # bancada
        bench = QRectF(190, 300, 330, 20)
        p.setPen(QPen(QColor("#1e293b"), 1.5))
        p.setBrush(QColor("#64748b"))
        p.drawRect(bench)
        # coluna da furadeira e cabecote
        p.setBrush(QColor("#475569"))
        p.drawRect(QRectF(470, 40, 26, 260))
        head_y = 60 + 150 * self.drill
        p.setBrush(QColor("#1d4ed8") if out.get("MOTOR") else QColor("#334155"))
        p.drawRoundedRect(QRectF(330, head_y - 40, 150, 44), 6, 6)
        draw.text(p, 340, head_y - 26, "mandril", 7.5, True, draw.WHITE)
        draw.tag(p, 400, head_y - 26, "Q0.3", out.get("MOTOR", False))
        # broca (gira): a ponta toca a peca em SURFACE e atravessa no fim do curso
        tip_len = 240 - (60 + 150 * SURFACE)
        p.setPen(QPen(QColor("#cbd5e1") if not self.broken else draw.RED, 5))
        tip = head_y + tip_len if not self.broken else head_y + tip_len * 0.5
        p.drawLine(QPointF(370, head_y + 4), QPointF(370, tip))
        p.setPen(QPen(QColor("#64748b"), 1.2))
        off = (self.spin_angle % 1.0) * 10
        y = head_y + 8 + off
        while y < tip - 2:
            p.drawLine(QPointF(366, y), QPointF(374, y + 4))
            y += 10
        # peca
        piece = QRectF(320, 240, 100, 60)
        if self.piece:
            p.setPen(QPen(QColor("#78350f"), 1.5))
            p.setBrush(QColor("#d97706"))
            p.drawRect(piece)
            if self.depth > 0:
                p.fillRect(QRectF(366, piece.top(), 8, piece.height() * self.depth), QColor("#451a03"))
        p.setPen(QPen(QColor("#1e293b"), 1.5))
        # fixador (cilindro A, da esquerda, na altura de cima da peca)
        cyl = QRectF(200, 244, 70, 26)
        p.setBrush(QColor("#cbd5e1"))
        p.drawRect(cyl)
        rod = 42 * self.clamp
        p.setBrush(QColor("#94a3b8"))
        p.drawRect(QRectF(cyl.right(), 252, rod, 10))
        p.setBrush(QColor("#0f766e"))
        p.drawRect(QRectF(cyl.right() + rod, 242, 8, 30))
        draw.text(p, 200, 232, "Fixador A", 7.5, True)
        # ejetor (cilindro C, rente a bancada: empurra a peca solta para a rampa)
        ej = QRectF(200, 278, 70, 20)
        p.setBrush(QColor("#cbd5e1"))
        p.drawRect(ej)
        er = 160 * self.eject
        p.setBrush(QColor("#94a3b8"))
        p.drawRect(QRectF(ej.right(), 284, er, 8))
        draw.text(p, 120, 288, "Ejetor C", 7.5, True, w=78)
        if self.ejected_piece_x is not None:
            p.setBrush(QColor("#d97706"))
            p.drawRect(QRectF(530 + self.ejected_piece_x * 0.5, 280, 50, 30))
        p.setPen(QPen(QColor("#334155"), 3))
        p.drawLine(QPointF(520, 310), QPointF(630, 330))          # rampa de saida
        # etiquetas dos sensores e valvulas
        draw.tag(p, 510, 70, "I0.4 B0 em cima", sens["B0"])
        draw.tag(p, 510, 220, "I0.5 B1 embaixo", sens["B1"])
        draw.tag(p, 510, 110, "Q0.1 desce", out.get("DESCE", False))
        draw.tag(p, 510, 132, "Q0.2 sobe", out.get("SOBE", False))
        draw.tag(p, 430, 262, "I0.2 peça", sens["PECA"])
        draw.text(p, 196, 334, "Fixador:", 7.5, True, w=60)
        draw.tag(p, 256, 334, "Q0.0", out.get("FIX", False))
        draw.tag(p, 300, 334, "I0.3 A1", sens["A1"])
        draw.text(p, 196, 358, "Ejetor:", 7.5, True, w=60)
        draw.tag(p, 256, 358, "Q0.4", out.get("EJETOR", False))
        draw.tag(p, 300, 358, "I0.6 C0", sens["C0"])
        draw.tag(p, 362, 358, "I0.7 C1", sens["C1"])
        # painel
        draw.panel(p, QRectF(14, 40, 160, 270), "PAINEL")
        draw.lamp(p, QPointF(36, 80), 10, out.get("CICLO", False), draw.GREEN)
        draw.text(p, 52, 80, "CICLO  Q0.5", 8, True)
        draw.text(p, 26, 120, f"Boas: {self.good}", 9, True, draw.GREEN)
        draw.text(p, 26, 140, f"Defeito: {self.defects}", 9, True, draw.RED)
        draw.push_button(p, QRectF(24, 330, 140, 30), "PARTIDA  I0.0", self.is_pressed("PARTIDA"), draw.GREEN)
        draw.switch(p, QRectF(24, 370, 140, 28), "EMERGÊNCIA I0.1", self.is_pressed("EMERG"))
