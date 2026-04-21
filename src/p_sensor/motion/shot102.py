from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from p_sensor.automation.runner import CommandBridge
from p_sensor.automation.models import AutomationStep
from p_sensor.config import resolve_runtime_path


SHOT102_SUPPORTED_BAUDRATES = {4800, 9600, 19200, 38400}
SHOT102_MAX_POSITION_PULSES = 16_777_124
SHOT102_MIN_SPEED_PPS = 1
SHOT102_MAX_SPEED_PPS = 20_000
SHOT702_MAX_SPEED_PPS = 500_000
SHOT102_MAX_ACCELERATION_MS = 5_000


class MotionError(RuntimeError):
    pass


class SerialTransport(Protocol):
    port: str
    timeout: float | None

    def write(self, data: bytes) -> int: ...

    def readline(self) -> bytes: ...

    def reset_input_buffer(self) -> None: ...

    def reset_output_buffer(self) -> None: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class Shot102Status:
    axis1_position: int
    axis2_position: int
    command_ack: str
    stop_ack: str
    ready_ack: str

    @property
    def is_ready(self) -> bool:
        return self.ready_ack == "R"

    @property
    def is_busy(self) -> bool:
        return self.ready_ack == "B"


@dataclass(slots=True)
class Shot102MotionConfig:
    port: str
    axis: int = 1
    baudrate: int = 9600
    rtscts: bool = True
    pulses_per_mm: float = 1000.0
    min_position_mm: float = 0.0
    max_position_mm: float = 85.0
    enforce_software_limits: bool = True
    home_direction: str = "-"
    disengage_position_mm: float = 0.0
    ready_timeout_s: float = 15.0
    ready_poll_interval_s: float = 0.05
    serial_timeout_s: float = 1.0
    driver_mode: str = "SHOT-102"
    stage_model: str = "SIGMAKOKI SGSP20-85"
    controller_model: str = "SIGMAKOKI SHOT-102"
    set_speed_on_connect: bool = True
    minimum_speed_pps: int = 50
    maximum_speed_pps: int = 5000
    acceleration_ms: int = 200
    home_on_connect: bool = True
    motor_hold_on_connect: bool = True
    free_motor_on_disconnect: bool = False

    def __post_init__(self) -> None:
        if not self.port.strip():
            raise ValueError(f"{self.controller_model} serial port must not be empty.")
        if self.axis not in {1, 2}:
            raise ValueError(f"{self.controller_model} axis must be 1 or 2.")
        if self.baudrate not in SHOT102_SUPPORTED_BAUDRATES:
            raise ValueError(f"Unsupported {self.controller_model} baudrate: {self.baudrate}")
        if self.pulses_per_mm <= 0:
            raise ValueError("pulses_per_mm must be greater than 0.")
        if self.min_position_mm >= self.max_position_mm:
            raise ValueError("min_position_mm must be less than max_position_mm.")
        if self.home_direction not in {"+", "-"}:
            raise ValueError("home_direction must be '+' or '-'.")
        if self.ready_timeout_s <= 0:
            raise ValueError("ready_timeout_s must be greater than 0.")
        if self.ready_poll_interval_s <= 0:
            raise ValueError("ready_poll_interval_s must be greater than 0.")
        if self.serial_timeout_s <= 0:
            raise ValueError("serial_timeout_s must be greater than 0.")
        if self.minimum_speed_pps <= 0 or self.maximum_speed_pps <= 0:
            raise ValueError(f"{self.controller_model} speed parameters must be greater than 0.")
        max_speed_pps = _max_supported_speed_pps(self.driver_mode, self.controller_model)
        if self.minimum_speed_pps > max_speed_pps:
            raise ValueError(f"minimum_speed_pps must be {max_speed_pps} or lower.")
        if self.maximum_speed_pps > max_speed_pps:
            raise ValueError(f"maximum_speed_pps must be {max_speed_pps} or lower.")
        if self.minimum_speed_pps > self.maximum_speed_pps:
            raise ValueError("minimum_speed_pps must be less than or equal to maximum_speed_pps.")
        if self.acceleration_ms < 0 or self.acceleration_ms > SHOT102_MAX_ACCELERATION_MS:
            raise ValueError(f"acceleration_ms must be between 0 and {SHOT102_MAX_ACCELERATION_MS}.")


def _is_shot702_mode(driver_mode: str, controller_model: str) -> bool:
    return "SHOT-702" in f"{driver_mode} {controller_model}".upper()


def _default_baudrate(driver_mode: str, controller_model: str) -> int:
    if _is_shot702_mode(driver_mode, controller_model):
        return 38400
    return 9600


def _max_supported_speed_pps(driver_mode: str, controller_model: str) -> int:
    if _is_shot702_mode(driver_mode, controller_model):
        return SHOT702_MAX_SPEED_PPS
    return SHOT102_MAX_SPEED_PPS


def _load_bool(payload: dict, key: str, default: bool) -> bool:
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return bool(value)


def parse_shot102_status_reply(reply: str) -> Shot102Status:
    parts = [part.strip() for part in reply.split(",")]
    if len(parts) != 5:
        raise MotionError(f"Invalid SHOT-102 status reply: {reply!r}")
    try:
        axis1_position = int(parts[0])
        axis2_position = int(parts[1])
    except ValueError as exc:
        raise MotionError(f"Invalid SHOT-102 coordinates in reply: {reply!r}") from exc

    command_ack, stop_ack, ready_ack = parts[2], parts[3], parts[4]
    if command_ack not in {"K", "X"}:
        raise MotionError(f"Unexpected SHOT-102 command ACK: {command_ack!r}")
    if stop_ack not in {"K", "L", "M", "W"}:
        raise MotionError(f"Unexpected SHOT-102 stop ACK: {stop_ack!r}")
    if ready_ack not in {"R", "B"}:
        raise MotionError(f"Unexpected SHOT-102 ready ACK: {ready_ack!r}")
    return Shot102Status(
        axis1_position=axis1_position,
        axis2_position=axis2_position,
        command_ack=command_ack,
        stop_ack=stop_ack,
        ready_ack=ready_ack,
    )


def load_shot102_motion_config(path: str | Path) -> Shot102MotionConfig:
    config_path = resolve_runtime_path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    driver_mode = str(payload.get("driver_mode", "SHOT-102"))
    controller_model = str(payload.get("controller_model", "SIGMAKOKI SHOT-102"))
    default_baudrate = _default_baudrate(driver_mode, controller_model)
    return Shot102MotionConfig(
        port=str(payload.get("port", "")).strip(),
        axis=int(payload.get("axis", 1)),
        baudrate=int(payload.get("baudrate", default_baudrate)),
        rtscts=_load_bool(payload, "rtscts", True),
        pulses_per_mm=float(payload.get("pulses_per_mm", 1000.0)),
        min_position_mm=float(payload.get("min_position_mm", 0.0)),
        max_position_mm=float(payload.get("max_position_mm", 85.0)),
        enforce_software_limits=_load_bool(payload, "enforce_software_limits", True),
        home_direction=str(payload.get("home_direction", "-")),
        disengage_position_mm=float(payload.get("disengage_position_mm", 0.0)),
        ready_timeout_s=float(payload.get("ready_timeout_s", 15.0)),
        ready_poll_interval_s=float(payload.get("ready_poll_interval_s", 0.05)),
        serial_timeout_s=float(payload.get("serial_timeout_s", 1.0)),
        driver_mode=driver_mode,
        stage_model=str(payload.get("stage_model", "SIGMAKOKI SGSP20-85")),
        controller_model=controller_model,
        set_speed_on_connect=_load_bool(payload, "set_speed_on_connect", True),
        minimum_speed_pps=int(payload.get("minimum_speed_pps", 50)),
        maximum_speed_pps=int(payload.get("maximum_speed_pps", 5000)),
        acceleration_ms=int(payload.get("acceleration_ms", 200)),
        home_on_connect=_load_bool(payload, "home_on_connect", True),
        motor_hold_on_connect=_load_bool(payload, "motor_hold_on_connect", True),
        free_motor_on_disconnect=_load_bool(payload, "free_motor_on_disconnect", False),
    )


class Shot102Controller:
    COMMAND_SUFFIX = "\r\n"

    def __init__(self, config: Shot102MotionConfig, transport: SerialTransport | None = None) -> None:
        self.config = config
        self._transport = transport

    def connect(self) -> str:
        if self._transport is None:
            self._transport = self._open_transport()
        self._reset_buffers()
        version = self.get_rom_version()
        if self.config.set_speed_on_connect:
            self.set_speed(
                axis=self.config.axis,
                minimum_speed_pps=self.config.minimum_speed_pps,
                maximum_speed_pps=self.config.maximum_speed_pps,
                acceleration_ms=self.config.acceleration_ms,
            )
        if self.config.motor_hold_on_connect:
            self.set_motor_hold(axis=self.config.axis, hold=True)
        if self.config.home_on_connect:
            self.home(axis=self.config.axis, direction=self.config.home_direction)
            self.wait_until_ready(timeout_s=self.config.ready_timeout_s)
        return (
            f"{self.config.controller_model} ready on {self.config.port} "
            f"(axis={self.config.axis}, rom={version}, stage={self.config.stage_model})"
        )

    def disconnect(self) -> None:
        if self._transport is None:
            return
        try:
            if self.config.free_motor_on_disconnect:
                try:
                    self.set_motor_hold(axis=self.config.axis, hold=False)
                except Exception:
                    pass
        finally:
            self._transport.close()
            self._transport = None

    def get_rom_version(self) -> str:
        return self._send_query("?:V")

    def get_status(self) -> Shot102Status:
        return parse_shot102_status_reply(self._send_query("Q:"))

    def is_ready(self) -> bool:
        return self._send_query("!:") == "R"

    def wait_until_ready(self, timeout_s: float | None = None) -> None:
        timeout = self.config.ready_timeout_s if timeout_s is None else timeout_s
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_ready():
                return
            time.sleep(self.config.ready_poll_interval_s)
        raise MotionError(f"{self.config.controller_model} did not become ready within {timeout:.2f}s.")

    def home(self, *, axis: int, direction: str) -> None:
        self._validate_axis(axis)
        self._validate_direction(direction)
        self._send_expect_ok(f"H:{axis}{direction}")

    def origin(self, *, axis: int, direction: str | None = None, reset_logical_zero: bool = False) -> None:
        origin_direction = self.config.home_direction if direction is None else direction
        self.home(axis=axis, direction=origin_direction)
        self.wait_until_ready()
        if reset_logical_zero:
            self.reset_logical_zero(axis=axis)

    def move_absolute_pulses(self, *, axis: int, position_pulses: int) -> None:
        self._validate_axis(axis)
        self._validate_absolute_pulses(position_pulses)
        direction = "+" if position_pulses >= 0 else "-"
        self._send_expect_ok(f"A:{axis}{direction}P{abs(int(position_pulses))}")
        self._send_expect_ok("G:")

    def move_relative_pulses(self, *, axis: int, delta_pulses: int) -> None:
        self._validate_axis(axis)
        self._validate_relative_pulses(axis=axis, delta_pulses=delta_pulses)
        direction = "+" if delta_pulses >= 0 else "-"
        self._send_expect_ok(f"M:{axis}{direction}P{abs(int(delta_pulses))}")
        self._send_expect_ok("G:")

    def move_absolute_mm(self, *, axis: int, position_mm: float) -> None:
        self.move_absolute_pulses(axis=axis, position_pulses=self.mm_to_pulses(position_mm))

    def move_relative_mm(self, *, axis: int, delta_mm: float) -> None:
        self.move_relative_pulses(axis=axis, delta_pulses=self.mm_to_pulses(delta_mm))

    def set_speed(self, *, axis: int, minimum_speed_pps: int, maximum_speed_pps: int, acceleration_ms: int) -> None:
        self._validate_axis(axis)
        self._validate_speed(
            minimum_speed_pps=minimum_speed_pps,
            maximum_speed_pps=maximum_speed_pps,
            acceleration_ms=acceleration_ms,
        )
        self._send_expect_ok(
            f"D:{axis}S{int(minimum_speed_pps)}F{int(maximum_speed_pps)}R{int(acceleration_ms)}"
        )

    def set_motor_hold(self, *, axis: int, hold: bool) -> None:
        self._validate_axis(axis)
        state = "1" if hold else "0"
        self._send_expect_ok(f"C:{axis}{state}")

    def slow_stop(self, *, axis: int) -> None:
        self._validate_axis(axis)
        self._send_expect_ok(f"L:{axis}")

    def emergency_stop(self) -> None:
        self._send_expect_ok("L:E")

    def reset_logical_zero(self, *, axis: int) -> None:
        self._validate_axis(axis)
        self._send_expect_ok(f"R:{axis}")

    def get_axis_position_pulses(self, axis: int) -> int:
        self._validate_axis(axis)
        status = self.get_status()
        return status.axis1_position if axis == 1 else status.axis2_position

    def get_axis_position_mm(self, axis: int) -> float:
        return self.pulses_to_mm(self.get_axis_position_pulses(axis))

    def mm_to_pulses(self, position_mm: float) -> int:
        return int(round(position_mm * self.config.pulses_per_mm))

    def pulses_to_mm(self, pulses: int) -> float:
        return pulses / self.config.pulses_per_mm

    def _send_expect_ok(self, command: str) -> None:
        response = self._send_query(command)
        if response != "OK":
            raise MotionError(f"{self.config.controller_model} command failed: {command!r} -> {response!r}")

    def _send_query(self, command: str) -> str:
        transport = self._require_transport()
        payload = f"{command}{self.COMMAND_SUFFIX}".encode("ascii")
        transport.write(payload)
        raw = transport.readline()
        if not raw:
            raise MotionError(
                f"{self.config.controller_model} timed out while waiting for reply to {command!r}"
            )
        return raw.decode("ascii", errors="replace").strip()

    def _reset_buffers(self) -> None:
        transport = self._require_transport()
        transport.reset_input_buffer()
        transport.reset_output_buffer()

    def _require_transport(self) -> SerialTransport:
        if self._transport is None:
            raise MotionError(f"{self.config.controller_model} transport is not connected.")
        return self._transport

    def _validate_axis(self, axis: int) -> None:
        if axis not in {1, 2}:
            raise ValueError(f"{self.config.controller_model} axis must be 1 or 2.")

    def _validate_direction(self, direction: str) -> None:
        if direction not in {"+", "-"}:
            raise ValueError(f"{self.config.controller_model} direction must be '+' or '-'.")

    def _validate_speed(self, *, minimum_speed_pps: int, maximum_speed_pps: int, acceleration_ms: int) -> None:
        max_speed_pps = _max_supported_speed_pps(self.config.driver_mode, self.config.controller_model)
        if minimum_speed_pps < SHOT102_MIN_SPEED_PPS or minimum_speed_pps > max_speed_pps:
            raise ValueError(
                f"minimum_speed_pps must be between {SHOT102_MIN_SPEED_PPS} and {max_speed_pps}."
            )
        if maximum_speed_pps < SHOT102_MIN_SPEED_PPS or maximum_speed_pps > max_speed_pps:
            raise ValueError(
                f"maximum_speed_pps must be between {SHOT102_MIN_SPEED_PPS} and {max_speed_pps}."
            )
        if minimum_speed_pps > maximum_speed_pps:
            raise ValueError("minimum_speed_pps must be less than or equal to maximum_speed_pps.")
        if acceleration_ms < 0 or acceleration_ms > SHOT102_MAX_ACCELERATION_MS:
            raise ValueError(f"acceleration_ms must be between 0 and {SHOT102_MAX_ACCELERATION_MS}.")

    def _validate_absolute_pulses(self, position_pulses: int) -> None:
        if abs(position_pulses) > SHOT102_MAX_POSITION_PULSES:
            raise MotionError(
                f"Requested position {position_pulses} pulses exceeds SHOT-102 coordinate range "
                f"+/-{SHOT102_MAX_POSITION_PULSES} pulses."
            )
        if not self.config.enforce_software_limits:
            return
        position_mm = self.pulses_to_mm(position_pulses)
        if position_mm < self.config.min_position_mm or position_mm > self.config.max_position_mm:
            raise MotionError(
                f"Requested position {position_mm:.6g} mm is outside configured software limits "
                f"[{self.config.min_position_mm:.6g}, {self.config.max_position_mm:.6g}] mm."
            )

    def _validate_relative_pulses(self, *, axis: int, delta_pulses: int) -> None:
        if abs(delta_pulses) > SHOT102_MAX_POSITION_PULSES:
            raise MotionError(
                f"Requested relative move {delta_pulses} pulses exceeds SHOT-102 coordinate range "
                f"+/-{SHOT102_MAX_POSITION_PULSES} pulses."
            )
        if not self.config.enforce_software_limits:
            return
        current_position = self.get_axis_position_pulses(axis)
        self._validate_absolute_pulses(current_position + delta_pulses)

    def _open_transport(self) -> SerialTransport:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on runtime install
            raise MotionError(
                f"pyserial is required for {self.config.controller_model} control. "
                "Install dependencies and try again."
            ) from exc

        return serial.Serial(
            port=self.config.port,
            baudrate=self.config.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.config.serial_timeout_s,
            write_timeout=self.config.serial_timeout_s,
            rtscts=self.config.rtscts,
        )


class Shot102CommandBridge(CommandBridge):
    def __init__(self, controller: Shot102Controller) -> None:
        self.controller = controller
        self.config = controller.config

    def connect(self) -> str:
        return self.controller.connect()

    def disconnect(self) -> None:
        self.controller.disconnect()

    def engage(self, step: AutomationStep) -> None:
        target_pulses = self._displacement_to_pulses(step.target_displacement or 0.0)
        self.controller.move_absolute_pulses(axis=self.config.axis, position_pulses=target_pulses)

    def disengage(self, step: AutomationStep) -> None:
        target_pulses = self._displacement_to_pulses(self.config.disengage_position_mm)
        self.controller.move_absolute_pulses(axis=self.config.axis, position_pulses=target_pulses)

    def wait_until_ready(self, timeout_s: float | None = None) -> None:
        self.controller.wait_until_ready(timeout_s=timeout_s)

    def get_position_mm(self) -> float | None:
        return self.controller.get_axis_position_mm(self.config.axis)

    def abort(self) -> None:
        try:
            self.controller.emergency_stop()
        finally:
            self.controller.disconnect()

    def _displacement_to_pulses(self, displacement_mm: float) -> int:
        return int(round(displacement_mm * self.config.pulses_per_mm))
