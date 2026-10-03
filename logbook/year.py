"""The Year: one calendar year of the record, read back — `logbook year YYYY [--html PATH] [--json]`.

A year is the readers composed over one reading of its days: the days per country (the rule
`rollup countries` counts by), the nights home, away and aboard each asset (`rollup nights`), the
trips in order with their nights and companions (`trips`), the flights and their kilometres
(`rollup flights`), the places by nights, named and the top unnamed clusters, with the people
confirmed there (`rollup places`), the people by days together (`rollup people`), the health
lines by month (`rollup health`), the keepers by month (RFC 0024), and twelve picks, **one day
each**: for every month of the year, the day with the most evidence, rendered with the day
reader exactly as `logbook day` prints it.

The evidence of a day is counted from its Day (`day.of_reading`): the attachments across its rows
(events, transcripts, notes, mail threads, calls, messages, photos, keepers, as the Day counts
them), plus the people confirmed present (never a proposal), plus one when the day has a flight
or a new place — a named place not stayed at earlier in the year, or an unnamed stay further than
`places.GROUP_M` from every earlier unnamed stay of the year (the distance `places propose`
groups by); home is never new. Between days of equal evidence, the one with more lines logged
wins, then the earlier day; a month with no line is no pick, and a month whose days have lines
but no evidence shows its fullest day.

The window is the year's days the owner's track covers, as `rollup --year` clips it, so a day the
record knows nothing about is nothing: not a night in transit, not a pick. One `reading.read` of
the window serves every section; the health lines come from the index in one query; each pick
is then read on its own (`day.read`, the day and the day before), so its page is the Day's own,
night before included. Nothing is written, not even `policy/stays.json` (ADR 0013). The HTML page
is one file: inline CSS, no script, no asset, nothing fetched."""

from __future__ import annotations

import html as html_text
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from . import day as day_reader
from . import health, keepers, reading, rollup, stays, trips, weather
from . import places as named_places
from .chain import Line
from .flights import Airports
from .reading import Reading
from .store import Logbook

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
EN_DASH = "\u2013"
EM_DASH = "\u2014"
ARROW = "\u2192"
DOT = " \u00b7 "


# -- the reading --------------------------------------------------------------------------------------------


def parse_year(text: str) -> str:
    """`YYYY`, else `ValueError`."""
    if not re.fullmatch(r"\d{4}", text):
        raise ValueError(f"not a year (YYYY): {text!r}")
    return text


def window(lb: Logbook, year: str) -> tuple[str, str] | None:
    """The year's days the owner's track covers (the first to the last day with a location line,
    the clip `rollup --year` applies); None when the record has no day in the year."""
    whole = reading.record_days(lb, "location")
    if whole is None:
        return None
    first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
    return (first, last) if first <= last else None


def read(lb: Logbook, year: str, airports: Airports | None = None) -> dict[str, Any]:
    """The Year as one JSON-ready object. `ValueError` for a year that is not one;
    `stays.SettingsError` when the record's settings, places or assets file is not what it should
    be. Nothing is written."""
    year = parse_year(year)
    span = window(lb, year)
    head = str(lb.meta.get("head") or "")
    if span is None:
        return _empty(year, head)
    first, last = span
    airports = airports or Airports.load()
    rd = reading.read(lb, first, last, airports)
    before = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
    with lb.index() as idx:
        found = idx.by_kind(health.KIND, before, last)
        marks = idx.retractions()
    scored = _scored(rd, found)
    picks = []
    for month in range(1, 13):
        key = f"{year}-{month:02d}"
        day = pick((d, e) for d, e in scored.items() if d.startswith(key))
        picks.append(
            {
                "month": key,
                "day": day,
                "evidence": scored[day] if day else None,
                "page": day_reader.read(lb, day, airports) if day else None,
            }
        )
    tz = str(rd.tz)
    out: dict[str, Any] = {
        "year": year,
        "window": {"since": first, "until": last, "days": len(rd.days)},
        "head": head,
        "warnings": [],
    }
    out["countries"] = _countries(rd, year)
    out["nights"] = _nights(rd, year)
    out["trips"] = _trips(rd, out["warnings"])
    out["flights"] = _flights(rd, year)
    out["places"] = _places(rd, year)
    out["people"] = _people(rd, year)
    out["health"] = [
        {"month": p["period"], **{k: p[k] for k in ("sleep", "steps", "resting_hr", "hrv")}}
        for p in rollup.health([*found, *marks], tz, first, last, "month")["periods"]
    ]
    out["weather"] = weather.span(weather.by_day(rd.of_kind(weather.KIND)), rd.days)
    out["keepers"] = _keepers(rd)
    out["picks"] = picks
    out["scored"] = scored
    return out


def _empty(year: str, head: str) -> dict[str, Any]:
    return {
        "year": year,
        "window": None,
        "head": head,
        "warnings": [],
        "countries": {"countries": [], "in_transit": 0, "unknown": 0},
        "nights": {"home": 0, "away": 0, "in_transit": 0, "aboard": []},
        "trips": [],
        "flights": {"count": 0, "km": 0, "long_haul": 0, "unmeasured": 0, "by_evidence": {}, "flights": []},
        "places": {"places": [], "assets": [], "unnamed": []},
        "people": [],
        "health": [],
        "weather": None,
        "keepers": [],
        "picks": [
            {"month": f"{year}-{m:02d}", "day": None, "evidence": None, "page": None} for m in range(1, 13)
        ],
        "scored": {},
    }


def _year_entry(data: Mapping[str, Any], year: str) -> dict[str, Any] | None:
    return next((y for y in data["years"] if y["year"] == year), None)


def _countries(rd: Reading, year: str) -> dict[str, Any]:
    found = _year_entry(rollup.countries(rd), year)
    if found is None:
        return {"countries": [], "in_transit": 0, "unknown": 0}
    return {
        "countries": [{"country": c["country"], "days": c["days"]} for c in found["countries"]],
        "in_transit": found["in_transit"]["days"],
        "unknown": found["unknown"]["days"],
    }


def _nights(rd: Reading, year: str) -> dict[str, Any]:
    found = _year_entry(rollup.nights(rd), year)
    if found is None:
        return {"home": 0, "away": 0, "in_transit": 0, "aboard": []}
    aboard = [
        {"asset": asset, "name": rd.assets[asset].name if asset in rd.assets else asset, "nights": n}
        for asset, n in sorted(found["aboard"].items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    return {k: found[k] for k in ("home", "away", "in_transit")} | {"aboard": aboard}


def _trips(rd: Reading, warnings: list[str]) -> list[dict[str, Any]]:
    found, warning = trips.trips(rd)
    if warning:
        warnings.append(warning)
    out = []
    for trip in found:
        data = trip.to_json()
        data["people"] = [c.name for c in trip.people]
        del data["flights"], data["lines"]
        out.append(data)
    return out


def _flights(rd: Reading, year: str) -> dict[str, Any]:
    found = _year_entry(rollup.flights(rd), year)
    if found is None:
        return {"count": 0, "km": 0, "long_haul": 0, "unmeasured": 0, "by_evidence": {}, "flights": []}
    return {
        **{k: found[k] for k in ("count", "km", "long_haul", "unmeasured", "by_evidence")},
        "flights": [{k: v for k, v in f.items() if k != "lines"} for f in found["flights"]],
    }


def _places(rd: Reading, year: str) -> dict[str, Any]:
    found = _year_entry(rollup.places(rd), year)
    if found is None:
        return {"places": [], "assets": [], "unnamed": []}

    def by_nights(entries: Iterable[Mapping[str, Any]], *keys: str) -> list[dict[str, Any]]:
        kept = [
            {k: e[k] for k in (*keys, "nights", "stays", "hours", "first", "last")}
            | {"people": [p["name"] for p in e["people"]]}
            for e in entries
        ]
        return sorted(kept, key=lambda e: (-e["nights"], -e["hours"]))

    return {
        "places": by_nights(found["places"], "place", "kind"),
        "assets": by_nights(found["aboard"], "asset", "name", "kind"),  # the rollup calls them aboard
        "unnamed": by_nights(found["unnamed"], "id", "label", "lat", "lon", "aboard", "city"),
    }


def _people(rd: Reading, year: str) -> list[dict[str, Any]]:
    found = _year_entry(rollup.people(rd), year)
    if found is None:
        return []
    keys = ("id", "name", "days", "nights", "stays", "last_contact", "places", "confirmed")
    return [{k: p[k] for k in keys} for p in found["people"]]


def _keepers(rd: Reading) -> list[dict[str, Any]]:
    """The keepers standing per month of the window, by lane; every month the window touches."""
    months: dict[str, dict[str, Any]] = {}
    for day in rd.days:
        months.setdefault(day[:7], {"month": day[:7], "count": 0, keepers.MEMORY: 0, keepers.ART: 0})
    for line in rd.of_kind(keepers.KIND):
        entry = months.get(rd.day_of(line)[:7])
        if entry is None:
            continue
        entry["count"] += 1
        lane = (line.get("payload") or {}).get("lane")
        if lane in keepers.LANES:
            entry[lane] += 1
    return list(months.values())


# -- the picks ----------------------------------------------------------------------------------------------


def _scored(rd: Reading, health_lines: Sequence[Line]) -> dict[str, dict[str, Any]]:
    """Every day of the reading with its evidence, from its Day."""
    health_of = day_reader.health_rows(health_lines, rd)
    by_day = _lines_by_day(rd)
    fresh = new_place_days(rd)
    return {
        day: evidence(day_reader.of_reading(rd, day, health_of.get(day), by_day.get(day, [])), day in fresh)
        for day in rd.days
    }


def _lines_by_day(rd: Reading) -> dict[str, list[Line]]:
    """The reading's lines by local day, in chain order, so each day's are picked once."""
    found: dict[str, list[Line]] = {}
    for line in rd.lines:
        at = stays.instant(line.get("at"))
        if at is not None:
            found.setdefault(at.astimezone(rd.tz).date().isoformat(), []).append(line)
    return found


def new_place_days(rd: Reading) -> set[str]:
    """The days on which the owner's stays began somewhere new in the window: a named place not
    stayed at before, or an unnamed stay further than `places.GROUP_M` from every earlier unnamed
    stay; a stay at home (`stays.is_home`: a place of kind home, or within 400 m of one) is never
    new. A stay counts on the local day it began."""
    names: set[str] = set()
    points: list[tuple[float, float]] = []
    out: set[str] = set()
    for stay in sorted(rd.owner_stays, key=lambda s: (s.start, s.id)):
        if stays.is_home(stay, rd.places):
            continue
        day = stay.start.astimezone(rd.tz).date().isoformat()
        if stay.place is not None:
            if stay.place in names:
                continue
            names.add(stay.place)
        elif stay.lat is not None and stay.lon is not None:
            lat, lon = stay.lat, stay.lon
            if any(named_places.distance_m(lat, lon, a, b) <= named_places.GROUP_M for a, b in points):
                continue
            points.append((lat, lon))
        else:
            continue
        out.add(day)
    return out


def evidence(page: Mapping[str, Any], new_place: bool) -> dict[str, Any]:
    """A Day's evidence: the attachments across its rows, the people confirmed, whether it has a
    flight, whether a stay began at a new place, the lines logged, and the score — attachments plus
    people plus one for a flight or a new place."""
    attachments = 0
    people: set[str] = set()
    for entry in page["timeline"]:
        attachments += sum(n for n, _noun in day_reader.counts(entry.get("attached")))
        for c in (entry.get("with") or {}).get("confirmed", []):
            people.add(str(c.get("person") or c.get("name")))
    flight = bool(page["flights"])
    lines = sum(int(s["lines"]) for s in page["sources"])
    return {
        "attachments": attachments,
        "people": len(people),
        "flight": flight,
        "new_place": new_place,
        "lines": lines,
        "score": attachments + len(people) + int(flight or new_place),
    }


def pick(scored: Iterable[tuple[str, Mapping[str, Any]]]) -> str | None:
    """The day with the most evidence among those with a line; of equals, the one with more lines
    logged, then the earlier; None when no day has a line."""
    logged = [(day, e) for day, e in scored if e["lines"]]
    if not logged:
        return None
    return min(logged, key=lambda item: (-item[1]["score"], -item[1]["lines"], item[0]))[0]


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: Mapping[str, Any]) -> Iterator[str]:
    """The Year as text: the header, one section per reader, then the twelve picks."""
    year = data["year"]
    w = data["window"]
    if w is None:
        yield f"year {year}: the record has no days in it"
        return
    yield f"{year}  {w['since']} {EN_DASH} {w['until']}{DOT}{_plural(w['days'], 'day')}"
    for warning in data["warnings"]:
        yield f"  ({warning})"
    yield _row("countries", countries_text(data["countries"]))
    yield _row("nights", nights_text(data["nights"]))
    yield _row("trips", trips_head(data["trips"]))
    for trip in data["trips"]:
        yield f"    {trip_text(trip)}"
    yield _row("flights", flights_head(data["flights"]))
    for f in data["flights"]["flights"]:
        yield f"    {flight_text(f)}"
    yield _row("places", "by nights")
    places = data["places"]
    heads = [
        *(_place_head(p) for p in places["places"]),
        *(_asset_head(a) for a in places["assets"]),
        *(str(u["label"]) for u in places["unnamed"]),
    ]
    width = max(28, *(len(h) for h in heads)) if heads else 28
    for p in places["places"]:
        yield f"    {_place_head(p):<{width}} {visit_text(p)}"
    for a in places["assets"]:
        yield f"    {_asset_head(a):<{width}} {visit_text(a)}"
    if places["unnamed"]:
        yield "    unnamed:"
    for u in places["unnamed"]:
        yield f"    {u['label']:<{width}} {visit_text(u)}"
    if not heads:
        yield "    nowhere"
    yield _row("people", "by days together")
    for p in data["people"]:
        yield f"    {p['name']:<{width}} {person_text(p)}"
    if not data["people"]:
        yield "    nobody confirmed"
    yield _row("health", "by month")
    for m in data["health"]:
        yield f"    {m['month']}  {health_text(m)}"
    if data.get("weather"):
        yield _row("weather", weather.span_text(data["weather"]))
    yield _row("keepers", "by month")
    for m in data["keepers"]:
        yield f"    {m['month']}  {keepers_text(m)}"
    yield ""
    yield "  one day each"
    for p in data["picks"]:
        name = MONTHS[int(p["month"][5:7]) - 1]
        if p["day"] is None:
            yield _row(name, "no days")
            continue
        yield _row(name, f"{p['day']}{DOT}{evidence_text(p['evidence'])}")
        for text in day_reader.rows(p["page"]):
            yield f"    {text}" if text else ""


def _row(label: str, text: str) -> str:
    return f"  {label:<13} {text}"


def countries_text(c: Mapping[str, Any]) -> str:
    parts = [f"{e['country']} {_plural(e['days'], 'day')}" for e in c["countries"]]
    parts.append(f"in transit {c['in_transit']}")
    if c["unknown"]:
        parts.append(f"unknown {c['unknown']}")
    return DOT.join(parts)


def nights_text(n: Mapping[str, Any]) -> str:
    parts = [f"{n['home']} home", f"{n['away']} away", f"{n['in_transit']} in transit"]
    parts += [f"{_plural(a['nights'], 'night')} aboard {a['name']}" for a in n["aboard"]]
    return DOT.join(parts)


def trips_head(found: Sequence[Mapping[str, Any]]) -> str:
    if not found:
        return "none"
    nights = sum(int(t["nights"]) for t in found)
    return f"{_plural(len(found), 'trip')}{DOT}{_plural(nights, 'night')} away"


def trip_text(trip: Mapping[str, Any]) -> str:
    """One trip as `trips` prints it: the dates, the nights, the route, the flights in and out,
    the places, the people."""
    nights = _plural(int(trip["nights"]), "night")
    if trip["asset"]:
        nights += f" aboard {trip['asset']}"
    if trip["in_transit"]:
        nights += f" ({trip['in_transit']} in transit)"
    parts = [nights, f"route {f' {ARROW} '.join(trip['route'])}" if trip["route"] else "route unknown"]
    for label in ("in", "out"):
        for f in trip[f"flights_{label}"]:
            name = f"{f['carrier']} {f['number']} " if f["number"] else ""
            parts.append(f"{label} {name}{f['from']} {ARROW} {f['to']}")
    if trip["places"]:
        parts.append("places " + ", ".join(trip["places"]))
    if trip["people"]:
        parts.append("with " + ", ".join(trip["people"]))
    if trip.get("weather"):
        parts.append("weather " + weather.span_text(trip["weather"]))
    return f"{trip['start']} {EN_DASH} {trip['end']}  {DOT.join(parts)}"


def flights_head(f: Mapping[str, Any]) -> str:
    if not f["count"]:
        return "none"
    parts = [_plural(f["count"], "flight"), f"{f['km']:,} km", f"{f['long_haul']} long-haul"]
    if f["unmeasured"]:
        parts.append(f"{f['unmeasured']} unmeasured")
    parts.append(", ".join(f"{k} {v}" for k, v in sorted(f["by_evidence"].items())))
    return DOT.join(parts)


def flight_text(f: Mapping[str, Any]) -> str:
    name = f"{f['carrier']} {f['number']}  " if f["number"] else ""
    km = "" if f["km"] is None else f"{DOT}{f['km']:,} km"
    return f"{f['date']}  {name}{f['from'] or '?'} {ARROW} {f['to'] or '?'}{km}{DOT}{f['evidence']}"


def _place_head(p: Mapping[str, Any]) -> str:
    return f"{p['place']} ({p['kind']})" if p.get("kind") else str(p["place"])


def _asset_head(a: Mapping[str, Any]) -> str:
    head = f"{a['name']} ({a['asset']})" if a.get("name") else str(a["asset"])
    return f"{head} ({a['kind']})" if a.get("kind") else head


def visit_text(v: Mapping[str, Any]) -> str:
    parts = [_plural(v["nights"], "night"), _plural(v["stays"], "stay"), f"{round(v['hours']):,} h"]
    if v["people"]:
        parts.append("with " + ", ".join(v["people"]))
    return DOT.join(parts)


def person_text(p: Mapping[str, Any]) -> str:
    parts = [
        _plural(p["days"], "day"),
        _plural(p["nights"], "night"),
        f"last {p['last_contact']}",
        ", ".join(p["places"]) if p["places"] else "nowhere",
    ]
    return DOT.join(parts)


def health_text(m: Mapping[str, Any]) -> str:
    """The rollup's own row: `sleep 7.2 h (29 nights)`, `8,000 steps (30 days)`, `resting 55 bpm`
    with its range and days, `hrv 45 ms (30 days)`; a field with no line is an em dash, never a zero."""
    sleep, steps, resting, hrv = (m[k] for k in ("sleep", "steps", "resting_hr", "hrv"))
    parts = [
        f"sleep {EM_DASH}"
        if sleep is None
        else f"sleep {sleep['mean_h']:.1f} h ({_plural(sleep['nights'], 'night')})",
        f"steps {EM_DASH}" if steps is None else f"{steps['mean']:,} steps ({_plural(steps['days'], 'day')})",
        f"resting {EM_DASH}"
        if resting is None
        else (
            f"resting {resting['mean']} bpm ({resting['min']}{EN_DASH}{resting['max']}, "
            f"{_plural(resting['days'], 'day')})"
        ),
        f"hrv {EM_DASH}" if hrv is None else f"hrv {hrv['mean_ms']} ms ({_plural(hrv['days'], 'day')})",
    ]
    return DOT.join(parts)


def keepers_text(m: Mapping[str, Any]) -> str:
    if not m["count"]:
        return "none"
    return f"{m['count']} ({m[keepers.MEMORY]} memory, {m[keepers.ART]} art)"


def evidence_text(e: Mapping[str, Any]) -> str:
    parts = []
    if e["attachments"]:
        parts.append(_plural(e["attachments"], "attachment"))
    if e["people"]:
        parts.append(_plural(e["people"], "person", "people"))
    if e["flight"]:
        parts.append("a flight")
    if e["new_place"]:
        parts.append("a new place")
    return ", ".join(parts) if parts else f"no evidence, {_plural(e['lines'], 'line')}"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {plural or noun + 's'}"


# -- the page -----------------------------------------------------------------------------------------------

CSS = """
:root { color-scheme: light; }
html { background: #fff; }
body { font: 11pt/1.5 -apple-system, "Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: #1b1b1b; background: #fff; max-width: 54rem; margin: 2.5rem auto; padding: 0 1.25rem; }
h1 { font-size: 3rem; line-height: 1; margin: 0 0 .5rem; letter-spacing: -.03em; }
h2 { font-size: 1.3rem; margin: 2.25rem 0 .6rem; padding-bottom: .25rem; border-bottom: 1px solid #c9c9c4;
  break-after: avoid; }
h3 { font-size: 1.05rem; margin: 1.5rem 0 .25rem; break-after: avoid; }
p { margin: .35rem 0; }
.muted { color: #666; }
table { border-collapse: collapse; width: 100%; margin: .25rem 0 .5rem; }
th, td { text-align: left; vertical-align: top; padding: .22rem .75rem .22rem 0;
  border-bottom: 1px solid #ebebe7; }
th { font-weight: 600; color: #555; font-size: .85em; text-transform: uppercase; letter-spacing: .03em; }
td.n, th.n { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.d { white-space: nowrap; font-variant-numeric: tabular-nums; }
pre { font: 9pt/1.45 ui-monospace, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
  white-space: pre-wrap; overflow-wrap: anywhere; background: #f5f5f1; padding: .8rem 1rem; margin: .4rem 0 0;
  border-radius: 4px; }
.pick { break-inside: avoid; margin-bottom: 1rem; }
.pick h3 span { font-weight: 400; color: #666; }
footer { margin: 3rem 0 1rem; padding-top: .6rem; border-top: 1px solid #c9c9c4; color: #666;
  font-size: .85em; }
@page { margin: 18mm; }
@media print {
  body { max-width: none; margin: 0; padding: 0; font-size: 10pt; }
  h1 { font-size: 2.4rem; }
  pre { background: none; padding: 0; border: 1px solid #ddd; padding: .5rem; }
  #picks { break-before: page; }
}
"""


def html(data: Mapping[str, Any]) -> str:
    """The Year as one self-contained HTML page: inline CSS, no script, no asset, nothing fetched;
    everything the record says is escaped. Suitable for printing."""
    year = data["year"]
    out = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{escape(year)} · Logbook</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        f"<h1>{escape(year)}</h1>",
    ]
    w = data["window"]
    if w is None:
        out += [
            '<p class="muted">The record has no days in this year.</p>',
            "</header>",
            *footer(data),
            "</body>",
            "</html>",
        ]
        return "\n".join(out) + "\n"
    out.append(
        f"<p>{escape(w['since'])} {EN_DASH} {escape(w['until'])}{DOT}{_plural(w['days'], 'day')}"
        " the track covers</p>"
    )
    for warning in data["warnings"]:
        out.append(f'<p class="muted">{escape(warning)}</p>')
    out.append("</header>")
    out += section("countries", "Days per country", _countries_html(data["countries"], data["nights"]))
    out += section("trips", "Trips", _trips_html(data["trips"]))
    out += section("flights", "Flights", _flights_html(data["flights"]))
    out += section("places", "Places, by nights", _places_html(data["places"]))
    out += section("people", "People", _people_html(data["people"]))
    out += section("health", "Health, by month", _health_html(data["health"]))
    if data.get("weather"):
        out += section("weather", "Weather", [f"<p>{escape(weather.span_text(data['weather']))}</p>"])
    out += section("keepers", "Keepers", _keepers_html(data["keepers"]))
    out += section("picks", "One day each", _picks_html(data["picks"]))
    out += footer(data)
    out += ["</body>", "</html>"]
    return "\n".join(out) + "\n"


def escape(text: object) -> str:
    return html_text.escape(str(text), quote=True)


def section(id_: str, heading: str, body: Sequence[str]) -> list[str]:
    return [f'<section id="{id_}">', f"<h2>{escape(heading)}</h2>", *body, "</section>"]


Cell = tuple[str | Sequence[str], str]  # the text (or the lines of a cell) and its class


def table(heads: Sequence[tuple[str, str]], body: Sequence[Sequence[Cell]]) -> list[str]:
    """A table from (text, class) cells; the text is escaped here, a cell of several lines broken
    between them."""
    out = ["<table>", "<thead><tr>"]
    out += [
        f'<th class="{cls}">{escape(text)}</th>' if cls else f"<th>{escape(text)}</th>" for text, cls in heads
    ]
    out += ["</tr></thead>", "<tbody>"]
    for row in body:
        cells = [
            f'<td class="{cls}">{_cell(text)}</td>' if cls else f"<td>{_cell(text)}</td>" for text, cls in row
        ]
        out.append("<tr>" + "".join(cells) + "</tr>")
    out += ["</tbody>", "</table>"]
    return out


def _cell(text: str | Sequence[str]) -> str:
    return escape(text) if isinstance(text, str) else "<br>".join(escape(t) for t in text)


def _countries_html(c: Mapping[str, Any], n: Mapping[str, Any]) -> list[str]:
    rows_ = [[(e["country"], "d"), (f"{e['days']:,}", "n")] for e in c["countries"]]
    rows_.append([("in transit", "d"), (f"{c['in_transit']:,}", "n")])
    if c["unknown"]:
        rows_.append([("unknown", "d"), (f"{c['unknown']:,}", "n")])
    out = table([("country", ""), ("days", "n")], rows_)
    out.append(f"<p>Nights: {escape(nights_text(n))}</p>")
    return out


def _trips_html(found: Sequence[Mapping[str, Any]]) -> list[str]:
    if not found:
        return ['<p class="muted">No trips.</p>']
    rows_ = []
    for t in found:
        nights = _plural(int(t["nights"]), "night") + (f" aboard {t['asset']}" if t["asset"] else "")
        flights = []
        for label in ("in", "out"):
            for f in t[f"flights_{label}"]:
                name = f"{f['carrier']} {f['number']} " if f["number"] else ""
                flights.append(f"{label} {name}{f['from']} {ARROW} {f['to']}")
        rows_.append(
            [
                (f"{t['start']} {EN_DASH} {t['end']}", "d"),
                (nights, ""),
                (f" {ARROW} ".join(t["route"]) if t["route"] else "unknown", ""),
                (flights, ""),
                (", ".join(t["people"]), ""),
            ]
        )
    out = [f"<p>{escape(trips_head(found))}</p>"]
    out += table([("dates", ""), ("nights", ""), ("route", ""), ("flights", ""), ("with", "")], rows_)
    return out


def _flights_html(f: Mapping[str, Any]) -> list[str]:
    if not f["count"]:
        return ['<p class="muted">No flights.</p>']
    rows_ = [
        [
            (x["date"], "d"),
            (f"{x['carrier']} {x['number']}" if x["number"] else "", "d"),
            (f"{x['from'] or '?'} {ARROW} {x['to'] or '?'}", "d"),
            ("" if x["km"] is None else f"{x['km']:,}", "n"),
            (x["evidence"], ""),
        ]
        for x in f["flights"]
    ]
    out = [f"<p>{escape(flights_head(f))}</p>"]
    out += table([("date", ""), ("flight", ""), ("route", ""), ("km", "n"), ("evidence", "")], rows_)
    return out


def _places_html(p: Mapping[str, Any]) -> list[str]:
    rows_: list[list[Cell]] = []
    for e in p["places"]:
        rows_.append(_visit_row(_place_head(e), e))
    for e in p["assets"]:
        rows_.append(_visit_row(_asset_head(e), e))
    for e in p["unnamed"]:
        rows_.append(_visit_row(str(e["label"]), e))
    if not rows_:
        return ['<p class="muted">Nowhere.</p>']
    out = table([("place", ""), ("nights", "n"), ("stays", "n"), ("hours", "n"), ("with", "")], rows_)
    if p["unnamed"]:
        out.append(
            '<p class="muted">An unnamed place is one `places name` takes; its stay id is under --json.</p>'
        )
    return out


def _visit_row(head: str, v: Mapping[str, Any]) -> list[Cell]:
    return [
        (head, ""),
        (f"{v['nights']:,}", "n"),
        (f"{v['stays']:,}", "n"),
        (f"{round(v['hours']):,}", "n"),
        (", ".join(v["people"]), ""),
    ]


def _people_html(people: Sequence[Mapping[str, Any]]) -> list[str]:
    if not people:
        return ['<p class="muted">Nobody confirmed.</p>']
    rows_ = [
        [
            (p["name"], ""),
            (f"{p['days']:,}", "n"),
            (f"{p['nights']:,}", "n"),
            (p["last_contact"] or "", "d"),
            (", ".join(p["places"]), ""),
        ]
        for p in people
    ]
    return table([("person", ""), ("days", "n"), ("nights", "n"), ("last", ""), ("places", "")], rows_)


def _health_html(months: Sequence[Mapping[str, Any]]) -> list[str]:
    if not months:
        return ['<p class="muted">No health lines.</p>']

    def cell(value: Mapping[str, Any] | None, text: str) -> tuple[str, str]:
        return (EM_DASH if value is None else text, "n")

    rows_ = []
    for m in months:
        sleep, steps, resting, hrv = (m[k] for k in ("sleep", "steps", "resting_hr", "hrv"))
        rows_.append(
            [
                (m["month"], "d"),
                cell(sleep, "" if sleep is None else f"{sleep['mean_h']:.1f} h ({sleep['nights']})"),
                cell(steps, "" if steps is None else f"{steps['mean']:,} ({steps['days']})"),
                cell(
                    resting,
                    ""
                    if resting is None
                    else (
                        f"{resting['mean']} bpm, {resting['min']}{EN_DASH}{resting['max']}"
                        f" ({resting['days']})"
                    ),
                ),
                cell(hrv, "" if hrv is None else f"{hrv['mean_ms']} ms ({hrv['days']})"),
            ]
        )
    out = table(
        [("month", ""), ("sleep", "n"), ("steps", "n"), ("resting heart rate", "n"), ("hrv", "n")], rows_
    )
    out.append('<p class="muted">Means over the nights and days with a line, their count in parentheses.</p>')
    return out


def _keepers_html(months: Sequence[Mapping[str, Any]]) -> list[str]:
    if not months:
        return ['<p class="muted">No keepers.</p>']
    rows_ = [
        [(m["month"], "d"), (f"{m['count']:,}", "n"), (f"{m['memory']:,}", "n"), (f"{m['art']:,}", "n")]
        for m in months
    ]
    return table([("month", ""), ("keepers", "n"), ("memory", "n"), ("art", "n")], rows_)


def _picks_html(picks: Sequence[Mapping[str, Any]]) -> list[str]:
    out = [
        "<p>For each month, the day with the most evidence: attachments, people confirmed, a flight or a"
        " new place; read back with the day reader.</p>"
    ]
    for p in picks:
        name = MONTHS[int(p["month"][5:7]) - 1]
        out.append('<article class="pick">')
        if p["day"] is None:
            out.append(f"<h3>{escape(name)} <span>no days</span></h3>")
        else:
            page = p["page"]
            why = f"{p['day']}, {page['weekday']}{DOT}{evidence_text(p['evidence'])}"
            out.append(f"<h3>{escape(name)} <span>{escape(why)}</span></h3>")
            out.append("<pre>" + "\n".join(escape(text) for text in day_reader.rows(page)) + "</pre>")
        out.append("</article>")
    return out


def footer(data: Mapping[str, Any]) -> list[str]:
    head = str(data.get("head") or "")
    at = f" at head {escape(head[:12])}…" if head else ""
    return [
        "<footer>",
        f"<p>Read from the record{at}: derived, never written; the same record gives the same page.</p>",
        "</footer>",
    ]
