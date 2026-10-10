"""Observed people, the review queue and the owner's say — `logbook people review`, `people --priority`.

The record has two layers of people. An **observed** person is what one source saw: an address a
mail came from, a number a message came from, a name a transcript gave a speaker. A **canonical**
person is one the owner has confirmed: an entity the resolution lines name (RFC 0006), minted by a
contacts import, a `logbook add` or a `people merge`. Nothing here invents a third store: the
canonical people are read as `people` reads them, and a confirmation is the line `people merge`
writes.

**The strongest-identifier rule.** An observed person's id is derived from the strongest identifier
the observation carries — an **email** address (case aside), else a **phone** number (E.164, a
WhatsApp JID read as the number it spells, a number entered without a country code read with
`LOGBOOK_DIAL_PREFIX` as the adapters read it), else the **name** as shown, its words folded and
sorted — never from the per-observation id a source gives (a speaker id, a chat guid, a line id).
An address seen under three display names is one observed person with three names; a number seen as
`+447700900101` and as `447700900101@s.whatsapp.net` is one. The other way, one person explodes
into a row per observation.

**The table.** Observed people are a derived table in the index, `observed_people` in
`index.sqlite`, keyed by (kind, value) of the strongest identifier, with the display names and the
identifiers as the lines wrote them, counts per source and per kind, the days seen, first and last
seen, the tier, a few line ids as evidence, and the canonical person the observation resolves to
when one of its identifiers has a resolution standing (as written: the readers look a ref up as the
line carries it) or, for a name alone, when the people reader would place it by that name. The table
is built from the lines through the index (`Index.of_kind`, mail, message, transcript and event,
standing lines only, the owner's own identities left out), stamped with the head it was built at,
served while the head stands and rebuilt when the record grows; its shape is checked with
`PRAGMA table_info` and a table of another shape is built again. Nothing is stored in the record.

**The queue.** `people review` proposes each observed person not yet placed against each canonical
person, ranked by the evidence, numbered from 1: the **same email** (an identifier of the observed
is an address a canonical ref spells, case aside, +60), the **same phone** (+50), the **same name**
(a display name and the canonical label are one name by `people merge`'s rule: the same words in
any order, or an initial for a first name, two words at least; +20, and +5 for each further source
the observed is seen on, up to +10) and **together on the same days** (+2 per day both were seen on,
up to +20; days alone never propose). A pair the owner rejected is never proposed again. An observed
person with no identifier a resolution line can carry (a spoken name alone) is listed, not proposed.

**The owner's say.** Nothing is promoted on its own. `--accept N[,N]` writes, per identifier of the
observed person as the lines wrote it, the line `people merge` writes: one `resolution/v1`,
`source` `manual`, `method` `owner`, `alias_of` the canonical person's own ref (a phone before an
address), the head the proposal was read against and under `extra` the proposal id, the entity,
the score and what matched. `--reject N[,N]` writes one `people-review/v1` line (RFC 0035) saying
the observed person and the canonical person are not the same, with the identifiers, so the pair
never comes back; retract it and the proposal returns. `--all-above SCORE` accepts every proposal at
or above the score. Only `Logbook.append` writes.

**Priority.** `people --priority` ranks the canonical people heard in the last year by a plain
sum: 3 per day together, 1 per message exchanged (the smaller of the two directions, up to 50),
2 per meeting (a timed calendar entry attended, a transcript spoken in), and 10 when the last real
contact is within 30 days, 5 within 90. Printed with the score, so the owner can argue with it."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..core import people, policy, present, reading, resolve, stays
from ..core.chain import Line
from ..core.index import Index
from ..core.resolve import Identity, Ref
from ..core.store import Logbook, now_utc, retractions
from . import people_merge
from .adapters import phone as phones
from .adapters.ios_contacts import DIAL_PREFIX_ENV

KIND = "people-review"  # the line a rejection writes
SCHEMA = "people-review/v1"
DIFFERENT = "different"
SOURCE = people_merge.SOURCE
METHOD = people_merge.METHOD
KINDS = ("mail", "message", "transcript", "event")  # the lines a counterpart is observed on
REF_KINDS = ("email", "phone", "handle", "provider_id")  # an identifier a resolution line can carry
TABLE = "observed_people"
TABLE_META = "observed_meta"
TABLE_VERSION = "1"
COLUMNS = (
    "key_kind",
    "key_value",
    "entity",
    "labels",
    "identifiers",
    "sources",
    "kinds",
    "days",
    "first",
    "last",
    "lines",
    "tier",
    "samples",
)
SAMPLES = 3  # line ids kept per observed person, as evidence
EMAIL, PHONE, NAME, TOGETHER = 60, 50, 20, 2  # the evidence, in points
NAME_SOURCE, NAME_SOURCE_CAP, TOGETHER_CAP = 5, 10, 20
DAYS, MESSAGES, MESSAGES_CAP, MEETINGS = 3, 1, 50, 2  # the priority score
RECENT, RECENT_DAYS, RECENTISH, RECENTISH_DAYS = 10, 30, 5, 90
YEAR = 365
ADDRESS = people_merge.ADDRESS
WHATSAPP_JID = people_merge.WHATSAPP_JID
E164 = people_merge.PHONE
PLAIN_PHONE = re.compile(r"^\+?\d{6,15}$")
EN_DASH = people_merge.EN_DASH
NOT_EQUAL = "\u2260"
ME = frozenset({"me", "you", "ich", "jeg", "du"})  # a transcript's word for the owner, never a name


class ReviewError(ValueError):
    """A number, a score or a proposal the record cannot act on; nothing was written."""


# -- what one source saw -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Seen:
    """One counterpart on one line: its identifiers as the line wrote them, strongest first, and
    the display name the line shows."""

    refs: tuple[Ref, ...]
    label: str | None


def counterparts(kind: str, payload: Mapping[str, Any]) -> list[Seen]:
    """The people one line names, source-native: a mail's addresses, a message's sender (or, for
    the owner's own line in a direct chat, the person the chat's id names), a transcript's
    participants, a calendar entry's attendees who did not decline and its organizer."""
    if kind == "mail":
        found = []
        for header in ("from", "to", "cc", "bcc"):
            value = payload.get(header)
            for address in value if isinstance(value, list) else [value]:
                if not isinstance(address, dict):
                    continue
                email = address.get("email")
                if isinstance(email, str) and email.strip():
                    found.append(Seen((("email", email.strip().casefold()),), _text(address.get("name"))))
        return found
    if kind == "message":
        chat = payload.get("chat")
        if payload.get("from_me") is True:
            if not isinstance(chat, dict) or chat.get("type") != "direct" or not chat.get("id"):
                return []
            ref = _chat_ref(str(chat["id"]))
            return [] if ref is None else [Seen((ref,), _text(chat.get("name")))]
        ref = _ref(payload.get("sender"))
        if ref is None:
            return []
        sender = payload.get("sender")
        return [Seen((ref,), _text(sender.get("name")) if isinstance(sender, dict) else None)]
    if kind == "transcript":
        found = []
        participants = payload.get("participants")
        for participant in participants if isinstance(participants, list) else []:
            if not isinstance(participant, dict):
                continue
            refs = tuple(
                (ref_kind, str(participant[key]).strip())
                for ref_kind, key in (("email", "email"), ("phone", "phone"), ("provider_id", "provider_id"))
                if isinstance(participant.get(key), str) and str(participant[key]).strip()
            )
            refs = tuple((k, v.casefold()) if k == "email" else (k, v) for k, v in refs)
            label = _text(participant.get("name"))
            if refs or label:
                found.append(Seen(refs, label))
        return found
    if kind == "event":
        found = []
        attendees = payload.get("attendees")
        for attendee in attendees if isinstance(attendees, list) else []:
            if not isinstance(attendee, dict) or attendee.get("response") == "declined":
                continue
            ref = _ref(attendee.get("ref"))
            if ref is not None:
                found.append(Seen((ref,), _text(attendee.get("name"))))
        organizer = _ref(payload.get("organizer"))
        if organizer is not None:
            found.append(Seen((organizer,), None))
        return found
    return []


def key_of(seen: Seen, prefix: str) -> Ref | None:
    """The strongest identifier, normalised: (`email`, the address), (`phone`, the E.164 number
    or the digits as entered), (`name`, the folded words sorted); None when the observation
    carries nothing a person can be known by."""
    for ref in seen.refs:
        email = _email_key(ref)
        if email is not None:
            return email
    for ref in seen.refs:
        phone = _phone_key(ref, prefix)
        if phone is not None:
            return phone
    words = sorted(people_merge._words(seen.label or ""))
    return ("name", " ".join(words)) if words else None


def _email_key(ref: Ref) -> Ref | None:
    """An `email` ref, or a `handle` that is an address and not a WhatsApp JID (which spells a
    number), as (`email`, the address, case aside)."""
    if ref[0] == "handle" and WHATSAPP_JID.match(ref[1]):
        return None
    return people_merge._email_key(ref)


def _phone_key(ref: Ref, prefix: str) -> Ref | None:
    kind, value = ref
    if kind == "phone":
        number, _flagged = phones.normalise(value, prefix)
        return ("phone", number) if number and PLAIN_PHONE.match(number) else None
    if kind == "handle":
        jid = WHATSAPP_JID.match(value)
        return ("phone", f"+{jid.group(1)}") if jid else None
    return None


def _chat_ref(chat_id: str) -> Ref | None:
    """The ref a direct chat's id names, as the people reader reads it: a JID is the phone number
    it spells, an address or a number as such is itself; anything else names nobody."""
    jid = WHATSAPP_JID.match(chat_id)
    if jid is not None:
        return ("phone", f"+{jid.group(1)}")
    if E164.match(chat_id):
        return ("phone", chat_id)
    if "@" in chat_id:
        return ("email", chat_id.strip().casefold())
    return None


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(ref_value, str) or not ref_value.strip():
        return None
    return kind, ref_value.strip()


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


# -- observed people ----------------------------------------------------------------------------------------


@dataclass
class Observed:
    """One observed person: everything one strongest identifier was seen as."""

    key: Ref
    labels: Counter[str] = field(default_factory=Counter)  # display names, as shown → times
    identifiers: dict[Ref, int] = field(default_factory=dict)  # as the lines wrote them → times
    sources: Counter[str] = field(default_factory=Counter)
    kinds: Counter[str] = field(default_factory=Counter)
    days: set[str] = field(default_factory=set)
    first: str | None = None
    last: str | None = None
    lines: int = 0
    tier: int = 0
    samples: list[str] = field(default_factory=list)
    entity: str | None = None  # the canonical person, when the record places it

    def add(self, seen: Seen, source: str, kind: str, day: str, line_id: str, tier: int) -> None:
        if seen.label:
            self.labels[seen.label] += 1
        for ref in seen.refs:
            self.identifiers[ref] = self.identifiers.get(ref, 0) + 1
        self.sources[source] += 1
        self.kinds[kind] += 1
        self.days.add(day)
        self.first = day if self.first is None else min(self.first, day)
        self.last = day if self.last is None else max(self.last, day)
        self.lines += 1
        self.tier = max(self.tier, tier)
        if len(self.samples) < SAMPLES:
            self.samples.append(line_id)

    @property
    def name(self) -> str:
        """The display name shown most, the first written when tied; the identifier when none."""
        return self.labels.most_common(1)[0][0] if self.labels else self.key[1]

    @property
    def writable(self) -> list[Ref]:
        """The identifiers a resolution line can carry, strongest kind first, as written."""
        order = {kind: n for n, kind in enumerate(REF_KINDS)}
        return sorted((ref for ref in self.identifiers if ref[0] in REF_KINDS), key=lambda r: order[r[0]])

    def to_json(self) -> dict[str, Any]:
        return {
            "key": {"kind": self.key[0], "value": self.key[1]},
            "name": self.name,
            "labels": dict(self.labels),
            "identifiers": [{"kind": k, "value": v, "lines": n} for (k, v), n in self.identifiers.items()],
            "sources": dict(self.sources),
            "kinds": dict(self.kinds),
            "days": len(self.days),
            "first": self.first,
            "last": self.last,
            "lines": self.lines,
            "tier": self.tier,
            "entity": self.entity,
        }

    def _row(self) -> tuple[Any, ...]:
        return (
            self.key[0],
            self.key[1],
            self.entity,
            json.dumps(dict(self.labels), ensure_ascii=False),
            json.dumps([[k, v, n] for (k, v), n in self.identifiers.items()], ensure_ascii=False),
            json.dumps(dict(self.sources), ensure_ascii=False),
            json.dumps(dict(self.kinds), ensure_ascii=False),
            json.dumps(sorted(self.days)),
            self.first,
            self.last,
            self.lines,
            self.tier,
            json.dumps(self.samples),
        )

    @classmethod
    def _from_row(cls, row: Sequence[Any]) -> Observed:
        (
            key_kind,
            key_value,
            entity,
            labels,
            identifiers,
            sources,
            kinds,
            days,
            first,
            last,
            n,
            tier,
            samples,
        ) = row
        return cls(
            (str(key_kind), str(key_value)),
            Counter(json.loads(labels)),
            {(str(k), str(v)): int(c) for k, v, c in json.loads(identifiers)},
            Counter(json.loads(sources)),
            Counter(json.loads(kinds)),
            set(json.loads(days)),
            first,
            last,
            int(n),
            int(tier),
            list(json.loads(samples)),
            entity,
        )


def observed(lb: Logbook) -> list[Observed]:
    """Every observed person of the record, from the index's derived table: served while the
    table's head is the record's, built from the lines and stored otherwise. Writes nothing to
    the record."""
    with lb.index() as idx:
        return observed_in(lb, idx)


def observed_in(lb: Logbook, idx: Index) -> list[Observed]:
    meta = lb.meta
    stamp = {"head": str(meta["head"]), "timezone": str(meta["timezone"]), "version": TABLE_VERSION}
    if _table_current(idx.db, stamp):
        rows = idx.db.execute(
            f"SELECT {', '.join(COLUMNS)} FROM {TABLE} ORDER BY key_kind, key_value"
        ).fetchall()
        return [Observed._from_row(row) for row in rows]
    found = build(lb, idx)
    _store(idx.db, found, stamp)
    return found


def _table_current(db: sqlite3.Connection, stamp: Mapping[str, str]) -> bool:
    """Whether the table is there, of the shape this module writes, and stamped with this head."""
    try:
        columns = {str(row[1]) for row in db.execute(f"PRAGMA table_info({TABLE})")}
        if not set(COLUMNS) <= columns:
            return False
        stored = dict(db.execute(f"SELECT key, value FROM {TABLE_META}"))
    except sqlite3.DatabaseError:
        return False
    return stored == dict(stamp)


def _store(db: sqlite3.Connection, found: Sequence[Observed], stamp: Mapping[str, str]) -> None:
    db.execute("BEGIN")
    try:
        db.execute(f"DROP TABLE IF EXISTS {TABLE}")
        db.execute(f"DROP TABLE IF EXISTS {TABLE_META}")
        db.execute(
            f"CREATE TABLE {TABLE} (key_kind TEXT NOT NULL, key_value TEXT NOT NULL, entity TEXT,"
            " labels TEXT NOT NULL, identifiers TEXT NOT NULL, sources TEXT NOT NULL, kinds TEXT NOT NULL,"
            " days TEXT NOT NULL, first TEXT, last TEXT, lines INTEGER NOT NULL, tier INTEGER NOT NULL,"
            " samples TEXT NOT NULL, PRIMARY KEY (key_kind, key_value))"
        )
        db.execute(f"CREATE TABLE {TABLE_META} (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.executemany(
            f"INSERT INTO {TABLE} ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
            [o._row() for o in found],
        )
        db.executemany(f"INSERT INTO {TABLE_META} VALUES (?, ?)", list(stamp.items()))
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def build(lb: Logbook, idx: Index) -> list[Observed]:
    """The pure read: every observed person from the standing mail, message, transcript and event
    lines, streamed one kind at a time, keyed by the strongest identifier, the owner's own
    identities left out, each placed when the record resolves it."""
    meta = lb.meta
    tz = ZoneInfo(str(meta["timezone"]))
    marks, resolutions = idx.retractions(), idx.resolutions()
    retracted = frozenset(retractions(marks))
    identities = resolve.identities_from([*marks, *resolutions])
    owner = present.owner_of(
        str(meta.get("owner_id") or ""),
        [str(e) for e in meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    found: dict[Ref, Observed] = {}
    for kind in KINDS:
        superseded = idx.superseded(kind)
        for line in idx.of_kind(kind):
            id_ = str(line.get("id"))
            if id_ in retracted or id_ in superseded:
                continue
            at = stays.instant(line.get("at"))
            if at is None:
                continue
            day = at.astimezone(tz).date().isoformat()
            source, tier = str(line.get("source") or ""), int(line.get("tier", 0))
            for seen in counterparts(kind, line.get("payload") or {}):
                if _is_owner(seen, owner, identities):
                    continue
                key = key_of(seen, prefix)
                if key is None:
                    continue
                found.setdefault(key, Observed(key)).add(seen, source, kind, day, id_, tier)
    for o in found.values():
        o.entity = placed(o, identities, owner)
    return sorted(found.values(), key=lambda o: o.key)


def _is_owner(seen: Seen, owner: present.Owner, identities: Mapping[Ref, Identity]) -> bool:
    for ref in seen.refs:
        if ref in owner.refs:
            return True
        entity, _label = present.resolve_ref(ref, identities)
        if entity is not None and entity in owner.entities:
            return True
    if seen.label:
        name = " ".join(seen.label.split()).casefold()
        return name in owner.names or name in ME
    return False


def placed(o: Observed, identities: Mapping[Ref, Identity], owner: present.Owner) -> str | None:
    """The canonical person the observed one resolves to: the first identifier, strongest kind
    first and as written, with a resolution standing (the readers look a ref up as the line
    carries it); for a name alone, the person the people reader would place a speaker of that
    name with. None when nobody."""
    for ref in o.writable:
        entity, _label = present.resolve_ref(ref, identities)
        if entity is not None and entity not in owner.entities:
            return entity
    if not o.writable:
        for label, _n in o.labels.most_common():
            entity, _label = present.by_name(label, identities)
            if entity is not None and entity not in owner.entities:
                return entity
    return None


# -- the queue -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Canonical:
    """One confirmed person as `people` reads them: the label, the refs, the tier, the days they
    were seen or met on, the sources that saw them, and the merge candidate (for its own lines)."""

    entity: str
    label: str
    refs: tuple[Ref, ...]
    tier: int
    days: frozenset[str]
    sources: Counter[str]
    candidate: people_merge.Candidate | None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.entity, "name": self.label}


@dataclass(frozen=True)
class Proposal:
    number: int
    id: str
    observed: Observed
    canonical: Canonical
    score: int
    evidence: tuple[str, ...]

    @property
    def tier(self) -> int:
        return max(self.observed.tier, self.canonical.tier)

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "id": self.id,
            "score": self.score,
            "evidence": list(self.evidence),
            "observed": self.observed.to_json(),
            "canonical": self.canonical.to_json(),
        }


@dataclass(frozen=True)
class Report:
    proposals: list[Proposal]
    unplaced: list[Observed]
    placed: int
    canonicals: dict[str, Canonical]
    rejected: Rejected
    standing: dict[Ref, Line]
    head: str

    @property
    def tier(self) -> int | None:
        return max((p.tier for p in self.proposals), default=None)

    def to_json(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "observed": {"placed": self.placed, "unplaced": [o.to_json() for o in self.unplaced]},
            "rejected": self.rejected.pairs,
            "proposals": [p.to_json() for p in self.proposals],
        }


def read(lb: Logbook) -> Report:
    """The queue of the record at its head: the observed people through the index's table, the
    canonical people through the `people` reader, the owner's rejections through the standing
    `people-review` lines. Writes nothing to the record. Raises what `people.read` raises."""
    rows = observed(lb)
    with lb.index() as idx:
        marks, resolutions = idx.retractions(), idx.resolutions()
        reviews = idx.by_kind(KIND)
    lines = [*marks, *resolutions]
    standing = resolve.standing(lines)
    identities = resolve.identities_from(lines)
    rejected = rejections(reviews, frozenset(retractions(marks)))
    window = reading.record_days(lb)
    canonicals: dict[str, Canonical] = {}
    if window is not None:
        report = people.read(lb, *window)
        channels = {
            entity: {name: c.lines for name, c in person.channels.items() if c.lines}
            for entity, person in report.known.items()
        }
        candidates = people_merge.candidates_from(standing, identities, report.owner.entities, channels)
        seen_days: dict[str, set[str]] = {}
        seen_sources: dict[str, Counter[str]] = {}
        for o in rows:
            if o.entity is not None:
                seen_days.setdefault(o.entity, set()).update(o.days)
                seen_sources.setdefault(o.entity, Counter()).update(o.sources)
        for entity, person in report.known.items():
            canonicals[entity] = Canonical(
                entity,
                person.name,
                person.refs,
                person.tier,
                frozenset(seen_days.get(entity, set()) | set(person.days)),
                seen_sources.get(entity, Counter()),
                candidates.get(entity),
            )
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    unplaced = [o for o in rows if o.entity is None]
    proposals = propose(unplaced, canonicals, rejected, prefix)
    placed_count = sum(1 for o in rows if o.entity is not None)
    return Report(proposals, unplaced, placed_count, canonicals, rejected, standing, str(lb.meta["head"]))


@dataclass(frozen=True)
class Rejected:
    """What the owner said is not the same person: per canonical entity, the observed identifiers
    (the key and the identifiers as written), and how many pairs were rejected."""

    by_entity: dict[str, set[Ref]] = field(default_factory=dict)
    pairs: int = 0

    def holds(self, o: Observed, entity: str) -> bool:
        no = self.by_entity.get(entity, set())
        return o.key in no or any(ref in no for ref in o.identifiers)


def rejections(reviews: Iterable[Line], retracted: frozenset[str]) -> Rejected:
    """The standing `people-review/v1` lines with verdict `different`, read into `Rejected`."""
    found: dict[str, set[Ref]] = {}
    pairs = 0
    for line in reviews:
        if str(line.get("id")) in retracted:
            continue
        payload = line.get("payload") or {}
        if payload.get("schema") != SCHEMA or payload.get("verdict") != DIFFERENT:
            continue
        entity = payload.get("entity")
        entity_id = entity.get("id") if isinstance(entity, dict) else None
        if not isinstance(entity_id, str) or not entity_id:
            continue
        refs = [_ref(payload.get("ref"))]
        listed = payload.get("refs")
        refs.extend(_ref(r) for r in (listed if isinstance(listed, list) else []))
        found.setdefault(entity_id, set()).update(ref for ref in refs if ref is not None)
        pairs += 1
    return Rejected(found, pairs)


def propose(
    unplaced: Sequence[Observed],
    canonicals: Mapping[str, Canonical],
    rejected: Rejected,
    prefix: str = "",
) -> list[Proposal]:
    """The pure function: every (observed, canonical) pair with evidence, ranked by score, then
    by how much evidence, then by the observed key and the canonical label; numbered from 1."""
    found: list[tuple[int, tuple[str, ...], Observed, Canonical]] = []
    for o in unplaced:
        if not o.writable:
            continue
        for c in canonicals.values():
            if rejected.holds(o, c.entity):
                continue
            score, why = evidence(o, c, prefix)
            if score:
                found.append((score, why, o, c))
    found.sort(key=lambda f: (-f[0], -len(f[1]), f[2].key, f[3].label.casefold(), f[3].entity))
    return [
        Proposal(n, proposal_id(o.key, c.entity), o, c, score, why)
        for n, (score, why, o, c) in enumerate(found, start=1)
    ]


def proposal_id(key: Ref, entity: str) -> str:
    return hashlib.sha256(f"{key[0]}\n{key[1]}\n{entity}".encode()).hexdigest()[:16]


def evidence(o: Observed, c: Canonical, prefix: str) -> tuple[int, tuple[str, ...]]:
    """(score, the evidence in words) for one pair; (0, ()) when nothing but days speaks."""
    score, why = 0, []
    emails = {key[1] for ref in o.identifiers if (key := _email_key(ref)) is not None}
    theirs = {key[1] for ref in c.refs if (key := _email_key(ref)) is not None}
    for address in sorted(emails & theirs):
        score += EMAIL
        why.append(f"same email {address}")
    numbers = {key[1] for ref in o.identifiers if (key := _phone_key(ref, prefix)) is not None}
    theirs = {key[1] for ref in c.refs if (key := people_merge._phone_key(ref, prefix)) is not None}
    for number in sorted(numbers & theirs):
        score += PHONE
        why.append(f"same phone {number}")
    for label, _n in o.labels.most_common():
        if people_merge.similar_names(label, c.label):
            extra = min(NAME_SOURCE * (len(o.sources) - 1), NAME_SOURCE_CAP)
            score += NAME + extra
            text = f"same name {label}" if label == c.label else f"same name {label} ~ {c.label}"
            if extra:
                text += f" across {', '.join(sorted(o.sources))}"
            why.append(text)
            break
    if not why:
        return 0, ()
    together = len(o.days & c.days)
    if together:
        score += min(TOGETHER * together, TOGETHER_CAP)
        why.append(f"together on {_plural(together, 'day')}")
    return score, tuple(why)


# -- the owner's say -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Written:
    proposal: Proposal
    verdict: str  # `accepted` or `rejected`
    lines: list[Line]

    def to_json(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.id,
            "number": self.proposal.number,
            "verdict": self.verdict,
            "observed": self.proposal.observed.to_json()["key"],
            "into": self.proposal.canonical.to_json(),
            "lines": [str(line["id"]) for line in self.lines],
        }


def numbers(text: Sequence[str] | None) -> list[int]:
    """`N[,N]`, given once or more, to the numbers in order, each once; `ReviewError` on a word
    that is not a number from 1."""
    found: list[int] = []
    for piece in text or ():
        for word in piece.split(","):
            word = word.strip()
            if not word:
                continue
            if not word.isdigit() or int(word) < 1:
                raise ReviewError(
                    f"not a proposal number: {word!r}; `people review` lists them, numbered from 1"
                )
            if int(word) not in found:
                found.append(int(word))
    return found


def pick(report: Report, wanted: Sequence[int]) -> list[Proposal]:
    """The proposals these numbers name; `ReviewError` on one the queue does not have."""
    by_number = {p.number: p for p in report.proposals}
    missing = [n for n in wanted if n not in by_number]
    if missing:
        have = f"the queue has {_plural(len(report.proposals), 'proposal')}"
        raise ReviewError(f"no proposal {', '.join(map(str, missing))}; {have}, `people review` lists them")
    return [by_number[n] for n in wanted]


def above(report: Report, score: str) -> list[Proposal]:
    """Every proposal at or above `score`; `ReviewError` when the score is not a whole number."""
    text = score.strip()
    if not re.fullmatch(r"-?\d+", text):
        raise ReviewError(f"not a score: {score!r}; `--all-above` takes a whole number")
    return [p for p in report.proposals if p.score >= int(text)]


def accept(lb: Logbook, report: Report, proposals: Sequence[Proposal]) -> list[Written]:
    """The proposals accepted: per identifier of the observed person a resolution line can carry,
    as the line wrote it, one alias line to the canonical person's own ref — what `people merge`
    writes — appended through `Logbook.append`. Every proposal is checked before the first line."""
    plans = []
    for p in proposals:
        candidate = p.canonical.candidate
        if candidate is None:
            raise ReviewError(f"{p.canonical.label} ({p.canonical.entity}) has no resolution line of its own")
        try:
            target = people_merge._target(candidate)
        except people_merge.MergeError as e:
            raise ReviewError(str(e)) from e
        plans.append((p, candidate, target))
    at = now_utc()
    written = []
    for p, candidate, target in plans:
        lines = []
        for ref in p.observed.writable:
            own = report.standing.get(ref)
            payload: dict[str, Any] = {
                "schema": people_merge.SCHEMA,
                "ref": {"kind": ref[0], "value": ref[1]},
                "alias_of": {"kind": target[0], "value": target[1]},
                "label": p.canonical.label,
                "method": METHOD,
                "evidence": [str(candidate.lines[target]["id"]), *p.observed.samples],
                "logbook_head": report.head,
                "raw_id": f"review:{p.id}:{ref[0]}:{ref[1]}",
                "extra": {
                    "review": p.id,
                    "into": p.canonical.entity,
                    "score": p.score,
                    "matched": list(p.evidence),
                },
            }
            if own is not None:
                payload["supersedes"] = str(own["id"])
            lines.append(lb.append(at=at, source=SOURCE, kind="resolution", tier=p.tier, payload=payload))
        written.append(Written(p, "accepted", lines))
    return written


def reject(lb: Logbook, report: Report, proposals: Sequence[Proposal]) -> list[Written]:
    """The proposals rejected: one `people-review/v1` line each, saying the observed person and
    the canonical person are not the same, appended through `Logbook.append`."""
    at = now_utc()
    written = []
    for p in proposals:
        o = p.observed
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "verdict": DIFFERENT,
            "ref": {"kind": o.key[0], "value": o.key[1]},
            "refs": [{"kind": k, "value": v} for k, v in o.writable],
            "observed": [label for label, _n in o.labels.most_common()],
            "entity": {"type": "person", "id": p.canonical.entity, "registry": "logbook"},
            "label": p.canonical.label,
            "method": METHOD,
            "evidence": list(o.samples),
            "logbook_head": report.head,
            "raw_id": f"review:{DIFFERENT}:{p.id}",
            "extra": {"review": p.id, "score": p.score, "matched": list(p.evidence)},
        }
        line = lb.append(at=at, source=SOURCE, kind=KIND, tier=p.tier, payload=payload)
        written.append(Written(p, "rejected", [line]))
    return written


# -- priority ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Ranked:
    entity: str
    name: str
    score: int
    days: int
    them: int
    me: int
    meetings: int
    last_real: str | None
    recency: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.entity,
            "name": self.name,
            "score": self.score,
            "days": self.days,
            "messages": {"them": self.them, "me": self.me},
            "meetings": self.meetings,
            "last_real_contact": self.last_real,
            "recency": self.recency,
        }


@dataclass(frozen=True)
class Priority:
    first: str
    last: str
    people: list[Ranked]

    def to_json(self) -> dict[str, Any]:
        return {
            "window": {"since": self.first, "until": self.last},
            "people": [r.to_json() for r in self.people],
        }


def score(days: int, them: int, me: int, meetings: int, since: int | None) -> int:
    """The priority score, the documented sum: 3 per day together, 1 per message exchanged (the
    smaller direction, up to 50), 2 per meeting, 10 when the last real contact is within 30 days,
    5 within 90, 0 when none or longer ago."""
    return DAYS * days + min(MESSAGES * min(them, me), MESSAGES_CAP) + MEETINGS * meetings + recency(since)


def recency(since: int | None) -> int:
    if since is None or since < 0:
        return 0
    if since <= RECENT_DAYS:
        return RECENT
    return RECENTISH if since <= RECENTISH_DAYS else 0


def priority(lb: Logbook, year: str | None = None) -> Priority | None:
    """The canonical people heard in the last year of the record (the 365 days ending on its last
    day), or in `year`, ranked by `score`; None for a record with no day in the window."""
    whole = reading.record_days(lb)
    if whole is None:
        return None
    if year is None:
        last = whole[1]
        first = max(whole[0], (date.fromisoformat(last) - timedelta(days=YEAR - 1)).isoformat())
    else:
        if not re.fullmatch(r"\d{4}", year):
            raise ValueError(f"not a year (YYYY): {year!r}")
        first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
        if last < first:
            return None
    report = people.read(lb, first, last)
    them, me = messages_by_direction(lb, report, first, last)
    end = date.fromisoformat(last)
    ranked = []
    for person in report.people:
        meetings = sum(
            person.channels[name].lines for name in ("calendar", "transcripts") if name in person.channels
        )
        last_real = person.real[0] if person.real is not None else None
        since = None if last_real is None else (end - date.fromisoformat(last_real)).days
        n_them, n_me = them.get(person.entity, 0), me.get(person.entity, 0)
        total = score(len(person.days), n_them, n_me, meetings, since)
        ranked.append(
            Ranked(
                person.entity,
                person.name,
                total,
                len(person.days),
                n_them,
                n_me,
                meetings,
                last_real,
                recency(since),
            )
        )
    ranked.sort(key=lambda r: (-r.score, -r.days, r.last_real or "", r.name.casefold()))
    return Priority(first, last, ranked)


def messages_by_direction(
    lb: Logbook, report: people.Report, first: str, last: str
) -> tuple[dict[str, int], dict[str, int]]:
    """(from them, from the owner) per person, over the standing message lines of the window, by
    the people reader's rule: their line by `sender`; the owner's line in a direct chat to the one
    person who wrote in it, else to the person the chat's id names."""
    them: dict[str, int] = {}
    mine: dict[str, int] = {}
    senders: dict[str, set[str | None]] = {}
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        superseded = idx.superseded("message")
        for line in idx.of_kind("message", first, last):
            if str(line.get("id")) in retracted or str(line.get("id")) in superseded:
                continue
            payload = line.get("payload") or {}
            chat = payload.get("chat")
            chat_id = str(chat.get("id")) if isinstance(chat, dict) and chat.get("id") else None
            direct = isinstance(chat, dict) and chat.get("type") == "direct"
            if payload.get("from_me") is True:
                if chat_id is not None and direct:
                    mine[chat_id] = mine.get(chat_id, 0) + 1
                continue
            entity = _entity(_ref(payload.get("sender")), report)
            if chat_id is not None and direct:
                senders.setdefault(chat_id, set()).add(entity)
            if entity is not None:
                them[entity] = them.get(entity, 0) + 1
    me: dict[str, int] = {}
    for chat_id, n in mine.items():
        others = {e for e in senders.get(chat_id, set()) if e is not None}
        entity = next(iter(others)) if len(others) == 1 else None
        if entity is None and not senders.get(chat_id):
            entity = _entity(_chat_ref(chat_id), report)
        if entity is not None:
            me[entity] = me.get(entity, 0) + n
    return them, me


def _entity(ref: Ref | None, report: people.Report) -> str | None:
    if ref is None:
        return None
    if (
        ref[0] == "handle"
        and (jid := WHATSAPP_JID.match(ref[1])) is not None
        and ref not in report.identities
    ):
        ref = ("phone", f"+{jid.group(1)}")
    entity, _label = present.resolve_ref(ref, report.identities)
    return None if entity is None or entity in report.owner.entities or entity not in report.known else entity


# -- text ----------------------------------------------------------------------------------------------------


def rows(report: Report) -> Iterator[str]:
    """The queue: one numbered line per proposal with the score and the evidence, then what to do."""
    if not report.proposals:
        if report.unplaced:
            yield f"no proposals: {_unplaced(report)} not yet placed, nobody matches"
        else:
            yield "no proposals: nobody observed is unplaced"
        return
    head = f"{_plural(len(report.proposals), 'proposal')} · {_unplaced(report)} not yet placed"
    head += f", {report.placed} placed · tier {report.tier}"
    yield head
    width = len(str(len(report.proposals)))
    for p in report.proposals:
        o = p.observed
        shown = o.key[1] if o.key[0] != "name" else o.name
        seen = ", ".join(f"{kind} {n}" for kind, n in sorted(o.kinds.items()))
        who = f"{shown} ({o.name}; {seen})" if o.name != shown else f"{shown} ({seen})"
        yield f"  {p.number:>{width}}  [{p.score}]  {who} → {p.canonical.label}: {' · '.join(p.evidence)}"
    yield "nothing written: `people review --accept N[,N]`, `--reject N[,N]`, or `--all-above SCORE`"


def written_rows(written: Iterable[Written]) -> Iterator[str]:
    for w in written:
        o, c = w.proposal.observed, w.proposal.canonical
        shown = o.key[1] if o.key[0] != "name" else o.name
        seqs = [int(line["seq"]) for line in w.lines]
        span = f" (seq {seqs[0]})" if len(seqs) == 1 else f" (seq {seqs[0]}{EN_DASH}{seqs[-1]})"
        sign = "→" if w.verdict == "accepted" else NOT_EQUAL
        yield f"{w.verdict} {shown} {sign} {c.label}: {_plural(len(seqs), 'line')}{span}"


def priority_rows(ranked: Priority) -> Iterator[str]:
    people_count = _plural(len(ranked.people), "person", "people")
    yield f"priority · {ranked.first} {EN_DASH} {ranked.last} · {people_count}"
    width = max((len(str(r.score)) for r in ranked.people), default=1)
    names = max((len(r.name) for r in ranked.people), default=0)
    for r in ranked.people:
        parts = []
        if r.days:
            parts.append(f"{_plural(r.days, 'day')} together")
        if r.them or r.me:
            parts.append(f"messages {r.them} from them, {r.me} from you")
        if r.meetings:
            parts.append(f"meetings {r.meetings}")
        parts.append(f"last real contact {r.last_real}" if r.last_real else "no real contact")
        yield f"  {r.score:>{width}}  {r.name:<{names}}  {' · '.join(parts)}"


def _unplaced(report: Report) -> str:
    return _plural(len(report.unplaced), "observed person", "observed people")


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
