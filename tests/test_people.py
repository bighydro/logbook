"""`logbook people` and `logbook person <name-or-ref>`: every resolved person of the record and
one person's page, read through the index. The Oslo persona's circle of twelve (`circle.py`);
nothing is written."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from circle import (
    ANDERS,
    EVA,
    FREJA,
    JONAS,
    KARI_ID,
    LIV,
    MARTA,
    NILS,
    OLA,
    OLA_BIRTHDAY,
    OLA_ID,
    OWNER,
    PER,
    RETRACTED_TEXT,
    SIGRID,
    TORE,
    circle_record,
)

from logbook import cli
from logbook.index import Index
from logbook.store import Logbook


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _by_name(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in data["people"]}


# -- people -------------------------------------------------------------------------------------------------


def test_people_lists_every_resolved_person_with_evidence_and_never_the_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = circle_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    data = _json(capsys, "people")
    assert data["window"] == {"since": "2026-06-01", "until": "2026-06-21"}, "the record's days, any kind"
    people = _by_name(data)
    assert OWNER["name"] not in people, "the owner is never their own company"
    assert TORE["name"] not in people, "a declined attendee is no evidence; nobody with none is listed"
    assert set(people) == {
        "Ola Nordmann",
        "Kari Nordmann",
        LIV["name"],
        FREJA["name"],
        ANDERS["name"],
        SIGRID["name"],
        EVA["name"],
        PER["name"],
        NILS["name"],
        MARTA["name"],
        JONAS["name"],
    }
    ola = people["Ola Nordmann"]
    assert ola["id"] == OLA_ID and sorted(r["kind"] for r in ola["refs"]) == ["email", "phone"]
    assert ola["channels"]["messages"] == {
        "lines": 5,
        "first": "2026-06-09",
        "last": "2026-06-14",
        "tier": 2,
        "last_line": ola["channels"]["messages"]["last_line"],
    }, "two from Ola and three of mine in the direct chat; a group line of mine names nobody"
    assert len(ola["channels"]["messages"]["last_line"]) == 36
    assert ola["channels"]["calendar"]["lines"] == 1 and ola["channels"]["transcripts"]["lines"] == 1
    assert set(ola["channels"]) == {"messages", "calendar", "transcripts"}
    assert ola["days"] == 3 and ola["nights"] == 2, "anchored with Ola, dinner in Zürich"
    assert ola["first_contact"] == "2026-06-09" and ola["last_contact"] == "2026-06-16"
    assert ola["last_real_contact"] == {
        "day": "2026-06-16",
        "via": "meeting",
        "line": ola["last_real_contact"]["line"],
    }
    assert {p["where"] for p in ola["places"]} >= {"Office", "aboard solvind"}
    assert all(p["days"] == 1 for p in ola["places"]) and len(ola["places"]) == 3
    assert ola["birthday"] == OLA_BIRTHDAY and ola["tier"] == 2
    assert all(len(id_) == 36 for id_ in ola["lines"]) and len(ola["lines"]) == 3, "the shared days' evidence"
    kari = people["Kari Nordmann"]
    assert kari["id"] == KARI_ID and kari["days"] == 1 and kari["nights"] == 0
    assert kari["channels"]["calendar"]["lines"] == 1 and kari["channels"]["faces"]["lines"] == 2
    assert kari["last_real_contact"]["day"] == "2026-06-10" and kari["birthday"] is None
    liv = people[LIV["name"]]
    assert liv["channels"] == {"calendar": liv["channels"]["calendar"]} and liv["days"] == 1
    assert liv["last_real_contact"]["via"] == "meeting" and liv["places"] == [{"where": "Office", "days": 1}]
    jonas = people[JONAS["name"]]
    assert jonas["channels"]["calendar"]["lines"] == 1 and jonas["days"] == 0
    assert jonas["last_real_contact"] is None, "an all-day entry is a channel, never a meeting"
    freja = people[FREJA["name"]]
    assert freja["channels"]["transcripts"]["lines"] == 1 and freja["days"] == 1
    assert (
        freja["places"] == [{"where": "Office", "days": 1}]
        and freja["last_real_contact"]["day"] == "2026-06-19"
    )
    anders = people[ANDERS["name"]]
    assert anders["channels"]["messages"]["lines"] == 1 and anders["channels"]["faces"]["lines"] == 1
    assert anders["days"] == 0, "a tagged face is a proposal, not a day together"
    assert anders["last_real_contact"] == {
        "day": "2026-06-11",
        "via": "message",
        "line": anders["last_real_contact"]["line"],
    }
    sigrid = people[SIGRID["name"]]
    assert sigrid["channels"]["messages"]["lines"] == 1, "the retracted message is out"
    assert sigrid["last_contact"] == "2026-06-11"
    eva = people[EVA["name"]]
    assert eva["channels"]["calls"]["lines"] == 1 and eva["last_real_contact"]["via"] == "call"
    assert eva["last_real_contact"]["day"] == "2026-06-17"
    per = people[PER["name"]]
    assert per["channels"]["calls"]["lines"] == 1 and per["last_real_contact"] is None, "not answered"
    assert per["first_contact"] == "2026-06-12" and per["last_contact"] == "2026-06-12"
    nils = people[NILS["name"]]
    assert nils["channels"] == {"mail": nils["channels"]["mail"]} and nils["last_real_contact"] is None
    marta = people[MARTA["name"]]
    assert marta["channels"]["mail"]["lines"] == 1, "a mail I sent counts for its recipient"
    assert data["tier"] == 2 and all(p["tier"] == 2 for p in data["people"])
    assert data["people"][0]["name"] == "Ola Nordmann", "most days together first"
    assert lb.meta["head"] == head, "nothing is written"


def test_people_text_is_one_row_per_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    circle_record(tmp_path, monkeypatch)
    text = _run(capsys, "people")
    assert "11 people" in text and "tier 2" in text and "2026-06-01" in text
    assert OWNER["name"] not in text and TORE["name"] not in text and RETRACTED_TEXT not in text
    ola = next(row for row in text.splitlines() if "Ola Nordmann" in row)
    assert "3 days" in ola and "2 nights" in ola and "messages 5" in ola and "2026-06-16" in ola
    assert OLA_BIRTHDAY in text
    assert "Office" in text and "aboard solvind" in text
    jonas = next(row for row in text.splitlines() if JONAS["name"] in row)
    assert "calendar 1" in jonas and "days" not in jonas


def test_year_narrows_the_window_and_an_empty_one_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    circle_record(tmp_path, monkeypatch)
    data = _json(capsys, "people", "--year", "2026")
    assert len(data["people"]) == 11
    data = _json(capsys, "people", "--year", "2025")
    assert data == {"window": None, "tier": None, "people": []}
    assert "no people" in _run(capsys, "people", "--year", "2025")
    with pytest.raises(SystemExit) as e:
        cli.main(["people", "--year", "26"])
    assert e.value.code == 2 and "year" in capsys.readouterr().err


def test_tier_is_the_highest_tier_of_the_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import transcript, utc

    lb = circle_record(tmp_path, monkeypatch)
    recorded = transcript(
        utc("2026-06-20", "10:00"),
        utc("2026-06-20", "10:30"),
        "Plans",
        [{"name": "Per Hansen", "email": PER["email"]}],
    )
    recorded["tier"] = 3
    lb.append_many([recorded])
    data = _json(capsys, "people")
    people = _by_name(data)
    assert people[PER["name"]]["tier"] == 3 and people[PER["name"]]["channels"]["transcripts"]["tier"] == 3
    assert people["Ola Nordmann"]["tier"] == 2 and data["tier"] == 3
    assert "tier 3" in _run(capsys, "people")


def test_people_reads_through_the_index_and_never_sweeps_the_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = circle_record(tmp_path, monkeypatch)
    with lb.index():
        pass  # built now, so the reader finds it current

    def scan(*_: Any, **__: Any) -> Any:
        raise AssertionError("people never sweeps the files")

    monkeypatch.setattr(Logbook, "lines", scan)
    monkeypatch.setattr(Logbook, "lines_unsorted", scan)
    monkeypatch.setattr(Logbook, "located_lines", scan)
    monkeypatch.setattr(Index, "between", scan)
    monkeypatch.setattr(Index, "day", scan)
    assert len(_json(capsys, "people")["people"]) == 11
    assert _json(capsys, "person", "Ola")["name"] == "Ola Nordmann"


def test_an_empty_record_has_no_people(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _json(capsys, "people") == {"window": None, "tier": None, "people": []}
    assert "no people" in _run(capsys, "people")
    with pytest.raises(SystemExit) as e:
        cli.main(["person", "Ola"])
    assert e.value.code == 2


def test_a_record_that_names_nobody_has_no_people_and_no_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from persona import HOME, point, utc

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many([point(utc("2026-06-08", "08:00"), HOME)])
    data = _json(capsys, "people")
    assert data == {"window": {"since": "2026-06-08", "until": "2026-06-08"}, "tier": None, "people": []}
    text = _run(capsys, "people")
    assert text.startswith("0 people") and "None" not in text


# -- person -------------------------------------------------------------------------------------------------


def test_a_person_page_is_found_by_name_first_name_ref_or_id_and_lists_the_shared_days_latest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = circle_record(tmp_path, monkeypatch)
    head = lb.meta["head"]
    by_name = _json(capsys, "person", "Ola Nordmann")
    assert by_name["page"] == "person" and by_name["id"] == OLA_ID and by_name["name"] == "Ola Nordmann"
    for how in ("ola", OLA_ID, OLA["email"], OLA["phone"], f"email:{OLA['email']}", f"phone:{OLA['phone']}"):
        assert _json(capsys, "person", how)["id"] == OLA_ID, how
    assert by_name["birthday"] == OLA_BIRTHDAY and by_name["tier"] == 2
    assert by_name["channels"]["messages"]["lines"] == 5 and by_name["days"] == 3 and by_name["nights"] == 2
    assert by_name["last_real_contact"]["day"] == "2026-06-16"
    shared = by_name["shared_days"]
    assert [s["day"] for s in shared] == ["2026-06-16", "2026-06-13", "2026-06-11"], "most recent first"
    assert shared[1]["where"] == "aboard solvind" and shared[1]["sources"] == ["note"]
    assert shared[2]["where"] == "Office" and shared[2]["reasons"] == ["spoke in Boat plans"]
    assert all(s["night"] is not None for s in shared[:2]) and shared[2]["night"] is None
    assert all(len(id_) == 36 for s in shared for id_ in s["lines"]) and all(s["stay"] for s in shared)
    assert lb.meta["head"] == head
    text = _run(capsys, "person", "Ola Nordmann")
    rows = text.splitlines()
    assert rows[0].startswith("Ola Nordmann") and OLA["email"] in rows[0] and "tier 2" in rows[0]
    assert OLA_BIRTHDAY in text and "messages 5" in text and "3 days together" in text and "2 nights" in text
    assert "last real contact 2026-06-16 (meeting)" in text
    days = [row for row in rows if row.startswith("    2026-06-")]
    assert [row.strip()[:10] for row in days] == ["2026-06-16", "2026-06-13", "2026-06-11"]
    assert "note says with Ola Nordmann" in days[1] and "aboard solvind" in days[1]


def test_a_person_with_no_evidence_has_a_page_that_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    circle_record(tmp_path, monkeypatch)
    data = _json(capsys, "person", "Tore Dahl")
    assert data["id"] == TORE["id"] and data["channels"] == {} and data["shared_days"] == []
    assert data["first_contact"] is None and data["last_real_contact"] is None and data["tier"] == 2
    text = _run(capsys, "person", "Tore")
    assert "no contact" in text and "Tore Dahl" in text


def test_a_person_the_record_does_not_know_several_or_the_owner_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    circle_record(tmp_path, monkeypatch)
    with pytest.raises(SystemExit) as e:
        cli.main(["person", "Nordmann"])
    assert e.value.code == 2 and "several" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["person", "Trude"])
    assert e.value.code == 2 and "nobody" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["person", "trude@example.org"])
    assert e.value.code == 2
    for how in (OWNER["name"], OWNER["email"], OWNER["phone"]):
        with pytest.raises(SystemExit) as e:
            cli.main(["person", how])
        assert e.value.code == 2 and "owner" in capsys.readouterr().err, how
    with pytest.raises(SystemExit) as e:
        cli.main(["person", "Ola", "--year", "2025"])
    assert e.value.code == 2 and "2025" in capsys.readouterr().err
