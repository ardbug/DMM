"""左栏：串口/通信/连接。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.domain.models import SerialSettings
from app.storage.csv_writer import default_csv_dir
from app.ui.widgets.themed_combo import ThemedComboBox


class ConnectionPanel(QFrame):
    open_requested = Signal(object)
    close_requested = Signal()
    refresh_requested = Signal()
    identify_requested = Signal()
    errors_requested = Signal()
    csv_toggle_requested = Signal()
    open_csv_folder_requested = Signal()
    collapse_requested = Signal()

    def __init__(
        self,
        config: AppConfig,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setMinimumWidth(210)
        self.setMaximumWidth(290)
        self._config = config
        self._state = "disconnected"
        self._initial_settings = config.serial_settings()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("连接与通信", self)
        title.setObjectName("SectionTitle")
        self.collapse_btn = QToolButton(self)
        self.collapse_btn.setText("◀")
        self.collapse_btn.setToolTip("折叠左侧工具栏")
        self.collapse_btn.clicked.connect(self.collapse_requested)
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.collapse_btn)
        root.addLayout(title_row)

        interface_row = QHBoxLayout()
        interface_row.setSpacing(6)
        interface_label = QLabel("接口", self)
        self.interface = ThemedComboBox(self)
        self.interface.addItem("串口", "serial")
        self.interface.addItem("GPIB", "gpib")
        self._select_data(self.interface, self._initial_settings.interface)
        interface_row.addWidget(interface_label)
        interface_row.addWidget(self.interface, 1)
        root.addLayout(interface_row)

        resource_row = QHBoxLayout()
        resource_row.setSpacing(4)
        self.resource_combo = ThemedComboBox(self)
        self.resource_combo.setEditable(True)
        self.resource_combo.setMinimumWidth(130)
        self.resource_combo.addItem(self._initial_settings.resource)
        self.resource_combo.lineEdit().setPlaceholderText("ASRL6::INSTR")
        resource_row.addWidget(self.resource_combo, 1)
        self.refresh_btn = QPushButton("刷新", self)
        self.refresh_btn.setFixedWidth(52)
        self.refresh_btn.clicked.connect(self.refresh_requested)
        resource_row.addWidget(self.refresh_btn)
        self.resource_label = QLabel("串口资源", self)
        root.addWidget(self.resource_label)
        root.addLayout(resource_row)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.baud = ThemedComboBox(self)
        for value in (300, 600, 1200, 2400, 4800, 9600):
            self.baud.addItem(str(value), value)
        self._select_data(self.baud, config.serial_settings().baud_rate)

        self.data_bits = ThemedComboBox(self)
        for value in (7, 8):
            self.data_bits.addItem(f"{value} 位", value)
        self._select_data(self.data_bits, config.serial_settings().data_bits)

        self.parity = ThemedComboBox(self)
        for label, value in (("Even（偶）", "even"), ("None（无）", "none"), ("Odd（奇）", "odd")):
            self.parity.addItem(label, value)
        self._select_data(self.parity, config.serial_settings().parity)

        self.stop_bits = ThemedComboBox(self)
        for value in (2, 1):
            self.stop_bits.addItem(f"{value} 位", value)
        self._select_data(self.stop_bits, config.serial_settings().stop_bits)

        self.flow = ThemedComboBox(self)
        for label, value in (
            ("DTR/DSR", "dtr_dsr"),
            ("无", "none"),
            ("RTS/CTS", "rts_cts"),
        ):
            self.flow.addItem(label, value)
        self._select_data(self.flow, config.serial_settings().flow_control)

        form.addRow("波特率", self.baud)
        form.addRow("数据位", self.data_bits)
        form.addRow("校验", self.parity)
        form.addRow("停止位", self.stop_bits)
        form.addRow("流控", self.flow)
        root.addLayout(form)

        hint = QLabel("34401A 默认 9600 / Even / 7 / 2", self)
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self.serial_hint = hint
        root.addWidget(hint)

        button_row = QHBoxLayout()
        self.open_btn = QPushButton("打开连接", self)
        self.open_btn.setObjectName("PrimaryButton")
        self.open_btn.clicked.connect(self._emit_open)
        self.close_btn = QPushButton("关闭（回本地）", self)
        self.close_btn.clicked.connect(self.close_requested)
        button_row.addWidget(self.open_btn)
        button_row.addWidget(self.close_btn)
        root.addLayout(button_row)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(line)

        self.identify_btn = QPushButton("*IDN?  读取身份", self)
        self.identify_btn.clicked.connect(self.identify_requested)
        root.addWidget(self.identify_btn)

        self.errors_btn = QPushButton("读取错误队列", self)
        self.errors_btn.clicked.connect(self.errors_requested)
        root.addWidget(self.errors_btn)

        record_title = QLabel("数据记录", self)
        record_title.setObjectName("SectionTitle")
        root.addWidget(record_title)
        self.csv_btn = QPushButton("开始记录 CSV", self)
        self.csv_btn.clicked.connect(self.csv_toggle_requested)
        root.addWidget(self.csv_btn)
        self.open_csv_folder_btn = QPushButton("打开 CSV 文件夹", self)
        self.open_csv_folder_btn.setToolTip(str(default_csv_dir()))
        self.open_csv_folder_btn.clicked.connect(self.open_csv_folder_requested)
        root.addWidget(self.open_csv_folder_btn)

        self.csv_path_label = QLabel("未记录", self)
        self.csv_path_label.setObjectName("Muted")
        self.csv_path_label.setWordWrap(True)
        root.addWidget(self.csv_path_label)

        self.status_label = QLabel("未连接", self)
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        root.addStretch(1)

        self._serial_fields = [
            self.baud,
            self.data_bits,
            self.parity,
            self.stop_bits,
            self.flow,
        ]
        self._serial_labels = [
            form.labelForField(widget) for widget in self._serial_fields
        ]
        self.interface.currentIndexChanged.connect(
            self._on_interface_changed
        )
        self._sync_interface()
        self.set_state("disconnected", "未连接")

    def _sync_interface(self) -> None:
        gpib = self.interface.currentData() == "gpib"
        self.resource_combo.setCurrentText(
            self._config.gpib_resource()
            if gpib
            else self._config.serial_resource()
        )
        self.resource_combo.lineEdit().setPlaceholderText(
            "gpib0,1" if gpib else "ASRL6::INSTR"
        )
        self.resource_label.setText("GPIB 地址" if gpib else "串口资源")
        self.refresh_btn.setVisible(not gpib)
        for label in self._serial_labels:
            if label is not None:
                label.setVisible(not gpib)
        for widget in self._serial_fields:
            widget.setVisible(not gpib)
        self.serial_hint.setVisible(not gpib)
        if gpib:
            self.serial_hint.setToolTip(
                "GPIB 使用 Keysight SICL 地址，例如 gpib0,1"
            )
        self.open_btn.setText("连接 GPIB" if gpib else "打开串口")

    def _on_interface_changed(self) -> None:
        self._sync_interface()
        self.status_label.setText(
            "GPIB 地址例如 gpib0,1；34401A 出厂地址通常为 1"
            if self.interface.currentData() == "gpib"
            else "请选择或填写串口资源"
        )

    def _emit_open(self) -> None:
        try:
            settings = self.serial_settings()
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return
        self.open_requested.emit(settings)

    def serial_settings(self) -> SerialSettings:
        resource = self.resource_combo.currentText().strip()
        interface = str(self.interface.currentData())
        if not resource:
            if interface == "gpib":
                raise ValueError("请填写 GPIB 地址，例如 gpib0,1")
            raise ValueError("请填写串口资源，例如 ASRL6::INSTR")
        return SerialSettings(
            resource=resource,
            baud_rate=int(self.baud.currentData()),
            data_bits=int(self.data_bits.currentData()),
            parity=str(self.parity.currentData()),
            stop_bits=int(self.stop_bits.currentData()),
            flow_control=str(self.flow.currentData()),
            interface=interface,
        )

    def populate_resources(self, resources: list[str]) -> None:
        current = self.resource_combo.currentText().strip()
        changed = False
        self.resource_combo.blockSignals(True)
        self.resource_combo.clear()
        for item in resources:
            self.resource_combo.addItem(item)
        if resources:
            selected = current if current in resources else resources[0]
            if selected != current:
                changed = True
            self.resource_combo.setCurrentIndex(
                max(0, self.resource_combo.findText(selected))
            )
        elif current:
            self.resource_combo.addItem(current)
        self.resource_combo.blockSignals(False)
        if changed:
            self.status_label.setText(f"原端口不可用，已选择 {selected}")
        elif not resources:
            self.status_label.setText("未发现串口资源，可手动填写")

    def set_state(self, state: str, detail: str) -> None:
        self._state = state
        editable = state in {"disconnected", "error"}
        self.interface.setEnabled(editable)
        self.resource_combo.setEnabled(editable)
        for widget in self._serial_fields:
            widget.setEnabled(editable)
        self.refresh_btn.setEnabled(editable)
        self.open_btn.setEnabled(editable)
        self.close_btn.setEnabled(state in {"ready", "reading"})
        self.identify_btn.setEnabled(state == "ready")
        self.errors_btn.setEnabled(state == "ready")
        self.csv_btn.setEnabled(state in {"ready", "acquiring"})

        colors = {
            "disconnected": "未连接",
            "opening": "正在打开…",
            "ready": "已连接（远程）",
            "reading": "正在读数…",
            "acquiring": "采集中",
            "stopping": "正在停止…",
            "closing": "正在关闭…",
            "error": "通信错误",
        }
        self.status_label.setText(f"{colors.get(state, state)}　{detail}".strip())
        self.open_btn.setText(
            "连接 GPIB"
            if self.interface.currentData() == "gpib"
            else "打开串口"
        )

    def set_csv_state(self, recording: bool, path: str = "") -> None:
        self.csv_btn.setText("结束记录 CSV" if recording else "开始记录 CSV")
        if recording:
            name = Path(path).name if path else "记录中…"
            self.csv_path_label.setText(name)
            self.csv_path_label.setToolTip(path)
        else:
            self.csv_path_label.setText("未记录")
            self.csv_path_label.setToolTip("")

    def _select_data(self, combo: QComboBox, value: object) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)
