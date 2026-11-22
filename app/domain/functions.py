"""34401A 功能名、单位与查询前缀。"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import FunctionInfo

# FUNC? 的返回值（去掉引号、转大写）到显示信息。
_FUNCTION_TABLE: dict[str, FunctionInfo] = {
    "VOLT": FunctionInfo("VOLT", "VDC", "V", "VOLT", supports_nplc=True),
    "VOLT:AC": FunctionInfo("VOLT:AC", "VAC", "V", "VOLT:AC"),
    "CURR": FunctionInfo("CURR", "DCI", "A", "CURR", supports_nplc=True),
    "CURR:AC": FunctionInfo("CURR:AC", "ACI", "A", "CURR:AC"),
    "RES": FunctionInfo("RES", "2WΩ", "Ω", "RES", supports_nplc=True),
    "FRES": FunctionInfo("FRES", "4WΩ", "Ω", "FRES", supports_nplc=True),
    "FREQ": FunctionInfo("FREQ", "频率", "Hz", "FREQ"),
    "PER": FunctionInfo("PER", "周期", "s", "PER"),
    "CONT": FunctionInfo("CONT", "导通", "Ω", "CONT"),
    "DIOD": FunctionInfo("DIOD", "二极管", "V", "DIOD"),
}


@dataclass(frozen=True, slots=True)
class FunctionSpec:
    raw: str
    label: str
    unit: str
    conf_command: str
    prefix: str
    ranges: tuple[float, ...]
    supports_nplc: bool = False
    supports_ac_filter: bool = False
    supports_null: bool = True
    fixed_range: bool = False


FUNCTION_SPECS: tuple[FunctionSpec, ...] = (
    FunctionSpec("VOLT", "VDC", "V", "VOLT:DC", "VOLT", (0.1, 1, 10, 100, 1000), supports_nplc=True),
    FunctionSpec("VOLT:AC", "VAC", "V", "VOLT:AC", "VOLT:AC", (0.1, 1, 10, 100, 750), supports_ac_filter=True),
    FunctionSpec("CURR", "DCI", "A", "CURR:DC", "CURR", (0.01, 0.1, 1, 3), supports_nplc=True),
    FunctionSpec("CURR:AC", "ACI", "A", "CURR:AC", "CURR:AC", (0.01, 0.1, 1, 3), supports_ac_filter=True),
    FunctionSpec("RES", "2WΩ", "Ω", "RES", "RES", (100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000, 100_000_000), supports_nplc=True),
    FunctionSpec("FRES", "4WΩ", "Ω", "FRES", "FRES", (100, 1_000, 10_000, 100_000, 1_000_000, 10_000_000, 100_000_000), supports_nplc=True),
    FunctionSpec("FREQ", "频率", "Hz", "FREQ", "FREQ", (0.1, 1, 10, 100, 750), fixed_range=True),
    FunctionSpec("PER", "周期", "s", "PER", "PER", (0.1, 1, 10, 100, 750), fixed_range=True),
    FunctionSpec("CONT", "导通", "Ω", "CONT", "CONT", (1000,), supports_null=False, fixed_range=True),
    FunctionSpec("DIOD", "二极管", "V", "DIOD", "DIOD", (1.0,), supports_null=False, fixed_range=True),
)

_SPEC_BY_RAW = {spec.raw: spec for spec in FUNCTION_SPECS}
_SPEC_BY_LABEL = {spec.label: spec for spec in FUNCTION_SPECS}


def function_spec(raw: str) -> FunctionSpec:
    return _SPEC_BY_RAW.get(normalize_function(raw), FUNCTION_SPECS[0])


def function_spec_by_label(label: str) -> FunctionSpec | None:
    return _SPEC_BY_LABEL.get(label)


def normalize_function(raw: str) -> str:
    """去掉仪器的引号/空白，统一成大写。"""

    return raw.strip().strip('"').strip("'").upper()


def describe_function(raw: str) -> FunctionInfo:
    """把 FUNC? 的返回值转成显示信息；未知功能不猜测单位。"""

    normalized = normalize_function(raw)
    return _FUNCTION_TABLE.get(
        normalized,
        FunctionInfo(normalized or "未知", normalized or "未知", "", ""),
    )


def function_query_prefix(info: FunctionInfo) -> str:
    """返回当前功能的 SCPI 查询前缀；未知功能返回空串。"""

    return info.query_prefix


def display_digits(function_label: str, nplc: float, az: bool) -> str:
    """34401A 的导通/二极管固定 5½ 位，其余按 NPLC/AZ。"""

    if function_label in {"导通", "二极管"}:
        return "5½"
    return digits_for(nplc, az)


def digits_for(nplc: float, az: bool) -> str:
    """按 NPLC 选位数（34401A 手册：AZ 不改变显示位数）。"""

    if nplc <= 0.02:
        return "4½"
    if nplc <= 1.0:
        return "5½"
    return "6½"


def nplc_to_digits(nplc: float) -> str:
    """34401A 的分辨率由 NPLC 决定，这里只做显示映射。"""

    if nplc <= 0.02:
        return "4½"
    if nplc <= 1:
        return "5½"
    return "6½"


def digits_to_nplc(digits: str) -> float:
    """选位数时落到该档最快的 NPLC。"""

    if digits == "4½":
        return 0.02
    if digits == "5½":
        return 0.2
    return 10.0
