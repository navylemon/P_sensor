from __future__ import annotations

import csv
import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from p_sensor.automation.models import (
    AutomationRecipe,
    AutomationSessionOptions,
    AutomationSessionResult,
    AutomationStep,
    AutomationStepResult,
)
from p_sensor.config import config_to_dict, resolve_runtime_path
from p_sensor.models import AppConfig
from p_sensor.services.measurement import MeasurementWindowResult
from p_sensor.storage import CsvRecorder, build_session_identifier, normalize_session_label


def _channel_slug(name: str) -> str:
    return normalize_session_label(name.lower()) or "channel"


class StepMeasurementRecorder:
    def __init__(
        self,
        *,
        file_path: Path,
        ai_channels,
        ao_channels,
        max_rows_per_file: int | None,
    ) -> None:
        self.file_path = file_path
        self._ai_channels = list(ai_channels)
        self._ao_channels = list(ao_channels)
        self._max_rows_per_file = max_rows_per_file
        self._recorder: CsvRecorder | None = None
        self._chunk_paths: list[Path] = []
        self._closed = False
        self._open_chunk(chunk_index=1)

    @property
    def path(self) -> Path:
        return self._chunk_paths[0] if self._chunk_paths else self.file_path

    @property
    def chunk_paths(self) -> tuple[Path, ...]:
        return tuple(self._chunk_paths)

    def append(self, frame) -> None:
        if self._closed:
            raise RuntimeError("Cannot append to a closed measurement recorder.")
        if self._should_rollover():
            self._rollover()
        if self._recorder is None:
            raise RuntimeError("Measurement recorder is not active.")
        self._recorder.append(frame)

    def close(self) -> tuple[Path, ...]:
        if not self._closed:
            if self._recorder is not None:
                self._recorder.stop()
            self._closed = True
        return self.chunk_paths

    def _should_rollover(self) -> bool:
        if self._max_rows_per_file is None or self._recorder is None:
            return False
        return self._recorder.rows_written >= self._max_rows_per_file

    def _rollover(self) -> None:
        if self._recorder is not None:
            self._recorder.stop()
        self._open_chunk(chunk_index=len(self._chunk_paths) + 1)

    def _open_chunk(self, *, chunk_index: int) -> None:
        chunk_path = self._build_chunk_path(chunk_index)
        recorder = CsvRecorder()
        recorder.start(chunk_path, self._ai_channels, self._ao_channels)
        self._recorder = recorder
        self._chunk_paths.append(chunk_path)

    def _build_chunk_path(self, chunk_index: int) -> Path:
        if chunk_index <= 1:
            return self.file_path
        return self.file_path.with_name(f"{self.file_path.stem}.part{chunk_index:04d}{self.file_path.suffix}")


class AutomationSessionStore:
    DEFAULT_MEASUREMENT_MAX_ROWS_PER_FILE = 100_000

    def __init__(
        self,
        *,
        options: AutomationSessionOptions,
        config: AppConfig,
        recipe: AutomationRecipe,
        started_at: datetime,
    ) -> None:
        self.options = options
        self.config = config
        self.recipe = recipe
        self.started_at = started_at
        self.session_id = build_session_identifier(options.session_label, started_at)
        self.export_root = resolve_runtime_path(options.export_directory)
        self.session_dir = self.export_root / f"session_{self.session_id}"
        self.manifest_path = self.session_dir / "session_manifest.json"
        self.summary_path = self.session_dir / "step_summary.csv"

        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._summary_file = self.summary_path.open("w", newline="", encoding="utf-8")
        self._summary_writer = csv.writer(self._summary_file)
        self._summary_writer.writerow(self._build_summary_header())
        self._summary_file.flush()
        self._step_results: list[AutomationStepResult] = []
        self._runtime_metadata: dict[str, Any] = {}
        self._session_status = "initialized"

    def close(self) -> None:
        if not self._summary_file.closed:
            self._summary_file.flush()
            self._summary_file.close()

    def write_manifest(
        self,
        *,
        extra_metadata: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> Path:
        if extra_metadata:
            self._runtime_metadata.update(extra_metadata)
        if status is not None:
            self._session_status = status
        manifest = {
            "session_id": self.session_id,
            "session_label": normalize_session_label(self.options.session_label),
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "status": self._session_status,
            "completed_step_count": len(self._step_results),
            "step_count": len(self.recipe.steps),
            "export_directory": str(self.export_root),
            "recipe": {
                "recipe_id": self.recipe.recipe_id,
                "steps": [asdict(step) for step in self.recipe.steps],
                "metadata": self.recipe.metadata,
            },
            "config": config_to_dict(self.config),
            "session_metadata": self.options.metadata,
            "step_results": [self._manifest_step_result(result) for result in self._step_results],
        }
        if self._runtime_metadata:
            manifest["runtime_metadata"] = dict(self._runtime_metadata)
        self._write_manifest_atomic(manifest)
        return self.manifest_path

    def write_measurement_window(
        self,
        *,
        step_index: int,
        window_result: MeasurementWindowResult,
    ) -> Path:
        recorder = self.open_measurement_recorder(step_index=step_index)
        try:
            for frame in window_result.frames:
                recorder.append(frame)
        finally:
            recorder.close()
        return recorder.path

    def open_measurement_recorder(self, *, step_index: int) -> StepMeasurementRecorder:
        file_name = f"measurement_{step_index:04d}.csv"
        file_path = self.session_dir / file_name
        return StepMeasurementRecorder(
            file_path=file_path,
            ai_channels=self.config.ai_channels,
            ao_channels=self.config.ao_channels,
            max_rows_per_file=self._measurement_max_rows_per_file(),
        )

    def append_step_result(
        self,
        *,
        step_index: int,
        step: AutomationStep,
        measurement_files: tuple[Path, ...] | None,
        window_result: MeasurementWindowResult | None,
        position_before_mm: float | None = None,
        position_after_engage_mm: float | None = None,
        position_after_disengage_mm: float | None = None,
        status: str = "completed",
    ) -> AutomationStepResult:
        average_inputs = {}
        average_outputs = {}
        started_at = datetime.now()
        ended_at = started_at
        frame_count = 0
        measurement_names: tuple[str, ...] = ()
        if window_result is not None:
            average_inputs = {
                channel.channel_name: {
                    "average_voltage": channel.average_voltage,
                    "average_value": channel.average_value,
                    "unit": channel.unit,
                }
                for channel in window_result.average_inputs
            }
            average_outputs = {
                channel.channel_name: channel.average_current_ma for channel in window_result.average_outputs
            }
            started_at = window_result.started_at
            ended_at = window_result.ended_at
            frame_count = window_result.frame_count
        if measurement_files:
            measurement_names = tuple(path.name for path in measurement_files)
        result = AutomationStepResult(
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
            measurement_file=self._summarize_measurement_files(measurement_names),
            started_at=started_at,
            ended_at=ended_at,
            frame_count=frame_count,
            average_inputs=average_inputs,
            average_outputs=average_outputs,
            measurement_chunk_count=len(measurement_names),
            measurement_files=measurement_names,
            status=status,
            notes=step.notes,
        )
        self._summary_writer.writerow(self._build_summary_row(result))
        self._summary_file.flush()
        self._step_results.append(result)
        self.write_manifest()
        return result

    def to_session_result(self) -> AutomationSessionResult:
        return AutomationSessionResult(
            session_id=self.session_id,
            session_dir=self.session_dir,
            manifest_path=self.manifest_path,
            summary_path=self.summary_path,
            step_results=list(self._step_results),
        )

    def _build_summary_header(self) -> list[str]:
        header = [
            "step_index",
            "step_id",
            "target_displacement",
            "position_before_mm",
            "position_after_engage_mm",
            "position_after_disengage_mm",
            "measurement_file",
            "started_at",
            "ended_at",
            "frame_count",
            "status",
            "notes",
            "cycle_index",
            "phase",
            "velocity_mm_min",
            "measure_enabled",
            "measurement_chunk_count",
            "measurement_files",
        ]
        for channel in self.config.ai_channels:
            if not channel.enabled:
                continue
            slug = _channel_slug(channel.name)
            header.extend([f"{slug}_avg_voltage", f"{slug}_avg_value"])
        for channel in self.config.ao_channels:
            if not channel.enabled:
                continue
            slug = _channel_slug(channel.name)
            header.append(f"{slug}_avg_current_ma")
        return header

    def _build_summary_row(self, result: AutomationStepResult) -> list[str]:
        row = [
            str(result.step_index),
            result.step_id,
            "" if result.target_displacement is None else f"{result.target_displacement:.6f}",
            self._format_optional_float(result.position_before_mm),
            self._format_optional_float(result.position_after_engage_mm),
            self._format_optional_float(result.position_after_disengage_mm),
            result.measurement_file,
            result.started_at.isoformat(timespec="milliseconds"),
            result.ended_at.isoformat(timespec="milliseconds"),
            str(result.frame_count),
            result.status,
            result.notes,
            "" if result.cycle_index is None else str(result.cycle_index),
            result.phase,
            self._format_optional_float(result.velocity_mm_min),
            "true" if result.measure_enabled else "false",
            str(result.measurement_chunk_count),
            ";".join(result.measurement_files),
        ]
        for channel in self.config.ai_channels:
            if not channel.enabled:
                continue
            summary = result.average_inputs.get(channel.name)
            if summary is None:
                row.extend(["", ""])
                continue
            row.extend(
                [
                    f"{float(summary['average_voltage']):.6f}",
                    f"{float(summary['average_value']):.6f}",
                ]
            )
        for channel in self.config.ao_channels:
            if not channel.enabled:
                continue
            average_current = result.average_outputs.get(channel.name)
            row.append("" if average_current is None else f"{average_current:.6f}")
        return row

    def _format_optional_float(self, value: float | None) -> str:
        return "" if value is None else f"{value:.6f}"

    def _manifest_step_result(self, result: AutomationStepResult) -> dict[str, Any]:
        return {
            "step_index": result.step_index,
            "step_id": result.step_id,
            "target_displacement": result.target_displacement,
            "cycle_index": result.cycle_index,
            "phase": result.phase,
            "velocity_mm_min": result.velocity_mm_min,
            "measure_enabled": result.measure_enabled,
            "position_before_mm": result.position_before_mm,
            "position_after_engage_mm": result.position_after_engage_mm,
            "position_after_disengage_mm": result.position_after_disengage_mm,
            "measurement_file": result.measurement_file,
            "measurement_chunk_count": result.measurement_chunk_count,
            "measurement_files": list(result.measurement_files),
            "started_at": result.started_at.isoformat(timespec="milliseconds"),
            "ended_at": result.ended_at.isoformat(timespec="milliseconds"),
            "frame_count": result.frame_count,
            "average_inputs": result.average_inputs,
            "average_outputs": result.average_outputs,
            "status": result.status,
            "notes": result.notes,
        }

    def _measurement_max_rows_per_file(self) -> int | None:
        raw_value = self.recipe.metadata.get("measurement_max_rows_per_file")
        if raw_value is None:
            return self.DEFAULT_MEASUREMENT_MAX_ROWS_PER_FILE
        try:
            parsed = int(raw_value)
        except (TypeError, ValueError):
            return self.DEFAULT_MEASUREMENT_MAX_ROWS_PER_FILE
        if parsed <= 0:
            return None
        return parsed

    def _summarize_measurement_files(self, measurement_names: tuple[str, ...]) -> str:
        if not measurement_names:
            return ""
        if len(measurement_names) == 1:
            return measurement_names[0]
        return f"{measurement_names[0]} (+{len(measurement_names) - 1} more)"

    def _write_manifest_atomic(self, manifest: dict[str, Any]) -> None:
        temp_path = self.manifest_path.with_suffix(f"{self.manifest_path.suffix}.tmp")
        temp_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temp_path, self.manifest_path)
