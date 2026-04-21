from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from p_sensor.app import run_application
from p_sensor.profiles import resolve_profile


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p_sensor")
    parser.add_argument(
        "--profile",
        default="io",
        help="Application profile to run. Supported aliases: io, ai, automation.",
    )
    parser.add_argument(
        "--config",
        help="Optional path to override the default config file for the selected profile.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args(argv)
    profile = resolve_profile(args.profile)
    config_path = Path(args.config).expanduser() if args.config else None
    return run_application(profile, config_path=config_path)


def main_io() -> int:
    return main(["--profile", "io"])


def main_ai() -> int:
    return main(["--profile", "ai"])


def main_automation() -> int:
    return main(["--profile", "automation"])
