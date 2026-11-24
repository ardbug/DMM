from PySide6.QtWidgets import QApplication

from app.domain.models import SerialSettings
from app.ui.dialogs.serial_dialog import SerialDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_connection_dialog_gpib_mode() -> None:
    _app()
    dialog = SerialDialog(
        SerialSettings(resource="gpib0,1", interface="gpib"),
        serial_resource="ASRL6::INSTR",
        gpib_resource="gpib0,1",
    )
    assert dialog.interface.currentData() == "gpib"
    assert dialog.gpib_resource.isVisibleTo(dialog)
    assert not dialog.resource.isVisibleTo(dialog)
    settings = dialog.settings()
    assert settings.interface == "gpib"
    assert settings.resource == "gpib0,1"

    dialog.interface.setCurrentIndex(dialog.interface.findData("serial"))
    assert dialog.resource.isVisibleTo(dialog)
    assert dialog.resource.currentData() == "COM6"
    assert dialog.settings().interface == "serial"
    assert dialog.settings().resource == "COM6"
    dialog.resource.setCurrentText("COM99")
    assert dialog.settings().resource == "COM99"
