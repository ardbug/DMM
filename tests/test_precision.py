from __future__ import annotations

import pytest

from app.domain.precision import compute_accuracy


def test_dcv_10v_1y() -> None:
    result = compute_accuracy("VDC", 10.0, 10.0, "1y")
    assert result is not None
    # 10 × 0.0035% + 10 × 0.0005% = 0.0004 V
    assert result.error == pytest.approx(0.0004)
    assert result.unit == "V"
    assert result.range_value == 10.0


def test_dcv_100mv_range() -> None:
    result = compute_accuracy("VDC", 0.05, 0.1, "1y")
    assert result is not None
    # 0.05 × 0.005% + 0.1 × 0.0035% = 6 µV
    assert result.error == pytest.approx(0.000006)


def test_24h_differs_from_1y() -> None:
    day = compute_accuracy("VDC", 10.0, 10.0, "24h")
    year = compute_accuracy("VDC", 10.0, 10.0, "1y")
    assert day is not None and year is not None
    assert day.error < year.error


def test_2w_adds_null_note() -> None:
    result = compute_accuracy("2WΩ", 100.0, 100.0, "1y")
    assert result is not None
    assert "0.2 Ω" in result.note
    assert result.error > 0.2


def test_ac_voltage_uses_frequency_band() -> None:
    low = compute_accuracy("VAC", 0.5, 1.0, "1y", "10-20k")
    high = compute_accuracy("VAC", 0.5, 1.0, "1y", "50-100k")
    assert low is not None and high is not None
    # 0.5 × 0.06% + 1 × 0.03% = 0.0006 V
    assert low.error == pytest.approx(0.0006)
    assert high.error > low.error


def test_frequency_accuracy_uses_reading_band() -> None:
    result = compute_accuracy("频率", 1000.0, None, "1y")
    assert result is not None
    # 1 kHz is in 40 Hz–300 kHz, 1y = 0.01% of reading
    assert result.error == pytest.approx(0.1)
    assert result.unit == "Hz"


def test_unsupported_function_returns_none() -> None:
    assert compute_accuracy("未知", 1.0, 1.0, "1y") is None
