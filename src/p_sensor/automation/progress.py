from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from p_sensor.automation.models import AutomationRecipe, AutomationStep


PHASE_ORDER = ("move", "settle", "measure", "disengage", "post_disengage_wait")


@dataclass(slots=True)
class PhaseDurationEstimate:
    phase: str
    duration_s: float | None
    reason: str = ""

    @property
    def available(self) -> bool:
        return self.duration_s is not None


@dataclass(slots=True)
class StepDurationEstimate:
    step_index: int
    step_id: str
    phase_durations: list[PhaseDurationEstimate]

    @property
    def available(self) -> bool:
        return all(phase.available for phase in self.phase_durations)

    @property
    def duration_s(self) -> float | None:
        if not self.available:
            return None
        return sum(phase.duration_s or 0.0 for phase in self.phase_durations)

    @property
    def unavailable_reasons(self) -> list[str]:
        return [phase.reason for phase in self.phase_durations if not phase.available and phase.reason]


@dataclass(slots=True)
class RecipeDurationEstimate:
    step_estimates: list[StepDurationEstimate]

    @property
    def available(self) -> bool:
        return all(step.available for step in self.step_estimates)

    @property
    def total_duration_s(self) -> float | None:
        if not self.available:
            return None
        return sum(step.duration_s or 0.0 for step in self.step_estimates)

    @property
    def unavailable_reasons(self) -> list[str]:
        reasons: list[str] = []
        for step in self.step_estimates:
            reasons.extend(step.unavailable_reasons)
        return reasons


@dataclass(slots=True)
class ProgressSnapshot:
    status: str
    total_steps: int
    completed_steps: int
    current_step_index: int | None
    current_phase: str
    fraction_complete: float | None
    elapsed_s: float
    estimated_total_s: float | None
    estimated_remaining_s: float | None
    estimated_end_time: datetime | None
    estimate_available: bool
    unavailable_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProgressEstimatorConfig:
    acquisition_hz: float | None = None
    default_move_duration_s: float | None = None
    default_disengage_duration_s: float | None = None

    def __post_init__(self) -> None:
        if self.acquisition_hz is not None and self.acquisition_hz <= 0:
            raise ValueError("acquisition_hz must be greater than 0 when provided.")
        if self.default_move_duration_s is not None and self.default_move_duration_s < 0:
            raise ValueError("default_move_duration_s must be 0 or higher when provided.")
        if self.default_disengage_duration_s is not None and self.default_disengage_duration_s < 0:
            raise ValueError("default_disengage_duration_s must be 0 or higher when provided.")


def estimate_recipe_duration(
    recipe: AutomationRecipe,
    config: ProgressEstimatorConfig | None = None,
) -> RecipeDurationEstimate:
    estimator_config = config or ProgressEstimatorConfig()
    estimates: list[StepDurationEstimate] = []
    previous_position: float | None = None
    for index, step in enumerate(recipe.steps, start=1):
        estimates.append(
            estimate_step_duration(
                step,
                step_index=index,
                previous_position_mm=previous_position,
                config=estimator_config,
            )
        )
        if step.target_displacement is not None:
            previous_position = step.target_displacement
    return RecipeDurationEstimate(step_estimates=estimates)


def estimate_step_duration(
    step: AutomationStep,
    *,
    step_index: int,
    previous_position_mm: float | None,
    config: ProgressEstimatorConfig,
) -> StepDurationEstimate:
    return StepDurationEstimate(
        step_index=step_index,
        step_id=step.step_id,
        phase_durations=[
            _estimate_move_duration(step, previous_position_mm, config),
            PhaseDurationEstimate("settle", step.settle_time_s),
            _estimate_measure_duration(step, config),
            _estimate_disengage_duration(step, config),
            PhaseDurationEstimate("post_disengage_wait", step.post_disengage_wait_s),
        ],
    )


class AutomationProgressEstimator:
    def __init__(
        self,
        recipe: AutomationRecipe,
        config: ProgressEstimatorConfig | None = None,
    ) -> None:
        self.recipe = recipe
        self.config = config or ProgressEstimatorConfig()
        self.estimate = estimate_recipe_duration(recipe, self.config)

    def snapshot(
        self,
        *,
        started_at: datetime,
        now: datetime,
        completed_steps: int,
        current_step_index: int | None = None,
        current_phase: str = "",
        current_phase_elapsed_s: float = 0.0,
        status: str = "running",
    ) -> ProgressSnapshot:
        elapsed_s = max(0.0, (now - started_at).total_seconds())
        total_steps = len(self.recipe.steps)
        completed_steps = min(max(completed_steps, 0), total_steps)
        if not self.estimate.available:
            return ProgressSnapshot(
                status=status,
                total_steps=total_steps,
                completed_steps=completed_steps,
                current_step_index=current_step_index,
                current_phase=current_phase,
                fraction_complete=None,
                elapsed_s=elapsed_s,
                estimated_total_s=None,
                estimated_remaining_s=None,
                estimated_end_time=None,
                estimate_available=False,
                unavailable_reasons=self.estimate.unavailable_reasons,
            )

        total_duration_s = self.estimate.total_duration_s or 0.0
        completed_duration_s = self._completed_duration_s(completed_steps)
        completed_duration_s += self._current_step_phase_elapsed_s(
            completed_steps=completed_steps,
            current_step_index=current_step_index,
            current_phase=current_phase,
            current_phase_elapsed_s=current_phase_elapsed_s,
        )
        fraction_complete = 1.0 if total_duration_s <= 0 else completed_duration_s / total_duration_s
        fraction_complete = min(1.0, max(0.0, fraction_complete))
        remaining_s = max(0.0, total_duration_s - completed_duration_s)
        end_time = now + timedelta(seconds=remaining_s)
        return ProgressSnapshot(
            status=status,
            total_steps=total_steps,
            completed_steps=completed_steps,
            current_step_index=current_step_index,
            current_phase=current_phase,
            fraction_complete=fraction_complete,
            elapsed_s=elapsed_s,
            estimated_total_s=total_duration_s,
            estimated_remaining_s=remaining_s,
            estimated_end_time=end_time,
            estimate_available=True,
        )

    def _completed_duration_s(self, completed_steps: int) -> float:
        return sum(
            estimate.duration_s or 0.0
            for estimate in self.estimate.step_estimates[:completed_steps]
        )

    def _current_step_phase_elapsed_s(
        self,
        *,
        completed_steps: int,
        current_step_index: int | None,
        current_phase: str,
        current_phase_elapsed_s: float,
    ) -> float:
        if current_step_index is None or current_step_index <= completed_steps:
            return 0.0
        if not current_phase:
            return 0.0
        step_offset = current_step_index - 1
        if step_offset < 0 or step_offset >= len(self.estimate.step_estimates):
            return 0.0
        step_estimate = self.estimate.step_estimates[step_offset]
        duration_s = 0.0
        for phase in step_estimate.phase_durations:
            if phase.phase == current_phase:
                phase_duration_s = phase.duration_s or 0.0
                duration_s += min(max(current_phase_elapsed_s, 0.0), phase_duration_s)
                return duration_s
            duration_s += phase.duration_s or 0.0
        return 0.0


def _estimate_move_duration(
    step: AutomationStep,
    previous_position_mm: float | None,
    config: ProgressEstimatorConfig,
) -> PhaseDurationEstimate:
    if step.target_displacement is None:
        return PhaseDurationEstimate("move", 0.0)
    if config.default_move_duration_s is not None:
        return PhaseDurationEstimate("move", config.default_move_duration_s)
    if previous_position_mm is None:
        return PhaseDurationEstimate(
            "move",
            None,
            f"Step {step.step_id!r} requires a move estimate but has no previous position.",
        )
    if step.velocity_mm_min is None:
        return PhaseDurationEstimate(
            "move",
            None,
            f"Step {step.step_id!r} requires velocity_mm_min for move time estimation.",
        )
    distance_mm = abs(step.target_displacement - previous_position_mm)
    return PhaseDurationEstimate("move", distance_mm / (step.velocity_mm_min / 60.0))


def _estimate_measure_duration(
    step: AutomationStep,
    config: ProgressEstimatorConfig,
) -> PhaseDurationEstimate:
    if not step.measure_enabled:
        return PhaseDurationEstimate("measure", 0.0)
    if step.measure_duration_s is not None:
        return PhaseDurationEstimate("measure", step.measure_duration_s)
    if step.measure_frame_count is not None and config.acquisition_hz is not None:
        return PhaseDurationEstimate("measure", step.measure_frame_count / config.acquisition_hz)
    return PhaseDurationEstimate(
        "measure",
        None,
        f"Step {step.step_id!r} requires acquisition_hz to estimate frame-count measurement.",
    )


def _estimate_disengage_duration(
    step: AutomationStep,
    config: ProgressEstimatorConfig,
) -> PhaseDurationEstimate:
    if not step.disengage_after_measure:
        return PhaseDurationEstimate("disengage", 0.0)
    if config.default_disengage_duration_s is not None:
        return PhaseDurationEstimate("disengage", config.default_disengage_duration_s)
    return PhaseDurationEstimate(
        "disengage",
        None,
        f"Step {step.step_id!r} requires default_disengage_duration_s for disengage estimation.",
    )
