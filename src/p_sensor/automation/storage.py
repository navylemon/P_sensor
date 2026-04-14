from __future__ import annotations

import csv
import json
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


class AutomationSessionStore:
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

    def close(self) -> None:
        if not self._summary_file.closed:
            self._summary_file.flush()
            self._summary_file.close()

    def write_manifest(self, *, extra_metadata: dict[str, Any] | None = None) -> Path:
        manifest = {
            "session_id": self.session_id,
            "session_label": normalize_session_label(self.options.session_label),
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "export_directory": str(self.export_root),
            "recipe": {
                "recipe_id": self.recipe.recipe_id,
                "steps": [asdict(step) for step in self.recipe.steps],
                "metadata": self.recipe.metadata,
            },
            "config": config_to_dict(self.config),
            "session_metadata": self.options.metadata,
        }
        if extra_metadata:
            manifest["runtime_metadata"] = extra_metadata
        self.manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        return self.manifest_path

    def write_measurement_window(
        self,
        *,
        step_index: int,
        window_result: MeasurementWindowResult,
    ) -> Path:
        file_name = f"measurement_{step_index:04d}.csv"
        file_path = self.session_dir / file_name
        recorder = CsvRecorder()
        recorder.start(file_path, self.config.ai_channels, self.config.ao_channels)
        try:
            for frame in window_result.frames:
                recorder.append(frame)
        finally:
            recorder.stop()
        return file_path

    def append_step_result(
        self,
        *,
        step_index: int,
        step: AutomationStep,
        measurement_path: Path,
        window_result: MeasurementWindowResult,
        status: str = "completed",
    ) -> AutomationStepResult:
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
        result = AutomationStepResult(
            step_index=step_index,
            step_id=step.step_id,
            target_displacement=step.target_displacement,
            measurement_file=measurement_path.name,
            started_at=window_result.started_at,
            ended_at=window_result.ended_at,
            frame_count=window_result.frame_count,
            average_inputs=average_inputs,
            average_outputs=average_outputs,
            status=status,
            notes=step.notes,
        )
        self._summary_writer.writerow(self._build_summary_row(result))
        self._summary_file.flush()
        self._step_results.append(result)
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
            "measurement_file",
            "started_at",
            "ended_at",
            "frame_count",
            "status",
            "notes",
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
            result.measurement_file,
            result.started_at.isoformat(timespec="milliseconds"),
            result.ended_at.isoformat(timespec="milliseconds"),
            str(result.frame_count),
            result.status,
            result.notes,
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
