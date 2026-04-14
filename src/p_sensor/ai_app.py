from __future__ import annotations

from p_sensor.app import main as run_main
from p_sensor.profiles import AI_MONITOR_PROFILE


def main() -> int:
    return run_main(AI_MONITOR_PROFILE)


if __name__ == "__main__":
    raise SystemExit(main())
