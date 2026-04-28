from __future__ import annotations

import math
import random
from datetime import datetime

from p_sensor.acquisition.base import BackendError, MeasurementBackend
from p_sensor.calculations import compute_input_reading, resistance_to_voltage
from p_sensor.models import AnalogInputReading, AnalogOutputState, MeasurementFrame


class SimulatedBackend(MeasurementBackend):
    def __init__(self, config) -> None:
        super().__init__(config)
        self._connected = False
        self._output_currents_ma = {
            index: channel.initial_current_ma for index, channel in enumerate(self.config.ao_channels)
        }

    def connect(self) -> str:
        self._connected = True
        self.write_output_currents(
            {
                index: channel.initial_current_ma
                for index, channel in enumerate(self.config.ao_channels)
                if channel.enabled
            }
        )
        active_inputs = len([channel for channel in self.config.ai_channels if channel.enabled])
        active_outputs = len([channel for channel in self.config.ao_channels if channel.enabled])
        return f"Simulation backend ready ({active_inputs} AI / {active_outputs} AO)"

    def disconnect(self) -> None:
        self._connected = False

    def read(self, elapsed_s: float) -> MeasurementFrame:
        if not self._connected:
            raise BackendError("Simulation backend is not connected.")

        enabled_outputs = [index for index, channel in enumerate(self.config.ao_channels) if channel.enabled]
        average_output_ma = 0.0
        if enabled_outputs:
            average_output_ma = sum(self._output_currents_ma.get(index, 0.0) for index in enabled_outputs) / len(
                enabled_outputs
            )

        inputs: list[AnalogInputReading] = []
        for index, channel in enumerate(self.config.ai_channels):
            if not channel.enabled:
                continue

            harmonic = math.sin(elapsed_s * 0.9 + index * 0.45)
            drift = math.sin(elapsed_s * 0.11 + index) * 0.2
            coupling = average_output_ma * 0.08
            noise = random.uniform(-0.03, 0.03)
            if channel.measurement_mode == "voltage":
                voltage = (harmonic * 0.8) + (drift * 0.15) + (average_output_ma * 0.025) + (noise * 0.5)
            else:
                resistance = channel.nominal_resistance_ohm + harmonic + drift + coupling + noise
                voltage = resistance_to_voltage(resistance, channel)

            inputs.append(
                compute_input_reading(
                    channel_index=index,
                    channel=channel,
                    voltage=voltage,
                )
            )

        return MeasurementFrame(
            timestamp=datetime.now(),
            elapsed_s=elapsed_s,
            inputs=inputs,
            outputs=self._build_output_states(),
        )

    def write_output_currents(self, currents_ma: dict[int, float]) -> list[AnalogOutputState]:
        if not self._connected:
            raise BackendError("Simulation backend is not connected.")

        for index, channel in enumerate(self.config.ao_channels):
            target_value = currents_ma.get(index, self._output_currents_ma.get(index, channel.initial_current_ma))
            clamped = max(channel.min_current_ma, min(channel.max_current_ma, float(target_value)))
            self._output_currents_ma[index] = clamped

        return self._build_output_states()

    def _build_output_states(self) -> list[AnalogOutputState]:
        return [
            AnalogOutputState(
                channel_index=index,
                channel_name=channel.name,
                current_ma=self._output_currents_ma.get(index, 0.0),
            )
            for index, channel in enumerate(self.config.ao_channels)
        ]
