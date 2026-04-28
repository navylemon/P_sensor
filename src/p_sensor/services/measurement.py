from __future__ import annotations

import time
from collections.abc import Callable
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
    captured_frame_count: int | None = None

    @property
    def frame_count(self) -> int:
        if self.captured_frame_count is not None:
            return self.captured_frame_count
        return len(self.frames)


class MeasurementWindowCancelledError(RuntimeError):
    pass


@dataclass(slots=True)
class _InputAggregationState:
    channel_name: str
    unit: str
    voltage_sum: float = 0.0
    value_sum: float = 0.0
    count: int = 0


@dataclass(slots=True)
class _OutputAggregationState:
    channel_name: str
    current_sum_ma: float = 0.0
    count: int = 0


class _WindowAggregator:
    def __init__(self) -> None:
        self.frame_count = 0
        self.last_timestamp: datetime | None = None
        self._input_channels: dict[int, _InputAggregationState] = {}
        self._output_channels: dict[int, _OutputAggregationState] = {}

    def consume(self, frame: MeasurementFrame) -> None:
        self.frame_count += 1
        self.last_timestamp = frame.timestamp
        for reading in frame.inputs:
            state = self._input_channels.setdefault(
                reading.channel_index,
                _InputAggregationState(channel_name=reading.channel_name, unit=reading.unit),
            )
            state.voltage_sum += reading.voltage
            state.value_sum += reading.scaled_value
            state.count += 1
        for state in frame.outputs:
            output = self._output_channels.setdefault(
                state.channel_index,
                _OutputAggregationState(channel_name=state.channel_name),
            )
            output.current_sum_ma += state.current_ma
            output.count += 1

    def average_inputs(self) -> list[AggregatedInputChannel]:
        aggregated: list[AggregatedInputChannel] = []
        for channel_index in sorted(self._input_channels):
            state = self._input_channels[channel_index]
            aggregated.append(
                AggregatedInputChannel(
                    channel_index=channel_index,
                    channel_name=state.channel_name,
                    average_voltage=state.voltage_sum / state.count,
                    average_value=state.value_sum / state.count,
                    unit=state.unit,
                )
            )
        return aggregated

    def average_outputs(self) -> list[AggregatedOutputChannel]:
        aggregated: list[AggregatedOutputChannel] = []
        for channel_index in sorted(self._output_channels):
            state = self._output_channels[channel_index]
            aggregated.append(
                AggregatedOutputChannel(
                    channel_index=channel_index,
                    channel_name=state.channel_name,
                    average_current_ma=state.current_sum_ma / state.count,
                )
            )
        return aggregated


class MeasurementService:
    POLL_INTERVAL_S = 0.01
    POST_PAUSE_DRAIN_WAIT_S = 0.02
    SNAPSHOT_TIMEOUT_S = 2.0

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

    def read_snapshot(
        self,
        *,
        timeout_s: float | None = None,
        stop_event: Event | None = None,
    ) -> MeasurementFrame:
        if not self._connected:
            self.connect()

        timeout = self.SNAPSHOT_TIMEOUT_S if timeout_s is None else timeout_s
        self.controller.drain_frames()
        if self.controller.is_running:
            self.controller.resume()
        else:
            self.controller.start()

        started_monotonic = time.monotonic()
        while True:
            if stop_event is not None and stop_event.is_set():
                self._pause_after_window_cancel()
                raise MeasurementWindowCancelledError("Measurement snapshot cancelled.")
            failure = self.controller.pop_failure()
            if failure is not None:
                self.controller.stop()
                self._connected = False
                raise failure
            frames = self.controller.drain_frames()
            if frames:
                if self.controller.is_running:
                    self.controller.pause()
                    time.sleep(self.POST_PAUSE_DRAIN_WAIT_S)
                    frames.extend(self.controller.drain_frames())
                return frames[-1]
            if (time.monotonic() - started_monotonic) >= timeout:
                self._pause_after_window_cancel()
                raise TimeoutError(f"Measurement snapshot did not arrive within {timeout:.2f}s.")
            time.sleep(self.POLL_INTERVAL_S)

    def collect_window(
        self,
        *,
        duration_s: float | None = None,
        frame_count: int | None = None,
        stop_event: Event | None = None,
        frame_callback: Callable[[MeasurementFrame], None] | None = None,
        retain_frames: bool = True,
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
        aggregator = _WindowAggregator()
        while not self._window_complete(
            started_monotonic=started_monotonic,
            captured_frame_count=aggregator.frame_count,
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
            self._consume_frames(
                self.controller.drain_frames(),
                frames=frames,
                aggregator=aggregator,
                frame_callback=frame_callback,
                retain_frames=retain_frames,
            )
            time.sleep(self.POLL_INTERVAL_S)

        failure = self.controller.pop_failure()
        if failure is not None:
            self.controller.stop()
            self._connected = False
            raise failure

        self._consume_frames(
            self.controller.drain_frames(),
            frames=frames,
            aggregator=aggregator,
            frame_callback=frame_callback,
            retain_frames=retain_frames,
        )
        if self.controller.is_running:
            self.controller.pause()
            time.sleep(self.POST_PAUSE_DRAIN_WAIT_S)
            self._consume_frames(
                self.controller.drain_frames(),
                frames=frames,
                aggregator=aggregator,
                frame_callback=frame_callback,
                retain_frames=retain_frames,
            )

        ended_at = aggregator.last_timestamp or datetime.now()
        return MeasurementWindowResult(
            started_at=started_at,
            ended_at=ended_at,
            frames=frames,
            average_inputs=aggregator.average_inputs(),
            average_outputs=aggregator.average_outputs(),
            captured_frame_count=aggregator.frame_count,
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
        captured_frame_count: int,
        duration_s: float | None,
        frame_count: int | None,
    ) -> bool:
        duration_met = duration_s is not None and (time.monotonic() - started_monotonic) >= duration_s
        frame_count_met = frame_count is not None and captured_frame_count >= frame_count
        if duration_s is not None and frame_count is not None:
            return duration_met and frame_count_met
        return duration_met or frame_count_met

    def _consume_frames(
        self,
        drained_frames: list[MeasurementFrame],
        *,
        frames: list[MeasurementFrame],
        aggregator: _WindowAggregator,
        frame_callback: Callable[[MeasurementFrame], None] | None,
        retain_frames: bool,
    ) -> None:
        if not drained_frames:
            return
        try:
            for frame in drained_frames:
                aggregator.consume(frame)
                if retain_frames:
                    frames.append(frame)
                if frame_callback is not None:
                    frame_callback(frame)
        except Exception:
            self._pause_after_window_cancel()
            raise
