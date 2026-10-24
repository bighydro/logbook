"""The ideas read back (RFC 0037 §7, §11) — `show ideas`, `show idea NAME` and the Ideas shelf under
`serve` — over the lines the entities foundation writes and reads (`logbook.contrib.entities`): the
ideas the `entity/v1` lines name (`entities.canonical`), the refs they bind (`entities.bindings`), and
the owner's `status/v1` lines (`entities.statuses`). It writes nothing (ADR 0013): `review idea` names
the ideas, `logbook status idea` disposes of them.

**A touch** is a standing line that resolves to a named idea through one of its refs (RFC 0037 §1): a
Notion page under its root (or a page it binds), an act on its repository or a link into it, a task
or a call of its title, each found as `review idea` finds them (`entity_review.idea_sightings`) and
looked up as the record binds them. A bot's line or an agent's (`entity_review.machine_line`) and a
relations line touch nothing, show nobody and add no words. Touches are read from the index at the
head every time, never stored. Each carries the canonical people on its line: a page's other editors,
a call's participants, an act's author (`people_review`'s counterparts, the owner and the not yet
placed left out of the names).

**The shelf** (`shelf`, `show ideas`) is every named idea under its current status, in the order
`build`, `exploring`, `spark`, `built`, `killed`, then no status (RFC 0037 §11); within a heading the
most recent touch first. A row says the status and since when, the reason (the latest the owner gave,
with the status it came with when that is not the current one: a killed idea that sparked again), the
last touch, the words written in the year (the Notion deltas), the repositories, how many people it
was discussed with and never their names (they are on its page: the owner's decision), the days since
its spark (its first touch), its latest titles, and `stale` (`entities.stale`: an `exploring` over two
years with nothing since, `stale_days` in `policy/entities.json`). **The page** (`page`, `show idea
NAME`) is one idea: its head and refs, its status and reason, first said, every touch newest first, the
people it was discussed with by name, its documents as references (its Notion pages with their titles
and word counts, its repositories with their README's versions), its title thread, the words by month,
and every status line, the one in force marked and a retracted one said so.

**Tiers.** An idea rests on lines at 2 or below and its status is tier 2 (RFC 0037 §8). A reader
through a gate (`tiers`) shows only the lines the gate reads; `show` and `serve` read every tier."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import PurePosixPath
from typing import Any, TypeGuard

from ..core import day_start, notes, present, stays
from ..core.chain import Line
from ..core.index import Index
from ..core.resolve import Ref
from ..core.store import Logbook, retractions
from . import entities, entity_review
from .entities import IDEA

KIND = IDEA
STAGES = ("build", "exploring", "spark", "built", "killed")  # RFC 0037 §11, in order; then no status
NO_STATUS = "no status"
TITLES = 2  # the latest titles a shelf row says
NOTION = entity_review.NOTION
DOT = " · "


class IdeaError(ValueError):
    """An idea the record does not name, or names several of; nothing to show."""


# -- touches ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Touch:
    """One standing line that resolves to a named idea, as what it already holds: never a body."""

    idea: str
    seq: int
    line: str
    day: str
    at: str
    kind: str
    source: str
    tier: int
    via: str  # the kind of ref it resolved through: page, repo, title
    what: str
    title: str | None  # the title the line holds, for the title thread: a page's, a task's, a call's
    words: int | None  # the words a Notion line added to its page
    total: int | None  # the page's words as the Notion line counts them
    page: str | None  # the Notion page it was on
    repo: str | None  # the repository it was on
    readme: tuple[int, int | None] | None  # a README's version: its words, and since the last
    people: tuple[str, ...]  # the canonical people on the line, the owner aside
    unplaced: tuple[str, ...]  # the observed people on it not yet placed, by their key


@dataclass
class Record:
    """What every reader of ideas reads, once: the named ideas, their status lines, every touch, the
    Notion pages, the people's names, today."""

    tiers: tuple[int, ...] | None
    ideas: dict[str, entities.Entity]
    statuses: dict[str, list[entities.Status]]  # standing, oldest first; the last is current
    lines: dict[str, list[Line]]  # every status line of each idea the gate reads, retracted ones too
    retracted: frozenset[str]
    touches: list[Touch]
    tree: entity_review.NotionTree
    names: dict[str, str]  # a canonical person → the label a resolution gives them
    settings: entities.Settings
    on: date
    local: Any = field(repr=False)

    def current(self, idea: str) -> entities.Status | None:
        history = self.statuses.get(idea, [])
        return history[-1] if history else None

    def touches_of(self, idea: str) -> list[Touch]:
        return [t for t in self.touches if t.idea == idea]


def _reads(tiers: tuple[int, ...] | None, line: Line) -> bool:
    return tiers is None or int(line.get("tier") or 0) in tiers


def read(lb: Logbook, tiers: Sequence[int] | None = None, today: str | None = None) -> Record:
    """The record as the idea readers see it through the gate of `tiers` (None: every tier), at its
    head. Writes nothing."""
    gate = None if tiers is None else tuple(sorted({int(t) for t in tiers}))
    with lb.index() as idx:
        return _read(lb, idx, gate, today)


def _read(lb: Logbook, idx: Index, gate: tuple[int, ...] | None, today: str | None) -> Record:
    meta = lb.meta
    days = day_start.of(meta)
    on = date.fromisoformat(today if today is not None else notes.today_in(days))
    marks = idx.retractions()
    retracted = frozenset(retractions(marks))
    ideas, bound, shown = _named(idx, gate, marks)
    history: dict[str, list[Line]] = {}
    for line in sorted(shown, key=lambda x: int(x["seq"])):
        history.setdefault(str(_status_idea(line)), []).append(line)
    folded = entities.statuses([*marks, *shown])
    ctx = entity_review.context(lb, idx)
    tree = entity_review.notion_tree(idx, ctx)
    names: dict[str, str] = {}
    for who in ctx.identities.values():
        if who.entity and who.label and who.type in present.PERSON_TYPES:
            names.setdefault(who.entity, who.label)
    return Record(
        gate,
        ideas,
        {i: found for (kind, i), found in folded.items() if kind == IDEA and i in ideas},
        history,
        retracted,
        _touches(lb, idx, ctx, tree, bound, gate) if ideas else [],
        tree,
        names,
        ctx.settings,
        on,
        _local(days),
    )


def _named(
    idx: Index, gate: tuple[int, ...] | None, marks: Sequence[Line]
) -> tuple[dict[str, entities.Entity], dict[Ref, str], list[Line]]:
    """(the ideas through the gate by id, the refs bound to them, their status lines the gate reads).
    An idea is one an `entity/v1` line names, or, when that line is retracted, one a standing status
    line still names, under the status line's label (RFC 0037 §3.4 rule 3)."""
    named = [line for line in idx.by_kind(entities.ENTITY) if _reads(gate, line)]
    ideas = {i: e for (kind, i), e in entities.canonical([*marks, *named]).items() if kind == IDEA}
    bound = {
        ref: entity_id
        for ref, (kind, entity_id) in entities.bindings([*marks, *named]).items()
        if kind == IDEA and entity_id in ideas
    }
    shown = [
        line for line in idx.by_kind(entities.STATUS) if _status_idea(line) is not None and _reads(gate, line)
    ]
    for (kind, entity_id), history in entities.statuses([*marks, *shown]).items():
        if kind == IDEA and entity_id not in ideas:
            label = next((s.label for s in reversed(history) if s.label), entity_id)
            ideas[entity_id] = entities.Entity(IDEA, entity_id, label)
    return ideas, bound, [line for line in shown if _status_idea(line) in ideas]


def _touches(
    lb: Logbook,
    idx: Index,
    ctx: entity_review.Context,
    tree: entity_review.NotionTree,
    bound: Mapping[Ref, str],
    gate: tuple[int, ...] | None,
) -> list[Touch]:
    """Every standing line the gate reads that resolves to a named idea through one of its refs: the
    line's own page or repository or title as bound, else its root page's. A Notion row whose `Type` is
    not `Idea` is still read here when the owner bound it: the type keeps a row out of the queue, never
    out of an idea the owner named."""
    found: list[Touch] = []
    for kind, lines in entity_review.idea_lines(lb, idx, ctx, tree).items():
        for line in lines:
            if not _reads(gate, line):
                continue
            hits: dict[str, entity_review.IdeaSighting] = {}
            for s in entity_review.idea_sightings(kind, line, ctx, tree):
                idea = bound.get(s.seen) or bound.get(s.key)
                if idea is not None:
                    hits.setdefault(idea, s)
            day = ctx.day(line) if hits else None
            if day is None:
                continue
            people, unplaced = _people_on(kind, line, ctx)
            for idea, s in hits.items():
                found.append(_touch(idea, s, kind, line, day, people, unplaced))
    return found


def _touch(
    idea: str,
    s: entity_review.IdeaSighting,
    kind: str,
    line: Line,
    day: str,
    people: tuple[str, ...],
    unplaced: tuple[str, ...],
) -> Touch:
    payload = line.get("payload") or {}
    extra = _obj(payload.get("extra"))
    title = _text(payload.get("title")) if kind in ("task", "transcript") or s.key[0] == "page" else None
    words = total = readme = None
    page = repo = None
    if s.key[0] == "page":
        page = s.seen[1].removeprefix("notion:")
        body = _obj(extra.get("body"))
        delta, counted = body.get("words_delta"), body.get("words")
        total = int(counted) if _count(counted) else None
        if _count(delta):
            words = int(delta)
        elif total is not None and extra.get("action") == "created":
            words = total
    if s.key[0] == "repo":
        repo = s.key[1]
        readme = _readme(extra)
    return Touch(
        idea,
        int(line["seq"]),
        str(line["id"]),
        day,
        str(line.get("at")),
        kind,
        str(line.get("source") or ""),
        int(line.get("tier") or 0),
        s.key[0],
        what(line),
        title,
        words,
        total,
        page,
        repo,
        readme,
        people,
        unplaced,
    )


def _readme(extra: Mapping[str, Any]) -> tuple[int, int | None] | None:
    """A README's version an act carries (`add github-export`): its words and the change since the
    path's last version; None for any other act."""
    file, content = _obj(extra.get("file")), _obj(extra.get("content"))
    path = _text(file.get("path"))
    if extra.get("action") != "revised" or path is None:
        return None
    if not PurePosixPath(path).name.casefold().startswith("readme") or not _count(content.get("words")):
        return None
    delta = content.get("words_delta")
    return int(content["words"]), int(delta) if _count(delta) else None


def _people_on(kind: str, line: Line, ctx: entity_review.Context) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(the canonical people on a line, the observed people on it not yet placed, by their key): a
    call's participants and an act's author (`people_review.counterparts`, which pass an agent over),
    a Notion page's editor when it is not the owner. The owner is nobody here."""
    from . import people_review  # its adapters (phone numbers) load when a line is read, never for --help
    from .adapters.ios_contacts import DIAL_PREFIX_ENV

    payload = line.get("payload") or {}
    people: list[str] = []
    unplaced: list[str] = []
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    for s in people_review.counterparts(kind, payload):
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
    actor = _obj(_obj(payload.get("extra")).get("actor"))
    name = _text(actor.get("name"))
    if line.get("source") == NOTION and name is not None and actor.get("role") != "owner":
        person = ctx.labels.get(entities.fold(name))
        if person is not None:
            if person not in people:
                people.append(person)
        elif " ".join(name.split()).casefold() not in ctx.owner.names and _text(actor.get("id")):
            seen = f"notion:{actor['id']}"
            if seen not in unplaced:
                unplaced.append(seen)
    return tuple(people), tuple(unplaced)


# -- what a line was ---------------------------------------------------------------------------------------


def what(line: Line) -> str:
    """One line as the timeline says it, from what the line already holds: a page's title and the
    titles above it, a word count, a commit's first line, a task's or a call's title, a url. A body is
    never shown because it is never stored; a commit's message is never read."""
    kind = str(line.get("kind"))
    payload = line.get("payload") or {}
    extra = _obj(payload.get("extra"))
    title = _text(payload.get("title"))
    if kind == "event" and line.get("source") == NOTION:
        path = [str(p) for p in extra.get("path") or [] if isinstance(p, str)]
        shown = " / ".join([*path[-1:], title or "untitled"])
        text = f'{_text(extra.get("action")) or "edited"} notion "{shown}"'
        body = _obj(extra.get("body"))
        if _count(body.get("words_delta")):
            text += f" {int(body['words_delta']):+,} words"
        elif _count(body.get("words")):
            text += f" ({int(body['words']):,} words)"
        return text
    if kind == "event":
        repo = _text(extra.get("repo")) or "a repository"
        found = _readme(extra)
        if found is not None:
            since = f", {found[1]:+,}" if found[1] is not None else ""
            return f"{title or 'README'} revised in {repo} ({found[0]:,} words{since})"
        action = _text(extra.get("action")) or "act"
        return f'{"commit" if action == "committed" else action} {repo} "{title or "untitled"}"'
    if kind == "task":
        return f'task "{title or "untitled"}"'
    if kind == "transcript":
        return f'transcript "{title or "untitled"}"'
    if kind == "browse":
        return f"browsed {_text(payload.get('url')) or ''}".strip()
    return kind


# -- the shelf ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Involved:
    person: str
    name: str
    touches: int
    days: int
    last: str

    def to_json(self) -> dict[str, Any]:
        return {"id": self.person, "name": self.name, "touches": self.touches, "days": self.days,
                "last": self.last}  # fmt: skip


@dataclass(frozen=True)
class Reason:
    """The owner's words on an idea's status: the day, the status they came with, the words, the
    line, and the note that carries them (RFC 0037 §10.5)."""

    day: str
    status: str
    reason: str
    line: str
    note: str | None

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day, "status": self.status, "reason": self.reason, "line": self.line,
                "note": self.note}  # fmt: skip


@dataclass(frozen=True)
class Row:
    """One named idea on the shelf: titles, counts and the owner's reason, never a person's name."""

    idea: entities.Entity
    status: entities.Status | None
    since: str | None
    stale: bool
    stale_since: str | None
    last: Touch | None
    touches: int
    words: int  # written in the shelf's year
    repos: list[str]
    pages: int
    people: int  # how many it was discussed with: their names are on its page
    first: str | None  # the day of its first touch: its spark
    days: int | None  # since then, to today
    titles: list[str]  # its latest titles, newest first
    reasons: list[Reason]  # oldest first
    tier: int

    @property
    def heading(self) -> str:
        return heading(self.status)

    @property
    def reason(self) -> Reason | None:
        return self.reasons[-1] if self.reasons else None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.idea.id,
            "name": self.idea.label,
            "key": self.idea.key,
            "heading": self.heading,
            "status": None if self.status is None else self.status.status,
            "since": self.since,
            "proposed_by": None if self.status is None else self.status.proposed_by,
            "reason": None if self.reason is None else self.reason.reason,
            "reasons": [r.to_json() for r in self.reasons],
            "stale": self.stale,
            "stale_since": self.stale_since,
            "last_touch": None
            if self.last is None
            else {
                "day": self.last.day,
                "kind": self.last.kind,
                "what": self.last.what,
                "line": self.last.line,
            },
            "touches": self.touches,
            "words": self.words,
            "repositories": self.repos,
            "pages": self.pages,
            "people": self.people,
            "first": self.first,
            "days_since_spark": self.days,
            "titles": self.titles,
            "tier": self.tier,
        }


@dataclass(frozen=True)
class Shelf:
    rows: list[Row]
    on: str
    year: str
    tier: int | None

    def grouped(self) -> list[tuple[str, list[Row]]]:
        """The rows under their headings, in the order of RFC 0037 §11, the empty ones left out."""
        return [
            (name, found)
            for name in (*STAGES, NO_STATUS)
            if (found := [r for r in self.rows if r.heading == name])
        ]

    def to_json(self) -> dict[str, Any]:
        return {
            "on": self.on,
            "year": self.year,
            "tier": self.tier,
            "ideas": [r.to_json() for r in self.rows],
        }


def heading(status: entities.Status | None) -> str:
    """The shelf's heading for a current status (RFC 0037 §11): the status itself, else no status."""
    return NO_STATUS if status is None else status.status


def shelf(
    lb: Logbook, tiers: Sequence[int] | None = None, year: str | None = None, today: str | None = None
) -> Shelf:
    """Every named idea under its heading, the most recent touch first (none last, by name); through
    the gate of `tiers`. Writes nothing."""
    return shelf_of(read(lb, tiers, today), year)


def shelf_of(rec: Record, year: str | None = None) -> Shelf:
    if year is not None and not re.fullmatch(r"\d{4}", year.strip()):
        raise IdeaError(f"--year {year!r} is not a year, YYYY")
    wanted = year.strip() if year is not None else str(rec.on.year)
    by_idea: dict[str, list[Touch]] = {}
    for t in rec.touches:
        by_idea.setdefault(t.idea, []).append(t)
    rows: list[Row] = []
    for idea in rec.ideas.values():
        mine = sorted(by_idea.get(idea.id, []), key=lambda t: (t.day, t.seq))
        last = mine[-1] if mine else None
        current = rec.current(idea.id)
        stale, stale_since = _staleness(rec, current, last)
        first = mine[0].day if mine else None
        rows.append(
            Row(
                idea,
                current,
                None if current is None else current.day(rec.local),
                stale,
                stale_since,
                last,
                len(mine),
                sum(t.words or 0 for t in mine if t.day.startswith(wanted)),
                repositories(idea, mine),
                len({t.page for t in mine if t.page is not None}),
                len({p for t in mine for p in t.people}) + len({u for t in mine for u in t.unplaced}),
                first,
                None if first is None else (rec.on - date.fromisoformat(first)).days,
                titles(mine)[:TITLES],
                reasons(rec, idea.id),
                max([entities.TIER, *(t.tier for t in mine)]),
            )
        )
    rows.sort(key=lambda r: r.idea.label.casefold())
    rows.sort(key=lambda r: ("", 0) if r.last is None else (r.last.day, r.last.seq), reverse=True)
    return Shelf(rows, rec.on.isoformat(), wanted, max((r.tier for r in rows), default=None))


def _staleness(rec: Record, current: entities.Status | None, last: Touch | None) -> tuple[bool, str | None]:
    """Whether the current status is stale (`entities.stale`, with the last touch) and since when."""
    if current is None:
        return False, None
    touched = None if last is None else last.day
    if not entities.stale(current, rec.on, rec.local, rec.settings.stale_days, touched):
        return False, None
    return True, max(current.day(rec.local), touched or "")


def repositories(idea: entities.Entity, touches: Sequence[Touch]) -> list[str]:
    """Its repositories: the ones its refs bind, then the ones its touches were on, each once."""
    found = [v for k, v in idea.refs if k == "repo"]
    found += [t.repo for t in touches if t.repo is not None and t.repo not in found]
    return list(dict.fromkeys(found))


def titles(touches: Sequence[Touch]) -> list[str]:
    """The title thread: the titles its lines hold, newest first, each once (case aside)."""
    found: dict[str, str] = {}
    for t in sorted(touches, key=lambda t: (t.day, t.seq), reverse=True):
        if t.title is not None and t.title.casefold() not in found:
            found[t.title.casefold()] = t.title
    return list(found.values())


def reasons(rec: Record, idea: str) -> list[Reason]:
    """The owner's reasons on the idea's status lines, oldest first: every line not retracted, the ones
    a later status replaced among them (a killed idea that sparked again keeps its reason, RFC 0037
    §11), each with the note its line names (§10.5)."""
    found = []
    for line in rec.lines.get(idea, []):
        payload = line.get("payload") or {}
        reason = _text(payload.get("reason"))
        if reason is not None and str(line["id"]) not in rec.retracted:
            status = str(payload.get("status"))
            day = _status_day(line, rec.local)
            found.append(Reason(day, status, reason, str(line["id"]), _text(payload.get("note"))))
    return found


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


# -- the page ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    """One row of an idea's timeline."""

    day: str
    at: str
    kind: str
    source: str
    line: str
    what: str
    via: str
    tier: int

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day, "at": self.at, "kind": self.kind, "source": self.source, "what": self.what,
                "via": self.via, "tier": self.tier, "line": self.line}  # fmt: skip


@dataclass(frozen=True)
class Document:
    """Where an idea lives, as a reference and never a copy: a Notion page (its title, the titles above
    it, its id and link, its words as its latest line counts them) or a repository (its README's versions
    and words)."""

    kind: str  # `notion` or `repo`
    name: str
    ref: str  # the page's id, the repository's `host/owner/name`
    path: tuple[str, ...]
    url: str | None
    words: int | None
    versions: int  # a repository's README versions
    first: str
    last: str
    lines: int

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "ref": self.ref, "path": list(self.path),
                "url": self.url, "words": self.words, "versions": self.versions, "first": self.first,
                "last": self.last, "lines": self.lines}  # fmt: skip


@dataclass(frozen=True)
class StatusLine:
    """One status line of the idea, as the page's history says it: `standing` unless retracted, and
    `current` for the one in force (each later line supersedes the one before it)."""

    day: str
    status: str
    proposed_by: str | None
    reason: str | None
    line: str
    standing: bool
    current: bool

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day, "status": self.status, "proposed_by": self.proposed_by,
                "reason": self.reason, "line": self.line, "standing": self.standing,
                "current": self.current}  # fmt: skip


@dataclass(frozen=True)
class Page:
    idea: entities.Entity
    status: entities.Status | None
    since: str | None
    reason: Reason | None
    stale: bool
    stale_since: str | None
    first: Item | None  # first said: its earliest touch
    timeline: list[Item]  # newest first
    people: list[Involved]
    unplaced: int
    documents: list[Document]
    titles: list[str]
    words: dict[str, int]  # month → the words written in it
    repositories: list[str]
    days: int | None  # since its spark
    history: list[StatusLine]
    on: str
    tier: int

    def to_json(self) -> dict[str, Any]:
        return {
            "idea": self.idea.to_json(),
            "status": None
            if self.status is None
            else {
                "status": self.status.status,
                "since": self.since,
                "reason": self.status.reason,
                "proposed_by": self.status.proposed_by,
                "line": self.status.line,
                "note": self.status.note,
            },
            "reason": None if self.reason is None else self.reason.to_json(),
            "stale": self.stale,
            "stale_since": self.stale_since,
            "first": None if self.first is None else self.first.to_json(),
            "timeline": [i.to_json() for i in self.timeline],
            "people": [p.to_json() for p in self.people],
            "unplaced": self.unplaced,
            "documents": [d.to_json() for d in self.documents],
            "titles": self.titles,
            "words_by_month": self.words,
            "repositories": self.repositories,
            "days_since_spark": self.days,
            "history": [s.to_json() for s in self.history],
            "on": self.on,
            "tier": self.tier,
        }


def named(lb: Logbook, tiers: Sequence[int] | None = None) -> dict[str, entities.Entity]:
    """The ideas the record names through the gate of `tiers` (None: every tier), by id: its naming
    lines and its status lines alone, no touch swept (what a form or a name is checked against)."""
    gate = None if tiers is None else tuple(sorted({int(t) for t in tiers}))
    with lb.index() as idx:
        return _named(idx, gate, idx.retractions())[0]


def find(lb: Logbook, name: str, tiers: Sequence[int] | None = None) -> entities.Entity:
    """The one named idea `name` names, as `status idea NAME` finds it (`entities.lookup`: a ref, an
    id, a label or an alias, a word of a label); `IdeaError` for none or several."""
    try:
        return entities.lookup({(IDEA, e.id): e for e in named(lb, tiers).values()}, IDEA, name)
    except entities.EntityError as e:
        raise IdeaError(str(e)) from e


def page(lb: Logbook, idea_id: str, tiers: Sequence[int] | None = None, today: str | None = None) -> Page:
    """One idea's page through the gate; `IdeaError` when the record names no such idea."""
    return page_of(read(lb, tiers, today), idea_id)


def page_of(rec: Record, idea_id: str) -> Page:
    idea = rec.ideas.get(idea_id)
    if idea is None:
        raise IdeaError(f"no idea {idea_id} in this record")
    mine = sorted(rec.touches_of(idea_id), key=lambda t: (t.day, t.at, t.seq))
    items = [Item(t.day, t.at, t.kind, t.source, t.line, t.what, t.via, t.tier) for t in mine]
    current = rec.current(idea_id)
    stale, stale_since = _staleness(rec, current, mine[-1] if mine else None)
    in_force = None if current is None else current.line
    history = [
        StatusLine(
            _status_day(line, rec.local),
            str((line.get("payload") or {}).get("status")),
            _text((line.get("payload") or {}).get("proposed_by")),
            _text((line.get("payload") or {}).get("reason")),
            str(line["id"]),
            str(line["id"]) not in rec.retracted,
            str(line["id"]) == in_force,
        )
        for line in rec.lines.get(idea_id, [])
    ]
    words: dict[str, int] = {}
    for t in mine:
        if t.words is not None:
            words[t.day[:7]] = words.get(t.day[:7], 0) + t.words
    found = reasons(rec, idea_id)
    first = mine[0].day if mine else None
    return Page(
        idea,
        current,
        None if current is None else current.day(rec.local),
        found[-1] if found else None,
        stale,
        stale_since,
        items[0] if items else None,
        list(reversed(items)),
        involved(mine, rec.names),
        len({u for t in mine for u in t.unplaced}),
        documents(rec, mine),
        titles(mine),
        dict(sorted(words.items())),
        repositories(idea, mine),
        None if first is None else (rec.on - date.fromisoformat(first)).days,
        history,
        rec.on.isoformat(),
        max([entities.TIER, *(t.tier for t in mine)]),
    )


def documents(rec: Record, touches: Sequence[Touch]) -> list[Document]:
    """Its Notion pages and its repositories, the most recently touched first, each once, as
    references: a page's title, the titles above it, its id, its link and its words as of its last
    touch (a bot's edit is none, so its words are not counted here either); a repository's README
    versions and the latest's words."""
    pages: dict[str, list[Touch]] = {}
    repos: dict[str, list[Touch]] = {}
    for t in touches:
        if t.page is not None:
            pages.setdefault(t.page, []).append(t)
        if t.repo is not None:
            repos.setdefault(t.repo, []).append(t)
    found: list[Document] = []
    for page_id, mine in pages.items():
        known = rec.tree.pages.get(page_id)
        counted = max((t for t in mine if t.total is not None), key=lambda t: (t.day, t.seq), default=None)
        found.append(
            Document(
                "notion",
                (known.title if known is not None else None) or "untitled",
                page_id,
                known.path if known is not None else (),
                known.url if known is not None else None,
                None if counted is None else counted.total,
                0,
                min(t.day for t in mine),
                max(t.day for t in mine),
                len(mine),
            )
        )
    for repo, mine in repos.items():
        readmes = [t for t in mine if t.readme is not None]
        latest = max(readmes, key=lambda t: (t.day, t.seq), default=None)
        found.append(
            Document(
                "repo",
                repo,
                repo,
                (),
                None,
                None if latest is None or latest.readme is None else latest.readme[0],
                len(readmes),
                min(t.day for t in mine),
                max(t.day for t in mine),
                len(mine),
            )
        )
    return sorted(found, key=lambda d: (d.last, d.kind, d.name), reverse=True)


# -- text ----------------------------------------------------------------------------------------------------


def shelf_rows(s: Shelf) -> Iterator[str]:
    """`show ideas`: the headings of RFC 0037 §11, one line per idea, its reason on the next; the people
    it was discussed with counted, never named."""
    if not s.rows:
        yield "no ideas: `logbook review idea` names them from what Notion, the repositories, the calls and"
        yield "the tasks already hold"
        return
    yield f"ideas{DOT}{len(s.rows)}{DOT}{s.on}{DOT}tier {s.tier}"
    width = max(len(r.idea.label) for r in s.rows)
    for name, rows in s.grouped():
        yield name
        for r in rows:
            yield f"  {r.idea.label:<{width}}  {row_text(r, s.year)}"
            reason = r.reason
            if reason is not None:
                yield f"  {'':<{width}}  reason{_earlier(r.status, reason)}: {reason.reason}"


def _earlier(status: entities.Status | None, reason: Reason) -> str:
    """How a reason is said when it is not the current status line's own: with its status and day."""
    return "" if status is not None and reason.line == status.line else f" ({reason.status} {reason.day})"


def row_text(r: Row, year: str) -> str:
    parts = []
    if r.status is not None:
        parts.append(f"{r.status.status} since {r.since} ({r.status.proposed_by or 'owner'})")
    if r.stale:
        parts.append(f"stale: nothing since {r.stale_since}")
    parts.append("no touch" if r.last is None else f"last touch {r.last.day} {r.last.what}")
    if r.words:
        parts.append(f"{r.words:+,} words in {year}")
    parts.extend(r.repos)
    if r.people:
        parts.append(plural(r.people, "person", "people"))
    if r.days is not None:
        parts.append(f"{plural(r.days, 'day')} since spark")
    if r.titles:
        parts.append("titles " + ", ".join(f'"{t}"' for t in r.titles))
    return DOT.join(parts)


def page_rows(p: Page) -> Iterator[str]:
    """`show idea NAME`: the page as text, its sections in the order of RFC 0037 §7, then the idea's own."""
    refs = ", ".join(v for _k, v in p.idea.refs)
    yield f"{p.idea.label}" + (f" ({refs})" if refs else "") + f"{DOT}idea{DOT}tier {p.tier}"
    if p.status is not None:
        line = f"  {p.status.status} since {p.since} ({p.status.proposed_by or 'owner'})"
        yield line + (f": {p.status.reason}" if p.status.reason else "")
    else:
        yield "  —"
    if p.reason is not None and _earlier(p.status, p.reason):
        yield f"  reason{_earlier(p.status, p.reason)}: {p.reason.reason}"
    if p.stale:
        yield f"  stale: nothing since {p.stale_since}, no touch and no status"
    if p.first is not None:
        yield f"  first said {p.first.day}: {p.first.what}" + (
            f"{DOT}{plural(p.days, 'day')} since" if p.days is not None else ""
        )
    yield "timeline"
    for item in p.timeline:
        yield f"  {item.day}  {item.kind:<11} {item.what}"
    if p.people or p.unplaced:
        yield "people"
        for person in p.people:
            yield f"  {person.name}, last {person.last}"  # the most days first, never their count
        if p.unplaced:
            yield f"  and {p.unplaced} not yet placed"
    if p.documents:
        yield "documents"
        for d in p.documents:
            yield f"  {d.last}  {d.kind:<6} {document_text(d)}"
    if p.titles:
        yield "titles"
        for title in p.titles:
            yield f"  {title}"
    if p.words:
        yield "words"
        yield "  " + ", ".join(f"{month} {n:+,}" for month, n in p.words.items())
    if p.history:
        yield "status lines"
        for s in p.history:
            mark = " (current)" if s.current else "" if s.standing else " (retracted)"
            reason = f": {s.reason}" if s.reason else ""
            yield f"  {s.day}  {s.status} ({s.proposed_by or 'owner'}){reason}{mark}"


def document_text(d: Document) -> str:
    if d.kind == "notion":
        where = " / ".join([*d.path, d.name])
        return f'"{where}"' + (f"{DOT}{d.words:,} words" if d.words is not None else "") + f" ({d.ref})"
    readme = f"{DOT}README {plural(d.versions, 'version')}" if d.versions else ""
    words = f", {d.words:,} words" if d.words is not None and d.versions else ""
    return f"{d.name}{readme}{words}"


# -- small things --------------------------------------------------------------------------------------------


def _status_idea(line: Line) -> str | None:
    payload = line.get("payload") or {}
    entity = payload.get("entity")
    if payload.get("schema") != entities.STATUS_SCHEMA or entities.kind_of(entity) != IDEA:
        return None
    entity_id = entity.get("id") if isinstance(entity, dict) else None
    return entity_id if isinstance(entity_id, str) and entity_id else None


def _status_day(line: Line, local: Any) -> str:
    since = _text((line.get("payload") or {}).get("since"))
    return since if since is not None else str(local(line.get("at")))


def _local(days: day_start.DayStart) -> Any:
    """A line's `at` as its local day; a stamp that is no instant, as its own first ten characters."""

    def local(at: object) -> str:
        found = stays.instant(str(at))
        return str(at)[:10] if found is None else days.day(found).isoformat()

    return local


def _count(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _obj(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {plural or noun + 's'}"
