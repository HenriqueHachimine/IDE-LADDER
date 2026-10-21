"""Area de desenho do diagrama LADDER (Qt Graphics View).

A view so desenha o modelo e o estado vindo de uma "fonte ao vivo"
(simulador ou monitor online). Edicoes sao emitidas como sinais e aplicadas
pela janela principal via ladderide.model.edit.
"""
from __future__ import annotations

from typing import Protocol

from PySide6.QtCore import QMimeData, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QGraphicsItem, QGraphicsLineItem, QGraphicsRectItem,
                               QGraphicsScene, QGraphicsView, QMenu)

from ..core.asm import parse_constant
from ..model.project import (COMPARE_KINDS, MATH_KINDS, Coil, CompareBox, Contact, CounterBox, MathBox, NotOp,
                             Parallel, Project, ResetBox, TimerBox)
from .layout import RUNG_HEAD, RUNG_PAD, Layout, PlacedElem, Slot, build_layout
from .symbols import (CURRENT_BORDER, DEENERGIZED, ENERGIZED, ERROR_FILL, NEUTRAL, SELECTED_BORDER,
                      SELECTED_FILL, SymbolState, paint_symbol)
from .theme import themed
from .fonts import ui_font

SX, SY = 100.0, 66.0       # pixels por unidade de grade
LABEL_W = 0.3              # margem entre a borda do cartao e o trilho esquerdo
CANVAS = themed((238, 242, 247), (11, 17, 32))
CARD_FILL = themed((255, 255, 255), (21, 30, 46))
CARD_BORDER = themed((216, 224, 234), (42, 54, 73))
CARD_HEAD_LINE = themed((238, 242, 247), (31, 42, 61))
BADGE_FILL = themed((238, 242, 255), (49, 46, 129))
BADGE_TEXT = themed((55, 48, 163), (199, 210, 254))
COMMENT_TEXT = themed((100, 116, 139), (148, 163, 184))
HINT_BORDER = themed((148, 163, 184), (71, 85, 105))
MIME_TOOL = "application/x-ladder-tool"
MIME_MOVE = "application/x-ladder-move"
OUTPUT_TOOLS = {"OTE", "OTL", "OTU", "TON", "TOF", "RTO", "CTU", "CTD", "RES"} | set(MATH_KINDS)
COND_TOOLS = {"XIC", "XIO", "NOT", "PAR"} | set(COMPARE_KINDS)
WRAPPABLE = {"XIC", "XIO", "NOT", "PAR"} | set(COMPARE_KINDS)


BLOCK_TIPS = {
    "EQU": "EQU - igual: conduz se A = B", "NEQ": "NEQ - diferente: conduz se A \u2260 B",
    "LES": "LES - menor: conduz se A < B", "GRT": "GRT - maior: conduz se A > B",
    "LEQ": "LEQ - menor ou igual: conduz se A \u2264 B", "GEQ": "GEQ - maior ou igual: conduz se A \u2265 B",
    "LIM": "LIM - teste de limite: conduz se inferior \u2264 teste \u2264 superior\n"
           "(com inferior > superior conduz fora da faixa)",
    "MEQ": "MEQ - comparacao com mascara: (origem AND mascara) = (comparar AND mascara)",
    "ADD": "ADD - soma: destino = A + B", "SUB": "SUB - subtracao: destino = A - B",
    "MUL": "MUL - multiplicacao: destino = A \u00d7 B",
    "DIV": "DIV - divisao inteira: destino = A \u00f7 B (truncada; divisao por zero liga S0.4)",
    "SQR": "SQR - raiz quadrada (arredondada)", "NEG": "NEG - troca o sinal: destino = -origem",
    "TOD": "TOD - converte inteiro para BCD", "FRD": "FRD - converte BCD para inteiro",
}


class LiveSource(Protocol):
    """Interface comum ao simulador e ao monitor online."""
    def element_power(self, element_id: str) -> bool: ...
    def branch_power(self, parallel_id: str) -> bool: ...
    def operand_value(self, element_id: str) -> bool | None: ...
    def timer_state(self, index: int): ...
    def counter_state(self, index: int): ...
    def block_values(self, element_id: str) -> list[int | None] | None: ...
    @property
    def current_element(self) -> str | None: ...


def node_kind(node) -> str:
    if isinstance(node, Contact):
        return node.kind
    if isinstance(node, NotOp):
        return "NOT"
    if isinstance(node, Parallel):
        return "PAR"
    if isinstance(node, (Coil, TimerBox, CounterBox, CompareBox, MathBox)):
        return node.kind
    if isinstance(node, ResetBox):
        return "RES"
    return "?"


def has_address(node) -> bool:
    """Elementos com um unico operando (contato, bobina, temporizador, contador, RES)."""
    return hasattr(node, "operand") and not isinstance(node, (CompareBox, MathBox))


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
        elif isinstance(node, (CompareBox, MathBox)):
            st.label = st.sublabel = ""
            self.set_rows(None)
        tip = {"XIC": "Contato normalmente aberto (NA / XIC)", "XIO": "Contato normalmente fechado (NF / XIO)",
               "NOT": "Inversor (NOT)", "OTE": "Bobina", "OTL": "Bobina SET (OTL)", "OTU": "Bobina RESET (OTU)",
               "RES": "Reset de temporizador/contador", "PAR": "Ramificacao paralela (OR)"}.get(self.kind, self.kind)
        if isinstance(node, (CompareBox, MathBox)):
            roles = (COMPARE_KINDS if isinstance(node, CompareBox) else MATH_KINDS)[node.kind]
            tip = BLOCK_TIPS.get(node.kind, node.kind) + "\n" + "\n".join(
                f"{role}: {text}" for role, text in zip(roles, node.operands))
            self.setToolTip(tip)
            return
        self.setToolTip(f"{tip}\n{operand}" if operand else tip)

    def set_rows(self, values: list[int | None] | None) -> None:
        """Linhas do bloco: operando (simbolo ou endereco) e, na simulacao, o valor atual."""
        node, project = self.node, self.view.project
        roles = (COMPARE_KINDS if isinstance(node, CompareBox) else MATH_KINDS)[node.kind]
        rows = []
        for k, (role, text) in enumerate(zip(roles, node.operands)):
            short = {"Limite inferior": "Min", "Limite superior": "Max", "Destino": "\u2192", "Origem": "Orig",
                     "Mascara": "Masc", "Comparar": "Comp"}.get(role, role)
            shown = text.strip() or "?"
            name = project.symbol_for(shown) if project is not None else None
            if name:
                shown = name
            value = values[k] if values is not None and k < len(values) else None
            try:
                is_const = parse_constant(text) is not None
            except ValueError:
                is_const = False
            if value is not None and not is_const:
                shown = f"{shown}={value}"
            rows.append((short, shown))
        self.state.rows = tuple(rows)

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


class RungCard(QGraphicsRectItem):
    """Cartao de uma rede: fundo, faixa de titulo com numero e comentario."""

    def __init__(self, rect: QRectF, index: int, comment: str):
        super().__init__(rect)
        self.index = index
        self.comment = comment
        self.selected = False
        self.setData(0, index)
        self.setZValue(-5)
        if comment:
            self.setToolTip(comment)

    def paint(self, p: QPainter, option, widget=None) -> None:
        r = self.rect()
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setPen(QPen(SELECTED_BORDER if self.selected else CARD_BORDER, 2 if self.selected else 1))
        p.setBrush(CARD_FILL)
        p.drawRoundedRect(r, 8, 8)
        head_h = RUNG_HEAD * SY
        p.setPen(QPen(CARD_HEAD_LINE, 1))
        p.drawLine(QPointF(r.left() + 1, r.top() + head_h), QPointF(r.right() - 1, r.top() + head_h))
        p.setFont(ui_font(8, bold=True))
        text = f"Rede {self.index}"
        bw = p.fontMetrics().horizontalAdvance(text) + 16
        badge = QRectF(r.left() + 10, r.top() + 6, bw, head_h - 12)
        p.setPen(Qt.NoPen)
        p.setBrush(SELECTED_BORDER if self.selected else BADGE_FILL)
        p.drawRoundedRect(badge, badge.height() / 2, badge.height() / 2)
        p.setPen(QColor(255, 255, 255) if self.selected else BADGE_TEXT)
        p.drawText(badge, Qt.AlignCenter, text)
        if self.comment:
            p.setFont(ui_font(8, italic=True))
            p.setPen(COMMENT_TEXT)
            area = QRectF(badge.right() + 10, r.top(), r.right() - badge.right() - 20, head_h)
            p.drawText(area, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(self.comment, Qt.ElideRight, int(area.width())))


class LadderView(QGraphicsView):
    selectionChangedTo = Signal(object)          # id de elemento, ("rung", n) ou None
    editRequested = Signal(str)                  # id
    addressRequested = Signal(str, object)       # id, posicao global (duplo clique no endereco)
    dropRequested = Signal(str, str, object)     # "tool"|"move", payload, Slot
    actionRequested = Signal(str, object)        # acao, alvo

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.Antialiasing)
        self.setAcceptDrops(True)
        self.setDragMode(QGraphicsView.NoDrag)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setBackgroundBrush(CANVAS)
        self.project: Project | None = None
        self.layout_: Layout | None = None
        self.items_by_id: dict[str, ElementItem] = {}
        self.wire_items: list[tuple[QGraphicsLineItem, tuple | None]] = []
        self.rail_items: list[QGraphicsLineItem] = []
        self.rung_labels: list[tuple[RungCard, int]] = []
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
        self._press_item = None             # o item pressionado deixa de existir
        scene = self.scene()
        scene.clear()
        self.items_by_id.clear()
        self.wire_items.clear()
        self.rail_items.clear()
        self.rung_labels.clear()
        lay = self.layout_ = build_layout(project)
        left, right = -LABEL_W * SX, (lay.rail_right + LABEL_W) * SX
        for rb in lay.rungs:
            card = RungCard(QRectF(left, rb.y * SY, right - left, rb.h * SY), rb.index, rb.rung.comment)
            scene.addItem(card)
            self.rung_labels.append((card, rb.index))
            y1 = (rb.y + RUNG_HEAD) * SY + 2
            y2 = (rb.y + rb.h - RUNG_PAD) * SY - 2
            for x in (0.0, lay.rail_right * SX):
                line = scene.addLine(x, y1, x, y2, QPen(NEUTRAL, 4, Qt.SolidLine, Qt.RoundCap))
                line.setZValue(0.5)
                self.rail_items.append(line)
        # area para criar uma nova rede (alvo de arrastar e soltar)
        new_y = (lay.height - 1.0) * SY
        hint = scene.addRect(QRectF(left, new_y, right - left, 0.6 * SY),
                             QPen(HINT_BORDER, 1.2, Qt.DashLine), QColor(0, 0, 0, 0))
        hint.setZValue(-5)
        text = scene.addText("+  Solte uma instrucao aqui para criar uma nova rede", ui_font(8))
        text.setDefaultTextColor(COMMENT_TEXT)
        text.setPos(left + 12, new_y + 0.3 * SY - text.boundingRect().height() / 2)
        for w in lay.wires:
            item = scene.addLine(w.x1 * SX, w.y1 * SY, w.x2 * SX, w.y2 * SY, QPen(NEUTRAL, 2))
            item.setZValue(0)
            self.wire_items.append((item, w.key))
        for placed in lay.elems:
            item = ElementItem(placed, self)
            item.has_error = placed.node.id in self.error_ids
            scene.addItem(item)
            self.items_by_id[placed.node.id] = item
        self.highlight = scene.addRect(QRectF(), QPen(SELECTED_BORDER, 1.5), QColor(59, 130, 246, 60))
        self.highlight.setZValue(10)
        self.highlight.hide()
        scene.setSceneRect(QRectF(left - 16, -16, right - left + 32, new_y + 0.6 * SY + 32))
        self._apply_selection()

    def theme_changed(self) -> None:
        self.setBackgroundBrush(CANVAS)
        if self.project is not None:
            self.rebuild(self.project)

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
            if pw is None and source is not None:
                pw = False                       # fios de retorno ao trilho direito
            line.setPen(QPen(NEUTRAL if pw is None else (ENERGIZED if pw else DEENERGIZED), 3 if pw else 2,
                             Qt.SolidLine, Qt.RoundCap))
        for k, line in enumerate(self.rail_items):
            left_rail = k % 2 == 0               # rail_items alterna esquerdo/direito por rede
            hot = source is not None and rail and left_rail
            color = ENERGIZED if hot else (NEUTRAL if source is None else DEENERGIZED)
            line.setPen(QPen(color, 4, Qt.SolidLine, Qt.RoundCap))
        current = source.current_element if source is not None else None
        for eid, item in self.items_by_id.items():
            st = item.state
            st.power_in = power(item.placed.in_key)
            st.power_out = None if source is None else source.element_power(eid)
            st.closed = source.operand_value(eid) if source is not None and item.kind in ("XIC", "XIO") else None
            if st.closed is not None and item.kind == "XIO":
                st.closed = not st.closed
            node = item.node
            if isinstance(node, (CompareBox, MathBox)):
                item.set_rows(source.block_values(eid) if source is not None else None)
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
        for card, idx in self.rung_labels:
            card.selected = self.selection == ("rung", idx)
            card.update()

    def _item_at(self, pos) -> ElementItem | QGraphicsRectItem | None:
        found = [i for i in self.items(pos) if isinstance(i, ElementItem)]
        if found:
            found.sort(key=lambda i: i.zValue(), reverse=True)
            return found[0]
        for i in self.items(pos):
            if isinstance(i, RungCard):
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
            item = self._press_item
            self._press_item = None
            mime = QMimeData()
            mime.setData(MIME_MOVE, item.node.id.encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            if item.kind != "PAR":
                drag.setPixmap(self._drag_pixmap(item))
                drag.setHotSpot(QPointF(item.rect.width() * self.zoom / 2,
                                        item.rect.height() * self.zoom / 2).toPoint())
            drag.exec(Qt.MoveAction)
            if self.highlight is not None:
                self.highlight.hide()
            return
        super().mouseMoveEvent(event)

    def _drag_pixmap(self, item: ElementItem) -> QPixmap:
        size = item.rect.size() * self.zoom
        pix = QPixmap(max(1, int(size.width())), max(1, int(size.height())))
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setOpacity(0.75)
        p.scale(self.zoom, self.zoom)
        p.fillRect(QRectF(0, 0, item.rect.width(), item.rect.height()), SELECTED_FILL)
        paint_symbol(p, item.kind, QRectF(0, 0, item.rect.width(), item.rect.height()), item.state)
        p.end()
        return pix

    def mouseReleaseEvent(self, event) -> None:
        self._press_item = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        item = self._item_at(event.position().toPoint())
        if isinstance(item, ElementItem) and item.kind != "PAR":
            pos = self.mapToScene(event.position().toPoint())
            on_address = has_address(item.node) and pos.y() >= item.rect.top() + 0.62 * item.rect.height()
            if on_address:                       # clique no endereco (texto de baixo): troca rapida
                self.addressRequested.emit(item.node.id, self.mapToGlobal(event.position().toPoint()))
            else:
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
            if has_address(item.node):
                add("Alterar endereco...", "address", eid)
            if item.kind in WRAPPABLE:
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
        # A edicao e aplicada depois que o laco de arrastar do sistema termina:
        # reconstruir a cena (e abrir dialogos) dentro de dropEvent trava o
        # Windows, pois o item arrastado e destruido no meio do arrasto.
        info = self._drag_info(event)
        if info and info[1] == "RUNG":
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.actionRequested.emit("rung_append", None))
            return
        found = self._slot_for(event)
        if found:
            (mode, payload, _), slot = found
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.dropRequested.emit(mode, payload, slot))
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
