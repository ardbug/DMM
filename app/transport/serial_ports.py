"""Windows 串口枚举，用于连接设置里的“扫描”列表。"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SerialPortInfo:
    device: str
    description: str


def list_serial_ports() -> list[SerialPortInfo]:
    try:
        from serial.tools import list_ports
    except Exception:
        return []
    result: list[SerialPortInfo] = []
    for item in list_ports.comports():
        device = str(item.device).upper()
        description = str(item.description or "").strip()
        description = re.sub(
            rf"\s*\({re.escape(device)}\)\s*$", "", description
        ).strip()
        result.append(SerialPortInfo(device, description))
    def sort_key(item: SerialPortInfo) -> tuple[int, str]:
        number = item.device.removeprefix("COM")
        return (int(number) if number.isdigit() else 9999, item.device)

    result.sort(key=sort_key)
    return result
