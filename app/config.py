"""用户配置：QSettings INI，不写注册表。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QSettings

from app.constants import (
    DEFAULT_BAUD_RATE,
    DEFAULT_DATA_BITS,
    DEFAULT_FLOW_CONTROL,
    DEFAULT_PARITY,
    DEFAULT_RESOURCE,
    DEFAULT_STOP_BITS,
    DEFAULT_TIMEOUT_MS,
)
from app.domain.models import AcquisitionConfig, SerialSettings


def default_config_path() -> Path:
    base = os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    return root / "34401A_Upper" / "settings.ini"


class AppConfig:
    """薄封装，避免各界面直接拼 QSettings 的键。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._settings = QSettings(str(self.path), QSettings.Format.IniFormat)

    # ---- 串口 ----
    def serial_settings(self) -> SerialSettings:
        s = self._settings
        return SerialSettings(
            resource=str(s.value("connection/resource", DEFAULT_RESOURCE)),
            baud_rate=_int_value(s.value("connection/baud_rate"), DEFAULT_BAUD_RATE),
            data_bits=_int_value(s.value("connection/data_bits"), DEFAULT_DATA_BITS),
            parity=str(s.value("connection/parity", DEFAULT_PARITY)),
            stop_bits=_int_value(s.value("connection/stop_bits"), DEFAULT_STOP_BITS),
            flow_control=str(s.value("connection/flow_control", DEFAULT_FLOW_CONTROL)),
            timeout_ms=_int_value(s.value("connection/timeout_ms"), DEFAULT_TIMEOUT_MS),
        )

    def save_serial_settings(self, settings: SerialSettings) -> None:
        s = self._settings
        s.setValue("connection/resource", settings.resource)
        s.setValue("connection/baud_rate", settings.baud_rate)
        s.setValue("connection/data_bits", settings.data_bits)
        s.setValue("connection/parity", settings.parity)
        s.setValue("connection/stop_bits", settings.stop_bits)
        s.setValue("connection/flow_control", settings.flow_control)
        s.setValue("connection/timeout_ms", settings.timeout_ms)
        s.sync()

    # ---- 采集 ----
    def acquisition_config(self) -> AcquisitionConfig:
        s = self._settings
        return AcquisitionConfig(
            nplc=_float_value(s.value("acq/nplc"), 1.0),
            digits=str(s.value("acq/digits", "5½")),
            rate=_float_value(s.value("acq/rate"), 30.0),
            az=_bool_value(s.value("acq/az"), False),
            function=str(s.value("acq/function", "VOLT")),
            # 量程不做跨进程记忆：每次启动都从自动量程开始。
            range_mode="auto",
            range_value=0.0,
            ac_filter=_int_value(s.value("acq/ac_filter"), 20),
            input_impedance=str(s.value("acq/input_impedance", "10M")),
            null_enabled=_bool_value(s.value("acq/null_enabled"), False),
            null_value=_float_value(s.value("acq/null_value"), 0.0),
        )

    def save_acquisition_config(self, config: AcquisitionConfig) -> None:
        s = self._settings
        s.setValue("acq/nplc", config.nplc)
        s.setValue("acq/digits", config.digits)
        s.setValue("acq/rate", config.rate)
        s.setValue("acq/az", config.az)
        s.setValue("acq/function", config.function)
        # 量程不落盘；会话内在 DmmPanel 内记忆即可。
        s.setValue("acq/range_mode", "auto")
        s.setValue("acq/range_value", 0.0)
        s.setValue("acq/ac_filter", config.ac_filter)
        s.setValue("acq/input_impedance", config.input_impedance)
        s.setValue("acq/null_enabled", config.null_enabled)
        s.setValue("acq/null_value", config.null_value)
        s.sync()

    def range_memory(self) -> dict[str, tuple[bool, float]]:
        raw = str(self._settings.value("acq/range_memory", "") or "")
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        result: dict[str, tuple[bool, float]] = {}
        if isinstance(data, dict):
            for key, item in data.items():
                if isinstance(item, list) and len(item) == 2:
                    result[str(key)] = (bool(item[0]), _float_value(item[1], 0.0))
        return result

    def save_range_memory(
        self, memory: dict[str, tuple[bool, float]]
    ) -> None:
        data = {
            str(key): [bool(auto), float(value)]
            for key, (auto, value) in memory.items()
        }
        self._settings.setValue(
            "acq/range_memory", json.dumps(data, ensure_ascii=False)
        )
        self._settings.sync()

    # ---- CSV ----
    def csv_directory(self) -> Path:
        raw = str(self._settings.value("csv/directory", "") or "").strip()
        if raw:
            return Path(raw)
        return Path.home() / "Documents" / "34401A数据"

    def save_csv_directory(self, path: str) -> None:
        self._settings.setValue("csv/directory", str(path))
        self._settings.sync()

    # ---- 仪器开关 ----
    def instrument_switches(self) -> tuple[bool, bool]:
        s = self._settings
        return (
            _bool_value(s.value("instrument/display_on"), True),
            _bool_value(s.value("instrument/beeper_on"), True),
        )

    def save_instrument_switches(self, display_on: bool, beeper_on: bool) -> None:
        s = self._settings
        s.setValue("instrument/display_on", display_on)
        s.setValue("instrument/beeper_on", beeper_on)
        s.sync()

    def remote_enabled(self) -> bool:
        return _bool_value(
            self._settings.value("instrument/remote_enabled"), True
        )

    def save_remote_enabled(self, enabled: bool) -> None:
        self._settings.setValue("instrument/remote_enabled", bool(enabled))
        self._settings.sync()

    # ---- 显示/精度记忆 ----
    def unit_modes(self) -> dict[str, str]:
        return {
            base: str(self._settings.value(f"ui/unit_{base}", "auto"))
            for base in ("V", "A", "Ω", "Hz", "s")
        }

    def save_unit_mode(self, base: str, mode: str) -> None:
        self._settings.setValue(f"ui/unit_{base}", mode)
        self._settings.sync()

    def accuracy_tier(self) -> str:
        value = str(self._settings.value("ui/accuracy_tier", "1y"))
        return value if value in {"24h", "90d", "1y"} else "1y"

    def save_accuracy_tier(self, tier: str) -> None:
        self._settings.setValue("ui/accuracy_tier", tier)
        self._settings.sync()

    def scale_factor(self) -> int:
        value = _int_value(self._settings.value("ui/scale_percent"), 100)
        return value if value in {75, 100, 125, 150, 200} else 100

    def save_scale_factor(self, percent: int) -> None:
        self._settings.setValue("ui/scale_percent", int(percent))
        self._settings.sync()

    def floating_settings(self) -> tuple[int, int]:
        percent = _int_value(self._settings.value("ui/floating_percent"), 100)
        opacity = _int_value(self._settings.value("ui/floating_opacity"), 100)
        return max(50, min(200, percent)), max(20, min(100, opacity))

    def save_floating_settings(self, percent: int, opacity: int) -> None:
        self._settings.setValue(
            "ui/floating_percent", max(50, min(200, int(percent)))
        )
        self._settings.setValue(
            "ui/floating_opacity", max(20, min(100, int(opacity)))
        )
        self._settings.sync()

    def ac_band(self) -> str:
        return str(self._settings.value("ui/ac_band", "10-20k"))

    def save_ac_band(self, band: str) -> None:
        self._settings.setValue("ui/ac_band", band)
        self._settings.sync()

    # ---- 界面 ----
    def window_geometry(self) -> bytes | None:
        value = self._settings.value("ui/window_geometry")
        if value is None:
            return None
        try:
            return bytes(value)
        except (TypeError, ValueError):
            return None

    def save_window_geometry(self, geometry: bytes) -> None:
        self._settings.setValue("ui/window_geometry", geometry)
        self._settings.sync()

    def last_save_dir(self) -> str:
        return str(self._settings.value("storage/last_dir", str(Path.home() / "Documents")))

    def save_last_save_dir(self, path: str) -> None:
        self._settings.setValue("storage/last_dir", path)
        self._settings.sync()


def _int_value(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _float_value(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _bool_value(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return fallback
    return bool(value)
