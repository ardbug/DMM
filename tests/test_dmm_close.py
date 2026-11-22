from __future__ import annotations

from app.instrument.dmm import Dmm


class FakeCloseIO:
    def __init__(self) -> None:
        self.is_open = True
        self.commands: list[str] = []
        self.closed = False

    def write_line(self, command: str) -> None:
        self.commands.append(command)

    def close(self) -> None:
        self.closed = True
        self.is_open = False


def test_close_uses_space_form_for_display_on() -> None:
    dmm = Dmm()
    fake = FakeCloseIO()
    dmm._io = fake  # type: ignore[assignment]

    dmm.close(restore_local=True)

    assert fake.commands == ["DISP ON", "SYST:LOC"]
    assert fake.closed is True


def test_display_and_beeper_commands() -> None:
    dmm = Dmm()
    fake = FakeCloseIO()
    dmm._io = fake  # type: ignore[assignment]

    dmm.set_display(False)
    dmm.set_display(True)
    dmm.set_beeper(False)
    dmm.set_beeper(True)

    assert fake.commands == [
        "DISP OFF",
        "DISP ON",
        "SYST:BEEP:STAT OFF",
        "SYST:BEEP:STAT ON",
    ]
