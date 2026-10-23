"""index.sqlite — a disposable locator for the log (ADR 0001, ADR 0007), kept in the user's cache
directory, never in the record's folder (RFC 0029 §8: a copy of the folder, by any tool, carries no
locator).

The files are the record. This is a cache of where every line is (file, byte offset) and the few
fields readers filter, count or cluster on, so `show`, `export --day`, `stats` and dedupe do not
parse the whole log. A line is read back from the files whenever a reader needs its payload;
what is served from here alone is counts (`stats`) and the columns of a point a clustering needs
and nothing else — `subject`, `lat`, `lon` of a location line, `end` of an event or a note — so
`places propose` clusters two years of the owner's track without opening a month file
(`locations`, `evidence`). It records the chain head, seq and timezone it was built at; a reader
that finds it missing, unreadable, or built at another head, timezone or schema rebuilds it from
the files. `verify` never opens it. Deleting it loses nothing.

Sealed lines (RFC 0029): their payload columns (`raw_id`, `supersedes`, `entity`, `media`, `subject`,
`lat`, `lon`) are read from the opened payload when the identity is here, and `raw_id`, the one of them
that talks (a chat id is a phone number), is stored blinded: an HMAC under a 32-byte index key made
when the index is built and kept in its `meta`, sealed to the record's recipients. Dedupe compares
equals, so `(source, raw_id)` lookups cost what they did; an adversary with the file has HMACs under a
key they cannot open. The search table never holds the words of a sealed line. Without the identity
the sealed lines' payload columns are NULL and `meta` says `opened` is false; the first reader that has
the identity rebuilds."""

from __future__ import annotations

import contextlib
import math
import sqlite3
import time
from array import array
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO, NamedTuple
from zoneinfo import ZoneInfo

from . import sealing
from . import search as _search
from .chain import Line, is_sealed
from .day_start import KEY as DAY_START
from .day_start import MIDNIGHT, lenient, local_day

if TYPE_CHECKING:
    from .store import Logbook

FILE_NAME = "index.sqlite"
# 2: supersedes, entity and media columns, for `stats`; 3: media reads `content` too; 4: subject
# (ADR 0018), for `assets status`; 5: lat, lon and end, the columns `places propose` clusters from,
# and the (kind, day_local) index that cuts a window; 6: the `search` FTS5 table, the words of every
# line that carries any, for `logbook search`; 7: sealed lines (RFC 0029) — opened payload columns,
# a blinded raw_id, the index key and `opened` in meta, the file in the cache directory; 8:
# `observed_entities`, what the sources saw of every kind (RFC 0037), and `observed_people` and
# `observed_places` its views (`OBSERVED`)
SCHEMA_VERSION = "8"
BUILD_PROGRESS_EVERY = 100_000  # rebuild: lines between progress reports
INSERT_EVERY = 10_000  # rebuild: rows per INSERT
STREAM_EVERY = 1_000  # `stream`: lines read from the files at a time

SEARCH = "search"  # the FTS5 table: rowid is the line's seq; kind, tier and day cut a query, unindexed


def _fts5_available() -> bool:
    """Whether this Python's SQLite was built with FTS5 (every official build is; a distribution's
    may not be). Without it the index has no search table and `logbook search` says so."""
    with contextlib.closing(sqlite3.connect(":memory:")) as db:
        try:
            db.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
        except sqlite3.OperationalError:
            return False
    return True


HAS_FTS5 = _fts5_available()
NO_FTS5 = "this Python's SQLite has no FTS5 module, so the index holds no search table"

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
    *(
        (
            # unicode61: case and diacritics folded, no stemmer in any language — a word matches
            # itself and never a stem of it (`logbook/core/search.py`)
            f"CREATE VIRTUAL TABLE {SEARCH} USING fts5("
            "body, kind UNINDEXED, tier UNINDEXED, day UNINDEXED, tokenize = 'unicode61')",
        )
        if HAS_FTS5
        else ()
    ),
)
# Indexes added after schema 8, by read queries alone: a line by its id (`by_id`, `by_ids`, the Library's
# `/line/ID` and every photo), and the lines that supersede another, by kind (`superseded`, and the
# retractions every reader leaves out). What a column holds is unchanged, so the schema is too: a new
# index has them from `rebuild`, an existing one is given them by the Library, once, the first time it
# finds the index current (`Index.add_indexes`; never a writer, which must not wait on them).
ADDED = {
    "lines_id": "CREATE INDEX IF NOT EXISTS lines_id ON lines (id)",
    "lines_kind_supersedes": (
        "CREATE INDEX IF NOT EXISTS lines_kind_supersedes ON lines (kind, supersedes)"
        " WHERE supersedes IS NOT NULL"
    ),
}

# What the sources saw, one table for every kind (RFC 0037, decision 7): a row per observed person,
# org, idea, asset or place, keyed by the kind and its strongest identifier, built by the review that
# reads it (`logbook.contrib.people_review`, `places_review`, `entity_review`) and stamped per kind in
# `observed_entities_meta`, never a line. `ord` is the row's place in its kind's queue order; `hint`
# an org's guess at what it is (company, brand, community, personal), for ranking only; `labels`,
# `refs`, `sources`, `kinds`, `days`, `samples` and `people` (the canonical people seen on its lines)
# JSON, their shape the kind's; `lat` to `aboard` a place's own. `observed_people` and
# `observed_places` are the person and place rows under the columns those tables had until 0.7 (one
# release), so a reader of the old tables reads on unchanged.
OBSERVED = "observed_entities"
OBSERVED_META = "observed_entities_meta"
OBSERVED_VIEWS = ("observed_people", "observed_places")
OBSERVED_LEGACY = ("observed_meta", "observed_places_meta")  # the old stamp tables, dropped at rebuild
OBSERVED_COLUMNS = (
    "kind",
    "ord",
    "key_kind",
    "key_value",
    "name",
    "entity",
    "hint",
    "labels",
    "refs",
    "sources",
    "kinds",
    "days",
    "first",
    "last",
    "count",
    "tier",
    "samples",
    "people",
    "lat",
    "lon",
    "nights",
    "hours",
    "spread_m",
    "aboard",
)
HINTS = ("company", "brand", "community", "personal")
OBSERVED_SCHEMA = (
    f"CREATE TABLE {OBSERVED} (kind TEXT NOT NULL, ord INTEGER NOT NULL, key_kind TEXT NOT NULL,"
    " key_value TEXT NOT NULL, name TEXT, entity TEXT, hint TEXT, labels TEXT NOT NULL DEFAULT '{}',"
    " refs TEXT NOT NULL DEFAULT '[]', sources TEXT NOT NULL DEFAULT '{}', kinds TEXT NOT NULL DEFAULT '{}',"
    " days TEXT NOT NULL DEFAULT '[]', first TEXT, last TEXT, count INTEGER NOT NULL DEFAULT 0,"
    " tier INTEGER NOT NULL DEFAULT 0, samples TEXT NOT NULL DEFAULT '[]',"
    " people TEXT NOT NULL DEFAULT '[]', lat REAL, lon REAL, nights INTEGER, hours REAL, spread_m REAL,"
    " aboard TEXT)",
    f"CREATE INDEX {OBSERVED}_key ON {OBSERVED} (kind, key_kind, key_value)",
    f"CREATE TABLE {OBSERVED_META} (kind TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL,"
    " PRIMARY KEY (kind, key))",
    "CREATE VIEW observed_people AS SELECT key_kind, key_value, entity, labels, refs AS identifiers,"
    " sources, kinds, days, first, last, count AS lines, tier, samples"
    f" FROM {OBSERVED} WHERE kind = 'person'",
    # `rowid` is the queue's order, as the table's own rowid was
    "CREATE VIEW observed_places AS SELECT ord AS rowid, 'place:' || key_value AS id, lat, lon,"
    " count AS visits, nights, hours, first, last, spread_m, entity AS place, aboard, labels AS names,"
    f" samples AS lines FROM {OBSERVED} WHERE kind = 'place'",
)
INSERT_OBSERVED = (
    f"INSERT INTO {OBSERVED} ({', '.join(OBSERVED_COLUMNS)})"
    f" VALUES ({', '.join('?' * len(OBSERVED_COLUMNS))})"
)
INDEX_KEY = "index_key"  # meta: the blinding key, sealed to the recipients (RFC 0029 §8)
INSERT = "INSERT INTO lines VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
INSERT_TEXT = f"INSERT INTO {SEARCH} (rowid, body, kind, tier, day) VALUES (?, ?, ?, ?, ?)"

UTC_SECONDS = (
    "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]"  # a stamp to the second
)
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
TextRow = tuple[int, str, str, int, str]  # seq, body, kind, tier, day_local: one row of the search table
# One hit of `Index.search`: seq, day_local, rank (bm25, lower is better), snippet, file, offset
SearchRow = tuple[int, str, float, str, str, int]


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


def local_date(at: str, tz: str, start: object = None) -> str:
    """The local day of an RFC3339 UTC instant in the owner's timezone: its calendar date, or the date
    before when its wall clock is earlier than `start`, the record's `day_start` (RFC 0036,
    `day_start.local_day`; None is midnight). A value no reader accepts counts as midnight here: the
    index is extended inside `add`, which never groups by day, and every reader refuses that value
    before it reads the index (`day_start.of`)."""
    instant = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(UTC)
    return local_day(instant, ZoneInfo(tz), lenient(start)).isoformat()


def row(
    line: Line,
    tz: str,
    file: str,
    offset: int,
    payload: dict[str, Any] | None = None,
    blind: Callable[[str], str] | None = None,
    start: object = None,
) -> Row:
    """The columns `stats` counts are kept as the payload gives them, never interpreted: the id a
    line `supersedes` (SPEC §3), the entity id a resolution mints (RFC 0006), and the digest of
    the one attachment a line points at (`payload.media`, else `payload.content`, else `extra.media`;
    SPEC §1.1). The columns a clustering reads are the payload's `subject` (RFC 0001, ADR 0018; absent, empty
    or not a string is the owner, NULL), its `lat` and `lon` when both are finite numbers (a bool
    or a string is not one, as `stays.derive` reads them, so a line without a point has NULL), and
    the line's `end`. For a sealed line `payload` is the opened payload (None when there is no
    identity: every payload column NULL) and `raw_id` is stored through `blind`. `day_local` is the
    line's local day under the record's `day_start`, `start` (`local_date`)."""
    sealed = is_sealed(line)
    if payload is None:
        payload = {} if sealed else (line.get("payload") or {})
    raw_id = payload.get("raw_id")
    if raw_id is not None and sealed:
        raw_id = None if blind is None else blind(str(raw_id))
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
        local_date(line["at"], tz, start),
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


def text_row(line: Line, root: Path, line_row: Row) -> TextRow | None:
    """The search table's row for a line that carries words (`search.body_of`: the payload's
    strings, a transcript's text from the attachment store under `root`), beside its `line_row`;
    None for a line that carries none, or when this SQLite has no FTS5."""
    if not HAS_FTS5:
        return None
    body = _search.body_of(line, root)
    if body is None:
        return None
    return (line_row[0], body, line_row[4], line_row[6], line_row[3])


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
        self.path = lb.index_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db: sqlite3.Connection | None = sqlite3.connect(self.path, isolation_level=None)
        _open[self.path] += 1
        self._key: bytes | None = None  # the blinding key, once read or made (`_blinder`)

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

    def add_indexes(self) -> bool:
        """The indexes `ADDED` names, on an index built before them that is current with the record;
        nothing when they are there, or when the index is not current (the rebuild that comes makes
        them with the rest). Asked by a reader that serves many requests (the Library, on a GET, once
        per head), never by a writer: building one over millions of rows takes seconds, and a writer
        must not wait on it inside SQLite's busy timeout. So the build takes the record's writer lock
        itself, without waiting, and lets it go the moment the statements are done: a writer that
        arrives meanwhile waits on the lock, saying so in its one line, and then appends. Nothing is
        built while another process holds the lock, or the record folder takes no lock file (True:
        the next head tries again), nor while this process holds it (a write path) or another
        connection holds the file (no busy wait; False: ask again)."""
        from .store import Locked, _held  # store imports this module

        if not self.matches(self.lb.meta):
            return True
        try:
            present = {
                str(name)
                for (name,) in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
            }
            missing = [statement for name, statement in ADDED.items() if name not in present]
            if not missing:
                return True
            if _held.get(self.lb._lock_path()):
                return False
            with self.lb.writer(wait=False):
                if not self.matches(self.lb.meta):  # a writer came between the look and the lock
                    return True
                (waited,) = self.db.execute("PRAGMA busy_timeout").fetchone()
                self.db.execute("PRAGMA busy_timeout = 0")
                try:
                    for statement in missing:
                        self.db.execute(statement)
                finally:
                    self.db.execute(f"PRAGMA busy_timeout = {int(waited)}")
            return True
        except (Locked, OSError):
            return True
        except sqlite3.OperationalError:
            return False

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
        """Built at this logbook.json's head and seq, in its timezone, by this schema, for these
        recipients, and opened when the identity is here now."""
        try:
            stored = dict(self.db.execute("SELECT key, value FROM meta"))
        except sqlite3.DatabaseError:  # no meta table yet, or nothing SQLite can read
            return False
        stored.pop(INDEX_KEY, None)
        return stored == self._meta_of(meta, opened=bool(self.lb.identities))

    def indexed(self) -> tuple[int, str]:
        """The seq and head of the last line the index holds: what a reader of it reads up to."""
        try:
            stored = dict(self.db.execute("SELECT key, value FROM meta"))
            return int(stored.get("seq", 0)), str(stored.get("head", ""))
        except (sqlite3.DatabaseError, ValueError):
            return 0, ""

    def behind(self, meta: dict[str, Any]) -> bool:
        """The same index `meta` asks for, short of its last lines: built for this schema, zone,
        recipients and day, and opened or not as now, at a seq before `meta`'s. What a reader finds
        between a writer's `logbook.json` and its index (SPEC §3's order): a prefix of the record,
        every line of it whole. Anything else that does not match is not behind, only stale."""
        try:
            stored = dict(self.db.execute("SELECT key, value FROM meta"))
            stored.pop(INDEX_KEY, None)
            wanted = self._meta_of(meta, opened=bool(self.lb.identities))
            rest = {k: v for k, v in stored.items() if k not in ("head", "seq")}
            return rest == {k: v for k, v in wanted.items() if k not in ("head", "seq")} and int(
                stored["seq"]
            ) < int(meta["seq"])
        except (sqlite3.DatabaseError, KeyError, ValueError):
            return False

    @staticmethod
    def _meta_of(meta: dict[str, Any], opened: bool | None = None) -> dict[str, str]:
        """What the index records about the record it was built from. `opened` is whether the
        sealed lines' payload columns were filled; None leaves it out (a read-only comparison of
        the rest, as `doctor` makes it)."""
        found = {
            "schema": SCHEMA_VERSION,
            "head": str(meta["head"]),
            "seq": str(meta["seq"]),
            "timezone": str(meta["timezone"]),
            "recipients": ",".join(sorted(sealing.recipients_of(meta))),
        }
        if meta.get(DAY_START) not in (None, MIDNIGHT):  # the boundary `day_local` was derived under
            found[DAY_START] = str(meta[DAY_START])
        if opened is not None:
            found["opened"] = "true" if opened else "false"
        return found

    def _set_meta(self, meta: dict[str, Any]) -> None:
        key = self._key_sealed(meta)
        self.db.execute("DELETE FROM meta")
        self.db.executemany(
            "INSERT INTO meta VALUES (?, ?)", self._meta_of(meta, opened=bool(self.lb.identities)).items()
        )
        if key is not None:
            self.db.execute("INSERT INTO meta VALUES (?, ?)", (INDEX_KEY, key))

    # -- sealed lines (RFC 0029 §8) ----------------------------------------------------------------
    def _key_sealed(self, meta: dict[str, Any]) -> str | None:
        """The blinding key sealed to the record's recipients, for `meta`; None when the record
        names no recipients or the identity is not here (nothing is blinded then)."""
        recipients = sealing.recipients_of(meta)
        if not recipients or not self.lb.identities:
            return None
        return sealing.seal_index_key(self._blinding_key(meta), recipients)

    def _blinding_key(self, meta: dict[str, Any]) -> bytes:
        """The index key: read from `meta` when this index has one that opens, else made now."""
        if self._key is None:
            try:
                stored = self.db.execute("SELECT value FROM meta WHERE key = ?", (INDEX_KEY,)).fetchone()
            except sqlite3.DatabaseError:
                stored = None
            if stored is not None:
                with contextlib.suppress(sealing.SealError, ValueError):
                    self._key = sealing.open_index_key(str(stored[0]), self.lb.identities)
            if self._key is None:
                self._key = sealing.new_index_key()
        return self._key

    def _blinder(self, meta: dict[str, Any]) -> Callable[[str], str] | None:
        if not sealing.recipients_of(meta) or not self.lb.identities:
            return None
        key = self._blinding_key(meta)
        return lambda raw_id: sealing.blind(key, raw_id)

    def rows_of(self, line: Line, meta: dict[str, Any], file: str, offset: int) -> tuple[Row, TextRow | None]:
        """The row of one line, and its search row when it carries words: a sealed line's payload
        columns come from its opened payload when the identity is here, its `raw_id` blinded, and
        it never has a search row (its words stay sealed)."""
        tz, start = str(meta["timezone"]), meta.get(DAY_START)
        if not is_sealed(line):
            line_row = row(line, tz, file, offset, start=start)
            return line_row, text_row(line, self.lb.root, line_row)
        payload = self.lb.opened(line)["payload"] if self.lb.identities else None
        return row(line, tz, file, offset, payload, self._blinder(meta), start), None

    def _forms(self, source: str, raw_id: str) -> tuple[str, str, str]:
        """(source, raw_id, blinded raw_id): what the (source, raw_id) index may hold for a line of
        this source — plain for a tier-1 or unsealed line, blinded for a sealed one."""
        blind = self._blinder(self.lb.meta)
        return source, raw_id, raw_id if blind is None else blind(raw_id)

    # -- building ----------------------------------------------------------------------------
    def rebuild(self, progress: Callable[[int, float], None] | None = None) -> int:
        """Drop everything and index every line in one streaming pass over the files. Returns
        the number of lines. One transaction: a crash leaves the old index, which the head check
        then rejects. `progress(count, elapsed_seconds)` every BUILD_PROGRESS_EVERY lines."""
        meta = self.lb.meta  # read before the pass: a write during it leaves a head that no longer matches
        n, started = 0, time.monotonic()
        batch: list[Row] = []
        texts: list[TextRow] = []
        self.db.execute("BEGIN")
        try:
            for statement in (
                "DROP TABLE IF EXISTS lines",
                "DROP TABLE IF EXISTS meta",
                f"DROP TABLE IF EXISTS {SEARCH}",
                *SCHEMA,
                *ADDED.values(),
            ):
                self.db.execute(statement)
            self._observed_schema()
            for file, offset, line in self.lb.located_lines():
                line_row, words = self.rows_of(line, meta, file, offset)
                batch.append(line_row)
                if words is not None:
                    texts.append(words)
                n += 1
                if len(batch) >= INSERT_EVERY:
                    self.db.executemany(INSERT, batch)
                    self.db.executemany(INSERT_TEXT, texts)
                    batch.clear()
                    texts.clear()
                if progress is not None and n % BUILD_PROGRESS_EVERY == 0:
                    progress(n, time.monotonic() - started)
            self.db.executemany(INSERT, batch)
            self.db.executemany(INSERT_TEXT, texts)
            self._set_meta(meta)
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise
        return n

    # -- observed entities (RFC 0037): derived per kind by the reviews, stamped per kind ------------------
    def _observed_schema(self) -> None:
        """Drop what the observed tables were (the views, the table, its stamps, the tables of 0.6
        under the views' names) and create them again, empty, inside the caller's transaction."""
        found = dict(self.db.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')"))
        for name in (*OBSERVED_VIEWS, OBSERVED, OBSERVED_META, *OBSERVED_LEGACY):
            if found.get(name) in ("table", "view"):
                self.db.execute(f"DROP {'VIEW' if found[name] == 'view' else 'TABLE'} {name}")
        for statement in OBSERVED_SCHEMA:
            self.db.execute(statement)

    def observed_shape(self) -> bool:
        """Whether `observed_entities` is there with every column this code writes (`PRAGMA
        table_info`), and the two views beside it; a table of another shape is built again, never read."""
        try:
            columns = {str(row[1]) for row in self.db.execute(f"PRAGMA table_info({OBSERVED})")}
            views = {
                str(row[0]) for row in self.db.execute("SELECT name FROM sqlite_master WHERE type = 'view'")
            }
        except sqlite3.DatabaseError:
            return False
        return set(OBSERVED_COLUMNS) <= columns and set(OBSERVED_VIEWS) <= views

    def observed_stamp(self, kind: str) -> dict[str, str]:
        """The stamp the rows of `kind` were built under (the head, and what else their builder
        names); empty when there are none, or the table is not of this shape."""
        if not self.observed_shape():
            return {}
        try:
            return dict(self.db.execute(f"SELECT key, value FROM {OBSERVED_META} WHERE kind = ?", (kind,)))
        except sqlite3.DatabaseError:
            return {}

    def store_observed(self, kind: str, rows: Sequence[Mapping[str, Any]], stamp: Mapping[str, str]) -> None:
        """Replace the rows of `kind` and their stamp, in one transaction: each row a mapping of
        `OBSERVED_COLUMNS` (`kind` and `ord`, the row's place in the order given, filled in here; a
        column not given is its default). A table of another shape is made again first."""
        self.db.execute("BEGIN")
        try:
            if not self.observed_shape():
                self._observed_schema()
            self.db.execute(f"DELETE FROM {OBSERVED} WHERE kind = ?", (kind,))
            self.db.execute(f"DELETE FROM {OBSERVED_META} WHERE kind = ?", (kind,))
            defaults = {"labels": "{}", "refs": "[]", "sources": "{}", "kinds": "{}", "days": "[]",
                        "count": 0, "tier": 0, "samples": "[]", "people": "[]"}  # fmt: skip
            self.db.executemany(
                INSERT_OBSERVED,
                [
                    tuple(
                        kind
                        if column == "kind"
                        else n
                        if column == "ord"
                        else row.get(column, defaults.get(column))
                        for column in OBSERVED_COLUMNS
                    )
                    for n, row in enumerate(rows)
                ],
            )
            self.db.executemany(
                f"INSERT INTO {OBSERVED_META} VALUES (?, ?, ?)", [(kind, k, v) for k, v in stamp.items()]
            )
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def observed(self, kind: str) -> list[dict[str, Any]]:
        """The rows of `kind`, in their order, as mappings of `OBSERVED_COLUMNS`."""
        cursor = self.db.execute(
            f"SELECT {', '.join(OBSERVED_COLUMNS)} FROM {OBSERVED} WHERE kind = ? ORDER BY ord", (kind,)
        )
        return [dict(zip(OBSERVED_COLUMNS, row, strict=True)) for row in cursor.fetchall()]

    def add(self, rows: Iterable[Row], meta: dict[str, Any], texts: Iterable[TextRow] = ()) -> None:
        """Lines just appended, the search rows of those that carry words (`text_row`), and the
        head they brought logbook.json to."""
        self.db.execute("BEGIN")
        try:
            self.db.executemany(INSERT, rows)
            self.db.executemany(INSERT_TEXT, texts)
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

    def window_tally(self, since: str, until: str) -> tuple[list[tuple[int, str, int]], list[Place]]:
        """`window`, counted: (tier, kind, lines) of the lines whose stamp is a UTC one (`...Z`) and
        whose seconds lie strictly between those of `since` and `until`, which are inside whatever their
        fraction, in one statement; and, as `window` gives them, the rest the cut holds (the lines at
        either edge, and a stamp with an offset), for the caller to hold against the exact instants."""
        inside = (
            "substr(at, 1, 19) > ? AND substr(at, 1, 19) < ?"
            f" AND (at GLOB '{UTC_SECONDS}Z' OR (at GLOB '{UTC_SECONDS}.[0-9]*Z'"
            " AND substr(at, 21, length(at) - 21) NOT GLOB '*[^0-9]*'))"
        )
        bounds = (since[:19], until[:19])
        counted = self.db.execute(
            f"SELECT tier, kind, count(*) FROM lines WHERE {inside} GROUP BY tier, kind", bounds
        ).fetchall()
        rest = self.db.execute(
            "SELECT seq, id, at, kind, tier, file, offset FROM lines"
            f" WHERE substr(at, 1, 19) BETWEEN ? AND ? AND NOT ({inside}) ORDER BY seq",
            (*bounds, *bounds),
        ).fetchall()
        return (
            [(int(tier), str(kind), int(n)) for tier, kind, n in counted],
            [
                Place(int(seq), str(id_), str(at), str(kind), int(tier), str(file), int(offset))
                for seq, id_, at, kind, tier, file, offset in rest
            ],
        )

    def read(self, places: Iterable[tuple[str, int]], opened: bool = True) -> list[Line]:
        """The lines at these (file, offset) places, in the order given; `opened` False gives a
        sealed line as the file holds it (for a crossing package, which reseals it)."""
        return self._read(list(places), opened)

    def by_seq(self, seq: int) -> Line | None:
        found = self.db.execute("SELECT file, offset FROM lines WHERE seq = ?", (seq,)).fetchall()
        return self._read(found)[0] if found else None

    def by_seqs(self, seqs: Iterable[int]) -> dict[int, Line]:
        """seq → line for these seqs, read from the files (the primary key; a few hundred per
        statement); a seq the record has no line for is absent. For the few lines a reader joins
        by seq: the first and last point of each of the owner's stays (`places review`)."""
        wanted: list[int] = sorted(set(seqs))
        found: dict[int, Line] = {}
        for n in range(0, len(wanted), 500):
            chunk = wanted[n : n + 500]
            places = self.db.execute(
                f"SELECT file, offset FROM lines WHERE seq IN ({', '.join('?' * len(chunk))}) ORDER BY seq",
                chunk,
            ).fetchall()
            for line in self._read(places):
                found[int(line["seq"])] = line
        return found

    def by_id(self, line_id: str) -> Line | None:
        """The line with this id, or None; the first in chain order when the record holds the id
        twice (`id` is outside the hash, SPEC §2, so a writer could repeat one)."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE id = ? ORDER BY seq LIMIT 1", (line_id,)
        ).fetchall()
        return self._read(found)[0] if found else None

    def retractions(self) -> list[Line]:
        """Every retraction line, in chain order (the (kind, at) index)."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'retraction' ORDER BY seq"
        ).fetchall()
        return self._read(found)

    def resolutions(self, opened: bool = True) -> list[Line]:
        """Every resolution line (RFC 0006), in chain order (the (kind, at) index). Served by the
        `kind` column every index has had, so a record indexed before this method exists needs
        no rebuild. `opened` as `read`."""
        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = 'resolution' ORDER BY seq"
        ).fetchall()
        return self._read(found, opened)

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

    def stream(
        self,
        kind: str,
        first_day: str | None = None,
        last_day: str | None = None,
        after_seq: int | None = None,
        through_seq: int | None = None,
    ) -> Iterator[Line]:
        """`by_kind`, a thousand lines at a time: the same lines in the same chain order, read from the
        files as they are asked for, so a reader that keeps a few of a kind's million lines (an agent's
        chat among the messages, a promise among the words) never holds them all, nor where they all
        are: their seqs are read first, in one statement, so no read of the index stays open while the
        caller works; the lines are read through `read`, so an index that gates what it reads back
        gates these too. With `after_seq` and `through_seq`, only the lines appended in between (a
        reading kept between heads, brought forward), found by the primary key's range."""
        args: tuple[object, ...]
        if after_seq is None:  # the kind's lines through the (kind, day_local) index
            statement, args = (
                "SELECT seq FROM lines WHERE kind = ? AND day_local >= ? AND day_local <= ? AND seq <= ?"
                " ORDER BY seq",
                (
                    kind,
                    first_day or "",
                    last_day or "9999-12-31",
                    through_seq if through_seq is not None else 2**62,
                ),
            )
        else:  # the seq range first: `+` keeps the planner off the kind's index for a few new lines
            statement, args = (
                "SELECT seq FROM lines WHERE seq > ? AND seq <= ? AND +kind = ? AND +day_local >= ?"
                " AND +day_local <= ? ORDER BY seq",
                (after_seq or 0, through_seq or 2**62, kind, first_day or "", last_day or "9999-12-31"),
            )
        seqs = array(
            "q", (int(seq) for (seq,) in self.db.execute(statement, args))
        )  # eight bytes a line; where each is, a thousand at a time by the primary key
        for n in range(0, len(seqs), STREAM_EVERY):
            chunk = seqs[n : n + STREAM_EVERY].tolist()
            places = self.db.execute(
                f"SELECT file, offset FROM lines WHERE seq IN ({', '.join('?' * len(chunk))}) ORDER BY seq",
                chunk,
            ).fetchall()
            yield from self.read(places)

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

    def location_rows(
        self, first_day: str, last_day: str, tiers: Sequence[int] | None = None
    ) -> list[tuple[int, str, str, float | None, float | None, str | None, bool]]:
        """(seq, id, at, lat, lon, subject, retracted) of every location line whose local day is in
        [first_day, last_day], of every subject (None the owner), in file order; with `tiers`, those of
        them alone. A line without a point has no `lat` and `lon`. Served from the index's own columns."""
        gate = "" if tiers is None else f" AND tier IN ({', '.join('?' * len(tiers))})"
        found = self.db.execute(
            f"SELECT seq, id, at, lat, lon, subject, id IN ({RETRACTED}) FROM lines"
            f" WHERE kind = 'location' AND day_local BETWEEN ? AND ?{gate} ORDER BY file, offset",
            (first_day, last_day, *(int(t) for t in tiers or ())),
        ).fetchall()
        return [
            (int(seq), str(i), str(at), lat, lon, None if subject is None else str(subject), bool(gone))
            for seq, i, at, lat, lon, subject, gone in found
        ]

    def evidence(
        self, kinds: Sequence[str], first_day: str, last_day: str, tiers: Sequence[int] | None = None
    ) -> list[EvidenceRow]:
        """Every standing line of one of `kinds` whose local day is in [first_day, last_day], with
        its `end`, ordered by `at` then seq; a retracted line is left out; with `tiers`, those of
        them alone. Served from the index's own columns; nothing is read from the files."""
        gate = "" if tiers is None else f" AND tier IN ({', '.join('?' * len(tiers))})"
        cursor = self.db.execute(
            "SELECT kind, at, end FROM lines"
            f" WHERE kind IN ({', '.join('?' * len(kinds))}) AND day_local BETWEEN ? AND ?"
            f" AND id NOT IN ({RETRACTED}){gate} ORDER BY at, seq",
            (*kinds, first_day, last_day, *(int(t) for t in tiers or ())),
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
        """id → the seq of the line of this kind that `supersedes` it (the last one not retracted when
        several do), from the `supersedes` column, nothing read from the files. A superseder that is
        retracted supersedes nothing: a line is superseded while at least one line of its kind that is
        not retracted supersedes it, a superseder superseded in turn included (issue #321, the rule the
        Day reads by). Retractions are every retraction (RFC 0003: a retraction is never retracted)."""
        standing = "" if kind == "retraction" else f" AND id NOT IN ({RETRACTED})"
        found = self.db.execute(
            f"SELECT supersedes, seq FROM lines WHERE kind = ? AND supersedes IS NOT NULL{standing}"
            " ORDER BY seq",
            (kind,),
        ).fetchall()
        return {str(superseded): int(seq) for superseded, seq in found}

    def of_kind(
        self,
        kind: str,
        first_day: str | None = None,
        last_day: str | None = None,
        source: str | None = None,
        after_seq: int | None = None,
        files: tuple[str | None, str | None] = (None, None),
    ) -> Iterator[Line]:
        """Every line of one kind, streamed in file order (one sequential sweep of the files, each
        opened once), so a kind with a million lines never sits in memory at once; with
        `first_day` or `last_day`, only the lines whose local day is inside the bounds (the
        (kind, day_local) index serves the cut), so a reader of one year never opens the others'
        files; with `source`, only that source's; with `after_seq`, only the lines appended after
        that one (a reading brought forward from where it stopped, `people.read_whole`); with `files`,
        only the month files from the first (inclusive) to the second (exclusive), by the path's
        order, which is the months' (`people_drift.real_contacts`)."""
        from .store import read_line_at

        found = self.db.execute(
            "SELECT file, offset FROM lines WHERE kind = ? AND day_local >= ? AND day_local <= ?"
            " AND (? IS NULL OR source = ?) AND seq > ? AND file >= ? AND (? IS NULL OR file < ?)"
            " ORDER BY file, offset",
            (
                kind,
                first_day or "",
                last_day or "9999-12-31",
                source,
                source,
                after_seq or 0,
                files[0] or "",
                files[1],
                files[1],
            ),
        ).fetchall()
        handle: Any = None
        current: str | None = None
        try:
            for file, offset in found:
                if file != current:
                    if handle is not None:
                        handle.close()
                    handle, current = (self.lb.root / file).open("rb"), file
                yield self.lb.opened(read_line_at(handle, offset))
        finally:
            if handle is not None:
                handle.close()

    def appended(self, seq: int) -> dict[str, tuple[str, int, int]]:
        """What was appended after `seq`, by kind: the earliest local day, how many lines, and how
        many of them supersede another line. What a reading kept between heads asks before it
        brings itself forward (`people.read_whole`); nothing read from the files."""
        rows = self.db.execute(
            "SELECT kind, min(day_local), count(*), sum(supersedes IS NOT NULL) FROM lines WHERE seq > ?"
            " GROUP BY kind",
            (seq,),
        ).fetchall()
        return {str(kind): (str(day), int(n), int(sup or 0)) for kind, day, n, sup in rows}

    def appended_files(self, seq: int) -> dict[str, tuple[str, int]]:
        """What was appended after `seq`, by kind: the first month file (by the path's order, which is
        the months') a line of it went to, and how many of them supersede another line. What a reading
        kept in file order asks before it reads on from where it stopped (`entity_review`)."""
        rows = self.db.execute(
            "SELECT kind, min(file), sum(supersedes IS NOT NULL) FROM lines WHERE seq > ? GROUP BY kind",
            (seq,),
        ).fetchall()
        return {str(kind): (str(file), int(sup or 0)) for kind, file, sup in rows}

    def last_file(self, kind: str, seq: int) -> str:
        """The last month file (by the path's order) a line of `kind` up to `seq` is in; empty for none."""
        (found,) = self.db.execute(
            "SELECT max(file) FROM lines WHERE kind = ? AND seq <= ?", (kind, seq)
        ).fetchone()
        return str(found or "")

    def by_ids(self, ids: Iterable[str]) -> dict[str, Line]:
        """id → line for these line ids, read from the files; an id the record has no line for is
        absent. A few hundred ids per statement; `id` has no index of its own, so each statement
        is one pass over the table — for the few lines a reader joins by id (a keeper's photo),
        never for a window."""
        wanted: list[str] = sorted(set(ids))
        found: dict[str, Line] = {}
        for n in range(0, len(wanted), 500):
            chunk = wanted[n : n + 500]
            places = self.db.execute(
                f"SELECT file, offset FROM lines WHERE id IN ({', '.join('?' * len(chunk))}) ORDER BY seq",
                chunk,
            ).fetchall()
            for line in self._read(places):
                found.setdefault(str(line["id"]), line)
        return found

    def line_id(self, source: str, raw_id: str) -> str | None:
        """The id of the line with this (source, raw_id), or None; the first written when the log
        has more than one (an adapter that keys on raw_id never writes two)."""
        found = self.db.execute(
            "SELECT id FROM lines WHERE source = ? AND raw_id IN (?, ?) ORDER BY seq LIMIT 1",
            self._forms(source, raw_id),
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

    def source_days(
        self, first: str, last: str, tiers: Sequence[int] | None = None
    ) -> tuple[int, dict[str, int]]:
        """For `days`: how many local days in [first, last] have a line, and per source on how many
        of them it has one; retractions aside (a retraction is a mark on another line, not a source
        speaking). With `tiers`, only the lines of those tiers count (a gated reading's days). Two
        aggregates on the `day_local` index; nothing is read from the files."""
        where = "day_local BETWEEN ? AND ? AND kind != 'retraction'"
        params: list[object] = [first, last]
        if tiers is not None:
            where += f" AND tier IN ({','.join('?' * len(tiers))})"
            params += [int(t) for t in tiers]
        (logged,) = self.db.execute(
            f"SELECT count(DISTINCT day_local) FROM lines WHERE {where}", params
        ).fetchone()
        found = self.db.execute(
            f"SELECT source, count(DISTINCT day_local) FROM lines WHERE {where} GROUP BY source", params
        ).fetchall()
        return int(logged), {str(source): int(n) for source, n in found}

    def kind_source_days(
        self, first: str, last: str, kinds: Sequence[str], tiers: Sequence[int] | None = None
    ) -> tuple[int, dict[tuple[str, str], int]]:
        """For `readiness`: how many local days in [first, last] have a line, and per (kind, source)
        for the given kinds on how many of them it has one; retractions aside, and with `tiers` only
        the lines of those tiers, as `source_days`. Two aggregates on the `day_local` index."""
        where = "day_local BETWEEN ? AND ? AND kind != 'retraction'"
        params: list[object] = [first, last]
        if tiers is not None:
            where += f" AND tier IN ({','.join('?' * len(tiers))})"
            params += [int(t) for t in tiers]
        (logged,) = self.db.execute(
            f"SELECT count(DISTINCT day_local) FROM lines WHERE {where}", params
        ).fetchone()
        if not kinds:
            return int(logged), {}
        found = self.db.execute(
            f"SELECT kind, source, count(DISTINCT day_local) FROM lines WHERE {where}"
            f" AND kind IN ({','.join('?' * len(kinds))}) GROUP BY kind, source",
            [*params, *kinds],
        ).fetchall()
        return int(logged), {(str(kind), str(source)): int(n) for kind, source, n in found}

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

    def media_by_source(self) -> Iterator[tuple[str, str, int]]:
        """(source, digest, lines) for every attachment a standing line points at (the `media`
        column: `payload.media`, else `content`, else `extra.media`; a retracted line is out), one
        row per source and digest, streamed from the index alone (`attach status`)."""
        for source, sha256, n in self.db.execute(
            f"SELECT source, media, count(*) FROM lines WHERE media IS NOT NULL AND id NOT IN ({RETRACTED})"
            " GROUP BY source, media ORDER BY source, media"
        ):
            yield str(source), str(sha256), int(n)

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

    # -- searching: the FTS5 table says which, the files say what -----------------------------------
    def search(
        self,
        expression: str,
        max_tier: int,
        first_day: str,
        last_day: str,
        kinds: Sequence[str] | None,
        limit: int,
    ) -> list[SearchRow]:
        """The `limit` best hits of an FTS5 MATCH `expression` (`search.expression` builds one)
        among the lines at or below `max_tier` whose local day is in [first_day, last_day], of one
        of `kinds` when given, ranked by bm25 (the best first; the later line first among equals),
        each with its day, rank, a snippet of the matching words marked `search.MARK`, and where
        the line is. A retracted line is left out. The MATCH, the cut and the ranking run inside
        the table in one query (the subquery keeps the LIMIT at the match); the join to `lines` is
        one primary-key lookup per hit kept, so the cost is the matches of the words, never the
        size of the record. Nothing is read from the files here."""
        if not HAS_FTS5:
            raise RuntimeError(NO_FTS5)
        cut = "" if kinds is None else f" AND kind IN ({', '.join('?' * len(kinds))})"
        hidden = self.retraction_counts()["hidden"]  # the hits a retraction can take, fetched over the limit
        found = self.db.execute(
            "SELECT s.seq, l.day_local, s.rank, s.snippet, l.file, l.offset FROM ("
            f" SELECT rowid AS seq, rank AS rank, snippet({SEARCH}, 0, ?, ?, ?, ?) AS snippet FROM {SEARCH}"
            f" WHERE {SEARCH} MATCH ? AND tier <= ? AND day BETWEEN ? AND ?{cut}"
            " ORDER BY rank, rowid DESC LIMIT ?) AS s"
            f" JOIN lines l ON l.seq = s.seq WHERE l.id NOT IN ({RETRACTED})"
            " ORDER BY s.rank, s.seq DESC LIMIT ?",
            (
                _search.MARK[0],
                _search.MARK[1],
                _search.ELLIPSIS,
                _search.SNIPPET_TOKENS,
                expression,
                max_tier,
                first_day,
                last_day,
                *(kinds or ()),
                limit + hidden,
                limit,
            ),
        ).fetchall()
        return [
            (int(seq), str(day), float(rank), str(snippet), str(file), int(offset))
            for seq, day, rank, snippet, file, offset in found
        ]

    def existing(self, keys: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
        """Which of these (source, raw_id) keys the log already has: one SELECT for the batch,
        through a temp table so a batch of any size stays one statement."""
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS batch (source TEXT, raw_id TEXT, blinded TEXT)")
        self.db.execute("DELETE FROM batch")
        self.db.executemany("INSERT INTO batch VALUES (?, ?, ?)", (self._forms(*key) for key in keys))
        found = self.db.execute(
            "SELECT b.source, b.raw_id FROM batch b"
            " WHERE EXISTS (SELECT 1 FROM lines l WHERE l.source = b.source"
            " AND (l.raw_id = b.raw_id OR l.raw_id = b.blinded))"
        ).fetchall()
        self.db.execute("DELETE FROM batch")
        return {(str(source), str(raw_id)) for source, raw_id in found}

    def lines_of(self, keys: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Line]:
        """The line with each of these (source, raw_id) keys, read from the files, for the keys the
        log has: the first written when it has more than one. One SELECT for the batch, through
        the temp table `existing` uses, so an adapter checking an export against the record asks
        once per batch, never once per line. A sealed line's `raw_id` is stored blinded (RFC 0029
        §8); the batch carries both forms and either matches."""
        self.db.execute("CREATE TEMP TABLE IF NOT EXISTS batch (source TEXT, raw_id TEXT, blinded TEXT)")
        self.db.execute("DELETE FROM batch")
        self.db.executemany("INSERT INTO batch VALUES (?, ?, ?)", (self._forms(*key) for key in keys))
        found = self.db.execute(
            "SELECT b.source, b.raw_id, l.file, l.offset FROM lines l"
            " JOIN batch b ON b.source = l.source AND (l.raw_id = b.raw_id OR l.raw_id = b.blinded)"
            " ORDER BY l.seq"
        ).fetchall()
        self.db.execute("DELETE FROM batch")
        places: dict[tuple[str, str], tuple[str, int]] = {}
        for source, raw_id, file, offset in found:
            places.setdefault((str(source), str(raw_id)), (str(file), int(offset)))
        lines = self._read(list(places.values()))
        return dict(zip(places, lines, strict=True))

    def holders(self, raw_ids: Iterable[str]) -> dict[str, set[str]]:
        """raw_id → the sources of the lines that carry it, for these raw_ids, whatever their
        source: what `import trip-bundle` asks before it writes a received line, so a line the
        record already holds as its own (the same calendar invite, the same shared photo) or
        received before is skipped, never written twice (SPEC §3: nothing is rewritten). A sealed
        line's `raw_id` is stored blinded (RFC 0029 §8), so each raw_id is asked in both forms."""
        wanted = sorted(set(raw_ids))
        blind = self._blinder(self.lb.meta)
        forms = {raw_id: raw_id for raw_id in wanted}
        if blind is not None:
            forms.update({blind(raw_id): raw_id for raw_id in wanted})
        keys = sorted(forms)
        found: dict[str, set[str]] = {}
        for n in range(0, len(keys), 500):
            chunk = keys[n : n + 500]
            rows = self.db.execute(
                f"SELECT raw_id, source FROM lines WHERE raw_id IN ({', '.join('?' * len(chunk))})", chunk
            ).fetchall()
            for stored, source in rows:
                found.setdefault(forms[str(stored)], set()).add(str(source))
        return found

    def _read(self, where: list[tuple[str, int]], opened: bool = True) -> list[Line]:
        """The lines at these (file, offset) places, in the order given, opened when they are
        sealed and the identity is here (`Logbook.opened`) unless `opened` is False. At most
        `store.OPEN_FILES` files open at once, however many months the places span."""
        from .store import OpenFiles, read_line_at

        lines: list[Line] = []
        handles: OpenFiles[str, BinaryIO] = OpenFiles(lambda file: (self.lb.root / file).open("rb"))
        with handles:
            for file, offset in where:
                line = read_line_at(handles.get(file), offset)
                lines.append(self.lb.opened(line) if opened else line)
        return lines
