"""A Pocket export → browse/v1 (RFC 0017), one `save` per saved page.

Pocket's export (getpocket.com/export, a zip of `part_000000.csv`, `part_000001.csv`, …) has the
header `title,url,time_added,tags,status`: `time_added` in unix seconds, `tags` joined with `|`,
`status` `unread` or `archive`.

Why `browse/v1` and not `note/v1`: a note is the owner's own words (RFC 0010 rule 4), and a
saved page is a url with the page's title. RFC 0017 already writes a Chrome bookmark as a page the
owner kept; a Pocket save is the same thing kept in a read-later app, so it is the profile's
`save` action with `browser` `pocket`, `tags` and `status` (`unread` | `archived`). A separate
read-later profile would have been the same fields a third time.

One line per row: kind `browse`, tier 2, source `pocket`, `at` from `time_added`, `raw_id`
`pocket:<time_added>:<sha256(url)[:16]>`. A row with no url or no time is skipped and counted.
Pure: no network, never writes the source.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "pocket"
KIND = "browse"
TIER = 2
SCHEMA = "browse/v1"
BROWSER = "pocket"

SUFFIX = ".csv"
HEADER = ("title", "url", "time_added", "tags", "status")
SNIFF_BYTES = 256
STATUS = {"archive": "archived", "archived": "archived", "unread": "unread"}


def sniff(path: Path) -> bool:
    """A `.csv` with Pocket's header, or a folder holding one (the unzipped export). Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_export(f) for f in sorted(path.iterdir()))
        return _is_export(path)
    except OSError:
        return False


def _is_export(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES).decode("utf-8-sig", errors="replace")
    first = tuple(cell.strip().lower() for cell in head.split("\n", 1)[0].split(","))
    return first[: len(HEADER)] == HEADER


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One browse/v1 line draft per saved page in `path` (one part, or the folder of parts),
    oldest first. `since` is RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_export(f))
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        with file.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                cells = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                draft = _draft(cells, tz, counts)
                if draft is not None:
                    drafts.append(draft)
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(row: dict[str, str], tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    url = row.get("url", "")
    if not url:
        _count(counts, "skipped_no_url")
        return None
    try:
        added = int(row.get("time_added", ""))
    except ValueError:
        _count(counts, "skipped_no_timestamp")
        return None
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{BROWSER}:{added}:{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}",
        "url": url,
    }
    title = " ".join(row.get("title", "").split())
    if title:
        payload["title"] = title
    payload["action"] = "save"
    payload["browser"] = BROWSER
    tags = [t.strip() for t in row.get("tags", "").split("|") if t.strip()]
    if tags:
        payload["tags"] = tags
    status = STATUS.get(row.get("status", "").lower())
    if status:
        payload["status"] = status
    at = datetime.fromtimestamp(added, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"at": at, "end": None, "tz": tz, "source": NAME, "kind": KIND, "tier": TIER, "payload": payload}
