"""Ajuda > Como funciona a comunicação: o caminho dos dados dentro da IDE.

Mostra, numa janela so, por onde passa o programa LADDER: editor -> compilador
-> simulador (ambiente animado / Factory IO) ou -> cliente LDP -> transporte ->
firmware -> reles. O mapa e clicavel e acende, ao vivo, os caminhos em uso; as
outras abas detalham o quadro LDP, a transferencia transacional, o Modbus TCP
do Factory IO e o trafego real de quadros. As tabelas de comandos e erros vem
de shared/specifications/protocol.json, a mesma fonte do firmware.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QPlainTextEdit, QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextBrowser, QVBoxLayout, QWidget)

from ..comm.frames import encode
from ..comm.protocol import ERROR_TEXT, FRAME_TIMEOUT_MS, MAX_CHUNK, MAX_PAYLOAD, SPEC, Cmd
from .fonts import mono_font, ui_font
from .theme import color

PERIODIC = {"STATUS", "READ_VARS", "READ_IO"}

# ------------------------------------------------------------------ conteudo
CMD_TEXT = {
    "INFO": ("conectar", "Identifica o firmware: versão do protocolo e do LDRB, nº de entradas e saídas, "
                         "tamanho máximo do programa e período de varredura."),
    "STATUS": ("a cada 0,2–1 s", "Estado (STOP/RUN/FAULT), programa ativo (build e CRC), varreduras e "
                                 "tempo de execução."),
    "SET_MODE": ("RUN / STOP", "Coloca o CLP em RUN ou STOP. RUN exige programa válido e nenhuma falha."),
    "CLEAR_FAULT": ("após falha", "Limpa a falha (watchdog, programa corrompido) e volta a STOP."),
    "LOAD_BEGIN": ("transferir", "Abre a sessão de carga: tamanho e CRC-32 do programa. Só em STOP."),
    "LOAD_CHUNK": ("transferir", f"Um bloco do programa (até {MAX_CHUNK} bytes) com o deslocamento."),
    "LOAD_END": ("transferir", "Fecha a carga: o firmware confere tamanho, CRC-32 e valida a imagem LDRB."),
    "LOAD_COMMIT": ("transferir", "Grava na flash de forma atômica e ativa o novo programa."),
    "LOAD_ABORT": ("erro na carga", "Descarta a carga; o programa antigo continua ativo."),
    "READ_IO": ("monitor", "Entradas, saídas lógicas e saídas comandadas nos relés."),
    "READ_VARS": ("monitor online", "Instantâneo completo: bits M, temporizadores, contadores, registradores e "
                                    "a energia de cada instrução para animar o diagrama."),
    "WRITE_MARKER": ("monitor", "Escreve um bit M (único dado que a IDE pode alterar com o CLP rodando)."),
    "TEST_BEGIN": ("equivalência", "Partida a frio da VM em modo teste, com as saídas físicas no estado seguro."),
    "TEST_SCAN": ("equivalência", "Executa uma varredura com entradas e dt dados; compara com o simulador."),
    "SIM_SET_INPUTS": ("placa virtual", "Liga/desliga as entradas da placa simulada (não existe na placa real)."),
}

FRAME_FIELDS = [   # (rotulo, bytes, cor, explicacao)
    ("A5 5A", 2, "#64748b", "Início de quadro (SOF). O analisador descarta tudo até achar estes dois bytes — "
                            "assim as mensagens de boot do ESP32 não atrapalham."),
    ("ver", 1, "#0891b2", f"Versão do protocolo (= {SPEC['version']}). Quadro de outra versão é descartado."),
    ("type", 1, "#2563eb", "Comando (INFO, STATUS, LOAD_CHUNK...). A resposta usa type | 0x80."),
    ("seq", 1, "#7c3aed", "Número de sequência. A resposta repete o seq; um pedido repetido com o mesmo seq "
                          "é respondido de novo sem reexecutar (idempotência)."),
    ("flags", 1, "#db2777", "Bit 0 = erro: o payload traz o código do erro."),
    ("len", 2, "#ea580c", f"Tamanho do payload, little-endian (0 a {MAX_PAYLOAD} bytes)."),
    ("payload", 0, "#16a34a", "Dados do comando (inteiros little-endian)."),
    ("crc16", 2, "#dc2626", "CRC-16/MODBUS de ver…payload. CRC errado: quadro descartado sem resposta; "
                            "a IDE percebe pelo timeout e reenvia (até 3 vezes)."),
]

TRANSFER_STEPS = [   # (pedido, resposta, explicacao)
    ("INFO", "versão LDRB, nº de E/S", "A IDE confere se o programa cabe no hardware antes de enviar."),
    ("STATUS", "RUN / STOP", "Se estiver em RUN, a IDE pede confirmação e manda SET_MODE STOP."),
    ("LOAD_BEGIN", "tamanho máx. do bloco", "Estado PROGRAM_LOADING; o programa novo vai para a RAM."),
    ("LOAD_CHUNK ×N", "bytes recebidos", "Blocos em ordem; o reenvio do último bloco é aceito."),
    ("LOAD_END", "ok (validado)", "Tamanho, CRC-32, validação da imagem LDRB e E/S compatíveis."),
    ("LOAD_COMMIT", "build_id, CRC", "Grava /prog.new e renomeia sobre /prog.bin: troca atômica."),
    ("STATUS", "build_id, CRC", "A IDE confirma que o programa ativo é o que foi enviado."),
]


@dataclass
class Node:
    key: str
    title: str
    subtitle: str
    rect: QRectF
    html: str


@dataclass
class Edge:
    key: str
    a: str
    b: str
    label: str
    channel: str          # sim / device / modbus
    both: bool
    html: str


def _section(title: str, what: str, how: str, code: str) -> str:
    return (f"<h3>{title}</h3><p><b>O que faz.</b> {what}</p><p><b>Como se comunica.</b> {how}</p>"
            f"<p><b>Onde está no código.</b> <code>{code}</code></p>")


NODES = [
    Node("editor", "Editor LADDER", "diagrama + símbolos", QRectF(10, 150, 155, 64), _section(
        "Editor LADDER",
        "Monta as redes (contatos, bobinas, temporizadores, contadores, blocos) e a tabela de símbolos. "
        "O editor só deixa construir redes válidas.",
        "Não fala com hardware: entrega o projeto (.ladproj) ao compilador. O C++ e os blocos IL são "
        "atualizados a cada edição.",
        "ladderide/model, ladderide/ui/ladder_view.py")),
    Node("compiler", "Compilador", "LDRB + mapa", QRectF(240, 270, 155, 64), _section(
        "Compilador",
        "Valida o programa (símbolos, endereços, saída acionada uma vez só) e gera a imagem binária LDRB: "
        "as instruções que a máquina virtual do CLP executa. Gera também o mapa instrução ↔ elemento, "
        "usado para animar o diagrama.",
        "A mesma imagem LDRB vai para o simulador (no PC) e para o firmware (pela transferência LDP). "
        "Por isso o que roda na simulação é exatamente o que roda na placa.",
        "ladderide/compiler, ladderide/core (ISA, LDRB, LadderVM)")),
    Node("sim", "Simulador", "VM no PC, tempo virtual", QRectF(480, 100, 155, 64), _section(
        "Simulador",
        "Executa a imagem LDRB na LadderVM em Python com tempo virtual: contínuo (com velocidade), "
        "uma varredura por vez ou instrução por instrução.",
        "A cada varredura lê as entradas do processo ligado (protocolo <i>Plant</i>), executa o programa e "
        "devolve as saídas. O processo pode ser o ambiente animado ou o Factory IO — um de cada vez.",
        "ladderide/sim/simulator.py")),
    Node("env", "Ambiente animado", "processo desenhado", QRectF(790, 30, 155, 64), _section(
        "Ambiente animado",
        "Processo desenhado na IDE (semáforo, silo, portão, elevador...). Tem física simples e sensores.",
        "Chamada direta, sem rede: a cada varredura o simulador chama <code>advance(dt, saídas)</code> e lê "
        "<code>input_bits</code>. As entradas que o ambiente comanda ficam travadas no painel de E/S.",
        "ladderide/envs")),
    Node("fio", "Factory IO", "cena 3D (servidor)", QRectF(790, 180, 155, 64), _section(
        "Factory IO",
        "Simulador 3D de fábrica. O driver <i>Modbus TCP/IP Server</i> transforma a cena num escravo Modbus.",
        "A IDE é o cliente Modbus TCP: uma thread lê sensores (FC02/FC01) e registradores (FC04) e escreve "
        "atuadores (FC15) e registradores (FC16) a cada ciclo. A varredura nunca espera pela rede: usa o último "
        "valor lido. Ao desconectar, todas as saídas da cena vão a 0.",
        "ladderide/comm/modbus_tcp.py, ladderide/sim/factoryio.py")),
    Node("client", "Cliente LDP", "pedidos, retransmissão", QRectF(290, 420, 155, 64), _section(
        "Cliente LDP",
        "Fala o protocolo LDP com o CLP: conectar, ler estado, transferir o programa, RUN/STOP e monitor online.",
        f"Cada pedido vira um quadro com número de sequência; sem resposta em ~{FRAME_TIMEOUT_MS * 4} ms ele é "
        "reenviado com o mesmo seq (até 3 vezes). Os pedidos rodam numa thread, a interface não trava.",
        "ladderide/comm/client.py, ladderide/ui/device_panel.py")),
    Node("transport", "Transporte", "serial / processo / TCP", QRectF(540, 420, 155, 64), _section(
        "Transporte",
        "Leva os bytes dos quadros até o CLP. Três meios, o mesmo protocolo:",
        "<ul><li><b>Serial USB</b> (115 200 bps 8N1) até o ESP32 — abre com DTR/RTS desligados para não "
        "reiniciar a placa;</li><li><b>Processo virtual</b>: o firmware compilado para o PC, falando por "
        "stdin/stdout (placa simulada);</li><li><b>TCP</b>: pronto na IDE, o firmware ainda não tem Wi-Fi."
        "</li></ul>",
        "ladderide/comm/transport.py, ladderide/comm/virtual.py")),
    Node("firmware", "Firmware do CLP", "runtime + VM em C", QRectF(790, 420, 155, 64), _section(
        "Firmware do CLP",
        "Máquina de estados STOP/RUN/FAULT, carga transacional do programa, varredura periódica com watchdog "
        "e a VM LADDER em C.",
        "Responde aos quadros LDP. O mesmo código C roda no ESP32 e no dispositivo virtual, então a placa "
        "simulada se comporta como a real.",
        "firmware/lib/plc_core, firmware/lib/ladder_vm")),
    Node("io", "Relés e entradas", "74HC595 / 74HC165", QRectF(790, 530, 155, 64), _section(
        "Relés e entradas",
        "Saídas Q0.x acionam relés; entradas I0.x vêm de optoacopladores.",
        "No ESP32 Relay X8 os relés são ligados por registrador de deslocamento 74HC595 e as entradas lidas "
        "pelo 74HC165, a cada varredura. Em STOP ou FAULT as saídas vão ao estado seguro (desligadas).",
        "firmware/src (HAL do ESP32), firmware/src/board_config.h")),
    Node("scada", "Supervisório", "Modbus RTU, só leitura", QRectF(540, 530, 155, 64), _section(
        "Supervisório",
        "Um sistema SCADA pode acompanhar o CLP sem a IDE.",
        "Modbus RTU pela RS-485 (endereço 11, 9 600 bps). Somente leitura: coils = saídas, discrete inputs = "
        "entradas, input registers = estado, varreduras, temporizadores e contadores. O Modbus nunca é usado "
        "para transferir programas.",
        "firmware/lib/plc_core (Modbus RTU)")),
]

EDGES = [
    Edge("e_compile", "editor", "compiler", "projeto", "sim", False,
         "<h3>Editor → Compilador</h3><p>O projeto é compilado ao simular, transferir ou verificar. Erros "
         "aparecem na aba Mensagens e o programa não segue adiante.</p>"),
    Edge("e_load_sim", "compiler", "sim", "imagem LDRB", "sim", False,
         "<h3>Compilador → Simulador</h3><p>O simulador recebe a imagem LDRB e o mapa de depuração. Nenhum "
         "byte sai do PC.</p>"),
    Edge("e_plant", "sim", "env", "Plant (chamada direta)", "sim", True,
         "<h3>Simulador ↔ Ambiente</h3><p>Troca por varredura, sem rede: saídas Q do programa → atuadores do "
         "ambiente; sensores do ambiente → entradas I.</p>"),
    Edge("e_fio", "sim", "fio", "Modbus TCP :502", "modbus", True,
         "<h3>Simulador ↔ Factory IO</h3><p>Modbus TCP, porta 502. Sensores → FC02 (ou FC01) → I0.x; "
         "Q0.x → FC15 → coils; input registers (FC04) → N; N → FC16 → holding registers. Veja a aba "
         "<i>Factory IO</i>.</p>"),
    Edge("e_transfer", "compiler", "client", "LDRB + CRC-32", "device", False,
         "<h3>Compilador → Cliente LDP</h3><p>Transferir envia a mesma imagem LDRB do simulador, em blocos, "
         "com CRC-32 do programa inteiro. Veja a aba <i>Transferência</i>.</p>"),
    Edge("e_ldp", "client", "transport", "quadros LDP", "device", True,
         "<h3>Cliente ↔ Transporte</h3><p>Quadros binários: A5 5A, versão, comando, seq, flags, tamanho, "
         "dados e CRC-16. Veja a aba <i>Protocolo LDP</i>.</p>"),
    Edge("e_wire", "transport", "firmware", "USB / stdin-stdout", "device", True,
         "<h3>Transporte ↔ Firmware</h3><p>Com a placa real, o cabo USB (UART0). Com a placa simulada, o "
         "processo do dispositivo virtual. Para o firmware os dois são iguais.</p>"),
    Edge("e_io", "firmware", "io", "a cada varredura", "device", True,
         "<h3>Firmware ↔ Relés e entradas</h3><p>Lê as entradas, executa o programa e escreve as saídas, "
         "no período configurado (10 ms por padrão).</p>"),
    Edge("e_rtu", "firmware", "scada", "Modbus RTU", "modbus", False,
         "<h3>Firmware → Supervisório</h3><p>RS-485, somente leitura. Só existe na placa real.</p>"),
]

CHANNEL_COLORS = {"sim": "#2563eb", "device": "#7c3aed", "modbus": "#16a34a"}
CHANNEL_NAMES = {"sim": "simulação no PC", "device": "dispositivo (LDP)", "modbus": "Modbus"}


def _anchors(a: QRectF, b: QRectF) -> tuple[QPointF, QPointF, bool]:
    """Pontos de saida/chegada nas bordas dos blocos; True se a ligacao e horizontal."""
    d = b.center() - a.center()
    if abs(d.x()) >= abs(d.y()):
        if d.x() > 0:
            return QPointF(a.right(), a.center().y()), QPointF(b.left(), b.center().y()), True
        return QPointF(a.left(), a.center().y()), QPointF(b.right(), b.center().y()), True
    if d.y() > 0:
        return QPointF(a.center().x(), a.bottom()), QPointF(b.center().x(), b.top()), False
    return QPointF(a.center().x(), a.top()), QPointF(b.center().x(), b.bottom()), False


def _path(a: QPointF, b: QPointF, horizontal: bool) -> QPainterPath:
    path = QPainterPath(a)
    if horizontal:
        mid = (a.x() + b.x()) / 2
        path.cubicTo(QPointF(mid, a.y()), QPointF(mid, b.y()), b)
    else:
        mid = (a.y() + b.y()) / 2
        path.cubicTo(QPointF(a.x(), mid), QPointF(b.x(), mid), b)
    return path


class CommMap(QWidget):
    """Mapa clicavel da comunicacao; caminhos em uso acendem e mostram quadros andando."""
    selected = Signal(str)
    W, H = 950.0, 600.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nodes = {n.key: n for n in NODES}
        self.edges = {e.key: e for e in EDGES}
        self.active: set[str] = set()          # chaves de blocos e ligacoes em uso
        self.status: dict[str, str] = {}       # linha de estado embaixo do bloco
        self.selection = "compiler"
        self.phase = 0.0
        self.setMouseTracking(True)
        self.setMinimumSize(QSize(560, 270))
        self._hover = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def sizeHint(self) -> QSize:
        return QSize(int(self.W), int(self.H))

    def _transform(self) -> tuple[float, float, float]:
        s = min(self.width() / self.W, self.height() / self.H)
        return s, (self.width() - self.W * s) / 2, (self.height() - self.H * s) / 2

    def _tick(self) -> None:
        if any(k in self.edges for k in self.active):
            self.phase = (self.phase + 0.012) % 1.0
            self.update()

    def _edge_geometry(self, e: Edge) -> QPainterPath:
        a, b, horizontal = _anchors(self.nodes[e.a].rect, self.nodes[e.b].rect)
        return _path(a, b, horizontal)

    def item_at(self, pos) -> str:
        s, ox, oy = self._transform()
        p = QPointF((pos.x() - ox) / s, (pos.y() - oy) / s)
        for n in self.nodes.values():
            if n.rect.contains(p):
                return n.key
        for e in self.edges.values():           # perto da curva (amostrada)
            path = self._edge_geometry(e)
            if any((path.pointAtPercent(t / 20) - p).manhattanLength() < 10 for t in range(21)):
                return e.key
        return ""

    def mousePressEvent(self, event) -> None:
        key = self.item_at(event.position())
        if key:
            self.select(key)

    def mouseMoveEvent(self, event) -> None:
        key = self.item_at(event.position())
        self.setCursor(Qt.PointingHandCursor if key else Qt.ArrowCursor)
        if key != self._hover:
            self._hover = key
            self.update()

    def select(self, key: str) -> None:
        self.selection = key
        self.selected.emit(key)
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s, ox, oy = self._transform()
        p.translate(ox, oy)
        p.scale(s, s)
        text, muted, surface = color("TEXT"), color("MUTED"), color("SURFACE")
        for e in self.edges.values():
            path = self._edge_geometry(e)
            on = e.key in self.active
            c = QColor(CHANNEL_COLORS[e.channel])
            if not on:
                c.setAlpha(110)
            width = 3.2 if e.key == self.selection or e.key == self._hover else 2.4 if on else 1.6
            p.setPen(QPen(c, width, Qt.SolidLine if on else Qt.DashLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            self._arrow_head(p, path, 1.0, c)
            if e.both:
                self._arrow_head(p, path, 0.0, c)
            if on:                                   # quadros andando no sentido do fluxo
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(CHANNEL_COLORS[e.channel]))
                for j in range(3):
                    t = (self.phase + j / 3) % 1.0
                    p.drawEllipse(path.pointAtPercent(t), 3.6, 3.6)
                    if e.both:
                        p.setBrush(QColor(CHANNEL_COLORS[e.channel]).lighter(140))
                        p.drawEllipse(path.pointAtPercent(1 - t), 2.6, 2.6)
                        p.setBrush(QColor(CHANNEL_COLORS[e.channel]))
            mid = path.pointAtPercent(0.5)
            p.setFont(ui_font(7, True))
            fm = p.fontMetrics()
            w = fm.horizontalAdvance(e.label) + 10
            box = QRectF(mid.x() - w / 2, mid.y() - 8, w, 16)
            p.setPen(QPen(c, 1))
            p.setBrush(surface)
            p.drawRoundedRect(box, 8, 8)
            p.setPen(text if on else muted)
            p.drawText(box, Qt.AlignCenter, e.label)
        for n in self.nodes.values():
            on = n.key in self.active
            sel = n.key == self.selection
            p.setPen(QPen(color("ACCENT") if sel else color("LED_ON") if on else color("BORDER"),
                          2.6 if sel else 1.8 if on else 1.2))
            p.setBrush(color("ACCENT_SOFT") if sel else surface)
            p.drawRoundedRect(n.rect, 9, 9)
            if n.key == self._hover and not sel:
                p.setPen(QPen(color("ACCENT_BORDER"), 1.2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(n.rect.adjusted(-3, -3, 3, 3), 11, 11)
            led = QPointF(n.rect.right() - 12, n.rect.top() + 12)
            p.setPen(Qt.NoPen)
            p.setBrush(color("LED_ON") if on else color("LED_OFF_BORDER"))
            p.drawEllipse(led, 4, 4)
            r = n.rect.adjusted(10, 6, -20, 0)
            p.setPen(text)
            p.setFont(ui_font(9, True))
            p.drawText(QRectF(r.left(), r.top(), r.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, n.title)
            p.setPen(muted)
            p.setFont(ui_font(7.5))
            p.drawText(QRectF(r.left(), r.top() + 18, r.width() + 10, 15), Qt.AlignLeft | Qt.AlignVCenter,
                       n.subtitle)
            status = self.status.get(n.key, "")
            if status:
                p.setPen(color("SUCCESS") if on else muted)
                p.setFont(ui_font(7.5, True))
                p.drawText(QRectF(r.left(), r.top() + 33, r.width() + 10, 15), Qt.AlignLeft | Qt.AlignVCenter,
                           status)
        y = 14.0                                     # legenda dos canais
        p.setFont(ui_font(8))
        for ch, name in CHANNEL_NAMES.items():
            p.setPen(QPen(QColor(CHANNEL_COLORS[ch]), 2.4))
            p.drawLine(QPointF(10, y), QPointF(32, y))
            p.setPen(muted)
            p.drawText(QRectF(38, y - 8, 200, 16), Qt.AlignLeft | Qt.AlignVCenter, name)
            y += 18
        p.drawText(QRectF(10, y - 8, 300, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   "linha cheia com pontos andando = em uso agora")
        p.setFont(ui_font(8.5, True))                # faixas: no PC x no dispositivo
        p.setPen(QPen(color("BORDER"), 1, Qt.DashLine))
        p.drawLine(QPointF(250, 380), QPointF(self.W, 380))
        p.setPen(muted)
        p.drawText(QRectF(self.W - 260, 360, 255, 16), Qt.AlignRight | Qt.AlignVCenter, "no PC (simulação)  ▲")
        p.drawText(QRectF(self.W - 260, 384, 255, 16), Qt.AlignRight | Qt.AlignVCenter,
                   "▼  no CLP (ESP32 ou placa virtual)")
        p.end()

    @staticmethod
    def _arrow_head(p, path: QPainterPath, t: float, c: QColor) -> None:
        tip = path.pointAtPercent(t)
        back = path.pointAtPercent(0.97 if t >= 1 else 0.03)
        d = tip - back
        length = max(1e-6, (d.x() ** 2 + d.y() ** 2) ** 0.5)
        ux, uy = d.x() / length, d.y() / length
        left = QPointF(tip.x() - ux * 8 - uy * 4.5, tip.y() - uy * 8 + ux * 4.5)
        right = QPointF(tip.x() - ux * 8 + uy * 4.5, tip.y() - uy * 8 - ux * 4.5)
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawPolygon(QPolygonF([tip, left, right]))


class FrameView(QWidget):
    """Quadro LDP desenhado campo a campo; clicar num campo mostra o que ele faz."""
    selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selection = 0
        self.setMinimumHeight(78)
        self.setMouseTracking(True)

    def sizeHint(self) -> QSize:
        return QSize(820, 78)

    def _rects(self) -> list[QRectF]:
        weights = [f[1] or 4 for f in FRAME_FIELDS]       # payload desenhado mais largo
        unit = (self.width() - 8) / sum(weights)
        x, rects = 4.0, []
        for w in weights:
            rects.append(QRectF(x, 10, w * unit - 3, 40))
            x += w * unit
        return rects

    def mousePressEvent(self, event) -> None:
        for k, r in enumerate(self._rects()):
            if r.contains(event.position()):
                self.selection = k
                self.selected.emit(k)
                self.update()

    def mouseMoveEvent(self, event) -> None:
        hit = any(r.contains(event.position()) for r in self._rects())
        self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for k, (r, (label, size, col, _)) in enumerate(zip(self._rects(), FRAME_FIELDS)):
            c = QColor(col)
            fill = QColor(c)
            fill.setAlpha(235 if k == self.selection else 150)
            p.setPen(QPen(color("TEXT") if k == self.selection else c.darker(130), 2 if k == self.selection else 1))
            p.setBrush(fill)
            p.drawRoundedRect(r, 6, 6)
            p.setPen(QColor("white"))
            p.setFont(mono_font(9, True))
            p.drawText(r, Qt.AlignCenter, label)
            p.setPen(color("MUTED"))
            p.setFont(ui_font(7.5))
            p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 14), Qt.AlignCenter,
                       f"{size} byte{'s' if size > 1 else ''}" if size else f"0–{MAX_PAYLOAD} bytes")
        p.end()


class SequenceView(QWidget):
    """Diagrama de sequencia da transferencia: IDE a esquerda, CLP a direita."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(60 + 44 * len(TRANSFER_STEPS))

    def sizeHint(self) -> QSize:
        return QSize(820, 70 + 44 * len(TRANSFER_STEPS))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        xa, xb = 110.0, min(w - 330.0, 520.0)
        text, muted = color("TEXT"), color("MUTED")
        for x, name in ((xa, "IDE (cliente LDP)"), (xb, "CLP (firmware)")):
            box = QRectF(x - 80, 6, 160, 26)
            p.setPen(QPen(color("ACCENT"), 1.4))
            p.setBrush(color("ACCENT_SOFT"))
            p.drawRoundedRect(box, 7, 7)
            p.setPen(text)
            p.setFont(ui_font(9, True))
            p.drawText(box, Qt.AlignCenter, name)
            p.setPen(QPen(color("BORDER"), 1.4, Qt.DashLine))
            p.drawLine(QPointF(x, 32), QPointF(x, self.height() - 4))
        req_c, resp_c = QColor(CHANNEL_COLORS["device"]), QColor(CHANNEL_COLORS["sim"])
        step = min(70.0, max(44.0, (self.height() - 70) / len(TRANSFER_STEPS)))   # ocupa a altura da aba
        for k, (req, resp, note) in enumerate(TRANSFER_STEPS):
            y = 52 + k * step
            for (x0, x1, yy, label, c, dashed) in ((xa, xb, y, req, req_c, False),
                                                   (xb, xa, y + 18, resp, resp_c, True)):
                p.setPen(QPen(c, 1.8, Qt.DashLine if dashed else Qt.SolidLine))
                p.drawLine(QPointF(x0, yy), QPointF(x1, yy))
                sgn = 1 if x1 > x0 else -1
                p.setPen(Qt.NoPen)
                p.setBrush(c)
                p.drawPolygon(QPolygonF([QPointF(x1, yy), QPointF(x1 - sgn * 8, yy - 4),
                                         QPointF(x1 - sgn * 8, yy + 4)]))
                p.setPen(c if not dashed else muted)
                p.setFont(mono_font(8, True) if not dashed else ui_font(7.5))
                p.drawText(QRectF(min(x0, x1) + 10, yy - 15, abs(x1 - x0) - 20, 14),
                           Qt.AlignLeft if not dashed else Qt.AlignRight, label)
            p.setPen(text)
            p.setFont(ui_font(8))
            p.drawText(QRectF(xb + 16, y - 8, w - xb - 20, 34), Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                       f"{k + 1}. {note}")
        p.end()


ACCENTS = {"invalido": "inválido", "nao": "não", "ha": "há", "valido": "válido", "maximo": "máximo",
           "transferencia": "transferência", "validacao": "validação", "memoria": "memória"}


def _accents(text: str) -> str:
    """Textos do protocol.json sao ASCII (o firmware usa o mesmo arquivo); acentua para exibir."""
    return re.sub(r"[A-Za-z]+", lambda m: ACCENTS.get(m.group(0).lower(), m.group(0)) if m.group(0).islower()
                  else ACCENTS.get(m.group(0).lower(), m.group(0).lower()).capitalize()
                  if m.group(0).lower() in ACCENTS else m.group(0), text)


def _table(headers: list[str], rows: list[list[str]], mono_cols=(0,)) -> QTableWidget:
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().hide()
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setWordWrap(True)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            item = QTableWidgetItem(value)
            if c in mono_cols:
                item.setFont(mono_font(9))
            t.setItem(r, c, item)
    h = t.horizontalHeader()
    for c in range(len(headers) - 1):
        h.setSectionResizeMode(c, QHeaderView.ResizeToContents)
    h.setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)
    t.resizeRowsToContents()
    return t


def _browser(html: str) -> QTextBrowser:
    b = QTextBrowser()
    b.setOpenExternalLinks(False)
    b.setHtml(html)
    return b


class CommGuideDialog(QDialog):
    """Janela da ajuda. `live()` devolve o estado atual da IDE; `session` fornece o trafego LDP."""

    def __init__(self, parent=None, live: Callable[[], dict] | None = None, session=None):
        super().__init__(parent)
        self.setWindowTitle("Como funciona a comunicação")
        self.resize(1180, 720)
        self.live = live
        self.session = session
        self.counts = {"TX": 0, "RX": 0, "RETRY": 0, "ERR": 0}
        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview_tab(), "Visão geral")
        self.tabs.addTab(self._ldp_tab(), "Protocolo LDP")
        self.tabs.addTab(self._transfer_tab(), "Transferência")
        self.tabs.addTab(self._fio_tab(), "Factory IO (Modbus TCP)")
        self.tabs.addTab(self._live_tab(), "Ao vivo")
        layout = QVBoxLayout(self)
        intro = QLabel("Por onde passa o programa LADDER: do editor até o simulador ou até a placa. "
                       "Clique nos blocos e nas setas do mapa para ver como cada parte funciona.")
        intro.setObjectName("muted")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        layout.addWidget(self.tabs, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        if session is not None:
            session.traffic.connect(self.on_traffic)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(500)
        self.refresh()

    # ------------------------------------------------------------- abas
    def _overview_tab(self) -> QWidget:
        self.map = CommMap()
        self.details = _browser("")
        self.map.selected.connect(self._show_details)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.map)
        split.addWidget(self.details)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([780, 340])
        self._show_details(self.map.selection)
        return split

    def _show_details(self, key: str) -> None:
        item = self.map.nodes.get(key) or self.map.edges.get(key)
        state = self.map.status.get(key, "")
        now = "em uso" if key in self.map.active else "parado no momento"
        extra = f"<p><b>Agora:</b> {now}{' — ' + state if state else ''}.</p>"
        self.details.setHtml(item.html + extra if item is not None else "")

    def _ldp_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("<b>Quadro LDP</b> — o mesmo formato em todos os meios (USB, processo virtual, TCP). "
                           "Clique num campo:"))
        self.frame = FrameView()
        self.frame_text = QLabel()
        self.frame_text.setWordWrap(True)
        self.frame.selected.connect(lambda k: self.frame_text.setText(f"<b>{FRAME_FIELDS[k][0]}</b>: "
                                                                     f"{FRAME_FIELDS[k][3]}"))
        self.frame.selected.emit(0)
        v.addWidget(self.frame)
        v.addWidget(self.frame_text)
        req = encode(Cmd.STATUS, 0x2A)
        resp_flag = SPEC["response_flag"]
        example = QLabel(f"Exemplo real — pedido STATUS com seq 0x2A: <code>{req.hex(' ').upper()}</code>"
                         f"<br>A resposta volta com type = 0x{Cmd.STATUS | resp_flag:02X} (STATUS | 0x80) e o "
                         "mesmo seq.")
        example.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(example)
        split = QSplitter(Qt.Horizontal)
        cmds = [[f"0x{c['code']:02X}", c["name"], *CMD_TEXT.get(c["name"], ("", ""))] for c in SPEC["commands"]]
        split.addWidget(_table(["Código", "Comando", "Quando", "O que faz"], cmds, (0, 1)))
        errs = [[str(code), _accents(text)] for code, text in sorted(ERROR_TEXT.items())]
        split.addWidget(_table(["Erro", "Significado"], errs))
        split.setSizes([760, 360])
        v.addWidget(split, 1)
        return w

    def _transfer_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("<b>Transferência transacional</b> — o programa ativo só muda no LOAD_COMMIT. "
                           "Qualquer falha antes disso (cabo solto, CRC errado, imagem inválida, queda de energia) "
                           "mantém o programa antigo."))
        v.addWidget(SequenceView(), 1)
        notes = QLabel("• Sem resposta: a IDE reenvia o mesmo pedido (mesmo seq) até 3 vezes; o CLP não executa "
                       "duas vezes.  • Sessão de carga parada por 5 s volta a STOP.  • Em erro a IDE envia "
                       "LOAD_ABORT.")
        notes.setObjectName("muted")
        notes.setWordWrap(True)
        v.addWidget(notes)
        return w

    def _fio_tab(self) -> QWidget:
        self.fio_view = _browser("")
        return self.fio_view

    def _fio_html(self, cfg) -> str:
        rows = []
        if cfg is not None:
            sensors = "Inputs (FC02)" if cfg.sensor_table == "inputs" else "Coils (FC01)"
            rows = [
                ("Sensores digitais", sensors, f"{cfg.sensor_offset}…{cfg.sensor_offset + cfg.n_sensors - 1}",
                 "→", f"I0.0…I0.{cfg.n_sensors - 1}" if cfg.n_sensors else "—"),
                ("Atuadores digitais", "Coils (FC15)", f"{cfg.actuator_offset}…{cfg.actuator_offset + cfg.n_actuators - 1}",
                 "←", f"Q0.0…Q0.{cfg.n_actuators - 1}" if cfg.n_actuators else "—"),
                ("Valores analógicos", "Input Registers (FC04)", str(cfg.n_input_regs or "—"), "→",
                 f"N{cfg.input_reg_to}…" if cfg.n_input_regs else "—"),
                ("Saídas analógicas", "Holding Registers (FC16)", str(cfg.n_holding_regs or "—"), "←",
                 f"N{cfg.holding_from}…" if cfg.n_holding_regs else "—"),
            ]
        table = "".join(f"<tr><td>{a}</td><td>{b}</td><td align='center'>{c}</td><td align='center'><b>{d}</b>"
                        f"</td><td>{e}</td></tr>" for a, b, c, d, e in rows)
        where = f"{cfg.host}:{cfg.port}, Slave ID {cfg.unit}, ciclo de {cfg.poll_ms} ms" if cfg is not None else ""
        return (
            "<h3>Factory IO por Modbus TCP</h3>"
            "<p>No Factory IO, o driver <b>Modbus TCP/IP Server</b> faz da cena um <i>servidor</i> (escravo). "
            "A IDE é o <i>cliente</i>: abre a conexão TCP e, a cada ciclo, faz uma troca completa:</p>"
            "<ol><li>lê os sensores (FC02, ou FC01 se a cena escreve em Coils);</li>"
            "<li>lê os registradores de entrada (FC04) para os valores analógicos;</li>"
            "<li>escreve as saídas Q do programa nas Coils (FC15);</li>"
            "<li>escreve os registradores N escolhidos nos Holding Registers (FC16).</li></ol>"
            "<p>Essa troca roda numa thread separada; a varredura do simulador só usa o último valor lido, então "
            "nunca espera pela rede. Como o Factory IO roda em tempo real, a simulação fica travada em 1×.</p>"
            f"<p><b>Configuração atual:</b> {where}</p>"
            "<table border='1' cellspacing='0' cellpadding='4'>"
            "<tr><th>Sinal</th><th>Tabela Modbus</th><th>Endereços</th><th>Sentido</th><th>No CLP</th></tr>"
            f"{table}</table>"
            "<p><b>Segurança.</b> Ao desconectar, a IDE escreve 0 em todas as coils e holding registers. Se a "
            "conexão cair, as entradas vindas da cena voltam a 0 e a IDE tenta reconectar a cada 1 s.</p>")

    def _live_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        grid = QGridLayout()
        self.live_labels: dict[str, QLabel] = {}
        for row, (key, title) in enumerate((("compile", "Programa"), ("sim", "Simulação"),
                                            ("process", "Processo ligado"), ("fio", "Factory IO"),
                                            ("device", "Dispositivo"), ("frames", "Quadros LDP"))):
            name = QLabel(f"<b>{title}</b>")
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self.live_labels[key] = value
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        bar = QHBoxLayout()
        bar.addWidget(QLabel("<b>Tráfego LDP</b> (cada pedido e resposta trocados com o CLP)"))
        bar.addStretch(1)
        self.hide_periodic = QCheckBox("Ocultar leituras periódicas")
        self.hide_periodic.setToolTip("STATUS, READ_IO e READ_VARS se repetem várias vezes por segundo")
        self.hide_periodic.setChecked(True)
        bar.addWidget(self.hide_periodic)
        self.pause_log = QCheckBox("Pausar")
        bar.addWidget(self.pause_log)
        clear = QPushButton("Limpar")
        clear.clicked.connect(self._clear_log)
        bar.addWidget(clear)
        v.addLayout(bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(mono_font(9))
        self.log.setMaximumBlockCount(2000)
        self.log.setPlaceholderText("Nenhum quadro ainda. Conecte a placa virtual ou o ESP32 (painel Dispositivo) "
                                    "e transfira um programa para ver os quadros aqui.")
        v.addWidget(self.log, 1)
        return w

    def _clear_log(self) -> None:
        self.log.clear()
        self.counts = dict.fromkeys(self.counts, 0)
        self.refresh()

    # ------------------------------------------------------------ ao vivo
    def on_traffic(self, direction: str, cmd: str, seq: int, nbytes: int) -> None:
        self.counts[direction] = self.counts.get(direction, 0) + 1
        if cmd.startswith("LOAD_"):
            self._last_load = time.monotonic()
        if self.pause_log.isChecked() or (self.hide_periodic.isChecked() and cmd in PERIODIC
                                          and direction in ("TX", "RX")):
            return
        arrow = {"TX": "IDE → CLP", "RX": "CLP → IDE", "RETRY": "reenvio  ", "ERR": "erro     "}.get(direction,
                                                                                                  direction)
        stamp = time.strftime("%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"
        self.log.appendPlainText(f"{stamp}  {arrow}  {cmd:<14} seq {seq:3d}  {nbytes:4d} bytes")

    def refresh(self) -> None:
        st = self.live() if self.live is not None else {}
        active: set[str] = {"editor"}
        status: dict[str, str] = {}
        if st.get("compiled"):
            active.add("compiler")
            status["compiler"] = f"{st.get('program_bytes', 0)} bytes de LDRB"
        sim_on = st.get("sim") == "rodando"
        if st.get("sim") not in (None, "parada"):
            active |= {"sim", "e_compile", "e_load_sim"}
            status["sim"] = f"{st.get('sim')}, {st.get('scans', 0)} varreduras"
        fio = st.get("fio")
        if fio:
            status["fio"] = fio
            if fio.startswith("conectado"):
                active |= {"fio"} | ({"e_fio"} if sim_on else set())
        elif st.get("env"):
            status["env"] = st["env"]
            active.add("env")
            if sim_on:
                active.add("e_plant")
        device = st.get("device")
        if device:
            active |= {"client", "transport", "firmware", "e_ldp", "e_wire", "io"}
            status["transport"] = device
            status["firmware"] = st.get("device_state", "")
            if st.get("device_state") == "RUN":
                active.add("e_io")
            if time.monotonic() - getattr(self, "_last_load", -10.0) < 2.0:
                active |= {"e_transfer", "e_compile"}
                status["client"] = "transferindo..."
        status["scada"] = "só na placa real"
        self.map.active = active
        self.map.status = status
        self.map.update()
        if self.map.selection:
            self._show_details(self.map.selection)
        cfg = st.get("fio_config")
        if self.tabs.currentIndex() == 3 or not self.fio_view.toPlainText():
            pos = self.fio_view.verticalScrollBar().value()
            self.fio_view.setHtml(self._fio_html(cfg))
            self.fio_view.verticalScrollBar().setValue(pos)
        L = self.live_labels
        L["compile"].setText(f"compilado ({st.get('program_bytes', 0)} bytes LDRB)" if st.get("compiled")
                             else "não compilado")
        L["sim"].setText(f"{st.get('sim', 'parada')}" + (f" — {st.get('scans', 0)} varreduras"
                                                         if st.get("sim") not in (None, "parada") else ""))
        L["process"].setText("Factory IO" if fio else st.get("env") or "nenhum (entradas pelo painel de E/S)")
        L["fio"].setText(fio or "desconectado")
        L["device"].setText(f"{device} — {st.get('device_state', '')}" if device else "desconectado")
        c = self.counts
        L["frames"].setText(f"{c['TX']} enviados, {c['RX']} recebidos, {c['RETRY']} reenvios, {c['ERR']} erros")
