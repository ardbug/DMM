"""定长环形缓冲：值 / 时间戳 / OVLD 标志。"""

from __future__ import annotations

from array import array
from collections.abc import Iterable

from app.domain.models import Batch

DEFAULT_CAPACITY = 1_000_000


class RingBuffer:
    """只允许 UI 线程读写；底层用标准库数组，避免 8 小时几十万对象。"""

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        if capacity <= 0:
            raise ValueError("capacity 必须为正")
        self.capacity = capacity
        self._values = array("d", [0.0]) * capacity
        self._ts_ns = array("q", [0]) * capacity
        self._flags = bytearray(capacity)
        self._start = 0
        self._count = 0

    def __len__(self) -> int:
        return self._count

    def clear(self) -> None:
        self._start = 0
        self._count = 0

    def append_batch(self, batch: Batch) -> None:
        for reading in batch.readings:
            index = (self._start + self._count) % self.capacity
            self._values[index] = reading.value
            self._ts_ns[index] = reading.timestamp_ns
            self._flags[index] = 1 if reading.ovld else 0
            if self._count < self.capacity:
                self._count += 1
            else:
                self._start = (self._start + 1) % self.capacity

    def latest(self) -> tuple[float, int, bool] | None:
        if self._count == 0:
            return None
        index = (self._start + self._count - 1) % self.capacity
        return self._values[index], self._ts_ns[index], bool(self._flags[index])

    def iter_ordered(self) -> Iterable[tuple[float, int, bool]]:
        for offset in range(self._count):
            index = (self._start + offset) % self.capacity
            yield self._values[index], self._ts_ns[index], bool(self._flags[index])

    def latest_n(self, n: int) -> list[tuple[float, int, bool]]:
        if n <= 0 or self._count == 0:
            return []
        n = min(n, self._count)
        start_offset = self._count - n
        result: list[tuple[float, int, bool]] = []
        for offset in range(start_offset, self._count):
            index = (self._start + offset) % self.capacity
            result.append(
                (self._values[index], self._ts_ns[index], bool(self._flags[index]))
            )
        return result

    def _ts_at(self, offset: int) -> int:
        return self._ts_ns[(self._start + offset) % self.capacity]

    def timestamp_at(self, offset: int) -> int | None:
        if offset < 0 or offset >= self._count:
            return None
        return self._ts_at(offset)

    def lower_bound(self, timestamp_ns: int) -> int:
        """返回第一个时间戳 >= timestamp_ns 的逻辑下标。"""

        low, high = 0, self._count
        while low < high:
            mid = (low + high) // 2
            if self._ts_at(mid) < timestamp_ns:
                low = mid + 1
            else:
                high = mid
        return low

    def slice_by_time(self, start_ns: int, end_ns: int) -> list[tuple[float, int, bool]]:
        """返回 [start_ns, end_ns] 内的真实样本，不做抽稀。"""

        if self._count == 0 or end_ns < start_ns:
            return []
        low = self.lower_bound(start_ns)
        high = self.lower_bound(end_ns + 1)
        result: list[tuple[float, int, bool]] = []
        for offset in range(low, high):
            index = (self._start + offset) % self.capacity
            result.append(
                (self._values[index], self._ts_ns[index], bool(self._flags[index]))
            )
        return result
