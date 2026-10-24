"""Closing the week (RFC 0043 §8, slice D, part 2), through the writers that exist: no new profile.

Two acts, both the owner's words, tier 2, each on the week's Sunday:

1. **The intention**: the week's one proposal kept (or said in the owner's own words) as one
   `note/v1` line labelled `intention` on the Sunday, through `notes.write` with `day reflect`'s
   source: the line `day reflect SUNDAY --intention "…"` writes, byte for byte, whether the page's
   form or the command line writes it (`keep`). Its words are one line, the whitespace between them
   folded to one space, so a browser's line ends and a shell's are the same words. An intention
   already kept on that Sunday is never duplicated: the same words again write nothing, and other
   words are a new line whose `supersedes` names it (RFC 0010 rule 2), so one intention stands for a
   week (`standing`). Next week's mornings show it under *what today was for* (`for_day`), in ink.
2. **The verdicts**: each standing goal's verdict for the week, one of the five, through
   `goals.review` with the period `week` at the Sunday: the line `goal review GOAL VERDICT --period
   week --at SUNDAY` writes. A goal reviewed already on a day of the week (any period, as `review
   goal`'s sitting counts it) is not reviewed again: the same verdict on the same day writes nothing,
   any other is refused.

`close` is the week page's one POST: every item checked first under one writer lock (each verdict
through `goals.review`'s own checks, `dry_run`; the intention through `keep`'s), and only then written,
under the same lock, so any refusal writes nothing. A week is closed on its Sunday or after it, never
before: a Sunday ahead of today is refused."""

from __future__ import annotations

import contextlib
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from ..core import day_start, goals, notes
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import Logbook, retractions
from . import week_paper

INTENTION = notes.INTENTION
SOURCE = "reflect"  # `day reflect`'s (`reflect.SOURCE`): the command that writes the same line
PERIOD = "week"  # a verdict on the week page covers the week, as `review goal`'s sitting's does
SUNDAY = 6  # `date.weekday()` of a Sunday


class CloseError(ValueError):
    """A close the record refuses; the message says why and nothing is written."""


@dataclass(frozen=True)
class Kept:
    """What `keep` did: the line it wrote (or, dry, None), the intention already kept in the same words
    (nothing written), and the intention the new one takes the place of."""

    line: Line | None
    existing: Line | None
    supersedes: Line | None


@dataclass(frozen=True)
class Verdict:
    """One goal's verdict as the form or the command line tells it: the goal line's id, the word, your
    words on it."""

    goal: str
    word: str
    note: str | None = None


@dataclass(frozen=True)
class Closed:
    """What `close` wrote: each verdict's `goals.Reviewed`, in the order told, and the intention's
    `Kept` when one was told."""

    reviews: list[goals.Reviewed]
    kept: Kept | None


@dataclass(frozen=True)
class Intention:
    """The intention kept for a week, as a Day of the next week shows it: its words, the Sunday it is
    on, that Sunday's week, and its line."""

    text: str
    sunday: str
    week: str
    line: str


def words(text: str | None) -> str:
    """An intention's words as the line keeps them: one line, the whitespace between words one space."""
    return " ".join((text or "").split())


def sunday_of(day: str) -> str:
    """The Sunday of the ISO week `day` is in."""
    d = date.fromisoformat(day)
    return (d + timedelta(days=SUNDAY - d.weekday())).isoformat()


def closing(sunday: str, today: str) -> str:
    """`sunday` as a local day when it is a Sunday that has come; `CloseError` otherwise."""
    try:
        day = parse_day(sunday.strip()).isoformat()
    except ValueError:
        raise CloseError(f"{sunday!r} is not a local day, YYYY-MM-DD") from None
    if date.fromisoformat(day).weekday() != SUNDAY:
        raise CloseError(f"{day} is not a Sunday; a week is closed on its Sunday, {sunday_of(day)}")
    if day > today:
        raise CloseError(f"{day} is ahead of today, {today}; a week is closed on its Sunday or after it")
    return day


def standing(lines: Iterable[Line], retracted: Collection[str] = ()) -> list[Line]:
    """The intentions among `lines` that stand: labelled `intention`, not retracted, and not named in
    the `supersedes` of another intention among them that stands; in the day's order."""
    found = notes.standing(lines, INTENTION, retracted)
    named = {str((line.get("payload") or {}).get("supersedes")) for line in found}
    return [line for line in found if str(line["id"]) not in named]


def kept(lb: Logbook, sunday: str, tiers: Sequence[int] | None = None) -> Line | None:
    """The intention standing on `sunday` through the gate `tiers` (None: every tier), the latest when
    two writers left two; None when none was kept."""
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        lines = [
            line
            for line in idx.by_kind(notes.KIND, sunday, sunday)
            if tiers is None or int(line.get("tier") or 0) in tiers
        ]
    found = standing(lines, retracted)
    return found[-1] if found else None


def for_day(lb: Logbook, day: str, tiers: Sequence[int] | None = None) -> Intention | None:
    """The intention a Day shows under *what today was for*: the one kept on the Sunday before the
    day's week, through the gate; None when that Sunday kept none."""
    before = (date.fromisoformat(day) - timedelta(days=7)).isoformat()
    week, _monday, sunday = week_paper.parse_week(week_paper.week_of(before))
    line = kept(lb, sunday, tiers)
    if line is None:
        return None
    return Intention(str((line.get("payload") or {}).get("text") or ""), sunday, week, str(line["id"]))


def keep(lb: Logbook, sunday: str, text: str, today: str | None = None, dry_run: bool = False) -> Kept:
    """The intention `text` kept on `sunday` as one `note/v1` line, label `intention`, source
    `reflect`, through `notes.write` (`today` the record's today unless the caller knows better);
    nothing written when the intention standing there has the same words (`Kept.existing`), and other
    words supersede it. `CloseError` for empty words or a day that is not a Sunday that has come.
    `dry_run` checks all of it, writes nothing and takes no lock."""
    said = words(text)
    if not said:
        raise CloseError("the intention is empty; say it in a sentence")
    with contextlib.nullcontext() if dry_run else lb.writer():
        days = day_start.of(lb.meta)
        on = today if today is not None else notes.today_in(days)
        day = closing(sunday, on)
        earlier = kept(lb, day)
        if earlier is not None and (earlier.get("payload") or {}).get("text") == said:
            return Kept(None, earlier, None)
        notes.moment(day, str(lb.meta["timezone"]), None, on, days)
        if dry_run:
            return Kept(None, None, earlier)
        line = notes.write(
            lb,
            day,
            said,
            INTENTION,
            SOURCE,
            today=on,
            supersedes=None if earlier is None else str(earlier["id"]),
        )
        return Kept(line, None, earlier)


def close(
    lb: Logbook,
    week: str,
    verdicts: Sequence[Verdict],
    intention: str | None = None,
    today: str | None = None,
) -> Closed:
    """The week page's one POST: each verdict on a goal, and the intention when one is told, every one
    checked before the first line is written and all of it under one writer lock, so a refusal
    (`CloseError`, naming the item) writes nothing. Nothing told is refused too."""
    week, monday, sunday = week_paper.parse_week(week)
    if not verdicts and intention is None:
        raise CloseError("nothing to write: give a goal its verdict, or keep the intention")
    with lb.writer():
        days = day_start.of(lb.meta)
        on = today if today is not None else notes.today_in(days)
        closing(sunday, on)
        with lb.index() as idx:
            retracted = retractions(idx.retractions())
            chains = goals.Goals(idx.by_kind(goals.KIND), retracted)
            reviews = goals.review_lines(idx.by_kind(goals.REVIEW), retracted)
        seen: set[str] = set()
        for v in verdicts:
            if v.goal not in chains.by_id:
                raise CloseError(f"{v.goal!r} is no goal line of the record; nothing was written")
            current = chains.current(v.goal) or chains.by_id[v.goal]
            text = str((current.get("payload") or {}).get("text") or "")
            if str(current["id"]) in seen:
                raise CloseError(f"goal “{text}” is given two verdicts; give it one; nothing was written")
            seen.add(str(current["id"]))
            try:
                checked = goals.review(lb, v.goal, v.word, PERIOD, v.note, at=sunday, dry_run=True)
            except goals.GoalError as e:
                raise CloseError(f"goal “{text}”: {e}; nothing was written") from None
            chain = chains.chain(v.goal)
            earlier = [
                r
                for r in reviews
                if str(r["payload"]["goal"]) in chain and monday <= days.day_of(str(r["at"])) <= sunday
            ]
            same = checked.existing is not None and checked.existing["payload"].get(
                "disposition"
            ) == goals.disposition(v.word)
            if earlier and not same:
                said = checked.existing or earlier[-1]
                raise CloseError(
                    f"goal “{text}” has its verdict for {week} already:"
                    f" {said['payload'].get('disposition')} on {days.day_of(str(said['at']))}"
                    f" (#{said['seq']}); nothing was written"
                )
        if intention is not None:
            keep(lb, sunday, intention, on, dry_run=True)
        written = [goals.review(lb, v.goal, v.word, PERIOD, v.note, at=sunday) for v in verdicts]
        return Closed(written, keep(lb, sunday, intention, on) if intention is not None else None)
