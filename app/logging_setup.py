"""日志初始化。"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.constants import LOG_DIR

_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(debug: bool = False, instance: int = 1) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    name = "34401a.log" if instance <= 1 else f"34401a_{instance}.log"
    log_path = LOG_DIR / name

    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(file_handler)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(console)

    # VISA 的底层日志很吵，只在 debug 时打开。
    logging.getLogger("pyvisa").setLevel(logging.DEBUG if debug else logging.WARNING)
    return log_path
