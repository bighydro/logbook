"""The orgs read back (RFC 0037 §7, §11) — `show orgs`, `show org NAME` and the Manifest under
`serve` — over the lines the entities foundation writes and reads (`logbook.contrib.entities`): the
orgs the `entity/v1` lines and the `company` resolution lines name (`entities.canonical`), the refs
they bind (`entities.bindings`), and the owner's `status/v1` lines (`entities.statuses`). It writes
nothing (ADR 0013): `review org` names the orgs, `logbook status org` disposes of them.

**A touch** is a standing line that resolves to a named org through one of its refs (RFC 0037 §1):
the domain of one of its addresses, the code-host org of one of its links, its group chat, its
merchant, each found as `review org` finds them (`entity_review.org_sightings`) and looked up as
the record binds them. Touches are read from the index at the head every time, never stored: no
derived table of their own. Each carries the canonical people on its line (`people_review`'s
counterparts, the owner and the not yet placed left out of the names).

**The shelf** (`shelf`, `show orgs`) is every named org under the headings of RFC 0037 §11, in
order: holding (`hold`, `add`, `sell`), exited, passed (the anti-portfolio, each with its reason in
full), let go, then no status; within a heading the most recent touch first. A row says the status
and since when, the last touch, the people involved (the first two by days), the documents, and
`stale` (a reader's rule, `entities.stale`: the status is one `policy/entities.json` `stale_days`
names, and neither it nor a touch is within that many days of today). Then the **co-investor
graph**: the canonical people who appear with more than one org, each edge as high a tier as the
lines that put the person with the org. **The page** (`page`, `show org NAME`) is one org: its
head, its status and every status line (a retracted one said so), every touch newest first, its
people, who introduced whom where a mail's subject says so (`Intro: …`, `A <> B`), its documents as
references, and the ledger's in, out and net per year.

**Tiers.** Every line is read through a gate (`Gate`): the tiers a reader may show (the owner's
terminal and `serve` read every tier; `export site` its policy's), and money only when asked and
tier 3 is among them. An org's status is tier 3 (RFC 0037 §8), its reason on that line and nowhere
else, so a gate without 3 shows no status and no reason, lists every org under no status and says
how many status lines it may not show. The ledger's lines are tier 3: without money they are no
touch at all, so no row, edge, last touch or figure rests on one.

**The portfolio** (RFC 0037 §10.2, amended 15 October 2026) is the field of an org's latest status
line that carries it (`entities.portfolios`), read from the status lines the gate shows and only
when it reads tier 3: the shelf and the page say it, `show orgs --portfolio TEXT` and the Manifest's
filter list the orgs in one (case and spaces aside), and the filter offers the portfolios the record
holds. Through a gate without 3 no row carries one, none is offered, and a filter asked for lists no
org at all, the same for every portfolio, so nothing tells which orgs one holds."""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from ..core import day_start, kept, notes, present, stays
from ..core.chain import Line
from ..core.index import Index
from ..core.resolve import Identity, Ref
from ..core.store import Logbook, retractions
from . import entities, entity_review
from .entities import ORG

KIND = ORG
TOUCHES_KEPT, TOUCHES_KEPT_VERSION = "orgs-touches-{}.json", 1  # each gate's touches, beside the index
MONEY_TIER = entities.MONEY_TIER
TRANSACTION = "transaction"
HOLDING = ("hold", "add", "sell")
HEADINGS: tuple[tuple[str, tuple[str, ...]], ...] = (  # RFC 0037 §11, in order; then no status
    ("holding", HOLDING),
    ("exited", ("exited",)),
    ("passed", ("passed",)),
    ("let go", ("let-go",)),
)
NO_STATUS = "no status"
HIDDEN = "status not shown: an org's status is tier 3, and this reads no tier 3"
PORTFOLIO_HIDDEN = "a portfolio is tier 3, on an org's status line, and this reads no tier 3"
THE_LEDGER = "the ledger"  # a ledger line as a last touch, without money: no merchant, no figure
WITH_REASON = ("passed", "let-go")  # the rows whose reason the shelf says in full
INTRO = re.compile(r"^(?:(?:re|fwd?|sv|vs|aw)\s*:\s*)*(?:intro(?:duction|ducing)?\b|.+\s<>\s.+)", re.I)
DOCUMENT_KINDS = ("mail", "browse", "event")  # the kinds a document reference is read from
EN_DASH, DOT = "\u2013", " · "


class OrgError(ValueError):
    """An org the record does not name, or names several of; nothing to show."""


# -- the gate -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Gate:
    """What a reader may show: the tiers it reads (None: every one), and whether money is among
    it: asked for, and tier 3 readable."""

    tiers: tuple[int, ...] | None
    money: bool

    def reads(self, tier: int) -> bool:
        return self.tiers is None or tier in self.tiers

    def allows(self, line: Line) -> bool:
        """Whether a line may be shown: its tier read, and a ledger line only with money."""
        if line.get("kind") == TRANSACTION and not self.money:
            return False
        return self.reads(int(line.get("tier") or 0))


def gate(tiers: Sequence[int] | None = None, money: bool = False) -> Gate:
    """The gate of a reader: `tiers` (None: every one), and money only when asked and tier 3 is read."""
    allowed = None if tiers is None else tuple(sorted({int(t) for t in tiers}))
    return Gate(allowed, money and (allowed is None or MONEY_TIER in allowed))


# -- touches ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Touch:
    """One standing line that resolves to a named org."""

    entity: str
    seq: int
    line: str
    day: str
    kind: str
    source: str
    tier: int
    via: str  # the kind of ref it resolved through: domain, repo, group, merchant
    people: tuple[str, ...]  # the canonical people on the line, the owner aside
    unplaced: tuple[str, ...]  # the observed people on it not yet placed, by their key


@dataclass
class Record:
    """What every reader of orgs reads, once, through the gate: the named orgs, the status lines
    the gate shows and how many it does not, every touch, the people's names, today."""

    gate: Gate
    orgs: dict[str, entities.Entity]
    statuses: dict[str, list[entities.Status]]  # standing, oldest first; the last is current
    lines: dict[str, list[Line]]  # every status line of each org the gate shows, retracted ones too
    retracted: frozenset[str]
    withheld: int  # the orgs' status lines (not retracted) the gate may not show, all of them
    touches: list[Touch]
    names: dict[str, str]  # a canonical person → the label a resolution gives them
    identities: Mapping[Ref, Identity]
    owner: present.Owner
    settings: entities.Settings
    on: date
    local: Any = field(repr=False)
    portfolios: dict[str, str] = field(default_factory=dict)  # org → its portfolio; empty without tier 3

    def current(self, org: str) -> entities.Status | None:
        history = self.statuses.get(org, [])
        return history[-1] if history else None

    def portfolio(self, org: str) -> str | None:
        """The portfolio that holds `org`, as the gate may show it: None without tier 3."""
        return self.portfolios.get(org) if self.statuses_read else None

    def touches_of(self, org: str) -> list[Touch]:
        return [t for t in self.touches if t.entity == org]

    def shown(self, t: Touch) -> bool:
        """Whether a touch is shown as itself (a timeline row, its people, a document, an edge): a
        ledger line only with money. Every touch the gate reads counts for the last touch, the order
        and the stale flag, so those never move with `--money`."""
        return t.kind != TRANSACTION or self.gate.money

    @property
    def statuses_read(self) -> bool:
        """Whether the gate reads an org's status lines, which are tier 3."""
        return self.gate.reads(entities.status_tier(ORG))


def read(lb: Logbook, g: Gate, today: str | None = None) -> Record:
    """The record as the org readers see it through `g`, at its head. Writes nothing."""
    with lb.index() as idx:
        return _read(lb, idx, g, today)


def _read(lb: Logbook, idx: Index, g: Gate, today: str | None) -> Record:
    meta = lb.meta
    days = day_start.of(meta)
    on = date.fromisoformat(today if today is not None else notes.today_in(days))
    marks = idx.retractions()
    retracted = frozenset(retractions(marks))
    orgs, bound, shown, hidden = _named(idx, g, marks, retracted)
    history: dict[str, list[Line]] = {}
    for line in sorted(shown, key=lambda x: int(x["seq"])):
        history.setdefault(str(_status_org(line)), []).append(line)
    folded = entities.statuses([*marks, *shown])
    ctx = entity_review.context(lb, idx)
    names: dict[str, str] = {}
    for who in ctx.identities.values():
        if who.entity and who.label and who.type in present.PERSON_TYPES:
            names.setdefault(who.entity, who.label)
    return Record(
        g,
        orgs,
        {i: found for (kind, i), found in folded.items() if kind == ORG and i in orgs},
        history,
        retracted,
        hidden,
        _touches(lb, idx, ctx, bound, g) if orgs else [],
        names,
        ctx.identities,
        ctx.owner,
        ctx.settings,
        on,
        _local(days),
        entities.portfolios([*marks, *shown]) if g.reads(MONEY_TIER) else {},
    )


def _named(
    idx: Index, g: Gate, marks: Sequence[Line], retracted: frozenset[str]
) -> tuple[dict[str, entities.Entity], dict[Ref, str], list[Line], int]:
    """(the orgs through the gate by id, the refs bound to them, their status lines the gate shows,
    how many it does not). An org is one an `entity/v1` or `company` resolution line names, or, when
    those are retracted, one a standing status line still names, under the status line's label
    (RFC 0037 §3.4 rule 3)."""
    named = [line for line in [*idx.resolutions(), *idx.by_kind(entities.ENTITY)] if g.reads(_tier(line))]
    orgs = {i: e for (kind, i), e in entities.canonical([*marks, *named]).items() if kind == ORG}
    bound = {
        ref: entity_id
        for ref, (kind, entity_id) in entities.bindings([*marks, *named]).items()
        if kind == ORG and entity_id in orgs
    }
    every = [line for line in idx.by_kind(entities.STATUS) if _status_org(line) is not None]
    shown = [line for line in every if g.reads(_tier(line))]
    for (kind, entity_id), history in entities.statuses([*marks, *shown]).items():
        if kind == ORG and entity_id not in orgs:
            label = next((s.label for s in reversed(history) if s.label), entity_id)
            orgs[entity_id] = entities.Entity(ORG, entity_id, label)
    shown = [line for line in shown if _status_org(line) in orgs]
    hidden = sum(1 for line in every if not g.reads(_tier(line)) and str(line["id"]) not in retracted)
    return orgs, bound, shown, hidden


def _touches(
    lb: Logbook, idx: Index, ctx: entity_review.Context, bound: Mapping[Ref, str], g: Gate
) -> list[Touch]:
    """Every standing line the gate reads that resolves to a named org through one of its refs, the
    ledger's among them (`Record.shown` says which are shown as themselves): each kind's in file
    order, the kinds in `ORG_KINDS`'s. Each kind's are kept beside the index (`TOUCHES_KEPT`) under the
    gate and the refs bound, and read on from where they stopped while that reads the same
    (`kept.read_on`)."""
    from .adapters.ios_contacts import DIAL_PREFIX_ENV

    path = kept.path(
        lb, TOUCHES_KEPT.format("-".join(map(str, g.tiers or ("all",))) + ("-money" if g.money else ""))
    )
    stamp = kept.stamp(
        lb,
        str(TOUCHES_KEPT_VERSION),
        kept.code_digest(__file__, entity_review.__file__, entities.__file__),
        json.dumps(sorted([k, v, org] for (k, v), org in bound.items())),
        json.dumps([g.tiers, g.money]),
        os.environ.get(DIAL_PREFIX_ENV, "").strip(),
    )
    seq, head = idx.indexed()
    held = kept.load(path)
    by_kind: dict[str, list[Touch]] | None = None
    if held is not None and held.get("version") == TOUCHES_KEPT_VERSION and held.get("stamp") == stamp:
        files = {str(k): str(v) for k, v in (held.get("files") or {}).items()}
        if set(files) == set(entity_review.ORG_KINDS) and kept.read_on(
            idx, held, files, entity_review.ORG_OVERLAY
        ):
            try:
                by_kind = {
                    kind: [_touch_from(t) for t in held["touches"][kind]] for kind in entity_review.ORG_KINDS
                }
            except (KeyError, TypeError, ValueError):
                by_kind = None
    since = int(held["seq"]) if by_kind is not None and held is not None else None
    if by_kind is None:
        by_kind = {kind: [] for kind in entity_review.ORG_KINDS}
    for kind, found in by_kind.items():
        superseded = idx.superseded(kind)
        for line in idx.of_kind(kind, after_seq=since):
            line_id = str(line.get("id"))
            if int(line.get("seq") or 0) > seq or line_id in ctx.retracted or line_id in superseded:
                continue
            found.extend(_touched(kind, line, ctx, bound, g))
    kept.save(
        path,
        {
            "version": TOUCHES_KEPT_VERSION,
            "stamp": stamp,
            "seq": seq,
            "head": head,
            "files": {kind: idx.last_file(kind, seq) for kind in entity_review.ORG_KINDS},
            "touches": {kind: [_touch_json(t) for t in found] for kind, found in by_kind.items()},
        },
    )
    return [t for kind in entity_review.ORG_KINDS for t in by_kind[kind]]


def _touched(
    kind: str, line: Line, ctx: entity_review.Context, bound: Mapping[Ref, str], g: Gate
) -> list[Touch]:
    """The touches of one standing line: one per named org it resolves to, through its first ref."""
    if not g.reads(_tier(line)):
        return []
    hits: dict[str, str] = {}
    for s in entity_review.org_sightings(kind, line, ctx):
        org = bound.get(s.key)
        if org is not None:
            hits.setdefault(org, s.key[0])
    if not hits:
        return []
    day = ctx.day(line)
    if day is None:
        return []
    people, unplaced = _people_on(kind, line, ctx)
    return [
        Touch(
            org,
            int(line["seq"]),
            str(line["id"]),
            day,
            kind,
            str(line.get("source") or ""),
            _tier(line),
            via,
            people,
            unplaced,
        )
        for org, via in hits.items()
    ]


def _touch_json(t: Touch) -> list[Any]:
    return [t.entity, t.seq, t.line, t.day, t.kind, t.source, t.tier, t.via, list(t.people), list(t.unplaced)]


def _touch_from(row: Sequence[Any]) -> Touch:
    entity, seq, line, day, kind, source, tier, via, people, unplaced = row
    return Touch(
        str(entity), int(seq), str(line), str(day), str(kind), str(source), int(tier), str(via),
        tuple(map(str, people)), tuple(map(str, unplaced)),
    )  # fmt: skip


def _people_on(kind: str, line: Line, ctx: entity_review.Context) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(the canonical people on a line, the observed people on it not yet placed, by their key)."""
    from . import people_review  # its adapters (phone numbers) load when a line is read, never for --help
    from .adapters.ios_contacts import DIAL_PREFIX_ENV

    payload = line.get("payload") or {}
    seen = list(people_review.counterparts(kind, payload))
    if kind == TRANSACTION:
        extra = _obj(payload.get("extra"))
        members = extra.get("members")
        for member in members if isinstance(members, list) else []:
            ref = member.get("ref") if isinstance(member, dict) else None
            if (
                isinstance(ref, dict)
                and isinstance(ref.get("kind"), str)
                and isinstance(ref.get("value"), str)
            ):
                seen.append(people_review.Seen(((ref["kind"], ref["value"]),), _text(member.get("name"))))
    people: list[str] = []
    unplaced: list[str] = []
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    for s in seen:
        if people_review._is_owner(s, ctx.owner, ctx.identities):
            continue
        entity = next(
            (e for ref in s.refs if (e := present.resolve_ref(ref, ctx.identities)[0]) is not None),
            None,
        )
        if entity is not None:
            if entity not in people and entity not in ctx.owner.entities:
                people.append(entity)
            continue
        key = people_review.key_of(s, prefix)
        if key is not None and key[0] != "name" and f"{key[0]}:{key[1]}" not in unplaced:
            unplaced.append(f"{key[0]}:{key[1]}")
    return tuple(people), tuple(unplaced)


# -- the shelf ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Involved:
    person: str
    name: str
    touches: int
    days: int
    last: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.person,
            "name": self.name,
            "touches": self.touches,
            "days": self.days,
            "last": self.last,
        }


@dataclass(frozen=True)
class Row:
    """One named org on the shelf."""

    org: entities.Entity
    status: entities.Status | None
    since: str | None
    stale: bool
    stale_since: str | None  # the later of the status's day and the last touch, when stale
    last: Touch | None
    last_text: str | None
    touches: int
    people: list[Involved]
    documents: int
    money: dict[str, dict[str, float]] | None  # currency → in, out, net, for the shelf's year
    tier: int
    portfolio: str | None = None  # the portfolio that holds it, only through a gate that reads tier 3

    @property
    def heading(self) -> str:
        return heading(self.status)

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.org.id,
            "name": self.org.label,
            "key": self.org.key,
            "heading": self.heading,
            "status": None if self.status is None else self.status.status,
            "since": self.since,
            "reason": None if self.status is None else self.status.reason,
            "proposed_by": None if self.status is None else self.status.proposed_by,
            "portfolio": self.portfolio,
            "stale": self.stale,
            "stale_since": self.stale_since,
            "last_touch": None
            if self.last is None
            else {
                "day": self.last.day,
                "kind": self.last.kind,
                "what": self.last_text,
                "line": self.last.line,
            },
            "touches": self.touches,
            "people": [p.to_json() for p in self.people],
            "documents": self.documents,
            "money": self.money,
            "tier": self.tier,
        }


@dataclass(frozen=True)
class Shared:
    """One canonical person who appears with more than one org: an edge of the co-investor graph,
    as high a tier as the lines that put them with the orgs (the lowest line with each org, the
    highest of those)."""

    person: str
    name: str
    orgs: list[entities.Entity]
    tier: int

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.person,
            "name": self.name,
            "orgs": [{"id": o.id, "name": o.label} for o in self.orgs],
            "tier": self.tier,
        }


@dataclass(frozen=True)
class Shelf:
    rows: list[Row]
    graph: list[Shared]
    on: str
    year: str
    money: bool
    withheld: int
    tier: int | None
    portfolio: str | None = None  # the portfolio asked for, as asked; None for every org
    portfolios: list[str] = field(default_factory=list)  # the record's, to filter by; none without tier 3
    portfolios_read: bool = True  # whether the gate reads tier 3, where a portfolio is

    @property
    def passed(self) -> list[Row]:
        """The anti-portfolio: the orgs whose current status is `passed`, with their reasons."""
        return [r for r in self.rows if r.status is not None and r.status.status == "passed"]

    def grouped(self) -> list[tuple[str, list[Row]]]:
        """The rows under their headings, in the order of RFC 0037 §11, the empty ones left out."""
        order = [name for name, _ in HEADINGS] + [NO_STATUS]
        return [(name, found) for name in order if (found := [r for r in self.rows if r.heading == name])]

    def to_json(self) -> dict[str, Any]:
        return {
            "on": self.on,
            "tier": self.tier,
            "money": self.money,
            "year": self.year if self.money else None,
            "withheld": self.withheld,
            "portfolio": self.portfolio,
            "portfolios": self.portfolios,
            "orgs": [r.to_json() for r in self.rows],
            "passed": [
                {"id": r.org.id, "name": r.org.label, "reason": r.status.reason}
                for r in self.passed
                if r.status
            ],
            "graph": [s.to_json() for s in self.graph],
        }


def heading(status: entities.Status | None) -> str:
    """The shelf's heading for a current status (RFC 0037 §11)."""
    if status is not None:
        for name, members in HEADINGS:
            if status.status in members:
                return name
    return NO_STATUS


def shelf(
    lb: Logbook,
    tiers: Sequence[int] | None = None,
    money: bool = False,
    year: str | None = None,
    today: str | None = None,
    portfolio: str | None = None,
) -> Shelf:
    """Every named org under its heading, the most recent touch first (none last, by name), the
    co-investor graph after; through the gate of `tiers` and `money`; with `portfolio`, only the
    orgs in that one (`shelf_of`). Writes nothing."""
    g = gate(tiers, money)
    rec = read(lb, g, today)
    return shelf_of(lb, rec, year, portfolio)


def shelf_of(lb: Logbook, rec: Record, year: str | None = None, portfolio: str | None = None) -> Shelf:
    """The shelf of `rec`; with `portfolio`, only the orgs that portfolio holds (`entities.fold`:
    case and spaces aside), the graph and the passed among them. Through a gate without tier 3 a
    portfolio asked for lists no org, whichever it is: the portfolio is on a tier-3 line."""
    if year is not None and not re.fullmatch(r"\d{4}", year.strip()):
        raise OrgError(f"--year {year!r} is not a year, YYYY")
    if portfolio is not None and not portfolio.strip():
        raise OrgError('--portfolio names a portfolio: --portfolio "Fund I"')
    wanted = year.strip() if year is not None else str(rec.on.year)
    by_org: dict[str, list[Touch]] = {}
    for t in rec.touches:
        by_org.setdefault(t.entity, []).append(t)
    lasts = {org: _last(found) for org, found in by_org.items()}
    with lb.index() as idx:
        lines = idx.by_seqs({t.seq for t in rec.touches if t.kind in DOCUMENT_KINDS or t.kind == TRANSACTION})
        lines.update(idx.by_seqs({t.seq for t in lasts.values() if t is not None}))
    rows: list[Row] = []
    for org in rec.orgs.values():
        mine = by_org.get(org.id, [])
        shown = [t for t in mine if rec.shown(t)]
        last = lasts.get(org.id)
        current = rec.current(org.id)
        stale, stale_since = _staleness(rec, current, last)
        ordered = [lines[t.seq] for t in sorted(mine, key=lambda t: t.seq) if t.seq in lines]
        figures = money_of(ordered, {t.seq: t for t in mine}) if rec.gate.money else None
        rows.append(
            Row(
                org,
                current,
                None if current is None else current.day(rec.local),
                stale,
                stale_since,
                last,
                None if last is None else _last_text(lines.get(last.seq), rec.gate),
                len(shown),
                involved(shown, rec.names),
                len(documents([line for line in ordered if line.get("kind") in DOCUMENT_KINDS], shown)),
                None if figures is None else figures.get(wanted, {}),
                max(
                    [
                        entities.TIER,
                        *(t.tier for t in mine),
                        *(_status_tier(s) for s in rec.statuses.get(org.id, [])),
                    ]
                ),
                rec.portfolio(org.id),
            )
        )
    if portfolio is not None:
        asked = entities.fold(portfolio)
        rows = [r for r in rows if rec.statuses_read and entities.fold(r.portfolio or "") == asked]
    rows.sort(key=lambda r: r.org.label.casefold())
    rows.sort(key=lambda r: ("", 0) if r.last is None else (r.last.day, r.last.seq), reverse=True)
    graph = _graph(rows, {org: [t for t in found if rec.shown(t)] for org, found in by_org.items()}, rec)
    tiers = [r.tier for r in rows]
    return Shelf(
        rows,
        graph,
        rec.on.isoformat(),
        wanted,
        rec.gate.money,
        rec.withheld,
        max(tiers, default=None),
        portfolio,
        held(rec),
        rec.statuses_read,
    )


def held(rec: Record) -> list[str]:
    """The portfolios the record's orgs are in, each once, case and spaces aside, under the first of
    its spellings in sort order, by name; none through a gate without tier 3."""
    if not rec.statuses_read:
        return []
    found: dict[str, str] = {}
    for name in sorted({p for org in rec.orgs if (p := rec.portfolio(org)) is not None}):
        found.setdefault(entities.fold(name), name)
    return sorted(found.values(), key=lambda name: (name.casefold(), name))


def _last_text(line: Line | None, g: Gate) -> str | None:
    """The last touch as the shelf says it: what the line was, a ledger line without money as
    `the ledger` and nothing more (no merchant, no figure)."""
    if line is not None and line.get("kind") == TRANSACTION and not g.money:
        return THE_LEDGER
    return what(line, g)


def _graph(rows: Sequence[Row], by_org: Mapping[str, Sequence[Touch]], rec: Record) -> list[Shared]:
    lowest: dict[str, dict[str, int]] = {}  # person → org → the lowest tier of a line with both
    for org, found in by_org.items():
        for t in found:
            for person in t.people:
                mine = lowest.setdefault(person, {})
                mine[org] = min(mine.get(org, t.tier), t.tier)
    named = {r.org.id: r.org for r in rows}
    shared = [
        Shared(
            person,
            rec.names.get(person, person),
            sorted((named[o] for o in orgs if o in named), key=lambda e: e.label.casefold()),
            max(orgs.values()),
        )
        for person, orgs in lowest.items()
        if len([o for o in orgs if o in named]) > 1
    ]
    return sorted(shared, key=lambda s: (-len(s.orgs), s.name.casefold(), s.person))


def _last(touches: Sequence[Touch]) -> Touch | None:
    return max(touches, key=lambda t: (t.day, t.seq)) if touches else None


def _staleness(rec: Record, current: entities.Status | None, last: Touch | None) -> tuple[bool, str | None]:
    """Whether the current status is stale (`entities.stale`, with the last touch) and since when."""
    if current is None:
        return False, None
    touched = None if last is None else last.day
    if not entities.stale(current, rec.on, rec.local, rec.settings.stale_days, touched):
        return False, None
    return True, max(current.day(rec.local), touched or "")


def involved(touches: Sequence[Touch], names: Mapping[str, str]) -> list[Involved]:
    """The canonical people on the touches, the most days first, then the most touches."""
    count: Counter[str] = Counter()
    days: dict[str, set[str]] = {}
    for t in touches:
        for person in t.people:
            count[person] += 1
            days.setdefault(person, set()).add(t.day)
    found = [Involved(p, names.get(p, p), n, len(days[p]), max(days[p])) for p, n in count.items()]
    return sorted(found, key=lambda i: (-i.days, -i.touches, i.name.casefold(), i.person))


# -- what a line was ---------------------------------------------------------------------------------------


def what(line: Line | None, g: Gate) -> str | None:
    """One line as the page's timeline says it; None for no line, or a ledger line without money.
    The subject of a mail and the title of an entry are what the line holds; a body is never shown
    because it is never stored."""
    if line is None or not g.allows(line):
        return None
    kind = str(line.get("kind"))
    payload = line.get("payload") or {}
    title = _text(payload.get("title"))
    if kind == "mail":
        sender = _obj(payload.get("from"))
        who = _text(sender.get("name")) or _text(sender.get("email")) or "someone"
        subject = _text(payload.get("subject")) or "(no subject)"
        if payload.get("direction") == "sent":
            to = payload.get("to")
            first = to[0] if isinstance(to, list) and to and isinstance(to[0], dict) else {}
            return f'mail to {_text(first.get("name")) or _text(first.get("email")) or "someone"} "{subject}"'
        return f'mail from {who} "{subject}"'
    if kind == "event":
        extra = _obj(payload.get("extra"))
        if entity_review.github_act(line):
            repo = _text(extra.get("repo"))
            return f"github {repo}: {title or 'an act'}" if repo else f"github: {title or 'an act'}"
        attendees = payload.get("attendees")
        n = len(attendees) if isinstance(attendees, list) else 0
        return f'meeting "{title or "untitled"}"' + (f" with {plural(n, 'attendee')}" if n else "")
    if kind == "message":
        chat = _obj(payload.get("chat"))
        sender = _obj(payload.get("sender"))
        who = _text(sender.get("name")) or ("you" if payload.get("from_me") else "someone")
        return f'group "{_text(chat.get("name")) or "a chat"}": message from {who}'
    if kind == "transcript":
        return f'transcript "{title or "untitled"}"'
    if kind == "browse":
        return f"browsed {_text(payload.get('url')) or ''}".strip()
    if kind == "task":
        return f'task "{title or "untitled"}"'
    if kind == TRANSACTION:
        amount = payload.get("amount")
        number = (
            f"{amount:+,.2f}" if isinstance(amount, int | float) and not isinstance(amount, bool) else "?"
        )
        merchant = _text(payload.get("merchant")) or "a transaction"
        return f"{merchant} {number} {payload.get('currency') or ''}".strip()
    return kind


# -- the page ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One row of an org's timeline."""

    day: str
    at: str
    kind: str
    source: str
    line: str
    what: str
    via: str
    tier: int

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "at": self.at,
            "kind": self.kind,
            "source": self.source,
            "what": self.what,
            "via": self.via,
            "tier": self.tier,
            "line": self.line,
        }


@dataclass(frozen=True)
class Intro:
    """A mail whose subject says it introduces: who sent it, whom it introduced, when."""

    by: str
    introduced: list[str]
    day: str
    subject: str
    line: str

    def to_json(self) -> dict[str, Any]:
        return {
            "by": self.by,
            "introduced": self.introduced,
            "day": self.day,
            "subject": self.subject,
            "line": self.line,
        }


@dataclass(frozen=True)
class Document:
    """A document that touches the org, as a reference: a mail (its subject and thread) or a
    repository (its address); never a copy."""

    kind: str  # `mail` or `repo`
    name: str
    ref: str
    day: str
    line: str

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "ref": self.ref, "day": self.day, "line": self.line}


@dataclass(frozen=True)
class StatusLine:
    """One status line of the org, as the page's history says it: `standing` unless retracted, and
    `current` for the one in force (each later line supersedes the one before it)."""

    day: str
    status: str
    proposed_by: str | None
    reason: str | None
    line: str
    tier: int
    standing: bool
    current: bool
    portfolio: str | None = None  # the field the line carries: None when none, empty when it clears one

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "status": self.status,
            "proposed_by": self.proposed_by,
            "reason": self.reason,
            "portfolio": self.portfolio,
            "line": self.line,
            "tier": self.tier,
            "standing": self.standing,
            "current": self.current,
        }


@dataclass(frozen=True)
class Page:
    org: entities.Entity
    status: entities.Status | None
    since: str | None
    history: list[StatusLine]
    timeline: list[Item]
    people: list[Involved]
    unplaced: int
    introductions: list[Intro]
    documents: list[Document]
    money: dict[str, dict[str, dict[str, float]]] | None  # year → currency → in, out, net
    stale: bool
    stale_since: str | None
    on: str
    hidden: bool  # the gate reads no tier 3: no status here, whether the org has one or not
    tier: int
    portfolio: str | None = None  # the portfolio that holds it, only through a gate that reads tier 3

    def to_json(self) -> dict[str, Any]:
        return {
            "org": self.org.to_json(),
            "status": None
            if self.status is None
            else {
                "status": self.status.status,
                "since": self.since,
                "reason": self.status.reason,
                "proposed_by": self.status.proposed_by,
                "line": self.status.line,
            },
            "portfolio": self.portfolio,
            "stale": self.stale,
            "stale_since": self.stale_since,
            "history": [s.to_json() for s in self.history],
            "hidden": self.hidden,
            "on": self.on,
            "tier": self.tier,
            "timeline": [i.to_json() for i in self.timeline],
            "people": [p.to_json() for p in self.people],
            "unplaced": self.unplaced,
            "introductions": [i.to_json() for i in self.introductions],
            "documents": [d.to_json() for d in self.documents],
            "money": self.money,
        }


def named(lb: Logbook, tiers: Sequence[int] | None = None) -> dict[str, entities.Entity]:
    """The orgs the record names through the gate of `tiers` (None: every tier), by id: its naming
    lines and its status lines alone, no touch swept (what a form or a name is checked against)."""
    with lb.index() as idx:
        marks = idx.retractions()
        return _named(idx, gate(tiers), marks, frozenset(retractions(marks)))[0]


def find(lb: Logbook, name: str, tiers: Sequence[int] | None = None) -> entities.Entity:
    """The one named org `name` names, as `status org NAME` finds it (`entities.lookup`: a ref, an
    id, a label or an alias, a word of a label); `OrgError` for none or several."""
    try:
        return entities.lookup({(ORG, e.id): e for e in named(lb, tiers).values()}, ORG, name)
    except entities.EntityError as e:
        raise OrgError(str(e)) from e


def page(
    lb: Logbook,
    org_id: str,
    tiers: Sequence[int] | None = None,
    money: bool = False,
    today: str | None = None,
) -> Page:
    """One org's page through the gate; `OrgError` when the record names no such org."""
    rec = read(lb, gate(tiers, money), today)
    return page_of(lb, rec, org_id)


def page_of(lb: Logbook, rec: Record, org_id: str) -> Page:
    org = rec.orgs.get(org_id)
    if org is None:
        raise OrgError(f"no org {org_id} in this record")
    mine = rec.touches_of(org_id)
    shown = [t for t in mine if rec.shown(t)]
    with lb.index() as idx:
        lines = idx.by_seqs(t.seq for t in mine)
    by_seq = {t.seq: t for t in mine}
    timeline = []
    for t in sorted(shown, key=lambda t: (t.day, str(lines[t.seq].get("at")), t.seq), reverse=True):
        text = what(lines[t.seq], rec.gate)
        if text is not None:
            line = lines[t.seq]
            timeline.append(Item(t.day, str(line.get("at")), t.kind, t.source, t.line, text, t.via, t.tier))
    ordered = [lines[s] for s in sorted(lines)]
    current = rec.current(org_id)
    stale, stale_since = _staleness(rec, current, _last(mine))
    in_force = None if current is None else current.line
    history = [
        StatusLine(
            _status_day(line, rec.local),
            str((line.get("payload") or {}).get("status")),
            _text((line.get("payload") or {}).get("proposed_by")),
            _text((line.get("payload") or {}).get("reason")),
            str(line["id"]),
            _tier(line),
            str(line["id"]) not in rec.retracted,
            str(line["id"]) == in_force,
            entities.portfolio_field(line.get("payload") or {}),
        )
        for line in rec.lines.get(org_id, [])
    ]
    return Page(
        org,
        current,
        None if current is None else current.day(rec.local),
        history,
        timeline,
        involved(shown, rec.names),
        len({u for t in shown for u in t.unplaced}),
        introductions([lines[t.seq] for t in sorted(shown, key=lambda t: t.seq)], by_seq, rec),
        documents(ordered, shown),
        money_of(ordered, by_seq) if rec.gate.money else None,
        stale,
        stale_since,
        rec.on.isoformat(),
        not rec.statuses_read,
        max([entities.TIER, *(t.tier for t in mine), *(s.tier for s in history)]),
        rec.portfolio(org_id),
    )


def introductions(lines: Sequence[Line], by_seq: Mapping[int, Touch], rec: Record) -> list[Intro]:
    """The mails among `lines` whose subject says they introduce (`Intro: …`, `A <> B`): the sender
    introduced the others on it, the owner left out."""
    found = []
    for line in lines:
        payload = line.get("payload") or {}
        subject = _text(payload.get("subject"))
        if line.get("kind") != "mail" or subject is None or not INTRO.match(subject):
            continue
        by = _who(_obj(payload.get("from")), rec)
        if by is None:
            continue
        others = []
        for header in ("to", "cc"):
            value = payload.get(header)
            for address in value if isinstance(value, list) else []:
                if isinstance(address, dict):
                    who = _who(address, rec)
                    if who is not None and who != by and who not in others:
                        others.append(who)
        if others:
            found.append(Intro(by, others, by_seq[int(line["seq"])].day, subject, str(line["id"])))
    return found


def _who(address: Mapping[str, Any], rec: Record) -> str | None:
    """A mail address as a name: the person it resolves to, else the name it shows, else the
    address; None for the owner."""
    email = _text(address.get("email"))
    if email is None:
        return None
    ref = ("email", email.casefold())
    if ref in rec.owner.refs:
        return None
    who = rec.identities.get(ref) or rec.identities.get(("email", email))
    if who is not None and who.entity in rec.owner.entities:
        return None
    if who is not None and who.label and who.type in present.PERSON_TYPES:
        return who.label
    return _text(address.get("name")) or email


def documents(lines: Sequence[Line], touches: Sequence[Touch]) -> list[Document]:
    """The mails and repositories among `lines` that touch the org, newest first, each once, as
    references: a mail's subject and thread, a repository's address; never a copy."""
    days = {t.seq: t.day for t in touches}
    found: dict[tuple[str, str], Document] = {}
    for line in lines:
        seq = int(line["seq"])
        if seq not in days:
            continue
        payload = line.get("payload") or {}
        day, line_id = days[seq], str(line.get("id"))
        doc: Document | None = None
        if line.get("kind") == "mail":
            subject = _text(payload.get("subject")) or "(no subject)"
            doc = Document("mail", subject, _text(payload.get("thread")) or line_id, day, line_id)
        else:
            for url in _links(line):
                repo = _repository(url)
                if repo is not None:
                    doc = Document("repo", repo, repo.casefold(), day, line_id)
                    break
        if doc is None:
            continue
        key = (doc.kind, doc.ref)
        if key not in found or found[key].day < doc.day:
            found[key] = doc
    return sorted(found.values(), key=lambda d: (d.day, d.kind, d.name), reverse=True)


def _links(line: Line) -> list[str]:
    payload = line.get("payload") or {}
    if line.get("kind") == "browse":
        url = _text(payload.get("url"))
        return [url] if url else []
    if line.get("kind") == "event" and entity_review.github_act(line):
        extra = _obj(payload.get("extra"))
        for name in entity_review.GITHUB_ACTS:
            url = _text(_obj(extra.get(name)).get("url"))
            if url:
                return [url]
        repo = _text(extra.get("repo"))
        return [f"https://{entity_review.GITHUB_HOST}/{repo}"] if repo else []
    return []


def _repository(url: str) -> str | None:
    """`host/owner/name` of a link into a repository, the host as the link spells it."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    segments = [s for s in parts.path.split("/") if s]
    if not host or len(segments) < 2:
        return None
    return f"{host}/{segments[0]}/{segments[1].removesuffix('.git')}"


def money_of(lines: Sequence[Line], by_seq: Mapping[int, Touch]) -> dict[str, dict[str, dict[str, float]]]:
    """The ledger's in, out and net per year and currency, derived at read time from the ledger
    lines that touch the org (its `merchant` refs); a line the source marks deleted is not counted."""
    out: dict[str, dict[str, dict[str, float]]] = {}
    for line in lines:
        if line.get("kind") != TRANSACTION or int(line["seq"]) not in by_seq:
            continue
        payload = line.get("payload") or {}
        amount, currency = payload.get("amount"), payload.get("currency")
        if _obj(payload.get("extra")).get("deleted") is True:
            continue
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            continue
        if not isinstance(currency, str) or not currency:
            continue
        year = by_seq[int(line["seq"])].day[:4]
        cell = out.setdefault(year, {}).setdefault(currency, {"in": 0.0, "out": 0.0, "net": 0.0})
        cell["in" if amount > 0 else "out"] += float(amount)
        cell["net"] += float(amount)
    return dict(sorted(out.items(), reverse=True))


# -- text ----------------------------------------------------------------------------------------------------


def shelf_rows(s: Shelf) -> Iterator[str]:
    """`show orgs`: the headings of RFC 0037 §11, one line per org, the reason of a passed or let-go
    row in full on the next; then the people with more than one org."""
    if s.portfolio is not None and not s.portfolios_read:
        yield f"no org shown by portfolio: {PORTFOLIO_HIDDEN}"
        return
    if s.portfolio is not None and not s.rows:
        known = ", ".join(s.portfolios) or "none yet"
        yield f"no org is in {s.portfolio} (the portfolios: {known})"
        return
    if not s.rows:
        yield "no orgs: `logbook review org` names them from what the record already saw"
        return
    count = f"{len(s.rows)}" if s.portfolio is None else f"{len(s.rows)} in {s.portfolio}"
    head = f"orgs · {count} · {s.on} · tier {s.tier}"
    head += f" · money {s.year}" if s.money else " · money not shown"
    yield head
    if s.withheld:
        yield f"  {plural(s.withheld, 'status line')} not shown: an org's status is tier 3"
    names = {r.org.id: shown_name(r.org, [x.org for x in s.rows]) for r in s.rows}
    width = max(len(name) for name in names.values())
    for name, rows in s.grouped():
        yield name
        for r in rows:
            yield f"  {names[r.org.id]:<{width}}  {row_text(r)}"
            if r.status is not None and r.status.status in WITH_REASON and r.status.reason:
                yield f"  {'':<{width}}  reason: {r.status.reason}"
    if s.graph:
        yield "people with more than one org"
        for shared in s.graph:
            yield f"  {shared.name}: {', '.join(o.label for o in shared.orgs)}"


def shown_name(org: entities.Entity, among: Sequence[entities.Entity]) -> str:
    """An org's label, and when another org of `among` has the same label (case aside), what tells
    them apart: its dedupe key, else its id."""
    if sum(1 for o in among if o.label.casefold() == org.label.casefold()) < 2:
        return org.label
    return f"{org.label} ({org.key or org.id})"


def row_text(r: Row) -> str:
    parts = []
    if r.status is not None:
        who = r.status.proposed_by or "owner"
        if r.status.proposal is not None and who == "dream":
            who = f"dream proposed {r.status.proposal}"
        parts.append(f"{r.status.status} since {r.since} ({who})")
    if r.portfolio is not None:
        parts.append(f"portfolio {r.portfolio}")
    if r.stale:
        parts.append(f"stale: nothing since {r.stale_since}")
    parts.append("no touch" if r.last is None else f"last touch {r.last.day} {r.last_text or r.last.kind}")
    if r.people:
        first = ", ".join(p.name for p in r.people[:2])
        parts.append(f"{plural(len(r.people), 'person', 'people')} ({first})")
    if r.documents:
        parts.append(plural(r.documents, "document"))
    if r.money:
        parts.extend(money_text(currency, cell) for currency, cell in sorted(r.money.items()))
    return DOT.join(parts)


def page_rows(p: Page) -> Iterator[str]:
    """`show org NAME`: the page as text, its sections in the order of RFC 0037 §7."""
    refs = ", ".join(v for _k, v in p.org.refs)
    yield f"{p.org.label}" + (f" ({refs})" if refs else "") + f" · org · tier {p.tier}"
    if p.status is not None:
        line = f"  {p.status.status} since {p.since} ({p.status.proposed_by or 'owner'})"
        yield line + (f": {p.status.reason}" if p.status.reason else "")
    elif p.hidden:
        yield f"  {HIDDEN}"
    else:
        yield "  —"
    if p.portfolio is not None:
        yield f"  portfolio {p.portfolio}"
    if p.stale:
        yield f"  stale: nothing since {p.stale_since}, no touch and no status"
    if p.money:
        for year, currencies in p.money.items():
            for currency, cell in currencies.items():
                yield f"  {year} {money_text(currency, cell)}"
    yield "timeline"
    for item in p.timeline:
        yield f"  {item.day}  {item.kind:<11} {item.what}"
    if p.people or p.unplaced:
        yield "people"
        for person in p.people:
            yield f"  {person.name}: {plural(person.days, 'day')}, last {person.last}"
        if p.unplaced:
            yield f"  and {p.unplaced} not yet placed"
    for intro in p.introductions:
        yield f'  {intro.by} introduced {", ".join(intro.introduced)} ({intro.day}, "{intro.subject}")'
    if p.documents:
        yield "documents"
        for d in p.documents:
            shown = "" if d.kind == "mail" or d.ref == d.name.casefold() else f" ({d.ref})"
            yield f"  {d.day}  {d.kind:<5} {d.name}{shown}"
    if p.history:
        yield "status lines"
        for s in p.history:
            mark = " (current)" if s.current else "" if s.standing else " (retracted)"
            reason = f": {s.reason}" if s.reason else ""
            portfolio = portfolio_text(s.portfolio)
            yield f"  {s.day}  {s.status} ({s.proposed_by or 'owner'}){reason}{portfolio}{mark}"


def portfolio_text(field: str | None) -> str:
    """What a status line's `portfolio` field says, after the line: nothing when it carries none."""
    if field is None:
        return ""
    return f" · portfolio {field}" if field else " · portfolio cleared"


def money_text(currency: str, cell: Mapping[str, float]) -> str:
    return f"{currency} in {cell['in']:,.2f}, out {cell['out']:,.2f}, net {cell['net']:+,.2f}"


# -- small things --------------------------------------------------------------------------------------------


def _tier(line: Line) -> int:
    return int(line.get("tier") or 0)


def _status_org(line: Line) -> str | None:
    payload = line.get("payload") or {}
    entity = payload.get("entity")
    if payload.get("schema") != entities.STATUS_SCHEMA or entities.kind_of(entity) != ORG:
        return None
    entity_id = entity.get("id") if isinstance(entity, dict) else None
    return entity_id if isinstance(entity_id, str) and entity_id else None


def _status_day(line: Line, local: Any) -> str:
    since = _text((line.get("payload") or {}).get("since"))
    return since if since is not None else str(local(line.get("at")))


def _status_tier(s: entities.Status) -> int:
    return entities.status_tier(s.kind)


def _local(days: day_start.DayStart) -> Any:
    return lambda at: days.day(_instant(str(at))).isoformat()


def _instant(stamp: str) -> Any:
    found = stays.instant(stamp)
    assert found is not None
    return found


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
