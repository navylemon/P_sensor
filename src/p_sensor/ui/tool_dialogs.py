from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from p_sensor.config import load_config, resolve_runtime_path, save_config, validate_app_config
from p_sensor.models import AnalogInputChannelConfig, AnalogOutputChannelConfig, AppConfig
from p_sensor.ui.protocol_panel import ProtocolPanel


class SetupSummaryDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget | None,
        collect_snapshot: Callable[[], dict[str, Any]],
        validate_current_config: Callable[[], tuple[bool, str]],
        ensure_export_directory: Callable[[], tuple[bool, str]],
        refresh_daq_devices: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._collect_snapshot = collect_snapshot
        self._validate_current_config = validate_current_config
        self._ensure_export_directory = ensure_export_directory
        self._refresh_daq_devices = refresh_daq_devices

        self.setWindowTitle("Setup Summary / Diagnostics")
        self.resize(760, 620)
        self.setMinimumSize(680, 480)

        self.summary_view = QPlainTextEdit()
        self.summary_view.setReadOnly(True)

        self.status_label = QLabel("Ready")
        self.status_label.setWordWrap(True)

        refresh_button = QPushButton("Refresh")
        validate_button = QPushButton("Validate Config")
        export_button = QPushButton("Ensure Export Folder")
        daq_button = QPushButton("Refresh DAQ Devices")
        snapshot_button = QPushButton("Save Snapshot")
        close_button = QPushButton("Close")

        refresh_button.clicked.connect(self.refresh_summary)
        validate_button.clicked.connect(self._run_validate)
        export_button.clicked.connect(self._run_export_check)
        daq_button.clicked.connect(self._run_refresh_daq)
        snapshot_button.clicked.connect(self._save_snapshot)
        close_button.clicked.connect(self.accept)

        button_row = QHBoxLayout()
        button_row.addWidget(refresh_button)
        button_row.addWidget(validate_button)
        button_row.addWidget(export_button)
        button_row.addWidget(daq_button)
        button_row.addWidget(snapshot_button)
        button_row.addStretch(1)
        button_row.addWidget(close_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.summary_view, 1)
        layout.addLayout(button_row)
        self.refresh_summary()

    def refresh_summary(self) -> None:
        snapshot = self._collect_snapshot()
        self.summary_view.setPlainText(json.dumps(snapshot, indent=2, ensure_ascii=False))
        self.status_label.setText("Current setup snapshot refreshed.")

    def _run_validate(self) -> None:
        ok, message = self._validate_current_config()
        self.status_label.setText(message)
        if not ok:
            QMessageBox.warning(self, "Validate Config", message)

    def _run_export_check(self) -> None:
        ok, message = self._ensure_export_directory()
        self.status_label.setText(message)
        if not ok:
            QMessageBox.warning(self, "Ensure Export Folder", message)

    def _run_refresh_daq(self) -> None:
        self._refresh_daq_devices()
        self.refresh_summary()
        self.status_label.setText("DAQ device list refreshed.")

    def _save_snapshot(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Setup Snapshot",
            str(resolve_runtime_path(Path("dev_local") / "tmp" / "setup_snapshot.json")),
            "JSON Files (*.json)",
        )
        if not target:
            return
        snapshot = self._collect_snapshot()
        path = resolve_runtime_path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        self.status_label.setText(f"Snapshot saved: {path}")


class RecipeWizardDialog(QDialog):
    def __init__(
        self,
        *,
        parent: QWidget | None,
        apply_recipe: Callable[[Any], None],
    ) -> None:
        super().__init__(parent)
        self._apply_recipe = apply_recipe
        self.setWindowTitle("Recipe Wizard")
        self.resize(760, 640)
        self.setMinimumSize(680, 520)

        self.protocol_panel = ProtocolPanel(self)
        self.status_label = QLabel("Adjust protocol parameters, then apply the generated recipe.")
        self.status_label.setWordWrap(True)

        apply_button = QPushButton("Apply Recipe")
        close_button = QPushButton("Close")
        apply_button.clicked.connect(self._apply_current_recipe)
        close_button.clicked.connect(self.reject)
        self.protocol_panel.error_reported.connect(self._show_protocol_error)

        buttons = QDialogButtonBox(self)
        buttons.addButton(apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(self.protocol_panel, 1)
        layout.addWidget(buttons)

    def _apply_current_recipe(self) -> None:
        try:
            recipe = self.protocol_panel.build_recipe()
        except Exception as exc:
            self._show_protocol_error("Recipe Wizard", str(exc))
            return
        self._apply_recipe(recipe)
        self.status_label.setText(f"Applied {recipe.recipe_id} with {len(recipe.steps)} steps.")
        self.accept()

    def _show_protocol_error(self, title: str, message: str) -> None:
        QMessageBox.warning(self, title, message)


class ChannelConfigManagerDialog(QDialog):
    AI_HEADERS = ("Enabled", "Name", "Physical", "Mode", "Scale", "Offset", "Unit", "Color")
    AO_HEADERS = ("Enabled", "Name", "Physical", "Min mA", "Max mA", "Initial mA")

    def __init__(
        self,
        *,
        parent: QWidget | None,
        initial_config: AppConfig,
        apply_config: Callable[[AppConfig], None],
    ) -> None:
        super().__init__(parent)
        self._apply_config = apply_config
        self._working_config = validate_app_config(replace(initial_config))

        self.setWindowTitle("Channel Config Manager")
        self.resize(980, 700)
        self.setMinimumSize(860, 560)

        self.ai_table = QTableWidget(0, len(self.AI_HEADERS))
        self.ai_table.setHorizontalHeaderLabels(self.AI_HEADERS)
        self.ao_table = QTableWidget(0, len(self.AO_HEADERS))
        self.ao_table.setHorizontalHeaderLabels(self.AO_HEADERS)

        self.status_label = QLabel("Load, edit, and apply AI/AO channel settings.")
        self.status_label.setWordWrap(True)

        self.ai_count_spin = QSpinBox()
        self.ai_count_spin.setRange(1, 64)
        self.ai_count_spin.valueChanged.connect(lambda value: self._resize_ai_table(value))
        self.ao_count_spin = QSpinBox()
        self.ao_count_spin.setRange(0, 64)
        self.ao_count_spin.valueChanged.connect(lambda value: self._resize_ao_table(value))

        load_button = QPushButton("Load Config")
        save_button = QPushButton("Save Config")
        apply_button = QPushButton("Apply")
        close_button = QPushButton("Close")
        load_button.clicked.connect(self._load_config)
        save_button.clicked.connect(self._save_config)
        apply_button.clicked.connect(self._apply_changes)
        close_button.clicked.connect(self.reject)

        counts = QGridLayout()
        counts.addWidget(QLabel("AI Count"), 0, 0)
        counts.addWidget(self.ai_count_spin, 0, 1)
        counts.addWidget(QLabel("AO Count"), 0, 2)
        counts.addWidget(self.ao_count_spin, 0, 3)
        counts.setColumnStretch(4, 1)

        ai_group = QGroupBox("AI Channels")
        ai_layout = QVBoxLayout(ai_group)
        ai_layout.addWidget(self.ai_table, 1)
        ao_group = QGroupBox("AO Channels")
        ao_layout = QVBoxLayout(ao_group)
        ao_layout.addWidget(self.ao_table, 1)

        tabs = QTabWidget()
        tabs.addTab(ai_group, "AI")
        tabs.addTab(ao_group, "AO")

        buttons = QDialogButtonBox(self)
        buttons.addButton(load_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(save_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addLayout(counts)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)
        self._load_into_tables(self._working_config)

    def _default_ai_channel(self, index: int) -> AnalogInputChannelConfig:
        return AnalogInputChannelConfig(
            enabled=True,
            name=f"AI {index + 1}",
            physical_channel=f"{self._working_config.chassis_name}Mod{self._working_config.ai_module_slot}/ai{index}",
            measurement_mode="resistance",
            scale=1.0,
            offset=0.0,
            engineering_unit="ohm",
            color="#3A7CA5",
        )

    def _default_ao_channel(self, index: int) -> AnalogOutputChannelConfig:
        return AnalogOutputChannelConfig(
            enabled=True,
            name=f"AO {index + 1}",
            physical_channel=f"{self._working_config.chassis_name}Mod{self._working_config.ao_module_slot}/ao{index}",
            min_current_ma=0.0,
            max_current_ma=20.0,
            initial_current_ma=0.0,
        )

    def _load_into_tables(self, config: AppConfig) -> None:
        self._working_config = validate_app_config(replace(config))
        self.ai_count_spin.blockSignals(True)
        self.ao_count_spin.blockSignals(True)
        self.ai_count_spin.setValue(len(config.ai_channels))
        self.ao_count_spin.setValue(len(config.ao_channels))
        self.ai_count_spin.blockSignals(False)
        self.ao_count_spin.blockSignals(False)

        self.ai_table.setRowCount(len(config.ai_channels))
        for row, channel in enumerate(config.ai_channels):
            self._set_item(self.ai_table, row, 0, "1" if channel.enabled else "0")
            self._set_item(self.ai_table, row, 1, channel.name)
            self._set_item(self.ai_table, row, 2, channel.physical_channel)
            self._set_item(self.ai_table, row, 3, channel.measurement_mode)
            self._set_item(self.ai_table, row, 4, f"{channel.scale:g}")
            self._set_item(self.ai_table, row, 5, f"{channel.offset:g}")
            self._set_item(self.ai_table, row, 6, channel.engineering_unit)
            self._set_item(self.ai_table, row, 7, channel.color)

        self.ao_table.setRowCount(len(config.ao_channels))
        for row, channel in enumerate(config.ao_channels):
            self._set_item(self.ao_table, row, 0, "1" if channel.enabled else "0")
            self._set_item(self.ao_table, row, 1, channel.name)
            self._set_item(self.ao_table, row, 2, channel.physical_channel)
            self._set_item(self.ao_table, row, 3, f"{channel.min_current_ma:g}")
            self._set_item(self.ao_table, row, 4, f"{channel.max_current_ma:g}")
            self._set_item(self.ao_table, row, 5, f"{channel.initial_current_ma:g}")

    def _set_item(self, table: QTableWidget, row: int, column: int, value: str) -> None:
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        item.setText(value)

    def _resize_ai_table(self, count: int) -> None:
        current = self._collect_ai_channels()
        while len(current) < count:
            current.append(self._default_ai_channel(len(current)))
        self._working_config = replace(self._working_config, ai_channels=current[:count])
        self._load_into_tables(self._working_config)

    def _resize_ao_table(self, count: int) -> None:
        current = self._collect_ao_channels()
        while len(current) < count:
            current.append(self._default_ao_channel(len(current)))
        self._working_config = replace(self._working_config, ao_channels=current[:count])
        self._load_into_tables(self._working_config)

    def _table_text(self, table: QTableWidget, row: int, column: int, default: str = "") -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None else default

    def _collect_ai_channels(self) -> list[AnalogInputChannelConfig]:
        channels: list[AnalogInputChannelConfig] = []
        for row in range(self.ai_table.rowCount()):
            channels.append(
                AnalogInputChannelConfig(
                    enabled=self._table_text(self.ai_table, row, 0, "1") not in {"0", "false", "False", ""},
                    name=self._table_text(self.ai_table, row, 1, f"AI {row + 1}") or f"AI {row + 1}",
                    physical_channel=self._table_text(self.ai_table, row, 2, self._default_ai_channel(row).physical_channel),
                    measurement_mode=self._table_text(self.ai_table, row, 3, "resistance") or "resistance",
                    scale=float(self._table_text(self.ai_table, row, 4, "1.0")),
                    offset=float(self._table_text(self.ai_table, row, 5, "0.0")),
                    engineering_unit=self._table_text(self.ai_table, row, 6, "ohm") or "ohm",
                    color=self._table_text(self.ai_table, row, 7, "#3A7CA5") or "#3A7CA5",
                )
            )
        return channels

    def _collect_ao_channels(self) -> list[AnalogOutputChannelConfig]:
        channels: list[AnalogOutputChannelConfig] = []
        for row in range(self.ao_table.rowCount()):
            channels.append(
                AnalogOutputChannelConfig(
                    enabled=self._table_text(self.ao_table, row, 0, "1") not in {"0", "false", "False", ""},
                    name=self._table_text(self.ao_table, row, 1, f"AO {row + 1}") or f"AO {row + 1}",
                    physical_channel=self._table_text(self.ao_table, row, 2, self._default_ao_channel(row).physical_channel),
                    min_current_ma=float(self._table_text(self.ao_table, row, 3, "0.0")),
                    max_current_ma=float(self._table_text(self.ao_table, row, 4, "20.0")),
                    initial_current_ma=float(self._table_text(self.ao_table, row, 5, "0.0")),
                )
            )
        return channels

    def _build_config(self) -> AppConfig:
        config = replace(
            self._working_config,
            ai_channels=self._collect_ai_channels(),
            ao_channels=self._collect_ao_channels(),
        )
        return validate_app_config(config)

    def _load_config(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Channel Config",
            str(resolve_runtime_path(Path("config") / "channel_settings.example.json")),
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            self._load_into_tables(load_config(file_path))
            self.status_label.setText(f"Loaded config: {file_path}")
        except Exception as exc:
            QMessageBox.warning(self, "Load Channel Config", str(exc))

    def _save_config(self) -> None:
        try:
            config = self._build_config()
        except Exception as exc:
            QMessageBox.warning(self, "Save Channel Config", str(exc))
            return
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Channel Config",
            str(resolve_runtime_path(Path("dev_local") / "tmp" / "channel_config.json")),
            "JSON Files (*.json)",
        )
        if not file_path:
            return
        try:
            save_config(file_path, config)
            self.status_label.setText(f"Saved config: {file_path}")
        except Exception as exc:
            QMessageBox.warning(self, "Save Channel Config", str(exc))

    def _apply_changes(self) -> None:
        try:
            config = self._build_config()
        except Exception as exc:
            QMessageBox.warning(self, "Apply Channel Config", str(exc))
            return
        self._apply_config(config)
        self.status_label.setText("Channel config applied to the main window.")
        self.accept()


class MarkerManagerDialog(QDialog):
    DAQ_HEADERS = ("Name", "Kind", "Start s", "End s", "Color")
    STAGE_HEADERS = ("Name", "Kind", "Move time s", "Value mm", "Color")

    def __init__(
        self,
        *,
        parent: QWidget | None,
        collect_markers: Callable[[], tuple[list[dict[str, Any]], list[dict[str, Any]]]],
        apply_markers: Callable[[list[dict[str, Any]], list[dict[str, Any]]], None],
        export_markers: Callable[[Path], None],
    ) -> None:
        super().__init__(parent)
        self._collect_markers = collect_markers
        self._apply_markers = apply_markers
        self._export_markers = export_markers

        self.setWindowTitle("Marker Manager")
        self.resize(900, 620)
        self.setMinimumSize(760, 500)

        self.status_label = QLabel("Rename, recolor, delete, or export DAQ/Stage markers.")
        self.status_label.setWordWrap(True)

        self.daq_table = QTableWidget(0, len(self.DAQ_HEADERS))
        self.daq_table.setHorizontalHeaderLabels(self.DAQ_HEADERS)
        self.stage_table = QTableWidget(0, len(self.STAGE_HEADERS))
        self.stage_table.setHorizontalHeaderLabels(self.STAGE_HEADERS)

        refresh_button = QPushButton("Refresh")
        delete_button = QPushButton("Delete Selected")
        apply_button = QPushButton("Apply")
        export_button = QPushButton("Export")
        close_button = QPushButton("Close")

        refresh_button.clicked.connect(self.refresh_tables)
        delete_button.clicked.connect(self._delete_selected)
        apply_button.clicked.connect(self._apply_changes)
        export_button.clicked.connect(self._export)
        close_button.clicked.connect(self.reject)

        buttons = QDialogButtonBox(self)
        buttons.addButton(refresh_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(delete_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(export_button, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.addButton(close_button, QDialogButtonBox.ButtonRole.RejectRole)

        tabs = QTabWidget()
        tabs.addTab(self.daq_table, "DAQ Markers")
        tabs.addTab(self.stage_table, "Stage Markers")

        layout = QVBoxLayout(self)
        layout.addWidget(self.status_label)
        layout.addWidget(tabs, 1)
        layout.addWidget(buttons)
        self.refresh_tables()

    def refresh_tables(self) -> None:
        daq_marks, stage_marks = self._collect_markers()
        self._fill_daq_table(daq_marks)
        self._fill_stage_table(stage_marks)
        self.status_label.setText(f"Loaded {len(daq_marks)} DAQ markers and {len(stage_marks)} Stage markers.")

    def _fill_daq_table(self, markers: list[dict[str, Any]]) -> None:
        self.daq_table.setRowCount(len(markers))
        for row, marker in enumerate(markers):
            self._set_item(self.daq_table, row, 0, str(marker.get("name", f"DAQ Mark {row + 1}")))
            self._set_item(self.daq_table, row, 1, str(marker.get("kind", "interval")))
            self._set_item(self.daq_table, row, 2, f"{float(marker.get('start_s', 0.0)):.6g}")
            self._set_item(self.daq_table, row, 3, f"{float(marker.get('end_s', 0.0)):.6g}")
            self._set_item(self.daq_table, row, 4, str(marker.get("color", "#F0C241")))

    def _fill_stage_table(self, markers: list[dict[str, Any]]) -> None:
        self.stage_table.setRowCount(len(markers))
        for row, marker in enumerate(markers):
            self._set_item(self.stage_table, row, 0, str(marker.get("name", f"Stage Mark {row + 1}")))
            self._set_item(self.stage_table, row, 1, str(marker.get("kind", "stage")))
            self._set_item(self.stage_table, row, 2, f"{float(marker.get('move_time_s', 0.0)):.6g}")
            self._set_item(self.stage_table, row, 3, f"{float(marker.get('value_mm', 0.0)):.6g}")
            self._set_item(self.stage_table, row, 4, str(marker.get("color", "#F778BA")))

    def _set_item(self, table: QTableWidget, row: int, column: int, value: str) -> None:
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            table.setItem(row, column, item)
        item.setText(value)
        if column == 4:
            item.setBackground(QColor(value) if QColor(value).isValid() else QColor("#30363D"))

    def _delete_selected(self) -> None:
        daq_rows = sorted({index.row() for index in self.daq_table.selectedIndexes()}, reverse=True)
        stage_rows = sorted({index.row() for index in self.stage_table.selectedIndexes()}, reverse=True)
        for row in daq_rows:
            self.daq_table.removeRow(row)
        for row in stage_rows:
            self.stage_table.removeRow(row)
        self.status_label.setText("Selected markers removed from the pending table state.")

    def _collect_daq_table(self) -> list[dict[str, Any]]:
        markers: list[dict[str, Any]] = []
        for row in range(self.daq_table.rowCount()):
            markers.append(
                {
                    "name": self._text(self.daq_table, row, 0, f"DAQ Mark {row + 1}"),
                    "kind": self._text(self.daq_table, row, 1, "interval"),
                    "start_s": float(self._text(self.daq_table, row, 2, "0.0")),
                    "end_s": float(self._text(self.daq_table, row, 3, "0.0")),
                    "color": self._text(self.daq_table, row, 4, "#F0C241"),
                }
            )
        return markers

    def _collect_stage_table(self) -> list[dict[str, Any]]:
        markers: list[dict[str, Any]] = []
        for row in range(self.stage_table.rowCount()):
            markers.append(
                {
                    "name": self._text(self.stage_table, row, 0, f"Stage Mark {row + 1}"),
                    "kind": self._text(self.stage_table, row, 1, "stage"),
                    "move_time_s": float(self._text(self.stage_table, row, 2, "0.0")),
                    "value_mm": float(self._text(self.stage_table, row, 3, "0.0")),
                    "color": self._text(self.stage_table, row, 4, "#F778BA"),
                }
            )
        return markers

    def _text(self, table: QTableWidget, row: int, column: int, default: str) -> str:
        item = table.item(row, column)
        return item.text().strip() if item is not None and item.text().strip() else default

    def _apply_changes(self) -> None:
        try:
            self._apply_markers(self._collect_daq_table(), self._collect_stage_table())
        except Exception as exc:
            QMessageBox.warning(self, "Apply Markers", str(exc))
            return
        self.status_label.setText("Marker changes applied.")
        self.accept()

    def _export(self) -> None:
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Export Markers",
            str(resolve_runtime_path(Path("dev_local") / "tmp" / "markers.json")),
            "JSON Files (*.json)",
        )
        if not target:
            return
        try:
            self._export_markers(resolve_runtime_path(target))
            self.status_label.setText(f"Markers exported: {target}")
        except Exception as exc:
            QMessageBox.warning(self, "Export Markers", str(exc))
