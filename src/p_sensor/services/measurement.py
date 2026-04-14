from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from threading import Event

from p_sensor.acquisition import AcquisitionController, MeasurementBackend
from p_sensor.models import MeasurementFrame


@dataclass(slots=True)
class AggregatedInputChannel:
    channel_index: int
    channel_name: str
    average_voltage: float
    average_value: float
    unit: str


@dataclass(slots=True)
class AggregatedOutputChannel:
    channel_index: int
    channel_name: str
    average_current_ma: float


@dataclass(slots=True)
class MeasurementWindowResult:
    started_at: datetime
    ended_at: datetime
    frames: list[MeasurementFrame]
    average_inputs: list[AggregatedInputChannel]
    average_outputs: list[AggregatedOutputChannel]

    @property
    def frame_count(self) -> int:
        return len(self.frames)


class MeasurementWindowCancelledError(RuntimeError):
    pass


class MeasurementService:
    POLL_INTERVAL_S = 0.01
    POST_PAUSE_DRAIN_WAIT_S = 0.02

    def __init__(self, backend: MeasurementBackend, acquisition_hz: float) -> None:
        self.controller = AcquisitionController(backend, acquisition_hz)
        self._connected = False

    @property
    def config(self):
        return self.controller.backend.config

    def connect(self) -> str:
        if self._connected:
            return "Measurement service already connected"
        message = self.controller.connect()
        self._connected = True
        return message

    def disconnect(self) -> None:
        if self.controller.is_running:
            self.controller.stop()
        else:
            self.controller.backend.disconnect()
        self._connected = False

    def shutdown(self) -> None:
        self.disconnect()

    def collect_window(
        self,
        *,
        duration_s: float | None = None,
        frame_count: int | None = None,
        stop_event: Event | None = None,
    ) -> MeasurementWindowResult:
        self._validate_window_request(duration_s=duration_s, frame_count=frame_count)
        if not self._connected:
            self.connect()

        self.controller.drain_frames()
        started_at = datetime.now()
        started_monotonic = time.monotonic()

        if self.controller.is_running:
            self.controller.resume()
        else:
            self.controller.start()

        frames: list[MeasurementFrame] = []
        while not self._window_complete(
            started_monotonic=started_monotonic,
            frames=frames,
            duration_s=duration_s,
            frame_count=frame_count,
        ):
            if stop_event is not None and stop_event.is_set():
                self._pause_after_window_cancel()
                raise MeasurementWindowCancelledError("Measurement window cancelled.")
            failure = self.controller.pop_failure()
            if failure is not None:
                self.controller.stop()
                self._connected = False
                raise failure
            frames.extend(self.controller.drain_frames())
            time.sleep(self.POLL_INTERVAL_S)

        failure = self.controller.pop_failure()
        if failure is not None:
            self.controller.stop()
            self._connected = False
            raise failure

        frames.extend(self.controller.drain_frames())
        if self.controller.is_running:
            self.controller.pause()
            time.sleep(self.POST_PAUSE_DRAIN_WAIT_S)
            frames.extend(self.controller.drain_frames())

        ended_at = frames[-1].timestamp if frames else datetime.now()
        return MeasurementWindowResult(
            started_at=started_at,
            ended_at=ended_at,
            frames=frames,
            average_inputs=self._aggregate_inputs(frames),
            average_outputs=self._aggregate_outputs(frames),
        )

    def _pause_after_window_cancel(self) -> None:
        if self.controller.is_running:
            self.controller.pause()
            time.sleep(self.POST_PAUSE_DRAIN_WAIT_S)
            self.controller.drain_frames()

    def _validate_window_request(self, *, duration_s: float | None, frame_count: int | None) -> None:
        if duration_s is None and frame_count is None:
            raise ValueError("Measurement window requires duration_s or frame_count.")
        if duration_s is not None and duration_s <= 0:
            raise ValueError("Measurement duration must be greater than 0.")
        if frame_count is not None and frame_count <= 0:
            raise ValueError("Measurement frame_count must be greater than 0.")

    def _window_complete(
        self,
        *,
        started_monotonic: float,
        frames: list[MeasurementFrame],
        duration_s: float | None,
        frame_count: int | None,
    ) -> bool:
        duration_met = duration_s is not None and (time.monotonic() - started_monotonic) >= duration_s
        frame_count_met = frame_count is not None and len(frames) >= frame_count
        if duration_s is not None and frame_count is not None:
            return duration_met and frame_count_met
        return duration_met or frame_count_met

    def _aggregate_inputs(self, frames: list[MeasurementFrame]) -> list[AggregatedInputChannel]:
        if not frames:
            return []

        grouped: dict[int, list] = {}
        for frame in frames:
            for reading in frame.inputs:
                grouped.setdefault(reading.channel_index, []).append(reading)

        aggregated: list[AggregatedInputChannel] = []
        for channel_index in sorted(grouped):
            readings = grouped[channel_index]
            count = len(readings)
            aggregated.append(
                AggregatedInputChannel(
                    channel_index=channel_index,
                    channel_name=readings[0].channel_name,
                    average_voltage=sum(reading.voltage for reading in readings) / count,
                    average_value=sum(reading.scaled_value for reading in readings) / count,
                    unit=readings[0].unit,
                )
            )
        return aggregated

    def _aggregate_outputs(self, frames: list[MeasurementFrame]) -> list[AggregatedOutputChannel]:
        if not frames:
            return []

        grouped: dict[int, list] = {}
        for frame in frames:
            for state in frame.outputs:
                grouped.setdefault(state.channel_index, []).append(state)

        aggregated: list[AggregatedOutputChannel] = []
        for channel_index in sorted(grouped):
            states = grouped[channel_index]
            count = len(states)
            aggregated.append(
                AggregatedOutputChannel(
                    channel_index=channel_index,
                    channel_name=states[0].channel_name,
                    average_current_ma=sum(state.current_ma for state in states) / count,
                )
            )
        return aggregated
