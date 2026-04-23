from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from p_sensor.app import run_application
from p_sensor.profiles import resolve_profile
from p_sensor.stage_app import run_stage_application


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p_sensor")
    parser.add_argument(
        "--profile",
        default="io",
        help="Application profile to run. Supported aliases: io, ai, automation, stage.",
    )
    parser.add_argument(
        "--config",
        help="Optional path to override the default config file for the selected profile.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    config_path = Path(args.config).expanduser() if args.config else None
    if (args.profile or "").strip().lower() in {"stage", "stage_control", "motion"}:
        return run_stage_application(config_path=config_path)
    profile = resolve_profile(args.profile)
    return run_application(profile, config_path=config_path)


def main_io() -> int:
    return main(["--profile", "io"])


def main_ai() -> int:
    return main(["--profile", "ai"])


def main_automation() -> int:
    return main(["--profile", "automation"])


def main_stage() -> int:
    return main(["--profile", "stage"])
