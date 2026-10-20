"""Janela principal da IDE."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QElapsedTimer, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QApplication, QDockWidget, QFileDialog, QHBoxLayout, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea,
                               QTableWidget, QToolButton,
                               QTableWidgetItem, QVBoxLayout, QWidget, QHeaderView)

from .. import __version__
from ..compiler import ImportError_, compile_project, import_image, import_lil
from ..compiler.compiler import COMPILER_VERSION, TARGET_FORMAT, CompileResult
from ..core.image import ImageValidationError
from ..core.asm import AsmError
from ..model import edit
from ..model.project import (CompareBox, Contact, CounterBox, MathBox, Project, ProjectFormatError, ResetBox,
                             Symbol, TimerBox, Coil)

EDITABLE_ON_INSERT = (Contact, Coil, TimerBox, CounterBox, ResetBox, CompareBox, MathBox)
from ..sim.simulator import SimState, Simulator
from ..comm.monitor import MonitorSource
from ..comm.protocol import DevState
from .device_panel import DevicePanel, DeviceSession
from .dialogs import ElementDialog, NewProjectDialog, ProjectDialog
from .env_panel import EnvironmentPanel
from .icons import make_icon
from .cpp_panel import CppPanel
from .esp32_panel import Esp32Panel
from .il_panel import ILPanel
from .verify_dialog import VerifyDialog
from . import theme
from .ladder_view import COND_TOOLS, OUTPUT_TOOLS, LadderView
from .palette import Palette
from .sim_panel import SimPanel

FILE_FILTER = "Projeto LADDER (*.ladproj)"
QWIDGETSIZE_MAX = (1 << 24) - 1     # limite de tamanho de widget do Qt (nao exportado pelo PySide6)


class MainWindow(QMainWindow):
    LAYOUT_VERSION = 4          # mude ao reorganizar os paineis: invalida layouts salvos antigos

    def __init__(self, project: Project | None = None, path: str | None = None, persist_layout: bool = False):
        super().__init__()
        self.persist_layout = persist_layout
        self.layout_locked = False
        self.project = project or Project()
        self.path: str | None = path
        self.dirty = False
        self.result: CompileResult | None = None
        self.sim: Simulator | None = None
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        screen = self.screen().availableGeometry() if self.screen() else None
        self.resize(min(1400, screen.width()) if screen else 1400, min(860, screen.height()) if screen else 860)

        self.view = LadderView()
        self.setCentralWidget(self.view)
        self._create_actions()
        self._create_docks()
        self._create_menus()
        self.view.dropRequested.connect(self.on_drop)
        self.view.actionRequested.connect(self.on_view_action)
        self.view.editRequested.connect(self.edit_element)
        self.view.selectionChangedTo.connect(lambda _: self._update_actions())

        self.status_mode = QLabel()
        self.status_mode.setObjectName("modeBadge")
        self.status_compile = QLabel()
        self.status_sim = QLabel()
        self.status_device = QLabel("ESP32: desconectado")
        self.statusBar().addWidget(self.status_mode)
        self.statusBar().addPermanentWidget(self.status_compile)
        self.statusBar().addPermanentWidget(self.status_sim)
        self.statusBar().addPermanentWidget(self.status_device)
        self.lock_button = QToolButton()        # cadeado: trava/destrava o layout
        self.lock_button.setDefaultAction(self.actions_["layout_lock"])
        self.lock_button.setAutoRaise(True)
        self.lock_button.setIconSize(QSize(16, 16))
        self.statusBar().addPermanentWidget(self.lock_button)
        self._was_editing = True
        self._palette_was_visible = True

        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.device_ticks = 0
        self.device_timer = QTimer(self)
        self.device_timer.setInterval(200)
        self.device_timer.timeout.connect(self.device_tick)
        self.device_timer.start()
        try:
            QGuiApplication.styleHints().colorSchemeChanged.connect(self.on_system_scheme_changed)
        except AttributeError:      # Qt < 6.5: sem deteccao do tema do sistema
            pass
        self._sync_device_status()
        self._default_layout = self.saveState(self.LAYOUT_VERSION)
        if persist_layout:
            self._restore_layout()
            self.sim_panel.speed.blockSignals(True)
            try:
                self.sim_panel.set_speed(float(self._settings().value("sim/speed", "1.0", type=str)))
            except ValueError:
                pass
            self.sim_panel.speed.blockSignals(False)
        self.set_layout_locked(persist_layout and self._settings().value("ui/layout_locked", False, type=bool),
                               save=False)
        self.refresh()

    # ================================================================ acoes
    def _act(self, key: str, text: str, slot, shortcut=None, tip: str = "") -> QAction:
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
        a.setStatusTip(tip or text)
        a.setToolTip(f"{text} ({QKeySequence(shortcut).toString()})" if shortcut else text)
        a.triggered.connect(slot)
        self.actions_[key] = a
        return a

    def _create_actions(self) -> None:
        self.actions_: dict[str, QAction] = {}
        A = self._act
        A("new", "Novo", self.file_new, QKeySequence.New)
        A("open", "Abrir...", self.file_open, QKeySequence.Open)
        A("save", "Salvar", self.file_save, QKeySequence.Save)
        A("save_as", "Salvar como...", self.file_save_as, QKeySequence.SaveAs)
        A("export_lil", "Exportar listagem LIL...", self.export_lil)
        A("export_bin", "Exportar binario LDRB...", self.export_bin)
        A("import", "Importar LIL/LDRB...", self.import_program)
        A("quit", "Sair", self.close, QKeySequence.Quit)
        A("undo", "Desfazer", self.undo, QKeySequence.Undo)
        A("redo", "Refazer", self.redo, QKeySequence.Redo)
        A("delete", "Excluir", self.delete_selected, QKeySequence.Delete)
        A("edit", "Editar elemento...", lambda: self.edit_element(self.view.selection), "Return")
        A("rung_add", "Nova rede", lambda: self.on_view_action("rung_append", None), "Ctrl+R")
        A("project", "Propriedades do projeto...", self.project_properties)
        A("compile", "Compilar", self.compile, "F7", "Valida e gera o programa intermediario")
        A("sim_run", "Executar", self.sim_run, "F5", "Executa a simulacao continuamente")
        A("sim_pause", "Pausar", self.sim_pause, "F6")
        A("sim_scan", "Varredura", self.sim_scan, "F10", "Executa uma varredura completa")
        A("sim_step", "Passo", self.sim_step, "F11", "Executa uma instrucao")
        A("sim_reset", "Reiniciar", self.sim_reset, "Ctrl+F5", "Partida a frio da simulacao")
        A("sim_stop", "Parar", self.sim_stop, "Shift+F5", "Encerra a simulacao e volta a edicao")
        A("sim_faster", "Acelerar", lambda: self.sim_panel.change_speed(1), "Ctrl+.",
          "Aumenta a velocidade do tempo simulado")
        A("sim_slower", "Desacelerar", lambda: self.sim_panel.change_speed(-1), "Ctrl+,",
          "Diminui a velocidade do tempo simulado")
        A("sim_realtime", "Tempo real (1x)", lambda: self.sim_panel.set_speed(1.0), "Ctrl+;",
          "Volta a simulacao para o tempo real")
        A("zoom_in", "Aproximar", lambda: self.view.set_zoom(self.view.zoom * 1.2), QKeySequence.ZoomIn)
        A("zoom_out", "Afastar", lambda: self.view.set_zoom(self.view.zoom / 1.2), QKeySequence.ZoomOut)
        A("zoom_reset", "Zoom 100%", lambda: self.view.set_zoom(1.0), "Ctrl+0")
        A("device_transfer", "Transferir programa ao dispositivo", lambda: self.device_transfer(), "F8")
        A("verify", "Verificar para ESP32", self.verify_esp32, "F9",
          "Valida o programa no codigo C do firmware, compara com o simulador e confere os limites da placa")
        A("cpp_code", "Codigo C++", self.show_cpp, "Ctrl+F7",
          "Mostra o diagrama traduzido para C++; atualiza a cada edicao, antes de compilar")
        A("il_blocks", "Blocos de instrucao", self.show_il_blocks, "F12",
          "Mostra o diagrama convertido em lista de instrucoes, bloco por rede")
        A("esp32_sim", "Simulador da placa ESP32", self.show_esp32, "Ctrl+Shift+E",
          "Placa de 8 reles com o firmware rodando no PC: pinos, registradores e configuracao")
        A("flash_firmware", "Gravar firmware na placa...", self.flash_firmware, None,
          "Grava o firmware do CLP no ESP32 pela USB (necessario uma vez, antes de transferir programas)")
        A("environment", "Ambiente de simulacao", self.show_environment, "Ctrl+E",
          "Processos animados (silo, semaforo, portao...) controlados pelo programa")
        A("theme_toggle", "Alternar tema claro/escuro", self.toggle_theme, "Ctrl+Shift+T")
        A("dev_run", "RUN (executar no ESP32)", lambda: self.device_panel.run_btn.click(), None,
          "Coloca o dispositivo em RUN")
        A("dev_stop", "STOP (parar o ESP32)", lambda: self.device_panel.stop_btn.click(), None,
          "Coloca o dispositivo em STOP (saidas no estado seguro)")
        A("dev_monitor", "Monitor online", lambda on: self.device_panel.monitor.setChecked(on), None,
          "Anima o diagrama com o estado lido do dispositivo")
        self.actions_["dev_monitor"].setCheckable(True)
        A("layout_reset", "Restaurar layout padrao", self.reset_layout, None,
          "Volta os paineis para a posicao original")
        A("layout_lock", "Travar layout", lambda on: self.set_layout_locked(on), "Ctrl+Alt+L",
          "Impede mover, fechar ou redimensionar paineis e barras")
        self.actions_["layout_lock"].setCheckable(True)
        A("about", "Sobre", self.about)
        A("help", "Referencia das instrucoes", self.instruction_help, "F1")
        for key, icon in (("new", "new"), ("open", "open"), ("save", "save"), ("undo", "undo"), ("redo", "redo"),
                          ("delete", "delete"), ("rung_add", "rung"), ("compile", "compile"), ("sim_run", "run"),
                          ("sim_pause", "pause"), ("sim_scan", "scan"), ("sim_step", "step"),
                          ("sim_reset", "reset"), ("sim_stop", "stop"), ("zoom_in", "zoom_in"),
                          ("zoom_out", "zoom_out"), ("device_transfer", "transfer"), ("verify", "verify"),
                          ("il_blocks", "il"), ("cpp_code", "cpp"), ("esp32_sim", "board"), ("environment", "env"),
                          ("theme_toggle", "theme")):
            self.actions_[key].setIcon(make_icon(icon))
        self._icon_names = {"new": "new", "open": "open", "save": "save", "undo": "undo", "redo": "redo",
                            "delete": "delete", "rung_add": "rung", "compile": "compile", "sim_run": "run",
                            "sim_pause": "pause", "sim_scan": "scan", "sim_step": "step", "sim_reset": "reset",
                            "sim_stop": "stop", "zoom_in": "zoom_in", "zoom_out": "zoom_out",
                            "device_transfer": "transfer", "verify": "verify", "il_blocks": "il", "cpp_code": "cpp", "esp32_sim": "board",
                            "environment": "env", "theme_toggle": "theme"}
        self.actions_["device_transfer"].setIconText("Transferir")
        self.actions_["verify"].setIconText("Verificar ESP32")
        self.actions_["il_blocks"].setIconText("Blocos IL")
        self.actions_["cpp_code"].setIconText("C++")
        self.actions_["esp32_sim"].setIconText("Placa ESP32")
        self.actions_["environment"].setIconText("Ambiente")
        self.actions_["open"].setIconText("Abrir")

    def _create_menus(self) -> None:
        a = self.actions_
        mb = self.menuBar()
        m = mb.addMenu("&Arquivo")
        for k in ("new", "open", "save", "save_as"):
            m.addAction(a[k])
        m.addSeparator()
        for k in ("import", "export_lil", "export_bin"):
            m.addAction(a[k])
        m.addSeparator()
        m.addAction(a["quit"])
        m = mb.addMenu("&Editar")
        for k in ("undo", "redo", "delete", "edit", "rung_add"):
            m.addAction(a[k])
        m.addSeparator()
        m.addAction(a["project"])
        m = mb.addMenu("&Programa")
        m.addAction(a["cpp_code"])
        m.addAction(a["compile"])
        m.addAction(a["il_blocks"])
        m = mb.addMenu("&Simulacao")
        for k in ("sim_run", "sim_pause", "sim_scan", "sim_step", "sim_reset", "sim_stop"):
            m.addAction(a[k])
        m.addSeparator()
        for k in ("sim_faster", "sim_slower", "sim_realtime"):
            m.addAction(a[k])
        m.addSeparator()
        m.addAction(a["environment"])
        self.device_menu = mb.addMenu("&Dispositivo")
        for k in ("esp32_sim", None, "verify", "device_transfer", None, "dev_run", "dev_stop", "dev_monitor", None,
                  "flash_firmware"):
            self.device_menu.addSeparator() if k is None else self.device_menu.addAction(a[k])
        self.device_menu.addSeparator()
        self.device_menu.addAction(self.device_dock.toggleViewAction())
        m = mb.addMenu("E&xibir")
        for k in ("zoom_in", "zoom_out", "zoom_reset"):
            m.addAction(a[k])
        m.addSeparator()
        self.theme_menu = m.addMenu("Tema")
        self.theme_actions = {}
        group = QActionGroup(self)
        for mode, label in theme.MODES.items():
            act = QAction(label, self, checkable=True)
            act.setChecked(mode == theme.current_mode)
            act.triggered.connect(lambda _=False, md=mode: self.set_theme(md))
            group.addAction(act)
            self.theme_menu.addAction(act)
            self.theme_actions[mode] = act
        self.theme_menu.addSeparator()
        self.theme_menu.addAction(a["theme_toggle"])
        m.addSeparator()
        panels = m.addMenu("Paineis")
        for dock in (self.palette_dock, self.sim_dock, self.device_dock, self.il_dock, self.cpp_dock,
                     self.env_dock, self.esp32_dock, self.msgs_dock, self.symbols_dock):
            panels.addAction(dock.toggleViewAction())
        m.addAction(a["layout_lock"])
        m.addAction(a["layout_reset"])
        m = mb.addMenu("Aj&uda")
        m.addAction(a["help"])
        m.addAction(a["about"])

        # Tres barras na ordem do fluxo de trabalho: editar -> compilar/simular -> dispositivo.
        # Texto so nas acoes principais; as demais mostram icone e dica com o atalho.
        groups = {
            "Edicao": ("new", "open", "save", None, "undo", "redo", None, "rung_add", None, "zoom_in", "zoom_out"),
            "Simulacao": ("cpp_code", "compile", None, "sim_run", "sim_pause", "sim_scan", "sim_step", "sim_reset", "sim_stop",
                          None, "environment"),
            "Dispositivo": ("esp32_sim", "verify", "device_transfer", None, "il_blocks"),
        }
        with_text = {"cpp_code", "compile", "sim_run", "sim_stop", "environment", "device_transfer"}
        self.toolbars = []
        for title, keys in groups.items():
            tb = self.addToolBar(title)
            tb.setObjectName(f"toolbar_{title.lower()}")
            tb.setMovable(True)                 # travado/destravado por set_layout_locked
            tb.setIconSize(QSize(20, 20))
            for k in keys:
                if k is None:
                    tb.addSeparator()
                    continue
                tb.addAction(a[k])
                tb.widgetForAction(a[k]).setToolButtonStyle(
                    Qt.ToolButtonTextBesideIcon if k in with_text else Qt.ToolButtonIconOnly)
            self.toolbars.append(tb)
        self.toolbar = self.toolbars[0]

    def _create_docks(self) -> None:
        # colunas laterais com altura total; o painel de baixo fica so sob o diagrama
        self.setCorner(Qt.BottomLeftCorner, Qt.LeftDockWidgetArea)
        self.setCorner(Qt.BottomRightCorner, Qt.RightDockWidgetArea)
        self.palette = Palette()
        self.palette.toolClicked.connect(self.tool_clicked)
        self.palette_dock = self._dock("Instrucoes", self.palette, Qt.LeftDockWidgetArea, "dock_palette")

        self.sim_panel = SimPanel(self.actions_)
        self.sim_panel.io.inputChanged.connect(self.on_input)
        self.sim_panel.speed.currentIndexChanged.connect(self.on_speed_changed)
        self.sim_dock = self._dock("Simulador", self.sim_panel, Qt.RightDockWidgetArea, "dock_sim", scroll=True)

        self.messages = QListWidget()
        self.messages.setAlternatingRowColors(True)
        self.messages.itemActivated.connect(self.on_message)
        self.messages.itemClicked.connect(self.on_message)
        self.symbols = QTableWidget(0, 3)
        self.symbols.setHorizontalHeaderLabels(["Nome", "Endereco", "Comentario"])
        self.symbols.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.symbols.cellChanged.connect(self.on_symbol_changed)
        sym_box = QWidget()
        lay = QVBoxLayout(sym_box)
        lay.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        add_b, del_b = QPushButton("Adicionar variavel"), QPushButton("Remover selecionada")
        add_b.clicked.connect(self.symbol_add)
        del_b.clicked.connect(self.symbol_remove)
        self.symbol_buttons = (add_b, del_b)
        row.addWidget(add_b)
        row.addWidget(del_b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(self.symbols)
        self.msgs_dock = self._dock("Mensagens", self.messages, Qt.BottomDockWidgetArea, "dock_msgs")
        self.symbols_dock = self._dock("Simbolos", sym_box, Qt.BottomDockWidgetArea, "dock_symbols")
        self.tabifyDockWidget(self.msgs_dock, self.symbols_dock)

        self.session = DeviceSession(self)
        self.device_panel = DevicePanel(self.session)
        self.device_dock = self._dock("Dispositivo", self.device_panel, Qt.RightDockWidgetArea, "dock_device",
                                      scroll=True)
        self.tabifyDockWidget(self.sim_dock, self.device_dock)

        self.il_panel = ILPanel()
        self.il_panel.elementActivated.connect(self.view.select)
        self.il_dock = self._dock("Blocos de instrucao", self.il_panel, Qt.RightDockWidgetArea, "dock_il")
        self.tabifyDockWidget(self.device_dock, self.il_dock)

        self.cpp_panel = CppPanel()
        self.cpp_panel.elementActivated.connect(self.view.select)
        self.cpp_dock = self._dock("Codigo C++", self.cpp_panel, Qt.RightDockWidgetArea, "dock_cpp")
        self.tabifyDockWidget(self.il_dock, self.cpp_dock)

        # o ambiente fica sob o diagrama: cena larga e Simulador visivel ao mesmo tempo
        self.env_panel = EnvironmentPanel()
        self.env_panel.environmentChanged.connect(self.on_environment_changed)
        self.env_panel.symbolsRequested.connect(self.add_environment_symbols)
        self.env_panel.exampleRequested.connect(self.open_example)
        self.env_dock = self._dock("Ambiente", self.env_panel, Qt.BottomDockWidgetArea, "dock_env")
        self.tabifyDockWidget(self.symbols_dock, self.env_dock)
        # placa ESP32 (firmware no PC): larga, fica sob o diagrama ao lado do ambiente
        self.esp32_panel = Esp32Panel(self.session, self.device_panel, lambda: self.device_transfer())
        self.esp32_dock = self._dock("Placa ESP32", self.esp32_panel, Qt.BottomDockWidgetArea, "dock_esp32")
        self.tabifyDockWidget(self.env_dock, self.esp32_dock)
        self.msgs_dock.raise_()
        self.il_dock.visibilityChanged.connect(lambda visible: visible and self._refresh_il())
        self.view.selectionChangedTo.connect(self.il_panel.highlight)
        self.cpp_dock.visibilityChanged.connect(lambda visible: visible and self._refresh_cpp())
        self.view.selectionChangedTo.connect(self.cpp_panel.highlight)
        self.sim_dock.raise_()
        self.device_panel.transferRequested.connect(self.device_transfer)
        self.device_panel.monitorToggled.connect(self.on_monitor_toggled)
        self.session.snapshot.connect(self.on_snapshot)
        self.session.jobDone.connect(self.on_job_done)
        self.session.jobFailed.connect(self.on_job_failed)
        self.session.disconnected.connect(lambda _: self._update_live())
        self.session.progress.connect(self.on_transfer_progress)
        self.monitoring = False
        self.last_snapshot = None
        self.progress_dialog = None
        self._sized = False
        self._apply_default_sizes()

    def _apply_default_sizes(self) -> None:
        """Larguras/alturas padrao dos paineis (proporcionais a janela)."""
        self.resizeDocks([self.palette_dock, self.sim_dock], [200, max(400, int(0.30 * self.width()))],
                         Qt.Horizontal)
        self.resizeDocks([self.msgs_dock], [max(120, int(0.20 * self.height()))], Qt.Vertical)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized:                 # tamanhos so valem depois que a janela tem geometria real
            self._sized = True
            if not (self.persist_layout and self._settings().value("ui/state") is not None):
                QTimer.singleShot(0, self._initial_sizes)
            QTimer.singleShot(0, lambda: self._freeze_sizes(self.layout_locked))

    def _initial_sizes(self) -> None:
        self._apply_default_sizes()
        self._default_layout = self.saveState(self.LAYOUT_VERSION)

    def _dock(self, title: str, widget, area, name: str, scroll: bool = False) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)            # nome estavel: usado para salvar o layout
        dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                         | QDockWidget.DockWidgetClosable)
        if scroll:                          # paineis longos rolam em vez de exigir altura da janela
            area_w = QScrollArea()
            area_w.setWidget(widget)
            area_w.setWidgetResizable(True)
            area_w.setFrameShape(QScrollArea.NoFrame)
            area_w.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            dock.setWidget(area_w)
        else:
            dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    # ================================================================ layout
    def _settings(self) -> QSettings:
        return QSettings("CLP-ESP32", "LadderIDE")

    def _restore_layout(self) -> None:
        s = self._settings()
        geometry, state = s.value("ui/geometry"), s.value("ui/state")
        if geometry is not None:
            self.restoreGeometry(geometry)
        if state is not None:
            self.restoreState(state, self.LAYOUT_VERSION)

    def _save_layout(self) -> None:
        s = self._settings()
        s.setValue("ui/geometry", self.saveGeometry())
        s.setValue("ui/state", self.saveState(self.LAYOUT_VERSION))

    DOCK_FEATURES = (QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable
                     | QDockWidget.DockWidgetClosable)

    def _docks(self) -> tuple[QDockWidget, ...]:
        return (self.palette_dock, self.sim_dock, self.device_dock, self.il_dock, self.cpp_dock,
                self.env_dock, self.esp32_dock, self.msgs_dock, self.symbols_dock)

    def set_layout_locked(self, locked: bool, save: bool = True) -> None:
        """Layout travado: paineis e barras nao podem ser movidos, desacoplados, fechados
        nem redimensionados (as divisorias param de responder)."""
        self.layout_locked = bool(locked)
        for dock in self._docks():
            dock.setFeatures(QDockWidget.NoDockWidgetFeatures if locked else self.DOCK_FEATURES)
        for tb in self.toolbars:
            tb.setMovable(not locked)
        for dock in self._docks():
            dock.toggleViewAction().setEnabled(not locked)
        self.actions_["layout_reset"].setEnabled(not locked)
        act = self.actions_["layout_lock"]
        act.blockSignals(True)
        act.setChecked(self.layout_locked)
        act.blockSignals(False)
        self._update_lock_icon()
        if self.isVisible():                # antes de exibir, showEvent aplica com os tamanhos reais
            self._freeze_sizes(self.layout_locked)
        if save and self.persist_layout:
            self._settings().setValue("ui/layout_locked", self.layout_locked)
            self._save_layout()
        if save:
            self.statusBar().showMessage("Layout travado: paineis fixos. Destrave pelo cadeado ou Ctrl+Alt+L."
                                         if locked else "Layout destravado: arraste paineis e divisorias.",
                                         4000)

    def _update_lock_icon(self) -> None:
        act = self.actions_["layout_lock"]
        act.setIcon(make_icon("lock" if self.layout_locked else "unlock"))
        act.setToolTip("Layout travado - clique para destravar (Ctrl+Alt+L)" if self.layout_locked
                       else "Layout livre - clique para travar (Ctrl+Alt+L)")

    def _freeze_sizes(self, frozen: bool) -> None:
        """Travado: cada painel fica com o tamanho atual (minimo = maximo), entao as
        divisorias nao conseguem redimensiona-lo; a area do diagrama absorve mudancas
        no tamanho da janela."""
        for dock in self._docks():
            if frozen and dock.isVisible() and not dock.isFloating():
                area = self.dockWidgetArea(dock)
                if area in (Qt.LeftDockWidgetArea, Qt.RightDockWidgetArea):
                    dock.setFixedWidth(dock.width())
                else:
                    dock.setFixedHeight(dock.height())
            else:
                dock.setMinimumSize(0, 0)
                dock.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)

    def reset_layout(self) -> None:
        if self.layout_locked:
            return
        for dock in self._docks():
            dock.setFloating(False)
            dock.show()
        self.restoreState(self._default_layout, self.LAYOUT_VERSION)
        self._apply_default_sizes()
        self._palette_was_visible = True
        self._was_editing = not (self.sim is not None and self.sim.active)
        self.palette_dock.setVisible(self._was_editing and not self.monitoring)
        self.sim_dock.raise_()
        self.msgs_dock.raise_()

    # ============================================================ estado geral
    def refresh(self) -> None:
        self.view.rebuild(self.project)
        self.view.set_errors({d.element_id for d in (self.result.errors if self.result else []) if d.element_id})
        self._fill_symbols()
        self.sim_panel.io.configure(self.project, self.sim.result if self.sim else self.result)
        self.device_panel.io.configure(self.project, self.result)
        self._device_io_build = self.result.build_id if self.result and self.result.ok else None
        self.device_panel.expected_build_id = self._device_io_build
        self._update_live()
        self._update_title()
        self._update_actions()
        self._refresh_il()
        self._refresh_cpp()
        self.esp32_panel.set_project(self.project)

    def _update_title(self) -> None:
        name = Path(self.path).name if self.path else "sem arquivo"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{self.project.name} [{name}] - LadderIDE {__version__}")

    def _update_actions(self) -> None:
        a = self.actions_
        sim_active = self.sim is not None and self.sim.active
        editing = not sim_active
        for k in ("undo", "redo", "delete", "edit", "rung_add", "project", "import", "new", "open"):
            a[k].setEnabled(editing)
        a["undo"].setEnabled(editing and bool(self.undo_stack))
        a["redo"].setEnabled(editing and bool(self.redo_stack))
        running = self.sim is not None and self.sim.state == SimState.RUNNING
        a["sim_run"].setEnabled(not running)
        a["sim_pause"].setEnabled(running)
        a["sim_stop"].setEnabled(sim_active)
        a["sim_reset"].setEnabled(sim_active)
        self.view.readonly = sim_active
        self._apply_work_mode(editing and not getattr(self, "monitoring", False))
        self.palette.set_enabled(editing)
        self.symbols.setEnabled(editing)
        for b in self.symbol_buttons:
            b.setEnabled(editing)
        if self.sim is not None:
            self.status_sim.setText(f"Simulacao: {self.sim.state.value}")
        else:
            self.status_sim.setText("")
        if self.result is None:
            self.status_compile.setText("Nao compilado")
        elif self.result.ok:
            self.status_compile.setText(f"Compilado: {len(self.result.program.code)} instrucoes, "
                                        f"{len(self.result.image)} bytes, id 0x{self.result.build_id:08x}")
        else:
            self.status_compile.setText(f"{len(self.result.errors)} erro(s) de compilacao")

    MODE_STYLE = {"EDICAO": ("#e2e8f0", "#334155"), "SIMULACAO": ("#16a34a", "#ffffff"),
                  "ONLINE": ("#ea580c", "#ffffff")}

    def _apply_work_mode(self, editing: bool) -> None:
        """Paleta so aparece na edicao; selo de modo na barra de status."""
        if editing != self._was_editing:
            if editing:
                self.palette_dock.setVisible(self._palette_was_visible)
            else:
                self._palette_was_visible = self.palette_dock.isVisible()
                self.palette_dock.hide()
            self._was_editing = editing
        if getattr(self, "monitoring", False) and self.device_panel.connected:
            mode = "ONLINE"
        elif self.sim is not None and self.sim.active:
            mode = "SIMULACAO"
        else:
            mode = "EDICAO"
        bg, fg = self.MODE_STYLE[mode]
        self.status_mode.setText({"EDICAO": "EDICAO", "SIMULACAO": "SIMULACAO", "ONLINE": "ONLINE (ESP32)"}[mode])
        self.status_mode.setStyleSheet(f"background:{bg}; color:{fg}; border-radius:8px; padding:1px 10px; "
                                       "font-weight:600;")

    def _sync_device_status(self) -> None:
        panel = self.device_panel
        a = self.actions_
        a["dev_run"].setEnabled(panel.run_btn.isEnabled())
        a["dev_stop"].setEnabled(panel.stop_btn.isEnabled())
        a["dev_monitor"].setEnabled(panel.connected)
        if a["dev_monitor"].isChecked() != panel.monitor.isChecked():
            a["dev_monitor"].setChecked(panel.monitor.isChecked())
        if not panel.connected:
            text = "ESP32: reconectando..." if self.session.auto_reconnect else "ESP32: desconectado"
        else:
            where = "virtual" if self.session.is_virtual else (panel.port.currentText() or "serial")
            state = panel.last_status.state.name if panel.last_status else "..."
            text = f"ESP32: {where} - {state}"
        self.status_device.setText(text)

    def _monitor_source(self) -> MonitorSource | None:
        snap, r = self.last_snapshot, self.result
        if (self.monitoring and self.device_panel.connected and snap is not None and r is not None and r.ok
                and snap.build_id == r.build_id):
            return MonitorSource(snap, r)
        return None

    def _update_live(self) -> None:
        if self.sim is not None and self.sim.active:
            self.view.update_live(self.sim)
        elif (src := self._monitor_source()) is not None:
            self.view.update_live(src, rail=src.s.state == DevState.RUN)
        else:
            self.view.update_live(None)
        self.sim_panel.refresh(self.sim)
        sim_on = self.sim is not None and self.sim.active
        self.env_panel.refresh(self.sim.physical_outputs if sim_on else 0)
        if self.il_dock.isVisible():
            vm = self.sim.vm if sim_on else None
            self.il_panel.update_live(vm.power if vm else None, vm.pc if vm and vm.in_scan else None)

    def modified(self) -> None:
        self.dirty = True
        self.result = None
        self.sim = None
        self.refresh()

    def _can_edit(self) -> bool:
        if self.sim is not None and self.sim.active:
            self.statusBar().showMessage("Pare a simulacao (Shift+F5) para editar o programa.", 4000)
            return False
        return True

    # ================================================================ edicao
    def push_undo(self) -> None:
        self.undo_stack.append(self.project.to_dict())
        del self.undo_stack[:-100]
        self.redo_stack.clear()

    def _restore(self, data: dict) -> None:
        self.project = Project.from_dict(data)
        self.view.selection = None
        self.modified()

    def undo(self) -> None:
        if self.undo_stack and self._can_edit():
            self.redo_stack.append(self.project.to_dict())
            self._restore(self.undo_stack.pop())

    def redo(self) -> None:
        if self.redo_stack and self._can_edit():
            self.undo_stack.append(self.project.to_dict())
            self._restore(self.redo_stack.pop())

    def apply_edit(self, fn) -> bool:
        if not self._can_edit():
            return False
        self.push_undo()
        try:
            fn()
        except edit.EditError as exc:
            # Desfaz qualquer alteracao parcial restaurando o instantaneo anterior.
            self._restore(self.undo_stack.pop())
            self.statusBar().showMessage(str(exc), 5000)
            return False
        self.modified()
        return True

    def _new_node(self, tool: str):
        node = edit.cond_node_for_tool(tool) or edit.output_node_for_tool(tool)
        if isinstance(node, TimerBox):
            node.operand = edit.next_free_element(self.project, "T")
        elif isinstance(node, CounterBox):
            node.operand = edit.next_free_element(self.project, "C")
        elif isinstance(node, ResetBox):
            drivers = [n.operand for _, n, _ in self.project.walk() if isinstance(n, (TimerBox, CounterBox))]
            node.operand = drivers[0] if drivers else "T0"
        return node

    def _insert_new(self, tool: str, container: list, index: int) -> None:
        node = self._new_node(tool)
        if node is None:
            return
        if not self.apply_edit(lambda: edit.insert(self.project, container, index, node)):
            return
        self.view.select(node.id)
        if isinstance(node, EDITABLE_ON_INSERT):
            self.edit_element(node.id, record_undo=False)

    def tool_clicked(self, tool: str) -> None:
        if not self._can_edit():
            return
        if tool == "RUNG":
            self.on_view_action("rung_append", None)
            return
        if not self.project.rungs and not self.apply_edit(lambda: edit.add_rung(self.project)):
            return
        sel = self.view.selection
        rung_index = len(self.project.rungs) - 1
        hit = self.project.find(sel) if isinstance(sel, str) else None
        if isinstance(sel, tuple):
            rung_index = sel[1]
        elif hit:
            rung_index = hit[0]
        rung = self.project.rungs[rung_index]
        if tool in OUTPUT_TOOLS:
            if hit and hit[2] is rung.outputs:
                self._insert_new(tool, rung.outputs, hit[2].index(hit[1]) + 1)
            else:
                self._insert_new(tool, rung.outputs, len(rung.outputs))
        else:
            if hit and hit[2] is not rung.outputs:
                self._insert_new(tool, hit[2], hit[2].index(hit[1]) + 1)
            else:
                self._insert_new(tool, rung.condition, len(rung.condition))

    def on_drop(self, mode: str, payload: str, slot) -> None:
        if not self._can_edit():
            return
        if slot.kind == "newrung":
            is_out = payload in OUTPUT_TOOLS or (mode == "move" and self._is_output(payload))
            node = self._new_node(payload) if mode == "tool" else None

            def into_new_rung():
                rung = edit.add_rung(self.project)
                target = rung.outputs if is_out else rung.condition
                if node is not None:
                    edit.insert(self.project, target, 0, node)
                else:
                    edit.move(self.project, payload, target, 0)
            if self.apply_edit(into_new_rung):
                self.view.select(node.id if node is not None else payload)
                if isinstance(node, EDITABLE_ON_INSERT):
                    self.edit_element(node.id, record_undo=False)
            return
        if mode == "tool":
            self._insert_new(payload, slot.container, slot.index)
        else:
            if self.apply_edit(lambda: edit.move(self.project, payload, slot.container, slot.index)):
                self.view.select(payload)

    def _is_output(self, element_id: str) -> bool:
        hit = self.project.find(element_id)
        return bool(hit) and isinstance(hit[1], edit.OUTPUT_TYPES)

    def on_view_action(self, action: str, target) -> None:
        if not self._can_edit():
            return
        p = self.project
        if action == "edit":
            self.edit_element(target)
        elif action == "delete":
            self.apply_edit(lambda: edit.remove(p, target))
        elif action == "wrap":
            self.apply_edit(lambda: edit.wrap_in_parallel(p, target))
        elif action == "add_branch":
            self.apply_edit(lambda: edit.add_branch(p, target))
        elif action == "remove_branch":
            self.apply_edit(lambda: edit.remove_branch(p, target))
        elif action == "rung_above":
            self.apply_edit(lambda: edit.add_rung(p, target))
        elif action == "rung_below":
            self.apply_edit(lambda: edit.add_rung(p, target + 1))
        elif action == "rung_append":
            if self.apply_edit(lambda: edit.add_rung(p)):
                self.view.select(("rung", len(p.rungs) - 1))
        elif action == "rung_delete":
            self.apply_edit(lambda: edit.remove_rung(p, target))
        elif action == "rung_comment":
            text, ok = QInputDialog.getText(self, "Comentario da rede", f"Rede {target}:",
                                            text=p.rungs[target].comment)
            if ok:
                self.apply_edit(lambda: setattr(p.rungs[target], "comment", text))

    def delete_selected(self) -> None:
        sel = self.view.selection
        if isinstance(sel, str):
            self.on_view_action("delete", sel)
        elif isinstance(sel, tuple):
            self.on_view_action("rung_delete", sel[1])

    def edit_element(self, element_id, record_undo: bool = True) -> None:
        if not isinstance(element_id, str) or not self._can_edit():
            return
        hit = self.project.find(element_id)
        if hit is None or isinstance(hit[1], (edit.Parallel, edit.NotOp)):
            return
        dlg = ElementDialog(hit[1], self.project, self)
        if dlg.exec():
            if record_undo:
                self.push_undo()
            dlg.apply()
            self.modified()
            self.view.select(element_id)

    def project_properties(self) -> None:
        if not self._can_edit():
            return
        dlg = ProjectDialog(self.project, self)
        if dlg.exec():
            self.push_undo()
            dlg.apply()
            self.modified()

    # --------------------------------------------------------------- simbolos
    def _fill_symbols(self) -> None:
        self.symbols.blockSignals(True)
        self.symbols.setRowCount(len(self.project.symbols))
        for row, s in enumerate(self.project.symbols):
            for col, value in enumerate((s.name, s.address, s.comment)):
                self.symbols.setItem(row, col, QTableWidgetItem(value))
        self.symbols.blockSignals(False)

    def on_symbol_changed(self, row: int, col: int) -> None:
        if row >= len(self.project.symbols):
            return
        self.push_undo()
        s = self.project.symbols[row]
        value = self.symbols.item(row, col).text().strip()
        if col == 0:
            s.name = value
        elif col == 1:
            s.address = value.upper()
        else:
            s.comment = value
        self.modified()

    def symbol_add(self) -> None:
        used = {s.name for s in self.project.symbols}
        k = 1
        while f"Var{k}" in used:
            k += 1
        self.apply_edit(lambda: self.project.symbols.append(Symbol(f"Var{k}", "M0.0")))
        self.symbols_dock.show()
        self.symbols_dock.raise_()

    def symbol_remove(self) -> None:
        row = self.symbols.currentRow()
        if 0 <= row < len(self.project.symbols):
            self.apply_edit(lambda: self.project.symbols.pop(row))

    # ============================================================ compilacao
    def compile(self) -> bool:
        self.result = compile_project(self.project)
        self.messages.clear()
        for d in self.result.diagnostics:
            item = QListWidgetItem(str(d))
            item.setData(Qt.UserRole, (d.element_id, d.rung))
            item.setForeground(Qt.red if d.severity == "erro" else Qt.darkYellow)
            self.messages.addItem(item)
        if self.result.ok:
            self.messages.addItem(QListWidgetItem(
                f"Compilacao concluida: {len(self.result.program.code)} instrucoes, {len(self.result.image)} bytes, "
                f"{len(self.result.warnings)} aviso(s). Compilador {COMPILER_VERSION}, formato "
                f"{TARGET_FORMAT}, id 0x{self.result.build_id:08x}."))
        if self.result.diagnostics:          # nao esconde o Ambiente quando compila sem avisos
            self.msgs_dock.show()
            self.msgs_dock.raise_()
        self.view.set_errors({d.element_id for d in self.result.errors if d.element_id})
        self.device_panel.expected_build_id = self.result.build_id if self.result.ok else None
        if self.result.ok and self._device_io_build != self.result.build_id:
            # tabelas de temporizadores/contadores do painel dependem do programa compilado
            self.device_panel.io.configure(self.project, self.result)
            self._device_io_build = self.result.build_id
        self._update_actions()
        return self.result.ok

    def on_message(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.UserRole)
        if not data:
            return
        element_id, rung = data
        if element_id and element_id in self.view.items_by_id:
            self.view.select(element_id)
        elif rung is not None:
            self.view.select(("rung", rung))

    # ============================================================== simulacao
    def _ensure_sim(self) -> Simulator | None:
        if self.sim is not None:
            return self.sim
        if not self.compile():
            QMessageBox.warning(self, "Simulacao", "Corrija os erros de compilacao antes de simular.\n"
                                                   "Veja a aba Mensagens.")
            return None
        self.sim = Simulator(self.result, self.project.io.scan_period_ms)
        self.sim.attach_plant(self.env_panel.plant)
        self.sim_panel.io.configure(self.project, self.result)
        self.sim_panel.io.set_owned(self.env_panel.owned_inputs)
        return self.sim

    def _after_sim_command(self) -> None:
        self._update_actions()
        self._update_live()

    def sim_run(self) -> None:
        sim = self._ensure_sim()
        if sim:
            if not self.device_dock.visibleRegion().isEmpty() or not self.il_dock.visibleRegion().isEmpty():
                self.sim_dock.raise_()       # entradas/saidas a vista ao iniciar a simulacao
            sim.start()
            self.clock.restart()
            self._after_sim_command()

    def sim_pause(self) -> None:
        if self.sim:
            self.sim.pause()
            self._after_sim_command()

    def sim_scan(self) -> None:
        sim = self._ensure_sim()
        if sim:
            sim.pause()
            sim.scan_once()
            self._after_sim_command()

    def sim_step(self) -> None:
        sim = self._ensure_sim()
        if sim:
            sim.pause()
            sim.step_instruction()
            self._after_sim_command()

    def sim_reset(self) -> None:
        if self.sim:
            self.sim.reset()
            self.clock.restart()
            self._after_sim_command()

    def sim_stop(self) -> None:
        if self.sim:
            self.sim.stop()
            self._after_sim_command()

    # ============================================== verificacao e blocos IL
    def verify_esp32(self) -> None:
        from ..verify import verify_for_esp32
        if self.result is None or not self.result.ok:
            self.compile()
        panel = self.device_panel
        info = getattr(panel, "device_info", None) if panel.connected else None
        status = panel.last_status if panel.connected else None
        self.setCursor(Qt.WaitCursor)
        try:
            report = verify_for_esp32(self.project, self.result, device_info=info, device_status=status)
        finally:
            self.unsetCursor()
        self.last_report = report
        self.statusBar().showMessage(report.summary(), 8000)
        VerifyDialog(report, self).exec()

    def show_il_blocks(self) -> None:
        self.il_dock.show()
        self.il_dock.raise_()
        self._refresh_il()

    def flash_firmware(self) -> None:
        from .flash_dialog import FlashDialog
        FlashDialog(before_flash=self.session.close, parent=self).exec()

    def show_esp32(self) -> None:
        self.esp32_dock.show()
        self.esp32_dock.raise_()
        if not self.layout_locked and not self.esp32_dock.isFloating():
            target = int(0.5 * self.height())           # a placa precisa de altura para ser legivel
            if self.esp32_dock.height() < target:
                self.resizeDocks([self.esp32_dock], [target], Qt.Vertical)

    def show_cpp(self) -> None:
        self.cpp_dock.show()
        self.cpp_dock.raise_()
        self._refresh_cpp()

    def _refresh_cpp(self) -> None:
        """O C++ sai direto do diagrama: atualiza a cada edicao, sem esperar a compilacao."""
        if not hasattr(self, "cpp_dock") or not self.cpp_dock.isVisible():
            return
        self.cpp_panel.set_project(self.project)
        self.cpp_panel.highlight(self.view.selection)

    def _refresh_il(self) -> None:
        if not hasattr(self, "il_dock") or not self.il_dock.isVisible():
            return
        result = self.result if self.result is not None else compile_project(self.project)
        key = (id(self.project), result.build_id, result.ok, len(result.diagnostics), theme.current_name)
        if getattr(self, "_il_key", None) != key or self.il_panel.tree.topLevelItemCount() == 0:
            self._il_key = key
            self.il_panel.set_program(self.project, result)
            self.il_panel.highlight(self.view.selection)

    # ================================================================ tema
    def set_theme(self, mode: str, save: bool = True) -> None:
        app = QApplication.instance()
        theme.apply_theme(app, mode)
        if save:
            theme.save_mode(mode)
        if mode in getattr(self, "theme_actions", {}):
            self.theme_actions[mode].setChecked(True)
        self.theme_changed()

    def toggle_theme(self) -> None:
        self.set_theme("light" if theme.is_dark() else "dark")

    def on_system_scheme_changed(self, *_args) -> None:
        if theme.current_mode == "system":
            self.set_theme("system", save=False)

    def theme_changed(self) -> None:
        """Redesenha o que guarda cores ja calculadas (icones, cena, listas)."""
        for key, name in self._icon_names.items():
            self.actions_[key].setIcon(make_icon(name))
        self._update_lock_icon()
        self.palette.theme_changed()
        self.view.theme_changed()
        self.view.set_errors({d.element_id for d in (self.result.errors if self.result else []) if d.element_id})
        self.sim_panel.io.theme_changed()
        self.device_panel.io.theme_changed()
        self._il_key = None
        self._refresh_il()
        self.cpp_panel.theme_changed()
        self.esp32_panel.theme_changed()
        self._update_live()

    # ================================================== ambientes de simulacao
    def show_environment(self) -> None:
        self.env_dock.show()
        self.env_dock.raise_()
        self._grow_environment()

    def _grow_environment(self) -> None:
        """Com um ambiente em uso, o painel de baixo cresce para a cena ficar legivel."""
        if self.layout_locked:              # layout travado: o usuario escolheu os tamanhos
            return
        if self.env_dock.isVisible() and not self.env_dock.isFloating() and self.env_panel.env is not None:
            target = int(0.42 * self.height())
            if self.env_dock.height() < target:
                self.resizeDocks([self.env_dock], [target], Qt.Vertical)

    def on_environment_changed(self, env_id: str) -> None:
        if self.project.environment != env_id:
            self.project.environment = env_id
            self.dirty = True
            self._update_title()
        if self.sim is not None:
            self.sim.attach_plant(self.env_panel.plant)
        self.sim_panel.io.set_owned(self.env_panel.owned_inputs)
        self._grow_environment()
        self._update_live()

    def add_environment_symbols(self) -> None:
        env = self.env_panel.env
        if env is None or not self._can_edit():
            return
        names = {s.name.upper() for s in self.project.symbols}
        addrs = {s.address.strip().upper() for s in self.project.symbols}
        new = [Symbol(p.label, p.address, p.description) for p in env.inputs + env.outputs
               if p.label.upper() not in names and p.address.upper() not in addrs]
        if not new:
            self.statusBar().showMessage("Os simbolos do ambiente ja existem no projeto.", 4000)
            return
        self.push_undo()
        self.project.symbols.extend(new)
        self.modified()
        self.statusBar().showMessage(f"{len(new)} simbolo(s) do ambiente '{env.name}' adicionados.", 5000)

    def open_example(self, rel: str) -> None:
        from ..core.isa import ISA_PATH
        path = ISA_PATH.parents[2] / "examples" / rel
        if not path.exists():
            QMessageBox.warning(self, "Exemplo", f"Exemplo nao encontrado: {path}")
            return
        self.file_open(str(path))

    def on_input(self, index: int, value: bool) -> None:
        if self.sim is not None:
            self.sim.set_input(index, value)
            self._update_live()

    def on_speed_changed(self, _index: int = 0) -> None:
        self.statusBar().showMessage(f"Velocidade da simulacao: {self.sim_panel.speed.currentText()}", 2500)
        if self.sim is not None:
            self.sim.actual_speed = 0.0         # recomeca a media da velocidade real
        if self.persist_layout:
            self._settings().setValue("sim/speed", str(self.sim_panel.speed_factor))   # "inf" = maxima

    def tick(self) -> None:
        if self.sim is not None and self.sim.state == SimState.RUNNING:
            ms = self.clock.restart()
            # no maximo ~2/3 do intervalo do relogio em varreduras: sobra tempo para desenhar e responder
            self.sim.advance(ms, self.sim_panel.speed_factor, work_ms=self.timer.interval() * 0.65)
            self._update_live()

    # ============================================================ dispositivo
    def device_tick(self) -> None:
        """Polling: 200 ms com monitor ligado, 1 s sem monitor, reconexao a cada 2 s."""
        self.device_ticks += 1
        self._sync_device_status()
        if self.device_panel.connected:
            board_visible = not self.esp32_dock.visibleRegion().isEmpty()
            if self.monitoring or board_visible or self.device_ticks % 5 == 0:
                self.session.poll()
        elif self.session.auto_reconnect and self.device_ticks % 10 == 0:
            self.session.poll()

    def on_monitor_toggled(self, on: bool) -> None:
        self.monitoring = on
        if on and (self.result is None or not self.result.ok):
            self.compile()
        self._update_actions()
        self._sync_device_status()
        self._update_live()

    def on_snapshot(self, snap) -> None:
        self.last_snapshot = snap
        src = MonitorSource(snap, self.result or CompileResult())
        self.device_panel.io.update_values(snap.inputs, snap.q_logical, snap.q_commanded, src.timer_state,
                                           src.counter_state, src.read_bit, src.word_value)
        self.esp32_panel.on_snapshot(snap)
        if self.monitoring:
            self._update_live()

    def device_transfer(self) -> None:
        if not self.device_panel.connected:
            QMessageBox.information(self, "Transferir", "Conecte-se a um dispositivo no painel Dispositivo.")
            self.device_dock.show()
            self.device_dock.raise_()
            return
        if not self.compile():
            QMessageBox.warning(self, "Transferir", "O programa tem erros e nao sera transferido.\n"
                                                    "Veja a aba Mensagens.")
            return
        st = self.device_panel.last_status
        if st is not None and st.state == DevState.RUN:
            answer = QMessageBox.question(
                self, "Transferir", "O dispositivo esta em RUN. Ele sera colocado em STOP (saidas no estado "
                                    "seguro) antes da transferencia. Continuar?")
            if answer != QMessageBox.Yes:
                return
        image = self.result.image
        from PySide6.QtWidgets import QProgressDialog
        self.progress_dialog = QProgressDialog("Transferindo programa...", None, 0, len(image), self)
        self.progress_dialog.setWindowTitle("Transferencia")
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        session = self.session
        self.session.run_on_client("transfer", lambda c: c.download(
            image, progress=lambda a, b: session.progress.emit(a, b), stop_if_running=True))

    def on_transfer_progress(self, sent: int, total: int) -> None:
        if self.progress_dialog is not None:
            self.progress_dialog.setMaximum(total)
            self.progress_dialog.setValue(sent)

    def _close_progress(self) -> None:
        if self.progress_dialog is not None:
            self.progress_dialog.close()
            self.progress_dialog = None

    def on_job_done(self, tag: str, result) -> None:
        if tag == "transfer":
            self._close_progress()
            QMessageBox.information(self, "Transferencia concluida", (
                f"Programa transferido, validado pelo firmware e ativado.\n\n"
                f"{result.bytes_sent} bytes em {result.chunks} bloco(s), {result.retries} retransmissao(oes)\n"
                f"build_id 0x{result.build_id:08x}, CRC-32 0x{result.crc:08x}\n\n"
                f"O dispositivo esta em STOP. Use RUN para executar."))
        if tag == "connect" and self.device_panel.store_target(self.project.target):
            self.dirty = True          # configuracao do dispositivo de destino salva no projeto
            self._update_title()
        if tag in ("transfer", "mode", "connect"):
            self.session.poll()

    def on_job_failed(self, tag: str, message: str) -> None:
        if tag == "transfer":
            self._close_progress()
            QMessageBox.critical(self, "Transferencia falhou",
                                 f"{message}\n\nO programa anterior do dispositivo foi preservado.")
        elif tag == "connect":
            self.device_panel.link.setText(f"Falha ao conectar: {message}")
            self.session.auto_reconnect = False
            self.device_panel._update_buttons()
        elif tag not in ("poll",):
            self.statusBar().showMessage(f"Dispositivo: {message}", 6000)

    # =============================================================== arquivos
    def maybe_save(self) -> bool:
        if not self.dirty:
            return True
        answer = QMessageBox.question(self, "Projeto modificado", "Salvar as alteracoes?",
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if answer == QMessageBox.Save:
            return self.file_save()
        return answer == QMessageBox.Discard

    def set_project(self, project: Project, path: str | None) -> None:
        self.project, self.path = project, path
        self.dirty = False
        self.result = None
        self.sim = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.messages.clear()
        self.view.selection = None
        self.device_panel.load_target(project.target)
        self.env_panel.select(project.environment)
        self.sim_panel.io.set_owned(self.env_panel.owned_inputs)
        if project.environment and self.env_panel.env is not None:
            self.env_dock.show()
            self.env_dock.raise_()
            QTimer.singleShot(0, self._grow_environment)
        self.refresh()

    def file_new(self) -> None:
        if not self.maybe_save():
            return
        dlg = NewProjectDialog(self)
        if dlg.exec():
            self.set_project(dlg.project(), None)

    def file_open(self, path: str | None = None) -> None:
        if not self.maybe_save():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Abrir projeto", "", FILE_FILTER)
        if not path:
            return
        try:
            self.set_project(Project.load(path), path)
        except (OSError, ProjectFormatError, ValueError, TypeError, KeyError) as exc:
            QMessageBox.critical(self, "Abrir projeto", f"Nao foi possivel abrir {path}:\n{exc}")

    def file_save(self) -> bool:
        if not self.path:
            return self.file_save_as()
        try:
            self.project.save(self.path)
        except OSError as exc:
            QMessageBox.critical(self, "Salvar", f"Erro ao salvar: {exc}")
            return False
        self.dirty = False
        self._update_title()
        self.statusBar().showMessage(f"Salvo em {self.path}", 4000)
        return True

    def file_save_as(self) -> bool:
        path, _ = QFileDialog.getSaveFileName(self, "Salvar projeto", self.path or f"{self.project.name}.ladproj",
                                              FILE_FILTER)
        if not path:
            return False
        self.path = path
        return self.file_save()

    def _compiled_or_warn(self) -> bool:
        if self.compile():
            return True
        QMessageBox.warning(self, "Exportar", "O programa tem erros de compilacao.")
        return False

    def export_lil(self) -> None:
        if not self._compiled_or_warn():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar LIL", f"{self.project.name}.lil",
                                              "Listagem LIL (*.lil)")
        if path:
            Path(path).write_text(self.result.lil, encoding="utf-8")

    def export_bin(self) -> None:
        if not self._compiled_or_warn():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar LDRB", f"{self.project.name}.ldrb",
                                              "Imagem LDRB (*.ldrb)")
        if path:
            Path(path).write_bytes(self.result.image)

    def import_program(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Importar programa", "",
                                              "Programas (*.lil *.ldrb);;Todos (*.*)")
        if not path:
            return
        try:
            name = Path(path).stem
            if path.lower().endswith(".ldrb"):
                project = import_image(Path(path).read_bytes(), name)
            else:
                project = import_lil(Path(path).read_text(encoding="utf-8"), name)
        except (OSError, AsmError, ImportError_, ImageValidationError, ValueError) as exc:
            QMessageBox.critical(self, "Importar", f"Nao foi possivel importar:\n{exc}")
            return
        self.set_project(project, None)
        self.dirty = True
        self._update_title()

    def closeEvent(self, event) -> None:
        if self.maybe_save():
            if self.persist_layout:
                self._save_layout()
            self.session.close()
            self.esp32_panel.shutdown()          # encerra o exemplo Arduino, se estiver rodando
            event.accept()
        else:
            event.ignore()

    # ================================================================ ajuda
    def about(self) -> None:
        QMessageBox.about(self, "Sobre", f"LadderIDE {__version__}\nCompilador {COMPILER_VERSION}, formato LDRB 1.0\n\n"
                                         "IDE LADDER para CLP com ESP32 - trabalho academico.\n"
                                         "Nao e um CLP de seguranca.")

    def instruction_help(self) -> None:
        QMessageBox.information(self, "Instrucoes", (
            "XIC  contato normalmente aberto (NA): conduz se o bit = 1\n"
            "XIO  contato normalmente fechado (NF): conduz se o bit = 0\n"
            "NOT  inverte o resultado ate o ponto\n"
            "Ramo paralelo = OU;  contatos em serie = E\n\n"
            "OTE  bobina: bit = resultado da rede\n"
            "OTL  SET: liga e mantem;  OTU  RESET: desliga\n\n"
            "TON  retardo na energizacao (DN apos PRE ms habilitado)\n"
            "TOF  retardo na desenergizacao (DN fica 1 por PRE ms apos desabilitar)\n"
            "RTO  retentivo: acumula enquanto habilitado; zera so com RES\n"
            "CTU/CTD  contadores por borda de subida; DN: ACC>=PRE (CTU) / ACC<=0 (CTD)\n"
            "RES  zera temporizador ou contador (CTD volta ao preset)\n\n"
            "Bits: Tn.DN Tn.TT Tn.EN  Cn.DN Cn.OV Cn.UN\n"
            "Sistema: S0.0 primeira varredura, S0.1 sempre 1, S0.2 sempre 0, S0.3 relogio 1 s\n\n"
            "Especificacao completa: docs/ladder-specification.md"))
