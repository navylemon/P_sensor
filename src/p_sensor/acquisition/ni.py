from __future__ import annotations

from datetime import datetime

from p_sensor.acquisition.base import BackendError, MeasurementBackend
from p_sensor.calculations import reading_status, voltage_to_resistance
from p_sensor.config import normalize_physical_channel
from p_sensor.models import ChannelReading, MeasurementSample


class NiDaqBackend(MeasurementBackend):
    MIN_9234_RATE_HZ = 1652.0

    def __init__(self, config) -> None:
        super().__init__(config)
        self._task = None
        self._hardware_rate_hz = max(config.sampling.acquisition_hz, self.MIN_9234_RATE_HZ)
        self._samples_per_read = max(1, int(round(self._hardware_rate_hz / config.sampling.acquisition_hz)))

    def connect(self) -> str:
        self.disconnect()

        try:
            import nidaqmx
            from nidaqmx.constants import AcquisitionType, Coupling, ExcitationSource, TerminalConfiguration
            from nidaqmx.system import System
        except ImportError as exc:  # pragma: no cover - depends on external install
            raise BackendError(
                "Failed to import nidaqmx. Use the simulation backend or install the NI Python package. "
                f"Import error: {exc}"
            ) from exc

        active_channels = [channel for channel in self.config.channels if channel.enabled]
        if not active_channels:
            raise BackendError("No active channels are enabled.")

        available_device_names = {device.name for device in System.local().devices}
        attempted_channels: list[str] = []

        try:
            self._task = nidaqmx.Task()
            for channel_index, channel in enumerate(active_channels):
                compact_channel = normalize_physical_channel(
                    channel.physical_channel,
                    channel_index,
                    device_name=self.config.ni_device_name,
                )
                slotted_channel = normalize_physical_channel(
                    channel.physical_channel,
                    channel_index,
                    device_name=self.config.ni_device_name,
                    use_slotted_module_path=True,
                )
                module_device_name = compact_channel.split("/", 1)[0]
                physical_channel = (
                    compact_channel if module_device_name in available_device_names else slotted_channel
                )
                attempted_channels.append(physical_channel)
                ai_channel = self._task.ai_channels.add_ai_voltage_chan(
                    physical_channel,
                    terminal_config=TerminalConfiguration.PSEUDO_DIFF,
                    min_val=-5.0,
                    max_val=5.0,
                )
                ai_channel.ai_term_cfg = TerminalConfiguration.PSEUDO_DIFF
                ai_channel.ai_coupling = Coupling.DC
                ai_channel.ai_excit_src = ExcitationSource.NONE

            self._task.timing.cfg_samp_clk_timing(
                rate=self._hardware_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=max(self._samples_per_read * 5, 10),
            )
        except Exception as exc:  # pragma: no cover - depends on external hardware
            self.disconnect()
            attempted_text = ", ".join(attempted_channels) if attempted_channels else "none"
            raise BackendError(
                f"Failed to initialize NI task: {exc}\nAttempted channels: {attempted_text}"
            ) from exc

        return (
            f"NI backend ready ({len(active_channels)} active channels, "
            f"device={self.config.ni_device_name}, "
            f"hardware_rate={self._hardware_rate_hz:.1f} Hz, "
            f"samples/read={self._samples_per_read})"
        )

    def disconnect(self) -> None:
        if self._task is not None:
            try:
                self._task.close()
            finally:
                self._task = None

    def read(self, elapsed_s: float) -> MeasurementSample:
        if self._task is None:
            raise BackendError("NI task is not connected.")

        try:
            raw_values = self._task.read(
                number_of_samples_per_channel=self._samples_per_read,
                timeout=5.0,
            )
        except Exception as exc:  # pragma: no cover - depends on external hardware
            raise BackendError(f"Failed to read NI samples: {exc}") from exc

        averaged = self._average_channel_values(raw_values)
        active_indices = [index for index, channel in enumerate(self.config.channels) if channel.enabled]
        if len(averaged) != len(active_indices):
            raise BackendError(
                f"NI read returned {len(averaged)} channel values for {len(active_indices)} active channels."
            )

        readings: list[ChannelReading] = []
        for value_index, channel_index in enumerate(active_indices):
            channel = self.config.channels[channel_index]
            voltage = averaged[value_index]
            resistance = voltage_to_resistance(voltage, channel)
            readings.append(
                ChannelReading(
                    channel_index=channel_index,
                    channel_name=channel.name,
                    voltage=voltage,
                    resistance_ohm=resistance,
                    status=reading_status(resistance, channel),
                )
            )

        return MeasurementSample(
            timestamp=datetime.now(),
            elapsed_s=elapsed_s,
            readings=readings,
        )

    def _average_channel_values(self, raw_values) -> list[float]:
        if not isinstance(raw_values, list):
            return [float(raw_values)]

        if not raw_values:
            return []

        if isinstance(raw_values[0], list):
            averaged: list[float] = []
            for channel_values in raw_values:
                if not channel_values:
                    averaged.append(0.0)
                else:
                    averaged.append(sum(float(value) for value in channel_values) / len(channel_values))
            return averaged

        return [sum(float(value) for value in raw_values) / len(raw_values)]
