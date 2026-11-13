"""Partida estrela-triangulo de motor de inducao: intertravamento e tempo morto na comutacao."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, SENSOR, Environment, IOPoint
from ..registry import register

CLOSE_MS, OPEN_MS = 30, 40          # contatores: fecham em 30 ms e abrem em 40 ms (arco eletrico)
TAU_STAR, TAU_DELTA, TAU_COAST = 1.6, 0.6, 3.0   # constantes de tempo da velocidade (s)
W_STAR, W_DELTA = 0.90, 0.98        # velocidade final em estrela (conjugado 1/3) e em triangulo
LOAD_PU, OVERLOAD_PU = 0.85, 1.35   # corrente de regime em triangulo (pu da nominal)
PEAK_LIMIT = 3.5                    # pico aceitavel na passagem para triangulo (pu)
STAR_MAX_MS = 15000                 # estrela por mais tempo aquece o motor
THERMAL_TRIP = 4.0                  # integral de (I^2 - 1,1^2) que desarma o rele termico
NOMINAL_A = 10.0                    # corrente nominal do motor (A), so para exibir


class Contactor:
    """Contator com atraso mecanico: o contato segue a bobina depois de CLOSE_MS/OPEN_MS."""

    def __init__(self) -> None:
        self.closed = False
        self._t = 0

    def step(self, coil: bool, dt_ms: int) -> None:
        if coil == self.closed:
            self._t = 0
            return
        self._t += dt_ms
        if self._t >= (CLOSE_MS if coil else OPEN_MS):
            self.closed, self._t = coil, 0


@register
class StarDeltaEnvironment(Environment):
    id = "estrela_triangulo"
    name = "Partida estrela-triângulo"
    description = ("Motor de 10 A partindo em estrela (K1 + K2, corrente e conjugado a 1/3) e passando para "
                   "triângulo (K1 + K3). Os contatores fecham em 30 ms e abrem em 40 ms: trocar K2 por K3 na mesma "
                   "varredura fecha os dois juntos (curto-circuito). Passar para triângulo com o motor lento gera "
                   "pico de corrente. 'Sobrecarga' aumenta a carga até o relé térmico (NF) desarmar.")
    example = "ambientes/estrela_triangulo.ladproj"
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Botão LIGA (NA)", BUTTON),
        IOPoint("DESLIGA", "I0.1", "Desliga", "Botão DESLIGA (NF: lê 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("TERMICO", "I0.2", "Rele_Termico", "Relé térmico (NF: lê 0 quando desarma)", SENSOR,
                normally_closed=True),
        IOPoint("ROTACAO", "I0.3", "Rotacao_Nominal", "Sensor de rotação: motor acima de 85% da velocidade"),
    ]
    outputs = [
        IOPoint("K1", "Q0.0", "Contator_K1", "K1: contator de linha (rede)"),
        IOPoint("K2", "Q0.1", "Contator_K2_Estrela", "K2: fecha o centro da estrela"),
        IOPoint("K3", "Q0.2", "Contator_K3_Triangulo", "K3: liga o motor em triângulo"),
        IOPoint("LIGADO", "Q0.3", "Lampada_Ligado", "Lâmpada MOTOR LIGADO (triângulo)"),
        IOPoint("FALHA", "Q0.4", "Lampada_Falha", "Lâmpada FALHA (relé térmico desarmado)"),
    ]

    def reset(self) -> None:
        self.k = {name: Contactor() for name in ("K1", "K2", "K3")}
        self.w = 0.0                     # velocidade (pu da sincrona)
        self.angle = 0.0
        self.current = 0.0               # pu da nominal
        self.overload = getattr(self, "overload", False)
        self.heat = 0.0
        self.tripped = False
        self.breaker_open = False        # disjuntor abriu por curto-circuito
        self.shorts = 0
        self.bad_transitions = 0
        self.last_peak = 0.0
        self.bad_peak = 0.0
        self.star_ms = 0
        self.max_star_ms = 0
        self.running_tripped_ms = 0
        self.starts = 0
        self._was_delta = False

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "SOBRECARGA":
            self.overload = not self.overload
        elif key == "REARMAR" and self.heat <= 1.0:
            self.tripped = False
            self.breaker_open = False

    def press(self, key: str, down: bool) -> None:
        if key in ("SOBRECARGA", "REARMAR"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    @property
    def connection(self) -> str:
        k1, k2, k3 = (self.k[n].closed for n in ("K1", "K2", "K3"))
        if self.breaker_open or not k1:
            return "desligado"
        if k2 and k3:
            return "curto"
        return "estrela" if k2 else ("triangulo" if k3 else "desligado")

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for name in ("K1", "K2", "K3"):
            self.k[name].step(out[name], dt_ms)
        conn = self.connection
        if conn == "curto":                       # fase-fase pela estrela e pelo triangulo
            self.shorts += 1
            self.breaker_open = True
            conn = "desligado"
        load = OVERLOAD_PU if self.overload else LOAD_PU
        i_dol = 6.0 * max(0.0, 1.0 - self.w / W_DELTA) + load * min(1.0, self.w / W_DELTA)
        if conn == "estrela":
            target, tau, self.current = W_STAR - (0.04 if self.overload else 0.0), TAU_STAR, i_dol / 3
            self.star_ms += dt_ms
            self.max_star_ms = max(self.max_star_ms, self.star_ms)
        elif conn == "triangulo":
            target, tau, self.current = W_DELTA - (0.03 if self.overload else 0.0), TAU_DELTA, i_dol
            if not self._was_delta:
                self.last_peak = i_dol
                if i_dol > PEAK_LIMIT:
                    self.bad_transitions += 1
                    self.bad_peak = self.bad_peak or i_dol
                elif self.w >= 0.5:
                    self.starts += 1
        else:
            target, tau, self.current = 0.0, TAU_COAST, 0.0
        if conn != "estrela":
            self.star_ms = 0
        self._was_delta = conn == "triangulo"
        self.w += (target - self.w) * min(1.0, dt / tau)
        self.angle += self.w * 25 * dt
        # rele termico: integra o excesso de corrente e esfria devagar
        self.heat = max(0.0, self.heat + (self.current ** 2 - 1.1 ** 2) * dt if self.current > 1.1
                        else self.heat - 0.4 * dt)
        if self.heat >= THERMAL_TRIP:
            self.tripped = True
        energized = self.k["K1"].closed and (self.k["K2"].closed or self.k["K3"].closed)
        self.running_tripped_ms = self.running_tripped_ms + dt_ms if (self.tripped and energized) else 0

    def sensors(self) -> dict[str, bool]:
        return {"TERMICO": self.tripped, "ROTACAO": self.w >= 0.85}

    def alarms(self) -> list[str]:
        out = []
        if self.shorts:
            out.append("CURTO-CIRCUITO: K2 (estrela) e K3 (triângulo) fecharam juntos e o disjuntor abriu. "
                       "Intertrave K2/K3 e espere o K2 abrir (tempo morto) antes de ligar o K3")
        if self.bad_transitions:
            out.append(f"Transição para triângulo cedo demais: pico de {self.bad_peak:.1f}x a corrente nominal "
                       "(espere o motor acelerar em estrela)")
        if self.max_star_ms > STAR_MAX_MS:
            out.append("Motor ficou mais de 15 s em estrela: com conjugado reduzido ele aquece")
        if self.running_tripped_ms > 500:
            out.append("Motor continua energizado com o relé térmico desarmado")
        return out

    def stats(self) -> list[str]:
        name = {"estrela": "ESTRELA", "triangulo": "TRIÂNGULO", "desligado": "desligado"}[self.connection
                                                                                       if self.connection != "curto"
                                                                                       else "desligado"]
        return [f"Ligação: {name} | velocidade {self.w * 100:.0f}% | corrente {self.current * NOMINAL_A:.1f} A",
                f"Partidas completas: {self.starts} | último pico na troca: {self.last_peak:.1f}x In"
                + (" | DISJUNTOR ABERTO (Rearmar)" if self.breaker_open else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (24, 300, 130, 28), "DESLIGA": (24, 336, 130, 28), "SOBRECARGA": (470, 336, 150, 28),
                "REARMAR": (470, 372, 150, 28)}

    def _contactor(self, p: QPainter, x: float, y: float, name: str, label: str, addr: str) -> None:
        c = self.k[name]
        coil = self.out.get(name, False)
        r = QRectF(x, y, 92, 70)
        p.setPen(QPen(QColor("#334155"), 1.2))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(r, 6, 6)
        draw.text(p, x + 8, y + 12, name, 9, True)
        draw.text(p, x + 34, y + 12, label, 7, False, draw.MUTED, w=60)
        for k in range(3):                       # tres polos
            cx = x + 20 + k * 26
            p.setPen(QPen(draw.GREEN if c.closed else QColor("#475569"), 3))
            if c.closed:
                p.drawLine(QPointF(cx, y + 26), QPointF(cx, y + 50))
            else:
                p.drawLine(QPointF(cx, y + 26), QPointF(cx + 9, y + 46))
        draw.tag(p, x, y + 82, f"{addr} bobina", coil)

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f8fafc"))
        draw.text(p, 20, 18, "Rede trifásica 380 V", 8, True, draw.MUTED)
        p.setPen(QPen(QColor("#1e293b"), 2))
        for k, col in enumerate(("#a16207", "#111827", "#64748b")):    # fases L1 L2 L3
            p.setPen(QPen(QColor(col), 3))
            p.drawLine(QPointF(20, 36 + k * 8), QPointF(620, 36 + k * 8))
        self._contactor(p, 60, 80, "K1", "linha", "Q0.0")
        self._contactor(p, 200, 80, "K2", "estrela", "Q0.1")
        self._contactor(p, 340, 80, "K3", "triângulo", "Q0.2")
        if self.breaker_open:
            draw.text(p, 200, 200, "DISJUNTOR ABERTO (curto-circuito)", 9, True, draw.RED, w=300)
        # motor e ventilador
        mc = QPointF(540, 140)
        conn = self.connection
        draw.motor(p, mc, 34, conn in ("estrela", "triangulo"), self.angle, "M 3~")
        draw.text(p, mc.x(), mc.y() + 50, {"estrela": "Y estrela", "triangulo": "Δ triângulo"}.get(conn, "parado"),
                  9, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 120)
        # amperimetro
        center = QPointF(130, 232)
        p.setPen(QPen(QColor("#334155"), 1.5))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(center, 52, 52)
        for k in range(0, 61, 10):
            a = math.radians(210 - k * 4)
            p.drawLine(QPointF(center.x() + math.cos(a) * 44, center.y() - math.sin(a) * 44),
                       QPointF(center.x() + math.cos(a) * 50, center.y() - math.sin(a) * 50))
        amps = min(60.0, self.current * NOMINAL_A)
        a = math.radians(210 - amps * 4)
        p.setPen(QPen(draw.RED, 2.5))
        p.drawLine(center, QPointF(center.x() + math.cos(a) * 42, center.y() - math.sin(a) * 42))
        draw.text(p, center.x(), center.y() + 22, f"{amps:.1f} A", 8, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 80)
        # barra de velocidade
        bar = QRectF(250, 222, 180, 18)
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRect(bar)
        p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * min(1.0, self.w), bar.height()),
                   draw.GREEN if self.w >= 0.85 else draw.AMBER)
        draw.text(p, bar.left(), bar.top() - 10, f"Velocidade {self.w * 100:.0f}%", 8, True)
        sens = self.sensors()
        draw.tag(p, bar.left(), bar.bottom() + 14, "I0.3 rotação nominal", sens["ROTACAO"])
        draw.tag(p, bar.left(), bar.bottom() + 36, "I0.2 relé térmico " + ("DESARMADO" if self.tripped else "ok"),
                 not self.tripped)
        # painel
        draw.lamp(p, QPointF(470, 270), 10, self.out.get("LIGADO", False), draw.GREEN)
        draw.text(p, 486, 270, "LIGADO  Q0.3", 8, True)
        draw.lamp(p, QPointF(470, 300), 10, self.out.get("FALHA", False), draw.RED)
        draw.text(p, 486, 300, "FALHA  Q0.4", 8, True)
        draw.push_button(p, QRectF(24, 300, 130, 28), "LIGA  I0.0", self.is_pressed("LIGA"), draw.GREEN)
        draw.push_button(p, QRectF(24, 336, 130, 28), "DESLIGA  I0.1 (NF)", self.is_pressed("DESLIGA"), draw.RED)
        draw.switch(p, QRectF(470, 336, 150, 28), "Sobrecarga", self.overload)
        draw.push_button(p, QRectF(470, 372, 150, 28), "Rearmar térmico", False, draw.AMBER)
