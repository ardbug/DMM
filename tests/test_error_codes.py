from app.domain.error_codes import (
    ERROR_CODES_34401A,
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
