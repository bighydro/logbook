"""The family's home videos in Google Drive → `video/v1` (RFC 0039), from Drive's metadata alone.

`logbook sync drive --videos` lists one Drive folder, the one `LOGBOOK_DRIVE_VIDEOS_FOLDER` names (a
folder id, a setting of the machine the record lives on, never in a repository), and every subfolder
below it, through the one Google service account (`service_account`: LOGBOOK_DRIVE_SA_KEY,
LOGBOOK_DRIVE_USER), read-only, with the metadata scope (`drive.metadata.readonly`) that `sync drive`'s
folder paths already use. One line per video file. No byte of a video is asked for: `videos fetch` is
the one command that reads a file's bytes, with its own scope (`drive.readonly`), one file at a time.

**What is listed.** Each folder's children that are folders or video files (`mimeType contains
'video/'`), never in the trash, by name, `PAGE_SIZE` a page: the photos, the scanned lists and the
documents beside the videos are never listed, and a subfolder of photos is walked and yields nothing.
A shortcut is not followed. A folder already walked is not walked twice (a folder two parents share),
and no walk goes deeper than `MAX_DEPTH`.

**The line.** `at` is when this run listed the folder: the moment the record learned of the file. A
digitised tape's Drive times say when it was digitised or uploaded, never when anything on it was
filmed, so they are kept as what they are, under `extra` (`drive_created`, `drive_modified`), and
never as the line's time; when a scene was filmed is only ever the owner's attribution (RFC 0039), a
line of its own. `end` is null. Tier 2: a family's video holds other people's faces and voices, and its
title and description may name them. The payload:

- `raw_id`: the Drive id, so a file is written once however often the folder is listed;
- `library` `google-drive`; `title`, the file's name; `description`, when Drive has one;
- `file`: `id`, `name`, `path` (the folders from the listed one down, by name), `mime_type`, `url` (a
  link that opens it in Drive) and `resource_key` when Drive keeps one for an older file (the owner's own
  account needs none to read it; it is recorded, and `videos fetch` sends it, so nothing fails on one);
- `bytes`, `duration_s`, `width`, `height` from Drive's `size` and `videoMediaMetadata`, when Drive has
  processed the file;
- `digest`: `{md5}`, the checksum Drive reports, which `videos fetch` verifies the bytes against.

**Every run lists the whole folder.** It is small (tens of files) and only folders and videos are
listed, so a file moved into it later, whatever its modified time, is found; the record's dedupe on
`(source, raw_id)` writes nothing twice. The watermark is the newest `drive_modified` a line holds.

**Not in the registry.** The module is reached through `sync drive --videos`, a flag of drive's, and is
deliberately not an entry point of `logbook.adapters`: `sync --all` and the schedule never list the
folder, which changes when the family adds a tape, and is listed by hand then.

**A quota answer.** Drive's daily or per-user limit (a 403 or 429 saying so, or the retries of
`service_account.Session` exhausted on one) stops the walk: the files listed before it are written, one
line says what happened, and `sync` keeps the watermark and exits 1. Run again later."""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from . import service_account
from .service_account import Account, ApiError, GoogleError

__all__ = [
    "ENV",
    "FOLDER_ENV",
    "KIND",
    "NAME",
    "SCHEMA",
    "TIER",
    "Config",
    "check",
    "configure",
    "media",
    "pull",
    "watermark",
]

NAME = "drive-videos"  # the `source` of its lines and the name of its watermark, `state/drive-videos.json`
FOLDER_ENV = "LOGBOOK_DRIVE_VIDEOS_FOLDER"
ENV = (*service_account.ENV, FOLDER_ENV)
KIND = "video"
SCHEMA = "video/v1"
TIER = 2  # a family's video: other people's faces and voices
UNIT = "video files"  # what `sync` counts in its progress lines
LIBRARY = "google-drive"
SCOPE = service_account.SCOPES["drive paths"]  # the listing: metadata, never content
MEDIA_SCOPE = service_account.SCOPES["drive files"]  # a file's bytes: `videos fetch` alone
LIST_URL = "https://www.googleapis.com/drive/v3/files"
FILE_URL = "https://www.googleapis.com/drive/v3/files/{id}"
OPEN_URL = "https://drive.google.com/file/d/{id}/view"
FOLDER_MIME = "application/vnd.google-apps.folder"
FIELDS = (
    "nextPageToken,files(id,name,mimeType,size,md5Checksum,createdTime,modifiedTime,description,"
    "resourceKey,videoMediaMetadata(width,height,durationMillis))"
)
PAGE_SIZE = 100
MAX_DEPTH = 32  # folders below the listed one, at most
FOLDER_ID = re.compile(r"[A-Za-z0-9_-]{10,128}\Z")
RESOURCE_KEYS = "X-Goog-Drive-Resource-Keys"
QUOTA_REASONS = frozenset(
    {
        "dailyLimitExceeded",
        "dailyLimitExceededUnreg",
        "quotaExceeded",
        "rateLimitExceeded",
        "userRateLimitExceeded",
        "sharingRateLimitExceeded",
    }
)


@dataclass(frozen=True)
class Config:
    """The account and the folder. The repr shows neither."""

    account: Account = field(repr=False)
    folder: str = field(repr=False)


def configure(env: Mapping[str, str]) -> Config | None:
    """The account and the folder from the environment; None until all three variables are set.
    ValueError naming the variable (never its value) when the folder is not a Drive folder id or the
    key is not one (`service_account.configure`)."""
    folder = env.get(FOLDER_ENV, "").strip()
    account = service_account.configure(env)
    if account is None or not folder:
        return None
    if not FOLDER_ID.match(folder):
        raise ValueError(
            f"{FOLDER_ENV} must be a Drive folder id, the part of the folder's address after"
            " /folders/ (letters, digits, - and _)"
        )
    return Config(account, folder)


def check(config: Config) -> str:
    """What `doctor` says: the key read and loadable, no network asked."""
    return service_account.describe(config.account)


def watermark(draft: dict[str, Any]) -> str | None:
    """The newest Drive modified time the line holds: the upload's clock, never the filming's."""
    found = draft["payload"].get("extra", {}).get("drive_modified")
    return str(found) if found else None


def _now() -> datetime:
    return datetime.now(UTC)


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    failed: list[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Every video file in the folder and below it, one `video/v1` line draft each, in the order they
    were listed. `since` is not a filter: the whole folder is listed every run (the record's dedupe
    writes each Drive id once). `progress(videos_so_far, elapsed_seconds)` after each folder. A quota
    answer is one entry in `failed` and the walk stops there, the files listed before it yielded; any
    other failure to read Google is a `service_account.GoogleError` (an OSError)."""
    counts = counts if counts is not None else {}
    at = _z(_now())
    tz = timezone or "UTC"
    session = service_account.Session(config.account, SCOPE)
    found: list[tuple[dict[str, Any], list[str]]] = []
    try:
        root = _root(session, config.folder)
        _walk(session, root, found, progress, counts)
    except GoogleError as e:
        if failed is None or not _quota(e):
            raise
        failed.append(
            f"Drive answered with its quota ({e}); stopped after {_plural(len(found), 'video file')}"
            " listed, the watermark kept: run again later"
        )
    for item, path in found:
        yield _draft(item, path, at, tz)


def _quota(error: GoogleError) -> bool:
    """Whether Drive said no for want of quota: a 403 or 429 with a quota reason, or the retries of a
    rate limit exhausted."""
    if isinstance(error, ApiError):
        return error.status in (403, 429) and bool(error.reasons & QUOTA_REASONS)
    return "gave up after" in str(error) and ("HTTP 429" in str(error) or "HTTP 403" in str(error))


def _root(session: service_account.Session, folder: str) -> dict[str, Any]:
    """The listed folder itself, by id: its name heads every path. GoogleError, naming the variable,
    when the account cannot see it or it is not a folder."""
    try:
        item = session.get_json(
            FILE_URL.format(id=folder), {"fields": "id,name,mimeType", "supportsAllDrives": "true"}
        )
    except ApiError as e:
        if e.status in (403, 404) and not e.reasons & QUOTA_REASONS:
            raise GoogleError(
                f"{FOLDER_ENV} names no folder this account can see (HTTP {e.status})"
            ) from None
        raise
    if item.get("mimeType") != FOLDER_MIME:
        raise GoogleError(f"{FOLDER_ENV} names a file, not a folder")
    return item


def _walk(
    session: service_account.Session,
    root: dict[str, Any],
    found: list[tuple[dict[str, Any], list[str]]],
    progress: Callable[[int, float], None] | None,
    counts: dict[str, int],
) -> None:
    """The folder and its subfolders, breadth first: each folder's video files appended to `found`
    with the folder's path, its subfolders queued. A folder seen before is not walked again."""
    started = time.monotonic()
    queue: list[tuple[str, list[str]]] = [(str(root["id"]), [_name(root)])]
    seen = {str(root["id"])}
    while queue:
        folder, path = queue.pop(0)
        for item in _children(session, folder):
            item_id = str(item.get("id") or "")
            if not item_id:
                continue
            if item.get("mimeType") == FOLDER_MIME:
                if item_id in seen:
                    continue
                seen.add(item_id)
                if len(path) > MAX_DEPTH:
                    _count(counts, "skipped_too_deep")
                    continue
                queue.append((item_id, [*path, _name(item)]))
            elif str(item.get("mimeType") or "").startswith("video/"):
                found.append((item, path))
        if progress is not None:
            progress(len(found), time.monotonic() - started)


def _children(session: service_account.Session, folder: str) -> Iterator[dict[str, Any]]:
    """One folder's subfolders and video files, every page."""
    params = {
        "q": f"'{folder}' in parents and trashed = false and"
        f" (mimeType = '{FOLDER_MIME}' or mimeType contains 'video/')",
        "fields": FIELDS,
        "pageSize": str(PAGE_SIZE),
        "orderBy": "name",
        "supportsAllDrives": "true",
        "includeItemsFromAllDrives": "true",
    }
    token: str | None = None
    while True:
        page = session.get_json(LIST_URL, {**params, "pageToken": token} if token else params)
        yield from (f for f in page.get("files") or [] if isinstance(f, dict))
        token = page.get("nextPageToken")
        if not isinstance(token, str) or not token:
            return


def _draft(item: dict[str, Any], path: list[str], at: str, tz: str) -> dict[str, Any]:
    file_id = str(item["id"])
    name = _name(item)
    file: dict[str, Any] = {"id": file_id, "name": name, "path": list(path)}
    if item.get("mimeType"):
        file["mime_type"] = str(item["mimeType"])
    file["url"] = OPEN_URL.format(id=file_id)
    if isinstance(item.get("resourceKey"), str) and item["resourceKey"]:
        file["resource_key"] = item["resourceKey"]
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": file_id, "library": LIBRARY, "title": name}
    description = " ".join(str(item.get("description") or "").split())
    if description:
        payload["description"] = description
    payload["file"] = file
    size = _int(item.get("size"))
    if size is not None:
        payload["bytes"] = size
    meta = item.get("videoMediaMetadata")
    meta = meta if isinstance(meta, dict) else {}
    millis = _int(meta.get("durationMillis"))
    if millis is not None:
        payload["duration_s"] = millis / 1000
    for key in ("width", "height"):
        value = _int(meta.get(key))
        if value is not None:
            payload[key] = value
    if isinstance(item.get("md5Checksum"), str) and item["md5Checksum"]:
        payload["digest"] = {"md5": item["md5Checksum"].lower()}
    extra: dict[str, Any] = {}
    for key, word in (("drive_created", "createdTime"), ("drive_modified", "modifiedTime")):
        stamp = item.get(word)
        if isinstance(stamp, str) and stamp:
            try:
                extra[key] = _z(_instant(stamp))
            except ValueError:
                continue
    payload["extra"] = extra
    return {"at": at, "end": None, "tz": tz, "source": NAME, "kind": KIND, "tier": TIER, "payload": payload}


def media(
    config: Config, file_id: str, resource_key: str | None = None, offset: int = 0
) -> service_account.Stream:
    """A file's bytes from `offset` on (`Range`), with its resource key sent when it has one: the stream
    `videos fetch` reads and closes. ApiError 416 when the offset is the file's end."""
    session = service_account.Session(config.account, MEDIA_SCOPE)
    headers: dict[str, str] = {}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    if resource_key:
        headers[RESOURCE_KEYS] = f"{file_id}/{resource_key}"
    return session.stream(FILE_URL.format(id=file_id), {"alt": "media", "supportsAllDrives": "true"}, headers)


def _name(item: dict[str, Any]) -> str:
    return " ".join(str(item.get("name") or "").split()) or "untitled"


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _instant(text: str) -> datetime:
    """An RFC 3339 time as an aware UTC datetime; ValueError for one that is not."""
    when = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return when.astimezone(UTC)


def _z(when: datetime) -> str:
    return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
