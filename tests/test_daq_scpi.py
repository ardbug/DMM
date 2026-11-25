from app.instrument.daq34970a import Daq34970A


class FakeIO:
    def __init__(self) -> None:
        self.commands = []
        self.queries = []

    def write_line(self, command: str) -> None:
        self.commands.append(command)

    def query_line(self, command: str, timeout_ms=None) -> str:
        self.queries.append(command)
        return "Keysight Technologies,34901A,0,1.0"


def test_scpi_query_with_parameter_reads_response() -> None:
    io = FakeIO()
    device = Daq34970A(io)
    assert "34901A" in device.scpi("SYST:CTYP? 100")
    assert io.queries == ["SYST:CTYP? 100"]
    assert io.commands == []


def test_scpi_command_does_not_wait_for_response() -> None:
    io = FakeIO()
    device = Daq34970A(io)
    assert device.scpi("*CLS") == ""
    assert io.commands == ["*CLS"]
    assert io.queries == []
