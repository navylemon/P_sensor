from __future__ import annotations

from p_sensor.models import AnalogInputChannelConfig, AnalogInputReading


def resistance_to_voltage(resistance_ohm: float, channel: AnalogInputChannelConfig) -> float:
    excitation = max(channel.excitation_voltage, 1e-9)
    nominal = max(channel.nominal_resistance_ohm, 1e-9)
    bridge_reference = nominal
    adjusted = ((resistance_ohm - channel.zero_offset) - nominal) / max(channel.calibration_scale, 1e-9)
    raw_resistance = nominal + adjusted

    if channel.bridge_type == "quarter_bridge":
        return excitation * ((raw_resistance - bridge_reference) / (2.0 * (raw_resistance + bridge_reference)))

    if channel.bridge_type == "half_bridge":
        return excitation * (adjusted / (2.0 * nominal))

    if channel.bridge_type == "full_bridge":
        return excitation * (adjusted / nominal)

    return excitation * (adjusted / (4.0 * nominal))


def voltage_to_resistance(voltage: float, channel: AnalogInputChannelConfig) -> float:
    excitation = max(channel.excitation_voltage, 1e-9)
    nominal = max(channel.nominal_resistance_ohm, 1e-9)
    bridge_reference = nominal
    ratio = voltage / excitation

    if channel.bridge_type == "quarter_bridge":
        denominator = max(1e-9, 1.0 - (2.0 * ratio))
        raw_resistance = bridge_reference * ((1.0 + (2.0 * ratio)) / denominator)
    elif channel.bridge_type == "half_bridge":
        raw_resistance = nominal * (1.0 + (2.0 * ratio))
    elif channel.bridge_type == "full_bridge":
        raw_resistance = nominal * (1.0 + ratio)
    else:
        raw_resistance = nominal * (1.0 + (4.0 * ratio))

    delta = raw_resistance - nominal
    return nominal + (delta * channel.calibration_scale) + channel.zero_offset


def reading_status(resistance_ohm: float, channel: AnalogInputChannelConfig) -> str:
    delta = abs(resistance_ohm - channel.nominal_resistance_ohm - channel.zero_offset)

    if delta > 4.5:
        return "error"
    if delta > 3.0:
        return "warning"
    return "normal"


def scale_voltage(voltage: float, channel: AnalogInputChannelConfig) -> float:
    return (voltage * channel.scale) + channel.offset


def compute_input_reading(
    *,
    channel_index: int,
    channel: AnalogInputChannelConfig,
    voltage: float,
) -> AnalogInputReading:
    if channel.measurement_mode == "voltage":
        scaled_value = scale_voltage(voltage, channel)
        unit = channel.engineering_unit.strip() or "V"
        status = "ok" if abs(voltage) < 4.9 else "limit"
    else:
        scaled_value = voltage_to_resistance(voltage, channel)
        unit = "ohm"
        status = reading_status(scaled_value, channel)

    return AnalogInputReading(
        channel_index=channel_index,
        channel_name=channel.name,
        voltage=voltage,
        scaled_value=scaled_value,
        unit=unit,
        status=status,
    )
