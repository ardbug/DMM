"""大字号读数：自绘固定字符格，避免 QLabel 每次 setText 的布局/重绘开销。"""

from __future__ import annotations

import time

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QPalette
from PySide6.QtWidgets import QWidget

from app.ui.widgets.common import FIELD_WIDTH

_UNIT_BLOCK = 120


class DigitalReadout(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = " " * FIELD_WIDTH
        self._unit = ""
        self._value_font = QFont("Consolas", 64, QFont.Weight.DemiBold)
        self._unit_font = QFont("Consolas", 44, QFont.Weight.Medium)
        self.last_paint_ms = 0.0
        self.setMinimumHeight(110)
        self.setSizePolicy(
            self.sizePolicy().horizontalPolicy(),
            self.sizePolicy().verticalPolicy(),
        )

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(560, 180)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - Qt 命名
        return QSize(220, 100)

    @property
    def display_unit(self) -> str:
        return self._unit

    @property
    def decimals(self) -> int:
        text = self._text.strip()
        if "E" in text:
            text = text.split("E", 1)[0]
        if "." not in text:
            return 0
        return len(text.split(".", 1)[1].rstrip())

    def set_value(self, text: str, unit: str) -> None:
        if text == self._text and unit == self._unit:
            return
        self._text = text
        self._unit = unit
        self.update()

    def fit_font(self) -> None:
        available_width = max(120, self.width() - _UNIT_BLOCK - 8)
        available_height = max(60, int(self.height() * 0.72))
        chosen = 32
        for size in range(120, 30, -2):
            font = QFont("Consolas", size, QFont.Weight.DemiBold)
            metrics = QFontMetrics(font)
            if (
                metrics.horizontalAdvance("0" * FIELD_WIDTH) <= available_width
                and metrics.height() <= available_height
            ):
                chosen = size
                break
        self._value_font = QFont("Consolas", chosen, QFont.Weight.DemiBold)
        self._unit_font = QFont(
            "Consolas",
            max(24, min(56, chosen * 2 // 3)),
            QFont.Weight.Medium,
        )

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        started = time.perf_counter_ns()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        group = (
            QPalette.ColorGroup.Active
            if self.isEnabled()
            else QPalette.ColorGroup.Disabled
        )
        painter.setPen(self.palette().color(group, QPalette.ColorRole.WindowText))
        painter.setFont(self._value_font)
        value_rect = QRect(0, 0, max(10, self.width() - _UNIT_BLOCK - 8), self.height())
        painter.drawText(
            value_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )
        if self._unit:
            painter.setFont(self._unit_font)
            painter.setPen(self.palette().color(group, QPalette.ColorRole.Text))
            unit_rect = QRect(
                self.width() - _UNIT_BLOCK + 4,
                int(self.height() * 0.58),
                _UNIT_BLOCK - 4,
                int(self.height() * 0.30),
            )
            painter.drawText(
                unit_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._unit,
            )
        painter.end()
        self.last_paint_ms = (time.perf_counter_ns() - started) / 1_000_000

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().resizeEvent(event)
        self.fit_font()
        self.update()
