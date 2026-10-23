"""Observed orgs, ideas and assets, the review queue and the owner's say — `logbook review org|idea|asset`
(RFC 0037 §4, §5). People (`people_review`) and places (`places_review`) have their own queues; the
sitting, `logbook review KIND`, is one loop over all five (`logbook.commands.review`).

**The strongest-identifier rule.** An observed thing's identity is the strongest identifier its
observation carries, never the id a source gives one observation:

- **org**: the registered domain of a `mail/v1` address, a calendar attendee's address or a
  transcript participant's (a public mail provider, `policy/entities.json`, the owner's own domains
  and a service's own hosts, a calendar's rooms among them, name nobody's org), else the code-host
  org of a `browse/v1` url, a task's link or an act `sync github` wrote (its own link, else its
  `extra.repo` on github.com: `github.com/nordmann-verft`; the owner's own account is the owner's),
  else a group chat's name folded (`message/v1`, `chat.type` group), else a `transaction/v1` merchant
  folded when it recurs on `merchant_min_lines` (3) lines or more. The row's `hint` is the guess at
  what it is — `company` for a domain, `personal` for a family's domain (every name seen on it is a
  given name and a surname whose given name is the address's own, `kari@` "Kari Nordmann", and
  they share the surname its first label spells) or a person's own code-host account (a `handle`
  ref `github:<login>` a resolution names), `community` for a code-host org or a group, `brand` for
  a merchant — for ranking only, never written to a line. `org_sightings` is one line's orgs, the
  walk the orgs reader (`logbook.contrib.orgs`) shares to find what touches a named org.
- **idea**: a `sync notion` page's root (the topmost page above it the record has a line for; a database
  row is its own root, RFC 0037 §4.3 as amended on 16 October 2026), as `page` `notion:<id>`, else a
  code-host repository (`host/owner/name`) of a url, of a task's own `url` or links, or of an act `sync
  github` wrote, else a task's or a transcript's title, its words folded and sorted, when it recurs on
  `title_min_lines` (2) lines of two sources or more. A transcript's summary is never read. A relations
  line (`sync notion --relations-backfill`) links rows and touches none; a bot's line (its actor a bot)
  or an agent's (`extra.machine`) is never a touch and shows nobody, and an agent on a call is no
  participant (`machine_line`). `idea_sightings` is one line's ideas, the walk the ideas reader
  (`logbook.contrib.ideas`) shares to find what touches a named idea.
- **asset**: a `location/v1` subject `assets.json` does not name (its MMSI or icao24 from the
  instrument's `extra` when the line has one), else an aircraft registration on
  `registration_min_flights` (3) standing flights or more that the registry does not hold.

**The table.** The observed rows are the org, idea and asset rows of `observed_entities` in the
index (`Index.store_observed`), stamped per kind with the head, the zone and the digests of
`places.json`, `assets.json` and `policy/entities.json`, served while the stamp holds, built again
when it does not; the orgs' sightings under it are kept beside the index each kind in file order
(`_org_folds`), so a new head reads only the lines appended since. Nothing is stored in the record.

**The queue.** Each observed thing not yet placed is proposed against each canonical entity of its
kind with evidence, a plain sum as `people review`'s: for an org the same domain (+60), the same
code-host org (+50), the same name (+20, +5 a further source up to +10; the words in any order,
`AS`, `ASA`, `Ltd`, `Inc`, `GmbH`, `AB` aside, two words or one of six letters or more), the org's
people seen on its lines (+10 each, up to +30) and the same days (+2 a day, up to +20); for an idea
the same page (+60), the same repository (+50), the same title (+20 …, the articles aside, one word
of six letters suffices), its people (+10 …) and the same weeks (+5 a week, up to +20); for an asset
the same identifier (+60), the same registration spelled another way (+50), the same name (+20).
Days, weeks and people alone never propose. An observed domain, code-host org, page, repository or
title that matches nothing, and an observed asset, is proposed as a **new** entity, after the
matches. A pair the owner rejected is never proposed again.

**The owner's say.** `--accept` writes one `entity/v1` line binding the observed identifiers to the
entity — minting a UUIDv7 for a new org or idea after looking its dedupe key up, so a key that
already resolves reuses its id; for a new asset, the `assets.json` entry as `assets add` writes it
first. `--name N "…"` accepts a new one under the owner's name. `--reject` writes one
`entity-review/v1` line. Every write goes through `Logbook.append`; nothing here opens a socket.

**Ideas from calls** (`call_ideas`). After the observed proposals, the idea queue lists what the calls'
syntheses proposed (`transcript synthesize`, `extra.ideas`): a new idea, or a refinement of a named
one by its entity id, each with the transcript's id and the utterances as evidence. Only a standing
synthesis the `dream` entry allows today, of a transcript that stands and is a call (`NOT_CALLS`, a
home video's soundtrack, never), is read; a candidate carries the higher tier of the call and its
synthesis. They are candidates and nothing more: `--accept` (or `--name` for a new one) writes one
`entity/v1` line, a new idea minted as any other, or, for a refinement, a line of the idea's own id.
That line is tier 2 and never carries what a tier-3 line said: of a tier-3 call (a Granola call) it
holds the name accepted and nothing else; of a call at tier 2 or below it adds the call as evidence
and the words, `extra.pitch` for a new idea and `extra.refines` for a refinement;
`--reject` writes the `entity-review/v1` no, on the idea's title for a new one and on the transcript
(`line`) against the idea for a refinement, so it is never proposed again. A candidate an `entity/v1`
line already answered (`extra.call`) is not proposed again."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any, NoReturn
from urllib.parse import urlsplit

from ..core import assets, day_start, drafts, flights, goals, kept, machine, policy, present, resolve, stays
from ..core.chain import Line
from ..core.index import Index
from ..core.store import RETRACTION, HeadMoved, Logbook, now_utc, retractions, uuid7
from ..core.transcripts import NOT_CALLS  # a home video's soundtrack (RFC 0040): it proposes no idea
from . import entities
from .entities import ASSET, IDEA, ORG, Ref

KINDS = (ORG, IDEA, ASSET)
TRANSCRIPT = "transcript"
SYNTHESIS = "synthesis"  # the source an idea from a call is seen by, in the queue only
TABLE_VERSION = "3"  # 2: transcripts, `sync github` acts, service hosts, the given name; 3: ideas (#292)
SAMPLES = 3  # line ids kept per observed thing, as evidence
ORGS_KEPT, ORGS_KEPT_VERSION = "orgs-observed.json", 1  # each kind's orgs, kept beside the index
ORG_OVERLAY = (RETRACTION, "resolution")  # what changes who is who: every line read again
IDEA_LINES_KEPT, IDEA_LINES_VERSION = "idea-lines.json", 1  # which lines name an idea, by their place
NOTION = "notion"  # the source `sync notion` writes
RELATIONS = "relations"  # the action of a `sync notion --relations-backfill` line: it links, never touches
BOT = "bot"  # an actor `sync notion` types `bot` and `sync github` `Bot`: an integration, an app
INSTRUMENTS = {"ais": "yacht", "adsb": "aircraft"}  # a subject's source → the kind it is
DOMAIN, REPO, NAME, PEOPLE, TOGETHER = 60, 50, 20, 10, 2
PAGE, WEEK = 60, 5
SAME_ID, SPELLED = 60, 50
NAME_SOURCE, NAME_SOURCE_CAP, PEOPLE_CAP, TOGETHER_CAP, WEEK_CAP = 5, 10, 30, 20, 20
LEGAL_FORMS = entities.LEGAL_FORMS
LONG_WORD = 6
HINT_ORDER = {"company": 0, "community": 1, "brand": 2, "personal": 3, None: 4}
NOT_ORGS = frozenset(  # first path segments of a code host that are its own pages, not an org
    {"settings", "notifications", "explore", "marketplace", "login", "search", "topics", "features",
     "pulls", "issues", "new", "about", "pricing", "sponsors", "orgs", "users", "apps", "site",
     "logout", "join", "enterprise", "collections", "trending", "codespaces", "account", "dashboard"}
)  # fmt: skip
# the hosts a service sends from or books with, a calendar's rooms and a code host's relay among them:
# an address there names the service, never a company the owner deals with
SERVICE_HOSTS = ("resource.calendar.google.com", "group.calendar.google.com", "users.noreply.github.com")
GITHUB, GITHUB_HOST = "github", "github.com"  # the source `sync github` writes, and the host it reads
GITHUB_ACTS = ("commit", "pull", "issue", "review", "comment")  # what an act's `extra` links to
ORG_KINDS = ("mail", "event", "transcript", "browse", "task", "message", "transaction")  # an org's lines
IDEA_KINDS = ("event", "browse", "task", "transcript")  # an idea's lines
BLANK = "____"
EN_DASH = "\u2013"
NOT_EQUAL = "\u2260"
WRITABLE = {
    ORG: ("domain", "repo", "group", "merchant"),
    IDEA: ("page", "repo", "title"),
    ASSET: ("mmsi", "icao24", "registration"),
}
NOUNS = {ORG: ("org", "orgs"), IDEA: ("idea", "ideas"), ASSET: ("asset", "assets")}


class ReviewError(ValueError):
    """A number, a score, a name or a proposal the record cannot act on; nothing was written."""


# -- observed ---------------------------------------------------------------------------------------------


@dataclass
class Observed:
    """One observed org, idea or asset: everything one strongest identifier was seen as."""

    kind: str
    key: Ref
    hint: str | None = None
    labels: Counter[str] = field(default_factory=Counter)
    identifiers: dict[Ref, int] = field(default_factory=dict)
    sources: Counter[str] = field(default_factory=Counter)
    kinds: Counter[str] = field(default_factory=Counter)
    days: set[str] = field(default_factory=set)
    first: str | None = None
    last: str | None = None
    lines: int = 0
    tier: int = 0
    samples: list[tuple[str, int]] = field(default_factory=list)  # (line id, its tier)
    people: set[str] = field(default_factory=set)  # canonical persons seen on its lines
    entity: str | None = None  # the canonical entity it resolves to, when the record binds it

    def add(
        self, source: str, kind: str, day: str, line_id: str, tier: int, label: str | None = None
    ) -> None:
        if label:
            self.labels[label] += 1
        self.sources[source] += 1
        self.kinds[kind] += 1
        self.days.add(day)
        self.first = day if self.first is None else min(self.first, day)
        self.last = day if self.last is None else max(self.last, day)
        self.lines += 1
        self.tier = max(self.tier, tier)
        if len(self.samples) < SAMPLES:
            self.samples.append((line_id, tier))

    def copy(self) -> Observed:
        return Observed.from_row(self.kind, self.row())

    def merge(self, other: Observed) -> None:
        """`other`'s lines added after this one's, as one reading of both adds them."""
        self.labels.update(other.labels)
        for ref, n in other.identifiers.items():
            self.saw(ref, n)
        self.sources.update(other.sources)
        self.kinds.update(other.kinds)
        self.days |= other.days
        for day in (other.first, other.last):
            if day is not None:
                self.first = day if self.first is None else min(self.first, day)
                self.last = day if self.last is None else max(self.last, day)
        self.lines += other.lines
        self.tier = max(self.tier, other.tier)
        self.samples = [*self.samples, *other.samples][:SAMPLES]
        self.people |= other.people

    def saw(self, ref: Ref, times: int = 1) -> None:
        self.identifiers[ref] = self.identifiers.get(ref, 0) + times

    @property
    def name(self) -> str:
        """The name shown most, the first written when tied; the identifier when none."""
        return self.labels.most_common(1)[0][0] if self.labels else self.key[1]

    @property
    def writable(self) -> list[Ref]:
        """The identifiers an `entity/v1` line can bind for this kind, as written, the key first."""
        found = [self.key] if self.key[0] in WRITABLE[self.kind] else []
        found += [ref for ref in self.identifiers if ref[0] in WRITABLE[self.kind] and ref not in found]
        return found

    @property
    def weeks(self) -> set[str]:
        return {f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}" for d in map(date.fromisoformat, self.days)}

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "key": {"kind": self.key[0], "value": self.key[1]},
            "name": self.name,
            "hint": self.hint,
            "labels": dict(self.labels),
            "identifiers": [{"kind": k, "value": v, "lines": n} for (k, v), n in self.identifiers.items()],
            "sources": dict(self.sources),
            "kinds": dict(self.kinds),
            "days": len(self.days),
            "first": self.first,
            "last": self.last,
            "lines": self.lines,
            "tier": self.tier,
            "people": sorted(self.people),
            "entity": self.entity,
        }

    def row(self) -> dict[str, Any]:
        """The row of `observed_entities` (`Index.store_observed`)."""
        return {
            "key_kind": self.key[0],
            "key_value": self.key[1],
            "name": self.name,
            "entity": self.entity,
            "hint": self.hint,
            "labels": json.dumps(dict(self.labels), ensure_ascii=False),
            "refs": json.dumps([[k, v, n] for (k, v), n in self.identifiers.items()], ensure_ascii=False),
            "sources": json.dumps(dict(self.sources), ensure_ascii=False),
            "kinds": json.dumps(dict(self.kinds), ensure_ascii=False),
            "days": json.dumps(sorted(self.days)),
            "first": self.first,
            "last": self.last,
            "count": self.lines,
            "tier": self.tier,
            "samples": json.dumps([[i, t] for i, t in self.samples]),
            "people": json.dumps(sorted(self.people)),
        }

    @classmethod
    def from_row(cls, kind: str, row: Mapping[str, Any]) -> Observed:
        return cls(
            kind,
            (str(row["key_kind"]), str(row["key_value"])),
            None if row["hint"] is None else str(row["hint"]),
            Counter(json.loads(row["labels"])),
            {(str(k), str(v)): int(n) for k, v, n in json.loads(row["refs"])},
            Counter(json.loads(row["sources"])),
            Counter(json.loads(row["kinds"])),
            set(json.loads(row["days"])),
            row["first"],
            row["last"],
            int(row["count"]),
            int(row["tier"]),
            [(str(i), int(t)) for i, t in json.loads(row["samples"])],
            set(json.loads(row["people"])),
            None if row["entity"] is None else str(row["entity"]),
        )


def observed(lb: Logbook, kind: str) -> list[Observed]:
    """Every observed thing of `kind` (org, idea, asset) from the index's table: served while its
    stamp holds, built from the lines and stored otherwise. Writes nothing to the record."""
    if kind not in KINDS:
        raise ValueError(f"not a kind this queue reads: {kind!r}")
    with lb.index() as idx:
        stamp = _stamp(lb, kind)
        if idx.observed_stamp(kind) == stamp:
            return [Observed.from_row(kind, row) for row in idx.observed(kind)]
        found = build(lb, idx, kind)
        idx.store_observed(kind, [o.row() for o in found], stamp)
        return found


def _stamp(lb: Logbook, kind: str) -> dict[str, str]:
    meta = lb.meta

    def digest(path: Any) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            return ""

    return {
        "head": str(meta["head"]),
        "timezone": str(meta["timezone"]),
        "version": TABLE_VERSION,
        "kind": kind,
        "settings": digest(entities.settings_path(lb.root)),
        "assets": digest(assets.assets_path(lb.root)),
        "owner": digest(policy.owner_path(lb.root)),
    }


@dataclass
class Context:
    """What every builder needs: the day of a line, the people the record resolves, the owner."""

    days: day_start.DayStart
    identities: Mapping[Ref, resolve.Identity]
    owner: present.Owner
    owner_domains: frozenset[str]
    settings: entities.Settings
    retracted: frozenset[str]
    labels: Mapping[str, str]  # a person's label folded → their entity, for a name a source shows
    owner_logins: frozenset[str] = frozenset()  # the owner's code-host accounts (`github:<login>` handles)

    def day(self, line: Line) -> str | None:
        at = stays.instant(line.get("at"))
        return None if at is None else self.days.day(at).isoformat()

    def person(self, ref: Ref | None) -> str | None:
        if ref is None:
            return None
        entity, _label = present.resolve_ref(ref, self.identities)
        return None if entity is None or entity in self.owner.entities else entity

    def standing(self, idx: Index, kind: str, source: str | None = None) -> Iterator[Line]:
        """The standing lines of `kind` (of `source` alone when given: the index cuts it), in file order."""
        superseded = idx.superseded(kind)
        for line in idx.of_kind(kind, source=source):
            line_id = str(line.get("id"))
            if line_id not in self.retracted and line_id not in superseded:
                yield line


def context(lb: Logbook, idx: Index) -> Context:
    """What reading the record's observations needs: its day, its people, its owner, its settings."""
    meta = lb.meta
    marks, resolutions = idx.retractions(), idx.resolutions()
    identities = resolve.identities_from([*marks, *resolutions])
    owner = present.owner_of(
        str(meta.get("owner_id") or ""),
        [str(e) for e in meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    settings = entities.read_settings(lb.root)
    domains = {
        d
        for ref in owner.refs
        if ref[0] == "email" and "@" in ref[1]
        if (d := entities.registered_domain(ref[1].rsplit("@", 1)[1], settings.public_suffixes))
    }
    people_labels: dict[str, str] = {}
    for who in identities.values():
        if who.entity and who.label and who.type in present.PERSON_TYPES and who.entity not in owner.entities:
            people_labels.setdefault(entities.fold(who.label), who.entity)
    return Context(
        day_start.of(meta),
        identities,
        owner,
        frozenset(domains),
        settings,
        frozenset(retractions(marks)),
        people_labels,
        frozenset(
            value.removeprefix(f"{GITHUB}:")
            for kind, value in owner.refs
            if kind == "handle" and (value.startswith(f"{GITHUB}:") or ":" not in value)
        ),
    )


def build(lb: Logbook, idx: Index, kind: str) -> list[Observed]:
    """The pure read: every observed thing of `kind` from the standing lines, keyed by the strongest
    identifier, the owner's own left out, each placed when the record binds one of its identifiers."""
    ctx = context(lb, idx)
    found = {ORG: _orgs, IDEA: _ideas, ASSET: _assets}[kind](lb, idx, ctx)
    marks, resolutions = idx.retractions(), idx.resolutions()
    bound = entities.bindings([*marks, *resolutions, *idx.by_kind(entities.ENTITY)])
    for o in found:
        o.entity = next(
            (bound[ref][1] for ref in o.writable if ref in bound and bound[ref][0] == kind),
            None,
        )
    if kind == ASSET:
        registered = entities.registry(lb.root)
        for o in found:
            if o.entity is None:
                o.entity = next(
                    (
                        e.id
                        for (k, _id), e in registered.items()
                        if k == ASSET and any(ref in e.refs for ref in o.writable)
                    ),
                    None,
                )
    return sorted(found, key=lambda o: o.key)


@dataclass(frozen=True)
class Sighting:
    """One org on one line: its strongest identifier, the hint that goes with it, the name the line
    gives it (a sender's display name, a group's, a code-host org's segment, a merchant string), the
    canonical person the line shows at it, and for a domain the local part of the address the name
    came with (for the family's hint)."""

    key: Ref
    hint: str
    label: str | None = None
    person: str | None = None
    local: str | None = None


def org_sightings(kind: str, line: Line, ctx: Context) -> list[Sighting]:
    """The orgs one standing line names, source-native, one per address or link as the line holds
    them (a mail to two people at one domain names it twice): the domains of its addresses (`mail`,
    `event`, `transcript`), the code-host orgs of its links (`browse`, `task`, an act `sync github`
    wrote), a group chat (`message`), a merchant (`transaction`, every time: the threshold is the
    queue's). The owner's own are left out; nothing is looked up."""
    payload = line.get("payload") or {}
    found: list[Sighting] = []
    if kind in ("mail", "event", "transcript"):
        for address, name, person in _addresses(kind, payload, ctx):
            domain = _domain_of(address, ctx)
            if domain is not None:
                local = address.rsplit("@", 1)[0].split(".")[0] if name else None
                found.append(Sighting(("domain", domain), "company", name, person, local))
    if kind in ("browse", "task") or (kind == "event" and github_act(line)):
        urls = _github_urls(payload, ctx.settings) if kind == "event" else _urls(kind, payload)
        for url in urls:
            org = _code_org(url, ctx.settings)
            if org is None:
                continue
            host, login = org.split("/", 1)
            if login in ctx.owner_logins:
                continue  # the owner's own account: the owner, never an org
            personal = host == GITHUB_HOST and ctx.person(("handle", f"{GITHUB}:{login}")) is not None
            found.append(Sighting(("repo", org), "personal" if personal else "community", login))
    if kind == "message":
        chat = payload.get("chat")
        if isinstance(chat, dict) and chat.get("type") == "group" and _text(chat.get("name")):
            person = None if payload.get("from_me") is True else ctx.person(_ref(payload.get("sender")))
            name = " ".join(str(chat["name"]).split())
            found.append(Sighting(("group", entities.fold(name)), "community", name, person))
    if kind == "transaction":
        merchant = payload.get("merchant")
        if _text(merchant):
            name = " ".join(str(merchant).split())
            found.append(Sighting(("merchant", entities.fold(name)), "brand", name))
    return found


def _orgs(lb: Logbook, idx: Index, ctx: Context) -> list[Observed]:
    """Every org the standing lines name, each kind's lines in file order and the kinds in
    `ORG_KINDS`'s; a merchant once it recurs (`merchant_min_lines`), a family's domain `personal`.
    Each kind's sightings are kept beside the index (`_OrgFold`, `ORGS_KEPT`) and read on from where
    they stopped while that reads the same (`kept.read_on`)."""
    merged: dict[Ref, Observed] = {}
    names: dict[Ref, list[tuple[str, str]]] = {}
    for fold in _org_folds(lb, idx, ctx):
        for key, o in fold.found.items():
            if key in merged:
                merged[key].merge(o)
            else:
                merged[key] = o.copy()
        for key, spelled in fold.names.items():
            names.setdefault(key, []).extend(spelled)
    found = {k: o for k, o in merged.items() if k[0] != "merchant"}
    found.update(
        {k: o for k, o in merged.items() if k[0] == "merchant" and o.lines >= ctx.settings.merchant_min_lines}
    )
    for o in found.values():
        if o.key[0] == "domain" and _family(o, names.get(o.key, [])):
            o.hint = "personal"
    return list(found.values())


@dataclass
class _OrgFold:
    """The orgs the standing lines of one kind name, in file order: each org as its lines add it up,
    and the display names of each domain with their address's local part (for the family's hint)."""

    kind: str
    found: dict[Ref, Observed] = field(default_factory=dict)
    names: dict[Ref, list[tuple[str, str]]] = field(default_factory=dict)

    def take(self, line: Line, ctx: Context) -> None:
        day = ctx.day(line)
        if day is None:
            return
        for s in org_sightings(self.kind, line, ctx):
            o = self.found.setdefault(s.key, Observed(ORG, s.key, s.hint))
            o.add(
                str(line.get("source") or ""),
                str(line.get("kind")),
                day,
                str(line["id"]),
                int(line.get("tier", 0)),
                s.label,
            )
            o.saw(s.key)
            if s.person is not None:
                o.people.add(s.person)
            if s.label is not None and s.local is not None:
                self.names.setdefault(s.key, []).append((s.label, s.local))

    def to_json(self) -> dict[str, Any]:
        return {
            "found": [o.row() for o in self.found.values()],
            "names": [[list(key), [list(n) for n in found]] for key, found in self.names.items()],
        }

    @classmethod
    def from_json(cls, kind: str, data: Mapping[str, Any]) -> _OrgFold:
        found = [Observed.from_row(ORG, row) for row in data["found"]]
        return cls(
            kind,
            {o.key: o for o in found},
            {(str(k), str(v)): [(str(a), str(b)) for a, b in names] for (k, v), names in data["names"]},
        )


def _org_folds(lb: Logbook, idx: Index, ctx: Context) -> list[_OrgFold]:
    """Each kind of `ORG_KINDS`'s fold, read on from the kept ones when that reads the same as every
    line (`kept.read_on`: no retraction or resolution since, which change who is who, no line
    superseding another, none into an earlier month), else read from every line; kept again."""
    path = kept.path(lb, ORGS_KEPT)
    stamp = kept.stamp(lb, str(ORGS_KEPT_VERSION), kept.code_digest(__file__, entities.__file__))
    seq, head = idx.indexed()
    held = kept.load(path)
    folds: list[_OrgFold] | None = None
    if held is not None and held.get("version") == ORGS_KEPT_VERSION and held.get("stamp") == stamp:
        files = {str(k): str(v) for k, v in (held.get("files") or {}).items()}
        if set(files) == set(ORG_KINDS) and kept.read_on(idx, held, files, ORG_OVERLAY):
            try:
                folds = [_OrgFold.from_json(kind, held["folds"][kind]) for kind in ORG_KINDS]
            except (KeyError, TypeError, ValueError):
                folds = None
    since = int(held["seq"]) if folds is not None and held is not None else None
    if folds is None:
        folds = [_OrgFold(kind) for kind in ORG_KINDS]
    for fold in folds:
        superseded = idx.superseded(fold.kind)
        for line in idx.of_kind(fold.kind, after_seq=since):
            line_id = str(line.get("id"))
            if (
                int(line.get("seq") or 0) <= seq
                and line_id not in ctx.retracted
                and line_id not in superseded
            ):
                fold.take(line, ctx)
    kept.save(
        path,
        {
            "version": ORGS_KEPT_VERSION,
            "stamp": stamp,
            "seq": seq,
            "head": head,
            "files": {kind: idx.last_file(kind) for kind in ORG_KINDS},
            "folds": {fold.kind: fold.to_json() for fold in folds},
        },
    )
    return folds


def _addresses(
    kind: str, payload: Mapping[str, Any], ctx: Context
) -> Iterator[tuple[str, str | None, str | None]]:
    """(address, the display name when it is the sender's, the person it resolves to) of a mail's
    headers, a calendar entry's attendees who did not decline and its organizer, or a transcript's
    participants (an agent taking notes is nobody's: `machine.is_machine_participant`)."""
    if kind == "mail":
        for header in ("from", "to", "cc", "bcc"):
            value = payload.get(header)
            for address in value if isinstance(value, list) else [value]:
                if isinstance(address, dict) and _text(address.get("email")):
                    email = str(address["email"]).strip().casefold()
                    name = (
                        " ".join(str(address["name"]).split())
                        if header == "from" and _text(address.get("name"))
                        else None
                    )
                    yield email, name, ctx.person(("email", email))
        return
    if kind == "transcript":
        participants = payload.get("participants")
        for participant in participants if isinstance(participants, list) else []:
            if not isinstance(participant, dict) or machine.is_machine_participant(participant):
                continue
            if _text(participant.get("email")):
                email = str(participant["email"]).strip().casefold()
                yield email, None, ctx.person(("email", email))
        return
    attendees = payload.get("attendees")
    for attendee in attendees if isinstance(attendees, list) else []:
        if not isinstance(attendee, dict) or attendee.get("response") == "declined":
            continue
        ref = _ref(attendee.get("ref"))
        if ref is not None and ref[0] == "email":
            yield ref[1].casefold(), None, ctx.person(ref)
    organizer = _ref(payload.get("organizer"))
    if organizer is not None and organizer[0] == "email":
        yield organizer[1].casefold(), None, ctx.person(organizer)


def _domain_of(address: str, ctx: Context) -> str | None:
    if "@" not in address or ("email", address) in ctx.owner.refs:
        return None
    host = address.rsplit("@", 1)[1].strip().strip(".").lower()
    if any(host == service or host.endswith("." + service) for service in SERVICE_HOSTS):
        return None  # a room, a list, a code host's relay: the service's, nobody's org
    domain = entities.registered_domain(host, ctx.settings.public_suffixes)
    if domain is None or domain in ctx.settings.public_mail_providers or domain in ctx.owner_domains:
        return None
    return domain


def _family(o: Observed, names: Sequence[tuple[str, str]]) -> bool:
    """A family's domain: every name seen on it is a person's, a given name and a surname, the given
    name the address's own (`kari@` "Kari Nordmann"; a newsletter `news@` "Nordmann Nytt" is not),
    they share the surname, and the domain's first label spells it (`nordmann.example.org`)."""
    seen = [(entities.words(label), local) for label, local in names]
    if not seen or any(len(found) < 2 or found[0] != entities.fold(local) for found, local in seen):
        return False
    surnames = {found[-1] for found, _local in seen}
    return len(surnames) == 1 and next(iter(surnames)) == o.key[1].split(".")[0].replace("-", "")


def github_act(line: Line) -> bool:
    """A line `sync github` (or `add github-export`) wrote: an act on a repository."""
    calendar = (line.get("payload") or {}).get("calendar")
    return line.get("source") == GITHUB or (isinstance(calendar, dict) and calendar.get("id") == GITHUB)


def _github_urls(payload: Mapping[str, Any], settings: entities.Settings) -> list[str]:
    """Where an act of `sync github` was: its own link (a commit's, a pull request's, an issue's, a
    review's, a comment's: the host it was read from), else its `extra.repo` on github.com."""
    extra = payload.get("extra")
    if not isinstance(extra, dict):
        return []
    for name in GITHUB_ACTS:
        act = extra.get(name)
        if isinstance(act, dict) and _text(act.get("url")):
            return [str(act["url"])]
    repo = extra.get("repo")
    if _text(repo) and GITHUB_HOST in settings.code_hosts:
        return [f"https://{GITHUB_HOST}/{str(repo).strip().strip('/')}"]
    return []


def _urls(kind: str, payload: Mapping[str, Any]) -> list[str]:
    if kind == "browse":
        url = payload.get("url")
        return [str(url)] if _text(url) else []
    extra = payload.get("extra")
    links = extra.get("links") if isinstance(extra, dict) else None
    return (
        [str(link["url"]) for link in links if isinstance(link, dict) and _text(link.get("url"))]
        if isinstance(links, list)
        else []
    )


def _code_path(url: str, settings: entities.Settings) -> list[str] | None:
    """The path segments of a url on a code host, the host first, lower-cased; None elsewhere."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if host not in settings.code_hosts:
        return None
    segments = [s for s in parts.path.lower().split("/") if s]
    if segments and segments[0] in ("orgs", "users"):
        segments = segments[1:]
    if not segments or segments[0] in NOT_ORGS:
        return None
    return [host, *segments]


def _code_org(url: str, settings: entities.Settings) -> str | None:
    path = _code_path(url, settings)
    return None if path is None else "/".join(path[:2])


def _code_repo(url: str, settings: entities.Settings) -> str | None:
    path = _code_path(url, settings)
    return None if path is None or len(path) < 3 else "/".join(path[:3]).removesuffix(".git")


@dataclass
class NotionPage:
    """One Notion page as the record's lines tell it, the latest line deciding (by its instant, then
    its seq): the page above it when its parent is a page, the database it is a row of (`extra.database`,
    which `sync notion` writes on every line of a row, else a parent that is a database or a later
    API's data source), its title, the titles above it, its private link and a row's properties as its
    latest line holding them says them. Every standing `sync notion` line shapes it, whoever acted."""

    id: str
    above: str | None = None
    database: str | None = None
    title: str | None = None
    path: tuple[str, ...] = ()
    url: str | None = None
    properties: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class NotionTree:
    """The Notion pages the record holds lines of, by id: what an idea's root is, and whether a root
    may be proposed as one (`rows`, the select and the option that make a row an idea)."""

    pages: Mapping[str, NotionPage]
    rows: tuple[str, str] = entities.IDEA_ROWS

    def root(self, page_id: str) -> str:
        """The idea's page of `page_id`: the topmost page above it the record holds, walking up while
        the parent is a page. A database row is its own root (RFC 0037 §4.3, amended 2026-10-16): the
        walk stops at a row, so a row is never folded into the page above its database, and a page under
        a row is the row's. A page the record holds no line of, or a cycle, stops the walk too."""
        seen = {page_id}
        page = self.pages.get(page_id)
        while (
            page is not None and page.database is None and page.above is not None and page.above in self.pages
        ):
            if page.above in seen:
                break
            seen.add(page.above)
            page_id = page.above
            page = self.pages[page_id]
        return page_id

    def candidate(self, root: str) -> bool:
        """Whether the root `root` may be proposed as an idea: a page that is no row, as always; a
        database row only when its select `rows` names (`Type`) says the option (`Idea`), case
        aside, as the latest line holding the row's properties says it (the owner's decision of 14
        October 2026). A row whose lines say no such value is no idea's."""
        page = self.pages.get(root)
        if page is None or page.database is None:
            return True
        name, option = (entities.fold(word) for word in self.rows)
        value = next((v for k, v in (page.properties or {}).items() if entities.fold(str(k)) == name), None)
        return isinstance(value, str) and entities.fold(value) == option

    def title(self, page_id: str) -> str | None:
        page = self.pages.get(page_id)
        return None if page is None else page.title


def notion_tree(idx: Index, ctx: Context) -> NotionTree:
    """Every page the standing `sync notion` lines name, as its latest line says it."""
    lines = list(ctx.standing(idx, "event", NOTION))  # the record's other events are never read
    lines.sort(key=lambda line: (_instant(line), int(line.get("seq") or 0)))
    pages: dict[str, NotionPage] = {}
    for line in lines:
        payload = line.get("payload") or {}
        extra = payload.get("extra")
        page = extra.get("page") if isinstance(extra, dict) else None
        if not isinstance(extra, dict) or not isinstance(page, dict) or not _text(page.get("id")):
            continue
        found = pages.setdefault(str(page["id"]), NotionPage(str(page["id"])))
        parent = extra.get("parent")
        parent = parent if isinstance(parent, dict) and _text(parent.get("id")) else {}
        database = extra.get("database")
        found.database = (
            str(database["id"])
            if isinstance(database, dict) and _text(database.get("id"))
            else str(parent["id"])
            if parent.get("type") in ("database", "data_source")
            else None
        )
        found.above = str(parent["id"]) if parent.get("type") == "page" else None
        if _text(payload.get("title")):
            found.title = str(payload["title"])
        path = extra.get("path")
        if isinstance(path, list):
            found.path = tuple(str(p) for p in path if isinstance(p, str))
        if _text(page.get("url")):
            found.url = str(page["url"])
        if isinstance(extra.get("properties"), dict):
            found.properties = extra["properties"]
    return NotionTree(pages, ctx.settings.idea_rows)


def _instant(line: Line) -> datetime:
    return stays.instant(line.get("at")) or datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class IdeaSighting:
    """One idea on one line: its strongest identifier (`key`: a Notion root page, a repository, a
    title's words), the identifier as the line wrote it (`seen`: the page itself, the repository,
    the title), and the name the line gives it."""

    key: Ref
    seen: Ref
    label: str | None
    candidate: bool = True  # whether the queue may propose it: a Notion row that is no idea's may not


def machine_line(line: Line) -> bool:
    """Whether a line is a bot's or an agent's: its actor is a bot (`extra.actor.type`, `bot` as `sync
    notion` writes it, `Bot` as `sync github` does) or its words an agent's (`extra.machine`,
    `logbook.core.machine`). Such a line is never a touch of an idea, never shows a person on one and
    adds no words to one (the owner's decision of 14 October 2026). An act the owner made through a
    coding agent under their own account (`sync github`'s `extra.agent`) is the owner's, and is one."""
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    actor = extra.get("actor") if isinstance(extra, dict) else None
    kind = actor.get("type") if isinstance(actor, dict) else None
    return (isinstance(kind, str) and kind.strip().casefold() == BOT) or machine.is_machine(payload)


def idea_sightings(kind: str, line: Line, ctx: Context, tree: NotionTree) -> list[IdeaSighting]:
    """The ideas one standing line names, source-native, one per page, repository link or title as
    the line holds them: a `sync notion` line's page under its root, the repository of an act `sync
    github` wrote (its own link, else its `extra.repo` on github.com), the code-host repositories of
    a url or of a task's own `url` and links, a task's or a transcript's title (when no repository
    names its task; the threshold is the queue's). A relations line names none, nor does a bot's or an
    agent's line (`machine_line`). Nothing is looked up; the walk `review idea` observes and the ideas
    reader (`logbook.contrib.ideas`) finds touches by."""
    payload = line.get("payload") or {}
    found: list[IdeaSighting] = []
    if machine_line(line):
        return found  # a bot's or an agent's line touches no idea
    if kind == "event" and github_act(line):
        for url in _github_urls(payload, ctx.settings):
            repo = _code_repo(url, ctx.settings)
            if repo is not None:
                found.append(IdeaSighting(("repo", repo), ("repo", repo), repo.split("/", 1)[1]))
        return found
    if kind == "event":
        extra = payload.get("extra")
        extra = extra if isinstance(extra, dict) else {}
        page = extra.get("page")
        if line.get("source") != NOTION or not isinstance(page, dict) or not _text(page.get("id")):
            return []
        if extra.get("action") == RELATIONS:
            return []  # a relations line says which rows a row links to: it touches nothing
        top = tree.root(str(page["id"]))
        return [
            IdeaSighting(
                ("page", f"notion:{top}"),
                ("page", f"notion:{page['id']}"),
                tree.title(top),
                tree.candidate(top),
            )
        ]
    if kind in ("browse", "task"):
        for url in _idea_urls(kind, payload):
            repo = _code_repo(url, ctx.settings)
            if repo is not None:
                found.append(IdeaSighting(("repo", repo), ("repo", repo), repo.split("/", 1)[1]))
    title = payload.get("title")
    if kind in ("task", "transcript") and not found and _text(title):
        folded = entities.title_key(str(title))
        if folded:
            found.append(IdeaSighting(("title", folded), ("title", folded), " ".join(str(title).split())))
    return found


def _idea_urls(kind: str, payload: Mapping[str, Any]) -> list[str]:
    """A url's, or a task's links and its own `url` (task/v1: "a link the task carries")."""
    found = _urls(kind, payload)
    url = payload.get("url")
    if kind == "task" and _text(url) and str(url) not in found:
        found.insert(0, str(url))
    return found


def idea_people(kind: str, line: Line, ctx: Context) -> set[str]:
    """The canonical people one line shows on an idea, the owner aside: the person a `sync notion`
    line's actor names, a transcript's participants by their addresses. A bot's or an agent's line
    shows nobody, and an agent among a call's participants is nobody (`logbook.core.machine`)."""
    payload = line.get("payload") or {}
    found: set[str] = set()
    if machine_line(line):
        return found
    if kind == "event" and line.get("source") == NOTION:
        extra = payload.get("extra")
        actor = extra.get("actor") if isinstance(extra, dict) else None
        if isinstance(actor, dict) and _text(actor.get("name")):
            person = ctx.labels.get(entities.fold(str(actor["name"])))
            if person is not None:
                found.add(person)
    if kind == "transcript":
        for participant in payload.get("participants") or []:
            if machine.is_machine_participant(participant):
                continue
            if isinstance(participant, dict) and _text(participant.get("email")):
                person = ctx.person(("email", str(participant["email"]).strip().casefold()))
                if person is not None:
                    found.add(person)
    return found


def idea_lines(lb: Logbook, idx: Index, ctx: Context, tree: NotionTree) -> dict[str, list[Line]]:
    """The standing lines of each of `IDEA_KINDS` that name an idea (`idea_sightings` gives one), in
    file order: what the readers of ideas walk, since a line that names none adds nothing. Whether a
    line names one is the line's alone and the settings', never the Notion tree's (a page's line names
    its root, whichever it is) or who is who, so their places in the files are kept beside the index
    (`IDEA_LINES_KEPT`) and only the lines appended since are read to add to them, each where it
    stands; what stands, a retraction or a correction since among it, is read from the lines each
    time. A chain written again under them, other code or other settings reads every line."""
    path = kept.path(lb, IDEA_LINES_KEPT)
    stamp = kept.stamp(lb, str(IDEA_LINES_VERSION), kept.code_digest(__file__, entities.__file__))
    seq, head = idx.indexed()
    held = kept.load(path)
    places: dict[str, list[tuple[str, int]]] = {kind: [] for kind in IDEA_KINDS}
    since = 0
    ours = held is not None and held.get("version") == IDEA_LINES_VERSION and held.get("stamp") == stamp
    if held is not None and ours and kept.read_on(idx, held, {}, ()):
        try:
            places = {kind: [(str(f), int(o)) for f, o in held["places"][kind]] for kind in IDEA_KINDS}
            since = int(held["seq"])
        except (KeyError, TypeError, ValueError):
            places, since = {kind: [] for kind in IDEA_KINDS}, 0
    for kind in IDEA_KINDS:
        new = [
            (str(f), int(o))
            for f, o in idx.db.execute(
                "SELECT file, offset FROM lines WHERE kind = ? AND seq > ? AND seq <= ?"
                " ORDER BY file, offset",
                (kind, since, seq),
            )
        ]
        # where a line is, through no gate: what the readers are handed is read through it, below
        lines = Index.read(idx, new)
        named = [at for at, line in zip(new, lines, strict=True) if idea_sightings(kind, line, ctx, tree)]
        places[kind] = sorted({*places[kind], *named})
    kept.save(
        path,
        {
            "version": IDEA_LINES_VERSION,
            "stamp": stamp,
            "seq": seq,
            "head": head,
            "places": {kind: [list(at) for at in found] for kind, found in places.items()},
        },
    )
    out: dict[str, list[Line]] = {}
    for kind in IDEA_KINDS:
        superseded = idx.superseded(kind)
        out[kind] = [
            line
            for line in idx.read(places[kind])
            if str(line.get("id")) not in ctx.retracted and str(line.get("id")) not in superseded
        ]
    return out


def _ideas(lb: Logbook, idx: Index, ctx: Context) -> list[Observed]:
    tree = notion_tree(idx, ctx)
    found: dict[Ref, Observed] = {}
    titles: dict[Ref, Observed] = {}
    for kind, lines in idea_lines(lb, idx, ctx, tree).items():
        for line in lines:
            day = ctx.day(line)
            sightings = idea_sightings(kind, line, ctx, tree) if day is not None else []
            if day is None or not sightings:
                continue
            people = idea_people(kind, line, ctx)
            source = str(line.get("source") or "")
            for s in sightings:
                if not s.candidate:
                    continue  # a row of a Notion database whose `Type` is not `Idea`, or a page under one
                into = titles if s.key[0] == "title" else found
                o = into.setdefault(s.key, Observed(IDEA, s.key))
                o.add(source, kind, day, str(line["id"]), int(line.get("tier", 0)), s.label)
                o.saw(s.seen)
                o.people.update(people)
    found.update(
        {k: o for k, o in titles.items() if o.lines >= ctx.settings.title_min_lines and len(o.sources) >= 2}
    )
    return list(found.values())


def _assets(lb: Logbook, idx: Index, ctx: Context) -> list[Observed]:
    registered = entities.registry(lb.root)
    ids = {entity_id for (kind, entity_id) in registered if kind == ASSET}
    regs = {  # as the registry spells them: another spelling is proposed against the asset (+50)
        entities.fold(value)
        for (kind, _id), e in registered.items()
        if kind == ASSET
        for k, value in e.refs
        if k == "registration"
    }
    found: dict[Ref, Observed] = {}
    rows = idx.db.execute(  # the subjects the track carries, from the index's own columns
        "SELECT subject, source, count(*), min(day_local), max(day_local) FROM lines"
        " WHERE kind = 'location' AND subject IS NOT NULL GROUP BY subject, source ORDER BY subject, source"
    ).fetchall()
    for subject, source, count, first, last in rows:
        if str(subject) in ids:
            continue
        line = idx.last_fix(str(subject))
        extra = (line.get("payload") or {}).get("extra") if line is not None else None
        extra = extra if isinstance(extra, dict) else {}
        refs: list[Ref] = []
        if _text(extra.get("mmsi")):
            refs.append(("mmsi", str(extra["mmsi"])))
        if _text(extra.get("icao24")):
            refs.append(("icao24", str(extra["icao24"]).lower()))
        key = refs[0] if refs else ("subject", str(subject))
        o = found.setdefault(key, Observed(ASSET, key))
        o.labels[str(extra.get("ship_name") or extra.get("callsign") or subject).strip()] += int(count)
        o.sources[str(source)] += int(count)
        o.kinds["location"] += int(count)
        o.first = str(first) if o.first is None else min(o.first, str(first))
        o.last = str(last) if o.last is None else max(o.last, str(last))
        o.lines += int(count)
        o.tier = max(o.tier, int(line.get("tier", 1)) if line is not None else 1)
        if line is not None and len(o.samples) < SAMPLES:
            o.samples.append((str(line["id"]), int(line.get("tier", 1))))
        o.saw(("subject", str(subject)), int(count))
        for ref in refs:
            o.saw(ref, int(count))
    flown: dict[str, Observed] = {}
    for line in flights.standing(list(ctx.standing(idx, "flight"))).values():
        aircraft = (line.get("payload") or {}).get("aircraft")
        registration = aircraft.get("registration") if isinstance(aircraft, dict) else None
        day = ctx.day(line)
        if not _text(registration) or day is None or entities.fold(str(registration)) in regs:
            continue
        written = " ".join(str(registration).split())
        key_value = entities.registration_key(written)
        o = flown.setdefault(key_value, Observed(ASSET, ("registration", written)))
        o.add(
            str(line.get("source") or ""), "flight", day, str(line["id"]), int(line.get("tier", 0)), written
        )
        o.saw(("registration", written))
    for o in flown.values():
        if o.lines >= ctx.settings.registration_min_flights:
            found.setdefault(o.key, o)
    return list(found.values())


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, text = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(text, str) or not text.strip():
        return None
    return kind, text.strip()


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


# -- the queue ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Canonical:
    """One canonical entity as the queue weighs it: the entity, the days its identifiers were seen
    on, the people seen on them, and the sources that saw them."""

    entity: entities.Entity
    days: frozenset[str]
    people: frozenset[str]

    @property
    def id(self) -> str:
        return self.entity.id

    @property
    def label(self) -> str:
        return self.entity.label

    def to_json(self) -> dict[str, Any]:
        return {"id": self.entity.id, "name": self.entity.label, "key": self.entity.key}


@dataclass(frozen=True)
class Proposal:
    number: int
    id: str
    observed: Observed
    canonical: Canonical | None  # None: a new entity
    score: int | None  # None for a new entity
    evidence: tuple[str, ...]
    call: dict[str, Any] | None = None  # an idea a call's synthesis proposed (`call_ideas`)

    @property
    def tier(self) -> int:
        return entities.review_tier([self.observed.tier])

    @property
    def new(self) -> bool:
        return self.canonical is None

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "id": self.id,
            "score": self.score,
            "new": self.new,
            "evidence": list(self.evidence),
            "observed": self.observed.to_json(),
            "canonical": None if self.canonical is None else self.canonical.to_json(),
            "key": entities.key_of(self.observed.kind, self.observed.writable),
            "call": self.call,
        }


@dataclass(frozen=True)
class Report:
    kind: str
    proposals: list[Proposal]
    unplaced: list[Observed]
    placed: int
    canonicals: dict[str, Canonical]
    rejected: int
    head: str

    @property
    def tier(self) -> int | None:
        return max((p.tier for p in self.proposals), default=None)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "tier": self.tier,
            "observed": {"placed": self.placed, "unplaced": [o.to_json() for o in self.unplaced]},
            "rejected": self.rejected,
            "proposals": [p.to_json() for p in self.proposals],
        }


def read(lb: Logbook, kind: str) -> Report:
    """The queue of `kind` (org, idea, asset) at the record's head: the observed things through the
    index's table, the canonical ones through their lines and registries, the owner's noes through
    the standing `entity-review/v1` lines. Writes nothing to the record."""
    rows = observed(lb, kind)
    with lb.index() as idx:
        marks = idx.retractions()
        lines = [*marks, *idx.resolutions(), *idx.by_kind(entities.ENTITY)]
        noes = [r for r in entities.reviews([*marks, *idx.by_kind(entities.ENTITY_REVIEW)]) if r.kind == kind]
    known = entities.known(lines, lb.root)
    seen_days: dict[str, set[str]] = {}
    seen_people: dict[str, set[str]] = {}
    for o in rows:
        if o.entity is not None:
            seen_days.setdefault(o.entity, set()).update(o.days)
            seen_people.setdefault(o.entity, set()).update(o.people)
    canonicals = {
        e.id: Canonical(e, frozenset(seen_days.get(e.id, set())), frozenset(seen_people.get(e.id, set())))
        for (k, _id), e in sorted(known.items())
        if k == kind
    }
    unplaced = [o for o in rows if o.entity is None]
    proposals = propose(unplaced, canonicals, noes)
    if kind == IDEA:
        proposals += call_ideas(lb, canonicals, noes, len(proposals) + 1)
    placed = sum(1 for o in rows if o.entity is not None)
    return Report(kind, proposals, unplaced, placed, canonicals, len(noes), str(lb.meta["head"]))


def propose(
    unplaced: Sequence[Observed], canonicals: Mapping[str, Canonical], noes: Sequence[entities.Review]
) -> list[Proposal]:
    """The pure function: every (observed, canonical) pair with evidence, ranked by score, then the
    hint (a company before a brand), then the observed key; then the new entities the observed
    things that matched nothing would make, by lines; numbered from 1. A pair a standing no covers
    is left out."""

    def refused(o: Observed, entity: str | None) -> bool:
        return any(no.holds([o.key, *o.identifiers], entity) for no in noes)

    matched: list[tuple[int, tuple[str, ...], Observed, Canonical]] = []
    fresh: list[Observed] = []
    for o in unplaced:
        hits = 0
        for c in canonicals.values():
            score, why = evidence(o, c)
            if not score:
                continue
            hits += 1
            if not refused(o, c.id):
                matched.append((score, why, o, c))
        if hits == 0 and _may_be_new(o) and not refused(o, None):
            fresh.append(o)
    matched.sort(
        key=lambda m: (-m[0], HINT_ORDER.get(m[2].hint, 4), -len(m[1]), m[2].key, m[3].label.casefold())
    )
    fresh.sort(key=lambda o: (HINT_ORDER.get(o.hint, 4), -o.lines, o.key))
    found = [
        Proposal(n, proposal_id(o, c.id), o, c, score, why)
        for n, (score, why, o, c) in enumerate(matched, start=1)
    ]
    found += [
        Proposal(n, proposal_id(o, None), o, None, None, ("new",))
        for n, o in enumerate(fresh, start=len(found) + 1)
    ]
    return found


def _may_be_new(o: Observed) -> bool:
    """A domain, a code-host org, a page, a repository, a title or an asset may be a new entity; a
    group chat and a merchant are proposed against an org the record has, never as one."""
    return o.key[0] not in ("group", "merchant")


def proposal_id(o: Observed, entity: str | None) -> str:
    return hashlib.sha256(f"{o.kind}\n{o.key[0]}\n{o.key[1]}\n{entity or ''}".encode()).hexdigest()[:16]


def org_words(name: str) -> tuple[str, ...]:
    """A name's words folded and sorted, the legal forms out, when they can name an org: two words
    at least, or one of six letters or more; () otherwise."""
    found = sorted(w for w in entities.words(name) if w not in LEGAL_FORMS)
    return tuple(found) if len(found) >= 2 or (found and len(found[0]) >= LONG_WORD) else ()


def idea_words(name: str) -> tuple[str, ...]:
    found = sorted(entities.words(name, articles=False))
    return tuple(found) if len(found) >= 2 or (found and len(found[0]) >= LONG_WORD) else ()


def evidence(o: Observed, c: Canonical) -> tuple[int, tuple[str, ...]]:
    """(score, the evidence in words) for one pair; (0, ()) when nothing but days, weeks or people speak."""
    score, why = 0, []
    theirs = c.entity.refs
    if o.kind == ORG:
        domains = {v for k, v in theirs if k == "domain"} | {
            v.rsplit("@", 1)[1] for k, v in theirs if k == "email" and "@" in v
        }
        domains = {entities.registered_domain(d) or d for d in domains}
        for k, v in o.writable:
            if k == "domain" and v in domains:
                score += DOMAIN
                why.append(f"same domain {v}")
            if k == "repo" and v in {entities.repo_org(r) for kk, r in theirs if kk == "repo"}:
                score += REPO
                why.append(f"same code org {v}")
        match = _same_name(o, c, org_words)
    elif o.kind == IDEA:
        pages = {v for k, v in theirs if k == "page"}
        if any(k == "page" and v in pages for k, v in o.identifiers):
            score += PAGE
            why.append(f"same page {o.key[1]}")
        repos = {v.lower() for k, v in theirs if k == "repo"}
        if o.key[0] == "repo" and o.key[1] in repos:
            score += REPO
            why.append(f"same repo {o.key[1]}")
        match = _same_name(o, c, idea_words)
    else:
        mine = {(k, v.lower()) for k, v in o.writable}
        same = sorted(mine & {(k, v.lower()) for k, v in theirs})
        for k, v in same:
            score += SAME_ID
            why.append(f"same {k} {v}")
        spelled = {entities.registration_key(v): v for k, v in o.writable if k == "registration"}
        for k, v in theirs:
            if k == "registration" and entities.registration_key(v) in spelled and (k, v.lower()) not in mine:
                score += SPELLED
                why.append(f"same registration {spelled[entities.registration_key(v)]} ~ {v}")
        match = (NAME, f"same name {o.name}") if entities.fold(o.name) == entities.fold(c.label) else None
    if match is not None:
        score += match[0]
        why.append(match[1])
    if not why:
        return 0, ()
    if o.kind in (ORG, IDEA):
        people = len(o.people & c.people)
        if people:
            score += min(PEOPLE * people, PEOPLE_CAP)
            why.append(f"{_plural(people, 'person', 'people')} on both")
    if o.kind == ORG and (together := len(o.days & c.days)):
        score += min(TOGETHER * together, TOGETHER_CAP)
        why.append(f"together on {_plural(together, 'day')}")
    if o.kind == IDEA:
        theirs_weeks = {
            f"{d.isocalendar()[0]}-W{d.isocalendar()[1]:02d}" for d in map(date.fromisoformat, c.days)
        }
        if weeks := len(o.weeks & theirs_weeks):
            score += min(WEEK * weeks, WEEK_CAP)
            why.append(f"the same {_plural(weeks, 'week')}")
    return score, tuple(why)


def _same_name(o: Observed, c: Canonical, fold: Any) -> tuple[int, str] | None:
    names = {fold(n) for n in (c.label, *c.entity.aliases)} - {()}
    for label, _n in o.labels.most_common():
        if fold(label) and fold(label) in names:
            extra = min(NAME_SOURCE * (len(o.sources) - 1), NAME_SOURCE_CAP)
            text = f"same name {label}" if label == c.label else f"same name {label} ~ {c.label}"
            if extra:
                text += f" across {', '.join(sorted(o.sources))}"
            return NAME + extra, text
    return None


# -- the owner's say ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Written:
    proposal: Proposal
    verdict: str  # `accepted` or `rejected`
    label: str | None
    lines: list[Line]

    def to_json(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal.id,
            "number": self.proposal.number,
            "verdict": self.verdict,
            "observed": self.proposal.observed.to_json()["key"],
            "into": None if self.proposal.canonical is None else self.proposal.canonical.to_json(),
            "label": self.label,
            "lines": [str(line["id"]) for line in self.lines],
        }


def numbers(text: Sequence[str] | None, kind: str) -> list[int]:
    """`N[,N]`, given once or more, to the numbers in order, each once."""
    found: list[int] = []
    for piece in text or ():
        for word in piece.split(","):
            word = word.strip()
            if not word:
                continue
            if not word.isdigit() or int(word) < 1:
                raise ReviewError(
                    f"not a proposal number: {word!r}; `review {kind}` lists them, numbered from 1"
                )
            if int(word) not in found:
                found.append(int(word))
    return found


def pick(report: Report, wanted: Sequence[int]) -> list[Proposal]:
    by_number = {p.number: p for p in report.proposals}
    missing = [n for n in wanted if n not in by_number]
    if missing:
        have = _plural(len(report.proposals), "proposal")
        raise ReviewError(
            f"no proposal {', '.join(map(str, missing))}; the queue has {have},"
            f" `review {report.kind}` lists them"
        )
    return [by_number[n] for n in wanted]


def above(report: Report, score: str) -> list[Proposal]:
    text = score.strip()
    if not re.fullmatch(r"-?\d+", text):
        raise ReviewError(f"not a score: {score!r}; `--all-above` takes a whole number")
    return [p for p in report.proposals if p.score is not None and p.score >= int(text)]


def write_entity(lb: Logbook, payload: dict[str, Any], at: str | None = None) -> Line:
    """One `entity/v1` line through `Logbook.append`, after its checks: the profile (`entities.
    validate_entity`) and the tier rules against the tiers of the lines it cites, read through
    the index (decision 8: never a tier-3 line). `entities.EntityError` names the first problem."""
    problems = entities.validate_entity(payload)
    with lb.index() as idx:
        cited = {
            str(line["id"]): int(line.get("tier", 0))
            for line in idx.by_ids(payload.get("evidence") or []).values()
        }
    problems += entities.tier_problems(entities.ENTITY_SCHEMA, entities.TIER, cited)
    if problems:
        raise entities.EntityError(problems[0])
    return lb.append(
        at=at or now_utc(), source=entities.SOURCE, kind=entities.ENTITY, tier=entities.TIER, payload=payload
    )


def accept(lb: Logbook, report: Report, chosen: Sequence[tuple[Proposal, str | None]]) -> list[Written]:
    """The proposals accepted, each with the owner's name when given: one `entity/v1` line binding
    the observed identifiers to the canonical entity, or to a new one (its id the dedupe key's when
    the key already resolves, else a new UUIDv7; a new asset registered in `assets.json` first).
    Every proposal is checked before the first line is written."""
    plans: list[tuple[Proposal, str, str, list[Ref], assets.Asset | None]] = []
    keys: dict[Ref, Proposal] = {}
    calls: dict[tuple[Ref, str | None], Proposal] = {}
    known = {e.key: e for e in (c.entity for c in report.canonicals.values()) if e.key is not None}
    minted: dict[str, str] = {}  # a dedupe key -> the id minted for it in this sitting: one id per key
    for p, given in chosen:
        o = p.observed
        if p.call is not None:
            pair = (o.key, None if p.canonical is None else p.canonical.id)
            other = calls.setdefault(pair, p)
            if other is not p:
                raise ReviewError(
                    f"proposals {other.number} and {p.number} are the same idea from two calls; accept one,"
                    " and reject the other or leave it"
                )
            plans.append(_call_plan(p, given, known, minted))
            continue
        other = keys.setdefault(o.key, p)
        if other is not p:
            raise ReviewError(
                f"proposals {other.number} and {p.number} place {o.name} with two {NOUNS[o.kind][1]};"
                " accept one, and reject the other or leave it"
            )
        if p.canonical is not None and given is not None:
            raise ReviewError(
                f"proposal {p.number} is {p.canonical.label} already: --accept it; to rename an {o.kind},"
                " add an entity/v1 line that supersedes its standing one"
            )
        refs = [ref for ref in o.writable if p.canonical is None or ref not in p.canonical.entity.refs]
        label = " ".join((given or "").split()) or (p.canonical.label if p.canonical is not None else o.name)
        asset = None
        if p.canonical is not None:
            entity_id = p.canonical.id
            if not refs:
                raise ReviewError(f"proposal {p.number}: {p.canonical.label} holds every identifier already")
        elif (key := entities.key_of(o.kind, o.writable, None, label)) is not None and key in known:
            same = known[key]
            entity_id = same.id  # §3.4 rule 4: the key resolves already, its id is reused
        elif o.kind == ASSET:
            asset = _new_asset(p, label, report)
            entity_id = asset.id
        else:
            entity_id = uuid7() if key is None else minted.setdefault(key, uuid7())
        plans.append((p, entity_id, label, refs, asset))
    written = []
    at = now_utc()
    for p, entity_id, label, refs, asset in plans:
        o = p.observed
        if p.call is not None:
            written.append(
                Written(
                    p, "accepted", label, [write_entity(lb, _call_payload(p, entity_id, label, report), at)]
                )
            )
            continue
        if asset is not None:
            assets.add(lb.root, asset)
        payload = entities.entity_payload(
            o.kind,
            entity_id,
            label,
            refs=refs,
            key=entities.key_of(
                o.kind, [*(p.canonical.entity.refs if p.canonical else []), *refs], entity_id, label
            ),
            evidence=[i for i, t in o.samples if t < entities.MONEY_TIER],
            head=report.head,
            extra={"review": p.id, "score": p.score, "matched": list(p.evidence)},
        )
        written.append(Written(p, "accepted", label, [write_entity(lb, payload, at)]))
    return written


def _new_asset(p: Proposal, label: str, report: Report) -> assets.Asset:
    o = p.observed
    subject = next((v for k, v in o.identifiers if k == "subject"), None)
    kind = (
        "yacht"
        if o.key[0] == "mmsi"
        else "aircraft"
        if o.key[0] in ("icao24", "registration")
        else next((INSTRUMENTS[s] for s in o.sources if s in INSTRUMENTS), None)
    )
    if kind is None:
        raise ReviewError(
            f"proposal {p.number}: what kind of asset is {o.name}? say it with `setup assets add`"
        )
    asset_id = subject or re.sub(r"[^a-z0-9]+", "-", entities.fold(label)).strip("-")
    taken = {c.id for c in report.canonicals.values()}
    if not asset_id or asset_id in taken:
        raise ReviewError(f"proposal {p.number}: {asset_id!r} is already an asset; --name it another")
    values = {k: v for k, v in o.identifiers if k in assets.IDENTIFIERS}
    try:
        return assets.Asset(
            asset_id, kind, label, values.get("mmsi"), values.get("icao24"), values.get("registration")
        ).check()
    except assets.AssetError as e:
        raise ReviewError(f"proposal {p.number}: {e}") from e


def reject(lb: Logbook, report: Report, proposals: Sequence[Proposal]) -> list[Written]:
    """The proposals rejected: one `entity-review/v1` line each, through `Logbook.append`."""
    at = now_utc()
    written = []
    for p in proposals:
        o = p.observed
        label = p.canonical.label if p.canonical is not None else o.name
        if p.call is not None:
            payload = entities.review_payload(
                o.kind,
                o.key,
                refs=[o.key],
                observed=[o.name],
                entity_id=None if p.canonical is None else p.canonical.id,
                label=label,
                evidence=[i for i, _t in o.samples],
                head=report.head,
                raw_id=f"review:{entities.DIFFERENT}:{p.id}",
                extra={"review": p.id, "call": _call_mark(p)},
            )
            problems = entities.validate_entity_review(payload)
            if problems:
                raise ReviewError(problems[0])
            line = lb.append(
                at=at,
                source=entities.SOURCE,
                kind=entities.ENTITY_REVIEW,
                tier=entities.review_tier(t for _i, t in o.samples),
                payload=payload,
            )
            written.append(Written(p, "rejected", label, [line]))
            continue
        payload = entities.review_payload(
            o.kind,
            o.key,
            refs=o.writable or [o.key],
            observed=[label for label, _n in o.labels.most_common()],
            entity_id=None if p.canonical is None else p.canonical.id,
            label=label,
            evidence=[i for i, _t in o.samples],
            head=report.head,
            raw_id=f"review:{entities.DIFFERENT}:{p.id}",
            extra={"review": p.id, "score": p.score, "matched": list(p.evidence)},
        )
        problems = entities.validate_entity_review(payload)
        if problems:
            raise ReviewError(problems[0])
        tier = entities.review_tier(t for _i, t in o.samples)
        line = lb.append(
            at=at, source=entities.SOURCE, kind=entities.ENTITY_REVIEW, tier=tier, payload=payload
        )
        written.append(Written(p, "rejected", label, [line]))
    return written


# -- text ----------------------------------------------------------------------------------------------------


def rows(report: Report) -> Iterator[str]:
    """The queue: one numbered line per proposal with the score and the evidence, then what to do."""
    single, plural = NOUNS[report.kind]
    unplaced = _plural(len(report.unplaced), f"observed {single}", f"observed {plural}")
    if not report.proposals:
        yield (
            f"no proposals: {unplaced} not yet placed, nothing matches"
            if report.unplaced
            else (f"no proposals: no observed {single} is unplaced")
        )
        return
    head = f"{_plural(len(report.proposals), 'proposal')} · {unplaced} not yet placed"
    yield f"{head}, {report.placed} placed · tier {report.tier}"
    width = len(str(len(report.proposals)))
    for p in report.proposals:
        o = p.observed
        seen = ", ".join(f"{kind} {n}" for kind, n in sorted(o.kinds.items()))
        names = ", ".join(sorted(o.labels)[:3])
        shown = f'group "{o.key[1]}"' if o.key[0] == "group" else o.key[1]
        who = f"{shown} ({names}; {seen})" if names and names != shown else f"{shown} ({seen})"
        if p.call is not None:
            yield f"  {p.number:>{width}}  [call]  {call_text(p)}"
            continue
        if p.canonical is None:
            yield f"  {p.number:>{width}}  [new]  {who} → {BLANK}"
        else:
            yield f"  {p.number:>{width}}  [{p.score}]  {who} → {p.canonical.label}: {' · '.join(p.evidence)}"
    yield (
        f'nothing written: `review {report.kind} --accept N[,N]`, `--name N "…"`, `--reject N[,N]`,'
        " or `--all-above SCORE`"
    )


def written_rows(written: Iterable[Written]) -> Iterator[str]:
    for w in written:
        o = w.proposal.observed
        seqs = [int(line["seq"]) for line in w.lines]
        span = f" (seq {seqs[0]})" if len(seqs) == 1 else f" (seq {seqs[0]}{EN_DASH}{seqs[-1]})"
        sign = "→" if w.verdict == "accepted" else NOT_EQUAL
        into = w.label or BLANK
        name = f"“{o.name}”" if w.proposal.call is not None else o.key[1]
        yield f"{w.verdict} {w.proposal.number} {name} {sign} {into}: {_plural(len(seqs), 'line')}{span}"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"


# -- ideas from calls ---------------------------------------------------------------------------------------


def call_ideas(
    lb: Logbook, canonicals: Mapping[str, Canonical], noes: Sequence[entities.Review], start: int
) -> list[Proposal]:
    """The ideas the calls' standing syntheses propose (`synthesis.ideas_of`), as proposals numbered
    from `start`, the oldest call first (the module's docstring): through the `dream` entry today,
    of standing calls; one the owner already answered, by an `entity/v1` line (its `extra.review`
    the proposal's id) or a standing no, left out; a new one whose title an idea of the record holds
    already, left out too. Each carries the highest tier of the call and its synthesis. Writes
    nothing."""
    allowed = drafts.allowed(lb.root)
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = retractions(marks)
        syntheses = drafts.by_transcript(idx.by_kind(drafts.KIND), retracted)
        transcripts = idx.by_ids(list(syntheses))
        superseded = idx.superseded(TRANSCRIPT)
        answered = {
            str(said)
            for line in entities.standing([*marks, *idx.by_kind(entities.ENTITY)], entities.ENTITY)
            if isinstance(extra := (line.get("payload") or {}).get("extra"), dict)
            and isinstance(said := extra.get("review"), str)
        }
    titles = {
        key
        for c in canonicals.values()
        for key in (entities.title_key(c.label), *(v for k, v in c.entity.refs if k == "title"))
        if key
    }
    days = day_start.of(lb.meta)
    found: list[Proposal] = []
    for transcript_id, lines in syntheses.items():
        transcript = transcripts.get(transcript_id)
        if transcript is None or transcript.get("kind") != TRANSCRIPT or transcript_id in retracted:
            continue
        if transcript_id in superseded or transcript.get("source") in NOT_CALLS:
            continue
        draft = drafts.standing(lines)
        if draft is None or not allowed.allows(draft):
            continue
        extra = (draft.get("payload") or {}).get("extra")
        items = extra.get("ideas") if isinstance(extra, dict) else None
        tier = max(int(draft.get("tier") or 0), int(transcript.get("tier") or 0))
        for n, item in enumerate(items if isinstance(items, list) else []):
            candidate = _call_candidate(
                draft, transcript, n, item, tier, canonicals, noes, answered, titles, days
            )
            if candidate is None:
                continue
            first = next((p for p in found if p.id == candidate.id), None)
            if first is None:
                found.append(candidate)
                continue
            # the same idea from another call: one candidate, the other call among its evidence
            o = candidate.observed
            first.observed.add(SYNTHESIS, TRANSCRIPT, str(o.first), o.samples[0][0], o.tier)
            if first.call is not None and candidate.call is not None:
                first.call["calls"] = [*first.call["calls"], candidate.call["transcript"]]
    found.sort(
        key=lambda p: (str((p.call or {})["at"]), str((p.call or {})["synthesis"]), (p.call or {})["n"])
    )
    return [
        Proposal(n, p.id, p.observed, p.canonical, None, p.evidence, p.call)
        for n, p in enumerate(found, start)
    ]


def _call_candidate(
    draft: Line,
    transcript: Line,
    n: int,
    item: object,
    tier: int,
    canonicals: Mapping[str, Canonical],
    noes: Sequence[entities.Review],
    answered: set[str],
    titles: set[str],
    days: day_start.DayStart,
) -> Proposal | None:
    if not isinstance(item, dict):
        return None
    name, text, idea = item.get("name"), item.get("text"), item.get("idea")
    if not _text(name) or not _text(text):
        return None
    transcript_id = str(transcript["id"])
    canonical = canonicals.get(idea) if isinstance(idea, str) else None
    if idea is not None and canonical is None:
        return None  # a refinement of an idea the record no longer names
    if canonical is None:
        key: Ref = ("title", entities.title_key(str(name)))
        if not key[1] or key[1] in titles:
            return None
    else:
        key = ("line", transcript_id)
    entity = None if canonical is None else canonical.id
    if any(no.holds([key], entity) for no in noes):
        return None
    observed = Observed(IDEA, key)
    observed.add(SYNTHESIS, TRANSCRIPT, days.day_of(str(transcript["at"])), transcript_id, tier, str(name))
    payload = transcript.get("payload") or {}
    title = payload.get("title") if _text(payload.get("title")) else "a recording"
    utterances = [u.get("n") for u in item.get("utterances") or [] if isinstance(u, dict)]
    call = {
        "synthesis": str(draft["id"]),
        "n": n,
        "transcript": transcript_id,
        "title": title,
        "day": days.day_of(str(transcript["at"])),
        "at": str(transcript["at"]),
        "name": str(name),
        "text": str(text),
        "idea": None if canonical is None else canonical.id,
        "utterances": utterances,
        "calls": [transcript_id],  # every call that put it forward, the first first
    }
    why = (f"from the call “{title}” {call['day']}",)
    found = proposal_id(observed, entity)
    return None if found in answered else Proposal(0, found, observed, canonical, None, why, call)


def call_text(p: Proposal) -> str:
    """A call's idea in the queue: its name, the call and the utterances it rests on, and where it
    goes: a new idea (`____`) or the named one it refines, with the words."""
    call = p.call or {}
    said = ", ".join(f"U{u}" for u in call.get("utterances") or [])
    where = f"call “{call.get('title')}” {call.get('day')}" + (f"; {said}" if said else "")
    into = BLANK if p.canonical is None else f"{p.canonical.label}, refines"
    return f"“{call.get('name')}” ({where}) → {into}: {call.get('text')}"


def _call_mark(p: Proposal) -> dict[str, Any]:
    call = p.call or {}
    return {"synthesis": call.get("synthesis"), "n": call.get("n"), "transcript": call.get("transcript")}


def _call_plan(
    p: Proposal, given: str | None, known: Mapping[str, entities.Entity], minted: dict[str, str]
) -> tuple[Proposal, str, str, list[Ref], assets.Asset | None]:
    """What accepting a call's idea writes: a new idea (its id the dedupe key's when the key resolves
    already or was minted in this sitting, else a new UUIDv7) under the owner's name or the call's, or
    the named idea it refines."""
    if p.canonical is not None:
        if given is not None:
            raise ReviewError(f"proposal {p.number} refines {p.canonical.label}: --accept it, or reject it")
        return p, p.canonical.id, p.canonical.label, [], None
    label = " ".join((given or "").split()) or p.observed.name
    key = entities.key_of(IDEA, [], None, label)
    same = known.get(key) if key is not None else None
    if same is not None:
        return p, same.id, label, [], None
    return p, uuid7() if key is None else minted.setdefault(key, uuid7()), label, [], None


def _call_payload(p: Proposal, entity_id: str, label: str, report: Report) -> dict[str, Any]:
    """The `entity/v1` line the owner's yes writes: tier 2, so of a tier-3 call (a Granola call is
    tier 3) it carries the name the owner accepted and nothing else of the call, neither its words nor
    the ids of its lines, as an observed title of a tier-3 line is accepted; of a call at tier 2 or
    below, the call as evidence, the synthesis it came from and the words (`pitch` for a new idea,
    `refines` for a refinement)."""
    call = p.call or {}
    extra: dict[str, Any] = {"review": p.id}
    if p.observed.tier < entities.MONEY_TIER:
        extra["call"] = _call_mark(p)
        extra["refines" if p.canonical is not None else "pitch"] = call.get("text")
    return entities.entity_payload(
        IDEA,
        entity_id,
        label,
        key=entities.key_of(IDEA, list(p.canonical.entity.refs) if p.canonical else [], entity_id, label),
        evidence=[i for i, t in p.observed.samples if t < entities.MONEY_TIER],
        head=report.head,
        extra=extra,
    )


# -- goals (RFC 0036 amendment 1, RFC 0037 §12) --------------------------------------------------------------


@dataclass(frozen=True)
class GoalProposal:
    """One standing goal open today with no review dated this week: asked once a week."""

    number: int
    goal: Line  # the standing goal line of its chain
    last: Line | None  # its standing review, of any period, when it has one

    @property
    def id(self) -> str:
        return str(self.goal["id"])

    @property
    def tier(self) -> int:
        return goals.TIER

    def to_json(self) -> dict[str, Any]:
        payload = self.goal.get("payload") or {}
        last = None if self.last is None else self.last.get("payload") or {}
        return {
            "number": self.number,
            "goal": self.id,
            "seq": int(self.goal["seq"]),
            "text": payload.get("text"),
            "horizon": payload.get("horizon"),
            "from": payload.get("from"),
            "until": payload.get("until"),
            "last_review": None
            if self.last is None or last is None
            else {
                "disposition": last.get("disposition"),
                "period": last.get("period"),
                "line": str(self.last["id"]),
            },
        }


@dataclass(frozen=True)
class GoalReport:
    """The goal queue of the week `week` (Monday `monday` to `today`): the open goals not yet reviewed
    this week, numbered, and how many open goals were reviewed this week already."""

    week: str
    monday: str
    today: str
    proposals: list[GoalProposal]
    reviewed: int
    head: str
    days: day_start.DayStart
    kind: str = goals.KIND

    @property
    def tier(self) -> int | None:
        return goals.TIER if self.proposals else None

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "week": self.week,
            "on": self.today,
            "tier": self.tier,
            "reviewed": self.reviewed,
            "proposals": [p.to_json() for p in self.proposals],
        }


@dataclass(frozen=True)
class GoalWritten:
    """What one answer came to: the `review/v1` line written, or the review that already held the key."""

    proposal: GoalProposal
    disposition: str
    line: Line | None
    existing: Line | None

    def to_json(self) -> dict[str, Any]:
        return {
            "goal": self.proposal.id,
            "number": self.proposal.number,
            "disposition": self.disposition,
            "period": GOAL_PERIOD,
            "lines": [] if self.line is None else [str(self.line["id"])],
            "existing": None if self.existing is None else str(self.existing["id"]),
        }


GOAL_PERIOD = "week"  # the sitting asks once a week, so its verdict covers the week
GOAL_WORDS = "|".join(d.replace(" ", "-") for d in goals.DISPOSITIONS)  # advancing|stalled|…|superseded


def goal_read(lb: Logbook) -> GoalReport:
    """The goal queue at the record's head: every standing goal open today (begun, not closed by a
    verdict, not past its `until`) whose chain has no `review/v1` line dated on a local day of this
    ISO week, in the order the goals were written. Writes nothing."""
    days = day_start.of(lb.meta)
    today = days.today(goals.now())
    monday = today - timedelta(days=today.weekday())
    year, number, _weekday = today.isocalendar()
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        found = goals.Goals(idx.by_kind(goals.KIND), retracted)
        reviews = goals.review_lines(idx.by_kind(goals.REVIEW), retracted)
    proposals: list[GoalProposal] = []
    reviewed = 0
    for line in found.standing():
        if str((line.get("payload") or {}).get("from") or "") > today.isoformat():
            continue
        chain = found.chain(str(line["id"]))
        last = goals.standing_review(reviews, chain)
        if goals.state(line, last, today.isoformat()) != "open":
            continue
        this_week = any(
            str(r["payload"]["goal"]) in chain
            and monday.isoformat() <= days.day_of(str(r["at"])) <= today.isoformat()
            for r in reviews
        )
        if this_week:
            reviewed += 1
            continue
        proposals.append(GoalProposal(len(proposals) + 1, line, last))
    return GoalReport(
        f"{year}-W{number:02d}",
        monday.isoformat(),
        today.isoformat(),
        proposals,
        reviewed,
        str(lb.meta["head"]),
        days,
    )


def goal_answers(
    report: GoalReport, said: Sequence[tuple[str, str]], notes: Sequence[tuple[str, str]]
) -> list[tuple[GoalProposal, str, str | None]]:
    """The answers told (`--say N DISPOSITION`, `--note N TEXT`), every one checked before anything is
    written: each number a proposal of the queue, said once, its disposition one of the five, and each
    note on a number that is said. (proposal, disposition as the line stores it, note) in order."""
    by_number = {p.number: p for p in report.proposals}
    answers: list[tuple[GoalProposal, str, str | None]] = []
    seen: list[int] = []
    for text, word in said:
        found = numbers([text], goals.KIND)
        if len(found) != 1:
            raise ReviewError(f"--say takes one number and a verdict: --say 2 stalled, not {text!r}")
        number = found[0]
        if number in seen:
            raise ReviewError(f"goal {number} is given --say twice; say one verdict")
        seen.append(number)
        try:
            value = goals.disposition(word)
        except goals.GoalError as e:
            raise ReviewError(str(e)) from None
        answers.append((by_number.get(number) or _no_goal(report, number), value, None))
    noted: dict[int, str] = {}
    for text, words_ in notes:
        found = numbers([text], goals.KIND)
        if len(found) != 1:
            raise ReviewError(f'--note takes one number and your words: --note 2 "…", not {text!r}')
        if found[0] not in seen:
            raise ReviewError(
                f"--note {found[0]} goes with --say {found[0]} DISPOSITION: a note is on a verdict"
            )
        if found[0] in noted:
            raise ReviewError(f"goal {found[0]} is given --note twice; say it once")
        noted[found[0]] = words_
    return [(p, value, noted.get(p.number)) for p, value, _none in answers]


def _no_goal(report: GoalReport, number: int) -> NoReturn:
    have = _plural(len(report.proposals), "goal")
    raise ReviewError(f"no goal {number}; the queue has {have} to review this week, `review goal` lists them")


def goal_write(lb: Logbook, answers: Sequence[tuple[GoalProposal, str, str | None]]) -> list[GoalWritten]:
    """Each answer as `goal review` writes it (`goals.review`, the same function: the same line, the
    same bytes), for the period `week`, at now. A review the dedupe key holds already writes nothing
    and says so; a head that moved under one is `ReviewError`, the answers before it written."""
    written: list[GoalWritten] = []
    for p, value, note in answers:
        try:
            done = goals.review(lb, p.id, value, GOAL_PERIOD, note)
        except HeadMoved as e:
            raise ReviewError(str(e)) from None
        except goals.GoalError as e:
            raise ReviewError(f"goal {p.number}: {e}") from None
        written.append(GoalWritten(p, value, done.line, done.existing))
    return written


def goal_rows(report: GoalReport) -> Iterator[str]:
    """The queue: one numbered line per goal with its horizon and its last verdict, then what to do."""
    if not report.proposals:
        done = f"{_plural(report.reviewed, 'goal')} reviewed this week" if report.reviewed else "no open goal"
        yield f"no goal to review this week ({report.week}): {done}"
        return
    head = f"{_plural(len(report.proposals), 'goal')} to review this week ({report.week})"
    yield f"{head} · {report.reviewed} reviewed · tier {report.tier}"
    width = len(str(len(report.proposals)))
    for p in report.proposals:
        payload = p.goal.get("payload") or {}
        if p.last is None:
            last = "never reviewed"
        else:
            verdict = p.last.get("payload") or {}
            last = f"last: {verdict.get('disposition')} on {report.days.day_of(str(p.last['at']))}"
        what = f"{payload.get('text')}  ({payload.get('horizon')})"
        yield f"  {p.number:>{width}}  #{p.goal['seq']}  {what} · {last}"
    yield f'nothing written: `review goal --say N {GOAL_WORDS}`, `--note N "…"`'


def goal_written_rows(written: Iterable[GoalWritten]) -> Iterator[str]:
    for w in written:
        text = (w.proposal.goal.get("payload") or {}).get("text")
        if w.line is None:
            existing = w.existing or {}
            verdict = (existing.get("payload") or {}).get("disposition")
            yield (
                f"goal {w.proposal.number} “{text}” has a week review today already"
                f" (#{existing.get('seq')}, {verdict}); nothing was written"
            )
            continue
        yield f"{w.disposition} {w.proposal.number} “{text}”: review/v1 (seq {w.line['seq']})"
