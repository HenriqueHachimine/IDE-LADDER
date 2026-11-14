"""Prensa hidraulica com comando bimanual, valvula de seguranca monitorada, modo ajuste e lubrificacao."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import SENSOR, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

SPEED_DOWN, SPEED_UP = 40.0, 55.0     # %/s: desce em 2,5 s e sobe em ~1,8 s
SLOW = 0.25                           # modo ajuste: 25% da velocidade de descida
CREEP = 6.0                           # %/s: valvula travada com a seguranca liberada
ACCEL = 400.0                         # %/s^2: o cilindro hidraulico responde em ~0,1 s
SPOOL_MS = 30                         # carretel da valvula segue o solenoide em 30 ms
SYNC_MS = 500                         # norma (EN 574 / NR-12): botoes acionados em ate 0,5 s
TOP, BOTTOM = 1.0, 99.0               # PMS e PMI (%)
TOOL_ZONE = 70.0                      # a partir daqui o martelo alcanca a mao na ferramenta
LUBE_EVERY, LUBE_LIMIT, LUBE_MS = 20, 25, 2000   # lubrificar a cada 20 golpes; alarme depois de 25


@register
class TwoHandPressEnvironment(Environment):
    id = "prensa"
    name = "Prensa hidráulica bimanual"
    description = ("Clique nos botões para APOIAR ou SOLTAR cada mão. A descida exige os dois botões em até 0,5 s, "
                   "mantidos até o PMI, e duas válvulas em série: DESCE (Q0.0) e a válvula de segurança LIBERA "
                   "(Q0.4). O sensor I0.7 mostra o carretel da DESCE em repouso: 'Válvula travada' o prende aberto "
                   "e o martelo desce sozinho se a LIBERA estiver ligada. O programa deve detectar, bloquear e "
                   "acender FALHA até a emergência ser acionada e liberada. Modo ajuste (I0.6): só velocidade "
                   "lenta (Q0.3). A cada 20 golpes a bomba de lubrificação (Q0.6) precisa rodar 2 s.")
    example = "ambientes/prensa.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("ESQ", "I0.0", "Botao_Esquerdo", "Botão da mão esquerda (NA)", SWITCH),
        IOPoint("DIR", "I0.1", "Botao_Direito", "Botão da mão direita (NA)", SWITCH),
        IOPoint("CORTINA", "I0.2", "Cortina_Luz", "Cortina de luz (NF: lê 1 com a zona livre)", SENSOR,
                normally_closed=True),
        IOPoint("PMS", "I0.3", "PMS", "Ponto morto superior (martelo em cima)"),
        IOPoint("PMI", "I0.4", "PMI", "Ponto morto inferior (fim do golpe)"),
        IOPoint("EMERG", "I0.5", "Emergencia", "Emergência com trava (NF: lê 1 quando liberada)", SWITCH,
                normally_closed=True),
        IOPoint("AJUSTE", "I0.6", "Modo_Ajuste", "Chave de modo: 1 = ajuste (velocidade lenta)", SWITCH),
        IOPoint("REPOUSO", "I0.7", "Valvula_Repouso", "Carretel da válvula DESCE em repouso (fechada)"),
    ]
    outputs = [
        IOPoint("DESCE", "Q0.0", "Valvula_Desce", "Válvula: martelo desce"),
        IOPoint("SOBE", "Q0.1", "Valvula_Sobe", "Válvula: martelo sobe"),
        IOPoint("PRONTA", "Q0.2", "Lampada_Pronta", "Lâmpada PRONTA para o golpe"),
        IOPoint("LENTA", "Q0.3", "Velocidade_Lenta", "Válvula de velocidade lenta (modo ajuste)"),
        IOPoint("LIBERA", "Q0.4", "Valvula_Seguranca", "Válvula de segurança em série com a DESCE"),
        IOPoint("FALHA", "Q0.5", "Lampada_Falha", "Lâmpada FALHA da válvula"),
        IOPoint("LUBRIFICA", "Q0.6", "Bomba_Lubrificacao", "Bomba de lubrificação centralizada"),
    ]

    def reset(self) -> None:
        self.pos = 0.0                  # 0 = em cima, 100 = embaixo
        self.v = 0.0
        self.hand_in_die = False
        self.stuck = getattr(self, "stuck", False)
        self.spool_open = False
        self._spool_t = 0
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
        self.fast_in_setup = 0
        self.uncommanded = 0.0           # % de curso descido sem comando (valvula travada)
        self.stroke_with_stuck = 0
        self.unsignalled_ms = 0
        self.since_lube = 0
        self.max_since_lube = 0
        self.lube_ms = 0
        self.lube_total = 0
        self.last_gap_ms: int | None = None
        self.bad_gap_ms = 0
        self._descending = False
        self.oil = 0.0

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AMBAS":
            both = self.is_pressed("ESQ") and self.is_pressed("DIR")
            self.operator["ESQ"] = self.operator["DIR"] = not both
        elif key == "MAO":
            self.hand_in_die = not self.hand_in_die
        elif key == "TRAVADA":
            self.stuck = not self.stuck

    def press(self, key: str, down: bool) -> None:
        if key in ("AMBAS", "MAO", "TRAVADA"):
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
        # carretel da valvula DESCE: segue o solenoide em 30 ms, ou fica preso aberto
        want = out["DESCE"] or self.stuck
        if want != self.spool_open:
            self._spool_t += dt_ms
            if self._spool_t >= SPOOL_MS:
                self.spool_open, self._spool_t = want, 0
        else:
            self._spool_t = 0
        flow_down = self.spool_open and out["LIBERA"]
        up = out["SOBE"]
        self.both_valves_ms = self.both_valves_ms + dt_ms if (out["DESCE"] and up) else 0
        cmd = 0 if flow_down == up else (1 if flow_down else -1)
        if cmd > 0 and not self._descending and self.pos <= TOP + 1:     # inicio de um golpe
            if out["DESCE"]:
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
                if self.stuck:
                    self.stroke_with_stuck += 1
            self.released_since_stroke = False
        self._descending = cmd > 0
        if cmd > 0:
            speed = SPEED_DOWN * (SLOW if out["LENTA"] else 1.0) if out["DESCE"] else CREEP
            target = speed
        else:
            target = -SPEED_UP if cmd < 0 else 0.0
        self.v = approach(self.v, target, ACCEL, ACCEL, dt)
        moving_down = self.v > 0.5 and self.pos < 100.0
        if moving_down:
            if self.hand_in_die and self.pos >= TOOL_ZONE:
                self.hand_danger += 1
            if out["DESCE"] and not both and self.pos > 5:
                self.one_hand = max(self.one_hand, 1)
            if self.is_pressed("EMERG"):
                self.emergency_moves += 1
            if self.is_pressed("AJUSTE") and self.v > SPEED_DOWN * SLOW + 1:
                self.fast_in_setup += 1
            if flow_down and not out["DESCE"]:
                self.uncommanded += self.v * dt
        self.pos = min(100.0, max(0.0, self.pos + self.v * dt))
        if self.pos in (0.0, 100.0):
            self.v = 0.0
        if self.pos >= BOTTOM and not self._stamped:
            self._stamped = True
            self.strokes += 1
            self.since_lube += 1
            self.max_since_lube = max(self.max_since_lube, self.since_lube)
        if self.pos <= TOP and self._stamped:            # peca estampada sai, entra outra
            self._stamped = False
            self.pieces += 1
        if out["LUBRIFICA"]:
            self.lube_ms += dt_ms
            self.oil = (self.oil + dt * 3) % 1.0
            if self.lube_ms >= LUBE_MS and self.since_lube:
                self.since_lube = 0
                self.lube_total += 1
        else:
            self.lube_ms = 0
        self.unsignalled_ms = self.unsignalled_ms + dt_ms if (self.stuck and not out["FALHA"]) else 0

    def sensors(self) -> dict[str, bool]:
        return {"CORTINA": self.hand_in_die, "PMS": self.pos <= TOP, "PMI": self.pos >= BOTTOM,
                "REPOUSO": not self.spool_open}

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
        if self.fast_in_setup:
            out.append("Modo ajuste com descida rápida: ligue a velocidade lenta (Q0.3)")
        if self.uncommanded > 3:
            out.append("O martelo desceu sem comando: válvula DESCE travada e válvula de segurança ligada")
        if self.stroke_with_stuck:
            out.append("Golpe iniciado com a válvula DESCE travada: monitore o sensor de repouso (I0.7) e bloqueie")
        if self.unsignalled_ms > 1000:
            out.append("Válvula travada sem a lâmpada FALHA acesa")
        if self.max_since_lube > LUBE_LIMIT:
            out.append(f"Prensa trabalhou {self.max_since_lube} golpes sem lubrificação (lubrifique a cada 20)")
        return out

    def stats(self) -> list[str]:
        gap = "-" if self.last_gap_ms is None else f"{self.last_gap_ms} ms"
        return [f"Martelo: {self.pos:.0f}% do curso | golpes: {self.strokes} | desde a lubrificação: {self.since_lube}",
                f"Intervalo entre as mãos no último golpe: {gap}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"ESQ": (180, 410, 130, 36), "DIR": (410, 410, 130, 36), "AMBAS": (316, 414, 88, 28),
                "MAO": (568, 214, 138, 28), "EMERG": (568, 144, 138, 28), "AJUSTE": (568, 74, 138, 28),
                "TRAVADA": (568, 284, 138, 28)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        draw.ground(p, 392, 720, 460)
        sens = self.sensors()
        out = self.out
        # ------------------------------------------------ prensa
        fx, fw = 226, 260
        top_y, base_y = 22, 360
        travel = 120.0
        # colunas e cabecote
        for x in (fx + 10, fx + fw - 34):
            draw.metal(p, QRectF(x, top_y + 40, 24, base_y - top_y - 40), "#64748b", 2, vertical=True)
        draw.shadow(p, QRectF(fx, top_y, fw, 48), 6, 4)
        draw.metal(p, QRectF(fx, top_y, fw, 48), "#475569", 6)
        draw.plate(p, QRectF(fx + 20, top_y + 14, 90, 20), "PH-60  60 t", "#1e293b")
        # cilindro hidraulico
        cyl = QRectF(fx + fw / 2 - 26, top_y - 8, 52, 56)
        draw.metal(p, cyl, "#334155", 4, vertical=True)
        ram_y = top_y + 70 + travel * self.pos / 100
        draw.metal(p, QRectF(fx + fw / 2 - 10, top_y + 48, 20, ram_y - top_y - 48), "#e5e7eb", 2, vertical=True)
        # martelo (porta-ferramenta) e punção
        slide = QRectF(fx + 44, ram_y, fw - 88, 46)
        draw.shadow(p, slide, 4, 3)
        draw.metal(p, slide, "#475569", 4)
        draw.hazard(p, QRectF(slide.left(), slide.bottom() - 7, slide.width(), 7), 7)
        punch = QRectF(fx + fw / 2 - 30, slide.bottom(), 60, 16)
        draw.metal(p, punch, "#94a3b8", 2)
        # mesa, matriz e peca
        die_y = base_y - 64
        draw.metal(p, QRectF(fx - 6, base_y - 28, fw + 12, 30), "#475569", 3)
        draw.metal(p, QRectF(fx + 50, die_y + 12, fw - 100, 24), "#1f2937", 2)
        stamped = self._stamped
        part = QRectF(fx + 80, die_y + (5 if stamped else 0), fw - 160, 12 if not stamped else 7)
        g = QLinearGradient(part.topLeft(), part.bottomLeft())
        g.setColorAt(0, QColor("#fbbf24") if not stamped else QColor("#d97706"))
        g.setColorAt(1, QColor("#b45309"))
        p.setPen(QPen(QColor("#78350f"), 1))
        p.setBrush(g)
        p.drawRect(part)
        # cortina de luz
        for x in (fx + 40, fx + fw - 40):
            draw.metal(p, QRectF(x - 5, die_y - 80, 10, 84), "#facc15", 2, vertical=True)
            for k in range(8):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ef4444") if sens["CORTINA"] else QColor("#7f1d1d"))
                p.drawEllipse(QPointF(x, die_y - 74 + k * 10), 1.8, 1.8)
        for k in range(8):
            yy = die_y - 74 + k * 10
            draw.beam(p, QPointF(fx + 46, yy), QPointF(fx + fw - 46, yy), sens["CORTINA"])
        draw.tag(p, fx + 46, die_y - 96, "I0.2 cortina", not sens["CORTINA"])
        if self.hand_in_die:
            hand = QRectF(fx + fw - 150, die_y - 24, 112, 26)
            p.setBrush(QColor("#fcd9b6"))
            p.setPen(QPen(QColor("#9a3412"), 1.5))
            p.drawRoundedRect(hand, 12, 12)
            for k in range(4):
                p.drawRoundedRect(QRectF(hand.left() - 22 + k * 0, hand.top() + 2 + k * 6, 26, 6), 3, 3)
            draw.text(p, hand.left() + 30, hand.center().y(), "mão do operador", 7.5, True, QColor("#9a3412"))
        # fins de curso e regua de curso
        rx = fx + fw + 6
        p.setPen(QPen(QColor("#334155"), 1))
        p.drawLine(QPointF(rx, top_y + 70), QPointF(rx, top_y + 70 + travel))
        for k in range(5):
            y = top_y + 70 + travel * k / 4
            p.drawLine(QPointF(rx, y), QPointF(rx + 5, y))
        draw.harrow(p, QPointF(rx - 4, ram_y), 9, False, True, QColor("#2563eb"))
        draw.tag(p, rx + 8, top_y + 70, "I0.3 PMS", sens["PMS"])
        draw.tag(p, rx + 8, top_y + 70 + travel, "I0.4 PMI", sens["PMI"])
        # ------------------------------------------------ bloco hidraulico
        draw.card(p, QRectF(14, 14, 196, 230), "Bloco hidráulico")
        self._solenoid(p, 26, 46, "DESCE", "Q0.0", out.get("DESCE", False), self.spool_open, self.stuck)
        self._solenoid(p, 26, 96, "SEGURANÇA", "Q0.4", out.get("LIBERA", False), out.get("LIBERA", False), False)
        self._solenoid(p, 26, 146, "SOBE", "Q0.1", out.get("SOBE", False), out.get("SOBE", False), False)
        draw.tag(p, 26, 200, "I0.7 carretel em repouso", sens["REPOUSO"])
        draw.tag(p, 26, 224, "Q0.3 velocidade lenta", out.get("LENTA", False))
        # ------------------------------------------------ estado e lubrificacao
        draw.card(p, QRectF(14, 252, 196, 136), "Estado")
        draw.lamp(p, QPointF(32, 284), 8, out.get("PRONTA", False), draw.GREEN)
        draw.text(p, 46, 284, "PRONTA Q0.2", 7.5, True)
        draw.lamp(p, QPointF(32, 308), 8, out.get("FALHA", False), draw.RED)
        draw.text(p, 46, 308, "FALHA Q0.5", 7.5, True)
        draw.lcd(p, QRectF(126, 278, 74, 28), f"{self.strokes:5d}", "#4ade80", "GOLPES")
        lube_frac = min(1.0, self.since_lube / LUBE_LIMIT)
        draw.text(p, 24, 332, f"Golpes sem lubrificar: {self.since_lube}", 7.5, True,
                  draw.RED if self.since_lube > LUBE_EVERY else draw.INK)
        draw.bar(p, QRectF(24, 344, 176, 8), lube_frac, draw.RED if self.since_lube > LUBE_EVERY else draw.AMBER,
                 marks=[(LUBE_EVERY / LUBE_LIMIT, "#1e293b")])
        pump_on = out.get("LUBRIFICA", False)
        draw.motor(p, QPointF(42, 370), 10, pump_on, self.oil * 2 * math.pi, "")
        draw.tag(p, 66, 370, "Q0.6 bomba de óleo", pump_on)
        # ------------------------------------------------ seguranca e modo
        draw.card(p, QRectF(562, 14, 150, 314), "Modo e segurança")
        draw.text(p, 570, 60, "Chave de modo", 7, True, draw.MUTED)
        draw.switch(p, QRectF(568, 74, 138, 28), "AJUSTE I0.6", self.is_pressed("AJUSTE"))
        draw.text(p, 570, 130, "Emergência com trava (NF)", 7, True, draw.MUTED)
        draw.switch(p, QRectF(568, 144, 138, 28), "EMERGÊNCIA I0.5", self.is_pressed("EMERG"))
        draw.text(p, 570, 200, "Situações", 7, True, draw.MUTED)
        draw.switch(p, QRectF(568, 214, 138, 28), "Mão na ferramenta", self.hand_in_die)
        draw.text(p, 570, 270, "Defeito", 7, True, draw.MUTED)
        draw.switch(p, QRectF(568, 284, 138, 28), "Válvula travada", self.stuck)
        if self.is_pressed("EMERG"):
            c = QPointF(637, 362)
            p.setPen(QPen(QColor("#7f1d1d"), 1.5))
            p.setBrush(QColor("#facc15"))
            p.drawEllipse(c, 26, 26)
            p.setBrush(QColor("#dc2626"))
            p.drawEllipse(c, 18, 18)
            draw.ctext(p, c.x(), c.y(), "STOP", 7, True, draw.WHITE, 40)
        # ------------------------------------------------ comando bimanual
        station = QRectF(170, 400, 380, 54)
        draw.shadow(p, station, 8, 3)
        draw.metal(p, station, "#facc15", 8)
        draw.push_button(p, QRectF(180, 410, 130, 36), "ESQUERDA I0.0", self.is_pressed("ESQ"), QColor("#2563eb"))
        draw.push_button(p, QRectF(410, 410, 130, 36), "DIREITA I0.1", self.is_pressed("DIR"), QColor("#2563eb"))
        draw.push_button(p, QRectF(316, 414, 88, 28), "As duas", False, draw.AMBER)
        for key, x in (("ESQ", 180), ("DIR", 410)):
            if self.is_pressed(key):
                p.setPen(QPen(draw.GREEN, 3))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(QRectF(x - 2, 408, 134, 40), 8, 8)
        draw.text(p, 14, 404, "clique para apoiar /", 7, False, draw.MUTED)
        draw.text(p, 14, 418, "soltar cada mão", 7, False, draw.MUTED)

    def _solenoid(self, p: QPainter, x: float, y: float, name: str, addr: str, coil: bool, spool_open: bool,
                  stuck: bool) -> None:
        body = QRectF(x + 40, y, 120, 34)
        draw.metal(p, body, "#cbd5e1", 4)
        coil_r = QRectF(x, y + 4, 38, 26)
        draw.metal(p, coil_r, "#16a34a" if coil else "#334155", 3)
        draw.ctext(p, coil_r.center().x(), coil_r.center().y(), addr, 7, True, draw.WHITE, 40)
        # carretel
        cx = body.left() + (64 if spool_open else 24)
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#dc2626") if stuck else QColor("#475569"))
        p.drawRect(QRectF(cx, y + 10, 32, 14))
        draw.text(p, body.left() + 4, y + 6, name, 6.5, True, draw.INK, w=110)
        draw.text(p, body.right() - 40, y + 27, "aberta" if spool_open else "fechada", 6.5, True,
                  draw.GREEN if spool_open else draw.MUTED, w=40)
