"""Goals and the verdicts on them (RFC 0036, `goal/v1` and `review/v1`): what the owner is for, said
once in their own words, and what became of it, said by the owner on a date.

A goal is one line: `text`, the `horizon` it is for (`life`, `year` or `quarter`), `from`, the first
local day it holds for, and optionally `until`, the last. `at` is when the owner wrote it. A goal
said better or bounded differently is a new goal line whose `supersedes` names the earlier one; the
**standing goal** is the latest goal line not retracted and not named in a later goal's
`supersedes`, and the chain of `supersedes` is one goal (`Goals`).

A review is one line: `goal` (the id of any goal line of the chain), `disposition` (one of five
strings: `advancing`, `stalled`, `done`, `let go`, `superseded`; `let go` has a space, and the
command line takes `let-go` for it), `period` (`day`, `week`, `month`, `quarter` or `year`) and
optionally `note`. Its `at` is the date the verdict is about and `recorded_at` when it was written,
so a verdict on August written in October is on the August Day. The **standing review** of a goal is
its latest review by `at`, then `seq`, not retracted; `done`, `let go` and `superseded` close the
goal, `advancing` and `stalled` keep it open. The dedupe key is `(goal, period, at)`: a second
review of the same goal (any line of its chain) for the same period on the same local day writes
nothing and says so (`Reviewed.existing`). A writer refuses an `at` more than five minutes past its
own clock (RFC 0034 amendment 2's rule) and one before the goal's `from`.

Each is tier 2, MUST, and `source` `manual`: the owner's words, never a producer's choice of tier.
Every writer here holds the record's writer lock (`Logbook.writer`) from the first read of the
index to the append and reads the head again before it appends: a head another writer moved in
between is `HeadMoved` and nothing is written. `now` is the one clock every writer reads, the `at`
and the `recorded_at` of what it writes, so a test can pin it.

The Day reads `reviews_on` (a row per review standing on its day, the goal's current text beside
it) and `goal_row` (a goal line listed on the day of its `at`); `logbook goal list` reads
`listing`. Nothing here derives anything from a goal on a Day but its own text."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import day_start, signing, store
from .chain import Line
from .day_start import DayStart
from .export import parse_day
from .store import HeadMoved, Logbook, retractions, utc

KIND = "goal"
SCHEMA = "goal/v1"
REVIEW = "review"
REVIEW_SCHEMA = "review/v1"
SOURCE = "manual"  # the owner wrote it: not a tool, not a model
TIER = 2  # the owner's words: tier 2, MUST (SPEC §4, as note/v1)
LIFE, YEAR, QUARTER = "life", "year", "quarter"
HORIZONS = (LIFE, YEAR, QUARTER)
ADVANCING, STALLED, DONE, LET_GO, SUPERSEDED = "advancing", "stalled", "done", "let go", "superseded"
DISPOSITIONS = (ADVANCING, STALLED, DONE, LET_GO, SUPERSEDED)
OPEN = (ADVANCING, STALLED)  # the verdicts that keep a goal open
CLOSING = (DONE, LET_GO, SUPERSEDED)  # the verdicts that close it
TYPED = {ADVANCING: ADVANCING, STALLED: STALLED, DONE: DONE, "let-go": LET_GO, SUPERSEDED: SUPERSEDED}
PERIODS = ("day", "week", "month", "quarter", "year")
PERIOD_OF_HORIZON = {LIFE: "year", YEAR: "year", QUARTER: "quarter"}  # a review's period when none is given
SKEW = signing.SKEW  # how far ahead of this clock an `at` may be (RFC 0034 amendment 2)
AT_EXAMPLE = "2026-08-31T22:00:00+02:00"
DOT = " · "
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
_MOMENT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})\Z")


class GoalError(ValueError):
    """A goal or a review the record refuses; the message says why and nothing is written."""


@dataclass(frozen=True)
class Reviewed:
    """What `review` did: the line it wrote, or, when the same goal already had a review for the same
    period on the same day (the dedupe key), None and that review; and the goal's standing line."""

    line: Line | None
    existing: Line | None
    goal: Line


def now() -> datetime:
    """The clock every writer here reads, as one function so a test can pin it."""
    return datetime.now(UTC)


def stamp(instant: datetime) -> str:
    """An instant as SPEC §2 writes it: UTC to the second, with a Z."""
    return instant.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def disposition(word: str) -> str:
    """The disposition `word` names, as the line stores it: `let-go` (or `let go`) is `let go`. A
    sixth word is refused naming the five."""
    text = word.strip().lower()
    if text in DISPOSITIONS:
        return text
    found = TYPED.get(text)
    if found is None:
        raise GoalError(f"{word!r} is not a disposition; a goal is {words()}")
    return found


def words() -> str:
    """`advancing, stalled, done, let-go or superseded`: the five as the command line takes them."""
    typed = [value.replace(" ", "-") for value in DISPOSITIONS]
    return f"{', '.join(typed[:-1])} or {typed[-1]}"


def day_of(text: str, flag: str) -> str:
    """`text` as a local day, `YYYY-MM-DD`, or `GoalError` naming the flag."""
    try:
        return parse_day(text.strip()).isoformat()
    except ValueError:
        raise GoalError(f"{flag} {text!r} is not a local day, YYYY-MM-DD") from None


def plain(text: str | None, what: str) -> str:
    """`text` stripped; `GoalError` when nothing is left."""
    found = (text or "").strip()
    if not found:
        raise GoalError(f"{what} is empty; say it in your own words")
    return found


# -- validation ------------------------------------------------------------------------------------------


def validate(payload: Mapping[str, Any]) -> list[str]:
    """Every way `payload` is not a `goal/v1`, one sentence each; empty when it is one."""
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {SCHEMA!r}")
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        problems.append("text must be the goal in the owner's words")
    if payload.get("horizon") not in HORIZONS:
        problems.append(f"horizon must be one of {', '.join(HORIZONS)}")
    first = _valid_day(payload.get("from"))
    if first is None:
        problems.append(f"from {payload.get('from')!r} is not a local day, YYYY-MM-DD")
    if "until" in payload:
        last = _valid_day(payload.get("until"))
        if last is None:
            problems.append(f"until {payload.get('until')!r} is not a local day, YYYY-MM-DD")
        elif first is not None and last < first:
            problems.append(f"until {last} is before from {first}")
    if "supersedes" in payload and (not isinstance(payload["supersedes"], str) or not payload["supersedes"]):
        problems.append("supersedes must be the id of the earlier goal line")
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    return problems


def validate_review(payload: Mapping[str, Any]) -> list[str]:
    """Every way `payload` is not a `review/v1`, one sentence each; empty when it is one."""
    problems: list[str] = []
    if payload.get("schema") != REVIEW_SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {REVIEW_SCHEMA!r}")
    if not isinstance(payload.get("goal"), str) or not payload["goal"]:
        problems.append("goal must be the id of the goal line reviewed")
    if payload.get("disposition") not in DISPOSITIONS:
        problems.append(f"disposition must be one of {', '.join(repr(d) for d in DISPOSITIONS)}")
    if payload.get("period") not in PERIODS:
        problems.append(f"period must be one of {', '.join(PERIODS)}")
    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        problems.append("note must be plain text")
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


def is_goal(line: Mapping[str, Any]) -> bool:
    return line.get("kind") == KIND and (line.get("payload") or {}).get("schema") == SCHEMA


def is_review(line: Mapping[str, Any]) -> bool:
    payload = line.get("payload") or {}
    return line.get("kind") == REVIEW and payload.get("schema") == REVIEW_SCHEMA


class Goals:
    """The goal lines of the record not retracted, and the chains their `supersedes` make: which
    line stands for each, and which lines are one goal."""

    def __init__(self, lines: Iterable[Line], retracted: Collection[str] = ()):
        found = [line for line in lines if is_goal(line) and str(line["id"]) not in retracted]
        self.lines = sorted(found, key=lambda line: int(line["seq"]))
        self.by_id = {str(line["id"]): line for line in self.lines}
        self.successor: dict[str, str] = {}  # id -> the id of the latest later goal naming it
        for line in self.lines:
            named = (line.get("payload") or {}).get("supersedes")
            earlier = self.by_id.get(named) if isinstance(named, str) else None
            if earlier is not None and int(earlier["seq"]) < int(line["seq"]):
                self.successor[str(earlier["id"])] = str(line["id"])

    def standing(self) -> list[Line]:
        """The standing goals, in the order they were written."""
        return [line for line in self.lines if str(line["id"]) not in self.successor]

    def current(self, goal_id: str) -> Line | None:
        """The standing goal of the chain `goal_id` is on; None for an id that is no goal line here."""
        if goal_id not in self.by_id:
            return None
        seen = {goal_id}
        while goal_id in self.successor and self.successor[goal_id] not in seen:
            goal_id = self.successor[goal_id]
            seen.add(goal_id)
        return self.by_id[goal_id]

    def chain(self, goal_id: str) -> set[str]:
        """Every goal line that is one goal with `goal_id`: the ones whose standing goal is its."""
        current = self.current(goal_id)
        if current is None:
            return {goal_id}
        target = str(current["id"])
        return {id_ for id_ in self.by_id if str((self.current(id_) or {}).get("id")) == target}


def review_lines(lines: Iterable[Line], retracted: Collection[str] = ()) -> list[Line]:
    """The review lines not retracted that name a goal, by `at` then `seq`."""
    found = [
        line
        for line in lines
        if is_review(line)
        and str(line["id"]) not in retracted
        and isinstance((line.get("payload") or {}).get("goal"), str)
    ]
    return sorted(found, key=_order)


def standing_review(reviews: Sequence[Line], chain: Collection[str]) -> Line | None:
    """Rule 2: the latest review by `at`, then `seq`, of any goal line in `chain`; None when the
    goal has none (it is unreviewed)."""
    found = [line for line in reviews if str(line["payload"]["goal"]) in chain]
    return max(found, key=_order) if found else None


def state(goal: Line, review: Line | None, today: str) -> str:
    """`open`, or why the goal is not: the closing verdict (`done`, `let go`, `superseded`), or
    `past` when its `until` is behind `today` (rule 3)."""
    if review is not None:
        verdict = str((review.get("payload") or {}).get("disposition"))
        if verdict in CLOSING:
            return verdict
    until = (goal.get("payload") or {}).get("until")
    if isinstance(until, str) and until < today:
        return "past"
    return "open"


def _order(line: Line) -> tuple[datetime, int]:
    return _instant(str(line["at"])), int(line["seq"])


# -- writing ---------------------------------------------------------------------------------------------


def add(
    lb: Logbook,
    text: str,
    horizon: str,
    start: str | None = None,
    until: str | None = None,
    supersedes: str | None = None,
) -> Line:
    """One `goal/v1` line: `text` as given (stripped), `horizon`, `from` `start` (today by default,
    the record's local day), `until` when given, and `supersedes` naming the earlier goal line it
    rewords (by id or seq; a standing goal, not retracted). `at` is now. `GoalError` says why a goal
    is refused; `HeadMoved` when another writer moved the head under it."""
    words_ = plain(text, "the goal")
    if horizon not in HORIZONS:
        raise GoalError(f"--horizon {horizon!r} is not one of {', '.join(HORIZONS)}")
    with lb.writer():
        meta = lb.meta
        instant = now()
        today = day_start.of(meta).today(instant).isoformat()
        first = day_of(start, "--from") if start is not None else today
        payload: dict[str, Any] = {"schema": SCHEMA, "text": words_, "horizon": horizon, "from": first}
        if until is not None:
            payload["until"] = day_of(until, "--until")
            if payload["until"] < first:
                raise GoalError(f"--until {payload['until']} is before --from {first}")
        if supersedes is not None:
            with lb.index() as idx:
                every, retracted = idx.by_kind(KIND), retractions(idx.retractions())
            earlier = named(every, retracted, supersedes)
            later = Goals(every, retracted).successor.get(str(earlier["id"]))
            if later is not None:
                raise GoalError(
                    f"goal #{earlier['seq']} is superseded by {later} already; reword the standing goal"
                )
            payload["supersedes"] = str(earlier["id"])
        problems = validate(payload)
        if problems:
            raise GoalError(f"the goal would not be a {SCHEMA}: {problems[0]}; nothing was written")
        same_head(lb, meta, "the goals were read")
        written = stamp(instant)
        return lb.append(
            at=written, source=SOURCE, kind=KIND, tier=TIER, payload=payload, recorded_at=written
        )


def review(
    lb: Logbook,
    goal: str,
    word: str,
    period: str | None = None,
    note: str | None = None,
    at: str | None = None,
) -> Reviewed:
    """One `review/v1` line: the verdict `word` on the goal line `goal` names (by id or seq; any line
    of the chain, not retracted), for `period` (the goal's horizon's by default: a year for a life or
    a year goal, a quarter for a quarter goal), with `note` when given, at `at` (`moment`). Nothing is
    written, and `Reviewed.existing` says why, when the goal already has a review for that period on
    that local day (rule 1). `GoalError` says why a review is refused; `HeadMoved` when another
    writer moved the head under it."""
    value = disposition(word)
    if period is not None and period not in PERIODS:
        raise GoalError(f"--period {period!r} is not one of {', '.join(PERIODS)}")
    said = (note or "").strip() or None
    with lb.writer():
        meta = lb.meta
        days, instant = day_start.of(meta), now()
        with lb.index() as idx:
            every, retracted = idx.by_kind(KIND), retractions(idx.retractions())
            reviews = review_lines(idx.by_kind(REVIEW), retracted)
        target = named(every, retracted, goal)
        goals = Goals(every, retracted)
        current = goals.current(str(target["id"])) or target
        horizon = str((current.get("payload") or {}).get("horizon"))
        period = period or PERIOD_OF_HORIZON.get(horizon, "year")
        when = moment(at, days, instant)
        day = days.day_of(when)
        first = _valid_day((target.get("payload") or {}).get("from"))
        if first is not None and day < first.isoformat():
            raise GoalError(
                f"--at {day} is before the goal's first day, {first}; a goal is reviewed once begun"
            )
        chain = goals.chain(str(target["id"]))
        for earlier in reviews:
            payload_before = earlier["payload"]
            same = str(payload_before["goal"]) in chain and payload_before.get("period") == period
            if same and days.day_of(str(earlier["at"])) == day:
                return Reviewed(None, earlier, current)
        payload: dict[str, Any] = {
            "schema": REVIEW_SCHEMA,
            "goal": str(target["id"]),
            "disposition": value,
            "period": period,
        }
        if said is not None:
            payload["note"] = said
        problems = validate_review(payload)
        if problems:
            raise GoalError(f"the review would not be a {REVIEW_SCHEMA}: {problems[0]}; nothing was written")
        same_head(lb, meta, "the goal and its reviews were read")
        line = lb.append(
            at=when, source=SOURCE, kind=REVIEW, tier=TIER, payload=payload, recorded_at=stamp(instant)
        )
        return Reviewed(line, None, current)


def moment(at: str | None, days: DayStart, instant: datetime) -> str:
    """A review's `at`, in UTC: now without `at`; a local day, `YYYY-MM-DD`, is now when it is
    today and else the day's last minute (23:59, or 05:59 the next morning when the day begins at
    06:00), as a note on a day is; an RFC 3339 moment with an offset or Z is itself. Refused when it
    is more than five minutes past `instant` (this clock), and for anything else."""
    if at is None:
        return stamp(instant)
    text = at.strip()
    if _DAY.match(text):
        d = parse_day(day_of(text, "--at"))
        today = days.today(instant)
        if d == today:
            return stamp(instant)
        if d > today:
            raise GoalError(f"--at {text} is in the future; a verdict is on a day that has come")
        return utc((days.span(d)[1] - timedelta(minutes=1)).isoformat())
    if _MOMENT.match(text):
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None:
            if parsed > instant + SKEW:
                raise GoalError(f"--at {text} is in the future; a verdict is on a day that has come")
            return utc(text)
    raise GoalError(
        f"--at {text!r} is neither a local day, YYYY-MM-DD, nor an RFC 3339 moment with an offset or Z,"
        f" e.g. {AT_EXAMPLE}"
    )


def named(lines: Iterable[Line], retracted: Collection[str], entry: str) -> Line:
    """The goal line `entry` names: an id, or a seq (`12` or `#12`). Refused when it names no goal
    line, or a retracted one."""
    text = entry.strip()
    seq = text[1:] if text.startswith("#") else text
    found: Line | None = None
    for line in lines:
        if not is_goal(line):
            continue
        if str(line["id"]) == text or (seq.isdigit() and int(line["seq"]) == int(seq)):
            found = line
            break
    if found is None:
        raise GoalError(f"{text!r} is not a goal line; `logbook goal list` lists them, with their ids")
    if str(found["id"]) in retracted:
        raise GoalError(f"goal #{found['seq']} is retracted")
    return found


def same_head(lb: Logbook, meta: Mapping[str, Any], what: str) -> None:
    """The guard under the lock: `HeadMoved` when `logbook.json` no longer names the head `meta` read."""
    current = lb.meta
    if current["head"] != meta["head"]:
        raise HeadMoved(
            f"the record's head moved from seq {meta['seq']} to seq {current['seq']} while {what}, so what"
            " was checked is not what would be written; nothing was written"
        )


# -- the import ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Entry:
    """One goal of an import file: its line number, text, horizon and first day."""

    number: int
    text: str
    horizon: str
    start: str


@dataclass(frozen=True)
class Imported:
    """What `import_goals` wrote, or would write: the goal drafts and the review drafts, in order."""

    goals: list[dict[str, Any]]
    reviews: list[dict[str, Any]]


def entries(text: str, horizon: str | None, start: str) -> list[Entry]:
    """The goals of an import file: one per line, `text`, optionally `| horizon`, optionally `| from`;
    blank lines and lines starting with `#` are skipped. A line without a horizon takes `horizon`, one
    without a first day takes `start`. `GoalError` names the first line that does not read."""
    found: list[Entry] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) > 3:
            raise GoalError(f"line {number}: more than three columns; a goal is `text | horizon | from`")
        words_ = cells[0]
        if not words_:
            raise GoalError(f"line {number}: no goal before the first `|`")
        given = cells[1] if len(cells) > 1 and cells[1] else horizon
        if given is None:
            raise GoalError(f"line {number}: no horizon; give it as `| year`, or --horizon for every line")
        if given not in HORIZONS:
            raise GoalError(f"line {number}: horizon {given!r} is not one of {', '.join(HORIZONS)}")
        first = start
        if len(cells) > 2 and cells[2]:
            try:
                first = parse_day(cells[2]).isoformat()
            except ValueError:
                raise GoalError(f"line {number}: from {cells[2]!r} is not a local day, YYYY-MM-DD") from None
        found.append(Entry(number, words_, given, first))
    if not found:
        raise GoalError("the file has no goal in it: one goal per line, `text | horizon | from`")
    return found


def import_goals(
    lb: Logbook,
    text: str,
    horizon: str | None = None,
    start: str | None = None,
    word: str | None = None,
    period: str | None = None,
    note: str | None = None,
    at: str | None = None,
    dry_run: bool = False,
) -> Imported:
    """The first backfill: one `goal/v1` line per entry of the file's `text` (`entries`), and, when
    `word` is given, one `review/v1` line per goal with that verdict, `period`, `note` and `at`, as
    `review` would write it. Every line is checked before any is written, and all of them are
    appended in one batch under the writer lock (`Logbook.append_many`, which reads the head again
    before it writes): a refusal writes nothing. `dry_run` checks and writes nothing."""
    value = disposition(word) if word is not None else None
    if value is None and (period is not None or note is not None or at is not None):
        raise GoalError("--period, --note and --at go with --review DISPOSITION")
    if period is not None and period not in PERIODS:
        raise GoalError(f"--period {period!r} is not one of {', '.join(PERIODS)}")
    said = (note or "").strip() or None
    with lb.writer():
        meta = lb.meta
        days, instant = day_start.of(meta), now()
        first = day_of(start, "--from") if start is not None else days.today(instant).isoformat()
        found = entries(text, horizon, first)
        when = moment(at, days, instant) if value is not None else None
        goals_out: list[dict[str, Any]] = []
        reviews_out: list[dict[str, Any]] = []
        for entry in found:
            payload: dict[str, Any] = {
                "schema": SCHEMA,
                "text": entry.text,
                "horizon": entry.horizon,
                "from": entry.start,
            }
            problems = validate(payload)
            if problems:
                raise GoalError(f"line {entry.number}: {problems[0]}; nothing was written")
            draft = _draft(KIND, stamp(instant), payload, instant)
            draft["id"] = store.uuid7()  # minted here, so the goal's review can name it
            goals_out.append(draft)
            if value is None or when is None:
                continue
            day = days.day_of(when)
            if day < entry.start:
                raise GoalError(
                    f"line {entry.number}: --at {day} is before the goal's first day, {entry.start};"
                    " nothing was written"
                )
            verdict: dict[str, Any] = {
                "schema": REVIEW_SCHEMA,
                "goal": draft["id"],
                "disposition": value,
                "period": period or PERIOD_OF_HORIZON[entry.horizon],
            }
            if said is not None:
                verdict["note"] = said
            reviews_out.append(_draft(REVIEW, when, verdict, instant))
        result = Imported(goals_out, reviews_out)
        if dry_run:
            return result
        same_head(lb, meta, "the file was read")
        lb.append_many([*goals_out, *reviews_out])
        return result


def _draft(kind: str, at: str, payload: dict[str, Any], instant: datetime) -> dict[str, Any]:
    return {
        "at": at,
        "source": SOURCE,
        "kind": kind,
        "tier": TIER,
        "payload": payload,
        "recorded_at": stamp(instant),
    }


# -- what the readers show -------------------------------------------------------------------------------


def goal_text(payload: Mapping[str, Any]) -> str:
    """`<text>  (year, from 2026-01-01)`, with `, until 2026-12-31` when bounded: a goal line's row
    on its Day and in `show`."""
    bounds = f"{payload.get('horizon')}, from {payload.get('from')}"
    until = payload.get("until")
    if isinstance(until, str):
        bounds += f", until {until}"
    return f"{payload.get('text')}  ({bounds})"


def review_text(payload: Mapping[str, Any], goal: str | None) -> str:
    """`let go · month · <goal text>`, the goal's current text or, when the reader does not hold it,
    the id it names: a review line's row in `show`."""
    named_goal = goal if goal is not None else f"goal {payload.get('goal')}"
    return DOT.join([str(payload.get("disposition")), str(payload.get("period")), named_goal])


def texts(goals: Goals, reviews: Iterable[Line]) -> dict[str, str]:
    """For each review line, by its `goal`, the current text of the goal it names: what `show` puts
    beside a review."""
    found: dict[str, str] = {}
    for line in reviews:
        goal_id = str((line.get("payload") or {}).get("goal"))
        current = goals.current(goal_id)
        if current is not None:
            found[goal_id] = str((current.get("payload") or {}).get("text"))
    return found


def goal_row(line: Line, goals: Goals) -> dict[str, Any]:
    """A goal line on the Day of its `at`: its id, text, horizon, bounds, and the standing goal that
    replaced it when a later goal names it (`superseded`)."""
    payload = line.get("payload") or {}
    later = goals.successor.get(str(line["id"]))
    return {
        "line": str(line["id"]),
        "text": payload.get("text"),
        "horizon": payload.get("horizon"),
        "from": payload.get("from"),
        "until": payload.get("until"),
        "superseded": later,
    }


def reviews_on(
    day: str, on_day: Iterable[Line], every_goal: Iterable[Line], retracted: Collection[str], tz: str
) -> list[dict[str, Any]]:
    """The Day's `reviews`: a row per review standing on `day` (of the reviews in `on_day`, the
    latest by `at`, then `seq`, of each goal, retracted ones left out), in the day's order, with the
    goal's current text (the standing goal of its chain), the disposition, the period, the note, and
    `recorded_at`, which the text shows when it is a later day than `at` in `tz`."""
    goals = Goals(every_goal, retracted)
    latest: dict[str, Line] = {}
    for line in review_lines(on_day, retracted):
        goal_id = str(line["payload"]["goal"])
        current = goals.current(goal_id)
        key = str(current["id"]) if current is not None else goal_id
        latest[key] = line  # review_lines is in the day's order: the last one stands
    rows = []
    for key, line in sorted(latest.items(), key=lambda item: _order(item[1])):
        payload = line["payload"]
        current = goals.by_id.get(key)
        rows.append(
            {
                "line": str(line["id"]),
                "goal": str(payload["goal"]),
                "goal_text": None if current is None else (current.get("payload") or {}).get("text"),
                "disposition": payload.get("disposition"),
                "period": payload.get("period"),
                "note": payload.get("note"),
                "recorded_at": line.get("recorded_at"),
            }
        )
    return rows


def review_row_text(row: Mapping[str, Any], at_day: str, tz: str) -> str:
    """A review's row on its Day: `let go · month · <goal text> · <note>`, then `written 2026-10-11
    20:30` (the local clock of `recorded_at`) when it was written on a later day than `at_day`."""
    goal = row.get("goal_text")
    parts = [
        str(row.get("disposition")),
        str(row.get("period")),
        str(goal) if goal is not None else f"goal {row.get('goal')}",
    ]
    if row.get("note"):
        parts.append(str(row["note"]))
    written = row.get("recorded_at")
    if isinstance(written, str):
        local = _instant(written).astimezone(ZoneInfo(tz))
        if local.date().isoformat() > at_day:
            parts.append(f"written {local:%Y-%m-%d %H:%M}")
    return DOT.join(parts)


def listing(lb: Logbook, open_only: bool = False) -> dict[str, Any]:
    """`goal list`: the standing goals in the order written (only the open ones with `open_only`),
    each with its latest review and its state (`open`, `done`, `let go`, `superseded`, `past`); how
    many goals stand and how many are open. Read through the index; nothing is written."""
    meta = lb.meta
    days = day_start.of(meta)
    today = days.today(now()).isoformat()
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        goals = Goals(idx.by_kind(KIND), retracted)
        reviews = review_lines(idx.by_kind(REVIEW), retracted)
    out = []
    for line in goals.standing():
        payload = line.get("payload") or {}
        latest = standing_review(reviews, goals.chain(str(line["id"])))
        out.append(
            {
                "line": str(line["id"]),
                "seq": int(line["seq"]),
                "text": payload.get("text"),
                "horizon": payload.get("horizon"),
                "from": payload.get("from"),
                "until": payload.get("until"),
                "supersedes": payload.get("supersedes"),
                "state": state(line, latest, today),
                "review": None if latest is None else _review_json(latest, days),
            }
        )
    open_count = sum(1 for goal in out if goal["state"] == "open")
    listed = [goal for goal in out if goal["state"] == "open"] if open_only else out
    return {"today": today, "standing": len(out), "open": open_count, "goals": listed}


def _review_json(line: Line, days: DayStart) -> dict[str, Any]:
    payload = line.get("payload") or {}
    return {
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "day": days.day_of(str(line["at"])),
        "at": line.get("at"),
        "recorded_at": line.get("recorded_at"),
        "disposition": payload.get("disposition"),
        "period": payload.get("period"),
        "note": payload.get("note"),
    }


def listing_rows(found: Mapping[str, Any]) -> list[str]:
    """`goal list` as text: a head line, then per goal its seq, horizon, bounds and text, and under it
    the latest review (or `unreviewed`)."""
    n = int(found["standing"])
    if not n:
        return ["no goals yet; `logbook goal add TEXT --horizon year` writes one"]
    out = [f"{n} goal{'s' if n != 1 else ''}{DOT}{found['open']} open"]
    for goal in found["goals"]:
        bounds = f"from {goal['from']}" + (f" until {goal['until']}" if goal.get("until") else "")
        out.append(f"  #{goal['seq']:<5} {goal['horizon']!s:<8} {bounds:<34} {goal['text']}")
        review_ = goal["review"]
        if review_ is None:
            verdict = "unreviewed"
        else:
            verdict = DOT.join(
                [f"{review_['disposition']} {review_['day']}", str(review_["period"])]
                + ([str(review_["note"])] if review_.get("note") else [])
            )
        past = f"{DOT}past its until" if goal["state"] == "past" else ""
        out.append(f"         {verdict}{past}")
    return out


def _instant(stamp_: str) -> datetime:
    parsed = datetime.fromisoformat(stamp_.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
