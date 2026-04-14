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
    pulses_per_mm: float = 1000.0
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
            raise ValueError("SHOT-102 serial port must not be empty.")
        if self.axis not in {1, 2}:
            raise ValueError("SHOT-102 axis must be 1 or 2.")
        if self.baudrate not in SHOT102_SUPPORTED_BAUDRATES:
            raise ValueError(f"Unsupported SHOT-102 baudrate: {self.baudrate}")
        if self.pulses_per_mm <= 0:
            raise ValueError("pulses_per_mm must be greater than 0.")
        if self.home_direction not in {"+", "-"}:
            raise ValueError("home_direction must be '+' or '-'.")
        if self.ready_timeout_s <= 0:
            raise ValueError("ready_timeout_s must be greater than 0.")
        if self.ready_poll_interval_s <= 0:
            raise ValueError("ready_poll_interval_s must be greater than 0.")
        if self.serial_timeout_s <= 0:
            raise ValueError("serial_timeout_s must be greater than 0.")
        if self.minimum_speed_pps <= 0 or self.maximum_speed_pps <= 0:
            raise ValueError("SHOT-102 speed parameters must be greater than 0.")
        if self.minimum_speed_pps > self.maximum_speed_pps:
            raise ValueError("minimum_speed_pps must be less than or equal to maximum_speed_pps.")
        if self.acceleration_ms < 0:
            raise ValueError("acceleration_ms must be 0 or higher.")


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
    return Shot102MotionConfig(
        port=str(payload.get("port", "")).strip(),
        axis=int(payload.get("axis", 1)),
        baudrate=int(payload.get("baudrate", 9600)),
        pulses_per_mm=float(payload.get("pulses_per_mm", 1000.0)),
        home_direction=str(payload.get("home_direction", "-")),
        disengage_position_mm=float(payload.get("disengage_position_mm", 0.0)),
        ready_timeout_s=float(payload.get("ready_timeout_s", 15.0)),
        ready_poll_interval_s=float(payload.get("ready_poll_interval_s", 0.05)),
        serial_timeout_s=float(payload.get("serial_timeout_s", 1.0)),
        driver_mode=str(payload.get("driver_mode", "SHOT-102")),
        stage_model=str(payload.get("stage_model", "SIGMAKOKI SGSP20-85")),
        controller_model=str(payload.get("controller_model", "SIGMAKOKI SHOT-102")),
        set_speed_on_connect=bool(payload.get("set_speed_on_connect", True)),
        minimum_speed_pps=int(payload.get("minimum_speed_pps", 50)),
        maximum_speed_pps=int(payload.get("maximum_speed_pps", 5000)),
        acceleration_ms=int(payload.get("acceleration_ms", 200)),
        home_on_connect=bool(payload.get("home_on_connect", True)),
        motor_hold_on_connect=bool(payload.get("motor_hold_on_connect", True)),
        free_motor_on_disconnect=bool(payload.get("free_motor_on_disconnect", False)),
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
        self._send_expect_ok(f"H:{axis}{direction}")

    def move_absolute_pulses(self, *, axis: int, position_pulses: int) -> None:
        direction = "+" if position_pulses >= 0 else "-"
        self._send_expect_ok(f"A:{axis}{direction}P{abs(int(position_pulses))}")
        self._send_expect_ok("G:")

    def move_relative_pulses(self, *, axis: int, delta_pulses: int) -> None:
        direction = "+" if delta_pulses >= 0 else "-"
        self._send_expect_ok(f"M:{axis}{direction}P{abs(int(delta_pulses))}")
        self._send_expect_ok("G:")

    def set_speed(self, *, axis: int, minimum_speed_pps: int, maximum_speed_pps: int, acceleration_ms: int) -> None:
        self._send_expect_ok(
            f"D:{axis}S{int(minimum_speed_pps)}F{int(maximum_speed_pps)}R{int(acceleration_ms)}"
        )

    def set_motor_hold(self, *, axis: int, hold: bool) -> None:
        state = "1" if hold else "0"
        self._send_expect_ok(f"C:{axis}{state}")

    def slow_stop(self, *, axis: int) -> None:
        self._send_expect_ok(f"L:{axis}")

    def emergency_stop(self) -> None:
        self._send_expect_ok("L:E")

    def reset_logical_zero(self, *, axis: int) -> None:
        self._send_expect_ok(f"R:{axis}")

    def get_axis_position_pulses(self, axis: int) -> int:
        status = self.get_status()
        return status.axis1_position if axis == 1 else status.axis2_position

    def _send_expect_ok(self, command: str) -> None:
        response = self._send_query(command)
        if response != "OK":
            raise MotionError(f"SHOT-102 command failed: {command!r} -> {response!r}")

    def _send_query(self, command: str) -> str:
        transport = self._require_transport()
        payload = f"{command}{self.COMMAND_SUFFIX}".encode("ascii")
        transport.write(payload)
        raw = transport.readline()
        if not raw:
            raise MotionError(f"SHOT-102 timed out while waiting for reply to {command!r}")
        return raw.decode("ascii", errors="replace").strip()

    def _reset_buffers(self) -> None:
        transport = self._require_transport()
        transport.reset_input_buffer()
        transport.reset_output_buffer()

    def _require_transport(self) -> SerialTransport:
        if self._transport is None:
            raise MotionError("SHOT-102 transport is not connected.")
        return self._transport

    def _open_transport(self) -> SerialTransport:
        try:
            import serial
        except ImportError as exc:  # pragma: no cover - depends on runtime install
            raise MotionError(
                "pyserial is required for SHOT-102 control. Install dependencies and try again."
            ) from exc

        return serial.Serial(
            port=self.config.port,
            baudrate=self.config.baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.config.serial_timeout_s,
            write_timeout=self.config.serial_timeout_s,
            rtscts=True,
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

    def abort(self) -> None:
        try:
            self.controller.emergency_stop()
        finally:
            self.controller.disconnect()

    def _displacement_to_pulses(self, displacement_mm: float) -> int:
        return int(round(displacement_mm * self.config.pulses_per_mm))
