from __future__ import annotations

from datetime import datetime

from p_sensor.acquisition.base import BackendError, MeasurementBackend
from p_sensor.config import normalize_physical_channel
from p_sensor.models import AnalogInputReading, AnalogOutputState, MeasurementFrame


class NiDaqBackend(MeasurementBackend):
    MIN_9234_RATE_HZ = 1652.0
    INPUT_BUFFER_SECONDS = 5.0
    INPUT_BUFFER_MIN_READS = 32
    MAX_READ_BATCH_MULTIPLIER = 8

    def __init__(self, config) -> None:
        super().__init__(config)
        self._input_task = None
        self._output_task = None
        self._hardware_rate_hz = max(config.sampling.acquisition_hz, self.MIN_9234_RATE_HZ)
        self._samples_per_read = max(1, int(round(self._hardware_rate_hz / config.sampling.acquisition_hz)))
        self._input_buffer_size = max(
            int(round(self._hardware_rate_hz * self.INPUT_BUFFER_SECONDS)),
            self._samples_per_read * self.INPUT_BUFFER_MIN_READS,
        )
        self._output_currents_ma = {
            index: channel.initial_current_ma for index, channel in enumerate(self.config.ao_channels)
        }

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

        active_inputs = [(index, channel) for index, channel in enumerate(self.config.ai_channels) if channel.enabled]
        active_outputs = [(index, channel) for index, channel in enumerate(self.config.ao_channels) if channel.enabled]
        if not active_inputs:
            raise BackendError("At least one AI channel must be enabled.")

        available_device_names = {device.name for device in System.local().devices}
        attempted_channels: list[str] = []

        try:
            self._input_task = nidaqmx.Task()
            for fallback_port, (channel_index, channel) in enumerate(active_inputs):
                physical_channel = self._resolve_physical_channel(
                    channel.physical_channel,
                    available_device_names=available_device_names,
                    fallback_slot=self.config.ai_module_slot,
                    fallback_port=fallback_port,
                    expected_kind="ai",
                )
                attempted_channels.append(physical_channel)
                ai_channel = self._input_task.ai_channels.add_ai_voltage_chan(
                    physical_channel,
                    terminal_config=TerminalConfiguration.PSEUDO_DIFF,
                    min_val=-5.0,
                    max_val=5.0,
                )
                ai_channel.ai_term_cfg = TerminalConfiguration.PSEUDO_DIFF
                ai_channel.ai_coupling = Coupling.DC
                ai_channel.ai_excit_src = ExcitationSource.NONE

            self._input_task.timing.cfg_samp_clk_timing(
                rate=self._hardware_rate_hz,
                sample_mode=AcquisitionType.CONTINUOUS,
                samps_per_chan=self._input_buffer_size,
            )
            try:
                self._input_task.in_stream.input_buf_size = self._input_buffer_size
            except Exception:
                pass

            if active_outputs:
                self._output_task = nidaqmx.Task()
                for fallback_port, (channel_index, channel) in enumerate(active_outputs):
                    physical_channel = self._resolve_physical_channel(
                        channel.physical_channel,
                        available_device_names=available_device_names,
                        fallback_slot=self.config.ao_module_slot,
                        fallback_port=fallback_port,
                        expected_kind="ao",
                    )
                    attempted_channels.append(physical_channel)
                    self._output_task.ao_channels.add_ao_current_chan(
                        physical_channel,
                        min_val=channel.min_current_ma / 1000.0,
                        max_val=channel.max_current_ma / 1000.0,
                    )

                self.write_output_currents(
                    {
                        index: channel.initial_current_ma
                        for index, channel in enumerate(self.config.ao_channels)
                        if channel.enabled
                    }
                )
        except Exception as exc:  # pragma: no cover - depends on external hardware
            self.disconnect()
            attempted_text = ", ".join(attempted_channels) if attempted_channels else "none"
            raise BackendError(
                f"Failed to initialize NI task: {exc}\nAttempted channels: {attempted_text}"
            ) from exc

        return (
            f"NI backend ready ({len(active_inputs)} AI / {len(active_outputs)} AO, "
            f"chassis={self.config.chassis_name}, "
            f"ai_rate={self._hardware_rate_hz:.1f} Hz, "
            f"samples/read={self._samples_per_read}, "
            f"buffer={self._input_buffer_size})"
        )

    def disconnect(self) -> None:
        for task_name in ("_input_task", "_output_task"):
            task = getattr(self, task_name)
            if task is None:
                continue
            try:
                task.close()
            finally:
                setattr(self, task_name, None)

    def read(self, elapsed_s: float) -> MeasurementFrame:
        if self._input_task is None:
            raise BackendError("NI input task is not connected.")

        samples_to_read = self._resolve_samples_to_read()
        try:
            raw_values = self._input_task.read(
                number_of_samples_per_channel=samples_to_read,
                timeout=5.0,
            )
        except Exception as exc:  # pragma: no cover - depends on external hardware
            raise BackendError(f"Failed to read NI samples: {exc}") from exc

        averaged = self._average_channel_values(raw_values)
        active_inputs = [(index, channel) for index, channel in enumerate(self.config.ai_channels) if channel.enabled]
        if len(averaged) != len(active_inputs):
            raise BackendError(
                f"NI read returned {len(averaged)} channel values for {len(active_inputs)} active AI channels."
            )

        inputs: list[AnalogInputReading] = []
        for value_index, (channel_index, channel) in enumerate(active_inputs):
            voltage = averaged[value_index]
            scaled_value = (voltage * channel.scale) + channel.offset
            inputs.append(
                AnalogInputReading(
                    channel_index=channel_index,
                    channel_name=channel.name,
                    voltage=voltage,
                    scaled_value=scaled_value,
                    unit=channel.engineering_unit,
                    status="ok" if abs(voltage) < 4.9 else "limit",
                )
            )

        return MeasurementFrame(
            timestamp=datetime.now(),
            elapsed_s=elapsed_s,
            inputs=inputs,
            outputs=self._build_output_states(),
        )

    def write_output_currents(self, currents_ma: dict[int, float]) -> list[AnalogOutputState]:
        active_outputs = [(index, channel) for index, channel in enumerate(self.config.ao_channels) if channel.enabled]
        if active_outputs and self._output_task is None:
            raise BackendError("NI output task is not connected.")

        ordered_currents_amp: list[float] = []
        for index, channel in enumerate(self.config.ao_channels):
            target_value = currents_ma.get(index, self._output_currents_ma.get(index, channel.initial_current_ma))
            clamped = max(channel.min_current_ma, min(channel.max_current_ma, float(target_value)))
            self._output_currents_ma[index] = clamped

        for index, _channel in active_outputs:
            ordered_currents_amp.append(self._output_currents_ma[index] / 1000.0)

        if self._output_task is not None and ordered_currents_amp:
            try:
                if len(ordered_currents_amp) == 1:
                    self._output_task.write(ordered_currents_amp[0], auto_start=True)
                else:
                    self._output_task.write(ordered_currents_amp, auto_start=True)
            except Exception as exc:  # pragma: no cover - depends on external hardware
                raise BackendError(f"Failed to write NI output currents: {exc}") from exc

        return self._build_output_states()

    def _resolve_physical_channel(
        self,
        physical_channel: str,
        *,
        available_device_names: set[str],
        fallback_slot: int,
        fallback_port: int,
        expected_kind: str,
    ) -> str:
        compact_channel = normalize_physical_channel(
            physical_channel,
            fallback_slot=fallback_slot,
            fallback_port=fallback_port,
            expected_kind=expected_kind,
            chassis_name=self.config.chassis_name,
        )
        slotted_channel = normalize_physical_channel(
            physical_channel,
            fallback_slot=fallback_slot,
            fallback_port=fallback_port,
            expected_kind=expected_kind,
            chassis_name=self.config.chassis_name,
            use_slotted_module_path=True,
        )
        module_device_name = compact_channel.split("/", 1)[0]
        return compact_channel if module_device_name in available_device_names else slotted_channel

    def _build_output_states(self) -> list[AnalogOutputState]:
        return [
            AnalogOutputState(
                channel_index=index,
                channel_name=channel.name,
                current_ma=self._output_currents_ma.get(index, 0.0),
            )
            for index, channel in enumerate(self.config.ao_channels)
        ]

    def _resolve_samples_to_read(self) -> int:
        if self._input_task is None:
            return self._samples_per_read

        available_samples = 0
        try:
            available_samples = int(getattr(self._input_task.in_stream, "avail_samp_per_chan", 0) or 0)
        except Exception:
            available_samples = 0

        if available_samples <= self._samples_per_read:
            return self._samples_per_read

        return min(
            available_samples,
            self._samples_per_read * self.MAX_READ_BATCH_MULTIPLIER,
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
