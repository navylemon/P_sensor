from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class SamplingConfig:
    acquisition_hz: float = 20.0
    display_update_hz: float = 10.0
    history_seconds: int = 180
    mode: str = "continuous"


@dataclass(slots=True)
class AnalogInputChannelConfig:
    enabled: bool
    name: str
    physical_channel: str
    scale: float = 1.0
    offset: float = 0.0
    engineering_unit: str = "V"
    color: str = "#3A7CA5"
    bridge_type: str = "quarter_bridge"
    excitation_voltage: float = 5.0
    nominal_resistance_ohm: float = 350.0
    zero_offset: float = 0.0
    calibration_scale: float = 1.0


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

    @property
    def channels(self) -> list[AnalogInputChannelConfig]:
        return self.ai_channels

    @channels.setter
    def channels(self, value: list[AnalogInputChannelConfig]) -> None:
        self.ai_channels = value


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


@dataclass(slots=True)
class ChannelReading:
    channel_index: int
    channel_name: str
    voltage: float
    resistance_ohm: float
    status: str = "ok"


@dataclass(slots=True)
class MeasurementSample:
    timestamp: datetime
    elapsed_s: float
    readings: list[ChannelReading]

    @property
    def inputs(self) -> list[AnalogInputReading]:
        return [
            AnalogInputReading(
                channel_index=reading.channel_index,
                channel_name=reading.channel_name,
                voltage=reading.voltage,
                scaled_value=reading.resistance_ohm,
                unit="ohm",
                status=reading.status,
            )
            for reading in self.readings
        ]

    @property
    def outputs(self) -> list[AnalogOutputState]:
        return []
