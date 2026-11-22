"""下拉框：弹层用显式 delegate 绘制，避免 Fusion 选中/hover 时白底白字。"""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QWidget,
)


class _ComboItemDelegate(QStyledItemDelegate):
    """自己画每一行；只有已选项高亮，悬停不高亮。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.background = QColor("#ffffff")
        self.foreground = QColor("#1f2328")
        self.highlight = QColor("#2563eb")
        self.highlighted_text = QColor("#ffffff")

    def set_colors(
        self,
        background: QColor,
        foreground: QColor,
        highlight: QColor,
        highlighted_text: QColor,
    ) -> None:
        self.background = background
        self.foreground = foreground
        self.highlight = highlight
        self.highlighted_text = highlighted_text

    def paint(self, painter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        combo = self.parent()
        if isinstance(combo, QComboBox) and not selected:
            selected = index.row() == combo.currentIndex()
        if selected:
            background = self.highlight
            foreground = self.highlighted_text
        else:
            background = self.background
            foreground = self.foreground
        painter.fillRect(option.rect, background)
        painter.setPen(foreground)
        painter.setFont(option.font)
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.drawText(
            option.rect.adjusted(7, 0, -7, 0),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            text,
        )
        painter.restore()

    def sizeHint(self, option, index):  # noqa: N802 - Qt 命名
        size = super().sizeHint(option, index)
        size.setHeight(max(24, size.height()))
        return size


class ThemedComboBox(QComboBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._delegate = _ComboItemDelegate(self)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        # 鼠标只是经过下拉框时滚轮不应改变选项；弹层打开时仍允许滚动列表。
        if self.view().isVisible():
            super().wheelEvent(event)
        else:
            event.ignore()

    def showPopup(self) -> None:  # noqa: N802 - Qt 命名
        view = self.view()
        # QComboBox 自身的 Window 角色常被 Fusion 设成白色；用应用级调色板，
        # 才能和左右面板/卡片的背景一致。
        app = QApplication.instance()
        palette = app.palette() if app is not None else self.palette()
        background = palette.color(QPalette.ColorRole.Window)
        popup_palette = view.palette()
        popup_palette.setColor(QPalette.ColorRole.Base, background)
        popup_palette.setColor(QPalette.ColorRole.Window, background)
        popup_palette.setColor(
            QPalette.ColorRole.Highlight,
            palette.color(QPalette.ColorRole.Highlight),
        )
        popup_palette.setColor(
            QPalette.ColorRole.HighlightedText,
            palette.color(QPalette.ColorRole.HighlightedText),
        )
        view.setPalette(popup_palette)
        view.viewport().setPalette(popup_palette)
        self._delegate.set_colors(
            background,
            palette.color(QPalette.ColorRole.WindowText),
            palette.color(QPalette.ColorRole.Highlight),
            palette.color(QPalette.ColorRole.HighlightedText),
        )
        view.setItemDelegate(self._delegate)
        super().showPopup()
