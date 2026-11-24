"""34970A 单通道读取（首期只做单通道，不做连续扫描）。"""

from __future__ import annotations

import logging
from dataclasses import dataclass

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
            self._io.write_line(
                f"SENS:{config.function}:NPLC {config.nplc:g},(@{channel})"
            )
            self.status = InstrumentStatus(
                function=_FUNCTIONS.get(config.function, _FUNCTIONS["VOLT:DC"]),
                nplc=f"{config.nplc:g}",
                range_text="AUTO",
                terminal="",
            )

    def read(self, timeout_ms: int = 5000) -> Reading:
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
        )

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
