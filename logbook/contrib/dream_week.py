"""The dream of a week (`logbook dream week [DAY|YYYY-Www]`, and `dream --catch-up` the morning its
Sunday closes): a model reads one ISO week, Monday to Sunday, its seven days' drafts and its lines
together, and writes one `draft/v1` line about it (RFC 0036, unit `week`): where the time went, by
place, person and thread; the energy, sleep and training when the record has them; the people who
moved and the promises open both ways; for each open goal a review it proposes; one proposal for next
week, never more; and a personal part, the only place for anything personal. Every sentence points at
the lines it came from. A proposal, as every draft: the owner reviews a goal (`goal review`); the week
only proposes the verdict. The prompt says it plainly: never moralise.

It runs on the dream's engine (`logbook.contrib.dream`) under the same `dream` entry of
`policy/crossing.json` and the same endpoint, and it is held to the same rules: the week is read
through the entry's ceiling (a gated reading, `reading.read(..., tiers)`), so no line above it is
read, named or counted; every sentence cites lines of the week or is marked unsupported, and more than
30 % unsupported refuses the answer; the draft's tier is the highest tier among the lines it read, and
it records the version of the entry it was dreamed under.

**The numbers are the code's** (`numbers`): the hours at each place (`dream.days_of`, from the stays'
first and last lines, as the Day reads them), the contacts with each canonical person (messages in a
direct chat, the calendar entries they attend, the calls, the recordings they speak in: the people
reader's channels, `people.read`, kept to the lines the ceiling lets through) and the days together
at a stay the with module confirms them at, the threads (each chat, mail subject, calendar title and
recording title with its count), and the energy: the nights that ended on its days as the Day counts
them (Monday's began the Sunday before, whose evening's sleep lines it reads for it), their asleep
hours, and the workouts (`health.nights`, `health.training`), else `no data` (always so under a
ceiling under 3: health is tier 3). Each figure carries the ids of the lines it came from, in
the draft's `extra.numbers` and, as references, in the material; a sentence that writes a figure the
items it cites do not give is marked unsupported (`dream.hold_numbers`). The counts by person are the
model's to read, never a reader's: `extra.numbers.people` keeps each person's name, id and lines only,
in the material's order (the most contacts first), a chat among the threads its counterpart and lines
without its count (`drafts.names_only`), and, as for a day, a month and a chapter, no
number stands beside a person, pencil included: a sentence that names a canonical person and writes a
figure is held (`dream.hold_names`, counted under `extra.marked` as `a number beside a person`).

**What else it reads.** The seven days' standing drafts the entry allows, read through the one rule
(`drafts.through`): a draft above the entry is not read, and the week is refused while a day that has
lines under the ceiling has no such draft (`dream day` it first; `--catch-up` dreams the days before
the week). Only a draft's supported sentences are given, as a model's (`drafted`), with the references
of the lines they rest on. The people who moved: each canonical person's contacts this week against
the week before (`drifting.windows`, seven days each), the largest changes either way, and the
promises open with them both ways (`people_drift.promises_with`). The promises open both ways made on
or before the Sunday (`promises.extract`), and the owner's goals open on the Sunday (`goals.Goals`,
their standing review). Every line of these is under the ceiling and counts toward the draft's tier
and its digest (`extra.read_ids_sha256`), and how many they are under `extra.read_beside`; `read_count`
is the week's own lines (RFC 0036 rule 5), the only ones cited.

**A week only from its seven days.** A week is dreamed once its Sunday is over: `dream week` refuses a
week whose Sunday is today or later (`NotOver`), and with no week named dreams the last one whose
Sunday is over. `--catch-up` dreams each week whose seven days are all among the days it looks at
(`weeks_to_catch_up`), after the days, whose drafts it reads: the first 06:00 close after a Sunday
(Monday's, which closes the Sunday) dreams the week that Sunday ended, and the runs after it leave it
alone while it is unchanged, until its Monday leaves the window. The re-dream rule is the day's
(`dream.why_again`).

**The line.** `unit` `week`; `subject` the ISO week, `2026-W25`; `extra.parts` the part of each
segment (`drafts.WEEK_PARTS`); `extra.numbers` the numbers with their line ids; `extra.goals` the
review proposed for each goal (`{goal, text, disposition, segment}`, the goal's line id and the
segment that says why); `extra.dropped` (a second proposal for next week, a goal item that names no
goal of the material, no disposition, a goal twice, or no line of the week) and `extra.marked`.
`day DAY` of a Sunday carries the week's standing draft (`on_sunday`).

**One stale question** (RFC 0037 §10.6, `stale_question`). The code, not the model, asks at most one
question a week about the stalest holding or idea: an org or an idea whose status has aged past the
reader's limit as of the Sunday (`entities.stale`: a `hold` over three years and an `exploring` over
two by default, any status `policy/entities.json` `stale_days` names), its last touch counted as the
Manifest and the Ideas shelf count it. "Havn Data AS: still hold? Nothing since June 2023." It is kept
under `extra.question` (`{entity, label, status, status_line, since, text, read}`), a proposal beside
the goals' reviews and never a segment, a line of its own or a status: the owner's answer, if any, is
`logbook status`, which restarts the clock. It is asked once: an entity whose standing status a draft
of another week asked about already is passed over for the next stalest. It never names an entity
above the draft: only an entity whose status line, entity lines and touches are under the ceiling and
at or below the tier the week's own reading gave the draft is a candidate (an org's status is tier 3,
so a holding is asked only of a tier-3 week). The lines it read are named in the question (`read`)
and kept out of the digest, so a status written or an entity named since never sends the week to the
model again by itself; and a `policy/entities.json` that does not read asks nothing and refuses
nothing. Nothing of it is sent to the model."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from string import Template
from typing import Any

from ..core import (
    day_start,
    drafts,
    drifting,
    goals,
    health,
    people,
    policy,
    reading,
    resolve,
    signing,
    stays,
)
from ..core.chain import Line
from ..core.day import WEEKDAYS
from ..core.export import day_range, parse_day
from ..core.flights import Airports
from ..core.index import Index
from ..core.store import HeadMoved, Logbook, retractions
from . import dream, entities, ideas, people_drift
from . import orgs as org_reader
from . import promises as promise_reader
from .dream import DreamError, Material, Outcome
from .model_client import Transport
from .week_paper import parse_week, week_of

PROMPT_FILE = Path(__file__).with_name("dream-week-prompt.md")
PROMPT_NAME = "dream-week/2"  # kept under `extra.prompt`, so a draft says which prompt wrote it
WEEK_DAYS = 7
REFS = 12  # the references an item carries, at most; its count is always whole
SHOWN = 8  # the places, people and threads given, at most, the largest first
MOVERS = 5  # the people who moved most against the week before, at most
PROMISES = 10  # the promises given each way, at most, the latest first
NEXT_WEEK = 1  # the proposals for next week a draft keeps: one
SUNDAY = 6  # `date.weekday()` of a Sunday
NO_DATA = "no data"
CONTACT_CHANNELS = ("messages", "calendar", "calls", "transcripts")  # the people reader's, a contact each
MORE_THAN_ONE = "more than one proposal for next week"
NOT_A_GOAL = "not a goal of the week"
NOT_A_DISPOSITION = "not a disposition"
GOAL_TWICE = "a goal reviewed twice"
NOT_OF_THE_WEEK = "evidence not of the week"
SUBJECT = re.compile(r"\d{4}-W\d{2}\Z")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")  # fmt: skip


class NotOver(DreamError):
    """The week's Sunday is today or later: a week is dreamed from its seven days, once they are."""


class DayUndreamed(DreamError):
    """A day of the week has lines under the ceiling and no draft the entry allows: the week reads
    its seven days' drafts, so the day is dreamed first."""


@dataclass
class Read:
    """What the dream read of a week: the material, the goals by their reference, and the ids of the
    lines it read beside the week's own."""

    made: Material
    week: str
    monday: str
    sunday: str
    goals: dict[str, Line] = field(default_factory=dict)  # `G1` -> the standing goal line
    beside: int = 0  # the lines it read beside the week's own: `extra.read_beside`
    numbers: dict[str, Any] = field(default_factory=dict)  # `extra.numbers`: the figures with line ids
    question: dict[str, Any] | None = None  # `extra.question`: the one stale question, or None


# -- the week ---------------------------------------------------------------------------------------------


def last_over(today: date) -> date:
    """The latest Sunday before `today`: the last week that has ended."""
    return today - timedelta(days=today.isoweekday() % WEEK_DAYS or WEEK_DAYS)


def which(text: str | None, today: date) -> tuple[str, str, str]:
    """The week `text` names, as (`YYYY-Www`, its Monday, its Sunday): an ISO week, any day of one
    (`yesterday` too), or, with no text, the last week whose Sunday is over. `ValueError` for text
    that is neither; `NotOver` for a week whose Sunday is today or later."""
    if text is None:
        week = week_of(last_over(today).isoformat())
    elif SUBJECT.match(text):
        week = text
    else:
        try:
            day = (
                (today - timedelta(days=1)).isoformat()
                if text == "yesterday"
                else parse_day(text).isoformat()
            )
        except ValueError as e:
            raise ValueError(f"not a day or a week (YYYY-MM-DD or YYYY-Www): {text!r}") from e
        week = week_of(day)
    week, monday, sunday = parse_week(week)
    if sunday >= today.isoformat():
        raise NotOver(
            f"{week} runs to Sunday {sunday}, which is not over; a week is dreamed from its seven days,"
            " once they are"
        )
    return week, monday, sunday


def standing_of(lb: Logbook, week: str) -> Line | None:
    """The week's standing draft, whatever the entry allows (rule 2): the one a new draft supersedes."""
    with lb.index() as idx:
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retractions(idx.retractions()), drafts.UNIT_WEEK)
    return drafts.standing(found.get(week, []))


# -- the material -----------------------------------------------------------------------------------------


def material(
    lb: Logbook, week: str, monday: str, sunday: str, found: policy.Ceiling, airports: Airports | None = None
) -> Read:
    """The week's material under the entry's ceiling (the module's docstring). `DayUndreamed` when a
    day with lines under the ceiling has no draft the entry allows."""
    tiers = dream.tiers_of(found)
    airports = airports or Airports.load()
    rd = reading.read(lb, monday, sunday, airports, tiers)
    on = dream.lines_of_days(rd, monday, sunday)
    ids = {str(line["id"]) for line in on}
    days = day_range(monday, sunday)
    before, _this = drifting.windows(sunday, WEEK_DAYS)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        names = resolve.labels(lb, idx)
        identities = resolve.identities_from([*idx.retractions(), *idx.resolutions()])
        allowed = drafts.allowed(lb.root)
        every_draft = idx.by_kind(drafts.KIND)
        day_drafts = {
            day: drafts.standing(
                drafts.through(drafts.of_day(every_draft, retracted, day), tiers, allowed)[0]
            )
            for day in days
        }
        goal_lines = [
            g for g in reading.crossing(idx.by_kind(goals.KIND), tiers) if str(g["id"]) not in retracted
        ]
        review_lines = goals.review_lines(reading.crossing(idx.by_kind(goals.REVIEW), tiers), retracted)
        earlier = _gated(idx, before[0], before[1], tiers, retracted)
        eve = (date.fromisoformat(monday) - timedelta(days=1)).isoformat()  # Monday's night begins on it
        night_before = [
            line
            for line in reading.crossing(idx.by_kind(health.KIND, eve, eve), tiers)
            if str(line["id"]) not in retracted
        ]
    lined = Counter(rd.day_of(line) for line in on)
    missing = [day for day in days if lined[day] and day_drafts[day] is None]
    if missing:
        raise DayUndreamed(
            f"{week} reads its seven days' drafts and {', '.join(missing)} has none the"
            f" {policy.DREAM_DESTINATION!r} entry allows; `dream day {missing[0]}` first,"
            " or `dream --catch-up`"
        )
    made = Material(
        day=week,
        unit=drafts.UNIT_WEEK,
        tier=1,
        read_count=0,
        read_head=str(lb.meta["head"]),
        read_ids_sha256="",
        language=dream.language_of(dream._texts(on)),
        data={},
        ids=ids,
        zone=rd.tz,
        canonical=dream.canonical(lb, identities),
        identities=identities,
    )
    read = Read(made, week, monday, sunday)
    beside: dict[str, int] = {}  # what it read beside the week's lines: id -> tier

    _by_day, places = dream.days_of(rd, days, made)
    report = people.read(lb, monday, sunday, airports)
    report_before = people.read(lb, *before, airports)
    persons = _persons(report, ids, made)
    movers, counted_before = _movers(report, report_before, ids, earlier, made)
    beside.update(counted_before)
    promises, promise_lines, open_then = _promises(lb, sunday, ids, tiers, made)
    beside.update(promise_lines)
    owed = _owed(lb, report, [m["id"] for m in movers], open_then)
    for mover in movers:
        mover.update(owed.get(mover["id"], {"you_owe": 0, "they_owe": 0}))
    by_sunday = [g for g in goal_lines if rd.day_start.day_of(str(g["at"])) <= sunday]  # as it stood
    until_sunday = [r for r in review_lines if rd.day_start.day_of(str(r["at"])) <= sunday]
    open_goals, goal_read = _goals(by_sunday, until_sunday, sunday, read)
    beside.update({str(line["id"]): int(line.get("tier") or 2) for line in goal_read})
    shown_days = []
    for day in days:
        line = day_drafts[day]
        if line is not None:
            beside[str(line["id"])] = int(line.get("tier") or 1)
        shown_days.append(_day(day, line, ids, made))
    energy, slept_before = _energy(on, night_before, rd, monday, sunday, made)
    beside.update(slept_before)
    threads = _threads(on, names, made, (rd.day_start.span(monday)[0], rd.day_start.span(sunday)[1]))
    read.numbers = {
        "places": [_lined(p, made) for p in places[:SHOWN]],
        "people": [_named(p, made) for p in persons[:SHOWN]],  # names and lines, no count
        "threads": drafts.names_only({"threads": [_lined(t, made) for t in threads[:SHOWN]]})["threads"],
        "energy": None if energy is None else {k: _lined(v, made) if v else None for k, v in energy.items()},
    }
    made.data = {
        "week": week,
        "monday": monday,
        "sunday": sunday,
        "max_tier": found.max_tier,
        "time": {"places": places[:SHOWN], "people": persons[:SHOWN], "threads": threads[:SHOWN]},
        "energy": NO_DATA if energy is None else energy,
        "people": {"movers": movers, "promises": promises},
        "goals": open_goals,
        "days": shown_days,
    }
    made.tier = max([int(line.get("tier", 1)) for line in on] + list(beside.values()), default=1)
    # at or below the tier the draft has already, so it never raises it; its lines are kept in the
    # question (`read`), out of the digest, so a question alone never sends the week to the model again
    read.question, _asked = stale_question(lb, week, sunday, tiers, made.tier)
    read_ids = ids | set(beside)
    made.read_count = len(ids)  # the lines of the unit (RFC 0036 rule 5); the digest covers all it read
    made.read_ids_sha256 = dream.digest(read_ids)
    read.beside = len(set(beside) - ids)
    return read


# -- the stale question -----------------------------------------------------------------------------------


def stale_question(
    lb: Logbook, week: str, sunday: str, tiers: Sequence[int], tier: int
) -> tuple[dict[str, Any] | None, dict[str, int]]:
    """The one question the week asks (the module's docstring), and the lines it read for it (id ->
    tier): the stalest holding or idea as of `sunday`, stale as the Manifest and the Ideas shelf say
    (`entities.stale` with the last touch, any status `stale_days` names), whose lines are all under
    the gate `tiers` and at or below `tier`, not asked by a draft of another week since its standing
    status; (None, {}) when nothing is stale, or when `policy/entities.json` cannot be read (the week
    is drafted without a question, never refused for it)."""
    gate = sorted({int(t) for t in tiers})
    rows: list[tuple[str, entities.Entity, entities.Status | None, bool, str | None, int]] = []
    try:
        for i in ideas.shelf_of(ideas.read(lb, gate, today=sunday)).rows:
            rows.append((entities.IDEA, i.idea, i.status, i.stale, i.stale_since, i.tier))
        if entities.status_tier(entities.ORG) <= tier:  # an org's status is tier 3
            record = org_reader.read(lb, org_reader.gate(gate), today=sunday)
            for o in org_reader.shelf_of(lb, record).rows:
                rows.append((entities.ORG, o.org, o.status, o.stale, o.stale_since, o.tier))
    except entities.EntityError:
        return None, {}
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        weeks = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_WEEK)
    asked = set()
    for subject, found in weeks.items():
        standing = drafts.standing(found)
        extra = (standing.get("payload") or {}).get("extra") if standing is not None else None
        question = extra.get("question") if isinstance(extra, dict) else None
        if subject != week and isinstance(question, dict) and isinstance(question.get("status_line"), str):
            asked.add(question["status_line"])
    candidates: list[tuple[str, str, entities.Status, str, dict[str, int]]] = []  # since, label, …
    for kind, entity, status, stale, since, row_tier in rows:
        if not stale or status is None or since is None or status.line in asked:
            continue
        read_ids = {line_id: entities.TIER for line_id in entity.lines}
        read_ids[status.line] = entities.status_tier(kind)
        if max([row_tier, *read_ids.values()]) > tier:
            continue
        candidates.append((since, entity.label, status, kind, read_ids))
    if not candidates:
        return None, {}
    since, label, status, kind, read_ids = min(candidates, key=lambda c: (c[0], c[1].casefold(), c[2].line))
    when = date.fromisoformat(since)
    return {
        "entity": {"type": kind, "id": status.entity},
        "label": label,
        "status": status.status,
        "status_line": status.line,
        "since": since,
        "text": f"{label}: still {status.status}? Nothing since {MONTHS[when.month - 1]} {when.year}.",
        "read": sorted(read_ids),
    }, read_ids


def _gated(
    idx: Index, first: str, last: str, tiers: Sequence[int], retracted: frozenset[str]
) -> dict[str, int]:
    """id -> tier of the lines of the local days `first` to `last` under the ceiling, not retracted."""
    return {
        str(line["id"]): int(line.get("tier") or 1)
        for line in reading.crossing((line for _day, line in idx.between(first, last)), tiers)
        if str(line["id"]) not in retracted
    }


def _lined(item: Mapping[str, Any], made: Material) -> dict[str, Any]:
    """An item of the material as `extra.numbers` keeps it: its references as line ids (`lines`)."""
    out = {k: v for k, v in item.items() if k != "ref"}
    out["lines"] = [made.refs[r] for r in item.get("ref") or [] if r in made.refs]
    return out


def _named(person: Mapping[str, Any], made: Material) -> dict[str, Any]:
    """A person of `time.people` as `extra.numbers` keeps them: the name, the id and the lines, never
    a count (RFC 0043: no number beside a person); the order of the list says who came first."""
    lined = _lined(person, made)
    return {k: lined[k] for k in drafts.PERSON_KEYS}


def _persons(report: people.Report, ids: set[str], made: Material) -> list[dict[str, Any]]:
    """The week's contacts by canonical person, each channel counted from the lines under the ceiling
    (`CONTACT_CHANNELS`), and the days together: the days the with module confirms them at one of the
    owner's stays (`people.read`'s `shared`, one per day), counted when some of their evidence is under
    the ceiling. A day together is a day, never hours: the with module puts someone at a stay, not
    beside the owner for all of it."""
    out = []
    for p in report.known.values():
        if made.person(p.entity) is None:
            continue
        counts: dict[str, Any] = {"name": p.name, "id": p.entity}
        refs: list[str] = []
        for channel in CONTACT_CHANNELS:
            found = p.channels.get(channel)
            kept = [i for i in dict.fromkeys(found.ids if found is not None else []) if i in ids]
            counts[channel] = len(kept)
            refs += made.refs_of(kept)
        counts["contacts"] = sum(counts[c] for c in CONTACT_CHANNELS)
        together: dict[str, list[str]] = {}
        for shared in p.shared.values():
            kept = [i for i in shared.lines if i in ids]
            if kept:
                together.setdefault(shared.day, []).extend(kept)
        if together:
            counts["days_together"] = len(together)
            refs += made.refs_of(i for day in sorted(together) for i in together[day])
        if counts["contacts"] or together:
            counts["ref"] = list(dict.fromkeys(refs))[:REFS]
            out.append(counts)
    return sorted(out, key=lambda p: (-p["contacts"], -p.get("days_together", 0), p["name"]))


def _contacts(p: people.Person | None, allowed: Mapping[str, int] | set[str]) -> list[str]:
    """The ids of a person's contacts in one window under the ceiling: the lines of the channels
    `time.people` counts as `contacts` (`CONTACT_CHANNELS`), so a mover's count is the same number."""
    if p is None:
        return []
    found: list[str] = []
    for channel in CONTACT_CHANNELS:
        ch = p.channels.get(channel)
        found += [i for i in (ch.ids if ch is not None else []) if i in allowed]
    return list(dict.fromkeys(found))


def _movers(
    report: people.Report, before: people.Report, ids: set[str], earlier: Mapping[str, int], made: Material
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """The canonical people whose contacts moved most between the week before and this one, either
    way (`MOVERS` at most, the largest change first), each with both counts and this week's lines;
    and the ids of the week before's lines counted, with their tiers, which it read too."""
    moved: list[tuple[str, list[str], list[str]]] = []
    for entity in sorted(set(report.known) | set(before.known)):
        if made.person(entity) is None:
            continue
        now = _contacts(report.known.get(entity), ids)
        was = _contacts(before.known.get(entity), earlier)
        if len(now) != len(was):
            moved.append((entity, now, was))
    moved.sort(key=lambda m: (-abs(len(m[1]) - len(m[2])), -len(m[1]), made.canonical[m[0]]))
    rows: list[dict[str, Any]] = []
    counted: dict[str, int] = {}
    for entity, now, was in moved[:MOVERS]:  # only what is given is read: the rest is never counted
        counted.update({i: earlier[i] for i in was})
        rows.append(
            {
                "id": entity,
                "name": made.canonical[entity],
                "this_week": len(now),
                "week_before": len(was),
                "ref": made.refs_of(now)[:REFS],
            }
        )
    return rows, counted


def _promises(
    lb: Logbook, sunday: str, ids: set[str], tiers: Sequence[int], made: Material
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int], list[promise_reader.Proposal]]:
    """The promises open both ways on the week's Sunday (`promises.extract` to that day, shown, and open
    as the Sunday stood: one closed later, by a task or a signed day written after it, was open then,
    so what a later week does never changes this one): what the owner owes (their own and what was
    asked of them) and what is owed to them, the latest first, `PROMISES` each way at most, each read
    from a line under the ceiling; and those lines' ids with their tiers. A promise made in the week
    carries its line's reference. And every promise open then under the ceiling, for the movers'
    counts (`_owed`)."""
    report = promise_reader.extract(lb, until=sunday)
    days = day_start.of(lb.meta)
    with lb.index() as idx:

        def open_then(p: promise_reader.Proposal) -> bool:
            closers = [p.closed_by] if p.closed_by else []
            if p.disposition is not None and p.disposition.value in signing.CLOSING:
                closers.append(p.disposition.line)
            found = [line for line in (idx.by_id(c) for c in closers) if line]
            return not any(days.day_of(str(line["at"])) <= sunday for line in found)

        wanted = [p for p in report.proposals if p.shows and p.role is not None and open_then(p)]
        found = [line for line in (idx.by_id(i) for i in dict.fromkeys(p.line for p in wanted)) if line]
    tier_of = {str(line["id"]): int(line.get("tier") or 1) for line in reading.crossing(found, tiers)}
    out: dict[str, list[dict[str, Any]]] = {"you_owe": [], "they_owe": []}
    lines: dict[str, int] = {}
    for p in sorted(wanted, key=lambda p: (p.day, p.seq), reverse=True):
        if p.line not in tier_of:
            continue  # a promise read from a line above the ceiling is not the model's to see
        side = "you_owe" if p.role in (promise_reader.PROMISE, promise_reader.ASKED) else "they_owe"
        if len(out[side]) >= PROMISES:
            continue
        lines[p.line] = tier_of[p.line]
        item: dict[str, Any] = {
            "day": p.day,
            "counterpart": p.counterpart,
            "quote": p.match.quote,
            "due": p.due,
        }
        if p.line in ids:
            item["ref"] = made.refs_of([p.line])
        out[side].append(item)
    return out, lines, [p for p in wanted if p.line in tier_of]


def _owed(
    lb: Logbook, report: people.Report, entities: Sequence[str], open_then: Sequence[promise_reader.Proposal]
) -> dict[str, dict[str, int]]:
    """How many promises were open with each mover each way on the Sunday (`people_drift.promises_with`
    over `open_then`, the promises `_promises` found open then, under the ceiling): the same promises
    the week gives, never the ones open today."""
    persons = [report.known[e] for e in entities if e in report.known]
    if not persons:
        return {}
    out: dict[str, dict[str, int]] = {}
    for entity, found in people_drift.promises_with(lb, persons, proposals=open_then).items():
        mine = sum(1 for _p, owed in found if owed)
        out[entity] = {"you_owe": mine, "they_owe": len(found) - mine}
    return out


def _goals(
    goal_lines: Sequence[Line], review_lines: Sequence[Line], sunday: str, read: Read
) -> tuple[list[dict[str, Any]], list[Line]]:
    """The owner's goals open on the Sunday, under the ceiling, as the goal and review lines up to
    that Sunday left them (none dated after it is given), each with a reference of its own (`G1`, ...) and its
    standing review's disposition; never a line of the week, never cited. And the lines given: each
    goal's and its standing review's, which it read, and no other."""
    found = goals.Goals(goal_lines)
    out = []
    given: list[Line] = []
    for line in found.standing():
        payload = line.get("payload") or {}
        if str(payload.get("from") or "") > sunday:
            continue
        review = goals.standing_review(review_lines, found.chain(str(line["id"])))
        if goals.state(line, review, sunday) != "open":
            continue
        given += [line] if review is None else [line, review]
        ref = f"G{len(read.goals) + 1}"
        read.goals[ref] = line
        out.append(
            {
                "goal": ref,
                "text": str(payload.get("text") or ""),
                "horizon": payload.get("horizon"),
                "last_review": None if review is None else (review.get("payload") or {}).get("disposition"),
            }
        )
    return out, given


def _day(day: str, line: Line | None, ids: set[str], made: Material) -> dict[str, Any]:
    """One day as its standing draft told it: its supported sentences, a model's words (`drafted`),
    each with the references of the week's lines it rests on; `no draft` for a day with no line."""
    weekday = WEEKDAYS[date.fromisoformat(day).weekday()]  # the Day's words, never the machine's locale
    if line is None:
        return {"day": day, "weekday": weekday, "draft": None}
    payload = line.get("payload") or {}
    told = []
    parts = (payload.get("extra") or {}).get("parts") if isinstance(payload.get("extra"), dict) else None
    segments = payload.get("segments") or []
    for i, segment in enumerate(segments):
        shown = drafts.segment_json(segment, ids, drafts.NOT_ON_WEEK)
        ref = made.refs_of(shown["evidence"]) if shown["supported"] else []
        if ref:
            part = parts[i] if isinstance(parts, list) and len(parts) == len(segments) else None
            told.append({"part": part, "drafted": shown["text"], "ref": ref})
    return {"day": day, "weekday": weekday, "draft": told}


def _energy(
    on: Sequence[Line],
    night_before: Sequence[Line],
    rd: reading.Reading,
    monday: str,
    sunday: str,
    made: Material,
) -> tuple[dict[str, dict[str, Any] | None] | None, dict[str, int]]:
    """Sleep and training from the health lines under the ceiling, as the Day counts them: the nights
    that ended on the week's days (`health.nights`; Monday's began the Sunday before, so that
    evening's lines, `night_before`, are read for it, and Sunday's own night is the next week's
    Monday's), their count and mean asleep hours; the workouts begun on its days (`health.training`),
    their count and minutes. None when there is neither: `no data`. And the lines of the evening
    before that a night counted, with their tiers, which it read too; they are never cited."""
    lines = [line for line in [*night_before, *on] if line.get("kind") == health.KIND]
    clock = rd.day_start.text
    nights = {d: n for d, n in health.nights(lines, str(rd.tz), clock).items() if monday <= d <= sunday}
    trained = {d: t for d, t in health.training(on, str(rd.tz), clock).items() if monday <= d <= sunday}
    used = {i for n in nights.values() for i in n["lines"]}
    before = {str(line["id"]): int(line.get("tier") or 3) for line in night_before if str(line["id"]) in used}
    sleep = None
    if nights:
        asleep = [n["asleep_s"] for n in nights.values()]
        sleep = {
            "nights": len(nights),
            "hours": round(sum(asleep) / len(asleep) / 3600, 1),
            "ref": made.refs_of(i for n in nights.values() for i in n["lines"])[:REFS],
        }
    training = None
    if trained:
        training = {
            "sessions": sum(len(t["lines"]) for t in trained.values()),
            "minutes": sum(int(t["minutes"]) for t in trained.values()),
            "ref": made.refs_of(i for t in trained.values() for i in t["lines"])[:REFS],
        }
    if sleep is None and training is None:
        return None, before
    return {"sleep": sleep, "training": training}, before


def _threads(
    on: Sequence[Line],
    names: Mapping[resolve.Ref, str],
    made: Material,
    span: tuple[datetime, datetime],
) -> list[dict[str, Any]]:
    """The week's threads, the largest first: each chat by its counterpart (`dream._messages`, an
    agent's marked), each mail subject, each calendar title with its hours, each recording's title
    with its minutes, the time of each clipped to the week (`span`); every count from the lines under
    the ceiling."""
    out: list[dict[str, Any]] = []
    for chat in dream._messages(on, names, made):
        item: dict[str, Any] = {
            "thread": chat["counterpart"],
            "kind": drafts.CHAT,
            "count": chat["count"],
            "ref": chat["ref"][:REFS],
        }
        if chat.get("agent"):
            item["agent"] = True
        out.append(item)
    grouped: dict[tuple[str, str], list[Line]] = {}
    for line in on:
        payload = line.get("payload") or {}
        kind = str(line.get("kind"))
        if kind == "mail":
            title = re.sub(r"^((re|fwd?|sv|vs)\s*:\s*)+", "", str(payload.get("subject") or ""), flags=re.I)
        elif kind in ("event", "transcript"):
            title = str(payload.get("title") or "")
        else:
            continue
        if title.strip():
            grouped.setdefault((kind, " ".join(title.split())), []).append(line)
    labels = {"mail": "mail", "event": "calendar", "transcript": "call"}
    for (kind, title), lines in grouped.items():
        item = {"thread": title, "kind": labels[kind], "count": len(lines)}
        if kind in ("event", "transcript"):
            minutes = sum(_minutes(line, span) for line in lines)
            if minutes:
                item["minutes" if kind == "transcript" else "hours"] = (
                    minutes if kind == "transcript" else round(minutes / 60, 1)
                )
        item["ref"] = made.refs_of(str(line["id"]) for line in lines)[:REFS]
        out.append(item)
    return sorted(out, key=lambda t: (-t["count"], t["thread"]))


def _minutes(line: Line, span: tuple[datetime, datetime]) -> int:
    """The minutes of a line's span that fell inside `span`."""
    begun, ended = stays.instant(line.get("at")), stays.instant(line.get("end"))
    if begun is None or ended is None:
        return 0
    begun, ended = max(begun, span[0]), min(ended, span[1])
    return round((ended - begun).total_seconds() / 60) if ended > begun else 0


# -- the prompt and the answer ------------------------------------------------------------------------------


def prompt(read: Read) -> list[dict[str, str]]:
    """The two messages the model gets: the week's prompt with its days and language filled in, and
    the material as JSON."""
    made = read.made
    system = Template(PROMPT_FILE.read_text(encoding="utf-8")).safe_substitute(
        week=read.week,
        monday=read.monday,
        sunday=read.sunday,
        tz=str(made.zone),
        language=made.language,
        language_name=dream.LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def shape(found: Mapping[str, Any], read: Read) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The answer as a draft has it: the goal items checked first (`_reviews`: a goal of the
    material, a disposition, once each, resting on lines of the week; else dropped and counted), then
    every part's segments in order (`dream.segments_of`), one proposal for next week at most, the
    number rule held (`dream.hold_numbers`), no figure beside a person (`dream.hold_names`), and the
    evidence rule's share checked again; and what `extra` keeps of it: `parts`, `goals`, `numbers`,
    `dropped`, `marked`."""
    made = read.made
    dropped: Counter[str] = Counter()
    reviews, items = _reviews(found.get("goals"), read, dropped)
    segments, parts = dream.segments_of({**found, "goals": items}, made, drafts.WEEK_PARTS, strict=True)
    proposals = [i for i, part in enumerate(parts) if part == "next_week"]
    for i in reversed(proposals[NEXT_WEEK:]):
        del segments[i], parts[i]
        dropped[MORE_THAN_ONE] += 1
    marked: dict[str, int] = {}
    unbacked = dream.hold_numbers(segments, made.data, made)
    if unbacked:
        marked[dream.UNBACKED] = unbacked
    beside = dream.hold_names(segments, made)
    if beside:
        marked[dream.BESIDE_A_NAME] = beside
    dream.share_of(segments, made.unit)
    goal_segments = [i for i, part in enumerate(parts) if part == "goals"]
    extra: dict[str, Any] = {"parts": parts, "numbers": read.numbers}
    kept = [
        {**review, "segment": i}
        for review, i in zip(reviews, goal_segments, strict=True)
        if "evidence" in segments[i]  # a review whose sentence the number rule marked proposes nothing
    ]
    if kept:
        extra["goals"] = kept
    if dropped:
        extra["dropped"] = dict(dropped)
    if marked:
        extra["marked"] = marked
    return segments, extra


def _reviews(
    items: object, read: Read, dropped: Counter[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The goal items that hold, as reviews proposed (`{goal, text, disposition}`) and as segments
    (`{text, evidence}`) in the same order: an item that names no goal of the material, no
    disposition, a goal named before, or no reference of the week, or that has no text, is dropped."""
    reviews: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not str(item.get("text") or "").strip():
            dropped[NOT_A_GOAL] += 1
            continue
        ref = str(item.get("goal") or "").strip()
        line = read.goals.get(ref)
        if line is None:
            dropped[NOT_A_GOAL] += 1
            continue
        word = str(item.get("disposition") or "").strip().lower()
        disposition = goals.TYPED.get(word) or (word if word in goals.DISPOSITIONS else None)
        if disposition is None:
            dropped[NOT_A_DISPOSITION] += 1
            continue
        if ref in seen:
            dropped[GOAL_TWICE] += 1
            continue
        segment = dream._segment(
            {"text": item["text"], "evidence": item.get("evidence")}, read.made, strict=True
        )
        if segment is None or "evidence" not in segment:
            dropped[NOT_OF_THE_WEEK] += 1
            continue
        seen.add(ref)
        goal_text = str((line.get("payload") or {}).get("text") or "")
        reviews.append({"goal": str(line["id"]), "text": goal_text, "disposition": disposition})
        segments.append(segment)
    return reviews, segments


# -- the dream --------------------------------------------------------------------------------------------


def run(
    lb: Logbook,
    text: str | None = None,
    env: Mapping[str, str] | None = None,
    airports: Airports | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    today: date | None = None,
    read: Read | None = None,
) -> dream.Dream:
    """Dream the week `text` names (`which`; the last one over when None): the policy, the endpoint,
    the material (`read` when the caller built it under the lock already), the model's turn, the
    checks, and one `draft/v1` line appended under the writer lock unless `dry_run`. `DreamError`
    says why nothing was written (`NotOver`, `DayUndreamed`, the answer); `HeadMoved` when the record
    moved under the reading."""
    found = dream.ceiling(lb)
    ep = dream.endpoint(found, env)
    week, monday, sunday = which(text, today or dream.today())
    with lb.writer():
        read = read or material(lb, week, monday, sunday, found, airports)
        made = read.made
        if not made.ids:
            raise DreamError(f"{week} has no line under max_tier {found.max_tier}; nothing to dream")
        latest = standing_of(lb, week)
        source = drafts.SOURCE_PREFIX + ep.model
        version = policy.version(found)
        if not dry_run:
            dream.refuse_same(latest, source, made, version)
        messages = prompt(read)
        if say is not None:
            say(messages[0]["content"])
            say(messages[1]["content"])
        answer, found_answer = dream.ask(ep, messages, transport)
        segments, kept = shape(found_answer, read)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_WEEK,
            "subject": week,
            "read_head": made.read_head,
            "read_count": made.read_count,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                **kept,
                "read_ids_sha256": made.read_ids_sha256,
                "read_beside": read.beside,
                "policy_version": version,
            },
        }
        if read.question is not None:
            payload["extra"]["question"] = read.question
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        dream.valid(payload)
        if dry_run:
            return dream.Dream(week, None, payload, made.tier, messages, answer)
        line = dream.append(lb, made, source, payload)
    return dream.Dream(week, line, payload, made.tier, messages, answer)


# -- catch-up ---------------------------------------------------------------------------------------------


def changed_since(
    lb: Logbook, week: str, monday: str, sunday: str, found: policy.Ceiling, airports: Airports | None = None
) -> tuple[bool, str, Read]:
    """Whether a week that has ended needs dreaming, by the day's rule (`dream.why_again`): no draft
    yet, a standing draft the entry no longer stands behind, or what it would read today is not what
    the standing draft read. The material is returned so a caller that dreams does not read twice."""
    read = material(lb, week, monday, sunday, found, airports)
    latest = standing_of(lb, week)
    if latest is None:
        return True, "its Sunday is over, no draft yet", read
    why = dream.why_again(latest, found, read.made.read_count, read.made.read_ids_sha256)
    if why is not None:
        return True, why, read
    return False, f"unchanged since #{latest['seq']}", read


def weeks_to_catch_up(today: date, days: int) -> list[tuple[str, str, str]]:
    """The weeks whose seven days are all among the last `days` days before today, oldest first: the
    days a catch-up dreams, so their drafts are there to read (none under `days` 7)."""
    window = dream.days_to_catch_up(today, days)
    weeks = [parse_week(week_of(day)) for day in window if date.fromisoformat(day).weekday() == SUNDAY]
    return [week for week in weeks if week[1] >= window[0]]


def catch_up(
    lb: Logbook,
    days: int,
    today: date,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    airports: Airports | None = None,
) -> list[Outcome]:
    """Dream each week whose seven days are among the last `days` days (`weeks_to_catch_up`), when it
    needs it (`changed_since`); one `Outcome` per week, oldest first, `empty` for a week with no line
    under the ceiling. Run after the days, whose drafts it reads. The policy and the endpoint are
    checked once: a refusal there is `DreamError`."""
    found = dream.ceiling(lb)
    dream.endpoint(found, env)
    airports = airports or Airports.load()
    out: list[Outcome] = []
    with lb.writer():
        for week, monday, sunday in weeks_to_catch_up(today, days):
            try:
                needed, why, read = changed_since(lb, week, monday, sunday, found, airports)
                if not read.made.ids:
                    out.append(Outcome(week, "empty", "nothing logged"))
                    continue
                if not needed:
                    out.append(Outcome(week, "unchanged", why))
                    continue
                dreamed = run(lb, week, env, airports, transport=transport, today=today, read=read)
                out.append(Outcome(week, "dreamed", dream.detail_of(dreamed, why)))
            except (DreamError, HeadMoved, ValueError, stays.SettingsError) as e:
                out.append(Outcome(week, "refused", str(e)))
    return out


# -- the reader -------------------------------------------------------------------------------------------


def on_sunday(lb: Logbook, day: str) -> tuple[str | None, dict[str, Any] | None, dict[str, Any] | None]:
    """The week a Sunday closes, its standing draft and its withheld row, as `day DAY` carries them: by
    the Journeys' rule (`drafts.for_unit`: the `dream` entry today, the evidence checked against the
    week's lines). (None, None, None) on any other day."""
    if parse_day(day).weekday() != SUNDAY:
        return None, None, None
    week, monday, sunday = parse_week(week_of(day))
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, drafts.UNIT_WEEK).get(week, [])
        if not found:
            return week, None, None
        on_week = {
            str(line["id"])
            for d in day_range(monday, sunday)
            for line in idx.day(d)
            if str(line["id"]) not in retracted
        }
    draft, withheld = drafts.for_unit(found, on_week, None, drafts.allowed(lb.root), drafts.NOT_ON_WEEK)
    return week, draft, withheld
