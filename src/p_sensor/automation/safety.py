from __future__ import annotations

from dataclasses import dataclass

from p_sensor.automation.models import AutomationRecipe, AutomationStep


class AutomationSafetyError(RuntimeError):
    pass


@dataclass(slots=True)
class AutomationSafetyPolicy:
    min_position_mm: float | None = None
    max_position_mm: float | None = None
    require_target_displacement: bool = False

    def __post_init__(self) -> None:
        if (
            self.min_position_mm is not None
            and self.max_position_mm is not None
            and self.min_position_mm >= self.max_position_mm
        ):
            raise ValueError("min_position_mm must be less than max_position_mm.")

    def validate_recipe(self, recipe: AutomationRecipe) -> None:
        for step in recipe.steps:
            self.validate_step(step)

    def validate_step(self, step: AutomationStep) -> None:
        if step.target_displacement is None:
            if self.require_target_displacement:
                raise AutomationSafetyError(
                    f"Automation step {step.step_id!r} does not define target_displacement."
                )
            return
        self.validate_position_mm(
            step.target_displacement,
            label=f"target_displacement for step {step.step_id!r}",
        )

    def validate_position_mm(self, position_mm: float | None, *, label: str) -> None:
        if position_mm is None:
            return
        if self.min_position_mm is not None and position_mm < self.min_position_mm:
            raise AutomationSafetyError(
                f"{label} {position_mm:.6g} mm is below configured minimum "
                f"{self.min_position_mm:.6g} mm."
            )
        if self.max_position_mm is not None and position_mm > self.max_position_mm:
            raise AutomationSafetyError(
                f"{label} {position_mm:.6g} mm is above configured maximum "
                f"{self.max_position_mm:.6g} mm."
            )
