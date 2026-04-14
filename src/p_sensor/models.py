from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SamplingConfig:
    acquisition_hz: float = 10.0
    display_update_hz: float = 10.0
    mode: str = "continuous"
    history_seconds: int = 300


@dataclass(slots=True)
class ChannelConfig:
    enabled: bool
    name: str
    physical_channel: str
    bridge_type: str
    excitation_voltage: float
    nominal_resistance_ohm: float
    bridge_reference_resistance_ohm: float
    zero_offset: float = 0.0
    calibration_scale: float = 1.0
    color: str = "#3A7CA5"


@dataclass(slots=True)
class AppConfig:
    backend: str = "simulation"
    ni_device_name: str = "cDAQ1"
    export_directory: str = "dev_local/exports"
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    channels: list[ChannelConfig] = field(default_factory=list)


@dataclass(slots=True)
class ChannelReading:
    channel_index: int
    channel_name: str
    voltage: float
    resistance_ohm: float
    unit: str = "ohm"
    status: str = "normal"


@dataclass(slots=True)
class MeasurementSample:
    timestamp: datetime
    elapsed_s: float
    readings: list[ChannelReading]
