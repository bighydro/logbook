"""Google Calendar → event/v1 (RFC 0009), live: pulls the private iCal feeds of your own calendars.

Google gives every calendar a "secret address in iCal format" (Settings → the calendar → Integrate
calendar): a URL that is the whole calendar as one iCalendar text, readable by anyone who holds it.
`LOGBOOK_GCAL_URLS` lists them, comma-separated, each optionally `name=url` so a feed with no
X-WR-CALNAME of its own is named. Fetched with stdlib urllib, no dependency, no network anywhere but
inside `pull`, which only `logbook sync gcal` calls (ADR 0012).

Every feed goes through `ics.lines`, the file adapter's own reader: an event imported from a calendar
export (`logbook add basic.ics`, Takeout's `Calendar/`) and the same event pulled here are the same
line with the same `raw_id` (`<UID>@<LAST-MODIFIED>`, RFC 0009 rule 5) and the same `source`, `ics`,
so `append_many` dedupes it (ADR 0017: backfill and live share one mapping). Recurring masters,
materialised occurrences, all-day and floating times (read in the record's zone, which `sync` passes
as `timezone`) are the ics adapter's, unchanged. The feed's own X-WR-CALNAME names the calendar as it
does for a file; the given name applies only when the feed has none, where a saved copy would have
used its file name (`basic.ics`, the URL's last part, when no name was given either).

The watermark is the newest LAST-MODIFIED (else DTSTAMP) seen. A feed is the whole calendar every
time, so each pull keeps only the events changed since a lookback (24 h, `LOGBOOK_GCAL_LOOKBACK_H`)
before the watermark, and the `raw_id` dedupe absorbs the overlap; `sync` says how many it saw and
how many were new, per calendar. With no watermark yet the whole feed is read (the record's newest
event is a start time, not a change time, so it cannot stand in). An explicit `--since` is used as
given. An event with neither stamp is always considered; dedupe still keeps it single.

The URLs are secrets: the config's repr hides them, `sync` prints only a calendar's label (its given
name, else eight hex characters of the URL's SHA-256) and an error is composed from the HTTP status or
the reason alone, with the URL scrubbed should a library put it there. A calendar that fails (an HTTP
error, an unreachable host, a body that is not a calendar) is one line in `failed` and the others are
still read; without a `failed` list the pull raises OSError with those lines after the others' events.
"""

from __future__ import annotations

import hashlib
import math
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from . import ics
from .ics import KIND

__all__ = ["ENV", "KIND", "NAME", "Calendar", "Config", "configure", "group", "pull", "resume", "watermark"]

NAME = "gcal"
URLS_ENV = "LOGBOOK_GCAL_URLS"
LOOKBACK_ENV = "LOGBOOK_GCAL_LOOKBACK_H"
ENV = (URLS_ENV,)
LOOKBACK_H = 24.0
UNIT = "events"  # what `sync` counts in its progress lines
TIMEOUT_S = 60
SCHEMES = ("http", "https")
LABEL_CHARS = 8
USER_AGENT = "logbook"
NOT_A_FEED = "not an iCalendar feed"


@dataclass(frozen=True)
class Calendar:
    """One feed: what `sync` may print (`label`), the URL it never prints, the name it was given."""

    label: str
    url: str = field(repr=False)
    name: str | None = None

    @property
    def fallback_name(self) -> str:
        """The calendar id when the feed carries no X-WR-CALNAME: the given name, else the URL's last
        path part, which is what a saved copy of the feed would be called."""
        if self.name:
            return self.name
        return urlsplit(self.url).path.rsplit("/", 1)[-1] or self.label


@dataclass(frozen=True)
class Config:
    calendars: tuple[Calendar, ...]
    lookback_h: float = LOOKBACK_H


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from LOGBOOK_GCAL_URLS; None when it is absent or names no URL. Raises ValueError, never
    echoing a URL, when an entry is not an http(s) URL or LOGBOOK_GCAL_LOOKBACK_H is set but not a
    number of hours ≥ 0."""
    calendars: list[Calendar] = []
    for position, item in enumerate(env.get(URLS_ENV, "").split(","), start=1):
        item = item.strip()
        if not item:
            continue
        name, url = _pair(item)
        parts = urlsplit(url)
        if parts.scheme.lower() not in SCHEMES or not parts.netloc:
            raise ValueError(f"{URLS_ENV}: entry {position} is not an http(s) URL")
        calendars.append(Calendar(label=name or _label(url), url=url, name=name))
    if not calendars:
        return None
    raw = env.get(LOOKBACK_ENV, "").strip()
    lookback = LOOKBACK_H
    if raw:
        try:
            lookback = float(raw)
        except ValueError:
            lookback = -1.0
        if not math.isfinite(lookback) or lookback < 0:
            raise ValueError(f"{LOOKBACK_ENV} must be a number of hours, 0 or more, not {raw!r}")
    return Config(calendars=tuple(calendars), lookback_h=lookback)


def _pair(item: str) -> tuple[str | None, str]:
    """`name=url` when there is an `=` before anything that could only be part of a URL (`:` or `/`);
    else the item is the URL."""
    name, sep, url = item.partition("=")
    if sep and name and ":" not in name and "/" not in name:
        return name.strip(), url.strip()
    return None, item


def _label(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:LABEL_CHARS]


def resume(config: Config, mark: str) -> str:
    """Where a pull starts, given the watermark: the lookback before it."""
    start = datetime.fromisoformat(mark).astimezone(UTC) - timedelta(hours=config.lookback_h)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def watermark(draft: dict[str, Any]) -> str | None:
    """The event's LAST-MODIFIED (else DTSTAMP): the calendar's own clock for it."""
    modified = draft["payload"].get("modified_at")
    return str(modified) if modified else None


def group(draft: dict[str, Any]) -> str:
    """The calendar the event belongs to, as `sync` reports seen and new per calendar."""
    calendar = draft["payload"]["calendar"]
    return str(calendar.get("name") or calendar["id"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    failed: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every event of every calendar changed since `since` (RFC3339; None means all), calendar by
    calendar in the order configured and feed order within one, one event/v1 line draft each. Every
    feed is fetched before the first line is yielded. Skips are tallied in `counts` as the ics adapter
    tallies them; `progress(events_so_far, elapsed_seconds)` is called after each calendar. A
    calendar that cannot be read is one line in `failed` (the label and the reason, never the URL);
    with no list given, OSError carries those lines once every other calendar's events are out."""
    counts = counts if counts is not None else {}
    cutoff = _cutoff(since)
    started = time.monotonic()
    problems: list[str] = []
    texts: list[tuple[Calendar, str]] = []
    for calendar in config.calendars:
        try:
            texts.append((calendar, _fetch(calendar)))
        except OSError as e:
            problems.append(f"{calendar.label}: {_scrub(str(e), calendar)}")
    count = 0
    for calendar, text in texts:
        for draft in ics.lines(text, calendar.fallback_name, counts, timezone):
            modified = draft["payload"].get("modified_at")
            if cutoff is not None and modified and str(modified) < cutoff:
                continue
            if calendar.name and "name" not in draft["payload"]["calendar"]:  # a feed with no name of its own
                draft["payload"]["calendar"]["name"] = calendar.name
            count += 1
            yield draft
        if progress is not None:
            progress(count, time.monotonic() - started)
    if problems:
        if failed is None:
            raise OSError("; ".join(problems))
        failed.extend(problems)


def _cutoff(since: str | None) -> str | None:
    """`since` as the RFC3339 UTC text a `modified_at` compares with, whatever offset it was given in."""
    if not since:
        return None
    return datetime.fromisoformat(since).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch(calendar: Calendar) -> str:
    """The feed's text. The only network call in this module. Raises OSError, its message free of the
    URL, for an HTTP error, an unreachable server or a body that is not a calendar."""
    req = Request(calendar.url, headers={"User-Agent": USER_AGENT, "Accept": "text/calendar"}, method="GET")
    try:
        with urlopen(req, timeout=TIMEOUT_S) as response:
            body = response.read()
    except HTTPError as e:
        raise OSError(f"HTTP {e.code} {e.reason}") from None
    except URLError as e:
        raise OSError(str(e.reason)) from None
    if not ics.sniff_bytes(body):
        raise OSError(NOT_A_FEED)
    text: str = body.decode("utf-8-sig", errors="replace")
    return text


def _scrub(message: str, calendar: Calendar) -> str:
    """The message with the URL, and its secret path on its own, replaced: belt and braces for a
    library error that quotes what it was asked to open."""
    for secret in (calendar.url, urlsplit(calendar.url).path):
        if secret and secret != "/":
            message = message.replace(secret, "<url>")
    return message
