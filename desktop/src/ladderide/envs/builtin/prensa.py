"""Prensa hidraulica com comando bimanual: simultaneidade, anti-repeticao e cortina de luz."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import SENSOR, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

SPEED_DOWN, SPEED_UP = 40.0, 55.0     # %/s: desce em 2,5 s e sobe em ~1,8 s
ACCEL = 400.0                         # %/s^2: o cilindro hidraulico responde em ~0,1 s
SYNC_MS = 500                         # norma (EN 574 / NR-12): botoes acionados em ate 0,5 s
TOP, BOTTOM = 1.0, 99.0               # PMS e PMI (%)
TOOL_ZONE = 70.0                      # a partir daqui o martelo alcanca a mao na ferramenta


@register
class TwoHandPressEnvironment(Environment):
    id = "prensa"
    name = "Prensa com comando bimanual"
    description = ("Clique nos botões para APOIAR ou SOLTAR cada mão (o operador mantém o botão apertado). "
                   "'Duas mãos juntas' aperta ou solta os dois no mesmo instante. A descida só é segura com os "
                   "dois botões acionados em até 0,5 s um do outro e mantidos até o PMI; soltar um deles deve "
                   "fazer a prensa subir. Para um novo golpe é preciso soltar os dois (anti-repetição). 'Mão na "
                   "ferramenta' interrompe a cortina de luz (NF). A emergência é uma chave com trava, NF.")
    example = "ambientes/prensa.ladproj"
    inputs = [
        IOPoint("ESQ", "I0.0", "Botao_Esquerdo", "Botão da mão esquerda (NA)", SWITCH),
        IOPoint("DIR", "I0.1", "Botao_Direito", "Botão da mão direita (NA)", SWITCH),
        IOPoint("CORTINA", "I0.2", "Cortina_Luz", "Cortina de luz (NF: lê 1 com a zona livre)", SENSOR,
                normally_closed=True),
        IOPoint("PMS", "I0.3", "PMS", "Ponto morto superior (martelo em cima)"),
        IOPoint("PMI", "I0.4", "PMI", "Ponto morto inferior (fim do golpe)"),
        IOPoint("EMERG", "I0.5", "Emergencia", "Emergência com trava (NF: lê 1 quando liberada)", SWITCH,
                normally_closed=True),
    ]
    outputs = [
        IOPoint("DESCE", "Q0.0", "Valvula_Desce", "Válvula: martelo desce"),
        IOPoint("SOBE", "Q0.1", "Valvula_Sobe", "Válvula: martelo sobe"),
        IOPoint("PRONTA", "Q0.2", "Lampada_Pronta", "Lâmpada PRONTA para o golpe"),
    ]

    def reset(self) -> None:
        self.pos = 0.0                  # 0 = em cima, 100 = embaixo
        self.v = 0.0
        self.hand_in_die = False
        self.pressed_at: dict[str, int | None] = {"ESQ": None, "DIR": None}
        self._prev = {"ESQ": False, "DIR": False}
        self.released_since_stroke = True
        self.strokes = 0
        self.pieces = 0
        self._stamped = False
        self.hand_danger = 0
        self.one_hand = 0
        self.not_simultaneous = 0
        self.repeats = 0
        self.both_valves_ms = 0
        self.emergency_moves = 0
        self.last_gap_ms: int | None = None
        self.bad_gap_ms = 0
        self._descending = False

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AMBAS":
            both = self.is_pressed("ESQ") and self.is_pressed("DIR")
            self.operator["ESQ"] = self.operator["DIR"] = not both
        elif key == "MAO":
            self.hand_in_die = not self.hand_in_die

    def press(self, key: str, down: bool) -> None:
        if key in ("AMBAS", "MAO"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        for key in ("ESQ", "DIR"):                     # instante em que cada mao apertou
            now = self.is_pressed(key)
            if now and not self._prev[key]:
                self.pressed_at[key] = self.time_ms
            self._prev[key] = now
        both = self.is_pressed("ESQ") and self.is_pressed("DIR")
        if not self.is_pressed("ESQ") and not self.is_pressed("DIR"):
            self.released_since_stroke = True
        down, up = out["DESCE"], out["SOBE"]
        self.both_valves_ms = self.both_valves_ms + dt_ms if (down and up) else 0
        cmd = 0 if down == up else (1 if down else -1)
        if cmd > 0 and not self._descending and self.pos <= TOP + 1:     # inicio de um golpe
            if not both:
                self.one_hand += 1
            else:
                gap = abs(self.pressed_at["ESQ"] - self.pressed_at["DIR"])
                self.last_gap_ms = gap
                if gap > SYNC_MS:
                    self.not_simultaneous += 1
                    self.bad_gap_ms = self.bad_gap_ms or gap
                if not self.released_since_stroke:
                    self.repeats += 1
            self.released_since_stroke = False
        self._descending = cmd > 0
        target = SPEED_DOWN if cmd > 0 else (-SPEED_UP if cmd < 0 else 0.0)
        self.v = approach(self.v, target, ACCEL, ACCEL, dt)
        moving_down = self.v > 0.5 and self.pos < 100.0
        if moving_down:
            if self.hand_in_die and self.pos >= TOOL_ZONE:
                self.hand_danger += 1
            if not both and self.pos > 5:
                self.one_hand = max(self.one_hand, 1)
            if self.is_pressed("EMERG"):
                self.emergency_moves += 1
        self.pos = min(100.0, max(0.0, self.pos + self.v * dt))
        if self.pos in (0.0, 100.0):
            self.v = 0.0
        if self.pos >= BOTTOM and not self._stamped:
            self._stamped = True
            self.strokes += 1
        if self.pos <= TOP and self._stamped:            # peca estampada sai, entra outra
            self._stamped = False
            self.pieces += 1

    def sensors(self) -> dict[str, bool]:
        return {"CORTINA": self.hand_in_die, "PMS": self.pos <= TOP, "PMI": self.pos >= BOTTOM}

    def alarms(self) -> list[str]:
        out = []
        if self.hand_danger:
            out.append("PERIGO: o martelo desceu com a mão na ferramenta (use a cortina de luz I0.2)")
        if self.one_hand:
            out.append("A prensa desceu sem as duas mãos nos botões")
        if self.not_simultaneous:
            out.append(f"Golpe aceito com os botões acionados a {self.bad_gap_ms} ms um do outro (máximo 500 ms)")
        if self.repeats:
            out.append("Novo golpe sem soltar os dois botões: falta a anti-repetição")
        if self.both_valves_ms > 0:
            out.append("Válvulas de descer e subir ligadas ao mesmo tempo")
        if self.emergency_moves:
            out.append("O martelo desceu com a emergência acionada")
        return out

    def stats(self) -> list[str]:
        gap = "-" if self.last_gap_ms is None else f"{self.last_gap_ms} ms"
        return [f"Martelo: {self.pos:.0f}% do curso | golpes: {self.strokes}",
                f"Intervalo entre as mãos no último golpe: {gap}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"ESQ": (40, 340, 150, 34), "DIR": (450, 340, 150, 34), "AMBAS": (245, 345, 150, 28),
                "MAO": (20, 220, 160, 28), "EMERG": (20, 256, 160, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f1f5f9"))
        frame = QRectF(200, 30, 240, 280)
        p.setPen(QPen(QColor("#1e293b"), 2))
        p.setBrush(QColor("#475569"))
        p.drawRect(QRectF(frame.left(), frame.top(), frame.width(), 30))                # cabecote
        p.drawRect(QRectF(frame.left(), frame.top(), 26, frame.height()))              # colunas
        p.drawRect(QRectF(frame.right() - 26, frame.top(), 26, frame.height()))
        p.drawRect(QRectF(frame.left() - 10, frame.bottom() - 30, frame.width() + 20, 30))
        # cilindro e martelo
        travel = 120.0
        ram_top = frame.top() + 40 + travel * self.pos / 100
        p.setBrush(QColor("#94a3b8"))
        p.drawRect(QRectF(frame.center().x() - 8, frame.top() + 30, 16, ram_top - frame.top() - 30))
        grad = QLinearGradient(0, ram_top, 0, ram_top + 50)
        grad.setColorAt(0, QColor("#64748b"))
        grad.setColorAt(1, QColor("#334155"))
        p.setBrush(grad)
        p.drawRect(QRectF(frame.left() + 40, ram_top, frame.width() - 80, 50))
        # matriz e peca
        die_y = frame.bottom() - 70
        p.setBrush(QColor("#1f2937"))
        p.drawRect(QRectF(frame.left() + 40, die_y + 10, frame.width() - 80, 30))
        stamped = self._stamped
        p.setBrush(QColor("#f59e0b") if not stamped else QColor("#b45309"))
        p.drawRect(QRectF(frame.left() + 70, die_y + (4 if stamped else 0), frame.width() - 140, 10 if not stamped else 6))
        # cortina de luz
        sens = self.sensors()
        for x in (frame.left() + 32, frame.right() - 32):
            draw.sensor(p, QRectF(x - 4, die_y - 60, 8, 60), sens["CORTINA"])
        for k in range(6):
            yy = die_y - 54 + k * 10
            draw.beam(p, QPointF(frame.left() + 36, yy), QPointF(frame.right() - 36, yy), sens["CORTINA"])
        if self.hand_in_die:
            p.setBrush(QColor("#fcd9b6"))
            p.setPen(QPen(QColor("#9a3412"), 1.5))
            p.drawRoundedRect(QRectF(frame.right() - 120, die_y - 22, 110, 26), 12, 12)
            draw.text(p, frame.right() - 112, die_y - 9, "mão", 8, True, QColor("#9a3412"))
        # fins de curso
        draw.tag(p, frame.right() + 8, frame.top() + 46, "I0.3 PMS", sens["PMS"])
        draw.tag(p, frame.right() + 8, frame.top() + 46 + travel, "I0.4 PMI", sens["PMI"])
        # valvulas
        draw.arrow(p, QPointF(frame.left() - 40, 90), 18, False, self.out.get("DESCE", False))
        draw.tag(p, 20, 90, "Q0.0 desce", self.out.get("DESCE", False))
        draw.arrow(p, QPointF(frame.left() - 40, 60), 18, True, self.out.get("SOBE", False))
        draw.tag(p, 20, 60, "Q0.1 sobe", self.out.get("SOBE", False))
        draw.lamp(p, QPointF(40, 140), 11, self.out.get("PRONTA", False), draw.GREEN)
        draw.text(p, 58, 140, "PRONTA  Q0.2", 8, True)
        draw.text(p, 20, 180, f"Golpes: {self.strokes}", 9, True)
        # controles do operador
        draw.switch(p, QRectF(20, 220, 160, 28), "Mão na ferramenta", self.hand_in_die)
        draw.switch(p, QRectF(20, 256, 160, 28), "EMERGÊNCIA I0.5", self.is_pressed("EMERG"))
        draw.push_button(p, QRectF(40, 340, 150, 34), "ESQUERDA  I0.0", self.is_pressed("ESQ"), QColor("#2563eb"))
        draw.push_button(p, QRectF(450, 340, 150, 34), "DIREITA  I0.1", self.is_pressed("DIR"), QColor("#2563eb"))
        draw.push_button(p, QRectF(245, 345, 150, 28), "Duas mãos juntas", False, draw.AMBER)
        draw.text(p, 320, 392, "clique para apoiar / soltar cada mão", 7.5, False, draw.MUTED,
                  Qt.AlignHCenter | Qt.AlignVCenter, 300)
