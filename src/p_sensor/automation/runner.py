from __future__ import annotations

from collections.abc import Callable
import time
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any
from typing import Protocol

from p_sensor.automation.contact import (
    ContactDetectionCancelledError,
    ContactDetectionConfig,
    ContactDetectionError,
    ContactDetector,
)
from p_sensor.automation.models import AutomationRecipe, AutomationSessionOptions, AutomationSessionResult, AutomationStep
from p_sensor.automation.safety import AutomationReadyTimeoutError, AutomationSafetyError, AutomationSafetyPolicy
from p_sensor.automation.storage import AutomationSessionStore
from p_sensor.models import MeasurementFrame
from p_sensor.services import MeasurementService, MeasurementWindowCancelledError


class CommandBridge(Protocol):
    def set_velocity_mm_min(self, velocity_mm_min: float | None) -> None: ...

    def move_relative_mm(self, *, axis: int, delta_mm: float) -> None: ...

    def engage(self, step: AutomationStep) -> None: ...

    def disengage(self, step: AutomationStep) -> None: ...

    def wait_until_ready(
        self,
        timeout_s: float | None = None,
        position_callback: Callable[[float | None], None] | None = None,
    ) -> None: ...

    def abort(self) -> None: ...

    def get_position_mm(self) -> float | None: ...

    def reset_logical_zero(self) -> None: ...


class NoOpCommandBridge:
    def set_velocity_mm_min(self, velocity_mm_min: float | None) -> None:
        return None

    def move_relative_mm(self, *, axis: int, delta_mm: float) -> None:
        return None

    def engage(self, step: AutomationStep) -> None:
        return None

    def disengage(self, step: AutomationStep) -> None:
        return None

    def wait_until_ready(
        self,
        timeout_s: float | None = None,
        position_callback: Callable[[float | None], None] | None = None,
    ) -> None:
        return None

    def abort(self) -> None:
        return None

    def get_position_mm(self) -> float | None:
        return None

    def reset_logical_zero(self) -> None:
        return None


class _MeasurementServiceResistanceSampler:
    def __init__(
        self,
        measurement_service: MeasurementService,
        *,
        channel_index: int | None = None,
        stop_event: Event | None = None,
    ) -> None:
        self.measurement_service = measurement_service
        self.channel_index = channel_index
        self.stop_event = stop_event

    def read_resistance_ohm(self) -> float:
        frame = self.measurement_service.read_snapshot(stop_event=self.stop_event)
        if not frame.inputs:
            raise ContactDetectionError("Contact detection requires at least one active input channel.")
        if self.channel_index is None:
            return frame.inputs[0].scaled_value
        for reading in frame.inputs:
            if reading.channel_index == self.channel_index:
                return reading.scaled_value
        raise ContactDetectionError(
            f"Configured contact detection channel_index {self.channel_index} is not active in measurement data."
        )


class AutomationCancelledError(RuntimeError):
    pass


class ExperimentRunner:
    def __init__(
        self,
        measurement_service: MeasurementService,
        *,
        command_bridge: CommandBridge | None = None,
        sleep_fn=time.sleep,
        event_callback=None,
        measurement_frame_callback: Callable[[MeasurementFrame], None] | None = None,
        stop_event: Event | None = None,
        safety_policy: AutomationSafetyPolicy | None = None,
    ) -> None:
        self.measurement_service = measurement_service
        self.command_bridge = command_bridge or NoOpCommandBridge()
        self.sleep_fn = sleep_fn
        self.event_callback = event_callback
        self.measurement_frame_callback = measurement_frame_callback
        self.stop_event = stop_event
        self.safety_policy = safety_policy or AutomationSafetyPolicy()

    def run(
        self,
        recipe: AutomationRecipe,
        options: AutomationSessionOptions,
    ) -> AutomationSessionResult:
        self.safety_policy.validate_start()
        self.safety_policy.validate_recipe(recipe)
        started_at = self._now()
        store = AutomationSessionStore(
            options=options,
            config=self.measurement_service.config,
            recipe=recipe,
            started_at=started_at,
        )
        self._emit("session_started", session_id=store.session_id, session_dir=str(store.session_dir))
        bridge_connect_message = self._connect_bridge()
        connect_message = self.measurement_service.connect()
        manifest_metadata = {"measurement_service_connect": connect_message}
        if bridge_connect_message is not None:
            manifest_metadata["motion_bridge_connect"] = bridge_connect_message
        contact_result = self._run_contact_detection_if_enabled(recipe)
        if contact_result is not None:
            manifest_metadata["contact_detection"] = {
                "detected": contact_result.detected,
                "contact_position_mm": contact_result.contact_position_mm,
                "contact_resistance_ohm": contact_result.contact_resistance_ohm,
                "delta_resistance_ohm": contact_result.delta_resistance_ohm,
                "traveled_mm": contact_result.traveled_mm,
                "elapsed_s": contact_result.elapsed_s,
                "reason": contact_result.reason,
                "use_as_zero": contact_result.use_as_zero,
            }
        store.write_manifest(extra_metadata=manifest_metadata, status="running")

        try:
            for step_index, step in enumerate(recipe.steps, start=1):
                self._ensure_not_cancelled()
                self._run_step(step_index=step_index, step=step, store=store)
            store.write_manifest(status="completed")
            result = store.to_session_result()
            self._emit("session_completed", session_id=result.session_id, step_count=len(result.step_results))
            return result
        except AutomationCancelledError as exc:
            self._abort_after_interruption(reason="cancelled")
            store.write_manifest(status="cancelled", extra_metadata={"last_error": str(exc)})
            self._emit("session_cancelled", session_id=store.session_id)
            raise
        except Exception as exc:
            self._abort_after_interruption(reason="failed")
            store.write_manifest(status="failed", extra_metadata={"last_error": str(exc)})
            self._emit("session_failed", session_id=store.session_id)
            raise
        finally:
            store.close()
            self.measurement_service.shutdown()
            self._disconnect_bridge()

    def _run_step(self, *, step_index: int, step: AutomationStep, store: AutomationSessionStore) -> None:
        position_before_mm = self._get_motion_position_mm()
        position_after_engage_mm = None
        position_after_disengage_mm = None
        self._emit(
            "step_started",
            step_index=step_index,
            step_id=step.step_id,
            target_displacement=step.target_displacement,
            cycle_index=step.cycle_index,
            phase=step.phase,
            velocity_mm_min=step.velocity_mm_min,
            measure_enabled=step.measure_enabled,
            position_before_mm=position_before_mm,
            position_after_engage_mm=position_after_engage_mm,
            position_after_disengage_mm=position_after_disengage_mm,
        )
        self.safety_policy.validate_position_mm(
            position_before_mm,
            label=f"position before step {step.step_id!r}",
        )
        self._emit_phase_started(step_index=step_index, step=step, phase="move")
        self._apply_step_velocity(step)
        self.command_bridge.engage(step)
        self._wait_until_ready(step, phase="engage")
        self._emit_phase_completed(step_index=step_index, step=step, phase="move")
        position_after_engage_mm = self._get_motion_position_mm()
        self.safety_policy.validate_position_mm(
            position_after_engage_mm,
            label=f"position after engage for step {step.step_id!r}",
        )
        self._ensure_not_cancelled()
        if step.settle_time_s > 0:
            self._emit_phase_started(
                step_index=step_index,
                step=step,
                phase="settle",
                duration_s=step.settle_time_s,
            )
            self.sleep_fn(step.settle_time_s)
            self._emit_phase_completed(
                step_index=step_index,
                step=step,
                phase="settle",
                duration_s=step.settle_time_s,
            )
        self._ensure_not_cancelled()

        window_result = None
        measurement_files: tuple[Path, ...] | None = None
        if step.measure_enabled:
            self._emit_phase_started(
                step_index=step_index,
                step=step,
                phase="measure",
                duration_s=step.measure_duration_s,
            )
            measurement_recorder = store.open_measurement_recorder(step_index=step_index)
            try:
                def append_measurement_frame(frame: MeasurementFrame) -> None:
                    measurement_recorder.append(frame)
                    if self.measurement_frame_callback is not None:
                        self.measurement_frame_callback(frame)

                try:
                    window_result = self.measurement_service.collect_window(
                        duration_s=step.measure_duration_s,
                        frame_count=step.measure_frame_count,
                        stop_event=self.stop_event,
                        frame_callback=append_measurement_frame,
                        retain_frames=False,
                    )
                except MeasurementWindowCancelledError as exc:
                    raise AutomationCancelledError(str(exc)) from exc
            except Exception:
                raise
            finally:
                measurement_files = measurement_recorder.close()
            self._emit_phase_completed(
                step_index=step_index,
                step=step,
                phase="measure",
                duration_s=step.measure_duration_s,
            )
        if step.disengage_after_measure:
            self._emit_phase_started(step_index=step_index, step=step, phase="disengage")
            self.command_bridge.disengage(step)
            self._wait_until_ready(step, phase="disengage")
            self._emit_phase_completed(step_index=step_index, step=step, phase="disengage")
            position_after_disengage_mm = self._get_motion_position_mm()
            self.safety_policy.validate_position_mm(
                position_after_disengage_mm,
                label=f"position after disengage for step {step.step_id!r}",
            )
        result = store.append_step_result(
            step_index=step_index,
            step=step,
            measurement_files=measurement_files,
            window_result=window_result,
            position_before_mm=position_before_mm,
            position_after_engage_mm=position_after_engage_mm,
            position_after_disengage_mm=position_after_disengage_mm,
        )
        self._emit(
            "step_completed",
            step_index=step_index,
            step_id=step.step_id,
            target_displacement=step.target_displacement,
            measurement_file=result.measurement_file,
            measurement_chunk_count=result.measurement_chunk_count,
            measurement_files=list(result.measurement_files),
            frame_count=result.frame_count,
            cycle_index=step.cycle_index,
            phase=step.phase,
            velocity_mm_min=step.velocity_mm_min,
            measure_enabled=step.measure_enabled,
            position_before_mm=position_before_mm,
            position_after_engage_mm=position_after_engage_mm,
            position_after_disengage_mm=position_after_disengage_mm,
        )

        self._ensure_not_cancelled()
        if step.post_disengage_wait_s > 0:
            self._emit_phase_started(
                step_index=step_index,
                step=step,
                phase="post_disengage_wait",
                duration_s=step.post_disengage_wait_s,
            )
            self.sleep_fn(step.post_disengage_wait_s)
            self._emit_phase_completed(
                step_index=step_index,
                step=step,
                phase="post_disengage_wait",
                duration_s=step.post_disengage_wait_s,
            )
        self._ensure_not_cancelled()

    def _now(self) -> datetime:
        return datetime.now()

    def _run_contact_detection_if_enabled(self, recipe: AutomationRecipe):
        config = self._contact_detection_config_from_recipe(recipe.metadata)
        if config is None:
            return None
        if isinstance(self.command_bridge, NoOpCommandBridge):
            raise ContactDetectionError("Contact detection requires a connected motion bridge.")

        self._emit(
            "contact_detection_started",
            stage_axis=config.stage_axis,
            max_travel_mm=config.max_travel_mm,
            scan_speed_mm_s=config.scan_speed_mm_s,
            delta_resistance_threshold_ohm=config.delta_resistance_threshold_ohm,
        )
        sampler = _MeasurementServiceResistanceSampler(
            self.measurement_service,
            channel_index=self._contact_detection_channel_index(recipe.metadata),
            stop_event=self.stop_event,
        )
        detector = ContactDetector(self.command_bridge, sampler, sleep_fn=self.sleep_fn)
        try:
            result = detector.detect(config, stop_event=self.stop_event)
        except ContactDetectionCancelledError as exc:
            raise AutomationCancelledError(str(exc)) from exc

        if not result.detected:
            raise ContactDetectionError(
                "Contact detection failed before the measurement run. "
                f"Reason: {result.reason}, traveled_mm={result.traveled_mm:.6g}"
            )

        self._emit(
            "contact_detection_completed",
            detected=result.detected,
            contact_position_mm=result.contact_position_mm,
            contact_resistance_ohm=result.contact_resistance_ohm,
            delta_resistance_ohm=result.delta_resistance_ohm,
            traveled_mm=result.traveled_mm,
            elapsed_s=result.elapsed_s,
            reason=result.reason,
            use_as_zero=result.use_as_zero,
            stage_axis=config.stage_axis,
        )
        if result.use_as_zero:
            reset_logical_zero = getattr(self.command_bridge, "reset_logical_zero", None)
            if not callable(reset_logical_zero):
                raise AutomationSafetyError("Contact detection requested logical zero reset, but the motion bridge does not support it.")
            reset_logical_zero()
            self._emit(
                "contact_detection_zero_applied",
                contact_position_mm=result.contact_position_mm,
            )
        return result

    def _contact_detection_channel_index(self, metadata: dict[str, Any]) -> int | None:
        payload = self._contact_detection_metadata_payload(metadata)
        raw_value = payload.get("contact_channel_index")
        if raw_value is None:
            return None
        return int(raw_value)

    def _contact_detection_config_from_recipe(self, metadata: dict[str, Any]) -> ContactDetectionConfig | None:
        payload = self._contact_detection_metadata_payload(metadata)
        enabled = self._metadata_bool(payload.get("enable_contact_detection"), False)
        if not enabled:
            return None
        return ContactDetectionConfig(
            stage_axis=int(payload.get("contact_stage_axis", 1)),
            scan_speed_mm_s=float(payload.get("contact_scan_speed_mm_s", 0.02)),
            scan_step_mm=float(payload.get("contact_scan_step_mm", 0.01)),
            max_travel_mm=float(payload.get("contact_max_travel_mm", 1.0)),
            delta_resistance_threshold_ohm=float(payload.get("contact_delta_resistance_threshold_ohm", 1.0)),
            baseline_duration_s=float(payload.get("contact_baseline_duration_s", 0.2)),
            stable_duration_s=float(payload.get("contact_stable_duration_s", 0.05)),
            sample_interval_s=float(payload.get("contact_sample_interval_s", 0.01)),
            ready_timeout_s=self._optional_float(payload.get("contact_ready_timeout_s", 10.0)),
            descent_direction=int(payload.get("contact_descent_direction", -1)),
            change_mode=str(payload.get("contact_change_mode", "absolute")),
            use_as_zero=self._metadata_bool(payload.get("contact_use_as_zero"), True),
        )

    def _contact_detection_metadata_payload(self, metadata: dict[str, Any]) -> dict[str, Any]:
        if not metadata:
            return {}
        raw_section = metadata.get("contact_detection")
        if isinstance(raw_section, dict):
            payload = dict(metadata)
            payload.update(raw_section)
            return payload
        return dict(metadata)

    def _metadata_bool(self, value: Any, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on"}:
                return True
            if normalized in {"0", "false", "no", "off"}:
                return False
        return bool(value)

    def _optional_float(self, value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    def _emit(self, event_name: str, **payload) -> None:
        if self.event_callback is not None:
            self.event_callback(event_name, payload)

    def _emit_phase_started(
        self,
        *,
        step_index: int,
        step: AutomationStep,
        phase: str,
        duration_s: float | None = None,
    ) -> None:
        self._emit_phase_event(
            "phase_started",
            step_index=step_index,
            step=step,
            phase=phase,
            duration_s=duration_s,
        )

    def _emit_phase_completed(
        self,
        *,
        step_index: int,
        step: AutomationStep,
        phase: str,
        duration_s: float | None = None,
    ) -> None:
        self._emit_phase_event(
            "phase_completed",
            step_index=step_index,
            step=step,
            phase=phase,
            duration_s=duration_s,
        )

    def _emit_phase_event(
        self,
        event_name: str,
        *,
        step_index: int,
        step: AutomationStep,
        phase: str,
        duration_s: float | None,
    ) -> None:
        self._emit(
            event_name,
            step_index=step_index,
            step_id=step.step_id,
            phase=phase,
            duration_s=duration_s,
            cycle_index=step.cycle_index,
            target_displacement=step.target_displacement,
            velocity_mm_min=step.velocity_mm_min,
            measure_enabled=step.measure_enabled,
        )

    def _ensure_not_cancelled(self) -> None:
        if self.stop_event is not None and self.stop_event.is_set():
            raise AutomationCancelledError("Automation run cancelled.")

    def _connect_bridge(self) -> str | None:
        connect = getattr(self.command_bridge, "connect", None)
        if callable(connect):
            message = connect()
            if isinstance(message, str):
                self._emit("motion_connected", message=message)
                return message
            return None
        return None

    def _disconnect_bridge(self) -> None:
        disconnect = getattr(self.command_bridge, "disconnect", None)
        if callable(disconnect):
            disconnect()

    def _abort_after_interruption(self, *, reason: str) -> None:
        self._emit("motion_abort_requested", reason=reason)
        try:
            self.command_bridge.abort()
        except Exception as exc:
            self._emit("motion_abort_failed", reason=reason, error=str(exc))
        self._emit(
            "recovery_required",
            reason=reason,
            message="Confirm motion state, clear the controller error if needed, then re-home or reset the logical origin before the next automation run.",
        )

    def _wait_until_ready(self, step: AutomationStep, *, phase: str) -> None:
        try:
            try:
                self.command_bridge.wait_until_ready(
                    step.ready_timeout_s,
                    position_callback=lambda position_mm: self._emit_motion_position(position_mm, phase=phase),
                )
            except TypeError as exc:
                if "position_callback" not in str(exc):
                    raise
                self.command_bridge.wait_until_ready(step.ready_timeout_s)
        except TimeoutError as exc:
            raise AutomationReadyTimeoutError(
                step_id=step.step_id,
                phase=phase,
                timeout_s=step.ready_timeout_s,
            ) from exc

    def _apply_step_velocity(self, step: AutomationStep) -> None:
        if step.velocity_mm_min is None:
            return
        set_velocity = getattr(self.command_bridge, "set_velocity_mm_min", None)
        if callable(set_velocity):
            set_velocity(step.velocity_mm_min)

    def _emit_motion_position(self, position_mm: float | None, *, phase: str) -> None:
        if position_mm is None:
            return
        axis = getattr(getattr(self.command_bridge, "config", None), "axis", 1)
        self._emit("motion_position", axis=axis, position_mm=position_mm, phase=phase)

    def _get_motion_position_mm(self) -> float | None:
        get_position = getattr(self.command_bridge, "get_position_mm", None)
        if not callable(get_position):
            return None
        return get_position()
