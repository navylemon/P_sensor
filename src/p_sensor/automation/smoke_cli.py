from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from typing import Sequence

from p_sensor.acquisition import NiDaqBackend, SimulatedBackend
from p_sensor.automation.models import AutomationSessionOptions
from p_sensor.automation.recipe import load_recipe
from p_sensor.automation.runner import ExperimentRunner, NoOpCommandBridge
from p_sensor.automation.safety import AutomationSafetyPolicy
from p_sensor.config import APP_ROOT, load_config, resolve_runtime_path
from p_sensor.models import AppConfig
from p_sensor.motion import ShotCommandBridge, ShotController, load_shot_motion_config
from p_sensor.services import MeasurementService


DEFAULT_APP_CONFIG = "config/channel_settings_automation.example.json"
DEFAULT_RECIPE = "config/experiment_recipe_smoke.example.json"
DEFAULT_LOCAL_MOTION_CONFIG = "dev_local/config/stage_shot702_osms20_35.local.json"
DEFAULT_EXAMPLE_MOTION_CONFIG = "config/stage_shot702_osms20_35.example.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a small automation smoke test with simulated DAQ and optional SHOT motion."
    )
    parser.add_argument("--config", default=DEFAULT_APP_CONFIG, help="App/DAQ config JSON path.")
    parser.add_argument("--recipe", default=DEFAULT_RECIPE, help="Automation recipe JSON path.")
    parser.add_argument("--motion-config", default=None, help="SHOT motion config JSON path.")
    parser.add_argument("--no-motion", action="store_true", help="Use NoOp motion bridge.")
    parser.add_argument("--allow-ni", action="store_true", help="Allow NI backend when app config requests it.")
    parser.add_argument("--require-ni", action="store_true", help="Fail unless the app config selects the NI backend.")
    parser.add_argument("--require-motion", action="store_true", help="Fail if the smoke run would use NoOp motion.")
    parser.add_argument("--include-ao", action="store_true", help="Keep AO channels from the app config.")
    parser.add_argument("--session-label", default="shot702_smoke", help="Automation session label.")
    parser.add_argument("--home-on-connect", action="store_true", help="Allow motion config home_on_connect.")
    parser.add_argument("--set-speed-on-connect", action="store_true", help="Apply configured SHOT speed on connect.")
    return parser


def default_motion_config_path() -> Path:
    for candidate in (
        DEFAULT_LOCAL_MOTION_CONFIG,
        DEFAULT_EXAMPLE_MOTION_CONFIG,
    ):
        path = resolve_runtime_path(candidate)
        if path.exists():
            return path
    return resolve_runtime_path(DEFAULT_EXAMPLE_MOTION_CONFIG)


def make_backend(config: AppConfig, *, allow_ni: bool):
    if config.backend == "simulation":
        return SimulatedBackend(config)
    if config.backend == "ni":
        if not allow_ni:
            raise RuntimeError("NI backend requested by config. Pass --allow-ni to use hardware DAQ.")
        return NiDaqBackend(config)
    raise RuntimeError(f"Unsupported backend: {config.backend}")


def make_motion_bridge(args: argparse.Namespace):
    if args.no_motion:
        return NoOpCommandBridge(), AutomationSafetyPolicy()

    motion_config_path = resolve_runtime_path(args.motion_config) if args.motion_config else default_motion_config_path()
    motion_config = load_shot_motion_config(motion_config_path)
    motion_config = replace(
        motion_config,
        home_on_connect=args.home_on_connect,
        set_speed_on_connect=args.set_speed_on_connect,
        motor_hold_on_connect=True,
    )
    safety_policy = AutomationSafetyPolicy(
        min_position_mm=motion_config.min_position_mm if motion_config.enforce_software_limits else None,
        max_position_mm=motion_config.max_position_mm if motion_config.enforce_software_limits else None,
        require_target_displacement=True,
    )
    return ShotCommandBridge(ShotController(motion_config)), safety_policy


def run_smoke(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.require_motion and args.no_motion:
        raise RuntimeError("--require-motion cannot be combined with --no-motion.")
    if args.require_ni and not args.allow_ni:
        raise RuntimeError("--require-ni requires --allow-ni so hardware DAQ access is explicit.")
    config = load_config(args.config)
    if args.require_ni and config.backend != "ni":
        raise RuntimeError(f"--require-ni expected backend 'ni', got {config.backend!r}.")
    if not args.include_ao:
        config = replace(config, ao_channels=[])
    recipe = load_recipe(args.recipe)
    backend = make_backend(config, allow_ni=args.allow_ni)
    measurement_service = MeasurementService(backend, config.sampling.acquisition_hz)
    command_bridge, safety_policy = make_motion_bridge(args)
    runner = ExperimentRunner(
        measurement_service,
        command_bridge=command_bridge,
        safety_policy=safety_policy,
    )
    options = AutomationSessionOptions(
        export_directory=config.export_directory,
        session_label=args.session_label,
        metadata={
            "app_config_path": str(resolve_runtime_path(args.config)),
            "recipe_path": str(resolve_runtime_path(args.recipe)),
            "motion_config_path": (
                "" if args.no_motion else str(resolve_runtime_path(args.motion_config) if args.motion_config else default_motion_config_path())
            ),
            "cwd": str(APP_ROOT),
            "smoke": True,
            "require_ni": args.require_ni,
            "require_motion": args.require_motion,
        },
    )

    result = runner.run(recipe, options)
    print(f"session_id={result.session_id}")
    print(f"session_dir={result.session_dir}")
    print(f"summary_path={result.summary_path}")
    for step in result.step_results:
        print(
            "step "
            f"{step.step_index} "
            f"id={step.step_id} "
            f"target={step.target_displacement} "
            f"before={step.position_before_mm} "
            f"engaged={step.position_after_engage_mm} "
            f"disengaged={step.position_after_disengage_mm} "
            f"measurement={step.measurement_file}"
        )
    return 0


def main() -> int:
    return run_smoke()


if __name__ == "__main__":
    raise SystemExit(main())
