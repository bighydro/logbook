"""The Trip: one trip read back — `logbook trip <id-or-date> [--html PATH] [--json]`.

A trip is one of `trips`' runs of nights away from home, named by its derived id
(`trip:<first day>:<last day>`, the one `trips` prints at the end of each row) or by any day
inside it, the return day included. Its page is the readers composed over one reading of the
days around it: the **route** as the stays slept at, in night order, each with its nights — the
anchorage a night aboard was spent at, not the asset (the `trips` route folds a week aboard into
`aboard <asset>`; here every night's place is a stay, consecutive nights at one point folded, a
night in transit a stay of its own with no place) — and the **legs** between them with their
great-circle kilometres; the **days** from the leaving day to the return day, one line each as
`days` prints them (the Day of each, `day.of_reading`, summarised by `days.summarise`); the
**flights** in and out; the **people** confirmed present and, apart, the ones only proposed (a
tagged face, an all-day entry's attendee; never someone confirmed elsewhere on the trip); the
**nights aboard** each asset when a night was spent on one; the **keepers** per day (RFC 0024);
the **health** of the span (sleep, steps, resting heart rate, HRV: the `rollup health` rule over
the span as one period); and the **spend**, every `transaction/v1` line (RFC 0021) dated inside
the span, summed per currency, when the record holds any.

The reading is the trip's days with a margin either side, widened until the run of nights away is
seen whole (a trip that reaches the window's edge might go on), so a week is read from a month,
never from a year. Nothing is written, not even `policy/stays.json` (ADR 0013). The HTML page is
one file: inline CSS, no script, no asset, nothing fetched, and the map is an inline SVG drawn
from the stays' coordinates — an equirectangular projection about the route's mean latitude, one
path per leg, one mark per stay with its number, a scale bar — with no tiles, since a page that
reads the same in twenty years loads nothing."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
from itertools import pairwise
from typing import Any, NamedTuple

from . import day as day_reader
from . import days as days_reader
from . import health, keepers, present, reading, rollup, stays, trip_bundle, trips
from . import places as named_places
from .chain import Line
from .export import day_range, parse_day
from .flights import Airports
from .reading import Reading
from .store import Logbook
from .year import ARROW, CSS, DOT, EN_DASH, Cell, escape, footer, health_text, keepers_text, section, table

MARGIN_DAYS = 7  # the reading starts this many days before the trip and ends this many after …
WIDEN = 4  # … and widens by this factor while the run of nights away touches the window's edge
TRANSACTION = "transaction"
MINUS = "\u2212"
MAP_WIDTH = 640.0  # px, the page's; the viewBox is the same so the drawing scales with the page
MAP_MAX_HEIGHT = 640.0
MAP_MIN_HEIGHT = 240.0
MAP_MIN_SPAN = 0.05  # degrees; a route of one point is drawn at this scale
MAP_PAD = 0.12  # of the larger span, on every side
MARK_PX = 2.0  # stays drawn this close are one mark
KM_PER_DEGREE = 111.2  # of latitude; the projection's y axis
SCALE_STEPS = (0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)  # km, for the scale bar
DAYS_ID_WIDTH = 13


class Ref(NamedTuple):
    day: str  # the day the trip is looked for on: a date, or the id's first day
    id: str | None  # the id asked for, when one was


# -- the reading --------------------------------------------------------------------------------------------


def parse_ref(text: str) -> Ref:
    """`trip:YYYY-MM-DD:YYYY-MM-DD` or `YYYY-MM-DD`; `ValueError` for anything else, and for an id
    whose last day is before its first."""
    if text.startswith("trip:"):
        parts = text.split(":")
        if len(parts) == 3:
            try:
                start, end = parse_day(parts[1]), parse_day(parts[2])
            except ValueError:
                pass
            else:
                if end < start:
                    raise ValueError(f"a trip id runs forward: {text!r} ends before it starts")
                return Ref(start.isoformat(), f"trip:{start.isoformat()}:{end.isoformat()}")
    else:
        try:
            return Ref(parse_day(text).isoformat(), None)
        except ValueError:
            pass
    raise ValueError(f"not a trip id (trip:YYYY-MM-DD:YYYY-MM-DD) or a day (YYYY-MM-DD): {text!r}")


def locate(lb: Logbook, ref: Ref, airports: Airports | None = None) -> tuple[Reading, trips.Trip]:
    """The trip `ref` names and the reading it was found in: the days from `MARGIN_DAYS` before
    the trip to as many after, clipped to the days the owner's track covers, widened by `WIDEN`
    while the run touches an edge of the window that is not the record's. `ValueError` when the
    record has no days, the day is at home or outside the record, no stay places the owner
    anywhere around it, the id names no trip (the trip on its first day is named instead), or
    `places.json` names no home (the `trips` warning)."""
    whole = reading.record_days(lb, "location")
    if whole is None:
        raise ValueError("the record has no days")
    last = ref.id.split(":")[2] if ref.id else ref.day
    margin = MARGIN_DAYS
    while True:
        since = max(whole[0], (date.fromisoformat(ref.day) - timedelta(days=margin)).isoformat())
        until = min(whole[1], (date.fromisoformat(last) + timedelta(days=margin)).isoformat())
        if not since <= ref.day <= until:
            raise ValueError(f"no trip on {ref.day}: the record runs {whole[0]} {EN_DASH} {whole[1]}")
        rd = reading.read(lb, since, until, airports)
        found, warning = trips.trips(rd)
        if warning:
            raise ValueError(warning)
        whole_window = since == whole[0] and until == whole[1]
        trip = next((t for t in found if t.start <= ref.day <= t.until), None)
        if trip is None:
            night = rd.night_of(ref.day)
            if night is None or night.home:
                raise ValueError(f"no trip on {ref.day}: the night was at home")
            if whole_window:
                raise ValueError(f"no trip on {ref.day}: no stay places the owner anywhere around that night")
        elif (trip.start > since or since == whole[0]) and (trip.end < until or until == whole[1]):
            if ref.id is not None and trip.id != ref.id:
                raise ValueError(f"no trip {ref.id}: the trip on {ref.day} is {trip.id}")
            return rd, trip
        margin *= WIDEN


def read(lb: Logbook, text: str, airports: Airports | None = None) -> dict[str, Any]:
    """The Trip as one JSON-ready object. `ValueError` as `parse_ref` and `locate` raise it;
    `stays.SettingsError` when the record's settings, places or assets file is not what it should
    be. Nothing is written."""
    ref = parse_ref(text)
    airports = airports or Airports.load()
    rd, trip = locate(lb, ref, airports)
    span = day_range(trip.start, trip.until)
    before = (date.fromisoformat(trip.start) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        found = idx.by_kind(health.KIND, before, trip.until)
    health_rows = [
        row
        for row in health.summary([*found, *rd.retracted.values()], str(rd.tz))
        if trip.start <= str(row["day"]) <= trip.until
    ]
    health_of = {
        str(row["day"]): {k: v for k, v in row.items() if k not in ("day", "by")} for row in health_rows
    }
    usual = days_reader.usual_sources(lb, trip.start, trip.until)
    by_day = _lines_by_day(rd)
    days = []
    for day in span:
        lines = by_day.get(day, [])
        page = day_reader.of_reading(rd, day, health_of.get(day), lines)
        located = any(line.get("kind") == days_reader.LOCATION for line in lines)
        days.append(days_reader.summarise(page, usual, located))
    route = _route(trip, rd)
    visited = trips.visited_stays(rd, trip.start, trip.until)
    confirmed = trips.companions(visited, rd)
    return {
        "id": trip.id,
        "start": trip.start,
        "end": trip.end,
        "until": trip.until,
        "nights": trip.nights,
        "in_transit": trip.in_transit,
        "asset": trip.asset,
        "nights_aboard": [
            {"asset": asset, "name": trip.names.get(asset, asset), "nights": n}
            for asset, n in sorted(trip.nights_aboard.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "head": str(lb.meta.get("head") or ""),
        "window": {"since": rd.first, "until": rd.last},
        "warnings": [],
        "route": route,
        "legs": _legs(route),
        "places": list(trip.places),
        "days": days,
        "flights_in": trip.flights_in,
        "flights_out": trip.flights_out,
        "flights": list(trip.flights),
        "people": {
            "confirmed": [_person(c) for c in confirmed],
            "proposed": [_person(c) for c in trips.companions(visited, rd, present.PROPOSED)],
        },
        "shared": trip_bundle.shares(lb, rd, trip, route, confirmed),
        "keepers": _keepers(rd, span),
        "health": rollup.health_summary(health_rows),
        "spend": _spend(rd, trip.start, trip.until),
        "lines": list(trip.lines),
    }


def _lines_by_day(rd: Reading) -> dict[str, list[Line]]:
    """The reading's lines by local day, in chain order, so each day's are picked once."""
    found: dict[str, list[Line]] = {}
    for line in rd.lines:
        at = stays.instant(line.get("at"))
        if at is not None:
            found.setdefault(at.astimezone(rd.tz).date().isoformat(), []).append(line)
    return found


def _route(trip: trips.Trip, rd: Reading) -> list[dict[str, Any]]:
    """The stays slept at, in night order: a night's place is the stay the night was spent at
    (`Night.innermost`: the anchorage of a night aboard, else the stay), labelled as the Day labels
    it (the name; else the coordinates with the airport, the place near or the city); consecutive
    nights at one point (`_same_anchorage`) are one stay with their nights; a night in transit is
    a stay with no place, its nights counted the same way."""
    out: list[dict[str, Any]] = []
    last: stays.Segment | None = None
    for night in rd.nights:
        if not trip.start <= night.day <= trip.end:
            continue
        stay = night.innermost
        if stay is None:
            if out and out[-1]["in_transit"]:
                out[-1]["nights"] += 1
                out[-1]["last"] = night.day
            else:
                out.append(_stay_entry(night.day, None, None, rd))
            last = None
            continue
        if last is not None and not out[-1]["in_transit"] and _same_anchorage(last, stay):
            out[-1]["nights"] += 1
            out[-1]["last"] = night.day
        else:
            out.append(_stay_entry(night.day, stay, night.aboard, rd))
        last = stay
    return [{"n": n, **entry} for n, entry in enumerate(out, 1)]


def _stay_entry(day: str, stay: stays.Segment | None, aboard: str | None, rd: Reading) -> dict[str, Any]:
    if stay is None:
        return {
            "in_transit": True,
            "nights": 1,
            "first": day,
            "last": day,
            "label": "in transit",
            "place": None,
            "lat": None,
            "lon": None,
            "aboard": None,
            "asset": None,
            "stay": None,
        }
    if stay.place:
        label = stay.place
    elif stay.lat is not None and stay.lon is not None:
        label = trips.coordinates_label(stay.lat, stay.lon, rd.places, rd.airports)
    else:
        label = "unknown"
    return {
        "in_transit": False,
        "nights": 1,
        "first": day,
        "last": day,
        "label": label,
        "place": stay.place,
        "lat": None if stay.lat is None else round(stay.lat, 6),
        "lon": None if stay.lon is None else round(stay.lon, 6),
        "aboard": aboard,
        "asset": trips.asset_name(aboard, rd.assets) if aboard else None,
        "stay": stay.id,
    }


def _same_anchorage(a: stays.Segment, b: stays.Segment) -> bool:
    """One route point: the same named place, or within `trips.MERGE_M` of each other — never by
    the asset, since a week aboard is its anchorages here."""
    if a.place is not None or b.place is not None:
        return a.place == b.place
    if a.lat is None or a.lon is None or b.lat is None or b.lon is None:
        return False
    return named_places.distance_m(a.lat, a.lon, b.lat, b.lon) <= trips.MERGE_M


def _legs(route: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One leg between each pair of consecutive located stays, with its great-circle kilometres;
    `through_transit` when a night in transit lies between them."""
    located = [s for s in route if s["lat"] is not None]
    out = []
    for a, b in pairwise(located):
        km = named_places.distance_m(a["lat"], a["lon"], b["lat"], b["lon"]) / 1000
        out.append(
            {
                "from": a["n"],
                "to": b["n"],
                "km": round(km, 1),
                "through_transit": any(s["in_transit"] for s in route if a["n"] < s["n"] < b["n"]),
            }
        )
    return out


def _person(c: present.Companion) -> dict[str, Any]:
    return {
        "id": c.person,
        "name": c.name,
        "status": c.status,
        "confidence": c.confidence,
        "sources": list(c.sources),
        "lines": list(c.lines),
    }


def _keepers(rd: Reading, span: Sequence[str]) -> dict[str, Any]:
    """The keepers standing per day of the span, by lane, with the photos' names; days with none
    are left out."""
    days: dict[str, dict[str, Any]] = {}
    inside = set(span)
    for line in keepers.standing(rd.of_kind(keepers.KIND)):
        day = rd.day_of(line)
        if day not in inside:
            continue
        entry = days.setdefault(
            day, {"day": day, "count": 0, keepers.MEMORY: 0, keepers.ART: 0, "photos": []}
        )
        entry["count"] += 1
        lane = (line.get("payload") or {}).get("lane")
        if lane in keepers.LANES:
            entry[lane] += 1
        entry["photos"].append(keepers.name_of(line))
    found = [days[day] for day in sorted(days)]
    return {
        "count": sum(e["count"] for e in found),
        keepers.MEMORY: sum(e[keepers.MEMORY] for e in found),
        keepers.ART: sum(e[keepers.ART] for e in found),
        "days": found,
    }


def _spend(rd: Reading, start: str, until: str) -> dict[str, Any] | None:
    """Every `transaction/v1` line standing whose day (`date`, else the local day of `at`) is in
    [start, until], in day order, summed per currency; None when there is none. Amounts are
    signed from the owner's side (RFC 0021): a sum below zero is money spent."""
    found: list[dict[str, Any]] = []
    for line in rd.of_kind(TRANSACTION):
        payload = line.get("payload") or {}
        amount = payload.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            continue
        day = str(payload.get("date") or rd.day_of(line))
        if not start <= day <= until:
            continue
        found.append(
            {
                "date": day,
                "merchant": str(payload.get("merchant") or ""),
                "amount": amount,
                "currency": str(payload.get("currency") or "?"),
                "category": payload.get("category"),
                "provider": payload.get("provider"),
                "line": str(line["id"]),
            }
        )
    if not found:
        return None
    found.sort(key=lambda t: str(t["date"]))  # stable: chain order within a day
    sums: dict[str, dict[str, Any]] = {}
    for t in found:
        entry = sums.setdefault(str(t["currency"]), {"currency": t["currency"], "amount": 0, "count": 0})
        entry["amount"] += t["amount"]
        entry["count"] += 1
    for entry in sums.values():
        entry["amount"] = round(entry["amount"], 2)
    return {"by_currency": [sums[c] for c in sorted(sums)], "transactions": found}


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: Mapping[str, Any]) -> Iterator[str]:
    """The Trip as text: the header, the route, the flights, the people, the nights aboard, the
    days one line each, the keepers, the health, the spend."""
    yield f"{data['id']}  {head_text(data)}"
    for warning in data["warnings"]:
        yield f"  ({warning})"
    yield "  route"
    width = max(len(_dates(s)) for s in data["route"]) if data["route"] else 0
    for s in data["route"]:
        yield f"    {s['n']:>2}  {_dates(s):<{width}}  {_plural(s['nights'], 'night'):<9} {stay_text(s)}"
    if data["legs"]:
        yield _row("legs", DOT.join(leg_text(leg) for leg in data["legs"]))
    yield _row("flights", flights_text(data) or "none")
    yield _row("with", people_text(data["people"]))
    if data["nights_aboard"]:
        yield _row("aboard", aboard_text(data["nights_aboard"]))
    for share in data.get("shared") or []:
        yield from trip_bundle.rows(share)
    yield "  days"
    for r in data["days"]:
        yield f"    {days_reader.row(r)}"
    yield _row("keepers", keepers_text(data["keepers"]))
    for k in data["keepers"]["days"]:
        yield f"    {k['day']}  {keeper_day_text(k)}"
    yield _row("health", health_text(data["health"]))
    spend = data["spend"]
    if spend:
        yield _row("spend", spend_text(spend))
        width = max(len(t["merchant"]) for t in spend["transactions"])
        for t in spend["transactions"]:
            yield f"    {t['date']}  {t['merchant']:<{width}}  {transaction_text(t)}"


def _row(label: str, text: str) -> str:
    return f"  {label:<{DAYS_ID_WIDTH}} {text}"


def head_text(data: Mapping[str, Any]) -> str:
    """The dates, the nights (`6 nights aboard Nordlys` for an asset trip; a mixed trip counts its
    nights aboard in parentheses, as `trips` does) and the return day, `until 2026-06-21`."""
    nights = _plural(int(data["nights"]), "night")
    aside: list[str] = []
    if data["asset"]:
        aboard = next(
            (a["name"] for a in data["nights_aboard"] if a["asset"] == data["asset"]), data["asset"]
        )
        nights += f" aboard {aboard}"
    else:
        aside += [f"{a['nights']} aboard {a['name']}" for a in data["nights_aboard"]]
    if data["in_transit"]:
        aside.append(f"{data['in_transit']} in transit")
    if aside:
        nights += f" ({', '.join(aside)})"
    return f"{data['start']} {EN_DASH} {data['end']}{DOT}{nights}{DOT}until {data['until']}"


def _dates(s: Mapping[str, Any]) -> str:
    return s["first"] if s["first"] == s["last"] else f"{s['first']} {EN_DASH} {s['last']}"


def stay_text(s: Mapping[str, Any]) -> str:
    return f"{s['label']}{DOT}aboard {s['asset']}" if s["aboard"] else str(s["label"])


def leg_text(leg: Mapping[str, Any]) -> str:
    km = f"{leg['km']:,.0f} km" if leg["km"] >= 10 else f"{leg['km']:.1f} km"
    return f"{leg['from']} {ARROW} {leg['to']} {km}" + (
        " (in transit between)" if leg["through_transit"] else ""
    )


def flights_text(data: Mapping[str, Any]) -> str:
    parts = []
    for label in ("in", "out"):
        for f in data[f"flights_{label}"]:
            name = f"{f['carrier']} {f['number']} " if f["number"] else ""
            parts.append(f"{label} {name}{f['from'] or '?'} {ARROW} {f['to'] or '?'}")
    return DOT.join(parts)


def people_text(people: Mapping[str, Any]) -> str:
    parts = [", ".join(p["name"] for p in people["confirmed"]) or "nobody confirmed"]
    if people["proposed"]:
        parts.append("proposed " + ", ".join(p["name"] for p in people["proposed"]))
    return DOT.join(parts)


def aboard_text(found: Sequence[Mapping[str, Any]]) -> str:
    return DOT.join(f"{_plural(a['nights'], 'night')} aboard {a['name']}" for a in found)


def keeper_day_text(k: Mapping[str, Any]) -> str:
    lanes = ", ".join(f"{k[lane]} {lane}" for lane in keepers.LANES if k[lane])
    return f"{lanes or k['count']}  {', '.join(k['photos'])}"


def spend_text(spend: Mapping[str, Any]) -> str:
    return DOT.join(
        f"{money_text(e['amount'])} {e['currency']} ({_plural(e['count'], 'transaction')})"
        for e in spend["by_currency"]
    )


def transaction_text(t: Mapping[str, Any]) -> str:
    text = f"{money_text(t['amount'])} {t['currency']}"
    return f"{text}  {t['category']}" if t["category"] else text


def money_text(amount: float) -> str:
    """A minus sign (U+2212, never a hyphen) for money that left, a plus for money that came, whole
    when the amount is whole and two decimals otherwise: 119 spent reads as minus 119, 94.5 as
    minus 94.50, 1200 received as +1,200."""
    sign = MINUS if amount < 0 else "+" if amount > 0 else ""
    value = abs(amount)
    return f"{sign}{value:,.0f}" if float(value).is_integer() else f"{sign}{value:,.2f}"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


# -- the page -----------------------------------------------------------------------------------------------

MAP_CSS = """
figure.map { margin: .5rem 0 1rem; }
svg.map { display: block; width: 100%; max-width: 40rem; height: auto; background: #f5f5f1;
  border: 1px solid #c9c9c4; border-radius: 4px; }
.leg { fill: none; stroke: #1b1b1b; stroke-width: 2; stroke-linecap: round; }
.leg.transit { stroke-dasharray: 6 5; }
.stay { fill: #fff; stroke: #1b1b1b; stroke-width: 1.5; }
.mark { font: 600 11px -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; fill: #1b1b1b; }
.scale { stroke: #1b1b1b; stroke-width: 1.5; }
.scale-text { font: 10px -apple-system, "Segoe UI", Helvetica, Arial, sans-serif; fill: #666; }
ul.people { margin: .25rem 0; padding-left: 1.2rem; }
@media print { svg.map { background: none; } }
"""


def html(data: Mapping[str, Any]) -> str:
    """The Trip as one self-contained HTML page: inline CSS, no script, no asset, nothing fetched,
    the map an inline SVG; everything the record says is escaped. Suitable for printing."""
    title = f"{data['start']} {EN_DASH} {data['end']}"
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)} · Logbook</title>",
        f"<style>{CSS}{MAP_CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<h1>{escape(title)}</h1>",
        f"<p>{escape(data['id'])}{DOT}{escape(head_text(data))}</p>",
    ]
    for warning in data["warnings"]:
        out.append(f'<p class="muted">{escape(warning)}</p>')
    out.append("</header>")
    out += section("route", "Route", _route_html(data["route"], data["legs"]))
    out += section("flights", "Flights", _flights_html(data))
    out += section("people", "People", _people_html(data["people"]))
    if data["nights_aboard"]:
        out += section("aboard", "Nights aboard", [f"<p>{escape(aboard_text(data['nights_aboard']))}</p>"])
    if data.get("shared"):
        out += section("shared", "Shared", _shared_html(data["shared"]))
    out += section("days", "Days", _days_html(data["days"]))
    out += section("keepers", "Keepers", _keepers_html(data["keepers"]))
    out += section("health", "Health", _health_html(data["health"]))
    if data["spend"]:
        out += section("spend", "Spend", _spend_html(data["spend"]))
    out += footer(data)
    out += ["</body>", "</html>"]
    return "\n".join(out) + "\n"


def _route_html(route: Sequence[Mapping[str, Any]], legs: Sequence[Mapping[str, Any]]) -> list[str]:
    if not route:
        return ['<p class="muted">No nights.</p>']
    out = [map_svg(route, legs)]
    rows_: list[list[Cell]] = [
        [
            (str(s["n"]), "n"),
            (_dates(s), "d"),
            (f"{s['nights']:,}", "n"),
            (str(s["label"]), ""),
            (s["asset"] or "", ""),
        ]
        for s in route
    ]
    out += table([("#", "n"), ("nights of", ""), ("nights", "n"), ("where", ""), ("aboard", "")], rows_)
    if legs:
        out.append(f"<p>Legs: {escape(DOT.join(leg_text(leg) for leg in legs))}</p>")
    return out


def map_svg(route: Sequence[Mapping[str, Any]], legs: Sequence[Mapping[str, Any]]) -> str:
    """The route as one inline SVG: an equirectangular projection about the route's mean latitude
    (x the longitude scaled by its cosine, y the latitude; straight lines, no tiles), one `path`
    per leg (dashed when a night in transit lies between), one `circle` per distinct point with the numbers of
    the stays at it beside it (`_marks`), and a scale bar in whole kilometres. A single point is drawn at
    `MAP_MIN_SPAN` degrees across."""
    located = [s for s in route if s["lat"] is not None and s["lon"] is not None]
    if not located:
        return '<p class="muted">No coordinates to draw.</p>'
    k = math.cos(math.radians(sum(s["lat"] for s in located) / len(located)))
    xs = [s["lon"] * k for s in located]
    ys = [-s["lat"] for s in located]
    span = max(max(xs) - min(xs), max(ys) - min(ys), MAP_MIN_SPAN)
    pad = MAP_PAD * span
    ext_x = max(max(xs) - min(xs), MAP_MIN_SPAN) + 2 * pad
    ext_y = max(max(ys) - min(ys), MAP_MIN_SPAN) + 2 * pad
    scale = min(MAP_WIDTH / ext_x, MAP_MAX_HEIGHT / ext_y)  # px per degree
    width = MAP_WIDTH
    height = max(MAP_MIN_HEIGHT, ext_y * scale)
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    def px(s: Mapping[str, Any]) -> tuple[float, float]:
        return ((s["lon"] * k - cx) * scale + width / 2, (-s["lat"] - cy) * scale + height / 2)

    at = {s["n"]: px(s) for s in located}
    out = [
        '<figure class="map">',
        f'<svg class="map" viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-label="the route">',
    ]
    for leg in legs:
        (x1, y1), (x2, y2) = at[leg["from"]], at[leg["to"]]
        cls = "leg transit" if leg["through_transit"] else "leg"
        out.append(f'<path class="{cls}" d="M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}"/>')
    for group in _marks(located, at):
        x, y = at[group[0]["n"]]
        r = 4 + min(sum(int(s["nights"]) for s in group), 6)
        label = ", ".join(str(s["n"]) for s in group)
        out.append(f'<circle class="stay" cx="{x:.1f}" cy="{y:.1f}" r="{r}"/>')
        out.append(f'<text class="mark" x="{x + r + 3:.1f}" y="{y + 4:.1f}">{label}</text>')
    km_per_px = KM_PER_DEGREE / scale
    target = width / 5 * km_per_px
    bar_km = max((step for step in SCALE_STEPS if step <= target), default=SCALE_STEPS[0])
    bar = bar_km / km_per_px
    x0, y0 = 16.0, height - 16
    out.append(f'<path class="scale" d="M {x0:.1f} {y0:.1f} L {x0 + bar:.1f} {y0:.1f}"/>')
    out.append(f'<text class="scale-text" x="{x0:.1f}" y="{y0 - 5:.1f}">{bar_km:g} km</text>')
    out += ["</svg>", "</figure>"]
    return "\n".join(out)


def _marks(
    located: Sequence[Mapping[str, Any]], at: Mapping[int, tuple[float, float]]
) -> list[list[Mapping[str, Any]]]:
    """The stays grouped by the point they draw at (within `MARK_PX`): a bay slept in twice, on
    the way out and the way back, is one mark labelled `1, 4`, never two marks on top of each
    other."""
    groups: list[list[Mapping[str, Any]]] = []
    for s in located:
        x, y = at[s["n"]]
        for group in groups:
            gx, gy = at[group[0]["n"]]
            if abs(gx - x) <= MARK_PX and abs(gy - y) <= MARK_PX:
                group.append(s)
                break
        else:
            groups.append([s])
    return groups


def _flights_html(data: Mapping[str, Any]) -> list[str]:
    found = [("in", f) for f in data["flights_in"]] + [("out", f) for f in data["flights_out"]]
    if not found:
        return ['<p class="muted">No flights.</p>']
    rows_: list[list[Cell]] = [
        [
            (label, ""),
            (f["date"], "d"),
            (f"{f['carrier']} {f['number']}" if f["number"] else "", "d"),
            (f"{f['from'] or '?'} {ARROW} {f['to'] or '?'}", "d"),
            (str(f["evidence"] or ""), ""),
        ]
        for label, f in found
    ]
    return table([("", ""), ("date", ""), ("flight", ""), ("route", ""), ("evidence", "")], rows_)


def _people_html(people: Mapping[str, Any]) -> list[str]:
    out = []
    for status, label in ((present.CONFIRMED, "Confirmed"), (present.PROPOSED, "Proposed")):
        found = people[status]
        if not found:
            if status == present.CONFIRMED:
                out.append('<p class="muted">Nobody confirmed.</p>')
            continue
        out.append(f"<h3>{label}</h3>")
        out.append('<ul class="people">')
        for p in found:
            sources = escape(", ".join(p["sources"]))
            out.append(f'<li>{escape(p["name"])} <span class="muted">({sources})</span></li>')
        out.append("</ul>")
    return out


def _shared_html(shared: Sequence[Mapping[str, Any]]) -> list[str]:
    """Per sender: who was there according to each record and the places the records agree on,
    each with a `seen only by` column (RFC 0025)."""
    out = []
    for share in shared:
        their = share["trip"]
        out.append(f"<h3>with {escape(share['from']['name'])}</h3>")
        head = DOT.join(
            [
                f"their {their.get('id')}",
                _plural(int(their.get("nights") or 0), "night"),
                f"received {str(share.get('received_at') or '')[:10]}".rstrip(),
                _plural(int(share["photos"]), "photo"),
            ]
        )
        out.append(f'<p class="muted">{escape(head)}</p>')
        people: list[list[Cell]] = [
            [
                (p["name"], ""),
                (p["yours"] or EN_DASH, ""),
                (p["theirs"] or EN_DASH, ""),
                (p["seen_only_by"] or "", ""),
            ]
            for p in share["people"]
        ]
        out += table([("who", ""), ("yours", ""), ("theirs", ""), ("seen only by", "")], people)
        if share["places"]:
            places: list[list[Cell]] = [
                [
                    (trip_bundle._place_text(p["label"], p["nights"]), ""),
                    (trip_bundle._place_text(p["theirs"], p["their_nights"]), ""),
                    (p["seen_only_by"] or "", ""),
                ]
                for p in share["places"]
            ]
            out += table([("where", ""), ("theirs", ""), ("seen only by", "")], places)
    return out


def _days_html(days: Sequence[Mapping[str, Any]]) -> list[str]:
    rows_: list[list[Cell]] = []
    for r in days:
        parts = [stays_or_nothing(r)]
        if r["people"]["confirmed"]:
            parts.append("with " + ", ".join(r["people"]["names"]))
        rows_.append(
            [
                (r["day"], "d"),
                (r["weekday"][:3], ""),
                (days_reader.night_text(r), ""),
                (days_reader.km_text(r["moved_m"]), "n"),
                ([days_reader.flight_text(f) for f in r["flights"]], ""),
                (DOT.join(parts), ""),
                (day_reader.health_text(r["health"]) if r["health"] is not None else "", ""),
                (", ".join(r["gaps"]), ""),
            ]
        )
    heads = [
        ("day", ""),
        ("", ""),
        ("night", ""),
        ("moved", "n"),
        ("flights", ""),
        ("stays", ""),
        ("health", ""),
        ("gaps", ""),
    ]
    return table(heads, rows_)


def stays_or_nothing(r: Mapping[str, Any]) -> str:
    return days_reader.stays_text(r["stays"]) if r["sources"] else "nothing logged"


def _keepers_html(found: Mapping[str, Any]) -> list[str]:
    if not found["count"]:
        return ['<p class="muted">No keepers.</p>']
    rows_: list[list[Cell]] = [
        [
            (k["day"], "d"),
            (f"{k['count']:,}", "n"),
            (f"{k['memory']:,}", "n"),
            (f"{k['art']:,}", "n"),
            (k["photos"], ""),
        ]
        for k in found["days"]
    ]
    return table([("day", ""), ("keepers", "n"), ("memory", "n"), ("art", "n"), ("photos", "")], rows_)


def _health_html(h: Mapping[str, Any]) -> list[str]:
    sleep, steps, resting, hrv = (h[k] for k in ("sleep", "steps", "resting_hr", "hrv"))
    if all(v is None for v in (sleep, steps, resting, hrv)):
        return ['<p class="muted">No health lines.</p>']
    rows_: list[list[Cell]] = [
        [
            ("sleep", ""),
            (
                "" if sleep is None else f"{sleep['mean_h']:.1f} h",
                "n",
            ),
            ("" if sleep is None else _plural(sleep["nights"], "night"), ""),
        ],
        [
            ("steps", ""),
            ("" if steps is None else f"{steps['mean']:,}", "n"),
            ("" if steps is None else _plural(steps["days"], "day"), ""),
        ],
        [
            ("resting heart rate", ""),
            (
                ""
                if resting is None
                else f"{resting['mean']} bpm ({resting['min']}{EN_DASH}{resting['max']})",
                "n",
            ),
            ("" if resting is None else _plural(resting["days"], "day"), ""),
        ],
        [
            ("hrv", ""),
            ("" if hrv is None else f"{hrv['mean_ms']} ms", "n"),
            ("" if hrv is None else _plural(hrv["days"], "day"), ""),
        ],
    ]
    out = table([("", ""), ("mean", "n"), ("over", "")], [row for row in rows_ if row[1][0]])
    out.append('<p class="muted">Means over the nights and days of the span with a line.</p>')
    return out


def _spend_html(spend: Mapping[str, Any]) -> list[str]:
    out = [f"<p>{escape(spend_text(spend))}</p>"]
    rows_: list[list[Cell]] = [
        [
            (t["date"], "d"),
            (t["merchant"], ""),
            (f"{money_text(t['amount'])} {t['currency']}", "n"),
            (str(t["category"] or ""), ""),
            (str(t["provider"] or ""), ""),
        ]
        for t in spend["transactions"]
    ]
    out += table([("date", ""), ("merchant", ""), ("amount", "n"), ("category", ""), ("provider", "")], rows_)
    return out
