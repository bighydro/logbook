"""Shazam's library export → listen/v1 (RFC 0019).

The Shazam app (Settings → Export library) writes `shazamlibrary.csv`: a title line `Shazam
Library`, then `Index,TagTime,Title,Artist,URL,TrackKey`, one row per song identified. `TagTime`
is a wall-clock time with no zone (`2026-03-04 21:15:30`, or with a `T`); the export is read in
the record's zone (rule 4), and a time that does carry `Z` or an offset is read as given.

One line per row: kind `listen`, tier 2, source `shazam`, `media` `track`, `title`, `artist`,
`url`, `service` `shazam`, `extra.track_key`; `raw_id` `shazam:<TrackKey>:<TagTime as spelled>`,
so the same song identified twice is two listens and a re-import of the export appends nothing.
A row with no time or no title is skipped and counted. Pure: no network, never writes the source.
"""

from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NAME = "shazam"
KIND = "listen"
TIER = 2
SCHEMA = "listen/v1"
SERVICE = "shazam"

SUFFIX = ".csv"
TITLE_LINE = "shazam library"
REQUIRED = ("tagtime", "title", "artist")
SNIFF_BYTES = 1024


def sniff(path: Path) -> bool:
    """A `.csv` that starts with Shazam's title line or its header. Never raises."""
    path = Path(path)
    try:
        if not path.is_file() or path.suffix.lower() != SUFFIX:
            return False
        with path.open("rb") as fh:
            head = fh.read(SNIFF_BYTES).decode("utf-8-sig", errors="replace").lower()
    except OSError:
        return False
    first = head.split("\n", 2)[:2]
    return any(line.strip() == TITLE_LINE or all(c in line for c in REQUIRED) for line in first)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One listen/v1 line draft per row of the export at `path`, oldest first. `since` is RFC3339
    UTC; `timezone` is the record's zone, which also reads the zoneless tag times."""
    counts = counts if counts is not None else {}
    tz = timezone or "UTC"
    zone = ZoneInfo(tz)
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    header = next(
        (i for i, row in enumerate(rows) if all(c in [x.strip().lower() for x in row] for c in REQUIRED)),
        None,
    )
    if header is None:
        return
    columns = {name.strip().lower(): i for i, name in enumerate(rows[header])}
    drafts: list[dict[str, Any]] = []
    for row in rows[header + 1 :]:
        cell = {name: (row[i].strip() if i < len(row) else "") for name, i in columns.items()}
        title = " ".join(cell["title"].split())
        if not title:
            _count(counts, "skipped_no_title")
            continue
        at = _instant(cell["tagtime"], zone)
        if at is None:
            _count(counts, "skipped_no_timestamp")
            continue
        key = cell.get("trackkey") or cell.get("index") or ""
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "raw_id": f"{SERVICE}:{key}:{cell['tagtime']}",
            "media": "track",
            "title": title,
        }
        artist = " ".join(cell["artist"].split())
        if artist:
            payload["artist"] = artist
        if cell.get("url"):
            payload["url"] = cell["url"]
        payload["service"] = SERVICE
        if cell.get("trackkey"):
            payload["extra"] = {"track_key": cell["trackkey"]}
        drafts.append(
            {"at": at, "end": None, "tz": tz, "source": NAME, "kind": KIND, "tier": TIER, "payload": payload}
        )
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _instant(text: str, zone: ZoneInfo) -> str | None:
    """`TagTime` as RFC3339 UTC: a zoneless time is in `zone`; one with `Z` or an offset as given."""
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=zone)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
