"""A flight line that does not carry both ends never breaks the Day: a flight with no `end` counts as
ending at its start, one with no start is skipped. The Library's Day page reads the day 1, 2, 3, 5
and 10 years back (`day_rhythm.looking_back`), so such a flight on any of those days must read too;
the page and `/today` stay 200. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, OSL, ZRH, ZURICH, dwell, flight, persona_record, travel, utc

from logbook.contrib import day_rhythm, serve
from logbook.core import day as day_reader
from logbook.core import flights as flight_lines
from logbook.core import reading
from logbook.core.store import Logbook

DAY = "2026-06-15"  # the persona flies to Zürich: the page's own day has a move and a flight
NO_END = "2025-06-15"  # 1 year back: a flight the record holds without its arrival
NO_START = "2024-06-15"  # 2 years back: a flight whose departure does not read
HOME_DAYS = ("2023-06-15", "2021-06-15", "2016-06-15")  # 3, 5 and 10 years back: a day at home


def _flight_day(day: str, number: str) -> list[dict[str, Any]]:
    """Home to Gardermoen, the tracker silent in the air, Zürich airport to the hotel; and the flight
    line, its arrival unknown (no `end`, no `actual_arrival`)."""
    line = flight(day, number, "OSL", "ZRH", utc(day, "07:05"), utc(day, "09:15"))
    del line["end"], line["payload"]["actual_arrival"]
    return [
        *dwell(day, "00:00", "05:00", HOME, every_min=10),
        *travel(day, "05:00", "05:40", HOME, OSL, steps=4),
        *dwell(day, "05:40", "07:00", OSL, every_min=5),
        *dwell(day, "09:20", "10:00", ZRH, every_min=5),
        *travel(day, "10:00", "10:30", ZRH, ZURICH, steps=3),
        *dwell(day, "10:30", "24:00", ZURICH, every_min=10),
        line,
    ]


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = persona_record(tmp_path, monkeypatch)
    drafts = _flight_day(NO_END, "771") + _flight_day(NO_START, "772")
    for day in HOME_DAYS:
        drafts += dwell(day, "00:00", "24:00", HOME, every_min=30)
    lb.append_many(drafts)
    real = flight_lines.standing

    def departure_unread(lines: Any) -> Any:  # the envelope requires `at`: a reader may still not read it
        out = real(lines)
        for k, line in out.items():
            if line["payload"]["number"] == "772":
                out[k] = {**line, "at": None}
        return out

    monkeypatch.setattr(flight_lines, "standing", departure_unread)
    return lb


def _move_on(lb: Logbook, day: str) -> dict[str, Any]:
    """The Day of `day` as looking back reads it, and its move from Gardermoen to Zürich airport."""
    data = day_reader.of_reading(reading.read(lb, day, day, serve.Airports.load(), None), day, None)
    [move] = [
        e
        for e in data["timeline"]
        if e["kind"] == "move" and e["start"] < utc(day, "09:20") and e["end"] > utc(day, "07:00")
    ]
    return {"data": data, "move": move}


def test_a_flight_without_an_end_ends_at_its_start(lb: Logbook) -> None:
    found = _move_on(lb, NO_END)
    [shown] = found["data"]["flights"]
    assert shown["end"] is None and shown["start"] == utc(NO_END, "07:05")
    assert found["move"]["flights"] == [shown["id"]], "its departure is inside the move"


def test_a_flight_without_a_start_is_skipped(lb: Logbook) -> None:
    found = _move_on(lb, NO_START)
    assert found["data"]["flights"] == []
    assert found["move"]["flights"] == []


def test_the_move_skips_a_flight_dict_without_a_start_and_ends_one_without_an_end_at_its_start() -> None:
    start, end = datetime(2025, 6, 15, 5, 0, tzinfo=UTC), datetime(2025, 6, 15, 7, 20, tzinfo=UTC)
    flights = [
        {"id": "a", "start": None, "end": "2025-06-15T06:00:00Z", "from": "OSL", "to": "ZRH"},
        {"id": "b", "start": "2025-06-15T05:05:00Z", "end": None, "from": "OSL", "to": "ZRH"},
        {"id": "c", "start": "2025-06-15T04:00:00Z", "end": None, "from": "OSL", "to": "ZRH"},
    ]
    assert [f["id"] for f in day_reader._covering(start, end, flights)] == ["b"], (
        "b departs inside the move; c departed before it and has no end to reach into it"
    )
    assert day_reader._flown(start, end, flights) == [], "no flight with both ends covers it"


def test_looking_back_reads_a_flight_without_an_end_and_one_without_a_start(lb: Logbook) -> None:
    found = day_rhythm.looking_back(lb, DAY, serve.Airports.load(), None)
    assert [b["years"] for b in found] == [1, 2, 3, 5, 10]


def test_the_day_page_and_today_render_with_those_years_back(lb: Logbook) -> None:
    now = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
    site = serve.Site(lb, now=lambda: now)
    today = site.respond("/today", "")
    assert today.status == 302 and today.headers["Location"] == f"/day/{DAY}"
    page = site.respond(today.headers["Location"], "open=1")
    assert page.status == 200, page.body[:300]
    body = page.body.decode("utf-8")
    assert f'href="/day/{NO_END}"' in body and f'href="/day/{NO_START}"' in body
    for day in (NO_END, NO_START):
        assert site.respond(f"/day/{day}", "").status == 200, day
