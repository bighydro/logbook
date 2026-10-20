"""The Goals shelf of `logbook serve` (RFC 0036): `/goals`, the chapter the owner is in and the goals
by horizon, and `/goals/ID`, one goal and its review thread. Read-only: no form, no act.

What it reads is the owner's own lines and nothing derived: the `chapter/v1` lines (`core.chapter`),
the `goal/v1` lines and the `review/v1` lines (`core.goals`), through the page's gate (`tiers`, as
`reading.crossing` reads it; every one of them is tier 2, so a gate without tier 2 shows none). The
**chapter** is the standing chapter today is in (rule 3), the clash beside it when another standing
chapter holds the day too (rule 4), and the other standing chapters listed under it. A **goal** is a
standing goal (the latest line of its chain of `supersedes`), under its horizon (life, year,
quarter), with its state (`goals.state`: open, or done, let go, superseded, past) and its standing
review's disposition and day. A goal's page is reached by the id of any line of its chain: its
wording and every earlier wording, then every review of the chain, the newest first, each with its
period, its day, its note, and when it was written on a later day than its verdict. A review whose
`extra.lines` names lines of the record says what the verdict rests on; those that are a session
with an agent (`shelf_agents.is_session`) are listed as the sessions that served the goal, and no
session is ever placed with a goal on any other ground.

The page says the highest tier it read. Nothing is written and no connection is opened."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from ..core import chapter, day_start, goals, reading
from ..core.chain import Line
from ..core.store import Logbook, retractions
from . import shelf_agents

if TYPE_CHECKING:  # the Site passes itself; serve imports this module, never the other way at import
    from .serve import Site

HORIZON_NAMES = {goals.LIFE: "Life", goals.YEAR: "This year", goals.QUARTER: "This quarter"}
ADD_FIRST = "logbook goal import ~/goals.txt"  # the empty shelf's one instruction
FILE_SHAPE = "Sail the whole coast to Lofoten | life"  # a line of that file, as the shelf shows it
DOT = goals.DOT
SHELF_STYLE = """
.badge{display:inline-block;font-size:.75rem;text-transform:uppercase;letter-spacing:.05em;padding:0 .35rem;
border:1px solid var(--line);border-radius:3px;color:var(--mute)}
.badge.advancing,.badge.open{color:#2e8b57}.badge.stalled,.badge.past{color:#c0652a}
p.facts{margin:.1rem 0;color:var(--mute);overflow-wrap:anywhere}
p.note{margin:.2rem 0 0;font-style:italic;overflow-wrap:anywhere}
pre.file{white-space:pre-wrap;overflow-wrap:anywhere;max-width:100%}
"""  # what the Goals pages add to the one stylesheet; every rule keeps to the column


class GoalNotFound(LookupError):
    """No goal line the page reads has this id."""


@dataclass(frozen=True)
class Review:
    """One `review/v1` line of a goal's chain, as the shelf shows it."""

    line: str
    day: str
    disposition: str
    period: str
    note: str | None
    written: str | None  # the local day `recorded_at` falls on, when later than `day`
    lines: tuple[str, ...]  # what `extra.lines` names: the lines the verdict rests on
    tier: int


@dataclass(frozen=True)
class Goal:
    """A standing goal: its line, wording, horizon, bounds, state, its standing review and every review
    of its chain (the newest first), its earlier wordings (the oldest first) and the sessions that
    the reviews say served it."""

    line: str
    text: str
    horizon: str
    start: str
    until: str | None
    state: str
    review: Review | None
    reviews: tuple[Review, ...]
    earlier: tuple[tuple[str, str], ...]  # (line, text) of the lines it supersedes
    served: tuple[tuple[str, str], ...]  # (session line, its day) a review names
    tier: int


@dataclass(frozen=True)
class Chapter:
    line: str
    name: str
    start: str
    to: str | None
    rules: str


@dataclass
class Shelf:
    """The Goals shelf through one gate: today, the chapter today is in and its clash, every standing
    chapter, the goals by horizon, and the highest tier read (0 when nothing was)."""

    today: str
    chapter: Chapter | None
    clash: list[Chapter]
    chapters: list[Chapter]
    goals: list[Goal]
    tier: int
    by_line: dict[str, str] = field(default_factory=dict)  # every goal line read → its standing line

    def by_horizon(self) -> list[tuple[str, list[Goal]]]:
        """(horizon, its goals, open first, then the rest, each in the order written) for every
        horizon that has one."""
        out = []
        for horizon in goals.HORIZONS:
            found = [g for g in self.goals if g.horizon == horizon]
            if found:
                out.append(
                    (
                        horizon,
                        [g for g in found if g.state == "open"] + [g for g in found if g.state != "open"],
                    )
                )
        return out

    def goal(self, line: str) -> Goal:
        """The goal whose chain holds `line`; `GoalNotFound` when no goal line read has that id."""
        standing = self.by_line.get(line)
        found = next((g for g in self.goals if g.line == standing), None)
        if found is None:
            raise GoalNotFound(f"no goal {line}")
        return found


def _gate(tiers: Sequence[int] | None, lines: Sequence[Line]) -> list[Line]:
    return reading.crossing(lines, tiers)


def _tier(lines: Collection[Line]) -> int:
    return max((int(line.get("tier") or 0) for line in lines), default=0)


def read(lb: Logbook, tiers: Sequence[int] | None = None, today: str | None = None) -> Shelf:
    """The shelf through the gate `tiers` (None: every tier) on `today` (the record's day now, by its
    `day_start`, when None). Writes nothing."""
    days = day_start.of(lb.meta)
    on = today if today is not None else days.today(goals.now()).isoformat()
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        goal_lines = [g for g in _gate(tiers, idx.by_kind(goals.KIND)) if str(g["id"]) not in retracted]
        review_lines = goals.review_lines(_gate(tiers, idx.by_kind(goals.REVIEW)), retracted)
        chapter_lines = chapter.chapter_lines(_gate(tiers, idx.by_kind(chapter.KIND)), retracted)
        named = {i for r in review_lines for i in _named_lines(r)}
        sessions = shelf_agents.sessions_among(idx, named, tiers, retracted, days)
        session_tier = {i: int(s.get("tier") or 0) for i, s in idx.by_ids(set(sessions)).items()}
    chain = goals.Goals(goal_lines)
    zone = ZoneInfo(str(lb.meta["timezone"]))
    found: list[Goal] = []
    by_line: dict[str, str] = {}
    for line in chain.standing():
        ids = chain.chain(str(line["id"]))
        by_line.update(dict.fromkeys(ids, str(line["id"])))
        payload = line.get("payload") or {}
        mine = [r for r in review_lines if str(r["payload"]["goal"]) in ids]
        latest = goals.standing_review(mine, ids)
        shown = tuple(_review(r, days, zone) for r in reversed(mine))
        earlier = sorted((chain.by_id[i] for i in ids if i != str(line["id"])), key=lambda g: int(g["seq"]))
        served = tuple(dict.fromkeys((i, sessions[i]) for r in shown for i in r.lines if i in sessions))
        found.append(
            Goal(
                str(line["id"]),
                str(payload.get("text") or ""),
                str(payload.get("horizon") or ""),
                str(payload.get("from") or ""),
                payload.get("until") if isinstance(payload.get("until"), str) else None,
                goals.state(line, latest, on),
                None if latest is None else _review(latest, days, zone),
                shown,
                tuple((str(g["id"]), str((g.get("payload") or {}).get("text") or "")) for g in earlier),
                served,
                max([_tier([line, *earlier, *mine]), *(session_tier.get(i, 0) for i, _day in served)]),
            )
        )
    current, clash = chapter.of_day(chapter_lines, on)
    return Shelf(
        on,
        None if current is None else _chapter(current),
        [_chapter(c) for c in clash],
        [_chapter(c) for c in chapter.standing(chapter_lines)],
        found,
        max([_tier([*goal_lines, *review_lines, *chapter_lines]), *session_tier.values()]),
        by_line,
    )


def _named_lines(review: Line) -> list[str]:
    extra = (review.get("payload") or {}).get("extra")
    named = extra.get("lines") if isinstance(extra, Mapping) else None
    return [i for i in named if isinstance(i, str)] if isinstance(named, list) else []


def _review(line: Line, days: day_start.DayStart, zone: ZoneInfo) -> Review:
    payload = line.get("payload") or {}
    day = days.day_of(str(line["at"]))
    written: str | None = None
    recorded = line.get("recorded_at")
    if isinstance(recorded, str):
        local = days.day_of(recorded)
        written = local if local > day else None
    note = payload.get("note")
    return Review(
        str(line["id"]),
        day,
        str(payload.get("disposition")),
        str(payload.get("period")),
        note if isinstance(note, str) and note.strip() else None,
        written,
        tuple(_named_lines(line)),
        int(line.get("tier") or 0),
    )


def _chapter(line: Line) -> Chapter:
    payload = line.get("payload") or {}
    first, last = chapter.span(line)
    rules = payload.get("rules")
    return Chapter(
        str(line["id"]), str(payload.get("name") or ""), first, last, rules if isinstance(rules, str) else ""
    )


# -- the pages ---------------------------------------------------------------------------------------------


def goal_path(line: str) -> str:
    return f"/goals/{line}"


def page_goals(site: Site) -> str:
    """`/goals`: the chapter today is in, then the goals by horizon, each a link to its page with its
    state and its standing review's disposition and day; the empty shelf says how to add the first."""
    shelf = read(site.lb, site.tiers, _today(site))
    head = f"{_plural(len(shelf.goals), 'goal')}{DOT}{shelf.today}"
    parts = [f"<h1>Goals {site.tier_small(head, shelf.tier)}</h1>\n"]
    if site.tiers is not None and goals.TIER not in site.tiers:
        parts.append(
            f'<p class="mute">Goals, reviews and chapters are your own words, tier {goals.TIER}; this page'
            f" reads tier {', '.join(str(t) for t in sorted(site.tiers)) or 'none'} only.</p>\n"
        )
        return site.document("goals", "".join(parts), style=SHELF_STYLE)
    parts.append(_chapter_html(shelf))
    if not shelf.goals:
        parts.append(
            "<p>No goals yet. Write them in a file, one a line, the horizon after a bar (life, year or"
            f" quarter), and add them with <code>{escape(ADD_FIRST)}</code>:</p>\n"
            f'<pre class="file">{escape(FILE_SHAPE)}</pre>\n'
            '<p class="mute">Then review one with <code>logbook goal review GOAL advancing</code>.</p>\n'
        )
        return site.document("goals", "".join(parts), style=SHELF_STYLE)
    parts.append(
        '<p class="mute">Your goals in your words, by horizon, the open ones first; each with the latest'
        " verdict you gave it and the day it was for.</p>\n"
    )
    for horizon, found in shelf.by_horizon():
        parts.append(f'<h2>{escape(HORIZON_NAMES.get(horizon, horizon))}</h2>\n<ol class="shelf">\n')
        parts.extend(_goal_row(site, g) for g in found)
        parts.append("</ol>\n")
    return site.document("goals", "".join(parts), style=SHELF_STYLE)


def _goal_row(site: Site, g: Goal) -> str:
    head = [site.link(f"<b>{escape(g.text)}</b>", goal_path(g.line)), _badge(g.state)]
    if g.review is not None:
        day = site.link(escape(g.review.day), f"/day/{g.review.day}")
        head.append(f'<span class="mute">{escape(g.review.disposition)}{DOT}{day}</span>')
    else:
        head.append('<span class="mute">not reviewed yet</span>')
    facts = [_bounds(g), _plural(len(g.reviews), "review")]
    if g.served:
        facts.append(_plural(len(g.served), "session") + " served it")
    return (
        f'<li id="{escape(g.line)}"><p class="head">{" ".join(head)}</p>\n'
        f'<p class="facts">{escape(DOT.join(facts))}</p></li>\n'
    )


def page_goal(site: Site, line: str) -> str:
    """`/goals/ID`: one goal, by the id of any line of its chain: its wording, horizon, bounds and
    state, its earlier wordings, every review the newest first, and the sessions a review names."""
    shelf = read(site.lb, site.tiers, _today(site))
    try:
        g = shelf.goal(line)
    except GoalNotFound as e:
        from .serve import NotFound  # serve is loaded by now: it is what called this page

        raise NotFound(f"no page at {goal_path(line)}: {e}, or none this page reads") from None
    parts = [f"<h1>{escape(g.text)} <small>goal{DOT}tier {g.tier}</small></h1>\n"]
    parts.append(
        f'<p class="head">{_badge(g.state)} <span class="mute">'
        f"{escape(HORIZON_NAMES.get(g.horizon, g.horizon))}{DOT}{escape(_bounds(g))}</span></p>\n"
    )
    if g.earlier:
        parts.append('<h2>Earlier wordings</h2>\n<ol class="shelf">\n')
        parts.extend(f'<li title="line {escape(i)}">{escape(text)}</li>\n' for i, text in g.earlier)
        parts.append("</ol>\n")
    parts.append(f"<h2>Reviews <small>{_plural(len(g.reviews), 'review')}</small></h2>\n")
    if not g.reviews:
        parts.append(
            '<p class="mute">not reviewed yet: <code>logbook goal review'
            f" {escape(g.line)} advancing</code> (or stalled, done, let-go, superseded)</p>\n"
        )
    else:
        parts.append('<ol class="shelf">\n')
        for r in g.reviews:
            day = site.link(escape(r.day), f"/day/{r.day}")
            facts = f"{escape(r.period)}{DOT}{day}"
            if r.written is not None:
                facts += f"{DOT}written {escape(r.written)}"
            parts.append(
                f'<li title="line {escape(r.line)}"><p class="head">{_badge(r.disposition)}'
                f' <span class="mute">{facts}</span></p>\n'
            )
            if r.note:
                parts.append(f'<p class="note">{escape(r.note)}</p>\n')
            parts.append("</li>\n")
        parts.append("</ol>\n")
    parts.append("<h2>Sessions that served it</h2>\n")
    if g.served:
        parts.append('<ul class="plain">\n')
        parts.extend(
            f"<li>{site.link(f'a session with an agent, {escape(day)}', shelf_agents.session_path(i, day))}"
            f' <span class="mute" title="line {escape(i)}">{escape(i[:8])}…</span></li>\n'
            for i, day in g.served
        )
        parts.append("</ul>\n")
    else:
        parts.append(
            '<p class="mute">none a review names: a session served a goal when a review of it says so'
            " (its <code>extra.lines</code>), never by a guess</p>\n"
        )
    parts.append(f"<p>{site.link('Goals', '/goals')}</p>\n")
    return site.document(g.text, "".join(parts), style=SHELF_STYLE)


def _chapter_html(shelf: Shelf) -> str:
    c = shelf.chapter
    if c is None:
        text = '<p class="mute">No chapter holds today'
        if not shelf.chapters:
            text += ': name one with <code>logbook chapter open "NAME" --from YYYY-MM-DD</code>'
        return text + ".</p>\n"
    out = [f"<h2>{escape(c.name)} <small>the chapter{DOT}{escape(_span(c))}</small></h2>\n"]
    if c.rules:
        out.append(f'<p class="note">{escape(c.rules)}</p>\n')
    if shelf.clash:
        names = ", ".join(x.name for x in shelf.clash)
        out.append(f'<p class="mute">clashes with {escape(names)}</p>\n')
    others = [x for x in shelf.chapters if x.line != c.line]
    if others:
        listed = "; ".join(f"{x.name} {_span(x)}" for x in others)
        out.append(f'<p class="facts">other chapters: {escape(listed)}</p>\n')
    return "".join(out)


def _span(c: Chapter) -> str:
    return chapter.span_text({"from": c.start, "to": c.to})


def _bounds(g: Goal) -> str:
    return f"from {g.start}" + (f", until {g.until}" if g.until else "")


def _badge(word: str) -> str:
    return f'<span class="badge {escape(word.replace(" ", "-"))}">{escape(word)}</span>'


def _today(site: Site) -> str:
    return day_start.of(site.lb.meta).today(site.now()).isoformat()


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun if n == 1 else noun + 's'}"


def to_json(shelf: Shelf) -> dict[str, Any]:
    """The shelf as data, for the tests and a reader that wants it."""
    return {
        "today": shelf.today,
        "tier": shelf.tier,
        "chapter": None if shelf.chapter is None else shelf.chapter.name,
        "goals": [
            {
                "line": g.line,
                "text": g.text,
                "horizon": g.horizon,
                "state": g.state,
                "review": None
                if g.review is None
                else {"disposition": g.review.disposition, "day": g.review.day},
                "served": [i for i, _day in g.served],
            }
            for g in shelf.goals
        ],
    }
