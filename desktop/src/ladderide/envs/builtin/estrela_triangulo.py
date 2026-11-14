"""Partida estrela-triangulo reversivel: intertravamentos, tempos mortos, espera de motor parado e protecoes."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from .. import draw
from ..base import BUTTON, SENSOR, Environment, IOPoint
from ..physics import History
from ..registry import register

CLOSE_MS, OPEN_MS = 30, 40          # contatores: fecham em 30 ms e abrem em 40 ms (arco eletrico)
TAU_STAR, TAU_DELTA, TAU_COAST = 1.6, 0.6, 2.2   # constantes de tempo da velocidade (s)
W_STAR, W_DELTA = 0.90, 0.98        # velocidade final em estrela (conjugado 1/3) e em triangulo
LOAD_PU, OVERLOAD_PU = 0.85, 1.35   # corrente de regime em triangulo (pu da nominal)
PEAK_LIMIT = 3.5                    # pico aceitavel na passagem para triangulo (pu)
STAR_MAX_MS = 15000                 # estrela por mais tempo aquece o motor
THERMAL_TRIP = 4.0                  # integral de (I^2 - 1,1^2) que desarma o rele termico
NOMINAL_A = 10.0                    # corrente nominal do motor (A), so para exibir
STOPPED = 0.03                      # sensor de motor parado: abaixo de 3% da velocidade


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
    name = "Partida estrela-triângulo reversível"
    description = ("Motor de 10 A com partida estrela-triângulo nos dois sentidos: K1 (horário) ou K4 (anti-horário, "
                   "fases invertidas) alimenta a linha, K2 fecha a estrela e K3 o triângulo. Os contatores fecham em "
                   "30 ms e abrem em 40 ms: K1/K4 e K2/K3 precisam de intertravamento e tempo morto. Reverter com o "
                   "motor girando gera contracorrente (7x In): espere o sensor de motor parado. Relé térmico e relé "
                   "de falta de fase são NF. Injete sobrecarga ou falta de fase pelos controles.")
    example = "ambientes/estrela_triangulo.ladproj"
    size = (720, 470)
    inputs = [
        IOPoint("LIGA_H", "I0.0", "Liga_Horario", "Botão LIGA sentido horário (NA)", BUTTON),
        IOPoint("LIGA_A", "I0.1", "Liga_Anti_Horario", "Botão LIGA sentido anti-horário (NA)", BUTTON),
        IOPoint("DESLIGA", "I0.2", "Desliga", "Botão DESLIGA (NF: lê 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("TERMICO", "I0.3", "Rele_Termico", "Relé térmico F1 (NF: lê 0 quando desarma)", SENSOR,
                normally_closed=True),
        IOPoint("FASE", "I0.4", "Rele_Falta_Fase", "Relé de falta de fase (NF: lê 0 sem uma fase)", SENSOR,
                normally_closed=True),
        IOPoint("ROTACAO", "I0.5", "Rotacao_Nominal", "Sensor de rotação: acima de 85% da velocidade"),
        IOPoint("PARADO", "I0.6", "Motor_Parado", "Sensor de motor parado: abaixo de 3% da velocidade"),
    ]
    outputs = [
        IOPoint("K1", "Q0.0", "K1_Horario", "K1: contator de linha, sentido horário"),
        IOPoint("K4", "Q0.1", "K4_Anti_Horario", "K4: contator de linha com duas fases trocadas"),
        IOPoint("K2", "Q0.2", "K2_Estrela", "K2: fecha o centro da estrela"),
        IOPoint("K3", "Q0.3", "K3_Triangulo", "K3: liga o motor em triângulo"),
        IOPoint("LIGADO", "Q0.4", "Lampada_Ligado", "Lâmpada MOTOR LIGADO (triângulo)"),
        IOPoint("FALHA", "Q0.5", "Lampada_Falha", "Lâmpada FALHA (térmico ou falta de fase)"),
    ]

    def reset(self) -> None:
        self.k = {name: Contactor() for name in ("K1", "K4", "K2", "K3")}
        self.w = 0.0                     # velocidade (pu da sincrona, com sinal: + horario)
        self.angle = 0.0
        self.current = 0.0               # pu da nominal
        self.overload = getattr(self, "overload", False)
        self.phase_lost = getattr(self, "phase_lost", False)
        self.heat = 0.0
        self.tripped = False
        self.breaker_open = False        # disjuntor Q1 abriu por curto-circuito
        self.shorts_star = 0             # K2 + K3
        self.shorts_line = 0             # K1 + K4
        self.bad_transitions = 0
        self.last_peak = 0.0
        self.bad_peak = 0.0
        self.star_ms = 0
        self.max_star_ms = 0
        self.running_tripped_ms = 0
        self.phase_energized_ms = 0
        self.unsignalled_ms = 0
        self.plugging = 0                # reversoes com o motor girando
        self._plug = False
        self.starts = {1: 0, -1: 0}
        self._was_delta = False
        self.trend = History(120, 250, 2)
        self.flow = 0.0

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "SOBRECARGA":
            self.overload = not self.overload
        elif key == "FALTA_FASE":
            self.phase_lost = not self.phase_lost
        elif key == "REARMAR" and self.heat <= 1.0:
            self.tripped = False
            self.breaker_open = False

    def press(self, key: str, down: bool) -> None:
        if key in ("SOBRECARGA", "FALTA_FASE", "REARMAR"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    # ------------------------------------------------------------ fisica
    @property
    def direction(self) -> int:
        k1, k4 = self.k["K1"].closed, self.k["K4"].closed
        if self.breaker_open or k1 == k4:
            return 0
        return 1 if k1 else -1

    @property
    def connection(self) -> str:
        if self.direction == 0:
            return "desligado"
        k2, k3 = self.k["K2"].closed, self.k["K3"].closed
        if k2 and k3:
            return "curto"
        return "estrela" if k2 else ("triangulo" if k3 else "aberto")

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for name in self.k:
            self.k[name].step(out[name], dt_ms)
        if not self.breaker_open and self.k["K1"].closed and self.k["K4"].closed:
            self.shorts_line += 1                  # duas fases em curto pelos contatores de linha
            self.breaker_open = True
        conn = self.connection
        if conn == "curto":                        # fase-fase pela estrela e pelo triangulo
            self.shorts_star += 1
            self.breaker_open = True
            conn = "desligado"
        d = self.direction
        rel = self.w * d                           # velocidade no sentido do campo girante
        load = OVERLOAD_PU if self.overload else LOAD_PU
        if rel >= 0:
            r = min(rel, W_DELTA)
            i_dol = 6.0 * (1.0 - r / W_DELTA) + load * r / W_DELTA
        else:
            i_dol = 6.0 + 2.0 * (-rel)             # contracorrente: frenagem por inversao de fases
        energized = conn in ("estrela", "triangulo")
        if energized and rel < -0.15:
            if not self._plug:
                self.plugging += 1
            self._plug = True
        else:
            self._plug = False
        phase_factor = 1.7 if self.phase_lost else 1.0
        if conn == "estrela":
            w_end = W_STAR - (0.04 if self.overload else 0.0)
            if self.phase_lost and abs(self.w) < 0.3:
                w_end = 0.0                        # monofasico nao parte
            target, tau, self.current = d * w_end, TAU_STAR, i_dol / 3 * phase_factor
            self.star_ms += dt_ms
            self.max_star_ms = max(self.max_star_ms, self.star_ms)
        elif conn == "triangulo":
            w_end = W_DELTA - (0.03 if self.overload else 0.0) - (0.2 if self.phase_lost else 0.0)
            target, tau, self.current = d * w_end, TAU_DELTA, i_dol * phase_factor
            if not self._was_delta:
                self.last_peak = i_dol
                if i_dol > PEAK_LIMIT:
                    self.bad_transitions += 1
                    self.bad_peak = self.bad_peak or i_dol
                elif rel >= 0.5:
                    self.starts[d] += 1
        else:
            target, tau, self.current = 0.0, TAU_COAST, 0.0
        if conn != "estrela":
            self.star_ms = 0
        self._was_delta = conn == "triangulo"
        self.w += (target - self.w) * min(1.0, dt / tau)
        self.angle += self.w * 25 * dt
        self.flow += 40 * dt if energized else 0.0
        # rele termico: integra o excesso de corrente e esfria devagar
        self.heat = max(0.0, self.heat + (self.current ** 2 - 1.1 ** 2) * dt if self.current > 1.1
                        else self.heat - 0.4 * dt)
        if self.heat >= THERMAL_TRIP:
            self.tripped = True
        line = self.k["K1"].closed or self.k["K4"].closed
        coils = line and (self.k["K2"].closed or self.k["K3"].closed)
        self.running_tripped_ms = self.running_tripped_ms + dt_ms if (self.tripped and coils) else 0
        self.phase_energized_ms = self.phase_energized_ms + dt_ms if (self.phase_lost and coils) else 0
        fault = self.tripped or self.phase_lost
        self.unsignalled_ms = self.unsignalled_ms + dt_ms if (fault and not out["FALHA"]) else 0
        self.trend.add(dt_ms, self.current * NOMINAL_A, self.w * 100)

    def sensors(self) -> dict[str, bool]:
        return {"TERMICO": self.tripped, "FASE": self.phase_lost, "ROTACAO": abs(self.w) >= 0.85,
                "PARADO": abs(self.w) < STOPPED}

    def alarms(self) -> list[str]:
        out = []
        if self.shorts_line:
            out.append("CURTO-CIRCUITO: K1 e K4 fecharam juntos (duas fases trocadas) e o disjuntor abriu. "
                       "Intertrave K1/K4 e dê um tempo morto entre abrir um e fechar o outro")
        if self.shorts_star:
            out.append("CURTO-CIRCUITO: K2 (estrela) e K3 (triângulo) fecharam juntos e o disjuntor abriu. "
                       "Intertrave K2/K3 e espere o K2 abrir (tempo morto) antes de ligar o K3")
        if self.plugging:
            out.append("Reversão com o motor girando: contracorrente de mais de 6x In e esforço no eixo. "
                       "Espere o sensor de motor parado (I0.6) antes de ligar o outro sentido")
        if self.bad_transitions:
            out.append(f"Transição para triângulo cedo demais: pico de {self.bad_peak:.1f}x a corrente nominal "
                       "(espere o motor acelerar em estrela)")
        if self.max_star_ms > STAR_MAX_MS:
            out.append("Motor ficou mais de 15 s em estrela: com conjugado reduzido ele aquece")
        if self.running_tripped_ms > 500:
            out.append("Motor continua energizado com o relé térmico desarmado")
        if self.phase_energized_ms > 1000:
            out.append("Motor energizado com falta de fase: ele perde conjugado e aquece. Desligue pelo relé I0.4")
        if self.unsignalled_ms > 1000:
            out.append("Falha (térmico ou falta de fase) sem a lâmpada FALHA acesa")
        return out

    def stats(self) -> list[str]:
        conn = self.connection
        name = {"estrela": "ESTRELA", "triangulo": "TRIÂNGULO"}.get(conn, "desligado")
        sent = {1: " horário", -1: " anti-horário"}.get(self.direction, "") if name != "desligado" else ""
        return [f"Ligação: {name}{sent} | velocidade {self.w * 100:+.0f}% | corrente {self.current * NOMINAL_A:.1f} A",
                f"Partidas: {self.starts[1]} horário, {self.starts[-1]} anti-horário | último pico "
                f"{self.last_peak:.1f}x In" + (" | DISJUNTOR ABERTO (Rearmar)" if self.breaker_open else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA_H": (462, 316, 120, 28), "LIGA_A": (588, 316, 120, 28), "DESLIGA": (462, 350, 120, 28),
                "SOBRECARGA": (20, 432, 132, 28), "FALTA_FASE": (160, 432, 132, 28), "REARMAR": (300, 432, 132, 28)}

    def _wire(self, p: QPainter, pts: list[QPointF], live: bool, flowing: bool) -> None:
        path = QPainterPath(pts[0])
        for q in pts[1:]:
            path.lineTo(q)
        p.setBrush(Qt.NoBrush)
        if live:
            p.setPen(QPen(QColor(234, 88, 12, 60), 9, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(path)
        p.setPen(QPen(QColor("#ea580c") if live else QColor("#94a3b8"), 3.2, Qt.SolidLine, Qt.RoundCap,
                      Qt.RoundJoin))
        p.drawPath(path)
        if flowing:
            pen = QPen(QColor("#fde68a"), 1.6, Qt.CustomDashLine, Qt.FlatCap)
            pen.setDashPattern([2, 4])
            pen.setDashOffset(-self.flow / 1.6)
            p.setPen(pen)
            p.drawPath(path)

    def _contactor(self, p: QPainter, x: float, y: float, name: str, label: str, addr: str) -> None:
        c = self.k[name]
        coil = self.out.get(name, False)
        r = QRectF(x, y, 84, 62)
        draw.shadow(p, r, 6, 3)
        p.setPen(QPen(QColor("#334155"), 1.2))
        p.setBrush(QColor("#f8fafc") if not coil else QColor("#ecfdf5"))
        p.drawRoundedRect(r, 6, 6)
        draw.text(p, x + 7, y + 11, name, 9, True)
        draw.text(p, x + 30, y + 11, label, 7, True, draw.MUTED, w=54)
        for k in range(3):                       # tres polos
            cx = x + 14 + k * 19
            p.setPen(QPen(QColor("#475569"), 1.2))
            p.drawLine(QPointF(cx, y + 22), QPointF(cx, y + 26))
            p.drawLine(QPointF(cx, y + 46), QPointF(cx, y + 50))
            p.setPen(QPen(draw.GREEN if c.closed else QColor("#475569"), 3, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(cx, y + 26), QPointF(cx, y + 46) if c.closed else QPointF(cx + 8, y + 43))
        # bobina (A1-A2)
        coil_r = QRectF(x + 68, y + 27, 10, 16)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(draw.GREEN if coil else QColor("#cbd5e1"))
        p.drawRect(coil_r)
        draw.tag(p, x, y + 74, addr, coil)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 470)
        sens = self.sensors()
        live_bus = not self.breaker_open
        d = self.direction
        conn = self.connection
        flowing = conn in ("estrela", "triangulo")
        # ---- barramento trifasico e disjuntor
        draw.text(p, 20, 14, "REDE 3~ 380 V 60 Hz", 7.5, True, draw.MUTED)
        for k, col in enumerate(("#a16207", "#111827", "#64748b")):
            p.setPen(QPen(QColor(col), 3))
            p.drawLine(QPointF(20, 28 + k * 6), QPointF(70, 28 + k * 6))
            p.setPen(QPen(QColor(col) if live_bus else QColor("#cbd5e1"), 3))
            p.drawLine(QPointF(110, 28 + k * 6), QPointF(430, 28 + k * 6))
        q1 = QRectF(72, 20, 36, 30)
        draw.metal(p, q1, "#334155" if live_bus else "#7f1d1d", 4)
        p.setPen(QPen(QColor("#f8fafc"), 2.5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(90, 42), QPointF(90, 28) if live_bus else QPointF(98, 36))
        draw.text(p, 72, 60, "Q1", 7.5, True, draw.INK, w=40)
        # rele de falta de fase sobre o barramento
        rff = QRectF(118, 50, 74, 22)
        draw.metal(p, rff, "#7c2d12" if self.phase_lost else "#1e3a8a", 4)
        draw.text(p, 124, 61, "RFF  " + ("FALTA" if self.phase_lost else "3 fases"), 7, True, draw.WHITE, w=70)
        draw.tag(p, 196, 61, "I0.4", not self.phase_lost)
        bus_x = {"K1": 190, "K4": 300, "K3": 410}
        # ---- contatores de linha e triangulo
        for name, label, addr in (("K1", "horário", "Q0.0"), ("K4", "anti-hor.", "Q0.1"), ("K3", "triângulo", "Q0.3")):
            x = bus_x[name]
            self._wire(p, [QPointF(x, 40), QPointF(x, 96)], live_bus, flowing and self.k[name].closed)
            self._contactor(p, x - 42, 96, name, label, addr)
        # saidas de K1/K4 juntam no borne U1 V1 W1 do motor
        m = QPointF(245, 266)
        u1 = QPointF(m.x(), m.y() - 52)
        line_live = live_bus and (self.k["K1"].closed or self.k["K4"].closed)
        self._wire(p, [QPointF(190, 158), QPointF(190, 186), QPointF(300, 186), QPointF(300, 158)],
                   line_live, flowing)
        self._wire(p, [QPointF(245, 186), u1], line_live, flowing)
        # rele termico F1 no caminho da linha
        f1 = QRectF(225, 194, 40, 16)
        draw.metal(p, f1, "#b91c1c" if self.tripped else "#475569", 3)
        draw.text(p, 229, 202, "F1", 7, True, draw.WHITE, w=20)
        draw.tag(p, 270, 202, "I0.3", not self.tripped)
        # motor
        mr = 44
        draw.shadow(p, QRectF(m.x() - mr, m.y() - mr, 2 * mr, 2 * mr), mr, 4)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#1d4ed8") if flowing else QColor("#475569"))
        p.drawEllipse(m, mr, mr)
        p.setBrush(QColor("#e2e8f0"))
        p.drawEllipse(m, mr * 0.66, mr * 0.66)
        p.setPen(QPen(draw.GREEN if flowing else QColor("#334155"), 3, Qt.SolidLine, Qt.RoundCap))
        for k in range(4):
            a = self.angle + k * math.pi / 2
            p.drawLine(QPointF(m.x() + math.cos(a) * mr * 0.15, m.y() + math.sin(a) * mr * 0.15),
                       QPointF(m.x() + math.cos(a) * mr * 0.58, m.y() + math.sin(a) * mr * 0.58))
        draw.ctext(p, m.x(), m.y() - mr * 0.82, "M 3~", 7, True, draw.WHITE, 40)
        if abs(self.w) > 0.02:                   # seta do sentido de giro
            p.setPen(QPen(QColor("#f59e0b"), 3, Qt.SolidLine, Qt.RoundCap))
            arc = QRectF(m.x() - mr - 9, m.y() - mr - 9, 2 * mr + 18, 2 * mr + 18)
            start = 20 if self.w > 0 else 160
            p.drawArc(arc, int(start * 16), int(-40 * 16 if self.w > 0 else 40 * 16))
            tip_a = math.radians(-20 if self.w > 0 else 200)
            tip = QPointF(m.x() + math.cos(tip_a) * (mr + 9), m.y() - math.sin(tip_a) * (mr + 9))
            p.setBrush(QColor("#f59e0b"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(tip, 4, 4)
        draw.ctext(p, m.x() - 92, m.y() - 10, {1: "↻ horário", -1: "↺ anti-horário"}.get(1 if self.w > 0.02 else
                                                                                       (-1 if self.w < -0.02 else 0),
                                                                                       "parado"),
                   8.5, True, draw.INK, 110)
        draw.tag(p, m.x() - 140, m.y() + 12, "I0.5 rotação", sens["ROTACAO"])
        draw.tag(p, m.x() - 140, m.y() + 34, "I0.6 parado", sens["PARADO"])
        # borne U2 V2 W2: estrela (K2) e retorno ao triangulo (K3)
        u2 = QPointF(m.x(), m.y() + mr)
        star_live = line_live
        self._wire(p, [u2, QPointF(m.x(), 326), QPointF(410, 326), QPointF(410, 158)], star_live,
                   flowing and conn == "triangulo")
        self._wire(p, [QPointF(m.x(), 326), QPointF(m.x(), 334)], star_live, flowing and conn == "estrela")
        self._contactor(p, m.x() - 42, 334, "K2", "estrela", "Q0.2")
        # ponto estrela
        sp = QPointF(m.x() + 62, 364)
        p.setPen(QPen(QColor("#334155"), 2))
        for k in range(3):
            a = math.radians(90 + k * 120)
            p.drawLine(sp, QPointF(sp.x() + math.cos(a) * 9, sp.y() - math.sin(a) * 9))
        draw.text(p, sp.x() + 12, sp.y(), "Y", 9, True, draw.MUTED, w=20)
        if self.breaker_open:
            draw.plate(p, QRectF(290, 200, 140, 22), "DISJUNTOR ABERTO", "#b91c1c")
        conn_name = {"estrela": "Y  ESTRELA", "triangulo": "Δ  TRIÂNGULO"}.get(conn, "")
        if conn_name:
            draw.plate(p, QRectF(300, 236, 118, 22), conn_name, "#1d4ed8")
        # ---- medicao
        draw.card(p, QRectF(456, 14, 252, 140), "Medição")
        amps = self.current * NOMINAL_A
        draw.gauge(p, QPointF(518, 86), 44, min(80.0, amps), 0, 80, "Corrente", "A",
                   [(0, 11, "#86efac"), (11, 35, "#fde047"), (35, 80, "#fca5a5")], "{:.1f}")
        draw.gauge(p, QPointF(646, 86), 44, self.w * 100, -100, 100, "Velocidade", "%",
                   [(-100, -85, "#86efac"), (-3, 3, "#93c5fd"), (85, 100, "#86efac")], "{:+.0f}", 4)
        draw.trend(p, QRectF(456, 164, 252, 128), [(self.trend.series(0), "#dc2626"),
                                                   ([v * 0.8 for v in self.trend.series(1)], "#2563eb")],
                   -80, 80, "Tendência: corrente (A) e velocidade", [(0, "#94a3b8")], 120)
        # ---- painel do operador
        draw.card(p, QRectF(456, 300, 252, 160))
        draw.push_button(p, QRectF(462, 316, 120, 28), "LIGA ↻ I0.0", self.is_pressed("LIGA_H"), draw.GREEN)
        draw.push_button(p, QRectF(588, 316, 120, 28), "LIGA ↺ I0.1", self.is_pressed("LIGA_A"), draw.GREEN)
        draw.push_button(p, QRectF(462, 350, 120, 28), "DESLIGA I0.2", self.is_pressed("DESLIGA"), draw.RED)
        draw.lamp(p, QPointF(600, 364), 8, self.out.get("LIGADO", False), draw.GREEN)
        draw.text(p, 614, 364, "LIGADO Q0.4", 7.5, True)
        draw.lamp(p, QPointF(476, 404), 8, self.out.get("FALHA", False), draw.RED)
        draw.text(p, 490, 404, "FALHA Q0.5", 7.5, True)
        draw.text(p, 576, 404, f"F1 {min(100, self.heat / THERMAL_TRIP * 100):.0f}%", 7.5, True,
                  draw.RED if self.tripped else draw.MUTED, w=120)
        # ---- injecao de defeitos
        draw.text(p, 20, 420, "DEFEITOS DO PROCESSO", 7, True, draw.MUTED)
        draw.switch(p, QRectF(20, 432, 132, 28), "Sobrecarga", self.overload)
        draw.switch(p, QRectF(160, 432, 132, 28), "Falta de fase", self.phase_lost)
        draw.push_button(p, QRectF(300, 432, 132, 28), "Rearmar Q1/F1", False, draw.AMBER)
