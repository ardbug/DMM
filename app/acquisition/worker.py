"""I/O 线程：连接、单次读数、连续批量采集。

所有 VISA 调用只发生在这个线程。UI 通过命令队列提交请求，
通过 Qt 信号接收状态、批次和错误。
"""

from __future__ import annotations

import logging
import queue
import time
from dataclasses import replace
from typing import TypeAlias

from PySide6.QtCore import QThread, Signal

from app.acquisition.commands import (
    CloseCommand,
    ConfigureAcquisitionCommand,
    IdentifyCommand,
    ListResourcesCommand,
    OpenCommand,
    ScpiCommand,
    SetBeeperCommand,
    SetDisplayCommand,
    ShutdownCommand,
    SingleReadCommand,
    StartAcquisitionCommand,
    StopAcquisitionCommand,
)
from app.acquisition.scheduler import RatePlan, plan_rate
from app.domain.models import AcquisitionConfig, Batch, InstrumentStatus, Reading
from app.instrument.dmm import Dmm
from app.transport.visa_io import VisaIO

log = logging.getLogger(__name__)

Command: TypeAlias = (
    OpenCommand
    | CloseCommand
    | IdentifyCommand
    | SingleReadCommand
    | ListResourcesCommand
    | ConfigureAcquisitionCommand
    | StartAcquisitionCommand
    | StopAcquisitionCommand
    | SetDisplayCommand
    | SetBeeperCommand
    | ScpiCommand
    | ShutdownCommand
)


class WorkerState:
    DISCONNECTED = "disconnected"
    OPENING = "opening"
    LOCAL = "local"
    READY = "ready"
    READING = "reading"
    ACQUIRING = "acquiring"
    STOPPING = "stopping"
    CLOSING = "closing"
    ERROR = "error"


class AcqWorker(QThread):
    """所有 VISA 调用的唯一线程。"""

    state_changed = Signal(str, str)
    identity_received = Signal(str)
    status_updated = Signal(object)
    reading_received = Signal(object)
    batch_received = Signal(object)
    scpi_result = Signal(str, str)
    resources_listed = Signal(object)
    error_occurred = Signal(str, str)
    notice = Signal(str)
    config_applied = Signal(int, object)
    plan_updated = Signal(object)
    read_activity = Signal(bool)

    def __init__(self) -> None:
        super().__init__()
        self._commands: queue.Queue[Command] = queue.Queue()
        self._dmm: Dmm | None = None
        self._shutdown = False
        self._state = WorkerState.DISCONNECTED

        self._acquisition: AcquisitionConfig | None = None
        self._plan: RatePlan | None = None
        self._acquiring = False
        self._stop_requested = False
        self._first_batch = True
        self._next_batch_at = 0
        self._batch_id = 0
        self._config_version = 0
        self._last_ts_ns = 0
        self._sample_count = 0
        self._first_count = 1
        self._average_buffer: list[Reading] = []
        self._average_start_ns = 0

    def submit(self, command: Command) -> None:
        if self._shutdown:
            return
        self._commands.put(command)

    def shutdown(self) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self._commands.put(ShutdownCommand())

    def run(self) -> None:
        log.info("I/O 线程启动")
        self._set_state(WorkerState.DISCONNECTED, "串口未打开")
        try:
            while not self._shutdown:
                # 先处理所有已排队命令，保证停止/改配置能插进批次边界。
                while True:
                    try:
                        command = self._commands.get_nowait()
                    except queue.Empty:
                        break
                    if isinstance(command, ShutdownCommand):
                        return
                    try:
                        self._handle(command)
                    except Exception as exc:
                        log.exception("命令执行失败：%s", command)
                        self._abort_with_error("操作失败", _format_error(exc))
                        break

                if self._shutdown:
                    break
                if self._acquiring:
                    if self._stop_requested:
                        self._finish_acquisition()
                        continue
                    try:
                        self._acquisition_step()
                    except Exception as exc:
                        log.exception("采集批次失败")
                        self._handle_acquisition_failure(exc)
                else:
                    try:
                        command = self._commands.get(timeout=0.05)
                    except queue.Empty:
                        continue
                    if isinstance(command, ShutdownCommand):
                        break
                    try:
                        self._handle(command)
                    except Exception as exc:
                        log.exception("命令执行失败：%s", command)
                        self._abort_with_error("操作失败", _format_error(exc))
        finally:
            self._close_session()
            log.info("I/O 线程结束")

    # ---------- 命令分发 ----------

    def _handle(self, command: Command) -> None:
        if isinstance(command, OpenCommand):
            self._open(command)
        elif isinstance(command, CloseCommand):
            self._close()
        elif isinstance(command, IdentifyCommand):
            self._identify()
        elif isinstance(command, SingleReadCommand):
            self._single_read()
        elif isinstance(command, ListResourcesCommand):
            self._list_resources()
        elif isinstance(command, ConfigureAcquisitionCommand):
            self._configure(command.config)
        elif isinstance(command, StartAcquisitionCommand):
            self._start_acquisition(command.config)
        elif isinstance(command, StopAcquisitionCommand):
            self._request_stop()
        elif isinstance(command, SetDisplayCommand):
            self._set_display(command.on)
        elif isinstance(command, SetBeeperCommand):
            self._set_beeper(command.on)
        elif isinstance(command, ScpiCommand):
            self._scpi(command.text)
        else:
            log.warning("未知命令：%r", command)

    # ---------- 连接 ----------

    def _open(self, command: OpenCommand) -> None:
        if self._dmm is not None and self._dmm.is_open:
            self._close()
        self._acquisition = None
        self._plan = None
        self._set_state(WorkerState.OPENING, f"正在打开 {command.settings.resource}…")
        dmm = Dmm()
        if not command.remote:
            try:
                dmm.open_local(command.settings)
            except Exception:
                dmm.close(restore_local=False)
                raise
            self._dmm = dmm
            self._set_state(WorkerState.LOCAL, "串口已打开（RMT 关闭，仅本地）")
            self.notice.emit("RMT 关闭：只打开串口，不控制仪器")
            return
        try:
            identity = dmm.open(
                command.settings,
                attempts=command.attempts,
                handshake_timeout_ms=command.handshake_timeout_ms,
            )
        except Exception:
            dmm.close(restore_local=True)
            raise
        self._dmm = dmm
        self.identity_received.emit(identity)
        if dmm.status is not None:
            self.status_updated.emit(dmm.status)
        self._set_state(WorkerState.READY, "远程模式，就绪")

    def _close(self) -> None:
        if self._dmm is None:
            self._set_state(WorkerState.DISCONNECTED, "串口未打开")
            return
        local_only = self._dmm.local_only
        self._acquiring = False
        self._stop_requested = False
        self._set_state(
            WorkerState.CLOSING,
            "正在关闭串口…" if local_only else "正在回本地并关闭…",
        )
        dmm, self._dmm = self._dmm, None
        dmm.close(restore_local=not local_only)
        if local_only:
            self._set_state(WorkerState.DISCONNECTED, "串口已关闭")
            self.notice.emit("串口已关闭")
        else:
            self._set_state(WorkerState.DISCONNECTED, "已关闭，仪器已回本地")
            self.notice.emit("串口已关闭，仪器已回本地模式")

    def _identify(self) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        identity = self._dmm.identify()
        self.identity_received.emit(identity)
        self.notice.emit("*IDN? 已返回")

    # ---------- 配置 ----------

    def _configure(self, config: AcquisitionConfig) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        previous = self._acquisition
        # 只改采样率/显示位数/平均设置时不必重发仪器配置。
        if previous is None or self._instrument_config_changed(previous, config):
            self._dmm.apply_config(config)
            self._sample_count = 0
        if (
            previous is None
            or previous.average_enabled != config.average_enabled
            or previous.average_count != config.average_count
        ):
            self._clear_average()
        self._acquisition = config
        self._plan = plan_rate(config)
        self._config_version += 1
        self.status_updated.emit(self._dmm.status)
        self.config_applied.emit(self._config_version, config)
        self.plan_updated.emit(self._plan)
        if self._acquiring:
            # 下一批按新设置走，不打断当前批次。
            self._next_batch_at = time.perf_counter_ns() + self._plan.period_ns
        self.notice.emit(f"配置已应用：NPLC {config.nplc:g} / {config.digits}")

    # ---------- 连续采集 ----------

    def _start_acquisition(self, config: AcquisitionConfig) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        if self._acquiring:
            return
        # MainWindow 在连接后会先下发一次配置；相同配置不要重复下发，
        # 否则首条读数会被一组无谓的 SCPI + 错误队列查询拖慢。
        if (
            self._acquisition is None
            or self._instrument_config_changed(self._acquisition, config)
            or self._dmm.status is None
        ):
            self._dmm.apply_config(config)
        self._acquisition = config
        self._plan = plan_rate(config)
        self._config_version += 1
        self._batch_id = 0
        self._last_ts_ns = 0
        self._first_batch = True
        self._stop_requested = False
        self._acquiring = True
        self._sample_count = 0
        self._clear_average()
        # 低速率时第一批直接取满批：例如 10/s、5 条/批约 120ms，
        # 既满足首读 <200ms，又不会出现“先来一条、等 0.5s 再来一批”的停顿。
        self._first_count = 1
        if (
            self._plan is not None
            and self._plan.batch_size > 1
            and self._plan.batch_size / max(self._plan.capability, 1e-9) <= 0.15
        ):
            self._first_count = self._plan.batch_size
        self.status_updated.emit(self._dmm.status)
        self.config_applied.emit(self._config_version, config)
        self.plan_updated.emit(self._plan)
        self._set_state(WorkerState.ACQUIRING, "正在连续采集…")
        if self._plan.limited:
            self.notice.emit(self._plan.note)

    def _request_stop(self) -> None:
        if not self._acquiring:
            return
        self._stop_requested = True
        self._set_state(WorkerState.STOPPING, "正在停止，等待当前批次读完…")

    def _finish_acquisition(self) -> None:
        self._acquiring = False
        self._stop_requested = False
        self._first_batch = True
        self._clear_average()
        self._set_state(WorkerState.READY, "已停止，远程模式就绪")

    def _acquisition_step(self) -> None:
        if not self._acquiring or self._dmm is None or self._plan is None:
            return

        now = time.perf_counter_ns()
        if not self._first_batch and now < self._next_batch_at:
            time.sleep(min(0.02, (self._next_batch_at - now) / 1_000_000_000))
            return

        if self._first_batch:
            # 高速率先取 1 条保证首读；低速率直接取满批避免启动停顿。
            batch_started = time.perf_counter_ns()
            self._ensure_sample_count(self._first_count)
            self._read_and_emit(self._first_count)
            if not self._acquiring or self._dmm is None or self._plan is None:
                return
            if self._first_count == 1:
                self._ensure_sample_count(self._plan.batch_size)
            self._first_batch = False
            # 从本批开始时刻排下一批，而不是从“读完时刻”再等一个周期；
            # 否则首条到第二条会出现 2 倍周期，低速时肉眼可见一次停顿。
            self._next_batch_at = batch_started + self._plan.period_ns
            return

        self._ensure_sample_count(self._plan.batch_size)
        self._read_and_emit(self._plan.batch_size)
        now_after = time.perf_counter_ns()
        if self._plan is not None:
            self._next_batch_at = max(
                self._next_batch_at + self._plan.period_ns,
                now_after,
            )

    @staticmethod
    def _instrument_config_changed(old: AcquisitionConfig, new: AcquisitionConfig) -> bool:
        fields = (
            "function",
            "range_mode",
            "range_value",
            "nplc",
            "az",
            "ac_filter",
            "input_impedance",
            "null_enabled",
            "null_value",
        )
        return any(getattr(old, name) != getattr(new, name) for name in fields)

    def _ensure_sample_count(self, count: int) -> None:
        if self._sample_count == count or self._dmm is None:
            return
        self._dmm.set_sample_count(count)
        self._sample_count = count

    def _read_timeout_ms(self) -> int:
        config = self._acquisition
        if config is None:
            return 5000
        # NPLC 100 本身约 2 s/次；2W/4W 自动量程在开路时可能连续换挡，
        # 5 s 固定超时会把正常测量误判成通信故障。
        expected_ms = int(max(0.02, config.nplc) * 20 * 10) + 3000
        if config.range_mode == "auto":
            expected_ms += 3000
        return max(5000, min(30000, expected_ms))

    def _clear_average(self) -> None:
        self._average_buffer = []
        self._average_start_ns = 0

    def _read_and_emit(self, count: int) -> None:
        assert self._dmm is not None
        self.read_activity.emit(True)
        try:
            batch_read = self._dmm.read_batch(
                count, timeout_ms=self._read_timeout_ms()
            )
        finally:
            self.read_activity.emit(False)

        readings = []
        last_ts = self._last_ts_ns
        for reading in batch_read.readings:
            ts = max(reading.timestamp_ns, last_ts + 1)
            if ts != reading.timestamp_ns:
                reading = replace(reading, timestamp_ns=ts)
            readings.append(reading)
            last_ts = ts
        self._last_ts_ns = last_ts

        config = self._acquisition or AcquisitionConfig()
        target = (
            max(1, int(config.average_count))
            if config.average_enabled
            else 1
        )
        if config.average_enabled:
            if not self._average_buffer:
                self._average_start_ns = batch_read.start_ns
            self._average_buffer.extend(readings)
            if len(self._average_buffer) < target:
                return
            averages = self._average_buffer[:target]
            del self._average_buffer[:target]
            start_ns = self._average_start_ns
            any_ovld = any(item.ovld for item in averages)
            last = averages[-1]
            if any_ovld:
                averaged = replace(
                    last,
                    value=0.0,
                    ovld=True,
                    raw=f"AVG {target} OVLD",
                    timestamp_ns=last_ts,
                    average_count=target,
                )
            else:
                values = [item.value for item in averages]
                averaged = replace(
                    last,
                    value=sum(values) / len(values),
                    ovld=False,
                    raw=f"AVG {target}",
                    timestamp_ns=last_ts,
                    average_count=target,
                )
            self._average_start_ns = self._last_ts_ns
            readings = [averaged]
            start_ns = start_ns if start_ns else batch_read.start_ns
        else:
            start_ns = batch_read.start_ns

        self._batch_id += 1
        batch = Batch(
            readings=tuple(readings),
            config=config,
            config_version=self._config_version,
            batch_id=self._batch_id,
            start_ns=start_ns,
            end_ns=max(batch_read.end_ns, last_ts),
            range_text=self._dmm.status.range_text if self._dmm.status else "",
        )
        self.batch_received.emit(batch)

    def _handle_acquisition_failure(self, exc: Exception) -> None:
        self._acquiring = False
        self._stop_requested = False
        message = _format_error(exc)
        log.warning("连续采集失败，尝试恢复：%s", message)
        self.error_occurred.emit("连续采集失败", message)
        assert self._dmm is not None
        if self._dmm.recover():
            log.info("通信恢复成功，采集已停止")
            self.status_updated.emit(self._dmm.status)
            self._set_state(WorkerState.READY, "通信已恢复，采集已停止")
        else:
            log.error("通信恢复失败")
            self._close_after_failure()
            self._set_state(WorkerState.ERROR, "通信恢复失败，请重新打开串口")

    # ---------- 单次/诊断 ----------

    def _single_read(self) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        if self._acquiring:
            raise RuntimeError("连续采集进行中，不能单次读数")
        config = self._acquisition
        target = (
            max(1, int(config.average_count))
            if config is not None and config.average_enabled
            else 1
        )
        detail = f"正在平均 {target} 次…" if target > 1 else "正在单次读数…"
        self._set_state(WorkerState.READING, detail)
        try:
            samples = []
            for _ in range(target):
                self.read_activity.emit(True)
                try:
                    samples.append(
                        self._dmm.single_read(
                            timeout_ms=self._read_timeout_ms()
                        )
                    )
                finally:
                    self.read_activity.emit(False)
            last = samples[-1]
            if any(item.ovld for item in samples):
                reading = replace(
                    last,
                    value=0.0,
                    ovld=True,
                    raw=f"AVG {target} OVLD",
                    average_count=target,
                )
            else:
                reading = replace(
                    last,
                    value=sum(item.value for item in samples) / len(samples),
                    ovld=False,
                    raw=f"AVG {target}",
                    average_count=target,
                )
        except Exception as exc:
            self.error_occurred.emit("单次读数失败", _format_error(exc))
            if self._dmm.recover():
                self.status_updated.emit(self._dmm.status)
                self._set_state(WorkerState.READY, "通信已恢复，请重试")
            else:
                self._close_after_failure()
                self._set_state(WorkerState.ERROR, "通信恢复失败，请重新打开串口")
            return
        self.reading_received.emit(reading)
        if self._dmm.status is not None:
            self.status_updated.emit(self._dmm.status)
        self._set_state(WorkerState.READY, "远程模式，就绪")

    def _set_display(self, on: bool) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        self._dmm.set_display(on)
        self.notice.emit("VFD 显示已" + ("开启" if on else "关闭"))

    def _set_beeper(self, on: bool) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        self._dmm.set_beeper(on)
        self.notice.emit("蜂鸣器已" + ("开启" if on else "关闭"))

    def _scpi(self, text: str) -> None:
        if self._dmm is None:
            raise RuntimeError("串口未打开")
        if self._state == WorkerState.ACQUIRING:
            self.scpi_result.emit(text, "采集进行中，请先停止采集")
            return
        try:
            response = self._dmm.scpi(text)
        except Exception as exc:  # 终端输错命令不应把整台仪器置为错误态
            self.scpi_result.emit(text, f"错误：{_format_error(exc)}")
            return
        self.scpi_result.emit(text, response if response else "OK")

    def _list_resources(self) -> None:
        resources = VisaIO.list_resources()
        self.resources_listed.emit(resources)

    # ---------- 收尾 ----------

    def _abort_with_error(self, title: str, detail: str) -> None:
        if self._acquiring:
            self._acquiring = False
            self._stop_requested = False
        self.error_occurred.emit(title, detail)
        self._set_state(WorkerState.ERROR, "操作失败，可重新打开串口")

    def _close_after_failure(self) -> None:
        if self._dmm is not None:
            dmm, self._dmm = self._dmm, None
            dmm.close(restore_local=True)

    def _close_session(self) -> None:
        self._acquiring = False
        if self._dmm is not None:
            dmm, self._dmm = self._dmm, None
            try:
                dmm.close(restore_local=True)
            except Exception:
                log.exception("退出时收尾失败")
        self._set_state(WorkerState.DISCONNECTED, "串口未打开")

    def _set_state(self, state: str, detail: str) -> None:
        self._state = state
        self.state_changed.emit(state, detail)


def _format_error(exc: Exception) -> str:
    text = str(exc).strip()
    name = type(exc).__name__
    return f"{name}: {text}" if text else name
