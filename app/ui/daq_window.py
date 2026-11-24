"""34970A 单通道窗口。"""

from __future__ import annotations

import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
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
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.common import ErrorBanner

from app.acquisition.daq_worker import DaqWorker

from app.config import AppConfig
from app.domain.models import (
    AcquisitionConfig,
    Batch,
    Reading,
    SerialSettings,
)
from app.instrument.daq34970a import DaqConfig
from app.storage.csv_writer import CsvQueueFull, CsvWriter, make_csv_path
from app.ui.sections.daq_panel import DaqConnectionPanel, DaqParamsPanel
from app.ui.sections.readout_panel import ReadoutPanel
from app.ui.widgets.multi_trend import MultiChannelTrend


class DaqWindow(QMainWindow):
    def __init__(self, config: AppConfig, instance: int = 1) -> None:
        super().__init__()
        self._config = config
        self._instance = instance
        self._state = "disconnected"

        self._worker = DaqWorker()
        self._csv: CsvWriter | None = None
        self._csv_path: Path | None = None
        self._last_config: DaqConfig | None = None
        self._batch_id = 0
        self._scan_rows: dict[int, int] = {}

        title = "34970A 上位机"
        if instance > 1:
            title += f" · 实例 {instance}"
        self.setWindowTitle(title)
        icon_path = Path(__file__).resolve().parents[2] / "icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.resize(1200, 820)

        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(6)
        self.error_banner = ErrorBanner(central)
        outer.addWidget(self.error_banner)
        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        outer.addWidget(splitter, 1)
        self.panel = DaqConnectionPanel(config, splitter)
        self.params = DaqParamsPanel(splitter)
        center = QSplitter(Qt.Orientation.Vertical, splitter)
        self.readout = ReadoutPanel(center)
        self.readout.set_daq_mode(True, 1.0)
        self.readout.set_daq_channels(1)
        self.trend = MultiChannelTrend(center)
        self.trend_tab = QWidget(center)
        trend_layout = QVBoxLayout(self.trend_tab)
        trend_layout.setContentsMargins(0, 0, 0, 0)
        trend_layout.setSpacing(4)
        trend_controls = QHBoxLayout()
        self.window_combo = QComboBox(self.trend_tab)
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
        self.ovld_check = QCheckBox("OVLD 入图", self.trend_tab)
        self.ovld_check.toggled.connect(self.trend.set_include_ovld)
        self.pause_btn = QPushButton("暂停", self.trend_tab)
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self._toggle_pause)
        self.clear_btn = QPushButton("清空", self.trend_tab)
        self.clear_btn.clicked.connect(self.trend.clear)
        self.save_trend_btn = QPushButton("另存为", self.trend_tab)
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
        trend_layout.addLayout(trend_controls)
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
            label = QLabel(f"{caption}：-", self.trend_tab)
            label.setObjectName("Muted")
            label.setStyleSheet("font-size: 11px;")
            label.setMinimumWidth(0)
            stats_grid.addWidget(label, index // 4, index % 4)
            self.trend_stats[key] = label
        trend_layout.addLayout(stats_grid)
        trend_layout.addWidget(self.trend, 1)
        self.trend.stats_changed.connect(self._update_trend_stats)
        self.output_tabs = QTabWidget(center)
        self.output_tabs.addTab(self.trend_tab, "趋势")
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

        file_menu = self.menuBar().addMenu("文件(&F)")
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
        self._worker.state_changed.connect(self._on_state)
        self._worker.status_updated.connect(self.readout.set_status)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()
        self._set_state("disconnected", "34970A 未连接")
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh_trend)
        self._timer.start()

    def _open(self, settings: SerialSettings) -> None:
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
        self._worker.submit("close")

    def _start(self, config: DaqConfig) -> None:
        self._last_config = config
        self.readout.set_daq_mode(True, config.nplc)
        self.readout.set_daq_channels(self.params.selected_channel_count())
        if self._state == "acquiring":
            self._worker.submit("stop")
        else:
            self.trend.clear()
            if config.scan:
                self.scan_table.setRowCount(0)
                self._scan_rows.clear()
            self.output_tabs.setCurrentWidget(self.trend)
            self._worker.submit("start", config)

    def _on_config_changed(self) -> None:
        config = self.params.config()
        self.readout.set_daq_mode(True, config.nplc)
        self.readout.set_daq_channels(self.params.selected_channel_count())
        if self._state == "acquiring":
            self._config_timer.start()

    def _apply_live_config(self) -> None:
        if self._state != "acquiring":
            return
        config = self.params.config()
        self._last_config = config
        self.readout.set_daq_mode(True, config.nplc)
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
        channel = self._last_config.channel if self._last_config else 1
        self.trend.append_samples([(channel, reading)])
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
        self.trend.append_samples(samples)
        last = samples[-1][1]
        self.readout.set_reading(last)
        self.output_tabs.setCurrentWidget(self.trend)
        self._record_batch(
            [
                replace(
                    reading,
                    function_label=f"CH{channel} {reading.function_label}",
                )
                for channel, reading in samples
            ]
        )

    def _record_batch(self, readings: list[Reading]) -> None:
        if not readings:
            return
        first = readings[0]
        config = AcquisitionConfig(
            function=first.function_label,
            nplc=float(self._last_config.nplc) if self._last_config else 1.0,
            rate=float(self._last_config.rate) if self._last_config else 1.0,
        )
        batch = Batch(
            readings=tuple(readings),
            config=config,
            config_version=1,
            batch_id=self._batch_id,
            start_ns=first.timestamp_ns,
            end_ns=readings[-1].timestamp_ns,
        )
        self._batch_id += 1
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
        self.readout.set_state(state, detail)

        self.statusBar().showMessage(detail)

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
        path = make_csv_path(label, self._config.csv_directory())
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
