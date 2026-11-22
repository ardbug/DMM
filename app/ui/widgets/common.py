"""跨界面复用的小控件与格式化函数。"""

from __future__ import annotations

import math

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget


class StatusChip(QLabel):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName("StatusChip")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self.font()
        font.setBold(True)
        self.setFont(font)
        self._active = False
        self._alarm = False
        self.set_state(False, False)

    def set_state(self, active: bool, alarm: bool = False) -> None:
        if active == self._active and alarm == self._alarm:
            return
        self._active = active
        self._alarm = alarm
        self.setProperty("active", "true" if active else "false")
        self.setProperty("alarm", "true" if alarm else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class ErrorBanner(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ErrorBanner")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 6)
        layout.setSpacing(8)
        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        layout.addWidget(self._label, 1)
        close = QPushButton("关闭", self)
        close.setFixedWidth(56)
        close.clicked.connect(self.hide)
        layout.addWidget(close)
        self.hide()

    def show_error(self, title: str, detail: str) -> None:
        self._label.setText(f"<b>{title}</b>　{detail}")
        self.show()


class PlaceholderChart(QWidget):
    """阶段 3 之前的占位绘图区，顺带把布局空间占住。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(220)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        from PySide6.QtGui import QColor, QPainter, QPen

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(16, 12, -16, -12)
        painter.fillRect(rect, QColor("#00000000"))

        grid_pen = QPen(QColor("#8b95a5"))
        grid_pen.setStyle(Qt.PenStyle.DotLine)
        grid_pen.setWidth(1)
        painter.setPen(grid_pen)
        for i in range(1, 6):
            y = rect.top() + rect.height() * i / 6
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))
        for i in range(1, 8):
            x = rect.left() + rect.width() * i / 8
            painter.drawLine(int(x), rect.top(), int(x), rect.bottom())

        painter.setPen(QColor("#7b8491"))
        font = painter.font()
        font.setPointSize(11)
        painter.setFont(font)
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter,
            "阶段 3：实时趋势图\n悬停读数 · 框选统计 · px 模式 · OVLD 开关",
        )


_DISPLAY_UNIT_SCALE: dict[str, float] = {
    "V": 1.0,
    "mV": 1e-3,
    "µV": 1e-6,
    "A": 1.0,
    "mA": 1e-3,
    "µA": 1e-6,
    "Ω": 1.0,
    "kΩ": 1e3,
    "MΩ": 1e6,
    "Hz": 1.0,
    "kHz": 1e3,
    "MHz": 1e6,
    "s": 1.0,
    "ms": 1e-3,
    "µs": 1e-6,
}


def unit_scale(unit: str) -> float:
    return _DISPLAY_UNIT_SCALE.get(unit, 1.0)


def plain_number(value: float, decimals: int = 9) -> str:
    """不用科学计数法的数值文本。"""

    if not math.isfinite(value):
        return "—"
    text = f"{value:.{max(0, decimals)}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if text in {"", "-0"}:
        return "0"
    return text


def format_measurement(value: float, unit: str) -> tuple[str, str]:
    """按 34401A 习惯做 m/k/M/µ 换算；不是数值修约，只影响显示。"""

    if not math.isfinite(value):
        return f"{value}", unit
    if value == 0:
        return "0.000000", unit
    magnitude = abs(value)
    if magnitude >= 1e6:
        prefix, scale = "M", 1e6
    elif magnitude >= 1e3:
        prefix, scale = "k", 1e3
    elif magnitude >= 1:
        prefix, scale = "", 1.0
    elif magnitude >= 1e-3:
        prefix, scale = "m", 1e-3
    elif unit == "V":
        # 电压不再显示 µV；小于 1 mV 也统一用 mV。
        prefix, scale = "m", 1e-3
    elif magnitude >= 1e-6:
        prefix, scale = "µ", 1e-6
    else:
        return plain_number(value, 9), unit

    scaled = value / scale
    exponent = math.floor(math.log10(abs(scaled))) if scaled else 0
    decimals = max(0, 7 - exponent)
    return f"{scaled:.{decimals}f}", f"{prefix}{unit}"


FIELD_WIDTH = 10
_SIGNIFICANT_DIGITS = {"4½": 5, "5½": 6, "6½": 7}

_UNIT_FAMILIES: dict[str, list[tuple[str, str]]] = {
    "V": [("auto", "AUTO"), ("m", "mV"), ("", "V")],
    "A": [("auto", "AUTO"), ("m", "mA"), ("", "A")],
    "Ω": [("auto", "AUTO"), ("", "Ω"), ("k", "kΩ"), ("M", "MΩ")],
    "Hz": [("auto", "AUTO"), ("", "Hz"), ("k", "kHz"), ("M", "MHz")],
    "s": [("auto", "AUTO"), ("u", "µs"), ("m", "ms"), ("", "s")],
}
_PREFIX_SCALE = {"u": 1e-6, "m": 1e-3, "": 1.0, "k": 1e3, "M": 1e6}


def unit_options(unit: str, function_label: str = "") -> list[tuple[str, str]]:
    """返回当前功能可选的显示单位：[(key, label), ...]。"""

    options = list(_UNIT_FAMILIES.get(unit, [("auto", "AUTO")]))
    if unit == "V" and function_label == "二极管":
        return [item for item in options if item[0] in {"auto", ""}]
    return options


def format_measurement_fixed(
    value: float,
    unit: str,
    digits: str = "5½",
    unit_mode: str = "auto",
    function_label: str = "",
    range_value: float | str | None = None,
    extra_decimals: int = 0,
) -> tuple[str, str]:
    """固定字符宽度的工程单位格式。

    - AUTO 时按数值自动选 m/k/M/µ。
    - 手动单位按 unit_options 的 key 固定。
    - 正数预留一个符号位（空格），与负数等宽。
    - 整个字段补到 FIELD_WIDTH 个字符，字号只按字段宽度计算，不随数值/负号改变。
    """

    if not math.isfinite(value):
        return f"{value}".rjust(FIELD_WIDTH), unit
    extra_decimals = max(0, min(9, int(extra_decimals)))
    significant = _SIGNIFICANT_DIGITS.get(digits, 6)
    options = unit_options(unit, function_label)
    valid_modes = {key for key, _ in options}
    auto_unit = unit_mode not in valid_modes or unit_mode == "auto"
    if auto_unit:
        prefix, scale = _choose_auto_prefix(value, unit, function_label)
        label = f"{prefix}{unit}"
    else:
        scale = _PREFIX_SCALE[unit_mode]
        label = dict(options)[unit_mode]

    # 固定量程功能的状态里可能没有 RANG?，用固定满量程。
    if range_value in {None, ""}:
        if function_label == "二极管":
            range_value = 1.0
        elif function_label == "导通":
            range_value = 1000.0

    # 频率/周期没有量程分辨率，继续按有效位数。
    if function_label not in {"频率", "周期"} and range_value not in {None, ""}:
        try:
            range_base = float(range_value)
        except (TypeError, ValueError):
            range_base = 0.0
        if range_base > 0:
            digits_count = int(str(digits)[0])
            resolution = range_base / (10 ** digits_count)
            scaled_resolution = resolution / scale
            if scaled_resolution > 0:
                decimals = max(
                    0,
                    min(
                        8,
                        int(math.ceil(-math.log10(scaled_resolution) - 1e-12))
                        + extra_decimals,
                    ),
                )
                scaled = value / scale
                text = f"{abs(scaled):.{decimals}f}"
                while len(text) > FIELD_WIDTH - 1 and decimals > 0:
                    decimals -= 1
                    text = f"{abs(scaled):.{decimals}f}"
                sign = "-" if scaled < 0 else " "
                return (sign + text).rjust(FIELD_WIDTH), label

    if auto_unit:
        return _format_auto(
            value, unit, significant, function_label, extra_decimals
        )
    scaled = value / scale
    text = _fixed_numeric_text(abs(scaled), significant + extra_decimals)
    sign = "-" if scaled < 0 else " "
    return (sign + text).rjust(FIELD_WIDTH), label


def _choose_auto_prefix(
    value: float,
    unit: str,
    function_label: str = "",
) -> tuple[str, float]:
    magnitude = abs(value)
    if unit == "V" and function_label == "二极管":
        return "", 1.0
    if magnitude == 0:
        # 自动单位时零值不能退回 V：量程 100 mV 下会显示
        # 0.00000 V，和相邻的 0.00 mV 来回跳。电压/电流零值保持
        # m 前缀；电阻/频率等零值用基本单位。
        if unit in {"V", "A"}:
            return "m", 1e-3
        return "", 1.0
    if unit == "Ω":
        # 欧姆档不显示 mΩ；小于 1 Ω 仍用 Ω。
        if magnitude >= 1e6:
            return "M", 1e6
        if magnitude >= 1e3:
            return "k", 1e3
        return "", 1.0
    if magnitude >= 1e6:
        return "M", 1e6
    if magnitude >= 1e3:
        return "k", 1e3
    if magnitude >= 1:
        return "", 1.0
    if magnitude >= 1e-3:
        return "m", 1e-3
    if unit in {"V", "A", "Ω"}:
        return "m", 1e-3
    if magnitude >= 1e-6:
        return "µ", 1e-6
    if magnitude >= 1e-9:
        return "µ", 1e-6
    return "", 1.0


def _format_auto(
    value: float,
    unit: str,
    significant: int,
    function_label: str = "",
    extra_decimals: int = 0,
) -> tuple[str, str]:
    prefix, scale = _choose_auto_prefix(value, unit, function_label)
    if scale == 1.0 and prefix == "" and abs(value) < 1e-9:
        text = plain_number(value, min(9, significant + 3))
        sign = "-" if value < 0 else " "
        return (sign + text).rjust(FIELD_WIDTH), unit
    scaled = value / scale
    text = _fixed_numeric_text(abs(scaled), significant + extra_decimals)
    sign = "-" if scaled < 0 else " "
    return (sign + text).rjust(FIELD_WIDTH), f"{prefix}{unit}"


def _fixed_numeric_text(magnitude: float, significant: int) -> str:
    """生成不带符号的数字串，最多占 FIELD_WIDTH-1 个字符。"""

    if magnitude == 0:
        exponent = 0
    else:
        exponent = math.floor(math.log10(magnitude))
    decimals = max(0, min(12, significant - 1 - exponent))
    text = f"{magnitude:.{decimals}f}"
    if len(text) <= FIELD_WIDTH - 1:
        return text

    # 界面不允许科学计数法：继续减少小数位，宁可显示 0.000…。
    while len(text) > FIELD_WIDTH - 1 and decimals > 0:
        decimals -= 1
        text = f"{magnitude:.{decimals}f}"
    return text


def format_range(value_text: str, unit: str) -> str:
    try:
        value = float(value_text)
    except (TypeError, ValueError):
        return value_text or "—"
    return _format_compact(value, unit)


def format_nplc(value_text: str) -> str:
    try:
        value = float(value_text)
    except (TypeError, ValueError):
        return value_text or "—"
    return f"{value:g}"


def digits_from_nplc(value_text: str) -> str:
    try:
        nplc = float(value_text)
    except (TypeError, ValueError):
        return "—"
    if nplc <= 0.02:
        return "4½"
    if nplc <= 1:
        return "5½"
    return "6½"


def terminal_text(raw: str) -> str:
    mapping = {"FRON": "前端", "REAR": "后端"}
    return mapping.get(raw.strip().upper(), raw.strip() or "—")


def _format_compact(value: float, unit: str) -> str:
    magnitude = abs(value)
    if magnitude >= 1e6:
        return f"{value / 1e6:g} M{unit}"
    if magnitude >= 1e3:
        return f"{value / 1e3:g} k{unit}"
    if magnitude >= 1:
        return f"{value:g} {unit}"
    if magnitude >= 1e-3:
        return f"{value / 1e-3:g} m{unit}"
    if magnitude >= 1e-6:
        return f"{value / 1e-6:g} µ{unit}"
    return f"{value:g} {unit}"
