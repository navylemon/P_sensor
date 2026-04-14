from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from pathlib import Path

from p_sensor.models import AppConfig, ChannelConfig, SamplingConfig


DEFAULT_COLORS = [
    "#3A7CA5",
    "#E63946",
    "#2A9D8F",
    "#F4A261",
    "#6D597A",
    "#457B9D",
    "#8D6A9F",
    "#BC6C25",
    "#1D3557",
    "#E76F51",
    "#118AB2",
    "#06D6A0",
    "#EF476F",
    "#FFD166",
    "#8338EC",
    "#3D5A80",
]

DEFAULT_NI_DEVICE_NAME = "cDAQ1"
DEFAULT_EXPORT_DIRECTORY = "dev_local/exports"
SUPPORTED_BACKENDS = {"simulation", "ni"}
SUPPORTED_BRIDGE_TYPES = {"quarter_bridge", "half_bridge", "full_bridge"}
PROJECT_LOCAL_ANCHORS = ("config", "dev_local", "docs", "scripts", "src", "tests")

_PHYSICAL_CHANNEL_PATTERN = re.compile(
    r"(?P<device>[A-Za-z0-9_]+)(?:/)?Mod(?P<module>\d+)/ai(?P<port>\d+)$",
    re.IGNORECASE,
)
_GENERIC_AI_PATTERN = re.compile(r"/ai(?P<port>\d+)$", re.IGNORECASE)


def _looks_like_project_root(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "src").exists()


def _iter_candidate_roots(path: Path) -> tuple[Path, ...]:
    resolved = path.resolve(strict=False)
    anchor = resolved.parent if resolved.suffix else resolved
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


def validate_app_config(config: AppConfig) -> AppConfig:
    if config.backend not in SUPPORTED_BACKENDS:
        raise ValueError(f"Unsupported backend: {config.backend}")
    if config.sampling.acquisition_hz <= 0:
        raise ValueError("Acquisition Hz must be greater than 0.")
    if config.sampling.display_update_hz <= 0:
        raise ValueError("Display Hz must be greater than 0.")
    if config.sampling.history_seconds <= 0:
        raise ValueError("History seconds must be greater than 0.")
    if not config.export_directory.strip():
        raise ValueError("Export directory must not be empty.")

    for index, channel in enumerate(config.channels, start=1):
        if not channel.name.strip():
            raise ValueError(f"Channel {index} name must not be empty.")
        if not channel.physical_channel.strip():
            raise ValueError(f"Channel {index} physical channel must not be empty.")
        if channel.bridge_type not in SUPPORTED_BRIDGE_TYPES:
            raise ValueError(
                f"Channel {index} bridge type must be one of: {', '.join(sorted(SUPPORTED_BRIDGE_TYPES))}."
            )
        if channel.excitation_voltage <= 0:
            raise ValueError(f"Channel {index} excitation voltage must be greater than 0.")
        if channel.nominal_resistance_ohm <= 0:
            raise ValueError(f"Channel {index} nominal resistance must be greater than 0.")
        if channel.calibration_scale == 0:
            raise ValueError(f"Channel {index} calibration scale must not be 0.")

    return config


def build_physical_channel(module_number: int, sensor_port: int) -> str:
    if module_number < 1:
        raise ValueError("Module number must be 1 or higher.")
    if sensor_port < 1:
        raise ValueError("Sensor port must be 1 or higher.")
    return f"{DEFAULT_NI_DEVICE_NAME}Mod{module_number}/ai{sensor_port - 1}"


def channel_selection_from_physical_channel(physical_channel: str, fallback_index: int = 0) -> tuple[int, int]:
    match = _PHYSICAL_CHANNEL_PATTERN.search(physical_channel.strip())
    if match:
        return int(match.group("module")), int(match.group("port")) + 1

    generic_match = _GENERIC_AI_PATTERN.search(physical_channel.strip())
    fallback_module = (fallback_index // 4) + 1
    fallback_port = (fallback_index % 4) + 1
    if generic_match:
        return fallback_module, int(generic_match.group("port")) + 1

    return fallback_module, fallback_port


def build_channel_name(module_number: int, sensor_port: int) -> str:
    return f"Module {module_number} Port {sensor_port}"


def normalize_physical_channel(
    physical_channel: str,
    fallback_index: int = 0,
    *,
    use_slotted_module_path: bool = False,
) -> str:
    module_number, sensor_port = channel_selection_from_physical_channel(physical_channel, fallback_index)
    if use_slotted_module_path:
        return f"{DEFAULT_NI_DEVICE_NAME}/Mod{module_number}/ai{sensor_port - 1}"
    return build_physical_channel(module_number, sensor_port)


def default_app_config(channel_count: int = 8) -> AppConfig:
    channels: list[ChannelConfig] = []
    for index in range(channel_count):
        module_number = (index // 4) + 1
        sensor_port = (index % 4) + 1
        channels.append(
            ChannelConfig(
                enabled=True,
                name=build_channel_name(module_number, sensor_port),
                physical_channel=build_physical_channel(module_number, sensor_port),
                bridge_type="quarter_bridge",
                excitation_voltage=5.0,
                nominal_resistance_ohm=350.0,
                zero_offset=0.0,
                calibration_scale=1.0,
                color=DEFAULT_COLORS[index % len(DEFAULT_COLORS)],
            )
        )

    return validate_app_config(
        AppConfig(
            backend="simulation",
            export_directory=DEFAULT_EXPORT_DIRECTORY,
            sampling=SamplingConfig(
                acquisition_hz=10.0,
                display_update_hz=10.0,
                mode="continuous",
                history_seconds=300,
            ),
            channels=channels,
        ),
    )


def config_to_dict(config: AppConfig) -> dict:
    return {
        "backend": config.backend,
        "export_directory": config.export_directory,
        "sampling": {
            "acquisition_hz": config.sampling.acquisition_hz,
            "display_update_hz": config.sampling.display_update_hz,
            "mode": config.sampling.mode,
            "history_seconds": config.sampling.history_seconds,
        },
        "channels": [
            {
                "enabled": channel.enabled,
                "name": channel.name,
                "physical_channel": channel.physical_channel,
                "bridge_type": channel.bridge_type,
                "excitation_voltage": channel.excitation_voltage,
                "nominal_resistance_ohm": channel.nominal_resistance_ohm,
                "zero_offset": channel.zero_offset,
                "calibration_scale": channel.calibration_scale,
                "color": channel.color,
            }
            for channel in config.channels
        ],
    }


def load_config(path: str | Path) -> AppConfig:
    config_path = resolve_runtime_path(path)
    data = json.loads(config_path.read_text(encoding="utf-8"))

    sampling_data = data.get("sampling", {})
    sampling = SamplingConfig(
        acquisition_hz=float(sampling_data.get("acquisition_hz", 10.0)),
        display_update_hz=float(sampling_data.get("display_update_hz", 10.0)),
        mode=str(sampling_data.get("mode", "continuous")),
        history_seconds=int(sampling_data.get("history_seconds", 300)),
    )

    channels = [
        ChannelConfig(
            enabled=bool(item.get("enabled", True)),
            name=str(item.get("name", f"Sensor {index + 1:02d}")),
            physical_channel=str(item.get("physical_channel", f"Dev1/ai{index}")),
            bridge_type=str(item.get("bridge_type", "quarter_bridge")),
            excitation_voltage=float(item.get("excitation_voltage", 5.0)),
            nominal_resistance_ohm=float(item.get("nominal_resistance_ohm", 350.0)),
            zero_offset=float(item.get("zero_offset", 0.0)),
            calibration_scale=float(item.get("calibration_scale", 1.0)),
            color=str(item.get("color", DEFAULT_COLORS[index % len(DEFAULT_COLORS)])),
        )
        for index, item in enumerate(data.get("channels", []))
    ]

    return validate_app_config(
        AppConfig(
            backend=str(data.get("backend", "simulation")),
            export_directory=normalize_runtime_path_value(
                str(data.get("export_directory", DEFAULT_EXPORT_DIRECTORY))
            ),
            sampling=sampling,
            channels=channels,
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
