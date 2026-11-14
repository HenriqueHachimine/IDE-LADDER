"""Controle de demanda de energia: projecao da media da janela e corte de cargas por prioridade."""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QPainter

from .. import draw
from ..base import Environment, IOPoint
from ..physics import History
from ..registry import register

WINDOW_S = 120                # janela de demanda (15 min reais = 120 s simulados)
CONTRACT = 400                # kW contratados
LOADS = {                     # chave: (nome, kW)
    "AC1": ("Ar-condicionado 1", 50),
    "AC2": ("Ar-condicionado 2", 50),
    "COMP": ("Compressor de ar", 75),
    "AQ": ("Aquecedor de água", 60),
    "BOMBA": ("Bomba d'água", 30),
}
ROOM_GAIN, AC_COOL = 0.06, 0.16       # degC/s: sala esquenta / ar-condicionado esfria
AIR_USE, COMP_FILL = 0.025, 0.06      # bar/s: consumo de ar / compressor
WATER_LOSS, HEATER = 0.08, 0.30       # degC/s: agua esfria / aquecedor
TANK_USE, PUMP_FILL = 0.6, 1.5        # %/s: consumo de agua / bomba
POWER_WORD, ENERGY_WORD, LEFT_WORD, CONTRACT_WORD = 0, 1, 2, 3


@register
class DemandControlEnvironment(Environment):
    id = "demanda_energia"
    name = "Controle de demanda de energia"
    description = ("A concessionária cobra multa se a potência MÉDIA da janela de 15 minutos (aqui, 120 s) passar dos "
                   "400 kW contratados. O medidor escreve a potência atual em N0 (kW), a energia da janela em N1 "
                   "(kW·s), os segundos que faltam em N2 e o contrato em N3, e dá um pulso de sincronismo (I0.0) no "
                   "fim de cada janela. A produção alterna janelas pesadas (~300 kW de máquinas) e leves (~170 kW); cinco cargas pedem para ligar pelos "
                   "seus termostatos (I0.1 a I0.5) e o programa decide (Q0.0 a Q0.4). Projete a média do fim da "
                   "janela e corte cargas por prioridade (aquecedor, ar-condicionado, compressor), sem passar dos "
                   "limites de conforto: sala até 27 °C, ar comprimido acima de 6 bar, água acima de 45 °C e caixa "
                   "d'água acima de 10%.")
    example = "ambientes/demanda_energia.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("SINC", "I0.0", "Pulso_Sincronismo", "Pulso do medidor no fim da janela de demanda"),
        IOPoint("P_AC1", "I0.1", "Pede_AC1", "Termostato da sala 1 pede frio"),
        IOPoint("P_AC2", "I0.2", "Pede_AC2", "Termostato da sala 2 pede frio"),
        IOPoint("P_COMP", "I0.3", "Pede_Compressor", "Pressostato: pressão de ar baixa (pede o compressor)"),
        IOPoint("P_AQ", "I0.4", "Pede_Aquecedor", "Termostato da água pede aquecimento"),
        IOPoint("P_BOMBA", "I0.5", "Pede_Bomba", "Boia da caixa d'água pede a bomba"),
    ]
    outputs = [
        IOPoint("AC1", "Q0.0", "Ar_Cond_1", "Ar-condicionado 1 (50 kW)"),
        IOPoint("AC2", "Q0.1", "Ar_Cond_2", "Ar-condicionado 2 (50 kW)"),
        IOPoint("COMP", "Q0.2", "Compressor", "Compressor de ar (75 kW)"),
        IOPoint("AQ", "Q0.3", "Aquecedor", "Aquecedor de água (60 kW)"),
        IOPoint("BOMBA", "Q0.4", "Bomba", "Bomba d'água (30 kW)"),
        IOPoint("ALERTA", "Q0.5", "Lampada_Demanda", "Lâmpada DEMANDA ALTA (projeção acima do contrato)"),
        IOPoint("CORTE", "Q0.6", "Lampada_Corte", "Lâmpada CORTE DE CARGA ATIVO"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(17)
        self.base = 220.0
        self.base_target = 220.0
        self.next_base_ms = 0
        self.window_t = 0.0
        self.energy = 0.0
        self.windows: list[float] = []
        self.room = [23.0, 24.0]
        self.air = 7.5
        self.water = 62.0
        self.tank = 70.0
        self.req = {"AC1": False, "AC2": False, "COMP": False, "AQ": False, "BOMBA": False}
        self.flags: dict[str, str] = {}
        self.sync_ms = 0
        self.power = 0.0
        self.peak_avg = 0.0
        self.trend = History(240, 500, 3)
        self.windows_over = 0

    # ------------------------------------------------------- registradores
    def input_words(self) -> dict[int, int]:
        return {POWER_WORD: round(self.power), ENERGY_WORD: round(self.energy),
                LEFT_WORD: max(0, round(WINDOW_S - self.window_t)), CONTRACT_WORD: CONTRACT}

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        # carga das maquinas: janelas de producao pesada (~300 kW) e leve (~170 kW), com variacoes
        if now >= self.next_base_ms:
            heavy = (now // (WINDOW_S * 1000)) % 2 == 0
            self.base_target = (300 if heavy else 170) + self.rng.choice([-25, -10, 0, 10, 25])
            self.next_base_ms = now + int(self.rng.uniform(5000, 10000))
        self.base += (self.base_target - self.base) * min(1.0, dt / 2.0)
        # processos atendidos pelas cargas
        for k, key in enumerate(("AC1", "AC2")):
            self.room[k] += (ROOM_GAIN * (1.2 if k else 1.0) - (AC_COOL if out[key] else 0.0)) * dt
        self.air += ((COMP_FILL if out["COMP"] else 0.0) - AIR_USE) * dt
        self.water += ((HEATER if out["AQ"] else 0.0) - WATER_LOSS) * dt
        self.tank = max(0.0, min(100.0, self.tank + ((PUMP_FILL if out["BOMBA"] else 0.0) - TANK_USE) * dt))
        # termostatos (pedidos) com histerese
        for k, key in enumerate(("AC1", "AC2")):
            if self.room[k] >= 24.0:
                self.req[key] = True
            elif self.room[k] <= 22.0:
                self.req[key] = False
        self.req["COMP"] = self.air <= 7.0 or (self.req["COMP"] and self.air < 8.0)
        self.req["AQ"] = self.water <= 58.0 or (self.req["AQ"] and self.water < 65.0)
        self.req["BOMBA"] = self.tank <= 40.0 or (self.req["BOMBA"] and self.tank < 90.0)
        # potencia e janela de demanda
        self.power = self.base + 15 + sum(kw for key, (_, kw) in LOADS.items() if out[key])
        self.energy += self.power * dt
        self.window_t += dt
        if self.window_t >= WINDOW_S:
            avg = self.energy / WINDOW_S
            self.windows.append(avg)
            self.peak_avg = max(self.peak_avg, avg)
            if avg > CONTRACT:
                self.windows_over += 1
                self.flags.setdefault("over", "Ultrapassagem de demanda: a média da janela passou do contrato (multa)")
            self.window_t, self.energy = 0.0, 0.0
            self.sync_ms = 300
        self.sync_ms = max(0, self.sync_ms - dt_ms)
        # limites de conforto e de processo
        for k, (key, name) in enumerate((("AC1", "sala 1"), ("AC2", "sala 2"))):
            if self.room[k] > 27.0:
                self.flags.setdefault("room", "Sala acima de 27 °C: ar-condicionado cortado por tempo demais (faça "
                                              "rodízio ou limite o tempo de corte)")
        if self.air < 6.0:
            self.flags.setdefault("air", "Ar comprimido abaixo de 6 bar: as máquinas pneumáticas pararam")
        if self.water < 45.0:
            self.flags.setdefault("water", "Água abaixo de 45 °C no vestiário")
        if self.tank < 10.0:
            self.flags.setdefault("tank", "Caixa d'água abaixo de 10%: não corte a bomba")
        for key in LOADS:
            if out[key] and not self.req[key] and key in ("AQ", "BOMBA"):
                if (key == "AQ" and self.water > 75) or (key == "BOMBA" and self.tank >= 99.5):
                    self.flags.setdefault("norequest", "Carga ligada sem pedido do termostato (água fervendo ou "
                                                       "caixa transbordando)")
        self.trend.add(dt_ms, self.power, self.partial_average(), self.base)

    def partial_average(self) -> float:
        if self.window_t >= 3.0:
            return self.energy / self.window_t
        return self.windows[-1] if self.windows else self.power

    def sensors(self) -> dict[str, bool]:
        s = {"SINC": self.sync_ms > 0}
        for key in LOADS:
            s["P_" + key] = self.req[key]
        return s

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        last = "-" if not self.windows else f"{self.windows[-1]:.0f} kW"
        return [f"Potência N0 = {self.power:.0f} kW | média parcial {self.energy / max(1.0, self.window_t):.0f} kW | "
                f"faltam {WINDOW_S - self.window_t:.0f} s",
                f"Última janela: {last} | maior: {self.peak_avg:.0f} kW | janelas com multa: {self.windows_over}"]

    # ------------------------------------------------------------ desenho
    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out = self.out
        sens = self.sensors()
        # medidor
        draw.card(p, QRectF(8, 8, 300, 176), "Medidor de energia")
        draw.gauge(p, QPointF(80, 92), 50, self.power, 0, 600, "Potência N0", "kW",
                   [(0, 360, "#86efac"), (360, 400, "#fde047"), (400, 600, "#fca5a5")])
        avg = self.partial_average()
        draw.lcd(p, QRectF(150, 36, 150, 32), f"{avg:4.0f} kW", "#fbbf24", "média parcial")
        draw.lcd(p, QRectF(150, 74, 150, 32), f"{round(self.energy):7d}", "#60a5fa", "N1 energia (kW·s)")
        draw.lcd(p, QRectF(150, 112, 150, 32), f"{WINDOW_S - self.window_t:4.0f} s", "#4ade80", "N2 resta na janela")
        draw.bar(p, QRectF(20, 166, 280, 8), self.window_t / WINDOW_S, draw.BLUE)
        draw.tag(p, 220, 152, "I0.0 sinc", sens["SINC"])
        # tendencia
        draw.trend(p, QRectF(316, 8, 396, 176), [(self.trend.series(0), "#dc2626"), (self.trend.series(1), "#f59e0b"),
                                                 (self.trend.series(2), "#94a3b8")], 0, 600,
                   "Potência (vermelho), média da janela (laranja), máquinas (cinza)", [(CONTRACT, "#7f1d1d")], 240)
        # cargas
        rows = [("AC1", f"sala 1: {self.room[0]:.1f} °C", self.room[0] / 30),
                ("AC2", f"sala 2: {self.room[1]:.1f} °C", self.room[1] / 30),
                ("COMP", f"ar: {self.air:.1f} bar", self.air / 9),
                ("AQ", f"água: {self.water:.0f} °C", self.water / 80),
                ("BOMBA", f"caixa: {self.tank:.0f}%", self.tank / 100)]
        draw.card(p, QRectF(8, 194, 704, 210), "Cargas (pedido do termostato → saída do CLP)")
        for k, (key, info, frac) in enumerate(rows):
            y = 228 + k * 34
            name, kw = LOADS[key]
            req = self.req[key]
            on = out.get(key, False)
            draw.text(p, 20, y, f"{name} ({kw} kW)", 8, True, w=170)
            draw.tag(p, 196, y, f"I0.{k + 1} pede", req)
            draw.harrow(p, QPointF(264, y), 10, True, True, QColor("#94a3b8"))
            draw.tag(p, 276, y, f"Q0.{k} liga", on)
            state = "LIGADA" if on else ("CORTADA" if req else "desligada")
            col = draw.GREEN if on else (draw.RED if req else draw.MUTED)
            draw.text(p, 350, y, state, 8, True, col, w=90)
            draw.text(p, 450, y, info, 8, False, draw.INK, w=140)
            draw.bar(p, QRectF(590, y - 5, 110, 10), frac, draw.mix(draw.BLUE, draw.RED, frac))
        # lampadas
        draw.card(p, QRectF(8, 412, 704, 40))
        draw.lamp(p, QPointF(30, 432), 8, out.get("ALERTA", False), draw.AMBER)
        draw.text(p, 44, 432, "DEMANDA ALTA Q0.5", 8, True, w=150)
        draw.lamp(p, QPointF(220, 432), 8, out.get("CORTE", False), draw.RED)
        draw.text(p, 234, 432, "CORTE ATIVO Q0.6", 8, True, w=150)
        draw.text(p, 420, 432, f"Contrato N3 = {CONTRACT} kW | janelas com multa: {self.windows_over}", 8, True,
                  draw.INK, w=300)
