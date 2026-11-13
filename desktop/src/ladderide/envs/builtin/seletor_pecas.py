"""Separacao de pecas com registrador de deslocamento: inspecao num ponto, desvio varios passos depois."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

PITCH_S = 0.5                 # um passo (taliscas da esteira) a cada 0,5 s
ACCEL = 8.0                   # passos/s^2 na partida e na parada
POS_A, POS_B, END = 3, 6, 9   # desviador A a 3 passos da inspecao, B a 6, caixa C no fim
SENSE = 0.35                  # janela dos sensores de inspecao (passos)
PUSH_S = 0.12                 # desviador: avanca/recua em 0,12 s
PX0, PX = 170.0, 46.0         # desenho: inspecao em x = 170, 46 px por passo
BELT_Y = 210.0
KINDS = {"metal": ("#94a3b8", "Metálica"), "alta": ("#f97316", "Plástica alta"), "baixa": ("#22c55e", "Plástica baixa")}
TARGET = {"metal": "A", "alta": "B", "baixa": "C"}


@dataclass
class Part:
    x: float            # posicao em passos (0 = inspecao)
    kind: str
    gone: float = 0.0   # animacao depois de desviada


@register
class SorterEnvironment(Environment):
    id = "seletor_pecas"
    name = "Separação de peças (registrador de deslocamento)"
    description = ("A esteira anda um passo a cada 0,5 s e o encoder dá um pulso por passo. A peça é examinada no "
                   "ponto de inspeção (presença, indutivo para metal, sensor de altura), mas só é desviada 3 passos "
                   "depois (metálicas, desviador A) ou 6 passos depois (plásticas altas, desviador B); as baixas vão "
                   "até a caixa C. Como várias peças estão na esteira ao mesmo tempo, o programa precisa guardar a "
                   "classificação de cada uma e deslocá-la a cada pulso: um registrador de deslocamento em N0 e N1.")
    example = "ambientes/seletor_pecas.ladproj"
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave liga a esteira", SWITCH),
        IOPoint("ENCODER", "I0.1", "Encoder", "Encoder: 1 pulso por passo (metade do passo em 1)"),
        IOPoint("PECA", "I0.2", "Peca_Inspecao", "Peça no ponto de inspeção"),
        IOPoint("METAL", "I0.3", "Sensor_Metal", "Sensor indutivo: peça metálica na inspeção"),
        IOPoint("ALTA", "I0.4", "Sensor_Altura", "Sensor de altura: peça alta na inspeção"),
    ]
    outputs = [
        IOPoint("MOTOR", "Q0.0", "Motor_Esteira", "Motor da esteira"),
        IOPoint("DESV_A", "Q0.1", "Desviador_A", "Desviador A: metálicas"),
        IOPoint("DESV_B", "Q0.2", "Desviador_B", "Desviador B: plásticas altas"),
        IOPoint("LUZ", "Q0.3", "Lampada_Run", "Lâmpada esteira em operação"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(5)
        self.s = 0.0                 # deslocamento total da esteira (passos)
        self.v = 0.0
        self.parts: list[Part] = []
        self.pushers = {"A": 0.0, "B": 0.0}
        self.bins = {b: {k: 0 for k in KINDS} for b in "ABC"}
        self.diverted: list[tuple[Part, str]] = []
        self.wrong = 0
        self.first_wrong = ""

    def _feed(self) -> None:
        """No instante em que a esteira completa um passo, o alimentador pode colocar uma peca 2 passos antes."""
        if self.rng.random() < 0.7:
            r = self.rng.random()
            kind = "metal" if r < 0.35 else ("alta" if r < 0.65 else "baixa")
            self.parts.append(Part(-2.0, kind))

    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        self.v = approach(self.v, 1 / PITCH_S if out["MOTOR"] else 0.0, ACCEL, ACCEL, dt)
        old = self.s
        self.s += self.v * dt
        ds = self.s - old
        for part in self.parts:
            part.x += ds
        if math.floor(self.s) > math.floor(old):        # completou um passo
            self._feed()
        for name, key in (("A", "DESV_A"), ("B", "DESV_B")):
            self.pushers[name] = approach(self.pushers[name], 1.0 if out[key] else 0.0, 1 / PUSH_S, 1 / PUSH_S, dt)
        keep = []
        for part in self.parts:
            target = None
            if self.pushers["A"] > 0.6 and POS_A - 0.3 <= part.x <= POS_A + 0.45:
                target = "A"
            elif self.pushers["B"] > 0.6 and POS_B - 0.3 <= part.x <= POS_B + 0.45:
                target = "B"
            elif part.x >= END + 0.5:
                target = "C"
            if target is None:
                keep.append(part)
                continue
            self.bins[target][part.kind] += 1
            if TARGET[part.kind] != target:
                self.wrong += 1
                self.first_wrong = self.first_wrong or f"{KINDS[part.kind][1].lower()} na caixa {target}"
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
                "METAL": part is not None and part.kind == "metal",
                "ALTA": part is not None and part.kind == "alta"}

    def alarms(self) -> list[str]:
        if not self.wrong:
            return []
        return [f"Peças no destino errado (a primeira: {self.first_wrong}): o desvio precisa da classificação "
                "de quando a peça passou pela inspeção"]

    def stats(self) -> list[str]:
        ok = sum(self.bins[TARGET[k]][k] for k in KINDS)
        return [f"Caixa A (metálicas): {sum(self.bins['A'].values())} | B (altas): {sum(self.bins['B'].values())} | "
                f"C (baixas): {sum(self.bins['C'].values())}",
                f"Certas: {ok} | erradas: {self.wrong} | peças na esteira: {len(self.parts)}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (16, 370, 150, 28)}

    def _px(self, x: float) -> float:
        return PX0 + x * PX

    def _part(self, p: QPainter, x: float, y: float, kind: str, alpha: int = 255) -> None:
        color = QColor(KINDS[kind][0])
        color.setAlpha(alpha)
        p.setPen(QPen(QColor(15, 23, 42, alpha), 1))
        p.setBrush(color)
        h = 34 if kind == "alta" else 20
        if kind == "metal":
            p.drawEllipse(QRectF(x - 14, y - h, 28, h))
        else:
            p.drawRoundedRect(QRectF(x - 14, y - h, 28, h), 3, 3)

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#f8fafc"))
        sens = self.sensors()
        # esteira com taliscas que andam
        belt = QRectF(self._px(-2.5), BELT_Y, self._px(END + 0.2) - self._px(-2.5), 18)
        p.setPen(QPen(QColor("#0f172a"), 1.5))
        p.setBrush(QColor("#334155"))
        p.drawRoundedRect(belt, 9, 9)
        p.setPen(QPen(QColor("#64748b"), 2))
        k = -3
        while True:
            x = self._px(k + self.s % 1.0)
            if x > belt.right() - 4:
                break
            if x > belt.left() + 4:
                p.drawLine(QPointF(x, BELT_Y + 2), QPointF(x, BELT_Y + 16))
            k += 1
        # caixas
        for name, pos, label in (("A", POS_A, "A metálicas"), ("B", POS_B, "B altas")):
            x = self._px(pos)
            p.setPen(QPen(QColor("#78350f"), 1.5))
            p.setBrush(QColor("#fde68a"))
            p.drawRect(QRectF(x - 26, BELT_Y + 60, 52, 50))
            draw.text(p, x, BELT_Y + 122, label, 7.5, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 100)
            draw.text(p, x, BELT_Y + 86, str(sum(self.bins[name].values())), 11, True, draw.INK,
                      Qt.AlignHCenter | Qt.AlignVCenter, 50)
            # desviador (empurra a peca para a frente, para a caixa)
            ext = self.pushers[name]
            p.setBrush(QColor("#cbd5e1"))
            p.setPen(QPen(QColor("#1e293b"), 1.2))
            p.drawRect(QRectF(x - 18, BELT_Y - 110, 36, 40))
            p.setBrush(QColor("#2563eb") if self.out.get("DESV_" + name) else QColor("#64748b"))
            p.drawRect(QRectF(x - 16, BELT_Y - 70 + ext * 46, 32, 10))
            draw.tag(p, x - 30, BELT_Y - 124, f"Q0.{1 if name == 'A' else 2} desv. {name}",
                     self.out.get("DESV_" + name, False))
        xc = self._px(END) + 10
        p.setBrush(QColor("#fde68a"))
        p.setPen(QPen(QColor("#78350f"), 1.5))
        p.drawRect(QRectF(xc - 20, BELT_Y + 20, 52, 50))
        draw.text(p, xc + 6, BELT_Y + 44, str(sum(self.bins["C"].values())), 11, True, draw.INK,
                  Qt.AlignHCenter | Qt.AlignVCenter, 50)
        draw.text(p, xc + 6, BELT_Y + 82, "C baixas", 7.5, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 80)
        # pecas
        for part in self.parts:
            self._part(p, self._px(part.x), BELT_Y, part.kind)
        for part, target in self.diverted:
            x = self._px(POS_A if target == "A" else POS_B if target == "B" else part.x)
            self._part(p, x, BELT_Y + 50 * min(1.0, part.gone / 0.3) + 10, part.kind, 160)
        # inspecao
        xi = self._px(0)
        p.setPen(QPen(QColor("#1e293b"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRect(QRectF(xi - 30, BELT_Y - 92, 60, 24))
        draw.text(p, xi, BELT_Y - 80, "inspeção", 7.5, True, draw.INK, Qt.AlignHCenter | Qt.AlignVCenter, 70)
        draw.sensor(p, QRectF(xi - 4, BELT_Y - 66, 8, 22), sens["PECA"])
        draw.tag(p, 8, BELT_Y - 132, "I0.2 peça", sens["PECA"])
        draw.tag(p, 8, BELT_Y - 110, "I0.3 metal", sens["METAL"])
        draw.tag(p, 8, BELT_Y - 88, "I0.4 alta", sens["ALTA"])
        # encoder
        ec = QPointF(self._px(-2.2), BELT_Y + 40)
        p.setPen(QPen(QColor("#1e293b"), 1.2))
        p.setBrush(QColor("#e2e8f0"))
        p.drawEllipse(ec, 16, 16)
        a = (self.s % 1.0) * 2 * math.pi
        p.setPen(QPen(draw.GREEN if sens["ENCODER"] else QColor("#475569"), 3))
        p.drawLine(ec, QPointF(ec.x() + math.cos(a) * 13, ec.y() + math.sin(a) * 13))
        draw.tag(p, ec.x() + 22, ec.y(), "I0.1 encoder", sens["ENCODER"])
        # motor, legenda e chave
        draw.motor(p, QPointF(self._px(END + 0.2), BELT_Y - 40), 14, self.out.get("MOTOR", False), self.s * 3)
        draw.tag(p, self._px(END) - 30, BELT_Y - 70, "Q0.0 esteira", self.out.get("MOTOR", False))
        for k, kind in enumerate(KINDS):
            self._part(p, 210 + k * 140, 395, kind)
            draw.text(p, 230 + k * 140, 385, KINDS[kind][1], 7.5, True, draw.MUTED, w=110)
        draw.lamp(p, QPointF(30, 40), 10, self.out.get("LUZ", False), draw.GREEN)
        draw.text(p, 46, 40, "EM OPERAÇÃO  Q0.3", 8, True)
        draw.switch(p, QRectF(16, 370, 150, 28), "LIGA  I0.0", self.is_pressed("LIGA"))
