"""Estacao de montagem: braco pneumatico poe a tampa na base parada no batente."""
from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..registry import register
from ..transport import Belt, Emitter, Item, blade, emitter_box, remover_box

LANE_BASE, LANE_LID = 262.0, 96.0
BELT_W = 56.0
X0, X_END = 40.0, 700.0
ST_X = 380.0                          # centro da estacao (base e tampa param centradas aqui)
BASE_L, LID_L = 52.0, 40.0
BLADE = ST_X + BASE_L / 2             # batente da base
LID_END = ST_X + LID_L / 2            # fim da esteira das tampas
BASE_V, EXIT_V, LID_V = 60.0, 160.0, 80.0
Y_S, Z_S = 0.8, 0.45                  # tempos de curso do braco (s)
CLOSE_S, OPEN_S = 0.35, 0.15          # garra sem sensor: fecha em 0,35 s
TOP = 1.0 - 1e-6


@register
class AssemblyEnvironment(Environment):
    id = "montagem"
    name = "Estação de montagem"
    description = ("As bases chegam pela esteira de baixo e param no batente (I0.1); as tampas chegam pela de cima e "
                   "param no fim dela (I0.2). O braço pneumático tem três movimentos: Q0.3 avança da tampa até a base "
                   "(I0.3 recuado, I0.4 avançado), Q0.4 desce o Z (I0.5 em cima, I0.6 embaixo) e Q0.5 fecha a garra, "
                   "que não tem sensor (leva 0,35 s para fechar). Pegue a tampa, leve até a base parada, solte e só "
                   "então abaixe o batente (Q0.1) para a base montada seguir; o batente deve subir antes da próxima. "
                   "O braço pode buscar a tampa enquanto a base ainda vem: as duas coisas acontecem em paralelo.")
    example = "ambientes/montagem.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("BASE", "I0.1", "Base_Na_Estacao", "Base parada no batente"),
        IOPoint("TAMPA", "I0.2", "Tampa_Pronta", "Tampa no fim da esteira das tampas"),
        IOPoint("NA_TAMPA", "I0.3", "Braco_Na_Tampa", "Braço recuado (sobre a tampa)"),
        IOPoint("NA_BASE", "I0.4", "Braco_Na_Base", "Braço avançado (sobre a base)"),
        IOPoint("Z_CIMA", "I0.5", "Z_Em_Cima", "Z em cima"),
        IOPoint("Z_BAIXO", "I0.6", "Z_Embaixo", "Z embaixo"),
    ]
    outputs = [
        IOPoint("BASES", "Q0.0", "Esteira_Bases", "Esteiras das bases (entrada e saída)"),
        IOPoint("LIBERA", "Q0.1", "Libera_Base", "Abaixa o batente da base"),
        IOPoint("TAMPAS", "Q0.2", "Esteira_Tampas", "Esteira das tampas"),
        IOPoint("AVANCA", "Q0.3", "Braco_Avanca", "Braço avança até a base (desligado volta)"),
        IOPoint("DESCE", "Q0.4", "Z_Desce", "Desce o Z (desligado sobe)"),
        IOPoint("GARRA", "Q0.5", "Garra", "Fecha a garra"),
        IOPoint("EMISSOR", "Q0.6", "Emissores", "Emissores de bases e tampas"),
        IOPoint("LUZ", "Q0.7", "Luz_Operando", "Lâmpada operando"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(8)
        self.bases = Belt(X0, BLADE, BASE_V)
        self.exit = Belt(BLADE, X_END, EXIT_V)
        self.lids = Belt(X0, LID_END, LID_V)
        self.base_em = Emitter(self.rng, (150.0, 300.0))
        self.lid_em = Emitter(self.rng, (40.0, 200.0))
        self.y = 0.0                  # 0 sobre a tampa, 1 sobre a base
        self.z = 0.0                  # 0 em cima, 1 embaixo
        self.grip = 0.0               # 0 aberta, 1 fechada
        self.held: Item | None = None
        self.flags: dict[str, str] = {}
        self.assembled = 0
        self.missing = 0
        self.dropped = 0

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def _base_at_station(self) -> Item | None:
        return next((b for b in self.bases.items if abs(b.center - ST_X) < 3), None)

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        if out["EMISSOR"]:
            if self.base_em.ready(self.bases, BASE_L):
                self.base_em.emit(self.bases, Item(0.0, BASE_L))
            if self.lid_em.ready(self.lids, LID_L):
                self.lid_em.emit(self.lids, Item(0.0, LID_L))
        # braco: Y so com o Z em cima, Z so com o Y parado
        moving_y = (out["AVANCA"] and self.y < 1.0) or (not out["AVANCA"] and self.y > 0.0)
        if moving_y and self.z > 0.05:
            self._flag("yz", "O braço andou com o Z embaixo")
        self.y = min(1.0, self.y + dt / Y_S) if out["AVANCA"] else max(0.0, self.y - dt / Y_S)
        if out["DESCE"] and 0.02 < self.y < 0.98:
            self._flag("zy", "O Z desceu com o braço no meio do caminho")
        self.z = min(1.0, self.z + dt / Z_S) if out["DESCE"] else max(0.0, self.z - dt / Z_S)
        down = self.z >= TOP
        # garra
        was = self.grip
        self.grip = min(1.0, self.grip + dt / CLOSE_S) if out["GARRA"] else max(0.0, self.grip - dt / OPEN_S)
        if self.held is None and was < 1.0 <= self.grip and down and self.y == 0.0:
            lid = next((i for i in self.lids.items if i.x >= LID_END - 1), None)
            if lid is not None:
                self.lids.items.remove(lid)
                self.held = lid
        if self.held is not None and self.z < TOP and self.grip < 1.0:
            self._flag("slip", "A tampa escorregou: o Z subiu com a garra abrindo")
            self.held = None
            self.dropped += 1
        if self.held is not None and self.grip <= 0.5:
            base = self._base_at_station() if self.y == 1.0 else None
            if not down:
                self._flag("drop", "A garra abriu com o Z no alto: a tampa caiu")
                self.dropped += 1
            elif self.y == 0.0:
                self.lids.items.append(self.held)          # devolvida no lugar
            elif base is None or out["LIBERA"]:
                self._flag("nobase", "Tampa largada sem base parada na estação")
                self.dropped += 1
            elif base.data.get("lid"):
                self._flag("twice", "Tampa colocada numa base que já tinha tampa")
                self.dropped += 1
            else:
                base.data["lid"] = True
            self.held = None
        if out["LIBERA"] and self.y > 0.9 and self.z > 0.3:
            self._flag("hit", "O batente abaixou com a garra encostada na base")
        # bases: batente no fim da esteira de entrada; a de saida e mais rapida e abre espaco
        if not out["LIBERA"] and any(i.back < BLADE - 0.5 for i in self.exit.items):
            self._flag("blade", "O batente subiu embaixo de uma base")
        if out["LIBERA"] and out["BASES"]:
            for it in list(self.bases.items):
                if it.x >= BLADE and self.exit.clear_from(BLADE, 2):
                    self.bases.items.remove(it)
                    self.exit.items.append(it)
        stop = min([BLADE] + [i.back - 1.0 for i in self.exit.items if i.back < BLADE + 1])
        self.bases.move(dt, bool(out["BASES"]), stop=stop)
        self.exit.move(dt, bool(out["BASES"]), end=X_END + BASE_L)
        for it in self.exit.take(lambda i: i.x >= X_END + BASE_L - 1):
            if it.data.get("lid"):
                self.assembled += 1
            else:
                self.missing += 1
                self._flag("missing", "Base saiu da estação sem tampa")
        self.lids.move(dt, bool(out["TAMPAS"]), end=LID_END)

    def sensors(self) -> dict[str, bool]:
        base = self.bases.at(BLADE - 0.5) or any(i.covers(BLADE - 0.5) for i in self.exit.items)
        return {"BASE": base, "TAMPA": any(i.x >= LID_END - 1 for i in self.lids.items),
                "NA_TAMPA": self.y == 0.0, "NA_BASE": self.y == 1.0,
                "Z_CIMA": self.z == 0.0, "Z_BAIXO": self.z >= TOP}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Montadas: {self.assembled} | sem tampa: {self.missing} | tampas perdidas: {self.dropped}",
                f"Bases na fila: {len(self.bases.items)} | tampas na fila: {len(self.lids.items)}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (510, 410, 140, 30)}

    @staticmethod
    def _base(p: QPainter, r: QRectF, lid: bool) -> None:
        draw.metal(p, r, "#64748b", 4)
        p.setPen(QPen(QColor("#334155"), 1))
        p.setBrush(QColor("#cbd5e1"))
        p.drawEllipse(r.center(), r.width() * 0.3, r.height() * 0.3)
        if lid:
            AssemblyEnvironment._lid(p, QRectF(r.center().x() - LID_L / 2, r.center().y() - LID_L / 2, LID_L, LID_L))
        p.setBrush(Qt.NoBrush)

    @staticmethod
    def _lid(p: QPainter, r: QRectF) -> None:
        draw.shadow(p, r, 6, 2)
        p.setPen(QPen(QColor("#9a3412"), 1.2))
        p.setBrush(QColor("#f97316"))
        p.drawRoundedRect(r, 7, 7)
        p.setPen(QPen(QColor("#fed7aa"), 1.4))
        p.drawEllipse(r.center(), r.width() * 0.22, r.height() * 0.22)
        p.setBrush(Qt.NoBrush)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out, sens = self.out, self.sensors()
        floor = QRectF(8, 8, 704, 322)
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(floor, 8, 8)
        draw.text(p, 18, 20, "VISTA DE CIMA", 7, True, draw.MUTED)
        run_b = bool(out.get("BASES"))
        draw.conveyor(p, QRectF(X0, LANE_BASE - BELT_W / 2, BLADE - X0, BELT_W), self.bases.offset, run_b)
        draw.conveyor(p, QRectF(BLADE, LANE_BASE - BELT_W / 2, X_END - BLADE, BELT_W), self.exit.offset, run_b)
        draw.conveyor(p, QRectF(X0, LANE_LID - BELT_W / 2, LID_END + 14 - X0, BELT_W), self.lids.offset,
                      bool(out.get("TAMPAS")))
        draw.metal(p, QRectF(LID_END, LANE_LID - BELT_W / 2 - 4, 6, BELT_W + 8), "#475569", 2)
        emitter_box(p, QRectF(10, LANE_BASE - BELT_W / 2 - 6, 34, BELT_W + 12), bool(out.get("EMISSOR")), "")
        emitter_box(p, QRectF(10, LANE_LID - BELT_W / 2 - 6, 34, BELT_W + 12), bool(out.get("EMISSOR")), "")
        remover_box(p, QRectF(X_END - 4, LANE_BASE - BELT_W / 2 - 6, 16, BELT_W + 12), "")
        for it in self.bases.items + self.exit.items:
            r = QRectF(it.back, LANE_BASE - BASE_L / 2, BASE_L, BASE_L)
            if r.right() > X0 - 2:
                self._base(p, r, bool(it.data.get("lid")))
        for it in self.lids.items:
            if it.x > X0 + 4:
                self._lid(p, QRectF(max(X0 - 2, it.back), LANE_LID - LID_L / 2, LID_L, LID_L))
        blade(p, BLADE + 2, LANE_BASE - BELT_W / 2 - 4, LANE_BASE + BELT_W / 2 + 4, not out.get("LIBERA"))
        # braco: trilho entre as duas esteiras
        rail = QRectF(ST_X + 40, LANE_LID - 8, 12, LANE_BASE - LANE_LID + 16)
        draw.metal(p, rail, "#94a3b8", 3, vertical=True)
        cy = LANE_LID + self.y * (LANE_BASE - LANE_LID)
        draw.metal(p, QRectF(ST_X - 6, cy - 7, ST_X + 52 - (ST_X - 6), 14), "#475569", 3)
        if self.held is not None:
            self._lid(p, QRectF(ST_X - LID_L / 2, cy - LID_L / 2, LID_L, LID_L))
        size = 26 - 8 * self.z
        g = QRectF(ST_X - size / 2, cy - size / 2, size, size)
        draw.metal(p, g, "#1e293b" if not out.get("GARRA") else "#7c3aed", 4)
        for s in (-1, 1):
            off = (1 - self.grip) * 8 + 3
            p.setPen(QPen(QColor("#e2e8f0"), 3))
            p.drawLine(QPointF(ST_X + s * (size / 2 + off), cy - 8), QPointF(ST_X + s * (size / 2 + off), cy + 8))
        # etiquetas
        draw.tag(p, BLADE - 84, LANE_BASE + BELT_W / 2 + 16, "I0.1 base", sens["BASE"])
        draw.tag(p, BLADE + 10, LANE_BASE + BELT_W / 2 + 16, "Q0.1 libera", out.get("LIBERA", False))
        draw.tag(p, 60, LANE_BASE + BELT_W / 2 + 16, "Q0.0 bases", run_b)
        draw.tag(p, 60, LANE_LID - BELT_W / 2 - 14, "Q0.2 tampas", out.get("TAMPAS", False))
        draw.tag(p, 160, LANE_LID - BELT_W / 2 - 14, "Q0.6 emissores", out.get("EMISSOR", False))
        draw.tag(p, LID_END - 70, LANE_LID - BELT_W / 2 - 14, "I0.2 tampa", sens["TAMPA"])
        draw.tag(p, ST_X + 60, LANE_LID + 8, "I0.3 recuado", sens["NA_TAMPA"])
        draw.tag(p, ST_X + 60, LANE_BASE - 46, "I0.4 avançado", sens["NA_BASE"])
        draw.tag(p, ST_X + 60, (LANE_LID + LANE_BASE) / 2 - 10, "Q0.3 avança", out.get("AVANCA", False))
        draw.tag(p, ST_X + 60, (LANE_LID + LANE_BASE) / 2 + 12, "Q0.5 garra", out.get("GARRA", False))
        draw.text(p, 600, LANE_BASE + BELT_W / 2 + 16, "MONTADAS →", 7, True, draw.MUTED, w=90)
        draw.tag(p, ST_X + 180, (LANE_LID + LANE_BASE) / 2 - 10, "Q0.4 desce", out.get("DESCE", False))
        draw.tag(p, ST_X + 180, (LANE_LID + LANE_BASE) / 2 + 12, "I0.5 Z em cima", sens["Z_CIMA"])
        draw.tag(p, ST_X + 180, (LANE_LID + LANE_BASE) / 2 + 34, "I0.6 Z embaixo", sens["Z_BAIXO"])
        # vista lateral do braco
        side = QRectF(16, 336, 330, 116)
        draw.card(p, side, "Braço (vista lateral)")
        floor_y = side.bottom() - 22
        x_lid, x_base = side.left() + 80, side.right() - 80
        p.setPen(QPen(QColor("#1f2937"), 3))
        p.drawLine(QPointF(x_lid - 50, floor_y), QPointF(x_lid + 50, floor_y))
        p.drawLine(QPointF(x_base - 50, floor_y), QPointF(x_base + 50, floor_y))
        draw.ctext(p, x_lid, floor_y + 11, "tampas", 6.5, True, draw.MUTED, w=60)
        draw.ctext(p, x_base, floor_y + 11, "bases", 6.5, True, draw.MUTED, w=60)
        lid_c, base_c = QColor("#f97316"), QColor("#64748b")
        if sens["TAMPA"]:
            p.fillRect(QRectF(x_lid - 16, floor_y - 7, 32, 7), lid_c)
        b = self._base_at_station()
        if b is not None:
            p.fillRect(QRectF(x_base - 22, floor_y - 14, 44, 14), base_c)
            if b.data.get("lid"):
                p.fillRect(QRectF(x_base - 16, floor_y - 21, 32, 7), lid_c)
        rail_y = side.top() + 30
        draw.metal(p, QRectF(x_lid - 30, rail_y - 4, x_base - x_lid + 60, 8), "#94a3b8", 2)
        ax = x_lid + self.y * (x_base - x_lid)
        tip = floor_y - 26 + self.z * 18
        draw.metal(p, QRectF(ax - 10, rail_y - 7, 20, 14), "#475569", 3)
        draw.metal(p, QRectF(ax - 3, rail_y + 6, 6, tip - rail_y - 6), "#e5e7eb", 1, vertical=True)
        if self.held is not None:
            p.fillRect(QRectF(ax - 16, tip + 1, 32, 7), lid_c)
        p.setPen(QPen(QColor("#7c3aed") if out.get("GARRA") else QColor("#1e293b"), 2.6))
        gap = 22 - 5 * self.grip
        p.drawLine(QPointF(ax - gap, tip), QPointF(ax + gap, tip))
        p.drawLine(QPointF(ax - gap, tip), QPointF(ax - gap, tip + 10))
        p.drawLine(QPointF(ax + gap, tip), QPointF(ax + gap, tip + 10))
        # painel
        panel = QRectF(356, 336, 356, 116)
        draw.card(p, panel, "Painel")
        draw.lcd(p, QRectF(366, 362, 76, 38), str(self.assembled), "#4ade80", "montadas")
        draw.lcd(p, QRectF(450, 362, 76, 38), str(self.missing), "#f87171", "sem tampa")
        draw.lcd(p, QRectF(534, 362, 76, 38), str(self.dropped), "#fbbf24", "perdidas")
        draw.stack_light(p, 660, 352, [(bool(self.flags), draw.RED), (bool(out.get("LUZ")), draw.GREEN)])
        draw.tag(p, 366, 420, "Q0.7 operando", out.get("LUZ", False))
        draw.switch(p, QRectF(510, 410, 140, 30), "LIGA I0.0", self.is_pressed("LIGA"))
