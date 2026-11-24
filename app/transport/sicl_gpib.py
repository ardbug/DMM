"""Keysight SICL GPIB transport.

PyVISA 的 64 位 VISA GPIB 在本机打开时会抛 0xE06D7363，
因此 GPIB 走一个很小的 native SICL 桥接进程；串口仍由 VisaIO 负责。
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from app.domain.models import SerialSettings
from app.transport.serial_log import serial_log

_BRIDGE = Path(__file__).resolve().parents[2] / "tools" / "sicl_bridge.exe"
_KEYSIGHT_BIN = Path(r"C:\Program Files\Keysight\IO Libraries Suite\bin")
_KEYSIGHT_VISA_BIN = Path(
    r"C:\Program Files\IVI Foundation\VISA\Win64\ktvisa\ktbin"
)
_ADDRESS_RE = re.compile(r"^gpib(\d+),(\d+)$", re.IGNORECASE)


def normalize_sicl_address(resource: str) -> str:
    text = resource.strip()
    if _ADDRESS_RE.match(text):
        return text.lower()
    match = re.match(
        r"^GPIB(\d+)::(\d+)(?:::INSTR)?$", text, re.IGNORECASE
    )
    if match:
        return f"gpib{match.group(1)},{match.group(2)}"
    raise ValueError("GPIB 地址应为 gpib0,1 或 GPIB0::1::INSTR")


class SiclGpibError(RuntimeError):
    pass


class SiclBridge:
    def __init__(self, address: str, timeout_ms: int = 10000) -> None:
        if not _BRIDGE.exists():
            raise SiclGpibError(
                f"缺少 {_BRIDGE}，请先运行 tools\\build_sicl_bridge.bat"
            )
        env = os.environ.copy()
        env["PATH"] = os.pathsep.join(
            [str(_KEYSIGHT_BIN), str(_KEYSIGHT_VISA_BIN), env.get("PATH", "")]
        )
        self._process = subprocess.Popen(
            [str(_BRIDGE), address, str(timeout_ms)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="ascii",
            errors="replace",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    @property
    def alive(self) -> bool:
        return self._process.poll() is None

    def _command(self, line: str) -> str:
        if not self.alive:
            raise SiclGpibError("GPIB 桥接进程已退出")
        stdin = self._process.stdin
        stdout = self._process.stdout
        if stdin is None or stdout is None:
            raise SiclGpibError("GPIB 桥接进程管道不可用")
        try:
            stdin.write(line + "\n")
            stdin.flush()
            reply = stdout.readline()
        except OSError as exc:
            raise SiclGpibError(f"GPIB 桥接通信失败：{exc}") from exc
        if not reply:
            raise SiclGpibError("GPIB 桥接进程没有响应")
        reply = reply.rstrip("\r\n")
        if reply.startswith("O:"):
            return reply[2:]
        if reply.startswith("E:"):
            raise SiclGpibError(f"SICL 错误：{reply[2:]}")
        raise SiclGpibError(f"GPIB 桥接协议错误：{reply!r}")

    def query(self, command: str, timeout_ms: int) -> str:
        return self._command(f"Q:{max(1, int(timeout_ms))}:{command}")

    def write(self, command: str) -> None:
        self._command(f"W:{command}")

    def read(self, timeout_ms: int) -> str:
        return self._command(f"R:{max(1, int(timeout_ms))}")

    def local(self) -> None:
        self._command("L")

    def close(self) -> None:
        if self.alive:
            try:
                stdin = self._process.stdin
                if stdin is not None:
                    stdin.write("X\n")
                    stdin.flush()
            except Exception:
                pass
        try:
            self._process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self._process.kill()
            self._process.wait(timeout=2)


class SiclGpibIO:
    def __init__(self) -> None:
        self._bridge: SiclBridge | None = None
        self._pending_query = False
        self._timeout_ms = 10000

    @property
    def is_open(self) -> bool:
        return self._bridge is not None and self._bridge.alive

    def open(self, settings: SerialSettings) -> None:
        if self._bridge is not None:
            self.close()
        address = normalize_sicl_address(settings.resource)
        self._timeout_ms = max(1000, int(settings.timeout_ms))
        self._bridge = SiclBridge(address, self._timeout_ms)

    def close(self) -> None:
        bridge, self._bridge = self._bridge, None
        self._pending_query = False
        if bridge is not None:
            bridge.close()

    @staticmethod
    def _ascii(command: str) -> bytes:
        if not command or "\r" in command or "\n" in command:
            raise SiclGpibError("非法 SCPI 命令（空或含换行）")
        try:
            return command.encode("ascii")
        except UnicodeEncodeError as exc:
            raise SiclGpibError("SCPI 命令必须为 ASCII") from exc

    def write_line(self, command: str) -> None:
        if self._bridge is None:
            raise SiclGpibError("GPIB 未打开")
        self._ascii(command)
        self._bridge.write(command)
        serial_log.record("TX", command.encode("ascii") + b"\n")

    def read_line(self, timeout_ms: int | None = None) -> str:
        if self._bridge is None:
            raise SiclGpibError("GPIB 未打开")
        timeout = self._timeout_ms if timeout_ms is None else int(timeout_ms)
        text = self._bridge.read(timeout)
        raw = text.encode("ascii", errors="replace") + b"\n"
        serial_log.record("RX", raw)
        if not text:
            raise SiclGpibError("仪器返回空行")
        return text

    def query_line(self, command: str, timeout_ms: int | None = None) -> str:
        if self._pending_query:
            raise SiclGpibError("上一轮查询尚未读完，拒绝发送新查询")
        if self._bridge is None:
            raise SiclGpibError("GPIB 未打开")
        self._ascii(command)
        self._pending_query = True
        timeout = self._timeout_ms if timeout_ms is None else int(timeout_ms)
        try:
            text = self._bridge.query(command, timeout)
            serial_log.record("TX", command.encode("ascii") + b"\n")
            serial_log.record(
                "RX", text.encode("ascii", errors="replace") + b"\n"
            )
            if not text:
                raise SiclGpibError("仪器返回空行")
            return text
        finally:
            self._pending_query = False

    def query_batch_timed(
        self, command: str, count: int, timeout_ms: int | None = None
    ) -> tuple[list[str], int, int]:
        """GPIB 批量读数可能按行/按 EOI 返回，逐行读取 count 条。"""

        raw, write_done, read_done = self.query_line_timed(
            command, timeout_ms
        )
        return [raw], write_done, read_done

    def query_line_timed(
        self, command: str, timeout_ms: int | None = None
    ) -> tuple[str, int, int]:
        if self._pending_query:
            raise SiclGpibError("上一轮查询尚未读完，拒绝发送新查询")
        if self._bridge is None:
            raise SiclGpibError("GPIB 未打开")
        self._ascii(command)
        self._pending_query = True
        timeout = self._timeout_ms if timeout_ms is None else int(timeout_ms)
        try:
            start = time.perf_counter_ns()
            text = self._bridge.query(command, timeout)
            read_done = time.perf_counter_ns()
            serial_log.record("TX", command.encode("ascii") + b"\n")
            serial_log.record(
                "RX", text.encode("ascii", errors="replace") + b"\n"
            )
            if not text:
                raise SiclGpibError("仪器返回空行")
            # GPIB 桥的命令是一问一答，写入完成时刻近似取查询开始时刻。
            return text, start, read_done
        finally:
            self._pending_query = False

    def flush(self) -> None:
        # 不做设备清除；避免改变 34401A 当前设置。
        return

    def clear(self) -> None:
        # 与 flush 相同：恢复流程由 Dmm.recover() 的命令负责。
        return

    def local(self) -> None:
        """GPIB 的 GTL（go to local），替代串口专用的 SYST:LOC。"""
        if self._bridge is None:
            raise SiclGpibError("GPIB 未打开")
        self._bridge.local()

    @staticmethod
    def list_resources() -> list[str]:
        return []
