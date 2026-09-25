"""Google Takeout Google Photos → photo/v1 (RFC 0002). The second Takeout sub-adapter.

Input is the unzipped `Takeout/Google Photos/` folder (or the Takeout root that holds it, or one
album folder from inside it): album folders holding media files, each with a JSON sidecar of the
photo's metadata. Google names the sidecar `<file>.json` in older archives and
`<file>.supplemental-metadata.json` in newer ones, cuts the name short when it would run long
(`<file>.supplemental-me.json`, or the first 46 characters of `<file>` when even that is too long),
and moves a duplicate marker outside the name (`IMG_1.JPG(1).json` for `IMG_1(1).JPG`). Matching
is by those rules, exact first, then by the sidecar's own `title`, then by a unique prefix; a
sidecar that names no file is counted, never a line. A media file with no sidecar (an edited copy,
say) is still a line, timed by the file's modification time and flagged `extra.no_sidecar`.

One line per media file. `at` is `photoTakenTime` (falling back to `creationTime`, counted).
`raw_id` is the id in the sidecar's Google Photos url when there is one, else `<album>/<file>`, so
a re-run appends nothing and one photo filed in two albums is one line (the first album by name).
Provenance follows RFC 0002 through `googlePhotosOrigin` (ADR 0011: a data rule, `ORIGINS`): a
phone upload is `camera`, a shared album is `received`, everything else `other`; a live-photo pair
(a still and a video with one stem in one album) is one `camera` line, the motion half under
`extra.live_video`. Names of people the sidecar carries go under `extra.people` as source-native
`{kind: "name", value}` refs, never resolved, never in `payload.people` (that field is for the
library's ids, RFC 0002). `lat`/`lon` come from `geoData` (then `geoDataExif`) when both are
non-zero.

Media v1 rule, as for WhatsApp and iMessage: the pixels are never copied and `payload.media` is only
the kind. The file's SHA-256 and size are recorded under `extra.media` for a later attach pass;
`LOGBOOK_TAKEOUT_HASH_MEDIA=0` skips the hashing and records only the path. Pure: reads the folder,
writes nothing, no network.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from logbook.adapters.takeout import SOURCE

NAME = "google-takeout-photos"
KIND = "photo"
TIER = 1
SCHEMA = "photo/v1"
LIBRARY = "google-photos"
FOLDER = "Google Photos"
HASH_MEDIA_ENV = "LOGBOOK_TAKEOUT_HASH_MEDIA"
CHUNK = 1 << 20
SNIFF_FILE_BUDGET = 200  # JSON files sniff opens before deciding the folder is not ours
SIDECAR_MAX_BYTES = 4 << 20  # a sidecar is a few kilobytes; a bigger JSON file is some other export
SUPPLEMENTAL = "supplemental-metadata"
TRUNCATED_AT = 46  # Google keeps this many characters of a long sidecar name before ".json"
MAX_SAFE_INT = 2**53
DUPLICATE = re.compile(r"^(?P<name>.+?)(?P<mark>\(\d+\))$")
EARLIEST = 631_152_000  # 1990-01-01: a smaller unix stamp is a placeholder, not a capture time
LATEST = 4_102_444_800  # 2100-01-01

# -- provenance rule (RFC 0002, ADR 0011): data, so it can be reconsidered ----------------------
ORIGINS = {"mobileUpload": "camera", "fromSharedAlbum": "received"}
OTHER = "other"

IMAGE_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".dng": "image/dng",
    ".cr2": "image/x-canon-cr2",
    ".cr3": "image/x-canon-cr3",
    ".nef": "image/x-nikon-nef",
    ".arw": "image/x-sony-arw",
    ".raf": "image/x-fuji-raf",
    ".orf": "image/x-olympus-orf",
    ".rw2": "image/x-panasonic-rw2",
}
VIDEO_TYPES = {
    ".mov": "video/quicktime",
    ".mp4": "video/mp4",
    ".m4v": "video/mp4",
    ".3gp": "video/3gpp",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".webm": "video/webm",
    ".mpg": "video/mpeg",
    ".mpeg": "video/mpeg",
    ".wmv": "video/x-ms-wmv",
    ".mts": "video/mp2t",
    ".m2ts": "video/mp2t",
}

# counts, in the order `logbook add` reports them
MEDIA_HASHED = "media_hashed"
LIVE_PAIRS = "live_photo_pairs"
NO_SIDECAR = "no_sidecar"
AT_FROM_CREATION = "at_from_creation_time"
AT_FROM_FILE = "at_from_file_time"
SIDECAR_WITHOUT_FILE = "skipped_sidecar_without_file"
UNREADABLE_JSON = "skipped_unreadable_json"
NOT_MEDIA = "skipped_not_media"
COUNTS = (
    MEDIA_HASHED,
    LIVE_PAIRS,
    NO_SIDECAR,
    AT_FROM_CREATION,
    AT_FROM_FILE,
    SIDECAR_WITHOUT_FILE,
    UNREADABLE_JSON,
    NOT_MEDIA,
)


# -- sniff --------------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A folder that is, or contains, `Google Photos/`; or any folder (an album, or the folder of
    albums) holding at least one JSON sidecar with `photoTakenTime`, looked for in the folder and its
    immediate subfolders. Never a file, never raises."""
    path = Path(path)
    try:
        if not path.is_dir():
            return False
        if (path / FOLDER).is_dir():
            return True
        budget = SNIFF_FILE_BUDGET
        for folder in _albums(path):
            for candidate in sorted(folder.iterdir()):
                if not _is_json(candidate) or not _small_file(candidate):
                    continue
                if budget <= 0:
                    return False
                budget -= 1
                doc = _read_json(candidate)
                if isinstance(doc, dict) and isinstance(doc.get("photoTakenTime"), dict):
                    return True
    except OSError:
        return False
    return False


def _albums(root: Path) -> list[Path]:
    """The root itself, then its immediate subfolders, in name order; hidden ones are not albums."""
    folders = [root]
    subfolders = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    folders.extend(sorted(subfolders, key=lambda p: p.name))
    return folders


def _is_json(path: Path) -> bool:
    return path.suffix.lower() == ".json"


def _small_file(path: Path) -> bool:
    """A regular file no bigger than a sidecar could be; never read a large export to say no."""
    return path.is_file() and path.stat().st_size <= SIDECAR_MAX_BYTES


def _read_json(path: Path) -> object:
    try:
        with path.open("rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError):
        return None


# -- run ------------------------------------------------------------------------------------


def run(
    path: Path, since: str | None = None, counts: dict[str, int] | None = None
) -> Iterator[dict[str, Any]]:
    """Yield one photo/v1 line draft per media file, albums and files in name order.

    `since` is RFC3339 UTC and filters on `at`. `counts`, when given, receives what was hashed,
    paired, defaulted or skipped (`COUNTS`)."""
    if counts is None:
        counts = {}
    for key in COUNTS:
        counts.setdefault(key, 0)
    root = Path(path)
    if (root / FOLDER).is_dir():
        root = root / FOLDER
    if not root.is_dir():
        raise ValueError(f"{path}: not a Google Takeout photos folder")
    hash_media = os.environ.get(HASH_MEDIA_ENV, "1").strip() != "0"
    for folder in _albums(root):
        album = folder.name
        for draft in _album(folder, album, root, hash_media, counts):
            if not (since and draft["at"] < since):
                yield draft


def _album(
    folder: Path, album: str, root: Path, hash_media: bool, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    media: dict[str, Path] = {}
    sidecars: dict[str, dict[str, Any]] = {}
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        if not entry.is_file() or entry.name.startswith("."):
            continue
        if _is_json(entry):
            if not _small_file(entry):
                continue
            doc = _read_json(entry)
            if doc is None:
                counts[UNREADABLE_JSON] += 1
            elif isinstance(doc, dict) and _is_sidecar(doc):
                sidecars[entry.name] = doc
        elif _media_type(entry) is not None:
            media[entry.name] = entry
        else:
            counts[NOT_MEDIA] += 1
    matched = _match(sidecars, media)
    for name in sidecars:
        if name not in matched.values():
            counts[SIDECAR_WITHOUT_FILE] += 1
    by_file = {file: sidecars[name] for file, name in matched.items()}
    motion = _live_pairs(media)
    counts[LIVE_PAIRS] += len(motion)
    for name in sorted(media):
        if name in motion.values():
            continue
        yield _draft(
            media[name],
            by_file.get(name),
            matched.get(name),
            album,
            root,
            motion.get(name),
            hash_media,
            counts,
        )


def _is_sidecar(doc: dict[str, Any]) -> bool:
    """A photo's sidecar carries a taken or creation time; an album's `metadata.json` carries neither."""
    return any(isinstance(doc.get(k), dict) for k in ("photoTakenTime", "creationTime"))


# -- sidecar ↔ file ---------------------------------------------------------------------------


def _match(sidecars: dict[str, dict[str, Any]], media: dict[str, Path]) -> dict[str, str]:
    """{media file name: sidecar file name}. Exact rules first for every sidecar, then the loose
    ones for what is left, each file claimed at most once: the sidecar's `title` (Google writes the
    full original name there), then, for a name Google cut at TRUNCATED_AT characters, the one file
    that starts with what is left."""
    claimed: dict[str, str] = {}
    loose: list[tuple[str, str]] = []
    for sidecar in sidecars:
        stem = Path(sidecar).stem
        name, mark = _split_duplicate(stem)
        base = _strip_supplemental(name)
        exact = _with_mark(base, mark)
        if exact in media and exact not in claimed:
            claimed[exact] = sidecar
        elif not mark:
            loose.append((sidecar, stem))
    for sidecar, stem in loose:
        title = sidecars[sidecar].get("title")
        if isinstance(title, str) and title in media and title not in claimed:
            claimed[title] = sidecar
            continue
        if len(stem) < TRUNCATED_AT:
            continue
        by_prefix = [f for f in media if f.startswith(stem) and f not in claimed]
        if len(by_prefix) == 1:
            claimed[by_prefix[0]] = sidecar
    return claimed


def _split_duplicate(stem: str) -> tuple[str, str]:
    """`IMG_1.JPG(1)` → (`IMG_1.JPG`, `(1)`); anything else → (stem, '')."""
    found = DUPLICATE.match(stem)
    return (found["name"], found["mark"]) if found else (stem, "")


def _strip_supplemental(name: str) -> str:
    """`IMG_1.JPG.supplemental-metadata` → `IMG_1.JPG`, however short Google cut the suffix."""
    head, dot, tail = name.rpartition(".")
    if dot and tail and SUPPLEMENTAL.startswith(tail.lower()) and head:
        return head
    return name


def _with_mark(name: str, mark: str) -> str:
    """The duplicate marker goes back before the extension: `IMG_1.JPG` + `(1)` → `IMG_1(1).JPG`."""
    if not mark:
        return name
    pure = PurePosixPath(name)
    return f"{pure.stem}{mark}{pure.suffix}"


def _live_pairs(media: dict[str, Path]) -> dict[str, str]:
    """{still file name: video file name} for a still and a video sharing one stem (case-insensitive)."""
    stills: dict[str, str] = {}
    videos: dict[str, str] = {}
    for name in sorted(media):
        kind = _kind(media[name])
        key = PurePosixPath(name).stem.lower()
        (stills if kind == "image" else videos).setdefault(key, name)
    return {stills[key]: videos[key] for key in stills if key in videos}


# -- mapping --------------------------------------------------------------------------------


def _draft(
    file: Path,
    sidecar: dict[str, Any] | None,
    sidecar_name: str | None,
    album: str,
    root: Path,
    live_video: str | None,
    hash_media: bool,
    counts: dict[str, int],
) -> dict[str, Any]:
    at, taken_from = _at(sidecar, file, counts)
    local_path = file.relative_to(root).as_posix()
    extra: dict[str, Any] = {"album": album, "taken_from": taken_from}
    if sidecar is None:
        extra["no_sidecar"] = True
        counts[NO_SIDECAR] += 1
        origin = None
    else:
        extra["sidecar"] = sidecar_name
        origin = _origin(sidecar.get("googlePhotosOrigin"))
        if origin:
            extra["origin"] = origin
        caption = sidecar.get("description")
        if isinstance(caption, str) and caption.strip():
            extra["caption"] = caption.strip()
        url = sidecar.get("url")
        if isinstance(url, str) and url:
            extra["url"] = url
        views = _int(sidecar.get("imageViews"))
        if views is not None:
            extra["image_views"] = views
    people = _people(sidecar)
    if people:
        extra["people"] = people
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "asset_id": _raw_id(sidecar, album, file.name),
        "library": LIBRARY,
        "file_name": file.name,
        "media": _kind(file),
    }
    place = _place(sidecar)
    if place is not None:
        payload["lat"], payload["lon"], altitude = place
        if altitude is not None:
            extra["altitude"] = altitude
    payload["live_photo"] = live_video is not None
    payload["provenance"] = "camera" if live_video is not None else ORIGINS.get(origin or "", OTHER)
    payload["faces"] = len(people)
    payload["raw_id"] = payload["asset_id"]
    extra["media"] = _media(file, local_path, hash_media, counts)
    if live_video is not None:
        video = file.with_name(live_video)
        extra["live_video"] = _media(video, video.relative_to(root).as_posix(), hash_media, counts)
    payload["extra"] = extra
    return {
        "at": at,
        "end": None,
        "tz": None,
        "source": SOURCE,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _at(sidecar: dict[str, Any] | None, file: Path, counts: dict[str, int]) -> tuple[str, str]:
    if sidecar is not None:
        taken = _stamp(sidecar.get("photoTakenTime"))
        if taken is not None:
            return taken, "photoTakenTime"
        created = _stamp(sidecar.get("creationTime"))
        if created is not None:
            counts[AT_FROM_CREATION] += 1
            return created, "creationTime"
        counts[AT_FROM_FILE] += 1
    return _rfc3339(file.stat().st_mtime), "file_time"


def _stamp(value: object) -> str | None:
    """`{"timestamp": "1772356320"}` (a string of unix seconds; a number is taken too) → RFC3339 UTC."""
    if not isinstance(value, dict):
        return None
    raw = value.get("timestamp")
    if isinstance(raw, str):
        raw = raw.strip()
    if isinstance(raw, bool) or not isinstance(raw, str | int | float):
        return None
    try:
        seconds = float(raw)
    except (ValueError, OverflowError):
        return None
    if not math.isfinite(seconds) or not EARLIEST <= seconds < LATEST:
        return None
    return _rfc3339(seconds)


def _rfc3339(seconds: float) -> str:
    return datetime.fromtimestamp(int(seconds), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _raw_id(sidecar: dict[str, Any] | None, album: str, file_name: str) -> str:
    """The id at the end of the sidecar's Google Photos url, else `<album>/<file name>`."""
    url = sidecar.get("url") if sidecar is not None else None
    if isinstance(url, str) and url:
        try:
            last = PurePosixPath(urlsplit(url).path).name
        except ValueError:
            last = ""
        if last and last != "/" and "photo" in urlsplit(url).path:
            return last
    return f"{album}/{file_name}"


def _origin(value: object) -> str | None:
    """`{"mobileUpload": {...}}` → `mobileUpload`; a bare string is taken as the name itself."""
    if isinstance(value, dict):
        keys = [k for k in value if isinstance(k, str) and k]
        return keys[0] if len(keys) == 1 else None
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _people(sidecar: dict[str, Any] | None) -> list[dict[str, str]]:
    if sidecar is None or not isinstance(sidecar.get("people"), list):
        return []
    refs: list[dict[str, str]] = []
    for person in sidecar["people"]:
        name = person.get("name") if isinstance(person, dict) else None
        if isinstance(name, str) and name.strip():
            refs.append({"kind": "name", "value": name.strip()})
    return refs


def _place(sidecar: dict[str, Any] | None) -> tuple[float, float, float | None] | None:
    """(lat, lon, altitude) from `geoData`, then `geoDataExif`, when both coordinates are non-zero."""
    if sidecar is None:
        return None
    for key in ("geoData", "geoDataExif"):
        geo = sidecar.get(key)
        if not isinstance(geo, dict):
            continue
        lat, lon = _degrees(geo.get("latitude"), 90), _degrees(geo.get("longitude"), 180)
        if lat is None or lon is None or (lat == 0.0 and lon == 0.0):
            continue
        altitude = _finite(geo.get("altitude"))
        return lat, lon, altitude
    return None


def _degrees(value: object, limit: float) -> float | None:
    number = _finite(value)
    if number is None or not -limit <= number <= limit:
        return None
    return float(number)


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, int) and -MAX_SAFE_INT <= value <= MAX_SAFE_INT:
        return value
    return None


def _media_type(file: Path) -> str | None:
    suffix = file.suffix.lower()
    return IMAGE_TYPES.get(suffix) or VIDEO_TYPES.get(suffix)


def _kind(file: Path) -> str:
    return "video" if file.suffix.lower() in VIDEO_TYPES else "image"


def _media(file: Path, local_path: str, hash_media: bool, counts: dict[str, int]) -> dict[str, Any]:
    """{local_path, media_type, sha256?, bytes?}: the v1 media rule, the file itself never copied."""
    media: dict[str, Any] = {"local_path": local_path}
    media_type = _media_type(file)
    if media_type:
        media["media_type"] = media_type
    if hash_media:
        digest, size = _sha256(file)
        media["sha256"] = digest
        media["bytes"] = size
        counts[MEDIA_HASHED] += 1
    return media


def _sha256(file: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with file.open("rb") as fh:
        while chunk := fh.read(CHUNK):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size
