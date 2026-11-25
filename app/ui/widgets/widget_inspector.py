"""调试辅助：显示鼠标当前悬停控件的 Qt 类名、objectName 和层级。"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QAbstractButton, QLabel, QWidget


class WidgetInspector(QObject):
    def __init__(
        self,
        callback: Callable[[str], None],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._callback = callback
        self._enabled = False
        self._last = ""
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._sample)

    @property
    def current_text(self) -> str:
        return self._last

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if enabled:
            self._timer.start()
            self._sample()
        else:
            self._timer.stop()
            self._last = ""
            self._callback("")

    def _sample(self) -> None:
        if not self._enabled:
            return
        widget = QApplication.widgetAt(QCursor.pos())
        if widget is None:
            return
        text = self.describe(widget)
        if text != self._last:
            self._last = text
            self._callback(text)

    def describe(self, widget: QWidget) -> str:
        parts: list[str] = []
        current: QWidget | None = widget
        while current is not None:
            name = current.metaObject().className()
            object_name = current.objectName()
            if object_name:
                name += f"#{object_name}"
            extra = ""
            if isinstance(current, QAbstractButton):
                extra = f' "{current.text()}"'
            elif isinstance(current, QLabel) and current.text():
                text = current.text().replace("\n", " ")
                extra = f' "{text[:30]}"'
            parts.append(name + extra)
            current = current.parentWidget()
        parts.reverse()
        return " > ".join(parts)
