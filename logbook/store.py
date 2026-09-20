"""The folder. The only code that writes to logbook/*.jsonl."""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
import uuid
from array import array
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO, TextIO

from . import FORMAT
from .chain import GENESIS, Line, compute_hash, parse_line, verify_lines
from .index import FILE_NAME as INDEX_FILE
from .index import Index, Located, Row, row


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
NOT_INTACT = "the 0.1 record is not intact; nothing was changed"


class CodeCheckoutError(Exception):
    """The folder looks like a clone of this repository, not a personal record."""


class FormatError(Exception):
    """logbook.json names a format this code will not verify or write (SPEC §3.1)."""


def code_checkout_marker(root: Path) -> str | None:
    """The first thing in `root` that says "source code, not a diary", or None.

    On a case-insensitive disk ~/Logbook and a clone at ~/logbook are the same folder,
    so a logbook must never be created in, or found in, a folder that has one of these."""
    return next((m for m in CHECKOUT_MARKERS if (Path(root) / m).exists()), None)


class Logbook:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.meta_path = self.root / "logbook.json"
        self.log_dir = self.root / "logbook"

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
        return cls(root)

    @classmethod
    def find(cls, start: Path | None = None) -> Logbook:
        env = os.environ.get("LOGBOOK_HOME")
        candidates = [Path(env)] if env else []
        p = Path(start or Path.cwd()).resolve()
        candidates += [p, *p.parents, Path.home() / "Logbook"]
        for c in candidates:
            if (c / "logbook.json").exists() and code_checkout_marker(c) is None:
                return cls(c)
        raise FileNotFoundError("no logbook found; run `logbook init`")

    @property
    def meta(self) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self.meta_path.read_text(encoding="utf-8"))
        return data

    def _save_meta(self, meta: dict[str, Any]) -> None:
        tmp = self.meta_path.with_name("logbook.json.tmp")
        tmp.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.meta_path)  # never a half-written logbook.json

    def _check_format(self, meta: dict[str, Any]) -> None:
        """verify and every writer refuse a record hashed by another rule (SPEC §3.1)."""
        found = meta.get("format")
        if found == FORMAT:
            return
        if found == OLD_FORMAT:
            raise FormatError(MIGRATE_MESSAGE)
        raise FormatError(f"format {found!r} is not {FORMAT}; this logbook needs another version of the code")

    # -- reading -------------------------------------------------------------
    def files(self) -> list[Path]:
        return sorted(self.log_dir.glob("*/*.jsonl"))

    def lines(self) -> Iterator[Line]:
        """All lines in chain order (by seq). Files partition by month of `at`; backfilled
        history lands in old files, so file order is not chain order."""
        rows = list(self.lines_unsorted())
        rows.sort(key=lambda r: r.get("seq", 0))
        return iter(rows)

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
        if not (self.root / INDEX_FILE).exists():
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

    def verify(self, warnings: list[str] | None = None) -> tuple[int, str, list[str]]:
        """(seq, head, errors) of the files, never the index. What this release only warns about
        (SPEC §2 timestamps with a numeric offset) is appended to `warnings` when a list is given."""
        meta = self.meta
        self._check_format(meta)
        try:
            seq, head, errors = verify_lines(self.lines(), warnings)
        except ValueError as e:  # a line that is not one JSON object with distinct keys (SPEC §2)
            return 0, GENESIS, [str(e)]
        if meta["seq"] != seq or meta["head"] != head:
            errors.append(
                f"logbook.json says seq={meta['seq']} head={meta['head'][:12]}…, "
                f"files say seq={seq} head={head[:12]}…"
            )
        return seq, head, errors

    # -- writing -------------------------------------------------------------
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
        meta = self.meta
        self._check_format(meta)
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
                idx.add([row(line, meta["timezone"], self._relative(path), offset)], meta)
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

    def append_many(
        self,
        drafts: Iterable[dict[str, Any]],
        progress: Callable[[int, float], None] | None = None,
    ) -> int:
        """Append drafts in order; returns how many were written.

        A draft whose (source, payload.raw_id) is already in the log is skipped, so re-adding the
        same export appends nothing. Drafts without a raw_id are never deduped.

        Built for millions of drafts: drafts are taken META_EVERY at a time, each batch is deduped
        with one SELECT against the index, the chain is computed in memory, month files stay open,
        and at the end of every batch the lines are written and flushed, then logbook.json is
        saved, then the index is extended (a checkpoint). Lines never reach disk ahead of a
        checkpoint, so an interruption leaves the log exactly as it was at the last checkpoint —
        a valid chain — and re-adding the same export finishes the job. On a Python-level
        interruption (Ctrl-C, an exception in an adapter) the drafts already taken are still
        written, so nothing already drafted is lost. `progress(count, elapsed_seconds)` is called
        every PROGRESS_EVERY lines.

        Chain order is import order: `seq` and `prev` follow the order the drafts arrive in,
        and `at` is the event time. A batch is never sorted."""
        meta = self.meta
        self._check_format(meta)
        idx = self.index()
        tz = str(meta["timezone"])
        seq, head = meta["seq"], meta["head"]
        handles: dict[Path, BinaryIO] = {}
        n, started = 0, time.monotonic()
        it = iter(drafts)

        def checkpoint(lines: list[tuple[Path, Line]]) -> None:
            pending: dict[Path, list[Line]] = {}
            for path, line in lines:
                pending.setdefault(path, []).append(line)
            rows: list[Row] = []
            for path, batch in pending.items():
                fh = handles.get(path)
                if fh is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fh = handles[path] = path.open("ab")
                    fh.seek(0, os.SEEK_END)
                rel, offset = self._relative(path), fh.tell()
                encoded = [_dumps(line).encode("utf-8") for line in batch]
                for line, raw in zip(batch, encoded, strict=True):
                    rows.append(row(line, tz, rel, offset))
                    offset += len(raw)
                fh.write(b"".join(encoded))
                fh.flush()
                os.fsync(fh.fileno())  # SPEC §3 write order: every line is on disk before logbook.json
            if (meta["seq"], meta["head"]) != (seq, head):
                meta["seq"], meta["head"] = seq, head
                self._save_meta(meta)
                idx.add(rows, meta)

        try:
            while True:
                batch, error = _take(it, META_EVERY)
                keys = {key for d in batch if (key := _dedupe_key(d)) is not None}
                found = idx.existing(keys) if keys else set()
                lines: list[tuple[Path, Line]] = []
                for d in batch:
                    key = _dedupe_key(d)
                    if key is not None:
                        if key in found:
                            continue
                        found.add(key)
                    line = self._line(meta, seq + 1, head, **d)
                    lines.append((self._path_for(line["at"]), line))
                    seq, head = line["seq"], line["hash"]
                    n += 1
                    if progress is not None and n % PROGRESS_EVERY == 0:
                        progress(n, time.monotonic() - started)
                checkpoint(lines)
                if error is not None:
                    raise error
                if len(batch) < META_EVERY:
                    break
        finally:
            for fh in handles.values():
                fh.close()
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
        handles: dict[Path, TextIO] = {}
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
                path = tmp / line["at"][:4] / f"{line['at'][5:7]}.jsonl"
                fh = handles.get(path)
                if fh is None:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    fh = handles[path] = path.open("a", encoding="utf-8")
                fh.write(_dumps(line))
                if progress is not None and n % MIGRATE_PROGRESS_EVERY == 0:
                    progress(n, time.monotonic() - started)
            if (n, old_prev) != (meta["seq"], old_head):
                raise ValueError(
                    f"logbook.json says seq={meta['seq']} head={old_head[:12]}…, files say seq={n} "
                    f"head={old_prev[:12]}…; {NOT_INTACT}"
                )
            for fh in handles.values():
                fh.flush()
                os.fsync(fh.fileno())
                fh.close()
        except BaseException:
            for fh in handles.values():
                fh.close()
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
        if (
            self.root / INDEX_FILE
        ).exists():  # ADR 0007: disposable; closed through the registry, then deleted
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

    def _lines_by_seq(self) -> Iterator[Line]:
        """Every line in chain order with one line in memory at a time: a first pass notes where
        each seq lives (two integers per line), a second reads them back in seq order."""
        files = self.files()
        seqs: array[int] = array("q")
        places: array[int] = array("q")  # file number << 40 | byte offset
        for file_no, f in enumerate(files):
            with f.open("rb") as fh:
                offset = 0
                for n, raw in enumerate(fh, 1):
                    if raw.strip():
                        seqs.append(int(self._parse(f, n, raw).get("seq", 0)))
                        places.append((file_no << 40) | offset)
                    offset += len(raw)
        order = sorted(range(len(seqs)), key=seqs.__getitem__)
        handles = [f.open("rb") for f in files]
        try:
            for i in order:
                fh = handles[places[i] >> 40]
                fh.seek(places[i] & ((1 << 40) - 1))
                yield parse_line(fh.readline())
        finally:
            for fh in handles:
                fh.close()

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
    ) -> Line:
        """A complete, hashed line; nothing is written."""
        if "schema" not in payload:
            raise ValueError("payload.schema is required")
        if tier not in (1, 2, 3):
            raise ValueError("tier must be 1, 2 or 3")
        line: Line = {
            "id": uuid7(),
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
        return line

    def _parse(self, path: Path, n: int, raw: str | bytes) -> Line:
        """One stored line as a dict; a bad one is reported by file and line number."""
        try:
            return parse_line(raw)
        except ValueError as e:
            raise ValueError(f"{self._relative(path)} line {n}: {e}") from e

    def _path_for(self, at: str) -> Path:
        year, month = at[:4], at[5:7]
        return self.log_dir / year / f"{month}.jsonl"

    def _relative(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()


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


def _dedupe_key(line: dict[str, Any]) -> tuple[str, str] | None:
    raw_id = (line.get("payload") or {}).get("raw_id")
    return (str(line.get("source")), str(raw_id)) if raw_id is not None else None
