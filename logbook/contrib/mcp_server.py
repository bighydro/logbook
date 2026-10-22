"""`logbook mcp`: the record as an MCP server for an agent on this machine, over stdio only.

The Model Context Protocol lets a host (an editor, a chat client, an agent runner) start a server
as a child process and call its tools over the process's own stdin and stdout. That is the one
transport here: no TCP, no socket, nothing listening. The host runs on the owner's machine under
the owner's command, and the record stays where it is.

Twelve read tools answer from the index and the readers every command already uses — `day`, `days`,
`trips`, `places`, `people`, `person`, `promises`, `gaps`, `search`, and the three that read the lines
themselves, `day_lines` (`logbook show DAY`, one object per line), `line` (one line in full, a
transcript's text from the attachment store included) and `digest` (`logbook digest`, the text as the
command prints it) — and two write tools go through `Logbook.append` and nothing else: `add_note` is
`logbook add "<sentence>"`, and `promise_done` is `logbook promises done <id>`. Two more write tools
are refused unless the owner allows them by name in the `mcp` entry's `write` (ADR 0022: orchestrators
reach the record only through the crossing): `sign_day` is `logbook day sign`, through the same
`signing.sign`, and `note_day` appends one `note/v1` line to a day. Both take the writer lock without
waiting and write only to a day inside the write window (`policy.mcp_door`).

Every tool's output passes the crossing gate of ADR 0016. `policy/crossing.json` names the `mcp`
destination and the highest tier that may cross to it, 1 unless the owner raises it (`policy.mcp_ceiling`);
the server reads the file on every call and never writes it. A line above the ceiling is left out of
every reading before anything is derived from it (`GatedIndex`: the readers see the record as if
the line were not there), and the response says how many lines were withheld, so a client knows the
answer is a partial one. Tier 3 crosses only when the policy allows it and the server was started with
`--allow-tier-3`: a policy edit alone never lets it through, as it never does for an export. A read
appends no `crossing/v1` line: nothing leaves the machine, and the record is not the place to log
an agent's every question. A `draft` line (RFC 0036) is a model's text about a day, derived through
the `dream` entry, and follows that entry as well as the door's: one above the entry's `max_tier`
today (lowered, expired, removed) is held back like a line above the ceiling, from every tool, and
counted the same way (`drafts.allowed`; derived material follows the policy, not the head). A person
draft follows the `relationship` entry it was written under instead (`Gate.people`). What
the server does log, one line per call on the `logbook.mcp` logger (stderr when serving; stdout is
the transport), is the tool's name, the day or id it was asked about and counts — never a line's
content, never a search's words, never a name."""

from __future__ import annotations

import contextlib
import json
import logging
import re
import sys
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import __version__
from ..core import day as day_reader
from ..core import (
    day_start,
    drafts,
    flights,
    notes,
    pages,
    people,
    policy,
    reading,
    rollup,
    sealing,
    signing,
    stays,
    transcripts,
    trips,
)
from ..core import days as days_reader
from ..core.chain import Line, is_sealed
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.index import RETRACTED, EvidenceRow, Index, LocationRow, Place
from ..core.resolve import Ref, labels
from ..core.store import (
    NOT_WAITING,
    RETRACTION,
    FormatError,
    HeadMoved,
    Locked,
    Logbook,
    now_utc,
    retractions,
    utc,
)
from . import digest as digest_reader
from . import gaps, people_drift, promises, reflect, sign_again
from .rows import _attendee, _clock, _line_text, _mail_person, _name, _ref_value

SERVER_NAME = "logbook"
DESTINATION = policy.MCP_DESTINATION
UNFLAGGED_CEILING = 2  # the most a policy alone lets cross; tier 3 needs `--allow-tier-3` too
SEARCH_LIMIT = 50
SEARCH_LIMIT_MAX = 500
READ_CHUNK = 200  # search: lines read from the files between checks of the hit count
EXTRA_MESSAGE = 'the mcp extra is not installed: pip install "openlogbook[mcp]"'
DAY = {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "a local day, YYYY-MM-DD"}
LOG = logging.getLogger("logbook.mcp")
QUOTED = re.compile(
    r"'[^']*'|\"[^\"]*\""
)  # what a refusal quotes back (a name, a day as typed): elided in the log
ELIDED = "'\u2026'"
# the arguments a log line may carry: a day, an id, a window, a switch; never `text`, never `name`
LOGGED = (
    "day", "kind", "date", "id", "from", "to", "since", "until", "year", "period", "kinds", "open", "limit"
)  # fmt: skip
PERIODS = ("day", "week")
NOTE_KINDS = (notes.NOTE, notes.PROPOSAL, notes.REFLECTION)  # `note_day(kind)`, in note/v1's `labels`
NOTE_MAX = 4000  # `note_day(text)`: the most characters one note through the door may hold
NOTE_SOURCE = "mcp"  # the source of a `note_day` line: written through the door, in the owner's words
NOTE_TIER = notes.TIER  # RFC 0010: a note/v1 line is tier 2, whoever writes it
ABOVE_LEFT = "above the door's ceiling left unconfirmed"  # `sign_day`'s `"all"` and first signature: a count
NOT_WAITED = "; the door does not wait for another writer, so nothing was written"
# `day_lines(kinds)`: a profile family -> the kinds in it (`calendar` is the `event/v1` lines)
FAMILIES: dict[str, tuple[str, ...]] = {
    "mail": ("mail",),
    "message": ("message",),
    "transcript": ("transcript",),
    "note": ("note",),
    "location": ("location",),
    "photo": ("photo",),
    "calendar": ("event",),
}


class ToolError(ValueError):
    """A call the record or the policy refuses; the message says why and is the whole answer."""


# -- the gate: the record as the ceiling lets a client see it ------------------------------------


# The gate as SQL over the index's columns: at or below the ceiling, and a draft at or below the dream's.
CUT = f"tier <= ? AND (kind != '{drafts.KIND}' OR tier <= ?)"
# A day's and a week's draft name their day and week as `subject`, a person's names the person (an
# entity id), a journey's and a call's synthesis an array, which the index keeps as no subject. The
# drafts whose `subject` is a string and neither are the ones read for their unit (`_sort_drafts`).
DAY_OR_WEEK = ("[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]", "[0-9][0-9][0-9][0-9]-W[0-9][0-9]")


@dataclass
class Gate:
    """The ceiling in force for one call and the seqs of the lines it held back. `drafts` is the
    `dream` entry's `max_tier` today, which a `draft` line must be at or under as well; a person
    draft is held to the `relationship` entry it was written under instead, `people` (RFC 0036
    amendment 1; `drafts.Allowed.of`). The index has no column for a draft's unit, so the SQL cut
    names by seq the person drafts the two entries judge apart: `own`, the ones their entry allows
    and the dream's would not, and `held`, the ones it withholds and the dream's would allow; None
    until the index has sorted them (`GatedIndex._sort_drafts`)."""

    max_tier: int
    withheld: set[int]
    drafts: int = policy.TIERS[-1]
    people: int | None = None  # the `relationship` entry's max_tier today; None: as `drafts`
    own: frozenset[int] | None = None
    held: frozenset[int] | None = None

    def allows(self, tier: int, kind: str, seq: int | None = None) -> bool:
        """At or below the ceiling; a draft also at or below the entry it was written under: the
        dream's, or the person draft's own when `seq` is one the two entries judge apart."""
        if tier > self.max_tier:
            return False
        if kind != drafts.KIND:
            return True
        if seq is not None and seq in (self.held or ()):
            return False
        if seq is not None and seq in (self.own or ()):
            return True
        return tier <= self.drafts

    def allows_line(self, line: Line) -> bool:
        """`allows` for a line in hand: a person draft by its own unit, read from the payload."""
        tier, kind = int(line["tier"]), str(line.get("kind"))
        if kind != drafts.KIND or self.people is None or drafts.unit_of(line) != drafts.UNIT_PERSON:
            return self.allows(tier, kind)
        return tier <= self.max_tier and tier <= self.people

    def entry_of(self, unit: object) -> tuple[str, int]:
        """The entry a draft of `unit` is held to and its `max_tier`, for a refusal's words."""
        if unit == drafts.UNIT_PERSON and self.people is not None:
            return drafts.PERSON_ENTRY, self.people
        return policy.DREAM_DESTINATION, self.drafts

    @property
    def sql(self) -> str:
        """`CUT`, with the person drafts the two entries judge apart named by seq when there are any."""
        if not self.own and not self.held:
            return CUT
        own = ", ".join(str(seq) for seq in sorted(self.own or ()))
        held = ", ".join(str(seq) for seq in sorted(self.held or ()))
        return (
            f"tier <= ? AND (kind != '{drafts.KIND}' OR seq IN ({own})"
            f" OR (tier <= ? AND seq NOT IN ({held})))"
        )

    @property
    def cut(self) -> tuple[int, int]:
        """The arguments of `CUT` (and of `sql`)."""
        return self.max_tier, self.drafts

    def shows(self, line: Line) -> bool:
        """A line the gate lets a client see, nothing counted: what `sign_day`'s `"all"` confirms, and
        its first signature without `confirm`."""
        return self.allows_line(line)

    def keep(self, line: Line) -> bool:
        """A line the gate allows. A retraction passes whatever its tier: it is a mark on another
        line, needed so that line stays hidden, and no tool ever returns one."""
        if self.allows_line(line) or line.get("kind") == RETRACTION:
            return True
        self.withheld.add(int(line["seq"]))
        return False

    def to_json(self) -> dict[str, Any]:
        return {"destination": DESTINATION, "max_tier": self.max_tier, "withheld": len(self.withheld)}


class GatedLogbook(Logbook):
    """A Logbook whose index serves only the lines the gate lets through. Every reader reads the
    record through `lb.index()`, so a reading made through this one never holds a line above the
    ceiling. Writing is the plain `Logbook.append`, untouched."""

    def __init__(self, root: Path, gate: Gate):
        super().__init__(root)
        self.gate = gate
        self.window_days = policy.WRITE_WINDOW_DAYS  # how far back a write tool may write (`call` sets it)

    def index(self) -> Index:
        idx = GatedIndex.open(self)
        if not idx.matches(self.meta):
            idx.rebuild()
        return idx


class GatedIndex(Index):
    """The index with the ceiling applied to everything it hands out: every line it reads back,
    every row it serves from its own columns, every aggregate. What it filters, it counts."""

    def __init__(self, lb: Logbook):
        if not isinstance(lb, GatedLogbook):
            raise TypeError("a GatedIndex is opened through a GatedLogbook")
        super().__init__(lb)
        self.gate = lb.gate

    def _kept(self, lines: Iterable[Line]) -> list[Line]:
        return [line for line in lines if self.gate.keep(line)]

    @property
    def _cut(self) -> str:
        """The gate as SQL (`Gate.sql`), the person drafts sorted first."""
        self._sort_drafts()
        return self.gate.sql

    def _sort_drafts(self) -> None:
        """Name by seq the person drafts the `relationship` and the `dream` entries judge apart
        (`Gate.own`, `Gate.held`), once per call and only when the two ceilings differ: the drafts
        whose `subject` is a string and not a day or a week are read (`DAY_OR_WEEK`), and the unit of
        each decides. A sealed one this machine cannot open has no unit to read and follows the
        dream's, as every reader of drafts holds it. A line in hand is judged by its unit whatever
        this finds (`Gate.allows_line`), so what crosses is exact; this keeps the counts with it."""
        gate = self.gate
        if gate.own is not None:
            return
        own: set[int] = set()
        held: set[int] = set()
        if gate.people is not None and gate.people != gate.drafts:
            where = "kind = ? AND subject IS NOT NULL AND subject NOT GLOB ? AND subject NOT GLOB ?"
            found = self.db.execute(
                f"SELECT file, offset FROM lines WHERE {where}", (drafts.KIND, *DAY_OR_WEEK)
            )
            for line in Index.read(self, [(str(f), int(o)) for f, o in found], opened=False):
                if is_sealed(line):
                    with contextlib.suppress(sealing.SealError, sealing.MissingExtra, ValueError):
                        line = self.lb.opened(line)
                if drafts.unit_of(line) != drafts.UNIT_PERSON:
                    continue
                tier, seq = int(line["tier"]), int(line["seq"])
                if tier <= gate.people and tier > gate.drafts:
                    own.add(seq)
                elif tier > gate.people and tier <= gate.drafts:
                    held.add(seq)
        gate.own, gate.held = frozenset(own), frozenset(held)

    def _count_above(self, where: str, args: Sequence[object]) -> None:
        """Hold back (count) every line `where` matches that the gate does not allow."""
        for (seq,) in self.db.execute(
            f"SELECT seq FROM lines WHERE {where} AND NOT ({self._cut})", (*args, *self.gate.cut)
        ):
            self.gate.withheld.add(int(seq))

    def day(self, day_local: str) -> list[Line]:
        return self._kept(super().day(day_local))

    def between(self, first: str, last: str) -> list[tuple[str, Line]]:
        return [(day, line) for day, line in super().between(first, last) if self.gate.keep(line)]

    def window(self, since: str, until: str) -> list[Place]:
        kept = []
        self._sort_drafts()
        for place in super().window(since, until):
            if self.gate.allows(place.tier, place.kind, place.seq) or place.kind == RETRACTION:
                kept.append(place)
            else:
                self.gate.withheld.add(place.seq)
        return kept

    def read(self, places: Iterable[tuple[str, int]], opened: bool = True) -> list[Line]:
        return self._kept(super().read(places, opened))

    def by_seq(self, seq: int) -> Line | None:
        line = super().by_seq(seq)
        return line if line is not None and self.gate.keep(line) else None

    def by_id(self, line_id: str) -> Line | None:
        line = super().by_id(line_id)
        return line if line is not None and self.gate.keep(line) else None

    def by_ids(self, ids: Iterable[str]) -> dict[str, Line]:
        return {id_: line for id_, line in super().by_ids(ids).items() if self.gate.keep(line)}

    def day_above(self, day_local: str, kinds: Sequence[str] | None = None) -> int:
        """How many standing lines of one local day (of these kinds, when given) sit above the
        ceiling: counted and held back, nothing else of them read."""
        where = f"day_local = ? AND kind != 'retraction' AND id NOT IN ({RETRACTED})"
        args: list[object] = [day_local]
        if kinds is not None:
            where += f" AND kind IN ({', '.join('?' * len(kinds))})"
            args.extend(kinds)
        self._count_above(where, args)
        (n,) = self.db.execute(
            f"SELECT count(*) FROM lines WHERE {where} AND NOT ({self._cut})", (*args, *self.gate.cut)
        ).fetchone()
        return int(n)

    def retractions(self) -> list[Line]:
        return super().retractions()  # marks on other lines; `keep` lets them through regardless

    def resolutions(self, opened: bool = True) -> list[Line]:
        return self._kept(super().resolutions(opened))

    def last_fix(self, subject: str) -> Line | None:
        line = super().last_fix(subject)
        return line if line is not None and self.gate.keep(line) else None

    def by_kind(self, kind: str, first_day: str | None = None, last_day: str | None = None) -> list[Line]:
        return self._kept(super().by_kind(kind, first_day, last_day))

    def of_source(
        self, kind: str, source: str, first_day: str, last_day: str, raw_id_prefix: str | None = None
    ) -> list[Line]:
        return self._kept(super().of_source(kind, source, first_day, last_day, raw_id_prefix))

    def of_kind(
        self,
        kind: str,
        first_day: str | None = None,
        last_day: str | None = None,
        source: str | None = None,
        after_seq: int | None = None,
    ) -> Iterator[Line]:
        found = super().of_kind(kind, first_day, last_day, source, after_seq)
        return (line for line in found if self.gate.keep(line))

    def locations(self, first_day: str, last_day: str, subject: str | None = None) -> list[LocationRow]:
        where = (
            "kind = 'location' AND day_local BETWEEN ? AND ? AND lat IS NOT NULL AND lon IS NOT NULL"
            f" AND subject {'IS NULL' if subject is None else '= ?'} AND id NOT IN ({RETRACTED})"
        )
        args: tuple[object, ...] = (first_day, last_day, *(() if subject is None else (subject,)))
        self._count_above(where, args)
        rows: list[LocationRow] = self.db.execute(
            f"SELECT seq, at, lat, lon FROM lines WHERE {where} AND {self._cut} ORDER BY at, seq",
            (*args, *self.gate.cut),
        ).fetchall()
        return rows

    def evidence(self, kinds: Sequence[str], first_day: str, last_day: str) -> list[EvidenceRow]:
        where = (
            f"kind IN ({', '.join('?' * len(kinds))}) AND day_local BETWEEN ? AND ?"
            f" AND id NOT IN ({RETRACTED})"
        )
        args: tuple[object, ...] = (*kinds, first_day, last_day)
        self._count_above(where, args)
        rows: list[EvidenceRow] = self.db.execute(
            f"SELECT kind, at, end FROM lines WHERE {where} AND {self._cut} ORDER BY at, seq",
            (*args, *self.gate.cut),
        ).fetchall()
        return rows

    def span(self, kind: str | None = None) -> tuple[str, str] | None:
        found = self.db.execute(
            "SELECT min(day_local), max(day_local) FROM lines"
            f" WHERE kind = coalesce(?, kind) AND {self._cut}",
            (kind, *self.gate.cut),
        ).fetchone()
        if found is None or found[0] is None:
            return None
        return str(found[0]), str(found[1])

    def source_days(
        self, first: str, last: str, tiers: Sequence[int] | None = None
    ) -> tuple[int, dict[str, int]]:
        where = "day_local BETWEEN ? AND ? AND kind != 'retraction'"
        self._count_above(where, (first, last))
        where += f" AND {self._cut}"
        args: tuple[object, ...] = (first, last, *self.gate.cut)
        if tiers is not None:  # a reader's own gate on top of the ceiling (`reading.read(..., tiers)`)
            where += f" AND tier IN ({','.join('?' * len(tiers))})"
            args += tuple(int(t) for t in tiers)
        (logged,) = self.db.execute(
            f"SELECT count(DISTINCT day_local) FROM lines WHERE {where}", args
        ).fetchone()
        found = self.db.execute(
            f"SELECT source, count(DISTINCT day_local) FROM lines WHERE {where} GROUP BY source", args
        ).fetchall()
        return int(logged), {str(source): int(n) for source, n in found}

    def activity(self, first_day: str, last_day: str) -> list[dict[str, Any]]:
        """`Index.activity` over the lines at or below the ceiling: the same three SELECTs with the
        tier cut in each, so a source whose every line is above it is not listed at all."""
        where = "day_local BETWEEN ? AND ?"
        self._count_above(where, (first_day, last_day))
        where += f" AND {self._cut}"
        cut = (first_day, last_day, *self.gate.cut)
        totals = self.db.execute(
            f"SELECT source, count(*), min(at), max(at) FROM lines WHERE {where}"
            " GROUP BY source ORDER BY count(*) DESC, source",
            cut,
        ).fetchall()
        days: dict[str, list[str]] = {}
        for source, day in self.db.execute(
            f"SELECT source, day_local FROM lines WHERE {where}"
            " GROUP BY source, day_local ORDER BY source, day_local",
            cut,
        ):
            days.setdefault(str(source), []).append(str(day))
        stretches = {
            str(source): (str(start), str(end))
            for source, start, end, _days in self.db.execute(
                "SELECT source, prev, at, max(julianday(at) - julianday(prev)) FROM ("
                " SELECT source, at, lag(at) OVER (PARTITION BY source ORDER BY at) AS prev"
                f" FROM lines WHERE {where}) WHERE prev IS NOT NULL GROUP BY source",
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

    def standing(self, first_day: str, last_day: str, kinds: Sequence[str] | None) -> list[Place]:
        """For `search`: where every standing line of the window is (retracted ones and retractions
        out, a kind cut when given) at or below the ceiling, in chain order; those above it counted."""
        where = f"day_local BETWEEN ? AND ? AND kind != 'retraction' AND id NOT IN ({RETRACTED})"
        args: list[object] = [first_day, last_day]
        if kinds is not None:
            where += f" AND kind IN ({', '.join('?' * len(kinds))})"
            args.extend(kinds)
        self._count_above(where, args)
        found = self.db.execute(
            f"SELECT seq, id, at, kind, tier, file, offset FROM lines WHERE {where} AND {self._cut}"
            " ORDER BY seq",
            (*args, *self.gate.cut),
        ).fetchall()
        return [
            Place(int(seq), str(id_), str(at), str(kind), int(tier), str(file), int(offset))
            for seq, id_, at, kind, tier, file, offset in found
        ]


def ceiling(root: Path, allow_tier_3: bool = False) -> int:
    """The ceiling in force for one call: the policy's, read now, and never 3 without the flag."""
    try:
        found = policy.mcp_ceiling(root)
    except policy.PolicyError as e:
        raise ToolError(str(e)) from e
    return found if allow_tier_3 else min(found, UNFLAGGED_CEILING)


# -- the tools ---------------------------------------------------------------------------------


Arguments = Mapping[str, Any]
ToolFn = Callable[[GatedLogbook, Arguments], Any]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict[str, dict[str, Any]]
    required: tuple[str, ...]
    fn: ToolFn
    sample: dict[str, Any]  # the arguments `--inspect` shows
    writes: bool = False
    named: bool = False  # a write tool refused unless the policy's `mcp` entry names it under `write`

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": self.properties,
            "required": list(self.required),
            "additionalProperties": False,
        }


def _string(a: Arguments, key: str, required: bool = False) -> str | None:
    value = a.get(key)
    if value is None:
        if required:
            raise ToolError(f"{key} is required")
        return None
    if not isinstance(value, str):
        raise ToolError(f"{key} must be a string")
    return value


def _day(a: Arguments, key: str) -> str | None:
    """An argument that is a local day, checked, or None when not given."""
    value = _string(a, key)
    return None if value is None else parse_day(value).isoformat()


def _today(lb: Logbook) -> str:
    """The day the owner is in now: the record's zone and its `day_start` (RFC 0036); a tool's `day`
    defaults to it. DayStartError (a ValueError, so the tool's error) for a boundary it cannot parse."""
    return day_start.of(lb.meta).today(datetime.now(UTC)).isoformat()


def _whole(lb: Logbook) -> tuple[str, str] | None:
    """The days the owner's track covers, else any line: the window a page or a rollup reads."""
    return reading.record_days(lb, "location") or reading.record_days(lb)


def _airports() -> Airports:
    return Airports.load()


def tool_day(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    day = _day(a, "date") or _today(lb)
    return day_reader.read(lb, day, _airports())


def tool_days(lb: GatedLogbook, a: Arguments) -> list[dict[str, Any]]:
    since, until = _day(a, "from"), _day(a, "to")
    if since is None or until is None:
        whole = _whole(lb)
        if whole is None:
            return []
        since, until = since or whole[0], until or whole[1]
    return list(days_reader.read(lb, since, until, _airports()))


def tool_trips(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    year = _string(a, "year")
    whole = _whole(lb)
    if whole is None:
        return {"window": None, "trips": []}
    first, last = whole
    if year is not None:
        if not (len(year) == 4 and year.isdigit()):
            raise ToolError(f"not a year (YYYY): {year!r}")
        first, last = max(first, f"{year}-01-01"), min(last, f"{year}-12-31")
        if last < first:
            return {"window": None, "trips": []}
    rd = reading.read(lb, first, last, _airports())
    found, warning = trips.trips(rd)
    out: dict[str, Any] = {"window": reading.window_json(rd), "trips": [t.to_json() for t in found]}
    if warning:
        out["warning"] = warning
    return out


def tool_places(lb: GatedLogbook, a: Arguments) -> list[dict[str, Any]]:
    settings = stays.read_settings(lb.root)
    return [
        {"name": place.name, **place.to_json()} for place in stays.read_places(lb.root, settings.radius_m)
    ]


def _reading_of_whole(lb: GatedLogbook) -> reading.Reading | None:
    whole = _whole(lb)
    return None if whole is None else reading.read(lb, whole[0], whole[1], _airports())


def tool_people(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    rd = _reading_of_whole(lb)
    return {"years": []} if rd is None else rollup.people(rd)


def tool_person(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """`show person`'s page, its commitments as `show person` counts them: the open promises of
    `promises` with the person, read through the ceiling as the `promises` tool reads them, as counts
    and the command that lists them, never a promise's words."""
    name = _string(a, "name", required=True)
    assert name is not None
    rd = _reading_of_whole(lb)
    if rd is None:
        raise ToolError("the record has no lines")
    page = pages.person(rd, name)
    who = people.Person(page["id"], page["name"], (), None, 0)
    found = people_drift.promises_with(lb, [who]).get(page["id"], [])
    mine = sum(1 for _p, owed in found if owed)
    theirs = len(found) - mine
    # `promises` lists the ones owed to the owner only with --all, as `show person` says
    listing = None if not found else "logbook promises --all" if theirs else "logbook promises"
    page["commitments"] = {"open": len(found), "you_owe": mine, "they_owe": theirs, "command": listing}
    return page


def tool_promises(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    open_only = bool(a.get("open", False))
    report = promises.extract(lb, _day(a, "since"))
    found = [p for p in report.proposals if not open_only or p.status == "open"]
    return {
        "since": report.since,
        "open_only": open_only,
        "extractor": report.extractor,
        "proposals": [p.to_json() for p in found],
        "skipped": report.skipped,
    }


def tool_gaps(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    return gaps.report(lb, since=_day(a, "since"))


def tool_search(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    day_start.of(lb.meta)  # a hit is listed on its day: a boundary not a clock is refused (RFC 0036)
    text = (_string(a, "text", required=True) or "").strip()
    if not text:
        raise ToolError("text is empty")
    kinds = a.get("kinds")
    if kinds is not None and (
        not isinstance(kinds, list) or not kinds or not all(isinstance(k, str) and k for k in kinds)
    ):
        raise ToolError("kinds must be a list of kind names")
    limit = a.get("limit", SEARCH_LIMIT)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= SEARCH_LIMIT_MAX:
        raise ToolError(f"limit must be an integer from 1 to {SEARCH_LIMIT_MAX}")
    since, until = _day(a, "since") or "", _day(a, "until") or "9999-12-31"
    if until < since:
        raise ToolError(f"the window runs backwards: {since} > {until}")
    needle = text.casefold()
    hits: list[dict[str, Any]] = []
    scanned, more = 0, False
    with lb.index() as idx:
        assert isinstance(idx, GatedIndex)
        where = idx.standing(since, until, kinds)
        for start in range(0, len(where), READ_CHUNK):
            chunk = where[start : start + READ_CHUNK]
            for line in idx.read((p.file, p.offset) for p in chunk):
                scanned += 1
                if _mentions(line.get("payload"), needle):
                    if len(hits) == limit:
                        more = True
                        break
                    hits.append({k: v for k, v in line.items() if k not in ("prev", "hash")})
            if more:
                break
    return {
        "query": {
            "text": text,
            "since": since or None,
            "until": None if until == "9999-12-31" else until,
            "kinds": kinds,
        },
        "hits": hits,
        "scanned": scanned,
        "more": more,
    }


def _mentions(obj: object, needle: str) -> bool:
    """`needle` (case-folded) inside any string anywhere in a payload."""
    if isinstance(obj, str):
        return needle in obj.casefold()
    if isinstance(obj, dict):
        return any(_mentions(v, needle) for v in obj.values())
    if isinstance(obj, list):
        return any(_mentions(v, needle) for v in obj)
    return False


# -- the lines themselves: day_lines, line, digest -----------------------------------------------


def _instant(stamp: str) -> datetime:
    """An RFC 3339 stamp as an aware instant, for ordering a day (SPEC §3.2: by the instant, then seq)."""
    parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _families(a: Arguments) -> list[str] | None:
    """`kinds`: profile families, each once, in the order given; None when not given."""
    kinds = a.get("kinds")
    if kinds is None:
        return None
    if (
        not isinstance(kinds, list)
        or not kinds
        or not all(isinstance(k, str) and k in FAMILIES for k in kinds)
    ):
        raise ToolError(f"kinds must be a list of profile families: {', '.join(FAMILIES)}")
    return list(dict.fromkeys(kinds))


def _profile(line: Line) -> str | None:
    payload = line.get("payload")
    schema = payload.get("schema") if isinstance(payload, dict) else None
    return schema if isinstance(schema, str) else None


def _message_counterpart(p: Mapping[str, Any], names: Mapping[Ref, str]) -> str:
    """The other side of a message: the chat for one the owner sent; else the sender, by its label,
    the name the source showed, the direct chat's own name, or the ref as given."""
    chat = p.get("chat")
    if isinstance(chat, str):
        chat = {"type": "direct", "name": chat}
    elif not isinstance(chat, dict):
        chat = {}
    chat_name = str(chat.get("name") or chat.get("id") or "")
    if p.get("from_me"):
        return chat_name
    sender = p.get("sender")
    own = sender.get("name") if isinstance(sender, dict) else None
    return (
        _name(sender, names)
        or (own if isinstance(own, str) else "")
        or (chat_name if chat.get("type") == "direct" else "")
        or _ref_value(sender)
    )


def _counterpart(line: Line, names: Mapping[Ref, str]) -> str | None:
    """Whom the line is with, as the record names them (the resolution lines under the ceiling,
    else the name the source gave, else the ref): a mail's sender, or its recipients when the owner
    sent it; a message's sender or chat; a transcript's participants; a calendar entry's attendees;
    a call's counterparty. None for a line with nobody in it, and for one still sealed."""
    if is_sealed(line):
        return None
    p: Mapping[str, Any] = line["payload"]
    kind = line["kind"]
    if kind == "mail":
        if p.get("direction") == "sent":
            people = [_mail_person(r, names) for r in [*(p.get("to") or []), *(p.get("cc") or [])]]
        else:
            people = [_mail_person(p.get("from"), names)]
    elif kind == "message":
        people = [_message_counterpart(p, names)]
    elif kind == "transcript":
        people = [
            _name({"kind": "email", "value": q.get("email")}, names)
            or str(q.get("name") or q.get("email") or "")
            for q in p.get("participants") or []
            if isinstance(q, dict)
        ]
    elif kind == "event":
        people = [_attendee(who, names) for who in p.get("attendees") or []]
    elif kind == "call":
        ref = p.get("counterparty")
        people = [_name(ref, names) or _ref_value(ref)]
    else:
        return None
    return ", ".join(who for who in people if who) or None


def _superseded(idx: Index) -> dict[str, int]:
    """The lines `show` marks superseded, by the index's one rule (a superseder not retracted, issue
    #321): a flight another flight line replaced (RFC 0013 rule 4) and a transcript heard again
    (RFC 0038 §2.8)."""
    return {**idx.superseded(flights.KIND), **idx.superseded("transcript")}


def _row_json(
    line: Line, tz: ZoneInfo, names: Mapping[Ref, str], superseded: Mapping[str, int]
) -> dict[str, Any]:
    """One line as `day_lines` lists it: its envelope, the local clock, the counterpart and the text
    part of the row `show` prints (a flight another flight line replaced, or a transcript heard again,
    says so instead)."""
    by = superseded.get(str(line["id"]))
    return {
        "id": line["id"],
        "seq": line["seq"],
        "at": line["at"],
        "end": line.get("end"),
        "time": _clock(str(line["at"]), tz),
        "kind": line["kind"],
        "profile": _profile(line),
        "source": line["source"],
        "tier": int(line["tier"]),
        "counterpart": _counterpart(line, names),
        "text": f"superseded by #{by}" if by is not None else _line_text(line, tz, names),
    }


def tool_day_lines(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """`logbook show DAY`, one object per standing line, through the gate: the index serves the day's
    lines at or below the ceiling only, and the ones above it are counted (`above_ceiling`) by a query
    that reads nothing of them. A retracted line is left out and counted; a retraction is never a
    row. The names are the resolution lines under the ceiling, as every reader has them."""
    day = _day(a, "day") or _today(lb)
    day_start.of(lb.meta)  # the page is the day so defined: a boundary not a clock is refused (RFC 0036)
    families = _families(a)
    kinds = None if families is None else [kind for family in families for kind in FAMILIES[family]]
    tz = ZoneInfo(str(lb.meta["timezone"]))
    with lb.index() as idx:
        assert isinstance(idx, GatedIndex)
        on_day = idx.day(day)
        marks = retractions(idx.retractions())
        superseded = _superseded(idx)
        names = labels(lb, idx)
        above = idx.day_above(day, kinds)
    rows: list[dict[str, Any]] = []
    retracted = 0
    for line in sorted(on_day, key=lambda found: (_instant(str(found["at"])), int(found["seq"]))):
        if line["kind"] == RETRACTION or (kinds is not None and line["kind"] not in kinds):
            continue
        if line["id"] in marks:
            retracted += 1
            continue
        rows.append(_row_json(line, tz, names, superseded))
    return {
        "day": day,
        "tz": str(tz),
        "kinds": families,
        "lines": rows,
        "count": len(rows),
        "above_ceiling": above,
        "retracted": retracted,
    }


def _full_text(lb: Logbook, line: Line) -> str | None:
    """The whole text of a line, where it has one: a note's, a mail's body, a message's, and a
    transcript's turns from the attachment store as `promises` and the search index read them, one
    `Speaker: text` per turn. None for a line without one, a transcript whose text is not in the
    store, a line still sealed, and a home video's soundtrack, which is no call (`NOT_CALLS`, RFC
    0040): its words go to no model, an MCP client's included, whatever the ceiling."""
    if is_sealed(line):
        return None
    p: Mapping[str, Any] = line["payload"]
    kind = line["kind"]
    if kind == "transcript" and line.get("source") in transcripts.NOT_CALLS:
        return None
    if kind == "transcript":
        turns = transcripts.turns_of(lb, line)
        if turns is None:
            return None
        return "\n".join(f"{t.speaker}: {t.text}" if t.speaker else t.text for t in turns)
    value = p.get("body") if kind == "mail" else p.get("text") if kind in ("note", "message") else None
    return value if isinstance(value, str) else None


def tool_line(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """One line by id, in full. The index is asked the line's tier first, by a query that reads
    nothing else of it: above the ceiling, the answer is a refusal that names the tier and the
    ceiling and nothing more, and the line counts as withheld; at or below it, the line is read
    through the gate and returned whole, a transcript's text from the store included."""
    id_ = (_string(a, "id", required=True) or "").strip()
    if not id_:
        raise ToolError("id is empty; day_lines and search list lines with their ids")
    tz = ZoneInfo(str(lb.meta["timezone"]))
    with lb.index() as idx:
        assert isinstance(idx, GatedIndex)
        found = idx.db.execute(
            "SELECT seq, tier, kind FROM lines WHERE id = ? ORDER BY seq LIMIT 1", (id_,)
        ).fetchone()
        if found is None:
            raise ToolError(f"no line {id_!r}")
        seq, tier, kind = int(found[0]), int(found[1]), str(found[2])
        if kind == RETRACTION:
            raise ToolError(f"line {id_!r} is a retraction, a mark on another line; no tool returns one")
        if tier > lb.gate.max_tier:
            lb.gate.withheld.add(seq)
            raise ToolError(
                f"line {id_!r} is tier {tier}, above the mcp ceiling of {lb.gate.max_tier};"
                " nothing of it crosses"
            )
        line = Index.by_id(idx, id_) if kind == drafts.KIND else None  # at or under the ceiling: its unit
        if line is not None and not lb.gate.allows_line(line):  # its own entry no longer allows it
            lb.gate.withheld.add(seq)
            entry, max_tier = lb.gate.entry_of(drafts.unit_of(line))
            raise ToolError(
                f"line {id_!r} is a draft of tier {tier}, above max_tier {max_tier} of the"
                f" {entry!r} entry it was written under; nothing of it crosses"
            )
        line = idx.by_id(id_)
        assert line is not None  # the tier is at or below the ceiling: the gate lets it through
        marks = retractions(idx.retractions())
        superseded = _superseded(idx)
        names = labels(lb, idx)
    mark = marks.get(str(line["id"]))
    if mark is not None:  # `show` prints the marker and nothing of the line
        reason = str(mark["payload"].get("reason", ""))
        return {
            "id": line["id"],
            "seq": line["seq"],
            "at": line["at"],
            "time": _clock(str(line["at"]), tz),
            "retracted": {"seq": mark["seq"], "reason": reason},
            "row": f"retracted #{line['seq']}: {reason}",
        }
    row = _row_json(line, tz, names, superseded)
    text = row.pop("text")
    return {
        **row,
        "tz": line.get("tz"),
        "row": text,
        "payload": line["payload"],
        "text": _full_text(lb, line),
    }


def tool_digest(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """`logbook digest DATE` through the gate: the reader composes the digest from the Day, the
    promises and the gaps, every one of them read through the gated index, so a line above the
    ceiling is in no part of it. `week` is the seven days of the ISO week that holds `date`, Monday
    to Sunday, each as the command prints it, a blank line between; a day that has not come is left
    out of a week and refused for a day, as the command refuses it. The digest's question bank and
    its state are files beside the record, written as the command writes them; the record itself is
    untouched."""
    period = _string(a, "period") or "day"
    if period not in PERIODS:
        raise ToolError(f"period must be one of {', '.join(PERIODS)}")
    day = _day(a, "date") or _today(lb)
    if period == "day":
        week = None
        days = [day]
    else:
        d = parse_day(day)
        monday = d - timedelta(days=d.weekday())
        year, number, _weekday = d.isocalendar()
        week = f"{year}-W{number:02d}"
        today = day_start.of(lb.meta).today(gaps.now())
        days = [
            (monday + timedelta(days=n)).isoformat() for n in range(7) if monday + timedelta(days=n) <= today
        ]
    airports = _airports()
    texts = ["\n".join(digest_reader.rows(digest_reader.read(lb, one, airports))) for one in days]
    text = "\n\n".join(texts)
    return {
        "period": period,
        "day": day,
        "week": week,
        "days": days,
        "text": text,
        "lines": len(text.splitlines()),
    }


# -- the write tools -------------------------------------------------------------------------------


def tool_add_note(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """`logbook add "<sentence>"`: one note/v1 line, source manual, tier 2, through `Logbook.append`."""
    text = (_string(a, "text", required=True) or "").strip()
    if not text:
        raise ToolError("text is empty; a note is a sentence in the owner's words")
    at = _string(a, "at")
    try:
        stamp = utc(at) if at else now_utc()
    except ValueError as e:
        raise ToolError(str(e)) from e
    line = lb.append(
        at=stamp, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": text}
    )
    return _written(lb, line)


def tool_promise_done(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """`logbook promises done <id>`: one task/v1 line (RFC 0016) through `Logbook.append`; a
    proposal already done writes nothing and says so. The proposal is looked up through the gate,
    so one above the ceiling is one this server does not know."""
    id_ = (_string(a, "id", required=True) or "").strip()
    report = promises.extract(lb)
    found = next((p for p in report.proposals if p.id == id_), None)
    if found is None:
        raise ToolError(
            f"no proposal {id_!r} within the ceiling; the promises tool lists them with their ids"
        )
    if found.status != "open":  # a task line closed it, or the owner's day kept, missed or dropped it
        d = found.disposition
        return {
            "already_done": True,
            "promise": found.id,
            "quote": found.match.quote,
            "task": found.closed_by,
            "disposition": None if d is None else {"value": d.value, "day": d.day, "line": d.line},
        }
    at = utc(now_utc())
    line = lb.append(
        at=at,
        source="manual",
        kind=promises.TASK,
        tier=promises.TASK_TIER,
        payload=promises.draft_done(found, at, report.extractor, None),
    )
    return {**_written(lb, line), "already_done": False, "promise": found.id, "quote": found.match.quote}


# -- the write tools the owner allows by name (ADR 0022) -------------------------------------------------


def _write_day(lb: GatedLogbook, a: Arguments) -> str:
    """The `day` a named write tool writes to, inside the window: today in the record's zone and the
    `window_days` before it (`write_window_days` in the policy's `mcp` entry, else 60)."""
    day = parse_day(_string(a, "day", required=True) or "")
    today = date.fromisoformat(_today(lb))
    first = today - timedelta(days=lb.window_days)
    if not first <= day <= today:
        raise ToolError(
            f"{day.isoformat()} is outside the write window, {first.isoformat()} to {today.isoformat()}"
            f" (today and the {lb.window_days} days before it, set by {policy.WINDOW} in the mcp entry"
            f" of {policy.POLICY_FILE.as_posix()})"
        )
    return day.isoformat()


def _entries(a: Arguments, key: str) -> list[str]:
    value = a.get(key)
    if not isinstance(value, list) or not all(isinstance(entry, str) for entry in value):
        raise ToolError(f"{key} must be a list of line ids or seqs, as day_lines lists them")
    return value


def tool_sign_day(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """`logbook day sign DAY` through the door: the arguments mapped onto the flags and handed to
    `signing.sign`, the one implementation, over the record itself and not through the gate, so the
    line is byte for byte what the command writes with the same flags and `--at`. A day signed before
    keeps what its standing signature said when `confirm` is not given (`sign_again`, RFC 0034
    amendment 4), as `day sign` does; `"all"`, and a first signature without `confirm`, confirm the
    page's lines at or under the door's ceiling and leave the rest unconfirmed, counted
    (`_shown_on_page`; amendment 4, 18 and 19 October 2026), since the agent was never shown them.
    Returns the line's envelope, the header the command prints, what was kept, and counts."""
    day = _write_day(lb, a)  # `_today` under the record's day_start: a boundary not a clock is refused
    confirm = a.get("confirm")
    entries = None if confirm is None else [confirm] if isinstance(confirm, str) else _entries(a, "confirm")
    disposed = {value: _entries(a, value) for value in signing.DISPOSITIONS if a.get(value) is not None}
    record = Logbook(lb.root)
    chosen, keep = sign_again.confirmation(entries, bool(disposed))
    args = sign_again.again(record, day, chosen, keep, disposed, _string(a, "note"))  # under `call`'s hold
    hidden: set[str] = set()
    if args.confirm is None:  # `"all"`, or a first signature: the page's lines the door can show, no more
        shown, hidden = _shown_on_page(lb, record, day)
        # a line given a disposition is confirmed whatever `confirm` says; none shown is not `"none"`
        args = replace(args, confirm=shown or [e for found in args.dispositions.values() for e in found])
    line = signing.sign(
        record,
        day,
        confirm=args.confirm,
        note=args.note,
        at=_string(a, "at"),
        dispositions=args.dispositions,
    )
    p = line["payload"]
    given = signing.dispositions_of(p).values()
    above = len(hidden - set(p["confirmed"]))  # a line given a disposition is confirmed, so not left
    return {
        **_written(lb, line),
        "day": p["day"],
        "header": signing.summary(line)[0],
        "confirmed": len(p["confirmed"]),
        "on_page": p["page"]["lines"],
        "dispositions": {value: n for value in signing.DISPOSITIONS if (n := list(given).count(value))},
        "supersedes": p.get("supersedes"),
        "kept": args.kept,
        "above_ceiling": above,
        "unconfirmed": None if not above else f"{above} line{'' if above == 1 else 's'} {ABOVE_LEFT}",
    }


def _shown_on_page(lb: GatedLogbook, record: Logbook, day: str) -> tuple[list[str], set[str]]:
    """What `confirm: "all"` confirms through the door, and a first signature without `confirm` (RFC
    0034 amendment 4, 18 and 19 October 2026): the ids of the page's lines the gate lets the agent
    see, in the page's order, and the ids of those it does not, which stay unconfirmed unless given a
    disposition. The page is read from the record itself, as `signing.sign` reads it; the caller says
    nothing of a line above the gate but how many there are."""
    lines, retracted = reflect.day_lines(record, day)
    page = reflect.on_page(lines, retracted)
    shown = [str(line["id"]) for line in lines if str(line["id"]) in page and lb.gate.shows(line)]
    return shown, set(page) - set(shown)


def tool_note_day(lb: GatedLogbook, a: Arguments) -> dict[str, Any]:
    """One note/v1 line on a day, through the door: source `mcp`, tier 2 (RFC 0010), the text as given
    and never filtered, `kind` in the profile's `labels`, written through `notes.write`, the note path
    `day reflect` writes through too. `at` is checked by the rules of `day sign --at` and must fall on
    the day in the record's zone; without it the note is now when the day is today, else at 23:59 of
    the day."""
    day = _write_day(lb, a)
    text = _string(a, "text", required=True) or ""
    if not text.strip():
        raise ToolError("text is empty; a note is the owner's words")
    if len(text) > NOTE_MAX:
        raise ToolError(f"text is {len(text)} characters, over the cap of {NOTE_MAX}; nothing was written")
    kind = _string(a, "kind") or NOTE_KINDS[0]
    if kind not in NOTE_KINDS:
        raise ToolError(f"kind must be one of {', '.join(NOTE_KINDS)}")
    line = notes.write(Logbook(lb.root), day, text, kind, NOTE_SOURCE, at=_string(a, "at"), today=_today(lb))
    return {**_written(lb, line), "day": day, "label": kind, "chars": len(text)}


def _door(root: Path, name: str) -> policy.Ceiling:
    """The policy's `mcp` entry when it allows the write tool `name` today; else the refusal, one
    sentence that says what to write in the file."""
    try:
        door = policy.mcp_door(root)
    except policy.PolicyError as e:
        raise ToolError(str(e)) from e
    file = policy.POLICY_FILE.as_posix()
    if door is not None and door.expired and door.until is not None and name in door.write:
        raise ToolError(
            f"{name} is not allowed through the door: the mcp entry of {file} expired on"
            f" {door.until.isoformat()} and allows no write tool"
        )
    if door is None or name not in door.writes:
        raise ToolError(
            f"{name} is not allowed through the door: the mcp entry of {file} does not name it"
            f' under "{policy.WRITE}"'
        )
    return door


def _written(lb: GatedLogbook, line: Line) -> dict[str, Any]:
    """What a write tool says about the line it appended: its envelope, never its payload, and
    whether this server will read it back under the ceiling in force."""
    tier = int(line["tier"])
    return {
        "seq": line["seq"],
        "id": line["id"],
        "at": line["at"],
        "kind": line["kind"],
        "tier": tier,
        "readable": lb.gate.allows(tier, str(line["kind"])),
    }


TOOLS: dict[str, Tool] = {
    t.name: t
    for t in (
        Tool(
            "day",
            "One calendar day read back (`logbook day`): the nights either side, the country, the timeline"
            " of stays, moves, stops and flights with what attached to each and who was there, the health"
            " line, the sources. Default: today in the record's zone.",
            {"date": DAY},
            (),
            tool_day,
            {"date": "2026-06-10"},
        ),
        Tool(
            "days",
            "A window of the record, one object per day (`logbook days`): the night, the kilometres moved,"
            " the flights, the stays, the people confirmed, the health triple, the sources gone quiet."
            " Both bounds default to the days the record covers.",
            {"from": DAY, "to": DAY},
            (),
            tool_days,
            {"from": "2026-06-08", "to": "2026-06-14"},
        ),
        Tool(
            "trips",
            "Runs of nights away from home (`logbook trips`), derived and never written: the route, the"
            " places, the people, the flights in and out. `year` clips the window to one year.",
            {"year": {"type": "string", "pattern": "^\\d{4}$", "description": "YYYY"}},
            (),
            tool_trips,
            {"year": "2026"},
        ),
        Tool(
            "places",
            "The named places of the record, `places.json` (`logbook places list`): name, coordinates,"
            " radius, kind, tags.",
            {},
            (),
            tool_places,
            {},
        ),
        Tool(
            "people",
            "Per resolved person, per year (`logbook rollup people`): days and nights together, the stays"
            " and places shared, the last contact; never the owner, never a proposal.",
            {},
            (),
            tool_people,
            {},
        ),
        Tool(
            "person",
            "One person's page (`logbook show person <name>`): their refs, first and last contact, days"
            " together per year, places, the last shared stays. The name matches a resolution label.",
            {"name": {"type": "string", "description": "a name, or part of one, the record resolves"}},
            ("name",),
            tool_person,
            {"name": "Kari"},
        ),
        Tool(
            "promises",
            "The commitments the record's own words suggest (`logbook promises`), proposals and never"
            " facts, each with its id; `open` hides the ones marked done.",
            {
                "open": {"type": "boolean", "description": "only proposals not yet done", "default": False},
                "since": DAY,
            },
            (),
            tool_promises,
            {"open": True},
        ),
        Tool(
            "gaps",
            "Where each source went quiet (`logbook sources --gaps`): lines, last line, the longest"
            " silence and the days with no line, per source, from `since` or each source's first day.",
            {"since": DAY},
            (),
            tool_gaps,
            {"since": "2026-06-01"},
        ),
        Tool(
            "search",
            "Lines whose payload mentions `text` (case-insensitive, any field), found through the index"
            " over a window of local days and a list of kinds; standing lines only, newest last, at most"
            " `limit`. Each hit is the line's envelope and payload.",
            {
                "text": {"type": "string"},
                "since": DAY,
                "until": DAY,
                "kinds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": 'e.g. ["note", "event"]',
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": SEARCH_LIMIT_MAX,
                    "default": SEARCH_LIMIT,
                },
            },
            ("text",),
            tool_search,
            {"text": "mooring", "kinds": ["note"], "since": "2026-06-01"},
        ),
        Tool(
            "day_lines",
            "Every standing line of one local day (`logbook show DAY`), in time order: id, kind, profile,"
            " local time, counterpart and the row's text as `show` prints it; `kinds` keeps only these"
            " profile families. Lines above the mcp ceiling are left out and counted in `above_ceiling`, and"
            " nothing of them crosses, not even an id. Default: today.",
            {
                "day": DAY,
                "kinds": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(FAMILIES)},
                    "description": 'profile families, e.g. ["mail", "message"]',
                },
            },
            (),
            tool_day_lines,
            {"day": "2026-06-10", "kinds": ["note", "transcript"]},
        ),
        Tool(
            "line",
            "One line by id, in full: its envelope, the row `show` prints, its payload and its text (a"
            " note's, a mail's body, a message's, a transcript's turns from the attachment store). A line"
            " above the mcp ceiling is refused naming its tier, and nothing else of it crosses.",
            {"id": {"type": "string", "description": "a line id, as day_lines and search list them"}},
            ("id",),
            tool_line,
            {"id": "019cadd3-6bc0-7dcd-9133-000000000010"},
        ),
        Tool(
            "digest",
            "The digest as `logbook digest DATE` prints it (`period` day), or the seven digests of the ISO"
            " week that holds `date`, Monday to Sunday, each as the command prints it (`period` week)."
            " Read under the mcp ceiling: a line above it is in no part of the digest, as if it were not"
            " in the record.",
            {
                "period": {"type": "string", "enum": list(PERIODS), "default": "day"},
                "date": DAY,
            },
            (),
            tool_digest,
            {"period": "day", "date": "2026-06-10"},
        ),
        Tool(
            "add_note",
            'Append one note in the owner\'s words (`logbook add "<sentence>"`): a note/v1 line, source'
            " manual, tier 2, at `at` (RFC 3339 with a zone) or now. The one way to write a note.",
            {
                "text": {"type": "string"},
                "at": {
                    "type": "string",
                    "description": "RFC 3339 with a zone, e.g. 2026-06-20T10:00:00+02:00",
                },
            },
            ("text",),
            tool_add_note,
            {"text": "Called the yard about the crane."},
            writes=True,
        ),
        Tool(
            "promise_done",
            "Mark one proposal of `promises` done (`logbook promises done <id>`): one task/v1 line. A"
            " proposal already done writes nothing.",
            {"id": {"type": "string", "description": "a proposal id from the promises tool"}},
            ("id",),
            tool_promise_done,
            {"id": "3b9e5d0f2a71c846"},
            writes=True,
        ),
        Tool(
            "sign_day",
            "Sign a day as `logbook day sign DAY` does, through the same code: one signed-day/v1 line,"
            " tier 1, the owner's reading of the page. `confirm` names the lines confirmed (default every"
            ' line on the page at or under the ceiling; "all" the same, "none" nothing, each alone),'
            " `kept`, `missed`, `dropped`, `carried` say what became of a commitment, `at` is when the"
            " owner signed; a line above the ceiling is left unconfirmed and counted. A day"
            " signed before is superseded and, without `confirm`, keeps what its signature confirmed, its"
            " dispositions and note: a line added since stays unconfirmed. Refused unless the mcp entry of"
            ' policy/crossing.json names it under "write".',
            {
                "day": DAY,
                "confirm": {
                    "anyOf": [
                        {"type": "array", "items": {"type": "string"}},
                        {"type": "string", "enum": [sign_again.EVERY, signing.NOTHING]},
                    ],
                    "description": 'line ids or seqs on the page, or "all", or "none"',
                },
                **{
                    value: {"type": "array", "items": {"type": "string"}, "description": f"lines {meaning}"}
                    for value, meaning in (
                        (signing.KEPT, "kept"),
                        (signing.MISSED, "missed"),
                        (signing.DROPPED, "let go of on purpose"),
                        (signing.CARRIED, "still open, carried to a later day"),
                    )
                },
                "note": {"type": "string", "description": "one line in the owner's words"},
                "at": {
                    "type": "string",
                    "description": f"RFC 3339 with an offset or Z, e.g. {signing.AT_EXAMPLE}",
                },
            },
            ("day",),
            tool_sign_day,
            {"day": "2026-06-09", "kept": ["019cadd3-6bc0-7dcd-9133-000000000010"], "at": signing.AT_EXAMPLE},
            writes=True,
            named=True,
        ),
        Tool(
            "note_day",
            f"Append one note to a day: a note/v1 line, source mcp, tier 2, the text as given (at most"
            f" {NOTE_MAX} characters), `kind` ({', '.join(NOTE_KINDS)}) in its labels, at `at` on that day"
            " or, without it, now for today and 23:59 for an earlier day. Refused unless the mcp entry of"
            ' policy/crossing.json names it under "write".',
            {
                "day": DAY,
                "text": {"type": "string", "maxLength": NOTE_MAX},
                "at": {"type": "string", "description": "RFC 3339 with an offset or Z, on the day"},
                "kind": {"type": "string", "enum": list(NOTE_KINDS), "default": NOTE_KINDS[0]},
            },
            ("day", "text"),
            tool_note_day,
            {"day": "2026-06-09", "text": "Proposed: book the crane for Friday.", "kind": "proposal"},
            writes=True,
            named=True,
        ),
    )
}


# -- calling -----------------------------------------------------------------------------------


def call(root: Path, name: str, arguments: Arguments, allow_tier_3: bool = False) -> dict[str, Any]:
    """One tool call against the record at `root`: the policy read now, the tool run through the
    gate, the answer with the gate's count. Raises ToolError (or a reader's ValueError) with the
    message the client should see."""
    tool = TOOLS.get(name)
    if tool is None:
        raise ToolError(f"no tool {name!r}; the tools are {', '.join(TOOLS)}")
    for key in arguments:
        if key not in tool.properties:
            raise ToolError(f"{name} takes no argument {key!r}")
    try:
        allowed = drafts.allowed(root)
        people = allowed.of(drafts.UNIT_PERSON).max_tier
        gate = Gate(ceiling(root, allow_tier_3), set(), allowed.max_tier, people)
        lb = GatedLogbook(root, gate)
        held: contextlib.AbstractContextManager[None] = contextlib.nullcontext()
        if tool.named:  # allowed by name, under the writer lock, never waiting for another writer
            lb.window_days = _door(root, name).window_days
            held = lb.writer(command=f"logbook serve mcp {name}", wait=False, notice=LOG.info)
        try:
            with held:
                data = tool.fn(lb, arguments)
        except (
            stays.SettingsError,
            pages.PageError,
            policy.PolicyError,
            FormatError,
            HeadMoved,
            sealing.IdentityRequired,  # a tier-2 line in a sealed record, on a machine without the identity
        ) as e:
            raise ToolError(str(e)) from e
        except Locked as e:
            raise ToolError(str(e).replace(NOT_WAITING, NOT_WAITED)) from e
    except (ToolError, ValueError, FileNotFoundError) as e:
        _log(name, arguments, f"refused: {QUOTED.sub(ELIDED, str(e))}")  # a quoted argument is not logged
        raise
    _log(name, arguments, f"{_counts(data)} withheld={len(gate.withheld)}".strip())
    return {"data": data, "gate": gate.to_json()}


def _log(name: str, arguments: Arguments, outcome: str) -> None:
    """One line per call: the tool, the arguments that are a day, an id, a window or a switch
    (`LOGGED`; never `text`, never `name`), and the outcome as counts or the refusal's reason."""
    parts = [name]
    for key in LOGGED:
        if key in arguments:
            value = arguments[key]
            parts.append(f"{key}={','.join(map(str, value)) if isinstance(value, list) else value}")
    parts.append(outcome)
    LOG.info("%s", " ".join(parts))


def _counts(data: object) -> str:
    """The counts of an answer and nothing else: each integer field as `key=n`, each list field as
    its length; a list answer as `n=<length>`."""
    if isinstance(data, list):
        return f"n={len(data)}"
    if not isinstance(data, dict):
        return ""
    found = []
    for key, value in data.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            found.append(f"{key}={value}")
        elif isinstance(value, list):
            found.append(f"{key}={len(value)}")
    return " ".join(found)


def inspect_text() -> str:
    """`logbook mcp --inspect`: the tools, their arguments, and one request as a host sends it."""
    lines = [
        f"logbook mcp: {len(TOOLS)} tools over stdio; every answer passes the mcp ceiling of"
        " policy/crossing.json",
        "",
    ]
    for tool in TOOLS.values():
        args = ", ".join(
            f"{key}{'' if key in tool.required else '?'}: {spec.get('type', 'any')}"
            for key, spec in tool.properties.items()
        )
        mark = "  [writes one line; only when the policy names it]" if tool.named else "  [writes one line]"
        lines.append(f"{tool.name}({args}){mark if tool.writes else ''}")
        lines.append(f"    {tool.description}")
    named = ", ".join(t.name for t in TOOLS.values() if t.named)
    lines += [
        "",
        f'write tools, allowed by name in the mcp entry\'s "{policy.WRITE}": {named} (none by default; e.g.'
        f' {{"mcp": {{"max_tier": 1, "{policy.WRITE}": ["sign_day", "note_day"]}}}})',
    ]
    sample = TOOLS["day"]
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": sample.name, "arguments": sample.sample},
    }
    lines += ["", "a call, as the host sends it on the server's stdin:", json.dumps(request, indent=2)]
    lines += [
        "",
        'the answer is one JSON text: {"data": <the tool\'s output>, "gate": {"destination": "mcp",'
        ' "max_tier": N, "withheld": K}}',
    ]
    return "\n".join(lines)


# -- the server: the SDK is imported here only, so `--inspect` needs no extra -------------------


def build_server(root: Path, allow_tier_3: bool = False) -> Any:
    """A low-level MCP `Server` over the record at `root`: `tools/list` from the table above,
    `tools/call` through `call`, one at a time. Raises ImportError naming the extra when the SDK
    is not installed."""
    try:
        from mcp import types
        from mcp.server.lowlevel import Server
    except ImportError as e:
        raise ImportError(EXTRA_MESSAGE) from e

    lock = threading.Lock()

    async def on_list_tools(ctx: Any, params: Any) -> Any:
        return types.ListToolsResult(
            tools=[
                types.Tool(name=t.name, description=t.description, input_schema=t.schema)
                for t in TOOLS.values()
            ]
        )

    async def on_call_tool(ctx: Any, params: Any) -> Any:
        name, arguments = str(params.name), dict(params.arguments or {})
        try:
            with lock:
                answer = call(root, name, arguments, allow_tier_3)
        except (ToolError, ValueError, FileNotFoundError) as e:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"{name}: {e}")], is_error=True
            )
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=json.dumps(answer, ensure_ascii=False))]
        )

    return Server(
        SERVER_NAME,
        version=__version__,
        instructions=(
            "The owner's logbook: a local, append-only record. Read tools answer through the owner's"
            " tier ceiling; `gate.withheld` says how many lines were left out. Write tools append"
            " one line each and nothing is ever rewritten."
        ),
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def serve(root: Path, allow_tier_3: bool = False) -> None:
    """Run over this process's stdin and stdout until the host closes them. Nothing else is opened."""
    import anyio

    server = build_server(root, allow_tier_3)
    if not LOG.handlers:  # one line per call on stderr; stdout is the transport
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(message)s"))
        LOG.addHandler(handler)
        LOG.setLevel(logging.INFO)

    async def run() -> None:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
