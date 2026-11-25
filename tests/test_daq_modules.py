from app.instrument.daq_modules import parse_slot


def test_34901a_slot_channels() -> None:
    info = parse_slot(100, "HEWLETT-PACKARD,34901A,0,2.3")
    assert info.model == "34901A"
    assert info.channels[0] == 101
    assert info.channels[-1] == 122
    assert info.current_channels == (121, 122)
    assert info.channel_text == "101–122"


def test_empty_slot_and_second_slot() -> None:
    assert parse_slot(200, "HEWLETT-PACKARD,0,0,0").is_empty
    info = parse_slot(200, "HEWLETT-PACKARD,34901A,0,2.3")
    assert info.channels[0] == 201
    assert info.channels[-1] == 222
