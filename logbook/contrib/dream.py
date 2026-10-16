"""The dream (`logbook dream day DAY`, `logbook dream --catch-up`): a model reads one day of the
record and writes one `draft/v1` line about it (RFC 0036, `logbook.core.drafts`), the day in a
paragraph, the threads it moved, two questions for the owner's reflection, and proposals, the
people it thinks were there and the promises it thinks were made, every sentence pointing at the
lines it came from. The dream is a proposal; the owner's signature and notes are the facts.

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
in full; the commitments on the day; and the owner's note on signing it. Never a raw line above the
ceiling. Every item carries a reference (`L1`, `L2`, ...) that stands for one line id of the day, so
the model cites references and the record keeps ids. The prompt is `dream-prompt.md` beside this
module (docs/dream-prompt.md explains it); it asks for one JSON object of segments `{text,
evidence}` and says which language to write in: the language most of the day's own text is in
(`language_of`).

The answer is checked before anything is written (`segments_of`): a segment whose every reference
is one the material gave is supported and carries the ids; one with a reference the day does not
have, or none, is marked unsupported; a segment without text is dropped. When more than
`UNSUPPORTED_SHARE` of the segments are unsupported the answer is refused and nothing is written.
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
line: the owner confirms one with `day sign --accept N` (`logbook.contrib.dream_events`).

`--catch-up` dreams each of the last N days that has no draft, or whose lines today differ from
what the standing draft read (its `read_count`, and the digest of the ids it read, kept under
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

from ..core import day as day_reader
from ..core import day_start, drafts, machine, policy, present, reading, resolve, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.resolve import Ref
from ..core.store import HeadMoved, Logbook, now_utc, retractions
from . import model_client
from .model_client import Endpoint, Transport
from .promises import chat_ref

PROMPT_FILE = Path(__file__).with_name("dream-prompt.md")
# kept under `extra.prompt`, so a draft says which prompt wrote it; 2 added the events, 3 rule 5 (agents)
PROMPT_NAME = "dream-day/3"
UNSUPPORTED_SHARE = 0.30  # more than this share of segments unsupported: refused, nothing written
TEXT_CHARS = 400  # a message's text in the material, at most
NOTE_CHARS = 1500  # a note's text in the material, at most
MESSAGES_PER_COUNTERPART = 25  # the texts given per counterpart; the count is always whole
EXCLUDED_KINDS = frozenset({"retraction", "signed-day", drafts.KIND, "crossing"})  # never material
DEFAULT_LANGUAGE = "en"
DOT = " \u00b7 "
HEAD_MOVED = (
    "the record's head moved from {was} to {now} while the model read the {unit}, so the draft would not"
    " say what it read; nothing was written, dream the {unit} again"
)
EVENTS = "events"  # the key of the answer that holds the proposed events
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
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
# -- the number rule (`hold_numbers`): a figure a sentence writes is one the code computed from lines --
UNBACKED = "a number the lines do not give"  # the key of `extra.marked`: a segment marked for a figure
# a figure: digits, a decimal point or comma and more digits, glued to a unit or not (`45min`, `7,5t`),
# never a piece of an id (`L12`, `6bc0`)
NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![.,]?\d)(?!\w*\d)")
MONTHS = (
    "january|february|march|april|june|july|august|september|october|november|december"
    "|januar|februar|mars|mai|juni|juli|oktober|desember"
    "|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|okt|nov|dec|des|(?-i:May)"  # `may`, lower-case, is a verb
)
# what a figure in a sentence may be without being a number: a date (ISO, `16.06.2026`, `16/6`), a
# clock (`19:30`, `kl. 19`, `9am`), an ISO week, a day of the month beside its month's name, an ordinal
CALENDAR = re.compile(
    r"\d{4}-\d{2}-\d{2}(?:T[\d:]+(?:Z|[+-]\d{2}:\d{2})?)?"
    r"|\b\d{4}-W\d{2}\b|\bW\d{1,2}\b|\b(?:week|uke|woche|semaine|semana)\s+\d{1,2}\b"
    r"|\b\d{1,2}\.\d{1,2}\.\d{2,4}\b|\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b"
    r"|\b\d{1,2}:\d{2}\b|\b(?:kl\.?|klokka|klokken)\s*\d{1,2}(?:[:.]\d{2})?\b|\b\d{1,2}\s?(?:am|pm)\b"
    rf"|\b\d{{1,2}}(?:\.|st|nd|rd|th)?\s+(?:{MONTHS})\b|\b(?:{MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
    r"|\b\d{1,2}(?:st|nd|rd|th)\b",
    re.IGNORECASE,
)
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")  # a year, when it is one of the unit's (`figures`)
# numbers written in words, in the languages a draft is most often in: a word is a figure too
NUMBER_WORDS: dict[str, dict[str, int]] = {
    "en": {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
    | {"ten": 10, "eleven": 11, "twelve": 12},
    "nb": {"to": 2, "tre": 3, "fire": 4, "fem": 5, "seks": 6, "sju": 7, "syv": 7, "åtte": 8, "ni": 9}
    | {"ti": 10, "elleve": 11, "tolv": 12},
}
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
    unit: str = drafts.UNIT_DAY  # what the material is of: a day, a journey, a week
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

    def refs_of(self, ids: Iterable[str | None]) -> list[str]:
        return [ref for ref in (self.ref_of(i) for i in ids) if ref is not None]

    def person(self, entity: str | None) -> str | None:
        """The entity id when it is a canonical person, noted as one the day names; else None."""
        if not entity or entity not in self.canonical:
            return None
        self.people.setdefault(entity, self.canonical[entity])
        return entity

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
    data = day_reader.read(lb, day, airports, tiers)
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        on_day = [
            line
            for line in reading.crossing(idx.day(day), tiers)
            if str(line["id"]) not in retracted and line.get("kind") not in EXCLUDED_KINDS
        ]
        names = resolve.labels(lb, idx)
        identities = resolve.identities_from([*idx.retractions(), *idx.resolutions()])
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
        canonical=canonical(lb, identities),
        identities=identities,
    )
    made.data = _data(data, on_day, names, made, found.max_tier)
    return made


def canonical(lb: Logbook, identities: Mapping[Ref, resolve.Identity]) -> dict[str, str]:
    """Every canonical person of the record, id -> name: the entities the resolution lines name as
    a person after the alias walk (a person merged into another is not one), never the owner."""
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
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
    reference the day does not have, or on none."""
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
) -> Dream:
    """Dream `day`: the policy, the endpoint, the material (`made` when the caller built it under
    the lock already), the model's turn, the check, and one `draft/v1` line appended under the
    writer lock unless `dry_run`. `DreamError` says why a dream is refused; `HeadMoved` when the
    record moved under the reading."""
    found = ceiling(lb)
    ep = endpoint(found, env)
    with lb.writer():
        if made is None:
            made = material(lb, day, found, airports)
        if made.read_count == 0:
            raise DreamError(f"{made.day} has no line under max_tier {found.max_tier}; nothing to dream")
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
        segments, parts = segments_of(found_answer, made)
        proposals, dropped = proposals_of(found_answer, made)
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
                "policy_version": version,
            },
        }
        if proposals:
            payload[drafts.PROPOSALS] = proposals
        if dropped:
            payload["extra"]["dropped"] = dropped
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        valid(payload)
        shown = drafts.proposals_json(payload, made.ids, made.zone, made.people, {})
        if dry_run:
            return Dream(made.day, None, payload, made.tier, messages, answer, shown, dropped)
        line = append(lb, made, source, payload)
    return Dream(made.day, line, payload, made.tier, messages, answer, shown, dropped)


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
    tier = int(latest.get("tier") or 0)
    if tier > found.max_tier:
        return f"dreamed at tier {tier}, above max_tier {found.max_tier} now"
    version = _policy_version(payload)
    if version is not None and version != policy.version(found):
        return f"dreamed under another {policy.DREAM_DESTINATION} entry"
    extra = payload.get("extra")
    kept = extra.get("read_ids_sha256") if isinstance(extra, dict) else None
    if payload.get("read_count") != read_count:
        return f"{read_count} lines now, {payload.get('read_count')} when last dreamed"
    if isinstance(kept, str) and kept != read_digest:
        return f"the {payload.get('unit') or 'unit'}'s lines are not the ones last dreamed"
    return None


# -- catch-up ----------------------------------------------------------------------------------------------


def today() -> date:
    """The day a catch-up counts back from: this machine's date."""
    return date.today()


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
    latest = drafts.standing(earlier)
    if latest is None:
        return True, "no draft yet", made
    why = why_again(latest, found, made.read_count, made.read_ids_sha256)
    if why is not None:
        return True, why, made
    return False, f"unchanged since #{latest['seq']}", made


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


def figures(
    text: str, calendar: bool = True, years: Collection[str] | None = None, language: str | None = None
) -> set[float]:
    """The numbers written in `text`: in figures, a decimal comma read as a point and a thousands
    comma dropped (`1,250`), and, in `language`, in words (`NUMBER_WORDS`). With `calendar`, dates,
    clocks, ISO weeks and days of the month beside their month are not numbers (`CALENDAR`), nor is a
    year: any (`YEAR`), or only one of `years` when they are given, so `2000 kroner` is a number."""
    if calendar:
        text = CALENDAR.sub(" ", text)
        text = YEAR.sub(lambda m: " " if years is None or m.group(0) in years else m.group(0), text)
    out: set[float] = set()
    for token in NUMBER.findall(text):
        if re.fullmatch(r"\d{1,3}(,\d{3})+", token):
            token = token.replace(",", "")
        try:
            out.add(float(token.replace(",", ".")))
        except ValueError:
            continue
    words = NUMBER_WORDS.get(language or "", {})
    if words:
        out |= {float(words[w]) for w in WORD.findall(text.lower()) if w in words}
    return out


def hold_numbers(segments: list[dict[str, Any]], data: Any, made: Material) -> int:
    """The number rule, in place: a supported segment that writes a figure the material does not
    give for one of the lines it cites (`numbers_by_id`) is marked unsupported, since its number
    rests on no line; returns how many were marked. A number is computed from the lines by the code
    that built the material, never estimated by the model: rounded, added up or guessed, it is not
    one of the given numbers and the sentence says so."""
    given = numbers_by_id(data, made)
    years = {str(y + d) for y in map(int, re.findall(r"\b(?:19|20)\d{2}\b", made.day)) for d in (-1, 0, 1)}
    marked = 0
    for i, segment in enumerate(segments):
        evidence = segment.get("evidence")
        if not isinstance(evidence, list):
            continue
        allowed = set().union(*(given.get(str(e), set()) for e in evidence))
        written = figures(str(segment["text"]), years=years, language=made.language)
        if any(not any(abs(n - a) < 1e-9 for a in allowed) for n in written):
            segments[i] = {"text": segment["text"], "unsupported": True}
            marked += 1
    return marked
