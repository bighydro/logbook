"""Three things a real week showed on the day page, on one synthetic day of the Oslo persona, who does
not exist: the same calendar entry from two calendars shows once, naming both; a car move between two
points near Gardermoen names no airport pair while the flight to Zürich does; and lines dated 1948 or
2612 are counted by `doctor`, listed by `doctor --implausible`, and never changed."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import OSL, TZ, ZRH, dwell, event, flight, point, travel, utc

from logbook import cli
from logbook.contrib import doctor
from logbook.core import events, plausible
from logbook.core.flights import Airlines
from logbook.core.store import Logbook

DAY = "2026-09-14"  # a Monday
HOME = (59.9139, 10.7522)
GATE_A = (OSL[0] + 0.0080, OSL[1] - 0.0060)  # the long-term car park, ~1 km from the reference point
GATE_B = (OSL[0] - 0.0060, OSL[1] + 0.0040)  # the terminal kerb, ~1.6 km further by road
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def _drafts() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    out += dwell(DAY, "05:00", "06:00", HOME, seed=1)
    out += travel(DAY, "06:00", "06:50", HOME, GATE_A, steps=10)
    out += dwell(DAY, "06:50", "07:20", GATE_A, seed=2)
    # the drive round the airport: 1.6 km in five minutes, with points on the way
    out += travel(DAY, "07:20", "07:25", GATE_A, GATE_B, steps=4)
    out += dwell(DAY, "07:25", "08:30", GATE_B, seed=3)
    # the flight: no points between the gate and Zürich
    out += dwell(DAY, "11:30", "13:00", ZRH, seed=4)
    out.append(flight(DAY, "561", "OSL", "ZRH", utc(DAY, "08:45"), utc(DAY, "11:15")))
    # the same check-in, from the phone's calendar and from the Google calendar (source `ics`, the
    # calendar named Work), 20 seconds apart, the Google one with a location and notes
    out.append(event(utc(DAY, "07:40"), utc(DAY, "08:00"), "Check-in XY 561"))
    gcal = event(
        utc(DAY, "07:40").replace(":00Z", ":20Z"),
        utc(DAY, "08:00").replace(":00Z", ":20Z"),
        "check-in  xy 561",
        location={"name": "Gardermoen, terminal"},
        notes="bag drop row C",
        calendar={"id": "Work", "name": "Work"},
    )
    gcal["source"] = "ics"
    gcal["payload"]["raw_id"] = "uid-checkin@20260901T000000Z"
    out.append(gcal)
    return out


def _odd() -> list[dict[str, Any]]:
    """A calendar entry a parser placed in 1948 and a mail a broken clock dated 2612."""
    return [
        {
            "at": "1948-03-01T09:00:00Z",
            "end": "1948-03-01T10:00:00Z",
            "source": "ics",
            "kind": "event",
            "tier": 1,
            "payload": {"schema": "event/v1", "raw_id": "uid-1948@x", "title": "Standup", "all_day": False},
        },
        {
            "at": "2612-03-01T09:00:00Z",
            "source": "mail",
            "kind": "mail",
            "tier": 2,
            "payload": {
                "schema": "mail/v1",
                "raw_id": "<odd-clock@example.org>",
                "subject": "Invoice",
                "from": {"kind": "email", "value": "billing@example.org"},
            },
        },
    ]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    record = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    record.append_many(_drafts())
    return record


def _day(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["day", DAY, *args])
    return capsys.readouterr().out


# -- calendar doubles ---------------------------------------------------------------------------------


def test_the_same_event_from_two_calendars_shows_once_naming_both(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(_day(capsys, "--json"))
    shown = [e for entry in data["timeline"] if entry.get("attached") for e in entry["attached"]["events"]]
    shown += [u for u in data["unplaced"] if u.get("kind") == "event"]
    [checkin] = shown
    assert checkin["title"] == "check-in  xy 561", "the richer line stands: it has a location and notes"
    assert checkin["sources"] == ["ics", "ios-calendar"]
    assert len(checkin["lines"]) == 2
    text = _day(capsys)
    assert text.lower().count("check-in") == 1
    assert "×2 sources (ics, ios-calendar)" in text
    sources = {s["source"]: s["lines"] for s in data["sources"]}
    assert sources["ics"] == 1 and sources["ios-calendar"] == 1, "both lines are still there"


def _line(id_: str, at: str, end: str | None, title: str, source: str, **payload: Any) -> dict[str, Any]:
    return {
        "id": id_,
        "at": at,
        "end": end,
        "source": source,
        "kind": "event",
        "payload": {"schema": "event/v1", "title": title, **payload},
    }


def test_fold_sameness_start_within_a_minute_equal_duration_or_all_day() -> None:
    airlines = Airlines.load()
    lines = [
        _line("a", "2026-09-14T08:00:00Z", "2026-09-14T09:00:00Z", "Review", "ios-calendar"),
        _line("b", "2026-09-14T08:00:45Z", "2026-09-14T09:00:45Z", "review", "ics"),  # same
        _line("c", "2026-09-14T10:00:00Z", "2026-09-14T11:00:00Z", "Lunch", "ios-calendar"),
        _line("d", "2026-09-14T10:00:30Z", "2026-09-14T11:30:30Z", "Lunch", "ics"),  # longer: apart
        _line(
            "e",
            "2026-09-13T22:00:00Z",
            "2026-09-14T22:00:00Z",
            "Ola's birthday",
            "ios-calendar",
            all_day=True,
        ),
        _line("f", "2026-09-13T22:00:00Z", "2026-09-14T21:59:59Z", "ola's birthday", "ics", all_day=True),
        _line("g", "2026-09-14T12:00:00Z", "2026-09-14T13:00:00Z", "Standup", "ics", calendar={"id": "Work"}),
        _line("h", "2026-09-14T12:00:00Z", "2026-09-14T13:00:00Z", "Standup", "ics", calendar={"id": "Team"}),
    ]
    kept, folded = events.fold(lines, airlines)
    assert [line["id"] for line in kept] == ["a", "c", "d", "e", "g"]
    assert folded["a"].lines == ["a", "b"] and folded["a"].sources == ["ios-calendar", "ics"]
    assert folded["e"].lines == ["e", "f"], "both all-day: the durations need not match"
    assert folded["g"].sources == ["ics (Work)", "ics (Team)"], "one source, two calendars"


def test_a_timed_entry_stands_over_an_all_day_one_at_the_same_start() -> None:
    lines = [
        _line("a", "2026-09-13T22:00:00Z", "2026-09-14T22:00:00Z", "Offsite", "ics", all_day=True),
        _line("b", "2026-09-13T22:00:00Z", "2026-09-14T06:00:00Z", "Offsite", "ios-calendar"),
    ]
    kept, folded = events.fold(lines, Airlines.load())
    assert [line["id"] for line in kept] == ["b"]
    assert folded["b"].sources == ["ios-calendar", "ics"]


# -- airport pairs ------------------------------------------------------------------------------------


def test_an_airport_pair_on_the_flight_and_none_on_the_car_move_near_the_airport(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = json.loads(_day(capsys, "--json"))
    moves = [e for e in data["timeline"] if e["kind"] == "move"]
    [drive] = [m for m in moves if m["mode"] == "car" and (m["distance_m"] or 0) < 3000]
    assert drive["airports"] == [], "a 1.6 km drive round Gardermoen is no flight"
    [hop] = [m for m in moves if m["mode"] == "flight"]
    assert hop["airports"] == ["OSL", "ZRH"]
    text = _day(capsys)
    assert "OSL → OSL" not in text
    assert text.count("OSL → ZRH") == 2, "the flight row and the move it covers"


def test_a_slow_move_a_flight_line_covers_names_the_flights_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A tracker that logged one point at the gate after boarding: the move's own speed is not a
    flight's, but the flight line covers it, so it names the flight's departure and arrival."""
    record = Logbook.init(tmp_path / "slow", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    drafts = dwell(DAY, "06:00", "07:00", GATE_B, seed=5)
    drafts.append(point(utc(DAY, "07:30"), (GATE_B[0] + 0.01, GATE_B[1])))
    drafts += dwell(DAY, "20:00", "21:00", ZRH, seed=6)
    drafts.append(flight(DAY, "561", "OSL", "ZRH", utc(DAY, "07:40"), utc(DAY, "10:10")))
    record.append_many(drafts)
    data = json.loads(_day(capsys, "--json"))
    covered = [e for e in data["timeline"] if e["kind"] == "move" and e["flights"]]
    assert covered and all(m["airports"] == ["OSL", "ZRH"] for m in covered)


# -- implausible dates --------------------------------------------------------------------------------


def _dates(lb: Logbook) -> doctor.Check:
    [check] = [c for c in doctor.run(lb, {}, installed=lambda _m: True, now=NOW) if c.name == "dates"]
    return check


def test_doctor_passes_a_record_with_plausible_dates(lb: Logbook) -> None:
    assert _dates(lb).status == "pass"


@pytest.mark.parametrize("indexed", [False, True])
def test_doctor_warns_on_lines_dated_1948_and_2612_with_counts(lb: Logbook, indexed: bool) -> None:
    lb.append_many(_odd())
    if indexed:
        lb.index_rebuild()
    before = [p.read_bytes() for p in lb.files()]
    check = _dates(lb)
    assert check.status == "warn"
    assert "2 line(s)" in check.detail
    assert "ics 1 (1948-03-01 to 1948-03-01)" in check.detail
    assert "mail 1 (2612-03-01 to 2612-03-01)" in check.detail
    assert [p.read_bytes() for p in lb.files()] == before, "nothing is changed"


def test_doctor_implausible_lists_the_line_ids(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    lb.append_many(_odd())
    ids = {str(line["id"]) for line in lb.lines() if str(line["at"])[:4] in {"1948", "2612"}}
    assert len(ids) == 2
    cli.main(["doctor", "--implausible"])
    out = capsys.readouterr().out.splitlines()
    assert {row.split()[0] for row in out[:-1]} == ids
    assert out[-1].startswith("2 line(s) outside")
    assert any("plausible 1970-01-01 to 20" in row and " event " in row for row in out)


def test_the_range_is_overridable_per_source(lb: Logbook) -> None:
    lb.append_many(_odd())
    path = plausible.path_of(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"sources": {"ics": {"earliest": "1940-01-01"}}}), encoding="utf-8")
    check = _dates(lb)
    assert check.status == "warn" and "1 line(s)" in check.detail and "ics" not in check.detail.split(":")[1]
    path.write_text(json.dumps({"sources": {"ics": {"ahead": "soon"}}}), encoding="utf-8")
    assert _dates(lb).status == "fail"


def test_the_default_ranges() -> None:
    assert plausible.window("event", "ics", {}).text(NOW) == "1970-01-01 to 2031-10-12"
    assert plausible.window("mail", "mail", {}).text(NOW) == "1990-01-01 to 2026-10-13"
    assert plausible.window("location", "dawarich", {}).text(NOW) == "1970-01-01 to 2026-10-13"
