"""With: `logbook with DAY NAME [NAME…] [--at HH:MM]` states who was there when the record could not
see. One `note/v1` line per canonical person, `with <label>`, labelled `with`, the person's id under
`extra.person`: the company the people reader already reads (SPEC §3.2.5 rule 3), no new profile. A
name the record does not place refuses the whole statement with the people-review hint. On the Oslo
persona, who does not exist; Ines is the owner's name in this record."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import KARI_ID, OLA_ID, TZ, persona_record, utc

from logbook import cli
from logbook.core import people, presence
from logbook.core.chain import Line
from logbook.core.store import Logbook

CLOCK = ("id", "seq", "prev", "hash", "recorded_at")
ROW = "\n  with" + " " * 10  # the Day's header row, at the margin (an entry's rows are indented)
FRIDAY = "2026-06-12"  # an office day: 08:10 to 17:50 at the office, home before and after


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    with pytest.MonkeyPatch.context() as mp:
        root = persona_record(tmp_path_factory.mktemp("with"), mp).root
    (root / "policy").mkdir(exist_ok=True)
    (root / "policy" / "owner.json").write_text(
        json.dumps({"names": ["Ines Nordmann"], "emails": [], "phones": []}), encoding="utf-8"
    )
    return root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main([*args])
    return capsys.readouterr().out


def _refused(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    with pytest.raises(SystemExit) as stop:
        cli.main([*args])
    assert stop.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    return captured.err


def _stated(lb: Logbook) -> list[Line]:
    return [
        line
        for line in lb.lines()
        if line["kind"] == "note" and "with" in (line["payload"].get("labels") or [])
    ]


def _content(line: Line) -> dict[str, Any]:
    return {k: v for k, v in line.items() if k not in CLOCK}


def test_with_writes_one_note_per_person_byte_for_byte(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    out = _run(capsys, "with", FRIDAY, "Ola", "kari nordmann", "--at", "12:00")
    ola, kari = _stated(lb)
    assert lb.meta["seq"] == seq + 2
    for line, name, entity in ((ola, "Ola Nordmann", OLA_ID), (kari, "Kari Nordmann", KARI_ID)):
        assert _content(line) == {
            "at": utc(FRIDAY, "12:00"),
            "end": None,
            "tz": TZ,
            "source": "manual",
            "kind": "note",
            "tier": 2,
            "payload": {
                "schema": "note/v1",
                "text": f"with {name}",
                "labels": ["with"],
                "extra": {"person": entity},
            },
        }
    assert out.splitlines() == [
        f"#{ola['seq']} with Ola Nordmann  {FRIDAY} 12:00",
        f"#{kari['seq']} with Kari Nordmann  {FRIDAY} 12:00",
    ]
    assert lb.verify()[2] == []


def test_a_name_is_what_people_name_opens_and_two_names_for_one_person_are_one_line(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "with", FRIDAY, "ola@example.org", "Ola Nordmann", OLA_ID, "--at", "19:00")
    [line] = _stated(lb)
    assert line["payload"]["extra"] == {"person": OLA_ID} and line["payload"]["text"] == "with Ola Nordmann"


def test_a_name_the_record_does_not_place_refuses_the_whole_statement_with_the_hint(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = lb.meta["seq"]
    nobody = _refused(capsys, "with", FRIDAY, "Ola", "Per")
    assert "'Per' is nobody the record's resolution lines name" in nobody
    assert "nothing was written" in nobody and "logbook people review" in nobody and "people merge" in nobody
    several = _refused(capsys, "with", FRIDAY, "Nordmann")
    assert "names several people: Kari Nordmann, Ola Nordmann" in several and "people review" in several
    assert "is you" in _refused(capsys, "with", FRIDAY, "Ines Nordmann")
    assert lb.meta["seq"] == seq and _stated(lb) == []


def test_without_a_clock_a_past_day_is_stated_at_noon_and_today_now(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "with", FRIDAY, "Kari")
    [noon] = _stated(lb)
    assert noon["at"] == utc(FRIDAY, "12:00")
    now = datetime(2026, 6, 13, 9, 41, 7, tzinfo=UTC)
    [item] = presence.state(Logbook(lb.root), "2026-06-13", ["Ola"], now=now)
    assert item.line is not None and item.line["at"] == "2026-06-13T09:41:07Z"


def test_a_day_or_a_clock_still_to_come_is_refused(lb: Logbook) -> None:
    now = datetime(2026, 6, 12, 10, 0, tzinfo=UTC)  # 12:00 in Oslo
    with pytest.raises(presence.WithError, match="has not begun"):
        presence.state(lb, "2026-06-13", ["Ola"], now=now)
    with pytest.raises(presence.WithError, match="still to come"):
        presence.state(lb, FRIDAY, ["Ola"], at="18:00", now=now)
    with pytest.raises(presence.WithError, match="not a clock"):
        presence.state(lb, FRIDAY, ["Ola"], at="7pm", now=now)
    assert _stated(lb) == []


def test_a_person_stated_on_the_day_is_not_stated_twice(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "with", FRIDAY, "Ola")
    seq = lb.meta["seq"]
    out = _run(capsys, "with", FRIDAY, "Ola")
    assert out == f"Ola Nordmann: stated on {FRIDAY} already; nothing written\n" and lb.meta["seq"] == seq
    _run(capsys, "with", FRIDAY, "Ola", "--at", "19:00")
    assert lb.meta["seq"] == seq + 1, "another clock is another statement"
    assert "already" in _run(capsys, "with", FRIDAY, "Ola", "--at", "19:00")


def test_the_people_reader_counts_the_day_together(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """SPEC §3.2.5 rule 3: a note inside a stay that says `with <label>` confirms the person; at the
    office at noon on Friday, Kari was not seen by any other source."""
    before = people.read(lb, "2026-06-08", "2026-06-21").known[KARI_ID]
    assert FRIDAY not in before.days
    _run(capsys, "with", FRIDAY, "Kari", "--at", "12:00")
    after = people.read(Logbook(lb.root), "2026-06-08", "2026-06-21").known[KARI_ID]
    assert FRIDAY in after.days


def test_the_clock_is_on_the_day_as_the_record_defines_it(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Under `day_start` 06:00 (RFC 0036), 02:00 on Friday is Saturday's calendar date."""
    lb.set_meta(day_start="06:00")
    _run(capsys, "with", FRIDAY, "Ola", "--at", "02:00")
    [line] = _stated(lb)
    assert line["at"] == utc("2026-06-13", "02:00")


def test_the_day_lists_who_the_owner_said_was_there(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    """On a day the owner said who was there, the Day's `with` row is everyone confirmed at a row
    and everyone stated, the owner's word marked; the JSON says who was stated under `stated`. A
    day without the owner's word prints as it did."""
    assert "stated" not in json.loads(_run(capsys, "day", "2026-06-10", "--json"))
    lunch = _run(capsys, "day", "2026-06-10")
    assert ROW not in lunch and "with         Kari Nordmann (calendar, photo)" in lunch
    _run(capsys, "with", FRIDAY, "Kari", "--at", "12:00")
    [line] = _stated(lb)
    data = json.loads(_run(capsys, "day", FRIDAY, "--json"))
    assert data["stated"] == [
        {"person": KARI_ID, "name": "Kari Nordmann", "at": utc(FRIDAY, "12:00"), "line": line["id"]}
    ]
    text = _run(capsys, "day", FRIDAY)
    assert f"{ROW}Kari Nordmann (you said)\n" in text
    assert "with         Kari Nordmann (note)" in text, "and at the stay that holds noon, the office"
    _run(capsys, "with", "2026-06-10", "Ola", "--at", "19:00")
    both = _run(capsys, "day", "2026-06-10")
    assert f"{ROW}Kari Nordmann, Ola Nordmann (you said)\n" in both


def test_a_bot_and_a_github_handle_are_nobody_with_names(
    lb: Logbook, capsys: pytest.CaptureFixture[str]
) -> None:
    """Main's agents and GitHub lines (RFC 0037's observed entities): a Telegram bot the owner talks
    to is machine text, never a person (`logbook.core.machine`), and a GitHub login is a handle ref
    that names a person only through a resolution line. Neither is a name `with` places: each is
    refused with the people-review hint and nothing is written; a `with` note still makes company,
    and `people` lists neither the bot nor the login."""
    bot = {
        "kind": "agent",
        "ref": {"kind": "provider_id", "value": "telegram:900000005"},
        "name": "Skipper Bot",
    }
    for at, mine in ((utc(FRIDAY, "12:05"), True), (utc(FRIDAY, "12:06"), False)):
        extra: dict[str, Any] = {"counterpart": bot, **({} if mine else {"machine": True})}
        lb.append(
            at=at,
            source="telegram",
            kind="message",
            tier=2,
            payload={
                "schema": "message/v1",
                "chat": {"id": "900000005", "type": "direct", "name": "Skipper Bot"},
                "from_me": mine,
                "text": "Wind tomorrow?" if mine else "Northwest, 6 m/s.",
                **(
                    {}
                    if mine
                    else {
                        "sender": {
                            "kind": "provider_id",
                            "value": "telegram:900000005",
                            "name": "Skipper Bot",
                        }
                    }
                ),
                "extra": extra,
            },
        )
    lb.append(
        at=utc(FRIDAY, "12:10"),
        source="github",
        kind="event",
        tier=2,
        payload={
            "schema": "event/v1",
            "raw_id": "commit/0123456789abcdef0123456789abcdef01234567",
            "title": "Fix the mooring chart",
            "start": utc(FRIDAY, "12:10"),
            "end": None,
            "all_day": False,
            "calendar": {"id": "github", "name": "GitHub"},
            "organizer": {"kind": "handle", "value": "github:ola-example"},
            "extra": {"action": "committed", "repo": "example/moorings", "actor": {"login": "ola-example"}},
        },
    )
    seq = Logbook(lb.root).meta["seq"]
    for name in ("Skipper Bot", "github:ola-example", "@ola-example", "ola-example"):
        said = _refused(capsys, "with", FRIDAY, name, "--at", "12:00")
        assert "people review" in said and "nothing was written" in said, (name, said)
    assert Logbook(lb.root).meta["seq"] == seq and _stated(Logbook(lb.root)) == []
    _run(capsys, "with", FRIDAY, "Ola", "--at", "12:00")
    report = people.read(Logbook(lb.root), "2026-06-08", "2026-06-21")
    assert FRIDAY in report.known[OLA_ID].days
    names = {p.name for p in report.known.values()}
    assert names == {"Kari Nordmann", "Ola Nordmann"}, names
    listed = _run(capsys, "people", "--year", "2026")
    assert "Skipper Bot" not in listed and "ola-example" not in listed
