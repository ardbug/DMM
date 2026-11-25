"""34970A 单通道读取（首期只做单通道，不做连续扫描）。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace

from app.constants import OVLD_THRESHOLD
from app.domain.models import InstrumentStatus, Reading, SerialSettings
from app.domain.functions import FunctionInfo
from app.instrument.daq_modules import (
    ScanChannelConfig,
    SlotInfo,
    parse_slot,
)

log = logging.getLogger(__name__)


def _info(raw: str, label: str, unit: str) -> FunctionInfo:
    return FunctionInfo(raw=raw, label=label, unit=unit, query_prefix=raw)


_FUNCTIONS = {
    "VOLT:DC": _info("VOLT:DC", "VDC", "V"),
    "VOLT:AC": _info("VOLT:AC", "VAC", "V"),
    "RES": _info("RES", "2WΩ", "Ω"),
    "FRES": _info("FRES", "4WΩ", "Ω"),
    "CURR:DC": _info("CURR:DC", "DCI", "A"),
    "CURR:AC": _info("CURR:AC", "ACI", "A"),
    "FREQ": _info("FREQ", "频率", "Hz"),
    "PER": _info("PER", "周期", "s"),
    "TEMP": _info("TEMP", "TEMP", "°C"),
}

_TEMP_CONF = {
    "TC:K": "CONF:TEMP TC,K",
    "RTD:2W:100": "CONF:TEMP RTD,85",
    "RTD:2W:1000": "CONF:TEMP RTD,85",
    "RTD:4W:100": "CONF:TEMP FRTD,85",
    "RTD:4W:1000": "CONF:TEMP FRTD,85",
    "THERM:5000": "CONF:TEMP THER,5000",
}


@dataclass(frozen=True, slots=True)
class DaqConfig:
    channel: int = 101
    function: str = "VOLT:DC"
    range_value: float = 0.0
    nplc: float = 1.0
    temperature: str = "TC:K"
    temp_unit: str = "C"
    rate: float = 1.0
    scan: bool = False
    scan_list: str = ""
    scan_rate: float = 1.0
    scan_count: int = 1
    pre_scan_wait: float = 0.0
    post_scan_wait: float = 0.0
    min_scan_seconds: float = 0.0
    channels: tuple[ScanChannelConfig, ...] = ()


def parse_channels(
    spec: str,
    allowed: set[int] | None = None,
) -> list[int]:
    channels: list[int] = []
    for part in spec.replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            first, last = part.split(":", 1)
            try:
                start, end = int(first), int(last)
            except ValueError as exc:
                raise ValueError(f"非法通道范围：{part}") from exc
            if start > end:
                start, end = end, start
            values = range(start, end + 1)
        else:
            try:
                values = (int(part),)
            except ValueError as exc:
                raise ValueError(f"非法通道：{part}") from exc
        for channel in values:
            if allowed is not None and channel not in allowed:
                raise ValueError(f"通道不在已安装模块范围内：{channel}")
            if not 101 <= channel <= 399:
                raise ValueError(f"通道超出范围：{channel}")
            if channel not in channels:
                channels.append(channel)
    if not channels:
        raise ValueError("扫描通道为空")
    return channels


def _format_channels(channels: list[int]) -> str:
    if not channels:
        return ""
    values = sorted(channels)
    parts: list[str] = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        parts.append(str(start) if start == prev else f"{start}:{prev}")
        start = prev = value
    parts.append(str(start) if start == prev else f"{start}:{prev}")
    return ",".join(parts)


class Daq34970A:
    def __init__(self, io) -> None:
        self._io = io
        self.interface = "serial"
        self.identity = ""
        self.local_only = False
        self.status: InstrumentStatus | None = None
        self.slots: list[SlotInfo] = []
        self.current_channels: set[int] = set()
        self._scan_functions: dict[int, FunctionInfo] = {}

    @property
    def is_open(self) -> bool:
        return self._io.is_open

    def open(self, settings: SerialSettings) -> str:
        self._io.open(settings)
        self.interface = settings.interface
        try:
            if self.interface == "gpib":
                remote = getattr(self._io, "remote", None)
                if remote is not None:
                    remote()
            else:
                self._io.write_line("SYST:REM")
            self._io.write_line("*CLS")
            self.identity = self._io.query_line("*IDN?", 5000)
        except Exception:
            self._io.close()
            raise
        self.status = _info("VOLT:DC", "DCV", "V")
        self.local_only = False
        return self.identity

    def open_local(self, settings: SerialSettings) -> None:
        self._io.open(settings)
        self.interface = settings.interface
        self.local_only = True

    def read_slots(self) -> list[SlotInfo]:
        slots: list[SlotInfo] = []
        for slot in (100, 200, 300):
            try:
                raw = self._io.query_line(
                    f"SYST:CTYP? {slot}", 3000
                )
                info = parse_slot(slot, raw)
            except Exception:
                info = parse_slot(slot, "")
            slots.append(info)
        self.slots = slots
        self.current_channels = {
            channel
            for item in slots
            for channel in item.current_channels
        }
        return slots

    def allowed_channels(self) -> set[int] | None:
        if not self.slots:
            return None
        channels = {
            channel
            for item in self.slots
            for channel in item.channels
        }
        return channels or None

    def configure(self, config: DaqConfig) -> None:
        if config.scan:
            self._configure_scan(config)
            return
        channel = int(config.channel)
        allowed = self.allowed_channels()
        if allowed is not None and channel not in allowed:
            raise ValueError(f"通道 {channel} 不在已安装模块范围内")
        current_set = self.current_channels or {121, 122}
        if channel in current_set and config.function not in {
            "CURR:DC",
            "CURR:AC",
        }:
            raise ValueError("电流通道只能测量电流")
        if config.function == "TEMP":
            conf = _TEMP_CONF.get(config.temperature, "CONF:TEMP TC,K")
            self._io.write_line(f"{conf},(@{channel})")
            if config.temperature.endswith(":1000"):
                if config.temperature.startswith("RTD:4W"):
                    self._io.write_line(
                        f"SENS:TEMP:TRAN:FRTD:RES 1000,(@{channel})"
                    )
                else:
                    self._io.write_line(
                        f"SENS:TEMP:TRAN:RTD:RES 1000,(@{channel})"
                    )
            self._io.write_line(f"UNIT:TEMP {config.temp_unit},(@{channel})")
            self._io.write_line(f"SENS:TEMP:NPLC {config.nplc:g},(@{channel})")
            self.status = InstrumentStatus(
                function=_FUNCTIONS["TEMP"],
                nplc=f"{config.nplc:g}",
                range_text="AUTO",
                terminal="",
            )
        else:
            self._io.write_line(f"CONF:{config.function} (@{channel})")
            if config.function not in {"FREQ", "PER"}:
                self._io.write_line(
                    f"SENS:{config.function}:NPLC {config.nplc:g},(@{channel})"
                )
            self.status = InstrumentStatus(
                function=_FUNCTIONS.get(config.function, _FUNCTIONS["VOLT:DC"]),
                nplc=f"{config.nplc:g}",
                range_text="AUTO",
                terminal="",
            )

    def _configure_scan(self, config: DaqConfig) -> None:
        channels = parse_channels(
            config.scan_list, self.allowed_channels()
        )
        current_set = self.current_channels or {121, 122}
        specs = [
            spec for spec in config.channels if spec.channel in channels
        ]
        if not specs:
            specs = [
                ScanChannelConfig(
                    channel, config.function, config.scan_count
                )
                for channel in channels
            ]
        current = [spec.channel for spec in specs if spec.channel in current_set]
        if current and len(current) != len(specs):
            raise ValueError("扫描列表不能混用电流通道和复用通道")
        if current and any(
            spec.function not in {"CURR:DC", "CURR:AC"} for spec in specs
        ):
            raise ValueError("电流通道只能扫描电流")
        groups: dict[str, list[int]] = {}
        for spec in specs:
            groups.setdefault(spec.function, []).append(spec.channel)
        scan_functions: dict[int, FunctionInfo] = {}
        for function, group_channels in groups.items():
            channel_spec = _format_channels(group_channels)
            if function == "TEMP":
                conf = _TEMP_CONF.get(
                    config.temperature, "CONF:TEMP TC,K"
                )
                self._io.write_line(f"{conf},(@{channel_spec})")
                if config.temperature.endswith(":1000"):
                    if config.temperature.startswith("RTD:4W"):
                        self._io.write_line(
                            f"SENS:TEMP:TRAN:FRTD:RES 1000,(@{channel_spec})"
                        )
                    else:
                        self._io.write_line(
                            f"SENS:TEMP:TRAN:RTD:RES 1000,(@{channel_spec})"
                        )
                self._io.write_line(
                    f"UNIT:TEMP {config.temp_unit},(@{channel_spec})"
                )
                self._io.write_line(
                    f"SENS:TEMP:NPLC {config.nplc:g},(@{channel_spec})"
                )
                info = _FUNCTIONS["TEMP"]
            else:
                self._io.write_line(
                    f"CONF:{function} (@{channel_spec})"
                )
                if function not in {"FREQ", "PER"}:
                    self._io.write_line(
                        f"SENS:{function}:NPLC "
                        f"{config.nplc:g},(@{channel_spec})"
                    )
                info = _FUNCTIONS.get(function, _FUNCTIONS["VOLT:DC"])
            for channel in group_channels:
                scan_functions[channel] = info
        channel_spec = _format_channels(channels)
        self._io.write_line(f"ROUT:SCAN (@{channel_spec})")
        self._scan_spec = channel_spec
        self._scan_functions = scan_functions
        info = next(iter(scan_functions.values()), _FUNCTIONS["VOLT:DC"])
        self.status = InstrumentStatus(
            function=info,
            nplc=f"{config.nplc:g}",
            range_text="SCAN",
            terminal="",
        )

    def read_scan(self, timeout_ms: int = 15000) -> list[tuple[int, Reading]]:
        channels = parse_channels(
            self._scan_spec if hasattr(self, "_scan_spec") else ""
        )
        raw = self._io.query_line("READ?", timeout_ms)
        tokens = [item.strip() for item in raw.split(",") if item.strip()]
        # 某些固件把一次扫描按多行返回；继续读到通道数足够为止。
        while len(tokens) < len(channels):
            more = self._io.read_line(timeout_ms)
            if not more:
                break
            tokens.extend(
                item.strip() for item in more.split(",") if item.strip()
            )
        if len(tokens) != len(channels):
            raise RuntimeError(
                f"34970A 扫描条数不符：期望 {len(channels)}，实际 {len(tokens)}"
            )
        fallback = self.status.function if self.status else _FUNCTIONS["VOLT:DC"]
        stamp = time.time_ns()
        result: list[tuple[int, Reading]] = []
        for channel, token in zip(channels, tokens, strict=True):
            info = self._scan_functions.get(channel, fallback)
            try:
                value = float(token)
            except ValueError as exc:
                raise RuntimeError(f"34970A 扫描读数无法解析：{token!r}") from exc
            result.append(
                (
                    channel,
                    Reading(
                        value=value,
                        unit=info.unit,
                        function_label=info.label,
                        ovld=abs(value) >= OVLD_THRESHOLD,
                        raw=token,
                        timestamp_ns=stamp,
                        channel=channel,
                    ),
                )
            )
        return result

    def read(
        self,
        timeout_ms: int = 5000,
        channel: int = 1,
    ) -> Reading:
        raw = self._io.query_line("READ?", timeout_ms)
        try:
            value = float(raw)
        except ValueError as exc:
            raise RuntimeError(f"34970A 读数无法解析：{raw!r}") from exc
        info = self.status.function if self.status else _FUNCTIONS["VOLT:DC"]
        return Reading(
            value=value,
            unit=info.unit,
            function_label=info.label,
            ovld=abs(value) >= OVLD_THRESHOLD,
            raw=raw,
            timestamp_ns=0,
            channel=channel,
        )

    def scpi(self, command: str) -> str:
        text = command.strip()
        if not text:
            return ""
        if "?" in text:
            return self._io.query_line(text, 5000)
        self._io.write_line(text)
        return ""

    def recover(self) -> None:
        """清掉迟到的 READ? 响应，恢复 GPIB/串口到可继续采集的状态。"""
        self._io.clear()
        self._io.flush()
        self._io.write_line("*CLS")
        self._io.query_line("*IDN?", 3000)

    def set_nplc(self, config: DaqConfig) -> None:
        """只更新积分时间，不重发 CONF/ROUT:SCAN，避免量程/通道继电器动作。"""
        if config.scan:
            if config.channels:
                groups: dict[str, list[int]] = {}
                for spec in config.channels:
                    if spec.function not in {"FREQ", "PER"}:
                        groups.setdefault(spec.function, []).append(spec.channel)
                for function, channels in groups.items():
                    sensor = "TEMP" if function == "TEMP" else function
                    self._io.write_line(
                        f"SENS:{sensor}:NPLC {config.nplc:g},"
                        f"(@{_format_channels(channels)})"
                    )
            else:
                if config.function in {"FREQ", "PER"}:
                    return
                sensor = "TEMP" if config.function == "TEMP" else config.function
                self._io.write_line(
                    f"SENS:{sensor}:NPLC {config.nplc:g},"
                    f"(@{_format_channels(parse_channels(config.scan_list))})"
                )
        else:
            if config.function in {"FREQ", "PER"}:
                return
            sensor = "TEMP" if config.function == "TEMP" else config.function
            self._io.write_line(
                f"SENS:{sensor}:NPLC {config.nplc:g},(@{int(config.channel)})"
            )
        if self.status is not None:
            self.status = replace(self.status, nplc=f"{config.nplc:g}")

    def set_display(self, on: bool) -> None:
        self._io.write_line(f"DISP {'ON' if on else 'OFF'}")

    def set_beeper(self, on: bool) -> None:
        self._io.write_line(
            f"SYST:BEEP:STAT {'ON' if on else 'OFF'}"
        )

    def set_remote(self, remote: bool) -> None:
        if self.interface == "gpib":
            method = getattr(
                self._io, "remote" if remote else "local", None
            )
            if method is not None:
                method()
        else:
            self._io.write_line("SYST:REM" if remote else "SYST:LOC")

    def close(self, restore_local: bool = True) -> None:
        if not self.is_open:
            return
        if restore_local and not self.local_only:
            try:
                if self.interface == "gpib":
                    local = getattr(self._io, "local", None)
                    if local is not None:
                        local()
                else:
                    self._io.write_line("SYST:LOC")
            except Exception:
                log.debug("34970A 回本地失败", exc_info=True)
        self._io.close()
