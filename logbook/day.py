"""The Day: one calendar day of the record, read back — `logbook day YYYY-MM-DD [--json]`.

A Day is the ordered list of the owner's stays and moves between 00:00 and 24:00 local, with what
attached to each and who was there, framed by the night before and the night after. It is read,
never written: `read(lb, day)` is a function of the record at one head, built from one
`reading.read` of the day and the day before (the night before is that day's night), located
through the index, so a multi-million-line record reads a day in the time its day takes. Every
number and name points at the lines it came from.

What a Day shows, in order:

1. The header: the date; where the night before and the night after were spent (the overnight
   stay, `stays.night`: a named place, `aboard <asset>` with the asset's position that night, the
   home place a night within 400 m of it lies by, or the coordinates with `near <place>, x km`,
   home or away, or in transit when no stay reaches the minimum); the country of the day
   (`countries.country_of` on the night's position, else the longest stay of the day, with the
   method); the day's all-day calendar entries.
2. The timeline: the owner's segments from `stays.derive` that touch the day — stays, stops and
   moves, each clipped to the day for display and keeping its real span — and the flights of the
   day from the `flight/v1` lines standing (`flights.standing`, the merged set: one line per
   flight, its `evidence` tracked, inferred or declared), as rows of their own; a move the flight
   covers names it. A stay aboard an asset — the owner's position matching the asset's own track
   for twenty minutes or longer (`stays._aboard`, ADR 0018), the run of stays and moves aboard it
   folded into one stay by `stays.fold` — is one `aboard <asset>` row, with the asset's berths,
   passages and anchorages inside it: the asset's movement never fragments the stay. A
   move with no points that lasts a silence or more (`merge_gap_s`), and is not a flight, is a
   gap in the track, said so, and it places nothing. To each row attach the day's lines that
   fall inside its span:
   events, transcripts, notes, mail threads and calls named; messages and photos counted; keepers
   (RFC 0024) named. A calendar entry several sources carry — the same start and end, the same
   flight or the same title, case and accents aside (`events.fold`) — is one event, `×N sources`.
   Who was there (`present.company`) is split into confirmed — declared in a
   note, speaking in a transcript, attending a timed calendar entry — and proposed — a face in a
   photo, an attendee of an all-day entry; never the owner.
3. Unplaced: the day's events, transcripts, notes, mail and calls that fall inside no row — what
   the calendar planned where the track has nothing, or what happened while the tracker was
   silent.
4. The health line (`health.summary`): the night's sleep in hours, the day's steps, the resting
   heart rate, from the `health-sample/v1` lines standing, a correction superseding what it
   corrects. Then, when the day has a `transaction/v1` line, the spend line (`ledger.spend`): the
   totals per currency in the lines' own currencies, how many transactions, the merchants.
   And when the day has `weather/v1` lines (RFC 0026, `logbook sync weather`), one
   weather line (`weather.day_row`): the cluster of the night after when the day has one, else
   the first, every cluster of the day under `places`; a day without them has no row.
5. The sources: every source with a line on the day, how many, and its newest line's time, so a
   tracker that fell silent at 14:02 is seen to have.
6. From the circle: for every page another record shared for this day and `logbook receive`
   verified (`share.pages`, RFC 0025), a `from <name>` section — how many lines, by kind, the tier
   it was shared at and when, and the titles of its events, transcripts, notes, mail and calls.
   A received page is read from `<root>/circle/<from>/<date>/`, never from the chain.

Thresholds are the record's (`policy/stays.json`), places and assets its own; nothing here is a
setting of the Day. ADR 0013: derived is disposable."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import countries as country_table
from . import events, health, keepers, ledger, present, reading, share, stays, story, trips, weather
from . import flights as flight_lines
from . import places as named_places
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


def read(
    lb: Logbook, day: str, airports: Airports | None = None, tiers: Sequence[int] | None = None
) -> dict[str, Any]:
    """The Day as one JSON-ready object; through the gate `tiers` when given (`reading.read`), the
    health and story lines included. `ValueError` for a day that is not one; `stays.SettingsError`
    when the record's settings, places or assets file is not what it should be. Nothing is written,
    not even the settings file."""
    d = parse_day(day)
    before = (d - timedelta(days=1)).isoformat()
    rd = reading.read(lb, before, day, airports, tiers)
    with lb.index() as idx:
        found = reading.crossing(idx.by_kind(health.KIND, before, day), tiers)
        # every story: a story is about a day it was not told on
        told = reading.crossing(idx.by_kind(story.KIND), tiers)
    data = of_reading(rd, day, health_rows(found, rd).get(day), stories=story.standing(told, rd.retracted))
    data["received"] = received(lb, day)
    return data


def of_reading(
    rd: Reading,
    day: str,
    health_row: dict[str, Any] | None,
    lines: Sequence[Line] | None = None,
    stories: Sequence[Line] | None = None,
) -> dict[str, Any]:
    """The Day of `day` from a reading that holds the day before it and the day, its night after
    inside (as `reading.read` reads a window): what `read` builds, for a caller that read a window
    once and asks for each day in it (`days`). `lines` are the day's lines when the caller has
    bucketed the reading's by day already, else they are picked from the reading's; `health_row` is
    the day's row of `health_rows`, None when the day has none; `stories` are the record's story
    lines standing (RFC 0028), of which the ones about the day are listed apart from the timeline,
    none when the caller read none."""
    d = parse_day(day)
    before = (d - timedelta(days=1)).isoformat()
    tz = rd.tz
    day_start = datetime.combine(d, time.min, tzinfo=tz)
    day_end = day_start + timedelta(days=1)
    if lines is None:
        lines = [
            line for line in rd.lines if (at := stays.instant(line.get("at"))) and day_start <= at < day_end
        ]
    lines = sorted(lines, key=lambda line: (str(line["at"]), int(line["seq"])))
    folded, stands_for = events.fold(lines, flight_lines.Airlines.load())  # one row per calendar entry
    owner = rd.owner
    segments = [s for s in rd.derived.folded if s.start < day_end and s.end > day_start]
    flights = _flights(rd, day, tz)
    entries = [
        _finish(entry, folded, stands_for, rd, owner, flights)
        for entry in _entries(segments, rd, day_start, day_end)
    ]
    timeline = sorted(
        [*entries, *flights],
        key=lambda e: (e["within_day"]["start"] if "within_day" in e else e["start"], e["kind"] == FLIGHT),
    )
    night_after = rd.night_of(day)
    night_before = rd.night_of(before)
    all_day = [
        {"title": _title(line), "line": str(line["id"]), **_stands_for(line, stands_for)}
        for line in folded
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
        "unplaced": _unplaced(folded, stands_for, entries, tz),
        "stories": [story.summary(line, rd.names) for line in story.about(stories or (), day)],
        "health": health_row,
        "spend": ledger.spend(lines, day),
        "weather": weather.day_row(
            weather.by_day(lines).get(day, []), None if night_after is None else night_after.position
        ),
        "sources": _sources(lines),  # every line, the folded calendar entries too
    }


# -- the header ---------------------------------------------------------------------------------------------


def _where(s: stays.Segment, rd: Reading, home: bool = False) -> str | None:
    """A stay's place: `aboard <asset>` for a stay aboard one, else its name, else — a night at
    home by the 400 m rule (`stays.HOME_NEAR_M`, `home`) — the home place it lies by, else its
    coordinates; None for a move."""
    if s.kind == stays.MOVE:
        return None
    if s.inside or (s.aboard and not s.place):
        return f"aboard {_asset_name(s.aboard or '', rd)}"
    if s.place:
        return s.place
    if home and s.lat is not None and s.lon is not None:
        near = named_places.nearest(s.lat, s.lon, named_places.home_places(rd.places))
        if near is not None:
            return near[0].name
    return _coordinates(s, rd)


def _coordinates(s: stays.Segment, rd: Reading) -> str | None:
    """The route's rule (`trips.coordinates_label`): the airport's code and city, `ZRH, Zurich`,
    when the stay is at one (3.5 km from the reference point of an airport with scheduled traffic,
    2 km from any other); else `lat,lon`, with `near <place>, x km` for the nearest named place
    within 5 km, else the city of the nearest large airport within 30 km in parentheses, so a
    reader sees `53.5998,10.0130 (Hamburg)`."""
    if s.lat is None or s.lon is None:
        return None
    return trips.coordinates_label(s.lat, s.lon, rd.places, rd.airports)


def _asset_name(asset_id: str, rd: Reading) -> str:
    asset = rd.assets.get(asset_id)
    return asset.name if asset else asset_id


def _night_json(night: stays.Night | None, day: str, rd: Reading) -> dict[str, Any]:
    """The night: where, home or away, the asset when aboard and the night's position — the
    asset's for a night aboard (where it lay for the longest part of the night), else the stay's
    centre — the stay's id and its first and last location line."""
    if night is None or night.stay is None:
        return {
            "day": day,
            "where": None,
            "home": False,
            "aboard": None,
            "in_transit": True,
            "stay": None,
            "position": None,
            "lines": [],
        }
    s = night.stay
    position = night.position
    return {
        "day": night.day,
        "where": _where(s, rd, night.home),
        "home": night.home,
        "aboard": s.aboard,
        "in_transit": False,
        "stay": s.id,
        "position": None
        if position is None
        else {"lat": round(position[0], 6), "lon": round(position[1], 6)},
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
    """The country of the night's position (the rule `rollup countries` counts by: aboard an
    asset, where it lay); when the night is in transit, of the longest stay of the day; else
    unknown."""
    source, stay = None, None
    if night is not None and night.stay is not None:
        source, stay = "night", night.innermost
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
    """The owner's folded segments (`stays.fold`) as entries: a stay aboard an asset is one
    `aboard` entry with the part of its run that touches the day inside it."""
    return [
        _aboard_entry(s, rd, day_start, day_end) if s.inside else _entry(s, rd, day_start, day_end)
        for s in segments
    ]


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
        "where": _where(s, rd) if s.aboard is None else (s.place or _coordinates(s, rd)),
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
    container: stays.Segment, rd: Reading, day_start: datetime, day_end: datetime
) -> dict[str, Any]:
    """A stay aboard an asset as an `aboard` entry: the whole stay's span and centre (the
    anchorage the owner spent longest at), the asset, and inside it the segments of the run that
    touch the day, each an entry of its own; its distance is the passages' on the day."""
    asset_id = str(container.aboard)
    asset = rd.assets.get(asset_id)
    run = [s for s in container.inside if s.start < day_end and s.end > day_start]
    return {
        "id": f"{ABOARD}:{asset_id}:{container.start.astimezone(UTC).strftime('%Y%m%dT%H%MZ')}",
        "kind": ABOARD,
        "start": _stamp(container.start),
        "end": _stamp(container.end),
        "start_local": container.start.astimezone(rd.tz).isoformat(timespec="seconds"),
        "end_local": container.end.astimezone(rd.tz).isoformat(timespec="seconds"),
        "within_day": _within(container.start, container.end, day_start, day_end),
        "duration_s": container.duration_s,
        "where": f"aboard {_asset_name(asset_id, rd)}",
        "place": None,
        "lat": None if container.lat is None else round(container.lat, 6),
        "lon": None if container.lon is None else round(container.lon, 6),
        "aboard": asset_id,
        "asset": {
            "id": asset_id,
            "name": asset.name if asset else asset_id,
            "kind": asset.kind if asset else None,
        },
        "mode": None,
        "distance_m": round(sum(s.distance_m or 0 for s in run if s.kind == stays.MOVE)),
        "airports": [],
        "points": container.points,
        "promoted": container.promoted,
        "gap": False,
        "inside": [_entry(s, rd, day_start, day_end) for s in run],
        "lines": {"first": container.first_line, "last": container.last_line},
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
    stands_for: Mapping[str, events.Folded],
    rd: Reading,
    owner: present.Owner,
    flights: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    """The entry with its attachments, its company and, for a move, the flights that cover it. A
    gap places nothing: the track says nothing about where the owner was, so its lines stay
    unplaced. `lines` are the day's with the calendar entries folded (`events.fold`),
    `stands_for` what each kept entry stands for."""
    start, end = _instant(entry["start"]), _instant(entry["end"])
    if entry["gap"]:
        entry["attached"] = _attached(start, end, [], stands_for, rd)
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
    entry["attached"] = _attached(start, end, lines, stands_for, rd)
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


def _attached(
    start: datetime,
    end: datetime,
    lines: Iterable[Line],
    stands_for: Mapping[str, events.Folded],
    rd: Reading,
) -> dict[str, Any]:
    found_events, transcripts, notes, calls, kept = [], [], [], [], []
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
            found_events.append(
                {
                    "title": _title(line),
                    "start": line["at"],
                    "end": line.get("end"),
                    "line": id_,
                    **_stands_for(line, stands_for),
                }
            )
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
        "events": found_events,
        "transcripts": transcripts,
        "notes": notes,
        "mail": list(threads.values()),
        "calls": calls,
        "messages": {"count": len(messages), "lines": messages},
        "photos": {"count": len(photos), "lines": photos},
        "keepers": kept,
    }


def _stands_for(line: Line, stands_for: Mapping[str, events.Folded]) -> dict[str, Any]:
    """The sources a kept calendar entry stands for and the ids of their lines, its own first; a
    line no other source repeats stands for itself."""
    folded = stands_for.get(str(line["id"]))
    if folded is None:
        return {"sources": [str(line.get("source"))], "lines": [str(line["id"])]}
    return {"sources": list(folded.sources), "lines": list(folded.lines)}


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


def _unplaced(
    lines: Sequence[Line],
    stands_for: Mapping[str, events.Folded],
    entries: Sequence[dict[str, Any]],
    tz: ZoneInfo,
) -> list[dict[str, Any]]:
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
        item = {
            "kind": kind,
            "at": line["at"],
            "end": line.get("end"),
            "title": _title(line),
            "line": str(line["id"]),
        }
        if kind == "event":
            item.update(_stands_for(line, stands_for))
        out.append(item)
    return out


# -- health and sources ----------------------------------------------------------------------------------


def health_rows(found: Iterable[Line], rd: Reading) -> dict[str, dict[str, Any]]:
    """By day, the rows of `health.summary` over `found` — the health lines of the days asked for and
    the day before the first (the night's sleep starts then), from the index — with the reading's
    retractions, so a retracted line is out. A day with no health lines has no row."""
    rows = health.summary([*found, *rd.retracted.values()], str(rd.tz))
    return {str(row["day"]): {k: v for k, v in row.items() if k not in ("day", "by")} for row in rows}


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


# -- from the circle ---------------------------------------------------------------------------------------


def received(lb: Logbook, day: str) -> list[dict[str, Any]]:
    """The pages the circle shared for `day` that `receive` kept, one row each: who, when, at what
    tier, how many lines by kind, and the titles of the named kinds with their line ids."""
    rows: list[dict[str, Any]] = []
    for page in share.pages(lb, day):
        kinds = Counter(str(line.get("kind")) for line in page.lines)
        rows.append(
            {
                "from": page.sender,
                "owner_id": page.manifest.get("from"),
                "created": page.manifest.get("created"),
                "max_tier": page.manifest.get("max_tier"),
                "lines": len(page.lines),
                "held_back": page.manifest.get("held_back"),
                "by_kind": dict(sorted(kinds.items())),
                "named": [
                    {
                        "kind": str(line["kind"]),
                        "at": str(line["at"]),
                        "title": _title(line),
                        "line": str(line["id"]),
                    }
                    for line in page.lines
                    if line.get("kind") in PLACED
                ],
                "attachments": len(page.manifest.get("attachments") or []),
            }
        )
    return rows


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
    yield _row("night before", night_text(data["nights"]["before"]))
    yield _row("night after", night_text(data["nights"]["after"]))
    yield _row("country", country_text(data["country"]))
    if data["all_day"]:
        yield _row("all day", ", ".join(a["title"] + sources_text(a) for a in data["all_day"]))
    yield ""
    if not data["timeline"]:
        yield _row("timeline", "nothing logged")
    for entry in data["timeline"]:
        yield from _entry_rows(entry, tz, indent="  ")
    if data["unplaced"]:
        yield ""
        for item in data["unplaced"]:
            span = span_text(item["at"], item["end"], tz)
            yield _row("unplaced", f"{span}  {item['kind']:<6} {item['title']}{sources_text(item)}")
    yield from story.rows(data.get("stories") or (), tz)
    yield ""
    yield _row("health", health_text(data["health"]))
    if data.get("spend"):
        yield _row("spend", ledger.spend_text(data["spend"]))
    if data.get("weather"):
        yield _row("weather", weather.text(data["weather"], data["tz"]))
    if data["sources"]:
        yield _row("sources", DOT.join(_source_text(s, tz) for s in data["sources"]))
    else:
        yield _row("sources", "none")
    for page in data.get("received") or []:
        yield ""
        yield _row(f"from {page['from']}", received_text(page))
        for item in page["named"]:
            yield f"      {item['kind']:<10} {item['title']}"


def received_text(page: dict[str, Any]) -> str:
    """`4 lines · location 2 · note 1 · photo 1 · tier 2 · shared 2026-06-14`."""
    parts = [_plural(int(page["lines"]), "line")]
    parts += [f"{kind} {n}" for kind, n in page["by_kind"].items()]
    parts.append(f"tier {page['max_tier']}")
    created = str(page.get("created") or "")
    if created:
        parts.append(f"shared {created[:10]}")
    return DOT.join(parts)


def _row(label: str, text: str) -> str:
    return f"  {label:<13} {text}"


def night_text(night: dict[str, Any]) -> str:
    """`Home · home`; aboard an asset, the asset's position that night between: `aboard Solvind ·
    59.8500,10.6000 · away`."""
    if night["in_transit"]:
        return "in transit"
    parts = [str(night["where"])]
    if night["aboard"] and night.get("position"):
        parts.append(f"{night['position']['lat']:.4f},{night['position']['lon']:.4f}")
    parts.append("home" if night["home"] else "away")
    return DOT.join(parts)


def country_text(country: dict[str, Any]) -> str:
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
        clock = span_text(entry["start"], entry["end"], tz)
        yield f"{indent}{clock:<12} {FLIGHT:<6} {route}{DOT}{entry['evidence']}"
        return
    clock = span_text(entry["within_day"]["start"], entry["within_day"]["end"], tz, clip=True)
    kind = GAP if entry["gap"] else entry["kind"]
    parts: list[str] = []
    if entry["kind"] == ABOARD:
        asset = entry["asset"]
        head = asset["name"] + (f" ({asset['kind']})" if asset["kind"] else "")
        parts = [head, duration_text(entry["within_day"]["duration_s"])]
    elif entry["kind"] == stays.MOVE:
        parts = [duration_text(entry["within_day"]["duration_s"])]
        if entry["gap"]:
            parts.append("no points")
            parts.append(distance_text(entry["distance_m"] or 0))
        else:
            parts.insert(0, distance_text(entry["distance_m"] or 0))
            parts.append(entry["mode"] or "mode unknown")
            if entry["airports"]:
                parts.append(f"{entry['airports'][0]} {ARROW} {entry['airports'][1]}")
            if entry.get("aboard") and not inside:
                parts.append(f"aboard {entry['aboard']}")
    else:
        parts = [str(entry["where"]), duration_text(entry["within_day"]["duration_s"])]
        if entry.get("aboard") and not inside:
            parts.append(f"aboard {entry['aboard']}")
    counts = _counts_text(entry.get("attached"))
    if counts:
        parts.append(counts)
    elif entry["kind"] == stays.STOP and not inside:
        parts.append("nothing attached")  # the kind column already says stop
    yield f"{indent}{clock:<12} {kind:<6} {DOT.join(parts)}"
    inner = indent + "    "
    for s in entry.get("inside", []):
        yield from _entry_rows({**s, "attached": None, "with": None}, tz, inner, inside=True)
    attached = entry.get("attached")
    if attached:
        for e in attached["events"]:
            span = span_text(e["start"], e["end"], tz)
            yield f"{inner}{'event':<12} {e['title']} {span}{sources_text(e)}"
        for t in attached["transcripts"]:
            yield f"{inner}{'transcript':<12} {t['title']}"
        for n in attached["notes"]:
            yield f"{inner}{'note':<12} {n['text']}"
        for m in attached["mail"]:
            yield f"{inner}{'mail':<12} {m['subject']} ({_plural(m['messages'], 'message')})"
        for c in attached["calls"]:
            yield f"{inner}{'call':<12} {call_text(c)}"
        for k in attached["keepers"]:
            yield f"{inner}{'keeper':<12} {k['name']} ({k['lane']})"
    company = entry.get("with")
    if company and (company["confirmed"] or company["proposed"]):
        confirmed = ", ".join(companion_text(c) for c in company["confirmed"])
        proposed = ", ".join(companion_text(c) for c in company["proposed"])
        text = confirmed
        if proposed:
            text = f"{text}{DOT}proposed {proposed}" if text else f"proposed {proposed}"
        yield f"{inner}{'with':<12} {text}"


def sources_text(item: Mapping[str, Any]) -> str:
    """` · ×N sources` for a calendar entry several sources carry; nothing for one source."""
    sources = item.get("sources") or []
    return f"{DOT}×{len(sources)} sources" if len(sources) > 1 else ""


def counts(attached: Mapping[str, Any] | None) -> list[tuple[int, str]]:
    """How many of each an entry has attached, as (count, noun), the empty kinds out; nothing for
    a row with no attachments (a flight, an asset's inner row)."""
    if not attached:
        return []
    found = [
        (len(attached["events"]), "event"),
        (len(attached["transcripts"]), "transcript"),
        (len(attached["notes"]), "note"),
        (len(attached["mail"]), "mail thread"),
        (len(attached["calls"]), "call"),
        (attached["messages"]["count"], "message"),
        (attached["photos"]["count"], "photo"),
        (len(attached["keepers"]), "keeper"),
    ]
    return [(n, noun) for n, noun in found if n]


def _counts_text(attached: dict[str, Any] | None) -> str:
    return ", ".join(_plural(n, noun) for n, noun in counts(attached))


def companion_text(c: dict[str, Any]) -> str:
    return f"{c['name']} ({', '.join(c['sources'])})"


def call_text(c: dict[str, Any]) -> str:
    arrow = ARROW if c["direction"] == "outgoing" else "←"
    parts = [f"{arrow} {c['who']}"]
    if not c["answered"]:
        parts.append("no answer" if c["direction"] == "outgoing" else "missed")
    elif isinstance(c["duration_s"], int) and c["duration_s"] > 0:
        parts.append(f"{c['duration_s'] // 60} min" if c["duration_s"] >= 60 else f"{c['duration_s']} s")
    return ", ".join(parts)


def health_text(row: dict[str, Any] | None) -> str:
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


def span_text(start: str, end: str | None, tz: ZoneInfo, clip: bool = False) -> str:
    a = _instant(start).astimezone(tz)
    if end is None:
        return a.strftime("%H:%M")
    b = _instant(end).astimezone(tz)
    if clip and b.time() == time.min and b.date() > a.date():
        return f"{a:%H:%M}{EN_DASH}24:00"
    days = (b.date() - a.date()).days
    return f"{a:%H:%M}{EN_DASH}{b:%H:%M}" + (f"+{days}" if days else "")


def duration_text(seconds: int) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "< 1 min"
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"{minutes} min"
    return f"{hours} h" if not minutes else f"{hours} h {minutes} min"


def distance_text(metres: float) -> str:
    if metres < 1000:
        return f"{round(metres)} m"
    km = metres / 1000
    return f"{km:.1f} km" if km < 100 else f"{round(km)} km"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
