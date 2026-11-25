"""简易仪器错误码查询（目前只有 34401A）。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.error_codes import filter_error_codes


class ErrorCodeDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        model: str = "34401A",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("错误码查询")
        self.resize(720, 560)

        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("机型：", self))
        self.model_combo = QComboBox(self)
        self.model_combo.addItem("34401A", "34401A")
        self.model_combo.addItem("34970A", "34970A")
        model_index = self.model_combo.findData(model)
        if model_index >= 0:
            self.model_combo.setCurrentIndex(model_index)
        top.addWidget(self.model_combo)
        top.addSpacing(8)
        self.search = QLineEdit(self)
        self.search.setPlaceholderText(
            "输入错误码或关键词，多个用逗号分隔，例如 513，514"
        )
        self.search.setClearButtonEnabled(True)
        top.addWidget(self.search, 1)
        self.count_label = QLabel("", self)
        top.addWidget(self.count_label)
        root.addLayout(top)

        self.table = QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["错误码", "说明"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        root.addWidget(self.table, 1)

        self.search.textChanged.connect(self._refresh)
        self.model_combo.currentIndexChanged.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        model = str(self.model_combo.currentData() or "34401A")
        rows = filter_error_codes(self.search.text(), model)
        self.table.setRowCount(len(rows))
        for row, (code, description) in enumerate(rows):
            code_item = QTableWidgetItem(code)
            code_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self.table.setItem(row, 0, code_item)
            self.table.setItem(row, 1, QTableWidgetItem(description))
        self.count_label.setText(f"共 {len(rows)} 条")
        if rows:
            self.table.resizeRowsToContents()
            self.table.scrollToTop()


__all__ = ["ErrorCodeDialog"]
