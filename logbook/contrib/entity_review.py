"""Observed orgs, ideas and assets, the review queue and the owner's say — `logbook review org|idea|asset`
(RFC 0037 §4, §5). People (`people_review`) and places (`places_review`) have their own queues; the
sitting, `logbook review KIND`, is one loop over all five (`logbook.commands.review`).

**The strongest-identifier rule.** An observed thing's identity is the strongest identifier its
observation carries, never the id a source gives one observation:

- **org**: the registered domain of a `mail/v1` address or a calendar attendee's address (a public
  mail provider, `policy/entities.json`, and the owner's own domains name nobody's org), else the
  code-host org of a `browse/v1` url or a task's link (`github.com/nordmann-verft`), else a group
  chat's name folded (`message/v1`, `chat.type` group), else a `transaction/v1` merchant folded when
  it recurs on `merchant_min_lines` (3) lines or more. The row's `hint` is the guess at what it is —
  `company` for a domain, `personal` for a family's domain (every name seen on it shares the
  surname its first label spells), `community` for a code-host org or a group, `brand` for a
  merchant — for ranking only, never written to a line.
- **idea**: a `sync notion` page's root (the topmost page above it the record has a line for), as
  `page` `notion:<id>`, else a code-host repository (`host/owner/name`) of a url or a task's link,
  else a task's or a transcript's title, its words folded and sorted, when it recurs on
  `title_min_lines` (2) lines of two sources or more. A transcript's summary is never read.
- **asset**: a `location/v1` subject `assets.json` does not name (its MMSI or icao24 from the
  instrument's `extra` when the line has one), else an aircraft registration on
  `registration_min_flights` (3) standing flights or more that the registry does not hold.

**The table.** The observed rows are the org, idea and asset rows of `observed_entities` in the
index (`Index.store_observed`), stamped per kind with the head, the zone and the digests of
`places.json`, `assets.json` and `policy/entities.json`, served while the stamp holds, built again
when it does not. Nothing is stored in the record.

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
`entity-review/v1` line. Every write goes through `Logbook.append`; nothing here opens a socket."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from ..core import assets, day_start, flights, policy, present, resolve, stays
from ..core.chain import Line
from ..core.index import Index
from ..core.store import Logbook, now_utc, retractions, uuid7
from . import entities
from .entities import ASSET, IDEA, ORG, Ref

KINDS = (ORG, IDEA, ASSET)
TABLE_VERSION = "1"
SAMPLES = 3  # line ids kept per observed thing, as evidence
NOTION = "notion"  # the source `sync notion` writes
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
     "pulls", "issues", "new", "about", "pricing", "sponsors", "orgs", "users", "apps", "site"}
)  # fmt: skip
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
class _Context:
    """What every builder needs: the day of a line, the people the record resolves, the owner."""

    days: day_start.DayStart
    identities: Mapping[Ref, resolve.Identity]
    owner: present.Owner
    owner_domains: frozenset[str]
    settings: entities.Settings
    retracted: frozenset[str]
    labels: Mapping[str, str]  # a person's label folded → their entity, for a name a source shows

    def day(self, line: Line) -> str | None:
        at = stays.instant(line.get("at"))
        return None if at is None else self.days.day(at).isoformat()

    def person(self, ref: Ref | None) -> str | None:
        if ref is None:
            return None
        entity, _label = present.resolve_ref(ref, self.identities)
        return None if entity is None or entity in self.owner.entities else entity

    def standing(self, idx: Index, kind: str) -> Iterator[Line]:
        superseded = idx.superseded(kind)
        for line in idx.of_kind(kind):
            line_id = str(line.get("id"))
            if line_id not in self.retracted and line_id not in superseded:
                yield line


def build(lb: Logbook, idx: Index, kind: str) -> list[Observed]:
    """The pure read: every observed thing of `kind` from the standing lines, keyed by the strongest
    identifier, the owner's own left out, each placed when the record binds one of its identifiers."""
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
    ctx = _Context(
        day_start.of(meta),
        identities,
        owner,
        frozenset(domains),
        settings,
        frozenset(retractions(marks)),
        people_labels,
    )
    found = {ORG: _orgs, IDEA: _ideas, ASSET: _assets}[kind](lb, idx, ctx)
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


def _orgs(lb: Logbook, idx: Index, ctx: _Context) -> list[Observed]:
    found: dict[Ref, Observed] = {}

    def observe(key: Ref, line: Line, day: str, label: str | None, hint: str) -> Observed:
        o = found.setdefault(key, Observed(ORG, key, hint))
        o.add(
            str(line.get("source") or ""),
            str(line.get("kind")),
            day,
            str(line["id"]),
            int(line.get("tier", 0)),
            label,
        )
        o.saw(key)
        return o

    for kind in ("mail", "event"):
        for line in ctx.standing(idx, kind):
            day = ctx.day(line)
            if day is None:
                continue
            payload = line.get("payload") or {}
            for address, name, person in _addresses(kind, payload, ctx):
                domain = _domain_of(address, ctx)
                if domain is None:
                    continue
                o = observe(("domain", domain), line, day, name, "company")
                if person is not None:
                    o.people.add(person)
    for kind in ("browse", "task"):
        for line in ctx.standing(idx, kind):
            day = ctx.day(line)
            if day is None:
                continue
            for url in _urls(kind, line.get("payload") or {}):
                org = _code_org(url, ctx.settings)
                if org is not None:
                    observe(("repo", org), line, day, org.split("/", 1)[1], "community")
    for line in ctx.standing(idx, "message"):
        payload = line.get("payload") or {}
        chat = payload.get("chat")
        if not isinstance(chat, dict) or chat.get("type") != "group" or not _text(chat.get("name")):
            continue
        day = ctx.day(line)
        if day is None:
            continue
        o = observe(
            ("group", entities.fold(str(chat["name"]))),
            line,
            day,
            " ".join(str(chat["name"]).split()),
            "community",
        )
        if payload.get("from_me") is not True:
            person = ctx.person(_ref(payload.get("sender")))
            if person is not None:
                o.people.add(person)
    merchants: dict[Ref, Observed] = {}
    for line in ctx.standing(idx, "transaction"):
        merchant = (line.get("payload") or {}).get("merchant")
        day = ctx.day(line)
        if not _text(merchant) or day is None:
            continue
        key = ("merchant", entities.fold(str(merchant)))
        o = merchants.setdefault(key, Observed(ORG, key, "brand"))
        o.add(
            str(line.get("source") or ""),
            "transaction",
            day,
            str(line["id"]),
            int(line.get("tier", 0)),
            " ".join(str(merchant).split()),
        )
        o.saw(key)
    found.update({k: o for k, o in merchants.items() if o.lines >= ctx.settings.merchant_min_lines})
    for o in found.values():
        if o.key[0] == "domain" and _family(o):
            o.hint = "personal"
    return list(found.values())


def _addresses(
    kind: str, payload: Mapping[str, Any], ctx: _Context
) -> Iterator[tuple[str, str | None, str | None]]:
    """(address, the display name when it is the sender's, the person it resolves to) of a mail's
    headers or a calendar entry's attendees who did not decline and its organizer."""
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


def _domain_of(address: str, ctx: _Context) -> str | None:
    if "@" not in address or ("email", address) in ctx.owner.refs:
        return None
    domain = entities.registered_domain(address.rsplit("@", 1)[1], ctx.settings.public_suffixes)
    if domain is None or domain in ctx.settings.public_mail_providers or domain in ctx.owner_domains:
        return None
    return domain


def _family(o: Observed) -> bool:
    """A family's domain: every name seen on it is a person's, a given name and a surname, they
    share the surname, and the domain's first label spells it (`nordmann.example.org`)."""
    names = [entities.words(label) for label in o.labels]
    if not names or any(len(found) < 2 for found in names):
        return False
    surnames = {found[-1] for found in names}
    return len(surnames) == 1 and next(iter(surnames)) == o.key[1].split(".")[0].replace("-", "")


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


def _ideas(lb: Logbook, idx: Index, ctx: _Context) -> list[Observed]:
    found: dict[Ref, Observed] = {}
    pages: dict[str, tuple[str | None, str | None]] = {}  # page id → (parent page id, title)
    notion = [line for line in ctx.standing(idx, "event") if line.get("source") == NOTION]
    for line in notion:
        extra = (line.get("payload") or {}).get("extra")
        page = extra.get("page") if isinstance(extra, dict) else None
        if not isinstance(page, dict) or not _text(page.get("id")):
            continue
        parent = extra.get("parent") if isinstance(extra, dict) else None
        above = (
            str(parent["id"])
            if isinstance(parent, dict) and parent.get("type") == "page" and _text(parent.get("id"))
            else None
        )
        title = (line.get("payload") or {}).get("title")
        pages[str(page["id"])] = (
            above,
            str(title) if _text(title) else pages.get(str(page["id"]), (None, None))[1],
        )

    def root(page_id: str) -> str:
        seen = {page_id}
        while (
            (above := pages.get(page_id, (None, None))[0]) is not None
            and above in pages
            and above not in seen
        ):
            seen.add(above)
            page_id = above
        return page_id

    for line in notion:
        extra = (line.get("payload") or {}).get("extra") or {}
        page_id = str((extra.get("page") or {}).get("id") or "")
        day = ctx.day(line)
        if not page_id or day is None:
            continue
        top = root(page_id)
        key = ("page", f"notion:{top}")
        o = found.setdefault(key, Observed(IDEA, key))
        o.add(
            NOTION, "event", day, str(line["id"]), int(line.get("tier", 0)), pages.get(top, (None, None))[1]
        )
        o.saw(("page", f"notion:{page_id}"))
        actor = extra.get("actor")
        if isinstance(actor, dict) and _text(actor.get("name")):
            person = ctx.labels.get(entities.fold(str(actor["name"])))
            if person is not None:
                o.people.add(person)
    titles: dict[Ref, Observed] = {}
    for kind in ("browse", "task", "transcript"):
        for line in ctx.standing(idx, kind):
            payload = line.get("payload") or {}
            day = ctx.day(line)
            if day is None:
                continue
            repos = (
                [r for url in _urls(kind, payload) if (r := _code_repo(url, ctx.settings)) is not None]
                if kind != "transcript"
                else []
            )
            for repo in repos:
                key = ("repo", repo)
                o = found.setdefault(key, Observed(IDEA, key))
                o.add(
                    str(line.get("source") or ""),
                    kind,
                    day,
                    str(line["id"]),
                    int(line.get("tier", 0)),
                    repo.split("/", 1)[1],
                )
                o.saw(key)
            title = payload.get("title")
            if (
                repos
                or kind == "browse"
                or not _text(title)
                or not (folded := entities.title_key(str(title)))
            ):
                continue
            key = ("title", folded)
            o = titles.setdefault(key, Observed(IDEA, key))
            o.add(
                str(line.get("source") or ""),
                kind,
                day,
                str(line["id"]),
                int(line.get("tier", 0)),
                " ".join(str(title).split()),
            )
            o.saw(key)
            if kind == "transcript":
                for participant in payload.get("participants") or []:
                    if isinstance(participant, dict) and _text(participant.get("email")):
                        person = ctx.person(("email", str(participant["email"]).strip().casefold()))
                        if person is not None:
                            o.people.add(person)
    found.update(
        {k: o for k, o in titles.items() if o.lines >= ctx.settings.title_min_lines and len(o.sources) >= 2}
    )
    return list(found.values())


def _assets(lb: Logbook, idx: Index, ctx: _Context) -> list[Observed]:
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
    known = {e.key: e for e in (c.entity for c in report.canonicals.values()) if e.key is not None}
    for p, given in chosen:
        o = p.observed
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
            entity_id = uuid7()
        plans.append((p, entity_id, label, refs, asset))
    written = []
    at = now_utc()
    for p, entity_id, label, refs, asset in plans:
        o = p.observed
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
        yield f"{w.verdict} {w.proposal.number} {o.key[1]} {sign} {into}: {_plural(len(seqs), 'line')}{span}"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
