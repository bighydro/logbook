"""The Journeys reader (`logbook.contrib.journeys`) and the captain's name for a journey, `logbook add
--trip ID "NAME"`: the trips of a year, most recent first, with their photos, their canonical people,
their name and the standing draft of each; one journey with its days, its stays' lines and the
promises made on it. On the four synthetic years (`library_record.py`); nobody here exists."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from four_years import OBSERVED
from library_record import BERGEN_WINTER, PHOTO_A, PHOTO_B, PHOTO_HOME, PROMISE, library_record

from logbook import cli
from logbook.contrib import journeys
from logbook.core import drafts
from logbook.core.store import Logbook


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    root = tmp_path_factory.mktemp("journeys") / "lb"
    library_record(root)
    yield root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _names(lb: Logbook) -> list[dict[str, Any]]:
    return [line for line in Logbook(lb.root).lines() if "name" in (line["payload"].get("labels") or [])]


def test_a_year_s_journeys_most_recent_first_each_as_its_page_finds_it(lb: Logbook) -> None:
    shelf = journeys.shelf(lb, "2022")
    ids = [j.id for j in shelf.journeys]
    assert ids == ["trip:2022-11-03:2023-07-31", BERGEN_WINTER], "begun in 2022, the latest first"
    assert shelf.years == ["2022", "2023", "2024", "2025"]
    for j in shelf.journeys:
        assert journeys.read(lb, j.id)["id"] == j.id, "the id the list links is the one the page finds"
    over_new_year = shelf.journeys[0]
    assert over_new_year.trip.until == "2023-08-01", "read past the year's end: listed once, whole"
    assert journeys.shelf(lb, "2023").journeys == [], "and not again under the year it ended"
    assert journeys.shelf(lb).year == "2025", "no year: the record's last"
    with pytest.raises(ValueError, match="not a year"):
        journeys.shelf(lb, "20x2")


def test_a_journey_carries_its_photos_its_canonical_people_and_its_nights_lines(lb: Logbook) -> None:
    bergen = journeys.shelf(lb, "2022").journeys[1]
    assert bergen.photos == [PHOTO_A, PHOTO_B], "the photos of its days; the one at home in June is not"
    assert PHOTO_HOME not in bergen.photos
    names = [p["name"] for p in bergen.people]
    assert "Astrid Bakke" in names and "Ingrid Aas" in names
    assert OBSERVED["name"] not in names and bergen.unplaced == 1, "the observed attendee is counted only"
    assert all(p["lines"] for p in bergen.people), "each person with the lines that put them there"
    first = bergen.nights_of[0]
    assert first["day"] == "2022-01-03" and first["stay"] and len(first["lines"]) == 2
    assert bergen.trip.nights == len(bergen.nights_of)


def test_the_journey_s_draft_is_its_standing_draft_checked_against_its_days(lb: Logbook) -> None:
    draft = journeys.shelf(lb, "2022").journeys[1].draft
    assert draft is not None and draft["source"] == "model:qwen2.5-7b-instruct"
    supported, unsupported, elsewhere = draft["segments"]
    assert supported["supported"] and supported["evidence"] == [PHOTO_A, PHOTO_B]
    assert not unsupported["supported"] and unsupported["why"] is None
    assert not elsewhere["supported"] and elsewhere["why"] == drafts.NOT_ON_JOURNEY, "a June line at home"
    assert journeys.shelf(lb, "2022").journeys[0].draft is None, "a journey nobody drafted has none"


def test_one_journey_is_the_trip_with_its_stays_lines_its_days_and_the_promises_made_on_it(
    lb: Logbook,
) -> None:
    data = journeys.read(lb, BERGEN_WINTER)
    assert data["journey"]["photos"]["count"] == 2
    located = [s for s in data["route"] if s["stay"]]
    assert located and all(s["lines"] for s in located), "every stay slept at says which lines it rests on"
    assert data["days"][0]["day"] == "2022-01-03" and data["days"][0]["night_lines"]
    assert data["days"][-1]["day"] == "2022-04-01", "to the return day"
    [promise] = data["promises"]
    assert promise["quote"] == PROMISE and promise["day"] == "2022-01-10" and promise["line"]
    assert promise["role"] == "promise" and promise["status"] == "open"
    with pytest.raises(ValueError, match="no trip"):
        journeys.read(lb, "2025-06-01")


# -- the name ------------------------------------------------------------------------------------------------


def test_add_trip_names_a_journey_with_one_note_dated_inside_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = Logbook(lb.root).meta["seq"]
    cli.main(["add", "--trip", "2022-02-01", "The", "Bergen", "winter"])
    out = capsys.readouterr().out
    assert f"named {BERGEN_WINTER}: The Bergen winter" in out
    [line] = _names(lb)
    assert line["seq"] == seq + 1 and line["source"] == "manual" and line["kind"] == "note"
    assert line["tier"] == 2
    assert line["payload"] == {
        "schema": "note/v1",
        "text": "The Bergen winter",
        "labels": ["name"],
        "extra": {"trip": BERGEN_WINTER},
    }
    assert line["at"] == "2022-03-31T21:59:00Z", "the last minute of its last day away, in Oslo"
    named = journeys.shelf(Logbook(lb.root), "2022").journeys[1].name
    assert named is not None and named.text == "The Bergen winter" and named.line == line["id"]
    assert journeys.read(Logbook(lb.root), BERGEN_WINTER)["journey"]["name"]["text"] == "The Bergen winter"


def test_the_latest_name_stands_and_one_names_a_journey_whose_bounds_moved(lb: Logbook) -> None:
    journeys.name(lb, BERGEN_WINTER, "Bergen")
    journeys.name(lb, BERGEN_WINTER, "  The   Bergen winter ")
    rows = journeys.shelf(Logbook(lb.root), "2022").journeys
    assert rows[1].name is not None and rows[1].name.text == "The Bergen winter", "whitespace folded"
    other = rows[0]
    assert other.name is None, "a name is its journey's alone"
    moved = {
        "at": "2023-02-01T12:00:00Z",
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {
            "schema": "note/v1",
            "text": "Trondheim",
            "labels": ["name"],
            "extra": {"trip": "trip:2022-11-10:2023-07-31"},
        },
    }
    Logbook(lb.root).append_many([moved])
    found = journeys.shelf(Logbook(lb.root), "2022").journeys[0].name
    assert found is not None and found.text == "Trondheim", "dated on one of its days: still its name"
    prose = {
        **moved,
        "at": "2023-02-02T12:00:00Z",
        "payload": {"schema": "note/v1", "text": "Trondheim, really"},
    }
    Logbook(lb.root).append_many([prose])
    later = journeys.shelf(Logbook(lb.root), "2022").journeys[0].name
    assert later is not None and later.text == "Trondheim", "a note without the label is never a name"


def test_a_name_is_words_on_a_journey_that_is_there(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(journeys.JourneyError, match="words"):
        journeys.name(lb, BERGEN_WINTER, "   ")
    for args in (
        ["add", "--trip", "2025-06-01", "Home"],
        ["add", "--trip", "trip:2022-01-04:2022-03-31", "Bergen"],
        ["add", "--trip", BERGEN_WINTER, "--at", "2022-02-01T10:00:00Z", "Bergen"],
        ["add", "--trip", BERGEN_WINTER, "--dry-run", "Bergen"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2, args
    err = capsys.readouterr().err
    assert "the night was at home" in err and f"the trip on 2022-01-04 is {BERGEN_WINTER}" in err
    assert _names(lb) == []
