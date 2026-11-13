"""Casa de caldeiras com deteccao de gas: votacao 2 de 3, alarme com reconhecimento e rearme."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import approach
from ..registry import register

LEAK = 12.0                     # %LIE/s que o vazamento solta com a valvula aberta
NATURAL, EXHAUST = 0.03, 0.35   # renovacao do ar: natural e com o exaustor (fracao por segundo)
TAUS = (1.0, 1.5, 2.0)          # tempo de resposta dos detectores (s)
ALARM_ON, ALARM_OFF = 20.0, 15.0    # detectores: alarme em 20% do LIE, volta em 15%
EXPLOSIVE = 40.0                # acima disso a casa de caldeiras corre risco
VALVE_OPEN_S, VALVE_CLOSE_S = 1.0, 0.5
FAN_S = 1.5


@register
class GasDetectionEnvironment(Environment):
    id = "detector_gas"
    name = "Detecção de gás (votação 2 de 3)"
    description = ("Casa de caldeiras a gás com três detectores (alarme em 20% do limite inferior de explosividade). "
                   "A válvula de bloqueio fica energizada (aberta) para os queimadores trabalharem e deve fechar "
                   "quando 2 dos 3 detectores atuarem; um detector sozinho pode ser defeito e não deve parar a "
                   "produção. A sirene toca até RECONHECER e a válvula só reabre com REARMAR depois de o gás baixar. "
                   "O pressostato do duto confirma o exaustor. Os botões de falha simulam um detector morto, um "
                   "detector em falso alarme e o exaustor quebrado.")
    example = "ambientes/detector_gas.ladproj"
    inputs = [
        IOPoint("D1", "I0.0", "Detector_1", "Detector de gás 1 (perto dos queimadores)"),
        IOPoint("D2", "I0.1", "Detector_2", "Detector de gás 2 (centro)"),
        IOPoint("D3", "I0.2", "Detector_3", "Detector de gás 3 (perto da porta)"),
        IOPoint("RECONHECER", "I0.3", "Reconhecer", "Botão RECONHECER (silencia a sirene)", BUTTON),
        IOPoint("REARMAR", "I0.4", "Rearmar", "Botão REARMAR (reabre a válvula)", BUTTON),
        IOPoint("FLUXO", "I0.5", "Fluxo_Exaustao", "Pressostato do duto: exaustor com fluxo"),
        IOPoint("TESTE", "I0.6", "Teste_Lampadas", "Botão TESTE de lâmpadas", BUTTON),
    ]
    outputs = [
        IOPoint("EXAUSTOR", "Q0.0", "Exaustor", "Exaustor da casa de caldeiras"),
        IOPoint("VALVULA", "Q0.1", "Valvula_Gas", "Válvula de bloqueio do gás (energizada = aberta)"),
        IOPoint("SIRENE", "Q0.2", "Sirene", "Sirene de alarme"),
        IOPoint("LUZ_ALARME", "Q0.3", "Luz_Alarme", "Lâmpada ALARME DE GÁS"),
        IOPoint("LUZ_FALHA_DET", "Q0.4", "Luz_Falha_Detector", "Lâmpada FALHA DE DETECTOR (discordância)"),
        IOPoint("LUZ_FALHA_EXAUST", "Q0.5", "Luz_Falha_Exaustor", "Lâmpada FALHA DO EXAUSTOR (sem fluxo)"),
    ]

    def reset(self) -> None:
        self.c = 0.0
        self.reading = [0.0, 0.0, 0.0]
        self.det = [False, False, False]
        self.valve = 0.0
        self.fan = 0.0
        self.fan_angle = 0.0
        self.leak = getattr(self, "leak", False)
        self.dead_d2 = getattr(self, "dead_d2", False)
        self.false_d3 = getattr(self, "false_d3", False)
        self.fan_broken = getattr(self, "fan_broken", False)
        self.peak = 0.0
        self.open_ms = 0
        self.explosive = False
        self.open_with_votes_ms = 0
        self.open_on_votes = False
        self.spurious = 0
        self.trips = 0
        self.need_reset = False
        self.reopened_without_reset = False
        self.siren_since: int | None = None
        self.siren_after_ack = False
        self.unsignalled_fan_ms = 0
        self.fan_unsignalled = False
        self._valve_cmd = False
        self._last_press = {"RECONHECER": -10**9, "REARMAR": -10**9}

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "VAZAMENTO":
            self.leak = not self.leak
        elif key == "FALHA_D2":
            self.dead_d2 = not self.dead_d2
        elif key == "FALHA_D3":
            self.false_d3 = not self.false_d3
        elif key == "FALHA_EXAUST":
            self.fan_broken = not self.fan_broken

    def press(self, key: str, down: bool) -> None:
        if key in ("VAZAMENTO", "FALHA_D2", "FALHA_D3", "FALHA_EXAUST"):
            self.on_control(key, down)
            return
        if down and key in self._last_press:
            self._last_press[key] = self.time_ms
        super().press(key, down)

    def votes(self) -> int:
        return sum(self.sensors()[k] for k in ("D1", "D2", "D3"))

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        for key in self._last_press:
            if self.is_pressed(key):
                self._last_press[key] = now
        cmd = out["VALVULA"]
        self.valve = approach(self.valve, 1.0 if cmd else 0.0, 1 / VALVE_OPEN_S, 1 / VALVE_CLOSE_S, dt)
        self.fan = approach(self.fan, 1.0 if (out["EXAUSTOR"] and not self.fan_broken) else 0.0, 1 / FAN_S, 1 / FAN_S, dt)
        self.fan_angle += self.fan * 18 * dt
        source = LEAK * self.valve if self.leak else 0.0
        self.c = max(0.0, self.c + (source - self.c * (NATURAL + EXHAUST * self.fan)) * dt)
        self.peak = max(self.peak, self.c)
        for k in range(3):
            self.reading[k] += (self.c - self.reading[k]) * min(1.0, dt / TAUS[k])
            if self.reading[k] >= ALARM_ON:
                self.det[k] = True
            elif self.reading[k] <= ALARM_OFF:
                self.det[k] = False
        votes = self.votes()
        if self.valve >= 0.9:
            self.open_ms += dt_ms
        if self.c >= EXPLOSIVE and self.valve > 0.1:
            self.explosive = True
        self.open_with_votes_ms = self.open_with_votes_ms + dt_ms if (cmd and votes >= 2) else 0
        if self.open_with_votes_ms > 2000:
            self.open_on_votes = True
        if self._valve_cmd and not cmd:                       # a valvula fechou
            if votes >= 2:
                self.trips += 1
            if self.c >= ALARM_OFF or votes >= 2:     # fechou com gas de verdade: reabrir so com rearme
                self.need_reset = True
            elif self.c < 10.0 and votes <= 1:
                self.spurious += 1
        if cmd and not self._valve_cmd:                       # a valvula reabriu
            if self.need_reset and now - self._last_press["REARMAR"] > 1000:
                self.reopened_without_reset = True
            self.need_reset = False
        self._valve_cmd = cmd
        if out["SIRENE"]:
            if self.siren_since is None:
                self.siren_since = now
            ack = self._last_press["RECONHECER"]
            if ack >= self.siren_since and now - ack > 2000:
                self.siren_after_ack = True
        else:
            self.siren_since = None
        no_flow = out["EXAUSTOR"] and not self.sensors()["FLUXO"] and not out["LUZ_FALHA_EXAUST"]
        self.unsignalled_fan_ms = self.unsignalled_fan_ms + dt_ms if no_flow else 0
        if self.unsignalled_fan_ms > 6000:
            self.fan_unsignalled = True

    def sensors(self) -> dict[str, bool]:
        return {"D1": self.det[0], "D2": self.det[1] and not self.dead_d2, "D3": self.det[2] or self.false_d3,
                "FLUXO": self.fan >= 0.6}

    def alarms(self) -> list[str]:
        out = []
        if self.explosive:
            out.append("PERIGO: concentração explosiva com a válvula de gás aberta")
        if self.open_on_votes:
            out.append("A válvula continuou aberta com 2 de 3 detectores em alarme")
        if self.spurious:
            out.append("Parada indevida: a válvula fechou sem gás, por um único detector (a votação 2 de 3 evita isso)")
        if self.reopened_without_reset:
            out.append("A válvula reabriu sozinha depois do disparo: exija o botão REARMAR")
        if self.siren_after_ack:
            out.append("A sirene continua tocando depois do RECONHECER")
        if self.fan_unsignalled:
            out.append("Exaustor comandado sem fluxo no duto e sem a lâmpada de falha do exaustor")
        return out

    def stats(self) -> list[str]:
        total = max(1, self.time_ms)
        faults = [n for n, f in (("D2 morto", self.dead_d2), ("D3 em falso alarme", self.false_d3),
                                 ("exaustor quebrado", self.fan_broken)) if f]
        return [f"Gás: {self.c:.1f}% do LIE (pico {self.peak:.1f}%) | detectores em alarme: {self.votes()} de 3",
                f"Produção (válvula aberta): {100 * self.open_ms / total:.0f}% do tempo | disparos: {self.trips}"
                + (f" | falhas: {', '.join(faults)}" if faults else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"RECONHECER": (16, 300, 140, 28), "REARMAR": (16, 334, 140, 28), "TESTE": (16, 368, 140, 28),
                "VAZAMENTO": (474, 266, 150, 28), "FALHA_D2": (474, 300, 150, 28), "FALHA_D3": (474, 334, 150, 28),
                "FALHA_EXAUST": (474, 368, 150, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f1f5f9"))
        room = QRectF(170, 30, 290, 250)
        p.setPen(QPen(QColor("#334155"), 3))
        p.setBrush(QColor("#fefce8"))
        p.drawRect(room)
        if self.c > 0.5:                          # nuvem de gas
            cloud = QColor(250, 204, 21, int(min(170, self.c * 4)))
            p.fillRect(room.adjusted(2, 2, -2, -2), cloud)
        # caldeiras e chamas
        sens = self.sensors()
        for k in range(2):
            b = QRectF(200 + k * 110, 160, 80, 100)
            p.setPen(QPen(QColor("#1e293b"), 1.5))
            p.setBrush(QColor("#94a3b8"))
            p.drawRoundedRect(b, 8, 8)
            if self.valve > 0.3:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(37, 99, 235, int(200 * self.valve)))
                flick = 4 * math.sin(self.time_ms / 90 + k)
                p.drawEllipse(QPointF(b.center().x(), b.bottom() - 16), 14, 10 + flick)
        # tubulacao de gas e valvula
        p.setPen(QPen(QColor("#ca8a04"), 6))
        p.drawLine(QPointF(170, 268), QPointF(390, 268))
        vc = QPointF(194, 268)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(draw.GREEN if self.valve > 0.9 else (draw.AMBER if self.valve > 0.05 else draw.RED))
        p.drawPolygon(QPolygonF([QPointF(vc.x() - 12, vc.y() - 9), QPointF(vc.x() + 12, vc.y() + 9),
                       QPointF(vc.x() + 12, vc.y() - 9), QPointF(vc.x() - 12, vc.y() + 9)]))
        draw.tag(p, 172, 296, "Q0.1 válvula", self.out.get("VALVULA", False))
        if self.leak:
            draw.text(p, 300, 296, "vazamento!", 8, True, draw.RED, w=90)
        # detectores
        for k, (x, y) in enumerate(((210, 60), (315, 60), (420, 60))):
            key = f"D{k + 1}"
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#e2e8f0"))
            p.drawRoundedRect(QRectF(x - 18, y - 12, 36, 34), 5, 5)
            draw.lamp(p, QPointF(x, y), 5, sens[key], draw.RED)
            draw.text(p, x, y + 13, f"{self.reading[k]:.0f}%", 7, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 40)
            draw.tag(p, x - 20, y + 34, f"I0.{k} D{k + 1}", sens[key])
        # exaustor
        fc = QPointF(room.right(), 140)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#cbd5e1"))
        p.drawEllipse(fc, 22, 22)
        p.setPen(QPen(QColor("#1d4ed8") if self.fan > 0.1 else QColor("#475569"), 4))
        for k in range(4):
            a = self.fan_angle + k * math.pi / 2
            p.drawLine(fc, QPointF(fc.x() + math.cos(a) * 18, fc.y() + math.sin(a) * 18))
        p.setPen(QPen(QColor("#475569"), 10))
        p.drawLine(QPointF(fc.x() + 22, 140), QPointF(620, 140))
        draw.tag(p, 486, 112, "Q0.0 exaustor", self.out.get("EXAUSTOR", False))
        draw.tag(p, 486, 166, "I0.5 fluxo", sens["FLUXO"])
        # medidor de concentracao
        bar = QRectF(486, 196, 130, 14)
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRect(bar)
        p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * min(1.0, self.c / 60), bar.height()),
                   draw.RED if self.c >= ALARM_ON else draw.AMBER)
        p.setPen(QPen(draw.RED, 1.5, Qt.DashLine))
        x40 = bar.left() + bar.width() * EXPLOSIVE / 60
        p.drawLine(QPointF(x40, bar.top() - 3), QPointF(x40, bar.bottom() + 3))
        draw.text(p, bar.left(), bar.top() - 10, f"Gás {self.c:.1f}% do LIE", 8, True)
        # painel
        draw.panel(p, QRectF(10, 30, 150, 254), "PAINEL")
        rows = (("LUZ_ALARME", "ALARME GÁS", draw.RED, "Q0.3"), ("LUZ_FALHA_DET", "FALHA DETECTOR", draw.AMBER, "Q0.4"),
                ("LUZ_FALHA_EXAUST", "FALHA EXAUSTOR", draw.AMBER, "Q0.5"))
        for k, (key, label, color, addr) in enumerate(rows):
            yy = 66 + k * 40
            draw.lamp(p, QPointF(30, yy), 9, self.out.get(key, False), color)
            draw.text(p, 46, yy - 6, label, 7.5, True, w=110)
            draw.tag(p, 46, yy + 9, addr, self.out.get(key, False))
        siren = self.out.get("SIRENE", False)
        draw.lamp(p, QPointF(30, 196), 9, siren and (self.time_ms // 250) % 2 == 0, QColor("#f97316"))
        draw.text(p, 46, 190, "SIRENE", 7.5, True, w=110)
        draw.tag(p, 46, 205, "Q0.2", siren)
        draw.push_button(p, QRectF(16, 300, 140, 28), "RECONHECER I0.3", self.is_pressed("RECONHECER"), draw.AMBER)
        draw.push_button(p, QRectF(16, 334, 140, 28), "REARMAR  I0.4", self.is_pressed("REARMAR"), draw.GREEN)
        draw.push_button(p, QRectF(16, 368, 140, 28), "TESTE  I0.6", self.is_pressed("TESTE"), QColor("#64748b"))
        draw.switch(p, QRectF(474, 266, 150, 28), "Vazamento", self.leak)
        draw.switch(p, QRectF(474, 300, 150, 28), "D2 morto", self.dead_d2)
        draw.switch(p, QRectF(474, 334, 150, 28), "D3 falso alarme", self.false_d3)
        draw.switch(p, QRectF(474, 368, 150, 28), "Exaustor quebrado", self.fan_broken)
