"""Apple Music's CSVs from Apple's data export → listen/v1 (RFC 0019).

privacy.apple.com → Apple Media Services information → `Apple_Media_Services.zip` → the folder
`Apple Music Activity/`, in which three files describe listening:

    Apple Music Play Activity.csv                one row per player event: `Event Start Timestamp`,
                                                 `Event End Timestamp`, `Event Type` (`PLAY_END`,
                                                 `PLAY_START`, …), `Song Name` and `Artist Name` (an
                                                 older export has `Content Name` alone), `Media
                                                 Duration In Milliseconds`, `Play Duration
                                                 Milliseconds`, `End Reason Type`, `Device
                                                 Identifier`, `Offline`, the client's IP address
    Apple Music Library Tracks.csv               one row per track in the library: `Title`,
                                                 `Artist`, `Album`, `Track Duration`, `Last Played
                                                 Date`, `Play Count`, `Skip Count`, the identifiers
    Apple Music - Play History Daily Tracks.csv  one row per track per day: `Date Played`
                                                 (`YYYYMMDD`), `Hours` (`20, 21`), `Play Duration
                                                 Milliseconds`, `Play Count`, `Skip Count`, `Track
                                                 Description` (`Artist - Title`)

`logbook add apple-music <file>` reads one file, whichever of the three it is, by its header; the
columns are found by name, case aside, and one the mapping does not need may be missing. Every line
is kind `listen`, tier 2, source `apple-music`, `media` `track`, `service` `apple-music`.

The play activity is the record of listening: one line per `PLAY_END` row (a `PLAY_START`, a lyric
view and the rest are counted, not lines), `at` the start, `end` the end, `title` the song, `artist`,
`duration_s` and `played_s`, and under `extra` `ms_played`, `skipped` (true for a skip, false for a
track played to its end, absent otherwise), `device`, `end_reason` as Apple spells it and `offline`;
`raw_id` `apple-music:<sha256(artist, title)[:16]>:<start as spelled>`, since the file carries no
track id. The library is a snapshot per last-played time, as `apple-podcasts` (RFC 0019 rule 1):
`raw_id` `apple-music:<track identifier>@<last played>`, `album`, `duration_s`, `extra.play_count`
and `extra.skip_count`; a track never played is counted (rule 5). The daily history is coarse: one
line per row at the first hour listed, read in the record's zone (rule 4), `played_s` the day's
total, `extra.hours`, `extra.play_count` and `extra.skip_count`; `raw_id` `apple-music:<track
identifier>:<date> <hours as spelled>`. The Apple ID and the IP address are never kept. Pure: no
network, never writes the source.
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NAME = "apple-music"
KIND = "listen"
TIER = 2
SCHEMA = "listen/v1"
SERVICE = "apple-music"

SUFFIX = ".csv"
SNIFF_BYTES = 8192
STAMP = "%Y-%m-%dT%H:%M:%SZ"
ACTIVITY, LIBRARY, DAILY = "activity", "library", "daily"
REQUIRED = {
    ACTIVITY: ("event start timestamp", "play duration milliseconds"),
    LIBRARY: ("title", "last played date"),
    DAILY: ("date played", "track description"),
}
PLAY_END = "play_end"
NATURAL_END = "natural_end_of_track"
SKIPS = ("skipped", "manually_selected_playback_of_a_diff_item")


def sniff(path: Path) -> bool:
    """A `.csv` whose header is one of the three Apple Music files'. Never raises."""
    path = Path(path)
    try:
        if not path.is_file() or path.suffix.lower() != SUFFIX:
            return False
        with path.open("rb") as fh:
            head = fh.read(SNIFF_BYTES).decode("utf-8-sig", errors="replace")
    except OSError:
        return False
    return _shape(_columns(head.splitlines()[0] if head else "")) is not None


def _columns(header: str) -> dict[str, int]:
    return {name.strip().lower(): i for i, name in enumerate(next(csv.reader([header]), []))}


def _shape(columns: dict[str, int]) -> str | None:
    return next((shape for shape, needed in REQUIRED.items() if all(c in columns for c in needed)), None)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One listen/v1 line draft per play (the activity), per last-played time (the library) or per
    track per day (the daily history) in the file at `path`, oldest first. `since` is RFC3339 UTC
    and cuts on `at`; `timezone` is the record's zone, which reads the daily history's hours."""
    counts = counts if counts is not None else {}
    tz = timezone or "UTC"
    zone = ZoneInfo(tz)
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return
    columns = {name.strip().lower(): i for i, name in enumerate(rows[0])}
    shape = _shape(columns)
    if shape is None:
        raise ValueError(f"{path}: not an Apple Music play activity, library or daily play history CSV")
    mapping = {ACTIVITY: _activity, LIBRARY: _library, DAILY: _daily}[shape]
    drafts: list[dict[str, Any]] = []
    for row in rows[1:]:
        cell = {name: (row[i].strip() if i < len(row) else "") for name, i in columns.items()}
        found = mapping(cell, zone, counts)
        if found is not None:
            drafts.append(_line(found, tz))
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _line(draft: tuple[str, str | None, dict[str, Any]], tz: str) -> dict[str, Any]:
    at, end, payload = draft
    return {"at": at, "end": end, "tz": tz, "source": NAME, "kind": KIND, "tier": TIER, "payload": payload}


# -- the three files --------------------------------------------------------------------------------


def _activity(
    cell: dict[str, str], zone: ZoneInfo, counts: dict[str, int]
) -> tuple[str, str | None, dict[str, Any]] | None:
    """One `PLAY_END` row: the play from its start to its end."""
    event = cell.get("event type", "").lower()
    if event and event != PLAY_END:
        _count(counts, "skipped_not_a_play")
        return None
    spelled = cell.get("event start timestamp", "")
    at = _instant(spelled)
    if at is None:
        _count(counts, "skipped_no_timestamp")
        return None
    title = _text(cell.get("song name") or cell.get("content name"))
    if not title:
        _count(counts, "skipped_no_title")
        return None
    artist = _text(cell.get("artist name"))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{SERVICE}:{_digest(artist, title)}:{spelled}",
        "media": "track",
        "title": title,
    }
    if artist:
        payload["artist"] = artist
    if album := _text(cell.get("album name")):
        payload["album"] = album
    duration = _ms(cell.get("media duration in milliseconds"))
    if duration is not None and duration > 0:
        payload["duration_s"] = _seconds(duration)
    played = _ms(cell.get("play duration milliseconds"))
    if played is not None:
        payload["played_s"] = _seconds(played)
    payload["service"] = SERVICE
    extra: dict[str, Any] = {}
    if played is not None:
        extra["ms_played"] = played
    reason = cell.get("end reason type", "")
    if reason.lower() == NATURAL_END:
        extra["skipped"] = False
    elif any(mark in reason.lower() for mark in SKIPS):
        extra["skipped"] = True
    if device := _text(cell.get("device identifier")):
        extra["device"] = device
    if reason:
        extra["end_reason"] = reason
    if (offline := _bool(cell.get("offline"))) is not None:
        extra["offline"] = offline
    if extra:
        payload["extra"] = extra
    return at, _instant(cell.get("event end timestamp", "")), payload


def _library(
    cell: dict[str, str], zone: ZoneInfo, counts: dict[str, int]
) -> tuple[str, str | None, dict[str, Any]] | None:
    """One library track with a last-played time: a snapshot of that time (RFC 0019 rule 1)."""
    title = _text(cell.get("title"))
    if not title:
        _count(counts, "skipped_no_title")
        return None
    spelled = cell.get("last played date", "")
    if not spelled:
        _count(counts, "skipped_never_played")
        return None
    at = _instant(spelled)
    if at is None:
        _count(counts, "skipped_no_timestamp")
        return None
    artist = _text(cell.get("artist"))
    ident = cell.get("apple music track identifier") or cell.get("track identifier") or _digest(artist, title)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{SERVICE}:{ident}@{spelled}",
        "media": "track",
        "title": title,
    }
    if artist:
        payload["artist"] = artist
    if album := _text(cell.get("album")):
        payload["album"] = album
    duration = _ms(cell.get("track duration"))
    if duration is not None and duration > 0:
        payload["duration_s"] = _seconds(duration)
    payload["service"] = SERVICE
    extra = {
        key: n
        for key in ("play_count", "skip_count")
        if (n := _ms(cell.get(key.replace("_", " ")))) and n > 0
    }
    if extra:
        payload["extra"] = extra
    return at, None, payload


def _daily(
    cell: dict[str, str], zone: ZoneInfo, counts: dict[str, int]
) -> tuple[str, str | None, dict[str, Any]] | None:
    """One track on one day: a line at the first hour listed, in the record's zone (rule 4)."""
    description = _text(cell.get("track description"))
    if not description:
        _count(counts, "skipped_no_title")
        return None
    day_text = cell.get("date played", "")
    try:
        day = datetime.strptime(day_text, "%Y%m%d").date()
    except ValueError:
        _count(counts, "skipped_no_timestamp")
        return None
    hours_text = cell.get("hours", "")
    hours = [int(h) for h in hours_text.split(",") if h.strip().isdigit() and 0 <= int(h) <= 23]
    first = datetime(day.year, day.month, day.day, hours[0] if hours else 0, tzinfo=zone)
    artist, _sep, title = description.partition(" - ")
    if not _sep:
        artist, title = "", description
    ident = cell.get("track identifier") or _digest(artist, title)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{SERVICE}:{ident}:{day_text}" + (f" {hours_text}" if hours_text else ""),
        "media": "track",
        "title": title.strip(),
    }
    if artist.strip():
        payload["artist"] = artist.strip()
    played = _ms(cell.get("play duration milliseconds"))
    if played is not None:
        payload["played_s"] = _seconds(played)
    payload["service"] = SERVICE
    extra: dict[str, Any] = {}
    if played is not None:
        extra["ms_played"] = played
    if hours:
        extra["hours"] = hours
    for key in ("play_count", "skip_count"):
        n = _ms(cell.get(key.replace("_", " ")))
        if n and n > 0:
            extra[key] = n
    if reason := cell.get("end reason type", ""):
        extra["end_reason"] = reason
    if extra:
        payload["extra"] = extra
    return first.astimezone(UTC).strftime(STAMP), None, payload


# -- helpers ----------------------------------------------------------------------------------------


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""


def _digest(artist: str, title: str) -> str:
    return hashlib.sha256(f"{artist}\n{title}".encode()).hexdigest()[:16]


def _ms(text: str | None) -> int | None:
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _bool(text: str | None) -> bool | None:
    return {"true": True, "false": False}.get((text or "").strip().lower())


def _seconds(ms: int) -> int | float:
    return ms // 1000 if ms % 1000 == 0 else round(ms / 1000, 3)


def _instant(text: str) -> str | None:
    """An Apple timestamp (`2026-03-04T20:15:30.000Z`) as RFC3339 UTC to the second; one with no
    zone is UTC, as Apple writes them. None when empty or unreadable."""
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC).strftime(STAMP)
