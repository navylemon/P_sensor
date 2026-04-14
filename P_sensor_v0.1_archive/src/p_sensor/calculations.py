from __future__ import annotations

from p_sensor.models import ChannelConfig


def resistance_to_voltage(resistance_ohm: float, channel: ChannelConfig) -> float:
    excitation = max(channel.excitation_voltage, 1e-9)
    nominal = max(channel.nominal_resistance_ohm, 1e-9)
    adjusted = ((resistance_ohm - channel.zero_offset) - nominal) / max(channel.calibration_scale, 1e-9)

    if channel.bridge_type == "quarter_bridge":
        return excitation * (adjusted / (2.0 * (adjusted + 2.0 * nominal)))

    if channel.bridge_type == "half_bridge":
        return excitation * (adjusted / (2.0 * nominal))

    if channel.bridge_type == "full_bridge":
        return excitation * (adjusted / nominal)

    return excitation * (adjusted / (4.0 * nominal))


def voltage_to_resistance(voltage: float, channel: ChannelConfig) -> float:
    excitation = max(channel.excitation_voltage, 1e-9)
    nominal = max(channel.nominal_resistance_ohm, 1e-9)
    ratio = voltage / excitation

    if channel.bridge_type == "quarter_bridge":
        denominator = max(1e-9, 1.0 - (2.0 * ratio))
        raw_resistance = nominal * ((1.0 + (2.0 * ratio)) / denominator)
    elif channel.bridge_type == "half_bridge":
        raw_resistance = nominal * (1.0 + (2.0 * ratio))
    elif channel.bridge_type == "full_bridge":
        raw_resistance = nominal * (1.0 + ratio)
    else:
        raw_resistance = nominal * (1.0 + (4.0 * ratio))

    delta = raw_resistance - nominal
    return nominal + (delta * channel.calibration_scale) + channel.zero_offset


def reading_status(resistance_ohm: float, channel: ChannelConfig) -> str:
    delta = abs(resistance_ohm - channel.nominal_resistance_ohm - channel.zero_offset)

    if delta > 4.5:
        return "error"
    if delta > 3.0:
        return "warning"
    return "normal"
