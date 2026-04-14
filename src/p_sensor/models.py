from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SamplingConfig:
    acquisition_hz: float = 20.0
    display_update_hz: float = 10.0
    history_seconds: int = 180


@dataclass(slots=True)
class AnalogInputChannelConfig:
    enabled: bool
    name: str
    physical_channel: str
    scale: float = 1.0
    offset: float = 0.0
    engineering_unit: str = "V"
    color: str = "#3A7CA5"


@dataclass(slots=True)
class AnalogOutputChannelConfig:
    enabled: bool
    name: str
    physical_channel: str
    min_current_ma: float = 0.0
    max_current_ma: float = 20.0
    initial_current_ma: float = 0.0


@dataclass(slots=True)
class AppConfig:
    backend: str = "simulation"
    chassis_name: str = "cDAQ1"
    ai_module_slot: int = 1
    ao_module_slot: int = 2
    export_directory: str = "dev_local/exports"
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    ai_channels: list[AnalogInputChannelConfig] = field(default_factory=list)
    ao_channels: list[AnalogOutputChannelConfig] = field(default_factory=list)


@dataclass(slots=True)
class AnalogInputReading:
    channel_index: int
    channel_name: str
    voltage: float
    scaled_value: float
    unit: str
    status: str = "ok"


@dataclass(slots=True)
class AnalogOutputState:
    channel_index: int
    channel_name: str
    current_ma: float


@dataclass(slots=True)
class MeasurementFrame:
    timestamp: datetime
    elapsed_s: float
    inputs: list[AnalogInputReading]
    outputs: list[AnalogOutputState]
