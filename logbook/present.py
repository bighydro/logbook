"""Who was with the owner at a stay: the "with" module.

For one stay (`stays.Segment`) and the lines of its window, `present` lists each person present
with a confidence, a status and the reason, one entry per piece of evidence; `company` merges
them per person. The sources, in the order a Day lists them:

| source       | what                                                            | status    | confidence |
|--------------|-----------------------------------------------------------------|-----------|------------|
| `circle`     | a page another member of the circle shared (not built yet)      | confirmed | —          |
| `calendar`   | an attendee of a timed `event/v1` held at the stay **            | confirmed | 0.8, 0.6 * |
| `calendar`   | an attendee of an all-day `event/v1` located at the stay **     | proposed  | 0.3        |
| `transcript` | a participant of a `transcript/v1` recorded inside the stay *** | confirmed | 0.9        |
| `note`       | a `note/v1` written inside the stay that says "with <name>" *** | confirmed | 1.0        |
| `photo`      | a face the library tagged in a `photo/v1` taken inside the stay | proposed  | 0.5        |
| `photo`      | a face the library named, `extra.faces`, in such a photo ****   | proposed  | 0.5        |

* 0.8 for an attendee who accepted, 0.6 for one who has not answered or is tentative; one who
declined is not listed.

**** The names a photo library's People album gives its faces, as the `apple-photos` adapter writes
them under `extra.faces`: a proposal of presence and nothing more. A name is resolved to a person
only when it is exactly the label a resolution line carries (case and spacing aside, `_by_label`);
`Kari` alone is not `Kari Nordmann` — the loose first-name rule of a note or a transcript does not
apply, because nobody wrote the name at the stay. A name the record does not know is proposed as
written, with no person. A face a line names both by id (`people`) and by name is one entry.

** An all-day event places nobody, unless it is located at the stay (below): then its attendees
are proposed only, at `ALL_DAY`, since the entry still names no hour. A timed event is held at
the stay when its location geocodes
within `EVENT_INSIDE_M` of the stay's centre — coordinates under `extra.location`, or a `location`
that is the name of a place in places.json — or when it has no location and overlaps the stay by
more than `EVENT_OVERLAP_S`. A located event the record cannot place does not count: a meeting
elsewhere that the owner joined from the hotel is not company. An attendee that does not resolve
and has no display name is a bare address and is dropped, and a calendar system address
(`@calendar.google.com`, `noreply`, `reservations@`, `invite@`) is never a person.

*** Only a participant the record resolves to a person: by email, phone or provider id, else by
the spoken name matching a label. A diarization label (`Speaker A`), `me`, `them`, `Unknown` or
a name no resolution knows is not company. A note's name follows the same rule: "with Ola" names
Ola Nordmann when a resolution line gives a person that label (`_by_name`); "with US", "with
XYZ", a country, an acronym or a name the record does not know names nobody.

Confirmed is what the calendar, a recording or the owner's own words say; a face is a library's
guess, by id or by name, and stays proposed until the owner says otherwise, and so are the
attendees of an all-day entry located at the stay: it names no hour. Names resolve through the
record's resolution lines
(RFC 0006, `resolve.identities_from`): an email, a phone number or a library's person id
(`provider_id`, `<library>:<id>`) to the person it names; a bare name in a transcript or a note to
the person whose label it is; a name that resolves to no person is dropped, in a note as in a
transcript. The owner is never listed as their own company: evidence
carrying one of the owner's own refs (`owner`, the addresses `logbook.json` lists under
`owner_emails`) is dropped. Nothing here reads a file or writes a line."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .chain import Line
from .places import Place, distance_m
from .resolve import Identity, Ref
from .stays import Segment, instant

CONFIRMED, PROPOSED = "confirmed", "proposed"
SOURCES = ("circle", "calendar", "transcript", "note", "photo")
EVIDENCE_KINDS = ("event", "transcript", "note", "photo")  # the kinds the sources above read
ACCEPTED, TENTATIVE, TRANSCRIPT, NOTE, PHOTO, ALL_DAY = 0.8, 0.6, 0.9, 1.0, 0.5, 0.3
EVENT_INSIDE_M = 1000.0  # a located event this close to the stay's centre is held at the stay
EVENT_OVERLAP_S = 3600  # an event with no location must overlap the stay by more than this
SYSTEM_ADDRESS = re.compile(r"(calendar\.google\.com$)|(^(no-?reply|reservations|invite)(@|[.+-]))")
NAME = r"[A-ZÆØÅÄÖÜ][\w'\-]*"
WITH = re.compile(rf"\bwith\s+({NAME}(?:\s+(?:(?:and|og|&)\s+)?{NAME})*)")  # with Ola Nordmann and Kari
AND = re.compile(r"\s+(?:and|og|&)\s+")
PERSON_TYPES = (None, "person")


@dataclass(frozen=True)
class Presence:
    """One piece of evidence that one person was present."""

    person: str | None  # the entity id the ref or name resolves to, when it does
    name: str  # the label, else the ref's value or the name as written
    ref: Ref | None  # the source-native ref, when the evidence carried one
    confidence: float
    status: str  # confirmed or proposed
    source: str  # calendar, transcript, note, photo (circle: not yet)
    reason: str
    line: str  # the evidence line's id

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "ref": None if self.ref is None else {"kind": self.ref[0], "value": self.ref[1]},
            "confidence": self.confidence,
            "status": self.status,
            "source": self.source,
            "reason": self.reason,
            "line": self.line,
        }


@dataclass(frozen=True)
class Companion:
    """One person at a stay, every piece of evidence merged: the best status and confidence,
    the sources and reasons in evidence order, the lines."""

    person: str | None
    name: str
    status: str
    confidence: float
    sources: tuple[str, ...]
    reasons: tuple[str, ...]
    lines: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "status": self.status,
            "confidence": self.confidence,
            "sources": list(self.sources),
            "reasons": list(self.reasons),
            "lines": list(self.lines),
        }


# -- the owner --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Owner:
    """The owner's own identities, so they are never their own company: the entity ids the record
    resolves them to, the refs (emails, phones, provider ids) that resolve to those, and every name
    those resolutions and `policy/owner.json` spell them by, normalised (`_normal`)."""

    entities: frozenset[str]
    refs: frozenset[Ref]
    names: frozenset[str]

    def holds(self, p: Presence) -> bool:
        return (
            (p.person is not None and p.person in self.entities)
            or (p.ref is not None and p.ref in self.refs)
            or _normal(p.name) in self.names
        )


def owner_of(
    owner_id: str,
    owner_emails: Iterable[str],
    aliases: Mapping[str, Iterable[str]],
    identities: Mapping[Ref, Identity],
) -> Owner:
    """`Owner` from `logbook.json` (`owner_id`, `owner_emails`), `policy/owner.json` (`aliases`:
    `names`, `emails`, `phones`) and the resolution lines: a ref that resolves to an owner entity
    is the owner's, an owner ref's entity is the owner, to a fixpoint; the names are the aliases'
    and every label an owner ref resolves to."""
    entities = {owner_id}
    refs: set[Ref] = {("email", _normal(e)) for e in owner_emails if e.strip()}
    refs |= {("email", _normal(e)) for e in aliases.get("emails", ()) if e.strip()}
    refs |= {("phone", p.strip()) for p in aliases.get("phones", ()) if p.strip()}
    names = {_normal(n) for n in aliases.get("names", ()) if n.strip()}
    while True:
        before = (len(entities), len(refs))
        for ref, who in identities.items():
            if who.entity and (who.entity in entities or ref in refs) and who.type in PERSON_TYPES:
                entities.add(who.entity)
                refs.add(ref)
        if before == (len(entities), len(refs)):
            break
    for ref in refs:
        resolved = identities.get(ref)
        if resolved is not None and resolved.label:
            names.add(_normal(resolved.label))
    return Owner(frozenset(entities), frozenset(refs), frozenset(names))


def _normal(name: str) -> str:
    return " ".join(name.split()).casefold()


# -- the sources ------------------------------------------------------------------------------------------


def from_circle(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    """A circle page that places someone at the stay. The circle's bundle format is not defined
    yet (ARCHITECTURE: the circle); this names nobody until it is."""
    return []


def from_calendar(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "event" or not _held_at(stay, line, places):
            continue
        payload = line.get("payload") or {}
        title = str(payload.get("title") or "an event")
        all_day = payload.get("all_day") is True
        attendees = payload.get("attendees")
        for attendee in attendees if isinstance(attendees, list) else []:
            if not isinstance(attendee, dict):
                continue
            response = attendee.get("response")
            if response == "declined":
                continue
            ref = _ref(attendee.get("ref"))
            if ref is None or _system_address(ref):
                continue
            person, label = _resolve(ref, identities)
            given = attendee.get("name")
            name = label or (str(given) if isinstance(given, str) and given.strip() else None)
            if name is None:
                continue  # a bare address nobody has named
            if all_day:
                confidence, status, reason = ALL_DAY, PROPOSED, f"attendee of {title} (all day)"
            else:
                confidence = ACCEPTED if response == "accepted" else TENTATIVE
                status, reason = CONFIRMED, f"attendee of {title}"
            found.append(Presence(person, name, ref, confidence, status, "calendar", reason, str(line["id"])))
    return found


def from_transcript(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "transcript" or not _overlaps(stay, line):
            continue
        payload = line.get("payload") or {}
        title = str(payload.get("title") or "a recording")
        participants = payload.get("participants")
        for participant in participants if isinstance(participants, list) else []:
            if not isinstance(participant, dict):
                continue
            person, label, ref = None, None, None
            for kind, field in (("email", "email"), ("phone", "phone"), ("provider_id", "provider_id")):
                value = participant.get(field)
                if isinstance(value, str) and value:
                    ref = (kind, value)
                    person, label = _resolve(ref, identities)
                    if person:
                        break
            spoken = participant.get("name")
            spoken = spoken if isinstance(spoken, str) and spoken.strip() else None
            if person is None and spoken:
                person, label = _by_name(spoken, identities)
            if person is None or not label:
                continue  # Speaker A, me, them, Unknown, a name the record has no person for
            found.append(
                Presence(
                    person,
                    label,
                    ref,
                    TRANSCRIPT,
                    CONFIRMED,
                    "transcript",
                    f"spoke in {title}",
                    str(line["id"]),
                )
            )
    return found


def from_notes(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "note" or not _inside(stay, line):
            continue
        text = str((line.get("payload") or {}).get("text") or "")
        for match in WITH.finditer(text):
            for name in AND.split(match.group(1)):
                name = name.strip()
                if not name:
                    continue
                person, label = _by_name(name, identities)
                if person is None or not label:
                    continue  # US, XYZ, a country, an acronym, a name the record has no person for
                found.append(
                    Presence(
                        person,
                        label,
                        None,
                        NOTE,
                        CONFIRMED,
                        "note",
                        f"note says with {name}",
                        str(line["id"]),
                    )
                )
    return found


def from_photos(
    stay: Segment, lines: Iterable[Line], identities: Mapping[Ref, Identity], places: Sequence[Place] = ()
) -> list[Presence]:
    found = []
    for line in lines:
        if line.get("kind") != "photo" or not _inside(stay, line):
            continue
        payload = line.get("payload") or {}
        library = str(payload.get("library") or line.get("source") or "")
        file_name = str(payload.get("file_name") or payload.get("asset_id") or "a photo")
        people = payload.get("people")
        by_id: set[str] = set()  # the persons the line's ids resolve to, so a name adds no second entry
        for person_id in people if isinstance(people, list) else []:
            if not isinstance(person_id, str) or not person_id:
                continue
            ref: Ref = ("provider_id", f"{library}:{person_id}")
            person, label = _resolve(ref, identities)
            if person is not None:
                by_id.add(person)
            found.append(
                Presence(
                    person,
                    label or ref[1],
                    ref,
                    PHOTO,
                    PROPOSED,
                    "photo",
                    f"face in {file_name}",
                    str(line["id"]),
                )
            )
        extra = payload.get("extra")
        faces = extra.get("faces") if isinstance(extra, dict) else None
        for name in faces if isinstance(faces, list) else []:
            if not isinstance(name, str) or not name.strip():
                continue
            name = " ".join(name.split())
            person, label = _by_label(name, identities)
            if person is not None and person in by_id:
                continue
            found.append(
                Presence(
                    person,
                    label or name,
                    None,
                    PHOTO,
                    PROPOSED,
                    "photo",
                    f"face {name} in {file_name}",
                    str(line["id"]),
                )
            )
    return found


FROM = (from_circle, from_calendar, from_transcript, from_notes, from_photos)


def present(
    stay: Segment,
    lines: Sequence[Line],
    identities: Mapping[Ref, Identity],
    places: Sequence[Place] = (),
    owner: Owner | None = None,
) -> list[Presence]:
    """Everyone the evidence puts at the stay, one entry per piece of evidence, sources in the
    order of `SOURCES`, lines in the order given. `places` (places.json) geocodes a calendar
    entry's location; `owner` is left out, never their own company."""
    found: list[Presence] = []
    for source in FROM:
        found.extend(
            p for p in source(stay, lines, identities, places) if owner is None or not owner.holds(p)
        )
    return found


def company(
    stay: Segment,
    lines: Sequence[Line],
    identities: Mapping[Ref, Identity],
    places: Sequence[Place] = (),
    owner: Owner | None = None,
) -> list[Companion]:
    """`present` merged per person (by entity id, else by name): confirmed before proposed, then
    by confidence, then by first evidence."""
    merged: dict[tuple[str | None, str], list[Presence]] = {}
    for p in present(stay, lines, identities, places, owner):
        merged.setdefault((p.person, "" if p.person else p.name.casefold()), []).append(p)
    companions = []
    for group in merged.values():
        best = min(group, key=lambda p: (p.status != CONFIRMED, -p.confidence))
        companions.append(
            Companion(
                best.person,
                best.name,
                best.status,
                best.confidence,
                tuple(dict.fromkeys(p.source for p in group)),
                tuple(p.reason for p in group),
                tuple(dict.fromkeys(p.line for p in group)),
            )
        )
    order = {CONFIRMED: 0, PROPOSED: 1}
    companions.sort(key=lambda c: (order[c.status], -c.confidence))
    return companions


# -- the evidence of a window, by day ---------------------------------------------------------------------


class Evidence:
    """The evidence lines of a window (`EVIDENCE_KINDS`) bucketed by every local day their span
    touches, so the company of a stay is read from the lines of the stay's days — one lookup per
    stay — and never by a pass over the whole window per stay or per place. The sources above still
    apply their exact rules to what `near` returns; a line on the stay's day that does not overlap
    it places nobody, as before."""

    def __init__(self, lines: Iterable[Line], tz: ZoneInfo):
        self.tz = tz
        self._by_day: dict[date, list[Line]] = {}
        for line in lines:
            if line.get("kind") not in EVIDENCE_KINDS:
                continue
            at = instant(line.get("at"))
            if at is None:
                continue
            end = instant(line.get("end")) or at
            first, last = at.astimezone(tz).date(), max(at, end).astimezone(tz).date()
            day = first
            while day <= last:
                self._by_day.setdefault(day, []).append(line)
                day += timedelta(days=1)

    def near(self, stay: Segment) -> list[Line]:
        """The evidence lines of the days the stay touches, in chain order, each once."""
        found: dict[str, Line] = {}
        day, last = stay.start.astimezone(self.tz).date(), stay.end.astimezone(self.tz).date()
        while day <= last:
            for line in self._by_day.get(day, ()):
                found.setdefault(str(line.get("id")), line)
            day += timedelta(days=1)
        return sorted(found.values(), key=lambda line: int(line.get("seq", 0)))


# -- helpers ----------------------------------------------------------------------------------------------


def _overlaps(stay: Segment, line: Line) -> bool:
    return _overlap_s(stay, line) > 0 or _inside(stay, line)


def _overlap_s(stay: Segment, line: Line) -> float:
    """The seconds the line's span shares with the stay; zero for an instant or no overlap."""
    at = instant(line.get("at"))
    if at is None:
        return 0.0
    end = instant(line.get("end")) or at
    return max(0.0, (min(end, stay.end) - max(at, stay.start)).total_seconds())


def _held_at(stay: Segment, line: Line, places: Sequence[Place]) -> bool:
    """Whether a calendar entry was held at the stay: timed, and either located within
    `EVENT_INSIDE_M` of the stay's centre or unlocated and overlapping it by more than
    `EVENT_OVERLAP_S`."""
    payload = line.get("payload") or {}
    if not _overlaps(stay, line):
        return False
    where = _event_coordinates(payload, places)
    if payload.get("all_day") is True and where is None:
        return False  # it overlaps every stay of its day and places nobody at any one of them
    if where is None:
        return payload.get("location") in (None, "") and _overlap_s(stay, line) > EVENT_OVERLAP_S
    if stay.lat is None or stay.lon is None:
        return False
    return distance_m(stay.lat, stay.lon, where[0], where[1]) <= EVENT_INSIDE_M


def _event_coordinates(payload: Mapping[str, Any], places: Sequence[Place]) -> tuple[float, float] | None:
    """Where an event/v1 was held: `extra.location.latitude`/`longitude` as ios-calendar and ics
    write them, else the place in places.json whose name is the `location` text, case aside."""
    extra = payload.get("extra")
    detail = extra.get("location") if isinstance(extra, dict) else None
    if isinstance(detail, dict):
        lat, lon = detail.get("latitude"), detail.get("longitude")
        if isinstance(lat, int | float) and isinstance(lon, int | float):
            return float(lat), float(lon)
    location = payload.get("location")
    if isinstance(location, str) and location.strip():
        wanted = " ".join(location.split()).casefold()
        for place in places:
            if place.name.casefold() == wanted:
                return place.lat, place.lon
    return None


def _system_address(ref: Ref) -> bool:
    return ref[0] == "email" and SYSTEM_ADDRESS.search(ref[1].strip().casefold()) is not None


def _inside(stay: Segment, line: Line) -> bool:
    at = instant(line.get("at"))
    return at is not None and stay.start <= at <= stay.end


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(ref_value, str) or not ref_value:
        return None
    return kind, ref_value


def _resolve(ref: Ref, identities: Mapping[Ref, Identity]) -> tuple[str | None, str | None]:
    who = identities.get(ref)
    if who is None or who.type not in PERSON_TYPES:
        return None, None
    return who.entity, who.label


def _by_name(name: str, identities: Mapping[Ref, Identity]) -> tuple[str | None, str | None]:
    """The person whose label is `name` (case aside), else the one person whose label's first
    word is `name`'s first word; None when none or several."""
    wanted = " ".join(name.split()).casefold()
    labels = _labels(identities)
    person, label = _by_label(name, identities)
    if person is not None:
        return person, label
    first = wanted.split(" ")[0]
    loose = {entity: label for entity, label in labels.items() if label.split()[0].casefold() == first}
    if len(loose) == 1:
        return next(iter(loose.items()))
    return None, None


def _by_label(name: str, identities: Mapping[Ref, Identity]) -> tuple[str | None, str | None]:
    """The one person whose label is exactly `name`, case and spacing aside; None when none or
    several. Never a first name alone: the rule for a name nobody wrote at the stay (a face)."""
    wanted = " ".join(name.split()).casefold()
    exact = {
        entity: label
        for entity, label in _labels(identities).items()
        if " ".join(label.split()).casefold() == wanted
    }
    if len(exact) == 1:
        return next(iter(exact.items()))
    return None, None


def _labels(identities: Mapping[Ref, Identity]) -> dict[str, str]:
    """entity → the first label a resolution gives it, for every person the record resolves."""
    labels: dict[str, str] = {}
    for who in identities.values():
        if who.entity and who.label and who.type in PERSON_TYPES:
            labels.setdefault(who.entity, who.label)
    return labels


# The lookups other readers of people share (`people`, `keepers`): a ref to the person it resolves to,
# a spoken or written name to the person whose label it is, and a name to the person whose label it
# is exactly (a face's name).
resolve_ref = _resolve
by_name = _by_name
by_label = _by_label
