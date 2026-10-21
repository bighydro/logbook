"""`logbook lab hold census files|senders|drive`: Hold v0 (RFC 0042, draft), a census of what the owner
holds, as a report and nothing else.

Hold is the layer that will give each thing the owner owns one place, so the attention it costs falls.
Version 0 only counts. Three censuses, each one report, Markdown and JSON, under `state/hold/` in the
record folder (`REPORTS`), replaced on every run:

- **files**: the folders the owner names, walked read-only. Counts and bytes by type, by extension
  and by the year a file was last modified; duplicates by digest (SHA-256 of the bytes, streamed, and
  only for files whose size another file shares); the `LARGEST` largest; the folders where nothing
  changed for `UNTOUCHED_DAYS` days.
- **senders**: the record's own `mail/v1` lines (RFC 0015). Every address that wrote to the owner, by
  count and by last seen, whether the owner ever wrote back, and whether its mail says it is a
  newsletter (a `List-Unsubscribe` header, when the line holds one); per sender, how many of its mails
  carry `extra.list.unsubscribe` and how many sit in Gmail's Promotions, Social or Updates tab
  (`extra.gmail_category`; RFC 0015, amendment of 2026-10-20: lines written before it hold neither).
- **drive**: the record's own Drive lines (`event/v1` of source `drive`): every file they name, by
  type, folder and last activity, the ones untouched for `UNTOUCHED_DAYS` days, the shared and the
  trashed.

What it never does, and the tests hold it to (`tests/test_lab_hold_safety.py`; what it counts is
`tests/test_lab_hold.py`):

- It never moves, renames, deletes or writes anything in a walked folder. A file is opened read-only
  (`_open`), only when its size is shared with another, and closed before the next. The one thing
  it writes is its report, in the record's `state/hold/`, which may lie under a walked folder (the
  record itself is never walked).
- It never makes the system fetch a file: a cloud placeholder (an iCloud file not on this Mac, a
  OneDrive or Google Drive file on demand) is counted from its metadata and never read, and a
  folder on another disk than the folder given (a mounted share, `/proc`) is not entered.
- The walk never leaves the folders it was given: a symbolic link (or a Windows junction) is counted
  and never followed, whether it points in or out; a folder that is not a folder (a FIFO, a socket, a
  device) is counted and never opened; the system's and Claude's own folders (`SKIP_FOLDERS`) and the
  record itself are skipped and counted.
- No file name leaves the report. A name is in the Markdown and the JSON under `state/hold/`, made
  for the owner's eyes alone (mode 0600 where the system has modes), and nowhere else: never in a
  line (nothing is appended), never in a crossing (which carries lines), never on stdout, which
  prints counts and the report's path (`summary`). The same holds for a sender's address.
- No connection is opened: the senders and Drive censuses read lines the record already holds.

Tiers (SPEC §4). A report is derived material and takes the highest tier it read: the senders' and
the Drive reports say so under `tier`, and `--tier N` leaves the lines above N out. A file has no
tier, and a file name can say anything, so the files report is tier 3.

Readers' rules otherwise: retracted and superseded lines are left out, a sealed line the identity
cannot open is counted (`sealed`) and never guessed at, and a payload this census cannot read is
counted and skipped, never a traceback."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
import stat
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path, PurePath, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..core.chain import Line, is_sealed
from ..core.search import MAX_TIER
from ..core.store import Logbook, retractions

REPORTS = PurePath("state") / "hold"  # record-relative: the only folder a census writes to
CENSUSES = ("files", "senders", "drive")
VERSION = 0  # the report's shape; a lab reader's JSON may change between releases
LARGEST = 50  # the largest files listed
UNTOUCHED_DAYS = 730  # a folder (or a Drive file) unchanged this long is "untouched"
TOP = 50  # rows per Markdown table where a list can be long; the JSON has them all
CHUNK = 1 << 20  # bytes read at a time while hashing
TIERS = (1, 2, 3)
FILES_TIER = 3  # a file name can say anything: the files report is held as the most private

# Folders the walk never enters, by name, case folded (macOS and Windows fold case): the system's own,
# the trash, version control's insides, and Claude's (a session's transcripts and settings are not
# the owner's things to shelve); `SKIP_TOP` only directly inside a given folder. Each skip is counted.
SKIP_FOLDERS = frozenset(
    name.casefold()
    for name in (
        "$RECYCLE.BIN",
        ".AppleDB",
        ".AppleDouble",
        ".DocumentRevisions-V100",
        ".Spotlight-V100",
        ".TemporaryItems",
        ".Trash",
        ".Trashes",
        ".claude",
        ".fseventsd",
        ".git",
        ".hg",
        ".svn",
        "System Volume Information",
    )
)
# Only directly inside a given folder: a home's `Library` and `AppData` are the system's, and a disk's
# own top folders when a whole disk is given (`/`, `C:\`); further down, a folder of these names is
# the owner's.
SKIP_TOP = frozenset(
    name.casefold()
    for name in (
        "$WinREAgent",
        "AppData",
        "Library",
        "Program Files",
        "Program Files (x86)",
        "ProgramData",
        "System",
        "Volumes",
        "Windows",
        "dev",
        "private",
        "proc",
        "run",
        "sys",
    )
)
# Claude's own folder under the system's application folders, wherever the walk meets them.
CLAUDE = "claude"
CLAUDE_PARENTS = frozenset(name.casefold() for name in (".config", "Application Support", "Local", "Roaming"))
SKIP_FILES = frozenset(
    name.casefold() for name in (".DS_Store", "Thumbs.db", "desktop.ini", ".localized", ".claude.json")
)
# A file or folder whose bytes are not on this disk: reading it makes the system fetch it.
SF_DATALESS = 0x40000000  # macOS `st_flags`: an iCloud file or folder evicted from this Mac
NOT_LOCAL_ATTRIBUTES = (
    0x00400000 | 0x00040000 | 0x00001000
)  # Windows: recall on data access, on open; offline

# The type of a file by its extension; anything else is `other`, a file without one `none`.
TYPES: dict[str, tuple[str, ...]] = {
    "image": ("jpg", "jpeg", "png", "gif", "heic", "heif", "webp", "tif", "tiff", "bmp", "raw", "dng",
              "cr2", "nef", "arw", "svg"),
    "video": ("mov", "mp4", "m4v", "avi", "mkv", "webm", "mts", "3gp"),
    "audio": ("mp3", "m4a", "aac", "wav", "flac", "ogg", "opus", "aiff"),
    "document": ("pdf", "doc", "docx", "odt", "rtf", "txt", "md", "pages", "epub", "tex"),
    "spreadsheet": ("xls", "xlsx", "ods", "csv", "tsv", "numbers"),
    "presentation": ("ppt", "pptx", "odp", "key"),
    "archive": ("zip", "tar", "gz", "tgz", "bz2", "xz", "7z", "rar", "dmg", "iso"),
    "code": ("py", "js", "ts", "html", "css", "json", "yaml", "yml", "toml", "sh", "c", "h", "rs", "go",
             "java", "swift", "ipynb", "sql"),
    "mail": ("eml", "mbox", "msg"),
}  # fmt: skip
TYPE_OF = {ext: kind for kind, exts in TYPES.items() for ext in exts}

DRIVE_SOURCE = "drive"
GONE = ("trash", "delete")  # a Drive file whose last such activity was not followed by a restore
NO_SENT = (
    "the record holds no mail you sent, so every sender reads as never answered: set owner_emails in"
    " logbook.json to your addresses before the mail is imported (RFC 0015 `direction`)"
)
UNSUBSCRIBE_KEYS = ("list_unsubscribe", "list-unsubscribe")  # where a mail line may hold the header
TABS = ("promotions", "social", "updates")  # the Gmail tabs counted per sender (`extra.gmail_category`)


Identity = tuple[int, int]  # (device, inode), either 0 where the system does not say


class CensusError(ValueError):
    """A census the arguments do not allow: one sentence, exit 2."""


# -- the files census --------------------------------------------------------------------------------------


@dataclass
class _Folder:
    files: int = 0
    bytes: int = 0
    newest: float | None = None  # the newest modified time of a file anywhere under it


@dataclass
class _Walk:
    roots: list[Path]
    zone: tzinfo
    files: int = 0
    bytes: int = 0
    folders: int = 0
    by_type: Counter[str] = field(default_factory=Counter)
    by_type_bytes: Counter[str] = field(default_factory=Counter)
    by_ext: Counter[str] = field(default_factory=Counter)
    by_ext_bytes: Counter[str] = field(default_factory=Counter)
    by_year: Counter[int | None] = field(default_factory=Counter)
    by_year_bytes: Counter[int | None] = field(default_factory=Counter)
    skipped: Counter[str] = field(default_factory=Counter)
    by_size: dict[int, list[tuple[int, tuple[str, ...], float, Identity]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    tree: dict[tuple[int, tuple[str, ...]], _Folder] = field(default_factory=dict)
    linked: set[Identity] = field(default_factory=set)  # files with more than one name, seen once
    largest: list[tuple[int, int, tuple[str, ...], float]] = field(
        default_factory=list
    )  # a heap, smallest first


def roots_of(paths: Sequence[Path], record: Path) -> list[Path]:
    """The folders to walk, each resolved once (the owner named it, so a link given here is followed to
    its folder, and only there), in the order given, a folder inside another given one left out. A
    folder that does not exist, is not a folder, or is the record or inside it is refused."""
    if not paths:
        raise CensusError("name at least one folder to count")
    home = Path(os.path.realpath(record))
    found: list[Path] = []
    for i, given in enumerate(paths, 1):
        which = f"PATH {i} of {len(paths)}"  # never the path itself: the terminal gets no name
        path = given.expanduser()
        if not path.is_dir():
            raise CensusError(f"{which} is not a folder")
        real = Path(os.path.realpath(path))
        if _same_or_inside(real, home) or _holds(real, record):
            raise CensusError(
                f"{which} is the record or inside it; the census counts your files, not the record"
            )
        found.append(real)
    unique = list(dict.fromkeys(found))
    return [
        real for real in unique if not any(real != other and _same_or_inside(real, other) for other in unique)
    ]


def _holds(path: Path, record: Path) -> bool:
    """Whether `path` or a folder above it is the record, by device and inode: on a disk that folds
    case, `~/LOGBOOK` is the record at `~/Logbook` though the two paths differ."""
    mine = _identity(record)
    return mine is not None and any(_identity(folder) == mine for folder in (path, *path.parents))


def _posix(parts: Sequence[str]) -> str:
    """A path in the report, relative to its folder and spelled with `/` on every system; `.` for the
    folder itself."""
    return PurePosixPath(*parts).as_posix() if parts else "."


def _same_or_inside(path: Path, folder: Path) -> bool:
    """`path` is `folder` or under it, by parts and folding case where the system does (pathlib)."""
    return path == folder or folder in path.parents


def census_files(lb: Logbook, paths: Sequence[Path], now: datetime | None = None) -> dict[str, Any]:
    """The files report of the folders `paths` (see the module's docstring). Nothing in them is
    written; the record is read for its folder and its zone and nothing else."""
    now = now or datetime.now(UTC)
    roots = roots_of(paths, lb.root)
    walk = _Walk(roots, _zone(lb))
    record = _identity(lb.root)
    home = Path(os.path.realpath(lb.root))
    for n, root in enumerate(roots):
        _walk(walk, n, root, record, home)
    duplicates, hard_links = _duplicates(walk)
    if hard_links:
        walk.skipped["hard_links"] += hard_links
    untouched = _untouched(walk, now)
    largest = sorted(walk.largest, key=lambda item: (-item[0], item[1], item[2]))
    return {
        "census": "files",
        "version": VERSION,
        "made_at": _stamp(now),
        "tier": FILES_TIER,
        "roots": [{"n": n + 1, "path": str(root)} for n, root in enumerate(roots)],
        "settings": {"largest": LARGEST, "untouched_days": UNTOUCHED_DAYS},
        "totals": {"files": walk.files, "bytes": walk.bytes, "folders": walk.folders},
        "by_type": _rows("type", walk.by_type, walk.by_type_bytes),
        "by_extension": _rows("extension", walk.by_ext, walk.by_ext_bytes),
        "by_year": sorted(
            (
                {"year": year, "files": walk.by_year[year], "bytes": walk.by_year_bytes[year]}
                for year in walk.by_year
            ),
            key=lambda row: (row["year"] is None, row["year"] or 0),
        ),
        "duplicates": {
            "sets": len(duplicates),
            "files": sum(len(d["files"]) for d in duplicates),
            "spare_bytes": sum(d["bytes"] * (len(d["files"]) - 1) for d in duplicates),
            "list": duplicates,
        },
        "largest": [
            {"root": n + 1, "path": _posix(parts), "bytes": size, "modified": _day(mtime, walk.zone)}
            for size, n, parts, mtime in largest
        ],
        "untouched": untouched,
        "skipped": dict(sorted(walk.skipped.items())),
        "changed": {"moved": 0, "renamed": 0, "deleted": 0, "written": 0},
    }


def _zone(lb: Logbook) -> tzinfo:
    """The record's zone, for the year a file was modified; UTC when the record names none or this
    machine's zone database lacks it."""
    name = lb.meta.get("timezone")
    try:
        return ZoneInfo(name) if isinstance(name, str) and name else UTC
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def _identity(path: Path) -> Identity | None:
    """(device, inode) of a folder, to know the record when the walk meets it under another name."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_dev, st.st_ino) if st.st_ino else None


def _walk(walk: _Walk, n: int, root: Path, record: Identity | None, home: Path) -> None:
    """One root, depth first, from an explicit stack (no recursion limit). Only entries the folder
    lists are visited, by their names joined to the folder's path, and a link is never followed: the
    walk cannot reach a path that is not under `root`."""
    stack: list[tuple[Path, tuple[str, ...], Identity]] = [(root, (), (0, 0))]
    walk.tree[(n, ())] = _Folder()
    disk = os.stat(root).st_dev
    while stack:
        folder, parts, listed = stack.pop()
        walk.folders += 1
        try:
            if parts and not _still(folder, listed, stat.S_ISDIR):
                walk.skipped["changed_during_census"] += 1  # replaced since it was listed: not entered
                continue
            with os.scandir(folder) as listing:
                entries = sorted(listing, key=lambda e: e.name)
        except OSError:
            walk.skipped["unreadable_folders"] += 1
            continue
        for entry in entries:
            here = (*parts, entry.name)
            try:
                if entry.is_symlink() or _is_junction(entry):
                    walk.skipped["links"] += 1
                elif entry.is_dir(follow_symlinks=False):
                    if _skipped(entry.name, parts):
                        walk.skipped["system_folders"] += 1
                    elif _is_record(Path(entry.path), record, home):
                        walk.skipped["record"] += 1
                    else:
                        st = os.lstat(entry.path)  # the folder's own device and flags
                        if disk and st.st_dev and st.st_dev != disk:
                            walk.skipped["other_disk"] += 1  # a disk mounted inside: not the folder given
                        elif _not_local(st):
                            walk.skipped["not_local"] += 1  # listing it would fetch it
                        else:
                            walk.tree[(n, here)] = _Folder()
                            stack.append((Path(entry.path), here, (st.st_dev, st.st_ino)))
                elif entry.is_file(follow_symlinks=False):
                    if entry.name.casefold() in SKIP_FILES:
                        walk.skipped["system_files"] += 1
                    else:
                        st = entry.stat(follow_symlinks=False)
                        if not st.st_nlink:  # Windows' listing says nothing of links or devices
                            st = os.lstat(entry.path)
                        _count(walk, n, here, st, (st.st_dev, st.st_ino or entry.inode()))
                else:
                    walk.skipped["special"] += 1  # a FIFO, a socket, a device: never opened
            except OSError:
                walk.skipped["unreadable_files"] += 1


def _not_local(st: os.stat_result) -> bool:
    """Whether the bytes are elsewhere, and reading them would make the system fetch them: an iCloud
    file or folder evicted from this Mac, a OneDrive or Google Drive file on demand, an offline file."""
    return bool(getattr(st, "st_flags", 0) & SF_DATALESS) or bool(
        getattr(st, "st_file_attributes", 0) & NOT_LOCAL_ATTRIBUTES
    )


def _same(listed: Identity, st: os.stat_result) -> bool:
    """Whether `st` is the entry the listing saw: each of the device and the inode equal wherever both
    sides know it (Windows' listing may give 0 for either)."""
    return all(not a or not b or a == b for a, b in zip(listed, (st.st_dev, st.st_ino), strict=True))


def _is_record(path: Path, record: Identity | None, home: Path) -> bool:
    """The record met inside a walked folder: by device and inode, else (a system without inodes) by
    its path, which the walk built from a real root without following a link."""
    return _identity(path) == record if record is not None else path == home


def _still(path: Path, listed: Identity, is_kind: Callable[[int], bool]) -> bool:
    """Whether `path` is still, without following a link, what the listing saw: the same kind, the
    same device and inode. A folder swapped for a link between the listing and the descent is not
    entered."""
    st = os.lstat(path)
    return is_kind(st.st_mode) and _same(listed, st)


def _skipped(name: str, parts: tuple[str, ...]) -> bool:
    """A folder the walk does not enter: one of `SKIP_FOLDERS` anywhere, by its name with case folded,
    or one of `SKIP_TOP` directly inside a given folder (a home's `Library` is the system's, a
    `library` of books further down is the owner's), or Claude's folder under an application folder."""
    folded = name.casefold()
    return (
        folded in SKIP_FOLDERS
        or (not parts and folded in SKIP_TOP)
        or (folded == CLAUDE and bool(parts) and parts[-1].casefold() in CLAUDE_PARENTS)
    )


def _is_junction(entry: os.DirEntry[str]) -> bool:
    """A Windows junction (a mount point a link-like folder can be): never followed."""
    check = getattr(entry, "is_junction", None)
    return bool(check()) if check is not None else False


def _count(walk: _Walk, n: int, parts: tuple[str, ...], st: os.stat_result, listed: Identity) -> None:
    size, mtime = st.st_size, st.st_mtime
    if st.st_nlink > 1 and all(listed):
        if listed in walk.linked:
            walk.skipped["hard_links"] += 1  # a second name of a file already counted
            return
        walk.linked.add(listed)
    walk.files += 1
    walk.bytes += size
    ext = _extension(parts[-1])
    kind = TYPE_OF.get(ext.lstrip("."), "none" if not ext else "other")
    walk.by_type[kind] += 1
    walk.by_type_bytes[kind] += size
    walk.by_ext[ext or "(none)"] += 1
    walk.by_ext_bytes[ext or "(none)"] += size
    year = _year(mtime, walk.zone)
    walk.by_year[year] += 1
    walk.by_year_bytes[year] += size
    if _not_local(st):
        walk.skipped["not_local"] += 1  # counted from its metadata; its bytes are never asked for
    else:
        walk.by_size[size].append((n, parts, mtime, listed))
    folder = walk.tree[(n, parts[:-1])]
    folder.files += 1
    folder.bytes += size
    folder.newest = mtime if folder.newest is None else max(folder.newest, mtime)
    item = (size, n, parts, mtime)
    if len(walk.largest) < LARGEST:
        heapq.heappush(walk.largest, item)
    elif item > walk.largest[0]:
        heapq.heapreplace(walk.largest, item)


def _extension(name: str) -> str:
    """The last suffix, lower case (`.JPG` is `.jpg`); a dot file (`.profile`) has none."""
    suffix = PurePath(name).suffix
    return suffix.lower() if suffix and suffix != name else ""


def _duplicates(walk: _Walk) -> tuple[list[dict[str, Any]], int]:
    """Sets of two or more files with the same bytes: hashed only where a size is shared, an empty
    file never. The same file reached by two names (a hard link) is one file, counted apart."""
    by_digest: dict[str, list[tuple[int, tuple[str, ...]]]] = defaultdict(list)
    sizes: dict[str, int] = {}
    hard_links = 0
    for size, found in walk.by_size.items():
        if size == 0 or len(found) < 2:
            continue
        seen: set[tuple[int, int]] = set()
        for n, parts, _mtime, listed in found:
            digest = _digest(walk.roots[n].joinpath(*parts), size, listed, walk)
            if digest is None:
                continue
            hexdigest, identity = digest
            if identity is not None and identity in seen:
                hard_links += 1
                continue
            if identity is not None:
                seen.add(identity)
            by_digest[hexdigest].append((n, parts))
            sizes[hexdigest] = size
    sets: list[dict[str, Any]] = [
        {
            "sha256": hexdigest,
            "bytes": sizes[hexdigest],
            "files": [{"root": n + 1, "path": _posix(parts)} for n, parts in sorted(found)],
        }
        for hexdigest, found in by_digest.items()
        if len(found) > 1
    ]
    sets.sort(key=lambda d: (-d["bytes"] * (len(d["files"]) - 1), d["sha256"]))
    return sets, hard_links


def _open(path: Path) -> int:
    """A file descriptor for reading `path` and nothing else: read-only, never through a link that
    appeared since the walk (O_NOFOLLOW), never blocking on a FIFO that replaced a file (O_NONBLOCK),
    never a terminal made the controlling one (O_NOCTTY), never inherited (O_CLOEXEC)."""
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_NOFOLLOW", "O_NONBLOCK", "O_NOCTTY", "O_CLOEXEC"):
        flags |= getattr(os, name, 0)
    return os.open(path, flags)


def _digest(path: Path, size: int, listed: Identity, walk: _Walk) -> tuple[str, Identity | None] | None:
    """The SHA-256 of the file's bytes, read `CHUNK` at a time, and its (device, inode); None when it
    cannot be read, is no longer a regular file, is no longer the file the walk listed (another
    inode), or changed size since the walk (each counted)."""
    try:
        fd = _open(path)
    except OSError:
        walk.skipped["unreadable_files"] += 1
        return None
    with open(fd, "rb", closefd=True) as fh:
        st = os.fstat(fh.fileno())
        if not stat.S_ISREG(st.st_mode):
            walk.skipped["special"] += 1
            return None
        if not _same(listed, st):
            walk.skipped["changed_during_census"] += 1
            return None
        sha = hashlib.sha256()
        read = 0
        try:
            while chunk := fh.read(CHUNK):
                sha.update(chunk)
                read += len(chunk)
        except OSError:
            walk.skipped["unreadable_files"] += 1
            return None
    if read != size:
        walk.skipped["changed_during_census"] += 1
        return None
    return sha.hexdigest(), ((st.st_dev, st.st_ino) if st.st_ino else None)


def _untouched(walk: _Walk, now: datetime) -> list[dict[str, Any]]:
    """The highest folders under which no file changed for `UNTOUCHED_DAYS` days, by bytes; a folder
    inside a listed one is not listed again, and a root is listed only as a whole."""
    for key in sorted(walk.tree, key=lambda k: -len(k[1])):
        n, parts = key
        if not parts:
            continue
        child, parent = walk.tree[key], walk.tree[(n, parts[:-1])]
        parent.files += child.files
        parent.bytes += child.bytes
        if child.newest is not None:
            parent.newest = child.newest if parent.newest is None else max(parent.newest, child.newest)
    cut = (now - timedelta(days=UNTOUCHED_DAYS)).timestamp()
    stale = {key for key, folder in walk.tree.items() if folder.newest is not None and folder.newest < cut}
    listed = [key for key in stale if not any((key[0], key[1][:i]) in stale for i in range(len(key[1])))]
    rows: list[dict[str, Any]] = [
        {
            "root": n + 1,
            "path": _posix(parts),
            "files": walk.tree[(n, parts)].files,
            "bytes": walk.tree[(n, parts)].bytes,
            "newest": _day(walk.tree[(n, parts)].newest or 0.0, walk.zone),
        }
        for n, parts in listed
    ]
    rows.sort(key=lambda row: (-row["bytes"], row["root"], row["path"]))
    return rows


# -- reading the record ------------------------------------------------------------------------------------


@dataclass
class _Read:
    lines: int = 0
    tier: int | None = None
    left_out: Counter[str] = field(default_factory=Counter)


def _standing(
    lb: Logbook, kind: str, read: _Read, max_tier: int, source: str | None = None
) -> Iterator[Line]:
    """Every standing line of `kind` (and `source`) the census may read: retracted and superseded
    lines left out, a sealed one it cannot open and one above `max_tier` counted and left out."""
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        superseded = idx.superseded(kind)
        for line in idx.of_kind(kind, source=source):
            id_ = str(line.get("id"))
            if id_ in retracted or id_ in superseded:
                continue
            if is_sealed(line):
                read.left_out["sealed"] += 1
                continue
            tier = line.get("tier")
            if not isinstance(tier, int) or tier > max_tier:
                read.left_out["above_tier"] += 1
                continue
            if not isinstance(line.get("payload"), dict):
                read.left_out["unreadable"] += 1
                continue
            read.lines += 1
            read.tier = tier if read.tier is None else max(read.tier, tier)
            yield line


def _instant(text: object) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None


def _email(value: object) -> str | None:
    """The lower-cased address of a `{email, name?}` object, or None."""
    if isinstance(value, Mapping):
        email = value.get("email")
        if isinstance(email, str) and "@" in email:
            return email.strip().lower()
    return None


def _addresses(payload: Mapping[str, Any]) -> Iterator[str]:
    for key in ("to", "cc", "bcc"):
        found = payload.get(key)
        for person in found if isinstance(found, list) else []:
            if email := _email(person):
                yield email


def _listed(payload: Mapping[str, Any]) -> bool:
    """Whether the line says its message had a List-Unsubscribe header (`extra.list.unsubscribe`, RFC
    0015, amendment of 2026-10-20)."""
    extra = payload.get("extra")
    found = extra.get("list") if isinstance(extra, Mapping) else None
    return isinstance(found, Mapping) and found.get("unsubscribe") is True


def _tab(payload: Mapping[str, Any]) -> str | None:
    """Gmail's inbox tab the line names (`extra.gmail_category`), when it is one of `TABS`."""
    extra = payload.get("extra")
    tab = extra.get("gmail_category") if isinstance(extra, Mapping) else None
    return tab if tab in TABS else None


def _unsubscribe(payload: Mapping[str, Any]) -> bool | None:
    """Whether the line holds a List-Unsubscribe header: True when it does, None when it cannot say
    (`extra.list.unsubscribe` on a line written since RFC 0015's amendment of 2026-10-20; before it a
    producer may have kept the header under `extra`, or a `headers` object)."""
    if _listed(payload):
        return True
    extra = payload.get("extra")
    places = [payload, extra if isinstance(extra, Mapping) else {}]
    for place in list(places):
        headers = place.get("headers")
        if isinstance(headers, Mapping):
            places.append(headers)
    for place in places:
        for key, value in place.items():
            if isinstance(key, str) and key.casefold() in UNSUBSCRIBE_KEYS and value:
                return True
    return None


@dataclass
class _Sender:
    messages: int = 0
    bytes: int = 0
    first: datetime | None = None
    last: datetime | None = None
    names: Counter[str] = field(default_factory=Counter)
    threads: set[str] = field(default_factory=set)
    newsletter: bool = False
    listed: int = 0  # mails with `extra.list.unsubscribe`
    tabs: Counter[str] = field(default_factory=Counter)  # mails per Gmail tab of `TABS`


def census_senders(lb: Logbook, max_tier: int = MAX_TIER, now: datetime | None = None) -> dict[str, Any]:
    """The senders report: every address the owner's received mail came from, by count and last seen,
    whether the owner ever wrote to it (a sent line with it under `to`, `cc` or `bcc`) or answered in
    one of its threads, whether its lines hold a List-Unsubscribe header, and how many of its mails carry
    `extra.list.unsubscribe` and sit in each of the `TABS`."""
    now = now or datetime.now(UTC)
    read = _Read()
    senders: dict[str, _Sender] = defaultdict(_Sender)
    written: dict[str, datetime | None] = {}
    sent_threads: set[str] = set()
    received = sent = holding = 0
    for line in _standing(lb, "mail", read, max_tier):
        payload = line["payload"]
        at = _instant(line.get("at"))
        thread = payload.get("thread")
        if payload.get("direction") == "sent":
            sent += 1
            if isinstance(thread, str):
                sent_threads.add(thread)
            for to in _addresses(payload):
                before = written.get(to)
                written[to] = at if before is None or (at is not None and at > before) else before
            continue
        email = _email(payload.get("from"))
        if email is None:
            read.left_out["no_sender"] += 1
            continue
        received += 1
        sender = senders[email]
        sender.messages += 1
        size = payload.get("size")
        sender.bytes += size if isinstance(size, int) and size > 0 else 0
        if at is not None:
            sender.first = at if sender.first is None else min(sender.first, at)
            sender.last = at if sender.last is None else max(sender.last, at)
        name = (payload.get("from") or {}).get("name")
        if isinstance(name, str) and name.strip():
            sender.names[name.strip()] += 1
        if isinstance(thread, str):
            sender.threads.add(thread)
        if _unsubscribe(payload):
            sender.newsletter = True
            holding += 1
        if _listed(payload):
            sender.listed += 1
        if (tab := _tab(payload)) is not None:
            sender.tabs[tab] += 1
    rows: list[dict[str, Any]] = [
        {
            "email": email,
            "name": s.names.most_common(1)[0][0] if s.names else None,
            "messages": s.messages,
            "bytes": s.bytes,
            "first_seen": _stamp(s.first) if s.first else None,
            "last_seen": _stamp(s.last) if s.last else None,
            "threads": len(s.threads),
            "threads_answered": len(s.threads & sent_threads),
            "written_to": email in written,
            "last_written": _stamp(w) if (w := written.get(email)) else None,
            "answered": email in written or bool(s.threads & sent_threads),
            "newsletter": True if s.newsletter else None,
            "list_unsubscribe": s.listed,
            "tabs": {tab: s.tabs[tab] for tab in TABS},
        }
        for email, s in senders.items()
    ]
    rows.sort(key=lambda row: (-row["messages"], row["email"]))
    never = [row for row in rows if not row["answered"]]
    letters = [row for row in rows if row["newsletter"]]
    return {
        "census": "senders",
        "version": VERSION,
        "made_at": _stamp(now),
        "tier": read.tier,
        "max_tier": max_tier,
        "totals": {
            "lines": read.lines,
            "received": received,
            "sent": sent,
            "senders": len(rows),
            "never_answered": len(never),
        },
        "answered_note": None if sent else NO_SENT,
        "newsletters": {
            "held": holding > 0,
            "lines_with_header": holding,
            "senders": len(letters),
            "note": None
            if holding
            else "no mail line holds a List-Unsubscribe header (none written before 20 October 2026 does);"
            " newsletters are unknown",
        },
        "lists_and_tabs": {
            "list_unsubscribe": sum(row["list_unsubscribe"] for row in rows),
            **{tab: sum(row["tabs"][tab] for row in rows) for tab in TABS},
        },
        "senders": rows,
        "left_out": dict(sorted(read.left_out.items())),
    }


@dataclass
class _DriveFile:
    name: str | None = None
    mime_type: str | None = None
    path: tuple[str, ...] = ()
    first: datetime | None = None
    last: datetime | None = None
    lines: int = 0
    activities: Counter[str] = field(default_factory=Counter)
    by_owner: bool = False
    shares: dict[str, str] = field(default_factory=dict)  # who → the last change, added or removed
    gone: str | None = None  # trash or delete, while no restore came after it


def _share_key(share: Mapping[str, Any]) -> str | None:
    target = share.get("with")
    if not isinstance(target, Mapping) or not target:
        return None
    kind, value = next(iter(sorted(target.items())))
    if kind == "owner":
        return None  # the owner's own access is no share
    return f"{kind}:{value}" if isinstance(value, str) else str(kind)


def census_drive(lb: Logbook, max_tier: int = MAX_TIER, now: datetime | None = None) -> dict[str, Any]:
    """The Drive report: every file the record's Drive lines name, by type, folder and year of its last
    activity; the ones untouched for `UNTOUCHED_DAYS` days, the shared (a share added and not removed
    since, by the lines) and the trashed or deleted (by the last such activity)."""
    now = now or datetime.now(UTC)
    read = _Read()
    files: dict[str, _DriveFile] = defaultdict(_DriveFile)
    ordered: list[tuple[datetime, int, str, Mapping[str, Any]]] = []
    for line in _standing(lb, "event", read, max_tier, source=DRIVE_SOURCE):
        payload = line["payload"]
        extra = payload.get("extra")
        file = extra.get("file") if isinstance(extra, Mapping) else None
        file_id = file.get("id") if isinstance(file, Mapping) else None
        at = _instant(payload.get("modified_at")) or _instant(line.get("end")) or _instant(line.get("at"))
        if not isinstance(file_id, str) or not file_id or at is None:
            read.left_out["no_file"] += 1
            continue
        seq = line.get("seq")
        ordered.append((at, seq if isinstance(seq, int) else 0, file_id, extra))
    for at, _seq, file_id, extra in sorted(ordered, key=lambda item: (item[0], item[1])):
        f = files[file_id]
        meta = extra["file"]
        f.lines += 1
        if isinstance(meta.get("name"), str):
            f.name = meta["name"]
        if isinstance(meta.get("mime_type"), str):
            f.mime_type = meta["mime_type"]
        path = meta.get("path")
        if isinstance(path, list) and all(isinstance(p, str) for p in path):
            f.path = tuple(path)
        f.first = at if f.first is None else min(f.first, at)
        f.last = at if f.last is None else max(f.last, at)
        activity = extra.get("activity")
        count = extra.get("count")
        if isinstance(activity, str):
            f.activities[activity] += count if isinstance(count, int) and count > 0 else 1
            if activity in GONE:
                f.gone = activity
            elif activity == "restore":
                f.gone = None
        f.by_owner = f.by_owner or extra.get("by_owner") is True
        shares = extra.get("shares")
        for share in shares if isinstance(shares, list) else []:
            if isinstance(share, Mapping) and (key := _share_key(share)):
                f.shares[key] = str(share.get("change") or "")
    cut = now - timedelta(days=UNTOUCHED_DAYS)
    rows: list[dict[str, Any]] = [
        {
            "id": file_id,
            "name": f.name,
            "mime_type": f.mime_type,
            "folder": _posix(f.path) if f.path else None,
            "lines": f.lines,
            "activities": sum(f.activities.values()),
            "by_activity": dict(sorted(f.activities.items())),
            "first_activity": _stamp(f.first) if f.first else None,
            "last_activity": _stamp(f.last) if f.last else None,
            "by_owner": f.by_owner,
            "shared_with": sorted(
                {key.split(":", 1)[0] for key, change in f.shares.items() if change != "removed"}
            ),
            "gone": f.gone,
            "untouched": f.gone is None and f.last is not None and f.last < cut,
        }
        for file_id, f in files.items()
    ]
    rows.sort(key=lambda row: (-row["activities"], row["id"]))
    standing = [row for row in rows if row["gone"] is None]
    return {
        "census": "drive",
        "version": VERSION,
        "made_at": _stamp(now),
        "tier": read.tier,
        "max_tier": max_tier,
        "settings": {"untouched_days": UNTOUCHED_DAYS},
        "totals": {
            "lines": read.lines,
            "files": len(rows),
            "untouched": sum(1 for row in rows if row["untouched"]),
            "shared": sum(1 for row in standing if row["shared_with"]),
            "gone": len(rows) - len(standing),
        },
        "by_type": _count_rows("mime_type", (row["mime_type"] or "(unknown)" for row in standing)),
        "by_folder": _count_rows("folder", (row["folder"] or "(unknown)" for row in standing)),
        "by_year": sorted(
            _count_rows("year", (int(row["last_activity"][:4]) for row in standing if row["last_activity"])),
            key=lambda row: row["year"],
        ),
        "files": rows,
        "left_out": dict(sorted(read.left_out.items())),
    }


# -- the report --------------------------------------------------------------------------------------------


def _rows(key: str, files: Counter[Any], sizes: Counter[Any]) -> list[dict[str, Any]]:
    return sorted(
        ({key: name, "files": files[name], "bytes": sizes[name]} for name in files),
        key=lambda row: (-row["bytes"], -row["files"], str(row[key])),
    )


def _count_rows(key: str, values: Iterable[Any]) -> list[dict[str, Any]]:
    found = Counter(values)
    return sorted(
        ({key: value, "files": n} for value, n in found.items()), key=lambda r: (-r["files"], str(r[key]))
    )


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _year(mtime: float, zone: tzinfo) -> int | None:
    """The year of a modified time; None for one no calendar holds (a damaged or foreign disk)."""
    try:
        return datetime.fromtimestamp(mtime, zone).year
    except (OverflowError, ValueError, OSError):
        return None


def _day(mtime: float, zone: tzinfo) -> str | None:
    try:
        return datetime.fromtimestamp(mtime, zone).date().isoformat()
    except (OverflowError, ValueError, OSError):
        return None


def size_text(n: int) -> str:
    """Bytes as a person reads them: `512 B`, `1.5 KB`, `3.2 GB` (powers of 1000, as the Finder)."""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1000 or unit == "TB":
            return f"{int(value)} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1000
    return f"{n} B"  # pragma: no cover


MARKDOWN = frozenset("\\`*_[]()<>!&|#~")  # what a viewer reads as markup: a link, an image, a tag


def _cell(text: object) -> str:
    """A name as plain text in the Markdown: every character a viewer reads as markup escaped, so a
    name like `<img src=…>` or `[x](https://…)` shows as written and fetches nothing, and a line break
    or a `|` keeps the row whole."""
    plain = str(text).replace("\r", " ").replace("\n", " ")
    return "".join(f"\\{c}" if c in MARKDOWN else c for c in plain)


def _table(head: Sequence[str], rows: Iterable[Sequence[object]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return out if len(out) > 2 else ["(none)"]


def _more(items: Sequence[Any]) -> list[str]:
    return ["", f"… and {len(items) - TOP:,} more in the JSON report."] if len(items) > TOP else []


def markdown(report: Mapping[str, Any]) -> str:
    """The report as Markdown, for the owner to read; every name it holds is in here."""
    census = report["census"]
    head = [
        f"# Hold census: {census}",
        "",
        f"Made {report['made_at']} by `logbook lab hold census {census}` (Hold v0, RFC 0042 draft). "
        f"Tier {report['tier'] if report['tier'] is not None else 'none'}: this report stays on this"
        " machine. "
        "Nothing was moved, renamed, deleted or written anywhere but here.",
        "",
    ]
    body = {"files": _files_md, "senders": _senders_md, "drive": _drive_md}[census](report)
    return "\n".join(head + body).rstrip("\n") + "\n"


def _files_md(r: Mapping[str, Any]) -> list[str]:
    t = r["totals"]
    out = [
        f"{t['files']:,} files, {size_text(t['bytes'])}, in {t['folders']:,} folders.",
        "",
        "## Folders counted",
        "",
        *_table(("#", "folder"), ((root["n"], root["path"]) for root in r["roots"])),
        "",
        "## By type",
        "",
        *_table(
            ("type", "files", "size"),
            ((x["type"], f"{x['files']:,}", size_text(x["bytes"])) for x in r["by_type"]),
        ),
        "",
        "## By extension",
        "",
        *_table(
            ("extension", "files", "size"),
            ((x["extension"], f"{x['files']:,}", size_text(x["bytes"])) for x in r["by_extension"][:TOP]),
        ),
        *_more(r["by_extension"]),
        "",
        "## By year last modified",
        "",
        *_table(
            ("year", "files", "size"),
            ((x["year"] or "unknown", f"{x['files']:,}", size_text(x["bytes"])) for x in r["by_year"]),
        ),
        "",
    ]
    d = r["duplicates"]
    out += [
        "## Duplicates",
        "",
        f"{d['sets']:,} sets of identical files, {d['files']:,} files;"
        f" {size_text(d['spare_bytes'])} held more than once.",
        "",
    ]
    for dup in d["list"][:TOP]:
        out.append(f"- {size_text(dup['bytes'])} × {len(dup['files'])}, sha256 `{dup['sha256'][:12]}`")
        out += [f"  - {_cell(f['root'])}: {_cell(f['path'])}" for f in dup["files"]]
    out += _more(d["list"])
    out += [
        "",
        f"## The {r['settings']['largest']} largest",
        "",
        *_table(
            ("#", "file", "size", "modified"),
            ((x["root"], x["path"], size_text(x["bytes"]), x["modified"] or "unknown") for x in r["largest"]),
        ),
        "",
        f"## Untouched for {r['settings']['untouched_days']} days",
        "",
        *_table(
            ("#", "folder", "files", "size", "newest file"),
            (
                (x["root"], x["path"], f"{x['files']:,}", size_text(x["bytes"]), x["newest"] or "unknown")
                for x in r["untouched"][:TOP]
            ),
        ),
        *_more(r["untouched"]),
        "",
        "## Skipped",
        "",
        *_table(("what", "count"), sorted(r["skipped"].items())),
    ]
    return out


def _senders_md(r: Mapping[str, Any]) -> list[str]:
    t, rows = r["totals"], r["senders"]
    n = r["newsletters"]

    def table(found: Sequence[Mapping[str, Any]]) -> list[str]:
        return _table(
            ("sender", "name", "messages", "last seen", "answered"),
            (
                (
                    x["email"],
                    x["name"] or "",
                    x["messages"],
                    (x["last_seen"] or "")[:10],
                    "yes" if x["answered"] else "no",
                )
                for x in found[:TOP]
            ),
        ) + _more(found)

    by_last = sorted(rows, key=lambda x: (x["last_seen"] or "", x["email"]), reverse=True)
    never = [x for x in rows if not x["answered"]]
    letters = [x for x in rows if x["newsletter"]]
    return [
        f"{t['lines']:,} mail lines read: {t['received']:,} received from {t['senders']:,} senders,"
        f" {t['sent']:,} sent. {t['never_answered']:,} senders never answered.",
        *(["", f"Note: {r['answered_note']}."] if r["answered_note"] else []),
        "",
        "## By count",
        "",
        *table(rows),
        "",
        "## By last seen",
        "",
        *table(by_last),
        "",
        "## Never answered",
        "",
        *table(never),
        "",
        "## Newsletters",
        "",
        *(table(letters) if n["held"] else [n["note"]]),
        "",
        "## Lists and tabs",
        "",
        *_lists_and_tabs(rows),
        "",
        "## Left out",
        "",
        *_table(("what", "count"), sorted(r["left_out"].items())),
    ]


def _lists_and_tabs(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Per sender with any: its mails with List-Unsubscribe and in each counted tab, most first."""
    found = [x for x in rows if x["list_unsubscribe"] or any(x["tabs"].values())]
    if not found:
        return [
            "No mail line says it came from a list or sits in Promotions, Social or Updates"
            " (lines written before 20 October 2026 say neither)."
        ]
    found = sorted(found, key=lambda x: (-x["list_unsubscribe"] - sum(x["tabs"].values()), x["email"]))
    return _table(
        ("sender", "List-Unsubscribe", "Promotions", "Social", "Updates"),
        ((x["email"], x["list_unsubscribe"], *(x["tabs"][tab] for tab in TABS)) for x in found[:TOP]),
    ) + _more(found)


def _drive_md(r: Mapping[str, Any]) -> list[str]:
    t, rows = r["totals"], r["files"]

    def table(found: Sequence[Mapping[str, Any]]) -> list[str]:
        return _table(
            ("file", "folder", "type", "activities", "last activity"),
            (
                (x["name"] or "(no name)", x["folder"] or "", x["mime_type"] or "", x["activities"],
                 (x["last_activity"] or "")[:10])
                for x in found[:TOP]
            ),
        ) + _more(found)  # fmt: skip

    return [
        f"{t['files']:,} files named by {t['lines']:,} Drive lines; {t['untouched']:,} untouched for"
        f" {r['settings']['untouched_days']} days, {t['shared']:,} shared, {t['gone']:,} trashed or deleted.",
        "",
        "The record holds a file only from the activity Drive reported since `sync drive` began: a file"
        " nobody touched since then is not here.",
        "",
        "## By type",
        "",
        *_table(("type", "files"), ((x["mime_type"], x["files"]) for x in r["by_type"][:TOP])),
        "",
        "## By folder",
        "",
        *_table(("folder", "files"), ((x["folder"], x["files"]) for x in r["by_folder"][:TOP])),
        "",
        "## By year of the last activity",
        "",
        *_table(("year", "files"), ((x["year"], x["files"]) for x in r["by_year"])),
        "",
        "## Most active",
        "",
        *table([x for x in rows if not x["gone"]]),
        "",
        "## Untouched",
        "",
        *table([x for x in rows if x["untouched"]]),
        "",
        "## Shared",
        "",
        *table([x for x in rows if x["shared_with"] and not x["gone"]]),
        "",
        "## Trashed or deleted",
        "",
        *table([x for x in rows if x["gone"]]),
        "",
        "## Left out",
        "",
        *_table(("what", "count"), sorted(r["left_out"].items())),
    ]


def write(root: Path, report: Mapping[str, Any]) -> tuple[Path, Path]:
    """The report as `state/hold/<census>.md` and `.json` in the record folder, each replacing the last
    in one step (written beside, then renamed over), readable by the owner alone where the system has
    modes. The only files a census writes."""
    folder = root.joinpath(*REPORTS.parts)
    for place in (folder.parent, folder):  # a link here would carry the names elsewhere: refused
        if place.is_symlink() or (place.exists() and not place.is_dir()):
            raise CensusError(
                f"{place.relative_to(root).as_posix()} in the record is not a plain folder; no report"
            )
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        os.chmod(folder, 0o700)  # a folder made before, by hand, is the owner's alone too
    census = report["census"]
    if census not in CENSUSES:
        raise CensusError(f"no census called {census!r}")
    written = (folder / f"{census}.md", folder / f"{census}.json")
    texts = (markdown(report), json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for path, text in zip(written, texts, strict=True):
        _replace(path, text.encode("utf-8", errors="backslashreplace"))  # a name no UTF-8 holds, escaped
    return written


def _replace(path: Path, data: bytes) -> None:
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)  # a part a crash left keeps no mode of its own: this one is made new
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    with open(fd, "wb", closefd=True) as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(part, path)


def summary(report: Mapping[str, Any], written: Sequence[Path]) -> dict[str, Any]:
    """What a census prints: counts and where the report is, never a name, a path inside a walked
    folder, or an address."""
    census = report["census"]
    out: dict[str, Any] = {
        "census": census,
        "made_at": report["made_at"],
        "tier": report["tier"],
        "report": {"markdown": str(written[0]), "json": str(written[1])},
        "totals": dict(report["totals"]),
    }
    if census == "files":
        out["roots"] = len(report["roots"])
        out["duplicates"] = {k: report["duplicates"][k] for k in ("sets", "files", "spare_bytes")}
        out["untouched_folders"] = len(report["untouched"])
        out["skipped"] = dict(report["skipped"])
        out["changed"] = dict(report["changed"])
    elif census == "senders":
        out["newsletters"] = {k: report["newsletters"][k] for k in ("held", "lines_with_header", "senders")}
        out["lists_and_tabs"] = dict(report["lists_and_tabs"])
        out["answered_note"] = report["answered_note"]
        out["left_out"] = dict(report["left_out"])
    else:
        out["left_out"] = dict(report["left_out"])
    return out


def summary_rows(s: Mapping[str, Any]) -> list[str]:
    """The summary as the lines `lab hold census` prints."""
    t, census = s["totals"], s["census"]
    if census == "files":
        d = s["duplicates"]
        first = (
            f"hold census files: {t['files']:,} files, {size_text(t['bytes'])}, in {t['folders']:,} folders"
            f" under {s['roots']} given; {d['sets']:,} duplicate sets"
            f" ({size_text(d['spare_bytes'])} held more than once);"
            f" {s['untouched_folders']:,} folders untouched for two years"
        )
        skipped = ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in sorted(s["skipped"].items()))
        rest = [f"skipped: {skipped}"] if skipped else []
    elif census == "senders":
        first = (
            f"hold census senders: {t['senders']:,} senders in {t['received']:,} received mails"
            f" ({t['sent']:,} sent); {t['never_answered']:,} never answered; newsletters "
            + (
                f"{s['newsletters']['senders']:,}"
                if s["newsletters"]["held"]
                else "unknown (no line holds the header)"
            )
        )
        lt = s["lists_and_tabs"]
        first += (
            f"; {lt['list_unsubscribe']:,} mails with List-Unsubscribe,"
            f" {sum(lt[tab] for tab in TABS):,} in Promotions, Social or Updates"
        )
        rest = [f"note: {s['answered_note']}"] if s.get("answered_note") else []
    else:
        first = (
            f"hold census drive: {t['files']:,} files in {t['lines']:,} Drive lines;"
            f" {t['untouched']:,} untouched for two years, {t['shared']:,} shared,"
            f" {t['gone']:,} trashed or deleted"
        )
        rest = []
    if census != "files" and s.get("left_out"):
        rest.append(
            "left out: " + ", ".join(f"{k.replace('_', ' ')} {v:,}" for k, v in sorted(s["left_out"].items()))
        )
    tier = s["tier"] if s["tier"] is not None else "none (nothing read)"
    return [
        first,
        *rest,
        f"report (tier {tier}; names stay in it): {s['report']['markdown']}",
        f"  and {s['report']['json']}; nothing was moved, renamed or deleted",
    ]


def run(lb: Logbook, census: str, paths: Sequence[Path] = (), max_tier: int = MAX_TIER) -> dict[str, Any]:
    """One census, its report written; the summary it prints."""
    if max_tier not in TIERS:
        raise CensusError(f"--tier must be one of {', '.join(map(str, TIERS))}")
    if census == "files":
        report = census_files(lb, paths)
    elif census == "senders":
        report = census_senders(lb, max_tier)
    elif census == "drive":
        report = census_drive(lb, max_tier)
    else:
        raise CensusError(f"no census called {census!r}")
    return summary(report, write(lb.root, report))
