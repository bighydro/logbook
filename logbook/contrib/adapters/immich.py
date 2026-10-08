"""Immich → photo/v1 (RFC 0002). The first live adapter: it pulls from your own Immich server.

Immich 3.2.x: `POST /api/search/metadata` with `filter.updatedAt.gte`, `orderBy`, `size`, `withExif`,
`withPeople`, paged with `cursor` / `assets.nextCursor` (the older `takenAfter`, `page` and `nextPage`
are deprecated in 3.2.0). The key is sent as `x-api-key`; it needs only the `asset.read` permission.
Stdlib urllib, no dependency.

The watermark is Immich's `updatedAt` (when the asset record last changed, which upload sets), so a
photo taken years ago and uploaded today is pulled today. `updatedAt` is filterable but not one of
the orderable fields in 3.2.1, so pages are ordered by `fileCreatedAt` and the watermark is the
largest `updatedAt` of the whole pull; `sync` stores it only once the pull has completed. A line's
`at` stays the capture time.

`fileCreatedAt` is not unique — a burst, a live-photo pair, a batch of scans or received files
stamped by the importing device share a second — and the cursor names a stamp, not an asset: the
page after a boundary that falls inside such a run begins at that stamp again and serves the run's
earlier members a second time. `pull` keeps the ids of the previous page's last-stamp run and drops
them when they come again, so every asset is counted and yielded once; the count under
`repeated_at_page_boundary` says how many the server served again. A run longer than a page would
leave the cursor where it is; the page then grows, up to MAX_PAGE_SIZE, and beyond that the walk
stops with one clear error rather than looping. `total` asks the server how many assets there are
before the walk, so `sync` can say `x of N`. A `walk` (the consumer's checkpoint keeper, `sync`'s
`WalkState`) is told after every page where the walk could resume; `pull` starts from what it saved.

One line per asset. The pixels stay in Immich; the line points at them by asset id. Names of people
are never logged, only Immich's person ids. Network happens only inside `total` and `pull`, which
only `logbook sync immich` calls (ADR 0012: no network on a file adapter's default path; a live adapter
has no default path).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from . import Walk

NAME = "immich"
ENV = ("LOGBOOK_IMMICH_URL", "LOGBOOK_IMMICH_KEY")
KIND = "photo"
TIER = 1
SCHEMA = "photo/v1"
PAGE_SIZE = 250
MAX_PAGE_SIZE = 1000  # Immich's ceiling on `size`; a run of equal stamps longer than this cannot be walked
TIMEOUT_S = 60
STATISTICS = ("/api/assets/statistics", "/api/server/statistics")  # the key's own count, then the server's

# -- provenance rule (RFC 0002, ADR 0011): data, so it can be reconsidered ----------------------
# A camera file: HEIC/RAW/JPEG stills, or a video, with make/model and an original capture time.
# A live-photo pair is camera evidence on its own: only a phone's camera makes one, and the mobile
# app links the pair at upload, before the server's metadata job has read any EXIF.
CAMERA_MIMES = frozenset(
    {
        "image/heic",
        "image/heif",
        "image/jpeg",
        "image/jpg",
        "image/dng",
        "image/x-adobe-dng",
        "image/x-canon-cr2",
        "image/x-canon-cr3",
        "image/x-nikon-nef",
        "image/x-sony-arw",
        "image/x-fuji-raf",
        "image/x-olympus-orf",
        "image/x-panasonic-rw2",
        "image/tiff",
        "video/quicktime",
        "video/mp4",
    }
)
# Device screen sizes in pixels (either orientation): phones, tablets, common laptop and desktop
# displays. A PNG at one of these with no camera data is a screenshot.
SCREEN_SIZES = frozenset(
    {
        (640, 1136),
        (750, 1334),
        (828, 1792),
        (1080, 1920),
        (1080, 2340),
        (1080, 2400),
        (1125, 2436),
        (1170, 2532),
        (1179, 2556),
        (1206, 2622),
        (1242, 2208),
        (1242, 2688),
        (1284, 2778),
        (1290, 2796),
        (1320, 2868),
        (1440, 2560),
        (1440, 3040),
        (1440, 3120),
        (1440, 3200),
        (1536, 2048),
        (1620, 2160),
        (1640, 2360),
        (1668, 2224),
        (1668, 2388),
        (2048, 2732),
        (1280, 800),
        (1366, 768),
        (1440, 900),
        (1470, 956),
        (1512, 982),
        (1680, 1050),
        (1728, 1117),
        (1920, 1080),
        (1920, 1200),
        (2560, 1440),
        (2560, 1600),
        (2560, 1664),
        (2880, 1800),
        (2940, 1912),
        (3024, 1964),
        (3456, 2234),
        (3840, 2160),
        (5120, 2880),
    }
)
SCREENSHOT_NAMES = re.compile(
    r"^(Screenshot|Screen Shot|Skjermbilde|Bildschirmfoto|Capture d)", re.IGNORECASE
)
# File names messengers give to what they hand you: WhatsApp, iOS shares, Telegram, Snapchat.
MESSENGER_NAMES = re.compile(
    r"^(IMG-\d{8}-WA\d+|VID-\d{8}-WA\d+|image\d*\.[A-Za-z0-9]+$|photo_\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}|Snapchat-)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Config:
    url: str
    key: str


def configure(env: Mapping[str, str]) -> Config | None:
    """Config from LOGBOOK_IMMICH_URL and LOGBOOK_IMMICH_KEY; None when either is absent or empty."""
    url, key = (env.get(name, "").strip() for name in ENV)
    if not url or not key:
        return None
    return Config(url=url.rstrip("/"), key=key)


def total(config: Config) -> int | None:
    """How many assets the server holds for this key: the key's own count (`GET
    /api/assets/statistics`, permission `asset.statistics`), else the whole server's (`GET
    /api/server/statistics`, an admin key); None when neither answers, and `sync` says `total
    unknown`. Asked once before the walk so progress can say `x of N`; network only under `sync`."""
    for path in STATISTICS:
        try:
            doc = _get(config, path)
        except (OSError, ValueError):
            continue
        n = _count(doc)
        if n is not None:
            return n
    return None


def _count(doc: Mapping[str, Any]) -> int | None:
    """`total` of the assets statistics; `photos` + `videos` of the server's (`images` + `videos`
    on an older assets endpoint)."""
    whole = doc.get("total")
    if isinstance(whole, int) and not isinstance(whole, bool):
        return whole
    parts = [doc.get(k) for k in ("images", "photos", "videos")]
    counted = [p for p in parts if isinstance(p, int) and not isinstance(p, bool)]
    return sum(counted) if counted else None


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    walk: Walk | None = None,
) -> Iterator[dict[str, Any]]:
    """Every asset Immich created or changed at or after `since` (RFC3339 UTC; None means all),
    oldest capture first, one photo/v1 line draft each. Trashed and hidden assets are never read
    (ADR 0011: the source's own junk judgement stands; hidden assets are the motion halves of live
    photos). Assets whose metadata is still pending are deferred to a later sync (see the module
    docstring) and tallied in `counts["pending"]`. `progress(assets_so_far, elapsed_seconds)` is
    called after every page with the assets counted once (the module docstring: the server serves
    the ones sharing a stamp at a page boundary again). With `walk`, the walk starts from the
    checkpoint it saved — `cursor`, `fetched`, `repeats` (the ids of the last-stamp run the cursor
    serves again), `watermark` — and `walk.reached(ordinal, checkpoint)` is told after every page
    but the last where the walk could resume once draft `ordinal` is in the record."""
    post: Callable[[Config, dict[str, Any]], dict[str, Any]] = _post
    saved = walk.start() if walk is not None else None
    cursor: str | None = str(saved["cursor"]) if saved and saved.get("cursor") else None
    count = int(saved.get("fetched") or 0) if saved else 0
    boundary: set[str] = set(saved.get("repeats") or []) if saved else set()
    mark: str | None = str(saved["watermark"]) if saved and saved.get("watermark") else None
    ordinal, size, started = 0, PAGE_SIZE, time.monotonic()
    if counts is not None:
        counts["pending"] = 0
    while True:
        body: dict[str, Any] = {
            "orderBy": {"field": "fileCreatedAt", "direction": "asc"},
            "size": size,
            "withExif": True,
            "withPeople": True,
        }
        if since:
            body["filter"] = {"updatedAt": {"gte": since}}
        if cursor:
            body["cursor"] = cursor
        page = post(config, body)["assets"]
        items: list[dict[str, Any]] = list(page.get("items", []))
        fresh = [asset for asset in items if asset["id"] not in boundary]
        if len(fresh) < len(items) and counts is not None:
            counts["repeated_at_page_boundary"] = counts.get("repeated_at_page_boundary", 0) + (
                len(items) - len(fresh)
            )
        for asset in fresh:
            if asset.get("isTrashed") or asset.get("visibility") == "hidden":
                continue
            if _metadata_pending(asset):
                if counts is not None:
                    counts["pending"] += 1
                continue
            draft = _line(asset)
            updated = watermark(draft)
            if updated is not None and (mark is None or updated > mark):
                mark = updated
            ordinal += 1
            yield draft
        count += len(fresh)
        if progress is not None:
            progress(count, time.monotonic() - started)
        next_cursor = page.get("nextCursor")
        if not next_cursor or not items:
            return
        last = items[-1]["fileCreatedAt"]
        boundary = {asset["id"] for asset in items if asset["fileCreatedAt"] == last}
        if not fresh and next_cursor == cursor:  # the whole page was the run again: it is longer than a page
            if size >= MAX_PAGE_SIZE:
                raise ValueError(
                    f"immich: more than {MAX_PAGE_SIZE:,} assets share fileCreatedAt {last}; the walk cannot"
                    " pass them (the cursor names a stamp, not an asset)"
                )
            size = min(size * 2, MAX_PAGE_SIZE)
            continue
        cursor = next_cursor
        if walk is not None:
            walk.reached(
                ordinal,
                {"cursor": cursor, "fetched": count, "repeats": sorted(boundary), "watermark": mark},
            )


def _metadata_pending(asset: dict[str, Any]) -> bool:
    """True for an upload Immich's metadata job has not reached: no dimensions on the asset and
    an EXIF row holding nothing but the file size (or no EXIF row at all). After the job every
    image and video has dimensions, even one with no EXIF of its own."""
    exif: dict[str, Any] = asset.get("exifInfo") or {}
    if asset.get("width") is not None or asset.get("height") is not None:
        return False
    return not any(value not in (None, "") for key, value in exif.items() if key != "fileSizeInByte")


def watermark(draft: dict[str, Any]) -> str | None:
    """The asset's `updatedAt`: the `since` that would pull this line again."""
    value = draft["payload"].get("extra", {}).get("updated_at")
    return str(value) if value else None


def _post(config: Config, body: dict[str, Any]) -> dict[str, Any]:
    """One POST /api/search/metadata. With `_get`, the only network calls in this module."""
    req = Request(
        f"{config.url.rstrip('/')}/api/search/metadata",
        data=json.dumps(body).encode("utf-8"),
        headers={"x-api-key": config.key, "Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=TIMEOUT_S) as response:
        doc: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return doc


def _get(config: Config, path: str) -> dict[str, Any]:
    """One GET of a statistics endpoint (`total`)."""
    req = Request(
        f"{config.url.rstrip('/')}{path}",
        headers={"x-api-key": config.key, "Accept": "application/json"},
        method="GET",
    )
    with urlopen(req, timeout=TIMEOUT_S) as response:
        doc: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    return doc


# -- mapping ---------------------------------------------------------------------------------


def _line(asset: dict[str, Any]) -> dict[str, Any]:
    exif: dict[str, Any] = asset.get("exifInfo") or {}
    return {
        "at": _rfc3339(exif.get("dateTimeOriginal") or asset["fileCreatedAt"]),
        "end": None,
        "tz": None,  # the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": _payload(asset, exif),
    }


def _rfc3339(stamp: str) -> str:
    """Immich's ISO stamps (with milliseconds and an offset or Z) → RFC3339 UTC to the second."""
    parsed = datetime.fromisoformat(stamp)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload(asset: dict[str, Any], exif: dict[str, Any]) -> dict[str, Any]:
    media = str(asset.get("type", "OTHER")).lower()
    people = [p["id"] for p in asset.get("people") or [] if p.get("id")]
    live_photo = bool(asset.get("livePhotoVideoId"))
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "asset_id": asset["id"],
        "library": NAME,
        "file_name": asset["originalFileName"],
        "media": media,
    }
    lat, lon = exif.get("latitude"), exif.get("longitude")
    if lat is not None and lon is not None:
        payload["lat"], payload["lon"] = lat, lon
    camera = _camera(exif)
    if camera:
        payload["camera"] = camera
    width, height = _dimensions(asset, exif)
    if width is not None and height is not None:
        payload["width"], payload["height"] = width, height
    if media == "video":
        duration = _duration_s(asset.get("duration"))
        if duration is not None:
            payload["duration_s"] = duration
    payload["live_photo"] = live_photo
    payload["provenance"] = _provenance(asset, exif, camera, live_photo, width, height)
    payload["faces"] = len(people)
    payload["people"] = people
    payload["raw_id"] = asset["id"]
    extra: dict[str, Any] = {"checksum": asset.get("checksum"), "original_path": asset.get("originalPath")}
    if "isFavorite" in asset:  # the owner's mark, read by `infer keepers` (RFC 0024)
        extra["favorite"] = bool(asset["isFavorite"])
    if asset.get("updatedAt"):
        extra["updated_at"] = _rfc3339(asset["updatedAt"])
    description = (exif.get("description") or "").strip()
    if description:
        extra["description"] = description
    payload["extra"] = extra
    return payload


def _camera(exif: dict[str, Any]) -> str | None:
    parts = [str(exif.get(k)).strip() for k in ("make", "model") if exif.get(k)]
    return " ".join(parts) or None


def _dimensions(asset: dict[str, Any], exif: dict[str, Any]) -> tuple[int | None, int | None]:
    """EXIF dimensions first; the asset's own when EXIF has none (screenshots, received files)."""
    width, height = exif.get("exifImageWidth"), exif.get("exifImageHeight")
    if width is None or height is None:
        width, height = asset.get("width"), asset.get("height")
    return (int(width) if width is not None else None, int(height) if height is not None else None)


def _duration_s(value: object) -> float | None:
    """Immich 3.2 sends milliseconds (int); older servers sent a clock string `H:MM:SS.fff`."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return value / 1000.0
    text = str(value).strip()
    try:
        hours, minutes, seconds = text.split(":")
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None


def _provenance(
    asset: dict[str, Any],
    exif: dict[str, Any],
    camera: str | None,
    live_photo: bool,
    width: int | None,
    height: int | None,
) -> str:
    """RFC 0002's reference rule. `camera` is a live-photo pair, or make/model and an original
    capture time on a camera file type; `screenshot` is a PNG with no camera data at a device
    screen size (or named as one); `received` has no EXIF and a messenger's file name; else `other`.

    Before Immich's metadata job has run on an upload, `exifInfo` holds only the file size and
    width/height/duration are null, so the EXIF-based branches see nothing; the pair link is the
    one signal the mobile app sets at upload."""
    mime = str(asset.get("originalMimeType") or "").lower()
    name = str(asset.get("originalFileName") or "")
    taken = bool(exif.get("dateTimeOriginal"))
    if live_photo or (camera and taken and mime in CAMERA_MIMES):
        return "camera"
    if mime == "image/png" and not camera:
        size = (width, height)
        if (size in SCREEN_SIZES or size[::-1] in SCREEN_SIZES) or SCREENSHOT_NAMES.match(name):
            return "screenshot"
    if not camera and not taken and MESSENGER_NAMES.match(name):
        return "received"
    return "other"
