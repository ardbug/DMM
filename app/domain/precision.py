"""34401A 精度误差：数据来自 datasheet 第 3 页（24h / 90d / 1y）。

表中为 ±(% of reading + % of range)，条件：1 小时预热、6½ 位、慢速 AC 滤波。
这里实现 DCV/DCI/2WΩ/4WΩ/导通/二极管；ACV/ACI/频率/周期需要额外汇率段或
时间基准信息，暂不硬猜，界面显示“—”。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.domain.functions import describe_function

Tier = str
_TIERS = ("24h", "90d", "1y")
TIER_LABELS = {"24h": "24 小时", "90d": "90 天", "1y": "1 年"}

# (reading%, range%) by tier
Pair = tuple[float, float]

_DCV: dict[float, dict[Tier, Pair]] = {
    0.1: {"24h": (0.0030, 0.0030), "90d": (0.0040, 0.0035), "1y": (0.0050, 0.0035)},
    1.0: {"24h": (0.0020, 0.0006), "90d": (0.0030, 0.0007), "1y": (0.0040, 0.0007)},
    10.0: {"24h": (0.0015, 0.0004), "90d": (0.0020, 0.0005), "1y": (0.0035, 0.0005)},
    100.0: {"24h": (0.0020, 0.0006), "90d": (0.0035, 0.0006), "1y": (0.0045, 0.0006)},
    1000.0: {"24h": (0.0020, 0.0006), "90d": (0.0035, 0.0010), "1y": (0.0045, 0.0010)},
}

_DCI: dict[float, dict[Tier, Pair]] = {
    0.01: {"24h": (0.005, 0.010), "90d": (0.030, 0.020), "1y": (0.050, 0.020)},
    0.1: {"24h": (0.010, 0.010), "90d": (0.030, 0.005), "1y": (0.050, 0.005)},
    1.0: {"24h": (0.050, 0.010), "90d": (0.080, 0.010), "1y": (0.100, 0.010)},
    3.0: {"24h": (0.100, 0.010), "90d": (0.120, 0.020), "1y": (0.120, 0.020)},
}

_RES: dict[float, dict[Tier, Pair]] = {
    100.0: {"24h": (0.0030, 0.0030), "90d": (0.008, 0.004), "1y": (0.010, 0.004)},
    1_000.0: {"24h": (0.0020, 0.0005), "90d": (0.008, 0.001), "1y": (0.010, 0.001)},
    10_000.0: {"24h": (0.0020, 0.0005), "90d": (0.008, 0.001), "1y": (0.010, 0.001)},
    100_000.0: {"24h": (0.0020, 0.0005), "90d": (0.008, 0.001), "1y": (0.010, 0.001)},
    1_000_000.0: {"24h": (0.002, 0.001), "90d": (0.008, 0.001), "1y": (0.010, 0.001)},
    10_000_000.0: {"24h": (0.015, 0.001), "90d": (0.020, 0.001), "1y": (0.040, 0.001)},
    100_000_000.0: {"24h": (0.300, 0.010), "90d": (0.800, 0.001), "1y": (0.800, 0.001)},
}

_CONT = {"24h": (0.002, 0.030), "90d": (0.008, 0.030), "1y": (0.010, 0.030)}
_DIODE = {"24h": (0.002, 0.010), "90d": (0.008, 0.020), "1y": (0.010, 0.020)}

AC_BANDS: list[tuple[str, str]] = [
    ("3-5", "3–5 Hz"),
    ("5-10", "5–10 Hz"),
    ("10-20k", "10 Hz–20 kHz"),
    ("20-50k", "20–50 kHz"),
    ("50-100k", "50–100 kHz"),
    ("100-300k", "100–300 kHz"),
]
ACI_BANDS: list[tuple[str, str]] = [
    ("3-5", "3–5 Hz"),
    ("5-10", "5–10 Hz"),
    ("10-5k", "10 Hz–5 kHz"),
]

# ACV 100 mV 档：band -> tier -> (reading%, range%)
_VAC_LOW: dict[str, dict[Tier, Pair]] = {
    "3-5": {"24h": (1.00, 0.03), "90d": (1.00, 0.04), "1y": (1.00, 0.04)},
    "5-10": {"24h": (0.35, 0.03), "90d": (0.35, 0.04), "1y": (0.35, 0.04)},
    "10-20k": {"24h": (0.04, 0.03), "90d": (0.05, 0.04), "1y": (0.06, 0.04)},
    "20-50k": {"24h": (0.10, 0.05), "90d": (0.11, 0.05), "1y": (0.12, 0.05)},
    "50-100k": {"24h": (0.55, 0.08), "90d": (0.60, 0.08), "1y": (0.60, 0.08)},
    "100-300k": {"24h": (4.00, 0.50), "90d": (4.00, 0.50), "1y": (4.00, 0.50)},
}
_VAC_HIGH: dict[str, dict[Tier, Pair]] = {
    "3-5": {"24h": (1.00, 0.02), "90d": (1.00, 0.03), "1y": (1.00, 0.03)},
    "5-10": {"24h": (0.35, 0.02), "90d": (0.35, 0.03), "1y": (0.35, 0.03)},
    "10-20k": {"24h": (0.04, 0.02), "90d": (0.05, 0.03), "1y": (0.06, 0.03)},
    "20-50k": {"24h": (0.10, 0.04), "90d": (0.11, 0.05), "1y": (0.12, 0.04)},
    "50-100k": {"24h": (0.55, 0.08), "90d": (0.60, 0.08), "1y": (0.60, 0.08)},
    "100-300k": {"24h": (4.00, 0.50), "90d": (4.00, 0.50), "1y": (4.00, 0.50)},
}
_ACI_1A: dict[str, dict[Tier, Pair]] = {
    "3-5": {"24h": (1.00, 0.04), "90d": (1.00, 0.04), "1y": (1.00, 0.04)},
    "5-10": {"24h": (0.30, 0.04), "90d": (0.30, 0.04), "1y": (0.30, 0.04)},
    "10-5k": {"24h": (0.10, 0.04), "90d": (0.10, 0.04), "1y": (0.10, 0.04)},
}
_ACI_3A: dict[str, dict[Tier, Pair]] = {
    "3-5": {"24h": (1.10, 0.06), "90d": (1.10, 0.06), "1y": (1.10, 0.06)},
    "5-10": {"24h": (0.35, 0.06), "90d": (0.35, 0.06), "1y": (0.35, 0.06)},
    "10-5k": {"24h": (0.15, 0.06), "90d": (0.15, 0.06), "1y": (0.15, 0.06)},
}
_FREQ: dict[str, dict[Tier, float]] = {
    "3-5": {"24h": 0.10, "90d": 0.10, "1y": 0.10},
    "5-10": {"24h": 0.05, "90d": 0.05, "1y": 0.05},
    "10-40": {"24h": 0.03, "90d": 0.03, "1y": 0.03},
    "40-300k": {"24h": 0.006, "90d": 0.01, "1y": 0.01},
}


@dataclass(frozen=True, slots=True)
class AccuracyResult:
    error: float
    unit: str
    tier: str
    range_value: float
    note: str = ""


def _nearest(value: float, candidates: list[float]) -> float:
    return min(candidates, key=lambda item: abs(item - value))


def _table_for(function_label: str) -> tuple[dict[float, dict[Tier, Pair]] | None, str]:
    if function_label == "VDC":
        return _DCV, "V"
    if function_label == "DCI":
        return _DCI, "A"
    if function_label in {"2WΩ", "4WΩ"}:
        return _RES, "Ω"
    return None, ""


def _infer_range(label: str, reading: float) -> float:
    if label == "VDC":
        return _nearest(abs(reading) * 1.05, list(_DCV))
    if label == "DCI":
        return _nearest(abs(reading) * 1.05, list(_DCI))
    if label in {"2WΩ", "4WΩ"}:
        return _nearest(abs(reading) * 1.05, list(_RES))
    return 0.0


def _frequency_band(frequency: float) -> str | None:
    if frequency < 3 or frequency > 300_000:
        return None
    if frequency < 5:
        return "3-5"
    if frequency < 10:
        return "5-10"
    if frequency < 40:
        return "10-40"
    return "40-300k"


def compute_accuracy(
    function_label: str,
    reading: float,
    range_value: float | str | None,
    tier: str = "1y",
    ac_band: str = "10-20k",
) -> AccuracyResult | None:
    if tier not in _TIERS:
        tier = "1y"
    if isinstance(range_value, str):
        try:
            range_value = float(range_value)
        except (TypeError, ValueError):
            range_value = None
    if function_label == "导通":
        pair = _CONT[tier]
        error = abs(reading) * pair[0] / 100 + 1000.0 * pair[1] / 100
        return AccuracyResult(error, "Ω", tier, 1000.0, "1000 Ω 量程")
    if function_label == "二极管":
        pair = _DIODE[tier]
        error = abs(reading) * pair[0] / 100 + 1.0 * pair[1] / 100
        return AccuracyResult(error, "V", tier, 1.0, "1 V 量程")

    if function_label == "VAC":
        if range_value is None or range_value <= 0:
            range_value = 0.1
        table = _VAC_LOW if range_value <= 0.1 else _VAC_HIGH
        band = ac_band if ac_band in table else "10-20k"
        reading_pct, range_pct = table[band][tier]
        error = abs(reading) * reading_pct / 100 + range_value * range_pct / 100
        note = ""
        if abs(reading) < 0.05 * range_value:
            error += range_value * 0.001
            note = "输入 <5% 量程，另加 0.1% 量程"
        return AccuracyResult(error, "V", tier, range_value, note)

    if function_label == "ACI":
        if range_value is None or range_value <= 0:
            range_value = 1.0
        table = _ACI_1A if range_value <= 1.0 else _ACI_3A
        band = ac_band if ac_band in table else "10-5k"
        reading_pct, range_pct = table[band][tier]
        error = abs(reading) * reading_pct / 100 + range_value * range_pct / 100
        note = ""
        if abs(reading) < 0.05 * range_value:
            error += range_value * 0.001
            note = "输入 <5% 量程，另加 0.1% 量程"
        return AccuracyResult(error, "A", tier, range_value, note)

    if function_label in {"频率", "周期"}:
        if function_label == "频率":
            frequency = abs(reading)
            unit = "Hz"
        else:
            frequency = 1.0 / abs(reading) if reading else 0.0
            unit = "s"
        band = _frequency_band(frequency)
        if band is None:
            return None
        error = abs(reading) * _FREQ[band][tier] / 100
        return AccuracyResult(error, unit, tier, 0.0, f"按输入频率 {frequency:g} Hz 分档")

    table, unit = _table_for(function_label)
    if table is None:
        return None
    if range_value is None or not math.isfinite(range_value) or range_value <= 0:
        range_value = _infer_range(function_label, reading)
    else:
        range_value = _nearest(range_value, list(table))
    if range_value not in table or not math.isfinite(reading):
        return None
    reading_pct, range_pct = table[range_value][tier]
    error = abs(reading) * reading_pct / 100 + range_value * range_pct / 100
    note = ""
    if function_label in {"2WΩ"}:
        # datasheet 注 7：2 线电阻未做 Math Null 时另加 0.2 Ω。
        error += 0.2
        note = "2W 未加 Null，含 +0.2 Ω"
    return AccuracyResult(error, unit, tier, range_value, note)


def describe_accuracy(
    function_raw: str,
    reading: float,
    range_text: str,
    tier: str = "1y",
) -> AccuracyResult | None:
    """从 FUNC? 原始值和 RANG? 文本计算；AC/频率返回 None。"""

    info = describe_function(function_raw)
    try:
        range_value = float(range_text) if range_text else None
    except (TypeError, ValueError):
        range_value = None
    return compute_accuracy(info.label, reading, range_value, tier)
