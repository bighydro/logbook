"""The dream (`logbook dream day DAY`, `logbook dream --catch-up`): a model reads one day of the
record and writes one `draft/v1` line about it (RFC 0036, `logbook.core.drafts`), in the parts of
dream-day/4 (RFC 0043 §13.4, `day_parts`): the goodnight story, one answer per lens, the threads it
moved, what was learned and decided, the ideas it moved, one question for the owner's reflection, and
proposals, the people it thinks were there, the promises it thinks were made and the photo of the day,
every sentence pointing at the lines it came from. The dream is a proposal; the owner's signature
and notes are the facts.

Sending a day to a model is a crossing like any other, so it is governed by `policy/crossing.json`
(ADR 0016, ADR 0022): the `dream` entry's `max_tier` is the ceiling the day is read under, its
`until` the last day it holds, and its optional `model` the one model the day may go to. No entry,
or an expired one, and the dream refuses in one sentence and nothing leaves the machine.

What the model sees (`material`) is the Day as the day reader shows it under that ceiling
(`day.read(..., tiers)`): the nights, the stays and moves with what attached to each and who was
there, the flights, what is unplaced, the health line when tier 3 is allowed; then the day's
messages by counterpart with their count and, since a message line is in the reading only when its
tier is under the ceiling, their text, an agent's marked (`agent` on its counterpart, `machine` on
the text it wrote; `logbook.core.machine`), so the model never takes a bot for a person; the notes
in full; the commitments on the day; the day's photos, the owner's own camera first, then the starred
(`_photos`); and the owner's note on signing it; and, when the day is dreamed (`enrich`), what the day
was for (`for`: the chapter it is in and its rule, the open goals), the ideas and orgs the owner named,
by id, and the lenses of
`policy/questions.json` (`"ask": "day"`, RFC 0027). Never a raw line above the ceiling. Every item
carries a reference (`L1`, `L2`, ...) that stands for one line id of the day, so the model cites
references and the record keeps ids. The prompt is `dream-prompt.md` beside this
module (docs/dream-prompt.md explains it); it asks for one JSON object of segments `{text,
evidence}` and says which language to write in: the language most of the day's own text is in
(`language_of`).

The answer is checked before anything is written (`segments_of`): a segment whose every reference
is one the material gave is supported and carries the ids; one with a reference the day does not
have, or none, is marked unsupported; a segment without text is dropped. Each part's own rule
then drops what breaks it and counts it under `extra.dropped_segments` (`day_segments`): six sentences
of story at most, one segment per lens and none without evidence, one question, an idea only by an id
the material named, one photo resting on one photo of the day; a figure the cited items do not give
marks the sentence (`hold_numbers`), and one that writes a figure beside a person's name is held, its
words dropped and its slot kept with the reason (`hold_names`). When more than `UNSUPPORTED_SHARE` of
the segments are unsupported the answer is refused and nothing is written.
The draft's tier is the highest tier among the lines it read, not the lines it cited (RFC 0036);
`read_count` is how many it read; `read_head` the record's head at that moment. The whole dream,
reading, the model's turn and the write, runs inside the record's writer lock (`Logbook.writer`,
#237), and the head is read again before the append: a head that moved is `HeadMoved` and nothing
is written. Dreaming a day again writes a new line whose `supersedes` names the standing draft; the
same model at the same head under the same entry writes nothing and says so (RFC 0036 rule 1). The
dream never writes a note, a signature or a review. Every draft records the version of the entry it
was dreamed under (`extra.policy_version`, `policy.version`: the SHA-256 of its `max_tier`, `until`
and `model`).

**Proposed events.** Beside its segments the model proposes the events it thinks the day held, `{title,
start, end, place, people, evidence}` (`proposals_of`): a stay at a restaurant with two photos and a
recording is a dinner with the people in it. The material names what a proposal may point at: each
stay's `place` (a named place by its name, else the observed place by its id, `place:<lat>,<lon>`),
the canonical people the day names under `people` (`id`, `name`; never the owner), and the
references. A proposal is checked as a segment is, and more strictly, since it has no unsupported
form: a time not on the day, a place not on the day, an evidence reference the day does not have,
and a person who is not one of the day's canonical people (a name, an id the record does not resolve,
the owner) each drop it, and the drops are counted by why under `extra.dropped`. What survives is
kept in the draft line under `proposals`, kind `event` (`drafts.proposal_shape`), never as an event
line: the owner confirms one with `day sign --accept N` (`logbook.contrib.dream_events`). Proposed
links (`draft/v1` amendment 2, `links_of`) follow the events in `proposals`: `{kind: link, entity,
text, evidence, note?}`, the entity an idea or an org the material named, dropped and counted under
`extra.dropped_links` otherwise.

**The evening** (`dream day TODAY --evening`): today so far, `extra.evening` and `extra.read_until`
on the draft; a day that is not today is refused, and the catch-up never dreams today.

`--catch-up` dreams each of the last N days that has no draft, or whose lines today differ from
what the standing draft compared (`why_again_day`, RFC 0043 §6 rules 4 to 6: the lines the close writes
left out, `kept`; on a signed day only a line that came after the signature and the draft; kept as
`extra.compared_count` and `extra.compared_ids_sha256`, and for an older draft its `read_count` and
`extra.read_ids_sha256`), or whose standing draft the entry no longer stands behind: its tier above
the entry's `max_tier` today, or dreamed under another version of the entry. Derived material follows
the policy, not the head, so a lowered ceiling or a moved `until` is a change of the day as much as a
new line is, and the day is dreamed again under the entry as it is now, superseding the old draft.
An expired entry dreams nothing (the refusal before any day); the readers withhold what it allowed
(`drafts.allowed`). One line per day; what the morning schedule calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from string import Template
from typing import Any
from zoneinfo import ZoneInfo

from ..core import chapter as chapters
from ..core import day as day_reader
from ..core import (
    day_start,
    drafts,
    goals,
    machine,
    notes,
    policy,
    present,
    reading,
    resolve,
    signing,
    stays,
)
from ..core import stars as starred
from ..core.chain import Line
from ..core.export import parse_day
from ..core.figures import CALENDAR as CALENDAR
from ..core.figures import LETTER_AFTER, LETTER_BEFORE, WORD, figures, years_of
from ..core.figures import MONTHS as MONTHS
from ..core.figures import NUMBER as NUMBER
from ..core.figures import NUMBER_WORDS as NUMBER_WORDS
from ..core.figures import YEAR as YEAR
from ..core.figures import beside_a_name as named_beside
from ..core.flights import Airports
from ..core.index import Index
from ..core.reading import Reading
from ..core.resolve import Ref
from ..core.store import HeadMoved, Logbook, now_utc, retractions
from . import entities, model_client, questions
from .model_client import Endpoint, Transport
from .promises import chat_ref

PROMPT_FILE = Path(__file__).with_name("dream-prompt.md")
# kept under `extra.prompt`, so a draft says which prompt wrote it; 2 added the events, 3 rule 5 (agents),
# 4 the goodnight story, the lenses, learned, decided, the ideas, the photo, the links and one question
PROMPT_NAME = "dream-day/4"
UNSUPPORTED_SHARE = 0.30  # more than this share of segments unsupported: refused, nothing written
TEXT_CHARS = 400  # a message's text in the material, at most
NOTE_CHARS = 1500  # a note's text in the material, at most
MESSAGES_PER_COUNTERPART = 25  # the texts given per counterpart; the count is always whole
# never material; `heard` (RFC 0046): the listen or watch it belongs to is, and a text that lands
# later is no reason to dream a day again
EXCLUDED_KINDS = frozenset({"retraction", "signed-day", drafts.KIND, "crossing", "heard"})
DEFAULT_LANGUAGE = "en"
DOT = " \u00b7 "
HEAD_MOVED = (
    "the record's head moved from {was} to {now} while the model read the {unit}, so the draft would not"
    " say what it read; nothing was written, dream the {unit} again"
)
EVENTS = "events"  # the key of the answer that holds the proposed events
LINKS = "links"  # the key of the answer that holds the proposed links (draft/v1 amendment 2)
STORY_SENTENCES = 6  # the goodnight story: five or six sentences, at most six kept
QUESTIONS_KEPT = 1  # one question for the reflection (RFC 0043 §7), where dream-day/3 asked two
LINKS_KEPT = 4  # the links a draft proposes, at most
PHOTOS_GIVEN = 12  # the photos of the day the material lists, own camera first, starred first
NAMED_GIVEN = 40  # the named ideas and orgs the material lists, each kind, by name
# why a segment of the answer was dropped, the keys of `extra.dropped_segments`
DROP_STORY = "story beyond six sentences"
DROP_QUESTION = "a second question"
DROP_LENS = "a lens answered twice"
DROP_LENS_UNSUPPORTED = "a lens answered without evidence"
DROP_IDEA = "an idea the material did not name"
DROP_PHOTO = "not one photo of the day"
DROP_PHOTO_TWICE = "a second photo"
# why a proposed link was dropped, the keys of `extra.dropped_links`
DROP_LINK_SHAPE = "not a link"
DROP_LINK_ENTITY = "an entity the material did not name"
DROP_LINK_TEXT = "no text"
DROP_LINK_MANY = "beyond four links"
DROP_BESIDE_A_NAME = "a number beside a person"  # an event or a link dropped for a figure beside a name
# a line the close writes, which never makes the day be dreamed again (RFC 0043 §6 rule 4): a line whose
# `extra.from` names a draft of the day, and the reflection and its delegations
KEPT_LABELS = (notes.REFLECTION, notes.DELEGATION)
LONGEST_EVENT = timedelta(hours=24)  # a proposed event lasts less than a day and a night
# why a proposed event was dropped, the keys of `extra.dropped`
DROP_SHAPE = "not an event"
DROP_TITLE = "no title"
DROP_TIME = "a time not on the day"
DROP_PLACE = "a place not on the day"
DROP_PERSON = "unresolved person"
DROP_EVIDENCE = "evidence not on the day"
CLOCK = re.compile(r"(\d{1,2}):(\d{2})\Z")
LANGUAGE_NAMES = {"en": "English", "nb": "Norwegian", "de": "German", "fr": "French", "es": "Spanish"}
# the commonest short words of each language the dream recognises, matched whole and lower-cased
STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {"the", "and", "with", "for", "was", "were", "from", "this", "that", "have", "not", "you"}
    )
    | frozenset({"are", "at", "on", "of", "to", "in"}),
    "nb": frozenset({"og", "med", "for", "var", "fra", "det", "den", "har", "ikke", "jeg", "du", "er"})
    | frozenset({"på", "til", "av", "som", "en", "et", "ei"}),
    "de": frozenset({"und", "mit", "für", "war", "aus", "das", "der", "die", "hat", "nicht", "ich", "du"})
    | frozenset({"ist", "auf", "zu", "von", "ein", "eine"}),
    "fr": frozenset({"et", "avec", "pour", "était", "dans", "le", "la", "les", "est", "pas", "je", "tu"})
    | frozenset({"sur", "une", "un", "des", "du", "au"}),
    "es": frozenset({"y", "con", "para", "era", "desde", "el", "la", "los", "las", "es", "no", "yo"})
    | frozenset({"tú", "en", "una", "un", "del", "al", "que"}),
}
# -- the number rule (`hold_numbers`): a figure a sentence writes is one the code computed from lines --
UNBACKED = "a number the lines do not give"  # the key of `extra.marked`: a segment marked for a figure
BESIDE_A_NAME = "a number beside a person"  # the key of `extra.marked` for a figure beside a name
HELD = drafts.HELD  # a held segment's text: the model's words are dropped, the slot kept
# the keys whose words are the record's own, whose figures an item gives (a model's are under `drafted`)
SCANNED = frozenset(
    {"title", "flight", "where", "place", "subject", "quote", "text", "name", "chat", "thread", "counterpart"}
)


class DreamError(ValueError):
    """The dream refuses: the policy, the endpoint, the day or the answer; one sentence, nothing
    written."""


class AnswerError(DreamError):
    """The model answered and the answer failed: not reachable, not JSON, no segment, or too many
    unsupported; the day was sent and nothing was written."""


@dataclass
class Material:
    """What the model is given about one day, and what the record keeps about that reading."""

    day: str  # the unit's subject in words: the day, a journey's id, a week
    tier: int  # the highest tier among the lines read: the draft's tier
    read_count: int
    read_head: str
    read_ids_sha256: str
    language: str
    data: dict[str, Any]  # the JSON the prompt carries
    refs: dict[str, str] = field(default_factory=dict)  # `L1` -> line id
    ids: set[str] = field(default_factory=set)  # every line id read on the day
    zone: ZoneInfo = field(default_factory=lambda: ZoneInfo("UTC"))  # the record's
    span: tuple[datetime, datetime] | None = None  # where the day starts and ends on the record's clock
    places: set[str] = field(default_factory=set)  # the place ids the material gave
    canonical: dict[str, str] = field(default_factory=dict)  # every canonical person: id -> name
    people: dict[str, str] = field(default_factory=dict)  # the canonical people the material names
    identities: dict[Ref, resolve.Identity] = field(default_factory=dict)
    withheld: frozenset[str] = frozenset()  # the names only a resolution above the ceiling gives (`Names`)
    unit: str = drafts.UNIT_DAY  # what the material is of: a day, a journey, a week
    compared: dict[str, int] = field(default_factory=dict)  # the ids `--catch-up` compares -> seq (rule 4)
    photos: set[str] = field(default_factory=set)  # the references of the day's photos the material gave
    named: dict[str, str] = field(default_factory=dict)  # the ideas and orgs the material named: id -> kind
    lenses: list[dict[str, str]] = field(default_factory=list)  # the lenses asked: {id, text}
    enriched: bool = False  # whether the named things, the chapter, the goals and the lenses were added
    _by_id: dict[str, str] = field(default_factory=dict)  # line id -> `L1`

    def ref_of(self, line_id: str | None) -> str | None:
        """The reference that stands for a line of the day, minted on first use; None for a line
        that is not on the day (the night before's), which the model cannot cite."""
        if not line_id or line_id not in self.ids:
            return None
        found = self._by_id.get(line_id)
        if found is not None:
            return found
        ref = f"L{len(self.refs) + 1}"
        self.refs[ref] = line_id
        self._by_id[line_id] = ref
        return ref

    @property
    def compared_sha256(self) -> str:
        """The digest of the ids `--catch-up` compares (`extra.compared_ids_sha256`)."""
        return digest(self.compared)

    def refs_of(self, ids: Iterable[str | None]) -> list[str]:
        return [ref for ref in (self.ref_of(i) for i in ids) if ref is not None]

    def person(self, entity: str | None) -> str | None:
        """The entity id when it is a canonical person, noted as one the day names; else None."""
        if not entity or entity not in self.canonical:
            return None
        self.people.setdefault(entity, self.canonical[entity])
        return entity

    def name_of(self, name: str | None) -> str | None:
        """`name` as the material may carry it: None for one only a resolution above the entry's
        tiers gives (`withheld`), as a reader that resolves the whole record (the promises) names it."""
        return None if name is not None and name in self.withheld else name

    def withholds(self, text: str) -> bool:
        """Whether `text` names someone by a name only a resolution above the entry's tiers gives
        (`withheld`, no letter stuck to either end: `Per Hemmelig2` names him): a drafted sentence a
        unit reads (a day's in a week, a week's in a chapter) written before the dream read names at
        its entry's tiers, never passed on (R2)."""
        return any(
            re.search(rf"{LETTER_BEFORE}{re.escape(name)}{LETTER_AFTER}", text) for name in self.withheld
        )

    def person_of(self, ref: Ref | None) -> str | None:
        """The canonical person a ref resolves to, noted as one the day names; else None."""
        if ref is None:
            return None
        entity, _label = present.resolve_ref(ref, self.identities)
        return self.person(entity)


@dataclass(frozen=True)
class Dream:
    """What a dream of one day came to: the draft line written (None under `--dry-run`), the
    payload, the prompt's messages and the model's raw answer; the proposed events as the Day
    shows them, and how many were dropped, by why."""

    day: str
    line: Line | None
    payload: dict[str, Any]
    tier: int
    messages: list[dict[str, str]]
    answer: str
    proposals: list[dict[str, Any]] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    links: list[dict[str, Any]] = field(default_factory=list)  # the proposed links, as the Day shows them
    closing: dict[str, Any] | None = None  # the story's closing line, computed (`drafts.closing`)

    def shown(self) -> dict[str, Any]:
        """The draft as `drafts.rows` prints it: the segments with their parts, the lenses asked and
        whether each was answered, the closing line, the proposed events and links."""
        extra = self.payload.get("extra") or {}
        segments = [drafts.segment_json(s, None) for s in self.payload["segments"]]
        for segment, part in zip(segments, extra.get("parts") or [], strict=False):
            segment["part"] = part
        block: dict[str, Any] = {"segments": segments, "proposals": self.proposals}
        block.update(drafts.dream_day_json(self.payload, segments, None, {}))
        block["closing"] = self.closing if any(s["part"] == drafts.STORY for s in segments) else None
        return block


@dataclass(frozen=True)
class Outcome:
    """One row of `--catch-up`: the day, what happened (`dreamed`, `unchanged`, `empty`, `refused`)
    and the detail."""

    day: str
    state: str
    detail: str


# -- the policy and the endpoint -------------------------------------------------------------------------


def ceiling(lb: Logbook) -> policy.Ceiling:
    """The `dream` entry of the crossing policy as it counts today; `DreamError` when there is
    none, when it has expired, or when the file is not a policy."""
    try:
        return policy.dream_entry(lb.root)
    except policy.PolicyError as e:
        raise DreamError(str(e)) from e


def endpoint(found: policy.Ceiling, env: Mapping[str, str] | None = None) -> Endpoint:
    """The model endpoint from the environment (`env`, else the process's), the policy's `model`
    winning when the entry names one; an environment that names another model is refused, since
    the entry is a ceiling, not a default."""
    env = os.environ if env is None else env
    try:
        made = model_client.from_env(env, found.model)
    except model_client.ModelError as e:
        raise DreamError(str(e)) from e
    named = (env.get(model_client.MODEL_ENV) or "").strip()
    if found.model and named and named != found.model:
        raise DreamError(
            f"{policy.POLICY_FILE.as_posix()} names the model {found.model!r} for"
            f" {policy.DREAM_DESTINATION!r} and {model_client.MODEL_ENV} says {named!r}; make them agree"
        )
    return made


# -- the material -----------------------------------------------------------------------------------------


def material(lb: Logbook, day: str, found: policy.Ceiling, airports: Airports | None = None) -> Material:
    """The day's material under the entry's ceiling: the Day as the reader shows it through the
    gate, the messages by counterpart, the notes, the commitments and the signing note, each item
    with its reference. The lines read are the day's lines under the ceiling, the kinds that are
    about the record rather than the day left out (`EXCLUDED_KINDS`)."""
    day = parse_day(day).isoformat()
    tiers = tiers_of(found)
    data = day_reader.read(lb, day, airports, tiers, names_at=tiers)
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        on_day = [
            line
            for line in reading.crossing(idx.day(day), tiers)
            if str(line["id"]) not in retracted and line.get("kind") not in EXCLUDED_KINDS
        ]
        known = names_for(lb, found, idx)
        names, identities = known.labels, known.identities
        dreamed = {str(line["id"]) for line in drafts.of_day(idx.by_kind(drafts.KIND), retracted, day)}
    on_day.sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    ids = {str(line["id"]) for line in on_day}
    tier = max((int(line.get("tier", 1)) for line in on_day), default=1)
    texts = _texts(on_day)
    made = Material(
        day=day,
        tier=tier,
        read_count=len(on_day),
        read_head=str(lb.meta["head"]),
        read_ids_sha256=digest(ids),
        language=language_of(texts),
        data={},
        ids=ids,
        zone=days.zone,
        span=days.span(day),
        canonical=known.canonical(lb),
        identities=identities,
        withheld=known.withheld,
        compared={str(line["id"]): int(line["seq"]) for line in on_day if not kept(line, dreamed)},
    )
    made.data = _data(data, on_day, names, made, found.max_tier)
    made.tier = max(made.tier, known.tier_in(made.data))
    return made


def kept(line: Line, dreamed: Collection[str]) -> bool:
    """Whether `line` is one the close wrote, which never makes the day be dreamed again (RFC 0043 §6
    rule 4): a line whose `extra.from` names one of the day's drafts (`dreamed`: an event the owner
    accepted, a sentence or a link kept), and the owner's reflection and its delegations. A star is the
    day's like any line: it changes the photos the material gives."""
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    if (
        isinstance(extra, dict)
        and isinstance(extra.get(drafts.KEPT_FROM), str)
        and extra[drafts.KEPT_FROM] in dreamed
    ):
        return True
    return any(notes.labelled(line, label) for label in KEPT_LABELS)


def enrich(lb: Logbook, made: Material, found: policy.Ceiling) -> None:
    """What dream-day/4 adds to a day's material, under the entry's ceiling as the rest of it, once,
    when the day is dreamed (a catch-up's comparison never pays for it): what the day was for (`for`,
    the chapter it is in and its rule, the open goals), the named ideas and orgs with their ids (the
    only ids an idea or a link may name), and the lenses of the bank (`questions.lenses`, `"ask":
    "day"`). Each from a scan of its own kind through the index, a few lines each; never the touches
    a shelf reads. The draft's tier rises to the highest of the chapter, goal and entity lines given."""
    if made.enriched:
        return
    tiers = tiers_of(found)
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = retractions(marks)
        chapter_lines = reading.crossing(idx.by_kind(chapters.KIND), tiers)
        goal_lines = reading.crossing(idx.by_kind(goals.KIND), tiers)
        review_lines = reading.crossing(idx.by_kind(goals.REVIEW), tiers)
        entity_lines = reading.crossing(idx.by_kind(entities.ENTITY), tiers)
    held, _clash = chapters.of_day(chapters.chapter_lines(chapter_lines, retracted), made.day)
    chapter: dict[str, Any] | None = None
    if held is not None:
        payload = held.get("payload") or {}
        first, last = chapters.span(held)
        chapter = {
            "name": payload.get("name"),
            "rules": payload.get("rules") or "",
            "from": first,
            "to": last,
        }
    drawn: list[Line] = [] if held is None else [held]  # every line the model is given beside the day's
    standing = goals.Goals(goal_lines, retracted)
    reviews = goals.review_lines(review_lines, retracted)
    open_lines = [
        goal
        for goal in standing.standing()
        if goals.state(goal, goals.standing_review(reviews, standing.chain(str(goal["id"]))), made.day)
        == "open"
    ]
    drawn += open_lines
    open_goals = [
        {"id": str(goal["id"]), "text": str((goal.get("payload") or {}).get("text") or "")}
        for goal in open_lines
    ]
    # what the day was for (RFC 0043 §4.1), under one key: a month's and a chapter's material have their
    # own `chapter` and `goals`, and a day's is not one of theirs
    made.data["for"] = {"chapter": chapter, "goals": open_goals}
    named = entities.canonical([*marks, *entity_lines])
    listed: list[dict[str, Any]] = []
    for kind in (entities.IDEA, entities.ORG):
        of_kind = sorted((e for (k, _i), e in named.items() if k == kind), key=lambda e: (e.label, e.id))
        for e in of_kind[:NAMED_GIVEN]:
            listed.append({"id": e.id, "kind": kind, "name": e.label})
            made.named[e.id] = kind
            drawn += [line for line in entity_lines if str(line["id"]) in e.lines]
    made.data["named"] = listed
    # the draft's tier is the highest among the lines it read (RFC 0036): these as much as the day's
    made.tier = max([made.tier, *(int(line.get("tier") or 1) for line in drawn)])
    try:
        made.lenses = [{"id": q.id, "text": q.text} for q in questions.lenses(lb.root)]
    except policy.PolicyError as e:
        raise DreamError(str(e)) from e
    made.data["lenses"] = list(made.lenses)
    made.enriched = True


@dataclass(frozen=True)
class Names:
    """The people overlay as a unit's material may read it under the entry's ceiling (`names_for`):
    the labels and the identities of the refs whose every resolution line, the alias hops included,
    is at one of the entry's tiers, and the tier each name was learned at (the highest of those
    lines)."""

    labels: dict[Ref, str]
    identities: dict[Ref, resolve.Identity]
    tiers: dict[Ref, int]
    every: dict[Ref, resolve.Identity]  # every identity, whatever its tier: whom the owner is found from
    withheld: frozenset[str]  # every label only a ref resolved through a line above the ceiling has

    def canonical(self, lb: Logbook) -> dict[str, str]:
        """The canonical people the material may name (`canonical`), the owner found from every tier."""
        return canonical(lb, self.identities, self.every)

    def tier_in(self, data: Any) -> int:
        """The highest tier of a resolution that supplied a name `data` carries (a label, no letter
        stuck to either end, a digit may be, anywhere in it); 1 when it carries none. The draft's tier
        rises to it: a name is read as much as a line is (RFC 0036)."""
        text = json.dumps(data, ensure_ascii=False)
        top = 1
        for ref, tier in self.tiers.items():
            label = self.labels.get(ref)
            if tier > top and label and re.search(rf"{LETTER_BEFORE}{re.escape(label)}{LETTER_AFTER}", text):
                top = tier
        return top


def names_for(lb: Logbook, found: policy.Ceiling, idx: Index | None = None) -> Names:
    """The people overlay at the entry's tiers, the one way every unit's material learns who is who:
    the record's resolutions and retractions read as `resolve.identities_from` reads them, then every
    ref whose walk passes through a resolution line above the entry's `max_tier` left out, so a name
    learned only above the ceiling, or a ref resolved through such a line, is never in the material
    (R2). Through the caller's open index, else a fresh one closed before returning."""
    if idx is None:
        with lb.index() as own:
            return names_for(lb, found, own)
    lines = [*idx.retractions(), *idx.resolutions()]
    allowed = resolve.tiers_of(lines, tiers_of(found))
    labels, identities = resolve.at_tiers(lines, tiers_of(found))
    every = resolve.identities_from(lines)
    given = set(labels.values())
    withheld = {who.label for who in every.values() if who.label} | set(resolve.labels_from(lines).values())
    withheld -= given
    # a withheld name's first name too (three letters or more, as `beside_a_name` reads one), unless a
    # name the entry gives shares it: "Per" is withheld for Per Hemmelig, not while Per Hansen is given
    firsts = {n.split()[0] for n in given if n.split()}
    withheld |= {n.split()[0] for n in withheld if len(n.split()[0]) >= 3} - firsts - given
    return Names(labels, identities, allowed, every, frozenset(withheld))


def canonical(
    lb: Logbook,
    identities: Mapping[Ref, resolve.Identity],
    every: Mapping[Ref, resolve.Identity] | None = None,
) -> dict[str, str]:
    """Every canonical person of the record, id -> name: the entities the resolution lines name as
    a person after the alias walk (a person merged into another is not one), never the owner, who is
    found from `every` identity when given (a material's are those at the entry's tiers, `Names`)."""
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities if every is None else every,
    )
    return {e: name for e, name in drafts.person_names(identities).items() if e not in owner.entities}


def _texts(lines: Iterable[Line]) -> list[str]:
    """The day's own words: notes, message texts, event titles, mail subjects, transcript titles;
    never an agent's (`logbook.core.machine`), which say nothing of the language the owner lives in."""
    out = []
    for line in lines:
        payload = line.get("payload") or {}
        if machine.is_machine(payload):
            continue
        for key in ("text", "title", "subject"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value)
    return out


def language_of(texts: Iterable[str]) -> str:
    """The language most of the day's text is in, by counting each language's commonest words;
    `en` when nothing decides it."""
    words = Counter(w.lower() for text in texts for w in WORD.findall(text))
    scores = {tag: sum(n for w, n in words.items() if w in stop) for tag, stop in STOPWORDS.items()}
    best = max(scores.values(), default=0)
    if best == 0:
        return DEFAULT_LANGUAGE
    winners = sorted(tag for tag, score in scores.items() if score == best)
    return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in winners else winners[0]


def _data(
    data: Mapping[str, Any], on_day: Sequence[Line], names: Mapping[Ref, str], made: Material, max_tier: int
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "day": data["day"],
        "weekday": data["weekday"],
        "tz": data["tz"],
        "max_tier": max_tier,
        "night_before": _night(data["nights"]["before"], made),
        "night_after": _night(data["nights"]["after"], made),
        "country": data["country"].get("code"),
        "all_day": [
            {"title": a["title"], "ref": made.refs_of(a.get("lines") or [a["line"]])} for a in data["all_day"]
        ],
        "timeline": [_entry(e, made) for e in data["timeline"]],
        "unplaced": [
            {
                "kind": u["kind"],
                "at": u["at"],
                "title": u["title"],
                "ref": made.refs_of(u.get("lines") or [u["line"]]),
            }
            for u in data["unplaced"]
        ],
        "messages": _messages(on_day, names, made),
        "notes": _notes(on_day, made),
        "commitments": _commitments(on_day, names, made),
        "photos": _photos(on_day, made),
    }
    named = sorted(made.people.items(), key=lambda p: (p[1], p[0]))
    out["people"] = [{"id": e, "name": name} for e, name in named]  # the only ids a proposal may hold
    if data.get("health"):
        out["health"] = day_reader.health_text(data["health"])
    signed = data.get("signed")
    if isinstance(signed, dict):
        out["signed"] = {"at": signed["at"], "note": signed.get("note")}
    return out


def _night(night: Mapping[str, Any], made: Material) -> dict[str, Any]:
    if night["in_transit"]:
        return {"where": "in transit"}
    return {
        "where": night["where"],
        "home": night["home"],
        "ref": made.refs_of(night.get("lines") or []),
    }


def _entry(entry: Mapping[str, Any], made: Material) -> dict[str, Any]:
    if entry["kind"] == day_reader.FLIGHT:
        return {
            "kind": "flight",
            "start": entry["start_local"],
            "end": entry["end_local"],
            "flight": f"{entry['carrier']} {entry['number']} {entry['from']} to {entry['to']}",
            "ref": made.refs_of([entry["line"]]),
        }
    lines = entry.get("lines") or {}
    out: dict[str, Any] = {
        "kind": "gap" if entry.get("gap") else entry["kind"],
        "start": entry["start_local"],
        "end": entry["end_local"],
        "where": entry.get("where"),
        "ref": made.refs_of([lines.get("first"), lines.get("last")]),
    }
    place = _place_id(entry)
    if place is not None:
        out["place"] = place
        made.places.add(place)
    if entry["kind"] == "move" and entry.get("mode"):
        out["mode"] = entry["mode"]
    if entry.get("airports"):
        out["airports"] = list(entry["airports"])
    attached = entry.get("attached")
    if attached:
        out["events"] = [
            {"title": e["title"], "ref": made.refs_of(e.get("lines") or [e["line"]])}
            for e in attached["events"]
        ]
        out["transcripts"] = [
            {"title": t["title"], "ref": made.refs_of([t["line"]])} for t in attached["transcripts"]
        ]
        out["mail"] = [
            {"subject": m["subject"], "messages": m["messages"], "ref": made.refs_of(m["lines"])}
            for m in attached["mail"]
        ]
        out["calls"] = [
            {
                "who": c["who"],
                "direction": c["direction"],
                "answered": c["answered"],
                "ref": made.refs_of([c["line"]]),
            }
            for c in attached["calls"]
        ]
        out["photos"] = {
            "count": attached["photos"]["count"],
            "ref": made.refs_of(attached["photos"]["lines"][:12]),
        }
        out["keepers"] = [{"name": k["name"], "ref": made.refs_of([k["line"]])} for k in attached["keepers"]]
        for key in ("events", "transcripts", "mail", "calls", "keepers"):
            if not out[key]:
                del out[key]
        if not out["photos"]["count"]:
            del out["photos"]
    company = entry.get("with")
    if company and (company["confirmed"] or company["proposed"]):
        out["with"] = {
            "confirmed": [_companion(c, made) for c in company["confirmed"]],
            "proposed": [_companion(c, made) for c in company["proposed"]],
        }
    inside = entry.get("inside")
    if inside:
        out["inside"] = [_entry({**s, "attached": None, "with": None}, made) for s in inside]
    return out


def _place_id(entry: Mapping[str, Any]) -> str | None:
    """The id a proposal names a stay's place by: the named place's name, else the observed place at
    its centre, `place:<lat>,<lon>` (as `places review` names a cluster and the Day links to it);
    None for a move, a gap, a flight or a stay aboard an asset."""
    if entry.get("gap") or entry.get("kind") not in (stays.STAY, stays.STOP) or entry.get("aboard"):
        return None
    if entry.get("place"):
        return str(entry["place"])
    lat, lon = entry.get("lat"), entry.get("lon")
    if lat is None or lon is None:
        return None
    return f"{drafts.CLUSTER}{float(lat):.4f},{float(lon):.4f}"


def _companion(c: Mapping[str, Any], made: Material) -> dict[str, Any]:
    """Someone at a stay as the model sees them: the name, the references, and the person's id when
    they are a canonical person, the id a proposal names them by."""
    out: dict[str, Any] = {"name": c["name"], "ref": made.refs_of(c["lines"])}
    person = made.person(c.get("person"))
    if person is not None:
        out["person"] = person
    return out


def _chat_key(payload: Mapping[str, Any]) -> tuple[bool, str, str]:
    """(direct, key, name) of a message's chat: a string `chat` is a direct chat's name (SPEC
    §3.2); a direct chat is one counterpart whichever way its messages went."""
    chat = payload.get("chat")
    if isinstance(chat, str):
        chat = {"type": "direct", "name": chat}
    elif not isinstance(chat, dict):
        chat = {}
    name = str(chat.get("name") or "")
    key = str(chat.get("id") or name)
    return chat.get("type") in (None, "direct"), key, name


def _counterpart(payload: Mapping[str, Any], names: Mapping[Ref, str]) -> str | None:
    """The other party of a direct chat as the record names them: the resolved sender of a message
    not from the owner, else the name the source showed for it, else the ref the chat's id names
    (`chat_ref`) resolved; None when nothing in this message says."""
    direct, key, _name = _chat_key(payload)
    sender = payload.get("sender")
    if direct and not payload.get("from_me") and isinstance(sender, dict):
        kind, value = sender.get("kind"), sender.get("value")
        if isinstance(kind, str) and isinstance(value, str) and (kind, value) in names:
            return names[(kind, value)]
        own = sender.get("name")
        if isinstance(own, str) and own:
            return own
    ref = chat_ref(key) if direct else None
    if ref is not None and ref in names:
        return names[ref]
    return None


def _messages(on_day: Sequence[Line], names: Mapping[Ref, str], made: Material) -> list[dict[str, Any]]:
    """The day's messages by counterpart, a direct chat one counterpart and a group its name: the
    count, the references, and the texts (a message in the reading is under the ceiling, so its
    text may be read), at most MESSAGES_PER_COUNTERPART of them, each shortened to TEXT_CHARS."""
    by: dict[str, dict[str, Any]] = {}
    for line in on_day:
        if line.get("kind") != "message":
            continue
        payload = line.get("payload") or {}
        direct, key, name = _chat_key(payload)
        entry = by.setdefault(
            ("direct:" if direct else "group:") + key,
            {
                "counterpart": None,
                "count": 0,
                "ref": [],
                "texts": [],
                "group": not direct,
                "chat": name or key,
            },
        )
        entry["count"] += 1
        if machine.with_agent(payload):
            entry["agent"] = True  # the counterpart is an agent the owner runs, never a person
        if entry["counterpart"] is None:
            entry["counterpart"] = _counterpart(payload, names)
        if direct and "person" not in entry:
            person = made.person_of(_sender_ref(payload)) or made.person_of(chat_ref(key))
            if person is not None:
                entry["person"] = person
        ref = made.ref_of(str(line["id"]))
        entry["ref"].append(ref)
        text = payload.get("text")
        if len(entry["texts"]) < MESSAGES_PER_COUNTERPART:
            body = (
                text
                if isinstance(text, str) and text.strip()
                else f"[{payload.get('media_kind') or 'media'}]"
            )
            said = {"ref": ref, "from_me": bool(payload.get("from_me")), "text": _clip(body, TEXT_CHARS)}
            if machine.is_machine(payload):
                said["machine"] = True  # an agent's words: machine text, never a person's
            entry["texts"].append(said)
    out = []
    for entry in by.values():
        chat = entry.pop("chat")
        if entry["counterpart"] is None:
            entry["counterpart"] = f"{chat} (group)" if entry["group"] else (chat or "withheld")
        elif entry["group"]:
            entry["counterpart"] = f"{chat} (group)"
        out.append(entry)
    return sorted(out, key=lambda e: (-e["count"], e["counterpart"]))


def _sender_ref(payload: Mapping[str, Any]) -> Ref | None:
    """The sender's ref of a message the owner did not write; None for the owner's own."""
    sender = payload.get("sender")
    if payload.get("from_me") or not isinstance(sender, dict):
        return None
    kind, value = sender.get("kind"), sender.get("value")
    return (kind, value) if isinstance(kind, str) and isinstance(value, str) and value else None


def _photos(on_day: Sequence[Line], made: Material) -> list[dict[str, Any]]:
    """The day's photos the photo of the day may be (RFC 0043 §12), the owner's own camera first, then
    the starred, then by time, at most `PHOTOS_GIVEN`: each its reference, the clock, where it came
    from (`provenance`, RFC 0002) and whether the owner starred it already."""
    stars = starred.standing(on_day)
    found = [line for line in on_day if line.get("kind") == "photo"]

    def order(line: Line) -> tuple[bool, bool, str, int]:
        payload = line.get("payload") or {}
        return (
            payload.get("provenance") != "camera",
            str(line["id"]) not in stars,
            str(line["at"]),
            int(line["seq"]),
        )

    out = []
    for line in sorted(found, key=order)[:PHOTOS_GIVEN]:
        payload = line.get("payload") or {}
        ref = made.ref_of(str(line["id"]))
        if ref is None:
            continue
        made.photos.add(ref)
        at = datetime.fromisoformat(str(line["at"]).replace("Z", "+00:00")).astimezone(made.zone)
        out.append(
            {
                "ref": [ref],
                "at": at.strftime("%H:%M"),
                "provenance": payload.get("provenance") or "other",
                "starred": str(line["id"]) in stars,
            }
        )
    return out


def _notes(on_day: Sequence[Line], made: Material) -> list[dict[str, Any]]:
    return [
        {
            "ref": made.ref_of(str(line["id"])),
            "text": _clip(str((line.get("payload") or {}).get("text") or ""), NOTE_CHARS),
        }
        for line in on_day
        if line.get("kind") == "note" and (line.get("payload") or {}).get("text")
    ]


def _commitments(on_day: Sequence[Line], names: Mapping[Ref, str], made: Material) -> list[dict[str, Any]]:
    out = []
    for line in on_day:
        if line.get("kind") != "commitment":
            continue
        payload = line.get("payload") or {}
        who = payload.get("counterparty")
        label, person = None, None
        if isinstance(who, dict) and isinstance(who.get("kind"), str) and isinstance(who.get("value"), str):
            label = names.get((who["kind"], who["value"])) or who["value"]
            person = made.person_of((who["kind"], who["value"]))
        item: dict[str, Any] = {
            "ref": made.ref_of(str(line["id"])),
            "text": _clip(str(payload.get("text") or ""), TEXT_CHARS),
            "direction": payload.get("direction"),
            "counterparty": label,
            "due": payload.get("due"),
        }
        if person is not None:
            item["person"] = person
        out.append(item)
    return out


def _clip(text: str, chars: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= chars else text[: chars - 1] + "…"


# -- the material of a span of days: a journey's, a week's -----------------------------------------------


def tiers_of(found: policy.Ceiling) -> tuple[int, ...]:
    """The gate the entry's ceiling is: every tier from 1 to its `max_tier`."""
    return tuple(range(1, found.max_tier + 1))


def lines_of_days(rd: Reading, first: str, last: str) -> list[Line]:
    """The lines a reading holds on the local days `first` to `last`, the kinds about the record
    rather than the days left out (`EXCLUDED_KINDS`), in `at` then `seq` order. A gated reading's:
    nothing above its gate is among them, and nothing retracted."""
    found = [
        line
        for line in rd.lines
        if first <= rd.day_of(line) <= last and line.get("kind") not in EXCLUDED_KINDS
    ]
    return sorted(found, key=lambda line: (str(line["at"]), int(line["seq"])))


def days_of(
    rd: Reading, days: Sequence[str], made: Material
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Each day of a span as the model is given it, from the Day reader over the reading (`day.
    of_reading`): the weekday, the night after it, and its timeline as a day's material has it
    (`_entry`), each stay and stop with the `hours` of it that fell on the day; and the places of
    the span, each with the hours spent there over all its days, how many days, and the references
    of the stays. Hours are computed here, from the stays' first and last lines, to one decimal."""
    by_day: dict[str, list[Line]] = {}
    for line in rd.lines:
        by_day.setdefault(rd.day_of(line), []).append(line)
    out: list[dict[str, Any]] = []
    places: dict[str, dict[str, Any]] = {}
    for day in days:
        page = day_reader.of_reading(rd, day, None, by_day.get(day, []))
        start, end = rd.day_start.span(day)
        timeline = []
        for entry in page["timeline"]:
            item = _entry(entry, made)
            hours = _hours_on(entry, start, end)
            if hours is not None:
                item["hours"] = hours
                label = str(entry.get("place") or entry.get("where") or "")
                if label:
                    kept = places.setdefault(
                        label, {"place": label, "seconds": 0.0, "days": set(), "ref": []}
                    )
                    kept["seconds"] += _seconds_on(entry, start, end)
                    kept["days"].add(day)
                    kept["ref"] += [r for r in item["ref"] if r not in kept["ref"]]
            timeline.append(item)
        out.append(
            {
                "day": day,
                "weekday": page["weekday"],
                "night_after": _night(page["nights"]["after"], made),
                "timeline": timeline,
            }
        )
    ranked = sorted(places.values(), key=lambda p: (-p["seconds"], p["place"]))
    totals = [
        {
            "place": p["place"],
            "hours": round(p["seconds"] / 3600, 1),
            "days": len(p["days"]),
            "ref": p["ref"][:12],
        }
        for p in ranked
    ]
    return out, totals


def _seconds_on(entry: Mapping[str, Any], start: datetime, end: datetime) -> float:
    begun = datetime.fromisoformat(str(entry["start_local"]))
    ended = datetime.fromisoformat(str(entry["end_local"]))
    return max((min(ended, end) - max(begun, start)).total_seconds(), 0.0)


def _hours_on(entry: Mapping[str, Any], start: datetime, end: datetime) -> float | None:
    """The hours of a stay or a stop that fell between `start` and `end`, to one decimal; None for
    a move, a flight, a gap or a stay aboard."""
    if entry.get("gap") or entry.get("kind") not in (stays.STAY, stays.STOP) or entry.get("aboard"):
        return None
    if not entry.get("start_local") or not entry.get("end_local"):
        return None
    return round(_seconds_on(entry, start, end) / 3600, 1)


# -- the prompt and the answer ---------------------------------------------------------------------------


def prompt(made: Material) -> list[dict[str, str]]:
    """The two messages the model gets: the prompt file with the day and the language filled in,
    and the material as JSON."""
    template = Template(PROMPT_FILE.read_text(encoding="utf-8"))
    system = template.safe_substitute(
        day=made.day,
        weekday=made.data.get("weekday", ""),
        tz=made.data.get("tz", ""),
        language=made.language,
        language_name=LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse(answer: str) -> dict[str, Any]:
    """The JSON object in the model's answer: the whole text, or the text inside a code fence, or
    the span from the first `{` to the last `}`; `DreamError` when there is none."""
    text = answer.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{") : text.rindex("}") + 1])
    for candidate in candidates:
        try:
            found = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    raise AnswerError("the model's answer is not one JSON object; nothing was written")


def segments_of(
    found: Mapping[str, Any], made: Material, parts: Sequence[str] = drafts.PARTS, strict: bool = False
) -> tuple[list[dict[str, Any]], list[str]]:
    """The answer's segments in the order of `parts` (the day's by default; a journey and a week
    name their own), each `{text, evidence: [ids]}` with the references the material gave (a full
    line id of the unit is taken too), else `{text, unsupported: true}`; and the part of each. A
    day's segment keeps the references that hold when some do not; with `strict` (a journey's, a
    week's) one reference the material did not give marks the segment, as RFC 0036 rule 6 reads.
    A segment without text is dropped. More than `UNSUPPORTED_SHARE` unsupported, or no segment at
    all, is `DreamError` (`share_of`)."""
    segments: list[dict[str, Any]] = []
    named: list[str] = []
    for part in parts:
        items = found.get(part)
        if not isinstance(items, list):
            continue
        for item in items:
            segment = _segment(item, made, strict)
            if segment is None:
                continue
            segments.append(segment)
            named.append(part)
    share_of(segments, made.unit)
    return segments, named


def day_parts(made: Material) -> tuple[str, ...]:
    """The parts of a day's dream in order (dream-day/4, RFC 0043 §13.4): the story, one part per lens
    asked (`lens:<id>`), then the rest of `drafts.PARTS`."""
    lenses = tuple(drafts.LENS + lens["id"] for lens in made.lenses)
    return (drafts.STORY, *lenses, *drafts.PARTS[1:])


@dataclass(frozen=True)
class DayAnswer:
    """A day's answer as dream-day/4 keeps it: the segments, the part of each, the idea each `ideas`
    segment names (`{segment, entity}`, the segment's place from 1), what was dropped and marked, by
    why, and the evidence of each slot held for a number beside a name (`{segment, evidence}`)."""

    segments: list[dict[str, Any]]
    parts: list[str]
    ideas: list[dict[str, Any]]
    dropped: dict[str, int]
    marked: dict[str, int]
    held: list[dict[str, Any]]


def day_segments(found: Mapping[str, Any], made: Material) -> DayAnswer:
    """The answer's segments of a day (dream-day/4), checked as every segment is (`_segment`) and by
    the rules of each part, a segment that breaks one dropped and counted, never marked: the story at
    most `STORY_SENTENCES`; one segment per lens, and a lens answered without evidence dropped (the
    reader says the day does not answer it, never the model); one question; an `ideas` segment only
    when its `entity` is an idea the material named; one `photo`, resting on exactly one photo of the
    day. Then the number rule (`hold_numbers`), no number beside a person (`hold_names`, each held
    slot's evidence kept in `held`), and the evidence rule's share (`share_of`)."""
    segments: list[dict[str, Any]] = []
    named: list[str] = []
    ideas: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for part in day_parts(made):
        items = found.get(part)
        if not isinstance(items, list):
            continue
        kept_here = 0
        for item in items:
            segment = _segment(item, made)
            if segment is None:
                continue
            why = _drop(part, item, segment, kept_here, made)
            if why is not None:
                dropped[why] += 1
                continue
            kept_here += 1
            segments.append(segment)
            named.append(part)
            if part == drafts.IDEAS:
                ideas.append({"segment": len(segments), "entity": str(item["entity"]).strip()})
    marked: dict[str, int] = {}
    cited = [list(s.get("evidence") or []) for s in segments]  # `hold_numbers` drops what it marks
    unbacked = hold_numbers(segments, made.data, made, own_words(made))
    if unbacked:
        marked[UNBACKED] = unbacked
    beside = hold_names(segments, made)  # no number beside a person, whatever the lines give
    if beside:
        marked[BESIDE_A_NAME] = beside
    held = [
        {"segment": n, "evidence": cited[n - 1]}
        for n, s in enumerate(segments, 1)
        if s["text"] == HELD and cited[n - 1]
    ]
    share_of(segments, made.unit)
    return DayAnswer(segments, named, ideas, dict(dropped), marked, held)


def _drop(part: str, item: object, segment: Mapping[str, Any], kept_here: int, made: Material) -> str | None:
    """Why a segment of `part` is dropped by its part's rule, None when it is kept."""
    if part == drafts.STORY and kept_here >= STORY_SENTENCES:
        return DROP_STORY
    if part == "questions" and kept_here >= QUESTIONS_KEPT:
        return DROP_QUESTION
    if part.startswith(drafts.LENS):
        if segment.get("unsupported"):
            return DROP_LENS_UNSUPPORTED
        return DROP_LENS if kept_here else None
    if part == drafts.IDEAS:
        entity = item.get("entity") if isinstance(item, dict) else None
        if not isinstance(entity, str) or made.named.get(entity.strip()) != entities.IDEA:
            return DROP_IDEA
    if part == drafts.PHOTO:
        if kept_here:
            return DROP_PHOTO_TWICE
        evidence = item.get("evidence") if isinstance(item, dict) else None
        refs = [str(e).strip() for e in evidence] if isinstance(evidence, list) else []
        if len(refs) != 1 or refs[0] not in made.photos or segment.get("unsupported"):
            return DROP_PHOTO
    return None


def links_of(found: Mapping[str, Any], made: Material) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The answer's proposed links that hold (draft/v1 amendment 2), each `{kind: link, entity, text,
    evidence, note?}` with the references turned into line ids, at most `LINKS_KEPT`; and how many were
    dropped, by why. A link is dropped, never marked, when it is not an object, names an entity the
    material did not give (`named`: an idea or an org, by id), has no text, puts a number beside a
    person's name in its text or note (`beside_a_name`), or rests on a reference the day does not
    have, or on none."""
    items = found.get(LINKS)
    kept_links: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped[DROP_LINK_SHAPE] += 1
            continue
        entity, text, note = item.get("entity"), item.get("text"), item.get("note")
        if not isinstance(entity, str) or entity.strip() not in made.named:
            dropped[DROP_LINK_ENTITY] += 1
            continue
        if not isinstance(text, str) or not text.strip():
            dropped[DROP_LINK_TEXT] += 1
            continue
        if any(isinstance(t, str) and beside_a_name(t, made) for t in (text, note)):
            dropped[DROP_BESIDE_A_NAME] += 1
            continue
        evidence = item.get("evidence")
        ids: list[str] = []
        for ref in evidence if isinstance(evidence, list) else []:
            line_id = made.refs.get(str(ref).strip()) or (
                str(ref).strip() if str(ref).strip() in made.ids else None
            )
            if line_id is None:
                ids = []
                break
            if line_id not in ids:
                ids.append(line_id)
        if not ids:
            dropped[DROP_EVIDENCE] += 1
            continue
        if len(kept_links) >= LINKS_KEPT:
            dropped[DROP_LINK_MANY] += 1
            continue
        link: dict[str, Any] = {"kind": drafts.LINK, "entity": entity.strip(), "text": " ".join(text.split())}
        link["evidence"] = ids
        if isinstance(note, str) and note.strip():
            link["note"] = " ".join(note.split())
        kept_links.append(link)
    return kept_links, dict(dropped)


def share_of(segments: Sequence[Mapping[str, Any]], unit: str = drafts.UNIT_DAY) -> None:
    """The evidence rule's last word on an answer: no segment at all, or more than
    `UNSUPPORTED_SHARE` of them unsupported, is `AnswerError` and nothing is written."""
    if not segments:
        raise AnswerError("the model's answer holds no segment with text; nothing was written")
    unsupported = sum(1 for s in segments if s.get("unsupported"))
    if unsupported / len(segments) > UNSUPPORTED_SHARE:
        raise AnswerError(
            f"{unsupported} of {len(segments)} segments rest on no line of the {unit}, more than"
            f" {round(UNSUPPORTED_SHARE * 100)} %; the answer is refused and nothing was written"
        )


def proposals_of(found: Mapping[str, Any], made: Material) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The answer's proposed events that hold, each `{kind: event, title, start, end, place, people,
    evidence}` with the times in UTC and the references turned into line ids; and how many were
    dropped, by why. A proposal is dropped, never marked: when it is not an object, has no title,
    starts off the day or does not run forward (or runs longer than `LONGEST_EVENT`), names a place
    the material did not give, a person who is not one of the day's canonical people, or rests on a
    reference the day does not have, or on none; and when its title puts a number beside a person's
    name (`beside_a_name`)."""
    items = found.get(EVENTS)
    kept: list[dict[str, Any]] = []
    dropped: Counter[str] = Counter()
    for item in items if isinstance(items, list) else []:
        proposal, why = _proposal(item, made)
        if proposal is None:
            dropped[why] += 1
        else:
            kept.append(proposal)
    return kept, dict(dropped)


def _proposal(item: object, made: Material) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(item, dict):
        return None, DROP_SHAPE
    title = item.get("title")
    if not isinstance(title, str) or not title.strip():
        return None, DROP_TITLE
    if beside_a_name(title, made):
        return None, DROP_BESIDE_A_NAME
    start, end = _moment(item.get("start"), made), _moment(item.get("end"), made)
    if start is None or end is None or made.span is None:
        return None, DROP_TIME
    if not made.span[0] <= start < made.span[1] or not start < end <= start + LONGEST_EVENT:
        return None, DROP_TIME
    place = item.get("place")
    if place in (None, ""):
        place = None
    elif not isinstance(place, str) or place.strip() not in made.places:
        return None, DROP_PLACE
    people = item.get("people")
    people = [] if people is None else people
    if not isinstance(people, list):
        return None, DROP_PERSON
    persons: list[str] = []
    for entry in people:
        key = str(entry).strip()
        if key not in made.people:
            return None, DROP_PERSON
        if key not in persons:
            persons.append(key)
    evidence = item.get("evidence")
    ids: list[str] = []
    for ref in evidence if isinstance(evidence, list) else []:
        key = str(ref).strip()
        line_id = made.refs.get(key) or (key if key in made.ids else None)
        if line_id is None:
            return None, DROP_EVIDENCE
        if line_id not in ids:
            ids.append(line_id)
    if not ids:
        return None, DROP_EVIDENCE
    return {
        "kind": drafts.EVENT,
        "title": " ".join(title.split()),
        "start": _utc(start),
        "end": _utc(end),
        "place": None if place is None else place.strip(),
        "people": persons,
        "evidence": ids,
    }, ""


def _moment(value: object, made: Material) -> datetime | None:
    """A time as the model gave it: an RFC 3339 moment (an offset or Z; without one, the record's
    wall clock), or `HH:MM` on the day in the record's zone; None for anything else."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    clock = CLOCK.match(text)
    try:
        if clock:
            when = datetime.combine(parse_day(made.day), time(int(clock.group(1)), int(clock.group(2))))
        else:
            when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=made.zone)


def _utc(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _segment(item: object, made: Material, strict: bool = False) -> dict[str, Any] | None:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())
    evidence = item.get("evidence")
    ids: list[str] = []
    foreign = False
    if isinstance(evidence, list):
        for ref in evidence:
            key = str(ref).strip()
            line_id = made.refs.get(key) or (key if key in made.ids else None)
            if line_id is None:
                foreign = True
            elif line_id not in ids:
                ids.append(line_id)
    if ids and item.get("unsupported") is not True and not (strict and foreign):
        return {"text": text, "evidence": ids}
    return {"text": text, "unsupported": True}


# -- the dream --------------------------------------------------------------------------------------------


def dream(
    lb: Logbook,
    day: str,
    env: Mapping[str, str] | None = None,
    airports: Airports | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    made: Material | None = None,
    evening: bool = False,
) -> Dream:
    """Dream `day`: the policy, the endpoint, the material (`made` when the caller built it under
    the lock already), the model's turn, the check, and one `draft/v1` line appended under the
    writer lock unless `dry_run`. With `evening`, the day is today and is dreamed so far: the draft
    carries `extra.evening` and `extra.read_until`, the moment it read up to (RFC 0043 §6 rule 1); a
    day that is not today is refused. `DreamError` says why a dream is refused; `HeadMoved` when the
    record moved under the reading."""
    found = ceiling(lb)
    ep = endpoint(found, env)
    if evening:
        asked, today_here = parse_day(day).isoformat(), local_today(lb)
        if asked != today_here:
            raise DreamError(
                f"--evening dreams today so far, and {asked} is not today ({today_here});"
                f" `dream day {asked}` dreams it whole"
            )
    with lb.writer():
        read_until = now_utc()
        if made is None:
            made = material(lb, day, found, airports)
        if made.read_count == 0:
            raise DreamError(f"{made.day} has no line under max_tier {found.max_tier}; nothing to dream")
        enrich(lb, made, found)
        with lb.index() as idx:
            earlier = drafts.of_day(idx.by_kind(drafts.KIND), retractions(idx.retractions()), made.day)
        latest = drafts.standing(earlier)
        source = drafts.SOURCE_PREFIX + ep.model
        version = policy.version(found)
        if not dry_run:
            refuse_same(latest, source, made, version)
        messages = prompt(made)
        if say is not None:
            say(messages[0]["content"])
            say(messages[1]["content"])
        answer, found_answer = ask(ep, messages, transport)
        told = day_segments(found_answer, made)
        segments, parts = told.segments, told.parts
        proposals, dropped = proposals_of(found_answer, made)
        links, dropped_links = links_of(found_answer, made)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_DAY,
            "subject": made.day,
            "read_head": made.read_head,
            "read_count": made.read_count,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                "parts": parts,
                "read_ids_sha256": made.read_ids_sha256,
                "compared_count": len(made.compared),
                "compared_ids_sha256": made.compared_sha256,
                "policy_version": version,
            },
        }
        extra = payload["extra"]
        if made.lenses:
            extra["lenses"] = list(made.lenses)
        if told.ideas:
            extra["ideas"] = told.ideas
        if told.held:
            extra["held"] = told.held
        if evening:
            extra["evening"] = True
            extra["read_until"] = read_until
        if proposals or links:
            payload[drafts.PROPOSALS] = [*proposals, *links]
        for key, counted in (
            ("dropped", dropped),
            ("dropped_links", dropped_links),
            ("dropped_segments", told.dropped),
            ("marked", told.marked),
        ):
            if counted:
                extra[key] = counted
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        valid(payload)
        shown = drafts.proposals_json(payload, made.ids, made.zone, made.people, {})
        linked = drafts.links_json(payload, made.ids)
        with lb.index() as idx:
            ending = drafts.closing(idx, made.day, tiers_of(found), retractions(idx.retractions()), made.zone)
        if dry_run:
            return Dream(made.day, None, payload, made.tier, messages, answer, shown, dropped, linked, ending)
        line = append(lb, made, source, payload)
    return Dream(made.day, line, payload, made.tier, messages, answer, shown, dropped, linked, ending)


# -- the steps every unit's dream takes ------------------------------------------------------------------


def same_draft(latest: Line | None, source: str, read_head: str, version: str) -> bool:
    """RFC 0036 rule 1: whether the standing draft is this model's, at this head, under this
    version of the entry (a draft that names no entry: the head decides)."""
    if latest is None:
        return False
    payload = latest.get("payload") or {}
    kept = _policy_version(payload)
    return (
        latest.get("source") == source
        and payload.get("read_head") == read_head
        and (kept is None or kept == version)
    )


def refuse_same(latest: Line | None, source: str, made: Material, version: str) -> None:
    """`DreamError` when the unit was dreamed by this model at this head under this entry already
    (`same_draft`): nothing new to dream, nothing is sent."""
    if latest is not None and same_draft(latest, source, made.read_head, version):
        raise DreamError(
            f"{made.day} was dreamed by {source} at this head already (#{latest['seq']}); the record"
            " has not moved, so there is nothing new to dream"
        )


def ask(
    ep: Endpoint, messages: list[dict[str, str]], transport: Transport | None
) -> tuple[str, dict[str, Any]]:
    """The model's turn: its raw answer and the JSON object in it; `AnswerError` when the endpoint
    fails or the answer is not one object."""
    try:
        answer = model_client.complete(ep, messages, transport=transport)
    except model_client.ModelError as e:
        raise AnswerError(str(e)) from e
    return answer, parse(answer)


def valid(payload: Mapping[str, Any]) -> None:
    """`AnswerError` when the payload is not a `draft/v1` (`drafts.validate`): nothing is written."""
    problems = drafts.validate(payload)
    if problems:
        raise AnswerError(f"the draft would not be a {drafts.SCHEMA}: {problems[0]}; nothing was written")


def append(lb: Logbook, made: Material, source: str, payload: Mapping[str, Any]) -> Line:
    """The one write of a dream, inside the caller's hold of the writer lock: the head read again
    first, `HeadMoved` when it moved under the reading, then one `draft` line at the material's tier."""
    current = lb.meta
    if str(current.get("head")) != made.read_head:
        raise HeadMoved(
            HEAD_MOVED.format(was=made.read_head[:8], now=str(current.get("head"))[:8], unit=made.unit)
        )
    return lb.append(at=now_utc(), source=source, kind=drafts.KIND, tier=made.tier, payload=dict(payload))


def digest(ids: Iterable[str]) -> str:
    """The digest of the ids a dream read, `extra.read_ids_sha256`, which `--catch-up` compares."""
    return hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()


def why_again(latest: Line, found: policy.Ceiling, read_count: int, read_digest: str) -> str | None:
    """Why a unit with a standing draft is dreamed again, in words; None when it is unchanged. Its
    tier above the entry's `max_tier` today, or dreamed under another version of the entry (a draft
    follows the policy, not the head); or what it would read today is not what it read: another
    count, or another set of ids when it kept their digest."""
    payload = latest.get("payload") or {}
    entry = why_entry(latest, found)
    if entry is not None:
        return entry
    extra = payload.get("extra")
    kept = extra.get("read_ids_sha256") if isinstance(extra, dict) else None
    if payload.get("read_count") != read_count:
        return f"{read_count} lines now, {payload.get('read_count')} when last dreamed"
    if isinstance(kept, str) and kept != read_digest:
        return f"the {payload.get('unit') or 'unit'}'s lines are not the ones last dreamed"
    return None


def why_entry(latest: Line, found: policy.Ceiling) -> str | None:
    """Why a standing draft is dreamed again for the entry, in words, whatever its lines: its tier
    above the entry's `max_tier` today, or dreamed under another version of the entry; None when the
    entry still stands behind it."""
    tier = int(latest.get("tier") or 0)
    if tier > found.max_tier:
        return f"dreamed at tier {tier}, above max_tier {found.max_tier} now"
    version = _policy_version(latest.get("payload") or {})
    if version is not None and version != policy.version(found):
        return f"dreamed under another {policy.DREAM_DESTINATION} entry"
    return None


# -- catch-up ----------------------------------------------------------------------------------------------


def today() -> date:
    """The day a catch-up counts back from: this machine's date."""
    return date.today()


def local_today(lb: Logbook) -> str:
    """The day the owner is in now, in the record's zone under its `day_start`: the day `--evening`
    dreams so far."""
    return day_start.of(lb.meta).today(datetime.fromisoformat(now_utc().replace("Z", "+00:00"))).isoformat()


def days_to_catch_up(today: date, days: int) -> list[str]:
    """The last `days` local days before today, oldest first; today is still being written."""
    return [(today - timedelta(days=n)).isoformat() for n in range(days, 0, -1)]


def _policy_version(payload: Mapping[str, Any]) -> str | None:
    """The version of the entry a draft was dreamed under, None for a draft that names none."""
    extra = payload.get("extra")
    kept = extra.get("policy_version") if isinstance(extra, dict) else None
    return kept if isinstance(kept, str) else None


def changed_since(lb: Logbook, day: str, found: policy.Ceiling) -> tuple[bool, str, Material | None]:
    """Whether `day` needs dreaming: no draft; a standing draft the entry no longer stands behind
    (its tier above the entry's `max_tier` today, or dreamed under another version of the entry: a
    draft follows the policy, not the head); or the lines under the ceiling today are not what the
    standing draft read (its count, and the digest of ids when it kept one). The material is
    returned so a caller that dreams does not read twice; None for an empty day."""
    made = material(lb, day, found)
    if made.read_count == 0:
        return False, "nothing logged", None
    with lb.index() as idx:
        earlier = drafts.of_day(idx.by_kind(drafts.KIND), retractions(idx.retractions()), made.day)
        signature = signing.signature_of(idx, made.day)
    latest = drafts.standing(earlier)
    if latest is None:
        return True, "no draft yet", made
    why = why_again_day(latest, found, made, signature)
    if why is not None:
        return True, why, made
    if signature is not None:
        return False, f"signed as #{signature['seq']}, no line since; unchanged since #{latest['seq']}", made
    return False, f"unchanged since #{latest['seq']}", made


def why_again_day(latest: Line, found: policy.Ceiling, made: Material, signature: Line | None) -> str | None:
    """Why a day with a standing draft is dreamed again, in words; None when it is not (RFC 0043 §6).
    The entry first, as for every unit (`why_again`: its tier above `max_tier` today, or another
    version of the entry). Then the lines, left out the ones the close writes (`kept`, rule 4): on a
    signed day, only a line that arrived after both the signature and the standing draft, by `seq`
    (rule 5), and a signed day with none is never dreamed again (rule 6); on a day not signed, what it
    would compare today is not what the standing draft compared (`extra.compared_count` and
    `extra.compared_ids_sha256`), or, for a draft written before them, what it read (`why_again`)."""
    payload = latest.get("payload") or {}
    found_extra = payload.get("extra")
    extra: Mapping[str, Any] = found_extra if isinstance(found_extra, dict) else {}
    entry = why_entry(latest, found)
    if entry is not None:
        return entry
    if signature is not None:
        after = max(int(signature["seq"]), int(latest["seq"]))
        late = sum(1 for seq in made.compared.values() if seq > after)
        if late:
            return f"{late} line{'s' if late != 1 else ''} since you signed (#{signature['seq']})"
        return None
    count, kept_digest = extra.get("compared_count"), extra.get("compared_ids_sha256")
    if isinstance(count, int) and isinstance(kept_digest, str):
        if count != len(made.compared):
            return f"{len(made.compared)} lines now, {count} when last dreamed"
        if kept_digest != made.compared_sha256:
            return "the day's lines are not the ones last dreamed"
        return None
    return why_again(latest, found, made.read_count, made.read_ids_sha256)


def catch_up(
    lb: Logbook,
    days: int,
    today: date | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> list[Outcome]:
    """Dream each of the last `days` days that needs it; one `Outcome` per day, oldest first. The
    policy and the endpoint are checked once, before any day: a refusal there is `DreamError`."""
    found = ceiling(lb)
    endpoint(found, env)
    out: list[Outcome] = []
    with lb.writer():  # one holder for the whole run, as `sync` holds it: each day's head is its own
        for day in days_to_catch_up(today or date.today(), days):
            out.append(_catch_up_day(lb, day, found, env, transport))
    return out


def _catch_up_day(
    lb: Logbook, day: str, found: policy.Ceiling, env: Mapping[str, str] | None, transport: Transport | None
) -> Outcome:
    try:
        needed, why, made = changed_since(lb, day, found)
        if made is None:
            return Outcome(day, "empty", why)
        if not needed:
            return Outcome(day, "unchanged", why)
        dreamed = dream(lb, day, env, transport=transport, made=made)
        return Outcome(day, "dreamed", detail_of(dreamed, why))
    except (DreamError, HeadMoved, ValueError) as e:
        return Outcome(day, "refused", str(e))


def detail_of(dreamed: Dream, why: str) -> str:
    """`#5440 · no draft yet · 6 segments, 1 unsupported`: one dream in a catch-up's row, with its
    proposed events when it has any."""
    line = dreamed.line
    n = len(dreamed.payload["segments"])
    unsupported = sum(1 for s in dreamed.payload["segments"] if s.get("unsupported"))
    detail = f"#{line['seq'] if line else '?'}{DOT}{why}{DOT}{n} segments" + (
        f", {unsupported} unsupported" if unsupported else ""
    )
    if dreamed.proposals:
        k = len(dreamed.proposals)
        detail += f"{DOT}{k} proposed event{'s' if k != 1 else ''}"
    return detail


# -- the number rule ---------------------------------------------------------------------------------------


def numbers_by_id(data: Any, made: Material) -> dict[str, set[float]]:
    """line id -> the numbers the material gives for the items that cite it: an item is an object
    with `ref` (a list of references), and its numbers are its number values and the figures in
    the record's own words it carries (`SCANNED`: a title, a note's text, a promise's quote, a
    flight's number; its dates and clocks are not numbers), never a model's (a day's draft is given
    under `drafted`, which is not read for numbers). An object without `ref` lends its numbers to the
    refs of the item that holds it, none at the top."""
    found: dict[str, set[float]] = {}

    def walk(node: Any, scope: Sequence[str]) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item, scope)
            return
        if not isinstance(node, dict):
            return
        refs = node.get("ref")
        refs = [refs] if isinstance(refs, str) else refs  # a note's and a promise's `ref` is one reference
        own = [r for r in refs if isinstance(r, str)] if isinstance(refs, list) else []
        here = own or scope
        if here:
            values: set[float] = set()
            for key, value in node.items():
                if isinstance(value, bool):
                    continue
                if isinstance(value, int | float):
                    values.add(float(value))
                elif isinstance(value, str) and key in SCANNED:
                    values |= figures(value)
            for ref in here:
                line_id = made.refs.get(ref)
                if line_id is not None:
                    found.setdefault(line_id, set()).update(values)
        for key, value in node.items():
            if isinstance(value, dict | list) and key != "ref":
                walk(value, here)

    walk(data, ())
    return found


def own_words(made: Material) -> set[float]:
    """The figures of the material's own words that rest on no line of the day, so carry no reference:
    the chapter's name and rule, the goals', the named ideas' and orgs' names, the lenses' texts. A
    sentence may write one of them whatever it cites (`hold_numbers`)."""
    texts: list[str] = []
    meant = made.data.get("for") or {}
    found = meant.get("chapter")
    if isinstance(found, dict):
        texts += [str(found.get("name") or ""), str(found.get("rules") or "")]
    texts += [str(g.get("text") or "") for g in meant.get("goals") or []]
    texts += [str(n.get("name") or "") for n in made.data.get("named") or []]
    texts += [str(lens.get("text") or "") for lens in made.data.get("lenses") or []]
    return set().union(*(figures(t, language=made.language) for t in texts if t))


def hold_numbers(
    segments: list[dict[str, Any]], data: Any, made: Material, also: Collection[float] = ()
) -> int:
    """The number rule, in place: a supported segment that writes a figure the material does not
    give for one of the lines it cites (`numbers_by_id`) is marked unsupported, since its number
    rests on no line; returns how many were marked. A number is computed from the lines by the code
    that built the material, never estimated by the model: rounded, added up or guessed, it is not
    one of the given numbers and the sentence says so. `also` are figures any sentence may write, the
    material's own words that rest on no line (`own_words`)."""
    given = numbers_by_id(data, made)
    years = years_of(made.day)
    marked = 0
    for i, segment in enumerate(segments):
        evidence = segment.get("evidence")
        if not isinstance(evidence, list):
            continue
        allowed = set(also).union(*(given.get(str(e), set()) for e in evidence))
        written = figures(str(segment["text"]), years=years, language=made.language)
        if any(not any(abs(n - a) < 1e-9 for a in allowed) for n in written):
            segments[i] = {"text": segment["text"], "unsupported": True}
            marked += 1
    return marked


def beside_a_name(text: str, made: Material) -> bool:
    """Whether `text` names a canonical person of the record (their full name, or their first name,
    whole words, as written) and writes a figure (`figures`: dates, clock times and the unit's years
    are not figures): a number beside a person (VISION: no metrics near people). The rule every reader
    holds a stored draft to as well (`logbook.core.figures.beside_a_name`, `drafts.hold_beside`)."""
    names = [*made.canonical.values(), *made.withheld]  # a name the entry withholds is a name too
    return named_beside(text, names, years_of(made.day), made.language)


def hold_names(segments: list[dict[str, Any]], made: Material) -> int:
    """No number beside a person, in place, pencil included (RFC 0043): a segment that writes one
    (`beside_a_name`), supported or already marked, is held: its words are dropped and its slot is
    `{text: HELD, unsupported: true}`, whatever its evidence, so no reader can print them (a model's
    sentence that reads as the reason itself is held too, never prose); returns
    how many were held. A day's, a month's and a chapter's dream hold it; the day keeps the evidence
    of each held slot under `extra.held`."""
    marked = 0
    for i, segment in enumerate(segments):
        if segment == {"text": HELD, "unsupported": True}:
            continue
        if segment["text"] == HELD or beside_a_name(str(segment["text"]), made):
            segments[i] = {"text": HELD, "unsupported": True}
            marked += 1
    return marked
