"""Maquina de venda de bebidas: credito em N0, moedas por pulso, espirais e troco moeda a moeda."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen

from .. import draw
from ..base import BUTTON, Environment, IOPoint
from ..registry import register

PRICES = {"A": 250, "B": 375}        # centavos: lata R$ 2,50 e suco R$ 3,75
COINS = {"M25": 25, "M50": 50, "M100": 100}
ROLL_MS, PULSE_MS = 300, 60          # moeda rola 0,3 s ate o sensor e gera um pulso de 60 ms
TURN_MS = 1500                       # uma volta da espiral entrega um produto
DROP_AT = 0.8                        # o produto cai com 80% da volta
FALL_MS, DROP_PULSE_MS = 300, 100
SOLENOID_MS = 50                     # o ejetor de troco precisa de 50 ms desligado entre moedas
SPIRAL_MAX_MS = 6000
CREDIT_WORD = 0


def money(cents: int) -> str:
    return f"R$ {cents / 100:.2f}".replace(".", ",")


@register
class VendingEnvironment(Environment):
    id = "venda"
    name = "Máquina de venda de bebidas"
    description = ("Moedas de R$ 0,25, 0,50 e 1,00 passam por sensores que dão um pulso cada. O programa soma o "
                   "crédito em N0 (centavos), mostrado no display. A lata (A) custa R$ 2,50 e o suco (B) R$ 3,75. A "
                   "espiral gira até o produto cair (sensor de queda); se não cair em 3 s o produto acabou e o crédito "
                   "volta. O troco sai moeda a moeda de R$ 0,25: cada pulso no ejetor (ligado, depois desligado ao "
                   "menos 50 ms) solta uma. As moedas de 0,25 recebidas vão para o tubo de troco; com o tubo vazio "
                   "o crédito que falta devolver deve continuar no display.")
    example = "ambientes/venda.ladproj"
    inputs = [
        IOPoint("M25", "I0.0", "Moeda_25", "Sensor de moeda de R$ 0,25 (pulso)"),
        IOPoint("M50", "I0.1", "Moeda_50", "Sensor de moeda de R$ 0,50 (pulso)"),
        IOPoint("M100", "I0.2", "Moeda_100", "Sensor de moeda de R$ 1,00 (pulso)"),
        IOPoint("BOT_A", "I0.3", "Botao_A", "Botão produto A (lata, R$ 2,50)", BUTTON),
        IOPoint("BOT_B", "I0.4", "Botao_B", "Botão produto B (suco, R$ 3,75)", BUTTON),
        IOPoint("DEVOLVER", "I0.5", "Devolver", "Botão DEVOLVER MOEDAS", BUTTON),
        IOPoint("QUEDA", "I0.6", "Sensor_Queda", "Sensor de queda do produto"),
        IOPoint("TUBO_VAZIO", "I0.7", "Tubo_Troco_Vazio", "Tubo de troco vazio"),
    ]
    outputs = [
        IOPoint("ESP_A", "Q0.0", "Espiral_A", "Motor da espiral A"),
        IOPoint("ESP_B", "Q0.1", "Espiral_B", "Motor da espiral B"),
        IOPoint("TROCO", "Q0.2", "Ejetor_Troco", "Ejetor de troco (uma moeda de R$ 0,25 por pulso)"),
        IOPoint("PRONTO", "Q0.3", "Lampada_Pronto", "Lâmpada PRONTO"),
        IOPoint("ESGOTADO", "Q0.4", "Lampada_Esgotado", "Lâmpada PRODUTO ESGOTADO"),
        IOPoint("SEM_TROCO", "Q0.5", "Lampada_Sem_Troco", "Lâmpada SEM TROCO (só valor exato)"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(21)
        self.auto = getattr(self, "auto", False)
        self.stock = {"A": 6, "B": 2}
        self.angle = {"A": 0.0, "B": 0.0}
        self.coins_in: list[tuple[int, str]] = []        # (instante em que o sensor ve, moeda)
        self.pulses: dict[str, int] = {}                  # sensor -> fim do pulso
        self.falling: list[tuple[int, str]] = []
        self.tray: list[str] = []                         # produtos na porta de retirada
        self.change_tray = 0
        self.tube = 10                                    # moedas de 0,25 para troco
        self.cashbox = 0
        self.inserted = self.returned = self.delivered = 0
        self.display: int | None = None
        self._troco_prev = False
        self._troco_off_ms = SOLENOID_MS
        self.run_ms = {"A": 0, "B": 0}
        self.drops_in_run = {"A": 0, "B": 0}
        self.idle_ms = 0
        self.flags: dict[str, str] = {}
        self.sales = 0
        self._script: list[tuple[int, str]] = []
        self.next_customer_ms = 2000

    def advance_words(self, n: list[int]) -> None:
        self.display = n[CREDIT_WORD] if len(n) > CREDIT_WORD else None

    # ---------------------------------------------------------- operador
    def _insert(self, coin: str) -> None:
        last = self.coins_in[-1][0] if self.coins_in else self.time_ms
        self.coins_in.append((max(self.time_ms + ROLL_MS, last + 200), coin))

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key in ("C25", "C50", "C100"):
            self._insert("M" + key[1:])
        elif key == "REABASTECER":
            self.stock = {"A": 6, "B": 6}
            self.tube = max(self.tube, 20)
        elif key == "RETIRAR":
            self.tray.clear()
            self.change_tray = 0
        elif key == "AUTO":
            self.auto = not self.auto

    def press(self, key: str, down: bool) -> None:
        if key in ("C25", "C50", "C100", "REABASTECER", "RETIRAR", "AUTO"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _customer(self) -> None:
        """Cliente automatico: escolhe um produto, paga (as vezes a mais) e aperta o botao."""
        product = self.rng.choice("AAB")
        price = PRICES[product]
        t, paid = self.time_ms, 0
        while paid < price + (25 if self.rng.random() < 0.5 else 0):
            coin = self.rng.choice(["M25", "M50", "M100", "M100"])
            self._script.append((t, coin))
            paid += COINS[coin]
            t += 250
        if self.rng.random() < 0.15:
            self._script.append((t + 800, "DEVOLVER"))
        else:
            self._script.append((t + 800, "BOT_" + product))

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        now = self.time_ms
        for key in ("BOT_A", "BOT_B", "DEVOLVER"):
            if self.operator.get(key) and self.pulses.get(key, 0) and now >= self.pulses[key]:
                self.operator[key] = False
        if self.auto and not self._script and now >= self.next_customer_ms and self.idle_ms > 1500:
            self._customer()
            self.next_customer_ms = now + 9000
        for t, action in list(self._script):
            if now >= t:
                self._script.remove((t, action))
                if action in COINS:
                    self._insert(action)
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
                if coin == "M25":
                    self.tube += 1
                else:
                    self.cashbox += COINS[coin]
        # espirais
        both = out["ESP_A"] and out["ESP_B"]
        if both:
            self.flags.setdefault("both", "As duas espirais giraram ao mesmo tempo")
        for p, key in (("A", "ESP_A"), ("B", "ESP_B")):
            if out[key]:
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
                    self.flags.setdefault("spin", f"Espiral {p} girando há mais de 6 s: o produto acabou? "
                                                  "Use um tempo máximo")
            else:
                self.run_ms[p] = 0
                self.drops_in_run[p] = 0
        for t, p in list(self.falling):
            if now >= t:
                self.falling.remove((t, p))
                self.pulses["QUEDA"] = now + DROP_PULSE_MS
                self.tray.append(p)
                self.delivered += PRICES[p]
                self.sales += 1
        # ejetor de troco: uma moeda por pulso, se o solenoide ficou desligado tempo suficiente
        troco = out["TROCO"]
        if troco and not self._troco_prev and self._troco_off_ms >= SOLENOID_MS and self.tube > 0:
            self.tube -= 1
            self.change_tray += 1
            self.returned += 25
        self._troco_off_ms = 0 if troco else self._troco_off_ms + dt_ms
        self._troco_prev = troco
        # conferencia do caixa (o cliente nao pode perder nem ganhar dinheiro)
        balance = self.inserted - self.returned - self.delivered
        busy = out["ESP_A"] or out["ESP_B"] or troco or self.coins_in or self.falling or self._script
        self.idle_ms = 0 if busy else self.idle_ms + dt_ms
        if balance < 0:
            self.flags.setdefault("loss", f"A máquina entregou mais do que recebeu (prejuízo de {money(-balance)})")
        if self.idle_ms > 2500 and self.display is not None and self.display != balance:
            self.flags.setdefault("display", f"O display mostrou {money(self.display)} mas o crédito real era "
                                             f"{money(balance)}")
        if self.idle_ms > 4000 and self.display == 0 and balance > 0:
            self.flags.setdefault("lost", f"O cliente perdeu {money(balance)}: faltou devolver o troco")

    def sensors(self) -> dict[str, bool]:
        now = self.time_ms
        return {"M25": now < self.pulses.get("M25", 0), "M50": now < self.pulses.get("M50", 0),
                "M100": now < self.pulses.get("M100", 0), "QUEDA": now < self.pulses.get("QUEDA", 0),
                "TUBO_VAZIO": self.tube <= 0}

    def alarms(self) -> list[str]:
        return list(self.flags.values())

    def stats(self) -> list[str]:
        shown = "--" if self.display is None else money(self.display)
        return [f"Display (N0): {shown} | vendas: {self.sales} | estoque A {self.stock['A']}, B {self.stock['B']}",
                f"Recebido {money(self.inserted)} | troco {money(self.returned)} | produtos {money(self.delivered)} | "
                f"tubo de troco: {self.tube} moedas"]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"C25": (486, 60, 136, 26), "C50": (486, 92, 136, 26), "C100": (486, 124, 136, 26),
                "BOT_A": (340, 60, 120, 28), "BOT_B": (340, 96, 120, 28), "DEVOLVER": (340, 132, 120, 28),
                "RETIRAR": (258, 340, 84, 28), "REABASTECER": (486, 334, 136, 28),
                "AUTO": (486, 372, 136, 28)}

    def paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(QRectF(0, 0, 640, 420), QColor("#e2e8f0"))
        body = QRectF(30, 20, 440, 380)
        p.setPen(QPen(QColor("#0f172a"), 2))
        p.setBrush(QColor("#1e40af"))
        p.drawRoundedRect(body, 10, 10)
        glass = QRectF(50, 40, 270, 280)
        p.setBrush(QColor("#e0f2fe"))
        p.drawRect(glass)
        # espirais e produtos
        for row, (prod, color, y) in enumerate((("A", "#dc2626", 110), ("B", "#f97316", 220))):
            p.setPen(QPen(QColor("#475569"), 2))
            for k in range(12):                            # espiral (molas)
                x = glass.left() + 14 + k * 20 + (self.angle[prod] % 1.0) * 20
                if x < glass.right() - 6:
                    p.drawArc(QRectF(x - 8, y - 6, 16, 22), 0, 180 * 16)
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor(color))
            for k in range(self.stock[prod]):
                x = glass.left() + 20 + k * 38 + (self.angle[prod] % 1.0) * 30
                if x < glass.right() - 24:
                    p.drawRoundedRect(QRectF(x, y - 44, 26, 44), 5, 5)
            p.setPen(QPen(QColor("#334155"), 3))
            p.drawLine(QPointF(glass.left(), y + 18), QPointF(glass.right(), y + 18))
            draw.text(p, glass.left() + 6, y + 30, f"{prod}  {money(PRICES[prod])}", 8, True, draw.INK, w=120)
            key = "ESP_" + prod
            draw.tag(p, glass.right() - 76, y + 30, f"Q0.{row} espiral", self.out.get(key, False))
        for t, prod in self.falling:
            frac = 1 - (t - self.time_ms) / FALL_MS
            p.setBrush(QColor("#dc2626" if prod == "A" else "#f97316"))
            p.drawRoundedRect(QRectF(glass.right() - 60, 150 + 140 * frac, 26, 44), 5, 5)
        # porta de retirada e sensor de queda
        tray = QRectF(50, 330, 200, 50)
        p.setBrush(QColor("#0f172a"))
        p.drawRect(tray)
        for k, prod in enumerate(self.tray[:6]):
            p.setBrush(QColor("#dc2626" if prod == "A" else "#f97316"))
            p.drawRoundedRect(QRectF(tray.left() + 8 + k * 30, tray.top() + 22, 40, 22), 4, 4)
        sens = self.sensors()
        draw.tag(p, 56, 318, "I0.6 queda", sens["QUEDA"])
        # display e botoes
        disp = QRectF(340, 20, 120, 34)
        p.setBrush(QColor("#022c22"))
        p.drawRoundedRect(disp, 4, 4)
        text = "--" if self.display is None else money(self.display)
        draw.text(p, disp.center().x(), disp.center().y() - 2, text, 12, True, QColor("#4ade80"),
                  Qt.AlignHCenter | Qt.AlignVCenter, 116, 22)
        draw.text(p, disp.right() - 4, disp.bottom() - 6, "N0", 6, True, QColor("#86efac"), Qt.AlignRight | Qt.AlignVCenter, 30)
        draw.push_button(p, QRectF(340, 60, 120, 28), "A  I0.3", self.is_pressed("BOT_A"), QColor("#dc2626"))
        draw.push_button(p, QRectF(340, 96, 120, 28), "B  I0.4", self.is_pressed("BOT_B"), QColor("#f97316"))
        draw.push_button(p, QRectF(340, 132, 120, 28), "DEVOLVER I0.5", self.is_pressed("DEVOLVER"), QColor("#64748b"))
        draw.lamp(p, QPointF(354, 186), 8, self.out.get("PRONTO", False), draw.GREEN)
        draw.text(p, 368, 186, "PRONTO Q0.3", 7.5, True, draw.WHITE, w=100)
        draw.lamp(p, QPointF(354, 210), 8, self.out.get("ESGOTADO", False), draw.AMBER)
        draw.text(p, 368, 210, "ESGOTADO Q0.4", 7.5, True, draw.WHITE, w=100)
        draw.lamp(p, QPointF(354, 234), 8, self.out.get("SEM_TROCO", False), draw.RED)
        draw.text(p, 368, 234, "SEM TROCO Q0.5", 7.5, True, draw.WHITE, w=100)
        # moedeiro e troco
        p.setBrush(QColor("#0f172a"))
        p.drawRect(QRectF(436, 250, 24, 8))
        for k, (key, label) in enumerate((("M25", "0,25"), ("M50", "0,50"), ("M100", "1,00"))):
            draw.tag(p, 340, 260 + k * 20, f"I0.{k} {label}", sens[key])
        change = QRectF(350, 330, 90, 40)
        p.setBrush(QColor("#0f172a"))
        p.drawRect(change)
        p.setBrush(QColor("#cbd5e1"))
        p.setPen(QPen(QColor("#475569"), 1))
        for k in range(min(self.change_tray, 8)):
            p.drawEllipse(QPointF(change.left() + 12 + (k % 4) * 20, change.top() + 14 + (k // 4) * 14), 7, 7)
        draw.tag(p, 350, 384, "Q0.2 troco", self.out.get("TROCO", False))
        # comandos do cliente e do repositor
        draw.push_button(p, QRectF(486, 60, 136, 26), "Moeda R$ 0,25", False, QColor("#cbd5e1"))
        draw.push_button(p, QRectF(486, 92, 136, 26), "Moeda R$ 0,50", False, QColor("#facc15"))
        draw.push_button(p, QRectF(486, 124, 136, 26), "Moeda R$ 1,00", False, QColor("#eab308"))
        draw.text(p, 486, 170, f"Tubo de troco: {self.tube}", 8, True, draw.INK, w=140)
        draw.text(p, 486, 190, f"Cofre: {money(self.cashbox)}", 8, True, draw.INK, w=140)
        draw.push_button(p, QRectF(258, 340, 84, 28), "Retirar", False, QColor("#16a34a"))
        draw.tag(p, 486, 214, "I0.7 tubo vazio", sens["TUBO_VAZIO"])
        draw.push_button(p, QRectF(486, 334, 136, 28), "Reabastecer", False, QColor("#2563eb"))
        draw.switch(p, QRectF(486, 372, 136, 28), "Automático", self.auto)
