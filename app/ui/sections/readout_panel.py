"""中上：主读数、状态位、单次读数。"""

from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.functions import function_spec_by_label
from app.domain.models import InstrumentStatus, Reading
from app.domain.precision import compute_accuracy
from app.ui.widgets.common import (
    FIELD_WIDTH,
    StatusChip,
    format_measurement_fixed,
    unit_scale,
    format_range,
)
from app.ui.widgets.digital_readout import DigitalReadout

_TIER_SHORT = {"24h": "24h", "90d": "90d", "1y": "1yr"}
_TIER_CYCLE = ("24h", "90d", "1y")
_UNIT_FACTORS = {"": 1.0, "µ": 1e-6, "m": 1e-3, "k": 1e3, "M": 1e6}


class _ClickableLabel(QLabel):
    clicked = Signal()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class ReadoutPanel(QFrame):
    single_read_requested = Signal()
    start_stop_requested = Signal()
    tier_changed = Signal(str)
    precision_changed = Signal(float)
    resolution_changed = Signal(float)
    full_scale_changed = Signal(float)
    display_unit_changed = Signal(str, float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReadoutCard")
        self.setMinimumHeight(270)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 16, 22, 14)
        root.setSpacing(8)

        top = QHBoxLayout()
        title = QLabel("主读数", self)
        title.setObjectName("SectionTitle")
        top.addWidget(title)
        self.function_badge = QLabel("VDC", self)
        self.function_badge.setObjectName("FunctionBadge")
        top.addWidget(self.function_badge)
        top.addStretch(1)

        self.chips = {
            "Rmt": StatusChip("Rmt", self),
            "AZ": StatusChip("AZ", self),
            "Null": StatusChip("Null", self),
            "FILT": StatusChip("FILT", self),
            "Range": StatusChip("Man", self),
            "Term": StatusChip("Front", self),
        }
        self.chips["Rmt"].setToolTip("远程控制（Remote）")
        self.chips["AZ"].setToolTip("自动调零（Auto Zero）")
        self.chips["Null"].setToolTip("数学空值偏移（Null）")
        self.chips["FILT"].setToolTip("AC 信号滤波器（VAC/ACI）")
        self.chips["Range"].setToolTip("量程：Auto 自动 / Man 手动")
        self.chips["Term"].setToolTip("前面板端子（Front）")
        for chip in self.chips.values():
            top.addWidget(chip)
        root.addLayout(top)

        self.display = DigitalReadout(self)
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.addWidget(self.display, 1)
        root.addLayout(value_row, 1)

        detail_row = QHBoxLayout()
        detail_row.setSpacing(12)
        detail_font = QFont("Microsoft YaHei UI", 15)
        self.accuracy_label = QLabel("精度误差 —", self)
        self.accuracy_label.setObjectName("ValueLabel")
        self.accuracy_label.setFont(detail_font)
        self.accuracy_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self.accuracy_label.setFixedWidth(260)
        self.tier_label = _ClickableLabel("(1yr)", self)
        self.tier_label.setObjectName("ValueLabel")
        self.tier_label.setFont(detail_font)
        self.tier_label.setFixedWidth(52)
        self.tier_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tier_label.setToolTip("点击轮换 24h / 90d / 1yr")
        self.range_label = QLabel("量程 —", self)
        self.range_label.setObjectName("ValueLabel")
        self.range_label.setFont(detail_font)
        self.range_label.setMinimumWidth(300)
        detail_row.addStretch(1)
        detail_row.addWidget(self.accuracy_label)
        detail_row.addWidget(self.tier_label)
        detail_row.addWidget(self.range_label)
        detail_row.addStretch(1)
        root.addLayout(detail_row)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.count_label = QLabel("已采 0 条", self)
        self.count_label.setObjectName("Muted")
        self.count_label.setMinimumWidth(82)
        self.rate_label = QLabel("实际速率 --", self)
        self.rate_label.setObjectName("Muted")
        self.rate_label.setMinimumWidth(150)
        bottom.addWidget(self.count_label)
        bottom.addWidget(self.rate_label)
        bottom.addStretch(1)

        self.single_btn = QPushButton("单次读数", self)
        self.single_btn.clicked.connect(self.single_read_requested)
        bottom.addWidget(self.single_btn)

        self.start_btn = QPushButton("开始测量", self)
        self.start_btn.setObjectName("StartButton")
        self.start_btn.setToolTip("空格键：开始/停止测量")
        self.start_btn.setEnabled(False)
        self.start_btn.setMinimumWidth(170)
        self.start_btn.clicked.connect(self.start_stop_requested)
        bottom.addWidget(self.start_btn)
        root.addLayout(bottom)

        self._state = "disconnected"
        self._digits = "5½"
        self._unit_mode = "auto"
        self._accuracy_tier = "1y"
        self._ac_band = "10-20k"
        self._auto_range = True
        self._accuracy_error_base = 0.0
        self._resolution_base = 0.0
        self._full_scale_base = 0.0
        self._extra_decimals = 0
        self._daq_mode = False
        self._daq_nplc = 1.0
        self._daq_channels = 1
        self._display_unit_label = ""
        self._status: InstrumentStatus | None = None
        self._display_interval_ms = 33
        self._last_reading: Reading | None = None
        self._range_reading: Reading | None = None
        self._pending: deque[Reading] = deque(maxlen=60)
        self._display_timer = QTimer()
        self._display_timer.setSingleShot(False)
        self._display_timer.setInterval(33)
        self._display_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._display_timer.timeout.connect(self._tick_display)
        self.tier_label.clicked.connect(self._cycle_tier)
        self.display_updates = 0

    def set_state(self, state: str, detail: str) -> None:
        self._state = state
        connected = state in {"ready", "reading", "acquiring", "stopping"}
        self.chips["Rmt"].set_state(connected)
        self.display.setEnabled(connected)
        self.function_badge.setEnabled(connected)
        for chip in self.chips.values():
            chip.setEnabled(connected)
        self.single_btn.setEnabled(state == "ready")
        self.single_btn.setText("正在读数…" if state == "reading" else "单次读数")

        if state == "acquiring":
            self.start_btn.setObjectName("StopButton")
            self.start_btn.setText("停止测量")
            self.start_btn.setEnabled(True)
        elif state == "stopping":
            self.start_btn.setObjectName("StopButton")
            self.start_btn.setText("正在停止…")
            self.start_btn.setEnabled(False)
        elif state == "ready":
            self.start_btn.setObjectName("StartButton")
            self.start_btn.setText("开始测量")
            self.start_btn.setEnabled(True)
        else:
            self.start_btn.setObjectName("StartButton")
            self.start_btn.setText("开始测量")
            self.start_btn.setEnabled(False)
        self.start_btn.style().unpolish(self.start_btn)
        self.start_btn.style().polish(self.start_btn)

        if not connected:
            self._pending.clear()
            self._display_timer.stop()
            self._last_reading = None
            self._range_reading = None
            self.display.set_value(" " * FIELD_WIDTH, "")
            self.accuracy_label.setText("精度误差 —")
            self._update_range_label()
        elif state == "acquiring" and not self._display_timer.isActive():
            # 采集中让 30 Hz 定时器持续运行，不要每批停/启；
            # 停启会引入相位差，导致每批剩一条、显示速率掉到 ~25/s。
            self._display_timer.start()
        self._fit_value_font()

    def reset_for_new_run(self) -> None:
        self._pending.clear()
        self._display_timer.stop()
        self._last_reading = None
        self.display.set_value(" " * FIELD_WIDTH, "")
        self.accuracy_label.setText("精度误差 —")
        # 不要在这里重算量程：旧的 _last_reading 被清空后，
        # _update_range_label 会暂时退回 status.range_text，造成量程闪一下。
        # 量程保留到第一条新读数/新的仪器状态到达。

    def set_daq_mode(self, enabled: bool = True, nplc: float = 1.0) -> None:
        """34970A 页面不显示精度误差/位数，只显示当前 NPLC。"""
        self._daq_mode = enabled
        self._daq_nplc = nplc
        self.accuracy_label.setVisible(not enabled)
        self.tier_label.setVisible(not enabled)
        if enabled:
            self.range_label.setText(f"NPLC {nplc:g}")
            self._update_daq_term_chip()
        else:
            self._update_range_label()

    def set_daq_channels(self, count: int) -> None:
        self._daq_channels = max(1, int(count))
        if self._daq_mode:
            self._update_daq_term_chip()

    def _update_daq_term_chip(self) -> None:
        self.chips["Term"].setText(f"{self._daq_channels}CH")
        self.chips["Term"].setToolTip(
            f"当前扫描通道数：{self._daq_channels}"
        )

    def set_extra_decimals(self, extra_decimals: int) -> None:
        extra_decimals = max(0, min(9, int(extra_decimals)))
        if extra_decimals != self._extra_decimals:
            self._extra_decimals = extra_decimals
            if self._last_reading is not None:
                self._show_reading(self._last_reading)

    def set_digits(self, digits: str) -> None:
        if digits == self._digits:
            return
        self._digits = digits
        self._update_range_label()
        self._update_resolution()
        if self._last_reading is not None:
            self._show_reading(self._last_reading)

    def set_range_mode(self, auto: bool) -> None:
        self._auto_range = auto
        self.chips["Range"].setText("Auto" if auto else "Man")
        # 手动量程时该提示高亮，自动时保持灰色。
        self.chips["Range"].set_state(not auto)
        self._update_range_label()
        self._update_accuracy()

    def _effective_range(self, reading: Reading | None) -> float | None:
        if not self._auto_range or reading is None:
            return None
        if reading.function_label in {"频率", "周期"}:
            return None
        if reading.function_label == "二极管":
            return 1.0
        if reading.function_label == "导通":
            return 1000.0
        spec = function_spec_by_label(reading.function_label)
        if spec is None or not spec.ranges:
            return None
        value = abs(reading.value)
        for range_value in sorted(spec.ranges):
            if value <= range_value * 1.2:
                return range_value
        return max(spec.ranges)

    def set_flags(self, az: bool, null: bool, filt: bool = False) -> None:
        self.chips["AZ"].set_state(az)
        self.chips["Null"].set_state(null)

    def set_unit_mode(self, mode: str) -> None:
        if mode == self._unit_mode:
            return
        self._unit_mode = mode
        if self._last_reading is not None:
            self._show_reading(self._last_reading)

    def set_ac_band(self, band: str) -> None:
        if band == self._ac_band:
            return
        self._ac_band = band
        self._update_accuracy()

    def set_accuracy_tier(self, tier: str) -> None:
        if tier not in _TIER_CYCLE:
            tier = "1y"
        self._accuracy_tier = tier
        self.tier_label.setText(f"({_TIER_SHORT[tier]})")
        self._update_accuracy()

    def set_display_interval_ms(self, interval_ms: float) -> None:
        """按有效采样率回放批内样本：10/s 时 100ms，30/s 时 33ms。"""

        interval = max(10, int(round(interval_ms)))
        if interval == self._display_interval_ms:
            return
        self._display_interval_ms = interval
        self._display_timer.setInterval(interval)

    def set_status(self, status: InstrumentStatus) -> None:
        old_label = self._status.function.label if self._status is not None else None
        if old_label is not None and old_label != status.function.label:
            # 功能变了，旧读数不能继续用于量程显示。
            self._range_reading = None
        self._status = status
        self.function_badge.setText(status.function.label)
        spec = function_spec_by_label(status.function.label)
        self.chips["FILT"].set_state(bool(spec and spec.supports_ac_filter))
        if self._state in {"ready", "reading", "acquiring", "stopping"}:
            self.chips["Rmt"].set_state(True)
        if self._daq_mode:
            self._update_daq_term_chip()
            self._update_range_label()
            self._update_accuracy()
            return
        terminal = (status.terminal or "").upper()
        if terminal == "REAR":
            self.chips["Term"].setText("Rear")
            self.chips["Term"].setToolTip("后面板端子（Rear）")
        else:
            self.chips["Term"].setText("Front")
            self.chips["Term"].setToolTip("前面板端子（Front）")
        self._update_range_label()
        self._update_accuracy()

    def _update_range_label(self) -> None:
        if self._daq_mode:
            self.range_label.setText(f"NPLC {self._daq_nplc:g}")
            return
        status = self._status
        if status is None:
            self.range_label.setText(f"量程 — · {self._digits}")
            return
        label = status.function.label
        if label in {"频率", "周期"}:
            self.range_label.setText(f"量程 {label} · {self._digits}")
            return
        if label == "二极管":
            self.range_label.setText(
                f"量程 1 V · 测试电流 1 mA · {self._digits}"
            )
            return
        if label == "导通":
            self.range_label.setText(f"量程 1 kΩ · {self._digits}")
            return
        hold_reading = (
            self._last_reading
            if self._last_reading is not None
            else self._range_reading
        )
        effective = self._effective_range(hold_reading)
        range_text = f"{effective:g}" if effective is not None else status.range_text
        if label in {"DCI", "ACI"} and range_text:
            try:
                current_range = abs(float(range_text))
            except ValueError:
                current_range = 0.0
            shunt = "5 Ω" if current_range <= 0.1 else "0.1 Ω"
            text = format_range(range_text, status.function.unit)
            self.range_label.setText(
                f"量程 {text} · 分流 {shunt} · {self._digits}"
            )
            return
        if range_text:
            text = format_range(range_text, status.function.unit)
            self.range_label.setText(f"量程 {text} · {self._digits}")
        else:
            self.range_label.setText(f"量程 — · {self._digits}")

    def set_reading(self, reading: Reading) -> None:
        """单次读数立即显示。"""

        self._last_reading = reading
        self._show_reading(reading)

    def push_batch(self, readings: tuple[Reading, ...]) -> None:
        """把一批读数按 30 Hz 节奏喂给显示。

        READ? 一次拿回 10 条，如果直接整批刷新，屏幕只有约 3 次/秒；
        这里先把第一条立即显示，其余每隔 33 ms 显示一条，让数字真正以
        约 30 次/秒变化。显示的是已经采到的真实样本，CSV 时间戳不受影响。
        """

        if not readings:
            return
        if self._display_timer.isActive():
            self._pending.extend(readings)
            return
        self._show_reading(readings[0])
        self._pending.extend(readings[1:])
        if not self._display_timer.isActive():
            self._display_timer.start()

    def _tick_display(self) -> None:
        if not self._pending:
            # 采集中保持 30 Hz 运行；停止后再把剩余队列排空并停表。
            if self._state not in {"acquiring", "stopping"}:
                self._display_timer.stop()
            return
        self._show_reading(self._pending.popleft())
        if not self._pending and self._state not in {"acquiring", "stopping"}:
            self._display_timer.stop()

    def display_text_for(self, reading: Reading) -> tuple[str, str]:
        if reading.ovld:
            if reading.function_label in {"导通", "CONT"}:
                return "OPEN", ""
            return "Overload", ""
        effective = self._effective_range(reading)
        range_text = (
            f"{effective:g}"
            if effective is not None
            else (self._status.range_text if self._status is not None else None)
        )
        extra_decimals = self._extra_decimals if reading.average_count > 0 else 0
        return format_measurement_fixed(
            reading.value,
            reading.unit,
            self._digits,
            self._unit_mode,
            reading.function_label,
            range_text,
            extra_decimals,
        )

    def _show_reading(self, reading: Reading) -> None:
        self._last_reading = reading
        self._range_reading = reading
        if self.function_badge.text() != reading.function_label:
            self.function_badge.setText(reading.function_label)
        self.display_updates += 1
        if reading.ovld:
            if reading.function_label in {"导通", "CONT"}:
                self.display.set_value("OPEN".rjust(FIELD_WIDTH), "")
            else:
                self.display.set_value("Overload".rjust(FIELD_WIDTH), "")
            self._update_accuracy()
            return
        text, unit = self.display_text_for(reading)
        self.display.set_value(text, unit)
        if unit:
            self._display_unit_label = unit
            self.display_unit_changed.emit(unit, unit_scale(unit))
        self._update_accuracy()

    def _cycle_tier(self) -> None:
        index = _TIER_CYCLE.index(self._accuracy_tier)
        self._accuracy_tier = _TIER_CYCLE[(index + 1) % len(_TIER_CYCLE)]
        self.tier_label.setText(f"({_TIER_SHORT[self._accuracy_tier]})")
        self._update_accuracy()
        self.tier_changed.emit(self._accuracy_tier)

    def _set_precision(self, error: float) -> None:
        error = max(0.0, float(error))
        if error != self._accuracy_error_base:
            self._accuracy_error_base = error
            self.precision_changed.emit(error)

    def _update_resolution(self) -> None:
        """当前分辨率和满度（基本单位）。"""

        status = self._status
        resolution = 0.0
        full_scale = 0.0
        if status is not None and status.function.label not in {"频率", "周期"}:
            effective = self._effective_range(self._last_reading)
            range_text = (
                f"{effective:g}"
                if effective is not None
                else status.range_text
            )
            try:
                range_value = abs(float(range_text))
                digit_count = int(str(self._digits)[0])
                if range_value > 0:
                    full_scale = range_value
                    if digit_count > 0:
                        resolution = range_value / (10**digit_count)
            except (TypeError, ValueError):
                resolution = 0.0
                full_scale = 0.0
        self._set_resolution(resolution)
        self._set_full_scale(full_scale)

    def _set_resolution(self, resolution: float) -> None:
        resolution = max(0.0, float(resolution))
        if resolution != self._resolution_base:
            self._resolution_base = resolution
            self.resolution_changed.emit(resolution)

    def _set_full_scale(self, full_scale: float) -> None:
        full_scale = max(0.0, float(full_scale))
        if full_scale != self._full_scale_base:
            self._full_scale_base = full_scale
            self.full_scale_changed.emit(full_scale)

    def _update_accuracy(self) -> None:
        self._update_resolution()
        reading = self._last_reading
        if reading is None or self._status is None or reading.ovld:
            self.accuracy_label.setText("精度误差 —")
            self._set_precision(0.0)
            return
        effective = self._effective_range(reading)
        range_value = (
            f"{effective:g}"
            if effective is not None
            else self._status.range_text
        )
        result = compute_accuracy(
            reading.function_label,
            reading.value,
            range_value,
            self._accuracy_tier,
            self._ac_band,
        )
        if result is None:
            self.accuracy_label.setText("精度误差 —")
            self.accuracy_label.setToolTip("AC/频率/周期需要先确定频率段或时间基准")
            self._set_precision(0.0)
            return
        self._set_precision(result.error)
        display_unit = self.display.display_unit
        base = result.unit
        prefix = (
            display_unit[: -len(base)]
            if base and display_unit.endswith(base)
            else ""
        )
        factor = _UNIT_FACTORS.get(prefix)
        if factor is None:
            error_text, error_unit = format_measurement_fixed(
                result.error, result.unit, self._digits, self._unit_mode
            )
            self.accuracy_label.setText(f"± {error_text.strip()} {error_unit}")
        else:
            scaled = result.error / factor
            # 精度值至少保留两位有效数字；主读数只有 4 位小数时，
            # 145 µV 不能四舍五入成 0.0001 V。
            if scaled > 0:
                exponent = math.floor(math.log10(scaled))
                significant_decimals = min(9, max(0, 1 - exponent))
            else:
                significant_decimals = 0
            decimals = max(self.display.decimals, significant_decimals)
            self.accuracy_label.setText(
                f"± {scaled:.{decimals}f} {display_unit}"
            )
        self.accuracy_label.setToolTip(result.note)
        self._update_range_label()

    def current_display_text(self) -> tuple[str, str]:
        return self.display._text.strip(), self.display.display_unit

    def floating_statuses(self) -> dict[str, bool]:
        label = self._status.function.label if self._status is not None else ""
        return {
            "Man": not self._auto_range,
            "Math": self.chips["Null"].property("active") == "true",
            "Rear": (
                self._status is not None
                and (self._status.terminal or "").upper() == "REAR"
            ),
            "Diode": label == "二极管",
            "Cont": label == "导通",
        }

    def floating_snapshot(self) -> tuple[str, str, str, bool]:
        """悬浮窗用：原始显示文本、单位、位数和 OVLD 状态。"""

        reading = self._last_reading
        if reading is None or self._status is None:
            return "", "", self._digits, False
        if reading.ovld:
            if reading.function_label in {"导通", "CONT"}:
                return "OPEN", "", self._digits, False
            return "OVLD", reading.unit, self._digits, True
        text, unit = self.display_text_for(reading)
        return text, unit, self._digits, False

    def set_count(self, count: int) -> None:
        self.count_label.setText(f"已采 {count} 条")

    def set_rate(self, rate: float | None) -> None:
        self.rate_label.setText("实际速率 --" if rate is None else f"实际速率 {rate:.1f} Hz")

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self._fit_value_font()

    def _fit_value_font(self) -> None:
        """按固定字符宽度的字段选字号，不随当前数值/负号改变。"""

        self.display.fit_font()
