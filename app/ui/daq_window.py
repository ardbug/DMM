"""34970A 单通道窗口。"""

from __future__ import annotations

import os
import csv
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QIcon,
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.common import ErrorBanner

from app.acquisition.daq_worker import DaqWorker
from app.acquisition.ring_buffer import RingBuffer

from app.config import AppConfig
from app.domain.functions import nplc_to_digits
from app.domain.models import (
    AcquisitionConfig,
    Batch,
    Reading,
    SerialSettings,
)
from app.domain.statistics import StatsAccumulator
from app.instrument.daq34970a import DaqConfig, parse_channels
from app.storage.csv_writer import CsvQueueFull, CsvWriter, make_csv_path
from app.ui.dialogs.error_code_dialog import ErrorCodeDialog
from app.ui.dialogs.log_dialogs import SerialLogDialog, SoftwareLogDialog
from app.ui.dialogs.scpi_dialog import ScpiDialog
from app.ui.sections.daq_panel import DaqConnectionPanel, DaqParamsPanel
from app.ui.sections.readout_panel import ReadoutPanel
from app.ui.sections.trend_panel import TrendPanel
from app.ui.widgets.multi_trend import MultiChannelTrend
from app.ui.widgets.widget_inspector import WidgetInspector


class DaqWindow(QMainWindow):
    def __init__(self, config: AppConfig, instance: int = 1) -> None:
        super().__init__()
        self._config = config
        self._instance = instance
        self._state = "disconnected"
        self._single_ring = RingBuffer()
        self._single_stats = StatsAccumulator()
        self._channel_rings: dict[int, RingBuffer] = {}
        self._connect_settings: SerialSettings | None = None
        self._scpi_dialog: ScpiDialog | None = None
        self._error_code_dialog: ErrorCodeDialog | None = None
        self._software_log_dialog: SoftwareLogDialog | None = None
        self._serial_log_dialog: SerialLogDialog | None = None

        self._worker = DaqWorker()
        self._csv: CsvWriter | None = None
        self._csv_path: Path | None = None
        self._last_config: DaqConfig | None = None
        self._batch_id = 0
        self._scan_rows: dict[int, int] = {}
        self._active_channels: set[int] = {1}
        self._reading_count = 0
        self._rate_started_ns = 0

        title = "34970A 上位机"
        if instance > 1:
            title += f" · 实例 {instance}"
        self.setWindowTitle(title)
        icon_path = Path(__file__).resolve().parents[2] / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self._apply_window_scale(self._config.daq_window_percent())

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        self.error_banner = ErrorBanner(central)
        outer.addWidget(self.error_banner)
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        outer.addWidget(splitter, 1)
        self.panel = DaqConnectionPanel(config, splitter)
        self.params = DaqParamsPanel(config, splitter)
        center = QSplitter(Qt.Orientation.Vertical, splitter)
        self.readout = ReadoutPanel(center)
        self.readout.set_digits(nplc_to_digits(1.0))
        self.readout.set_daq_mode(True, 1.0)
        self.readout.set_daq_channels(1)
        self.trend_tab = QWidget(center)
        trend_layout = QVBoxLayout(self.trend_tab)
        trend_layout.setContentsMargins(0, 0, 0, 0)
        trend_layout.setSpacing(0)
        self.trend_stack = QStackedWidget(self.trend_tab)
        trend_layout.addWidget(self.trend_stack)
        self.single_trend = TrendPanel(self._single_ring, self.trend_stack)
        self.trend_stack.addWidget(self.single_trend)
        self.multi_page = QWidget(self.trend_stack)
        multi_layout = QVBoxLayout(self.multi_page)
        multi_layout.setContentsMargins(0, 0, 0, 0)
        multi_layout.setSpacing(4)
        self.trend_stack.addWidget(self.multi_page)
        self.trend = MultiChannelTrend(self.multi_page)
        trend_title = QLabel("实时趋势", self.multi_page)
        trend_title.setObjectName("SectionTitle")
        multi_layout.addWidget(trend_title)
        trend_controls = QHBoxLayout()
        self.window_combo = QComboBox(self.multi_page)
        for label, value in (
            ("PX 模式", "px"),
            ("5 s", 5.0),
            ("10 s", 10.0),
            ("30 s", 30.0),
            ("1 min", 60.0),
            ("ALL TIME", "all"),
        ):
            self.window_combo.addItem(label, value)
        self.window_combo.currentIndexChanged.connect(
            lambda: self.trend.set_window_mode(
                self.window_combo.currentData()
            )
        )
        self.ovld_check = QCheckBox("OVLD 入图", self.multi_page)
        self.ovld_check.toggled.connect(self.trend.set_include_ovld)
        self.pause_btn = QPushButton("暂停", self.multi_page)
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)
        self.clear_btn = QPushButton("清空", self.multi_page)
        self.clear_btn.clicked.connect(self.trend.clear)
        self.save_trend_btn = QPushButton("另存为", self.multi_page)
        self.save_trend_btn.clicked.connect(self._save_trend)
        for widget in (
            self.window_combo,
            self.ovld_check,
            self.pause_btn,
            self.clear_btn,
            self.save_trend_btn,
        ):
            trend_controls.addWidget(widget)
        trend_controls.addStretch(1)
        multi_layout.addLayout(trend_controls)
        stats_title = QLabel("会话统计", self.multi_page)
        stats_title.setObjectName("Muted")
        multi_layout.addWidget(stats_title)
        stats_grid = QGridLayout()
        stats_grid.setHorizontalSpacing(10)
        stats_grid.setVerticalSpacing(2)
        self.trend_stats: dict[str, QLabel] = {}
        for index, (key, caption) in enumerate(
            (
                ("min", "最小值"),
                ("avg", "平均值"),
                ("max", "最大值"),
                ("cv", "离散系数"),
                ("pp", "峰峰值"),
                ("std", "标准差"),
                ("count", "采样数"),
                ("duration_s", "采样时间"),
            )
        ):
            label = QLabel(f"{caption}：-", self.multi_page)
            label.setObjectName("Muted")
            label.setStyleSheet("font-size: 11px;")
            label.setMinimumWidth(0)
            stats_grid.addWidget(label, index // 4, index % 4)
            self.trend_stats[key] = label
        multi_layout.addLayout(stats_grid)
        multi_layout.addWidget(self.trend, 1)
        self.trend.stats_changed.connect(self._update_trend_stats)
        self.readout.resolution_changed.connect(
            self.single_trend.set_min_y_step
        )
        self.single_trend.clear_requested.connect(self._clear_single_trend)
        self.single_trend.save_requested.connect(self._save_single_trend)
        self.single_trend.record_requested.connect(self._record_single_trend)
        self.output_tabs = QTabWidget(center)
        self.output_tabs.addTab(self.trend_tab, "趋势")
        self.output_tabs.addTab(self.single_trend.record_page, "记录列表")
        self.scan_table = QTableWidget(0, 5, self.output_tabs)
        self.scan_table.setHorizontalHeaderLabels(
            ["通道", "功能", "读数", "单位", "时间"]
        )
        self.scan_table.verticalHeader().setVisible(False)
        self.scan_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self.scan_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.output_tabs.addTab(self.scan_table, "扫描表")
        self.output_tabs.currentChanged.connect(self._on_output_tab_changed)
        center.addWidget(self.readout)
        center.addWidget(self.output_tabs)
        center.setStretchFactor(0, 35)
        center.setStretchFactor(1, 65)
        splitter.addWidget(self.panel)
        splitter.addWidget(center)
        splitter.addWidget(self.params)
        splitter.setSizes([260, 650, 290])
        self.setCentralWidget(central)
        self._splitter = splitter
        self.status_state = QLabel("34970A 未连接", self)
        self.status_identity = QLabel("", self)
        self.statusBar().addWidget(self.status_state)
        self.statusBar().addPermanentWidget(self.status_identity)
        self.inspect_label = QLabel("", self)
        self.inspect_label.setObjectName("Muted")
        self.inspect_label.setMaximumWidth(720)
        self.inspect_label.hide()
        self.statusBar().addPermanentWidget(self.inspect_label)
        self.widget_inspector = WidgetInspector(
            self._show_widget_details, self
        )
        self.inspect_copy_shortcut = QShortcut(
            QKeySequence.StandardKey.Copy, self
        )
        self.inspect_copy_shortcut.setEnabled(False)
        self.inspect_copy_shortcut.activated.connect(
            self._copy_widget_details
        )

        file_menu = self.menuBar().addMenu("文件(&F)")
        location_action = QAction("更改 CSV 存储位置...", self)
        location_action.triggered.connect(self._change_csv_directory)
        file_menu.addAction(location_action)
        file_menu.addSeparator()
        quit_action = QAction("退出", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        window_menu = self.menuBar().addMenu("窗口(&W)")
        action_34401 = QAction("新开 34401A 窗口", self)
        action_34401.triggered.connect(
            lambda: self._open_new_instance("34401A")
        )
        action_34970 = QAction("新开 34970A 窗口", self)
        action_34970.triggered.connect(
            lambda: self._open_new_instance("34970A")
        )
        window_menu.addAction(action_34401)
        window_menu.addAction(action_34970)

        view_menu = self.menuBar().addMenu("视图(&V)")
        interface_menu = view_menu.addMenu("界面缩放")
        self.interface_group = QActionGroup(self)
        self.interface_group.setExclusive(True)
        current_interface_scale = self._config.scale_factor()
        for percent in (75, 100, 125, 150, 200):
            action = QAction(f"{percent}%", self)
            action.setCheckable(True)
            action.setChecked(percent == current_interface_scale)
            action.triggered.connect(
                lambda _checked=False, value=percent:
                self._set_interface_scale(value)
            )
            self.interface_group.addAction(action)
            interface_menu.addAction(action)

        size_menu = view_menu.addMenu("尺寸缩放")
        self.size_group = QActionGroup(self)
        self.size_group.setExclusive(True)
        current_window_scale = self._config.daq_window_percent()
        for percent in (75, 100, 125, 150, 200):
            action = QAction(f"{percent}%", self)
            action.setCheckable(True)
            action.setChecked(percent == current_window_scale)
            action.triggered.connect(
                lambda _checked=False, value=percent:
                self._apply_saved_window_scale(value)
            )
            self.size_group.addAction(action)
            size_menu.addAction(action)

        width_menu = view_menu.addMenu("曲线粗细")
        self.line_width_group = QActionGroup(self)
        self.line_width_group.setExclusive(True)
        for width in (1.0, 1.5, 2.0):
            action = QAction(f"{width:g} px", self)
            action.setCheckable(True)
            action.setChecked(width == 2.0)
            action.triggered.connect(
                lambda _checked=False, value=width:
                self.single_trend.chart.set_line_width(value)
            )
            self.line_width_group.addAction(action)
            width_menu.addAction(action)

        tools_menu = self.menuBar().addMenu("工具(&T)")
        scpi_action = QAction("SCPI 终端...", self)
        scpi_action.triggered.connect(self._open_scpi)
        tools_menu.addAction(scpi_action)
        error_action = QAction("错误码查询...", self)
        error_action.triggered.connect(self._open_error_codes)
        tools_menu.addAction(error_action)
        logs_menu = tools_menu.addMenu("日志")
        software_log_action = QAction("软件日志", self)
        software_log_action.triggered.connect(self._open_software_log)
        logs_menu.addAction(software_log_action)
        serial_log_action = QAction("串口日志", self)
        serial_log_action.triggered.connect(self._open_serial_log)
        logs_menu.addAction(serial_log_action)
        tools_menu.addSeparator()
        self.inspect_action = QAction("调试：显示控件名称", self)
        self.inspect_action.setCheckable(True)
        self.inspect_action.setShortcut(QKeySequence("Ctrl+Shift+I"))
        self.inspect_action.toggled.connect(
            self._toggle_widget_inspector
        )
        tools_menu.addAction(self.inspect_action)

        comm_menu = self.menuBar().addMenu("通信(&C)")
        settings_action = QAction("连接设置...", self)
        settings_action.triggered.connect(self.panel._edit_settings)
        comm_menu.addAction(settings_action)
        self.comm_open_action = QAction("打开连接", self)
        self.comm_open_action.triggered.connect(self._toggle_connection)
        comm_menu.addAction(self.comm_open_action)

        instrument_menu = self.menuBar().addMenu("仪器控制(&I)")
        self.rmt_action = QAction("RMT 远程控制", self)
        self.rmt_action.setCheckable(True)
        self.rmt_action.setChecked(self._config.remote_enabled())
        self.rmt_action.toggled.connect(self._on_rmt)
        instrument_menu.addAction(self.rmt_action)
        self.display_action = QAction("VFD 显示", self)
        self.display_action.setCheckable(True)
        self.display_action.setChecked(
            self._config.instrument_switches()[0]
        )
        self.display_action.toggled.connect(self._on_display)
        instrument_menu.addAction(self.display_action)
        self.beeper_action = QAction("蜂鸣器", self)
        self.beeper_action.setCheckable(True)
        self.beeper_action.setChecked(
            self._config.instrument_switches()[1]
        )
        self.beeper_action.toggled.connect(self._on_beeper)
        instrument_menu.addAction(self.beeper_action)

        self.panel.open_requested.connect(self._open)
        self.panel.close_requested.connect(self._close)
        self.params.config_changed.connect(self._on_config_changed)
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(250)
        self._config_timer.timeout.connect(self._apply_live_config)
        self.readout.start_stop_requested.connect(
            lambda: self._start(self.params.config())
        )
        self.readout.single_read_requested.connect(
            lambda: self._single(self.params.config())
        )
        self.panel.csv_toggle_requested.connect(self._toggle_csv)
        self.panel.open_csv_folder_requested.connect(self._open_csv_folder)
        self._worker.reading_received.connect(self._on_reading)
        self._worker.scan_received.connect(self._on_scan)
        self._worker.scpi_result.connect(self._on_scpi_result)
        self._worker.state_changed.connect(self._on_state)
        self._worker.identity_ready.connect(self._on_identity)
        self._worker.status_updated.connect(self.readout.set_status)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
        self._set_state("disconnected", "34970A 未连接")
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_trend)
        self._timer.start()

    def _toggle_connection(self) -> None:
        if self._state in {"ready", "acquiring", "stopping", "opening"}:
            self._close()
        else:
            self._open(self.panel.settings())

    def _on_identity(self, identity: str) -> None:
        resource = ""
        if self._connect_settings is not None:
            resource = self._connect_settings.resource
            upper = resource.upper()
            if upper.startswith("ASRL"):
                digits = "".join(ch for ch in resource if ch.isdigit())
                resource = f"COM{digits}"
            elif upper.startswith("GPIB"):
                parts = upper.replace("::", ",").split(",")
                if len(parts) >= 2 and parts[0].startswith("GPIB"):
                    resource = f"{parts[0]},{parts[1]}"
                else:
                    resource = upper
        text = f"{identity} on {resource}" if resource else identity
        self.status_identity.setText(text)

    def _change_csv_directory(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "选择 CSV 存储位置",
            str(self._config.csv_directory()),
        )
        if not folder:
            return
        self._config.save_csv_directory(folder)
        self.statusBar().showMessage(f"CSV 存储位置：{folder}", 5000)

    def _open_scpi(self) -> None:
        if self._scpi_dialog is None:
            self._scpi_dialog = ScpiDialog(self)
            self._scpi_dialog.send_requested.connect(self._send_scpi)
        self._scpi_dialog.show()
        self._scpi_dialog.raise_()
        self._scpi_dialog.activateWindow()

    def _send_scpi(self, command: str) -> None:
        if self._state not in {"ready", "acquiring"}:
            self._on_error("SCPI", "请先打开 34970A 连接")
            return
        self._worker.submit("scpi", command)

    def _on_scpi_result(self, command: str, response: str) -> None:
        if self._scpi_dialog is not None:
            self._scpi_dialog.append_result(command, response)

    def _show_widget_details(self, text: str) -> None:
        self.inspect_label.setText(text)
        self.inspect_label.setToolTip(text)

    def _copy_widget_details(self) -> None:
        text = self.widget_inspector.current_text or self.inspect_label.text()
        if not text:
            self.statusBar().showMessage("没有可复制的控件名称", 1500)
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("已复制控件名称", 1500)

    def _toggle_widget_inspector(self, enabled: bool) -> None:
        self.inspect_label.setVisible(enabled)
        self.widget_inspector.set_enabled(enabled)
        self.inspect_copy_shortcut.setEnabled(enabled)
        if not enabled:
            self.inspect_label.clear()

    def _open_error_codes(self) -> None:
        if (
            self._error_code_dialog is None
            or not self._error_code_dialog.isVisible()
        ):
            self._error_code_dialog = ErrorCodeDialog(
                self, model="34970A"
            )
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

    def _apply_window_scale(self, percent: int) -> None:
        self.resize(
            max(600, round(1200 * percent / 100)),
            max(400, round(820 * percent / 100)),
        )

    def _apply_saved_window_scale(self, percent: int) -> None:
        self._config.save_daq_window_percent(percent)
        self._apply_window_scale(percent)

    def _set_interface_scale(self, percent: int) -> None:
        self._config.save_scale_factor(percent)
        os.environ["QT_SCALE_FACTOR"] = f"{percent / 100:g}"
        answer = QMessageBox.question(
            self,
            "界面缩放",
            f"已设置为 {percent}%。\n需要重启程序才能生效。\n\n现在重启吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        ok = QProcess.startDetached(
            sys.executable,
            sys.argv,
            str(Path.cwd()),
        )
        if not ok:
            QMessageBox.warning(self, "重启失败", "请手动重启程序。")
            return
        QTimer.singleShot(150, self.close)

    def _on_rmt(self, enabled: bool) -> None:
        self._config.save_remote_enabled(enabled)
        if self._state in {"ready", "acquiring"}:
            self._worker.submit("remote", enabled)

    def _on_display(self, enabled: bool) -> None:
        self._config.save_instrument_switches(
            enabled, self.beeper_action.isChecked()
        )
        if self._state in {"ready", "acquiring"}:
            self._worker.submit("display", enabled)

    def _on_beeper(self, enabled: bool) -> None:
        self._config.save_instrument_switches(
            self.display_action.isChecked(), enabled
        )
        if self._state in {"ready", "acquiring"}:
            self._worker.submit("beeper", enabled)

    def _open(self, settings: SerialSettings) -> None:
        self._connect_settings = settings
        self._config.save_serial_settings(settings)
        self._worker.submit("open", settings)

    def _open_new_instance(self, model: str) -> None:
        main_py = Path(__file__).resolve().parents[2] / "main.py"
        ok = QProcess.startDetached(
            sys.executable,
            [str(main_py), "--model", model],
            str(main_py.parent),
        )
        if not ok:
            QMessageBox.warning(self, "新开窗口失败", "无法启动新实例")

    def _close(self) -> None:
        if self._state == "opening":
            self.panel.status.setText("正在取消打开连接…")
            self.panel.close_btn.setEnabled(False)
            self.comm_open_action.setText("正在取消…")
            self.comm_open_action.setEnabled(False)
        self._worker.submit("close")

    @staticmethod
    def _config_channels(config: DaqConfig) -> set[int]:
        if config.scan:
            try:
                return set(parse_channels(config.scan_list))
            except ValueError:
                return set()
        return {config.channel}

    def _reset_session(self, config: DaqConfig) -> None:
        self._reading_count = 0
        self._rate_started_ns = time.time_ns()
        self._active_channels = self._config_channels(config)
        self.readout.set_count(0)
        self.readout.set_rate(None)
        self.trend.clear()
        self._single_ring.clear()
        self._channel_rings.clear()
        self._single_stats.reset()
        self.single_trend.set_overlay_rings({}, None)
        self.single_trend.clear_view()
        self.single_trend.set_stats(self._single_stats.snapshot())
        self.single_trend.set_measurement_state("disconnected")
        self.scan_table.setRowCount(0)
        self._scan_rows.clear()
        self._select_trend_page(config)

    def _on_output_tab_changed(self, index: int) -> None:
        self.single_trend.set_record_view(
            self.output_tabs.widget(index) is self.single_trend.record_page
        )

    def _select_trend_page(self, config: DaqConfig) -> None:
        # 单通道和多通道都使用 34401A 的 TrendPanel；扫描只是多叠几条线。
        self.trend_stack.setCurrentWidget(self.single_trend)

    def _clear_single_trend(self) -> None:
        self._single_ring.clear()
        self._channel_rings.clear()
        self._single_stats.reset()
        self.single_trend.set_overlay_rings({}, None)
        self.single_trend.clear_view()
        self.single_trend.set_stats(self._single_stats.snapshot())
        self.readout.set_count(0)
        self._reading_count = 0

    def _save_single_trend(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "另存趋势数据",
            str(self._config.csv_directory() / "34970A_single_trend.csv"),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp_ns", "value", "ovld"])
                for value, timestamp_ns, ovld in self._single_ring.iter_ordered():
                    writer.writerow([timestamp_ns, f"{value:.15g}", int(ovld)])
        except Exception as exc:
            self._on_error("保存趋势失败", str(exc))

    def _record_single_trend(self) -> None:
        latest = self.readout._last_reading
        if latest is None:
            return
        self.single_trend.add_record(
            self.readout.display_text_for(latest),
            f"NPLC {self._last_config.nplc:g}" if self._last_config else "",
        )

    def _update_rate(self) -> None:
        if not self._rate_started_ns:
            return
        elapsed = (time.time_ns() - self._rate_started_ns) / 1e9
        if elapsed > 0.2:
            self.readout.set_rate(self._reading_count / elapsed)

    def _sync_readout_digits(self, nplc: float) -> None:
        self.readout.set_digits(nplc_to_digits(nplc))
        self.readout.set_daq_mode(True, nplc)

    def _start(self, config: DaqConfig) -> None:
        self._last_config = config
        self._sync_readout_digits(config.nplc)
        self.readout.set_daq_channels(self.params.selected_channel_count())
        if self._state == "acquiring":
            self._worker.submit("stop")
        else:
            self._reset_session(config)
            self.output_tabs.setCurrentWidget(self.trend_tab)
            self._worker.submit("start", config)

    def _on_config_changed(self) -> None:
        config = self.params.config()
        self._sync_readout_digits(config.nplc)
        self.readout.set_daq_channels(self.params.selected_channel_count())
        self._select_trend_page(config)
        channels = self._config_channels(config)
        if channels and channels != self._active_channels:
            # 切换通道或扫描模式时，旧曲线不能继续留在图上。
            self._active_channels = channels
            self._reading_count = 0
            self._rate_started_ns = time.time_ns()
            self.readout.set_count(0)
            self.readout.set_rate(None)
            self.trend.clear()
            self._single_ring.clear()
            self._channel_rings.clear()
            self._single_stats.reset()
            self.single_trend.set_overlay_rings({}, None)
            self.single_trend.clear_view()
            self.single_trend.set_stats(self._single_stats.snapshot())
            self.scan_table.setRowCount(0)
            self._scan_rows.clear()
        if self._state == "acquiring":
            self._config_timer.start()

    def _apply_live_config(self) -> None:
        if self._state != "acquiring":
            return
        config = self.params.config()
        self._last_config = config
        self._sync_readout_digits(config.nplc)
        self.readout.set_daq_channels(self.params.selected_channel_count())
        self._worker.submit("start", config)

    def _stop(self) -> None:
        self._worker.submit("stop")

    def _single(self, config: DaqConfig) -> None:
        self._last_config = config
        self._worker.submit("single", config)

    def _toggle_pause(self, paused: bool) -> None:
        self.trend.set_paused(paused)
        self.pause_btn.setText("继续" if paused else "暂停")

    def _update_trend_stats(self, stats) -> None:
        for key, label in self.trend_stats.items():
            if key not in stats:
                label.setText(f"{label.text().split('：')[0]}：-")
                continue
            value = stats[key]
            caption = label.text().split("：")[0]
            if key == "duration_s":
                seconds = int(value)
                text = (
                    f"{seconds // 3600:02d}:"
                    f"{seconds % 3600 // 60:02d}:"
                    f"{seconds % 60:02d}"
                )
            elif key == "count":
                text = str(value)
            else:
                text = f"{float(value):.6g}"
            label.setText(f"{caption}：{text}")

    def _save_trend(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "另存趋势数据",
            str(self._config.csv_directory() / "34970A_trend.csv"),
            "CSV 文件 (*.csv)",
        )
        if not path:
            return
        try:
            self.trend.save_csv(path)
        except Exception as exc:
            self._on_error("保存趋势失败", str(exc))

    def _on_reading(self, reading: Reading) -> None:
        self.readout.set_reading(reading)
        if self._last_config is not None and self._last_config.scan:
            return
        self._reading_count += 1
        self.readout.set_count(self._reading_count)
        self._update_rate()
        self._record_batch([reading])

    def _on_scan(self, samples) -> None:
        if not samples:
            return
        for channel, reading in samples:
            row = self._scan_rows.get(channel)
            if row is None:
                row = self.scan_table.rowCount()
                self.scan_table.insertRow(row)
                self._scan_rows[channel] = row
                self.scan_table.setItem(row, 0, QTableWidgetItem(str(channel)))
            self.scan_table.setItem(
                row, 1, QTableWidgetItem(reading.function_label)
            )
            self.scan_table.setItem(
                row, 2, QTableWidgetItem(f"{reading.value:.8g}")
            )
            self.scan_table.setItem(row, 3, QTableWidgetItem(reading.unit))
            self.scan_table.setItem(
                row,
                4,
                QTableWidgetItem(
                    datetime.fromtimestamp(
                        reading.timestamp_ns / 1_000_000_000
                    ).strftime("%H:%M:%S")
                ),
            )
        self.scan_table.scrollToBottom()
        self._reading_count += len(samples)
        self.readout.set_count(self._reading_count)
        self._update_rate()
        last = samples[-1][1]
        self.readout.set_reading(last)
        self._append_scan_trend(samples)
        self._record_batch(
            [
                replace(
                    reading,
                    function_label=f"CH{channel} {reading.function_label}",
                )
                for channel, reading in samples
            ]
        )

    def _append_scan_trend(self, samples) -> None:
        if not samples:
            return
        primary_channel = sorted(channel for channel, _ in samples)[0]
        primary_reading = None
        for channel, reading in samples:
            ring = self._channel_rings.setdefault(channel, RingBuffer())
            batch = self._make_batch([reading])
            ring.append_batch(batch)
            self._single_stats.add_batch((reading,))
            if channel == primary_channel:
                primary_reading = reading
        if primary_reading is None:
            return
        self.single_trend.set_function(primary_reading.function_label)
        self.single_trend.set_unit(primary_reading.unit)
        self.single_trend.set_measurement_state("acquiring")
        self.single_trend.notify_data(self._make_batch([primary_reading]))
        self.single_trend.set_overlay_rings(
            self._channel_rings, primary_channel
        )
        self.single_trend.set_stats(self._single_stats.snapshot())

    def _make_batch(self, readings: list[Reading]) -> Batch:
        first = readings[0]
        return Batch(
            readings=tuple(readings),
            config=AcquisitionConfig(
                function=first.function_label,
                nplc=(
                    float(self._last_config.nplc)
                    if self._last_config
                    else 1.0
                ),
                rate=(
                    float(self._last_config.rate)
                    if self._last_config
                    else 1.0
                ),
            ),
            config_version=1,
            batch_id=self._batch_id,
            start_ns=first.timestamp_ns,
            end_ns=readings[-1].timestamp_ns,
            range_text="AUTO",
        )

    def _record_batch(self, readings: list[Reading]) -> None:
        if not readings:
            return
        batch = self._make_batch(readings)
        self._batch_id += 1
        if self._last_config is None or not self._last_config.scan:
            first = batch.readings[0]
            self._single_ring.append_batch(batch)
            self._single_stats.add_batch(batch.readings)
            self.single_trend.set_function(first.function_label)
            self.single_trend.set_unit(first.unit)
            self.single_trend.notify_data(batch)
            self.single_trend.set_stats(self._single_stats.snapshot())
            self.single_trend.set_measurement_state("acquiring")
        if self._csv is not None:
            try:
                self._csv.enqueue(batch)
            except CsvQueueFull:
                self._on_error("CSV", "CSV 队列已满，已停止记录")
                self._toggle_csv()

    def _on_state(self, state: str, detail: str) -> None:
        self._state = state
        self.panel.set_state(state, detail)
        self.params.set_state(state)
        self.single_trend.set_measurement_state(state)
        self.readout.set_state(state, detail)

        self.statusBar().showMessage(detail)
        self.status_state.setText(detail or state)
        connected = state in {"ready", "acquiring", "stopping", "opening"}
        if not connected:
            self.status_identity.clear()
        self.comm_open_action.setText("关闭连接" if connected else "打开连接")

    def _on_error(self, title: str, detail: str) -> None:
        self.error_banner.show_error(title, detail)
        self.statusBar().showMessage(f"{title}：{detail}", 8000)

    def _refresh_trend(self) -> None:
        self.trend.update()

    def _toggle_csv(self) -> None:
        if self._csv is not None:
            self._csv.stop()
            self._csv = None
            self._csv_path = None
            self.panel.set_csv_state(False)
            return
        if self._last_config and self._last_config.scan:
            label = f"SCAN_{self._last_config.function.replace(':', '_')}"
        elif self._last_config:
            label = (
                f"CH{self._last_config.channel}_"
                f"{self._last_config.function.replace(':', '_')}"
            )
        else:
            label = "34970A"
        function = (
            self._last_config.function if self._last_config else "VOLT:DC"
        )
        token = {
            "VOLT:DC": "VDC",
            "VOLT:AC": "VAC",
            "CURR:DC": "DCI",
            "CURR:AC": "ACI",
            "RES": "OHM",
            "FRES": "OHM4",
            "FREQ": "FREQ",
            "PER": "PER",
            "TEMP": "TEMP",
        }.get(function, function.replace(":", "_"))
        path = make_csv_path(
            token,
            self._config.csv_directory(),
            model="34970a",
        )
        writer = CsvWriter(path, self)
        writer.opened.connect(
            lambda value: self.panel.set_csv_state(True, str(value))
        )
        writer.error.connect(
            lambda message: self._on_error("CSV", message)
        )
        self._csv = writer
        self._csv_path = path
        writer.start()
        self.panel.set_csv_state(True, str(path))

    def _open_csv_folder(self) -> None:
        dir_path = self._config.csv_directory()
        dir_path.mkdir(parents=True, exist_ok=True)
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dir_path)))

    def _set_state(self, state: str, detail: str) -> None:
        self._on_state(state, detail)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self._csv is not None:
            self._csv.stop()
        self._worker.shutdown()
        self._config.save_window_geometry(self.saveGeometry())
        event.accept()
