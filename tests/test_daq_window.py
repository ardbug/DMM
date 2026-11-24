from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.ui.daq_window import DaqWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_daq_window_builds_with_gpib_default(tmp_path) -> None:
    _app()
    window = DaqWindow(AppConfig(tmp_path / "daq.ini", instance=2))
    assert "34970A" in window.windowTitle()
    assert window.panel.interface.currentData() == "gpib"
    assert window.panel.resource.currentText() == "gpib0,9"
    window.close()
