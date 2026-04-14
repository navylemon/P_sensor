from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from p_sensor.config import default_app_config, load_config, save_config
from p_sensor.models import AppConfig
from p_sensor.profiles import IO_APP_PROFILE, AppProfile
from p_sensor.ui.main_window import MainWindow


def resolve_default_config_path(profile: AppProfile) -> Path:
    return profile.config_path


def apply_profile(config: AppConfig, profile: AppProfile) -> AppConfig:
    if profile.supports_analog_output:
        return config
    return replace(config, ao_channels=[])


def load_or_create_config(config_path: Path, profile: AppProfile) -> AppConfig:
    if config_path.exists():
        return apply_profile(load_config(config_path), profile)

    config = default_app_config(
        input_channel_count=profile.default_input_channel_count,
        output_channel_count=profile.default_output_channel_count,
    )
    save_config(config_path, config)
    return apply_profile(config, profile)


def configure_palette(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#13161B"))
    palette.setColor(QPalette.WindowText, QColor("#E8ECF1"))
    palette.setColor(QPalette.Base, QColor("#0F1217"))
    palette.setColor(QPalette.AlternateBase, QColor("#171B22"))
    palette.setColor(QPalette.ToolTipBase, QColor("#11151B"))
    palette.setColor(QPalette.ToolTipText, QColor("#E8ECF1"))
    palette.setColor(QPalette.Text, QColor("#E8ECF1"))
    palette.setColor(QPalette.Button, QColor("#1B212B"))
    palette.setColor(QPalette.ButtonText, QColor("#E8ECF1"))
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Highlight, QColor("#2F81F7"))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.PlaceholderText, QColor("#8B949E"))
    app.setPalette(palette)


def run_application(profile: AppProfile = IO_APP_PROFILE, *, config_path: Path | None = None) -> int:
    resolved_config_path = resolve_default_config_path(profile) if config_path is None else config_path
    app = QApplication(sys.argv)
    app.setOrganizationName("25CNT")
    app.setApplicationName(profile.application_name)
    configure_palette(app)
    try:
        config = load_or_create_config(resolved_config_path, profile)
    except Exception as exc:
        QMessageBox.critical(None, "Configuration Error", f"Failed to load configuration:\n{exc}")
        return 1

    window = MainWindow(config=config, config_path=resolved_config_path, profile=profile)
    window.show()
    return app.exec()


def main(profile: AppProfile = IO_APP_PROFILE) -> int:
    return run_application(profile)


if __name__ == "__main__":
    raise SystemExit(main())
