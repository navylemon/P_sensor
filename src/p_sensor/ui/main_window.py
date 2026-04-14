from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QPushButton,
    QSplitter,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from p_sensor import __version__
from p_sensor.acquisition import AcquisitionController, NiDaqBackend, SimulatedBackend
from p_sensor.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_EXPORT_DIRECTORY,
    build_physical_channel,
    load_config,
    normalize_runtime_path_value,
    resolve_runtime_path,
    save_config,
    validate_app_config,
)
from p_sensor.models import (
    AnalogInputChannelConfig,
    AnalogInputReading,
    AnalogOutputChannelConfig,
    AnalogOutputState,
    AppConfig,
    MeasurementFrame,
    SamplingConfig,
)
from p_sensor.profiles import AppProfile
from p_sensor.storage import CsvRecorder


class MainWindow(QMainWindow):
    SETTINGS_GROUP = "main_window"
    RANGE_OPTIONS = {"10 s": 10.0, "60 s": 60.0, "180 s": 180.0, "All": None}

    def __init__(self, config: AppConfig, config_path: Path, profile: AppProfile) -> None:
        super().__init__()
        self.profile = profile
        self.setWindowTitle(profile.window_title)
        self.resize(1560, 960)

        self.config = self._config_for_profile(config)
        self.config_path = config_path
        self.csv_recorder = CsvRecorder()
        self.controller: AcquisitionController | None = None
        self.settings = QSettings()
        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_frames)

        self.latest_inputs: dict[int, AnalogInputReading] = {}
        self.latest_outputs: dict[int, AnalogOutputState] = {}
        self.latest_elapsed_s = 0.0
        self.history: dict[int, deque[tuple[float, float, float]]] = {}
        self.output_history: dict[int, deque[tuple[float, float]]] = {}
        self.input_curves: dict[int, pg.PlotDataItem] = {}
        self.output_curves: dict[int, pg.PlotDataItem] = {}
        self.ai_color_by_row: list[str] = []
        self.ai_card_widgets: dict[int, tuple[QLabel, QLabel, QLabel]] = {}
        self.ao_card_widgets: dict[int, tuple[QLabel, QLabel, QLabel]] = {}
        self.highlight_intervals: list[tuple[float, float]] = []
        self.highlight_regions: list[pg.LinearRegionItem] = []
        self.active_highlight_start_s: float | None = None
        self.active_highlight_region: pg.LinearRegionItem | None = None

        self.ai_enabled_checks: list[QCheckBox] = []
        self.ai_name_items: list[QTableWidgetItem] = []
        self.ai_physical_items: list[QTableWidgetItem] = []
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

        self._build_menu()
        self._build_ui()
        self._load_config_into_widgets(self.config)
        self._restore_window_preferences()
        self._reset_history()
        self._refresh_runtime_summary()
        self._update_runtime_controls()
        self._log("Application initialized")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save_window_preferences()
        self._stop_measurement()
        super().closeEvent(event)

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

    def _supports_analog_output(self) -> bool:
        return self.profile.supports_analog_output

    def _fallback_ao_slot(self, ai_module_slot: int) -> int:
        return 2 if ai_module_slot != 2 else 1

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
        central_layout.setContentsMargins(10, 10, 10, 10)
        central_layout.setSpacing(8)
        central_layout.addWidget(self._build_status_bar())

        self.workspace_splitter = QSplitter(Qt.Horizontal)
        self.workspace_splitter.addWidget(self._build_left_panel())
        self.workspace_splitter.addWidget(self._build_right_panel())
        self.workspace_splitter.setStretchFactor(0, 4)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setSizes([1180, 380])
        self.workspace_splitter.splitterMoved.connect(self._save_window_preferences)
        central_layout.addWidget(self.workspace_splitter, 1)
        self.setCentralWidget(central)

    def _build_status_bar(self) -> QWidget:
        bar = QFrame()
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        self.session_state_label = QLabel("Disconnected")
        self.backend_state_label = QLabel("Backend simulation")
        self.channel_summary_label = QLabel("AI 0 / AO 0" if self._supports_analog_output() else "AI 0")
        self.export_state_label = QLabel(DEFAULT_EXPORT_DIRECTORY)
        version_label = QLabel(f"v{__version__}")
        for widget in (
            self.session_state_label,
            self.backend_state_label,
            self.channel_summary_label,
            self.export_state_label,
            version_label,
        ):
            widget.setStyleSheet(
                "padding: 4px 8px; border: 1px solid #30363D; border-radius: 6px; background: #161B22;"
            )
        layout.addWidget(self.session_state_label)
        layout.addWidget(self.backend_state_label)
        layout.addWidget(self.channel_summary_label)
        layout.addWidget(self.export_state_label, 1)
        layout.addWidget(version_label)
        return bar

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_plot_group(), 4)
        layout.addWidget(self._build_monitor_group(), 2)
        layout.addWidget(self._build_log_group(), 1)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(self._build_session_group())
        layout.addWidget(self._build_ai_group(), 1)
        self.ao_group = self._build_ao_group()
        self.ao_group.setVisible(self._supports_analog_output())
        layout.addWidget(self.ao_group, 1)
        return panel

    def _build_session_group(self) -> QWidget:
        group = QGroupBox("Session")
        layout = QVBoxLayout(group)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(["simulation", "ni"])
        self.backend_combo.currentTextChanged.connect(self._refresh_runtime_summary)
        self.chassis_name_edit = QLineEdit()
        self.chassis_name_edit.textChanged.connect(self._sync_physical_channels)
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
        self.export_path_edit = QLineEdit()
        self.export_path_edit.setReadOnly(True)
        browse_button = QPushButton("Browse")
        browse_button.clicked.connect(self._choose_export_directory)

        labels = [
            ("Backend", self.backend_combo),
            ("Chassis", self.chassis_name_edit),
            ("AI Slot", self.ai_slot_spin),
        ]
        if self._supports_analog_output():
            labels.append(("AO Slot", self.ao_slot_spin))
        labels.extend(
            [
                ("Acquisition Hz", self.acquisition_hz_spin),
                ("Display Hz", self.display_hz_spin),
                ("History Seconds", self.history_seconds_spin),
            ]
        )
        for index, (text, widget) in enumerate(labels):
            row = (index // 2) * 2
            col = (index % 2)
            grid.addWidget(QLabel(text), row, col)
            grid.addWidget(widget, row + 1, col)
        export_row = ((len(labels) - 1) // 2) * 2 + 2
        grid.addWidget(QLabel("Export Directory"), export_row, 0, 1, 2)
        grid.addWidget(self.export_path_edit, export_row + 1, 0)
        grid.addWidget(browse_button, export_row + 1, 1)

        button_row = QHBoxLayout()
        self.connect_button = QPushButton("Connect")
        self.start_button = QPushButton("Start Logging")
        self.stop_button = QPushButton("Stop")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.apply_outputs_button = QPushButton("Apply Outputs")
        self.zero_outputs_button = QPushButton("Zero Outputs")
        self.connect_button.clicked.connect(self._connect_backend)
        self.start_button.clicked.connect(self._start_measurement)
        self.stop_button.clicked.connect(self._stop_measurement)
        self.pause_button.clicked.connect(self._pause_measurement)
        self.resume_button.clicked.connect(self._resume_measurement)
        self.apply_outputs_button.clicked.connect(self._apply_outputs)
        self.zero_outputs_button.clicked.connect(self._zero_outputs)
        for button in (
            self.connect_button,
            self.start_button,
            self.pause_button,
            self.resume_button,
            self.stop_button,
        ):
            button_row.addWidget(button)
        if self._supports_analog_output():
            button_row.addWidget(self.apply_outputs_button)
            button_row.addWidget(self.zero_outputs_button)

        mark_row = QHBoxLayout()
        self.mark_state_label = QLabel("Marks 0")
        self.mark_state_label.setStyleSheet(
            "padding: 4px 8px; border: 1px solid #30363D; border-radius: 6px; background: #161B22;"
        )
        self.mark_start_button = QPushButton("Mark Start")
        self.mark_stop_button = QPushButton("Mark Stop")
        self.mark_start_button.clicked.connect(self._start_highlight_interval)
        self.mark_stop_button.clicked.connect(self._stop_highlight_interval)
        mark_row.addWidget(self.mark_state_label)
        mark_row.addStretch(1)
        mark_row.addWidget(self.mark_start_button)
        mark_row.addWidget(self.mark_stop_button)

        layout.addLayout(grid)
        layout.addLayout(button_row)
        layout.addLayout(mark_row)
        return group

    def _build_monitor_group(self) -> QWidget:
        group = QGroupBox("Live Monitor")
        layout = QHBoxLayout(group)
        layout.setSpacing(8)

        ai_group = QGroupBox("AI Live")
        ai_layout = QGridLayout(ai_group)
        ai_layout.setHorizontalSpacing(8)
        ai_layout.setVerticalSpacing(8)
        self.ai_cards_host = ai_group
        self.ai_cards_layout = ai_layout

        ao_group = QGroupBox("AO Live")
        ao_layout = QGridLayout(ao_group)
        ao_layout.setHorizontalSpacing(8)
        ao_layout.setVerticalSpacing(8)
        self.ao_cards_host = ao_group
        self.ao_cards_layout = ao_layout

        layout.addWidget(ai_group, 1)
        layout.addWidget(ao_group, 1)
        ao_group.setVisible(self._supports_analog_output())
        return group

    def _build_plot_group(self) -> QWidget:
        group = QGroupBox("Input Trend")
        layout = QVBoxLayout(group)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Range"))
        self.range_combo = QComboBox()
        self.range_combo.addItems(list(self.RANGE_OPTIONS.keys()))
        self.range_combo.currentTextChanged.connect(self._refresh_plot)
        top_row.addWidget(self.range_combo)
        top_row.addWidget(QLabel("AI View"))
        self.ai_plot_mode_combo = QComboBox()
        self.ai_plot_mode_combo.addItems(["Scaled", "Raw Voltage"])
        self.ai_plot_mode_combo.currentTextChanged.connect(self._refresh_plot)
        top_row.addWidget(self.ai_plot_mode_combo)
        self.ao_overlay_checkbox = QCheckBox("AO Overlay")
        self.ao_overlay_checkbox.setChecked(True)
        self.ao_overlay_checkbox.toggled.connect(self._refresh_plot)
        top_row.addWidget(self.ao_overlay_checkbox)
        self.ao_overlay_checkbox.setVisible(self._supports_analog_output())
        top_row.addStretch(1)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#0D1117")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.18)
        self.plot_widget.setLabel("left", "Scaled Value")
        self.plot_widget.setLabel("bottom", "Elapsed", units="s")
        self.plot_widget.showAxis("right")
        self.plot_widget.getAxis("right").setTextPen("#F4A261")
        self.plot_widget.getAxis("right").setPen(pg.mkPen("#3B4450"))
        self.ao_viewbox = pg.ViewBox()
        self.plot_widget.scene().addItem(self.ao_viewbox)
        self.plot_widget.getAxis("right").linkToView(self.ao_viewbox)
        self.ao_viewbox.setXLink(self.plot_widget.getPlotItem())
        self.plot_widget.getPlotItem().vb.sigResized.connect(self._sync_plot_views)
        self._sync_plot_views()
        layout.addLayout(top_row)
        layout.addWidget(self.plot_widget, 1)
        return group

    def _build_log_group(self) -> QWidget:
        group = QGroupBox("Log")
        layout = QVBoxLayout(group)
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(self.log_output)
        return group

    def _build_ai_group(self) -> QWidget:
        group = QGroupBox("AI Channels")
        layout = QVBoxLayout(group)
        self.ai_table = QTableWidget()
        self.ai_table.setColumnCount(10)
        self.ai_table.setHorizontalHeaderLabels(
            ["On", "Name", "Physical", "Scale", "Offset", "Unit", "Voltage", "Value", "Status", "Plot"]
        )
        self.ai_table.verticalHeader().setVisible(False)
        self.ai_table.setAlternatingRowColors(True)
        self.ai_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ai_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.ai_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.ai_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)
        layout.addWidget(self.ai_table)
        return group

    def _build_ao_group(self) -> QWidget:
        group = QGroupBox("AO Channels")
        layout = QVBoxLayout(group)
        self.ao_table = QTableWidget()
        self.ao_table.setColumnCount(8)
        self.ao_table.setHorizontalHeaderLabels(
            ["On", "Name", "Physical", "Min mA", "Max mA", "Initial mA", "Setpoint mA", "Live mA"]
        )
        self.ao_table.verticalHeader().setVisible(False)
        self.ao_table.setAlternatingRowColors(True)
        self.ao_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.ao_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.ao_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.ao_table)
        return group

    def _load_config_into_widgets(self, config: AppConfig) -> None:
        config = self._config_for_profile(config)
        self.config = config
        self.backend_combo.setCurrentText(config.backend)
        self.chassis_name_edit.setText(config.chassis_name)
        self.ai_slot_spin.setValue(config.ai_module_slot)
        self.ao_slot_spin.setValue(config.ao_module_slot)
        self.acquisition_hz_spin.setValue(config.sampling.acquisition_hz)
        self.display_hz_spin.setValue(config.sampling.display_update_hz)
        self.history_seconds_spin.setValue(config.sampling.history_seconds)
        self.export_path_edit.setText(config.export_directory)
        self.ai_color_by_row = [channel.color for channel in config.ai_channels]
        self._populate_ai_table(config.ai_channels)
        self._populate_ao_table(config.ao_channels)
        self._sync_physical_channels()
        self._rebuild_monitor_cards()
        self._rebuild_plot_curves()
        self._refresh_input_table()
        self._refresh_output_table()
        self._refresh_monitor_cards()

    def _rebuild_monitor_cards(self) -> None:
        self._clear_layout(self.ai_cards_layout)
        self._clear_layout(self.ao_cards_layout)
        self.ai_card_widgets.clear()
        self.ao_card_widgets.clear()

        for row, name_item in enumerate(self.ai_name_items):
            frame, value_label, detail_label, status_label = self._create_live_card(
                title=name_item.text(),
                accent=self.ai_color_by_row[row] if row < len(self.ai_color_by_row) else "#3A7CA5",
                subtitle=self.ai_physical_items[row].text(),
            )
            self.ai_cards_layout.addWidget(frame, row // 2, row % 2)
            self.ai_card_widgets[row] = (value_label, detail_label, status_label)

        for row, name_item in enumerate(self.ao_name_items):
            frame, value_label, detail_label, status_label = self._create_live_card(
                title=name_item.text(),
                accent="#F4A261",
                subtitle=self.ao_physical_items[row].text(),
            )
            self.ao_cards_layout.addWidget(frame, row // 2, row % 2)
            self.ao_card_widgets[row] = (value_label, detail_label, status_label)

    def _create_live_card(
        self,
        *,
        title: str,
        accent: str,
        subtitle: str,
    ) -> tuple[QFrame, QLabel, QLabel, QLabel]:
        frame = QFrame()
        frame.setStyleSheet(
            "QFrame { background: #161B22; border: 1px solid #30363D; border-radius: 8px; }"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setStyleSheet(f"font-weight: 700; color: {accent};")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setStyleSheet("color: #8B949E;")
        value_label = QLabel("--")
        value_label.setStyleSheet("font-size: 22px; font-weight: 800; color: #F0F6FC;")
        detail_label = QLabel("--")
        detail_label.setStyleSheet("color: #C9D1D9;")
        status_label = QLabel("--")
        status_label.setStyleSheet("color: #8B949E;")

        layout.addWidget(title_label)
        layout.addWidget(subtitle_label)
        layout.addWidget(value_label)
        layout.addWidget(detail_label)
        layout.addWidget(status_label)
        return frame, value_label, detail_label, status_label

    def _populate_ai_table(self, channels: list[AnalogInputChannelConfig]) -> None:
        self.ai_table.setRowCount(len(channels))
        self.ai_enabled_checks.clear()
        self.ai_name_items.clear()
        self.ai_physical_items.clear()
        self.ai_scale_spins.clear()
        self.ai_offset_spins.clear()
        self.ai_unit_items.clear()
        self.ai_voltage_items.clear()
        self.ai_value_items.clear()
        self.ai_status_items.clear()
        self.ai_plot_checks.clear()

        for row, channel in enumerate(channels):
            enabled_check = QCheckBox()
            enabled_check.setChecked(channel.enabled)
            enabled_check.stateChanged.connect(self._refresh_runtime_summary)
            self.ai_table.setCellWidget(row, 0, self._centered_widget(enabled_check))
            self.ai_enabled_checks.append(enabled_check)

            name_item = QTableWidgetItem(channel.name)
            physical_item = self._readonly_item(channel.physical_channel)
            scale_spin = self._new_double_spin(-1_000_000.0, 1_000_000.0, 4, channel.scale, 0.1)
            offset_spin = self._new_double_spin(-1_000_000.0, 1_000_000.0, 4, channel.offset, 0.1)
            unit_item = QTableWidgetItem(channel.engineering_unit)
            voltage_item = self._readonly_item("--")
            value_item = self._readonly_item("--")
            status_item = self._readonly_item("--")

            plot_check = QCheckBox()
            plot_check.setChecked(channel.enabled)
            plot_check.stateChanged.connect(self._refresh_plot)
            self.ai_table.setCellWidget(row, 9, self._centered_widget(plot_check))

            self.ai_table.setItem(row, 1, name_item)
            self.ai_table.setItem(row, 2, physical_item)
            self.ai_table.setCellWidget(row, 3, scale_spin)
            self.ai_table.setCellWidget(row, 4, offset_spin)
            self.ai_table.setItem(row, 5, unit_item)
            self.ai_table.setItem(row, 6, voltage_item)
            self.ai_table.setItem(row, 7, value_item)
            self.ai_table.setItem(row, 8, status_item)

            self.ai_name_items.append(name_item)
            self.ai_physical_items.append(physical_item)
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
            enabled_check = QCheckBox()
            enabled_check.setChecked(channel.enabled)
            enabled_check.stateChanged.connect(self._refresh_runtime_summary)
            self.ao_table.setCellWidget(row, 0, self._centered_widget(enabled_check))
            self.ao_enabled_checks.append(enabled_check)

            name_item = QTableWidgetItem(channel.name)
            physical_item = self._readonly_item(channel.physical_channel)
            min_spin = self._new_double_spin(-100.0, 100.0, 3, channel.min_current_ma, 0.1)
            max_spin = self._new_double_spin(-100.0, 100.0, 3, channel.max_current_ma, 0.1)
            initial_spin = self._new_double_spin(-100.0, 100.0, 3, channel.initial_current_ma, 0.1)
            setpoint_spin = self._new_double_spin(-100.0, 100.0, 3, channel.initial_current_ma, 0.1)
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

    def _sync_physical_channels(self) -> None:
        chassis_name = self.chassis_name_edit.text().strip() or "cDAQ1"
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
        self.plot_widget.scene().addItem(self.ao_viewbox)
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

    def _config_from_ui(self) -> AppConfig:
        ai_channels: list[AnalogInputChannelConfig] = []
        ao_channels: list[AnalogOutputChannelConfig] = []
        for row in range(self.ai_table.rowCount()):
            ai_channels.append(
                AnalogInputChannelConfig(
                    enabled=self.ai_enabled_checks[row].isChecked(),
                    name=self.ai_name_items[row].text().strip(),
                    physical_channel=self.ai_physical_items[row].text().strip(),
                    scale=self.ai_scale_spins[row].value(),
                    offset=self.ai_offset_spins[row].value(),
                    engineering_unit=self.ai_unit_items[row].text().strip() or "V",
                    color=self.ai_color_by_row[row],
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
                chassis_name=self.chassis_name_edit.text().strip(),
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
        if self._supports_analog_output():
            active_ao = len([checkbox for checkbox in self.ao_enabled_checks if checkbox.isChecked()])
            self.channel_summary_label.setText(f"AI {active_ai} / AO {active_ao}")
        else:
            self.channel_summary_label.setText(f"AI {active_ai}")
        self.export_state_label.setText(self.export_path_edit.text() or DEFAULT_EXPORT_DIRECTORY)

    def _update_runtime_controls(self) -> None:
        connected = self.controller is not None
        running = bool(self.controller and self.controller.is_running)
        paused = bool(self.controller and self.controller.is_paused)
        if running and paused:
            state_text = "Paused"
        elif running:
            state_text = "Running"
        elif connected:
            state_text = "Connected"
        else:
            state_text = "Disconnected"
        self.session_state_label.setText(state_text)
        self.connect_button.setEnabled(not running)
        self.start_button.setEnabled(connected and not running)
        self.pause_button.setEnabled(running and not paused)
        self.resume_button.setEnabled(running and paused)
        self.stop_button.setEnabled(connected or running or self.csv_recorder.is_active)
        output_controls_enabled = self._supports_analog_output() and connected
        self.apply_outputs_button.setEnabled(output_controls_enabled)
        self.zero_outputs_button.setEnabled(output_controls_enabled)
        self.mark_start_button.setEnabled(running and not paused and self.active_highlight_start_s is None)
        self.mark_stop_button.setEnabled(running and self.active_highlight_start_s is not None)
        if self.active_highlight_start_s is None:
            self.mark_state_label.setText(f"Marks {len(self.highlight_intervals)}")
        else:
            self.mark_state_label.setText(f"Marking {self.active_highlight_start_s:.3f}s")

    def _make_backend(self, config: AppConfig):
        if config.backend == "simulation":
            return SimulatedBackend(config)
        if config.backend == "ni":
            return NiDaqBackend(config)
        raise RuntimeError(f"Unsupported backend: {config.backend}")

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
        export_dir = resolve_runtime_path(self.config.export_directory)
        export_dir.mkdir(parents=True, exist_ok=True)
        session_dir = export_dir / started_at.strftime("session_%Y%m%d_%H%M%S")
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir, session_dir / "measurement.csv"

    def _start_measurement(self) -> None:
        if not self._apply_ui_config():
            return
        try:
            if self.controller is None:
                self._connect_backend()
            if self.controller is None:
                return
            started_at = datetime.now()
            session_dir, csv_path = self._prepare_measurement_session(started_at)
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
            if self.controller is None:
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
            frames = self.controller.drain_frames()
            for frame in frames:
                self.csv_recorder.append(frame)
                self._process_frame(frame)
        except Exception as exc:
            self._handle_runtime_failure(exc)
            return
        if frames:
            self._refresh_input_table()
            self._refresh_output_table()
            self._refresh_monitor_cards()
            self._refresh_plot()
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
            value_label, detail_label, status_label = widgets
            reading = self.latest_inputs.get(row)
            unit = self.ai_unit_items[row].text().strip() or "V"
            if reading is None:
                value_label.setText("--")
                detail_label.setText(f"Voltage -- | Value -- {unit}")
                status_label.setText("Status --")
                continue
            value_label.setText(f"{reading.scaled_value:.4f} {reading.unit}")
            detail_label.setText(f"Voltage {reading.voltage:.5f} V")
            status_label.setText(f"Status {reading.status}")

        for row, widgets in self.ao_card_widgets.items():
            value_label, detail_label, status_label = widgets
            state = self.latest_outputs.get(row)
            minimum = self.ao_min_spins[row].value()
            maximum = self.ao_max_spins[row].value()
            if state is None:
                value_label.setText("--")
                detail_label.setText(f"Range {minimum:.3f} .. {maximum:.3f} mA")
                status_label.setText("Output idle")
                continue
            value_label.setText(f"{state.current_ma:.3f} mA")
            detail_label.setText(f"Range {minimum:.3f} .. {maximum:.3f} mA")
            status_label.setText("Output applied")

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
        self.plot_widget.getPlotItem().vb.autoRange()
        if show_ao_overlay:
            self.ao_viewbox.autoRange()

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
        self._log(f"Highlight stop @ {end_s:.3f}s")
        self.active_highlight_start_s = None
        self.active_highlight_region = None
        self._update_runtime_controls()
        return True

    def _stop_highlight_interval(self) -> None:
        self._close_active_highlight_interval()

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

    def _show_error(self, title: str, message: str) -> None:
        self._log(f"{title}: {message}")
        QMessageBox.critical(self, title, message)

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

    def _sync_plot_views(self) -> None:
        plot_viewbox = self.plot_widget.getPlotItem().vb
        self.ao_viewbox.setGeometry(plot_viewbox.sceneBoundingRect())
        self.ao_viewbox.linkedViewChanged(plot_viewbox, self.ao_viewbox.XAxis)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()
            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self._clear_layout(child_layout)

    def _restore_window_preferences(self) -> None:
        self.settings.beginGroup(self.SETTINGS_GROUP)
        geometry = self.settings.value("geometry")
        maximized = self.settings.value("maximized")
        splitter_sizes = self.settings.value("workspace_splitter")
        ai_enabled = self.settings.value("ai_enabled")
        ao_enabled = self.settings.value("ao_enabled")
        ai_plot_enabled = self.settings.value("ai_plot_enabled")
        range_text = self.settings.value("range_text")
        ai_plot_mode = self.settings.value("ai_plot_mode")
        ao_overlay = self.settings.value("ao_overlay")
        self.settings.endGroup()

        if geometry is not None:
            self.restoreGeometry(geometry)
        if splitter_sizes:
            restored_sizes = [int(size) for size in splitter_sizes]
            if len(restored_sizes) == self.workspace_splitter.count():
                self.workspace_splitter.setSizes(restored_sizes)
        if maximized is not None and str(maximized).lower() == "true":
            self.showMaximized()

        self._restore_check_states(ai_enabled, self.ai_enabled_checks)
        self._restore_check_states(ao_enabled, self.ao_enabled_checks)
        self._restore_check_states(ai_plot_enabled, self.ai_plot_checks)

        if range_text and str(range_text) in self.RANGE_OPTIONS:
            self.range_combo.setCurrentText(str(range_text))
        if ai_plot_mode and str(ai_plot_mode) in {"Scaled", "Raw Voltage"}:
            self.ai_plot_mode_combo.setCurrentText(str(ai_plot_mode))
        if ao_overlay is not None:
            self.ao_overlay_checkbox.setChecked(str(ao_overlay).lower() == "true")

    def _restore_check_states(self, raw_value, checkboxes: list[QCheckBox]) -> None:
        if not raw_value:
            return
        states = [str(value).lower() == "true" for value in raw_value]
        for checkbox, state in zip(checkboxes, states):
            checkbox.setChecked(state)

    def _save_window_preferences(self, *_args) -> None:
        self.settings.beginGroup(self.SETTINGS_GROUP)
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("maximized", self.isMaximized())
        self.settings.setValue("workspace_splitter", self.workspace_splitter.sizes())
        self.settings.setValue("ai_enabled", [checkbox.isChecked() for checkbox in self.ai_enabled_checks])
        self.settings.setValue("ao_enabled", [checkbox.isChecked() for checkbox in self.ao_enabled_checks])
        self.settings.setValue("ai_plot_enabled", [checkbox.isChecked() for checkbox in self.ai_plot_checks])
        self.settings.setValue("range_text", self.range_combo.currentText())
        self.settings.setValue("ai_plot_mode", self.ai_plot_mode_combo.currentText())
        self.settings.setValue("ao_overlay", self.ao_overlay_checkbox.isChecked())
        self.settings.endGroup()
        self.settings.sync()
