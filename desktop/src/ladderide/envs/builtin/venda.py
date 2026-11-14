"""Maquina de venda: tres produtos com precos configuraveis, teclado por registrador e troco com duas moedas."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..registry import register

PRODUCTS = {"A": ("Lata", "#dc2626", 250), "B": ("Suco", "#f97316", 375), "C": ("Água", "#0ea5e9", 175)}
STOCK0 = {"A": 6, "B": 2, "C": 4}
COINS = {"M25": 25, "M50": 50, "M100": 100}
ROLL_MS, PULSE_MS = 300, 60          # moeda rola 0,3 s ate o sensor e gera um pulso de 60 ms
TURN_MS = 1500                       # uma volta da espiral entrega um produto
DROP_AT = 0.8                        # o produto cai com 80% da volta
FALL_MS, DROP_PULSE_MS = 300, 100
SOLENOID_MS = 50                     # cada ejetor precisa de 50 ms desligado entre moedas
SPIRAL_MAX_MS = 6000
TUBE_MAX = {"T25": 30, "T50": 20}
CREDIT_WORD, PRICE_WORDS, KEY_WORD = 0, {"A": 1, "B": 2, "C": 3}, 4


def money(cents: int) -> str:
    return f"R$ {cents / 100:.2f}".replace(".", ",")


@register
class VendingEnvironment(Environment):
    id = "venda"
    name = "Máquina de venda (preços e troco)"
    description = ("Moedas de R$ 0,25, 0,50 e 1,00 dão um pulso cada; o programa soma o crédito em N0 (centavos), "
                   "mostrado no display. Os preços ficam em N1, N2 e N3 (o dono ajusta com a porta de serviço "
                   "aberta, I0.7; com ela aberta a máquina não vende). O teclado escreve o produto escolhido (1, 2 "
                   "ou 3) em N4 e o programa deve zerar N4 depois de ler. A espiral gira até o sensor de queda; sem "
                   "queda em 3 s o produto acabou. Troco: as moedas de 0,25 e 0,50 recebidas vão para dois tubos com "
                   "ejetores (um pulso = uma moeda). Use a moeda de 0,50 enquanto der; com o tubo de 0,25 vazio só "
                   "valor exato. O que não der para devolver continua no display.")
    example = "ambientes/venda.ladproj"
    size = (720, 470)
    inputs = [
        IOPoint("M25", "I0.0", "Moeda_25", "Sensor de moeda de R$ 0,25 (pulso)"),
        IOPoint("M50", "I0.1", "Moeda_50", "Sensor de moeda de R$ 0,50 (pulso)"),
        IOPoint("M100", "I0.2", "Moeda_100", "Sensor de moeda de R$ 1,00 (pulso)"),
        IOPoint("QUEDA", "I0.3", "Sensor_Queda", "Sensor de queda do produto"),
        IOPoint("DEVOLVER", "I0.4", "Devolver", "Botão DEVOLVER MOEDAS", BUTTON),
        IOPoint("T25_VAZIO", "I0.5", "Tubo_25_Vazio", "Tubo de troco de R$ 0,25 vazio"),
        IOPoint("T50_VAZIO", "I0.6", "Tubo_50_Vazio", "Tubo de troco de R$ 0,50 vazio"),
        IOPoint("PORTA", "I0.7", "Porta_Servico", "Porta de serviço aberta (chave)", SWITCH),
    ]
    outputs = [
        IOPoint("ESP_A", "Q0.0", "Espiral_A", "Motor da espiral 1 (lata)"),
        IOPoint("ESP_B", "Q0.1", "Espiral_B", "Motor da espiral 2 (suco)"),
        IOPoint("ESP_C", "Q0.2", "Espiral_C", "Motor da espiral 3 (água)"),
        IOPoint("EJ25", "Q0.3", "Ejetor_25", "Ejetor do tubo de R$ 0,25 (uma moeda por pulso)"),
        IOPoint("EJ50", "Q0.4", "Ejetor_50", "Ejetor do tubo de R$ 0,50 (uma moeda por pulso)"),
        IOPoint("PRONTO", "Q0.5", "Lampada_Pronto", "Lâmpada PRONTO"),
        IOPoint("ESGOTADO", "Q0.6", "Lampada_Esgotado", "Lâmpada PRODUTO ESGOTADO"),
        IOPoint("SEM_TROCO", "Q0.7", "Lampada_Sem_Troco", "Lâmpada SEM TROCO (só valor exato)"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(21)
        self.auto = getattr(self, "auto", False)
        self.prices = getattr(self, "prices", {k: v[2] for k, v in PRODUCTS.items()})
        self.stock = dict(STOCK0)
        self.angle = {p: 0.0 for p in PRODUCTS}
        self.coins_in: list[tuple[int, str]] = []        # (instante em que o sensor ve, moeda)
        self.pulses: dict[str, int] = {}                  # sensor -> fim do pulso
        self.falling: list[tuple[int, str]] = []
        self.tray: list[str] = []                         # produtos na porta de retirada
        self.change_tray: list[int] = []
        self.tubes = {"T25": 8, "T50": 4}
        self.cashbox = 0
        self.inserted = self.returned = self.delivered = 0
        self.display: int | None = None
        self.key_pending = 0
        self.key_shown = 0
        self._ej_prev = {"EJ25": False, "EJ50": False}
        self._ej_off = {"EJ25": SOLENOID_MS, "EJ50": SOLENOID_MS}
        self.run_ms = {p: 0 for p in PRODUCTS}
        self.drops_in_run = {p: 0 for p in PRODUCTS}
        self.idle_ms = 0
        self.flags: dict[str, str] = {}
        self.sales = 0
        self.coins_returned = 0
        self._script: list[tuple[int, str]] = []
        self.next_customer_ms = 2000

    # ------------------------------------------------------- registradores
    def input_words(self) -> dict[int, int]:
        words = {PRICE_WORDS[p]: self.prices[p] for p in PRODUCTS}
        if self.key_pending:
            words[KEY_WORD] = self.key_pending
            self.key_pending = 0
        return words

    def advance_words(self, n: list[int]) -> None:
        self.display = n[CREDIT_WORD] if len(n) > CREDIT_WORD else None
        self.key_shown = n[KEY_WORD] if len(n) > KEY_WORD else 0

    # ---------------------------------------------------------- operador
    def _insert(self, coin: str) -> None:
        last = self.coins_in[-1][0] if self.coins_in else self.time_ms
        self.coins_in.append((max(self.time_ms + ROLL_MS, last + 200), coin))

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key in ("C25", "C50", "C100"):
            self._insert("M" + key[1:])
        elif key in ("K1", "K2", "K3"):
            self.key_pending = int(key[1])
        elif key == "REABASTECER" and self.is_pressed("PORTA"):
            self.stock = {p: 6 for p in PRODUCTS}
            self.tubes = {"T25": 20, "T50": 10}
        elif key.startswith("P") and key[1] in PRODUCTS and self.is_pressed("PORTA"):
            step = 25 if key[2] == "+" else -25
            self.prices[key[1]] = max(50, min(1000, self.prices[key[1]] + step))
        elif key == "RETIRAR":
            self.tray.clear()
            self.change_tray.clear()
        elif key == "AUTO":
            self.auto = not self.auto

    def press(self, key: str, down: bool) -> None:
        if key in ("C25", "C50", "C100", "K1", "K2", "K3", "REABASTECER", "RETIRAR", "AUTO") or \
                (len(key) == 3 and key[0] == "P" and key[1] in PRODUCTS):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _customer(self) -> None:
        """Cliente automatico: escolhe um produto, paga (as vezes a mais) e digita o codigo."""
        product = self.rng.choice("AABC")
        price = self.prices[product]
        t, paid = self.time_ms, 0
        while paid < price + (25 if self.rng.random() < 0.5 else 0):
            coin = self.rng.choice(["M25", "M50", "M100", "M100"])
            self._script.append((t, coin))
            paid += COINS[coin]
            t += 250
        if self.rng.random() < 0.15:
            self._script.append((t + 800, "DEVOLVER"))
        else:
            self._script.append((t + 800, "K" + str(" ABC".index(product))))

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        now = self.time_ms
        if self.operator.get("DEVOLVER") and self.pulses.get("DEVOLVER", 0) and now >= self.pulses["DEVOLVER"]:
            self.operator["DEVOLVER"] = False
        if self.auto and not self._script and now >= self.next_customer_ms and self.idle_ms > 1500 \
                and not self.is_pressed("PORTA"):
            self._customer()
            self.next_customer_ms = now + 9000
        for t, action in list(self._script):
            if now >= t:
                self._script.remove((t, action))
                if action in COINS:
                    self._insert(action)
                elif action.startswith("K"):
                    self.key_pending = int(action[1])
                else:
                    self.operator[action] = True
                    self.clicked.add(action)
                    self.pulses[action] = now + 200
        # moedas chegando aos sensores
        for t, coin in list(self.coins_in):
            if now >= t:
                self.coins_in.remove((t, coin))
                self.pulses[coin] = now + PULSE_MS
                self.inserted += COINS[coin]
                tube = {"M25": "T25", "M50": "T50"}.get(coin)
                if tube and self.tubes[tube] < TUBE_MAX[tube]:
                    self.tubes[tube] += 1
                else:
                    self.cashbox += COINS[coin]
        # espirais
        running = [p for p in PRODUCTS if out["ESP_" + p]]
        if len(running) > 1:
            self.flags.setdefault("both", "Duas espirais giraram ao mesmo tempo")
        if running and self.is_pressed("PORTA"):
            self.flags.setdefault("door", "Espiral girou com a porta de serviço aberta (perigo para o repositor)")
        for p in PRODUCTS:
            if out["ESP_" + p]:
                old = self.angle[p]
                self.angle[p] += dt_ms / TURN_MS
                self.run_ms[p] += dt_ms
                if math.floor(self.angle[p] - DROP_AT) > math.floor(old - DROP_AT) and self.stock[p] > 0:
                    self.stock[p] -= 1
                    self.falling.append((now + FALL_MS, p))
                    self.drops_in_run[p] += 1
                    if self.drops_in_run[p] > 1:
                        self.flags.setdefault("double", "A espiral continuou girando e entregou dois produtos: "
                                                        "pare a espiral no sensor de queda")
                if self.run_ms[p] > SPIRAL_MAX_MS:
                    self.flags.setdefault("spin", "Espiral girando há mais de 6 s: o produto acabou? Use um "
                                                  "tempo máximo")
            else:
                self.run_ms[p] = 0
                self.drops_in_run[p] = 0
        for t, p in list(self.falling):
            if now >= t:
                self.falling.remove((t, p))
                self.pulses["QUEDA"] = now + DROP_PULSE_MS
                self.tray.append(p)
                self.delivered += self.prices[p]
                self.sales += 1
        # ejetores de troco
        owed = self.inserted - self.returned - self.delivered
        for key, tube, value in (("EJ50", "T50", 50), ("EJ25", "T25", 25)):
            on = out[key]
            if on and not self._ej_prev[key] and self._ej_off[key] >= SOLENOID_MS and self.tubes[tube] > 0:
                if value == 25 and owed >= 50 and self.tubes["T50"] > 0:
                    self.flags.setdefault("coins", "Troco com moedas de R$ 0,25 havendo R$ 0,50 no tubo: devolva "
                                                   "primeiro a moeda maior")
                self.tubes[tube] -= 1
                self.change_tray.append(value)
                self.returned += value
                self.coins_returned += 1
                owed -= value
            self._ej_off[key] = 0 if on else self._ej_off[key] + dt_ms
            self._ej_prev[key] = on
        # conferencia do caixa (o cliente nao pode perder nem ganhar dinheiro)
        balance = self.inserted - self.returned - self.delivered
        busy = any(out["ESP_" + p] for p in PRODUCTS) or out["EJ25"] or out["EJ50"] or self.coins_in or \
            self.falling or self._script
        self.idle_ms = 0 if busy else self.idle_ms + dt_ms
        if balance < 0:
            self.flags.setdefault("loss", "A máquina entregou mais do que recebeu (prejuízo)")
        if self.idle_ms > 2500 and self.display is not None and self.display != balance:
            self.flags.setdefault("display", "O display (N0) não mostra o crédito real")
        if self.idle_ms > 4000 and self.display == 0 and balance > 0:
            self.flags.setdefault("lost", "O cliente perdeu dinheiro: faltou devolver o troco")
        if self.idle_ms > 3000 and self.key_shown:
            self.flags.setdefault("key", "A tecla escolhida (N4) não foi zerada pelo programa")

    def sensors(self) -> dict[str, bool]:
        now = self.time_ms
        return {"M25": now < self.pulses.get("M25", 0), "M50": now < self.pulses.get("M50", 0),
                "M100": now < self.pulses.get("M100", 0), "QUEDA": now < self.pulses.get("QUEDA", 0),
                "T25_VAZIO": self.tubes["T25"] <= 0, "T50_VAZIO": self.tubes["T50"] <= 0}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        shown = "--" if self.display is None else money(self.display)
        stock = ", ".join(f"{PRODUCTS[p][0].lower()} {self.stock[p]}" for p in PRODUCTS)
        return [f"Display (N0): {shown} | vendas: {self.sales} | estoque: {stock}",
                f"Recebido {money(self.inserted)} | troco {money(self.returned)} em {self.coins_returned} moedas | "
                f"tubos: {self.tubes['T25']} x 0,25 e {self.tubes['T50']} x 0,50"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        c = {"C25": (514, 40, 94, 26), "C50": (514, 70, 94, 26), "C100": (514, 100, 94, 26),
             "K1": (380, 132, 30, 30), "K2": (414, 132, 30, 30), "K3": (448, 132, 30, 30),
             "DEVOLVER": (380, 168, 98, 26), "RETIRAR": (200, 398, 80, 26), "AUTO": (514, 140, 194, 26),
             "PORTA": (514, 260, 194, 26), "REABASTECER": (514, 428, 194, 26)}
        for k, p in enumerate(PRODUCTS):
            c[f"P{p}-"] = (604, 300 + k * 40, 24, 24)
            c[f"P{p}+"] = (684, 300 + k * 40, 24, 24)
        return c

    def _product(self, p: QPainter, r: QRectF, prod: str) -> None:
        col = QColor(PRODUCTS[prod][1])
        g = QLinearGradient(r.topLeft(), r.topRight())
        g.setColorAt(0, col.darker(130))
        g.setColorAt(0.4, col.lighter(130))
        g.setColorAt(1, col.darker(150))
        p.setPen(QPen(QColor("#0f172a"), 1))
        p.setBrush(g)
        p.drawRoundedRect(r, 4, 4)
        p.setBrush(QColor(255, 255, 255, 160))
        p.drawRect(QRectF(r.left() + 3, r.center().y() - 4, r.width() - 6, 8))

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 470)
        draw.ground(p, 440, 720, 470)
        out = self.out
        sens = self.sensors()
        door = self.is_pressed("PORTA")
        # gabinete
        body = QRectF(20, 14, 480, 426)
        draw.shadow(p, body, 12, 6)
        g = QLinearGradient(body.topLeft(), body.topRight())
        g.setColorAt(0, QColor("#1e3a8a"))
        g.setColorAt(0.5, QColor("#2563eb"))
        g.setColorAt(1, QColor("#1e3a8a"))
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.setBrush(g)
        p.drawRoundedRect(body, 12, 12)
        glass = QRectF(36, 30, 320, 330)
        p.setBrush(QColor("#0b1220"))
        p.drawRoundedRect(glass, 6, 6)
        # prateleiras com espirais e produtos
        for row, prod in enumerate(PRODUCTS):
            y = glass.top() + 100 + row * 104
            name, color, _ = PRODUCTS[prod]
            p.setPen(QPen(QColor("#94a3b8"), 2))
            for k in range(11):                               # espiral
                x = glass.left() + 16 + k * 26 + (self.angle[prod] % 1.0) * 26
                if x < glass.right() - 10:
                    p.drawArc(QRectF(x - 10, y - 12, 20, 24), 0, 180 * 16)
            for k in range(self.stock[prod]):
                x = glass.left() + 18 + k * 44 + (self.angle[prod] % 1.0) * 30
                if x < glass.right() - 32:
                    self._product(p, QRectF(x, y - 56, 30, 54), prod)
            draw.metal(p, QRectF(glass.left() + 4, y + 10, glass.width() - 8, 6), "#64748b", 1)
            draw.plate(p, QRectF(glass.left() + 8, y + 18, 98, 16), f"{row + 1}  {name}  {money(self.prices[prod])}",
                       "#0f172a", QColor("#fde68a"), 7)
            draw.tag(p, glass.right() - 92, y + 26, f"Q0.{row} espiral", out.get("ESP_" + prod, False))
        for t, prod in self.falling:
            frac = 1 - (t - self.time_ms) / FALL_MS
            self._product(p, QRectF(glass.right() - 70, glass.top() + 100 + 240 * frac, 30, 54), prod)
        if self.is_pressed("PORTA"):
            p.setBrush(QColor(250, 204, 21, 60))
            p.setPen(QPen(QColor("#facc15"), 3, Qt.DashLine))
            p.drawRoundedRect(glass, 6, 6)
            draw.plate(p, QRectF(glass.center().x() - 70, glass.top() + 8, 140, 22), "PORTA ABERTA - SERVIÇO",
                       "#a16207", QColor("#fef9c3"))
        # porta de retirada
        tray = QRectF(36, 370, 240, 56)
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.setBrush(QColor("#020617"))
        p.drawRoundedRect(tray, 6, 6)
        for k, prod in enumerate(self.tray[:5]):
            self._product(p, QRectF(tray.left() + 8 + k * 46, tray.top() + 26, 48, 24), prod)
        draw.tag(p, tray.left() + 6, tray.top() + 10, "I0.3 queda", sens["QUEDA"])
        draw.push_button(p, QRectF(200, 398, 80, 26), "Retirar", False, draw.GREEN)
        # painel do cliente
        panel = QRectF(366, 30, 124, 400)
        p.setBrush(QColor("#0f172a"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(panel, 6, 6)
        text = "--" if self.display is None else money(self.display)
        draw.lcd(p, QRectF(374, 40, 108, 40), text, "#4ade80", "CRÉDITO N0")
        draw.text(p, 376, 92, "Escolha (N4)", 7, True, QColor("#cbd5e1"), w=100)
        draw.lcd(p, QRectF(440, 86, 42, 24), str(self.key_shown or "-"), "#fbbf24")
        for k in range(3):
            r = QRectF(380 + k * 34, 132, 30, 30)
            draw.metal(p, r, "#cbd5e1", 4)
            draw.ctext(p, r.center().x(), r.center().y(), str(k + 1), 11, True, draw.INK, 30)
        draw.push_button(p, QRectF(380, 168, 98, 26), "DEVOLVER", self.is_pressed("DEVOLVER"), QColor("#64748b"))
        lamps = (("PRONTO Q0.5", "PRONTO", draw.GREEN), ("ESGOTADO Q0.6", "ESGOTADO", draw.AMBER),
                 ("SEM TROCO Q0.7", "SEM_TROCO", draw.RED))
        for k, (label, key, col) in enumerate(lamps):
            draw.lamp(p, QPointF(382, 214 + k * 22), 6.5, out.get(key, False), col)
            draw.text(p, 394, 214 + k * 22, label, 6.8, True, draw.WHITE, w=96)
        draw.metal(p, QRectF(452, 286, 26, 6), "#020617", 2)
        draw.text(p, 376, 289, "moedas", 7, True, QColor("#cbd5e1"), w=60)
        for k, (key, label) in enumerate((("M25", "0,25"), ("M50", "0,50"), ("M100", "1,00"))):
            draw.tag(p, 376, 310 + k * 20, f"I0.{k} {label}", sens[key])
        change = QRectF(376, 372, 104, 50)
        p.setBrush(QColor("#020617"))
        p.drawRoundedRect(change, 6, 6)
        for k, v in enumerate(self.change_tray[-10:]):
            c = QPointF(change.left() + 12 + (k % 5) * 20, change.top() + 16 + (k // 5) * 18)
            p.setPen(QPen(QColor("#475569"), 1))
            p.setBrush(QColor("#e5e7eb") if v == 25 else QColor("#facc15"))
            p.drawEllipse(c, 7 if v == 25 else 8, 7 if v == 25 else 8)
        draw.text(p, 380, 432, "troco", 7, True, draw.WHITE, w=50)
        # cliente
        draw.card(p, QRectF(508, 14, 206, 160), "Cliente")
        draw.push_button(p, QRectF(514, 40, 94, 26), "R$ 0,25", False, QColor("#e5e7eb"))
        draw.push_button(p, QRectF(514, 70, 94, 26), "R$ 0,50", False, QColor("#facc15"))
        draw.push_button(p, QRectF(514, 100, 94, 26), "R$ 1,00", False, QColor("#eab308"))
        draw.text(p, 616, 54, "clique nas", 7, False, draw.MUTED, w=90)
        draw.text(p, 616, 68, "teclas 1, 2, 3", 7, False, draw.MUTED, w=90)
        draw.text(p, 616, 82, "do painel azul", 7, False, draw.MUTED, w=90)
        draw.switch(p, QRectF(514, 140, 194, 26), "Clientes automáticos", self.auto)
        # dono / repositor
        draw.card(p, QRectF(508, 184, 206, 276), "Dono (porta de serviço)")
        for k, (key, tube, label) in enumerate((("T25_VAZIO", "T25", "0,25"), ("T50_VAZIO", "T50", "0,50"))):
            y = 214 + k * 22
            draw.text(p, 516, y, f"Tubo {label}: {self.tubes[tube]}", 7.5, True, w=90)
            draw.bar(p, QRectF(606, y - 4, 40, 8), self.tubes[tube] / TUBE_MAX[tube], draw.AMBER)
            draw.tag(p, 652, y, f"I0.{5 + k}", sens[key])
        draw.switch(p, QRectF(514, 260, 194, 26), "Porta aberta I0.7", door)
        for k, prod in enumerate(PRODUCTS):
            y = 300 + k * 40
            draw.push_button(p, QRectF(604, y, 24, 24), "", False, draw.RED if door else QColor("#94a3b8"))
            draw.push_button(p, QRectF(684, y, 24, 24), "", False, draw.GREEN if door else QColor("#94a3b8"))
            draw.text(p, 516, y + 12, f"N{k + 1} {PRODUCTS[prod][0]}", 7.5, True, w=86)
            draw.lcd(p, QRectF(630, y, 52, 24), f"{self.prices[prod] / 100:.2f}".replace(".", ","), "#fbbf24")
        draw.text(p, 606, 286, "−", 9, True, draw.MUTED, w=20)
        draw.text(p, 688, 286, "+", 9, True, draw.MUTED, w=20)
        draw.push_button(p, QRectF(514, 428, 194, 26), "Reabastecer (porta aberta)", False,
                         draw.BLUE if door else QColor("#94a3b8"))
