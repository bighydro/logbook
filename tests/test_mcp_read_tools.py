"""`logbook mcp`'s `day_lines`, `line` and `digest`: three read tools behind the crossing ceiling of
`policy/crossing.json` for the `mcp` destination (ADR 0016), driven through the SDK's in-process client
as `tests/test_mcp.py` drives the others. The record is three synthetic days of the Oslo persona (Ines
Nordmann, who does not exist) with lines at tiers 1, 2 and 3 across location, calendar, note, mail,
message, transcript and health; every address is at example.org."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from persona import HOME, KARI, KARI_ID, OLA, OLA_ID, TZ, attendee, event, note, point, resolution, utc
from test_mcp import _call, _policy

from logbook import cli
from logbook.core import attachments
from logbook.core.store import Logbook

pytest.importorskip("mcp")

INES = "ines@example.org"
DAY_A, DAY_B, DAY_C = "2026-06-08", "2026-06-09", "2026-06-10"  # a Monday, Tuesday and Wednesday
WEEK = [f"2026-06-{d:02d}" for d in range(8, 15)]  # the ISO week of the three days, Monday to Sunday

BUDGET_CALL = (
    "Ola Nordmann: Could you send the slides to Kari after this?\n"
    "Ines: Sure. I'll write up the minutes tonight.\n"
)
YARD_CALL = "Ola Nordmann: The yard quoted two prices.\nInes: I will book the crane for Tuesday.\n"
PHOTOS_NOTE = "Long day. I'll send Ola the mooring photos by Friday."
PUMP_NOTE = "Fixed the bilge pump."
BERTH_MAIL = "Can you send me the berth number before Friday?"
LUNCH_TEXT = "Lunch tomorrow?"

# what each line says, which an answer that left the line out must never carry
SECRETS = {
    "a_transcript": ("Budget call", "slides", "minutes"),
    "a_note": (PHOTOS_NOTE,),
    "b_mail": ("Berth number", BERTH_MAIL),
    "b_message": (LUNCH_TEXT,),
    "b_health": ("resting_hr", "count/min"),
    "c_transcript": ("Yard call", "crane", "two prices"),
    "c_note": (PUMP_NOTE,),
}
DAY_KEYS = {
    DAY_A: ["a_point", "a_event", "a_transcript", "a_note"],  # tiers 1, 1, 3, 2, in time order
    DAY_B: ["b_point", "b_mail", "b_message", "b_health"],  # tiers 1, 2, 2, 3
    DAY_C: ["c_point", "c_transcript", "c_note"],  # tiers 1, 3, 2
}
TIERS = {
    "a_point": 1, "a_event": 1, "a_transcript": 3, "a_note": 2,
    "b_point": 1, "b_mail": 2, "b_message": 2, "b_health": 3,
    "c_point": 1, "c_transcript": 3, "c_note": 2,
}  # fmt: skip


def _transcript(lb: Logbook, at: str, end: str, title: str, text: str) -> dict[str, Any]:
    """A transcript/v1 line at tier 3, as the reference adapters write it, its text in the store."""
    blob = text.encode("utf-8")
    lb.attach(blob)
    return {
        "at": at,
        "end": end,
        "source": "granola",
        "kind": "transcript",
        "tier": 3,
        "payload": {
            "schema": "transcript/v1",
            "provider": "granola",
            "raw_id": f"t-{at}",
            "title": title,
            "participants": [
                {"name": "Ola Nordmann", "email": OLA["email"]},
                {"name": "Ines Nordmann", "email": INES},
            ],
            "content": attachments.reference(blob, "text/plain"),
        },
    }


def _mail(at: str, subject: str, body: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "mail",
        "kind": "mail",
        "tier": 2,
        "payload": {
            "schema": "mail/v1",
            "raw_id": f"{INES}:{at}@mail.example.org",
            "message_id": f"{at}@mail.example.org",
            "thread": f"{at}@mail.example.org",
            "from": {"email": OLA["email"], "name": "Ola Nordmann"},
            "to": [{"email": INES, "name": "Ines Nordmann"}],
            "subject": subject,
            "direction": "received",
            "body": body,
            "size": 1000 + len(body),
        },
    }


def _message(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "imessage",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "raw_id": f"imessage-{at}",
            "chat": {"id": KARI["phone"], "type": "direct", "name": "Kari"},
            "from_me": False,
            "sender": {"kind": "phone", "value": KARI["phone"], "name": "Kari"},
            "text": text,
        },
    }


def _health(at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "apple-health",
        "kind": "health",
        "tier": 3,
        "payload": {
            "schema": "health-sample/v1",
            "raw_id": f"resting_hr:{at}",
            "type": "resting_hr",
            "value": 52,
            "unit": "count/min",
            "device": "watch",
        },
    }


def _drafts(lb: Logbook) -> dict[str, dict[str, Any]]:
    """The record's lines by a short key, in chain order: three resolutions (tier 2), then the
    three days."""
    return {
        "kari": resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        "kari_phone": resolution(("phone", KARI["phone"]), KARI_ID, "Kari Nordmann"),
        "ola": resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        "a_point": point(utc(DAY_A, "08:00"), HOME),
        "a_event": event(utc(DAY_A, "10:00"), utc(DAY_A, "11:00"), "Planning", [attendee(KARI["email"])]),
        "a_transcript": _transcript(lb, utc(DAY_A, "13:00"), utc(DAY_A, "13:30"), "Budget call", BUDGET_CALL),
        "a_note": note(utc(DAY_A, "19:00"), PHOTOS_NOTE),
        "b_point": point(utc(DAY_B, "08:00"), HOME),
        "b_mail": _mail(utc(DAY_B, "09:00"), "Berth number", BERTH_MAIL),
        "b_message": _message(utc(DAY_B, "12:00"), LUNCH_TEXT),
        "b_health": _health(utc(DAY_B, "22:00")),
        "c_point": point(utc(DAY_C, "08:00"), HOME),
        "c_transcript": _transcript(lb, utc(DAY_C, "15:00"), utc(DAY_C, "15:20"), "Yard call", YARD_CALL),
        "c_note": note(utc(DAY_C, "18:00"), PUMP_NOTE),
    }


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, dict[str, Any]]:
    """The record and its lines by key."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    drafts = _drafts(lb)
    lb.append_many(list(drafts.values()))
    lines = list(lb.lines())[-len(drafts) :]
    return lb, dict(zip(drafts, lines, strict=True))


def _filtered_copy(tmp_path: Path, ceiling: int) -> Logbook:
    """A second record holding only the lines at or below `ceiling`: what the gate makes the readers
    see, as a record of its own, for the command line to read."""
    lb = Logbook.init(tmp_path / f"below-{ceiling}", TZ)
    lb.append_many([draft for draft in _drafts(lb).values() if int(draft["tier"]) <= ceiling])
    return lb


def _allowed(ceiling: int, day: str) -> list[str]:
    return [key for key in DAY_KEYS[day] if TIERS[key] <= ceiling]


def _no_secret_of(keys: set[str], text: str) -> None:
    for key in keys:
        for secret in SECRETS.get(key, ()):
            assert secret not in text, f"{key} leaked through: {secret!r}"


# -- day_lines ----------------------------------------------------------------------------------------


@pytest.mark.parametrize("ceiling", [1, 2, 3])
def test_day_lines_returns_exactly_the_lines_the_ceiling_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ceiling: int
):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, ceiling)
    for day, keys in DAY_KEYS.items():
        allowed = _allowed(ceiling, day)
        out = _call(lb, "day_lines", {"day": day}, allow_tier_3=True)
        data = out["data"]
        assert out["gate"]["max_tier"] == ceiling
        assert data["day"] == day and data["tz"] == TZ
        assert [row["id"] for row in data["lines"]] == [lines[k]["id"] for k in allowed]
        assert data["above_ceiling"] == len(keys) - len(allowed)
        assert data["count"] == len(allowed)
        text = json.dumps(out, ensure_ascii=False)
        omitted = set(keys) - set(allowed)
        for key in omitted:
            assert lines[key]["id"] not in text, f"the id of {key} leaked"
        _no_secret_of(omitted, text)
        for row in data["lines"]:
            assert set(row) >= {
                "id",
                "seq",
                "at",
                "time",
                "kind",
                "profile",
                "source",
                "tier",
                "counterpart",
                "text",
            }
            assert row["tier"] <= ceiling


def test_day_lines_rows_read_as_the_show_reader_prints_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    rows = {row["kind"]: row for row in _call(lb, "day_lines", {"day": DAY_B})["data"]["lines"]}
    mail, message, where = rows["mail"], rows["message"], rows["location"]
    assert mail["time"] == "09:00" and mail["profile"] == "mail/v1" and mail["id"] == lines["b_mail"]["id"]
    assert mail["counterpart"] == "Ola Nordmann", "the resolution line names the sender"
    assert mail["text"].startswith("✉ Berth number — Ola Nordmann")
    assert BERTH_MAIL not in mail["text"], "the row is the summary; `line` has the body"
    assert message["counterpart"] == "Kari Nordmann" and message["text"] == f"Kari Nordmann: {LUNCH_TEXT}"
    assert where["counterpart"] is None and where["profile"] == "location/v1" and where["time"] == "08:00"
    rows = {row["kind"]: row for row in _call(lb, "day_lines", {"day": DAY_A})["data"]["lines"]}
    assert (
        rows["event"]["counterpart"] == "Kari Nordmann"
        and rows["event"]["text"] == "Planning · with Kari Nordmann"
    )
    assert rows["note"]["text"] == PHOTOS_NOTE and rows["note"]["counterpart"] is None
    _policy(lb, 1)
    rows = {row["kind"]: row for row in _call(lb, "day_lines", {"day": DAY_A})["data"]["lines"]}
    assert rows["event"]["counterpart"] == KARI["email"], "no resolution line crosses at 1: the ref as given"


def test_day_lines_filters_by_profile_family(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    data = _call(lb, "day_lines", {"day": DAY_B, "kinds": ["mail", "message"]})["data"]
    assert [row["id"] for row in data["lines"]] == [lines["b_mail"]["id"], lines["b_message"]["id"]]
    assert data["above_ceiling"] == 0, "the tier-3 health sample is in no family asked for"
    assert data["kinds"] == ["mail", "message"]
    data = _call(lb, "day_lines", {"day": DAY_B, "kinds": ["location"]})["data"]
    assert [row["id"] for row in data["lines"]] == [lines["b_point"]["id"]]
    data = _call(lb, "day_lines", {"day": DAY_A, "kinds": ["calendar", "transcript"]})["data"]
    assert [row["id"] for row in data["lines"]] == [lines["a_event"]["id"]]
    assert data["above_ceiling"] == 1
    _policy(lb, 1)
    data = _call(lb, "day_lines", {"day": DAY_B, "kinds": ["mail", "message"]})["data"]
    assert data["lines"] == [] and data["above_ceiling"] == 2
    assert "kinds" in _call(lb, "day_lines", {"day": DAY_B, "kinds": ["health"]})["error"]
    assert "kinds" in _call(lb, "day_lines", {"day": DAY_B, "kinds": []})["error"]
    assert "not a date" in _call(lb, "day_lines", {"day": "yesterday"})["error"]


def test_day_lines_leaves_a_retracted_line_out_and_counts_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    lb.retract(int(lines["c_note"]["seq"]), "a slip")
    data = _call(lb, "day_lines", {"day": DAY_C})["data"]
    assert [row["id"] for row in data["lines"]] == [lines["c_point"]["id"]]
    assert data["retracted"] == 1 and data["above_ceiling"] == 1
    assert PUMP_NOTE not in json.dumps(data) and "a slip" not in json.dumps(data)


# -- line ---------------------------------------------------------------------------------------------


def test_line_refuses_a_transcript_above_the_ceiling_naming_the_tier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb, lines = _record(tmp_path, monkeypatch)
    id_ = lines["a_transcript"]["id"]
    _policy(lb, 2)
    out = _call(lb, "line", {"id": id_}, allow_tier_3=True)
    assert "tier 3" in out["error"] and "ceiling" in out["error"] and id_ in out["error"]
    _no_secret_of({"a_transcript"}, out["error"])
    assert "transcript" not in out["error"], "the refusal names the tier, nothing else of the line"
    _policy(lb, 3)
    out = _call(lb, "line", {"id": id_})  # the policy allows 3; the server was not started with the flag
    assert "tier 3" in out["error"] and "ceiling of 2" in out["error"]
    _no_secret_of({"a_transcript"}, out["error"])
    _policy(lb, 1)
    out = _call(lb, "line", {"id": lines["a_note"]["id"]})
    assert "tier 2" in out["error"] and PHOTOS_NOTE not in out["error"]


def test_line_returns_the_transcript_text_when_the_ceiling_allows_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 3)
    out = _call(lb, "line", {"id": lines["a_transcript"]["id"]}, allow_tier_3=True)
    data = out["data"]
    assert out["gate"]["max_tier"] == 3
    assert data["id"] == lines["a_transcript"]["id"] and data["kind"] == "transcript"
    assert data["profile"] == "transcript/v1" and data["tier"] == 3 and data["time"] == "13:00"
    assert data["row"].startswith("Budget call — Ola Nordmann, Ines Nordmann")
    assert data["text"] == BUDGET_CALL.rstrip("\n"), (
        "the text from the attachment store, as `promises` reads it"
    )
    assert data["payload"]["title"] == "Budget call" and data["counterpart"] == "Ola Nordmann, Ines Nordmann"
    assert "hash" not in data and "prev" not in data

    _policy(lb, 2)
    data = _call(lb, "line", {"id": lines["b_mail"]["id"]})["data"]
    assert data["row"].startswith("✉ Berth number") and data["text"] == BERTH_MAIL
    assert data["payload"]["body"] == BERTH_MAIL
    data = _call(lb, "line", {"id": lines["a_note"]["id"]})["data"]
    assert data["text"] == PHOTOS_NOTE and data["row"] == PHOTOS_NOTE
    data = _call(lb, "line", {"id": lines["b_message"]["id"]})["data"]
    assert data["text"] == LUNCH_TEXT and data["counterpart"] == "Kari Nordmann"
    data = _call(lb, "line", {"id": lines["a_point"]["id"]})["data"]
    assert data["text"] is None and data["payload"]["lat"] == HOME[0]


def test_line_of_a_transcript_whose_text_is_not_in_the_store_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 3)
    sha256 = lines["c_transcript"]["payload"]["content"]["sha256"]
    (lb.root / "attachments" / sha256).unlink()
    data = _call(lb, "line", {"id": lines["c_transcript"]["id"]}, allow_tier_3=True)["data"]
    assert data["text"] is None and data["payload"]["title"] == "Yard call"


def test_line_of_an_unknown_id_or_a_retracted_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    assert "no line" in _call(lb, "line", {"id": "019cadd3-6bc0-7dcd-9133-ffffffffffff"})["error"]
    assert "id" in _call(lb, "line", {"id": "   "})["error"]
    mark = lb.retract(int(lines["c_note"]["seq"]), "a slip")
    data = _call(lb, "line", {"id": lines["c_note"]["id"]})["data"]
    assert data["retracted"] == {"seq": mark["seq"], "reason": "a slip"}
    assert data["row"] == f"retracted #{lines['c_note']['seq']}: a slip"
    assert "payload" not in data and "text" not in data and PUMP_NOTE not in json.dumps(data)
    assert "retraction" in _call(lb, "line", {"id": mark["id"]})["error"]


# -- digest -------------------------------------------------------------------------------------------


def _cli_digest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], lb: Logbook, day: str
) -> str:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    cli.main(["digest", day])
    return capsys.readouterr().out


def _forget_questions(lb: Logbook) -> None:
    """The digest remembers what it asked; both records start from nothing asked."""
    state = lb.root / "state" / "questions.json"
    if state.exists():
        state.unlink()


@pytest.mark.parametrize("ceiling", [1, 2, 3])
def test_digest_matches_the_command_line_at_the_same_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], ceiling: int
):
    lb, _lines = _record(tmp_path, monkeypatch)
    _policy(lb, ceiling)
    below = _filtered_copy(tmp_path, ceiling)
    for day in (DAY_A, DAY_B, DAY_C):
        _forget_questions(lb)
        _forget_questions(below)
        out = _call(lb, "digest", {"period": "day", "date": day}, allow_tier_3=True)
        data = out["data"]
        assert out["gate"]["max_tier"] == ceiling
        assert data["period"] == "day" and data["day"] == day and data["days"] == [day]
        expected = _cli_digest(monkeypatch, capsys, below, day)
        assert data["text"].splitlines() == expected.splitlines()
        assert data["lines"] == len(expected.splitlines())
        omitted = {key for key in DAY_KEYS[day] if TIERS[key] > ceiling}
        _no_secret_of(omitted, json.dumps(out, ensure_ascii=False))
    text = _call(lb, "digest", {"date": DAY_A})["data"]["text"]
    assert ("mooring photos" in text) == (ceiling >= 2), "the promise due is in the tier-2 note"


def test_digest_of_a_week_is_the_seven_days_as_the_command_prints_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    lb, _lines = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    below = _filtered_copy(tmp_path, 2)
    _forget_questions(lb)
    data = _call(lb, "digest", {"period": "week", "date": DAY_B})["data"]
    assert data["period"] == "week" and data["week"] == "2026-W24" and data["days"] == WEEK
    expected = "\n\n".join(_cli_digest(monkeypatch, capsys, below, day).rstrip("\n") for day in WEEK)
    assert data["text"] == expected
    assert data["lines"] == len(expected.splitlines())
    assert "period" in _call(lb, "digest", {"period": "month", "date": DAY_B})["error"]
    assert "not a date" in _call(lb, "digest", {"date": "2026-W24"})["error"]
    assert "after today" in _call(lb, "digest", {"date": "2999-01-01"})["error"]


# -- the ceiling's default ----------------------------------------------------------------------------


def test_a_missing_or_silent_policy_is_a_ceiling_of_1_and_a_broken_one_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb, lines = _record(tmp_path, monkeypatch)
    path = lb.root / "policy" / "crossing.json"
    path.unlink()
    out = _call(lb, "day_lines", {"day": DAY_A}, allow_tier_3=True)
    assert out["gate"]["max_tier"] == 1 and out["data"]["above_ceiling"] == 2
    assert "tier 2" in _call(lb, "line", {"id": lines["a_note"]["id"]}, allow_tier_3=True)["error"]
    _policy(lb, None)  # a file that names other destinations and not mcp
    out = _call(lb, "day_lines", {"day": DAY_A}, allow_tier_3=True)
    assert out["gate"]["max_tier"] == 1 and out["data"]["above_ceiling"] == 2
    for broken in ("{not json", '{"mcp": {"max_tier": 9}}', '{"mcp": "all"}'):
        path.write_text(broken, encoding="utf-8")
        for name, arguments in (
            ("day_lines", {"day": DAY_A}),
            ("line", {"id": lines["a_note"]["id"]}),
            ("digest", {"date": DAY_A}),
        ):
            out = _call(lb, name, arguments, allow_tier_3=True)
            assert "crossing.json" in out["error"], (broken, name)
            _no_secret_of(set(SECRETS), out["error"])


# -- the log ------------------------------------------------------------------------------------------


def test_every_call_logs_one_line_of_counts_and_never_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    lb, lines = _record(tmp_path, monkeypatch)
    _policy(lb, 2)
    caplog.set_level(logging.INFO, logger="logbook.mcp")
    _call(lb, "day_lines", {"day": DAY_B, "kinds": ["mail", "message"]})
    _call(lb, "line", {"id": lines["b_mail"]["id"]})
    _call(lb, "digest", {"period": "day", "date": DAY_A})
    _call(lb, "search", {"text": BERTH_MAIL})
    _call(lb, "line", {"id": lines["a_transcript"]["id"]})  # refused: logged all the same
    records = [r for r in caplog.records if r.name == "logbook.mcp"]
    assert len(records) == 5
    messages = [r.getMessage() for r in records]
    assert messages[0].startswith("day_lines ") and f"day={DAY_B}" in messages[0]
    assert "count=2" in messages[0] and "above_ceiling=0" in messages[0] and "withheld=" in messages[0]
    assert messages[1].startswith("line ") and f"id={lines['b_mail']['id']}" in messages[1]
    assert messages[2].startswith("digest ") and f"date={DAY_A}" in messages[2] and "lines=" in messages[2]
    assert messages[3].startswith("search ") and "hits=1" in messages[3]
    assert messages[4].startswith("line ") and "refused" in messages[4] and "tier 3" in messages[4]
    joined = "\n".join(messages)
    _no_secret_of(set(SECRETS), joined)
    assert "Ola" not in joined and "Kari" not in joined
