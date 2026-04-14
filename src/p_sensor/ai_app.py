from __future__ import annotations

from p_sensor.launcher import main as run_main


def main() -> int:
    return run_main(["--profile", "ai"])


if __name__ == "__main__":
    raise SystemExit(main())
