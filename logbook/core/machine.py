"""The machine mark: which lines, and which turns of a transcript, an agent wrote.

The owner talks to agents of their own: bots they run on Telegram, a coding assistant in a Claude
Code session. Those conversations are part of the record, the owner's words at their tier and the
agent's words beside them, marked as machine text so that no reader takes them for a person's.
No profile has a slot for the mark, and none is invented for it (docs/adapters/agents.md):

- **A message** (`message/v1`, RFC 0008, which keeps anything else a source reports under `extra`):
  `extra.machine` is `true` on a line the agent wrote, and `extra.counterpart` is
  `{"kind": "agent", "ref": {kind, value}, "name"?}` on every line of a conversation with one, the
  owner's and the agent's: the counterpart is an observed entity of kind `agent` (RFC 0037's
  observed entity, a kind that RFC does not list yet), never a person.
- **A transcript** (`transcript/v1`, RFC 0004, whose consumers ignore a participant's sub-fields
  they do not know): a participant `{"name": ..., "machine": true}` is an agent, and every turn
  whose speaker label is that participant's name is machine text.

Only the literal `true` marks anything. A reader that counts people (`people`, `person`, `people
review`, the company of a stay) passes machine text and agent counterparts over; `promises` reads
the owner's turns only. Pure: no record, no I/O."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .transcripts import Turn

MACHINE = "machine"  # the key of the mark, under a message's `extra` and on a participant
COUNTERPART = "counterpart"  # under a message's `extra`: who the conversation is with
AGENT = "agent"  # the kind of an observed entity that is an agent, never a person


def _extra(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    extra = payload.get("extra") if isinstance(payload, Mapping) else None
    return extra if isinstance(extra, Mapping) else {}


def is_machine(payload: Mapping[str, Any]) -> bool:
    """Whether the line's own words are an agent's: `extra.machine` is `true`."""
    return _extra(payload).get(MACHINE) is True


def agent_of(payload: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The agent a conversation is with (`extra.counterpart` of kind `agent`), or None."""
    counterpart = _extra(payload).get(COUNTERPART)
    if isinstance(counterpart, Mapping) and counterpart.get("kind") == AGENT:
        return counterpart
    return None


def with_agent(payload: Mapping[str, Any]) -> bool:
    """Whether the line belongs to a conversation with an agent, whoever wrote it."""
    return agent_of(payload) is not None


def is_machine_participant(participant: object) -> bool:
    return isinstance(participant, Mapping) and participant.get(MACHINE) is True


def _folded(name: str) -> str:
    return " ".join(name.split()).casefold()


def labels(participants: Iterable[Any]) -> frozenset[str]:
    """The names of a transcript's machine participants, case and spacing aside."""
    return frozenset(
        _folded(p["name"])
        for p in participants
        if is_machine_participant(p) and isinstance(p.get("name"), str) and p["name"].strip()
    )


def human_turns(turns: Sequence[Turn], participants: Iterable[Any]) -> list[Turn]:
    """The turns no machine participant spoke: every turn whose label is a machine participant's
    name is dropped; an unlabelled turn is kept, as it was before the mark existed."""
    machines = labels(participants)
    if not machines:
        return list(turns)
    return [t for t in turns if t.speaker is None or _folded(t.speaker) not in machines]
