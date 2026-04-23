from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from p_sensor.automation.models import AutomationRecipe, AutomationStep


PROTOCOL_STEP_HOLD = "step_hold"
PROTOCOL_HYSTERESIS = "hysteresis"
PROTOCOL_SPEED_DEPENDENCY = "speed_dependency"
PROTOCOL_FATIGUE = "fatigue"
SUPPORTED_PROTOCOLS = {
    PROTOCOL_STEP_HOLD,
    PROTOCOL_HYSTERESIS,
    PROTOCOL_SPEED_DEPENDENCY,
    PROTOCOL_FATIGUE,
}


@dataclass(slots=True)
class ProtocolRecipeSpec:
    recipe_id: str
    protocol_type: str
    max_displacement_mm: float
    min_displacement_mm: float = 0.0
    step_increment_mm: float | None = None
    hold_time_s: float = 0.0
    measure_duration_s: float | None = None
    measure_frame_count: int | None = None
    velocity_mm_min: float | None = None
    velocities_mm_min: list[float] = field(default_factory=list)
    return_velocity_mm_min: float | None = None
    cycle_count: int = 1
    checkpoint_interval_cycles: int = 10
    ready_timeout_s: float | None = 10.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.recipe_id.strip():
            raise ValueError("recipe_id must not be empty.")
        if self.protocol_type not in SUPPORTED_PROTOCOLS:
            raise ValueError(f"Unsupported protocol_type: {self.protocol_type!r}")
        if self.max_displacement_mm <= self.min_displacement_mm:
            raise ValueError("max_displacement_mm must be greater than min_displacement_mm.")
        if self.step_increment_mm is not None and self.step_increment_mm <= 0:
            raise ValueError("step_increment_mm must be greater than 0 when provided.")
        if self.hold_time_s < 0:
            raise ValueError("hold_time_s must be 0 or higher.")
        if self.measure_duration_s is None and self.measure_frame_count is None:
            raise ValueError("measure_duration_s or measure_frame_count is required.")
        if self.measure_duration_s is not None and self.measure_duration_s <= 0:
            raise ValueError("measure_duration_s must be greater than 0.")
        if self.measure_frame_count is not None and self.measure_frame_count <= 0:
            raise ValueError("measure_frame_count must be greater than 0.")
        if self.velocity_mm_min is not None and self.velocity_mm_min <= 0:
            raise ValueError("velocity_mm_min must be greater than 0 when provided.")
        if any(speed <= 0 for speed in self.velocities_mm_min):
            raise ValueError("All velocities_mm_min values must be greater than 0.")
        if self.return_velocity_mm_min is not None and self.return_velocity_mm_min <= 0:
            raise ValueError("return_velocity_mm_min must be greater than 0 when provided.")
        if self.cycle_count <= 0:
            raise ValueError("cycle_count must be greater than 0.")
        if self.checkpoint_interval_cycles <= 0:
            raise ValueError("checkpoint_interval_cycles must be greater than 0.")
        if self.ready_timeout_s is not None and self.ready_timeout_s <= 0:
            raise ValueError("ready_timeout_s must be greater than 0 when provided.")
        if self.protocol_type in {PROTOCOL_STEP_HOLD, PROTOCOL_HYSTERESIS, PROTOCOL_SPEED_DEPENDENCY}:
            if self.step_increment_mm is None:
                raise ValueError("step_increment_mm is required for sweep protocols.")
            _positions(self.min_displacement_mm, self.max_displacement_mm, self.step_increment_mm)
        if self.protocol_type == PROTOCOL_SPEED_DEPENDENCY and not self.velocities_mm_min:
            raise ValueError("velocities_mm_min is required for speed_dependency.")


def protocol_spec_from_dict(data: dict[str, Any]) -> ProtocolRecipeSpec:
    return ProtocolRecipeSpec(
        recipe_id=str(data.get("recipe_id", "")).strip(),
        protocol_type=str(data.get("protocol_type", "")).strip(),
        min_displacement_mm=float(data.get("min_displacement_mm", 0.0)),
        max_displacement_mm=float(data.get("max_displacement_mm")),
        step_increment_mm=(
            None if data.get("step_increment_mm") is None else float(data.get("step_increment_mm"))
        ),
        hold_time_s=float(data.get("hold_time_s", data.get("settle_time_s", 0.0))),
        measure_duration_s=(
            None if data.get("measure_duration_s") is None else float(data.get("measure_duration_s"))
        ),
        measure_frame_count=(
            None if data.get("measure_frame_count") is None else int(data.get("measure_frame_count"))
        ),
        velocity_mm_min=(
            None if data.get("velocity_mm_min") is None else float(data.get("velocity_mm_min"))
        ),
        velocities_mm_min=[float(speed) for speed in data.get("velocities_mm_min", [])],
        return_velocity_mm_min=(
            None if data.get("return_velocity_mm_min") is None else float(data.get("return_velocity_mm_min"))
        ),
        cycle_count=int(data.get("cycle_count", 1)),
        checkpoint_interval_cycles=int(data.get("checkpoint_interval_cycles", 10)),
        ready_timeout_s=(None if data.get("ready_timeout_s") is None else float(data.get("ready_timeout_s"))),
        metadata=dict(data.get("metadata", {})),
    )


def compile_protocol_recipe(data: dict[str, Any] | ProtocolRecipeSpec) -> AutomationRecipe:
    spec = data if isinstance(data, ProtocolRecipeSpec) else protocol_spec_from_dict(data)
    if spec.protocol_type == PROTOCOL_STEP_HOLD:
        steps = _build_step_hold_steps(spec)
    elif spec.protocol_type == PROTOCOL_HYSTERESIS:
        steps = _build_hysteresis_steps(spec)
    elif spec.protocol_type == PROTOCOL_SPEED_DEPENDENCY:
        steps = _build_speed_dependency_steps(spec)
    elif spec.protocol_type == PROTOCOL_FATIGUE:
        steps = _build_fatigue_steps(spec)
    else:
        raise ValueError(f"Unsupported protocol_type: {spec.protocol_type!r}")

    metadata = dict(spec.metadata)
    metadata.update(
        {
            "protocol_type": spec.protocol_type,
            "min_displacement_mm": spec.min_displacement_mm,
            "max_displacement_mm": spec.max_displacement_mm,
            "step_increment_mm": spec.step_increment_mm,
            "cycle_count": spec.cycle_count,
        }
    )
    return AutomationRecipe(recipe_id=spec.recipe_id, steps=steps, metadata=metadata)


def _build_step_hold_steps(spec: ProtocolRecipeSpec) -> list[AutomationStep]:
    steps = []
    for index, displacement in enumerate(_positions_for_spec(spec), start=1):
        steps.append(_measured_step(spec, index, displacement, cycle_index=1, phase="loading"))
    steps.append(_return_step(spec, len(steps) + 1, cycle_index=1, phase="return"))
    return steps


def _build_hysteresis_steps(spec: ProtocolRecipeSpec) -> list[AutomationStep]:
    steps: list[AutomationStep] = []
    loading_positions = _positions_for_spec(spec)
    unloading_positions = list(reversed(loading_positions[:-1]))
    for cycle_index in range(1, spec.cycle_count + 1):
        for displacement in loading_positions:
            steps.append(
                _measured_step(
                    spec,
                    len(steps) + 1,
                    displacement,
                    cycle_index=cycle_index,
                    phase="loading",
                )
            )
        for displacement in unloading_positions:
            steps.append(
                _measured_step(
                    spec,
                    len(steps) + 1,
                    displacement,
                    cycle_index=cycle_index,
                    phase="unloading",
                )
            )
    return steps


def _build_speed_dependency_steps(spec: ProtocolRecipeSpec) -> list[AutomationStep]:
    steps: list[AutomationStep] = []
    for speed_index, velocity_mm_min in enumerate(spec.velocities_mm_min, start=1):
        for displacement in _positions_for_spec(spec):
            steps.append(
                _measured_step(
                    spec,
                    len(steps) + 1,
                    displacement,
                    cycle_index=speed_index,
                    phase="loading",
                    velocity_mm_min=velocity_mm_min,
                )
            )
        steps.append(
            _return_step(
                spec,
                len(steps) + 1,
                cycle_index=speed_index,
                phase="return",
                velocity_mm_min=spec.return_velocity_mm_min or velocity_mm_min,
            )
        )
    return steps


def _build_fatigue_steps(spec: ProtocolRecipeSpec) -> list[AutomationStep]:
    steps: list[AutomationStep] = []
    for cycle_index in range(1, spec.cycle_count + 1):
        is_checkpoint = (
            cycle_index == 1
            or cycle_index == spec.cycle_count
            or cycle_index % spec.checkpoint_interval_cycles == 0
        )
        steps.append(
            _protocol_step(
                spec,
                len(steps) + 1,
                spec.max_displacement_mm,
                cycle_index=cycle_index,
                phase="fatigue_loading",
                velocity_mm_min=spec.velocity_mm_min,
                measure_enabled=is_checkpoint,
                notes="fatigue checkpoint at max displacement" if is_checkpoint else "fatigue max displacement",
            )
        )
        steps.append(
            _protocol_step(
                spec,
                len(steps) + 1,
                spec.min_displacement_mm,
                cycle_index=cycle_index,
                phase="fatigue_unloading",
                velocity_mm_min=spec.return_velocity_mm_min or spec.velocity_mm_min,
                measure_enabled=False,
                notes="fatigue return to minimum displacement",
            )
        )
    return steps


def _measured_step(
    spec: ProtocolRecipeSpec,
    step_index: int,
    displacement: float,
    *,
    cycle_index: int,
    phase: str,
    velocity_mm_min: float | None = None,
) -> AutomationStep:
    return _protocol_step(
        spec,
        step_index,
        displacement,
        cycle_index=cycle_index,
        phase=phase,
        velocity_mm_min=velocity_mm_min or spec.velocity_mm_min,
        measure_enabled=True,
        notes=f"{phase} {displacement:.6f} mm",
    )


def _return_step(
    spec: ProtocolRecipeSpec,
    step_index: int,
    *,
    cycle_index: int,
    phase: str,
    velocity_mm_min: float | None = None,
) -> AutomationStep:
    return _protocol_step(
        spec,
        step_index,
        spec.min_displacement_mm,
        cycle_index=cycle_index,
        phase=phase,
        velocity_mm_min=velocity_mm_min or spec.return_velocity_mm_min or spec.velocity_mm_min,
        measure_enabled=False,
        notes=f"{phase} to {spec.min_displacement_mm:.6f} mm",
    )


def _protocol_step(
    spec: ProtocolRecipeSpec,
    step_index: int,
    displacement: float,
    *,
    cycle_index: int,
    phase: str,
    velocity_mm_min: float | None,
    measure_enabled: bool,
    notes: str,
) -> AutomationStep:
    return AutomationStep(
        step_id=f"{phase}_{step_index:05d}",
        target_displacement=displacement,
        cycle_index=cycle_index,
        phase=phase,
        velocity_mm_min=velocity_mm_min,
        measure_enabled=measure_enabled,
        settle_time_s=spec.hold_time_s if measure_enabled else 0.0,
        measure_duration_s=spec.measure_duration_s if measure_enabled else None,
        measure_frame_count=spec.measure_frame_count if measure_enabled else None,
        disengage_after_measure=False,
        post_disengage_wait_s=0.0,
        ready_timeout_s=spec.ready_timeout_s,
        notes=notes,
    )


def _positions_for_spec(spec: ProtocolRecipeSpec) -> list[float]:
    if spec.step_increment_mm is None:
        raise ValueError("step_increment_mm is required.")
    return _positions(spec.min_displacement_mm, spec.max_displacement_mm, spec.step_increment_mm)


def _positions(start: float, stop: float, increment: float) -> list[float]:
    positions = list(_generate_positions(start, stop, increment))
    if not positions:
        raise ValueError("Protocol must generate at least one position.")
    return positions


def _generate_positions(start: float, stop: float, increment: float) -> Iterable[float]:
    distance = stop - start
    interval_count = distance / increment
    rounded_interval_count = round(interval_count)
    if abs(interval_count - rounded_interval_count) > 1e-9:
        raise ValueError("max_displacement_mm must align with min_displacement_mm and step_increment_mm.")
    for index in range(int(rounded_interval_count) + 1):
        yield round(start + (increment * index), 9)
