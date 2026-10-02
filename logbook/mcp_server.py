"""`logbook mcp`: the record as an MCP server for an agent on this machine, over stdio only.

The Model Context Protocol lets a host (an editor, a chat client, an agent runner) start a server
as a child process and call its tools over the process's own stdin and stdout. That is the one
transport here: no TCP, no socket, nothing listening. The host runs on the owner's machine under
the owner's command, and the record stays where it is.

Nine read tools answer from the index and the readers every command already uses — `day`, `days`,
`trips`, `places`, `people`, `person`, `promises`, `gaps` and `search` — and two write tools go
through `Logbook.append` and nothing else: `add_note` is `logbook add "<sentence>"`, and
`promise_done` is `logbook promises done <id>`.

Every tool's output passes the crossing gate of ADR 0016. `policy/crossing.json` names the `mcp`
destination and the highest tier that may cross to it, 1 unless the owner raises it (`policy.mcp_ceiling`);
the server reads the file on every call and never writes it. A line above the ceiling is left out of
every reading before anything is derived from it (`GatedIndex`: the readers see the record as if
the line were not there), and the response says how many lines were withheld, so a client knows the
answer is a partial one. Tier 3 crosses only when the policy allows it and the server was started with
`--allow-tier-3`: a policy edit alone never lets it through, as it never does for an export. A read
appends no `crossing/v1` line: nothing leaves the machine, and the record is not the place to log
an agent's every question."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import __version__, gaps, pages, policy, promises, reading, rollup, stays, trips
from . import day as day_reader
from . import days as days_reader
from .chain import Line
from .export import parse_day
from .flights import Airports
from .index import RETRACTED, EvidenceRow, Index, LocationRow, Place
from .store import RETRACTION, FormatError, Logbook, now_utc, utc

SERVER_NAME = "logbook"
DESTINATION = policy.MCP_DESTINATION
UNFLAGGED_CEILING = 2  # the most a policy alone lets cross; tier 3 needs `--allow-tier-3` too
SEARCH_LIMIT = 50
SEARCH_LIMIT_MAX = 500
READ_CHUNK = 200  # search: lines read from the files between checks of the hit count
EXTRA_MESSAGE = 'the mcp extra is not installed: pip install "openlogbook[mcp]"'
DAY = {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$", "description": "a local day, YYYY-MM-DD"}


class ToolError(ValueError):
    """A call the record or the policy refuses; the message says why and is the whole answer."""


# -- the gate: the record as the ceiling lets a client see it ------------------------------------


@dataclass
class Gate:
    """The ceiling in force for one call and the seqs of the lines it held back."""

    max_tier: int
    withheld: set[int]

    def keep(self, line: Line) -> bool:
        """A line at or below the ceiling. A retraction passes whatever its tier: it is a mark on
        another line, needed so that line stays hidden, and no tool ever returns one."""
        if int(line["tier"]) <= self.max_tier or line.get("kind") == RETRACTION:
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

    def _count_above(self, where: str, args: Sequence[object]) -> None:
        """Hold back (count) every line `where` matches that is above the ceiling."""
        for (seq,) in self.db.execute(
            f"SELECT seq FROM lines WHERE {where} AND tier > ?", (*args, self.gate.max_tier)
        ):
            self.gate.withheld.add(int(seq))

    def day(self, day_local: str) -> list[Line]:
        return self._kept(super().day(day_local))

    def between(self, first: str, last: str) -> list[tuple[str, Line]]:
        return [(day, line) for day, line in super().between(first, last) if self.gate.keep(line)]

    def window(self, since: str, until: str) -> list[Place]:
        kept = []
        for place in super().window(since, until):
            if place.tier <= self.gate.max_tier or place.kind == RETRACTION:
                kept.append(place)
            else:
                self.gate.withheld.add(place.seq)
        return kept

    def read(self, places: Iterable[tuple[str, int]]) -> list[Line]:
        return self._kept(super().read(places))

    def by_seq(self, seq: int) -> Line | None:
        line = super().by_seq(seq)
        return line if line is not None and self.gate.keep(line) else None

    def retractions(self) -> list[Line]:
        return super().retractions()  # marks on other lines; `keep` lets them through regardless

    def resolutions(self) -> list[Line]:
        return self._kept(super().resolutions())

    def last_fix(self, subject: str) -> Line | None:
        line = super().last_fix(subject)
        return line if line is not None and self.gate.keep(line) else None

    def by_kind(self, kind: str, first_day: str | None = None, last_day: str | None = None) -> list[Line]:
        return self._kept(super().by_kind(kind, first_day, last_day))

    def of_source(
        self, kind: str, source: str, first_day: str, last_day: str, raw_id_prefix: str | None = None
    ) -> list[Line]:
        return self._kept(super().of_source(kind, source, first_day, last_day, raw_id_prefix))

    def of_kind(self, kind: str) -> Iterator[Line]:
        return (line for line in super().of_kind(kind) if self.gate.keep(line))

    def locations(self, first_day: str, last_day: str, subject: str | None = None) -> list[LocationRow]:
        where = (
            "kind = 'location' AND day_local BETWEEN ? AND ? AND lat IS NOT NULL AND lon IS NOT NULL"
            f" AND subject {'IS NULL' if subject is None else '= ?'} AND id NOT IN ({RETRACTED})"
        )
        args: tuple[object, ...] = (first_day, last_day, *(() if subject is None else (subject,)))
        self._count_above(where, args)
        rows: list[LocationRow] = self.db.execute(
            f"SELECT seq, at, lat, lon FROM lines WHERE {where} AND tier <= ? ORDER BY at, seq",
            (*args, self.gate.max_tier),
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
            f"SELECT kind, at, end FROM lines WHERE {where} AND tier <= ? ORDER BY at, seq",
            (*args, self.gate.max_tier),
        ).fetchall()
        return rows

    def span(self, kind: str | None = None) -> tuple[str, str] | None:
        found = self.db.execute(
            "SELECT min(day_local), max(day_local) FROM lines WHERE kind = coalesce(?, kind) AND tier <= ?",
            (kind, self.gate.max_tier),
        ).fetchone()
        if found is None or found[0] is None:
            return None
        return str(found[0]), str(found[1])

    def source_days(self, first: str, last: str) -> tuple[int, dict[str, int]]:
        where = "day_local BETWEEN ? AND ? AND kind != 'retraction'"
        self._count_above(where, (first, last))
        where += " AND tier <= ?"
        args = (first, last, self.gate.max_tier)
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
        where += " AND tier <= ?"
        cut = (first_day, last_day, self.gate.max_tier)
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
            f"SELECT seq, id, at, kind, tier, file, offset FROM lines WHERE {where} AND tier <= ?"
            " ORDER BY seq",
            (*args, self.gate.max_tier),
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
    return datetime.now(ZoneInfo(str(lb.meta["timezone"]))).date().isoformat()


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
    name = _string(a, "name", required=True)
    assert name is not None
    rd = _reading_of_whole(lb)
    if rd is None:
        raise ToolError("the record has no lines")
    return pages.person(rd, name)


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
    if found.closed_by:
        return {
            "already_done": True,
            "promise": found.id,
            "quote": found.match.quote,
            "task": found.closed_by,
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
        "readable": tier <= lb.gate.max_tier,
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
    gate = Gate(ceiling(root, allow_tier_3), set())
    lb = GatedLogbook(root, gate)
    try:
        data = tool.fn(lb, arguments)
    except (stays.SettingsError, pages.PageError, policy.PolicyError, FormatError) as e:
        raise ToolError(str(e)) from e
    return {"data": data, "gate": gate.to_json()}


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
        lines.append(f"{tool.name}({args}){'  [writes one line]' if tool.writes else ''}")
        lines.append(f"    {tool.description}")
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

    async def run() -> None:
        from mcp.server.stdio import stdio_server

        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(run)
