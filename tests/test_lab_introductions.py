"""`logbook lab introductions`: for every person, the first day the record confirms them present at a
stay with the owner, and who else was confirmed present that day. Synthetic Oslo persona, nobody
in it exists; nothing is appended."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from persona import (
    HOME,
    KARI,
    KARI_ID,
    OFFICE,
    OLA,
    OLA_ID,
    TZ,
    attendee,
    dwell,
    event,
    note,
    photo,
    resolution,
    transcript,
    travel,
    utc,
)

from logbook import cli
from logbook.store import Logbook

PER = {"id": "019cadd3-6bc0-7dcd-9133-000000000003", "name": "Per Hansen", "email": "per.hansen@example.org"}
LIV = {"id": "019cadd3-6bc0-7dcd-9133-000000000004", "name": "Liv Berg", "email": "liv.berg@example.org"}
FIRST, LATER, LAST = "2026-06-01", "2026-07-10", "2026-07-17"  # Kari alone; then three at once; nothing new
PLACES = {
    "Home": {"lat": HOME[0], "lon": HOME[1], "radius_m": 120, "kind": "home"},
    "Office": {"lat": OFFICE[0], "lon": OFFICE[1], "radius_m": 120},
}


def _office_day(day: str) -> list[dict[str, Any]]:
    return (
        dwell(day, "07:00", "08:00", HOME, every_min=20)
        + travel(day, "08:00", "08:10", HOME, OFFICE, steps=3)
        + dwell(day, "08:10", "17:50", OFFICE, every_min=20)
        + travel(day, "17:50", "18:00", OFFICE, HOME, steps=3)
        + dwell(day, "18:00", "23:40", HOME, every_min=20)
    )


def _drafts() -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        resolution(("email", PER["email"]), PER["id"], PER["name"]),
        resolution(("email", LIV["email"]), LIV["id"], LIV["name"]),
        resolution(("provider_id", f"immich:{KARI['face']}"), KARI_ID, "Kari Nordmann"),
    ]
    for day in (FIRST, LATER, LAST):
        drafts += _office_day(day)
    # The first day: lunch with Kari at the office. A face in a photo proposes Ola, which is not a
    # confirmation; an all-day entry naming Per places nobody either.
    drafts.append(
        event(utc(FIRST, "12:00"), utc(FIRST, "13:00"), "Lunch", [attendee(KARI["email"])], location="Office")
    )
    drafts.append(photo(utc(FIRST, "12:30"), OFFICE, people=[KARI["face"], "p_99"]))
    drafts.append(
        event(
            utc(FIRST, "00:00"), utc("2026-06-02", "00:00"), "Offsite", [attendee(PER["email"])], all_day=True
        )
    )
    # Five weeks later, three people at once: Ola in a transcript at the office, Per and Kari in a
    # planning entry at the same stay, Liv in a note at home that evening.
    drafts.append(
        transcript(
            utc(LATER, "10:00"),
            utc(LATER, "10:30"),
            "Boat plans",
            [{"name": "Ola Nordmann", "email": OLA["email"]}],
        )
    )
    drafts.append(
        event(
            utc(LATER, "14:00"),
            utc(LATER, "15:00"),
            "Planning",
            [attendee(KARI["email"]), attendee(PER["email"], response="needsAction")],
            location="Office",
        )
    )
    drafts.append(note(utc(LATER, "19:30"), "Dinner at home with Liv Berg. Pasta."))
    # A week on, Per and Ola again: nothing new to introduce.
    drafts.append(
        event(
            utc(LAST, "09:00"),
            utc(LAST, "10:00"),
            "Standup",
            [attendee(PER["email"]), attendee(OLA["email"])],
        )
    )
    return drafts


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    lb = Logbook.init(tmp_path_factory.mktemp("introductions") / "lb", TZ)
    lb.append_many(_drafts())
    (lb.root / "places.json").write_text(json.dumps(PLACES), encoding="utf-8")
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["lab", "introductions", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def test_first_days_and_likely_introducers(
    record: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    head = record.meta["head"]
    data = _json(capsys)
    assert data["window"] == {"since": FIRST, "until": LAST, "days": data["window"]["days"]}
    by_name = {p["name"]: p for p in data["people"]}
    assert [p["name"] for p in data["people"]] == ["Kari Nordmann", "Liv Berg", "Ola Nordmann", "Per Hansen"]
    kari = by_name["Kari Nordmann"]
    assert kari["person"] == KARI_ID and kari["first_day"] == FIRST
    assert kari["where"] == "Office" and kari["sources"] == ["calendar"]
    assert kari["introducers"] == [] and kari["met_together"] == []
    assert kari["near_record_start"] is True, "the record had just begun: the first day is not a meeting"
    assert len(kari["lines"]) == 1 and len(kari["lines"][0]) == 36
    per = by_name["Per Hansen"]
    assert per["first_day"] == LATER and per["near_record_start"] is False
    assert per["sources"] == ["calendar"], "the all-day entry on the first day placed nobody"
    [introducer] = per["introducers"]
    assert introducer["name"] == "Kari Nordmann" and introducer["known_since"] == FIRST
    assert introducer["same_stay"] is True and len(introducer["lines"]) == 1
    assert [(m["name"], m["same_stay"]) for m in per["met_together"]] == [
        ("Ola Nordmann", True),
        ("Liv Berg", False),
    ]
    ola = by_name["Ola Nordmann"]
    assert ola["first_day"] == LATER and ola["sources"] == ["transcript"]
    introducers = [i["name"] for i in ola["introducers"]]
    assert introducers == ["Kari Nordmann"], "a tagged face on the first day is proposed, not confirmed"
    liv = by_name["Liv Berg"]
    assert liv["where"] == "Home" and liv["sources"] == ["note"]
    assert [(i["name"], i["same_stay"]) for i in liv["introducers"]] == [("Kari Nordmann", False)]
    assert {m["name"] for m in liv["met_together"]} == {"Ola Nordmann", "Per Hansen"}
    assert isinstance(data["blind_spots"], list) and len(data["blind_spots"]) >= 4
    assert all(isinstance(s, str) and s.endswith(".") for s in data["blind_spots"])
    assert record.meta["head"] == head and no_network == []


def test_text_lists_one_row_per_person_and_the_blind_spots(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    text = _run(capsys)
    lines = text.splitlines()
    assert lines[0].startswith(f"introductions {FIRST}") and "4 people" in lines[0]
    [per_row] = [row for row in lines if row.strip().startswith(f"{LATER}  Per Hansen")]
    assert "Office" in per_row and "Kari Nordmann" in per_row and FIRST in per_row
    [kari_row] = [row for row in lines if row.strip().startswith(FIRST)]
    assert "record had just begun" in kari_row
    assert "blind spots" in text
    assert "proposed" in text or "face" in text, "the text says what does not count as a confirmation"


def test_a_window_narrows_what_counts_as_first(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    data = _json(capsys, "--since", LATER)
    by_name = {p["name"]: p for p in data["people"]}
    assert by_name["Kari Nordmann"]["first_day"] == LATER, "the window starts after her real first day"
    kari = by_name["Kari Nordmann"]
    assert kari["near_record_start"] is False, "measured against the record, not the window"
    assert by_name["Per Hansen"]["introducers"] == [], "inside the window nobody was known before"
    assert {m["name"] for m in by_name["Per Hansen"]["met_together"]} == {
        "Kari Nordmann",
        "Ola Nordmann",
        "Liv Berg",
    }


def test_an_empty_record_has_nobody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _json(capsys) == {"window": None, "people": [], "blind_spots": _json(capsys)["blind_spots"]}
    assert "no days" in _run(capsys)
