"""`logbook backup DEST [--keep N] [--verify]`, `backup list DEST`, `backup restore SNAPSHOT TARGET`:
the record copied to another disk, verified there, and read back when the day comes.

A snapshot is `DEST/<owner_id>/<timestamp>/`, the record's files at their own paths: `logbook.json`,
every file under `logbook/`, `policy/`, `places.json`, `assets.json`, `attachments/` and `notes/`.
Never `index.sqlite` (a derived locator, rebuilt by the next reader; ADR 0007), never `inbox/` (copies
of exports, not the record), never `state/` (a sync watermark is bookkeeping; a restored record
syncs again from the start and appends nothing twice). The copy is pure Python and streams: a file
is read a chunk at a time, never whole, and nothing is shelled out to.

Hard links, as `rsync --link-dest` does it: a file whose size and modification time are those of the
same file in the previous snapshot is linked to it, not copied, so a snapshot of a record with
gigabytes of attachments costs the bytes that changed since the last one, and every snapshot is
still a complete record on its own: pruning one never touches another. A filesystem that refuses the
link (exFAT, a network share, a different volume) gets a copy. The copy is written under
`.<timestamp>.partial` and renamed into place only after it verifies, so a crash or a bad copy
leaves no directory that looks like a snapshot; `list` never shows a dotted directory.

Verified, every time: `Logbook.verify` runs on the copy (the files, never an index) and its head
must be the head `logbook.json` named when the copy began. A line appended during the copy makes
the files run ahead of the copied `logbook.json`; that copy does not verify, is removed, and the
owner is told to run again. `--verify` also hashes every attachment in the copy against its name
(SPEC §1.1: a verifier may; a file whose bytes do not match its name is an error).

Refused before anything is written: a destination inside the record, and one under a folder a sync
client owns, by `doctor.cloud_folder`'s detection (a backup there is on someone else's server, and
the client may evict it). `restore` copies a snapshot to a folder that does not exist or is empty —
never over anything, the record included — and verifies the result; it refuses the same folders and
a code checkout (never empty, so the rule above covers it), as `init` does.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from ..core import attachments
from ..core.store import Logbook
from . import doctor

META = "logbook.json"
#: the directories copied whole, every file under them (a name beginning with `.` left out: an
#: attachment being written is `.<digest>.<pid>.tmp` until it is renamed into place)
DIRECTORIES = ("logbook", "policy", attachments.DIR, "notes")
#: the files at the root copied when they exist
FILES = ("places.json", "assets.json")
PARTIAL = ".{name}.partial"
STAMP = "%Y-%m-%dT%H%M%SZ"  # a snapshot's name: UTC, sortable, no colon (Windows refuses one)
CHUNK = 1 << 20
CLOUD_REASON = (
    "a sync client keeps the backup on someone else's server and may evict it; back up to a plain"
    " local disk or a drive you plug in"
)


class BackupError(Exception):
    """Nothing was kept; the message says why."""


class Refused(BackupError):
    """The destination, target or record is one this command will not write to or copy (exit 2)."""


class Invalid(BackupError):
    """The copy was made and does not verify, or is not the record it was copied from (exit 1)."""


@dataclass(frozen=True)
class Result:
    """One snapshot written, or one restore done."""

    path: Path
    seq: int
    head: str
    files: int
    bytes: int  # the size of every file in the snapshot
    copied: int
    copied_bytes: int
    linked: int
    linked_to: Path | None  # the previous snapshot, when there was one to link against
    attachments_checked: int | None = None  # with `verify_attachments`: how many hashed to their name


@dataclass(frozen=True)
class Entry:
    """One snapshot as `list` sees it: what its `logbook.json` claims, not a verification."""

    path: Path
    seq: int | None
    head: str | None
    bytes: int
    new_bytes: int  # bytes of files not shared, by hard link, with an earlier snapshot
    error: str | None = None


def now() -> datetime:
    return datetime.now(UTC)


# -- what a snapshot holds -----------------------------------------------------------------------------------


def record_files(root: Path) -> list[PurePosixPath]:
    """The record's files, relative to `root`, `logbook.json` first and the rest in path order;
    never the index, the inbox, the watermarks or a temporary file."""
    found: list[PurePosixPath] = []
    for name in FILES:
        if (root / name).is_file():
            found.append(PurePosixPath(name))
    for name in DIRECTORIES:
        folder = root / name
        if folder.is_dir():
            found.extend(
                PurePosixPath(p.relative_to(root).as_posix())
                for p in folder.rglob("*")
                if p.is_file() and not p.name.startswith(".")
            )
    return [PurePosixPath(META), *sorted(found)]


def _at(root: Path, rel: PurePosixPath) -> Path:
    return root.joinpath(*rel.parts)


# -- refusals ------------------------------------------------------------------------------------------------


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path.absolute()


def check_destination(dest: Path, root: Path | None, env: Mapping[str, str]) -> None:
    """Refused when `dest` is inside the record at `root`, under a sync client's folder, or an
    existing path that is not a directory."""
    if dest.exists() and not dest.is_dir():
        raise Refused(f"{dest} is not a directory")
    if root is not None:
        target, record = _resolved(dest), _resolved(root)
        if target == record or record in target.parents:
            raise Refused(f"{dest} is inside the record at {root}; a backup goes to another disk")
    service = doctor.cloud_folder(dest, env)
    if service is not None:
        raise Refused(f"{dest} is under {service}, a sync client's folder: {CLOUD_REASON}")


# -- the copy ------------------------------------------------------------------------------------------------


def copy_file(src: Path, dst: Path) -> None:
    """`src` to `dst` a chunk at a time, with its modification time, so the next snapshot can tell
    it is unchanged."""
    with src.open("rb") as fh_in, dst.open("wb") as fh_out:
        while chunk := fh_in.read(CHUNK):
            fh_out.write(chunk)
    shutil.copystat(src, dst)


def _unchanged(live: os.stat_result, previous: Path) -> bool:
    try:
        old = previous.stat()
    except OSError:
        return False
    return old.st_size == live.st_size and old.st_mtime_ns == live.st_mtime_ns


def _copy_tree(
    source: Path, files: list[PurePosixPath], target: Path, previous: Path | None
) -> tuple[int, int, int, int]:
    """Every file of `files` from `source` into `target`, a hard link to `previous` when it holds
    the same file unchanged, else a copy. Returns (copied, copied bytes, linked, total bytes)."""
    copied = copied_bytes = linked = total = 0
    for rel in files:
        src, dst = _at(source, rel), _at(target, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        live = src.stat()
        total += live.st_size
        if previous is not None and _unchanged(live, _at(previous, rel)):
            try:
                os.link(_at(previous, rel), dst)
            except OSError:  # another volume, or a filesystem without hard links: a copy then
                pass
            else:
                linked += 1
                continue
        copy_file(src, dst)
        copied += 1
        copied_bytes += live.st_size
    return copied, copied_bytes, linked, total


def _verify_copy(copy: Path, expected_head: str | None, check_attachments: bool) -> tuple[int, str, int]:
    """(seq, head, attachments checked) of the copy at `copy`, by the files alone; Invalid when
    it does not verify, when its head is not `expected_head`, or, with `check_attachments`, when a
    file in its store does not hash to its name."""
    seq, head, errors = Logbook(copy).verify()
    if errors:
        raise Invalid("the copy does not verify: " + "; ".join(errors[:3]))
    if expected_head is not None and head != expected_head:
        raise Invalid(
            f"the record changed while it was copied (head {expected_head[:12]}… became {head[:12]}…);"
            " run the backup again"
        )
    checked = 0
    if check_attachments:
        store = copy / attachments.DIR
        identities = Logbook(copy).identities  # a sealed file is checked when the identity is here
        for file in sorted(store.iterdir()) if store.is_dir() else []:
            if not file.is_file() or file.name.startswith("."):
                continue
            matches = attachments.check(file, identities)
            if matches is False:
                raise Invalid(f"{attachments.DIR}/{file.name} holds bytes that do not match its name")
            if matches:
                checked += 1
    return seq, head, checked


def snapshots(owner_dir: Path) -> list[Path]:
    """The finished snapshots under one owner's directory, oldest first; a dotted directory (a copy
    in progress, or one that was abandoned) is never one."""
    if not owner_dir.is_dir():
        return []
    return sorted(p for p in owner_dir.iterdir() if p.is_dir() and not p.name.startswith("."))


def _snapshot_name(owner_dir: Path, stamp: datetime) -> str:
    """The stamp, suffixed `-2`, `-3`, … when that second already has a snapshot or a partial."""
    base = stamp.strftime(STAMP)
    name, n = base, 1
    while (owner_dir / name).exists() or (owner_dir / PARTIAL.format(name=name)).exists():
        n += 1
        name = f"{base}-{n}"
    return name


def snapshot(
    lb: Logbook,
    dest: Path,
    *,
    verify_attachments: bool = False,
    env: Mapping[str, str] | None = None,
) -> Result:
    """One snapshot of `lb` under `dest/<owner_id>/`, linked against the previous one where files
    are unchanged, verified before it gets its name. Refused before anything is written; Invalid
    when the copy does not verify, and nothing is left behind."""
    meta = lb.meta
    lb._check_format(meta)  # a 0.1 record is not verified by this code: migrate first, as everywhere
    check_destination(dest, lb.root, os.environ if env is None else env)
    owner_dir = dest / str(meta["owner_id"])
    owner_dir.mkdir(parents=True, exist_ok=True)
    earlier = snapshots(owner_dir)
    previous = earlier[-1] if earlier else None
    name = _snapshot_name(owner_dir, now())
    partial, final = owner_dir / PARTIAL.format(name=name), owner_dir / name
    files = record_files(lb.root)
    try:
        partial.mkdir()
        copied, copied_bytes, linked, total = _copy_tree(lb.root, files, partial, previous)
        seq, head, checked = _verify_copy(partial, str(meta["head"]), verify_attachments)
        os.rename(partial, final)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return Result(
        final,
        seq,
        head,
        len(files),
        total,
        copied,
        copied_bytes,
        linked,
        previous,
        checked if verify_attachments else None,
    )


def prune(owner_dir: Path, keep: int, spare: Path) -> list[Path]:
    """Remove the oldest snapshots under `owner_dir` until `keep` remain; `spare` is never one of
    them. The paths removed, oldest first."""
    if keep < 1:
        raise ValueError("--keep takes a number of snapshots to keep, 1 or more")
    found = snapshots(owner_dir)
    removed: list[Path] = []
    for path in found:
        if len(found) - len(removed) <= keep:
            break
        if path == spare:
            continue
        shutil.rmtree(path)
        removed.append(path)
    return removed


# -- list ----------------------------------------------------------------------------------------------------


def _entry(path: Path, seen: set[tuple[int, int]]) -> Entry:
    total = new = 0
    for file in path.rglob("*"):
        if not file.is_file():
            continue
        st = file.stat()
        total += st.st_size
        key = (st.st_dev, st.st_ino)
        if key not in seen:
            new += st.st_size
            seen.add(key)
    try:
        meta = json.loads((path / META).read_text(encoding="utf-8"))
        seq, head = int(meta["seq"]), str(meta["head"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        return Entry(path, None, None, total, new, f"{META}: {type(e).__name__}: {e}")
    return Entry(path, seq, head, total, new)


def listing(dest: Path) -> Iterator[tuple[str, list[Entry]]]:
    """Per owner directory under `dest`, its snapshots oldest first, with what each claims and
    how many of its bytes are its own (not a hard link to an earlier one)."""
    if not dest.is_dir():
        return
    for owner_dir in sorted(p for p in dest.iterdir() if p.is_dir() and not p.name.startswith(".")):
        found = snapshots(owner_dir)
        if not found:
            continue
        seen: set[tuple[int, int]] = set()
        yield owner_dir.name, [_entry(path, seen) for path in found]


# -- restore -------------------------------------------------------------------------------------------------


def check_target(target: Path, env: Mapping[str, str]) -> None:
    """Refused unless `target` is missing or an empty directory outside any sync client's folder.
    (A code checkout, which `init` refuses, is never empty, so the emptiness rule covers it.)"""
    if target.exists():
        if not target.is_dir():
            raise Refused(f"{target} is not a directory")
        if any(target.iterdir()):
            raise Refused(f"{target} is not empty; restore never writes over anything")
    service = doctor.cloud_folder(target, env)
    if service is not None:
        raise Refused(f"{target} is under {service}, a sync client's folder: {doctor.CLOUD_REASON}")


def restore(source: Path, target: Path, *, env: Mapping[str, str] | None = None) -> Result:
    """The snapshot at `source` copied — never linked — to `target`, then verified there.
    Refused when `source` is not a snapshot or `target` is not free; Invalid when the copy does
    not verify, and it is removed."""
    if not (source / META).is_file():
        raise Refused(f"{source} is not a snapshot: no {META} in it")
    check_target(target, os.environ if env is None else env)
    copy = Logbook(source)
    try:
        copy._check_format(copy.meta)  # FormatError for a 0.1 snapshot: migrate, as everywhere
    except (OSError, ValueError) as e:
        raise Refused(f"{source / META}: {e}") from e
    files = record_files(source)
    made = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    try:
        copied, copied_bytes, _linked, total = _copy_tree(source, files, target, None)
        seq, head, _checked = _verify_copy(target, None, False)
    except BaseException:
        if made:
            shutil.rmtree(target, ignore_errors=True)
        else:
            for child in target.iterdir():
                shutil.rmtree(child) if child.is_dir() else child.unlink()
        raise
    return Result(target, seq, head, len(files), total, copied, copied_bytes, 0, None)


# -- text ----------------------------------------------------------------------------------------------------


def human(n: int) -> str:
    """`999 B`, `4.0 KiB`, `1.2 MiB`, `5.0 GiB`."""
    value = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{n} B" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def describe(result: Result) -> list[str]:
    """The lines `backup` prints after the snapshot's path."""
    parts = [f"{result.copied} copied ({human(result.copied_bytes)})"]
    if result.linked_to is not None:
        parts.append(f"{result.linked} linked to {result.linked_to.name}")
    return [
        f"  {result.files} files, {human(result.bytes)}: " + ", ".join(parts),
        f"  valid — {result.seq:,} lines, head {result.head}",
    ]


__all__ = [
    "BackupError",
    "Entry",
    "Invalid",
    "Refused",
    "Result",
    "check_destination",
    "check_target",
    "copy_file",
    "describe",
    "human",
    "listing",
    "prune",
    "record_files",
    "restore",
    "snapshot",
    "snapshots",
]
