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
    with lb.index():
        pass
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    started = time.perf_counter()
    cli.main(["show", "2026-04-13"])  # a full day: 8,640 points at one every 10 s
    elapsed = time.perf_counter() - started
    rows = capsys.readouterr().out.splitlines()
    print(f"\nshow: {len(rows) - 1:,} rows in {elapsed:.2f}s")
    assert len(rows) - 1 == 8_640
    assert elapsed < 1.0


# -- three million lines: verify and dedupe never hold the log (#28, #29) -----------------------------

BIG = 3_000_000
SMALL = 1_000_000
FLAT_MB = 48  # how much more verify may take on three million lines than on one: the heap, not the log
DEDUPE_CEILING_MB = 256  # a 100,000-draft batch deduped through the index on three million lines
MEASURE = """
import resource, sys, time
from pathlib import Path
from logbook.store import Logbook
mode, root = sys.argv[1], Path(sys.argv[2])
lb = Logbook(root)
t = time.perf_counter()
if mode == "verify":
    seq, _head, errors = lb.verify()
    assert errors == [], errors
    result = seq
else:
    drafts = ({"at": "2026-01-01T00:00:00Z", "source": "sim", "kind": "note", "tier": 1,
               "payload": {"schema": "note/v1", "raw_id": f"sim-{i}", "text": "x"}} for i in range(100_000))
    result = lb.append_many(drafts)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
if sys.platform != "darwin":
    rss *= 1024  # Linux reports kilobytes
print(result, round(time.perf_counter() - t, 1), round(rss / 1e6))
"""


def _synthetic_drafts(n: int) -> Iterator[dict[str, Any]]:
    """`n` notes spread evenly over ten years of month files, raw_id sim-0 … sim-(n-1). Synthetic."""
    from datetime import UTC, datetime

    start, step = 1_500_000_000, (10 * 365 * 86400) // n  # 2017-07-14T02:40:00Z onwards
    for i in range(n):
        at = datetime.fromtimestamp(start + i * step, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        yield {
            "at": at,
            "source": "sim",
            "kind": "note",
            "tier": 1,
            "payload": {"schema": "note/v1", "raw_id": f"sim-{i}", "text": f"synthetic line {i}"},
        }


def _measure(mode: str, root: Path) -> tuple[int, float, int]:
    """(result, seconds, peak RSS in MB) of `mode` on the record, in a process of its own."""
    import subprocess

    out = subprocess.run(
        [sys.executable, "-c", MEASURE, mode, str(root)], capture_output=True, encoding="utf-8", check=True
    ).stdout.split()
    return int(out[0]), float(out[1]), int(out[2])


@pytest.fixture(scope="module")
def big_record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    lb = Logbook.init(tmp_path_factory.mktemp("big") / "lb", "Europe/Oslo")
    started = time.perf_counter()
    assert lb.append_many(_synthetic_drafts(BIG)) == BIG
    print(f"\nbuilt {BIG:,} lines over {len(lb.files())} month files in {time.perf_counter() - started:.0f}s")
    return lb


@pytest.mark.slow
def test_verify_peak_memory_is_flat_as_the_record_grows(big_record: Logbook, tmp_path: Path):
    small = Logbook.init(tmp_path / "small", "Europe/Oslo")
    assert small.append_many(_synthetic_drafts(SMALL)) == SMALL
    n_small, s_small, rss_small = _measure("verify", small.root)
    n_big, s_big, rss_big = _measure("verify", big_record.root)
    print(f"\nverify: {n_small:,} lines in {s_small}s, peak {rss_small} MB")
    print(f"verify: {n_big:,} lines in {s_big}s, peak {rss_big} MB")
    assert (n_small, n_big) == (SMALL, BIG)
    assert rss_big - rss_small < FLAT_MB


@pytest.mark.slow
def test_dedupe_of_a_batch_against_three_million_lines_stays_in_the_index(big_record: Logbook):
    appended, seconds, rss = _measure("dedupe", big_record.root)
    print(f"\ndedupe: 100,000 drafts already in the log, {seconds}s, peak {rss} MB")
    assert appended == 0
    assert rss < DEDUPE_CEILING_MB
