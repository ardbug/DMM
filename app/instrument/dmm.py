"""34401A 高层命令：握手、单次读数、状态、错误队列、回本地。"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import replace

from app.constants import (
    HANDSHAKE_RETRIES,
    HANDSHAKE_RETRY_DELAY_S,
    HANDSHAKE_TIMEOUT_MS,
    OVLD_THRESHOLD,
    SINGLE_READ_TIMEOUT_MS,
)
from app.domain.functions import describe_function, function_query_prefix, function_spec
from app.domain.models import (
    AcquisitionConfig,
    BatchRead,
    InstrumentStatus,
    Reading,
    ScpiError,
    SerialSettings,
)
from app.transport.visa_io import VisaIO

log = logging.getLogger(__name__)

_ERROR_RE = re.compile(r"^\s*([+-]?\d+)\s*(?:,\s*(.*))?$")


class DmmError(RuntimeError):
    """仪器会话错误。"""


class Dmm:
    def __init__(self, io=None) -> None:
        self._io = io if io is not None else VisaIO()
        self.identity = ""
        self.status: InstrumentStatus | None = None
        self.local_only = False
        self.interface = "serial"

    @property
    def is_open(self) -> bool:
        return self._io.is_open

    def open_local(self, settings: SerialSettings) -> None:
        """只打开串口，不发送任何 SCPI，不把仪器切到远程。"""

        self._io.open(settings)
        self.interface = settings.interface
        self.local_only = True
        self.status = None
        self.identity = ""
        log.info("串口已打开（RMT 关闭，仅本地，不控制仪器）")

    def open(
        self,
        settings: SerialSettings,
        attempts: int = HANDSHAKE_RETRIES,
        handshake_timeout_ms: int = HANDSHAKE_TIMEOUT_MS,
    ) -> str:
        self._io.open(settings)
        self.interface = settings.interface
        self.local_only = False
        try:
            # SYST:REM 是 RS-232 专用；GPIB 被寻址时自动进入远程。
            if self.interface != "gpib":
                self._io.write_line("SYST:REM")
            self._io.write_line("*CLS")
            self.identity = self._handshake(attempts, handshake_timeout_ms)
            self.status = self.read_status()
            errors = self.read_error_queue()
            if errors:
                log.warning("握手后错误队列非空：%s", [e.raw for e in errors])
            # 丢掉可能迟到的可选查询响应，避免污染第一次 READ?。
            self._io.flush()
            return self.identity
        except Exception:
            # 即使握手失败，也尽量把仪器放回本地，避免停在 Rmt。
            self.close(restore_local=True)
            raise

    def _handshake(
        self,
        attempts: int = HANDSHAKE_RETRIES,
        timeout_ms: int = HANDSHAKE_TIMEOUT_MS,
    ) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, max(1, attempts) + 1):
            try:
                idn = self._io.query_line("*IDN?", timeout_ms)
                if "34401A" not in idn.upper():
                    raise DmmError(f"仪器身份不是 34401A：{idn}")
                log.info("握手成功（第 %d 次）：%s", attempt, idn)
                return idn
            except Exception as exc:
                last_exc = exc
                log.warning("第 %d/%d 次握手失败：%s", attempt, attempts, exc)
                if attempt >= attempts:
                    break
                self._safe_clear_and_reprepare()

        raise DmmError(f"*IDN? 握手失败：{last_exc}") from last_exc

    def _safe_clear_and_reprepare(self) -> None:
        try:
            self._io.clear()
        except Exception:
            log.debug("device clear 失败", exc_info=True)
        time.sleep(HANDSHAKE_RETRY_DELAY_S)
        try:
            self._io.flush()
        except Exception:
            log.debug("清缓冲失败", exc_info=True)
        try:
            if self.interface != "gpib":
                self._io.write_line("SYST:REM")
            self._io.write_line("*CLS")
        except Exception:
            log.debug("重新进入远程失败", exc_info=True)
        time.sleep(0.2)

    def read_status(self) -> InstrumentStatus:
        drain = getattr(self._io, "drain", None)
        if drain is not None:
            try:
                drain()
            except Exception:
                log.debug("FUNC? 前清空串口失败", exc_info=True)
        func_raw = ""
        info = None
        for attempt in range(2):
            func_raw = self._io.query_line("FUNC?", 3000)
            info = describe_function(func_raw)
            if info.query_prefix:
                break
            log.warning(
                "FUNC? 返回异常：%r，串口可能失步；清理输入后重试",
                func_raw,
            )
            if attempt == 0:
                self._resync_serial_link()
        if info is None or not info.query_prefix:
            raise DmmError(
                f"FUNC? 返回异常：{func_raw!r}；串口可能失步，请重新连接"
            )
        nplc = ""
        range_text = ""

        if info.query_prefix:
            # 只对确定支持的功能发带前缀查询；不要发裸 NPLC? / RANG?。
            if info.supports_nplc:
                nplc = self._io.query_line(f"{info.query_prefix}:NPLC?", 3000)
            if info.supports_nplc or info.raw in {"VOLT:AC", "CURR:AC"}:
                range_text = self._io.query_line(f"{info.query_prefix}:RANG?", 3000)

        terminal = "FRON"
        try:
            # 前后端状态单独查询；前后都 flush，避免残留响应污染 READ?。
            self._io.flush()
            raw_terminal = (
                self._io.query_line("ROUT:TERM?", 3000)
                .strip()
                .strip('"')
                .upper()
            )
            if raw_terminal in {"FRON", "FRONT", "REAR"}:
                terminal = "REAR" if raw_terminal == "REAR" else "FRON"
        except Exception:
            log.warning("查询前后端失败，按前端处理", exc_info=True)
        finally:
            try:
                self._io.flush()
            except Exception:
                pass

        return InstrumentStatus(
            function=info,
            nplc=nplc,
            range_text=range_text,
            terminal=terminal,
        )

    def _resync_serial_link(self) -> None:
        """串口收到残留响应时清理输入并清仪器状态，避免陆续错位。"""
        try:
            self._io.clear()
            self._io.flush()
            drain = getattr(self._io, "drain", None)
            if drain is not None:
                drain()
            self._io.write_line("*CLS")
            time.sleep(0.2)
            self._io.flush()
            if drain is not None:
                drain()
        except Exception:
            log.warning("串口失步清理失败", exc_info=True)

    def read_error_queue(self, limit: int = 20) -> list[ScpiError]:
        errors: list[ScpiError] = []
        for _ in range(limit):
            raw = self._io.query_line("SYST:ERR?")
            match = _ERROR_RE.match(raw)
            if not match:
                errors.append(ScpiError(code=-1, raw=raw))
                break
            code = int(match.group(1))
            if code == 0:
                break
            errors.append(ScpiError(code=code, raw=raw))
        return errors

    def scpi(self, command: str) -> str:
        """SCPI 终端用：带 ? 的查询返回响应，其余命令返回空串。"""

        text = command.strip()
        if not text:
            return ""
        try:
            if "?" in text:
                return self._io.query_line(text, 5000)
            self._io.write_line(text)
            return ""
        except Exception as exc:
            # 超时后仪器可能仍把响应发回来，必须清掉，否则下一条命令
            # 会读到上一条的迟到响应，整个终端从此错位。
            time.sleep(0.2)
            try:
                self._io.flush()
            except Exception:
                log.debug("SCPI 超时后清缓冲失败", exc_info=True)
            raise DmmError(f"{exc}；已清空串口输入缓冲，请重试") from exc

    def set_display(self, on: bool) -> None:
        self._io.write_line(f"DISP {'ON' if on else 'OFF'}")

    def set_beeper(self, on: bool) -> None:
        self._io.write_line(f"SYST:BEEP:STAT {'ON' if on else 'OFF'}")

    def set_trigger_delay(self, seconds: float) -> None:
        self._io.write_line(f"TRIG:DEL {max(0.0, seconds):.6f}")

    def set_sample_count(self, count: int) -> None:
        if not 1 <= count <= 512:
            raise DmmError(f"SAMP:COUN 越界：{count}")
        self._io.write_line(f"SAMP:COUN {count}")

    def apply_config(self, config: AcquisitionConfig) -> None:
        """下发功能/量程/NPLC/AZ/滤波/阻抗/Null，并读错误队列确认。"""

        spec = function_spec(config.function)
        self._io.write_line(f"CONF:{spec.conf_command}")

        if spec.raw in {"VOLT", "VOLT:AC", "CURR", "CURR:AC", "RES", "FRES"}:
            if config.range_mode == "manual" and config.range_value > 0:
                self._io.write_line(f"{spec.prefix}:RANG {config.range_value:g}")
            else:
                self._io.write_line(f"{spec.prefix}:RANG:AUTO ON")

        if spec.supports_nplc:
            self._io.write_line(f"{spec.prefix}:NPLC {config.nplc:g}")
            self._io.write_line(f"ZERO:AUTO {'ON' if config.az else 'OFF'}")

        if spec.supports_ac_filter:
            self._io.write_line(f"DET:BAND {config.ac_filter:g}")

        if spec.raw == "VOLT":
            self._io.write_line(
                f"INP:IMP:AUTO {'ON' if config.input_impedance == 'high' else 'OFF'}"
            )

        if spec.supports_null and config.null_enabled:
            self._io.write_line("CALC:FUNC NULL")
            self._io.write_line(f"CALC:NULL:OFFS {config.null_value:.15g}")
            self._io.write_line("CALC:STAT ON")
        else:
            self._io.write_line("CALC:STAT OFF")

        self._io.write_line("TRIG:SOUR IMM")
        self._io.write_line("TRIG:COUN 1")
        self._io.write_line("TRIG:DEL 0")
        self._io.write_line("TRIG:DEL:AUTO OFF")

        errors = self.read_error_queue()
        if errors:
            raise DmmError(f"配置被仪器拒绝：{errors[0].raw}")
        self.status = self.read_status()
        self._io.flush()
        log.info(
            "采集配置已下发：%s %s，NPLC=%g，AZ=%s，AC=%g，Zin=%s，Null=%s",
            spec.label,
            config.range_mode,
            config.nplc,
            "ON" if config.az else "OFF",
            config.ac_filter,
            config.input_impedance,
            "ON" if config.null_enabled else "OFF",
        )

    def read_batch(self, count: int, timeout_ms: int = 5000) -> BatchRead:
        """取回一批读数。批量响应是一行、逗号分隔。"""

        if self.status is None:
            self.status = self.read_status()
        info = self.status.function
        perf_start = time.perf_counter_ns()
        wall_start = time.time_ns()
        batch_timed = getattr(self._io, "query_batch_timed", None)
        if batch_timed is not None:
            raw_lines, write_done, read_done = batch_timed(
                "READ?", count, timeout_ms
            )
        else:
            raw, write_done, read_done = self._io.query_line_timed(
                "READ?", timeout_ms
            )
            raw_lines = [raw]
        tokens = [
            token.strip()
            for line in raw_lines
            for token in line.split(",")
            if token.strip()
        ]
        if len(tokens) != count:
            raise DmmError(
                f"批量读数条数不符：期望 {count}，实际 {len(tokens)}："
                f"{','.join(raw_lines)[:80]}"
            )
        try:
            values = [float(token) for token in tokens]
        except ValueError as exc:
            raise DmmError(f"无法解析批量读数：{raw!r}") from exc

        duration = max(1, read_done - write_done)
        step = duration / count
        readings: list[Reading] = []
        for index, (token, value) in enumerate(zip(tokens, values, strict=True)):
            perf_ts = write_done + int(step * (index + 1))
            epoch_ts = wall_start + (perf_ts - perf_start)
            readings.append(
                Reading(
                    value=value,
                    unit=info.unit,
                    function_label=info.label,
                    ovld=abs(value) >= OVLD_THRESHOLD,
                    raw=token,
                    timestamp_ns=epoch_ts,
                )
            )
        return BatchRead(
            readings=tuple(readings),
            start_ns=wall_start,
            end_ns=max(wall_start, wall_start + (read_done - perf_start)),
        )

    def single_read(self, timeout_ms: int = SINGLE_READ_TIMEOUT_MS) -> Reading:
        if self.status is None:
            self.status = self.read_status()
        # 仪器可能被上次会话留在 SAMP:COUN >1；单次读之前显式复位。
        self.set_sample_count(1)
        raw = self._io.query_line("READ?", timeout_ms)
        if "," in raw:
            raise DmmError(f"单次 READ? 返回了多条读数：{raw[:80]}")
        try:
            value = float(raw)
        except ValueError as exc:
            raise DmmError(f"无法解析读数：{raw!r}") from exc

        info = self.status.function
        return Reading(
            value=value,
            unit=info.unit,
            function_label=info.label,
            ovld=abs(value) >= OVLD_THRESHOLD,
            raw=raw,
            timestamp_ns=time.time_ns(),
        )

    def identify(self) -> str:
        self.identity = self._io.query_line("*IDN?", HANDSHAKE_TIMEOUT_MS)
        return self.identity

    def recover(self) -> bool:
        """单次读失败后的保守恢复；成功也不自动继续采集。"""

        if not self.is_open:
            return False
        try:
            self._io.clear()
        except Exception:
            log.warning("恢复时 device clear 失败", exc_info=True)
            return False
        time.sleep(0.3)
        try:
            self._io.flush()
            if self.interface != "gpib":
                self._io.write_line("SYST:REM")
            self._io.write_line("*CLS")
            time.sleep(0.2)
            idn = self._io.query_line("*IDN?", HANDSHAKE_TIMEOUT_MS)
            self.identity = idn
            self.status = self.read_status()
            return True
        except Exception:
            log.warning("恢复失败", exc_info=True)
            return False

    def close(self, restore_local: bool = True) -> None:
        if not self.is_open:
            return
        if self.local_only:
            self._io.close()
            self.local_only = False
            return
        if restore_local:
            try:
                # 34401A 的写法是 "DISPlay ON"（空格），不是 "DISPlay:ON"。
                # 实测 "DISPLAY:ON" 会留下 -113 Undefined header。
                self._io.write_line("DISP ON")
                if self.interface == "gpib":
                    local = getattr(self._io, "local", None)
                    if local is not None:
                        local()
                    log.info("已发送 DISP ON / GPIB GTL")
                else:
                    self._io.write_line("SYST:LOC")
                    log.info("已发送 DISP ON / SYST:LOC")
                time.sleep(0.1)
            except Exception:
                log.warning("回本地失败，请按面板 Shift+Local", exc_info=True)
        self._io.close()
