"""Casa de caldeiras com detectores de gas analogicos: votacao 2 de 3 degradavel, pre-alarme, purga e defeitos."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import History, approach
from ..registry import register

LEAKS = {"VAZAMENTO": 4.0, "VAZAMENTO_GRANDE": 14.0}   # %LIE/s soltos com a valvula aberta
NATURAL, LOW, HIGH = 0.03, 0.20, 0.55   # renovacao do ar (fracao/s): natural, exaustor baixa e alta
PLACE = (1.2, 1.0, 0.7)         # o gas se concentra perto dos queimadores (D1) e menos perto da porta (D3)
TAUS = (1.0, 1.5, 2.0)          # tempo de resposta dos detectores (s)
PRE, ALARM = 10.0, 20.0         # niveis de pre-alarme e alarme (%LIE)
EXPLOSIVE = 40.0                # acima disso a casa de caldeiras corre risco
GAS_LIMIT = 25.0                # valvula aberta com mais que isso (gas real) e falha da protecao
VALVE_OPEN_S, VALVE_CLOSE_S = 1.0, 0.5
FAN_S = 1.5
PURGE_MS = 30000                # exaustao alta com gas abaixo de 10% antes de reabrir
DEAD_READING = -6.0             # laco 4-20 mA aberto: leitura abaixo da faixa
DRIFT = 15.0                    # detector descalibrado soma 15% do LIE


@register
class GasDetectionEnvironment(Environment):
    id = "detector_gas"
    name = "Detecção de gás analógica (2 de 3)"
    description = ("Casa de caldeiras com três transmissores de gás 4-20 mA: a leitura em %LIE x10 chega em N0, N1 e "
                   "N2 (D1 perto dos queimadores lê mais, D3 perto da porta lê menos). Pré-alarme: 2 detectores em "
                   "10% ligam o exaustor em alta (Q0.6). Alarme: 2 de 3 em 20% fecham a válvula (energizada = "
                   "aberta), tocam a sirene até RECONHECER e travam até REARMAR; antes de reabrir é preciso purgar "
                   "30 s com exaustão alta. Defeitos: laço rompido (leitura negativa) ou descalibrado (longe da "
                   "mediana): acenda FALHA DE DETECTOR e passe a votar 1 de 2 com os bons. N3 é a mediana para o "
                   "painel.")
    example = "ambientes/detector_gas.ladproj"
    size = (720, 470)
    inputs = [
        IOPoint("RECONHECER", "I0.0", "Reconhecer", "Botão RECONHECER (silencia a sirene)", BUTTON),
        IOPoint("REARMAR", "I0.1", "Rearmar", "Botão REARMAR (libera a válvula depois da purga)", BUTTON),
        IOPoint("FLUXO", "I0.2", "Fluxo_Exaustao", "Pressostato do duto: exaustor com fluxo"),
        IOPoint("TESTE", "I0.3", "Teste_Lampadas", "Botão TESTE de lâmpadas", BUTTON),
    ]
    outputs = [
        IOPoint("EXAUSTOR", "Q0.0", "Exaustor", "Exaustor (velocidade baixa, ventilação contínua)"),
        IOPoint("VALVULA", "Q0.1", "Valvula_Gas", "Válvula de bloqueio do gás (energizada = aberta)"),
        IOPoint("SIRENE", "Q0.2", "Sirene", "Sirene de alarme"),
        IOPoint("LUZ_ALARME", "Q0.3", "Luz_Alarme", "Lâmpada ALARME DE GÁS"),
        IOPoint("LUZ_FALHA_DET", "Q0.4", "Luz_Falha_Detector", "Lâmpada FALHA DE DETECTOR"),
        IOPoint("LUZ_FALHA_EXAUST", "Q0.5", "Luz_Falha_Exaustor", "Lâmpada FALHA DO EXAUSTOR (sem fluxo)"),
        IOPoint("EXAUSTOR_ALTA", "Q0.6", "Exaustor_Alta", "Exaustor em velocidade alta (pré-alarme e purga)"),
        IOPoint("LUZ_PRE", "Q0.7", "Luz_Pre_Alarme", "Lâmpada PRÉ-ALARME"),
    ]

    def reset(self) -> None:
        self.c = 0.0
        self.reading = [0.0, 0.0, 0.0]
        self.valve = 0.0
        self.fan = 0.0
        self.fan_angle = 0.0
        self.leak = getattr(self, "leak", "")
        self.dead_d2 = getattr(self, "dead_d2", False)
        self.drift_d3 = getattr(self, "drift_d3", False)
        self.fan_broken = getattr(self, "fan_broken", False)
        self.peak = 0.0
        self.open_ms = 0
        self.explosive = False
        self.over_limit_ms = 0
        self.over_limit = False
        self.spurious = 0
        self.trips = 0
        self.need_reset = False
        self.reopened_without_reset = False
        self.no_purge = False
        self.purge_ms = 0
        self.siren_since: int | None = None
        self.siren_after_ack = False
        self.unsignalled_fan_ms = 0
        self.fan_unsignalled = False
        self.pre_without_fan_ms = 0
        self.pre_without_fan = False
        self.det_unsignalled_ms = 0
        self.det_unsignalled = False
        self.median_shown: int | None = None
        self._valve_cmd = False
        self._tripped_once = False
        self._last_press = {"RECONHECER": -10**9, "REARMAR": -10**9}
        self.trend = History(160, 250, 3)

    # ---------------------------------------------------------- operador
    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key in LEAKS:
            self.leak = "" if self.leak == key else key
        elif key == "FALHA_D2":
            self.dead_d2 = not self.dead_d2
        elif key == "FALHA_D3":
            self.drift_d3 = not self.drift_d3
        elif key == "FALHA_EXAUST":
            self.fan_broken = not self.fan_broken

    def press(self, key: str, down: bool) -> None:
        if key in ("VAZAMENTO", "VAZAMENTO_GRANDE", "FALHA_D2", "FALHA_D3", "FALHA_EXAUST"):
            self.on_control(key, down)
            return
        if down and key in self._last_press:
            self._last_press[key] = self.time_ms
        super().press(key, down)

    # ------------------------------------------------------------- leituras
    def readings(self) -> list[float]:
        """Leituras que o CLP recebe (%LIE), com os defeitos aplicados."""
        r = list(self.reading)
        if self.dead_d2:
            r[1] = DEAD_READING
        if self.drift_d3:
            r[2] += DRIFT
        return r

    def input_words(self) -> dict[int, int]:
        return {k: round(v * 10) for k, v in enumerate(self.readings())}

    def advance_words(self, n: list[int]) -> None:
        self.median_shown = n[3] if len(n) > 3 else None

    def healthy(self) -> list[int]:
        return [k for k in range(3) if not (k == 1 and self.dead_d2) and not (k == 2 and self.drift_d3)]

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        for key in self._last_press:
            if self.is_pressed(key):
                self._last_press[key] = now
        cmd = out["VALVULA"]
        self.valve = approach(self.valve, 1.0 if cmd else 0.0, 1 / VALVE_OPEN_S, 1 / VALVE_CLOSE_S, dt)
        target = 0.0
        if not self.fan_broken:
            target = 1.0 if out["EXAUSTOR_ALTA"] else (LOW / HIGH if out["EXAUSTOR"] else 0.0)
        self.fan = approach(self.fan, target, 1 / FAN_S, 1 / FAN_S, dt)
        self.fan_angle += self.fan * 22 * dt
        source = LEAKS.get(self.leak, 0.0) * self.valve
        self.c = max(0.0, self.c + (source - self.c * (NATURAL + HIGH * self.fan)) * dt)
        self.peak = max(self.peak, self.c)
        for k in range(3):
            self.reading[k] += (self.c * PLACE[k] - self.reading[k]) * min(1.0, dt / TAUS[k])
        if self.valve >= 0.9:
            self.open_ms += dt_ms
        if self.c >= EXPLOSIVE and self.valve > 0.1:
            self.explosive = True
        self.over_limit_ms = self.over_limit_ms + dt_ms if (self.c >= GAS_LIMIT and self.valve > 0.5) else 0
        if self.over_limit_ms > 1500:
            self.over_limit = True
        good = [self.reading[k] for k in self.healthy()]
        # purga: exaustao alta com o gas real abaixo de 10%
        self.purge_ms = self.purge_ms + dt_ms if (self.fan >= 0.9 and self.c < PRE) else 0
        if self._valve_cmd and not cmd:                       # a valvula fechou
            if self.c >= PRE or sum(v >= ALARM for v in good) >= 1:
                self.trips += 1
                self.need_reset = True
                self._tripped_once = True
            elif self.c < PRE:
                self.spurious += 1
        if cmd and not self._valve_cmd:                       # a valvula reabriu
            if self.need_reset and now - self._last_press["REARMAR"] > 1500:
                self.reopened_without_reset = True
            if self._tripped_once and self.purge_ms < PURGE_MS - 3000:
                self.no_purge = True
            self.need_reset = False
        self._valve_cmd = cmd
        if out["SIRENE"]:
            if self.siren_since is None:
                self.siren_since = now
            ack = self._last_press["RECONHECER"]
            if ack >= self.siren_since and now - ack > 2000:
                self.siren_after_ack = True
        else:
            self.siren_since = None
        no_flow = (out["EXAUSTOR"] or out["EXAUSTOR_ALTA"]) and not self.sensors()["FLUXO"] and \
            not out["LUZ_FALHA_EXAUST"]
        self.unsignalled_fan_ms = self.unsignalled_fan_ms + dt_ms if no_flow else 0
        if self.unsignalled_fan_ms > 6000:
            self.fan_unsignalled = True
        pre = sum(v >= PRE for v in good) >= min(2, len(good))
        self.pre_without_fan_ms = self.pre_without_fan_ms + dt_ms if (pre and cmd and not out["EXAUSTOR_ALTA"]) else 0
        if self.pre_without_fan_ms > 3000:
            self.pre_without_fan = True
        faulty = self.dead_d2 or self.drift_d3
        self.det_unsignalled_ms = self.det_unsignalled_ms + dt_ms if (faulty and not out["LUZ_FALHA_DET"]) else 0
        if self.det_unsignalled_ms > 15000:
            self.det_unsignalled = True
        self.trend.add(dt_ms, *self.readings())

    def sensors(self) -> dict[str, bool]:
        return {"FLUXO": self.fan >= 0.3}

    def alarms(self) -> list[str]:
        out = []
        if self.explosive:
            out.append("PERIGO: concentração explosiva com a válvula de gás aberta")
        if self.over_limit:
            out.append(f"A válvula ficou aberta com mais de {GAS_LIMIT:.0f}% do LIE: com um detector em defeito "
                       "vote 1 de 2 com os que sobram")
        if self.spurious:
            out.append("Parada indevida: a válvula fechou sem gás (um detector sozinho ou com defeito não pode "
                       "disparar)")
        if self.reopened_without_reset:
            out.append("A válvula reabriu sozinha depois do disparo: exija o botão REARMAR")
        if self.no_purge:
            out.append("A válvula reabriu sem 30 s de purga com o exaustor em alta")
        if self.siren_after_ack:
            out.append("A sirene continua tocando depois do RECONHECER")
        if self.fan_unsignalled:
            out.append("Exaustor comandado sem fluxo no duto e sem a lâmpada de falha do exaustor")
        if self.pre_without_fan:
            out.append("Pré-alarme (2 detectores em 10%) sem o exaustor em alta")
        if self.det_unsignalled:
            out.append("Detector com defeito (leitura fora da faixa ou longe dos outros) sem a lâmpada FALHA DE "
                       "DETECTOR")
        return out

    def stats(self) -> list[str]:
        total = max(1, self.time_ms)
        faults = [n for n, f in (("D2 laço aberto", self.dead_d2), ("D3 descalibrado", self.drift_d3),
                                 ("exaustor quebrado", self.fan_broken)) if f]
        r = self.readings()
        return [f"Gás real: {self.c:.1f}% do LIE (pico {self.peak:.1f}%) | N0..N2: "
                + ", ".join(f"{v * 10:.0f}" for v in r),
                f"Produção (válvula aberta): {100 * self.open_ms / total:.0f}% do tempo | disparos: {self.trips}"
                + (f" | defeitos: {', '.join(faults)}" if faults else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"RECONHECER": (14, 300, 132, 28), "REARMAR": (14, 334, 132, 28), "TESTE": (14, 368, 132, 28),
                "VAZAMENTO": (574, 262, 136, 26), "VAZAMENTO_GRANDE": (574, 292, 136, 26),
                "FALHA_D2": (574, 330, 136, 26), "FALHA_D3": (574, 360, 136, 26), "FALHA_EXAUST": (574, 390, 136, 26)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 470)
        out = self.out
        sens = self.sensors()
        test = self.is_pressed("TESTE")
        # sala
        room = QRectF(160, 40, 360, 250)
        draw.shadow(p, room, 4, 4)
        p.setPen(QPen(QColor("#334155"), 4))
        g = QLinearGradient(room.topLeft(), room.bottomLeft())
        g.setColorAt(0, QColor("#f8fafc"))
        g.setColorAt(1, QColor("#e2e8f0"))
        p.setBrush(g)
        p.drawRect(room)
        p.fillRect(QRectF(room.left(), room.bottom() - 14, room.width(), 14), QColor("#94a3b8"))
        # caldeiras e queimadores
        for k in range(2):
            b = QRectF(186 + k * 120, 130, 90, 140)
            draw.shadow(p, b, 8, 3)
            draw.metal(p, b, "#64748b", 8, vertical=True)
            draw.ctext(p, b.center().x(), b.top() + 16, f"CALDEIRA {k + 1}", 6.5, True, draw.WHITE, 90)
            fire = QRectF(b.left() + 20, b.bottom() - 52, 50, 36)
            p.setPen(QPen(QColor("#1e293b"), 1))
            p.setBrush(QColor("#0f172a"))
            p.drawRoundedRect(fire, 6, 6)
            if self.valve > 0.2:
                for j in range(4):
                    h = (18 + 8 * math.sin(self.time_ms / 90 + j * 1.7 + k)) * self.valve
                    fl = QRadialGradient(QPointF(fire.left() + 10 + j * 10, fire.bottom() - 4), h)
                    fl.setColorAt(0, QColor("#fde68a"))
                    fl.setColorAt(0.5, QColor("#f97316"))
                    fl.setColorAt(1, QColor(239, 68, 68, 0))
                    p.setPen(Qt.NoPen)
                    p.setBrush(fl)
                    p.drawEllipse(QPointF(fire.left() + 10 + j * 10, fire.bottom() - 6), 6, h * 0.8)
        # linha de gas e valvula
        draw.pipe(p, [QPointF(230, 318), QPointF(539, 318)], 7, None, color="#facc15")
        draw.pipe(p, [QPointF(230, 318), QPointF(230, 272)], 6, (self.time_ms / 25) if self.valve > 0.2 else None,
                  QColor("#fde047"), "#facc15")
        draw.pipe(p, [QPointF(350, 318), QPointF(350, 272)], 6, (self.time_ms / 25) if self.valve > 0.2 else None,
                  QColor("#fde047"), "#facc15")
        draw.valve(p, QPointF(548, 318), 18, self.valve > 0.5)
        draw.pipe(p, [QPointF(557, 318), QPointF(566, 318)], 7, None, color="#facc15")
        draw.text(p, 380, 304, "GÁS NATURAL →", 7, True, QColor("#a16207"), w=100)
        draw.tag(p, 470, 304, "Q0.1", out.get("VALVULA", False))
        # nuvem de gas (mais densa perto dos queimadores)
        if self.c > 0.3:
            cloud = QRadialGradient(QPointF(260, 220), 260)
            a = int(min(190, self.c * 5))
            cloud.setColorAt(0, QColor(250, 204, 21, a))
            cloud.setColorAt(1, QColor(250, 204, 21, int(a * 0.35)))
            p.fillRect(room.adjusted(3, 3, -3, -3), cloud)
        # exaustor no teto com duto
        fc = QPointF(500, 40)
        draw.pipe(p, [QPointF(500, 30), QPointF(500, 12), QPointF(560, 12)], 22, None, color="#cbd5e1")
        draw.fan(p, fc, 22, self.fan_angle, self.fan > 0.1)
        if self.fan > 0.1:
            for j in range(3):
                x = 560 + ((self.time_ms / 8 * self.fan + j * 18) % 50)
                draw.harrow(p, QPointF(x, 12), 8, True, True, QColor("#0ea5e9"))
        draw.tag(p, 528, 52, "Q0.0 baixa", out.get("EXAUSTOR", False))
        draw.tag(p, 528, 72, "Q0.6 alta", out.get("EXAUSTOR_ALTA", False))
        draw.tag(p, 528, 92, "I0.2 fluxo", sens["FLUXO"])
        # detectores na parede
        r = self.readings()
        for k, (x, y) in enumerate(((186, 74), (300, 74), (414, 96))):
            body = QRectF(x - 14, y - 14, 28, 34)
            draw.shadow(p, body, 4, 2)
            draw.metal(p, body, "#e2e8f0", 4)
            v = r[k]
            bad = (k == 1 and self.dead_d2) or (k == 2 and self.drift_d3)
            led = draw.RED if v >= ALARM else (draw.AMBER if v >= PRE else draw.GREEN)
            if v < -1:
                led = QColor("#a855f7")
            draw.lamp(p, QPointF(x, y - 4), 4.5, True, led)
            draw.ctext(p, x, y + 12, f"D{k + 1}", 6.5, True, draw.INK, 30)
            draw.lcd(p, QRectF(x + 18, y - 12, 54, 30), f"{v:5.1f}", "#fbbf24" if not bad else "#c084fc", f"N{k}")
        # painel do operador
        draw.card(p, QRectF(14, 14, 132, 280), "Painel")
        lamps = (("ALARME Q0.3", out.get("LUZ_ALARME", False), draw.RED),
                 ("PRÉ Q0.7", out.get("LUZ_PRE", False), draw.AMBER),
                 ("DETECTOR Q0.4", out.get("LUZ_FALHA_DET", False), QColor("#a855f7")),
                 ("EXAUSTOR Q0.5", out.get("LUZ_FALHA_EXAUST", False), draw.AMBER))
        for k, (label, on, col) in enumerate(lamps):
            draw.lamp(p, QPointF(30, 50 + k * 26), 7, on, col)
            draw.text(p, 44, 50 + k * 26, label, 7, True, w=100)
        draw.text(p, 24, 160, "Sirene Q0.2", 7, True, draw.MUTED)
        if out.get("SIRENE"):
            for j in range(3):
                p.setPen(QPen(draw.RED, 2))
                p.setBrush(Qt.NoBrush)
                rr = 6 + j * 5 + (self.time_ms / 60) % 5
                p.drawArc(QRectF(100 - rr, 160 - rr, 2 * rr, 2 * rr), -45 * 16, 90 * 16)
        median = "--" if self.median_shown is None else f"{self.median_shown / 10:.1f}"
        draw.lcd(p, QRectF(24, 178, 112, 40), median, "#4ade80", "MEDIANA N3 (%LIE)")
        draw.text(p, 24, 234, f"Gás real {self.c:.1f}%", 7.5, True, draw.INK)
        purge = min(1.0, self.purge_ms / PURGE_MS)
        draw.text(p, 24, 254, "Purga", 7, True, draw.MUTED)
        draw.bar(p, QRectF(24, 264, 112, 8), purge, draw.CYAN)
        draw.push_button(p, QRectF(14, 300, 132, 28), "RECONHECER I0.0", self.is_pressed("RECONHECER"), draw.AMBER)
        draw.push_button(p, QRectF(14, 334, 132, 28), "REARMAR I0.1", self.is_pressed("REARMAR"), draw.GREEN)
        draw.push_button(p, QRectF(14, 368, 132, 28), "TESTE I0.3", test, QColor("#64748b"))
        # tendencia
        draw.trend(p, QRectF(160, 336, 400, 124),
                   [(self.trend.series(0), "#dc2626"), (self.trend.series(1), "#2563eb"),
                    (self.trend.series(2), "#16a34a")], -10, 40,
                   "Tendência: D1 (vermelho), D2 (azul), D3 (verde) em %LIE",
                   [(PRE, "#f59e0b"), (ALARM, "#dc2626"), (0, "#94a3b8")], 160)
        # defeitos
        draw.card(p, QRectF(568, 236, 146, 186), "Simulação")
        draw.switch(p, QRectF(574, 262, 136, 26), "Vazamento", self.leak == "VAZAMENTO")
        draw.switch(p, QRectF(574, 292, 136, 26), "Vazamento grande", self.leak == "VAZAMENTO_GRANDE")
        draw.switch(p, QRectF(574, 330, 136, 26), "D2 laço aberto", self.dead_d2)
        draw.switch(p, QRectF(574, 360, 136, 26), "D3 descalibrado", self.drift_d3)
        draw.switch(p, QRectF(574, 390, 136, 26), "Exaustor quebrado", self.fan_broken)
