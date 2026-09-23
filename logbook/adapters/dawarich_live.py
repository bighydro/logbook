"""Dawarich → location/v1 (RFC 0001), live: pulls new points from your own Dawarich server.

`GET /api/v1/points?start_at=&end_at=&page=&per_page=` with `Authorization: Bearer <key>`, paged
until an empty page. `end_at` is fixed to the moment the pull starts, so points that arrive while it
pages do not shift the pages under it; they come with the next sync. Stdlib urllib, no dependency.

Every row goes through `dawarich.draft`, the file adapter's own mapping: a point already imported
from an export and the same point pulled here are the same line with the same `raw_id`
(`<tracker_id>:<timestamp>`), so `append_many` dedupes it. The API row carries more than that
mapping reads (`id`, `city`, `country`, `battery_status`, ...); what it does not read is ignored,
exactly as for an export. A row without usable coordinates, timestamp or tracker is skipped and
counted.

The watermark is the newest point time seen. A phone uploads in batches, so a point can reach the
server after newer ones: `resume` starts each pull a lookback (24 h, `LOGBOOK_DAWARICH_LOOKBACK_H`)
before the watermark and dedupe absorbs the overlap. With no watermark yet, `sync` resumes from the
record's newest dawarich location line, so a record seeded from an export carries on where the
export ended. An explicit `--since` is used as given.

The key is full-access on Dawarich: it is sent only in the Authorization header, never in a URL,
never in the config's repr, never printed. Network happens only inside `pull`, which only
`logbook sync dawarich` calls (ADR 0012).
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .dawarich import KIND, NAME, draft

__all__ = ["ENV", "KIND", "NAME", "Config", "configure", "draft", "pull", "resume", "watermark"]

ENV = ("LOGBOOK_DAWARICH_URL", "LOGBOOK_DAWARICH_KEY")
LOOKBACK_ENV = "LOGBOOK_DAWARICH_LOOKBACK_H"
LOOKBACK_H = 24.0
UNIT = "points"  # what `sync` counts in its progress lines
PAGE_SIZE = 1000
TIMEOUT_S = 60
EPOCH = "1970-01-01T00:00:00Z"
# Beyond datetime's range on every platform (Windows refuses negative and far-future stamps).
MAX_UNIX = 32_503_680_000  # 3000-01-01

BAD_COORDINATES = "skipped_bad_coordinates"
NO_TIMESTAMP = "skipped_no_timestamp"
NO_TRACKER = "skipped_no_tracker"


@dataclass(frozen=True)
class Config:
    url: str
    key: str = field(repr=False)
    lookback_h: float = LOOKBACK_H


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from LOGBOOK_DAWARICH_URL and LOGBOOK_DAWARICH_KEY; None when either is absent or
    empty. Raises ValueError when LOGBOOK_DAWARICH_LOOKBACK_H is set but not a number of hours ≥ 0."""
    url, key = (env.get(name, "").strip() for name in ENV)
    if not url or not key:
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
    return Config(url=url.rstrip("/"), key=key, lookback_h=lookback)


def resume(config: Config, mark: str) -> str:
    """Where a pull starts, given the watermark (or the record's newest point): the lookback before it."""
    start = datetime.fromisoformat(mark).astimezone(UTC) - timedelta(hours=config.lookback_h)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def watermark(draft: dict[str, Any]) -> str | None:
    """The point's own time: Dawarich is queried by it."""
    return str(draft["at"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every point Dawarich holds from `since` (RFC3339 UTC; None means all) to now, oldest first as
    the server orders them, one location/v1 line draft each. Skips are tallied in `counts`.
    `progress(points_so_far, elapsed_seconds)` is called after every page."""
    counts = _counts(counts if counts is not None else {})
    window = {"start_at": since or EPOCH, "end_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
    page, count, started = 1, 0, time.monotonic()
    previous: set[object] = set()
    while True:
        rows = _get(config, {**window, "page": page, "per_page": PAGE_SIZE})
        keys = {_row_key(row) for row in rows}
        if not rows or keys <= previous:  # an empty page, or a server that ignores `page`
            return
        for row in rows:
            line = _line(row, counts)
            if line is not None:
                yield line
        count += len(rows)
        if progress is not None:
            progress(count, time.monotonic() - started)
        previous, page = keys, page + 1


def _get(config: Config, params: dict[str, Any]) -> list[Any]:
    """One GET /api/v1/points. The only network call in this module."""
    req = Request(
        f"{config.url.rstrip('/')}/api/v1/points?{urlencode(params)}",
        headers={"Authorization": f"Bearer {config.key}", "Accept": "application/json"},
        method="GET",
    )
    with urlopen(req, timeout=TIMEOUT_S) as response:
        return _decode(response.read())


def _decode(body: bytes) -> list[Any]:
    """A page of points: a JSON array. NaN and Infinity (which Python's json would accept) read as
    null. Anything else is an error: a login page, an error object."""
    try:
        doc = json.loads(body.decode("utf-8"), parse_constant=lambda _name: None)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"expected a JSON array of points, got something that is not JSON ({e})") from None
    if not isinstance(doc, list):
        raise ValueError(f"expected a JSON array of points, got a JSON {type(doc).__name__}")
    return doc


def _row_key(row: object) -> object:
    if isinstance(row, dict):
        return row.get("id", json.dumps(row, sort_keys=True, default=str))
    return json.dumps(row, default=str)


def _counts(counts: dict[str, int]) -> dict[str, int]:
    for key in (NO_TIMESTAMP, BAD_COORDINATES, NO_TRACKER):
        counts.setdefault(key, 0)
    return counts


def _line(row: Any, counts: dict[str, int]) -> dict[str, Any] | None:
    """The line draft for one API row, or None (counted) when it lacks what a line needs."""
    if not isinstance(row, dict):
        counts[BAD_COORDINATES] = counts.get(BAD_COORDINATES, 0) + 1
        return None
    stamp = row.get("timestamp")
    if isinstance(stamp, bool) or not isinstance(stamp, int | float) or not 0 <= stamp < MAX_UNIX:
        counts[NO_TIMESTAMP] = counts.get(NO_TIMESTAMP, 0) + 1
        return None
    lat, lon = _degrees(row.get("latitude"), 90), _degrees(row.get("longitude"), 180)
    if lat is None or lon is None:
        counts[BAD_COORDINATES] = counts.get(BAD_COORDINATES, 0) + 1
        return None
    tracker = row.get("tracker_id")
    if not isinstance(tracker, str) or not tracker:
        counts[NO_TRACKER] = counts.get(NO_TRACKER, 0) + 1
        return None
    return draft(row, lat, lon)


def _degrees(value: object, limit: int) -> float | None:
    """A coordinate as a number within ±limit. A number is kept as sent (so the line is the one an
    export gives); a numeric string is read."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        number: float = value
    elif isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) and -limit <= number <= limit else None
