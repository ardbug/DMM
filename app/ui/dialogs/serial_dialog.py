"""串口 / GPIB 连接设置对话框。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import SerialSettings
from app.ui.widgets.themed_combo import ThemedComboBox


class SerialDialog(QDialog):
    def __init__(
        self,
        settings: SerialSettings,
        serial_resource: str | None = None,
        gpib_resource: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("连接设置")
        self.setMinimumWidth(420)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setVerticalSpacing(8)

        self.interface = ThemedComboBox(self)
        self.interface.addItem("串口", "serial")
        self.interface.addItem("GPIB", "gpib")
        self._select(self.interface, settings.interface)
        form.addRow("接口", self.interface)

        self.resource = ThemedComboBox(self)
        self.resource.setEditable(True)
        serial_resource = serial_resource or (
            settings.resource if settings.interface == "serial" else "ASRL6::INSTR"
        )
        self.resource.addItem(serial_resource)
        for number in range(1, 33):
            item = f"ASRL{number}::INSTR"
            if self.resource.findText(item) < 0:
                self.resource.addItem(item)
        self.resource.setCurrentText(serial_resource)
        self.resource.setToolTip("COM10 对应 ASRL10::INSTR；也可直接输入")
        self.serial_resource_label = QLabel("串口资源", self)
        form.addRow(self.serial_resource_label, self.resource)

        self.gpib_resource = ThemedComboBox(self)
        self.gpib_resource.setEditable(True)
        gpib_resource = gpib_resource or (
            settings.resource if settings.interface == "gpib" else "gpib0,1"
        )
        self.gpib_resource.addItem(gpib_resource)
        for number in range(1, 33):
            item = f"gpib0,{number}"
            if self.gpib_resource.findText(item) < 0:
                self.gpib_resource.addItem(item)
        self.gpib_resource.setCurrentText(gpib_resource)
        self.gpib_resource.setToolTip("34401A 出厂 GPIB 地址通常为 1")
        self.gpib_resource_label = QLabel("GPIB 地址", self)
        form.addRow(self.gpib_resource_label, self.gpib_resource)

        self.baud = ThemedComboBox(self)
        for value in (300, 600, 1200, 2400, 4800, 9600):
            self.baud.addItem(str(value), value)
        self._select(self.baud, settings.baud_rate)
        self.serial_labels = []
        self.serial_widgets = []
        form.addRow("波特率", self.baud)
        self.serial_labels.append(form.labelForField(self.baud))
        self.serial_widgets.append(self.baud)

        self.data_bits = ThemedComboBox(self)
        for value in (7, 8):
            self.data_bits.addItem(f"{value} 位", value)
        self._select(self.data_bits, settings.data_bits)
        form.addRow("数据位", self.data_bits)
        self.serial_labels.append(form.labelForField(self.data_bits))
        self.serial_widgets.append(self.data_bits)

        self.parity = ThemedComboBox(self)
        for key, label in (
            ("none", "None（无）"),
            ("even", "Even（偶）"),
            ("odd", "Odd（奇）"),
        ):
            self.parity.addItem(label, key)
        self._select(self.parity, settings.parity)
        form.addRow("校验", self.parity)
        self.serial_labels.append(form.labelForField(self.parity))
        self.serial_widgets.append(self.parity)

        self.stop_bits = ThemedComboBox(self)
        for value in (1, 2):
            self.stop_bits.addItem(f"{value} 位", value)
        self._select(self.stop_bits, settings.stop_bits)
        form.addRow("停止位", self.stop_bits)
        self.serial_labels.append(form.labelForField(self.stop_bits))
        self.serial_widgets.append(self.stop_bits)

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
        self.serial_labels.append(form.labelForField(self.flow))
        self.serial_widgets.append(self.flow)

        self.serial_hint = QLabel(
            "34401A 串口默认 9600 / Even / 7 / 2", self
        )
        self.serial_hint.setObjectName("Muted")
        self.serial_hint.setWordWrap(True)
        form.addRow(self.serial_hint)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.interface.currentIndexChanged.connect(self._sync_mode)
        self._sync_mode()

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _sync_mode(self) -> None:
        gpib = self.interface.currentData() == "gpib"
        self.serial_resource_label.setVisible(not gpib)
        self.resource.setVisible(not gpib)
        self.gpib_resource_label.setVisible(gpib)
        self.gpib_resource.setVisible(gpib)
        self.serial_hint.setVisible(not gpib)
        for label in self.serial_labels:
            if label is not None:
                label.setVisible(not gpib)
        for widget in self.serial_widgets:
            widget.setVisible(not gpib)

    def settings(self) -> SerialSettings:
        interface = str(self.interface.currentData())
        resource = (
            self.gpib_resource.currentText().strip()
            if interface == "gpib"
            else self.resource.currentText().strip()
        )
        return SerialSettings(
            resource=resource,
            baud_rate=int(self.baud.currentData()),
            data_bits=int(self.data_bits.currentData()),
            parity=str(self.parity.currentData()),
            stop_bits=int(self.stop_bits.currentData()),
            flow_control=str(self.flow.currentData()),
            timeout_ms=2000,
            interface=interface,
        )
