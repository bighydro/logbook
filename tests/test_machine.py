"""The machine mark (`logbook.core.machine`): which lines and which transcript turns an agent wrote,
so that no reader takes a bot's or a coding assistant's words for a person's. Synthetic payloads
only: the Oslo persona's own bot, `Nordlys`, and a Claude Code session; nobody here is real."""

from __future__ import annotations

from logbook.core import machine
from logbook.core.transcripts import Turn

BOT = {"kind": "agent", "ref": {"kind": "provider_id", "value": "telegram:900000001"}, "name": "Nordlys"}


def _message(from_me: bool, **extra: object) -> dict[str, object]:
    return {
        "schema": "message/v1",
        "raw_id": "900000001/1772360100/bot/0a1b2c3d4e5f",
        "chat": {"id": "900000001", "type": "direct", "name": "Nordlys"},
        "from_me": from_me,
        "text": "I'll have the passage plan ready by Friday.",
        "extra": dict(extra),
    }


def test_a_message_the_agent_wrote_is_machine_text():
    assert machine.is_machine(_message(False, machine=True, counterpart=BOT))


def test_the_owners_own_message_to_an_agent_is_not_machine_text_but_is_with_an_agent():
    payload = _message(True, counterpart=BOT)
    assert not machine.is_machine(payload)
    assert machine.with_agent(payload)
    assert machine.agent_of(payload) == BOT


def test_a_message_without_the_mark_is_a_persons_as_before():
    payload = _message(False)
    assert not machine.is_machine(payload) and not machine.with_agent(payload)
    assert machine.agent_of(payload) is None


def test_only_the_literal_true_marks_a_line():
    assert not machine.is_machine(_message(False, machine="yes"))
    assert not machine.is_machine({"schema": "message/v1", "extra": "machine"})
    assert not machine.is_machine({})


def test_a_counterpart_of_another_kind_is_not_an_agent():
    person = {"kind": "person", "ref": {"kind": "phone", "value": "+447700900123"}}
    assert not machine.with_agent(_message(True, counterpart=person))


def test_the_machine_participants_of_a_transcript_are_named_case_and_spacing_aside():
    participants = [{"name": "owner"}, {"name": "Assistant ", "machine": True}, "noise", {"machine": True}]
    assert machine.labels(participants) == frozenset({"assistant"})
    assert machine.is_machine_participant(participants[1])
    assert not machine.is_machine_participant(participants[0])


def test_the_owners_turns_are_kept_and_the_machines_dropped():
    participants = [{"name": "owner"}, {"name": "assistant", "machine": True}]
    turns = [
        Turn("owner", "Can you check the anchor log?"),
        Turn("assistant", "I'll read it now and report back."),
        Turn("ASSISTANT", "Done."),
        Turn(None, "unattributed text stays"),
    ]
    kept = machine.human_turns(turns, participants)
    assert [t.speaker for t in kept] == ["owner", None]


def test_a_transcript_with_no_machine_participant_keeps_every_turn():
    turns = [Turn("Ola", "Hei"), Turn("me", "Hei hei")]
    assert machine.human_turns(turns, [{"name": "Ola"}]) == turns
