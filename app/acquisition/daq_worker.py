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

    def __init__(self) -> None:
        super().__init__()
        self._commands: queue.Queue[tuple] = queue.Queue()
        self._device: Daq34970A | None = None
        self._config: DaqConfig | None = None
        self._acquiring = False
        self._shutdown = False

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
            self.error_occurred.emit("34970A 操作失败", str(exc))
            self._set_state("error", str(exc))

    def _handle(self, kind: str, payload) -> None:
        if kind == "open":
            settings: SerialSettings = payload
            io = SiclGpibIO() if settings.interface == "gpib" else VisaIO()
            device = Daq34970A(io)
            self._set_state("opening", f"正在打开 {settings.resource}…")
            device.open(settings)
            self._device = device
            self._set_state("ready", "34970A 已连接")
        elif kind == "close":
            device, self._device = self._device, None
            if device is not None:
                device.close()
            self._set_state("disconnected", "34970A 已关闭")
        elif kind == "start":
            self._config = payload
            if self._device is None:
                raise RuntimeError("34970A 未打开")
            self._set_state("opening", "正在配置通道…")
            self._device.configure(self._config)
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
        elif kind == "shutdown":
            self._acquiring = False
            device, self._device = self._device, None
            if device is not None:
                device.close()
            self._set_state("disconnected", "34970A 已关闭")
            self._shutdown = True

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
            reading = self._device.read(5000)
            reading = reading.__class__(
                value=reading.value,
                unit=reading.unit,
                function_label=reading.function_label,
                ovld=reading.ovld,
                raw=reading.raw,
                timestamp_ns=time.time_ns(),
            )
            self.reading_received.emit(reading)
        except Exception as exc:
            self.error_occurred.emit("34970A 读数失败", str(exc))
            self._acquiring = False
            self._set_state("error", str(exc))
        finally:
            self.read_activity.emit(False)

    def _set_state(self, state: str, detail: str) -> None:
        self.state_changed.emit(state, detail)

    def shutdown(self) -> None:
        self._commands.put(("shutdown", None))
        self.wait(6000)
