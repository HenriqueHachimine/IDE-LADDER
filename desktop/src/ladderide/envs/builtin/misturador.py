"""Misturador de batelada: dosagem por fluxometro, agitacao, aquecimento com termostato e descarga."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import approach
from ..registry import register

CAPACITY = 100.0         # L
LOW_L, HIGH_L = 10.0, 90.0
PUMP_FLOW = 4.0          # L/s das bombas de entrada
DRAIN_FLOW = 6.0         # L/s da bomba de saida
PUMP_UP_S, PUMP_DOWN_S = 0.5, 0.3
HEATER = 140.0           # degC*L/s (com 70 L: 2 degC/s)
AMBIENT = 20.0
LOSS = 0.008             # 1/s: perda de calor para o ambiente
SET_ON, SET_OFF = 40.0, 39.0   # termostato fecha em 40 degC e abre abaixo de 39 degC
MIX_S = 4.0              # s de agitacao para homogeneizar
RECIPE_A = 40 / 70       # receita: 40 L do produto A + 30 L do produto B
RATIO_TOL = 0.03
DRY_S = 1.0

# desenho
TANK = QRectF(230, 110, 260, 230)
COLOR_A = QColor("#16a34a")
COLOR_B = QColor("#eab308")


def _mix_color(frac_a: float) -> QColor:
    a, b = COLOR_A, COLOR_B
    t = max(0.0, min(1.0, frac_a))
    return QColor(int(a.red() * t + b.red() * (1 - t)), int(a.green() * t + b.green() * (1 - t)),
                  int(a.blue() * t + b.blue() * (1 - t)))


@register
class BatchMixerEnvironment(Environment):
    id = "misturador"
    name = "Misturador de batelada"
    description = ("Receita: 40 L do produto A (bomba 1) e 30 L do produto B (bomba 2), contados pelos pulsos "
                   "dos fluxometros (1 pulso por litro). Depois o lote e agitado e aquecido ate o termostato "
                   "(40 degC) e descarregado pela bomba de saida ate esvaziar. Aquecer abaixo do nivel baixo, "
                   "aquecer sem agitar, transbordar, deixar a bomba de saida trabalhar a seco ou descarregar um "
                   "lote fora da receita, frio ou sem mistura sao falhas.")
    example = "ambientes/misturador.ladproj"
    inputs = [
        IOPoint("START", "I0.0", "Start", "Botao de partida (NA)", BUTTON),
        IOPoint("STOP", "I0.1", "Stop", "Botao de parada (NF: le 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("LOW", "I0.2", "Nivel_Baixo", "Chave de nivel: liquido acima de 10 L"),
        IOPoint("HIGH", "I0.3", "Nivel_Alto", "Chave de nivel: liquido acima de 90 L"),
        IOPoint("THERMO", "I0.4", "Termostato", "Fecha com 40 degC (abre abaixo de 39 degC)"),
        IOPoint("FLOW1", "I0.5", "Fluxometro_1", "1 pulso por litro do produto A"),
        IOPoint("FLOW2", "I0.6", "Fluxometro_2", "1 pulso por litro do produto B"),
    ]
    outputs = [
        IOPoint("PUMP1", "Q0.0", "Bomba_1", "Bomba do produto A"),
        IOPoint("PUMP2", "Q0.1", "Bomba_2", "Bomba do produto B"),
        IOPoint("MIXER", "Q0.2", "Misturador", "Motor do agitador"),
        IOPoint("DRAIN", "Q0.3", "Bomba_Saida", "Bomba de descarga"),
        IOPoint("HEATER", "Q0.4", "Aquecedor", "Resistencia de aquecimento"),
        IOPoint("RUN", "Q0.5", "Lampada_Run", "Lampada RUN"),
        IOPoint("FULL", "Q0.6", "Lampada_Cheio", "Lampada nivel alto"),
    ]

    def reset(self) -> None:
        self.a = 0.0                  # litros do produto A no tanque
        self.b = 0.0
        self.temp = AMBIENT
        self.mix = 1.0
        self.speed = {"PUMP1": 0.0, "PUMP2": 0.0, "DRAIN": 0.0, "MIXER": 0.0}
        self.meter = [0.0, 0.0]       # litros que passaram pelos fluxometros
        self.thermo = False
        self.angle = 0.0
        self.spilled = 0.0
        self.dry_heat = False
        self.unstirred_ms = 0
        self.unstirred = False
        self.dry_ms = 0
        self.dry_pump = False
        self.good = 0
        self.bad: list[str] = []
        self._draining = False
        self.last_batch = ""

    @property
    def volume(self) -> float:
        return self.a + self.b

    # ------------------------------------------------------------- fisica
    def _add(self, liters: float, product: str) -> None:
        v = self.volume
        if v + liters > CAPACITY:
            self.spilled += v + liters - CAPACITY
            liters = max(0.0, CAPACITY - v)
        if liters <= 0:
            return
        self.temp = (self.temp * v + AMBIENT * liters) / (v + liters)
        self.mix = self.mix * v / (v + liters) if v > 0 else 0.0
        if product == "A":
            self.a += liters
        else:
            self.b += liters

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for key in self.speed:
            self.speed[key] = approach(self.speed[key], 1.0 if out[key] else 0.0, 1 / PUMP_UP_S, 1 / PUMP_DOWN_S, dt)
        for k, (key, product) in enumerate((("PUMP1", "A"), ("PUMP2", "B"))):
            q = PUMP_FLOW * self.speed[key] * dt
            self.meter[k] += q
            self._add(q, product)
        # descarga (bomba de saida)
        drain_on = self.speed["DRAIN"] > 0.3
        if drain_on and not self._draining and self.volume >= 20:
            self._judge_batch()
        self._draining = drain_on
        q = min(self.volume, DRAIN_FLOW * self.speed["DRAIN"] * dt)
        if q > 0 and self.volume > 0:
            frac = self.a / self.volume
            self.a -= q * frac
            self.b -= q * (1 - frac)
        if self.volume < 1e-6:
            self.a = self.b = 0.0
            self.mix = 1.0
        self.dry_ms = self.dry_ms + dt_ms if drain_on and self.volume <= 0.0 else 0
        if self.dry_ms > DRY_S * 1000:
            self.dry_pump = True
        # agitacao
        self.angle += self.speed["MIXER"] * 10 * dt
        if self.speed["MIXER"] > 0.5 and self.volume >= LOW_L:
            self.mix = min(1.0, self.mix + dt / MIX_S)
        # aquecimento
        if out["HEATER"]:
            if self.volume < LOW_L:
                self.dry_heat = True
            else:
                self.temp += HEATER / self.volume * dt
            self.unstirred_ms = self.unstirred_ms + dt_ms if self.speed["MIXER"] < 0.5 else 0
            if self.unstirred_ms > 2000:
                self.unstirred = True
        else:
            self.unstirred_ms = 0
        self.temp -= LOSS * (self.temp - AMBIENT) * dt
        if self.temp >= SET_ON:
            self.thermo = True
        elif self.temp < SET_OFF:
            self.thermo = False

    def _judge_batch(self) -> None:
        v = self.volume
        problems = []
        ratio = self.a / v
        if abs(ratio - RECIPE_A) > RATIO_TOL:
            problems.append(f"receita {ratio * 100:.0f}% A (esperado {RECIPE_A * 100:.0f}%)")
        if self.temp < SET_OFF - 0.5:
            problems.append(f"frio ({self.temp:.0f} degC)")
        if self.mix < 0.99:
            problems.append(f"mal misturado ({self.mix * 100:.0f}%)")
        self.last_batch = f"{v:.0f} L, {ratio * 100:.0f}% A, {self.temp:.1f} degC"
        if problems:
            self.bad.append(", ".join(problems))
        else:
            self.good += 1

    def flow_pulse(self, k: int) -> bool:
        m = self.meter[k]
        return m > 0 and (m % 1.0) < 0.5

    def sensors(self) -> dict[str, bool]:
        v = self.volume
        return {"LOW": v >= LOW_L, "HIGH": v >= HIGH_L, "THERMO": self.thermo,
                "FLOW1": self.flow_pulse(0), "FLOW2": self.flow_pulse(1)}

    def alarms(self) -> list[str]:
        out = []
        if self.spilled > 0:
            out.append(f"O tanque transbordou ({self.spilled:.1f} L)")
        if self.dry_heat:
            out.append("Aquecedor ligado abaixo do nivel baixo: resistencia exposta queimou")
        if self.unstirred:
            out.append("Aquecedor ligado sem o misturador: superaquecimento local do produto")
        if self.dry_pump:
            out.append("Bomba de saida trabalhando a seco: desligue quando o tanque esvaziar")
        if self.bad:
            out.append(f"{len(self.bad)} lote(s) rejeitado(s): {self.bad[-1]}")
        return out

    def stats(self) -> list[str]:
        v = self.volume
        a = f"{self.a / v * 100:.0f}% A" if v > 0.5 else "-"
        return [f"Tanque: {v:.1f} L ({a}) | {self.temp:.1f} degC | mistura {self.mix * 100:.0f}%",
                f"Lotes bons: {self.good} | rejeitados: {len(self.bad)}"
                + (f" | ultimo: {self.last_batch}" if self.last_batch else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"START": (22, 236, 120, 28), "STOP": (22, 270, 120, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        out, sens = self.out, self.sensors()
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#fffbeb"))
        pipe = QPen(QColor("#1f2937"), 9, Qt.SolidLine, Qt.FlatCap, Qt.MiterJoin)
        # tubulacoes de entrada
        for k, (y, x_in) in enumerate(((40, 330), (80, 300))):
            p.setPen(pipe)
            p.drawPolyline([QPointF(0, y), QPointF(x_in, y), QPointF(x_in, TANK.bottom() - 30)])
            color = COLOR_A if k == 0 else COLOR_B
            if self.speed[f"PUMP{k + 1}"] > 0.05:
                p.setPen(QPen(color, 4))
                p.drawPolyline([QPointF(0, y), QPointF(x_in, y), QPointF(x_in, TANK.bottom() - 30)])
            fm = QPointF(70, y)
            p.setPen(QPen(QColor("#111827"), 1))
            p.setBrush(QColor("#9ca3af"))
            p.drawEllipse(fm, 11, 11)
            draw.lamp(p, QPointF(fm.x() - 22, fm.y()), 4.5, sens[f"FLOW{k + 1}"], draw.AMBER)   # LED de pulso
            draw.tag(p, fm.x() - 64, y + 18, f"I0.{5 + k} fluxo {self.meter[k]:.0f} L",
                     sens[f"FLOW{k + 1}"])
            self._pump(p, QPointF(150, y), self.speed[f"PUMP{k + 1}"], self.angle * (2 + k))
            draw.tag(p, 166, y + 18, f"Q0.{k} bomba {'A' if k == 0 else 'B'}",
                     out[f"PUMP{k + 1}"])
        # tanque e liquido
        p.setPen(QPen(QColor("#6366f1"), 4))
        p.setBrush(QColor("#ffffff"))
        p.drawRect(TANK)
        v = self.volume
        if v > 0.05:
            h = TANK.height() * min(1.0, v / CAPACITY)
            liquid = QRectF(TANK.left() + 2, TANK.bottom() - h, TANK.width() - 4, h)
            frac_a = self.a / v
            if self.mix >= 0.99:
                p.fillRect(liquid, _mix_color(frac_a))
            else:                                   # camadas ainda separadas
                a_h = h * frac_a
                p.fillRect(QRectF(liquid.left(), liquid.bottom() - a_h, liquid.width(), a_h), COLOR_A)
                p.fillRect(QRectF(liquid.left(), liquid.top(), liquid.width(), h - a_h), COLOR_B)
                blend = QColor(_mix_color(frac_a))
                blend.setAlpha(int(255 * self.mix))
                p.fillRect(liquid, blend)
        draw.text(p, TANK.left() + 8, TANK.top() + 14, f"{v:.0f} L  {self.temp:.1f} °C", 9, True,
                  draw.INK, Qt.AlignLeft | Qt.AlignVCenter, 110)
        # agitador
        mc = QPointF(TANK.center().x(), TANK.top() - 34)
        p.setPen(QPen(QColor("#111827"), 1))
        p.setBrush(QColor("#991b1b"))
        p.drawRect(QRectF(mc.x() - 26, mc.y() - 26, 52, 40))
        draw.tag(p, mc.x() + 32, mc.y() - 10, "Q0.2 misturador", out["MIXER"])
        p.setPen(QPen(QColor("#111827"), 3))
        p.drawLine(QPointF(mc.x(), mc.y() + 14), QPointF(mc.x(), TANK.bottom() - 34))
        blade = 34 * math.cos(self.angle)
        p.setPen(QPen(QColor("#374151"), 6, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(mc.x() - blade, TANK.bottom() - 34), QPointF(mc.x() + blade, TANK.bottom() - 34))
        # aquecedor
        heat = QRectF(TANK.center().x() - 50, TANK.bottom() + 6, 100, 20)
        p.setPen(QPen(QColor("#111827"), 1))
        p.setBrush(QColor("#dc2626") if out["HEATER"] else QColor("#44403c"))
        p.drawRect(heat)
        draw.tag(p, heat.right() + 6, heat.center().y(), "Q0.4 aquecedor", out["HEATER"])
        # chaves de nivel e termostato
        for key, liters, addr in (("HIGH", HIGH_L, "I0.3 nivel alto"), ("LOW", LOW_L, "I0.2 nivel baixo")):
            y = TANK.bottom() - TANK.height() * liters / CAPACITY
            p.setPen(QPen(QColor("#111827"), 1))
            p.setBrush(QColor("#a16207"))
            p.drawRect(QRectF(TANK.right() - 14, y - 4, 12, 8))
            draw.tag(p, TANK.right() + 8, y, addr, sens[key])
        draw.tag(p, TANK.right() + 8, TANK.center().y(), f"I0.4 termostato 40°C", sens["THERMO"])
        # descarga
        p.setPen(pipe)
        p.drawPolyline([QPointF(TANK.left() + 40, TANK.bottom()), QPointF(TANK.left() + 40, 380),
                        QPointF(640, 380)])
        if self.speed["DRAIN"] > 0.05 and v > 0:
            p.setPen(QPen(_mix_color(self.a / v if v > 0 else 0.5), 4))
            p.drawPolyline([QPointF(TANK.left() + 40, TANK.bottom()), QPointF(TANK.left() + 40, 380),
                            QPointF(640, 380)])
        self._pump(p, QPointF(560, 380), self.speed["DRAIN"], self.angle * 3)
        draw.tag(p, 500, 400, "Q0.3 bomba de saida", out["DRAIN"])
        # painel
        draw.panel(p, QRectF(12, 120, 140, 190), "BATELADA")
        for k, (key, label, color, addr) in enumerate((("RUN", "RUN", draw.GREEN, "Q0.5"),
                                                      ("FULL", "CHEIO", draw.AMBER, "Q0.6"))):
            yy = 152 + k * 36
            draw.lamp(p, QPointF(32, yy), 10, out[key], color)
            draw.text(p, 48, yy - 6, label, 7.5, True)
            draw.tag(p, 48, yy + 8, addr, out[key])
        draw.push_button(p, QRectF(22, 236, 120, 28), "START I0.0", self.is_pressed("START"), draw.GREEN)
        draw.push_button(p, QRectF(22, 270, 120, 28), "STOP I0.1 (NF)", self.is_pressed("STOP"), draw.RED)

    @staticmethod
    def _pump(p: QPainter, c: QPointF, speed: float, angle: float) -> None:
        p.setPen(QPen(QColor("#111827"), 1.2))
        p.setBrush(QColor("#22c55e") if speed > 0.5 else QColor("#d1d5db"))
        p.drawEllipse(c, 15, 15)
        p.setPen(QPen(QColor("#111827"), 2))
        for j in range(3):
            a = angle + j * 2 * math.pi / 3
            p.drawLine(c, QPointF(c.x() + math.cos(a) * 11, c.y() + math.sin(a) * 11))
