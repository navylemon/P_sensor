from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from p_sensor.automation import ProtocolRecipeSpec, compile_protocol_recipe
from p_sensor.automation.models import AutomationRecipe


@dataclass(slots=True)
class RecipeHelperResult:
    recipe: AutomationRecipe
    suggested_file_name: str


class RecipeHelperDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recipe Wizard")
        screen = self.screen()
        available_height = screen.availableGeometry().height() if screen is not None else 720
        self.resize(560, min(640, max(480, available_height - 120)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        form_container = QWidget()
        form = QFormLayout()
        form_container.setLayout(form)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["step_hold", "hysteresis", "speed_dependency", "fatigue"])
        self.recipe_id_edit = QLineEdit("step_hold_protocol")
        self.recipe_id_edit.setPlaceholderText("Recipe id")
        self.start_spin = self._new_double_spin(0.0)
        self.stop_spin = self._new_double_spin(1.0)
        self.step_spin = self._new_double_spin(0.1, minimum=0.000001)
        self.settle_spin = self._new_double_spin(0.2, minimum=0.0, maximum=3600.0, decimals=3, single_step=0.1)
        self.speed_spin = self._new_double_spin(10.0, minimum=0.001, maximum=500.0, decimals=3, single_step=1.0)
        self.speed_a_spin = self._new_double_spin(1.0, minimum=0.001, maximum=500.0, decimals=3, single_step=1.0)
        self.speed_b_spin = self._new_double_spin(10.0, minimum=0.001, maximum=500.0, decimals=3, single_step=1.0)
        self.speed_c_spin = self._new_double_spin(50.0, minimum=0.001, maximum=500.0, decimals=3, single_step=1.0)
        self.cycle_count_spin = QSpinBox()
        self.cycle_count_spin.setRange(1, 1_000_000)
        self.cycle_count_spin.setValue(3)
        self.checkpoint_spin = QSpinBox()
        self.checkpoint_spin.setRange(1, 100_000)
        self.checkpoint_spin.setValue(10)
        self.measure_mode_combo = QComboBox()
        self.measure_mode_combo.addItems(["Frame Count", "Duration"])
        self.frame_count_spin = QSpinBox()
        self.frame_count_spin.setRange(1, 1000000)
        self.frame_count_spin.setValue(5)
        self.duration_spin = self._new_double_spin(0.5, minimum=0.001, maximum=3600.0, decimals=3, single_step=0.1)
        self.duration_spin.setEnabled(False)
        self.measure_mode_combo.currentTextChanged.connect(self._update_measurement_mode)
        self.disengage_checkbox = QCheckBox()
        self.disengage_checkbox.setChecked(True)
        self.post_wait_spin = self._new_double_spin(0.1, minimum=0.0, maximum=3600.0, decimals=3, single_step=0.1)
        self.ready_timeout_spin = self._new_double_spin(10.0, minimum=0.001, maximum=3600.0, decimals=3, single_step=0.5)
        self.notes_prefix_edit = QLineEdit()
        self.notes_prefix_edit.setPlaceholderText("Optional note prefix")
        self.contact_relative_checkbox = QCheckBox()
        self.contact_direction_combo = QComboBox()
        self.contact_direction_combo.addItem("Down / -Z", -1.0)
        self.contact_direction_combo.addItem("Up / +Z", 1.0)
        self.contact_detect_checkbox = QCheckBox()
        self.contact_use_zero_checkbox = QCheckBox()
        self.contact_use_zero_checkbox.setChecked(True)
        self.contact_axis_spin = QSpinBox()
        self.contact_axis_spin.setRange(1, 2)
        self.contact_axis_spin.setValue(1)
        self.contact_channel_spin = QSpinBox()
        self.contact_channel_spin.setRange(0, 63)
        self.contact_channel_spin.setValue(0)
        self.contact_speed_spin = self._new_double_spin(
            0.02, minimum=0.001, maximum=10.0, decimals=3, single_step=0.01
        )
        self.contact_step_spin = self._new_double_spin(
            0.01, minimum=0.001, maximum=5.0, decimals=3, single_step=0.01
        )
        self.contact_travel_spin = self._new_double_spin(
            1.0, minimum=0.001, maximum=100.0, decimals=3, single_step=0.1
        )
        self.contact_threshold_spin = self._new_double_spin(
            1.0, minimum=0.001, maximum=1_000_000.0, decimals=3, single_step=0.1
        )
        self.contact_baseline_spin = self._new_double_spin(
            0.2, minimum=0.0, maximum=60.0, decimals=3, single_step=0.05
        )
        self.contact_stable_spin = self._new_double_spin(
            0.05, minimum=0.0, maximum=60.0, decimals=3, single_step=0.01
        )
        self.protocol_combo.currentTextChanged.connect(self._update_protocol_mode)
        self.contact_relative_checkbox.toggled.connect(self._update_contact_relative_mode)
        self.contact_detect_checkbox.toggled.connect(self._update_contact_detection_mode)

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.measure_mode_combo)
        mode_row.addWidget(self.frame_count_spin)
        mode_row.addWidget(self.duration_spin)

        form.addRow(QLabel("Step 1 - Measurement Method"))
        form.addRow("Method", self.protocol_combo)
        form.addRow("Recipe ID", self.recipe_id_edit)
        form.addRow(QLabel("Step 2 - Motion and Measurement"))
        form.addRow("Start mm", self.start_spin)
        form.addRow("Stop mm", self.stop_spin)
        form.addRow("Step mm", self.step_spin)
        form.addRow("Settle s", self.settle_spin)
        form.addRow("Velocity mm/min", self.speed_spin)
        form.addRow("Cycles", self.cycle_count_spin)
        form.addRow("Checkpoint", self.checkpoint_spin)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed_a_spin)
        speed_row.addWidget(self.speed_b_spin)
        speed_row.addWidget(self.speed_c_spin)
        form.addRow("Speed set", speed_row)
        form.addRow("Measure", mode_row)
        form.addRow("Disengage", self.disengage_checkbox)
        form.addRow("Post Wait s", self.post_wait_spin)
        form.addRow("Ready Timeout s", self.ready_timeout_spin)
        form.addRow("Notes Prefix", self.notes_prefix_edit)
        form.addRow(QLabel("Step 3 - Optional Contact Start"))
        form.addRow("Use Contact Start", self.contact_relative_checkbox)
        form.addRow("Press Direction", self.contact_direction_combo)
        form.addRow(QLabel("Step 4 - Optional Contact Check"))
        form.addRow("Contact Detect", self.contact_detect_checkbox)
        form.addRow("Contact Axis", self.contact_axis_spin)
        form.addRow("Contact Ch", self.contact_channel_spin)
        form.addRow("Use As Zero", self.contact_use_zero_checkbox)
        form.addRow("Contact Speed", self.contact_speed_spin)
        form.addRow("Contact Step", self.contact_step_spin)
        form.addRow("Contact Travel", self.contact_travel_spin)
        form.addRow("Contact dR", self.contact_threshold_spin)
        form.addRow("Baseline s", self.contact_baseline_spin)
        form.addRow("Stable s", self.contact_stable_spin)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setWidget(form_container)
        layout.addWidget(scroll_area, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_protocol_mode(self.protocol_combo.currentText())
        self._update_contact_relative_mode(self.contact_relative_checkbox.isChecked())
        self._update_contact_detection_mode(self.contact_detect_checkbox.isChecked())

    def build_result(self) -> RecipeHelperResult:
        protocol_type = self.protocol_combo.currentText()
        if self.contact_relative_checkbox.isChecked() and min(self.start_spin.value(), self.stop_spin.value()) < 0:
            raise ValueError("Contact-relative press depth must be 0 mm or greater.")
        velocities = []
        if protocol_type == "speed_dependency":
            velocities = [self.speed_a_spin.value(), self.speed_b_spin.value(), self.speed_c_spin.value()]
        spec = ProtocolRecipeSpec(
            recipe_id=self.recipe_id_edit.text().strip(),
            protocol_type=protocol_type,
            min_displacement_mm=self.start_spin.value(),
            max_displacement_mm=self.stop_spin.value(),
            step_increment_mm=None if protocol_type == "fatigue" else self.step_spin.value(),
            hold_time_s=self.settle_spin.value(),
            measure_duration_s=self.duration_spin.value() if self._measurement_mode_is_duration() else None,
            measure_frame_count=self.frame_count_spin.value() if not self._measurement_mode_is_duration() else None,
            velocity_mm_min=self.speed_spin.value(),
            velocities_mm_min=velocities,
            return_velocity_mm_min=self.speed_spin.value(),
            cycle_count=1 if protocol_type == "step_hold" else self.cycle_count_spin.value(),
            checkpoint_interval_cycles=self.checkpoint_spin.value(),
            ready_timeout_s=self.ready_timeout_spin.value(),
            metadata=self._build_metadata(),
        )
        recipe = compile_protocol_recipe(spec)
        return RecipeHelperResult(recipe=recipe, suggested_file_name=f"{recipe.recipe_id}.json")

    def accept(self) -> None:
        try:
            self.build_result()
        except Exception as exc:
            QMessageBox.critical(self, "Recipe Helper Error", str(exc))
            return
        super().accept()

    def _measurement_mode_is_duration(self) -> bool:
        return self.measure_mode_combo.currentText() == "Duration"

    def _update_measurement_mode(self, mode: str) -> None:
        use_duration = mode == "Duration"
        self.frame_count_spin.setEnabled(not use_duration)
        self.duration_spin.setEnabled(use_duration)

    def _update_contact_detection_mode(self, enabled: bool) -> None:
        for widget in (
            self.contact_use_zero_checkbox,
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

    def _update_contact_relative_mode(self, enabled: bool) -> None:
        self.contact_direction_combo.setEnabled(enabled)

    def _update_protocol_mode(self, protocol_type: str) -> None:
        self.step_spin.setEnabled(protocol_type != "fatigue")
        self.speed_a_spin.setEnabled(protocol_type == "speed_dependency")
        self.speed_b_spin.setEnabled(protocol_type == "speed_dependency")
        self.speed_c_spin.setEnabled(protocol_type == "speed_dependency")
        self.cycle_count_spin.setEnabled(protocol_type != "step_hold")
        self.checkpoint_spin.setEnabled(protocol_type == "fatigue")
        if not self.recipe_id_edit.text().strip() or self.recipe_id_edit.text().strip().endswith("_protocol"):
            self.recipe_id_edit.setText(f"{protocol_type}_protocol")

    def _build_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "helper": "recipe_helper_dialog",
            "notes_prefix": self.notes_prefix_edit.text().strip(),
            "disengage_after_measure": self.disengage_checkbox.isChecked(),
            "post_disengage_wait_s": self.post_wait_spin.value(),
        }
        if self.contact_relative_checkbox.isChecked():
            direction = float(self.contact_direction_combo.currentData())
            metadata.update(
                {
                    "coordinate_mode": "contact_relative",
                    "contact_relative": {
                        "enabled": True,
                        "press_direction": direction,
                        "target_units": "press_depth_mm",
                    },
                }
            )
        contact_metadata = {
            "enable_contact_detection": self.contact_detect_checkbox.isChecked(),
            "contact_stage_axis": self.contact_axis_spin.value(),
            "contact_channel_index": self.contact_channel_spin.value(),
            "contact_scan_speed_mm_s": self.contact_speed_spin.value(),
            "contact_scan_step_mm": self.contact_step_spin.value(),
            "contact_max_travel_mm": self.contact_travel_spin.value(),
            "contact_delta_resistance_threshold_ohm": self.contact_threshold_spin.value(),
            "contact_baseline_duration_s": self.contact_baseline_spin.value(),
            "contact_stable_duration_s": self.contact_stable_spin.value(),
            "contact_use_as_zero": self.contact_use_zero_checkbox.isChecked(),
        }
        metadata.update(contact_metadata)
        metadata["contact_detection"] = dict(contact_metadata)
        return metadata

    def _new_double_spin(
        self,
        value: float,
        *,
        minimum: float = -1000000.0,
        maximum: float = 1000000.0,
        decimals: int = 6,
        single_step: float = 0.1,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(single_step)
        spin.setValue(value)
        return spin
