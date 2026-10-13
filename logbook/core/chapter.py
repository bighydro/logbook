"""The chapter (RFC 0036, `chapter/v1`): a stretch of life the owner names, a sabbatical, a passage,
the year after a move, as one line. Not `lab chapters` (`logbook.labs.chapters`), which derives a
table of contents from the track and writes nothing; a chapter here is said by the owner.

The payload: `name`, `from` (its first local day), `to` (its last, absent while the chapter is open),
`rules` (what counts in the stretch, what the owner is for in it, as plain text; may be empty) and
`supersedes` when the line renames, re-bounds or closes an earlier one. `at` is when the owner named
it; tier 2, MUST, and `source` `manual`, as every line in the owner's words.

The **standing chapter** is the latest chapter line not retracted and not named in a later chapter's
`supersedes` (rule 2). The chapter of a local day is the standing chapter whose `from` is on or before
it and whose `to` is absent or on or after it (rule 3); when two standing chapters hold one day (two
writers, or a retraction that reopened one), the later by `from`, then `seq`, is the day's, and the
clash is said (rule 4). The writers here never make one: `open` refuses a stretch that overlaps a
standing chapter, naming it, and the dedupe key is `(name, from)`, so the same name from the same day
writes nothing and says so (rule 1). `close` writes the open chapter again with its `to` and every
other field, `rules` included, superseding it (rule 2).

Every writer holds the record's writer lock (`Logbook.writer`) from the first read to the append and
reads the head again before it appends (`goals.same_head`): a head another writer moved is
`HeadMoved` and nothing is written. The clock is `goals.now`, one for every writer of RFC 0036's
owner lines. `rules` is read by people: no reader derives anything from it."""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import day_start, goals
from .chain import Line
from .export import parse_day
from .store import Logbook, retractions

KIND = "chapter"
SCHEMA = "chapter/v1"
SOURCE = goals.SOURCE  # the owner named it
TIER = goals.TIER  # the owner's words about their own life: tier 2, MUST
DOT = goals.DOT
EN_DASH = "\u2013"


class ChapterError(ValueError):
    """A chapter the record refuses; the message says why and nothing is written."""


@dataclass(frozen=True)
class Opened:
    """What `open` did: the line it wrote, or None and the standing chapter that already has the
    same name from the same day (the dedupe key)."""

    line: Line | None
    existing: Line | None


# -- validation ------------------------------------------------------------------------------------------


def validate(payload: Mapping[str, Any]) -> list[str]:
    """Every way `payload` is not a `chapter/v1`, one sentence each; empty when it is one."""
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {SCHEMA!r}")
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append("name must be the chapter's name in the owner's words")
    first = _valid_day(payload.get("from"))
    if first is None:
        problems.append(f"from {payload.get('from')!r} is not a local day, YYYY-MM-DD")
    if "to" in payload:
        last = _valid_day(payload.get("to"))
        if last is None:
            problems.append(f"to {payload.get('to')!r} is not a local day, YYYY-MM-DD")
        elif first is not None and last < first:
            problems.append(f"to {last} is before from {first}")
    if not isinstance(payload.get("rules"), str):
        problems.append("rules must be plain text, empty when the owner has not said")
    if "supersedes" in payload and (not isinstance(payload["supersedes"], str) or not payload["supersedes"]):
        problems.append("supersedes must be the id of the earlier chapter line")
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    return problems


def _valid_day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_day(value)
    except ValueError:
        return None


# -- reading ---------------------------------------------------------------------------------------------


def is_chapter(line: Mapping[str, Any]) -> bool:
    return line.get("kind") == KIND and (line.get("payload") or {}).get("schema") == SCHEMA


def chapter_lines(lines: Iterable[Line], retracted: Collection[str] = ()) -> list[Line]:
    """The chapter lines not retracted whose `from` is a local day, by `seq`."""
    found = [
        line
        for line in lines
        if is_chapter(line)
        and str(line["id"]) not in retracted
        and _valid_day((line.get("payload") or {}).get("from")) is not None
    ]
    return sorted(found, key=lambda line: int(line["seq"]))


def successors(found: Sequence[Line]) -> dict[str, str]:
    """id → the id of the latest later chapter line naming it in `supersedes`."""
    by_id = {str(line["id"]): line for line in found}
    later: dict[str, str] = {}
    for line in found:
        named = (line.get("payload") or {}).get("supersedes")
        earlier = by_id.get(named) if isinstance(named, str) else None
        if earlier is not None and int(earlier["seq"]) < int(line["seq"]):
            later[str(earlier["id"])] = str(line["id"])
    return later


def standing(found: Sequence[Line]) -> list[Line]:
    """Rule 2: the chapter lines no later chapter names in `supersedes`, by `from`, then `seq`."""
    replaced = successors(found)
    kept = [line for line in found if str(line["id"]) not in replaced]
    return sorted(kept, key=_order)


def span(line: Line) -> tuple[str, str | None]:
    """A chapter's first and last local day; None for the last while it is open."""
    payload = line.get("payload") or {}
    last = payload.get("to")
    return str(payload["from"]), last if _valid_day(last) is not None else None


def holds(line: Line, day: str) -> bool:
    """Rule 3: whether `day` is in the chapter's stretch."""
    first, last = span(line)
    return first <= day and (last is None or day <= last)


def of_day(found: Sequence[Line], day: str) -> tuple[Line | None, list[Line]]:
    """The chapter of `day` among the standing chapters `found` (rule 3), and the other standing
    chapters that hold it too (the clash of rule 4): the later by `from`, then `seq`, is the day's."""
    holding = [line for line in standing(found) if holds(line, day)]
    if not holding:
        return None, []
    return holding[-1], holding[:-1]


def overlaps(first: str, last: str | None, line: Line) -> bool:
    """Whether the stretch `first`..`last` (None: open) shares a day with the chapter's."""
    other_first, other_last = span(line)
    return (other_last is None or first <= other_last) and (last is None or other_first <= last)


def for_day(lines: Iterable[Line], retracted: Collection[str], day: str) -> dict[str, Any] | None:
    """The Day's `chapter`: `{name, line, from, to}` of the chapter `day` is in, with `clash`, the
    names and lines of the other standing chapters that hold it, only when there are some; None for
    a day in no chapter."""
    chapter, clash = of_day(chapter_lines(lines, retracted), day)
    if chapter is None:
        return None
    out = _json(chapter)
    if clash:
        out["clash"] = [_json(line) for line in clash]
    return out


def header_text(chapter: Mapping[str, Any] | None) -> str:
    """`chapter The Lofoten summer` for the Day's header, with `, clashes with <name>` when another
    standing chapter holds the day too; nothing for a day in no chapter."""
    if not chapter:
        return ""
    text = f"chapter {chapter['name']}"
    clash = chapter.get("clash") or []
    if clash:
        text += ", clashes with " + ", ".join(str(other["name"]) for other in clash)
    return text


def span_text(payload: Mapping[str, Any]) -> str:
    """`2026-06-20 - 2026-08-09` (an en dash between), or `2026-08-10 -` while open."""
    last = payload.get("to")
    return (
        f"{payload.get('from')} {EN_DASH} {last}"
        if isinstance(last, str)
        else f"{payload.get('from')} {EN_DASH}"
    )


def row_text(payload: Mapping[str, Any]) -> str:
    """`The Lofoten summer  2026-06-20 - 2026-08-09` (an en dash): a chapter line's row on its Day and in
    `show`."""
    return f"{payload.get('name')}  {span_text(payload)}"


def line_row(line: Line, found: Sequence[Line]) -> dict[str, Any]:
    """A chapter line on the Day of its `at`: its fields, and the line that superseded it, if any."""
    return {**_json(line), "superseded": successors(found).get(str(line["id"]))}


def _json(line: Line) -> dict[str, Any]:
    payload = line.get("payload") or {}
    first, last = span(line)
    return {"name": payload.get("name"), "line": str(line["id"]), "from": first, "to": last}


def _order(line: Line) -> tuple[str, int]:
    return str((line.get("payload") or {}).get("from")), int(line["seq"])


# -- writing ---------------------------------------------------------------------------------------------


def open_chapter(
    lb: Logbook,
    name: str,
    start: str | None = None,
    to: str | None = None,
    rules: str | None = None,
) -> Opened:
    """One `chapter/v1` line: `name`, `from` `start` (today by default, the record's local day), `to`
    when the chapter is already over, and `rules` (empty when not given). Nothing is written, and
    `Opened.existing` says why, when a chapter of that name already starts that day (rule 1).
    `ChapterError` when the stretch overlaps a standing chapter, naming it (rule 4); `HeadMoved` when
    another writer moved the head under it."""
    words = (name or "").strip()
    if not words:
        raise ChapterError("the chapter's name is empty; name it in your own words")
    with lb.writer():
        meta = lb.meta
        today = day_start.of(meta).today(goals.now()).isoformat()
        first = _day(start, "--from") if start is not None else today
        payload: dict[str, Any] = {"schema": SCHEMA, "name": words, "from": first}
        if to is not None:
            payload["to"] = _day(to, "--to")
            if payload["to"] < first:
                raise ChapterError(f"--to {payload['to']} is before --from {first}")
        payload["rules"] = (rules or "").strip()
        with lb.index() as idx:
            found = chapter_lines(idx.by_kind(KIND), retractions(idx.retractions()))
        later = successors(found)
        for line in found:
            other = line.get("payload") or {}
            if other.get("name") == words and other.get("from") == first:
                current = _current(str(line["id"]), later, found)
                return Opened(None, current)
        _no_overlap(first, payload.get("to"), standing(found))
        return Opened(_append(lb, meta, payload), None)


def close(lb: Logbook, to: str | None = None) -> Line:
    """The open chapter closed: one `chapter/v1` line with every field of the standing chapter that has
    no `to` (the later by `from`, then `seq`, if two do), `to` set (today by default) and `supersedes`
    naming it (rule 2). `ChapterError` when no chapter is open or `to` is before its first day;
    `HeadMoved` when another writer moved the head under it."""
    with lb.writer():
        meta = lb.meta
        today = day_start.of(meta).today(goals.now()).isoformat()
        last = _day(to, "--to") if to is not None else today
        with lb.index() as idx:
            found = chapter_lines(idx.by_kind(KIND), retractions(idx.retractions()))
        current = standing(found)
        still_open = [line for line in current if span(line)[1] is None]
        if not still_open:
            raise ChapterError("no chapter is open; `logbook chapter open NAME` opens one")
        chapter = still_open[-1]
        payload = {k: v for k, v in (chapter.get("payload") or {}).items() if k != "supersedes"}
        if last < str(payload["from"]):
            raise ChapterError(f"--to {last} is before {payload['name']} began, on {payload['from']}")
        payload["to"] = last
        payload["supersedes"] = str(chapter["id"])
        others = [line for line in current if line["id"] != chapter["id"]]
        _no_overlap(str(payload["from"]), last, others)
        return _append(lb, meta, payload)


def _append(lb: Logbook, meta: Mapping[str, Any], payload: dict[str, Any]) -> Line:
    problems = validate(payload)
    if problems:
        raise ChapterError(f"the chapter would not be a {SCHEMA}: {problems[0]}; nothing was written")
    goals.same_head(lb, meta, "the chapters were read")
    written = goals.stamp(goals.now())
    return lb.append(at=written, source=SOURCE, kind=KIND, tier=TIER, payload=payload, recorded_at=written)


def _no_overlap(first: str, last: str | None, found: Sequence[Line]) -> None:
    """Rule 4: `ChapterError` naming the first standing chapter the stretch shares a day with."""
    for line in found:
        if overlaps(first, last, line):
            other = line.get("payload") or {}
            close_first = (
                " (close it first: `logbook chapter close --to DAY`)" if span(line)[1] is None else ""
            )
            raise ChapterError(
                f"{span_text({'from': first, 'to': last})} overlaps {other.get('name')}"
                f" ({span_text(other)}, #{line['seq']}); chapters do not overlap{close_first}"
            )


def _current(chapter_id: str, later: Mapping[str, str], found: Sequence[Line]) -> Line:
    by_id = {str(line["id"]): line for line in found}
    seen = {chapter_id}
    while chapter_id in later and later[chapter_id] not in seen:
        chapter_id = later[chapter_id]
        seen.add(chapter_id)
    return by_id[chapter_id]


def _day(text: str, flag: str) -> str:
    try:
        return goals.day_of(text, flag)
    except goals.GoalError as e:
        raise ChapterError(str(e)) from None


def listing(lb: Logbook) -> dict[str, Any]:
    """`chapter list`: every standing chapter by `from`, with its rules, the one today is in, and the
    ids of the lines it supersedes. Read through the index; nothing is written."""
    days = day_start.of(lb.meta)
    today = days.today(goals.now()).isoformat()
    with lb.index() as idx:
        found = chapter_lines(idx.by_kind(KIND), retractions(idx.retractions()))
    current, _clash = of_day(found, today)
    out = []
    for line in standing(found):
        payload = line.get("payload") or {}
        out.append(
            {
                **_json(line),
                "seq": int(line["seq"]),
                "rules": payload.get("rules"),
                "supersedes": payload.get("supersedes"),
                "today": current is not None and current["id"] == line["id"],
            }
        )
    return {"today": today, "chapters": out}


def listing_rows(found: Mapping[str, Any]) -> list[str]:
    """`chapter list` as text: per chapter its seq, stretch and name, `· today` on the one today is in,
    and its rules under it."""
    chapters = found["chapters"]
    if not chapters:
        return ['no chapters yet; `logbook chapter open "NAME" --from YYYY-MM-DD` names one']
    out = []
    for chapter in chapters:
        stretch = span_text(chapter)
        mark = f"{DOT}today" if chapter["today"] else ""
        out.append(f"  #{chapter['seq']:<5} {stretch:<25} {chapter['name']}{mark}")
        if chapter.get("rules"):
            out.append(f"         {chapter['rules']}")
    return out
