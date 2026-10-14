"""The readers never take an agent for a person: `people`, `person`, `people review`, the company of a
stay and the dream's material pass machine text and agent counterparts over, and `promises` reads
only the owner's own words in a conversation with an agent. The record holds the persona's Telegram
export (`telegram_persona`), her Claude Code sessions (`claude_sessions`), her conversations in the
Claude apps (`claude_conversations`), and a bot she named after her sister Kari, who is also a person
of the record. Nobody here exists."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import claude_conversations as cc
import claude_sessions as cs
import pytest
import telegram_persona as tp
from duplicates import resolution

from logbook.contrib import dream, people_review
from logbook.contrib import promises as promise_reader
from logbook.contrib.adapters import claude_code, claude_export, telegram
from logbook.core import machine, people, policy, present, resolve, stays
from logbook.core.store import Logbook

KARI = {"id": "019cadd3-6bc0-7dcd-9133-000000000201", "name": "Kari Nordmann", "phone": "+447700900124"}
KARI_BOT_ID = 900000003
KARI_BOT = [  # a bot the owner named after her sister: it is still a bot
    tp.message(
        801, 90, KARI_BOT_ID, "Kari Nordmann", "Kari's birthday is on Friday; I'll remind you on Thursday."
    ),
    tp.message(802, 91, tp.OWNER_ID, "Ines Nordmann", "Thanks, I'll buy the present on Wednesday."),
]


def _from_kari(minutes: float, text: str) -> dict[str, Any]:
    """A message from the real Kari, by her number: the evidence that makes her a person here."""
    return {
        "at": tp.at(minutes),
        "source": "whatsapp",
        "kind": "message",
        "tier": 2,
        "payload": {
            "schema": "message/v1",
            "raw_id": f"wa-kari-{minutes}",
            "chat": {"id": "447700900124@s.whatsapp.net", "type": "direct", "name": "Kari"},
            "from_me": False,
            "sender": {"kind": "phone", "value": KARI["phone"], "name": "Kari Nordmann"},
            "text": text,
        },
    }


def _named_machine(at: str, end: str) -> dict[str, Any]:
    """A session whose machine participant carries a person's name: still nobody's company."""
    return {
        "at": at,
        "end": end,
        "source": "claude-code",
        "kind": "transcript",
        "tier": 2,
        "payload": {
            "schema": "transcript/v1",
            "provider": "claude-code",
            "raw_id": "claude-code:named-machine",
            "participants": [{"name": "owner"}, {"name": "Kari Nordmann", "machine": True}],
        },
    }


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    chats = [
        {"name": "Nordlys", "type": "bot_chat", "id": tp.NORDLYS_ID, "messages": tp.NORDLYS_MESSAGES},
        {"name": "Fjordvakt", "type": "bot_chat", "id": tp.FJORDVAKT_ID, "messages": tp.FJORDVAKT_MESSAGES},
        {"name": "Kari Nordmann", "type": "bot_chat", "id": KARI_BOT_ID, "messages": KARI_BOT},
    ]
    export = tp.export(tmp_path / "export", tp.document(chats))
    lb.append_many([resolution("ios-contacts", ("phone", KARI["phone"]), KARI["id"], KARI["name"])])
    lb.append_many(telegram.run(export, timezone="Europe/Oslo"))
    lb.append_many(claude_code.run(cs.projects(tmp_path / "projects"), store=lb.attach))
    lb.append_many(claude_export.run(cc.zipped(tmp_path / "claude-export.zip"), store=lb.attach))
    lb.append_many([_from_kari(100, "See you at the harbour"), _named_machine(tp.at(120), tp.at(150))])
    return lb


# -- people and person ---------------------------------------------------------------------------------


def test_people_counts_the_real_kari_and_never_the_bot_named_after_her(lb: Logbook):
    report = people.read(lb, "2026-03-01", "2026-03-02")
    (kari,) = [p for p in report.people if p.entity == KARI["id"]]
    assert kari.channels["messages"].lines == 1  # her own message; not the bot's, not the owner's to it
    assert "transcripts" not in kari.channels or kari.channels["transcripts"].lines == 0


def test_people_has_nobody_but_kari(lb: Logbook):
    report = people.read(lb, "2026-03-01", "2026-03-02")
    assert [p.entity for p in report.people] == [KARI["id"]]


# -- people review -------------------------------------------------------------------------------------


def test_people_review_never_proposes_a_bot_or_the_assistant_as_a_person(lb: Logbook):
    report = people_review.read(lb)
    assert report.proposals == []
    observed = [o.name for o in report.unplaced]
    assert all(
        name not in ("Kari Nordmann", "Nordlys", "Fjordvakt", "assistant", "owner", "Claude")
        for name in observed
    )


def test_the_observed_table_holds_no_agent(lb: Logbook):
    found = people_review.observed(lb)
    keys = {o.key for o in found}
    assert ("phone", KARI["phone"]) in keys
    assert all(not ref[1].startswith("telegram:") for o in found for ref in o.identifiers)
    assert all("assistant" not in o.labels and "owner" not in o.labels for o in found)


def test_messages_by_direction_count_no_conversation_with_an_agent(lb: Logbook):
    report = people.read(lb, "2026-03-01", "2026-03-02")
    them, mine = people_review.messages_by_direction(lb, report, "2026-03-01", "2026-03-02")
    assert them == {KARI["id"]: 1} and mine == {}


# -- the company of a stay -----------------------------------------------------------------------------


def test_a_machine_participant_is_nobodys_company_whatever_its_name(lb: Logbook):
    with lb.index() as idx:
        identities = resolve.identities_from(idx.resolutions())
        lines = [
            t for t in idx.by_kind("transcript") if t["payload"]["raw_id"] == "claude-code:named-machine"
        ]
    stay = stays.Segment(
        "stay",
        None,
        datetime.fromisoformat(tp.at(110).replace("Z", "+00:00")),
        datetime.fromisoformat(tp.at(160).replace("Z", "+00:00")),
        12,
        lat=59.91,
        lon=10.75,
    )
    assert present.from_transcript(stay, lines, identities) == []
    person = {**lines[0], "payload": {**lines[0]["payload"], "participants": [{"name": "Kari Nordmann"}]}}
    (presence,) = present.from_transcript(stay, [person], identities)  # the same name, not a machine
    assert presence.person == KARI["id"]


# -- promises ------------------------------------------------------------------------------------------


def test_promises_reads_only_the_owners_words_in_a_conversation_with_an_agent(lb: Logbook):
    report = promise_reader.extract(lb)
    quotes = {p.quote for p in (proposal.match for proposal in report.proposals)}
    owner_promises = {
        "I will check the anchor chain tomorrow",  # to Nordlys
        "Thanks, I'll double the mooring lines",  # to Fjordvakt
        "Thanks, I'll buy the present on Wednesday.",  # to the bot named Kari
        "I'll test it on Saturday.",  # in the Claude Code session
        "I will send the harbour list tomorrow.",
        "I'll leave the harbour at nine on Saturday.",  # in a conversation in the Claude apps
        "I will send the tide table tomorrow.",
    }
    assert owner_promises <= quotes
    machine_words = {
        "I'll have the passage plan ready by Friday.",
        "Can you send me the tide table?",
        "Kari's birthday is on Friday; I'll remind you on Thursday.",
        "I'll start with the tide tables.",
        "Can you send me the harbour list?",
        "I'll bring the charts on Friday",  # forwarded: Ola's words, not the owner's
        "I'll draft the plan by Friday.",  # the assistant's, in the Claude apps
    }
    assert not machine_words & quotes
    for proposal in report.proposals:
        if proposal.source in ("telegram", "claude-code", "claude"):
            assert proposal.speaker is not None and proposal.speaker.owner, proposal.match.quote
            assert proposal.role == promise_reader.PROMISE


def test_promises_counts_what_it_left_out_as_an_agents(lb: Logbook):
    report = promise_reader.extract(lb)
    assert report.skipped["messages_by_an_agent"] == 4  # the bots' four lines, one of them a document
    assert report.skipped["forwarded_messages"] == 1
    text = promise_reader.rows(report, report.proposals, lambda at: at)
    assert "  4 messages an agent wrote skipped: an agent's words are nobody's promise" in text
    assert "  1 forwarded message skipped: someone else's words" in text


# -- the dream's material ------------------------------------------------------------------------------


def test_the_dream_marks_an_agents_words_as_machine_text(lb: Logbook):
    with lb.index() as idx:
        lines = [m for m in idx.by_kind("message") if m["source"] == "telegram"]
    made = dream.Material("2026-03-01", 2, len(lines), "", "", "en", {}, ids={str(m["id"]) for m in lines})
    entries = {e["counterpart"]: e for e in dream._messages(lines, {}, made)}
    nordlys = entries["Nordlys"]
    assert nordlys["agent"] is True
    texts = {t["text"]: t for t in nordlys["texts"]}
    assert texts["Plan the passage to Drøbak for Saturday, and remind me to call Ola"]["from_me"] is True
    assert "machine" not in texts["Plan the passage to Drøbak for Saturday, and remind me to call Ola"]
    bot = texts["I'll have the passage plan ready by Friday. Can you send me the tide table?"]
    assert bot["machine"] is True and bot["from_me"] is False
    assert entries["Kari Nordmann"]["agent"] is True


def test_the_days_language_is_the_owners_not_the_agents(lb: Logbook):
    with lb.index() as idx:
        lines = list(idx.by_kind("message"))
    texts = dream._texts(lines)
    assert all(
        not machine.is_machine(line["payload"]) or line["payload"].get("text") not in texts for line in lines
    )


def test_the_dream_sees_a_conversation_in_the_apps_as_it_sees_a_claude_code_session(lb: Logbook):
    ceiling = policy.Ceiling("dream", 2, None, False)
    session_day = dream.material(lb, "2026-03-01", ceiling).data
    apps_day = dream.material(lb, "2026-03-02", ceiling).data
    (session,) = [u for u in session_day["unplaced"] if u.get("title") == "Passage planner for Solvind"]
    (conversation,) = [u for u in apps_day["unplaced"] if u.get("title") == "Passage to Drøbak"]
    assert session["kind"] == conversation["kind"] == "transcript" and set(session) == set(conversation)
    seen = json.dumps(apps_day, ensure_ascii=False)
    for words in (cc.OWNER_FIRST, cc.MACHINE_FIRST, cc.MACHINE_SECOND, "Claude", "assistant"):
        assert words not in seen, words
