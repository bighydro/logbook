"""iCalendar files (.ics, RFC 5545) → event/v1 (RFC 0009).

The export every calendar can write: Google Calendar's settings page and Takeout (`Takeout/Calendar/
<calendar>.ics`, one file per calendar), Apple Calendar's File → Export, Outlook, Nextcloud, a subscribed
feed saved to disk. One event/v1 line per VEVENT, mapped as `ios_calendar` maps a CalendarItem row so
the same event from either source has the same shape: kind `event`, tier 1, source `ics`, `at` the
DTSTART and `end` the DTEND (else DTSTART plus DURATION) in UTC, `tz` the DTSTART's TZID when the zone
database knows it — a `/mozilla.org/…/Europe/Oslo` prefix is skipped over — else the record's own, with
the text kept under `extra.tzid`. A floating time (no TZID, no `Z`) is read in the record's zone, passed
by `logbook add` as `timezone`, else as UTC. A VALUE=DATE start is an all-day event: `at` its local
midnight, `end` the DTEND's (exclusive, as RFC 5545 has it) or the next one, `all_day` true. An end not
after the start is not one (all-day: the next midnight; timed: no end).

`title` SUMMARY, `notes` DESCRIPTION, `location` LOCATION (GEO under `extra.location`), `status` STATUS,
`calendar` `{id, name}` from the file's X-WR-CALNAME (the file name as `id` when there is none),
`organizer` ORGANIZER and `attendees` ATTENDEE as `mailto:` email refs (RFC 0006), CN as the name,
PARTSTAT as accepted / declined / tentative / none, an unknown one kept under the attendee's `extra`.
Occurrences are never expanded (rule 1): a master carries its RRULE text as `recurrence` (EXDATE and
RDATE verbatim under `extra`), a VEVENT with RECURRENCE-ID carries `recurrence_of`, its UID, and
`extra.original_date`.

`raw_id` is `<UID>@<LAST-MODIFIED, else DTSTAMP>` (rule 5), so an entry edited after an export is a new
line next time and the same export appends nothing; an exception is keyed `<UID>/<RECURRENCE-ID>@…` so
it never collides with its master. `supersedes` is never set on import (see `ios_calendar`). A VEVENT
with no DTSTART, an unreadable one, or one before 1900 (rule 4), and one with no UID, are skipped and
counted; so are VTODO and VJOURNAL components. VTIMEZONE, VALARM and anything else are ignored.

The parser is the small tolerant kind RFC 5545 asks readers to be, stdlib only: lines are unfolded,
BEGIN/END nest (an END that matches nothing is ignored, an outer END closes what is still open, so is the
end of the file), parameters may be quoted and multi-valued, TEXT escapes are undone, and every property
or component it does not know is passed over. Names are case-insensitive. A file is read whole: a
calendar export is megabytes, not gigabytes. Also reads a folder of such files (the Takeout `Calendar/`
folder among them), each in name order. Pure: no network, the source is never written.
"""

from __future__ import annotations

import math
import re
import zoneinfo
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any

NAME = "ics"
KIND = "event"
TIER = 1
SCHEMA = "event/v1"

HEAD = b"BEGIN:VCALENDAR"
SNIFF_BYTES = 64  # a BOM, blank lines and the BEGIN line
BOM = b"\xef\xbb\xbf"
PLACEHOLDER_BEFORE_YEAR = 1900  # as ios_calendar: a 1985 birthday is a plan, 1601 is a placeholder (rule 4)

EVENT_STATUS = {"CONFIRMED": "confirmed", "TENTATIVE": "tentative", "CANCELLED": "cancelled"}
PARTSTAT = {"ACCEPTED": "accepted", "DECLINED": "declined", "TENTATIVE": "tentative", "NEEDS-ACTION": "none"}
SKIPPED_COMPONENTS = {"VTODO": "skipped_todo", "VJOURNAL": "skipped_journal"}
MAILTO = "mailto:"
CHAIR = "CHAIR"

DATE = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
DATE_TIME = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})?(Z)?$", re.IGNORECASE)
DURATION = re.compile(
    r"^([+-])?P(?:(\d+)W)?(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$", re.IGNORECASE
)
LINE_END = re.compile(r"\r\n|\r|\n")  # str.splitlines would also split on U+2028 inside a value
ESCAPE = re.compile(r"\\(.)")
ESCAPES = {
    "n": "\n",
    "N": "\n",
    ",": ",",
    ";": ";",
    "\\": "\\",
}  # an escape we do not know keeps its backslash


@dataclass
class Property:
    """One content line: `NAME;PARAM=VALUE:value`, the name and parameter names upper-cased."""

    name: str
    params: dict[str, list[str]]
    value: str

    def param(self, name: str) -> str | None:
        values = self.params.get(name)
        return values[0] if values else None


@dataclass
class Component:
    """A BEGIN:…/END:… block: its own properties and the blocks nested in it, in file order."""

    name: str
    properties: list[Property] = field(default_factory=list)
    children: list[Component] = field(default_factory=list)

    def first(self, name: str) -> Property | None:
        return next((p for p in self.properties if p.name == name), None)

    def each(self, name: str) -> list[Property]:
        return [p for p in self.properties if p.name == name]


@dataclass
class _When:
    """A parsed DTSTART/DTEND/…: the instant, its wall-clock reading, whether it was a date."""

    local: datetime  # aware, in the property's own zone, else the fallback given, else UTC
    utc: datetime
    is_date: bool
    zone: zoneinfo.ZoneInfo | None  # the TZID when the zone database knows it; None for UTC or floating
    tzid: str | None  # the TZID text when it named a zone we do not know


# -- sniff -----------------------------------------------------------------------------


def sniff(path: Path) -> bool:
    """A file whose first bytes are BEGIN:VCALENDAR (after a BOM or blank lines, any case), whatever its
    extension; or a folder holding at least one such file. Never raises."""
    path = Path(path)
    try:
        if path.is_dir():
            return next(_calendar_files(path), None) is not None
        return _is_calendar(path)
    except OSError:
        return False


def _is_calendar(path: Path) -> bool:
    if not path.is_file():
        return False
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    return head.removeprefix(BOM).lstrip().upper().startswith(HEAD)


def _calendar_files(folder: Path) -> Iterator[Path]:
    """The calendar files directly in the folder, in name order; hidden files are not exports."""
    for p in sorted(folder.iterdir()):
        if not p.name.startswith(".") and _is_calendar(p):
            yield p


# -- run -------------------------------------------------------------------------------


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One event/v1 line per VEVENT, in file order (a folder: file by file, in name order), streamed.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `timezone` is the record's IANA
    zone (`logbook add` passes it): floating times and all-day events are read in it. `counts` tallies
    `skipped_no_start`, `skipped_bad_start`, `skipped_placeholder_date`, `skipped_no_uid`,
    `skipped_todo` and `skipped_journal`."""
    counts = counts if counts is not None else {}
    record_zone = _zone(timezone)
    path = Path(path)
    files = list(_calendar_files(path)) if path.is_dir() else [path]
    for file in files:
        for draft in _file(file, record_zone, counts):
            if not (since and draft["at"] < since):
                yield draft


def _file(
    path: Path, record_zone: zoneinfo.ZoneInfo | None, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for root in parse(text):
        if root.name == "VCALENDAR":
            calendar, components = _calendar(root, path), root.children
        else:  # a bare component with no VCALENDAR around it
            calendar, components = _calendar(None, path), [root]
        for component in components:
            if component.name == "VEVENT":
                draft = _draft(component, calendar, record_zone, counts)
                if draft is not None:
                    yield draft
            elif component.name in SKIPPED_COMPONENTS:
                _count(counts, SKIPPED_COMPONENTS[component.name])


def _calendar(root: Component | None, path: Path) -> dict[str, str]:
    """`{id, name?}`: X-WR-CALNAME names the calendar (Google and Apple write it); without one the file name
    is the id."""
    name = _text_value(root, "X-WR-CALNAME") if root is not None else ""
    return {"id": name, "name": name} if name else {"id": path.name}


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    event: Component, calendar: dict[str, str], record_zone: zoneinfo.ZoneInfo | None, counts: dict[str, int]
) -> dict[str, Any] | None:
    start_property = event.first("DTSTART")
    if start_property is None:
        _count(counts, "skipped_no_start")
        return None
    start = _when(start_property, record_zone)
    if start is None:
        _count(counts, "skipped_bad_start")
        return None
    if start.local.year < PLACEHOLDER_BEFORE_YEAR:
        _count(counts, "skipped_placeholder_date")
        return None
    uid = _text_value(event, "UID")
    if not uid:
        _count(counts, "skipped_no_uid")
        return None
    try:
        end = _end(event, start, record_zone)
    except (OverflowError, ValueError):  # the next midnight after 9999-12-31 does not exist
        _count(counts, "skipped_bad_start")
        return None
    extra: dict[str, Any] = {}
    if start.tzid:
        extra["tzid"] = start.tzid
    modified = _modified(event)
    payload: dict[str, Any] = {"schema": SCHEMA, "raw_id": uid}
    if modified:
        payload["modified_at"] = modified
    if title := _text_value(event, "SUMMARY"):
        payload["title"] = title
    payload["calendar"] = dict(calendar)
    payload["all_day"] = start.is_date
    _place(payload, extra, event)
    _people(payload, event)
    if status := _text_value(event, "STATUS"):
        if status.upper() in EVENT_STATUS:
            payload["status"] = EVENT_STATUS[status.upper()]
        else:
            extra["status"] = status
    bare = _recurrence(payload, extra, event, uid, start, record_zone)
    if notes := _text_value(event, "DESCRIPTION"):
        payload["notes"] = notes
    if extra:
        payload["extra"] = extra
    payload["raw_id"] = f"{bare}@{modified}" if modified else bare
    return {
        "at": _stamp(start.utc),
        "end": _stamp(end) if end is not None else None,
        "tz": start.zone.key if start.zone is not None else None,  # None: the logbook's own
        "source": NAME,
        "kind": KIND,
        "tier": TIER,
        "payload": payload,
    }


def _end(event: Component, start: _When, record_zone: zoneinfo.ZoneInfo | None) -> datetime | None:
    """The end in UTC: DTEND (a date with no zone of its own is read in the start's), else DTSTART plus
    DURATION, else the next local midnight for an all-day event and nothing for a timed one. An end before
    the start is not one (RFC 5545 forbids it); an all-day end must be after the start."""
    fallback = start.zone or record_zone
    end: datetime | None = None
    if (prop := event.first("DTEND")) is not None:
        when = _when(prop, fallback)
        end = when.utc if when is not None else None
    elif (prop := event.first("DURATION")) is not None:
        end = _add_duration(start.local, prop.value)
    if start.is_date:
        if end is None or end <= start.utc:
            end = (start.local + timedelta(days=1)).astimezone(UTC)
        return end
    return end if end is None or end >= start.utc else None


def _add_duration(local: datetime, text: str) -> datetime | None:
    """`P1W`, `P1DT2H30M`, `-PT30M` (RFC 5545 §3.3.6): weeks and days are wall-clock days in the event's
    zone, the time part is exact, as the RFC has it. None for anything else, including an empty `P`."""
    m = DURATION.match(text.strip())
    if m is None:
        return None
    sign = -1 if m.group(1) == "-" else 1
    weeks, days, hours, minutes, seconds = (int(g) if g else 0 for g in m.groups()[1:])
    if not (weeks or days or hours or minutes or seconds):
        return None
    try:
        moved = local + sign * timedelta(weeks=weeks, days=days)
        return moved.astimezone(UTC) + sign * timedelta(hours=hours, minutes=minutes, seconds=seconds)
    except (OverflowError, ValueError):
        return None


def _modified(event: Component) -> str | None:
    """LAST-MODIFIED, else DTSTAMP, as RFC3339 UTC: both MUST be UTC (RFC 5545), a floating one is read so."""
    for name in ("LAST-MODIFIED", "DTSTAMP"):
        prop = event.first(name)
        if prop is not None and (when := _when(prop, UTC)) is not None:
            return _stamp(when.utc)
    return None


def _place(payload: dict[str, Any], extra: dict[str, Any], event: Component) -> None:
    """`location` is the LOCATION text; GEO's `lat;lon` under `extra.location` as `ios_calendar` keeps a
    Location row's coordinates. Resolving the place is a resolution/v1 line, never done here."""
    if location := _text_value(event, "LOCATION"):
        payload["location"] = location
    geo = event.first("GEO")
    if geo is None:
        return
    parts = geo.value.split(";")
    if len(parts) != 2:
        return
    try:
        latitude, longitude = (float(p.strip()) for p in parts)
    except ValueError:
        return
    if (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90 <= latitude <= 90
        and -180 <= longitude <= 180
    ):
        extra["location"] = {"latitude": latitude, "longitude": longitude}


def _people(payload: dict[str, Any], event: Component) -> None:
    """ORGANIZER and ATTENDEE `mailto:` values as source-native email refs (RFC 0006), never resolved;
    anything that is not a mailto is passed over. Without an ORGANIZER, the first attendee with ROLE=CHAIR
    is the organizer, as `ios_calendar` reads the chair role."""
    organizer = event.first("ORGANIZER")
    if organizer is not None and (ref := _email_ref(organizer.value)) is not None:
        payload["organizer"] = ref
    attendees: list[dict[str, Any]] = []
    for prop in event.each("ATTENDEE"):
        ref = _email_ref(prop.value)
        if ref is None:
            continue
        if "organizer" not in payload and (prop.param("ROLE") or "").strip().upper() == CHAIR:
            payload["organizer"] = ref
            continue
        attendee: dict[str, Any] = {"ref": ref}
        if name := _text(prop.param("CN")):
            attendee["name"] = name
        partstat = _text(prop.param("PARTSTAT"))
        if partstat:
            attendee["response"] = PARTSTAT.get(partstat.upper(), "none")
            if partstat.upper() not in PARTSTAT:
                attendee["extra"] = {"partstat": partstat}
        attendees.append(attendee)
    if attendees:
        payload["attendees"] = attendees


def _email_ref(value: str) -> dict[str, str] | None:
    text = value.strip()
    if text[: len(MAILTO)].lower() != MAILTO:
        return None
    address = text[len(MAILTO) :].strip().lower()
    return {"kind": "email", "value": address} if address else None


def _recurrence(
    payload: dict[str, Any],
    extra: dict[str, Any],
    event: Component,
    uid: str,
    start: _When,
    record_zone: zoneinfo.ZoneInfo | None,
) -> str:
    """A master's RRULE text as `recurrence` (only a rule with a FREQ part is one; another goes under
    `extra.rrule`); an exception's RECURRENCE-ID as `recurrence_of` = the UID and `extra.original_date`.
    Returns the bare key: the UID, or `<UID>/<original date>` for an exception, which shares its master's
    UID and must not share its `raw_id`. EXDATE and RDATE are kept verbatim under `extra`."""
    rule = _text(prop.value) if (prop := event.first("RRULE")) is not None else ""
    bare = uid
    recurrence_id = event.first("RECURRENCE-ID")
    if recurrence_id is not None:
        payload["recurrence_of"] = uid
        original = _when(recurrence_id, start.zone or record_zone)
        if original is not None:
            extra["original_date"] = _stamp(original.utc)
            bare = f"{uid}/{extra['original_date']}"
        else:
            bare = f"{uid}/{_text(recurrence_id.value) or 'occurrence'}"
        if rule:
            extra["rrule"] = rule
    elif rule:
        if any(part.strip().upper().startswith("FREQ=") for part in rule.split(";")):
            payload["recurrence"] = rule
        else:
            extra["rrule"] = rule
    for name in ("EXDATE", "RDATE"):
        values = [p.value.strip() for p in event.each(name) if p.value.strip()]
        if values:
            extra[name.lower()] = values
    return bare


# -- values ----------------------------------------------------------------------------


def _when(prop: Property, fallback: tzinfo | None) -> _When | None:
    """A DATE (`20260307`, or VALUE=DATE) or DATE-TIME (`20260307T093000`, `…Z` for UTC) value. A local
    time is read in the TZID's zone, else `fallback`, else UTC; a date is its local midnight there. A
    `Z` time has no zone of its own. None for anything unreadable, or an instant no zone can place."""
    value = prop.value.strip()
    tzid = _text(prop.param("TZID"))
    zone = _zone(tzid)
    unknown = tzid if tzid and zone is None else None
    is_date = (prop.param("VALUE") or "").strip().upper() == "DATE"
    try:
        if m := DATE.match(value):
            year, month, day = (int(g) for g in m.groups())
            local = datetime(year, month, day, tzinfo=zone or fallback or UTC)
            is_date = True
        elif m := DATE_TIME.match(value):
            year, month, day, hour, minute = (int(g) for g in m.groups()[:5])
            second = int(m.group(6) or 0)
            if is_date:
                hour = minute = second = 0
            if m.group(7):  # UTC: a TZID beside it does not apply (RFC 5545 §3.3.5)
                local, zone, unknown = (
                    datetime(year, month, day, hour, minute, second, tzinfo=UTC),
                    None,
                    None,
                )
            else:
                local = datetime(year, month, day, hour, minute, second, tzinfo=zone or fallback or UTC)
        else:
            return None
        return _When(local, local.astimezone(UTC), is_date, zone, unknown)
    except (ValueError, OverflowError):
        return None


def _zone(name: object) -> zoneinfo.ZoneInfo | None:
    """The zone the database knows by that name, else by the longest suffix after a `/` that it knows
    (`/mozilla.org/20050126_1/Europe/Oslo`, `/freeassociation.sourceforge.net/Europe/Oslo`), else None."""
    text = _text(name)
    if not text:
        return None
    parts = text.split("/")
    for i in range(len(parts)):
        candidate = "/".join(parts[i:])
        if not candidate:
            continue
        try:
            return zoneinfo.ZoneInfo(candidate)
        except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
            continue
    return None


def _text_value(component: Component | None, name: str) -> str:
    """The first property's TEXT value with RFC 5545 escapes undone, stripped; empty when absent."""
    if component is None:
        return ""
    prop = component.first(name)
    return _unescape(prop.value).strip() if prop is not None else ""


def _unescape(value: str) -> str:
    return ESCAPE.sub(lambda m: ESCAPES.get(m.group(1), m.group(0)), value)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


# -- the parser ------------------------------------------------------------------------


def parse(text: str) -> list[Component]:
    """Every top-level component in the text. Tolerant: a line without a name or a colon is skipped, an END
    that matches nothing open is ignored, an END for an outer component closes the inner ones, and a
    component still open at the end of the text is closed there."""
    roots: list[Component] = []
    stack: list[Component] = []
    for line in _unfold(text):
        prop = _content_line(line)
        if prop is None:
            continue
        if prop.name == "BEGIN":
            component = Component(prop.value.strip().upper())
            (stack[-1].children if stack else roots).append(component)
            stack.append(component)
        elif prop.name == "END":
            name = prop.value.strip().upper()
            if any(c.name == name for c in stack):
                while stack.pop().name != name:
                    pass
        elif stack:
            stack[-1].properties.append(prop)
    return roots


def _unfold(text: str) -> Iterator[str]:
    """Physical lines → content lines: a line starting with a space or tab continues the one before
    (RFC 5545 §3.1), with that one character dropped. CRLF, LF or CR."""
    current: str | None = None
    for raw in LINE_END.split(text):
        if raw[:1] in (" ", "\t") and current is not None:
            current += raw[1:]
            continue
        if current is not None:
            yield current
        current = raw
    if current is not None:
        yield current


def _content_line(line: str) -> Property | None:
    """`NAME;PARAM=VALUE,"quoted:value";OTHER=V:value`. Names upper-cased; a parameter value in double
    quotes may hold `:`, `;` and `,`; several values are comma-separated. None for a line with no name or
    no colon after the parameters, which the parser skips."""
    n = len(line)
    i = _scan(line, 0, ";:")
    name = line[:i].strip().upper()
    if not name or i == n:
        return None
    params: dict[str, list[str]] = {}
    while i < n and line[i] == ";":
        j = _scan(line, i + 1, "=;:")
        key = line[i + 1 : j].strip().upper()
        values: list[str] = []
        i = j
        if i < n and line[i] == "=":
            i += 1
            while True:
                if i < n and line[i] == '"':
                    j = line.find('"', i + 1)
                    j = n if j < 0 else j
                    values.append(line[i + 1 : j])
                    i = min(j + 1, n)
                else:
                    j = _scan(line, i, ",;:")
                    values.append(line[i:j])
                    i = j
                if i < n and line[i] == ",":
                    i += 1
                else:
                    break
        if key:
            params.setdefault(key, []).extend(values)
        if i < n and line[i] not in ";:":  # something after a closing quote: skip to the next delimiter
            i = _scan(line, i, ";:")
    if i >= n or line[i] != ":":
        return None
    return Property(name, params, line[i + 1 :])


def _scan(line: str, start: int, stop: str) -> int:
    """The index of the first character of `stop` at or after `start`, else the end of the line."""
    for i in range(start, len(line)):
        if line[i] in stop:
            return i
    return len(line)
