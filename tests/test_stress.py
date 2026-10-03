"""Generated stress tests: 200,000 synthetic points up to three million lines. `stress` (timing and
memory assertions; run with LOGBOOK_STRESS=1, never in CI), except the one plain correctness test on a
large export, which is `slow` (LOGBOOK_SLOW=1; CI runs it on push to main and nightly)."""

from __future__ import annotations

import json
import random
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


@pytest.mark.stress
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


@pytest.mark.stress
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


@pytest.mark.stress
def test_verify_peak_memory_is_flat_as_the_record_grows(big_record: Logbook, tmp_path: Path):
    small = Logbook.init(tmp_path / "small", "Europe/Oslo")
    assert small.append_many(_synthetic_drafts(SMALL)) == SMALL
    n_small, s_small, rss_small = _measure("verify", small.root)
    n_big, s_big, rss_big = _measure("verify", big_record.root)
    print(f"\nverify: {n_small:,} lines in {s_small}s, peak {rss_small} MB")
    print(f"verify: {n_big:,} lines in {s_big}s, peak {rss_big} MB")
    assert (n_small, n_big) == (SMALL, BIG)
    assert rss_big - rss_small < FLAT_MB


@pytest.mark.stress
def test_dedupe_of_a_batch_against_three_million_lines_stays_in_the_index(big_record: Logbook):
    appended, seconds, rss = _measure("dedupe", big_record.root)
    print(f"\ndedupe: 100,000 drafts already in the log, {seconds}s, peak {rss} MB")
    assert appended == 0
    assert rss < DEDUPE_CEILING_MB


# -- places propose over two years: the index serves the points, no month file is read (#perf) ----------

TWO_YEARS_FIRST = "2024-07-01"  # Monday 1 July 2024 to Tuesday 30 June 2026: 730 days
TWO_YEARS_LAST = "2026-06-30"
TWO_YEARS_LINES = 500_000
PROPOSE_CEILING_S = 20.0  # the target is 20 s on four million lines; this record is an eighth of that
TWO_YEARS_TZ = "Europe/Oslo"
TWO_YEARS_HOME = (59.9139, 10.7522)
TWO_YEARS_OFFICE = (59.9100, 10.7600)
TWO_YEARS_MARINA = (59.9050, 10.7350)
TWO_YEARS_LUNCH = [
    (59.9200, 10.7400),
    (59.9165, 10.7480),
    (59.9120, 10.7700),
]  # unnamed; `propose` finds them
TWO_YEARS_EVENINGS = [
    (59.9270, 10.7320),
    (59.9180, 10.7900),
    (59.9050, 10.7800),
    (59.9300, 10.7600),
    (59.9000, 10.7200),
]
TWO_YEARS_BOAT = "nordlys"


def _two_years() -> Iterator[dict[str, Any]]:
    """Two years of one synthetic routine, day after day: home at night, the office by day, lunch at
    one of three cafes, an evening at one of five venues, the boat at the marina, two hundred and
    ten messages, three calendar entries and two notes a day. About 690 lines a day. Deterministic;
    nothing in it is real."""
    from datetime import date, datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(TWO_YEARS_TZ)
    rng = random.Random(2024)
    first, last = date.fromisoformat(TWO_YEARS_FIRST), date.fromisoformat(TWO_YEARS_LAST)

    def stamp(day: date, hour: int, minute: int, second: int = 0) -> str:
        local = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=tz)
        return local.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ")

    def point(at: str, where: tuple[float, float], subject: str | None = None) -> dict[str, Any]:
        lat = where[0] + rng.uniform(-0.00015, 0.00015)
        lon = where[1] + rng.uniform(-0.0003, 0.0003)
        payload: dict[str, Any] = {"schema": "location/v1", "lat": round(lat, 6), "lon": round(lon, 6)}
        payload["raw_id"] = f"{subject or 'owner'}:{at}"
        if subject:
            payload["subject"] = subject
        source = "ais" if subject else "dawarich"
        return {"at": at, "source": source, "kind": "location", "tier": 1, "payload": payload}

    def minutes(h0: int, m0: int, h1: int, m1: int, every: int) -> Iterator[tuple[int, int]]:
        t = h0 * 60 + m0
        while t < h1 * 60 + m1:
            yield divmod(t, 60)
            t += every

    def between(
        day: date, h0: int, m0: int, h1: int, m1: int, a: tuple[float, float], b: tuple[float, float]
    ):
        steps = list(minutes(h0, m0, h1, m1, 5))
        for n, (h, m) in enumerate(steps):
            f = n / len(steps)
            yield point(stamp(day, h, m), (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))

    day = first
    while day <= last:
        n = (day - first).days
        lunch, evening = TWO_YEARS_LUNCH[n % 3], TWO_YEARS_EVENINGS[n % 5]
        for h, m in minutes(0, 0, 7, 0, 15):
            yield point(stamp(day, h, m), TWO_YEARS_HOME)
        yield from between(day, 7, 30, 8, 0, TWO_YEARS_HOME, TWO_YEARS_OFFICE)
        for h, m in minutes(8, 0, 12, 0, 2):
            yield point(stamp(day, h, m), TWO_YEARS_OFFICE)
        for h, m in minutes(12, 5, 12, 55, 2):
            yield point(stamp(day, h, m), lunch)
        for h, m in minutes(13, 0, 17, 30, 2):
            yield point(stamp(day, h, m), TWO_YEARS_OFFICE)
        yield from between(day, 17, 30, 18, 0, TWO_YEARS_OFFICE, evening)
        for h, m in minutes(18, 30, 21, 30, 2):
            yield point(stamp(day, h, m), evening)
        for h, m in minutes(21, 45, 24, 0, 15):
            yield point(stamp(day, h, m), TWO_YEARS_HOME)
        for h, m in minutes(0, 0, 24, 0, 24):
            yield point(stamp(day, h, m), TWO_YEARS_MARINA, TWO_YEARS_BOAT)
        for i in range(210):
            at = stamp(day, 7 + (i * 7) // 100, (i * 13) % 60, i % 60)
            yield {
                "at": at,
                "source": "whatsapp",
                "kind": "message",
                "tier": 1,
                "payload": {
                    "schema": "message/v1",
                    "raw_id": f"msg:{day.isoformat()}:{i}",
                    "chat_id": f"4790000{i % 9:03d}@s.whatsapp.net",
                    "direction": "in" if i % 2 else "out",
                    "text": f"synthetic message {i}",
                },
            }
        for i, (h, m, length) in enumerate(((9, 0, 60), (14, 0, 30), (19, 0, 90))):
            start = datetime(day.year, day.month, day.day, h, m, tzinfo=tz)
            yield {
                "at": stamp(day, h, m),
                "end": (start + timedelta(minutes=length))
                .astimezone(ZoneInfo("UTC"))
                .strftime("%Y-%m-%dT%H:%M:%SZ"),
                "source": "ics",
                "kind": "event",
                "tier": 1,
                "payload": {
                    "schema": "event/v1",
                    "raw_id": f"evt:{day.isoformat()}:{i}",
                    "title": f"Entry {i}",
                },
            }
        for i, (h, m) in enumerate(((12, 30), (20, 0))):
            yield {
                "at": stamp(day, h, m),
                "source": "manual",
                "kind": "note",
                "tier": 2,
                "payload": {"schema": "note/v1", "text": f"synthetic note {i} on {day.isoformat()}"},
            }
        day += timedelta(days=1)


def _jsonl_opens(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """Every month file opened from here on: the record's lines are only ever read through `Path.open`."""
    opened: list[Path] = []
    original = Path.open

    def counting(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".jsonl":
            opened.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", counting)
    return opened


@pytest.mark.stress
def test_places_propose_over_two_years_reads_the_index_and_not_the_files(tmp_path, monkeypatch, capsys):
    """`places propose` on half a million lines over two years: the owner's points, the boat's, the
    evidence and the retractions come from the index's own columns and the clustering runs from
    there; not one month file is opened, and the two-year window is under the ceiling. The same
    command on one month is served the same way."""
    from logbook import cli

    lb = Logbook.init(tmp_path / "lb", TWO_YEARS_TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    report: list[str] = []  # printed at the end: the command's output is read through capsys meanwhile
    started = time.perf_counter()
    n = lb.append_many(_two_years())
    report.append(
        f"built {n:,} lines over {len(lb.files())} month files in {time.perf_counter() - started:.0f}s"
    )
    assert n >= TWO_YEARS_LINES
    (lb.root / "places.json").write_text(
        json.dumps(
            {
                "Home": {"lat": TWO_YEARS_HOME[0], "lon": TWO_YEARS_HOME[1], "radius_m": 120, "kind": "home"},
                "Office": {"lat": TWO_YEARS_OFFICE[0], "lon": TWO_YEARS_OFFICE[1], "radius_m": 120},
                "Marina": {
                    "lat": TWO_YEARS_MARINA[0],
                    "lon": TWO_YEARS_MARINA[1],
                    "radius_m": 150,
                    "kind": "asset-berth",
                },
            }
        ),
        encoding="utf-8",
    )
    (lb.root / "assets.json").write_text(
        json.dumps(
            {"assets": [{"id": TWO_YEARS_BOAT, "kind": "yacht", "name": "Nordlys", "mmsi": "970000001"}]}
        ),
        encoding="utf-8",
    )
    started = time.perf_counter()
    with lb.index():
        pass
    report.append(f"indexed in {time.perf_counter() - started:.0f}s")
    opened = _jsonl_opens(monkeypatch)
    started = time.perf_counter()
    cli.main(["places", "propose", "--since", TWO_YEARS_FIRST, "--until", TWO_YEARS_LAST, "--json"])
    elapsed = time.perf_counter() - started
    data = json.loads(capsys.readouterr().out)
    proposals = data["proposals"]
    report.append(f"places propose, two years: {len(proposals)} proposals in {elapsed:.1f}s")
    assert opened == [], f"month files opened: {len(opened)}"

    # The five evening venues, then the three cafes; after them the commute's midpoint and whatever
    # a jittered first point left unnamed. Each venue has a fifth of the days, three hours each.
    def same(a: tuple[float, float], b: tuple[float, float]) -> bool:
        return abs(a[0] - b[0]) < 0.0005 and abs(a[1] - b[1]) < 0.0005

    found = [(p["lat"], p["lon"]) for p in proposals[:8]]
    assert all(same(f, v) for f, v in zip(found[:5], TWO_YEARS_EVENINGS, strict=True)), "first evening order"
    assert all(any(same(f, c) for c in TWO_YEARS_LUNCH) for f in found[5:8])
    assert proposals[0]["hours"] > 400 and len(proposals[0]["stays"]) >= 140, "an evening venue, 3 h a day"
    assert all(p["nearest"] is not None for p in proposals)
    assert elapsed < PROPOSE_CEILING_S
    started = time.perf_counter()
    cli.main(["places", "propose", "--since", "2025-03-01", "--until", "2025-03-31", "--json"])
    elapsed = time.perf_counter() - started
    month = json.loads(capsys.readouterr().out)["proposals"]
    report.append(f"places propose, one month: {len(month)} proposals in {elapsed:.1f}s")
    print("\n" + "\n".join(report))
    assert opened == []
    assert len(month) >= 8 and all(p["first"].startswith("2025-03") for p in month)
    assert elapsed < PROPOSE_CEILING_S / 8
