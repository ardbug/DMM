"""CSV 写线程：只接收不可变 Batch，按批 flush。"""

from __future__ import annotations

import csv
import logging
import os
import queue
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from app.domain.models import Batch

log = logging.getLogger(__name__)

_HEADER = [
    "时间戳",
    "Unix纳秒",
    "批次号",
    "批次开始",
    "批次结束",
    "功能",
    "量程",
    "NPLC",
    "位数",
    "读数",
    "单位",
    "OVLD",
    "配置版本",
]

_SENTINEL = object()


class CsvQueueFull(RuntimeError):
    pass


def default_csv_dir() -> Path:
    return Path.home() / "Documents" / "34401A数据"


def make_csv_path(
    function_label: str = "DMM",
    root: Path | None = None,
) -> Path:
    root = root or default_csv_dir()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%m%d_%H%M")
    safe = "".join(ch if ch not in '\\/:*?"<>|' else "_" for ch in function_label)
    candidate = root / f"{safe}_{stamp}.csv"
    index = 2
    while candidate.exists():
        candidate = root / f"{safe}_{stamp}_{index:02d}.csv"
        index += 1
    return candidate


def _iso(ns: int) -> str:
    return datetime.fromtimestamp(ns / 1_000_000_000).astimezone().isoformat(
        timespec="microseconds"
    )


class CsvWriter(QThread):
    opened = Signal(str)
    error = Signal(str)
    closed = Signal(str, int)

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self.path = Path(path)
        # 3000 批 ≈ 30,000 条（30 条/秒约 16 分钟）的缓冲；
        # 按 Batch 计数，不能按 100,000 条直接当队列容量，否则内存会过大。
        self._queue: queue.Queue[Batch | object] = queue.Queue(maxsize=3000)
        self._stop_requested = False
        self.rows_written = 0

    def enqueue(self, batch: Batch) -> None:
        if self._stop_requested:
            raise CsvQueueFull("CSV 已停止")
        try:
            self._queue.put_nowait(batch)
        except queue.Full as exc:
            raise CsvQueueFull("CSV 写入队列已满") from exc

    def stop(self) -> None:
        if self._stop_requested:
            return
        self._stop_requested = True
        try:
            self._queue.put(_SENTINEL, timeout=1.0)
        except queue.Full:
            log.error("CSV 队列已满，停止信号未能入队")

    def run(self) -> None:
        log.info("CSV 写线程启动：%s", self.path)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(_HEADER)
                handle.flush()
                self.opened.emit(str(self.path))

                while True:
                    item = self._queue.get()
                    if item is _SENTINEL:
                        break
                    assert isinstance(item, Batch)
                    self._write_batch(writer, item)
                    handle.flush()

                handle.flush()
                os.fsync(handle.fileno())
            log.info("CSV 写线程结束：%s，%d 行", self.path, self.rows_written)
            self.closed.emit(str(self.path), self.rows_written)
        except Exception as exc:
            log.exception("CSV 写入失败")
            self.error.emit(f"CSV 写入失败：{exc}")

    def _write_batch(self, writer, batch: Batch) -> None:
        start = _iso(batch.start_ns)
        end = _iso(batch.end_ns)
        nplc = f"{batch.config.nplc:g}"
        for reading in batch.readings:
            writer.writerow(
                [
                    _iso(reading.timestamp_ns),
                    reading.timestamp_ns,
                    batch.batch_id,
                    start,
                    end,
                    reading.function_label,
                    batch.range_text,
                    nplc,
                    batch.config.digits,
                    format(reading.value, ".15g"),
                    reading.unit,
                    1 if reading.ovld else 0,
                    batch.config_version,
                ]
            )
            self.rows_written += 1
