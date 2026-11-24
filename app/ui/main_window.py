"""主窗口：三栏布局与阶段 1 交互。"""

from __future__ import annotations

import csv
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QEventLoop, QProcess, QTimer, Qt, QUrl
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDesktopServices,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.config import AppConfig
from app.constants import APP_NAME, VERSION
from app.domain.functions import function_spec
from app.domain.models import (
    AcquisitionConfig,
    Batch,
    InstrumentStatus,
    Reading,
    SerialSettings,
)
from app.ui.controller import SessionController
from app.ui.dialogs.error_code_dialog import ErrorCodeDialog
from app.ui.dialogs.log_dialogs import SerialLogDialog, SoftwareLogDialog
from app.ui.dialogs.scpi_dialog import ScpiDialog
from app.ui.dialogs.serial_dialog import SerialDialog
from app.ui.floating_window import FloatingWindow
from app.ui.sections.dmm_panel import DmmPanel
from app.ui.sections.readout_panel import ReadoutPanel
from app.ui.sections.tool_panel import ToolPanel
from app.ui.sections.trend_panel import TrendPanel
from app.ui.audio import OhmsBeeper
from app.ui.widgets.common import ErrorBanner, format_range

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self._config = config
        self._state = "disconnected"
        self._single_count = 0
        self._record_after_single = False
        self._last_status: InstrumentStatus | None = None
        self._pending_settings: SerialSettings | None = None
        self._needs_initial_config = False
        self._auto_open_attempted = False
        self._auto_open_pending = False
        self._auto_open_failed = False
        self._reopen_after_close = False
        self._ohms_beeper = OhmsBeeper(self)
        self._closing = False
        self._scpi_dialog: ScpiDialog | None = None
        self._software_log_dialog: SoftwareLogDialog | None = None
        self._serial_log_dialog: SerialLogDialog | None = None
        self._error_code_dialog: ErrorCodeDialog | None = None
        self._floating_window: FloatingWindow | None = None
        self._floating_minimized_main = False
        self._read_active = False

        self.setWindowTitle("34401A上位机")
        icon_path = Path(__file__).resolve().parents[2] / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1280, 820)
        self.setMinimumSize(960, 640)

        self.controller = SessionController(self._config, self)
        self._build_ui()
        self._build_menu()
        self._connect_signals()
        self._setup_shortcuts()

        geometry = config.window_geometry()
        if geometry:
            self.restoreGeometry(geometry)

        self._on_state("disconnected", "连接未打开")
        QTimer.singleShot(500, self._auto_open_serial)

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("CentralRoot")
        outer = QVBoxLayout(central)
        outer.setContentsMargins(10, 10, 10, 6)
        outer.setSpacing(8)

        self.error_banner = ErrorBanner(central)
        outer.addWidget(self.error_banner)

        floating_percent, floating_opacity = self._config.floating_settings()
        self.tool_panel = ToolPanel(
            central,
            floating_percent=floating_percent,
            floating_opacity=floating_opacity,
            section_order=self._config.tool_section_order(),
        )
        self.tool_panel.section_order_changed.connect(
            self._config.save_tool_section_order
        )
        self.readout_panel = ReadoutPanel(central)
        self.trend_panel = TrendPanel(self.controller.ring, central)
        self.dmm_panel = DmmPanel(
            self._config.acquisition_config(),
            unit_modes=self._config.unit_modes(),
            ac_band=self._config.ac_band(),
            range_memory={},
            parent=central,
        )
        initial = self.dmm_panel.current_config()
        self.readout_panel.set_digits(initial.digits)
        self.readout_panel.set_flags(initial.az, initial.null_enabled)
        self.readout_panel.set_range_mode(initial.range_mode != "manual")
        self.readout_panel.set_accuracy_tier(self._config.accuracy_tier())
        self.readout_panel.set_ac_band(self._config.ac_band())

        center = QSplitter(Qt.Orientation.Vertical, central)
        center.addWidget(self.readout_panel)
        center.addWidget(self.trend_panel)
        center.setStretchFactor(0, 38)
        center.setStretchFactor(1, 62)
        center.setSizes([360, 520])
        center.setChildrenCollapsible(False)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self._splitter = splitter
        splitter.addWidget(self.tool_panel)
        splitter.addWidget(center)
        splitter.addWidget(self.dmm_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([230, 700, 350])
        splitter.setChildrenCollapsible(True)
        outer.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self._apply_ohms_beeper_settings()

        self.status_state = QLabel("未连接", self)
        self.status_identity = QLabel("", self)
        self.statusBar().addWidget(self.status_state)
        self.statusBar().addPermanentWidget(self.status_identity)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("文件(&F)")
        location_action = QAction("更改 CSV 存储位置…", self)
        location_action.triggered.connect(self._change_csv_directory)
        file_menu.addAction(location_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("视图(&V)")
        self.left_action = QAction("显示左侧工具栏", self)
        self.left_action.setCheckable(True)
        self.left_action.setChecked(True)
        self.left_action.setShortcut(QKeySequence("Ctrl+L"))
        self.left_action.toggled.connect(self._set_left_visible)
        view_menu.addAction(self.left_action)
        scale_menu = view_menu.addMenu("界面缩放")
        self.scale_group = QActionGroup(self)
        self.scale_group.setExclusive(True)
        current_scale = self._config.scale_factor()
        for percent in (75, 100, 125, 150, 200):
            action = QAction(f"{percent}%", self)
            action.setCheckable(True)
            action.setChecked(percent == current_scale)
            action.triggered.connect(
                lambda _checked=False, value=percent: self._set_scale_factor(value)
            )
            self.scale_group.addAction(action)
            scale_menu.addAction(action)

        width_menu = view_menu.addMenu("曲线粗细")
        self.line_width_group = QActionGroup(self)
        self.line_width_group.setExclusive(True)
        for width in (1.0, 1.5, 2.0):
            label = f"{width:g} px"
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(width == 2.0)
            action.triggered.connect(
                lambda _checked=False, value=width: (
                    self.trend_panel.chart.set_line_width(value)
                )
            )
            self.line_width_group.addAction(action)
            width_menu.addAction(action)

        tools_menu = self.menuBar().addMenu("工具(&T)")
        self.scpi_action = QAction("SCPI 终端...", self)
        self.scpi_action.triggered.connect(self._open_scpi)
        tools_menu.addAction(self.scpi_action)
        self.error_code_action = QAction("错误码查询...", self)
        self.error_code_action.triggered.connect(self._open_error_codes)
        tools_menu.addAction(self.error_code_action)
        logs_menu = tools_menu.addMenu("日志")
        software_log_action = QAction("软件日志", self)
        software_log_action.triggered.connect(self._open_software_log)
        logs_menu.addAction(software_log_action)
        serial_log_action = QAction("串口日志", self)
        serial_log_action.triggered.connect(self._open_serial_log)
        logs_menu.addAction(serial_log_action)

        comm_menu = self.menuBar().addMenu("通信(&C)")
        settings_action = QAction("连接设置…", self)
        settings_action.triggered.connect(self._open_serial_dialog)
        comm_menu.addAction(settings_action)
        self.open_action = QAction("打开连接", self)
        self.open_action.triggered.connect(self._toggle_connection)
        comm_menu.addAction(self.open_action)

        instrument_menu = self.menuBar().addMenu("仪器控制(&I)")
        self.rmt_action = QAction("RMT 远程控制", self)
        self.rmt_action.setCheckable(True)
        self.rmt_action.setChecked(self._config.remote_enabled())
        self.rmt_action.setToolTip(
            "开启时进入远程并控制仪器；关闭时只打开串口，不发送任何 SCPI"
        )
        self.rmt_action.toggled.connect(self._on_rmt_toggled)
        instrument_menu.addAction(self.rmt_action)
        instrument_menu.addSeparator()
        self.display_action = QAction("VFD 显示", self)
        self.display_action.setCheckable(True)
        self.display_action.setChecked(self._config.instrument_switches()[0])
        self.display_action.toggled.connect(self._on_display_action)
        instrument_menu.addAction(self.display_action)
        self.beeper_action = QAction("蜂鸣器", self)
        self.beeper_action.setCheckable(True)
        self.beeper_action.setChecked(self._config.instrument_switches()[1])
        self.beeper_action.toggled.connect(self._on_beeper_action)
        instrument_menu.addAction(self.beeper_action)

        shortcut = QShortcut(QKeySequence("F5"), self)
        shortcut.activated.connect(self._request_single_read)

    def _connect_signals(self) -> None:
        self.tool_panel.csv_toggle_requested.connect(self.controller.toggle_csv)
        self.tool_panel.open_csv_folder_requested.connect(self._open_csv_folder)
        self.tool_panel.average_changed.connect(self._on_average_changed)
        self.tool_panel.floating_toggle_requested.connect(
            self._toggle_floating_window
        )
        self.tool_panel.floating_options_changed.connect(
            self._apply_floating_options
        )
        self.tool_panel.beeper_changed.connect(self._apply_ohms_beeper_settings)
        self.tool_panel.test_beep_requested.connect(self._ohms_beeper.test)
        self.readout_panel.single_read_requested.connect(self._request_single_read)
        self.readout_panel.start_stop_requested.connect(self._toggle_acquisition)
        self.dmm_panel.config_changed.connect(self._on_config_changed)
        self.dmm_panel.unit_mode_changed.connect(self._on_unit_mode_changed)
        self.dmm_panel.ac_band_changed.connect(self._on_ac_band_changed)
        self.dmm_panel.function_changed.connect(lambda _raw: self.controller.clear_stats())
        self.readout_panel.tier_changed.connect(self._on_tier_changed)
        self.readout_panel.resolution_changed.connect(self.trend_panel.set_min_y_step)
        self.readout_panel.full_scale_changed.connect(
            self.trend_panel.set_full_scale
        )
        self.readout_panel.display_unit_changed.connect(
            self.trend_panel.set_display_unit
        )
        self.trend_panel.clear_requested.connect(self._clear_data)
        self.trend_panel.save_requested.connect(self._save_as)
        self.trend_panel.save_records_requested.connect(self._save_records)
        self.trend_panel.record_requested.connect(self._handle_record_request)
        self.controller.stats_updated.connect(self.trend_panel.set_stats)

        self.controller.state_changed.connect(self._on_state)
        self.controller.identity_received.connect(self._on_identity)
        self.controller.status_updated.connect(self._on_status)
        self.controller.reading_received.connect(self._on_reading)
        self.controller.read_activity.connect(self._on_read_activity)
        self.controller.batch_received.connect(self._on_batch)
        self.controller.resources_listed.connect(self._on_resources)
        self.controller.error_occurred.connect(self._on_error)
        self.controller.notice.connect(self._on_notice)
        self.controller.rate_updated.connect(self.readout_panel.set_rate)
        self.controller.plan_updated.connect(self._on_plan_updated)
        self.controller.csv_state.connect(self._on_csv_state)
        self.controller.csv_state.connect(self.tool_panel.set_csv_state)

    def _open_connection(
        self,
        settings: SerialSettings,
        attempts: int = 5,
        handshake_timeout_ms: int = 1500,
        save_settings: bool = True,
        remote: bool | None = None,
    ) -> None:
        # 打开成功后才写入配置，避免把打不开的资源字符串记成下次默认值。
        remote = self._config.remote_enabled() if remote is None else remote
        self._pending_settings = settings if save_settings else None
        self._needs_initial_config = remote
        self._single_count = 0
        self.readout_panel.set_count(0)
        self.readout_panel.set_rate(None)
        self.error_banner.hide()
        self.open_action.setEnabled(False)
        self.open_action.setText("正在打开连接…")
        self.status_state.setText(f"正在打开 {settings.resource}…")
        self.controller.open_connection(
            settings,
            attempts=attempts,
            handshake_timeout_ms=handshake_timeout_ms,
            remote=remote,
        )

    def _auto_open_serial(self) -> None:
        if self._auto_open_attempted:
            return
        self._auto_open_attempted = True
        if self._state not in {"disconnected", "error"}:
            return
        settings = self._config.serial_settings()
        settings = SerialSettings(
            resource=settings.resource,
            baud_rate=settings.baud_rate,
            data_bits=settings.data_bits,
            parity=settings.parity,
            stop_bits=settings.stop_bits,
            flow_control=settings.flow_control,
            timeout_ms=3000,
            interface=settings.interface,
        )
        self._auto_open_pending = True
        self._open_connection(
            settings,
            attempts=1,
            handshake_timeout_ms=3000,
            save_settings=False,
            remote=self._config.remote_enabled(),
        )

    def _toggle_connection(self) -> None:
        if self._state in {"disconnected", "error"}:
            self._open_connection(self._config.serial_settings())
        elif self._state != "opening":
            self.controller.close_connection()

    def _on_rmt_toggled(self, enabled: bool) -> None:
        if self._state in {"acquiring", "stopping"}:
            self.rmt_action.blockSignals(True)
            self.rmt_action.setChecked(not enabled)
            self.rmt_action.blockSignals(False)
            QMessageBox.information(
                self, "RMT", "请先停止连续采集，再切换 RMT。"
            )
            return
        self._config.save_remote_enabled(enabled)
        if self._state not in {"local", "ready", "reading"}:
            return
        self._reopen_after_close = True
        self.controller.close_connection()

    def _open_serial_dialog(self) -> None:
        dialog = SerialDialog(
            self._config.serial_settings(),
            serial_resource=self._config.serial_resource(),
            gpib_resource=self._config.gpib_resource(),
            parent=self,
        )
        if not dialog.exec():
            return
        settings = dialog.settings()
        self._config.save_serial_settings(settings)
        self.statusBar().showMessage("连接设置已保存", 3000)
        if self._state in {"ready", "acquiring", "reading"}:
            self.statusBar().showMessage("连接设置已保存，重新打开后生效", 5000)

    def _on_resources(self, _resources: list[str]) -> None:
        # 目前端口由“串口设置”手动填写；保留信号避免无接收者。
        pass

    def _on_state(self, state: str, detail: str) -> None:
        self._state = state
        self.readout_panel.set_state(state, detail)
        self.dmm_panel.set_state(state)
        self.tool_panel.set_state(state)
        self.trend_panel.set_measurement_state(state)
        if state in {"error", "disconnected"}:
            self._record_after_single = False
        self.status_state.setText(detail)
        self.open_action.setEnabled(state not in {"opening", "stopping"})
        if state == "opening":
            self.open_action.setText("正在打开连接…")
        elif state in {"local", "ready", "reading", "acquiring", "stopping"}:
            self.open_action.setText("关闭连接")
        else:
            self.open_action.setText("打开连接")
        remote_ready = state in {"ready", "reading", "acquiring", "stopping"}
        self.tool_panel.csv_btn.setEnabled(remote_ready)
        self.scpi_action.setEnabled(remote_ready or state == "local")
        self.rmt_action.setEnabled(state not in {"opening", "stopping", "closing"})

        if state in {"disconnected", "error", "local"}:
            self.dmm_panel.clear()
            self.readout_panel.chips["Rmt"].set_state(False)
            self.status_identity.setText("")
            self._ohms_beeper.stop()
            if state != "local":
                self._needs_initial_config = False
        if state in {"ready", "reading", "acquiring", "stopping"}:
            self.readout_panel.chips["Rmt"].set_state(True)
            self.error_banner.hide()
        if state in {"ready", "local"} and self._pending_settings is not None:
            self._config.save_serial_settings(self._pending_settings)
            self._pending_settings = None
        if state == "ready" and self._needs_initial_config:
            self._needs_initial_config = False
            config = self._acquisition_config()
            self._config.save_acquisition_config(config)
            self.controller.configure(config)
            self.controller.set_display(self.display_action.isChecked())
            self.controller.set_beeper(self.beeper_action.isChecked())
        if state == "error":
            self._pending_settings = None
            if self._auto_open_failed:
                self._auto_open_failed = False
                self.status_state.setText(
                    "自动打开连接失败；请检查端口或 GPIB 地址后手动打开"
                )
        if state == "disconnected" and self._reopen_after_close:
            self._reopen_after_close = False
            QTimer.singleShot(0, lambda: self._open_connection(self._config.serial_settings()))

    def _on_identity(self, identity: str) -> None:
        self.status_identity.setText(identity)
        log.info("IDN：%s", identity)

    def _on_status(self, status: InstrumentStatus) -> None:
        self._last_status = status
        self.dmm_panel.set_status(status)
        self.readout_panel.set_status(status)
        self.tool_panel.set_function(status.function.label)
        self.trend_panel.set_function(status.function.label)
        self.trend_panel.set_unit(status.function.unit)

    def _on_reading(self, reading: Reading) -> None:
        self._single_count += 1
        self.dmm_panel.set_current_value(None if reading.ovld else reading.value)
        self.readout_panel.set_reading(reading)
        self.readout_panel.set_count(self._single_count)
        self._ohms_beeper.update_reading(reading)
        self.status_state.setText(f"单次读数：{reading.raw} {reading.unit}")
        if self._record_after_single:
            self._record_after_single = False
            self._record_reading(reading)

    def _on_batch(self, batch: Batch) -> None:
        if not batch.readings:
            return
        self.dmm_panel.set_current_value(
            None if batch.readings[-1].ovld else batch.readings[-1].value
        )
        self.readout_panel.push_batch(batch.readings)
        self.readout_panel.set_count(self.controller.sample_count)
        self.trend_panel.notify_data(batch)
        self._ohms_beeper.update_reading(batch.readings[-1])

    def _acquisition_config(self) -> AcquisitionConfig:
        return replace(
            self.dmm_panel.current_config(),
            average_enabled=self.tool_panel.average_enabled,
            average_count=self.tool_panel.average_count,
        )

    def _on_average_changed(self) -> None:
        self.readout_panel.set_extra_decimals(
            self.tool_panel.average_extra_decimals
        )
        if self._state in {"ready", "acquiring"}:
            self.controller.configure(self._acquisition_config())

    def _on_config_changed(self, config: AcquisitionConfig) -> None:
        config = replace(
            config,
            average_enabled=self.tool_panel.average_enabled,
            average_count=self.tool_panel.average_count,
        )
        self._config.save_acquisition_config(config)
        self.readout_panel.set_digits(config.digits)
        self.readout_panel.set_flags(config.az, config.null_enabled)
        self.readout_panel.set_range_mode(config.range_mode != "manual")
        self.controller.configure(config)

    def _on_plan_updated(self, plan) -> None:
        if plan is not None and getattr(plan, "effective", 0):
            interval_ms = 1000.0 / plan.effective
            self.readout_panel.set_display_interval_ms(interval_ms)
            self.trend_panel.set_display_interval_ms(interval_ms)

    def _on_unit_mode_changed(self, mode: str) -> None:
        self.readout_panel.set_unit_mode(mode)
        self._config.save_unit_mode(self.dmm_panel.unit_base, mode)

    def _on_ac_band_changed(self, band: str) -> None:
        self.readout_panel.set_ac_band(band)
        self._config.save_ac_band(band)

    def _on_tier_changed(self, tier: str) -> None:
        self._config.save_accuracy_tier(tier)

    def _on_display_action(self, on: bool) -> None:
        self._config.save_instrument_switches(
            on,
            self.beeper_action.isChecked(),
        )
        if self._state in {"ready", "reading", "acquiring", "stopping"}:
            self.controller.set_display(on)

    def _on_beeper_action(self, on: bool) -> None:
        self._config.save_instrument_switches(
            self.display_action.isChecked(),
            on,
        )
        if self._state in {"ready", "reading", "acquiring", "stopping"}:
            self.controller.set_beeper(on)

    def _apply_ohms_beeper_settings(self) -> None:
        self._ohms_beeper.set_settings(
            self.tool_panel.beep_enabled,
            self.tool_panel.beep_threshold,
            self.tool_panel.beep_volume,
        )

    def _change_csv_directory(self) -> None:
        start = str(self._config.csv_directory())
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 CSV 存储位置",
            start,
        )
        if not folder:
            return
        self._config.save_csv_directory(folder)
        self.statusBar().showMessage(f"CSV 存储位置：{folder}", 5000)

    def _on_csv_state(self, recording: bool, path: str) -> None:
        if recording:
            self.statusBar().showMessage(
                f"CSV 记录中：{Path(path).name}", 5000
            )

    def _open_csv_folder(self) -> None:
        folder = self._config.csv_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "打开 CSV 文件夹失败", str(exc))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
            QMessageBox.warning(
                self,
                "打开 CSV 文件夹失败",
                f"无法打开文件夹：\n{folder}",
            )

    def _setup_shortcuts(self) -> None:
        self._space_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Space), self)
        self._space_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._space_shortcut.activated.connect(self._space_pressed)
        self._enter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Return), self)
        self._enter_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._enter_shortcut.activated.connect(self._enter_pressed)
        self._numpad_enter_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Enter), self)
        self._numpad_enter_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
        self._numpad_enter_shortcut.activated.connect(self._enter_pressed)

    def _text_editing_active(self) -> bool:
        focus = QApplication.focusWidget()
        if isinstance(
            focus,
            (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox),
        ):
            return True
        combo = getattr(focus, "isEditable", None)
        return bool(combo and focus.isEditable())

    def _space_pressed(self) -> None:
        if self._text_editing_active():
            return
        if self._state in {"ready", "acquiring"}:
            self._toggle_acquisition()

    def _enter_pressed(self) -> None:
        if self._text_editing_active():
            return
        if self.trend_panel.record_view_active:
            self._handle_record_request()

    def _record_parameter_text(self) -> str:
        config = self.dmm_panel.current_config()
        status = self._last_status
        if status is not None:
            label = status.function.label
            unit = status.function.unit
            range_text = status.range_text
        else:
            spec = function_spec(config.function)
            label = spec.label
            unit = spec.unit
            range_text = ""
        label = {
            "VDC": "DCV",
            "VAC": "ACV",
            "IDC": "DCI",
            "IAC": "ACI",
        }.get(label, label)
        if config.range_mode == "auto":
            if not range_text or range_text.upper() == "AUTO":
                range_label = "AUTO"
            else:
                range_label = format_range(range_text, unit).replace(" ", "")
        else:
            range_label = format_range(f"{config.range_value:g}", unit).replace(
                " ", ""
            )
        parameter = f"{label} {range_label} {config.nplc:g}NPLC"
        if self.tool_panel.average_enabled:
            parameter += f"×{self.tool_panel.average_count}AVG"
        return parameter

    def _handle_record_request(self) -> None:
        if self._state == "ready":
            self._record_after_single = True
            self.controller.single_read()
            return
        self._record_current_value()

    def _record_reading(self, reading: Reading) -> None:
        text, unit = self.readout_panel.display_text_for(reading)
        if not text:
            return
        self.trend_panel.add_record(
            f"{text} {unit}".strip(), self._record_parameter_text()
        )

    def _record_current_value(self) -> None:
        text, unit = self.readout_panel.current_display_text()
        if not text:
            return
        self.trend_panel.add_record(
            f"{text} {unit}".strip(), self._record_parameter_text()
        )

    def _set_left_visible(self, visible: bool) -> None:
        size = self._splitter.width()
        right = self.dmm_panel.width() or 350
        if visible:
            self.tool_panel.setVisible(True)
            self._splitter.setSizes([230, max(1, size - 230 - right), right])
        else:
            self.tool_panel.setVisible(False)
            self._splitter.setSizes([0, max(1, size - right), right])

    def _toggle_floating_window(self) -> None:
        if (
            self._floating_window is not None
            and self._floating_window.isVisible()
        ):
            self._floating_window.hide()
            self.tool_panel.set_floating_active(False)
            if self._floating_minimized_main:
                self._floating_minimized_main = False
                self.showNormal()
                self.raise_()
                self.activateWindow()
            return
        if self._floating_window is None:
            self._floating_window = FloatingWindow(
                self.readout_panel,
                self.tool_panel.floating_percent,
                None,
            )
            self._floating_window.command_requested.connect(
                self._on_floating_command
            )
            self._floating_window.set_read_active(self._read_active)
            screen = self.screen().availableGeometry()
            self._floating_window.move(
                screen.right() - self._floating_window.width() - 24,
                screen.top() + 24,
            )
        self._floating_window.apply_percent(self.tool_panel.floating_percent)
        self._floating_window.set_opacity_percent(
            self.tool_panel.floating_opacity
        )
        self._floating_window.show()
        self._floating_window.raise_()
        self.tool_panel.set_floating_active(True)
        if self.tool_panel.floating_minimize:
            self._floating_minimized_main = True
            self.showMinimized()

    def _on_read_activity(self, active: bool) -> None:
        self._read_active = active
        if self._floating_window is not None:
            self._floating_window.set_read_active(active)

    def _on_floating_command(self, command: str) -> None:
        if command == "BACK":
            if self.isMinimized():
                self.showNormal()
            self.raise_()
            self.activateWindow()
            return
        if command == "NPLC":
            if not self.dmm_panel.toggle_nplc_1_10():
                self.statusBar().showMessage(
                    "当前功能不支持 NPLC", 3000
                )
            return
        if self.dmm_panel.select_function_raw(command):
            self.statusBar().showMessage(
                f"悬浮窗切换功能：{self.dmm_panel.current_config().function}",
                3000,
            )

    def _apply_floating_options(self) -> None:
        self._config.save_floating_settings(
            self.tool_panel.floating_percent,
            self.tool_panel.floating_opacity,
        )
        if self._floating_window is not None:
            self._floating_window.apply_percent(
                self.tool_panel.floating_percent
            )
            self._floating_window.set_opacity_percent(
                self.tool_panel.floating_opacity
            )

    def _open_error_codes(self) -> None:
        if (
            self._error_code_dialog is None
            or not self._error_code_dialog.isVisible()
        ):
            self._error_code_dialog = ErrorCodeDialog(self)
        self._error_code_dialog.show()
        self._error_code_dialog.raise_()
        self._error_code_dialog.activateWindow()

    def _open_software_log(self) -> None:
        if (
            self._software_log_dialog is None
            or not self._software_log_dialog.isVisible()
        ):
            self._software_log_dialog = SoftwareLogDialog(self)
        self._software_log_dialog.show()
        self._software_log_dialog.raise_()
        self._software_log_dialog.activateWindow()

    def _open_serial_log(self) -> None:
        if (
            self._serial_log_dialog is None
            or not self._serial_log_dialog.isVisible()
        ):
            self._serial_log_dialog = SerialLogDialog(self)
        self._serial_log_dialog.show()
        self._serial_log_dialog.raise_()
        self._serial_log_dialog.activateWindow()

    def _open_scpi(self) -> None:
        if self._scpi_dialog is None:
            self._scpi_dialog = ScpiDialog(self)
            self._scpi_dialog.send_requested.connect(self.controller.send_scpi)
            self.controller.scpi_result.connect(self._scpi_dialog.append_result)
        if self._state == "local":
            self._scpi_dialog.setWindowTitle(
                "SCPI 终端（RMT 关闭：手动发送会控制仪器）"
            )
        else:
            self._scpi_dialog.setWindowTitle("SCPI 终端")
        self._scpi_dialog.show()
        self._scpi_dialog.raise_()
        self._scpi_dialog.activateWindow()

    def _on_error(self, title: str, detail: str) -> None:
        self._record_after_single = False
        if self._auto_open_pending:
            self._auto_open_pending = False
            self._auto_open_failed = True
            log.warning("启动自动打开连接失败：%s：%s", title, detail)
            self.error_banner.hide()
            self.status_state.setText(
                "自动打开连接失败；请检查端口或 GPIB 地址后手动打开"
            )
            return
        log.error("%s：%s", title, detail)
        self.error_banner.show_error(title, detail)
        self.status_state.setText(f"{title}：{detail}")

    def _on_notice(self, text: str) -> None:
        self.statusBar().showMessage(text, 4000)

    def _request_single_read(self) -> None:
        if self._state == "ready":
            self.controller.single_read()

    def _clear_data(self) -> None:
        self.controller.clear_data()
        self.readout_panel.set_count(0)
        self.readout_panel.set_rate(None)
        self.trend_panel.clear_view()

    def _save_records(self) -> None:
        records = self.trend_panel.records()
        if not records:
            QMessageBox.information(self, "保存记录", "记录列表为空。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存记录列表",
            str(self._config.last_save_dir()) + "/34401A_记录列表.csv",
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["序号", "时间", "读数", "备注", "参数"])
                for index, (time_text, value, note, parameter) in enumerate(
                    records, 1
                ):
                    writer.writerow([index, time_text, value, note, parameter])
            self._config.save_last_save_dir(str(Path(path).parent))
        except Exception as exc:
            QMessageBox.warning(self, "保存记录失败", str(exc))
            return
        self.statusBar().showMessage(f"记录已保存：{path}", 5000)

    def _save_as(self) -> None:
        if len(self.controller.ring) == 0:
            QMessageBox.information(self, "另存为", "当前缓冲没有数据。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "另存当前数据",
            str(self._config.last_save_dir()) + "/34401A_缓冲导出.csv",
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            self.controller.save_snapshot(path)
            self._config.save_last_save_dir(str(Path(path).parent))
        except Exception as exc:
            QMessageBox.warning(self, "另存为失败", str(exc))
            return
        self.statusBar().showMessage(f"已另存：{path}", 5000)

    def _toggle_acquisition(self) -> None:
        if self._state == "ready":
            self.readout_panel.reset_for_new_run()
            self.readout_panel.set_count(0)
            self.readout_panel.set_rate(None)
            self.controller.start_acquisition(self._acquisition_config())
        elif self._state == "acquiring":
            self.controller.stop_acquisition()
            self.readout_panel.start_btn.setText("正在停止…")
            self.readout_panel.start_btn.setEnabled(False)

    def _set_scale_factor(self, percent: int) -> None:
        self._config.save_scale_factor(percent)
        os.environ["QT_SCALE_FACTOR"] = f"{percent / 100:g}"
        answer = QMessageBox.question(
            self,
            "界面缩放",
            f"已设置为 {percent}%。\nQT_SCALE_FACTOR 需要重启程序才能生效。\n\n现在重启吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            ok = QProcess.startDetached(
                sys.executable,
                sys.argv,
                str(Path.cwd()),
            )
            if not ok:
                QMessageBox.warning(self, "重启失败", "请手动关闭后重新启动程序。")
                return
            QTimer.singleShot(150, self.close)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt 命名
        if self._closing:
            event.accept()
            return
        self._closing = True
        self._ohms_beeper.stop()
        if self._floating_window is not None:
            self._floating_window.close()

        # 采集中关窗口时，先让当前批次走完/发到 UI/写入 CSV，
        # 再关闭 I/O 线程；否则最后一批会卡在跨线程队列里。
        if self._state in {"acquiring", "stopping"}:
            self.controller.stop_acquisition()
            loop = QEventLoop(self)
            timer = QTimer(self)
            timer.setSingleShot(True)

            def on_state(state: str, _detail: str) -> None:
                if state in {"ready", "error", "disconnected"}:
                    loop.quit()

            self.controller.state_changed.connect(on_state)
            timer.timeout.connect(loop.quit)
            timer.start(3000)
            loop.exec()
            self.controller.state_changed.disconnect(on_state)
            timer.stop()

        self._config.save_window_geometry(self.saveGeometry())
        self.controller.shutdown()
        event.accept()
