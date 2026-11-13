"""Dosagem por balanca: duas velocidades, material em queda e corte antecipado (registradores N)."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import DelayLine, approach
from ..registry import register

COARSE, FINE = 300.0, 25.0        # g/s com a valvula grossa e com a fina
VALVE_S = 0.1                     # valvulas abrem e fecham em 0,1 s
FALL_S = 0.3                      # tempo de queda do bico ao recipiente
FILTER_S = 0.1                    # filtro da celula de carga
STABLE_RATE, STABLE_MS = 3.0, 500     # estavel: menos de 3 g/s por 0,5 s
BELT_SPEED, BELT_ACCEL = 250.0, 4000.0  # mm/s e mm/s^2 (para em ~8 mm)
SPACING = 500.0                   # mm entre recipientes
SENSOR_MM = 12.0                  # janela do sensor de recipiente
SCALE_MM = 60.0                   # o recipiente esta sobre a balanca
TOL = 0.02                        # tolerancia de +-2% do setpoint
SETPOINTS = {"SP_250": 250, "SP_500": 500, "SP_1000": 1000}
PESO_WORD, SP_WORD = 0, 1


@register
class ScaleEnvironment(Environment):
    id = "balanca"
    name = "Dosagem por balança"
    description = ("A balança escreve o peso em N0 (gramas) e o setpoint escolhido em N1. A válvula grossa enche "
                   "rápido (300 g/s) e a fina termina devagar (25 g/s). O material leva 0,3 s caindo: quando o peso "
                   "chega ao alvo ainda há produto no ar, então é preciso fechar antes (corte antecipado) e corrigir "
                   "esse corte pelo erro de cada recipiente. 'Estável' indica que o peso parou de mudar. Tolerância: "
                   "±2% do setpoint.")
    example = "ambientes/balanca.ladproj"
    inputs = [
        IOPoint("PARTIDA", "I0.0", "Partida", "Botão PARTIDA (NA)", BUTTON),
        IOPoint("PARADA", "I0.1", "Parada", "Botão PARADA (NF: lê 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("RECIPIENTE", "I0.2", "Recipiente_Posicionado", "Recipiente sob o bico"),
        IOPoint("ESTAVEL", "I0.3", "Peso_Estavel", "Balança estável (peso parado)"),
    ]
    outputs = [
        IOPoint("GROSSA", "Q0.0", "Valvula_Grossa", "Válvula de enchimento grossa (rápida)"),
        IOPoint("FINA", "Q0.1", "Valvula_Fina", "Válvula de enchimento fina (lenta)"),
        IOPoint("ESTEIRA", "Q0.2", "Esteira", "Esteira dos recipientes"),
        IOPoint("OK", "Q0.3", "Lampada_OK", "Lâmpada PESO OK"),
        IOPoint("REJEITO", "Q0.4", "Lampada_Rejeito", "Lâmpada FORA DA TOLERÂNCIA"),
    ]

    def reset(self) -> None:
        self.setpoint = getattr(self, "setpoint", 500)
        self.cans: list[list[float]] = [[-SPACING, 0.0], [-2 * SPACING, 0.0]]   # [posicao mm, gramas]
        self.v = 0.0
        self.valves = {"GROSSA": 0.0, "FINA": 0.0}
        self.air = DelayLine(FALL_S)
        self.reading = 0.0
        self.stable_ms = 0
        self.spilled = 0.0
        self.results: list[float] = []
        self.ok = self.bad = 0
        self.last_error: float | None = None
        self.overflow = False
        self.wrong_ok = False
        self.n_words = 64

    def configure(self, n_inputs: int, n_outputs: int, n_words: int) -> bool:
        self.n_words = n_words
        return False

    def input_words(self) -> dict[int, int]:
        return {PESO_WORD: round(self.reading), SP_WORD: self.setpoint}

    def on_control(self, key: str, down: bool) -> None:
        if down and key in SETPOINTS:
            self.setpoint = SETPOINTS[key]

    def press(self, key: str, down: bool) -> None:
        if key in SETPOINTS:
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _under_spout(self) -> list[float] | None:
        return next((c for c in self.cans if abs(c[0]) <= 15.0), None)

    def _on_scale(self) -> list[float] | None:
        return next((c for c in self.cans if abs(c[0]) <= SCALE_MM), None)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for key in self.valves:
            self.valves[key] = approach(self.valves[key], 1.0 if out[key] else 0.0, 1 / VALVE_S, 1 / VALVE_S, dt)
        self.air.push((COARSE * self.valves["GROSSA"] + FINE * self.valves["FINA"]) * dt)
        landed = self.air.advance(dt)
        can = self._under_spout()
        if landed:
            if can is not None:
                can[1] += landed
            else:
                self.spilled += landed
        before = {id(c): abs(c[0]) <= SCALE_MM for c in self.cans}
        self.v = approach(self.v, BELT_SPEED if out["ESTEIRA"] else 0.0, BELT_ACCEL, BELT_ACCEL, dt)
        for c in self.cans:
            c[0] += self.v * dt
        for c in self.cans:                              # recipiente saindo da balanca: resultado
            if before[id(c)] and abs(c[0]) > SCALE_MM and c[0] > 0 and c[1] > 1.0:
                error = c[1] - self.setpoint
                self.last_error = error
                good = abs(error) <= TOL * self.setpoint
                self.ok += good
                self.bad += not good
                if out["OK"] and not good:
                    self.wrong_ok = True
        if self.cans and self.cans[-1][0] > -2 * SPACING + 1:
            self.cans.append([self.cans[-1][0] - SPACING, 0.0])
        self.cans = [c for c in self.cans if c[0] < 700]
        on_scale = self._on_scale()
        weight = on_scale[1] if on_scale is not None else 0.0
        old = self.reading
        self.reading += (weight - self.reading) * min(1.0, dt / FILTER_S)
        rate = abs(self.reading - old) / dt if dt else 0.0
        self.stable_ms = self.stable_ms + dt_ms if rate < STABLE_RATE and abs(self.v) < 1.0 else 0
        if on_scale is not None and on_scale[1] > 1.3 * self.setpoint:
            self.overflow = True

    def sensors(self) -> dict[str, bool]:
        return {"RECIPIENTE": any(abs(c[0]) <= SENSOR_MM for c in self.cans), "ESTAVEL": self.stable_ms >= STABLE_MS}

    def alarms(self) -> list[str]:
        out = []
        if self.spilled > 5.0:
            out.append("Produto derramado: válvula aberta sem recipiente sob o bico ou com a esteira andando")
        if self.overflow:
            out.append("O recipiente transbordou (mais de 130% do setpoint)")
        if self.wrong_ok:
            out.append("A lâmpada OK acendeu para um recipiente fora da tolerância")
        return out

    def stats(self) -> list[str]:
        err = "-" if self.last_error is None else f"{self.last_error:+.1f} g"
        info = [f"Setpoint N1: {self.setpoint} g | peso N0: {self.reading:.0f} g | último erro: {err}",
                f"Dentro da tolerância (±2%): {self.ok} | fora: {self.bad} | derramado: {self.spilled:.0f} g"]
        if self.n_words <= SP_WORD:
            info.append("A balança precisa dos registradores N0 e N1: escolha um controlador com registradores N.")
        return info

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"PARTIDA": (16, 340, 130, 28), "PARADA": (16, 376, 130, 28),
                "SP_250": (470, 350, 50, 28), "SP_500": (524, 350, 50, 28), "SP_1000": (578, 350, 50, 28)}

    def _x(self, mm: float) -> float:
        return 320 + mm * 0.4

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f8fafc"))
        # funil
        p.setPen(QPen(QColor("#1e293b"), 1.5))
        p.setBrush(QColor("#cbd5e1"))
        p.drawPolygon(QPolygonF([QPointF(250, 20), QPointF(390, 20), QPointF(332, 90), QPointF(308, 90)]))
        p.setBrush(QColor("#a16207"))
        p.drawPolygon(QPolygonF([QPointF(262, 32), QPointF(378, 32), QPointF(330, 86), QPointF(310, 86)]))
        # valvulas
        for k, (key, label, addr) in enumerate((("GROSSA", "grossa", "Q0.0"), ("FINA", "fina", "Q0.1"))):
            x = 300 + k * 40
            p.setBrush(draw.GREEN if self.valves[key] > 0.5 else QColor("#475569"))
            p.drawRect(QRectF(x - 8, 92, 16, 14))
            draw.tag(p, 226 if k == 0 else 350, 100 + k * 22, f"{addr} {label}", self.out.get(key, False))
        # produto caindo
        if self.air.in_flight > 0.5:
            p.setPen(QPen(QColor("#a16207"), 2 + 6 * self.valves["GROSSA"], Qt.DotLine))
            p.drawLine(QPointF(320, 108), QPointF(320, 220))
        # esteira e recipientes
        belt_y = 262
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#334155"))
        p.drawRoundedRect(QRectF(20, belt_y, 600, 14), 7, 7)
        for pos, grams in self.cans:
            x = self._x(pos)
            if -40 < x < 680:
                r = QRectF(x - 22, belt_y - 50, 44, 50)
                p.setPen(QPen(QColor("#1e3a8a"), 1.5))
                p.setBrush(QColor("#dbeafe"))
                p.drawRect(r)
                frac = min(1.3, grams / max(1, self.setpoint)) / 1.3
                p.fillRect(QRectF(r.left() + 2, r.bottom() - 48 * frac, r.width() - 4, 48 * frac), QColor("#ca8a04"))
        # balanca
        p.setBrush(QColor("#64748b"))
        p.setPen(QPen(QColor("#0f172a"), 1.2))
        p.drawRect(QRectF(self._x(-SCALE_MM) - 10, belt_y + 14, self._x(SCALE_MM) - self._x(-SCALE_MM) + 20, 12))
        disp = QRectF(400, 160, 150, 60)
        p.setBrush(QColor("#111827"))
        p.drawRoundedRect(disp, 6, 6)
        draw.text(p, disp.center().x(), disp.top() + 24, f"{self.reading:6.0f} g", 16, True, QColor("#22c55e"),
                  Qt.AlignHCenter | Qt.AlignVCenter, 140, 28)
        draw.text(p, disp.center().x(), disp.bottom() - 10, f"N0  | alvo N1 = {self.setpoint} g", 7, True,
                  QColor("#9ca3af"), Qt.AlignHCenter | Qt.AlignVCenter, 140)
        sens = self.sensors()
        draw.tag(p, 400, 236, "I0.3 estável", sens["ESTAVEL"])
        draw.sensor(p, QRectF(self._x(-80) - 16, belt_y - 34, 16, 10), sens["RECIPIENTE"], vertical=False)
        draw.tag(p, 40, belt_y - 46, "I0.2 recipiente", sens["RECIPIENTE"])
        draw.tag(p, 40, belt_y + 34, "Q0.2 esteira", self.out.get("ESTEIRA", False))
        # painel
        draw.lamp(p, QPointF(40, 60), 10, self.out.get("OK", False), draw.GREEN)
        draw.text(p, 56, 60, "PESO OK  Q0.3", 8, True)
        draw.lamp(p, QPointF(40, 92), 10, self.out.get("REJEITO", False), draw.RED)
        draw.text(p, 56, 92, "FORA DA TOLERÂNCIA  Q0.4", 8, True, w=170)
        draw.text(p, 30, 130, f"OK: {self.ok}   Fora: {self.bad}", 9, True)
        draw.push_button(p, QRectF(16, 340, 130, 28), "PARTIDA  I0.0", self.is_pressed("PARTIDA"), draw.GREEN)
        draw.push_button(p, QRectF(16, 376, 130, 28), "PARADA  I0.1 (NF)", self.is_pressed("PARADA"), draw.RED)
        draw.text(p, 470, 340, "Setpoint (N1):", 7.5, True, draw.MUTED, w=150)
        for key, x in (("SP_250", 470), ("SP_500", 524), ("SP_1000", 578)):
            value = SETPOINTS[key]
            r = QRectF(x, 350, 50, 28)
            p.setPen(QPen(QColor("#334155"), 1))
            p.setBrush(QColor("#2563eb") if self.setpoint == value else QColor("#e2e8f0"))
            p.drawRoundedRect(r, 5, 5)
            draw.text(p, r.center().x(), r.center().y(), f"{value}", 8, True,
                      draw.WHITE if self.setpoint == value else draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 48)
