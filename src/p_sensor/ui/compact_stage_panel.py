from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from p_sensor.config import APP_ROOT
from p_sensor.motion import (
    ShotController,
    ShotMotionConfig,
    create_shot_controller,
    is_simulated_motion_config,
    load_shot_motion_config,
)


DEFAULT_STAGE_CONFIG = APP_ROOT / "dev_local" / "config" / "stage_shot702_osms20_35.local.json"
FALLBACK_STAGE_CONFIG = APP_ROOT / "config" / "stage_shot702_osms20_35.example.json"
SIMULATED_STAGE_CONFIG = APP_ROOT / "config" / "stage_simulated.example.json"


class CompactStagePanel(QWidget):
    log_requested = Signal(str)
    error_reported = Signal(str, str)
    config_loaded = Signal(object, str)
    recovery_required = Signal(str)
    status_changed = Signal(str, str)
    position_changed = Signal(int, float)
    active_axis_changed = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        self.setStyleSheet(
            """
            CompactStagePanel QLabel {
                font-size: 11px;
            }
            CompactStagePanel QComboBox,
            CompactStagePanel QDoubleSpinBox,
            CompactStagePanel QPushButton {
                min-height: 18px;
                max-height: 20px;
                padding: 0px 3px;
            }
            """
        )
        self.config_path: Path | None = None
        self.config: ShotMotionConfig | None = None
        self.controller: ShotController | None = None
        self._target_validator: Callable[[int, float], tuple[bool, str]] | None = None
        self._status_poll_enabled = True
        self._status_polling = False
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status_from_timer)

        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Simulation", "simulation")
        self.backend_combo.addItem("SHOT-702", "shot702")
        self.backend_combo.currentIndexChanged.connect(self._handle_backend_changed)
        self.port_combo = QComboBox()
        self.port_combo.setEditable(True)
        self.port_combo.setMinimumWidth(90)
        self.port_combo.currentTextChanged.connect(self._handle_port_changed)
        self.refresh_ports_button = QPushButton("Ports")
        self.refresh_ports_button.setToolTip("Refresh available serial COM ports.")
        self.refresh_ports_button.clicked.connect(lambda _checked=False: self._refresh_port_choices())
        self.connect_button = QPushButton("Connect")
        self.disconnect_button = QPushButton("Disc.")
        self.connect_button.clicked.connect(self.connect_stage)
        self.disconnect_button.clicked.connect(self.disconnect_stage)

        self.status_label = QLabel("Disconnected")
        self.axis_combo = QComboBox()
        self.axis_combo.addItem("Stage 1 / Z", 1)
        self.axis_combo.addItem("Stage 2 / X", 2)
        self.axis_combo.currentIndexChanged.connect(self._handle_axis_changed)
        self.position_label = QLabel("-- mm")
        self.step_spin = self._new_spin(0.001, 10.0, 3, 0.1, 0.1)
        self.target_spin = self._new_spin(-1000.0, 1000.0, 3, 0.0, 0.1)

        self.minus_button = QPushButton("Step -")
        self.plus_button = QPushButton("Step +")
        self.goto_zero_button = QPushButton("SW 0")
        self.goto_zero_button.setToolTip("Move to the current session software zero.")
        self.zero_here_button = QPushButton("Set 0")
        self.zero_here_button.setToolTip("Set the current position as software zero.")
        self.origin_button = QPushButton("HW Home")
        self.origin_button.setToolTip("Run the controller hardware home command.")
        self.hold_button = QPushButton("Hold")
        self.free_button = QPushButton("Free")
        self.stop_button = QPushButton("Stop")
        self.status_button = QPushButton("Status")
        self.absolute_button = QPushButton("Move")
        self.minus_button.clicked.connect(lambda: self._move_relative(-self.step_spin.value()))
        self.plus_button.clicked.connect(lambda: self._move_relative(self.step_spin.value()))
        self.goto_zero_button.clicked.connect(lambda: self._move_absolute(0.0))
        self.zero_here_button.clicked.connect(self._zero_here)
        self.origin_button.clicked.connect(self._origin)
        self.hold_button.clicked.connect(lambda: self._set_hold(True))
        self.free_button.clicked.connect(lambda: self._set_hold(False))
        self.stop_button.clicked.connect(self.emergency_stop)
        self.status_button.clicked.connect(lambda _checked=False: self.refresh_status())
        self.absolute_button.clicked.connect(lambda: self._move_absolute(self.target_spin.value()))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(1)
        for column in range(8):
            grid.setColumnStretch(column, 1)
        grid.addWidget(QLabel("Backend"), 0, 0)
        grid.addWidget(self.backend_combo, 0, 1)
        grid.addWidget(QLabel("Port"), 0, 2)
        grid.addWidget(self.port_combo, 0, 3, 1, 2)
        grid.addWidget(self.refresh_ports_button, 0, 5)
        grid.addWidget(self.connect_button, 0, 6)
        grid.addWidget(self.disconnect_button, 0, 7)
        grid.addWidget(QLabel("Axis"), 1, 0)
        grid.addWidget(self.axis_combo, 1, 1)
        grid.addWidget(self.status_label, 1, 2)
        grid.addWidget(self.position_label, 1, 3, 1, 3)
        grid.addWidget(self.status_button, 1, 6)
        grid.addWidget(self.stop_button, 1, 7)
        grid.addWidget(QLabel("Step"), 2, 0)
        grid.addWidget(self.step_spin, 2, 1)
        grid.addWidget(self.minus_button, 2, 2)
        grid.addWidget(self.plus_button, 2, 3)
        grid.addWidget(self.hold_button, 2, 4)
        grid.addWidget(self.free_button, 2, 5)
        grid.addWidget(QLabel("Abs"), 3, 0)
        grid.addWidget(self.target_spin, 3, 1)
        grid.addWidget(self.absolute_button, 3, 2)
        grid.addWidget(self.goto_zero_button, 3, 3)
        grid.addWidget(self.origin_button, 3, 4)
        grid.addWidget(self.zero_here_button, 3, 5)
        layout.addLayout(grid)

        for widget in (
            self.backend_combo,
            self.port_combo,
            self.refresh_ports_button,
            self.connect_button,
            self.disconnect_button,
            self.status_button,
            self.axis_combo,
            self.step_spin,
            self.target_spin,
            self.minus_button,
            self.plus_button,
            self.goto_zero_button,
            self.zero_here_button,
            self.origin_button,
            self.hold_button,
            self.free_button,
            self.stop_button,
            self.absolute_button,
        ):
            widget.setMinimumHeight(18)
            widget.setMaximumHeight(20)
            widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for button in (
            self.connect_button,
            self.disconnect_button,
            self.status_button,
            self.refresh_ports_button,
            self.minus_button,
            self.plus_button,
            self.goto_zero_button,
            self.zero_here_button,
            self.origin_button,
            self.hold_button,
            self.free_button,
            self.stop_button,
            self.absolute_button,
        ):
            button.setMinimumWidth(0)
        self.step_spin.setMaximumWidth(76)
        self.target_spin.setMaximumWidth(76)
        for label in (self.status_label, self.position_label):
            label.setMinimumWidth(0)
            label.setMinimumHeight(18)
            label.setMaximumHeight(20)
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self._load_initial_config()
        self._update_controls()

    def set_target_validator(self, validator: Callable[[int, float], tuple[bool, str]] | None) -> None:
        self._target_validator = validator

    def disconnect_stage(self) -> None:
        self._status_timer.stop()
        if self.controller is not None:
            try:
                self.controller.disconnect()
            finally:
                self.controller = None
        self._set_status("Disconnected", "muted")
        self._update_controls()

    def connect_stage(self) -> None:
        if self.config is None:
            self._emit_error("Stage Config Missing", "Load a stage config before connecting.")
            return
        try:
            self._apply_selected_port_to_config(emit=True)
            self.controller = create_shot_controller(self.config)
            message = self.controller.connect()
            self._set_status("Connected", "info")
            self.log_requested.emit(message)
            self.refresh_status()
            self._sync_status_timer()
        except Exception as exc:
            self.controller = None
            self._status_timer.stop()
            self._set_status("Error", "error")
            self._emit_error("Stage Connect Failed", str(exc))
        self._update_controls()

    def emergency_stop(self) -> None:
        controller = self._require_controller()
        if controller is None:
            return
        try:
            controller.emergency_stop()
            self._set_status("Recovery Required", "warning")
            self.recovery_required.emit("Emergency stop issued. Confirm stage state before continuing.")
            self.log_requested.emit("Stage emergency stop issued")
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Emergency Stop Failed", str(exc))

    def refresh_status(self, *, report_errors: bool = True) -> None:
        controller = self._require_controller(report_errors=report_errors)
        if controller is None:
            return
        try:
            status = controller.get_status()
            axis1_mm = controller.pulses_to_mm(status.axis1_position)
            axis2_mm = controller.pulses_to_mm(status.axis2_position)
            self.position_changed.emit(1, axis1_mm)
            self.position_changed.emit(2, axis2_mm)
            active_axis = self._active_axis()
            position_pulses = status.axis1_position if active_axis == 1 else status.axis2_position
            position_mm = axis1_mm if active_axis == 1 else axis2_mm
            self.position_label.setText(f"{self._axis_label(active_axis)} {position_mm:.3f} mm / {position_pulses} p")
            self._set_status("Ready" if status.is_ready else "Busy", "info" if status.is_ready else "running")
        except Exception as exc:
            self._set_status("Error", "error")
            self._status_timer.stop()
            if report_errors:
                self._emit_error("Stage Status Failed", str(exc))

    def set_live_status_polling(self, enabled: bool) -> None:
        self._status_poll_enabled = enabled
        self._sync_status_timer()

    def _sync_status_timer(self) -> None:
        if self._status_poll_enabled and self.controller is not None:
            if not self._status_timer.isActive():
                self._status_timer.start()
            return
        self._status_timer.stop()

    def _refresh_status_from_timer(self) -> None:
        if self._status_polling or self.controller is None:
            return
        self._status_polling = True
        try:
            self.refresh_status(report_errors=False)
        finally:
            self._status_polling = False

    def _load_initial_config(self) -> None:
        path = self._backend_config_path(str(self.backend_combo.currentData() or "simulation"))
        if path.exists():
            self._load_config(path)

    def _backend_config_path(self, backend: str) -> Path:
        if backend == "simulation":
            return SIMULATED_STAGE_CONFIG
        return DEFAULT_STAGE_CONFIG if DEFAULT_STAGE_CONFIG.exists() else FALLBACK_STAGE_CONFIG

    def _handle_backend_changed(self) -> None:
        backend = str(self.backend_combo.currentData() or "shot702")
        path = self._backend_config_path(backend)
        if not path.exists():
            self._emit_error("Stage Config Missing", f"Stage backend config not found: {path}")
            return
        self._load_config(path)

    def _load_config(self, path: Path) -> None:
        try:
            config = load_shot_motion_config(path)
            self.config = config
            self.config_path = path
            self._set_active_axis(config.axis)
            self.target_spin.setRange(config.min_position_mm, config.max_position_mm)
            self._refresh_port_choices(config.port)
            self.config_loaded.emit(config, str(path))
            if self.controller is None:
                self._set_status("Config Loaded", "muted")
            self.log_requested.emit(f"Stage config loaded: {path}")
        except Exception as exc:
            self._set_status("Config Error", "error")
            self._emit_error("Stage Config Failed", str(exc))
        self._update_controls()

    def _available_serial_ports(self) -> list[tuple[str, str]]:
        try:
            from serial.tools import list_ports
        except Exception:
            return []
        ports = []
        for port in list_ports.comports():
            device = str(getattr(port, "device", "") or "").strip()
            if not device:
                continue
            description = str(getattr(port, "description", "") or device).strip()
            ports.append((device, description))
        return sorted(ports, key=lambda item: item[0].upper())

    def _refresh_port_choices(self, preferred_port: str | None = None) -> None:
        if self.config is None:
            return
        selected_port = str(preferred_port or self.port_combo.currentText() or self.config.port).strip()
        blocked = self.port_combo.blockSignals(True)
        self.port_combo.clear()
        if is_simulated_motion_config(self.config):
            self.port_combo.addItem("SIM", "SIM")
            self.port_combo.setCurrentText("SIM")
            self.port_combo.setToolTip("Simulation backend does not use a serial COM port.")
            self.port_combo.blockSignals(blocked)
            return

        discovered_ports = self._available_serial_ports()
        if not discovered_ports and selected_port:
            self.port_combo.addItem(selected_port, selected_port)
        for device, description in discovered_ports:
            self.port_combo.addItem(device, device)
            self.port_combo.setItemData(self.port_combo.count() - 1, description, role=Qt.ItemDataRole.ToolTipRole)
        if selected_port:
            if self.port_combo.findText(selected_port) < 0:
                self.port_combo.insertItem(0, selected_port, selected_port)
            self.port_combo.setCurrentText(selected_port)
        self.port_combo.setToolTip("Select the SHOT-702 serial COM port. Use Ports after reconnecting USB.")
        self.port_combo.blockSignals(blocked)
        self._apply_selected_port_to_config(emit=True)

    def _selected_port(self) -> str:
        return self.port_combo.currentText().strip()

    def _handle_port_changed(self) -> None:
        self._apply_selected_port_to_config(emit=True)

    def _apply_selected_port_to_config(self, *, emit: bool) -> None:
        if self.config is None or is_simulated_motion_config(self.config):
            return
        selected_port = self._selected_port()
        if not selected_port or selected_port == self.config.port:
            return
        self.config = replace(self.config, port=selected_port)
        if emit and self.config_path is not None:
            self.config_loaded.emit(self.config, str(self.config_path))

    def _active_axis(self) -> int:
        axis = self.axis_combo.currentData()
        return int(axis) if axis in {1, 2} else 1

    def _set_active_axis(self, axis: int) -> None:
        index = self.axis_combo.findData(axis)
        if index >= 0:
            blocked = self.axis_combo.blockSignals(True)
            self.axis_combo.setCurrentIndex(index)
            self.axis_combo.blockSignals(blocked)
            self.active_axis_changed.emit(axis)

    def _handle_axis_changed(self) -> None:
        axis = self._active_axis()
        self.active_axis_changed.emit(axis)
        self.log_requested.emit(f"Manual stage target selected: {self._axis_label(axis)}")
        if self.controller is not None:
            self.refresh_status()

    def _axis_label(self, axis: int) -> str:
        return "Z" if axis == 1 else "X"

    def _move_relative(self, delta_mm: float) -> None:
        controller = self._require_controller()
        if controller is None:
            return
        axis = self._active_axis()
        try:
            target_mm = controller.get_axis_position_mm(axis) + delta_mm
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Stage Status Failed", str(exc))
            return
        if not self._target_allowed(axis, target_mm):
            return
        try:
            self._set_status("Busy", "running")
            controller.move_relative_mm(axis=axis, delta_mm=delta_mm)
            controller.wait_until_ready()
            self.refresh_status()
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Stage Move Failed", str(exc))

    def _move_absolute(self, position_mm: float) -> None:
        controller = self._require_controller()
        if controller is None:
            return
        axis = self._active_axis()
        if not self._target_allowed(axis, position_mm):
            return
        try:
            self._set_status("Busy", "running")
            controller.move_absolute_mm(axis=axis, position_mm=position_mm)
            controller.wait_until_ready()
            self.refresh_status()
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Stage Move Failed", str(exc))

    def _origin(self) -> None:
        controller = self._require_controller()
        if controller is None:
            return
        try:
            self._set_status("Busy", "running")
            controller.origin(axis=self._active_axis(), reset_logical_zero=False)
            self.refresh_status()
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Stage Origin Failed", str(exc))

    def _zero_here(self) -> None:
        controller = self._require_controller()
        if controller is None:
            return
        try:
            controller.reset_logical_zero(axis=self._active_axis())
            self.refresh_status()
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Stage Zero Failed", str(exc))

    def _set_hold(self, hold: bool) -> None:
        controller = self._require_controller()
        if controller is None:
            return
        try:
            controller.set_motor_hold(axis=self._active_axis(), hold=hold)
            self.log_requested.emit("Stage hold enabled" if hold else "Stage hold released")
        except Exception as exc:
            self._set_status("Error", "error")
            self._emit_error("Stage Hold Failed", str(exc))

    def _require_controller(self, *, report_errors: bool = True) -> ShotController | None:
        if self.controller is None:
            if report_errors:
                self._emit_error("Stage Disconnected", "Connect the stage before sending motion commands.")
            return None
        return self.controller

    def _target_allowed(self, axis: int, target_mm: float) -> bool:
        if self._target_validator is None:
            return True
        allowed, message = self._target_validator(axis, target_mm)
        if allowed:
            return True
        self._set_status("Soft Limit", "warning")
        self.log_requested.emit(f"Stage soft limit blocked: {message}")
        return False

    def _update_controls(self) -> None:
        connected = self.controller is not None
        self.backend_combo.setEnabled(not connected)
        port_selectable = self.config is not None and not is_simulated_motion_config(self.config)
        self.port_combo.setEnabled(not connected and port_selectable)
        self.refresh_ports_button.setEnabled(not connected and port_selectable)
        for button in (
            self.disconnect_button,
            self.minus_button,
            self.plus_button,
            self.goto_zero_button,
            self.zero_here_button,
            self.origin_button,
            self.hold_button,
            self.free_button,
            self.stop_button,
            self.status_button,
            self.absolute_button,
        ):
            button.setEnabled(connected)
        self.connect_button.setEnabled(self.config is not None and not connected)

    def _set_status(self, text: str, tone: str) -> None:
        self.status_label.setText(text)
        self.status_changed.emit(text, tone)

    def _emit_error(self, title: str, message: str) -> None:
        self.error_reported.emit(title, message)

    def _new_spin(
        self,
        minimum: float,
        maximum: float,
        decimals: int,
        value: float,
        step: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSingleStep(step)
        return spin
