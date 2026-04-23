from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


BadgeStyler = Callable[[QLabel, str], None]


class AutomationPanel(QGroupBox):
    load_recipe_requested = Signal()
    recipe_helper_requested = Signal()
    load_motion_requested = Signal()
    run_requested = Signal()
    stop_requested = Signal()

    def __init__(self, *, badge_styler: BadgeStyler, parent=None) -> None:
        super().__init__("Automation", parent)
        self._badge_styler = badge_styler

        self.recipe_path_edit = QLineEdit()
        self.recipe_path_edit.setReadOnly(True)
        self.recipe_path_edit.setPlaceholderText("Select automation recipe JSON")

        self.load_recipe_button = QPushButton("Load Recipe")
        self.load_recipe_button.clicked.connect(lambda: self.load_recipe_requested.emit())

        self.recipe_helper_button = QPushButton("Recipe Helper")
        self.recipe_helper_button.clicked.connect(lambda: self.recipe_helper_requested.emit())

        self.motion_config_path_edit = QLineEdit()
        self.motion_config_path_edit.setReadOnly(True)
        self.motion_config_path_edit.setPlaceholderText("Optional SHOT motion config JSON")

        self.load_motion_button = QPushButton("Load Motion")
        self.load_motion_button.clicked.connect(lambda: self.load_motion_requested.emit())

        self.automation_status_label = QLabel("Idle")
        self.automation_step_label = QLabel("No recipe loaded")
        self.motion_status_label = QLabel("Motion bridge: disabled")
        self.automation_step_label.setWordWrap(True)
        self.motion_status_label.setWordWrap(True)
        self._style_badges()

        self.run_automation_button = QPushButton("Run Automation")
        self.stop_automation_button = QPushButton("Stop Automation")
        self.run_automation_button.clicked.connect(lambda: self.run_requested.emit())
        self.stop_automation_button.clicked.connect(lambda: self.stop_requested.emit())

        self._build_layout()

    def _style_badges(self) -> None:
        self._badge_styler(self.automation_status_label, "muted")
        self._badge_styler(self.automation_step_label, "neutral")
        self._badge_styler(self.motion_status_label, "muted")

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)

        grid.addWidget(QLabel("Recipe"), 0, 0, 1, 2)
        grid.addWidget(self.recipe_path_edit, 1, 0)
        grid.addWidget(self.load_recipe_button, 1, 1)
        grid.addWidget(self.recipe_helper_button, 2, 0, 1, 2)
        grid.addWidget(QLabel("Motion Config"), 3, 0, 1, 2)
        grid.addWidget(self.motion_config_path_edit, 4, 0)
        grid.addWidget(self.load_motion_button, 4, 1)
        grid.addWidget(QLabel("Status"), 5, 0)
        grid.addWidget(QLabel("Current Step"), 5, 1)
        grid.addWidget(self.automation_status_label, 6, 0)
        grid.addWidget(self.automation_step_label, 6, 1)
        grid.addWidget(self.motion_status_label, 7, 0, 1, 2)

        button_row = QHBoxLayout()
        button_row.addWidget(self.run_automation_button)
        button_row.addWidget(self.stop_automation_button)

        layout.addLayout(grid)
        layout.addLayout(button_row)
