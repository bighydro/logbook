"""A record for the Promises, Goals and Agents shelves (`logbook serve`'s `/promises`, `/goals`,
`/agents`), built the way the commands and the adapters write it. Nobody and nothing here exists: the
owner is Ines Nordmann of Oslo (ines.nordmann@example.org), her brother Ola Nordmann
(ola.nordmann@example.org, 07700 900101) the one person she promises things to.

- **Agents**: the Claude Code sessions of `claude_sessions` (1 and 2 March 2026), the conversations
  of the Claude apps' export of `claude_conversations` (2 and 3 March) and the Telegram bot chats of
  `telegram_persona` (1 March), each through its own `logbook add`; and one more Claude Code session
  imported at tier 3 (`--tier 3`), which a page read through a gate of tiers 1 and 2 never shows.
- **Goals**: a chapter (*The spring at the yard*, from 1 February), three goals imported from a file
  (a life goal, a year goal and a quarter goal, from 1 January), the year goal reworded once (a goal
  whose `supersedes` names it), and reviews: the life goal advancing, the quarter goal stalled and
  then advancing with a note, and one review whose `extra.lines` names the passage-planner session,
  the owner saying that session served the quarter goal.
- **Promises**: notes in the owner's words (`I'll send Ola the harbour map by Friday.`, kept by
  `promises done`; `I will call the yard about the mast on Monday.`, open; `I'll book the ferry for
  Ola.`, dropped by the signed day; `I'll pay Ola for the sails.`, a note at tier 3), a message Ola
  sent asking for the tide table, and a judgement of the local model kept for the open one in
  `policy/promises-cache.json`.

`record(folder, monkeypatch)` writes it and returns the record; `ids(lb)` finds the lines the tests
name."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import claude_conversations as cc
import claude_sessions as cs
import pytest
import telegram_persona as tp

from logbook import cli
from logbook.contrib import promises
from logbook.core import chapter, goals, signing
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
OWNER_EMAIL = "ines.nordmann@example.org"
OLA = {"name": "Ola Nordmann", "email": "ola.nordmann@example.org", "phone": "+447700900101"}
OLA_ID = "019cadd3-6bc0-7dcd-9133-000000000002"
TODAY = "2026-03-20"  # the sitting: after every line below
NOW = datetime(2026, 3, 20, 12, 0, tzinfo=UTC)
GOALS_FILE = (
    "Sail the whole coast to Lofoten | life\n"
    "Finish the passage planner | year\n"
    "Ship the tide clock to the yard | quarter\n"
)
LIFE, YEAR, QUARTER = (
    "Sail the whole coast to Lofoten",
    "Finish the passage planner",
    "Ship the tide clock to the yard",
)
YEAR_REWORDED = "Finish the passage planner and sail with it"
CHAPTER = "The spring at the yard"
STALLED_NOTE = "the yard has not answered"
ADVANCING_NOTE = "the planner carries the tides now"
KEPT = "I'll send Ola the harbour map by Friday."
OPEN = "I will call the yard about the mast on Monday."
DROPPED = "I'll book the ferry for Ola."
SECRET = "I'll pay Ola for the sails by Friday."  # tier 3: never on a page read through tiers 1 and 2
ASKED = "Can you send me the tide table for Saturday?"
HIDDEN_SESSION = "0193c0de-0000-7000-8000-0000000000f3"
HIDDEN_WORDS = "CANARY-tier-three-session-never-on-a-tier-two-page"
JUDGED_MODEL = "synthetic-judge-model"


def _note(at: str, text: str, tier: int = 2) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": tier,
        "payload": {"schema": "note/v1", "text": text},
    }


def _from_ola(at: str, text: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "imessage",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "service": "imessage",
            "chat": {"id": "chat-ola", "type": "direct", "name": OLA["name"]},
            "from_me": False,
            "sender": {"kind": "email", "value": OLA["email"], "name": OLA["name"]},
            "text": text,
        },
    }


def _ola_resolved() -> list[dict[str, Any]]:
    """Ola, resolved from his address and his number."""
    return [
        {
            "at": "2026-02-01T10:00:00Z",
            "source": "manual",
            "kind": "resolution",
            "tier": 2,
            "payload": {
                "schema": "resolution/v1",
                "ref": {"kind": kind, "value": value},
                "entity": {"type": "person", "id": OLA_ID, "registry": "logbook"},
                "label": OLA["name"],
                "method": "owner",
            },
        }
        for kind, value in (("email", OLA["email"]), ("phone", OLA["phone"]))
    ]


def _hidden_session(folder: Path) -> Path:
    """One more Claude Code project, whose one session is imported at tier 3."""
    project = folder / "-Users-ines-code-private"
    cs.write(
        project / f"{HIDDEN_SESSION}.jsonl",
        [
            cs.user(3 * 86400, 1, f"{HIDDEN_WORDS} I'll pay the yard on Monday.", session=HIDDEN_SESSION),
            cs.assistant(3 * 86400 + 30, 2, [cs.text("Noted.")], "msg-h", session=HIDDEN_SESSION),
        ],
    )
    return project


def _clock() -> Iterator[datetime]:
    """The sitting's instants, a minute apart, on `TODAY`."""
    for minute in range(60):
        yield NOW.replace(minute=minute)


def record(folder: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The record of the module's list, under `folder`, found through LOGBOOK_HOME."""
    lb = Logbook.init(folder / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    lb.set_owner_emails([OWNER_EMAIL])
    sources = folder / "sources"
    for argv in (
        ["add", "claude-sessions", str(cs.projects(sources / "projects"))],
        ["add", "claude-export", str(cc.export(sources / "claude-export"))],
        ["add", "telegram-export", str(tp.export(sources / "telegram"))],
        ["add", "claude-sessions", str(_hidden_session(sources / "hidden")), "--tier", "3"],
    ):
        assert cli.main(argv) in (0, None), argv
    lb = Logbook(lb.root)
    lb.append_many(
        [
            *_ola_resolved(),
            _note("2026-03-02T17:00:00Z", KEPT),
            _note("2026-03-03T08:00:00Z", OPEN),
            _note("2026-03-04T08:00:00Z", DROPPED),
            _note("2026-03-05T08:00:00Z", SECRET, tier=3),
            _from_ola("2026-03-04T09:00:00Z", ASKED),
        ]
    )
    clock = _clock()
    with pytest.MonkeyPatch.context() as sitting:  # the owner's sitting, on its own clock
        sitting.setattr(goals, "now", lambda: next(clock))
        chapter.open_chapter(lb, CHAPTER, start="2026-02-01", rules="the yard, the planner, the boat")
        goals.import_goals(lb, GOALS_FILE, start="2026-01-01")
        found = ids(lb)
        goals.add(lb, YEAR_REWORDED, "year", start="2026-01-01", supersedes=found["year"])
        goals.review(lb, found["life"], "advancing", at="2026-03-01")
        goals.review(lb, found["quarter"], "stalled", note=STALLED_NOTE, at="2026-03-01")
        goals.review(lb, found["quarter"], "advancing", note=ADVANCING_NOTE, period="month", at="2026-03-02")
    _served(lb, found["quarter"], found["session"])
    report = promises.extract(lb)
    by_quote = {p.match.quote: p for p in report.proposals}
    kept = by_quote[KEPT]
    lb.append(
        at="2026-03-06T10:00:00Z",
        source="manual",
        kind=promises.TASK,
        tier=promises.TASK_TIER,
        payload=promises.draft_done(kept, "2026-03-06T10:00:00Z", report.extractor),
    )
    signing.sign(
        lb, "2026-03-04", at="2026-03-04T21:00:00Z", dispositions={"dropped": [by_quote[DROPPED].line]}
    )
    judged = by_quote[OPEN]
    cache = {
        "version": 1,
        "judgements": {
            judged.id: {
                "is_commitment": True,
                "by": "owner",
                "to": "unknown",
                "what": "call the yard about the mast",
                "due": "2026-03-09",
                "confidence": 0.9,
                "engine": "synthetic",
                "model": JUDGED_MODEL,
                "judged_at": "2026-03-10T09:00:00Z",
            }
        },
    }
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "promises-cache.json").write_bytes(json.dumps(cache, indent=1).encode("utf-8"))
    return Logbook(lb.root)


def _served(lb: Logbook, goal: str, session: str) -> None:
    """A review of `goal` whose `extra.lines` names `session`: the owner saying it served the goal."""
    lb.append(
        at="2026-03-02T20:00:00Z",
        source=goals.SOURCE,
        kind=goals.REVIEW,
        tier=goals.TIER,
        payload={
            "schema": goals.REVIEW_SCHEMA,
            "goal": goal,
            "disposition": "advancing",
            "period": "day",
            "note": "the planner session",
            "extra": {"lines": [session]},
        },
        recorded_at="2026-03-02T20:00:00Z",
    )


def ids(lb: Logbook) -> dict[str, str]:
    """The lines the tests name, by a short word: the three goals as imported (`life`, `year`,
    `quarter`), the reworded year goal (`reworded`) when written, the passage-planner session
    (`session`), the tier-3 session (`hidden`)."""
    found: dict[str, str] = {}
    with lb.index() as idx:
        for line in idx.by_kind(goals.KIND):
            text = line["payload"]["text"]
            word = {LIFE: "life", YEAR: "year", QUARTER: "quarter", YEAR_REWORDED: "reworded"}.get(text)
            if word is not None:
                found[word] = str(line["id"])
        for line in idx.by_kind("transcript"):
            session = (line["payload"].get("extra") or {}).get("session")
            if session == cs.SESSION:
                found["session"] = str(line["id"])
            elif session == HIDDEN_SESSION:
                found["hidden"] = str(line["id"])
    return found
