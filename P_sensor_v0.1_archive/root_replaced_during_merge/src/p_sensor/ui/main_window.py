from __future__ import annotations

import json
from collections import deque
from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QEvent, QPoint, QRect, QSettings, QSize, QTimer, Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from p_sensor import __version__
from p_sensor.acquisition import AcquisitionController, NiDaqBackend, SimulatedBackend
from p_sensor.config import (
    DEFAULT_COLORS,
    DEFAULT_CONFIG_PATH,
    DEFAULT_EXPORT_DIRECTORY,
    build_channel_name,
    build_physical_channel,
    channel_selection_from_physical_channel,
    load_config,
    normalize_runtime_path_value,
    resolve_runtime_path,
    save_config,
    validate_app_config,
)
from p_sensor.models import (
    AppConfig,
    ChannelConfig,
    ChannelReading,
    MeasurementSample,
    SamplingConfig,
)
from p_sensor.storage import CsvRecorder


class FlowLayout(QLayout):
    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        margin: int = 0,
        h_spacing: int = 6,
        v_spacing: int = 6,
    ) -> None:
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self.setContentsMargins(margin, margin, margin, margin)

    def __del__(self) -> None:
        while self.count():
            self.takeAt(0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int) -> QLayoutItem | None:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientations:
        return Qt.Orientations()

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        margins = self.contentsMargins()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        size += QSize(margins.left() + margins.right(), margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, *, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective_rect = rect.adjusted(margins.left(), margins.top(), -margins.right(), -margins.bottom())
        x = effective_rect.x()
        y = effective_rect.y()
        line_height = 0

        for item in self._items:
            item_size = item.sizeHint()
            next_x = x + item_size.width()
            if line_height > 0 and next_x > effective_rect.right() + 1:
                x = effective_rect.x()
                y += line_height + self._v_spacing
                next_x = x + item_size.width()
                line_height = 0

            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item_size))

            x = next_x + self._h_spacing
            line_height = max(line_height, item_size.height())

        used_height = y + line_height - rect.y()
        return used_height + margins.bottom()


class ChannelGaugeWidget(QFrame):
    CARD_MIN_HEIGHT = 84
    CARD_MIN_WIDTH = 248

    def __init__(
        self,
        channel_name: str,
        physical_channel: str,
        color: str,
        *,
        module_number: int,
        sensor_port: int,
    ) -> None:
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self._color = color
        self.setMinimumWidth(self.CARD_MIN_WIDTH)
        self.setMinimumHeight(self.CARD_MIN_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        compact_physical_channel = f"AI{sensor_port - 1}"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(2)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(2)
        self.module_label = QLabel(f"Module {module_number}")
        self.module_label.setStyleSheet(
            "font-size: 16px; font-weight: 800; color: #D6E7FF; "
            "background: rgba(31, 111, 235, 0.20); border: 1px solid rgba(83, 155, 245, 0.24); "
            "border-radius: 12px; padding: 0px 8px;"
        )
        self.module_label.setFixedHeight(22)
        self.module_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.module_label.setAlignment(Qt.AlignCenter)
        self.module_label.setToolTip(f"Module {module_number}")
        self.port_label = QLabel(f"Port {sensor_port}")
        self.port_label.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #E6EDF3; "
            "background: rgba(255, 255, 255, 0.03); border: 1px solid #30363D; "
            "border-radius: 12px; padding: 0px 8px;"
        )
        self.port_label.setFixedHeight(22)
        self.port_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.port_label.setAlignment(Qt.AlignCenter)
        self.port_label.setToolTip(f"Port {sensor_port}")
        self.channel_label = QLabel(compact_physical_channel)
        self.channel_label.setStyleSheet(
            "font-size: 16px; font-weight: 600; color: #9FB0C3; "
            "background: rgba(255, 255, 255, 0.03); border: 1px solid #30363D; border-radius: 13px; padding: 0px 10px;"
        )
        self.channel_label.setAlignment(Qt.AlignCenter)
        self.channel_label.setFixedHeight(22)
        self.channel_label.setMinimumWidth(0)
        self.channel_label.setMaximumWidth(88)
        self.channel_label.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)
        self.channel_label.setToolTip(physical_channel)
        header.addWidget(self.module_label)
        header.addWidget(self.port_label)
        header.addStretch(1)
        header.addWidget(self.channel_label)

        self.resistance_label = QLabel("-- ohm")
        self.resistance_label.setAlignment(Qt.AlignCenter)
        self.resistance_label.setFixedHeight(28)
        self.resistance_label.setMinimumWidth(0)
        self.resistance_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.resistance_label.setStyleSheet(
            "font-size: 19px; font-weight: 800; color: #F0F6FC; "
            "background: rgba(255, 255, 255, 0.02); border: 1px solid #30363D; border-radius: 6px; padding: 0px 8px;"
        )
        self.voltage_label = QLabel("-- V")
        self.voltage_label.setAlignment(Qt.AlignCenter)
        self.voltage_label.setFixedHeight(28)
        self.voltage_label.setMinimumWidth(0)
        self.voltage_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.voltage_label.setStyleSheet(
            "font-size: 16px; font-weight: 700; color: #A9B4C2; "
            "background: rgba(255, 255, 255, 0.02); border: 1px solid #30363D; border-radius: 6px; padding: 0px 8px;"
        )
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(2)
        value_row.addWidget(self.resistance_label, 1)
        value_row.addWidget(self.voltage_label, 1)

        layout.addLayout(header)
        layout.addLayout(value_row)

        self._apply_card_style()
        self.update_reading(None)

    def update_reading(self, reading: ChannelReading | None) -> None:
        if reading is None:
            self.resistance_label.setText("-- ohm")
            self.voltage_label.setText("-- V")
            return

        self.resistance_label.setText(f"{reading.resistance_ohm:.3f} ohm")
        self.voltage_label.setText(f"{reading.voltage:.5f} V")

    def _apply_card_style(self) -> None:
        self.setStyleSheet(
            "QFrame {"
            "background: #18222E;"
            "border: 1px solid #30363D;"
            "border-radius: 6px;"
            "}"
        )


class MainWindow(QMainWindow):
    SETTINGS_GROUP = "main_window"
    WINDOW_MARGIN = 8
    PANEL_MARGIN = 8
    PANEL_TOP_MARGIN = 6
    PANEL_SPACING = 6
    GAUGE_COLUMNS = 4
    GAUGE_VISIBLE_ROWS = 1
    CHANNEL_COLUMNS = [
        "Module",
        "Port 1",
        "Port 2",
        "Port 3",
        "Port 4",
    ]
    CHANNEL_DETAIL_COLUMNS = [
        "Module",
        "Port",
        "Bridge",
        "Excitation (V)",
        "Nominal (ohm)",
    ]
    BRIDGE_TYPE_OPTIONS = ["quarter_bridge", "half_bridge", "full_bridge"]
    VALUE_RANGES = {
        "10 s": 10.0,
        "1 min": 60.0,
        "5 min": 300.0,
        "All": None,
    }

    def __init__(self, config: AppConfig, config_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("P_sensor DAQ Monitor")
        self.resize(1760, 980)

        self.config = config
        self.config_path = config_path
        self.csv_recorder = CsvRecorder()
        self.controller: AcquisitionController | None = None
        self.settings = QSettings()

        self.history: dict[int, deque[tuple[float, float, float]]] = {}
        self.resistance_curves: dict[int, pg.PlotDataItem] = {}
        self.voltage_curves: dict[int, pg.PlotDataItem] = {}
        self.gauges: dict[int, ChannelGaugeWidget] = {}
        self.channel_toggle_buttons: dict[tuple[int, int], QPushButton] = {}
        self.latest_readings: dict[int, ChannelReading] = {}
        self.latest_elapsed_s: float = 0.0
        self.plot_checkboxes: dict[int, QCheckBox] = {}
        self.resistance_plot_checkbox: QCheckBox | None = None
        self.voltage_plot_checkbox: QCheckBox | None = None
        self.highlight_intervals: list[tuple[float, float]] = []
        self.highlight_regions: list[pg.LinearRegionItem] = []
        self.active_highlight_start_s: float | None = None
        self.active_highlight_region: pg.LinearRegionItem | None = None
        self.monitoring_layout_auto_fit = True
        self._restoring_preferences = False
        self._applying_monitoring_fit = False
        self._pending_layout_refresh = False
        self._gauge_order: list[int] = []
        self._gauge_columns_in_use = 1

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_samples)

        self._apply_window_style()
        self._build_menu()
        self._build_ui()
        self._load_config_into_widgets(self.config)
        self._rebuild_gauges()
        self._reset_history()
        self._restore_window_preferences()
        self._log("Application initialized")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save_window_preferences()
        self._stop_measurement()
        super().closeEvent(event)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        self.load_action = QAction("Load Config", self)
        self.save_action = QAction("Save Config", self)
        quit_action = QAction("Quit", self)

        self.load_action.triggered.connect(self._load_config_dialog)
        self.save_action.triggered.connect(self._save_config_dialog)
        quit_action.triggered.connect(self.close)

        file_menu.addAction(self.load_action)
        file_menu.addAction(self.save_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

    def _build_ui(self) -> None:
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(
            self.WINDOW_MARGIN,
            self.WINDOW_MARGIN,
            self.WINDOW_MARGIN,
            self.WINDOW_MARGIN,
        )
        central_layout.setSpacing(self.PANEL_SPACING)

        central_layout.addWidget(self._build_operation_bar())

        self.monitoring_stack = QSplitter(Qt.Vertical)
        self.monitoring_stack.setChildrenCollapsible(False)
        self.monitoring_stack.setHandleWidth(3)
        self.monitoring_stack.addWidget(self._build_monitor_panel())
        self.monitoring_stack.addWidget(self._build_graph_panel())
        self.monitoring_stack.setStretchFactor(0, 4)
        self.monitoring_stack.setStretchFactor(1, 6)
        self.monitoring_stack.setSizes([420, 560])

        self.side_stack = QSplitter(Qt.Vertical)
        self.side_stack.setChildrenCollapsible(False)
        self.side_stack.setHandleWidth(3)
        self.side_stack.addWidget(self._build_channel_panel())
        self.side_stack.addWidget(self._build_log_panel())
        self.side_stack.setStretchFactor(0, 7)
        self.side_stack.setStretchFactor(1, 3)
        self.side_stack.setSizes([600, 260])

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(3)
        self.workspace_splitter.addWidget(self.monitoring_stack)
        self.workspace_splitter.addWidget(self.side_stack)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 0)
        self.workspace_splitter.setSizes([1380, 340])

        self.monitoring_stack.splitterMoved.connect(self._handle_monitoring_splitter_moved)
        self.side_stack.splitterMoved.connect(self._save_window_preferences)
        self.workspace_splitter.splitterMoved.connect(self._save_window_preferences)
        self.workspace_splitter.splitterMoved.connect(self._schedule_layout_refresh)

        central_layout.addWidget(self.workspace_splitter, stretch=1)

        self.setCentralWidget(central)

    def _build_operation_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("operationBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.session_state_label = QLabel("Status Idle")
        self.session_state_label.setObjectName("statusBadge")
        self.backend_label = QLabel("Backend SIM")
        self.backend_label.setObjectName("statusBadge")
        self.active_channels_label = QLabel("Channels 0")
        self.active_channels_label.setObjectName("statusBadge")
        self.export_summary_label = QLabel(DEFAULT_EXPORT_DIRECTORY)
        self.export_summary_label.setObjectName("summaryText")
        self.version_label = QLabel(f"v{'.'.join(__version__.split('.')[:2])}")
        self.version_label.setObjectName("versionBadge")

        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("primaryButton")
        self.connect_button.clicked.connect(self._connect_backend)
        self.start_button = QPushButton("Start")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start_measurement)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setObjectName("secondaryButton")
        self.pause_button.clicked.connect(self._pause_measurement)
        self.resume_button = QPushButton("Resume")
        self.resume_button.setObjectName("secondaryButton")
        self.resume_button.clicked.connect(self._resume_measurement)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.clicked.connect(self._stop_measurement)
        self.mark_start_button = QPushButton("Mark Start")
        self.mark_start_button.setObjectName("markStartButton")
        self.mark_start_button.clicked.connect(self._start_highlight_interval)
        self.mark_stop_button = QPushButton("Mark Stop")
        self.mark_stop_button.setObjectName("markStopButton")
        self.mark_stop_button.clicked.connect(self._stop_highlight_interval)
        self.mark_state_label = QLabel("Marks 0")
        self.mark_state_label.setObjectName("statusBadge")

        for button in (
            self.connect_button,
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.stop_button,
            self.mark_start_button,
            self.mark_stop_button,
        ):
            button.setMinimumHeight(26)

        layout.addWidget(self.session_state_label, 0)
        layout.addWidget(self.backend_label, 0)
        layout.addWidget(self.active_channels_label, 0)
        layout.addWidget(self.export_summary_label, 1)
        layout.addWidget(self.connect_button, 0)
        layout.addWidget(self.start_button, 0)
        layout.addWidget(self.pause_button, 0)
        layout.addWidget(self.resume_button, 0)
        layout.addWidget(self.stop_button, 0)
        layout.addWidget(self.mark_state_label, 0)
        layout.addWidget(self.mark_start_button, 0)
        layout.addWidget(self.mark_stop_button, 0)
        layout.addWidget(self.version_label, 0, Qt.AlignRight)
        return bar

    def _build_channel_panel(self) -> QWidget:
        group = QGroupBox("SESSION")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(
            self.PANEL_MARGIN,
            self.PANEL_TOP_MARGIN,
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
        )
        layout.setSpacing(self.PANEL_SPACING)

        self.export_path_edit = QLineEdit(self.config.export_directory)
        self.export_path_edit.setReadOnly(True)
        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["simulation", "ni"])
        self.acquisition_hz_edit = QLineEdit()
        self.display_hz_edit = QLineEdit()

        runtime_grid = QGridLayout()
        runtime_grid.setContentsMargins(0, 0, 0, 0)
        runtime_grid.setHorizontalSpacing(8)
        runtime_grid.setVerticalSpacing(6)
        runtime_grid.addWidget(self._create_field_label("Backend"), 0, 0)
        runtime_grid.addWidget(self._create_field_label("Export"), 0, 1)
        runtime_grid.addWidget(self.backend_combo, 1, 0)
        runtime_grid.addWidget(self.export_path_edit, 1, 1)
        runtime_grid.addWidget(self._create_field_label("Acquisition Hz"), 2, 0)
        runtime_grid.addWidget(self._create_field_label("Display Hz"), 2, 1)
        runtime_grid.addWidget(self.acquisition_hz_edit, 3, 0)
        runtime_grid.addWidget(self.display_hz_edit, 3, 1)
        layout.addLayout(runtime_grid)

        self.channel_table = QTableWidget(0, len(self.CHANNEL_COLUMNS))
        self.channel_table.setHorizontalHeaderLabels(self.CHANNEL_COLUMNS)
        self.channel_table.verticalHeader().setVisible(False)
        self.channel_table.setAlternatingRowColors(True)
        self.channel_table.setSelectionMode(QTableWidget.NoSelection)
        self.channel_table.setFocusPolicy(Qt.NoFocus)
        self.channel_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for column in range(1, len(self.CHANNEL_COLUMNS)):
            self.channel_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.channel_table.horizontalHeader().setMinimumSectionSize(56)
        self.channel_table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.channel_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.channel_table.setMinimumWidth(340)
        layout.addWidget(self.channel_table)

        self.channel_detail_table = QTableWidget(0, len(self.CHANNEL_DETAIL_COLUMNS))
        self.channel_detail_table.setHorizontalHeaderLabels(self.CHANNEL_DETAIL_COLUMNS)
        self.channel_detail_table.verticalHeader().setVisible(False)
        self.channel_detail_table.setAlternatingRowColors(True)
        self.channel_detail_table.setSelectionMode(QTableWidget.NoSelection)
        self.channel_detail_table.setFocusPolicy(Qt.NoFocus)
        self.channel_detail_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.channel_detail_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        for column in range(2, len(self.CHANNEL_DETAIL_COLUMNS)):
            self.channel_detail_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.Stretch)
        self.channel_detail_table.horizontalHeader().setMinimumSectionSize(72)
        self.channel_detail_table.setMinimumWidth(340)
        self.channel_detail_table.setMinimumHeight(200)
        layout.addWidget(self.channel_detail_table)

        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(6)

        self.browse_button = QPushButton("Folder")
        self.browse_button.setObjectName("secondaryButton")
        self.browse_button.clicked.connect(self._choose_export_directory)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("primaryButton")
        self.apply_button.clicked.connect(self._apply_ui_config)

        self.browse_button.setMinimumHeight(24)
        self.apply_button.setMinimumHeight(24)

        action_row.addWidget(self.browse_button, 0)
        action_row.addWidget(self.apply_button, 0)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        return group

    def _build_graph_panel(self) -> QWidget:
        group = QGroupBox("PLOT")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(
            self.PANEL_MARGIN,
            self.PANEL_TOP_MARGIN,
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
        )
        layout.setSpacing(self.PANEL_SPACING)

        self.range_combo = QComboBox()
        self.range_combo.addItems(list(self.VALUE_RANGES.keys()))
        self.range_combo.setCurrentText("1 min")
        self.range_combo.currentIndexChanged.connect(self._refresh_plot)

        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(4)

        self.plot_range_box, plot_range_layout = self._create_plot_selector_box()
        plot_range_layout.addWidget(self._create_plot_selector_title("Range"))
        plot_range_layout.addWidget(self.range_combo)
        self.plot_range_box.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        self.plot_mode_box, self.plot_mode_layout = self._create_plot_selector_box()
        self.plot_mode_box.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Minimum)

        self.plot_channel_box = QFrame()
        self.plot_channel_box.setObjectName("plotSelectorBox")
        self.plot_channel_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        plot_channel_box_layout = QHBoxLayout(self.plot_channel_box)
        plot_channel_box_layout.setContentsMargins(8, 1, 8, 1)
        plot_channel_box_layout.setSpacing(4)
        plot_channel_box_layout.addWidget(self._create_plot_selector_title("Channels"))

        self.plot_channel_scroll = QScrollArea()
        self.plot_channel_scroll.setObjectName("plotChannelScroll")
        self.plot_channel_scroll.setWidgetResizable(True)
        self.plot_channel_scroll.setFrameShape(QFrame.NoFrame)
        self.plot_channel_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.plot_channel_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.plot_channel_scroll.setMinimumHeight(26)
        self.plot_channel_scroll.setMaximumHeight(30)
        self.plot_channel_scroll.viewport().setAutoFillBackground(False)
        self.plot_channel_scroll.viewport().setStyleSheet("background: transparent;")

        self.plot_channel_host = QWidget()
        self.plot_channel_host.setObjectName("plotChannelHost")
        self.plot_channel_layout = FlowLayout(self.plot_channel_host, margin=0, h_spacing=8, v_spacing=2)
        self.plot_channel_scroll.setWidget(self.plot_channel_host)
        plot_channel_box_layout.addWidget(self.plot_channel_scroll, 1)

        controls_row.addWidget(self.plot_range_box, 0)
        controls_row.addWidget(self.plot_mode_box, 0)
        controls_row.addWidget(self.plot_channel_box, 1)
        layout.addLayout(controls_row)

        self.plot_widget = pg.PlotWidget(background="#0F1217")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.25)
        self.plot_widget.getAxis("left").setTextPen("#C9D1D9")
        self.plot_widget.getAxis("bottom").setTextPen("#C9D1D9")
        self.plot_widget.getAxis("right").setTextPen("#9EC1FF")
        self.plot_widget.getAxis("left").setPen(pg.mkPen("#3B4450"))
        self.plot_widget.getAxis("bottom").setPen(pg.mkPen("#3B4450"))
        self.plot_widget.getAxis("right").setPen(pg.mkPen("#3B4450"))
        self.plot_widget.setLabel("left", "Resistance", units="ohm", color="#C9D1D9")
        self.plot_widget.setLabel("bottom", "Elapsed Time", units="s", color="#C9D1D9")
        self.plot_widget.showAxis("right")
        self.voltage_viewbox = pg.ViewBox()
        self.plot_widget.scene().addItem(self.voltage_viewbox)
        self.plot_widget.getAxis("right").linkToView(self.voltage_viewbox)
        self.voltage_viewbox.setXLink(self.plot_widget.getPlotItem())
        self.plot_widget.getPlotItem().vb.sigResized.connect(self._sync_plot_views)
        self._sync_plot_views()
        layout.addWidget(self.plot_widget, 1)

        return group

    def _build_monitor_panel(self) -> QWidget:
        self.monitor_panel = QGroupBox("MODULES")
        gauge_layout = QVBoxLayout(self.monitor_panel)
        gauge_layout.setContentsMargins(
            self.PANEL_MARGIN,
            self.PANEL_TOP_MARGIN,
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
        )
        gauge_layout.setSpacing(self.PANEL_SPACING)
        self.gauge_area = QScrollArea()
        self.gauge_area.setWidgetResizable(True)
        self.gauge_area.setFrameShape(QFrame.NoFrame)
        self.gauge_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.gauge_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.gauge_area.viewport().installEventFilter(self)
        self.gauge_content = QWidget()
        self.gauge_grid = QGridLayout(self.gauge_content)
        self.gauge_grid.setContentsMargins(0, 0, 0, 0)
        self.gauge_grid.setHorizontalSpacing(8)
        self.gauge_grid.setVerticalSpacing(8)
        self.gauge_area.setWidget(self.gauge_content)
        gauge_layout.addWidget(self.gauge_area)
        return self.monitor_panel

    def _build_log_panel(self) -> QWidget:
        group = QGroupBox("LOG")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(
            self.PANEL_MARGIN,
            self.PANEL_TOP_MARGIN,
            self.PANEL_MARGIN,
            self.PANEL_MARGIN,
        )
        layout.setSpacing(self.PANEL_SPACING)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(500)
        self.log_output.setPlaceholderText("Debug echo")
        self.log_output.document().setDocumentMargin(3)
        layout.addWidget(self.log_output)
        return group

    def _create_panel_intro(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("panelIntro")
        label.setWordWrap(True)
        return label

    def _create_section_heading(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionHeading")
        return label

    def _create_section_header(self, title: str, description: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        title_label = self._create_section_heading(title)
        description_label = self._create_panel_intro(description)
        layout.addWidget(title_label)
        layout.addWidget(description_label, 1)
        return widget

    def _create_field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _apply_window_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #13161B;
                color: #E6EDF3;
            }
            QWidget {
                color: #E6EDF3;
                font-size: 16px;
            }
            QFrame#operationBar {
                background: #181C23;
                border: 1px solid #2D333B;
                border-radius: 4px;
            }
            QMenuBar, QMenuBar::item, QMenu {
                background: #181C23;
                color: #E6EDF3;
            }
            QMenuBar::item:selected, QMenu::item:selected {
                background: #253041;
            }
            QGroupBox {
                background: #181C23;
                color: #E6EDF3;
                border: 1px solid #2D333B;
                border-radius: 4px;
                margin-top: 14px;
                font-weight: 700;
                font-size: 19px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 8px;
                padding: 0 4px 2px 4px;
            }
            QLabel {
                color: #E6EDF3;
                padding: 0px;
                margin: 0px;
            }
            QLineEdit, QComboBox {
                background: #0F1217;
                color: #E6EDF3;
                border: 1px solid #30363D;
                border-radius: 3px;
                padding: 0px 4px;
                min-height: 22px;
                selection-background-color: #2F81F7;
                selection-color: #FFFFFF;
            }
            QTableWidget, QPlainTextEdit {
                background: #0F1217;
                color: #E6EDF3;
                border: 1px solid #30363D;
                border-radius: 3px;
                padding: 0px 4px;
                selection-background-color: #2F81F7;
                selection-color: #FFFFFF;
            }
            QComboBox::drop-down {
                width: 16px;
                border: 0;
            }
            QAbstractItemView {
                alternate-background-color: #171B22;
            }
            QTableView::item {
                padding: 0px 3px;
            }
            QHeaderView::section {
                background: #20262E;
                color: #E6EDF3;
                border: 0;
                border-right: 1px solid #30363D;
                border-bottom: 1px solid #30363D;
                padding: 1px 4px;
                font-weight: 700;
            }
            QTableCornerButton::section {
                background: #20262E;
                border: 1px solid #30363D;
            }
            QPushButton {
                font-weight: 700;
                border-radius: 4px;
                padding: 0px 6px;
                min-height: 22px;
                color: #E6EDF3;
                border: 1px solid #3B4450;
                background: #1C232D;
            }
            QPushButton:hover {
                background: #232C38;
            }
            QPushButton#primaryButton {
                background: #1F6FEB;
                color: #FFFFFF;
                border: 1px solid #1759BA;
            }
            QPushButton#primaryButton:hover {
                background: #175FD1;
            }
            QPushButton#secondaryButton {
                background: #1C232D;
                color: #E6EDF3;
            }
            QPushButton#markStartButton {
                background: #B9E6C9;
                color: #173B27;
                border: 1px solid #8EC6A2;
            }
            QPushButton#markStartButton:hover {
                background: #A9DBBC;
            }
            QPushButton#markStopButton {
                background: #EAB7BE;
                color: #4A1F28;
                border: 1px solid #D4929C;
            }
            QPushButton#markStopButton:hover {
                background: #E0A4AD;
            }
            QPushButton#dangerButton {
                background: #D9485F;
                color: #FFFFFF;
                border: 1px solid #B5364A;
            }
            QPushButton#dangerButton:hover {
                background: #C43B52;
            }
            QLabel#statusBadge {
                background: #13233A;
                color: #D6E7FF;
                border: 1px solid #234C80;
                border-radius: 4px;
                padding: 0px 3px;
                min-height: 20px;
                font-weight: 700;
            }
            QLabel#versionBadge {
                color: #8B949E;
                padding: 0px 2px;
                font-weight: 700;
                min-width: 42px;
            }
            QLabel#summaryText {
                color: #9AA4AF;
                padding: 0px;
                font-weight: 600;
            }
            QLabel#helperText {
                color: #8B949E;
                padding: 0;
            }
            QLabel#panelIntro {
                color: #9AA4AF;
                padding: 0;
            }
            QLabel#sectionHeading {
                color: #D6E7FF;
                font-weight: 700;
                font-size: 19px;
                padding: 0;
            }
            QLabel#fieldLabel {
                color: #8B949E;
                font-size: 16px;
                font-weight: 700;
                padding: 0px;
            }
            QFrame#plotSelectorBox {
                background: #171C23;
                border: 1px solid #2D333B;
                border-radius: 3px;
            }
            QScrollArea#plotChannelScroll, QWidget#plotChannelHost {
                background: transparent;
                border: 0;
            }
            QLabel#plotSelectorTitle {
                color: #8B949E;
                font-size: 16px;
                font-weight: 700;
                padding-right: 3px;
            }
            QSplitter::handle {
                background: #242A33;
            }
        """
        )

    def _load_config_into_widgets(self, config: AppConfig) -> None:
        self.backend_combo.setCurrentText(config.backend)
        self.acquisition_hz_edit.setText(str(config.sampling.acquisition_hz))
        self.display_hz_edit.setText(str(config.sampling.display_update_hz))
        self.export_path_edit.setText(config.export_directory)
        self._refresh_runtime_summary()
        self.channel_toggle_buttons.clear()

        channels_by_selection: dict[tuple[int, int], ChannelConfig] = {}
        module_numbers: set[int] = set()
        for index, channel in enumerate(config.channels):
            module_number, sensor_port = channel_selection_from_physical_channel(channel.physical_channel, index)
            channels_by_selection[(module_number, sensor_port)] = channel
            module_numbers.add(module_number)

        ordered_modules = sorted(module_numbers) if module_numbers else [1]
        self.channel_table.setRowCount(len(ordered_modules))
        self.channel_detail_table.setRowCount(len(ordered_modules) * 4)
        detail_row = 0
        for row, module_number in enumerate(ordered_modules):
            module_item = QTableWidgetItem(str(module_number))
            module_item.setFlags(Qt.ItemIsEnabled)
            module_item.setForeground(QColor("#E6EDF3"))
            self.channel_table.setItem(row, 0, module_item)

            for sensor_port in range(1, 5):
                channel = channels_by_selection.get((module_number, sensor_port))
                button = self._create_channel_toggle_button(
                    module_number=module_number,
                    sensor_port=sensor_port,
                    enabled=bool(channel and channel.enabled),
                )
                self.channel_table.setCellWidget(row, sensor_port, button)
                self.channel_toggle_buttons[(row, sensor_port)] = button
                self._set_channel_detail_row(
                    detail_row,
                    module_number=module_number,
                    sensor_port=sensor_port,
                    channel=channel,
                )
                detail_row += 1

        self.channel_table.resizeColumnsToContents()
        self.channel_table.setColumnWidth(0, 64)
        self.channel_detail_table.resizeColumnsToContents()
        self.channel_detail_table.setColumnWidth(0, 64)
        self.channel_detail_table.setColumnWidth(1, 56)
        self._update_channel_table_height()
        self._update_runtime_controls()

    def _apply_ui_config(self) -> bool:
        try:
            self.config = self._config_from_ui()
        except ValueError as exc:
            self._show_error("Invalid Configuration", str(exc))
            return False

        self._refresh_runtime_summary()
        self._rebuild_gauges()
        self._reset_history()
        self._refresh_displays()
        self._update_runtime_controls()
        self._log("UI configuration applied")
        return True

    def _config_from_ui(self) -> AppConfig:
        channels: list[ChannelConfig] = []
        previous_channels = self._channel_map_by_selection(self.config.channels)
        channel_details = self._channel_detail_map_from_ui()
        color_index = 0
        for row in range(self.channel_table.rowCount()):
            module_number = self._table_int(row, 0, minimum=1, field_name="Module")
            for sensor_port in range(1, 5):
                enabled = self._channel_toggle_enabled(row, sensor_port)
                previous_channel = previous_channels.get((module_number, sensor_port))
                detail = channel_details.get((module_number, sensor_port))
                channels.append(
                    ChannelConfig(
                        enabled=enabled,
                        name=build_channel_name(module_number, sensor_port),
                        physical_channel=build_physical_channel(module_number, sensor_port),
                        bridge_type=(
                            detail["bridge_type"]
                            if detail is not None
                            else previous_channel.bridge_type if previous_channel else "quarter_bridge"
                        ),
                        excitation_voltage=(
                            detail["excitation_voltage"]
                            if detail is not None
                            else previous_channel.excitation_voltage if previous_channel else 5.0
                        ),
                        nominal_resistance_ohm=(
                            detail["nominal_resistance_ohm"]
                            if detail is not None
                            else previous_channel.nominal_resistance_ohm if previous_channel else 350.0
                        ),
                        zero_offset=previous_channel.zero_offset if previous_channel else 0.0,
                        calibration_scale=previous_channel.calibration_scale if previous_channel else 1.0,
                        color=(
                            previous_channel.color
                            if previous_channel
                            else DEFAULT_COLORS[color_index % len(DEFAULT_COLORS)]
                        ),
                    )
                )
                color_index += 1

        return validate_app_config(
            AppConfig(
                backend=self.backend_combo.currentText(),
                export_directory=normalize_runtime_path_value(
                    self.export_path_edit.text().strip() or DEFAULT_EXPORT_DIRECTORY
                ),
                sampling=SamplingConfig(
                    acquisition_hz=float(self.acquisition_hz_edit.text() or 10.0),
                    display_update_hz=float(self.display_hz_edit.text() or 10.0),
                    mode=self.config.sampling.mode,
                    history_seconds=self.config.sampling.history_seconds,
                ),
                channels=channels,
            ),
        )

    def _dispose_controller(self) -> None:
        if not self.controller:
            return

        controller = self.controller
        self.controller = None
        try:
            controller.stop()
        except Exception as exc:  # pragma: no cover - cleanup path
            self._log(f"Controller shutdown error: {exc}")

    def _stop_recorder(self) -> None:
        if not self.csv_recorder.is_active:
            return

        try:
            summary = self.csv_recorder.stop()
            if summary is not None:
                self._log(f"CSV closed: {summary.path} (rows={summary.rows_written})")
        except Exception as exc:  # pragma: no cover - cleanup path
            self._log(f"Recorder shutdown error: {exc}")

    def _table_text(self, row: int, column: int) -> str:
        item = self.channel_table.item(row, column)
        return item.text().strip() if item else ""

    def _detail_table_text(self, row: int, column: int) -> str:
        item = self.channel_detail_table.item(row, column)
        return item.text().strip() if item else ""

    def _set_channel_detail_row(
        self,
        row: int,
        *,
        module_number: int,
        sensor_port: int,
        channel: ChannelConfig | None,
    ) -> None:
        module_item = QTableWidgetItem(str(module_number))
        module_item.setFlags(Qt.ItemIsEnabled)
        module_item.setForeground(QColor("#E6EDF3"))
        self.channel_detail_table.setItem(row, 0, module_item)

        port_item = QTableWidgetItem(str(sensor_port))
        port_item.setFlags(Qt.ItemIsEnabled)
        port_item.setForeground(QColor("#E6EDF3"))
        self.channel_detail_table.setItem(row, 1, port_item)

        bridge_combo = QComboBox()
        bridge_combo.addItems(self.BRIDGE_TYPE_OPTIONS)
        bridge_combo.setCurrentText(channel.bridge_type if channel else self.BRIDGE_TYPE_OPTIONS[0])
        self.channel_detail_table.setCellWidget(row, 2, bridge_combo)

        excitation_edit = QLineEdit(f"{channel.excitation_voltage:.6g}" if channel else "5.0")
        excitation_edit.setAlignment(Qt.AlignCenter)
        self.channel_detail_table.setCellWidget(row, 3, excitation_edit)

        nominal_edit = QLineEdit(f"{channel.nominal_resistance_ohm:.6g}" if channel else "350.0")
        nominal_edit.setAlignment(Qt.AlignCenter)
        self.channel_detail_table.setCellWidget(row, 4, nominal_edit)

    def _channel_map_by_selection(
        self,
        channels: list[ChannelConfig],
    ) -> dict[tuple[int, int], ChannelConfig]:
        mapped: dict[tuple[int, int], ChannelConfig] = {}
        for index, channel in enumerate(channels):
            module_number, sensor_port = channel_selection_from_physical_channel(channel.physical_channel, index)
            mapped[(module_number, sensor_port)] = channel
        return mapped

    def _create_channel_toggle_button(self, *, module_number: int, sensor_port: int, enabled: bool) -> QPushButton:
        button = QPushButton()
        button.setCheckable(True)
        button.setChecked(enabled)
        button.setProperty("module_number", module_number)
        button.setProperty("sensor_port", sensor_port)
        button.setFixedHeight(24)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(lambda checked, b=button: self._handle_channel_toggle_clicked(b, checked))
        self._apply_channel_toggle_button_style(button, enabled)
        return button

    def _handle_channel_toggle_clicked(self, button: QPushButton, checked: bool) -> None:
        self._apply_channel_toggle_button_style(button, checked)
        if not self._restoring_preferences:
            self._save_window_preferences()

    def _apply_channel_toggle_button_style(self, button: QPushButton, enabled: bool) -> None:
        sensor_port = int(button.property("sensor_port"))
        if enabled:
            button.setText(f"P{sensor_port} ON")
            button.setStyleSheet(
                "QPushButton {"
                "font-size: 16px; font-weight: 800; color: #FFFFFF;"
                "background: #1F6FEB; border: 1px solid #1759BA; border-radius: 6px; padding: 0px 3px;"
                "}"
                "QPushButton:disabled { background: #274C80; color: #D6E7FF; }"
            )
        else:
            button.setText(f"P{sensor_port} OFF")
            button.setStyleSheet(
                "QPushButton {"
                "font-size: 16px; font-weight: 700; color: #9AA4AF;"
                "background: #1A2029; border: 1px solid #30363D; border-radius: 6px; padding: 0px 3px;"
                "}"
                "QPushButton:disabled { background: #161B22; color: #6E7681; }"
            )

    def _channel_toggle_enabled(self, row: int, sensor_port: int) -> bool:
        button = self.channel_table.cellWidget(row, sensor_port)
        return bool(isinstance(button, QPushButton) and button.isChecked())

    def _channel_detail_map_from_ui(self) -> dict[tuple[int, int], dict[str, float | str]]:
        details: dict[tuple[int, int], dict[str, float | str]] = {}
        for row in range(self.channel_detail_table.rowCount()):
            module_number = self._detail_table_int(row, 0, minimum=1, field_name="Detail module")
            sensor_port = self._detail_table_int(row, 1, minimum=1, maximum=4, field_name="Detail port")

            bridge_widget = self.channel_detail_table.cellWidget(row, 2)
            if not isinstance(bridge_widget, QComboBox):
                raise ValueError(f"Bridge type on detail row {row + 1} is unavailable.")

            details[(module_number, sensor_port)] = {
                "bridge_type": bridge_widget.currentText(),
                "excitation_voltage": self._detail_table_widget_float(row, 3, field_name="Excitation voltage"),
                "nominal_resistance_ohm": self._detail_table_widget_float(
                    row,
                    4,
                    field_name="Nominal resistance",
                ),
            }
        return details

    def _update_channel_table_height(self) -> None:
        header_height = max(28, self.channel_table.horizontalHeader().sizeHint().height())
        self.channel_table.horizontalHeader().setFixedHeight(header_height)
        frame_height = self.channel_table.frameWidth() * 2
        row_count = self.channel_table.rowCount()
        row_height = max(
            28,
            max(
                (button.sizeHint().height() for button in self.channel_toggle_buttons.values()),
                default=24,
            )
            + 4,
        )
        self.channel_table.verticalHeader().setDefaultSectionSize(row_height)
        for row in range(row_count):
            self.channel_table.setRowHeight(row, row_height)
        table_height = header_height + frame_height + sum(self.channel_table.rowHeight(row) for row in range(row_count))
        self.channel_table.setFixedHeight(table_height + 2)

    def _table_int(
        self,
        row: int,
        column: int,
        *,
        minimum: int,
        field_name: str,
        maximum: int | None = None,
    ) -> int:
        raw_value = self._table_text(row, column)
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} on row {row + 1} must be an integer.") from exc

        if value < minimum:
            raise ValueError(f"{field_name} on row {row + 1} must be {minimum} or higher.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{field_name} on row {row + 1} must be {maximum} or lower.")
        return value

    def _detail_table_int(
        self,
        row: int,
        column: int,
        *,
        minimum: int,
        field_name: str,
        maximum: int | None = None,
    ) -> int:
        raw_value = self._detail_table_text(row, column)
        try:
            value = int(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} on detail row {row + 1} must be an integer.") from exc

        if value < minimum:
            raise ValueError(f"{field_name} on detail row {row + 1} must be {minimum} or higher.")
        if maximum is not None and value > maximum:
            raise ValueError(f"{field_name} on detail row {row + 1} must be {maximum} or lower.")
        return value

    def _detail_table_widget_float(self, row: int, column: int, *, field_name: str) -> float:
        widget = self.channel_detail_table.cellWidget(row, column)
        if not isinstance(widget, QLineEdit):
            raise ValueError(f"{field_name} on detail row {row + 1} is unavailable.")

        raw_value = widget.text().strip()
        try:
            return float(raw_value)
        except ValueError as exc:
            raise ValueError(f"{field_name} on detail row {row + 1} must be a number.") from exc

    def _rebuild_gauges(self) -> None:
        while self.gauge_grid.count():
            item = self.gauge_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.gauges.clear()
        self._gauge_order.clear()
        active_gauges: list[tuple[int, int, int, ChannelConfig]] = []
        for channel_index, channel in enumerate(self.config.channels):
            if not channel.enabled:
                continue
            module_number, sensor_port = channel_selection_from_physical_channel(channel.physical_channel, channel_index)
            active_gauges.append((module_number, sensor_port, channel_index, channel))

        for module_number, sensor_port, channel_index, channel in sorted(active_gauges):
            gauge = ChannelGaugeWidget(
                channel.name,
                channel.physical_channel,
                channel.color,
                module_number=module_number,
                sensor_port=sensor_port,
            )
            self.gauges[channel_index] = gauge
            self._gauge_order.append(channel_index)

        self._relayout_gauges()
        if self.monitoring_layout_auto_fit:
            QTimer.singleShot(0, self._fit_monitor_panel_to_gauges)
        self._rebuild_plot_selectors()

    def _relayout_gauges(self) -> None:
        while self.gauge_grid.count():
            self.gauge_grid.takeAt(0)

        column_count = self._calculate_gauge_columns()
        self._gauge_columns_in_use = column_count

        for visible_index, channel_index in enumerate(self._gauge_order):
            self.gauge_grid.addWidget(
                self.gauges[channel_index],
                visible_index // column_count,
                visible_index % column_count,
            )

        for column in range(self.GAUGE_COLUMNS):
            self.gauge_grid.setColumnStretch(column, 1 if column < column_count else 0)

        row_count = max(1, (len(self._gauge_order) + column_count - 1) // column_count)
        for row in range(row_count + 1):
            self.gauge_grid.setRowStretch(row, 0)
        self.gauge_grid.setRowStretch(row_count, 1)
        self.gauge_content.updateGeometry()

    def _calculate_gauge_columns(self) -> int:
        if not self._gauge_order:
            return 1

        available_width = self.gauge_area.viewport().width() or self.monitor_panel.width()
        if available_width <= 0:
            return self.GAUGE_COLUMNS

        spacing = max(0, self.gauge_grid.horizontalSpacing())
        for columns in range(self.GAUGE_COLUMNS, 0, -1):
            usable_width = available_width - (spacing * max(0, columns - 1))
            if usable_width / columns >= ChannelGaugeWidget.CARD_MIN_WIDTH:
                return columns
        return 1

    def _fit_monitor_panel_to_gauges(self) -> None:
        gauge_count = len(self.gauges)
        column_count = max(1, self._gauge_columns_in_use)
        required_rows = max(1, (gauge_count + column_count - 1) // column_count)
        visible_rows = min(self.GAUGE_VISIBLE_ROWS, required_rows)
        card_height = max(
            (gauge.sizeHint().height() for gauge in self.gauges.values()),
            default=ChannelGaugeWidget.CARD_MIN_HEIGHT,
        )
        full_content_height = (required_rows * card_height) + (max(0, required_rows - 1) * self.gauge_grid.verticalSpacing())
        visible_content_height = (visible_rows * card_height) + (max(0, visible_rows - 1) * self.gauge_grid.verticalSpacing())
        self.gauge_content.setMinimumHeight(full_content_height)
        self.gauge_content.adjustSize()

        area_height = visible_content_height + (self.gauge_area.frameWidth() * 2) + 2
        self.gauge_area.setMinimumHeight(area_height)
        self.gauge_area.updateGeometry()

        panel_layout = self.monitor_panel.layout()
        layout_margins = panel_layout.contentsMargins()
        panel_frame_width = self.monitor_panel.style().pixelMetric(
            QStyle.PM_DefaultFrameWidth,
            None,
            self.monitor_panel,
        )
        title_height = self.monitor_panel.fontMetrics().height() + 6
        panel_height = (
            area_height
            + layout_margins.top()
            + layout_margins.bottom()
            + (panel_frame_width * 2)
            + title_height
            + 2
        )
        self.monitor_panel.setMinimumHeight(panel_height)

        splitter_sizes = self.monitoring_stack.sizes()
        total_height = sum(size for size in splitter_sizes if size > 0)
        if total_height <= 0:
            total_height = panel_height + 420

        graph_min_height = 180
        if total_height - panel_height >= graph_min_height:
            monitor_height = panel_height
        else:
            monitor_height = max(180, total_height - graph_min_height)
        plot_height = max(graph_min_height, total_height - monitor_height)
        self._applying_monitoring_fit = True
        try:
            self.monitoring_stack.setSizes([monitor_height, plot_height])
        finally:
            self._applying_monitoring_fit = False

    def _handle_monitoring_splitter_moved(self, *_args) -> None:
        if not self._restoring_preferences and not self._applying_monitoring_fit:
            self.monitoring_layout_auto_fit = False
        self._schedule_layout_refresh()
        self._save_window_preferences()

    def _compact_channel_label(self, channel: ChannelConfig, fallback_index: int) -> str:
        module_number, sensor_port = channel_selection_from_physical_channel(channel.physical_channel, fallback_index)
        return f"M{module_number} P{sensor_port}"

    def _rebuild_plot_selectors(self) -> None:
        previous_channel_states = {
            index: checkbox.isChecked() for index, checkbox in self.plot_checkboxes.items()
        }
        previous_resistance_state = (
            self.resistance_plot_checkbox.isChecked() if self.resistance_plot_checkbox is not None else True
        )
        previous_voltage_state = (
            self.voltage_plot_checkbox.isChecked() if self.voltage_plot_checkbox is not None else False
        )

        self._clear_layout_widgets(self.plot_mode_layout)
        self._clear_layout_widgets(self.plot_channel_layout)

        self.plot_checkboxes.clear()
        self.plot_mode_layout.addWidget(self._create_plot_selector_title("Values"))
        self.resistance_plot_checkbox = self._create_plot_checkbox("Resistance", checked=previous_resistance_state)
        self.voltage_plot_checkbox = self._create_plot_checkbox("Voltage", checked=previous_voltage_state)
        self.plot_mode_layout.addWidget(self.resistance_plot_checkbox)
        self.plot_mode_layout.addWidget(self.voltage_plot_checkbox)

        for index, channel in enumerate(self.config.channels):
            if not channel.enabled:
                continue
            checkbox = self._create_plot_checkbox(
                self._compact_channel_label(channel, index),
                checked=previous_channel_states.get(index, True),
            )
            checkbox.setToolTip(channel.name)
            self.plot_channel_layout.addWidget(checkbox)
            self.plot_checkboxes[index] = checkbox

        self._refresh_plot()

    def _create_plot_checkbox(self, text: str, *, checked: bool) -> QCheckBox:
        checkbox = QCheckBox(text)
        checkbox.setChecked(checked)
        checkbox.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        checkbox.setStyleSheet(
            "QCheckBox { color: #E6EDF3; font-weight: 600; spacing: 4px; }"
            "QCheckBox::indicator { width: 13px; height: 13px; }"
        )
        checkbox.toggled.connect(self._handle_plot_selector_changed)
        return checkbox

    def _handle_plot_selector_changed(self, _checked: bool) -> None:
        self._refresh_plot()

    def _create_plot_selector_box(self, *, flow: bool = False) -> tuple[QFrame, QLayout]:
        frame = QFrame()
        frame.setObjectName("plotSelectorBox")
        if flow:
            layout = FlowLayout(frame, margin=1, h_spacing=5, v_spacing=2)
        else:
            layout = QHBoxLayout(frame)
            layout.setContentsMargins(6, 1, 6, 1)
            layout.setSpacing(4)
        return frame, layout

    def _create_plot_selector_title(self, title: str) -> QLabel:
        title_label = QLabel(title)
        title_label.setObjectName("plotSelectorTitle")
        return title_label

    def _clear_layout_widgets(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def _active_channel_indices(self) -> list[int]:
        return [index for index, channel in enumerate(self.config.channels) if channel.enabled]

    def _refresh_runtime_summary(self) -> None:
        backend_text = "NI" if self.config.backend.lower() == "ni" else "SIM"
        self.backend_label.setText(f"Backend {backend_text}")
        self.active_channels_label.setText(f"Channels {len(self._active_channel_indices())}")
        self.export_summary_label.setText(self._summarize_path(self.config.export_directory))

    def _summarize_path(self, raw_path: str) -> str:
        normalized_path = normalize_runtime_path_value(raw_path)
        path = Path(normalized_path)
        if not path.is_absolute():
            return normalized_path.replace("/", "\\")
        parts = path.parts[-2:] if len(path.parts) >= 2 else path.parts
        return "\\".join(parts) if parts else raw_path

    def _update_runtime_controls(self) -> None:
        controller_exists = self.controller is not None
        is_running = bool(self.controller and self.controller.is_running)
        is_paused = bool(self.controller and self.controller.is_paused)
        has_active_highlight = self.active_highlight_start_s is not None

        if is_running and is_paused:
            state = "Paused"
        elif is_running:
            state = "Running"
        elif controller_exists:
            state = "Connected"
        else:
            state = "Idle"

        self.session_state_label.setText(f"Status {state}")
        self.connect_button.setEnabled(not is_running)
        self.start_button.setEnabled(not is_running)
        self.pause_button.setEnabled(is_running and not is_paused)
        self.resume_button.setEnabled(is_running and is_paused)
        self.stop_button.setEnabled(controller_exists)
        self.mark_start_button.setEnabled(is_running and not is_paused and not has_active_highlight)
        self.mark_stop_button.setEnabled(controller_exists and has_active_highlight)
        self.load_action.setEnabled(not is_running)
        self.save_action.setEnabled(not is_running)
        if has_active_highlight:
            start_text = f"{self.active_highlight_start_s:.3f}" if self.active_highlight_start_s is not None else "-"
            self.mark_state_label.setText(f"Marking {start_text}s")
        else:
            self.mark_state_label.setText(f"Marks {len(self.highlight_intervals)}")

        settings_locked = is_running
        self.channel_table.setEnabled(not settings_locked)
        self.channel_detail_table.setEnabled(not settings_locked)
        self.backend_combo.setEnabled(not settings_locked)
        self.acquisition_hz_edit.setEnabled(not settings_locked)
        self.display_hz_edit.setEnabled(not settings_locked)
        self.browse_button.setEnabled(not settings_locked)
        self.apply_button.setEnabled(not settings_locked)

    def _reset_history(self) -> None:
        history_size = max(100, int(self.config.sampling.history_seconds * self.config.sampling.display_update_hz))
        self.history = {
            index: deque(maxlen=history_size) for index, channel in enumerate(self.config.channels) if channel.enabled
        }
        self.latest_readings.clear()
        self.latest_elapsed_s = 0.0
        self._clear_highlight_intervals()
        self.plot_widget.clear()
        self.resistance_curves.clear()
        for item in list(self.voltage_viewbox.addedItems):
            self.voltage_viewbox.removeItem(item)
        self.voltage_curves.clear()

        for index, channel in enumerate(self.config.channels):
            if not channel.enabled:
                continue
            resistance_curve = self.plot_widget.plot([], [], pen=pg.mkPen(channel.color, width=2), name=channel.name)
            voltage_curve = pg.PlotDataItem(
                [],
                [],
                pen=pg.mkPen(channel.color, width=2, style=Qt.DashLine),
                symbol="o",
                symbolSize=4,
                symbolBrush=channel.color,
                symbolPen=channel.color,
            )
            self.voltage_viewbox.addItem(voltage_curve)
            self.resistance_curves[index] = resistance_curve
            self.voltage_curves[index] = voltage_curve

        self._refresh_plot()

    def _connect_backend(self) -> None:
        if not self._apply_ui_config():
            return
        try:
            if self.controller:
                self._dispose_controller()
            backend = self._make_backend(self.config)
            self.controller = AcquisitionController(backend, self.config.sampling.acquisition_hz)
            message = self.controller.connect()
            self._update_runtime_controls()
            self._log(message)
            self.statusBar().showMessage(message, 5000)
        except Exception as exc:  # pragma: no cover - GUI path
            self._dispose_controller()
            self._update_runtime_controls()
            self._show_error("Connection Failed", str(exc))

    def _make_backend(self, config: AppConfig):
        if config.backend == "simulation":
            return SimulatedBackend(config)
        if config.backend == "ni":
            return NiDaqBackend(config)
        raise RuntimeError(f"Unsupported backend: {config.backend}")

    def _prepare_measurement_session(self, started_at: datetime) -> tuple[Path, Path]:
        export_dir = resolve_runtime_path(self.config.export_directory)
        export_root_created = not export_dir.exists()
        export_dir.mkdir(parents=True, exist_ok=True)
        session_id = started_at.strftime("%Y%m%d_%H%M%S")
        session_dir = export_dir / f"measurement_{session_id}"
        session_dir_created = not session_dir.exists()
        session_dir.mkdir(parents=True, exist_ok=True)
        if export_root_created:
            self._log(f"Export root created: {export_dir}")
        else:
            self._log(f"Export root ready: {export_dir}")
        if session_dir_created:
            self._log(f"Session directory created: {session_dir}")
        else:
            self._log(f"Session directory ready: {session_dir}")
        return session_dir, session_dir / "measurement.csv"

    def _start_measurement(self) -> None:
        try:
            if not self._apply_ui_config():
                return
            if self.controller is None:
                self._connect_backend()
            if self.controller is None:
                return

            started_at = datetime.now()
            session_dir, csv_path = self._prepare_measurement_session(started_at)
            summary = self.csv_recorder.start(csv_path, self.config.channels)
            self._log(f"CSV initialized: {summary.path}")

            self._reset_history()
            self.controller.start()
            poll_ms = max(50, int(1000 / max(self.config.sampling.display_update_hz, 1.0)))
            self.poll_timer.start(poll_ms)
            self._update_runtime_controls()
            self._log(f"Measurement started: {session_dir}")
        except Exception as exc:  # pragma: no cover - GUI path
            self._stop_recorder()
            self._dispose_controller()
            self._update_runtime_controls()
            self._show_error("Start Failed", str(exc))

    def _pause_measurement(self) -> None:
        if self.controller and self.controller.is_running:
            self.controller.pause()
            self._update_runtime_controls()
            self._log("Measurement paused")

    def _resume_measurement(self) -> None:
        if self.controller and self.controller.is_running:
            self.controller.resume()
            self._update_runtime_controls()
            self._log("Measurement resumed")

    def _stop_measurement(self) -> None:
        self._close_active_highlight_interval()
        self.poll_timer.stop()
        self._dispose_controller()
        self._stop_recorder()
        self._update_runtime_controls()
        self._log("Measurement stopped")

    def _poll_samples(self) -> None:
        if not self.controller:
            return

        failure = self.controller.pop_failure()
        try:
            samples = self.controller.drain_samples()
            for sample in samples:
                self.csv_recorder.append(sample)
                self._process_sample(sample)
        except Exception as exc:  # pragma: no cover - GUI path
            self._handle_runtime_failure(exc)
            return

        if samples:
            self._refresh_displays()
        if failure is not None:
            self._handle_runtime_failure(failure)

    def _process_sample(self, sample: MeasurementSample) -> None:
        self.latest_elapsed_s = sample.elapsed_s
        if self.active_highlight_region is not None and self.active_highlight_start_s is not None:
            self.active_highlight_region.setRegion((self.active_highlight_start_s, self.latest_elapsed_s))
        for reading in sample.readings:
            self.latest_readings[reading.channel_index] = reading
            self.history[reading.channel_index].append(
                (sample.elapsed_s, reading.voltage, reading.resistance_ohm)
            )

    def _refresh_displays(self) -> None:
        for channel_index, gauge in self.gauges.items():
            gauge.update_reading(self.latest_readings.get(channel_index))

        self._refresh_plot()

    def _create_highlight_region(self, start_s: float, end_s: float) -> pg.LinearRegionItem:
        region = pg.LinearRegionItem(
            values=(start_s, end_s),
            orientation="vertical",
            movable=False,
            brush=pg.mkBrush(246, 193, 67, 45),
            pen=pg.mkPen("#F0C241", width=1),
            hoverBrush=pg.mkBrush(246, 193, 67, 55),
            hoverPen=pg.mkPen("#F0C241", width=1),
        )
        region.setZValue(-5)
        self.plot_widget.addItem(region)
        return region

    def _clear_highlight_intervals(self) -> None:
        for region in self.highlight_regions:
            try:
                self.plot_widget.removeItem(region)
            except Exception:
                pass
        if self.active_highlight_region is not None:
            try:
                self.plot_widget.removeItem(self.active_highlight_region)
            except Exception:
                pass
        self.highlight_intervals.clear()
        self.highlight_regions.clear()
        self.active_highlight_start_s = None
        self.active_highlight_region = None

    def _start_highlight_interval(self) -> None:
        if not self.controller or not self.controller.is_running or self.controller.is_paused:
            return
        if self.active_highlight_start_s is not None:
            return

        start_s = self.latest_elapsed_s
        self.active_highlight_start_s = start_s
        self.active_highlight_region = self._create_highlight_region(start_s, start_s)
        self._update_runtime_controls()
        self._log(f"Highlight start @ {start_s:.3f}s")

    def _close_active_highlight_interval(self) -> bool:
        if self.active_highlight_start_s is None or self.active_highlight_region is None:
            return False

        end_s = max(self.latest_elapsed_s, self.active_highlight_start_s)
        self.active_highlight_region.setRegion((self.active_highlight_start_s, end_s))
        self.highlight_intervals.append((self.active_highlight_start_s, end_s))
        self.highlight_regions.append(self.active_highlight_region)
        self._log(f"Highlight stop @ {end_s:.3f}s")
        self.active_highlight_start_s = None
        self.active_highlight_region = None
        self._update_runtime_controls()
        return True

    def _stop_highlight_interval(self) -> None:
        self._close_active_highlight_interval()

    def _refresh_plot(self) -> None:
        range_limit = self.VALUE_RANGES[self.range_combo.currentText()]
        show_resistance = self.resistance_plot_checkbox.isChecked() if self.resistance_plot_checkbox else True
        show_voltage = self.voltage_plot_checkbox.isChecked() if self.voltage_plot_checkbox else False

        if show_resistance:
            self.plot_widget.showAxis("left")
            self.plot_widget.setLabel("left", "Resistance", units="ohm", color="#C9D1D9")
        else:
            self.plot_widget.hideAxis("left")

        if show_voltage:
            self.plot_widget.showAxis("right")
            self.plot_widget.setLabel("right", "Voltage", units="V", color="#9EC1FF")
        else:
            self.plot_widget.hideAxis("right")

        for channel_index, resistance_curve in self.resistance_curves.items():
            checkbox = self.plot_checkboxes.get(channel_index)
            channel_enabled = checkbox.isChecked() if checkbox is not None else True
            voltage_curve = self.voltage_curves[channel_index]
            channel = self.config.channels[channel_index]

            resistance_curve.setVisible(channel_enabled and show_resistance)
            voltage_curve.setVisible(channel_enabled and show_voltage)

            if not channel_enabled:
                resistance_curve.setData([], [])
                voltage_curve.setData([], [])
                continue
            values = list(self.history[channel_index])
            if range_limit is not None and values:
                latest_elapsed = values[-1][0]
                values = [item for item in values if latest_elapsed - item[0] <= range_limit]

            x_values = [item[0] for item in values]
            resistance_values = [item[2] for item in values]
            voltage_values = [item[1] for item in values]
            resistance_curve.setData(
                x=x_values if show_resistance else [],
                y=resistance_values if show_resistance else [],
                symbol="o" if show_resistance and len(x_values) == 1 else None,
                symbolSize=7 if show_resistance and len(x_values) == 1 else None,
                symbolBrush=channel.color if show_resistance and len(x_values) == 1 else None,
                symbolPen=channel.color if show_resistance and len(x_values) == 1 else None,
            )
            voltage_curve.setData(
                x=x_values if show_voltage else [],
                y=voltage_values if show_voltage else [],
                symbol="o" if show_voltage else None,
                symbolSize=4 if show_voltage else None,
                symbolBrush=channel.color if show_voltage else None,
                symbolPen=channel.color if show_voltage else None,
            )

        self.plot_widget.getPlotItem().vb.autoRange()
        if show_voltage:
            self.voltage_viewbox.autoRange()

    def _sync_plot_views(self) -> None:
        plot_viewbox = self.plot_widget.getPlotItem().vb
        self.voltage_viewbox.setGeometry(plot_viewbox.sceneBoundingRect())
        self.voltage_viewbox.linkedViewChanged(plot_viewbox, self.voltage_viewbox.XAxis)

    def _handle_runtime_failure(self, exc: Exception) -> None:
        self._close_active_highlight_interval()
        self.poll_timer.stop()
        self._dispose_controller()
        self._stop_recorder()
        self._update_runtime_controls()
        self._show_error("Measurement Failed", str(exc))

    def _choose_export_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select CSV Export Directory",
            str(resolve_runtime_path(self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY)),
        )
        if selected:
            self.export_path_edit.setText(normalize_runtime_path_value(selected))
            self._apply_ui_config()

    def _load_config_dialog(self) -> None:
        if self.controller and self.controller.is_running:
            self._show_error("Load Blocked", "Stop the measurement before loading a different configuration.")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Config",
            str(self.config_path.parent if self.config_path.exists() else DEFAULT_CONFIG_PATH.parent),
            "JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            self.config_path = resolve_runtime_path(file_path)
            self.config = load_config(self.config_path)
            self._load_config_into_widgets(self.config)
            self._rebuild_gauges()
            self._reset_history()
            self._log(f"Loaded config: {self.config_path}")
        except Exception as exc:
            self._show_error("Load Failed", str(exc))

    def _save_config_dialog(self) -> None:
        if self.controller and self.controller.is_running:
            self._show_error("Save Blocked", "Stop the measurement before saving configuration changes.")
            return
        if not self._apply_ui_config():
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Config",
            str(self.config_path),
            "JSON Files (*.json)",
        )
        if not file_path:
            return

        try:
            self.config_path = resolve_runtime_path(file_path)
            save_config(self.config_path, self.config)
            self._log(f"Saved config: {self.config_path}")
        except Exception as exc:
            self._show_error("Save Failed", str(exc))

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")

    def _show_error(self, title: str, message: str) -> None:
        self._log(f"{title}: {message}")
        QMessageBox.critical(self, title, message)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._schedule_layout_refresh()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.gauge_area.viewport() and event.type() == QEvent.Resize:
            self._schedule_layout_refresh()
        return super().eventFilter(watched, event)

    def _schedule_layout_refresh(self, *_args) -> None:
        if self._pending_layout_refresh:
            return
        self._pending_layout_refresh = True
        QTimer.singleShot(0, self._refresh_responsive_layout)

    def _refresh_responsive_layout(self) -> None:
        self._pending_layout_refresh = False
        next_columns = self._calculate_gauge_columns()
        if next_columns != self._gauge_columns_in_use:
            self._relayout_gauges()
        if self.monitoring_layout_auto_fit:
            self._fit_monitor_panel_to_gauges()

    def _restore_window_preferences(self) -> None:
        self._restoring_preferences = True
        self.settings.beginGroup(self.SETTINGS_GROUP)
        geometry = self.settings.value("geometry")
        was_maximized = self.settings.value("maximized", None)

        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.showMaximized()

        self._restore_splitter_sizes(self.workspace_splitter, "workspace_splitter")
        monitoring_restored = self._restore_splitter_sizes(self.monitoring_stack, "monitoring_stack")
        self._restore_splitter_sizes(self.side_stack, "side_stack")
        channels_restored = self._restore_channel_toggle_preferences()

        if was_maximized is not None and str(was_maximized).lower() == "true":
            self.showMaximized()
        self.settings.endGroup()
        self._restoring_preferences = False

        if channels_restored:
            self.config = self._config_from_ui()
            self._refresh_runtime_summary()
            self._rebuild_gauges()
            self._reset_history()
            self._refresh_displays()
            self._update_runtime_controls()

        self.monitoring_layout_auto_fit = not monitoring_restored
        if self.monitoring_layout_auto_fit:
            QTimer.singleShot(0, self._fit_monitor_panel_to_gauges)

    def _restore_splitter_sizes(self, splitter: QSplitter, key: str) -> bool:
        sizes = self.settings.value(key)
        if not sizes:
            return False

        restored_sizes = [int(size) for size in sizes]
        if len(restored_sizes) == splitter.count():
            splitter.setSizes(restored_sizes)
            return True
        return False

    def _save_window_preferences(self, *_args) -> None:
        self.settings.beginGroup(self.SETTINGS_GROUP)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("maximized", self.isMaximized())
        self.settings.setValue("workspace_splitter", self.workspace_splitter.sizes())
        self.settings.setValue("monitoring_stack", self.monitoring_stack.sizes())
        self.settings.setValue("side_stack", self.side_stack.sizes())
        self.settings.setValue(
            "channel_enabled",
            json.dumps(self._collect_channel_toggle_preferences(), separators=(",", ":")),
        )
        self.settings.endGroup()
        self.settings.sync()

    def _collect_channel_toggle_preferences(self) -> dict[str, bool]:
        preferences: dict[str, bool] = {}
        for row in range(self.channel_table.rowCount()):
            module_number = self._table_int(row, 0, minimum=1, field_name="Module")
            for sensor_port in range(1, 5):
                preferences[f"{module_number}:{sensor_port}"] = self._channel_toggle_enabled(row, sensor_port)
        return preferences

    def _restore_channel_toggle_preferences(self) -> bool:
        raw_preferences = self.settings.value("channel_enabled")
        if not raw_preferences:
            return False

        try:
            saved_preferences = json.loads(str(raw_preferences))
        except json.JSONDecodeError:
            return False

        restored = False
        for row in range(self.channel_table.rowCount()):
            module_number = self._table_int(row, 0, minimum=1, field_name="Module")
            for sensor_port in range(1, 5):
                key = f"{module_number}:{sensor_port}"
                if key not in saved_preferences:
                    continue
                button = self.channel_table.cellWidget(row, sensor_port)
                if not isinstance(button, QPushButton):
                    continue
                checked = bool(saved_preferences[key])
                button.setChecked(checked)
                self._apply_channel_toggle_button_style(button, checked)
                restored = True
        return restored
