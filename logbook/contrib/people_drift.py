"""`logbook people drift` and the Day's anniversaries: who the owner used to see and has drifted
from, and who they were with on this day years ago. Readers (ADR 0013): derived from the record at
its head, every time, by rules alone, never a model, and never written. Only canonical people are
named: the people the record's resolution lines name (`people.read`), never an observed one.

A **real contact** with a person is, and is only:

- a **day together** (`together`): a day the with module confirms them at one of the owner's stays,
  as `people` counts it — the attendee of a timed entry held there, a speaker of a recording made
  there, a note written there that says "with <name>";
- a **meeting** (`meeting`): a timed calendar entry they attended and did not decline, wherever it
  was held (a video call too), or a recording they spoke in;
- a **call** (`call`): a call they were the other end of that was answered, either way;
- a **message** (`message`): a message in a **direct** chat, theirs or the owner's (the owner's line
  goes to the one person who wrote in the chat, else to the person the chat's id names).

Nothing else is one. A mail never is, sent or received: a newsletter is a mail, and so is the
owner's note to forty people, and the record cannot tell either from a letter. A line in a group
chat is the group's, not a contact with whoever wrote it. A missed call, a tagged face and an
all-day entry are not one either. On one day a day together is named before a meeting, a meeting
before a call, a call before a message.

**Drift** lists the canonical people with at least `--min-days` days together (default 20) in one
calendar year — their best year, or `--year` — whose last real contact is more than `--quiet-days`
(default 365) before the record's last day (today, when the record runs past it: a planned entry is
not a day that happened). Most days together in that year first, then the longest silence, then the
name. Each row carries the open promises with them both ways from `promises`: the owner's own (and
what they asked of the owner) as `you_owe`, theirs as `they_owe`. `--show` adds the days together,
each with where and the ids of its evidence: days, never a word of a message.

**Anniversaries** are the days together exactly 1, 2, 3, 5 and 10 years before a day, with the same
canonical person: a stay together, the days of a journey among them, since a trip's days are its
stays. One per person and year, the nearest years first, then by name, five at most."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from ..core import kept, machine, people, present, reading, stays
from ..core.chain import Line
from ..core.flights import Airports
from ..core.resolve import Ref
from ..core.store import Logbook, retractions
from . import promises as promise_reader

TOGETHER, MEETING, CALL, MESSAGE = "together", "meeting", "call", "message"
ORDER = {TOGETHER: 0, MEETING: 1, CALL: 2, MESSAGE: 3}  # on one day, the contact to name
KINDS = ("message", "call", "event", "transcript")  # the kinds a real contact other than a day together is in
DEFAULT_MIN_DAYS = 20
DEFAULT_QUIET_DAYS = 365
YEARS = (1, 2, 3, 5, 10)  # the anniversaries the Day names
MAX_ANNIVERSARIES = 5
WHATSAPP_JID = re.compile(r"^(\d{6,15})@s\.whatsapp\.net$")


# -- real contact --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Contact:
    """One real contact: the local day, how (`together`, `meeting`, `call`, `message`), the line."""

    day: str
    via: str
    line: str

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day, "via": self.via, "line": self.line}

    def after(self, other: Contact | None) -> bool:
        """Whether this contact is the one to name over `other`: a later day, else the stronger way."""
        return other is None or (self.day, -ORDER[self.via]) > (other.day, -ORDER[other.via])


def real_contacts(lb: Logbook, report: people.Report) -> dict[str, Contact]:
    """The last real contact of every canonical person of `report`, by entity id, over its window:
    its days together, and the standing message, call, event and transcript lines of the window,
    streamed one kind at a time through the index. Writes nothing to the record. Over a window to the
    record's last day (`people.read_whole`'s, `people.read_to_end`'s), the reading is kept between heads
    (`_kept`), each such window in a file of its own."""
    whole = reading.record_days(lb)
    if whole is not None and report.last == whole[1] and report.first >= whole[0]:
        return _kept(lb, report, KEPT_FILE if report.first == whole[0] else KEPT_SINCE_FILE)
    return _read(lb, report)


def _read(lb: Logbook, report: people.Report) -> dict[str, Contact]:
    """`real_contacts` read from the lines, every one of the window."""
    fold = _Fold(report)
    fold.together()
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        for kind in KINDS:
            superseded = idx.superseded(kind)
            for line in idx.of_kind(kind, report.first, report.last):
                fold.line(kind, line, retracted, superseded)
    return fold.finish()


class _Fold:
    """The reading of `real_contacts`, line by line: each person's contact to name so far (a later day,
    else the stronger way; the first seen of equals), the days together first (`together`), and the
    direct chats the owner wrote in, given to their one other person at the end (`finish`)."""

    def __init__(self, report: people.Report, found: dict[str, Contact] | None = None):
        self.report = report
        self.found: dict[str, Contact] = {} if found is None else found
        self.chats: dict[str, _Chat] = {}

    def saw(
        self, entity: str | None, day: str, via: str, line: str, into: dict[str, Contact] | None = None
    ) -> None:
        if entity is None or entity not in self.report.known:
            return
        found = self.found if into is None else into
        contact = Contact(day, via, line)
        if contact.after(found.get(entity)):
            found[entity] = contact

    def together(self) -> None:
        for person in self.report.people:
            for shared in person.shared.values():
                self.saw(person.entity, shared.day, TOGETHER, shared.lines[0] if shared.lines else "")

    def line(self, kind: str, line: Line, retracted: frozenset[str], superseded: Mapping[str, int]) -> None:
        report = self.report
        id_ = str(line.get("id"))
        at = stays.instant(line.get("at"))
        if id_ in retracted or id_ in superseded or at is None:
            return
        day = report.days.day(at).isoformat()
        payload = line.get("payload") or {}
        if kind == "message":
            _message(payload, day, id_, self.chats, report, self.saw)
        elif kind == "call":
            if payload.get("answered") is True:
                self.saw(_entity(_ref(payload.get("counterparty")), report), day, CALL, id_)
        elif kind == "event":
            if payload.get("all_day") is True:
                return
            attendees = payload.get("attendees")
            for attendee in attendees if isinstance(attendees, list) else []:
                if isinstance(attendee, dict) and attendee.get("response") != "declined":
                    self.saw(_entity(_ref(attendee.get("ref")), report), day, MEETING, id_)
        else:
            participants = payload.get("participants")
            for participant in participants if isinstance(participants, list) else []:
                if isinstance(participant, dict) and not machine.is_machine_participant(participant):
                    self.saw(_participant(participant, report), day, MEETING, id_)

    def finish(self) -> dict[str, Contact]:
        """The contacts, with each direct chat's last line of the owner's given to its one other person
        (or, with nobody else in it, to the person its id names); this fold is left as it was."""
        found = dict(self.found)
        for chat_id, chat in self.chats.items():
            if chat.mine is None:
                continue
            others = {e for e in chat.senders if e is not None}
            entity = next(iter(others)) if len(others) == 1 else None
            if entity is None and not chat.senders:
                entity = _entity(promise_reader.chat_ref(chat_id), self.report)
            self.saw(entity, chat.mine[0], MESSAGE, chat.mine[1], into=found)
        return found


# -- the whole record, kept between readings -----------------------------------------------------------------

KEPT_VERSION = 1
KEPT_FILE = "contacts-whole.json"  # beside the index (`kept`)
KEPT_SINCE_FILE = "contacts-to-end.json"  # a window from a later day to the record's last
OVERLAY = ("retraction", "resolution")


def _kept(lb: Logbook, report: people.Report, name: str = KEPT_FILE) -> dict[str, Contact]:
    """`real_contacts` over the whole record, kept beside the index (`kept`, `KEPT_FILE`): for each
    kind, the contact to name of each person over the month files before the current one, and the
    direct chats as they stood there; then those files are not read again, the current month and
    after are (every line, old and new), and the kept part stands where its lines stood in the
    reading, before them. The contact to name is the first of the greatest, so the greatest of a
    part, put where the part was, names the same one; the chats keep the order the reading met them.
    A resolution or retraction appended, a line correcting one of `KINDS`, or a line in a month file
    before the current one (a backfill): the whole record again. `tests/test_contacts_kept.py`."""
    at = kept.path(lb, name)
    stamp = kept.stamp(lb, str(KEPT_VERSION), kept.code_digest(__file__), report.first)
    held = kept.load(at)
    with lb.index() as idx:
        seq, head = idx.indexed()
        newest = idx.db.execute(
            f"SELECT max(file) FROM lines WHERE kind IN ({', '.join('?' * len(KINDS))})", KINDS
        ).fetchone()[0]
        cut = str(newest or "")  # the next kept part: the files before the current month's
        usable = held is not None and held.get("version") == KEPT_VERSION and held.get("stamp") == stamp
        if usable and held is not None:
            since = int(held.get("seq", -1))
            line = idx.by_seq(since) if since > 0 else None
            appended = idx.appended(since) if 0 <= since <= seq else {}
            earliest = idx.db.execute(
                f"SELECT min(file) FROM lines WHERE seq > ? AND kind IN ({', '.join('?' * len(KINDS))})",
                (since, *KINDS),
            ).fetchone()[0]
            usable = (
                0 <= since <= seq
                and (since == 0 or (line is not None and str(line.get("hash")) == str(held.get("head"))))
                and not any(kind in appended for kind in OVERLAY)
                and not any(appended.get(kind, ("", 0, 0))[2] for kind in KINDS)
                and (earliest is None or str(earliest) >= str(held.get("cut", "")))
            )
        start = str(held["cut"]) if usable and held is not None else ""
        retracted = frozenset(retractions(idx.retractions()))
        fold = _Fold(report)
        fold.together()
        parts: dict[str, dict[str, Contact]] = {}
        chats: dict[str, _Chat] = {}
        for kind in KINDS:
            superseded = idx.superseded(kind)
            part = _Fold(report, _contacts_from(held["parts"].get(kind, {})) if usable and held else {})
            if kind == "message" and usable and held is not None:
                fold.chats, part.chats = _chats_from(held["chats"]), _chats_from(held["chats"])
            for entity, contact in part.found.items():  # the kept files, where they stood
                fold.saw(entity, contact.day, contact.via, contact.line)
            if start < cut:
                for line in idx.of_kind(kind, report.first, report.last, files=(start, cut)):
                    part.line(kind, line, retracted, superseded)
                    fold.line(kind, line, retracted, superseded)
            for line in idx.of_kind(kind, report.first, report.last, files=(max(start, cut), None)):
                fold.line(kind, line, retracted, superseded)
            parts[kind] = part.found
            if kind == "message":
                chats = part.chats
    kept.save(
        at,
        {
            "version": KEPT_VERSION,
            "stamp": stamp,
            "seq": seq,
            "head": head,
            "cut": max(start, cut),
            "parts": {
                kind: {e: [c.day, c.via, c.line] for e, c in found.items()} for kind, found in parts.items()
            },
            "chats": {k: {"senders": list(c.senders), "mine": c.mine} for k, c in chats.items()},
        },
    )
    return fold.finish()


def _contacts_from(data: Mapping[str, Any]) -> dict[str, Contact]:
    return {e: Contact(c[0], c[1], c[2]) for e, c in data.items()}


def _chats_from(data: Mapping[str, Any]) -> dict[str, _Chat]:
    return {
        k: _Chat(set(c["senders"]), None if c["mine"] is None else (c["mine"][0], c["mine"][1]))
        for k, c in data.items()
    }


@dataclass
class _Chat:
    senders: set[str | None] = field(default_factory=set)
    mine: tuple[str, str] | None = None  # (day, line) of the owner's last line in it


def _message(
    payload: Mapping[str, Any],
    day: str,
    id_: str,
    chats: dict[str, _Chat],
    report: people.Report,
    saw: Callable[[str | None, str, str, str], None],
) -> None:
    """A message line: theirs in a direct chat is a contact with its sender; the owner's in a
    direct chat waits for the chat's people (`real_contacts`); a group's line is nobody's. A chat
    given as a string (the shape before RFC 0008) is a direct chat's name, as SPEC §3.2 reads it. A
    line of a conversation with an agent (`logbook.core.machine`) is nobody's."""
    if machine.is_machine(payload) or machine.with_agent(payload):
        return
    chat = payload.get("chat")
    if isinstance(chat, dict):
        if chat.get("type") != "direct":
            return
        chat_id = str(chat.get("id")) if chat.get("id") else None
    elif isinstance(chat, str):
        chat_id = None
    else:
        return
    if payload.get("from_me") is True:
        if chat_id is not None:
            held = chats.setdefault(chat_id, _Chat())
            if held.mine is None or day >= held.mine[0]:
                held.mine = (day, id_)
        return
    entity = _entity(_ref(payload.get("sender")), report)
    if chat_id is not None:
        chats.setdefault(chat_id, _Chat()).senders.add(entity)
    saw(entity, day, MESSAGE, id_)


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(ref_value, str) or not ref_value:
        return None
    return kind, ref_value


def _entity(ref: Ref | None, report: people.Report) -> str | None:
    """The canonical person a ref resolves to, never the owner; a WhatsApp JID handle the record
    has no line for is read as the number it spells."""
    if ref is None:
        return None
    if ref[0] == "handle" and ref not in report.identities and (jid := WHATSAPP_JID.match(ref[1])):
        ref = ("phone", f"+{jid.group(1)}")
    entity, _label = present.resolve_ref(ref, report.identities)
    if entity is None or entity in report.owner.entities or entity not in report.known:
        return None
    return entity


def _participant(participant: Mapping[str, Any], report: people.Report) -> str | None:
    """A transcript's participant as the people reader places one: by email, phone or provider
    id, else by the spoken name when the record labels exactly one person by it."""
    for kind, key in (("email", "email"), ("phone", "phone"), ("provider_id", "provider_id")):
        value = participant.get(key)
        if isinstance(value, str) and value:
            entity = _entity((kind, value), report)
            if entity is not None:
                return entity
    spoken = participant.get("name")
    if isinstance(spoken, str) and spoken.strip():
        entity, _label = present.by_name(spoken, report.identities)
        if entity is not None and entity in report.known and entity not in report.owner.entities:
            return entity
    return None


# -- drift ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Drifted:
    person: people.Person
    year: str  # the best year, or the one asked for
    days_in_year: int
    contact: Contact | None
    silent: int | None  # days from the last real contact to the window's end
    you_owe: int
    they_owe: int

    def to_json(self, show: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.person.entity,
            "name": self.person.name,
            "best_year": {"year": self.year, "days": self.days_in_year},
            "days": len(self.person.days),
            "last_real_contact": None if self.contact is None else self.contact.to_json(),
            "silent_days": self.silent,
            "promises": {"you_owe": self.you_owe, "they_owe": self.they_owe},
        }
        if show:
            out["days_together"] = days_together(self.person)
        return out


@dataclass(frozen=True)
class Drift:
    first: str
    until: str
    min_days: int
    quiet_days: int
    year: str | None
    people: list[Drifted]

    def to_json(self, show: bool = False) -> dict[str, Any]:
        return {
            "window": {"since": self.first, "until": self.until},
            "until": self.until,
            "min_days": self.min_days,
            "quiet_days": self.quiet_days,
            "year": self.year,
            "people": [d.to_json(show) for d in self.people],
        }


def drift(
    lb: Logbook,
    min_days: int = DEFAULT_MIN_DAYS,
    quiet_days: int = DEFAULT_QUIET_DAYS,
    year: str | None = None,
    airports: Airports | None = None,
) -> Drift | None:
    """The drift over the whole record; None for a record with no lines. Raises `ValueError` for
    a floor under one day, a negative silence or a year that is not one, and what the people
    reader raises; writes nothing."""
    if min_days < 1:
        raise ValueError("--min-days is a number of days, at least 1")
    if quiet_days < 0:
        raise ValueError("--quiet-days is a number of days, at least 0")
    if year is not None and not re.fullmatch(r"\d{4}", year):
        raise ValueError(f"not a year (YYYY): {year!r}")
    whole = reading.record_days(lb)
    if whole is None:
        return None
    report = people.read(lb, *whole, airports)
    until = until_of(report, whole[1])
    contacts = real_contacts(lb, report)
    found = []
    for person in report.people:
        v = verdict(person, contacts.get(person.entity), until, min_days, quiet_days, year)
        if v.drifted:
            assert v.year is not None
            found.append((person, v.year, v.days_in_year, v.contact, v.silent))
    owed = open_promises(lb, [person for person, *_ in found]) if found else {}
    rows = [
        Drifted(person, best, n, contact, silent, *owed.get(person.entity, (0, 0)))
        for person, best, n, contact, silent in found
    ]
    rows.sort(
        key=lambda d: (
            -d.days_in_year,
            -(d.silent if d.silent is not None else 10**9),
            d.person.name.casefold(),
        )
    )
    return Drift(whole[0], until, min_days, quiet_days, year, rows)


@dataclass(frozen=True)
class Verdict:
    """Whether one person has drifted, and why not when not: the year counted (their best, or the
    one asked for; None when they have no day together at all), its days together, the last real
    contact and the days of silence since it, to `until`."""

    drifted: bool
    year: str | None
    days_in_year: int
    contact: Contact | None
    silent: int | None
    min_days: int
    quiet_days: int

    def text(self) -> str:
        """`drifting: 25 days together in 2022, no real contact in 1,035 days`, or why not."""
        if self.year is None:
            return "not drifting: no day together"
        together = f"{_plural(self.days_in_year, 'day')} together in {self.year}"
        silence = (
            "no real contact"
            if self.contact is None
            else f"last real contact {self.contact.day}, {self.silent:,} days ago"
        )
        if self.drifted:
            return f"drifting: {together}, {silence}"
        if self.days_in_year < self.min_days:
            return f"not drifting: {together}, under {self.min_days}"
        return f"not drifting: {together}; {silence}, within {self.quiet_days:,}"

    def to_json(self) -> dict[str, Any]:
        return {
            "drifted": self.drifted,
            "year": self.year,
            "days_in_year": self.days_in_year,
            "last_real_contact": None if self.contact is None else self.contact.to_json(),
            "silent_days": self.silent,
            "min_days": self.min_days,
            "quiet_days": self.quiet_days,
        }


def until_of(report: people.Report, last: str) -> str:
    """The day a silence is counted to: the record's last day, today when the record runs past it
    (a planned entry is not a day that happened)."""
    return min(last, report.days.today(datetime.now(UTC)).isoformat())


def verdict(
    person: people.Person,
    contact: Contact | None,
    until: str,
    min_days: int = DEFAULT_MIN_DAYS,
    quiet_days: int = DEFAULT_QUIET_DAYS,
    year: str | None = None,
) -> Verdict:
    """The drift rule for one person: at least `min_days` days together in their best year (or
    `year`), and no real contact in more than `quiet_days` days before `until`; never one with no
    day together, unless `year` is asked for."""
    by_year = Counter(day[:4] for day in person.days)
    if year is None:
        if not by_year:
            return Verdict(False, None, 0, contact, None, min_days, quiet_days)
        best, n = max(by_year.items(), key=lambda item: (item[1], item[0]))
    else:
        best, n = year, by_year.get(year, 0)
    silent = None if contact is None else (date.fromisoformat(until) - date.fromisoformat(contact.day)).days
    drifted = n >= min_days and (silent is None or silent > quiet_days)
    return Verdict(drifted, best, n, contact, silent, min_days, quiet_days)


def open_promises(lb: Logbook, who: Iterable[people.Person]) -> dict[str, tuple[int, int]]:
    """(you owe, they owe) per person, from the open proposals of `promises` (`promises_with`)."""
    out: dict[str, tuple[int, int]] = {}
    for entity, found in promises_with(lb, who).items():
        mine = sum(1 for _p, owed_by_owner in found if owed_by_owner)
        out[entity] = (mine, len(found) - mine)
    return out


def promises_with(
    lb: Logbook,
    who: Iterable[people.Person],
    *,
    admit: Callable[[Line], bool] | None = None,
    since: str | None = None,
    until: str | None = None,
    proposals: Iterable[promise_reader.Proposal] | None = None,
) -> dict[str, list[tuple[promise_reader.Proposal, bool]]]:
    """The open proposals of `promises` with each person, in day order, each with whether the
    owner owes it: the owner's own and what was asked of the owner are owed by the owner; theirs
    are owed to the owner. A proposal is theirs when its speaker resolves to them, else when its
    counterpart is their name, a name only one of them carries. Read one of two ways, each named:
    `proposals`, the ones a caller found open already (the week's dream reads them as its Sunday
    stood), read as given; else every proposal of `promises` open today, `admit`, `since` and
    `until` being `promises.extract`'s: a gate on the lines it reads and the local days it reads
    them on (`export notion`). Proposals with a gate or a window are a mistake: `ValueError`."""
    if proposals is not None and (admit is not None or since is not None or until is not None):
        raise ValueError("promises_with: proposals found already take no admit, since or until")
    wanted = list(who)
    by_entity = {p.entity for p in wanted}
    names = Counter(p.name.casefold() for p in wanted)
    by_name = {p.name.casefold(): p.entity for p in wanted if names[p.name.casefold()] == 1}
    out: dict[str, list[tuple[promise_reader.Proposal, bool]]] = {}
    found = (
        promise_reader.extract(lb, since, until=until, admit=admit).proposals
        if proposals is None
        else proposals
    )
    for proposal in found:
        if (proposals is None and proposal.status != "open") or not proposal.shows or proposal.role is None:
            continue
        entity = None
        if proposal.speaker is not None and proposal.speaker.person in by_entity:
            entity = proposal.speaker.person
        elif proposal.counterpart is not None:
            entity = by_name.get(proposal.counterpart.casefold())
        if entity is None:
            continue
        owed_by_owner = proposal.role in (promise_reader.PROMISE, promise_reader.ASKED)
        out.setdefault(entity, []).append((proposal, owed_by_owner))
    return out


def days_together(person: people.Person) -> list[dict[str, Any]]:
    """The days together, oldest first, each with where and the ids of the lines that put the
    person there."""
    by_day: dict[str, dict[str, Any]] = {}
    for shared in sorted(person.shared.values(), key=lambda s: (s.day, s.stay)):
        day = by_day.setdefault(shared.day, {"day": shared.day, "where": shared.where, "lines": []})
        day["lines"] += [id_ for id_ in shared.lines if id_ not in day["lines"]]
    return list(by_day.values())


def drift_rows(found: Drift, show: bool = False) -> Iterator[str]:
    floor = (
        f"{found.min_days}+ days together in {found.year}"
        if found.year
        else (f"{found.min_days}+ days together in a year")
    )
    count = _plural(len(found.people), "person", "people")
    yield f"drift · {count} · {floor} · no real contact in over {found.quiet_days} days · to {found.until}"
    width = max((len(d.person.name) for d in found.people), default=0)
    for d in found.people:
        parts = [f"{d.year}: {_plural(d.days_in_year, 'day')}"]
        if d.contact is None:
            parts.append("no real contact")
        else:
            parts.append(f"last real contact {d.contact.day} ({d.contact.via}, {d.silent} days ago)")
        if d.you_owe or d.they_owe:
            parts.append(f"promises open: you owe {d.you_owe}, they owe {d.they_owe}")
        yield f"  {d.person.name:<{width}}  {' · '.join(parts)}"
        if show:
            by_year: dict[str, list[str]] = {}
            for day in days_together(d.person):
                by_year.setdefault(day["day"][:4], []).append(day["day"])
            for y, listed in sorted(by_year.items()):
                yield f"      {y}  {_plural(len(listed), 'day')}: {', '.join(listed)}"
            if d.contact is not None:
                yield f"      last real contact line {d.contact.line}"


# -- anniversaries -------------------------------------------------------------------------------------------


def anniversaries(lb: Logbook, day: str, airports: Airports | None = None) -> list[dict[str, Any]]:
    """The days together exactly `YEARS` before `day`, one entry per person and year — `years`,
    `day`, `id`, `name`, `where` and the evidence `lines` — the nearest years first, then by name,
    `MAX_ANNIVERSARIES` at most. A year whose date the record has no day on is skipped, and so is
    29 February in a year that has none. Writes nothing."""
    whole = reading.record_days(lb)
    if whole is None:
        return []
    airports = airports or Airports.load()
    found: list[dict[str, Any]] = []
    for years in YEARS:
        then = _years_before(day, years)
        if then is None or not whole[0] <= then <= whole[1]:
            continue
        report = people.read(lb, then, then, airports)
        for person in sorted(report.people, key=lambda p: p.name.casefold()):
            shared = sorted((s for s in person.shared.values() if s.day == then), key=lambda s: s.stay)
            if not shared:
                continue
            lines = list(dict.fromkeys(id_ for s in shared for id_ in s.lines))
            found.append(
                {
                    "years": years,
                    "day": then,
                    "id": person.entity,
                    "name": person.name,
                    "where": shared[0].where,
                    "lines": lines,
                }
            )
            if len(found) == MAX_ANNIVERSARIES:
                return found
    return found


def _years_before(day: str, years: int) -> str | None:
    d = date.fromisoformat(day)
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:  # 29 February, in a year without one
        return None


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
