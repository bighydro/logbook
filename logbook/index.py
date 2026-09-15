"""index.sqlite — a disposable locator for the log (ADR 0001, ADR 0007).

The files are the record. This is a cache of where every line is (file, byte offset) and the few
fields readers filter on, so `show`, `export --day` and dedupe do not parse the whole log. Lines
are always read back from the files; nothing is ever served from here. It records the chain head,
seq and timezone it was built at; a reader that finds it missing, unreadable, or built at another
head or timezone rebuilds it from the files. `verify` never opens it. Deleting it loses nothing."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .chain import Line

if TYPE_CHECKING:
    from .store import Logbook

FILE_NAME = "index.sqlite"
SCHEMA_VERSION = "1"
BUILD_PROGRESS_EVERY = 100_000  # rebuild: lines between progress reports
INSERT_EVERY = 10_000  # rebuild: rows per INSERT

SCHEMA = (
    "CREATE TABLE lines ("
    " seq INTEGER PRIMARY KEY, id TEXT NOT NULL, at TEXT NOT NULL, day_local TEXT NOT NULL,"
    " kind TEXT NOT NULL, source TEXT NOT NULL, tier INTEGER NOT NULL, raw_id TEXT,"
    " file TEXT NOT NULL, offset INTEGER NOT NULL)",
    "CREATE INDEX lines_day_local ON lines (day_local)",
    "CREATE INDEX lines_source_raw_id ON lines (source, raw_id)",
    "CREATE INDEX lines_kind_at ON lines (kind, at)",
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
)
INSERT = "INSERT INTO lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"

Row = tuple[int, str, str, str, str, str, int, str | None, str, int]
Located = tuple[str, int, Line]  # file (relative to the root, posix), byte offset, the line


def local_date(at: str, tz: str) -> str:
    """The calendar date of an RFC3339 UTC instant in the owner's timezone."""
    instant = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(UTC)
    return instant.astimezone(ZoneInfo(tz)).date().isoformat()


def row(line: Line, tz: str, file: str, offset: int) -> Row:
    raw_id = (line.get("payload") or {}).get("raw_id")
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
    )


class Index:
    """One connection to index.sqlite. Autocommit mode; every write is an explicit transaction."""

    def __init__(self, lb: Logbook):
        self.lb = lb
        self.path = lb.root / FILE_NAME
        self.db = sqlite3.connect(self.path, isolation_level=None)

    @classmethod
    def open(cls, lb: Logbook) -> Index:
        """Open, or replace a file SQLite cannot read (a crash, a stray file of that name)."""
        idx = cls(lb)
        try:
            idx.db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        except sqlite3.DatabaseError:
            idx.close()
            idx.path.unlink(missing_ok=True)
            idx = cls(lb)
        return idx

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> Index:
        return self

    def __exit__(self, *exc: object) -> None:
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

    def by_seq(self, seq: int) -> Line | None:
        found = self.db.execute("SELECT file, offset FROM lines WHERE seq = ?", (seq,)).fetchall()
        return self._read(found)[0] if found else None

    def retractions(self) -> list[Line]:
        """Every retraction line, in chain order (the (kind, at) index)."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'retraction' ORDER BY seq"
        ).fetchall()
        return self._read(found)

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
