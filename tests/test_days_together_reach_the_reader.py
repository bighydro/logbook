"""Days together go to the relationship reader (RFC 0036 amendment 2, the owner's decision of 18 October
2026): a person's set for `people ask` and `dream person` adds the days the with module counts as days
together in the window, each with its date, the `places.json` name of the stay they shared ("a place
with no name" for a stay at none, never coordinates) and the line ids it rests on, sent as references.
The same gate as every other line: at or under the `relationship` entry's `max_tier`, on signed days.
The endpoint is an in-process fake under the `no_network` guard; the record is slice 0's synthetic June
of Ines and Ola Nordmann of Oslo, who do not exist, with the owner's stays added: the Marina on the
12th, a mooring out on the fjord (no named place) on the 17th, and the café on the 30th, a day the
owner has not signed."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from persona import CAFE, FJORD, MARINA, PLACES, attendee, dwell, event, note, utc
from test_relationship_model import _env, _fake, _sent
from test_relationship_reader import OLA, WINDOW, _entry, _ingest, _record

from logbook import cli
from logbook.contrib import dream_person
from logbook.contrib.relationship import ask, reader
from logbook.core import drafts, signing
from logbook.core.store import Logbook, uuid7

COORDINATE = re.compile(r"\d{1,3}\.\d{3,}")  # 59.9050, 10.735: what a stay at no named place reads as


@pytest.fixture
def june(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str]
) -> tuple[Logbook, dict[str, str]]:
    lb, ids = _record(tmp_path, monkeypatch)
    _env(monkeypatch)
    monkeypatch.setattr(dream_person, "today", lambda: date(2026, 7, 1))
    (lb.root / "places.json").write_text(json.dumps({"Marina": PLACES["Marina"]}), encoding="utf-8")
    coffee = note(utc("2026-06-30", "19:00"), "Coffee with Ola at the café.")
    coffee["id"] = uuid7()
    dinner = event(  # tier 1, held at the Marina: he attends
        utc("2026-06-12", "19:00"),
        utc("2026-06-12", "21:00"),
        "Crew dinner",
        [attendee(OLA["email"], OLA["name"])],
        location="Marina",
    )
    dinner["id"] = uuid7()
    lb.append_many(
        [
            *dwell("2026-06-12", "16:30", "23:30", MARINA),  # the meeting and the dinner note: the Marina
            *dwell("2026-06-17", "09:30", "11:30", FJORD),  # the recorded crew call: no named place
            *dwell("2026-06-30", "18:00", "21:00", CAFE),  # the 30th, a day not signed
            coffee,
            dinner,
        ]
    )
    ids["coffee"], ids["dinner"] = str(coffee["id"]), str(dinner["id"])
    for day in ("2026-06-12", "2026-06-17"):  # signed again over the page with the owner's stays on it
        signing.sign(lb, day, at=utc("2026-06-30", "23:00"))
    return lb, ids


def _ask(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    code = 0
    try:
        cli.main(["people", "ask", "Ola Nordmann", "When did we spend time together?", *args])
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def _cites_the_days(material: dict[str, Any]) -> dict[str, Any]:
    days = material.get("days_together") or []
    return {
        "answer": [
            {"text": f"You were together on {d['day']}.", "evidence": list(d["evidence"])} for d in days
        ]
        or [{"text": "Nothing says so.", "unsupported": True}]
    }


def _days(found: reader.InputSet) -> list[tuple[str, tuple[str, ...]]]:
    return [(t.day, t.places) for t in found.together]


def test_two_days_together_are_in_his_set_and_the_unsigned_one_is_held_back(
    june: tuple[Logbook, dict[str, str]],
) -> None:
    lb, ids = june
    found = reader.read(lb, "Ola Nordmann", *WINDOW, 2)
    assert _days(found) == [("2026-06-12", ("Marina",)), ("2026-06-17", (reader.NO_NAME,))]
    by_day = {t.day: t for t in found.together}
    assert set(by_day["2026-06-12"].lines) == {ids["dinner"], ids["note"]}
    assert by_day["2026-06-17"].lines == (ids["recorded"],)
    assert found.together_held == 1, "the café on the 30th rests on a note of a day not signed"
    assert ids["note"] not in found.by_line(), "the note is not a line of his set: it is a day's evidence"
    assert ids["note"] in found.by_evidence() and ids["coffee"] not in found.by_evidence()
    lifted = reader.read(lb, "Ola Nordmann", *WINDOW, 2, include_unsigned=True)
    assert [t.day for t in lifted.together] == ["2026-06-12", "2026-06-17", "2026-06-30"]
    assert lifted.together[-1].places == (reader.NO_NAME,) and lifted.together_held == 0


def test_people_ask_sends_the_days_as_references_and_never_a_coordinate(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb, ids = june
    _ingest(lb)
    seen = _fake(monkeypatch, _cites_the_days)
    code, out, err = _ask(capsys, "--show-prompt")
    assert code == 0, err
    assert "days_together" in out and "Marina" in out and reader.NO_NAME in out
    assert not COORDINATE.search(out), "no coordinate is ever in the prompt"
    request = json.dumps(seen["calls"][-1], ensure_ascii=False)  # what would have left the machine
    assert not COORDINATE.search(request)
    for name in ("note", "dinner", "recorded", "coffee"):
        assert ids[name] not in request, f"{name}: references, never ids"
    assert "Dinner with Ola" not in request and "Coffee with Ola" not in request, "its day, not its words"
    sent = _sent(seen)
    days = sent["days_together"]
    assert [d["day"] for d in days] == ["2026-06-12", "2026-06-17"]
    refs = {line["ref"] for line in sent["lines"]}
    assert all(re.fullmatch(r"L\d+", ref) for d in days for ref in d["evidence"])
    assert any(ref not in refs for ref in days[0]["evidence"]), "the note gets a reference of its own"


def test_a_claim_citing_a_day_together_resolves_and_the_answer_counts_them(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb, ids = june
    _ingest(lb)
    _fake(monkeypatch, _cites_the_days)
    code, out, err = _ask(capsys, "--json")
    assert code == 0, err
    data = json.loads(out)
    assert data["days_together"] == {"sent": 2, "held_back": 1}
    first, second = data["answer"]
    assert first["supported"] and {c["id"] for c in first["evidence"]} == {ids["dinner"], ids["note"]}
    assert second["supported"] and [c["id"] for c in second["evidence"]] == [ids["recorded"]]
    noted = next(c for c in first["evidence"] if c["id"] == ids["note"])
    assert noted["line"]["kind"] == "note" and noted["line"]["speakers"] == []
    assert data["unsupported"] == 0
    code, out, _err = _ask(capsys)
    assert code == 0 and "2 days together" in out.splitlines()[0]


def test_at_max_tier_1_a_day_resting_on_a_tier_2_line_is_not_sent(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb, ids = june
    _entry(lb, 1, "2026-12-31")
    found = reader.read(lb, "Ola Nordmann", *WINDOW, 1)
    # the 12th rests on the tier-1 dinner at the Marina as well, so it stays, on that line alone; the
    # 17th rests on the tier-2 recording only, so it is not sent, and is counted
    assert _days(found) == [("2026-06-12", ("Marina",))]
    assert found.together[0].lines == (ids["dinner"],) and found.together_held == 2
    _ingest(lb)
    seen = _fake(monkeypatch, _cites_the_days)
    code, out, err = _ask(capsys, "--json")
    assert code == 0, err
    assert json.loads(out)["days_together"] == {"sent": 1, "held_back": 2}
    sent = json.dumps(_sent(seen))
    assert "2026-06-17" not in json.dumps(_sent(seen)["days_together"]) and ids["note"] not in sent


def test_nothing_is_sent_without_the_entry_or_after_its_date(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb, _ids = june
    _ingest(lb)
    seen = _fake(monkeypatch, _cites_the_days)
    _entry(lb, 2, "2026-06-30")  # today is 1 July
    code, _out, err = _ask(capsys)
    assert code == 2 and "expired" in err and seen["calls"] == []


def _person_answer(material: dict[str, Any]) -> dict[str, Any]:
    days = material["days_together"]
    first = material["lines"][0]["ref"]
    return {
        "person": [
            {"text": "You spent the 12th together at the Marina.", "evidence": list(days[0]["evidence"])},
            {"text": "You were out on the water on the 17th.", "evidence": list(days[1]["evidence"])},
            {"text": "You wrote first.", "evidence": [first]},
        ],
        "threads": [],
        "promises": [],
        "questions": [],
    }


def test_dream_person_reads_the_days_together_and_writes_their_ids(
    june: tuple[Logbook, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lb, ids = june
    seen = _fake(monkeypatch, _person_answer)
    code = 0
    try:
        cli.main(["dream", "person", "Ola Nordmann", "--window", *WINDOW, "--show-prompt"])
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    assert code == 0, err
    assert "days_together" in out and not COORDINATE.search(out) and ids["note"] not in out
    assert [d["day"] for d in _sent(seen)["days_together"]] == ["2026-06-12", "2026-06-17"]
    (line,) = [line for line in lb.lines() if line.get("kind") == drafts.KIND]
    segments = line["payload"]["segments"]
    assert set(segments[0]["evidence"]) == {ids["dinner"], ids["note"]}
    assert segments[1]["evidence"] == [ids["recorded"]]
    assert line["payload"]["extra"]["days_together"] == 2
    assert line["payload"]["extra"]["prompt"] == dream_person.PROMPT_NAME


def test_a_person_with_no_day_together_is_sent_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    lb, _ids = _record(tmp_path, monkeypatch)  # no stays: no day together
    _env(monkeypatch)
    _ingest(lb)
    seen = _fake(monkeypatch, _cites_the_days)
    code, out, err = _ask(capsys, "--json")
    assert code == 0, err
    assert "days_together" not in _sent(seen) and json.loads(out)["days_together"] == {
        "sent": 0,
        "held_back": 0,
    }
    assert ask.Question("x", ("2026-06-01", "2026-06-30"), "q", []).together == []
