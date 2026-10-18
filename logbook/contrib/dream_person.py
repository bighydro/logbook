"""The dream of a person (`logbook dream person NAME [--window FROM TO]`): a model reads what passed
between the owner and one person over a window and writes one `draft/v1` line about it (RFC 0036
amendment 1, unit `person`), what has passed between them, the threads still open, the promises made
and two questions, every sentence pointing at the lines it came from or marked unsupported. A
proposal, as every draft: the owner's notes and signatures are the facts.

**The entry.** Reading a person for a model is the relationship reader's crossing, so the dream of a
person is governed by the `relationship` entry of `policy/crossing.json`, never the `dream` entry
(`logbook.contrib.relationship`): its `max_tier` the ceiling, its `until` the last day, its `model`
the one model, its `include_unsigned` whether a day the owner has not signed may be read. No entry,
no `until`, or an expired one, and nothing is read or sent and one sentence says so. The endpoint is
the dream's (`model_client`, LOGBOOK_DREAM_*), and the key is never said (`relationship.model.scrub`).

**What it reads** is the person's authorized input set (`relationship.reader.read`) read from the
record, never from the reader's store: the lines on which they are a counterpart, an attendee or a
speaker, on a local day of the window, not retracted, through the entry's gate (the ceiling, the
signed days); with each line its instant, kind, speakers by label, words and the promises read in its
words (`reader.promises`), and the person's label. Nothing else of the record: no note, no group, no
stay, no draft. Each line is a reference (`L1`, ...) that stands for its id, so the model cites
references and the record keeps ids.

**The line**, as the day's (`logbook.contrib.dream`): the answer checked (`dream.segments_of`, strict:
one reference the material did not give marks the segment, so evidence outside the set is never
written, rule 6), more than 30 % unsupported refused; `unit` `person`, `subject` the person's
canonical id, `window` `{from, to}`, `read_head`, `read_count` the size of the set, `language`;
`extra.prompt`, `extra.parts` (`drafts.PERSON_PARTS`), `extra.read_ids_sha256`, `extra.policy_version`
(`policy.version` of the `relationship` entry), `extra.entry` (`relationship`) and `extra.signed_only`;
the tier the highest tier read, the set's lines and the resolution lines of the peers named. It
`supersedes` the person's standing draft, whatever its window (rule 2). The same model on the same
person over the same window at the same head under the same entry writes nothing and says so (rule
1). The whole run, reading, the model's turn and the write, is inside the writer lock, and the head is
read again before the append (`dream.append`): a head that moved is `HeadMoved` and nothing is
written. Where a person draft shows (the person page) is not this module's; nothing reads it yet."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from pathlib import Path
from string import Template
from typing import Any

from ..core import drafts, policy
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import Logbook, retractions
from . import dream, model_client
from .dream import AnswerError, Dream, DreamError, Material
from .model_client import Transport
from .relationship import model as relationship_model
from .relationship import reader
from .relationship.reader import ENTRY, RelationshipError

PROMPT_FILE = Path(__file__).with_name("dream-person-prompt.md")
PROMPT_NAME = "dream-person/1"  # kept under `extra.prompt`, so a draft says which prompt wrote it
DEFAULT_DAYS = 90  # the window when none is given: the 90 local days that end today


def today() -> date:
    """The day a window may not run past (amendment 1: `to` not after the day of the draft's `at`):
    the machine's local date, the one the entry's `until` is held against (`policy.today`)."""
    return policy.today()


def head_of(lb: Logbook) -> str:
    """The record's head the reading is at."""
    return str(lb.meta.get("head"))


def window_of(window: tuple[str, str] | None, on: date) -> tuple[str, str]:
    """`window` as two local days, or the `DEFAULT_DAYS` that end on `on`; `DreamError` for one that
    runs backwards or past `on`."""
    if window is None:
        return (on - timedelta(days=DEFAULT_DAYS - 1)).isoformat(), on.isoformat()
    first, last = parse_day(window[0]), parse_day(window[1])
    if first > last:
        raise DreamError(f"the window runs backwards: {window[0]} is after {window[1]}")
    if last > on:
        raise DreamError(
            f"the window ends on {last.isoformat()}, after today ({on.isoformat()}); a draft reads days"
            " that were"
        )
    return first.isoformat(), last.isoformat()


def material(lb: Logbook, found: reader.InputSet, ceiling: int, head: str) -> Material:
    """The person's material: the label, the window and each line of the set as a reference."""
    said = reader.promises(lb, found, ceiling)
    ids = {item.line for item in found.items}
    made = Material(
        day=f"{found.label} {found.span}",
        tier=found.tier,
        read_count=len(found.items),
        read_head=head,
        read_ids_sha256=dream.digest(ids),
        language=dream.language_of(item.text for item in found.items if item.text),
        data={},
        ids=ids,
        unit=drafts.UNIT_PERSON,
    )
    lines = []
    for item in found.items:
        shown: dict[str, Any] = {"ref": made.ref_of(item.line), "at": item.at, "kind": item.kind}
        shown |= {"speakers": [found.peers[s] for s in item.speakers], "text": item.text}
        if said.get(item.line):
            shown["promises"] = said[item.line]
        lines.append(shown)
    made.data = {"person": found.label, "window": {"from": found.first, "to": found.last}, "lines": lines}
    return made


def prompt(made: Material, found: reader.InputSet) -> list[dict[str, str]]:
    """The two messages: the prompt with the person, the window and the language, and the material."""
    system = Template(PROMPT_FILE.read_text(encoding="utf-8")).safe_substitute(
        person=found.label,
        first=found.first,
        last=found.last,
        language=made.language,
        language_name=dream.LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def standing_of(lb: Logbook, person: str) -> Line | None:
    """The person's standing draft, by their id, whatever its window (rule 2)."""
    with lb.index() as idx:
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retractions(idx.retractions()), drafts.UNIT_PERSON)
    return drafts.standing(found.get(person, []))


def same(
    latest: Line | None, source: str, made: Material, window: dict[str, str], version: str, signed: bool
) -> bool:
    """Rule 1 for a person: the standing draft is this model's, at this head, under this entry, over
    this window and through the same signed-day gate."""
    if latest is None or not dream.same_draft(latest, source, made.read_head, version):
        return False
    payload = latest.get("payload") or {}
    found = payload.get("extra")
    extra: dict[str, Any] = found if isinstance(found, dict) else {}
    return payload.get(drafts.WINDOW) == window and extra.get("signed_only", True) == signed


def run(
    lb: Logbook,
    name: str,
    window: tuple[str, str] | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
) -> Dream:
    """Dream the person `name` means over `window`: the entry, the endpoint, the set, the model's turn,
    the check and one `draft/v1` line appended under the writer lock unless `dry_run`. `DreamError`
    says why it is refused (`AnswerError` when the model's answer failed); `HeadMoved` when the
    record moved under the reading."""
    try:
        current = reader.entry(lb.root)
        ep = relationship_model.endpoint(current, os.environ if env is None else env)
    except RelationshipError as e:
        raise DreamError(str(e)) from None
    first, last = window_of(window, today())
    with lb.writer():
        head = head_of(lb)
        try:
            found = reader.read(lb, name, first, last, current.max_tier, current.include_unsigned)
        except RelationshipError as e:
            raise DreamError(str(e)) from None
        if not found.items:
            raise DreamError(
                f"{found.label} has no line in {found.span} through the {ENTRY!r} entry (max_tier"
                f" {current.max_tier}{'' if current.include_unsigned else ', signed days'}); nothing to dream"
            )
        made = material(lb, found, current.max_tier, head)
        latest = standing_of(lb, found.person)
        source = drafts.SOURCE_PREFIX + ep.model
        version = current.version
        span = {"from": found.first, "to": found.last}
        signed = not current.include_unsigned
        if not dry_run and latest is not None and same(latest, source, made, span, version, signed):
            raise DreamError(
                f"{made.day} was dreamed by {source} at this head already (#{latest['seq']}); the record"
                " has not moved, so there is nothing new to dream"
            )
        messages = prompt(made, found)
        if say is not None:
            for message in messages:
                say(message["content"])
        try:
            answer = model_client.complete(ep, messages, transport=transport)
        except model_client.ModelError as e:
            raise AnswerError(relationship_model.scrub(str(e), ep.key)) from None
        segments, parts = dream.segments_of(dream.parse(answer), made, drafts.PERSON_PARTS, strict=True)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_PERSON,
            "subject": found.person,
            drafts.WINDOW: span,
            "read_head": made.read_head,
            "read_count": made.read_count,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                "parts": parts,
                "read_ids_sha256": made.read_ids_sha256,
                "policy_version": version,
                "entry": ENTRY,
                "signed_only": signed,
            },
        }
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        dream.valid(payload)
        if dry_run:
            return Dream(made.day, None, payload, made.tier, messages, answer)
        line = dream.append(lb, made, source, payload)
    return Dream(made.day, line, payload, made.tier, messages, answer)
