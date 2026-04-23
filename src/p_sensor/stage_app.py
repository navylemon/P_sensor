from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import QApplication, QMessageBox

from p_sensor.app import configure_palette
from p_sensor.ui.stage_window import StageWindow


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p-sensor-stage")
    parser.add_argument(
        "--config",
        help="Optional SHOT-702 stage JSON config path.",
    )
    return parser


def run_stage_application(*, config_path: Path | None = None) -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName("25CNT")
    app.setApplicationName("P_sensor_Stage")
    configure_palette(app)
    try:
        window = StageWindow(config_path=config_path)
    except Exception as exc:
        QMessageBox.critical(None, "Stage GUI Error", f"Failed to start stage GUI:\n{exc}")
        return 1
    window.showMaximized()
    return app.exec()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    config_path = Path(args.config).expanduser() if args.config else None
    return run_stage_application(config_path=config_path)


if __name__ == "__main__":
    raise SystemExit(main())
