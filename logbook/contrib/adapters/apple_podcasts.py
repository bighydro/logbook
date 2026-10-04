"""Apple Podcasts' MTLibrary.sqlite → listen/v1 (RFC 0019), from a copy, an iPhone backup or live from
the Mac.

The Mac keeps the library at `~/Library/Group Containers/243LU875E5.groups.com.apple.podcasts/
Documents/MTLibrary.sqlite`, the phone under its app group (`group.com.apple.podcasts`,
`Documents/MTLibrary.sqlite`, which `import-backup --only podcasts` copies out), a Core Data store
either way. Two tables matter:

    ZMTEPISODE   one row per episode: ZTITLE, ZUUID, ZLASTDATEPLAYED (seconds since 2001-01-01
                 UTC; null until played), ZPLAYHEAD, ZDURATION, ZPLAYCOUNT, ZPUBDATE,
                 ZWEBPAGEURL / ZENCLOSUREURL, ZAUTHOR, ZPODCAST → ZMTPODCAST.Z_PK, ZPODCASTUUID,
                 and the feed's transcript URL when the store keeps one (`TRANSCRIPT`)
    ZMTPODCAST   one row per show: Z_PK, ZUUID, ZTITLE, ZAUTHOR, ZFEEDURL

The store has over a hundred columns and Apple changes them: the columns are discovered with
`PRAGMA table_info`, only `ZMTEPISODE.ZTITLE`, `ZUUID` and `ZLASTDATEPLAYED` are required, every
other one is read when present and left out when not, and a missing `ZMTPODCAST` leaves `show`
out.

One line per episode that has been played (rule 5): kind `listen`, tier 2, source
`apple-podcasts`, `media` `episode`, `at` the last-played time, `raw_id`
`apple-podcasts:<ZUUID>@<at>` — the store overwrites the time when the episode is played again,
and that is a new line (rule 1). `title`, `show`, `publisher` (the show's author), `url` (the web
page, else the enclosure), `duration_s`, `played_s`, `completed`, `published`, `service`
`apple-podcasts`, `extra.play_count`, `extra.transcript_url`. An episode never played, or without
a title, is skipped and counted.

`completed` is the store's playhead read against its duration (rule 3, with `COMPLETE_SLACK_S` of
slack), or a playhead rewound to zero with a play counted — the app rewinds an episode it played
to the end; it is left out when the store has no playhead column, and false, never a guess, when
the columns it needs are not all there. `extra.transcript_url` is the feed's own transcript
(`<podcast:transcript>`) when the store keeps its URL in one of the `TRANSCRIPT` columns, and
only when the value is an http(s) URL: Apple's own transcript identifiers are not public and are
never recorded. The URL is recorded, never fetched: a reader never touches the network.

File mode (`logbook add apple-podcasts <copy>`, or sniffed): opened `mode=ro`, `immutable=1`.
Live mode (`logbook sync apple-podcasts`, ADR 0017): the Mac's own store (`LOGBOOK_PODCASTS_DB`
names another; `~` expanded), opened `mode=ro` so rows still in the -wal file are seen and
`immutable=1` only when that fails; the watermark is the newest last-played time, so a nightly
sync turns one row per episode into a listening history. Both modes are one mapping. No
network, never a write.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

NAME = "apple-podcasts"
KIND = "listen"
TIER = 2
SCHEMA = "listen/v1"
SERVICE = "apple-podcasts"
UNIT = "episodes"

DB_ENV = "LOGBOOK_PODCASTS_DB"
ENV = (DB_ENV,)  # optional: the default is the Mac's own store
DEFAULT_DB = (
    "Library",
    "Group Containers",
    "243LU875E5.groups.com.apple.podcasts",
    "Documents",
    "MTLibrary.sqlite",
)
SQLITE_HEADER = b"SQLite format 3\x00"
APPLE_EPOCH = 978_307_200
EPISODES, SHOWS = "ZMTEPISODE", "ZMTPODCAST"
REQUIRED = ("ZTITLE", "ZUUID", "ZLASTDATEPLAYED")
#: the columns a transcript URL may sit in, first one with an http(s) value wins; none is required
TRANSCRIPT = ("ZTRANSCRIPTURL", "ZTRANSCRIPTIDENTIFIER")
OPTIONAL = (
    "ZPLAYHEAD",
    "ZDURATION",
    "ZPLAYCOUNT",
    "ZPUBDATE",
    "ZWEBPAGEURL",
    "ZENCLOSUREURL",
    "ZAUTHOR",
    "ZPODCAST",
    "ZPODCASTUUID",
    *TRANSCRIPT,
)
SHOW_COLUMNS = ("Z_PK", "ZUUID", "ZTITLE", "ZAUTHOR")
#: a playhead this close to the end (seconds) counts as played to the end (RFC 0019 rule 3)
COMPLETE_SLACK_S = 30.0
URL_SCHEMES = ("http://", "https://")
PROGRESS_EVERY = 500
NOT_A_STORE = "not an Apple Podcasts library (no ZMTEPISODE table with ZTITLE, ZUUID, ZLASTDATEPLAYED)"


@dataclass(frozen=True)
class Config:
    db: Path


# -- file mode ------------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A SQLite file with the `ZMTEPISODE` table and its three required columns. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)
        try:
            return _columns(con, EPISODES) >= set(REQUIRED)
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One listen/v1 line draft per played episode in the store at `path`, oldest first."""
    con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro&immutable=1", uri=True)
    try:
        yield from lines(con, timezone or "UTC", counts if counts is not None else {}, since)
    finally:
        con.close()


# -- live mode ------------------------------------------------------------------------------------


def configure(env: Mapping[str, str]) -> Config:
    """Config from the environment; the one variable is optional."""
    given = env.get(DB_ENV, "").strip()
    return Config(db=Path(given).expanduser() if given else Path.home().joinpath(*DEFAULT_DB))


def watermark(draft: dict[str, Any]) -> str | None:
    """The listen's own time: the store is read by it."""
    return str(draft["at"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Every played episode from `since` (RFC3339 UTC; None means all), oldest first, through the
    same mapping as `run`. Raises OSError when the store cannot be read."""
    con = open_live(config.db)
    count, started = 0, time.monotonic()
    try:
        for draft in lines(con, timezone or "UTC", counts if counts is not None else {}, since):
            count += 1
            if progress is not None and count % PROGRESS_EVERY == 0:
                progress(count, time.monotonic() - started)
            yield draft
    except sqlite3.Error as e:
        raise OSError(f"cannot read {config.db} ({e})") from None
    finally:
        con.close()
    if progress is not None:
        progress(count, time.monotonic() - started)


def open_live(path: Path) -> sqlite3.Connection:
    """The Mac's own store, read-only: `mode=ro` first (sees the -wal file), `immutable=1` when
    that fails. Raises OSError, one line, when neither opens or the table is not there."""
    path = Path(path)
    errors: list[str] = []
    for extra in ("", "&immutable=1"):
        try:
            con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro{extra}", uri=True)
            columns = _columns(con, EPISODES)
        except (OSError, ValueError, sqlite3.Error) as e:
            errors.append(str(e).replace("\n", " "))
            continue
        if not columns >= set(REQUIRED):
            con.close()
            raise OSError(f"{path} is {NOT_A_STORE}")
        return con
    raise OSError(f"cannot open {path}: {'; '.join(errors)}")


# -- the mapping ----------------------------------------------------------------------------------


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def lines(
    con: sqlite3.Connection, tz: str, counts: dict[str, int], since: str | None = None
) -> Iterator[dict[str, Any]]:
    """The mapping both modes share: one draft per played episode, oldest first, streamed."""
    have = _columns(con, EPISODES)
    if not have >= set(REQUIRED):
        raise ValueError(NOT_A_STORE)
    shows = _shows(con)
    selected = list(REQUIRED) + [c if c in have else "NULL" for c in OPTIONAL]
    query = (
        f"SELECT {', '.join(selected)} FROM {EPISODES}"
        " WHERE ZLASTDATEPLAYED IS NOT NULL ORDER BY ZLASTDATEPLAYED, ZUUID"
    )
    for row in con.execute(query):
        draft = _draft(row, shows, tz, counts)
        if draft is not None and (since is None or draft["at"] >= since):
            yield draft
    never = con.execute(f"SELECT count(*) FROM {EPISODES} WHERE ZLASTDATEPLAYED IS NULL").fetchone()[0]
    if never:
        counts["skipped_never_played"] = counts.get("skipped_never_played", 0) + int(never)


def _shows(con: sqlite3.Connection) -> dict[object, tuple[str, str]]:
    """(title, author) by Z_PK and by ZUUID of every show; empty when the table is not there."""
    have = _columns(con, SHOWS)
    if "ZTITLE" not in have:
        return {}
    selected = [c if c in have else "NULL" for c in SHOW_COLUMNS]
    found: dict[object, tuple[str, str]] = {}
    for pk, uuid, title, author in con.execute(f"SELECT {', '.join(selected)} FROM {SHOWS}"):
        show = (" ".join(str(title or "").split()), " ".join(str(author or "").split()))
        if pk is not None:
            found[pk] = show
        if uuid:
            found[str(uuid)] = show
    return found


def _draft(
    row: tuple[Any, ...], shows: dict[object, tuple[str, str]], tz: str, counts: dict[str, int]
) -> dict[str, Any] | None:
    (
        title,
        uuid,
        played_at,
        playhead,
        duration,
        play_count,
        pub,
        web,
        enclosure,
        author,
        show_pk,
        show_uuid,
        *transcripts,
    ) = row
    name = " ".join(str(title or "").split())
    if not name:
        counts["skipped_no_title"] = counts.get("skipped_no_title", 0) + 1
        return None
    at = _rfc3339(played_at)
    if at is None:
        counts["skipped_bad_date"] = counts.get("skipped_bad_date", 0) + 1
        return None
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{SERVICE}:{uuid}@{at}",
        "media": "episode",
        "title": name,
    }
    show = shows.get(show_pk) or shows.get(str(show_uuid)) if (show_pk is not None or show_uuid) else None
    if show and show[0]:
        payload["show"] = show[0]
    publisher = (show[1] if show else "") or " ".join(str(author or "").split())
    if publisher:
        payload["publisher"] = publisher
    url = str(web or enclosure or "")
    if url:
        payload["url"] = url
    if isinstance(duration, int | float) and duration > 0:
        payload["duration_s"] = round(float(duration), 3)
    if isinstance(playhead, int | float) and playhead > 0:
        payload["played_s"] = round(float(playhead), 3)
    if isinstance(playhead, int | float):
        payload["completed"] = _completed(float(playhead), duration, play_count)
    published = _rfc3339(pub)
    if published is not None:
        payload["published"] = published
    payload["service"] = SERVICE
    extra: dict[str, Any] = {}
    if isinstance(play_count, int) and play_count > 0:
        extra["play_count"] = play_count
    transcript = next((str(t) for t in transcripts if isinstance(t, str) and t.startswith(URL_SCHEMES)), None)
    if transcript is not None:
        extra["transcript_url"] = transcript
    if extra:
        payload["extra"] = extra
    return {"at": at, "end": None, "tz": tz, "source": NAME, "kind": KIND, "tier": TIER, "payload": payload}


def _completed(playhead: float, duration: object, play_count: object) -> bool:
    """Played to the end: the playhead within `COMPLETE_SLACK_S` of a known duration, or rewound
    to zero after a play the store counted. False when the store cannot show either."""
    if isinstance(duration, int | float) and duration > 0 and playhead >= float(duration) - COMPLETE_SLACK_S:
        return True
    return playhead == 0 and isinstance(play_count, int) and play_count > 0


def _rfc3339(seconds_since_2001: object) -> str | None:
    if not isinstance(seconds_since_2001, int | float):
        return None
    try:
        when = datetime.fromtimestamp(APPLE_EPOCH + float(seconds_since_2001), UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")
