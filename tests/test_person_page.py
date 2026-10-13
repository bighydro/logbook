"""The People page's reader and one person's page (`logbook.contrib.person_page`): the canonical people
of a year ranked by days together, never an observed one; a person's days together by year, last real
contact and what it was, promises both ways, anniversaries, drift and places, each with its lines. On
the four synthetic years (`library_record.py`); nobody here exists."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from four_years import ASTRID, BJORN, CAMILLA, FRODE, INGRID, JON, KRISTIN, OBSERVED
from library_record import ASTRID_ELSEWHERE, library_record

from logbook.contrib import people_drift, person_page
from logbook.core import people, reading
from logbook.core.store import Logbook

OCTOBER = datetime(2025, 10, 1, 12, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def lb(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Logbook]:
    yield library_record(tmp_path_factory.mktemp("people-page") / "lb")


def test_the_year_s_canonical_people_ranked_by_days_together(lb: Logbook) -> None:
    data = person_page.ranked(lb, now=OCTOBER)
    assert data["year"] == "2025" and data["years"] == ["2022", "2023", "2024", "2025"]
    names = [r["name"] for r in data["people"]]
    assert names[0] == FRODE["name"] and data["people"][0]["days"] == 20
    assert OBSERVED["name"] not in names, "an observed person is never in the list"
    assert names.count(ASTRID["name"]) == 1, "the address seen under her name is not a second Astrid"
    assert all(r["days"] >= s["days"] for r, s in zip(data["people"], data["people"][1:], strict=False))
    frode = data["people"][0]
    assert len(frode["together"]) == 20 and all(d["lines"] for d in frode["together"])
    assert frode["last_real_contact"]["via"] == "together"
    past = person_page.ranked(lb, "2022", now=OCTOBER)
    assert [r["name"] for r in past["people"]][:2] == ["Elin Moe", ASTRID["name"]]
    assert person_page.ranked(lb, now=datetime(2027, 1, 1, tzinfo=UTC))["year"] == "2025", (
        "a record that ended before today: its last year"
    )
    assert person_page.ranked(lb, "1999", now=OCTOBER)["people"] == []
    with pytest.raises(ValueError, match="not a year"):
        person_page.ranked(lb, "19x9")


def test_a_person_s_page_days_by_year_last_real_contact_drift_and_places(lb: Logbook) -> None:
    astrid = person_page.read(lb, ASTRID["id"], now=OCTOBER)
    assert astrid["name"] == ASTRID["name"] and astrid["days"] == 24
    assert [(y["year"], y["days"]) for y in astrid["years"]] == [("2022", 24)]
    assert astrid["drift"]["drifted"] and astrid["drift"]["text"].startswith(
        "drifting: 24 days together in 2022"
    )
    assert astrid["last_real_contact"]["what"].startswith("a day together at 60.3913,5.3221")
    [bergen] = astrid["places"]
    assert bergen["days"] == 24 and len(bergen["on"]) == 24 and bergen["lines"]

    ingrid = person_page.read(lb, INGRID["name"], now=OCTOBER)
    assert ingrid["last_real_contact"]["via"] == "meeting"
    assert ingrid["last_real_contact"]["what"] == "Catch-up (Video call)"
    assert not ingrid["drift"]["drifted"] and "within 365" in ingrid["drift"]["text"]
    camilla = person_page.read(lb, CAMILLA["email"], now=OCTOBER)
    assert camilla["last_real_contact"]["what"] == "a call, incoming, answered, 10 min", (
        "the missed one is not"
    )
    assert person_page.read(lb, JON["name"], now=OCTOBER)["last_real_contact"]["what"] == "spoke in Planning"
    for found in (astrid, ingrid, camilla):
        assert found["last_real_contact"]["line"]


def test_the_drift_on_a_page_is_the_command_s(lb: Logbook) -> None:
    drifted = people_drift.drift(lb)
    assert drifted is not None
    listed = {d.person.entity for d in drifted.people}
    whole = reading.record_days(lb)
    assert whole is not None
    report = people.read(lb, *whole)
    for p in report.people:
        assert person_page.read(lb, p.entity, now=OCTOBER)["drift"]["drifted"] == (p.entity in listed), p.name


def test_promises_both_ways_never_a_word_of_a_message_elsewhere(lb: Logbook) -> None:
    bjorn = person_page.read(lb, BJORN["name"], now=OCTOBER)
    [mine] = bjorn["promises"]["you_owe"]
    [theirs] = bjorn["promises"]["they_owe"]
    assert mine["quote"] == "I'll send you the photos by Friday." and mine["due"] == "2024-03-15"
    assert theirs["quote"] == "I will bring the charts next time."
    assert mine["line"] and theirs["line"]
    assert bjorn["last_real_contact"]["what"] == "a message from them in a direct chat (whatsapp)"
    assert "charts" not in bjorn["last_real_contact"]["what"]


def test_anniversaries_in_the_coming_month(lb: Logbook) -> None:
    kristin = person_page.read(lb, KRISTIN["name"], now=OCTOBER)
    [year_ago] = kristin["anniversaries"]
    assert (year_ago["on"], year_ago["years"], year_ago["day"]) == ("2025-10-14", 1, "2024-10-14")
    assert year_ago["lines"]
    later = person_page.read(lb, KRISTIN["name"], now=datetime(2025, 10, 20, tzinfo=UTC))
    assert [a["on"] for a in later["anniversaries"]] == ["2025-11-03"]


def test_a_page_is_never_an_observed_person_s_or_the_owner_s(lb: Logbook) -> None:
    with pytest.raises(people.PersonError):
        person_page.read(lb, OBSERVED["name"], now=OCTOBER)
    with pytest.raises(people.PersonError):
        person_page.read(lb, ASTRID_ELSEWHERE["email"], now=OCTOBER)
    with pytest.raises(people.PersonError, match="owner"):
        person_page.read(lb, "Ines Nordmann", now=OCTOBER)


def test_an_empty_record_has_no_people(tmp_path: Path) -> None:
    empty = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert person_page.ranked(empty)["people"] == []
    with pytest.raises(ValueError, match="no days"):
        person_page.read(empty, "anyone")
