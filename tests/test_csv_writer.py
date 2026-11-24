from __future__ import annotations

import csv

from app.domain.models import AcquisitionConfig, Batch, Reading
from app.storage.csv_writer import CsvWriter, make_csv_path


def test_csv_path_is_compact_and_collision_safe(tmp_path) -> None:
    path = make_csv_path("VDC", tmp_path)
    assert path.parent == tmp_path
    assert path.name.startswith("VDC_")
    assert path.suffix == ".csv"
    assert len(path.stem) == len("VDC_MMDD_HHMM")
    path.write_text("", encoding="utf-8")
    second = make_csv_path("VDC", tmp_path)
    assert second != path
    assert second.name.endswith("_02.csv")
    named = make_csv_path("DCI", tmp_path, model="34401a")
    assert named.name.startswith("34401a_DCI_")


def test_csv_writer_writes_one_row_per_reading(tmp_path) -> None:
    path = tmp_path / "sample.csv"
    writer = CsvWriter(path)
    readings = tuple(
        Reading(
            value=1.0 + index,
            unit="V",
            function_label="VDC",
            ovld=False,
            raw=str(1.0 + index),
            timestamp_ns=1_700_000_000_000_000_000 + index * 1_000_000,
        )
        for index in range(3)
    )
    batch = Batch(
        readings=readings,
        config=AcquisitionConfig(nplc=1, digits="5½", rate=30, az=False),
        config_version=1,
        batch_id=1,
        start_ns=1_700_000_000_000_000_000,
        end_ns=1_700_000_000_002_000_000,
        range_text="+1.00000000E-01",
    )
    writer.start()
    writer.enqueue(batch)
    writer.stop()
    assert writer.wait(5000)

    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "时间戳"
    assert len(rows) == 4
    assert rows[0][6] == "通道"
    assert "位数" not in rows[0]
    assert rows[1][5] == "VDC"
    assert rows[1][6] == "1"
    assert rows[1][9] == "1"
    assert rows[1][11] == "0"
