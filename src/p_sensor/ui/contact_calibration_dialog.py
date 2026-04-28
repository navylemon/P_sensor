from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import math
import queue
import threading
import time

import pyqtgraph as pg
from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


@dataclass(slots=True)
class ContactCalibrationSample:
    position_mm: float
    signal_value: float


@dataclass(slots=True)
class ContactCalibrationResult:
    selected_position_mm: float
    recommended_position_mm: float | None
    baseline_value: float
    samples: list[ContactCalibrationSample]


@dataclass(frozen=True, slots=True)
class ContactCalibrationScanSettings:
    channel_index: int
    speed_mm_s: float
    step_mm: float
    travel_mm: float
    threshold: float
    baseline_s: float


class ContactCalibrationDialog(QDialog):
    def __init__(
        self,
        *,
        motion,
        read_signal: Callable[[int], float],
        soft_limit_checker: Callable[[int, float], tuple[bool, str]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Contact Calibration")
        self.resize(980, 680)
        self.motion = motion
        self.read_signal = read_signal
        self.soft_limit_checker = soft_limit_checker
        self._events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self.samples: list[ContactCalibrationSample] = []
        self.baseline_value: float | None = None
        self.recommended_position_mm: float | None = None
        self.selected_position_mm: float | None = None
        self.result: ContactCalibrationResult | None = None
        self._recommend_line: pg.InfiniteLine | None = None
        self._selected_line: pg.InfiniteLine | None = None

        self.channel_spin = QSpinBox()
        self.channel_spin.setRange(0, 63)
        self.channel_spin.setValue(0)
        self.speed_spin = self._new_spin(0.001, 10.0, 3, 0.02, 0.01)
        self.step_spin = self._new_spin(0.001, 5.0, 3, 0.01, 0.001)
        self.travel_spin = self._new_spin(0.001, 100.0, 3, 1.0, 0.1)
        self.threshold_spin = self._new_spin(0.001, 1_000_000.0, 3, 1.0, 0.1)
        self.baseline_spin = self._new_spin(0.0, 60.0, 3, 0.2, 0.05)
        self.status_label = QLabel(
            "Ready. Confirm the probe is above the sample, then start a slow scan."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("contact_calibration_status")

        self.plot_widget = pg.PlotWidget()
        self.plot_widget.setBackground("#0D1117")
        self.plot_widget.showGrid(x=True, y=True, alpha=0.18)
        self.plot_widget.setLabel("bottom", "Stage 1 Z position", units="mm")
        self.plot_widget.setLabel("left", "DAQ signal")
        self.signal_curve = self.plot_widget.plot([], [], pen=pg.mkPen("#58A6FF", width=2), symbol="o")
        self.plot_widget.scene().sigMouseClicked.connect(self._handle_plot_click)

        self.start_button = QPushButton("Auto Scan")
        self.stop_button = QPushButton("Stop")
        self.apply_button = QPushButton("Apply Contact Point")
        self.start_button.clicked.connect(self._start_scan)
        self.stop_button.clicked.connect(self._stop_scan)
        self.apply_button.clicked.connect(self._apply_selection)
        self.stop_button.setEnabled(False)
        self.apply_button.setEnabled(False)
        if self.motion is None:
            self.start_button.setEnabled(False)
            self.start_button.setToolTip("Connect Stage 1/Z, then reopen this wizard to enable Auto Scan.")
            self.status_label.setText(
                "Stage is not connected. Auto Scan requires Stage 1/Z."
            )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        content_row = QHBoxLayout()
        content_row.setContentsMargins(0, 0, 0, 0)
        content_row.setSpacing(8)

        guide_column = QVBoxLayout()
        guide_column.setContentsMargins(0, 0, 0, 0)
        guide_column.setSpacing(6)
        guide_column.addWidget(self._build_guide_group())
        settings_group = QGroupBox("Scan Settings")
        settings_group.setMinimumWidth(290)
        settings_group.setMaximumWidth(340)
        settings_grid = QGridLayout(settings_group)
        settings_grid.setHorizontalSpacing(6)
        settings_grid.setVerticalSpacing(4)
        settings_grid.addWidget(QLabel("Channel"), 0, 0)
        settings_grid.addWidget(self.channel_spin, 0, 1)
        settings_grid.addWidget(QLabel("Speed mm/s"), 0, 2)
        settings_grid.addWidget(self.speed_spin, 0, 3)
        settings_grid.addWidget(QLabel("Step mm"), 1, 0)
        settings_grid.addWidget(self.step_spin, 1, 1)
        settings_grid.addWidget(QLabel("Travel mm"), 1, 2)
        settings_grid.addWidget(self.travel_spin, 1, 3)
        settings_grid.addWidget(QLabel("dSignal"), 2, 0)
        settings_grid.addWidget(self.threshold_spin, 2, 1)
        settings_grid.addWidget(QLabel("Baseline s"), 2, 2)
        settings_grid.addWidget(self.baseline_spin, 2, 3)
        settings_grid.addWidget(self._setting_hint("DAQ channel used for the contact signal."), 3, 0, 1, 4)
        settings_grid.addWidget(self._setting_hint("Speed and Step control how gently Z approaches the sample."), 4, 0, 1, 4)
        settings_grid.addWidget(self._setting_hint("Travel is the maximum search distance. dSignal is the recommendation threshold."), 5, 0, 1, 4)
        guide_column.addWidget(settings_group)
        guide_column.addStretch(1)

        plot_column = QVBoxLayout()
        plot_column.setContentsMargins(0, 0, 0, 0)
        plot_column.setSpacing(6)
        graph_hint = QLabel(
            "Graph: blue points are DAQ signal vs Z position. Yellow marks the first threshold crossing. "
            "Green marks the contact point that will be applied. Click the graph to override the recommendation."
        )
        graph_hint.setWordWrap(True)
        graph_hint.setObjectName("contact_calibration_graph_hint")
        graph_hint.setStyleSheet("color: #9BA7B4;")
        plot_column.addWidget(graph_hint)
        plot_column.addWidget(self.plot_widget, 1)
        content_row.addLayout(guide_column, 0)
        content_row.addLayout(plot_column, 1)

        layout.addWidget(self.status_label)
        layout.addLayout(content_row, 1)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.apply_button)
        button_row.addStretch(1)
        close_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_box.rejected.connect(self.reject)
        button_row.addWidget(close_box)
        layout.addLayout(button_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer)
        self._timer.start(50)

    def _build_guide_group(self) -> QGroupBox:
        group = QGroupBox("How To Use")
        group.setMinimumWidth(290)
        group.setMaximumWidth(340)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        guide_texts = [
            "1. The wizard reads the selected DAQ channel during the Z scan.",
            "2. Connect Stage 1/Z and keep the probe above the sample.",
            "3. Use a small Step and Travel for the first run.",
            "4. Auto Scan moves Z downward until dSignal changes or Travel ends.",
            "5. Apply Contact Point stores a nominal contact point, not a hardware origin.",
        ]
        for text in guide_texts:
            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet("color: #D8E1EA;")
            layout.addWidget(label)
        warning = QLabel("Stop immediately if direction, sound, or clearance looks wrong.")
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "padding: 5px; border: 1px solid #D29922; border-radius: 4px; color: #F2CC60;"
        )
        warning.setObjectName("contact_calibration_warning")
        layout.addWidget(warning)
        return group

    def _setting_hint(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 10px; color: #9BA7B4;")
        return label

    def done(self, result: int) -> None:  # type: ignore[override]
        self._stop_scan()
        self._timer.stop()
        super().done(result)

    def _on_timer(self) -> None:
        self._drain_events()

    def _start_scan(self) -> None:
        if self.motion is None:
            self.status_label.setText("Connect Stage 1/Z, then reopen this wizard to enable Auto Scan.")
            return
        if self._worker is not None and self._worker.is_alive():
            return
        self.samples.clear()
        self.baseline_value = None
        self.recommended_position_mm = None
        self.selected_position_mm = None
        self.apply_button.setEnabled(False)
        self.signal_curve.setData([], [])
        self._remove_line("_recommend_line")
        self._remove_line("_selected_line")
        self._stop_event.clear()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText(
            "Scanning Stage 1/Z downward. Stop if the probe approaches the sample too quickly or the direction is wrong."
        )
        settings = ContactCalibrationScanSettings(
            channel_index=self.channel_spin.value(),
            speed_mm_s=self.speed_spin.value(),
            step_mm=self.step_spin.value(),
            travel_mm=self.travel_spin.value(),
            threshold=self.threshold_spin.value(),
            baseline_s=self.baseline_spin.value(),
        )
        self._worker = threading.Thread(target=self._scan_worker, args=(settings,), daemon=True)
        self._worker.start()

    def _stop_scan(self) -> None:
        self._stop_event.set()
        self.stop_button.setEnabled(False)

    def reject(self) -> None:  # type: ignore[override]
        if self._scan_is_active():
            self._stop_scan()
            self.status_label.setText("Stopping scan. Wait for the current stage move to finish before closing.")
            return
        super().reject()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self._scan_is_active():
            self._stop_scan()
            self.status_label.setText("Stopping scan. Wait for the current stage move to finish before closing.")
            event.ignore()
            return
        super().closeEvent(event)

    def _scan_is_active(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def _scan_worker(self, settings: ContactCalibrationScanSettings) -> None:
        try:
            if self.motion is None:
                raise RuntimeError("Stage is not connected.")
            axis = 1
            threshold = settings.threshold
            baseline_count = max(1, math.ceil(settings.baseline_s / 0.05))
            baseline_values = []
            for index in range(baseline_count):
                if self._stop_event.is_set():
                    self._events.put(("stopped", None))
                    return
                baseline_values.append(self.read_signal(settings.channel_index))
                if index < baseline_count - 1:
                    time.sleep(0.05)
            baseline = sum(baseline_values) / len(baseline_values)
            self._events.put(("baseline", baseline))
            self._set_velocity(axis=axis, speed_mm_s=settings.speed_mm_s)

            traveled = 0.0
            step_count = math.ceil(settings.travel_mm / settings.step_mm)
            for _ in range(step_count):
                if self._stop_event.is_set():
                    self._events.put(("stopped", None))
                    return
                move_mm = min(settings.step_mm, settings.travel_mm - traveled)
                if move_mm <= 0:
                    break
                current_position = self.motion.get_axis_position_mm(axis)
                target_position = current_position - move_mm
                if self.soft_limit_checker is not None:
                    allowed, message = self.soft_limit_checker(axis, target_position)
                    if not allowed:
                        raise RuntimeError(message)
                self.motion.move_relative_mm(axis=axis, delta_mm=-move_mm)
                self.motion.wait_until_ready()
                traveled += move_mm
                position = self.motion.get_axis_position_mm(axis)
                signal_value = self.read_signal(settings.channel_index)
                sample = ContactCalibrationSample(position_mm=position, signal_value=signal_value)
                self._events.put(("sample", sample))
                if abs(signal_value - baseline) >= threshold:
                    self._events.put(("recommend", position))
                    threshold = float("inf")
            self._events.put(("done", None))
        except Exception as exc:
            self._events.put(("error", str(exc)))

    def _set_velocity(self, *, axis: int, speed_mm_s: float) -> None:
        velocity_mm_min = speed_mm_s * 60.0
        try:
            self.motion.set_velocity_mm_min(axis=axis, velocity_mm_min=velocity_mm_min)
        except TypeError:
            self.motion.set_velocity_mm_min(velocity_mm_min)

    def _drain_events(self) -> None:
        while True:
            try:
                event, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if event == "baseline":
                self.baseline_value = float(payload)
                self.status_label.setText(
                    f"Baseline {self.baseline_value:.6g}. Moving in small steps and watching for dSignal change."
                )
            elif event == "sample":
                sample = payload
                if isinstance(sample, ContactCalibrationSample):
                    self.samples.append(sample)
                    self.signal_curve.setData(
                        [item.position_mm for item in self.samples],
                        [item.signal_value for item in self.samples],
                    )
            elif event == "recommend":
                self.recommended_position_mm = float(payload)
                if self.selected_position_mm is None:
                    self.selected_position_mm = self.recommended_position_mm
                self._set_line("_recommend_line", self.recommended_position_mm, "#F2CC60")
                self._set_line("_selected_line", self.selected_position_mm, "#3FB950")
                self.apply_button.setEnabled(False)
                self.status_label.setText(
                    f"Recommended contact point: {self.recommended_position_mm:.6g} mm. "
                    "The point can be applied after the scan finishes."
                )
            elif event == "done":
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                if self.recommended_position_mm is None:
                    self.status_label.setText(
                        "Scan complete without a threshold crossing. Click the graph to select a nominal contact point, "
                        "or reduce dSignal / increase Travel and scan again."
                    )
                else:
                    self.apply_button.setEnabled(True)
                    self.status_label.setText(
                        "Scan complete. Apply the recommendation or click another point before applying."
                    )
            elif event == "stopped":
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.apply_button.setEnabled(self.selected_position_mm is not None)
                self.status_label.setText("Scan stopped. Check clearance and current Z position before scanning again.")
            elif event == "error":
                self.start_button.setEnabled(True)
                self.stop_button.setEnabled(False)
                self.apply_button.setEnabled(False)
                self.status_label.setText(f"Scan failed: {payload}")

    def _handle_plot_click(self, event) -> None:
        if self._scan_is_active():
            return
        if not self.samples:
            return
        view_box = self.plot_widget.getPlotItem().vb
        if not view_box.sceneBoundingRect().contains(event.scenePos()):
            return
        point = view_box.mapSceneToView(event.scenePos())
        self.selected_position_mm = point.x()
        self._set_line("_selected_line", self.selected_position_mm, "#3FB950")
        self.apply_button.setEnabled(True)
        self.status_label.setText(
            f"Selected contact point: {self.selected_position_mm:.6g} mm. "
            "Apply stores this as the nominal contact point."
        )

    def _apply_selection(self) -> None:
        if self._scan_is_active():
            self.status_label.setText("Wait for the current scan to finish before applying the contact point.")
            return
        if self.selected_position_mm is None or self.baseline_value is None:
            return
        self.result = ContactCalibrationResult(
            selected_position_mm=self.selected_position_mm,
            recommended_position_mm=self.recommended_position_mm,
            baseline_value=self.baseline_value,
            samples=list(self.samples),
        )
        self.accept()

    def _set_line(self, attr_name: str, position_mm: float, color: str) -> None:
        self._remove_line(attr_name)
        line = pg.InfiniteLine(pos=position_mm, angle=90, pen=pg.mkPen(color, width=2))
        self.plot_widget.addItem(line)
        setattr(self, attr_name, line)

    def _remove_line(self, attr_name: str) -> None:
        line = getattr(self, attr_name)
        if line is None:
            return
        try:
            self.plot_widget.removeItem(line)
        finally:
            setattr(self, attr_name, None)

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
        spin.setAlignment(Qt.AlignmentFlag.AlignRight)
        return spin
