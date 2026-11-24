"""34401A 上位机入口。"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from app.config import AppConfig, default_config_path
from app.constants import APP_NAME, ORG_NAME, VERSION
from app.logging_setup import setup_logging
from app.ui.main_window import MainWindow
from app.ui.theme import apply_theme

log = logging.getLogger(__name__)


def _install_excepthook() -> None:
    def hook(exc_type, exc_value, exc_tb) -> None:
        log.critical("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
        try:
            QMessageBox.critical(
                None,
                "程序异常",
                f"{exc_type.__name__}: {exc_value}\n\n详细信息已写入日志。",
            )
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HP 34401A 台式万用表上位机")
    parser.add_argument("--debug", action="store_true", help="记录调试日志（含 VISA 细节）")
    parser.add_argument(
        "--instance",
        type=int,
        default=0,
        help="实例编号；0 自动选择空闲实例，2 及以上使用独立配置和日志",
    )
    return parser.parse_args(argv)


def _acquire_instance(requested: int) -> tuple[int, QLockFile]:
    start = max(1, int(requested))
    for instance in range(start, start + 100):
        path = default_config_path(instance).with_suffix(".lock")
        lock = QLockFile(str(path))
        if lock.tryLock(0):
            return instance, lock
    raise RuntimeError("无法创建实例锁，请检查用户配置目录权限")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    instance, instance_lock = _acquire_instance(args.instance)
    log_path = setup_logging(debug=args.debug, instance=instance)
    log.info(
        "启动 %s v%s（实例 %d），日志：%s",
        APP_NAME,
        VERSION,
        instance,
        log_path,
    )
    _install_excepthook()

    config = AppConfig(instance=instance)
    os.environ["QT_SCALE_FACTOR"] = f"{config.scale_factor() / 100:g}"

    app = QApplication(sys.argv)
    app._instance_lock = instance_lock  # type: ignore[attr-defined]
    app.setApplicationName("34401A")
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    icon_path = Path(__file__).resolve().parent / "icon.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    apply_theme(app)
    # 系统主题切换时重刷 QSS/调色板。
    app.styleHints().colorSchemeChanged.connect(lambda _scheme: apply_theme(app))

    window = MainWindow(config, instance=instance)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
