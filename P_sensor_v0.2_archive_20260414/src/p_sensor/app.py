from __future__ import annotations

import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMessageBox

from p_sensor.config import DEFAULT_CONFIG_PATH, default_app_config, load_config, save_config
from p_sensor.ui.main_window import MainWindow


def resolve_default_config_path() -> Path:
    return DEFAULT_CONFIG_PATH


def load_or_create_config(config_path: Path):
    if config_path.exists():
        return load_config(config_path)

    config = default_app_config()
    save_config(config_path, config)
    return config


def main() -> int:
    config_path = resolve_default_config_path()
    app = QApplication(sys.argv)
    app.setOrganizationName("25CNT")
    app.setApplicationName("P_sensor")
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
    try:
        config = load_or_create_config(config_path)
    except Exception as exc:
        QMessageBox.critical(None, "Configuration Error", f"Failed to load configuration:\n{exc}")
        return 1

    window = MainWindow(config=config, config_path=config_path)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
