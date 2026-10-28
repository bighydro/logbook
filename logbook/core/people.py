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
messages is counted as it streams and never held; its ids are kept. A retracted line, and one
another line of its kind `supersedes` (an edited calendar entry), counts for nothing; nor does an
agent (`logbook.core.machine`): a message in a conversation with one, whoever wrote it, and a
transcript's participant marked machine, whatever its name, name nobody."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import attribution, day_start, kept, machine, policy, present, reading, resolve, speakers, stays, trips
from . import places as named_places
from .chain import Line
from .day_start import DayStart
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
    tier among them, the last line (by its instant) and the ids of them all (`ids`, for a reader
    that compares windows, `rollup people --drifting`; the lines themselves are never held)."""

    lines: int = 0
    first: str | None = None
    last: str | None = None
    tier: int = 0
    last_line: str | None = None
    ids: list[str] = field(default_factory=list)
    spoke_s: float | None = None  # transcripts: the seconds of the voices bound to them (RFC 0038 §3.4)
    _last_at: str = ""

    def add(self, day: str, at: str, line_id: str, tier: int) -> None:
        self.lines += 1
        self.ids.append(line_id)
        self.first = day if self.first is None else min(self.first, day)
        self.last = day if self.last is None else max(self.last, day)
        self.tier = max(self.tier, tier)
        if at >= self._last_at:
            self._last_at, self.last_line = at, line_id

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "lines": self.lines,
            "first": self.first,
            "last": self.last,
            "tier": self.tier,
            "last_line": self.last_line,
        }
        if self.spoke_s is not None:  # only once a voice is bound to them: the channel otherwise as it was
            out["spoke_s"] = round(self.spoke_s, 2)
        return out


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
    day_start: DayStart | None = None  # where the record's day begins (RFC 0036); None is midnight in `tz`
    unnamed: int = 0  # the people the owner bound a voice to and would not name, who spoke in the window
    not_yet_named: int = 0  # the voices of the window's transcripts nobody has said whose they are

    @property
    def days(self) -> DayStart:
        return self.day_start or DayStart(self.tz)

    @property
    def tier(self) -> int | None:
        return max((p.tier for p in self.people), default=None)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "window": {"since": self.first, "until": self.last},
            "tier": self.tier,
            "people": [p.to_json() for p in self.people],
        }
        if self.unnamed or self.not_yet_named:  # RFC 0038 §3.4: counted, never rows
            out["unnamed"] = self.unnamed
            out["not_yet_named"] = self.not_yet_named
        return out


def empty() -> dict[str, Any]:
    """The report of a record with no lines, or of a window the record has no day in."""
    return {"window": None, "tier": None, "people": []}


# -- reading -------------------------------------------------------------------------------------------------


def read(
    lb: Logbook,
    first: str,
    last: str,
    airports: Airports | None = None,
    admit: Callable[[Line], bool] | None = None,
) -> Report:
    """The people of `[first, last]` (local days, inclusive). `admit`, when given, is a gate every
    resolution line and every line of evidence must pass before it counts (a crossing's tier and
    signed days: `export notion`), so no person, channel, contact or day together rests on a line it
    refuses. Raises `stays.SettingsError` or `policy.PolicyError` as the readers it builds on do;
    writes nothing."""
    days = day_start.of(lb.meta)  # a line's day under the record's day_start (RFC 0036)
    tz = days.zone
    airports = airports or Airports.load()
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()  # a stay's night runs into it
    track = reading.owner_track(lb, first, last, airports)
    with lb.index() as idx:
        marks = idx.retractions()
        resolutions = [line for line in idx.resolutions() if admit is None or admit(line)]
        retracted = frozenset(retractions(marks))
        identities = resolve.identities_from([*marks, *resolutions])
        owner = present.owner_of(
            str(lb.meta.get("owner_id") or ""),
            [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
            policy.owner_aliases(lb.root),
            identities,
        )
        known = _people_of(identities, resolve.standing([*marks, *resolutions]), owner)
        gather = _Gather(known, identities, owner, days, first, last)
        evidence: list[Line] = []
        for channel in CHANNELS:
            kind = KIND_OF[channel]
            evidence.extend(gather.stream(channel, _standing(idx, kind, first, spill, retracted, admit)))
        evidence.extend(gather.stream("notes", _standing(idx, "note", first, spill, retracted, admit)))
    gather.finish_messages()
    _together(known, evidence, track, identities, owner, tz, first, last, airports)
    heard = sorted(
        (p for p in known.values() if p.heard),
        key=lambda p: (-len(p.days), _desc(p.last_contact), p.name.casefold()),
    )
    return Report(
        first,
        last,
        tz,
        heard,
        known,
        owner,
        identities,
        days,
        unnamed=len(gather.unnamed),
        not_yet_named=gather.not_yet_named,
    )


def directory(lb: Logbook) -> Report:
    """Every person the record's resolution lines name, never the owner, and nothing read of their
    evidence: what `find` needs to name one (`logbook with`), in the time two kinds take to read.
    The report's window is empty and its `people` none."""
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        marks = idx.retractions()
        resolutions = idx.resolutions()
    identities = resolve.identities_from([*marks, *resolutions])
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    known = _people_of(identities, resolve.standing([*marks, *resolutions]), owner)
    return Report("", "", days.zone, [], known, owner, identities, days)


def _desc(day: str | None) -> str:
    """A key that sorts later days first: each digit flipped."""
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in (day or "")) or "~"


def _standing(
    idx: Index,
    kind: str,
    first: str,
    last: str,
    retracted: frozenset[str],
    admit: Callable[[Line], bool] | None = None,
    after: int | None = None,
) -> Iterator[Line]:
    """The lines of `kind` in the window that stand: not retracted, not superseded by a line of
    the same kind (a calendar entry edited since is one entry), and through `admit` when given;
    with `after`, only those appended after that seq."""
    superseded = idx.superseded(kind)
    for line in idx.of_kind(kind, first, last, after_seq=after):
        id_ = str(line.get("id"))
        if id_ in retracted or id_ in superseded or (admit is not None and not admit(line)):
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
        if who.unnamed:
            continue  # a person the owner would not name is never a row (RFC 0038 §3.4)
        voice = ref[0] == attribution.SPEAKER  # a voice is evidence of a person, not one of their refs
        person = people.get(who.entity)
        line = standing.get(ref)
        tier = int(line.get("tier", 0)) if line is not None else 0
        birthday = _birthday(line)
        if person is None:
            people[who.entity] = Person(
                who.entity, who.label or who.entity, () if voice else (ref,), birthday, tier
            )
            continue
        if not voice:
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
        days: DayStart,
        first: str,
        last: str,
    ):
        self.people = people
        self.identities = identities
        self.owner = owner
        self.days = days
        self.first, self.last = first, last
        self.chats: dict[str, _Chat] = {}
        self.voices = attribution.Voices(identities, owner.entities, owner.id)
        self.unnamed: set[str] = set()  # the unnamed people who spoke in the window
        self.not_yet_named = 0  # the window's voices no line binds

    def stream(self, channel: str, lines: Iterable[Line]) -> list[Line]:
        kept: list[Line] = []
        for line in lines:
            at = stays.instant(line.get("at"))
            if at is None:
                continue
            day = self.days.day(at).isoformat()
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
            for heard in self.voices.of({"id": id_, "payload": payload}):
                if heard.state == attribution.NOT_YET_NAMED:
                    self.not_yet_named += 1
                elif heard.state == attribution.UNNAMED and heard.entity:
                    self.unnamed.add(heard.entity)
                elif heard.state == attribution.PERSON and heard.entity in self.people:
                    found.append(heard.entity)  # the far end of a call too: they spoke in it
                    channel_of = self.people[heard.entity].channel("transcripts")
                    channel_of.spoke_s = (channel_of.spoke_s or 0.0) + (heard.voice.seconds or 0.0)
            participants = payload.get("participants")
            for participant in participants if isinstance(participants, list) else []:
                if isinstance(participant, dict) and not machine.is_machine_participant(participant):
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
        if machine.is_machine(payload) or machine.with_agent(payload):
            return []  # a conversation with an agent names nobody, whichever side wrote the line
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
        participants = payload.get("participants")
        return bool(speakers.voices(payload)) or any(
            not machine.is_machine_participant(p)
            for p in (participants if isinstance(participants, list) else [])
        )
    if kind == "photo":
        extra = payload.get("extra")
        return bool(payload.get("people")) or bool(isinstance(extra, dict) and extra.get("faces"))
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
        str(line["id"]): track.day_start.day(at).isoformat()
        for line in lines
        if (at := stays.instant(line.get("at"))) is not None
    }
    tiers = {str(line["id"]): int(line.get("tier", 0)) for line in lines}
    near = present.Evidence(lines, tz)
    for stay in track.stays:
        stay_day = track.day_start.day(stay.start).isoformat()
        where = None
        for p in present.present(stay, near.near(stay), identities, track.places, owner):
            if p.status != present.CONFIRMED or p.person is None or p.person not in people:
                continue
            day = days_of.get(p.line, stay_day)
            if not first <= day <= last:
                continue
            if where is None:
                where = _where(stay, track.places, airports, track.assets)
            person = people[p.person]
            shared = person.shared.setdefault((day, stay.id), SharedDay(day, stay.id, where))
            shared.add(p, tiers.get(p.line, 0))
            person.tier = max(person.tier, tiers.get(p.line, 0))
            person.contact(day, MEETING, p.line)
    shared_at: dict[tuple[str, str], list[SharedDay]] = {}  # (day, stay id) → everyone's day there
    for person in people.values():
        for key, shared in person.shared.items():
            shared_at.setdefault(key, []).append(shared)
    nights = stays.Nights(track.stays, tz, track.settings, track.places)
    for day in day_range(first, last):
        night = nights.of(day)
        if night.stay is None:
            continue
        # a night aboard is at the stay aboard, one run of the owner's stays folded (`stays.fold`):
        # the person was confirmed at one of the stays inside it, and that is the night under one roof
        for stay in (night.stay, *night.stay.inside):
            for at_night in shared_at.get((day, stay.id), ()):
                at_night.night = day


def _where(
    stay: stays.Segment,
    places: list[named_places.Place],
    airports: Airports,
    assets: Mapping[str, Any] | None = None,
) -> str:
    """How a stay reads: its named place; `aboard <the asset's registered name>`; else its coordinates
    with `near <place>, x km` for a named place within `trips.NEAR_KM`, or the city of the nearest
    large airport in parentheses (the rollups' rule for an unnamed place)."""
    if stay.place:
        return stay.place
    if stay.aboard:
        asset = (assets or {}).get(stay.aboard)
        return f"aboard {getattr(asset, 'name', None) or stay.aboard}"
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
    head = f"{_plural(len(report.people), 'person', 'people')} · {report.first} {EN_DASH} {report.last}"
    if report.tier is not None:
        head += f" · tier {report.tier}"
    if report.not_yet_named:
        head += f" · {_plural(report.not_yet_named, 'voice')} not yet named · review speakers"
    if report.unnamed:
        head += f" · and {report.unnamed} unnamed"
    yield head
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
        f"{name} {c['lines']} ({_span(c['first'], c['last'])}"
        + (f", spoke {speakers.duration_text(c['spoke_s'])})" if c.get("spoke_s") else ")")
        for name, c in data["channels"].items()
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


# -- the whole record, kept between readings ---------------------------------------------------------------

MEMO_VERSION = 1
MEMO_FILE = "people-whole.json"  # beside the index, in the cache folder: never in the record
MEMO_SINCE_FILE = "people-to-end.json"  # a window from a later day to the record's last (`read_to_end`)
MARGIN_DAYS = 3  # the last days read, whose stays and nights a later point may still lengthen
LOOKBACK_DAYS = 32  # the owner's track read before those days when they are read again
LOOKBACK_MOST = 512  # a stay longer than this before them: the whole record is read again
TRACKED = ("message", "call", "mail", "event", "transcript", "photo", "note", "location", "flight")
OVERLAY = ("retraction", "resolution")  # one of these appended: everyone is someone else, read again
EVIDENCE_KINDS = ("event", "transcript", "photo", "note")  # the kinds the days together read


def read_whole(lb: Logbook, airports: Airports | None = None) -> Report | None:
    """`read` over the record's whole window (`reading.record_days`): every person, every day; None
    for a record with no days. The reading is kept beside the index (`MEMO_FILE`) and brought
    forward from where it stopped when all that was appended since is that: lines of later days,
    none of them correcting another (`supersedes`) or retracting one, no resolution, no setting
    changed (`_stamp`). Then only the appended lines are read, and the days together from
    `MARGIN_DAYS` before the last day read are read again, with the owner's track from
    `LOOKBACK_DAYS` before them (`_forward`). Anything else, and a kept reading that cannot be read,
    reads the whole record again (`_whole`). The result is `read`'s for the same window, field for
    field (`tests/test_people_memo.py`)."""
    whole = reading.record_days(lb)
    if whole is None:
        return None
    return _kept_reading(lb, whole, MEMO_FILE, airports)


def read_to_end(lb: Logbook, first: str, airports: Airports | None = None) -> Report | None:
    """`read` from `first` to the record's last day (the year so far, the People door's), kept beside
    the index as `read_whole` keeps the whole window, in a file of its own (`MEMO_SINCE_FILE`, one
    such window at a time); `read_whole` when `first` is the record's first day. None when the record
    has no days, or none from `first`."""
    whole = reading.record_days(lb)
    if whole is None or first > whole[1]:
        return None
    if first <= whole[0]:
        return read_whole(lb, airports) if first == whole[0] else read(lb, first, whole[1], airports)
    return _kept_reading(lb, (first, whole[1]), MEMO_SINCE_FILE, airports)


def _kept_reading(lb: Logbook, whole: tuple[str, str], name: str, airports: Airports | None) -> Report:
    """`read` of the window `whole`, which runs to the record's last day, kept beside the index as
    `name` and brought forward (`read_whole`)."""
    airports = airports or Airports.load()
    path = kept.path(lb, name)
    stamp = _stamp(lb, airports)
    with lb.index() as idx:
        at = (str(path), stamp, whole, *idx.indexed())
    if path is not None and (mine := _HELD.get(name)) is not None and mine[0] == at:
        return mine[1]  # read already in this process, at this head: the readers only read it
    held = kept.load(path)
    found = None if held is None else _forward(lb, held, whole, stamp, airports)
    if found is None:
        found = _whole(lb, whole, stamp, airports)
    report, memo = found
    kept.save(path, memo)  # one that cannot be written: the whole record is read next time
    if path is not None:
        _HELD[name] = (at, report)
    return report


_HELD: dict[str, tuple[tuple[Any, ...], Report]] = {}  # each kept reading's last report in this process


def _stamp(lb: Logbook, airports: Airports) -> str:
    """What a kept reading was read under besides the lines (`kept.stamp`): this version, the code,
    the settings, and the airports table."""
    return kept.stamp(lb, str(MEMO_VERSION), kept.code_digest(), airports.fingerprint())


def _context(
    lb: Logbook, idx: Index
) -> tuple[list[Line], frozenset[str], dict[Ref, Identity], present.Owner, dict[str, Person]]:
    """The overlay `read` reads first: the retractions and resolutions, who is who, the owner, and
    every person the resolutions name."""
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
    return marks, retracted, identities, owner, known


def _through(lines: Iterable[Line], seq: int) -> Iterator[Line]:
    """The lines up to `seq`: a reading names the line it read through, and reads no later one."""
    return (line for line in lines if int(line.get("seq") or 0) <= seq)


def _whole(
    lb: Logbook, whole: tuple[str, str], stamp: str, airports: Airports
) -> tuple[Report, dict[str, Any]]:
    """`read` over the whole window, and what it keeps: the channels before the owner's own direct
    messages are given out (`_Gather.finish_messages`), and the days together before the last
    `MARGIN_DAYS`."""
    first, last = whole
    days = day_start.of(lb.meta)
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    with lb.index() as idx:
        seq, head = idx.indexed()
        _marks, retracted, identities, owner, known = _context(lb, idx)
        gather = _Gather(known, identities, owner, days, first, last)
        evidence: list[Line] = []
        for channel in CHANNELS:
            lines = _standing(idx, KIND_OF[channel], first, spill, retracted)
            evidence.extend(gather.stream(channel, _through(lines, seq)))
        evidence.extend(
            gather.stream("notes", _through(_standing(idx, "note", first, spill, retracted), seq))
        )
    kept = _gathered(gather)
    gather.finish_messages()
    track = reading.owner_track(lb, first, last, airports)
    _together(known, evidence, track, identities, owner, days.zone, first, last, airports)
    cut = max(first, (date.fromisoformat(last) - timedelta(days=MARGIN_DAYS)).isoformat())
    memo = {
        "version": MEMO_VERSION,
        "stamp": stamp,
        "first": first,
        "last": last,
        "cut": cut,
        "seq": seq,
        "head": head,
        **kept,
        "before": _before(known, cut),
    }
    return _report(first, last, days, known, owner, identities, gather), memo


def _forward(
    lb: Logbook, memo: dict[str, Any], whole: tuple[str, str], stamp: str, airports: Airports
) -> tuple[Report, dict[str, Any]] | None:
    """The kept reading brought to the record as it stands, or None when it cannot be (`read_whole`)."""
    first, last = whole
    if memo.get("version") != MEMO_VERSION or memo.get("stamp") != stamp or memo.get("first") != first:
        return None
    since, cut = int(memo["seq"]), str(memo["cut"])
    days = day_start.of(lb.meta)
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    with lb.index() as idx:
        seq, head = idx.indexed()
        if seq < since:
            return None
        if since and (line := idx.by_seq(since)) is not None and str(line.get("hash")) != str(memo["head"]):
            return None  # the chain was written again under the kept reading (SPEC §3.1): every line anew
        appended = idx.appended(since)
        if any(kind in appended for kind in OVERLAY):
            return None
        for kind in TRACKED:
            earliest, _n, superseding = appended.get(kind, ("9999-12-31", 0, 0))
            if superseding or earliest < cut:
                return None  # a correction of a line read, or a line of a day already read whole
        _marks, retracted, identities, owner, _named = _context(lb, idx)
        known = _people_from(memo["people"])
        gather = _Gather(known, identities, owner, days, first, last)
        gather.chats = _chats_from(memo["chats"])
        gather.unnamed = set(memo["unnamed"])
        gather.not_yet_named = int(memo["not_yet_named"])
        for channel in CHANNELS:
            lines = _standing(idx, KIND_OF[channel], cut, spill, retracted, after=since)
            gather.stream(channel, _through(lines, seq))
        for person in known.values():  # in the order the whole reading meets them (`_whole`)
            person.channels = {name: person.channels[name] for name in CHANNELS if name in person.channels}
    kept = _gathered(gather)
    gather.finish_messages()
    for entity, before in memo["before"].items():
        if (them := known.get(entity)) is None:
            continue
        for s in before["shared"]:
            them.shared[(s["day"], s["stay"])] = _shared_from(s)
        them.tier = max(them.tier, int(before["tier"]))
        if before["real"] is not None:
            them.contact(before["real"][0], MEETING, before["real"][1])
    track = _track_back(lb, first, cut, last, airports)
    if track is None:
        return None
    with lb.index() as idx:
        evidence = [
            line
            for kind in EVIDENCE_KINDS
            for line in _through(_standing(idx, kind, track.first, spill, retracted), seq)
            if _names_someone(line)
        ]
    _together(known, evidence, track, identities, owner, days.zone, cut, last, airports)
    new_cut = max(cut, (date.fromisoformat(last) - timedelta(days=MARGIN_DAYS)).isoformat())
    memo = {
        "version": MEMO_VERSION,
        "stamp": stamp,
        "first": first,
        "last": last,
        "cut": new_cut,
        "seq": seq,
        "head": head,
        **kept,
        "before": _before(known, new_cut),
    }
    return _report(first, last, days, known, owner, identities, gather), memo


def _track_back(
    lb: Logbook, first: str, cut: str, last: str, airports: Airports
) -> reading.OwnerTrack | None:
    """The owner's track from far enough before `cut` that every stay reaching it is the stay the
    whole record's track has: one that is not the first stay of the track read (a stay begun before
    the track would be cut short). Read back `LOOKBACK_DAYS`, then twice as far, up to
    `LOOKBACK_MOST`; None past that."""
    back = LOOKBACK_DAYS
    days = day_start.of(lb.meta)
    floor = first  # the window's first day: the whole reading's track begins there
    while True:
        start = max(floor, (date.fromisoformat(cut) - timedelta(days=back)).isoformat())
        track = reading.owner_track(lb, start, last, airports)
        begins = days.span(cut)[0]
        reaching = [s for s in track.stays if s.end > begins]
        if start == floor or not reaching or reaching[0] is not track.stays[0]:
            return track
        if back >= LOOKBACK_MOST:
            return None
        back *= 2


def _report(
    first: str,
    last: str,
    days: DayStart,
    known: dict[str, Person],
    owner: present.Owner,
    identities: dict[Ref, Identity],
    gather: _Gather,
) -> Report:
    heard = sorted(
        (p for p in known.values() if p.heard),
        key=lambda p: (-len(p.days), _desc(p.last_contact), p.name.casefold()),
    )
    return Report(
        first,
        last,
        days.zone,
        heard,
        known,
        owner,
        identities,
        days,
        unnamed=len(gather.unnamed),
        not_yet_named=gather.not_yet_named,
    )


# -- what a reading keeps, as JSON ---------------------------------------------------------------------------


def _gathered(gather: _Gather) -> dict[str, Any]:
    """The counting as it stands before the owner's own direct messages are given out: every person
    with their channels, tier and last real contact so far, the direct chats, the voices."""
    return {
        "people": {
            entity: {
                "name": p.name,
                "refs": [list(r) for r in p.refs],
                "birthday": p.birthday,
                "tier": p.tier,
                "real": None if p.real is None else list(p.real),
                "channels": {
                    name: {
                        "lines": c.lines,
                        "first": c.first,
                        "last": c.last,
                        "tier": c.tier,
                        "last_line": c.last_line,
                        "ids": list(c.ids),
                        "spoke_s": c.spoke_s,
                        "last_at": c._last_at,
                    }
                    for name, c in p.channels.items()
                },
            }
            for entity, p in gather.people.items()
        },
        "chats": {
            k: {"senders": sorted(c.senders, key=lambda s: s or ""), "mine": c.mine}
            for k, c in gather.chats.items()
        },
        "unnamed": sorted(gather.unnamed),
        "not_yet_named": gather.not_yet_named,
    }


def _people_from(data: Mapping[str, Any]) -> dict[str, Person]:
    found: dict[str, Person] = {}
    for entity, p in data.items():
        person = Person(
            entity, p["name"], tuple((r[0], r[1]) for r in p["refs"]), p["birthday"], int(p["tier"])
        )
        person.real = None if p["real"] is None else (p["real"][0], p["real"][1], p["real"][2])
        for name, c in p["channels"].items():
            channel = Channel(
                c["lines"], c["first"], c["last"], c["tier"], c["last_line"], list(c["ids"]), c["spoke_s"]
            )
            channel._last_at = c["last_at"]
            person.channels[name] = channel
        found[entity] = person
    return found


def _chats_from(data: Mapping[str, Any]) -> dict[str, _Chat]:
    return {
        k: _Chat(set(c["senders"]), [(m[0], m[1], m[2], int(m[3])) for m in c["mine"]])
        for k, c in data.items()
    }


def _shared_from(s: Mapping[str, Any]) -> SharedDay:
    return SharedDay(
        s["day"],
        s["stay"],
        s["where"],
        list(s["sources"]),
        list(s["reasons"]),
        list(s["lines"]),
        int(s["tier"]),
        s["night"],
    )


def _before(known: Mapping[str, Person], cut: str) -> dict[str, Any]:
    """Each person's days together before `cut`, as they stand (in the order the reading met them),
    their highest tier, and the first of the latest of them, which the days after never undo: the
    last real contact the days together gave before the cut."""
    found: dict[str, Any] = {}
    for entity, person in known.items():
        kept = [s for s in person.shared.values() if s.day < cut]
        if not kept:
            continue
        best: tuple[str, str] | None = None
        for s in kept:
            if s.lines and (best is None or s.day > best[0]):
                best = (s.day, s.lines[0])
        found[entity] = {
            "shared": [
                {
                    "day": s.day,
                    "stay": s.stay,
                    "where": s.where,
                    "sources": s.sources,
                    "reasons": s.reasons,
                    "lines": s.lines,
                    "tier": s.tier,
                    "night": s.night,
                }
                for s in kept
            ],
            "tier": max(s.tier for s in kept),
            "real": None if best is None else list(best),
        }
    return found
