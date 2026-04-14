from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass
from pathlib import Path

from p_sensor.models import ChannelConfig, MeasurementSample


@dataclass(slots=True)
class CsvRecorderSummary:
    path: Path
    rows_written: int


class CsvRecorder:
    FLUSH_INTERVAL_S = 1.0
    FLUSH_ROWS = 100
    FSYNC_INTERVAL_S = 5.0

    def __init__(self) -> None:
        self._file = None
        self._writer = None
        self._header_written = False
        self._path: Path | None = None
        self._rows_written = 0
        self._rows_since_flush = 0
        self._last_flush_monotonic = 0.0
        self._last_fsync_monotonic = 0.0

    @property
    def is_active(self) -> bool:
        return self._writer is not None

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def rows_written(self) -> int:
        return self._rows_written

    def start(self, file_path: str | Path, channels: list[ChannelConfig]) -> CsvRecorderSummary:
        if self._file is not None:
            self.stop()

        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._file = path.open("w", newline="", encoding="utf-8", buffering=1)
            self._writer = csv.writer(self._file)
            self._path = path
            self._header_written = False
            self._rows_written = 0
            self._rows_since_flush = 0
            started_at = time.monotonic()
            self._last_flush_monotonic = started_at
            self._last_fsync_monotonic = started_at
            self._write_header(channels)
        except Exception as exc:
            self.stop()
            raise OSError(f"Failed to initialize CSV recorder at {path}: {exc}") from exc

        return CsvRecorderSummary(path=path, rows_written=self._rows_written)

    def _flush_to_disk(self, *, force_fsync: bool = False) -> None:
        if self._file is None:
            return
        now = time.monotonic()
        self._file.flush()
        self._rows_since_flush = 0
        self._last_flush_monotonic = now
        if force_fsync or (now - self._last_fsync_monotonic) >= self.FSYNC_INTERVAL_S:
            os.fsync(self._file.fileno())
            self._last_fsync_monotonic = now

    def _flush_to_disk_if_needed(self) -> None:
        if self._file is None:
            return
        now = time.monotonic()
        if self._rows_since_flush >= self.FLUSH_ROWS or (now - self._last_flush_monotonic) >= self.FLUSH_INTERVAL_S:
            self._flush_to_disk()

    def _write_header(self, channels: list[ChannelConfig]) -> None:
        if not self._writer or not self._file or self._header_written:
            return

        header = ["timestamp", "elapsed_s"]
        for channel in channels:
            if not channel.enabled:
                continue
            base_name = channel.name.lower().replace(" ", "_")
            header.extend([f"{base_name}_voltage", f"{base_name}_resistance_ohm"])

        self._writer.writerow(header)
        self._header_written = True
        self._flush_to_disk(force_fsync=True)

    def append(self, sample: MeasurementSample) -> None:
        if not self._writer or not self._file:
            return

        row = [sample.timestamp.isoformat(timespec="milliseconds"), f"{sample.elapsed_s:.3f}"]
        for reading in sample.readings:
            row.extend([f"{reading.voltage:.6f}", f"{reading.resistance_ohm:.6f}"])

        try:
            self._writer.writerow(row)
            self._rows_written += 1
            self._rows_since_flush += 1
            self._flush_to_disk_if_needed()
        except Exception as exc:
            target = self._path if self._path is not None else "<inactive>"
            raise OSError(f"Failed to append CSV row to {target}: {exc}") from exc

    def stop(self) -> CsvRecorderSummary | None:
        summary = (
            CsvRecorderSummary(path=self._path, rows_written=self._rows_written)
            if self._path is not None
            else None
        )
        if self._file:
            try:
                self._flush_to_disk(force_fsync=True)
            finally:
                self._file.close()
        self._file = None
        self._writer = None
        self._header_written = False
        self._path = None
        self._rows_written = 0
        self._rows_since_flush = 0
        self._last_flush_monotonic = 0.0
        self._last_fsync_monotonic = 0.0
        return summary
