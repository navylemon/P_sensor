from __future__ import annotations

import math
import random
from datetime import datetime

from p_sensor.acquisition.base import BackendError, MeasurementBackend
from p_sensor.calculations import reading_status, resistance_to_voltage
from p_sensor.models import AppConfig, ChannelReading, MeasurementSample


class SimulatedBackend(MeasurementBackend):
    def __init__(self, config: AppConfig) -> None:
        super().__init__(config)
        self._connected = False

    def connect(self) -> str:
        self._connected = True
        channel_count = len([channel for channel in self.config.channels if channel.enabled])
        return f"Simulation backend ready ({channel_count} active channels)"

    def disconnect(self) -> None:
        self._connected = False

    def read(self, elapsed_s: float) -> MeasurementSample:
        if not self._connected:
            raise BackendError("Simulation backend is not connected.")

        readings: list[ChannelReading] = []

        for index, channel in enumerate(self.config.channels):
            if not channel.enabled:
                continue

            harmonic = math.sin(elapsed_s * 0.7 + index * 0.35)
            drift = math.sin(elapsed_s * 0.07 + index) * 0.6
            noise = random.uniform(-0.08, 0.08)
            delta_r = harmonic * 2.5 + drift + noise
            resistance = (
                channel.nominal_resistance_ohm
                + (delta_r * channel.calibration_scale)
                + channel.zero_offset
            )
            voltage = resistance_to_voltage(resistance, channel)
            status = reading_status(resistance, channel)

            readings.append(
                ChannelReading(
                    channel_index=index,
                    channel_name=channel.name,
                    voltage=voltage,
                    resistance_ohm=resistance,
                    status=status,
                )
            )

        return MeasurementSample(
            timestamp=datetime.now(),
            elapsed_s=elapsed_s,
            readings=readings,
        )
