from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.domain.models import SerialSettings
from app.ui.sections.connection_panel import ConnectionPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_connection_panel_uses_gpib_mode(tmp_path) -> None:
    _app()
    config = AppConfig(tmp_path / "settings.ini")
    config.save_serial_settings(
        SerialSettings(resource="gpib0,1", interface="gpib")
    )
    panel = ConnectionPanel(config)
    assert panel.interface.currentData() == "gpib"
    assert panel.resource_combo.currentText() == "gpib0,1"
    assert not panel.baud.isVisibleTo(panel)
    assert panel.serial_settings().interface == "gpib"
    panel.interface.setCurrentIndex(panel.interface.findData("serial"))
    assert panel.resource_combo.currentText() == "ASRL6::INSTR"
    assert panel.baud.isVisibleTo(panel)
    assert panel.serial_settings().interface == "serial"
