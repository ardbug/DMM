"""UI 与 I/O 线程、环形缓冲、CSV 写线程之间的协调者。"""

from __future__ import annotations

import logging
from collections import deque
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from app.acquisition.commands import (
    CloseCommand,
    ConfigureAcquisitionCommand,
    IdentifyCommand,
    ListResourcesCommand,
    OpenCommand,
    ScpiCommand,
    SetBeeperCommand,
    SetDisplayCommand,
    SingleReadCommand,
    StartAcquisitionCommand,
    StopAcquisitionCommand,
)
from app.acquisition.ring_buffer import RingBuffer
from app.acquisition.worker import AcqWorker
from app.config import AppConfig
from app.domain.models import AcquisitionConfig, Batch, InstrumentStatus, SerialSettings
from app.domain.statistics import StatsAccumulator
from app.storage.csv_writer import CsvQueueFull, CsvWriter, make_csv_path
from app.transport.visa_io import VisaIO

log = logging.getLogger(__name__)


class SessionController(QObject):
    state_changed = Signal(str, str)
    identity_received = Signal(str)
    status_updated = Signal(object)
    reading_received = Signal(object)
    batch_received = Signal(object)
    scpi_result = Signal(str, str)
    resources_listed = Signal(object)
    error_occurred = Signal(str, str)
    notice = Signal(str)
    config_applied = Signal(int, object)
    plan_updated = Signal(object)
    read_activity = Signal(bool)
    rate_updated = Signal(object)
    stats_updated = Signal(object)
    csv_state = Signal(bool, str)

    def __init__(self, config: AppConfig, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._shutdown = False
        self._state = "disconnected"
        self._was_acquiring = False
        self._count = 0
        self._status: InstrumentStatus | None = None
        self._rate_points: deque[tuple[int, int]] = deque()
        self.ring = RingBuffer()
        self.stats = StatsAccumulator()
        self._csv_writer: CsvWriter | None = None
        self._csv_path: Path | None = None

        self.worker = AcqWorker()
        self.worker.state_changed.connect(self._on_state)
        self.worker.identity_received.connect(self.identity_received.emit)
        self.worker.status_updated.connect(self._on_status)
        self.worker.reading_received.connect(self.reading_received.emit)
        self.worker.batch_received.connect(self._on_batch)
        self.worker.scpi_result.connect(self.scpi_result.emit)
        self.worker.resources_listed.connect(self.resources_listed.emit)
        self.worker.error_occurred.connect(self.error_occurred.emit)
        self.worker.notice.connect(self.notice.emit)
        self.worker.config_applied.connect(self.config_applied.emit)
        self.worker.plan_updated.connect(self.plan_updated.emit)
        self.worker.read_activity.connect(self.read_activity.emit)
        self.worker.start()

    # ---------- 连接/配置 ----------

    def open_connection(
        self,
        settings: SerialSettings,
        attempts: int = 5,
        handshake_timeout_ms: int = 1500,
        remote: bool = True,
    ) -> None:
        self.worker.submit(
            OpenCommand(
                settings,
                attempts=max(1, int(attempts)),
                handshake_timeout_ms=max(100, int(handshake_timeout_ms)),
                remote=bool(remote),
            )
        )

    def close_connection(self) -> None:
        self.worker.submit(CloseCommand())

    def identify(self) -> None:
        self.worker.submit(IdentifyCommand())

    def single_read(self) -> None:
        self.worker.submit(SingleReadCommand())

    def send_scpi(self, text: str) -> None:
        if self._state not in {"ready", "local"}:
            self.scpi_result.emit(text, "串口未就绪；采集期间请先停止采集")
            return
        self.worker.submit(ScpiCommand(text.strip()))

    def list_resources(self) -> None:
        self.worker.submit(ListResourcesCommand())

    def configure(self, config: AcquisitionConfig) -> None:
        if self._state in {"ready", "acquiring"}:
            self.worker.submit(ConfigureAcquisitionCommand(config))

    def set_display(self, on: bool) -> None:
        if self._state in {"ready", "acquiring"}:
            self.worker.submit(SetDisplayCommand(on))

    def set_beeper(self, on: bool) -> None:
        if self._state in {"ready", "acquiring"}:
            self.worker.submit(SetBeeperCommand(on))

    # ---------- 连续采集 ----------

    def start_acquisition(self, config: AcquisitionConfig) -> None:
        if self._state != "ready":
            return
        self._count = 0
        self._rate_points.clear()
        self._was_acquiring = True
        self.stats.reset()
        self.stats_updated.emit(self.stats.snapshot())
        self.rate_updated.emit(None)
        self.worker.submit(StartAcquisitionCommand(config))

    def stop_acquisition(self) -> None:
        self.worker.submit(StopAcquisitionCommand())

    # ---------- CSV ----------

    @property
    def is_recording(self) -> bool:
        return self._csv_writer is not None

    def toggle_csv(self) -> None:
        if self._csv_writer is not None:
            self.stop_csv()
        else:
            self.start_csv()

    def start_csv(self) -> None:
        if self._csv_writer is not None:
            return
        label = self._status.function.label if self._status else "DMM"
        try:
            path = make_csv_path(label, self._config.csv_directory())
            writer = CsvWriter(path, self)
        except Exception as exc:
            self.error_occurred.emit("无法开始 CSV", str(exc))
            return
        writer.error.connect(self._on_csv_error)
        writer.closed.connect(self._on_csv_closed)
        writer.opened.connect(lambda p: log.info("CSV 文件已打开：%s", p))
        self._csv_writer = writer
        self._csv_path = path
        writer.start()
        self.csv_state.emit(True, str(path))
        self.notice.emit(f"开始记录：{path.name}")

    def stop_csv(self) -> None:
        writer = self._csv_writer
        if writer is None:
            return
        self._csv_writer = None
        writer.stop()
        if not writer.wait(8000):
            self.error_occurred.emit("CSV 停止超时", "写入线程未能及时退出，请检查磁盘/日志")
        path = self._csv_path
        self._csv_path = None
        self.csv_state.emit(False, str(path) if path else "")
        self.notice.emit(f"CSV 已结束：{path.name if path else ''}")

    def _on_csv_error(self, message: str) -> None:
        self._csv_writer = None
        self._csv_path = None
        self.csv_state.emit(False, "")
        self.error_occurred.emit("CSV 写入失败", message)
        if self._state == "acquiring":
            self.stop_acquisition()

    def _on_csv_closed(self, path: str, rows: int) -> None:
        log.info("CSV 已关闭：%s，%d 行", path, rows)
        self.notice.emit(f"CSV 已关闭：{Path(path).name}，{rows} 行")

    # ---------- 数据 ----------

    def _on_status(self, status: InstrumentStatus) -> None:
        self._status = status
        self.status_updated.emit(status)

    def _on_batch(self, batch: Batch) -> None:
        self.ring.append_batch(batch)
        self._count += len(batch.readings)
        self.stats.add_batch(batch.readings)
        self.stats_updated.emit(self.stats.snapshot())
        self._update_rate(batch)
        self.batch_received.emit(batch)

        if self._csv_writer is not None:
            try:
                self._csv_writer.enqueue(batch)
            except CsvQueueFull as exc:
                self.error_occurred.emit("CSV 队列溢出", str(exc))
                self.stop_acquisition()
                self.stop_csv()

    def _update_rate(self, batch: Batch) -> None:
        if not batch.readings:
            return
        # 第 1 批是首条单采样（为了 <200ms 首读），不拿它当速率基准，
        # 否则启动阶段会短暂显示 18–26 /s 的假低速率。
        if batch.batch_id == 1:
            self.rate_updated.emit(None)
            return
        last_ts = batch.readings[-1].timestamp_ns
        self._rate_points.append((last_ts, len(batch.readings)))
        cutoff = last_ts - 5_000_000_000
        while len(self._rate_points) > 2 and self._rate_points[1][0] < cutoff:
            self._rate_points.popleft()
        if len(self._rate_points) < 2:
            self.rate_updated.emit(None)
            return
        first_ts, _ = self._rate_points[0]
        total = sum(count for _, count in list(self._rate_points)[1:])
        span_s = (last_ts - first_ts) / 1_000_000_000
        self.rate_updated.emit(total / span_s if span_s > 0 else None)

    @property
    def sample_count(self) -> int:
        return self._count

    def clear_data(self) -> None:
        self.ring.clear()
        self._count = 0
        self.stats.reset()
        self._rate_points.clear()
        self.rate_updated.emit(None)
        self.stats_updated.emit(self.stats.snapshot())
        self.notice.emit("缓冲已清空")

    def clear_stats(self) -> None:
        self.stats.reset()
        self.stats_updated.emit(self.stats.snapshot())
        self.notice.emit("统计已清零")

    def save_snapshot(self, path: str) -> None:
        """把环形缓冲另存为 CSV；不覆盖正在录制的文件。"""

        import csv
        from datetime import datetime

        unit = self._status.function.unit if self._status else ""
        function = self._status.function.label if self._status else ""
        with open(path, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["时间戳", "Unix纳秒", "功能", "读数", "单位", "OVLD"])
            for value, timestamp_ns, ovld in self.ring.iter_ordered():
                stamp = datetime.fromtimestamp(timestamp_ns / 1e9).astimezone().isoformat(
                    timespec="microseconds"
                )
                writer.writerow(
                    [stamp, timestamp_ns, function, format(value, ".15g"), unit, 1 if ovld else 0]
                )

    def _on_state(self, state: str, detail: str) -> None:
        self._state = state
        self.state_changed.emit(state, detail)
        if state in {"ready", "error", "disconnected"} and self._was_acquiring:
            self._was_acquiring = False
            if self._csv_writer is not None:
                self.stop_csv()
        if state in {"error", "disconnected"} and self._csv_writer is not None:
            self.stop_csv()

    # ---------- 收尾 ----------

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        log.info("正在停止 I/O 线程…")
        self.worker.shutdown()
        if not self.worker.wait(15000):
            log.error("I/O 线程 15 秒内未退出")
            return
        self.stop_csv()
        VisaIO.release_shared()
