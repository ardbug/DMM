"""可折叠工具区：折叠后只保留标题行。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QFrame):
    """标题栏可点击折叠的区块。内容控件加到 ``body_layout``。"""

    move_requested = Signal(int)

    def __init__(
        self,
        title: str,
        parent: QWidget | None = None,
        expanded: bool = True,
        key: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CollapsibleSection")
        self.key = key or title

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header_row = QWidget(self)
        header_layout = QHBoxLayout(self.header_row)
        header_layout.setContentsMargins(0, 0, 4, 0)
        header_layout.setSpacing(2)

        self.header = QToolButton(self.header_row)
        self.header.setObjectName("CollapsibleHeader")
        self.header.setText(title)
        self.header.setCheckable(True)
        self.header.setChecked(expanded)
        self.header.setAutoRaise(True)
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.header.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )
        self.header.toggled.connect(self._on_toggled)
        header_layout.addWidget(self.header, 1)

        self.up_btn = QToolButton(self.header_row)
        self.up_btn.setObjectName("SectionMoveButton")
        self.up_btn.setText("↑")
        self.up_btn.setToolTip("上移")
        self.up_btn.setAutoRaise(True)
        self.up_btn.setFixedSize(22, 22)
        self.up_btn.clicked.connect(lambda: self.move_requested.emit(-1))
        header_layout.addWidget(self.up_btn)

        self.down_btn = QToolButton(self.header_row)
        self.down_btn.setObjectName("SectionMoveButton")
        self.down_btn.setText("↓")
        self.down_btn.setToolTip("下移")
        self.down_btn.setAutoRaise(True)
        self.down_btn.setFixedSize(22, 22)
        self.down_btn.clicked.connect(lambda: self.move_requested.emit(1))
        header_layout.addWidget(self.down_btn)

        outer.addWidget(self.header_row)

        self.body = QWidget(self)
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(12, 4, 12, 12)
        self.body_layout.setSpacing(7)
        self.body.setVisible(expanded)
        outer.addWidget(self.body)

    def _on_toggled(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.header.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def is_expanded(self) -> bool:
        return self.header.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.header.setChecked(expanded)

    def set_move_enabled(self, can_up: bool, can_down: bool) -> None:
        self.up_btn.setEnabled(can_up)
        self.down_btn.setEnabled(can_down)
