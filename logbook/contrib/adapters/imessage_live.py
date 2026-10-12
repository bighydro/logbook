"""iOS/macOS Messages → message/v1 (RFC 0008), live: reads the Mac's own Messages database.

`logbook sync imessage` opens `~/Library/Messages/chat.db` (`LOGBOOK_IMESSAGE_DB` names another
store, a copy for instance; `~` is expanded) with `imessage.open_live`: `mode=ro`, `immutable=1` only
when that fails, never a write, never a lock Messages.app would wait on. No network: the source is a
file on this Mac, which is why nothing here needs a key.

Every row goes through `imessage.lines`, the file adapter's own mapping: a message imported from the
phone backup (`logbook add sms.db`, `import-backup`) and the same message read on the Mac are the same
line with the same `raw_id` (the message guid), so `append_many` dedupes it. The tapback and
group-event skips, the typedstream body, the nanosecond/second dates and the media rule are the file
adapter's, unchanged. Attachments are looked up by the paths the attachment table stores
(`~/Library/Messages/Attachments/ab/12/<guid>/<name>`): the part after `Attachments` under the
`Attachments` folder beside the database when there is one, else under the Mac's own
`~/Library/Messages/Attachments` (a copy of chat.db elsewhere still finds them). A file that is there
is hashed into `extra.media` (`LOGBOOK_IMESSAGE_HASH_MEDIA=0` skips the hashing); one that is not
stays on the line as `extra.media` with no digest, and the row is counted as a skipped attachment.

The watermark is the newest message date seen. A message can land in the store after newer ones (a
device that was offline syncs its half of a conversation late; a row still in the -wal file is seen
on the next run), so `resume` starts each pull a lookback (24 h, `LOGBOOK_IMESSAGE_LOOKBACK_H`)
before the watermark and dedupe absorbs the overlap. With no watermark yet, `sync` resumes from the
record's newest imessage line, so a record seeded from the phone backup carries on where the backup
ended. An explicit `--since` is used as given.

`pull` tallies what it saw per chat type (`direct_chat`, `group_chat`) next to what the mapping
skipped and noted, and raises OSError, one line naming Full Disk Access as the usual cause, when the
database cannot be read.
"""

from __future__ import annotations

import math
import sqlite3
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from . import imessage
from .imessage import KIND, NAME

__all__ = ["ENV", "KIND", "NAME", "Config", "configure", "pull", "resume", "watermark"]

DB_ENV = "LOGBOOK_IMESSAGE_DB"
LOOKBACK_ENV = "LOGBOOK_IMESSAGE_LOOKBACK_H"
HASH_MEDIA_ENV = imessage.HASH_MEDIA_ENV
ENV = (DB_ENV, LOOKBACK_ENV, HASH_MEDIA_ENV)  # all optional: the defaults are the Mac's own store
LOOKBACK_H = 24.0
UNIT = "messages"  # what `sync` counts in its progress lines
PROGRESS_EVERY = 1000
DEFAULT_DB = ("Library", "Messages", "chat.db")

DIRECT_CHAT = "direct_chat"
GROUP_CHAT = "group_chat"


@dataclass(frozen=True)
class Config:
    db: Path
    attachments: Path
    lookback_h: float = LOOKBACK_H
    hash_media: bool = True


def configure(env: Mapping[str, str]) -> Config:
    """Config from the environment; every variable is optional. Raises ValueError when
    LOGBOOK_IMESSAGE_LOOKBACK_H is set but not a number of hours ≥ 0."""
    given = env.get(DB_ENV, "").strip()
    db = Path(given).expanduser() if given else Path.home().joinpath(*DEFAULT_DB)
    raw = env.get(LOOKBACK_ENV, "").strip()
    lookback = LOOKBACK_H
    if raw:
        try:
            lookback = float(raw)
        except ValueError:
            lookback = -1.0
        if not math.isfinite(lookback) or lookback < 0:
            raise ValueError(f"{LOOKBACK_ENV} must be a number of hours, 0 or more, not {raw!r}")
    hash_media = env.get(HASH_MEDIA_ENV, "1").strip() != "0"
    return Config(db=db, attachments=_attachments(db), lookback_h=lookback, hash_media=hash_media)


def _attachments(db: Path) -> Path:
    """The Attachments folder beside the store when there is one, else the Mac's own."""
    beside = db.parent / imessage.MEDIA_FOLDER
    if beside.is_dir():
        return beside
    return Path.home().joinpath(*DEFAULT_DB[:-1], imessage.MEDIA_FOLDER)


def resume(config: Config, mark: str) -> str:
    """Where a pull starts, given the watermark (or the record's newest message): the lookback before it."""
    start = datetime.fromisoformat(mark).astimezone(UTC) - timedelta(hours=config.lookback_h)
    return start.strftime("%Y-%m-%dT%H:%M:%SZ")


def watermark(draft: dict[str, Any]) -> str | None:
    """The message's own date: the store is read by it."""
    return str(draft["at"])


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every message in the store dated from `since` (RFC3339 UTC; None means all), in ROWID order,
    one message/v1 line draft each, streamed. Skips and notes are tallied in `counts`, with how many
    lines were in direct and in group chats. `progress(messages_so_far, elapsed_seconds)` is called
    every thousand lines and once at the end. Raises OSError when the store cannot be read."""
    counts = counts if counts is not None else {}
    counts.setdefault(DIRECT_CHAT, 0)
    counts.setdefault(GROUP_CHAT, 0)
    con = imessage.open_live(config.db)
    count, started = 0, time.monotonic()
    try:
        for draft in imessage.lines(con, config.attachments, config.hash_media, counts, since):
            kind = GROUP_CHAT if draft["payload"]["chat"]["type"] == "group" else DIRECT_CHAT
            counts[kind] += 1
            count += 1
            if progress is not None and count % PROGRESS_EVERY == 0:
                progress(count, time.monotonic() - started)
            yield draft
    except sqlite3.Error as e:
        raise OSError(f"cannot read {config.db} ({e}): {imessage.FULL_DISK_ACCESS}") from None
    finally:
        con.close()
    if progress is not None and count % PROGRESS_EVERY:
        progress(count, time.monotonic() - started)
