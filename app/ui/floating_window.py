"""置顶实时读数悬浮窗。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QLabel, QWidget

from app.ui.sections.readout_panel import ReadoutPanel

_WHEEL_OPTIONS = ("DCV", "CONT", "Ω2W", "DCI", "", "BACK")
_WHEEL_COMMANDS = ("VOLT", "CONT", "RES", "CURR", "", "BACK")

_UNIT_BY_FUNCTION = {
    "VDC": "VDC",
    "VAC": "VAC",
    "DCI": "ADC",
    "ACI": "AAC",
    "2WΩ": "OHM",
    "4WΩ": "OHM",
    "FRES": "OHM",
    "OHM": "OHM",
}


def floating_unit(unit: str, function_label: str) -> str:
    """生成固定 4 字符单位；例如 mVDC / ' VDC' / ' KHZ' / MOHM。"""

    if not unit:
        return " " * 4
    upper = unit.replace("μ", "u").upper()
    if upper in {"HZ", "KHZ", "MHZ"}:
        return upper.rjust(4)[:4]
    if upper in {"S", "MS", "US"}:
        return upper.rjust(4)[:4]
    code = _UNIT_BY_FUNCTION.get(function_label, "")
    if not code:
        return unit.upper().rjust(4)[:4]
    base = unit.replace("μ", "u")
    prefix = base[:-1] if len(base) > 1 else ""
    if prefix.upper() == "U":
        prefix = "u"
    text = f"{prefix}{code}"
    return text.rjust(4)[:4]


def floating_text(
    text: str, unit: str, function_label: str, digits: str
) -> str:
    clean = text.strip()
    if not clean:
        return "-"
    if clean.upper() == "OPEN":
        return "OPEN"
    sign, value = floating_value(clean, digits)
    if value == "OPEN":
        return "-"
    unit_text = floating_unit(unit, function_label)
    return f"{sign}{value}{unit_text}"


def floating_value(text: str, digits: str) -> tuple[str, str]:
    """返回固定符号位 + 8 字符数字字段（7 个数字，含小数点）。

    6½ 填满 7 个数字；5½ 填 6 个，最右 1 位留空；
    4½ 填 5 个，最右 2 位留空。
    """

    text = text.strip()
    if not text or text.lower() == "overload":
        return "", "OPEN"
    negative = text.startswith("-")
    body = text.lstrip("+-")
    target_digits = {"6": 7, "5": 6, "4": 5}.get(
        str(digits)[:1], 7
    )
    if "." not in body:
        body += "."
    integer, fraction = body.split(".", 1)
    digits_count = len(integer) + len(fraction)
    if digits_count < target_digits:
        fraction += "0" * (target_digits - digits_count)
    elif digits_count > target_digits:
        remove = digits_count - target_digits
        while remove > 0 and fraction:
            fraction = fraction[:-1]
            remove -= 1
        if remove > 0 and integer:
            integer = integer[:-remove]
    body = f"{integer}.{fraction}"
    if len(body) > 8:
        body = body[:8]
    sign = "-" if negative else " "
    return sign, body.ljust(8)[:8]


class RadialWheel(QWidget):
    """100 px 半径的六分区功能轮盘。"""

    selected = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedSize(200, 200)
        self._hover = -1
        self._center = QPointF(100, 100)
        self._inner_radius = 28.0
        self._outer_radius = 100.0
        self._hit_radius = 150.0

    def show_at(self, global_pos: QPoint) -> None:
        self.move(global_pos - QPoint(100, 100))
        self.show()
        self.raise_()
        self.grabMouse()

    def close_menu(self) -> None:
        if self.mouseGrabber() is self:
            self.releaseMouse()
        self.hide()

    def _sector_at(self, global_pos: QPoint) -> int | None:
        local = self.mapFromGlobal(global_pos)
        dx = local.x() - self._center.x()
        dy = local.y() - self._center.y()
        distance = math.hypot(dx, dy)
        if distance < self._inner_radius or distance > self._hit_radius:
            return None
        angle = (math.degrees(math.atan2(dy, dx)) + 90.0) % 360.0
        # 0 号扇区以正上方为中心，左右各 30°，再顺时针编号。
        return int(((angle + 30.0) % 360.0) // 60.0) % 6

    def finish_at(self, global_pos: QPoint) -> None:
        sector = self._sector_at(global_pos)
        if sector is not None:
            # 选项整体逆时针移动一位。
            self.selected.emit((sector + 1) % 6)
        self.close_menu()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        hover = self._sector_at(event.globalPosition().toPoint())
        if hover != self._hover:
            self._hover = -1 if hover is None else hover
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.finish_at(event.globalPosition().toPoint())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.close_menu()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outer = QRect(0, 0, 200, 200)
        for index in range(6):
            start = 60 - index * 60
            if index == self._hover:
                color = QColor(84, 204, 192, 235)
            else:
                color = QColor(22, 28, 36, 232) if index % 2 == 0 else QColor(
                    31, 39, 49, 232
                )
            painter.setBrush(color)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPie(outer, start * 16, 60 * 16)

        # 分割线对齐扇区边界（比旧位置转 30°）。
        painter.setPen(QPen(QColor(120, 132, 148, 220), 1))
        for index in range(6):
            angle = math.radians(60 - index * 60)
            x = self._center.x() + math.cos(angle) * self._outer_radius
            y = self._center.y() + math.sin(angle) * self._outer_radius
            painter.drawLine(self._center, QPointF(x, y))

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(150, 160, 175, 230), 2))
        painter.drawEllipse(self._center, self._outer_radius, self._outer_radius)

        painter.setBrush(QColor(12, 16, 22, 245))
        painter.setPen(QPen(QColor(150, 160, 175, 220), 1))
        painter.drawEllipse(self._center, 27, 27)

        painter.setPen(QColor(240, 244, 248))
        font = QFont("Microsoft YaHei UI", 10)
        font.setBold(True)
        painter.setFont(font)
        for sector in range(6):
            option_index = (sector + 1) % 6
            label = _WHEEL_OPTIONS[option_index]
            if not label:
                continue
            angle = math.radians(-90 + sector * 60)
            x = self._center.x() + math.cos(angle) * 65
            y = self._center.y() + math.sin(angle) * 65
            painter.drawText(
                QRect(int(x) - 46, int(y) - 12, 92, 24),
                Qt.AlignmentFlag.AlignCenter,
                label,
            )


class FloatingWindow(QWidget):
    command_requested = Signal(str)

    def __init__(
        self,
        readout: ReadoutPanel,
        percent: int = 100,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._readout = readout
        self._percent = max(50, min(200, int(percent)))
        self._drag_offset: QPoint | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.label = QLabel(self)
        self.label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True
        )
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet(
            "background: #05070a; color: #54ccc0;"
        )
        self.label.setGeometry(self.rect())

        self._wheel = RadialWheel(None)
        self._wheel.selected.connect(self._on_wheel_selected)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()
        self.apply_percent(self._percent)
        self.refresh()

    def apply_percent(self, percent: int) -> None:
        self._percent = max(50, min(200, int(percent)))
        width = max(250, round(500 * self._percent / 100))
        height = max(60, round(120 * self._percent / 100))
        self.resize(width, height)
        font = QFont("Consolas", 1)
        font.setPixelSize(max(20, round(height * 0.46)))
        font.setWeight(QFont.Weight.Bold)
        self.label.setFont(font)
        self.label.setGeometry(self.rect())

    def set_opacity_percent(self, percent: int) -> None:
        self.setWindowOpacity(max(0.2, min(1.0, int(percent) / 100.0)))

    def refresh(self) -> None:
        text, unit, digits, ovld = self._readout.floating_snapshot()
        if ovld:
            display = "OVLD"
        else:
            function_label = self._readout.function_badge.text()
            display = floating_text(text, unit, function_label, digits)
        if self.label.text() != display:
            self.label.setText(display)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        self.label.setGeometry(self.rect())
        super().resizeEvent(event)

    def _on_wheel_selected(self, index: int) -> None:
        if 0 <= index < len(_WHEEL_COMMANDS):
            command = _WHEEL_COMMANDS[index]
            if command:
                self.command_requested.emit(command)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self._wheel.show_at(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton and self._wheel.isVisible():
            self._wheel.finish_at(event.globalPosition().toPoint())
            event.accept()
            return
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._wheel.close_menu()
        super().closeEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (
            self._drag_offset is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)
