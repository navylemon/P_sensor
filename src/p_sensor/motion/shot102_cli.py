from __future__ import annotations

import argparse
from dataclasses import replace

from p_sensor.motion.shot102 import Shot102Controller, Shot102MotionConfig, load_shot102_motion_config


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Small SHOT command-line tool for connection checks and cautious stage moves."
    )
    parser.add_argument("--config", help="Optional SHOT JSON config path.")
    parser.add_argument("--port", default=None, help="Serial port, for example COM10.")
    parser.add_argument("--axis", type=int, default=None, choices=(1, 2), help="Stage axis to control.")
    parser.add_argument("--baudrate", type=int, default=None, help="RS-232C baudrate.")
    parser.add_argument("--pulses-per-mm", type=float, default=None, help="Motion conversion factor.")
    parser.add_argument("--min-position-mm", type=float, default=None, help="Software lower limit.")
    parser.add_argument("--max-position-mm", type=float, default=None, help="Software upper limit.")
    parser.add_argument("--no-limits", action="store_true", help="Disable software travel limits.")
    parser.add_argument("--timeout-s", type=float, default=None, help="Serial read/write timeout.")
    parser.add_argument("--ready-timeout-s", type=float, default=None, help="Motion ready timeout.")
    parser.add_argument("--set-speed", action="store_true", help="Apply speed settings on connect.")
    parser.add_argument("--minimum-speed-pps", type=int, default=None, help="Minimum speed for --set-speed.")
    parser.add_argument("--maximum-speed-pps", type=int, default=None, help="Maximum speed for --set-speed.")
    parser.add_argument("--acceleration-ms", type=int, default=None, help="Acceleration/deceleration for --set-speed.")
    parser.add_argument("--hold-on-connect", action="store_true", help="Energize motor on connect.")
    parser.add_argument("--home", choices=("+", "-"), help="Home the selected axis in this direction.")
    parser.add_argument("--origin", action="store_true", help="Move selected axis to origin using config home_direction.")
    parser.add_argument("--origin-direction", choices=("+", "-"), help="Override origin direction for --origin.")
    parser.add_argument("--origin-zero", action="store_true", help="Reset logical zero after --origin completes.")
    parser.add_argument("--zero", action="store_true", help="Set current selected-axis position to logical zero.")
    parser.add_argument("--status", action="store_true", help="Print status. This is the default action.")
    parser.add_argument("--move-relative-mm", type=float, help="Move selected axis by this many mm.")
    parser.add_argument("--move-absolute-mm", type=float, help="Move selected axis to this absolute mm position.")
    parser.add_argument("--wait", action="store_true", help="Wait until ready after motion commands.")
    parser.add_argument("--hold", action="store_true", help="Energize selected-axis motor.")
    parser.add_argument("--free", action="store_true", help="Deenergize selected-axis motor.")
    parser.add_argument("--jog", action="store_true", help="Interactive arrow-key jog mode.")
    parser.add_argument("--jog-step-mm", type=float, default=0.5, help="Jog distance per arrow key press.")
    return parser


def config_from_args(args: argparse.Namespace) -> Shot102MotionConfig:
    if args.config:
        config = load_shot102_motion_config(args.config)
    else:
        config = Shot102MotionConfig(
            port=args.port or "COM10",
            axis=args.axis or 1,
            baudrate=args.baudrate or 9600,
            home_on_connect=False,
            set_speed_on_connect=False,
            motor_hold_on_connect=False,
        )

    updates = {}
    for field_name, arg_name in (
        ("port", "port"),
        ("axis", "axis"),
        ("baudrate", "baudrate"),
        ("pulses_per_mm", "pulses_per_mm"),
        ("min_position_mm", "min_position_mm"),
        ("max_position_mm", "max_position_mm"),
        ("serial_timeout_s", "timeout_s"),
        ("ready_timeout_s", "ready_timeout_s"),
        ("minimum_speed_pps", "minimum_speed_pps"),
        ("maximum_speed_pps", "maximum_speed_pps"),
        ("acceleration_ms", "acceleration_ms"),
    ):
        value = getattr(args, arg_name)
        if value is not None:
            updates[field_name] = value

    updates["home_on_connect"] = False
    updates["set_speed_on_connect"] = args.set_speed
    updates["motor_hold_on_connect"] = args.hold_on_connect
    if args.no_limits:
        updates["enforce_software_limits"] = False

    return replace(config, **updates)


def print_status(controller: Shot102Controller, axis: int) -> None:
    status = controller.get_status()
    position_pulses = status.axis1_position if axis == 1 else status.axis2_position
    position_mm = controller.pulses_to_mm(position_pulses)
    print(
        "status "
        f"axis1_pulses={status.axis1_position} "
        f"axis2_pulses={status.axis2_position} "
        f"selected_axis={axis} "
        f"selected_position_mm={position_mm:.6f} "
        f"ack={status.command_ack}/{status.stop_ack}/{status.ready_ack}"
    )


def read_jog_key() -> str:
    try:
        import msvcrt
    except ImportError as exc:  # pragma: no cover - Windows-only operator tool
        raise RuntimeError("Interactive jog mode requires a Windows console.") from exc

    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        extended = msvcrt.getwch()
        return {
            "K": "left",
            "M": "right",
            "H": "up",
            "P": "down",
        }.get(extended, "")
    if key == " ":
        return "space"
    return key.lower()


def run_jog_mode(controller: Shot102Controller, config: Shot102MotionConfig, *, step_mm: float) -> None:
    if step_mm <= 0:
        raise ValueError("jog_step_mm must be greater than 0.")

    controller.set_motor_hold(axis=config.axis, hold=True)
    print_status(controller, config.axis)
    print(
        f"jog mode: axis={config.axis}, step={step_mm:g} mm. "
        "Use Left/Down=-, Right/Up=+, s=status, Space=emergency stop, q=quit."
    )

    while True:
        key = read_jog_key()
        if key in {"q", "\x03"}:
            break
        if key == "s":
            print_status(controller, config.axis)
            continue
        if key == "space":
            controller.emergency_stop()
            print("emergency stop sent")
            print_status(controller, config.axis)
            continue
        if key not in {"left", "right", "up", "down"}:
            continue

        direction = -1.0 if key in {"left", "down"} else 1.0
        controller.move_relative_mm(axis=config.axis, delta_mm=direction * step_mm)
        controller.wait_until_ready()
        print_status(controller, config.axis)


def main() -> int:
    args = build_parser().parse_args()
    config = config_from_args(args)
    controller = Shot102Controller(config)
    should_print_status = args.status or not any(
        (
            args.home,
            args.origin,
            args.zero,
            args.move_relative_mm is not None,
            args.move_absolute_mm is not None,
            args.hold,
            args.free,
            args.jog,
        )
    )

    try:
        print(controller.connect())
        if args.hold:
            controller.set_motor_hold(axis=config.axis, hold=True)
        if args.free:
            controller.set_motor_hold(axis=config.axis, hold=False)
        if args.home:
            controller.home(axis=config.axis, direction=args.home)
            controller.wait_until_ready()
        if args.origin:
            controller.origin(
                axis=config.axis,
                direction=args.origin_direction,
                reset_logical_zero=args.origin_zero,
            )
        if args.zero:
            controller.reset_logical_zero(axis=config.axis)
        if args.move_absolute_mm is not None:
            controller.move_absolute_mm(axis=config.axis, position_mm=args.move_absolute_mm)
            if args.wait:
                controller.wait_until_ready()
        if args.move_relative_mm is not None:
            controller.move_relative_mm(axis=config.axis, delta_mm=args.move_relative_mm)
            if args.wait:
                controller.wait_until_ready()
        if args.jog:
            run_jog_mode(controller, config, step_mm=args.jog_step_mm)
        if should_print_status or args.wait or args.origin:
            print_status(controller, config.axis)
    finally:
        controller.disconnect()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
