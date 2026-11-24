"""逐条轮询的采样能力与节拍。

所有连续采集都使用 `SAMP:COUN 1` + 一次 `READ?` 取一条。
不再用批量取回，因此每个读数都有独立的读取完成时间，CSV 时间戳不再
按批内插值。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import AcquisitionConfig


@dataclass(frozen=True, slots=True)
class RatePlan:
    requested: float
    effective: float
    capability: float
    batch_size: int
    period_ns: int
    limited: bool
    note: str
    uniform: bool = True


def capability_for(
    nplc: float, az: bool, interface: str = "serial"
) -> float:
    """逐条 `READ?` 的规划上限（条/秒）。

    实测（DCV、固定量程、9600-7E2，单条读取中位耗时）：
    - 0.02 PLC：约 30.0 ms（AZ 关）/31.2 ms（AZ 开）
    - 0.2 PLC：约 32.8 ms（AZ 关）/36.6 ms（AZ 开）
    - 1 PLC：约 47 ms（AZ 关）；AZ 开更慢
    - 10 PLC：约 0.5 s 级
    - 100 PLC：约 2.3 s

    取略保守的规划值；实际值由批次时间戳和界面实际速率反映。
    NPLC 1 及以上不可能达到 30 条/秒。
    """

    if interface == "gpib":
        # 34401A 的 GPIB 读取上限高于串口；实际值由界面速率反馈。
        if nplc <= 0.02:
            return 500.0 if not az else 300.0
        if nplc <= 0.2:
            return 200.0 if not az else 120.0
        if nplc <= 1.0:
            return 40.0 if not az else 25.0
        if nplc <= 10.0:
            return 4.0 if not az else 2.5
        return 0.4
    if nplc <= 0.02:
        return 30.0
    if nplc <= 0.2:
        return 27.0 if az else 30.0
    if nplc <= 1.0:
        return 16.0 if az else 20.0
    if nplc <= 10.0:
        return 1.5 if az else 1.8
    return 0.4


def plan_rate(
    config: AcquisitionConfig, interface: str = "serial"
) -> RatePlan:
    capability = capability_for(config.nplc, config.az, interface)
    average_count = (
        max(1, int(config.average_count)) if config.average_enabled else 1
    )
    input_rate = max(0.001, min(config.rate, capability))
    effective = max(0.001, input_rate / average_count)
    # period_ns 是内部每次 READ? 的间隔；平均 N 次后输出一条。
    period_ns = max(1, int(1_000_000_000 / input_rate))
    limited = config.rate > capability + 1e-9

    note = ""
    if average_count > 1:
        note = (
            f"平均 {average_count} 次：输入约 {input_rate:g} 次/秒，"
            f"输出约 {effective:g} 次/秒"
        )
        if limited:
            note += (
                f"（NPLC {config.nplc:g}"
                f"{' / AZ 开' if config.az else ''} 输入上限 {capability:g} 次/秒）"
            )
    elif limited:
        note = (
            f"逐条轮询在 NPLC {config.nplc:g}"
            f"{' / AZ 开' if config.az else ''} 上限约 {capability:g} 条/秒"
        )
    return RatePlan(
        requested=config.rate,
        effective=effective,
        capability=capability,
        batch_size=1,
        period_ns=period_ns,
        limited=limited,
        note=note,
        uniform=True,
    )
