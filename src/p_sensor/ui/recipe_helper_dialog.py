from __future__ import annotations

from dataclasses import dataclass
from html import escape
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


PROTOCOL_GUIDANCE = {
    "step_hold": (
        "Moves from start to stop in fixed displacement steps. Each point is held, measured once, "
        "then the stage returns to the start position."
    ),
    "hysteresis": (
        "Repeats loading and unloading between start and stop. Use this when the return path matters."
    ),
    "speed_dependency": (
        "Runs the same displacement sweep at V1, V2, and V3. Use this to compare velocity effects."
    ),
    "fatigue": (
        "Cycles between start and stop many times. Measurements are saved only at checkpoint cycles."
    ),
}


FIELD_HELP = {
    "Method": "Selects the experiment pattern used to generate the step sequence.",
    "Recipe ID": "File-friendly name stored in the generated recipe JSON.",
    "Start displacement (mm)": "Minimum press depth or displacement target used by the protocol.",
    "Stop displacement (mm)": "Maximum press depth or displacement target. Must be greater than start.",
    "Step interval (mm)": "Distance between adjacent measurement points. Fatigue uses only start and stop.",
    "Hold before measure (s)": "Wait time after each move before DAQ measurement starts.",
    "Move velocity (mm/min)": "Stage speed for ordinary moves. Speed dependency uses V1/V2/V3 instead.",
    "Cycles": "Number of repeated loading/unloading cycles. Step-hold always uses one cycle.",
    "Checkpoint interval": "For fatigue, records a measurement every N cycles plus the first and last cycle.",
    "Speed set (V1/V2/V3)": "Velocity values used by the speed-dependency protocol.",
    "Measure mode": "Choose whether each measurement window is defined by frame count or elapsed time.",
    "Disengage after measure": "Adds metadata requesting release after measurement when the runner supports it.",
    "Post-disengage wait (s)": "Wait time after disengage before the next move begins.",
    "Ready timeout (s)": "Maximum wait for stage move-ready state before a step is treated as failed.",
    "Notes prefix": "Optional text copied into recipe metadata for later result review.",
    "Use contact start": "Interprets displacement values as press depth from the calibrated contact point.",
    "Press direction": "Axis direction that increases press depth from the contact point.",
    "Run contact check": "Runs an automatic contact scan before recipe execution.",
    "Contact axis": "Stage axis used for contact scan. This is the stage controller axis index.",
    "Contact channel": "DAQ channel index watched for contact signal change.",
    "Use contact as zero": "Stores detected contact as the recipe zero reference for the run.",
    "Contact scan speed": "Speed used during contact search. Keep conservative for first hardware runs.",
    "Contact scan step": "Micro-step size between contact signal checks.",
    "Max contact travel": "Maximum distance allowed during contact search before aborting.",
    "Contact dR threshold": "Resistance change threshold used to decide that contact occurred.",
    "Baseline duration": "Initial signal sampling time used to estimate the no-contact baseline.",
    "Stable duration": "Required stable time after threshold crossing before accepting contact.",
}

ABSOLUTE_POSITION_HELP = {
    "Start displacement (mm)": "Start target in the current stage/software coordinate system.",
    "Stop displacement (mm)": "Stop target in the current stage/software coordinate system.",
}

CONTACT_DEPTH_HELP = {
    "Start press depth (mm)": "Start depth measured from the calibrated contact point. Must be 0 or greater.",
    "Stop press depth (mm)": "Maximum depth measured from the calibrated contact point. Must be 0 or greater.",
}


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
        self._help_labels: dict[QWidget | QHBoxLayout, QLabel] = {}

        form_container = QWidget()
        form = QFormLayout()
        form_container.setLayout(form)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.protocol_combo = QComboBox()
        self.protocol_combo.addItems(["step_hold", "hysteresis", "speed_dependency", "fatigue"])
        self.method_description_label = QLabel()
        self.method_description_label.setWordWrap(True)
        self.method_description_label.setStyleSheet("color: #3f4a59;")
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
        self._connect_summary_updates()

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.measure_mode_combo)
        mode_row.addWidget(self.frame_count_spin)
        mode_row.addWidget(self.duration_spin)

        form.addRow(QLabel("Step 1 - Measurement Method"))
        self._add_help_row(form, "Method", self.protocol_combo)
        form.addRow("", self.method_description_label)
        self._add_help_row(form, "Recipe ID", self.recipe_id_edit)
        form.addRow(QLabel("Step 2 - Motion and Measurement"))
        self._add_help_row(form, "Start displacement (mm)", self.start_spin)
        self._add_help_row(form, "Stop displacement (mm)", self.stop_spin)
        self._add_help_row(form, "Step interval (mm)", self.step_spin)
        self._add_help_row(form, "Hold before measure (s)", self.settle_spin)
        self._add_help_row(form, "Move velocity (mm/min)", self.speed_spin)
        self._add_help_row(form, "Cycles", self.cycle_count_spin)
        self._add_help_row(form, "Checkpoint interval", self.checkpoint_spin)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self.speed_a_spin)
        speed_row.addWidget(self.speed_b_spin)
        speed_row.addWidget(self.speed_c_spin)
        self._add_help_row(form, "Speed set (V1/V2/V3)", speed_row)
        self._add_help_row(form, "Measure mode", mode_row)
        self._add_help_row(form, "Disengage after measure", self.disengage_checkbox)
        self._add_help_row(form, "Post-disengage wait (s)", self.post_wait_spin)
        self._add_help_row(form, "Ready timeout (s)", self.ready_timeout_spin)
        self._add_help_row(form, "Notes prefix", self.notes_prefix_edit)
        form.addRow(QLabel("Step 3 - Optional Contact Start"))
        self._add_help_row(form, "Use contact start", self.contact_relative_checkbox)
        self._add_help_row(form, "Press direction", self.contact_direction_combo)
        form.addRow(QLabel("Step 4 - Optional Contact Check"))
        self._add_help_row(form, "Run contact check", self.contact_detect_checkbox)
        self._add_help_row(form, "Contact axis", self.contact_axis_spin)
        self._add_help_row(form, "Contact channel", self.contact_channel_spin)
        self._add_help_row(form, "Use contact as zero", self.contact_use_zero_checkbox)
        self._add_help_row(form, "Contact scan speed", self.contact_speed_spin)
        self._add_help_row(form, "Contact scan step", self.contact_step_spin)
        self._add_help_row(form, "Max contact travel", self.contact_travel_spin)
        self._add_help_row(form, "Contact dR threshold", self.contact_threshold_spin)
        self._add_help_row(form, "Baseline duration", self.contact_baseline_spin)
        self._add_help_row(form, "Stable duration", self.contact_stable_spin)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.NoFrame)
        scroll_area.setWidget(form_container)
        layout.addWidget(scroll_area, 1)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-weight: 600; color: #25313f;")
        layout.addWidget(self.summary_label)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_protocol_mode(self.protocol_combo.currentText())
        self._update_contact_relative_mode(self.contact_relative_checkbox.isChecked())
        self._update_contact_detection_mode(self.contact_detect_checkbox.isChecked())
        self._refresh_summary()

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
        self._refresh_summary()

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
        self._refresh_summary()

    def _update_contact_relative_mode(self, enabled: bool) -> None:
        self.contact_direction_combo.setEnabled(enabled)
        self._set_dynamic_help(
            self.start_spin,
            "Start press depth (mm)" if enabled else "Start displacement (mm)",
            CONTACT_DEPTH_HELP["Start press depth (mm)"]
            if enabled
            else ABSOLUTE_POSITION_HELP["Start displacement (mm)"],
        )
        self._set_dynamic_help(
            self.stop_spin,
            "Stop press depth (mm)" if enabled else "Stop displacement (mm)",
            CONTACT_DEPTH_HELP["Stop press depth (mm)"]
            if enabled
            else ABSOLUTE_POSITION_HELP["Stop displacement (mm)"],
        )
        self._refresh_summary()

    def _update_protocol_mode(self, protocol_type: str) -> None:
        self.method_description_label.setText(PROTOCOL_GUIDANCE.get(protocol_type, ""))
        self.step_spin.setEnabled(protocol_type != "fatigue")
        self.speed_a_spin.setEnabled(protocol_type == "speed_dependency")
        self.speed_b_spin.setEnabled(protocol_type == "speed_dependency")
        self.speed_c_spin.setEnabled(protocol_type == "speed_dependency")
        self.cycle_count_spin.setEnabled(protocol_type != "step_hold")
        self.checkpoint_spin.setEnabled(protocol_type == "fatigue")
        if not self.recipe_id_edit.text().strip() or self.recipe_id_edit.text().strip().endswith("_protocol"):
            self.recipe_id_edit.setText(f"{protocol_type}_protocol")
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        if not hasattr(self, "summary_label"):
            return
        try:
            recipe = self.build_result().recipe
        except Exception as exc:
            self.summary_label.setText(f"Recipe preview unavailable: {exc}")
            return
        measured_count = sum(1 for step in recipe.steps if step.measure_enabled)
        contact_start = "contact-relative depth" if recipe.metadata.get("coordinate_mode") else "absolute displacement"
        contact_check = "contact check on" if recipe.metadata.get("enable_contact_detection") else "contact check off"
        measure_window = (
            f"{self.duration_spin.value():g} s"
            if self._measurement_mode_is_duration()
            else f"{self.frame_count_spin.value()} frames"
        )
        self.summary_label.setText(
            f"Preview: {len(recipe.steps)} moves, {measured_count} measurements, "
            f"{measure_window} each, {contact_start}, {contact_check}."
        )

    def _connect_summary_updates(self) -> None:
        for widget in (
            self.protocol_combo,
            self.start_spin,
            self.stop_spin,
            self.step_spin,
            self.settle_spin,
            self.speed_spin,
            self.speed_a_spin,
            self.speed_b_spin,
            self.speed_c_spin,
            self.cycle_count_spin,
            self.checkpoint_spin,
            self.frame_count_spin,
            self.duration_spin,
            self.disengage_checkbox,
            self.post_wait_spin,
            self.ready_timeout_spin,
            self.notes_prefix_edit,
            self.contact_direction_combo,
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
            value_changed = getattr(widget, "valueChanged", None)
            if value_changed is not None:
                value_changed.connect(self._refresh_summary)
            text_changed = getattr(widget, "textChanged", None)
            if text_changed is not None:
                text_changed.connect(self._refresh_summary)
            current_text_changed = getattr(widget, "currentTextChanged", None)
            if current_text_changed is not None:
                current_text_changed.connect(self._refresh_summary)
            toggled = getattr(widget, "toggled", None)
            if toggled is not None:
                toggled.connect(self._refresh_summary)

    def _add_help_row(self, form: QFormLayout, label: str, item: QWidget | QHBoxLayout) -> None:
        help_text = FIELD_HELP.get(label, "")
        if isinstance(item, QWidget):
            item.setToolTip(help_text)
        elif isinstance(item, QHBoxLayout):
            for index in range(item.count()):
                child = item.itemAt(index).widget()
                if child is not None:
                    child.setToolTip(help_text)
        label_widget = QLabel(self._format_help_label(label, help_text))
        label_widget.setWordWrap(True)
        label_widget.setToolTip(help_text)
        self._help_labels[item] = label_widget
        form.addRow(label_widget, item)

    def _set_dynamic_help(self, item: QWidget | QHBoxLayout, label: str, help_text: str) -> None:
        label_widget = self._help_labels.get(item)
        if label_widget is not None:
            label_widget.setText(self._format_help_label(label, help_text))
            label_widget.setToolTip(help_text)
        if isinstance(item, QWidget):
            item.setToolTip(help_text)
        elif isinstance(item, QHBoxLayout):
            for index in range(item.count()):
                child = item.itemAt(index).widget()
                if child is not None:
                    child.setToolTip(help_text)

    def _format_help_label(self, label: str, help_text: str) -> str:
        if not help_text:
            return escape(label)
        return (
            f"<span style='font-weight:600;'>{escape(label)}</span><br>"
            f"<span style='color:#667085; font-size:10px;'>{escape(help_text)}</span>"
        )

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
