"""The folder. The only code that writes to logbook/*.jsonl."""

from __future__ import annotations

import contextlib
import heapq
import json
import os
import re
import secrets
import shutil
import sys
import time
import uuid
import zoneinfo
from array import array
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import IO, Any, BinaryIO, TextIO

from .. import FORMAT, PREVIOUS_FORMAT
from . import attachments, policy, sealing
from .chain import GENESIS, Line, Opener, compute_hash, is_sealed, parse_line, verify_lines
from .index import FILE_NAME as INDEX_FILE
from .index import Index, Located, Row, TextRow


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc(stamp: str) -> str:
    """`stamp` as SPEC §2 wants it written: RFC 3339 in UTC with a literal Z. A stamp that already
    ends in Z is kept verbatim (it is hashed as written); a numeric offset is converted, keeping
    the fractional seconds as given; a stamp with no zone at all is refused."""
    if stamp.endswith("Z"):
        return stamp
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        raise ValueError(f"timestamp {stamp!r} is not RFC 3339 UTC, e.g. 2026-03-01T07:30:00Z") from None
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp {stamp!r} has no zone; SPEC §2 wants UTC, e.g. 2026-03-01T07:30:00Z")
    fraction = FRACTION.search(stamp)
    seconds = parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    return seconds + (fraction.group(0) if fraction else "") + "Z"


FRACTION = re.compile(r"\.\d+(?=[+-]\d\d:?\d\d$)")  # the fractional seconds before a numeric offset


def uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit ms timestamp, then random. Time-ordered, so ids sort like the log."""
    ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return str(uuid.UUID(int=value))


CHECKOUT_MARKERS = ("pyproject.toml", ".git", "logbook/__init__.py")

META_EVERY = 10_000  # append_many: lines between checkpoints (files flushed, then logbook.json)
PROGRESS_EVERY = 50_000  # append_many: lines between progress reports

RETRACTION = "retraction"  # kind of the line that supersedes another (SPEC §3)

OLD_FORMAT = "logbook/0.1"  # hashed with a canonicalisation that deviated from RFC 8785 (SPEC §3.1)
MIGRATE_MESSAGE = "created as logbook/0.1 before the canonicalisation fix; run: logbook migrate"
MIGRATE_PROGRESS_EVERY = 100_000  # migrate: lines between progress reports
MIGRATION = "migration"  # kind of the one line a migration appends (SPEC §3.1)
REKEY = "rekey"  # kind of the one line a reseal to other recipients appends (RFC 0029 §6.4)
NOT_INTACT = "the 0.1 record is not intact; nothing was changed"
CUT_SHORT = "the file ends inside this line (cut short)"  # a month file a crash tore (SPEC §3)


# -- one writer at a time (#234) ----------------------------------------------------------------------
LOCK_FILE = PurePath("state") / "writer.lock"  # in the record folder, beside the sync watermarks
LOCK_POLL_S = 0.5  # how often a waiting writer looks again
COMMAND = "logbook"  # the words this process was run with, for the lock file; `cli.main` sets it
WAIT = True  # a second writer waits; `--no-wait` makes it refuse
WRITING = "another logbook command is writing to this record ({command}, since {since})"
STALE = "a stale lock from {command} (pid {pid}, since {since}) whose process is gone; taking it over"
HEAD_MOVED = (
    "the record's head moved from seq {was} to seq {now} while this command ran, so the batch it computed"
    " would not chain; the batch was not written"
)
_held: dict[Path, int] = {}  # lock file -> how many `writer` blocks of this process hold it


class Locked(Exception):
    """Another process is writing to this record and `--no-wait` said not to wait."""


class HeadMoved(Exception):
    """`logbook.json` changed under a writer between the head it read and the batch it would
    write: the batch would not chain, and nothing of it was written. Cannot happen while every
    writer holds the lock; this is the guard, the lock is the courtesy."""


class CodeCheckoutError(Exception):
    """The folder looks like a clone of this repository, not a personal record."""


class FormatError(Exception):
    """logbook.json names a format this code will not verify or write (SPEC §3.1)."""


class UnsortedFile(Exception):
    """A month file whose lines are not in seq order. This code never writes one; SPEC §3 still
    orders by seq wherever a line lives, so a caller that meets one reads again through
    `Logbook._lines_by_seq`, which sorts."""


# progress(file, lines_in_file, lines_so_far, elapsed_seconds): once per month file, as it is finished
FileProgress = Callable[[str, int, int, float], None]
OPEN_FILES = 8  # month files a reader or writer holds open at once, however many the record has


class OpenFiles[K, F: IO[Any]]:
    """At most `limit` files open at once, the least recently used closed to make room. A record
    of a few decades has hundreds of month files and macOS gives a process 256 open files by
    default, so a reader or writer over every month file holds a handful of handles and reopens
    one when it comes round again (`get(key)` opens with `opener(key)` when `key` is not open;
    the opener seeks where the reader left off). `closing(key, fh)` is told of each file before
    it is closed, so a writer can flush and fsync. Use as a context manager: leaving closes all."""

    def __init__(
        self,
        opener: Callable[[K], F],
        limit: int = OPEN_FILES,
        closing: Callable[[K, F], None] | None = None,
    ):
        self._opener = opener
        self._limit = max(1, limit)
        self._closing = closing
        self._open: OrderedDict[K, F] = OrderedDict()

    def get(self, key: K) -> F:
        fh = self._open.get(key)
        if fh is not None:
            self._open.move_to_end(key)
            return fh
        while len(self._open) >= self._limit:
            self._close(*self._open.popitem(last=False))
        fh = self._open[key] = self._opener(key)
        return fh

    def close(self) -> None:
        while self._open:
            self._close(*self._open.popitem(last=False))

    def _close(self, key: K, fh: F) -> None:
        try:
            if self._closing is not None:
                self._closing(key, fh)
        finally:
            fh.close()

    def __enter__(self) -> OpenFiles[K, F]:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def code_checkout_marker(root: Path) -> str | None:
    """The first thing in `root` that says "source code, not a diary", or None.

    On a case-insensitive disk ~/Logbook and a clone at ~/logbook are the same folder,
    so a logbook must never be created in, or found in, a folder that has one of these."""
    return next((m for m in CHECKOUT_MARKERS if (Path(root) / m).exists()), None)


IDENTITY_NEEDED = (
    "this record seals tiers 2 and 3 and writing them needs the identity (RFC 0029 §6.3); "
    "none at {path}: pass --identity-file, set LOGBOOK_IDENTITY_FILE, or run `logbook key init`"
)


class Logbook:
    def __init__(self, root: Path, identity_file: Path | None = None):
        self.root = Path(root)
        self.meta_path = self.root / "logbook.json"
        self.log_dir = self.root / "logbook"
        self._identity_file = identity_file  # `--identity-file`; else the variable, else the default path
        self._identities: list[Any] | None = None  # loaded once, on first need

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def init(cls, root: Path, timezone_name: str) -> Logbook:
        root = Path(root)
        marker = code_checkout_marker(root)
        if marker is not None:
            raise CodeCheckoutError(
                f"{root} looks like a code checkout (it has {marker}); "
                "choose another folder or set LOGBOOK_HOME"
            )
        if (root / "logbook.json").exists():
            raise FileExistsError(f"{root} is already a logbook")
        for d in ("logbook", "notes", "inbox", "inbox/done"):
            (root / d).mkdir(parents=True, exist_ok=True)
        meta = {
            "format": FORMAT,
            "owner_id": uuid7(),
            "created_at": now_utc(),
            "timezone": timezone_name,
            "seq": 0,
            "head": GENESIS,
        }
        (root / "logbook.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        policy.write_default(root)  # ADR 0016: the crossing ceiling is a setting in the record
        policy.write_default_import(root)  # the disabled sources, an empty list to begin with
        policy.write_default_owner(root)  # the owner's extra aliases, none to begin with
        return cls(root)

    @classmethod
    def find(cls, start: Path | None = None, identity_file: Path | None = None) -> Logbook:
        env = os.environ.get("LOGBOOK_HOME")
        candidates = [Path(env)] if env else []
        p = Path(start or Path.cwd()).resolve()
        candidates += [p, *p.parents, Path.home() / "Logbook"]
        for c in candidates:
            if (c / "logbook.json").exists() and code_checkout_marker(c) is None:
                return cls(c, identity_file)
        raise FileNotFoundError("no logbook found; run `logbook init`")

    @property
    def meta(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return data

    @property
    def index_path(self) -> Path:
        """`<cache dir>/logbook/<owner_id>/index.sqlite` (RFC 0029 §8): a derived locator, outside
        the folder that is the record, so a copy of the record never carries it."""
        folder = sealing.cache_dir(os.environ) / str(self.meta.get("owner_id"))
        folder.mkdir(parents=True, exist_ok=True)  # a cache folder; nothing of the record is in it
        return folder / INDEX_FILE

    # -- sealing (SPEC §2 and §4, RFC 0029) ------------------------------------------------------
    @property
    def recipients(self) -> list[str]:
        """The age recipients `logbook.json` names; a record that names none seals nothing."""
        return sealing.recipients_of(self.meta)

    @property
    def identity_file(self) -> Path:
        """Where the identity is looked for: `--identity-file`, else `LOGBOOK_IDENTITY_FILE`, else
        `<config dir>/logbook/identities/<owner_id>.txt` (RFC 0029 §6.2)."""
        return sealing.identity_path(str(self.meta.get("owner_id")), os.environ, self._identity_file)

    @property
    def identities(self) -> list[Any]:
        """The owner's identities, loaded once from `identity_file`; empty when the file is not
        there. A file that is there but holds no identity is an error naming the path."""
        if self._identities is None:
            path = self.identity_file
            self._identities = sealing.load_identities(path) if path.exists() else []
        return self._identities

    def opened(self, line: Line) -> Line:
        """The line a reader shows: a sealed line with its real payload in place of the reference
        and no `payload_enc`, when the identity is here; any other line as it is. A sealed line
        that will not open raises SealError; one without an identity is returned sealed, so a
        reader without the key still lists the day and says so."""
        if not is_sealed(line):
            return line
        identities = self.identities
        if not identities:
            return line
        opened = dict(line)
        opened["payload"] = sealing.open_line(line, identities)
        opened.pop(sealing.FIELD, None)
        return opened

    def _opener(self) -> Opener | None:
        """What `verify` opens sealed lines with: None (keyless) when there is no identity."""
        identities = self.identities
        if not identities:
            return None

        def check(line: Line) -> str | None:
            try:
                sealing.open_line(line, identities)
            except (sealing.SealError, sealing.MissingExtra) as e:
                return str(e).removeprefix(f"line {line.get('seq')}: ")  # verify_lines names the line once
            return None

        return check

    def _require_identity(self, tiers: Iterable[int]) -> None:
        """A tier 2 or 3 line is sealed on append and deduped through the blinded index, both of which
        need the identity: a writer that holds only the recipients refuses (RFC 0029 §6.3)."""
        if not self.recipients or not any(t in (2, 3) for t in tiers):
            return
        if not self.identities:
            raise sealing.IdentityRequired(IDENTITY_NEEDED.format(path=self.identity_file))

    def _save_meta(self, meta: dict[str, Any]) -> None:
        tmp = self.meta_path.with_name("logbook.json.tmp")
        tmp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.meta_path)  # never a half-written logbook.json

    def set_meta(self, **fields: Any) -> dict[str, Any]:
        """Set keys of `logbook.json` that are not the chain's — `share_key`, an `owner_id` a
        generator fixes — keeping every key already there (SPEC §1: read, change, write back),
        atomically. `seq` and `head` are `append`'s alone and are refused. Returns the new meta."""
        if "seq" in fields or "head" in fields:
            raise ValueError("seq and head are set by append only")
        meta = self.meta
        meta.update(fields)
        self._save_meta(meta)
        return meta

    def set_timezone(self, zone: str) -> None:
        """Change the record's zone (`timezone` in logbook.json, SPEC §3.2): a setting, not a line, so no
        hash changes; the index notes the new meta and rebuilds. The zone must be one this machine knows."""
        zoneinfo.ZoneInfo(zone)  # ZoneInfoNotFoundError for a name this machine's database lacks
        meta = self.meta
        meta["timezone"] = zone
        self._save_meta(meta)

    def set_owner_emails(self, emails: list[str]) -> list[str]:
        """Add to `owner_emails` in logbook.json (SPEC §3.2: the owner's own addresses, which `mail`,
        `splitwise` and the chat adapters take sides by); what the file lists afterwards, in order."""
        meta = self.meta
        listed = [str(e) for e in meta.get("owner_emails") or []]
        for email in emails:
            if email not in listed:
                listed.append(email)
        meta["owner_emails"] = listed
        self._save_meta(meta)
        return listed

    def _check_format(self, meta: dict[str, Any]) -> None:
        """verify and every writer refuse a record hashed by another rule (SPEC §3.1). A 0.2
        record hashes by the same rule as 0.3 and only lacks sealing: read and written as it is;
        `logbook key init` is what moves it to 0.3."""
        found = meta.get("format")
        if found in (FORMAT, PREVIOUS_FORMAT):
            return
        if found == OLD_FORMAT:
            raise FormatError(MIGRATE_MESSAGE)
        raise FormatError(f"format {found!r} is not {FORMAT}; this logbook needs another version of the code")

    # -- reading -------------------------------------------------------------
    def files(self) -> list[Path]:
        return sorted(self.log_dir.glob("*/*.jsonl"))

    def lines(
        self, progress: FileProgress | None = None, unreadable: list[str] | None = None
    ) -> Iterator[Line]:
        """All lines in chain order (by seq), streamed. Files partition by month of `at`;
        backfilled history lands in old files, so file order is not chain order, but the writer
        appends each file in chain order, so this is a merge: one parsed line from each file in a
        heap keyed by seq, the smallest yielded and its file read on. Memory is one line per month
        file, whatever the size of the log; open files are at most OPEN_FILES, whatever the number
        of month files: each file's byte offset is kept, a file is reopened and sought there when
        its turn comes round after the least recently used were closed. `progress` is told of
        each file in path order: a file that finishes early is held until every earlier path
        has finished, so `--progress` reads as file 1, 2, … N. A file whose lines are not in seq order raises
        UnsortedFile after some lines have been yielded; `verify` then reads again, sorted
        (`_lines_by_seq`), as SPEC §3 orders by seq wherever a line was found. A line that is not
        one (a month file cut inside its last line, bytes that are not one JSON object with
        distinct keys) raises ValueError naming its file and line number, so a reader never takes
        a broken record; when `unreadable` is a list the message goes there instead and the file is
        read no further, every line before it in that file and every other file's still merged,
        so `verify` reports the lines a crash left whole (SPEC §3, truncation)."""
        files = self.files()
        offsets = [0] * len(files)  # where the reader is in each file, for reopening it there

        def reopen(file_no: int) -> BinaryIO:
            fh = files[file_no].open("rb")
            if offsets[file_no]:
                fh.seek(offsets[file_no])
            return fh

        with OpenFiles(reopen) as handles:
            counts = [0] * len(files)  # raw lines read from each file, for messages
            held = [0] * len(files)  # lines each file holds, blank ones aside, for progress
            heap: list[tuple[int, int, Line]] = []
            started, total = time.monotonic(), 0
            pending_held: dict[int, int] = {}
            next_emit = 0

            def emit_ready() -> None:
                """Report finished files in path order, not heap-exhaustion order."""
                nonlocal next_emit
                if progress is None:
                    return
                while next_emit < len(files) and next_emit in pending_held:
                    file_no = next_emit
                    progress(
                        self._relative(files[file_no]),
                        pending_held.pop(file_no),
                        total,
                        time.monotonic() - started,
                    )
                    next_emit += 1

            def advance(file_no: int, after: int) -> None:
                """Push the next line of a file, or report the file finished."""
                fh, f = handles.get(file_no), files[file_no]
                while raw := fh.readline():
                    counts[file_no] += 1
                    offsets[file_no] += len(raw)
                    if raw.strip():
                        try:
                            line = self._parse(f, counts[file_no], raw)
                        except ValueError as e:
                            if unreadable is None:
                                raise
                            unreadable.append(str(e))
                            break  # the file ends here for the reader: read no further
                        seq = _seq_of(line)
                        if seq < after:
                            raise UnsortedFile(
                                f"{self._relative(f)} line {counts[file_no]}: seq {seq} after {after}"
                            )
                        heapq.heappush(heap, (seq, file_no, line))
                        held[file_no] += 1
                        return
                if progress is not None:
                    pending_held[file_no] = held[file_no]
                    emit_ready()

            for file_no in range(len(files)):
                advance(file_no, 0)
            while heap:
                seq, file_no, line = heapq.heappop(heap)
                total += 1
                yield line
                advance(file_no, seq)

    def lines_unsorted(self) -> Iterator[Line]:
        """Every line, streamed file by file, in file order — not chain order. For a pass that
        groups or indexes and must not hold the whole log in memory; `lines()` does."""
        for f in self.files():
            with f.open(encoding="utf-8") as fh:
                for n, raw in enumerate(fh, 1):
                    if raw.strip():
                        yield self._parse(f, n, raw)

    def located_lines(self) -> Iterator[Located]:
        """Every line with its file (relative to the root) and byte offset, streamed in file order."""
        for f in self.files():
            rel = f.relative_to(self.root).as_posix()
            offset = 0
            with f.open("rb") as fh:
                for n, raw in enumerate(fh, 1):
                    if raw.strip():
                        yield rel, offset, self._parse(f, n, raw)
                    offset += len(raw)

    # -- the index: a locator, rebuilt whenever it is missing or stale (ADR 0001, 0007) ----------
    def index(self) -> Index:
        """The index, current with logbook.json; built from the files first when it is not. The
        caller closes it (`with lb.index() as idx:`). Silent: a rebuild inside a reader prints
        nothing; `logbook index` is the command that shows progress."""
        idx = Index.open(self)
        if not idx.matches(self.meta):
            idx.rebuild()
        return idx

    def index_rebuild(self, progress: Callable[[int, float], None] | None = None) -> int:
        """`logbook index`: build from the files whatever the state; returns the line count."""
        with Index.open(self) as idx:
            return idx.rebuild(progress)

    def _index_if_current(self, meta: dict[str, Any]) -> Index | None:
        """For a writer: the index when it exists and is current, so it can be extended; a stale
        one is deleted (the next reader rebuilds) and a missing one is left missing."""
        if not self.index_path.exists():
            return None
        idx = Index.open(self)
        if idx.matches(meta):
            return idx
        idx.discard()
        return None

    def day_lines(self, day_local: str) -> list[Line]:
        """Every line of one local day (the owner's timezone), in chain order."""
        with self.index() as idx:
            return idx.day(day_local)

    def line_by_seq(self, seq: int) -> Line | None:
        with self.index() as idx:
            return idx.by_seq(seq)

    def verify(
        self,
        warnings: list[str] | None = None,
        progress: FileProgress | None = None,
        counts: dict[str, int] | None = None,
        keyed: bool | None = None,
    ) -> tuple[int, str, list[str]]:
        """(seq, head, errors) of the files, never the index, streamed through `lines()`: memory is
        one line per month file however long the record. A month file cut inside a line (a crash,
        SPEC §3) or a line that is not one JSON object is an error naming the file and line, and
        `seq` and `head` are still those of the lines read, so a torn record reports the last line
        written whole and its hash, never 0 and GENESIS while a line survives. What this release
        only warns about (SPEC §2 timestamps with a numeric offset) is appended to `warnings` when
        a list is given.
        `progress` is told of each month file as it is finished. Sealed lines are opened and
        checked against their digest when the identity is here (`keyed` None), always when
        `keyed` is True (no identity is then an error), never when False; `counts` is told how
        many were sealed, opened and plain at tier 2 or 3 (RFC 0029 §4.3)."""
        meta = self.meta
        self._check_format(meta)
        kept = 0 if warnings is None else len(warnings)
        opener = None if keyed is False else self._opener()
        if keyed is True and opener is None:
            return 0, GENESIS, [f"no identity at {self.identity_file} to open the sealed lines with"]
        tally = {} if counts is None else counts
        unreadable: list[str] = []  # lines that are not one (SPEC §3, truncation), by file and line
        try:
            seq, head, errors = verify_lines(self.lines(progress, unreadable), warnings, opener, tally)
        except UnsortedFile:  # not written by this code; SPEC §3 orders by seq regardless
            if warnings is not None:
                del warnings[kept:]
            tally.clear()
            unreadable.clear()
            seq, head, errors = verify_lines(
                self._lines_by_seq(progress, unreadable), warnings, opener, tally
            )
        errors.extend(unreadable)
        if meta["seq"] != seq or meta["head"] != head:
            errors.append(
                f"logbook.json says seq={meta['seq']} head={meta['head'][:12]}…, "
                f"files say seq={seq} head={head[:12]}…"
            )
        return seq, head, errors

    # -- writing -------------------------------------------------------------
    @contextlib.contextmanager
    def writer(
        self,
        command: str | None = None,
        wait: bool | None = None,
        notice: Callable[[str], None] | None = None,
    ) -> Iterator[None]:
        """Hold the record's writer lock, `state/writer.lock`, for the block (#234): `append` and
        `append_many` take it themselves, and a command that will append takes it around its whole
        run, so a `sync`'s walk is inside it. One process, one holder: a block inside a block of
        the same process re-enters. Another process's lock is waited for, polled every
        LOCK_POLL_S, after one line on stderr (`notice`) naming its command and start; with `wait`
        False (`--no-wait`) `Locked` is raised instead. A lock whose pid is gone is taken over,
        said in one line. A reader never calls this. The lock is a courtesy between writers; what
        keeps the chain whole is the head re-check before every batch (`append_many`)."""
        path = self._lock_path()
        if _held.get(path, 0):
            _held[path] += 1
            try:
                yield
            finally:
                _held[path] -= 1
            return
        say = notice if notice is not None else (lambda text: print(text, file=sys.stderr))
        _take_lock(path, command or COMMAND, WAIT if wait is None else wait, say)
        _held[path] = 1
        try:
            yield
        finally:
            _held[path] -= 1
            if not _held[path]:
                del _held[path]
                _release_lock(path)

    def _lock_path(self) -> Path:
        root = self.root
        with contextlib.suppress(OSError):
            root = root.resolve()
        return root / LOCK_FILE

    def append(
        self,
        at: str,
        source: str,
        kind: str,
        tier: int,
        payload: dict[str, Any],
        end: str | None = None,
        tz: str | None = None,
        recorded_at: str | None = None,
    ) -> Line:
        with self.writer():
            return self._append(at, source, kind, tier, payload, end, tz, recorded_at)

    def _append(
        self,
        at: str,
        source: str,
        kind: str,
        tier: int,
        payload: dict[str, Any],
        end: str | None,
        tz: str | None,
        recorded_at: str | None,
    ) -> Line:
        meta = self.meta  # read under the lock: the head is current until the lock is released
        self._check_format(meta)
        self._require_identity((tier,))
        line = self._line(
            meta, meta["seq"] + 1, meta["head"], at, source, kind, tier, payload, end, tz, recorded_at
        )
        path = self._path_for(line["at"])  # the month of `at` in UTC, after normalisation (SPEC §2)
        path.parent.mkdir(parents=True, exist_ok=True)
        idx = self._index_if_current(meta)
        with path.open("ab") as fh:
            fh.seek(0, os.SEEK_END)
            offset = fh.tell()
            fh.write(_dumps(line).encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())  # SPEC §3 write order: the line is on disk before logbook.json names it
        meta["seq"], meta["head"] = line["seq"], line["hash"]
        self._save_meta(meta)
        if idx is not None:
            with idx:
                line_row, words = idx.rows_of(line, meta, self._relative(path), offset)
                idx.add([line_row], meta, [] if words is None else [words])
        return line

    def retract(self, seq: int, reason: str, at: str | None = None) -> Line:
        """Retract line `seq`: a new manual line, kind `retraction`, whose payload supersedes it
        (SPEC §3). The retracted line stays; readers hide it. Raises ValueError when there is no
        such line or it is itself a retraction."""
        target = self.line_by_seq(seq)
        if target is None:
            raise ValueError(f"no line with seq {seq}")
        if target.get("kind") == RETRACTION:
            raise ValueError(f"#{seq} is itself a retraction")
        return self.append(
            at=at or now_utc(),
            source="manual",
            kind=RETRACTION,
            tier=2,
            payload={"schema": "retraction/v1", "supersedes": target["id"], "seq": seq, "reason": reason},
        )

    def attach(self, data: bytes, tier: int | None = None) -> Path:
        """Put `data` in the SPEC §1.1 store, `<root>/attachments/<sha256>`, once; the file. In a
        record that names recipients the file is sealed (RFC 0029 §7) unless `tier` says the line
        that will point at it is tier 1; a caller that does not know the tier gets the safe side."""
        return attachments.write(self.root, data, self._attachment_recipients(tier))

    def attach_file(self, path: Path, tier: int | None = None) -> Path:
        """Put the file at `path` in the SPEC §1.1 store, streamed, once; the file in the store.
        Sealed as `attach` is."""
        return attachments.write_path(self.root, path, self._attachment_recipients(tier))

    def _attachment_recipients(self, tier: int | None) -> list[str]:
        return [] if tier == 1 else self.recipients

    def attachment_bytes(self, sha256: str) -> bytes:
        """The plaintext of the store file named `sha256`, opened with the identity when sealed."""
        return attachments.read_bytes(self.root, sha256, self.identities)

    def attachment(self, sha256: str) -> contextlib.AbstractContextManager[Path]:
        """A path to the plaintext of the store file named `sha256`, for a decoder: the file
        itself when plain, a temporary copy when sealed, gone on exit (`attachments.opened`)."""
        return attachments.opened(self.root, sha256, self.identities)

    def append_many(
        self,
        drafts: Iterable[dict[str, Any]],
        progress: Callable[[int, float], None] | None = None,
        skipped: Callable[[dict[str, Any]], None] | None = None,
        committed: Callable[[int], None] | None = None,
    ) -> int:
        """Append drafts in order; returns how many were written.

        A draft whose (source, payload.raw_id) is already in the log is skipped, so re-adding the
        same export appends nothing; `skipped(draft)` is called for each one, so a caller can say
        what was already there. Drafts without a raw_id are never deduped. A draft may bring
        its own `id` (a UUIDv7 an adapter minted so another draft could point at it); one without
        gets one here. `id` is outside the hash (SPEC §2).

        Built for millions of drafts: drafts are taken META_EVERY at a time, each batch is deduped
        with one SELECT against the index, the chain is computed in memory, and at the end of
        every batch the lines are written and flushed, one month file open at a time, then
        logbook.json is saved, then the index is extended (a checkpoint). Lines never reach disk ahead of a
        checkpoint, so an interruption leaves the log exactly as it was at the last checkpoint —
        a valid chain — and re-adding the same export finishes the job. On a Python-level
        interruption (Ctrl-C, an exception in an adapter) the drafts already taken are still
        written, so nothing already drafted is lost. `progress(count, elapsed_seconds)` is called
        every PROGRESS_EVERY lines. `committed(taken)` is called after every checkpoint, the
        interrupted one included, with how many drafts have been taken from `drafts` so far, the
        deduped ones counted: everything up to that draft is on disk, so a caller that knows where
        each draft came from can note how far the source is read (`logbook.contrib.inbox.Cursor`).

        Chain order is import order: `seq` and `prev` follow the order the drafts arrive in,
        and `at` is the event time. A batch is never sorted.

        The writer lock (`writer`) is held from before the first draft is asked for until the
        last checkpoint, so the walk that produces the drafts is inside it. Before every batch is
        written, `logbook.json` is read again and must still name the head the batch was computed
        from; when it does not (a writer that did not hold the lock moved it), HeadMoved is raised
        and nothing of the batch reaches the files (#234)."""
        with self.writer():
            return self._append_many(drafts, progress, skipped, committed)

    def _append_many(
        self,
        drafts: Iterable[dict[str, Any]],
        progress: Callable[[int, float], None] | None,
        skipped: Callable[[dict[str, Any]], None] | None,
        committed: Callable[[int], None] | None,
    ) -> int:
        meta = self.meta
        self._check_format(meta)
        idx = self.index()
        seq, head = meta["seq"], meta["head"]
        n, taken, started = 0, 0, time.monotonic()
        it = iter(drafts)

        def checkpoint(lines: list[tuple[Path, Line]]) -> None:
            current = self.meta  # the guard: the head this batch chains from must still be the head
            if (current.get("seq"), current.get("head")) != (meta["seq"], meta["head"]):
                raise HeadMoved(HEAD_MOVED.format(was=meta["seq"], now=current.get("seq")))
            pending: dict[Path, list[Line]] = {}
            for path, line in lines:
                pending.setdefault(path, []).append(line)
            rows: list[Row] = []
            texts: list[TextRow] = []
            for path, batch in pending.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("ab") as fh:  # one month file open at a time, however many a batch spans
                    fh.seek(0, os.SEEK_END)
                    rel, offset = self._relative(path), fh.tell()
                    encoded = [_dumps(line).encode("utf-8") for line in batch]
                    for line, raw in zip(batch, encoded, strict=True):
                        line_row, words = idx.rows_of(line, meta, rel, offset)
                        rows.append(line_row)
                        if words is not None:
                            texts.append(words)
                        offset += len(raw)
                    fh.write(b"".join(encoded))
                    fh.flush()
                    os.fsync(fh.fileno())  # SPEC §3 write order: every line is on disk before logbook.json
            if (meta["seq"], meta["head"]) != (seq, head):
                meta["seq"], meta["head"] = seq, head
                self._save_meta(meta)
                idx.add(rows, meta, texts)

        try:
            while True:
                batch, error = _take(it, META_EVERY)
                taken += len(batch)
                self._require_identity(int(d.get("tier", 0)) for d in batch if isinstance(d.get("tier"), int))
                keys = {key for d in batch if (key := dedupe_key(d)) is not None}
                found = idx.existing(keys) if keys else set()
                lines: list[tuple[Path, Line]] = []
                for d in batch:
                    key = dedupe_key(d)
                    if key is not None:
                        if key in found:
                            if skipped is not None:
                                skipped(d)
                            continue
                        found.add(key)
                    line = self._line(meta, seq + 1, head, **d)
                    lines.append((self._path_for(line["at"]), line))
                    seq, head = line["seq"], line["hash"]
                    n += 1
                    if progress is not None and n % PROGRESS_EVERY == 0:
                        progress(n, time.monotonic() - started)
                checkpoint(lines)
                if committed is not None:
                    committed(taken)
                if error is not None:
                    raise error
                if len(batch) < META_EVERY:
                    break
        finally:
            idx.close()
        return n

    # -- migration -----------------------------------------------------------
    def migrate(self, progress: Callable[[int, float], None] | None = None) -> dict[str, Any]:
        """logbook/0.1 → logbook/0.2 (SPEC §3.1, ADR 0014): the same lines, hashed with the right rule.

        Every line keeps `id`, `seq`, the content fields and `recorded_at`; `prev` and `hash` are
        recomputed in seq order. New month files are written under <root>/logbook.migrating/, then
        swapped in: the 0.1 files move to <root>/logbook-0.1/ (kept, never deleted here) and the
        new ones take their place. logbook.json gets the new format and head and a `lineage`
        entry; index.sqlite is dropped (it is rebuilt from the files); then one manual line,
        `migration/v1`, records the old head inside the chain. Refuses anything but a 0.1 record,
        and a 0.1 record whose links (`seq`, `prev`, the head) are broken — nothing is touched then.
        `progress(count, elapsed_seconds)` is called every MIGRATE_PROGRESS_EVERY lines."""
        meta = self.meta
        if meta.get("format") != OLD_FORMAT:
            raise FormatError(f"nothing to migrate: this logbook is {meta.get('format')}")
        old_head = meta["head"]
        kept = self.root / "logbook-0.1"
        if kept.exists():
            raise FileExistsError(f"{kept} already exists; move it away before migrating")
        tmp = self.root / "logbook.migrating"
        if tmp.exists():
            shutil.rmtree(tmp)  # an earlier run that did not finish; nothing in it is the record
        tmp.mkdir()

        def reopen(path: Path) -> TextIO:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path.open("a", encoding="utf-8")

        def synced(_path: Path, fh: TextIO) -> None:
            fh.flush()
            os.fsync(fh.fileno())

        handles: OpenFiles[Path, TextIO] = OpenFiles(reopen, closing=synced)
        n, prev, old_prev, started = 0, GENESIS, GENESIS, time.monotonic()
        try:
            for line in self._lines_by_seq():
                n += 1
                if line.get("seq") != n:
                    raise ValueError(f"line {n}: seq {line.get('seq')}, expected {n}; {NOT_INTACT}")
                if line.get("prev") != old_prev:
                    raise ValueError(f"line {n}: prev does not match the previous hash; {NOT_INTACT}")
                old_prev = line["hash"]
                line["prev"] = prev
                line["hash"] = prev = compute_hash(line)
                handles.get(tmp / line["at"][:4] / f"{line['at'][5:7]}.jsonl").write(_dumps(line))
                if progress is not None and n % MIGRATE_PROGRESS_EVERY == 0:
                    progress(n, time.monotonic() - started)
            if (n, old_prev) != (meta["seq"], old_head):
                raise ValueError(
                    f"logbook.json says seq={meta['seq']} head={old_head[:12]}…, files say seq={n} "
                    f"head={old_prev[:12]}…; {NOT_INTACT}"
                )
            handles.close()  # each file flushed and fsynced as it closes
        except BaseException:
            with contextlib.suppress(OSError):  # the files are about to go; their fsync may not matter
                handles.close()
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        if self.log_dir.exists():
            os.rename(self.log_dir, kept)
        os.rename(tmp, self.log_dir)
        migrated_at = now_utc()
        meta["format"], meta["head"] = FORMAT, prev
        lineage = meta.setdefault("lineage", [])
        lineage.append({"from_format": OLD_FORMAT, "from_head": old_head, "migrated_at": migrated_at})
        self._save_meta(meta)
        if self.index_path.exists():  # ADR 0007: disposable; closed through the registry, then deleted
            Index.open(self).discard()
        line = self.append(
            at=migrated_at,
            source="manual",
            kind=MIGRATION,
            tier=1,
            payload={"schema": "migration/v1", "from_format": OLD_FORMAT, "from_head": old_head},
            recorded_at=migrated_at,
        )
        return {"lines": n, "from_head": old_head, "head": line["hash"], "kept": kept}

    # -- sealing the past, and resealing (RFC 0029 §6.4 and §10.2) ------------------------------------
    def seal_all(self, progress: Callable[[int, float], None] | None = None) -> dict[str, Any]:
        """Seal every plain tier 2 or 3 line of the record to its recipients (RFC 0029 §10.2): the ADR
        0014 road. Every line keeps `id`, `seq`, `at`, `end`, `tz`, `source`, `kind`, `tier` and
        `recorded_at`; a plain tier 2 or 3 payload becomes the sealed reference with its content in
        `payload_enc`; `prev` and `hash` are recomputed in seq order from the first changed line;
        every attachment such a line names is sealed in place under its name. New month files are
        written under <root>/logbook.sealing/ and swapped in; the plain files are **not** kept
        beside the record, and the caller says so once (a backup taken before holds them still).
        `logbook.json` gets `format` 0.3 and a `lineage` entry; the index is dropped; one manual
        `migration/v1` line records the head it replaced and the counts. Refuses a record with no
        recipients, and a record whose chain is not intact; nothing is touched then."""
        meta = self.meta
        self._check_format(meta)
        recipients = self.recipients
        if not recipients:
            raise sealing.IdentityRequired("this record names no recipients; run `logbook key init` first")
        if not self.identities:
            raise sealing.IdentityRequired(IDENTITY_NEEDED.format(path=self.identity_file))
        old_head, old_format = str(meta["head"]), str(meta["format"])
        digests: set[str] = set()

        def transform(line: Line) -> Line:
            if line.get("tier") in (2, 3) and not is_sealed(line):
                payload = line["payload"]
                digests.update(attachments.digests_in(payload))
                line["payload"], line[sealing.FIELD] = sealing.seal(payload, recipients)
            return line

        n, head, changed = self._rewrite("logbook.sealing", transform, recompute=True, progress=progress)
        sealed_files = 0
        for sha256 in sorted(digests):
            file = self.root / attachments.DIR / sha256
            if file.is_file() and not sealing.is_sealed_file(file):
                attachments.write_path(self.root, file, recipients)  # sealed in place: raised, never lowered
                sealed_files += 1
        migrated_at = now_utc()
        meta = self.meta
        meta["format"], meta["head"] = FORMAT, head
        meta.setdefault("lineage", []).append(
            {"from_format": old_format, "from_head": old_head, "migrated_at": migrated_at}
        )
        self._save_meta(meta)
        if self.index_path.exists():
            Index.open(self).discard()
        line = self.append(
            at=migrated_at,
            source="manual",
            kind=MIGRATION,
            tier=1,
            payload={
                "schema": "migration/v1",
                "from_format": old_format,
                "from_head": old_head,
                "sealed_lines": changed,
                "sealed_attachments": sealed_files,
            },
            recorded_at=migrated_at,
        )
        return {
            "lines": n,
            "sealed_lines": changed,
            "sealed_attachments": sealed_files,
            "from_head": old_head,
            "head": line["hash"],
        }

    def reseal(
        self, recipients: list[str], progress: Callable[[int, float], None] | None = None
    ) -> dict[str, Any]:
        """Reseal every sealed line and attachment to `recipients` (RFC 0029 §6.4: a recipient
        added, an identity rotated). No hash changes: `payload_enc` is outside the hash, so this is
        a rewrite of the stored form, done the migration way (a temporary folder, a swap). Then
        `logbook.json` names the new recipients, the index is dropped (its key was sealed to the
        old ones) and one `rekey/v1` line, tier 1, says it happened. The identity here must open
        the record as it is; the new list is checked (two at least)."""
        meta = self.meta
        self._check_format(meta)
        before = self.recipients
        if not before:
            raise sealing.IdentityRequired("this record names no recipients; run `logbook key init` first")
        new = sealing.check_recipients(recipients)
        identities = self.identities
        if not identities:
            raise sealing.IdentityRequired(IDENTITY_NEEDED.format(path=self.identity_file))

        def transform(line: Line) -> Line:
            if is_sealed(line):
                plain = sealing.open_bytes(line, identities)
                line[sealing.FIELD] = sealing.encode(sealing.seal_bytes(plain, new))
            return line

        n, head, changed = self._rewrite("logbook.resealing", transform, recompute=False, progress=progress)
        if head != meta["head"]:  # cannot happen: nothing hashed was touched
            raise RuntimeError(f"resealing changed the head to {head[:12]}…; the record was not swapped")
        store = self.root / attachments.DIR
        sealed_files = 0
        for file in sorted(store.iterdir()) if store.is_dir() else []:
            if file.is_file() and not file.name.startswith(".") and sealing.is_sealed_file(file):
                with attachments.opened(self.root, file.name, identities) as plain:
                    tmp = store / f".{file.name}.{os.getpid()}.resealing"
                    try:
                        sealing.seal_file(plain, tmp, new)
                        os.replace(tmp, file)
                    finally:
                        tmp.unlink(missing_ok=True)
                sealed_files += 1
        meta = self.meta
        meta["recipients"] = new
        self._save_meta(meta)
        if self.index_path.exists():
            Index.open(self).discard()
        at = now_utc()
        line = self.append(
            at=at,
            source="logbook",
            kind=REKEY,
            tier=1,
            payload={
                "schema": "rekey/v1",
                "recipients_before": len(before),
                "recipients_after": len(new),
                "recipients": new,
                "sealed_lines": changed,
                "sealed_attachments": sealed_files,
            },
            recorded_at=at,
        )
        return {"lines": n, "sealed_lines": changed, "sealed_attachments": sealed_files, "head": line["hash"]}

    def _rewrite(
        self,
        tmp_name: str,
        transform: Callable[[Line], Line],
        recompute: bool,
        progress: Callable[[int, float], None] | None,
    ) -> tuple[int, str, int]:
        """Every line through `transform`, in seq order, into new month files under <root>/<tmp_name>/,
        then swapped in; the old files are removed. With `recompute`, `prev` and `hash` are
        recomputed as a migration does. The chain is checked on the way (`seq`, `prev`) and an
        intact record is required; an exception leaves the record as it was. Returns (lines, head,
        lines the transform changed)."""
        meta = self.meta
        tmp = self.root / tmp_name
        if tmp.exists():
            shutil.rmtree(tmp)  # an earlier run that did not finish; nothing in it is the record
        tmp.mkdir()

        def reopen(path: Path) -> TextIO:
            path.parent.mkdir(parents=True, exist_ok=True)
            return path.open("a", encoding="utf-8", newline="\n")

        def synced(_path: Path, fh: TextIO) -> None:
            fh.flush()
            os.fsync(fh.fileno())

        handles: OpenFiles[Path, TextIO] = OpenFiles(reopen, closing=synced)
        n, changed, prev, old_prev, started = 0, 0, GENESIS, GENESIS, time.monotonic()
        try:
            for line in self._lines_by_seq():
                n += 1
                if line.get("seq") != n or line.get("prev") != old_prev:
                    raise ValueError(f"line {n}: the chain is not intact; nothing was changed")
                old_prev = line["hash"]
                before = _dumps(line)
                line = transform(line)
                if _dumps(line) != before:
                    changed += 1
                if recompute:
                    line["prev"] = prev
                    line["hash"] = compute_hash(line)
                elif line["hash"] != compute_hash(line):
                    raise ValueError(f"line {n}: hash does not recompute; nothing was changed")
                prev = line["hash"]
                handles.get(tmp / line["at"][:4] / f"{line['at'][5:7]}.jsonl").write(_dumps(line))
                if progress is not None and n % MIGRATE_PROGRESS_EVERY == 0:
                    progress(n, time.monotonic() - started)
            if (n, old_prev) != (meta["seq"], meta["head"]):
                raise ValueError(
                    f"logbook.json says seq={meta['seq']} head={str(meta['head'])[:12]}…, files say seq={n} "
                    f"head={old_prev[:12]}…; nothing was changed"
                )
            handles.close()  # each file flushed and fsynced as it closes
        except BaseException:
            with contextlib.suppress(OSError):  # the files are about to go; their fsync may not matter
                handles.close()
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        old = self.root / f"{tmp_name}.old"
        if old.exists():
            shutil.rmtree(old)
        if self.log_dir.exists():
            os.rename(self.log_dir, old)
        os.rename(tmp, self.log_dir)
        shutil.rmtree(old, ignore_errors=True)  # not kept beside the record (RFC 0029 §10.2)
        return n, prev, changed

    def _lines_by_seq(
        self, progress: FileProgress | None = None, unreadable: list[str] | None = None
    ) -> Iterator[Line]:
        """Every line in chain order with one line in memory at a time, whatever order the files
        are in: a first pass notes where each seq lives (two integers per line), a second reads
        them back in seq order through at most OPEN_FILES open files. `lines()` is the one-pass
        merge for files the writer kept in seq order; this is for `migrate` and for `verify`'s
        fallback. `unreadable` is as `lines()` takes it: a line that is not one ends its file for
        the reader."""
        files = self.files()
        seqs: array[int] = array("q")
        places: array[int] = array("q")  # file number << 40 | byte offset
        started = time.monotonic()
        for file_no, f in enumerate(files):
            with f.open("rb") as fh:
                offset, before = 0, len(seqs)
                for n, raw in enumerate(fh, 1):
                    if raw.strip():
                        try:
                            line = self._parse(f, n, raw)
                        except ValueError as e:
                            if unreadable is None:
                                raise
                            unreadable.append(str(e))
                            break  # the file ends here for the reader: read no further
                        seqs.append(_seq_of(line))
                        places.append((file_no << 40) | offset)
                    offset += len(raw)
            if progress is not None:
                progress(self._relative(f), len(seqs) - before, len(seqs), time.monotonic() - started)
        order = sorted(range(len(seqs)), key=seqs.__getitem__)
        handles: OpenFiles[int, BinaryIO] = OpenFiles(lambda file_no: files[file_no].open("rb"))
        with handles:
            for i in order:
                yield read_line_at(handles.get(places[i] >> 40), places[i] & ((1 << 40) - 1))

    def _line(
        self,
        meta: dict[str, Any],
        seq: int,
        prev: str,
        at: str,
        source: str,
        kind: str,
        tier: int,
        payload: dict[str, Any],
        end: str | None = None,
        tz: str | None = None,
        recorded_at: str | None = None,
        id: str | None = None,
        payload_enc: str | None = None,
    ) -> Line:
        """A complete, hashed line; nothing is written. A tier 2 or 3 payload is sealed to the record's
        recipients when it names any (SPEC §4, RFC 0029 §5): the hashed `payload` becomes the
        reference and the content goes in `payload_enc`, outside the hash. A draft that already
        carries a `payload_enc` (a line re-added from `export --sealed`) is kept as it came."""
        if "schema" not in payload:
            raise ValueError("payload.schema is required")
        if tier not in (1, 2, 3):
            raise ValueError("tier must be 1, 2 or 3")
        recipients = sealing.recipients_of(meta)
        if payload_enc is None and sealing.needs_sealing(tier, payload, recipients):
            payload, payload_enc = sealing.seal(payload, recipients)
        line: Line = {
            "id": id or uuid7(),
            "seq": seq,
            "at": utc(at),
            "end": None if end is None else utc(end),
            "tz": tz or meta["timezone"],
            "source": source,
            "kind": kind,
            "tier": tier,
            "payload": payload,
            "recorded_at": utc(recorded_at) if recorded_at else now_utc(),
            "prev": prev,
        }
        line["hash"] = compute_hash(line)
        if payload_enc is not None:
            line[sealing.FIELD] = payload_enc
        return line

    def _parse(self, path: Path, n: int, raw: str | bytes) -> Line:
        """One stored line as a dict; a bad one is reported by file and line number. A last line
        with no newline that is not JSON is a file cut inside it (SPEC §3): said plainly, without
        the decoder's position."""
        try:
            return parse_line(raw)
        except json.JSONDecodeError as e:
            whole = raw.endswith(b"\n") if isinstance(raw, bytes) else raw.endswith("\n")
            if not whole:
                raise ValueError(f"{self._relative(path)} line {n}: {CUT_SHORT}") from e
            raise ValueError(f"{self._relative(path)} line {n}: {e}") from e
        except ValueError as e:
            raise ValueError(f"{self._relative(path)} line {n}: {e}") from e

    def _path_for(self, at: str) -> Path:
        year, month = at[:4], at[5:7]
        return self.log_dir / year / f"{month}.jsonl"

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


def _take_lock(path: Path, command: str, wait: bool, notice: Callable[[str], None]) -> None:
    """Create the lock file, exclusively, with this process's pid, the command and the time; or
    wait for, refuse, or take over the one that is there (`Logbook.writer`)."""
    said = False
    while True:
        path.parent.mkdir(parents=True, exist_ok=True)  # each time: a release may have removed it
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            holder = _read_lock(path)
            if holder is None:  # being written this instant, or a crash between create and write
                time.sleep(LOCK_POLL_S)
                if _read_lock(path) is None:
                    path.unlink(missing_ok=True)
                continue
            pid, since = holder.get("pid"), str(holder.get("since", "?"))
            who = str(holder.get("command", "?"))
            if not isinstance(pid, int) or pid == os.getpid() or not _alive(pid):
                # gone, or this very process's from a block that never released (`_held` says so)
                notice(STALE.format(command=who, pid=pid, since=since))
                path.unlink(missing_ok=True)
                continue
            if not wait:
                raise Locked(
                    WRITING.format(command=who, since=since) + "; --no-wait, so not waiting"
                ) from None
            if not said:
                notice(WRITING.format(command=who, since=since) + "; waiting")
                said = True
            time.sleep(LOCK_POLL_S)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "command": command, "since": now_utc()}, fh)
            fh.flush()
        return


def _release_lock(path: Path) -> None:
    """Remove the lock when it is still this process's; one another process took over stays. The
    folder goes too when the lock was the only thing in it: a record that has synced nothing has
    no `state/`, lock or no lock."""
    holder = _read_lock(path)
    if holder is None or holder.get("pid") == os.getpid():
        path.unlink(missing_ok=True)
        with contextlib.suppress(OSError):  # not empty, or already gone: either is fine
            path.parent.rmdir()


def _read_lock(path: Path) -> dict[str, Any] | None:
    """The lock file's object, or None when it is not there yet, empty, or not JSON."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _alive(pid: int) -> bool:
    """Whether a process with this pid exists (not whether it is a logbook command: a reused pid
    holds a stale lock as a live one would, and `--no-wait`, or removing the file, answers that)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel32.GetLastError() == 5  # ERROR_ACCESS_DENIED: there, not ours
        kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def retractions(lines: Iterable[Line]) -> dict[str, Line]:
    """The retraction that supersedes each retracted line, keyed by the retracted line's id.
    When a line is retracted more than once the one written last wins."""
    found: dict[str, Line] = {}
    for line in lines:
        if line.get("kind") == RETRACTION:
            superseded = (line.get("payload") or {}).get("supersedes")
            if isinstance(superseded, str):
                found[superseded] = line
    return found


def read_line_at(fh: BinaryIO, offset: int) -> Line:
    """The line that starts at byte `offset` of an open month file."""
    fh.seek(offset)
    return parse_line(fh.readline())


def _take(it: Iterator[dict[str, Any]], size: int) -> tuple[list[dict[str, Any]], BaseException | None]:
    """Up to `size` drafts, and the exception that stopped the iterator early, if one did: the
    drafts taken before it are still returned so an interrupted import keeps them."""
    batch: list[dict[str, Any]] = []
    try:
        for _ in range(size):
            batch.append(next(it))
    except StopIteration:
        pass
    except BaseException as e:  # KeyboardInterrupt included
        return batch, e
    return batch, None


def _dumps(line: Line) -> str:
    return json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n"


def _seq_of(line: Line) -> int:
    """The seq a line claims, for ordering; a missing or non-integer one sorts first and is
    reported by `verify_lines`."""
    seq = line.get("seq")
    return seq if isinstance(seq, int) and not isinstance(seq, bool) else 0


def dedupe_key(line: dict[str, Any]) -> tuple[str, str] | None:
    raw_id = (line.get("payload") or {}).get("raw_id")
    return (str(line.get("source")), str(raw_id)) if raw_id is not None else None
