"""The People door of the Library (RFC 0047 §4.3): everyone by closeness, each person a thread.

`/people` answers "who is in my life, and where do we stand?" The head names the door and, in the
pencil colour, how many people the record names; a legend names the rings. Then **the orbit**: the
owner at the centre and the people on four rings around them, from the inside Home, Family, Friends
and Everyone else, the closest `ORBIT` people drawn and the rest a plain list under "Everyone else",
A to Z, `LISTED` a page. Beside it (below it on a phone) **the thread** of the person asked for with
`?sel=ID`, or of the closest when nobody is: the ring, the name, the last contact in words, the first
`CARD` moments newest first, the beginning, the promises open both ways, and two links on to Life and
Places. Under them the people heard in the window, in the same order, as the People page has always
listed them: each a link to their whole thread, the last real contact, the evidence folded. `/people/ID`
is the whole thread on its own page: the person's page's rows of facts (the days together counted, the
last real contact, the drift) with their evidence, the days together as a strip over the years and
counted by year, every moment the card leaves out, the promises and the coming anniversaries as the
person's page listed them, what was said (the words only when asked, `?said=1`, as an
org's money is), the places shared, and in pencil what a model drafted about them. The review queue
of `people review` stays at the foot of `/people`, exactly as it was.

**Closeness** is the order and nothing else (RFC 0047 §4.3): the people the owner lives with first,
always, on the innermost ring (the owner's answer of 25 October 2026 to §14 question 1); then days
together in the last year (or in the year `?year=` names), then calls and messages, then how long the
record has known them (the first contact, earlier first), then the name. It is never shown: no
number, no size that encodes a count, no bar, and no number beside a person's name anywhere on the
door, in its text, a `title` or an `aria-label`. A person's own page counts their days together, as it
always has, never beside their name.

**The rings** are a rule's reading, never the owner's word: the record holds no "family" or "friend"
(no line says so, no contact card carries it), so each person's ring is read from what it does hold
and is set in pencil, the rule named on hover (`RULE`). Home: someone who spent at least `HOME_NIGHTS`
nights of the window with the owner at a place `places.json` calls home. Family:
someone who carries the owner's family name, as the record spells the owner (`policy/owner.json`'s
names, the labels of the owner's own resolution lines, an address of the owner's that reads
`given.family@`). Friends: a call, a message or a night together in the window.
Everyone else: the rest.

**What it reads**, and nothing more at request time: the people of the whole record as the person
pages already read them (`person_page.everyone`, kept beside the index and brought forward by what was
appended), a closed year's ranking when `?year=` asks for one (`person_page.ranked`, kept too), the
index's own rows (the kind, the local day, the tier) of a person's most recent lines, never the lines
themselves, and on `/people/ID` the one line its last real contact was (read once, for its words and
its row of facts). Through the page's tier gate
(`Site.tiers`): a gated page reads the people through it (`people.read(admit=...)`), names a person
only when it reads every tier up to theirs (`day_rhythm.reads_up_to`) and shows no row of a line
above it. A model's draft about a person is shown under the `relationship` entry it was written under
(`drafts.allowed`), a sentence that sets a figure beside a name held as the dream holds it. Nothing
here writes; the queue's two acts post to `/people/review` as they always did."""

from __future__ import annotations

import contextlib
import heapq
import math
import re
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode

from ..core import drafts, people, places, policy, reading
from ..core.store import retractions
from . import day_rhythm, doors, dream, people_drift, person_page
from . import promises as promise_reader

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

HOME, FAMILY, FRIENDS, EVERYONE = "home", "family", "friends", "everyone"
EMPTY_RING = {  # what puts someone on a ring nobody is on, by the rule
    "home": "Nobody on Home yet: a month of nights with you at home puts someone there.",
    "family": "Nobody on Family yet: someone who carries your family name goes there.",
    "friends": ("Nobody on Friends yet: a call, a message or a night together this year puts someone there."),
}
RINGS = (HOME, FAMILY, FRIENDS, EVERYONE)  # from the inside out
RING_WORDS = {HOME: "Home", FAMILY: "Family", FRIENDS: "Friends", EVERYONE: "Everyone else"}
RULE = (
    "rule: rings, read from the record, not from you. Home: nights with you at your home; Family:"
    " your family name; Friends: a call, a message or a night together this year;"
    " Everyone else: the rest."
)
HOME_NIGHTS = 30  # nights of the window under one roof at a home place: someone the owner lives with
YEAR_DAYS = 365  # the window of closeness without `?year=`: the last year, to the record's today
ORBIT = 30  # people drawn on the rings, the closest; the rest are listed A to Z
TURNS = 24  # the turns of a ring the orbit tries, to keep its names clear of the rings inside it
NAME_BELOW = 40  # a first name's baseline under its circle, in the orbit's units
NAME_HALF = 26  # half a first name's width, about, in the orbit's units
LISTED = 60  # names a page of the list under "Everyone else"
CARD = 5  # moments the card on `/people` shows before it links to the whole thread
RECENT = 24  # past moments the whole thread shows
COMING = 3  # what is coming up with them, at most
ROWS_READ = 400  # of each channel, the most recent lines whose index rows the thread reads
LATEST_WRITTEN = 4  # how many more of a channel's last-written lines are read than are kept
SAID = 6  # messages and recordings `?said=1` reads, the latest
SPAN_GAP = 2  # days apart that still run on as one span: messages back and forth
AWAY_GAP = 7  # and days together at one place away from home: a stay away, its visits a few days apart
ANNIVERSARY_DAYS = 30
# the review queue's observed people come from lines of any tier: shown on a page that reads them all
REVIEW_TIER = 3
DOT = " · "
EN_DASH = "\u2013"
RSQUO = "\u2019"
REF_WORDS = {"email": "Email", "phone": "Phone", "handle": "Handle"}  # a library's ids are left out
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")
PROMISE_RULE = (  # a promise is read out of the record's words by a rule, never confirmed by the owner here
    "rule: promises, read from your messages and notes; not confirmed. Sign the day to keep or drop it."
)
EMPTY = "Nobody yet. People appear here once a message, a call or a photo names them."
NOTHING_YET = "Nothing with them yet but their name: a day together, a call or a message starts the thread."
MET = "The day you met. Add it, and the thread begins there."
# a moment's dot: today's open item, a moment in the past, what is coming up
SIGNAL, INK, HOLLOW = "signal", "ink", "hollow"
COORDINATES = re.compile(r"^-?\d+\.\d+,-?\d+\.\d+")  # an unnamed stay, as the people reader names it
CHANNEL_KINDS = {"calls": "call", "calendar": "event", "transcripts": "transcript", "faces": "photo"}
SAID_KINDS = ("message", "transcript")
RUNS = {  # a run of one kind of moment, in words, never a count
    "call": "Calls between you.",
    "photo": "Photos of them.",
    "event": "In the calendar together, more than once.",
    "transcript": "You both spoke in recordings.",
}


class Gone(people.PersonError):
    """No person of the record at this address, through this page's gate."""


# -- what the door reads --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Row:
    """A line as the index holds it, never read from the files: its id, instant, local day, kind,
    source and tier."""

    id: str
    at: str
    day: str
    kind: str
    source: str
    tier: int


@dataclass(frozen=True)
class Near:
    """One person as the door places them: their ring, why (the rule's words), and the key that
    orders them (closeness, never shown)."""

    person: people.Person
    ring: str
    why: str
    key: tuple[Any, ...]
    contact: people_drift.Contact | None = None  # the last real contact in the window, through the gate


@dataclass(frozen=True)
class Circle:
    """Everyone the door shows, closest first, through the page's gate, and what it was read under:
    the window of closeness, the year asked for (None: the last year), the years the record holds,
    the record's today, and the reading of the whole record behind it."""

    near: list[Near]
    since: str
    until: str
    year: str | None
    years: list[str]
    today: str
    everyone: person_page.Everyone


@dataclass(frozen=True)
class Moment:
    """One moment of a thread: its first and last local day (one day: both the same), its dot, one
    sentence, the address it opens and whether a rule wrote the sentence (pencil)."""

    first: str
    last: str
    dot: str
    text: str
    href: str | None = None
    pencil: str | None = None  # the rule's or model's name, on hover
    kind: str = ""  # a row's kind, so a run of one kind reads as one moment (`RUNS`)


@dataclass
class Thread:
    """One person's thread: the last contact in words, today's open item, what is coming up, the past
    moments newest first, the beginning, the promises both ways and the places shared."""

    near: Near
    last: str | None
    today: list[Moment] = field(default_factory=list)
    coming: list[Moment] = field(default_factory=list)
    past: list[Moment] = field(default_factory=list)
    beginning: Moment | None = None
    you_owe: list[tuple[str, str | None]] = field(default_factory=list)  # (the words, due)
    they_owe: list[tuple[str, str | None]] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    first_day: str | None = None
    what: str | None = None  # the last real contact in the record's words, as the person's page names it
    owed: list[tuple[promise_reader.Proposal, bool]] = field(default_factory=list)  # (proposal, yours)
    together: list[dict[str, Any]] = field(default_factory=list)  # the days together, through the gate


def _gate(tiers: Sequence[int] | None) -> set[int] | None:
    return None if tiers is None else {int(t) for t in tiers}


def _reads(tier: object, tiers: Sequence[int] | None) -> bool:
    """Whether the gate `tiers` reads a line of `tier` (every tier when None)."""
    return tiers is None or int(str(tier)) in {int(t) for t in tiers}


def everyone(site: Site) -> person_page.Everyone | None:
    """The people of the whole record as the person pages read them, kept for the record as it stands
    (`Site.shared`, the same key the person pages used); through the page's gate when it has one: the
    people read through it, the contacts and the promises of the lines it reads alone."""
    if site.tiers is None:
        return site.shared(("everyone",), lambda: person_page.everyone(site.lb, site.airports))
    tiers = tuple(int(t) for t in site.tiers)
    return site.shared(("everyone", tiers), lambda: _gated(site, tiers))


def _gated(site: Site, tiers: tuple[int, ...]) -> person_page.Everyone | None:
    lb, gate = site.lb, set(tiers)
    whole = reading.record_days(lb)
    if whole is None:
        return None

    def admit(line: Mapping[str, Any]) -> bool:
        return int(line.get("tier") or 0) in gate

    report = people.read(lb, whole[0], whole[1], site.airports, admit=admit)
    contacts = people_drift.real_contacts(lb, report)
    with lb.index() as idx:
        allowed = {r.id for r in _rows(idx, [c.line for c in contacts.values()], tiers)}
    contacts = {entity: c for entity, c in contacts.items() if c.line in allowed}
    found = promise_reader.extract(lb, admit=admit).proposals
    return person_page.Everyone(whole, report, contacts, [p for p in found if p.status == "open"])


def circle(site: Site, year: str | None) -> Circle | None:
    """Everyone the door shows, closest first (see the module); None for a record with no days.
    `ValueError` for a year that is not one."""
    if year is not None and not (len(year) == 4 and year.isdigit()):
        raise ValueError(f"not a year (YYYY): {year!r}")
    found = everyone(site)
    if found is None:
        return None
    today = person_page.today_of(site.lb, site.now())
    first, last = found.window
    years = [str(y) for y in range(int(first[:4]), int(last[:4]) + 1)]
    if site.tiers is not None:  # a gated page names only the years its own people were heard in
        spans = [(p.first_contact, p.last_contact) for p in found.report.people if p.first_contact]
        years = sorted({str(y) for a, b in spans if b for y in range(int(a[:4]), int(b[:4]) + 1)})
    if year is None:
        until = min(today, last)
        since = (date.fromisoformat(until) - timedelta(days=YEAR_DAYS - 1)).isoformat()
    else:
        since, until = f"{year}-01-01", f"{year}-12-31"
    report, gate = found.report, site.tiers
    talk: dict[str, int] = {}
    contact_in: dict[str, people_drift.Contact] = {}
    if year is None:
        heard = [p for p in report.people if p.heard]
        for p in heard:
            talk[p.entity] = sum(p.channels[c].lines for c in ("messages", "calls") if c in p.channels)
            c = found.contacts.get(p.entity)
            if c is not None and since <= c.day <= until:
                contact_in[p.entity] = c
    elif gate is None:
        ranked = site.shared(("ranked", year), lambda: person_page.ranked(site.lb, year, site.now()))
        heard = [report.known[r["id"]] for r in ranked["people"] if r["id"] in report.known]
        for r in ranked["people"]:
            talk[r["id"]] = sum(int(r["channels"].get(c, {}).get("lines", 0)) for c in ("messages", "calls"))
            c = r["last_real_contact"]
            if c is not None:
                contact_in[r["id"]] = people_drift.Contact(str(c["day"]), str(c["via"]), str(c["line"]))
    else:  # through a gate a year's people are those the gated reading heard in it, by their spans
        heard = [p for p in report.people if _heard_in(p, since, until)]
        for p in heard:
            talk[p.entity] = sum(p.channels[c].lines for c in ("messages", "calls") if c in p.channels)
            c = found.contacts.get(p.entity)
            if c is not None and since <= c.day <= until:
                contact_in[p.entity] = c
    homes = {p.name for p in places.home_places(_places(site))}
    family = owner_families(site.lb, report)
    near = []
    for p in heard:
        if not day_rhythm.reads_up_to(p.tier, gate):
            continue
        days = sum(1 for d in p.days if since <= d <= until)
        ring, why = ring_of(p, since, until, homes, family, contact_in.get(p.entity))
        # the people you live with first, then closeness (the owner's answer of 25 Oct 2026, RFC 0047 §15)
        home = 0 if ring == HOME else 1
        key = (home, -days, -talk.get(p.entity, 0), p.first_contact or "~", p.name.casefold(), p.entity)
        near.append(Near(p, ring, why, key, contact_in.get(p.entity)))
    near.sort(key=lambda n: n.key)
    return Circle(near, since, until, year, years, today, found)


def _heard_in(p: people.Person, since: str, until: str) -> bool:
    if any(since <= d <= until for d in p.days):
        return True
    return any(c.first and c.last and c.first <= until and c.last >= since for c in p.channels.values())


def _places(site: Site) -> list[places.Place]:
    try:
        return places.read(site.lb.root)
    except places.PlaceError:
        return []  # the Places page says what is wrong with the file; the door draws nobody at home


def owner_families(lb: Any, report: people.Report) -> set[str]:
    """The owner's family names as the record spells the owner, folded: the last word of each name
    `policy/owner.json` gives, of each label the owner's own resolution lines carry, and of an address
    of the owner's that reads `given.family@`."""
    names = set(report.owner.names)
    for who in report.identities.values():
        if who.entity and who.entity in report.owner.entities and who.label:
            names.add(who.label)
    with contextlib.suppress(policy.PolicyError):  # the file's errors are `doctor`'s to say
        names |= set(policy.owner_aliases(lb.root).get("names", []))
    for address in lb.meta.get("owner_emails") or []:
        local = str(address).partition("@")[0]
        given, dot, family = local.rpartition(".")
        if dot and given and family.isalpha():
            names.add(f"{given} {family}")
    return {f for n in names if (f := _family(n)) is not None}


def _family(name: str) -> str | None:
    words = name.split()
    if len(words) < 2 or len(words[-1]) < 2 or not words[-1].replace("-", "").isalpha():
        return None
    return words[-1].casefold()


def ring_of(
    p: people.Person,
    since: str,
    until: str,
    homes: set[str],
    family: set[str],
    contact: people_drift.Contact | None,
) -> tuple[str, str]:
    """The ring the rule reads for `p` over the window (see the module), and why, in words with no
    number in them."""
    nights = [s for s in p.shared.values() if s.night is not None and since <= s.day <= until]
    if sum(1 for s in nights if s.where in homes) >= HOME_NIGHTS:
        return HOME, "Home: many nights with you at home"
    if _family(p.name) in family:
        return FAMILY, "Family: they carry your family name"
    if contact is not None and contact.via in (people_drift.CALL, people_drift.MESSAGE):
        return FRIENDS, f"Friends: {day_rhythm.VIA[contact.via]} this year"
    for name, said in (("calls", "a call"), ("messages", "a message")):
        channel = p.channels.get(name)
        if (
            channel is not None
            and channel.first is not None
            and channel.last is not None
            and (channel.first <= until and channel.last >= since)
        ):
            return FRIENDS, f"Friends: {said} this year"
    if nights:
        return FRIENDS, "Friends: a night together this year"
    return EVERYONE, "Everyone else: nothing more the rule reads"


# -- one person's thread ----------------------------------------------------------------------------------


def _rows(idx: Any, ids: Iterable[str], tiers: Sequence[int] | None) -> list[Row]:
    """The index's rows of `ids` that stand (not retracted) and pass the gate, oldest first; no line is
    read from the files."""
    wanted = list(dict.fromkeys(i for i in ids if i))
    gate = _gate(tiers)
    out: list[Row] = []
    for n in range(0, len(wanted), 500):
        chunk = wanted[n : n + 500]
        marks = ",".join("?" * len(chunk))
        for i, at, day, kind, source, tier in idx.db.execute(
            f"SELECT id, at, day_local, kind, source, tier FROM lines WHERE id IN ({marks})", chunk
        ):
            if gate is None or int(tier) in gate:
                out.append(Row(str(i), str(at), str(day), str(kind), str(source), int(tier)))
    out.sort(key=lambda r: (r.at, r.id))
    return out


def _latest(idx: Any, p: people.Person, channel: str, want: int, tiers: Sequence[int] | None) -> list[Row]:
    """The index's rows of the latest `want` lines of one of `p`'s channels, through the gate, oldest
    first. A channel's ids are in the order the people reader met them, which is not time's: a
    person's own messages first, then the owner's in their direct chat, as one block; so its tail is
    the owner's words alone. A line's id is a uuid7, in the order the lines were written: the
    `LATEST_WRITTEN` times `want` written last, of either side, are read from the index (never a line)
    and the latest by their instant kept."""
    found = p.channels.get(channel)
    if found is None or not found.ids:
        return []
    written = heapq.nlargest(max(want * LATEST_WRITTEN, want), set(found.ids))
    return _rows(idx, written, tiers)[-want:]


def find(found: Circle, entity: str) -> Near:
    for n in found.near:
        if n.person.entity == entity:
            return n
    raise Gone(f"no person {entity!r} in the record this page reads")


def near_of(site: Site, found: Circle, entity: str) -> Near:
    """The person `entity` names, placed as the door places them: on the door when the window heard
    them, else on the ring the rule reads over the whole record (a person of another year). `entity` is
    their id, or anything `people.find` reads as one person (a label, a unique first or last name, an
    address), as `/people/NAME` always took. `Gone` (a `people.PersonError`, as `find`'s own) for
    nobody the gated record names."""
    report = found.everyone.report
    known = report.known.get(entity) or people.find(entity, report)
    entity = known.entity
    try:
        return find(found, entity)
    except Gone:
        pass
    p = report.known.get(entity)
    if p is None or not p.heard or not day_rhythm.reads_up_to(p.tier, site.tiers):
        raise Gone(f"no person {entity!r} in the record this page reads")
    homes = {pl.name for pl in places.home_places(_places(site))}
    ring, why = ring_of(
        p,
        found.since,
        found.until,
        homes,
        owner_families(site.lb, report),
        found.everyone.contacts.get(entity),
    )
    return Near(p, ring, why, ())


def thread(site: Site, found: Circle, near: Near, recent: int, words: bool = False) -> Thread:
    """`near`'s thread through the page's gate, `recent` past moments at most; `words` reads the one
    line the last real contact was, to say what it was."""
    p, today = near.person, found.today
    out = Thread(near, None)
    with site.lb.index() as idx:
        retracted = set(retractions(idx.retractions()))
        ids = [i for name in CHANNEL_KINDS if name in p.channels for i in p.channels[name].ids[-ROWS_READ:]]
        rows = [r for r in _rows(idx, ids, site.tiers) if r.id not in retracted]
        messages = [r for r in _latest(idx, p, "messages", ROWS_READ, site.tiers) if r.id not in retracted]
    together = sorted((s for s in p.shared.values() if _shared_allowed(s, site.tiers)), key=lambda s: s.day)
    out.first_day = _first_day(together, rows, messages)
    contact = found.everyone.contacts.get(p.entity)
    out.last, out.what = _last(site, p, contact, together, today, words)
    # today's open item: an entry in the calendar with them today, a promise due, their birthday
    for r in rows:
        if r.kind == "event" and r.day == today:
            out.today.append(
                Moment(today, today, SIGNAL, "Today, in the calendar with you both.", _day(r.day))
            )
            break
    owed = people_drift.promises_with(site.lb, [p], proposals=found.everyone.proposals).get(p.entity, [])
    out.owed = list(owed)
    for proposal, mine in owed:
        quote_ = _quote(proposal.match.quote)
        owed_list = out.you_owe if mine else out.they_owe
        if all(words.casefold() != quote_.casefold() for words, _due in owed_list):  # one promise said again
            owed_list.append((quote_, proposal.due))
        if mine and proposal.due is not None and proposal.due <= today and not out.today:
            out.today.append(
                Moment(
                    today,
                    today,
                    SIGNAL,
                    f"Still open, owed by you: {quote_}",
                    _day(proposal.day),
                    PROMISE_RULE,
                )
            )
    if p.birthday is not None and p.birthday[-5:] == today[-5:] and not out.today:
        out.today.append(Moment(today, today, SIGNAL, "Their birthday.", _day(today)))
    # what is coming up: the calendar with them after today, their birthday, an anniversary
    coming = [r for r in rows if r.kind == "event" and r.day > today]
    for r in coming[:COMING]:
        out.coming.append(Moment(r.day, r.day, HOLLOW, "In the calendar with you both.", _day(r.day)))
    soon = date.fromisoformat(today) + timedelta(days=ANNIVERSARY_DAYS)
    if p.birthday is not None and len(out.coming) < COMING:
        next_ = _next_birthday(p.birthday, today)
        if next_ is not None and today < next_ <= soon.isoformat():
            out.coming.append(Moment(next_, next_, HOLLOW, "Their birthday.", None))
    days_together = people_drift.days_together(_gated_person(p, together))
    out.together = days_together
    for a in person_page.anniversaries(days_together, today, ANNIVERSARY_DAYS):
        if len(out.coming) >= COMING or a["on"] == today:
            continue
        years = day_rhythm.WORDS[a["years"]] if a["years"] < len(day_rhythm.WORDS) else "many"
        span = "A year" if a["years"] == 1 else f"{years.capitalize()} years"
        text = f"{span} since a day together {_place(str(a['where']))}."
        out.coming.append(Moment(str(a["on"]), str(a["on"]), HOLLOW, text, _day(str(a["day"]))))
    out.coming.sort(key=lambda m: m.first, reverse=True)
    # the past: days together (a stay away as one span), then each other day once, the strongest way
    past: list[Moment] = []
    homes = {pl.name for pl in places.home_places(_places(site))}
    for first, last, where, night in _stays(together, homes):
        if first == last:
            said = "A night together" if night else "A day together"
            past.append(Moment(first, last, INK, f"{said} {_place(where)}.", _day(first)))
        else:
            past.append(Moment(first, last, INK, f"Days together {_place(where)}.", _day(first)))
    taken = {s.day for s in together}
    for r in reversed([r for r in rows if r.day <= today]):
        if r.day in taken:
            continue
        taken.add(r.day)
        past.append(Moment(r.day, r.day, INK, _row_words(r), _day(r.day), kind=r.kind))
    for first, last in _spans(sorted({r.day for r in messages if r.day <= today})):
        said = "A message between you." if first == last else "Messages back and forth."
        past.append(Moment(first, last, INK, said, _day(last)))
    past.sort(key=lambda m: (m.last, m.first), reverse=True)
    out.past = _runs(past)[:recent]
    if out.first_day is not None:
        out.beginning = Moment(
            out.first_day,
            out.first_day,
            INK,
            "The first day the record holds with you both.",
            _day(out.first_day),
        )
    out.places = [
        _place(str(pl["where"]), bare=True) for pl in person_page.places(_gated_person(p, together))
    ]
    return out


def _shared_allowed(s: people.SharedDay, tiers: Sequence[int] | None) -> bool:
    return _reads(s.tier, tiers)


def _gated_person(p: people.Person, together: Sequence[people.SharedDay]) -> people.Person:
    kept = {(s.day, s.stay): s for s in together}
    return people.Person(p.entity, p.name, p.refs, p.birthday, p.tier, p.channels, kept, p.real)


def _first_day(
    together: Sequence[people.SharedDay], rows: Sequence[Row], messages: Sequence[Row]
) -> str | None:
    """The first day the record holds with them, through the gate: the first day together, or the
    first of the rows the thread reads."""
    found = [s.day for s in together[:1]] + [r.day for r in [*rows[:1], *messages[:1]]]
    return min(found) if found else None


def _last(
    site: Site,
    p: people.Person,
    contact: people_drift.Contact | None,
    together: Sequence[people.SharedDay],
    today: str,
    words: bool,
) -> tuple[str | None, str | None]:
    """The last real contact in words and a time ago: `A day together at the Marina, twelve days ago.`;
    with `words`, what it was in the record's words (`person_page.describe`, the one line read), and
    that as the person's page has always named it, for its row of facts (`person_page._what`)."""
    if contact is None:
        return None, None
    named: str | None = None
    if contact.via == people_drift.TOGETHER:
        where = next((s.where for s in reversed(together) if s.day == contact.day), None)
        what = f"a day together {_place(where)}" if where else "a day together"
        named = f"a day together at {where}" if where else "a day together"
    elif words:
        with site.lb.index() as idx:
            line = idx.by_id(contact.line)
        allowed = line is not None and _reads(line.get("tier") or 0, site.tiers)
        what = person_page.describe(line) if line is not None and allowed else day_rhythm.VIA[contact.via]
        named = what if line is not None and allowed else contact.via
        what = re.sub(r",\s*\d[\d,]*\s*min$", "", what)  # a call's length: never a figure near a name
    else:
        what = day_rhythm.VIA[contact.via]
    return f"{what[:1].upper()}{what[1:]}, {ago(contact.day, today)}.", named


def ago(day: str, today: str) -> str:
    """How long ago `day` was, in words and never a figure: `today`, `yesterday`, `five days ago`,
    `three weeks ago`, `four months ago`, `over a year ago`, `six years ago`."""
    gap = (date.fromisoformat(today) - date.fromisoformat(day)).days
    words = day_rhythm.WORDS
    if gap <= 0:
        return "today"
    if gap == 1:
        return "yesterday"
    if gap < 7:
        return f"{words[gap]} days ago"
    if gap < 60:
        weeks = round(gap / 7)
        return "a week ago" if weeks == 1 else f"{words[weeks]} weeks ago"
    if gap < 365:
        months = max(2, round(gap / 30.4))
        return f"{words[min(months, 11)]} months ago"
    years = gap // 365
    if years == 1:
        return "over a year ago"
    return f"{words[years]} years ago" if years < len(words) else "many years ago"


def _next_birthday(birthday: str, today: str) -> str | None:
    month_day = birthday[-5:]
    year = int(today[:4])
    for y in (year, year + 1):
        try:
            found = date.fromisoformat(f"{y}-{month_day}").isoformat()
        except ValueError:
            continue
        if found > today:
            return found
    return None


def _stays(together: Sequence[people.SharedDay], homes: Collection[str]) -> list[tuple[str, str, str, bool]]:
    """Days together run into spans: days at one place away from home (`AWAY_GAP` apart at most) are
    one stay away, and at home only the next day runs on; each `(first, last, where, a night under one
    roof)`."""
    out: list[tuple[str, str, str, bool]] = []
    for s in together:
        gap = SPAN_GAP if s.where in homes else AWAY_GAP
        if out and out[-1][2] == s.where and _apart(out[-1][1], s.day) <= gap and s.day != out[-1][1]:
            first, _last_day, where, night = out[-1]
            out[-1] = (first, s.day, where, night or s.night is not None)
        elif out and out[-1][1] == s.day:
            continue  # one day at two stays: the first is the day's
        else:
            out.append((s.day, s.day, s.where, s.night is not None))
    return out


def _spans(days: Sequence[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for d in days:
        if out and _apart(out[-1][1], d) <= SPAN_GAP:
            out[-1] = (out[-1][0], d)
        else:
            out.append((d, d))
    return out


def _apart(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _runs(moments: Sequence[Moment]) -> list[Moment]:
    """Moments newest first, a run of one kind of row (calls, photos, entries, recordings) next to each
    other and `AWAY_GAP` days apart at most read as one, its span and its words in the plural."""
    out: list[Moment] = []
    for m in moments:
        before = out[-1] if out else None
        if (
            before is not None
            and m.kind in RUNS
            and m.kind == before.kind
            and _apart(m.last, before.first) <= AWAY_GAP
        ):
            out[-1] = Moment(m.first, before.last, INK, RUNS[m.kind], before.href, kind=m.kind)
        else:
            out.append(m)
    return out


def _row_words(r: Row) -> str:
    if r.kind == "event":
        return "In the calendar together."
    if r.kind == "transcript":
        return "You both spoke in a recording."
    if r.kind == "call":
        return "A call."
    if r.kind == "photo":
        return "A photo of them."
    return "In the record together."


def _place(where: str | None, bare: bool = False) -> str:
    """A stay's name in words: `at the Marina` for a named place, `in Zurich` for a place the people
    reader names by its coordinates and the nearest city, `near the Cabin` for one near a named place,
    `aboard Nordlys`; `bare` without the preposition. Never coordinates."""
    if not where:
        return "" if bare else "somewhere"
    if where.startswith("aboard "):
        return where[len("aboard ") :] if bare else where
    if COORDINATES.match(where):
        city = re.search(r"\(([^)]+)\)\s*$", where)
        near = re.search(r" near (.+?), [\d.]+ km$", where)
        if city:
            return city.group(1) if bare else f"in {city.group(1)}"
        if near:
            return near.group(1) if bare else f"near {near.group(1)}"
        return "somewhere unnamed"
    return where if bare else f"at {where}"


def _quote(text: str) -> str:
    return f"“{' '.join(str(text).split())}”"


def _day(day: str) -> str:
    return f"/day/{day}"


def person_path(entity: str) -> str:
    return "/people/" + quote(entity, safe="")


def date_words(first: str, last: str | None = None) -> str:
    """A moment's date in the mono label: `12 JUN 2026`; a span `3 to 9 JAN 2022` with an en dash in
    place of `to`, across months and years as each needs."""
    a = date.fromisoformat(first)
    if last is None or last == first:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year}"
    b = date.fromisoformat(last)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day} {EN_DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    if a.year == b.year:
        return f"{a.day} {MONTHS[a.month - 1]} {EN_DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    return f"{a.day} {MONTHS[a.month - 1]} {a.year} {EN_DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"


# -- what was said, and what a model drafted ---------------------------------------------------------------


def _first(name: str) -> str:
    words = name.split()
    return words[0] if words else name


def said(site: Site, p: people.Person) -> list[tuple[Row, str]]:
    """The latest `SAID` messages and recordings with them through the gate, newest first, each with
    its words as the record holds them: a message's text, a recording's title and summary. Reads those
    lines, and no other."""
    with site.lb.index() as idx:
        retracted = set(retractions(idx.retractions()))
        found = [
            *_latest(idx, p, "messages", SAID * 2, site.tiers),
            *_latest(idx, p, "transcripts", SAID, site.tiers),
        ]
        rows = sorted((r for r in found if r.id not in retracted), key=lambda r: (r.at, r.id))
        rows = rows[-SAID:]
        lines = idx.by_ids([r.id for r in rows])
    out = []
    for r in reversed(rows):
        payload = (lines.get(r.id) or {}).get("payload") or {}
        if r.kind == "message":
            text = payload.get("text")
            who = "You wrote" if payload.get("from_me") is True else f"{_first(p.name)} wrote"
            words = f"{who}: {_quote(text)}" if isinstance(text, str) and text.strip() else f"{who}."
        else:
            title = payload.get("title")
            title = title if isinstance(title, str) and title.strip() else "a recording"
            summary = payload.get("summary")
            words = f"You both spoke in {_quote(title)}." + (
                f" {' '.join(summary.split())}" if isinstance(summary, str) and summary.strip() else ""
            )
        out.append((r, words))
    return out


@dataclass(frozen=True)
class Drafted:
    """What a model drafted about a person (`draft/v1`, unit `person`): the model, the window, each
    segment's words (or that it was held) and the ids of its evidence."""

    model: str
    window: str
    segments: list[tuple[str, list[str], bool]]  # (words, evidence ids, held)


def drafted(site: Site, p: people.Person, names: Sequence[str]) -> Drafted | None:
    """The standing person draft about them, through the page's gate and the `relationship` entry it
    was written under (`drafts.allowed`); a segment that sets a figure beside one of `names` is held,
    as the dream holds one (`dream.HELD`). None when there is none to show."""
    with site.lb.index() as idx:
        ids = [
            str(i)
            for (i,) in idx.db.execute(
                "SELECT id FROM lines WHERE kind = ? AND subject = ?", (drafts.KIND, p.entity)
            )
        ]
        if not ids:
            return None
        retracted = set(retractions(idx.retractions()))
        lines = list(idx.by_ids(ids).values())
    found = drafts.by_unit(lines, retracted, drafts.UNIT_PERSON).get(p.entity, [])
    shown, _withheld = drafts.through(found, site.tiers, drafts.allowed(site.lb.root))
    latest = drafts.standing(shown)
    if latest is None:
        return None
    payload = latest.get("payload") or {}
    window = payload.get(drafts.WINDOW) or {}
    span = (
        date_words(str(window["from"]), str(window["to"]))
        if isinstance(window, dict) and window.get("from") and window.get("to")
        else ""
    )
    guard = beside_guard(names)
    segments = []
    for segment in payload.get("segments") or []:
        if not isinstance(segment, dict) or not isinstance(segment.get("text"), str):
            continue
        text = " ".join(segment["text"].split())
        evidence = [str(e) for e in segment.get("evidence") or [] if isinstance(e, str)]
        held = guard.search(dream.CALENDAR.sub(" ", text)) is not None
        segments.append((dream.HELD if held else text, evidence, held))
    if not segments:
        return None
    return Drafted(drafts.model_of(latest.get("source")), span, segments)


def beside_guard(names: Iterable[str]) -> re.Pattern[str]:
    """A digit, then nothing but a separator, then one of `names`; or a name, then a separator, then a
    digit: a number beside a person's name (#394's guard)."""
    alt = "|".join(re.escape(n) for n in sorted({n for n in names if n}, key=len, reverse=True)) or "(?!)"
    return re.compile(rf"(\d[\s(:×x#·,]*(?:{alt})\b)|(\b(?:{alt})\??[\s(:×x#·,]*\d)", re.IGNORECASE)


# -- the page -----------------------------------------------------------------------------------------------


STYLE = """
main.door{max-width:72rem}
.door-people{--dp-paper:var(--paper,#F4F1EA);--dp-surface:var(--surface,#FBFAF6);
--dp-line:var(--line,#E3DED3);--dp-soft:var(--line-soft,#ECE7DD);--dp-tint:var(--tint,#EDE8DE);
--dp-ink:var(--ink,#16181D);--dp-pencil:var(--pencil,#62666D);--dp-rule:var(--pencil-rule,#8C8F95);
--dp-signal:var(--signal,#C8401A);--dp-deep:var(--signal-deep,#A93413);
--dp-serif:var(--serif,'Instrument Serif',Georgia,serif);--dp-sans:var(--sans,Inter,system-ui,sans-serif);
--dp-mono:var(--mono,'JetBrains Mono',ui-monospace,monospace);
color:var(--dp-ink);font-size:15px;line-height:1.5;min-width:0}
.door-people *{box-sizing:border-box}
.door-people a{color:inherit}
.door-people h1{font:40px/1.05 var(--dp-serif);font-weight:400;margin:8px 0 6px}
.door-people h2{font:26px/1.15 var(--dp-serif);font-weight:400;margin:0;color:var(--dp-ink)}
.door-people .mono,.door-people .kicker,.door-people .date,.door-people .legend,.door-people .years,
.door-people .chip b,.door-people .label{font:12px/1.4 var(--dp-mono);font-weight:500;
text-transform:uppercase;
letter-spacing:.13em}
.door-people .lead{color:var(--dp-pencil);margin:0 0 14px;font-size:15px}
.door-people .pencil{color:var(--dp-pencil);text-decoration:underline dotted var(--dp-rule);
text-underline-offset:3px}
.door-people .legend{display:flex;flex-wrap:wrap;gap:6px 16px;list-style:none;padding:0;margin:0 0 8px;
color:var(--dp-pencil)}
.door-people .legend li{display:flex;align-items:center;gap:6px;white-space:nowrap}
.door-people .legend i{display:inline-block;flex:0 0 auto;width:14px;height:14px;border-radius:50%;
border:1.5px solid var(--dp-rule)}
.door-people .legend i.ring-everyone{border-style:dashed}
.door-people .legend i.ring-home{border-color:var(--dp-ink)}
.door-people .years{color:var(--dp-pencil);margin:0 0 18px}
.door-people .years a,.door-people .years b{display:inline-flex;align-items:center;min-height:44px;
padding:0 6px;text-decoration:none}
.door-people .years b{color:var(--dp-ink)}
.door-people .split{display:grid;grid-template-columns:minmax(0,1fr);gap:24px;align-items:start}
.door-people .orbit{background:var(--dp-surface);border:1px solid var(--dp-line);border-radius:20px;
padding:12px;min-width:0}
.door-people svg.rings{display:block;width:100%;height:auto;max-width:100%}
.door-people p.ring-empty{margin:4px 8px 8px;font-size:13px;color:var(--dp-pencil)}
.door-people svg.rings circle.ring{fill:none;stroke:var(--dp-line);stroke-width:1.5}
.door-people svg.rings circle.ring.home{stroke:var(--dp-rule)}
.door-people svg.rings circle.ring.everyone{stroke:var(--dp-rule);stroke-dasharray:6 7}
.door-people svg.rings circle.you{fill:var(--dp-ink)}
.door-people svg.rings text{font-family:var(--dp-sans);fill:var(--dp-ink)}
.door-people svg.rings text.you{fill:var(--dp-paper);font:15px var(--dp-sans);font-weight:500}
.door-people svg.rings text.initial{font:17px var(--dp-sans);font-weight:500}
.door-people svg.rings text.name{font:15px var(--dp-sans);font-weight:400}
.door-people svg.rings circle.face{fill:var(--dp-surface);stroke:var(--dp-ink);stroke-width:1.2}
.door-people svg.rings circle.hit{fill:transparent}
.door-people svg.rings a.sel circle.face{stroke-width:3.5}
.door-people svg.rings a.sel text.name{font-weight:600}
.door-people svg.rings a:focus-visible circle.face{stroke:var(--dp-signal);stroke-width:3}
.door-people .card{background:var(--dp-surface);border:1px solid var(--dp-line);border-radius:20px;
padding:20px;min-width:0}
.door-people .kicker{color:var(--dp-pencil);margin:0 0 6px}
.door-people .card h2.name{font:40px/1.05 var(--dp-serif);font-weight:400;margin:0 0 8px;
overflow-wrap:anywhere}
.door-people .last{margin:0 0 18px;color:var(--dp-ink)}
.door-people ol.moments{list-style:none;margin:0;padding:0 0 0 22px;position:relative}
.door-people ol.moments::before{content:"";position:absolute;left:5px;top:8px;bottom:8px;width:1px;
background:var(--dp-line)}
.door-people ol.moments li{position:relative;padding:0 0 18px}
.door-people ol.moments li::before{content:"";position:absolute;left:-22px;top:5px;width:11px;height:11px;
border-radius:50%;background:var(--dp-ink);box-sizing:border-box}
.door-people ol.moments li.signal::before{background:var(--dp-signal)}
.door-people ol.moments li.hollow::before{background:var(--dp-surface);border:1.5px solid var(--dp-ink)}
.door-people ol.moments li.more::before{background:none;border:0}
.door-people p.more{margin:0;color:var(--dp-pencil);font-size:13px}
.door-people p.more a{display:inline-flex;align-items:center;min-height:44px}
.door-people ol.moments li.beginning::before{background:var(--dp-paper);border:1.5px dashed var(--dp-rule)}
.door-people ol.moments li.at{background:var(--dp-tint);border-radius:10px}
.door-people .date{display:block;color:var(--dp-pencil);margin:0 0 2px}
.door-people li.signal .date{color:var(--dp-deep)}
.door-people .moment{font:22px/1.25 var(--dp-serif);font-weight:400;margin:0}
.door-people .moment a{text-decoration:none;display:inline-block;min-height:28px}
.door-people .moment a:hover{text-decoration:underline}
.door-people p.empty{color:var(--dp-pencil);margin:0 0 12px}
.door-people .chips{list-style:none;display:flex;flex-wrap:wrap;gap:8px;padding:0;margin:4px 0 18px}
.door-people .chip{border:1px solid var(--dp-line);background:var(--dp-paper);border-radius:14px;
padding:8px 12px;font-size:15px;max-width:100%;overflow-wrap:anywhere}
.door-people .chip b{font-weight:500;margin-right:4px}
.door-people .chip.owe b{color:var(--dp-deep)}
.door-people .chip .due{display:block;font:12px/1.4 var(--dp-mono);color:var(--dp-pencil);margin:4px 0 0;
text-transform:uppercase;letter-spacing:.12em}
.door-people .pills{display:flex;flex-wrap:wrap;gap:10px;margin:8px 0 0;padding:0;list-style:none}
.door-people .pill{display:inline-flex;align-items:center;min-height:46px;padding:0 20px;border-radius:23px;
border:1px solid var(--dp-ink);text-decoration:none;font-weight:500}
.door-people .pill.dark{background:var(--dp-ink);color:var(--dp-paper)}
.door-people dl.refs{display:grid;grid-template-columns:max-content minmax(0,1fr);gap:4px 16px;margin:0;
font-size:13px;color:var(--dp-pencil)}
.door-people dl.refs dt{font-weight:500}
.door-people dl.refs dd{margin:0;font-family:var(--dp-mono);overflow-wrap:anywhere}
.door-people .everyone{margin:28px 0 0}
.door-people .everyone h2{font-size:36px;margin:0 0 10px}
.door-people ul.names{list-style:none;padding:0;margin:0;display:grid;
grid-template-columns:repeat(auto-fill,minmax(10rem,1fr));gap:0 16px}
.door-people ul.names a{display:flex;align-items:center;min-height:44px;text-decoration:none;
border-bottom:1px solid var(--dp-soft);overflow-wrap:anywhere}
.door-people .pager{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0 0}
.door-people .review{margin:40px 0 0;padding:20px 0 0;border-top:1px solid var(--dp-line)}
.door-people .review h2{font:26px var(--dp-serif);font-weight:400}
.door-people .review h2 small{font:13px var(--dp-sans);color:var(--dp-pencil);margin-left:8px}
.door-people .review details{margin-left:0}
.door-people ol.shelf{list-style:none;padding:0;margin:8px 0 0}
.door-people ol.shelf>li{padding:8px 0;border-bottom:1px solid var(--dp-soft);overflow-wrap:anywhere}
.door-people ol.shelf p{margin:2px 0}
.door-people ol.shelf p.head{display:flex;flex-wrap:wrap;gap:2px 12px;align-items:baseline}
.door-people .mute{color:var(--dp-pencil)}
.door-people p.mute,.door-people .head .mute{font-size:14px}
.door-people h3{font:12px/1.4 var(--dp-mono);font-weight:500;text-transform:uppercase;letter-spacing:.13em;
color:var(--dp-pencil);margin:14px 0 0}
.door-people summary{cursor:pointer;min-height:44px;padding:10px 0;color:var(--dp-pencil)}
.door-people details.evidence>summary{font-size:14px}
.door-people ul.evidence{list-style:none;padding:0;margin:2px 0 0 12px;color:var(--dp-pencil);font-size:14px}
.door-people span.id{font-family:var(--dp-mono);font-size:14px;color:var(--dp-pencil)}
.door-people .shelf-of{margin:32px 0 0;padding:20px 0 0;border-top:1px solid var(--dp-line)}
.door-people ol.facts{margin:14px 0}
.door-people .strip{list-style:none;padding:0;margin:0 0 18px}
.door-people .strip li{display:flex;gap:12px;align-items:center;margin:0 0 6px;min-width:0}
.door-people .strip .label{flex:0 0 3.2rem;color:var(--dp-pencil)}
.door-people .strip span.marks{display:flex;flex-wrap:wrap;gap:6px;min-width:0}
.door-people .strip .mark{display:block;width:6px;height:14px;border-radius:1px;background:var(--dp-pencil)}
.door-people section.part{margin:28px 0 0}
.door-people section.part>h2{font-size:36px;margin:0 0 12px}
.door-people ul.said{list-style:none;padding:0;margin:0}
.door-people ul.said li{padding:10px 0;border-bottom:1px solid var(--dp-soft)}
.door-people ul.said a{text-decoration:none}
.door-people ul.said a:hover,.door-people ul.said a:focus-visible{text-decoration:underline}
.door-people ul.said p{margin:2px 0 0;font:20px/1.3 var(--dp-serif);font-weight:400;overflow-wrap:anywhere}
.door-people .draft p{font:20px/1.35 var(--dp-serif);font-weight:400;color:var(--dp-pencil);margin:0 0 6px}
.door-people .draft .evidence{font:12px var(--dp-mono);font-weight:400;color:var(--dp-pencil);margin:0 0 12px}
.door-people .draft .evidence a{display:inline-flex;min-height:28px;align-items:center;margin-right:6px}
.door-people .back{display:inline-flex;align-items:center;min-height:44px;text-decoration:none}
.door-people .sides{display:grid;grid-template-columns:minmax(0,1fr);gap:0}
.door-people .sides>div{min-width:0}
@media (max-width:40rem){
.door-people svg.rings text.name{font-size:24px}
.door-people svg.rings text.initial{font-size:21px}
.door-people svg.rings text.you{font-size:19px}
.door-people .chip b{display:block;margin:0 0 2px}
.door-people .chip .sep{display:none}
.door-people .mono,.door-people .kicker,.door-people .date,.door-people .legend,.door-people .years,
.door-people .chip b,.door-people .label,.door-people .chip .due,.door-people p.ring-empty,
.door-people dl.refs,.door-people p.more,.door-people .fact,.door-people .lead{font-size:14px}
.door-people .kicker,.door-people .date,.door-people .legend,.door-people .years,.door-people .label{
letter-spacing:.08em}
}
@media (min-width:64rem){
.door-people h1{font-size:72px}
.door-people .split{grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:32px}
.door-people .card{padding:32px}
.door-people .orbit{position:sticky;top:24px}
.door-people .card h2.name{font-size:56px}
.door-people .moment{font-size:24px}
.door-people.one h1{font-size:72px}
.door-people .sides{grid-template-columns:minmax(0,1.2fr) minmax(0,1fr);gap:48px;align-items:start}
}
"""


def _link(site: Site, text: str, path: str, cls: str = "", attrs: str = "") -> str:
    """`text` (escaped already) as a link to `path`; plain text when the page has no page there (an
    exported site)."""
    href = site.href(path)
    if href is None:
        return f'<span class="{cls}">{text}</span>' if cls else text
    return f'<a href="{escape(href)}"{f" class={chr(34)}{cls}{chr(34)}" if cls else ""}{attrs}>{text}</a>'


def _query(**params: str | None) -> str:
    found = {k: v for k, v in params.items() if v}
    return f"?{urlencode(found)}" if found else ""


def page(site: Site, params: Mapping[str, str]) -> str:
    """`/people`: the head, the orbit and the thread of the person asked for (`sel`) or the closest,
    everyone else A to Z (`page`), then the review queue (see the module)."""
    year = params.get("year") or None
    found = circle(site, year)
    listed = params.get("page") or "1"
    if not listed.isdigit() or int(listed) < 1:
        raise ValueError(f"page must be a number from 1, not {listed!r}")
    parts = ['<div class="door-people">\n']
    # the year the queue's forms carry back: the one asked for, else the year of the record's today
    head_year = year or ("" if found is None else min(found.today, found.everyone.window[1])[:4])
    shown = [] if found is None else found.near
    parts.append(_head(site, found, shown, year))
    if not shown:
        parts.append(f'<p class="empty">{escape(EMPTY)}</p>\n')
    else:
        drawn, rest = shown[:ORBIT], shown[ORBIT:]
        asked = params.get("sel") or None
        assert found is not None
        # the person asked for (`Gone`, a 404, for nobody), else the closest
        selected = shown[0] if asked is None else near_of(site, found, asked)
        parts.append('<div class="split">\n')
        parts.append(_orbit(site, drawn, selected, year, listed))
        parts.append(_card(site, found, selected, params.get("at") or None))
        parts.append("</div>\n")
        parts.append(_everyone_else(site, rest, year, int(listed)))
        parts.append(_shelf(site, found))
    if not site.static and day_rhythm.reads_up_to(REVIEW_TIER, site.tiers):
        from . import people_review

        with site._review_lock:  # the observed table is built once, as the Places page's queue is
            report = site.shared(("people review",), lambda: people_review.read(site.lb))
        parts.append(f'<section class="review">\n{site._review_html(report, head_year)}</section>\n')
    parts.append("</div>\n")
    return doors.page(site, doors.PEOPLE, "People", "".join(parts), style_=STYLE)


def _head(site: Site, found: Circle | None, shown: Sequence[Near], year: str | None) -> str:
    out = ["<h1>People</h1>\n"]
    if shown:
        count = f"{len(shown):,} {'person' if len(shown) == 1 else 'people'}"
        when = f" heard in {year}" if year else ""
        out.append(
            f'<p class="lead">{escape(count)} in your record{escape(when)}. The closest sit nearest.</p>\n'
        )
    out.append('<ul class="legend" aria-label="The rings, from the inside">\n')
    for ring in RINGS:
        out.append(f'<li><i class="ring-{ring}"></i>{escape(RING_WORDS[ring])}</li>\n')
    out.append("</ul>\n")
    if found is not None and len(found.years) > 1:
        links = [
            "<b>the last year</b>" if year is None else _link(site, "the last year", "/people"),
            *(
                f"<b>{y}</b>" if y == year else _link(site, escape(y), f"/people?year={y}")
                for y in reversed(found.years)
            ),
        ]
        out.append(f'<p class="years">Closeness over {DOT.join(links)}</p>\n')
    return "".join(out)


def _orbit(site: Site, drawn: Sequence[Near], selected: Near, year: str | None, listed: str) -> str:
    """The rings as inline SVG: the owner a dark disc at the centre, each drawn person a circle with
    their initial and their first name under it, on their ring, closest first clockwise from the top;
    each a link that keeps the orbit and opens their thread beside it. No size, no colour and no
    distance says how close: only the ring and the order."""
    size, centre = 600, 300
    radius = {HOME: 70, FAMILY: 128, FRIENDS: 188, EVERYONE: 248}
    out = [
        '<section class="orbit" aria-label="Everyone, by closeness">\n'
        f'<svg class="rings" viewBox="0 0 {size} {size}" role="img" aria-labelledby="orbit-title">'
        '<title id="orbit-title">You at the centre; Home, Family, Friends and Everyone else around you,'
        " the closest first</title>\n"
    ]
    for ring in reversed(RINGS):
        out.append(f'<circle class="ring {ring}" cx="{centre}" cy="{centre}" r="{radius[ring]}"/>\n')
    out.append(f'<circle class="you" cx="{centre}" cy="{centre}" r="34"/>')
    out.append(f'<text class="you" x="{centre}" y="{centre + 5}" text-anchor="middle">You</text>\n')
    by_ring: dict[str, list[Near]] = {r: [] for r in RINGS}
    for n in drawn:
        by_ring[n.ring].append(n)
    # written in closeness order, the closest first, wherever each is drawn: a reader that reads the
    # page in order (a screen reader, the text) meets the people as the order has them
    order = {n.person.entity: i for i, n in enumerate(drawn)}
    placed = sorted(_placed(by_ring, radius, centre), key=lambda found: order[found[1].person.entity])
    for ring, n, x, y in placed:
        name = n.person.name
        first = name.split()[0] if name.split() else name
        initial = first[:1].upper() or "?"
        label = f"{name}, {RING_WORDS[ring]}"
        href = site.href(
            f"/people{_query(year=year, sel=n.person.entity, page=None if listed == '1' else listed)}"
        )
        body = (
            f"<title>{escape(label)}</title>"
            f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="40"/>'
            f'<circle class="face" cx="{x:.1f}" cy="{y:.1f}" r="19"/>'
            f'<text class="initial" x="{x:.1f}" y="{y + 6:.1f}" text-anchor="middle">'
            f"{escape(initial)}</text>"
            f'<text class="name" x="{x:.1f}" y="{y + NAME_BELOW:.1f}" text-anchor="middle">'
            f"{escape(first)}</text>"
        )
        sel = n.person.entity == selected.person.entity
        if href is None:
            out.append(f'<g aria-label="{escape(label)}">{body}</g>\n')
        else:
            current = ' aria-current="true"' if sel else ""
            cls = ' class="sel"' if sel else ""
            out.append(f'<a href="{escape(href)}"{cls}{current} aria-label="{escape(label)}">{body}</a>\n')
    out.append("</svg>\n")
    for ring in (HOME, FAMILY, FRIENDS):
        if not by_ring[ring]:
            said = f'<span class="pencil" title="{escape(RULE)}">{escape(EMPTY_RING[ring])}</span>'
            out.append(f'<p class="ring-empty">{said}</p>\n')
    out.append("</section>\n")
    return "".join(out)


def _placed(
    by_ring: Mapping[str, Sequence[Near]], radius: Mapping[str, int], centre: int
) -> list[tuple[str, Near, float, float]]:
    """Where each drawn person sits: evenly round their ring, the ring's closest first and clockwise,
    each ring turned (`TURNS` tries) so its circles and names keep farthest from those of the rings
    already placed, the innermost first, its closest at the top."""
    placed: list[tuple[str, Near, float, float]] = []
    marks: list[tuple[float, float]] = []  # each placed circle's centre and its name's
    for ring in RINGS:
        found = by_ring[ring]
        if not found:
            continue
        step = 2 * math.pi / len(found)
        best: tuple[float, list[tuple[float, float]]] | None = None
        for k in range(TURNS if marks else 1):
            turn = -math.pi / 2 + step * k / TURNS
            spots = [
                (
                    centre + radius[ring] * math.cos(turn + step * i),
                    centre + radius[ring] * math.sin(turn + step * i),
                )
                for i in range(len(found))
            ]
            ours = [m for x, y in spots for m in _marks(x, y)]
            gap = min((math.dist(a, b) for a in ours for b in marks), default=math.inf)
            if best is None or gap > best[0] + 1e-9:
                best = (gap, spots)
        assert best is not None
        for n, (x, y) in zip(found, best[1], strict=True):
            placed.append((ring, n, x, y))
            marks += _marks(x, y)
    return placed


def _marks(x: float, y: float) -> list[tuple[float, float]]:
    """The points a drawn person covers: their circle, and their name under it, its middle and ends."""
    return [(x, y), (x, y + NAME_BELOW), (x - NAME_HALF, y + NAME_BELOW), (x + NAME_HALF, y + NAME_BELOW)]


def _kicker(near: Near) -> str:
    return (
        f'<p class="kicker"><span class="pencil" title="{escape(RULE)}">'
        f"{escape(RING_WORDS[near.ring])}</span>"
        f"</p>\n"
    )


def _moments(site: Site, moments: Sequence[Moment], at: str | None = None) -> str:
    out = []
    for m in moments:
        text = escape(m.text)
        if m.href is not None:
            text = _link(site, text, m.href)
        if m.pencil is not None:
            text = f'<span class="pencil" title="{escape(m.pencil)}">{text}</span>'
        label = "TODAY" if m.dot == SIGNAL else date_words(m.first, m.last)
        here = at is not None and m.first <= at <= m.last
        cls = m.dot + (" at" if here else "")
        anchor = f' id="at-{m.first}"' if here else ""
        out.append(
            f'<li class="{cls}"{anchor}><span class="date">{escape(label)}</span>'
            f'<p class="moment">{text}</p></li>\n'
        )
    return "".join(out)


def _beginning(site: Site, t: Thread) -> str:
    if t.beginning is not None:
        m = t.beginning
        return (
            f'<li class="beginning"><span class="date">The beginning{DOT}{escape(date_words(m.first))}</span>'
            f'<p class="moment">{_link(site, escape(m.text), str(m.href))}</p></li>\n'
        )
    command = f'logbook with YYYY-MM-DD "{t.near.person.name}"'
    return (
        f'<li class="beginning"><span class="date">The beginning</span>'
        f'<p class="moment"><span class="pencil" title="rule: the beginning">{escape(MET)}</span></p>'
        f'<p class="mono">{escape(command)}</p></li>\n'
    )


def _promises(t: Thread) -> str:
    """The promises open both ways as chips, words only: `YOU OWE THEM · “the book you borrowed”`, `THEY
    OWE YOU · …`, the label set in capitals by the stylesheet. The
    chip names nobody: the thread is theirs already, the record holds no pronoun of anyone's, and a
    promise's words or a day due can begin or end with a figure, which a name would stand beside."""
    if not t.you_owe and not t.they_owe:
        return ""
    out = ['<ul class="chips" aria-label="Promises open both ways">\n']
    for owed, label, cls in ((t.you_owe, "You owe them", "chip owe"), (t.they_owe, "They owe you", "chip")):
        for words, _by in owed:
            said = f'<span class="pencil" title="{escape(PROMISE_RULE)}">{escape(words)}</span>'
            out.append(f'<li class="{cls}"><b>{label}<span class="sep">{DOT}</span></b>{said}</li>\n')
    out.append("</ul>\n")
    return "".join(out)


def _pills(site: Site, t: Thread, first: str = "") -> str:
    """The two links on, after `first`: your years together (Life at your first day together, `/life?at=`,
    RFC 0047 §5) and the places you have shared (Places with them)."""
    entity = t.near.person.entity
    life = "/life" + (f"?at={t.first_day}" if t.first_day else "")
    years = _link(site, "Your years together", life, "pill")
    shared = _link(site, f"Places you{RSQUO}ve shared", f"/places?person={quote(entity, safe='')}", "pill")
    return f'<p class="pills">{first}{years}{shared}</p>\n'


def _known_by(p: people.Person) -> str:
    """How the record knows them: the addresses its resolution lines bind to them, and the birthday one
    carries; at the foot of the whole thread, set small."""
    rows = [(REF_WORDS.get(kind, kind), str(value)) for kind, value in p.refs if kind in REF_WORDS]
    if p.birthday:
        rows.append(("Birthday", date_words(p.birthday) if len(p.birthday) == 10 else p.birthday.lstrip("-")))
    if not rows:
        return ""
    # a word before each: an address that carries their name never stands beside a number
    found = "".join(f"<dt>{escape(word)}</dt><dd>{escape(value)}</dd>" for word, value in rows)
    head = '<section class="part known"><h2>How the record knows them</h2>\n'
    return f'{head}<dl class="refs">{found}</dl>\n</section>\n'


def _card(site: Site, found: Circle, near: Near, at: str | None) -> str:
    """The thread of `near` as a card: the first `CARD` moments, newest first, the beginning, the
    promises both ways, and the links on."""
    t = thread(site, found, near, CARD + 1)  # one more than shown: whether there are earlier ones
    p = near.person
    moments = [*t.coming, *t.today, *t.past]
    out = [
        '<section class="card thread" aria-labelledby="thread-name">\n',
        _kicker(near),
        f'<h2 class="name" id="thread-name">{escape(p.name)}</h2>\n',
        f'<p class="last">{escape(t.last or "No real contact in the record yet.")}</p>\n',
    ]
    if not moments and t.beginning is None:
        out.append(f'<p class="empty">{escape(NOTHING_YET)}</p>\n')
    out.append('<ol class="moments">\n')
    out.append(_moments(site, moments[:CARD], at))
    if len(moments) > CARD:
        earlier = _link(site, "Earlier moments, on the whole thread", person_path(p.entity))
        out.append(f'<li class="more"><p class="more">{earlier}</p></li>\n')
    out.append(_beginning(site, t))
    out.append("</ol>\n")
    out.append(_promises(t))
    out.append(_pills(site, t, _link(site, "The whole thread", person_path(p.entity), "pill dark")))
    out.append("</section>\n")
    return "".join(out)


def _everyone_else(site: Site, rest: Sequence[Near], year: str | None, listed: int) -> str:
    """The people the orbit does not draw, A to Z, `LISTED` a page; the pages named by their letters."""
    if not rest:
        return ""
    ordered = sorted(rest, key=lambda n: (n.person.name.casefold(), n.person.entity))
    pages = [ordered[n : n + LISTED] for n in range(0, len(ordered), LISTED)]
    listed = min(listed, len(pages))
    here = pages[listed - 1]
    out = [
        '<section class="everyone" id="everyone" aria-labelledby="everyone-title">\n'
        '<h2 id="everyone-title">Everyone else</h2>\n<ul class="names">\n'
    ]
    for n in here:
        path = f"/people{_query(year=year, sel=n.person.entity, page=None if listed == 1 else str(listed))}"
        out.append(f"<li>{_link(site, escape(n.person.name), path)}</li>\n")
    out.append("</ul>\n")
    if len(pages) > 1:
        links = []
        for number, group in enumerate(pages, start=1):
            letters = f"{group[0].person.name[:1].upper()} {EN_DASH} {group[-1].person.name[:1].upper()}"
            path = f"/people{_query(year=year, page=None if number == 1 else str(number))}#everyone"
            links.append(
                f"<b>{escape(letters)}</b>"
                if number == listed
                else _link(site, escape(letters), path, "pill")
            )
        out.append(f'<p class="pager">{"".join(links)}</p>\n')
    out.append("</section>\n")
    return "".join(out)


def _shelf(site: Site, found: Circle) -> str:
    """The people heard in the window (the last year, or the year asked for), in the door's order, as
    the People page has always listed them (`Site._person_row`): each name a link to their whole
    thread, the last real contact, and where both come from folded, uncounted; no count beside a name
    (RFC 0043 §2.5), the order says it."""
    heard = [n for n in found.near if _heard_in(n.person, found.since, found.until)]
    when = "in the last year" if found.year is None else f"in {found.year}"
    out = [
        '<section class="part shelf-of" id="shelf" aria-labelledby="shelf-title">\n'
        f'<h2 id="shelf-title">Heard {escape(when)}</h2>\n'
    ]
    if not heard:
        out.append(f'<p class="mute">Nobody the record names was heard {escape(when)}.</p>\n</section>\n')
        return "".join(out)
    out.append(
        '<p class="mute">The people the record names who were heard then, in the order the rings are drawn'
        " in: the people you live with, then days together, calls and messages, and the years the record"
        " has known them. Someone the sources saw and the record has not placed is in the review below,"
        ' never here.</p>\n<ol class="shelf">\n'
    )
    for n in heard:
        p = n.person
        together = [s for s in p.shared.values() if _shared_allowed(s, site.tiers)]
        days = [d for d in people_drift.days_together(_gated_person(p, together)) if found.since <= d["day"]]
        row = {
            "id": p.entity,
            "name": p.name,
            "last_real_contact": None if n.contact is None else n.contact.to_json(),
            "together": [d for d in days if d["day"] <= found.until],
            "channels": {name: p.channels[name].to_json() for name in people.CHANNELS if name in p.channels},
        }
        out.append(site._person_row(row))
    out.append("</ol>\n</section>\n")
    return "".join(out)


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _facts(site: Site, found: Circle, t: Thread) -> str:
    """The person's page's rows of facts, as it has always had them, each with where it comes from
    folded: the days together (and nights under one roof), the last real contact and what it was, and
    the drift (`people_drift.verdict`), read through the page's gate."""
    p, together = t.near.person, t.together
    days = f"{_plural(len(together), 'day')} together" if together else "no day together"
    if p.nights:
        days += f"{DOT}{_plural(p.nights, 'night')} under one roof"
    evidence: list[tuple[str, list[str], str | None]] = [
        (f"at {d['where']}", list(d["lines"]), str(d["day"])) for d in together
    ]
    out = ['<ol class="shelf facts">\n', f"<li><p>{escape(days)}</p>\n{site._evidence(evidence)}</li>\n"]
    contact = found.everyone.contacts.get(p.entity)
    if contact is None:
        out.append("<li><p>no real contact in the record</p></li>\n")
    else:
        day = site.link(escape(contact.day), f"/day/{contact.day}")
        out.append(
            f"<li><p>last real contact {day}{DOT}{escape(t.what or contact.via)}</p>\n"
            f"{site._evidence([(contact.via, [contact.line], contact.day)])}</li>\n"
        )
    until = people_drift.until_of(found.everyone.report, found.everyone.window[1])
    verdict = people_drift.verdict(p, contact, until)
    by_year = Counter(str(d["day"])[:4] for d in together)
    items: list[tuple[str, list[str], str | None]] = []
    if verdict.year is not None and by_year.get(verdict.year):
        items.append((f"{_plural(by_year[verdict.year], 'day')} together in {verdict.year}", [], None))
    if contact is not None:
        items.append(("the last real contact", [contact.line], contact.day))
    out.append(f"<li><p>{escape(verdict.text())}</p>\n{site._evidence(items)}</li>\n</ol>\n")
    return "".join(out)


def _years(site: Site, t: Thread) -> str:
    """The days together by year, newest first, each year's days counted and folded with where."""
    by_year: dict[str, list[dict[str, Any]]] = {}
    for d in t.together:
        by_year.setdefault(str(d["day"])[:4], []).append(d)
    if not by_year:
        return ""
    out = ['<ol class="shelf years-of">\n']
    for year in sorted(by_year, reverse=True):
        items = [(f"at {d['where']}", list(d["lines"]), str(d["day"])) for d in by_year[year]]
        out.append(
            f"<li><p><b>{year}</b>{DOT}{_plural(len(by_year[year]), 'day')}</p>\n"
            f"{site._evidence(items, 'the days')}</li>\n"
        )
    out.append("</ol>\n")
    return "".join(out)


def _owed(site: Site, t: Thread) -> str:
    """The promises open both ways, as the person's page has always listed them: the day each was said,
    the day it is due, its words (a rule's reading: pencil) and the line it was read from, folded."""
    if not t.owed:
        return '<p class="empty">Nothing open between you, either way.</p>\n'
    out = []
    for mine, label in ((True, "You owe them"), (False, "They owe you")):
        found = [person_page.promise_json(proposal) for proposal, yours in t.owed if yours is mine]
        out.append(f"<h3>{label}</h3>\n")
        if not found:
            out.append('<p class="mute">nothing open</p>\n')
            continue
        out.append('<ol class="shelf">\n')
        for o in found:
            due = f"{DOT}due {o['due']}" if o["due"] else ""
            day = str(o["day"])
            said = f'<span class="pencil" title="{escape(PROMISE_RULE)}">{escape(str(o["quote"]))}</span>'
            out.append(
                f'<li><p class="head">{site.link(escape(day), f"/day/{day}")}'
                f'<span class="mute">{escape(due)}</span></p>\n<p>{said}</p>\n'
                f"{site._evidence([(f'{o["kind"]} ({o["source"]})', [o['line']], day)])}</li>\n"
            )
        out.append("</ol>\n")
    return "".join(out)


def _anniversaries(site: Site, found: Circle, t: Thread) -> str:
    """The days together a whole number of years before a day of the coming month, as the person's
    page has always listed them, each with its day's lines folded."""
    out = [
        '<section class="part"><h2>Anniversaries'
        f" <small>{escape(found.today)} and the month after</small></h2>\n"
    ]
    coming = person_page.anniversaries(t.together, found.today)
    if not coming:
        out.append('<p class="mute">none in the coming month</p>\n</section>\n')
        return "".join(out)
    out.append('<ol class="shelf">\n')
    for a in coming:
        day = str(a["day"])
        out.append(
            f"<li><p>{escape(str(a['on']))}{DOT}{_plural(int(a['years']), 'year')} since "
            f"{site.link(escape(day), f'/day/{day}')} at {escape(str(a['where']))}</p>\n"
            f"{site._evidence([('together', list(a['lines']), day)])}</li>\n"
        )
    out.append("</ol>\n</section>\n")
    return "".join(out)


# -- one person's page ----------------------------------------------------------------------------------


def page_person(site: Site, entity: str, params: Mapping[str, str]) -> str:
    """`/people/ID`: the whole thread (see the module); `?said=1` with the words of the last few
    messages and recordings; `?at=DAY` marks the moment of that day."""
    found = circle(site, None)
    if found is None:
        raise Gone(f"no person {entity!r}: the record has no days")
    near = near_of(site, found, entity)
    p = near.person
    t = thread(site, found, near, RECENT, words=True)
    at = params.get("at") or None
    out = [
        '<div class="door-people one">\n',
        f"<p>{_link(site, '← People', '/people' + _query(sel=p.entity), 'back mono')}</p>\n",
        _kicker(near),
        f'<h1 id="thread-name">{escape(p.name)}</h1>\n',
        f'<p class="last">{escape(t.last or "No real contact in the record yet.")}</p>\n',
        _pills(site, t),
        _facts(site, found, t),
        _strip(site, p, _years(site, t)),
        '<div class="sides">\n<div>\n<section class="part"><h2>The thread</h2>\n',
    ]
    moments = [*t.coming, *t.today, *t.past]
    if not moments and t.beginning is None:
        out.append(f'<p class="empty">{escape(NOTHING_YET)}</p>\n')
    out.append('<ol class="moments">\n')
    out.append(_moments(site, moments, at))
    out.append(_beginning(site, t))
    out.append("</ol>\n</section>\n</div>\n<div>\n")
    names = [n.person.name for n in found.near] + [p.name, *p.name.split()]
    drafted_ = drafted(site, p, names)
    if drafted_ is not None:
        out.append(_drafted_html(site, drafted_))
    out.append('<section class="part"><h2>Promises</h2>\n')
    out.append(_owed(site, t))
    out.append("</section>\n")
    out.append(_anniversaries(site, found, t))
    out.append(_said(site, p, params.get("said") == "1"))
    out.append(f'<section class="part"><h2>Places you{RSQUO}ve shared</h2>\n')
    if t.places:
        links = "".join(
            f"<li>{_link(site, escape(name), f'/places?person={quote(p.entity, safe="")}', 'pill')}</li>"
            for name in t.places
        )
        out.append(f'<ul class="pills">{links}</ul>\n')
    else:
        out.append('<p class="empty">None yet: a day together somewhere puts it here.</p>\n')
    out.append("</section>\n")
    out.append(_known_by(p))
    out.append("</div>\n</div>\n")
    out.append("</div>\n")
    return doors.page(site, doors.PEOPLE, p.name, "".join(out), style_=STYLE)


def _strip(site: Site, p: people.Person, years: str = "") -> str:
    """The days together as a strip over the years: one small mark per day, all alike, each a link to
    that day; then `years`, the days of each year counted with their evidence (`_years`)."""
    together = sorted(
        {s.day: s for s in p.shared.values() if _shared_allowed(s, site.tiers)}.values(), key=lambda s: s.day
    )
    out = ['<section class="part"><h2>Days together</h2>\n']
    if not together:
        out.append(
            '<p class="empty">None yet: a day you are both somewhere, by the record, puts a mark here.</p>\n'
        )
        out.append("</section>\n")
        return "".join(out)
    by_year: dict[str, list[people.SharedDay]] = {}
    for s in together:
        by_year.setdefault(s.day[:4], []).append(s)
    out.append('<p class="fact">One mark for each day you were together; each opens that day.</p>\n')
    out.append('<ul class="strip">\n')
    for year in sorted(by_year, reverse=True):
        marks = []
        for s in by_year[year]:
            title = f"{date_words(s.day)}{DOT}{_place(s.where, bare=True)}"
            cls = "mark"
            href = site.href(_day(s.day))
            if href is None:
                marks.append(f'<span class="{cls}" title="{escape(title)}"></span>')
            else:
                marks.append(
                    f'<a class="{cls}" href="{escape(href)}" title="{escape(title)}"'
                    f' aria-label="{escape(title)}"></a>'
                )
        out.append(
            f'<li><span class="label">{escape(year)}</span><span class="marks">{"".join(marks)}</span></li>\n'
        )
    out.append(f"</ul>\n{years}</section>\n")
    return "".join(out)


def _said(site: Site, p: people.Person, words: bool) -> str:
    out = ['<section class="part" id="said"><h2>What was said</h2>\n']
    if not words:
        if not any(name in p.channels for name in ("messages", "transcripts")):
            out.append('<p class="empty">Nothing yet: a message or a recording with them goes here.</p>\n')
        else:
            out.append(
                '<p class="empty">The words of your last messages and recordings with them, read only when'
                " asked.</p>\n"
                f'<p class="pills">'
                f"{_link(site, 'Read what was said', person_path(p.entity) + '?said=1#said', 'pill')}</p>\n"
            )
        out.append("</section>\n")
        return "".join(out)
    found = said(site, p)
    if not found:
        out.append(
            '<p class="empty">Nothing this page reads: a message or a recording with them goes here.</p>\n'
        )
    else:
        out.append('<ul class="said">\n')
        for r, text in found:
            out.append(
                f'<li><span class="date">{escape(date_words(r.day))}{DOT}{escape(r.source)}</span>'
                f"<p>{_link(site, escape(text), _day(r.day))}</p></li>\n"
            )
        out.append("</ul>\n")
    out.append(
        f'<p class="pills">{_link(site, "Fold the words away", person_path(p.entity) + "#said", "pill")}'
        "</p>\n"
    )
    out.append("</section>\n")
    return "".join(out)


def _drafted_html(site: Site, d: Drafted) -> str:
    """What a model drafted about them, in pencil: each sentence lighter, dotted, the model on hover,
    and the lines it rests on."""
    said = f"model: {d.model}" + (f"{DOT}{d.window}" if d.window else "")
    out = ['<section class="part draft"><h2>Drafted about them</h2>\n']
    out.append(f'<p class="kicker">Pencil{DOT}{escape(d.model)}</p>\n')
    for text, evidence, held in d.segments:
        out.append(f'<p><span class="pencil" title="{escape(said)}">{escape(text)}</span></p>\n')
        if evidence and not held:
            links = "".join(
                _link(site, escape(drafts.short_id(e)), f"/line/{quote(e, safe='')}") for e in evidence
            )
            out.append(f'<p class="evidence">Evidence{DOT}{links}</p>\n')
    out.append("</section>\n")
    return "".join(out)
