"""Ponte rolante com encoder e guincho com eletroima: referenciamento, posicionamento e tarefas de transporte."""
from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen

from .. import draw
from ..base import BUTTON, SWITCH, Environment, IOPoint
from ..physics import approach
from ..registry import register

STATIONS = [400.0, 1200.0, 2000.0, 2800.0, 3600.0]   # mm
PITCH = 20.0                  # encoder: um ciclo a cada 20 mm (10 mm em 1, 10 mm em 0)
FAST, SLOW = 400.0, 80.0      # mm/s
ACCEL, DECEL = 400.0, 800.0   # mm/s^2 acelerando e reduzindo com o motor
BRAKE, COAST = 1500.0, 150.0  # mm/s^2 com o freio e solta (sem motor nem freio)
END_LEFT, END_RIGHT = -100.0, 3900.0   # batentes
TOLERANCE = 20.0              # parada aceita a +-20 mm da estacao
PLACE_TOL = 30.0              # carga pousada a mais de 30 mm da estacao: fora do lugar
STATION_WIN = 60.0            # o gancho "ve" a pilha da estacao a +-60 mm
START_X = 2130.0
HOIST_S = 4.0                 # o gancho percorre a altura toda em 4 s
PLATE = 0.15                  # altura de uma chapa (fracao da altura do gancho)
MAX_STACK = 3
GRAB_MS = 300                 # o eletroima prende a chapa em 0,3 s
SWAY_DAMPING = 0.6            # 1/s: amortecimento do balanco (cabo e carga)
SWAY_LIMIT = 0.022           # rad: balanco maximo para baixar uma carga
TASK_WORDS = (10, 11)         # N10 estacao de origem, N11 estacao de destino (1 a 5)
PX0, PX = 50.0, 0.155         # desenho: 0 mm em x = 50, 0,155 px/mm
RAIL_Y, HOOK_TOP, FLOOR_Y = 64.0, 112.0, 372.0


@register
class OverheadCraneEnvironment(Environment):
    id = "ponte_rolante"
    name = "Ponte rolante com guincho"
    description = ("A ponte liga sem saber onde está: referencie andando para a esquerda até a chave de origem (0 mm). "
                   "O encoder alterna 1 e 0 a cada 10 mm, sem sentido: conte as bordas pelo sentido do último "
                   "movimento. Estações 1 a 5 em 400, 1200, 2000, 2800 e 3600 mm. Escolha a origem (N10) e o destino "
                   "(N11) e aperte INICIAR: a ponte vai à origem, desce o gancho até apoiar na chapa (I0.3), liga o "
                   "eletroímã (I0.4 confirma), sobe até o topo (I0.2), leva à estação de destino, espera o balanço "
                   "parar, desce, solta e sobe. Não ande com o gancho baixo, não baixe a carga balançando e não solte "
                   "a chapa no alto. I0.6 indica chapa sob o gancho.")
    example = "ambientes/ponte_rolante.ladproj"
    size = (720, 460)
    inputs = [
        IOPoint("ENCODER", "I0.0", "Encoder", "Encoder incremental (1 ciclo / 20 mm)"),
        IOPoint("HOME", "I0.1", "Origem", "Chave de origem (posição 0 mm)"),
        IOPoint("TOPO", "I0.2", "Gancho_Topo", "Gancho em cima (fim de curso do guincho)"),
        IOPoint("EMBAIXO", "I0.3", "Gancho_Apoiado", "Gancho apoiado (cabo frouxo: tocou a chapa ou o piso)"),
        IOPoint("PRESA", "I0.4", "Carga_Presa", "Eletroímã segurando uma chapa"),
        IOPoint("INICIAR", "I0.5", "Iniciar", "Botão INICIAR transporte", BUTTON),
        IOPoint("SOB", "I0.6", "Carga_Sob_Gancho", "Sensor: chapa embaixo do gancho"),
        IOPoint("EMERG", "I0.7", "Emergencia", "Emergência com trava (NF: lê 1 quando liberada)", SWITCH,
                normally_closed=True),
    ]
    outputs = [
        IOPoint("DIR", "Q0.0", "Motor_Direita", "Translação: direita"),
        IOPoint("ESQ", "Q0.1", "Motor_Esquerda", "Translação: esquerda"),
        IOPoint("LENTA", "Q0.2", "Velocidade_Lenta", "Velocidade baixa (aproximação)"),
        IOPoint("FREIO", "Q0.3", "Libera_Freio", "Solta o freio (sem energia o freio atua)"),
        IOPoint("PRONTA", "Q0.4", "Lampada_Pronta", "Lâmpada PRONTA (pisca com erro)"),
        IOPoint("SOBE", "Q0.5", "Guincho_Sobe", "Guincho: sobe"),
        IOPoint("DESCE", "Q0.6", "Guincho_Desce", "Guincho: desce"),
        IOPoint("IMA", "Q0.7", "Eletroima", "Eletroímã do gancho"),
    ]

    def reset(self) -> None:
        self.rng = random.Random(9)
        self.auto = getattr(self, "auto", False)
        self.origin = getattr(self, "origin", 1)
        self.dest = getattr(self, "dest", 3)
        self.x = START_X
        self.v = 0.0
        self.h = 0.0                       # gancho: 0 = em cima, 1 = no piso
        self.stacks = {1: 1, 2: 0, 3: 0, 4: 1, 5: 0}
        self.carrying = False
        self.grab_ms = 0
        self.sway = 0.0
        self.sway_v = 0.0
        self.crash_speed = 0.0
        self.both_ms = 0
        self.hoist_both_ms = 0
        self.drag_ms = 0
        self.dragged = False
        self.emergency_moves = 0
        self.flags: dict[str, str] = {}
        self.delivered = 0
        self.wrong = 0
        self.next_auto_ms = 4000
        self._driver_press: dict[str, int] = {}
        self.drop_anim: list[list[float]] = []

    # ---------------------------------------------------------- operador
    def input_words(self) -> dict[int, int]:
        return {TASK_WORDS[0]: self.origin, TASK_WORDS[1]: self.dest}

    def on_control(self, key: str, down: bool) -> None:
        if not down:
            return
        if key == "AUTO":
            self.auto = not self.auto
        elif key == "ORIG":
            self.origin = self.origin % 5 + 1
        elif key == "DEST":
            self.dest = self.dest % 5 + 1

    def press(self, key: str, down: bool) -> None:
        if key in ("AUTO", "ORIG", "DEST"):
            self.on_control(key, down)
        else:
            super().press(key, down)

    def _station_at(self, tol: float = STATION_WIN) -> int | None:
        for k, s in enumerate(STATIONS):
            if abs(self.x - s) <= tol:
                return k + 1
        return None

    def _contact(self) -> float:
        """Altura em que o gancho (ou a chapa presa) apoia."""
        st = self._station_at()
        stack = self.stacks[st] if st else 0
        return 1.0 - PLATE * stack - (PLATE if self.carrying else 0.0)

    def _flag(self, key: str, text: str) -> None:
        self.flags.setdefault(key, text)

    # ------------------------------------------------------------- fisica
    def step(self, dt_ms: int, out: dict[str, bool]) -> None:
        dt = dt_ms / 1000.0
        now = self.time_ms
        for key, until in list(self._driver_press.items()):
            if now >= until:
                self.operator[key] = False
                del self._driver_press[key]
        if self.auto and now >= self.next_auto_ms and abs(self.v) < 1 and out["PRONTA"] and self.h < 0.03 \
                and not self.carrying:
            full = [k for k, n in self.stacks.items() if n > 0]
            if full:
                self.origin = self.rng.choice(full)
                self.dest = self.rng.choice([k for k, n in self.stacks.items() if k != self.origin and n < MAX_STACK])
                self.operator["INICIAR"] = True
                self.clicked.add("INICIAR")
                self._driver_press["INICIAR"] = now + 300
                self.next_auto_ms = now + 5000
        # translacao
        right, left = out["DIR"], out["ESQ"]
        self.both_ms = self.both_ms + dt_ms if (right and left) else 0
        cmd = 0 if right == left else (1 if right else -1)
        brake_free = out["FREIO"]
        old_v = self.v
        if cmd and self.is_pressed("EMERG") and abs(self.v) > 5:
            self.emergency_moves += 1
        if cmd and not brake_free:                       # motor contra o freio
            self.drag_ms += dt_ms
            self.v = approach(self.v, 0.0, BRAKE, BRAKE, dt)
        elif cmd:
            self.drag_ms = 0
            target = cmd * (SLOW if out["LENTA"] else FAST)
            rate_up = ACCEL if abs(target) > abs(self.v) and target * self.v >= 0 else DECEL
            self.v = approach(self.v, target, rate_up, rate_up, dt)
        else:
            self.drag_ms = 0
            decel = COAST if brake_free else BRAKE
            self.v = approach(self.v, 0.0, decel, decel, dt)
        if self.drag_ms > 300:
            self.dragged = True
        self.x += self.v * dt
        for end in (END_LEFT, END_RIGHT):
            if (self.x <= END_LEFT and end == END_LEFT) or (self.x >= END_RIGHT and end == END_RIGHT):
                if abs(self.v) > 30:
                    self.crash_speed = max(self.crash_speed, abs(self.v))
                self.x, self.v = end, 0.0
        if abs(self.v) > 20 and self.h > 0.1:
            self._flag("low", "A ponte andou com o gancho baixo: suba até o topo (I0.2) antes de andar")
        # balanco da carga (pendulo amortecido; o gancho vazio quase nao balanca)
        accel = (self.v - old_v) / dt if dt else 0.0
        length = 1.5 + 2.5 * self.h
        self.sway_v += (-9.81 / length * self.sway - accel / 1000 / length - SWAY_DAMPING * self.sway_v) * dt
        self.sway += self.sway_v * dt
        # guincho
        up, down = out["SOBE"], out["DESCE"]
        self.hoist_both_ms = self.hoist_both_ms + dt_ms if (up and down) else 0
        if up and down:
            self._flag("hoist", "Guincho comandado para subir e descer ao mesmo tempo")
        contact = self._contact()
        if down and not up:
            if self.carrying and abs(self.sway) > SWAY_LIMIT and self.h > 0.05:
                self._flag("sway", "A carga desceu balançando: espere o balanço parar antes de baixar")
            self.h = min(contact, self.h + dt / HOIST_S)
        elif up and not down:
            self.h = max(0.0, self.h - dt / HOIST_S)
        self.h = min(self.h, contact)                    # apoiado: o cabo afrouxa
        resting = self.h >= contact - 0.005
        st = self._station_at()
        # eletroima
        if out["IMA"] and not self.carrying and resting and st and self.stacks[st] > 0:
            self.grab_ms += dt_ms
            if self.grab_ms >= GRAB_MS:
                if abs(self.x - STATIONS[st - 1]) > PLACE_TOL:
                    self._flag("offset", "O gancho desceu fora do centro da estação (mais de 30 mm)")
                self.stacks[st] -= 1
                self.carrying = True
                self.grab_ms = 0
        else:
            self.grab_ms = 0
        if self.carrying and not out["IMA"]:
            if not resting:
                self._flag("drop", "A chapa caiu do alto: só desligue o eletroímã com ela apoiada (I0.3)")
                self.drop_anim.append([self.x, self.h])
            target = self._station_at()
            if target is None or abs(self.x - STATIONS[target - 1]) > PLACE_TOL:
                self._flag("offset", "Chapa pousada fora do centro da estação (mais de 30 mm)")
            if target is not None:
                self.stacks[target] = min(MAX_STACK, self.stacks[target] + 1)
                if target == self.dest:
                    self.delivered += 1
                else:
                    self.wrong += 1
                    self._flag("wrong", "Chapa entregue numa estação diferente do destino (N11)")
            self.carrying = False
        self.drop_anim = [[x, h + dt * 2] for x, h in self.drop_anim if h < 1.0]

    def sensors(self) -> dict[str, bool]:
        st = self._station_at()
        return {"ENCODER": (self.x % PITCH) < PITCH / 2, "HOME": self.x <= 0.0, "TOPO": self.h <= 0.01,
                "EMBAIXO": self.h >= self._contact() - 0.005, "PRESA": self.carrying,
                "SOB": bool(st and self.stacks[st] > 0)}

    def alarms(self) -> list[str]:
        out = []
        if self.crash_speed:
            out.append("A ponte bateu no batente")
        if self.both_ms > 0:
            out.append("Motor comandado para a direita e a esquerda ao mesmo tempo")
        if self.dragged:
            out.append("Motor ligado com o freio aplicado: solte o freio (Q0.3) junto com o motor")
        if self.emergency_moves:
            out.append("A ponte andou com a emergência acionada")
        return out + list(self.flags.values())

    def stats(self) -> list[str]:
        st = " ".join(f"{k}:{n}" for k, n in self.stacks.items())
        return [f"Posição real: {self.x:.0f} mm | velocidade {self.v:+.0f} mm/s | gancho {self.h * 100:.0f}% | "
                f"balanço {math.degrees(self.sway):+.1f}°",
                f"Tarefa: {self.origin} → {self.dest} | entregas: {self.delivered} | chapas por estação {st}"
                + (" | Automático" if self.auto else "")]

    # ------------------------------------------------------------ desenho
    def controls(self):
        return {"ORIG": (14, 410, 112, 40), "DEST": (132, 410, 112, 40), "INICIAR": (250, 416, 130, 28),
                "EMERG": (390, 416, 150, 28), "AUTO": (550, 416, 156, 28)}

    def _px(self, mm: float) -> float:
        return PX0 + mm * PX

    def _plate(self, p: QPainter, cx: float, bottom: float, h: float) -> None:
        r = QRectF(cx - 34, bottom - h, 68, h - 2)
        g = QLinearGradient(r.topLeft(), r.bottomLeft())
        g.setColorAt(0, QColor("#cbd5e1"))
        g.setColorAt(1, QColor("#475569"))
        p.setPen(QPen(QColor("#1e293b"), 1))
        p.setBrush(g)
        p.drawRect(r)

    def paint(self, p: QPainter) -> None:
        draw.background(p, 720, 460, "#e2e8f0", "#cbd5e1")
        draw.ground(p, FLOOR_Y, 720, 460, hazard_edge=False)
        out = self.out
        sens = self.sensors()
        span = FLOOR_Y - HOOK_TOP
        plate_px = PLATE * span
        # pilares e trilho
        for x in (24, 696):
            draw.metal(p, QRectF(x - 8, RAIL_Y, 16, FLOOR_Y - RAIL_Y), "#64748b", 2, vertical=True)
        draw.metal(p, QRectF(16, RAIL_Y - 8, 688, 10), "#334155", 2)
        for end in (END_LEFT, END_RIGHT):
            draw.hazard(p, QRectF(self._px(end) - 5, RAIL_Y - 16, 10, 16))
        # estacoes e pilhas
        for k, s in enumerate(STATIONS):
            x = self._px(s)
            p.setPen(QPen(QColor("#475569"), 2))
            p.drawLine(QPointF(x - 40, FLOOR_Y + 2), QPointF(x + 40, FLOOR_Y + 2))
            draw.plate(p, QRectF(x - 12, FLOOR_Y + 8, 24, 16), str(k + 1),
                       "#1d4ed8" if k + 1 == self.dest else ("#16a34a" if k + 1 == self.origin else "#334155"))
            for j in range(self.stacks[k + 1]):
                self._plate(p, x, FLOOR_Y - j * plate_px, plate_px)
        # ponte (viga) e carro
        bx = self._px(self.x)
        girder = QRectF(bx - 44, RAIL_Y - 4, 88, 22)
        draw.shadow(p, girder, 3, 3)
        draw.metal(p, girder, "#eab308", 3)
        draw.hazard(p, QRectF(bx - 44, RAIL_Y + 14, 88, 5))
        for wx in (bx - 34, bx + 34):
            p.setPen(QPen(QColor("#0f172a"), 1))
            p.setBrush(QColor("#1e293b"))
            p.drawEllipse(QPointF(wx, RAIL_Y - 6), 5, 5)
        drum = QRectF(bx - 16, RAIL_Y + 18, 32, 16)
        draw.metal(p, drum, "#475569", 3)
        # cabo e gancho com balanco
        hook_y = HOOK_TOP + span * self.h
        length = hook_y - (RAIL_Y + 34)
        hx = bx + math.sin(self.sway) * length * 2.5
        p.setPen(QPen(QColor("#111827"), 2))
        p.drawLine(QPointF(bx - 4, RAIL_Y + 34), QPointF(hx - 4, hook_y - 14))
        p.drawLine(QPointF(bx + 4, RAIL_Y + 34), QPointF(hx + 4, hook_y - 14))
        magnet = QRectF(hx - 30, hook_y - 14, 60, 14)
        draw.metal(p, magnet, "#dc2626" if out.get("IMA") else "#64748b", 3)
        if out.get("IMA"):
            p.setPen(QPen(QColor(239, 68, 68, 120), 1.5, Qt.DashLine))
            p.drawLine(QPointF(hx - 24, hook_y + 2), QPointF(hx + 24, hook_y + 2))
        if self.carrying:
            self._plate(p, hx, hook_y + plate_px, plate_px)
        for x, h in self.drop_anim:
            self._plate(p, self._px(x), HOOK_TOP + span * min(1.0, h) + plate_px, plate_px)
        # setas de movimento
        if abs(self.v) > 5:
            draw.harrow(p, QPointF(bx + (60 if self.v > 0 else -60), RAIL_Y + 6), 12, self.v > 0, True)
        # sensores e saidas (painel superior)
        draw.card(p, QRectF(8, 8, 704, 44))
        tags = [("I0.0 encoder", sens["ENCODER"]), ("I0.1 origem", sens["HOME"]), ("I0.2 topo", sens["TOPO"]),
                ("I0.3 apoiado", sens["EMBAIXO"]), ("I0.4 presa", sens["PRESA"]), ("I0.6 chapa", sens["SOB"])]
        for k, (label, on) in enumerate(tags):
            draw.tag(p, 16 + k * 84, 20, label, on)
        outs = [("Q0.0 dir", "DIR"), ("Q0.1 esq", "ESQ"), ("Q0.2 lenta", "LENTA"), ("Q0.3 freio", "FREIO"),
                ("Q0.5 sobe", "SOBE"), ("Q0.6 desce", "DESCE"), ("Q0.7 ímã", "IMA")]
        for k, (label, key) in enumerate(outs):
            draw.tag(p, 16 + k * 84, 40, label, out.get(key, False))
        draw.lamp(p, QPointF(620, 30), 8, out.get("PRONTA", False), draw.GREEN)
        draw.text(p, 632, 30, "PRONTA Q0.4", 7, True, w=80)
        # posicao
        draw.lcd(p, QRectF(560, 70, 140, 34), f"{self.x:6.0f}", "#60a5fa", "posição real (mm)")
        # tarefa
        for key, x, label, value, word in (("ORIG", 14, "ORIGEM", self.origin, "N10"),
                                           ("DEST", 132, "DESTINO", self.dest, "N11")):
            r = QRectF(x, 410, 112, 40)
            draw.shadow(p, r, 6, 2)
            p.setPen(QPen(QColor("#2563eb"), 1.4))
            p.setBrush(QColor("#eff6ff"))
            p.drawRoundedRect(r, 6, 6)
            draw.text(p, x + 8, 422, f"{label} ({word})", 7, True, QColor("#1d4ed8"), w=100)
            draw.text(p, x + 8, 439, f"estação {value}  ▸", 9, True, draw.INK, w=100)
        draw.push_button(p, QRectF(250, 416, 130, 28), "INICIAR I0.5", self.is_pressed("INICIAR"), draw.GREEN)
        draw.switch(p, QRectF(390, 416, 150, 28), "EMERGÊNCIA I0.7", self.is_pressed("EMERG"))
        draw.switch(p, QRectF(550, 416, 156, 28), "Tarefas automáticas", self.auto)
