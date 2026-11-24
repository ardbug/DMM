from app.transport.sicl_gpib import normalize_sicl_address


def test_normalize_sicl_address() -> None:
    assert normalize_sicl_address("gpib0,1") == "gpib0,1"
    assert normalize_sicl_address("GPIB0::1::INSTR") == "gpib0,1"
    assert normalize_sicl_address("gpib2,22") == "gpib2,22"
    assert normalize_sicl_address("GPIB2::22") == "gpib2,22"


def test_normalize_rejects_invalid_address() -> None:
    for value in ("", "COM3", "ASRL3::INSTR", "gpib0", "GPIB0::"):
        try:
            normalize_sicl_address(value)
        except ValueError:
            pass
        else:
            raise AssertionError(value)
