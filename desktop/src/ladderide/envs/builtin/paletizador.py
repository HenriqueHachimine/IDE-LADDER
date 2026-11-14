"""Paletizador de camadas: contadores aninhados (caixas, filas, camadas) e amarracao alternada."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

BELT_SPEED = 120.0            # px/s na esteira de entrada
BOX_L, BOX_W = 60.0, 40.0     # caixa vista de cima (comprimento x largura)
TABLE_X0, TABLE_X1 = 300.0, 486.0   # mesa de formacao da fila (3 caixas e uma folga)
PHOTO_X = 300.0               # fotocelula na borda da mesa: limpa quando a caixa entra toda
TURN_X = 300.0                # girador na entrada da mesa (a caixa gira ao entrar)
ROW_BOXES, ROWS, LAYERS = 3, 2, 4
PUSH_S, PLATE_S = 1.0, 0.6
PLATE_H = 1300.0              # mm: altura da placa de camada
ALIGN_H = PLATE_H - 250.0     # topo da pilha alinhado: uma caixa abaixo da placa
PALLET_H, BOX_H = 150.0, 250.0
LIFT_SPEED = 120.0            # mm/s do elevador
ALIGN_TOL = 4.0
PALLET_SWAP_S = 5.0           # a esteira de pallets troca o pallet em 5 s
LANE_Y = 110.0


@dataclass
class Box:
    x: float                  # frente (borda direita) na esteira, px
    rot: bool = False         # girada 90 graus pelo girador
    turned: bool = False      # ja passou pelo girador

    @property
    def length(self) -> float:
        return BOX_W if self.rot else BOX_L


@register
class PalletizerEnvironment(Environment):
    id = "paletizador"
    name = "Paletizador de camadas"
    description = ("As caixas chegam pela esteira e formam uma fila de 3 na mesa (a fotocélula I0.1 vê cada caixa "
                   "entrar). O empurrador leva a fila para a placa de camada; com 2 filas a placa abre e a camada cai "
                   "sobre o pallet, que precisa estar alinhado logo abaixo (I0.5). Depois de cada camada o elevador "
                   "desce até alinhar de novo. Amarração: camadas pares (2ª e 4ª) com as caixas giradas pelo girador "
                   "(Q0.6), para a pilha não desmoronar. Com 4 camadas o pallet desce, a esteira de pallets troca por "
                   "um vazio e o elevador sobe até alinhar.")
    example = "ambientes/paletizador.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("FOTO", "I0.1", "Caixa_Entrando", "Fotocélula na entrada da mesa"),
        IOPoint("REC", "I0.2", "Empurrador_Recuado", "Empurrador recuado"),
        IOPoint("AVA", "I0.3", "Empurrador_Avancado", "Empurrador avançado"),
        IOPoint("FECHADA", "I0.4", "Placa_Fechada", "Placa de camada fechada"),
        IOPoint("ALINHADA", "I0.5", "Pilha_Alinhada", "Topo da pilha logo abaixo da placa"),
        IOPoint("FUNDO", "I0.6", "Elevador_Embaixo", "Elevador no fundo"),
        IOPoint("PALLET", "I0.7", "Pallet_Presente", "Pallet vazio ou em formação no elevador"),
    ]
    outputs = [
        IOPoint("ESTEIRA", "Q0.0", "Esteira_Entrada", "Esteira de entrada das caixas"),
        IOPoint("EMPURRA", "Q0.1", "Empurrador", "Empurrador de fila (avança; mola recua)"),
        IOPoint("PLACA", "Q0.2", "Abre_Placa", "Abre a placa de camada"),
        IOPoint("DESCE", "Q0.3", "Elevador_Desce", "Elevador: desce"),
        IOPoint("SOBE", "Q0.4", "Elevador_Sobe", "Elevador: sobe"),
        IOPoint("PALLETS", "Q0.5", "Esteira_Pallets", "Esteira de pallets (troca o pallet)"),
        IOPoint("GIRADOR", "Q0.6", "Girador", "Girador de caixas (camadas pares)"),
        IOPoint("COMPLETO", "Q0.7", "Lampada_Completo", "Lâmpada PALLET COMPLETO"),
    ]

    def reset(self) -> None:
        self.boxes: list[Box] = []
        self.belt = 0.0
        self.pusher = 0.0
        self.plate = 0.0                  # 0 fechada, 1 aberta
        self.rows: list[list[bool]] = []  # filas sobre a placa (orientacao de cada caixa)
        self.lift = 0.0                   # altura do elevador (mm)
        self.pallet = True
        self.layers: list[list[bool]] = []
        self.swap_t: float | None = None
        self.shipped = 0
        self.boxes_in = 0
        self.flags: dict[str, str] = {}
        self._pushed = False
        self._dropped = False
        self.falling: list[list[float]] = []

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    @property
    def stack_top(self) -> float:
        return self.lift + (PALLET_H + BOX_H * len(self.layers) if self.pallet else 0.0)

    def _on_table(self) -> list[Box]:
        return [b for b in self.boxes if b.x - b.length >= TABLE_X0 - 0.5]

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        # alimentacao continua de caixas na esteira
        if not self.boxes or min(b.x - b.length for b in self.boxes) > 30:
            self.boxes.append(Box(-10.0))
        if out["ESTEIRA"]:
            self.belt += BELT_SPEED * dt
            limit = TABLE_X1
            for b in sorted(self.boxes, key=lambda b: -b.x):
                old = b.x
                b.x = min(limit, b.x + BELT_SPEED * dt)
                center_old, center = old - b.length / 2, b.x - b.length / 2
                if not b.turned and center_old < TURN_X <= center:
                    b.turned = True
                    b.rot = bool(out["GIRADOR"])
                limit = b.x - b.length
                if old - b.length < TABLE_X0 - 0.5 <= b.x - b.length:
                    self.boxes_in += 1
            if self.pusher > 0.15 and any(TABLE_X0 < b.x and b.x - b.length < TABLE_X0 for b in self.boxes):
                self._flag("enter", "Caixa entrando na mesa com o empurrador avançado: pare a esteira antes de "
                                    "empurrar")
        on_table = self._on_table()
        if len(on_table) > ROW_BOXES:
            self._flag("many", "Mais de 3 caixas na mesa: pare a esteira quando a fila completar")
        # empurrador
        self.pusher = approach(self.pusher, 1.0 if out["EMPURRA"] else 0.0, 1 / PUSH_S, 1 / PUSH_S, dt)
        if self.pusher >= 0.98 and not self._pushed:
            self._pushed = True
            if on_table:
                if len(on_table) < ROW_BOXES:
                    self._flag("short", "Fila empurrada com menos de 3 caixas")
                if self.plate > 0.1:
                    self._flag("open", "Fila empurrada com a placa aberta: as caixas caíram")
                elif len(self.rows) >= ROWS:
                    self._flag("full", "Terceira fila empurrada sobre a placa cheia: as caixas caíram")
                else:
                    self.rows.append([b.rot for b in on_table])
                self.boxes = [b for b in self.boxes if b not in on_table]
        elif self.pusher <= 0.0:
            self._pushed = False
        # placa de camada
        self.plate = approach(self.plate, 1.0 if out["PLACA"] else 0.0, 1 / PLATE_S, 1 / PLATE_S, dt)
        if self.plate >= 0.9 and self.rows and not self._dropped:
            self._dropped = True
            layer = [r for row in self.rows for r in row]
            if len(self.rows) < ROWS:
                self._flag("incomplete", "Camada incompleta: a placa abriu com uma fila só")
            gap = ALIGN_H - self.stack_top
            if not self.pallet:
                self._flag("nopallet", "Camada solta sem pallet no elevador")
            elif gap > 20:
                self._flag("high", "A camada caiu de alto: alinhe a pilha logo abaixo da placa (I0.5)")
            if self.pallet:
                k = len(self.layers)
                expected = k % 2 == 1
                if any(r != expected for r in layer):
                    self._flag("pattern", "Amarração errada: camadas pares (2ª e 4ª) devem ter as caixas giradas")
                if len(self.layers) >= LAYERS:
                    self._flag("tall", "Mais de 4 camadas no pallet")
                self.layers.append(layer)
                self.falling.append([0.0])
            self.rows = []
        if self.plate <= 0.0:
            self._dropped = False
        # elevador
        up, down = out["SOBE"], out["DESCE"]
        if up and down:
            self._flag("both", "Elevador comandado para subir e descer ao mesmo tempo")
        elif up:
            self.lift += LIFT_SPEED * dt
        elif down:
            self.lift = max(0.0, self.lift - LIFT_SPEED * dt)
        if self.pallet and self.stack_top > PLATE_H + 6:
            self._flag("crash", "A pilha subiu contra a placa de camada")
            self.lift = PLATE_H - (self.stack_top - self.lift) + 6
        self.lift = min(self.lift, PLATE_H)
        # esteira de pallets
        if out["PALLETS"]:
            if self.lift > 2:
                self._flag("lift", "Esteira de pallets ligada com o elevador fora do fundo")
            else:
                self.swap_t = (self.swap_t or 0.0) + dt
                if self.pallet and 0.5 <= self.swap_t < PALLET_SWAP_S:
                    if len(self.layers) < LAYERS:
                        self._flag("ship", "Pallet incompleto expedido (menos de 4 camadas)")
                    else:
                        self.shipped += 1
                    self.pallet = False
                    self.layers = []
                if self.swap_t >= PALLET_SWAP_S:
                    self.pallet = True
        elif self.pallet:
            self.swap_t = None                     # o proximo acionamento troca de novo
        self.falling = [[t + dt] for (t,) in self.falling if t < 0.4]

    def sensors(self) -> dict[str, bool]:
        on_photo = any(b.x - b.length < PHOTO_X < b.x for b in self.boxes)
        return {"FOTO": on_photo, "REC": self.pusher <= 0.02, "AVA": self.pusher >= 0.98,
                "FECHADA": self.plate <= 0.02, "ALINHADA": self.pallet and abs(self.stack_top - ALIGN_H) <= ALIGN_TOL,
                "FUNDO": self.lift <= 1.0, "PALLET": self.pallet}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Caixas na mesa: {len(self._on_table())} | filas na placa: {len(self.rows)} | camadas no pallet: "
                f"{len(self.layers)}",
                f"Pallets completos expedidos: {self.shipped} | caixas recebidas: {self.boxes_in} | elevador "
                f"{self.lift:.0f} mm"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"LIGA": (14, 412, 160, 30)}

    def _box(self, p: QPainter, r: QRectF, rot: bool, alpha: int = 255) -> None:
        c = QColor("#c08a4a") if not rot else QColor("#a16207")
        c.setAlpha(alpha)
        p.setPen(QPen(QColor(69, 26, 3, alpha), 1))
        p.setBrush(c)
        p.drawRect(r)
        p.setPen(QPen(QColor(255, 237, 213, alpha), 1.5))
        if rot:
            p.drawLine(QPointF(r.center().x(), r.top() + 3), QPointF(r.center().x(), r.bottom() - 3))
        else:
            p.drawLine(QPointF(r.left() + 3, r.center().y()), QPointF(r.right() - 3, r.center().y()))

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out = self.out
        sens = self.sensors()
        # piso da celula (vista de cima)
        cell = QRectF(10, 30, 490, 360)
        p.setPen(QPen(QColor("#94a3b8"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(cell, 8, 8)
        draw.text(p, 20, 44, "VISTA DE CIMA", 7, True, draw.MUTED)
        # esteira de entrada
        draw.conveyor(p, QRectF(14, LANE_Y - 26, TABLE_X0 - 14, 52), self.belt, bool(out.get("ESTEIRA")))
        draw.tag(p, 20, LANE_Y + 40, "Q0.0 esteira", out.get("ESTEIRA", False))
        # girador
        p.setPen(QPen(QColor("#7c3aed") if out.get("GIRADOR") else QColor("#94a3b8"), 3))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(TURN_X - 30, LANE_Y), 30, 30)
        draw.tag(p, TURN_X - 90, LANE_Y - 44, "Q0.6 girador", out.get("GIRADOR", False))
        # mesa e placa
        table = QRectF(TABLE_X0, LANE_Y - 30, TABLE_X1 - TABLE_X0, 60)
        draw.metal(p, table, "#94a3b8", 2)
        draw.metal(p, QRectF(TABLE_X1, LANE_Y - 34, 8, 68), "#334155", 1)
        plate = QRectF(TABLE_X0, 150, TABLE_X1 - TABLE_X0, 150)
        p.setPen(QPen(QColor("#334155"), 2))
        p.setBrush(QColor("#1e293b"))
        p.drawRect(plate)
        half = plate.width() / 2 * (1 - self.plate)
        draw.metal(p, QRectF(plate.left(), plate.top(), half, plate.height()), "#64748b", 0)
        draw.metal(p, QRectF(plate.right() - half, plate.top(), half, plate.height()), "#64748b", 0)
        draw.text(p, plate.left() + 4, plate.bottom() + 10, "placa de camada", 7, True, draw.MUTED)
        draw.tag(p, plate.left() + 90, plate.bottom() + 12, "Q0.2 abre", out.get("PLACA", False))
        draw.tag(p, plate.left() + 90, plate.bottom() + 34, "I0.4 fechada", sens["FECHADA"])
        for i, row in enumerate(self.rows):
            x = plate.left() + 2
            for rot in row:
                w, h = (BOX_W, BOX_L) if rot else (BOX_L, BOX_W)
                self._box(p, QRectF(x, plate.top() + 4 + i * 64, w, h), rot)
                x += w
        # caixas na esteira e na mesa
        for b in self.boxes:
            w, h = (BOX_W, BOX_L) if b.rot else (BOX_L, BOX_W)
            if b.x > 14:
                self._box(p, QRectF(max(14.0, b.x - w), LANE_Y - h / 2, min(w, b.x - 14), h), b.rot)
        # empurrador (de cima para baixo)
        push_y = LANE_Y - 70 + self.pusher * 80
        draw.metal(p, QRectF(TABLE_X0 + 20, 34, 140, 10), "#475569", 2)
        draw.metal(p, QRectF(TABLE_X0 + 86, 34, 8, push_y - 34), "#e5e7eb", 1, vertical=True)
        draw.metal(p, QRectF(TABLE_X0 + 4, push_y, TABLE_X1 - TABLE_X0 - 8, 8),
                   "#2563eb" if out.get("EMPURRA") else "#64748b", 2)
        draw.tag(p, TABLE_X1 - 70, 50, "Q0.1", out.get("EMPURRA", False))
        draw.tag(p, TABLE_X1 - 30, 50, "I0.2", sens["REC"])
        draw.tag(p, TABLE_X1 - 30, 70, "I0.3", sens["AVA"])
        draw.beam(p, QPointF(PHOTO_X, LANE_Y - 32), QPointF(PHOTO_X, LANE_Y + 32), sens["FOTO"])
        draw.tag(p, PHOTO_X - 40, LANE_Y + 40, "I0.1 foto", sens["FOTO"])
        # legenda da amarracao
        draw.text(p, 30, 330, "Amarração das camadas", 8, True, draw.INK, w=200)
        for k in range(LAYERS):
            rot = k % 2 == 1
            x0 = 30 + k * 66
            for j in range(3 if not rot else 4):
                w = 20 if not rot else 14
                self._box(p, QRectF(x0 + j * w, 346, w, 22 if not rot else 30), rot)
            draw.text(p, x0, 386, f"{k + 1}ª " + ("girada" if rot else "normal"), 7, False, draw.MUTED, w=64)
        # vista lateral do elevador
        side = QRectF(512, 30, 200, 360)
        draw.card(p, side, "Elevador (vista lateral)")
        floor = side.bottom() - 16
        scale = (side.height() - 60) / 1500.0
        plate_y = floor - PLATE_H * scale
        draw.metal(p, QRectF(side.left() + 20, plate_y - 6, 130, 6), "#334155", 1)
        draw.text(p, side.left() + 152, plate_y - 3, "placa", 7, True, draw.MUTED, w=50)
        base = floor - self.lift * scale
        draw.metal(p, QRectF(side.left() + 26, base, 118, 6), "#475569", 1)
        if self.pallet:
            pallet_r = QRectF(side.left() + 30, base - PALLET_H * scale, 110, PALLET_H * scale)
            draw.metal(p, pallet_r, "#a16207", 1)
            for k, layer in enumerate(self.layers):
                y = pallet_r.top() - (k + 1) * BOX_H * scale
                n = 2 if layer and layer[0] else 3
                for j in range(n):
                    self._box(p, QRectF(pallet_r.left() + j * 110 / n, y, 110 / n, BOX_H * scale), bool(layer and layer[0]))
        p.setPen(QPen(QColor("#64748b"), 2))
        p.drawLine(QPointF(side.left() + 160, floor), QPointF(side.left() + 160, plate_y))
        draw.tag(p, side.left() + 120, base + 18 if base < floor - 30 else floor - 24, "I0.5", sens["ALINHADA"])
        draw.tag(p, side.left() + 8, floor - 8, "I0.6 fundo", sens["FUNDO"])
        draw.tag(p, side.left() + 8, side.top() + 34, "Q0.4 sobe", out.get("SOBE", False))
        draw.tag(p, side.left() + 90, side.top() + 34, "Q0.3 desce", out.get("DESCE", False))
        draw.tag(p, side.left() + 8, side.top() + 56, "Q0.5 pallets", out.get("PALLETS", False))
        draw.tag(p, side.left() + 106, side.top() + 56, "I0.7", sens["PALLET"])
        # painel
        draw.card(p, QRectF(184, 400, 528, 52))
        draw.lcd(p, QRectF(192, 408, 80, 36), f"{len(self._on_table())}/3", "#4ade80", "fila")
        draw.lcd(p, QRectF(278, 408, 80, 36), f"{len(self.rows)}/2", "#4ade80", "filas na placa")
        draw.lcd(p, QRectF(364, 408, 80, 36), f"{len(self.layers)}/4", "#4ade80", "camadas")
        draw.lcd(p, QRectF(450, 408, 80, 36), f"{self.shipped}", "#fbbf24", "pallets prontos")
        draw.lamp(p, QPointF(552, 426), 8, out.get("COMPLETO", False), draw.GREEN)
        draw.text(p, 566, 426, "COMPLETO Q0.7", 7.5, True, w=120)
        draw.switch(p, QRectF(14, 412, 160, 30), "LIGA I0.0", self.is_pressed("LIGA"))
