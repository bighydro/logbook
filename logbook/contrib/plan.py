"""The plan, read and never run (RFC 0043 §9, slice E): `logbook show plan [DAY] [--json] [--coverage]`.

The owner keeps tasks, sprints and trips in Notion, and `sync notion` already
writes what happens there into the record: one `event/v1` line per page, local day and action, tier 1,
with a database row's `status`, `select`, `multi_select`, `date` and `checkbox` values by name and its
relations as page ids, never its body (`logbook/contrib/adapters/notion.py`). This reader reads those
lines and nothing else: no other line of the record (never the day's stays or its browsing) and
nothing of Notion. It is tier 1 alone: every row, every field and every line id it prints is a tier-1
`sync notion` line's. It fetches nothing, writes nothing to the record or to Notion, and never ranks,
reschedules or creates a task.

**The mapping.** Which databases are which is the owner's, in `policy/notion.json` under `plan`, each
by id or by the link Notion copies:

    {"plan": {"tasks": "<id>", "sprints": "<id>", "trips": "<id>",
              "status": "Status", "done": ["Done"], "date": "Due"}}

Every key is optional; a part whose database is not named is empty. `status` names the property that says
a row is done (default `Status`): a status or select whose option is one `done` names (default `Done`,
case aside), or a checkbox, ticked; and `date` the date property of every database (default: a row's
first date property by name, since the line keeps a property's value and not its type). No file, or a
file with no `plan` entry, is no mapping: the reader says so in one sentence (`NO_MAPPING`) and answers
nothing. A `plan` entry that is not this shape is a `PlanError` naming the file and the key. Nothing here
writes it. The cities, the people, the places and the queue (`cities`, `people`, `places`, `queue`)
are RFC 0043 §9's *where you are* and *from the queue*, which rest on the day's tier-2 lines; this
reader has neither, so a mapping that names one is a `PlanError` naming the key.

**A row** is the fold of its standing lines (retracted ones out, tier 1 only), oldest first by `at`
then `seq`: its title from the latest line with one, its properties from the latest line that holds
the row as it was (the adapter writes them only there), its relations from the latest line with
`relations` (a `--relations-backfill` line holds them and nothing else), archived while its latest
`created`, `edited`, `moved` or `archived` line is `archived`. Its link is `https://www.notion.so/`
and its id; its line is the one that holds its properties, else its latest.

**The parts**, for one local day under the record's zone and `day_start`:

- **the sprint**: the sprints row whose date holds the day (`start` to `end`, or `start` alone), the
  latest start when two do;
- **today's tasks**: the open task rows (not archived, not done) whose date holds today (a day, or a
  range from `start` to `end`), and the overdue ones, whose last day is past, in the current sprint (a
  row whose relations name the sprint, or which the sprint's relations name); with no current sprint,
  none overdue when a sprints database is mapped (the owner's rule, said in one line, `NO_SPRINT`,
  and as the tasks' `said`), every overdue open row when none is. Ordered by
  Notion's own date, then title; five at most, the rest counted, with how many of them are in the
  sprint (`and 4 more in Sprint 24`, `and 5 more, 3 of them in Sprint 24`);
- **the next trip**: the trips row whose date starts soonest on or after the day, with the days to it;
**Coverage** (RFC 0043 §9): the record knows a row only from a line `sync notion` wrote of it. A
first run by hand reads every page; a first scheduled run reads its last 14 days, and
`LOGBOOK_NOTION_ROOTS` reads only the pages under its roots, so a row last edited before then, or
outside them, is not in the record. `coverage` counts, per mapped
database, the rows and lines the record holds and its first line, so the owner can decide on one
`sync notion --since` run back to an earlier day; the reader never runs it.

The cost: the `sync notion` lines are read through the index's `(source, raw_id)` cut, never a scan
of the record (a few tens of thousands among millions), and nothing else is read."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ..core import day_start, stays
from ..core.chain import Line
from ..core.store import Logbook, retractions

PLAN_FILE = PurePosixPath("policy/notion.json")  # record-relative; `plan` is its one key today
KEY = "plan"
SOURCE, KIND, TIER = "notion", "event", 1  # what `sync notion` writes
ROLES = ("tasks", "sprints", "trips")
LATER = ("cities", "people", "places", "queue")  # RFC 0043 §9's other parts: they read tier-2 lines
STATUS, DONE = "Status", ("Done",)  # Notion's own defaults for a task database
TASKS_SHOWN = 5
NOTION_URL = "https://www.notion.so/"
UNTITLED = "Untitled"  # as Notion shows a page with no title
NO_MAPPING = (
    'no plan is mapped: name your Notion task, sprint and trip databases under "plan" in'
    " policy/notion.json (docs/plan.md)."
)
NO_SPRINT = "No sprint holds this day, so no overdue tasks are shown."  # the owner's rule, said
STATE_ACTIONS = ("created", "edited", "moved", "archived")  # not `relations`, the backfill's
ID = re.compile(
    r"(?<![0-9a-f])([0-9a-f]{32}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", re.I
)


class PlanError(ValueError):
    """`policy/notion.json`'s `plan` entry is not the documented shape."""


@dataclass(frozen=True)
class PlanMap:
    """The owner's `plan` entry: database ids by role, and how a row says it is done and dated."""

    databases: Mapping[str, str]
    status: str = STATUS
    done: frozenset[str] = frozenset(d.casefold() for d in DONE)
    date: str | None = None

    def role_of(self, database: str | None) -> str | None:
        for role, found in self.databases.items():
            if database == found:
                return role
        return None


def notion_id(text: str) -> str | None:
    """A Notion id from the id itself (32 hex digits, dashed or not) or from the link Notion copies,
    dashed and lower case, as `sync notion` writes one; None for anything else (the adapter's rule,
    kept here so a reader never imports an adapter)."""
    head = text.strip().split("?", 1)[0].split("#", 1)[0].rstrip("/")
    found = ID.search(head)
    if found is None:
        return None
    raw = found.group(1).replace("-", "").lower()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def plan_path(root: Path) -> Path:
    return Path(root).joinpath(*PLAN_FILE.parts)


def read_mapping(root: Path) -> PlanMap | None:
    """The `plan` entry of `policy/notion.json`; None without the file or the entry; `PlanError`
    naming the file and the key for anything that is not the documented shape."""
    path = plan_path(root)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PlanError(f"{path} is not JSON: {e}") from None
    if not isinstance(data, dict):
        raise PlanError(f"{path} must be an object")
    entry = data.get(KEY)
    if entry is None:
        return None
    if not isinstance(entry, dict):
        raise PlanError(f"{path}: {KEY} must be an object naming databases by role")
    later = sorted(set(entry) & set(LATER))
    if later:
        raise PlanError(
            f"{path}: {KEY}.{later[0]} is for where you are and the queue, which read the day's tier-2"
            " lines and are not built: show plan reads tier-1 lines alone; the roles are"
            f" {', '.join(ROLES)}"
        )
    unknown = sorted(set(entry) - {*ROLES, "status", "done", "date"})
    if unknown:
        raise PlanError(f"{path}: {KEY} has no key {unknown[0]!r}; the roles are {', '.join(ROLES)}")
    databases: dict[str, str] = {}
    for role in ROLES:
        value = entry.get(role)
        if value is None:
            continue
        found = notion_id(value) if isinstance(value, str) else None
        if found is None:
            raise PlanError(f"{path}: {KEY}.{role} must be a Notion database id or the link Notion copies")
        databases[role] = found
    status = entry.get("status", STATUS)
    date_name = entry.get("date")
    done = entry.get("done", list(DONE))
    if not isinstance(status, str) or not status.strip():
        raise PlanError(f"{path}: {KEY}.status must name the property whose option says a row is done")
    if date_name is not None and (not isinstance(date_name, str) or not date_name.strip()):
        raise PlanError(f"{path}: {KEY}.date must name a date property")
    if not isinstance(done, list) or not done or not all(isinstance(d, str) and d.strip() for d in done):
        raise PlanError(f"{path}: {KEY}.done must be a list of the options that mean done")
    return PlanMap(databases, status, frozenset(d.strip().casefold() for d in done), date_name)


# -- the rows ---------------------------------------------------------------------------------------------


@dataclass
class Row:
    """One Notion page as its standing lines leave it."""

    id: str
    database: str | None = None
    title: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    relations: dict[str, list[str]] = field(default_factory=dict)
    archived: bool = False
    line: str | None = None  # the line that holds its properties, else its latest
    first_at: str | None = None
    lines: int = 0

    @property
    def url(self) -> str:
        return NOTION_URL + self.id.replace("-", "")

    def related(self) -> set[str]:
        return {i for ids in self.relations.values() for i in ids}

    def date(self, name: str | None) -> dict[str, Any] | None:
        """The row's date property: the one named, else its first by name (`{start, end}`)."""
        names = [name] if name is not None else sorted(self.properties)
        for n in names:
            value = self.properties.get(n)
            if isinstance(value, dict) and isinstance(value.get("start"), str):
                return {"start": value["start"], "end": value.get("end")}
        return None

    def done(self, mapping: PlanMap) -> bool:
        """Done when the `status` property is an option `done` names, or a checkbox ticked."""
        value = self.properties.get(mapping.status)
        if isinstance(value, bool):
            return value
        return isinstance(value, str) and value.strip().casefold() in mapping.done

    def open(self, mapping: PlanMap) -> bool:
        return not self.archived and not self.done(mapping)


def rows_of(lines: Iterable[Line], retracted: Mapping[str, Line] | frozenset[str]) -> dict[str, Row]:
    """Every page the standing tier-1 `sync notion` lines name, as the module docstring folds it."""
    kept = [
        line
        for line in lines
        if line.get("source") == SOURCE
        and line.get("kind") == KIND
        and line.get("tier") == TIER
        and str(line.get("id")) not in retracted
    ]
    kept.sort(key=lambda line: (_instant(str(line.get("at") or "")), int(line.get("seq") or 0)))
    found: dict[str, Row] = {}
    for line in kept:
        payload = line.get("payload") or {}
        extra = payload.get("extra") if isinstance(payload, dict) else None
        page = extra.get("page") if isinstance(extra, dict) else None
        page_id = page.get("id") if isinstance(page, dict) else None
        if not isinstance(extra, dict) or not isinstance(page_id, str) or not page_id:
            continue
        row = found.setdefault(page_id, Row(page_id, first_at=str(line["at"])))
        row.lines += 1
        database = extra.get("database")
        if isinstance(database, dict) and isinstance(database.get("id"), str):
            row.database = database["id"]
        if isinstance(payload.get("title"), str) and payload["title"].strip():
            row.title = payload["title"]
        action = extra.get("action")
        if action in STATE_ACTIONS:
            row.archived = action == "archived"
        if isinstance(extra.get("properties"), dict):
            row.properties = dict(extra["properties"])
            row.line = str(line["id"])
        elif row.line is None or not row.properties:
            row.line = str(line["id"])
        relations = extra.get("relations")
        if isinstance(relations, dict):
            row.relations = {
                str(k): [i for i in v if isinstance(i, str)]
                for k, v in relations.items()
                if isinstance(v, list)
            }
    return found


def _instant(stamp: str) -> datetime:
    return stays.instant(stamp) or datetime.min.replace(tzinfo=UTC)


def notion_lines(lb: Logbook) -> tuple[list[Line], dict[str, Line]]:
    """The `sync notion` lines and the record's retractions, through the index."""
    with lb.index() as idx:
        lines = idx.of_source(KIND, SOURCE, "0000-01-01", "9999-12-31")
        retracted = retractions(idx.retractions())
    return lines, retracted


# -- dates ---------------------------------------------------------------------------------------------------


def local_day(text: object, days: day_start.DayStart) -> str | None:
    """A Notion date's local day: a date as it is, an instant on the record's clock."""
    if not isinstance(text, str) or len(text) < 10:
        return None
    if len(text) == 10:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return when.date().isoformat()
    return days.day(when).isoformat()


def _span(row: Row, mapping: PlanMap, days: day_start.DayStart) -> tuple[str, str] | None:
    when = row.date(mapping.date)
    if when is None:
        return None
    first = local_day(when["start"], days)
    if first is None:
        return None
    last = local_day(when.get("end"), days) or first
    return first, max(first, last)


# -- the answer ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    """The plan for one day: the five parts, each a JSON-ready mapping or list."""

    day: str
    mapped: bool
    tasks: dict[str, Any] | None = None
    sprint: dict[str, Any] | None = None
    trip: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"day": self.day, "mapped": self.mapped}
        if not self.mapped:
            out["said"] = NO_MAPPING
        out.update(
            {
                "tasks": self.tasks,
                "sprint": self.sprint,
                "trip": self.trip,
            }
        )
        return out


def _ref(row: Row, mapping: PlanMap) -> dict[str, Any]:
    out: dict[str, Any] = {"id": row.id, "title": row.title, "url": row.url, "line": row.line}
    when = row.date(mapping.date)
    if when is not None:
        out["date"] = when
    return out


def read(lb: Logbook, day: str) -> Plan:
    """The plan for `day`, `YYYY-MM-DD`, from the `sync notion` lines alone: `PlanError` for a
    mapping not the documented shape."""
    mapping = read_mapping(lb.root)
    if mapping is None:
        return Plan(day, False)
    days = day_start.of(lb.meta)
    lines, retracted = notion_lines(lb)
    rows = rows_of(lines, retracted)
    by_role: dict[str, list[Row]] = {role: [] for role in ROLES}
    for row in rows.values():
        role = mapping.role_of(row.database)
        if role is not None:
            by_role[role].append(row)
    sprint = _sprint(by_role["sprints"], mapping, days, day)
    tasks = _tasks(by_role["tasks"], sprint, mapping, days, day)
    trip = _trip(by_role["trips"], mapping, days, day)
    return Plan(
        day,
        True,
        tasks=tasks,
        sprint=None if sprint is None else _ref(sprint, mapping),
        trip=trip,
    )


def _sprint(rows: Sequence[Row], mapping: PlanMap, days: day_start.DayStart, day: str) -> Row | None:
    holding = [
        (span[0], row.title or "", row)
        for row in rows
        if not row.archived and (span := _span(row, mapping, days)) is not None and span[0] <= day <= span[1]
    ]
    if not holding:
        return None
    return max(holding, key=lambda found: (found[0], found[1]))[2]


def _tasks(
    rows: Sequence[Row], sprint: Row | None, mapping: PlanMap, days: day_start.DayStart, day: str
) -> dict[str, Any] | None:
    if "tasks" not in mapping.databases:
        return None
    in_sprint = sprint.related() if sprint is not None else set()
    chosen: list[tuple[str, str, Row]] = []
    for row in rows:
        span = _span(row, mapping, days)
        if span is None or span[0] > day or not row.open(mapping):
            continue
        overdue = span[1] < day
        if (
            overdue
            and "sprints" in mapping.databases
            and (sprint is None or (sprint.id not in row.related() and row.id not in in_sprint))
        ):
            continue
        chosen.append((str((row.date(mapping.date) or {}).get("start")), row.title or "", row))
    chosen.sort(key=lambda found: (found[0], found[1].casefold(), found[1], found[2].id))
    shown = []
    for _start, _title, row in chosen[:TASKS_SHOWN]:
        ref = _ref(row, mapping)
        status = row.properties.get(mapping.status)
        ref["status"] = status if isinstance(status, str) else None
        span = _span(row, mapping, days)
        ref["overdue"] = span is not None and span[1] < day  # past its last day: a range holds today
        shown.append(ref)
    rest = [row for _start, _title, row in chosen[TASKS_SHOWN:]]
    return {
        "rows": shown,
        "more": len(rest),
        "more_in_sprint": 0
        if sprint is None
        else sum(1 for row in rest if sprint.id in row.related() or row.id in in_sprint),
        "sprint": None if sprint is None else sprint.title,
        "said": NO_SPRINT if sprint is None and "sprints" in mapping.databases else None,
    }


def _trip(rows: Sequence[Row], mapping: PlanMap, days: day_start.DayStart, day: str) -> dict[str, Any] | None:
    ahead = [
        (span[0], row.title or "", row)
        for row in rows
        if not row.archived and (span := _span(row, mapping, days)) is not None and span[0] >= day
    ]
    if not ahead:
        return None
    first, _title, row = min(ahead, key=lambda found: (found[0], found[1].casefold(), found[2].id))
    ref = _ref(row, mapping)
    ref["days"] = (date.fromisoformat(first) - date.fromisoformat(day)).days
    return ref


# -- coverage ------------------------------------------------------------------------------------------------


def coverage(lb: Logbook) -> dict[str, dict[str, Any]] | None:
    """Per mapped database: its id, the rows and lines the record holds of it, its first line's `at`
    and local day; None without a mapping."""
    mapping = read_mapping(lb.root)
    if mapping is None:
        return None
    days = day_start.of(lb.meta)
    lines, retracted = notion_lines(lb)
    rows = rows_of(lines, retracted)
    out: dict[str, dict[str, Any]] = {}
    for role, database in mapping.databases.items():
        held = [row for row in rows.values() if row.database == database]
        firsts = [row.first_at for row in held if row.first_at]
        first = min(firsts, key=_instant) if firsts else None
        out[role] = {
            "id": database,
            "rows": len(held),
            "lines": sum(row.lines for row in held),
            "first": first,
            "first_day": days.day_of(first) if first else None,
        }
    return out


# -- the text ------------------------------------------------------------------------------------------------

DOT = " · "
NOUNS = {"tasks": "task", "sprints": "sprint", "trips": "trip"}


def _title(ref: Mapping[str, Any]) -> str:
    return str(ref.get("title") or UNTITLED)


def _in_sprint(tasks: Mapping[str, Any]) -> str:
    """` in Sprint 24` when every task counted is in it, `, 3 of them in Sprint 24` when some are."""
    if not tasks["sprint"] or not tasks["more_in_sprint"]:
        return ""
    if tasks["more_in_sprint"] == tasks["more"]:
        return f" in {tasks['sprint']}"
    return f", {tasks['more_in_sprint']} of them in {tasks['sprint']}"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" + ("" if n == 1 else "s")


def _days_text(n: int) -> str:
    return "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"


def _date_text(when: Mapping[str, Any] | None) -> str:
    if not when:
        return ""
    start, end = str(when.get("start") or "")[:10], str(when.get("end") or "")[:10]
    return f"{start} to {end}" if end and end != start else start


def rows(plan: Plan) -> list[str]:
    """`show plan` as text: the header, one row per part that holds something, then one row naming
    the parts that hold nothing."""
    if not plan.mapped:
        return [NO_MAPPING]
    head = f"plan  {plan.day}"
    if plan.sprint is not None:
        head += f"{DOT}{_title(plan.sprint)}, {_date_text(plan.sprint.get('date'))}  {plan.sprint['url']}"
    out = [head]
    empty: list[str] = []
    tasks = plan.tasks
    if tasks and tasks["rows"]:
        for n, t in enumerate(tasks["rows"]):
            label = "today" if n == 0 else ""
            late = f"{DOT}overdue" if t["overdue"] else ""
            status = f"{DOT}{t['status']}" if t.get("status") else ""
            out.append(f"  {label:<10} {_date_text(t.get('date'))}  {_title(t)}{status}{late}  {t['url']}")
        if tasks["more"]:
            out.append(f"  {'':<10} and {tasks['more']} more{_in_sprint(tasks)}")
    elif tasks is not None:
        empty.append("today's tasks")
    if tasks and tasks["said"]:
        out.append(f"  {'':<10} {tasks['said']}")
    if plan.trip is not None:
        t = plan.trip
        when = f"{_date_text(t.get('date'))}{DOT}{_days_text(t['days'])}"
        out.append(f"  {'next trip':<10} {_title(t)}{DOT}{when}  {t['url']}")
    else:
        empty.append("next trip")
    if empty:
        out.append(f"  nothing from: {', '.join(empty)}")
    return out


def coverage_rows(found: Mapping[str, Mapping[str, Any]] | None) -> list[str]:
    if found is None:
        return [NO_MAPPING]
    out = ["plan coverage: the record knows a row from a line `sync notion` wrote of it"]
    for role, c in found.items():
        noun = NOUNS[role]
        if not c["rows"]:
            out.append(f"  {role:<8} no line yet")
            continue
        rows_text = _plural(c["rows"], f"{noun} row")
        out.append(
            f"  {role:<8} {rows_text}{DOT}{_plural(c['lines'], 'line')}{DOT}first line {c['first_day']}"
        )
    out.append(
        "  a row no run has read (last edited before the first, or outside LOGBOOK_NOTION_ROOTS) is not"
        " in the record; one `sync notion --since` run from an earlier day reads it as it is now (not"
        " run here)"
    )
    return out
