"""Spotify's extended streaming history → listen/v1 (RFC 0019).

Spotify's privacy page (Account → Privacy settings → Extended streaming history) delivers a zip
whose folder `Spotify Extended Streaming History/` holds `Streaming_History_Audio_<years>_<n>.json`
and `Streaming_History_Video_<years>.json`: one JSON array each of

    {ts, platform, ms_played, conn_country, ip_addr, master_metadata_track_name,
     master_metadata_album_artist_name, master_metadata_album_album_name, spotify_track_uri,
     episode_name, episode_show_name, spotify_episode_uri, audiobook_title, audiobook_uri,
     audiobook_chapter_uri, audiobook_chapter_title, reason_start, reason_end, shuffle, skipped,
     offline, offline_timestamp, incognito_mode}

`ts` is when the stream *stopped*, in UTC. An older export carries `username` and lacks
`platform`, `skipped` and the audiobook columns; a row is read with whatever it has.

One line per stream: kind `listen`, tier 2, source `spotify`. `at` is `ts` less `ms_played` — when
playback started — and `end` is `ts`. `media` is `track` or `episode`; `title`, `artist` and `album`
(a track) or `show` (an episode) as Spotify spells them; `url` the open.spotify.com page of the URI;
`played_s`; `service` `spotify`; under `extra`: `ms_played`, `skipped`, `device` (Spotify's
`platform`), `reason_start`, `reason_end`, `shuffle`, `offline` and `country` (`conn_country`).
`raw_id` is `spotify:<the URI without its spotify: prefix>:<ts as spelled>`, so a track streamed
twice is two listens and a re-import appends nothing. The IP address and the username are never
kept. An audiobook chapter (RFC 0019 has tracks and episodes) and a row that names nothing (a local
file, a removed item) are skipped and counted. Streamed through `ijson`, one row in memory at a
time. Pure: no network, never writes the source.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import ijson

NAME = "spotify"
KIND = "listen"
TIER = 2
SCHEMA = "listen/v1"
SERVICE = "spotify"

SUFFIX = ".json"
SNIFF_BYTES = 4096
MARKS = (b'"ts"', b'"ms_played"')
NAMES = (b'"master_metadata_track_name"', b'"spotify_track_uri"', b'"episode_name"', b'"spotify_episode_uri"')
URI_PREFIX = "spotify:"
PAGE = "https://open.spotify.com/{kind}/{id}"
FLAGS = ("shuffle", "offline")
REASONS = ("reason_start", "reason_end")
STAMP = "%Y-%m-%dT%H:%M:%SZ"


def sniff(path: Path) -> bool:
    """A `Streaming_History_*.json`, or a folder holding one. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return any(_is_history(f) for f in sorted(path.iterdir()))
        return _is_history(path)
    except OSError:
        return False


def _is_history(path: Path) -> bool:
    """A JSON array whose first rows carry `ts`, `ms_played` and a track or episode column."""
    if not path.is_file() or path.suffix.lower() != SUFFIX:
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    if head.startswith(b"\xef\xbb\xbf"):
        head = head[3:]
    return head.lstrip().startswith(b"[") and all(m in head for m in MARKS) and any(n in head for n in NAMES)


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One listen/v1 line draft per stream in `path` (a history file, or the folder of them),
    oldest first. `since` is RFC3339 UTC and cuts on `at`; `timezone` is the record's zone, which
    every line carries (Spotify's times are UTC, so it localises nothing)."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else sorted(f for f in path.iterdir() if _is_history(f))
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        with file.open("rb") as fh:
            for row in ijson.items(fh, "item"):
                draft = _draft(row, tz, counts)
                if draft is not None:
                    drafts.append(draft)
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _draft(row: Any, tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    if not isinstance(row, dict):
        _count(counts, "skipped_no_title")
        return None
    stopped = _instant(row.get("ts"))
    if stopped is None:
        _count(counts, "skipped_no_timestamp")
        return None
    ms = _int(row.get("ms_played")) or 0
    track, episode = _text(row.get("master_metadata_track_name")), _text(row.get("episode_name"))
    if track:
        media, title, uri = "track", track, _text(row.get("spotify_track_uri"))
    elif episode:
        media, title, uri = "episode", episode, _text(row.get("spotify_episode_uri"))
    elif _text(row.get("audiobook_chapter_title")) or _text(row.get("audiobook_title")):
        _count(counts, "skipped_audiobook")
        return None
    else:
        _count(counts, "skipped_no_title")
        return None
    started = stopped - timedelta(milliseconds=ms)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{SERVICE}:{_ident(media, title, uri, row)}:{row['ts']}",
        "media": media,
        "title": title,
    }
    if media == "track":
        if artist := _text(row.get("master_metadata_album_artist_name")):
            payload["artist"] = artist
        if album := _text(row.get("master_metadata_album_album_name")):
            payload["album"] = album
    elif show := _text(row.get("episode_show_name")):
        payload["show"] = show
    if uri and uri.startswith(URI_PREFIX) and uri.count(":") == 2:
        _spotify, kind, id_ = uri.split(":")
        payload["url"] = PAGE.format(kind=kind, id=id_)
    payload["played_s"] = _seconds(ms)
    payload["service"] = SERVICE
    extra: dict[str, Any] = {"ms_played": ms}
    if isinstance(row.get("skipped"), bool):
        extra["skipped"] = row["skipped"]
    if device := _text(row.get("platform")):
        extra["device"] = device
    for key in REASONS:
        if reason := _text(row.get(key)):
            extra[key] = reason
    for key in FLAGS:
        if isinstance(row.get(key), bool):
            extra[key] = row[key]
    if country := _text(row.get("conn_country")):
        extra["country"] = country
    payload["extra"] = extra
    return {
        "at": started.strftime(STAMP),
        "end": stopped.strftime(STAMP),
        "tz": tz,
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _ident(media: str, title: str, uri: str, row: dict[str, Any]) -> str:
    """The URI without its `spotify:` prefix (`track:<id>`); for a named stream with no URI, the
    media and a digest of the name and performer, so the row still has a stable key."""
    if uri:
        return uri.removeprefix(URI_PREFIX)
    by = _text(row.get("master_metadata_album_artist_name")) or _text(row.get("episode_show_name"))
    return f"{media}:{hashlib.sha256(f'{by}\n{title}'.encode()).hexdigest()[:16]}"


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""


def _int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float | Decimal):
        return None
    return int(value)


def _seconds(ms: int) -> int | float:
    return ms // 1000 if ms % 1000 == 0 else round(ms / 1000, 3)


def _instant(text: object) -> datetime | None:
    """`ts` as an aware UTC datetime; a time with no zone is UTC, as Spotify writes them."""
    if not isinstance(text, str) or not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)
