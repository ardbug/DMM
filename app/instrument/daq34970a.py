"""34970A 单通道读取（首期只做单通道，不做连续扫描）。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace

from app.constants import OVLD_THRESHOLD
from app.domain.models import InstrumentStatus, Reading, SerialSettings
from app.domain.functions import FunctionInfo

log = logging.getLogger(__name__)


def _info(raw: str, label: str, unit: str) -> FunctionInfo:
    return FunctionInfo(raw=raw, label=label, unit=unit, query_prefix=raw)


_FUNCTIONS = {
    "VOLT:DC": _info("VOLT:DC", "DCV", "V"),
    "VOLT:AC": _info("VOLT:AC", "ACV", "V"),
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


def parse_channels(spec: str) -> list[int]:
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
            if not 101 <= channel <= 122:
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

    def configure(self, config: DaqConfig) -> None:
        if config.scan:
            self._configure_scan(config)
            return
        channel = int(config.channel)
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
        channels = parse_channels(config.scan_list)
        current = [ch for ch in channels if ch >= 121]
        if current and len(current) != len(channels):
            raise ValueError("扫描列表不能混用电流通道 121/122 和复用通道")
        if current and config.function not in {"CURR:DC", "CURR:AC"}:
            raise ValueError("通道 121/122 只能扫描电流")
        channel_spec = _format_channels(channels)
        if config.function == "TEMP":
            conf = _TEMP_CONF.get(config.temperature, "CONF:TEMP TC,K")
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
            self._io.write_line(f"UNIT:TEMP {config.temp_unit},(@{channel_spec})")
            self._io.write_line(
                f"SENS:TEMP:NPLC {config.nplc:g},(@{channel_spec})"
            )
            info = _FUNCTIONS["TEMP"]
        else:
            self._io.write_line(f"CONF:{config.function} (@{channel_spec})")
            if config.function not in {"FREQ", "PER"}:
                self._io.write_line(
                    f"SENS:{config.function}:NPLC {config.nplc:g},(@{channel_spec})"
                )
            info = _FUNCTIONS.get(config.function, _FUNCTIONS["VOLT:DC"])
        self._io.write_line(f"ROUT:SCAN (@{channel_spec})")
        self._scan_spec = channel_spec
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
        info = self.status.function if self.status else _FUNCTIONS["VOLT:DC"]
        stamp = time.time_ns()
        result: list[tuple[int, Reading]] = []
        for channel, token in zip(channels, tokens, strict=True):
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
        if text.endswith("?"):
            return self._io.query_line(text, 5000)
        self._io.write_line(text)
        return ""

    def set_nplc(self, config: DaqConfig) -> None:
        """只更新积分时间，不重发 CONF/ROUT:SCAN，避免量程/通道继电器动作。"""
        if config.function in {"FREQ", "PER"}:
            return
        if config.scan:
            channels = _format_channels(parse_channels(config.scan_list))
        else:
            channels = str(int(config.channel))
        sensor = "TEMP" if config.function == "TEMP" else config.function
        self._io.write_line(
            f"SENS:{sensor}:NPLC {config.nplc:g},(@{channels})"
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
