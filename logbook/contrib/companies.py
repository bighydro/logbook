"""The companies a day touched (RFC 0043 §11, §12) — `logbook lab companies DAY [--json]`, and the Day's
Companies row when a page shows it: the orgs the Manifest names (`orgs`, over the lines the entities
foundation writes) that one local day's lines touched, each with what touched it and the lines. It
writes nothing (ADR 0013).

**What touches an org**, through the refs the record binds to it (`entity_review.org_sightings`, as
`show orgs` finds its touches), on a standing line of the day the gate reads:

- an **update**: a mail from an address at one of its domains;
- a **mail**: a mail to or copied to someone at one of its domains, the owner's own mail to them;
- a **meeting**: a calendar entry with an attendee (who did not decline) or an organizer at one of its
  domains, a transcript with a participant there, a call whose counterparty is an address there;
- a **document**: a link into one of its repositories (a page browsed, a task, an act `sync github`
  wrote), as the org's page lists its documents (`orgs.documents`).

A touch names the people of theirs on the line, the record's label for each address at the org's
domain, else the name the line shows it under, else `someone at <org>`: never a bare
address. A group chat and a
merchant bind an org too; neither is an update, a meeting or a document, and the money is the money
slot's (`core.money`).

**Status and portfolio** are tier 3 (RFC 0037 §8, §10.2 amended 15 October 2026): a row carries its
org's current status and the portfolio its latest status line names (`entities.portfolios`; the
Manifest's `entity/v1` line never carries one) only when the gate reads tier 3, and the rows group by
portfolio, in its words, the orgs in none last. Through a gate without 3 no row carries either, every
row is in one group, and the reading says the status is not shown (`orgs.HIDDEN`).

**Cost**: one day's lines through the `day_local` index, and the naming lines (`resolution`, `entity/v1`,
`status/v1`, retractions) by kind, as `show orgs` reads them; never a sweep of the record's mail."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..core.chain import Line
from ..core.export import parse_day
from ..core.index import Index
from ..core.resolve import Ref
from ..core.store import Logbook, retractions
from . import entities, entity_review, orgs

UPDATE, MAIL, MEETING, DOCUMENT = "update", "mail", "meeting", "document"
MEETING_KINDS = ("event", "transcript", "call")
DOCUMENT_KINDS = ("browse", "task", "event")
KINDS = ("mail", "event", "transcript", "call", "browse", "task")  # the kinds a day's touch is read from
NO_PORTFOLIO = "no portfolio"
DOT = " · "


@dataclass(frozen=True)
class Touched:
    """One line that touched an org: what it was, the line, its title, the people of theirs on it."""

    what: str  # UPDATE, MAIL, MEETING or DOCUMENT
    kind: str
    line: str
    seq: int
    title: str | None
    people: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "what": self.what,
            "kind": self.kind,
            "line": self.line,
            "seq": self.seq,
            "title": self.title,
            "people": list(self.people),
        }


@dataclass
class Company:
    """One org the day touched: its id and name, its status and portfolio when tier 3 is read, and
    what touched it, in chain order."""

    org: str
    name: str
    status: str | None
    portfolio: str | None
    touches: list[Touched] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "org": self.org,
            "name": self.name,
            "status": self.status,
            "portfolio": self.portfolio,
            "touches": [t.to_json() for t in self.touches],
        }


@dataclass(frozen=True)
class Companies:
    """The orgs one day touched, and whether their statuses were read (tier 3)."""

    day: str
    rows: list[Company]
    statuses: bool

    def groups(self) -> list[tuple[str | None, list[Company]]]:
        """The rows by portfolio, the portfolios in order (case aside), the orgs in none last; one
        group, None, when no row carries one."""
        by: dict[str | None, list[Company]] = {}
        for row in self.rows:
            by.setdefault(row.portfolio, []).append(row)
        named = sorted((p for p in by if p is not None), key=lambda p: (p.casefold(), p))
        return [(p, by[p]) for p in [*named, None] if p in by]

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "statuses": self.statuses,
            "hidden": None if self.statuses else orgs.HIDDEN,
            "groups": [
                {"portfolio": p, "companies": [c.to_json() for c in rows]} for p, rows in self.groups()
            ],
        }


def companies_of(lb: Logbook, day: str, tiers: Sequence[int] | None = None) -> Companies:
    """The orgs the Manifest names that `day`'s standing lines touched, through the gate of `tiers`
    (None: every tier, as the owner's terminal reads). `ValueError` for a day that is not one."""
    day = parse_day(day).isoformat()
    g = orgs.gate(tiers)
    statuses = g.reads(entities.status_tier(entities.ORG))
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = frozenset(retractions(marks))
        named, bound, shown, _hidden = orgs._named(idx, g, marks, retracted)
        if not named:
            return Companies(day, [], statuses)
        ctx = entity_review.context(lb, idx)
        labels = {org: e.label for org, e in named.items()}
        touched = _touched(idx, idx.day(day), ctx, bound, labels, g)
    current = {
        entity_id: history[-1].status
        for (kind, entity_id), history in entities.statuses([*marks, *shown]).items()
        if kind == entities.ORG and history
    }
    held = entities.portfolios([*marks, *shown]) if statuses else {}
    rows = [
        Company(
            org,
            named[org].label,
            current.get(org) if statuses else None,
            held.get(org) if statuses else None,
            found,
        )
        for org, found in touched.items()
    ]
    rows.sort(key=lambda c: (c.name.casefold(), c.org))
    return Companies(day, rows, statuses)


def _touched(
    idx: Index,
    lines: Sequence[Line],
    ctx: entity_review.Context,
    bound: Mapping[Ref, str],
    labels: Mapping[str, str],
    g: orgs.Gate,
) -> dict[str, list[Touched]]:
    """org → what touched it among a day's `lines`: the standing ones of `KINDS` the gate reads."""
    superseded = {kind: idx.superseded(kind) for kind in {str(x.get("kind")) for x in lines} if kind in KINDS}
    names = _names(ctx)
    found: dict[str, list[Touched]] = {}
    for line in sorted(lines, key=lambda x: int(x["seq"])):
        kind = str(line.get("kind"))
        line_id = str(line.get("id"))
        if kind not in KINDS or line_id in ctx.retracted or line_id in superseded.get(kind, {}):
            continue
        if not g.reads(int(line.get("tier") or 0)):
            continue
        for org, what in _what(kind, line, ctx, bound).items():
            people = (
                _people(kind, line, ctx, bound, org, labels.get(org, org), names) if what != DOCUMENT else ()
            )
            found.setdefault(org, []).append(
                Touched(what, kind, line_id, int(line["seq"]), _title(kind, line), people)
            )
    return found


def _what(kind: str, line: Line, ctx: entity_review.Context, bound: Mapping[Ref, str]) -> dict[str, str]:
    """org → what this line was to it; an org the line touches twice is the first way it does."""
    payload = line.get("payload") or {}
    found: dict[str, str] = {}
    if kind == "call":
        for address in _call_addresses(payload):
            called = _org_of(address, ctx, bound)
            if called is not None:
                found.setdefault(called, MEETING)
        return found
    if kind == "mail":
        sender = payload.get("from")
        for item in sender if isinstance(sender, list) else [sender]:
            email = item.get("email") if isinstance(item, dict) else None
            sent = _org_of(email, ctx, bound) if isinstance(email, str) else None
            if sent is not None:
                found.setdefault(sent, UPDATE)
    for s in entity_review.org_sightings(kind, line, ctx):
        org = bound.get(s.key)
        if org is None:
            continue
        if s.key[0] == "domain":
            found.setdefault(org, MAIL if kind == "mail" else MEETING)
        elif s.key[0] == "repo" and kind in DOCUMENT_KINDS:
            found.setdefault(org, DOCUMENT)
    return found


def _people(
    kind: str,
    line: Line,
    ctx: entity_review.Context,
    bound: Mapping[Ref, str],
    org: str,
    label: str,
    names: Mapping[str, str],
) -> tuple[str, ...]:
    """The people of `org` (named `label`) on the line: each address at one of its domains as the
    record names it, else as the line shows it, else `someone at <org>`; never a bare address."""
    payload = line.get("payload") or {}
    addresses: list[tuple[str, str | None]]
    if kind == "call":
        addresses = [(a, None) for a in _call_addresses(payload)]
    else:
        addresses = [
            (a, _shown_name(payload, a)) for a, _name, _person in entity_review._addresses(kind, payload, ctx)
        ]
    out: list[str] = []
    for address, shown in addresses:
        if _org_of(address, ctx, bound) != org:
            continue
        person = ctx.person(("email", address))
        candidates = (names.get(person) if person is not None else None, shown)
        name = next((c for c in candidates if c and "@" not in c), f"someone at {label}")
        if name not in out:
            out.append(name)
    return tuple(out)


def _org_of(address: str, ctx: entity_review.Context, bound: Mapping[Ref, str]) -> str | None:
    domain = entity_review._domain_of(address.strip().casefold(), ctx)
    return None if domain is None else bound.get(("domain", domain))


def _call_addresses(payload: Mapping[str, Any]) -> list[str]:
    """A call's counterparty when it is an address (RFC 0012: a FaceTime call by email)."""
    ref = payload.get("counterparty")
    if isinstance(ref, dict) and ref.get("kind") == "email" and isinstance(ref.get("value"), str):
        return [ref["value"].strip().casefold()]
    return []


def _shown_name(payload: Mapping[str, Any], address: str) -> str | None:
    """The display name a mail gives `address` in any of its headers, a transcript its participant or a
    calendar entry its attendee, else None."""
    for header in ("from", "to", "cc", "bcc", "participants", "attendees"):
        value = payload.get(header)
        for item in value if isinstance(value, list) else [value]:
            if not isinstance(item, dict):
                continue
            ref = item.get("ref")
            email = ref.get("value") if header == "attendees" and isinstance(ref, dict) else item.get("email")
            name = item.get("name")
            if str(email or "").strip().casefold() == address and isinstance(name, str) and name.strip():
                return " ".join(name.split())
    return None


def _names(ctx: entity_review.Context) -> dict[str, str]:
    """A canonical person → the label a resolution gives them."""
    found: dict[str, str] = {}
    for who in ctx.identities.values():
        if who.entity and who.label:
            found.setdefault(who.entity, who.label)
    return found


def _title(kind: str, line: Line) -> str | None:
    payload = line.get("payload") or {}
    value = payload.get("subject") if kind == "mail" else payload.get("title")
    if isinstance(value, str) and value.strip():
        return " ".join(value.split())
    return None


# -- text ----------------------------------------------------------------------------------------------------


def rows(found: Companies) -> Iterator[str]:
    """The reading as text: the day and how many, the status said hidden when it is, then each group's
    portfolio (when any row has one) and its orgs, each touch under its org."""
    if not found.rows:
        yield f"{found.day}{DOT}no org the Manifest names touched this day"
        return
    n = len(found.rows)
    yield f"{found.day}{DOT}{n} {'company' if n == 1 else 'companies'}"
    if not found.statuses:
        yield orgs.HIDDEN
    groups = found.groups()
    for portfolio, companies in groups:
        if len(groups) > 1 or portfolio is not None:
            yield portfolio if portfolio is not None else NO_PORTFOLIO
        for c in companies:
            yield f"  {c.name}" + (f"  {c.status}" if c.status else "")
            for t in c.touches:
                parts = [t.what, t.title or t.kind]
                if t.people:
                    parts.append(f"with {', '.join(t.people)}")
                yield f"    {'  '.join(parts)}  #{t.seq}"
