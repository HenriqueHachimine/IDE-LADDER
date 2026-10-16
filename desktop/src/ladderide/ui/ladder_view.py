"""Area de desenho do diagrama LADDER (Qt Graphics View).

A view so desenha o modelo e o estado vindo de uma "fonte ao vivo"
(simulador ou monitor online). Edicoes sao emitidas como sinais e aplicadas
pela janela principal via ladderide.model.edit.
"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QFont, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QMenu)

from ..model.project import Coil, Contact, CounterBox, NotOp, Parallel, Project, ResetBox, TimerBox
from .layout import Layout, PlacedElem, Slot, build_layout
from .symbols import (CURRENT_BORDER, DEENERGIZED, ENERGIZED, ERROR_FILL, NEUTRAL, SELECTED_BORDER,
                      SELECTED_FILL, SymbolState, paint_symbol)

SX, SY = 96.0, 62.0        # pixels por unidade de grade
LABEL_W = 0.8
MIME_TOOL = "application/x-ladder-tool"
MIME_MOVE = "application/x-ladder-move"
OUTPUT_TOOLS = {"OTE", "OTL", "OTU", "TON", "TOF", "RTO", "CTU", "CTD", "RES"}
COND_TOOLS = {"XIC", "XIO", "NOT", "PAR"}


class LiveSource(Protocol):
    """Interface comum ao simulador e ao monitor online."""
    def element_power(self, element_id: str) -> bool: ...
    def branch_power(self, parallel_id: str) -> bool: ...
    def operand_value(self, element_id: str) -> bool | None: ...
    def timer_state(self, index: int): ...
    def counter_state(self, index: int): ...
    @property
    def current_element(self) -> str | None: ...


def node_kind(node) -> str:
    if isinstance(node, Contact):
        return node.kind
    if isinstance(node, NotOp):
        return "NOT"
    if isinstance(node, Parallel):
        return "PAR"
    if isinstance(node, (Coil, TimerBox, CounterBox)):
        return node.kind
    if isinstance(node, ResetBox):
        return "RES"
    return "?"


class ElementItem(QGraphicsItem):
    def __init__(self, placed: PlacedElem, view: "LadderView"):
        super().__init__()
        self.placed = placed
        self.view = view
        self.node = placed.node
        self.kind = node_kind(self.node)
        self.rect = QRectF(placed.x * SX, placed.y * SY, placed.w * SX, placed.h * SY)
        self.state = SymbolState()
        self.selected = False
        self.current = False
        self.has_error = False
        self.setZValue(-1 if self.kind == "PAR" else 1)
        self.setAcceptHoverEvents(True)
        self.refresh_labels()

    def boundingRect(self) -> QRectF:
        return self.rect.adjusted(-2, -2, 2, 2)

    def refresh_labels(self) -> None:
        node, project = self.node, self.view.project
        operand = getattr(node, "operand", "")
        st = self.state
        st.label, st.sublabel = operand, ""
        if operand:
            symbol_addr = next((s.address for s in project.symbols if s.name.upper() == operand.upper()), None)
            if symbol_addr:
                st.sublabel = symbol_addr.upper()
            else:
                name = project.symbol_for(operand)
                if name:
                    st.label, st.sublabel = name, operand.upper()
        if isinstance(node, TimerBox):
            st.lines = (f"PRE {node.preset} ms", "ACC -")
        elif isinstance(node, CounterBox):
            st.lines = (f"PRE {node.preset}", "ACC -")
        tip = {"XIC": "Contato normalmente aberto (NA / XIC)", "XIO": "Contato normalmente fechado (NF / XIO)",
               "NOT": "Inversor (NOT)", "OTE": "Bobina", "OTL": "Bobina SET (OTL)", "OTU": "Bobina RESET (OTU)",
               "RES": "Reset de temporizador/contador", "PAR": "Ramificacao paralela (OR)"}.get(self.kind, self.kind)
        self.setToolTip(f"{tip}\n{operand}" if operand else tip)

    def paint(self, p: QPainter, option, widget=None) -> None:
        r = self.rect
        if self.has_error:
            p.fillRect(r, ERROR_FILL)
        if self.kind == "PAR":
            if self.selected:
                pen = QPen(SELECTED_BORDER, 1.5, Qt.DashLine)
                p.setPen(pen)
                p.drawRect(r.adjusted(-3, 2, 3, -2))
            return
        if self.selected:
            p.fillRect(r.adjusted(1, 1, -1, -1), SELECTED_FILL)
            p.setPen(QPen(SELECTED_BORDER, 1))
            p.drawRect(r.adjusted(1, 1, -1, -1))
        if self.current:
            p.setPen(QPen(CURRENT_BORDER, 2.5))
            p.drawRect(r.adjusted(2, 2, -2, -2))
        paint_symbol(p, self.kind, r, self.state)


class LadderView(QGraphicsView):
    selectionChangedTo = Signal(object)          # id de elemento, ("rung", n) ou None
    editRequested = Signal(str)                  # id
    dropRequested = Signal(str, str, object)     # "tool"|"move", payload, Slot
    actionRequested = Signal(str, object)        # acao, alvo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setBackgroundBrush(QColor(250, 250, 249))
        self.project: Project | None = None
        self.layout_: Layout | None = None
        self.items_by_id: dict[str, ElementItem] = {}
        self.wire_items: list[tuple[QGraphicsLineItem, tuple | None]] = []
        self.rail_items: list[QGraphicsLineItem] = []
        self.rung_labels: list[tuple[QGraphicsRectItem, int]] = []
        self.selection: object = None
        self.readonly = False
        self.error_ids: set[str] = set()
        self._press_pos = None
        self._press_item: ElementItem | None = None
        self.highlight = None
        self.zoom = 1.0

    # --------------------------------------------------------------- montagem
    def rebuild(self, project: Project) -> None:
        self.project = project
        scene = self.scene()
        scene.clear()
        self.items_by_id.clear()
        self.wire_items.clear()
        self.rail_items.clear()
        self.rung_labels.clear()
        lay = self.layout_ = build_layout(project)
        top, bottom = -0.3 * SY, (lay.height - 1.0) * SY
        for x in (0.0, lay.rail_right * SX):
            line = scene.addLine(x, top, x, bottom, QPen(NEUTRAL, 4))
            self.rail_items.append(line)
        for w in lay.wires:
            item = scene.addLine(w.x1 * SX, w.y1 * SY, w.x2 * SX, w.y2 * SY, QPen(NEUTRAL, 2))
            item.setZValue(0)
            self.wire_items.append((item, w.key))
        for placed in lay.elems:
            item = ElementItem(placed, self)
            item.has_error = placed.node.id in self.error_ids
            scene.addItem(item)
            self.items_by_id[placed.node.id] = item
        for rb in lay.rungs:
            box = QRectF(-LABEL_W * SX, rb.y * SY, LABEL_W * SX - 8, rb.h * SY)
            rect = scene.addRect(box, QPen(Qt.NoPen))
            rect.setData(0, rb.index)
            text = scene.addText(str(rb.index), QFont("Segoe UI", 11, QFont.Bold))
            text.setDefaultTextColor(QColor(71, 85, 105))
            text.setPos(box.left() + 6, box.top() + 4)
            if rb.rung.comment:
                rect.setToolTip(rb.rung.comment)
                c = scene.addText(rb.rung.comment[:14], QFont("Segoe UI", 7))
                c.setDefaultTextColor(QColor(100, 116, 139))
                c.setPos(box.left(), box.top() + 26)
            self.rung_labels.append((rect, rb.index))
        self.highlight = scene.addRect(QRectF(), QPen(SELECTED_BORDER, 1.5), QColor(59, 130, 246, 60))
        self.highlight.setZValue(10)
        self.highlight.hide()
        scene.setSceneRect(QRectF(-LABEL_W * SX - 10, top - 10, (lay.rail_right + LABEL_W + 1) * SX,
                                  bottom - top + 2 * SY))
        self._apply_selection()

    def set_errors(self, ids: set[str]) -> None:
        self.error_ids = ids
        for eid, item in self.items_by_id.items():
            item.has_error = eid in ids
            item.update()

    # ------------------------------------------------------------- ao vivo
    def update_live(self, source: LiveSource | None, rail: bool = True) -> None:
        """Atualiza cores e valores. source=None volta ao modo edicao."""
        def power(key) -> bool | None:
            if source is None or key is None:
                return None
            if key[0] == "rail":
                return rail
            if key[0] == "elem":
                return source.element_power(key[1])
            return source.branch_power(key[1])

        for line, key in self.wire_items:
            pw = power(key)
            line.setPen(QPen(NEUTRAL if pw is None else (ENERGIZED if pw else DEENERGIZED), 3 if pw else 2))
        for line in self.rail_items:
            line.setPen(QPen(ENERGIZED if (source is not None and rail) else NEUTRAL, 4))
        current = source.current_element if source is not None else None
        for eid, item in self.items_by_id.items():
            st = item.state
            st.power_in = power(item.placed.in_key)
            st.power_out = None if source is None else source.element_power(eid)
            st.closed = source.operand_value(eid) if source is not None and item.kind in ("XIC", "XIO") else None
            if st.closed is not None and item.kind == "XIO":
                st.closed = not st.closed
            node = item.node
            if isinstance(node, (TimerBox, CounterBox)):
                is_timer = isinstance(node, TimerBox)
                pre = f"PRE {node.preset} ms" if is_timer else f"PRE {node.preset}"
                data = None
                if source is not None:
                    idx = _element_index(node.operand, self.project)
                    data = source.timer_state(idx) if is_timer else source.counter_state(idx)
                if data is None:
                    st.lines, st.done = (pre, "ACC -"), None
                else:
                    unit = " ms" if is_timer else ""
                    flags = "  ".join(n for n, v in data["bits"].items() if v)
                    st.lines, st.done = (pre, f"ACC {data['acc']}{unit}", flags), data["bits"].get("DN")
            item.current = eid == current
            item.update()

    # ------------------------------------------------------------ selecao
    def select(self, target) -> None:
        self.selection = target
        self._apply_selection()
        self.selectionChangedTo.emit(target)
        if isinstance(target, str) and target in self.items_by_id:
            self.ensureVisible(self.items_by_id[target], 40, 40)

    def _apply_selection(self) -> None:
        for eid, item in self.items_by_id.items():
            item.selected = eid == self.selection
            item.update()
        for rect, idx in self.rung_labels:
            selected = self.selection == ("rung", idx)
            rect.setBrush(QColor(59, 130, 246, 60) if selected else QColor(0, 0, 0, 0))

    def _item_at(self, pos) -> ElementItem | QGraphicsRectItem | None:
        found = [i for i in self.items(pos) if isinstance(i, ElementItem)]
        if found:
            found.sort(key=lambda i: i.zValue(), reverse=True)
            return found[0]
        for i in self.items(pos):
            if isinstance(i, QGraphicsRectItem) and i.data(0) is not None:
                return i
        return None

    # ------------------------------------------------------------- mouse
    def mousePressEvent(self, event) -> None:
        item = self._item_at(event.position().toPoint())
        if isinstance(item, ElementItem):
            self.select(item.node.id)
            self._press_item = item
            self._press_pos = event.position()
        elif item is not None:
            self.select(("rung", item.data(0)))
        else:
            self.select(None)
        if event.button() == Qt.MiddleButton:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if (self._press_item is not None and not self.readonly and event.buttons() & Qt.LeftButton
                and (event.position() - self._press_pos).manhattanLength() > QApplication.startDragDistance()):
            mime = QMimeData()
            mime.setData(MIME_MOVE, self._press_item.node.id.encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            self._press_item = None
            drag.exec(Qt.MoveAction)
            self.highlight.hide()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_item = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self._item_at(event.position().toPoint())
        if isinstance(item, ElementItem) and item.kind != "PAR":
            self.editRequested.emit(item.node.id)
        elif item is not None and not isinstance(item, ElementItem):
            self.actionRequested.emit("rung_comment", item.data(0))

    def wheelEvent(self, event) -> None:
        if event.modifiers() & Qt.ControlModifier:
            self.set_zoom(self.zoom * (1.15 if event.angleDelta().y() > 0 else 1 / 1.15))
        else:
            super().wheelEvent(event)

    def set_zoom(self, z: float) -> None:
        self.zoom = max(0.3, min(3.0, z))
        self.resetTransform()
        self.scale(self.zoom, self.zoom)

    def contextMenuEvent(self, event) -> None:
        item = self._item_at(event.pos())
        menu = QMenu(self)

        def add(text: str, action: str, target, enabled: bool = True) -> None:
            a = QAction(text, menu)
            a.setEnabled(enabled and not self.readonly)
            a.triggered.connect(lambda: self.actionRequested.emit(action, target))
            menu.addAction(a)

        if isinstance(item, ElementItem):
            self.select(item.node.id)
            eid = item.node.id
            in_branch = self.project.find_parent_parallel(eid) is not None
            if item.kind != "PAR":
                add("Editar...", "edit", eid)
            if item.kind in ("XIC", "XIO", "NOT", "PAR"):
                add("Envolver em ramo paralelo", "wrap", eid)
            if item.kind == "PAR" or in_branch:
                add("Adicionar ramo paralelo", "add_branch", eid)
            if in_branch:
                add("Excluir este ramo", "remove_branch", eid)
            menu.addSeparator()
            add("Excluir", "delete", eid)
        else:
            rung = item.data(0) if item is not None else None
            if rung is not None:
                self.select(("rung", rung))
                add("Inserir rede acima", "rung_above", rung)
                add("Inserir rede abaixo", "rung_below", rung)
                add("Comentario da rede...", "rung_comment", rung)
                menu.addSeparator()
                add("Excluir rede", "rung_delete", rung)
            else:
                add("Nova rede no final", "rung_append", None)
        menu.exec(event.globalPos())

    # -------------------------------------------------------- arrastar/soltar
    def _drag_info(self, event) -> tuple[str, str, str] | None:
        mime = event.mimeData()
        if mime.hasFormat(MIME_TOOL):
            tool = bytes(mime.data(MIME_TOOL)).decode()
            return "tool", tool, "out" if tool in OUTPUT_TOOLS else "cond"
        if mime.hasFormat(MIME_MOVE) and self.project is not None:
            eid = bytes(mime.data(MIME_MOVE)).decode()
            hit = self.project.find(eid)
            if hit is None:
                return None
            return "move", eid, "out" if node_kind(hit[1]) in OUTPUT_TOOLS else "cond"
        return None

    def _slot_for(self, event) -> tuple[tuple[str, str, str], Slot] | None:
        info = self._drag_info(event)
        if info is None or self.readonly or self.layout_ is None:
            return None
        sp = self.mapToScene(event.position().toPoint())
        slot = self.layout_.slot_at(sp.x() / SX, sp.y() / SY, info[2])
        if info[1] == "RUNG":
            slot = None
        return (info, slot) if slot else None

    def dragEnterEvent(self, event) -> None:
        if self._drag_info(event) is not None and not self.readonly:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._drag_info(event) is None or self.readonly:
            event.ignore()
            return
        found = self._slot_for(event)
        if found:
            x, y, w, h = found[1].rect
            self.highlight.setRect(QRectF(x * SX, y * SY, w * SX, h * SY))
            self.highlight.show()
        else:
            self.highlight.hide()
        event.acceptProposedAction()

    def dragLeaveEvent(self, event) -> None:
        if self.highlight is not None:
            self.highlight.hide()

    def dropEvent(self, event) -> None:
        if self.highlight is not None:
            self.highlight.hide()
        info = self._drag_info(event)
        if info and info[1] == "RUNG":
            self.actionRequested.emit("rung_append", None)
            event.acceptProposedAction()
            return
        found = self._slot_for(event)
        if found:
            (mode, payload, _), slot = found
            event.acceptProposedAction()
            self.dropRequested.emit(mode, payload, slot)
        else:
            event.ignore()


def _element_index(operand: str, project: Project) -> int:
    text = operand.strip()
    for s in project.symbols:
        if s.name.upper() == text.upper():
            text = s.address
            break
    try:
        return int(text.strip()[1:].split(".")[0])
    except ValueError:
        return -1
