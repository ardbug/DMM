"""PyVISA 串口/GPIB 低层封装。

约定：
- 只在本类里出现 VISA 调用；调用者必须保证这些方法都在 I/O 线程执行。
- 一次只允许一个未完成的查询。
"""

from __future__ import annotations

import logging
import time

import pyvisa
from pyvisa import constants

from app.domain.models import SerialSettings
from app.transport.serial_log import serial_log

log = logging.getLogger(__name__)


class VisaIOError(RuntimeError):
    """传输层可读错误。"""


class VisaIO:
    # 全进程只保留一个 ResourceManager。
    # 实测：在会话打开时另建一个 RM，再 close 它，会让已打开的 session
    # 变成 InvalidSession（NI-VISA 的库级引用被释放）。列表和会话共用这个 RM。
    _shared_rm: pyvisa.ResourceManager | None = None

    def __init__(self) -> None:
        self._rm: pyvisa.ResourceManager | None = None
        self._inst: pyvisa.resources.MessageBasedResource | None = None
        self._pending_query = False

    @classmethod
    def _get_shared_rm(cls) -> pyvisa.ResourceManager:
        if cls._shared_rm is None:
            cls._shared_rm = pyvisa.ResourceManager("@ivi")
        return cls._shared_rm

    @property
    def is_open(self) -> bool:
        return self._inst is not None

    def open(self, settings: SerialSettings) -> None:
        if self.is_open:
            self.close()

        inst: pyvisa.resources.MessageBasedResource | None = None
        try:
            rm = self._get_shared_rm()
            inst = rm.open_resource(
                settings.resource,
                open_timeout=settings.timeout_ms,
            )
            inst.timeout = settings.timeout_ms
            inst.read_termination = "\n"
            inst.write_termination = "\n"

            # 有些 NI-VISA 安装允许用 COM10 作为串口别名；它同样必须
            # 应用 7E2/DTR-DSR。只判断 ASRL 会让 COM10 留在默认 8N1，
            # 仪器会报 513（RS-232 parity error）/ -410。
            if settings.resource.upper().startswith(("ASRL", "COM")):
                inst.baud_rate = settings.baud_rate
                inst.data_bits = settings.data_bits
                inst.parity = {
                    "none": constants.Parity.none,
                    "odd": constants.Parity.odd,
                    "even": constants.Parity.even,
                }[settings.parity]
                inst.stop_bits = {
                    1: constants.StopBits.one,
                    2: constants.StopBits.two,
                }[settings.stop_bits]
                inst.flow_control = {
                    "none": constants.VI_ASRL_FLOW_NONE,
                    "rts_cts": constants.VI_ASRL_FLOW_RTS_CTS,
                    "dtr_dsr": constants.VI_ASRL_FLOW_DTR_DSR,
                }[settings.flow_control]

                # 注意：不要在这里手工 set DTR/RTS。
                # 实测 DTR/DSR 流控开启后，再设置 VI_ATTR_ASRL_DTR_STATE
                # 会报 VI_ERROR_INV_SETUP；让 VISA/NI-VISA 管理握手。

            # 等 DTR/DSR 稳定，丢弃打开端口前的残留。
            time.sleep(0.4)
            inst.flush(constants.VI_READ_BUF | constants.VI_WRITE_BUF)

            self._rm = rm
            self._inst = inst
            log.info(
                "VISA 已打开：%s（%s/%s/%s/%s）",
                settings.resource,
                settings.baud_rate,
                settings.parity,
                settings.data_bits,
                settings.stop_bits,
            )
        except Exception:
            if inst is not None:
                try:
                    inst.close()
                except Exception:
                    pass
            # 不能 close 共享 RM，否则后续/现有会话都可能失效。
            self._rm = None
            raise

    def close(self) -> None:
        inst = self._inst
        self._inst = None
        self._rm = None
        self._pending_query = False
        if inst is not None:
            try:
                inst.close()
            except Exception:
                log.debug("关闭 VISA session 失败", exc_info=True)
        # 注意：不关闭共享 ResourceManager。留给进程退出时统一回收。

    def write_line(self, command: str) -> None:
        if self._inst is None:
            raise VisaIOError("串口未打开")
        if not command or "\r" in command or "\n" in command:
            raise VisaIOError("非法 SCPI 命令（空或含换行）")
        try:
            command.encode("ascii")
        except UnicodeEncodeError as exc:
            raise VisaIOError("SCPI 命令必须为 ASCII") from exc
        self._inst.write(command)
        serial_log.record("TX", command.encode("ascii") + b"\n")

    def read_line(self, timeout_ms: int | None = None) -> str:
        if self._inst is None:
            raise VisaIOError("串口未打开")
        if timeout_ms is not None:
            self._inst.timeout = timeout_ms
        # read_raw 保留终止符/所有原始字节；read() 会去掉 read_termination，
        # 串口日志就看不到仪器实际发回的 CR/LF。
        raw_bytes = self._inst.read_raw()
        if raw_bytes:
            serial_log.record("RX", raw_bytes)
        text = raw_bytes.decode("ascii", errors="replace").strip()
        if not text:
            raise VisaIOError("仪器返回空行")
        return text

    def query_line(self, command: str, timeout_ms: int | None = None) -> str:
        if self._pending_query:
            raise VisaIOError("上一轮查询尚未读完，拒绝发送新查询")
        self._pending_query = True
        try:
            self.write_line(command)
            return self.read_line(timeout_ms)
        finally:
            self._pending_query = False

    def query_line_timed(
        self,
        command: str,
        timeout_ms: int | None = None,
    ) -> tuple[str, int, int]:
        """返回 (响应, 命令写完时刻, 响应读完时刻)，均为 perf_counter_ns。"""

        if self._pending_query:
            raise VisaIOError("上一轮查询尚未读完，拒绝发送新查询")
        self._pending_query = True
        try:
            self.write_line(command)
            write_done = time.perf_counter_ns()
            text = self.read_line(timeout_ms)
            read_done = time.perf_counter_ns()
            return text, write_done, read_done
        finally:
            self._pending_query = False

    def flush(self) -> None:
        if self._inst is None:
            raise VisaIOError("串口未打开")
        self._inst.flush(constants.VI_READ_BUF | constants.VI_WRITE_BUF)

    def clear(self) -> None:
        """RS-232 下等价 Ctrl-C / device clear。"""

        if self._inst is None:
            raise VisaIOError("串口未打开")
        self._inst.clear()

    @staticmethod
    def list_resources() -> list[str]:
        rm = VisaIO._get_shared_rm()
        return sorted(str(item) for item in rm.list_resources("ASRL?*INSTR"))

    @classmethod
    def release_shared(cls) -> None:
        """进程退出前调用；会话必须已经关闭。"""

        if cls._shared_rm is not None:
            try:
                cls._shared_rm.close()
            except Exception:
                log.debug("关闭共享 ResourceManager 失败", exc_info=True)
            cls._shared_rm = None
