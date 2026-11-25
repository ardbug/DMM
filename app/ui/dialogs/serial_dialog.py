"""串口 / GPIB 连接设置对话框。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QSpinBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import SerialSettings
from app.transport.serial_ports import list_serial_ports
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
            settings.resource if settings.interface == "serial" else "COM6"
        )
        self.resource_row = QWidget(self)
        resource_layout = QHBoxLayout(self.resource_row)
        resource_layout.setContentsMargins(0, 0, 0, 0)
        resource_layout.setSpacing(4)
        resource_layout.addWidget(self.resource, 1)
        self.refresh_btn = QPushButton("扫描", self)
        self.refresh_btn.setFixedWidth(52)
        self.refresh_btn.setToolTip("重新扫描当前可用的串口")
        self.refresh_btn.clicked.connect(self._populate_serial_ports)
        resource_layout.addWidget(self.refresh_btn)
        self._populate_serial_ports(serial_resource)
        self.resource.setToolTip("可扫描选择 COM 口，也可直接输入")
        self.serial_resource_label = QLabel("串口资源", self)
        form.addRow(self.serial_resource_label, self.resource_row)

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

        self.timeout = QSpinBox(self)
        self.timeout.setRange(500, 120000)
        self.timeout.setSingleStep(500)
        self.timeout.setSuffix(" ms")
        self.timeout.setValue(max(500, min(120000, settings.timeout_ms)))
        self.timeout.setToolTip("单次 I/O 读取/写入的最长等待时间")
        form.addRow("超时", self.timeout)

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
    def _com_resource(value: str) -> str:
        text = value.strip().upper()
        if text.startswith("ASRL"):
            number = text.removeprefix("ASRL").split("::", 1)[0]
            if number.isdigit():
                return f"COM{number}"
        return text

    def _populate_serial_ports(self, selected: str | None = None) -> None:
        current = selected or self._resource_value()
        current_com = self._com_resource(current)
        self.resource.blockSignals(True)
        self.resource.clear()
        ports = list_serial_ports()
        for port in ports:
            label = port.device
            if port.description:
                label += f"    {port.description}"
            self.resource.addItem(label, port.device)
        index = self.resource.findData(current_com)
        if index >= 0:
            self.resource.setCurrentIndex(index)
        elif current:
            self.resource.addItem(current, current)
            self.resource.setCurrentIndex(self.resource.count() - 1)
        self.resource.blockSignals(False)

    def _resource_value(self) -> str:
        text = self.resource.currentText().strip()
        data = self.resource.currentData()
        index = self.resource.currentIndex()
        if (
            data
            and index >= 0
            and text == self.resource.itemText(index).strip()
        ):
            return str(data)
        return text

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _sync_mode(self) -> None:
        gpib = self.interface.currentData() == "gpib"
        self.serial_resource_label.setVisible(not gpib)
        self.resource_row.setVisible(not gpib)
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
            else self._resource_value()
        )
        return SerialSettings(
            resource=resource,
            baud_rate=int(self.baud.currentData()),
            data_bits=int(self.data_bits.currentData()),
            parity=str(self.parity.currentData()),
            stop_bits=int(self.stop_bits.currentData()),
            flow_control=str(self.flow.currentData()),
            timeout_ms=int(self.timeout.value()),
            interface=interface,
        )
