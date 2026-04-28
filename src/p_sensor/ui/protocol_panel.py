from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from p_sensor.automation import AutomationRecipe, ProtocolRecipeSpec, compile_protocol_recipe


class ProtocolPanel(QWidget):
    recipe_created = Signal(object)
    error_reported = Signal(str, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["step_hold", "hysteresis", "speed_dependency", "fatigue"])
        self.protocol_combo.setMaximumWidth(132)
        self.protocol_combo.currentTextChanged.connect(self._refresh_preview)

        self.max_displacement_spin = self._new_double_spin(0.001, 35.0, 3, 1.0, 0.1)
        self.step_increment_spin = self._new_double_spin(0.001, 10.0, 3, 0.1, 0.1)
        self.hold_time_spin = self._new_double_spin(0.0, 3600.0, 2, 0.5, 0.1)
        self.measure_frames_spin = QSpinBox()
        self.measure_frames_spin.setRange(1, 1_000_000)
        self.measure_frames_spin.setValue(10)
        self.speed_spin = self._new_double_spin(0.001, 500.0, 3, 10.0, 1.0)
        self.speed_a_spin = self._new_double_spin(0.001, 500.0, 3, 1.0, 1.0)
        self.speed_b_spin = self._new_double_spin(0.001, 500.0, 3, 10.0, 1.0)
        self.speed_c_spin = self._new_double_spin(0.001, 500.0, 3, 50.0, 1.0)
        self.cycle_count_spin = QSpinBox()
        self.cycle_count_spin.setRange(1, 1_000_000)
        self.cycle_count_spin.setValue(3)
        self.checkpoint_spin = QSpinBox()
        self.checkpoint_spin.setRange(1, 100_000)
        self.checkpoint_spin.setValue(10)
        self.contact_detect_check = QCheckBox("Contact")
        self.contact_detect_check.toggled.connect(self._refresh_preview)
        self.contact_detect_check.toggled.connect(self._update_contact_detection_mode)
        self.contact_use_zero_check = QCheckBox("Use0")
        self.contact_use_zero_check.setChecked(True)
        self.contact_use_zero_check.toggled.connect(self._refresh_preview)
        self.contact_axis_spin = QSpinBox()
        self.contact_axis_spin.setRange(1, 2)
        self.contact_axis_spin.setValue(1)
        self.contact_channel_spin = QSpinBox()
        self.contact_channel_spin.setRange(0, 63)
        self.contact_channel_spin.setValue(0)
        self.contact_speed_spin = self._new_double_spin(0.02, 10.0, 3, 0.02, 0.01)
        self.contact_step_spin = self._new_double_spin(0.01, 5.0, 3, 0.01, 0.01)
        self.contact_travel_spin = self._new_double_spin(1.0, 100.0, 3, 1.0, 0.1)
        self.contact_threshold_spin = self._new_double_spin(1.0, 1_000_000.0, 3, 1.0, 0.1)
        self.contact_baseline_spin = self._new_double_spin(0.2, 60.0, 3, 0.2, 0.05)
        self.contact_stable_spin = self._new_double_spin(0.05, 60.0, 3, 0.05, 0.01)

        for widget in (
            self.max_displacement_spin,
            self.step_increment_spin,
            self.hold_time_spin,
            self.measure_frames_spin,
            self.speed_spin,
            self.speed_a_spin,
            self.speed_b_spin,
            self.speed_c_spin,
            self.cycle_count_spin,
            self.checkpoint_spin,
            self.contact_axis_spin,
            self.contact_channel_spin,
            self.contact_speed_spin,
            self.contact_step_spin,
            self.contact_travel_spin,
            self.contact_threshold_spin,
            self.contact_baseline_spin,
            self.contact_stable_spin,
        ):
            widget.setMaximumWidth(82)

        for widget in (
            self.max_displacement_spin,
            self.step_increment_spin,
            self.hold_time_spin,
            self.measure_frames_spin,
            self.speed_spin,
            self.speed_a_spin,
            self.speed_b_spin,
            self.speed_c_spin,
            self.cycle_count_spin,
            self.checkpoint_spin,
            self.contact_axis_spin,
            self.contact_channel_spin,
            self.contact_speed_spin,
            self.contact_step_spin,
            self.contact_travel_spin,
            self.contact_threshold_spin,
            self.contact_baseline_spin,
            self.contact_stable_spin,
        ):
            value_changed = getattr(widget, "valueChanged", None)
            if value_changed is not None:
                value_changed.connect(self._refresh_preview)

        self.preview_label = QLabel("No recipe generated")
        self.preview_label.setWordWrap(True)
        self.sequence_preview = QPlainTextEdit()
        self.sequence_preview.setReadOnly(True)
        self.sequence_preview.setMinimumHeight(84)
        self.create_button = QPushButton("Use Protocol Recipe")
        self.create_button.clicked.connect(self._create_recipe)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)
        grid = QGridLayout()
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self._add_row(grid, 0, 0, "Type", self.protocol_combo)
        self._add_row(grid, 0, 2, "Max", self.max_displacement_spin)
        self._add_row(grid, 1, 0, "Step", self.step_increment_spin)
        self._add_row(grid, 1, 2, "Hold", self.hold_time_spin)
        self._add_row(grid, 2, 0, "Frames", self.measure_frames_spin)
        self._add_row(grid, 2, 2, "Speed", self.speed_spin)
        self._add_row(grid, 3, 0, "Cycles", self.cycle_count_spin)
        self._add_row(grid, 3, 2, "Chkpt", self.checkpoint_spin)
        self._add_row(grid, 4, 0, "V1", self.speed_a_spin)
        self._add_row(grid, 4, 2, "V2", self.speed_b_spin)
        self._add_row(grid, 5, 0, "V3", self.speed_c_spin)
        self._add_row(grid, 6, 0, "CD", self.contact_detect_check, self.contact_use_zero_check)
        self._add_row(grid, 6, 2, "Axis", self.contact_axis_spin, QLabel("Ch"), self.contact_channel_spin)
        self._add_row(grid, 7, 0, "CV", self.contact_speed_spin)
        self._add_row(grid, 7, 2, "CStep", self.contact_step_spin)
        self._add_row(grid, 8, 0, "CTravel", self.contact_travel_spin)
        self._add_row(grid, 8, 2, "CdR", self.contact_threshold_spin)
        self._add_row(grid, 9, 0, "CBase", self.contact_baseline_spin)
        self._add_row(grid, 9, 2, "CStable", self.contact_stable_spin)
        layout.addLayout(grid)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.sequence_preview, 1)
        layout.addWidget(self.create_button)
        self._update_contact_detection_mode(self.contact_detect_check.isChecked())
        self._refresh_preview()

    def build_recipe(self) -> AutomationRecipe:
        protocol_type = self.protocol_combo.currentText()
        cycle_count = self.cycle_count_spin.value()
        if protocol_type == "step_hold":
            cycle_count = 1
        velocities = []
        if protocol_type == "speed_dependency":
            velocities = [self.speed_a_spin.value(), self.speed_b_spin.value(), self.speed_c_spin.value()]
        spec = ProtocolRecipeSpec(
            recipe_id=f"{protocol_type}_protocol",
            protocol_type=protocol_type,
            min_displacement_mm=0.0,
            max_displacement_mm=self.max_displacement_spin.value(),
            step_increment_mm=None if protocol_type == "fatigue" else self.step_increment_spin.value(),
            hold_time_s=self.hold_time_spin.value(),
            measure_frame_count=self.measure_frames_spin.value(),
            velocity_mm_min=self.speed_spin.value(),
            velocities_mm_min=velocities,
            return_velocity_mm_min=self.speed_spin.value(),
            cycle_count=cycle_count,
            checkpoint_interval_cycles=self.checkpoint_spin.value(),
            metadata=self._build_metadata(),
        )
        return compile_protocol_recipe(spec)

    def _create_recipe(self) -> None:
        try:
            self.recipe_created.emit(self.build_recipe())
        except Exception as exc:
            self.error_reported.emit("Protocol Recipe Failed", str(exc))

    def _refresh_preview(self) -> None:
        try:
            recipe = self.build_recipe()
            measured = len([step for step in recipe.steps if step.measure_enabled])
            contact_text = " | CD on" if recipe.metadata.get("enable_contact_detection") else ""
            self.preview_label.setText(
                f"{recipe.recipe_id}: {len(recipe.steps)} moves, {measured} measurement windows{contact_text}"
            )
            self.sequence_preview.setPlainText(self._format_sequence_preview(recipe))
        except Exception as exc:
            self.preview_label.setText(str(exc))
            self.sequence_preview.setPlainText("")

    def _build_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {"source": "protocol_panel"}
        contact_metadata = {
            "enable_contact_detection": self.contact_detect_check.isChecked(),
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
        metadata.update(contact_metadata)
        metadata["contact_detection"] = dict(contact_metadata)
        return metadata

    def _update_contact_detection_mode(self, enabled: bool) -> None:
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

    def _format_sequence_preview(self, recipe: AutomationRecipe) -> str:
        lines = []
        for index, step in enumerate(recipe.steps[:8], start=1):
            phase = step.phase or "step"
            target = "" if step.target_displacement is None else f"{step.target_displacement:g} mm"
            speed = "" if step.velocity_mm_min is None else f", {step.velocity_mm_min:g} mm/min"
            measure = "measure" if step.measure_enabled else "motion"
            cycle = "" if step.cycle_index is None else f"C{step.cycle_index} "
            lines.append(f"{index}. {cycle}{phase}: {target}{speed} [{measure}]")
        if len(recipe.steps) > len(lines):
            lines.append(f"... {len(recipe.steps) - len(lines)} more steps")
        return "\n".join(lines)

    def _add_row(self, grid: QGridLayout, row: int, column: int, label: str, *widgets) -> None:
        grid.addWidget(QLabel(label), row, column)
        for offset, widget in enumerate(widgets, start=1):
            grid.addWidget(widget, row, column + offset)

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
