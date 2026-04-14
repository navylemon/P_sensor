from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from p_sensor.models import (
    AnalogInputChannelConfig,
    AnalogOutputChannelConfig,
    AppConfig,
    SamplingConfig,
)


DEFAULT_COLORS = ["#3A7CA5", "#E63946", "#2A9D8F", "#F4A261"]
DEFAULT_CHASSIS_NAME = "cDAQ1"
DEFAULT_EXPORT_DIRECTORY = "dev_local/exports"
DEFAULT_AI_MODULE_SLOT = 1
DEFAULT_AO_MODULE_SLOT = 2
SUPPORTED_BACKENDS = {"simulation", "ni"}
MAX_CDAQ_9174_SLOTS = 4
PROJECT_LOCAL_ANCHORS = ("config", "dev_local", "docs", "scripts", "src", "tests")

_PHYSICAL_CHANNEL_PATTERN = re.compile(
    r"(?P<device>[A-Za-z0-9_-]+)(?:/)?Mod(?P<slot>\d+)/(?P<kind>ai|ao)(?P<port>\d+)$",
    re.IGNORECASE,
)
_GENERIC_CHANNEL_PATTERN = re.compile(r"/(?P<kind>ai|ao)(?P<port>\d+)$", re.IGNORECASE)


def _looks_like_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "src").exists()


def _iter_candidate_roots(path: Path) -> tuple[Path, ...]:
    resolved = path.resolve(strict=False)
    anchor = resolved
    if (resolved.exists() and resolved.is_file()) or (not resolved.exists() and resolved.suffix):
        anchor = resolved.parent
    return (anchor, *anchor.parents)


def resolve_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    module_root = Path(__file__).resolve().parents[2]
    candidates = [module_root, Path.cwd()]
    visited: set[Path] = set()

    for candidate in candidates:
        for base in _iter_candidate_roots(candidate):
            resolved = base.resolve(strict=False)
            if resolved in visited:
                continue
            visited.add(resolved)
            if _looks_like_project_root(resolved):
                return resolved

    return module_root


APP_ROOT = resolve_app_root()
DEFAULT_CONFIG_PATH = APP_ROOT / "config" / "channel_settings.example.json"


def resolve_base_path(base_path: str | Path | None = None) -> Path:
    if base_path is None:
        return APP_ROOT

    candidate = Path(base_path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)

    return (APP_ROOT / candidate).resolve(strict=False)


def _rebase_missing_project_path(candidate: Path, *, base_path: str | Path | None = None) -> Path | None:
    parts = [part for part in candidate.parts if part not in {candidate.anchor, ""}]
    lower_parts = [part.lower() for part in parts]
    resolved_base = resolve_base_path(base_path)

    for anchor in PROJECT_LOCAL_ANCHORS:
        if anchor not in lower_parts:
            continue
        anchor_index = lower_parts.index(anchor)
        return resolved_base / Path(*parts[anchor_index:])

    return None


def resolve_runtime_path(path: str | Path, *, base_path: str | Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        resolved = candidate.resolve(strict=False)
        if resolved.exists():
            return resolved
        rebased = _rebase_missing_project_path(resolved, base_path=base_path)
        return rebased.resolve(strict=False) if rebased is not None else resolved

    resolved_base = resolve_base_path(base_path)
    return (resolved_base / candidate).resolve(strict=False)


def normalize_runtime_path_value(path: str | Path, *, base_path: str | Path | None = None) -> str:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        return Path(*candidate.parts).as_posix() if candidate.parts else str(candidate)

    resolved = resolve_runtime_path(candidate, base_path=base_path)
    resolved_base = resolve_base_path(base_path)
    try:
        return resolved.relative_to(resolved_base).as_posix()
    except ValueError:
        return str(resolved)


def build_physical_channel(
    module_slot: int,
    channel_port: int,
    *,
    channel_kind: str,
    chassis_name: str = DEFAULT_CHASSIS_NAME,
) -> str:
    if module_slot < 1 or module_slot > MAX_CDAQ_9174_SLOTS:
        raise ValueError(f"Module slot must be between 1 and {MAX_CDAQ_9174_SLOTS}.")
    if channel_port < 0:
        raise ValueError("Channel port must be 0 or higher.")
    if channel_kind not in {"ai", "ao"}:
        raise ValueError(f"Unsupported channel kind: {channel_kind}")
    cleaned_chassis_name = chassis_name.strip() or DEFAULT_CHASSIS_NAME
    return f"{cleaned_chassis_name}Mod{module_slot}/{channel_kind}{channel_port}"


def channel_selection_from_physical_channel(
    physical_channel: str,
    *,
    fallback_slot: int,
    fallback_port: int,
    expected_kind: str,
) -> tuple[int, int]:
    match = _PHYSICAL_CHANNEL_PATTERN.search(physical_channel.strip())
    if match and match.group("kind").lower() == expected_kind:
        return int(match.group("slot")), int(match.group("port"))

    generic_match = _GENERIC_CHANNEL_PATTERN.search(physical_channel.strip())
    if generic_match and generic_match.group("kind").lower() == expected_kind:
        return fallback_slot, int(generic_match.group("port"))

    return fallback_slot, fallback_port


def normalize_physical_channel(
    physical_channel: str,
    *,
    fallback_slot: int,
    fallback_port: int,
    expected_kind: str,
    chassis_name: str = DEFAULT_CHASSIS_NAME,
    use_slotted_module_path: bool = False,
) -> str:
    module_slot, channel_port = channel_selection_from_physical_channel(
        physical_channel,
        fallback_slot=fallback_slot,
        fallback_port=fallback_port,
        expected_kind=expected_kind,
    )
    cleaned_chassis_name = chassis_name.strip() or DEFAULT_CHASSIS_NAME
    if use_slotted_module_path:
        return f"{cleaned_chassis_name}/Mod{module_slot}/{expected_kind}{channel_port}"
    return build_physical_channel(
        module_slot,
        channel_port,
        channel_kind=expected_kind,
        chassis_name=cleaned_chassis_name,
    )


def infer_chassis_name(channels_data: list[dict], default_chassis_name: str = DEFAULT_CHASSIS_NAME) -> str:
    for item in channels_data:
        physical_channel = str(item.get("physical_channel", "")).strip()
        match = _PHYSICAL_CHANNEL_PATTERN.search(physical_channel)
        if match:
            return match.group("device")
    return default_chassis_name


def validate_app_config(config: AppConfig) -> AppConfig:
    if config.backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported backend: {config.backend}")
    if not config.chassis_name.strip():
        raise ValueError("Chassis name must not be empty.")
    if config.ai_module_slot < 1 or config.ai_module_slot > MAX_CDAQ_9174_SLOTS:
        raise ValueError(f"AI module slot must be between 1 and {MAX_CDAQ_9174_SLOTS}.")
    if config.ao_module_slot < 1 or config.ao_module_slot > MAX_CDAQ_9174_SLOTS:
        raise ValueError(f"AO module slot must be between 1 and {MAX_CDAQ_9174_SLOTS}.")
    if config.ai_module_slot == config.ao_module_slot:
        raise ValueError("AI and AO modules cannot use the same chassis slot.")
    if config.sampling.acquisition_hz <= 0:
        raise ValueError("Acquisition Hz must be greater than 0.")
    if config.sampling.display_update_hz <= 0:
        raise ValueError("Display Hz must be greater than 0.")
    if config.sampling.history_seconds <= 0:
        raise ValueError("History seconds must be greater than 0.")
    if not config.export_directory.strip():
        raise ValueError("Export directory must not be empty.")
    if not config.ai_channels:
        raise ValueError("At least one analog input channel must exist.")
    if not any(channel.enabled for channel in config.ai_channels):
        raise ValueError("At least one analog input channel must be enabled.")

    for index, channel in enumerate(config.ai_channels, start=1):
        if not channel.name.strip():
            raise ValueError(f"AI channel {index} name must not be empty.")
        if not channel.physical_channel.strip():
            raise ValueError(f"AI channel {index} physical channel must not be empty.")
        if not channel.engineering_unit.strip():
            raise ValueError(f"AI channel {index} engineering unit must not be empty.")

    for index, channel in enumerate(config.ao_channels, start=1):
        if not channel.name.strip():
            raise ValueError(f"AO channel {index} name must not be empty.")
        if not channel.physical_channel.strip():
            raise ValueError(f"AO channel {index} physical channel must not be empty.")
        if channel.min_current_ma >= channel.max_current_ma:
            raise ValueError(f"AO channel {index} current range is invalid.")
        if not (channel.min_current_ma <= channel.initial_current_ma <= channel.max_current_ma):
            raise ValueError(f"AO channel {index} initial current must stay inside its current range.")

    return config


def default_app_config(input_channel_count: int = 2, output_channel_count: int = 2) -> AppConfig:
    ai_channels = [
        AnalogInputChannelConfig(
            enabled=True,
            name=f"AI {index + 1}",
            physical_channel=build_physical_channel(
                DEFAULT_AI_MODULE_SLOT,
                index,
                channel_kind="ai",
                chassis_name=DEFAULT_CHASSIS_NAME,
            ),
            scale=1.0,
            offset=0.0,
            engineering_unit="V",
            color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
        )
        for index in range(input_channel_count)
    ]
    ao_channels = [
        AnalogOutputChannelConfig(
            enabled=True,
            name=f"AO {index + 1}",
            physical_channel=build_physical_channel(
                DEFAULT_AO_MODULE_SLOT,
                index,
                channel_kind="ao",
                chassis_name=DEFAULT_CHASSIS_NAME,
            ),
            min_current_ma=0.0,
            max_current_ma=20.0,
            initial_current_ma=0.0,
        )
        for index in range(output_channel_count)
    ]

    return validate_app_config(
        AppConfig(
            backend="simulation",
            chassis_name=DEFAULT_CHASSIS_NAME,
            ai_module_slot=DEFAULT_AI_MODULE_SLOT,
            ao_module_slot=DEFAULT_AO_MODULE_SLOT,
            export_directory=DEFAULT_EXPORT_DIRECTORY,
            sampling=SamplingConfig(acquisition_hz=20.0, display_update_hz=10.0, history_seconds=180),
            ai_channels=ai_channels,
            ao_channels=ao_channels,
        )
    )


def config_to_dict(config: AppConfig) -> dict:
    return {
        "backend": config.backend,
        "chassis_name": config.chassis_name,
        "ai_module_slot": config.ai_module_slot,
        "ao_module_slot": config.ao_module_slot,
        "export_directory": config.export_directory,
        "sampling": {
            "acquisition_hz": config.sampling.acquisition_hz,
            "display_update_hz": config.sampling.display_update_hz,
            "history_seconds": config.sampling.history_seconds,
        },
        "ai_channels": [
            {
                "enabled": channel.enabled,
                "name": channel.name,
                "physical_channel": channel.physical_channel,
                "scale": channel.scale,
                "offset": channel.offset,
                "engineering_unit": channel.engineering_unit,
                "color": channel.color,
            }
            for channel in config.ai_channels
        ],
        "ao_channels": [
            {
                "enabled": channel.enabled,
                "name": channel.name,
                "physical_channel": channel.physical_channel,
                "min_current_ma": channel.min_current_ma,
                "max_current_ma": channel.max_current_ma,
                "initial_current_ma": channel.initial_current_ma,
            }
            for channel in config.ao_channels
        ],
    }


def load_config(path: str | Path) -> AppConfig:
    config_path = resolve_runtime_path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))
    ai_channels_data = list(data.get("ai_channels", []))
    ao_channels_data = list(data.get("ao_channels", []))
    chassis_name = (
        str(data.get("chassis_name", "")).strip()
        or infer_chassis_name(ai_channels_data)
        or infer_chassis_name(ao_channels_data)
    )
    if not chassis_name:
        chassis_name = DEFAULT_CHASSIS_NAME

    ai_module_slot = int(data.get("ai_module_slot", DEFAULT_AI_MODULE_SLOT))
    ao_module_slot = int(data.get("ao_module_slot", DEFAULT_AO_MODULE_SLOT))
    sampling_data = data.get("sampling", {})
    sampling = SamplingConfig(
        acquisition_hz=float(sampling_data.get("acquisition_hz", 20.0)),
        display_update_hz=float(sampling_data.get("display_update_hz", 10.0)),
        history_seconds=int(sampling_data.get("history_seconds", 180)),
    )

    ai_channels = [
        AnalogInputChannelConfig(
            enabled=bool(item.get("enabled", True)),
            name=str(item.get("name", f"AI {index + 1}")),
            physical_channel=str(
                item.get(
                    "physical_channel",
                    build_physical_channel(
                        ai_module_slot,
                        index,
                        channel_kind="ai",
                        chassis_name=chassis_name,
                    ),
                )
            ),
            scale=float(item.get("scale", 1.0)),
            offset=float(item.get("offset", 0.0)),
            engineering_unit=str(item.get("engineering_unit", "V")),
            color=str(item.get("color", DEFAULT_COLORS[index % len(DEFAULT_COLORS)])),
        )
        for index, item in enumerate(ai_channels_data)
    ]
    if not ai_channels:
        ai_channels = default_app_config().ai_channels

    ao_channels = [
        AnalogOutputChannelConfig(
            enabled=bool(item.get("enabled", True)),
            name=str(item.get("name", f"AO {index + 1}")),
            physical_channel=str(
                item.get(
                    "physical_channel",
                    build_physical_channel(
                        ao_module_slot,
                        index,
                        channel_kind="ao",
                        chassis_name=chassis_name,
                    ),
                )
            ),
            min_current_ma=float(item.get("min_current_ma", 0.0)),
            max_current_ma=float(item.get("max_current_ma", 20.0)),
            initial_current_ma=float(item.get("initial_current_ma", 0.0)),
        )
        for index, item in enumerate(ao_channels_data)
    ]
    if not ao_channels:
        ao_channels = default_app_config().ao_channels

    return validate_app_config(
        AppConfig(
            backend=str(data.get("backend", "simulation")),
            chassis_name=chassis_name,
            ai_module_slot=ai_module_slot,
            ao_module_slot=ao_module_slot,
            export_directory=normalize_runtime_path_value(
                str(data.get("export_directory", DEFAULT_EXPORT_DIRECTORY))
            ),
            sampling=sampling,
            ai_channels=ai_channels,
            ao_channels=ao_channels,
        )
    )


def save_config(path: str | Path, config: AppConfig) -> None:
    validate_app_config(config)
    config_path = resolve_runtime_path(path)
    payload = config_to_dict(config)
    payload["export_directory"] = normalize_runtime_path_value(config.export_directory)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            delete=False,
            dir=config_path.parent,
            prefix=f"{config_path.stem}_",
            suffix=".tmp",
            encoding="utf-8",
        ) as temp_file:
            temp_file.write(serialized)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, config_path)
    except Exception as exc:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink(missing_ok=True)
        raise OSError(f"Failed to save config to {config_path}: {exc}") from exc
