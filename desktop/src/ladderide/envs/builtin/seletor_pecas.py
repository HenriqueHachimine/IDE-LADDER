"""Separacao de pecas configuravel: o operador escolhe o tipo de cada caixa; o programa rastreia cada peca."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

PITCH_S = 0.5                 # um passo (taliscas da esteira) a cada 0,5 s
ACCEL = 8.0                   # passos/s^2 na partida e na parada
POS = {"A": 3, "B": 6, "C": 9}
END = 12                      # cacamba D no fim da esteira
SENSE = 0.35                  # janela dos sensores de inspecao (passos)
PUSH_S = 0.12                 # desviador: avanca/recua em 0,12 s
CAPACITY = 10                 # pecas por caixa (A, B e C)
PX0, PX = 110.0, 40.0         # desenho: inspecao em x = 110, 40 px por passo
BELT_Y = 200.0
CFG_WORD = {"A": 10, "B": 11, "C": 12}     # N10..N12: tipo escolhido para cada caixa
REG_WORD, REG_LEN = 20, 12                 # N20..N31: registrador do exemplo (so para desenhar)
# codigo = 1 + 2*(plastica) + (baixa)
KINDS = {1: ("Metálica alta", True, True), 2: ("Metálica baixa", True, False),
         3: ("Plástica alta", False, True), 4: ("Plástica baixa", False, False)}
OPTIONS = [0, 1, 2, 3, 4]
CHANGE_GRACE_MS = 1000        # peca a caminho quando o operador troca o tipo de uma caixa


@dataclass
class Part:
    x: float            # posicao em passos (0 = inspecao)
    kind: int
    gone: float = 0.0   # animacao depois de desviada
    passed: dict = None  # caixa -> tipos aceitos quando a peca passou por ela sem ser desviada

    def __post_init__(self) -> None:
        self.passed = {}


@register
class SorterEnvironment(Environment):
    id = "seletor_pecas"
    name = "Separação de peças configurável"
    description = ("A esteira anda um passo a cada 0,5 s (encoder: 1 pulso por passo). Na inspeção: presença, "
                   "indutivo (metal) e altura. Clique no seletor de cada caixa para escolher que peça ela recebe "
                   "(código em N10, N11 e N12: 1 metálica alta, 2 metálica baixa, 3 plástica alta, 4 plástica baixa, "
                   "0 nenhuma). A peça vai para a primeira caixa com o seu tipo: desviador A 3 passos depois da "
                   "inspeção, B 6 e C 9; o resto cai na caçamba D. Cada caixa tem 10 lugares: pare a esteira, acenda "
                   "TROCAR CAIXAS e espere o botão CAIXAS TROCADAS. A linha embaixo da esteira mostra N20 a N31.")
    example = "ambientes/seletor_pecas.ladproj"
    size = (720, 450)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave liga a esteira", SWITCH),
        IOPoint("ENCODER", "I0.1", "Encoder", "Encoder: 1 pulso por passo (metade do passo em 1)"),
        IOPoint("PECA", "I0.2", "Peca_Inspecao", "Peça no ponto de inspeção"),
        IOPoint("METAL", "I0.3", "Sensor_Metal", "Sensor indutivo: peça metálica na inspeção"),
        IOPoint("ALTA", "I0.4", "Sensor_Altura", "Sensor de altura: peça alta na inspeção"),
        IOPoint("TROCADAS", "I0.5", "Caixas_Trocadas", "Botão CAIXAS TROCADAS (operador esvaziou as caixas)", BUTTON),
    ]
    outputs = [
        IOPoint("MOTOR", "Q0.0", "Motor_Esteira", "Motor da esteira"),
        IOPoint("DESV_A", "Q0.1", "Desviador_A", "Desviador da caixa A (3 passos)"),
        IOPoint("DESV_B", "Q0.2", "Desviador_B", "Desviador da caixa B (6 passos)"),
        IOPoint("LUZ", "Q0.3", "Lampada_Run", "Lâmpada esteira em operação"),
        IOPoint("DESV_C", "Q0.4", "Desviador_C", "Desviador da caixa C (9 passos)"),
        IOPoint("TROCAR", "Q0.5", "Lampada_Trocar", "Lâmpada TROCAR CAIXAS"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(5)
        self.s = 0.0                 # deslocamento total da esteira (passos)
        self.v = 0.0
        self.parts: list[Part] = []
        self.pushers = {"A": 0.0, "B": 0.0, "C": 0.0}
        self.bins = {b: {k: 0 for k in KINDS} for b in "ABCD"}
        self.config = getattr(self, "config", {"A": 1, "B": 3, "C": 2})
        self.diverted: list[tuple[Part, str]] = []
        self.wrong = 0
        self.first_wrong = ""
        self.overflow = ""
        self.swaps = 0
        self.plc_reg = [0] * REG_LEN
        self.prev_config = dict(self.config)
        self.changed_at = -10_000             # instante da ultima troca de tipo (ms)

    # ----------------------------------------------------------- configuracao
    def input_words(self) -> dict[int, int]:
        return {CFG_WORD[b]: self.config[b] for b in "ABC"}

    def advance_words(self, n: list[int]) -> None:
        self.plc_reg = [n[REG_WORD + k] if REG_WORD + k < len(n) else 0 for k in range(REG_LEN)]

    def on_control(self, key: str, down: bool) -> None:
        if down and key.startswith("CFG_"):
            b = key[-1]
            if self.time_ms - self.changed_at > CHANGE_GRACE_MS:
                self.prev_config = dict(self.config)
            self.changed_at = self.time_ms
            self.config[b] = OPTIONS[(OPTIONS.index(self.config[b]) + 1) % len(OPTIONS)]

    def press(self, key: str, down: bool) -> None:
        if key.startswith("CFG_"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def target_of(self, kind: int, config: dict[str, int] | None = None) -> str:
        config = config or self.config
        return next((b for b in "ABC" if config[b] == kind), "D")

    def _types(self, b: str) -> set[int]:
        """Tipos que a caixa b aceita agora (logo depois de uma troca, o antigo tambem)."""
        types = {self.config[b]}
        if self.time_ms - self.changed_at <= CHANGE_GRACE_MS:
            types.add(self.prev_config[b])
        return types

    def accepted(self, part: Part, target: str) -> bool:
        """A peca vai para a primeira caixa que aceitava o seu tipo quando ela passou por la."""
        if any(types == {part.kind} for types in part.passed.values()):
            return False                        # devia ter sido desviada antes
        return target == "D" or part.kind in self._types(target)

    # ----------------------------------------------------------- fisica
    def _feed(self) -> None:
        """No instante em que a esteira completa um passo, o alimentador pode colocar uma peca 2 passos antes."""
        if self.rng.random() < 0.7:
            self.parts.append(Part(-2.0, 1 + int(self.rng.random() * 4)))

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        if self.is_pressed("TROCADAS"):
            if any(sum(self.bins[b].values()) for b in "ABC"):
                self.swaps += 1
            for b in "ABC":
                self.bins[b] = {k: 0 for k in KINDS}
        self.v = approach(self.v, 1 / PITCH_S if out["MOTOR"] else 0.0, ACCEL, ACCEL, dt)
        old = self.s
        self.s += self.v * dt
        ds = self.s - old
        for part in self.parts:
            part.x += ds
        if math.floor(self.s) > math.floor(old):        # completou um passo
            self._feed()
        for name in "ABC":
            self.pushers[name] = approach(self.pushers[name], 1.0 if out["DESV_" + name] else 0.0,
                                          1 / PUSH_S, 1 / PUSH_S, dt)
        keep = []
        for part in self.parts:
            target = next((b for b in "ABC" if self.pushers[b] > 0.6 and POS[b] - 0.3 <= part.x <= POS[b] + 0.45),
                          None)
            if target is None and part.x >= END + 0.5:
                target = "D"
            if target is None:
                for b in "ABC":
                    if b not in part.passed and part.x > POS[b] + 0.45:
                        part.passed[b] = self._types(b)
                keep.append(part)
                continue
            self.bins[target][part.kind] += 1
            if target != "D" and sum(self.bins[target].values()) > CAPACITY and not self.overflow:
                self.overflow = target
            if not self.accepted(part, target):
                self.wrong += 1
                self.first_wrong = self.first_wrong or f"{KINDS[part.kind][0].lower()} na caixa {target}"
            self.diverted.append((part, target))
        self.parts = keep
        for part, _ in self.diverted:
            part.gone += dt
        self.diverted = [(p, b) for p, b in self.diverted if p.gone < 0.4]

    def _at_inspection(self) -> Part | None:
        return next((p for p in self.parts if abs(p.x) < SENSE), None)

    def sensors(self) -> dict[str, bool]:
        part = self._at_inspection()
        return {"ENCODER": (self.s % 1.0) < 0.5, "PECA": part is not None,
                "METAL": part is not None and KINDS[part.kind][1],
                "ALTA": part is not None and KINDS[part.kind][2]}

    def alarms(self) -> list[str]:
        out = []
        if self.wrong:
            out.append(f"Peças no destino errado (a primeira: {self.first_wrong}): o desvio precisa da "
                       "classificação de quando a peça passou pela inspeção e do tipo escolhido para cada caixa")
        if self.overflow:
            out.append(f"A caixa {self.overflow} transbordou: pare a esteira com {CAPACITY} peças e peça a troca")
        return out

    def stats(self) -> list[str]:
        names = {0: "nenhuma"} | {k: v[0].lower() for k, v in KINDS.items()}
        return [" | ".join(f"{b} ({names[self.config[b]]}): {sum(self.bins[b].values())}" for b in "ABC")
                + f" | D: {sum(self.bins['D'].values())}",
                f"Destino errado: {self.wrong} | trocas de caixas: {self.swaps} | peças na esteira: {len(self.parts)}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        c = {"LIGA": (528, 64, 176, 28), "TROCADAS": (528, 98, 176, 28)}
        for b in "ABC":
            c["CFG_" + b] = (self._px(POS[b]) - 44, 344, 88, 34)
        return c

    def _px(self, x: float) -> float:
        return PX0 + x * PX

    def _part(self, p: QPainter, x: float, y: float, kind: int, alpha: int = 255, scale: float = 1.0) -> None:
        _, metal, high = KINDS[kind]
        h = (30 if high else 16) * scale
        w = 26 * scale
        r = QRectF(x - w / 2, y - h, w, h)
        g = QLinearGradient(r.topLeft(), r.topRight())
        base = QColor("#94a3b8") if metal else QColor("#f97316")
        for t, c in ((0, base.darker(130)), (0.35, base.lighter(140)), (1, base.darker(160))):
            cc = QColor(c)
            cc.setAlpha(alpha)
            g.setColorAt(t, cc)
        p.setPen(QPen(QColor(15, 23, 42, alpha), 1))
        p.setBrush(g)
        if metal:
            p.drawRoundedRect(r, 3, 3)
            top = QColor(base.lighter(160))
            top.setAlpha(alpha)
            p.setBrush(top)
            p.drawEllipse(QRectF(r.left(), r.top() - 3 * scale, w, 6 * scale))
        else:
            p.drawRoundedRect(r, 2, 2)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 450)
        sens = self.sensors()
        # legenda dos tipos
        draw.card(p, QRectF(14, 14, 500, 56))
        for k, (name, _, _) in KINDS.items():
            x = 40 + (k - 1) * 120
            self._part(p, x, 56, k, scale=0.8)
            draw.text(p, x + 16, 42, f"{k}", 9, True, draw.INK, w=20)
            draw.text(p, x + 16, 56, name, 7.5, True, draw.MUTED, w=100)
        # painel
        draw.card(p, QRectF(520, 14, 188, 150), "Painel")
        draw.switch(p, QRectF(528, 64, 176, 28), "LIGA I0.0", self.is_pressed("LIGA"))
        draw.push_button(p, QRectF(528, 98, 176, 28), "CAIXAS TROCADAS I0.5", self.is_pressed("TROCADAS"),
                         draw.AMBER)
        draw.lamp(p, QPointF(540, 46), 7, self.out.get("LUZ", False), draw.GREEN)
        draw.text(p, 552, 46, "OPER. Q0.3", 7, True, w=70)
        draw.lamp(p, QPointF(630, 46), 7, self.out.get("TROCAR", False), draw.AMBER)
        draw.text(p, 642, 46, "TROCAR Q0.5", 7, True, w=70)
        draw.text(p, 530, 146, "clique nas caixas para escolher", 6.5, False, draw.MUTED, w=180)
        # esteira
        belt = QRectF(self._px(-2.4), BELT_Y, self._px(END + 0.3) - self._px(-2.4), 18)
        draw.conveyor(p, belt, self.s * PX, self.v > 0.05)
        for x in (belt.left() + 30, belt.right() - 30):
            draw.metal(p, QRectF(x - 4, BELT_Y + 18, 8, 50), "#64748b", 1, vertical=True)
        # inspecao (portico com tres sensores)
        xi = self._px(0)
        draw.metal(p, QRectF(xi - 34, BELT_Y - 100, 6, 100), "#475569", 1, vertical=True)
        draw.metal(p, QRectF(xi + 28, BELT_Y - 100, 6, 100), "#475569", 1, vertical=True)
        draw.metal(p, QRectF(xi - 38, BELT_Y - 106, 76, 12), "#334155", 3)
        draw.ctext(p, xi, BELT_Y - 100, "INSPEÇÃO", 6.5, True, draw.WHITE, 76)
        draw.sensor(p, QRectF(xi - 4, BELT_Y - 92, 8, 22), sens["METAL"])
        draw.beam(p, QPointF(xi - 28, BELT_Y - 26), QPointF(xi + 28, BELT_Y - 26), sens["ALTA"])
        draw.beam(p, QPointF(xi - 28, BELT_Y - 8), QPointF(xi + 28, BELT_Y - 8), sens["PECA"])
        draw.tag(p, 8, BELT_Y - 92, "I0.3 metal", sens["METAL"])
        draw.tag(p, 8, BELT_Y - 26, "I0.4 alta", sens["ALTA"])
        draw.tag(p, 8, BELT_Y - 8, "I0.2 peça", sens["PECA"])
        # desviadores e caixas
        names = {0: "nenhuma"} | {k: v[0] for k, v in KINDS.items()}
        for b in "ABC":
            x = self._px(POS[b])
            ext = self.pushers[b]
            on = self.out.get("DESV_" + b, False)
            draw.cylinder(p, QRectF(x - 12, BELT_Y - 88, 24, 40), ext, horizontal=False, stroke=46)
            draw.metal(p, QRectF(x - 17, BELT_Y - 48 + ext * 46 - 4, 34, 8), "#2563eb" if on else "#64748b", 2)
            addr = {"A": "Q0.1", "B": "Q0.2", "C": "Q0.4"}[b]
            draw.tag(p, x - 22, BELT_Y - 102, addr, on)
            # caixa
            box = QRectF(x - 32, BELT_Y + 70, 64, 56)
            n = sum(self.bins[b].values())
            draw.shadow(p, box, 3, 3)
            draw.metal(p, box, "#c08a4a", 3)
            fill = min(1.0, n / CAPACITY)
            p.fillRect(QRectF(box.left() + 4, box.bottom() - 4 - (box.height() - 8) * fill, box.width() - 8,
                              (box.height() - 8) * fill), QColor(30, 41, 59, 80))
            draw.ctext(p, x, box.top() + 14, b, 10, True, draw.WHITE, 40)
            draw.ctext(p, x, box.top() + 36, f"{n}/{CAPACITY}", 9, True,
                       QColor("#fecaca") if n > CAPACITY else draw.WHITE, 60)
            # seletor do tipo
            sel = QRectF(x - 44, 344, 88, 34)
            draw.shadow(p, sel, 6, 2)
            p.setPen(QPen(QColor("#2563eb"), 1.4))
            p.setBrush(QColor("#eff6ff"))
            p.drawRoundedRect(sel, 6, 6)
            kind = self.config[b]
            if kind:
                self._part(p, sel.left() + 14, sel.bottom() - 6, kind, scale=0.6)
            draw.text(p, sel.left() + 26, sel.top() + 11, f"caixa {b}: {kind}", 7, True, QColor("#1d4ed8"), w=62)
            draw.text(p, sel.left() + 26, sel.top() + 24, names[kind], 6.5, False, draw.INK, w=62)
            draw.text(p, x - 44, 386, f"N{CFG_WORD[b]} = {kind}", 6.5, True, draw.MUTED, w=88)
        # cacamba D
        xd = self._px(END) + 22
        bin_d = QRectF(xd - 24, BELT_Y + 30, 66, 70)
        draw.metal(p, bin_d, "#475569", 4)
        draw.ctext(p, bin_d.center().x(), bin_d.top() + 16, "D resto", 7.5, True, draw.WHITE, 66)
        draw.ctext(p, bin_d.center().x(), bin_d.top() + 40, str(sum(self.bins["D"].values())), 11, True,
                   draw.WHITE, 66)
        # pecas
        for part in self.parts:
            self._part(p, self._px(part.x), BELT_Y, part.kind)
        for part, target in self.diverted:
            if target == "D":
                x, y = self._px(part.x) + 20 * part.gone / 0.4, BELT_Y + 60 * min(1.0, part.gone / 0.3)
            else:
                x, y = self._px(POS[target]), BELT_Y + 70 * min(1.0, part.gone / 0.3) + 10
            self._part(p, x, y, part.kind, 170)
        # encoder
        ec = QPointF(self._px(-1.6), BELT_Y + 40)
        p.setPen(QPen(QColor("#1e293b"), 1.2))
        p.setBrush(QColor("#e2e8f0"))
        p.drawEllipse(ec, 14, 14)
        a = (self.s % 1.0) * 2 * math.pi
        p.setPen(QPen(draw.GREEN if sens["ENCODER"] else QColor("#475569"), 3))
        p.drawLine(ec, QPointF(ec.x() + math.cos(a) * 11, ec.y() + math.sin(a) * 11))
        draw.tag(p, 8, BELT_Y + 72, "I0.1 encoder", sens["ENCODER"])
        # motor
        draw.motor(p, QPointF(self._px(END) - 14, BELT_Y + 50), 12, self.out.get("MOTOR", False), self.s * 3)
        draw.tag(p, self._px(END) - 100, BELT_Y + 78, "Q0.0 esteira", self.out.get("MOTOR", False))
        # registrador do programa (N20..N31): o que o CLP acha que esta em cada passo
        y = 410
        draw.text(p, 8, y, "programa", 7, True, draw.MUTED, w=60)
        draw.text(p, 8, y + 14, "N20…N31", 7, True, draw.MUTED, w=60)
        for k, code in enumerate(self.plc_reg):
            cell = QRectF(self._px(k) - 17, y - 8, 34, 26)
            p.setPen(QPen(QColor("#94a3b8"), 1))
            p.setBrush(QColor("#ffffff") if not code else (QColor("#e2e8f0") if code in (1, 2) else QColor("#ffedd5")))
            p.drawRoundedRect(cell, 4, 4)
            draw.ctext(p, cell.center().x(), cell.top() + 9, str(code), 8, True,
                       draw.INK if code else QColor("#cbd5e1"), 34)
            draw.ctext(p, cell.center().x(), cell.bottom() - 6, f"N{REG_WORD + k}", 5.5, False, draw.MUTED, 34)
