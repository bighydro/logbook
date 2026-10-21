"""The dream of a chapter (`logbook dream chapter [ID]`, and `dream --catch-up` the first morning after
it closes): a model reads one chapter the owner named (RFC 0036, `chapter/v1`), open or closed, and
writes one `draft/v1` line about it (unit `chapter`, the amendment of 2026-10-21): its arc in a few
paragraphs' worth of sentences, what it was for (its `rules`, the owner's words), what it held and what
it closed. Every sentence points at the lines it came from. A proposal, as every draft: the chapter's
name, stretch and rules are the owner's, and only `chapter open` and `chapter close` write them.

It runs on the dream's engine (`logbook.contrib.dream`) under the same `dream` entry of
`policy/crossing.json`, the same endpoint and the same rules as the month and the week: read under the
entry's ceiling, every sentence cited or marked, more than 30 % unsupported refused, no figure the
items it cites do not give (`dream.hold_numbers`) and no figure beside a person (`dream_month.
hold_names`), the tier the highest among what it read, the entry's version recorded.

**From the drafts it spans, never the raw lines.** A chapter may run for years, so it is never read
line by line. It reads the chapter as the owner named it (its standing `chapter/v1` line: name, stretch,
`rules`), then the standing **month drafts** the entry allows for the months its stretch spans
(`MONTHS_SHOWN` at most, the latest), and, for a month of the stretch no month draft covers, the
standing **week drafts** of the weeks that touch it (`WEEKS_SHOWN` at most, the latest), each draft's
supported sentences only, as a model's words (`drafted`), with the references of the lines they rest
on. A sentence of a draft is given only when every line it rests on is a line on a day of the stretch,
not retracted and under the ceiling, read one by one through the index (`Index.by_id`): a month draft
of June given to a chapter that began on the 20th gives only what rests on the 20th and after. Those
lines, the chapter line and the reviews it gives are what a segment may cite (`read_count`); the drafts
and the goals they close are read beside them, toward the tier and the digest (`extra.read_beside`).

**What it held** is computed, never the model's: its days, the days signed (a standing `signed-day/v1`
line, RFC 0034), the months and the weeks drafted. **What it closed**: the goals the owner reviewed
`done`, `let go` or `superseded` on a day of the stretch (`review/v1`, by its `at`), and the chapter's
own close, its `to`, when it has one. An open chapter is read up to yesterday: today is still being
written.

**The subject** is the ids of the chapter's lines, the standing one first and then each it supersedes
(`chapter.successors`), so a reader finds the draft by any line of it; the standing draft of a chapter is
the latest of every draft that names one of them (`standing_of`). Closing a chapter writes a new line
(`chapter close`), so the line read changes and the chapter is dreamed again by the re-dream rule.

**The catch-up** (`catch_up_arcs`, the close's one hook for both): after the days and the weeks,
`dream --catch-up` looks at each month whose last day is among the days it looks at
(`dream_month.months_to_catch_up`: the first 06:00 close of a month dreams the month before), then at
each chapter that closed on one of those days or whose closing line was written on one
(`chapters_to_catch_up`), months first, since a chapter reads them. Each is dreamed when it needs it
and left alone while it is unchanged (`dream.why_again`, the week's comparison); an open chapter is
never caught up, only dreamed on demand. A month with no signed day, and a chapter no month or week
draft says anything of, are `empty`, never refused."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from string import Template
from typing import Any

from ..core import chapter as chapters
from ..core import day_start, drafts, goals, policy, reading, resolve, signing, stays
from ..core.chain import Line
from ..core.export import day_range
from ..core.flights import Airports
from ..core.index import Index
from ..core.store import HeadMoved, Logbook, retractions
from . import dream, dream_month
from .dream import DreamError, Material, Outcome
from .model_client import Transport
from .week_paper import parse_week, week_of

PROMPT_FILE = Path(__file__).with_name("dream-chapter-prompt.md")
PROMPT_NAME = "dream-chapter/1"  # kept under `extra.prompt`, so a draft says which prompt wrote it
UNIT = drafts.UNIT_CHAPTER
TOLD = dream_month.TOLD  # the sentences of one draft given, at most
MONTHS_SHOWN = 24  # the month drafts given, at most, the latest: a long chapter is still one prompt
WEEKS_SHOWN = 12  # the week drafts given for the months no month draft covers, at most, the latest
CLOSED = "closed"  # a chapter with a `to` on or before yesterday, as the material says it
OPEN = "open"


class NotBegun(DreamError):
    """The chapter begins today or later: there is nothing of it lived yet to read."""


class AboveCeiling(DreamError):
    """The chapter's own line is above the entry's ceiling: nothing of it crosses. On demand a
    refusal; in the catch-up a chapter held back, as the policy means it to be, never a failure."""


class NothingDrafted(DreamError):
    """No month or week draft says anything of the chapter's stretch: its arc is told from them."""


@dataclass(frozen=True)
class Chapter:
    """The chapter a dream reads: its standing line, the ids of its lines (the standing one first),
    its name and rules, its first day, its `to` (None while open) and the last day read."""

    line: Line
    chain: tuple[str, ...]
    name: str
    rules: str
    first: str
    to: str | None
    last: str

    @property
    def state(self) -> str:
        return CLOSED if self.to is not None else OPEN  # closed by its owner, whatever day it ends

    @property
    def words(self) -> str:
        """The chapter in words, the subject of its rows: its name and stretch, which carry the
        years `dream.hold_numbers` does not count as figures."""
        return f"{self.name} ({self.first} {chapters.EN_DASH} {self.last})"


@dataclass
class Read:
    """What the dream read of a chapter: the material and the ids of what it read beside its lines."""

    made: Material
    chapter: Chapter
    beside: int = 0
    told: int = 0  # the drafts that gave at least one sentence
    numbers: dict[str, Any] = field(default_factory=dict)  # `extra.numbers`: held and closed, with line ids


# -- the chapter ------------------------------------------------------------------------------------------


def _chain(line: Line, found: Sequence[Line]) -> tuple[str, ...]:
    """The ids of the chapter lines that are one chapter with the standing `line`: `line` first, then
    each line it supersedes, directly or through another, the latest first."""
    later = chapters.successors(found)
    target = str(line["id"])

    def current(line_id: str) -> str:
        seen = {line_id}
        while line_id in later and later[line_id] not in seen:
            line_id = later[line_id]
            seen.add(line_id)
        return line_id

    earlier = [x for x in found if str(x["id"]) != target and current(str(x["id"])) == target]
    earlier.sort(key=lambda x: int(x["seq"]), reverse=True)
    return (target, *(str(x["id"]) for x in earlier))


def of_line(line: Line, found: Sequence[Line], today: date) -> Chapter:
    """The chapter a standing line is, read up to yesterday; `NotBegun` when it begins today or later."""
    payload = line.get("payload") or {}
    first, to = chapters.span(line)
    yesterday = (today - timedelta(days=1)).isoformat()
    if first > yesterday:
        raise NotBegun(f"{payload.get('name')} begins on {first}; nothing of it is lived yet to read")
    return Chapter(
        line=line,
        chain=_chain(line, found),
        name=str(payload.get("name") or ""),
        rules=str(payload.get("rules") or ""),
        first=first,
        to=to,
        last=min(to, yesterday) if to is not None else yesterday,
    )


def which(lb: Logbook, text: str | None, today: date) -> Chapter:
    """The chapter `text` names: the id of any of its lines, its seq (`12` or `#12`), or its name (any
    case); with no text, the chapter yesterday was in, else the latest closed one. `ValueError` for text
    that names none; `DreamError` when the record has no chapter."""
    with lb.index() as idx:
        found = chapters.chapter_lines(idx.by_kind(chapters.KIND), retractions(idx.retractions()))
    current = chapters.standing(found)
    if not current:
        raise DreamError(
            'the record has no chapter; `logbook chapter open "NAME" --from YYYY-MM-DD` names one'
        )
    yesterday = (today - timedelta(days=1)).isoformat()
    if text is None:
        line, _clash = chapters.of_day(found, yesterday)
        if line is None:
            closed = sorted(
                (c for c in current if (chapters.span(c)[1] or "9999") <= yesterday),
                key=lambda c: (str(chapters.span(c)[1]), int(c["seq"])),
            )
            if not closed:
                raise DreamError(
                    "no chapter held yesterday and none has closed; `dream chapter ID` names one"
                )
            line = closed[-1]
        return of_line(line, found, today)
    wanted = text.strip()
    by_id = {str(x["id"]): x for x in found}
    named: Line | None = None
    if wanted in by_id:
        target = by_id[wanted]
        named = next((c for c in current if str(target["id"]) in _chain(c, found)), None)
    elif wanted.lstrip("#").isdigit():
        seq = int(wanted.lstrip("#"))
        by_seq = next((x for x in found if int(x["seq"]) == seq), None)
        if by_seq is not None:
            named = next((c for c in current if str(by_seq["id"]) in _chain(c, found)), None)
    else:
        matches = [
            c
            for c in current
            if str((c.get("payload") or {}).get("name") or "").casefold() == wanted.casefold()
        ]
        named = matches[-1] if matches else None
    if named is None:
        raise ValueError(
            f"no chapter is {text!r}: its id, its seq or its name, as `chapter list` prints them"
        )
    return of_line(named, found, today)


def standing_of(lb: Logbook, chain: Sequence[str]) -> Line | None:
    """The chapter's standing draft, whatever the entry allows: the latest of every draft that names one
    of its lines (a draft written while it was open names the open line alone), by rule 2."""
    with lb.index() as idx:
        by_subject = drafts.by_unit(idx.by_kind(drafts.KIND), retractions(idx.retractions()), UNIT)
    found = {str(line["id"]): line for line_id in chain for line in by_subject.get(line_id, [])}
    return drafts.standing(sorted(found.values(), key=lambda line: (str(line["at"]), int(line["seq"]))))


def months_of(first: str, last: str) -> list[str]:
    """The months `YYYY-MM` the local days `first` to `last` touch, in order."""
    out: list[str] = []
    year, month = int(first[:4]), int(first[5:7])
    while f"{year:04d}-{month:02d}" <= last[:7]:
        out.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


# -- the material -----------------------------------------------------------------------------------------


def material(lb: Logbook, ch: Chapter, found: policy.Ceiling) -> Read:
    """The chapter's material under the entry's ceiling (the module's docstring). `DreamError` when the
    chapter's own line, tier 2, is above the ceiling: its name and rules are what it is about."""
    tiers = dream.tiers_of(found)
    if int(ch.line.get("tier") or chapters.TIER) not in tiers:
        raise AboveCeiling(
            f"{ch.name} is a tier-{ch.line.get('tier') or chapters.TIER} line, above max_tier"
            f" {found.max_tier} of the {policy.DREAM_DESTINATION!r} entry; nothing of it crosses"
        )
    bounds = day_start.of(lb.meta)
    months = months_of(ch.first, ch.last)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        identities = resolve.identities_from([*idx.retractions(), *idx.resolutions()])
        allowed = drafts.allowed(lb.root)
        every_draft = idx.by_kind(drafts.KIND)
        month_drafts = drafts.by_unit(every_draft, retracted, drafts.UNIT_MONTH)
        week_drafts = drafts.by_unit(every_draft, retracted, drafts.UNIT_WEEK)
        by_month: dict[str, Line] = {}
        for month in months:
            line = drafts.standing(drafts.through(month_drafts.get(month, []), tiers, allowed)[0])
            if line is not None:
                by_month[month] = line
        weeks: list[str] = []
        for day in day_range(ch.first, ch.last):
            week = week_of(day)
            if day[:7] not in by_month and week not in weeks:
                weeks.append(week)
        by_week: dict[str, Line] = {}
        for week in weeks:
            line = drafts.standing(drafts.through(week_drafts.get(week, []), tiers, allowed)[0])
            if line is not None:
                by_week[week] = line
        shown_months = sorted(by_month)[-MONTHS_SHOWN:]
        shown_weeks = sorted(by_week)[-WEEKS_SHOWN:]
        given = [by_month[m] for m in shown_months] + [by_week[w] for w in shown_weeks]
        on_stretch = _on_stretch(idx, given, ch, tiers, retracted, bounds)
        signed = [
            line
            for day, line in signing.signatures(
                idx.by_kind(signing.KIND), retracted, dream_month.owner_of(lb)
            ).items()
            if ch.first <= day <= ch.last and reading.crossing([line], tiers)
        ]
        goal_lines = [
            g for g in reading.crossing(idx.by_kind(goals.KIND), tiers) if str(g["id"]) not in retracted
        ]
        review_lines = goals.review_lines(reading.crossing(idx.by_kind(goals.REVIEW), tiers), retracted)
    closing = [
        r
        for r in review_lines
        if ch.first <= bounds.day_of(str(r["at"])) <= ch.last
        and (r.get("payload") or {}).get("disposition") in goals.CLOSING
    ]
    ids = {ch.chain[0], *on_stretch, *(str(r["id"]) for r in closing)}
    made = Material(
        day=ch.words,
        unit=UNIT,
        tier=1,
        read_count=0,
        read_head=str(lb.meta["head"]),
        read_ids_sha256="",
        language=dream.DEFAULT_LANGUAGE,
        data={},
        ids=ids,
        zone=bounds.zone,
        canonical=dream.canonical(lb, identities),  # whose names no figure may stand beside
        identities=identities,
    )
    read = Read(made, ch)
    beside: dict[str, int] = {}
    chapter_ref = made.refs_of([ch.chain[0]])
    told_months, told_weeks, texts = [], [], [ch.name, ch.rules]
    for month in shown_months:
        told = _told(by_month[month], on_stretch, made)
        beside[str(by_month[month]["id"])] = int(by_month[month].get("tier") or 1)
        if told:
            told_months.append({"month": month, "drafted": told})
            texts += [t["drafted"] for t in told]
    for week in shown_weeks:
        told = _told(by_week[week], on_stretch, made)
        beside[str(by_week[week]["id"])] = int(by_week[week].get("tier") or 1)
        if told:
            _week, monday, sunday = parse_week(week)
            told_weeks.append({"week": week, "monday": monday, "sunday": sunday, "drafted": told})
            texts += [t["drafted"] for t in told]
    read.told = len(told_months) + len(told_weeks)
    made.language = dream.language_of(texts)
    held = {
        "days": len(day_range(ch.first, ch.last)),
        "signed": len(signed),
        "months_drafted": len(by_month),
        "weeks_drafted": len(by_week),
        "ref": chapter_ref,
    }
    standing_goals = goals.Goals(goal_lines)
    closed_goals = []
    for review in closing:
        payload = review.get("payload") or {}
        goal = standing_goals.current(str(payload.get("goal")))
        if goal is None:
            continue  # a goal above the ceiling, or retracted: not the model's to see
        beside[str(goal["id"])] = int(goal.get("tier") or goals.TIER)
        closed_goals.append(
            {
                "text": str((goal.get("payload") or {}).get("text") or ""),
                "disposition": payload.get("disposition"),
                "day": bounds.day_of(str(review["at"])),
                "ref": made.refs_of([str(review["id"])]),
            }
        )
    close = {"to": ch.to, "ref": chapter_ref} if ch.state == CLOSED else None
    made.data = {
        "chapter": {
            "name": ch.name,
            "from": ch.first,
            "to": ch.to,
            "read_to": ch.last,
            "state": ch.state,
            "rules": {"text": ch.rules} if ch.rules else None,
            "ref": chapter_ref,
        },
        "max_tier": found.max_tier,
        "months": told_months,
        "weeks": told_weeks,
        "held": held,
        "closed": {"goals": closed_goals, "chapter": close},
    }
    read.numbers = {
        "held": {k: v for k, v in held.items() if k != "ref"} | {"lines": [ch.chain[0]]},
        "closed": [
            {
                "goal": c["text"],
                "disposition": c["disposition"],
                "day": c["day"],
                "lines": [made.refs[r] for r in c["ref"] or []],
            }
            for c in closed_goals
        ],
    }
    tiers_read = [int(ch.line.get("tier") or chapters.TIER), *on_stretch.values(), *beside.values()]
    tiers_read += [int(r.get("tier") or goals.TIER) for r in closing]
    made.tier = max(tiers_read, default=1)
    made.read_count = len(ids)
    made.read_ids_sha256 = dream.digest(ids | set(beside))
    read.beside = len(set(beside) - ids)
    return read


def _on_stretch(
    idx: Index,
    given: Sequence[Line],
    ch: Chapter,
    tiers: Sequence[int],
    retracted: frozenset[str],
    bounds: day_start.DayStart,
) -> dict[str, int]:
    """id -> tier of every line the given drafts' supported sentences rest on that is a line on a day
    of the chapter's stretch, not retracted and under the ceiling: each read by its id, so the cost is
    the drafts' evidence, never the stretch's lines."""
    wanted: list[str] = []
    for line in given:
        for segment in (line.get("payload") or {}).get("segments") or []:
            evidence = segment.get("evidence") if isinstance(segment, dict) else None
            if isinstance(evidence, list):
                wanted += [str(e) for e in evidence]
    out: dict[str, int] = {}
    for line_id in dict.fromkeys(wanted):
        if line_id in retracted:
            continue
        rested = idx.by_id(line_id)
        if rested is None or not reading.crossing([rested], tiers):
            continue
        if ch.first <= bounds.day_of(str(rested["at"])) <= ch.last:
            out[line_id] = int(rested.get("tier") or 1)
    return out


def _told(line: Line, on_stretch: Mapping[str, int], made: Material) -> list[dict[str, Any]]:
    """A month's or a week's draft as it told the stretch: its supported sentences whose every line is
    on the stretch (`on_stretch`), a model's words (`drafted`), `TOLD` at most, with their references."""
    payload = line.get("payload") or {}
    extra = payload.get("extra")
    parts = extra.get("parts") if isinstance(extra, dict) else None
    segments = payload.get("segments") or []
    told: list[dict[str, Any]] = []
    for i, segment in enumerate(segments):
        if len(told) >= TOLD:
            break
        shown = drafts.segment_json(segment, set(on_stretch), drafts.NOT_ON_CHAPTER)
        if not shown["supported"] or not shown["evidence"] or dream_month.beside_a_name(shown["text"], made):
            continue  # a sentence with a figure beside a person (a week's `people`) is never passed on
        part = parts[i] if isinstance(parts, list) and len(parts) == len(segments) else None
        told.append({"part": part, "drafted": shown["text"], "ref": made.refs_of(shown["evidence"])})
    return told


# -- the prompt and the answer ------------------------------------------------------------------------------


def prompt(read: Read) -> list[dict[str, str]]:
    """The two messages the model gets: the chapter's prompt with its name, stretch and language filled
    in, and the material as JSON."""
    made, ch = read.made, read.chapter
    system = Template(PROMPT_FILE.read_text(encoding="utf-8")).safe_substitute(
        name=ch.name,
        first=ch.first,
        last=ch.last,
        state=(
            "open, read up to yesterday"
            if ch.to is None
            else f"closed on {ch.to}"
            if ch.to <= ch.last
            else f"closing on {ch.to}, read up to yesterday"
        ),
        tz=str(made.zone),
        language=made.language,
        language_name=dream.LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def shape(found: Mapping[str, Any], read: Read) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The answer as a draft has it, as the month's (`dream_month.shape`): the parts in order, strictly
    held to the evidence, the number rule and no figure beside a person, the share checked again; and
    `extra`'s `parts`, `numbers` and `marked`."""
    made = read.made
    segments, parts = dream.segments_of(found, made, drafts.CHAPTER_PARTS, strict=True)
    marked: dict[str, int] = {}
    unbacked = dream.hold_numbers(segments, made.data, made)
    if unbacked:
        marked[dream.UNBACKED] = unbacked
    beside = dream_month.hold_names(segments, made)
    if beside:
        marked[dream_month.BESIDE_A_NAME] = beside
    dream.share_of(segments, made.unit)
    extra: dict[str, Any] = {"parts": parts, "numbers": read.numbers}
    if marked:
        extra["marked"] = marked
    return segments, extra


# -- the dream --------------------------------------------------------------------------------------------


def run(
    lb: Logbook,
    text: str | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    today: date | None = None,
    read: Read | None = None,
) -> dream.Dream:
    """Dream the chapter `text` names (`which`): the policy, the endpoint, the material (`read` when the
    caller built it under the lock already), the model's turn, the checks, and one `draft/v1` line
    appended under the writer lock unless `dry_run`. `DreamError` says why nothing was written
    (`NotBegun`, `NothingDrafted`, the ceiling, the answer); `HeadMoved` when the record moved."""
    found = dream.ceiling(lb)
    ep = dream.endpoint(found, env)
    with lb.writer():
        if read is None:
            read = material(lb, which(lb, text, today or dream.today()), found)
        made, ch = read.made, read.chapter
        if not read.told:
            raise NothingDrafted(
                f"no month or week draft says anything of {ch.words}; a chapter's arc is told from"
                " them: `dream month YYYY-MM` or `dream week` first"
            )
        latest = standing_of(lb, ch.chain)
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
            "unit": UNIT,
            "subject": list(ch.chain),
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
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        dream.valid(payload)
        if dry_run:
            return dream.Dream(ch.words, None, payload, made.tier, messages, answer)
        line = dream.append(lb, made, source, payload)
    return dream.Dream(ch.words, line, payload, made.tier, messages, answer)


# -- catch-up ---------------------------------------------------------------------------------------------


def changed_since(lb: Logbook, ch: Chapter, found: policy.Ceiling) -> tuple[bool, str, Read]:
    """Whether a chapter needs dreaming, by the week's rule (`dream.why_again`): no draft yet, a standing
    draft the entry no longer stands behind, or what it would read today is not what it read (its close
    is a new line, so a chapter closed since its last draft is one). The material is returned too."""
    read = material(lb, ch, found)
    latest = standing_of(lb, ch.chain)
    if latest is None:
        return True, "closed, no draft yet", read
    why = dream.why_again(latest, found, read.made.read_count, read.made.read_ids_sha256)
    if why is not None:
        return True, why, read
    return False, f"unchanged since #{latest['seq']}", read


def chapters_to_catch_up(lb: Logbook, today: date, days: int, months: Sequence[str] = ()) -> list[Chapter]:
    """The standing chapters closed by yesterday whose last day, or whose closing line, is on one of the
    last `days` days before today, or whose stretch touches one of `months` (the months this catch-up
    looks at), by their first day: the first close after a chapter closes looks at it, so does the first
    after `chapter close` closes it later than its last day, and so does the first close of the month
    after its last, whose month draft it reads."""
    window = set(dream.days_to_catch_up(today, days))
    bounds = day_start.of(lb.meta)
    with lb.index() as idx:
        found = chapters.chapter_lines(idx.by_kind(chapters.KIND), retractions(idx.retractions()))
    yesterday = (today - timedelta(days=1)).isoformat()
    out = []
    for line in chapters.standing(found):
        to = chapters.span(line)[1]
        if to is None or to > yesterday:
            continue
        first = chapters.span(line)[0]
        touched = any(first[:7] <= month <= to[:7] for month in months)
        if to in window or bounds.day_of(str(line["at"])) in window or touched:
            out.append(of_line(line, found, today))
    return out


def catch_up_arcs(
    lb: Logbook,
    days: int,
    today: date,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    airports: Airports | None = None,
) -> list[Outcome]:
    """The close's hook for the month and the chapter, run after the days and the weeks, whose drafts
    they read: each month whose last day is among the last `days` days (`dream_month.months_to_catch_up`),
    then each chapter that closed on one of them (`chapters_to_catch_up`), each dreamed when it needs it;
    one `Outcome` each, months first. The policy and the endpoint are checked once: a refusal there is
    `DreamError`, before anything is read."""
    found = dream.ceiling(lb)
    dream.endpoint(found, env)
    airports = airports or Airports.load()
    out: list[Outcome] = []
    with lb.writer():
        months = dream_month.months_to_catch_up(today, days)
        for month, first, last in months:
            out.append(
                dream_month.catch_up_one(lb, month, first, last, found, today, env, transport, airports)
            )
        for ch in chapters_to_catch_up(lb, today, days, [month for month, _first, _last in months]):
            out.append(_catch_up_chapter(lb, ch, found, today, env, transport))
    return out


def _catch_up_chapter(
    lb: Logbook,
    ch: Chapter,
    found: policy.Ceiling,
    today: date,
    env: Mapping[str, str] | None,
    transport: Transport | None,
) -> Outcome:
    label = f"chapter {ch.name}"
    try:
        try:
            needed, why, read = changed_since(lb, ch, found)
        except AboveCeiling as e:
            return Outcome(label, "empty", f"held back: {e}")
        if not read.told:
            return Outcome(label, "empty", "no month or week draft says anything of it")
        if not needed:
            return Outcome(label, "unchanged", why)
        dreamed = run(lb, None, env, transport=transport, today=today, read=read)
        return Outcome(label, "dreamed", dream.detail_of(dreamed, why))
    except (DreamError, HeadMoved, ValueError, stays.SettingsError) as e:
        return Outcome(label, "refused", str(e))


# -- the reader -------------------------------------------------------------------------------------------


def for_chapter(lb: Logbook, ch: Chapter) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The chapter's standing draft and its withheld row, as `dream chapter --json` prints them and a
    page will read them, by the Journeys' rule (`drafts.for_unit`: the `dream` entry today); its
    evidence checked against the chapter's lines and the lines on a day of its stretch, each read by
    its id, never the stretch's every line."""
    bounds = day_start.of(lb.meta)
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        by_subject = drafts.by_unit(idx.by_kind(drafts.KIND), retracted, UNIT)
        found = sorted(
            {str(x["id"]): x for line_id in ch.chain for x in by_subject.get(line_id, [])}.values(),
            key=lambda line: (str(line["at"]), int(line["seq"])),
        )
        if not found:
            return None, None
        on_chapter = set(ch.chain)
        for draft in found:
            for segment in (draft.get("payload") or {}).get("segments") or []:
                evidence = segment.get("evidence") if isinstance(segment, dict) else None
                for line_id in evidence if isinstance(evidence, list) else []:
                    line = None if str(line_id) in retracted else idx.by_id(str(line_id))
                    if line is not None and ch.first <= bounds.day_of(str(line["at"])) <= ch.last:
                        on_chapter.add(str(line_id))
    return drafts.for_unit(found, on_chapter, None, drafts.allowed(lb.root), drafts.NOT_ON_CHAPTER)


def rows(payload: Mapping[str, Any], indent: str = "  ") -> list[str]:
    """What the chapter's line keeps beside its segments, in text: what it held, the goals it closed,
    and what was marked."""
    found = payload.get("extra")
    extra: Mapping[str, Any] = found if isinstance(found, dict) else {}
    found = extra.get("numbers")
    numbers: Mapping[str, Any] = found if isinstance(found, dict) else {}
    out: list[str] = []
    held = numbers.get("held")
    if isinstance(held, dict):
        out.append(
            f"{indent}  {'held':<9} {held.get('days')} days{drafts.DOT}{held.get('signed')} signed"
            f"{drafts.DOT}{held.get('months_drafted')} months and {held.get('weeks_drafted')} weeks drafted"
        )
    for goal in numbers.get("closed") or []:
        out.append(
            f"{indent}  {'closed':<9} “{goal['goal']}”{drafts.DOT}{goal['disposition']} on {goal['day']}"
        )
    marked = extra.get("marked")
    if isinstance(marked, dict) and marked:
        k = sum(int(n) for n in marked.values())
        why = ", ".join(f"{reason} {n}" for reason, n in marked.items())
        out.append(f"{indent}  {k} marked unsupported: {why}")
    return out
