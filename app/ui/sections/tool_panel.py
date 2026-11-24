"""左侧工具栏：CSV 记录与 2WΩ 软件蜂鸣。"""

from __future__ import annotations

import math
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QLabel,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.collapsible import CollapsibleSection


class ToolPanel(QFrame):
    csv_toggle_requested = Signal()
    open_csv_folder_requested = Signal()
    beeper_changed = Signal()
    test_beep_requested = Signal()
    average_changed = Signal()
    floating_toggle_requested = Signal()
    floating_options_changed = Signal()

    def add_section(self, title: str) -> CollapsibleSection:
        """新增工具区；以后加的工具区也统一使用可折叠容器。"""
        section = CollapsibleSection(title, self)
        index = self._root_layout.count()
        if index > 0 and self._root_layout.itemAt(index - 1).spacerItem():
            index -= 1
        self._root_layout.insertWidget(index, section)
        self.sections.append(section)
        return section

    def __init__(
        self,
        parent: QWidget | None = None,
        floating_percent: int = 100,
        floating_opacity: int = 100,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("LeftPanel")
        self.setMinimumWidth(220)
        self.setMaximumWidth(270)
        self._state = "disconnected"
        self._csv_started = 0.0
        self._csv_recording = False
        self._csv_timer = QTimer(self)
        self._csv_timer.setInterval(250)
        self._csv_timer.timeout.connect(self._update_csv_timer)

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)
        self._root_layout = root
        self.sections: list[CollapsibleSection] = []

        title = QLabel("工具栏", self)
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        csv_group = self.add_section("数据记录")
        csv_layout = csv_group.body_layout
        csv_layout.setSpacing(8)
        self.csv_btn = QPushButton("开始记录 CSV", csv_group)
        self.csv_btn.setObjectName("RecordButton")
        self.csv_btn.setCheckable(True)
        self.csv_btn.clicked.connect(self.csv_toggle_requested)
        self.csv_timer_label = QLabel("记录时间：-", csv_group)
        self.csv_timer_label.setObjectName("Muted")
        self.csv_timer_label.setStyleSheet(
            "font-family: Consolas; font-size: 12px;"
        )
        self.csv_path_label = QLabel("文件：-", csv_group)
        self.csv_path_label.setObjectName("Muted")
        self.csv_path_label.setWordWrap(True)
        self.folder_btn = QPushButton("打开 CSV 文件夹", csv_group)
        self.folder_btn.clicked.connect(self.open_csv_folder_requested)
        csv_layout.addWidget(self.csv_btn)
        csv_layout.addWidget(self.csv_timer_label)
        csv_layout.addWidget(self.csv_path_label)
        csv_layout.addWidget(self.folder_btn)

        avg_group = self.add_section("平均值")
        avg_layout = avg_group.body_layout
        avg_layout.setSpacing(7)
        self.avg_check = QPushButton("开启平均值", avg_group)
        self.avg_check.setObjectName("AverageButton")
        self.avg_check.setCheckable(True)
        self.avg_count_spin = QSpinBox(avg_group)
        self.avg_count_spin.setRange(1, 1000)
        self.avg_count_spin.setValue(10)
        self.avg_count_spin.setSuffix(" 次")
        self.avg_count_spin.setToolTip(
            "每 N 次读数取平均后输出一条；N 越大，输出速率越低"
        )
        self.avg_count_spin.setEnabled(False)
        avg_layout.addWidget(self.avg_check)
        avg_layout.addWidget(self.avg_count_spin)
        decimals_label = QLabel("增加小数位", avg_group)
        decimals_label.setObjectName("Muted")
        self.avg_decimals_combo = QComboBox(avg_group)
        self.avg_decimals_combo.addItem("不增加", "none")
        self.avg_decimals_combo.addItem("floor(log10 N / 2)", "formula")
        self.avg_decimals_combo.setToolTip("平均后主读数增加的显示小数位")
        avg_layout.addWidget(decimals_label)
        avg_layout.addWidget(self.avg_decimals_combo)

        float_group = self.add_section("悬浮窗")
        float_layout = float_group.body_layout
        float_layout.setSpacing(7)
        self.floating_btn = QPushButton("开启悬浮窗", float_group)
        self.floating_btn.setObjectName("FloatingButton")
        self.floating_btn.setCheckable(True)
        self.floating_btn.clicked.connect(self.floating_toggle_requested)
        size_label = QLabel("尺寸", float_group)
        size_label.setObjectName("Muted")
        self.floating_size_spin = QSpinBox(float_group)
        self.floating_size_spin.setRange(50, 200)
        self.floating_size_spin.setSingleStep(10)
        self.floating_size_spin.setValue(max(50, min(200, floating_percent)))
        self.floating_size_spin.setSuffix(" %")
        self.floating_size_spin.setToolTip("100% 为 500 × 120 px")
        opacity_label = QLabel("不透明度", float_group)
        opacity_label.setObjectName("Muted")
        self.floating_opacity_spin = QSpinBox(float_group)
        self.floating_opacity_spin.setRange(20, 100)
        self.floating_opacity_spin.setSingleStep(5)
        self.floating_opacity_spin.setValue(
            max(20, min(100, floating_opacity))
        )
        self.floating_opacity_spin.setSuffix(" %")
        self.floating_minimize_check = QCheckBox(
            "开启时最小化主窗口", float_group
        )
        self.floating_minimize_check.setChecked(True)
        float_layout.addWidget(self.floating_btn)
        float_layout.addWidget(size_label)
        float_layout.addWidget(self.floating_size_spin)
        float_layout.addWidget(opacity_label)
        float_layout.addWidget(self.floating_opacity_spin)
        float_layout.addWidget(self.floating_minimize_check)

        self.beep_group = self.add_section("2WΩ 软件蜂鸣")
        beep_layout = self.beep_group.body_layout
        beep_layout.setSpacing(7)
        self.beep_check = QCheckBox("小于阈值时蜂鸣", self.beep_group)
        self.beep_threshold_spin = QDoubleSpinBox(self.beep_group)
        self.beep_threshold_spin.setRange(0.0, 10000.0)
        self.beep_threshold_spin.setDecimals(3)
        self.beep_threshold_spin.setSingleStep(0.1)
        self.beep_threshold_spin.setValue(1.0)
        self.beep_threshold_spin.setSuffix(" Ω")
        self.beep_volume_slider = QSlider(Qt.Orientation.Horizontal, self.beep_group)
        self.beep_volume_slider.setRange(0, 100)
        self.beep_volume_slider.setValue(60)
        hint = QLabel("仅 2WΩ；低于阈值持续蜂鸣（1000 Hz）", self.beep_group)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)

        beep_layout.addWidget(self.beep_check)
        threshold_row = QLabel("阈值", self.beep_group)
        threshold_row.setObjectName("Muted")
        beep_layout.addWidget(threshold_row)
        beep_layout.addWidget(self.beep_threshold_spin)
        volume_row = QLabel("音量", self.beep_group)
        volume_row.setObjectName("Muted")
        beep_layout.addWidget(volume_row)
        beep_layout.addWidget(self.beep_volume_slider)
        self.beep_test_btn = QPushButton("测试蜂鸣", self.beep_group)
        self.beep_test_btn.clicked.connect(self.test_beep_requested)
        beep_layout.addWidget(self.beep_test_btn)
        beep_layout.addWidget(hint)
        # 保持“数据记录 / 悬浮窗 / 平均值 / 蜂鸣”的固定顺序。
        root.removeWidget(float_group)
        root.insertWidget(2, float_group)
        self.sections.remove(float_group)
        self.sections.insert(1, float_group)
        root.addStretch(1)

        self.beep_check.toggled.connect(self._emit_beeper)
        self.beep_threshold_spin.valueChanged.connect(self._emit_beeper)
        self.beep_volume_slider.valueChanged.connect(self._emit_beeper)
        self.avg_check.toggled.connect(self._on_average_toggled)
        self.avg_count_spin.valueChanged.connect(self._emit_average)
        self.avg_decimals_combo.currentIndexChanged.connect(self._emit_average)
        self.floating_size_spin.valueChanged.connect(
            self.floating_options_changed
        )
        self.floating_opacity_spin.valueChanged.connect(
            self.floating_options_changed
        )
        self.floating_minimize_check.toggled.connect(
            self.floating_options_changed
        )
        self.set_function("VDC")

    def _emit_beeper(self, *_args) -> None:
        self.beeper_changed.emit()

    def _on_average_toggled(self, enabled: bool) -> None:
        self.avg_check.setText("关闭平均值" if enabled else "开启平均值")
        self.avg_count_spin.setEnabled(enabled and self._state != "disconnected")
        self.avg_decimals_combo.setEnabled(self._state != "disconnected")
        self._emit_average()

    def _emit_average(self, *_args) -> None:
        self.avg_decimals_combo.setToolTip(
            f"当前 N={self.avg_count_spin.value()}，"
            f"增加 {self.average_extra_decimals} 位小数"
        )
        self.average_changed.emit()

    def set_function(self, function_label: str) -> None:
        self.beep_group.setVisible(function_label == "2WΩ")

    def set_state(self, state: str) -> None:
        self._state = state
        connected = state in {"ready", "reading", "acquiring", "stopping"}
        self.csv_btn.setEnabled(connected)
        self.avg_check.setEnabled(connected)
        self.avg_count_spin.setEnabled(connected and self.avg_check.isChecked())
        self.avg_decimals_combo.setEnabled(connected)
        for widget in (
            self.beep_check,
            self.beep_threshold_spin,
            self.beep_volume_slider,
            self.beep_test_btn,
        ):
            widget.setEnabled(connected)

    def set_csv_state(self, recording: bool, path: str = "") -> None:
        self.csv_btn.setText("停止记录 CSV" if recording else "开始记录 CSV")
        self.csv_btn.setChecked(recording)
        if recording:
            if path:
                self.csv_path_label.setText(f"文件：{Path(path).name}")
            else:
                self.csv_path_label.setText("文件：-")
            if not self._csv_recording:
                self._csv_recording = True
                self._csv_started = time.monotonic()
                self.csv_timer_label.setText("记录时间：00h 00m 00s")
            self._csv_timer.start()
        else:
            self._csv_recording = False
            self._csv_timer.stop()
            self.csv_timer_label.setText("记录时间：-")
            self.csv_path_label.setText("文件：-")

    def _update_csv_timer(self) -> None:
        elapsed = max(0, int(time.monotonic() - self._csv_started))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.csv_timer_label.setText(
            f"记录时间：{hours:02d}h {minutes:02d}m {seconds:02d}s"
        )

    def set_floating_active(self, active: bool) -> None:
        self.floating_btn.setText(
            "关闭悬浮窗" if active else "开启悬浮窗"
        )
        self.floating_btn.setChecked(active)

    @property
    def floating_percent(self) -> int:
        return self.floating_size_spin.value()

    @property
    def floating_opacity(self) -> int:
        return self.floating_opacity_spin.value()

    @property
    def floating_minimize(self) -> bool:
        return self.floating_minimize_check.isChecked()

    @property
    def average_enabled(self) -> bool:
        return self.avg_check.isChecked()

    @property
    def average_count(self) -> int:
        return self.avg_count_spin.value()

    @property
    def average_extra_decimals(self) -> int:
        if not self.avg_check.isChecked():
            return 0
        if self.avg_decimals_combo.currentData() != "formula":
            return 0
        count = max(1, self.avg_count_spin.value())
        return max(0, int(math.floor(math.log10(count) / 2)))

    @property
    def beep_enabled(self) -> bool:
        return self.beep_check.isChecked()

    @property
    def beep_threshold(self) -> float:
        return self.beep_threshold_spin.value()

    @property
    def beep_volume(self) -> int:
        return self.beep_volume_slider.value()
