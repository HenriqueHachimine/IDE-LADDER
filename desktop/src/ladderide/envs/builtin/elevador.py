"""Elevador de 4 andares: motor com freio, sensores de zona de porta e operador de porta com mola."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import approach
from ..registry import register

FLOORS = 4
FLOOR_H = 3.0            # m entre andares
SPEED = 0.5              # m/s (elevador de acionamento simples, uma velocidade)
ACCEL = 0.6              # m/s^2 na partida
BRAKE = 2.0              # m/s^2 do freio ao desligar o motor (para em ~6 cm)
ZONE = 0.10              # m: sensor de andar (zona de porta) atua a +-10 cm do nivel
OVERTRAVEL = 0.30        # m alem do ultimo andar ate o para-choque (buffer)
DOOR_OPEN_S = 1.5        # operador abre a porta em 1,5 s
DOOR_CLOSE_S = 2.5       # mola/fechador fecha em 2,5 s quando o operador desliga
WAIT_ALARM_S = 60        # chamada esperando mais que isso = logica travada

# desenho: 100 px por andar
SHAFT = QRectF(205, 40, 110, 360)
PX_PER_M = 100 / FLOOR_H
CAR_H = 78.0


def floor_y(k: int) -> float:
    """y (px) do piso do andar k (0 = terreo)."""
    return SHAFT.bottom() - 20 - k * 100


@register
class ElevatorEnvironment(Environment):
    id = "elevador"
    name = "Elevador de 4 andares"
    description = ("Botoes 1 a 4 (cabine ou pavimento) chamam o elevador. O motor tem uma velocidade "
                   "(0,5 m/s) e freio: ao desligar, a cabine anda ~6 cm, por isso o sensor de andar atua "
                   "10 cm antes do nivel. O operador abre a porta enquanto a saida estiver ligada; desligada, "
                   "o fechador leva 2,5 s para fechar (nao ha sensor de porta: use um temporizador). "
                   "Andar com a porta aberta, abrir fora do andar ou passar do ultimo andar sao falhas.")
    example = "ambientes/elevador.ladproj"
    size = (640, 420)
    inputs = [
        IOPoint("CALL1", "I0.0", "Chamada_1", "Botao do 1o andar (cabine ou pavimento)", BUTTON),
        IOPoint("CALL2", "I0.1", "Chamada_2", "Botao do 2o andar", BUTTON),
        IOPoint("CALL3", "I0.2", "Chamada_3", "Botao do 3o andar", BUTTON),
        IOPoint("CALL4", "I0.3", "Chamada_4", "Botao do 4o andar", BUTTON),
        IOPoint("FLOOR1", "I0.4", "Andar_1", "Cabine no nivel do 1o andar (+-10 cm)"),
        IOPoint("FLOOR2", "I0.5", "Andar_2", "Cabine no nivel do 2o andar"),
        IOPoint("FLOOR3", "I0.6", "Andar_3", "Cabine no nivel do 3o andar"),
        IOPoint("FLOOR4", "I0.7", "Andar_4", "Cabine no nivel do 4o andar"),
    ]
    outputs = [
        IOPoint("UP", "Q0.0", "Motor_Sobe", "Motor no sentido de subir"),
        IOPoint("DOWN", "Q0.1", "Motor_Desce", "Motor no sentido de descer"),
        IOPoint("DOOR", "Q0.2", "Abrir_Porta", "Operador de porta: abre (desligado, o fechador fecha)"),
        IOPoint("LAMP1", "Q0.3", "Lampada_1", "Chamada registrada no 1o andar"),
        IOPoint("LAMP2", "Q0.4", "Lampada_2", "Chamada registrada no 2o andar"),
        IOPoint("LAMP3", "Q0.5", "Lampada_3", "Chamada registrada no 3o andar"),
        IOPoint("LAMP4", "Q0.6", "Lampada_4", "Chamada registrada no 4o andar"),
    ]

    def reset(self) -> None:
        self.y = 0.0                     # m: nivel do piso da cabine (0 = 1o andar)
        self.v = 0.0
        self.door = 0.0                  # 0 fechada .. 1 aberta
        self.pending: dict[int, int] = {}            # andar -> instante da chamada (ms)
        self.waits: list[float] = []
        self.moved_open = 0
        self.opened_outside = 0
        self.buffer_hit = False
        self.both_ms = 0
        self.trips = 0
        self.last_level_cm: float | None = None
        self._moving = False
        self._door_was_open = False
        self._was_outside = False

    # ------------------------------------------------------------ fisica
    def floor_offset(self) -> tuple[int, float]:
        k = min(FLOORS - 1, max(0, round(self.y / FLOOR_H)))
        return k, self.y - k * FLOOR_H

    def press(self, key: str, down: bool) -> None:
        super().press(key, down)
        if down and key.startswith("CALL"):
            k = int(key[-1]) - 1
            self.pending.setdefault(k, self.time_ms)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        up, down = out["UP"], out["DOWN"]
        self.both_ms = self.both_ms + dt_ms if up and down else 0
        cmd = 0 if up == down else (1 if up else -1)
        if cmd == 0 or cmd * self.v < 0:
            self.v = approach(self.v, 0.0, BRAKE, BRAKE, dt)        # freio
        else:
            self.v = approach(self.v, cmd * SPEED, ACCEL, ACCEL, dt)
        new = self.y + self.v * dt
        top = (FLOORS - 1) * FLOOR_H + OVERTRAVEL
        if new > top or new < -OVERTRAVEL:                         # para-choque no fim do poco
            new = min(top, max(-OVERTRAVEL, new))
            self.v = 0.0
            self.buffer_hit = True
        self.y = new
        moving = abs(self.v) > 0.005
        if moving and not self._moving:
            self.trips += 1
            if self.door > 0.02:
                self.moved_open += 1
        if self._moving and not moving:
            self.last_level_cm = self.floor_offset()[1] * 100
        self._moving = moving
        # porta: operador abre; fechador (mola) fecha mais devagar
        self.door = approach(self.door, 1.0 if out["DOOR"] else 0.0, 1 / DOOR_OPEN_S, 1 / DOOR_CLOSE_S, dt)
        k, off = self.floor_offset()
        outside = abs(off) > ZONE
        if self.door > 0.05 and outside and not self._was_outside:
            self.opened_outside += 1
        self._was_outside = self.door > 0.05 and outside
        if self.door >= 0.95 and not outside:
            if not self._door_was_open and k in self.pending:
                self.waits.append((self.time_ms - self.pending.pop(k)) / 1000)
            self._door_was_open = True
        elif self.door < 0.5:
            self._door_was_open = False

    def sensors(self) -> dict[str, bool]:
        return {f"FLOOR{k + 1}": abs(self.y - k * FLOOR_H) <= ZONE for k in range(FLOORS)}

    def alarms(self) -> list[str]:
        out = []
        if self.both_ms:
            out.append("PERIGO: motor comandado para subir e descer ao mesmo tempo")
        if self.moved_open:
            out.append(f"O elevador andou com a porta aberta ({self.moved_open}x): espere o fechador "
                       f"fechar a porta (2,5 s) antes de ligar o motor")
        if self.opened_outside:
            out.append("A porta abriu com a cabine fora do andar (desnivel perigoso)")
        if self.buffer_hit:
            out.append("A cabine passou do ultimo andar e bateu no para-choque do poco")
        late = [k + 1 for k, t in self.pending.items() if self.time_ms - t > WAIT_ALARM_S * 1000]
        if late:
            out.append(f"Chamada do andar {', '.join(map(str, late))} esperando ha mais de {WAIT_ALARM_S} s")
        return out

    def stats(self) -> list[str]:
        k, off = self.floor_offset()
        level = f"{off * 100:+.1f} cm" if abs(off) <= ZONE else "entre andares"
        mean = f"{sum(self.waits) / len(self.waits):.1f} s" if self.waits else "-"
        last = f"{self.last_level_cm:+.1f} cm" if self.last_level_cm is not None else "-"
        return [f"Andar {k + 1} ({level}) | {self.v:+.2f} m/s | porta {self.door * 100:.0f}% aberta",
                f"Chamadas atendidas: {len(self.waits)} | espera media {mean} | ultimo nivelamento {last}"]

    # ------------------------------------------------------------ desenho
    def _buttons(self) -> list[tuple[str, QRectF]]:
        rects = []
        for k in range(FLOORS):                                   # botoeira da cabine (painel)
            rects.append((f"CALL{k + 1}", QRectF(20 + (k % 2) * 54, 250 - (k // 2) * 52, 46, 42)))
        for k in range(FLOORS):                                   # botoes de pavimento
            rects.append((f"CALL{k + 1}", QRectF(SHAFT.right() + 14, floor_y(k) - 46, 28, 28)))
        return rects

    def control_at(self, x: float, y: float) -> str | None:
        for key, r in self._buttons():
            if r.contains(QPointF(x, y)):
                return key
        return None

    def controls(self):
        return {key: (r.x(), r.y(), r.width(), r.height()) for key, r in self._buttons()}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        out, sens = self.out, self.sensors()
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f5f5f4"))
        # predio e poco
        p.fillRect(QRectF(SHAFT.left() - 10, SHAFT.top() - 10, SHAFT.width() + 70, SHAFT.height() + 20),
                   QColor("#e7e5e4"))
        p.fillRect(SHAFT, QColor("#44403c"))
        for k in range(FLOORS):
            fy = floor_y(k)
            p.fillRect(QRectF(SHAFT.left() - 10, fy, SHAFT.width() + 70, 6), QColor("#78350f"))
            draw.text(p, SHAFT.left() - 16, fy - 40, f"{k + 1}\u00ba", 10, True, draw.INK,
                      Qt.AlignRight | Qt.AlignVCenter, 30)
            # sensor de andar (chapa no poco + sensor na cabine)
            active = sens[f"FLOOR{k + 1}"]
            p.setPen(Qt.NoPen)
            p.setBrush(draw.AMBER if active else QColor("#a8a29e"))
            p.drawRect(QRectF(SHAFT.left() + 2, fy - CAR_H / 2 - ZONE * PX_PER_M - 3, 6,
                              2 * ZONE * PX_PER_M + 6))
            draw.tag(p, SHAFT.left() - 48, fy - 20, f"I0.{4 + k}", active)
        # cabos e motor
        car_bottom = floor_y(0) - self.y * PX_PER_M
        car = QRectF(SHAFT.left() + 14, car_bottom - CAR_H, SHAFT.width() - 28, CAR_H)
        p.setPen(QPen(QColor("#a8a29e"), 2))
        p.drawLine(QPointF(car.center().x(), SHAFT.top()), QPointF(car.center().x(), car.top()))
        mc = QPointF(SHAFT.center().x(), SHAFT.top() - 2)
        draw.motor(p, QPointF(mc.x() - 4, 22), 13, out["UP"] or out["DOWN"], -self.y * 2)
        draw.arrow(p, QPointF(mc.x() + 38, 14), 12, True, out["UP"])
        draw.arrow(p, QPointF(mc.x() + 38, 30), 12, False, out["DOWN"])
        draw.tag(p, mc.x() + 48, 14, "Q0.0", out["UP"])
        draw.tag(p, mc.x() + 48, 30, "Q0.1", out["DOWN"])
        # cabine com portas
        p.setPen(QPen(QColor("#0f172a"), 1.2))
        p.setBrush(QColor("#fef9c3"))
        p.drawRect(car)
        self._doors(p, QRectF(car.left() + 6, car.top() + 8, car.width() - 12, car.height() - 10), self.door)
        # botoes de pavimento com a lampada de chamada registrada
        for key, r in self._buttons()[FLOORS:]:
            k = int(key[-1])
            lit = out[f"LAMP{k}"]
            p.setPen(QPen(QColor("#334155"), 1))
            p.setBrush(QColor("#e2e8f0"))
            p.drawRoundedRect(r, 5, 5)
            draw.lamp(p, r.center(), 8, lit or self.is_pressed(key), draw.AMBER)
        # botoeira da cabine
        draw.panel(p, QRectF(10, 150, 124, 158), "CABINE")
        for key, r in self._buttons()[:FLOORS]:
            k = int(key[-1])
            lit = out[f"LAMP{k}"]
            pressed = self.is_pressed(key)
            p.setPen(QPen(QColor("#334155"), 1.2))
            p.setBrush(QColor("#cbd5e1") if pressed else QColor("#f8fafc"))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QPen(draw.AMBER if lit else QColor("#94a3b8"), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(r.center(), 15, 15)
            draw.text(p, r.center().x(), r.center().y(), str(k), 11, True, draw.INK,
                      Qt.AlignHCenter | Qt.AlignVCenter, 30)
            draw.tag(p, r.left(), r.bottom() + 3, f"I0.{k - 1}", pressed)
        draw.text(p, 14, 326, "Lampadas Q0.3..Q0.6", 7, False, draw.MUTED)
        draw.text(p, 14, 342, "Clique nos botoes da", 7, False, draw.MUTED)
        draw.text(p, 14, 356, "cabine ou de cada andar.", 7, False, draw.MUTED)
        # visao frontal da porta da cabine
        k, off = self.floor_offset()
        front = QRectF(420, 70, 190, 230)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#1e3a8a"))
        p.drawRect(front.adjusted(-14, -30, 14, 14))
        draw.text(p, front.center().x(), front.top() - 16, f"{k + 1}", 16, True, QColor("#fde047"),
                  Qt.AlignHCenter | Qt.AlignVCenter, 40)
        draw.arrow(p, QPointF(front.center().x() - 34, front.top() - 16), 12, True, self.v > 0.005)
        draw.arrow(p, QPointF(front.center().x() + 34, front.top() - 16), 12, False, self.v < -0.005)
        self._doors(p, front, self.door)
        draw.tag(p, front.left(), front.bottom() + 24, f"Q0.2 abrir porta: {self.door * 100:.0f}%", out["DOOR"])

    @staticmethod
    def _doors(p: QPainter, r: QRectF, opening: float) -> None:
        p.fillRect(r, QColor("#fffbeb"))
        leaf = r.width() / 2 * (1 - opening)
        grad = QLinearGradient(r.left(), 0, r.right(), 0)
        grad.setColorAt(0, QColor("#94a3b8"))
        grad.setColorAt(0.5, QColor("#cbd5e1"))
        grad.setColorAt(1, QColor("#94a3b8"))
        p.setPen(QPen(QColor("#475569"), 1))
        p.setBrush(grad)
        if leaf > 0.5:
            p.drawRect(QRectF(r.left(), r.top(), leaf, r.height()))
            p.drawRect(QRectF(r.right() - leaf, r.top(), leaf, r.height()))
        p.setBrush(Qt.NoBrush)
