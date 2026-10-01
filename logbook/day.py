"""The Day: one calendar day of the record, read back — `logbook day YYYY-MM-DD [--json]`.

A Day is the ordered list of the owner's stays and moves between 00:00 and 24:00 local, with what
attached to each and who was there, framed by the night before and the night after. It is read,
never written: `read(lb, day)` is a function of the record at one head, built from one
`reading.read` of the day and the day before (the night before is that day's night), located
through the index, so a multi-million-line record reads a day in the time its day takes. Every
number and name points at the lines it came from.

What a Day shows, in order:

1. The header: the date; where the night before and the night after were spent (the overnight
   stay, `stays.night`: a named place, `aboard <asset>` or the coordinates, home or away, or in
   transit when no stay reaches the minimum); the country of the day (`countries.country_of` on
   the night's stay, else the longest stay of the day, with the method); the day's all-day
   calendar entries.
2. The timeline: the owner's segments from `stays.derive` that touch the day — stays, stops and
   moves, each clipped to the day for display and keeping its real span — and the flights of the
   day from the `flight/v1` lines standing (`flights.standing`, the merged set: one line per
   flight, its `evidence` tracked, inferred or declared), as rows of their own; a move the flight
   covers names it. A run of consecutive segments aboard one asset — the owner's position matching
   the asset's own track (`stays._aboard`, ADR 0018) — is one stay `aboard <asset>`, with the
   asset's anchorages and passages inside it: the asset's movement never fragments the stay. A
   move with no points that lasts a silence or more (`merge_gap_s`), and is not a flight, is a
   gap in the track, said so, and it places nothing. To each row attach the day's lines that
   fall inside its span:
   events, transcripts, notes, mail threads and calls named; messages and photos counted; keepers
   (RFC 0024) named. Who was there (`present.company`) is split into confirmed — declared in a
   note, speaking in a transcript, attending a timed calendar entry — and proposed — a face in a
   photo, an attendee of an all-day entry; never the owner.
3. Unplaced: the day's events, transcripts, notes, mail and calls that fall inside no row — what
   the calendar planned where the track has nothing, or what happened while the tracker was
   silent.
4. The health line (`health.summary`): the night's sleep in hours, the day's steps, the resting
   heart rate, from the `health-sample/v1` lines standing, a correction superseding what it
   corrects.
5. The sources: every source with a line on the day, how many, and its newest line's time, so a
   tracker that fell silent at 14:02 is seen to have.

Thresholds are the record's (`policy/stays.json`), places and assets its own; nothing here is a
setting of the Day. ADR 0013: derived is disposable."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import countries as country_table
from . import flights as flight_lines
from . import health, keepers, present, reading, stays
from .chain import Line
from .export import parse_day
from .flights import Airports
from .reading import Reading
from .resolve import Ref
from .store import Logbook

ABOARD, FLIGHT, GAP = "aboard", "flight", "gap"
NAMED = ("event", "transcript", "note", "mail", "call", keepers.KIND)  # attachments listed by name
COUNTED = ("message", "photo")  # attachments counted
PLACED = ("event", "transcript", "note", "mail", "call")  # the kinds `unplaced` lists
NOTE_CHARS = 72
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
EN_DASH = "\u2013"
ARROW = "\u2192"
DOT = " · "


# -- the reading --------------------------------------------------------------------------------------------


def read(lb: Logbook, day: str, airports: Airports | None = None) -> dict[str, Any]:
    """The Day as one JSON-ready object. `ValueError` for a day that is not one;
    `stays.SettingsError` when the record's settings, places or assets file is not what it should
    be. Nothing is written, not even the settings file."""
    d = parse_day(day)
    before = (d - timedelta(days=1)).isoformat()
    rd = reading.read(lb, before, day, airports)
    tz = rd.tz
    day_start = datetime.combine(d, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    lines = [line for line in rd.lines if (at := stays.instant(line.get("at"))) and day_start <= at < day_end]
    lines.sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    owner = rd.owner
    segments = [s for s in rd.segments if s.subject is None and s.start < day_end and s.end > day_start]
    flights = _flights(rd, day, tz)
    entries = [
        _finish(entry, lines, rd, owner, flights) for entry in _entries(segments, rd, day_start, day_end)
    ]
    timeline = sorted(
        [*entries, *flights],
        key=lambda e: (e["within_day"]["start"] if "within_day" in e else e["start"], e["kind"] == FLIGHT),
    )
    night_after = rd.night_of(day)
    night_before = rd.night_of(before)
    all_day = [
        {"title": _title(line), "line": str(line["id"])}
        for line in lines
        if line.get("kind") == "event" and (line.get("payload") or {}).get("all_day") is True
    ]
    return {
        "day": day,
        "weekday": WEEKDAYS[d.weekday()],
        "tz": str(tz),
        "nights": {
            "before": _night_json(night_before, before, rd),
            "after": _night_json(night_after, day, rd),
        },
        "country": _country(night_after, segments, day_start, day_end, rd),
        "all_day": all_day,
        "timeline": timeline,
        "flights": flights,
        "unplaced": _unplaced(lines, entries, tz),
        "health": _health(lb, before, day, rd),
        "sources": _sources(lines),
    }


# -- the header ---------------------------------------------------------------------------------------------


def _where(s: stays.Segment, rd: Reading) -> str | None:
    """A stay's place: its name, else `aboard <asset>`, else its coordinates; None for a move."""
    if s.kind == stays.MOVE:
        return None
    if s.place:
        return s.place
    if s.aboard:
        return f"aboard {_asset_name(s.aboard, rd)}"
    return _coordinates(s)


def _coordinates(s: stays.Segment) -> str | None:
    return f"{s.lat:.4f},{s.lon:.4f}" if s.lat is not None and s.lon is not None else None


def _asset_name(asset_id: str, rd: Reading) -> str:
    asset = rd.assets.get(asset_id)
    return asset.name if asset else asset_id


def _night_json(night: stays.Night | None, day: str, rd: Reading) -> dict[str, Any]:
    if night is None or night.stay is None:
        return {
            "day": day,
            "where": None,
            "home": False,
            "aboard": None,
            "in_transit": True,
            "stay": None,
            "lines": [],
        }
    s = night.stay
    return {
        "day": night.day,
        "where": _where(s, rd),
        "home": night.home,
        "aboard": s.aboard,
        "in_transit": False,
        "stay": s.id,
        "lines": _stay_lines(s),
    }


def _stay_lines(s: stays.Segment) -> list[str]:
    return [id_ for id_ in (s.first_line, s.last_line) if id_]


def _country(
    night: stays.Night | None,
    segments: Sequence[stays.Segment],
    day_start: datetime,
    day_end: datetime,
    rd: Reading,
) -> dict[str, Any]:
    """The country of the night's stay (the rule `rollup countries` counts by); when the night is
    in transit, of the longest stay of the day; else unknown."""
    source, stay = None, None
    if night is not None and night.stay is not None:
        source, stay = "night", night.stay
    else:
        on_day = [s for s in segments if s.kind == stays.STAY]
        if on_day:
            source = "longest stay"
            stay = max(on_day, key=lambda s: (min(s.end, day_end) - max(s.start, day_start)).total_seconds())
    if stay is None or stay.lat is None or stay.lon is None:
        return {"code": None, "method": None, "by": None, "from": None}
    found = country_table.country_of(
        stay.lat, stay.lon, rd.places, rd.airports, country_table.Countries.load()
    )
    if found.code is None:
        return {"code": None, "method": None, "by": None, "from": source}
    return {"code": found.code, "method": found.method, "by": found.by, "from": source}


# -- the timeline -------------------------------------------------------------------------------------------


def _entries(
    segments: Sequence[stays.Segment], rd: Reading, day_start: datetime, day_end: datetime
) -> list[dict[str, Any]]:
    """The owner's segments as entries, a run of two or more consecutive segments aboard one asset
    folded into one `aboard` entry with the run inside it."""
    out: list[dict[str, Any]] = []
    run: list[stays.Segment] = []

    def flush() -> None:
        if len(run) == 1:
            out.append(_entry(run[0], rd, day_start, day_end))
        elif run:
            out.append(_aboard_entry(run, rd, day_start, day_end))
        run.clear()

    for s in segments:
        if run and s.aboard != run[-1].aboard:
            flush()
        if s.aboard is None:
            out.append(_entry(s, rd, day_start, day_end))
        else:
            run.append(s)
    flush()
    return out


def _entry(s: stays.Segment, rd: Reading, day_start: datetime, day_end: datetime) -> dict[str, Any]:
    tz = rd.tz
    out: dict[str, Any] = {
        "id": s.id,
        "kind": s.kind,
        "start": _stamp(s.start),
        "end": _stamp(s.end),
        "start_local": s.start.astimezone(tz).isoformat(timespec="seconds"),
        "end_local": s.end.astimezone(tz).isoformat(timespec="seconds"),
        "within_day": _within(s.start, s.end, day_start, day_end),
        "duration_s": s.duration_s,
        "where": _where(s, rd) if s.aboard is None else (s.place or _coordinates(s)),
        "place": s.place,
        "lat": None if s.lat is None else round(s.lat, 6),
        "lon": None if s.lon is None else round(s.lon, 6),
        "aboard": s.aboard,
        "mode": s.mode,
        "distance_m": None if s.distance_m is None else round(s.distance_m),
        "airports": list(s.airports),
        "points": s.points,
        "promoted": s.promoted,
        "gap": _is_gap(s, rd.settings),
        "lines": {"first": s.first_line, "last": s.last_line},
    }
    return out


def _aboard_entry(
    run: Sequence[stays.Segment], rd: Reading, day_start: datetime, day_end: datetime
) -> dict[str, Any]:
    first, last = run[0], run[-1]
    asset_id = str(first.aboard)
    asset = rd.assets.get(asset_id)
    anchor = next((s for s in run if s.kind != stays.MOVE), first)
    return {
        "id": f"{ABOARD}:{asset_id}:{first.start.astimezone(UTC).strftime('%Y%m%dT%H%MZ')}",
        "kind": ABOARD,
        "start": _stamp(first.start),
        "end": _stamp(last.end),
        "start_local": first.start.astimezone(rd.tz).isoformat(timespec="seconds"),
        "end_local": last.end.astimezone(rd.tz).isoformat(timespec="seconds"),
        "within_day": _within(first.start, last.end, day_start, day_end),
        "duration_s": int((last.end - first.start).total_seconds()),
        "where": f"aboard {_asset_name(asset_id, rd)}",
        "place": None,
        "lat": None if anchor.lat is None else round(anchor.lat, 6),
        "lon": None if anchor.lon is None else round(anchor.lon, 6),
        "aboard": asset_id,
        "asset": {
            "id": asset_id,
            "name": asset.name if asset else asset_id,
            "kind": asset.kind if asset else None,
        },
        "mode": None,
        "distance_m": round(sum(s.distance_m or 0 for s in run if s.kind == stays.MOVE)),
        "airports": [],
        "points": sum(s.points for s in run),
        "promoted": any(s.promoted for s in run),
        "gap": False,
        "inside": [_entry(s, rd, day_start, day_end) for s in run],
        "lines": {"first": first.first_line, "last": last.last_line},
    }


def _is_gap(s: stays.Segment, settings: stays.Settings) -> bool:
    """A move the tracker did not see: no points, a silence or longer, not a flight (a flight with
    the phone off explains itself) and not aboard an asset whose track fills it."""
    return (
        s.kind == stays.MOVE
        and s.points == 0
        and s.duration_s >= settings.merge_gap_s
        and s.mode != FLIGHT
        and s.aboard is None
    )


def _within(start: datetime, end: datetime, day_start: datetime, day_end: datetime) -> dict[str, Any]:
    """The part of a span that lies on the day: the Day runs from 00:00 to 24:00, so a stay that
    began the evening before shows from midnight, and keeps its real span beside."""
    a, b = max(start, day_start), min(end, day_end)
    return {"start": _stamp(a), "end": _stamp(b), "duration_s": int((b - a).total_seconds())}


def _finish(
    entry: dict[str, Any],
    lines: Sequence[Line],
    rd: Reading,
    owner: present.Owner,
    flights: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The entry with its attachments, its company and, for a move, the flights that cover it. A
    gap places nothing: the track says nothing about where the owner was, so its lines stay
    unplaced."""
    start, end = _instant(entry["start"]), _instant(entry["end"])
    if entry["gap"]:
        entry["attached"] = _attached(start, end, [], rd)
        entry["with"] = {"confirmed": [], "proposed": []}
        entry["flights"] = []
        return entry
    span = stays.Segment(
        kind=stays.STAY,
        subject=None,
        start=start,
        end=end,
        points=int(entry["points"]),
        lat=entry["lat"] if entry["lat"] is not None else 0.0,
        lon=entry["lon"] if entry["lon"] is not None else 0.0,
        place=entry["place"],
        aboard=entry["aboard"],
    )
    entry["attached"] = _attached(start, end, lines, rd)
    companions = (
        [] if entry["kind"] == stays.MOVE else present.company(span, lines, rd.identities, rd.places, owner)
    )  # with is a stay's relation: a photo from the train attaches to the move, nobody is with you on it
    entry["with"] = {
        "confirmed": [c.to_json() for c in companions if c.status == present.CONFIRMED],
        "proposed": [c.to_json() for c in companions if c.status == present.PROPOSED],
    }
    if entry["kind"] == stays.MOVE:
        entry["flights"] = [
            f["id"] for f in flights if _instant(f["start"]) < end and (_instant(f["end"]) or start) > start
        ]
    return entry


# -- flights ------------------------------------------------------------------------------------------------


def _flights(rd: Reading, day: str, tz: ZoneInfo) -> list[dict[str, Any]]:
    """The flight lines standing (RFC 0013 rule 4) dated the day, in time order."""
    out = []
    for line in flight_lines.standing(rd.of_kind(flight_lines.KIND)).values():
        payload = line.get("payload") or {}
        dated = payload.get("date") if isinstance(payload.get("date"), str) else rd.day_of(line)
        if dated != day:
            continue
        at = stays.instant(line.get("at"))
        if at is None:
            continue
        end = stays.instant(line.get("end"))
        out.append(
            {
                "id": str(line["id"]),
                "kind": FLIGHT,
                "start": _stamp(at),
                "end": None if end is None else _stamp(end),
                "start_local": at.astimezone(tz).isoformat(timespec="seconds"),
                "end_local": None if end is None else end.astimezone(tz).isoformat(timespec="seconds"),
                "carrier": payload.get("carrier"),
                "number": payload.get("number"),
                "from": _code(payload.get("from")),
                "to": _code(payload.get("to")),
                "evidence": payload.get("evidence"),
                "role": payload.get("role"),
                "aircraft": payload.get("aircraft"),
                "line": str(line["id"]),
            }
        )
    out.sort(key=lambda f: str(f["start"]))
    return out


def _code(ref: object) -> str | None:
    if not isinstance(ref, dict):
        return None
    code = ref.get("iata") or ref.get("icao")
    return str(code) if code else None


# -- attachments ------------------------------------------------------------------------------------------


def _inside(line: Line, start: datetime, end: datetime) -> bool:
    at = stays.instant(line.get("at"))
    if at is None:
        return False
    until = stays.instant(line.get("end"))
    if until is None or until == at:
        return start <= at <= end
    return at < end and until > start


def _attached(start: datetime, end: datetime, lines: Iterable[Line], rd: Reading) -> dict[str, Any]:
    events, transcripts, notes, calls, kept = [], [], [], [], []
    threads: dict[str, dict[str, Any]] = {}
    messages: list[str] = []
    photos: list[str] = []
    for line in lines:
        kind = line.get("kind")
        if kind not in NAMED and kind not in COUNTED:
            continue
        if not _inside(line, start, end):
            continue
        payload = line.get("payload") or {}
        id_ = str(line["id"])
        if kind == "event":
            if payload.get("all_day") is True:
                continue  # the day's, not the stay's
            events.append({"title": _title(line), "start": line["at"], "end": line.get("end"), "line": id_})
        elif kind == "transcript":
            transcripts.append({"title": _title(line), "line": id_})
        elif kind == "note":
            notes.append({"text": _note_text(payload), "line": id_})
        elif kind == "mail":
            key = str(payload.get("thread") or payload.get("message_id") or id_)
            thread = threads.setdefault(
                key,
                {
                    "subject": str(payload.get("subject") or "(no subject)"),
                    "thread": key,
                    "messages": 0,
                    "lines": [],
                },
            )
            thread["messages"] += 1
            thread["lines"].append(id_)
        elif kind == "call":
            calls.append(_call(payload, rd.names, id_))
        elif kind == keepers.KIND:
            kept.append({"name": keepers.name_of(line), "lane": payload.get("lane"), "line": id_})
        elif kind == "message":
            messages.append(id_)
        elif kind == "photo":
            photos.append(id_)
    return {
        "events": events,
        "transcripts": transcripts,
        "notes": notes,
        "mail": list(threads.values()),
        "calls": calls,
        "messages": {"count": len(messages), "lines": messages},
        "photos": {"count": len(photos), "lines": photos},
        "keepers": kept,
    }


def _title(line: Line) -> str:
    payload = line.get("payload") or {}
    kind = line.get("kind")
    if kind == "note":
        return _note_text(payload)
    if kind == "mail":
        return str(payload.get("subject") or "(no subject)")
    if kind == "call":
        return str(_call(payload, {}, "")["who"])
    return str(payload.get("title") or ("a recording" if kind == "transcript" else "an event"))


def _note_text(payload: Mapping[str, Any]) -> str:
    text = str(payload.get("text") or payload.get("title") or "")
    first = text.strip().splitlines()[0] if text.strip() else "(empty)"
    return first if len(first) <= NOTE_CHARS else first[: NOTE_CHARS - 1] + "…"


def _call(payload: Mapping[str, Any], names: Mapping[Ref, str], id_: str) -> dict[str, Any]:
    ref = payload.get("counterparty")
    who = None
    if isinstance(ref, dict) and isinstance(ref.get("kind"), str) and isinstance(ref.get("value"), str):
        who = names.get((ref["kind"], ref["value"])) or ref["value"]
    return {
        "who": who or "withheld",
        "direction": payload.get("direction"),
        "answered": payload.get("answered"),
        "duration_s": payload.get("duration_s"),
        "line": id_,
    }


def _unplaced(lines: Sequence[Line], entries: Sequence[dict[str, Any]], tz: ZoneInfo) -> list[dict[str, Any]]:
    """The day's placeable lines inside no entry: planned where the track has nothing."""
    spans = [(_instant(e["start"]), _instant(e["end"])) for e in entries if not e["gap"]]
    out = []
    for line in lines:
        kind = line.get("kind")
        if kind not in PLACED:
            continue
        payload = line.get("payload") or {}
        if kind == "event" and payload.get("all_day") is True:
            continue
        if any(_inside(line, start, end) for start, end in spans):
            continue
        out.append(
            {
                "kind": kind,
                "at": line["at"],
                "end": line.get("end"),
                "title": _title(line),
                "line": str(line["id"]),
            }
        )
    return out


# -- health and sources ----------------------------------------------------------------------------------


def _health(lb: Logbook, before: str, day: str, rd: Reading) -> dict[str, Any] | None:
    """The day's row of `health.summary`, from the health lines of the day and the day before (the
    night's sleep starts then), through the index; None when the day has none."""
    with lb.index() as idx:
        found = idx.by_kind(health.KIND, before, day)
    rows = health.summary([*found, *rd.retracted.values()], str(rd.tz))
    row = next((r for r in rows if r["day"] == day), None)
    if row is None:
        return None
    return {k: v for k, v in row.items() if k != "day"}


def _sources(lines: Sequence[Line]) -> list[dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for line in lines:
        source = str(line.get("source"))
        entry = found.setdefault(
            source, {"source": source, "lines": 0, "first": line["at"], "newest": line["at"]}
        )
        entry["lines"] += 1
        entry["first"] = min(entry["first"], line["at"])
        entry["newest"] = max(entry["newest"], line["at"])
    return sorted(found.values(), key=lambda e: (-e["lines"], e["source"]))


# -- helpers -----------------------------------------------------------------------------------------------


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The Day as text: the header, the timeline, what is unplaced, the health line, the sources."""
    tz = ZoneInfo(data["tz"])
    yield f"{data['day']}  {data['weekday']}"
    yield _row("night before", _night_text(data["nights"]["before"]))
    yield _row("night after", _night_text(data["nights"]["after"]))
    yield _row("country", _country_text(data["country"]))
    if data["all_day"]:
        yield _row("all day", ", ".join(a["title"] for a in data["all_day"]))
    yield ""
    if not data["timeline"]:
        yield _row("timeline", "nothing logged")
    for entry in data["timeline"]:
        yield from _entry_rows(entry, tz, indent="  ")
    if data["unplaced"]:
        yield ""
        for item in data["unplaced"]:
            yield _row(
                "unplaced", f"{_span_text(item['at'], item['end'], tz)}  {item['kind']:<6} {item['title']}"
            )
    yield ""
    yield _row("health", _health_text(data["health"]))
    if data["sources"]:
        yield _row("sources", DOT.join(_source_text(s, tz) for s in data["sources"]))
    else:
        yield _row("sources", "none")


def _row(label: str, text: str) -> str:
    return f"  {label:<13} {text}"


def _night_text(night: dict[str, Any]) -> str:
    if night["in_transit"]:
        return "in transit"
    return f"{night['where']}{DOT}{'home' if night['home'] else 'away'}"


def _country_text(country: dict[str, Any]) -> str:
    if country["code"] is None:
        return "unknown"
    by = {"place": f"place {country['by']}", "airport": f"nearest airport {country['by']}"}.get(
        str(country["method"]), str(country["method"])
    )
    text = f"{country['code']} ({by})"
    return text if country["from"] == "night" else f"{text}{DOT}from the {country['from']}"


def _entry_rows(entry: dict[str, Any], tz: ZoneInfo, indent: str, inside: bool = False) -> Iterator[str]:
    """One row for the entry, then its inner rows (an `aboard` entry's), then one row per named
    attachment and one for its company. `inside` rows are an asset's own grammar and do not repeat
    the asset's name."""
    if entry["kind"] == FLIGHT:
        route = f"{entry['carrier']} {entry['number']}  {entry['from']} {ARROW} {entry['to']}"
        clock = _span_text(entry["start"], entry["end"], tz)
        yield f"{indent}{clock:<12} {FLIGHT:<6} {route}{DOT}{entry['evidence']}"
        return
    clock = _span_text(entry["within_day"]["start"], entry["within_day"]["end"], tz, clip=True)
    kind = GAP if entry["gap"] else entry["kind"]
    parts: list[str] = []
    if entry["kind"] == ABOARD:
        asset = entry["asset"]
        head = asset["name"] + (f" ({asset['kind']})" if asset["kind"] else "")
        parts = [head, _duration_text(entry["within_day"]["duration_s"])]
    elif entry["kind"] == stays.MOVE:
        parts = [_duration_text(entry["within_day"]["duration_s"])]
        if entry["gap"]:
            parts.append("no points")
            parts.append(_distance_text(entry["distance_m"] or 0))
        else:
            parts.insert(0, _distance_text(entry["distance_m"] or 0))
            parts.append(entry["mode"] or "mode unknown")
            if entry["airports"]:
                parts.append(f"{entry['airports'][0]} {ARROW} {entry['airports'][1]}")
            if entry.get("aboard") and not inside:
                parts.append(f"aboard {entry['aboard']}")
    else:
        parts = [str(entry["where"]), _duration_text(entry["within_day"]["duration_s"])]
        if entry.get("aboard") and not inside:
            parts.append(f"aboard {entry['aboard']}")
        if entry["kind"] == stays.STOP:
            parts.append("stop")
    counts = _counts_text(entry.get("attached"))
    if counts:
        parts.append(counts)
    yield f"{indent}{clock:<12} {kind:<6} {DOT.join(parts)}"
    inner = indent + "    "
    for s in entry.get("inside", []):
        yield from _entry_rows({**s, "attached": None, "with": None}, tz, inner, inside=True)
    attached = entry.get("attached")
    if attached:
        for e in attached["events"]:
            yield f"{inner}{'event':<12} {e['title']} {_span_text(e['start'], e['end'], tz)}"
        for t in attached["transcripts"]:
            yield f"{inner}{'transcript':<12} {t['title']}"
        for n in attached["notes"]:
            yield f"{inner}{'note':<12} {n['text']}"
        for m in attached["mail"]:
            yield f"{inner}{'mail':<12} {m['subject']} ({_plural(m['messages'], 'message')})"
        for c in attached["calls"]:
            yield f"{inner}{'call':<12} {_call_text(c)}"
        for k in attached["keepers"]:
            yield f"{inner}{'keeper':<12} {k['name']} ({k['lane']})"
    company = entry.get("with")
    if company and (company["confirmed"] or company["proposed"]):
        confirmed = ", ".join(_companion_text(c) for c in company["confirmed"])
        proposed = ", ".join(_companion_text(c) for c in company["proposed"])
        text = confirmed
        if proposed:
            text = f"{text}{DOT}proposed {proposed}" if text else f"proposed {proposed}"
        yield f"{inner}{'with':<12} {text}"


def _counts_text(attached: dict[str, Any] | None) -> str:
    if not attached:
        return ""
    counts = [
        (len(attached["events"]), "event"),
        (len(attached["transcripts"]), "transcript"),
        (len(attached["notes"]), "note"),
        (len(attached["mail"]), "mail thread"),
        (len(attached["calls"]), "call"),
        (attached["messages"]["count"], "message"),
        (attached["photos"]["count"], "photo"),
        (len(attached["keepers"]), "keeper"),
    ]
    return ", ".join(_plural(n, noun) for n, noun in counts if n)


def _companion_text(c: dict[str, Any]) -> str:
    return f"{c['name']} ({', '.join(c['sources'])})"


def _call_text(c: dict[str, Any]) -> str:
    arrow = ARROW if c["direction"] == "outgoing" else "←"
    parts = [f"{arrow} {c['who']}"]
    if not c["answered"]:
        parts.append("no answer" if c["direction"] == "outgoing" else "missed")
    elif isinstance(c["duration_s"], int) and c["duration_s"] > 0:
        parts.append(f"{c['duration_s'] // 60} min" if c["duration_s"] >= 60 else f"{c['duration_s']} s")
    return ", ".join(parts)


def _health_text(row: dict[str, Any] | None) -> str:
    if row is None:
        return "no lines"
    parts = []
    if row["sleep_h"] is not None:
        parts.append(f"sleep {row['sleep_h']:.1f} h")
    if row["steps"] is not None:
        parts.append(f"{row['steps']:,} steps")
    if row["resting_hr"] is not None:
        parts.append(f"resting {row['resting_hr']} bpm")
    return DOT.join(parts) if parts else "no lines"


def _source_text(s: dict[str, Any], tz: ZoneInfo) -> str:
    return f"{s['source']} {_plural(s['lines'], 'line')}, last {_clock(s['newest'], tz)}"


def _clock(stamp: str, tz: ZoneInfo) -> str:
    return _instant(stamp).astimezone(tz).strftime("%H:%M")


def _span_text(start: str, end: str | None, tz: ZoneInfo, clip: bool = False) -> str:
    a = _instant(start).astimezone(tz)
    if end is None:
        return a.strftime("%H:%M")
    b = _instant(end).astimezone(tz)
    if clip and b.time() == time.min and b.date() > a.date():
        return f"{a:%H:%M}{EN_DASH}24:00"
    days = (b.date() - a.date()).days
    return f"{a:%H:%M}{EN_DASH}{b:%H:%M}" + (f"+{days}" if days else "")


def _duration_text(seconds: int) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "< 1 min"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h" if not minutes else f"{hours} h {minutes} min"


def _distance_text(metres: float) -> str:
    if metres < 1000:
        return f"{round(metres)} m"
    km = metres / 1000
    return f"{km:.1f} km" if km < 100 else f"{round(km)} km"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
