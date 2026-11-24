from app.config import AppConfig
from app.domain.models import SerialSettings
from app.domain.models import AcquisitionConfig


def test_geometry_roundtrip(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings.ini")
    assert config.window_geometry() is None
    config.save_window_geometry(b"geometry-bytes")
    assert config.window_geometry() == b"geometry-bytes"


def test_acquisition_config_roundtrip_ignores_range(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings.ini")
    expected = AcquisitionConfig(
        nplc=10.0,
        digits="6½",
        rate=6.0,
        az=True,
        function="VOLT:AC",
        range_mode="auto",
        range_value=0.0,
        ac_filter=200,
        input_impedance="high",
        null_enabled=True,
        null_value=0.001,
    )
    config.save_acquisition_config(expected)
    assert config.acquisition_config() == expected


def test_instance_uses_separate_config_and_csv_directory(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings_2.ini", instance=2)
    assert config.instance == 2
    assert config.path.name == "settings_2.ini"
    assert config.csv_directory().name == "实例2"


def test_connection_interface_roundtrip(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings.ini")
    config.save_serial_settings(
        SerialSettings(resource="gpib0,1", interface="gpib")
    )
    assert config.serial_settings().interface == "gpib"
    assert config.serial_settings().resource == "gpib0,1"
    config.save_serial_settings(
        SerialSettings(resource="ASRL3::INSTR", interface="serial")
    )
    assert config.serial_settings().interface == "serial"
    assert config.serial_settings().resource == "ASRL3::INSTR"
    assert config.gpib_resource() == "gpib0,1"


def test_tool_section_order_roundtrip(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings.ini")
    assert config.tool_section_order() == []
    config.save_tool_section_order(["floating", "csv", "average", "beep"])
    assert config.tool_section_order() == [
        "floating",
        "csv",
        "average",
        "beep",
    ]


def test_floating_settings_roundtrip(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings.ini")
    assert config.floating_settings() == (100, 100)
    config.save_floating_settings(150, 40)
    assert config.floating_settings() == (150, 40)
    config.save_floating_settings(999, 1)
    assert config.floating_settings() == (200, 20)


def test_display_preferences_roundtrip(tmp_path) -> None:
    config = AppConfig(tmp_path / "settings.ini")
    config.save_instrument_switches(False, True)
    config.save_unit_mode("V", "m")
    config.save_accuracy_tier("90d")
    config.save_ac_band("50-100k")

    assert config.instrument_switches() == (False, True)
    assert config.unit_modes()["V"] == "m"
    assert config.accuracy_tier() == "90d"
    assert config.ac_band() == "50-100k"
    config.save_scale_factor(150)
    assert config.scale_factor() == 150
    config.save_range_memory({"VOLT": (False, 10.0), "RES": (True, 100.0)})
    assert config.range_memory() == {
        "VOLT": (False, 10.0),
        "RES": (True, 100.0),
    }
    config.save_csv_directory(str(tmp_path / "csv"))
    assert config.csv_directory() == tmp_path / "csv"
