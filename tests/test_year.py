"""`logbook year YYYY [--html PATH] [--json]`: a year read back — the rollups, the trips, the
places, the people, the health and the keepers per month, and twelve picks, one day a month,
rendered with the day reader. Composed from one reading of the year; nothing is written. The
synthetic demo record (365 days) and the Oslo persona, who does not exist."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from persona import TZ, note, persona_record, utc

from logbook import cli, reading, rollup, year
from logbook import day as day_reader
from logbook import trips as trips_reader
from logbook.store import Logbook

ARROW = "\u2192"
EN_DASH = "\u2013"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> Any:
    return json.loads(_run(capsys, *args, "--json"))


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    """A year of the demo record (365 days from 1 June 2026, seed 7), generated once for the
    readers' tests of this module; nothing in it is real."""
    root = tmp_path_factory.mktemp("demo") / "Demo"
    cli.main(["demo", "--days", "365", "--seed", "7", "--out", str(root)])
    return Logbook(root)


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


@pytest.fixture(scope="module")
def found(record: Logbook) -> dict[str, Any]:
    """The Year of 2026, read once for the module (a reading of 214 days and the trips take seconds),
    as the JSON the command prints."""
    data: dict[str, Any] = json.loads(json.dumps(year.read(record, "2026"), ensure_ascii=False))
    return data


# -- the year is the rollups, the trips and twelve picks ---------------------------------------------------


def test_the_year_composes_the_readers_and_writes_nothing(lb: Logbook, found: dict[str, Any]) -> None:
    """Every section says what the reader it names says for 2026, from one reading of the window."""
    head = lb.meta["head"]
    data = found
    assert data["year"] == "2026"
    window = {"since": "2026-06-01", "until": "2026-12-31", "days": 214}
    assert data["window"] == window, "clipped to the track"
    assert data["head"] == head

    rd = reading.read(lb, "2026-06-01", "2026-12-31")
    countries = rollup.countries(rd)["years"][0]
    assert data["countries"]["countries"] == [
        {"country": c["country"], "days": c["days"]} for c in countries["countries"]
    ]
    assert data["countries"]["in_transit"] == countries["in_transit"]["days"]
    assert data["countries"]["unknown"] == countries["unknown"]["days"]

    nights = rollup.nights(rd)["years"][0]
    assert data["nights"] == {
        "home": nights["home"],
        "away": nights["away"],
        "in_transit": nights["in_transit"],
        "aboard": [{"asset": "nordlys", "name": "Nordlys", "nights": nights["aboard"]["nordlys"]}],
    }
    assert data["nights"]["home"] + data["nights"]["away"] + data["nights"]["in_transit"] == 214

    trips = [t.to_json() for t in trips_reader.trips(rd)[0]]
    assert [t["id"] for t in data["trips"]] == [t["id"] for t in trips], "every trip, in order"
    assert len(trips) > 10
    for found, trip in zip(data["trips"], trips, strict=True):
        assert found["nights"] == trip["nights"] and found["route"] == trip["route"]
        assert found["people"] == [p["name"] for p in trip["people"]]
        assert found["asset"] == trip["asset"]
        assert [f["number"] for f in found["flights_in"]] == [f["number"] for f in trip["flights_in"]]

    flights = rollup.flights(rd)["years"][0]
    assert data["flights"]["count"] == flights["count"] == len(data["flights"]["flights"])
    assert data["flights"]["km"] == flights["km"] > 10_000
    assert data["flights"]["by_evidence"] == flights["by_evidence"]

    places = rollup.places(rd)["years"][0]
    by_nights = [p["nights"] for p in data["places"]["places"]]
    assert by_nights == sorted(by_nights, reverse=True), "places by nights"
    assert {p["place"] for p in data["places"]["places"]} == {p["place"] for p in places["places"]}
    assert data["places"]["places"][0]["place"] == "Home"
    assert [a["asset"] for a in data["places"]["assets"]] == ["nordlys"]
    unnamed = [p["nights"] for p in data["places"]["unnamed"]]
    assert unnamed == sorted(unnamed, reverse=True) and len(unnamed) == len(places["unnamed"])
    assert all(p["label"] and p["id"] for p in data["places"]["unnamed"])

    people = rollup.people(rd)["years"][0]
    assert [(p["name"], p["days"]) for p in data["people"]] == [
        (p["name"], p["days"]) for p in people["people"]
    ]
    assert data["people"][0]["days"] >= data["people"][-1]["days"] > 0

    with lb.index() as idx:
        health_lines = [*idx.by_kind("health", "2026-05-31", "2026-12-31"), *idx.retractions()]
    health = rollup.health(health_lines, TZ, "2026-06-01", "2026-12-31", "month")["periods"]
    assert [m["month"] for m in data["health"]] == [f"2026-{m:02d}" for m in range(6, 13)]
    for found, period in zip(data["health"], health, strict=True):
        assert found["sleep"] == period["sleep"] and found["steps"] == period["steps"]
        assert found["resting_hr"] == period["resting_hr"] and found["hrv"] == period["hrv"]

    keepers = [line for line in lb.lines() if line["kind"] == "keeper" and line["at"].startswith("2026")]
    assert [m["month"] for m in data["keepers"]] == [f"2026-{m:02d}" for m in range(6, 13)]
    assert sum(m["count"] for m in data["keepers"]) == len(keepers) > 0
    assert all(m["count"] == m["memory"] + m["art"] for m in data["keepers"])

    assert lb.meta["head"] == head, "the year writes nothing"


def test_twelve_picks_one_day_each_rendered_with_the_day_reader(
    lb: Logbook, found: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    data = found
    assert _json(capsys, "year", "2026") == data, "the command prints the Year"
    picks = data["picks"]
    assert [p["month"] for p in picks] == [f"2026-{m:02d}" for m in range(1, 13)]
    before = [(p["day"], p["evidence"], p["page"]) for p in picks[:5]]
    assert before == [(None, None, None)] * 5, "months before the record have no day"
    for p in picks[5:]:
        assert p["day"] and p["day"].startswith(p["month"]), p["month"]
        assert p["evidence"]["score"] == (
            p["evidence"]["attachments"]
            + p["evidence"]["people"]
            + int(p["evidence"]["flight"] or p["evidence"]["new_place"])
        )
        assert p["evidence"]["score"] > 0
        assert p["page"]["day"] == p["day"], "the Day of the pick, as `logbook day` reads it"
        assert p["page"]["timeline"] and p["page"]["sources"]
    june = picks[5]
    assert june["page"] == day_reader.read(lb, june["day"]), "the same Day, line ids and all"

    text = "\n".join(year.rows(data)) + "\n"
    assert text.startswith(f"2026  2026-06-01 {EN_DASH} 2026-12-31 · 214 days")
    for label in ("countries", "nights", "trips", "flights", "places", "people", "health", "keepers"):
        assert re.search(rf"^  {label}\b", text, re.MULTILINE), label
    assert "one day each" in text
    assert "  January       no days" in text
    for p in picks[5:]:
        assert f"{p['day']}  {p['page']['weekday']}" in text, "the Day's own header row"
        assert "night before" in text and "night after" in text
    assert "XY 561" in text and "OSL" in text and f"OSL {ARROW} ZRH" in text
    assert "Nordlys" in text and "Marta Keller" in text


# -- the month-pick rule -------------------------------------------------------------------------------------


def test_evidence_is_attachments_people_and_a_flight_or_a_new_place() -> None:
    page = {
        "timeline": [
            {
                "kind": "stay",
                "attached": _attached(events=2, photos=3),
                "with": {"confirmed": [_c("a"), _c("b")]},
            },
            {"kind": "move", "attached": _attached(messages=1), "with": {"confirmed": []}},
            {"kind": "stay", "attached": _attached(), "with": {"confirmed": [_c("a")]}},
            {"kind": "flight"},
        ],
        "flights": [{"line": "x"}],
        "sources": [{"source": "dawarich", "lines": 40}],
    }
    found = year.evidence(page, new_place=False)
    assert found == {
        "attachments": 6,
        "people": 2,
        "flight": True,
        "new_place": False,
        "lines": 40,
        "score": 9,
    }
    grounded = {**page, "flights": []}
    assert year.evidence(grounded, new_place=True)["score"] == 9, "a flight or a new place is one"
    assert year.evidence(grounded, new_place=False)["score"] == 8


def test_the_pick_is_the_most_evidence_then_the_most_lines_then_the_earlier_day() -> None:
    def row(day: str, score: int, lines: int) -> tuple[str, dict[str, Any]]:
        return day, {"score": score, "lines": lines}

    assert (
        year.pick([row("2026-06-02", 3, 10), row("2026-06-01", 5, 1), row("2026-06-03", 5, 1)])
        == "2026-06-01"
    )
    assert year.pick([row("2026-06-02", 3, 10), row("2026-06-01", 3, 2)]) == "2026-06-02", "more lines"
    assert year.pick([row("2026-06-02", 0, 10), row("2026-06-01", 0, 10)]) == "2026-06-01", "the earlier day"
    assert year.pick([row("2026-06-02", 0, 0)]) is None, "a day with no lines is no pick"
    assert year.pick([]) is None


def test_the_persona_fortnight_picks_the_saturday_aboard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """June of the persona: Wednesday's lunch (an event and a photo, Kari confirmed, the cafe a new
    place: 4) ties with the Saturday aboard (a note and a photo, Ola confirmed, the marina and the
    anchorage new: 4); the Saturday has the boat's track too, so it has more lines and is the pick.
    Monday's flight to Zürich is one (the calendar entry attached to the move, the flight) and a
    new place is not a second one. The new places are the office on the first day, the cafe, the
    marina and the fjord, the airports and the hotel; never home."""
    lb = persona_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = year.read(lb, "2026")
    assert data["window"] == {"since": "2026-06-08", "until": "2026-06-21", "days": 14}
    picks = {p["month"]: p for p in data["picks"]}
    assert [m for m, p in picks.items() if p["day"]] == ["2026-06"]
    june = picks["2026-06"]
    assert june["day"] == "2026-06-13"
    assert june["evidence"] == {
        "attachments": 2,
        "people": 1,
        "flight": False,
        "new_place": True,
        "lines": june["evidence"]["lines"],
        "score": 4,
    }
    assert june["page"] == day_reader.read(lb, "2026-06-13")
    scored = data["scored"]
    assert scored["2026-06-10"]["score"] == 4 and scored["2026-06-10"]["lines"] < june["evidence"]["lines"]
    assert scored["2026-06-15"] == {
        **scored["2026-06-15"],
        "attachments": 1,
        "people": 0,
        "flight": True,
        "score": 2,
    }
    assert scored["2026-06-16"]["score"] == 3, "dinner with Ola and a photo"
    assert scored["2026-06-09"]["score"] == 0, "an office day"
    assert [d for d, e in scored.items() if e["new_place"]] == [
        "2026-06-08",
        "2026-06-10",
        "2026-06-13",
        "2026-06-15",
    ]
    assert lb.meta["head"] == head


# -- the page ----------------------------------------------------------------------------------------------


def test_html_is_one_self_contained_page(found: dict[str, Any]) -> None:
    page = year.html(found)
    assert page.startswith("<!doctype html>")
    assert "<style>" in page and "<script" not in page
    assert not re.search(r"\b(src|href)\s*=", page), "no external asset, no link out"
    assert "http://" not in page and "https://" not in page
    assert "@media print" in page
    assert "<title>2026 · Logbook</title>" in page
    for heading in (
        "Days per country",
        "Trips",
        "Flights",
        "Places, by nights",
        "People",
        "Health, by month",
        "Keepers",
        "One day each",
    ):
        assert f">{heading}<" in page, heading
    assert "Nordlys" in page and "Marta Keller" in page and "OSL" in page
    assert page.count('<article class="pick"') == 12
    assert "night before" in page and "<pre>" in page, "the picks are the day reader's rows"
    assert "&lt;" not in page.split("<pre>")[0], "nothing in the tables is a tag"


def test_html_is_written_where_asked_and_escapes_what_the_record_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many([note(utc("2026-06-13", "19:30"), "<b>bold</b> & done")])
    head = lb.meta["head"]
    out = tmp_path / "pages" / "2026.html"
    text = _run(capsys, "year", "2026", "--html", str(out))
    assert text == f"year 2026: wrote {out}\n"
    page = out.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and page == year.html(year.read(lb, "2026"))
    assert "<b>bold</b>" not in page and "&lt;b&gt;bold&lt;/b&gt; &amp; done" in page
    assert lb.meta["head"] == head, "the page writes nothing to the record"


# -- the edges ---------------------------------------------------------------------------------------------


def test_a_year_outside_the_record_and_an_empty_record_say_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    persona_record(tmp_path, monkeypatch)
    assert _run(capsys, "year", "2025") == "year 2025: the record has no days in it\n"
    data = _json(capsys, "year", "2025")
    assert data["window"] is None and data["trips"] == [] and data["people"] == []
    assert [p["day"] for p in data["picks"]] == [None] * 12
    out = tmp_path / "2025.html"
    _run(capsys, "year", "2025", "--html", str(out))
    assert "no days" in out.read_text(encoding="utf-8")
    for bad in ("20x6", "2026-06", "26"):
        with pytest.raises(SystemExit) as e:
            cli.main(["year", bad])
        assert e.value.code == 2 and "not a year" in capsys.readouterr().err
    empty = Logbook.init(tmp_path / "empty", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    assert _run(capsys, "year", "2026") == "year 2026: the record has no days in it\n"


def test_the_decision_is_written_down() -> None:
    doc = Path(__file__).parent.parent / "docs" / "year.md"
    text = doc.read_text(encoding="utf-8")
    assert "one day each" in text and "most evidence" in text and "--html" in text


# -- helpers -----------------------------------------------------------------------------------------------


def _attached(events: int = 0, photos: int = 0, messages: int = 0) -> dict[str, Any]:
    return {
        "events": [{}] * events,
        "transcripts": [],
        "notes": [],
        "mail": [],
        "calls": [],
        "messages": {"count": messages, "lines": []},
        "photos": {"count": photos, "lines": []},
        "keepers": [],
    }


def _c(person: str) -> dict[str, Any]:
    return {"person": person, "name": person.upper()}
