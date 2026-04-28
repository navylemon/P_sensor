from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from threading import Event
from typing import Protocol


class ContactDetectionCancelledError(RuntimeError):
    pass


class ContactDetectionError(RuntimeError):
    pass


class ContactMotionController(Protocol):
    def set_velocity_mm_min(self, velocity_mm_min: float) -> None: ...

    def move_relative_mm(self, *, axis: int, delta_mm: float) -> None: ...

    def wait_until_ready(self, timeout_s: float | None = None) -> None: ...

    def get_position_mm(self) -> float | None: ...

    def abort(self) -> None: ...


class ResistanceSampler(Protocol):
    def read_resistance_ohm(self) -> float: ...


@dataclass(slots=True)
class ContactDetectionConfig:
    stage_axis: int = 1
    scan_speed_mm_s: float = 0.02
    scan_step_mm: float = 0.01
    max_travel_mm: float = 1.0
    delta_resistance_threshold_ohm: float = 1.0
    baseline_duration_s: float = 0.2
    stable_duration_s: float = 0.05
    sample_interval_s: float = 0.01
    ready_timeout_s: float | None = 10.0
    descent_direction: int = -1
    change_mode: str = "absolute"
    use_as_zero: bool = True

    def __post_init__(self) -> None:
        if self.stage_axis <= 0:
            raise ValueError("stage_axis must be greater than 0.")
        if self.scan_speed_mm_s <= 0:
            raise ValueError("scan_speed_mm_s must be greater than 0.")
        if self.scan_step_mm <= 0:
            raise ValueError("scan_step_mm must be greater than 0.")
        if self.max_travel_mm <= 0:
            raise ValueError("max_travel_mm must be greater than 0.")
        if self.delta_resistance_threshold_ohm <= 0:
            raise ValueError("delta_resistance_threshold_ohm must be greater than 0.")
        if self.baseline_duration_s < 0:
            raise ValueError("baseline_duration_s must be 0 or higher.")
        if self.stable_duration_s < 0:
            raise ValueError("stable_duration_s must be 0 or higher.")
        if self.sample_interval_s <= 0:
            raise ValueError("sample_interval_s must be greater than 0.")
        if self.ready_timeout_s is not None and self.ready_timeout_s <= 0:
            raise ValueError("ready_timeout_s must be greater than 0 when provided.")
        if self.descent_direction not in (-1, 1):
            raise ValueError("descent_direction must be -1 or 1.")
        if self.change_mode not in {"absolute", "increase", "decrease"}:
            raise ValueError("change_mode must be 'absolute', 'increase', or 'decrease'.")

    @property
    def scan_velocity_mm_min(self) -> float:
        return self.scan_speed_mm_s * 60.0

    @property
    def baseline_sample_count(self) -> int:
        return max(1, math.ceil(self.baseline_duration_s / self.sample_interval_s))

    @property
    def stable_sample_count(self) -> int:
        return max(1, math.ceil(self.stable_duration_s / self.sample_interval_s))


@dataclass(slots=True)
class ContactDetectionSample:
    elapsed_s: float
    position_mm: float | None
    resistance_ohm: float
    delta_resistance_ohm: float
    triggered: bool


@dataclass(slots=True)
class ContactDetectionResult:
    detected: bool
    baseline_resistance_ohm: float
    contact_position_mm: float | None
    contact_resistance_ohm: float | None
    delta_resistance_ohm: float | None
    traveled_mm: float
    elapsed_s: float
    reason: str
    use_as_zero: bool
    samples: list[ContactDetectionSample] = field(default_factory=list)


class ContactDetector:
    def __init__(
        self,
        motion: ContactMotionController,
        sampler: ResistanceSampler,
        *,
        sleep_fn=time.sleep,
        monotonic_fn=time.monotonic,
    ) -> None:
        self.motion = motion
        self.sampler = sampler
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn

    def detect(
        self,
        config: ContactDetectionConfig,
        *,
        stop_event: Event | None = None,
    ) -> ContactDetectionResult:
        started_at = self.monotonic_fn()
        self._ensure_not_cancelled(stop_event)
        baseline_values = self._collect_baseline(config, started_at, stop_event=stop_event)
        baseline = sum(baseline_values) / len(baseline_values)

        self._set_velocity_mm_min(config)
        stable_count = 0
        first_trigger_sample: ContactDetectionSample | None = None
        samples: list[ContactDetectionSample] = []
        traveled_mm = 0.0
        step_count = math.ceil(config.max_travel_mm / config.scan_step_mm)

        for step_index in range(step_count):
            self._ensure_not_cancelled(stop_event)
            remaining_mm = config.max_travel_mm - traveled_mm
            if remaining_mm <= 0:
                break
            step_mm = min(config.scan_step_mm, remaining_mm)
            delta_mm = config.descent_direction * step_mm
            self._move_relative_mm(axis=config.stage_axis, delta_mm=delta_mm)
            self.motion.wait_until_ready(config.ready_timeout_s)
            traveled_mm += step_mm

            resistance = self.sampler.read_resistance_ohm()
            delta_resistance = resistance - baseline
            triggered = self._is_triggered(config, delta_resistance)
            sample = ContactDetectionSample(
                elapsed_s=self.monotonic_fn() - started_at,
                position_mm=self._read_position_mm(config.stage_axis),
                resistance_ohm=resistance,
                delta_resistance_ohm=delta_resistance,
                triggered=triggered,
            )
            samples.append(sample)

            if triggered:
                stable_count += 1
                if first_trigger_sample is None:
                    first_trigger_sample = sample
                if stable_count >= config.stable_sample_count:
                    trigger = first_trigger_sample
                    return ContactDetectionResult(
                        detected=True,
                        baseline_resistance_ohm=baseline,
                        contact_position_mm=trigger.position_mm,
                        contact_resistance_ohm=trigger.resistance_ohm,
                        delta_resistance_ohm=trigger.delta_resistance_ohm,
                        traveled_mm=traveled_mm,
                        elapsed_s=self.monotonic_fn() - started_at,
                        reason="threshold_reached",
                        use_as_zero=config.use_as_zero,
                        samples=samples,
                    )
            else:
                stable_count = 0
                first_trigger_sample = None

            if step_index < step_count - 1:
                self.sleep_fn(config.sample_interval_s)

        return ContactDetectionResult(
            detected=False,
            baseline_resistance_ohm=baseline,
            contact_position_mm=None,
            contact_resistance_ohm=None,
            delta_resistance_ohm=None,
            traveled_mm=traveled_mm,
            elapsed_s=self.monotonic_fn() - started_at,
            reason="max_travel_reached",
            use_as_zero=config.use_as_zero,
            samples=samples,
        )

    def _collect_baseline(
        self,
        config: ContactDetectionConfig,
        started_at: float,
        *,
        stop_event: Event | None,
    ) -> list[float]:
        values: list[float] = []
        for index in range(config.baseline_sample_count):
            self._ensure_not_cancelled(stop_event)
            values.append(self.sampler.read_resistance_ohm())
            if index < config.baseline_sample_count - 1:
                self.sleep_fn(config.sample_interval_s)
        if not values:
            raise ContactDetectionError("Contact detection baseline did not produce samples.")
        return values

    def _read_position_mm(self, axis: int) -> float | None:
        get_position = getattr(self.motion, "get_position_mm", None)
        if callable(get_position):
            return get_position()
        get_axis_position = getattr(self.motion, "get_axis_position_mm", None)
        if callable(get_axis_position):
            return get_axis_position(axis)
        controller = getattr(self.motion, "controller", None)
        controller_get_axis_position = getattr(controller, "get_axis_position_mm", None)
        if callable(controller_get_axis_position):
            return controller_get_axis_position(axis)
        return None

    def _set_velocity_mm_min(self, config: ContactDetectionConfig) -> None:
        set_velocity = getattr(self.motion, "set_velocity_mm_min", None)
        if not callable(set_velocity):
            controller = getattr(self.motion, "controller", None)
            set_velocity = getattr(controller, "set_velocity_mm_min", None)
        if not callable(set_velocity):
            raise ContactDetectionError("Motion controller does not support velocity control.")
        try:
            set_velocity(config.scan_velocity_mm_min)
        except TypeError:
            set_velocity(axis=config.stage_axis, velocity_mm_min=config.scan_velocity_mm_min)

    def _move_relative_mm(self, *, axis: int, delta_mm: float) -> None:
        move_relative = getattr(self.motion, "move_relative_mm", None)
        if not callable(move_relative):
            controller = getattr(self.motion, "controller", None)
            move_relative = getattr(controller, "move_relative_mm", None)
        if not callable(move_relative):
            raise ContactDetectionError("Motion controller does not support relative mm moves.")
        move_relative(axis=axis, delta_mm=delta_mm)

    def _is_triggered(self, config: ContactDetectionConfig, delta_resistance: float) -> bool:
        if config.change_mode == "increase":
            return delta_resistance >= config.delta_resistance_threshold_ohm
        if config.change_mode == "decrease":
            return -delta_resistance >= config.delta_resistance_threshold_ohm
        return abs(delta_resistance) >= config.delta_resistance_threshold_ohm

    def _ensure_not_cancelled(self, stop_event: Event | None) -> None:
        if stop_event is not None and stop_event.is_set():
            try:
                abort = getattr(self.motion, "abort", None)
                if callable(abort):
                    abort()
                else:
                    emergency_stop = getattr(self.motion, "emergency_stop", None)
                    if callable(emergency_stop):
                        emergency_stop()
            finally:
                raise ContactDetectionCancelledError("Contact detection cancelled.")
