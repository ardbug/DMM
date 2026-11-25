"""34970A 连接面板和右侧 DMM 参数面板。"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.domain.models import SerialSettings
from app.instrument.daq34970a import DaqConfig, parse_channels
from app.instrument.daq_modules import ScanChannelConfig
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
            self._settings = config.serial_settings()
        else:
            self._settings = SerialSettings(
                resource="gpib0,9",
                baud_rate=57600,
                data_bits=8,
                parity="none",
                stop_bits=1,
                flow_control="xon_xoff",
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
        self.connection_box = QWidget(self)
        connection_layout = QVBoxLayout(self.connection_box)
        connection_layout.setContentsMargins(0, 0, 0, 0)
        connection_layout.setSpacing(6)
        connection_layout.addWidget(QLabel("接口", self))
        connection_layout.addWidget(self.interface)

        self.resource = ThemedComboBox(self)
        self.resource.setEditable(True)
        self.resource.addItem(self._settings.resource)
        self.resource.setCurrentText(self._settings.resource)
        self.resource_label = QLabel("GPIB 地址", self)
        connection_layout.addWidget(self.resource_label)
        connection_layout.addWidget(self.resource)

        self.settings_btn = QPushButton("连接设置…", self)
        self.settings_btn.clicked.connect(self._edit_settings)
        connection_layout.addWidget(self.settings_btn)

        buttons = QHBoxLayout()
        self.open_btn = QPushButton("打开连接", self)
        self.open_btn.setObjectName("PrimaryButton")
        self.open_btn.clicked.connect(self._emit_open)
        self.close_btn = QPushButton("关闭", self)
        self.close_btn.clicked.connect(self.close_requested)
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.close_btn)
        connection_layout.addLayout(buttons)
        root.addWidget(self.connection_box)

        root.addWidget(QLabel("模块信息", self))
        self.slot_table = QTableWidget(3, 3, self)
        self.slot_table.setHorizontalHeaderLabels(
            ["槽位", "模块", "通道"]
        )
        self.slot_table.verticalHeader().setVisible(False)
        self.slot_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        slot_header = self.slot_table.horizontalHeader()
        slot_header.setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        slot_header.setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        slot_header.setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.slot_table.setMaximumHeight(112)
        for row, slot in enumerate((100, 200, 300)):
            self.slot_table.setItem(
                row, 0, QTableWidgetItem(f"Slot {slot}")
            )
            self.slot_table.setItem(
                row, 1, QTableWidgetItem("未读取")
            )
            self.slot_table.setItem(row, 2, QTableWidgetItem("—"))
        root.addWidget(self.slot_table)

        root.addWidget(QLabel("数据记录", self))
        csv_row = QHBoxLayout()
        self.csv_btn = QPushButton("开始记录 CSV", self)
        self.csv_btn.setObjectName("RecordButton")
        self.csv_btn.setCheckable(True)
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
        gpib = self.interface.currentData() == "gpib"
        self.resource_label.setText("GPIB 地址" if gpib else "串口资源")
        text = self.resource.currentText().strip().upper()
        if gpib and not text.startswith(("GPIB", "GPIB0")):
            self.resource.setCurrentText("gpib0,9")
        elif not gpib and text.startswith(("GPIB", "GPIB0")):
            self.resource.setCurrentText("COM6")

    def _emit_open(self) -> None:
        self.open_requested.emit(self.settings())

    def settings(self) -> SerialSettings:
        return replace(
            self._settings,
            resource=self.resource.currentText().strip() or "gpib0,9",
            interface=str(self.interface.currentData()),
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
        self.connection_box.setVisible(not connected)
        self.interface.setEnabled(state in {"disconnected", "error"})
        self.resource.setEnabled(state in {"disconnected", "error"})
        self.settings_btn.setEnabled(state in {"disconnected", "error"})
        self.open_btn.setEnabled(state in {"disconnected", "error"})
        self.close_btn.setEnabled(
            state in {"opening", "ready", "acquiring", "stopping"}
        )
        if detail:
            self.status.setText(detail)

    def set_slots(self, slots) -> None:
        by_slot = {item.slot: item for item in slots}
        for row, slot in enumerate((100, 200, 300)):
            info = by_slot.get(slot)
            self.slot_table.item(row, 1).setText(
                info.label if info is not None else "Empty"
            )
            self.slot_table.item(row, 2).setText(
                info.channel_text if info is not None else "—"
            )

    def set_csv_state(self, recording: bool, path: str = "") -> None:
        self.csv_btn.setChecked(recording)
        self.csv_btn.setText("停止记录 CSV" if recording else "开始记录 CSV")
        self.csv_label.setText(path or "未记录")


class DaqParamsPanel(QFrame):
    config_changed = Signal()

    def __init__(
        self,
        config: AppConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self.setObjectName("LeftPanel")
        self.setMinimumWidth(255)
        self.setMaximumWidth(330)
        self._state = "disconnected"
        self._current_channels = {121, 122}
        self._available_channels = tuple(range(101, 123))
        self._scan_specs: dict[int, ScanChannelConfig] = {
            channel: ScanChannelConfig(channel)
            for channel in self._available_channels
        }
        self._saved_enabled: set[int] | None = None
        self._saved_channel = 101
        self._loading = False
        self._selection_channel: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(7)
        title = QLabel("DMM 参数", self)
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        form = QFormLayout()
        form.setSpacing(6)
        self.channel = QSpinBox(self)
        self.channel.setRange(101, 399)
        self.channel.setValue(101)
        self.scan_check = QCheckBox("多通道扫描", self)
        form.addRow("通道", self.channel)
        form.addRow("", self.scan_check)

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
        form.addRow("功能", self.function)
        self._function_label = form.labelForField(self.function)
        form.addRow("传感器", self.temp_sensor)
        self._temp_sensor_label = form.labelForField(self.temp_sensor)
        form.addRow("温度单位", self.temp_unit)
        self._temp_unit_label = form.labelForField(self.temp_unit)
        form.addRow("NPLC", self.nplc)
        self._nplc_label = form.labelForField(self.nplc)
        form.addRow("读取速率", self.rate)
        self._rate_label = form.labelForField(self.rate)
        root.addLayout(form)

        self.scan_group = QGroupBox("扫描通道", self)
        scan_layout = QVBoxLayout(self.scan_group)
        scan_layout.setContentsMargins(6, 8, 6, 6)
        self.scan_table = QTableWidget(0, 4, self.scan_group)
        self.scan_table.setHorizontalHeaderLabels(
            ["开关", "通道", "功能", "扫描次数"]
        )
        header = self.scan_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.scan_table.setSelectionMode(
            QTableWidget.SelectionMode.ExtendedSelection
        )
        self.scan_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.scan_table.setMinimumHeight(180)
        scan_layout.addWidget(self.scan_table, 1)
        buttons = QHBoxLayout()
        self.scan_all_btn = QPushButton("全选", self.scan_group)
        self.scan_none_btn = QPushButton("清空", self.scan_group)
        self.scan_all_btn.clicked.connect(lambda: self._set_all_scan(True))
        self.scan_none_btn.clicked.connect(lambda: self._set_all_scan(False))
        buttons.addWidget(self.scan_all_btn)
        buttons.addWidget(self.scan_none_btn)
        scan_layout.addLayout(buttons)
        root.addWidget(self.scan_group, 1)

        self.scan_config = QGroupBox("选中通道配置", self)
        scan_config_form = QFormLayout(self.scan_config)
        scan_config_form.setSpacing(5)
        self.scan_function = ThemedComboBox(self.scan_config)
        for label, value in _FUNCTIONS:
            self.scan_function.addItem(label, value)
        self.scan_nplc = ThemedComboBox(self.scan_config)
        for value in (0.02, 0.2, 1, 10, 100):
            self.scan_nplc.addItem(f"{value:g}", value)
        self.scan_nplc.setCurrentIndex(self.scan_nplc.findData(1.0))
        self.min_scan_seconds = QDoubleSpinBox(self.scan_config)
        self.min_scan_seconds.setRange(0.0, 3600.0)
        self.min_scan_seconds.setDecimals(3)
        self.min_scan_seconds.setSuffix(" s")
        self.min_scan_seconds.setToolTip(
            "每次扫描至少占用这么长时间，扫描更快时补足等待"
        )
        self.scan_count = QSpinBox(self.scan_config)
        self.scan_count.setRange(1, 50000)
        self.scan_count.setValue(1)
        self.scan_count.setSuffix(" 次")
        self.scan_count.setToolTip("选中通道的扫描次数设置")
        self.pre_scan_wait = QDoubleSpinBox(self.scan_config)
        self.pre_scan_wait.setRange(0.0, 3600.0)
        self.pre_scan_wait.setDecimals(3)
        self.pre_scan_wait.setSuffix(" s")
        self.post_scan_wait = QDoubleSpinBox(self.scan_config)
        self.post_scan_wait.setRange(0.0, 3600.0)
        self.post_scan_wait.setDecimals(3)
        self.post_scan_wait.setSuffix(" s")
        scan_config_form.addRow("功能", self.scan_function)
        scan_config_form.addRow("NPLC", self.scan_nplc)
        scan_config_form.addRow("最小每次扫描时长", self.min_scan_seconds)
        scan_config_form.addRow("每通道扫描次数", self.scan_count)
        scan_config_form.addRow("扫描前等待", self.pre_scan_wait)
        scan_config_form.addRow("扫描后等待", self.post_scan_wait)
        root.addWidget(self.scan_config)

        root.addStretch(0)

        self._load_saved_parameters()
        self._rebuild_table(self._available_channels)
        self.channel.valueChanged.connect(self._sync_channel)
        self.scan_check.toggled.connect(self._sync_scan)
        self.function.currentIndexChanged.connect(self._sync_function)
        self.function.currentIndexChanged.connect(self._persist_parameters)
        self.temp_sensor.currentIndexChanged.connect(self._persist_parameters)
        self.temp_unit.currentIndexChanged.connect(self._persist_parameters)
        self.nplc.currentIndexChanged.connect(self._persist_parameters)
        self.rate.valueChanged.connect(self._persist_parameters)
        self.channel.valueChanged.connect(self._persist_parameters)
        self.scan_check.toggled.connect(self._persist_parameters)
        self.scan_function.currentIndexChanged.connect(
            self._apply_function_to_selection
        )
        self.scan_nplc.currentIndexChanged.connect(self._persist_parameters)
        self.min_scan_seconds.valueChanged.connect(self._persist_parameters)
        self.scan_count.valueChanged.connect(
            self._apply_count_to_selection
        )
        self.pre_scan_wait.valueChanged.connect(self._persist_parameters)
        self.post_scan_wait.valueChanged.connect(self._persist_parameters)
        self.scan_table.itemChanged.connect(self._on_table_item_changed)
        self.scan_table.itemSelectionChanged.connect(
            self._on_selection_changed
        )
        self._sync_scan()
        self._sync_function()
        self._sync_channel()
        self._on_selection_changed()

    def _load_saved_parameters(self) -> None:
        if self._config is None:
            return
        self._loading = True
        values = self._config.daq_parameters()
        self._saved_channel = max(101, int(values["channel"]))
        self.channel.setValue(self._saved_channel)
        function_index = self.function.findData(values["function"])
        if function_index >= 0:
            self.function.setCurrentIndex(function_index)
        nplc_index = self.nplc.findData(float(values["nplc"]))
        if nplc_index >= 0:
            self.nplc.setCurrentIndex(nplc_index)
        scan_nplc_index = self.scan_nplc.findData(float(values["nplc"]))
        if scan_nplc_index >= 0:
            self.scan_nplc.setCurrentIndex(scan_nplc_index)
        temp_index = self.temp_sensor.findData(values["temperature"])
        if temp_index >= 0:
            self.temp_sensor.setCurrentIndex(temp_index)
        unit_index = self.temp_unit.findData(values["temp_unit"])
        if unit_index >= 0:
            self.temp_unit.setCurrentIndex(unit_index)
        self.rate.setValue(float(values["rate"]))
        self.min_scan_seconds.setValue(
            float(values.get("min_scan_seconds", 0.0))
        )
        self.scan_count.setValue(int(values["scan_count"]))
        self.pre_scan_wait.setValue(float(values["pre_scan_wait"]))
        self.post_scan_wait.setValue(float(values["post_scan_wait"]))
        for item in values.get("channels", []):
            try:
                spec = ScanChannelConfig(
                    int(item["channel"]),
                    str(item["function"]),
                    max(1, int(item.get("count", 1))),
                )
                self._scan_specs[spec.channel] = spec
            except (KeyError, TypeError, ValueError):
                continue
        try:
            self._saved_enabled = set(
                parse_channels(str(values["scan_list"]))
            )
        except ValueError:
            self._saved_enabled = set(range(101, 111))
        self.scan_check.setChecked(bool(values["scan"]))
        self._loading = False

    def _persist_parameters(self) -> None:
        if self._loading:
            return
        if self.scan_check.isChecked():
            self._saved_enabled = set(self._enabled_channels())
        if self._config is not None:
            config = self.config()
            self._config.save_daq_parameters(
                {
                    "channel": config.channel,
                    "function": config.function,
                    "nplc": config.nplc,
                    "temperature": config.temperature,
                    "temp_unit": config.temp_unit,
                    "rate": config.rate,
                    "scan": config.scan,
                    "scan_list": config.scan_list,
                    "scan_rate": config.scan_rate,
                    "scan_count": config.scan_count,
                    "pre_scan_wait": config.pre_scan_wait,
                    "post_scan_wait": config.post_scan_wait,
                    "min_scan_seconds": config.min_scan_seconds,
                    "channels": [
                        {
                            "channel": spec.channel,
                            "function": spec.function,
                            "count": spec.count,
                        }
                        for spec in sorted(
                            self._scan_specs.values(),
                            key=lambda item: item.channel,
                        )
                    ],
                }
            )
        self.config_changed.emit()

    def _sync_scan(self) -> None:
        scan = self.scan_check.isChecked()
        self.channel.setEnabled(not scan)
        self.scan_group.setVisible(scan)
        self.scan_config.setVisible(scan)
        self.function.setVisible(not scan)
        self.nplc.setVisible(not scan)
        self.rate.setVisible(not scan)
        self._function_label.setVisible(not scan)
        self._nplc_label.setVisible(not scan)
        self._rate_label.setVisible(not scan)
        self._update_temp_visibility()

    def _sync_function(self) -> None:
        self._update_temp_visibility()

    def _update_temp_visibility(self) -> None:
        if self.scan_check.isChecked():
            functions = {
                self.scan_function.currentData(),
                *(
                    self.scan_table.cellWidget(row, 2).currentData()
                    for row in range(self.scan_table.rowCount())
                    if self.scan_table.cellWidget(row, 2) is not None
                ),
            }
            temp = "TEMP" in functions
        else:
            temp = self.function.currentData() == "TEMP"
        for widget, label in (
            (self.temp_sensor, self._temp_sensor_label),
            (self.temp_unit, self._temp_unit_label),
        ):
            widget.setVisible(temp)
            if label is not None:
                label.setVisible(temp)

    def _channel_combo(self, channel: int) -> ThemedComboBox:
        combo = ThemedComboBox(self.scan_table)
        for label, value in _FUNCTIONS:
            combo.addItem(label, value)
        spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
        index = combo.findData(spec.function)
        if index >= 0:
            combo.setCurrentIndex(index)
        if channel in self._current_channels:
            for idx in range(combo.count()):
                value = combo.itemData(idx)
                combo.model().item(idx).setEnabled(
                    value in {"CURR:DC", "CURR:AC"}
                )
            if combo.currentData() not in {"CURR:DC", "CURR:AC"}:
                combo.setCurrentIndex(combo.findData("CURR:DC"))
        combo.currentIndexChanged.connect(
            lambda _index, ch=channel: self._on_row_config_changed(ch)
        )
        return combo

    def _channel_count(self, channel: int) -> QSpinBox:
        spin = QSpinBox(self.scan_table)
        spin.setRange(1, 50000)
        spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
        spin.setValue(max(1, spec.count))
        spin.valueChanged.connect(
            lambda value, ch=channel: self._on_row_count_changed(ch, value)
        )
        return spin

    def _rebuild_table(self, channels) -> None:
        channels = tuple(sorted(channels))
        self._available_channels = channels
        if not channels:
            return
        self.scan_table.blockSignals(True)
        self.scan_table.setRowCount(0)
        for channel in channels:
            row = self.scan_table.rowCount()
            self.scan_table.insertRow(row)
            item = QTableWidgetItem("")
            item.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            enabled = (
                channel in self._saved_enabled
                if self._saved_enabled is not None
                else 101 <= channel <= 110
            )
            item.setCheckState(
                Qt.CheckState.Checked if enabled else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, channel)
            self.scan_table.setItem(row, 0, item)
            channel_item = QTableWidgetItem(str(channel))
            channel_item.setData(Qt.ItemDataRole.UserRole, channel)
            channel_item.setFlags(
                Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
            )
            self.scan_table.setItem(row, 1, channel_item)
            self.scan_table.setCellWidget(row, 2, self._channel_combo(channel))
            self.scan_table.setCellWidget(row, 3, self._channel_count(channel))
        if channels and not any(
            self.scan_table.item(row, 0).checkState()
            == Qt.CheckState.Checked
            for row in range(self.scan_table.rowCount())
        ):
            for row in range(min(10, self.scan_table.rowCount())):
                self.scan_table.item(row, 0).setCheckState(
                    Qt.CheckState.Checked
                )
        self.scan_table.blockSignals(False)
        self.channel.blockSignals(True)
        self.channel.setRange(channels[0], channels[-1])
        if self.channel.value() not in channels:
            self.channel.setValue(
                self._saved_channel
                if self._saved_channel in channels
                else channels[0]
            )
        self.channel.blockSignals(False)
        self._sync_channel()
        self._update_temp_visibility()

    def set_slots(self, slots) -> None:
        channels = sorted(
            channel for item in slots for channel in item.channels
        )
        if not channels:
            return
        existing = set(self._scan_specs)
        for channel in list(self._scan_specs):
            if channel not in channels:
                self._scan_specs.pop(channel, None)
        for channel in channels:
            if channel not in existing:
                self._scan_specs.setdefault(
                    channel, ScanChannelConfig(channel)
                )
        self._current_channels = {
            channel for item in slots for channel in item.current_channels
        }
        self._rebuild_table(channels)
        self._persist_parameters()

    def _on_table_item_changed(self, item) -> None:
        if self._loading or item.column() != 0:
            return
        self._persist_parameters()

    def _on_row_config_changed(self, channel: int) -> None:
        if self._loading:
            return
        combo = self.scan_table.cellWidget(
            self.scan_table.currentRow(), 2
        )
        row = self._row_for_channel(channel)
        if row is None:
            return
        combo = self.scan_table.cellWidget(row, 2)
        spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
        self._scan_specs[channel] = ScanChannelConfig(
            channel,
            str(combo.currentData()),
            spec.count,
        )
        self._persist_parameters()

    def _on_row_count_changed(self, channel: int, value: int) -> None:
        if self._loading:
            return
        spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
        self._scan_specs[channel] = ScanChannelConfig(
            channel, spec.function, max(1, int(value))
        )
        self._persist_parameters()

    def _row_for_channel(self, channel: int) -> int | None:
        for row in range(self.scan_table.rowCount()):
            item = self.scan_table.item(row, 1)
            if item is not None and int(
                item.data(Qt.ItemDataRole.UserRole)
            ) == channel:
                return row
        return None

    def _selected_rows(self) -> list[int]:
        return sorted(
            {index.row() for index in self.scan_table.selectionModel().selectedRows()}
        )

    def _selected_channels(self) -> list[int]:
        return [
            int(
                self.scan_table.item(row, 1).data(
                    Qt.ItemDataRole.UserRole
                )
            )
            for row in self._selected_rows()
        ]

    def _on_selection_changed(self) -> None:
        selected = self._selected_channels()
        self.scan_config.setEnabled(bool(selected))
        if not selected:
            self._selection_channel = None
            return
        channel = selected[0]
        self._selection_channel = channel
        spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
        self._loading = True
        idx = self.scan_function.findData(spec.function)
        if idx >= 0:
            self.scan_function.setCurrentIndex(idx)
        self.scan_count.setValue(max(1, spec.count))
        self._loading = False

    def _apply_function_to_selection(self) -> None:
        if self._loading:
            return
        function = str(self.scan_function.currentData())
        for channel in self._selected_channels():
            spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
            self._scan_specs[channel] = ScanChannelConfig(
                channel, function, spec.count
            )
            row = self._row_for_channel(channel)
            if row is None:
                continue
            combo = self.scan_table.cellWidget(row, 2)
            if combo is not None:
                combo.blockSignals(True)
                index = combo.findData(function)
                if index >= 0:
                    combo.setCurrentIndex(index)
                combo.blockSignals(False)
        self._update_temp_visibility()
        self._persist_parameters()

    def _apply_count_to_selection(self) -> None:
        if self._loading:
            return
        count = max(1, int(self.scan_count.value()))
        for channel in self._selected_channels():
            spec = self._scan_specs.get(channel, ScanChannelConfig(channel))
            self._scan_specs[channel] = ScanChannelConfig(
                channel, spec.function, count
            )
            row = self._row_for_channel(channel)
            if row is None:
                continue
            spin = self.scan_table.cellWidget(row, 3)
            if spin is not None:
                spin.blockSignals(True)
                spin.setValue(count)
                spin.blockSignals(False)
        self._persist_parameters()

    def _set_all_scan(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        self.scan_table.blockSignals(True)
        for row in range(self.scan_table.rowCount()):
            self.scan_table.item(row, 0).setCheckState(state)
        self.scan_table.blockSignals(False)
        self._persist_parameters()

    def _enabled_channels(self) -> list[int]:
        channels = []
        for row in range(self.scan_table.rowCount()):
            item = self.scan_table.item(row, 0)
            channel_item = self.scan_table.item(row, 1)
            if (
                item is not None
                and channel_item is not None
                and item.checkState() == Qt.CheckState.Checked
            ):
                channels.append(
                    int(channel_item.data(Qt.ItemDataRole.UserRole))
                )
        return sorted(channels)

    def _scan_channels(self) -> str:
        return ",".join(str(channel) for channel in self._enabled_channels())

    def _sync_channel(self) -> None:
        current_only = self.channel.value() in self._current_channels
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
        scan = self.scan_check.isChecked()
        enabled = self._enabled_channels() if scan else []
        if scan:
            specs = tuple(
                self._scan_specs.get(channel, ScanChannelConfig(channel))
                for channel in enabled
            )
            first = specs[0] if specs else ScanChannelConfig(self.channel.value())
            return DaqConfig(
                channel=first.channel,
                function=first.function,
                nplc=float(self.scan_nplc.currentData()),
                temperature=str(self.temp_sensor.currentData()),
                temp_unit=str(self.temp_unit.currentData()),
                rate=float(self.rate.value()),
                scan=True,
                scan_list=",".join(str(channel) for channel in enabled),
                scan_rate=1000.0,
                scan_count=max((spec.count for spec in specs), default=1),
                pre_scan_wait=float(self.pre_scan_wait.value()),
                post_scan_wait=float(self.post_scan_wait.value()),
                min_scan_seconds=float(self.min_scan_seconds.value()),
                channels=specs,
            )
        channel = int(self.channel.value())
        function = str(self.function.currentData())
        if channel in self._current_channels and function not in {
            "CURR:DC",
            "CURR:AC",
        }:
            function = "CURR:DC"
        return DaqConfig(
            channel=channel,
            function=function,
            nplc=float(self.nplc.currentData()),
            temperature=str(self.temp_sensor.currentData()),
            temp_unit=str(self.temp_unit.currentData()),
            rate=float(self.rate.value()),
            scan=False,
            scan_list="",
            scan_rate=1000.0,
            pre_scan_wait=float(self.pre_scan_wait.value()),
            post_scan_wait=float(self.post_scan_wait.value()),
            min_scan_seconds=float(self.min_scan_seconds.value()),
        )

    def selected_channel_count(self) -> int:
        if not self.scan_check.isChecked():
            return 1
        return len(self._enabled_channels())

    def set_state(self, state: str) -> None:
        self._state = state

# Backwards-compatible name used by older tests/imports.
DaqPanel = DaqConnectionPanel
