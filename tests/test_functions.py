from app.domain.functions import digits_for, display_digits, function_spec


def test_function_spec_dcv_range() -> None:
    spec = function_spec("VOLT")
    assert spec.label == "VDC"
    assert spec.conf_command == "VOLT:DC"
    assert 0.1 in spec.ranges
    assert 1000 in spec.ranges


def test_function_spec_acv() -> None:
    spec = function_spec("VOLT:AC")
    assert spec.label == "VAC"
    assert spec.supports_ac_filter is True
    assert spec.supports_nplc is False


def test_function_spec_fixed_cont() -> None:
    spec = function_spec("CONT")
    assert spec.fixed_range is True


def test_fixed_52_digits_for_continuity_and_diode() -> None:
    assert display_digits("二极管", 1, True) == "5½"
    assert display_digits("导通", 0.02, False) == "5½"


def test_auto_digits_mapping() -> None:
    assert digits_for(0.02, False) == "4½"
    assert digits_for(0.2, False) == "5½"
    assert digits_for(1, True) == "5½"
    assert digits_for(1, False) == "5½"
    assert digits_for(10, True) == "6½"
    assert digits_for(10, False) == "6½"
    assert digits_for(100, False) == "6½"
