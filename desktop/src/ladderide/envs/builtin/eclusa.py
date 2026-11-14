"""Eclusa de navegacao: permissivos, equalizacao de niveis e trafego de barcos nos dois sentidos."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPolygonF

from .. import draw
from ..base import Environment, IOPoint
from ..registry import register

UP_LEVEL, DOWN_LEVEL = 10.0, 2.0      # m: rio a montante e a jusante
VALVE_K = 0.35                        # m/s por raiz de metro de desnivel (Torricelli)
EQUAL_TOL = 0.05                      # sensores de nivel igualado
GATE_S = 8.0                          # comporta leva 8 s para abrir ou fechar
GATE_FORCE = 0.15                     # abrir com mais desnivel que isso danifica a comporta
BOAT_SPEED = 30.0                     # px/s
GATE_M, GATE_J = 300.0, 470.0         # posicao das comportas no desenho
WAIT_M, WAIT_J = 230.0, 540.0         # onde os barcos esperam o sinal
PARK = 385.0                          # centro da camara
BOAT_L = 70.0
AUTO_EVERY_MS = 45000
LEVEL_WORD, BOAT_WORD = 0, 1


@dataclass
class Boat:
    side: str          # "M" (vem de montante, desce) ou "J" (vem de jusante, sobe)
    x: float
    state: str = "esperando"   # esperando, entrando, na_camara, saindo, foi, parado
    color: str = "#dc2626"
    wait_ms: int = 0


@register
class CanalLockEnvironment(Environment):
    id = "eclusa"
    name = "Eclusa de navegação"
    description = ("A eclusa leva barcos entre o rio a montante (10 m) e a jusante (2 m). A câmara enche pela válvula "
                   "de enchimento e esvazia pela de esvaziamento (vazão pela raiz do desnível); o nível da câmara "
                   "chega em N0 (cm) e os sensores I0.0 e I0.1 indicam nível igual a montante ou a jusante. Uma "
                   "comporta só pode abrir com o nível igualado; as duas comportas e as duas válvulas nunca abertas "
                   "juntas. O semáforo verde (Q0.6 montante, Q0.7 jusante) manda o barco entrar, então só com a "
                   "comporta toda aberta. N1: 0 câmara vazia, 1 barco passando por uma comporta, 2 barco parado na "
                   "câmara. O barco sai sozinho quando a comporta do outro lado abre.")
    example = "ambientes/eclusa.ladproj"
    size = (720, 420)
    inputs = [
        IOPoint("IG_M", "I0.0", "Nivel_Igual_Montante", "Câmara no nível de montante"),
        IOPoint("IG_J", "I0.1", "Nivel_Igual_Jusante", "Câmara no nível de jusante"),
        IOPoint("M_ABERTA", "I0.2", "Montante_Aberta", "Comporta de montante aberta"),
        IOPoint("M_FECHADA", "I0.3", "Montante_Fechada", "Comporta de montante fechada"),
        IOPoint("J_ABERTA", "I0.4", "Jusante_Aberta", "Comporta de jusante aberta"),
        IOPoint("J_FECHADA", "I0.5", "Jusante_Fechada", "Comporta de jusante fechada"),
        IOPoint("ESP_M", "I0.6", "Barco_Montante", "Barco esperando a montante"),
        IOPoint("ESP_J", "I0.7", "Barco_Jusante", "Barco esperando a jusante"),
    ]
    outputs = [
        IOPoint("ABRE_M", "Q0.0", "Abre_Montante", "Comporta de montante: abrir"),
        IOPoint("FECHA_M", "Q0.1", "Fecha_Montante", "Comporta de montante: fechar"),
        IOPoint("ABRE_J", "Q0.2", "Abre_Jusante", "Comporta de jusante: abrir"),
        IOPoint("FECHA_J", "Q0.3", "Fecha_Jusante", "Comporta de jusante: fechar"),
        IOPoint("ENCHE", "Q0.4", "Valvula_Enchimento", "Válvula de enchimento (vem de montante)"),
        IOPoint("ESVAZIA", "Q0.5", "Valvula_Esvaziamento", "Válvula de esvaziamento (vai para jusante)"),
        IOPoint("VERDE_M", "Q0.6", "Verde_Montante", "Semáforo de montante verde (vermelho desligado)"),
        IOPoint("VERDE_J", "Q0.7", "Verde_Jusante", "Semáforo de jusante verde (vermelho desligado)"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(23)
        self.auto = getattr(self, "auto", True)
        self.h = DOWN_LEVEL
        self.gate = {"M": 0.0, "J": 0.0}      # 0 fechada, 1 aberta
        self.boats: list[Boat] = []
        self.next_auto_ms = 3000
        self.auto_side = "M"
        self.flags: dict[str, str] = {}
        self.passed = 0
        self.max_wait_ms = 0
        self.wave = 0.0
        self.flow = 0.0

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.auto = not self.auto
        elif key in ("BARCO_M", "BARCO_J"):
            self._arrive(key[-1])

    def press(self, key: str, down: bool) -> None:
        if key in ("AUTO", "BARCO_M", "BARCO_J"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _arrive(self, side: str) -> None:
        if any(b.side == side and b.state == "esperando" for b in self.boats):
            return
        x = -BOAT_L if side == "M" else 720 + BOAT_L
        self.boats.append(Boat(side, x, "chegando", self.rng.choice(["#dc2626", "#2563eb", "#16a34a", "#f59e0b",
                                                                       "#7c3aed"])))

    def input_words(self) -> dict[int, int]:
        return {LEVEL_WORD: round(self.h * 100), BOAT_WORD: self.chamber_state()}

    def chamber_state(self) -> int:
        """0 camara vazia, 1 barco atravessando uma comporta, 2 barco parado na camara."""
        if any(b.state in ("entrando", "saindo", "parado") and b.x > GATE_M - 4 and b.x - BOAT_L < GATE_J + 4
               for b in self.boats):
            return 1
        return 2 if any(b.state == "na_camara" for b in self.boats) else 0

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        if self.auto and now >= self.next_auto_ms:
            self._arrive(self.auto_side)
            self.auto_side = "J" if self.auto_side == "M" else "M"
            self.next_auto_ms = now + AUTO_EVERY_MS
        # valvulas
        fill, empty = out["ENCHE"], out["ESVAZIA"]
        if fill and empty:
            self._flag("valves", "Válvulas de enchimento e esvaziamento abertas juntas: o rio escoa pela câmara")
        dh = 0.0
        if fill:
            dh += VALVE_K * math.sqrt(max(0.0, UP_LEVEL - self.h))
        if empty:
            dh -= VALVE_K * math.sqrt(max(0.0, self.h - DOWN_LEVEL))
        # comportas abertas igualam o nivel rapidamente
        if self.gate["M"] > 0.1:
            dh += 2.0 * self.gate["M"] * (UP_LEVEL - self.h)
        if self.gate["J"] > 0.1:
            dh += 2.0 * self.gate["J"] * (DOWN_LEVEL - self.h)
        self.h = max(DOWN_LEVEL, min(UP_LEVEL, self.h + dh * dt))
        self.flow = dh
        self.wave += dt * (1 + abs(dh) * 3)
        if self.gate["M"] > 0.1 and self.gate["J"] > 0.1:
            self._flag("gates", "As duas comportas abertas ao mesmo tempo: o rio de montante desce pela eclusa")
        # comportas
        for side in ("M", "J"):
            opening, closing = out["ABRE_" + side], out["FECHA_" + side]
            if opening and closing:
                self._flag("motor", "Comporta comandada para abrir e fechar ao mesmo tempo")
                continue
            old = self.gate[side]
            if opening:
                level = UP_LEVEL if side == "M" else DOWN_LEVEL
                if old < 0.05 and abs(self.h - level) > GATE_FORCE:
                    self._flag("force", "Comporta forçada contra o desnível: abra só com o nível igualado")
                    continue                        # a comporta nao abre com a pressao da agua
                self.gate[side] = min(1.0, old + dt / GATE_S)
            elif closing:
                self.gate[side] = max(0.0, old - dt / GATE_S)
                gx = GATE_M if side == "M" else GATE_J
                if any(b.x - BOAT_L < gx < b.x and b.state in ("entrando", "saindo", "parado") for b in self.boats):
                    self._flag("crush", "Comporta fechou sobre um barco")
        # barcos
        for b in self.boats:
            green = out["VERDE_M"] if b.side == "M" else out["VERDE_J"]
            if b.side == "M":
                entry_gate, exit_gate, d = GATE_M, GATE_J, 1
            else:
                entry_gate, exit_gate, d = GATE_J, GATE_M, -1
            front = b.x if d > 0 else b.x - BOAT_L
            if b.state == "chegando":
                stop = WAIT_M if d > 0 else WAIT_J + BOAT_L
                b.x = min(stop, b.x + BOAT_SPEED * dt) if d > 0 else max(stop, b.x - BOAT_SPEED * dt)
                if b.x == stop:
                    b.state = "esperando"
            elif b.state == "esperando":
                b.wait_ms += dt_ms
                self.max_wait_ms = max(self.max_wait_ms, b.wait_ms)
                if green:
                    if any(o.state in ("entrando", "na_camara") and o is not b for o in self.boats):
                        self._flag("two", "Sinal verde com outro barco na câmara")
                    b.state = "entrando"
            elif b.state in ("entrando", "saindo"):
                gate_open = self.gate["M" if (b.state == "entrando") == (d > 0) else "J"] >= 0.98
                ahead_gate = entry_gate if b.state == "entrando" else exit_gate
                nxt = b.x + d * BOAT_SPEED * dt
                nxt_front = nxt if d > 0 else nxt - BOAT_L
                crossing = (front <= ahead_gate - 2 < nxt_front) if d > 0 else (front >= ahead_gate + 2 > nxt_front)
                if crossing and not gate_open:
                    self._flag("hit", "Barco bateu na comporta: sinal verde antes de a comporta abrir toda")
                    b.state = "parado"
                    continue
                if b.state == "entrando" and ((d > 0 and nxt - BOAT_L / 2 >= PARK) or
                                              (d < 0 and nxt - BOAT_L / 2 <= PARK)):
                    b.x = PARK + BOAT_L / 2
                    b.state = "na_camara"
                    continue
                b.x = nxt
                if b.state == "saindo" and (b.x > 720 + BOAT_L or b.x < -BOAT_L):
                    b.state = "foi"
                    self.passed += 1
            elif b.state == "na_camara":
                exit_side = "J" if d > 0 else "M"
                if self.gate[exit_side] >= 0.98:
                    b.state = "saindo"
        self.boats = [b for b in self.boats if b.state != "foi"]
        if self.max_wait_ms > 150000:
            self._flag("wait", "Barco esperando mais de 2,5 minutos: a eclusa não atende os dois lados?")

    def sensors(self) -> dict[str, bool]:
        return {"IG_M": abs(self.h - UP_LEVEL) <= EQUAL_TOL, "IG_J": abs(self.h - DOWN_LEVEL) <= EQUAL_TOL,
                "M_ABERTA": self.gate["M"] >= 0.98, "M_FECHADA": self.gate["M"] <= 0.02,
                "J_ABERTA": self.gate["J"] >= 0.98, "J_FECHADA": self.gate["J"] <= 0.02,
                "ESP_M": any(b.side == "M" and b.state == "esperando" for b in self.boats),
                "ESP_J": any(b.side == "J" and b.state == "esperando" for b in self.boats)}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Câmara N0 = {self.h * 100:.0f} cm | N1 = {self.chamber_state()} | comportas: montante "
                f"{self.gate['M'] * 100:.0f}%, jusante {self.gate['J'] * 100:.0f}%",
                f"Barcos que passaram: {self.passed} | maior espera {self.max_wait_ms / 1000:.0f} s"
                + (" | Automático" if self.auto else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"BARCO_M": (14, 380, 140, 28), "BARCO_J": (566, 380, 140, 28), "AUTO": (290, 380, 140, 28)}

    def _y(self, level: float) -> float:
        return 330 - level * 22

    def _water(self, p: QPainter, x0: float, x1: float, level: float) -> None:
        top = self._y(level)
        path = QPainterPath(QPointF(x0, 330))
        n = max(2, int((x1 - x0) / 20))
        for k in range(n + 1):
            x = x0 + (x1 - x0) * k / n
            path.lineTo(x, top + math.sin(self.wave + x / 25) * 1.5)
        path.lineTo(x1, 330)
        path.closeSubpath()
        g = QLinearGradient(0, top, 0, 330)
        g.setColorAt(0, QColor("#38bdf8"))
        g.setColorAt(1, QColor("#0c4a6e"))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawPath(path)

    def _boat(self, p: QPainter, b: Boat) -> None:
        if b.x < GATE_M - 30 and b.side == "M" and b.state in ("chegando", "esperando"):
            level = UP_LEVEL
        elif b.x > GATE_J + BOAT_L + 30 and b.side == "J" and b.state in ("chegando", "esperando"):
            level = DOWN_LEVEL
        else:
            center = b.x - BOAT_L / 2
            level = UP_LEVEL if center < GATE_M else (DOWN_LEVEL if center > GATE_J else self.h)
        wl = self._y(level)
        hull = QPolygonF([QPointF(b.x - BOAT_L, wl - 8), QPointF(b.x, wl - 8), QPointF(b.x - 8, wl + 8),
                          QPointF(b.x - BOAT_L + 8, wl + 8)])
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor(b.color))
        p.drawPolygon(hull)
        draw.metal(p, QRectF(b.x - BOAT_L + 18, wl - 24, 30, 16), "#f1f5f9", 3)
        if b.state == "parado":
            draw.plate(p, QRectF(b.x - BOAT_L, wl - 44, 70, 16), "BATEU", "#b91c1c")

    def paint(self, p: QPainter) -> None:
        draw.sky(p, 720, 330, 1.0)
        out = self.out
        sens = self.sensors()
        # agua
        self._water(p, 0, GATE_M, UP_LEVEL)
        self._water(p, GATE_M, GATE_J, self.h)
        self._water(p, GATE_J, 720, DOWN_LEVEL)
        # muros e fundo
        p.fillRect(QRectF(0, 330, 720, 90), QColor("#78716c"))
        p.fillRect(QRectF(0, self._y(UP_LEVEL) - 22, 120, 22 + 6), QColor("#a8a29e"))
        p.fillRect(QRectF(GATE_M - 12, self._y(UP_LEVEL + 1.4), 24, 330 - self._y(UP_LEVEL + 1.4)), QColor("#57534e"))
        p.fillRect(QRectF(GATE_J - 12, self._y(UP_LEVEL + 1.4), 24, 330 - self._y(UP_LEVEL + 1.4)), QColor("#57534e"))
        # comportas (sobem para abrir)
        for side, gx in (("M", GATE_M), ("J", GATE_J)):
            frac = self.gate[side]
            h = 330 - self._y(UP_LEVEL + 0.6)
            r = QRectF(gx - 8, self._y(UP_LEVEL + 0.6) - frac * h * 0.95, 16, h)
            draw.metal(p, r, "#334155", 2, vertical=True)
            draw.hazard(p, QRectF(r.left(), r.top(), r.width(), 8), 5)
        # valvulas nos aquedutos
        draw.pipe(p, [QPointF(200, 318), QPointF(340, 318)], 8, self.time_ms / 15 if out.get("ENCHE") else None)
        draw.valve(p, QPointF(250, 318), 14, bool(out.get("ENCHE")))
        draw.pipe(p, [QPointF(430, 318), QPointF(570, 318)], 8, self.time_ms / 15 if out.get("ESVAZIA") else None)
        draw.valve(p, QPointF(520, 318), 14, bool(out.get("ESVAZIA")))
        # barcos
        for b in self.boats:
            self._boat(p, b)
        # semaforos
        for side, x in (("M", 200), ("J", 520)):
            post = QRectF(x - 9, 60, 18, 40)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#111827"))
            p.drawRoundedRect(post, 5, 5)
            green = out.get("VERDE_" + side, False)
            draw.lamp(p, QPointF(x, 70), 6, not green, draw.RED)
            draw.lamp(p, QPointF(x, 90), 6, green, draw.GREEN)
            draw.metal(p, QRectF(x - 2, 100, 4, 30), "#475569", 1, vertical=True)
        # etiquetas
        draw.tag(p, 8, 20, "I0.6 barco a montante", sens["ESP_M"])
        draw.tag(p, 560, 20, "I0.7 barco a jusante", sens["ESP_J"])
        draw.tag(p, 222, 64, "Q0.6", out.get("VERDE_M", False))
        draw.tag(p, 542, 64, "Q0.7", out.get("VERDE_J", False))
        draw.tag(p, GATE_M - 70, 128, "Q0.0 abre", out.get("ABRE_M", False))
        draw.tag(p, GATE_M - 70, 148, "Q0.1 fecha", out.get("FECHA_M", False))
        draw.tag(p, GATE_M + 16, 128, "I0.2", sens["M_ABERTA"])
        draw.tag(p, GATE_M + 16, 148, "I0.3", sens["M_FECHADA"])
        draw.tag(p, GATE_J - 66, 128, "Q0.2 abre", out.get("ABRE_J", False))
        draw.tag(p, GATE_J - 66, 148, "Q0.3 fecha", out.get("FECHA_J", False))
        draw.tag(p, GATE_J + 16, 128, "I0.4", sens["J_ABERTA"])
        draw.tag(p, GATE_J + 16, 148, "I0.5", sens["J_FECHADA"])
        draw.tag(p, 200, 346, "Q0.4 enchimento", out.get("ENCHE", False))
        draw.tag(p, 470, 346, "Q0.5 esvaziamento", out.get("ESVAZIA", False))
        draw.lcd(p, QRectF(325, 40, 120, 36), f"{self.h * 100:4.0f} cm", "#38bdf8", "N0 câmara")
        draw.lcd(p, QRectF(325, 82, 56, 30), str(self.chamber_state()), "#fbbf24", "N1")
        draw.tag(p, 388, 90, "I0.0 =mont.", sens["IG_M"])
        draw.tag(p, 388, 110, "I0.1 =jus.", sens["IG_J"])
        draw.text(p, 10, 50, "MONTANTE 10 m", 8, True, QColor("#0c4a6e"), w=150)
        draw.text(p, 600, 50, "JUSANTE 2 m", 8, True, QColor("#0c4a6e"), w=110)
        draw.text(p, 300, 362, f"barcos que passaram: {self.passed}", 8, True, draw.WHITE, w=200)
        draw.push_button(p, QRectF(14, 380, 140, 28), "Barco a montante", False, draw.BLUE)
        draw.push_button(p, QRectF(566, 380, 140, 28), "Barco a jusante", False, draw.BLUE)
        draw.switch(p, QRectF(290, 380, 140, 28), "Automático", self.auto)
