"""34970A 连接面板和右侧 DMM 参数面板。"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.domain.models import SerialSettings
from app.instrument.daq34970a import DaqConfig
from app.ui.dialogs.serial_dialog import SerialDialog
from app.ui.widgets.themed_combo import ThemedComboBox

_FUNCTIONS = (
    ("DCV", "VOLT:DC"),
    ("ACV", "VOLT:AC"),
    ("2WΩ", "RES"),
    ("4WΩ", "FRES"),
    ("DCI", "CURR:DC"),
    ("ACI", "CURR:AC"),
    ("频率", "FREQ"),
    ("周期", "PER"),
    ("温度", "TEMP"),
)

_TEMPS = (
    ("K 型热电偶", "TC:K"),
    ("PT100 2W", "RTD:2W:100"),
    ("PT1000 2W", "RTD:2W:1000"),
    ("PT100 4W", "RTD:4W:100"),
    ("PT1000 4W", "RTD:4W:1000"),
    ("热敏电阻 5k", "THERM:5000"),
)


class DaqConnectionPanel(QFrame):
    open_requested = Signal(object)
    close_requested = Signal()
    csv_toggle_requested = Signal()
    open_csv_folder_requested = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LeftPanel")
        self.setMinimumWidth(235)
        self.setMaximumWidth(300)
        self._config = config
        self._state = "disconnected"
        if config.has_connection_settings():
            self._settings = replace(
                config.serial_settings(), timeout_ms=5000
            )
        else:
            self._settings = SerialSettings(
                resource="gpib0,9",
                timeout_ms=5000,
                interface="gpib",
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(8)
        title = QLabel("34970A", self)
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        self.interface = ThemedComboBox(self)
        self.interface.addItem("GPIB", "gpib")
        self.interface.addItem("串口", "serial")
        self.interface.setCurrentIndex(
            self.interface.findData(self._settings.interface)
        )
        root.addWidget(QLabel("接口", self))
        root.addWidget(self.interface)

        self.resource = ThemedComboBox(self)
        self.resource.setEditable(True)
        self.resource.addItem(self._settings.resource)
        self.resource.setCurrentText(self._settings.resource)
        self.resource_label = QLabel("GPIB 地址", self)
        root.addWidget(self.resource_label)
        root.addWidget(self.resource)

        self.settings_btn = QPushButton("连接设置…", self)
        self.settings_btn.clicked.connect(self._edit_settings)
        root.addWidget(self.settings_btn)

        buttons = QHBoxLayout()
        self.open_btn = QPushButton("打开连接", self)
        self.open_btn.setObjectName("PrimaryButton")
        self.open_btn.clicked.connect(self._emit_open)
        self.close_btn = QPushButton("关闭", self)
        self.close_btn.clicked.connect(self.close_requested)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.close_btn)
        root.addLayout(buttons)

        root.addWidget(QLabel("数据记录", self))
        csv_row = QHBoxLayout()
        self.csv_btn = QPushButton("开始记录 CSV", self)
        self.csv_btn.clicked.connect(self.csv_toggle_requested)
        self.csv_folder_btn = QPushButton("文件夹", self)
        self.csv_folder_btn.clicked.connect(self.open_csv_folder_requested)
        csv_row.addWidget(self.csv_btn)
        csv_row.addWidget(self.csv_folder_btn)
        root.addLayout(csv_row)
        self.csv_label = QLabel("未记录", self)
        self.csv_label.setObjectName("Muted")
        self.csv_label.setWordWrap(True)
        root.addWidget(self.csv_label)
        self.status = QLabel("未连接", self)
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        root.addStretch(1)

        self.interface.currentIndexChanged.connect(self._sync_interface)
        self._sync_interface()
        self.set_state("disconnected", "34970A 未连接")

    def _sync_interface(self) -> None:
        self.resource_label.setText(
            "GPIB 地址"
            if self.interface.currentData() == "gpib"
            else "串口资源"
        )

    def _emit_open(self) -> None:
        self.open_requested.emit(self.settings())

    def settings(self) -> SerialSettings:
        return replace(
            self._settings,
            resource=self.resource.currentText().strip() or "gpib0,9",
            interface=str(self.interface.currentData()),
            timeout_ms=5000,
        )

    def _edit_settings(self) -> None:
        dialog = SerialDialog(
            self.settings(),
            serial_resource=self._config.serial_resource(),
            gpib_resource=self.resource.currentText().strip() or "gpib0,9",
            parent=self,
        )
        if not dialog.exec():
            return
        self._settings = dialog.settings()
        self.interface.setCurrentIndex(
            self.interface.findData(self._settings.interface)
        )
        self.resource.setCurrentText(self._settings.resource)

    def set_state(self, state: str, detail: str = "") -> None:
        self._state = state
        connected = state in {"ready", "acquiring", "stopping"}
        self.interface.setEnabled(state in {"disconnected", "error"})
        self.resource.setEnabled(state in {"disconnected", "error"})
        self.settings_btn.setEnabled(state in {"disconnected", "error"})
        self.open_btn.setEnabled(state in {"disconnected", "error"})
        self.close_btn.setEnabled(connected)
        if detail:
            self.status.setText(detail)

    def set_csv_state(self, recording: bool, path: str = "") -> None:
        self.csv_btn.setText("停止记录 CSV" if recording else "开始记录 CSV")
        self.csv_label.setText(path or "未记录")


class DaqParamsPanel(QFrame):
    config_changed = Signal()
    start_requested = Signal(object)
    stop_requested = Signal()
    single_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LeftPanel")
        self.setMinimumWidth(255)
        self.setMaximumWidth(330)
        self._state = "disconnected"

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(8)
        title = QLabel("DMM 参数", self)
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(6)
        self.channel = QSpinBox(self)
        self.channel.setRange(101, 122)
        self.channel.setValue(101)
        self.scan_check = QCheckBox("多通道扫描", self)
        self.scan_list = QLineEdit("101:110", self)
        self.scan_list.setPlaceholderText("例如 101:110,121")
        self.function = ThemedComboBox(self)
        for label, value in _FUNCTIONS:
            self.function.addItem(label, value)
        self.temp_sensor = ThemedComboBox(self)
        for label, value in _TEMPS:
            self.temp_sensor.addItem(label, value)
        self.temp_unit = ThemedComboBox(self)
        for label, value in (("°C", "C"), ("°F", "F"), ("K", "K")):
            self.temp_unit.addItem(label, value)
        self.nplc = ThemedComboBox(self)
        for value in (0.02, 0.2, 1, 10, 100):
            self.nplc.addItem(f"{value:g}", value)
        self.nplc.setCurrentIndex(self.nplc.findData(1.0))
        self.rate = QDoubleSpinBox(self)
        self.rate.setRange(0.1, 20.0)
        self.rate.setDecimals(1)
        self.rate.setValue(1.0)
        self.rate.setSuffix(" Hz")
        self.scan_rate = QDoubleSpinBox(self)
        self.scan_rate.setRange(0.1, 20.0)
        self.scan_rate.setDecimals(2)
        self.scan_rate.setValue(1.0)
        self.scan_rate.setSuffix(" Hz")
        self.scan_rate.setToolTip("每轮扫描的间隔，1 Hz 表示每秒扫描一次")

        form.addRow("通道", self.channel)
        form.addRow("", self.scan_check)
        form.addRow("扫描列表", self.scan_list)
        self._scan_label = form.labelForField(self.scan_list)
        form.addRow("功能", self.function)
        form.addRow("传感器", self.temp_sensor)
        self._temp_sensor_label = form.labelForField(self.temp_sensor)
        form.addRow("温度单位", self.temp_unit)
        self._temp_unit_label = form.labelForField(self.temp_unit)
        form.addRow("NPLC", self.nplc)
        form.addRow("读取速率", self.rate)
        self._rate_label = form.labelForField(self.rate)
        form.addRow("扫描速率", self.scan_rate)
        self._scan_rate_label = form.labelForField(self.scan_rate)
        root.addLayout(form)

        actions = QHBoxLayout()
        self.start_btn = QPushButton("开始连续读取", self)
        self.start_btn.setObjectName("StartButton")
        self.start_btn.clicked.connect(self._emit_start)
        self.single_btn = QPushButton("单次", self)
        self.single_btn.clicked.connect(self._emit_single)
        actions.addWidget(self.start_btn)
        actions.addWidget(self.single_btn)
        root.addLayout(actions)
        root.addStretch(1)

        self.channel.valueChanged.connect(self._sync_channel)
        self.scan_check.toggled.connect(self._sync_scan)
        self.function.currentIndexChanged.connect(self._sync_function)
        self.scan_list.textChanged.connect(self.config_changed)
        self.function.currentIndexChanged.connect(self.config_changed)
        self.temp_sensor.currentIndexChanged.connect(self.config_changed)
        self.temp_unit.currentIndexChanged.connect(self.config_changed)
        self.nplc.currentIndexChanged.connect(self.config_changed)
        self.rate.valueChanged.connect(self.config_changed)
        self.scan_rate.valueChanged.connect(self.config_changed)
        self.channel.valueChanged.connect(self.config_changed)
        self.scan_check.toggled.connect(self.config_changed)
        self._sync_scan()
        self._sync_function()
        self._sync_channel()

    def _sync_scan(self) -> None:
        scan = self.scan_check.isChecked()
        self.channel.setEnabled(not scan)
        self.scan_list.setVisible(scan)
        self._scan_label.setVisible(scan)
        self.rate.setVisible(not scan)
        self._rate_label.setVisible(not scan)
        self._scan_rate_label.setVisible(scan)
        self.scan_rate.setVisible(scan)

    def _sync_function(self) -> None:
        temp = self.function.currentData() == "TEMP"
        self.temp_sensor.setVisible(temp)
        self.temp_unit.setVisible(temp)
        self._temp_sensor_label.setVisible(temp)
        self._temp_unit_label.setVisible(temp)

    def _sync_channel(self) -> None:
        if self.scan_check.isChecked():
            return
        current_only = self.channel.value() >= 121
        for index in range(self.function.count()):
            value = self.function.itemData(index)
            allowed = (value in {"CURR:DC", "CURR:AC"}) if current_only else True
            self.function.model().item(index).setEnabled(allowed)
        if current_only and self.function.currentData() not in {
            "CURR:DC",
            "CURR:AC",
        }:
            self.function.setCurrentIndex(self.function.findData("CURR:DC"))
        elif not current_only and self.function.currentData() in {
            "CURR:DC",
            "CURR:AC",
        }:
            self.function.setCurrentIndex(self.function.findData("VOLT:DC"))

    def config(self) -> DaqConfig:
        channel = int(self.channel.value())
        function = str(self.function.currentData())
        if not self.scan_check.isChecked() and channel in {121, 122}:
            if function not in {"CURR:DC", "CURR:AC"}:
                function = "CURR:DC"
        return DaqConfig(
            channel=channel,
            function=function,
            nplc=float(self.nplc.currentData()),
            temperature=str(self.temp_sensor.currentData()),
            temp_unit=str(self.temp_unit.currentData()),
            rate=float(self.rate.value()),
            scan=self.scan_check.isChecked(),
            scan_list=self.scan_list.text().strip(),
            scan_rate=float(self.scan_rate.value()),
        )

    def _emit_start(self) -> None:
        self.start_requested.emit(self.config())

    def _emit_single(self) -> None:
        self.single_requested.emit(self.config())

    def set_state(self, state: str) -> None:
        self._state = state
        self.start_btn.setEnabled(state in {"ready", "acquiring"})
        self.single_btn.setEnabled(state == "ready")
        self.start_btn.setText(
            "停止" if state == "acquiring" else "开始连续读取"
        )


# Backwards-compatible name used by older tests/imports.
DaqPanel = DaqConnectionPanel
