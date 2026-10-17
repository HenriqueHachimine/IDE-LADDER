"""Portao de garagem com motor reversivel, fins de curso e fotocelula de seguranca."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..registry import register

DOOR = QRectF(210, 70, 270, 260)     # vao do portao
SPEED = 12.5                         # % por segundo (8 s de curso)
VEHICLE_TOP = 35.0                   # % de abertura abaixo da qual o portao toca o veiculo
STRAIN_MS = 300


@register
class GarageDoorEnvironment(Environment):
    id = "portao"
    name = "Portao de garagem"
    description = ("ABRIR e FECHAR acionam o motor (sobe/desce) ate os fins de curso LS1 (aberto) e LS2 "
                   "(fechado). PARAR e um botao NF. A fotocelula detecta um veiculo sob o portao: o portao "
                   "nao pode descer sobre ele. Clique no botao 'Veiculo' para colocar ou retirar o carro.")
    example = "ambientes/portao.ladproj"
    inputs = [
        IOPoint("OPEN", "I0.0", "Abrir", "Botao ABRIR (NA)", BUTTON),
        IOPoint("CLOSE", "I0.1", "Fechar", "Botao FECHAR (NA)", BUTTON),
        IOPoint("STOP", "I0.2", "Parar", "Botao PARAR (NF: le 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("LS1", "I0.3", "Fim_Curso_Aberto", "LS1: portao totalmente aberto"),
        IOPoint("LS2", "I0.4", "Fim_Curso_Fechado", "LS2: portao totalmente fechado"),
        IOPoint("PHOTO", "I0.5", "Fotocelula", "Veiculo/obstaculo sob o portao"),
    ]
    outputs = [
        IOPoint("UP", "Q0.0", "Motor_Sobe", "Motor no sentido de abrir"),
        IOPoint("DOWN", "Q0.1", "Motor_Desce", "Motor no sentido de fechar"),
        IOPoint("AJAR", "Q0.2", "Lampada_Entreaberto", "Lampada ENTREABERTO"),
        IOPoint("OPENED", "Q0.3", "Lampada_Aberto", "Lampada ABERTO"),
        IOPoint("SHUT", "Q0.4", "Lampada_Fechado", "Lampada FECHADO"),
    ]

    def reset(self) -> None:
        self.pos = 0.0               # 0 = fechado, 100 = aberto
        self.vehicle = False
        self.both_ms = 0
        self.strain_ms = 0
        self.hit_vehicle = False
        self.cycles = 0
        self._was_open = False

    def on_control(self, key: str, down: bool) -> None:
        if key == "VEHICLE" and down and self.pos >= VEHICLE_TOP:
            self.vehicle = not self.vehicle

    def press(self, key: str, down: bool) -> None:
        if key == "VEHICLE":
            self.on_control(key, down)
        else:
            super().press(key, down)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        up, down = out["UP"], out["DOWN"]
        delta = SPEED * dt_ms / 1000.0
        if up and down:
            self.both_ms += dt_ms
            return
        self.both_ms = 0
        floor = VEHICLE_TOP if self.vehicle else 0.0
        blocked = (up and self.pos >= 100) or (down and self.pos <= floor)
        self.strain_ms = self.strain_ms + dt_ms if blocked else 0
        if down and self.vehicle and self.pos <= floor:
            self.hit_vehicle = True
        if up:
            self.pos = min(100.0, self.pos + delta)
        elif down:
            self.pos = max(floor, self.pos - delta)
        if self.pos >= 99.5:
            self._was_open = True
        elif self.pos <= 0.5 and self._was_open:
            self._was_open = False
            self.cycles += 1

    def sensors(self) -> dict[str, bool]:
        return {"LS1": self.pos >= 99.5, "LS2": self.pos <= 0.5, "PHOTO": self.vehicle}

    def alarms(self) -> list[str]:
        out = []
        if self.both_ms > 0:
            out.append("PERIGO: motor comandado para subir e descer ao mesmo tempo (falta intertravamento)")
        if self.hit_vehicle:
            out.append("O portao desceu sobre o veiculo! Use a fotocelula (I0.5) para impedir")
        if self.strain_ms > STRAIN_MS and not self.hit_vehicle:
            end = "superior" if self.pos >= 99.5 else "inferior"
            out.append(f"Motor forcando contra o fim de curso {end}: desligue o motor no fim de curso")
        return out

    def stats(self) -> list[str]:
        return [f"Abertura: {self.pos:.0f}%", f"Ciclos completos (abrir e fechar): {self.cycles}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"OPEN": (30, 214, 130, 28), "CLOSE": (30, 250, 130, 28), "STOP": (30, 286, 130, 28),
                "VEHICLE": (500, 360, 120, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        out, sens = self.out, self.sensors()
        p.fillRect(QRectF(0, 0, 640, 340), QColor("#fef3c7"))
        p.fillRect(QRectF(0, 0, 640, 40), QColor("#d6d3d1"))
        p.fillRect(QRectF(0, 340, 640, 80), QColor("#a8a29e"))
        # interior da garagem e veiculo
        p.fillRect(DOOR, QColor("#44403c"))
        if self.vehicle:
            car = QRectF(DOOR.left() + 40, DOOR.bottom() - 70, 190, 62)
            p.setPen(QPen(QColor("#7f1d1d"), 1.5))
            p.setBrush(QColor("#dc2626"))
            p.drawRoundedRect(QRectF(car.left(), car.top() + 20, car.width(), 34), 8, 8)
            p.drawRoundedRect(QRectF(car.left() + 30, car.top(), 110, 30), 10, 10)
            p.setBrush(QColor("#bae6fd"))
            p.drawRoundedRect(QRectF(car.left() + 40, car.top() + 5, 40, 18), 4, 4)
            p.drawRoundedRect(QRectF(car.left() + 88, car.top() + 5, 42, 18), 4, 4)
            p.setBrush(QColor("#111827"))
            p.drawEllipse(QPointF(car.left() + 40, car.bottom()), 13, 13)
            p.drawEllipse(QPointF(car.right() - 40, car.bottom()), 13, 13)
        # folha do portao (sobe)
        bottom = DOOR.bottom() - DOOR.height() * self.pos / 100
        leaf = QRectF(DOOR.left(), DOOR.top(), DOOR.width(), bottom - DOOR.top())
        grad = QLinearGradient(leaf.left(), 0, leaf.right(), 0)
        grad.setColorAt(0, QColor("#0f766e"))
        grad.setColorAt(0.5, QColor("#14b8a6"))
        grad.setColorAt(1, QColor("#0f766e"))
        p.fillRect(leaf, grad)
        p.setPen(QPen(QColor("#115e59"), 1.5))
        y = bottom - 26
        while y > DOOR.top():
            p.drawLine(QPointF(leaf.left(), y), QPointF(leaf.right(), y))
            y -= 26
        p.setPen(QPen(QColor("#1c1917"), 6))
        p.drawLine(QPointF(DOOR.left() - 3, DOOR.top() - 3), QPointF(DOOR.right() + 3, DOOR.top() - 3))
        p.drawLine(QPointF(DOOR.left() - 3, DOOR.top() - 3), QPointF(DOOR.left() - 3, DOOR.bottom()))
        p.drawLine(QPointF(DOOR.right() + 3, DOOR.top() - 3), QPointF(DOOR.right() + 3, DOOR.bottom()))
        draw.text(p, DOOR.center().x(), DOOR.top() - 16, f"{self.pos:.0f}% aberto", 8, True,
                  QColor("#44403c"), Qt.AlignHCenter | Qt.AlignVCenter, 120)

        # fins de curso e fotocelula
        for key, yy, addr, name in (("LS1", DOOR.top() + 4, "I0.3", "LS1"), ("LS2", DOOR.bottom() - 30, "I0.4", "LS2")):
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#7f1d1d"))
            p.drawRoundedRect(QRectF(DOOR.left() - 28, yy, 18, 26), 3, 3)
            draw.lamp(p, QPointF(DOOR.left() - 19, yy + 7), 4, sens[key], draw.GREEN)
            draw.text(p, DOOR.left() - 74, yy + 6, name, 8, True)
            draw.tag(p, DOOR.left() - 74, yy + 22, addr, sens[key])
        ph_y = DOOR.bottom() - 40
        draw.sensor(p, QRectF(DOOR.left() + 2, ph_y - 5, 16, 10), sens["PHOTO"], vertical=False)
        draw.sensor(p, QRectF(DOOR.right() - 18, ph_y - 5, 16, 10), sens["PHOTO"], vertical=False)
        draw.beam(p, QPointF(DOOR.left() + 18, ph_y), QPointF(DOOR.right() - 18, ph_y), sens["PHOTO"])
        draw.tag(p, DOOR.right() + 10, ph_y, "I0.5 fotocelula", sens["PHOTO"])

        # motor
        mc = QPointF(DOOR.right() + 34, 40)
        draw.motor(p, mc, 16, out["UP"] or out["DOWN"], -self.pos / 6.0)
        draw.arrow(p, QPointF(mc.x() + 40, mc.y() - 8), 14, True, out["UP"])
        draw.arrow(p, QPointF(mc.x() + 40, mc.y() + 10), 14, False, out["DOWN"])
        draw.tag(p, mc.x() + 50, mc.y() - 8, "Q0.0 sobe", out["UP"])
        draw.tag(p, mc.x() + 50, mc.y() + 12, "Q0.1 desce", out["DOWN"])

        # painel
        draw.panel(p, QRectF(20, 70, 150, 254), "PAINEL")
        for k, (key, label, color, addr) in enumerate((("AJAR", "ENTREABERTO", draw.AMBER, "Q0.2"),
                                                      ("OPENED", "ABERTO", draw.GREEN, "Q0.3"),
                                                      ("SHUT", "FECHADO", draw.RED, "Q0.4"))):
            yy = 104 + k * 34
            draw.lamp(p, QPointF(40, yy), 10, out[key], color)
            draw.text(p, 56, yy - 6, label, 7.5, True)
            draw.tag(p, 56, yy + 8, addr, out[key])
        draw.push_button(p, QRectF(30, 214, 130, 28), "ABRIR  I0.0", self.is_pressed("OPEN"), draw.GREEN)
        draw.push_button(p, QRectF(30, 250, 130, 28), "FECHAR  I0.1", self.is_pressed("CLOSE"), QColor("#2563eb"))
        draw.push_button(p, QRectF(30, 286, 130, 28), "PARAR  I0.2 (NF)", self.is_pressed("STOP"), draw.RED)
        draw.switch(p, QRectF(500, 360, 120, 28), "Veiculo", self.vehicle)
