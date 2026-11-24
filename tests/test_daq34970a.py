from app.domain.models import SerialSettings
from app.instrument.daq34970a import (
    Daq34970A,
    DaqConfig,
    parse_channels,
)


class FakeIo:
    def __init__(self) -> None:
        self.writes: list[str] = []
        self.is_open = False
        self.scan_response = "+1.25000000E+00"

    def open(self, settings: SerialSettings) -> None:
        self.is_open = True

    def write_line(self, command: str) -> None:
        self.writes.append(command)

    def query_line(self, command: str, timeout_ms: int | None = None) -> str:
        if command == "*IDN?":  # noqa: S105
            return "KEYSIGHT,34970A,0,1.0"
        if command == "READ?":
            return self.scan_response
        return ""

    def close(self) -> None:
        self.is_open = False


def test_thermocouple_k_configuration() -> None:
    io = FakeIo()
    device = Daq34970A(io)
    device.open(SerialSettings(resource="gpib0,9", interface="gpib"))
    device.configure(
        DaqConfig(channel=101, function="TEMP", temperature="TC:K", nplc=1)
    )
    assert "CONF:TEMP TC,K,(@101)" in io.writes
    assert "UNIT:TEMP C,(@101)" in io.writes
    assert "SENS:TEMP:NPLC 1,(@101)" in io.writes
    reading = device.read()
    assert reading.value == 1.25


def test_rtd_4wire_configuration() -> None:
    io = FakeIo()
    device = Daq34970A(io)
    device.open(SerialSettings(resource="gpib0,9", interface="gpib"))
    device.configure(
        DaqConfig(
            channel=103,
            function="TEMP",
            temperature="RTD:4W:100",
            nplc=10,
        )
    )
    assert "CONF:TEMP FRTD,85,(@103)" in io.writes
    assert "SENS:TEMP:NPLC 10,(@103)" in io.writes


def test_rtd_1000_type_sets_nominal_resistance() -> None:
    io = FakeIo()
    device = Daq34970A(io)
    device.open(SerialSettings(resource="gpib0,9", interface="gpib"))
    device.configure(
        DaqConfig(
            channel=104,
            function="TEMP",
            temperature="RTD:4W:1000",
        )
    )
    assert "SENS:TEMP:TRAN:FRTD:RES 1000,(@104)" in io.writes


def test_parse_scan_channels() -> None:
    assert parse_channels("101:103,110") == [101, 102, 103, 110]
    assert parse_channels("110:108，121") == [108, 109, 110, 121]


def test_scan_configuration_and_read() -> None:
    io = FakeIo()
    io.scan_response = "+1.0,+2.0,+3.0"
    device = Daq34970A(io)
    device.open(SerialSettings(resource="gpib0,9", interface="gpib"))
    config = DaqConfig(
        scan=True,
        scan_list="101:103",
        function="VOLT:DC",
        nplc=1,
    )
    device.configure(config)
    assert "CONF:VOLT:DC (@101:103)" in io.writes
    assert "ROUT:SCAN (@101:103)" in io.writes
    samples = device.read_scan()
    assert [channel for channel, _ in samples] == [101, 102, 103]
    assert [reading.value for _, reading in samples] == [1.0, 2.0, 3.0]


def test_current_channel_configuration() -> None:
    io = FakeIo()
    device = Daq34970A(io)
    device.open(SerialSettings(resource="gpib0,9", interface="gpib"))
    device.configure(
        DaqConfig(channel=121, function="CURR:DC", nplc=0.2)
    )
    assert "CONF:CURR:DC (@121)" in io.writes
    assert "SENS:CURR:DC:NPLC 0.2,(@121)" in io.writes
