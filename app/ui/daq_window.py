"""34970A 单通道窗口。"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QProcess, QTimer, Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ui.widgets.common import ErrorBanner

from app.acquisition.daq_worker import DaqWorker
from app.acquisition.ring_buffer import RingBuffer
from app.config import AppConfig
from app.domain.models import (
    AcquisitionConfig,
    Batch,
    Reading,
    SerialSettings,
)
from app.instrument.daq34970a import DaqConfig
from app.storage.csv_writer import CsvQueueFull, CsvWriter, make_csv_path
from app.ui.sections.daq_panel import DaqPanel
from app.ui.sections.readout_panel import ReadoutPanel
from app.ui.sections.trend_panel import TrendPanel


class DaqWindow(QMainWindow):
    def __init__(self, config: AppConfig, instance: int = 1) -> None:
        super().__init__()
        self._config = config
        self._instance = instance
        self._state = "disconnected"
        self._ring = RingBuffer()
        self._worker = DaqWorker()
        self._csv: CsvWriter | None = None
        self._csv_path: Path | None = None
        self._last_config: DaqConfig | None = None
        self._batch_id = 0

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
        self.panel = DaqPanel(config, splitter)
        right = QSplitter(Qt.Orientation.Vertical, splitter)
        self.readout = ReadoutPanel(right)
        self.readout.set_daq_mode(True, 1.0)
        self.trend = TrendPanel(self._ring, right)
        right.addWidget(self.readout)
        right.addWidget(self.trend)
        right.setStretchFactor(0, 35)
        right.setStretchFactor(1, 65)
        splitter.addWidget(self.panel)
        splitter.addWidget(right)
        splitter.setSizes([280, 900])
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
        self.panel.start_requested.connect(self._start)
        self.panel.stop_requested.connect(self._stop)
        self.panel.single_requested.connect(self._single)
        self.panel.config_changed.connect(self._on_config_changed)
        self._config_timer = QTimer(self)
        self._config_timer.setSingleShot(True)
        self._config_timer.setInterval(250)
        self._config_timer.timeout.connect(self._apply_live_config)
        self.readout.start_stop_requested.connect(
            lambda: self._start(self.panel.config())
        )
        self.panel.csv_toggle_requested.connect(self._toggle_csv)
        self.panel.open_csv_folder_requested.connect(self._open_csv_folder)
        self._worker.reading_received.connect(self._on_reading)
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
        if self._state == "acquiring":
            self._worker.submit("stop")
        else:
            self._worker.submit("start", config)

    def _on_config_changed(self) -> None:
        config = self.panel.config()
        self.readout.set_daq_mode(True, config.nplc)
        if self._state == "acquiring":
            self._config_timer.start()

    def _apply_live_config(self) -> None:
        if self._state != "acquiring":
            return
        config = self.panel.config()
        self._last_config = config
        self.readout.set_daq_mode(True, config.nplc)
        self._worker.submit("start", config)

    def _stop(self) -> None:
        self._worker.submit("stop")

    def _single(self, config: DaqConfig) -> None:
        self._last_config = config
        self._worker.submit("single", config)

    def _on_reading(self, reading: Reading) -> None:
        self.readout.set_reading(reading)
        self.trend.set_function(reading.function_label)
        self.trend.set_unit(reading.unit)
        self.trend.set_measurement_state("acquiring")
        config = AcquisitionConfig(
            function=reading.function_label,
            rate=float(self._last_config.rate) if self._last_config else 1.0,
        )
        start = reading.timestamp_ns
        batch = Batch(
            readings=(reading,),
            config=config,
            config_version=1,
            batch_id=self._batch_id,
            start_ns=start,
            end_ns=start,
        )
        self._batch_id += 1
        self._ring.append_batch(batch)
        if self._csv is not None:
            try:
                self._csv.enqueue(batch)
            except CsvQueueFull:
                self._on_error("CSV", "CSV 队列已满，已停止记录")
                self._toggle_csv()

    def _on_state(self, state: str, detail: str) -> None:
        self._state = state
        self.panel.set_state(state, detail)
        self.readout.set_state(state, detail)
        self.trend.set_measurement_state(state)
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
        label = (
            f"CH{self._last_config.channel}_"
            f"{self._last_config.function.replace(':', '_')}"
            if self._last_config
            else "34970A"
        )
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
