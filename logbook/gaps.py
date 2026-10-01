"""Where each source went quiet: `logbook sources --gaps [--since DAY] [--expect SOURCE...]`.

Per source, from the index alone (`Index.activity`: SQL over its columns, nothing read from the
files, however long the log): the lines in the range, the first and last line's time, the longest
silent stretch, and the local days of the range with no line from it, so a phone that stopped
sending or a sync that died is seen on one screen.

The range is [`since`, today] in the record's timezone; without `since` it starts, per source, on
the day of the source's first line, since a source is not silent before it began. A line dated
after today (a calendar's future entries) is outside the range. The silent stretches are the gaps
between consecutive lines, the stretch from the range's start to the first line when `since` names
it, and the open stretch from the last line to now; the longest is reported with its ends, `to`
None when it is still running. Every line counts, retracted or not: a retracted line still shows
the source was alive when it wrote.

With `expect`, only those sources are reported, one with no line in the range among them, and a
source is flagged when its longest silence is a day or more, or it has no line at all. Nothing is
written."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .export import parse_day

if TYPE_CHECKING:
    from .store import Logbook

FLAG_SECONDS = 86400  # an expected source silent this long, at any point of the range, is flagged
RUNS_SHOWN = 3  # runs of missing days printed per row before `+N runs`


def now() -> datetime:
    """The clock, as one function so a test can pin it."""
    return datetime.now(UTC)


def report(lb: Logbook, since: str | None = None, expect: Sequence[str] | None = None) -> dict[str, Any]:
    """The JSON-ready report: `since`, `today`, `timezone`, `expect` (the names asked for, or
    None), `sources` (most lines first, or in `expect` order), `flagged` (the expected sources
    flagged, in that order; empty without `expect`). Raises ValueError for a `since` that is not a
    day or is after today."""
    tz = ZoneInfo(str(lb.meta["timezone"]))
    instant = now()
    today = instant.astimezone(tz).date()
    start: date | None = None
    if since is not None:
        start = parse_day(since)
        if start > today:
            raise ValueError(f"--since {since} is after today ({today.isoformat()})")
    with lb.index() as idx:
        found = idx.activity("" if start is None else start.isoformat(), today.isoformat())
    by_source = {a["source"]: a for a in found}
    names = list(by_source) if expect is None else list(dict.fromkeys(expect))
    sources = [_source(name, by_source.get(name), start, today, instant, tz) for name in names]
    return {
        "since": None if start is None else start.isoformat(),
        "today": today.isoformat(),
        "timezone": str(lb.meta["timezone"]),
        "expect": None if expect is None else names,
        "sources": sources,
        "flagged": [] if expect is None else [s["source"] for s in sources if s["flagged"]],
    }


def _source(
    name: str,
    activity: dict[str, Any] | None,
    start: date | None,
    today: date,
    instant: datetime,
    tz: ZoneInfo,
) -> dict[str, Any]:
    if activity is None:
        return {
            "source": name,
            "lines": 0,
            "first": None,
            "last": None,
            "silence": None,
            "missing_days": [],
            "flagged": True,
        }
    first, last = _instant(activity["first"]), _instant(activity["last"])
    candidates: list[tuple[float, str, str | None]] = []
    if activity["stretch"] is not None:
        a, b = activity["stretch"]
        candidates.append(((_instant(b) - _instant(a)).total_seconds(), a, b))
    if start is not None:
        opening = datetime.combine(start, datetime.min.time(), tzinfo=tz)
        candidates.append(((first - opening).total_seconds(), _stamp(opening), activity["first"]))
    quiet = max(0.0, (instant - last).total_seconds())  # the open stretch, still running
    candidates.append((quiet, activity["last"], None))
    seconds, gap_from, gap_to = max(candidates, key=lambda c: c[0])
    range_start = start or first.astimezone(tz).date()
    present = set(activity["days"])
    missing = [
        day.isoformat()
        for day in _days(range_start, today)
        if day.isoformat() not in present and (day != today or quiet >= FLAG_SECONDS)
    ]
    return {
        "source": name,
        "lines": activity["lines"],
        "first": activity["first"],
        "last": activity["last"],
        "silence": {"from": gap_from, "to": gap_to, "seconds": seconds},
        "missing_days": missing,
        "flagged": seconds >= FLAG_SECONDS,
    }


def _days(first: date, last: date) -> Iterator[date]:
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# -- text ------------------------------------------------------------------------------------------


def duration(seconds: float) -> str:
    """`9d 17h`, `12h 30m` or `4m`; whole units, rounded down."""
    whole = int(seconds)
    if whole >= 86400:
        return f"{whole // 86400}d {whole % 86400 // 3600}h"
    if whole >= 3600:
        return f"{whole // 3600}h {whole % 3600 // 60}m"
    return f"{whole // 60}m"


def runs(days: Sequence[str], limit: int = RUNS_SHOWN) -> str:
    """Consecutive days folded: `2026-09-02..2026-09-03, 2026-09-06`, the first `limit` runs and
    `+N run(s)` for the rest."""
    folded: list[tuple[date, date]] = []
    for text in days:
        day = date.fromisoformat(text)
        if folded and folded[-1][1] + timedelta(days=1) == day:
            folded[-1] = (folded[-1][0], day)
        else:
            folded.append((day, day))
    shown = [a.isoformat() if a == b else f"{a.isoformat()}..{b.isoformat()}" for a, b in folded[:limit]]
    rest = len(folded) - len(shown)
    if rest:
        shown.append(f"+{rest} run" if rest == 1 else f"+{rest} runs")
    return ", ".join(shown)


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The report as one screen: a row per source (`!` first when flagged under `expect`), then
    the summary."""
    tz = ZoneInfo(data["timezone"])
    sources = data["sources"]
    expected = data["expect"] is not None
    if not sources:
        yield "no lines"
    else:
        name = max(10, *(len(s["source"]) for s in sources))
        width = max(5, *(len(f"{s['lines']:,}") for s in sources))
        silences = {s["source"]: _silence_text(s["silence"], tz) for s in sources if s["lines"]}
        quiet = max(15, *(len(text) for text in silences.values())) if silences else 15
        head = f"  {'source':<{name}}  {'lines':>{width}}  {'last':<16}  {'longest silence':<{quiet}}"
        yield f"{head}  missing days"
        for s in sources:
            mark = "! " if expected and s["flagged"] else "  "
            if s["lines"] == 0:
                yield f"{mark}{s['source']:<{name}}  {0:>{width}}  {'-':<16}  no lines"
                continue
            missing = s["missing_days"]
            tail = f"{len(missing):>3}  {runs(missing)}" if missing else f"{0:>3}"
            yield (
                f"{mark}{s['source']:<{name}}  {s['lines']:>{width},}  {_clock(s['last'], tz)}"
                f"  {silences[s['source']]:<{quiet}}  {tail}"
            )
    yield ""
    span = f"since {data['since']}" if data["since"] else "since each source's first line"
    if expected:
        n, flagged = len(sources), data["flagged"]
        noun = "expected source" if n == 1 else "expected sources"
        if flagged:
            yield f"{len(flagged)} of {n} {noun} flagged: {', '.join(flagged)}"
        else:
            yield f"{n} {noun}, none flagged"
    else:
        n = len(sources)
        yield f"{n} {'source' if n == 1 else 'sources'} with lines"
    yield f"{span}, today {data['today']} ({data['timezone']}); counted through the index, every line"


def _silence_text(silence: dict[str, Any], tz: ZoneInfo) -> str:
    """`9d 17h   since 2026-09-20 21:00` for a silence still running, else its two ends."""
    length = f"{duration(silence['seconds']):<7}"
    if silence["to"] is None:
        return f"{length} since {_clock(silence['from'], tz)}"
    return f"{length} {_clock(silence['from'], tz)} → {_clock(silence['to'], tz)}"


def _clock(stamp: str, tz: ZoneInfo) -> str:
    return _instant(stamp).astimezone(tz).strftime("%Y-%m-%d %H:%M")
