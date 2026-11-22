"""串口设置对话框。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import SerialSettings
from app.ui.widgets.themed_combo import ThemedComboBox


class SerialDialog(QDialog):
    def __init__(
        self,
        settings: SerialSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("串口设置")
        self.setMinimumWidth(380)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(8)

        self.resource = ThemedComboBox(self)
        self.resource.setEditable(True)
        self.resource.addItem(settings.resource)
        for number in range(1, 33):
            item = f"ASRL{number}::INSTR"
            if self.resource.findText(item) < 0:
                self.resource.addItem(item)
        self.resource.setCurrentText(settings.resource)
        self.resource.setToolTip("COM10 对应 ASRL10::INSTR；也可直接输入")
        form.addRow("串口资源", self.resource)

        self.baud = ThemedComboBox(self)
        for value in (300, 600, 1200, 2400, 4800, 9600):
            self.baud.addItem(str(value), value)
        self._select(self.baud, settings.baud_rate)
        form.addRow("波特率", self.baud)

        self.data_bits = ThemedComboBox(self)
        for value in (7, 8):
            self.data_bits.addItem(f"{value} 位", value)
        self._select(self.data_bits, settings.data_bits)
        form.addRow("数据位", self.data_bits)

        self.parity = ThemedComboBox(self)
        for key, label in (
            ("none", "None（无）"),
            ("even", "Even（偶）"),
            ("odd", "Odd（奇）"),
        ):
            self.parity.addItem(label, key)
        self._select(self.parity, settings.parity)
        form.addRow("校验", self.parity)

        self.stop_bits = ThemedComboBox(self)
        for value in (1, 2):
            self.stop_bits.addItem(f"{value} 位", value)
        self._select(self.stop_bits, settings.stop_bits)
        form.addRow("停止位", self.stop_bits)

        self.flow = ThemedComboBox(self)
        for key, label in (
            ("none", "None（无）"),
            ("dtr_dsr", "DTR/DSR"),
            ("rts_cts", "RTS/CTS"),
            ("xon_xoff", "XON/XOFF"),
        ):
            self.flow.addItem(label, key)
        self._select(self.flow, settings.flow_control)
        form.addRow("流控", self.flow)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def settings(self) -> SerialSettings:
        return SerialSettings(
            resource=self.resource.currentText().strip(),
            baud_rate=int(self.baud.currentData()),
            data_bits=int(self.data_bits.currentData()),
            parity=str(self.parity.currentData()),
            stop_bits=int(self.stop_bits.currentData()),
            flow_control=str(self.flow.currentData()),
            timeout_ms=2000,
        )
