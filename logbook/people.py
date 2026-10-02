"""People: who the record knows and what it knows of each — `logbook people` and `logbook person`.

For every person the record's resolution lines name (RFC 0006, a `person` entity; never the owner)
and that has evidence in the window: the **channels** they come through — `messages` (a
`message/v1` they sent, and one the owner sent in a direct chat with them), `calls` (a `call/v1`
whose counterparty they are, answered or not), `mail` (a `mail/v1` from them or to them), `calendar`
(an `event/v1` they attend and did not decline, timed or all-day), `transcripts` (a `transcript/v1`
they spoke in) and `faces` (a `photo/v1` with their face tagged) — each with its lines, first and
last day, the highest tier among them and the last line; **first and last contact** over every
channel and every shared day; the **days together**, the confirmed set of the with module
(`present`: an attendee of a timed entry held at the stay, a speaker of a recording made there, a
note written there that says "with <name>"; a tagged face and an all-day entry are proposals and
not a day together); the **nights under one roof**, the nights whose overnight stay the person was
confirmed at on that day; the **places** shared, by days there; the **birthday** when a standing
resolution line of one of their refs carries one (`payload.extra.birthday`, `YYYY-MM-DD` or
`--MM-DD`, as a contacts adapter writes it); and the **last real contact**: the latest message,
answered call or day together. A mail is a channel and never a real contact — a newsletter is a
mail too, and the record cannot tell them apart; a missed call, a tagged face and an all-day entry
are not one either. The **tier** of a person is the highest tier of their evidence, the resolution
lines that name them included (SPEC §4); the report's is the highest of its people.

`person <name-or-ref>` is one page: the same numbers, then the timeline of the shared days, most
recent first, each with where, the evidence and whether the night was spent under one roof. The
name is a label, a unique first or last name, an entity id, or a ref the record resolves: an email
address, a phone number, or `kind:value` (`handle:...`, `provider_id:immich:p_17`).

Everything is read through the index and nothing is written: the resolution and retraction lines
(`Index.resolutions`, `Index.retractions`), the owner's stays and nights from the index's own
columns (`reading.owner_track`), and the lines of the six kinds above streamed one kind at a time
over the window (`Index.of_kind`), each read once and kept only when it names a person — a year of
messages is counted as it streams and never held. A retracted line, and one another line of its
kind `supersedes` (an edited calendar entry), counts for nothing."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import places as named_places
from . import policy, present, reading, resolve, stays, trips
from .chain import Line
from .export import day_range
from .flights import Airports
from .index import Index
from .resolve import Identity, Ref
from .store import Logbook, retractions

CHANNELS = ("messages", "calls", "mail", "calendar", "transcripts", "faces")
KIND_OF = {
    "messages": "message",
    "calls": "call",
    "mail": "mail",
    "calendar": "event",
    "transcripts": "transcript",
    "faces": "photo",
}
MEETING, MESSAGE, CALL = "meeting", "message", "call"  # how a real contact happened
REAL_ORDER = {MEETING: 0, CALL: 1, MESSAGE: 2}  # on one day, a meeting is the contact to name
BIRTHDAY = re.compile(r"^(\d{4}-\d{2}-\d{2}|--\d{2}-\d{2})$")
REF_KINDS = ("email", "phone", "handle", "provider_id")
PHONE = re.compile(r"^\+\d{6,15}$")
WHATSAPP_DIRECT = re.compile(r"^(\d{6,15})@s\.whatsapp\.net$")
EN_DASH = "\u2013"


class PersonError(ValueError):
    """The page's person is not one the record names, or is the owner."""


# -- what is known of one person -----------------------------------------------------------------------------


@dataclass
class Channel:
    """One channel's lines for one person: how many, the first and last local day, the highest
    tier among them and the last line (by its instant)."""

    lines: int = 0
    first: str | None = None
    last: str | None = None
    tier: int = 0
    last_line: str | None = None
    _last_at: str = ""

    def add(self, day: str, at: str, line_id: str, tier: int) -> None:
        self.lines += 1
        self.first = day if self.first is None else min(self.first, day)
        self.last = day if self.last is None else max(self.last, day)
        self.tier = max(self.tier, tier)
        if at >= self._last_at:
            self._last_at, self.last_line = at, line_id

    def to_json(self) -> dict[str, Any]:
        return {
            "lines": self.lines,
            "first": self.first,
            "last": self.last,
            "tier": self.tier,
            "last_line": self.last_line,
        }


@dataclass
class SharedDay:
    """One day the person was confirmed at one of the owner's stays: the evidence merged."""

    day: str
    stay: str
    where: str
    sources: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    tier: int = 0
    night: str | None = None  # the night's day when it was spent at this stay, under one roof

    def add(self, p: present.Presence, tier: int) -> None:
        if p.source not in self.sources:
            self.sources.append(p.source)
        self.reasons.append(p.reason)
        if p.line not in self.lines:
            self.lines.append(p.line)
        self.tier = max(self.tier, tier)

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "stay": self.stay,
            "where": self.where,
            "night": self.night,
            "sources": list(self.sources),
            "reasons": list(self.reasons),
            "lines": list(self.lines),
        }


@dataclass
class Person:
    entity: str
    name: str
    refs: tuple[Ref, ...]
    birthday: str | None
    tier: int  # of the resolution lines that name them, then raised by every line of evidence
    channels: dict[str, Channel] = field(default_factory=dict)
    shared: dict[tuple[str, str], SharedDay] = field(default_factory=dict)  # (day, stay id)
    real: tuple[str, str, str] | None = None  # (day, via, line) of the last real contact

    def channel(self, name: str) -> Channel:
        return self.channels.setdefault(name, Channel())

    def saw(self, channel: str, day: str, at: str, line_id: str, tier: int) -> None:
        self.channel(channel).add(day, at, line_id, tier)
        self.tier = max(self.tier, tier)

    def contact(self, day: str, via: str, line_id: str) -> None:
        """A real contact on `day`; the latest day wins, and on one day `REAL_ORDER` decides."""
        if self.real is None or (day, -REAL_ORDER[via]) > (self.real[0], -REAL_ORDER[self.real[1]]):
            self.real = (day, via, line_id)

    @property
    def days(self) -> list[str]:
        return sorted({day for day, _stay in self.shared})

    @property
    def nights(self) -> int:
        return sum(1 for s in self.shared.values() if s.night is not None)

    @property
    def places(self) -> list[tuple[str, int]]:
        """The places shared, by days there, most first; a place is counted once per day."""
        by_place: dict[str, set[str]] = {}
        for s in self.shared.values():
            by_place.setdefault(s.where, set()).add(s.day)
        return sorted(((where, len(days)) for where, days in by_place.items()), key=lambda p: (-p[1], p[0]))

    @property
    def first_contact(self) -> str | None:
        found = [c.first for c in self.channels.values() if c.first] + self.days
        return min(found) if found else None

    @property
    def last_contact(self) -> str | None:
        found = [c.last for c in self.channels.values() if c.last] + self.days
        return max(found) if found else None

    @property
    def heard(self) -> bool:
        return bool(self.channels or self.shared)

    def to_json(self) -> dict[str, Any]:
        days = self.days
        return {
            "id": self.entity,
            "name": self.name,
            "refs": [{"kind": k, "value": v} for k, v in self.refs],
            "tier": self.tier,
            "birthday": self.birthday,
            "first_contact": self.first_contact,
            "last_contact": self.last_contact,
            "last_real_contact": None
            if self.real is None
            else {"day": self.real[0], "via": self.real[1], "line": self.real[2]},
            "channels": {name: self.channels[name].to_json() for name in CHANNELS if name in self.channels},
            "days": len(days),
            "nights": self.nights,
            "places": [{"where": where, "days": n} for where, n in self.places],
            "lines": list(dict.fromkeys(id_ for s in self.shared.values() for id_ in s.lines)),
        }


@dataclass(frozen=True)
class Report:
    first: str  # local days, inclusive
    last: str
    tz: ZoneInfo
    people: list[Person]  # everyone heard in the window, most days together first
    known: dict[str, Person]  # every person the record names, heard or not, by entity id
    owner: present.Owner
    identities: dict[Ref, Identity]

    @property
    def tier(self) -> int | None:
        return max((p.tier for p in self.people), default=None)

    def to_json(self) -> dict[str, Any]:
        return {
            "window": {"since": self.first, "until": self.last},
            "tier": self.tier,
            "people": [p.to_json() for p in self.people],
        }


def empty() -> dict[str, Any]:
    """The report of a record with no lines, or of a window the record has no day in."""
    return {"window": None, "tier": None, "people": []}


# -- reading -------------------------------------------------------------------------------------------------


def read(lb: Logbook, first: str, last: str, airports: Airports | None = None) -> Report:
    """The people of `[first, last]` (local days, inclusive). Raises `stays.SettingsError` or
    `policy.PolicyError` as the readers it builds on do; writes nothing."""
    tz = ZoneInfo(str(lb.meta["timezone"]))
    airports = airports or Airports.load()
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()  # a stay's night runs into it
    track = reading.owner_track(lb, first, last, airports)
    with lb.index() as idx:
        marks = idx.retractions()
        resolutions = idx.resolutions()
        retracted = frozenset(retractions(marks))
        identities = resolve.identities_from([*marks, *resolutions])
        owner = present.owner_of(
            str(lb.meta.get("owner_id") or ""),
            [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
            policy.owner_aliases(lb.root),
            identities,
        )
        known = _people_of(identities, resolve.standing([*marks, *resolutions]), owner)
        gather = _Gather(known, identities, owner, tz, first, last)
        evidence: list[Line] = []
        for channel in CHANNELS:
            kind = KIND_OF[channel]
            evidence.extend(gather.stream(channel, _standing(idx, kind, first, spill, retracted)))
        evidence.extend(gather.stream("notes", _standing(idx, "note", first, spill, retracted)))
    gather.finish_messages()
    _together(known, evidence, track, identities, owner, tz, first, last, airports)
    heard = sorted(
        (p for p in known.values() if p.heard),
        key=lambda p: (-len(p.days), _desc(p.last_contact), p.name.casefold()),
    )
    return Report(first, last, tz, heard, known, owner, identities)


def _desc(day: str | None) -> str:
    """A key that sorts later days first: each digit flipped."""
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in (day or "")) or "~"


def _standing(idx: Index, kind: str, first: str, last: str, retracted: frozenset[str]) -> Iterator[Line]:
    """The lines of `kind` in the window that stand: not retracted, not superseded by a line of
    the same kind (a calendar entry edited since is one entry)."""
    superseded = idx.superseded(kind)
    for line in idx.of_kind(kind, first, last):
        id_ = str(line.get("id"))
        if id_ in retracted or id_ in superseded:
            continue
        yield line


def _people_of(
    identities: Mapping[Ref, Identity], standing: Mapping[Ref, Line], owner: present.Owner
) -> dict[str, Person]:
    """Every person the resolution lines name, never the owner: the label (the first standing
    line's), the refs, the birthday any standing line of theirs carries, and the highest tier of
    those lines."""
    people: dict[str, Person] = {}
    for ref, who in identities.items():
        if not who.entity or who.type not in present.PERSON_TYPES or who.entity in owner.entities:
            continue
        person = people.get(who.entity)
        line = standing.get(ref)
        tier = int(line.get("tier", 0)) if line is not None else 0
        birthday = _birthday(line)
        if person is None:
            people[who.entity] = Person(who.entity, who.label or who.entity, (ref,), birthday, tier)
            continue
        person.refs = (*person.refs, ref)
        person.tier = max(person.tier, tier)
        if person.birthday is None:
            person.birthday = birthday
        if person.name == person.entity and who.label:
            person.name = who.label
    return people


def _birthday(line: Line | None) -> str | None:
    if line is None:
        return None
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    value = extra.get("birthday") if isinstance(extra, dict) else None
    return value if isinstance(value, str) and BIRTHDAY.match(value) else None


class _Gather:
    """The channel counting: each kind's lines stream through once; what names a person is counted
    on them, and the lines the with module reads (`present.EVIDENCE_KINDS`) are kept, only when
    they name someone, for the days together."""

    def __init__(
        self,
        people: dict[str, Person],
        identities: Mapping[Ref, Identity],
        owner: present.Owner,
        tz: ZoneInfo,
        first: str,
        last: str,
    ):
        self.people = people
        self.identities = identities
        self.owner = owner
        self.tz = tz
        self.first, self.last = first, last
        self.chats: dict[str, _Chat] = {}

    def stream(self, channel: str, lines: Iterable[Line]) -> list[Line]:
        kept: list[Line] = []
        for line in lines:
            at = stays.instant(line.get("at"))
            if at is None:
                continue
            day = at.astimezone(self.tz).date().isoformat()
            keep = channel in ("calendar", "transcripts", "faces", "notes")
            if keep and _names_someone(line):
                kept.append(line)
            if not self.first <= day <= self.last:
                continue  # the spill day feeds the stays' nights, not the channels
            if channel != "notes":
                self._count(channel, line, day)
        return kept

    def _count(self, channel: str, line: Line, day: str) -> None:
        payload = line.get("payload") or {}
        at, id_, tier = str(line.get("at")), str(line.get("id")), int(line.get("tier", 0))
        for entity, real in self._who(channel, payload, day, at, id_, tier):
            person = self.people.get(entity)
            if person is None:
                continue
            person.saw(channel, day, at, id_, tier)
            if real:
                person.contact(day, real, id_)

    def _who(
        self, channel: str, payload: Mapping[str, Any], day: str, at: str, id_: str, tier: int
    ) -> list[tuple[str, str | None]]:
        """The people one line names on `channel`, each with how it is a real contact (or None)."""
        if channel == "messages":
            return self._message(payload, day, at, id_, tier)
        if channel == "calls":
            entity = self._entity(_ref(payload.get("counterparty")))
            return [] if entity is None else [(entity, CALL if payload.get("answered") is True else None)]
        if channel == "mail":
            found = []
            for header in ("from", "to", "cc", "bcc"):
                value = payload.get(header)
                for address in value if isinstance(value, list) else [value]:
                    email = address.get("email") if isinstance(address, dict) else None
                    if isinstance(email, str) and email.strip():
                        found.append(self._entity(("email", email.strip().casefold())))
            return [(e, None) for e in dict.fromkeys(found) if e is not None]
        if channel == "calendar":
            found = []
            attendees = payload.get("attendees")
            for attendee in attendees if isinstance(attendees, list) else []:
                if isinstance(attendee, dict) and attendee.get("response") != "declined":
                    found.append(self._entity(_ref(attendee.get("ref"))))
            return [(e, None) for e in dict.fromkeys(found) if e is not None]
        if channel == "transcripts":
            found = []
            participants = payload.get("participants")
            for participant in participants if isinstance(participants, list) else []:
                if isinstance(participant, dict):
                    found.append(self._participant(participant))
            return [(e, None) for e in dict.fromkeys(found) if e is not None]
        if channel == "faces":
            library = str(payload.get("library") or "")
            people = payload.get("people")
            found = [
                self._entity(("provider_id", f"{library}:{pid}"))
                for pid in (people if isinstance(people, list) else [])
                if isinstance(pid, str) and pid
            ]
            return [(e, None) for e in dict.fromkeys(found) if e is not None]
        return []

    def _message(
        self, payload: Mapping[str, Any], day: str, at: str, id_: str, tier: int
    ) -> list[tuple[str, str | None]]:
        chat = payload.get("chat")
        chat_id = str(chat.get("id")) if isinstance(chat, dict) and chat.get("id") else None
        direct = isinstance(chat, dict) and chat.get("type") == "direct"
        if payload.get("from_me") is True:
            if chat_id is not None and direct:
                self.chats.setdefault(chat_id, _Chat()).mine.append((day, at, id_, tier))
            return []
        entity = self._entity(_ref(payload.get("sender")))
        if chat_id is not None and direct:
            self.chats.setdefault(chat_id, _Chat()).senders.add(entity)
        return [] if entity is None else [(entity, MESSAGE)]

    def finish_messages(self) -> None:
        """The owner's own lines in a direct chat go to the one person who wrote in it; in a chat
        nobody else wrote in, to the person the chat's id names (a WhatsApp JID is a phone
        number; iMessage names a direct chat by the address). A group's lines name nobody."""
        for chat_id, chat in self.chats.items():
            if not chat.mine:
                continue
            others = {e for e in chat.senders if e is not None}
            entity = next(iter(others)) if len(others) == 1 else None
            if entity is None and not chat.senders:
                entity = self._entity(_chat_ref(chat_id))
            person = None if entity is None else self.people.get(entity)
            if person is None:
                continue
            for day, at, id_, tier in chat.mine:
                person.saw("messages", day, at, id_, tier)
                person.contact(day, MESSAGE, id_)

    def _entity(self, ref: Ref | None) -> str | None:
        if ref is None:
            return None
        entity, _label = present.resolve_ref(ref, self.identities)
        return None if entity is None or entity in self.owner.entities else entity

    def _participant(self, participant: Mapping[str, Any]) -> str | None:
        for kind, key in (("email", "email"), ("phone", "phone"), ("provider_id", "provider_id")):
            value = participant.get(key)
            if isinstance(value, str) and value:
                entity = self._entity((kind, value))
                if entity is not None:
                    return entity
        spoken = participant.get("name")
        if isinstance(spoken, str) and spoken.strip():
            entity, _label = present.by_name(spoken, self.identities)
            if entity is not None and entity not in self.owner.entities:
                return entity
        return None


@dataclass
class _Chat:
    senders: set[str | None] = field(default_factory=set)  # who wrote in it (None: unresolved)
    mine: list[tuple[str, str, str, int]] = field(default_factory=list)  # (day, at, id, tier) of the owner's


def _chat_ref(chat_id: str) -> Ref | None:
    """The ref a direct chat's id names: `4790000001@s.whatsapp.net` is a phone, an address or a
    number as such is itself."""
    jid = WHATSAPP_DIRECT.match(chat_id)
    if jid is not None:
        return ("phone", f"+{jid.group(1)}")
    if PHONE.match(chat_id):
        return ("phone", chat_id)
    if "@" in chat_id:
        return ("email", chat_id.strip().casefold())
    return None


def _names_someone(line: Line) -> bool:
    """Whether a line of one of the with module's kinds can name anyone at all; one that cannot is
    not kept for the stays."""
    payload = line.get("payload") or {}
    kind = line.get("kind")
    if kind == "event":
        return bool(payload.get("attendees"))
    if kind == "transcript":
        return bool(payload.get("participants"))
    if kind == "photo":
        return bool(payload.get("people"))
    if kind == "note":
        return present.WITH.search(str(payload.get("text") or "")) is not None
    return False


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(ref_value, str) or not ref_value:
        return None
    return kind, ref_value


def _together(
    people: dict[str, Person],
    evidence: Iterable[Line],
    track: reading.OwnerTrack,
    identities: Mapping[Ref, Identity],
    owner: present.Owner,
    tz: ZoneInfo,
    first: str,
    last: str,
    airports: Airports,
) -> None:
    """The days together and the nights under one roof: the with module's confirmed set at each of
    the owner's stays, dated by the evidence line's own day; a night counts when its stay is one
    the person was confirmed at on that day (`rollup people`'s rule)."""
    lines = list(evidence)
    days_of = {
        str(line["id"]): at.astimezone(tz).date().isoformat()
        for line in lines
        if (at := stays.instant(line.get("at"))) is not None
    }
    tiers = {str(line["id"]): int(line.get("tier", 0)) for line in lines}
    near = present.Evidence(lines, tz)
    for stay in track.stays:
        stay_day = stay.start.astimezone(tz).date().isoformat()
        where = None
        for p in present.present(stay, near.near(stay), identities, track.places, owner):
            if p.status != present.CONFIRMED or p.person is None or p.person not in people:
                continue
            day = days_of.get(p.line, stay_day)
            if not first <= day <= last:
                continue
            if where is None:
                where = _where(stay, track.places, airports)
            person = people[p.person]
            shared = person.shared.setdefault((day, stay.id), SharedDay(day, stay.id, where))
            shared.add(p, tiers.get(p.line, 0))
            person.tier = max(person.tier, tiers.get(p.line, 0))
            person.contact(day, MEETING, p.line)
    for day in day_range(first, last):
        night = stays.night(track.stays, day, tz, track.settings, track.places)
        if night.stay is None:
            continue
        for person in people.values():
            at_night = person.shared.get((day, night.stay.id))
            if at_night is not None:
                at_night.night = day


def _where(stay: stays.Segment, places: list[named_places.Place], airports: Airports) -> str:
    """How a stay reads: its named place; `aboard <asset>`; else its coordinates with `near
    <place>, x km` for a named place within `trips.NEAR_KM`, or the city of the nearest large
    airport in parentheses (the rollups' rule for an unnamed place)."""
    if stay.place:
        return stay.place
    if stay.aboard:
        return f"aboard {stay.aboard}"
    if stay.lat is None or stay.lon is None:
        return "somewhere"
    label = f"{stay.lat:.4f},{stay.lon:.4f}"
    near = named_places.nearest(stay.lat, stay.lon, places)
    if near is not None and near[1] <= trips.NEAR_KM * 1000:
        return f"{label} near {near[0].name}, {near[1] / 1000:.1f} km"
    city = trips.city_near(stay.lat, stay.lon, airports)
    return f"{label} ({city})" if city else label


# -- one person ----------------------------------------------------------------------------------------------


def find(name: str, report: Report) -> Person:
    """The person `name` means: an entity id, a ref (an address, a `+` number, or `kind:value`),
    a label (case aside), or a unique first or last name. `PersonError` when nobody, several, or
    the owner."""
    text = " ".join(name.split())
    owner = report.owner
    for ref in _refs_of(text):
        who = report.identities.get(ref)
        if who is not None and who.entity and who.type in present.PERSON_TYPES:
            if who.entity in owner.entities:
                raise PersonError(f"{text!r} is the owner; a person page is never the owner's")
            if who.entity in report.known:
                return report.known[who.entity]
    if text in report.known:
        return report.known[text]
    if text in owner.entities:
        raise PersonError(f"{text!r} is the owner; a person page is never the owner's")
    wanted = text.casefold()
    labels = {entity: p.name for entity, p in report.known.items()}
    for entity, label in _owner_labels(report).items():
        labels.setdefault(entity, label)
    exact = [e for e, label in labels.items() if " ".join(label.split()).casefold() == wanted]
    found = (
        exact
        if exact
        else [e for e, label in labels.items() if wanted in (w.casefold() for w in label.split())]
    )
    if (len(found) == 1 and found[0] in owner.entities) or (not found and wanted in owner.names):
        raise PersonError(f"{text!r} is the owner; a person page is never the owner's")
    if len(found) > 1:
        raise PersonError(f"{text!r} names several people: {', '.join(sorted(labels[e] for e in found))}")
    if not found:
        raise PersonError(f"{text!r} is nobody the record's resolution lines name")
    return report.known[found[0]]


def _owner_labels(report: Report) -> dict[str, str]:
    """The owner's entities and the labels they carry, so that a name that is the owner's is
    refused as such and not as nobody."""
    found: dict[str, str] = {}
    for who in report.identities.values():
        if who.entity and who.entity in report.owner.entities and who.label:
            found.setdefault(who.entity, who.label)
    return found


def _refs_of(text: str) -> list[Ref]:
    kind, colon, value = text.partition(":")
    if colon and kind in REF_KINDS and value:
        return [(kind, value.casefold() if kind == "email" else value)]
    if "@" in text and " " not in text:
        return [("email", text.casefold()), ("handle", text)]
    if PHONE.match(text.replace(" ", "")):
        return [("phone", text.replace(" ", ""))]
    return []


def page(report: Report, person: Person) -> dict[str, Any]:
    """One person's page: the report's numbers and the shared days, most recent first."""
    shared = sorted(person.shared.values(), key=lambda s: (s.day, s.stay), reverse=True)
    return {
        "page": "person",
        "window": {"since": report.first, "until": report.last},
        **person.to_json(),
        "shared_days": [s.to_json() for s in shared],
    }


# -- text ----------------------------------------------------------------------------------------------------


def rows(report: Report) -> Iterator[str]:
    """One row per person, most days together first."""
    n = len(report.people)
    yield f"{_plural(n, 'person', 'people')} · {report.first} {EN_DASH} {report.last} · tier {report.tier}"
    width = max((len(p.name) for p in report.people), default=0)
    for p in report.people:
        yield f"  {p.name:<{width}}  {' · '.join(_summary(p))}"


def _summary(p: Person) -> list[str]:
    parts = [_channels(p)]
    if p.days:
        together = _plural(len(p.days), "day")
        if p.nights:
            together += f" · {_plural(p.nights, 'night')}"
        parts.append(together)
    if p.real is not None:
        parts.append(f"last real contact {p.real[0]} ({p.real[1]})")
    if p.birthday:
        parts.append(f"birthday {p.birthday}")
    if p.places:
        parts.append(", ".join(where for where, _n in p.places))
    return parts


def _channels(p: Person) -> str:
    return " · ".join(f"{name} {p.channels[name].lines}" for name in CHANNELS if name in p.channels)


def person_rows(data: Mapping[str, Any]) -> Iterator[str]:
    """The page as text: the head, the numbers, then the shared days, most recent first."""
    refs = ", ".join(r["value"] for r in data["refs"])
    yield f"{data['name']}  ({refs}) · tier {data['tier']}"
    if data["birthday"]:
        yield f"  birthday {data['birthday']}"
    if data["first_contact"] is None:
        yield "  no contact in the record"
        return
    contact = f"  first contact {data['first_contact']} · last {data['last_contact']}"
    real = data["last_real_contact"]
    if real is not None:
        contact += f" · last real contact {real['day']} ({real['via']})"
    yield contact
    channels = [
        f"{name} {c['lines']} ({_span(c['first'], c['last'])})" for name, c in data["channels"].items()
    ]
    if channels:
        yield f"  channels  {' · '.join(channels)}"
    if data["days"]:
        together = f"  {_plural(data['days'], 'day')} together"
        if data["nights"]:
            together += f" · {_plural(data['nights'], 'night')} under one roof"
        yield together
    if data["places"]:
        yield "  places  " + ", ".join(f"{p['where']} ({_plural(p['days'], 'day')})" for p in data["places"])
    if data["shared_days"]:
        yield "  shared days"
        for s in data["shared_days"]:
            night = " · night" if s["night"] else ""
            yield f"    {s['day']}  {s['where']} · {', '.join(s['reasons'])}{night}"


def _span(first: str, last: str) -> str:
    return first if first == last else f"{first} {EN_DASH} {last}"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
