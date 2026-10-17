"""Silo de envase: esteira leva caixas ate a valvula, que as enche ate o sensor de nivel."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..registry import register

VALVE_X = 360.0         # eixo da valvula / sensor de presenca
BOX_W, BOX_H = 70.0, 48.0
BELT_Y = 320.0
SPEED = 60.0            # px/s
FILL_RATE = 25.0        # % da caixa por segundo
SPACING = 210.0
PROX_WINDOW = 4.0       # px: tolerancia do sensor de presenca
UNDER_WINDOW = 30.0     # px: caixa recebe produto se estiver a menos disso da valvula


@dataclass
class Box:
    x: float            # borda esquerda
    level: float = 0.0  # 0..100+ %

    @property
    def center(self) -> float:
        return self.x + BOX_W / 2


@register
class SiloEnvironment(Environment):
    id = "silo"
    name = "Silo de envase"
    description = ("A esteira traz caixas vazias. Quando a caixa chega sob a valvula (sensor de presenca), "
                   "pare a esteira e abra a valvula ate o sensor de nivel indicar caixa cheia; depois "
                   "religue a esteira. START/STOP controlam o processo (STOP e um botao NF).")
    example = "ambientes/silo.ladproj"
    inputs = [
        IOPoint("START", "I0.0", "Start", "Botao de partida (NA)", BUTTON),
        IOPoint("STOP", "I0.1", "Stop", "Botao de parada (NF: le 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("PROX", "I0.2", "Sensor_Presenca", "Caixa posicionada sob a valvula"),
        IOPoint("LEVEL", "I0.3", "Sensor_Nivel", "Caixa sob a valvula esta cheia"),
    ]
    outputs = [
        IOPoint("MOTOR", "Q0.0", "Motor_Esteira", "Motor da esteira"),
        IOPoint("VALVE", "Q0.1", "Valvula", "Valvula solenoide do silo"),
        IOPoint("RUN", "Q0.2", "Lampada_Run", "Lampada RUN (processo ligado)"),
        IOPoint("FILL", "Q0.3", "Lampada_Fill", "Lampada FILL (enchendo)"),
        IOPoint("FULL", "Q0.4", "Lampada_Full", "Lampada FULL (caixa cheia)"),
    ]

    def reset(self) -> None:
        self.boxes = [Box(VALVE_X - BOX_W / 2 - 230), Box(VALVE_X - BOX_W / 2 - 230 - SPACING)]
        self.belt_pos = 0.0
        self.spilled = 0.0
        self.overflow = 0.0
        self.shipped_full = 0
        self.shipped_partial = 0

    # ------------------------------------------------------------- fisica
    def box_under_valve(self, window: float = UNDER_WINDOW) -> Box | None:
        return next((b for b in self.boxes if abs(b.center - VALVE_X) <= window), None)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        if out["MOTOR"]:
            d = SPEED * dt
            self.belt_pos += d
            for b in self.boxes:
                b.x += d
            for b in [b for b in self.boxes if b.x > 650]:
                self.boxes.remove(b)
                if b.level >= 100:
                    self.shipped_full += 1
                else:
                    self.shipped_partial += 1
            while min(b.x for b in self.boxes) > -BOX_W - 10:
                self.boxes.append(Box(min(b.x for b in self.boxes) - SPACING))
        if out["VALVE"]:
            box = self.box_under_valve()
            amount = FILL_RATE * dt
            if box is None:
                self.spilled += amount
            else:
                box.level += amount
                if box.level > 110:
                    self.overflow += amount

    def sensors(self) -> dict[str, bool]:
        box = self.box_under_valve()
        return {"PROX": self.box_under_valve(PROX_WINDOW) is not None,
                "LEVEL": box is not None and box.level >= 100}

    def alarms(self) -> list[str]:
        out = []
        if self.spilled >= 1:
            out.append(f"Produto derramado na esteira ({self.spilled:.0f}% de uma caixa): valvula aberta sem caixa")
        if self.overflow >= 1:
            out.append("Caixa transbordando: a valvula continuou aberta com a caixa cheia")
        if self.shipped_partial:
            out.append(f"{self.shipped_partial} caixa(s) sairam sem encher")
        return out

    def stats(self) -> list[str]:
        return [f"Caixas cheias expedidas: {self.shipped_full}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"START": (30, 150, 130, 28), "STOP": (30, 186, 130, 28)}

    def paint(self, p: QPainter) -> None:
        out, sens = self.out, self.sensors()
        p.setRenderHint(QPainter.Antialiasing)
        # fundo
        sky = QLinearGradient(0, 0, 0, 420)
        sky.setColorAt(0, QColor("#e0f2fe"))
        sky.setColorAt(1, QColor("#f8fafc"))
        p.fillRect(QRectF(0, 0, 640, 420), sky)
        p.fillRect(QRectF(0, 360, 640, 60), QColor("#cbd5e1"))

        # silo
        body = QRectF(300, 20, 120, 130)
        grad = QLinearGradient(body.left(), 0, body.right(), 0)
        grad.setColorAt(0, QColor("#cbd5e1"))
        grad.setColorAt(0.5, QColor("#f1f5f9"))
        grad.setColorAt(1, QColor("#94a3b8"))
        silo = QPainterPath()
        silo.moveTo(300, 20)
        silo.lineTo(420, 20)
        silo.lineTo(420, 150)
        silo.lineTo(368, 212)
        silo.lineTo(352, 212)
        silo.lineTo(300, 150)
        silo.closeSubpath()
        p.setPen(QPen(QColor("#475569"), 1.5))
        p.setBrush(grad)
        p.drawPath(silo)
        p.save()
        p.setClipPath(silo)
        p.fillRect(QRectF(290, 70, 140, 160), QColor(217, 160, 70, 200))  # produto
        p.restore()
        draw.text(p, 360, 40, "SILO", 9, True, QColor("#334155"), Qt.AlignHCenter | Qt.AlignVCenter, 100)
        # tubo + valvula
        p.setPen(QPen(QColor("#475569"), 1.2))
        p.setBrush(QColor("#94a3b8"))
        p.drawRect(QRectF(353, 212, 14, 36))
        valve_on = out["VALVE"]
        p.setBrush(draw.GREEN if valve_on else QColor("#64748b"))
        p.drawRect(QRectF(348, 226, 24, 10))
        p.setBrush(QColor("#334155"))
        p.drawRect(QRectF(300, 222, 40, 18))                       # bobina do solenoide
        p.setPen(QPen(QColor("#e2e8f0"), 1))
        for k in range(5):
            p.drawLine(QPointF(304 + k * 8, 224), QPointF(308 + k * 8, 238))
        p.setPen(QPen(QColor("#475569"), 2))
        p.drawLine(QPointF(340, 231), QPointF(348, 231))
        draw.text(p, 268, 212, "Valvula", 7.5, True)
        draw.tag(p, 262, 250, "Q0.1", valve_on)
        if valve_on:                                               # jato de produto
            box = self.box_under_valve()
            bottom = BELT_Y - (BOX_H * min(box.level, 100) / 100 if box else 0) if box else BELT_Y
            p.fillRect(QRectF(356, 248, 8, bottom - 248), QColor(217, 160, 70, 220))

        # sensor de nivel (acima da caixa)
        draw.sensor(p, QRectF(392, 236, 12, 30), sens["LEVEL"])
        draw.beam(p, QPointF(398, 266), QPointF(398, BELT_Y - BOX_H), sens["LEVEL"])
        draw.text(p, 410, 244, "Nivel", 7.5, True)
        draw.tag(p, 410, 260, "I0.3", sens["LEVEL"])

        # esteira
        belt = QRectF(10, BELT_Y, 590, 34)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#334155"))
        p.drawRoundedRect(belt, 17, 17)
        p.setBrush(QColor("#e2e8f0"))
        for k in range(12):
            cx = 30 + k * 50
            c = QPointF(cx, BELT_Y + 17)
            p.setBrush(QColor("#e2e8f0"))
            p.drawEllipse(c, 10, 10)
            a = self.belt_pos / 10.0
            p.drawLine(c, QPointF(cx + 9 * math.cos(a), BELT_Y + 17 + 9 * math.sin(a)))
        p.setPen(QPen(QColor("#f97316"), 3))
        p.drawLine(QPointF(20, BELT_Y), QPointF(590, BELT_Y))

        # caixas
        for b in self.boxes:
            r = QRectF(b.x, BELT_Y - BOX_H, BOX_W, BOX_H)
            p.setPen(QPen(QColor("#78350f"), 1.5))
            p.setBrush(QColor("#fde68a"))
            p.drawRect(r)
            lvl = min(b.level, 100) / 100
            if lvl > 0:
                p.fillRect(QRectF(r.left() + 2, r.bottom() - (BOX_H - 4) * lvl - 2, BOX_W - 4, (BOX_H - 4) * lvl),
                           QColor(217, 160, 70))
            if b.level >= 100:
                draw.text(p, r.center().x(), r.top() - 8, "cheia", 7, True, draw.GREEN,
                          Qt.AlignHCenter | Qt.AlignVCenter, 60)

        # sensor de presenca (abaixo da esteira)
        draw.sensor(p, QRectF(VALVE_X - 6, 372, 12, 30), sens["PROX"])
        draw.beam(p, QPointF(VALVE_X, 372), QPointF(VALVE_X, BELT_Y + 34), sens["PROX"])
        draw.text(p, VALVE_X + 12, 382, "Presenca", 7.5, True)
        draw.tag(p, VALVE_X + 12, 398, "I0.2", sens["PROX"])

        # motor
        draw.motor(p, QPointF(560, 388), 16, out["MOTOR"], self.belt_pos / 12.0)
        draw.text(p, 470, 380, "Motor", 7.5, True)
        draw.tag(p, 470, 396, "Q0.0", out["MOTOR"])

        # painel de comando
        draw.panel(p, QRectF(20, 20, 150, 204), "PAINEL")
        for k, (key, label, color, addr) in enumerate((("RUN", "RUN", draw.GREEN, "Q0.2"),
                                                      ("FILL", "FILL", draw.AMBER, "Q0.3"),
                                                      ("FULL", "FULL", draw.RED, "Q0.4"))):
            y = 50 + k * 32
            draw.lamp(p, QPointF(42, y), 10, out[key], color)
            draw.text(p, 60, y, label, 8.5, True)
            draw.tag(p, 112, y, addr, out[key])
        draw.push_button(p, QRectF(30, 150, 130, 28), "START  I0.0", self.is_pressed("START"), draw.GREEN)
        draw.push_button(p, QRectF(30, 186, 130, 28), "STOP  I0.1 (NF)", self.is_pressed("STOP"), draw.RED)
