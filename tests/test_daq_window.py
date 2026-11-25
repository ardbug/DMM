import time

from PySide6.QtWidgets import QApplication

from app.config import AppConfig
from app.domain.models import Reading
from app.instrument.daq_modules import parse_slot
from app.ui.daq_window import DaqWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_daq_window_builds_with_gpib_default(tmp_path) -> None:
    _app()
    window = DaqWindow(AppConfig(tmp_path / "daq.ini", instance=2))
    assert "34970A" in window.windowTitle()
    assert window.panel.interface.currentData() == "gpib"
    assert window.panel.resource.currentText() == "gpib0,9"
    window.panel.set_state("opening", "正在打开串口…")
    assert window.panel.close_btn.isEnabled()
    window.params.scan_check.setChecked(True)
    config = window.params.config()
    assert config.scan is True
    assert config.scan_list.startswith("101,102,103")
    assert window._config.daq_parameters()["scan"] is True
    window.params.scan_check.setChecked(False)
    window._last_config = window.params.config()
    window._on_reading(
        Reading(
            7.0273,
            "V",
            "DCV",
            False,
            "0",
            time.time_ns(),
        )
    )
    assert "1" in window.readout.count_label.text()
    window._on_slots_detected([
        parse_slot(100, "HEWLETT-PACKARD,34901A,0,2.3"),
        parse_slot(200, "HEWLETT-PACKARD,0,0,0"),
        parse_slot(300, "HEWLETT-PACKARD,0,0,0"),
    ])
    assert window.params.channel.minimum() == 101
    assert window.params.channel.maximum() == 122
    assert window.params.scan_list.count() == 22
    window.single_trend.set_record_view(True)
    assert window.single_trend.record_view_active is True
    window.single_trend.set_record_view(False)
    assert window.single_trend.record_view_active is False
    window.close()


def test_daq_parameters_are_persisted(tmp_path) -> None:
    _app()
    path = tmp_path / "daq_params.ini"
    config = AppConfig(path, instance=1)
    window = DaqWindow(config)
    window.params.channel.setValue(102)
    window.params.nplc.setCurrentIndex(
        window.params.nplc.findData(10.0)
    )
    window.params.scan_rate.setValue(2.5)
    window.params.scan_count.setValue(3)
    window.params.pre_scan_wait.setValue(0.2)
    window.params.post_scan_wait.setValue(0.1)
    window.close()

    loaded = AppConfig(path, instance=1).daq_parameters()
    assert loaded["channel"] == 102
    assert loaded["nplc"] == 10.0
    assert loaded["scan_rate"] == 2.5
    assert loaded["scan_count"] == 3
    assert loaded["pre_scan_wait"] == 0.2
    assert loaded["post_scan_wait"] == 0.1
