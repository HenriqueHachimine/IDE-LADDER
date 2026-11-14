"""Quadro de transferencia automatica rede/gerador: partida com tentativas, intertravamento e retorno."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

CRANK_RPM, RUN_RPM = 300.0, 1800.0
FIRE_MS = 2000                # o motor pega depois de 2 s de arranque (partida dificil: so na 2a tentativa)
RUNNING_RPM = 1200.0          # sensor de motor girando
VOLT_OK_MS = 3000             # tensao e frequencia estabilizam 3 s depois de girar
CONTACTOR_MS = 60             # contatores fecham/abrem em 60 ms
STARTER_HOT_MS = 7000
OUTAGE_LIMIT_MS = 20000
COOLDOWN_MS = 5000            # o motor precisa girar sem carga ao menos 5 s antes de parar
GLITCH_MS = 1000


class Contactor:
    def __init__(self) -> None:
        self.closed = False
        self._t = 0

    def step(self, coil: bool, dt_ms: int, stuck: bool = False) -> None:
        if stuck:
            self.closed = True
            return
        if coil == self.closed:
            self._t = 0
            return
        self._t += dt_ms
        if self._t >= CONTACTOR_MS:
            self.closed, self._t = coil, 0


@register
class TransferSwitchEnvironment(Environment):
    id = "gerador_qta"
    name = "Transferência rede/gerador (QTA)"
    description = ("Hospital alimentado pela rede (contator KR) ou por um gerador diesel (contator KG). Na falta da "
                   "rede (I0.0) por mais de alguns segundos, ligue o combustível e o motor de partida: o motor pega "
                   "em ~2 s; não deixe o arranque mais de 5 s seguidos, descanse e tente até 3 vezes (depois, "
                   "bloqueio até o REARME). Com a tensão do gerador estável (I0.2), transfira. KR e KG nunca podem "
                   "fechar juntos: confira os contatos auxiliares (I0.3, I0.4) e dê tempo morto. Quando a rede voltar "
                   "e ficar estável, retorne e deixe o motor resfriar sem carga antes de parar. Simule falta, piscada "
                   "da rede, partida difícil, falta de combustível e contator KR soldado.")
    example = "ambientes/gerador_qta.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("REDE", "I0.0", "Rede_OK", "Relé de monitoramento: rede presente e dentro da faixa"),
        IOPoint("GIRANDO", "I0.1", "Gerador_Girando", "Motor do gerador girando (acima de 1200 rpm)"),
        IOPoint("TENSAO", "I0.2", "Gerador_Tensao_OK", "Gerador com tensão e frequência estáveis"),
        IOPoint("KR_AUX", "I0.3", "KR_Fechado", "Contato auxiliar: KR fechado"),
        IOPoint("KG_AUX", "I0.4", "KG_Fechado", "Contato auxiliar: KG fechado"),
        IOPoint("COMB", "I0.5", "Combustivel_Baixo", "Boia: combustível baixo"),
        IOPoint("AUTO", "I0.6", "Automatico", "Chave AUTOMÁTICO", SWITCH),
        IOPoint("REARME", "I0.7", "Rearme", "Botão REARME (após falha de partida)", BUTTON),
    ]
    outputs = [
        IOPoint("ARRANQUE", "Q0.0", "Motor_Partida", "Motor de partida (arranque)"),
        IOPoint("COMBUSTIVEL", "Q0.1", "Solenoide_Combustivel", "Solenoide de combustível (motor funciona)"),
        IOPoint("KR", "Q0.2", "Contator_KR", "Contator da rede"),
        IOPoint("KG", "Q0.3", "Contator_KG", "Contator do gerador"),
        IOPoint("L_REDE", "Q0.4", "Lampada_Rede", "Lâmpada CARGA NA REDE"),
        IOPoint("L_GER", "Q0.5", "Lampada_Gerador", "Lâmpada CARGA NO GERADOR"),
        IOPoint("FALHA", "Q0.6", "Lampada_Falha", "Lâmpada FALHA"),
        IOPoint("BUZINA", "Q0.7", "Buzina", "Alarme sonoro"),
    ]

    def reset(self) -> None:
        self.mains_off = getattr(self, "mains_off", False)
        self.hard_start = getattr(self, "hard_start", False)
        self.no_fuel = getattr(self, "no_fuel", False)
        self.kr_stuck = getattr(self, "kr_stuck", False)
        self.glitch_ms = 0
        self.rpm = 0.0
        self.crank_ms = 0
        self.attempts = 0
        self.fired = False
        self.run_ms = 0
        self.kr, self.kg = Contactor(), Contactor()
        self.flags: dict[str, str] = {}
        self.outage_ms = 0
        self.max_outage_ms = 0
        self.outages = 0
        self.mains_ok_ms = 100000
        self.unloaded_ms = 0
        self.loaded_since_start = False
        self.fuel = 100.0
        self.angle = 0.0
        self.starts = 0
        self._was_crank = False
        self._powered = True

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    @property
    def mains(self) -> bool:
        return not self.mains_off and self.glitch_ms <= 0

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "FALTA":
            self.mains_off = not self.mains_off
        elif key == "PISCADA":
            self.glitch_ms = GLITCH_MS
        elif key == "DIFICIL":
            self.hard_start = not self.hard_start
        elif key == "SEM_COMB":
            self.no_fuel = not self.no_fuel
        elif key == "SOLDADO":
            self.kr_stuck = not self.kr_stuck

    def press(self, key: str, down: bool) -> None:
        if key in ("FALTA", "PISCADA", "DIFICIL", "SEM_COMB", "SOLDADO"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        self.glitch_ms = max(0, self.glitch_ms - dt_ms)
        mains = self.mains
        self.mains_ok_ms = self.mains_ok_ms + dt_ms if mains else 0
        # motor diesel
        crank = out["ARRANQUE"]
        fuel = out["COMBUSTIVEL"] and not self.no_fuel and self.fuel > 0
        if crank and not self._was_crank:
            self.attempts += 1
            self.crank_ms = 0
            if mains and self.mains_ok_ms < 4000:
                self._flag("glitch", "O gerador partiu por uma piscada da rede: filtre a falta (alguns segundos)")
        self._was_crank = crank
        if crank:
            self.crank_ms += dt_ms
            if self.crank_ms > STARTER_HOT_MS:
                self._flag("starter", "Motor de partida acionado mais de 7 s seguidos: superaqueceu")
            if self.rpm >= RUNNING_RPM and self.crank_ms > 300 and self.fired:
                self._flag("crank_run", "Motor de partida acionado com o motor já funcionando")
        need = FIRE_MS + (1000 if self.hard_start else 0)
        can_fire = fuel and (not self.hard_start or self.attempts >= 2)
        if crank and can_fire and self.crank_ms >= need:
            if not self.fired:
                self.starts += 1
            self.fired = True
        if not fuel:
            self.fired = False
        target = RUN_RPM if self.fired else (CRANK_RPM if crank else 0.0)
        self.rpm = approach(self.rpm, target, 900.0, 600.0, dt)
        self.angle += self.rpm / 60 * 2 * math.pi * dt * 0.05
        self.run_ms = self.run_ms + dt_ms if self.rpm >= RUNNING_RPM else 0
        if fuel and self.rpm > 100:
            self.fuel = max(0.0, self.fuel - 0.02 * dt)
        gen_ok = self.run_ms >= VOLT_OK_MS
        # contatores
        self.kr.step(out["KR"], dt_ms, self.kr_stuck)
        self.kg.step(out["KG"], dt_ms)
        if self.kr.closed and self.kg.closed:
            self._flag("parallel", "KR e KG fechados juntos: rede e gerador em paralelo (curto entre fontes)")
        if self.kg.closed and self.rpm > 100 and not gen_ok:
            self._flag("unstable", "Carga ligada ao gerador antes da tensão estabilizar (I0.2)")
        powered = (self.kr.closed and mains) or (self.kg.closed and gen_ok)
        if not powered:
            self.outage_ms += dt_ms
            self.max_outage_ms = max(self.max_outage_ms, self.outage_ms)
            limit = OUTAGE_LIMIT_MS + (12000 if self.hard_start else 0)    # partida dificil: uma tentativa a mais
            if self.outage_ms > limit and not (self.no_fuel or self.kr_stuck):
                self._flag("outage", "Hospital sem energia por mais de 20 s com o gerador disponível")
        else:
            if not self._powered:
                self.outages += 1
            self.outage_ms = 0
        self._powered = powered
        # retorno precoce: KR fechou com a rede de volta ha pouco tempo
        if out["KR"] and not self.kr.closed and mains and self.mains_ok_ms < 8000 and self.loaded_since_start:
            self._flag("early", "Voltou para a rede sem esperar ela ficar estável")
        # resfriamento: tempo girando sem carga antes de parar
        if self.kg.closed:
            self.loaded_since_start = True
            self.unloaded_ms = 0
        elif self.rpm >= RUNNING_RPM:
            self.unloaded_ms += dt_ms
        if self.loaded_since_start and self.fired is False and self.rpm < RUNNING_RPM and self.rpm > 1000:
            if self.unloaded_ms < COOLDOWN_MS:
                self._flag("cool", "Gerador parado logo depois de sair da carga: deixe resfriar sem carga")
            self.loaded_since_start = False

    def sensors(self) -> dict[str, bool]:
        return {"REDE": self.mains, "GIRANDO": self.rpm >= RUNNING_RPM, "TENSAO": self.run_ms >= VOLT_OK_MS,
                "KR_AUX": self.kr.closed, "KG_AUX": self.kg.closed, "COMB": self.fuel < 20.0}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        src = "rede" if (self.kr.closed and self.mains) else ("gerador" if self.kg.closed else "SEM ENERGIA")
        return [f"Hospital: {src} | motor {self.rpm:.0f} rpm | tentativas de partida: {self.attempts}",
                f"Maior falta de energia: {self.max_outage_ms / 1000:.1f} s | quedas: {self.outages} | combustível "
                f"{self.fuel:.0f}%"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"AUTO": (14, 410, 120, 28), "REARME": (140, 410, 120, 28), "FALTA": (276, 370, 140, 26),
                "PISCADA": (276, 402, 140, 26), "DIFICIL": (424, 370, 140, 26), "SEM_COMB": (424, 402, 140, 26),
                "SOLDADO": (572, 370, 140, 26)}

    def _contactor(self, p: QPainter, x: float, y: float, name: str, c: Contactor, coil: bool, stuck: bool) -> None:
        r = QRectF(x - 34, y - 26, 68, 52)
        draw.shadow(p, r, 6, 3)
        p.setPen(QPen(QColor("#334155"), 1.2))
        p.setBrush(QColor("#fef2f2") if stuck else (QColor("#ecfdf5") if coil else QColor("#f8fafc")))
        p.drawRoundedRect(r, 6, 6)
        draw.text(p, x - 28, y - 16, name, 9, True, w=40)
        for k in range(3):
            cx = x - 14 + k * 14
            p.setPen(QPen(draw.GREEN if c.closed else QColor("#475569"), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, y - 4), QPointF(cx, y + 16) if c.closed else QPointF(cx + 7, y + 13))
        if stuck:
            draw.text(p, x - 30, y + 34, "SOLDADO", 7, True, draw.RED, w=70)

    def _wire(self, p: QPainter, pts: list[QPointF], live: bool) -> None:
        p.setPen(QPen(QColor("#ea580c") if live else QColor("#94a3b8"), 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out = self.out
        sens = self.sensors()
        gen_ok = sens["TENSAO"]
        mains = self.mains
        # rede (transformador)
        tc = QPointF(120, 70)
        p.setPen(QPen(QColor("#334155"), 2))
        p.setBrush(QColor("#e2e8f0"))
        p.drawEllipse(tc + QPointF(-10, 0), 20, 20)
        p.drawEllipse(tc + QPointF(10, 0), 20, 20)
        draw.text(p, 60, 30, "REDE 13,8 kV / 380 V", 7.5, True, draw.MUTED, w=160)
        draw.tag(p, 160, 70, "I0.0 rede", mains)
        if not mains:
            draw.plate(p, QRectF(136, 98, 80, 18), "SEM REDE", "#b91c1c")
        self._wire(p, [QPointF(120, 90), QPointF(120, 140)], mains)
        self._contactor(p, 120, 166, "KR", self.kr, out.get("KR", False), self.kr_stuck)
        draw.tag(p, 160, 150, "Q0.2", out.get("KR", False))
        draw.tag(p, 160, 182, "I0.3", sens["KR_AUX"])
        # gerador
        gx = 560
        eng = QRectF(gx - 90, 40, 140, 64)
        draw.shadow(p, eng, 8, 4)
        draw.metal(p, eng, "#ca8a04" if self.rpm > 100 else "#a16207", 8)
        draw.ctext(p, eng.center().x() - 20, eng.top() + 14, "DIESEL", 8, True, draw.WHITE, 80)
        draw.motor(p, QPointF(gx + 30, 72), 16, self.rpm > 100, self.angle, "G")
        if self.rpm > 1000:
            for k in range(3):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(100, 116, 139, 90 - k * 25))
                p.drawEllipse(QPointF(eng.left() + 20 + k * 8, eng.top() - 10 - k * 10 - (self.time_ms / 50) % 10),
                              6 + k * 3, 5 + k * 2)
        draw.gauge(p, QPointF(gx - 140, 72), 34, self.rpm, 0, 2000, "rpm", "", [(1700, 1900, "#86efac")])
        draw.tag(p, gx - 90, 116, "I0.1 girando", sens["GIRANDO"])
        draw.tag(p, gx + 4, 116, "I0.2 tensão", gen_ok)
        self._wire(p, [QPointF(gx, 104), QPointF(gx, 140)], gen_ok)
        self._contactor(p, gx, 166, "KG", self.kg, out.get("KG", False), False)
        draw.tag(p, gx + 40, 150, "Q0.3", out.get("KG", False))
        draw.tag(p, gx + 40, 182, "I0.4", sens["KG_AUX"])
        # barramento e carga
        bus_live = (self.kr.closed and mains) or (self.kg.closed and gen_ok)
        self._wire(p, [QPointF(120, 192), QPointF(120, 230), QPointF(gx, 230), QPointF(gx, 192)], bus_live)
        self._wire(p, [QPointF(340, 230), QPointF(340, 260)], bus_live)
        hosp = QRectF(270, 260, 140, 90)
        draw.shadow(p, hosp, 6, 4)
        draw.metal(p, hosp, "#e2e8f0", 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#dc2626"))
        p.drawRect(QRectF(hosp.center().x() - 5, hosp.top() + 10, 10, 26))
        p.drawRect(QRectF(hosp.center().x() - 13, hosp.top() + 18, 26, 10))
        for k in range(4):
            win = QRectF(hosp.left() + 12 + k * 32, hosp.top() + 50, 22, 26)
            p.setBrush(QColor("#fde68a") if bus_live else QColor("#334155"))
            p.drawRect(win)
        draw.text(p, hosp.left(), hosp.bottom() + 12, "HOSPITAL", 8, True, draw.INK, w=140)
        # motor de partida e combustivel
        draw.card(p, QRectF(430, 236, 282, 120), "Motor diesel")
        draw.tag(p, 440, 266, "Q0.0 arranque", out.get("ARRANQUE", False))
        draw.tag(p, 552, 266, "Q0.1 combustível", out.get("COMBUSTIVEL", False))
        draw.text(p, 440, 292, f"Tentativas de partida: {self.attempts}", 8, True, w=260)
        draw.text(p, 440, 312, f"Arranque contínuo: {self.crank_ms / 1000 if out.get('ARRANQUE') else 0:.1f} s", 7.5,
                  False, draw.MUTED, w=260)
        draw.bar(p, QRectF(440, 330, 160, 9), self.fuel / 100, draw.AMBER if self.fuel > 20 else draw.RED)
        draw.tag(p, 608, 334, "I0.5 baixo", sens["COMB"])
        # painel
        draw.card(p, QRectF(8, 236, 250, 160), "Painel do QTA")
        lamps = (("REDE Q0.4", "L_REDE", draw.GREEN), ("GERADOR Q0.5", "L_GER", draw.AMBER),
                 ("FALHA Q0.6", "FALHA", draw.RED), ("BUZINA Q0.7", "BUZINA", draw.RED))
        for k, (label, key, col) in enumerate(lamps):
            draw.lamp(p, QPointF(28, 270 + k * 28), 8, out.get(key, False), col)
            draw.text(p, 42, 270 + k * 28, label, 7.5, True, w=110)
        outage = self.outage_ms / 1000
        draw.lcd(p, QRectF(150, 262, 100, 34), f"{outage:4.1f} s", "#f87171" if outage > 0 else "#4ade80",
                 "sem energia")
        draw.text(p, 150, 312, f"maior: {self.max_outage_ms / 1000:.1f} s", 7, False, draw.MUTED, w=100)
        draw.switch(p, QRectF(14, 410, 120, 28), "AUTO I0.6", self.is_pressed("AUTO"))
        draw.push_button(p, QRectF(140, 410, 120, 28), "REARME I0.7", self.is_pressed("REARME"), draw.AMBER)
        # simulacao
        draw.switch(p, QRectF(276, 370, 140, 26), "Falta de rede", self.mains_off)
        draw.push_button(p, QRectF(276, 402, 140, 26), "Piscada (1 s)", self.glitch_ms > 0, draw.AMBER)
        draw.switch(p, QRectF(424, 370, 140, 26), "Partida difícil", self.hard_start)
        draw.switch(p, QRectF(424, 402, 140, 26), "Sem combustível", self.no_fuel)
        draw.switch(p, QRectF(572, 370, 140, 26), "KR soldado", self.kr_stuck)
