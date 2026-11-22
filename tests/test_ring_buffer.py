from app.acquisition.ring_buffer import RingBuffer
from app.domain.models import AcquisitionConfig, Batch, Reading


def _batch(values: list[float], start_ns: int = 1_000) -> Batch:
    readings = tuple(
        Reading(
            value=value,
            unit="V",
            function_label="VDC",
            ovld=False,
            raw=str(value),
            timestamp_ns=start_ns + index,
        )
        for index, value in enumerate(values)
    )
    return Batch(
        readings=readings,
        config=AcquisitionConfig(),
        config_version=1,
        batch_id=1,
        start_ns=start_ns,
        end_ns=start_ns + len(values),
    )


def test_ring_wraps_and_keeps_latest() -> None:
    ring = RingBuffer(capacity=3)
    ring.append_batch(_batch([1.0, 2.0]))
    ring.append_batch(_batch([3.0, 4.0], start_ns=2_000))
    assert len(ring) == 3
    assert [value for value, _, _ in ring.iter_ordered()] == [2.0, 3.0, 4.0]
    assert ring.latest()[0] == 4.0


def test_latest_n() -> None:
    ring = RingBuffer(capacity=10)
    ring.append_batch(_batch([1.0, 2.0, 3.0]))
    assert [value for value, _, _ in ring.latest_n(2)] == [2.0, 3.0]
    assert ring.latest_n(0) == []
