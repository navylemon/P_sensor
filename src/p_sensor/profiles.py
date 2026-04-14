from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from p_sensor.config import APP_ROOT, DEFAULT_CONFIG_PATH


@dataclass(frozen=True, slots=True)
class AppProfile:
    profile_id: str
    application_name: str
    window_title: str
    config_path: Path
    supports_analog_output: bool
    default_input_channel_count: int
    default_output_channel_count: int


IO_APP_PROFILE = AppProfile(
    profile_id="io_console",
    application_name="P_sensor",
    window_title="P_sensor IO Console",
    config_path=DEFAULT_CONFIG_PATH,
    supports_analog_output=True,
    default_input_channel_count=2,
    default_output_channel_count=2,
)


AI_MONITOR_PROFILE = AppProfile(
    profile_id="ai_monitor",
    application_name="P_sensor_AI",
    window_title="P_sensor AI Monitor",
    config_path=APP_ROOT / "config" / "channel_settings_ai_only.example.json",
    supports_analog_output=False,
    default_input_channel_count=2,
    default_output_channel_count=0,
)
