from __future__ import annotations

import queue
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime

from p_sensor.models import AppConfig, AnalogOutputState, MeasurementFrame


class BackendError(RuntimeError):
    pass


class MeasurementBackend(ABC):
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    @abstractmethod
    def connect(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def read(self, elapsed_s: float) -> MeasurementFrame:
        raise NotImplementedError

    def write_output_currents(self, currents_ma: dict[int, float]) -> list[AnalogOutputState]:
        return []


class AcquisitionController:
    STOP_JOIN_TIMEOUT_S = 6.0

    def __init__(self, backend: MeasurementBackend, acquisition_hz: float) -> None:
        self.backend = backend
        self.acquisition_hz = max(1.0, acquisition_hz)
        self.frames: queue.Queue[MeasurementFrame] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._running = threading.Event()
        self._paused = threading.Event()
        self._started_at: float | None = None
        self._pause_started_at: float | None = None
        self._paused_accumulated_s = 0.0
        self._failure: Exception | None = None
        self._failure_lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def connect(self) -> str:
        self._clear_failure()
        return self.backend.connect()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._clear_failure()
        self._clear_pending_frames()
        self._running.set()
        self._paused.clear()
        self._started_at = time.perf_counter()
        self._pause_started_at = None
        self._paused_accumulated_s = 0.0
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def pause(self) -> None:
        if not self._running.is_set() or self._paused.is_set():
            return
        self._pause_started_at = time.perf_counter()
        self._paused.set()

    def resume(self) -> None:
        if not self._paused.is_set():
            return
        if self._pause_started_at is not None:
            self._paused_accumulated_s += time.perf_counter() - self._pause_started_at
        self._pause_started_at = None
        self._paused.clear()

    def stop(self) -> None:
        self._running.clear()
        self._paused.clear()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.STOP_JOIN_TIMEOUT_S)
        self._thread = None
        self.backend.disconnect()

    def drain_frames(self) -> list[MeasurementFrame]:
        drained: list[MeasurementFrame] = []
        while True:
            try:
                drained.append(self.frames.get_nowait())
            except queue.Empty:
                break
        return drained

    def pop_failure(self) -> Exception | None:
        with self._failure_lock:
            failure = self._failure
            self._failure = None
        return failure

    def _clear_pending_frames(self) -> None:
        self.drain_frames()

    def _clear_failure(self) -> None:
        with self._failure_lock:
            self._failure = None

    def _set_failure(self, exc: Exception) -> None:
        with self._failure_lock:
            self._failure = exc

    def _run_loop(self) -> None:
        interval = 1.0 / self.acquisition_hz

        while self._running.is_set():
            loop_started = time.perf_counter()
            try:
                if self._paused.is_set():
                    time.sleep(min(interval, 0.05))
                    continue
                elapsed_s = loop_started - (self._started_at or loop_started)
                elapsed_s -= self._paused_accumulated_s
                frame = self.backend.read(elapsed_s)
                frame.timestamp = datetime.now()
                self.frames.put(frame)
            except Exception as exc:
                if self._running.is_set():
                    self._set_failure(exc)
                self._running.clear()
                break

            sleep_s = interval - (time.perf_counter() - loop_started)
            if sleep_s > 0:
                time.sleep(sleep_s)
