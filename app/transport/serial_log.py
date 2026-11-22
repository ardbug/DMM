"""进程内串口收发原始字节日志（仅用于界面查看，不落盘）。"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SerialLogEntry:
    at_ns: int
    direction: str
    data: bytes


class SerialLogBuffer:
    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: deque[SerialLogEntry] = deque(maxlen=max_entries)
        self._lock = threading.Lock()

    def record(self, direction: str, data: bytes) -> None:
        with self._lock:
            self._entries.append(
                SerialLogEntry(time.time_ns(), direction, bytes(data))
            )

    def snapshot(self) -> list[SerialLogEntry]:
        with self._lock:
            return list(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


serial_log = SerialLogBuffer()
