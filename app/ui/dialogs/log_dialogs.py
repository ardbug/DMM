"""软件日志与串口原始字节日志窗口（只读，不导出）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.constants import LOG_DIR
from app.transport.serial_log import SerialLogEntry, serial_log


class SoftwareLogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("软件日志")
        self.resize(900, 560)
        self._path = LOG_DIR / "34401a.log"
        self._last_text = ""

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(f"日志文件：{self._path}", self), 1)
        self.follow_check = QCheckBox("刷新滚动", self)
        self.follow_check.setChecked(True)
        self.follow_check.setToolTip("关闭后冻结当前日志，方便查看")
        self.follow_check.toggled.connect(self._on_follow_changed)
        top.addWidget(self.follow_check)
        root.addLayout(top)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self.text, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _on_follow_changed(self, enabled: bool) -> None:
        if enabled:
            self._refresh()

    def _refresh(self) -> None:
        if not self.follow_check.isChecked():
            return
        try:
            text = self._path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            text = "（日志文件尚未创建）"
        except OSError as exc:
            text = f"（读取日志失败：{exc}）"
        if len(text) > 80_000:
            text = "……（仅显示最近 80 KB）……\n" + text[-80_000:]
        if text == self._last_text:
            return
        self._last_text = text
        bar = self.text.verticalScrollBar()
        old_value = bar.value()
        at_bottom = old_value >= bar.maximum() - 4
        self.text.setPlainText(text)
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum() if at_bottom else min(old_value, bar.maximum()))


class SerialLogDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("串口日志（原始字节）")
        self.resize(1000, 600)
        self._shown = 0
        self._first_key: tuple[int, str, bytes] | None = None

        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(
            QLabel(
                "发送 TX / 接收 RX 的原始字节；\\n 表示换行，仅显示本次运行。",
                self,
            ),
            1,
        )
        self.follow_check = QCheckBox("刷新滚动", self)
        self.follow_check.setChecked(True)
        self.follow_check.setToolTip("关闭后冻结当前日志，方便查看")
        self.follow_check.toggled.connect(self._on_follow_changed)
        top.addWidget(self.follow_check)
        root.addLayout(top)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setFont(QFont("Consolas", 9))
        self.text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        root.addWidget(self.text, 1)
        row = QHBoxLayout()
        clear = QPushButton("清空显示", self)
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        row.addStretch(1)
        root.addLayout(row)

        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh(force=True)

    @staticmethod
    def _line(entry: SerialLogEntry) -> str:
        stamp = datetime.fromtimestamp(entry.at_ns / 1e9).strftime(
            "%H:%M:%S.%f"
        )[:-3]
        return (
            f"{stamp} {entry.direction} "
            f"[{len(entry.data):3d}] {entry.data!r}"
        )

    def _on_follow_changed(self, enabled: bool) -> None:
        if enabled:
            self._refresh(force=True)

    def _refresh(self, force: bool = False) -> None:
        if not self.follow_check.isChecked():
            return
        entries = serial_log.snapshot()
        first_key = (
            (entries[0].at_ns, entries[0].direction, entries[0].data)
            if entries
            else None
        )
        rebuild = force or (
            self._first_key is not None and first_key != self._first_key
        )
        if not rebuild and len(entries) == self._shown:
            return
        if rebuild:
            self.text.clear()
            self._shown = 0
        for entry in entries[self._shown :]:
            self.text.appendPlainText(self._line(entry))
        self._shown = len(entries)
        self._first_key = first_key
        bar = self.text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _clear(self) -> None:
        self.text.clear()
        entries = serial_log.snapshot()
        self._shown = len(entries)
        self._first_key = (
            (entries[0].at_ns, entries[0].direction, entries[0].data)
            if entries
            else None
        )


__all__ = ["SoftwareLogDialog", "SerialLogDialog"]
