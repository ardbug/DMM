"""跨层传递的不可变数据模型。"""

from __future__ import annotations

from dataclasses import dataclass

from app.constants import (
    DEFAULT_BAUD_RATE,
    DEFAULT_DATA_BITS,
    DEFAULT_FLOW_CONTROL,
    DEFAULT_PARITY,
    DEFAULT_RESOURCE,
    DEFAULT_STOP_BITS,
    DEFAULT_TIMEOUT_MS,
)


@dataclass(frozen=True, slots=True)
class SerialSettings:
    """VISA 串口参数。GPIB 时只使用 resource。"""

    resource: str = DEFAULT_RESOURCE
    baud_rate: int = DEFAULT_BAUD_RATE
    data_bits: int = DEFAULT_DATA_BITS
    parity: str = DEFAULT_PARITY
    stop_bits: int = DEFAULT_STOP_BITS
    flow_control: str = DEFAULT_FLOW_CONTROL
    timeout_ms: int = DEFAULT_TIMEOUT_MS


@dataclass(frozen=True, slots=True)
class FunctionInfo:
    """当前功能的显示信息。"""

    raw: str
    label: str
    unit: str
    query_prefix: str
    supports_nplc: bool = False


@dataclass(frozen=True, slots=True)
class InstrumentStatus:
    """从仪器读回的只读状态。"""

    function: FunctionInfo
    nplc: str = ""
    range_text: str = ""
    terminal: str = ""


@dataclass(frozen=True, slots=True)
class AcquisitionConfig:
    """采集、功能、量程与仪器设置。"""

    nplc: float = 1.0
    digits: str = "5½"
    rate: float = 30.0
    az: bool = False
    function: str = "VOLT"
    range_mode: str = "auto"  # auto / manual
    range_value: float = 0.0
    ac_filter: int = 20
    input_impedance: str = "10M"  # 10M / high (>10 GΩ)
    null_enabled: bool = False
    null_value: float = 0.0
    average_enabled: bool = False
    average_count: int = 10


@dataclass(frozen=True, slots=True)
class Reading:
    """一条读数。"""

    value: float
    unit: str
    function_label: str
    ovld: bool
    raw: str
    timestamp_ns: int = 0
    average_count: int = 0


@dataclass(frozen=True, slots=True)
class BatchRead:
    """Dmm 层返回的原始批次与时序。"""

    readings: tuple[Reading, ...]
    start_ns: int
    end_ns: int


@dataclass(frozen=True, slots=True)
class Batch:
    """I/O 线程 → UI 的不可变批次。"""

    readings: tuple[Reading, ...]
    config: AcquisitionConfig
    config_version: int
    batch_id: int
    start_ns: int
    end_ns: int
    range_text: str = ""


@dataclass(frozen=True, slots=True)
class ScpiError:
    """错误队列条目。"""

    code: int
    raw: str

    @property
    def is_no_error(self) -> bool:
        return self.code == 0
