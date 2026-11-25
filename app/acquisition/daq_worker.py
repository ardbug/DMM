"""34970A 单通道后台读取线程。"""

from __future__ import annotations

import queue
import time

from PySide6.QtCore import QThread, Signal

from app.instrument.daq34970a import Daq34970A, DaqConfig
from app.domain.models import SerialSettings
from app.transport.sicl_gpib import SiclGpibIO
from app.transport.visa_io import VisaIO


class DaqWorker(QThread):
    reading_received = Signal(object)
    scan_received = Signal(object)
    state_changed = Signal(str, str)
    error_occurred = Signal(str, str)
    status_updated = Signal(object)
    read_activity = Signal(bool)
    scpi_result = Signal(str, str)
    identity_ready = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._device: Daq34970A | None = None
        self._config: DaqConfig | None = None
        self._last_hardware_config: DaqConfig | None = None
        self._acquiring = False
        self._shutdown = False
        self._read_recovered = False

    def submit(self, kind: str, payload=None) -> None:
        self._commands.put((kind, payload))

    def run(self) -> None:
        while not self._shutdown:
            if self._acquiring:
                self._read_once()
                period = 1.0 / max(
                    0.1,
                    float(
                        self._config.scan_rate
                        if self._config and self._config.scan
                        else (self._config.rate if self._config else 1.0)
                    ),
                )
                deadline = time.monotonic() + max(0.05, period)
                while time.monotonic() < deadline and self._acquiring:
                    try:
                        kind, payload = self._commands.get(
                            timeout=min(
                                0.05,
                                max(0.0, deadline - time.monotonic()),
                            )
                        )
                    except queue.Empty:
                        continue
                    self._dispatch(kind, payload)
            else:
                try:
                    kind, payload = self._commands.get(timeout=0.1)
                except queue.Empty:
                    continue
                self._dispatch(kind, payload)

    def _dispatch(self, kind: str, payload) -> None:
        try:
            self._handle(kind, payload)
        except Exception as exc:
            self._acquiring = False
            self.error_occurred.emit("34970A 操作失败", str(exc))
            self._set_error_state(str(exc))

    def _set_error_state(self, detail: str) -> None:
        # 配置错误不应把已建立的 GPIB/串口连接变成“已断开”。
        if self._device is not None and self._device.is_open:
            self._set_state("ready", f"操作失败，连接保持：{detail}")
        else:
            self._set_state("error", detail)

    def _handle(self, kind: str, payload) -> None:
        if kind == "open":
            settings: SerialSettings = payload
            io = SiclGpibIO() if settings.interface == "gpib" else VisaIO()
            device = Daq34970A(io)
            self._set_state("opening", f"正在打开 {settings.resource}…")
            device.open(settings)
            self._device = device
            self._config = None
            self.identity_ready.emit(device.identity)
            self._set_state("ready", "34970A 已连接")
        elif kind == "close":
            self._acquiring = False
            device, self._device = self._device, None
            self._config = None
            self._last_hardware_config = None
            if device is not None:
                device.close()
            self._set_state("disconnected", "34970A 已关闭")
        elif kind == "start":
            self._config = payload
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            old_config = self._last_hardware_config
            incremental = (
                old_config is not None
                and self._same_hardware(old_config, self._config)
            )
            if incremental:
                if old_config.nplc != self._config.nplc:
                    self._device.set_nplc(self._config)
                self._last_hardware_config = self._config
            else:
                self._set_state("opening", "正在配置通道…")
                self._device.configure(self._config)
                self._last_hardware_config = self._config
            if self._device.status is not None:
                self.status_updated.emit(self._device.status)
            self._acquiring = True
            self._set_state("acquiring", "34970A 连续读取中")
        elif kind == "stop":
            self._acquiring = False
            self._set_state("ready", "34970A 已停止")
        elif kind == "single":
            self._config = payload
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            self._device.configure(self._config)
            if self._device.status is not None:
                self.status_updated.emit(self._device.status)
            self._read_once()
        elif kind == "display":
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            self._device.set_display(bool(payload))
        elif kind == "beeper":
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            self._device.set_beeper(bool(payload))
        elif kind == "remote":
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            self._device.set_remote(bool(payload))
        elif kind == "scpi":
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            command = str(payload)
            self.scpi_result.emit(
                command, self._device.scpi(command)
            )
        elif kind == "shutdown":
            self._acquiring = False
            device, self._device = self._device, None
            self._config = None
            self._last_hardware_config = None
            if device is not None:
                device.close()
            self._set_state("disconnected", "34970A 已关闭")
            self._shutdown = True

    @staticmethod
    def _same_hardware(a, b) -> bool:
        return (
            a.channel,
            a.function,
            a.range_value,
            a.temperature,
            a.temp_unit,
            a.scan,
            a.scan_list,
        ) == (
            b.channel,
            b.function,
            b.range_value,
            b.temperature,
            b.temp_unit,
            b.scan,
            b.scan_list,
        )

    def _read_once(self) -> None:
        assert self._device is not None
        self.read_activity.emit(True)
        try:
            if self._config is not None and self._config.scan:
                samples = self._device.read_scan(15000)
                self.scan_received.emit(samples)
                if samples:
                    self.reading_received.emit(samples[-1][1])
                return
            reading = self._device.read(
                15000,
                self._config.channel if self._config else 1,
            )
            reading = reading.__class__(
                value=reading.value,
                unit=reading.unit,
                function_label=reading.function_label,
                ovld=reading.ovld,
                raw=reading.raw,
                timestamp_ns=time.time_ns(),
            )
            self.reading_received.emit(reading)
            self._read_recovered = False
        except Exception as exc:
            if self._recover_read_failure():
                self.error_occurred.emit(
                    "34970A 读数超时",
                    "仪器未按时返回，已清总线并继续采集",
                )
                return
            self.error_occurred.emit("34970A 读数失败", str(exc))
            self._acquiring = False
            self._set_error_state(str(exc))
        finally:
            self.read_activity.emit(False)

    def _recover_read_failure(self) -> bool:
        if self._read_recovered or self._device is None:
            return False
        self._read_recovered = True
        try:
            self._device.recover()
            return True
        except Exception:
            return False

    def _set_state(self, state: str, detail: str) -> None:
        self.state_changed.emit(state, detail)

    def shutdown(self) -> None:
        self._commands.put(("shutdown", None))
        # 扫描一次最多可能等待 15 s，不能在读线程仍运行时销毁对象。
        self.wait(20000)
