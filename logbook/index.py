"""index.sqlite — a disposable locator for the log (ADR 0001, ADR 0007).

The files are the record. This is a cache of where every line is (file, byte offset) and the few
fields readers filter, count or cluster on, so `show`, `export --day`, `stats` and dedupe do not
parse the whole log. A line is read back from the files whenever a reader needs its payload;
what is served from here alone is counts (`stats`) and the columns of a point a clustering needs
and nothing else — `subject`, `lat`, `lon` of a location line, `end` of an event or a note — so
`places propose` clusters two years of the owner's track without opening a month file
(`locations`, `evidence`). It records the chain head, seq and timezone it was built at; a reader
that finds it missing, unreadable, or built at another head, timezone or schema rebuilds it from
the files. `verify` never opens it. Deleting it loses nothing."""

from __future__ import annotations

import contextlib
import math
import sqlite3
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple
from zoneinfo import ZoneInfo

from .chain import Line

if TYPE_CHECKING:
    from .store import Logbook

FILE_NAME = "index.sqlite"
# 2: supersedes, entity and media columns, for `stats`; 3: media reads `content` too; 4: subject
# (ADR 0018), for `assets status`; 5: lat, lon and end, the columns `places propose` clusters from,
# and the (kind, day_local) index that cuts a window
SCHEMA_VERSION = "5"
BUILD_PROGRESS_EVERY = 100_000  # rebuild: lines between progress reports
INSERT_EVERY = 10_000  # rebuild: rows per INSERT

SCHEMA = (
    "CREATE TABLE lines ("
    " seq INTEGER PRIMARY KEY, id TEXT NOT NULL, at TEXT NOT NULL, day_local TEXT NOT NULL,"
    " kind TEXT NOT NULL, source TEXT NOT NULL, tier INTEGER NOT NULL, raw_id TEXT,"
    " file TEXT NOT NULL, offset INTEGER NOT NULL, supersedes TEXT, entity TEXT, media TEXT,"
    " subject TEXT, lat REAL, lon REAL, end TEXT)",
    "CREATE INDEX lines_day_local ON lines (day_local)",
    "CREATE INDEX lines_source_raw_id ON lines (source, raw_id)",
    "CREATE INDEX lines_kind_at ON lines (kind, at)",
    "CREATE INDEX lines_subject_at ON lines (subject, at)",
    "CREATE INDEX lines_kind_day_local ON lines (kind, day_local)",
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
INSERT = "INSERT INTO lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

RETRACTED = "SELECT supersedes FROM lines WHERE kind = 'retraction' AND supersedes IS NOT NULL"  # a subquery

Row = tuple[
    int,
    str,
    str,
    str,
    str,
    str,
    int,
    str | None,
    str,
    int,
    str | None,
    str | None,
    str | None,
    str | None,
    float | None,
    float | None,
    str | None,
]
Located = tuple[str, int, Line]  # file (relative to the root, posix), byte offset, the line


class Place(NamedTuple):
    """Where one line is and the columns a reader filters on without opening the file."""

    seq: int
    id: str
    at: str
    kind: str
    tier: int
    file: str
    offset: int


# What a clustering needs of one location line, served from the index alone (`locations`): its seq
# (`ids` gives the line id of the few a stay keeps), its `at` and the payload's numbers. Plain tuples
# as SQLite hands them over, no id: a million 36-character strings and a million named tuples are
# what a fetch of a two-year track would spend its time making.
LocationRow = tuple[int, str, float, float]  # seq, at, lat, lon
# What a clustering needs of a line that can promote a stay (`evidence`): kind, at, end (None for none).
EvidenceRow = tuple[str, str, str | None]


# Open connections per index file, in this process. Windows refuses to delete a file that has an
# open handle and Unix does not; `discard` consults this so the refusal is the same everywhere.
_open: Counter[Path] = Counter()


def local_date(at: str, tz: str) -> str:
    """The calendar date of an RFC3339 UTC instant in the owner's timezone."""
    instant = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(UTC)
    return instant.astimezone(ZoneInfo(tz)).date().isoformat()


def row(line: Line, tz: str, file: str, offset: int) -> Row:
    """The columns `stats` counts are kept as the payload gives them, never interpreted: the id a
    line `supersedes` (SPEC §3), the entity id a resolution mints (RFC 0006), and the digest of
    the one attachment a line points at (`payload.media`, else `payload.content`, else `extra.media`;
    SPEC §1.1). The columns a clustering reads are the payload's `subject` (RFC 0001, ADR 0018; absent, empty
    or not a string is the owner, NULL), its `lat` and `lon` when both are finite numbers (a bool
    or a string is not one, as `stays.derive` reads them, so a line without a point has NULL), and
    the line's `end`."""
    payload = line.get("payload") or {}
    raw_id = payload.get("raw_id")
    media = (
        _field(payload.get("media"), "sha256")
        or _field(payload.get("content"), "sha256")
        or _field(_field(payload.get("extra"), "media"), "sha256")
    )
    lat, lon = _coordinate(payload.get("lat")), _coordinate(payload.get("lon"))
    if lat is None or lon is None:
        lat = lon = None
    return (
        int(line["seq"]),
        str(line["id"]),
        str(line["at"]),
        local_date(line["at"], tz),
        str(line["kind"]),
        str(line["source"]),
        int(line["tier"]),
        None if raw_id is None else str(raw_id),
        file,
        offset,
        _string(payload.get("supersedes")),
        _string(_field(payload.get("entity"), "id")),
        _string(media),
        _string(payload.get("subject")),
        lat,
        lon,
        _string(line.get("end")),
    )


def _field(obj: object, key: str) -> object:
    return obj.get(key) if isinstance(obj, dict) else None


def _coordinate(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


class Index:
    """One connection to index.sqlite. Autocommit mode; every write is an explicit transaction.
    Close it when done (`with lb.index() as idx:`); the file is only ever deleted through
    `discard`, which closes first."""

    def __init__(self, lb: Logbook):
        self.lb = lb
        self.path = lb.root / FILE_NAME
        self._db: sqlite3.Connection | None = sqlite3.connect(self.path, isolation_level=None)
        _open[self.path] += 1

    @classmethod
    def open(cls, lb: Logbook) -> Index:
        """Open, or replace a file SQLite cannot read (a crash, a stray file of that name)."""
        idx = cls(lb)
        try:
            idx.db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            idx.discard()
            idx = cls(lb)
        return idx

    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            raise RuntimeError("this Index is closed")
        return self._db

    def close(self) -> None:
        """Idempotent. Every path that could delete the file goes through here first."""
        if self._db is not None:
            self._db.close()
            self._db = None
            _open[self.path] -= 1

    def discard(self) -> None:
        """Close, then delete the file. Refuses while another Index in this process is still
        open on it: deleting under an open handle fails on Windows and silently succeeds on
        Unix, and the same code must do the same thing on both."""
        self.close()
        if _open[self.path] > 0:
            raise RuntimeError(f"{self.path} is still open elsewhere in this process; close it first")
        self.path.unlink(missing_ok=True)

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:
        with contextlib.suppress(Exception):  # interpreter shutdown, or never fully constructed
            self.close()

    # -- state -------------------------------------------------------------------------------
    def matches(self, meta: dict[str, Any]) -> bool:
        """Built at this logbook.json's head and seq, in its timezone, by this schema."""
        try:
            stored = dict(self.db.execute("SELECT key, value FROM meta"))
        except sqlite3.DatabaseError:  # no meta table yet, or nothing SQLite can read
            return False
        return stored == self._meta_of(meta)

    @staticmethod
    def _meta_of(meta: dict[str, Any]) -> dict[str, str]:
        return {
            "schema": SCHEMA_VERSION,
            "head": str(meta["head"]),
            "seq": str(meta["seq"]),
            "timezone": str(meta["timezone"]),
        }

    def _set_meta(self, meta: dict[str, Any]) -> None:
        self.db.execute("DELETE FROM meta")
        self.db.executemany("INSERT INTO meta VALUES (?, ?)", self._meta_of(meta).items())

    # -- building ----------------------------------------------------------------------------
    def rebuild(self, progress: Callable[[int, float], None] | None = None) -> int:
        """Drop everything and index every line in one streaming pass over the files. Returns
        the number of lines. One transaction: a crash leaves the old index, which the head check
        then rejects. `progress(count, elapsed_seconds)` every BUILD_PROGRESS_EVERY lines."""
        meta = self.lb.meta  # read before the pass: a write during it leaves a head that no longer matches
        tz = str(meta["timezone"])
        n, started = 0, time.monotonic()
        batch: list[Row] = []
        self.db.execute("BEGIN")
        try:
            for statement in ("DROP TABLE IF EXISTS lines", "DROP TABLE IF EXISTS meta", *SCHEMA):
                self.db.execute(statement)
            for file, offset, line in self.lb.located_lines():
                batch.append(row(line, tz, file, offset))
                n += 1
                if len(batch) >= INSERT_EVERY:
                    self.db.executemany(INSERT, batch)
                    batch.clear()
                if progress is not None and n % BUILD_PROGRESS_EVERY == 0:
                    progress(n, time.monotonic() - started)
            self.db.executemany(INSERT, batch)
            self._set_meta(meta)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return n

    def add(self, rows: Iterable[Row], meta: dict[str, Any]) -> None:
        """Lines just appended, and the head they brought logbook.json to."""
        self.db.execute("BEGIN")
        try:
            self.db.executemany(INSERT, rows)
            self._set_meta(meta)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    # -- reading: the index says where, the files say what ------------------------------------
    def day(self, day_local: str) -> list[Line]:
        """Every line of one local day, in chain order."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE day_local = ? ORDER BY seq", (day_local,)
        ).fetchall()
        return self._read(found)

    def between(self, first: str, last: str) -> list[tuple[str, Line]]:
        """(day_local, line) for every line whose local day is in [first, last], in file order:
        one sequential sweep of the files, whatever the range. Callers order each day by seq."""
        found = self.db.execute(
            "SELECT day_local, file, offset FROM lines WHERE day_local BETWEEN ? AND ? ORDER BY file, offset",
            (first, last),
        ).fetchall()
        lines = self._read([(file, offset) for _day, file, offset in found])
        return [(str(day), line) for (day, _file, _offset), line in zip(found, lines, strict=True)]

    def window(self, since: str, until: str) -> list[Place]:
        """Where every line with `since` <= `at` < `until` is, in chain order, with the columns a
        caller filters on before reading. The SQL cut is on the first 19 characters of `at` (the
        seconds, which order as text whatever the fractional part); the caller applies the exact
        instants. Nothing is read from the files here."""
        found = self.db.execute(
            "SELECT seq, id, at, kind, tier, file, offset FROM lines"
            " WHERE substr(at, 1, 19) BETWEEN ? AND ? ORDER BY seq",
            (since[:19], until[:19]),
        ).fetchall()
        return [
            Place(int(seq), str(id_), str(at), str(kind), int(tier), str(file), int(offset))
            for seq, id_, at, kind, tier, file, offset in found
        ]

    def read(self, places: Iterable[tuple[str, int]]) -> list[Line]:
        """The lines at these (file, offset) places, in the order given."""
        return self._read(list(places))

    def by_seq(self, seq: int) -> Line | None:
        found = self.db.execute("SELECT file, offset FROM lines WHERE seq = ?", (seq,)).fetchall()
        return self._read(found)[0] if found else None

    def retractions(self) -> list[Line]:
        """Every retraction line, in chain order (the (kind, at) index)."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'retraction' ORDER BY seq"
        ).fetchall()
        return self._read(found)

    def resolutions(self) -> list[Line]:
        """Every resolution line (RFC 0006), in chain order (the (kind, at) index). Served by the
        `kind` column every index has had, so a record indexed before this method exists needs
        no rebuild."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'resolution' ORDER BY seq"
        ).fetchall()
        return self._read(found)

    def last_fix(self, subject: str) -> Line | None:
        """The standing location line of this `subject` (RFC 0001, ADR 0018) with the latest `at`
        (the latest seq when two share it), or None when the record has none: an asset's last
        known position. A line another line `supersedes` (a retraction, a correction) is out.
        Served by the (subject, at) index; one line is read from the files."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'location' AND subject = ?"
            " AND id NOT IN (SELECT supersedes FROM lines WHERE supersedes IS NOT NULL)"
            " ORDER BY at DESC, seq DESC LIMIT 1",
            (subject,),
        ).fetchall()
        return self._read(found)[0] if found else None

    def by_kind(self, kind: str, first_day: str | None = None, last_day: str | None = None) -> list[Line]:
        """Every line of one kind, in chain order, optionally only those whose local day is in
        [first_day, last_day] (either bound may be None). Flights, calendar entries: the kinds a
        reader needs whole."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = ? AND day_local >= ? AND day_local <= ?"
            " ORDER BY seq",
            (kind, first_day or "", last_day or "9999-12-31"),
        ).fetchall()
        return self._read(found)

    def locations(self, first_day: str, last_day: str, subject: str | None = None) -> list[LocationRow]:
        """The standing location points of one subject (None is the owner) for every location line
        whose local day is in [first_day, last_day] and whose payload has a point, ordered by `at`
        then seq (as text; a caller that compares instants sorts again). A retracted line is left
        out here (the `supersedes` column of the retraction lines). Served from the index's own
        columns: nothing is read from the files, whatever the range."""
        cursor = self.db.execute(
            "SELECT seq, at, lat, lon FROM lines"
            " WHERE kind = 'location' AND day_local BETWEEN ? AND ? AND lat IS NOT NULL AND lon IS NOT NULL"
            f" AND subject {'IS NULL' if subject is None else '= ?'} AND id NOT IN ({RETRACTED})"
            " ORDER BY at, seq",
            (first_day, last_day, *(() if subject is None else (subject,))),
        )
        rows: list[LocationRow] = cursor.fetchall()
        return rows

    def evidence(self, kinds: Sequence[str], first_day: str, last_day: str) -> list[EvidenceRow]:
        """Every standing line of one of `kinds` whose local day is in [first_day, last_day], with
        its `end`, ordered by `at` then seq; a retracted line is left out. Served from the index's
        own columns; nothing is read from the files."""
        cursor = self.db.execute(
            "SELECT kind, at, end FROM lines"
            f" WHERE kind IN ({', '.join('?' * len(kinds))}) AND day_local BETWEEN ? AND ?"
            f" AND id NOT IN ({RETRACTED}) ORDER BY at, seq",
            (*kinds, first_day, last_day),
        )
        rows: list[EvidenceRow] = cursor.fetchall()
        return rows

    def ids(self, seqs: Iterable[int]) -> dict[int, str]:
        """seq → line id for these seqs (the primary key; a few hundred per statement)."""
        wanted: list[int] = sorted(set(seqs))
        found: dict[int, str] = {}
        for n in range(0, len(wanted), 500):
            chunk = wanted[n : n + 500]
            found.update(
                self.db.execute(
                    f"SELECT seq, id FROM lines WHERE seq IN ({', '.join('?' * len(chunk))})", chunk
                ).fetchall()
            )
        return {int(seq): str(id_) for seq, id_ in found.items()}

    def of_source(
        self, kind: str, source: str, first_day: str, last_day: str, raw_id_prefix: str | None = None
    ) -> list[Line]:
        """Every line of one kind and source whose local day is in [first_day, last_day], in chain
        order, read from the files; with `raw_id_prefix`, only those whose `raw_id` starts with it
        (the (source, raw_id) index serves the cut). For the few lines a reader needs whole among
        a kind it otherwise clusters from the index: the Google Timeline visits."""
        cut, args = "", []
        if raw_id_prefix is not None:
            cut = " AND raw_id >= ? AND raw_id < ?"
            args = [raw_id_prefix, raw_id_prefix[:-1] + chr(ord(raw_id_prefix[-1]) + 1)]
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE source = ? AND kind = ? AND day_local BETWEEN ? AND ?"
            f"{cut} ORDER BY seq",
            (source, kind, first_day, last_day, *args),
        ).fetchall()
        return self._read(found)

    def superseded(self, kind: str) -> dict[str, int]:
        """id → the seq of the line of this kind that `supersedes` it (the last one when several
        do), from the `supersedes` column, nothing read from the files."""
        found = self.db.execute(
            "SELECT supersedes, seq FROM lines WHERE kind = ? AND supersedes IS NOT NULL ORDER BY seq",
            (kind,),
        ).fetchall()
        return {str(superseded): int(seq) for superseded, seq in found}

    def of_kind(self, kind: str) -> Iterator[Line]:
        """Every line of one kind, streamed in file order (one sequential sweep of the files, each
        opened once), so a kind with a million lines never sits in memory at once."""
        from .store import read_line_at

        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = ? ORDER BY file, offset", (kind,)
        ).fetchall()
        handle: Any = None
        current: str | None = None
        try:
            for file, offset in found:
                if file != current:
                    if handle is not None:
                        handle.close()
                    handle, current = (self.lb.root / file).open("rb"), file
                yield read_line_at(handle, offset)
        finally:
            if handle is not None:
                handle.close()

    def line_id(self, source: str, raw_id: str) -> str | None:
        """The id of the line with this (source, raw_id), or None; the first written when the log
        has more than one (an adapter that keys on raw_id never writes two)."""
        found = self.db.execute(
            "SELECT id FROM lines WHERE source = ? AND raw_id = ? ORDER BY seq LIMIT 1", (source, raw_id)
        ).fetchone()
        return None if found is None else str(found[0])

    def newest(self, source: str, kind: str) -> str | None:
        """The latest `at` among lines of this source and kind, or None when there are none."""
        found = self.db.execute(
            "SELECT MAX(at) FROM lines WHERE kind = ? AND source = ?", (kind, source)
        ).fetchone()
        return None if found is None or found[0] is None else str(found[0])

    def span(self, kind: str | None = None) -> tuple[str, str] | None:
        """The first and last local day with a line of `kind` (any kind when None); None when
        there is none. Nothing is read from the files."""
        found = self.db.execute(
            "SELECT min(day_local), max(day_local) FROM lines WHERE kind = coalesce(?, kind)", (kind,)
        ).fetchone()
        if found is None or found[0] is None:
            return None
        return str(found[0]), str(found[1])

    # -- counting: `stats`; one SELECT per table, nothing read from the files ----------------------
    def totals(self) -> tuple[int, str | None, str | None]:
        """(lines, first `at`, last `at`); the stamps are None on an empty record."""
        n, first, last = self.db.execute("SELECT count(*), min(at), max(at) FROM lines").fetchone()
        return int(n), first, last

    def kinds(self) -> list[dict[str, Any]]:
        """Per kind, most lines first: lines, first and last local day, distinct sources."""
        found = self.db.execute(
            "SELECT kind, count(*), min(day_local), max(day_local), count(DISTINCT source) FROM lines"
            " GROUP BY kind ORDER BY count(*) DESC, kind"
        ).fetchall()
        return [
            {"kind": kind, "lines": n, "first": first, "last": last, "sources": sources}
            for kind, n, first, last, sources in found
        ]

    def sources(self) -> list[dict[str, Any]]:
        """Per source, most lines first."""
        found = self.db.execute(
            "SELECT source, count(*) FROM lines GROUP BY source ORDER BY count(*) DESC, source"
        ).fetchall()
        return [{"source": source, "lines": n} for source, n in found]

    def years(self) -> list[dict[str, Any]]:
        """Lines per local year, oldest first."""
        found = self.db.execute(
            "SELECT substr(day_local, 1, 4), count(*) FROM lines GROUP BY 1 ORDER BY 1"
        ).fetchall()
        return [{"year": year, "lines": n} for year, n in found]

    def retraction_counts(self) -> dict[str, int]:
        """Retraction lines, and how many distinct lines they hide."""
        n, hidden = self.db.execute(
            "SELECT count(*), count(DISTINCT supersedes) FROM lines WHERE kind = 'retraction'"
        ).fetchone()
        return {"lines": int(n), "hidden": int(hidden)}

    def resolution_counts(self) -> dict[str, int]:
        """Resolution lines, and how many distinct entities they mint (an alias line mints none)."""
        n, entities = self.db.execute(
            "SELECT count(*), count(DISTINCT entity) FROM lines WHERE kind = 'resolution'"
        ).fetchone()
        return {"lines": int(n), "entities": int(entities)}

    def attachment_counts(self, present: Callable[[str], bool]) -> dict[str, int]:
        """Distinct attachments referenced, the lines that reference one, and how many of the
        digests `present` finds in the store. One SELECT, streamed; digests are never returned."""
        lines, referenced, found = 0, 0, 0
        for sha256, n in self.db.execute(
            "SELECT media, count(*) FROM lines WHERE media IS NOT NULL GROUP BY media"
        ):
            lines += int(n)
            referenced += 1
            if present(str(sha256)):
                found += 1
        return {"referenced": referenced, "lines": lines, "present": found}

    def activity(self, first_day: str, last_day: str) -> list[dict[str, Any]]:
        """Per source, most lines first, over the lines whose local day is in [first_day, last_day]
        (`sources --gaps`): lines, first and last `at`, the local days with a line, and the longest
        stretch between two consecutive lines as its (from, to) stamps, None for a source with one
        line. Three SELECTs over the columns, nothing read from the files; the stretch is one window
        query (LAG over each source's lines in `at` order), and SQLite's rule that bare columns
        beside max() come from the row holding the maximum picks the pair."""
        cut = (first_day, last_day)
        totals = self.db.execute(
            "SELECT source, count(*), min(at), max(at) FROM lines WHERE day_local BETWEEN ? AND ?"
            " GROUP BY source ORDER BY count(*) DESC, source",
            cut,
        ).fetchall()
        days: dict[str, list[str]] = {}
        for source, day in self.db.execute(
            "SELECT source, day_local FROM lines WHERE day_local BETWEEN ? AND ?"
            " GROUP BY source, day_local ORDER BY source, day_local",
            cut,
        ):
            days.setdefault(str(source), []).append(str(day))
        stretches = {
            str(source): (str(start), str(end))
            for source, start, end, _days in self.db.execute(
                "SELECT source, prev, at, max(julianday(at) - julianday(prev)) FROM ("
                " SELECT source, at, lag(at) OVER (PARTITION BY source ORDER BY at) AS prev"
                " FROM lines WHERE day_local BETWEEN ? AND ?) WHERE prev IS NOT NULL GROUP BY source",
                cut,
            )
        }
        return [
            {
                "source": str(source),
                "lines": int(n),
                "first": str(first),
                "last": str(last),
                "days": days.get(str(source), []),
                "stretch": stretches.get(str(source)),
            }
            for source, n, first, last in totals
        ]

    def existing(self, keys: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
        """Which of these (source, raw_id) keys the log already has: one SELECT for the batch,
        through a temp table so a batch of any size stays one statement."""
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS batch (source TEXT, raw_id TEXT)")
        self.db.execute("DELETE FROM batch")
        self.db.executemany("INSERT INTO batch VALUES (?, ?)", keys)
        found = self.db.execute(
            "SELECT b.source, b.raw_id FROM batch b"
            " WHERE EXISTS (SELECT 1 FROM lines l WHERE l.source = b.source AND l.raw_id = b.raw_id)"
        ).fetchall()
        self.db.execute("DELETE FROM batch")
        return {(str(source), str(raw_id)) for source, raw_id in found}

    def _read(self, where: list[tuple[str, int]]) -> list[Line]:
        """The lines at these (file, offset) places, in the order given. Each file opened once."""
        from .store import read_line_at

        handles: dict[str, Any] = {}
        lines: list[Line] = []
        try:
            for file, offset in where:
                fh = handles.get(file)
                if fh is None:
                    fh = handles[file] = (self.lb.root / file).open("rb")
                lines.append(read_line_at(fh, offset))
        finally:
            for fh in handles.values():
                fh.close()
        return lines
