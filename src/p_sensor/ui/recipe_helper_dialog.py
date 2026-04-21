from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from p_sensor.automation.builder import DisplacementSweepRecipeSpec, build_displacement_sweep_recipe
from p_sensor.automation.models import AutomationRecipe


@dataclass(slots=True)
class RecipeHelperResult:
    recipe: AutomationRecipe
    suggested_file_name: str


class RecipeHelperDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Recipe Helper")
        self.resize(420, 360)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)

        self.recipe_id_edit = QLineEdit("displacement_sweep")
        self.recipe_id_edit.setPlaceholderText("Recipe id")
        self.start_spin = self._new_double_spin(0.0)
        self.stop_spin = self._new_double_spin(1.0)
        self.step_spin = self._new_double_spin(0.1, minimum=0.000001)
        self.settle_spin = self._new_double_spin(0.2, minimum=0.0, maximum=3600.0, decimals=3, single_step=0.1)
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

        mode_row = QHBoxLayout()
        mode_row.addWidget(self.measure_mode_combo)
        mode_row.addWidget(self.frame_count_spin)
        mode_row.addWidget(self.duration_spin)

        form.addRow("Recipe ID", self.recipe_id_edit)
        form.addRow("Start mm", self.start_spin)
        form.addRow("Stop mm", self.stop_spin)
        form.addRow("Step mm", self.step_spin)
        form.addRow("Settle s", self.settle_spin)
        form.addRow("Measure", mode_row)
        form.addRow("Disengage", self.disengage_checkbox)
        form.addRow("Post Wait s", self.post_wait_spin)
        form.addRow("Ready Timeout s", self.ready_timeout_spin)
        form.addRow("Notes Prefix", self.notes_prefix_edit)
        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def build_result(self) -> RecipeHelperResult:
        spec = DisplacementSweepRecipeSpec(
            recipe_id=self.recipe_id_edit.text().strip(),
            start_displacement=self.start_spin.value(),
            stop_displacement=self.stop_spin.value(),
            step_size=self.step_spin.value(),
            settle_time_s=self.settle_spin.value(),
            measure_duration_s=self.duration_spin.value() if self._measurement_mode_is_duration() else None,
            measure_frame_count=self.frame_count_spin.value() if not self._measurement_mode_is_duration() else None,
            disengage_after_measure=self.disengage_checkbox.isChecked(),
            post_disengage_wait_s=self.post_wait_spin.value(),
            ready_timeout_s=self.ready_timeout_spin.value(),
            notes_prefix=self.notes_prefix_edit.text().strip(),
            metadata={"helper": "recipe_helper_dialog"},
        )
        recipe = build_displacement_sweep_recipe(spec)
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
