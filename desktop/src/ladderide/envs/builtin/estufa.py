"""Estufa agricola: temperatura, umidade e solo analogicos, relogio do dia, chuva, vento e irrigacao."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from .. import draw
from ..base import SENSOR, SWITCH, Environment, IOPoint
from ..physics import History
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
ET_BASE, ET_SUN = 0.05, 0.30      # evapotranspiracao do solo (%/s): base e com sol a pino
IRRIGATION = 1.5                  # %/s de umidade do solo com a bomba
PUMP_LPS, RAIN_LPS = 4.0, 3.0     # litros/s: bomba e calha de chuva
TANK_L = 600.0
LOW_TANK = 0.10                   # sensor de reservatorio baixo: 10%
NOON = (11, 15)                   # sol forte: irrigar so com o solo muito seco
TEMP_WORD, HUM_WORD, HOUR_WORD, SOIL_WORD = 0, 1, 2, 3


@register
class GreenhouseEnvironment(Environment):
    id = "estufa"
    name = "Estufa agrícola com irrigação"
    description = ("A estufa escreve a temperatura em N0 (décimos de °C: 253 = 25,3 °C), a umidade do ar em N1 (%), "
                   "a hora em N2 (0 a 23; uma hora dura 10 s) e a umidade do solo em N3 (%). Faixas ideais: 20 a "
                   "28 °C e 55 a 85% de umidade. Aquecer ventilando é desperdício; janela aberta com chuva ou vento "
                   "estraga as plantas. Irrigação: o solo seca com o sol; molhe abaixo de 40% até 60%, mas não das "
                   "11 h às 15 h (sol forte), a não ser com o solo abaixo de 25%. A bomba não pode rodar com o "
                   "reservatório vazio (sensor de nível baixo I0.5); a chuva enche o reservatório pela calha.")
    example = "ambientes/estufa.ladproj"
    size = (720, 470)
    inputs = [
        IOPoint("AUTO", "I0.0", "Automatico", "Chave AUTOMÁTICO", SWITCH),
        IOPoint("ABERTA", "I0.1", "Janela_Aberta", "Fim de curso: janela do teto aberta"),
        IOPoint("FECHADA", "I0.2", "Janela_Fechada", "Fim de curso: janela do teto fechada"),
        IOPoint("CHUVA", "I0.3", "Sensor_Chuva", "Sensor de chuva", SENSOR),
        IOPoint("VENTO", "I0.4", "Sensor_Vento", "Anemômetro: vento forte", SENSOR),
        IOPoint("NIVEL_BAIXO", "I0.5", "Reservatorio_Baixo", "Reservatório abaixo de 10%"),
    ]
    outputs = [
        IOPoint("AQUECEDOR", "Q0.0", "Aquecedor", "Aquecedor a gás"),
        IOPoint("VENTILADOR", "Q0.1", "Exaustor", "Exaustores das paredes"),
        IOPoint("ABRE", "Q0.2", "Janela_Abre", "Motor da janela: abrir"),
        IOPoint("FECHA", "Q0.3", "Janela_Fecha", "Motor da janela: fechar"),
        IOPoint("NEBULIZADOR", "Q0.4", "Nebulizador", "Nebulizador (resfria e umedece)"),
        IOPoint("LUZ", "Q0.5", "Iluminacao", "Iluminação suplementar"),
        IOPoint("ALARME", "Q0.6", "Alarme", "Lâmpada de alarme"),
        IOPoint("BOMBA", "Q0.7", "Bomba_Irrigacao", "Bomba da irrigação por gotejamento"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(3)
        self.forced_rain = getattr(self, "forced_rain", False)
        self.forced_wind = getattr(self, "forced_wind", False)
        self.T, self.H = 15.0, 80.0
        self.soil = 55.0
        self.tank = 0.5 * TANK_L
        self.window = 0.0
        self.fan_angle = 0.0
        self.growth = 0.0                         # crescimento das plantas (0..1)
        self.health = 1.0
        self._plans: dict[int, tuple[tuple[float, float] | None, tuple[float, float] | None]] = {
            0: ((13.0, 15.0), (10.0, 11.0))}          # primeiro dia: chuva 13-15 h e vento 10-11 h
        self.in_band_ms = 0
        self.heater_ms = 0
        self.pump_ms = 0
        self.waste_ms = 0
        self.rain_in_ms = 0
        self.wind_in_ms = 0
        self.humid_ms = 0
        self.force_ms = 0
        self.both_ms = 0
        self.dry_run_ms = 0
        self.noon_ms = 0
        self.dry_soil_ms = 0
        self.wet_soil_ms = 0
        self.flags: dict[str, str] = {}
        self.trend = History(240, 1000, 3)
        self.drops: list[list[float]] = []

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
        return {TEMP_WORD: round(self.T * 10), HUM_WORD: round(self.H), HOUR_WORD: self.hour,
                SOIL_WORD: round(self.soil)}

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "CHUVA_MAN":
            self.forced_rain = not self.forced_rain
        elif key == "VENTO_MAN":
            self.forced_wind = not self.forced_wind
        elif key == "ENCHER":
            self.tank = TANK_L

    def press(self, key: str, down: bool) -> None:
        if key in ("CHUVA_MAN", "VENTO_MAN", "ENCHER"):
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
        # solo e irrigacao
        pumping = out["BOMBA"] and self.tank > 0
        self.soil -= (ET_BASE + ET_SUN * sun) * dt * (0.4 + self.soil / 100)
        dH += 0.05 * (self.soil > 50)
        if pumping:
            self.soil += IRRIGATION * dt
            self.tank = max(0.0, self.tank - PUMP_LPS * dt)
            self.pump_ms += dt_ms
            if self.rng.random() < 0.6:
                self.drops.append([0.0, self.rng.uniform(0, 1)])
        self.drops = [[t + dt, x] for t, x in self.drops if t < 0.5][-40:]
        if raining:
            self.tank = min(TANK_L, self.tank + RAIN_LPS * dt)
        self.soil = max(0.0, min(100.0, self.soil))
        self.dry_run_ms = self.dry_run_ms + dt_ms if (out["BOMBA"] and self.tank <= 0) else 0
        hod = self.hours % 24
        noon_waste = out["BOMBA"] and NOON[0] <= hod < NOON[1] and self.soil > 28 and sun > 0.5
        self.noon_ms = self.noon_ms + dt_ms if noon_waste else 0
        self.dry_soil_ms = self.dry_soil_ms + dt_ms if self.soil < 20 else 0
        self.wet_soil_ms = self.wet_soil_ms + dt_ms if self.soil > 90 else 0
        self.T += dT * dt
        self.H = min(100.0, max(10.0, self.H + dH * dt))
        good = IDEAL_T[0] <= self.T <= IDEAL_T[1] and IDEAL_H[0] <= self.H <= IDEAL_H[1]
        soil_ok = 30 <= self.soil <= 80
        self.in_band_ms += dt_ms if good else 0
        self.heater_ms += dt_ms if heater else 0
        light = sun + (0.5 if out["LUZ"] else 0.0)
        if good and soil_ok:
            self.growth = min(1.0, self.growth + 0.0037 * light * dt)   # ~3 dias para crescer
            self.health = min(1.0, self.health + 0.0005 * dt)
        elif not soil_ok or self.T > 33 or self.T < 10:
            self.health = max(0.2, self.health - 0.004 * dt)
        waste = heater and (fan or self.window > 0.1)
        self.waste_ms = self.waste_ms + dt_ms if waste else 0
        self.rain_in_ms = self.rain_in_ms + dt_ms if (raining and self.window > 0.05) else 0
        self.wind_in_ms = self.wind_in_ms + dt_ms if (windy and self.window > 0.05) else 0
        self.humid_ms = self.humid_ms + dt_ms if self.H > 92 else 0
        for key, cond, text in (
                ("waste", self.waste_ms > 5000, "Aquecedor ligado junto com a ventilação ou a janela aberta (desperdício)"),
                ("rain", self.rain_in_ms > WINDOW_S * 1000 + 2000, "Janela aberta com chuva: a água está entrando na estufa"),
                ("wind", self.wind_in_ms > WINDOW_S * 1000 + 2000, "Janela aberta com vento forte: risco de quebrar a janela"),
                ("hot", self.T > 35, "Plantas sofrendo calor: mais de 35 °C"),
                ("cold", self.T < 8, "Risco de geada: menos de 8 °C"),
                ("humid", self.humid_ms > 20000, "Umidade acima de 92% por muito tempo: risco de fungos"),
                ("force", self.force_ms > 2000, "Motor da janela forçando contra o fim de curso"),
                ("both", self.both_ms > 0, "Motor da janela comandado para abrir e fechar ao mesmo tempo"),
                ("dry_run", self.dry_run_ms > 2000, "Bomba de irrigação rodando a seco: respeite o nível baixo (I0.5)"),
                ("noon", self.noon_ms > 3000, "Irrigação no sol forte (11 h às 15 h) com o solo úmido: a água evapora "
                                             "e queima as folhas"),
                ("dry", self.dry_soil_ms > 10000, "Solo abaixo de 20%: as plantas estão murchando"),
                ("wet", self.wet_soil_ms > 10000, "Solo acima de 90%: encharcado, as raízes apodrecem")):
            if cond and key not in self.flags:
                self.flags[key] = text
        self.trend.add(dt_ms, self.T, self.H, self.soil)

    def sensors(self) -> dict[str, bool]:
        raining, windy = self._weather()
        return {"ABERTA": self.window >= 0.98, "FECHADA": self.window <= 0.02, "CHUVA": raining, "VENTO": windy,
                "NIVEL_BAIXO": self.tank < LOW_TANK * TANK_L}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        t_out, h_out, _ = self.outside()
        total = max(1, self.time_ms)
        minute = int((self.hours % 1) * 60)
        return [f"{self.hour:02d}:{minute:02d} | dentro {self.T:.1f} °C e {self.H:.0f}% | solo {self.soil:.0f}% | fora "
                f"{t_out:.1f} °C e {h_out:.0f}%",
                f"Na faixa ideal: {100 * self.in_band_ms / total:.0f}% do tempo | aquecedor {self.heater_ms / HOUR_MS:.1f} h"
                f" | irrigação {self.pump_ms / HOUR_MS:.1f} h | reservatório {self.tank:.0f} L"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"AUTO": (14, 432, 120, 28), "CHUVA_MAN": (140, 432, 110, 28), "VENTO_MAN": (256, 432, 110, 28),
                "ENCHER": (372, 432, 130, 28)}

    def paint(self, p: QPainter) -> None:
        hod = self.hours % 24
        t_out, _, sun = self.outside()
        raining, windy = self._weather()
        out = self.out
        sens = self.sensors()
        daylight = max(0.0, min(1.0, math.sin(math.pi * (hod - 5) / 14) * 1.4)) if 5 <= hod <= 19 else 0.0
        draw.sky(p, 720, 330, daylight * (0.55 if raining else 1.0))
        # sol ou lua
        if 6 <= hod <= 18:
            a = math.pi * (hod - 6) / 12
            c = QPointF(40 + 640 * (hod - 6) / 12, 150 - 120 * math.sin(a))
            g = QRadialGradient(c, 36)
            g.setColorAt(0, QColor(253, 224, 71, 255 if not raining else 110))
            g.setColorAt(0.45, QColor(250, 204, 21, 200 if not raining else 70))
            g.setColorAt(1, QColor(250, 204, 21, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawEllipse(c, 36, 36)
        else:
            h2 = (hod - 18) % 24
            c = QPointF(40 + 640 * h2 / 12, 150 - 110 * math.sin(math.pi * h2 / 12))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#e2e8f0"))
            p.drawEllipse(c, 13, 13)
            p.setBrush(QColor(15, 23, 42, 220))
            p.drawEllipse(c + QPointF(5, -3), 11, 11)
            p.setBrush(QColor(255, 255, 255, 140))
            for k in range(14):
                p.drawEllipse(QPointF((k * 97) % 700 + 10, (k * 53) % 140 + 10), 1.2, 1.2)
        if raining:
            for k in range(3):
                cc = QPointF(120 + k * 220 + (self.time_ms / 200) % 40, 50 + 10 * k)
                p.setBrush(QColor(100, 116, 139, 200))
                p.drawEllipse(cc, 60, 22)
                p.drawEllipse(cc + QPointF(30, -10), 40, 20)
            p.setPen(QPen(QColor(147, 197, 253, 180), 1.2))
            off = (self.time_ms / 4) % 40
            for k in range(90):
                x = (k * 37) % 720
                y = (k * 61 + off * 3) % 320
                p.drawLine(QPointF(x, y), QPointF(x - 3, y + 8))
        if windy:
            p.setPen(QPen(QColor(255, 255, 255, 150), 2, Qt.SolidLine, Qt.RoundCap))
            off = (self.time_ms / 3) % 720
            for k in range(6):
                y = 40 + k * 40
                x = (off + k * 130) % 760 - 40
                path = QPainterPath(QPointF(x, y))
                path.cubicTo(QPointF(x + 30, y - 8), QPointF(x + 50, y + 8), QPointF(x + 80, y))
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
        draw.grass(p, 330, 720, 470)
        # estufa (arco de vidro)
        gx, gy, gw, gh = 150, 170, 420, 170
        house = QPainterPath()
        house.moveTo(gx, gy + gh)
        house.lineTo(gx, gy + 50)
        house.quadTo(gx + gw / 2, gy - 40, gx + gw, gy + 50)
        house.lineTo(gx + gw, gy + gh)
        house.closeSubpath()
        heat = max(0.0, min(1.0, (self.T - 15) / 20))
        glass = QLinearGradient(gx, gy, gx, gy + gh)
        glass.setColorAt(0, QColor(186, 230, 253, 150))
        glass.setColorAt(1, draw.mix(QColor(219, 234, 254), QColor(254, 202, 202), heat))
        p.setPen(QPen(QColor("#475569"), 2))
        p.setBrush(glass)
        p.drawPath(house)
        p.setPen(QPen(QColor(71, 85, 105, 140), 1.2))
        for k in range(1, 7):
            x = gx + gw * k / 7
            p.drawLine(QPointF(x, gy + gh), QPointF(x, gy + 50 - 36 * math.sin(math.pi * k / 7)))
        # janela do teto (aba que abre)
        hinge = QPointF(gx + gw / 2 - 40, gy + 6)
        ang = math.radians(-10 - 40 * self.window)
        tip = QPointF(hinge.x() + 80 * math.cos(ang), hinge.y() + 80 * math.sin(ang))
        p.setPen(QPen(QColor("#1e3a8a"), 4, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(hinge, tip)
        draw.tag(p, gx + gw / 2 + 50, gy - 24, f"janela {self.window * 100:.0f}%", None)
        # canteiros e plantas
        bed_y = gy + gh - 18
        p.fillRect(QRectF(gx + 10, bed_y, gw - 20, 14), draw.mix(QColor("#a16207"), QColor("#422006"), self.soil / 100))
        green = draw.mix(QColor("#a3a33a"), QColor("#16a34a"), self.health)
        for k in range(10):
            x = gx + 30 + k * (gw - 60) / 9
            h = 16 + 44 * self.growth
            sway = math.sin(self.time_ms / 400 + k) * (3 if out.get("VENTILADOR") else 1)
            p.setPen(QPen(QColor("#166534"), 2))
            p.drawLine(QPointF(x, bed_y), QPointF(x + sway, bed_y - h))
            p.setPen(Qt.NoPen)
            p.setBrush(green)
            for j in range(3):
                yy = bed_y - h * (0.35 + 0.3 * j)
                p.drawEllipse(QPointF(x + sway * (0.4 + 0.3 * j) - 7, yy), 7, 3.5)
                p.drawEllipse(QPointF(x + sway * (0.4 + 0.3 * j) + 7, yy - 3), 7, 3.5)
            if self.growth > 0.6:
                p.setBrush(QColor("#dc2626"))
                p.drawEllipse(QPointF(x + sway + 3, bed_y - h * 0.5), 3, 3)
        # gotejamento
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.drawLine(QPointF(gx + 14, bed_y - 4), QPointF(gx + gw - 14, bed_y - 4))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(56, 189, 248, 220))
        for t, x in self.drops:
            p.drawEllipse(QPointF(gx + 20 + x * (gw - 40), bed_y - 4 + t * 24), 1.8, 2.4)
        # aquecedor, exaustor, nebulizador e luzes
        hr = QRectF(gx + 14, gy + 70, 46, 30)
        draw.metal(p, hr, "#b91c1c" if out.get("AQUECEDOR") else "#475569", 4)
        if out.get("AQUECEDOR"):
            glow = QRadialGradient(hr.center(), 50)
            glow.setColorAt(0, QColor(249, 115, 22, 110))
            glow.setColorAt(1, QColor(249, 115, 22, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(hr.center(), 50, 50)
        draw.ctext(p, hr.center().x(), hr.center().y(), "Q0.0", 6.5, True, draw.WHITE, 46)
        draw.fan(p, QPointF(gx + gw - 32, gy + 86), 18, self.fan_angle, bool(out.get("VENTILADOR")))
        draw.tag(p, gx + gw - 52, gy + 116, "Q0.1", out.get("VENTILADOR", False))
        if out.get("NEBULIZADOR"):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(255, 255, 255, 150))
            for k in range(26):
                x = gx + 40 + (k * 31 + self.time_ms / 30) % (gw - 80)
                y = gy + 60 + (k * 17) % 50
                p.drawEllipse(QPointF(x, y), 4, 3)
        for k in range(4):
            lc = QPointF(gx + 110 + k * 70, gy + 30)
            if out.get("LUZ"):
                g = QRadialGradient(lc, 40)
                g.setColorAt(0, QColor(232, 121, 249, 120))
                g.setColorAt(1, QColor(232, 121, 249, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawEllipse(lc, 40, 40)
            draw.metal(p, QRectF(lc.x() - 12, lc.y() - 3, 24, 6), "#c026d3" if out.get("LUZ") else "#64748b", 2)
        # reservatorio, calha e bomba
        tank = QRectF(600, 230, 70, 100)
        draw.tank(p, tank, self.tank / TANK_L, QColor("#38bdf8"), wave=self.time_ms / 300)
        draw.ctext(p, tank.center().x(), tank.top() + 16, f"{self.tank:.0f} L", 7, True, draw.INK, 70)
        draw.pipe(p, [QPointF(gx + gw, gy + 54), QPointF(tank.center().x(), gy + 54), QPointF(tank.center().x(), tank.top())],
                  5, self.time_ms / 25 if raining else None, QColor("#93c5fd"))
        draw.tag(p, 608, 344, "I0.5 nível baixo", sens["NIVEL_BAIXO"])
        pump_c = QPointF(586, 316)
        draw.motor(p, pump_c, 9, bool(out.get("BOMBA")) and self.tank > 0, self.time_ms / 60, "")
        draw.pipe(p, [QPointF(tank.left(), 318), QPointF(pump_c.x() + 6, 318)], 4, None)
        draw.pipe(p, [QPointF(pump_c.x() - 14, 318), QPointF(gx + gw - 10, bed_y - 4)], 4,
                  self.time_ms / 20 if out.get("BOMBA") and self.tank > 0 else None)
        draw.tag(p, 500, 356, "Q0.7 bomba", out.get("BOMBA", False))
        # sensores do tempo
        draw.tag(p, 8, 186, "I0.3 chuva", sens["CHUVA"])
        draw.tag(p, 8, 208, "I0.4 vento", sens["VENTO"])
        draw.tag(p, 8, 230, "I0.1 aberta", sens["ABERTA"])
        draw.tag(p, 8, 252, "I0.2 fechada", sens["FECHADA"])
        draw.tag(p, 8, 274, "Q0.2 abre", out.get("ABRE", False))
        draw.tag(p, 8, 296, "Q0.3 fecha", out.get("FECHA", False))
        draw.tag(p, 8, 318, "Q0.4 névoa", out.get("NEBULIZADOR", False))
        draw.tag(p, 80, 318, "Q0.5 luz", out.get("LUZ", False))
        # painel
        card = QRectF(8, 8, 300, 166)
        draw.card(p, card, f"Painel  {self.hour:02d}:{int((self.hours % 1) * 60):02d}  (N2 = {self.hour})")
        draw.lcd(p, QRectF(16, 34, 92, 34), f"{self.T:5.1f}", "#fb923c", "N0 °C")
        draw.lcd(p, QRectF(112, 34, 92, 34), f"{self.H:4.0f}", "#38bdf8", "N1 umidade %")
        draw.lcd(p, QRectF(208, 34, 92, 34), f"{self.soil:4.0f}", "#a3e635", "N3 solo %")
        draw.trend(p, QRectF(14, 74, 290, 94), [(self.trend.series(0), "#f97316"), (self.trend.series(1), "#0ea5e9"),
                                               (self.trend.series(2), "#65a30d")], 0, 100, "",
                   [(20, "#fed7aa"), (28, "#fed7aa")], 240)
        draw.lamp(p, QPointF(326, 22), 7, out.get("ALARME", False), draw.RED)
        draw.text(p, 338, 22, "ALARME Q0.6", 7, True, draw.WHITE if daylight < 0.4 else draw.INK, w=90)
        draw.text(p, 600, 22, f"fora {t_out:.0f} °C", 8, True, draw.WHITE if daylight < 0.4 else draw.INK, w=110)
        draw.text(p, 600, 40, f"plantas {self.growth * 100:.0f}%", 7.5, True,
                  draw.WHITE if daylight < 0.4 else draw.INK, w=110)
        # controles
        draw.switch(p, QRectF(14, 432, 120, 28), "AUTO I0.0", self.is_pressed("AUTO"))
        draw.switch(p, QRectF(140, 432, 110, 28), "Chover", self.forced_rain)
        draw.switch(p, QRectF(256, 432, 110, 28), "Ventar", self.forced_wind)
        draw.push_button(p, QRectF(372, 432, 130, 28), "Encher reserv.", False, draw.BLUE)
