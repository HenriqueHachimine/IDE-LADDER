"""Forno de tratamento termico: perfil de rampa e patamar, aquecimento proporcional ao tempo e porta travada."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QRadialGradient

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..physics import History
from ..registry import register

AMBIENT = 25.0
BANK_HEAT = 8.0               # degC/s que cada banco de resistencias aquece o forno frio (a plena carga)
ELEMENT_TAU = 3.0             # s: as resistencias levam tempo para esquentar e esfriar
K_LOSS = 0.004                # perdas pelas paredes (1/s)
K_FAN = 0.025                 # resfriamento com o ventilador (1/s)
K_DOOR = 0.05                 # porta aberta (1/s)
THERMOSTAT = 950.0            # termostato de seguranca (independente do CLP)
MAX_RATE = 15.0               # degC/s: acima disso, choque termico na peca
SOAK = (840.0, 870.0)         # faixa do patamar de tempera
SOAK_MS = 25000               # tempo minimo no patamar
DOOR_SAFE = 200.0             # so abre abaixo de 200 degC
DOOR_S = 2.0
TRACK_TOL, TRACK_MS = 40.0, 10000
TEMP_WORD, SP_WORD = 0, 1


def glow(t: float) -> QColor:
    """Cor de incandescencia aproximada para a temperatura (degC)."""
    stops = [(25, QColor("#334155")), (450, QColor("#4c0519")), (600, QColor("#991b1b")), (750, QColor("#dc2626")),
             (850, QColor("#f97316")), (950, QColor("#fbbf24"))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if t <= b:
            return draw.mix(ca, cb, (t - a) / (b - a))
    return stops[-1][1]


@register
class FurnaceEnvironment(Environment):
    id = "forno_rampa"
    name = "Forno com rampa e patamar"
    description = ("Forno de têmpera. O termopar chega em N0 (°C) e o programa escreve o setpoint do perfil em N1: "
                   "rampa a 10 °C/s até 600 °C, patamar de 20 s, rampa a 5 °C/s até 850 °C, patamar de 30 s e "
                   "resfriamento controlado a 8 °C/s até 300 °C com o ventilador (também proporcional ao tempo). Dois bancos de resistências, que "
                   "esquentam e esfriam devagar: use controle proporcional ao tempo (liga uma fração de cada ciclo de "
                   "1 s). A peça só fica boa com 25 s entre 840 e 870 °C e sem mudar mais que 15 °C/s. A porta só "
                   "pode abrir abaixo de 200 °C (trava energizada = travada); o termostato de segurança (NF) abre em "
                   "950 °C.")
    example = "ambientes/forno_rampa.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("START", "I0.0", "Partida", "Botão PARTIDA do ciclo (NA)", BUTTON),
        IOPoint("STOP", "I0.1", "Parada", "Botão PARADA (NF: lê 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("FECHADA", "I0.2", "Porta_Fechada", "Porta fechada"),
        IOPoint("TERMOSTATO", "I0.3", "Termostato", "Termostato de segurança (NF: lê 0 acima de 950 °C)",
                normally_closed=True),
        IOPoint("FLUXO", "I0.4", "Fluxo_Ventilador", "Pressostato: ventilador com fluxo"),
    ]
    outputs = [
        IOPoint("R1", "Q0.0", "Resistencia_1", "Banco de resistências 1"),
        IOPoint("R2", "Q0.1", "Resistencia_2", "Banco de resistências 2"),
        IOPoint("FAN", "Q0.2", "Ventilador", "Ventilador de resfriamento"),
        IOPoint("TRAVA", "Q0.3", "Trava_Porta", "Trava da porta (energizada = travada)"),
        IOPoint("CICLO", "Q0.4", "Lampada_Ciclo", "Lâmpada CICLO EM ANDAMENTO"),
        IOPoint("FIM", "Q0.5", "Lampada_Fim", "Lâmpada FIM DE CICLO (pode abrir)"),
        IOPoint("ALARME", "Q0.6", "Lampada_Alarme", "Lâmpada ALARME"),
    ]

    def reset(self) -> None:
        self.T = AMBIENT
        self.power = [0.0, 0.0]
        self.door = 0.0                           # 0 fechada, 1 aberta
        self.want_open = getattr(self, "want_open", False)
        self.piece = True
        self.sp: int | None = None
        self.flags: dict[str, str] = {}
        self.soak_ms = 0
        self.max_rate = 0.0
        self._rate_buf: list[float] = []
        self.track_ms = 0
        self.good = self.bad = 0
        self.result = ""
        self.cycle_seen = False
        self.trend = History(240, 1000, 2)
        self.fan_angle = 0.0
        self.fan_broken = getattr(self, "fan_broken", False)

    # ------------------------------------------------------- registradores
    def input_words(self) -> dict[int, int]:
        return {TEMP_WORD: round(self.T)}

    def advance_words(self, n: list[int]) -> None:
        self.sp = n[SP_WORD] if len(n) > SP_WORD else None

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "PORTA":
            self.want_open = not self.want_open
        elif key == "FALHA_FAN":
            self.fan_broken = not self.fan_broken

    def press(self, key: str, down: bool) -> None:
        if key in ("PORTA", "FALHA_FAN"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        old_t = self.T
        # porta: o operador puxa; so abre destravada
        if self.want_open and not out["TRAVA"]:
            self.door = min(1.0, self.door + dt / DOOR_S)
        elif not self.want_open:
            self.door = max(0.0, self.door - dt / DOOR_S)
        if self.door > 0.05 and self.T > DOOR_SAFE:
            self.flags.setdefault("hot_door", "A porta abriu com o forno acima de 200 °C: mantenha a trava (Q0.3)")
        if self.door > 0.05 and (out["R1"] or out["R2"]):
            self.flags.setdefault("door_heat", "Resistências ligadas com a porta aberta")
        thermostat_ok = self.T < THERMOSTAT
        for k, key in enumerate(("R1", "R2")):
            on = out[key] and thermostat_ok
            self.power[k] += ((1.0 if on else 0.0) - self.power[k]) * min(1.0, dt / ELEMENT_TAU)
        fan = out["FAN"] and not self.fan_broken
        if fan:
            self.fan_angle += 20 * dt
        heat = BANK_HEAT * (self.power[0] + self.power[1])
        loss = (self.T - AMBIENT) * (K_LOSS + (K_FAN if fan else 0.0) + K_DOOR * self.door)
        self.T += (heat - loss) * dt
        if self.T >= THERMOSTAT + 5:
            self.flags.setdefault("over", "Sobretemperatura: o termostato de segurança desligou as resistências")
        # taxa de variacao (media de 1 s) e qualidade da peca
        self._rate_buf.append((self.T - old_t) / dt if dt else 0.0)
        self._rate_buf = self._rate_buf[-100:]
        if len(self._rate_buf) >= 100:
            rate = abs(sum(self._rate_buf) / len(self._rate_buf))
            if self.piece and self.door < 0.05:
                self.max_rate = max(self.max_rate, rate)
            if rate > MAX_RATE and self.piece:
                self.flags.setdefault("rate", "Choque térmico: a temperatura mudou mais de 15 °C/s")
        if self.piece and SOAK[0] <= self.T <= SOAK[1]:
            self.soak_ms += dt_ms
        if out["CICLO"]:
            self.cycle_seen = True
            if self.sp is not None:
                self.track_ms = self.track_ms + dt_ms if abs(self.T - self.sp) > TRACK_TOL else 0
                if self.track_ms > TRACK_MS:
                    self.flags.setdefault("track", "A temperatura não acompanha o setpoint do perfil (N1)")
        # peca sai quando a porta abre depois de um ciclo
        if self.door >= 0.95 and self.piece and self.cycle_seen:
            ok = self.soak_ms >= SOAK_MS and self.max_rate <= MAX_RATE and "over" not in self.flags
            self.good += ok
            self.bad += not ok
            self.result = "BOA" if ok else "REPROVADA"
            self.piece = False
        if self.door <= 0.05 and not self.piece and self.T < DOOR_SAFE:
            self.piece, self.soak_ms, self.max_rate, self.cycle_seen = True, 0, 0.0, False   # nova peca carregada
        self.trend.add(dt_ms, self.T, self.sp if self.sp is not None else 0)

    def sensors(self) -> dict[str, bool]:
        return {"FECHADA": self.door <= 0.02, "TERMOSTATO": self.T >= THERMOSTAT,
                "FLUXO": bool(self.out.get("FAN")) and not self.fan_broken}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        sp = "--" if self.sp is None else f"{self.sp} °C"
        return [f"Forno N0 = {self.T:.0f} °C | setpoint N1 = {sp} | resistências {self.power[0] * 100:.0f}% e "
                f"{self.power[1] * 100:.0f}%",
                f"Patamar: {self.soak_ms / 1000:.0f} s de 25 | maior taxa {self.max_rate:.1f} °C/s | peças boas "
                f"{self.good}, reprovadas {self.bad}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"START": (14, 330, 130, 28), "STOP": (14, 364, 130, 28), "PORTA": (14, 410, 130, 30),
                "FALHA_FAN": (150, 410, 160, 30)}

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        draw.ground(p, 400, 720, 460)
        out = self.out
        sens = self.sensors()
        # carcaca do forno
        body = QRectF(170, 70, 280, 300)
        draw.shadow(p, body, 10, 6)
        draw.metal(p, body, "#475569", 10, vertical=True)
        cavity = QRectF(200, 130, 220, 200)
        g = QRadialGradient(cavity.center(), 160)
        c = glow(self.T)
        g.setColorAt(0, c.lighter(130))
        g.setColorAt(1, c.darker(140))
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.setBrush(g)
        p.drawRect(cavity)
        # resistencias (serpentinas nas paredes)
        for k, x in enumerate((cavity.left() + 10, cavity.right() - 10)):
            col = glow(AMBIENT + 900 * self.power[k])
            p.setPen(QPen(col, 4, Qt.SolidLine, Qt.RoundCap))
            for j in range(9):
                y = cavity.top() + 14 + j * 20
                p.drawLine(QPointF(x - 6, y), QPointF(x + 6, y + 10))
                p.drawLine(QPointF(x + 6, y + 10), QPointF(x - 6, y + 20))
            draw.tag(p, x - 26 if k == 0 else x - 20, cavity.bottom() + 16, f"Q0.{k} R{k + 1}", out.get(f"R{k + 1}", False))
        # peca
        if self.piece:
            pc = QRectF(cavity.center().x() - 50, cavity.bottom() - 46, 100, 30)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(glow(self.T).lighter(110) if self.T > 450 else QColor("#64748b"))
            p.drawRoundedRect(pc, 4, 4)
        # porta (sobe)
        door = QRectF(cavity.left() - 6, cavity.top() - 6 - 200 * self.door, cavity.width() + 12, cavity.height() + 12)
        p.save()
        p.setClipRect(QRectF(0, 0, 720, cavity.bottom() + 6))
        draw.metal(p, door, "#64748b", 4, vertical=True)
        window = door.adjusted(40, 40, -40, -60)
        wg = QRadialGradient(window.center(), window.width() * 0.7)
        wg.setColorAt(0, glow(self.T).lighter(140))
        wg.setColorAt(1, glow(self.T).darker(130))
        p.setPen(QPen(QColor("#1e293b"), 3))
        p.setBrush(wg)
        p.drawRoundedRect(window, 6, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 40))
        p.drawRect(QRectF(window.left() + 8, window.top() + 6, 10, window.height() - 12))
        p.restore()
        lock = QRectF(body.right() - 26, body.top() + 16, 18, 24)
        draw.metal(p, lock, "#16a34a" if not out.get("TRAVA") else "#b91c1c", 3)
        draw.tag(p, body.left(), body.bottom() + 16, "Q0.3 trava", out.get("TRAVA", False))
        draw.tag(p, body.left() + 90, body.bottom() + 16, "I0.2 fechada", sens["FECHADA"])
        # ventilador
        fc = QPointF(body.center().x(), body.top() + 28)
        draw.fan(p, fc, 20, self.fan_angle, bool(out.get("FAN")) and not self.fan_broken)
        draw.tag(p, body.left() + 8, body.top() + 16, "Q0.2 ventilador", out.get("FAN", False))
        draw.tag(p, body.left() + 8, body.top() + 38, "I0.4 fluxo", sens["FLUXO"])
        # termopar e termostato
        draw.lcd(p, QRectF(470, 70, 110, 40), f"{self.T:4.0f}", "#fb923c", "N0 °C")
        sp = "--" if self.sp is None else f"{self.sp}"
        draw.lcd(p, QRectF(590, 70, 110, 40), sp, "#4ade80", "N1 setpoint")
        draw.tag(p, 470, 124, "I0.3 termostato 950 °C", not sens["TERMOSTATO"])
        # grafico do perfil
        chart = QRectF(466, 140, 244, 200)
        draw.trend(p, chart, [(self.trend.series(1), "#16a34a"), (self.trend.series(0), "#ea580c")], 0, 1000,
                   "Perfil: setpoint (verde) e forno (laranja)", [(SOAK[0], "#fdba74"), (SOAK[1], "#fdba74")], 240)
        # resultado
        draw.card(p, QRectF(466, 348, 244, 52))
        soak = min(1.0, self.soak_ms / SOAK_MS)
        draw.text(p, 476, 364, f"Patamar 840-870 °C: {self.soak_ms / 1000:.0f}/25 s", 7.5, True, w=220)
        draw.bar(p, QRectF(476, 376, 224, 8), soak, draw.GREEN if soak >= 1 else draw.AMBER)
        draw.text(p, 476, 392, f"Peças boas {self.good} | reprovadas {self.bad}" +
                  (f" | última: {self.result}" if self.result else ""), 7, False, draw.MUTED, w=230)
        # painel
        draw.card(p, QRectF(8, 70, 150, 250), "Painel")
        lamps = (("CICLO Q0.4", "CICLO", draw.GREEN), ("FIM Q0.5", "FIM", draw.BLUE), ("ALARME Q0.6", "ALARME", draw.RED))
        for k, (label, key, col) in enumerate(lamps):
            draw.lamp(p, QPointF(26, 106 + k * 28), 8, out.get(key, False), col)
            draw.text(p, 40, 106 + k * 28, label, 7.5, True, w=110)
        draw.text(p, 18, 200, f"Taxa máx. {self.max_rate:.1f} °C/s", 7.5, True, w=140)
        draw.text(p, 18, 220, "Limite 15 °C/s", 7, False, draw.MUTED, w=140)
        draw.text(p, 18, 246, "Porta: " + ("aberta" if self.door > 0.9 else "fechada" if self.door < 0.05 else "movendo"),
                  7.5, True, w=140)
        draw.push_button(p, QRectF(14, 330, 130, 28), "PARTIDA I0.0", self.is_pressed("START"), draw.GREEN)
        draw.push_button(p, QRectF(14, 364, 130, 28), "PARADA I0.1", self.is_pressed("STOP"), draw.RED)
        draw.switch(p, QRectF(14, 410, 130, 30), "Abrir porta", self.want_open)
        draw.switch(p, QRectF(150, 410, 160, 30), "Ventilador quebrado", self.fan_broken)
