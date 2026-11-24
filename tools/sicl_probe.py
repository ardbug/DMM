"""SICL GPIB bridge probe (proof of concept, not used by the app yet)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIDGE = ROOT / "tools" / "sicl_bridge.exe"
KEYSIGHT_BIN = Path(r"C:\Program Files\Keysight\IO Libraries Suite\bin")
KEYSIGHT_VISA_BIN = Path(r"C:\Program Files\IVI Foundation\VISA\Win64\ktvisa\ktbin")


class SiclBridge:
    def __init__(self, address: str, timeout_ms: int = 10000) -> None:
        if not BRIDGE.exists():
            raise FileNotFoundError(
                f"{BRIDGE} not found; run tools\\build_sicl_bridge.bat"
            )
        env = os.environ.copy()
        paths = [str(KEYSIGHT_BIN), str(KEYSIGHT_VISA_BIN)]
        env["PATH"] = os.pathsep.join(paths + [env.get("PATH", "")])
        self._process = subprocess.Popen(
            [str(BRIDGE), address, str(timeout_ms)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )

    def query(self, command: str) -> str:
        return self._transact(f"Q:{command}")

    def write(self, command: str) -> None:
        self._transact(f"W:{command}")

    def _transact(self, line: str) -> str:
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._process.stdin.write(line + "\n")
        self._process.stdin.flush()
        reply = self._process.stdout.readline().rstrip("\r\n")
        if not reply.startswith("O:"):
            raise RuntimeError(f"SICL bridge error: {reply or 'no reply'}")
        return reply[2:]

    def close(self) -> None:
        if self._process.poll() is None:
            try:
                assert self._process.stdin is not None
                self._process.stdin.write("X\n")
                self._process.stdin.flush()
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()
        if self._process.stdin is not None:
            self._process.stdin.close()
        if self._process.stdout is not None:
            self._process.stdout.close()
        if self._process.stderr is not None:
            self._process.stderr.close()


def main() -> int:
    address = sys.argv[1] if len(sys.argv) > 1 else "gpib0,1"
    bridge = SiclBridge(address)
    try:
        print("IDN:", bridge.query("*IDN?"))
        bridge.write("CONF:VOLT:DC")
        print("DCV:", bridge.query("READ?"))
    finally:
        bridge.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
