r"""阶段 1 真机冒烟：连接 → IDN → 状态 → 单次读数 → 回本地。

用法（在“程序”目录）：
    .\.venv\Scripts\python.exe tools\smoke_phase1.py
    .\.venv\Scripts\python.exe tools\smoke_phase1.py --resource ASRL6::INSTR
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接运行 tools\smoke_phase1.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.domain.models import SerialSettings  # noqa: E402
from app.instrument.dmm import Dmm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--resource", default="ASRL6::INSTR")
    args = parser.parse_args()

    dmm = Dmm()
    try:
        identity = dmm.open(SerialSettings(resource=args.resource))
        print("IDN :", identity)
        print("状态:", dmm.status)
        print("错误:", dmm.read_error_queue())
        reading = dmm.single_read()
        print("读数:", reading.raw, reading.unit, "OVLD" if reading.ovld else "")
        return 0
    except Exception as exc:
        print("失败:", type(exc).__name__, exc, file=sys.stderr)
        return 1
    finally:
        dmm.close(restore_local=True)
        print("已发送 DISP ON / SYST:LOC")


if __name__ == "__main__":
    raise SystemExit(main())
