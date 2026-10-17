"""Linha de garrafas: enchimento por tempo, inspecao de nivel com rejeitor e encaixotamento de 6 em 6."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

BELT_Y = 200.0          # topo da esteira de garrafas
BELT_END = 470.0        # garrafas caem na caixa ao passar daqui
BW = 24.0               # largura da garrafa (px)
SPACING = 60.0
BELT_SPEED, BELT_ACCEL, BELT_DECEL = 60.0, 300.0, 400.0     # px/s, px/s^2 (para em ~4,5 px)
FILL_X = 180.0          # eixo do bico de enchimento
EYE_X = FILL_X + BW / 2 - 4.0                              # feixe: a garrafa interrompe ao chegar sob o bico
NOZZLE_MARGIN = 7.0     # bico precisa estar sobre a boca da garrafa
FLOW = 0.25             # L/s (tanque pressurizado: vazao constante)
VALVE_OPEN_S, VALVE_CLOSE_S = 0.10, 0.08
INSP_X = 330.0          # ponto de inspecao de nivel / rejeitor
INSP_WINDOW = 12.0
PUSH_WINDOW = 16.0
PUSH_S = 0.2            # cilindro estende/recolhe em 0,2 s
LEVEL_OK = (0.92, 1.03)  # faixa aceita pela inspecao (fracao da capacidade)
BOX_Y = 330.0           # topo da esteira de caixas
DROP_X = 492.0          # centro da boca da caixa sob o fim da esteira de garrafas
BOX_W, BOX_SPACING = 84.0, 130.0
BOX_SPEED, BOX_ACCEL, BOX_DECEL = 80.0, 300.0, 500.0       # para em ~6,4 px
BOX_WINDOW = 10.0       # sensor de caixa posicionada (+-10 px)
PER_BOX = 6
DROP_PULSE_MS = 200     # tempo que a garrafa em queda interrompe o sensor da caixa


@dataclass
class Bottle:
    x: float                # centro
    large: bool
    liters: float = 0.0

    @property
    def capacity(self) -> float:
        return 1.0 if self.large else 0.5

    @property
    def fraction(self) -> float:
        return self.liters / self.capacity

    @property
    def level_ok(self) -> bool:
        return LEVEL_OK[0] <= self.fraction <= LEVEL_OK[1]


@dataclass
class Box:
    x: float                # centro
    bottles: int = 0
    bad: int = 0


@register
class BottleLineEnvironment(Environment):
    id = "garrafas"
    name = "Linha de garrafas"
    description = ("A esteira para com a garrafa sob o bico (fotocelula I0.2) e enche por tempo: 0,25 L/s, "
                   "garrafa pequena 0,5 L e grande 1 L (chave I0.5). A inspecao (I0.4/I0.3) aceita 92% a "
                   "103% do volume; garrafa fora do nivel deve ser empurrada para o refugo pelo rejeitor. No fim, "
                   "as garrafas caem na caixa (sensor I0.6 conta cada uma); com 6 garrafas a esteira de caixas "
                   "leva a caixa e traz a proxima (I0.7 = caixa posicionada).")
    example = "ambientes/garrafas.ladproj"
    inputs = [
        IOPoint("START", "I0.0", "Start", "Botao de partida (NA)", BUTTON),
        IOPoint("STOP", "I0.1", "Stop", "Botao de parada (NF: le 1 quando solto)", BUTTON, normally_closed=True),
        IOPoint("AT_FILL", "I0.2", "Garrafa_No_Bico", "Fotocelula: garrafa sob o bico de enchimento"),
        IOPoint("LEVEL_OK", "I0.3", "Nivel_OK", "Inspecao: garrafa no ponto com nivel entre 92% e 103%"),
        IOPoint("AT_INSP", "I0.4", "Garrafa_Inspecao", "Fotocelula: garrafa no ponto de inspecao/rejeitor"),
        IOPoint("LARGE", "I0.5", "Seletor_Grande", "Chave: 1 = garrafas grandes (1 L), 0 = pequenas (0,5 L)",
                SWITCH),
        IOPoint("DROP", "I0.6", "Garrafa_Na_Caixa", "Sensor na boca da caixa: pulso a cada garrafa que cai"),
        IOPoint("BOX_OK", "I0.7", "Caixa_Posicionada", "Caixa vazia alinhada sob o fim da esteira"),
    ]
    outputs = [
        IOPoint("BELT", "Q0.0", "Esteira_Garrafas", "Motor da esteira de garrafas"),
        IOPoint("VALVE", "Q0.1", "Valvula_Enchimento", "Valvula do bico de enchimento"),
        IOPoint("PUSH", "Q0.2", "Rejeitor", "Cilindro que empurra a garrafa para o refugo"),
        IOPoint("BOXBELT", "Q0.3", "Esteira_Caixas", "Motor da esteira de caixas"),
        IOPoint("RUN", "Q0.4", "Lampada_Run", "Lampada RUN"),
    ]

    def reset(self) -> None:
        large = self.is_pressed("LARGE")
        self.bottles = [Bottle(FILL_X - 150 - k * SPACING, large) for k in range(4)]
        self.boxes = [Box(DROP_X), Box(DROP_X - BOX_SPACING)]
        self.belt_v = 0.0
        self.box_v = 0.0
        self.belt_pos = 0.0
        self.valve = 0.0
        self.push = 0.0
        self.spilled = 0.0
        self.overflowed = 0
        self.broken = 0
        self.bad_packed = 0
        self.good_rejected = 0
        self.scrap = 0
        self.packed_small = 0
        self.packed_large = 0
        self.boxes_shipped = 0
        self.boxes_incomplete = 0
        self.box_overfull = 0
        self.drop_ms = 0
        self.scrap_anim: list[list[float]] = []

    # ------------------------------------------------------------- fisica
    def bottle_at(self, x: float, window: float) -> Bottle | None:
        return next((b for b in self.bottles if abs(b.x - x) <= window), None)

    def box_ready(self) -> Box | None:
        return next((b for b in self.boxes if abs(b.x - DROP_X) <= BOX_WINDOW), None)

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        # esteira de garrafas
        self.belt_v = approach(self.belt_v, BELT_SPEED if out["BELT"] else 0.0, BELT_ACCEL, BELT_DECEL, dt)
        d = self.belt_v * dt
        self.belt_pos += d
        for b in self.bottles:
            b.x += d
        if self.belt_v == 0.0:                   # troca de produto: com a linha parada o operador
            large = self.is_pressed("LARGE")     # troca as garrafas vazias que ainda vao ao bico
            for b in self.bottles:
                if b.liters == 0.0 and b.x < FILL_X - BW:
                    b.large = large
        while min(b.x for b in self.bottles) > -BW:
            self.bottles.append(Bottle(min(b.x for b in self.bottles) - SPACING, self.is_pressed("LARGE")))
        # enchimento
        self.valve = approach(self.valve, 1.0 if out["VALVE"] else 0.0, 1 / VALVE_OPEN_S, 1 / VALVE_CLOSE_S, dt)
        flow = FLOW * self.valve * dt
        if flow:
            target = self.bottle_at(FILL_X, NOZZLE_MARGIN)
            if target is None:
                self.spilled += flow
            else:
                before = target.fraction
                target.liters += flow
                if target.fraction > 1.08 and before <= 1.08:
                    self.overflowed += 1
        # rejeitor
        self.push = approach(self.push, 1.0 if out["PUSH"] else 0.0, 1 / PUSH_S, 1 / PUSH_S, dt)
        if self.push >= 0.8:
            hit = self.bottle_at(INSP_X, PUSH_WINDOW)
            if hit is not None:
                self.bottles.remove(hit)
                self.scrap += 1
                if hit.level_ok:
                    self.good_rejected += 1
                self.scrap_anim.append([INSP_X, 0.0])
        for a in self.scrap_anim:
            a[1] += dt
        self.scrap_anim = [a for a in self.scrap_anim if a[1] < 0.6]
        # queda na caixa
        self.drop_ms = max(0, self.drop_ms - dt_ms)
        for b in [b for b in self.bottles if b.x > BELT_END]:
            self.bottles.remove(b)
            self.drop_ms = DROP_PULSE_MS
            box = self.box_ready()
            if box is None:
                self.broken += 1
                continue
            box.bottles += 1
            if box.bottles == PER_BOX + 1:
                self.box_overfull += 1
            if not b.level_ok:
                box.bad += 1
                self.bad_packed += 1
            elif b.large:
                self.packed_large += 1
            else:
                self.packed_small += 1
        # esteira de caixas
        self.box_v = approach(self.box_v, BOX_SPEED if out["BOXBELT"] else 0.0, BOX_ACCEL, BOX_DECEL, dt)
        d = self.box_v * dt
        for bx in self.boxes:
            bx.x += d
        for bx in [bx for bx in self.boxes if bx.x > 700]:
            self.boxes.remove(bx)
            if bx.bottles == PER_BOX:
                self.boxes_shipped += 1
            else:
                self.boxes_incomplete += 1
        while min(bx.x for bx in self.boxes) > 360:
            self.boxes.append(Box(min(bx.x for bx in self.boxes) - BOX_SPACING))

    def sensors(self) -> dict[str, bool]:
        insp = self.bottle_at(INSP_X, INSP_WINDOW)
        eye = any(b.x - BW / 2 <= EYE_X <= b.x + BW / 2 for b in self.bottles)
        return {"AT_FILL": eye, "AT_INSP": insp is not None, "LEVEL_OK": insp is not None and insp.level_ok,
                "DROP": self.drop_ms > 0, "BOX_OK": self.box_ready() is not None}

    def alarms(self) -> list[str]:
        out = []
        if self.spilled > 0.02:
            out.append(f"{self.spilled:.2f} L derramados: valvula aberta sem garrafa sob o bico")
        if self.overflowed:
            out.append(f"{self.overflowed} garrafa(s) transbordaram: tempo de enchimento grande demais")
        if self.broken:
            out.append(f"{self.broken} garrafa(s) quebraram: cairam sem caixa posicionada")
        if self.bad_packed:
            out.append(f"{self.bad_packed} garrafa(s) fora do nivel foram encaixotadas: use o rejeitor")
        if self.box_overfull:
            out.append("Caixa com mais de 6 garrafas")
        if self.boxes_incomplete:
            out.append(f"{self.boxes_incomplete} caixa(s) expedidas incompletas")
        return out

    def stats(self) -> list[str]:
        return [f"Embaladas: {self.packed_small} pequenas, {self.packed_large} grandes | caixas: {self.boxes_shipped}",
                f"Refugo: {self.scrap} (boas rejeitadas: {self.good_rejected}) | "
                f"esteira {self.belt_v / 400:.2f} m/s"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"START": (20, 268, 120, 28), "STOP": (20, 302, 120, 28), "LARGE": (20, 336, 120, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        out, sens = self.out, self.sensors()
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f8fafc"))
        p.fillRect(QRectF(0, 380, 640, 40), QColor("#cbd5e1"))
        # tanque e bico
        tank = QRectF(FILL_X - 40, 22, 80, 70)
        p.setPen(QPen(QColor("#334155"), 1.2))
        grad = QLinearGradient(tank.left(), 0, tank.right(), 0)
        grad.setColorAt(0, QColor("#94a3b8"))
        grad.setColorAt(0.5, QColor("#e2e8f0"))
        grad.setColorAt(1, QColor("#94a3b8"))
        p.setBrush(grad)
        p.drawRoundedRect(tank, 8, 8)
        draw.text(p, tank.center().x(), tank.top() + 14, "PRODUTO", 7, True, draw.INK,
                  Qt.AlignHCenter | Qt.AlignVCenter, 80)
        p.fillRect(QRectF(FILL_X - 3, tank.bottom(), 6, 40), QColor("#475569"))
        p.setBrush(QColor("#2563eb") if self.valve > 0.5 else QColor("#64748b"))
        p.drawRect(QRectF(FILL_X - 10, tank.bottom() + 12, 20, 14))
        draw.tag(p, FILL_X - 98, tank.bottom() + 19, "Q0.1 valvula", out["VALVE"])
        nozzle_y = tank.bottom() + 40
        if self.valve > 0.05:
            p.fillRect(QRectF(FILL_X - 1.5 * self.valve, nozzle_y, 3 * self.valve, BELT_Y - nozzle_y - 30),
                       QColor(37, 99, 235, 170))
        # esteira de garrafas
        self._belt(p, QRectF(0, BELT_Y, BELT_END, 16), self.belt_pos)
        draw.motor(p, QPointF(230, BELT_Y + 42), 13, out["BELT"], self.belt_pos / 12)
        draw.tag(p, 254, BELT_Y + 42, "Q0.0 esteira", out["BELT"])
        for b in self.bottles:
            self._bottle(p, b)
        # fotocelula do enchimento
        draw.sensor(p, QRectF(EYE_X - 5, BELT_Y - 92, 10, 18), sens["AT_FILL"])
        draw.beam(p, QPointF(EYE_X, BELT_Y - 74), QPointF(EYE_X, BELT_Y - 2), sens["AT_FILL"])
        draw.tag(p, EYE_X + 8, BELT_Y - 84, "I0.2", sens["AT_FILL"])
        # inspecao e rejeitor
        draw.sensor(p, QRectF(INSP_X - 5, BELT_Y - 100, 10, 18), sens["AT_INSP"])
        draw.beam(p, QPointF(INSP_X, BELT_Y - 82), QPointF(INSP_X, BELT_Y - 2), sens["AT_INSP"])
        draw.tag(p, INSP_X + 8, BELT_Y - 100, "I0.4 garrafa", sens["AT_INSP"])
        draw.tag(p, INSP_X + 8, BELT_Y - 82, "I0.3 nivel OK", sens["LEVEL_OK"])
        rod = 30 * self.push
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#7c3aed"))
        p.drawRect(QRectF(INSP_X - 14, BELT_Y + 22 + 30, 28, 24))
        p.setBrush(QColor("#a8a29e"))
        p.drawRect(QRectF(INSP_X - 3, BELT_Y + 22 + 30 - rod, 6, rod))
        p.setBrush(QColor("#ddd6fe"))
        p.drawRect(QRectF(INSP_X - 12, BELT_Y + 18 + 30 - rod, 24, 6))
        draw.tag(p, INSP_X + 18, BELT_Y + 62, "Q0.2 rejeitor", out["PUSH"])
        bin_r = QRectF(INSP_X - 32, 300, 64, 70)
        p.setBrush(QColor("#57534e"))
        p.drawRect(bin_r)
        draw.text(p, bin_r.center().x(), bin_r.center().y(), f"REFUGO\n{self.scrap}", 7, True, draw.WHITE,
                  Qt.AlignHCenter | Qt.AlignVCenter, 64, 30)
        for x, t in self.scrap_anim:
            self._bottle(p, Bottle(x, False, 0.0), y_off=t * 160, faded=True)
        # esteira de caixas
        self._belt(p, QRectF(380, BOX_Y + 46, 260, 14), self.box_v)
        draw.motor(p, QPointF(600, BOX_Y + 82), 12, out["BOXBELT"], sum(b.x for b in self.boxes) / 12)
        draw.tag(p, 470, BOX_Y + 82, "Q0.3 caixas", out["BOXBELT"])
        p.setClipRect(QRectF(380, 0, 260, 420))          # caixas so aparecem sobre a esteira
        for bx in self.boxes:
            r = QRectF(bx.x - BOX_W / 2, BOX_Y, BOX_W, 46)
            p.setPen(QPen(QColor("#78350f"), 1.2))
            p.setBrush(QColor("#d6a76c"))
            p.drawRect(r)
            for k in range(min(bx.bottles, PER_BOX)):
                cx = r.left() + 12 + (k % 3) * 30
                cy = r.top() + 12 + (k // 3) * 20
                p.setBrush(QColor("#fca5a5") if k >= bx.bottles - bx.bad else QColor("#93c5fd"))
                p.drawEllipse(QPointF(cx, cy), 8, 8)
            draw.text(p, r.center().x(), r.bottom() - 6, f"{bx.bottles}/6", 7, True, QColor("#451a03"),
                      Qt.AlignHCenter | Qt.AlignVCenter, 60)
        p.setClipping(False)
        draw.sensor(p, QRectF(DROP_X + 50, BOX_Y + 10, 18, 10), sens["BOX_OK"], vertical=False)
        draw.tag(p, DROP_X + 70, BOX_Y + 15, "I0.7", sens["BOX_OK"])
        draw.beam(p, QPointF(BELT_END + 2, BOX_Y - 16), QPointF(DROP_X + 46, BOX_Y - 16), sens["DROP"])
        draw.tag(p, DROP_X + 50, BOX_Y - 16, "I0.6 queda", sens["DROP"])
        # painel
        draw.panel(p, QRectF(10, 244, 190, 132), "LINHA DE GARRAFAS")
        draw.push_button(p, QRectF(20, 268, 120, 28), "START I0.0", self.is_pressed("START"), draw.GREEN)
        draw.push_button(p, QRectF(20, 302, 120, 28), "STOP I0.1 (NF)", self.is_pressed("STOP"), draw.RED)
        draw.switch(p, QRectF(20, 336, 120, 28), "Grande I0.5", self.is_pressed("LARGE"))
        draw.lamp(p, QPointF(160, 282), 9, out["RUN"], draw.GREEN)
        draw.text(p, 148, 300, "RUN", 7.5, True)
        draw.tag(p, 148, 314, "Q0.4", out["RUN"])

    def _belt(self, p: QPainter, r: QRectF, phase: float) -> None:
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(QColor("#334155"))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        p.setBrush(QColor("#94a3b8"))
        step = 22.0
        x = r.left() + (phase % step)
        while x < r.right() - 4:
            p.drawEllipse(QPointF(x, r.center().y()), r.height() / 2 - 3, r.height() / 2 - 3)
            x += step

    def _bottle(self, p: QPainter, b: Bottle, y_off: float = 0.0, faded: bool = False) -> None:
        h = 58.0 if b.large else 42.0
        base = BELT_Y + y_off
        body = QRectF(b.x - BW / 2, base - h, BW, h)
        neck = QRectF(b.x - 5, body.top() - 12, 10, 12)
        alpha = 110 if faded else 255
        p.setPen(QPen(QColor(15, 23, 42, alpha), 1))
        p.setBrush(QColor(224, 242, 254, alpha))
        p.drawRoundedRect(body, 5, 5)
        p.drawRect(neck)
        frac = min(1.1, b.fraction)
        if frac > 0:
            liquid_h = (h - 4) * min(1.0, frac)
            color = QColor(37, 99, 235, alpha) if b.level_ok or frac < LEVEL_OK[0] else QColor(220, 38, 38, alpha)
            p.fillRect(QRectF(body.left() + 2, body.bottom() - 2 - liquid_h, BW - 4, liquid_h), color)
            if frac > 1.0:
                p.fillRect(QRectF(neck.left() + 1, neck.top() + 2, 8, 10), color)
        p.setBrush(Qt.NoBrush)
