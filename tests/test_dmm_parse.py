from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.domain.models import InstrumentStatus, ScpiError, SerialSettings
from app.instrument.dmm import Dmm, DmmError
from app.domain.functions import describe_function


class FakeIO:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.commands: list[str] = []
        self.is_open = True
        self.timed_response = ""
        self.opened_settings = None
        self.close_count = 0

    def open(self, settings) -> None:
        self.opened_settings = settings
        self.is_open = True

    def close(self) -> None:
        self.close_count += 1
        self.is_open = False

    def write_line(self, command: str) -> None:
        self.commands.append(command)

    def query_line(self, command: str, timeout_ms: int | None = None) -> str:
        self.commands.append(command)
        if not self.responses:
            raise AssertionError(f"没有为 {command} 准备响应")
        return self.responses.pop(0)

    def query_line_timed(
        self,
        command: str,
        timeout_ms: int | None = None,
    ) -> tuple[str, int, int]:
        self.commands.append(command)
        now = time.perf_counter_ns()
        return self.timed_response, now, now + 1_000_000


def _dmm_with(responses: list[str]) -> Dmm:
    dmm = Dmm()
    dmm._io = FakeIO(responses)  # type: ignore[assignment]
    dmm.status = InstrumentStatus(
        function=describe_function("VOLT"),
        nplc="1",
        range_text="10",
        terminal="FRON",
    )
    return dmm


def test_single_read_parses_value() -> None:
    dmm = _dmm_with(["+1.23456789E-03"])
    reading = dmm.single_read()
    assert reading.value == pytest.approx(0.00123456789)
    assert reading.unit == "V"
    assert reading.ovld is False


def test_single_read_flags_ovld() -> None:
    dmm = _dmm_with(["+9.90000000E+37"])
    reading = dmm.single_read()
    assert reading.ovld is True


def test_single_read_rejects_multiple_values() -> None:
    dmm = _dmm_with(["+1.0E+00,+2.0E+00"])
    with pytest.raises(DmmError):
        dmm.single_read()


def test_error_queue_stops_at_no_error() -> None:
    dmm = _dmm_with(['-113,"Undefined header"', '+0,"No error"'])
    errors = dmm.read_error_queue()
    assert errors == [ScpiError(code=-113, raw='-113,"Undefined header"')]


def test_batch_read_splits_one_line_and_checks_count() -> None:
    dmm = _dmm_with([])
    assert isinstance(dmm._io, FakeIO)
    dmm._io.timed_response = "+1.0E+00,+2.0E+00,+3.0E+00"
    batch = dmm.read_batch(3)
    assert len(batch.readings) == 3
    assert [reading.value for reading in batch.readings] == [1.0, 2.0, 3.0]
    assert batch.start_ns <= batch.end_ns
    assert batch.readings[0].timestamp_ns <= batch.readings[-1].timestamp_ns


def test_batch_read_rejects_wrong_count() -> None:
    dmm = _dmm_with([])
    assert isinstance(dmm._io, FakeIO)
    dmm._io.timed_response = "+1.0E+00,+2.0E+00"
    with pytest.raises(DmmError):
        dmm.read_batch(3)


def test_local_open_sends_no_scpi() -> None:
    dmm = Dmm()
    fake = FakeIO([])
    dmm._io = fake  # type: ignore[assignment]
    settings = SerialSettings(resource="ASRL10::INSTR")
    dmm.open_local(settings)
    assert fake.opened_settings == settings
    assert dmm.local_only is True
    assert fake.commands == []
    dmm.close()
    assert fake.close_count == 1
    assert fake.commands == []
