from __future__ import annotations

import time
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Callable

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from p_sensor.config import APP_ROOT, resolve_runtime_path
from p_sensor.motion.shot_series import (
    MotionError,
    ShotController,
    ShotMotionConfig,
    load_shot_motion_config,
)


CONFIRMED_CONTROLLER_MODEL = "OPTOSIGMA SHOT-702"
CONFIRMED_STAGE_MODEL = "OPTOSIGMA OSMS20-35"
DEFAULT_STAGE_CONFIG_PATH = APP_ROOT / "dev_local" / "config" / "stage_shot702_osms20_35.local.json"
FALLBACK_STAGE_CONFIG_PATH = APP_ROOT / "config" / "stage_shot702_osms20_35.example.json"
MAX_STAGE_COUNT = 2


@dataclass(frozen=True, slots=True)
class StageStatusSnapshot:
    axis1_position: int
    axis2_position: int
    pulses_per_mm: float
    command_ack: str
    stop_ack: str
    ready_ack: str

    def position_mm(self, axis: int) -> float:
        pulses = self.axis1_position if axis == 1 else self.axis2_position
        return pulses / self.pulses_per_mm

    def position_pulses(self, axis: int) -> int:
        return self.axis1_position if axis == 1 else self.axis2_position


def make_status_snapshot(controller: ShotController) -> StageStatusSnapshot:
    status = controller.get_status()
    return StageStatusSnapshot(
        axis1_position=status.axis1_position,
        axis2_position=status.axis2_position,
        pulses_per_mm=controller.config.pulses_per_mm,
        command_ack=status.command_ack,
        stop_ack=status.stop_ack,
        ready_ack=status.ready_ack,
    )


class StageDirectionDiagram(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._axes = [1]
        self.setMinimumHeight(250)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_axes(self, axes: list[int]) -> None:
        self._axes = axes or [1]
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        hint_font = QFont(self.font())
        hint_font.setPointSize(9)
        painter.setFont(hint_font)
        painter.setPen(QColor("#9aa8b8"))
        painter.drawText(
            rect.adjusted(4, 0, -4, -8),
            Qt.AlignLeft | Qt.AlignTop,
            "설치 기준: Stage 1은 Z축, Stage 2는 X축으로 이동합니다.",
        )

        plot_rect = rect.adjusted(4, 24, -4, -24)
        self._draw_direction_plot(painter, plot_rect, set(self._axes))

        painter.setFont(hint_font)
        painter.setPen(QColor("#7f8b99"))
        painter.drawText(
            rect.adjusted(4, rect.height() - 19, -4, -2),
            Qt.AlignLeft | Qt.AlignBottom,
            "처음에는 0.01 mm로 실제 방향을 확인하세요.",
        )

    def _draw_direction_plot(self, painter: QPainter, rect: QRectF, axes: set[int]) -> None:
        painter.setPen(QPen(QColor("#253442"), 1))
        painter.setBrush(QBrush(QColor("#151f29")))
        painter.drawRoundedRect(rect, 5, 5)

        center = rect.center()
        block = QRectF(center.x() - 22, center.y() - 14, 44, 28)
        axis_pen = QPen(QColor("#536172"), 3, Qt.SolidLine, Qt.RoundCap)
        active_z = 1 in axes
        active_x = 2 in axes

        title_font = QFont(self.font())
        title_font.setPointSize(10)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor("#ffffff"))
        title_parts = []
        if active_z:
            title_parts.append("Stage 1 · Z축")
        if active_x:
            title_parts.append("Stage 2 · X축")
        painter.drawText(rect.adjusted(8, 6, -8, -6), Qt.AlignLeft | Qt.AlignTop, " / ".join(title_parts))

        if active_z:
            x = center.x()
            top = rect.top() + 40
            bottom = rect.bottom() - 30
            painter.setPen(axis_pen)
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))
            self._draw_arrow(
                painter,
                QPointF(x, center.y() - 18),
                QPointF(x, top + 2),
                QColor("#8bd3c7"),
                "S1 +: Z축 위",
                QRectF(rect.left() + 8, top + 1, x - rect.left() - 24, 28),
                Qt.AlignLeft,
            )
            self._draw_arrow(
                painter,
                QPointF(x, center.y() + 18),
                QPointF(x, bottom - 2),
                QColor("#f6c177"),
                "S1 -: Z축 아래",
                QRectF(x + 18, bottom - 29, rect.right() - x - 26, 28),
                Qt.AlignRight,
            )

        if active_x:
            y = center.y()
            left = rect.left() + 18
            right = rect.right() - 18
            painter.setPen(axis_pen)
            painter.drawLine(QPointF(left, y), QPointF(right, y))
            self._draw_arrow(
                painter,
                QPointF(center.x() - 28, y),
                QPointF(left + 4, y),
                QColor("#f6c177"),
                "S2 -: X축 좌측",
                QRectF(left, y + 13, center.x() - left - 34, 36),
                Qt.AlignLeft,
            )
            self._draw_arrow(
                painter,
                QPointF(center.x() + 28, y),
                QPointF(right - 4, y),
                QColor("#8bd3c7"),
                "S2 +: X축 우측",
                QRectF(center.x() + 34, y + 13, right - center.x() - 34, 36),
                Qt.AlignRight,
            )

        def draw_current_block() -> None:
            painter.setPen(QPen(QColor("#88d9c8"), 1))
            painter.setBrush(QBrush(QColor("#1f6f63")))
            painter.drawRoundedRect(block, 5, 5)

            small_font = QFont(self.font())
            small_font.setPointSize(9)
            small_font.setBold(True)
            painter.setFont(small_font)
            painter.setPen(QColor("#e8fff8"))
            painter.drawText(block, Qt.AlignCenter, "현재")

        draw_current_block()

    def _draw_arrow(
        self,
        painter: QPainter,
        start: QPointF,
        end: QPointF,
        color: QColor,
        label: str,
        label_rect: QRectF,
        label_alignment: Qt.AlignmentFlag,
    ) -> None:
        painter.setPen(QPen(color, 3, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(start, end)

        dx = end.x() - start.x()
        dy = end.y() - start.y()
        length = max(1.0, math.hypot(dx, dy))
        ux = dx / length
        uy = dy / length
        px = -uy
        py = ux
        head_length = 11
        head_width = 6
        head = QPolygonF(
            [
                end,
                QPointF(
                    end.x() - ux * head_length + px * head_width,
                    end.y() - uy * head_length + py * head_width,
                ),
                QPointF(
                    end.x() - ux * head_length - px * head_width,
                    end.y() - uy * head_length - py * head_width,
                ),
            ]
        )
        painter.setBrush(QBrush(color))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(head)

        label_font = QFont(self.font())
        label_font.setPointSize(9)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setPen(color)
        painter.drawText(label_rect, label_alignment | Qt.AlignVCenter | Qt.TextWordWrap, label)


class TouchKeypadDialog(QDialog):
    def __init__(self, *, title: str, initial_value: str, allow_decimal: bool, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumSize(420, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        self.value_edit = QLineEdit(initial_value)
        self.value_edit.setAlignment(Qt.AlignRight)
        self.value_edit.setMinimumHeight(58)
        self.value_edit.setObjectName("KeypadDisplay")
        layout.addWidget(self.value_edit)

        grid = QGridLayout()
        grid.setSpacing(8)
        keys = [
            ("7", 0, 0),
            ("8", 0, 1),
            ("9", 0, 2),
            ("4", 1, 0),
            ("5", 1, 1),
            ("6", 1, 2),
            ("1", 2, 0),
            ("2", 2, 1),
            ("3", 2, 2),
            ("+/-", 3, 0),
            ("0", 3, 1),
            (".", 3, 2),
        ]
        for text, row, column in keys:
            button = QPushButton(text)
            button.setMinimumHeight(68)
            button.setObjectName("KeypadButton")
            button.clicked.connect(lambda checked=False, value=text: self._press(value, allow_decimal))
            grid.addWidget(button, row, column)

        clear_button = QPushButton("지움")
        clear_button.setMinimumHeight(62)
        clear_button.clicked.connect(lambda: self.value_edit.setText(""))
        back_button = QPushButton("한칸 삭제")
        back_button.setMinimumHeight(62)
        back_button.clicked.connect(lambda: self.value_edit.setText(self.value_edit.text()[:-1]))
        grid.addWidget(clear_button, 4, 0)
        grid.addWidget(back_button, 4, 1, 1, 2)
        layout.addLayout(grid)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("입력")
        buttons.button(QDialogButtonBox.Cancel).setText("취소")
        buttons.button(QDialogButtonBox.Ok).setMinimumHeight(54)
        buttons.button(QDialogButtonBox.Cancel).setMinimumHeight(54)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> float:
        text = self.value_edit.text().strip()
        if text in {"", "-", ".", "-."}:
            return 0.0
        return float(text)

    def _press(self, key: str, allow_decimal: bool) -> None:
        text = self.value_edit.text()
        if key == "+/-":
            self.value_edit.setText(text[1:] if text.startswith("-") else f"-{text}")
            return
        if key == "." and (not allow_decimal or "." in text):
            return
        self.value_edit.setText(f"{text}{key}")


class StageControlPanel(QFrame):
    action_requested = Signal(int, str, object)

    def __init__(self, axis: int) -> None:
        super().__init__()
        self.axis = axis
        self.setObjectName("StageControlPanel")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        header_card = QFrame()
        header_card.setObjectName("StageHeaderCard")
        header_card.setMinimumHeight(62)
        header_card.setMaximumHeight(72)
        header = QHBoxLayout(header_card)
        header.setContentsMargins(10, 6, 10, 6)
        header.setSpacing(8)

        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title = QLabel(f"Stage {axis}")
        title.setObjectName("StagePanelTitle")
        driver = QLabel(f"SHOT-702 driver {axis}")
        driver.setObjectName("StagePanelDriver")
        title_box.addWidget(title)
        title_box.addWidget(driver)

        position_box = QVBoxLayout()
        position_box.setSpacing(2)
        position_title = QLabel("현재 위치")
        position_title.setObjectName("StageSmallCaption")
        self.position_label = QLabel("-- mm")
        self.position_label.setObjectName("StagePanelPosition")
        self.position_label.setAlignment(Qt.AlignRight)
        position_box.addWidget(position_title, alignment=Qt.AlignRight)
        position_box.addWidget(self.position_label, alignment=Qt.AlignRight)

        header.addLayout(title_box, stretch=1)
        header.addLayout(position_box)
        layout.addWidget(header_card)

        move_title = QLabel("수동 이동")
        move_title.setObjectName("StageSectionTitle")
        move_hint = QLabel("상단의 기본 이동량만큼 이 스테이지만 이동합니다.")
        move_hint.setObjectName("StageHint")
        move_hint.setMaximumHeight(16)
        layout.addWidget(move_title)
        layout.addWidget(move_hint)

        move_grid = QGridLayout()
        move_grid.setHorizontalSpacing(8)
        move_grid.setVerticalSpacing(7)
        self.minus_button = self._make_touch_button("음의 방향으로 이동 (-)", "NegativeMoveButton")
        self.plus_button = self._make_touch_button("양의 방향으로 이동 (+)", "PositiveMoveButton")
        self.zero_move_button = self._make_touch_button("논리 원점(0 mm)으로 이동")
        self.zero_here_button = self._make_touch_button("현재 위치를 0 mm로 설정")
        self.stop_button = self._make_touch_button("감속 정지")
        self.minus_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "move_negative", None))
        self.plus_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "move_positive", None))
        self.zero_move_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "goto_zero", None))
        self.zero_here_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "zero_here", None))
        self.stop_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "slow_stop", None))
        move_grid.addWidget(self.minus_button, 0, 0)
        move_grid.addWidget(self.plus_button, 0, 1)
        move_grid.addWidget(self.zero_move_button, 1, 0)
        move_grid.addWidget(self.zero_here_button, 1, 1)
        move_grid.addWidget(self.stop_button, 2, 0, 1, 2)
        layout.addLayout(move_grid)

        setup_title = QLabel("기준점과 모터 상태")
        setup_title.setObjectName("StageSectionTitle")
        setup_hint = QLabel("원점복귀는 이동 명령이고, 현재 0 mm 설정은 기준점만 바꿉니다.")
        setup_hint.setObjectName("StageHint")
        setup_hint.setMaximumHeight(16)
        layout.addWidget(setup_title)
        layout.addWidget(setup_hint)

        setup_grid = QGridLayout()
        setup_grid.setHorizontalSpacing(8)
        setup_grid.setVerticalSpacing(7)
        self.home_button = self._make_touch_button("기계 원점복귀")
        self.home_zero_button = self._make_touch_button("원점복귀 후 0 mm 설정")
        self.hold_button = self._make_touch_button("모터 홀드(고정)")
        self.free_button = self._make_touch_button("모터 프리(해제)")
        self.speed_button = self._make_touch_button("속도 설정 적용")
        self.home_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "home", None))
        self.home_zero_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "home_zero", None))
        self.hold_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "hold", None))
        self.free_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "free", None))
        self.speed_button.clicked.connect(lambda: self.action_requested.emit(self.axis, "speed", None))
        setup_grid.addWidget(self.home_button, 0, 0)
        setup_grid.addWidget(self.home_zero_button, 0, 1)
        setup_grid.addWidget(self.hold_button, 1, 0)
        setup_grid.addWidget(self.free_button, 1, 1)
        setup_grid.addWidget(self.speed_button, 2, 0, 1, 2)
        layout.addLayout(setup_grid)

        target_title = QLabel("절대 위치 이동")
        target_title.setObjectName("StageSectionTitle")
        target_hint = QLabel("입력한 목표 위치(mm)로 이동합니다.")
        target_hint.setObjectName("StageHint")
        target_hint.setMaximumHeight(16)
        layout.addWidget(target_title)
        layout.addWidget(target_hint)

        absolute_row = QHBoxLayout()
        absolute_row.setSpacing(8)
        self.absolute_spin = QDoubleSpinBox()
        self.absolute_spin.setDecimals(3)
        self.absolute_spin.setSuffix(" mm")
        self.absolute_spin.setAlignment(Qt.AlignRight)
        self.absolute_spin.setMinimumHeight(44)
        self.absolute_spin.setButtonSymbols(QDoubleSpinBox.PlusMinus)
        self.absolute_button = self._make_touch_button("목표 위치로 이동")
        self.absolute_button.clicked.connect(
            lambda: self.action_requested.emit(self.axis, "move_absolute", self.absolute_spin.value())
        )
        target_label = QLabel("목표 위치")
        target_label.setObjectName("StageTargetLabel")
        absolute_row.addWidget(target_label)
        absolute_row.addWidget(self.absolute_spin, stretch=1)
        absolute_row.addWidget(self.absolute_button)
        layout.addLayout(absolute_row)
        layout.addStretch(1)

    def set_position(self, position_mm: float, pulses: int) -> None:
        self.position_label.setText(f"{position_mm:.3f} mm / {pulses} p")

    def set_motion_range(self, minimum_mm: float, maximum_mm: float) -> None:
        self.absolute_spin.setRange(minimum_mm, maximum_mm)
        self.absolute_spin.setSingleStep(max(0.001, (maximum_mm - minimum_mm) / 100.0))

    def set_controls_enabled(self, enabled: bool) -> None:
        for button in self.findChildren(QPushButton):
            button.setEnabled(enabled)
        self.absolute_spin.setEnabled(enabled)

    def _make_touch_button(self, text: str, object_name: str = "StageButton") -> QPushButton:
        button = QPushButton(text)
        button.setObjectName(object_name)
        button.setMinimumHeight(44)
        button.setCursor(Qt.PointingHandCursor)
        return button


class StageWindow(QMainWindow):
    operation_finished = Signal(str, bool, str, object, bool)

    def __init__(self, config_path: Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("P_sensor Stage Control")
        self.resize(1280, 800)

        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="p-sensor-stage")
        self._io_lock = Lock()
        self._controller: ShotController | None = None
        self._config_path = self._resolve_initial_config_path(config_path)
        self._config: ShotMotionConfig | None = None
        self._busy = False
        self._connected = False
        self._keypad_open = False
        self._stage_panels: dict[int, StageControlPanel] = {}

        self.operation_finished.connect(self._handle_operation_finished)
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._refresh_status_from_timer)

        self._build_ui()
        self._apply_styles()
        self._load_config(self._config_path)
        self._rebuild_stage_panels()
        self._update_connection_state()

    def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
        if (
            self.touch_only_check.isChecked()
            and isinstance(watched, (QSpinBox, QDoubleSpinBox))
            and event.type() == QEvent.MouseButtonPress
        ):
            self._open_touch_keypad(watched)
            return True
        return super().eventFilter(watched, event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._status_timer.stop()
        controller = self._controller
        if controller is not None:
            try:
                with self._io_lock:
                    controller.disconnect()
                    self._controller = None
            except Exception as exc:
                self._log(f"종료 중 연결 해제 실패: {exc}")
        self._executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._sync_stage_panel_widths()

    def _build_ui(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 4, 8, 8)
        outer.setSpacing(5)
        self.setCentralWidget(central)

        header = QHBoxLayout()
        header.setSpacing(8)
        title = QLabel(f"스테이지 구동  |  {CONFIRMED_CONTROLLER_MODEL} / {CONFIRMED_STAGE_MODEL}")
        title.setObjectName("WindowTitle")

        self.touch_only_check = QCheckBox("터치스크린 온리")
        self.touch_only_check.setObjectName("TouchOnlyCheck")
        self.touch_only_check.setMinimumHeight(36)
        self.connection_badge = QLabel("연결 안 됨")
        self.connection_badge.setObjectName("StatusBadge")
        self.connection_badge.setMinimumHeight(36)
        self.emergency_button = QPushButton("비상 정지")
        self.emergency_button.setObjectName("DangerButton")
        self.emergency_button.setIcon(self.style().standardIcon(QStyle.SP_MessageBoxCritical))
        self.emergency_button.setMinimumHeight(40)
        self.emergency_button.clicked.connect(self._emergency_stop)

        header.addWidget(title, stretch=1)
        header.addWidget(self.touch_only_check)
        header.addWidget(self.connection_badge)
        header.addWidget(self.emergency_button)
        outer.addLayout(header)

        body = QGridLayout()
        body.setColumnStretch(0, 0)
        body.setColumnStretch(1, 1)
        body.setColumnStretch(2, 0)
        body.setRowStretch(0, 1)
        body.setRowStretch(1, 1)
        body.setHorizontalSpacing(6)
        body.setVerticalSpacing(6)
        outer.addLayout(body, stretch=1)

        body.addWidget(self._build_connection_panel(), 0, 0)
        body.addWidget(self._build_equipment_panel(), 1, 0)
        body.addWidget(self._build_motion_panel(), 0, 1, 2, 1)
        body.addWidget(self._build_right_panel(), 0, 2, 2, 1)

    def _build_equipment_panel(self) -> QWidget:
        panel = QGroupBox("장비")
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(340)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        layout = QFormLayout(panel)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(5)
        layout.setLabelAlignment(Qt.AlignLeft)
        layout.setFormAlignment(Qt.AlignTop)

        self.controller_model_label = QLabel(CONFIRMED_CONTROLLER_MODEL)
        self.stage_model_label = QLabel(CONFIRMED_STAGE_MODEL)
        self.driver_mode_label = QLabel("SHOT-702")
        self.stage_count_label = QLabel("driver 1 / driver 2")
        self.config_path_label = QLabel("")
        self.config_path_label.setWordWrap(True)
        self.config_path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.port_summary_label = QLabel("")
        self.limit_summary_label = QLabel("")
        self.speed_summary_label = QLabel("")

        layout.addRow("컨트롤러", self.controller_model_label)
        layout.addRow("스테이지", self.stage_model_label)
        layout.addRow("드라이버", self.driver_mode_label)
        layout.addRow("조작 가능", self.stage_count_label)
        layout.addRow("설정", self.config_path_label)
        layout.addRow("통신", self.port_summary_label)
        layout.addRow("제한", self.limit_summary_label)
        layout.addRow("속도", self.speed_summary_label)
        return panel

    def _build_connection_panel(self) -> QWidget:
        panel = QGroupBox("연결")
        panel.setMinimumWidth(260)
        panel.setMaximumWidth(340)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        self.config_path_edit = QLineEdit()
        self.config_path_edit.setReadOnly(True)
        self.config_path_edit.setMinimumWidth(0)
        self.config_path_edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        load_button = QPushButton("설정 불러오기")
        load_button.setIcon(self.style().standardIcon(QStyle.SP_DialogOpenButton))
        load_button.setMinimumHeight(46)
        load_button.clicked.connect(self._choose_config_file)
        layout.addWidget(self.config_path_edit)
        layout.addWidget(load_button)

        form = QFormLayout()
        form.setSpacing(5)
        self.port_edit = QLineEdit()
        self.port_edit.setPlaceholderText("COM10")
        self.stage_count_combo = QComboBox()
        self.stage_count_combo.addItem("Stage 1만 조작", (1,))
        self.stage_count_combo.addItem("Stage 2만 조작", (2,))
        self.stage_count_combo.addItem("Stage 1 + Stage 2 조작", (1, 2))
        self.stage_count_combo.currentIndexChanged.connect(self._rebuild_stage_panels)
        form.addRow("COM", self.port_edit)
        form.addRow("패널", self.stage_count_combo)
        layout.addLayout(form)

        self.apply_speed_on_connect_check = QCheckBox("연결 시 속도 적용")
        self.hold_on_connect_check = QCheckBox("연결 시 홀드")
        self.home_on_connect_check = QCheckBox("연결 시 원점복귀")
        self.home_on_connect_check.setToolTip("체크하면 연결 직후 표시된 스테이지가 움직입니다.")
        layout.addWidget(self.apply_speed_on_connect_check)
        layout.addWidget(self.hold_on_connect_check)
        layout.addWidget(self.home_on_connect_check)

        self.connect_button = QPushButton("연결")
        self.connect_button.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.connect_button.setMinimumHeight(56)
        self.connect_button.clicked.connect(self._connect_controller)
        self.disconnect_button = QPushButton("연결 해제")
        self.disconnect_button.setIcon(self.style().standardIcon(QStyle.SP_DialogCloseButton))
        self.disconnect_button.setMinimumHeight(48)
        self.disconnect_button.clicked.connect(self._disconnect_from_ui)
        layout.addWidget(self.connect_button)
        layout.addWidget(self.disconnect_button)
        layout.addStretch(1)
        return panel

    def _build_motion_panel(self) -> QWidget:
        panel = QGroupBox("스테이지 구동")
        panel.setObjectName("MotionGroup")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        global_controls = QFrame()
        global_controls.setObjectName("TouchSettingsBox")
        global_layout = QGridLayout(global_controls)
        global_layout.setContentsMargins(8, 6, 8, 6)
        global_layout.setHorizontalSpacing(8)
        global_layout.setVerticalSpacing(4)

        self.step_combo = QComboBox()
        for value in (0.01, 0.05, 0.1, 0.5, 1.0, 5.0):
            self.step_combo.addItem(f"{value:g} mm", value)
        self.step_combo.setCurrentIndex(3)
        self.wait_motion_check = QCheckBox("이동 완료 대기")
        self.wait_motion_check.setChecked(True)
        self.min_speed_spin = self._make_int_spin(1, 500000, 100, " pps")
        self.max_speed_spin = self._make_int_spin(1, 500000, 5000, " pps")
        self.accel_spin = self._make_int_spin(0, 5000, 200, " ms")
        global_layout.addWidget(QLabel("이동량"), 0, 0)
        global_layout.addWidget(self.step_combo, 0, 1)
        global_layout.addWidget(self.wait_motion_check, 0, 2)
        global_layout.addWidget(QLabel("시작"), 0, 3)
        global_layout.addWidget(self.min_speed_spin, 0, 4)
        global_layout.addWidget(QLabel("최대"), 1, 3)
        global_layout.addWidget(self.max_speed_spin, 1, 4)
        global_layout.addWidget(QLabel("가감속"), 1, 0)
        global_layout.addWidget(self.accel_spin, 1, 1)
        layout.addWidget(global_controls)

        self.stage_panel_container = QWidget()
        self.stage_panel_layout = QGridLayout(self.stage_panel_container)
        self.stage_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.stage_panel_layout.setHorizontalSpacing(8)
        self.stage_panel_layout.setVerticalSpacing(8)
        layout.addWidget(self.stage_panel_container, stretch=1)
        return panel

    def _build_status_panel(self) -> QWidget:
        panel = QGroupBox("상태")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        grid = QGridLayout()
        grid.setSpacing(4)
        self.ready_label = QLabel("--")
        self.ack_label = QLabel("--")
        self.axis1_position_label = QLabel("--")
        self.axis2_position_label = QLabel("--")
        self.axis1_pulses_label = QLabel("--")
        self.axis2_pulses_label = QLabel("--")
        grid.addWidget(QLabel("상태"), 0, 0)
        grid.addWidget(self.ready_label, 0, 1)
        grid.addWidget(QLabel("ACK"), 1, 0)
        grid.addWidget(self.ack_label, 1, 1)
        grid.addWidget(QLabel("S1 mm"), 2, 0)
        grid.addWidget(self.axis1_position_label, 2, 1)
        grid.addWidget(QLabel("S1 pulse"), 3, 0)
        grid.addWidget(self.axis1_pulses_label, 3, 1)
        grid.addWidget(QLabel("S2 mm"), 4, 0)
        grid.addWidget(self.axis2_position_label, 4, 1)
        grid.addWidget(QLabel("S2 pulse"), 5, 0)
        grid.addWidget(self.axis2_pulses_label, 5, 1)
        layout.addLayout(grid)

        self.auto_refresh_check = QCheckBox("자동 갱신")
        self.auto_refresh_check.setChecked(True)
        self.auto_refresh_check.stateChanged.connect(self._auto_refresh_changed)
        self.refresh_status_button = QPushButton("상태 새로고침")
        self.refresh_status_button.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_status_button.setMinimumHeight(52)
        self.refresh_status_button.clicked.connect(self._refresh_status)
        layout.addWidget(self.auto_refresh_check)
        layout.addWidget(self.refresh_status_button)
        return panel

    def _build_direction_panel(self) -> QWidget:
        panel = QGroupBox("이동 방향 안내")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 8)
        self.direction_diagram = StageDirectionDiagram()
        layout.addWidget(self.direction_diagram)
        return panel

    def _build_log_panel(self) -> QWidget:
        panel = QGroupBox("기록")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 10, 8, 8)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.WidgetWidth)
        layout.addWidget(self.log_edit)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(340)
        panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self._build_status_panel(), stretch=0)
        layout.addWidget(self._build_direction_panel(), stretch=1)
        layout.addWidget(self._build_log_panel(), stretch=1)
        return panel

    def _apply_styles(self) -> None:
        font = QFont()
        font.setPointSize(11)
        self.setFont(font)
        self.setStyleSheet(
            """
            QMainWindow, QWidget {
                background: #10151b;
                color: #e8edf2;
            }
            QGroupBox {
                border: 1px solid #2c3542;
                border-radius: 5px;
                margin-top: 8px;
                padding: 8px 6px 6px 6px;
                background: #151b22;
                font-weight: 700;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 8px;
                padding: 0 3px;
                color: #f1f4f8;
            }
            QGroupBox#MotionGroup {
                border: 2px solid #2f8f7d;
                background: #121f22;
            }
            QLabel {
                color: #d7dee7;
            }
            QLabel#WindowTitle {
                font-size: 24px;
                font-weight: 800;
                color: #ffffff;
            }
            QLabel#WindowSubtitle {
                color: #8bd3c7;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#StatusBadge {
                padding: 4px 12px;
                border-radius: 5px;
                background: #2b3039;
                color: #f6c177;
                font-weight: 800;
            }
            QFrame#TouchSettingsBox {
                border: 1px solid #2f6f62;
                border-radius: 5px;
                background: #13221f;
            }
            QFrame#StageControlPanel {
                border: 2px solid #3a4b5f;
                border-radius: 6px;
                background: #16212b;
            }
            QFrame#StageHeaderCard {
                border: 1px solid #2f4859;
                border-radius: 6px;
                background: #101923;
            }
            QLabel#StagePanelTitle {
                font-size: 22px;
                font-weight: 900;
                color: #ffffff;
            }
            QLabel#StagePanelDriver {
                color: #9fe6d7;
                font-weight: 800;
            }
            QLabel#StagePanelPosition {
                color: #ffffff;
                font-size: 18px;
                font-weight: 900;
            }
            QLabel#StageSmallCaption {
                color: #93a4b8;
                font-size: 11px;
                font-weight: 700;
            }
            QLabel#StageSectionTitle {
                color: #ffffff;
                font-size: 13px;
                font-weight: 900;
                padding-top: 1px;
            }
            QLabel#StageHint {
                color: #9aa8b8;
                font-size: 10px;
                font-weight: 600;
            }
            QLabel#StageTargetLabel {
                font-weight: 800;
            }
            QPushButton {
                border: 1px solid #3b4655;
                border-radius: 6px;
                background: #202834;
                color: #eef3f8;
                padding: 6px 10px;
                font-weight: 750;
            }
            QPushButton:hover {
                background: #273242;
            }
            QPushButton:disabled {
                color: #737d8a;
                background: #171b22;
                border-color: #242b35;
            }
            QPushButton#PositiveMoveButton {
                background: #8bd3c7;
                border-color: #8bd3c7;
                color: #0d1f22;
                font-size: 15px;
                font-weight: 900;
            }
            QPushButton#PositiveMoveButton:hover {
                background: #a3e0d6;
            }
            QPushButton#NegativeMoveButton {
                background: #f6c177;
                border-color: #f6c177;
                color: #241607;
                font-size: 15px;
                font-weight: 900;
            }
            QPushButton#NegativeMoveButton:hover {
                background: #ffd08d;
            }
            QPushButton#PositiveMoveButton:disabled,
            QPushButton#NegativeMoveButton:disabled {
                color: #737d8a;
                background: #171b22;
                border-color: #242b35;
            }
            QPushButton#DangerButton {
                background: #8f1d2c;
                border-color: #b63245;
                font-size: 17px;
                font-weight: 900;
                min-width: 150px;
            }
            QPushButton#DangerButton:hover {
                background: #a92336;
            }
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit {
                background: #0f1319;
                border: 1px solid #303947;
                border-radius: 5px;
                color: #e8edf2;
                min-height: 32px;
                padding: 3px;
            }
            QLineEdit#KeypadDisplay {
                font-size: 26px;
                font-weight: 800;
            }
            QPushButton#KeypadButton {
                font-size: 22px;
                font-weight: 900;
            }
            QComboBox {
                min-height: 40px;
            }
            QCheckBox {
                color: #d7dee7;
                spacing: 7px;
            }
            QCheckBox#TouchOnlyCheck {
                font-weight: 900;
                color: #ffffff;
                spacing: 9px;
            }
            QCheckBox#TouchOnlyCheck::indicator {
                width: 44px;
                height: 24px;
                border-radius: 12px;
                background: #2b3039;
                border: 1px solid #4a5665;
            }
            QCheckBox#TouchOnlyCheck::indicator:checked {
                background: #1f6f63;
                border: 1px solid #2f9f8d;
            }
            QCheckBox#TouchOnlyCheck::indicator:unchecked {
                background: #1a2028;
            }
            """
        )

    def _make_int_spin(self, minimum: int, maximum: int, value: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setSuffix(suffix)
        spin.setAlignment(Qt.AlignRight)
        spin.setMinimumHeight(42)
        spin.installEventFilter(self)
        return spin

    def _open_touch_keypad(self, spin: QSpinBox | QDoubleSpinBox) -> None:
        if self._keypad_open:
            return
        self._keypad_open = True
        try:
            allow_decimal = isinstance(spin, QDoubleSpinBox)
            dialog = TouchKeypadDialog(
                title="숫자 입력",
                initial_value=str(spin.value()),
                allow_decimal=allow_decimal,
                parent=self,
            )
            if dialog.exec() == QDialog.Accepted:
                value = dialog.value()
                if isinstance(spin, QSpinBox):
                    spin.setValue(int(round(value)))
                else:
                    spin.setValue(value)
        finally:
            self._keypad_open = False

    def _resolve_initial_config_path(self, config_path: Path | None) -> Path:
        if config_path is not None:
            return resolve_runtime_path(config_path)
        if DEFAULT_STAGE_CONFIG_PATH.exists():
            return DEFAULT_STAGE_CONFIG_PATH
        return FALLBACK_STAGE_CONFIG_PATH

    def _display_config_path(self, config_path: Path) -> str:
        try:
            return config_path.relative_to(APP_ROOT).as_posix()
        except ValueError:
            return config_path.name

    def _load_config(self, config_path: Path) -> None:
        try:
            config = load_shot_motion_config(config_path)
        except Exception as exc:
            QMessageBox.critical(self, "스테이지 설정 오류", f"설정 파일을 불러올 수 없습니다.\n\n{exc}")
            self._log(f"설정 로드 실패: {exc}")
            return

        self._config = config
        self._config_path = config_path
        self._populate_config_fields(config, config_path)
        self._log(f"설정 로드: {config_path}")
        if (
            config.controller_model != CONFIRMED_CONTROLLER_MODEL
            or config.stage_model != CONFIRMED_STAGE_MODEL
        ):
            self._log(
                "주의: 설정 파일의 장비명이 확정 장비와 다릅니다. "
                f"config=({config.controller_model}, {config.stage_model})"
            )

    def _populate_config_fields(self, config: ShotMotionConfig, config_path: Path) -> None:
        display_path = self._display_config_path(config_path)
        self.config_path_edit.setText(display_path)
        self.config_path_edit.setToolTip(str(config_path))
        self.config_path_label.setText(display_path)
        self.config_path_label.setToolTip(str(config_path))
        self.controller_model_label.setText(config.controller_model)
        self.stage_model_label.setText(config.stage_model)
        self.driver_mode_label.setText(config.driver_mode)
        self.port_edit.setText(config.port)
        self.stage_count_combo.setCurrentIndex(0)
        self.apply_speed_on_connect_check.setChecked(config.set_speed_on_connect)
        self.hold_on_connect_check.setChecked(config.motor_hold_on_connect)
        self.home_on_connect_check.setChecked(False)
        self.min_speed_spin.setValue(config.minimum_speed_pps)
        self.max_speed_spin.setValue(config.maximum_speed_pps)
        self.accel_spin.setValue(config.acceleration_ms)
        self.port_summary_label.setText(f"{config.port}, {config.baudrate} bps")
        self.limit_summary_label.setText(
            f"{config.min_position_mm:g} - {config.max_position_mm:g} mm"
            if config.enforce_software_limits
            else "제한 꺼짐"
        )
        self.speed_summary_label.setText(
            f"{config.minimum_speed_pps}-{config.maximum_speed_pps} pps, {config.acceleration_ms} ms"
        )
        for panel in self._stage_panels.values():
            panel.set_motion_range(config.min_position_mm, config.max_position_mm)

    def _choose_config_file(self) -> None:
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "스테이지 설정 파일 선택",
            str(self._config_path.parent),
            "JSON files (*.json);;All files (*.*)",
        )
        if file_name:
            self._load_config(Path(file_name))

    def _enabled_axes(self) -> list[int]:
        axes = self.stage_count_combo.currentData()
        if isinstance(axes, (tuple, list)):
            return [axis for axis in axes if axis in {1, 2}]
        if axes in {1, 2}:
            return [int(axes)]
        return [1]

    def _rebuild_stage_panels(self) -> None:
        if not hasattr(self, "stage_panel_layout"):
            return
        while self.stage_panel_layout.count() > 0:
            item = self.stage_panel_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._stage_panels.clear()
        for column in range(MAX_STAGE_COUNT):
            self.stage_panel_layout.setColumnStretch(column, 0)
            self.stage_panel_layout.setColumnMinimumWidth(column, 0)

        axes = self._enabled_axes()
        if hasattr(self, "direction_diagram"):
            self.direction_diagram.set_axes(axes)
        for column, axis in enumerate(axes):
            panel = StageControlPanel(axis)
            panel.action_requested.connect(self._handle_stage_action)
            panel.absolute_spin.installEventFilter(self)
            if self._config is not None:
                panel.set_motion_range(self._config.min_position_mm, self._config.max_position_mm)
            alignment = Qt.AlignTop
            if len(axes) == 1:
                alignment |= Qt.AlignHCenter
            self.stage_panel_layout.addWidget(panel, 0, column, alignment)
            self.stage_panel_layout.setColumnStretch(column, 1)
            self._stage_panels[axis] = panel
        self._sync_stage_panel_widths()
        self._update_connection_state()
        if self._connected and not self._busy:
            self._refresh_status()

    def _sync_stage_panel_widths(self) -> None:
        if not self._stage_panels or not hasattr(self, "stage_panel_container"):
            return
        available_width = self.stage_panel_container.width()
        if available_width <= 0:
            return
        spacing = max(0, self.stage_panel_layout.horizontalSpacing())
        two_column_width = max(1, (available_width - spacing) // 2)
        panel_width = max(460, min(640, two_column_width))
        if available_width < panel_width:
            panel_width = max(320, available_width)
        for panel in self._stage_panels.values():
            panel.setFixedWidth(panel_width)

    def _connected_config_from_ui(self) -> ShotMotionConfig:
        if self._config is None:
            raise MotionError("스테이지 설정이 로드되지 않았습니다.")
        return replace(
            self._config,
            port=self.port_edit.text().strip(),
            axis=1,
            set_speed_on_connect=False,
            motor_hold_on_connect=False,
            home_on_connect=False,
            minimum_speed_pps=self.min_speed_spin.value(),
            maximum_speed_pps=self.max_speed_spin.value(),
            acceleration_ms=self.accel_spin.value(),
        )

    def _connect_controller(self) -> None:
        if self._connected:
            return
        axes = self._enabled_axes()
        apply_speed = self.apply_speed_on_connect_check.isChecked()
        hold = self.hold_on_connect_check.isChecked()
        home = self.home_on_connect_check.isChecked()

        def connect() -> tuple[str, StageStatusSnapshot]:
            config = self._connected_config_from_ui()
            controller = ShotController(config)
            with self._io_lock:
                message = controller.connect()
                for axis in axes:
                    if apply_speed:
                        controller.set_speed(
                            axis=axis,
                            minimum_speed_pps=config.minimum_speed_pps,
                            maximum_speed_pps=config.maximum_speed_pps,
                            acceleration_ms=config.acceleration_ms,
                        )
                    if hold:
                        controller.set_motor_hold(axis=axis, hold=True)
                    if home:
                        controller.home(axis=axis, direction=config.home_direction)
                        controller.wait_until_ready()
                self._controller = controller
                self._config = config
                snapshot = make_status_snapshot(controller)
            return f"{message}; enabled stages={axes}", snapshot

        self._submit_operation("연결", connect, refresh=False)

    def _disconnect_from_ui(self) -> None:
        self._submit_operation("연결 해제", lambda: self._disconnect_controller(), refresh=False)

    def _disconnect_controller(self) -> str:
        controller = self._require_controller()
        with self._io_lock:
            controller.disconnect()
            self._controller = None
        self._connected = False
        return "연결을 해제했습니다."

    def _refresh_status_from_timer(self) -> None:
        if self._connected and not self._busy:
            self._refresh_status()

    def _auto_refresh_changed(self) -> None:
        if self.auto_refresh_check.isChecked() and self._connected:
            self._status_timer.start()
        else:
            self._status_timer.stop()

    def _refresh_status(self) -> None:
        if not self._connected or self._busy:
            return
        self._submit_operation("상태 갱신", lambda: "상태를 갱신했습니다.", refresh=True, mark_busy=False)

    def _handle_stage_action(self, axis: int, action: str, value: object) -> None:
        if action == "move_negative":
            self._move_relative(axis, -self._step_mm())
        elif action == "move_positive":
            self._move_relative(axis, self._step_mm())
        elif action == "goto_zero":
            self._goto_logical_origin(axis)
        elif action == "zero_here":
            self._reset_logical_zero(axis)
        elif action == "move_absolute":
            self._move_absolute(axis, float(value))
        elif action == "home":
            self._home_stage(axis)
        elif action == "home_zero":
            self._home_and_zero_stage(axis)
        elif action == "hold":
            self._set_motor_hold(axis, True)
        elif action == "free":
            self._set_motor_hold(axis, False)
        elif action == "slow_stop":
            self._slow_stop_stage(axis)
        elif action == "speed":
            self._apply_speed(axis)

    def _step_mm(self) -> float:
        return float(self.step_combo.currentData() or 0.5)

    def _move_relative(self, axis: int, delta_mm: float) -> None:
        def move() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.move_relative_mm(axis=axis, delta_mm=delta_mm)
            if self.wait_motion_check.isChecked():
                self._wait_until_ready_interruptible(controller)
            return f"Stage {axis} 상대 이동: {delta_mm:+.3f} mm"

        self._submit_operation("상대 이동", move)

    def _move_absolute(self, axis: int, target_mm: float) -> None:
        def move() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.move_absolute_mm(axis=axis, position_mm=target_mm)
            if self.wait_motion_check.isChecked():
                self._wait_until_ready_interruptible(controller)
            return f"Stage {axis} 절대 위치 이동: {target_mm:.3f} mm"

        self._submit_operation("절대 이동", move)

    def _goto_logical_origin(self, axis: int) -> None:
        def move() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.move_absolute_mm(axis=axis, position_mm=0.0)
            if self.wait_motion_check.isChecked():
                self._wait_until_ready_interruptible(controller)
            return f"Stage {axis} 논리 0 mm 이동"

        self._submit_operation("논리 원점 이동", move)

    def _home_stage(self, axis: int) -> None:
        def home() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.home(axis=axis, direction=controller.config.home_direction)
            if self.wait_motion_check.isChecked():
                self._wait_until_ready_interruptible(controller)
            return f"Stage {axis} 기계 원점복귀"

        self._submit_operation("기계 원점복귀", home)

    def _home_and_zero_stage(self, axis: int) -> None:
        confirmed = QMessageBox.question(
            self,
            "원점+0 확인",
            f"Stage {axis}가 원점 방향으로 이동한 뒤 현재 위치를 논리 0으로 설정합니다.\n계속할까요?",
        )
        if confirmed != QMessageBox.Yes:
            return

        def origin() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.home(axis=axis, direction=controller.config.home_direction)
            self._wait_until_ready_interruptible(controller)
            with self._io_lock:
                controller.reset_logical_zero(axis=axis)
            return f"Stage {axis} 원점복귀 및 논리 0 설정"

        self._submit_operation("원점+0", origin)

    def _reset_logical_zero(self, axis: int) -> None:
        confirmed = QMessageBox.question(
            self,
            "현재 0설정 확인",
            f"Stage {axis}의 현재 위치를 소프트웨어 0 mm로 설정합니다.\n계속할까요?",
        )
        if confirmed != QMessageBox.Yes:
            return

        def zero() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.reset_logical_zero(axis=axis)
            return f"Stage {axis} 현재 위치를 소프트웨어 0으로 설정"

        self._submit_operation("현재 0설정", zero)

    def _set_motor_hold(self, axis: int, hold: bool) -> None:
        def set_hold() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.set_motor_hold(axis=axis, hold=hold)
            return f"Stage {axis} 모터 {'홀드' if hold else '프리'}"

        self._submit_operation("모터 홀드" if hold else "모터 프리", set_hold)

    def _slow_stop_stage(self, axis: int) -> None:
        def stop() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.slow_stop(axis=axis)
            return f"Stage {axis} 감속 정지"

        self._submit_operation("감속 정지", stop)

    def _emergency_stop(self) -> None:
        if not self._connected or self._controller is None:
            return

        def stop() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.emergency_stop()
            return "비상 정지 명령을 보냈습니다."

        self._submit_operation("비상 정지", stop, mark_busy=False)

    def _apply_speed(self, axis: int) -> None:
        min_speed = self.min_speed_spin.value()
        max_speed = self.max_speed_spin.value()
        accel = self.accel_spin.value()

        def apply() -> str:
            controller = self._require_controller()
            with self._io_lock:
                controller.set_speed(
                    axis=axis,
                    minimum_speed_pps=min_speed,
                    maximum_speed_pps=max_speed,
                    acceleration_ms=accel,
                )
                controller.config = replace(
                    controller.config,
                    minimum_speed_pps=min_speed,
                    maximum_speed_pps=max_speed,
                    acceleration_ms=accel,
                )
                self._config = controller.config
            return f"Stage {axis} 속도 적용: {min_speed}-{max_speed} pps, {accel} ms"

        self._submit_operation("속도 적용", apply)

    def _wait_until_ready_interruptible(self, controller: ShotController) -> None:
        deadline = time.monotonic() + controller.config.ready_timeout_s
        while time.monotonic() < deadline:
            with self._io_lock:
                if controller.is_ready():
                    return
            time.sleep(controller.config.ready_poll_interval_s)
        raise MotionError(
            f"{controller.config.controller_model} did not become ready within "
            f"{controller.config.ready_timeout_s:.2f}s."
        )

    def _submit_operation(
        self,
        title: str,
        operation: Callable[[], str | tuple[str, StageStatusSnapshot]],
        *,
        refresh: bool = True,
        mark_busy: bool = True,
    ) -> None:
        if mark_busy and self._busy:
            self._log("다른 작업이 끝난 뒤 다시 실행하십시오.")
            return
        if mark_busy:
            self._busy = True
            self._update_connection_state()

        def worker() -> tuple[str, StageStatusSnapshot | None]:
            result = operation()
            message: str
            snapshot: StageStatusSnapshot | None = None
            if isinstance(result, tuple):
                message, snapshot = result
            else:
                message = result
            controller = self._controller
            if refresh and controller is not None:
                with self._io_lock:
                    snapshot = make_status_snapshot(controller)
            return message, snapshot

        future = self._executor.submit(worker)

        def done_callback(done_future) -> None:
            try:
                message, snapshot = done_future.result()
            except Exception as exc:
                self.operation_finished.emit(title, False, str(exc), None, mark_busy)
            else:
                self.operation_finished.emit(title, True, message, snapshot, mark_busy)

        future.add_done_callback(done_callback)

    def _handle_operation_finished(
        self,
        title: str,
        ok: bool,
        message: str,
        snapshot: StageStatusSnapshot | None,
        clear_busy: bool,
    ) -> None:
        if clear_busy:
            self._busy = False
        if ok:
            if title == "연결":
                self._connected = True
                if self.auto_refresh_check.isChecked():
                    self._status_timer.start()
            elif title == "연결 해제":
                self._connected = False
                self._status_timer.stop()
            self._log(f"{title}: {message}")
            if snapshot is not None:
                self._apply_status_snapshot(snapshot)
        else:
            self._log(f"{title} 실패: {message}")
            if title == "연결":
                self._connected = False
                self._controller = None
            QMessageBox.warning(self, f"{title} 실패", message)
        self._update_connection_state()

    def _apply_status_snapshot(self, snapshot: StageStatusSnapshot) -> None:
        axis1_mm = snapshot.position_mm(1)
        axis2_mm = snapshot.position_mm(2)
        self.axis1_position_label.setText(f"{axis1_mm:.6f}")
        self.axis2_position_label.setText(f"{axis2_mm:.6f}")
        self.axis1_pulses_label.setText(str(snapshot.axis1_position))
        self.axis2_pulses_label.setText(str(snapshot.axis2_position))
        for axis, panel in self._stage_panels.items():
            panel.set_position(snapshot.position_mm(axis), snapshot.position_pulses(axis))
        ready_text = "Ready" if snapshot.ready_ack == "R" else "Busy"
        self.ready_label.setText(ready_text)
        self.ready_label.setStyleSheet(
            f"color: {'#9fe6d7' if snapshot.ready_ack == 'R' else '#f6c177'}; font-weight: 800;"
        )
        self.ack_label.setText(f"{snapshot.command_ack}/{snapshot.stop_ack}/{snapshot.ready_ack}")

    def _update_connection_state(self) -> None:
        connected = self._connected and self._controller is not None
        self.connection_badge.setText("연결됨" if connected else "연결 안 됨")
        badge_color = QColor("#1d5f4f") if connected else QColor("#3a3024")
        badge_text = QColor("#caffef") if connected else QColor("#f6c177")
        self.connection_badge.setStyleSheet(
            f"background: {badge_color.name()}; color: {badge_text.name()}; "
            "padding: 8px 12px; border-radius: 5px; font-weight: 800;"
        )

        self.connect_button.setEnabled(not connected and not self._busy)
        self.disconnect_button.setEnabled(connected and not self._busy)
        self.config_path_edit.setEnabled(not connected)
        self.port_edit.setEnabled(not connected)
        self.apply_speed_on_connect_check.setEnabled(not connected)
        self.hold_on_connect_check.setEnabled(not connected)
        self.home_on_connect_check.setEnabled(not connected)
        self.refresh_status_button.setEnabled(connected and not self._busy)
        for panel in self._stage_panels.values():
            panel.set_controls_enabled(connected and not self._busy)
        self.emergency_button.setEnabled(connected)

    def _require_controller(self) -> ShotController:
        if self._controller is None:
            raise MotionError("스테이지 컨트롤러가 연결되지 않았습니다.")
        return self._controller

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_edit.append(f"[{timestamp}] {message}")
