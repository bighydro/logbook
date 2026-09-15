"""Generated stress tests: 200,000 synthetic points. `slow` — run with LOGBOOK_SLOW=1."""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.adapters import dawarich
from logbook.store import Logbook

POINTS = 200_000
MIN_LINES_PER_SECOND = 20_000
TRACKER = "00000000-0000-4000-8000-00000000abcd"
START = 1_775_970_000  # 2026-04-12T05:00:00Z, the fixture's first point


def _point(i: int) -> dict[str, Any]:
    """One synthetic Dawarich feature: a walk around Oslo, one point every 10 s."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [10.7 + (i % 1000) / 1e4, 59.9 + (i % 700) / 1e4]},
        "properties": {
            "timestamp": START + i * 10,
            "accuracy": 5 + i % 20,
            "altitude": f"{10 + i % 50}.0",
            "velocity": f"{(i % 30) / 10}",
            "course": f"{i % 360}.0",
            "vertical_accuracy": 3,
            "anomaly": None,
            "track_id": i // 500,
            "tracker_id": TRACKER,
            "battery": 100 - (i // 2000) % 100,
            "ssid": None,
            "bssid": None,
            "motion_data": {"stationary": i % 7 == 0},
            "geodata": None,
        },
    }


def _drafts(n: int) -> Iterator[dict[str, Any]]:
    for i in range(n):
        yield {
            "at": dawarich._rfc3339(START + i * 10),
            "end": None,
            "tz": None,
            "source": "dawarich",
            "kind": "location",
            "tier": 1,
            "payload": dawarich._payload(_point(i)),
        }


def _write_export(path: Path, n: int) -> None:
    with path.open("w", encoding="utf-8") as fh:
        fh.write('{"type": "FeatureCollection", "features": [\n')
        for i in range(n):
            fh.write(("," if i else "") + json.dumps(_point(i)) + "\n")
        fh.write("]}\n")


@pytest.mark.slow
def test_append_many_throughput_is_at_least_20k_lines_per_second(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    drafts = list(_drafts(POINTS))  # generation is not what is being measured
    started = time.perf_counter()
    n = lb.append_many(drafts)
    elapsed = time.perf_counter() - started
    assert n == POINTS
    rate = n / elapsed
    print(f"\nappend_many: {n:,} lines in {elapsed:.1f}s = {rate:,.0f} lines/s")
    assert rate >= MIN_LINES_PER_SECOND
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == POINTS


@pytest.mark.slow
def test_dawarich_streams_a_large_export_into_a_valid_logbook(tmp_path):
    export = tmp_path / "export.json"
    _write_export(export, POINTS)
    assert dawarich.sniff(export)
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    started = time.perf_counter()
    n = lb.append_many(dawarich.run(export))
    elapsed = time.perf_counter() - started
    print(f"\ndawarich → append_many: {n:,} lines in {elapsed:.1f}s = {n / elapsed:,.0f} lines/s")
    assert n == POINTS
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == POINTS


@pytest.mark.slow
def test_show_on_200k_lines_takes_under_a_second_after_indexing(tmp_path, monkeypatch, capsys):
    from logbook import cli

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append_many(_drafts(POINTS))
    lb.index()
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    started = time.perf_counter()
    cli.main(["show", "2026-04-13"])  # a full day: 8,640 points at one every 10 s
    elapsed = time.perf_counter() - started
    rows = capsys.readouterr().out.splitlines()
    print(f"\nshow: {len(rows) - 1:,} rows in {elapsed:.2f}s")
    assert len(rows) - 1 == 8_640
    assert elapsed < 1.0
