"""`logbook repair fork`: a record whose month files hold two chains that fork at one head, diagnosed,
and with `--apply` the orphan chain moved out of the record. Nothing is deleted and no kept line is
re-serialised.

How a record gets there (#234): a long writer (a two-hour `sync`) reads the head when it starts; while
it walks, another command appends a correctly chained batch; the long writer then writes its own batch
into the month files chained from the head it read, and the index refuses the batch (`UNIQUE
constraint failed: lines.seq`) after the files already hold it. The files now carry two chains from
that head, `verify` reports every second line from the fork, and the index, which never took the bad
batch, still describes the good chain.

The diagnosis walks every line of every month file in seq order and links each line to the chain whose
last hash is its `prev`. Where two lines claim the same `prev` the chain forks: a *segment* ends there
and one segment per line begins, each remembering the segment and the line it forked from. A segment
with no child is a leaf, and the path from GENESIS to a leaf is a *candidate* for the record. The
record's chain is, in order: (a) the candidate the index agrees with (the index records the head it
was built at, SPEC §1; the candidate that head is on, when it is on exactly one); (b) with the index
absent, or behind the fork, the longest candidate; (c) when two candidates are equally long, no one:
the diagnosis says so and `--apply` refuses. Every segment off the record's chain is an *orphan chain*.

`--apply` copies every orphan line, in seq order, to `repair/<UTC stamp>-removed.jsonl` inside the
record folder, writes `repair/<UTC stamp>-report.json` with what the diagnosis found, then writes each
touched month file again without the orphan lines: the kept lines are the bytes they were, copied
through a temporary file and an atomic rename, fsynced. Then `logbook.json` is set to the record's
chain's last seq and head, the index is rebuilt and `verify` runs; its result is the command's.
It refuses when the record's chain cannot be told, when a line chains from no line of the record (a
break, not a fork), when a month file is cut inside a line, when an orphan line is sealed and cannot be
opened here, and when the files changed since the diagnosis. The dry run always works."""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
from array import array
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO

from . import sealing
from .chain import GENESIS, Line, is_sealed, parse_line
from .store import Logbook, OpenFiles, read_line_at

REPAIR_DIR = "repair"  # inside the record folder: what a repair moved out, and its report
SCHEMA = "repair-fork/v1"  # the report's schema
DRY_RUN = "nothing written — run with --apply to repair"
NOTHING = "nothing to repair"
CHANGED = "the record changed since the diagnosis; run `logbook repair fork` again"
PLACE_BITS = 40  # `places`: file number << 40 | byte offset, as `Logbook._lines_by_seq` packs it
OFFSET_MASK = (1 << PLACE_BITS) - 1
SPAN = "\u2013"  # the en dash between the first and last seq of a run


class Refused(Exception):
    """`--apply` will not run; the sentence says why. The dry run always works."""


@dataclass
class Segment:
    """A run of lines each chained from the one before, between two forks (or GENESIS and a leaf)."""

    id: int
    parent: int | None  # the segment of the line it forks from; None for the root and a detached one
    fork_seq: int  # the seq of the line it forks from, 0 for GENESIS
    fork_head: str  # the hash of that line, GENESIS for the root
    detached: bool = False  # its first line's `prev` is no line of the record: a break, not a fork
    first_seq: int = 0
    last_seq: int = 0
    head: str = GENESIS
    lines: int = 0
    bytes: int = 0
    sources: Counter[str] = field(default_factory=Counter)
    files: set[str] = field(default_factory=set)
    children: list[int] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "lines": self.lines,
            "first_seq": self.first_seq,
            "last_seq": self.last_seq,
            "head": self.head,
            "fork_seq": self.fork_seq,
            "fork_head": self.fork_head,
            "bytes": self.bytes,
            "sources": dict(sorted(self.sources.items())),
            "files": sorted(self.files),
        }


OrphanLine = tuple[int, int, int, str]  # file number, byte offset, byte length, hash: one orphan line


@dataclass
class Report:
    """What the diagnosis found. Counts, seqs and hashes only: never a line's contents."""

    segments: list[Segment]
    main: list[int] | None  # the record's chain as segment ids, root first; None when it cannot be told
    chosen_by: str  # "only", "index", "length", or "" when `main` is None
    candidates: list[list[int]]  # every leaf path, root first
    orphans: list[int]  # the segments off the record's chain, by fork then first seq
    detached: list[int]
    duplicates: int  # lines whose hash another line already carried
    unreadable: list[str]  # a month file cut inside a line, by file and line number (SPEC §3)
    index_state: str  # "agrees", "behind", "absent", "unknown"
    index_head: tuple[int, str] | None
    manifest: tuple[int, str]
    refusals: list[str]
    orphan_lines: list[OrphanLine]  # every orphan line, in seq order, for `apply`
    files: list[str]  # month files relative to the root, by file number

    @property
    def forks(self) -> list[tuple[int, str]]:
        """The (seq, hash) of every line more than one line chains from, by seq."""
        heads = {(s.fork_seq, s.fork_head) for s in self.segments if s.parent is not None}
        return sorted(heads)

    def path_lines(self, path: list[int]) -> int:
        return sum(self.segments[i].lines for i in path)

    def path_summary(self, path: list[int]) -> dict[str, Any]:
        last = self.segments[path[-1]]
        first = next((self.segments[i].first_seq for i in path if self.segments[i].lines), 0)
        return {
            "lines": self.path_lines(path),
            "first_seq": first,
            "last_seq": last.last_seq,
            "head": last.head,
        }

    @property
    def main_end(self) -> tuple[int, str] | None:
        """The record's chain's last (seq, head); None when the chain cannot be told."""
        if self.main is None:
            return None
        last = self.segments[self.main[-1]]
        return last.last_seq, last.head

    @property
    def orphan_count(self) -> int:
        return sum(self.segments[i].lines for i in self.orphans)

    def to_json(self, applied: bool, stamp: str) -> dict[str, Any]:
        main = None
        if self.main is not None:
            main = {**self.path_summary(self.main), "chosen_by": self.chosen_by}
        return {
            "schema": SCHEMA,
            "at": stamp,
            "applied": applied,
            "forks": [{"seq": seq, "head": head} for seq, head in self.forks],
            "main": main,
            "candidates": [self.path_summary(p) for p in self.candidates],
            "orphans": [self.segments[i].summary() for i in self.orphans],
            "detached": [self.segments[i].summary() for i in self.detached],
            "duplicates": self.duplicates,
            "unreadable": list(self.unreadable),
            "index": {
                "state": self.index_state,
                "seq": None if self.index_head is None else self.index_head[0],
                "head": None if self.index_head is None else self.index_head[1],
            },
            "manifest": {"seq": self.manifest[0], "head": self.manifest[1]},
            "refusals": list(self.refusals),
        }


@dataclass(frozen=True)
class Applied:
    """What `apply` did, and what `verify` said afterwards."""

    removed: int
    removed_path: Path
    report_path: Path
    files: list[str]  # the month files written again, relative to the root
    seq: int
    head: str
    indexed: int
    errors: list[str]


# -- the diagnosis --------------------------------------------------------------------------------------


def diagnose(lb: Logbook) -> Report:
    """Walk every line of every month file and link the lines into chains by `prev`; pick the
    record's chain by the rule in the module docstring. Reads the files and the index's recorded
    head; writes nothing. Memory is two integers per line and one per line for its segment,
    whatever the size of the record, as `Logbook._lines_by_seq` keeps it."""
    meta = lb.meta
    lb._check_format(meta)
    files = lb.files()
    relative = [lb._relative(f) for f in files]
    seqs, places, unreadable = _scan(lb, files)
    order = sorted(range(len(seqs)), key=seqs.__getitem__)  # stable: a seq's lines stay in file order
    index_head = _index_head(lb)
    root = Segment(0, None, 0, GENESIS)
    segments = [root]
    tails: dict[str, int] = {GENESIS: 0}  # the hash of each open segment's last line
    segment_of = array("i", bytes(4 * len(order)))
    index_segment: int | None = None
    duplicates = 0

    def begin(parent: int | None, fork_seq: int, fork_head: str, detached: bool) -> int:
        segment = Segment(len(segments), parent, fork_seq, fork_head, detached)
        segments.append(segment)
        if parent is not None:
            segments[parent].children.append(segment.id)
        return segment.id

    with _handles(files) as handles:
        pos = 0
        while pos < len(order):
            group: list[tuple[int, int, bytes, Line]] = []  # one seq: (position, file number, raw, line)
            seq = seqs[order[pos]]
            while pos < len(order) and seqs[order[pos]] == seq:
                i = order[pos]
                file_no, offset = places[i] >> PLACE_BITS, places[i] & OFFSET_MASK
                fh = handles.get(file_no)
                fh.seek(offset)
                raw = fh.readline()
                group.append((pos, file_no, raw, parse_line(raw)))
                pos += 1
            by_prev: dict[str, list[tuple[int, int, bytes, Line]]] = {}
            for member in group:
                by_prev.setdefault(str(member[3].get("prev")), []).append(member)
            for prev, members in by_prev.items():
                open_segment = tails.pop(prev, None)
                if open_segment is None:
                    targets = [begin(None, 0, prev, detached=True) for _ in members]
                elif len(members) == 1:
                    targets = [open_segment]
                else:  # a fork: the open segment ends at `prev`; one segment per line begins
                    fork_seq = segments[open_segment].last_seq
                    targets = [begin(open_segment, fork_seq, prev, detached=False) for _ in members]
                for (position, file_no, raw, line), target in zip(members, targets, strict=True):
                    segment = segments[target]
                    if not segment.lines:
                        segment.first_seq = seq
                    segment.last_seq, segment.head = seq, str(line.get("hash"))
                    segment.lines += 1
                    segment.bytes += len(raw)
                    segment.sources[str(line.get("source"))] += 1
                    segment.files.add(relative[file_no])
                    segment_of[position] = target
                    if segment.head in tails:
                        duplicates += 1
                    tails[segment.head] = target
                    if index_head is not None and segment.head == index_head[1]:
                        index_segment = target

    detached = [s.id for s in segments if s.detached]
    leaves = [s for s in segments if not s.children and not s.detached]
    candidates = [_path(segments, leaf.id) for leaf in leaves]
    main, chosen_by, index_state, refusals = _choose(segments, candidates, index_head, index_segment)
    on_main = set(main or ())
    orphans = sorted(  # nothing is an orphan until the record's chain is known
        (s.id for s in segments if main is not None and s.id not in on_main and not s.detached and s.id != 0),
        key=lambda i: (segments[i].fork_seq, segments[i].first_seq),
    )
    if detached:
        n = sum(segments[i].lines for i in detached)
        where = ", ".join(sorted({f for i in detached for f in segments[i].files}))
        refusals.append(
            f"{_plural(n, 'line')} chain from no line of the record ({where}): a break, not a fork;"
            " `repair fork` does not mend it"
        )
    if duplicates:
        refusals.append(
            f"{_plural(duplicates, 'line')} carry the hash of another line; `repair fork` cannot tell"
            " them apart"
        )
    for problem in unreadable:
        refusals.append(f"{problem}; `repair fork` does not mend a torn file")
    orphan_lines: list[OrphanLine] = []
    if main is not None:
        orphan_set = set(orphans)
        orphan_lines = [
            (places[order[p]] >> PLACE_BITS, places[order[p]] & OFFSET_MASK, 0, "")
            for p in range(len(order))
            if segment_of[p] in orphan_set
        ]
        orphan_lines = _measured(files, orphan_lines)
        refusals.extend(_sealed_refusals(lb, files, orphan_lines))
    return Report(
        segments=segments,
        main=main,
        chosen_by=chosen_by,
        candidates=candidates,
        orphans=orphans,
        detached=detached,
        duplicates=duplicates,
        unreadable=unreadable,
        index_state=index_state,
        index_head=index_head,
        manifest=(int(meta["seq"]), str(meta["head"])),
        refusals=refusals,
        orphan_lines=orphan_lines,
        files=relative,
    )


def _scan(lb: Logbook, files: list[Path]) -> tuple[array[int], array[int], list[str]]:
    """Pass one: where every line lives, two integers per line, as `Logbook._lines_by_seq` notes it.
    A line that is not one ends its file for the reader and is reported (SPEC §3, truncation)."""
    seqs: array[int] = array("q")
    places: array[int] = array("q")
    unreadable: list[str] = []
    for file_no, f in enumerate(files):
        with f.open("rb") as fh:
            offset = 0
            for n, raw in enumerate(fh, 1):
                if raw.strip():
                    try:
                        line = lb._parse(f, n, raw)
                    except ValueError as e:
                        unreadable.append(str(e))
                        break
                    seq = line.get("seq")
                    seqs.append(seq if isinstance(seq, int) and not isinstance(seq, bool) else 0)
                    places.append((file_no << PLACE_BITS) | offset)
                offset += len(raw)
    return seqs, places, unreadable


def _handles(files: list[Path]) -> OpenFiles[int, BinaryIO]:
    """At most OPEN_FILES month files open at once, by file number (`Logbook.OpenFiles`)."""
    return OpenFiles(lambda file_no: files[file_no].open("rb"))


def _index_head(lb: Logbook) -> tuple[int, str] | None:
    """The (seq, head) the index records it was built at; None when there is no index, or no
    readable one. Read directly: `Logbook.index()` would rebuild a stale index from the files, and
    files that hold two chains have no index."""
    path = lb.index_path
    if not path.exists():
        return None
    try:
        with contextlib.closing(sqlite3.connect(path)) as db:
            found = dict(db.execute("SELECT key, value FROM meta WHERE key IN ('seq', 'head')"))
    except sqlite3.DatabaseError:
        return None
    if "seq" not in found or "head" not in found:
        return None
    try:
        return int(found["seq"]), str(found["head"])
    except ValueError:
        return None


def _path(segments: list[Segment], leaf: int) -> list[int]:
    path = [leaf]
    while (parent := segments[path[-1]].parent) is not None:
        path.append(parent)
    path.reverse()
    return path


def _choose(
    segments: list[Segment],
    candidates: list[list[int]],
    index_head: tuple[int, str] | None,
    index_segment: int | None,
) -> tuple[list[int] | None, str, str, list[str]]:
    """The record's chain among the candidates: (main, chosen_by, index_state, refusals)."""
    index_state = "absent" if index_head is None else "unknown" if index_segment is None else "behind"
    if len(candidates) == 1:
        if index_segment is not None:
            index_state = "agrees"
        return candidates[0], "only", index_state, []
    if index_segment is not None:
        on = [path for path in candidates if index_segment in path]
        if len(on) == 1:
            return on[0], "index", "agrees", []
    by_length = sorted(candidates, key=lambda path: -sum(segments[i].lines for i in path))
    longest = sum(segments[i].lines for i in by_length[0])
    runner_up = sum(segments[i].lines for i in by_length[1])
    if longest > runner_up:
        return by_length[0], "length", index_state, []
    tied = sum(1 for path in candidates if sum(segments[i].lines for i in path) == longest)
    why = {
        "absent": "there is no index",
        "unknown": "the index was built at a head the files do not hold",
        "behind": "the index was built before the fork",
    }[index_state]
    return (
        None,
        "",
        index_state,
        [f"cannot tell which chain is the record: {tied} chains of {longest:,} lines each, and {why}"],
    )


def _measured(files: list[Path], orphan_lines: list[OrphanLine]) -> list[OrphanLine]:
    """Each orphan line with its byte length and hash, read back from its place."""
    measured: list[OrphanLine] = []
    with _handles(files) as handles:
        for file_no, offset, _length, _hash in orphan_lines:
            fh = handles.get(file_no)
            fh.seek(offset)
            raw = fh.readline()
            measured.append((file_no, offset, len(raw), str(parse_line(raw).get("hash"))))
    return measured


def _sealed_refusals(lb: Logbook, files: list[Path], orphan_lines: list[OrphanLine]) -> list[str]:
    """An orphan line that is sealed and will not open here (no identity, or one that does not
    open it) is one `--apply` refuses to move: the owner reads what leaves the chain."""
    sealed, unopened = 0, 0
    with _handles(files) as handles:
        for file_no, offset, _length, _hash in orphan_lines:
            line = read_line_at(handles.get(file_no), offset)
            if not is_sealed(line):
                continue
            sealed += 1
            try:
                if is_sealed(lb.opened(line)):
                    unopened += 1
            except (sealing.SealError, sealing.MissingExtra):
                unopened += 1
    if not unopened:
        return []
    return [
        f"{unopened} of the {_plural(sealed, 'sealed orphan line')} cannot be read here"
        f" (no identity at {lb.identity_file} that opens them); nothing is moved unread"
    ]


def orphan_bytes(lb: Logbook, report: Report) -> Iterator[bytes]:
    """The stored bytes of every orphan line, in seq order, as `--apply` moves them."""
    files = [lb.root / f for f in report.files]
    with _handles(files) as handles:
        for file_no, offset, length, _hash in report.orphan_lines:
            fh = handles.get(file_no)
            fh.seek(offset)
            yield fh.read(length)


def describe(report: Report) -> Iterator[str]:
    """The diagnosis as `logbook repair fork` prints it: counts, seqs and hash prefixes, never a
    line's contents; sources by name."""
    segments = report.segments
    sound = not (report.forks or report.detached or report.duplicates or report.unreadable)
    if sound and report.main is not None:
        end = report.path_summary(report.main)
        if not end["lines"]:
            yield f"no lines; {NOTHING}"
            return
        yield f"one chain: {_run(end)}, head {_short(end['head'])}; {NOTHING}"
        yield from _manifest_line(report)
        return
    for seq, head in report.forks:
        continuing = sum(
            1 for s in segments if s.parent is not None and (s.fork_seq, s.fork_head) == (seq, head)
        )
        yield f"fork at seq {seq}, head {_short(head)}: {continuing} chains continue from it"
    if report.main is not None:
        end = report.path_summary(report.main)
        why = {
            "only": "the only chain",
            "index": "the index agrees (its head is on it)",
            "length": f"the longer chain ({_index_words(report)})",
        }[report.chosen_by]
        yield f"  main chain: {_run(end)}, head {_short(end['head'])}; {why}"
    else:
        for path in report.candidates:
            end = report.path_summary(path)
            yield f"  candidate chain: {_run(end)}, head {_short(end['head'])}"
    for i in report.orphans:
        s = segments[i]
        sources = ", ".join(f"{name} {n:,}" for name, n in sorted(s.sources.items()))
        yield (
            f"  orphan chain: {_run(s.summary())}, head {_short(s.head)}, forked at seq {s.fork_seq};"
            f" sources: {sources}; files: {', '.join(sorted(s.files))}"
        )
    for i in report.detached:
        s = segments[i]
        yield (
            f"  detached: {_run(s.summary())}, chained from {_short(s.fork_head)}, which no line of the"
            f" record carries; files: {', '.join(sorted(s.files))}"
        )
    yield from _manifest_line(report)
    for refusal in report.refusals:
        yield f"  {refusal}"


def _manifest_line(report: Report) -> Iterator[str]:
    seq, head = report.manifest
    end = report.main_end
    if end is None:
        yield f"logbook.json says seq={seq} head={_short(head)}"
    elif end == (seq, head):
        yield f"logbook.json says seq={seq} head={_short(head)}, the main chain's end"
    else:
        yield (
            f"logbook.json says seq={seq} head={_short(head)}; the main chain ends at seq={end[0]}"
            f" head={_short(end[1])}"
        )


def _index_words(report: Report) -> str:
    return {
        "absent": "there is no index",
        "unknown": "the index was built at a head the files do not hold",
        "behind": "the index was built before the fork",
        "agrees": "the index agrees",
    }[report.index_state]


# -- the repair -----------------------------------------------------------------------------------------


def apply(lb: Logbook, report: Report, stamp: str | None = None) -> Applied:
    """Move every orphan line out of the record, as the module docstring says. Raises `Refused`
    when the diagnosis has a refusal, or the files changed since it. `stamp` names the files under
    `repair/`: the UTC time now, as `YYYY-MM-DDTHHMMSSZ`."""
    if report.refusals:
        raise Refused("; ".join(report.refusals))
    if report.main is None:  # cannot happen without a refusal; said plainly all the same
        raise Refused("cannot tell which chain is the record")
    end = report.main_end
    assert end is not None
    files = [lb.root / f for f in report.files]
    spans: dict[int, list[OrphanLine]] = {}
    for orphan in report.orphan_lines:
        spans.setdefault(orphan[0], []).append(orphan)
    _confirm_unchanged(files, spans)
    stamp = stamp or datetime.now(UTC).strftime("%Y-%m-%dT%H%M%SZ")
    folder = lb.root / REPAIR_DIR
    folder.mkdir(exist_ok=True)
    removed_path = folder / f"{stamp}-removed.jsonl"
    report_path = folder / f"{stamp}-report.json"
    if removed_path.exists() or report_path.exists():
        raise Refused(f"{REPAIR_DIR}/{removed_path.name} already exists; run again in a second")
    with removed_path.open("wb") as out:
        for raw in orphan_bytes(lb, report):
            out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    _write_json(report_path, report.to_json(applied=True, stamp=stamp))
    _fsync_dir(folder)
    touched: list[str] = []
    for file_no in sorted(spans):
        _rewrite_without(files[file_no], sorted(spans[file_no], key=lambda span: span[1]))
        touched.append(report.files[file_no])
    meta = lb.meta  # read again: every other key kept (SPEC §1)
    meta["seq"], meta["head"] = end
    lb._save_meta(meta)
    indexed = lb.index_rebuild()
    seq, head, errors = lb.verify()
    return Applied(
        removed=len(report.orphan_lines),
        removed_path=removed_path,
        report_path=report_path,
        files=touched,
        seq=seq,
        head=head,
        indexed=indexed,
        errors=errors,
    )


def _confirm_unchanged(files: list[Path], spans: dict[int, list[OrphanLine]]) -> None:
    """Every orphan line is still the bytes the diagnosis measured, at its place: the cut is then
    exactly those bytes and no kept line is touched."""
    for file_no, file_spans in spans.items():
        with files[file_no].open("rb") as fh:
            for _file_no, offset, length, expected in file_spans:
                fh.seek(offset)
                raw = fh.readline()
                if len(raw) != length:
                    raise Refused(CHANGED)
                try:
                    found = parse_line(raw).get("hash")
                except ValueError:
                    raise Refused(CHANGED) from None
                if found != expected:
                    raise Refused(CHANGED)


def _rewrite_without(path: Path, spans: list[OrphanLine], chunk: int = 1 << 20) -> None:
    """The month file again without the byte spans, every other byte as it was: through a
    temporary file beside it, flushed and fsynced, then renamed into place."""
    tmp = path.with_name(path.name + ".repairing")
    tmp.unlink(missing_ok=True)
    with path.open("rb") as src, tmp.open("wb") as dst:
        position = 0
        for _file_no, offset, length, _hash in spans:
            if offset < position:
                raise Refused(CHANGED)  # overlapping spans: not what the diagnosis measured
            _copy(src, dst, offset - position, chunk)
            src.seek(offset + length)
            position = offset + length
        _copy(src, dst, None, chunk)
        dst.flush()
        os.fsync(dst.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _copy(src: BinaryIO, dst: BinaryIO, count: int | None, chunk: int) -> None:
    """`count` bytes from `src` to `dst` (to the end when None), a chunk at a time."""
    while count is None or count > 0:
        data = src.read(chunk if count is None else min(chunk, count))
        if not data:
            if count:
                raise Refused(CHANGED)  # the file is shorter than the diagnosis measured
            return
        dst.write(data)
        if count is not None:
            count -= len(data)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    with path.open("wb") as out:
        out.write((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        out.flush()
        os.fsync(out.fileno())


def _fsync_dir(folder: Path) -> None:
    """The directory entry on disk too (a rename is durable once its directory is); Windows has no
    directory handles to fsync and makes the rename durable itself."""
    if os.name == "nt":
        return
    fd = os.open(folder, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _run(summary: dict[str, Any]) -> str:
    """`N lines, seq a..b` of a chain or segment summary, with the en dash between the seqs."""
    return f"{_plural(summary['lines'], 'line')}, seq {summary['first_seq']}{SPAN}{summary['last_seq']}"


def _short(digest: str) -> str:
    return f"{digest[:12]}…"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" if n == 1 else f"{n:,} {word}s"
