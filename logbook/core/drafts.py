"""The draft (RFC 0036, `draft/v1`): what a model wrote about a unit of the record, every sentence
pointing at the lines it rests on or marked unsupported.

A draft is a proposal. Nothing in it is a fact of the record until the owner confirms it through an
act of their own: a signed day (RFC 0034), a note (RFC 0010), a review or a star. This module fixes
the line and reads it back; what writes one is `logbook.contrib.dream` (`logbook dream day`). Nothing
here writes.

The payload: `unit` (`day` here), `subject` (the local day), `read_head` (the record's head when the
model read), `read_count` (how many lines of the unit it read, under the ceiling it read under),
`language` (a BCP 47 tag) and `segments`, in order, each `{text, evidence: [line ids]}` or `{text,
unsupported: true}` and nothing else (`segment_shape`). `supersedes` names the earlier draft of the
same unit this one replaces. `extra` keeps what the writer wants to say about its run: the prompt's
name, the part of the dream each segment belongs to (`parts`, one word per segment: the day in a
paragraph, the threads it moved, the questions, the people and promises proposed) and the digest of
the ids it read (`read_ids_sha256`), which `dream --catch-up` compares, the version of the
crossing entry it was dreamed under (`policy_version`, `policy.version`: the SHA-256 of the entry's
`max_tier`, `until` and `model`), and how many proposals the writer dropped and why (`dropped`).

**Proposals.** Beside its text a draft MAY carry `proposals`: what the model thinks happened and the
owner may confirm, each one object, kind `event` the only kind so far (`proposal_shape`): `{kind:
"event", title, start, end, place, people, evidence}`, `start` before `end`, both RFC 3339 UTC with a
`Z`; `place` a named place of `places.json` by its name or an observed place by its id
(`place:<lat>,<lon>`, as `places review` names a cluster), or null; `people` canonical person ids
(the entity ids the resolution lines name, never the owner); `evidence` the line ids it rests on. A
proposal is numbered by its place in the list, from 1. It is never an event line: the owner's
`--accept` (`day sign`, `day reflect --sign`) makes it one, an `event/v1` line, source `owner`, whose
`raw_id` is `<draft id>/<number>` and whose `extra.from` names the draft (`confirmations`); the Day
then shows the proposal confirmed and the event among the day's events.

**Forward compatibility** (`draft/v1`, 19 Oct 2026). A proposal of a kind this module does not know
(`PROPOSAL_KINDS`), one written by a later writer, is not a malformed line to a reader: the Day shows
the proposals of the kinds it knows, counts the others under `proposals_unknown` and keeps their
numbers, so a known proposal's number, and the `raw_id` it is confirmed under, never moves. A known
kind of the wrong shape, or a proposal with no kind at all, is still malformed. The writers stay
strict: `validate` refuses an unknown kind unless it is asked as a reader (`reader=True`), so the dream
and every other writer here write only the kinds they know.

**A transcript's synthesis** (`logbook transcript synthesize`, `logbook.contrib.synthesis`) is a
draft of unit `event` whose `subject` is `[<the transcript line's id>]`. A transcript's utterances
are not lines of their own (`transcript/v1` keeps the text in one attachment, RFC 0004), so every
supported segment's `evidence` is the transcript line, and which utterances it rests on is kept
beside the segments: `extra.segments`, one object per segment, `{part, utterances: [{n, offset?}],
assignee?, due?: {phrase, date}}`, `part` one of `SYNTHESIS_PARTS` (actions on top), `n` the
utterance's place in the transcript as `transcripts.turns_of` reads it, from 1, and `offset` where
it is in the recording (`20:05`) when the source says. Like every draft it records the version of
the `dream` entry it was made under (`extra.policy_version`), and it follows the policy as every
draft does (below). `by_transcript` finds the syntheses as `by_day` finds the days' drafts, and
`for_transcripts` gives the Day the standing synthesis of each of its transcripts through the same
rule as `for_day` (`through`), every evidence id checked against the transcript. A synthesis is the
call's draft, never the day's (amendment 1: one standing draft per unit): `by_day`, `for_day` and
`withheld` read unit `day` alone, so a synthesis neither replaces nor shadows the day's draft.

**The standing draft** of a day is its latest `draft` line, by `at` then `seq`, that is not retracted
and not named in a later draft's `supersedes`; the earlier ones stay in the record and the Day lists
their ids. A reader that holds the record checks every evidence id against the day's lines: an id
that is not on the day makes the segment unsupported and says why (rule 6); a segment of neither
documented shape is unsupported and the line is said to be malformed. A reader never prints an
unsupported segment as plain prose between two supported ones: in text it is set apart with a
leading `~` and the word `unsupported` after it.

**Derived material follows the policy, not the head.** A draft is what a model wrote from lines the
`dream` entry of `policy/crossing.json` let cross to it, so a reader shows it only while the entry
still allows its tier (`allowed`): a draft above the entry's `max_tier` today (lowered since, expired,
removed, or a file that is not a policy) is withheld, whatever the head, and the standing draft among
the ones the entry allows is shown in its place, if there is one. The line stays in the record. The
Day of a reader that holds the whole record says so in one row, `superseded by policy` and why, and
nothing of the draft's text (`withheld_json`); a reader through a gate of its own hides it without a
word, as it hides every line above its gate. A withheld draft's proposals are withheld with it: the Day
shows none and `--accept` names none, and the draft shown in its place brings its own; an event the
owner confirmed from it before stays, an owner's line like any other. A call's synthesis is held the
same way, by the same rule (`through`), and its row goes under the call's own row on the Day
(`syntheses_withheld`), never in the day's draft's place. `doctor` lists the days whose standing draft
is withheld (`withheld`), and `dream --catch-up` dreams them again under the entry when it allows any
tier. A reader of another unit (a journey's: `by_unit`, `for_unit`) holds its drafts to the same rule
(`through`), the row included.

**A draft is held to the entry it was written under** (`Allowed.of`): a person draft (unit `person`,
`dream person`) to the `relationship` entry, read as the relationship reader reads it (`person_allowed`:
no entry, no `until` or one past it withholds every person draft), every other unit to the `dream`
entry. The unit decides, as the draft line carries it; `extra.policy_version` says which version of
that entry wrote it, and today's entry, not the version, decides what is shown. A sealed draft this
machine cannot open has no unit to read and follows the `dream` entry. `doctor` lists the people whose
standing draft is withheld beside the days (`withheld_people`)."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import events, figures, policy, present, resolve, signing
from .chain import Line
from .flights import Airlines
from .index import Index
from .store import retractions

KIND = "draft"
SCHEMA = "draft/v1"
UNIT_DAY = "day"
UNIT_EVENT = "event"  # a transcript's synthesis: the call is the unit, its line the subject
UNITS = ("day", "journey", "event", "week", "month", "year", "chapter", "person")
SOURCE_PREFIX = "model:"  # `source` names the model as its runner names it; never `manual`
SUPPORTED, UNSUPPORTED, MALFORMED = "supported", "unsupported", "malformed"
# the parts of a day's dream, in order (dream-day/4, RFC 0043 §13.4): the goodnight story, then one part
# per lens (`lens:<id>`, `LENS`), then the threads, what was learned and decided, the ideas the day moved,
# the one question, the people and promises proposed, and the photo of the day
PARTS = ("story", "threads", "learned", "decision", "ideas", "questions", "people", "promises", "photo")
PARTS_3 = ("day", "threads", "questions", "people", "promises")  # a dream-day/3 draft's, and before it
STORY, LEARNED, DECISION, IDEAS, PHOTO = "story", "learned", "decision", "ideas", "photo"
LENS = "lens:"  # a lens's part: `lens:<id>`, the id of a question of the bank asked of the day (RFC 0027)
NO_ANSWER = (
    "\u2014 the day doesn't answer this"  # a lens with no segment: the reader's words, never a model's
)
SINCE_SIGNED = "since you signed"  # the head of a draft dreamed after the day's standing signature
EVENING = "the day so far"  # the head of a draft read before the day ended (`extra.evening`)
# the parts of a journey's dream and of a week's (`dream journey`, `dream week`), in order
JOURNEY_PARTS = ("journey", "days", "places", "people", "decisions", "promises", "photos", "name")
WEEK_PARTS = ("time", "energy", "people", "goals", "next_week", "personal")
PERSON_PARTS = ("person", "threads", "promises", "questions")  # `dream person` (amendment 1)
DAY_PARTS = tuple(dict.fromkeys((*PARTS_3, *PARTS)))  # every part a day's draft may name, a lens's aside
# `dream month` and `dream chapter` (the amendment of 2026-10-21), in order
MONTH_PARTS = ("month", "where", "goals", "next_month", "question")
CHAPTER_PARTS = ("arc", "rule", "held", "closed")
UNIT_PARTS = {
    "day": DAY_PARTS,
    "journey": JOURNEY_PARTS,
    "week": WEEK_PARTS,
    "person": PERSON_PARTS,
    "month": MONTH_PARTS,
    "chapter": CHAPTER_PARTS,
}  # by `unit`
PART_LABELS = {
    "story": "story",
    "learned": "learned",
    "decision": "decided",
    "ideas": "idea",
    "photo": "photo",
    "day": "day",
    "threads": "thread",
    "questions": "question",
    "people": "people",
    "promises": "promise",
    "journey": "journey",
    "days": "days",
    "places": "place",
    "decisions": "decision",
    "photos": "star",
    "name": "name",
    "time": "time",
    "energy": "energy",
    "goals": "goal",
    "next_week": "next week",
    "personal": "personal",
    "person": "person",
    "month": "month",
    "where": "where",
    "next_month": "proposal",
    "question": "question",
    "arc": "arc",
    "rule": "rule",
    "held": "held",
    "closed": "closed",
}
# the parts of a transcript's synthesis, in order: actions on top (`logbook transcript synthesize`)
SYNTHESIS_PARTS = ("actions", "topics", "decisions", "open_threads", "personal")
SYNTHESIS_LABELS = {
    "actions": "action",
    "topics": "topic",
    "decisions": "decision",
    "open_threads": "open",
    "personal": "personal",
}
SYNTHESIS_NOUNS = {
    "actions": ("action", "actions"),
    "topics": ("topic", "topics"),
    "decisions": ("decision", "decisions"),
    "open_threads": ("open thread", "open threads"),
    "personal": ("personal", "personal"),
}
HEAD_SHORT = 8  # `read at bb97e90d`: the first 8 hex of the head
SUBJECT_SHOWN = 3  # `show` names a subject of more entries by its first and how many lines follow
ID_SHORT = 8  # an evidence id shortened to its last 8 characters in text
EVIDENCE = "from"  # the word before a sentence's evidence ids, `… Kari Nordmann.  from […6742a9f5]`
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*\Z")  # a BCP 47 tag, loosely
SHA256_HEX = 64
NOT_ON_DAY = "evidence names a line that is not on the day"
NOT_THE_TRANSCRIPT = "evidence names a line that is not the transcript"
WHOLE = "the transcript"  # a segment that rests on the transcript line and on no utterance of it
NOT_ON_JOURNEY = "evidence names a line that is not of the journey"
NOT_ON_WEEK = "evidence names a line that is not of the week"
UNIT_JOURNEY = "journey"
UNIT_WEEK = "week"
UNIT_PERSON = "person"  # one canonical person over a window (RFC 0036 amendment 1)
UNIT_MONTH = "month"  # a calendar month, `2026-06` (the amendment of 2026-10-21)
UNIT_CHAPTER = "chapter"  # a chapter, its `chapter/v1` lines the subject (the same amendment)
NOT_ON_MONTH = "evidence names a line that is not of the month"
NOT_ON_CHAPTER = "evidence names a line that is not of the chapter"
ISO_MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])\Z")  # a month's subject, `2026-06`
PERSON_ENTRY = "relationship"  # the entry a person draft is written under and held to (`Allowed.of`)
SCENE_SOURCE = "model:video-rules/"  # a video scene's draft (`labs/scenes.py`): written here, under no entry
WINDOW = "window"  # a person draft's `{from, to}`, two local days, both inclusive; absent on every other unit
ISO_WEEK = re.compile(r"\d{4}-W(0[1-9]|[1-4]\d|5[0-3])\Z")  # a week's subject, `2026-W25`
NOT_A_SEGMENT = "a segment is {text, evidence} or {text, unsupported: true}, nothing else"
HELD = "held: a number beside a name"  # a held slot's text: the words are dropped, the slot kept
SUPERSEDED_BY_POLICY = "superseded by policy"  # the Day's row for a draft the dream entry no longer allows
DOT = " · "
EN_DASH = "\u2013"
PROPOSALS = "proposals"  # the payload key of what a draft proposes beside its text
EVENT = "event"  # a proposed event the owner may confirm into an event/v1 line
LINK = "link"  # a proposed link of a line of the day to a canonical entity (amendment 2, RFC 0037)
PROPOSAL_KINDS = frozenset(
    {EVENT, LINK}
)  # the kinds this reader shows and its writers write; others are counted
EVENT_KIND = "event"  # the line a confirmed proposal becomes
OWNER = "owner"  # its source: the owner confirmed it, the model only proposed it
CLUSTER = "place:"  # an observed place's id, `place:<lat>,<lon>`, as `places review` names a cluster
PROPOSAL_KEYS = frozenset({"kind", "title", "start", "end", "place", "people", "evidence"})
NOT_A_PROPOSAL = (
    "a proposal is {kind: event, title, start, end, place, people, evidence}: start before end, both UTC"
    " with a Z, people and evidence lists of ids, evidence not empty"
)
LINK_KEYS = frozenset({"kind", "entity", "text", "evidence", "note"})
NOT_A_LINK = (
    "a link is {kind: link, entity, text, evidence, note?}: entity an entity id, text what it says, evidence"
    " a non-empty list of line ids, note a string when given"
)
KEPT_FROM = "from"  # `extra.from` of a line the owner kept from a draft: the draft's id
KEPT_PROPOSAL = "proposal"  # `extra.proposal` of a kept line: the proposal's kind and identifying fields
KEEPABLE = (LEARNED, DECISION, IDEAS, PHOTO)  # the parts whose sentences `--keep` keeps (RFC 0043 §5)
UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z\Z")


class DraftError(ValueError):
    """A draft the record refuses; the message says what and nothing is written."""


# -- the shape ------------------------------------------------------------------------------------------


def segment_shape(segment: object) -> str:
    """`supported` for `{text, evidence: [ids]}`, `unsupported` for `{text, unsupported: true}`,
    `malformed` for anything else: both keys, neither, an empty evidence, a false mark, an empty
    text, or an evidence entry that is not a string."""
    if not isinstance(segment, dict):
        return MALFORMED
    text = segment.get("text")
    if not isinstance(text, str) or not text.strip():
        return MALFORMED
    has_evidence, has_mark = "evidence" in segment, "unsupported" in segment
    if has_evidence and not has_mark:
        evidence = segment["evidence"]
        if isinstance(evidence, list) and evidence and all(isinstance(e, str) and e for e in evidence):
            return SUPPORTED
        return MALFORMED
    if has_mark and not has_evidence and segment["unsupported"] is True:
        return UNSUPPORTED
    return MALFORMED


def validate(payload: Mapping[str, Any], *, reader: bool = False) -> list[str]:
    """Every way the payload is not a `draft/v1`, in words; empty when it is one. A writer refuses
    a payload with any problem; a reader keeps reading and says the line is malformed. A proposal of
    a kind not in `PROPOSAL_KINDS` is a problem to a writer, which writes only the kinds it knows, and
    none to a `reader`, which counts it (`unknown_proposals`); a known kind of the wrong shape is a
    problem to both."""
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {SCHEMA!r}")
    if payload.get("unit") not in UNITS:
        problems.append(f"unit must be one of {', '.join(UNITS)}")
    subject = payload.get("subject")
    if payload.get("unit") == UNIT_DAY:
        try:
            datetime.strptime(str(subject), "%Y-%m-%d")
        except ValueError:
            problems.append(f"subject {subject!r} is not a local day, YYYY-MM-DD")
    elif payload.get("unit") == UNIT_WEEK:
        if not isinstance(subject, str) or not ISO_WEEK.match(subject):
            problems.append(f"subject {subject!r} is not an ISO week, YYYY-Www")
    elif payload.get("unit") == UNIT_MONTH:
        if not isinstance(subject, str) or not ISO_MONTH.match(subject):
            problems.append(f"subject {subject!r} is not a month, YYYY-MM")
    elif payload.get("unit") == UNIT_PERSON:
        if not isinstance(subject, str) or not subject.strip():
            problems.append("subject must be one canonical person id, as a string")
    elif not isinstance(subject, str) and not (
        isinstance(subject, list) and subject and all(isinstance(s, str) for s in subject)
    ):
        problems.append("subject must be a string or a non-empty list of line ids")
    problems += _window_problems(payload)
    head = payload.get("read_head")
    if not isinstance(head, str) or len(head) != SHA256_HEX or not all(c in "0123456789abcdef" for c in head):
        problems.append("read_head must be the record's head, 64 lowercase hex characters")
    count = payload.get("read_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        problems.append("read_count must be how many lines of the unit the model read")
    language = payload.get("language")
    if not isinstance(language, str) or not LANGUAGE.match(language):
        problems.append("language must be a BCP 47 tag, en or nb")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        problems.append("segments must be a non-empty list")
    else:
        bad = [i for i, segment in enumerate(segments) if segment_shape(segment) == MALFORMED]
        if bad:
            problems.append(f"segment {bad[0] + 1} is malformed: {NOT_A_SEGMENT}")
    if "supersedes" in payload and (not isinstance(payload["supersedes"], str) or not payload["supersedes"]):
        problems.append("supersedes must be the id of the earlier draft")
    if PROPOSALS in payload:
        proposals = payload[PROPOSALS]
        if not isinstance(proposals, list):
            problems.append("proposals must be a list")
        else:
            unknown = [i for i, proposal in enumerate(proposals) if unknown_kind(proposal)]
            bad = [i for i, p in enumerate(proposals) if i not in unknown and not known_shape(p)]
            if unknown and not reader:
                kind = proposals[unknown[0]]["kind"]
                problems.append(f"proposal {unknown[0] + 1} is of a kind this writer does not know: {kind!r}")
            if bad:
                found = proposals[bad[0]]
                said = NOT_A_LINK if isinstance(found, dict) and found.get("kind") == LINK else NOT_A_PROPOSAL
                problems.append(f"proposal {bad[0] + 1} is malformed: {said}")
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    elif isinstance(payload.get("extra"), dict) and "evening" in payload["extra"]:
        problems += _evening_problems(payload)
    return problems


def _evening_problems(payload: Mapping[str, Any]) -> list[str]:
    """`extra.evening` (amendment 2): `true` on a day draft read before the day ended, and then
    `extra.read_until`, the moment read up to, RFC 3339 UTC with a `Z`."""
    extra = payload["extra"]
    if payload.get("unit") != UNIT_DAY:
        return ["extra.evening is a day draft's alone"]
    if extra.get("evening") is not True:
        return ["extra.evening is true when present"]
    until = extra.get("read_until")
    if not isinstance(until, str) or not UTC_STAMP.match(until):
        return ["an evening draft's extra.read_until is the moment it read up to, UTC with a Z"]
    return []


def _window_problems(payload: Mapping[str, Any]) -> list[str]:
    """A person draft's `window`, MUST and `{from, to}` with `from` not after `to`; any other unit's,
    absent (amendment 1)."""
    if payload.get("unit") != UNIT_PERSON:
        return [] if WINDOW not in payload else [f"window is a {UNIT_PERSON} draft's alone"]
    window = payload.get(WINDOW)
    if not isinstance(window, dict) or set(window) != {"from", "to"}:
        return ["a person draft's window must be {from, to}, two local days"]
    try:
        first, last = (datetime.strptime(str(window[k]), "%Y-%m-%d") for k in ("from", "to"))
    except ValueError:
        return ["a person draft's window must be two local days, YYYY-MM-DD"]
    return [] if first <= last else ["a person draft's window runs backwards: from is after to"]


def unknown_kind(proposal: object) -> bool:
    """Whether `proposal` names a kind, a non-empty string, that is not one of `PROPOSAL_KINDS`: a
    later writer's, which a reader counts and does not show. One with no kind is malformed instead."""
    if not isinstance(proposal, dict):
        return False
    kind = proposal.get("kind")
    return isinstance(kind, str) and bool(kind.strip()) and kind not in PROPOSAL_KINDS


def unknown_proposals(payload: Mapping[str, Any]) -> int:
    """How many of the draft's proposals are of a kind this reader does not know (`unknown_kind`)."""
    found = payload.get(PROPOSALS)
    return sum(1 for proposal in found if unknown_kind(proposal)) if isinstance(found, list) else 0


def known_shape(proposal: object) -> bool:
    """Whether `proposal` is one of the kinds this reader knows, of its documented shape."""
    return proposal_shape(proposal) or link_shape(proposal)


def link_shape(proposal: object) -> bool:
    """Whether `proposal` is a link of the documented shape (`NOT_A_LINK`, amendment 2): nothing but
    its keys, an entity id, the text that says what it links, a non-empty list of line ids and, when
    given, a note."""
    if not isinstance(proposal, dict) or not set(proposal) <= LINK_KEYS or proposal.get("kind") != LINK:
        return False
    entity, text, evidence = proposal.get("entity"), proposal.get("text"), proposal.get("evidence")
    if not isinstance(entity, str) or not entity.strip() or not isinstance(text, str) or not text.strip():
        return False
    if "note" in proposal and (not isinstance(proposal["note"], str) or not proposal["note"].strip()):
        return False
    return isinstance(evidence, list) and bool(evidence) and all(isinstance(e, str) and e for e in evidence)


def proposal_shape(proposal: object) -> bool:
    """Whether `proposal` is an event proposal of the documented shape (`NOT_A_PROPOSAL`): nothing
    but its keys, a title, a span in UTC that runs forward, a place that is a non-empty string or
    null, a list of person ids and a non-empty list of line ids."""
    if not isinstance(proposal, dict) or not set(proposal) <= PROPOSAL_KEYS:
        return False
    if proposal.get("kind") != EVENT:
        return False
    title, start, end = proposal.get("title"), proposal.get("start"), proposal.get("end")
    if not isinstance(title, str) or not title.strip():
        return False
    if not all(isinstance(t, str) and UTC_STAMP.match(t) for t in (start, end)):
        return False
    if _instant(str(start)) >= _instant(str(end)):
        return False
    place = proposal.get("place")
    if place is not None and (not isinstance(place, str) or not place.strip()):
        return False
    people, evidence = proposal.get("people"), proposal.get("evidence")
    if not isinstance(people, list) or not all(isinstance(p, str) and p for p in people):
        return False
    return isinstance(evidence, list) and bool(evidence) and all(isinstance(e, str) and e for e in evidence)


# -- the policy it follows ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Allowed:
    """What the entry a draft was written under lets a reader show today of it: the drafts at or
    under `max_tier`. `max_tier` is 0 when the file names no entry, when the entry has expired, or
    when the file is not a policy, and `reason` then says which; None when the entry is in force.
    `entry` names it: `dream` for every unit but one, and a person draft (`dream person`, RFC 0036
    amendment 1) is held to `person`, the `relationship` entry it was written under (`of`)."""

    max_tier: int
    reason: str | None = None
    entry: str = policy.DREAM_DESTINATION
    person: Allowed | None = None  # the `relationship` entry, for unit `person`; None: this entry

    def of(self, unit: object) -> Allowed:
        """The entry a draft of `unit` is held to: the `relationship` entry for a person, this one
        (the `dream` entry) for every other unit, and for a line whose unit cannot be read."""
        return self.person if unit == UNIT_PERSON and self.person is not None else self

    def allows(self, line: Line) -> bool:
        return int(line.get("tier") or 0) <= self.of(unit_of(line)).max_tier

    def why_not(self, tier: int, unit: str = UNIT_DAY) -> str:
        """Why a draft of `tier` is withheld, in words, for the Day and `doctor`. A day is dreamed
        again under the entry; a call's synthesis is of the call's tier, so the call is above the
        entry as well and stays home (`synthesis.gate`) until the entry allows it again."""
        held = self.of(unit)
        if held.reason is not None:
            return held.reason
        found = f"tier {tier}, above max_tier {held.max_tier} of the {held.entry!r} entry"
        if unit == UNIT_EVENT:
            return f"{found}; the call stays home until the entry allows its tier"
        if unit in (UNIT_JOURNEY, UNIT_WEEK, UNIT_PERSON, UNIT_MONTH, UNIT_CHAPTER):
            return f"{found}; `dream {unit}` dreams it again under it"
        return f"{found}; `dream --catch-up` dreams the day again under it"


PENCIL_SOURCES = ("description", "mcp")  # a model's description of a photo; an agent's line through the door


def is_pencil(line: Line) -> bool:
    """Whether `line` is pencil, a proposal no signature confirms (RFC 0043 §6 rule 3; R7): the
    dream's draft, a note a model derived (`extra.derived`: a photo's description, a meeting's summary),
    and any line written by a model describing a photo or by an agent through the MCP door (source
    `description` or `mcp`). Everything else on a day's page is ink, the owner's to confirm."""
    if line.get("kind") == KIND or line.get("source") in PENCIL_SOURCES:
        return True
    payload = line.get("payload")
    extra = payload.get("extra") if isinstance(payload, dict) else None
    return line.get("kind") == "note" and isinstance(extra, dict) and extra.get("derived") is True


def under_entry(line: Line) -> bool:
    """Whether a draft was written under an entry of the crossing policy: every draft but a video
    scene's (source `SCENE_SOURCE`), which the rules on this machine write from lines that never
    crossed, so that no entry governs it and a crossing carries it by its tier like any line."""
    return not str(line.get("source") or "").startswith(SCENE_SOURCE)


def held_by_entry(line: Line, entries: Allowed) -> bool:
    """A draft the entry it was written under no longer allows (`Allowed.allows`: a person's the
    `relationship` entry, every other unit's the `dream` entry, and a sealed one this machine cannot
    open the `dream` entry); every other line, a video scene's draft among them (written under no
    entry, `under_entry`), is the tier's alone. The one check every crossing applies to a draft in
    hand: an export, `share day` (R4) and the MCP door."""
    return line.get("kind") == KIND and under_entry(line) and not entries.allows(line)


def unit_of(line: Line) -> object:
    """The `unit` a draft line names; None for a payload that does not say (a sealed one)."""
    payload = line.get("payload")
    return payload.get("unit") if isinstance(payload, dict) else None


def allowed(root: Path) -> Allowed:
    """The entries of `root`'s policy as the readers of drafts hold them against them today: the
    `dream` entry, and the `relationship` entry for a person draft (`person_allowed`). Never raises:
    a file that is not a policy withholds every draft and says why, so the Day still reads."""
    name = policy.POLICY_FILE.as_posix()
    person = person_allowed(root)
    try:
        entry = policy.dream_today(root)
    except policy.PolicyError as e:
        return Allowed(policy.EXPIRED_TIER, f"{e}; no draft is shown until it is", person=person)
    if entry is None:
        return Allowed(
            policy.EXPIRED_TIER,
            f"{name} names no {policy.DREAM_DESTINATION!r} entry; no draft is shown",
            person=person,
        )
    if entry.expired and entry.until is not None:
        return Allowed(
            policy.EXPIRED_TIER,
            f"the {policy.DREAM_DESTINATION!r} entry expired on {entry.until.isoformat()} and counts as"
            f" max_tier 0; nothing it allowed is shown until {name} gives it a new until",
            person=person,
        )
    return Allowed(entry.max_tier, person=person)


def person_allowed(root: Path) -> Allowed:
    """The `relationship` entry as the readers of person drafts hold them against it today, read as
    the relationship reader reads it (`relationship.reader.entry`): no entry, no `until` (a lend to
    the reader has a last day) or one past it, and no person draft is shown, and `reason` says why;
    else its `max_tier` as written (the reader's cloud ceiling refuses a reading above tier 2, and no
    person draft is written above it). Never raises."""
    name = policy.POLICY_FILE.as_posix()
    try:
        entry = next((c for c in policy.ceilings(root) if c.destination == PERSON_ENTRY), None)
    except policy.PolicyError as e:
        return Allowed(policy.EXPIRED_TIER, f"{e}; no person draft is shown until it is", PERSON_ENTRY)
    if entry is None:
        return Allowed(
            policy.EXPIRED_TIER,
            f"{name} names no {PERSON_ENTRY!r} entry; no person draft is shown",
            PERSON_ENTRY,
        )
    if entry.until is None:
        return Allowed(
            policy.EXPIRED_TIER,
            f"the {PERSON_ENTRY!r} entry has no until, and a lend to the relationship reader has a last"
            " day; no person draft is shown",
            PERSON_ENTRY,
        )
    if entry.expired:
        return Allowed(
            policy.EXPIRED_TIER,
            f"the {PERSON_ENTRY!r} entry expired on {entry.until.isoformat()} and counts as max_tier 0;"
            f" nothing it allowed is shown until {name} gives it a new until",
            PERSON_ENTRY,
        )
    return Allowed(entry.max_tier, entry=PERSON_ENTRY)


def model_of(source: object) -> str:
    """`qwen2.5-7b-instruct` from `model:qwen2.5-7b-instruct`; the source as given when it is not
    a model's."""
    text = str(source)
    return text[len(SOURCE_PREFIX) :] if text.startswith(SOURCE_PREFIX) else text


# -- the standing draft -----------------------------------------------------------------------------------


def of_day(lines: Iterable[Line], retracted: Collection[str], day: str) -> list[Line]:
    """The draft lines of the day, unit `day` and subject `day`, not retracted, in `at` then `seq`
    order; a line whose payload is not a draft's is left out."""
    return by_day(lines, retracted).get(day, [])


def by_day(lines: Iterable[Line], retracted: Collection[str]) -> dict[str, list[Line]]:
    """The draft lines of unit `day`, not retracted, by the day they are about, each day's in `at`
    then `seq` order; a line whose payload is not a draft's (a sealed one this machine cannot open
    among them) is left out."""
    found: dict[str, list[Line]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA:
            continue
        subject = payload.get("subject")
        if payload.get("unit") != UNIT_DAY or not isinstance(subject, str):
            continue
        if str(line["id"]) in retracted:
            continue
        found.setdefault(subject, []).append(line)
    for day in found:
        found[day].sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    return found


def by_unit(lines: Iterable[Line], retracted: Collection[str], unit: str) -> dict[str, list[Line]]:
    """The draft lines of another unit than the day (`by_day`'s), not retracted, by each subject
    they name, each subject's in `at` then `seq` order: a `subject` that is a string is one, an
    array names every entry in it (a journey's draft names the lines or the derived id it is about,
    `trip:<first day>:<last day>`, RFC 0036); a line whose payload is not a draft's is left out."""
    found: dict[str, list[Line]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA or payload.get("unit") != unit:
            continue
        if str(line["id"]) in retracted:
            continue
        named = payload.get("subject")
        subjects = [named] if isinstance(named, str) else named if isinstance(named, list) else []
        for subject in dict.fromkeys(s for s in subjects if isinstance(s, str)):
            found.setdefault(subject, []).append(line)
    for subject in found:
        found[subject].sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    return found


def standing(found: Sequence[Line]) -> Line | None:
    """Rule 2: the latest draft not named in a later draft's `supersedes`; None when there is none."""
    if not found:
        return None
    replaced = {
        str((line.get("payload") or {}).get("supersedes"))
        for line in found
        if isinstance((line.get("payload") or {}).get("supersedes"), str)
    }
    kept = [line for line in found if str(line["id"]) not in replaced]
    return kept[-1] if kept else found[-1]


def for_day(
    idx: Index, day: str, tiers: Sequence[int] | None = None, allowed: Allowed | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The Day's `draft` block and its `draft_withheld` row. The draft: the standing draft of `day`
    read through the index, with its evidence checked against the day's lines, its proposals with
    their people's names and the event lines that confirmed them (`confirmations`), how many times the
    day was dreamed and when last; None when the day has none. Through the gate `tiers` when given:
    a draft above it is not seen, as a reader under a ceiling never sees it. Through `allowed`, the
    `dream` entry today, when given: a draft above it is not seen either, and when the standing
    draft is one of those, a reader that holds the whole record (no `tiers`) gets the row that says
    so (`withheld_json`), never its text or its proposals; None otherwise."""
    retracted = retractions(idx.retractions())
    found = of_day(idx.by_kind(KIND), retracted, day)
    shown, withheld = through(found, tiers, allowed)
    latest = standing(shown)
    if latest is None:
        return None, withheld
    lines = idx.day(day)
    on_day = {str(line["id"]) for line in lines if str(line["id"]) not in retracted}
    names: dict[str, str] = {}
    payload = latest.get("payload") or {}
    if payload.get(PROPOSALS):
        overlay = [*idx.retractions(), *idx.resolutions()]
        # a gated reader names a proposal's people only as its tiers name them (R2)
        names = person_names(
            resolve.identities_from(overlay) if tiers is None else resolve.at_tiers(overlay, tiers)[1]
        )
    confirmed = confirmations(lines, retracted, str(latest["id"]))
    # kept by a line through the gate alone: "kept as #N" for a line above it is a reference that leaks
    seen = lines if tiers is None else [line for line in lines if int(line.get("tier") or 0) in set(tiers)]
    kept = kept_keys(seen, retracted, {str(line["id"]) for line in found})
    block = day_json(latest, shown, on_day, names, confirmed, kept=kept, people=people_of(idx))
    signature = signing.signature_of(idx, day)
    block["since_signed"] = signature is not None and int(latest["seq"]) > int(signature["seq"])
    block["signed_seq"] = None if signature is None else int(signature["seq"])
    block["closing"] = None
    if any(segment["part"] == STORY for segment in block["segments"]):
        block["closing"] = closing(idx, day, tiers, retracted, ZoneInfo(str(latest.get("tz") or "UTC")))
    return block, withheld


def kept_on_day(idx: Index, day: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    """What the owner kept from any draft of `day`, the whole record read (`kept_keys`): so a page
    through a gate refuses to keep again what was kept above it, naming no line."""
    retracted = retractions(idx.retractions())
    found = of_day(idx.by_kind(KIND), retracted, day)
    return kept_keys(idx.day(day), retracted, {str(line["id"]) for line in found})


def kept_keys(
    lines: Iterable[Line], retracted: Collection[str], drafts_of_day: Collection[str]
) -> dict[tuple[Any, ...], dict[str, Any]]:
    """What the owner kept from any draft of the day (RFC 0043 §6 rule 5): by `proposal_key`, the
    `{line, seq}` of each line, not retracted, whose `extra.from` names one of `drafts_of_day`, keyed
    by the proposal it kept: its `extra.proposal` when it carries one, else, for an event line the
    owner confirmed (`confirmations`), its title and span. So a proposal of a later draft, the morning's
    after the evening's, that says what a kept one said is kept, though its `raw_id` names another
    draft."""
    found: dict[tuple[Any, ...], dict[str, Any]] = {}
    for line in sorted(lines, key=lambda line: int(line["seq"])):
        payload = line.get("payload") or {}
        extra = payload.get("extra")
        if str(line["id"]) in retracted or not isinstance(extra, dict):
            continue
        if not isinstance(extra.get(KEPT_FROM), str) or extra[KEPT_FROM] not in drafts_of_day:
            continue
        named = extra.get(KEPT_PROPOSAL)
        if isinstance(named, dict):
            key = proposal_key(named)
        elif line.get("kind") == EVENT_KIND and line.get("source") == OWNER:
            key = proposal_key(
                {
                    "kind": EVENT,
                    "title": payload.get("title"),
                    "start": line.get("at"),
                    "end": line.get("end"),
                }
            )
        else:
            key = None
        if key is not None:
            found[key] = {"line": str(line["id"]), "seq": int(line["seq"])}
    return found


def proposal_key(proposal: Mapping[str, Any]) -> tuple[Any, ...] | None:
    """What identifies a proposal across drafts (amendment 2, *kept*): an event's title (its words,
    case aside) and its span as instants; a link's entity and the lines it rests on; a kept sentence's
    part and its words, case aside (`learned`, `decision`, `ideas`, `photo`: RFC 0043 §6 rule 5). None
    for a proposal of another kind, or one whose fields do not read."""
    kind = proposal.get("kind")
    if kind in KEEPABLE:
        words = " ".join(str(proposal.get("text") or "").split()).casefold()
        return (kind, words) if words else None
    try:
        if kind == EVENT:
            title = " ".join(str(proposal.get("title") or "").split()).casefold()
            start, end = proposal.get("start"), proposal.get("end")
            if not title or not isinstance(start, str) or not isinstance(end, str):
                return None
            return (EVENT, title, _instant(start), _instant(end))
        if kind == LINK:
            evidence = proposal.get("evidence")
            if not isinstance(proposal.get("entity"), str) or not isinstance(evidence, list):
                return None
            return (LINK, proposal["entity"], tuple(sorted(str(e) for e in evidence)))
    except ValueError:
        return None
    return None


NUMBER_WORDS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten")


def closing(
    idx: Index, day: str, tiers: Sequence[int] | None, retracted: Collection[str], tz: ZoneInfo
) -> dict[str, Any] | None:
    """The goodnight story's last line, computed here and never written by a model (RFC 0043 §4.3):
    what tomorrow holds, `Tomorrow: two entries, the first at 09:00.`, from the timed calendar entries
    of the next local day, standing and folded across calendars (`events.fold`), through the gate
    `tiers`; None when it holds none."""
    tomorrow = (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).date().isoformat()
    found = [
        line
        for line in idx.by_kind(EVENT_KIND, tomorrow, tomorrow)
        if str(line["id"]) not in retracted and (tiers is None or int(line.get("tier") or 0) in tiers)
    ]
    folded, _stands_for = events.fold(found, Airlines.load())
    timed = sorted(
        (line for line in folded if (line.get("payload") or {}).get("all_day") is not True),
        key=lambda line: (_instant(str(line["at"])), int(line["seq"])),
    )
    if not timed:
        return None
    n = len(timed)
    first = _instant(str(timed[0]["at"])).astimezone(tz).strftime("%H:%M")
    count = NUMBER_WORDS[n] if n < len(NUMBER_WORDS) else str(n)
    text = (
        f"Tomorrow: one entry, at {first}." if n == 1 else f"Tomorrow: {count} entries, the first at {first}."
    )
    return {
        "text": text,
        "day": tomorrow,
        "entries": n,
        "first": first,
        "lines": [str(t["id"]) for t in timed],
    }


def for_unit(
    found: Sequence[Line],
    on_unit: Collection[str],
    tiers: Sequence[int] | None = None,
    allowed: Allowed | None = None,
    not_on: str = NOT_ON_DAY,
    *,
    people: Collection[str],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The `draft` block and the `draft_withheld` row of a unit other than the day (a journey), by
    `for_day`'s rule (`through`): `found` the unit's draft lines (`by_unit`), `on_unit` the ids of the
    lines its evidence may name, `not_on` the words for an id outside them (`NOT_ON_JOURNEY`), `people`
    the names no figure may stand beside (`people_of`, `hold_beside`)."""
    shown, withheld = through(found, tiers, allowed)
    latest = standing(shown)
    if latest is None:
        return None, withheld
    block = day_json(latest, shown, on_unit, not_on=not_on, people=people)
    block.update(unit_json(latest.get("payload") or {}, people))
    return block, withheld


def unit_json(payload: Mapping[str, Any], people: Collection[str] = ()) -> dict[str, Any]:
    """What a journey's or a week's draft keeps beside its segments, as a reader carries it: under
    `proposed` the name and the photos to star a journey's draft proposes (`name`, `star`) and the
    review a week's proposes for each goal (`goals`: `{goal, text, disposition, segment}`) and its
    one stale question (`question`: `{entity, label, status, status_line, since, text}`); under
    `numbers` what the code computed from the lines for a week (each figure with its line ids: a
    reader that prints them prints its people by name only, `names_only`); and `dropped` and `marked`,
    by why. Only the keys the draft has; a proposed name that sets a figure beside one of `people` is
    not one (`hold_beside`)."""
    extra = payload.get("extra")
    if not isinstance(extra, dict):
        return {}
    out: dict[str, Any] = {}
    proposed = {key: extra[key] for key in ("name", "star", "goals", "question") if extra.get(key)}
    if isinstance(proposed.get("name"), str) and _beside(proposed["name"], people, payload):
        del proposed["name"]
    if proposed:
        out["proposed"] = proposed
    for key in ("numbers", "dropped", "marked"):
        if isinstance(extra.get(key), dict) and extra[key]:
            out[key] = extra[key]
    return out


PERSON_KEYS = ("name", "id", "lines")  # what a reader prints of a draft's person: never a count
CHAT = "chat"  # a thread that is a chat, named by its counterpart: a person, or people


def names_only(numbers: Mapping[str, Any]) -> dict[str, Any]:
    """A draft's numbers as a reader prints them, in text or in its JSON: its people as `PERSON_KEYS`
    alone and its chats (`CHAT`, named by their counterpart) without their count, in the draft's order
    (the most first), whatever counts the line keeps beside them; no number stands beside a person
    (VISION: no metrics near people). The week page computes who moved from the line's `contacts` and
    prints none of them (`week_page._moved`)."""
    out = dict(numbers)
    people = numbers.get("people")
    if isinstance(people, list):
        out["people"] = [
            {k: p[k] for k in PERSON_KEYS if k in p} for p in people if isinstance(p, dict) and p.get("name")
        ]
    threads = numbers.get("threads")
    if isinstance(threads, list):
        out["threads"] = [
            {k: v for k, v in t.items() if k != "count"} if t.get("kind") == CHAT else t
            for t in threads
            if isinstance(t, dict)
        ]
    return out


def people_of(idx: Index) -> frozenset[str]:
    """Every name the record gives a person, whatever the tier of the line that gives it, the owner's
    aside (`present.owner_of`): the names no figure may stand beside in a draft a reader prints
    (`hold_beside`). Every tier, since holding a sentence back shows nothing."""
    lb = idx.lb
    identities = resolve.identities_from([*idx.retractions(), *idx.resolutions()])
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    return frozenset(
        who.label
        for who in identities.values()
        if who.label and who.entity and who.type in (None, "person") and who.entity not in owner.entities
    )


def _beside(text: str, people: Collection[str], payload: Mapping[str, Any]) -> bool:
    """`figures.beside_a_name` for a stored draft's words: its language, the years of its subject."""
    language = payload.get("language")
    years = figures.years_of(str(payload.get("subject") or ""))
    return figures.beside_a_name(text, people, years, language if isinstance(language, str) else None)


def hold_beside(segments: list[dict[str, Any]], people: Collection[str], payload: Mapping[str, Any]) -> int:
    """No number beside a person as a draft is read, in place (VISION: no metrics near people): a
    segment as `segment_json` shows it whose text names one of `people` and writes a figure
    (`figures.beside_a_name`, the rule the dream writes by, `dream.hold_names`) is shown as the dream
    holds one, `HELD`, unsupported, no evidence; a draft written before the rule, or by any other
    writer, prints its words nowhere. Returns how many were held."""
    held = 0
    for segment in segments:
        if segment["text"] != HELD and people and _beside(segment["text"], people, payload):
            segment.update({"text": HELD, "evidence": [], "supported": False, "why": None})
            held += 1
    return held


def through(
    found: Sequence[Line], tiers: Sequence[int] | None = None, allowed: Allowed | None = None
) -> tuple[list[Line], dict[str, Any] | None]:
    """The drafts of one unit (a day's, a call's) a reader may show, and the row for a standing draft
    it may not: the one rule `for_day` and `for_transcripts` read through. Through the gate `tiers`
    when given, a draft above it is not seen. Through `allowed`, the `dream` entry today, when given,
    a draft above it is not seen either, and when the standing draft is one of those, a reader that
    holds the whole record (no `tiers`) gets the row that says so (`withheld_json`); None otherwise."""
    if tiers is not None:
        gate = {int(t) for t in tiers}
        found = [line for line in found if int(line.get("tier", 0)) in gate]
    shown = list(found) if allowed is None else [line for line in found if allowed.allows(line)]
    withheld = None
    if allowed is not None and tiers is None:
        top = standing(found)
        if top is not None and not allowed.allows(top):
            withheld = withheld_json(top, allowed)
    return shown, withheld


def withheld_json(line: Line, allowed: Allowed) -> dict[str, Any]:
    """The row a Day carries for a standing draft the `dream` entry no longer allows: the line, its
    tier, the entry's `max_tier` today and why, in words. Nothing of what the draft says."""
    tier = int(line.get("tier") or 0)
    return {
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "tier": tier,
        "max_tier": allowed.of(unit_of(line)).max_tier,
        "why": allowed.why_not(tier, str((line.get("payload") or {}).get("unit"))),
    }


def withheld_text(row: Mapping[str, Any]) -> str:
    """`superseded by policy: tier 3, above max_tier 2 of the 'dream' entry; ...`"""
    return f"{SUPERSEDED_BY_POLICY}: {row['why']}"


def withheld(lines: Iterable[Line], retracted: Collection[str], allowed: Allowed) -> list[Line]:
    """The standing draft of every day whose standing draft `allowed` withholds, in day order: what
    `doctor` lists."""
    out = []
    for _day, found in sorted(by_day(lines, retracted).items()):
        top = standing(found)
        if top is not None and not allowed.allows(top):
            out.append(top)
    return out


def withheld_people(lines: Iterable[Line], retracted: Collection[str], allowed: Allowed) -> list[Line]:
    """The standing draft of every person whose standing draft the `relationship` entry withholds
    (`Allowed.of`), by the person's id: what `doctor` lists beside the days."""
    out = []
    for _person, found in sorted(by_unit(lines, retracted, UNIT_PERSON).items()):
        top = standing(found)
        if top is not None and not allowed.allows(top):
            out.append(top)
    return out


def person_names(identities: Mapping[resolve.Ref, resolve.Identity]) -> dict[str, str]:
    """entity id → the first label a resolution gives it, for every person the record resolves."""
    found: dict[str, str] = {}
    for who in identities.values():
        if who.entity and who.label and who.type in (None, "person"):
            found.setdefault(who.entity, who.label)
    return found


def confirmations(lines: Iterable[Line], retracted: Collection[str], draft: str) -> dict[int, dict[str, Any]]:
    """number → `{line, seq}` of the event line that confirmed each of the draft's proposals: an
    `event` line, source `owner`, not retracted, whose `extra.from` is the draft and whose `raw_id`
    is `<draft>/<number>`; the latest one when the owner confirmed it twice."""
    found: dict[int, dict[str, Any]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != EVENT_KIND or line.get("source") != OWNER or str(line["id"]) in retracted:
            continue
        extra = payload.get("extra")
        raw_id = str(payload.get("raw_id") or "")
        if not isinstance(extra, dict) or extra.get("from") != draft or not raw_id.startswith(f"{draft}/"):
            continue
        number = raw_id[len(draft) + 1 :]
        if number.isdigit():
            found[int(number)] = {"line": str(line["id"]), "seq": int(line["seq"])}
    return found


def day_json(
    line: Line,
    found: Sequence[Line],
    on_day: Collection[str] | None,
    names: Mapping[str, str] | None = None,
    confirmed: Mapping[int, dict[str, Any]] | None = None,
    not_on: str = NOT_ON_DAY,
    kept: Mapping[tuple[Any, ...], dict[str, Any]] | None = None,
    *,
    people: Collection[str],
) -> dict[str, Any]:
    """The standing draft as the Day carries it: the line, its source and model, when it was
    written, what it read, its segments each with `supported` and, when a reader holding the
    record found the evidence not on the day, `why`; its proposals (`proposals_json`, the people by
    `names`, each with the event line that `confirmed` it) and how many are of a kind this reader
    does not know (`proposals_unknown`); the ids of the earlier drafts newest
    first, how many times the day was dreamed and the day it was last. A day's draft of dream-day/4
    adds (`dream_day_json`): `evening` and `read_until`, the lenses asked and whether each was
    answered, the entity an `ideas` segment names, its proposed links (`links`), each proposal `kept`
    when the owner kept it from this draft or one with the same fields from another draft of the day
    (`kept`, by `proposal_key`), and what the writer dropped or marked. Another unit's page reads its
    draft the same way, `on_day` the unit's lines and `not_on` its own words for an id outside
    them (`NOT_ON_JOURNEY`). A segment that sets a figure beside one of `people` is held as it is
    read (`hold_beside`), whatever wrote it and whenever: its words are never printed."""
    payload = line.get("payload") or {}
    tz = ZoneInfo(str(line.get("tz") or "UTC"))
    problems = validate(payload, reader=True)
    segments = [
        segment_json(s, on_day, not_on) for s in (payload.get("segments") or []) if isinstance(s, dict)
    ]
    hold_beside(segments, people, payload)
    parts = (payload.get("extra") or {}).get("parts") if isinstance(payload.get("extra"), dict) else None
    unit = str(payload.get("unit"))
    known = UNIT_PARTS.get(unit, DAY_PARTS)  # each unit's parts, a day's for any other
    if isinstance(parts, list) and len(parts) == len(segments):
        for segment, part in zip(segments, parts, strict=True):
            lens = (
                unit == UNIT_DAY and isinstance(part, str) and part.startswith(LENS) and len(part) > len(LENS)
            )
            segment["part"] = str(part) if part in known or lens else None
    else:
        for segment in segments:
            segment["part"] = None
    earlier = [str(other["id"]) for other in reversed(found) if other["id"] != line["id"]]
    last = max((str(other["at"]) for other in found), default=str(line["at"]))
    shown = proposals_json(payload, on_day, tz, names or {}, confirmed or {}, not_on)
    for p in shown:  # kept from another draft of the day: confirmed by that line, never accepted twice
        p["kept"] = p["confirmed"] or (kept or {}).get(proposal_key(p) or ())
        p["confirmed"] = p["kept"]
    out = {
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "source": str(line.get("source")),
        "model": model_of(line.get("source")),
        "tier": line.get("tier"),
        "at": str(line["at"]),
        "read_head": payload.get("read_head"),
        "read_count": payload.get("read_count"),
        "language": payload.get("language"),
        "segments": segments,
        "unsupported": sum(1 for s in segments if not s["supported"]),
        "proposals": shown,
        "proposals_unknown": unknown_proposals(payload),
        "supersedes": payload.get("supersedes"),
        "earlier": earlier,
        "dreamed": len(found),
        "last": _instant(last).astimezone(tz).date().isoformat(),
        "malformed": problems,
    }
    if unit == UNIT_DAY:
        out.update(dream_day_json(payload, segments, on_day, kept or {}, not_on))
    return out


def keep_numbers(payload: Mapping[str, Any], segments: Sequence[Mapping[str, Any]]) -> dict[int, int]:
    """What `--keep` numbers in a day's draft (RFC 0043 §5): segment index (from 0) → its number. A
    link keeps the number it has among the proposals; a sentence of a part one keeps (`KEEPABLE`)
    is numbered after the last proposal, in the draft's order, so a number never names two things
    and `--accept`'s numbers never move. Read from the draft alone, so the numbers stay while the
    draft stands."""
    found = payload.get(PROPOSALS)
    n = len(found) if isinstance(found, list) else 0
    numbers: dict[int, int] = {}
    for i, segment in enumerate(segments):
        if segment.get("part") in KEEPABLE:
            n += 1
            numbers[i] = n
    return numbers


def dream_day_json(
    payload: Mapping[str, Any],
    segments: list[dict[str, Any]],
    on_day: Collection[str] | None,
    kept: Mapping[tuple[Any, ...], dict[str, Any]],
    not_on: str = NOT_ON_DAY,
) -> dict[str, Any]:
    """What a day's draft carries beside its segments since dream-day/4, as a reader shows it (each
    key on every day draft, empty or false for an older one): `evening` and `read_until`, the moment an
    evening draft read up to (amendment 2); `lenses`, `{id, text, answered}` for each lens asked (a lens
    with no segment is printed by the reader as `NO_ANSWER`, never by the model); `entity` on each
    `ideas` segment, the idea it names; `links`, the proposed links (`links_json`), each `kept` when
    the owner kept one of the same fields from any draft of the day, and its `keep`, the number
    `--keep` takes (its proposal number); `keep` and `kept` on each segment of a part one keeps
    (`keep_numbers`); and `marked`, `dropped`, `dropped_links`, `dropped_segments`, by why. Sets
    `entity`, `keep` and `kept` on the segments in place."""
    found_extra = payload.get("extra")
    extra: Mapping[str, Any] = found_extra if isinstance(found_extra, dict) else {}
    answered = {str(s["part"])[len(LENS) :] for s in segments if str(s.get("part") or "").startswith(LENS)}
    found_lenses, found_ideas = extra.get("lenses"), extra.get("ideas")
    asked: list[Any] = found_lenses if isinstance(found_lenses, list) else []
    lenses = [
        {"id": str(lens["id"]), "text": str(lens.get("text") or ""), "answered": str(lens["id"]) in answered}
        for lens in asked
        if isinstance(lens, dict) and isinstance(lens.get("id"), str) and lens["id"]
    ]
    ideas: list[Any] = found_ideas if isinstance(found_ideas, list) else []
    for idea in ideas:
        n = idea.get("segment") if isinstance(idea, dict) else None
        if (
            isinstance(n, int)
            and not isinstance(n, bool)
            and 1 <= n <= len(segments)
            and segments[n - 1]["part"] == IDEAS
            and isinstance(idea.get("entity"), str)
        ):
            segments[n - 1]["entity"] = idea["entity"]
    links = links_json(payload, on_day, not_on)
    for link in links:
        link["keep"] = link["number"]
        link["kept"] = kept.get(proposal_key(link) or ())
    for i, number in keep_numbers(payload, segments).items():
        segment = segments[i]
        segment["keep"] = number
        segment["kept"] = kept.get(proposal_key({"kind": segment["part"], "text": segment["text"]}) or ())
    until = extra.get("read_until")
    out: dict[str, Any] = {
        "evening": extra.get("evening") is True,
        "read_until": until if isinstance(until, str) else None,
        "lenses": lenses,
        "links": links,
    }
    for key in ("marked", "dropped", "dropped_links", "dropped_segments"):
        out[key] = dict(extra[key]) if isinstance(extra.get(key), dict) else {}
    return out


def links_json(
    payload: Mapping[str, Any], on_day: Collection[str] | None, not_on: str = NOT_ON_DAY
) -> list[dict[str, Any]]:
    """The draft's proposed links (amendment 2), each numbered by its place among all its proposals,
    as `proposals_json` numbers the events: the entity, the text, the note, the evidence, and
    `supported` when every evidence id is a line of the day (when the reader holds it), else `why`."""
    found = payload.get(PROPOSALS)
    out: list[dict[str, Any]] = []
    for n, proposal in enumerate(found if isinstance(found, list) else [], 1):
        if not link_shape(proposal):
            continue
        evidence = [str(e) for e in proposal["evidence"]]
        outside = on_day is not None and any(e not in on_day for e in evidence)
        out.append(
            {
                "number": n,
                "kind": LINK,
                "entity": str(proposal["entity"]),
                "text": " ".join(str(proposal["text"]).split()),
                "note": proposal.get("note"),
                "evidence": evidence,
                "supported": not outside,
                "why": not_on if outside else None,
            }
        )
    return out


def segment_json(
    segment: Mapping[str, Any], on_day: Collection[str] | None, not_on: str = NOT_ON_DAY
) -> dict[str, Any]:
    """One segment with its verdict: supported when every evidence id is a line of the day (when
    the reader holds the day; any id otherwise), or of the unit `on_day` names; else unsupported with
    `why`, `not_on` when an id is not among them."""
    shape = segment_shape(segment)
    text = str(segment.get("text") or "").strip()
    if shape == SUPPORTED:
        evidence = [str(e) for e in segment["evidence"]]
        missing = [e for e in evidence if on_day is not None and e not in on_day]
        if missing:
            return {"text": text, "evidence": evidence, "supported": False, "why": not_on}
        return {"text": text, "evidence": evidence, "supported": True, "why": None}
    if shape == UNSUPPORTED:
        return {"text": text, "evidence": [], "supported": False, "why": None}
    return {"text": text or "(no text)", "evidence": [], "supported": False, "why": NOT_A_SEGMENT}


def proposals_json(
    payload: Mapping[str, Any],
    on_day: Collection[str] | None,
    tz: ZoneInfo,
    names: Mapping[str, str],
    confirmed: Mapping[int, dict[str, Any]],
    not_on: str = NOT_ON_DAY,
) -> list[dict[str, Any]]:
    """The draft's event proposals as a reader shows them, each numbered by its place in the list
    (a malformed one, a link, which `links_json` lists, or one of a kind this reader does not know, is
    left out, and its number with it): the title, the span in UTC and in `tz`,
    the place and where that is in words, the people by id and name, the evidence, `supported` when
    every evidence id is a line of the day (when the reader holds the day), else `why` (`not_on`);
    and `confirmed`, the event line that confirmed it, or None."""
    found = payload.get(PROPOSALS)
    out: list[dict[str, Any]] = []
    for n, proposal in enumerate(found if isinstance(found, list) else [], 1):
        if not proposal_shape(proposal):  # an event's; a link is `links_json`'s
            continue
        evidence = [str(e) for e in proposal["evidence"]]
        outside = on_day is not None and any(e not in on_day for e in evidence)
        place = proposal.get("place")
        out.append(
            {
                "number": n,
                "kind": EVENT,
                "title": " ".join(str(proposal["title"]).split()),
                "start": proposal["start"],
                "end": proposal["end"],
                "start_local": _instant(proposal["start"]).astimezone(tz).isoformat(timespec="seconds"),
                "end_local": _instant(proposal["end"]).astimezone(tz).isoformat(timespec="seconds"),
                "place": place,
                "where": where_of(place),
                "people": [{"id": p, "name": names.get(p)} for p in proposal["people"]],
                "evidence": evidence,
                "supported": not outside,
                "why": not_on if outside else None,
                "confirmed": confirmed.get(n),
            }
        )
    return out


def where_of(place: object) -> str | None:
    """A proposal's place in words: a named place's name; an observed place's coordinates."""
    if not isinstance(place, str) or not place:
        return None
    return place[len(CLUSTER) :] if place.startswith(CLUSTER) else place


def cluster_coordinates(place: str) -> tuple[float, float] | None:
    """(lat, lon) of an observed place's id, `place:59.9200,10.7400`; None for any other place."""
    if not place.startswith(CLUSTER):
        return None
    try:
        lat, lon = (float(part) for part in place[len(CLUSTER) :].split(","))
    except ValueError:
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


# -- a transcript's synthesis ------------------------------------------------------------------------------


def subject_ids(payload: Mapping[str, Any]) -> list[str]:
    """The ids a draft's `subject` names: the list, or the one string; empty for anything else."""
    subject = payload.get("subject")
    if isinstance(subject, str):
        return [subject]
    if isinstance(subject, list):
        return [str(s) for s in subject if isinstance(s, str)]
    return []


def by_transcript(lines: Iterable[Line], retracted: Collection[str]) -> dict[str, list[Line]]:
    """The syntheses, as `by_day` gives the days' drafts: the draft lines of unit `event` whose
    subject is one line's id alone (a transcript's), not retracted, by that id, each one's in `at`
    then `seq` order; a line whose payload is not a draft's is left out."""
    found: dict[str, list[Line]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA or payload.get("unit") != UNIT_EVENT:
            continue
        subject = subject_ids(payload)
        if len(subject) != 1 or str(line["id"]) in retracted:
            continue
        found.setdefault(subject[0], []).append(line)
    for transcript in found:
        found[transcript].sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    return found


def for_transcripts(
    idx: Index, transcripts: Sequence[str], tiers: Sequence[int] | None = None, allowed: Allowed | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The Day's `syntheses` and its `syntheses_withheld` rows, read through the rule `for_day` reads
    a day's draft through (`through`). The syntheses: the standing synthesis of each of these
    transcript lines that has one, in the order given, each with its evidence checked against its
    transcript (`synthesis_json`). Through the gate `tiers` when given, a synthesis above it is not
    seen; through `allowed`, the `dream` entry today, one above the entry is not seen either, and a
    reader that holds the whole record gets the row for a standing synthesis the entry withholds, the
    transcript's id first (`withheld_json`), never its text."""
    if not transcripts:
        return [], []
    by = by_transcript(idx.by_kind(KIND), retractions(idx.retractions()))
    out, held = [], []
    for transcript in transcripts:
        shown, withheld = through(by.get(transcript, []), tiers, allowed)
        latest = standing(shown)
        if latest is not None:
            out.append(synthesis_json(latest, shown, transcript))
        if withheld is not None:
            held.append({"transcript": transcript, **withheld})
    return out, held


def synthesis_json(line: Line, found: Sequence[Line], transcript: str) -> dict[str, Any]:
    """A transcript's standing synthesis as the Day carries it: the transcript it is of, the draft
    line, its source and model, what it read, its segments (`synthesis_segments`), how many of each
    part and how many unsupported, the earlier syntheses newest first and how many there were."""
    payload = line.get("payload") or {}
    tz = ZoneInfo(str(line.get("tz") or "UTC"))
    segments = synthesis_segments(payload, {transcript})
    found_extra = payload.get("extra")
    extra: Mapping[str, Any] = found_extra if isinstance(found_extra, dict) else {}
    last = max((str(other["at"]) for other in found), default=str(line["at"]))
    return {
        "transcript": transcript,
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "source": str(line.get("source")),
        "model": model_of(line.get("source")),
        "tier": line.get("tier"),
        "at": str(line["at"]),
        "read_head": payload.get("read_head"),
        "language": payload.get("language"),
        "utterances": extra.get("utterances"),
        "segments": segments,
        "counts": {part: sum(1 for s in segments if s["part"] == part) for part in SYNTHESIS_PARTS},
        "unsupported": sum(1 for s in segments if not s["supported"]),
        "supersedes": payload.get("supersedes"),
        "earlier": [str(other["id"]) for other in reversed(found) if other["id"] != line["id"]],
        "synthesized": len(found),
        "last": _instant(last).astimezone(tz).date().isoformat(),
        "malformed": validate(payload, reader=True),
    }


def synthesis_segments(
    payload: Mapping[str, Any], transcript: Collection[str] | None
) -> list[dict[str, Any]]:
    """The segments of a synthesis with their verdict (`segment_json`, the transcript's id the only
    evidence a segment may name when `transcript` is given) and what `extra.segments` keeps of each:
    `part`, `utterances` (`[{n, offset}]`), `assignee` and `due` (`{phrase, date}`), each None or
    empty when the line does not say."""
    found = payload.get("segments")
    raw = [s for s in found if isinstance(s, dict)] if isinstance(found, list) else []
    found_extra = payload.get("extra")
    extra: Mapping[str, Any] = found_extra if isinstance(found_extra, dict) else {}
    details = extra.get("segments")
    if not isinstance(details, list) or len(details) != len(raw):
        details = [{}] * len(raw)
    out = []
    for segment, detail in zip(raw, details, strict=True):
        shown = segment_json(segment, transcript, NOT_THE_TRANSCRIPT)
        detail = detail if isinstance(detail, dict) else {}
        part = detail.get("part")
        shown["part"] = part if part in SYNTHESIS_PARTS else None
        shown["utterances"] = [
            {"n": u["n"], "offset": u.get("offset") if isinstance(u.get("offset"), str) else None}
            for u in detail.get("utterances") or []
            if isinstance(u, dict) and isinstance(u.get("n"), int) and not isinstance(u.get("n"), bool)
        ]
        assignee = detail.get("assignee")
        shown["assignee"] = assignee if isinstance(assignee, str) and assignee else None
        due = detail.get("due")
        shown["due"] = (
            {
                "phrase": str(due.get("phrase") or ""),
                "date": due.get("date") if isinstance(due.get("date"), str) else None,
            }
            if isinstance(due, dict) and due.get("phrase")
            else None
        )
        out.append(shown)
    return out


def synthesis_summary(block: Mapping[str, Any]) -> str:
    """`synthesis · 1 action, 2 topics, 1 decision, 1 open thread, 1 personal · model:qwen2.5-7b-instruct`,
    the Day's one row for a synthesis, collapsed; with `· N unsupported` when any is."""
    counts = block.get("counts") or {}
    found = [
        f"{n} {SYNTHESIS_NOUNS[part][0 if n == 1 else 1]}"
        for part in SYNTHESIS_PARTS
        if (n := int(counts.get(part) or 0))
    ]
    parts = ["synthesis", ", ".join(found) or "no items"]
    if block.get("unsupported"):
        parts.append(f"{block['unsupported']} unsupported")
    if block.get("malformed"):
        parts.append("malformed")
    parts.append(str(block["source"]))
    return DOT.join(parts)


def is_withheld(block: Mapping[str, Any]) -> bool:
    """Whether a block of the Day's is the row of a draft the `dream` entry withholds (`withheld_json`:
    no segments, the reason why) rather than a draft it shows."""
    return "segments" not in block and "why" in block


def synthesis_row(block: Mapping[str, Any]) -> str:
    """The one row under a call on the Day: its synthesis, collapsed (`synthesis_summary`), or, for a
    synthesis the `dream` entry withholds, `superseded by policy` and why (`withheld_text`)."""
    return withheld_text(block) if is_withheld(block) else synthesis_summary(block)


def synthesis_rows(segments: Sequence[Mapping[str, Any]], indent: str = "    ") -> Iterator[str]:
    """The segments of a synthesis, one per row: the part's word, the text, an action's assignee and
    due hint (`assignment_text`), then where in the call it rests (`where_text`); an unsupported one
    starts with `~` and ends with the word."""
    for segment in segments:
        label = SYNTHESIS_LABELS.get(str(segment.get("part")), "")
        mark = "  " if segment["supported"] else "~ "
        assigned = assignment_text(segment)
        who = f"  {assigned}" if assigned else ""
        if segment["supported"]:
            tail = f"[{where_text(segment)}]"
        else:
            tail = UNSUPPORTED if not segment.get("why") else f"{UNSUPPORTED}: {segment['why']}"
        yield f"{indent}{mark}{label:<9} {segment['text']}{who}  {tail}"


def assignment_text(segment: Mapping[str, Any]) -> str:
    """`→ Ola Nordmann · due by Friday (2026-06-12?)`: an action's assignee and due hint, the date a
    reading of the words (SPEC §3.2.10 rule 4); empty when the segment names neither."""
    parts = []
    if segment.get("assignee"):
        parts.append(f"→ {segment['assignee']}")
    due = segment.get("due")
    if due:
        parts.append(f"due {due['phrase']}" + (f" ({due['date']}?)" if due.get("date") else ""))
    return DOT.join(parts)


def where_text(segment: Mapping[str, Any]) -> str:
    """Where in the call a segment rests: `02:10, 20:05`, `u3, u17` when the recording gives no time,
    `the transcript` when it rests on the line and no utterance of it."""
    return ", ".join(utterance_text(u) for u in segment.get("utterances") or []) or WHOLE


def utterance_text(utterance: Mapping[str, Any]) -> str:
    """`20:05` where the recording gives the utterance's time, else `u17`."""
    return str(utterance["offset"]) if utterance.get("offset") else f"u{utterance['n']}"


# -- text ------------------------------------------------------------------------------------------------


def head_text(draft: Mapping[str, Any], word: bool = True) -> str:
    """`draft · model:qwen2.5-7b-instruct · read at bb97e90d · 5 lines · dreamed 2×, last on
    2026-06-14 · 1 unsupported`; without the leading word when the row's label says it."""
    head = str(draft.get("read_head") or "")[:HEAD_SHORT]
    n = draft.get("read_count")
    parts = [
        *(["draft"] if word else []),
        str(draft["source"]),
        *([EVENING] if draft.get("evening") else []),
        f"read at {head}",
        f"{n} line{'s' if n != 1 else ''}",
        f"dreamed {draft['dreamed']}×, last on {draft['last']}",
    ]
    if draft["unsupported"]:
        parts.append(f"{draft['unsupported']} unsupported")
    proposals = draft.get("proposals") or []
    if proposals:
        confirmed = sum(1 for p in proposals if p.get("confirmed"))
        n = len(proposals)
        parts.append(
            f"{n} proposed event{'s' if n != 1 else ''}" + (f", {confirmed} confirmed" if confirmed else "")
        )
    links = draft.get("links") or []
    if links:
        n, kept = len(links), sum(1 for p in links if p.get("kept"))
        parts.append(f"{n} proposed link{'s' if n != 1 else ''}" + (f", {kept} kept" if kept else ""))
    if draft.get("since_signed"):
        parts.append(SINCE_SIGNED)
    if draft.get("malformed"):
        parts.append("malformed: " + "; ".join(draft["malformed"]))
    return DOT.join(parts)


def rows(draft: Mapping[str, Any], indent: str = "    ") -> Iterator[str]:
    """The segments, one per row: the part's word, the text, then the evidence ids shortened and, for a
    part one keeps, `keep N`, the number `--keep` takes, or `kept as #seq` once the owner kept it; an
    unsupported one starts with `~` and ends with `unsupported` (and why, when a reader found
    out), never run into the prose around it. After the last sentence of the story, its closing line
    as the reader computed it (`closing`); after the lenses answered, each lens asked and not
    answered, `NO_ANSWER`; then the proposals. A draft dreamed after the day's signature shows only
    what the owner has not kept, under `since you signed`."""
    segments = list(draft["segments"])
    closing_row = draft.get("closing")
    unanswered = [lens for lens in draft.get("lenses") or [] if not lens.get("answered")]
    told = not closing_row
    for i, segment in enumerate(segments):
        part = str(segment.get("part") or "")
        if not told and part != STORY and any(s.get("part") == STORY for s in segments[:i]):
            yield f"{indent}  {'':<9} {closing_row['text']}"  # type: ignore[index]
            told = True
        if unanswered and part != STORY and not part.startswith(LENS):
            yield from _unanswered(unanswered, indent)
            unanswered = []
        yield _segment_row(segment, indent)
    if not told:
        yield f"{indent}  {'':<9} {closing_row['text']}"  # type: ignore[index]
    yield from _unanswered(unanswered, indent)
    events_, links = draft.get("proposals") or [], draft.get("links") or []
    if draft.get("since_signed"):
        events_ = [p for p in events_ if not p.get("kept")]
        links = [p for p in links if not p.get("kept")]
        if events_ or links:
            yield f"{indent}  {SINCE_SIGNED}"
    yield from proposal_rows(sorted([*events_, *links], key=lambda p: int(p["number"])), indent)


def _segment_row(segment: Mapping[str, Any], indent: str) -> str:
    part = str(segment.get("part") or "")
    label = PART_LABELS.get(part, part if part.startswith(LENS) else "") if part else ""
    mark = "  " if segment["supported"] else "~ "
    if segment.get("kept"):
        tail = f"kept as #{segment['kept']['seq']}"
    elif segment["supported"]:
        # a word before the ids: an id may open with a digit, and the sentence may end with a name
        tail = EVIDENCE + " [" + ", ".join(short_id(e) for e in segment["evidence"]) + "]"
    else:
        tail = UNSUPPORTED if not segment.get("why") else f"{UNSUPPORTED}: {segment['why']}"
    if segment.get("keep") and segment["supported"] and not segment.get("kept"):  # `--keep`'s number (RFC
        tail += (
            f"  keep {segment['keep']}"  # 0043 §5), at the end: never beside a name the sentence opens with
        )
    return f"{indent}{mark}{label:<9} {segment['text']}  {tail}"


def _unanswered(lenses: Iterable[Mapping[str, Any]], indent: str) -> Iterator[str]:
    """A lens the day gave no segment for, in the reader's words (`NO_ANSWER`), never the model's."""
    for lens in lenses:
        yield f"{indent}  {LENS + str(lens['id']):<9} {NO_ANSWER}"


def extra_rows(block: Mapping[str, Any], indent: str = "    ") -> Iterator[str]:
    """The rows after a journey's or a week's segments (`unit_json`, or a payload's `extra` as a
    writer has it): the name and the photos it proposes, the reviews it proposes for the goals, the
    week's stale question, the week's numbers, and what was dropped or marked; nothing for a block
    without them."""
    found = block.get("proposed")
    proposed: Mapping[str, Any] = found if isinstance(found, dict) else {}
    extra = block.get("extra")
    if isinstance(extra, dict):  # a payload as the writer has it
        proposed = {key: extra[key] for key in ("name", "star", "goals", "question") if extra.get(key)}
        block = {key: extra[key] for key in ("numbers", "dropped", "marked") if extra.get(key)}
    if proposed.get("name"):
        yield f"{indent}? {'name':<9} {proposed['name']}  proposed"
    star = proposed.get("star") or []
    if star:
        n = len(star)
        yield (
            f"{indent}? {'star':<9} {n} photo{'s' if n != 1 else ''}  proposed  ["
            + ", ".join(short_id(i) for i in star)
            + "]"
        )
    for review in proposed.get("goals") or []:
        yield f"{indent}? {'review':<9} {review['disposition']} for “{review['text']}”  proposed"
    question = proposed.get("question")
    if isinstance(question, dict) and question.get("text"):
        yield f"{indent}? {'question':<9} {question['text']}  asked once"
    numbers = block.get("numbers")
    if isinstance(numbers, dict):
        yield from number_rows(numbers, indent)
    for key in ("dropped", "marked"):
        counted = block.get(key)
        if isinstance(counted, dict) and counted:
            k = sum(int(n) for n in counted.values())
            why = ", ".join(f"{reason} {n}" for reason, n in counted.items())
            yield f"{indent}  {k} {'dropped' if key == 'dropped' else 'marked unsupported'}: {why}"


def number_rows(numbers: Mapping[str, Any], indent: str = "    ") -> Iterator[str]:
    """A week's numbers, one row each: the hours by place, the people by name in the draft's order
    (the most time together first), the threads (a chat by its counterpart alone, a title quoted with
    its kind and its count, `_thread_text`), and the energy (`no data` when the health lines under the
    ceiling hold none); never a count beside a name (`names_only`)."""
    numbers = names_only(numbers)
    places = numbers.get("places") or []
    if places:
        yield f"{indent}  {'hours':<9} " + DOT.join(f"{p['place']} {p['hours']} h" for p in places)
    people = numbers.get("people") or []
    if people:
        yield f"{indent}  {'with':<9} " + DOT.join(str(p["name"]) for p in people)
    threads = numbers.get("threads") or []
    if threads:
        yield f"{indent}  {'threads':<9} " + DOT.join(map(_thread_text, threads))
    energy = numbers.get("energy")
    if isinstance(energy, dict):
        said = []
        sleep, training = energy.get("sleep"), energy.get("training")
        if sleep:
            said.append(f"sleep {sleep['nights']} nights, {sleep['hours']} h")
        if training:
            said.append(f"training {training['sessions']} sessions, {training['minutes']} min")
        yield f"{indent}  {'energy':<9} " + (DOT.join(said) or "no data")


def _thread_text(t: Mapping[str, Any]) -> str:
    """A chat by its counterpart alone; a title quoted, then its kind and its count in words,
    `“Dinner with Ola Nordmann” calendar 1 time`: a word on either side of the count, so it stands
    beside no name, the title's own or the next thread's (`seen` for a draft that kept no kind)."""
    if t.get("kind") == CHAT:
        return str(t["thread"])
    count = t["count"]
    return f"“{t['thread']}” {t.get('kind') or 'seen'} {count} {'time' if count == 1 else 'times'}"


def unit_rows(
    label: str, draft: Mapping[str, Any] | None, withheld: Mapping[str, Any] | None
) -> Iterator[str]:
    """A journey's or a week's draft under its row: the head (`head_text`) and its segments, the
    proposals and numbers after them (`extra_rows`); or, withheld by the `dream` entry, the one row
    that says so and nothing of its text; nothing when it has neither."""
    if draft is not None:
        yield f"  {label}{DOT}{head_text(draft)}"
        yield from rows(draft)
        yield from extra_rows(draft)
    elif withheld is not None:
        yield f"  {label}{DOT}draft{DOT}{withheld_text(withheld)}"


def proposal_rows(proposals: Iterable[Mapping[str, Any]], indent: str = "    ") -> Iterator[str]:
    """One row per proposal, after the segments: the title, the place, the span and the people, or what
    a link links, then `(event N)` or `(link N)`, the number `--accept` and `--keep` take, after the
    words so it never stands beside a name; then `proposed` and the evidence, set apart with a leading
    `?` (greyed on the page), or `confirmed as #seq` once the owner accepted it (`kept as #seq` when
    it was kept from another draft of the day), or `~` and `unsupported` when a reader found its
    evidence not on the day."""
    for p in proposals:
        label = f"{p.get('kind') or EVENT} {p['number']}"
        if p.get("confirmed"):
            mark, tail = "  ", f"confirmed as #{p['confirmed']['seq']}"
        elif p.get("kept"):
            mark, tail = "  ", f"kept as #{p['kept']['seq']}"
        elif not p["supported"]:
            mark, tail = "~ ", f"{UNSUPPORTED}: {p['why']}" if p.get("why") else UNSUPPORTED
        else:
            mark, tail = "? ", "proposed  [" + ", ".join(short_id(e) for e in p["evidence"]) + "]"
        # the number after the words, never before them: a proposal's text may open with a name (the owner)
        yield f"{indent}{mark}{proposal_text(p)} ({label})  {tail}"


def proposal_text(p: Mapping[str, Any]) -> str:
    """The title, the place, the span in words, the people: `Dinner with Kari Nordmann · Bistro
    Eksempel · from 19:30 to 22:10 · with Kari Nordmann`; a link's text, and its note when it has
    one. A title may open or close with a name, so the clocks stand behind a word, never beside it
    (the owner, 27 October)."""
    if p.get("kind") == LINK:
        return DOT.join(str(x) for x in (p["text"], p.get("note")) if x)
    parts = [str(p["title"])]
    if p.get("where"):
        parts.append(str(p["where"]))
    parts.append(f"from {str(p['start_local'])[11:16]} to {str(p['end_local'])[11:16]}")
    people = [str(who.get("name") or who["id"]) for who in p.get("people") or []]
    if people:
        parts.append("with " + ", ".join(people))
    return DOT.join(parts)


def short_id(line_id: str) -> str:
    return f"…{line_id[-ID_SHORT:]}" if len(line_id) > ID_SHORT else line_id


def row_text(payload: Mapping[str, Any]) -> str:
    """The row `show` prints for a draft line: `draft of day 2026-06-13 · 5 lines read at bb97e90d
    · 7 segments, 1 unsupported`."""
    found = payload.get("segments")
    segments: list[Any] = found if isinstance(found, list) else []
    unsupported = sum(1 for s in segments if segment_shape(s) != SUPPORTED)
    head = str(payload.get("read_head") or "")[:HEAD_SHORT]
    subject = payload.get("subject")
    subject_text = ", ".join(subject) if isinstance(subject, list) else str(subject)
    if isinstance(subject, list) and len(subject) > SUBJECT_SHOWN:  # a journey's id and its lines
        subject_text = f"{', '.join(subject[:1])} and {len(subject) - 1} lines"
    n = payload.get("read_count")
    parts = [
        f"draft of {payload.get('unit')} {subject_text}",
        f"{n} line{'s' if n != 1 else ''} read at {head}",
        f"{len(segments)} segment{'s' if len(segments) != 1 else ''}"
        + (f", {unsupported} unsupported" if unsupported else ""),
    ]
    proposals = payload.get(PROPOSALS)
    if isinstance(proposals, list) and proposals:
        links = sum(1 for p in proposals if isinstance(p, dict) and p.get("kind") == LINK)
        n = len(proposals) - links
        if n:
            parts.append(f"{n} proposed event{'s' if n != 1 else ''}")
        if links:
            parts.append(f"{links} proposed link{'s' if links != 1 else ''}")
    if payload.get("supersedes"):
        parts.append("supersedes an earlier draft")
    return DOT.join(parts)


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
