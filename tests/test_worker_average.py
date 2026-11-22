from __future__ import annotations

from types import SimpleNamespace

from app.acquisition.worker import AcqWorker
from app.domain.models import AcquisitionConfig, BatchRead, Reading


class FakeDmm:
    def __init__(self) -> None:
        self.values = iter((1.0, 2.0, 3.0))
        self.status = SimpleNamespace(range_text="10")

    def read_batch(self, count: int, timeout_ms: int) -> BatchRead:
        values = [next(self.values) for _ in range(count)]
        readings = tuple(
            Reading(
                value=value,
                unit="V",
                function_label="VDC",
                ovld=False,
                raw=str(value),
                timestamp_ns=1_700_000_000_000_000_000 + index * 1_000_000,
            )
            for index, value in enumerate(values)
        )
        return BatchRead(
            readings=readings,
            start_ns=readings[0].timestamp_ns,
            end_ns=readings[-1].timestamp_ns,
        )


def test_worker_averages_n_readings() -> None:
    worker = AcqWorker()
    fake = FakeDmm()
    worker._dmm = fake
    worker._acquisition = AcquisitionConfig(
        nplc=0.02,
        rate=10,
        average_enabled=True,
        average_count=3,
    )
    worker._config_version = 1
    batches = []
    worker.batch_received.connect(batches.append)

    worker._read_and_emit(1)
    worker._read_and_emit(1)
    assert batches == []
    worker._read_and_emit(1)

    assert len(batches) == 1
    reading = batches[0].readings[0]
    assert reading.value == 2.0
    assert reading.raw == "AVG 3"
