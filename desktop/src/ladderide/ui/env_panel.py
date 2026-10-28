"""Painel generico dos ambientes de simulacao (nao conhece nenhum ambiente especifico)."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..envs import BUTTON, SWITCH, Environment, EnvironmentPlant, available, create
from ..envs.registry import load_errors
from .theme import themed
from .fonts import ui_font

VIEW_BG = themed("#e2e8f0", "#0b1120")
VIEW_TEXT = themed("#64748b", "#94a3b8")
VALUE_ON = themed("#15803d", "#4ade80")

KIND_TEXT = {BUTTON: "botão", SWITCH: "chave", "sensor": "sensor"}


class EnvironmentView(QWidget):
    """Desenha o ambiente escalado e repassa cliques nos controles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.env: Environment | None = None
        self.pressed_key: str | None = None
        self.setMouseTracking(True)
        self.setMinimumSize(220, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.on_change = lambda: None

    def _transform(self) -> tuple[float, float, float]:
        w, h = self.env.size
        scale = min(self.width() / w, self.height() / h)
        return scale, (self.width() - w * scale) / 2, (self.height() - h * scale) / 2

    def _to_env(self, pos) -> tuple[float, float]:
        scale, ox, oy = self._transform()
        return (pos.x() - ox) / scale, (pos.y() - oy) / scale

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), VIEW_BG)
        if self.env is None:
            p.setPen(VIEW_TEXT)
            p.setFont(ui_font(10))
            p.drawText(self.rect(), Qt.AlignCenter, "Escolha um ambiente de simulação acima")
            return
        scale, ox, oy = self._transform()
        w, h = self.env.size
        p.save()
        p.translate(ox, oy)
        p.scale(scale, scale)
        p.setClipRect(QRectF(0, 0, w, h))
        try:
            self.env.paint(p)
        except Exception as exc:  # noqa: BLE001 - erro em um ambiente nao derruba a IDE
            p.fillRect(QRectF(0, 0, w, h), QColor("#7f1d1d"))
            p.setPen(QColor("white"))
            p.drawText(QRectF(10, 10, w - 20, h - 20), Qt.TextWordWrap, f"Erro ao desenhar o ambiente:\n{exc}")
        p.restore()
        alarms = self.env.alarms()
        if alarms:
            p.setFont(ui_font(9, bold=True))
            line_h = p.fontMetrics().height() + 4
            box = QRectF(ox + 6, oy + 6, w * scale - 12, line_h * len(alarms) + 8)
            p.setPen(QPen(QColor("#7f1d1d"), 1))
            p.setBrush(QColor(220, 38, 38, 225))
            p.drawRoundedRect(box, 6, 6)
            p.setPen(QColor("white"))
            for k, a in enumerate(alarms):
                p.drawText(QRectF(box.left() + 10, box.top() + 4 + k * line_h, box.width() - 20, line_h),
                           Qt.AlignLeft | Qt.AlignVCenter, "⚠ " + a)

    def mousePressEvent(self, event) -> None:
        if self.env is None or event.button() != Qt.LeftButton:
            return
        key = self.env.control_at(*self._to_env(event.position()))
        if key:
            self.pressed_key = key
            self.env.press(key, True)
            self.on_change()
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self.env is not None and self.pressed_key:
            self.env.press(self.pressed_key, False)
            self.pressed_key = None
            self.on_change()
            self.update()

    def mouseMoveEvent(self, event) -> None:
        over = self.env is not None and self.env.control_at(*self._to_env(event.position())) is not None
        self.setCursor(Qt.PointingHandCursor if over else Qt.ArrowCursor)


class EnvironmentPanel(QWidget):
    environmentChanged = Signal(str)      # id ("" = nenhum)
    symbolsRequested = Signal()
    exampleRequested = Signal(str)
    plantChanged = Signal()               # o ambiente refez os pontos de E/S (troca de controlador)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.io = (8, 8, 32)                # entradas, saidas e registradores N do projeto
        self.env: Environment | None = None
        self.plant: EnvironmentPlant | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        row = QHBoxLayout()                 # escolha e acoes numa linha so: mais altura para a cena
        row.addWidget(QLabel("Ambiente:"))
        self.combo = QComboBox()
        self.combo.addItem("(nenhum - usar apenas o painel de E/S)", "")
        for cls in available():
            self.combo.addItem(cls.name, cls.id)
        self.combo.currentIndexChanged.connect(self._combo_changed)
        row.addWidget(self.combo, 1)
        layout.addLayout(row)
        self._row = row
        self.description = QLabel()         # fica na coluna lateral, ao lado da cena
        self.description.setWordWrap(True)
        self.description.setObjectName("muted")
        self.reset_btn = QPushButton("Reiniciar")
        self.symbols_btn = QPushButton("Criar símbolos")
        self.example_btn = QPushButton("Abrir exemplo")
        self.reset_btn.setToolTip("Volta o processo ao estado inicial")
        self.symbols_btn.setToolTip("Adiciona ao projeto os nomes dos pontos de E/S do ambiente")
        self.example_btn.setToolTip("Abre um programa LADDER pronto para este ambiente")
        self.reset_btn.clicked.connect(self.reset_process)
        self.symbols_btn.clicked.connect(self.symbolsRequested)
        self.example_btn.clicked.connect(lambda: self.env and self.exampleRequested.emit(self.env.example))
        for b in (self.reset_btn, self.symbols_btn, self.example_btn):
            self._row.addWidget(b)
        self.view = EnvironmentView()
        self.view.on_change = self._refresh_table
        body = QHBoxLayout()                # cena (paisagem) ao lado da tabela de E/S
        body.addWidget(self.view, 3)
        side = QVBoxLayout()
        side.addWidget(self.description)
        self.stats = QLabel()
        self.stats.setObjectName("stats")
        self.stats.setWordWrap(True)
        side.addWidget(self.stats)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Endereço", "Nome", "Tipo", "Valor"])
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setMinimumWidth(200)
        self.table.setMinimumHeight(60)
        self.table.setMaximumWidth(340)
        side.addWidget(self.table, 1)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)
        if load_errors:
            warn = QLabel("Ambientes com erro: " + "; ".join(load_errors))
            warn.setWordWrap(True)
            warn.setObjectName("danger")
            layout.addWidget(warn)
        self._set(None)

    # ------------------------------------------------------------ selecao
    def _combo_changed(self) -> None:
        env_id = self.combo.currentData() or ""
        self._set(create(env_id) if env_id else None)
        self.environmentChanged.emit(env_id)

    def select(self, env_id: str) -> None:
        """Seleciona sem emitir environmentChanged (ex.: ao abrir um projeto)."""
        idx = max(0, self.combo.findData(env_id or ""))
        self.combo.blockSignals(True)
        self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(False)
        env_id = self.combo.currentData() or ""
        self._set(create(env_id) if env_id else None)

    def set_io(self, n_inputs: int, n_outputs: int, n_words: int) -> None:
        """Quantidades do projeto; ambientes que se adaptam ao controlador refazem os pontos."""
        self.io = (n_inputs, n_outputs, n_words)
        if self.env is not None and self.env.configure(*self.io):
            self._set(self.env)
            self.plantChanged.emit()

    def _set(self, env: Environment | None) -> None:
        if env is not None:
            env.configure(*self.io)
        self.env = env
        self.plant = EnvironmentPlant(env) if env is not None else None
        self.view.env = env
        self.description.setText(env.description if env else
                                 "Escolha um processo animado (silo, semáforo, portão...) para testar a lógica.")
        for b in (self.reset_btn, self.symbols_btn):
            b.setEnabled(env is not None)
        self.example_btn.setEnabled(env is not None and bool(env.example))
        points = ([("in", p) for p in env.inputs] + [("out", p) for p in env.outputs]) if env else []
        self.table.setRowCount(len(points))
        for row, (direction, pt) in enumerate(points):
            kind = KIND_TEXT.get(pt.kind, pt.kind) if direction == "in" else "saída"
            if pt.normally_closed:
                kind += " NF"
            for col, text in enumerate((pt.address, pt.label, kind, "-")):
                item = QTableWidgetItem(text)
                item.setToolTip(pt.description)
                self.table.setItem(row, col, item)
        self._points = points
        self.refresh(None)

    def reset_process(self) -> None:
        if self.plant is not None:
            self.plant.reset()
            self.refresh(None)

    # ------------------------------------------------------------ estado
    @property
    def owned_inputs(self) -> int:
        return self.plant.owned_inputs if self.plant else 0

    def refresh(self, outputs: int | None) -> None:
        """Atualiza desenho e tabela. outputs: saidas fisicas atuais (para exibir)."""
        if self.plant is not None and outputs is not None:
            self.plant.show_outputs(outputs)
        if self.env is not None:
            self.stats.setText("\n".join(self.env.stats()))
        else:
            self.stats.setText("")
        self._refresh_table()
        self.view.update()

    def _refresh_table(self) -> None:
        if self.env is None:
            return
        values = self.plant.input_values()
        current = {p.key: p for p in self.env.inputs}       # o tipo da botoeira pode mudar
        for row, (direction, pt) in enumerate(self._points):
            if direction == "in" and pt.key in current and current[pt.key] != pt:
                pt = current[pt.key]
                self._points[row] = (direction, pt)
                self.table.item(row, 2).setText(KIND_TEXT.get(pt.kind, pt.kind) + (" NF" if pt.normally_closed else ""))
                self.table.item(row, 2).setToolTip(pt.description)
            v = values.get(pt.key) if direction == "in" else self.env.out.get(pt.key)
            item = self.table.item(row, 3)
            item.setText("1" if v else "0")
            item.setForeground(VALUE_ON if v else VIEW_TEXT)
