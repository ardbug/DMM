"""会话统计：Welford，OVLD 排除，样本标准差。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.models import Reading


@dataclass(frozen=True, slots=True)
class StatsSnapshot:
    count: int = 0
    minimum: float | None = None
    maximum: float | None = None
    average: float | None = None
    std: float | None = None
    peak_to_peak: float | None = None
    ovld: int = 0


class StatsAccumulator:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.count = 0
        self.ovld = 0
        self.mean = 0.0
        self.m2 = 0.0
        self.minimum: float | None = None
        self.maximum: float | None = None

    def add_batch(self, readings: tuple[Reading, ...]) -> None:
        for reading in readings:
            if reading.ovld or not math.isfinite(reading.value):
                self.ovld += 1
                continue
            value = reading.value
            self.count += 1
            delta = value - self.mean
            self.mean += delta / self.count
            self.m2 += delta * (value - self.mean)
            self.minimum = value if self.minimum is None else min(self.minimum, value)
            self.maximum = value if self.maximum is None else max(self.maximum, value)

    def snapshot(self) -> StatsSnapshot:
        if self.count == 0:
            return StatsSnapshot(ovld=self.ovld)
        std = math.sqrt(self.m2 / (self.count - 1)) if self.count > 1 else 0.0
        assert self.minimum is not None and self.maximum is not None
        return StatsSnapshot(
            count=self.count,
            minimum=self.minimum,
            maximum=self.maximum,
            average=self.mean,
            std=std,
            peak_to_peak=self.maximum - self.minimum,
            ovld=self.ovld,
        )
