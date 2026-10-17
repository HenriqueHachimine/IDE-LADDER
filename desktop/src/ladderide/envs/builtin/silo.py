"""Silo de envase: esteira leva caixas ate a valvula, que as enche ate o sensor de nivel."""
from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import DelayLine, approach, torricelli
from ..registry import register

# Escala: 100 px = 1 m. Tempo em s.
VALVE_X = 360.0         # eixo do bico da valvula
BOX_W, BOX_H = 70.0, 48.0
BELT_Y = 320.0
SPACING = 210.0
BELT_SPEED = 60.0       # px/s (0,6 m/s)
BELT_ACCEL = 240.0      # px/s^2: partida suave do motor (0,25 s ate a velocidade)
BELT_DECEL = 400.0      # px/s^2: inercia ao desligar (caixa passa ~4,5 px do ponto)
PROX_X = VALVE_X + BOX_W / 2 - 5.0   # feixe da fotocelula: borda dianteira da caixa interrompe aqui
NOZZLE_MARGIN = 6.0     # produto so entra se o bico estiver sobre a boca da caixa
LEVEL_WINDOW = 20.0     # sensor de nivel (ultrassonico) mede a caixa sob o bico
LEVEL_TRIP = 95.0       # % em que o sensor de nivel atua
FLOW_MAX = 32.0         # % de caixa por segundo com silo cheio e valvula toda aberta
VALVE_OPEN_S, VALVE_CLOSE_S = 0.15, 0.10   # tempo de abertura/fechamento do solenoide
FALL_S = 0.35           # tempo de queda do produto do bico ate a caixa
SILO_CAPACITY = 25.0    # caixas
REFILL_ON, REFILL_OFF, REFILL_RATE = 0.20, 0.90, 0.6   # reabastecimento automatico (caixas/s)


@dataclass
class Box:
    x: float            # borda esquerda
    level: float = 0.0  # 0..100+ % do volume

    @property
    def center(self) -> float:
        return self.x + BOX_W / 2


@register
class SiloEnvironment(Environment):
    id = "silo"
    name = "Silo de envase"
    description = ("A esteira traz caixas vazias. A fotocelula (I0.2) ve a caixa quando ela chega sob o bico; "
                   "a esteira tem inercia e a caixa passa um pouco do ponto. A valvula demora a abrir e a fechar, "
                   "a vazao cai com o nivel do silo e o produto em queda continua caindo depois que a valvula "
                   "fecha. O sensor de nivel (I0.3) atua com 95%. STOP e um botao NF.")
    example = "ambientes/silo.ladproj"
    inputs = [
        IOPoint("START", "I0.0", "Start", "Botao de partida (NA)", BUTTON),
        IOPoint("STOP", "I0.1", "Stop", "Botao de parada (NF: le 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("PROX", "I0.2", "Sensor_Presenca", "Fotocelula: caixa interrompendo o feixe sob o bico"),
        IOPoint("LEVEL", "I0.3", "Sensor_Nivel", "Sensor de nivel: caixa sob o bico com 95% ou mais"),
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
        self.belt_v = 0.0               # px/s
        self.valve = 0.0                # abertura 0..1
        self.silo = 0.8 * SILO_CAPACITY
        self.refilling = False
        self.falling = DelayLine(FALL_S)
        self.spilled = 0.0
        self.overflow = 0.0
        self.shipped_full = 0
        self.shipped_partial = 0
        self.last_fill = None           # nivel final da ultima caixa expedida

    # ------------------------------------------------------------- fisica
    def box_at(self, x: float, margin: float = 0.0) -> Box | None:
        return next((b for b in self.boxes if b.x + margin <= x <= b.x + BOX_W - margin), None)

    def box_under_nozzle(self) -> Box | None:
        return self.box_at(VALVE_X, NOZZLE_MARGIN)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        # esteira com inercia (motor de inducao + redutor)
        self.belt_v = approach(self.belt_v, BELT_SPEED if out["MOTOR"] else 0.0, BELT_ACCEL, BELT_DECEL, dt)
        d = self.belt_v * dt
        if d:
            self.belt_pos += d
            for b in self.boxes:
                b.x += d
            for b in [b for b in self.boxes if b.x > 650]:
                self.boxes.remove(b)
                self.last_fill = b.level
                if b.level >= 90:
                    self.shipped_full += 1
                else:
                    self.shipped_partial += 1
            while min(b.x for b in self.boxes) > -BOX_W - 10:
                self.boxes.append(Box(min(b.x for b in self.boxes) - SPACING))
        # valvula: abre/fecha com atraso; vazao de Torricelli pelo nivel do silo
        self.valve = approach(self.valve, 1.0 if out["VALVE"] else 0.0, 1 / VALVE_OPEN_S, 1 / VALVE_CLOSE_S, dt)
        flow = FLOW_MAX * self.valve * torricelli(self.silo / SILO_CAPACITY) if self.silo > 0 else 0.0
        released = min(flow * dt, self.silo * 100)
        self.silo -= released / 100
        self.falling.push(released)
        landed = self.falling.advance(dt)
        if landed:
            box = self.box_under_nozzle()
            if box is None:
                self.spilled += landed
            else:
                box.level += landed
                if box.level > 115:
                    self.overflow += landed
        # reabastecimento automatico do silo (nao comandado pelo CLP)
        frac = self.silo / SILO_CAPACITY
        if frac <= REFILL_ON:
            self.refilling = True
        elif frac >= REFILL_OFF:
            self.refilling = False
        if self.refilling:
            self.silo = min(SILO_CAPACITY, self.silo + REFILL_RATE * dt)

    def sensors(self) -> dict[str, bool]:
        level_box = next((b for b in self.boxes if abs(b.center - VALVE_X) <= LEVEL_WINDOW), None)
        return {"PROX": self.box_at(PROX_X) is not None,
                "LEVEL": level_box is not None and level_box.level >= LEVEL_TRIP}

    def alarms(self) -> list[str]:
        out = []
        if self.spilled >= 1:
            out.append(f"Produto derramado na esteira ({self.spilled:.0f}% de uma caixa)")
        if self.overflow >= 1:
            out.append("Caixa transbordando: a valvula ficou aberta tempo demais")
        if self.shipped_partial:
            out.append(f"{self.shipped_partial} caixa(s) sairam com menos de 90%")
        if self.silo <= 0.01:
            out.append("Silo vazio")
        return out

    def stats(self) -> list[str]:
        last = f", ultima com {self.last_fill:.0f}%" if self.last_fill is not None else ""
        refill = " (reabastecendo)" if self.refilling else ""
        return [f"Caixas cheias expedidas: {self.shipped_full}{last}",
                f"Silo: {100 * self.silo / SILO_CAPACITY:.0f}%{refill} | esteira {self.belt_v / 100:.2f} m/s | "
                f"valvula {100 * self.valve:.0f}%"]

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
        top = 212 - 192 * self.silo / SILO_CAPACITY                 # nivel real do silo
        p.fillRect(QRectF(290, top, 140, 212 - top + 10), QColor(217, 160, 70, 200))
        if self.refilling:
            p.fillRect(QRectF(354, 0, 12, top), QColor(217, 160, 70, 160))
        p.restore()
        draw.text(p, 360, 40, "SILO", 9, True, QColor("#334155"), Qt.AlignHCenter | Qt.AlignVCenter, 100)
        # tubo + valvula
        p.setPen(QPen(QColor("#475569"), 1.2))
        p.setBrush(QColor("#94a3b8"))
        p.drawRect(QRectF(353, 212, 14, 36))
        valve_on = out["VALVE"]
        p.setBrush(draw.GREEN if self.valve > 0.5 else (draw.AMBER if self.valve > 0.01 else QColor("#64748b")))
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
        if self.falling.items:                                     # produto em queda (atraso de transporte)
            box = self.box_under_nozzle()
            bottom = BELT_Y - BOX_H * min(box.level, 100) / 100 if box else BELT_Y
            span = bottom - 248
            for t_left, _amount in self.falling.items:
                y = 248 + span * (1 - t_left / FALL_S)
                p.fillRect(QRectF(357, y - 3, 6, 6), QColor(217, 160, 70, 230))

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
            if b.level >= 90:
                draw.text(p, r.center().x(), r.top() - 8, "cheia", 7, True, draw.GREEN,
                          Qt.AlignHCenter | Qt.AlignVCenter, 60)

        # sensor de presenca (abaixo da esteira)
        draw.sensor(p, QRectF(PROX_X - 6, 372, 12, 30), sens["PROX"])           # fotocelula (feixe vertical)
        draw.beam(p, QPointF(PROX_X, 372), QPointF(PROX_X, BELT_Y - BOX_H + 6), sens["PROX"])
        draw.text(p, PROX_X + 10, 382, "Presenca", 7.5, True)
        draw.tag(p, PROX_X + 10, 398, "I0.2", sens["PROX"])

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
