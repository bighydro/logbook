"""`logbook days --from DATE --to DATE [--json]`: a window of the record, one line per day — the night,
the kilometres moved, the flights, the stays with what attached, the people confirmed, the health
triple, and a gap marker when a source that is usually present has no lines that day. Composed
from the Day (`logbook/day.py`) over readings of the window in chunks, so a year streams through the
index in seconds and never costs a reading per day. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, KARI, KARI_ID, PLACES, TZ, attendee, dwell, event, persona_record, resolution, utc
from test_day import _gap_record, _health

from logbook import cli, reading
from logbook import day as day_reader
from logbook import days as days_reader
from logbook.index import Index
from logbook.store import Logbook

ARROW = "→"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["days", *args])
    return capsys.readouterr().out


def _rows(capsys: pytest.CaptureFixture[str], *args: str) -> list[dict[str, Any]]:
    out = _run(capsys, *args, "--json")
    return [json.loads(line) for line in out.splitlines() if line]


# -- the fortnight, one line per day ------------------------------------------------------------------------


def test_the_fortnight_is_one_line_per_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    rows = _rows(capsys, "--from", "2026-06-08", "--to", "2026-06-21")
    assert [r["day"] for r in rows] == [f"2026-06-{d:02d}" for d in range(8, 22)]
    by_day = {r["day"]: r for r in rows}

    office = by_day["2026-06-09"]
    assert office["weekday"] == "Tuesday"
    assert office["night"] == {
        "where": "Home",
        "home": True,
        "aboard": None,
        "in_transit": False,
        "stay": office["night"]["stay"],
    }
    assert office["night"]["stay"], "the night points at its stay"
    assert office["country"] == "NO"
    assert office["flights"] == [] and office["health"] is None
    assert office["stays"]["count"] == 3, "home, the office, home"
    assert office["stays"]["attached"] == 0 and office["stays"]["with_attachments"] == 0
    assert office["people"] == {"confirmed": 0, "names": []}
    assert 1000 < office["moved_m"] < 1600, "two walks of 600 m"
    assert [s["source"] for s in office["sources"]] == ["dawarich"]
    assert office["gaps"] == []

    lunch = by_day["2026-06-10"]
    assert lunch["people"] == {"confirmed": 1, "names": ["Kari Nordmann"]}
    assert lunch["stays"]["count"] == 5, "home, the office, the cafe, the office, home"
    assert lunch["stays"]["with_attachments"] == 1
    assert lunch["stays"]["attached"] == 2, "the lunch and the photo, at the cafe"

    aboard = by_day["2026-06-13"]
    assert aboard["night"]["where"] == "aboard Solvind" and aboard["night"]["aboard"] == "solvind"
    assert aboard["night"]["home"] is False
    assert aboard["people"]["names"] == ["Ola Nordmann"], "the note says who was there"

    zurich = by_day["2026-06-15"]
    assert zurich["night"]["where"].startswith("47.37") and zurich["night"]["where"].endswith(" (Zurich)")
    assert zurich["night"]["home"] is False and zurich["country"] == "CH"
    [flight] = zurich["flights"]
    assert (flight["carrier"], flight["number"], flight["from"], flight["to"]) == ("XY", "561", "OSL", "ZRH")
    assert flight["evidence"] == "tracked" and flight["line"]
    assert zurich["moved_m"] > 1_000_000, "Oslo to Zürich"
    assert by_day["2026-06-18"]["flights"][0]["number"] == "562" and by_day["2026-06-18"]["country"] == "NO"

    assert lb.meta["head"] == head, "days writes nothing"
    text = _run(capsys, "--from", "2026-06-08", "--to", "2026-06-21")
    lines = text.splitlines()
    assert len(lines) == 14
    assert lines[1].startswith("2026-06-09  Tue  Home")
    assert "0 stays" not in lines[1] and "3 stays" in lines[1] and "1.2 km" in lines[1]
    [z] = [line for line in lines if line.startswith("2026-06-15")]
    assert "  Mon  47.37" in z and "(Zurich) CH" in z and f"XY 561 OSL{ARROW}ZRH" in z
    assert f"{zurich['moved_m'] / 1000:,.0f} km" in z, "the kilometres, with a thousands separator"
    [sat] = [line for line in lines if line.startswith("2026-06-13")]
    assert "aboard Solvind NO" in sat and "with 1" in sat
    [wed] = [line for line in lines if line.startswith("2026-06-10")]
    assert "5 stays (2 attached)" in wed and "with 1" in wed


def test_days_agree_with_the_day(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every line of the window says what the Day of that day says: the same night, country,
    flights, health and sources — the chunked reading changes nothing."""
    lb = persona_record(tmp_path, monkeypatch)
    rows = list(days_reader.read(lb, "2026-06-07", "2026-06-22"))
    assert len(rows) == 16
    for row in rows:
        data = day_reader.read(lb, row["day"])
        night = data["nights"]["after"]
        assert row["night"]["where"] == night["where"], row["day"]
        assert row["night"]["home"] == night["home"] and row["night"]["in_transit"] == night["in_transit"]
        assert row["country"] == data["country"]["code"]
        assert [f["line"] for f in row["flights"]] == [f["line"] for f in data["flights"]]
        assert row["health"] == data["health"]
        assert row["sources"] == data["sources"]
        stays = [e for e in data["timeline"] if e["kind"] in ("stay", "aboard")]
        assert row["stays"]["count"] == len(stays)


def test_the_chunk_size_changes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every number and name is the same whatever the chunk. The one thing a window clips is a
    stay's start, and the night's stay id carries it (`stays.Segment.id`): a hotel stay of three
    nights starts, in a reading that opens on its second day, at that day's midnight, as it does
    for `day` of that day; so the ids are left out of the comparison."""
    lb = persona_record(tmp_path, monkeypatch)

    def without_ids(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{**r, "night": {**r["night"], "stay": None}} for r in rows]

    whole = list(days_reader.read(lb, "2026-06-08", "2026-06-21"))
    for chunk_days in (1, 3, 5):
        chunked = list(days_reader.read(lb, "2026-06-08", "2026-06-21", chunk_days=chunk_days))
        assert without_ids(chunked) == without_ids(whole), chunk_days
    with pytest.raises(ValueError):
        next(days_reader.read(lb, "2026-06-08", "2026-06-21", chunk_days=0))


# -- the gap marker and the health triple -------------------------------------------------------------------


def _week_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Monday 6 to Saturday 11 July 2026 at home: the tracker speaks every day, the watch every day
    but Thursday, the calendar once."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    days = [f"2026-07-{d:02d}" for d in range(6, 12)]
    drafts: list[dict[str, Any]] = [resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann")]
    for day in days:
        drafts += dwell(day, "00:00", "24:00", HOME, every_min=10)
        if day != "2026-07-09":
            drafts.append(_health(utc(day, "08:00"), "steps", 4000, "Watch7,1", end=utc(day, "08:15")))
            drafts.append(_health(utc(day, "05:00"), "resting_hr", 55, "Watch7,1"))
    drafts.append(
        event(utc("2026-07-07", "12:00"), utc("2026-07-07", "13:00"), "Lunch", [attendee(KARI["email"])])
    )
    lb.append_many(drafts)
    (lb.root / "places.json").write_text(json.dumps({"Home": PLACES["Home"]}), encoding="utf-8")
    return lb


def test_a_usual_source_with_no_lines_on_a_day_is_a_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _week_record(tmp_path, monkeypatch)
    rows = _rows(capsys, "--from", "2026-07-06", "--to", "2026-07-12")
    by_day = {r["day"]: r for r in rows}
    assert by_day["2026-07-07"]["gaps"] == [], "every usual source spoke"
    assert by_day["2026-07-09"]["gaps"] == ["apple-health"], "the watch is usual and silent"
    assert by_day["2026-07-10"]["gaps"] == [], "a calendar entry on one day of six is not usual"
    assert by_day["2026-07-12"]["gaps"] == ["apple-health", "dawarich"], "a day past the record: everything"
    assert by_day["2026-07-12"]["sources"] == [] and by_day["2026-07-12"]["night"]["in_transit"] is True
    assert by_day["2026-07-10"]["health"] == {
        "sleep_h": None,
        "steps": 4000,
        "resting_hr": 55,
        "hrv": None,
        "lines": by_day["2026-07-10"]["health"]["lines"],
    }
    text = _run(capsys, "--from", "2026-07-06", "--to", "2026-07-12")
    lines = {line[:10]: line for line in text.splitlines()}
    assert "gap" not in lines["2026-07-07"]
    assert lines["2026-07-09"].endswith("gap apple-health")
    assert "4,000 steps · resting 55 bpm" in lines["2026-07-10"]
    assert "sleep" not in lines["2026-07-10"], "a triple shows the numbers it has"
    assert "in transit" in lines["2026-07-12"] and "nothing logged" in lines["2026-07-12"]
    assert lines["2026-07-12"].endswith("gap apple-health, dawarich")


def test_the_health_triple_takes_the_correction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _gap_record(tmp_path, monkeypatch)
    [row] = _rows(capsys, "--from", "2026-07-02", "--to", "2026-07-02")
    assert (row["health"]["sleep_h"], row["health"]["steps"], row["health"]["resting_hr"]) == (7.0, 3250, 56)
    assert row["stays"]["count"] == 3 and row["people"]["confirmed"] == 0, "an all-day entry confirms nobody"
    text = _run(capsys, "--from", "2026-07-02", "--to", "2026-07-02")
    assert "sleep 7.0 h · 3,250 steps · resting 56 bpm" in text


def test_usual_sources_come_from_one_index_aggregate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = _week_record(tmp_path, monkeypatch)
    with lb.index() as idx:
        logged, per_source = idx.source_days("2026-07-06", "2026-07-12")
    assert logged == 6
    assert per_source == {"dawarich": 6, "apple-health": 5, "ios-calendar": 1}
    assert days_reader.usual_sources(lb, "2026-07-06", "2026-07-12") == ["apple-health", "dawarich"]
    assert days_reader.usual_sources(lb, "2026-08-01", "2026-08-31") == []


# -- streaming: a year through the index, never a scan, never a reading per day ------------------------------


def test_a_year_streams_in_chunks_through_the_index_never_a_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    with lb.index():
        pass  # built once, here, so the readings below cannot be the rebuild

    def scan(*_: Any, **__: Any) -> Any:
        raise AssertionError("days never sweeps the files")

    monkeypatch.setattr(Logbook, "lines", scan)
    monkeypatch.setattr(Logbook, "lines_unsorted", scan)
    monkeypatch.setattr(Logbook, "located_lines", scan)
    monkeypatch.setattr(Index, "of_kind", scan)
    readings: list[tuple[str, str]] = []
    real = reading.read

    def counted(lb_: Logbook, first: str, last: str, airports: Any = None) -> reading.Reading:
        readings.append((first, last))
        return real(lb_, first, last, airports)

    monkeypatch.setattr(reading, "read", counted)
    rows = days_reader.read(lb, "2026-01-01", "2026-12-31")
    first = next(rows)
    assert first["day"] == "2026-01-01" and len(readings) == 1, "the first line comes after one reading"
    rest = list(rows)
    assert len(rest) == 364 and rest[-1]["day"] == "2026-12-31"
    assert len(readings) <= 13, "a year is at most a reading a month, never one a day"
    assert all(last >= first for first, last in readings)
    logged = [r["day"] for r in [first, *rest] if r["sources"]]
    assert logged == [
        "2026-06-01",
        *(f"2026-06-{d:02d}" for d in range(8, 22)),
    ], "the resolutions, the fortnight"


# -- the edges --------------------------------------------------------------------------------------------


def test_the_window_defaults_to_the_record_and_rejects_nonsense(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    rows = _rows(capsys)
    assert [rows[0]["day"], rows[-1]["day"]] == ["2026-06-08", "2026-06-21"], "the days the track covers"
    rows = _rows(capsys, "--to", "2026-06-09")
    assert [r["day"] for r in rows] == ["2026-06-08", "2026-06-09"]
    with pytest.raises(SystemExit) as e:
        cli.main(["days", "--from", "2026-06-10", "--to", "2026-06-09"])
    assert e.value.code == 2 and "backwards" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["days", "--from", "2026-13-01", "--to", "2026-06-09"])
    assert e.value.code == 2 and "not a date" in capsys.readouterr().err


def test_an_empty_record_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _run(capsys) == "no days: the record has no lines\n"
    assert _run(capsys, "--json") == ""
    rows = _rows(capsys, "--from", "2026-07-01", "--to", "2026-07-02")
    assert [r["day"] for r in rows] == ["2026-07-01", "2026-07-02"] and rows[0]["gaps"] == []
