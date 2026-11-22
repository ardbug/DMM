from app.ui.floating_window import (
    floating_text,
    floating_unit,
    floating_value,
)


def test_unit_is_four_characters() -> None:
    assert floating_unit("mV", "VDC") == "mVDC"
    assert floating_unit("V", "VDC") == " VDC"
    assert floating_unit("kHz", "频率") == " KHZ"
    assert floating_unit("MΩ", "2WΩ") == "MOHM"
    assert floating_unit("mA", "DCI") == "mADC"
    assert floating_unit("A", "DCI") == " ADC"
    assert floating_unit("mA", "ACI") == "mAAC"


def test_value_is_fixed_seven_digits_plus_point() -> None:
    sign, body = floating_value("7.027600", "6½")
    assert sign == " "
    assert body == "7.027600"
    sign, body = floating_value("-7.02760", "5½")
    assert sign == "-"
    assert body == "7.02760 "
    sign, body = floating_value("7.0276", "4½")
    assert sign == " "
    assert body == "7.0276  "


def test_full_text_has_fixed_width() -> None:
    text = floating_text("7.027600", "V", "VDC", "6½")
    assert text == " 7.027600 VDC"
    assert len(text) == 13
    assert floating_text("", "", "VDC", "5½") == "-"
    assert floating_text("OPEN", "", "导通", "5½") == "OPEN"
    assert floating_text("7.02760", "V", "VDC", "6½") == " 7.027600 VDC"
    assert floating_text("7.02760", "V", "VDC", "5½") == " 7.02760  VDC"
