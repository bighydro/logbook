"""Google Takeout YouTube history → watch/v1 (RFC 0018).

Takeout writes `Takeout/YouTube and YouTube Music/history/watch-history.json` and
`search-history.json` (when the owner asked for JSON): one array each of
`{header, title, titleUrl?, subtitles?: [{name, url?}], time, products, activityControls?,
details?: [{name}]}`. `title` starts with the activity — `Watched …`, `Searched for …`, `Visited …`
— and `header` is the product (`YouTube`, `YouTube Music`). An ad carries
`details: [{name: "From Google Ads"}]`.

One line per watch and per search: kind `watch`, tier 2, source `google-takeout`, `at` the
entry's `time` in UTC to the second, `tz` the record's zone. `raw_id` is
`youtube:<time as the export spells it>:<sha256(titleUrl, else the title)[:16]>`. `action` is
`watched` or `searched`, `title` the words after the activity (a search's query), `url` the
`titleUrl`, `video_id` its `v=` when it has one, `channel` the first subtitle as `{name, url?}`,
`service` `youtube` or `youtube-music` from `header`. An ad (rule 2) and an activity that is
neither a watch nor a search (rule 3) are skipped and counted; an entry with no `time` too; a
removed video (no `titleUrl`) is a line without `url`, counted. Streamed through `ijson`, one
entry in memory at a time, whatever the size of the history. Pure: no network, never writes the
source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import ijson

from . import SOURCE

NAME = "google-takeout-youtube"
KIND = "watch"
TIER = 2
SCHEMA = "watch/v1"
FOLDER = "history"

SUFFIX = ".json"
SNIFF_BYTES = 4096
MARKS = (b'"YouTube watch history"', b'"YouTube search history"', b'"Watched ', b'"Searched for ')
ACTIONS = (("Watched ", "watched"), ("Searched for ", "searched"))
SERVICES = {"YouTube": "youtube", "YouTube Music": "youtube-music"}
AD = "From Google Ads"


def sniff(path: Path) -> bool:
    """A `watch-history.json` or `search-history.json`, or a folder holding one. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_history(f) for f in sorted(path.iterdir()))
        return _is_history(path)
    except OSError:
        return False


def _is_history(path: Path) -> bool:
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    return head.lstrip().startswith(b"[") and b'"header"' in head and any(mark in head for mark in MARKS)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One watch/v1 line draft per watch and per search in `path` (a history file, or the folder
    of them), oldest first. `since` is RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_history(f))
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        with file.open("rb") as fh:
            for entry in ijson.items(fh, "item"):
                draft = _draft(entry, tz, counts) if isinstance(entry, dict) else None
                if draft is not None and (since is None or draft["at"] >= since):
                    drafts.append(draft)
    yield from sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"]))


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(entry: dict[str, Any], tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    if any(isinstance(d, dict) and d.get("name") == AD for d in entry.get("details") or []):
        _count(counts, "skipped_ad")
        return None
    title = " ".join(str(entry.get("title") or "").split())
    action = next((a for prefix, a in ACTIONS if title.startswith(prefix)), None)
    if action is None:
        _count(counts, "skipped_other_activity")
        return None
    at, spelled = _time(entry.get("time"))
    if at is None:
        _count(counts, "skipped_no_timestamp")
        return None
    title = title[len(next(p for p, a in ACTIONS if a == action)) :]
    url = str(entry.get("titleUrl") or "")
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"youtube:{spelled}:{hashlib.sha256((url or title).encode('utf-8')).hexdigest()[:16]}",
        "action": action,
        "title": title,
    }
    if url:
        payload["url"] = url
        video_id = parse_qs(urlsplit(url).query).get("v", [""])[0]
        if video_id and action == "watched":
            payload["video_id"] = video_id
    else:
        _count(counts, "no_url")
    subtitles = [s for s in entry.get("subtitles") or [] if isinstance(s, dict) and s.get("name")]
    if subtitles:
        channel: dict[str, str] = {"name": " ".join(str(subtitles[0]["name"]).split())}
        if subtitles[0].get("url"):
            channel["url"] = str(subtitles[0]["url"])
        payload["channel"] = channel
    header = str(entry.get("header") or "")
    payload["service"] = SERVICES.get(header, header.lower().replace(" ", "-") or "youtube")
    return {"at": at, "end": None, "tz": tz, "source": SOURCE, "kind": KIND, "tier": TIER, "payload": payload}


def _time(value: object) -> tuple[str | None, str]:
    """(`at` to the second in UTC, the string as the export spells it), or (None, "")."""
    if not isinstance(value, str) or not value:
        return None, ""
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), value
