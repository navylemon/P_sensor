from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from p_sensor.automation.models import AutomationRecipe, AutomationStep
from p_sensor.automation.protocols import compile_protocol_recipe
from p_sensor.config import resolve_runtime_path


def recipe_from_dict(data: dict[str, Any]) -> AutomationRecipe:
    if "protocol_type" in data:
        return compile_protocol_recipe(data)
    recipe_id = str(data.get("recipe_id", "")).strip()
    metadata = dict(data.get("metadata", {}))
    steps_data = list(data.get("steps", []))
    steps = [
        AutomationStep(
            step_id=str(item.get("step_id", f"step_{index + 1:03d}")),
            target_displacement=(
                None if item.get("target_displacement") is None else float(item.get("target_displacement"))
            ),
            cycle_index=(None if item.get("cycle_index") is None else int(item.get("cycle_index"))),
            phase=str(item.get("phase", "")),
            velocity_mm_min=(
                None if item.get("velocity_mm_min") is None else float(item.get("velocity_mm_min"))
            ),
            measure_enabled=bool(item.get("measure_enabled", True)),
            settle_time_s=float(item.get("settle_time_s", 0.0)),
            measure_duration_s=(
                None if item.get("measure_duration_s") is None else float(item.get("measure_duration_s"))
            ),
            measure_frame_count=(
                None if item.get("measure_frame_count") is None else int(item.get("measure_frame_count"))
            ),
            disengage_after_measure=bool(item.get("disengage_after_measure", True)),
            post_disengage_wait_s=float(item.get("post_disengage_wait_s", 0.0)),
            ready_timeout_s=(
                None if item.get("ready_timeout_s") is None else float(item.get("ready_timeout_s"))
            ),
            notes=str(item.get("notes", "")),
        )
        for index, item in enumerate(steps_data)
    ]
    return AutomationRecipe(recipe_id=recipe_id, steps=steps, metadata=metadata)


def load_recipe(path: str | Path) -> AutomationRecipe:
    recipe_path = resolve_runtime_path(path)
    payload = json.loads(recipe_path.read_text(encoding="utf-8"))
    return recipe_from_dict(payload)
