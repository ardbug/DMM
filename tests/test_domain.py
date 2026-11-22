from app.domain.functions import (
    describe_function,
    digits_to_nplc,
    normalize_function,
    nplc_to_digits,
)
from app.ui.widgets.common import (
    FIELD_WIDTH,
    digits_from_nplc,
    format_measurement,
    format_measurement_fixed,
    format_nplc,
    format_range,
    terminal_text,
    unit_options,
)


def test_normalize_function_removes_quotes() -> None:
    assert normalize_function('"VOLT"') == "VOLT"
    assert normalize_function(" 'volt:ac' ") == "VOLT:AC"


def test_describe_function_mapping() -> None:
    assert describe_function("VOLT").label == "VDC"
    assert describe_function("VOLT:AC").unit == "V"
    assert describe_function("FRES").label == "4WΩ"
    assert describe_function("FREQ").unit == "Hz"
    assert describe_function("UNKNOWN").unit == ""


def test_format_measurement_uses_engineering_prefix() -> None:
    text, unit = format_measurement(0.000208887, "V")
    assert (text, unit) == ("0.20888700", "mV")

    text, unit = format_measurement(10.0, "V")
    assert (text, unit) == ("10.000000", "V")

    text, unit = format_measurement(1_250_000.0, "Ω")
    assert (text, unit) == ("1.2500000", "MΩ")


def test_zero_and_small_values() -> None:
    assert format_measurement(0.0, "V") == ("0.000000", "V")
    text, unit = format_measurement(1e-9, "V")
    assert unit == "mV"
    assert text == "0.0000010000000"


def test_fixed_width_is_stable_for_sign_and_digits() -> None:
    pos, unit = format_measurement_fixed(0.000434811, "V", "5½")
    neg, _ = format_measurement_fixed(-0.000434811, "V", "5½")
    six, _ = format_measurement_fixed(0.000434811, "V", "6½")

    assert len(pos) == FIELD_WIDTH
    assert len(neg) == FIELD_WIDTH
    assert len(six) == FIELD_WIDTH
    assert pos.startswith(" ")
    assert unit == "mV"
    assert pos[1:] != neg[1:]


def test_range_nplc_digits() -> None:
    assert format_nplc("+1.00000000E+01") == "10"
    assert digits_from_nplc("0.02") == "4½"
    assert digits_from_nplc("0.2") == "5½"
    assert digits_from_nplc("1") == "5½"
    assert digits_from_nplc("10") == "6½"
    assert digits_from_nplc("100") == "6½"
    assert format_range("+1.00000000E-01", "V") == "100 mV"
    assert terminal_text("FRON") == "前端"
    assert terminal_text("REAR") == "后端"


def test_manual_unit_modes() -> None:
    micro, unit = format_measurement_fixed(0.000434811, "V", "5½", "auto")
    milli, unit_m = format_measurement_fixed(0.000434811, "V", "5½", "m")
    volt, unit_v = format_measurement_fixed(0.000434811, "V", "5½", "")
    assert unit == "mV"
    assert unit_m == "mV"
    assert unit_v == "V"
    assert len(micro) == len(milli) == len(volt) == FIELD_WIDTH
    assert unit_options("Ω") == [("auto", "AUTO"), ("", "Ω"), ("k", "kΩ"), ("M", "MΩ")]
    assert unit_options("A") == [("auto", "AUTO"), ("m", "mA"), ("", "A")]
    assert unit_options("V", "二极管") == [("auto", "AUTO"), ("", "V")]


def test_small_value_never_uses_scientific_notation() -> None:
    text, unit = format_measurement_fixed(0.0000123, "V", "4½", "", "VDC")
    assert unit == "V"
    assert "E" not in text
    assert len(text) == FIELD_WIDTH


def test_range_based_decimals_match_front_panel() -> None:
    text, unit = format_measurement_fixed(
        0.004, "V", "5½", "auto", "VDC", 0.1
    )
    assert (text.strip(), unit) == ("4.000", "mV")

    current, current_unit = format_measurement_fixed(
        0.0000123, "A", "4½", "auto", "DCI", 0.01
    )
    assert (current.strip(), current_unit) == ("0.012", "mA")

    diode, diode_unit = format_measurement_fixed(
        0.56604, "V", "5½", "auto", "二极管", None
    )
    assert (diode.strip(), diode_unit) == ("0.56604", "V")


def test_extra_decimals_for_averaged_readings() -> None:
    text, unit = format_measurement_fixed(
        1.23456789, "V", "5½", "manual", "VDC", 10, 1
    )
    assert (text.strip(), unit) == ("1.23457", "V")
    text, unit = format_measurement_fixed(
        0.004, "V", "5½", "auto", "VDC", 0.1, 1
    )
    assert (text.strip(), unit) == ("4.0000", "mV")


def test_auto_zero_keeps_milli_prefix_for_voltage_and_current() -> None:
    text, unit = format_measurement_fixed(
        0.0, "V", "4½", "auto", "VDC", 0.1
    )
    assert (text.strip(), unit) == ("0.00", "mV")

    text, unit = format_measurement_fixed(
        0.0, "A", "4½", "auto", "DCI", 0.01
    )
    assert unit == "mA"

    _, diode_unit = format_measurement_fixed(
        0.0, "V", "5½", "auto", "二极管", None
    )
    assert diode_unit == "V"


def test_ohms_never_use_milliohms() -> None:
    text, unit = format_measurement_fixed(
        0.004, "Ω", "6½", "auto", "2WΩ", 100
    )
    assert (text.strip(), unit) == ("0.0040", "Ω")

    text, unit = format_measurement_fixed(
        -0.003919, "Ω", "6½", "auto", "2WΩ", 100
    )
    assert (text.strip(), unit) == ("-0.0039", "Ω")


def test_function_specific_auto_units() -> None:
    _, diode_unit = format_measurement_fixed(0.5, "V", "5½", "auto", "二极管")
    _, cont_unit = format_measurement_fixed(0.0004, "Ω", "5½", "auto", "导通")
    _, current_unit = format_measurement_fixed(0.0004, "A", "5½", "auto", "DCI")
    assert diode_unit == "V"
    assert cont_unit == "Ω"
    assert current_unit == "mA"


def test_nplc_digits_mapping() -> None:
    assert nplc_to_digits(0.02) == "4½"
    assert nplc_to_digits(0.2) == "5½"
    assert nplc_to_digits(1) == "5½"
    assert nplc_to_digits(10) == "6½"
    assert nplc_to_digits(100) == "6½"
    assert digits_to_nplc("4½") == 0.02
    assert digits_to_nplc("5½") == 0.2
    assert digits_to_nplc("6½") == 10
