"""The inbox: what was dropped in `<root>/inbox/`, which import consumed it, and clearing it out.

An import that runs to its end — `logbook add <file|folder>`, each source of `logbook import-backup`
— records what it read in `<root>/state/imports.jsonl`, one JSON object per run, appended: the
input (`inbox/takeout/Records.json`, relative to the root when inside it, else absolute), the
adapter, how many lines the adapter produced and how many were new, the `seq` span appended and
the hash of its last line, the record's `owner_id`, the input's size. Bookkeeping, not the record
(like `state/<source>.json`): `verify` never reads it, and losing it only makes `inbox clean`
refuse everything until the inputs are imported again, which appends nothing.

A run that stopped early (an adapter error, Ctrl-C) records nothing, so its input reads
`not imported` and is never cleaned.

`inbox list` matches every file under `inbox/` to the latest run whose input is the file or a
folder above it. Two more files are taken by name, never by a run of their own: a store's `-wal`,
`-shm` or `-journal` sibling, read with the store; and `copies.json` and `Manifest.db` directly
under an `ios-backup-<udid>/` folder, the backup import's own bookkeeping, ready when every other
file in the folder is. A file is **ready** — `inbox clean` may move or delete it — when its run
belongs to this record (`owner_id`), the input has not changed since (size, and for a single file
its modification time), and the last line the run appended is still at its `seq` with its hash:
the record is append-only, so that line standing means every line before it stands too, and a
line the run skipped was already in the record then. Nothing here is a match on path strings:
paths are compared part by part.

The inbox manifest, `<root>/inbox/manifest.json`, is where a long import got to.

A file adapter that reads one big export front to back — `mail` on a 20 GB Takeout mbox — takes
a `cursor`. Before every draft it tells the cursor how far the file is read (`reached`), and
`logbook add` tells the cursor, after every checkpoint of `append_many`, how many drafts the record
holds (`commit`). The cursor then writes the byte offset of the last message in the record, so an
import that stopped — Ctrl-C, a crash, a full disk — picks up there the next time `add` runs on
the same file with the same options, and a finished one reads nothing and appends nothing.

An entry is keyed by the adapter, the file's absolute path and the options the import ran with
(`--account`, `--since`, `--only-labels`, `--skip-labels`, …): an import with other options is
another import. It is honoured only while the file is the same one: the digest of its first
`HEAD_BYTES` bytes and its size are kept and checked, and a file that changed is read from the
start again, as is one the owner asks to with `--restart`. The record never depends on this file:
re-adding the same export appends nothing either way (ADR 0017); the manifest only saves the
hours of reading. Bookkeeping beside the record, like `state/` and `index.sqlite`, never in it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath, PurePosixPath
from typing import Any

from ..core.store import Logbook, now_utc

INBOX = "inbox"
LEDGER = PurePath("state") / "imports.jsonl"
JSONL = "jsonl"  # the "adapter" of observations an adapter run by hand wrote
SIBLING_SUFFIXES = ("-wal", "-shm", "-journal")  # SQLite's companions, read with their store
BACKUP_PREFIX = "ios-backup-"  # `import-backup` copies into inbox/ios-backup-<udid>/
BOOKKEEPING = ("copies.json", "Manifest.db")  # directly under that folder; not an adapter's input
MTIME_SLACK_S = 2  # a file system may keep modification times to two seconds


@dataclass(frozen=True)
class Import:
    """One run that read one input to its end."""

    at: str  # when the run finished, RFC 3339 UTC
    input: str  # POSIX; relative to the root when under it, else absolute
    adapter: str  # the adapter's NAME, or `jsonl`
    produced: int  # lines the adapter yielded
    appended: int  # of those, new to the record; the rest were already there
    seq_first: int | None  # the span appended; None when nothing was
    seq_last: int | None
    last_hash: str | None  # the hash of the line at seq_last
    owner_id: str  # of the record written to
    bytes: int  # the input's size then: a file's, or the sum of a folder's files

    @property
    def day(self) -> str:
        return self.at[:10]

    @property
    def parts(self) -> tuple[str, ...]:
        return PurePosixPath(self.input).parts

    def covers(self, relative_to_root: PurePath) -> bool:
        """Whether `relative_to_root` is this run's input or lies under it."""
        mine = self.parts
        return relative_to_root.parts[: len(mine)] == mine

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Import:
        return cls(
            at=str(data["at"]),
            input=str(data["input"]),
            adapter=str(data["adapter"]),
            produced=int(data["produced"]),
            appended=int(data["appended"]),
            seq_first=_int_or_none(data.get("seq_first")),
            seq_last=_int_or_none(data.get("seq_last")),
            last_hash=None if data.get("last_hash") is None else str(data["last_hash"]),
            owner_id=str(data["owner_id"]),
            bytes=int(data["bytes"]),
        )


def _int_or_none(value: object) -> int | None:
    return None if value is None else int(str(value))


def describe(root: Path, path: Path) -> str:
    """How a ledger entry spells an input: POSIX, relative to `root` when under it, else absolute."""
    try:
        return path.resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def input_bytes(path: Path) -> int:
    """A file's size, or the sum of a folder's files; a path that is gone is 0."""
    try:
        if path.is_dir():
            return sum(f.stat().st_size for f in _files_under(path))
        return path.stat().st_size
    except OSError:
        return 0


def _files_under(folder: Path) -> Iterator[Path]:
    for f in folder.rglob("*"):
        if f.is_file():
            yield f


def finished(lb: Logbook, path: Path, adapter: str, produced: int, appended: int, seq_before: int) -> Import:
    """The entry for a run that just appended `appended` lines of `produced` through `adapter`,
    the record's `seq` having been `seq_before` first."""
    meta = lb.meta
    appended_any = appended > 0
    return Import(
        at=now_utc(),
        input=describe(lb.root, path),
        adapter=adapter,
        produced=produced,
        appended=appended,
        seq_first=seq_before + 1 if appended_any else None,
        seq_last=int(meta["seq"]) if appended_any else None,
        last_hash=str(meta["head"]) if appended_any else None,
        owner_id=str(meta["owner_id"]),
        bytes=input_bytes(path),
    )


def record(root: Path, entry: Import) -> Path:
    """Append one entry to the ledger; the file's path."""
    path = Path(root) / LEDGER
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as fh:
        fh.write((json.dumps(entry.to_json(), ensure_ascii=False) + "\n").encode("utf-8"))
    return path


def imports(root: Path) -> list[Import]:
    """Every entry of the ledger in the order written; a line that will not parse is skipped."""
    path = Path(root) / LEDGER
    if not path.is_file():
        return []
    found: list[Import] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                found.append(Import.from_json(data))
        except (ValueError, KeyError, TypeError):
            continue
    return found


# -- what is in the inbox ---------------------------------------------------------------


@dataclass
class File:
    """One file under inbox/: where, how big, which run consumed it, whether it may go, and why."""

    path: Path
    relative: PurePath  # to inbox/
    bytes: int
    consumer: Import | None
    ready: bool
    status: str

    @property
    def name(self) -> str:
        return self.relative.as_posix()

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.name,
            "bytes": self.bytes,
            "ready": self.ready,
            "adapter": self.consumer.adapter if self.consumer else None,
            "imported_at": self.consumer.at if self.consumer else None,
            "status": self.status,
        }


NOT_IMPORTED = "not imported"


def files(lb: Logbook) -> list[File]:
    """Every regular file under inbox/ (hidden files are not exports), in path order, each matched
    to the run that consumed it and judged ready or not. None when there is no inbox/ folder."""
    folder = lb.root / INBOX
    if not folder.is_dir():
        return []
    runs = imports(lb.root)
    owner_id = str(lb.meta["owner_id"])
    verdicts: dict[Import, tuple[bool, str]] = {}
    found: list[File] = []
    for path in sorted((f for f in _files_under(folder) if not _hidden(f, folder)), key=lambda f: f.parts):
        relative = path.relative_to(folder)
        to_root = PurePath(INBOX) / relative
        run = _consumer(runs, to_root)
        if run is None:
            found.append(File(path, relative, _size(path), None, False, NOT_IMPORTED))
            continue
        if run not in verdicts:
            verdicts[run] = _judge(lb, run, owner_id)
        ready, status = verdicts[run]
        found.append(File(path, relative, _size(path), run, ready, status))
    _take_siblings(found)
    _take_bookkeeping(found)
    return found


def _hidden(path: Path, folder: Path) -> bool:
    """A hidden file is no export; nor is the import manifest directly under inbox/ (the cursor's
    own bookkeeping, `MANIFEST`), which no run consumes and `inbox clean` never touches."""
    parts = path.relative_to(folder).parts
    return any(part.startswith(".") for part in parts) or parts == (MANIFEST.name,)


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _consumer(runs: list[Import], to_root: PurePath) -> Import | None:
    """The latest run whose input is this path or a folder above it."""
    return next((run for run in reversed(runs) if run.covers(to_root)), None)


def _judge(lb: Logbook, run: Import, owner_id: str) -> tuple[bool, str]:
    """Whether a run's input may go, and the words for it."""
    who = f"imported by {run.adapter} on {run.day}"
    if run.owner_id != owner_id:
        return False, f"{who} into another record"
    if _changed(lb.root, run):
        return False, f"changed since {run.adapter} read it on {run.day}"
    if run.seq_last is not None:
        line = lb.line_by_seq(run.seq_last)
        if line is None or line.get("hash") != run.last_hash:
            return False, f"{who}, but line #{run.seq_last} is not in the record"
    lines = f"{run.produced:,} line{'s' if run.produced != 1 else ''}"
    return True, f"{who}; {lines}, all in the record"


def _changed(root: Path, run: Import) -> bool:
    """Whether the input is not what the run read: another size, or (a single file) written since."""
    path = _input_path(root, run)
    if not path.exists():
        return True
    if input_bytes(path) != run.bytes:
        return True
    if path.is_file():
        finished_at = datetime.fromisoformat(run.at.replace("Z", "+00:00")).astimezone(UTC).timestamp()
        return path.stat().st_mtime > finished_at + MTIME_SLACK_S
    return False


def _input_path(root: Path, run: Import) -> Path:
    given = PurePosixPath(run.input)
    return Path(given) if given.is_absolute() else Path(root).joinpath(*given.parts)


def _take_siblings(found: list[File]) -> None:
    """A `-wal`, `-shm` or `-journal` beside an imported store was read with the store."""
    by_relative = {f.relative: f for f in found}
    for f in found:
        if f.consumer is not None:
            continue
        for suffix in SIBLING_SUFFIXES:
            if not f.relative.name.endswith(suffix):
                continue
            store = by_relative.get(f.relative.with_name(f.relative.name[: -len(suffix)]))
            if store is not None and store.consumer is not None:
                f.consumer, f.ready = store.consumer, store.ready
                f.status = f"with {store.relative.name}: {store.status}"
            break


def _take_bookkeeping(found: list[File]) -> None:
    """`copies.json` and `Manifest.db` directly under an `ios-backup-<udid>/` folder go when every
    other file in that folder is ready."""
    others: dict[PurePath, list[File]] = {}
    for f in found:
        parts = f.relative.parts
        if len(parts) >= 2 and parts[0].startswith(BACKUP_PREFIX) and not _bookkeeping(f):
            others.setdefault(PurePath(parts[0]), []).append(f)
    for f in found:
        if not _bookkeeping(f):
            continue
        beside = others.get(PurePath(f.relative.parts[0]), [])
        waiting = sum(not o.ready for o in beside)
        f.status = "bookkeeping of the backup import; " + (
            f"{waiting:,} file{'s' if waiting != 1 else ''} beside it {'are' if waiting != 1 else 'is'} not"
            if waiting
            else "every file beside it is imported"
        )
        f.ready = not waiting and bool(beside)
        if not beside:
            f.status = "bookkeeping of the backup import; nothing beside it"


def _bookkeeping(f: File) -> bool:
    parts = f.relative.parts
    return len(parts) == 2 and parts[0].startswith(BACKUP_PREFIX) and parts[1] in BOOKKEEPING


# -- clean -----------------------------------------------------------------------------


@dataclass
class Cleaned:
    """What `clean` did, or would do: the files that went, the files kept with their reasons, the bytes."""

    gone: list[File]
    kept: list[File]
    freed: int


def clean(lb: Logbook, to: Path | None, delete: bool, dry_run: bool) -> Cleaned:
    """Move every ready file to `to/<path under inbox>`, or with `delete` remove it; keep every
    other file where it is. A file already at its destination is kept, never overwritten. Folders
    emptied on the way go too (never inbox/ itself, never inbox/done). `dry_run` touches nothing."""
    folder = lb.root / INBOX
    gone: list[File] = []
    kept: list[File] = []
    freed = 0
    for f in files(lb):
        if not f.ready:
            kept.append(f)
            continue
        if not delete:
            assert to is not None
            target = to.joinpath(*f.relative.parts)
            if target.exists():
                kept.append(File(f.path, f.relative, f.bytes, f.consumer, False, f"already at {to}"))
                continue
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(os.fspath(f.path), os.fspath(target))
        elif not dry_run:
            f.path.unlink()
        gone.append(f)
        freed += f.bytes
        if not dry_run:
            _prune(f.path.parent, folder)
    return Cleaned(gone, kept, freed)


def _prune(start: Path, inbox: Path) -> None:
    """Remove the now-empty folders from `start` up to (not including) `inbox`, and leave inbox/done."""
    folder = start
    while folder != inbox and inbox in folder.parents:
        if folder == inbox / "done":
            return
        try:
            folder.rmdir()
        except OSError:  # not empty, or already gone
            return
        folder = folder.parent


# -- words ------------------------------------------------------------------------------


def size_text(n: int) -> str:
    """`551 bytes`, `41.5 kB`, `812.3 MB`, `1.2 GB`: decimal units, as the Finder counts."""
    if n < 1000:
        return f"{n:,} byte{'s' if n != 1 else ''}"
    value = float(n)
    for unit in ("kB", "MB", "GB", "TB"):
        value /= 1000
        if value < 1000 or unit == "TB":
            return f"{value:,.1f} {unit}"
    return f"{value:,.1f} TB"  # pragma: no cover — the loop returns at TB


def hint(root: Path, inputs: list[Path]) -> str | None:
    """The one line `add` and `import-backup` end with: the inputs are imported in full and may go.
    Inputs under inbox/ name `inbox clean`; any other may simply be deleted."""
    if not inputs:
        return None
    inside = [p for p in inputs if _under_inbox(root, p)]
    what = inputs[0].name if len(inputs) == 1 else f"{len(inputs)} files"
    if inside and len(inside) == len(inputs):
        return (
            f"inbox: {what} can be cleaned now — logbook inbox clean --to DIR moves it to DIR"
            f" (an external disk), --delete removes it"
        )
    return (
        f"done: {what} imported in full and can be deleted"
        " (dropped in inbox/ instead, logbook inbox clean does it)"
    )


def backup_hint(root: Path, backup_folder: Path, sources: int) -> str | None:
    """`import-backup`'s last line: the sources imported in full under inbox/ios-backup-<udid>/."""
    if not sources:
        return None
    what = f"{sources} source{'s' if sources != 1 else ''}"
    try:
        shown = backup_folder.relative_to(root).as_posix()
    except ValueError:
        shown = str(backup_folder)
    return (
        f"inbox: {what} under {shown} can be cleaned now — logbook inbox clean --to DIR moves"
        " them to DIR (an external disk), --delete removes them"
    )


def _under_inbox(root: Path, path: Path) -> bool:
    try:
        return path.resolve().relative_to((Path(root) / INBOX).resolve()).parts != ()
    except ValueError:
        return False


# -- the manifest: where a long import got to ------------------------------------------------

MANIFEST = Path("inbox") / "manifest.json"
HEAD_BYTES = 4096


class Cursor:
    """One import's cursor over the files it reads; `logbook.contrib.adapters.mail.Cursor` is the half the
    adapter sees (`start`, `reached`), `commit` the half the consumer drives."""

    def __init__(
        self,
        root: Path,
        adapter: str,
        options: Mapping[str, Any] | None = None,
        restart: bool = False,
        notice: Callable[[str], None] | None = None,
    ) -> None:
        self.root = Path(root)
        self.adapter = adapter
        self.options = {k: v for k, v in sorted((options or {}).items()) if v is not None}
        self.restart = restart
        self.notice = notice
        self.files: dict[Path, tuple[str, int]] = {}  # file → (head digest, size) when `start` ran
        # file → the last two (ordinal, offset) marks not yet committed: the latest, and the one
        # before it for when the import stops while the latest draft is still on its way
        self.pending: dict[Path, list[tuple[int, int]]] = {}
        self.resumed: list[tuple[Path, int]] = []
        self.written = 0

    # -- the adapter's half ----------------------------------------------------

    def start(self, file: Path) -> int:
        file = Path(file).resolve()
        head, size = _identity(file)
        self.files[file] = (head, size)
        if self.restart:
            return 0
        entry = self._entry(file)
        if entry is None or entry.get("head") != head or entry.get("size") != size:
            return 0
        offset = int(entry.get("offset") or 0)
        if offset <= 0 or offset > size:
            return 0
        self.resumed.append((file, offset))
        if self.notice is not None:
            if offset == size:
                self.notice(
                    f"  {file.name}: read to the end already ({size:,} bytes, {MANIFEST.as_posix()});"
                    " --restart reads it again"
                )
            else:
                self.notice(
                    f"  {file.name}: resuming at {offset:,} of {size:,} bytes ({MANIFEST.as_posix()})"
                )
        return offset

    def reached(self, file: Path, ordinal: int, offset: int) -> None:
        marks = self.pending.setdefault(Path(file).resolve(), [])
        if marks and marks[-1][0] == ordinal:  # the end of the file: the same draft, further on
            marks[-1] = (ordinal, offset)
        else:
            marks.append((ordinal, offset))
        del marks[:-2]

    # -- the consumer's half ---------------------------------------------------

    def commit(self, taken: int) -> None:
        """Every draft up to `taken` is in the record: write the offset of every file whose last
        reported draft is among them."""
        done: dict[Path, tuple[int, int]] = {}
        for file, marks in list(self.pending.items()):
            reached = [mark for mark in marks if mark[0] <= taken]
            if reached:
                done[file] = reached[-1]
                marks[:] = [mark for mark in marks if mark[0] > taken]
            if not marks:
                del self.pending[file]
        if not done:
            return
        manifest = self.load()
        entries: list[dict[str, Any]] = [e for e in manifest.get("cursors", []) if isinstance(e, dict)]
        for file, (ordinal, offset) in done.items():
            head, size = self.files.get(file) or _identity(file)
            entry = self._find(entries, file)
            if entry is None:
                entry = {"adapter": self.adapter, "path": str(file), "options": self.options}
                entries.append(entry)
            entry.update(
                head=head,
                size=size,
                offset=offset,
                drafts=ordinal,
                done=offset >= size,
                updated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            self.written += 1
        manifest["cursors"] = entries
        self.save(manifest)

    # -- the file ----------------------------------------------------------------

    @property
    def path(self) -> Path:
        return self.root / MANIFEST

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, manifest: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)  # never a half-written manifest

    def _entry(self, file: Path) -> dict[str, Any] | None:
        entries = [e for e in self.load().get("cursors", []) if isinstance(e, dict)]
        return self._find(entries, file)

    def _find(self, entries: list[dict[str, Any]], file: Path) -> dict[str, Any] | None:
        for entry in entries:
            if (
                entry.get("adapter") == self.adapter
                and Path(str(entry.get("path") or "")) == file
                and (entry.get("options") or {}) == self.options
            ):
                return entry
        return None


def _identity(file: Path) -> tuple[str, int]:
    """(the digest of the file's first HEAD_BYTES bytes, its size): the same file, or not."""
    with file.open("rb") as fh:
        head = fh.read(HEAD_BYTES)
        size = fh.seek(0, os.SEEK_END)
    return hashlib.sha256(head).hexdigest(), size
