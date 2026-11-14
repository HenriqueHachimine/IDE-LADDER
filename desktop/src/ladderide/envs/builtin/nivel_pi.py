"""Controle de nivel PI: valvula de controle analogica, consumo variavel e protecoes por chave de nivel."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..physics import DelayLine, History, approach
from ..registry import register

HEIGHT = 2000.0               # mm (tanque de 1 m2: 1 L = 1 mm)
Q_MAX = 40.0                  # L/s com a valvula toda aberta
VALVE_TAU = 2.0               # s: o posicionador segue o comando com atraso
DEAD_S = 1.0                  # s: tempo morto da tubulacao ate o tanque
LSH, LSL = 1850.0, 150.0      # chaves de nivel alto e baixo (mm)
DEMANDS = {"BAIXO": 10.0, "MEDIO": 20.0, "ALTO": 30.0}   # L/s consumidos
SETPOINTS = (800, 1000, 1200, 1500)
AUTO_CHANGE_MS = 60000        # perfil automatico: muda o consumo a cada 60 s
TRACK_TOL, TRACK_MS = 250.0, 40000   # erro maior que 250 mm por 40 s: o controle nao segue
LEVEL_WORD, VALVE_WORD, SP_WORD = 0, 1, 2


@register
class LevelControlEnvironment(Environment):
    id = "nivel_pi"
    name = "Controle de nível PI"
    description = ("Tanque de 2 m alimentado por uma válvula de controle (0 a 100%: o programa escreve a abertura em "
                   "N1) e esvaziado pelo consumo da fábrica (10, 20 ou 30 L/s, muda sozinho no perfil automático). "
                   "O nível chega em N0 (mm) e o setpoint escolhido pelo operador em N2. A válvula segue o comando "
                   "com atraso (2 s) e há 1 s de tempo morto na tubulação. Faça um controle PI: P = Kp x erro, I "
                   "acumula o erro a cada período, saída limitada a 0..100% sem deixar o integral crescer quando "
                   "satura (anti-windup). Chaves de nível alto (I0.1) e baixo (I0.2) protegem o tanque e a bomba.")
    example = "ambientes/nivel_pi.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("AUTO", "I0.0", "Automatico", "Chave AUTOMÁTICO (malha fechada)", SWITCH),
        IOPoint("LSH", "I0.1", "Nivel_Alto", "Chave de nível alto (1850 mm)"),
        IOPoint("LSL", "I0.2", "Nivel_Baixo", "Chave de nível baixo (150 mm)"),
    ]
    outputs = [
        IOPoint("BOMBA", "Q0.0", "Bomba_Alimentacao", "Bomba de alimentação (a válvula só tem vazão com ela)"),
        IOPoint("CONSUMO", "Q0.1", "Bomba_Consumo", "Bomba de saída para o consumo"),
        IOPoint("ALTO", "Q0.2", "Alarme_Alto", "Lâmpada NÍVEL ALTO"),
        IOPoint("BAIXO", "Q0.3", "Alarme_Baixo", "Lâmpada NÍVEL BAIXO"),
    ]

    def reset(self) -> None:
        self.level = 500.0
        self.valve = 0.0                 # abertura real (%)
        self.cmd: int | None = None      # comando escrito pelo programa em N1
        self.pipe = DelayLine(DEAD_S)
        self.demand_key = getattr(self, "demand_key", "MEDIO")
        self.profile = getattr(self, "profile", True)
        self.setpoint = getattr(self, "setpoint", 1000)
        self.next_change_ms = AUTO_CHANGE_MS
        self._profile_k = 0
        self.flags: dict[str, str] = {}
        self.off_ms = 0
        self.lsh_open_ms = 0
        self.iae = 0.0                   # integral do erro absoluto (mm.s) em automatico
        self.auto_ms = 0
        self.trend = History(200, 500, 3)
        self.wave = 0.0

    # ------------------------------------------------------- registradores
    def input_words(self) -> dict[int, int]:
        return {LEVEL_WORD: round(self.level), SP_WORD: self.setpoint}

    def advance_words(self, n: list[int]) -> None:
        self.cmd = n[VALVE_WORD] if len(n) > VALVE_WORD else None

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key in DEMANDS:
            self.demand_key = key
            self.profile = False
        elif key == "PERFIL":
            self.profile = not self.profile
        elif key == "SP":
            self.setpoint = SETPOINTS[(SETPOINTS.index(self.setpoint) + 1) % len(SETPOINTS)] \
                if self.setpoint in SETPOINTS else SETPOINTS[0]

    def press(self, key: str, down: bool) -> None:
        if key in DEMANDS or key in ("PERFIL", "SP"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        if self.profile and now >= self.next_change_ms:
            seq = ("ALTO", "BAIXO", "MEDIO", "ALTO", "MEDIO")
            self._profile_k = (self._profile_k + 1) % len(seq)
            self.demand_key = seq[self._profile_k]
            self.next_change_ms = now + AUTO_CHANGE_MS
        cmd = self.cmd if self.cmd is not None else 0
        if cmd < 0 or cmd > 100:
            self.flags.setdefault("range", "Comando da válvula (N1) fora de 0 a 100%: limite a saída do PI")
        target = max(0.0, min(100.0, float(cmd)))
        self.valve += (target - self.valve) * min(1.0, dt / VALVE_TAU)
        q_in = Q_MAX * self.valve / 100 if out["BOMBA"] else 0.0
        self.pipe.push(q_in * dt)
        arrived = self.pipe.advance(dt)
        demand = DEMANDS[self.demand_key] if out["CONSUMO"] else 0.0
        self.level += arrived
        if out["CONSUMO"] and self.level <= 0.5:
            self.flags.setdefault("dry", "Bomba de consumo rodando com o tanque vazio: desligue pela chave de nível "
                                         "baixo (I0.2)")
        self.level = max(0.0, self.level - demand * dt)
        if self.level >= HEIGHT:
            self.level = HEIGHT
            self.flags.setdefault("over", "O tanque transbordou")
        self.lsh_open_ms = self.lsh_open_ms + dt_ms if (self.level >= LSH and out["BOMBA"] and self.valve > 5) else 0
        if self.lsh_open_ms > 3000:
            self.flags.setdefault("lsh", "Nível alto com a alimentação ligada: a chave I0.1 deve cortar a bomba")
        if self.is_pressed("AUTO"):
            err = abs(self.level - self.setpoint)
            self.auto_ms += dt_ms
            if self.auto_ms > 30000:
                self.iae += err * dt
            self.off_ms = self.off_ms + dt_ms if err > TRACK_TOL else 0
            if self.off_ms > TRACK_MS:
                self.flags.setdefault("track", "O nível ficou longe do setpoint por mais de 40 s: ajuste o PI")
        else:
            self.off_ms = 0
        self.wave += dt * (1 + abs(arrived / dt if dt else 0) / 10)
        self.trend.add(dt_ms, self.level, self.setpoint, self.valve * 20)

    def sensors(self) -> dict[str, bool]:
        return {"LSH": self.level >= LSH, "LSL": self.level <= LSL}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        cmd = "--" if self.cmd is None else f"{self.cmd}%"
        return [f"Nível N0 = {self.level:.0f} mm | setpoint N2 = {self.setpoint} mm | válvula: comando N1 {cmd}, "
                f"real {self.valve:.0f}%",
                f"Consumo {DEMANDS[self.demand_key]:.0f} L/s" + (" (perfil automático)" if self.profile else "")
                + f" | erro médio {self.iae / max(1.0, (self.auto_ms - 30000) / 1000):.0f} mm"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"SP": (14, 300, 150, 30), "BAIXO": (14, 352, 70, 26), "MEDIO": (88, 352, 70, 26),
                "ALTO": (162, 352, 70, 26), "PERFIL": (14, 386, 218, 26), "AUTO": (14, 420, 218, 28)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        draw.ground(p, 420, 720, 460)
        out = self.out
        sens = self.sensors()
        tank = QRectF(330, 90, 140, 300)
        frac = self.level / HEIGHT
        draw.tank(p, tank, frac, QColor("#38bdf8"), wave=self.wave)
        inner = tank.adjusted(6, 6, -6, -6)
        sp_y = inner.bottom() - inner.height() * self.setpoint / HEIGHT
        p.setPen(QPen(QColor("#16a34a"), 2, Qt.DashLine))
        p.drawLine(QPointF(inner.left() - 14, sp_y), QPointF(inner.right() + 14, sp_y))
        draw.text(p, inner.right() + 16, sp_y, f"SP {self.setpoint}", 7, True, draw.GREEN, w=60)
        for lvl, key, addr in ((LSH, "LSH", "I0.1 alto"), (LSL, "LSL", "I0.2 baixo")):
            y = inner.bottom() - inner.height() * lvl / HEIGHT
            draw.sensor(p, QRectF(tank.left() - 22, y - 5, 18, 10), sens[key], vertical=False)
            draw.tag(p, tank.left() - 92, y, addr, sens[key])
        # alimentacao: bomba, valvula de controle e tubo
        flowing = out.get("BOMBA") and self.valve > 2
        draw.pipe(p, [QPointF(40, 60), QPointF(260, 60), QPointF(260, 70), QPointF(400, 70), QPointF(400, 96)], 10,
                  self.time_ms / 15 if flowing else None)
        draw.motor(p, QPointF(70, 60), 14, bool(out.get("BOMBA")), self.time_ms / 50 if out.get("BOMBA") else 0)
        draw.tag(p, 50, 88, "Q0.0 bomba", out.get("BOMBA", False))
        vc = QPointF(190, 60)
        draw.valve(p, vc, 22, self.valve > 2)
        draw.lcd(p, QRectF(150, 4, 90, 30), f"{self.valve:3.0f}%", "#fbbf24", "abertura real")
        cmd = "--" if self.cmd is None else str(self.cmd)
        draw.tag(p, 244, 20, f"N1 = {cmd}", None)
        # saida e consumo
        consuming = out.get("CONSUMO") and self.level > 0
        draw.pipe(p, [QPointF(400, 384), QPointF(400, 404), QPointF(560, 404), QPointF(560, 300), QPointF(690, 300)],
                  10, self.time_ms / 15 if consuming else None)
        draw.motor(p, QPointF(500, 404), 13, bool(consuming), self.time_ms / 50 if consuming else 0)
        draw.tag(p, 470, 432, "Q0.1 consumo", out.get("CONSUMO", False))
        factory = QRectF(600, 230, 110, 60)
        draw.metal(p, factory, "#64748b", 4)
        draw.ctext(p, factory.center().x(), factory.top() + 16, "FÁBRICA", 7.5, True, draw.WHITE, 110)
        draw.ctext(p, factory.center().x(), factory.top() + 38, f"{DEMANDS[self.demand_key]:.0f} L/s", 10, True,
                   QColor("#fde68a"), 110)
        # faceplate e tendencia
        draw.card(p, QRectF(470, 14, 240, 200), "Malha de nível (N0 / N2 / N1)")
        draw.lcd(p, QRectF(480, 40, 70, 30), f"{self.level:4.0f}", "#38bdf8", "PV N0")
        draw.lcd(p, QRectF(556, 40, 70, 30), f"{self.setpoint:4d}", "#4ade80", "SP N2")
        draw.lcd(p, QRectF(632, 40, 70, 30), cmd, "#fbbf24", "MV N1 %")
        draw.trend(p, QRectF(474, 76, 232, 134), [(self.trend.series(0), "#0284c7"), (self.trend.series(1), "#16a34a"),
                                                  (self.trend.series(2), "#f59e0b")], 0, 2000, "", [], 200)
        draw.lamp(p, QPointF(606, 330), 7, out.get("ALTO", False), draw.RED)
        draw.text(p, 618, 330, "ALTO Q0.2", 7, True, w=80)
        draw.lamp(p, QPointF(606, 354), 7, out.get("BAIXO", False), draw.AMBER)
        draw.text(p, 618, 354, "BAIXO Q0.3", 7, True, w=80)
        # operador
        draw.card(p, QRectF(8, 120, 230, 168), "Operador")
        draw.text(p, 18, 156, "Tanque de 1 m² (1 L = 1 mm)", 7, False, draw.MUTED, w=210)
        draw.text(p, 18, 176, "Vazão máxima da válvula: 40 L/s", 7, False, draw.MUTED, w=210)
        draw.text(p, 18, 196, "Tempo morto 1 s, válvula τ = 2 s", 7, False, draw.MUTED, w=210)
        draw.text(p, 18, 224, f"Consumo: {self.demand_key.lower()}", 8, True, w=210)
        draw.push_button(p, QRectF(14, 300, 150, 30), f"Setpoint ▸ {self.setpoint}", False, draw.GREEN)
        for key, x in (("BAIXO", 14), ("MEDIO", 88), ("ALTO", 162)):
            draw.push_button(p, QRectF(x, 352, 70, 26), key.capitalize(), self.demand_key == key and not self.profile,
                             draw.BLUE)
        draw.text(p, 14, 342, "consumo", 7, True, draw.MUTED)
        draw.switch(p, QRectF(14, 386, 218, 26), "Perfil automático de consumo", self.profile)
        draw.switch(p, QRectF(14, 420, 218, 28), "AUTOMÁTICO I0.0", self.is_pressed("AUTO"))
