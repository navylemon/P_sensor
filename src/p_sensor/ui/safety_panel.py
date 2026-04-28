from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from pathlib import Path

from PySide6.QtWidgets import QCheckBox, QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget


BadgeStyler = Callable[[QLabel, str], None]


class SafetyPanel(QWidget):
    emergency_stop_requested = Signal()

    def __init__(self, *, badge_styler: BadgeStyler, parent=None) -> None:
        super().__init__(parent)
        self._badge_styler = badge_styler

        self.origin_confirmed_check = QCheckBox("Origin confirmed")
        self.interlock_label = QLabel("Interlock: standby")
        self.limit_label = QLabel("Limits: not loaded")
        self.contact_label = QLabel("Contact detect: off")
        self.recovery_label = QLabel("Recovery: clear")
        self.config_label = QLabel("Motion config: none")
        for label in (
            self.interlock_label,
            self.limit_label,
            self.contact_label,
            self.recovery_label,
            self.config_label,
        ):
            label.setWordWrap(False)
        self._badge_styler(self.interlock_label, "muted")
        self._badge_styler(self.limit_label, "muted")
        self._badge_styler(self.contact_label, "muted")
        self._badge_styler(self.recovery_label, "muted")
        self._badge_styler(self.config_label, "muted")

        self.emergency_button = QPushButton("Emergency Stop")
        self.emergency_button.clicked.connect(lambda: self.emergency_stop_requested.emit())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(3)
        grid.setVerticalSpacing(2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.addWidget(self.origin_confirmed_check, 0, 0)
        grid.addWidget(self.emergency_button, 0, 1)
        grid.addWidget(self.interlock_label, 1, 0)
        grid.addWidget(self.limit_label, 1, 1)
        grid.addWidget(self.contact_label, 2, 0)
        grid.addWidget(self.recovery_label, 2, 1)
        layout.addLayout(grid)

    def origin_confirmed(self) -> bool:
        return self.origin_confirmed_check.isChecked()

    def set_motion_config_summary(
        self,
        *,
        path: str,
        port: str,
        axis: int,
        min_position_mm: float | None,
        max_position_mm: float | None,
    ) -> None:
        self.config_label.setText(f"Config: {Path(path).name}")
        self.config_label.setToolTip(path)
        self._badge_styler(self.config_label, "info")
        self.limit_label.setText(f"Limits: {min_position_mm}-{max_position_mm} mm / A{axis} / {port}")
        self._badge_styler(self.limit_label, "info")
        self.interlock_label.setText("Interlock: origin required")
        self._badge_styler(self.interlock_label, "warning")
        self.origin_confirmed_check.setChecked(False)

    def set_recovery_required(self, message: str) -> None:
        self.recovery_label.setText(f"Recovery: {message}")
        self._badge_styler(self.recovery_label, "warning")

    def clear_recovery(self) -> None:
        self.recovery_label.setText("Recovery: clear")
        self._badge_styler(self.recovery_label, "muted")

    def set_contact_detection_summary(
        self,
        *,
        enabled: bool,
        axis: int | None = None,
        channel_index: int | None = None,
        speed_mm_s: float | None = None,
        threshold_ohm: float | None = None,
        motion_required: bool = False,
    ) -> None:
        if not enabled:
            self.contact_label.setText("Contact detect: off")
            self._badge_styler(self.contact_label, "muted")
            return
        if motion_required:
            self.contact_label.setText("Contact detect: enabled, motion config required")
            self._badge_styler(self.contact_label, "warning")
            return
        self.contact_label.setText(
            "Contact detect: "
            f"A{axis if axis is not None else 1} / "
            f"CH{channel_index if channel_index is not None else 0} / "
            f"{speed_mm_s if speed_mm_s is not None else 0.0:g} mm/s / "
            f"dR {threshold_ohm if threshold_ohm is not None else 0.0:g}"
        )
        self._badge_styler(self.contact_label, "info")

    def set_contact_detection_running(self) -> None:
        self.contact_label.setText("Contact detect: scanning")
        self._badge_styler(self.contact_label, "warning")

    def set_contact_detection_result(
        self,
        *,
        detected: bool,
        contact_position_mm: float | None,
        contact_resistance_ohm: float | None,
        use_as_zero: bool,
    ) -> None:
        if not detected:
            self.contact_label.setText("Contact detect: failed")
            self._badge_styler(self.contact_label, "error")
            return
        position_text = "--" if contact_position_mm is None else f"{contact_position_mm:g}"
        resistance_text = "--" if contact_resistance_ohm is None else f"{contact_resistance_ohm:g}"
        zero_text = " / zero applied" if use_as_zero else ""
        self.contact_label.setText(
            f"Contact detect: {position_text} mm / {resistance_text} ohm{zero_text}"
        )
        self._badge_styler(self.contact_label, "info")

    def mark_contact_detection_zero_applied(self, *, contact_position_mm: float | None) -> None:
        position_text = "--" if contact_position_mm is None else f"{contact_position_mm:g}"
        self.contact_label.setText(f"Contact detect: zero applied at {position_text} mm")
        self._badge_styler(self.contact_label, "info")
