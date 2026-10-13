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

**The table.** Observed people are the person rows of the index's derived table,
`observed_entities` in `index.sqlite` (RFC 0037), read through its view `observed_people`, keyed
by (kind, value) of the strongest identifier, with the display names and the identifiers as the
lines wrote them, counts per source and per kind, the days seen, first and last
seen, the tier, a few line ids as evidence, and the canonical person the observation resolves to
when one of its identifiers has a resolution standing (as written: the readers look a ref up as the
line carries it) or, for a name alone, when the people reader would place it by that name. The table
is built from the lines through the index (`Index.of_kind`, mail, message, transcript and event,
standing lines only, the owner's own identities left out), stamped with the head it was built at (in
`observed_entities_meta`), served while the head stands and rebuilt when the record grows; its shape
is checked with `PRAGMA table_info` and a table of another shape is built again. Nothing is stored
in the record.

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

from ..core import day_start, people, policy, present, reading, resolve, stays
from ..core.chain import Line
from ..core.index import Index
from ..core.resolve import Identity, Ref
from ..core.store import Logbook, now_utc, retractions, uuid7
from . import google_contacts, people_merge
from .adapters import phone as phones
from .adapters import service_account
from .adapters.ios_contacts import DIAL_PREFIX_ENV
from .google_contacts import Contact

KIND = "people-review"  # the line a rejection writes
SCHEMA = "people-review/v1"
DIFFERENT = "different"
SOURCE = people_merge.SOURCE
METHOD = people_merge.METHOD
KINDS = ("mail", "message", "transcript", "event")  # the lines a counterpart is observed on
REF_KINDS = ("email", "phone", "handle", "provider_id")  # an identifier a resolution line can carry
TABLE = "observed_people"  # the view of the person rows of `observed_entities` (RFC 0037)
OBSERVED_KIND = "person"
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
CONTACT, CONTACT_NAME = 50, 20  # a Google contact holds the observed identifier and the canonical's, or name
NAMED_TIER = 2  # a name from the owner's address book is personal: a resolution over it is tier 2 at least
NAMED_FROM = "google contacts"  # the name source a new person's name came from, under `extra`
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

    def _row(self) -> dict[str, Any]:
        """The row of `observed_entities` (`Index.store_observed`) the view reads back as `COLUMNS`."""
        return {
            "key_kind": self.key[0],
            "key_value": self.key[1],
            "name": self.name,
            "entity": self.entity,
            "labels": json.dumps(dict(self.labels), ensure_ascii=False),
            "refs": json.dumps([[k, v, n] for (k, v), n in self.identifiers.items()], ensure_ascii=False),
            "sources": json.dumps(dict(self.sources), ensure_ascii=False),
            "kinds": json.dumps(dict(self.kinds), ensure_ascii=False),
            "days": json.dumps(sorted(self.days)),
            "first": self.first,
            "last": self.last,
            "count": self.lines,
            "tier": self.tier,
            "samples": json.dumps(self.samples),
        }

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
    if _table_current(idx, stamp):
        rows = idx.db.execute(
            f"SELECT {', '.join(COLUMNS)} FROM {TABLE} ORDER BY key_kind, key_value"
        ).fetchall()
        return [Observed._from_row(row) for row in rows]
    found = build(lb, idx)
    idx.store_observed(OBSERVED_KIND, [o._row() for o in found], stamp)
    return found


def _table_current(idx: Index, stamp: Mapping[str, str]) -> bool:
    """Whether the view is there, of the shape this module reads, and its rows stamped with this head."""
    try:
        columns = {str(row[1]) for row in idx.db.execute(f"PRAGMA table_info({TABLE})")}
    except sqlite3.DatabaseError:
        return False
    return set(COLUMNS) <= columns and idx.observed_stamp(OBSERVED_KIND) == dict(stamp)


def build(lb: Logbook, idx: Index) -> list[Observed]:
    """The pure read: every observed person from the standing mail, message, transcript and event
    lines, streamed one kind at a time, keyed by the strongest identifier, the owner's own
    identities left out, each placed when the record resolves it."""
    meta = lb.meta
    days = day_start.of(meta)  # a line's day under the record's day_start (RFC 0036)
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
            day = days.day(at).isoformat()
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
    """One pair for the owner to decide: the observed person and a canonical one, or — from a name
    source, `canonical` None — a Google contact whose name the observed person would be given, as a
    new person."""

    number: int
    id: str
    observed: Observed
    canonical: Canonical | None
    score: int
    evidence: tuple[str, ...]
    contact: Contact | None = None

    @property
    def label(self) -> str:
        if self.canonical is not None:
            return self.canonical.label
        return str(self.contact.name if self.contact is not None else "")

    @property
    def tier(self) -> int:
        if self.canonical is not None:
            return max(self.observed.tier, self.canonical.tier)
        return max(self.observed.tier, NAMED_TIER)

    def to_json(self) -> dict[str, Any]:
        found: dict[str, Any] = {
            "number": self.number,
            "id": self.id,
            "score": self.score,
            "evidence": list(self.evidence),
            "observed": self.observed.to_json(),
            "canonical": self.canonical.to_json() if self.canonical is not None else None,
        }
        if self.contact is not None:
            found["contact"] = self.contact.shown()
        return found


@dataclass(frozen=True)
class Report:
    proposals: list[Proposal]
    unplaced: list[Observed]
    placed: int
    canonicals: dict[str, Canonical]
    rejected: Rejected
    standing: dict[Ref, Line]
    head: str
    book: google_contacts.Book | None = None  # the Google contacts weighed, with --from-google
    duplicates: list[google_contacts.Duplicate] = field(default_factory=list)

    @property
    def tier(self) -> int | None:
        return max((p.tier for p in self.proposals), default=None)

    def to_json(self) -> dict[str, Any]:
        found: dict[str, Any] = {
            "tier": self.tier,
            "observed": {"placed": self.placed, "unplaced": [o.to_json() for o in self.unplaced]},
            "rejected": self.rejected.pairs,
            "proposals": [p.to_json() for p in self.proposals],
        }
        if self.book is not None:
            found["contacts"] = {
                **self.book.to_json(),
                "duplicates": [d.to_json() for d in self.duplicates],
            }
        return found


def read(lb: Logbook, book: google_contacts.Book | None = None) -> Report:
    """The queue of the record at its head: the observed people through the index's table, the
    canonical people through the `people` reader, the owner's rejections through the standing
    `people-review` lines; with `book`, the owner's Google contacts as a name source too (evidence for
    a pair, a name for a new person, the duplicates among them), less the contact proposals the owner
    rejected. Writes nothing to the record. Raises what `people.read` raises."""
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
    contacts = book.contacts if book is not None else ()
    passed = google_contacts.rejected(lb.root) if book is not None else frozenset()
    proposals = propose(unplaced, canonicals, rejected, prefix, contacts, passed)
    placed_count = sum(1 for o in rows if o.entity is not None)
    return Report(
        proposals,
        unplaced,
        placed_count,
        canonicals,
        rejected,
        standing,
        str(lb.meta["head"]),
        book,
        google_contacts.duplicates(contacts, prefix) if book is not None else [],
    )


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
    contacts: Sequence[Contact] = (),
    passed: frozenset[str] = frozenset(),
) -> list[Proposal]:
    """The pure function: every (observed, canonical) pair with evidence, the owner's Google contacts
    among it when given, and every (observed, contact) pair a contact would name as a new person (less
    the ones in `passed`, rejected), ranked by score, then by how much evidence, then by the observed
    key and the label; numbered from 1."""
    links = Links(contacts, canonicals, prefix) if contacts else None
    found: list[tuple[int, tuple[str, ...], Observed, Canonical | None, Contact | None, str]] = []
    for o in unplaced:
        if not o.writable:
            continue
        linked, naming = links.of(o) if links is not None else ({}, [])
        for c in canonicals.values():
            if rejected.holds(o, c.entity):
                continue
            link = linked.get(c.entity)
            score, why = evidence(o, c, prefix, (link,) if link is not None else ())
            if score:
                found.append((score, why, o, c, None, proposal_id(o.key, c.entity)))
        for k, score, why in naming:
            pid = naming_id(o.key, k)
            if pid not in passed:
                found.append((score, why, o, None, k, pid))
    found.sort(
        key=lambda f: (
            -f[0],
            -len(f[1]),
            f[2].key,
            (f[3].label if f[3] is not None else str(f[4].name if f[4] else "")).casefold(),
            f[5],
        )
    )
    return [
        Proposal(n, pid, o, c, score, why, k) for n, (score, why, o, c, k, pid) in enumerate(found, start=1)
    ]


def proposal_id(key: Ref, entity: str) -> str:
    return hashlib.sha256(f"{key[0]}\n{key[1]}\n{entity}".encode()).hexdigest()[:16]


def naming_id(key: Ref, contact: Contact) -> str:
    """A contact proposal's id: a digest that names neither the person nor the contact."""
    return hashlib.sha256(f"{key[0]}\n{key[1]}\ncontact\n{contact.id}".encode()).hexdigest()[:16]


class Links:
    """What the owner's Google contacts say about the observed people, against the canonical ones. A
    contact that holds an observed person's address or number **links** them to a canonical person
    when it also holds one of the canonical person's own (`CONTACT` points), or else when its name is
    the canonical person's (`CONTACT_NAME`): evidence for that pair. A contact that touches no canonical
    person — none of its identifiers is theirs, its name is none of theirs — and has a name **names**
    the observed people it holds an identifier of, or whose shown name is its own: a proposal of a new
    person by that name, scored as a pair is (the same email, phone, name). Indexed by identifier and
    by name word, so an observed person meets only the contacts that could speak for it."""

    def __init__(self, contacts: Sequence[Contact], canonicals: Mapping[str, Canonical], prefix: str) -> None:
        self.prefix = prefix
        self.contacts = list(contacts)
        self.ids = [google_contacts.keys(k, prefix) for k in self.contacts]
        self.by_key: dict[Ref, list[int]] = {}
        self.by_word: dict[str, list[int]] = {}
        for i, (k, ids) in enumerate(zip(self.contacts, self.ids, strict=True)):
            for key in ids:
                self.by_key.setdefault(key, []).append(i)
            for word in set(people_merge._words(k.name or "")):
                self.by_word.setdefault(word, []).append(i)
        self.owners: dict[Ref, set[str]] = {}
        labels: dict[str, set[str]] = {}
        for entity, c in canonicals.items():
            for key in _keys(c.refs, prefix, canonical=True):
                self.owners.setdefault(key, set()).add(entity)
            for word in set(people_merge._words(c.label)):
                labels.setdefault(word, set()).add(entity)
        self.by_id = [{e for key in ids for e in self.owners.get(key, ())} for ids in self.ids]
        self.by_name: list[set[str]] = []
        for k in self.contacts:
            near = {e for word in people_merge._words(k.name or "") for e in labels.get(word, ())}
            self.by_name.append(
                {e for e in near if people_merge.similar_names(k.name or "", canonicals[e].label)}
            )
        self.free = [
            bool(k.name) and not self.by_id[i] and not self.by_name[i] for i, k in enumerate(self.contacts)
        ]

    def of(
        self, o: Observed
    ) -> tuple[dict[str, tuple[int, str]], list[tuple[Contact, int, tuple[str, ...]]]]:
        """For one observed person: the strongest thing a contact says for each canonical person, in
        points and words, and each contact that would name it as a new person, with the score and the
        evidence."""
        mine = _keys(o.identifiers, self.prefix)
        holding = {i for key in mine for i in self.by_key.get(key, ())}
        links: dict[str, tuple[int, str]] = {}
        for i in sorted(holding):
            k, ids = self.contacts[i], self.ids[i]
            held = sorted(ids & mine)[0][1]
            who = f"Google contact {k.name}" if k.name else "a Google contact"
            found: dict[str, tuple[int, str]] = {}
            for entity in self.by_id[i]:
                bridge = sorted(key for key in ids - mine if entity in self.owners.get(key, ()))
                if bridge:
                    found[entity] = (CONTACT, f"{who} has {held} and {bridge[0][1]}")
            for entity in self.by_name[i] - set(found):
                found[entity] = (CONTACT_NAME, f"{who} has {held}")
            for entity, link in found.items():
                if entity not in links or (-link[0], link[1]) < (-links[entity][0], links[entity][1]):
                    links[entity] = link
        words = {word for label in o.labels for word in people_merge._words(label)}
        near = holding | {i for word in words for i in self.by_word.get(word, ())}
        naming = []
        for i in sorted(near):
            if not self.free[i]:
                continue
            k, ids = self.contacts[i], self.ids[i]
            score, why = 0, []
            for kind, points in (("email", EMAIL), ("phone", PHONE)):
                for _kind, value in sorted(key for key in ids & mine if key[0] == kind):
                    score += points
                    why.append(f"same {kind} {value}")
            for label, _n in o.labels.most_common():
                if people_merge.similar_names(label, k.name or ""):
                    extra = min(NAME_SOURCE * (len(o.sources) - 1), NAME_SOURCE_CAP)
                    score += NAME + extra
                    why.append(f"same name {label}" if label == k.name else f"same name {label} ~ {k.name}")
                    break
            if why:
                naming.append((k, score, tuple(why)))
        return links, naming


def _keys(refs: Iterable[Ref], prefix: str, canonical: bool = False) -> frozenset[Ref]:
    """Refs as the review keys an identifier: an address case aside, a number in E.164."""
    found: set[Ref] = set()
    for ref in refs:
        key = _email_key(ref) or (
            people_merge._phone_key(ref, prefix) if canonical else _phone_key(ref, prefix)
        )
        if key is not None:
            found.add(key)
    return frozenset(found)


def evidence(
    o: Observed, c: Canonical, prefix: str, linked: Sequence[tuple[int, str]] = ()
) -> tuple[int, tuple[str, ...]]:
    """(score, the evidence in words) for one pair, with what a Google contact says for it (`linked`,
    from `Links`); (0, ()) when nothing but days speaks."""
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
    for points, text in linked:
        score += points
        why.append(text)
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
        p = self.proposal
        into: dict[str, Any]
        if p.canonical is not None:
            into = p.canonical.to_json()
        else:  # a new person, named after a contact: its id is the one the lines minted, if any
            minted = self.lines[0]["payload"]["entity"]["id"] if self.lines else None
            into = {"id": minted, "name": p.label, "new": True}
        return {
            "proposal": p.id,
            "number": p.number,
            "verdict": self.verdict,
            "observed": p.observed.to_json()["key"],
            "into": into,
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
    writes — appended through `Logbook.append`. A proposal from a name source (a Google contact) mints
    a person instead: one entity line per identifier, the contact's name as the label, one entity for
    every proposal of one contact in the run; nothing else of the contact is written. Every proposal is
    checked before the first line."""
    plans: list[tuple[Proposal, people_merge.Candidate | None, Ref | None]] = []
    keys: dict[Ref, Proposal] = {}
    for p in proposals:
        other = keys.setdefault(p.observed.key, p)
        if other is not p:
            raise ReviewError(
                f"proposals {other.number} and {p.number} place {p.observed.name} with two people;"
                " accept one, and reject the other or leave it"
            )
        if p.canonical is None:
            if p.contact is None or not p.contact.name:
                raise ReviewError(f"proposal {p.number} names nobody")
            plans.append((p, None, None))
            continue
        candidate = p.canonical.candidate
        if candidate is None:
            raise ReviewError(f"{p.canonical.label} ({p.canonical.entity}) has no resolution line of its own")
        try:
            plans.append((p, candidate, people_merge._target(candidate)))
        except people_merge.MergeError as e:
            raise ReviewError(str(e)) from e
    at = now_utc()
    written = []
    minted: dict[str, str] = {}  # a contact's id → the person minted for it in this run
    for p, candidate, target in plans:
        if p.canonical is None or candidate is None or target is None:
            written.append(Written(p, "accepted", _named(lb, report, p, minted, at)))
            continue
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


def _named(lb: Logbook, report: Report, p: Proposal, minted: dict[str, str], at: str) -> list[Line]:
    """A contact proposal accepted: the observed person becomes a person of the record, named after
    the contact, through one entity line per identifier the lines wrote (RFC 0006: the first mints
    the id, the rest reuse it). The name is all that comes of the contact."""
    contact = p.contact
    if contact is None or not contact.name:  # never: `accept` checks every proposal before the first line
        raise ReviewError(f"proposal {p.number} names nobody")
    entity = minted.setdefault(contact.id, uuid7())
    lines = []
    for ref in p.observed.writable:
        own = report.standing.get(ref)
        payload: dict[str, Any] = {
            "schema": people_merge.SCHEMA,
            "ref": {"kind": ref[0], "value": ref[1]},
            "entity": {"type": "person", "id": entity, "registry": "logbook"},
            "label": contact.name,
            "method": METHOD,
            "evidence": list(p.observed.samples),
            "logbook_head": report.head,
            "raw_id": f"review:{p.id}:{ref[0]}:{ref[1]}",
            "extra": {
                "review": p.id,
                "score": p.score,
                "matched": list(p.evidence),
                "named_from": NAMED_FROM,
            },
        }
        if own is not None:
            payload["supersedes"] = str(own["id"])
        lines.append(lb.append(at=at, source=SOURCE, kind="resolution", tier=p.tier, payload=payload))
    return lines


def reject(lb: Logbook, report: Report, proposals: Sequence[Proposal]) -> list[Written]:
    """The proposals rejected: one `people-review/v1` line each, saying the observed person and
    the canonical person are not the same, appended through `Logbook.append`. A contact proposal's no
    writes no line, the contact not being in the record: its id is kept in
    `state/google-contacts-review.json` (`google_contacts.reject`) and it is not proposed again."""
    at = now_utc()
    passed = [p.id for p in proposals if p.canonical is None]
    if passed:
        google_contacts.reject(lb.root, passed, at)
    written = []
    for p in proposals:
        if p.canonical is None:
            written.append(Written(p, "rejected", []))
            continue
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
    """The queue: one numbered line per proposal with the score and the evidence, the Google contacts
    weighed and their duplicates when they were, then what to do."""
    if not report.proposals:
        if report.unplaced:
            yield f"no proposals: {_unplaced(report)} not yet placed, nobody matches"
        else:
            yield "no proposals: nobody observed is unplaced"
        yield from contact_rows(report)
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
        yield f"  {p.number:>{width}}  [{p.score}]  {who} → {_target(p)}: {' · '.join(p.evidence)}"
    yield from contact_rows(report)
    flag = " --from-google" if report.book is not None else ""
    yield f"nothing written: `people review{flag} --accept N[,N]`, `--reject N[,N]`, or `--all-above SCORE`"


def _target(p: Proposal) -> str:
    """Who a proposal places the observed person with: a canonical person's label, or a contact's name
    and the book it is in, as a new person."""
    if p.canonical is not None or p.contact is None:
        return p.label
    return f"{p.contact.name}, new (Google {p.contact.book})"


def contact_rows(report: Report) -> Iterator[str]:
    """What was weighed of the Google contacts: how many, when they were read, any book not read, and
    the groups of contacts that share an address or a number. Never a contact in full."""
    book = report.book
    if book is None:
        return
    counts = book.counts()
    when = f"{'from the cache, read' if book.cached else 'read'} {book.read_at}"
    hours = int(google_contacts.TTL.total_seconds() // 3600)
    yield (
        f"google contacts: {counts[google_contacts.CONTACTS]:,} contacts, {counts[google_contacts.OTHER]:,}"
        f" other contacts, {when}, kept {hours} h in {google_contacts.CACHE.as_posix()}"
    )
    for name in book.refused:
        yield f"  {name}: not read; the delegation does not grant {service_account.SCOPES[name]}"
    if not report.duplicates:
        return
    groups = _plural(len(report.duplicates), "group")
    yield f"{groups} of duplicate contacts, to merge in Google Contacts (Merge & fix; the key only reads):"
    for d in report.duplicates:
        names = " ↔ ".join(c.name or "(no name)" for c in d.contacts)
        yield f"  {names}: {' · '.join(d.evidence)}"


def written_rows(written: Iterable[Written]) -> Iterator[str]:
    for w in written:
        o = w.proposal.observed
        shown = o.key[1] if o.key[0] != "name" else o.name
        sign = "→" if w.verdict == "accepted" else NOT_EQUAL
        target = _target(w.proposal)
        if not w.lines:
            kept = f"no line, a contact is not in the record; kept in {google_contacts.REJECTED.as_posix()}"
            yield f"{w.verdict} {shown} {sign} {target}: {kept}"
            continue
        seqs = [int(line["seq"]) for line in w.lines]
        span = f" (seq {seqs[0]})" if len(seqs) == 1 else f" (seq {seqs[0]}{EN_DASH}{seqs[-1]})"
        yield f"{w.verdict} {shown} {sign} {target}: {_plural(len(seqs), 'line')}{span}"


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
