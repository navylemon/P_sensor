from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from p_sensor.automation.models import AutomationRecipe, AutomationStep
from p_sensor.config import resolve_runtime_path


@dataclass(slots=True)
class DisplacementSweepRecipeSpec:
    recipe_id: str
    start_displacement: float
    stop_displacement: float
    step_size: float
    settle_time_s: float = 0.0
    measure_duration_s: float | None = None
    measure_frame_count: int | None = None
    disengage_after_measure: bool = True
    post_disengage_wait_s: float = 0.0
    ready_timeout_s: float | None = 10.0
    notes_prefix: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.recipe_id.strip():
            raise ValueError("recipe_id must not be empty.")
        if self.step_size <= 0:
            raise ValueError("step_size must be greater than 0.")
        if self.settle_time_s < 0:
            raise ValueError("settle_time_s must be 0 or higher.")
        if self.measure_duration_s is None and self.measure_frame_count is None:
            raise ValueError("measure_duration_s or measure_frame_count is required.")
        if self.measure_duration_s is not None and self.measure_duration_s <= 0:
            raise ValueError("measure_duration_s must be greater than 0.")
        if self.measure_frame_count is not None and self.measure_frame_count <= 0:
            raise ValueError("measure_frame_count must be greater than 0.")
        if self.post_disengage_wait_s < 0:
            raise ValueError("post_disengage_wait_s must be 0 or higher.")
        if self.ready_timeout_s is not None and self.ready_timeout_s <= 0:
            raise ValueError("ready_timeout_s must be greater than 0 when provided.")


def build_displacement_sweep_recipe(spec: DisplacementSweepRecipeSpec) -> AutomationRecipe:
    positions = list(_generate_positions(spec.start_displacement, spec.stop_displacement, spec.step_size))
    steps = [
        AutomationStep(
            step_id=f"step_{index + 1:03d}",
            target_displacement=position,
            settle_time_s=spec.settle_time_s,
            measure_duration_s=spec.measure_duration_s,
            measure_frame_count=spec.measure_frame_count,
            disengage_after_measure=spec.disengage_after_measure,
            post_disengage_wait_s=spec.post_disengage_wait_s,
            ready_timeout_s=spec.ready_timeout_s,
            notes=_build_step_note(spec.notes_prefix, position, index),
        )
        for index, position in enumerate(positions)
    ]
    return AutomationRecipe(recipe_id=spec.recipe_id.strip(), steps=steps, metadata=dict(spec.metadata))


def recipe_to_dict(recipe: AutomationRecipe) -> dict[str, Any]:
    return {
        "recipe_id": recipe.recipe_id,
        "metadata": dict(recipe.metadata),
        "steps": [asdict(step) for step in recipe.steps],
    }


def save_recipe(path: str | Path, recipe: AutomationRecipe) -> Path:
    recipe_path = resolve_runtime_path(path)
    recipe_path.parent.mkdir(parents=True, exist_ok=True)
    recipe_path.write_text(json.dumps(recipe_to_dict(recipe), indent=2, ensure_ascii=False), encoding="utf-8")
    return recipe_path


def _generate_positions(start: float, stop: float, step_size: float):
    if start == stop:
        yield round(start, 9)
        return

    distance = stop - start
    direction = 1.0 if distance > 0 else -1.0
    step = direction * step_size
    interval_count = abs(distance) / step_size
    rounded_interval_count = round(interval_count)
    if abs(interval_count - rounded_interval_count) > 1e-9:
        raise ValueError("stop_displacement must align with start_displacement and step_size.")

    for index in range(int(rounded_interval_count) + 1):
        yield round(start + (step * index), 9)


def _build_step_note(notes_prefix: str, position: float, index: int) -> str:
    displacement_note = f"{position:.6f} mm"
    prefix = notes_prefix.strip()
    if not prefix:
        return displacement_note
    return f"{prefix} {index + 1}: {displacement_note}"
