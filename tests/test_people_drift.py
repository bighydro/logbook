"""`logbook people drift`, `logbook people nearby` and the Day's anniversaries, over four synthetic
years (`four_years.py`): 25 canonical people, days together in Oslo, Bergen and Trondheim, messages
direct and in a group, calls answered and missed, mail, a meeting by video, a transcript, and one
observed person the record never named, who must never appear. Nothing is written."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from four_years import (
    A_DAYS,
    ASTRID,
    BJORN,
    BY_NAME,
    CAMILLA,
    DAG,
    ELIN,
    F_DAYS,
    FRODE,
    GURO,
    HANS,
    INGRID,
    JON,
    KRISTIN,
    NAMES,
    OBSERVED,
    four_years_record,
)

from logbook import cli
from logbook.core.store import Logbook


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Logbook]:
    yield four_years_record(tmp_path_factory.mktemp("four-years") / "lb")


@pytest.fixture
def lb(record: Logbook, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    return record


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _names(rows: list[dict[str, Any]]) -> list[str]:
    return [r["name"] for r in rows]


def _only_canonical(text: str) -> None:
    assert OBSERVED["name"] not in text and OBSERVED["email"] not in text, (
        "an observed person is never listed"
    )


# -- drift --------------------------------------------------------------------------------------------------


def test_drift_ranks_by_days_together_in_the_best_year_then_by_silence(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    head = lb.meta["head"]
    data = _json(capsys, "people", "drift")
    assert data["until"] == "2025-12-31" and data["min_days"] == 20 and data["quiet_days"] == 365
    assert _names(data["people"]) == [ELIN["name"], ASTRID["name"], DAG["name"], BJORN["name"]], (
        "25, 24, then two of 22: Dag, silent longer, before Bjørn"
    )
    elin, astrid, dag, bjorn = data["people"]
    assert elin["best_year"] == {"year": "2022", "days": 25} and elin["days"] == 25
    assert astrid["best_year"] == {"year": "2022", "days": 24}
    assert dag["best_year"] == {"year": "2023", "days": 22} and bjorn["best_year"] == {
        "year": "2023",
        "days": 22,
    }
    assert (
        bjorn["last_real_contact"]["day"] == "2024-03-10" and bjorn["last_real_contact"]["via"] == "message"
    )
    assert bjorn["silent_days"] == 661
    assert dag["silent_days"] > bjorn["silent_days"]
    assert bjorn["promises"] == {"you_owe": 1, "they_owe": 1}, "one each way, both open"
    assert elin["promises"] == {"you_owe": 0, "they_owe": 0}
    assert "days_together" not in bjorn, "the days themselves only with --show"
    assert lb.meta["head"] == head, "nothing is written"


def test_real_contact_is_a_day_together_a_meeting_an_answered_call_or_a_direct_message(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    rows = {r["name"]: r for r in _json(capsys, "people", "drift", "--quiet-days", "0")["people"]}
    real = {name: (r["last_real_contact"]["day"], r["last_real_contact"]["via"]) for name, r in rows.items()}
    assert real[CAMILLA["name"]] == ("2025-06-01", "call"), "the call answered; the missed one later is not"
    assert real[INGRID["name"]] == ("2025-09-01", "meeting"), (
        "a timed entry attended, held nowhere: a meeting"
    )
    assert real[JON["name"]] == ("2025-08-01", "meeting"), "a transcript spoken in"
    assert real[ELIN["name"]] == ("2022-06-12", "together"), "a line in a group is the group's"
    assert real[DAG["name"]] == ("2023-07-04", "together"), "a newsletter and a mail to everyone are not one"
    assert real[ASTRID["name"]][1] == "together", "the owner's mail to many is not a contact"
    assert real[BJORN["name"]] == ("2024-03-10", "message"), "a direct message, theirs"
    assert real[FRODE["name"]] == (F_DAYS[-1], "together")
    assert GURO["name"] not in rows and HANS["name"] not in rows, (
        "19 days, and ten a year, are under the floor"
    )


def test_drift_options_narrow_it(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    assert _names(_json(capsys, "people", "drift", "--year", "2023")["people"]) == [
        DAG["name"],
        BJORN["name"],
    ]
    assert _names(_json(capsys, "people", "drift", "--quiet-days", "700")["people"]) == [
        ELIN["name"],
        ASTRID["name"],
        DAG["name"],
    ]
    with_g = _names(_json(capsys, "people", "drift", "--min-days", "19")["people"])
    assert GURO["name"] in with_g and with_g.index(GURO["name"]) == len(with_g) - 1
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "drift", "--min-days", "none"])
    assert e.value.code == 2


def test_drift_text_and_show_name_the_days_never_the_words(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _run(capsys, "people", "drift")
    _only_canonical(text)
    lines = text.splitlines()
    assert lines[0].startswith("drift · 4 people")
    bjorn = next(row for row in lines if BJORN["name"] in row)
    assert "2023: 22 days" in bjorn and "2024-03-10 (message" in bjorn
    assert "you owe 1" in bjorn and "they owe 1" in bjorn
    assert "photos" not in text and "charts" not in text
    shown = _run(capsys, "people", "drift", "--show")
    assert "2023-01-05" in shown and "photos" not in shown and "charts" not in shown, "days, never text"
    data = _json(capsys, "people", "drift", "--show")
    bjorn_json = next(r for r in data["people"] if r["name"] == BJORN["name"])
    assert len(bjorn_json["days_together"]) == 22 and bjorn_json["days_together"][0]["day"] == "2023-01-05"
    assert all(len(id_) == 36 for d in bjorn_json["days_together"] for id_ in d["lines"])
    assert "text" not in json.dumps(bjorn_json)


# -- nearby -------------------------------------------------------------------------------------------------


def test_nearby_a_city_by_the_gazetteer_ranks_by_days_there(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "people", "nearby", "Bergen")
    (place,) = data["places"]
    assert place["label"] == "Bergen" and place["radius_km"] == 50 and place["by"] == "airports"
    people = place["people"]
    assert _names(people) == [ASTRID["name"], DAG["name"], INGRID["name"]]
    astrid = people[0]
    assert astrid["days_there"] == 24 and astrid["days"] == 24 and astrid["last_there"] == A_DAYS[-1]
    assert astrid["last_real_contact"]["day"] == A_DAYS[-1]
    assert people[2]["last_real_contact"] == {**people[2]["last_real_contact"], "day": "2025-09-01"}
    text = _run(capsys, "people", "nearby", "Bergen")
    _only_canonical(text)
    assert "Astrid Bakke" in text and "24 days there" in text and f"last seen {A_DAYS[-1]}" in text


def test_nearby_a_named_place_and_coordinates(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    data = _json(capsys, "people", "nearby", "home")
    (place,) = data["places"]
    assert place["label"] == "Home" and place["by"] == "places"
    names = _names(place["people"])
    assert names[:5] == [HANS["name"], ELIN["name"], CAMILLA["name"], FRODE["name"], GURO["name"]]
    assert place["people"][0]["days_there"] == 31
    assert OBSERVED["name"] not in names and set(names) <= set(NAMES)
    near = _json(capsys, "people", "nearby", "63.43,10.40", "--radius", "10")
    assert _names(near["places"][0]["people"])[:2] == [BJORN["name"], JON["name"]]
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "nearby", "Atlantis"])
    assert e.value.code == 2 and "Atlantis" in capsys.readouterr().err


def test_nearby_the_planned_days_are_the_flight_and_the_entries_away_from_home(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "people", "nearby", "--days", "2025-12-19", "2025-12-23")
    assert [p["label"] for p in data["places"]] == ["Bergen", "Trondheim"], "the party at home is not a trip"
    bergen, trondheim = data["places"]
    assert any(f["kind"] == "flight" for f in bergen["from"])
    assert {f["kind"] for f in trondheim["from"]} == {"journey", "event"}
    assert _names(bergen["people"]) == [ASTRID["name"], DAG["name"], INGRID["name"]]
    assert _names(trondheim["people"])[:3] == [BJORN["name"], JON["name"], KRISTIN["name"]]
    text = _run(capsys, "people", "nearby", "--days", "2025-12-19", "2025-12-23")
    _only_canonical(text)
    assert text.index("Bergen") < text.index("Trondheim")


def test_nearby_a_journey(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    with lb.index() as idx:
        (line,) = idx.by_kind("journey")
    data = _json(capsys, "people", "nearby", "--journey", str(line["id"]))
    (place,) = data["places"]
    assert place["label"] == "Trondheim" and _names(place["people"])[:2] == [BJORN["name"], JON["name"]]
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "nearby", "--journey", "no-such-line"])
    assert e.value.code == 2


def test_the_help_names_the_readers_defaults() -> None:
    from logbook.commands.people import people_drift_default
    from logbook.contrib import people_drift, people_nearby

    assert int(people_drift_default("min")) == people_drift.DEFAULT_MIN_DAYS
    assert int(people_drift_default("quiet")) == people_drift.DEFAULT_QUIET_DAYS
    assert float(people_drift_default("radius")) == people_nearby.DEFAULT_RADIUS_KM


def test_nearby_takes_one_of_a_place_a_journey_or_days(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["people", "nearby"],
        ["people", "nearby", "Bergen", "--days", "2025-12-19", "2025-12-23"],
        ["people", "merge", "Bergen"],
        ["people", "Bjørn", "--min-days", "3"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2


# -- anniversaries ------------------------------------------------------------------------------------------


def test_day_names_the_shared_days_one_and_three_years_ago(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _run(capsys, "day", "2025-11-03")
    rows = [row for row in text.splitlines() if "years ago" in row or "year ago" in row]
    assert rows[0].lstrip().startswith("anniversaries")
    assert "1 year ago" in rows[0] and KRISTIN["name"] in rows[0] and "2024-11-03" in rows[0]
    assert "3 years ago" in rows[1] and HANS["name"] in rows[1] and "2022-11-03" in rows[1]
    assert len(rows) == 2
    _only_canonical(text)
    data = _json(capsys, "day", "2025-11-03")
    assert [(a["years"], a["name"]) for a in data["anniversaries"]] == [
        (1, KRISTIN["name"]),
        (3, HANS["name"]),
    ]
    assert all(a["lines"] for a in data["anniversaries"])


def test_anniversaries_are_five_at_most_and_off_with_a_flag(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    text = _run(capsys, "day", "2025-10-14")
    rows = [row for row in text.splitlines() if "1 year ago" in row]
    assert len(rows) == 5, "six people a year ago; five lines"
    assert KRISTIN["name"] in rows[0], "the most days together first"
    off = _run(capsys, "day", "2025-10-14", "--no-anniversaries")
    assert "anniversaries" not in off and "year ago" not in off
    assert "anniversaries" not in _json(capsys, "day", "2025-10-14", "--no-anniversaries")
    assert "anniversaries" not in _json(capsys, "day", "2025-10-15"), "no key on a day with none"


def test_every_name_printed_is_canonical(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    for args in (
        ["people", "drift", "--quiet-days", "0", "--min-days", "1"],
        ["people", "nearby", "Oslo"],
        ["people", "nearby", "--days", "2022-01-01", "2025-12-31"],
    ):
        out = _run(capsys, *args)
        _only_canonical(out)
    # the Day's company names an attendee as the entry spells them (SPEC 3.2.5); its anniversaries never
    day = _run(capsys, "day", "2025-11-03")
    _only_canonical("\n".join(row for row in day.splitlines() if "ago, " in row))
    data = _json(capsys, "people", "drift", "--quiet-days", "0", "--min-days", "1")
    assert set(_names(data["people"])) <= set(BY_NAME)


def test_nothing_is_written(lb: Logbook, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    head, seq = lb.meta["head"], lb.meta["seq"]
    _run(capsys, "people", "drift")
    _run(capsys, "people", "nearby", "Bergen")
    _run(capsys, "day", "2025-11-03")
    after = Logbook.find()
    assert (after.meta["head"], after.meta["seq"]) == (head, seq)
