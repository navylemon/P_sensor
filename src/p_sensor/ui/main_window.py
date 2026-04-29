from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import replace
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
from typing import Any, Callable

import numpy as np
import pyqtgraph as pg
try:
    import pyqtgraph.opengl as gl
except Exception:  # pragma: no cover - optional OpenGL runtime dependency
    gl = None
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction, QColor, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from p_sensor import __version__
from p_sensor.acquisition import AcquisitionController, NiDaqBackend, SimulatedBackend
from p_sensor.automation import (
    AutomationCancelledError,
    AutomationProgressEstimator,
    AutomationSafetyPolicy,
    AutomationSessionOptions,
    ExperimentRunner,
    NoOpCommandBridge,
    ProgressEstimatorConfig,
    load_recipe,
    recipe_from_dict,
    save_recipe,
)
from p_sensor.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_EXPORT_DIRECTORY,
    build_physical_channel,
    config_to_dict,
    load_config,
    normalize_runtime_path_value,
    resolve_runtime_path,
    save_config,
    validate_app_config,
)
from p_sensor.motion import ShotCommandBridge, create_shot_controller, is_simulated_motion_config
from p_sensor.models import (
    AnalogInputChannelConfig,
    AnalogInputReading,
    AnalogOutputChannelConfig,
    AnalogOutputState,
    AppConfig,
    MeasurementSample,
    MeasurementFrame,
    SamplingConfig,
)
from p_sensor.profiles import AppProfile, IO_APP_PROFILE
from p_sensor.services import MeasurementService
from p_sensor.storage import CsvRecorder, prepare_session_paths
from p_sensor.ui.compact_stage_panel import CompactStagePanel
from p_sensor.ui.contact_calibration_dialog import ContactCalibrationDialog, ContactCalibrationResult
from p_sensor.ui.protocol_panel import ProtocolPanel
from p_sensor.ui.recipe_helper_dialog import RecipeHelperDialog
from p_sensor.ui.safety_panel import SafetyPanel
from p_sensor.ui.tool_dialogs import (
    ChannelConfigManagerDialog,
    MarkerManagerDialog,
    RecipeWizardDialog,
    SetupSummaryDialog,
)


class MainWindow(QMainWindow):
    SETTINGS_GROUP = "main_window"
    MAX_LOG_BLOCKS = 2000
    PLOT_ASPECT_WIDTH = 2
    PLOT_ASPECT_HEIGHT = 1
    CHANNEL_TABLE_ROW_HEIGHT = 28
    CHANNEL_CELL_WIDGET_HEIGHT = 22
    RANGE_OPTIONS = {"10 s": 10.0, "60 s": 60.0, "180 s": 180.0, "All": None}
    TONE_STYLES = {
        "neutral": "background: #161B22; border: 1px solid #30363D; color: #E6EDF3;",
        "running": "background: #0F2D2A; border: 1px solid #2EA043; color: #D2F4DF;",
        "warning": "background: #35270F; border: 1px solid #D29922; color: #F8E3B1;",
        "error": "background: #3A1F24; border: 1px solid #F85149; color: #FFD8D4;",
        "info": "background: #152238; border: 1px solid #2F81F7; color: #D8E9FF;",
        "muted": "background: #11151B; border: 1px solid #30363D; color: #9BA7B4;",
    }
    READINESS_STEPS = (
        ("daq_device", "1 DAQ Dev"),
        ("daq_backend", "2 DAQ Backend"),
        ("daq_signal", "3 DAQ Signal"),
        ("stage_device", "4 Stage Dev"),
        ("stage_backend", "5 Stage Backend"),
        ("stage_signal", "6 Stage Signal"),
        ("storage", "7 Storage"),
    )

    def __init__(self, config: AppConfig, config_path: Path, profile: AppProfile = IO_APP_PROFILE) -> None:
        super().__init__()
        self.profile = profile
        self._startup_maximize_pending = True
        self.setWindowTitle(profile.window_title)
        if profile.supports_analog_output:
            self.resize(1660, 980)
        else:
            self.resize(1520, 940)

        self.config = self._config_for_profile(config)
        self.config_path = config_path
        self.csv_recorder = CsvRecorder()
        self.controller: AcquisitionController | None = None
        self.settings = QSettings()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_frames)
        self.automation_timer = QTimer(self)
        self.automation_timer.timeout.connect(self._poll_automation_events)

        self.automation_recipe_path: Path | None = None
        self.automation_recipe = None
        self.motion_config_path: Path | None = None
        self.motion_config = None
        self.automation_thread: threading.Thread | None = None
        self.automation_stop_event = threading.Event()
        self.automation_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.automation_live_frames: queue.Queue[MeasurementFrame] = queue.Queue()
        self.automation_last_result = None
        self.automation_started_at: datetime | None = None
        self.automation_progress_estimator: AutomationProgressEstimator | None = None
        self.automation_completed_steps = 0
        self.automation_current_step_index: int | None = None
        self.automation_current_phase = ""
        self.automation_phase_started_at: datetime | None = None

        self.latest_inputs: dict[int, AnalogInputReading] = {}
        self.latest_outputs: dict[int, AnalogOutputState] = {}
        self.latest_elapsed_s = 0.0
        self.history: dict[int, deque[tuple[float, float, float]]] = {}
        self.output_history: dict[int, deque[tuple[float, float]]] = {}
        self.input_curves: dict[int, pg.PlotDataItem] = {}
        self.output_curves: dict[int, pg.PlotDataItem] = {}
        self.ai_color_by_row: list[str] = []
        self.ai_card_widgets: dict[int, tuple[QLabel, QLabel, QLabel, QCheckBox]] = {}
        self.ao_card_widgets: dict[int, tuple[QLabel, QLabel, QLabel, QCheckBox]] = {}
        self.highlight_intervals: list[tuple[float, float]] = []
        self.highlight_regions: list[pg.LinearRegionItem] = []
        self.highlight_markers: list[dict[str, Any]] = []
        self.active_highlight_start_s: float | None = None
        self.active_highlight_region: pg.LinearRegionItem | None = None
        self.stage_positions_mm: dict[int, float | None] = {1: None, 2: None}
        self.stage_motion_elapsed_s = 0.0
        self.stage_motion_started_at: datetime | None = None
        self.stage_position_history: deque[tuple[float, float | None, float | None]] = deque(maxlen=2000)
        self.stage_plot_active_axis: int | None = None
        self.stage_mark_items: list[pg.ScatterPlotItem] = []
        self.stage_markers: list[dict[str, Any]] = []
        self.contact_point_position_mm: float | None = None

        self.ai_enabled_checks: list[QCheckBox] = []
        self.ai_name_items: list[QTableWidgetItem] = []
        self.ai_physical_items: list[QTableWidgetItem] = []
        self.ai_mode_combos: list[QComboBox] = []
        self.ai_scale_spins: list[QDoubleSpinBox] = []
        self.ai_offset_spins: list[QDoubleSpinBox] = []
        self.ai_unit_items: list[QTableWidgetItem] = []
        self.ai_voltage_items: list[QTableWidgetItem] = []
        self.ai_value_items: list[QTableWidgetItem] = []
        self.ai_status_items: list[QTableWidgetItem] = []
        self.ai_plot_checks: list[QCheckBox] = []

        self.ao_enabled_checks: list[QCheckBox] = []
        self.ao_name_items: list[QTableWidgetItem] = []
        self.ao_physical_items: list[QTableWidgetItem] = []
        self.ao_min_spins: list[QDoubleSpinBox] = []
        self.ao_max_spins: list[QDoubleSpinBox] = []
        self.ao_initial_spins: list[QDoubleSpinBox] = []
        self.ao_setpoint_spins: list[QDoubleSpinBox] = []
        self.ao_live_items: list[QTableWidgetItem] = []
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMinimumWidth(0)
        self.log_output.document().setMaximumBlockCount(self.MAX_LOG_BLOCKS)
        self._detail_section_toggles: dict[str, QPushButton] = {}
        self._detail_section_actions: dict[str, QAction] = {}

        self._apply_visual_style()
        self._build_menu()
        self._build_ui()
        self._init_compatibility_widgets()
        self._load_config_into_widgets(self.config)
        self._restore_window_preferences()
        self._reset_history()
        self._refresh_runtime_summary()
        self._update_runtime_controls()
        self._log("Application initialized")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save_window_preferences()
        self._request_stop_automation(wait=True)
        if hasattr(self, "stage_panel"):
            self.stage_panel.disconnect_stage()
        self._stop_measurement()
        super().closeEvent(event)

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        if self._startup_maximize_pending and not event.spontaneous():
            self._startup_maximize_pending = False
            QTimer.singleShot(0, self._ensure_startup_maximized)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        if hasattr(self, "plot_widget") or hasattr(self, "stage_plot_stack"):
            QTimer.singleShot(0, self._apply_plot_section_geometry)
        if hasattr(self, "channel_controls_panel"):
            QTimer.singleShot(0, self._sync_channel_controls_geometry)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        load_action = QAction("Load Config", self)
        save_action = QAction("Save Config", self)
        quit_action = QAction("Quit", self)
        load_action.triggered.connect(self._load_config_dialog)
        save_action.triggered.connect(self._save_config_dialog)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(load_action)
        file_menu.addAction(save_action)
        file_menu.addSeparator()
        file_menu.addAction(quit_action)

        tools_menu = self.menuBar().addMenu("Tools")
        action_specs = (
            ("Setup Summary / Diagnostics", self._open_setup_summary_dialog),
            ("Contact Calibration", self._open_contact_calibration_dialog),
            ("Recipe Wizard", self._open_recipe_wizard_dialog),
            ("Channel Config Manager", self._open_channel_config_manager_dialog),
            ("Marker Manager", self._open_marker_manager_dialog),
        )
        for title, handler in action_specs:
            action = QAction(title, self)
            action.triggered.connect(handler)
            tools_menu.addAction(action)
            self._detail_section_actions[title] = action

    def _supports_analog_output(self) -> bool:
        return self.profile.supports_analog_output

    def _fallback_ao_slot(self, ai_module_slot: int) -> int:
        return 2 if ai_module_slot != 2 else 1

    def _chassis_name_text(self) -> str:
        widget = getattr(self, "chassis_name_edit", None)
        if isinstance(widget, QComboBox):
            return widget.currentText().strip()
        if isinstance(widget, QLineEdit):
            return widget.text().strip()
        return ""

    def _set_chassis_name_text(self, chassis_name: str) -> None:
        cleaned = chassis_name.strip() or "cDAQ1"
        widget = getattr(self, "chassis_name_edit", None)
        if isinstance(widget, QComboBox):
            if widget.findText(cleaned) < 0:
                widget.addItem(cleaned, cleaned)
            widget.setCurrentText(cleaned)
            return
        if isinstance(widget, QLineEdit):
            widget.setText(cleaned)

    def _available_daq_devices(self) -> list[tuple[str, str]]:
        try:
            from nidaqmx.system import System
        except Exception:
            return []

        devices: list[tuple[str, str]] = []
        try:
            for device in System.local().devices:
                name = str(getattr(device, "name", "") or "").strip()
                if not name:
                    continue
                product_type = str(getattr(device, "product_type", "") or "").strip()
                description = f"{name} ({product_type})" if product_type else name
                devices.append((name, description))
        except Exception:
            return []
        return sorted(devices, key=lambda item: item[0].upper())

    def _refresh_daq_device_choices(self, preferred_device: str | None = None) -> None:
        widget = getattr(self, "chassis_name_edit", None)
        if not isinstance(widget, QComboBox):
            return

        selected = str(preferred_device or widget.currentText() or "cDAQ1").strip() or "cDAQ1"
        blocked = widget.blockSignals(True)
        widget.clear()
        if self.backend_combo.currentText() != "ni":
            widget.addItem(selected, selected)
            widget.setCurrentText(selected)
            widget.setToolTip("Simulation backend uses this name only for generated channel labels.")
            widget.blockSignals(blocked)
            self._sync_physical_channels()
            return

        discovered_devices = self._available_daq_devices()
        if not discovered_devices:
            widget.addItem(selected, selected)
        for name, description in discovered_devices:
            widget.addItem(name, name)
            widget.setItemData(widget.count() - 1, description, role=Qt.ItemDataRole.ToolTipRole)
        if selected and widget.findText(selected) < 0:
            widget.insertItem(0, selected, selected)
        widget.setCurrentText(selected)
        widget.setToolTip("Select the NI-DAQmx device/chassis name. Use Devices after reconnecting USB.")
        widget.blockSignals(blocked)
        self._sync_physical_channels()

    def _handle_daq_backend_changed(self) -> None:
        self._refresh_daq_device_choices()
        self._refresh_runtime_summary()
        self._update_runtime_controls()

    def _config_for_profile(self, config: AppConfig) -> AppConfig:
        if self._supports_analog_output():
            return config
        return AppConfig(
            backend=config.backend,
            chassis_name=config.chassis_name,
            ai_module_slot=config.ai_module_slot,
            ao_module_slot=(
                config.ao_module_slot
                if config.ao_module_slot != config.ai_module_slot
                else self._fallback_ao_slot(config.ai_module_slot)
            ),
            export_directory=config.export_directory,
            sampling=config.sampling,
            ai_channels=config.ai_channels,
            ao_channels=[],
        )

    def _build_ui(self) -> None:
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(4, 4, 4, 4)
        central_layout.setSpacing(3)
        central_layout.addWidget(self._build_status_bar())

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.measurement_workspace = self._build_measurement_workspace()
        self.measurement_workspace_scroll = self._wrap_workspace_scroll(self.measurement_workspace)
        self.right_status_section = self._build_right_status_section()
        self.right_status_scroll = self._wrap_workspace_scroll(self.right_status_section)
        self.workspace_splitter.addWidget(self.measurement_workspace_scroll)
        self.workspace_splitter.addWidget(self.right_status_scroll)
        self.workspace_splitter.setStretchFactor(0, 8)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setSizes(self._default_workspace_splitter_sizes())
        self.workspace_splitter.splitterMoved.connect(self._save_window_preferences)
        central_layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(central)
        self.cockpit_panel = self.workspace_splitter
        self._build_legacy_layout_compatibility_groups()
        self._hidden_results_group = self._build_results_group()
        self._hidden_results_group.hide()

    def _wrap_workspace_scroll(self, content: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(content)
        return scroll

    def _build_legacy_layout_compatibility_groups(self) -> None:
        self._legacy_layout_groups: list[QGroupBox] = []
        parent = self.workspace_splitter.widget(1) if self.workspace_splitter.count() >= 2 else self.cockpit_panel
        for title in ("Recipe", "Run", "Motion", "Protocol", "Results"):
            group = QGroupBox(title, parent)
            height_hint = group.sizeHint().height()
            if height_hint >= 0:
                group.setFixedHeight(height_hint)
            group.hide()
            self._legacy_layout_groups.append(group)

    def _apply_visual_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #0D1117;
            }
            QWidget {
                font-family: "Segoe UI", "Malgun Gothic", Arial, sans-serif;
            }
            QGroupBox {
                background: #0F141B;
                border: 1px solid #30363D;
                border-radius: 4px;
                margin-top: 10px;
                font-weight: 700;
                font-size: 12px;
                color: #E6EDF3;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 5px;
                padding: 0 2px;
                color: #F0F6FC;
            }
            QGroupBox#DaqSection {
                border-bottom-left-radius: 0px;
                border-bottom-right-radius: 0px;
                border-bottom: 0px;
            }
            QGroupBox#DaqChannelShelf {
                background: #0F141B;
                border-top-left-radius: 0px;
                border-top-right-radius: 0px;
                margin-top: 0px;
            }
            QLabel {
                color: #D0D7DE;
                font-size: 12px;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTableWidget {
                background: #11161D;
                color: #E6EDF3;
                border: 1px solid #30363D;
                border-radius: 4px;
                selection-background-color: #1F6FEB;
                selection-color: #FFFFFF;
                font-size: 12px;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
                min-height: 21px;
                padding: 0px 3px;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QPushButton {
                background: #1A2330;
                color: #E6EDF3;
                border: 1px solid #314158;
                border-radius: 4px;
                min-height: 19px;
                min-width: 0px;
                padding: 0px 3px;
                font-weight: 600;
                font-size: 12px;
            }
            QPushButton:hover {
                background: #223049;
            }
            QPushButton:disabled {
                background: #14181E;
                color: #6E7681;
                border: 1px solid #2A2F36;
            }
            QProgressBar {
                background: #11161D;
                color: #E6EDF3;
                border: 1px solid #30363D;
                border-radius: 4px;
                text-align: center;
                min-height: 18px;
            }
            QProgressBar::chunk {
                background: #1F6FEB;
                border-radius: 3px;
            }
            QHeaderView::section {
                background: #161B22;
                color: #C9D1D9;
                border: none;
                border-right: 1px solid #30363D;
                border-bottom: 1px solid #30363D;
                padding: 2px 4px;
                font-weight: 700;
                font-size: 12px;
            }
            QTableWidget {
                gridline-color: #26303A;
                alternate-background-color: #0F141B;
            }
            QTableWidget::item {
                padding: 1px;
            }
            """
        )

    def _init_compatibility_widgets(self) -> None:
        self.resistance_plot_checkbox = QCheckBox()
        self.resistance_plot_checkbox.setChecked(True)
        self.voltage_plot_checkbox = QCheckBox()
        self.voltage_plot_checkbox.setChecked(True)
        self.resistance_curves: dict[int, pg.PlotDataItem] = {}
        self.voltage_curves: dict[int, pg.PlotDataItem] = {}
        self.channel_table = QTableWidget()
        self.channel_table.setColumnCount(2)
        self.channel_detail_table = QTableWidget()
        self.channel_detail_table.setColumnCount(5)

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(4, 3, 4, 3)
        layout.setSpacing(4)
        self.session_state_label = QLabel("Disconnected")
        self.stage_state_label = QLabel("Stage Disconnected")
        self.backend_state_label = QLabel("Backend simulation")
        self.channel_summary_label = QLabel(
            "AI 0 / AO 0" if self._supports_analog_output() else f"{self._input_summary_prefix()} 0"
        )
        self.export_state_label = QLabel(DEFAULT_EXPORT_DIRECTORY)
        version_label = QLabel(f"v{__version__}")
        for widget in (
            self.session_state_label,
            self.stage_state_label,
            self.backend_state_label,
            self.channel_summary_label,
            self.export_state_label,
            version_label,
        ):
            self._set_badge_style(widget, tone="neutral")
        self._set_badge_style(self.stage_state_label, tone="muted")
        self.readiness_labels: dict[str, QLabel] = {}
        layout.addWidget(self.session_state_label)
        for key, label_text in self.READINESS_STEPS:
            label = QLabel(f"{label_text} Pending")
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self._set_badge_style(label, tone="muted")
            self.readiness_labels[key] = label
            layout.addWidget(label, 1)
        layout.addWidget(version_label)
        return bar

    def _build_measurement_workspace(self) -> QWidget:
        workspace = QWidget()
        workspace.setMinimumWidth(0)
        layout = QGridLayout(workspace)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(2)
        self.measurement_workspace_layout = layout

        self.daq_section = self._build_daq_section(include_channels=False)
        self.stage_section = self._build_stage_section()
        self.channel_controls_panel = self._build_channel_controls()
        self.channel_controls_panel.setMinimumHeight(86)
        self.channel_controls_panel.setMaximumHeight(118)

        layout.addWidget(self.daq_section, 0, 0)
        layout.addWidget(self.stage_section, 0, 1)
        layout.addWidget(self.channel_controls_panel, 1, 0, 1, 2)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        layout.setRowStretch(0, 1)
        layout.setRowStretch(1, 0)
        return workspace

    def _build_daq_section(self, *, include_channels: bool = True) -> QWidget:
        section = QGroupBox("DAQ")
        section.setObjectName("DaqSection")
        section.setMinimumWidth(0)
        section.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignTop)
        plot_group = self._build_plot_group()
        plot_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(plot_group, 1)
        layout.addWidget(self._build_monitor_group(), 0)
        layout.addWidget(self._build_daq_control_group(), 0)
        if include_channels:
            layout.addWidget(self._build_channel_controls(), 1)
        return section

    def _build_daq_control_group(self) -> QWidget:
        group = QGroupBox("DAQ Control")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(1)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["simulation", "ni"])
        self.backend_combo.currentTextChanged.connect(self._handle_daq_backend_changed)
        self.chassis_name_edit = QComboBox()
        self.chassis_name_edit.setEditable(True)
        self.chassis_name_edit.setMinimumWidth(110)
        self.chassis_name_edit.setToolTip("Select or type the NI-DAQmx device/chassis name.")
        self.chassis_name_edit.currentTextChanged.connect(self._sync_physical_channels)
        self.refresh_daq_devices_button = QPushButton("Devices")
        self.refresh_daq_devices_button.setToolTip("Refresh NI-DAQmx device names such as cDAQ1 or Dev1.")
        self.refresh_daq_devices_button.clicked.connect(lambda _checked=False: self._refresh_daq_device_choices())
        self.ai_slot_spin = QSpinBox()
        self.ai_slot_spin.setRange(1, 4)
        self.ai_slot_spin.valueChanged.connect(self._sync_physical_channels)
        self.ao_slot_spin = QSpinBox()
        self.ao_slot_spin.setRange(1, 4)
        self.ao_slot_spin.valueChanged.connect(self._sync_physical_channels)
        self.acquisition_hz_spin = self._new_double_spin(1.0, 5000.0, 1, 20.0, 1.0)
        self.display_hz_spin = self._new_double_spin(1.0, 100.0, 1, 10.0, 1.0)
        self.history_seconds_spin = QSpinBox()
        self.history_seconds_spin.setRange(10, 3600)
        self.history_seconds_spin.setSingleStep(10)
        self.session_label_edit = QLineEdit()
        self.session_label_edit.setPlaceholderText("Session label")
        self.export_path_edit = QLineEdit()
        self.export_path_edit.setReadOnly(True)
        self.csv_save_interval_spin = self._new_double_spin(0.1, 60.0, 1, 1.0, 0.5)
        self.csv_save_interval_spin.setToolTip("CSV flush interval in seconds for Record Measurement.")
        self.browse_export_button = QPushButton("Browse")
        self.browse_export_button.clicked.connect(self._choose_export_directory)

        self.connect_button = QPushButton("Connect")
        self.monitor_button = QPushButton("Monitor")
        self.start_button = QPushButton("Record")
        self.stop_button = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.apply_outputs_button = QPushButton("Apply AO")
        self.zero_outputs_button = QPushButton("Zero AO")
        self.connect_button.clicked.connect(self._connect_backend)
        self.monitor_button.clicked.connect(self._start_live_monitor)
        self.start_button.clicked.connect(self._start_measurement)
        self.stop_button.clicked.connect(self._stop_measurement)
        self.pause_button.clicked.connect(self._pause_measurement)
        self.resume_button.clicked.connect(self._resume_measurement)
        self.apply_outputs_button.clicked.connect(self._apply_outputs)
        self.zero_outputs_button.clicked.connect(self._zero_outputs)
        for widget in (
            self.backend_combo,
            self.chassis_name_edit,
            self.ai_slot_spin,
            self.ao_slot_spin,
            self.acquisition_hz_spin,
            self.display_hz_spin,
            self.history_seconds_spin,
            self.csv_save_interval_spin,
            self.session_label_edit,
            self.export_path_edit,
            self.refresh_daq_devices_button,
            self.browse_export_button,
            self.connect_button,
            self.monitor_button,
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.stop_button,
            self.apply_outputs_button,
            self.zero_outputs_button,
        ):
            if hasattr(widget, "setMinimumHeight"):
                widget.setMinimumHeight(19)
            if hasattr(widget, "setMaximumHeight"):
                widget.setMaximumHeight(19)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(1)
        grid.addWidget(self._build_run_field("Backend", self.backend_combo), 0, 0)
        grid.addWidget(self._build_run_field("DAQ Device", self.chassis_name_edit), 0, 1)
        grid.addWidget(self._build_run_field("AI Slot", self.ai_slot_spin), 0, 2)
        if self._supports_analog_output():
            grid.addWidget(self._build_run_field("AO Slot", self.ao_slot_spin), 0, 3)
        grid.addWidget(self.refresh_daq_devices_button, 0, 4, Qt.AlignBottom)
        grid.addWidget(self._build_run_field("Acq Hz", self.acquisition_hz_spin), 1, 0)
        grid.addWidget(self._build_run_field("Disp Hz", self.display_hz_spin), 1, 1)
        grid.addWidget(self._build_run_field("History s", self.history_seconds_spin), 1, 2)
        grid.addWidget(self._build_run_field("CSV s", self.csv_save_interval_spin), 1, 3)
        layout.addLayout(grid)

        export_row = QHBoxLayout()
        export_row.setContentsMargins(0, 0, 0, 0)
        export_row.setSpacing(2)
        export_row.addWidget(self._build_run_field("Session", self.session_label_edit), 1)
        export_row.addWidget(self._build_run_field("Export Folder", self.export_path_edit), 2)
        export_row.addWidget(self.browse_export_button, 0, Qt.AlignBottom)
        layout.addLayout(export_row)

        buttons = QGridLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setHorizontalSpacing(2)
        buttons.setVerticalSpacing(2)
        buttons.addWidget(self.connect_button, 0, 0)
        buttons.addWidget(self.monitor_button, 0, 1)
        buttons.addWidget(self.start_button, 0, 2)
        buttons.addWidget(self.pause_button, 0, 3)
        buttons.addWidget(self.resume_button, 0, 4)
        buttons.addWidget(self.stop_button, 0, 5)
        if self._supports_analog_output():
            buttons.addWidget(self.apply_outputs_button, 1, 0)
            buttons.addWidget(self.zero_outputs_button, 1, 1)
        layout.addLayout(buttons)
        return group

    def _build_stage_section(self) -> QWidget:
        section = QGroupBox("Stage")
        section.setMinimumWidth(0)
        section.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        layout = QVBoxLayout(section)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        layout.setAlignment(Qt.AlignTop)
        stage_plot_group = self._build_stage_plot_group()
        stage_plot_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(stage_plot_group, 1)
        layout.addWidget(self._build_stage_dashboard_group(), 0)
        stage_group = self._build_stage_group()
        stage_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(stage_group, 0)
        self._hidden_safety_group = self._build_safety_group()
        self._hidden_safety_group.hide()
        stage_safety_strip = self._build_stage_safety_strip()
        stage_safety_strip.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(stage_safety_strip, 0)
        orchestration_controls = self._build_orchestration_control_group()
        orchestration_controls.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(orchestration_controls, 0)
        self._refresh_motion_config_control_summary()
        return section

    def _build_stage_plot_group(self) -> QWidget:
        group = QGroupBox("Stage Plot")
        self.stage_plot_group = group
        group.setMinimumWidth(0)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.stage_plot_mode_label = QLabel("Position vs move time")
        self.stage_plot_mode_label.setMinimumWidth(0)
        self.stage_plot_mode_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._set_badge_style(self.stage_plot_mode_label, tone="muted")
        self.stage_mark_start_button = QPushButton("Start Mark")
        self.stage_mark_stop_button = QPushButton("Stop Mark")
        self.stage_plot_clear_button = QPushButton("Clear")
        self.stage_mark_state_label = QLabel("Marks 0")
        self._set_badge_style(self.stage_mark_state_label, tone="muted")
        self.stage_mark_start_button.setMaximumWidth(92)
        self.stage_mark_stop_button.setMaximumWidth(92)
        self.stage_plot_clear_button.setMaximumWidth(64)
        self.stage_mark_state_label.setMaximumWidth(86)
        self.stage_mark_start_button.clicked.connect(lambda: self._add_stage_marker("start"))
        self.stage_mark_stop_button.clicked.connect(lambda: self._add_stage_marker("stop"))
        self.stage_plot_clear_button.clicked.connect(lambda _checked=False: self._clear_stage_plot_view())
        row.addWidget(self.stage_plot_mode_label)
        row.addStretch(1)
        row.addWidget(self.stage_mark_state_label)
        row.addWidget(self.stage_mark_start_button)
        row.addWidget(self.stage_mark_stop_button)
        row.addWidget(self.stage_plot_clear_button)
        self.stage_plot_widget = pg.PlotWidget()
        self.stage_plot_widget.setMinimumWidth(0)
        self.stage_plot_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.stage_plot_widget.setBackground("#0D1117")
        self.stage_plot_widget.showGrid(x=True, y=True, alpha=0.18)
        self.stage_plot_widget.setLabel("left", "Position", units="mm")
        self.stage_plot_widget.setLabel("bottom", "Move time", units="s")
        self.stage_plot_widget.addLegend(offset=(8, 8))
        self.stage_trace_curve = self.stage_plot_widget.plot([], [], pen=pg.mkPen("#58A6FF", width=2), name="Z")
        self.stage_x_trace_curve = self.stage_plot_widget.plot([], [], pen=pg.mkPen("#F4A261", width=2), name="X")
        self.stage_plot_stack = QStackedWidget()
        self.stage_plot_stack.setMinimumWidth(0)
        self.stage_plot_stack.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.stage_plot_stack.addWidget(self.stage_plot_widget)
        self.stage_trajectory_3d_item = None
        if gl is not None:
            self.stage_trajectory_widget = gl.GLViewWidget()
            self.stage_trajectory_widget.setBackgroundColor("#0D1117")
            self.stage_trajectory_widget.setCameraPosition(distance=10, elevation=22, azimuth=-55)
            self.stage_trajectory_grid = gl.GLGridItem()
            self.stage_trajectory_grid.setSize(10, 10, 1)
            self.stage_trajectory_grid.setSpacing(1, 1, 1)
            self.stage_trajectory_widget.addItem(self.stage_trajectory_grid)
            self.stage_trajectory_3d_item = gl.GLLinePlotItem(
                pos=np.empty((0, 3)),
                color=(0.35, 0.65, 1.0, 1.0),
                width=2,
                antialias=True,
            )
            self.stage_trajectory_widget.addItem(self.stage_trajectory_3d_item)
            self.stage_plot_stack.addWidget(self.stage_trajectory_widget)
        else:
            self.stage_trajectory_widget = None
        self.stage_plot_stack.setCurrentWidget(self.stage_plot_widget)
        layout.addLayout(row)
        layout.addWidget(self.stage_plot_stack, 1, Qt.AlignHCenter)
        QTimer.singleShot(0, self._apply_plot_section_geometry)
        return group

    def _build_stage_dashboard_group(self) -> QWidget:
        group = QGroupBox("Position Dashboard")
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QGridLayout(group)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setHorizontalSpacing(2)
        layout.setVerticalSpacing(0)
        self.stage_z_position_label = QLabel("Z -- mm")
        self.stage_x_position_label = QLabel("X -- mm")
        self.stage_motion_state_label = QLabel("State Idle")
        self.stage_contact_state_label = QLabel("Contact Not set")
        self.stage_axis_state_label = QLabel("Axis --")
        self.stage_last_update_label = QLabel("Last --")
        self.contact_calibration_button = QPushButton("Contact Cal.")
        self.contact_calibration_button.setMaximumWidth(112)
        self.contact_calibration_button.setToolTip("Open the contact calibration workflow.")
        self.contact_calibration_button.clicked.connect(self._open_contact_calibration_dialog)
        dashboard_labels = (
            self.stage_z_position_label,
            self.stage_x_position_label,
            self.stage_motion_state_label,
            self.stage_contact_state_label,
            self.stage_axis_state_label,
            self.stage_last_update_label,
        )
        for label in dashboard_labels:
            self._set_badge_style(label, tone="muted")
            label.setMinimumWidth(0)
            label.setMinimumHeight(18)
            label.setMaximumHeight(20)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.contact_calibration_button.setMinimumHeight(18)
        self.contact_calibration_button.setMaximumHeight(20)
        self.contact_calibration_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.stage_z_position_label, 0, 0)
        layout.addWidget(self.stage_x_position_label, 0, 1)
        layout.addWidget(self.stage_motion_state_label, 0, 2)
        layout.addWidget(self.stage_axis_state_label, 0, 3)
        layout.addWidget(self.stage_contact_state_label, 0, 4)
        layout.addWidget(self.stage_last_update_label, 0, 5)
        layout.addWidget(self.contact_calibration_button, 0, 6)
        for column in range(7):
            layout.setColumnStretch(column, 1)
        return group

    def _set_stage_dashboard_style(self, widget: QLabel, text: str, tone: str) -> None:
        widget.setText(text)
        self._set_badge_style(widget, tone=tone)

    def _refresh_stage_dashboard_defaults(self) -> None:
        if not hasattr(self, "stage_z_position_label"):
            return
        self._set_stage_dashboard_style(
            self.stage_z_position_label,
            self._format_stage_position_label("Z", self.stage_positions_mm.get(1)),
            "info" if self.stage_positions_mm.get(1) is not None else "muted",
        )
        self._set_stage_dashboard_style(
            self.stage_x_position_label,
            self._format_stage_position_label("X", self.stage_positions_mm.get(2)),
            "info" if self.stage_positions_mm.get(2) is not None else "muted",
        )
        status_text = (
            self.stage_state_label.text().replace("Stage ", "", 1)
            if hasattr(self, "stage_state_label")
            else "Idle"
        )
        self._set_stage_dashboard_style(self.stage_motion_state_label, f"State {status_text}", "muted")
        axis_text = f"Axis {self.motion_config.axis}" if self.motion_config is not None else "Axis --"
        axis_tone = "info" if self.motion_config is not None else "muted"
        self._set_stage_dashboard_style(self.stage_axis_state_label, axis_text, axis_tone)

    def _format_stage_position_label(self, axis_name: str, position_mm: float | None) -> str:
        return f"{axis_name} -- mm" if position_mm is None else f"{axis_name} {position_mm:.3f} mm"

    def _set_stage_last_update_now(self) -> None:
        if hasattr(self, "stage_last_update_label"):
            self._set_stage_dashboard_style(
                self.stage_last_update_label,
                f"Last {datetime.now().strftime('%H:%M:%S')}",
                "info",
            )

    def _build_stage_safety_strip(self) -> QWidget:
        group = QGroupBox("Soft Limits")
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QHBoxLayout(group)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(1)
        self.stage_soft_limit_check = QCheckBox("Soft limit")
        self.stage_soft_limit_check.setToolTip("Enable the software min/max travel lock.")
        self.stage_origin_confirm_check = QCheckBox("Origin Confirmed")
        self.stage_origin_confirm_check.setToolTip(
            "Confirm the current stage origin/reference is valid before hardware automation."
        )
        self.stage_soft_min_spin = self._new_double_spin(-1000.0, 1000.0, 3, -35.0, 0.1)
        self.stage_soft_max_spin = self._new_double_spin(-1000.0, 1000.0, 3, 35.0, 0.1)
        self.stage_soft_min_spin.setMaximumWidth(78)
        self.stage_soft_max_spin.setMaximumWidth(78)
        self.stage_origin_confirm_check.toggled.connect(self._handle_origin_confirmed_changed)
        self.stage_soft_limit_check.toggled.connect(self._update_runtime_controls)
        self.stage_soft_min_spin.valueChanged.connect(self._update_runtime_controls)
        self.stage_soft_max_spin.valueChanged.connect(self._update_runtime_controls)
        layout.addWidget(self.stage_origin_confirm_check)
        layout.addWidget(self.stage_soft_limit_check)
        layout.addWidget(QLabel("Min"))
        layout.addWidget(self.stage_soft_min_spin)
        layout.addWidget(QLabel("Max"))
        layout.addWidget(self.stage_soft_max_spin)
        layout.addStretch(1)
        if self.motion_config is not None:
            self._apply_motion_config_to_soft_limits(self.motion_config)
        return group

    def _build_right_status_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_orchestration_status_group())
        splitter.addWidget(self._build_system_log_group())
        splitter.setSizes([560, 360])
        layout.addWidget(splitter, 1)
        self.log_splitter = splitter
        return section

    def _build_orchestration_status_group(self) -> QWidget:
        group = QGroupBox("Recipe Steps")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self.orchestration_step_list = QPlainTextEdit()
        self.orchestration_step_list.setReadOnly(True)
        self.orchestration_step_list.setPlaceholderText("Recipe steps will appear here.")
        layout.addWidget(self.orchestration_step_list, 1)
        self.automation_time_strip_label = QLabel("Elapsed -- | Left -- | ETA --")
        self.automation_time_strip_label.setWordWrap(True)
        self.automation_time_strip_label.setMinimumWidth(0)
        self.automation_time_strip_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._set_badge_style(self.automation_time_strip_label, tone="muted")
        layout.addWidget(self.automation_time_strip_label)
        self.automation_progress_bar = QProgressBar()
        self.automation_progress_bar.setRange(0, 1000)
        self.automation_progress_bar.setValue(0)
        self.automation_progress_bar.setTextVisible(True)
        self.automation_progress_bar.setFormat("Progress 0%")
        layout.addWidget(self.automation_progress_bar)
        self.automation_phase_label = QLabel("Phase idle")
        self.automation_progress_summary_label = QLabel("Steps 0 / 0")
        self.automation_eta_label = QLabel("Remain --")
        self.automation_end_time_label = QLabel("End --")
        for label in (
            self.automation_phase_label,
            self.automation_progress_summary_label,
            self.automation_eta_label,
            self.automation_end_time_label,
        ):
            label.hide()
            self._set_badge_style(label, tone="muted")
        layout.addWidget(self.automation_phase_label)
        layout.addWidget(self.automation_progress_summary_label)
        layout.addWidget(self.automation_eta_label)
        layout.addWidget(self.automation_end_time_label)
        self._reset_automation_progress()
        return group

    def _build_orchestration_control_group(self) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #0E1319; border: 1px solid #26303A; border-radius: 4px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        self.recipe_path_edit = QLineEdit()
        self.recipe_path_edit.setReadOnly(True)
        self.recipe_path_edit.setPlaceholderText("Recipe JSON or wizard output")
        self.recipe_path_edit.setMinimumWidth(0)
        self.recipe_path_edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.load_recipe_button = QPushButton("Load")
        self.recipe_helper_button = QPushButton("Helper")
        self.recipe_helper_button.setToolTip("Open the recipe wizard.")
        self.load_session_button = QPushButton("Session")
        self.load_recipe_button.clicked.connect(self._load_automation_recipe_dialog)
        self.recipe_helper_button.clicked.connect(self._open_recipe_helper_dialog)
        self.load_session_button.clicked.connect(self._load_automation_session_dialog)
        self.contact_detect_check = QCheckBox("Contact Check")
        self.contact_detect_check.hide()
        self.contact_use_zero_check = QCheckBox("Use as Zero")
        self.contact_axis_spin = QSpinBox()
        self.contact_axis_spin.setRange(1, 2)
        self.contact_axis_spin.setValue(1)
        self.contact_channel_spin = QSpinBox()
        self.contact_channel_spin.setRange(0, 63)
        self.contact_speed_spin = self._new_double_spin(0.001, 10.0, 3, 0.02, 0.01)
        self.contact_step_spin = self._new_double_spin(0.001, 5.0, 3, 0.01, 0.01)
        self.contact_travel_spin = self._new_double_spin(0.001, 100.0, 3, 1.0, 0.1)
        self.contact_threshold_spin = self._new_double_spin(0.001, 1_000_000.0, 3, 1.0, 0.1)
        self.contact_baseline_spin = self._new_double_spin(0.0, 60.0, 3, 0.2, 0.05)
        self.contact_stable_spin = self._new_double_spin(0.0, 60.0, 3, 0.05, 0.01)
        self.contact_summary_label = QLabel("Contact: Not set")
        self.contact_summary_label.setWordWrap(False)
        self.contact_summary_label.setMinimumWidth(0)
        self.contact_summary_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._set_badge_style(self.contact_summary_label, tone="muted")
        self.contact_detect_check.toggled.connect(self._update_contact_detection_controls)

        self.automation_status_label = QLabel("Idle")
        self.automation_step_label = QLabel("No recipe loaded")
        self.motion_status_label = QLabel("Motion bridge: disabled")
        self.automation_status_label.setMinimumWidth(0)
        self.automation_status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.automation_step_label.setWordWrap(False)
        self.automation_step_label.setMinimumWidth(0)
        self.automation_step_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.motion_status_label.setWordWrap(False)
        self.motion_status_label.setMinimumWidth(0)
        self.motion_status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._set_badge_style(self.automation_status_label, tone="muted")
        self._set_badge_style(self.automation_step_label, tone="neutral")
        self._set_badge_style(self.motion_status_label, tone="muted")
        self.scenario_title_label = QLabel("Readiness")
        self.scenario_hint_label = QLabel("Load or create a recipe, then confirm motion readiness.")
        self.scenario_title_label.hide()
        self.scenario_hint_label.hide()
        self.scenario_hint_label.setWordWrap(True)
        self.scenario_hint_label.setMinimumWidth(0)
        self.scenario_hint_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.scenario_setup_label = QLabel("DAQ Pending")
        self.scenario_recipe_label = QLabel("Recipe Missing")
        self.scenario_safety_label = QLabel("Stage Pending")
        self.scenario_run_label = QLabel("Run Blocked")
        for label in (
            self.scenario_setup_label,
            self.scenario_recipe_label,
            self.scenario_safety_label,
            self.scenario_run_label,
        ):
            label.setWordWrap(False)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            self._set_badge_style(label, tone="muted")

        self.run_automation_button = QPushButton("Run")
        self.stop_automation_button = QPushButton("Stop")
        self.run_automation_button.clicked.connect(self._start_automation)
        self.stop_automation_button.clicked.connect(self._request_stop_automation)

        recipe_row = QHBoxLayout()
        recipe_row.setContentsMargins(0, 0, 0, 0)
        recipe_row.setSpacing(2)
        recipe_row.addWidget(self.recipe_path_edit, 1)
        recipe_row.addWidget(self.load_recipe_button)
        recipe_row.addWidget(self.recipe_helper_button)
        recipe_row.addWidget(self.load_session_button)
        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(2)
        status_row.addWidget(self.automation_status_label, 1)
        status_row.addWidget(self.motion_status_label, 3)
        status_row.addWidget(self.contact_summary_label, 2)
        readiness_row = QHBoxLayout()
        readiness_row.setContentsMargins(0, 0, 0, 0)
        readiness_row.setSpacing(2)
        readiness_row.addWidget(self.scenario_setup_label)
        readiness_row.addWidget(self.scenario_recipe_label)
        readiness_row.addWidget(self.scenario_safety_label)
        readiness_row.addWidget(self.scenario_run_label)
        action_row = QHBoxLayout()
        action_row.setContentsMargins(0, 0, 0, 0)
        action_row.setSpacing(2)
        action_row.addWidget(self.automation_step_label, 3)
        action_row.addWidget(self.run_automation_button, 1)
        action_row.addWidget(self.stop_automation_button, 1)

        layout.addLayout(readiness_row)
        layout.addLayout(recipe_row)
        layout.addLayout(status_row)
        layout.addLayout(action_row)
        self._update_contact_detection_controls()
        return frame

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self._build_plot_group(), 6)
        layout.addWidget(self._build_monitor_group(), 3)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(980 if self._supports_analog_output() else 900)
        panel.setMaximumWidth(1360 if self._supports_analog_output() else 1240)
        self.cockpit_panel = panel

        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        cockpit_stack = QWidget()
        cockpit_layout = QVBoxLayout(cockpit_stack)
        cockpit_layout.setContentsMargins(0, 0, 0, 0)
        cockpit_layout.setSpacing(2)
        cockpit_layout.addWidget(self._build_recipe_group())
        cockpit_layout.addWidget(self._build_run_group())
        cockpit_layout.addWidget(self._build_motion_group())
        cockpit_layout.addWidget(self._build_results_group(), 1)
        cockpit_layout.addStretch(1)

        layout.addWidget(cockpit_stack, 5)
        layout.addWidget(self._build_system_log_group(), 3)
        return panel

    def _build_channel_controls(self) -> QWidget:
        panel = QGroupBox("Channels")
        panel.setObjectName("DaqChannelShelf")
        panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(3)
        self.ai_group = self._build_ai_group()
        layout.addWidget(self.ai_group, 1)
        self.ao_group = self._build_ao_group()
        self.ao_group.setVisible(self._supports_analog_output())
        layout.addWidget(self.ao_group, 1)
        return panel

    def _build_recipe_group(self) -> QWidget:
        group = QGroupBox("Recipe")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)

        self.recipe_path_edit = QLineEdit()
        self.recipe_path_edit.setReadOnly(True)
        self.recipe_path_edit.setPlaceholderText("Recipe JSON or generated protocol")
        self.load_recipe_button = QPushButton("Load Recipe")
        self.load_recipe_button.setMinimumWidth(110)
        self.recipe_helper_button = QPushButton("Recipe Helper")
        self.recipe_helper_button.setMinimumWidth(110)
        self.load_session_button = QPushButton("Open Session")
        self.load_session_button.setMinimumWidth(110)
        self.load_recipe_button.clicked.connect(self._load_automation_recipe_dialog)
        self.recipe_helper_button.clicked.connect(self._open_recipe_helper_dialog)
        self.load_session_button.clicked.connect(self._load_automation_session_dialog)

        self.scenario_title_label = QLabel("Scenario: 1 Prepare -> 2 Load -> 3 Verify -> 4 Run")
        self.scenario_hint_label = QLabel("Load a recipe or reopen a session snapshot.")
        self.scenario_setup_label = QLabel("1 Setup")
        self.scenario_recipe_label = QLabel("2 Recipe")
        self.scenario_safety_label = QLabel("3 Safety")
        self.scenario_run_label = QLabel("4 Run")
        self.scenario_hint_label.setWordWrap(True)
        self.scenario_title_label.setStyleSheet("font-weight: 700; font-size: 12px; color: #F0F6FC; border: none;")
        self.scenario_hint_label.setStyleSheet("font-size: 11px; color: #9BA7B4; border: none;")
        for label in (
            self.scenario_setup_label,
            self.scenario_recipe_label,
            self.scenario_safety_label,
            self.scenario_run_label,
        ):
            self._set_badge_style(label, tone="muted")

        scenario_strip = QHBoxLayout()
        scenario_strip.setContentsMargins(0, 0, 0, 0)
        scenario_strip.setSpacing(4)
        scenario_strip.addWidget(self.scenario_setup_label)
        scenario_strip.addWidget(self.scenario_recipe_label)
        scenario_strip.addWidget(self.scenario_safety_label)
        scenario_strip.addWidget(self.scenario_run_label)
        scenario_strip.addStretch(1)
        scenario_host = QWidget()
        scenario_host.setLayout(scenario_strip)

        recipe_row = QHBoxLayout()
        recipe_row.setContentsMargins(0, 0, 0, 0)
        recipe_row.setSpacing(4)
        recipe_row.addWidget(self.recipe_path_edit, 1)
        recipe_row.addWidget(self.load_recipe_button)
        recipe_row.addWidget(self.recipe_helper_button)
        recipe_row.addWidget(self.load_session_button)

        layout.addWidget(self.scenario_title_label)
        layout.addWidget(scenario_host)
        layout.addWidget(self.scenario_hint_label)
        layout.addLayout(recipe_row)
        return group

    def _build_run_group(self) -> QWidget:
        group = QGroupBox("Run")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        group.setMaximumHeight(360)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        layout.setAlignment(Qt.AlignTop)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["simulation", "ni"])
        self.backend_combo.setMaximumWidth(100)
        self.backend_combo.currentTextChanged.connect(self._refresh_runtime_summary)
        self.chassis_name_edit = QLineEdit()
        self.chassis_name_edit.setMaximumWidth(120)
        self.chassis_name_edit.textChanged.connect(self._sync_physical_channels)
        self.ai_slot_spin = QSpinBox()
        self.ai_slot_spin.setRange(1, 4)
        self.ai_slot_spin.setMaximumWidth(54)
        self.ai_slot_spin.valueChanged.connect(self._sync_physical_channels)
        self.ao_slot_spin = QSpinBox()
        self.ao_slot_spin.setRange(1, 4)
        self.ao_slot_spin.setMaximumWidth(54)
        self.ao_slot_spin.valueChanged.connect(self._sync_physical_channels)
        self.acquisition_hz_spin = self._new_double_spin(1.0, 5000.0, 1, 20.0, 1.0)
        self.acquisition_hz_spin.setMaximumWidth(72)
        self.display_hz_spin = self._new_double_spin(1.0, 100.0, 1, 10.0, 1.0)
        self.display_hz_spin.setMaximumWidth(64)
        self.history_seconds_spin = QSpinBox()
        self.history_seconds_spin.setRange(10, 3600)
        self.history_seconds_spin.setSingleStep(10)
        self.history_seconds_spin.setMaximumWidth(64)
        self.session_label_edit = QLineEdit()
        self.session_label_edit.setPlaceholderText("Session label")
        self.session_label_edit.setMinimumWidth(132)
        self.export_path_edit = QLineEdit()
        self.export_path_edit.setReadOnly(True)
        browse_button = QPushButton("Browse")
        browse_button.setMinimumWidth(72)
        browse_button.clicked.connect(self._choose_export_directory)
        self.browse_export_button = browse_button

        self.recipe_path_edit = QLineEdit()
        self.recipe_path_edit.setReadOnly(True)
        self.recipe_path_edit.setPlaceholderText("Recipe JSON or generated protocol")
        self.load_recipe_button = QPushButton("Load")
        self.load_recipe_button.setMinimumWidth(72)
        self.recipe_helper_button = QPushButton("Helper")
        self.recipe_helper_button.setMinimumWidth(72)
        self.load_session_button = QPushButton("Session")
        self.load_session_button.setMinimumWidth(72)
        self.load_recipe_button.clicked.connect(self._load_automation_recipe_dialog)
        self.recipe_helper_button.clicked.connect(self._open_recipe_helper_dialog)
        self.load_session_button.clicked.connect(self._load_automation_session_dialog)

        self.contact_detect_check = QCheckBox("Contact Detection")
        self.contact_detect_check.toggled.connect(self._update_contact_detection_controls)
        self.contact_use_zero_check = QCheckBox("Use as Zero")
        self.contact_axis_spin = QSpinBox()
        self.contact_axis_spin.setRange(1, 2)
        self.contact_axis_spin.setValue(1)
        self.contact_axis_spin.setMaximumWidth(54)
        self.contact_channel_spin = QSpinBox()
        self.contact_channel_spin.setRange(0, 63)
        self.contact_channel_spin.setValue(0)
        self.contact_channel_spin.setMaximumWidth(54)
        self.contact_speed_spin = self._new_double_spin(0.001, 10.0, 3, 0.02, 0.01)
        self.contact_speed_spin.setMaximumWidth(68)
        self.contact_step_spin = self._new_double_spin(0.001, 5.0, 3, 0.01, 0.01)
        self.contact_step_spin.setMaximumWidth(68)
        self.contact_travel_spin = self._new_double_spin(0.001, 100.0, 3, 1.0, 0.1)
        self.contact_travel_spin.setMaximumWidth(68)
        self.contact_threshold_spin = self._new_double_spin(0.001, 1_000_000.0, 3, 1.0, 0.1)
        self.contact_threshold_spin.setMaximumWidth(72)
        self.contact_baseline_spin = self._new_double_spin(0.0, 60.0, 3, 0.2, 0.05)
        self.contact_baseline_spin.setMaximumWidth(68)
        self.contact_stable_spin = self._new_double_spin(0.0, 60.0, 3, 0.05, 0.01)
        self.contact_stable_spin.setMaximumWidth(68)
        self.contact_summary_label = QLabel("Contact detect off")
        self.contact_summary_label.setWordWrap(True)
        self._set_badge_style(self.contact_summary_label, tone="muted")
        for widget in (
            self.contact_use_zero_check,
            self.contact_axis_spin,
            self.contact_channel_spin,
            self.contact_speed_spin,
            self.contact_step_spin,
            self.contact_travel_spin,
            self.contact_threshold_spin,
            self.contact_baseline_spin,
            self.contact_stable_spin,
        ):
            changed = getattr(widget, "valueChanged", None)
            if changed is not None:
                changed.connect(self._update_contact_detection_controls)
                continue
            toggled = getattr(widget, "toggled", None)
            if toggled is not None:
                toggled.connect(self._update_contact_detection_controls)

        self.automation_status_label = QLabel("Idle")
        self.automation_step_label = QLabel("No recipe loaded")
        self.motion_status_label = QLabel("Motion bridge: disabled")
        self.automation_step_label.setWordWrap(True)
        self.motion_status_label.setWordWrap(False)
        self._set_badge_style(self.automation_status_label, tone="muted")
        self._set_badge_style(self.automation_step_label, tone="neutral")
        self._set_badge_style(self.motion_status_label, tone="muted")

        self.automation_progress_bar = QProgressBar()
        self.automation_progress_bar.setRange(0, 1000)
        self.automation_progress_bar.setValue(0)
        self.automation_progress_bar.setTextVisible(True)
        self.automation_progress_bar.setFormat("0%")
        self.automation_phase_label = QLabel("Phase idle")
        self.automation_progress_summary_label = QLabel("Steps 0 / 0")
        self.automation_eta_label = QLabel("Remain --")
        self.automation_end_time_label = QLabel("End --")
        for label in (
            self.automation_phase_label,
            self.automation_progress_summary_label,
            self.automation_eta_label,
            self.automation_end_time_label,
        ):
            self._set_badge_style(label, tone="muted")

        self.connect_button = QPushButton("Connect")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.apply_outputs_button = QPushButton("Apply AO")
        self.zero_outputs_button = QPushButton("Zero AO")
        self.run_automation_button = QPushButton("Run Automation")
        self.stop_automation_button = QPushButton("Stop Automation")
        self.connect_button.clicked.connect(self._connect_backend)
        self.start_button.clicked.connect(self._start_measurement)
        self.stop_button.clicked.connect(self._stop_measurement)
        self.pause_button.clicked.connect(self._pause_measurement)
        self.resume_button.clicked.connect(self._resume_measurement)
        self.apply_outputs_button.clicked.connect(self._apply_outputs)
        self.zero_outputs_button.clicked.connect(self._zero_outputs)
        self.run_automation_button.clicked.connect(self._start_automation)
        self.stop_automation_button.clicked.connect(self._request_stop_automation)

        self.mark_state_label = QLabel("Marks 0")
        self._set_badge_style(self.mark_state_label, tone="muted")
        self.mark_start_button = QPushButton("Start Mark")
        self.mark_stop_button = QPushButton("Stop Mark")
        self.mark_start_button.clicked.connect(self._start_highlight_interval)
        self.mark_stop_button.clicked.connect(self._stop_highlight_interval)
        contact_toggle_row = QHBoxLayout()
        contact_toggle_row.setContentsMargins(0, 0, 0, 0)
        contact_toggle_row.setSpacing(4)
        contact_toggle_row.addWidget(self.contact_detect_check)
        contact_toggle_row.addWidget(self.contact_use_zero_check)
        contact_toggle_row.addWidget(self.contact_summary_label, 1)
        layout.addLayout(contact_toggle_row)

        status_badges_row = QHBoxLayout()
        status_badges_row.setContentsMargins(0, 0, 0, 0)
        status_badges_row.setSpacing(4)
        status_badges_row.addWidget(self.automation_status_label)
        status_badges_row.addWidget(self.motion_status_label, 1)
        layout.addLayout(status_badges_row)
        layout.addWidget(self.automation_step_label)
        layout.addWidget(self.automation_progress_bar)

        meta_grid = QGridLayout()
        meta_grid.setContentsMargins(0, 0, 0, 0)
        meta_grid.setHorizontalSpacing(4)
        meta_grid.setVerticalSpacing(4)
        meta_grid.addWidget(self.automation_phase_label, 0, 0)
        meta_grid.addWidget(self.automation_progress_summary_label, 0, 1)
        meta_grid.addWidget(self.automation_eta_label, 1, 0)
        meta_grid.addWidget(self.automation_end_time_label, 1, 1)
        meta_grid.setColumnStretch(0, 1)
        meta_grid.setColumnStretch(1, 1)
        layout.addLayout(meta_grid)

        manual_controls_grid = QGridLayout()
        manual_controls_grid.setContentsMargins(0, 0, 0, 0)
        manual_controls_grid.setHorizontalSpacing(4)
        manual_controls_grid.setVerticalSpacing(4)
        manual_controls_grid.addWidget(self.connect_button, 0, 0)
        manual_controls_grid.addWidget(self.start_button, 0, 1)
        manual_controls_grid.addWidget(self.pause_button, 0, 2)
        manual_controls_grid.addWidget(self.resume_button, 0, 3)
        manual_controls_grid.addWidget(self.stop_button, 0, 4)
        for column in range(5):
            manual_controls_grid.setColumnStretch(column, 1)
        layout.addLayout(manual_controls_grid)

        auto_controls_grid = QGridLayout()
        auto_controls_grid.setContentsMargins(0, 0, 0, 0)
        auto_controls_grid.setHorizontalSpacing(4)
        auto_controls_grid.setVerticalSpacing(4)
        auto_controls_grid.addWidget(self.run_automation_button, 0, 0, 1, 2)
        auto_controls_grid.addWidget(self.stop_automation_button, 0, 2, 1, 2)
        auto_controls_grid.addWidget(self.mark_start_button, 1, 0, 1, 2)
        auto_controls_grid.addWidget(self.mark_stop_button, 1, 2, 1, 2)
        for column in range(4):
            auto_controls_grid.setColumnStretch(column, 1)
        layout.addLayout(auto_controls_grid)

        for widget in (
            self.backend_combo,
            self.chassis_name_edit,
            self.ai_slot_spin,
            self.ao_slot_spin,
            self.acquisition_hz_spin,
            self.display_hz_spin,
            self.history_seconds_spin,
            self.session_label_edit,
            self.export_path_edit,
            self.contact_axis_spin,
            self.contact_channel_spin,
            self.contact_speed_spin,
            self.contact_step_spin,
            self.contact_travel_spin,
            self.contact_threshold_spin,
            self.contact_baseline_spin,
            self.contact_stable_spin,
            browse_button,
            self.connect_button,
            self.start_button,
            self.stop_button,
            self.pause_button,
            self.resume_button,
            self.apply_outputs_button,
            self.zero_outputs_button,
            self.run_automation_button,
            self.stop_automation_button,
            self.mark_start_button,
            self.mark_stop_button,
        ):
            if hasattr(widget, "setMinimumHeight"):
                widget.setMinimumHeight(24)
            if isinstance(widget, QPushButton):
                widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.automation_panel = group
        layout.addStretch(1)
        self._update_contact_detection_controls()
        self._reset_automation_progress()
        return group

    def _open_setup_summary_dialog(self) -> None:
        dialog = SetupSummaryDialog(
            parent=self,
            collect_snapshot=self._collect_setup_summary_snapshot,
            validate_current_config=self._validate_current_config_for_diagnostics,
            ensure_export_directory=self._ensure_export_directory_for_diagnostics,
            refresh_daq_devices=lambda: self._refresh_daq_device_choices(),
        )
        dialog.exec()

    def _open_recipe_wizard_dialog(self) -> None:
        dialog = RecipeWizardDialog(parent=self, apply_recipe=self._use_protocol_recipe)
        dialog.exec()

    def _open_channel_config_manager_dialog(self) -> None:
        dialog = ChannelConfigManagerDialog(
            parent=self,
            initial_config=self._config_from_ui(),
            apply_config=self._apply_channel_manager_config,
        )
        dialog.exec()

    def _open_marker_manager_dialog(self) -> None:
        dialog = MarkerManagerDialog(
            parent=self,
            collect_markers=self._collect_marker_manager_payload,
            apply_markers=self._apply_marker_manager_payload,
            export_markers=self._export_marker_manager_payload,
        )
        dialog.exec()

    def _collect_setup_summary_snapshot(self) -> dict[str, Any]:
        config = self._config_from_ui()
        readiness = {
            key: label.text()
            for key, label in getattr(self, "readiness_labels", {}).items()
        }
        return {
            "version": __version__,
            "config_path": str(self.config_path),
            "config": config_to_dict(config),
            "runtime": {
                "session_label": self.session_label_edit.text().strip(),
                "motion_config_path": str(self.motion_config_path) if self.motion_config_path else "",
                "automation_recipe_path": str(self.automation_recipe_path) if self.automation_recipe_path else "",
                "automation_recipe_id": getattr(self.automation_recipe, "recipe_id", ""),
                "controller_running": bool(self.controller and self.controller.is_running),
                "automation_running": self._is_automation_running(),
            },
            "readiness": readiness,
        }

    def _validate_current_config_for_diagnostics(self) -> tuple[bool, str]:
        try:
            validate_app_config(self._config_from_ui())
        except Exception as exc:
            return False, f"Configuration invalid: {exc}"
        return True, "Configuration is valid."

    def _ensure_export_directory_for_diagnostics(self) -> tuple[bool, str]:
        export_path = resolve_runtime_path(self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY)
        try:
            export_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return False, f"Failed to create export directory: {exc}"
        return True, f"Export directory ready: {export_path}"

    def _apply_channel_manager_config(self, config: AppConfig) -> None:
        if self.controller and self.controller.is_running:
            raise RuntimeError("Stop the measurement before applying channel changes.")
        if self._is_automation_running():
            raise RuntimeError("Stop automation before applying channel changes.")
        self.config = self._config_for_profile(config)
        self._load_config_into_widgets(self.config)
        self._reset_history()
        self._refresh_runtime_summary()
        self._update_runtime_controls()
        self._log(
            f"Channel config applied: AI {len(self.config.ai_channels)} / AO {len(self.config.ao_channels)}"
        )

    def _collect_marker_manager_payload(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        return deepcopy(self.highlight_markers), deepcopy(self.stage_markers)

    def _apply_marker_manager_payload(
        self,
        daq_markers: list[dict[str, Any]],
        stage_markers: list[dict[str, Any]],
    ) -> None:
        self._rebuild_highlight_markers_from_payload(daq_markers)
        self._rebuild_stage_markers_from_payload(stage_markers)
        self._log(
            f"Marker manager applied: DAQ {len(self.highlight_markers)} / Stage {len(self.stage_markers)}"
        )

    def _export_marker_manager_payload(self, target_path: Path) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "daq_markers": self.highlight_markers,
            "stage_markers": self.stage_markers,
        }
        target_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def _build_motion_group(self) -> QWidget:
        group = QGroupBox("Motion")
        group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        stage_group = self._build_stage_group()
        stage_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        safety_group = self._build_safety_group()
        safety_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(stage_group)
        layout.addWidget(safety_group)
        group.setMaximumHeight(stage_group.sizeHint().height() + safety_group.sizeHint().height() + 56)
        return group

    def _build_advanced_group(self) -> QWidget:
        group = QGroupBox("Advanced")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        layout.addWidget(self._build_collapsible_section("Setup", self._build_setup_group(), expanded=False))
        layout.addWidget(
            self._build_collapsible_section("Contact Details", self._build_contact_details_group(), expanded=False)
        )
        layout.addWidget(self._build_collapsible_section("Protocol", self._build_protocol_section(), expanded=False))
        layout.addWidget(
            self._build_collapsible_section(
                "Channels",
                self._build_detail_note_group("Channels", "Channel settings are shown in the DAQ section."),
                expanded=False,
            )
        )
        layout.addWidget(
            self._build_collapsible_section(
                "Annotations",
                self._build_detail_note_group("Annotations", "DAQ and Stage marker controls are on their plots."),
                expanded=False,
            )
        )
        return group

    def _build_setup_group(self) -> QWidget:
        group = QGroupBox("Setup")
        layout = QGridLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(4)
        rows = [
            ("Backend", self.backend_combo.currentText()),
            ("Chassis", self._chassis_name_text()),
            ("AI Slot", str(self.ai_slot_spin.value())),
            ("AO Slot", str(self.ao_slot_spin.value()) if self._supports_analog_output() else "disabled"),
            ("Acq Hz", f"{self.acquisition_hz_spin.value():g}"),
            ("Disp Hz", f"{self.display_hz_spin.value():g}"),
            ("History s", str(self.history_seconds_spin.value())),
            ("Export", self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY),
        ]
        for row, (key, value) in enumerate(rows):
            key_label = QLabel(key)
            value_label = QLabel(value)
            value_label.setWordWrap(True)
            layout.addWidget(key_label, row, 0)
            layout.addWidget(value_label, row, 1)
        return group

    def _build_detail_note_group(self, title: str, message: str) -> QWidget:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        label = QLabel(message)
        label.setWordWrap(True)
        layout.addWidget(label)
        return group

    def _build_contact_details_group(self) -> QWidget:
        group = QGroupBox("Contact Details")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        row_one = QHBoxLayout()
        row_one.setContentsMargins(0, 0, 0, 0)
        row_one.setSpacing(4)
        row_one.addWidget(self._build_run_field("Axis", self.contact_axis_spin), 1)
        row_one.addWidget(self._build_run_field("Channel", self.contact_channel_spin), 1)
        row_one.addWidget(self._build_run_field("Speed", self.contact_speed_spin), 1)
        row_one.addWidget(self._build_run_field("Step", self.contact_step_spin), 1)
        layout.addLayout(row_one)

        row_two = QHBoxLayout()
        row_two.setContentsMargins(0, 0, 0, 0)
        row_two.setSpacing(4)
        row_two.addWidget(self._build_run_field("Travel", self.contact_travel_spin), 1)
        row_two.addWidget(self._build_run_field("dR", self.contact_threshold_spin), 1)
        row_two.addWidget(self._build_run_field("Baseline", self.contact_baseline_spin), 1)
        row_two.addWidget(self._build_run_field("Stable", self.contact_stable_spin), 1)
        layout.addLayout(row_two)
        return group

    def _build_collapsible_section(self, title: str, content: QWidget, *, expanded: bool) -> QWidget:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #0F141B; border: 1px solid #30363D; border-radius: 4px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)

        toggle = QPushButton()
        toggle.setCheckable(True)
        toggle.setChecked(expanded)
        toggle.setStyleSheet(
            "QPushButton { text-align: left; background: #121821; border: 1px solid #26303A; padding: 2px 6px; }"
        )

        def _set_toggle_state(checked: bool) -> None:
            toggle.setText(f"[-] {title}" if checked else f"[+] {title}")
            content.setVisible(checked)

        toggle.toggled.connect(_set_toggle_state)
        _set_toggle_state(expanded)
        self._detail_section_toggles[title] = toggle
        layout.addWidget(toggle)
        layout.addWidget(content)
        return frame

    def _build_annotations_group(self) -> QWidget:
        group = QGroupBox("Annotations")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.setSpacing(4)
        state_row.addWidget(self.mark_state_label)
        state_row.addStretch(1)
        layout.addLayout(state_row)

        button_row = QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(4)
        button_row.addWidget(self.mark_start_button)
        button_row.addWidget(self.mark_stop_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return group

    def _build_protocol_section(self) -> QWidget:
        group = QGroupBox("Protocol")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        layout.addWidget(self._build_protocol_group())
        return group

    def _build_run_field(self, label: str, widget: QWidget) -> QWidget:
        field = QWidget()
        layout = QVBoxLayout(field)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        label_widget = QLabel(label)
        label_widget.setStyleSheet("font-size: 10px; color: #9BA7B4; border: none;")
        label_widget.setMaximumHeight(12)
        widget.setSizePolicy(QSizePolicy.Expanding, widget.sizePolicy().verticalPolicy())
        layout.addWidget(label_widget)
        layout.addWidget(widget)
        return field

    def _build_run_card(self, title: str, description: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #11161D; border: 1px solid #30363D; border-radius: 4px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 2, 4, 3)
        layout.setSpacing(1)
        if title:
            title_label = QLabel(title)
            title_label.setStyleSheet("font-weight: 700; font-size: 11px; color: #F0F6FC; border: none; background: transparent;")
            layout.addWidget(title_label)
        if description:
            desc_label = QLabel(description)
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("font-size: 10px; color: #9BA7B4; border: none; background: transparent;")
            layout.addWidget(desc_label)
        return frame, layout

    def _build_run_subpanel(self, title: str) -> tuple[QFrame, QVBoxLayout]:
        frame = QFrame()
        frame.setStyleSheet("QFrame { background: #0E1319; border: 1px solid #26303A; border-radius: 4px; }")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 3, 4, 4)
        layout.setSpacing(2)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: 700; font-size: 11px; color: #D8E1EA; border: none; background: transparent;")
        layout.addWidget(title_label)
        return frame, layout

    def _build_stage_group(self) -> QWidget:
        self.stage_panel = CompactStagePanel()
        self.stage_panel.log_requested.connect(self._log)
        self.stage_panel.error_reported.connect(self._show_error)
        self.stage_panel.config_loaded.connect(self._apply_stage_panel_motion_config)
        self.stage_panel.recovery_required.connect(self._handle_stage_recovery_required)
        self.stage_panel.status_changed.connect(self._set_stage_status)
        self.stage_panel.position_changed.connect(self._handle_stage_position_changed)
        self.stage_panel.active_axis_changed.connect(self._handle_manual_stage_axis_changed)
        self.stage_panel.set_target_validator(self._stage_target_allowed)
        if self.stage_panel.config is not None and self.stage_panel.config_path is not None:
            self._apply_stage_panel_motion_config(self.stage_panel.config, str(self.stage_panel.config_path))
        return self.stage_panel

    def _build_protocol_group(self) -> QWidget:
        self.protocol_panel = ProtocolPanel()
        self.protocol_panel.recipe_created.connect(self._use_protocol_recipe)
        self.protocol_panel.error_reported.connect(self._show_error)
        return self.protocol_panel

    def _build_safety_group(self) -> QWidget:
        self.safety_panel = SafetyPanel(badge_styler=lambda label, tone: self._set_badge_style(label, tone=tone))
        self.safety_panel.emergency_stop_requested.connect(self._handle_emergency_stop_requested)
        self.safety_panel.origin_confirmed_check.toggled.connect(self._handle_origin_confirmed_changed)
        if self.motion_config is not None and self.motion_config_path is not None:
            self._set_safety_motion_summary(self.motion_config, self.motion_config_path)
        return self.safety_panel

    def _build_monitor_group(self) -> QWidget:
        group = QGroupBox("Live Monitor")
        self.monitor_group = group
        group.setMaximumHeight(260)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(1)

        self.monitor_scroll = QScrollArea()
        self.monitor_scroll.setWidgetResizable(True)
        self.monitor_scroll.setFrameShape(QFrame.NoFrame)
        self.monitor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.monitor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.monitor_scroll.setMinimumHeight(126)

        monitor_content = QWidget()
        self.monitor_sections_layout = QGridLayout(monitor_content)
        self.monitor_sections_layout.setContentsMargins(0, 0, 0, 0)
        self.monitor_sections_layout.setHorizontalSpacing(3)
        self.monitor_sections_layout.setVerticalSpacing(3)
        self.monitor_scroll.setWidget(monitor_content)
        layout.addWidget(self.monitor_scroll, 1)

        ai_group = QFrame()
        ai_group.setStyleSheet("QFrame { background: #11161D; border: 1px solid #30363D; border-radius: 4px; }")
        ai_group.setMinimumHeight(78)
        ai_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        ai_outer = QVBoxLayout(ai_group)
        ai_outer.setContentsMargins(2, 1, 2, 2)
        ai_outer.setSpacing(0)
        ai_title = QLabel(self._input_live_group_title())
        ai_title.setStyleSheet("font-weight: 700; color: #F0F6FC; border: none; background: transparent;")
        ai_layout = QGridLayout()
        ai_layout.setContentsMargins(2, 2, 2, 2)
        ai_layout.setHorizontalSpacing(2)
        ai_layout.setVerticalSpacing(2)
        ai_layout.setAlignment(Qt.AlignTop)
        ai_outer.addWidget(ai_title)
        ai_outer.addLayout(ai_layout)
        self.ai_cards_host = ai_group
        self.ai_cards_layout = ai_layout

        ao_group = QFrame()
        ao_group.setStyleSheet("QFrame { background: #11161D; border: 1px solid #30363D; border-radius: 4px; }")
        ao_group.setMinimumHeight(78)
        ao_group.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        ao_outer = QVBoxLayout(ao_group)
        ao_outer.setContentsMargins(2, 1, 2, 2)
        ao_outer.setSpacing(0)
        ao_title = QLabel("AO Live")
        ao_title.setStyleSheet("font-weight: 700; color: #F0F6FC; border: none; background: transparent;")
        ao_layout = QGridLayout()
        ao_layout.setContentsMargins(2, 2, 2, 2)
        ao_layout.setHorizontalSpacing(2)
        ao_layout.setVerticalSpacing(2)
        ao_layout.setAlignment(Qt.AlignTop)
        ao_outer.addWidget(ao_title)
        ao_outer.addLayout(ao_layout)
        self.ao_cards_host = ao_group
        self.ao_cards_layout = ao_layout

        ao_group.setVisible(self._supports_analog_output())
        self._sync_monitor_section_layout()
        return group

    def _build_system_log_group(self) -> QWidget:
        group = QGroupBox("System Log")
        group.setMinimumWidth(0)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)

        layout.addWidget(self.log_output, 1)
        return group

    def _build_plot_group(self) -> QWidget:
        group = QGroupBox(self._input_plot_group_title())
        self.daq_plot_group = group
        group.setMinimumWidth(0)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(2)
        top_row = QGridLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setHorizontalSpacing(3)
        top_row.setVerticalSpacing(1)
        top_row.addWidget(QLabel("Range"), 0, 0)
        self.range_combo = QComboBox()
        self.range_combo.addItems(list(self.RANGE_OPTIONS.keys()))
        self.range_combo.setFixedWidth(68)
        self.range_combo.currentTextChanged.connect(self._refresh_plot)
        top_row.addWidget(self.range_combo, 0, 1)
        top_row.addWidget(QLabel("View"), 0, 2)
        self.ai_plot_mode_combo = QComboBox()
        self.ai_plot_mode_combo.addItems(["Scaled", "Raw V"])
        self.ai_plot_mode_combo.setFixedWidth(76)
        self.ai_plot_mode_combo.currentTextChanged.connect(self._refresh_plot)
        top_row.addWidget(self.ai_plot_mode_combo, 0, 3)
        self.ao_overlay_checkbox = QCheckBox("AO")
        self.ao_overlay_checkbox.setChecked(True)
        self.ao_overlay_checkbox.setToolTip("Overlay analog output current on the DAQ plot.")
        self.ao_overlay_checkbox.toggled.connect(self._refresh_plot)
        top_row.addWidget(self.ao_overlay_checkbox, 0, 4)
        self.ao_overlay_checkbox.setVisible(self._supports_analog_output())
        self.mark_state_label = QLabel("Marks 0")
        self._set_badge_style(self.mark_state_label, tone="muted")
        self.mark_start_button = QPushButton("Start Mark")
        self.mark_stop_button = QPushButton("Stop Mark")
        self.plot_clear_button = QPushButton("Clear")
        self.mark_start_button.setMaximumWidth(92)
        self.mark_stop_button.setMaximumWidth(92)
        self.plot_clear_button.setMaximumWidth(64)
        self.mark_state_label.setMaximumWidth(86)
        self.mark_start_button.clicked.connect(self._start_highlight_interval)
        self.mark_stop_button.clicked.connect(self._stop_highlight_interval)
        self.plot_clear_button.clicked.connect(self._clear_daq_plot_view)
        top_row.setColumnStretch(5, 1)
        top_row.addWidget(self.mark_state_label, 0, 6)
        top_row.addWidget(self.mark_start_button, 0, 7)
        top_row.addWidget(self.mark_stop_button, 0, 8)
        top_row.addWidget(self.plot_clear_button, 0, 9)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setMinimumWidth(0)
        self.plot_widget.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.plot_widget.setBackground("#0D1117")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.18)
        self.plot_widget.setLabel("left", "Scaled Value")
        self.plot_widget.setLabel("bottom", "Elapsed", units="s")
        self.plot_widget.showAxis("right")
        self.plot_widget.getAxis("right").setTextPen("#F4A261")
        self.plot_widget.getAxis("right").setPen(pg.mkPen("#3B4450"))
        self.ao_viewbox = pg.ViewBox()
        self._add_ao_viewbox_to_plot_scene()
        self.plot_widget.getAxis("right").linkToView(self.ao_viewbox)
        self.ao_viewbox.setXLink(self.plot_widget.getPlotItem())
        self.plot_widget.getPlotItem().vb.sigResized.connect(self._sync_plot_views)
        self._sync_plot_views()
        layout.addLayout(top_row)
        layout.addWidget(self.plot_widget, 1, Qt.AlignHCenter)
        QTimer.singleShot(0, self._apply_plot_section_geometry)
        return group

    def _build_results_group(self) -> QWidget:
        group = QGroupBox("Results")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(3)
        self.result_table = QTableWidget()
        self.result_table.setColumnCount(6)
        self.result_table.setHorizontalHeaderLabels(["Step", "Cycle", "Phase", "Target", "Frames", "File"])
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setWordWrap(False)
        self.result_table.verticalHeader().setDefaultSectionSize(26)
        self.result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.result_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.result_table, 1)
        return group

    def _build_ai_group(self) -> QWidget:
        group = QWidget()
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.ai_table = QTableWidget()
        self._configure_compact_channel_table(self.ai_table)
        self.ai_table.setColumnCount(11)
        self.ai_table.setHorizontalHeaderLabels(
            ["On", "Name", "Physical", "Mode", "Scale", "Offset", "Unit", "Voltage", "Value", "Status", "Plot"]
        )
        self.ai_table.verticalHeader().setVisible(False)
        self.ai_table.setAlternatingRowColors(True)
        self.ai_table.setWordWrap(False)
        self.ai_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ai_table.horizontalHeader().setStretchLastSection(False)
        self.ai_table.setColumnHidden(10, True)
        layout.addWidget(self.ai_table)
        return group

    def _build_ao_group(self) -> QWidget:
        group = QWidget()
        group.setMinimumWidth(0)
        group.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.ao_table = QTableWidget()
        self._configure_compact_channel_table(self.ao_table)
        self.ao_table.setColumnCount(8)
        self.ao_table.setHorizontalHeaderLabels(
            ["On", "Name", "Physical", "Min mA", "Max mA", "Initial mA", "Setpoint mA", "Live mA"]
        )
        self.ao_table.verticalHeader().setVisible(False)
        self.ao_table.setAlternatingRowColors(True)
        self.ao_table.setWordWrap(False)
        self.ao_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.ao_table.horizontalHeader().setStretchLastSection(False)
        layout.addWidget(self.ao_table)
        return group

    def _configure_compact_channel_table(self, table: QTableWidget) -> None:
        table.setMinimumWidth(0)
        table.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Maximum)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.verticalHeader().setMinimumSectionSize(self.CHANNEL_TABLE_ROW_HEIGHT)
        table.verticalHeader().setDefaultSectionSize(self.CHANNEL_TABLE_ROW_HEIGHT)
        table.horizontalHeader().setMinimumSectionSize(18)
        table.horizontalHeader().setFixedHeight(21)
        table.setStyleSheet(
            """
            QTableWidget {
                font-size: 12px;
            }
            QHeaderView::section {
                padding: 1px 2px;
                font-size: 11px;
            }
            QTableWidget::item {
                padding: 0px;
            }
            """
        )

    def _configure_channel_cell_widget(self, widget: QWidget, *, maximum_width: int | None = None) -> None:
        widget.setMinimumHeight(self.CHANNEL_CELL_WIDGET_HEIGHT)
        widget.setMaximumHeight(self.CHANNEL_CELL_WIDGET_HEIGHT)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if maximum_width is not None:
            widget.setMaximumWidth(maximum_width)
        widget.setStyleSheet(
            """
            QComboBox, QDoubleSpinBox, QSpinBox {
                min-height: 18px;
                max-height: 22px;
                padding: 0px 3px;
                border-radius: 3px;
            }
            """
        )

    def _load_config_into_widgets(self, config: AppConfig) -> None:
        config = self._config_for_profile(config)
        self.config = config
        self.backend_combo.setCurrentText(config.backend)
        self._set_chassis_name_text(config.chassis_name)
        self._refresh_daq_device_choices(config.chassis_name)
        self.ai_slot_spin.setValue(config.ai_module_slot)
        self.ao_slot_spin.setValue(config.ao_module_slot)
        self.acquisition_hz_spin.setValue(config.sampling.acquisition_hz)
        self.display_hz_spin.setValue(config.sampling.display_update_hz)
        self.history_seconds_spin.setValue(config.sampling.history_seconds)
        self.export_path_edit.setText(config.export_directory)
        self.ai_color_by_row = [channel.color for channel in config.ai_channels]
        self._populate_ai_table(config.ai_channels)
        self._populate_ao_table(config.ao_channels)
        self._sync_channel_controls_geometry()
        self._sync_physical_channels()
        self._rebuild_monitor_cards()
        self._rebuild_plot_curves()
        self._rebuild_compatibility_widgets()
        self._refresh_input_table()
        self._refresh_output_table()
        self._refresh_monitor_cards()

    def _rebuild_monitor_cards(self) -> None:
        self._clear_layout(self.ai_cards_layout)
        self._clear_layout(self.ao_cards_layout)
        self.ai_card_widgets.clear()
        self.ao_card_widgets.clear()

        for row, name_item in enumerate(self.ai_name_items):
            frame, value_label, detail_label, status_label, limit_check = self._create_live_card(
                title=name_item.text(),
                accent=self.ai_color_by_row[row] if row < len(self.ai_color_by_row) else "#3A7CA5",
                subtitle=self.ai_physical_items[row].text(),
            )
            if self._supports_analog_output():
                self.ai_cards_layout.addWidget(frame, row // 2, row % 2)
            else:
                self.ai_cards_layout.addWidget(frame, row, 0)
            self.ai_card_widgets[row] = (value_label, detail_label, status_label, limit_check)

        for row, name_item in enumerate(self.ao_name_items):
            frame, value_label, detail_label, status_label, limit_check = self._create_live_card(
                title=name_item.text(),
                accent="#F4A261",
                subtitle=self.ao_physical_items[row].text(),
            )
            self.ao_cards_layout.addWidget(frame, row // 2, row % 2)
            self.ao_card_widgets[row] = (value_label, detail_label, status_label, limit_check)
        self._sync_monitor_section_layout()

    def _sync_monitor_section_layout(self) -> None:
        if not hasattr(self, "monitor_sections_layout"):
            return
        layout = self.monitor_sections_layout
        layout.removeWidget(self.ai_cards_host)
        layout.removeWidget(self.ao_cards_host)
        has_ao = self._supports_analog_output() and bool(getattr(self, "ao_name_items", []))
        ai_count = len(getattr(self, "ai_name_items", []))
        ao_count = len(getattr(self, "ao_name_items", []))
        compact_columns = has_ao and max(ai_count, ao_count) <= 2
        self.ao_cards_host.setVisible(has_ao)
        if compact_columns:
            layout.addWidget(self.ai_cards_host, 0, 0)
            layout.addWidget(self.ao_cards_host, 0, 1)
            layout.setColumnStretch(0, 1)
            layout.setColumnStretch(1, 1)
            layout.setRowStretch(0, 1)
            content_height = max(self.ai_cards_host.sizeHint().height(), self.ao_cards_host.sizeHint().height())
        else:
            layout.addWidget(self.ai_cards_host, 0, 0)
            if has_ao:
                layout.addWidget(self.ao_cards_host, 1, 0)
            layout.setColumnStretch(0, 1)
            layout.setColumnStretch(1, 0)
            layout.setRowStretch(0, 1)
            layout.setRowStretch(1, 1 if has_ao else 0)
            content_height = self.ai_cards_host.sizeHint().height()
            if has_ao:
                content_height += self.ao_cards_host.sizeHint().height() + layout.verticalSpacing()

        self.monitor_scroll.widget().setMinimumHeight(content_height)
        if compact_columns:
            target_height = max(128, min(content_height + 6, 220))
            self.monitor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        else:
            target_height = max(150, min(content_height, 230))
            self.monitor_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.monitor_scroll.setMinimumHeight(target_height)
        self.monitor_scroll.setMaximumHeight(target_height)
        if hasattr(self, "monitor_group"):
            self.monitor_group.setMinimumHeight(target_height + 24)

    def _create_live_card(
        self,
        *,
        title: str,
        accent: str,
        subtitle: str,
    ) -> tuple[QFrame, QLabel, QLabel, QLabel, QCheckBox]:
        frame = QFrame()
        frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        frame.setStyleSheet(
            "QFrame { background: #161B22; border: 1px solid #30363D; border-radius: 4px; }"
        )
        frame.setMinimumHeight(0)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(4, 1, 4, 1)
        layout.setSpacing(0)

        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(4)
        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight: 700; color: {accent};")
        limit_check = QCheckBox("Limit")
        limit_check.setToolTip("Enable limit warning status for this live value.")
        limit_check.toggled.connect(self._refresh_monitor_cards)
        header.addWidget(title_label, 1)
        header.addWidget(limit_check)
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #8B949E;")
        subtitle_label.setWordWrap(False)
        value_label = QLabel("--")
        value_label.setStyleSheet("font-size: 14px; font-weight: 800; color: #F0F6FC;")
        detail_label = QLabel("--")
        detail_label.setStyleSheet("color: #C9D1D9;")
        detail_label.setWordWrap(False)
        status_label = QLabel("--")
        status_label.setStyleSheet("color: #8B949E;")
        status_label.setWordWrap(False)
        for label in (title_label, subtitle_label, value_label, detail_label, status_label):
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

        layout.addLayout(header)
        layout.addWidget(subtitle_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        layout.addWidget(status_label)
        return frame, value_label, detail_label, status_label, limit_check

    def _populate_ai_table(self, channels: list[AnalogInputChannelConfig]) -> None:
        self.ai_table.setRowCount(len(channels))
        self.ai_enabled_checks.clear()
        self.ai_name_items.clear()
        self.ai_physical_items.clear()
        self.ai_mode_combos.clear()
        self.ai_scale_spins.clear()
        self.ai_offset_spins.clear()
        self.ai_unit_items.clear()
        self.ai_voltage_items.clear()
        self.ai_value_items.clear()
        self.ai_status_items.clear()
        self.ai_plot_checks.clear()

        for row, channel in enumerate(channels):
            self.ai_table.setRowHeight(row, self.CHANNEL_TABLE_ROW_HEIGHT)
            enabled_check = QCheckBox()
            enabled_check.setChecked(channel.enabled)
            enabled_check.stateChanged.connect(self._refresh_runtime_summary)
            self.ai_table.setCellWidget(row, 0, self._centered_widget(enabled_check))
            self.ai_enabled_checks.append(enabled_check)

            name_item = QTableWidgetItem(channel.name)
            physical_item = self._readonly_item(channel.physical_channel)
            mode_combo = QComboBox()
            mode_combo.addItems(["resistance", "voltage"])
            mode_combo.setCurrentText(channel.measurement_mode)
            self._configure_channel_cell_widget(mode_combo, maximum_width=86)
            scale_spin = self._new_double_spin(-1_000_000.0, 1_000_000.0, 4, channel.scale, 0.1)
            self._configure_channel_cell_widget(scale_spin, maximum_width=78)
            offset_spin = self._new_double_spin(-1_000_000.0, 1_000_000.0, 4, channel.offset, 0.1)
            self._configure_channel_cell_widget(offset_spin, maximum_width=78)
            unit_item = QTableWidgetItem(channel.engineering_unit)
            voltage_item = self._readonly_item("--")
            value_item = self._readonly_item("--")
            status_item = self._readonly_item("--")

            plot_check = QCheckBox()
            plot_check.setChecked(channel.enabled)
            plot_check.stateChanged.connect(self._refresh_plot)
            enabled_check.stateChanged.connect(
                lambda state, check=plot_check: check.setChecked(state == Qt.CheckState.Checked.value)
            )
            self.ai_table.setCellWidget(row, 10, self._centered_widget(plot_check))

            self.ai_table.setItem(row, 1, name_item)
            self.ai_table.setItem(row, 2, physical_item)
            self.ai_table.setCellWidget(row, 3, mode_combo)
            self.ai_table.setCellWidget(row, 4, scale_spin)
            self.ai_table.setCellWidget(row, 5, offset_spin)
            self.ai_table.setItem(row, 6, unit_item)
            self.ai_table.setItem(row, 7, voltage_item)
            self.ai_table.setItem(row, 8, value_item)
            self.ai_table.setItem(row, 9, status_item)

            self.ai_name_items.append(name_item)
            self.ai_physical_items.append(physical_item)
            self.ai_mode_combos.append(mode_combo)
            self.ai_scale_spins.append(scale_spin)
            self.ai_offset_spins.append(offset_spin)
            self.ai_unit_items.append(unit_item)
            self.ai_voltage_items.append(voltage_item)
            self.ai_value_items.append(value_item)
            self.ai_status_items.append(status_item)
            self.ai_plot_checks.append(plot_check)

    def _populate_ao_table(self, channels: list[AnalogOutputChannelConfig]) -> None:
        self.ao_table.setRowCount(len(channels))
        self.ao_enabled_checks.clear()
        self.ao_name_items.clear()
        self.ao_physical_items.clear()
        self.ao_min_spins.clear()
        self.ao_max_spins.clear()
        self.ao_initial_spins.clear()
        self.ao_setpoint_spins.clear()
        self.ao_live_items.clear()

        for row, channel in enumerate(channels):
            self.ao_table.setRowHeight(row, self.CHANNEL_TABLE_ROW_HEIGHT)
            enabled_check = QCheckBox()
            enabled_check.setChecked(channel.enabled)
            enabled_check.stateChanged.connect(self._refresh_runtime_summary)
            self.ao_table.setCellWidget(row, 0, self._centered_widget(enabled_check))
            self.ao_enabled_checks.append(enabled_check)

            name_item = QTableWidgetItem(channel.name)
            physical_item = self._readonly_item(channel.physical_channel)
            min_spin = self._new_double_spin(-100.0, 100.0, 3, channel.min_current_ma, 0.1)
            self._configure_channel_cell_widget(min_spin, maximum_width=74)
            max_spin = self._new_double_spin(-100.0, 100.0, 3, channel.max_current_ma, 0.1)
            self._configure_channel_cell_widget(max_spin, maximum_width=74)
            initial_spin = self._new_double_spin(-100.0, 100.0, 3, channel.initial_current_ma, 0.1)
            self._configure_channel_cell_widget(initial_spin, maximum_width=74)
            setpoint_spin = self._new_double_spin(-100.0, 100.0, 3, channel.initial_current_ma, 0.1)
            self._configure_channel_cell_widget(setpoint_spin, maximum_width=74)
            live_item = self._readonly_item("--")

            self.ao_table.setItem(row, 1, name_item)
            self.ao_table.setItem(row, 2, physical_item)
            self.ao_table.setCellWidget(row, 3, min_spin)
            self.ao_table.setCellWidget(row, 4, max_spin)
            self.ao_table.setCellWidget(row, 5, initial_spin)
            self.ao_table.setCellWidget(row, 6, setpoint_spin)
            self.ao_table.setItem(row, 7, live_item)

            self.ao_name_items.append(name_item)
            self.ao_physical_items.append(physical_item)
            self.ao_min_spins.append(min_spin)
            self.ao_max_spins.append(max_spin)
            self.ao_initial_spins.append(initial_spin)
            self.ao_setpoint_spins.append(setpoint_spin)
            self.ao_live_items.append(live_item)
            self._sync_ao_range_widgets(row)
            min_spin.valueChanged.connect(lambda _value, row=row: self._sync_ao_range_widgets(row))
            max_spin.valueChanged.connect(lambda _value, row=row: self._sync_ao_range_widgets(row))

    def _sync_ao_range_widgets(self, row: int) -> None:
        if row >= len(self.ao_min_spins) or row >= len(self.ao_max_spins):
            return
        min_spin = self.ao_min_spins[row]
        max_spin = self.ao_max_spins[row]
        min_value = min_spin.value()
        max_value = max_spin.value()
        minimum_gap = max(min_spin.singleStep(), 0.001)

        if min_value >= max_value:
            sender = self.sender()
            if sender is max_spin:
                min_value = max(min_spin.minimum(), max_value - minimum_gap)
                blocked = min_spin.blockSignals(True)
                min_spin.setValue(min_value)
                min_spin.blockSignals(blocked)
            else:
                max_value = min(max_spin.maximum(), min_value + minimum_gap)
                if max_value <= min_value:
                    min_value = max(min_spin.minimum(), max_value - minimum_gap)
                    blocked = min_spin.blockSignals(True)
                    min_spin.setValue(min_value)
                    min_spin.blockSignals(blocked)
                blocked = max_spin.blockSignals(True)
                max_spin.setValue(max_value)
                max_spin.blockSignals(blocked)

        for spin in (self.ao_initial_spins[row], self.ao_setpoint_spins[row]):
            blocked = spin.blockSignals(True)
            spin.setRange(min_value, max_value)
            if spin.value() < min_value:
                spin.setValue(min_value)
            elif spin.value() > max_value:
                spin.setValue(max_value)
            spin.blockSignals(blocked)

        self._refresh_monitor_cards()
        self._refresh_runtime_summary()

    def _sync_channel_controls_geometry(self) -> None:
        table_names = ("ai_table", "ao_table") if self._supports_analog_output() else ("ai_table",)
        tables = [table for table_name in table_names if (table := getattr(self, table_name, None)) is not None]
        if not tables:
            return
        row_counts = [table.rowCount() for table in tables]
        max_rows = max(row_counts)
        allow_vertical_scroll = max_rows > 2
        visible_rows = max(1, min(max_rows, 2))
        table_height = 21 + (self.CHANNEL_TABLE_ROW_HEIGHT * visible_rows) + 20
        panel_height = table_height + 28
        for table in tables:
            table.setVerticalScrollBarPolicy(
                Qt.ScrollBarAsNeeded if table.rowCount() > visible_rows and allow_vertical_scroll else Qt.ScrollBarAlwaysOff
            )
            table.setMinimumHeight(table_height)
            table.setMaximumHeight(table_height)
        if hasattr(self, "channel_controls_panel"):
            self.channel_controls_panel.setMinimumHeight(panel_height)
            self.channel_controls_panel.setMaximumHeight(panel_height)
            self.channel_controls_panel.setMinimumWidth(0)
            self.channel_controls_panel.setMaximumWidth(16777215)

    def _sync_physical_channels(self) -> None:
        chassis_name = self._chassis_name_text() or "cDAQ1"
        for row, item in enumerate(self.ai_physical_items):
            item.setText(build_physical_channel(self.ai_slot_spin.value(), row, channel_kind="ai", chassis_name=chassis_name))
        for row, item in enumerate(self.ao_physical_items):
            item.setText(build_physical_channel(self.ao_slot_spin.value(), row, channel_kind="ao", chassis_name=chassis_name))
        if hasattr(self, "ai_cards_layout"):
            self._rebuild_monitor_cards()
            self._refresh_monitor_cards()
        self._refresh_runtime_summary()

    def _rebuild_plot_curves(self) -> None:
        self.plot_widget.clear()
        self.plot_widget.addLegend(offset=(10, 10))
        self.plot_widget.showAxis("right")
        self._add_ao_viewbox_to_plot_scene()
        self.plot_widget.getAxis("right").linkToView(self.ao_viewbox)
        self.ao_viewbox.setXLink(self.plot_widget.getPlotItem())
        self.input_curves.clear()
        for item in list(self.ao_viewbox.addedItems):
            self.ao_viewbox.removeItem(item)
        self.output_curves.clear()
        for row, name_item in enumerate(self.ai_name_items):
            color = self.ai_color_by_row[row] if row < len(self.ai_color_by_row) else "#3A7CA5"
            self.input_curves[row] = self.plot_widget.plot(name=name_item.text(), pen=pg.mkPen(color, width=2))
        for row, name_item in enumerate(self.ao_name_items):
            self.output_curves[row] = pg.PlotDataItem(
                [],
                [],
                pen=pg.mkPen("#F4A261", width=2, style=Qt.DashLine),
                name=f"{name_item.text()} setpoint",
            )
            self.ao_viewbox.addItem(self.output_curves[row])
        self._sync_plot_views()

    def _rebuild_compatibility_widgets(self) -> None:
        self.resistance_curves = {row: pg.PlotDataItem(symbol="o") for row in range(self.ai_table.rowCount())}
        self.voltage_curves = {row: pg.PlotDataItem(symbol="o") for row in range(self.ai_table.rowCount())}

        self.channel_table.setRowCount(self.ai_table.rowCount())
        for row in range(self.ai_table.rowCount()):
            name_item = QTableWidgetItem(self.ai_name_items[row].text())
            toggle_button = QPushButton("Enabled")
            toggle_button.setCheckable(True)
            toggle_button.setChecked(self.ai_enabled_checks[row].isChecked())
            toggle_button.clicked.connect(
                lambda checked=False, row_index=row: self._set_channel_enabled_from_compat(row_index)
            )
            self.channel_table.setItem(row, 0, name_item)
            self.channel_table.setCellWidget(row, 1, toggle_button)

        self.channel_detail_table.setRowCount(self.ai_table.rowCount())
        for row in range(self.ai_table.rowCount()):
            module_number = (row // 4) + 1
            sensor_port = (row % 4) + 1
            self.channel_detail_table.setItem(row, 0, QTableWidgetItem(str(module_number)))
            self.channel_detail_table.setItem(row, 1, QTableWidgetItem(str(sensor_port)))

            bridge_combo = QComboBox()
            bridge_combo.addItems(["quarter_bridge", "half_bridge", "full_bridge"])
            bridge_combo.setCurrentText(self.config.ai_channels[row].bridge_type)
            excitation_edit = QLineEdit(self._format_float_compact(self.config.ai_channels[row].excitation_voltage))
            nominal_edit = QLineEdit(self._format_float_compact(self.config.ai_channels[row].nominal_resistance_ohm))
            self.channel_detail_table.setCellWidget(row, 2, bridge_combo)
            self.channel_detail_table.setCellWidget(row, 3, excitation_edit)
            self.channel_detail_table.setCellWidget(row, 4, nominal_edit)

    def _set_channel_enabled_from_compat(self, row_index: int) -> None:
        button = self.channel_table.cellWidget(row_index, 1)
        if isinstance(button, QPushButton):
            self.ai_enabled_checks[row_index].setChecked(button.isChecked())
            self._refresh_runtime_summary()

    def _config_from_ui(self) -> AppConfig:
        ai_channels: list[AnalogInputChannelConfig] = []
        ao_channels: list[AnalogOutputChannelConfig] = []
        for row in range(self.ai_table.rowCount()):
            bridge_type = "quarter_bridge"
            excitation_voltage = 5.0
            nominal_resistance = 350.0
            bridge_widget = self.channel_detail_table.cellWidget(row, 2) if self.channel_detail_table.rowCount() > row else None
            excitation_widget = (
                self.channel_detail_table.cellWidget(row, 3) if self.channel_detail_table.rowCount() > row else None
            )
            nominal_widget = (
                self.channel_detail_table.cellWidget(row, 4) if self.channel_detail_table.rowCount() > row else None
            )
            if isinstance(bridge_widget, QComboBox):
                bridge_type = bridge_widget.currentText()
            if isinstance(excitation_widget, QLineEdit):
                try:
                    excitation_voltage = float(excitation_widget.text().strip() or "5.0")
                except ValueError:
                    excitation_voltage = 5.0
            if isinstance(nominal_widget, QLineEdit):
                try:
                    nominal_resistance = float(nominal_widget.text().strip() or "350.0")
                except ValueError:
                    nominal_resistance = 350.0
            measurement_mode = self.ai_mode_combos[row].currentText()
            ai_channels.append(
                AnalogInputChannelConfig(
                    enabled=self.ai_enabled_checks[row].isChecked(),
                    name=self.ai_name_items[row].text().strip(),
                    physical_channel=self.ai_physical_items[row].text().strip(),
                    measurement_mode=measurement_mode,
                    scale=self.ai_scale_spins[row].value(),
                    offset=self.ai_offset_spins[row].value(),
                    engineering_unit=(
                        "ohm" if measurement_mode == "resistance" else self.ai_unit_items[row].text().strip() or "V"
                    ),
                    color=self.ai_color_by_row[row],
                    bridge_type=bridge_type,
                    excitation_voltage=excitation_voltage,
                    nominal_resistance_ohm=nominal_resistance,
                )
            )
        if self._supports_analog_output():
            for row in range(self.ao_table.rowCount()):
                ao_channels.append(
                    AnalogOutputChannelConfig(
                        enabled=self.ao_enabled_checks[row].isChecked(),
                        name=self.ao_name_items[row].text().strip(),
                        physical_channel=self.ao_physical_items[row].text().strip(),
                        min_current_ma=self.ao_min_spins[row].value(),
                        max_current_ma=self.ao_max_spins[row].value(),
                        initial_current_ma=self.ao_initial_spins[row].value(),
                    )
                )
        return validate_app_config(
            AppConfig(
                backend=self.backend_combo.currentText(),
                chassis_name=self._chassis_name_text(),
                ai_module_slot=self.ai_slot_spin.value(),
                ao_module_slot=(
                    self.ao_slot_spin.value()
                    if self._supports_analog_output()
                    else self._fallback_ao_slot(self.ai_slot_spin.value())
                ),
                export_directory=normalize_runtime_path_value(self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY),
                sampling=SamplingConfig(
                    acquisition_hz=self.acquisition_hz_spin.value(),
                    display_update_hz=self.display_hz_spin.value(),
                    history_seconds=self.history_seconds_spin.value(),
                ),
                ai_channels=ai_channels,
                ao_channels=ao_channels,
            )
        )

    def _apply_ui_config(self, *, reset_history: bool = True) -> bool:
        try:
            self.config = self._config_from_ui()
        except Exception as exc:
            self._show_error("Configuration Error", str(exc))
            return False
        self._refresh_runtime_summary()
        self._rebuild_monitor_cards()
        self._refresh_monitor_cards()
        if reset_history:
            self._reset_history()
            self._rebuild_plot_curves()
        return True

    def _refresh_runtime_summary(self) -> None:
        active_ai = len([checkbox for checkbox in self.ai_enabled_checks if checkbox.isChecked()])
        self.backend_state_label.setText(f"Backend {self.backend_combo.currentText()}")
        self._set_badge_style(self.backend_state_label, tone="info")
        if self._supports_analog_output():
            active_ao = len([checkbox for checkbox in self.ao_enabled_checks if checkbox.isChecked()])
            self.channel_summary_label.setText(f"AI {active_ai} / AO {active_ao}")
        else:
            self.channel_summary_label.setText(f"{self._input_summary_prefix()} {active_ai}")
        self._set_badge_style(self.channel_summary_label, tone="neutral")
        self.export_state_label.setText(self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY)
        self._set_badge_style(self.export_state_label, tone="muted")
        for row in range(min(self.channel_table.rowCount(), len(self.ai_enabled_checks))):
            button = self.channel_table.cellWidget(row, 1)
            if isinstance(button, QPushButton):
                button.setChecked(self.ai_enabled_checks[row].isChecked())
        self._sync_ai_display_checks_to_enabled()
        self._refresh_readiness_status()

    def _sync_ai_display_checks_to_enabled(self) -> None:
        for enabled_check, plot_check in zip(self.ai_enabled_checks, self.ai_plot_checks):
            desired = enabled_check.isChecked()
            if plot_check.isChecked() == desired:
                continue
            old_state = plot_check.blockSignals(True)
            plot_check.setChecked(desired)
            plot_check.blockSignals(old_state)

    def _refresh_readiness_status(self) -> None:
        if not hasattr(self, "readiness_labels"):
            return
        storage_state = self._storage_readiness_state()
        raw_states = {
            "daq_device": (
                "Ready",
                "info",
                "DAQ controller connected.",
            )
            if self.controller is not None
            else ("Blocked", "error", "Connect the DAQ controller first."),
            "daq_backend": (
                "Ready",
                "info",
                f"Backend {self.backend_combo.currentText()} selected.",
            )
            if self.backend_combo.currentText().strip()
            else ("Blocked", "error", "Select a DAQ backend."),
            "daq_signal": (
                "Ready",
                "running",
                "Live DAQ sample received.",
            )
            if self.latest_inputs
            else ("Pending", "muted", "Start Monitor or Record and wait for a DAQ sample."),
            "stage_device": (
                "Ready",
                "info",
                "Stage controller connected.",
            )
            if hasattr(self, "stage_panel") and self.stage_panel.controller is not None
            else ("Pending", "muted", "Connect the stage when hardware motion is needed."),
            "stage_backend": (
                "Ready",
                "info",
                "Stage motion config loaded.",
            )
            if self.motion_config is not None
            else ("Pending", "muted", "Load a stage motion backend/config."),
            "stage_signal": (
                "Ready",
                "running",
                "Stage position sample received.",
            )
            if any(position is not None for position in self.stage_positions_mm.values())
            else ("Pending", "muted", "Refresh or move the stage to confirm position feedback."),
            "storage": storage_state,
        }

        waiting_for_previous = False
        for key, title in self.READINESS_STEPS:
            label = self.readiness_labels[key]
            state, tone, detail = raw_states[key]
            if waiting_for_previous:
                label.setText(f"{title} Pending")
                label.setToolTip(f"Waiting for an earlier readiness step. Actual state: {state}. {detail}")
                self._set_badge_style(label, tone="muted")
                continue
            label.setText(f"{title} {state}")
            label.setToolTip(detail)
            self._set_badge_style(label, tone=tone)
            if state not in {"Ready", "Warning"}:
                waiting_for_previous = True

    def _storage_readiness_state(self) -> tuple[str, str, str]:
        raw_path = self.export_path_edit.text().strip() or DEFAULT_EXPORT_DIRECTORY
        try:
            export_path = resolve_runtime_path(raw_path)
        except Exception as exc:
            return "Blocked", "error", f"Storage path is invalid: {exc}"
        if export_path.exists() and export_path.is_dir():
            return "Ready", "info", f"Storage folder exists: {export_path}"
        if export_path.exists() and not export_path.is_dir():
            return "Blocked", "error", f"Storage path is not a folder: {export_path}"
        existing_ancestor = next((parent for parent in export_path.parents if parent.exists()), None)
        if existing_ancestor is None:
            return "Blocked", "error", f"Storage path root is missing: {export_path.anchor or export_path.parent}"
        if not existing_ancestor.is_dir():
            return "Blocked", "error", f"Storage path ancestor is not a folder: {existing_ancestor}"
        return "Warning", "warning", f"Storage folder will be created on Record: {export_path}"

    def _update_runtime_controls(self) -> None:
        connected = self.controller is not None
        running = bool(self.controller and self.controller.is_running)
        paused = bool(self.controller and self.controller.is_paused)
        automation_running = self._is_automation_running()
        automation_stopping = automation_running and self.automation_stop_event.is_set()
        if automation_stopping:
            state_text = "Automation Stopping"
            tone = "warning"
        elif automation_running:
            state_text = "Automation Running"
            tone = "running"
        elif running and paused:
            state_text = "Paused"
            tone = "warning"
        elif running:
            state_text = "Running"
            tone = "running"
        elif connected:
            state_text = "Connected"
            tone = "info"
        else:
            state_text = "Disconnected"
            tone = "muted"
        self.session_state_label.setText(state_text)
        self._set_badge_style(self.session_state_label, tone=tone)
        manual_controls_enabled = not automation_running
        self.connect_button.setEnabled(manual_controls_enabled and not running)
        daq_setup_enabled = manual_controls_enabled and not running
        if hasattr(self, "backend_combo"):
            self.backend_combo.setEnabled(daq_setup_enabled)
        if hasattr(self, "chassis_name_edit"):
            self.chassis_name_edit.setEnabled(daq_setup_enabled)
        if hasattr(self, "refresh_daq_devices_button"):
            self.refresh_daq_devices_button.setEnabled(
                daq_setup_enabled and self.backend_combo.currentText() == "ni"
            )
        if hasattr(self, "monitor_button"):
            self.monitor_button.setEnabled(manual_controls_enabled and connected and not running)
        self.start_button.setEnabled(manual_controls_enabled and connected and not running)
        self.pause_button.setEnabled(manual_controls_enabled and running and not paused)
        self.resume_button.setEnabled(manual_controls_enabled and running and paused)
        self.stop_button.setEnabled(manual_controls_enabled and (connected or running or self.csv_recorder.is_active))
        output_controls_enabled = self._supports_analog_output() and connected and manual_controls_enabled
        self.apply_outputs_button.setEnabled(output_controls_enabled)
        self.zero_outputs_button.setEnabled(output_controls_enabled)
        self.mark_start_button.setEnabled(manual_controls_enabled and running and not paused and self.active_highlight_start_s is None)
        self.mark_stop_button.setEnabled(manual_controls_enabled and running and self.active_highlight_start_s is not None)
        if hasattr(self, "stage_mark_start_button"):
            self.stage_mark_start_button.setEnabled(manual_controls_enabled)
        if hasattr(self, "stage_mark_stop_button"):
            self.stage_mark_stop_button.setEnabled(manual_controls_enabled)
        if hasattr(self, "load_recipe_button"):
            self.load_recipe_button.setEnabled(not automation_running)
        if hasattr(self, "recipe_helper_button"):
            self.recipe_helper_button.setEnabled(not automation_running)
        contact_detection_ready = True
        if hasattr(self, "contact_detect_check"):
            contact_detection_ready = (not self.contact_detect_check.isChecked()) or self.motion_config is not None
        soft_limit_ready = self._stage_soft_limit_error() is None
        origin_ready = self._origin_confirmed_for_run()
        if hasattr(self, "run_automation_button"):
            self.run_automation_button.setEnabled(
                not automation_running
                and self.automation_recipe is not None
                and not running
                and contact_detection_ready
                and soft_limit_ready
                and origin_ready
            )
        if hasattr(self, "stop_automation_button"):
            self.stop_automation_button.setEnabled(automation_running)
        self._sync_manual_stage_runtime_limits()
        if self.active_highlight_start_s is None:
            self.mark_state_label.setText(f"Marks {len(self.highlight_intervals)}")
            self._set_badge_style(self.mark_state_label, tone="muted")
        else:
            self.mark_state_label.setText(f"Marking {self.active_highlight_start_s:.3f}s")
            self._set_badge_style(self.mark_state_label, tone="warning")
        self._refresh_readiness_status()
        self._update_run_scenario()

    def _is_automation_running(self) -> bool:
        return self.automation_thread is not None and self.automation_thread.is_alive()

    def _update_run_scenario(self) -> None:
        if not hasattr(self, "scenario_hint_label"):
            return
        recipe_loaded = self.automation_recipe is not None
        session_snapshot_loaded = self.recipe_path_edit.text().strip().startswith("session:")
        contact_enabled = self.contact_detect_check.isChecked()
        motion_loaded = self.motion_config is not None
        origin_required = self._motion_origin_confirmation_required()
        safety_confirmed = self._origin_confirmed_for_run()
        soft_limit_error = self._stage_soft_limit_error()
        automation_running = self._is_automation_running()
        manual_running = bool(self.controller and self.controller.is_running)
        run_ready = self.run_automation_button.isEnabled() if hasattr(self, "run_automation_button") else False

        self.scenario_setup_label.setText("1 Setup OK")
        self._set_badge_style(self.scenario_setup_label, tone="info")

        if recipe_loaded:
            recipe_text = self.recipe_path_edit.text().strip()
            if recipe_text.startswith("session:"):
                self.scenario_recipe_label.setText("2 Session Snapshot")
                self._set_badge_style(self.scenario_recipe_label, tone="info")
            else:
                self.scenario_recipe_label.setText("2 Recipe Ready")
                self._set_badge_style(self.scenario_recipe_label, tone="info")
        else:
            self.scenario_recipe_label.setText("2 Recipe Missing")
            self._set_badge_style(self.scenario_recipe_label, tone="warning")

        if soft_limit_error is not None:
            self.scenario_safety_label.setText("3 Limit Invalid")
            self._set_badge_style(self.scenario_safety_label, tone="error")
        elif contact_enabled and not motion_loaded:
            self.scenario_safety_label.setText("3 Motion Required")
            self._set_badge_style(self.scenario_safety_label, tone="warning")
        elif origin_required and not safety_confirmed:
            self.scenario_safety_label.setText("3 Origin Pending")
            self._set_badge_style(self.scenario_safety_label, tone="warning")
        elif motion_loaded:
            self.scenario_safety_label.setText("3 Safety Ready")
            self._set_badge_style(self.scenario_safety_label, tone="info")
        else:
            self.scenario_safety_label.setText("3 Dry Run Mode")
            self._set_badge_style(self.scenario_safety_label, tone="muted")

        status_text = self.automation_status_label.text().strip().lower() if hasattr(self, "automation_status_label") else ""
        if automation_running:
            self.scenario_run_label.setText("4 Running")
            self._set_badge_style(self.scenario_run_label, tone="running")
        elif session_snapshot_loaded:
            self.scenario_run_label.setText("4 Snapshot Loaded")
            self._set_badge_style(self.scenario_run_label, tone="info")
        elif run_ready:
            self.scenario_run_label.setText("4 Ready")
            self._set_badge_style(self.scenario_run_label, tone="info")
        elif status_text in {"completed"}:
            self.scenario_run_label.setText("4 Review Complete")
            self._set_badge_style(self.scenario_run_label, tone="info")
        elif status_text in {"failed", "cancelled"}:
            self.scenario_run_label.setText("4 Review Required")
            self._set_badge_style(self.scenario_run_label, tone="warning")
        else:
            self.scenario_run_label.setText("4 Blocked")
            self._set_badge_style(self.scenario_run_label, tone="muted")

        if automation_running:
            hint = "Automation is running. Monitor Safety and phase progress before touching motion controls."
        elif manual_running:
            hint = "Manual acquisition is active. Stop it before automation so the run path is deterministic."
        elif soft_limit_error is not None:
            hint = soft_limit_error
        elif not recipe_loaded:
            hint = "Start with Recipe Load, Protocol, or Session reopen depending on whether this is a new run or a review."
        elif contact_enabled and not motion_loaded:
            hint = "Contact detect is on. Load a motion config first or turn Contact off for a dry run."
        elif origin_required and not safety_confirmed:
            hint = "Check Origin Confirmed in the Stage section after verifying the current hardware reference."
        elif self.recipe_path_edit.text().strip().startswith("session:"):
            hint = "This is a reopened session snapshot. Review results, then load a new recipe when ready for the next run."
        elif run_ready:
            hint = "Scenario is ready. Review target path and press Run Auto."
        else:
            hint = "Finish the remaining setup items in order before running automation."
        self.scenario_hint_label.setText(hint)

    def _make_backend(self, config: AppConfig):
        if config.backend == "simulation":
            return SimulatedBackend(config)
        if config.backend == "ni":
            return NiDaqBackend(config)
        raise RuntimeError(f"Unsupported backend: {config.backend}")

    def _controller_matches_config(self) -> bool:
        return self.controller is not None and self.controller.backend.config == self.config

    def _dispose_controller(self) -> None:
        if self.controller is not None:
            try:
                self.controller.stop()
            finally:
                self.controller = None

    def _connect_backend(self) -> None:
        if not self._apply_ui_config(reset_history=False):
            return
        try:
            self._dispose_controller()
            self.controller = AcquisitionController(self._make_backend(self.config), self.config.sampling.acquisition_hz)
            message = self.controller.connect()
            self._update_runtime_controls()
            self._log(message)
            self.statusBar().showMessage(message, 5000)
        except Exception as exc:
            self._dispose_controller()
            self._update_runtime_controls()
            self._show_error("Connection Failed", str(exc))

    def _prepare_measurement_session(self, started_at: datetime) -> tuple[Path, Path]:
        session_label = self.session_label_edit.text().strip()
        session_paths = prepare_session_paths(
            self.config.export_directory,
            started_at=started_at,
            session_label=session_label,
            session_prefix="session" if session_label else "measurement",
        )
        self._log(f"Export root created: {session_paths.export_root}")
        self._log(f"Session directory created: {session_paths.session_dir}")
        return session_paths.session_dir, session_paths.data_path

    def _start_live_monitor(self) -> None:
        if self._is_automation_running():
            self._show_error("Automation Running", "Stop automation before starting live monitor.")
            return
        if not self._apply_ui_config():
            return
        try:
            if self.controller is None or not self._controller_matches_config():
                self._connect_backend()
            if self.controller is None:
                return
            self._reset_history()
            self.controller.start()
            poll_ms = max(50, int(1000 / max(self.config.sampling.display_update_hz, 1.0)))
            self.poll_timer.start(poll_ms)
            self._update_runtime_controls()
            self._log("Live monitor started")
        except Exception as exc:
            self._stop_measurement()
            self._show_error("Live Monitor Failed", str(exc))

    def _start_measurement(self) -> None:
        if self._is_automation_running():
            self._show_error("Automation Running", "Stop automation before starting manual measurement.")
            return
        if not self._apply_ui_config():
            return
        try:
            if self.controller is None or not self._controller_matches_config():
                self._connect_backend()
            if self.controller is None:
                return
            started_at = datetime.now()
            session_dir, csv_path = self._prepare_measurement_session(started_at)
            if hasattr(self, "csv_save_interval_spin"):
                self.csv_recorder.FLUSH_INTERVAL_S = self.csv_save_interval_spin.value()
                self.csv_recorder.FSYNC_INTERVAL_S = max(self.csv_recorder.FSYNC_INTERVAL_S, self.csv_save_interval_spin.value())
            self.csv_recorder.start(csv_path, self.config.ai_channels, self.config.ao_channels)
            self._reset_history()
            self.controller.start()
            poll_ms = max(50, int(1000 / max(self.config.sampling.display_update_hz, 1.0)))
            self.poll_timer.start(poll_ms)
            self._update_runtime_controls()
            self._log(f"Measurement started: {session_dir}")
        except Exception as exc:
            self._stop_measurement()
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
        summary = self.csv_recorder.stop()
        self._update_runtime_controls()
        if summary is not None:
            self._log(f"Measurement stopped: {summary.path}")

    def _apply_outputs(self) -> None:
        if not self._supports_analog_output():
            return
        if not self._apply_ui_config(reset_history=False):
            return
        try:
            if self.controller is None or not self._controller_matches_config():
                self._connect_backend()
            if self.controller is None:
                return
            currents = {
                row: self.ao_setpoint_spins[row].value()
                for row in range(self.ao_table.rowCount())
                if self.ao_enabled_checks[row].isChecked()
            }
            states = self.controller.backend.write_output_currents(currents)
            self.latest_outputs = {state.channel_index: state for state in states}
            max_points = max(1, int(self.history_seconds_spin.value() * max(self.acquisition_hz_spin.value(), 1.0)))
            for state in states:
                history = self.output_history.setdefault(state.channel_index, deque(maxlen=max_points))
                history.append((self.latest_elapsed_s, state.current_ma))
            self._refresh_output_table()
            self._refresh_monitor_cards()
            self._refresh_plot()
            self._log(", ".join(f"{state.channel_name}={state.current_ma:.3f} mA" for state in states))
        except Exception as exc:
            self._show_error("Output Apply Failed", str(exc))

    def _zero_outputs(self) -> None:
        if not self._supports_analog_output():
            return
        for spin in self.ao_setpoint_spins:
            spin.setValue(0.0)
        self._apply_outputs()

    def _poll_frames(self) -> None:
        if self.controller is None:
            return
        failure = self.controller.pop_failure()
        try:
            dropped_frames = self.controller.take_dropped_frame_count()
            frames = self.controller.drain_frames()
            for frame in frames:
                self.csv_recorder.append(frame)
                self._process_frame(frame)
        except Exception as exc:
            self._handle_runtime_failure(exc)
            return
        if dropped_frames > 0:
            self._log(
                f"Frame buffer overflow: dropped {dropped_frames} frames while the UI/export loop was catching up."
            )
        if frames:
            self._refresh_input_table()
            self._refresh_output_table()
            self._refresh_monitor_cards()
            self._refresh_plot()
            self._refresh_readiness_status()
        if failure is not None:
            self._handle_runtime_failure(failure)

    def _process_frame(self, frame: MeasurementFrame) -> None:
        self.latest_elapsed_s = frame.elapsed_s
        if self.active_highlight_region is not None and self.active_highlight_start_s is not None:
            self.active_highlight_region.setRegion((self.active_highlight_start_s, self.latest_elapsed_s))
        for reading in frame.inputs:
            self.latest_inputs[reading.channel_index] = reading
            self.history[reading.channel_index].append((frame.elapsed_s, reading.voltage, reading.scaled_value))
        for state in frame.outputs:
            self.latest_outputs[state.channel_index] = state
            self.output_history[state.channel_index].append((frame.elapsed_s, state.current_ma))

    def _handle_runtime_failure(self, exc: Exception) -> None:
        self._close_active_highlight_interval()
        self.poll_timer.stop()
        self._dispose_controller()
        self.csv_recorder.stop()
        self._update_runtime_controls()
        self._show_error("Measurement Failed", str(exc))

    def _reset_history(self) -> None:
        max_points = max(1, int(self.history_seconds_spin.value() * max(self.acquisition_hz_spin.value(), 1.0)))
        self.history = {row: deque(maxlen=max_points) for row in range(self.ai_table.rowCount())}
        self.output_history = {row: deque(maxlen=max_points) for row in range(self.ao_table.rowCount())}
        self.latest_inputs.clear()
        self.latest_outputs.clear()
        self.latest_elapsed_s = 0.0
        self._clear_highlight_intervals()
        self._refresh_input_table()
        self._refresh_output_table()
        self._refresh_monitor_cards()
        self._refresh_plot()
        self._refresh_readiness_status()

    def _refresh_input_table(self) -> None:
        for row in range(self.ai_table.rowCount()):
            reading = self.latest_inputs.get(row)
            self.ai_voltage_items[row].setText("--" if reading is None else f"{reading.voltage:.6f} V")
            self.ai_value_items[row].setText("--" if reading is None else f"{reading.scaled_value:.6f} {reading.unit}")
            self.ai_status_items[row].setText("--" if reading is None else reading.status)

    def _refresh_output_table(self) -> None:
        for row in range(self.ao_table.rowCount()):
            state = self.latest_outputs.get(row)
            self.ao_live_items[row].setText("--" if state is None else f"{state.current_ma:.3f}")

    def _refresh_monitor_cards(self) -> None:
        for row, widgets in self.ai_card_widgets.items():
            value_label, detail_label, status_label, limit_check = widgets
            reading = self.latest_inputs.get(row)
            unit = self.ai_unit_items[row].text().strip() or "V"
            if reading is None:
                value_label.setText("--")
                detail_label.setText(f"Voltage -- | Value -- {unit}")
                status_label.setText("No signal" if limit_check.isChecked() else "Status --")
                continue
            value_label.setText(f"{reading.scaled_value:.4f} {reading.unit}")
            detail_label.setText(f"Voltage {reading.voltage:.5f} V")
            status_label.setText("Limit No rule" if limit_check.isChecked() else f"Status {reading.status}")

        for row, widgets in self.ao_card_widgets.items():
            value_label, detail_label, status_label, limit_check = widgets
            state = self.latest_outputs.get(row)
            minimum = self.ao_min_spins[row].value()
            maximum = self.ao_max_spins[row].value()
            if state is None:
                value_label.setText("--")
                detail_label.setText(f"Range {minimum:.3f} .. {maximum:.3f} mA")
                status_label.setText("No signal" if limit_check.isChecked() else "Output idle")
                continue
            value_label.setText(f"{state.current_ma:.3f} mA")
            detail_label.setText(f"Range {minimum:.3f} .. {maximum:.3f} mA")
            if limit_check.isChecked():
                if state.current_ma < minimum:
                    status_text = "Limit Low"
                elif state.current_ma > maximum:
                    status_text = "Limit High"
                else:
                    status_text = "Limit OK"
            else:
                status_text = "Output applied"
            status_label.setText(status_text)

    def _refresh_plot(self) -> None:
        range_limit = self.RANGE_OPTIONS[self.range_combo.currentText()]
        show_scaled = self.ai_plot_mode_combo.currentText() == "Scaled"
        show_ao_overlay = self._supports_analog_output() and self.ao_overlay_checkbox.isChecked()
        self.plot_widget.setLabel(
            "left",
            "Scaled Value" if show_scaled else "Raw Voltage",
            units="" if show_scaled else "V",
        )
        self.plot_widget.getAxis("right").setLabel("AO Current", units="mA", color="#F4A261")
        if show_ao_overlay:
            self.plot_widget.showAxis("right")
        else:
            self.plot_widget.hideAxis("right")
        for row, curve in self.input_curves.items():
            if not self.ai_enabled_checks[row].isChecked() or not self.ai_plot_checks[row].isChecked():
                curve.setData([], [])
                continue
            values = list(self.history.get(row, deque()))
            if range_limit is not None and values:
                latest_elapsed = values[-1][0]
                values = [item for item in values if latest_elapsed - item[0] <= range_limit]
            curve.setData(
                [item[0] for item in values],
                [item[2] if show_scaled else item[1] for item in values],
            )
        for row, curve in self.output_curves.items():
            if not show_ao_overlay or not self.ao_enabled_checks[row].isChecked():
                curve.setData([], [])
                continue
            values = list(self.output_history.get(row, deque()))
            if range_limit is not None and values:
                latest_elapsed = values[-1][0]
                values = [item for item in values if latest_elapsed - item[0] <= range_limit]
            curve.setData([item[0] for item in values], [item[1] for item in values])
        for row in range(self.ai_table.rowCount()):
            values = list(self.history.get(row, deque()))
            if range_limit is not None and values:
                latest_elapsed = values[-1][0]
                values = [item for item in values if latest_elapsed - item[0] <= range_limit]
            resistance_curve = self.resistance_curves.get(row)
            voltage_curve = self.voltage_curves.get(row)
            if resistance_curve is not None:
                if self.resistance_plot_checkbox.isChecked() and self.ai_enabled_checks[row].isChecked():
                    resistance_curve.setData([item[0] for item in values], [item[2] for item in values], symbol="o")
                else:
                    resistance_curve.setData([], [])
            if voltage_curve is not None:
                if self.voltage_plot_checkbox.isChecked() and self.ai_enabled_checks[row].isChecked():
                    voltage_curve.setData([item[0] for item in values], [item[1] for item in values], symbol="o")
                else:
                    voltage_curve.setData([], [])
        self.plot_widget.getPlotItem().vb.autoRange()
        if show_ao_overlay:
            self.ao_viewbox.autoRange()

    def _clear_daq_plot_view(self) -> None:
        for values in self.history.values():
            values.clear()
        for values in self.output_history.values():
            values.clear()
        self._clear_highlight_intervals()
        self._refresh_plot()
        self._log("DAQ plot cleared")

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
        self.highlight_markers.clear()
        self.active_highlight_start_s = None
        self.active_highlight_region = None
        self._update_runtime_controls()

    def _start_highlight_interval(self) -> None:
        if not self.controller or not self.controller.is_running or self.active_highlight_start_s is not None:
            return
        self.active_highlight_start_s = self.latest_elapsed_s
        self.active_highlight_region = self._create_highlight_region(self.latest_elapsed_s, self.latest_elapsed_s)
        self._update_runtime_controls()
        self._log(f"Highlight start @ {self.latest_elapsed_s:.3f}s")

    def _close_active_highlight_interval(self) -> bool:
        if self.active_highlight_start_s is None or self.active_highlight_region is None:
            return False
        end_s = max(self.latest_elapsed_s, self.active_highlight_start_s)
        self.active_highlight_region.setRegion((self.active_highlight_start_s, end_s))
        self.highlight_intervals.append((self.active_highlight_start_s, end_s))
        self.highlight_regions.append(self.active_highlight_region)
        self.highlight_markers.append(
            {
                "name": f"DAQ Mark {len(self.highlight_intervals)}",
                "kind": "interval",
                "start_s": self.active_highlight_start_s,
                "end_s": end_s,
                "color": "#F0C241",
            }
        )
        self._log(f"Highlight stop @ {end_s:.3f}s")
        self.active_highlight_start_s = None
        self.active_highlight_region = None
        self._update_runtime_controls()
        return True

    def _stop_highlight_interval(self) -> None:
        self._close_active_highlight_interval()

    def _rebuild_highlight_markers_from_payload(self, markers: list[dict[str, Any]]) -> None:
        self._clear_highlight_intervals()
        for marker in markers:
            start_s = float(marker.get("start_s", 0.0))
            end_s = float(marker.get("end_s", start_s))
            color = str(marker.get("color", "#F0C241"))
            region = pg.LinearRegionItem(
                values=(start_s, end_s),
                orientation="vertical",
                movable=False,
                brush=pg.mkBrush(QColor(color).red(), QColor(color).green(), QColor(color).blue(), 45),
                pen=pg.mkPen(color, width=1),
                hoverBrush=pg.mkBrush(QColor(color).red(), QColor(color).green(), QColor(color).blue(), 55),
                hoverPen=pg.mkPen(color, width=1),
            )
            region.setZValue(-5)
            self.plot_widget.addItem(region)
            self.highlight_intervals.append((start_s, end_s))
            self.highlight_regions.append(region)
            self.highlight_markers.append(
                {
                    "name": str(marker.get("name", f"DAQ Mark {len(self.highlight_markers) + 1}")),
                    "kind": str(marker.get("kind", "interval")),
                    "start_s": start_s,
                    "end_s": end_s,
                    "color": color,
                }
            )
        self._update_runtime_controls()

    def _choose_export_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Export Directory",
            str(resolve_runtime_path(self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY)),
        )
        if selected:
            self.export_path_edit.setText(normalize_runtime_path_value(selected))
            self._refresh_runtime_summary()

    def _load_config_dialog(self) -> None:
        if self.controller and self.controller.is_running:
            self._show_error("Load Blocked", "Stop the measurement before loading a configuration.")
            return
        if self._is_automation_running():
            self._show_error("Load Blocked", "Stop automation before loading a configuration.")
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
            self._stop_measurement()
            self.config_path = resolve_runtime_path(file_path)
            self.config = self._config_for_profile(load_config(self.config_path))
            self._load_config_into_widgets(self.config)
            self._reset_history()
            self._refresh_runtime_summary()
            self._update_runtime_controls()
            self._log(f"Loaded config: {self.config_path}")
        except Exception as exc:
            self._show_error("Load Failed", str(exc))

    def _save_config_dialog(self) -> None:
        if not self._apply_ui_config(reset_history=False):
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

    def _process_sample(self, sample: MeasurementSample) -> None:
        frame = MeasurementFrame(
            timestamp=sample.timestamp,
            elapsed_s=sample.elapsed_s,
            inputs=[
                AnalogInputReading(
                    channel_index=reading.channel_index,
                    channel_name=reading.channel_name,
                    voltage=reading.voltage,
                    scaled_value=reading.resistance_ohm,
                    unit="ohm",
                    status=reading.status,
                )
                for reading in sample.readings
            ],
            outputs=[],
        )
        self._process_frame(frame)
        self._refresh_input_table()
        self._refresh_monitor_cards()

    def _stop_recorder(self) -> None:
        summary = self.csv_recorder.stop()
        if summary is not None:
            self._log(f"CSV closed: {summary.path} (rows={summary.rows_written})")

    def _show_error(self, title: str, message: str) -> None:
        self._log(f"{title}: {message}")
        QMessageBox.critical(self, title, message)

    def _update_contact_detection_controls(self) -> None:
        enabled = self.contact_detect_check.isChecked()
        for widget in (
            self.contact_use_zero_check,
            self.contact_axis_spin,
            self.contact_channel_spin,
            self.contact_speed_spin,
            self.contact_step_spin,
            self.contact_travel_spin,
            self.contact_threshold_spin,
            self.contact_baseline_spin,
            self.contact_stable_spin,
        ):
            widget.setEnabled(enabled)
        if enabled:
            if self.motion_config is None:
                self.contact_summary_label.setText("CD on | motion req")
                self._set_badge_style(self.contact_summary_label, tone="warning")
            else:
                self.contact_summary_label.setText(
                    f"CD on | {self.contact_speed_spin.value():g} mm/s | dR {self.contact_threshold_spin.value():g}"
                )
                self._set_badge_style(self.contact_summary_label, tone="info")
        else:
            self.contact_summary_label.setText("Contact detect off")
            self._set_badge_style(self.contact_summary_label, tone="muted")
        if hasattr(self, "safety_panel"):
            self.safety_panel.set_contact_detection_summary(
                enabled=enabled,
                axis=self.contact_axis_spin.value(),
                channel_index=self.contact_channel_spin.value(),
                speed_mm_s=self.contact_speed_spin.value(),
                threshold_ohm=self.contact_threshold_spin.value(),
                motion_required=enabled and self.motion_config is None,
            )
        if hasattr(self, "run_automation_button"):
            self._update_runtime_controls()

    def _read_contact_signal(self, channel_index: int) -> float:
        reading = self.latest_inputs.get(channel_index)
        if reading is None:
            raise RuntimeError(
                f"Waiting for DAQ sample on channel {channel_index}. Confirm Monitor or Record is running."
            )
        return reading.scaled_value

    def _contact_calibration_signal_source(self) -> tuple[Callable[[int], float] | None, Callable[[], None]]:
        if self.controller is None or not self.controller.is_running:
            if not self._apply_ui_config(reset_history=False):
                return None, lambda: None
            if self.controller is not None:
                self._dispose_controller()
                self._update_runtime_controls()
            preview_controller = AcquisitionController(
                self._make_backend(self.config),
                self.config.sampling.acquisition_hz,
            )
            latest_readings: dict[int, AnalogInputReading] = {}
            latest_lock = threading.Lock()

            try:
                message = preview_controller.connect()
                preview_controller.start()
            except Exception as exc:
                try:
                    preview_controller.stop()
                except Exception:
                    pass
                self._show_error("Contact Calibration", f"Failed to start DAQ preview: {exc}")
                return None, lambda: None

            self._log(f"Contact calibration DAQ preview started: {message}")

            def read_preview_signal(channel_index: int) -> float:
                with latest_lock:
                    failure = preview_controller.pop_failure()
                    if failure is not None:
                        raise RuntimeError(f"Contact calibration DAQ preview failed: {failure}") from failure
                    for frame in preview_controller.drain_frames():
                        for reading in frame.inputs:
                            latest_readings[reading.channel_index] = reading
                    reading = latest_readings.get(channel_index)
                    if reading is None:
                        raise RuntimeError(f"Waiting for DAQ sample on channel {channel_index}.")
                    return reading.scaled_value

            def cleanup_preview() -> None:
                try:
                    preview_controller.stop()
                finally:
                    self._log("Contact calibration DAQ preview stopped")
                    self._update_runtime_controls()

            return read_preview_signal, cleanup_preview

        return self._read_contact_signal, lambda: None

    def _open_contact_calibration_dialog(self) -> None:
        read_signal, cleanup_signal_source = self._contact_calibration_signal_source()
        if read_signal is None:
            return
        motion = self.stage_panel.controller if hasattr(self, "stage_panel") else None
        result: ContactCalibrationResult | None = None
        if hasattr(self, "stage_panel"):
            self.stage_panel.set_live_status_polling(False)
        try:
            dialog = ContactCalibrationDialog(
                motion=motion,
                read_signal=read_signal,
                soft_limit_checker=self._stage_target_allowed,
                parent=self,
            )
            dialog.channel_spin.setValue(self.contact_channel_spin.value())
            dialog.speed_spin.setValue(self.contact_speed_spin.value())
            dialog.step_spin.setValue(self.contact_step_spin.value())
            dialog.travel_spin.setValue(self.contact_travel_spin.value())
            dialog.threshold_spin.setValue(self.contact_threshold_spin.value())
            dialog.baseline_spin.setValue(self.contact_baseline_spin.value())
            if dialog.exec() == QDialog.DialogCode.Accepted:
                result = dialog.result
        finally:
            if hasattr(self, "stage_panel"):
                self.stage_panel.set_live_status_polling(True)
                if self.stage_panel.controller is not None:
                    self.stage_panel.refresh_status()
            cleanup_signal_source()
        if result is None:
            return
        self.contact_point_position_mm = result.selected_position_mm
        self._set_stage_dashboard_style(
            self.stage_contact_state_label,
            f"Contact {result.selected_position_mm:.3f} mm",
            "info",
        )
        self.contact_summary_label.setText(f"Contact calibrated at {result.selected_position_mm:.6g} mm")
        self._set_badge_style(self.contact_summary_label, tone="info")
        self._log(
            "Contact calibrated: "
            f"selected={result.selected_position_mm:.6g} mm "
            f"recommended={result.recommended_position_mm if result.recommended_position_mm is not None else '--'}"
        )

    def _contact_detection_metadata_from_ui(self) -> dict[str, Any]:
        if not self.contact_detect_check.isChecked():
            return {"enable_contact_detection": False}
        return {
            "enable_contact_detection": True,
            "contact_stage_axis": self.contact_axis_spin.value(),
            "contact_channel_index": self.contact_channel_spin.value(),
            "contact_scan_speed_mm_s": self.contact_speed_spin.value(),
            "contact_scan_step_mm": self.contact_step_spin.value(),
            "contact_max_travel_mm": self.contact_travel_spin.value(),
            "contact_delta_resistance_threshold_ohm": self.contact_threshold_spin.value(),
            "contact_baseline_duration_s": self.contact_baseline_spin.value(),
            "contact_stable_duration_s": self.contact_stable_spin.value(),
            "contact_use_as_zero": self.contact_use_zero_check.isChecked(),
        }

    def _apply_contact_detection_metadata(self, recipe) -> None:
        payload = self._contact_detection_metadata_payload(getattr(recipe, "metadata", {}) or {})
        enabled = self._metadata_bool(payload.get("enable_contact_detection"), False)
        self.contact_detect_check.setChecked(enabled)
        self.contact_axis_spin.setValue(int(payload.get("contact_stage_axis", 1)))
        if payload.get("contact_channel_index") is not None:
            self.contact_channel_spin.setValue(int(payload.get("contact_channel_index", 0)))
        else:
            self.contact_channel_spin.setValue(0)
        self.contact_speed_spin.setValue(float(payload.get("contact_scan_speed_mm_s", 0.02)))
        self.contact_step_spin.setValue(float(payload.get("contact_scan_step_mm", 0.01)))
        self.contact_travel_spin.setValue(float(payload.get("contact_max_travel_mm", 1.0)))
        self.contact_threshold_spin.setValue(float(payload.get("contact_delta_resistance_threshold_ohm", 1.0)))
        self.contact_baseline_spin.setValue(float(payload.get("contact_baseline_duration_s", 0.2)))
        self.contact_stable_spin.setValue(float(payload.get("contact_stable_duration_s", 0.05)))
        self.contact_use_zero_check.setChecked(self._metadata_bool(payload.get("contact_use_as_zero"), True))
        self._update_contact_detection_controls()

    def _recipe_for_execution(self, recipe):
        base_metadata = dict(getattr(recipe, "metadata", {}) or {})
        base_metadata.update(self._contact_detection_metadata_from_ui())
        base_metadata["contact_detection"] = dict(self._contact_detection_metadata_from_ui())
        steps = list(recipe.steps)
        if self._recipe_uses_contact_relative_coordinates(base_metadata):
            contact_position = self.contact_point_position_mm
            if contact_position is None:
                raise ValueError("Contact-relative recipe requires an applied contact point. Run Contact Cal. first.")
            direction = self._contact_relative_press_direction(base_metadata)
            absolute_steps = []
            clamp_messages: list[str] = []
            for step in recipe.steps:
                if step.target_displacement is None:
                    absolute_steps.append(deepcopy(step))
                    continue
                absolute_step = deepcopy(step)
                press_depth_mm = float(step.target_displacement)
                if press_depth_mm < 0:
                    raise ValueError(
                        f"Contact-relative step {step.step_id!r} has negative press depth {press_depth_mm:g} mm."
                    )
                absolute_step.target_displacement = contact_position + (direction * press_depth_mm)
                absolute_step.target_displacement, clamp_message = self._clamp_contact_relative_target(
                    step_id=step.step_id,
                    press_depth_mm=press_depth_mm,
                    contact_position_mm=contact_position,
                    target_position_mm=absolute_step.target_displacement,
                )
                if clamp_message:
                    clamp_messages.append(clamp_message)
                absolute_step.notes = self._contact_relative_step_note(
                    original_notes=step.notes,
                    press_depth_mm=press_depth_mm,
                    contact_position_mm=contact_position,
                    target_position_mm=absolute_step.target_displacement,
                )
                absolute_steps.append(absolute_step)
            steps = absolute_steps
            base_metadata["contact_position_mm"] = contact_position
            base_metadata["resolved_coordinate_mode"] = "absolute_stage_mm"
            base_metadata["source_coordinate_mode"] = "contact_relative"
            if clamp_messages:
                base_metadata["contact_relative_clamped_steps"] = list(clamp_messages)
                self._show_contact_relative_clamp_warning(clamp_messages)
        return recipe.__class__(
            recipe_id=recipe.recipe_id,
            steps=steps,
            metadata=base_metadata,
        )

    def _recipe_uses_contact_relative_coordinates(self, metadata: dict[str, Any]) -> bool:
        mode = str(metadata.get("coordinate_mode", "")).strip().lower()
        if mode == "contact_relative":
            return True
        contact_relative = metadata.get("contact_relative")
        return isinstance(contact_relative, dict) and self._metadata_bool(contact_relative.get("enabled"), False)

    def _contact_relative_press_direction(self, metadata: dict[str, Any]) -> float:
        contact_relative = metadata.get("contact_relative")
        if isinstance(contact_relative, dict) and contact_relative.get("press_direction") is not None:
            direction = float(contact_relative.get("press_direction"))
        else:
            direction = float(metadata.get("contact_press_direction", -1.0))
        if direction == 0:
            raise ValueError("Contact-relative press_direction must not be zero.")
        return 1.0 if direction > 0 else -1.0

    def _stage_motion_bounds(self) -> tuple[float, float]:
        if hasattr(self, "stage_soft_limit_check") and self.stage_soft_limit_check.isChecked():
            return self.stage_soft_min_spin.value(), self.stage_soft_max_spin.value()
        if hasattr(self, "stage_soft_limit_check"):
            return -float("inf"), float("inf")
        if self.motion_config is not None and self.motion_config.enforce_software_limits:
            return self.motion_config.min_position_mm, self.motion_config.max_position_mm
        return -float("inf"), float("inf")

    def _clamp_contact_relative_target(
        self,
        *,
        step_id: str,
        press_depth_mm: float,
        contact_position_mm: float,
        target_position_mm: float,
    ) -> tuple[float, str | None]:
        min_position, max_position = self._stage_motion_bounds()
        if min_position <= target_position_mm <= max_position:
            return target_position_mm, None
        clamped_target = min(max(target_position_mm, min_position), max_position)
        applied_press_depth = abs(contact_position_mm - clamped_target)
        boundary = "minimum" if target_position_mm < min_position else "maximum"
        message = (
            f"{step_id}: requested press {press_depth_mm:.6g} mm -> target {target_position_mm:.6g} mm, "
            f"clamped to {boundary} {clamped_target:.6g} mm "
            f"(actual press {applied_press_depth:.6g} mm)."
        )
        return clamped_target, message

    def _show_contact_relative_clamp_warning(self, clamp_messages: list[str]) -> None:
        preview = "\n".join(clamp_messages[:6])
        if len(clamp_messages) > 6:
            preview = f"{preview}\n... and {len(clamp_messages) - 6} more step(s)."
        QMessageBox.warning(
            self,
            "Contact-relative Limit",
            "Some contact-relative steps would move outside the configured soft limit, "
            "so they were automatically limited to the nearest allowed stage position.\n\n"
            f"{preview}",
        )

    def _contact_relative_step_note(
        self,
        *,
        original_notes: str,
        press_depth_mm: float,
        contact_position_mm: float,
        target_position_mm: float,
    ) -> str:
        suffix = (
            f"press_depth={press_depth_mm:.6g} mm, "
            f"contact={contact_position_mm:.6g} mm, target={target_position_mm:.6g} mm"
        )
        return f"{original_notes} | {suffix}" if original_notes else suffix

    def _contact_detection_metadata_payload(self, metadata: dict[str, Any]) -> dict[str, Any]:
        if not metadata:
            return {}
        payload = dict(metadata)
        nested = payload.get("contact_detection")
        if isinstance(nested, dict):
            payload.update(nested)
        return payload

    def _metadata_bool(self, value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def _configure_automation_progress(self, recipe) -> None:
        self.automation_progress_estimator = AutomationProgressEstimator(
            recipe,
            ProgressEstimatorConfig(
                acquisition_hz=self.acquisition_hz_spin.value(),
                default_move_duration_s=0.5,
                default_disengage_duration_s=0.25,
            ),
        )
        self.automation_completed_steps = 0
        self.automation_current_step_index = None
        self.automation_current_phase = ""
        self.automation_started_at = None
        self.automation_phase_started_at = None
        self._reset_automation_progress()
        self._refresh_orchestration_step_list()

    def _refresh_orchestration_step_list(self) -> None:
        if not hasattr(self, "orchestration_step_list"):
            return
        if self.automation_recipe is None:
            self.orchestration_step_list.setPlainText("")
            self.orchestration_step_list.setExtraSelections([])
            return
        lines: list[str] = []
        metadata = dict(getattr(self.automation_recipe, "metadata", {}) or {})
        contact_relative = self._recipe_uses_contact_relative_coordinates(metadata)
        for index, step in enumerate(self.automation_recipe.steps, start=1):
            if self.automation_completed_steps >= index:
                prefix = "[done]"
            elif self.automation_current_step_index == index:
                prefix = "[run ]"
            else:
                prefix = "[wait]"
            phase = step.phase or "step"
            step_id = step.step_id or f"step_{index}"
            if step.target_displacement is None:
                target = "--"
            elif contact_relative:
                target = f"press {step.target_displacement:g} mm"
            else:
                target = f"{step.target_displacement:g} mm"
            measure = "measure" if step.measure_enabled else "motion"
            lines.append(f"{prefix} {index:02d}. {step_id} | {phase} | {target} | {measure}")
        self.orchestration_step_list.setPlainText("\n".join(lines))
        self._apply_orchestration_step_highlight()

    def _active_orchestration_step_index(self) -> int | None:
        if self.automation_current_step_index is None:
            return None
        if self.automation_completed_steps >= self.automation_current_step_index:
            return None
        return self.automation_current_step_index

    def _apply_orchestration_step_highlight(self) -> None:
        if not hasattr(self, "orchestration_step_list"):
            return
        active_step_index = self._active_orchestration_step_index()
        if active_step_index is None:
            self.orchestration_step_list.setExtraSelections([])
            return
        block = self.orchestration_step_list.document().findBlockByNumber(active_step_index - 1)
        if not block.isValid():
            self.orchestration_step_list.setExtraSelections([])
            return
        selection = QTextEdit.ExtraSelection()
        selection.cursor = QTextCursor(block)
        selection.cursor.clearSelection()
        selection.format.setBackground(QColor("#1F3A5F"))
        selection.format.setForeground(QColor("#F0F6FC"))
        selection.format.setProperty(QTextFormat.Property.FullWidthSelection, True)
        self.orchestration_step_list.setExtraSelections([selection])
        QTimer.singleShot(0, lambda step_index=active_step_index: self._scroll_orchestration_to_step(step_index))

    def _scroll_orchestration_to_step(self, step_index: int) -> None:
        if not hasattr(self, "orchestration_step_list"):
            return
        if self._active_orchestration_step_index() != step_index:
            return
        block = self.orchestration_step_list.document().findBlockByNumber(step_index - 1)
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        self.orchestration_step_list.setTextCursor(cursor)
        self.orchestration_step_list.centerCursor()

    def _center_orchestration_step_block(self, block) -> None:
        if not hasattr(self, "orchestration_step_list"):
            return
        scrollbar = self.orchestration_step_list.verticalScrollBar()
        viewport = self.orchestration_step_list.viewport()
        block_cursor = QTextCursor(block)
        block_rect = self.orchestration_step_list.cursorRect(block_cursor)
        block_center = block_rect.top() + (block_rect.height() / 2.0)
        viewport_center = viewport.height() / 2.0
        target_value = int(round(scrollbar.value() + block_center - viewport_center))
        target_value = max(scrollbar.minimum(), min(scrollbar.maximum(), target_value))
        scrollbar.setValue(target_value)

    def _reset_automation_progress(self) -> None:
        total_steps = 0 if self.automation_recipe is None else len(self.automation_recipe.steps)
        self.automation_progress_bar.setValue(0)
        self.automation_progress_bar.setFormat("Progress 0%")
        self.automation_progress_bar.setToolTip("")
        self.automation_phase_label.setText("Phase idle")
        self.automation_progress_summary_label.setText(f"Steps 0 / {total_steps}")
        self.automation_eta_label.setText("Remain --")
        self.automation_end_time_label.setText("End --")
        if hasattr(self, "automation_time_strip_label"):
            self.automation_time_strip_label.setText("Elapsed -- | Left -- | ETA --")
            self._set_badge_style(self.automation_time_strip_label, tone="muted")
        self._set_badge_style(self.automation_phase_label, tone="muted")
        self._set_badge_style(self.automation_progress_summary_label, tone="muted")
        self._set_badge_style(self.automation_eta_label, tone="muted")
        self._set_badge_style(self.automation_end_time_label, tone="muted")
        if self.automation_progress_estimator is not None and not self.automation_progress_estimator.estimate.available:
            reason_text = "\n".join(self.automation_progress_estimator.estimate.unavailable_reasons[:4])
            self.automation_eta_label.setToolTip(reason_text)
            self.automation_end_time_label.setToolTip(reason_text)
        else:
            self.automation_eta_label.setToolTip("")
            self.automation_end_time_label.setToolTip("")

    def _refresh_automation_progress(self) -> None:
        total_steps = 0 if self.automation_recipe is None else len(self.automation_recipe.steps)
        if self.automation_progress_estimator is None or self.automation_started_at is None:
            self.automation_progress_summary_label.setText(f"Steps {self.automation_completed_steps} / {total_steps}")
            return

        now = datetime.now()
        phase_elapsed_s = 0.0
        if self.automation_phase_started_at is not None:
            phase_elapsed_s = max(0.0, (now - self.automation_phase_started_at).total_seconds())
        snapshot = self.automation_progress_estimator.snapshot(
            started_at=self.automation_started_at,
            now=now,
            completed_steps=self.automation_completed_steps,
            current_step_index=self.automation_current_step_index,
            current_phase=self.automation_current_phase,
            current_phase_elapsed_s=phase_elapsed_s,
            status=self.automation_status_label.text().lower(),
        )
        self._apply_automation_progress_snapshot(snapshot)

    def _apply_automation_progress_snapshot(self, snapshot) -> None:
        total_steps = max(snapshot.total_steps, 0)
        if snapshot.estimate_available and snapshot.fraction_complete is not None:
            fraction = snapshot.fraction_complete
            tool_tip = ""
        else:
            running_offset = 0.5 if snapshot.current_step_index is not None and snapshot.completed_steps < total_steps else 0.0
            denominator = max(total_steps, 1)
            fraction = min(1.0, max(0.0, (snapshot.completed_steps + running_offset) / denominator))
            tool_tip = "\n".join(snapshot.unavailable_reasons[:4])

        percent = round(fraction * 100)
        self.automation_progress_bar.setValue(int(fraction * 1000))
        self.automation_progress_bar.setFormat(f"Progress {percent}%")
        self.automation_progress_bar.setToolTip(tool_tip)

        phase_text = self._format_phase_label(snapshot.current_phase)
        summary_text = f"Steps {snapshot.completed_steps} / {total_steps}"
        if snapshot.current_step_index is not None and snapshot.current_step_index > 0:
            summary_text = f"{summary_text} | Current {snapshot.current_step_index}"
        self.automation_phase_label.setText(phase_text)
        self.automation_progress_summary_label.setText(summary_text)

        if snapshot.estimate_available and snapshot.estimated_remaining_s is not None:
            self.automation_eta_label.setText(f"Remain {self._format_duration_compact(snapshot.estimated_remaining_s)}")
            end_text = "--"
            if snapshot.estimated_end_time is not None:
                end_text = snapshot.estimated_end_time.strftime("%H:%M:%S")
            self.automation_end_time_label.setText(f"End {end_text}")
            elapsed_s = 0.0
            if self.automation_started_at is not None:
                elapsed_s = max(0.0, (datetime.now() - self.automation_started_at).total_seconds())
            if hasattr(self, "automation_time_strip_label"):
                self.automation_time_strip_label.setText(
                    "Elapsed "
                    f"{self._format_duration_compact(elapsed_s)} | Left "
                    f"{self._format_duration_compact(snapshot.estimated_remaining_s)} | ETA {end_text}"
                )
                self._set_badge_style(self.automation_time_strip_label, tone="info")
            self.automation_eta_label.setToolTip("")
            self.automation_end_time_label.setToolTip("")
        else:
            self.automation_eta_label.setText("Remain est. unavailable")
            self.automation_end_time_label.setText("End est. unavailable")
            if hasattr(self, "automation_time_strip_label"):
                self.automation_time_strip_label.setText("Elapsed -- | Left -- | ETA --")
                self._set_badge_style(self.automation_time_strip_label, tone="muted")
            self.automation_eta_label.setToolTip(tool_tip)
            self.automation_end_time_label.setToolTip(tool_tip)

        phase_tone = "muted" if snapshot.status in {"idle", "ready"} else "info"
        if snapshot.status in {"running", "stopping"}:
            phase_tone = "running" if snapshot.status == "running" else "warning"
        self._set_badge_style(self.automation_phase_label, tone=phase_tone)
        self._set_badge_style(self.automation_progress_summary_label, tone="info" if total_steps else "muted")
        self._set_badge_style(self.automation_eta_label, tone="info" if snapshot.estimate_available else "muted")
        self._set_badge_style(self.automation_end_time_label, tone="info" if snapshot.estimate_available else "muted")
        self._refresh_orchestration_step_list()

    def _format_phase_label(self, phase: str) -> str:
        if not phase:
            return "Phase idle"
        return f"Phase {phase.replace('_', ' ')}"

    def _format_duration_compact(self, seconds: float) -> str:
        total_seconds = max(0, round(seconds))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}h {minutes:02d}m {secs:02d}s"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _load_automation_recipe_dialog(self) -> None:
        if self._is_automation_running():
            self._show_error("Automation Running", "Stop automation before loading another recipe.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Automation Recipe",
            str(resolve_runtime_path("config")),
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            recipe_path = resolve_runtime_path(file_path)
            recipe = load_recipe(recipe_path)
            self.automation_recipe_path = recipe_path
            self.automation_recipe = recipe
            self.recipe_path_edit.setText(recipe_path.name)
            self.recipe_path_edit.setToolTip(str(recipe_path))
            self.automation_status_label.setText("Ready")
            self.automation_step_label.setText(f"{recipe.recipe_id} ({len(recipe.steps)} steps)")
            self._set_badge_style(self.automation_status_label, tone="info")
            self._apply_contact_detection_metadata(recipe)
            self._configure_automation_progress(recipe)
            self._update_runtime_controls()
            self._log(f"Automation recipe loaded: {recipe_path}")
        except Exception as exc:
            self._show_error("Recipe Load Failed", str(exc))

    def _load_automation_session_dialog(self) -> None:
        if self._is_automation_running():
            self._show_error("Automation Running", "Stop automation before opening another session snapshot.")
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Automation Session Manifest",
            str(resolve_runtime_path(self.config.export_directory)),
            "Session Manifest (session_manifest.json);;JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            self._open_automation_session_manifest(resolve_runtime_path(file_path))
        except Exception as exc:
            self._show_error("Session Open Failed", str(exc))

    def _open_recipe_helper_dialog(self) -> None:
        if self._is_automation_running():
            self._show_error("Automation Running", "Stop automation before creating another recipe.")
            return
        dialog = RecipeHelperDialog(self)
        if self.contact_point_position_mm is not None:
            dialog.contact_relative_checkbox.setChecked(True)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            helper_result = dialog.build_result()
            default_dir = resolve_runtime_path(Path("dev_local") / "config")
            default_dir.mkdir(parents=True, exist_ok=True)
            default_path = default_dir / helper_result.suggested_file_name
            file_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Automation Recipe",
                str(default_path),
                "JSON Files (*.json);;All Files (*)",
            )
            if not file_path:
                return
            recipe_path = resolve_runtime_path(file_path)
            save_recipe(recipe_path, helper_result.recipe)
            self.automation_recipe_path = recipe_path
            self.automation_recipe = helper_result.recipe
            self.recipe_path_edit.setText(recipe_path.name)
            self.recipe_path_edit.setToolTip(str(recipe_path))
            self.automation_status_label.setText("Ready")
            self.automation_step_label.setText(
                f"{helper_result.recipe.recipe_id} ({len(helper_result.recipe.steps)} steps)"
            )
            self._set_badge_style(self.automation_status_label, tone="info")
            self._apply_contact_detection_metadata(helper_result.recipe)
            self._configure_automation_progress(helper_result.recipe)
            self._update_runtime_controls()
            self._log(f"Recipe created: {recipe_path}")
        except Exception as exc:
            self._show_error("Recipe Helper Failed", str(exc))

    def _apply_stage_panel_motion_config(self, motion_config, motion_path: str) -> None:
        path = Path(motion_path)
        self.motion_config_path = path
        self.motion_config = motion_config
        self._refresh_motion_config_control_summary()
        if not (hasattr(self, "stage_panel") and self.stage_panel.controller is not None):
            self._set_stage_status("Config Loaded", "muted")
        self._apply_motion_config_to_soft_limits(motion_config)
        self._set_safety_motion_summary(motion_config, path)
        self._refresh_stage_dashboard_defaults()
        self._update_runtime_controls()
        self._log(f"Stage motion config selected: {path}")

    def _refresh_motion_config_control_summary(self) -> None:
        if self.motion_config is None:
            return
        if hasattr(self, "motion_status_label"):
            self.motion_status_label.setText(
                f"{self.motion_config.controller_model} {self.motion_config.port} axis {self.motion_config.axis}"
            )
            self._set_badge_style(self.motion_status_label, tone="info")

    def _apply_motion_config_to_soft_limits(self, motion_config) -> None:
        if not hasattr(self, "stage_soft_min_spin"):
            return
        minimum_mm, maximum_mm = self._expanded_stage_limit_range(motion_config)
        self.stage_soft_min_spin.setRange(minimum_mm, maximum_mm)
        self.stage_soft_max_spin.setRange(minimum_mm, maximum_mm)
        self.stage_soft_min_spin.setValue(motion_config.min_position_mm)
        self.stage_soft_max_spin.setValue(motion_config.max_position_mm)
        self.stage_soft_limit_check.setChecked(bool(motion_config.enforce_software_limits))
        self._refresh_origin_confirmation_controls()
        self._sync_manual_stage_runtime_limits()

    def _expanded_stage_limit_range(self, motion_config) -> tuple[float, float]:
        stroke_mm = max(1.0, abs(motion_config.max_position_mm - motion_config.min_position_mm))
        return min(motion_config.min_position_mm, -stroke_mm), max(motion_config.max_position_mm, stroke_mm)

    def _runtime_motion_config(self):
        if self.motion_config is None:
            return None
        if not hasattr(self, "stage_soft_limit_check") or not self.stage_soft_limit_check.isChecked():
            return replace(self.motion_config, enforce_software_limits=False)
        if self._stage_soft_limit_error() is not None:
            return self.motion_config
        return replace(
            self.motion_config,
            enforce_software_limits=True,
            min_position_mm=self.stage_soft_min_spin.value(),
            max_position_mm=self.stage_soft_max_spin.value(),
        )

    def _sync_manual_stage_runtime_limits(self) -> None:
        if not hasattr(self, "stage_panel"):
            return
        runtime_config = self._runtime_motion_config()
        if runtime_config is None:
            return
        if runtime_config.enforce_software_limits:
            self.stage_panel.apply_runtime_limits(
                enforce_software_limits=True,
                min_position_mm=runtime_config.min_position_mm,
                max_position_mm=runtime_config.max_position_mm,
            )
            return
        self.stage_panel.apply_runtime_limits(enforce_software_limits=False)

    def _motion_origin_confirmation_required(self) -> bool:
        return self.motion_config is not None and not is_simulated_motion_config(self.motion_config)

    def _origin_confirmed_for_run(self) -> bool:
        if not self._motion_origin_confirmation_required():
            return True
        return hasattr(self, "safety_panel") and self.safety_panel.origin_confirmed()

    def _handle_origin_confirmed_changed(self, checked: bool) -> None:
        if hasattr(self, "safety_panel") and self.safety_panel.origin_confirmed_check.isChecked() != checked:
            blocked = self.safety_panel.origin_confirmed_check.blockSignals(True)
            self.safety_panel.origin_confirmed_check.setChecked(checked)
            self.safety_panel.origin_confirmed_check.blockSignals(blocked)
        if hasattr(self, "stage_origin_confirm_check") and self.stage_origin_confirm_check.isChecked() != checked:
            blocked = self.stage_origin_confirm_check.blockSignals(True)
            self.stage_origin_confirm_check.setChecked(checked)
            self.stage_origin_confirm_check.blockSignals(blocked)
        self._refresh_origin_confirmation_controls()
        self._update_runtime_controls()

    def _refresh_origin_confirmation_controls(self) -> None:
        required = self._motion_origin_confirmation_required()
        confirmed = self._origin_confirmed_for_run()
        if hasattr(self, "stage_origin_confirm_check"):
            blocked = self.stage_origin_confirm_check.blockSignals(True)
            self.stage_origin_confirm_check.setText(
                "Origin Confirmed" if required else "Origin Confirmed (Sim)"
            )
            self.stage_origin_confirm_check.setChecked(confirmed)
            self.stage_origin_confirm_check.setEnabled(required)
            self.stage_origin_confirm_check.setToolTip(
                "Confirm the current hardware stage origin/reference before automation."
                if required
                else "Origin confirmation is not required for simulated or disabled motion."
            )
            self.stage_origin_confirm_check.blockSignals(blocked)
        if not hasattr(self, "safety_panel"):
            return
        if not required:
            self.safety_panel.interlock_label.setText("Interlock: origin not required")
            self._set_badge_style(self.safety_panel.interlock_label, tone="muted")
        elif confirmed:
            self.safety_panel.interlock_label.setText("Interlock: origin confirmed")
            self._set_badge_style(self.safety_panel.interlock_label, tone="info")
        else:
            self.safety_panel.interlock_label.setText("Interlock: origin required")
            self._set_badge_style(self.safety_panel.interlock_label, tone="warning")

    def _stage_target_allowed(self, axis: int, target_mm: float) -> tuple[bool, str]:
        limit_error = self._stage_soft_limit_error()
        if limit_error is not None:
            return False, limit_error
        if not hasattr(self, "stage_soft_limit_check") or not self.stage_soft_limit_check.isChecked():
            return True, ""
        min_position = self.stage_soft_min_spin.value()
        max_position = self.stage_soft_max_spin.value()
        if target_mm < min_position or target_mm > max_position:
            return (
                False,
                f"Stage {axis} target {target_mm:.6g} mm is outside soft limit "
                f"{min_position:.6g} to {max_position:.6g} mm.",
            )
        return True, ""

    def _stage_soft_limit_error(self) -> str | None:
        if not hasattr(self, "stage_soft_limit_check") or not self.stage_soft_limit_check.isChecked():
            return None
        min_position = self.stage_soft_min_spin.value()
        max_position = self.stage_soft_max_spin.value()
        if min_position >= max_position:
            return "Stage soft limit min must be lower than max."
        return None

    def _handle_manual_stage_axis_changed(self, axis: int) -> None:
        if hasattr(self, "stage_axis_state_label"):
            axis_name = "Z" if axis == 1 else "X"
            self._set_stage_dashboard_style(self.stage_axis_state_label, f"Manual {axis_name}", "info")

    def _handle_stage_position_changed(
        self,
        axis: int,
        position_mm: float,
        *,
        elapsed_s: float | None = None,
        force_sample: bool = False,
    ) -> None:
        now = datetime.now()
        previous_position = self.stage_positions_mm.get(axis)
        position_changed = previous_position is None or abs(previous_position - position_mm) > 1e-9
        self.stage_positions_mm[axis] = position_mm
        if axis == 1 and hasattr(self, "stage_z_position_label"):
            self._set_stage_dashboard_style(self.stage_z_position_label, f"Z {position_mm:.3f} mm", "info")
        if axis == 2 and hasattr(self, "stage_x_position_label"):
            self._set_stage_dashboard_style(self.stage_x_position_label, f"X {position_mm:.3f} mm", "info")
        if hasattr(self, "stage_motion_state_label"):
            self._set_stage_dashboard_style(self.stage_motion_state_label, "State Updated", "info")
        self._set_stage_last_update_now()
        if position_changed or force_sample:
            if elapsed_s is None:
                elapsed_s = self.stage_motion_elapsed_s
                if self.stage_motion_started_at is not None:
                    elapsed_s += max(0.0, (now - self.stage_motion_started_at).total_seconds())
                    self.stage_motion_started_at = now
            self.stage_motion_elapsed_s = max(self.stage_motion_elapsed_s, elapsed_s)
            self.stage_position_history.append(
                (elapsed_s, self.stage_positions_mm.get(1), self.stage_positions_mm.get(2))
            )
            self._refresh_stage_plot()
        self._refresh_readiness_status()

    def _refresh_stage_plot(self) -> None:
        if not hasattr(self, "stage_trace_curve"):
            return
        samples = list(self.stage_position_history)
        z_points = [(elapsed, z) for elapsed, z, _ in samples if z is not None]
        x_points = [(elapsed, x) for elapsed, _, x in samples if x is not None]
        if self.stage_plot_active_axis in {None, 1}:
            self.stage_trace_curve.setData([elapsed for elapsed, _ in z_points], [z for _, z in z_points])
        else:
            self.stage_trace_curve.setData([], [])
        if hasattr(self, "stage_x_trace_curve"):
            if self.stage_plot_active_axis in {None, 2}:
                self.stage_x_trace_curve.setData([elapsed for elapsed, _ in x_points], [x for _, x in x_points])
            else:
                self.stage_x_trace_curve.setData([], [])
        trajectory_points = [(x, elapsed, z) for elapsed, z, x in samples if z is not None and x is not None]
        if (
            len(trajectory_points) >= 2
            and self.stage_plot_active_axis is None
            and self._stage_axes_vary_for_trajectory(samples)
            and getattr(self, "stage_trajectory_3d_item", None) is not None
        ):
            positions = np.asarray(trajectory_points, dtype=float)
            centered = positions - positions.mean(axis=0)
            max_span = float(np.ptp(positions, axis=0).max())
            if max_span > 0:
                centered *= 6.0 / max_span
            self.stage_trajectory_3d_item.setData(pos=centered)
            self.stage_plot_stack.setCurrentWidget(self.stage_trajectory_widget)
            self.stage_plot_mode_label.setText("3D X-Z trajectory")
            return
        if hasattr(self, "stage_plot_stack"):
            self.stage_plot_stack.setCurrentWidget(self.stage_plot_widget)
        self.stage_plot_widget.setLabel("bottom", "Move time", units="s")
        self.stage_plot_widget.setLabel("left", "Position", units="mm")
        self.stage_plot_mode_label.setText("Position vs move time")

    def _stage_axes_vary_for_trajectory(self, samples: list[tuple[float, float | None, float | None]]) -> bool:
        z_values = [z for _, z, _ in samples if z is not None]
        x_values = [x for _, _, x in samples if x is not None]
        return self._stage_axis_varies(z_values) and self._stage_axis_varies(x_values)

    def _stage_axis_varies(self, values: list[float]) -> bool:
        if len(values) < 2:
            return False
        first = values[0]
        return any(abs(value - first) > 1e-9 for value in values[1:])

    def _current_stage_plot_point(self) -> tuple[float, float] | None:
        z_position = self.stage_positions_mm.get(1)
        x_position = self.stage_positions_mm.get(2)
        if z_position is not None and x_position is not None:
            return self.stage_motion_elapsed_s, z_position
        if z_position is not None:
            return self.stage_motion_elapsed_s, z_position
        if x_position is not None:
            return self.stage_motion_elapsed_s, x_position
        return None

    def _add_stage_marker(self, label: str) -> None:
        point = self._current_stage_plot_point()
        if point is None:
            self._show_error("Stage Marker", "No stage position has been read yet.")
            return
        x_value, y_value = point
        color = "#F2CC60" if label == "start" else "#F778BA"
        marker = pg.ScatterPlotItem(
            [x_value],
            [y_value],
            symbol="x",
            size=14,
            pen=pg.mkPen(color, width=2),
        )
        self.stage_plot_widget.addItem(marker)
        self.stage_mark_items.append(marker)
        self.stage_markers.append(
            {
                "name": f"Stage Mark {len(self.stage_mark_items)}",
                "kind": label,
                "move_time_s": x_value,
                "value_mm": y_value,
                "color": color,
            }
        )
        if hasattr(self, "stage_mark_state_label"):
            self.stage_mark_state_label.setText(f"Marks {len(self.stage_mark_items)}")
            self._set_badge_style(self.stage_mark_state_label, tone="muted")
        self._log(f"Stage mark {label}: x={x_value:.6g}, y={y_value:.6g}")

    def _clear_stage_markers(self) -> None:
        for item in self.stage_mark_items:
            try:
                self.stage_plot_widget.removeItem(item)
            except Exception:
                pass
        self.stage_mark_items.clear()
        self.stage_markers.clear()
        if hasattr(self, "stage_mark_state_label"):
            self.stage_mark_state_label.setText("Marks 0")
            self._set_badge_style(self.stage_mark_state_label, tone="muted")

    def _clear_stage_plot_view(self, *, log: bool = True) -> None:
        self.stage_position_history.clear()
        self.stage_motion_elapsed_s = 0.0
        self.stage_plot_active_axis = None
        if self.stage_motion_started_at is not None:
            self.stage_motion_started_at = datetime.now()
        self._clear_stage_markers()
        self.stage_trace_curve.setData([], [])
        if hasattr(self, "stage_x_trace_curve"):
            self.stage_x_trace_curve.setData([], [])
        if getattr(self, "stage_trajectory_3d_item", None) is not None:
            self.stage_trajectory_3d_item.setData(pos=np.empty((0, 3)))
        if hasattr(self, "stage_plot_stack"):
            self.stage_plot_stack.setCurrentWidget(self.stage_plot_widget)
        self.stage_plot_mode_label.setText("Position vs move time")
        if log:
            self._log("Stage plot cleared")

    def _rebuild_stage_markers_from_payload(self, markers: list[dict[str, Any]]) -> None:
        self._clear_stage_markers()
        for marker in markers:
            move_time_s = float(marker.get("move_time_s", 0.0))
            value_mm = float(marker.get("value_mm", 0.0))
            color = str(marker.get("color", "#F778BA"))
            item = pg.ScatterPlotItem(
                [move_time_s],
                [value_mm],
                symbol="x",
                size=14,
                pen=pg.mkPen(color, width=2),
            )
            self.stage_plot_widget.addItem(item)
            self.stage_mark_items.append(item)
            self.stage_markers.append(
                {
                    "name": str(marker.get("name", f"Stage Mark {len(self.stage_mark_items)}")),
                    "kind": str(marker.get("kind", "stage")),
                    "move_time_s": move_time_s,
                    "value_mm": value_mm,
                    "color": color,
                }
            )
        if hasattr(self, "stage_mark_state_label"):
            self.stage_mark_state_label.setText(f"Marks {len(self.stage_mark_items)}")
            self._set_badge_style(self.stage_mark_state_label, tone="muted")

    def _set_safety_motion_summary(self, motion_config, motion_path: Path) -> None:
        if not hasattr(self, "safety_panel"):
            return
        self.safety_panel.set_motion_config_summary(
            path=str(motion_path),
            port=motion_config.port,
            axis=motion_config.axis,
            min_position_mm=motion_config.min_position_mm,
            max_position_mm=motion_config.max_position_mm,
        )
        self.safety_panel.clear_recovery()
        self._refresh_origin_confirmation_controls()

    def _use_protocol_recipe(self, recipe) -> None:
        self.automation_recipe_path = None
        self.automation_recipe = recipe
        self.recipe_path_edit.setText(f"generated:{recipe.recipe_id}")
        self.recipe_path_edit.setToolTip("Generated in Protocol panel")
        self.automation_status_label.setText("Ready")
        self.automation_step_label.setText(f"{recipe.recipe_id} ({len(recipe.steps)} steps)")
        self._set_badge_style(self.automation_status_label, tone="info")
        self._apply_contact_detection_metadata(recipe)
        self._configure_automation_progress(recipe)
        self._update_runtime_controls()
        self._log(f"Protocol recipe generated: {recipe.recipe_id} ({len(recipe.steps)} steps)")

    def _open_automation_session_manifest(self, manifest_path: Path) -> None:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self._apply_automation_session_snapshot(payload, manifest_path)

    def _apply_automation_session_snapshot(self, payload: dict[str, Any], manifest_path: Path) -> None:
        session_id = str(payload.get("session_id", manifest_path.parent.name))
        status = str(payload.get("status", "unknown")).strip().lower() or "unknown"
        recipe_payload = payload.get("recipe")
        if not isinstance(recipe_payload, dict):
            raise ValueError("Session manifest missing recipe payload.")
        recipe = recipe_from_dict(
            {
                "recipe_id": recipe_payload.get("recipe_id", "session_recipe"),
                "steps": recipe_payload.get("steps", []),
                "metadata": recipe_payload.get("metadata", {}),
            }
        )
        self.automation_recipe_path = None
        self.automation_recipe = recipe
        self.recipe_path_edit.setText(f"session:{session_id}")
        self.recipe_path_edit.setToolTip(str(manifest_path))
        session_label = payload.get("session_label")
        self.session_label_edit.setText("" if session_label is None else str(session_label))
        self._apply_contact_detection_metadata(recipe)
        self._configure_automation_progress(recipe)

        step_results = payload.get("step_results", [])
        if not isinstance(step_results, list):
            raise ValueError("Session manifest step_results must be a list.")
        self._clear_result_table()
        for step_result in step_results:
            if isinstance(step_result, dict):
                self._append_result_row(step_result)

        completed_steps = int(payload.get("completed_step_count", len(step_results)))
        self.automation_completed_steps = max(0, completed_steps)
        self.automation_current_step_index = None
        self.automation_current_phase = status
        self.automation_started_at = None
        self.automation_phase_started_at = None
        self._set_automation_status_badge(status)
        total_steps = len(recipe.steps)
        fraction = 0.0 if total_steps <= 0 else min(1.0, self.automation_completed_steps / max(total_steps, 1))
        self.automation_progress_bar.setValue(int(fraction * 1000))
        self.automation_progress_bar.setFormat(f"{round(fraction * 100)}%")
        self.automation_phase_label.setText(self._format_phase_label(status))
        self.automation_progress_summary_label.setText(f"Steps {self.automation_completed_steps} / {total_steps}")
        self.automation_eta_label.setText("Remain snapshot")
        self.automation_end_time_label.setText("End snapshot")
        self._set_badge_style(self.automation_phase_label, tone="info" if total_steps else "muted")
        self._set_badge_style(self.automation_progress_summary_label, tone="info" if total_steps else "muted")
        self._set_badge_style(self.automation_eta_label, tone="muted")
        self._set_badge_style(self.automation_end_time_label, tone="muted")
        self.automation_step_label.setText(
            f"{session_id} | {self.automation_completed_steps}/{total_steps} steps | {status}"
        )
        self._restore_contact_detection_from_session(payload)
        self._update_runtime_controls()
        self._log(f"Automation session reopened: {manifest_path}")

    def _restore_contact_detection_from_session(self, payload: dict[str, Any]) -> None:
        if not hasattr(self, "safety_panel"):
            return
        runtime_metadata = payload.get("runtime_metadata")
        if not isinstance(runtime_metadata, dict):
            return
        contact_payload = runtime_metadata.get("contact_detection")
        if not isinstance(contact_payload, dict):
            return
        if bool(contact_payload.get("detected", False)):
            self.safety_panel.set_contact_detection_result(
                detected=True,
                contact_position_mm=contact_payload.get("contact_position_mm"),
                contact_resistance_ohm=contact_payload.get("contact_resistance_ohm"),
                use_as_zero=bool(contact_payload.get("use_as_zero", False)),
            )
            if bool(contact_payload.get("use_as_zero", False)):
                self.safety_panel.mark_contact_detection_zero_applied(
                    contact_position_mm=contact_payload.get("contact_position_mm")
                )

    def _set_automation_status_badge(self, status: str) -> None:
        normalized = status.strip().lower()
        tone = "muted"
        label = normalized.title() if normalized else "Idle"
        if normalized in {"ready", "completed", "reopened"}:
            tone = "info"
        elif normalized in {"running"}:
            tone = "running"
        elif normalized in {"stopping", "cancelled"}:
            tone = "warning"
        elif normalized in {"failed", "error"}:
            tone = "error"
        self.automation_status_label.setText(label)
        self._set_badge_style(self.automation_status_label, tone=tone)

    def _handle_emergency_stop_requested(self) -> None:
        if self._is_automation_running():
            self._request_stop_automation()
        if hasattr(self, "stage_panel"):
            self.stage_panel.emergency_stop()

    def _handle_stage_recovery_required(self, message: str) -> None:
        if hasattr(self, "safety_panel"):
            self.safety_panel.set_recovery_required(message)
        if hasattr(self, "motion_status_label"):
            self.motion_status_label.setText("Recovery required")
            self._set_badge_style(self.motion_status_label, tone="warning")
        self._set_stage_status("Recovery Required", "warning")
        self._log(message)

    def _start_automation(self) -> None:
        if self._is_automation_running():
            return
        if self.controller and self.controller.is_running:
            if self.csv_recorder.is_active:
                self._show_error("Measurement Running", "Stop manual measurement before running automation.")
                return
            self._log("Stopping live monitor before automation")
            self._stop_measurement()
        if self.automation_recipe is None:
            self._show_error("Recipe Missing", "Load an automation recipe before running automation.")
            return
        soft_limit_error = self._stage_soft_limit_error()
        if soft_limit_error is not None:
            self._show_error("Stage Soft Limit", soft_limit_error)
            self._update_runtime_controls()
            return
        operator_confirmed = self._confirm_automation_start()
        if not operator_confirmed:
            return
        if not self._apply_ui_config(reset_history=False):
            return

        self.automation_stop_event = threading.Event()
        self.automation_events = queue.Queue()
        self.automation_live_frames = queue.Queue()
        self.automation_last_result = None
        recipe = self._recipe_for_execution(self.automation_recipe)
        self._configure_automation_progress(recipe)
        self.automation_started_at = datetime.now()
        self._reset_history()
        self._clear_stage_plot_view(log=False)
        self.stage_plot_active_axis = self.motion_config.axis if self.motion_config is not None else None
        if hasattr(self, "stage_panel"):
            self.stage_panel.set_live_status_polling(False)
        options = AutomationSessionOptions(
            export_directory=self.config.export_directory,
            session_label=self.session_label_edit.text(),
            metadata={
                "backend": self.config.backend,
                "chassis_name": self.config.chassis_name,
                "recipe_path": str(self.automation_recipe_path) if self.automation_recipe_path is not None else "",
                "motion_config_path": str(self.motion_config_path) if self.motion_config_path is not None else "",
            },
        )
        try:
            backend = self._make_backend(self.config)
            measurement_service = MeasurementService(backend, self.config.sampling.acquisition_hz)
            command_bridge = self._make_automation_command_bridge()
            safety_policy = self._make_automation_safety_policy(operator_confirmed=operator_confirmed)
            runner = ExperimentRunner(
                measurement_service,
                command_bridge=command_bridge,
                event_callback=self._queue_automation_event,
                measurement_frame_callback=self._queue_automation_live_frame,
                stop_event=self.automation_stop_event,
                safety_policy=safety_policy,
            )
        except Exception as exc:
            if hasattr(self, "stage_panel"):
                self.stage_panel.set_live_status_polling(True)
            self._show_error("Automation Start Failed", str(exc))
            self._update_runtime_controls()
            return

        def run_automation() -> None:
            try:
                result = runner.run(recipe, options)
            except AutomationCancelledError as exc:
                self.automation_events.put(("cancelled", str(exc)))
            except Exception as exc:
                self.automation_events.put(("failed", str(exc)))
            else:
                self.automation_events.put(("completed", result))

        self.automation_thread = threading.Thread(target=run_automation, daemon=True)
        self.automation_status_label.setText("Running")
        self.automation_step_label.setText("Initializing")
        self._set_badge_style(self.automation_status_label, tone="running")
        self._refresh_automation_progress()
        self.automation_thread.start()
        self.automation_timer.start(100)
        self._update_runtime_controls()
        self._log("Automation run started")

    def _make_automation_command_bridge(self):
        if self.motion_config is None:
            self.motion_status_label.setText("Motion bridge: disabled")
            self._set_badge_style(self.motion_status_label, tone="muted")
            self._set_stage_status("Disconnected", "muted")
            return NoOpCommandBridge()
        runtime_motion_config = self._runtime_motion_config() or self.motion_config
        if self._can_reuse_manual_stage_controller():
            controller = self.stage_panel.controller
            self.motion_status_label.setText(
                f"{runtime_motion_config.controller_model} {runtime_motion_config.port} axis {runtime_motion_config.axis} reused"
            )
            self._set_badge_style(self.motion_status_label, tone="info")
            self._set_stage_status("Bridge Reused", "info")
            self._log("Automation using existing manual stage connection")
            controller.config = runtime_motion_config
            return ShotCommandBridge(controller, disconnect_on_close=False)
        controller = create_shot_controller(runtime_motion_config)
        self.motion_status_label.setText(
            f"{runtime_motion_config.controller_model} {runtime_motion_config.port} axis {runtime_motion_config.axis}"
        )
        self._set_badge_style(self.motion_status_label, tone="info")
        self._set_stage_status("Bridge Ready", "info")
        return ShotCommandBridge(controller)

    def _can_reuse_manual_stage_controller(self) -> bool:
        if not hasattr(self, "stage_panel"):
            return False
        controller = self.stage_panel.controller
        if controller is None or self.motion_config is None:
            return False
        controller_config = controller.config
        return (
            controller_config.port == self.motion_config.port
            and controller_config.baudrate == self.motion_config.baudrate
            and controller_config.controller_model == self.motion_config.controller_model
            and controller_config.driver_mode == self.motion_config.driver_mode
            and controller_config.simulated == self.motion_config.simulated
        )

    def _confirm_automation_start(self) -> bool:
        if self.motion_config is None:
            return True
        if self._motion_origin_confirmation_required() and not self._origin_confirmed_for_run():
            self._show_error(
                "Origin Confirmation Required",
                "Check Origin Confirmed in the Stage section before running hardware automation.",
            )
            return False
        result = QMessageBox.question(
            self,
            "Confirm Automation",
            "Confirm the stage path is clear, emergency stop is reachable, and the current origin is valid before running hardware automation.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return result == QMessageBox.StandardButton.Yes

    def _make_automation_safety_policy(self, *, operator_confirmed: bool = False) -> AutomationSafetyPolicy:
        if self.motion_config is None:
            return AutomationSafetyPolicy()
        runtime_motion_config = self._runtime_motion_config() or self.motion_config
        if not runtime_motion_config.enforce_software_limits:
            return AutomationSafetyPolicy(
                min_position_mm=None,
                max_position_mm=None,
                require_target_displacement=True,
                require_operator_confirmation=True,
                operator_confirmed=operator_confirmed,
            )
        return AutomationSafetyPolicy(
            min_position_mm=runtime_motion_config.min_position_mm,
            max_position_mm=runtime_motion_config.max_position_mm,
            require_target_displacement=True,
            require_operator_confirmation=True,
            operator_confirmed=operator_confirmed,
        )

    def _request_stop_automation(self, *_args, wait: bool = False) -> None:
        if not self._is_automation_running():
            return
        if not self.automation_stop_event.is_set():
            self.automation_stop_event.set()
            self.automation_status_label.setText("Stopping")
            self._set_badge_style(self.automation_status_label, tone="warning")
            self._refresh_automation_progress()
            self._log("Automation stop requested")
            self._update_runtime_controls()
        if wait and self.automation_thread is not None:
            self.automation_thread.join(timeout=2.0)

    def _queue_automation_event(self, event_name: str, payload: dict) -> None:
        self.automation_events.put(("event", (event_name, payload)))

    def _queue_automation_live_frame(self, frame: MeasurementFrame) -> None:
        self.automation_live_frames.put(frame)

    def _automation_elapsed_seconds(self) -> float:
        if self.automation_started_at is None:
            return self.stage_motion_elapsed_s
        return max(0.0, (datetime.now() - self.automation_started_at).total_seconds())

    def _drain_automation_live_frames(self) -> None:
        processed = False
        while True:
            try:
                frame = self.automation_live_frames.get_nowait()
            except queue.Empty:
                break
            self._process_frame(frame)
            processed = True
        if not processed:
            return
        self._refresh_input_table()
        self._refresh_output_table()
        self._refresh_monitor_cards()
        self._refresh_plot()
        self._refresh_readiness_status()

    def _poll_automation_events(self) -> None:
        self._drain_automation_live_frames()
        while True:
            try:
                kind, payload = self.automation_events.get_nowait()
            except queue.Empty:
                break
            if kind == "event":
                event_name, event_payload = payload
                self._handle_automation_event(event_name, event_payload)
            elif kind == "completed":
                self.automation_last_result = payload
                self.automation_completed_steps = len(payload.step_results)
                self.automation_current_step_index = len(payload.step_results)
                self.automation_current_phase = "completed"
                self.automation_phase_started_at = None
                self.automation_status_label.setText("Completed")
                self._set_badge_style(self.automation_status_label, tone="info")
                self.automation_step_label.setText(
                    f"{len(payload.step_results)} steps -> {payload.session_dir.name}"
                )
                self._refresh_automation_progress()
                self._log(f"Automation completed: {payload.session_dir}")
            elif kind == "cancelled":
                self.automation_current_phase = "cancelled"
                self.automation_phase_started_at = None
                self.automation_status_label.setText("Cancelled")
                self._set_badge_style(self.automation_status_label, tone="warning")
                self.automation_step_label.setText("Stopped by user")
                self._refresh_automation_progress()
                self._log(str(payload))
            elif kind == "failed":
                self.automation_current_phase = "failed"
                self.automation_phase_started_at = None
                self.automation_status_label.setText("Failed")
                self._set_badge_style(self.automation_status_label, tone="error")
                self.automation_step_label.setText("Execution error")
                self._refresh_automation_progress()
                self._show_error("Automation Failed", str(payload))

        self._refresh_automation_progress()
        self._drain_automation_live_frames()
        if self.automation_thread is not None and not self.automation_thread.is_alive():
            self.automation_timer.stop()
            self.automation_thread = None
            if hasattr(self, "stage_panel"):
                self.stage_panel.set_live_status_polling(True)
            if hasattr(self, "stage_panel") and self.stage_panel.controller is not None:
                self.stage_panel.refresh_status()
            self._update_runtime_controls()

    def _handle_automation_event(self, event_name: str, payload: dict) -> None:
        if event_name == "session_started":
            self.automation_status_label.setText("Running")
            self._set_badge_style(self.automation_status_label, tone="running")
            self.automation_started_at = datetime.now()
            self.automation_completed_steps = 0
            self.automation_current_step_index = None
            self.automation_current_phase = ""
            self.automation_phase_started_at = None
            self.automation_step_label.setText(payload["session_id"])
            self._refresh_automation_progress()
            self._log(f"Automation session created: {payload['session_dir']}")
            return
        if event_name == "motion_connected":
            self.motion_status_label.setText(payload["message"])
            self._set_badge_style(self.motion_status_label, tone="info")
            self._set_stage_status("Connected", "info")
            self._log(payload["message"])
            return
        if event_name == "contact_detection_started":
            self.automation_current_phase = "contact_detect"
            self.automation_phase_started_at = datetime.now()
            self.automation_step_label.setText("Contact detection in progress")
            if hasattr(self, "safety_panel"):
                self.safety_panel.set_contact_detection_running()
            self._refresh_automation_progress()
            self._log(
                "Contact detection started: "
                f"axis={payload['stage_axis']} max_travel={payload['max_travel_mm']} "
                f"threshold={payload['delta_resistance_threshold_ohm']}"
            )
            return
        if event_name == "contact_detection_completed":
            self.automation_current_phase = "contact_detect_done"
            self.automation_phase_started_at = None
            position_text = payload.get("contact_position_mm")
            resistance_text = payload.get("contact_resistance_ohm")
            if position_text is not None:
                axis = int(payload.get("stage_axis", self.motion_config.axis if self.motion_config is not None else 1))
                self._handle_stage_position_changed(
                    axis,
                    float(position_text),
                    elapsed_s=self._automation_elapsed_seconds(),
                    force_sample=True,
                )
            self.automation_step_label.setText(
                f"Contact {position_text} mm / {resistance_text} ohm"
            )
            if hasattr(self, "safety_panel"):
                self.safety_panel.set_contact_detection_result(
                    detected=bool(payload.get("detected", False)),
                    contact_position_mm=payload.get("contact_position_mm"),
                    contact_resistance_ohm=payload.get("contact_resistance_ohm"),
                    use_as_zero=bool(payload.get("use_as_zero", False)),
                )
            self._refresh_automation_progress()
            self._log(
                "Contact detection completed: "
                f"position={payload.get('contact_position_mm')} "
                f"delta={payload.get('delta_resistance_ohm')}"
            )
            return
        if event_name == "contact_detection_zero_applied":
            if hasattr(self, "safety_panel"):
                self.safety_panel.mark_contact_detection_zero_applied(
                    contact_position_mm=payload.get("contact_position_mm")
                )
            self._log(f"Contact detection logical zero applied at {payload.get('contact_position_mm')} mm")
            return
        if event_name == "step_started":
            self.automation_status_label.setText("Running")
            self._set_badge_style(self.automation_status_label, tone="running")
            self.automation_current_step_index = payload["step_index"]
            phase = payload.get("phase") or "step"
            cycle = payload.get("cycle_index")
            cycle_prefix = "" if cycle is None else f"Cycle {cycle} "
            self.automation_step_label.setText(
                f"{cycle_prefix}Step {payload['step_index']}: {payload['step_id']}"
            )
            self._refresh_automation_progress()
            position_before = payload.get("position_before_mm")
            if position_before is not None:
                axis = self.motion_config.axis if self.motion_config is not None else 1
                self._handle_stage_position_changed(
                    axis,
                    float(position_before),
                    elapsed_s=self._automation_elapsed_seconds(),
                    force_sample=True,
                )
            self._log(
                f"Automation step started: {payload['step_id']} phase={phase} "
                f"target={payload['target_displacement']} speed={payload.get('velocity_mm_min')}"
            )
            return
        if event_name == "phase_started":
            self.automation_current_step_index = payload["step_index"]
            self.automation_current_phase = payload.get("phase") or ""
            self.automation_phase_started_at = datetime.now()
            self._refresh_automation_progress()
            self._log(f"Automation phase started: step={payload['step_id']} phase={self.automation_current_phase}")
            return
        if event_name == "motion_position":
            self._handle_stage_position_changed(
                int(payload["axis"]),
                float(payload["position_mm"]),
                elapsed_s=self._automation_elapsed_seconds(),
                force_sample=True,
            )
            return
        if event_name == "phase_completed":
            self.automation_current_phase = payload.get("phase") or self.automation_current_phase
            self.automation_phase_started_at = None
            self._refresh_automation_progress()
            return
        if event_name == "step_completed":
            self.automation_completed_steps = payload["step_index"]
            self.automation_current_step_index = payload["step_index"]
            self.automation_current_phase = "step_completed"
            self.automation_phase_started_at = None
            position_mm = (
                payload.get("position_after_disengage_mm")
                if payload.get("position_after_disengage_mm") is not None
                else payload.get("position_after_engage_mm")
            )
            if position_mm is not None:
                axis = self.motion_config.axis if self.motion_config is not None else 1
                self._handle_stage_position_changed(
                    axis,
                    float(position_mm),
                    elapsed_s=self._automation_elapsed_seconds(),
                    force_sample=True,
                )
            self._refresh_automation_progress()
            self._append_result_row(payload)
            self._log(
                f"Automation step completed: {payload['step_id']} -> {payload['measurement_file']} "
                f"({payload['frame_count']} frames)"
            )
            return
        if event_name == "session_completed":
            self._log(
                f"Automation session completed: {payload['session_id']} ({payload['step_count']} steps)"
            )
            return
        if event_name == "session_cancelled":
            self._log(f"Automation session cancelled: {payload['session_id']}")
            return
        if event_name == "session_failed":
            self._log(f"Automation session failed: {payload['session_id']}")
            return
        if event_name == "motion_abort_requested":
            self._log(f"Motion abort requested after automation {payload['reason']}")
            return
        if event_name == "motion_abort_failed":
            self._log(f"Motion abort failed after automation {payload['reason']}: {payload['error']}")
            return
        if event_name == "recovery_required":
            self._handle_stage_recovery_required(payload["message"])
            return

    def _clear_result_table(self) -> None:
        if hasattr(self, "result_table"):
            self.result_table.setRowCount(0)

    def _append_result_row(self, payload: dict) -> None:
        if not hasattr(self, "result_table"):
            return
        self.result_table.insertRow(0)
        measurement_file = payload.get("measurement_file") or ""
        file_name = Path(str(measurement_file)).name if measurement_file else ""
        values = [
            f"{payload.get('step_index', '')}: {payload.get('step_id', '')}",
            "" if payload.get("cycle_index") is None else str(payload.get("cycle_index")),
            str(payload.get("phase") or ""),
            "" if payload.get("target_displacement") is None else f"{payload.get('target_displacement')} mm",
            str(payload.get("frame_count", "")),
            file_name,
        ]
        for column, value in enumerate(values):
            self.result_table.setItem(0, column, self._readonly_item(value))
        if self.result_table.rowCount() > 200:
            self.result_table.removeRow(self.result_table.rowCount() - 1)

    def _readonly_item(self, text: str) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)
        return item

    def _centered_widget(self, child: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(child)
        layout.addStretch(1)
        return wrapper

    def _new_double_spin(
        self,
        minimum: float,
        maximum: float,
        decimals: int,
        value: float,
        step: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSingleStep(step)
        return spin

    def _format_float_compact(self, value: float) -> str:
        if float(value).is_integer():
            return str(int(value))
        return f"{value:g}"

    def _sync_plot_views(self) -> None:
        plot_viewbox = self.plot_widget.getPlotItem().vb
        self.ao_viewbox.setGeometry(plot_viewbox.sceneBoundingRect())
        self.ao_viewbox.linkedViewChanged(plot_viewbox, self.ao_viewbox.XAxis)

    def _add_ao_viewbox_to_plot_scene(self) -> None:
        scene = self.plot_widget.scene()
        if self.ao_viewbox.scene() is not scene:
            scene.addItem(self.ao_viewbox)

    def _apply_plot_section_geometry(self) -> None:
        plot_widgets = [
            widget
            for widget_name in ("plot_widget", "stage_plot_stack")
            if (widget := getattr(self, widget_name, None)) is not None
        ]
        if not plot_widgets:
            return
        available_widths: list[int] = []
        for widget in plot_widgets:
            parent = widget.parentWidget()
            if parent is None:
                continue
            layout = parent.layout()
            if layout is None:
                available_widths.append(parent.width())
                continue
            margins = layout.contentsMargins()
            available_widths.append(parent.width() - margins.left() - margins.right())
        positive_widths = [width for width in available_widths if width > 0]
        if positive_widths:
            common_width = min(positive_widths)
        elif hasattr(self, "workspace_splitter"):
            splitter_sizes = self.workspace_splitter.sizes()
            if hasattr(self, "measurement_workspace_layout") and splitter_sizes:
                common_width = int(splitter_sizes[0] / 2) - 24
            else:
                common_width = min(splitter_sizes[:2]) - 24 if len(splitter_sizes) >= 2 else 360
        else:
            common_width = 360
        height_cap = int(max(self.height(), 700) * 0.34)
        target_width = max(1, min(common_width, int(height_cap * self.PLOT_ASPECT_WIDTH / self.PLOT_ASPECT_HEIGHT)))
        target_height = int(round(target_width * self.PLOT_ASPECT_HEIGHT / self.PLOT_ASPECT_WIDTH))
        for widget in plot_widgets:
            widget.setMinimumWidth(target_width)
            widget.setMaximumWidth(target_width)
            widget.setMinimumHeight(target_height)
            widget.setMaximumHeight(target_height)
            widget.resize(target_width, target_height)
        for widget_name in ("stage_plot_widget", "stage_trajectory_widget"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setMinimumWidth(target_width)
                widget.setMaximumWidth(target_width)
                widget.setMinimumHeight(target_height)
                widget.setMaximumHeight(target_height)
                widget.resize(target_width, target_height)
        self._sync_plot_group_heights()
        self._apply_plot_height_from_actual_width()
        QTimer.singleShot(0, self._apply_plot_height_from_actual_width)

    def _sync_plot_group_heights(self) -> None:
        plot_groups = [
            group
            for group_name in ("daq_plot_group", "stage_plot_group")
            if (group := getattr(self, group_name, None)) is not None
        ]
        if len(plot_groups) != 2:
            return
        for group in plot_groups:
            group.setMinimumHeight(0)
            group.setMaximumHeight(16777215)
        target_height = max(group.sizeHint().height() for group in plot_groups)
        for group in plot_groups:
            group.setMinimumHeight(target_height)
            group.setMaximumHeight(target_height)

    def _apply_plot_height_from_actual_width(self) -> None:
        plot_widgets = [
            widget
            for widget_name in ("plot_widget", "stage_plot_stack")
            if (widget := getattr(self, widget_name, None)) is not None
        ]
        rendered_widths = [widget.width() for widget in plot_widgets if widget.width() > 0]
        if not rendered_widths:
            return
        target_width = min(rendered_widths)
        target_height = int(round(target_width * self.PLOT_ASPECT_HEIGHT / self.PLOT_ASPECT_WIDTH))
        for widget in plot_widgets:
            widget.setMinimumWidth(target_width)
            widget.setMaximumWidth(target_width)
            widget.setMinimumHeight(target_height)
            widget.setMaximumHeight(target_height)
            widget.resize(target_width, target_height)
        for widget_name in ("stage_plot_widget", "stage_trajectory_widget"):
            widget = getattr(self, widget_name, None)
            if widget is not None:
                widget.setMinimumWidth(target_width)
                widget.setMaximumWidth(target_width)
                widget.setMinimumHeight(target_height)
                widget.setMaximumHeight(target_height)
                widget.resize(target_width, target_height)
        self._sync_plot_group_heights()

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _default_splitter_sizes(self) -> list[int]:
        # Backward-compatible value for legacy profile/layout checks.
        return [820, 980] if self._supports_analog_output() else [760, 900]

    def _default_workspace_splitter_sizes(self) -> list[int]:
        return [1600, 400]

    def _set_stage_status(self, status: str, tone: str) -> None:
        if not hasattr(self, "stage_state_label"):
            return
        if status == "Busy":
            if self.stage_motion_started_at is None:
                self.stage_motion_started_at = datetime.now()
        else:
            self.stage_motion_started_at = None
        label = status if status.startswith("Stage ") else f"Stage {status}"
        self.stage_state_label.setText(label)
        self._set_badge_style(self.stage_state_label, tone=tone)
        if hasattr(self, "stage_motion_state_label"):
            self._set_stage_dashboard_style(self.stage_motion_state_label, f"State {status}", tone)
        self._refresh_readiness_status()

    def _set_badge_style(self, widget: QLabel, *, tone: str) -> None:
        style = self.TONE_STYLES.get(tone, self.TONE_STYLES["neutral"])
        widget.setStyleSheet(f"padding: 1px 5px; border-radius: 4px; font-weight: 600; {style}")

    def _ensure_startup_maximized(self) -> None:
        self.setWindowState(self.windowState() | Qt.WindowMaximized)
        self.raise_()
        QTimer.singleShot(0, self._apply_startup_splitter_sizes)

    def _apply_startup_splitter_sizes(self) -> None:
        if hasattr(self, "workspace_splitter"):
            self.workspace_splitter.setSizes(self._default_workspace_splitter_sizes())

    def _input_summary_prefix(self) -> str:
        return "Sensors" if self.profile.profile_id == "automation_console" else "AI"

    def _input_live_group_title(self) -> str:
        return "Sensor Live" if self.profile.profile_id == "automation_console" else "AI Live"

    def _input_channel_group_title(self) -> str:
        return "Sensor Channels" if self.profile.profile_id == "automation_console" else "AI Channels"

    def _input_plot_group_title(self) -> str:
        return "Sensor Trend" if self.profile.profile_id == "automation_console" else "Input Trend"

    def _input_view_selector_label(self) -> str:
        return "Sensor View" if self.profile.profile_id == "automation_console" else "AI View"

    def _restore_window_preferences(self) -> None:
        self.settings.beginGroup(self.SETTINGS_GROUP)
        ai_enabled = self.settings.value("ai_enabled")
        ao_enabled = self.settings.value("ao_enabled")
        ai_plot_enabled = self.settings.value("ai_plot_enabled")
        range_text = self.settings.value("range_text")
        ai_plot_mode = self.settings.value("ai_plot_mode")
        ao_overlay = self.settings.value("ao_overlay")
        session_label = self.settings.value("session_label")
        self.settings.endGroup()

        self.showMaximized()
        self.workspace_splitter.setSizes(self._default_workspace_splitter_sizes())

        self._restore_check_states(ai_enabled, self.ai_enabled_checks)
        self._restore_check_states(ao_enabled, self.ao_enabled_checks)
        self._restore_check_states(ai_plot_enabled, self.ai_plot_checks)

        if range_text and str(range_text) in self.RANGE_OPTIONS:
            self.range_combo.setCurrentText(str(range_text))
        if ai_plot_mode and str(ai_plot_mode) in {"Scaled", "Raw Voltage", "Raw V"}:
            restored_plot_mode = "Raw V" if str(ai_plot_mode) == "Raw Voltage" else str(ai_plot_mode)
            self.ai_plot_mode_combo.setCurrentText(restored_plot_mode)
        if ao_overlay is not None:
            self.ao_overlay_checkbox.setChecked(str(ao_overlay).lower() == "true")
        if session_label is not None:
            self.session_label_edit.setText(str(session_label))
        try:
            self.config = self._config_from_ui()
        except Exception:
            pass

    def _restore_check_states(self, raw_value, checkboxes: list[QCheckBox]) -> None:
        if not raw_value:
            return
        states = [str(value).lower() == "true" for value in raw_value]
        for checkbox, state in zip(checkboxes, states):
            checkbox.setChecked(state)

    def _save_window_preferences(self, *_args) -> None:
        self.settings.beginGroup(self.SETTINGS_GROUP)
        self.settings.setValue("ai_enabled", [checkbox.isChecked() for checkbox in self.ai_enabled_checks])
        self.settings.setValue("ao_enabled", [checkbox.isChecked() for checkbox in self.ao_enabled_checks])
        self.settings.setValue("ai_plot_enabled", [checkbox.isChecked() for checkbox in self.ai_plot_checks])
        self.settings.setValue("range_text", self.range_combo.currentText())
        self.settings.setValue("ai_plot_mode", self.ai_plot_mode_combo.currentText())
        self.settings.setValue("ao_overlay", self.ao_overlay_checkbox.isChecked())
        self.settings.setValue("session_label", self.session_label_edit.text())
        self.settings.endGroup()
        self.settings.sync()
