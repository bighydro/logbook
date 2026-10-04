"""`logbook digest [YYYY-MM-DD] [--json|--markdown]`: one short text per day — the Day's shape in
three lines, the flights, the open promises due within a week, the usual sources with no line, what
the calendar holds for tomorrow, and one closing question the owner can answer in a word, from
the record's question bank (`tests/test_questions.py` has the bank and the choice). It composes the
readers (`day`, `promises`, `gaps`, `days.usual_sources`) and derives nothing of its own; it writes
nothing to the record — the bank's default and the state of what was asked are files beside it —
and sends nothing. Synthetic Oslo persona, who does not exist; the clock is
pinned where today matters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, KARI, OLA_ID, TZ, attendee, dwell, event, note, persona_record, resolution, utc

from logbook import cli, digest, gaps, promises, questions
from logbook.commands import day as day_commands
from logbook.core.store import Logbook

NOW = datetime(2026, 6, 22, 18, 0, tzinfo=UTC)  # the Monday evening after the persona's fortnight
EN_DASH = "\u2013"
ARROW = "\u2192"


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["digest", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The persona's fortnight, plus: a note on Tuesday 9 June that promises the mooring photos by
    Friday and the insurance by 20 July; on Thursday 11 June a standup, a lunch with Kari and an
    all-day entry; the clock pinned to the Monday after."""
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    lb = persona_record(tmp_path, monkeypatch)
    lb.append_many(
        [
            note(
                utc("2026-06-09", "19:00"),
                "Long day. I'll send Ola the mooring photos by Friday."
                " I need to renew the insurance by July 20.",
            ),
            event(utc("2026-06-11", "09:00"), utc("2026-06-11", "09:30"), "Standup"),
            event(
                utc("2026-06-11", "12:00"),
                utc("2026-06-11", "13:00"),
                "Lunch",
                [attendee(KARI["email"], "Kari Nordmann")],
            ),
            event(utc("2026-06-11", "00:00"), utc("2026-06-12", "00:00"), "Kari in town", all_day=True),
        ]
    )
    return lb


# -- the shape of a day --------------------------------------------------------------------------------------


def test_an_office_day_in_three_lines_plus_the_question(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    head, before = lb.meta["head"], _files(lb.root)
    data = _json(capsys, "2026-06-10")
    assert data["day"] == "2026-06-10" and data["weekday"] == "Wednesday" and data["tz"] == TZ
    shape = data["shape"]
    assert shape["where"] == [
        "Home",
        "Office",
        "59.9200,10.7400 near Home, 1.0 km",
        "Office",
        "Home",
    ], "the cafe is unnamed"
    assert shape["night"]["where"] == "Home" and shape["night"]["home"] is True
    assert shape["with"]["confirmed"] == ["Kari Nordmann"], "an attendee of the lunch at the cafe"
    assert shape["with"]["proposed"] == [], "the face in the photo is the same person, confirmed elsewhere"
    assert {a["noun"]: a["count"] for a in shape["attached"]} == {"event": 1, "photo": 1}
    assert shape["unplaced"] == 0
    assert data["flights"] == []
    assert data["tomorrow"]["day"] == "2026-06-11"
    assert [e["title"] for e in data["tomorrow"]["entries"]] == [
        "Standup",
        "Lunch",
    ], "the all-day entry is not timed"
    assert data["tomorrow"]["entries"][1]["with"] == ["Kari Nordmann"]
    assert data["question"]["text"].endswith("?")
    assert lb.meta["head"] == head, "a digest writes nothing to the record"
    assert _files(lb.root) - before == {
        str(Path("policy") / "questions.json"),
        str(Path("state") / "questions.json"),
    }, "only the question bank's default and the state of what was asked; no reader's settings"
    text = _run(capsys, "2026-06-10")
    lines = text.splitlines()
    assert lines[0] == "2026-06-10  Wednesday"
    assert lines[1].startswith("  where") and "Home" in lines[1] and "Office" in lines[1]
    assert lines[2].startswith("  with") and "Kari Nordmann" in lines[2]
    assert lines[3].startswith("  attached") and "1 event, 1 photo" in lines[3]
    assert any(line.startswith("  tomorrow") and f"09:00{EN_DASH}09:30  Standup" in line for line in lines)
    assert any("Lunch" in line and "Kari Nordmann" in line for line in lines if line.startswith("  tomorrow"))
    assert lines[-1] == data["question"]["text"] and lines[-2] == "", "the question closes the digest"
    assert "Kari in town" not in text


def test_a_travel_day_names_its_flight_and_sleeps_away(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "2026-06-15")
    [flight] = data["flights"]
    assert (flight["carrier"], flight["number"], flight["from"], flight["to"]) == ("XY", "561", "OSL", "ZRH")
    assert flight["evidence"] == "tracked" and flight["line"]
    assert data["shape"]["night"]["home"] is False and data["shape"]["night"]["where"].endswith("(Zurich)")
    text = _run(capsys, "2026-06-15")
    assert f"  flight     XY 561 OSL{ARROW}ZRH  07:05{EN_DASH}09:15" in text
    assert "night away" in text.splitlines()[1]


# -- promises, gaps ----------------------------------------------------------------------------------------


def test_open_promises_due_within_seven_days_from_the_promises_reader(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _json(capsys, "2026-06-10")
    due = data["promises"]
    assert due["within_days"] == 7 and due["judged"] is False
    [photos] = due["open"]
    assert (
        photos["quote"] == "I'll send Ola the mooring photos by Friday."
        and photos["due"]["date"] == "2026-06-12"
    )
    assert photos["speaker"]["owner"] is True and photos["status"] == "open"
    text = _run(capsys, "2026-06-10")
    assert "  due        “I'll send Ola the mooring photos by Friday.”  you, 2026-06-12 (by Friday)" in text
    assert "insurance" not in text, "due 20 July: not within the week"
    # a week later the insurance is still not within seven days; the photos were due two days ago
    data = _json(capsys, "2026-06-14")
    assert data["promises"]["open"] == []
    # closed with `promises done`, it is out
    report = promises.extract(lb)
    [proposal] = [p for p in report.proposals if "mooring" in p.match.quote]
    cli.main(["promises", "done", proposal.id])
    capsys.readouterr()
    assert _json(capsys, "2026-06-10")["promises"]["open"] == []


def test_a_judged_set_on_the_report_narrows_the_promises() -> None:
    """A promises reader that judges its proposals puts the ids it holds to be promises on the
    report as `judged`; the digest keeps those alone. Without the attribute every open proposal counts."""

    @dataclass(frozen=True)
    class Judged(promises.Report):
        judged: frozenset[str] = frozenset()

    match = promises.Match("I'll call you by Friday.", "I'll", "future", "en", "by Friday", "2026-06-12")
    a = promises.Proposal(
        "a" * 16,
        "2026-06-09",
        utc("2026-06-09", "10:00"),
        "l1",
        1,
        "note",
        "manual",
        None,
        None,
        None,
        match,
        "2026-06-12",
    )
    b = promises.Proposal(
        "b" * 16,
        "2026-06-09",
        utc("2026-06-09", "10:00"),
        "l1",
        1,
        "note",
        "manual",
        None,
        None,
        None,
        match,
        "2026-06-12",
    )
    plain = promises.Report([a, b], {}, {"name": "rules", "version": "1"}, None)
    assert [p.id for p in digest.due_promises(plain, "2026-06-10")] == [a.id, b.id]
    judged = Judged([a, b], {}, {"name": "model", "version": "1"}, None, judged=frozenset({b.id}))
    assert [p.id for p in digest.due_promises(judged, "2026-06-10")] == [b.id]
    assert digest.due_promises(plain, "2026-06-13") == [], "due in the past is not due within the week"
    assert digest.due_promises(plain, "2026-06-05") == [a, b], "seven days ahead, inclusive"
    assert digest.due_promises(plain, "2026-06-04") == []


def test_a_usual_source_with_no_line_is_a_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A phone that logged every day of a week and is silent on Sunday 21 June: the digest of that
    Sunday names it, by the `sources --gaps` rule, with the week before deciding what is usual."""
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    drafts: list[dict[str, Any]] = []
    for day in range(14, 21):
        drafts += dwell(f"2026-06-{day:02d}", "08:00", "09:00", HOME, every_min=10)
    drafts.append(note(utc("2026-06-17", "20:00"), "A note once in the week."))
    lb.append_many(drafts)
    data = _json(capsys, "2026-06-21")
    assert data["gaps"] == {"usual": ["dawarich"], "missing": ["dawarich"]}, "manual spoke once: not usual"
    assert data["shape"]["where"] == [] and data["sources"] == []
    text = _run(capsys, "2026-06-21")
    assert "  gaps       dawarich: usual, no line" in text
    question = data["question"]
    assert "gap" in question["facts"] and "logged" not in question["facts"]
    assert question["id"] in ("gap-switched-off", "day-where"), "the two the bank asks on a silent day"
    assert text.splitlines()[-1] == question["text"] in ("Was dawarich switched off?", "Where were you?")
    assert _json(capsys, "2026-06-20")["gaps"]["missing"] == []


# -- the closing question ------------------------------------------------------------------------


def test_the_question_is_one_the_owner_answers_in_a_word(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """The question comes from the bank (`policy/questions.json`, written with its defaults on the
    first digest): its conditions hold on the day's facts, it ends in a question mark, and two days
    running never ask the same one."""
    bank = {q.id: q for q in questions.read(lb.root)}
    asked: list[str] = []
    for day in range(8, 22):
        data = _json(capsys, f"2026-06-{day:02d}")
        q = data["question"]
        assert set(q) == {"id", "kind", "text", "facts"} and q["text"].endswith("?")
        assert q["id"] in bank and q["kind"] == bank[q["id"]].kind
        facts = questions.Facts(flags={name: name in q["facts"] for name in questions.FACTS}, values={})
        assert questions.matches(bank[q["id"]], facts), (day, q)
        asked.append(q["id"])
    assert all(a != b for a, b in pairwise(asked)), asked
    # Saturday aboard: Ola is named in the note (confirmed), nobody proposed; a promise is not due; no gap
    saturday = _json(capsys, "2026-06-13")
    assert saturday["shape"]["with"]["confirmed"] == ["Ola Nordmann"]
    assert {"logged", "aboard", "company", "weekend", "travelled"} <= set(saturday["question"]["facts"])
    assert not {"proposed", "gap", "promise_due", "flew"} & set(saturday["question"]["facts"])
    assert saturday["question"] == _json(capsys, "2026-06-13")["question"], "asked once, it stands"
    # a face in a photo with no confirmation anywhere that day is a proposed person
    lb.append_many(
        [
            resolution(("email", "per@example.org"), OLA_ID[:-1] + "9", "Per Hansen"),
            resolution(("provider_id", "immich:p_99"), OLA_ID[:-1] + "9", "Per Hansen"),
            {
                "at": utc("2026-06-19", "19:00"),
                "source": "immich",
                "kind": "photo",
                "tier": 1,
                "payload": {
                    "schema": "photo/v1",
                    "asset_id": "p-per",
                    "library": "immich",
                    "file_name": "IMG_1900.HEIC",
                    "media": "image",
                    "provenance": "camera",
                    "faces": 1,
                    "people": ["p_99"],
                    "lat": HOME[0],
                    "lon": HOME[1],
                    "raw_id": "p-per",
                },
            },
        ]
    )
    friday = _json(capsys, "2026-06-19")
    assert friday["shape"]["with"] == {"confirmed": [], "proposed": ["Per Hansen"]}
    assert "proposed" in friday["question"]["facts"] and "photos" in friday["question"]["facts"]


def test_an_empty_day_is_short_and_asks_where_you_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    data = _json(capsys, "2026-06-10")
    assert data["shape"] == {
        "where": [],
        "night": {"where": None, "home": False, "aboard": None, "in_transit": True},
        "with": {"confirmed": [], "proposed": []},
        "attached": [],
        "unplaced": 0,
    }
    assert data["flights"] == [] and data["promises"]["open"] == [] and data["gaps"]["missing"] == []
    assert data["tomorrow"]["entries"] == [] and data["sources"] == []
    assert data["question"] == {"id": "day-where", "kind": "place", "text": "Where were you?", "facts": []}
    text = _run(capsys, "2026-06-10")
    assert text.splitlines() == [
        "2026-06-10  Wednesday",
        "  where      nothing logged",
        "  with       nobody confirmed",
        "  attached   nothing",
        "",
        "Where were you?",
    ]
    assert len(text.splitlines()) <= digest.LIMIT


# -- the length limit ----------------------------------------------------------------------------------------


def test_never_more_than_the_limit_and_never_a_list_of_everything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A day with six flights, eight promises due this week, two silent usual sources and nine timed
    entries tomorrow: each part is capped and the whole stays under the limit, the question last."""
    monkeypatch.setattr(gaps, "now", lambda: NOW)
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    day, tomorrow = "2026-06-10", "2026-06-11"
    drafts: list[dict[str, Any]] = []
    for d in range(1, 10):
        drafts += dwell(f"2026-06-{d:02d}", "08:00", "09:00", HOME, every_min=10)
        drafts += dwell(f"2026-06-{d:02d}", "08:00", "09:00", HOME, every_min=10, subject=None)
        drafts.append(
            {
                "at": utc(f"2026-06-{d:02d}", "12:00"),
                "source": "apple-health",
                "kind": "health",
                "tier": 3,
                "payload": {
                    "schema": "health-sample/v1",
                    "type": "steps",
                    "value": 100,
                    "unit": "count",
                    "device": "Watch7,1",
                    "raw_id": f"h-{d}",
                },
            }
        )
    for n in range(6):
        hour = f"{6 + 2 * n:02d}"
        drafts.append(
            {
                "at": utc(day, f"{hour}:00"),
                "end": utc(day, f"{hour}:45"),
                "source": "flighty",
                "kind": "flight",
                "tier": 1,
                "payload": {
                    "schema": "flight/v1",
                    "raw_id": f"fx-{n}",
                    "date": day,
                    "carrier": "XY",
                    "number": str(100 + n),
                    "from": {"iata": "OSL"},
                    "to": {"iata": "ZRH"},
                    "role": "passenger",
                    "evidence": "declared",
                },
            }
        )
    for n in range(8):
        drafts.append(note(utc(day, f"{10 + n}:00"), f"I'll send the file number {n} by tomorrow."))
    for n in range(9):
        drafts.append(
            event(utc(tomorrow, f"{8 + n:02d}:00"), utc(tomorrow, f"{8 + n:02d}:30"), f"Meeting {n}")
        )
    lb.append_many(drafts)
    text = _run(capsys, day)
    lines = text.splitlines()
    assert len(lines) <= digest.LIMIT, text
    assert lines[-1].endswith("?") and lines[-2] == ""
    shown = sum(line.startswith("  flight") for line in lines)
    assert shown == digest.FLIGHTS_SHOWN + 1, "N shown, then `+N more`"
    assert sum(line.startswith("  due") for line in lines) == digest.PROMISES_SHOWN + 1
    assert sum(line.startswith("  tomorrow") for line in lines) == digest.TOMORROW_SHOWN + 1
    assert "+3 more flights" in text and "+5 more due this week" in text and "+6 more entries" in text
    assert "Meeting 8" not in text and "file number 7" not in text
    data = _json(capsys, day)
    assert len(data["flights"]) == 6 and len(data["promises"]["open"]) == 8, "the JSON holds the whole sets"
    assert len(data["tomorrow"]["entries"]) == 9 and data["lines"] == len(lines)
    assert data["gaps"]["missing"] == ["apple-health", "dawarich"]
    markdown = _run(capsys, day, "--markdown")
    assert len(markdown.splitlines()) <= digest.LIMIT
    assert markdown.splitlines()[0] == "## Wednesday 10 June 2026" and markdown.rstrip().endswith("?**")
    assert digest.fit(["head", *["x"] * 40, "", "Q?"]) == ["head", *["x"] * (digest.LIMIT - 4), "…", "", "Q?"]


# -- the command --------------------------------------------------------------------------------------


def test_the_command_refuses_a_day_that_is_not_one_or_has_not_come(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as e:
        cli.main(["digest", "2026-13-01"])
    assert e.value.code == 2 and "not a date" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["digest", "2026-06-23"])
    assert e.value.code == 2 and "after today" in capsys.readouterr().err
    with pytest.raises(SystemExit) as e:
        cli.main(["digest", "2026-06-10", "--json", "--markdown"])
    assert e.value.code == 2


def test_today_is_the_default_and_markdown_is_the_same_lines(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(day_commands, "_today", lambda: "2026-06-13")
    text = _run(capsys)
    assert text.splitlines()[0] == "2026-06-13  Saturday"
    markdown = _run(capsys, "2026-06-13", "--markdown")
    lines = markdown.splitlines()
    assert lines[0] == "## Saturday 13 June 2026"
    assert lines[1].startswith("- **where** ") and "aboard Solvind" in lines[1]
    assert lines[2] == "- **with** Ola Nordmann"
    assert lines[3].startswith("- **attached** ") and "1 note" in lines[3]
    assert lines[-1] == f"**{text.splitlines()[-1]}**" and lines[-2] == "", "the same question, in bold"
    assert len(lines) == len(text.splitlines()), "the Markdown is the text's lines, one for one"
