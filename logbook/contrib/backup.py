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
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

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
LAST_BACKUP_FILE = PurePosixPath("state/last-backup.json")  # record-relative: the live record at backup time
LAST_RESTORE_TEST_FILE = PurePosixPath("state/last-restore-test.json")
RUN_STAMP = "%Y-%m-%dT%H:%M:%SZ"
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
class RestoreTest:
    """One restore test (`backup --restore-test`): the latest snapshot restored into a temporary
    folder, verified there, compared with what the record said when the backup was taken."""

    at: datetime  # UTC, aware
    status: str  # `passed`, `failed` or `skipped`
    snapshot: Path | None
    seq: int | None
    head: str | None
    reason: str | None  # why it failed or was skipped; None when it passed
    kept: Path | None = None  # the restore left in place (`--to DIR`); None when it was deleted


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
    stamp = now()
    name = _snapshot_name(owner_dir, stamp)
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
    record_backup(lb.root, dest, final, seq, head, stamp)
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


# -- the restore test ----------------------------------------------------------------------------------------


def _stamp(at: datetime) -> str:
    return at.astimezone(UTC).strftime(RUN_STAMP)


def _parse_stamp(text: str) -> datetime:
    return datetime.strptime(text, RUN_STAMP).replace(tzinfo=UTC)


def _write_json(path: Path, data: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    return path


def record_backup(root: Path, dest: Path, snapshot_path: Path, seq: int, head: str, at: datetime) -> Path:
    """`state/last-backup.json`: where the last backup went and what the live record said at the
    time (lines and head), for the restore test to compare against. Bookkeeping, never in the
    chain; a snapshot leaves `state/` out, so it never carries this file."""
    data = {
        "at": _stamp(at),
        "dest": str(dest),
        "snapshot": str(snapshot_path),
        "seq": seq,
        "head": head,
    }
    return _write_json(root.joinpath(*LAST_BACKUP_FILE.parts), data)


def last_backup(root: Path) -> dict[str, Any] | None:
    """What `record_backup` wrote, or None: no backup recorded, or a file that is not the shape
    (bookkeeping; the restore test then compares with the snapshot alone and says so)."""
    path = root.joinpath(*LAST_BACKUP_FILE.parts)
    if not path.exists():
        return None
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("dest"), str):
        return None
    return data


def read_restore_test(root: Path) -> RestoreTest | None:
    """The last restore test as written, or None when there has been none. A file that is not the
    shape raises ValueError naming it."""
    path = root.joinpath(*LAST_RESTORE_TEST_FILE.parts)
    if not path.exists():
        return None
    shape = f"{path} is not the shape `logbook backup --restore-test` writes"
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data["status"] not in ("passed", "failed", "skipped"):
            raise ValueError(shape)
        snapshot = data.get("snapshot")
        kept = data.get("kept")
        return RestoreTest(
            _parse_stamp(str(data["at"])),
            str(data["status"]),
            Path(snapshot) if isinstance(snapshot, str) else None,
            int(data["seq"]) if data.get("seq") is not None else None,
            str(data["head"]) if data.get("head") is not None else None,
            str(data["reason"]) if data.get("reason") is not None else None,
            Path(kept) if isinstance(kept, str) else None,
        )
    except (KeyError, TypeError, ValueError):
        raise ValueError(shape) from None


def write_restore_test(root: Path, test: RestoreTest) -> Path:
    data = {
        "at": _stamp(test.at),
        "status": test.status,
        "snapshot": str(test.snapshot) if test.snapshot is not None else None,
        "seq": test.seq,
        "head": test.head,
        "reason": test.reason,
        "kept": str(test.kept) if test.kept is not None else None,
    }
    return _write_json(root.joinpath(*LAST_RESTORE_TEST_FILE.parts), data)


NO_BACKUP = (
    "no backup recorded in state/last-backup.json: run `logbook backup DEST` once and the schedule tests"
    " it on the first Sunday of the month, or name DEST: `logbook backup --restore-test DEST`"
)
NO_IDENTITY = (
    "the record seals tiers 2 and 3 and opening them needs the identity; none at {path}: put"
    " LOGBOOK_IDENTITY_FILE=<path to the identity file> in ~/.config/logbook/sync.env (the schedule reads"
    " it) or pass --identity-file, and the restore test opens every sealed line"
)


def restore_test(
    lb: Logbook,
    dest: Path | None = None,
    to: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
    at: datetime | None = None,
) -> RestoreTest:
    """The latest snapshot of this record under `dest` (default: where the last backup went,
    `state/last-backup.json`) restored into a temporary folder (or `to`, which is then kept),
    verified there — every sealed line opened, when the record seals — and compared with what the
    record said when the backup was taken; the temporary restore deleted; the outcome written to
    `state/last-restore-test.json` and returned. Skipped, with the reason, when there is no backup
    to test or no identity to open a sealed record with; failed when the copy does not verify or
    is not the backup the record made. Never a prompt, never an exception for what the outcome
    can say: only `to` being refused (not empty, under a sync client) raises `Refused`."""
    environ = os.environ if env is None else env
    at = now() if at is None else at
    recorded = last_backup(lb.root)
    if dest is None:
        if recorded is None:
            return _outcome(lb, RestoreTest(at, "skipped", None, None, None, NO_BACKUP))
        dest = Path(str(recorded["dest"]))
    meta = lb.meta
    found = snapshots(dest / str(meta["owner_id"]))
    if not found:
        reason = (
            f"no snapshot of this record under {dest}: is the backup disk there? run `logbook backup {dest}`"
        )
        return _outcome(lb, RestoreTest(at, "failed", None, None, None, reason))
    latest = found[-1]
    sealed = bool(lb.recipients)
    if sealed and not lb.identities:
        reason = NO_IDENTITY.format(path=lb.identity_file)
        return _outcome(lb, RestoreTest(at, "skipped", latest, None, None, reason))
    if to is not None:
        check_target(to, environ)
    target = to if to is not None else Path(tempfile.mkdtemp(prefix="logbook-restore-test-"))
    try:
        try:
            result = restore(latest, target, env=environ)
        except BackupError as e:
            return _outcome(lb, RestoreTest(at, "failed", latest, None, None, f"{latest.name}: {e}"))
        seq, head = result.seq, result.head
        if sealed:
            seq, head, errors = Logbook(target).verify(keyed=True)
            if errors:
                reason = f"{latest.name}: a sealed line does not open or verify: " + "; ".join(errors[:3])
                return _outcome(lb, RestoreTest(at, "failed", latest, seq, head, reason))
        problem = _compare(lb, recorded, latest, seq, head)
        if problem is not None:
            return _outcome(lb, RestoreTest(at, "failed", latest, seq, head, problem))
        return _outcome(lb, RestoreTest(at, "passed", latest, seq, head, None, to))
    finally:
        if to is None:
            shutil.rmtree(target, ignore_errors=True)


def _compare(lb: Logbook, recorded: dict[str, Any] | None, latest: Path, seq: int, head: str) -> str | None:
    """Why the restored copy is not the backup the record made, or None: what the live record said
    when the backup was taken (`state/last-backup.json`, when it names this snapshot), and the live
    chain itself, whose line `seq` must be the copy's head."""
    if recorded is not None and Path(str(recorded.get("snapshot"))) == latest:  # as paths, never strings
        said_seq, said_head = recorded.get("seq"), recorded.get("head")
        if said_seq != seq or said_head != head:
            return (
                f"{latest.name} restores to {seq:,} lines, head {head[:12]}…, but the record said"
                f" {said_seq} lines, head {str(said_head)[:12]}… when the backup was taken"
            )
    if seq == 0:  # an empty record: no line to find, the head is the genesis hash either way
        return None
    live = lb.line_by_seq(seq)
    if live is None:
        return f"{latest.name} holds {seq:,} lines; the live record has only {lb.meta['seq']:,}"
    if str(live.get("hash")) != head:
        return f"{latest.name} is not a backup of this record: its head is not line {seq:,} of the live chain"
    return None


def _outcome(lb: Logbook, test: RestoreTest) -> RestoreTest:
    write_restore_test(lb.root, test)
    return test


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
    "RestoreTest",
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
