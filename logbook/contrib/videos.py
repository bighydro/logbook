"""The family's videos once the record names them (RFC 0040): the scene a draft and an attribution are
about, the record's lines read back, the bounded cache `videos fetch` fills and `videos infer` empties,
and what `doctor` counts. No model here and no network but `fetch`'s, through `drive_videos.media`.

**A scene** is one continuous recording inside a file: a digitised tape holds many, one after another.
It is named by the video line's id and its offsets in seconds, as a W3C media fragment: `<line
id>#t=<start>,<end>`, two decimals (`scene_ref`). The per-scene draft's `subject` is that string, and
the attribution's `ref` is `{kind: scene, value: <it>}`, so a scene is the same thing to every line that
names it and the video line is never touched.

**The cache** is `state/videos/` in the record folder: `state/` is bookkeeping, never the record, and
`backup` leaves it out. One file per video, named by its Drive id, while it waits for `videos infer`;
`<id>.part` while it downloads. Its cap is 8 GB unless the owner gives another with `--cache-gb`, which is
kept in `state/videos.json` for the next run and for `doctor`, with the files fetched so far. A file
bigger than the cap is refused and said so; a file that would take the cache past it waits for `videos
infer` to make room. A video is never copied into the record: what the record gets from one is the
lines `videos infer` writes, and none of them holds a pixel or a sample.

**Fetching** (`fetch`) takes the video lines nobody has inferred yet and that are not in the cache, in
the folder's order (path, then title), and downloads each, one at a time, a megabyte a read, through
`drive_videos.media` (the `drive.readonly` scope, the file's resource key sent when it has one). The md5
of what was written is compared with the one Drive reported when the line was written; a file that does
not match is deleted and said so, never kept. A dropped connection is resumed in the same run from the
byte it stopped at (`Range`), up to `RESUMES` times; a part an earlier run left is hashed and carried on
the same way, so an interrupted run loses nothing."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.chain import Line
from ..core.store import Logbook, now_utc, retractions
from .adapters import drive_videos, service_account

KIND = drive_videos.KIND
SCHEMA = drive_videos.SCHEMA
SOURCE = drive_videos.NAME
DRAFT_KIND, DRAFT_SCHEMA, DRAFT_UNIT = "draft", "draft/v1", "event"
DRAFT_SOURCE = "model:video-rules/1"  # who wrote the scene drafts: the rules, on two models' readings
ATTRIBUTION_KIND, ATTRIBUTION_SCHEMA = "attribution", "attribution/v1"
NO_KIND, NO_SCHEMA = "entity-review", "entity-review/v1"  # the review's no (RFC 0037 §6), type `scene`
ASK_KIND, ASK_SCHEMA, ASK_LIST = "task", "task/v1", "videos"  # "ask the family": an open task (RFC 0016)
SCENE = "scene"  # the ref kind
TIER = 2
GB = 1_000_000_000
DEFAULT_CAP_BYTES = 8 * GB  # the largest file of the family's folder is about 4 GB: it fits twice
CHUNK = 1 << 20  # bytes per read and write
PROGRESS_EVERY = 256 << 20  # a progress line every this many bytes
RESUMES = 3  # a dropped connection resumed in the same run, at most this many times per file
CACHE_DIR = Path("state", "videos")
STATE_FILE = Path("state", "videos.json")
PART = ".part"
SCENE_REF = re.compile(r"(?P<id>[^#\s]+)#t=(?P<start>\d+(?:\.\d+)?),(?P<end>\d+(?:\.\d+)?)\Z")
EN_DASH = "\u2013"
SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
SUFFIX = re.compile(r"\.[a-z0-9]{1,5}\Z")
RANGE = re.compile(r"bytes (\d+)-")


# -- the scene ------------------------------------------------------------------------------------


def scene_ref(video: str, start: float, end: float) -> str:
    """`<video line id>#t=12.50,47.00`: the W3C media fragment of a stretch of the video, in seconds."""
    return f"{video}#t={start:.2f},{end:.2f}"


def parse_scene(value: object) -> tuple[str, float, float] | None:
    """(video line id, start, end) from a scene ref; None for anything else."""
    found = SCENE_REF.match(str(value)) if isinstance(value, str) else None
    if found is None:
        return None
    start, end = float(found["start"]), float(found["end"])
    return (found["id"], start, end) if end > start else None


def clock(seconds: float) -> str:
    """`1:02:05`, `12:04`: an offset into a recording as a player shows it."""
    whole = int(seconds)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def span(start: float, end: float) -> str:
    return f"{clock(start)}{EN_DASH}{clock(end)}"


# -- the record, read back ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Video:
    """A standing video line."""

    line: Line

    @property
    def id(self) -> str:
        return str(self.line["id"])

    @property
    def payload(self) -> Mapping[str, Any]:
        found = self.line.get("payload")
        return found if isinstance(found, dict) else {}

    @property
    def drive_id(self) -> str:
        return str(self.payload.get("raw_id") or "")

    @property
    def title(self) -> str:
        return str(self.payload.get("title") or "untitled")

    @property
    def bytes(self) -> int | None:
        found = self.payload.get("bytes")
        return found if isinstance(found, int) and not isinstance(found, bool) else None

    @property
    def md5(self) -> str | None:
        digest = self.payload.get("digest")
        found = digest.get("md5") if isinstance(digest, dict) else None
        return str(found).lower() if isinstance(found, str) and found else None

    @property
    def file(self) -> Mapping[str, Any]:
        found = self.payload.get("file")
        return found if isinstance(found, dict) else {}

    @property
    def resource_key(self) -> str | None:
        found = self.file.get("resource_key")
        return str(found) if isinstance(found, str) and found else None

    @property
    def path(self) -> list[str]:
        found = self.file.get("path")
        return [str(p) for p in found] if isinstance(found, list) else []

    @property
    def duration_s(self) -> float | None:
        found = self.payload.get("duration_s")
        return float(found) if isinstance(found, int | float) and not isinstance(found, bool) else None

    @property
    def name(self) -> str:
        """`Familiens videoer / Home 01`: where it is in the folder, for a person."""
        return " / ".join([*self.path, self.title])

    def order(self) -> tuple[str, str, int]:
        return (" / ".join(self.path).casefold(), self.title.casefold(), int(self.line["seq"]))


def standing_videos(
    lines: Iterable[Line], retracted: Iterable[str] = (), superseded: Iterable[str] = ()
) -> list[Video]:
    """The video lines no retraction and no later line takes back, in the folder's order."""
    gone = {*retracted, *superseded}
    found = [
        Video(line)
        for line in lines
        if line.get("kind") == KIND
        and (line.get("payload") or {}).get("schema") == SCHEMA
        and str(line["id"]) not in gone
    ]
    return sorted(found, key=Video.order)


def read_videos(lb: Logbook) -> list[Video]:
    """The record's standing video lines, through the index."""
    with lb.index() as idx:
        gone = retractions(idx.retractions())
        return standing_videos(idx.by_kind(KIND), gone, idx.superseded(KIND))


def is_scene_draft(line: Line) -> bool:
    """A draft of unit `event` whose subject is one scene of a video."""
    payload = line.get("payload") or {}
    if line.get("kind") != DRAFT_KIND or payload.get("schema") != DRAFT_SCHEMA:
        return False
    subject = payload.get("subject")
    return (
        payload.get("unit") == DRAFT_UNIT
        and isinstance(subject, list)
        and len(subject) == 1
        and parse_scene(subject[0]) is not None
    )


def scene_of(line: Line) -> tuple[str, float, float] | None:
    """The scene a draft is of, or an attribution, a no or an ask names."""
    payload = line.get("payload") or {}
    if is_scene_draft(line):
        return parse_scene(payload["subject"][0])
    ref = payload.get("ref")
    if isinstance(ref, dict) and ref.get("kind") == SCENE:
        return parse_scene(ref.get("value"))
    extra = payload.get("extra")
    if line.get("kind") == ASK_KIND and isinstance(extra, dict):
        return parse_scene(extra.get(SCENE))
    return None


def inferred(lines: Iterable[Line]) -> set[str]:
    """The video line ids some scene draft is of: the files `videos infer` has done, under any model."""
    found: set[str] = set()
    for line in lines:
        scene = scene_of(line) if is_scene_draft(line) else None
        if scene is not None:
            found.add(scene[0])
    return found


# -- the cache --------------------------------------------------------------------------------------


@dataclass
class State:
    """`state/videos.json`: the cap and the files fetched so far. Bookkeeping, never the record."""

    cap_bytes: int = DEFAULT_CAP_BYTES
    fetched: dict[str, dict[str, Any]] = field(default_factory=dict)


class StateError(ValueError):
    """`state/videos.json` is not what it should be."""


def read_state(root: Path) -> State:
    """The cache's state; the defaults when there is no file. StateError naming the file when it is
    not the shape."""
    path = root.joinpath(*STATE_FILE.parts)
    if not path.is_file():
        return State()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise StateError(f"{STATE_FILE.as_posix()} is not JSON: {e}") from None
    cap = data.get("cap_bytes") if isinstance(data, dict) else None
    fetched = data.get("fetched") if isinstance(data, dict) else None
    if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0 or not isinstance(fetched, dict):
        raise StateError(
            f"{STATE_FILE.as_posix()} needs cap_bytes (a positive number) and fetched (an object)"
        )
    return State(cap, {str(k): v for k, v in fetched.items() if isinstance(v, dict)})


def write_state(root: Path, state: State) -> Path:
    """Replace the state file whole: a temporary file, then a rename."""
    path = root.joinpath(*STATE_FILE.parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"cap_bytes": state.cap_bytes, "fetched": dict(sorted(state.fetched.items()))}
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    os.replace(tmp, path)
    return path


class Cache:
    """`state/videos/`: one file per video waiting to be inferred, `<id>.part` while it downloads."""

    def __init__(self, root: Path) -> None:
        self.dir = root.joinpath(*CACHE_DIR.parts)

    @staticmethod
    def stem(video: Video) -> str:
        """The file's name without its suffix: the Drive id, or its digest when it is not a plain id."""
        found = video.drive_id
        return found if SAFE_ID.match(found) else hashlib.sha256(found.encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def suffix(video: Video) -> str:
        found = Path(video.title).suffix.lower()
        return found if SUFFIX.match(found) else ".mp4"

    def path(self, video: Video) -> Path:
        return self.dir / f"{self.stem(video)}{self.suffix(video)}"

    def part(self, video: Video) -> Path:
        return self.dir / f"{self.stem(video)}{PART}"

    def cached(self, video: Video) -> Path | None:
        """The file, whole and verified, when it is in the cache."""
        found = self.path(video)
        return found if found.is_file() else None

    def files(self) -> list[Path]:
        """Everything in the cache that takes room: the files, the parts, the scratch of a run."""
        if not self.dir.is_dir():
            return []
        return sorted(p for p in self.dir.rglob("*") if p.is_file())

    def used(self) -> int:
        total = 0
        for path in self.files():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
        return total

    def complete(self) -> list[Path]:
        """The whole files waiting for `videos infer`."""
        if not self.dir.is_dir():
            return []
        return sorted(p for p in self.dir.iterdir() if p.is_file() and p.suffix != PART)


# -- fetching ---------------------------------------------------------------------------------------

Media = Callable[[Any, str, str | None, int], service_account.Stream]


@dataclass
class Fetched:
    video: Video
    bytes: int
    resumed_from: int  # the byte the download began at: 0, or where a part left it


@dataclass
class FetchReport:
    cap_bytes: int
    used_before: int
    pending: int = 0  # the files neither inferred nor cached when the run began
    fetched: list[Fetched] = field(default_factory=list)
    refused: list[Video] = field(default_factory=list)  # bigger than the cap
    unknown_size: list[Video] = field(default_factory=list)  # Drive gave no size: the cap cannot hold it
    full: Video | None = None  # the file that would have taken the cache past its cap
    failed: list[str] = field(default_factory=list)  # one sentence per file that could not be fetched
    limit_reached: bool = False
    used_after: int = 0  # the cache's size when the run ended
    disk_full: bool = False  # the disk under the record filled up: the run stopped there


def fetch(
    lb: Logbook,
    config: Any,
    *,
    limit: int | None = None,
    cap_bytes: int | None = None,
    media: Media | None = None,
    progress: Callable[[str], None] | None = None,
    again: bool = False,
) -> FetchReport:
    """Download the videos nobody has inferred yet (with `again`, those inferred too, for `videos infer`
    under other models or settings) and the cache does not hold, one at a time, until
    `limit` files are tried or the next one would take the cache past its cap. `cap_bytes` is kept in
    `state/videos.json` when given. A file whose md5 does not match is deleted and its sentence put in
    `failed`; a dropped connection is resumed from its byte, `RESUMES` times, then left as a part for the
    next run and said in `failed`. Raises service_account.GoogleError when Google refuses the account
    (the scope not delegated, the key gone)."""
    state = read_state(lb.root)
    if cap_bytes is not None:
        state.cap_bytes = cap_bytes
        write_state(lb.root, state)
    cache = Cache(lb.root)
    report = FetchReport(state.cap_bytes, cache.used())
    with lb.index() as idx:
        done = set() if again else inferred(idx.of_source(DRAFT_KIND, DRAFT_SOURCE, "", "9999-12-31"))
    videos = [v for v in read_videos(lb) if v.id not in done and cache.cached(v) is None]
    report.pending = len(videos)
    get = media if media is not None else drive_videos.media
    tried = 0
    for video in videos:
        if limit is not None and tried >= limit:
            report.limit_reached = True
            break
        size = video.bytes
        if size is None:
            report.unknown_size.append(video)
            continue
        if size > state.cap_bytes:
            report.refused.append(video)
            continue
        part = cache.part(video)
        have = part.stat().st_size if part.is_file() else 0
        if cache.used() - have + size > state.cap_bytes:
            report.full = video
            break
        tried += 1
        done_bytes = _download(config, video, cache, get, report, progress)
        if report.disk_full:
            break
        if done_bytes is None:
            continue
        state.fetched[video.drive_id] = {"at": now_utc(), "bytes": done_bytes, "md5": video.md5}
        write_state(lb.root, state)
    report.used_after = cache.used()
    return report


def _download(
    config: Any,
    video: Video,
    cache: Cache,
    media: Media,
    report: FetchReport,
    progress: Callable[[str], None] | None,
) -> int | None:
    """One file into the cache, verified: its size on success; None, with the sentence in `failed`,
    when it could not be fetched whole or did not match. A drop, whether the connection fails or the
    answer just ends short, is resumed from the byte it reached, `RESUMES` times, and then the part is
    kept for the next run; bytes that cannot be the file (more than the line says, a 416 before its
    end, a wrong md5) are deleted. A full disk stops the run (`report.disk_full`)."""
    cache.dir.mkdir(parents=True, exist_ok=True)
    part = cache.part(video)
    expected = video.bytes or 0
    digest = hashlib.md5()
    written = 0
    if part.is_file():
        with part.open("rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK), b""):
                digest.update(chunk)
                written += len(chunk)
    else:
        part.touch()  # a file of no bytes is a file too: it is verified and kept like any other
    began = written
    resumes = 0
    reported = written // PROGRESS_EVERY
    while written < expected:
        try:
            stream = media(config, video.drive_id, video.resource_key, written)
        except service_account.ApiError as e:
            if e.status == 416:  # past the file's end: the part is all of it, or Drive's file is shorter
                break
            if e.status == 404:
                _unlink(part)
                report.failed.append(f"{video.name}: Drive has no file with its id any more (HTTP 404)")
                return None
            raise
        try:
            start = _range_start(stream)
            if written and (stream.status == 200 or (start is not None and start != written)):
                digest, written, began, reported = hashlib.md5(), 0, 0, 0  # not from our byte: start over
                part.write_bytes(b"")
                if stream.status != 200:  # a part of the file from somewhere else: ask again, whole
                    stream.close()
                    continue
            with part.open("ab") as fh:
                while True:
                    chunk = stream.read(CHUNK)
                    if not chunk:
                        break
                    fh.write(chunk)
                    digest.update(chunk)
                    written += len(chunk)
                    if written > expected:
                        break
                    if progress is not None and written // PROGRESS_EVERY > reported:
                        reported = written // PROGRESS_EVERY
                        progress(f"  {video.title}: {_size(written)} of {_size(expected)}")
        except OSError as e:
            stream.close()
            if e.errno == errno.ENOSPC:
                report.disk_full = True
                report.failed.append(
                    f"{video.name}: the disk is full at {_size(written)} of {_size(expected)}; the part is"
                    " kept: make room, then run `videos fetch` again"
                )
                return None
            resumes += 1
            if resumes > RESUMES:
                report.failed.append(
                    f"{video.name}: the connection dropped at {_size(written)} of {_size(expected)}"
                    f" ({e}); the part is kept, run `videos fetch` again to resume"
                )
                return None
            service_account.sleep(service_account.BACKOFF_S * 2.0 ** (resumes - 1))
            continue
        stream.close()
        if written > expected:
            break
        if written < expected:  # the answer ended short with no error: how urllib shows a drop
            resumes += 1
            if resumes > RESUMES:
                report.failed.append(
                    f"{video.name}: Drive's answer ended at {_size(written)} of {_size(expected)}"
                    f" {resumes} times; the part is kept, run `videos fetch` again to resume"
                )
                return None
    if written != expected:
        _unlink(part)
        report.failed.append(
            f"{video.name}: Drive sent {_size(written)} where the line says {_size(expected)}; nothing kept"
        )
        return None
    if video.md5 is not None and digest.hexdigest() != video.md5:
        _unlink(part)
        report.failed.append(
            f"{video.name}: the md5 of the bytes is not the one Drive reported when the line was written"
            " (the file in Drive changed, or the download was damaged); nothing kept"
        )
        return None
    os.replace(part, cache.path(video))
    report.fetched.append(Fetched(video, written, began))
    return written


def _range_start(stream: service_account.Stream) -> int | None:
    """Where a 206's bytes begin, from its `Content-Range` (`bytes 1000-3039/3040`); None without one."""
    found = RANGE.match(stream.headers.get("content-range", "")) if stream.status == 206 else None
    return int(found[1]) if found is not None else None


def _unlink(path: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        path.unlink()


def _size(n: int) -> str:
    """`3.2 GB`, `412 MB`, `3,040 bytes`: decimal units, as Drive and a disk's label count."""
    if n >= GB:
        return f"{n / GB:.1f} GB"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.0f} MB"
    return f"{n:,} bytes"


size_text = _size


def fetch_lines(report: FetchReport) -> Iterator[str]:
    """What `videos fetch` prints, after the progress: a line per file fetched, refused or waiting,
    then the cache against its cap."""
    for done in report.fetched:
        resumed = f", resumed at {_size(done.resumed_from)}" if done.resumed_from else ""
        checked = "md5 verified" if done.video.md5 is not None else "no md5 from Drive to verify it by"
        yield f"fetched {done.video.name}: {_size(done.bytes)}, {checked}{resumed}"
    for video in report.refused:
        yield (
            f"refused {video.name}: {_size(video.bytes or 0)} is more than the cache's cap of"
            f" {_size(report.cap_bytes)}; raise it with --cache-gb {_gb_for(video.bytes or 0)}"
        )
    for video in report.unknown_size:
        yield f"skipped {video.name}: Drive gave no size, so the cap cannot hold it"
    if report.full is not None:
        yield (
            f"the cache is full for {report.full.name} ({_size(report.full.bytes or 0)}): run `videos infer`,"
            " which empties it as it goes, then fetch again"
        )
    left = report.pending - len(report.fetched) - len(report.refused) - len(report.unknown_size)
    if not report.fetched and report.full is None and not report.failed and left <= 0:
        held = " or refused above" if report.refused or report.unknown_size else ""
        yield (
            f"nothing to fetch: every video in the record is inferred or already in the cache{held}"
            " (--again fetches the inferred ones, to infer them under other models or settings)"
        )
    yield f"cache: {cache_text(report.used_after, report.cap_bytes)}; {max(0, left)} more to fetch"


def _gb_for(n: int) -> str:
    """The `--cache-gb` that holds a file of `n` bytes: the next whole gigabyte, at least 8."""
    return str(max(8, -(-n // GB)))


def cache_text(used: int, cap: int) -> str:
    return f"{_size(used)} of {_size(cap)}"


# -- what doctor counts --------------------------------------------------------------------------


@dataclass(frozen=True)
class Counts:
    """The videos as `doctor` says them, from the record's lines and the cache."""

    files: int  # standing video lines
    bytes: int  # their sizes, as Drive reported them
    fetched: int  # files `videos fetch` has fetched, ever (`state/videos.json`)
    inferred: int  # files with scene drafts
    waiting: int  # whole files in the cache now
    scenes: int  # scenes of each file's latest inference
    proposed: int  # of those, the scenes with a proposal
    confirmed: int  # scenes with a standing attribution
    used: int  # the cache's bytes
    cap: int


def counts(lb: Logbook, lines: Iterable[Line]) -> Counts:
    """`lines`: the record's video, draft, attribution and retraction lines, opened. StateError when
    `state/videos.json` is not the shape."""
    found = list(lines)
    gone = set(retractions(line for line in found if line.get("kind") == "retraction"))
    replaced = {str((line.get("payload") or {}).get("supersedes")) for line in found}
    listed = standing_videos(found, gone, replaced)
    drafts_of = [line for line in found if is_scene_draft(line) and str(line["id"]) not in gone]
    latest: dict[str, str] = {}
    for line in sorted(drafts_of, key=lambda line: int(line["seq"])):
        scene = scene_of(line)
        extra = (line.get("payload") or {}).get("extra")
        if scene is not None and isinstance(extra, dict):
            latest[scene[0]] = str(extra.get("inference"))
    scenes = proposed = 0
    for line in drafts_of:
        scene = scene_of(line)
        extra = (line.get("payload") or {}).get("extra")
        if (
            scene is None
            or not isinstance(extra, dict)
            or str(extra.get("inference")) != latest.get(scene[0])
        ):
            continue
        scenes += 1
        proposed += isinstance(extra.get("proposal"), dict)
    confirmed = {
        ref
        for line in found
        if line.get("kind") == ATTRIBUTION_KIND
        and str(line["id"]) not in gone | replaced
        and (ref := ((line.get("payload") or {}).get("ref") or {}).get("value")) is not None
    }
    state = read_state(lb.root)
    cache = Cache(lb.root)
    return Counts(
        len(listed),
        sum(v.bytes or 0 for v in listed),
        len(state.fetched),
        len(inferred(drafts_of)),
        len(cache.complete()),
        scenes,
        proposed,
        len(confirmed),
        cache.used(),
        state.cap_bytes,
    )


def counts_text(found: Counts) -> str:
    """`3 video files in the record (9.6 GB); 2 fetched, 1 inferred, 1 waiting in the cache; 12 scenes,
    5 proposed, 2 confirmed; cache 3.2 GB of 8.0 GB`."""
    return (
        f"{found.files} video file{'s' if found.files != 1 else ''} in the record ({_size(found.bytes)});"
        f" {found.fetched} fetched, {found.inferred} inferred, {found.waiting} waiting in the cache;"
        f" {found.scenes} scene{'s' if found.scenes != 1 else ''}, {found.proposed} proposed,"
        f" {found.confirmed} confirmed; cache {cache_text(found.used, found.cap)}"
    )
