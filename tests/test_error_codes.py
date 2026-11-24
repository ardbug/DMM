from app.domain.error_codes import (
    ERROR_CODES_34401A,
    ERROR_CODES_34970A,
    describe_error,
    filter_error_codes,
)
from app.domain.models import ScpiError


def test_known_error_code() -> None:
    error = ScpiError(-113, '-113,"Undefined header"')
    assert "未定义命令头" in describe_error(error)


def test_unknown_error_code() -> None:
    assert "未收录" in describe_error(-999)


def test_error_code_lookup_by_code_and_keyword() -> None:
    assert filter_error_codes("513") == [("513", "RS-232 parity error")]
    assert ("701", "Cal security disabled by jumper") in filter_error_codes(
        "jumper"
    )
    assert filter_error_codes("") == list(ERROR_CODES_34401A)
    assert filter_error_codes("160") == [
        ("-160 to -168", "Block data errors")
    ]
    assert filter_error_codes("+0") == [("+0", "No error")]


def test_34970a_error_lookup() -> None:
    assert filter_error_codes("", "34970A") == list(ERROR_CODES_34970A)
    assert filter_error_codes("514", "34970A") == [
        ("514", "RS-232 only: unable to execute using HP-IB")
    ]
    assert ("251", "Unsupported temperature transducer type") in (
        filter_error_codes("transducer", "34970A")
    )
    assert ("901", "Plug-in module: unexpected data received") in (
        filter_error_codes("module", "34970A")
    )
