from __future__ import annotations

import time
from datetime import datetime
from threading import Event
from typing import Protocol

from p_sensor.automation.models import AutomationRecipe, AutomationSessionOptions, AutomationSessionResult, AutomationStep
from p_sensor.automation.safety import AutomationReadyTimeoutError, AutomationSafetyPolicy
from p_sensor.automation.storage import AutomationSessionStore
from p_sensor.services import MeasurementService, MeasurementWindowCancelledError


class CommandBridge(Protocol):
    def set_velocity_mm_min(self, velocity_mm_min: float | None) -> None: ...

    def engage(self, step: AutomationStep) -> None: ...

    def disengage(self, step: AutomationStep) -> None: ...

    def wait_until_ready(self, timeout_s: float | None = None) -> None: ...

    def abort(self) -> None: ...

    def get_position_mm(self) -> float | None: ...


class NoOpCommandBridge:
    def set_velocity_mm_min(self, velocity_mm_min: float | None) -> None:
        return None

    def engage(self, step: AutomationStep) -> None:
        return None

    def disengage(self, step: AutomationStep) -> None:
        return None

    def wait_until_ready(self, timeout_s: float | None = None) -> None:
        return None

    def abort(self) -> None:
        return None

    def get_position_mm(self) -> float | None:
        return None


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
        stop_event: Event | None = None,
        safety_policy: AutomationSafetyPolicy | None = None,
    ) -> None:
        self.measurement_service = measurement_service
        self.command_bridge = command_bridge or NoOpCommandBridge()
        self.sleep_fn = sleep_fn
        self.event_callback = event_callback
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
        store.write_manifest(extra_metadata=manifest_metadata)

        try:
            for step_index, step in enumerate(recipe.steps, start=1):
                self._ensure_not_cancelled()
                self._run_step(step_index=step_index, step=step, store=store)
            result = store.to_session_result()
            self._emit("session_completed", session_id=result.session_id, step_count=len(result.step_results))
            return result
        except AutomationCancelledError:
            self._abort_after_interruption(reason="cancelled")
            self._emit("session_cancelled", session_id=store.session_id)
            raise
        except Exception:
            self._abort_after_interruption(reason="failed")
            self._emit("session_failed", session_id=store.session_id)
            raise
        finally:
            store.close()
            self.measurement_service.shutdown()
            self._disconnect_bridge()

    def _run_step(self, *, step_index: int, step: AutomationStep, store: AutomationSessionStore) -> None:
        self._emit(
            "step_started",
            step_index=step_index,
            step_id=step.step_id,
            target_displacement=step.target_displacement,
            cycle_index=step.cycle_index,
            phase=step.phase,
            velocity_mm_min=step.velocity_mm_min,
            measure_enabled=step.measure_enabled,
        )
        position_before_mm = self._get_motion_position_mm()
        self.safety_policy.validate_position_mm(
            position_before_mm,
            label=f"position before step {step.step_id!r}",
        )
        self._apply_step_velocity(step)
        self.command_bridge.engage(step)
        self._wait_until_ready(step, phase="engage")
        position_after_engage_mm = self._get_motion_position_mm()
        self.safety_policy.validate_position_mm(
            position_after_engage_mm,
            label=f"position after engage for step {step.step_id!r}",
        )
        self._ensure_not_cancelled()
        if step.settle_time_s > 0:
            self.sleep_fn(step.settle_time_s)
        self._ensure_not_cancelled()

        window_result = None
        measurement_path = None
        if step.measure_enabled:
            try:
                window_result = self.measurement_service.collect_window(
                    duration_s=step.measure_duration_s,
                    frame_count=step.measure_frame_count,
                    stop_event=self.stop_event,
                )
            except MeasurementWindowCancelledError as exc:
                raise AutomationCancelledError(str(exc)) from exc
            measurement_path = store.write_measurement_window(
                step_index=step_index,
                window_result=window_result,
            )
        position_after_disengage_mm = None
        if step.disengage_after_measure:
            self.command_bridge.disengage(step)
            self._wait_until_ready(step, phase="disengage")
            position_after_disengage_mm = self._get_motion_position_mm()
            self.safety_policy.validate_position_mm(
                position_after_disengage_mm,
                label=f"position after disengage for step {step.step_id!r}",
            )
        result = store.append_step_result(
            step_index=step_index,
            step=step,
            measurement_path=measurement_path,
            window_result=window_result,
            position_before_mm=position_before_mm,
            position_after_engage_mm=position_after_engage_mm,
            position_after_disengage_mm=position_after_disengage_mm,
        )
        self._emit(
            "step_completed",
            step_index=step_index,
            step_id=step.step_id,
            measurement_file=result.measurement_file,
            frame_count=result.frame_count,
            cycle_index=step.cycle_index,
            phase=step.phase,
            velocity_mm_min=step.velocity_mm_min,
            measure_enabled=step.measure_enabled,
        )

        self._ensure_not_cancelled()
        if step.post_disengage_wait_s > 0:
            self.sleep_fn(step.post_disengage_wait_s)
        self._ensure_not_cancelled()

    def _now(self) -> datetime:
        return datetime.now()

    def _emit(self, event_name: str, **payload) -> None:
        if self.event_callback is not None:
            self.event_callback(event_name, payload)

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

    def _get_motion_position_mm(self) -> float | None:
        get_position = getattr(self.command_bridge, "get_position_mm", None)
        if not callable(get_position):
            return None
        return get_position()
