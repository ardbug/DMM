from __future__ import annotations

import pytest

from app.domain.models import Reading
from app.domain.statistics import StatsAccumulator


def reading(value: float, ovld: bool = False) -> Reading:
    return Reading(value=value, unit="V", function_label="VDC", ovld=ovld, raw=str(value))


def test_statistics_welford() -> None:
    stats = StatsAccumulator()
    stats.add_batch((reading(1.0), reading(2.0), reading(3.0)))
    snap = stats.snapshot()
    assert snap.count == 3
    assert snap.minimum == 1.0
    assert snap.maximum == 3.0
    assert snap.average == pytest.approx(2.0)
    assert snap.std == pytest.approx(1.0)
    assert snap.peak_to_peak == pytest.approx(2.0)


def test_statistics_excludes_ovld_and_resets() -> None:
    stats = StatsAccumulator()
    stats.add_batch((reading(1.0), reading(9.9e37, True), reading(2.0)))
    snap = stats.snapshot()
    assert snap.count == 2
    assert snap.ovld == 1
    stats.reset()
    assert stats.snapshot().count == 0
