"""Estufa agricola: temperatura e umidade analogicas, relogio do dia, chuva e vento."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF

from .. import draw
from ..base import SENSOR, SWITCH, Environment, IOPoint
from ..registry import register

HOUR_MS = 10000                   # 1 hora simulada = 10 s (um dia em 4 min)
START_HOUR = 6.0
K_WALL = 1 / 45                   # troca de calor pelas paredes (1/s)
SOLAR = 0.55                      # degC/s com sol a pino e estufa fechada
HEATER = 0.35                     # degC/s do aquecedor
K_FAN, K_WINDOW = 0.08, 0.05      # renovacao do ar pelo exaustor e pela janela aberta (1/s)
MIST_COOL, MIST_WET = 0.12, 1.2   # nebulizador: resfria (degC/s) e umedece (%/s)
WINDOW_S = 8.0                    # a janela leva 8 s para abrir ou fechar
IDEAL_T, IDEAL_H = (20.0, 28.0), (55.0, 85.0)
TEMP_WORD, HUM_WORD, HOUR_WORD = 0, 1, 2


@register
class GreenhouseEnvironment(Environment):
    id = "estufa"
    name = "Estufa agrícola (controle por faixas)"
    description = ("A estufa escreve a temperatura em N0 (décimos de °C: 253 = 25,3 °C), a umidade em N1 (%) e a "
                   "hora do dia em N2 (0 a 23; uma hora dura 10 s). O sol esquenta muito a estufa fechada; à noite "
                   "ela esfria. Faixa ideal: 20 a 28 °C e 55 a 85% de umidade. Aquecer com a ventilação ligada é "
                   "desperdício; janela aberta com chuva ou vento forte estraga as plantas. Use faixas com histerese "
                   "(liga num valor, desliga em outro) e a hora para a iluminação suplementar (18 h às 21 h).")
    example = "ambientes/estufa.ladproj"
    inputs = [
        IOPoint("AUTO", "I0.0", "Automatico", "Chave AUTOMÁTICO", SWITCH),
        IOPoint("ABERTA", "I0.1", "Janela_Aberta", "Fim de curso: janela do teto aberta"),
        IOPoint("FECHADA", "I0.2", "Janela_Fechada", "Fim de curso: janela do teto fechada"),
        IOPoint("CHUVA", "I0.3", "Sensor_Chuva", "Sensor de chuva", SENSOR),
        IOPoint("VENTO", "I0.4", "Sensor_Vento", "Anemômetro: vento forte", SENSOR),
    ]
    outputs = [
        IOPoint("AQUECEDOR", "Q0.0", "Aquecedor", "Aquecedor a gás"),
        IOPoint("VENTILADOR", "Q0.1", "Exaustor", "Exaustores das paredes"),
        IOPoint("ABRE", "Q0.2", "Janela_Abre", "Motor da janela: abrir"),
        IOPoint("FECHA", "Q0.3", "Janela_Fecha", "Motor da janela: fechar"),
        IOPoint("NEBULIZADOR", "Q0.4", "Nebulizador", "Nebulizador (resfria e umedece)"),
        IOPoint("LUZ", "Q0.5", "Iluminacao", "Iluminação suplementar"),
        IOPoint("ALARME", "Q0.6", "Alarme", "Lâmpada de alarme"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(3)
        self.forced_rain = getattr(self, "forced_rain", False)
        self.forced_wind = getattr(self, "forced_wind", False)
        self.T, self.H = 15.0, 80.0
        self.window = 0.0
        self.fan_angle = 0.0
        self._plans: dict[int, tuple[tuple[float, float] | None, tuple[float, float] | None]] = {
            0: ((13.0, 15.0), (10.0, 11.0))}          # primeiro dia: chuva 13-15 h e vento 10-11 h
        self.in_band_ms = 0
        self.heater_ms = 0
        self.waste_ms = 0
        self.rain_in_ms = 0
        self.wind_in_ms = 0
        self.humid_ms = 0
        self.force_ms = 0
        self.both_ms = 0
        self.flags: dict[str, str] = {}

    # ------------------------------------------------------------ clima
    @property
    def hours(self) -> float:
        return START_HOUR + self.time_ms / HOUR_MS

    @property
    def hour(self) -> int:
        return int(self.hours) % 24

    def _plan(self, day: int):
        if day not in self._plans:
            rng = random.Random(1000 + day)
            rain = None
            if rng.random() < 0.5:
                start = rng.uniform(11, 16)
                rain = (start, start + rng.uniform(1, 3))
            wind = None
            if rng.random() < 0.4:
                start = rng.uniform(9, 16)
                wind = (start, start + 1.0)
            self._plans[day] = (rain, wind)
        return self._plans[day]

    def _weather(self) -> tuple[bool, bool]:
        h = self.hours
        rain, wind = self._plan(int(h // 24))            # dia 0 = primeiro dia simulado
        hod = h % 24
        raining = self.forced_rain or (rain is not None and rain[0] <= hod < rain[1])
        windy = self.forced_wind or (wind is not None and wind[0] <= hod < wind[1])
        return raining, windy

    def outside(self) -> tuple[float, float, float]:
        """Temperatura e umidade externas e sol (0..1)."""
        hod = self.hours % 24
        raining, _ = self._weather()
        t = 17 + 8 * math.sin(2 * math.pi * (hod - 9) / 24) - (3 if raining else 0)
        h = 95.0 if raining else 70 - 15 * math.sin(2 * math.pi * (hod - 9) / 24)
        sun = max(0.0, math.sin(math.pi * (hod - 6) / 12)) if 6 <= hod <= 18 else 0.0
        return t, h, sun * (0.3 if raining else 1.0)

    def input_words(self) -> dict[int, int]:
        return {TEMP_WORD: round(self.T * 10), HUM_WORD: round(self.H), HOUR_WORD: self.hour}

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "CHUVA_MAN":
            self.forced_rain = not self.forced_rain
        elif key == "VENTO_MAN":
            self.forced_wind = not self.forced_wind

    def press(self, key: str, down: bool) -> None:
        if key in ("CHUVA_MAN", "VENTO_MAN"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    # ------------------------------------------------------------ fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        t_out, h_out, sun = self.outside()
        raining, windy = self._weather()
        opening, closing = out["ABRE"], out["FECHA"]
        self.both_ms = self.both_ms + dt_ms if (opening and closing) else 0
        old = self.window
        if opening and not closing:
            self.window = min(1.0, self.window + dt / WINDOW_S)
        elif closing and not opening:
            self.window = max(0.0, self.window - dt / WINDOW_S)
        forcing = (opening and not closing and old >= 1.0) or (closing and not opening and old <= 0.0)
        self.force_ms = self.force_ms + dt_ms if forcing else 0
        heater, fan, mist = out["AQUECEDOR"], out["VENTILADOR"], out["NEBULIZADOR"]
        if fan:
            self.fan_angle += 15 * dt
        exchange = K_WALL + K_FAN * fan + K_WINDOW * self.window
        dT = (t_out - self.T) * exchange + SOLAR * sun + HEATER * heater - MIST_COOL * mist * (self.H < 98)
        dH = (0.08 + 0.5 * sun) + MIST_WET * mist - (0.01 + K_FAN * fan + K_WINDOW * self.window) * (self.H - h_out) \
            - 0.25 * heater
        if raining and self.window > 0.05:
            dH += 1.0
        self.T += dT * dt
        self.H = min(100.0, max(10.0, self.H + dH * dt))
        good = IDEAL_T[0] <= self.T <= IDEAL_T[1] and IDEAL_H[0] <= self.H <= IDEAL_H[1]
        self.in_band_ms += dt_ms if good else 0
        self.heater_ms += dt_ms if heater else 0
        waste = heater and (fan or self.window > 0.1)
        self.waste_ms = self.waste_ms + dt_ms if waste else 0
        self.rain_in_ms = self.rain_in_ms + dt_ms if (raining and self.window > 0.05) else 0
        self.wind_in_ms = self.wind_in_ms + dt_ms if (windy and self.window > 0.05) else 0
        self.humid_ms = self.humid_ms + dt_ms if self.H > 92 else 0
        for key, cond, text in (
                ("waste", self.waste_ms > 5000, "Aquecedor ligado junto com a ventilação ou a janela aberta (desperdício)"),
                ("rain", self.rain_in_ms > WINDOW_S * 1000 + 2000, "Janela aberta com chuva: a água está entrando na estufa"),
                ("wind", self.wind_in_ms > WINDOW_S * 1000 + 2000, "Janela aberta com vento forte: risco de quebrar a janela"),
                ("hot", self.T > 35, f"Plantas sofrendo calor: {self.T:.1f} °C"),
                ("cold", self.T < 8, f"Risco de geada: {self.T:.1f} °C"),
                ("humid", self.humid_ms > 20000, "Umidade acima de 92% por muito tempo: risco de fungos"),
                ("force", self.force_ms > 2000, "Motor da janela forçando contra o fim de curso"),
                ("both", self.both_ms > 0, "Motor da janela comandado para abrir e fechar ao mesmo tempo")):
            if cond and key not in self.flags:
                self.flags[key] = text

    def sensors(self) -> dict[str, bool]:
        raining, windy = self._weather()
        return {"ABERTA": self.window >= 0.98, "FECHADA": self.window <= 0.02, "CHUVA": raining, "VENTO": windy}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        t_out, h_out, _ = self.outside()
        total = max(1, self.time_ms)
        minute = int((self.hours % 1) * 60)
        return [f"{self.hour:02d}:{minute:02d} | dentro {self.T:.1f} °C e {self.H:.0f}% | fora {t_out:.1f} °C e "
                f"{h_out:.0f}%",
                f"Tempo na faixa ideal: {100 * self.in_band_ms / total:.0f}% | aquecedor ligado "
                f"{self.heater_ms / HOUR_MS:.1f} h"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"AUTO": (16, 372, 150, 28), "CHUVA_MAN": (330, 372, 140, 28), "VENTO_MAN": (480, 372, 140, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        hod = self.hours % 24
        _, _, sun = self.outside()
        raining, windy = self._weather()
        day = 6 <= hod <= 18
        sky = QLinearGradient(0, 0, 0, 300)
        sky.setColorAt(0, QColor("#7dd3fc") if day and not raining else (QColor("#64748b") if day else QColor("#0f172a")))
        sky.setColorAt(1, QColor("#e0f2fe") if day and not raining else (QColor("#94a3b8") if day else QColor("#1e293b")))
        p.fillRect(QRectF(0, 0, 640, 300), sky)
        p.fillRect(QRectF(0, 300, 640, 120), QColor("#a3e635") if day else QColor("#365314"))
        if day:                                   # sol
            a = math.pi * (hod - 6) / 12
            c = QPointF(60 + 520 * (hod - 6) / 12, 120 - 90 * math.sin(a))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(250, 204, 21, 255 if not raining else 90))
            p.drawEllipse(c, 18, 18)
        if raining:
            p.setPen(QPen(QColor(59, 130, 246, 160), 1.5))
            for k in range(60):
                x = (k * 37 + self.time_ms / 8) % 640
                y = (k * 53 + self.time_ms / 4) % 300
                p.drawLine(QPointF(x, y), QPointF(x - 3, y + 10))
        if windy:
            p.setPen(QPen(QColor("#e2e8f0"), 2))
            for k in range(4):
                y = 40 + k * 30
                x = (self.time_ms / 3 + k * 140) % 700 - 60
                p.drawLine(QPointF(x, y), QPointF(x + 50, y))
        # estufa
        house = QRectF(170, 120, 300, 180)
        roof_top = QPointF(house.center().x(), 70)
        p.setPen(QPen(QColor("#334155"), 2))
        p.setBrush(QColor(224, 242, 254, 170))
        p.drawRect(house)
        p.drawPolygon(QPolygonF([house.topLeft(), roof_top, house.topRight()]))
        # janela do teto (abre girando)
        hinge = QPointF(roof_top.x() + 4, roof_top.y() + 2)
        slope = math.atan2(house.top() - roof_top.y(), house.right() - roof_top.x())   # fechada: sobre o telhado
        ang = slope - math.radians(40) * self.window                                   # aberta: levanta 40 graus
        tip = QPointF(hinge.x() + 80 * math.cos(ang), hinge.y() + 80 * math.sin(ang))
        p.setPen(QPen(QColor("#0369a1"), 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(hinge, tip)
        # plantas
        healthy = IDEAL_T[0] - 4 <= self.T <= IDEAL_T[1] + 5
        for k in range(7):
            x = house.left() + 26 + k * 40
            p.setPen(QPen(QColor("#166534") if healthy else QColor("#a16207"), 3))
            p.drawLine(QPointF(x, house.bottom()), QPointF(x, house.bottom() - 34))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#22c55e") if healthy else QColor("#ca8a04"))
            p.drawEllipse(QPointF(x - 7, house.bottom() - 30), 8, 5)
            p.drawEllipse(QPointF(x + 7, house.bottom() - 22), 8, 5)
        # equipamentos
        out = self.out
        if out.get("NEBULIZADOR"):
            p.setPen(QPen(QColor(186, 230, 253, 220), 2, Qt.DotLine))
            for k in range(6):
                x = house.left() + 40 + k * 44
                p.drawLine(QPointF(x, house.top() + 8), QPointF(x - 8, house.top() + 40))
        if out.get("LUZ"):
            p.setBrush(QColor(196, 181, 253, 120))
            p.setPen(Qt.NoPen)
            p.drawRect(house.adjusted(4, 4, -4, -60))
        fc = QPointF(house.right() - 22, house.top() + 40)
        p.setPen(QPen(QColor("#0f172a"), 1.2))
        p.setBrush(QColor("#cbd5e1"))
        p.drawEllipse(fc, 16, 16)
        p.setPen(QPen(QColor("#1d4ed8") if out.get("VENTILADOR") else QColor("#475569"), 3))
        for k in range(3):
            a = self.fan_angle + k * 2 * math.pi / 3
            p.drawLine(fc, QPointF(fc.x() + math.cos(a) * 13, fc.y() + math.sin(a) * 13))
        heater = QRectF(house.left() + 10, house.top() + 26, 34, 22)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#ef4444") if out.get("AQUECEDOR") else QColor("#64748b"))
        p.drawRoundedRect(heater, 4, 4)
        # mostradores
        panel = QRectF(486, 40, 140, 150)
        draw.panel(p, panel, "MEDIÇÕES")
        draw.text(p, panel.left() + 10, panel.top() + 34, f"{self.T:5.1f} °C", 13, True,
                  draw.RED if not IDEAL_T[0] <= self.T <= IDEAL_T[1] else draw.INK, w=130, h=24)
        draw.text(p, panel.left() + 10, panel.top() + 52, f"N0 = {round(self.T * 10)}", 7, True, draw.MUTED, w=120)
        draw.text(p, panel.left() + 10, panel.top() + 78, f"{self.H:5.0f} %", 13, True,
                  draw.RED if not IDEAL_H[0] <= self.H <= IDEAL_H[1] else draw.INK, w=130, h=24)
        draw.text(p, panel.left() + 10, panel.top() + 96, f"N1 = {round(self.H)}", 7, True, draw.MUTED, w=120)
        minute = int((self.hours % 1) * 60)
        draw.text(p, panel.left() + 10, panel.top() + 122, f"{self.hour:02d}:{minute:02d}", 13, True, draw.INK, w=130, h=24)
        draw.text(p, panel.left() + 10, panel.top() + 140, f"N2 = {self.hour}", 7, True, draw.MUTED, w=120)
        sens = self.sensors()
        draw.tag(p, 16, 40, "Q0.0 aquecedor", out.get("AQUECEDOR", False))
        draw.tag(p, 16, 62, "Q0.1 exaustor", out.get("VENTILADOR", False))
        draw.tag(p, 16, 84, "Q0.2 abre janela", out.get("ABRE", False))
        draw.tag(p, 16, 106, "Q0.3 fecha janela", out.get("FECHA", False))
        draw.tag(p, 16, 128, "Q0.4 nebulizador", out.get("NEBULIZADOR", False))
        draw.tag(p, 16, 150, "Q0.5 iluminação", out.get("LUZ", False))
        draw.tag(p, 16, 194, "I0.1 janela aberta", sens["ABERTA"])
        draw.tag(p, 16, 216, "I0.2 janela fechada", sens["FECHADA"])
        draw.tag(p, 16, 238, "I0.3 chuva", sens["CHUVA"])
        draw.tag(p, 16, 260, "I0.4 vento forte", sens["VENTO"])
        draw.lamp(p, QPointF(500, 216), 9, out.get("ALARME", False), draw.RED)
        draw.text(p, 514, 216, "ALARME Q0.6", 8, True, w=110)
        draw.switch(p, QRectF(16, 372, 150, 28), "AUTOMÁTICO I0.0", self.is_pressed("AUTO"))
        draw.switch(p, QRectF(330, 372, 140, 28), "Forçar chuva", self.forced_rain)
        draw.switch(p, QRectF(480, 372, 140, 28), "Forçar vento", self.forced_wind)
