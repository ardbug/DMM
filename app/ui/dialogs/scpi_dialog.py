"""SCPI 终端：单条命令/查询，采集期间只读提示。"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ScpiDialog(QDialog):
    send_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("SCPI 终端")
        self.resize(760, 500)
        self._history: list[str] = []
        self._history_index = 0

        root = QVBoxLayout(self)
        tip = QLabel(
            "只发送单条命令；带 ? 为查询。写命令可能改变仪器状态，"
            "采集期间请先停止采集。",
            self,
        )
        tip.setObjectName("Muted")
        tip.setWordWrap(True)
        root.addWidget(tip)

        self.log = QPlainTextEdit(self)
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("发送记录和仪器响应会显示在这里")
        root.addWidget(self.log, 1)

        row = QHBoxLayout()
        self.input = QLineEdit(self)
        self.input.setPlaceholderText("例如 *IDN?  或  SYST:ERR?")
        self.send_btn = QPushButton("发送", self)
        self.clear_btn = QPushButton("清空记录", self)
        row.addWidget(self.input, 1)
        row.addWidget(self.send_btn)
        row.addWidget(self.clear_btn)
        root.addLayout(row)

        quick = QHBoxLayout()
        for command in ("*IDN?", "SYST:ERR?", "*CLS"):
            button = QPushButton(command, self)
            button.setToolTip(f"直接发送 {command}")
            button.clicked.connect(
                lambda _checked=False, cmd=command:
                self._send_command(cmd)
            )
            quick.addWidget(button)
        quick.addStretch(1)
        root.addLayout(quick)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.send_btn.clicked.connect(self._send)
        self.input.returnPressed.connect(self._send)
        self.clear_btn.clicked.connect(self.log.clear)

    def _send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._send_command(text)

    def _send_command(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self._history.append(text)
        self._history_index = len(self._history)
        self.log.appendPlainText(f">>> {text}")
        self.send_requested.emit(text)

    def append_result(self, command: str, response: str) -> None:
        text = response.strip()
        if not text:
            text = "(无响应)" if "?" in command else "已发送"
        self.log.appendPlainText(f"{command}  ->  {text}\n")
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if event.key() == Qt.Key.Key_Up and self._history:
            self._history_index = max(0, self._history_index - 1)
            self.input.setText(self._history[self._history_index])
            return
        if event.key() == Qt.Key.Key_Down and self._history:
            self._history_index = min(len(self._history), self._history_index + 1)
            if self._history_index >= len(self._history):
                self.input.clear()
            else:
                self.input.setText(self._history[self._history_index])
            return
        super().keyPressEvent(event)
