"""右栏：功能/量程/采集设置。"""

from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.domain.functions import FunctionSpec, display_digits, function_spec
from app.domain.models import AcquisitionConfig, InstrumentStatus
from app.domain.precision import AC_BANDS, ACI_BANDS
from app.ui.widgets.common import format_range, unit_options
from app.ui.widgets.themed_combo import ThemedComboBox

_FUNCTION_BUTTONS: tuple[tuple[str, str, str], ...] = (
    ("VOLT", "DC V", "直流电压"),
    ("VOLT:AC", "AC V", "交流电压"),
    ("FRES", "Ω 4W", "四线电阻"),
    ("CURR", "DC I", "直流电流"),
    ("CURR:AC", "AC I", "交流电流"),
    ("RES", "Ω 2W", "两线电阻"),
    ("FREQ", "Freq", "频率/周期在量程选项里切换"),
    ("CONT", "Cont", "通断"),
    ("DIOD", "Diode", "二极管"),
)


class DmmPanel(QFrame):
    config_changed = Signal(object)
    unit_mode_changed = Signal(str)
    ac_band_changed = Signal(str)
    function_changed = Signal(str)

    def __init__(
        self,
        initial: AcquisitionConfig | None = None,
        unit_modes: dict[str, str] | None = None,
        ac_band: str = "10-20k",
        range_memory: dict[str, tuple[bool, float]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("RightPanel")
        self.setMinimumWidth(320)
        self.setMaximumWidth(430)
        self._loading = True
        self._supports_nplc = True
        self._initial = initial or AcquisitionConfig()
        self._spec = function_spec(self._initial.function)
        self._unit_base = self._spec.unit
        self._unit_modes: dict[str, str] = dict(unit_modes or {})
        self._ac_band = ac_band
        self._null_value = float(self._initial.null_value)
        self._range_memory = dict(range_memory or {})
        self._last_value: float | None = None
        self._switch_locked = False
        self._switch_timer = QTimer(self)
        self._switch_timer.setSingleShot(True)
        self._switch_timer.setInterval(700)
        self._switch_timer.timeout.connect(self._unlock_function_switch)
        self._state = "disconnected"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        content = QWidget(scroll)
        content.setObjectName("RightContent")
        scroll.setWidget(content)
        outer.addWidget(scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(10)

        title = QLabel("DMM 参数", content)
        title.setObjectName("SectionTitle")
        root.addWidget(title)

        settings_group = QGroupBox("采集设置", content)
        settings_form = QFormLayout(settings_group)
        settings_form.setContentsMargins(12, 14, 12, 12)
        settings_form.setSpacing(8)
        settings_form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        self._function_group = QButtonGroup(self)
        self._function_group.setExclusive(True)
        function_grid = QGridLayout()
        function_grid.setSpacing(6)
        for index, (raw, label, tip) in enumerate(_FUNCTION_BUTTONS):
            button = QPushButton(label, settings_group)
            button.setCheckable(True)
            button.setObjectName("FunctionButton")
            button.setToolTip(tip)
            button.setMinimumHeight(64)
            button.setMaximumHeight(64)
            button.setSizePolicy(
                button.sizePolicy().horizontalPolicy(),
                button.sizePolicy().verticalPolicy(),
            )
            button.setProperty("raw", raw)
            self._function_group.addButton(button)
            function_grid.addWidget(button, index // 3, index % 3)
            button.clicked.connect(
                lambda _checked=False, raw=raw: self._select_function(raw)
            )
        settings_form.addRow(function_grid)

        self.auto_range_btn = QPushButton("自动量程", settings_group)
        self.auto_range_btn.setObjectName("AutoRangeButton")
        self.auto_range_btn.setCheckable(True)
        self.range_combo = ThemedComboBox(settings_group)
        range_row = QWidget(settings_group)
        range_layout = QHBoxLayout(range_row)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(6)
        range_layout.addWidget(self.auto_range_btn)
        range_layout.addWidget(self.range_combo, 1)

        self.nplc_combo = ThemedComboBox(settings_group)
        for value in (0.02, 0.2, 1.0, 10.0, 100.0):
            self.nplc_combo.addItem(f"{value:g}", value)

        self.rate_spin = QSpinBox(settings_group)
        self.rate_spin.setRange(1, 1_000_000)
        self.rate_spin.setSingleStep(1)
        self.rate_spin.setSuffix(" Hz")
        self.rate_spin.setToolTip(
            "设定最高采样率；实际速率受 NPLC/AZ 的硬件能力和平均值设置限制"
        )

        self.ac_filter_combo = ThemedComboBox(settings_group)
        for value in (3, 20, 200):
            self.ac_filter_combo.addItem(f"{value} Hz", value)
        self.impedance_combo = ThemedComboBox(settings_group)
        self.impedance_combo.addItem("10 MΩ", "10M")
        self.impedance_combo.addItem(">10 GΩ", "high")

        self.null_btn = QPushButton("NULL", settings_group)
        self.null_btn.setObjectName("NullButton")
        self.null_btn.setCheckable(True)
        self.null_btn.setToolTip("点击启用 NULL 偏移；再次点击关闭")
        self.null_btn.toggled.connect(self._on_null_toggled)

        self.az_check = QCheckBox("自动调零（AZ）", settings_group)

        self.unit_combo = ThemedComboBox(settings_group)
        self.unit_combo.setToolTip("只影响界面显示，不改变仪器量程或读数")
        self.unit_combo.addItem("AUTO", "auto")
        self.ac_band_combo = ThemedComboBox(settings_group)
        self.ac_band_combo.setToolTip("仅影响 ACV/ACI 的精度误差计算，不改仪器滤波")

        settings_form.addRow("量程", range_row)
        self._range_row = range_row
        self._range_label = settings_form.labelForField(range_row)
        settings_form.addRow("NPLC", self.nplc_combo)
        settings_form.addRow("最高采样率", self.rate_spin)
        settings_form.addRow("AC 滤波", self.ac_filter_combo)
        self._ac_filter_label = settings_form.labelForField(self.ac_filter_combo)
        settings_form.addRow("DC 阻抗", self.impedance_combo)
        self._impedance_label = settings_form.labelForField(self.impedance_combo)
        settings_form.addRow("", self.null_btn)
        settings_form.addRow("单位", self.unit_combo)
        settings_form.addRow("AC 频段", self.ac_band_combo)
        self._ac_band_label = settings_form.labelForField(self.ac_band_combo)
        settings_form.addRow("", self.az_check)
        root.addWidget(settings_group)

        self._load_initial()
        self.auto_range_btn.toggled.connect(self._on_auto_range_toggled)
        self.range_combo.currentIndexChanged.connect(self._on_range_changed)
        self.nplc_combo.currentIndexChanged.connect(self._on_value_changed)
        self.rate_spin.valueChanged.connect(self._on_value_changed)
        self.ac_filter_combo.currentIndexChanged.connect(self._on_value_changed)
        self.impedance_combo.currentIndexChanged.connect(self._on_value_changed)
        self.az_check.toggled.connect(self._on_value_changed)
        self.unit_combo.currentIndexChanged.connect(self._on_unit_changed)
        self.ac_band_combo.currentIndexChanged.connect(self._on_ac_band_changed)
        self._loading = False
        self._apply_function_ui(self._spec)

        root.addStretch(1)

    # ---------- 初始化 ----------

    def _load_initial(self) -> None:
        cfg = self._initial
        self._spec = function_spec(cfg.function)
        self._select_function_button(self._spec.raw)
        self._set_range_options(cfg.range_value)
        auto = cfg.range_mode != "manual"
        self.auto_range_btn.setChecked(auto)
        self.auto_range_btn.setText("自动量程" if auto else "手动量程")
        self._range_memory.setdefault(
            self._spec.raw,
            (auto, float(self.range_combo.currentData() or 0.0)),
        )
        nplc_index = self.nplc_combo.findData(float(cfg.nplc))
        if nplc_index >= 0:
            self.nplc_combo.setCurrentIndex(nplc_index)
        self.rate_spin.setValue(max(1, int(round(cfg.rate))))
        filter_index = self.ac_filter_combo.findData(cfg.ac_filter)
        self.ac_filter_combo.setCurrentIndex(filter_index if filter_index >= 0 else 1)
        imp_index = self.impedance_combo.findData(cfg.input_impedance)
        self.impedance_combo.setCurrentIndex(imp_index if imp_index >= 0 else 0)
        self._null_value = float(cfg.null_value)
        self.null_btn.setChecked(cfg.null_enabled)
        self.null_btn.setText("NULL")  # 偏移值放 tooltip，不占行
        self.null_btn.setToolTip(
            f"NULL 偏移：{self._null_value:g}\n点击启用/关闭"
        )
        self.az_check.setChecked(cfg.az)

    def _select_function_button(self, raw: str) -> None:
        button_raw = "FREQ" if raw == "PER" else raw
        for button in self._function_group.buttons():
            if button.property("raw") == button_raw:
                button.setChecked(True)
                return

    def _set_range_options(self, desired: float = 0.0) -> None:
        spec = self._spec
        with QSignalBlocker(self.range_combo):
            self.range_combo.clear()
            for value in spec.ranges:
                self.range_combo.addItem(format_range(str(value), spec.unit), float(value))
            index = self.range_combo.findData(float(desired))
            if index < 0 and spec.ranges:
                index = 0
            if index >= 0:
                self.range_combo.setCurrentIndex(index)

    def set_current_value(self, value: float | None) -> None:
        self._last_value = value

    def _select_function(self, raw: str) -> None:
        if self._loading or self._switch_locked:
            return
        self._remember_current_range()
        next_raw = raw
        spec = function_spec(next_raw)
        self._spec = spec
        auto, desired = self._range_memory.get(
            spec.raw, (True, spec.ranges[0] if spec.ranges else 0.0)
        )
        self._set_range_options(desired)
        with QSignalBlocker(self.auto_range_btn):
            self.auto_range_btn.setChecked(auto)
        self.auto_range_btn.setText("自动量程" if auto else "手动量程")
        with QSignalBlocker(self.az_check):
            self.az_check.setChecked(True)
        self._apply_function_ui(spec)
        self._switch_locked = True
        self._switch_timer.start(700)
        self._apply_enabled_state()
        self.function_changed.emit(spec.raw)
        self._on_value_changed()

    def toggle_nplc_1_10(self) -> bool:
        # VAC/ACI/频率/周期/导通/二极管没有 NPLC 设置，不能绕过禁用控件。
        if not self._supports_nplc:
            return False
        current = float(self.nplc_combo.currentData())
        target = 10.0 if abs(current - 1.0) < 1e-9 else 1.0
        index = self.nplc_combo.findData(target)
        if index < 0:
            return False
        self.nplc_combo.setCurrentIndex(index)
        return True

    def select_function_raw(self, raw: str) -> bool:
        if self._loading or self._switch_locked:
            return False
        spec = function_spec(raw)
        if spec.raw == self._spec.raw:
            return True
        self._select_function_button(spec.raw)
        self._select_function(spec.raw)
        return True

    def _unlock_function_switch(self) -> None:
        self._switch_locked = False
        self._apply_enabled_state()

    def _apply_function_ui(self, spec: FunctionSpec) -> None:
        self._spec = spec
        self._supports_nplc = spec.supports_nplc
        is_ac = spec.raw in {"VOLT:AC", "CURR:AC"}
        if is_ac:
            options = ACI_BANDS if spec.raw == "CURR:AC" else AC_BANDS
            desired = self._ac_band if self._ac_band in {k for k, _ in options} else options[0][0]
            with QSignalBlocker(self.ac_band_combo):
                self.ac_band_combo.clear()
                for key, label in options:
                    self.ac_band_combo.addItem(label, key)
                self.ac_band_combo.setCurrentIndex(self.ac_band_combo.findData(desired))
            self._ac_band = str(self.ac_band_combo.currentData())
        self._set_ac_band_visible(is_ac)
        if is_ac:
            self.ac_band_changed.emit(self._ac_band)

        is_frequency = spec.raw in {"FREQ", "PER"}
        if is_frequency:
            with QSignalBlocker(self.range_combo):
                self.range_combo.clear()
                self.range_combo.addItem("频率", "FREQ")
                self.range_combo.addItem("周期", "PER")
                self.range_combo.setCurrentIndex(
                    max(0, self.range_combo.findData(spec.raw))
                )
            with QSignalBlocker(self.auto_range_btn):
                self.auto_range_btn.setChecked(False)
            self.auto_range_btn.setVisible(False)
            self._range_row.setVisible(True)
            if self._range_label is not None:
                self._range_label.setVisible(True)
        else:
            fixed = spec.fixed_range
            self.auto_range_btn.setVisible(True)
            self._range_row.setVisible(not fixed)
            if self._range_label is not None:
                self._range_label.setVisible(not fixed)

        self.ac_filter_combo.setVisible(spec.supports_ac_filter)
        if self._ac_filter_label is not None:
            self._ac_filter_label.setVisible(spec.supports_ac_filter)
        impedance_visible = spec.raw == "VOLT"
        self.impedance_combo.setVisible(impedance_visible)
        if self._impedance_label is not None:
            self._impedance_label.setVisible(impedance_visible)
        self.null_btn.setVisible(spec.supports_null)

        self._set_unit_base(spec.unit)
        self._apply_enabled_state()

    def _apply_enabled_state(self) -> None:
        enabled = self._state in {"ready", "acquiring"}
        for button in self._function_group.buttons():
            button.setEnabled(enabled and not self._switch_locked)
        self.auto_range_btn.setEnabled(enabled)
        if self._spec.raw in {"FREQ", "PER"}:
            self.range_combo.setEnabled(enabled)
        else:
            self.range_combo.setEnabled(
                enabled and not self.auto_range_btn.isChecked() and not self._spec.fixed_range
            )
        self.nplc_combo.setEnabled(enabled and self._supports_nplc)
        self.rate_spin.setEnabled(enabled)
        self.ac_filter_combo.setEnabled(enabled)
        self.impedance_combo.setEnabled(enabled)
        self.null_btn.setEnabled(enabled)
        self.az_check.setEnabled(enabled and self._supports_nplc)
        self.unit_combo.setEnabled(enabled)
        self.ac_band_combo.setEnabled(enabled)


    # ---------- 配置 ----------

    def current_config(self) -> AcquisitionConfig:
        spec = self._spec
        is_frequency = spec.raw in {"FREQ", "PER"}
        manual = is_frequency or not self.auto_range_btn.isChecked()
        range_value = (
            float(self.range_combo.currentData() or 0.0)
            if manual and not is_frequency
            else 0.0
        )
        nplc = float(self.nplc_combo.currentData())
        az = self.az_check.isChecked()
        return AcquisitionConfig(
            nplc=nplc,
            digits=display_digits(spec.label, nplc, az),
            rate=float(self.rate_spin.value()),
            az=az,
            function=spec.raw,
            range_mode="manual" if manual else "auto",
            range_value=range_value,
            ac_filter=int(self.ac_filter_combo.currentData()),
            input_impedance=str(self.impedance_combo.currentData()),
            null_enabled=self.null_btn.isChecked() and spec.supports_null,
            null_value=self._null_value,
        )

    @property
    def unit_base(self) -> str:
        return self._unit_base

    @property
    def ac_band(self) -> str:
        return self._ac_band

    def set_state(self, state: str) -> None:
        self._state = state
        self._apply_enabled_state()

    def set_status(self, status: InstrumentStatus) -> None:
        # 状态显示已合并到主读数；这里只保持控件可用性。
        self._supports_nplc = status.function.supports_nplc
        self._apply_enabled_state()

    def clear(self) -> None:
        self._set_ac_band_visible(False)

    # ---------- 事件 ----------

    def _remember_current_range(self) -> None:
        if not self._spec or self._spec.raw in {"FREQ", "PER"}:
            return
        if self._spec.fixed_range:
            return
        self._range_memory[self._spec.raw] = (
            self.auto_range_btn.isChecked(),
            float(self.range_combo.currentData() or 0.0),
        )

    def range_memory(self) -> dict[str, tuple[bool, float]]:
        self._remember_current_range()
        return dict(self._range_memory)

    def _on_auto_range_toggled(self, checked: bool) -> None:
        if self._loading:
            return
        self.auto_range_btn.setText("自动量程" if checked else "手动量程")
        self._remember_current_range()
        self._apply_enabled_state()
        self._on_value_changed()

    def _on_range_changed(self) -> None:
        if self._loading:
            return
        data = self.range_combo.currentData()
        if data in {"FREQ", "PER"} and self._spec.raw in {"FREQ", "PER"}:
            if data != self._spec.raw:
                self._spec = function_spec(str(data))
                self._apply_function_ui(self._spec)
                self.function_changed.emit(self._spec.raw)
                self._on_value_changed()
            return
        self._on_value_changed()

    def _on_null_toggled(self, enabled: bool) -> None:
        if self._loading:
            return
        if enabled:
            if self._last_value is None:
                with QSignalBlocker(self.null_btn):
                    self.null_btn.setChecked(False)
                return
            self._null_value = self._last_value
            self.null_btn.setToolTip(
                f"NULL 已去皮：{self._null_value:g}\n再次点击关闭"
            )
        self._on_value_changed()

    def _on_unit_changed(self) -> None:
        if self._loading:
            return
        mode = str(self.unit_combo.currentData())
        self._unit_modes[self._unit_base] = mode
        self.unit_mode_changed.emit(mode)

    def _on_ac_band_changed(self) -> None:
        if self._loading:
            return
        self._ac_band = str(self.ac_band_combo.currentData())
        self.ac_band_changed.emit(self._ac_band)

    def _set_unit_base(self, base: str) -> None:
        self._unit_base = base
        options = unit_options(base, self._spec.label)
        desired = self._unit_modes.get(base, "auto")
        with QSignalBlocker(self.unit_combo):
            self.unit_combo.clear()
            for key, label in options:
                self.unit_combo.addItem(label, key)
            index = self.unit_combo.findData(desired)
            self.unit_combo.setCurrentIndex(index if index >= 0 else 0)
        if self.unit_combo.currentData() != desired:
            self._unit_modes[base] = str(self.unit_combo.currentData())
        self.unit_mode_changed.emit(str(self.unit_combo.currentData()))

    def _set_ac_band_visible(self, visible: bool) -> None:
        self.ac_band_combo.setVisible(visible)
        if self._ac_band_label is not None:
            self._ac_band_label.setVisible(visible)

    def _on_value_changed(self) -> None:
        if self._loading:
            return
        self._remember_current_range()
        self.config_changed.emit(self.current_config())


