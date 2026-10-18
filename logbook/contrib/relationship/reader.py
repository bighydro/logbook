"""The authorized input set of one canonical person, and the derived store it is written to
(EXPERIMENTAL, slice 1; README.md beside this file).

**The entry.** Reading a person for a model is a crossing like any other, so it has its own entry in
`policy/crossing.json`, `{"relationship": {"max_tier": 2, "until": "YYYY-MM-DD"}}`: `max_tier` is the
ceiling the lines are read and served under, `until` the last day the lend holds, and it is required.
No entry, no `until`, or an expired one, and nothing is read or served (`entry`). Its optional `model`
is the one model the person may go to, as the `dream` entry's is; its optional `include_unsigned`
(`true`) lifts the signed-day gate below.

**The gate** (`Gate`) is the crossing's, as `export notion` holds it: a line of evidence counts only at
or under the ceiling and on a day the owner has signed (RFC 0034), unless the entry lifts that; a
resolution line, which binds a ref to a person and gives the label, counts only at or under the
ceiling, whatever its day. The people reader reads through it (`people.read(admit=...)`), so no
person, label, speaker or line of the set rests on a line above the ceiling.

**The authorized input set** (RFC 0036 amendment 1, the person unit) is exactly the lines on which the
person is a counterpart (a message they sent or the owner sent in a direct chat with them, a call with
them, a mail from or to them), an attendee (an event they did not decline) or a speaker (a transcript
they spoke in), on a local day of the window, not retracted, not superseded, through the gate:
the person page's channels `messages`, `calls`, `mail`, `calendar` and `transcripts`, read as
`logbook.core.people` reads them, and nothing else. A line that merely mentions them is never in it: a
note that says "with Ola", a mail that names them, a message someone else sent in a group, a tagged
face. The person is one the resolution lines name, never the owner (`people.find`); an unresolved name
is refused and gets no store.

**The days together** (RFC 0036 amendment 2, the owner's decision of 18 October 2026) go beside the set:
each day the with module confirms the person at one of the owner's stays in the window, read through
the same gate (`people.read`'s days together), with the `places.json` names of the stays (`NO_NAME`
for a stay at none, never coordinates) and the lines it rests on (`Together`); a line of a day that is
not in the set is a `Rest`, which a citation resolves to without its words. A day whose every line the
gate refuses is counted (`together_held`). They are read from the record each time, never stored.

**Speaker attribution.** Each line carries the peers whose words it is: a message its sender's (the
owner's for one the owner sent), a mail its sender's, an answered call both ends', a transcript every
participant the record resolves; an event is attendance, which is not speech. A peer is one canonical
person, by entity id, or the owner; a speaker the record does not resolve gets no peer and is counted
on the line as `unresolved`. A name inside a line's text is never a speaker.

**The store** is `state/relationship/<person>/`, bookkeeping beside the record and never in it, shaped
as a Honcho-like store would hold it: `peers.json` (one peer per canonical person: the person, the
other people who spoke on their lines, the owner), `messages.jsonl` (one message per line of the set,
with its speakers, role, kind, instant, source, tier and words), `lines.json` (the line-id map: message
id to line id) and `manifest.json` (the person, the window, the head and the policy it was read under,
how many lines it read, how many it held back above the ceiling and how many on unsigned days), written
last. Ingesting rebuilds
the whole store from the record, so ingesting twice writes the same bytes and a store wiped by hand is
recovered by ingesting again. A store serves only under the head and the policy it was read under
(`check`): a head that moved, an entry that changed or expired, and it serves nothing until rebuilt."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ...core import day_start, people, policy, present, signing, stays
from ...core import places as named_places
from ...core.chain import Line
from ...core.export import parse_day
from ...core.resolve import Ref
from ...core.store import Logbook

ENTRY = "relationship"  # its entry in policy/crossing.json
READER = "relationship/1"  # kept in the manifest: which reader wrote the store; 1 added the signed-day gate
STATE = PurePosixPath("state/relationship")  # record-relative; one folder per person
CHANNELS = ("messages", "calls", "mail", "calendar", "transcripts")  # the person page's, less `faces`
ROLE = {
    "messages": "counterpart",
    "calls": "counterpart",
    "mail": "counterpart",
    "calendar": "attendee",
    "transcripts": "speaker",
}
OWNER = "owner"  # the owner's peer's label
FOLDER_NAME = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_-]*$")  # an entity id that can name a folder
EN_DASH = "\u2013"
NO_NAME = "a place with no name"  # a day together's stay at no place places.json names: never coordinates
CLOUD_CEILING = 2  # the owner's decision (18 Oct 2026): nothing above tier 2 goes to the cloud model
EARLIEST = datetime.min.replace(tzinfo=UTC)  # a stamp that is no instant sorts first


class RelationshipError(ValueError):
    """The reader refuses: the entry, the person, the window or the store; one sentence, nothing
    written."""


@dataclass(frozen=True)
class Entry:
    """The `relationship` entry as it counts today: the ceiling, the last day, the one model it names
    (None: the endpoint's) and whether unsigned days are read too."""

    max_tier: int
    until: date
    model: str | None = None
    include_unsigned: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "max_tier": self.max_tier,
            "until": self.until.isoformat(),
            "model": self.model,
            "include_unsigned": self.include_unsigned,
        }

    @property
    def version(self) -> str:
        """`policy.version` of the entry: what a person draft records under `extra.policy_version`."""
        return policy.version(self.ceiling)

    @property
    def ceiling(self) -> policy.Ceiling:
        return policy.Ceiling(ENTRY, self.max_tier, self.until, False, model=self.model)


def entry(root: Path) -> Entry:
    """The `relationship` entry held against today; refused in one sentence naming the file when
    there is none, when it has no `until`, or when it has expired."""
    path = policy.policy_path(root)
    try:
        found = next((c for c in policy.ceilings(root) if c.destination == ENTRY), None)
    except policy.PolicyError as e:
        raise RelationshipError(str(e)) from None
    if found is None:
        raise RelationshipError(
            f"{path} names no {ENTRY!r} entry, so nothing crosses to the relationship reader; add"
            f' {{"{ENTRY}": {{"max_tier": 2, "until": "YYYY-MM-DD"}}}} to it'
        )
    if found.until is None:
        raise RelationshipError(
            f"{path}: the {ENTRY!r} entry has no until; a lend to the relationship reader has a last"
            " day, write it as YYYY-MM-DD"
        )
    if found.expired:
        raise RelationshipError(
            f"{path}: the {ENTRY!r} entry expired on {found.until.isoformat()} and counts as max_tier 0,"
            " so nothing is read or served; write a new until there or remove the entry"
        )
    if found.max_tier > CLOUD_CEILING:
        raise RelationshipError(
            f"{path}: the {ENTRY!r} entry says max_tier {found.max_tier}, and the relationship reader's"
            f" model is a cloud one, which reads at most {CLOUD_CEILING}; write max_tier 1 or 2 there"
        )
    return Entry(found.max_tier, found.until, found.model, found.include_unsigned)


@dataclass(frozen=True)
class Item:
    """One line of the set, as the store holds it."""

    line: str
    at: str
    kind: str
    source: str
    tier: int
    role: str  # counterpart, attendee or speaker: how the person is on the line
    speakers: tuple[str, ...]  # the peers whose words the line is
    unresolved: int  # the speakers the record does not resolve: no peer
    text: str


@dataclass(frozen=True)
class Rest:
    """A line a day together rests on that is not a line of the set (a note "with Ola" written at the
    stay): what a citation of it resolves to, never its words."""

    line: str
    at: str
    kind: str
    source: str
    tier: int


@dataclass(frozen=True)
class Together:
    """One day together in the window (RFC 0036 amendment 2): a day the with module confirms the
    person at one of the owner's stays (`people.read`'s days together), the named places of the stays
    they shared, `NO_NAME` for a stay at no place `places.json` names, and the lines it rests on."""

    day: str
    places: tuple[str, ...]
    lines: tuple[str, ...]
    tier: int


@dataclass(frozen=True)
class InputSet:
    """The authorized input set of one person over a window, read under one ceiling."""

    person: str  # the entity id
    label: str
    first: str  # local days, both inclusive
    last: str
    peers: dict[str, str]  # peer id -> label: the person, the others who spoke, the owner
    items: tuple[Item, ...]  # by instant
    held_back: int  # the person's lines in the window above the ceiling
    unsigned: int = 0  # the person's lines in the window on a day the owner has not signed
    tier: int = 1  # the highest tier read: the lines of the set, the days together's and the resolution lines
    together: tuple[Together, ...] = ()  # the days together in the window, by day (amendment 2)
    rests: tuple[Rest, ...] = ()  # the lines the days together rest on that are not lines of the set
    together_held: int = 0  # days together the gate refused: resting on no line it lets through

    def by_line(self) -> dict[str, Item]:
        return {item.line: item for item in self.items}

    def by_evidence(self) -> dict[str, Item | Rest]:
        """Every line a claim may cite: the lines of the set and the lines the days together rest on."""
        return {**{r.line: r for r in self.rests}, **self.by_line()}

    @property
    def span(self) -> str:
        return f"{self.first} {EN_DASH} {self.last}"


@dataclass
class Gate:
    """What a line must pass to be read: a resolution line its tier, a line of evidence its tier and,
    unless `signed` is None (the gate lifted), a signed local day. What it refuses is kept by id."""

    ceiling: int
    signed: frozenset[str] | None
    days: day_start.DayStart
    evidence: bool = True  # False: the counting read, which gates resolution lines alone
    above: set[str] = field(default_factory=set)
    unsigned: set[str] = field(default_factory=set)

    def __call__(self, line: Line) -> bool:
        tier = int(line.get("tier", 0))
        if line.get("kind") == "resolution":
            return tier <= self.ceiling
        if not self.evidence:
            return True
        line_id = str(line.get("id"))
        if tier > self.ceiling:
            self.above.add(line_id)
            return False
        if self.signed is not None and not self._signed(line):
            self.unsigned.add(line_id)
            return False
        return True

    def _signed(self, line: Line) -> bool:
        at = stays.instant(line.get("at"))
        return at is not None and self.days.day(at).isoformat() in (self.signed or ())


def gate(lb: Logbook, ceiling: int, include_unsigned: bool = False) -> Gate:
    """The gate of the entry: `ceiling`, and the days with a standing signature unless lifted."""
    signed = None
    if not include_unsigned:
        with lb.index() as idx:
            signed = frozenset(signing.gate(idx, str(lb.meta.get("owner_id") or "") or None)[0])
    return Gate(ceiling, signed, day_start.of(lb.meta))


def read(
    lb: Logbook, name: str, first: str, last: str, ceiling: int, include_unsigned: bool = False
) -> InputSet:
    """The set of the person `name` means (as `people NAME` finds them) over `[first, last]`, through
    the gate of `ceiling` and, unless `include_unsigned`, of the signed days. The person's lines the
    gate refuses are counted, never read: above the ceiling (`held_back`) or on a day not signed
    (`unsigned`). Writes nothing."""
    first, last = _window(first, last)
    through = gate(lb, ceiling, include_unsigned)
    try:
        report = people.read(lb, first, last, admit=through)
        person = _find(lb, name, report, ceiling)
        whole = people.read(lb, first, last, admit=Gate(ceiling, None, through.days, evidence=False))
        counted = people.find(name, whole)
    except people.PersonError as e:
        raise RelationshipError(str(e)) from None
    role: dict[str, str] = {}
    for channel in CHANNELS:
        found = person.channels.get(channel)
        for id_ in found.ids if found is not None else []:
            role.setdefault(id_, ROLE[channel])
    theirs = {id_ for channel in CHANNELS for id_ in _ids(counted, channel)} - set(role)
    owner = str(lb.meta.get("owner_id") or "")
    with lb.index() as idx:
        lines = idx.by_ids(role)
    items: list[Item] = []
    for id_, line in lines.items():
        tier = int(line.get("tier", 0))
        if tier > ceiling:  # the gate refused it already; never read, whatever the reader returned
            continue
        speakers, unresolved = _speakers(line, report, owner)
        at, kind, source = str(line.get("at")), str(line.get("kind")), str(line.get("source"))
        items.append(Item(id_, at, kind, source, tier, role[id_], speakers, unresolved, _text(line)))
    items.sort(key=lambda i: (stays.instant(i.at) or EARLIEST, i.line))  # instants, never the text
    others = sorted(
        {s for i in items for s in i.speakers} - {person.entity, owner},
        key=lambda e: (report.known[e].name.casefold(), e),
    )
    peers = {person.entity: person.name, **{e: report.known[e].name for e in others}, owner: OWNER}
    together = _together(lb, person, ceiling)
    rests = _rests(lb, together, {i.line for i in items})
    tier = max(
        [i.tier for i in items]
        + [t.tier for t in together]
        + [report.known[e].tier for e in (person.entity, *others)]
        + [1]
    )
    held = len({day for day, _stay in counted.shared} - {t.day for t in together})
    return InputSet(
        person.entity,
        person.name,
        first,
        last,
        peers,
        tuple(items),
        len(theirs & through.above),
        len(theirs & through.unsigned),
        tier,
        together,
        rests,
        held,
    )


def _together(lb: Logbook, person: people.Person, ceiling: int) -> tuple[Together, ...]:
    """The person's days together in the gated reading (`people.read` through the entry's gate, so
    every line a day rests on is at or under the ceiling and on a signed day unless lifted), one per
    day: the stays' names as `places.json` gives them, else `NO_NAME`, never the coordinates a stay
    at no named place reads as; and the lines it rests on, in the order the with module found them.
    A day whose every line the gate refused is not one (`InputSet.together_held` counts it)."""
    named = {place.name for place in named_places.read(lb.root)}
    by_day: dict[str, list[people.SharedDay]] = {}
    for (day, _stay), shared in sorted(person.shared.items()):
        by_day.setdefault(day, []).append(shared)
    out = []
    for day, found in by_day.items():
        found = [s for s in found if s.tier <= ceiling]  # the gate refused them already; never sent
        lines = tuple(dict.fromkeys(id_ for s in found for id_ in s.lines))
        if not lines:
            continue
        places = tuple(dict.fromkeys(s.where if s.where in named else NO_NAME for s in found))
        out.append(Together(day, places, lines, max(s.tier for s in found)))
    return tuple(out)


def _rests(lb: Logbook, together: tuple[Together, ...], items: set[str]) -> tuple[Rest, ...]:
    """The lines the days together rest on that are not lines of the set, read for what a citation
    of one resolves to (its instant, kind, source and tier), never for its words."""
    wanted = list(dict.fromkeys(id_ for t in together for id_ in t.lines if id_ not in items))
    if not wanted:
        return ()
    with lb.index() as idx:
        lines = idx.by_ids(wanted)
    return tuple(
        Rest(
            id_, str(line.get("at")), str(line.get("kind")), str(line.get("source")), int(line.get("tier", 0))
        )
        for id_ in wanted
        if (line := lines.get(id_)) is not None
    )


def _ids(person: people.Person, channel: str) -> list[str]:
    found = person.channels.get(channel)
    return found.ids if found is not None else []


def _find(lb: Logbook, name: str, report: people.Report, ceiling: int) -> people.Person:
    """The person in the gated reading; one named only by resolution lines above the ceiling is
    refused in one sentence, since nothing of them may be read under it."""
    try:
        return people.find(name, report)
    except people.PersonError:
        try:
            people.find(name, people.directory(lb))
        except people.PersonError:
            raise
        raise RelationshipError(
            f"every resolution line that names {name!r} is above max_tier {ceiling} of the {ENTRY!r}"
            " entry, so nothing of them is read"
        ) from None


def promises(lb: Logbook, found: InputSet, ceiling: int) -> dict[str, list[dict[str, Any]]]:
    """The promises read in the lines of the set, by line id: `{owed, quote, due}`, `owed` `by_owner`
    (the owner's own, or asked of the owner) or `to_owner` (theirs). A promise is the words of a line of
    the set, so it adds no line: `promises` reads only the set's lines (and the resolution lines at or
    under the ceiling, to know who spoke), never a group, a note or a mail that merely names the person
    (RFC 0036 amendment 1). Writes nothing."""
    from .. import promises as promise_reader

    ids = {item.line for item in found.items}

    def admit(line: Line) -> bool:
        if line.get("kind") == "resolution":
            return int(line.get("tier", 0)) <= ceiling
        return str(line.get("id")) in ids

    out: dict[str, list[dict[str, Any]]] = {}
    report = promise_reader.extract(lb, found.first, until=found.last, admit=admit)
    for proposal in report.proposals:
        if proposal.line not in ids or not proposal.shows or proposal.role is None:
            continue
        mine = proposal.role in (promise_reader.PROMISE, promise_reader.ASKED)
        said = {"owed": "by_owner" if mine else "to_owner", "quote": proposal.match.quote}
        if proposal.due:
            said["due"] = proposal.due
        out.setdefault(proposal.line, []).append(said)
    return out


def identify(lb: Logbook, name: str, ceiling: int) -> tuple[str, str]:
    """The entity id and label of the person `name` means, read through the resolution lines at or
    under `ceiling` alone, as the set is: a name given only above it neither finds nor labels anyone.
    The people reader's `known` is every person those lines name, heard in its window or not, so one
    day's reading finds anyone."""
    day = policy.today().isoformat()
    names_only = Gate(ceiling, None, day_start.of(lb.meta), evidence=False)
    try:
        person = _find(lb, name, people.read(lb, day, day, admit=names_only), ceiling)
    except people.PersonError as e:
        raise RelationshipError(str(e)) from None
    return person.entity, person.name


def _window(first: str, last: str) -> tuple[str, str]:
    a, b = parse_day(first), parse_day(last)
    if a > b:
        raise RelationshipError(f"the window runs backwards: {first} is after {last}")
    return a.isoformat(), b.isoformat()


def _speakers(line: Line, report: people.Report, owner: str) -> tuple[tuple[str, ...], int]:
    payload = line.get("payload") or {}
    kind = line.get("kind")
    found: list[str | None] = []
    if kind == "message":
        found = (
            [owner] if payload.get("from_me") is True else [_peer(_ref(payload.get("sender")), report, owner)]
        )
    elif kind == "mail":
        sender = payload.get("from")
        email = sender.get("email") if isinstance(sender, dict) else None
        found = [_peer(("email", email) if isinstance(email, str) else None, report, owner)]
    elif kind == "call" and payload.get("answered") is True:
        found = [_peer(_ref(payload.get("counterparty")), report, owner), owner]
    elif kind == "transcript":
        participants = payload.get("participants")
        found = [
            _participant(p, report, owner)
            for p in (participants if isinstance(participants, list) else [])
            if isinstance(p, dict)
        ]
    return tuple(dict.fromkeys(f for f in found if f is not None)), sum(1 for f in found if f is None)


def _peer(ref: Ref | None, report: people.Report, owner: str) -> str | None:
    """The peer a ref is: the owner, a canonical person of the record, or None (no peer)."""
    if ref is None or not ref[1].strip():
        return None
    if ref[0] == "email":
        ref = ("email", ref[1].strip().casefold())
    if ref in report.owner.refs:
        return owner
    entity, _label = present.resolve_ref(ref, report.identities)
    return _canonical(entity, report, owner)


def _participant(participant: dict[str, Any], report: people.Report, owner: str) -> str | None:
    """A transcript's participant by email, phone or provider id, else by the spoken name when the
    record labels exactly one person by it (`docs/people.md`)."""
    for kind in ("email", "phone", "provider_id"):
        value = participant.get(kind)
        if isinstance(value, str) and value:
            found = _peer((kind, value), report, owner)
            if found is not None:
                return found
    spoken = participant.get("name")
    if not isinstance(spoken, str) or not spoken.strip():
        return None
    entity, _label = present.by_name(spoken, report.identities)
    return _canonical(entity, report, owner)


def _canonical(entity: str | None, report: people.Report, owner: str) -> str | None:
    if entity is None:
        return None
    if entity in report.owner.entities:
        return owner
    return entity if entity in report.known else None


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    return (kind, ref_value) if isinstance(kind, str) and isinstance(ref_value, str) else None


def _text(line: Line) -> str:
    """The line's own words, as the source gave them: a message's text, a mail's subject, an event's
    title, a transcript's title and the provider's summary, a call as what it was."""
    payload = line.get("payload") or {}
    kind = line.get("kind")
    if kind == "call":
        minutes = round(int(payload.get("duration_s") or 0) / 60)
        how = f"answered, {minutes} min" if payload.get("answered") is True else "not answered"
        return f"{payload.get('direction') or 'a'} call, {how}"
    keys = {
        "message": ("text",),
        "mail": ("subject",),
        "event": ("title",),
        "transcript": ("title", "summary"),
    }
    return "; ".join(str(payload[k]) for k in keys.get(str(kind), ()) if payload.get(k))


# -- the store ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Derived:
    """A store as read back: what the manifest says, the peers, the messages, the line-id map."""

    folder: Path
    manifest: dict[str, Any]
    peers: dict[str, str]
    messages: list[dict[str, Any]]
    lines: dict[str, str]  # message id -> line id

    @property
    def window(self) -> tuple[str, str]:
        return str(self.manifest["window"]["from"]), str(self.manifest["window"]["to"])


def folder(lb: Logbook, person: str) -> Path:
    if not FOLDER_NAME.match(person):
        raise RelationshipError(f"the person's id {person!r} cannot name a folder under {STATE}")
    return lb.root.joinpath(*STATE.parts, person)


def message_id(person: str, line: str) -> str:
    """The store's id for one line of one person's set: the same line, the same id, every rebuild."""
    return hashlib.sha256(f"{person}|{line}".encode()).hexdigest()[:16]


def ingest(lb: Logbook, name: str, first: str, last: str) -> tuple[InputSet, Path]:
    """Read the set of `name` over `[first, last]` under the `relationship` entry and write the
    store, replacing what was there. The record is never written."""
    current = entry(lb.root)
    head = str(lb.meta.get("head"))
    found = read(lb, name, first, last, current.max_tier, current.include_unsigned)
    if str(lb.meta.get("head")) != head:
        raise RelationshipError(
            "the record's head moved while the reader read it; nothing was written, ingest again"
        )
    where = folder(lb, found.person)
    if where.exists():
        shutil.rmtree(where)
    where.mkdir(parents=True)
    messages = [
        {
            "id": message_id(found.person, i.line),
            "speakers": list(i.speakers),
            "role": i.role,
            "kind": i.kind,
            "at": i.at,
            "source": i.source,
            "tier": i.tier,
            "unresolved": i.unresolved,
            "text": i.text,
        }
        for i in found.items
    ]
    manifest = {
        "reader": READER,
        "person": found.person,
        "label": found.label,
        "window": {"from": found.first, "to": found.last},
        "read_head": head,
        "policy": current.to_json(),
        "read_count": len(found.items),
        "held_back": found.held_back,
        "unsigned": found.unsigned,
    }
    _write(where / "peers.json", _json([{"id": k, "label": v} for k, v in found.peers.items()]))
    _write(where / "messages.jsonl", "".join(json.dumps(m, ensure_ascii=False) + "\n" for m in messages))
    _write(where / "lines.json", _json({m["id"]: i.line for m, i in zip(messages, found.items, strict=True)}))
    _write(where / "manifest.json", _json(manifest))  # last: a folder without it is no store
    return found, where


def _json(data: object) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def _write(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))  # the bytes, never text mode: the same file on every platform


def load(lb: Logbook, person: str) -> Derived | None:
    """The store of `person`, or None when there is none (never built, or wiped)."""
    where = folder(lb, person)
    if not (where / "manifest.json").is_file():
        return None
    try:
        manifest = json.loads((where / "manifest.json").read_text(encoding="utf-8"))
        peers = {
            str(p["id"]): str(p["label"])
            for p in json.loads((where / "peers.json").read_text(encoding="utf-8"))
        }
        rows = (where / "messages.jsonl").read_text(encoding="utf-8").splitlines()
        messages = [json.loads(row) for row in rows if row.strip()]
        if not all(isinstance(m, dict) for m in messages):
            raise ValueError("a message that is not an object")
        lines = {
            str(k): str(v) for k, v in json.loads((where / "lines.json").read_text(encoding="utf-8")).items()
        }
        window = manifest["window"]
        if not isinstance(window.get("from"), str) or not isinstance(window.get("to"), str):
            raise ValueError("the manifest has no window")
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise RelationshipError(
            f"{where} is not a store this reader wrote ({e}); remove it and ingest again"
        ) from None
    if manifest.get("person") != person:  # a case-insensitive disk folds two ids into one folder
        raise RelationshipError(f"{where} holds another person's store; remove it and ingest again")
    return Derived(where, manifest, peers, messages, lines)


def check(lb: Logbook, store: Derived, current: Entry) -> None:
    """A store serves only under the policy and the head it was read under: an entry that changed
    since (lowered, raised, a new `until`) or a head that moved (a line retracted, a line added),
    and it serves nothing until it is rebuilt. An expired entry is refused before (`entry`)."""
    label = store.manifest.get("label") or store.manifest.get("person")
    built = store.manifest.get("policy")
    if built != current.to_json():
        raise RelationshipError(
            f"the {ENTRY!r} entry changed since the store for {label} was built ({_policy(built)}, now"
            f" {_policy(current.to_json())}), so it no longer serves; ingest again"
        )
    head = str(lb.meta.get("head"))
    read_head = str(store.manifest.get("read_head"))
    if read_head != head:
        raise RelationshipError(
            f"the record moved since the store for {label} was built (read at {read_head[:8]}, now"
            f" {head[:8]}), so it no longer serves; ingest again"
        )


def _policy(found: object) -> str:
    if not isinstance(found, dict):
        return "no policy"
    said = f"max_tier {found.get('max_tier')} until {found.get('until')}"
    if found.get("model"):
        said += f" model {found.get('model')}"
    return said + (" with unsigned days" if found.get("include_unsigned") else "")
