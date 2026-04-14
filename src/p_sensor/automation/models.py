from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class AutomationStep:
    step_id: str
    target_displacement: float | None = None
    settle_time_s: float = 0.0
    measure_duration_s: float | None = None
    measure_frame_count: int | None = None
    disengage_after_measure: bool = True
    post_disengage_wait_s: float = 0.0
    ready_timeout_s: float | None = 10.0
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.step_id.strip():
            raise ValueError("Automation step_id must not be empty.")
        if self.settle_time_s < 0:
            raise ValueError("settle_time_s must be 0 or higher.")
        if self.measure_duration_s is None and self.measure_frame_count is None:
            raise ValueError("Each step must define measure_duration_s or measure_frame_count.")
        if self.measure_duration_s is not None and self.measure_duration_s <= 0:
            raise ValueError("measure_duration_s must be greater than 0.")
        if self.measure_frame_count is not None and self.measure_frame_count <= 0:
            raise ValueError("measure_frame_count must be greater than 0.")
        if self.post_disengage_wait_s < 0:
            raise ValueError("post_disengage_wait_s must be 0 or higher.")
        if self.ready_timeout_s is not None and self.ready_timeout_s <= 0:
            raise ValueError("ready_timeout_s must be greater than 0 when provided.")


@dataclass(slots=True)
class AutomationRecipe:
    recipe_id: str
    steps: list[AutomationStep]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.recipe_id.strip():
            raise ValueError("recipe_id must not be empty.")
        if not self.steps:
            raise ValueError("Automation recipe must contain at least one step.")


@dataclass(slots=True)
class AutomationSessionOptions:
    export_directory: str | Path
    session_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AutomationStepResult:
    step_index: int
    step_id: str
    target_displacement: float | None
    measurement_file: str
    started_at: datetime
    ended_at: datetime
    frame_count: int
    average_inputs: dict[str, dict[str, float | str]]
    average_outputs: dict[str, float]
    status: str = "completed"
    notes: str = ""


@dataclass(slots=True)
class AutomationSessionResult:
    session_id: str
    session_dir: Path
    manifest_path: Path
    summary_path: Path
    step_results: list[AutomationStepResult]
