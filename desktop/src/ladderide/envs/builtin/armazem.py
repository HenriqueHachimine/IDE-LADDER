"""Armazem automatico: transelevador por numero de posicao e mapa de ocupacao das celulas."""
from __future__ import annotations

import random

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register
from ..transport import Belt, Item, carton, emitter_box, remover_box

COLS, LEVELS = 5, 3
CELL_W, CELL_H = 92.0, 84.0
RACK_X0 = 124.0               # borda esquerda da coluna 1
FLOOR = 326.0                 # piso da fileira de baixo
ENTRY_X, EXIT_X = 70.0, 650.0
SPEED_X, SPEED_Z = 170.0, 95.0
FORK_S, LIFT_S = 0.8, 0.4
LIFT_PX = 14.0
BOX_W, BOX_H = 56.0, 44.0
TARGET_WORD, REQUEST_WORD = 10, 1
ENTRY_QUEUE = 3
PALETTE = ("#c08a4a", "#2563eb", "#16a34a", "#9333ea", "#dc2626")


def position(n: int) -> tuple[float, float]:
    """Centro (x) e altura do piso (em px acima de FLOOR) da posicao n (0 entrada, 1..15 celulas, 16 saida)."""
    if n == 0:
        return ENTRY_X, 0.0
    if n == COLS * LEVELS + 1:
        return EXIT_X, 0.0
    c, z = (n - 1) % COLS, (n - 1) // COLS
    return RACK_X0 + CELL_W * (c + 0.5), z * CELL_H


@register
class WarehouseEnvironment(Environment):
    id = "armazem"
    name = "Armazém automático"
    description = ("Um transelevador guarda as caixas que chegam pela esteira de entrada nas 15 células da estante "
                   "e retira as pedidas para a esteira de saída. O programa escreve a posição de destino em N10 (0 "
                   "entrada, 1 a 15 células, numeradas da esquerda para a direita a partir de baixo, 16 saída); I0.1 "
                   "indica parado no destino. Pegar: garfo baixo avança (Q0.1), sobe (Q0.2) e recua. Deixar: garfo "
                   "alto avança, desce e recua. Clique numa caixa da estante para pedir a retirada: o número da "
                   "célula aparece em N1 e o programa zera N1 quando aceita o pedido. O programa precisa lembrar "
                   "quais células estão ocupadas.")
    example = "ambientes/armazem.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("LIGA", "I0.0", "Liga", "Chave LIGA", SWITCH),
        IOPoint("POS", "I0.1", "Em_Posicao", "Transelevador parado no destino"),
        IOPoint("CENTRO", "I0.2", "Garfo_Centro", "Garfo recolhido"),
        IOPoint("ESTENDIDO", "I0.3", "Garfo_Estendido", "Garfo avançado"),
        IOPoint("ENTRADA", "I0.4", "Caixa_Na_Entrada", "Caixa no fim da esteira de entrada"),
        IOPoint("SAIDA", "I0.5", "Saida_Livre", "Início da esteira de saída livre"),
        IOPoint("ALTO", "I0.6", "Garfo_Em_Cima", "Garfo levantado"),
        IOPoint("BAIXO", "I0.7", "Garfo_Embaixo", "Garfo abaixado"),
    ]
    outputs = [
        IOPoint("ESTEIRA_E", "Q0.0", "Esteira_Entrada", "Esteira de entrada"),
        IOPoint("AVANCA", "Q0.1", "Garfo_Avanca", "Garfo: avança"),
        IOPoint("SOBE", "Q0.2", "Garfo_Sobe", "Garfo: sobe"),
        IOPoint("ESTEIRA_S", "Q0.3", "Esteira_Saida", "Esteira de saída"),
        IOPoint("CHEIO", "Q0.4", "Luz_Cheio", "Lâmpada ARMAZÉM CHEIO"),
        IOPoint("LUZ", "Q0.5", "Luz_Operando", "Lâmpada operando"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(31)
        self.entry = Belt(-40.0, ENTRY_X + BOX_W / 2, 110.0)
        self.exit = Belt(EXIT_X - BOX_W / 2, 760.0, 110.0)
        self.cells: dict[int, Item] = {}
        self.x, self.z = ENTRY_X, 0.0
        self.target = 0
        self.fork = 0.0
        self.lift = 0.0
        self.load: Item | None = None
        self.next_box = 2.0
        self.next_id = 1
        self.queue: list[int] = []        # pedidos ainda nao entregues ao CLP
        self.asked: list[int] = []        # ids das caixas pedidas
        self.to_write = 0
        self.n1 = 0
        self.auto_t = 0.0
        self.stored = 0
        self.delivered = 0
        self.flags: dict[str, str] = {}
        self.operator.setdefault("AUTO", True)

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    def _here(self) -> int | None:
        for n in range(COLS * LEVELS + 2):
            x, z = position(n)
            if abs(self.x - x) < 1 and abs(self.z - z) < 1:
                return n
        return None

    def _box_at(self, n: int) -> Item | None:
        if n == 0:
            return next((i for i in self.entry.items if i.x >= self.entry.x1 - 0.5), None)
        if n == COLS * LEVELS + 1:
            return next((i for i in self.exit.items if i.back < self.exit.x0 + BOX_W + 4), None)
        return self.cells.get(n)

    # ------------------------------------------------------------ operador
    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.operator["AUTO"] = not self.operator.get("AUTO", True)
        elif key.startswith("CEL"):
            self._request(int(key[3:]))

    def _request(self, n: int) -> None:
        box = self.cells.get(n)
        if box is not None and box.data["id"] not in self.asked:
            self.asked.append(box.data["id"])
            self.queue.append(n)

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        # chegada de caixas
        self.next_box -= dt
        if self.next_box <= 0 and len(self.entry.items) < ENTRY_QUEUE and self.entry.clear_from(self.entry.x0, BOX_W):
            color = self.next_id % len(PALETTE)
            self.entry.items.append(Item(self.entry.x0, BOX_W, color, {"id": self.next_id}))
            self.next_id += 1
            self.next_box = self.rng.uniform(7.0, 14.0)
        self.entry.move(dt, bool(out["ESTEIRA_E"]), end=self.entry.x1)
        self.exit.move(dt, bool(out["ESTEIRA_S"]))
        self.exit.take(lambda i: i.back > 720)
        # pedidos automaticos do operador
        self.auto_t += dt
        if self.operator.get("AUTO", True) and self.auto_t >= 25.0 and len(self.cells) >= 6:
            self.auto_t = 0.0
            free = [n for n, b in self.cells.items() if b.data["id"] not in self.asked]
            if free:
                self._request(self.rng.choice(sorted(free)))
        # transelevador
        if not 0 <= self.target <= COLS * LEVELS + 1:
            self._flag("range", "Destino fora de 0 a 16 em N10")
            tx, tz = self.x, self.z
        else:
            tx, tz = position(self.target)
        if (abs(tx - self.x) > 0.01 or abs(tz - self.z) > 0.01):
            if self.fork > 0.03:
                self._flag("travel", "Transelevador mandado andar com o garfo estendido")
            else:
                self.x = approach(self.x, tx, SPEED_X, SPEED_X, dt)
                self.z = approach(self.z, tz, SPEED_Z, SPEED_Z, dt)
        here = self._here()
        box = self._box_at(here) if here is not None else None
        # garfo
        f0, l0 = self.fork, self.lift
        self.fork = approach(self.fork, 1.0 if out["AVANCA"] else 0.0, 1 / FORK_S, 1 / FORK_S, dt)
        self.lift = approach(self.lift, 1.0 if out["SOBE"] else 0.0, 1 / LIFT_S, 1 / LIFT_S, dt)
        if f0 < 0.5 <= self.fork:
            if here is None:
                self._flag("rack", "Garfo avançou fora de uma posição: bateu na estante")
            elif self.load is not None and box is not None:
                self._flag("hit", "A caixa do garfo bateu em outra caixa: posição ocupada")
            elif self.load is not None and self.lift < 0.9:
                self._flag("low", "Garfo carregado avançou baixo: a caixa bateu na longarina")
            elif self.load is None and box is not None and self.lift > 0.1:
                self._flag("high", "Garfo vazio avançou alto e bateu na caixa")
        if f0 >= 0.98 > self.fork and 0.02 < self.lift < 0.98:
            self._flag("mid", "Garfo recolhido antes de terminar de subir ou descer")
        if self.fork >= 0.98 and here is not None:
            if l0 < 0.5 <= self.lift and self.load is None and box is not None:
                self._take(here, box)
            elif l0 >= 0.5 > self.lift and self.load is not None:
                if box is not None:
                    self._flag("hit", "A caixa do garfo bateu em outra caixa: posição ocupada")
                else:
                    self._put(here)

    def _take(self, n: int, box: Item) -> None:
        if n == 0:
            self.entry.items.remove(box)
        elif n == COLS * LEVELS + 1:
            self.exit.items.remove(box)
        else:
            del self.cells[n]
        self.load = box

    def _put(self, n: int) -> None:
        box, self.load = self.load, None
        if n == 0:
            self._flag("back", "Caixa devolvida para a esteira de entrada")
        elif n == COLS * LEVELS + 1:
            box.x = self.exit.x0 + BOX_W
            self.exit.items.append(box)
            if box.data["id"] in self.asked:
                self.asked.remove(box.data["id"])
                self.delivered += 1
            else:
                self._flag("unasked", "Caixa retirada sem pedido do operador")
        else:
            self.cells[n] = box
            self.stored += 1

    def sensors(self) -> dict[str, bool]:
        tx, tz = position(self.target) if 0 <= self.target <= COLS * LEVELS + 1 else (-99, -99)
        return {"POS": abs(self.x - tx) < 0.5 and abs(self.z - tz) < 0.5, "CENTRO": self.fork <= 0.02,
                "ESTENDIDO": self.fork >= 0.98, "ENTRADA": self._box_at(0) is not None,
                "SAIDA": self._box_at(COLS * LEVELS + 1) is None, "ALTO": self.lift >= 0.98,
                "BAIXO": self.lift <= 0.02}

    def input_words(self) -> dict[int, int]:
        if self.queue and self.n1 == 0 and not self.to_write:
            self.to_write = self.queue.pop(0)
            return {REQUEST_WORD: self.to_write}
        return {}

    def advance_words(self, n: list[int]) -> None:
        if len(n) > TARGET_WORD:
            self.target = n[TARGET_WORD]
            self.n1 = n[REQUEST_WORD]
            if self.to_write and self.n1 != self.to_write:
                self.to_write = 0                     # o programa aceitou (zerou ou trocou) o pedido

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        return [f"Caixas na estante: {len(self.cells)}/15 | guardadas: {self.stored} | entregues: {self.delivered}",
                f"Pedidos esperando: {len(self.asked)} | fila de entrada: {len(self.entry.items)} | destino N10 = "
                f"{self.target}"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        ctl = {"LIGA": (16, 412, 150, 30), "AUTO": (176, 412, 170, 30)}
        for n in self.cells:
            x, z = position(n)
            ctl[f"CEL{n}"] = (x - CELL_W / 2 + 4, FLOOR - z - CELL_H + 6, CELL_W - 8, CELL_H - 8)
        return ctl

    def _carton(self, p: QPainter, x: float, floor: float, box: Item, mark: bool = False) -> None:
        carton(p, QRectF(x - BOX_W / 2, floor - BOX_H, BOX_W, BOX_H), PALETTE[box.kind], str(box.data["id"]),
               highlight=mark)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460)
        out, sens = self.out, self.sensors()
        p.setPen(QPen(QColor("#cbd5e1"), 1))
        p.setBrush(QColor("#e2e8f0"))
        p.drawRoundedRect(QRectF(8, 28, 704, 370), 8, 8)
        # estante
        asked = set(self.asked)
        for n in range(1, COLS * LEVELS + 1):
            x, z = position(n)
            r = QRectF(x - CELL_W / 2, FLOOR - z - CELL_H, CELL_W, CELL_H)
            p.setPen(QPen(QColor("#94a3b8"), 1))
            p.setBrush(QColor("#f1f5f9"))
            p.drawRect(r)
            draw.text(p, r.left() + 4, r.top() + 9, str(n), 7, True, draw.MUTED, w=30)
            if n in self.cells:
                self._carton(p, x, FLOOR - z - 2, self.cells[n], self.cells[n].data["id"] in asked)
        for z in range(LEVELS + 1):
            draw.metal(p, QRectF(RACK_X0 - 4, FLOOR - z * CELL_H - 3, COLS * CELL_W + 8, 6), "#ea580c", 1)
        for c in range(COLS + 1):
            draw.metal(p, QRectF(RACK_X0 + c * CELL_W - 3, FLOOR - LEVELS * CELL_H, 6, LEVELS * CELL_H),
                       "#2563eb", 1, vertical=True)
        # esteiras
        draw.conveyor(p, QRectF(14, FLOOR + 2, self.entry.x1 - 14, 22), self.entry.offset, bool(out.get("ESTEIRA_E")))
        emitter_box(p, QRectF(10, FLOOR - 50, 16, 76), bool(out.get("ESTEIRA_E")), "")
        for it in self.entry.items:
            if it.x > 26:
                self._carton(p, max(26 + BOX_W / 2, it.center), FLOOR + 2, it)
        draw.conveyor(p, QRectF(self.exit.x0, FLOOR + 2, 704 - self.exit.x0, 22), self.exit.offset,
                      bool(out.get("ESTEIRA_S")))
        remover_box(p, QRectF(700, FLOOR - 50, 12, 76), "")
        for it in self.exit.items:
            if it.back < 700:
                self._carton(p, min(it.center, 700 - BOX_W / 2), FLOOR + 2, it)
        # transelevador
        rail_y = FLOOR + 32
        draw.metal(p, QRectF(30, rail_y, 660, 6), "#475569", 2)
        draw.metal(p, QRectF(30, 50, 660, 6), "#475569", 2)
        draw.metal(p, QRectF(self.x - 4, 54, 8, rail_y - 54), "#facc15", 2, vertical=True)
        draw.metal(p, QRectF(self.x - 26, rail_y - 10, 52, 12), "#334155", 3)
        car_floor = FLOOR - self.z + 2 - self.lift * LIFT_PX
        car = QRectF(self.x - 34, car_floor, 68, 8)
        ext = self.fork
        draw.metal(p, car, "#f97316" if ext < 0.02 else draw.mix(QColor("#f97316"), QColor("#7c2d12"), ext), 2)
        if self.load is not None:
            self._carton(p, self.x, car_floor, self.load)
        draw.bar(p, QRectF(self.x - 30, car_floor + 12, 60, 5), ext, "#f97316")
        # etiquetas
        draw.tag(p, 16, 52, "Q0.0 entrada", out.get("ESTEIRA_E", False))
        draw.tag(p, 16, 74, "I0.4 caixa", sens["ENTRADA"])
        draw.tag(p, 610, 52, "Q0.3 saída", out.get("ESTEIRA_S", False))
        draw.tag(p, 610, 74, "I0.5 livre", sens["SAIDA"])
        row = [("I0.1 em posição", sens["POS"]), ("I0.2 centro", sens["CENTRO"]),
               ("I0.3 estendido", sens["ESTENDIDO"]), ("I0.6 alto", sens["ALTO"]), ("I0.7 baixo", sens["BAIXO"]),
               ("Q0.1 avança", out.get("AVANCA", False)), ("Q0.2 sobe", out.get("SOBE", False))]
        x = 20.0
        for label, on in row:
            draw.tag(p, x, rail_y + 22, label, on)
            x += 12 + 6.2 * len(label)
        # painel
        draw.switch(p, QRectF(16, 412, 150, 30), "LIGA I0.0", self.is_pressed("LIGA"))
        draw.switch(p, QRectF(176, 412, 170, 30), "Pedidos automáticos", self.operator.get("AUTO", True))
        draw.lcd(p, QRectF(356, 408, 70, 38), str(self.target), "#fbbf24", "N10 destino")
        draw.lcd(p, QRectF(432, 408, 70, 38), str(self.n1 or "-"), "#c084fc", "N1 pedido")
        draw.lcd(p, QRectF(508, 408, 70, 38), f"{len(self.cells)}", "#4ade80", "na estante")
        draw.stack_light(p, 600, 410, [(bool(out.get("CHEIO")), draw.AMBER), (bool(out.get("LUZ")), draw.GREEN)], 12)
        draw.text(p, 614, 418, "Q0.4 cheio", 7, True, draw.MUTED, w=90)
        draw.text(p, 614, 432, "Q0.5 operando", 7, True, draw.MUTED, w=90)
        draw.text(p, 200, 39, "Clique numa caixa para pedir a retirada", 7.5, True, draw.MUTED, w=300)
