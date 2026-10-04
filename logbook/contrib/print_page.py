"""The paper edition: `logbook year YYYY --html PATH --print` and `logbook trip ID --html PATH
--print` write one HTML document designed for paper, A4 and US Letter, laid out with CSS paged
media — a cover (the owner's name, the year or the trip, the dates), a contents page, then one
spread per month of the year or per day of the trip: a facts page (the nights, the places by
nights numbered to the map, who was there — confirmed only, never a proposal — the flights, the
sleep and the steps when the record has them, the keepers) with the track of the span drawn as an
inline SVG from the location lines themselves, no tiles, nothing fetched; then, when the span has
keepers (RFC 0024), a page of them as hero photos sized to the page. A day or a month with no
photos has its facts page and no photo page, and lays out the same. Page numbers come from the
page counter; the cover has none.

The document is one file with one inline stylesheet (`print_layout.stylesheet()`, where every
typographic constant lives), no script, no link, no font, nothing loaded from anywhere. The
photos are referenced, never copied: an `img` points at the photo's attachment when the record
stores the pixels (a SPEC §1.1 reference under `content` or `attachment`), else at the original
path the library wrote in the line (`path` or `original_path`, at the payload's top or under
`extra`), and a photo the record only names gets a frame with its name, so the page lays out
whether or not the file is there. Everything the record says is escaped.

The Year is read once (`reading.read` of the window `year.window` gives) and each month's facts
are counted from the reading's nights, stays, flights and keepers, the health rows from the
index; no pick is read. The Trip is `trip_page.read` (the route and the legs for the contents
page) and the reading `trip_page.locate` returns, each day of it built with the day reader
(`day.of_reading`), the same Day `logbook day` prints. Nothing is written, not even
`policy/stays.json` (ADR 0013); the same record gives the same document."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..core import day as day_reader
from ..core import health, keepers, policy, reading, rollup, stays, trips
from ..core import places as named_places
from ..core import year as year_reader
from ..core.chain import Line
from ..core.export import day_range
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.store import Logbook
from ..core.year import ARROW, DOT, EN_DASH, MONTHS, escape
from . import print_layout as layout
from . import trip_page

YEAR, TRIP = "year", "trip"


class Markup(str):
    """HTML already built and escaped (a places list); every other string is escaped on the way in."""


LOCATION = "location"
PHOTO = "photo"
MAX_TRACK_POINTS = 1500  # a span's track is thinned to this many points before it is drawn
MAP_MIN_SPAN = 0.02  # degrees; a track of one point is drawn at this scale
MAP_PAD = 0.1  # of the larger span, on every side
MARK_PX = 3.0  # places drawn this close are one mark
KM_PER_DEGREE = 111.2
SCALE_STEPS = (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000)  # km, the scale bar
ATTACHMENT_KEYS = ("content", "attachment")  # a §1.1 reference the photo line may carry
PATH_KEYS = ("path", "original_path")  # the library's own path, at the top or under `extra`


# -- the reading --------------------------------------------------------------------------------------------


def read_year(lb: Logbook, year: str, airports: Airports | None = None) -> dict[str, Any]:
    """The Year's paper edition as one JSON-ready object: the owner's name, the window, the trips
    for the contents page, and a month entry for every month of the window with its facts, its
    keepers and its track. `ValueError` for a year that is not one; `stays.SettingsError` when
    the record's settings, places or assets file is not what it should be."""
    year = year_reader.parse_year(year)
    head = str(lb.meta.get("head") or "")
    span = year_reader.window(lb, year)
    if span is None:
        return {
            "kind": YEAR,
            "year": year,
            "name": owner_name(lb, None),
            "head": head,
            "window": None,
            "warnings": [],
            "trips": [],
            "months": [],
        }
    first, last = span
    airports = airports or Airports.load()
    rd = reading.read(lb, first, last, airports)
    before = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        found = idx.by_kind(health.KIND, before, last)
        marks = idx.retractions()
    periods = rollup.health([*found, *marks], str(rd.tz), first, last, "month")["periods"]
    health_of = {str(p["period"]): p for p in periods}
    flights: list[dict[str, Any]] = next(
        (y["flights"] for y in rollup.flights(rd)["years"] if y["year"] == year), []
    )
    found_trips, warning = trips.trips(rd)
    kept = keepers_by_day(rd, lb.root)
    track = points_by_day(rd)
    months = []
    for m in range(1, 13):
        key = f"{year}-{m:02d}"
        days = [d for d in rd.days if d.startswith(key)]
        if days:
            months.append(_month(rd, key, days, flights, health_of.get(key), kept, track))
    return {
        "kind": YEAR,
        "year": year,
        "name": owner_name(lb, rd),
        "head": head,
        "window": {"since": first, "until": last, "days": len(rd.days)},
        "warnings": [warning] if warning else [],
        "trips": [_trip_row(t, rd) for t in found_trips],
        "months": months,
    }


def read_trip(lb: Logbook, text: str, airports: Airports | None = None) -> dict[str, Any]:
    """The Trip's paper edition as one JSON-ready object: what `trip_page.read` gives for the
    cover and the contents (the id, the dates, the nights, the route and the legs, the flights in
    and out, the people confirmed), and a day entry for every day from the leaving day to the
    return day with its facts, its keepers and its track. `ValueError` and `stays.SettingsError`
    as `trip_page.read` raises them."""
    ref = trip_page.parse_ref(text)
    airports = airports or Airports.load()
    rd, trip = trip_page.locate(lb, ref, airports)
    data = trip_page.read(lb, text, airports)
    span = day_range(trip.start, trip.until)
    before = (date.fromisoformat(trip.start) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        found = idx.by_kind(health.KIND, before, trip.until)
    health_of = day_reader.health_rows(found, rd)
    by_day = _lines_by_day(rd)
    kept = keepers_by_day(rd, lb.root)
    track = points_by_day(rd)
    days = []
    for n, day in enumerate(span, 1):
        page = day_reader.of_reading(rd, day, health_of.get(day), by_day.get(day, []))
        days.append(_day(page, n, len(span), kept.get(day, []), track.get(day, [])))
    return {
        "kind": TRIP,
        "id": data["id"],
        "start": data["start"],
        "end": data["end"],
        "until": data["until"],
        "nights": data["nights"],
        "head_text": trip_page.head_text(data),
        "name": owner_name(lb, rd),
        "head": data["head"],
        "warnings": list(data["warnings"]),
        "route": data["route"],
        "legs": data["legs"],
        "places": data["places"],
        "flights_in": data["flights_in"],
        "flights_out": data["flights_out"],
        "people": [p["name"] for p in data["people"]["confirmed"]],
        "days": days,
    }


def owner_name(lb: Logbook, rd: Reading | None) -> str:
    """How the cover names the owner: the first name `policy/owner.json` lists, else the label a
    resolution line gives one of the owner's refs, else the first owner email of `logbook.json`,
    else `the captain`. Nothing is guessed from an address."""
    aliases = policy.owner_aliases(lb.root)
    for name in aliases.get("names", []):
        if name.strip():
            return name.strip()
    if rd is not None:
        for ref in sorted(rd.owner.refs):
            who = rd.identities.get(ref)
            if who is not None and who.label:
                return str(who.label)
    emails = lb.meta.get("owner_emails") or []
    for email in emails:
        if isinstance(email, str) and email.strip():
            return email.strip()
    return "the captain"


def _lines_by_day(rd: Reading) -> dict[str, list[Line]]:
    found: dict[str, list[Line]] = {}
    for line in rd.lines:
        at = stays.instant(line.get("at"))
        if at is not None:
            found.setdefault(at.astimezone(rd.tz).date().isoformat(), []).append(line)
    return found


def points_by_day(rd: Reading) -> dict[str, list[tuple[float, float]]]:
    """The track a map is drawn from, as (lat, lon) per local day in time order: the owner's
    location lines (no `subject`) and, while the owner was aboard an asset (the folded stays
    aboard, ADR 0018), the asset's own lines inside that stay, since the boat's track is where
    the owner went."""
    aboard = [(str(s.aboard), s.start, s.end) for s in rd.derived.folded if s.aboard]
    found: dict[str, list[tuple[str, float, float]]] = {}
    for line in rd.of_kind(LOCATION):
        payload = line.get("payload") or {}
        subject = payload.get("subject")
        if subject:
            at = stays.instant(line.get("at"))
            if at is None or not any(a == subject and start <= at <= end for a, start, end in aboard):
                continue
        lat, lon = _coordinate(payload.get("lat")), _coordinate(payload.get("lon"))
        if lat is not None and lon is not None:
            found.setdefault(rd.day_of(line), []).append((str(line["at"]), lat, lon))
    return {day: [(lat, lon) for _at, lat, lon in sorted(points)] for day, points in found.items()}


def _coordinate(value: object) -> float | None:
    """A finite number as a float; None for anything else (a reader skips it)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def keepers_by_day(rd: Reading, root: Path) -> dict[str, list[dict[str, Any]]]:
    """The keepers standing per local day, memory first then by time, each with the photo line it
    points at and where its pixels are (`photo_source`)."""
    photos = {str(line["id"]): line for line in rd.of_kind(PHOTO)}
    found: dict[str, list[dict[str, Any]]] = {}
    for line in keepers.standing(rd.of_kind(keepers.KIND)):
        payload = line.get("payload") or {}
        ref = payload.get("photo")
        photo = photos.get(str(ref.get("line"))) if isinstance(ref, dict) else None
        lane = str(payload.get("lane") or "")
        photo_payload = (photo.get("payload") or {}) if photo is not None else {}
        lat, lon = _coordinate(photo_payload.get("lat")), _coordinate(photo_payload.get("lon"))
        found.setdefault(rd.day_of(line), []).append(
            {
                "day": rd.day_of(line),
                "at": str(line["at"]),
                "lane": lane,
                "name": keepers.name_of(line),
                "line": str(line["id"]),
                "photo": None if photo is None else str(photo["id"]),
                "src": photo_source(photo, root),
                "lat": lat,
                "lon": lon,
            }
        )
    order = {lane: n for n, lane in enumerate(keepers.LANES)}
    for day in found:
        found[day].sort(key=lambda k: (order.get(k["lane"], len(order)), k["at"], k["line"]))
    return found


def photo_source(photo: Line | None, root: Path) -> str | None:
    """Where a photo's pixels are, never copied: the attachment's path when the record stores
    them (a SPEC §1.1 reference under `content` or `attachment`), as a file URL under the record's
    root; else the original path the library wrote in the line (`path` or `original_path`, at the
    payload's top or under `extra`) — a file URL when it is absolute, as written when it is not;
    None when the line only names the photo."""
    if photo is None:
        return None
    payload = photo.get("payload") or {}
    extra = payload.get("extra")
    for key in ATTACHMENT_KEYS:
        ref = payload.get(key)
        if isinstance(ref, dict) and isinstance(ref.get("path"), str) and str(ref["path"]).strip():
            return (Path(root).resolve() / str(ref["path"]).strip()).as_uri()
    for holder in (payload, extra if isinstance(extra, dict) else {}):
        for key in PATH_KEYS:
            value = holder.get(key)
            if isinstance(value, str) and value.strip():
                text = str(value).strip()
                found = Path(text)
                return found.as_uri() if found.is_absolute() else text
    return None


# -- a month ------------------------------------------------------------------------------------------------


def _month(
    rd: Reading,
    key: str,
    days: Sequence[str],
    flights: Sequence[Mapping[str, Any]],
    health_row: Mapping[str, Any] | None,
    kept: Mapping[str, Sequence[Mapping[str, Any]]],
    track: Mapping[str, Sequence[tuple[float, float]]],
) -> dict[str, Any]:
    inside = set(days)
    nights = [n for n in rd.nights if n.day in inside]
    home = sum(1 for n in nights if n.stay is not None and n.home)
    in_transit = sum(1 for n in nights if n.stay is None)
    aboard = Counter(str(n.aboard) for n in nights if n.aboard)
    places = _places_by_nights(nights, rd)
    people = [c.name for c in trips.companions(trips.visited_stays(rd, days[0], days[-1]), rd)]
    sleep = steps = None
    if health_row is not None:
        if health_row.get("sleep"):
            sleep = {"mean_h": health_row["sleep"]["mean_h"], "nights": health_row["sleep"]["nights"]}
        if health_row.get("steps"):
            steps = {"mean": health_row["steps"]["mean"], "days": health_row["steps"]["days"]}
    keepers_ = [dict(k) for day in days for k in kept.get(day, [])]
    points = [p for day in days for p in track.get(day, [])]
    return {
        "month": key,
        "name": MONTHS[int(key[5:7]) - 1],
        "first": days[0],
        "last": days[-1],
        "days": len(days),
        "nights": {
            "home": home,
            "away": len(nights) - home - in_transit,
            "in_transit": in_transit,
            "aboard": [
                {"asset": asset, "name": trips.asset_name(asset, rd.assets), "nights": n}
                for asset, n in sorted(aboard.items(), key=lambda kv: (-kv[1], kv[0]))
            ],
        },
        "places": places,
        "people": people,
        "flights": [
            {k: f[k] for k in ("date", "carrier", "number", "from", "to", "km")}
            for f in flights
            if str(f["date"]).startswith(key)
        ],
        "health": None if sleep is None and steps is None else {"sleep": sleep, "steps": steps},
        "keepers": keepers_,
        "map": map_svg(points, places, f"{_span_text(days[0], days[-1])}: the track, the places by nights"),
    }


def _places_by_nights(nights: Sequence[stays.Night], rd: Reading) -> list[dict[str, Any]]:
    """The places the nights were spent at, most nights first then first slept at, numbered for
    the map: the stay's name; a night at home by the home place it lies by; aboard an asset the
    anchorage with the asset's name; else the coordinates as the trips' route reads them."""
    found: dict[str, dict[str, Any]] = {}
    for n in nights:
        stay = n.innermost
        if stay is None:
            continue
        label = _stay_label(stay, n.home, rd)
        if n.aboard:
            label = f"{label}{DOT}aboard {trips.asset_name(n.aboard, rd.assets)}"
        position = n.position
        entry = found.setdefault(
            label,
            {
                "label": label,
                "nights": 0,
                "first": n.day,
                "lat": None if position is None else round(position[0], 6),
                "lon": None if position is None else round(position[1], 6),
            },
        )
        entry["nights"] += 1
    ordered = sorted(found.values(), key=lambda e: (-int(e["nights"]), str(e["first"])))
    return [{"n": n, **entry} for n, entry in enumerate(ordered, 1)]


def _stay_label(stay: stays.Segment, home: bool, rd: Reading) -> str:
    if stay.place:
        return str(stay.place)
    if stay.lat is None or stay.lon is None:
        return "unknown"
    if home:
        near = named_places.nearest(stay.lat, stay.lon, [p for p in rd.places if p.kind == named_places.HOME])
        if near is not None:
            return near[0].name
    return trips.coordinates_label(stay.lat, stay.lon, rd.places, rd.airports)


def _trip_row(trip: trips.Trip, rd: Reading) -> dict[str, Any]:
    nights = _plural(trip.nights, "night")
    if trip.asset:
        nights += f" aboard {trips.asset_name(trip.asset, rd.assets)}"
    return {
        "id": trip.id,
        "start": trip.start,
        "end": trip.end,
        "until": trip.until,
        "nights": nights,
        "route": list(trip.route),
        "places": list(trip.places),
        "people": [c.name for c in trip.people],
    }


# -- a day --------------------------------------------------------------------------------------------------


def _day(
    page: Mapping[str, Any],
    n: int,
    of: int,
    kept: Sequence[Mapping[str, Any]],
    points: Sequence[tuple[float, float]],
) -> dict[str, Any]:
    """One day of a trip from its Day: the nights either side as the Day prints them, the stays
    as places numbered for the map, the people confirmed across the day, the flights, the sleep
    and the steps when the day's health row has them."""
    places: list[dict[str, Any]] = []
    people: dict[str, str] = {}

    def place(label: str, lat: float | None, lon: float | None) -> None:
        if all(p["label"] != label for p in places):
            places.append({"n": len(places) + 1, "label": label, "lat": lat, "lon": lon})

    for entry in page["timeline"]:
        if entry["kind"] == stays.STAY:
            place(str(entry["where"] or "unknown"), entry["lat"], entry["lon"])
        elif entry["kind"] == day_reader.ABOARD:
            inside = [e for e in entry["inside"] if e["kind"] == stays.STAY]
            if inside:  # the anchorages are the places, each named with the asset
                for e in inside:
                    place(f"{e['where']}{DOT}{entry['where']}", e["lat"], e["lon"])
            else:  # a run aboard with no stay inside it: the run itself, at its centre
                place(str(entry["where"]), entry["lat"], entry["lon"])
        for c in (entry.get("with") or {}).get("confirmed", []):
            people.setdefault(str(c.get("person") or c.get("name")), str(c["name"]))
    row = page["health"]
    sleep_h = None if row is None else row.get("sleep_h")
    steps = None if row is None else row.get("steps")
    day = str(page["day"])
    return {
        "day": day,
        "n": n,
        "of": of,
        "weekday": page["weekday"],
        "nights": {
            "before": day_reader.night_text(page["nights"]["before"]),
            "after": day_reader.night_text(page["nights"]["after"]),
        },
        "country": page["country"]["code"],
        "places": places,
        "people": list(people.values()),
        "flights": [{k: f[k] for k in ("carrier", "number", "from", "to")} for f in page["flights"]],
        "health": None if sleep_h is None and steps is None else {"sleep_h": sleep_h, "steps": steps},
        "keepers": [dict(k) for k in kept],
        "map": map_svg(points, places, f"{_long_date(day)}: the track, the stays"),
    }


# -- the map ------------------------------------------------------------------------------------------------


def map_svg(points: Sequence[tuple[float, float]], marks: Sequence[Mapping[str, Any]], caption: str) -> str:
    """The span's track as one inline SVG figure: an equirectangular projection about the mean
    latitude of everything drawn (x the longitude scaled by its cosine, y the latitude; straight
    lines, no tiles), the owner's points thinned to `MAX_TRACK_POINTS` as one `path`, one `circle`
    per distinct place with the numbers of the places at it, a scale bar in kilometres. With no
    point and no placed mark the figure says so and keeps its height."""
    located = [m for m in marks if m.get("lat") is not None and m.get("lon") is not None]
    if not points and not located:
        return "\n".join(
            [
                '<figure class="map empty">',
                '<div class="none">No location lines.</div>',
                f"<figcaption>{escape(caption)}</figcaption>",
                "</figure>",
            ]
        )
    thinned = _thin(points)
    everything = [*thinned, *((float(m["lat"]), float(m["lon"])) for m in located)]
    k = math.cos(math.radians(sum(lat for lat, _lon in everything) / len(everything)))
    xs = [lon * k for _lat, lon in everything]
    ys = [-lat for lat, _lon in everything]
    width, height = layout.MAP_VIEW_PX
    span_x = max(max(xs) - min(xs), MAP_MIN_SPAN)
    span_y = max(max(ys) - min(ys), MAP_MIN_SPAN)
    pad = MAP_PAD * max(span_x, span_y)
    scale = min(width / (span_x + 2 * pad), height / (span_y + 2 * pad))  # px per degree
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2

    def px(lat: float, lon: float) -> tuple[float, float]:
        return ((lon * k - cx) * scale + width / 2, (-lat - cy) * scale + height / 2)

    out = [
        '<figure class="map">',
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{escape(caption)}">',
    ]
    if thinned:
        d = " L ".join(f"{x:.1f} {y:.1f}" for x, y in (px(lat, lon) for lat, lon in thinned))
        out.append(f'<path class="track" d="M {d}"/>')
    at = {int(m["n"]): px(float(m["lat"]), float(m["lon"])) for m in located}
    for group in _marks(located, at):
        x, y = at[int(group[0]["n"])]
        label = ", ".join(str(m["n"]) for m in group)
        out.append(f'<circle class="stay" cx="{x:.1f}" cy="{y:.1f}" r="5"/>')
        out.append(f'<text class="mark" x="{x + 8:.1f}" y="{y + 4:.1f}">{escape(label)}</text>')
    km_per_px = KM_PER_DEGREE / scale
    target = width / 5 * km_per_px
    bar_km = max((step for step in SCALE_STEPS if step <= target), default=SCALE_STEPS[0])
    bar = bar_km / km_per_px
    x0, y0 = 16.0, height - 16
    out.append(f'<path class="scale" d="M {x0:.1f} {y0:.1f} L {x0 + bar:.1f} {y0:.1f}"/>')
    out.append(f'<text class="scale-text" x="{x0:.1f}" y="{y0 - 5:.1f}">{bar_km:g} km</text>')
    out += ["</svg>", f"<figcaption>{escape(caption)}</figcaption>", "</figure>"]
    return "\n".join(out)


def _thin(points: Sequence[tuple[float, float]]) -> list[tuple[float, float]]:
    """Every `stride`th point, the last always kept, so a month of one fix a minute is a path a
    page can hold."""
    if len(points) <= MAX_TRACK_POINTS:
        return list(points)
    stride = math.ceil(len(points) / MAX_TRACK_POINTS)
    kept = list(points[::stride])
    if kept[-1] != points[-1]:
        kept.append(points[-1])
    return kept


def _marks(
    located: Sequence[Mapping[str, Any]], at: Mapping[int, tuple[float, float]]
) -> list[list[Mapping[str, Any]]]:
    """The places grouped by the point they draw at (within `MARK_PX`), one mark each."""
    groups: list[list[Mapping[str, Any]]] = []
    for m in located:
        x, y = at[int(m["n"])]
        for group in groups:
            gx, gy = at[int(group[0]["n"])]
            if abs(gx - x) <= MARK_PX and abs(gy - y) <= MARK_PX:
                group.append(m)
                break
        else:
            groups.append([m])
    return groups


# -- the document -------------------------------------------------------------------------------------------


def html(data: Mapping[str, Any]) -> str:
    """The paper edition as one HTML document: the cover, the contents, the spreads, the
    colophon; one inline stylesheet, no script, nothing fetched."""
    title = data["year"] if data["kind"] == YEAR else _span_text(data["start"], data["until"])
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(title)} · Logbook</title>",
        f"<style>{layout.stylesheet()}</style>",
        "</head>",
        "<body>",
    ]
    if data["kind"] == YEAR:
        out += _year_cover(data)
        out += _year_contents(data)
        for m in data["months"]:
            out += _month_spread(data, m)
    else:
        out += _trip_cover(data)
        out += _trip_contents(data)
        out += _trip_route(data)
        for d in data["days"]:
            out += _day_spread(d)
    out += _colophon(data)
    out += ["</body>", "</html>"]
    return "\n".join(out) + "\n"


def _year_cover(data: Mapping[str, Any]) -> list[str]:
    w = data["window"]
    dates = (
        "The record has no days in this year."
        if w is None
        else f"{_span_text(w['since'], w['until'])}{DOT}{_plural(w['days'], 'day')}"
    )
    return [
        '<section class="cover">',
        '<p class="kicker">Logbook</p>',
        f"<h1>{escape(data['year'])}</h1>",
        '<hr class="rule">',
        f'<p class="name">{escape(data["name"])}</p>',
        f'<p class="dates">{escape(dates)}</p>',
        "</section>",
    ]


def _trip_cover(data: Mapping[str, Any]) -> list[str]:
    where = ", ".join(data["places"]) if data["places"] else _route_text(data["route"])
    return [
        '<section class="cover">',
        '<p class="kicker">Logbook · a trip</p>',
        f"<h1>{escape(_span_text(data['start'], data['until']))}</h1>",
        '<hr class="rule">',
        f'<p class="name">{escape(data["name"])}</p>',
        f'<p class="dates">{escape(where)}{DOT}{escape(data["head_text"])}</p>',
        "</section>",
    ]


def _route_text(route: Sequence[Mapping[str, Any]]) -> str:
    labels: list[str] = []
    for s in route:
        label = str(s["label"])
        if not labels or labels[-1] != label:
            labels.append(label)
    return f" {ARROW} ".join(labels) if labels else "nowhere"


def _year_contents(data: Mapping[str, Any]) -> list[str]:
    out = ['<section class="contents">', "<h2>Contents</h2>"]
    for warning in data["warnings"]:
        out.append(f'<p class="muted">{escape(warning)}</p>')
    if not data["months"]:
        out += ['<p class="muted">No days.</p>', "</section>"]
        return out
    out.append('<ol class="contents">')
    for m in data["months"]:
        about = [_span_text(m["first"], m["last"]), _plural(m["days"], "day")]
        if m["nights"]["away"]:
            about.append(f"{m['nights']['away']} away")
        if m["flights"]:
            about.append(_plural(len(m["flights"]), "flight"))
        if m["keepers"]:
            about.append(_plural(len(m["keepers"]), "keeper"))
        out.append(
            f'<li><span class="what">{escape(m["name"])}</span>'
            f'<span class="about">{escape(DOT.join(about))}</span></li>'
        )
    out.append("</ol>")
    if data["trips"]:
        out.append("<h3>Trips</h3>")
        rows_: list[list[year_reader.Cell]] = [
            [
                (f"{t['start']} {EN_DASH} {t['end']}", "d"),
                (t["nights"], ""),
                (f" {ARROW} ".join(t["route"]) if t["route"] else "unknown", ""),
                (", ".join(t["people"]), ""),
            ]
            for t in data["trips"]
        ]
        out += year_reader.table([("dates", ""), ("nights", ""), ("route", ""), ("with", "")], rows_)
    out.append("</section>")
    return out


def _trip_contents(data: Mapping[str, Any]) -> list[str]:
    out = ['<section class="contents">', "<h2>Contents</h2>"]
    for warning in data["warnings"]:
        out.append(f'<p class="muted">{escape(warning)}</p>')
    out.append('<ol class="contents">')
    for d in data["days"]:
        about = [d["nights"]["after"]]
        if d["flights"]:
            about.append(", ".join(_flight_text(f) for f in d["flights"]))
        if d["people"]:
            about.append("with " + ", ".join(d["people"]))
        if d["keepers"]:
            about.append(_plural(len(d["keepers"]), "keeper"))
        out.append(
            f'<li><span class="what">{escape(_weekday_date(d))}</span>'
            f'<span class="about">{escape(DOT.join(about))}</span></li>'
        )
    out.append("</ol>")
    flights = [f"in {_flight_text(f)}" for f in data["flights_in"]]
    flights += [f"out {_flight_text(f)}" for f in data["flights_out"]]
    if flights:
        out.append(f"<p>Flights: {escape(DOT.join(flights))}</p>")
    if data["people"]:
        out.append(f"<p>With: {escape(', '.join(data['people']))}</p>")
    out.append("</section>")
    return out


def _trip_route(data: Mapping[str, Any]) -> list[str]:
    """The route on a page of its own: the trip page's map (`trip_page.map_svg`, one path per leg,
    one mark per point) and the stays under it; nothing when the trip has no night anywhere."""
    if not data["route"]:
        return []
    out = ['<section class="route">', "<h2>Route</h2>", trip_page.map_svg(data["route"], data["legs"])]
    rows_: list[list[year_reader.Cell]] = [
        [
            (str(s["n"]), "n"),
            (s["first"] if s["first"] == s["last"] else f"{s['first']} {EN_DASH} {s['last']}", "d"),
            (f"{s['nights']:,}", "n"),
            (trip_page.stay_text(s), ""),
        ]
        for s in data["route"]
    ]
    out += year_reader.table([("#", "n"), ("nights of", ""), ("nights", "n"), ("where", "")], rows_)
    if data["legs"]:
        out.append(f"<p>Legs: {escape(DOT.join(trip_page.leg_text(leg) for leg in data['legs']))}</p>")
    out.append("</section>")
    return out


def _month_spread(data: Mapping[str, Any], m: Mapping[str, Any]) -> list[str]:
    nights = m["nights"]
    night_parts = [f"{nights['home']} home", f"{nights['away']} away"]
    if nights["in_transit"]:
        night_parts.append(f"{nights['in_transit']} in transit")
    night_parts += [f"{_plural(a['nights'], 'night')} aboard {a['name']}" for a in nights["aboard"]]
    facts: list[tuple[str, list[str] | str | None, str]] = [
        ("Nights", DOT.join(night_parts), ""),
        ("Places, by nights", _places_list(m["places"], "nights"), "nowhere"),
        ("With", ", ".join(m["people"]), "nobody confirmed"),
        (
            "Flights",
            [f"{_long_date(f['date'], year=False)}  {_flight_text(f)}" for f in m["flights"]],
            "none",
        ),
    ]
    h = m["health"]
    if h is not None and h["sleep"]:
        facts.append(
            ("Sleep", f"{h['sleep']['mean_h']:.1f} h a night ({_plural(h['sleep']['nights'], 'night')})", "")
        )
    if h is not None and h["steps"]:
        facts.append(("Steps", f"{h['steps']['mean']:,} a day ({_plural(h['steps']['days'], 'day')})", ""))
    facts.append(("Keepers", _keepers_text(m["keepers"]), "none"))
    out = [f'<section class="spread month" id="m-{escape(m["month"])}">', '<article class="facts">']
    out += [
        "<header>",
        f'<p class="kicker">{escape(data["year"])}</p>',
        f"<h2>{escape(m['name'])}</h2>",
        f'<p class="lead">{escape(_span_text(m["first"], m["last"]))}{DOT}{_plural(m["days"], "day")}</p>',
        "</header>",
    ]
    out += _facts_html(facts)
    out.append(m["map"])
    out.append("</article>")
    out += _photos_html(m["keepers"], m["name"])
    out.append("</section>")
    return out


def _day_spread(d: Mapping[str, Any]) -> list[str]:
    facts: list[tuple[str, list[str] | str | None, str]] = [
        ("Night before", d["nights"]["before"], ""),
        ("Night after", d["nights"]["after"], ""),
        ("Country", d["country"] or "", "unknown"),
        ("Places", _places_list(d["places"], None), "nothing logged"),
        ("With", ", ".join(d["people"]), "nobody confirmed"),
        ("Flights", [_flight_text(f) for f in d["flights"]], "none"),
    ]
    h = d["health"]
    if h is not None and h["sleep_h"] is not None:
        facts.append(("Sleep", f"{h['sleep_h']:.1f} h", ""))
    if h is not None and h["steps"] is not None:
        facts.append(("Steps", f"{h['steps']:,}", ""))
    facts.append(("Keepers", _keepers_text(d["keepers"]), "none"))
    out = [f'<section class="spread day" id="d-{escape(d["day"])}">', '<article class="facts">']
    out += [
        "<header>",
        f'<p class="kicker">Day {d["n"]} of {d["of"]}</p>',
        f"<h2>{escape(_weekday_date(d))}</h2>",
        f'<p class="lead">{escape(d["day"])}{DOT}night {escape(d["nights"]["after"])}</p>',
        "</header>",
    ]
    out += _facts_html(facts)
    out.append(d["map"])
    out.append("</article>")
    out += _photos_html(d["keepers"], _weekday_date(d))
    out.append("</section>")
    return out


def _facts_html(facts: Sequence[tuple[str, list[str] | str | None, str]]) -> list[str]:
    """A definition list of (term, the text or the lines or a `Markup`, the word for none); the
    text is escaped here, a `Markup` was escaped when it was built."""
    out = ['<dl class="facts">']
    for term, value, none in facts:
        out.append(f"<dt>{escape(term)}</dt>")
        if isinstance(value, Markup):
            out.append(f"<dd>{value}</dd>")
        elif isinstance(value, list) and value:
            out.append("<dd>" + "<br>".join(escape(v) for v in value) + "</dd>")
        elif isinstance(value, str) and value:
            out.append(f"<dd>{escape(value)}</dd>")
        else:
            out.append(f'<dd class="empty">{escape(none)}</dd>')
    out.append("</dl>")
    return out


def _places_list(places: Sequence[Mapping[str, Any]], count_key: str | None) -> Markup | None:
    """The places numbered as the map marks them, escaped here; None when there are none."""
    if not places:
        return None
    items = []
    for p in places:
        text = escape(p["label"])
        if count_key:
            text += f' <span class="count">{_plural(int(p[count_key]), "night")}</span>'
        items.append(f"<li>{text}</li>")
    return Markup('<ol class="places">' + "".join(items) + "</ol>")


def _photos_html(kept: Sequence[Mapping[str, Any]], heading: str) -> list[str]:
    """The keepers as hero photos, `PHOTOS_PER_PAGE` to a page, the grid class by how many the
    page holds; nothing when there are none."""
    out = []
    for start in range(0, len(kept), layout.PHOTOS_PER_PAGE):
        page = kept[start : start + layout.PHOTOS_PER_PAGE]
        size = next(n for n in (1, 2, 4, 6) if len(page) <= n)
        out.append(f'<article class="photos n{size}" aria-label="{escape(heading)}: the keepers">')
        for k in page:
            caption = f"{_long_date(k['day'])}{DOT}{k['lane']}{DOT}{k['name']}"
            out.append('<figure class="photo">')
            if k["src"]:
                out.append(f'<img src="{escape(k["src"])}" alt="{escape(k["name"])}">')
            else:
                out.append(f'<div class="frame">{escape(k["name"])}<br>not in the record</div>')
            out.append(f"<figcaption>{escape(caption)}</figcaption>")
            out.append("</figure>")
        out.append("</article>")
    return out


def _colophon(data: Mapping[str, Any]) -> list[str]:
    head = str(data.get("head") or "")
    at = f" at head {escape(head[:12])}…" if head else ""
    return [
        '<footer class="colophon">',
        f"<p>Read from the record{at}: derived, never written; the same record gives the same pages."
        " The photos are the record's own files, referenced where they are; the maps are drawn from"
        " the location lines, with no tiles.</p>",
        "</footer>",
    ]


# -- text ----------------------------------------------------------------------------------------------------


def _keepers_text(kept: Sequence[Mapping[str, Any]]) -> str:
    if not kept:
        return ""
    lanes = Counter(str(k["lane"]) for k in kept)
    parts = [f"{lanes[lane]} {lane}" for lane in keepers.LANES if lanes[lane]]
    return f"{len(kept)} ({', '.join(parts)})" if parts else str(len(kept))


def _flight_text(f: Mapping[str, Any]) -> str:
    name = f"{f['carrier']} {f['number']} " if f.get("carrier") and f.get("number") else ""
    return f"{name}{f['from'] or '?'} {ARROW} {f['to'] or '?'}"


def _weekday_date(d: Mapping[str, Any]) -> str:
    return f"{d['weekday']} {_long_date(d['day'], year=False)}"


def _long_date(day: str, year: bool = True) -> str:
    """`1 June 2026`; `1 June` without the year."""
    d = date.fromisoformat(day)
    text = f"{d.day} {MONTHS[d.month - 1]}"
    return f"{text} {d.year}" if year else text


def _span_text(first: str, last: str) -> str:
    """`1-30 June 2026`; `15 June - 21 July 2026`; `20 December 2026 - 3 January 2027`, each dash an
    en dash."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    if a == b:
        return _long_date(first)
    if (a.year, a.month) == (b.year, b.month):
        return f"{a.day}{EN_DASH}{b.day} {MONTHS[a.month - 1]} {a.year}"
    if a.year == b.year:
        return f"{_long_date(first, year=False)} {EN_DASH} {_long_date(last)}"
    return f"{_long_date(first)} {EN_DASH} {_long_date(last)}"


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"
