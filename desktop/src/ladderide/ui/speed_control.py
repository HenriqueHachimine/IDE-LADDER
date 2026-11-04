"""Controle da velocidade da simulacao: valor livre (digitado) e predefinicoes.

Um unico SpeedModel e compartilhado pela caixa da barra de ferramentas, pelos
atalhos e pelo Factory IO (que trava em 1x), entao todos usam sempre o mesmo valor.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QComboBox

MIN_SPEED = 0.01
MAX_SPEED = 1000.0
PRESETS = [0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0, math.inf]
HINT = ("Velocidade do tempo simulado (temporizadores e ambiente). Digite qualquer valor entre "
        f"{MIN_SPEED:g}x e {MAX_SPEED:g}x (ex.: 3, 0,5 ou 2,5x) ou \"max\". "
        "Ctrl+. acelera, Ctrl+, desacelera, Ctrl+; volta ao tempo real.")


def format_speed(value: float) -> str:
    if math.isinf(value):
        return "Máxima"
    if value >= 100:
        text = f"{value:.0f}"
    elif value >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",") + "x"


def parse_speed(text: str) -> float | None:
    """'3', '2,5x', '0.5 x', 'max' -> valor; None se nao for uma velocidade valida."""
    t = text.strip().lower().replace(" ", "").removesuffix("(temporeal)")
    if t in ("max", "maxima", "máxima", "máx", "inf"):
        return math.inf
    t = t.removesuffix("x").replace(",", ".")
    try:
        value = float(t)
    except ValueError:
        return None
    if not math.isfinite(value) or value <= 0:
        return None
    return min(MAX_SPEED, max(MIN_SPEED, value))


class SpeedModel(QObject):
    changed = Signal(float)

    def __init__(self, value: float = 1.0, parent=None):
        super().__init__(parent)
        self._value = value

    @property
    def value(self) -> float:
        return self._value

    def set(self, value: float) -> None:
        if not math.isinf(value):
            value = min(MAX_SPEED, max(MIN_SPEED, float(value)))
        if value != self._value:
            self._value = value
            self.changed.emit(value)

    def step(self, steps: int) -> None:
        """Vai para a predefinicao seguinte (steps > 0) ou anterior, a partir de qualquer valor."""
        v = self._value
        if steps > 0:
            bigger = [p for p in PRESETS if p > v * 1.0001]
            self.set(bigger[min(steps, len(bigger)) - 1] if bigger else PRESETS[-1])
        elif steps < 0:
            smaller = [p for p in PRESETS if p < v / 1.0001]
            self.set(smaller[max(-len(smaller), steps)] if smaller else PRESETS[0])


class SpeedCombo(QComboBox):
    """Lista de predefinicoes onde tambem se digita qualquer velocidade."""

    def __init__(self, model: SpeedModel, parent=None):
        super().__init__(parent)
        self.model_ = model
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        for p in PRESETS:
            self.addItem("1x (tempo real)" if p == 1.0 else format_speed(p), p)
        self.setToolTip(HINT)
        self.setMinimumContentsLength(11)          # cabe "1x (tempo real)" inteiro (texto estreito)
        self.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.activated.connect(lambda i: self._apply(self.itemText(i)))
        self.lineEdit().editingFinished.connect(lambda: self._apply(self.currentText()))
        model.changed.connect(self._show)
        self._show(model.value)

    def _apply(self, text: str) -> None:
        value = parse_speed(text)
        if value is None:
            self._show(self.model_.value)          # texto invalido: volta ao valor atual
        else:
            self.model_.set(value)
            self._show(self.model_.value)

    def _show(self, value: float) -> None:
        self.blockSignals(True)
        index = self.findData(value)
        if index >= 0:
            self.setCurrentIndex(index)
        self.setEditText(self.itemText(index) if index >= 0 else format_speed(value))
        self.blockSignals(False)

