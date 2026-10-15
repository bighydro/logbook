"""A source's first scheduled run reads two weeks, not its whole history (docs/schedule.md).

The schedule runs `logbook sync --scheduled`, and that flag, passed by the installed agents or timers and
by nothing else, is how a run knows it is scheduled: never the environment. `sync --scheduled` takes the
window once, from its own clock (`window`): the last `DAYS` local days of the record, today included, in
its zone and from its `day_start`. A live source that has never been synced, no watermark and no state of
its own (`is_first`), then starts there and not from the beginning, however long its history (`start`):
backfilling a source is a deliberate act, a `--since` typed by the owner, never a timer's. A run by hand,
`sync <source>` or `sync --all`, starts where it always did, and `--since` always wins.

The bound leaves a mark in the source's state file, `state/<name>.json`, bookkeeping beside its watermark,
never in the chain (`KEY`):

    "first_run": {"from": "2026-09-24T22:00:00Z", "day": "2026-09-25", "complete": true}

It is written before the pull, so a run that fails or is interrupted leaves it: the next scheduled run
starts from the same instant again and never from a window that slid on, so nothing after it is skipped,
and a walk checkpointed for that `since` (`immich`) resumes. A run that left no watermark (nothing in the
window) keeps starting there until one does. `complete` says a run from the mark finished; a source whose
lasting state is its own (`RESUMES`: `mail`, `gmail`) then carries on from that state, as by hand. The
mark goes when a run that completes reads back past it (`reads_back`): `--since` before `from`,
`--restart`, or a run by hand from the beginning. Until then `doctor` names the source (`text`).

A source with no history to read (`HISTORY = False`: a stream, the present, what a server keeps for a
day) is never bounded, and `weather` has its own window (yesterday alone on a first run)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ..core import day_start

DAYS = 14  # a first scheduled run reads this many local days, today included
KEY = "first_run"  # the mark in `state/<name>.json`
RESUME = "resume"  # where a source that keeps its own lasting state (`RESUMES`) keeps it
OWN_STATE = (RESUME, "walk")  # a source's own lasting state, or a walk under way: it has been synced


@dataclass(frozen=True)
class Window:
    """Where a first scheduled run starts: the local day `DAYS - 1` before today, and the instant that
    day begins, in UTC."""

    day: str
    since: str


@dataclass(frozen=True)
class Start:
    """Where a scheduled run of one source starts. `bounded` is the window when this run is the
    source's first (the mark to write, the line to say); `from_mark` when it starts from the mark an
    earlier first run left."""

    since: str | None
    resumed_from_record: str | None
    bounded: Window | None = None
    from_mark: bool = False


def window(meta: Mapping[str, Any], now: datetime) -> Window:
    """The window of a scheduled run that began at `now`, on the record's clock (`logbook.json`'s zone
    and `day_start`, read leniently: a sync never refuses for a setting only readers need)."""
    days = day_start.DayStart(ZoneInfo(str(meta["timezone"])), day_start.lenient(meta.get(day_start.KEY)))
    first = days.today(now) - timedelta(days=DAYS - 1)
    begins = days.span(first)[0].astimezone(UTC)
    return Window(first.isoformat(), begins.strftime("%Y-%m-%dT%H:%M:%SZ"))


def mark(state: Mapping[str, Any]) -> dict[str, Any] | None:
    """The mark a bounded first run left in a source's state, or None (none, or not the shape)."""
    found = state.get(KEY)
    if isinstance(found, dict) and isinstance(found.get("from"), str) and isinstance(found.get("day"), str):
        return found
    return None


def is_first(state: Mapping[str, Any]) -> bool:
    """Whether a source has never been synced: no watermark, no state of its own, no walk under way and
    no mark of a first run."""
    if state.get("since") is not None or mark(state) is not None:
        return False
    return not any(state.get(key) for key in OWN_STATE)


def start(
    state: Mapping[str, Any],
    since: str | None,
    resumed_from_record: str | None,
    given: Window,
    resumes: bool,
) -> Start:
    """Where a scheduled run starts, given where a run by hand would (`since`, and the record's newest
    line when that is what it came from). A watermark: as by hand. The mark of an earlier first run
    and no watermark yet: from the mark again, unless the source keeps its own state (`resumes`), a
    run from the mark completed and the state is there (a run that left none starts from the mark
    again, never from the beginning). A first run: from the window, unless the run by hand would start
    inside it already, or from the record's newest line (an export's) when that line is inside it: the
    source's lookback before that line is kept, so what reached the source late is not lost."""
    if state.get("since") is not None:
        return Start(since, resumed_from_record)
    found = mark(state)
    if found is not None:
        if resumes and found.get("complete") and state.get(RESUME):
            return Start(since, resumed_from_record)
        return Start(str(found["from"]), None, from_mark=True)
    if not is_first(state):
        return Start(since, resumed_from_record)
    inside = since is not None and not before(since, given.since)
    if inside or (resumed_from_record is not None and not before(resumed_from_record, given.since)):
        return Start(since, resumed_from_record)  # the record's newest line is in it: on from there
    return Start(given.since, None, bounded=given)


def reads_back(
    found: Mapping[str, Any],
    given: str | None,
    restart: bool,
    since: str | None,
    stored: str | None,
    own_state: bool,
) -> bool:
    """Whether a run by hand that completed read the history the mark `found` says is unread: `--since`
    (`given`) before the mark's `from`; `--restart`; or, with no watermark, a start from the beginning
    or from before the mark (`since`), unless the source carried on from its own state (`own_state`).
    A start at `from` itself reads nothing the bound left out, and a start from the watermark is never
    one, whatever its lookback."""
    if restart:
        return True
    if given is not None:
        return before(given, str(found["from"]))
    if stored is not None or own_state:
        return False
    return since is None or before(since, str(found["from"]))


def text(found: Mapping[str, Any], name: str) -> str:
    """What `doctor` says of a source whose first scheduled run was bounded and whose history no run
    has read since."""
    return (
        f"first run bounded to {DAYS} days; history not read (before {found['day']}:"
        f" `logbook sync {name} --since <date>`)"
    )


def read(root: Path, name: str) -> dict[str, Any] | None:
    """The mark in `state/<name>.json`, for `doctor`: None when there is none, or the file is not
    there or not JSON (the sync that reads it says so; doctor never raises over bookkeeping)."""
    try:
        state = json.loads((root / "state" / f"{name}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return mark(state) if isinstance(state, dict) else None


def before(a: str, b: str) -> bool:
    """Whether instant `a` is before instant `b`, both RFC 3339 (a naive one read as UTC); False when
    either is not an instant, so a start in a source's own clock that is not one is left as it is."""
    first, second = _instant(a), _instant(b)
    return first is not None and second is not None and first < second


def _instant(text: str) -> datetime | None:
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo is not None else when.replace(tzinfo=UTC)
