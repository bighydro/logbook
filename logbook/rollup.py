"""`logbook rollup <kind>`: the record summed up per year — countries, flights, nights, places,
people — from one reading of the window (`reading.read`). Every number carries, under `lines`,
the ids of the lines it came from: for a stay, the ids of its first and last location line (a
stay is one unbroken run of one subject's points, so the two ids name the run); for a flight,
the flight line standing; for a person, the lines that put them there. Readers derive and never
append (ADR 0013); the same record gives the same rollup."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from . import countries as country_table
from . import flights as flight_lines
from . import places as named_places
from . import present, stays
from .reading import Reading, window_json

KINDS = ("countries", "flights", "nights", "places", "people")
LONG_HAUL_KM = 3500.0
EN_DASH = "\u2013"
ARROW = "\u2192"


def _year_of(day: str) -> str:
    return day[:4]


def _stay_lines(stay: stays.Segment | None) -> list[str]:
    if stay is None:
        return []
    return [id_ for id_ in (stay.first_line, stay.last_line) if id_]


def _head(kind: str, reading: Reading) -> dict[str, Any]:
    return {"kind": kind, "window": window_json(reading)}


def empty(kind: str) -> dict[str, Any]:
    """The rollup of a record with no lines."""
    return {"kind": kind, "window": {"since": None, "until": None, "days": []}, "years": []}


# -- countries --------------------------------------------------------------------------------------------


def countries(reading: Reading, table: country_table.Countries | None = None) -> dict[str, Any]:
    """Days per country per year from the overnight stay; in-transit nights and nights whose
    country is unknown listed separately. The method is reported with the numbers."""
    table = table or country_table.Countries.load()
    years: dict[str, dict[str, Any]] = {}
    for night in reading.nights:
        year = years.setdefault(
            _year_of(night.day),
            {"year": _year_of(night.day), "countries": {}, "in_transit": _bucket(), "unknown": _bucket()},
        )
        if night.stay is None:
            _count(year["in_transit"], night.day, [])
            continue
        assert night.stay.lat is not None and night.stay.lon is not None
        found = country_table.country_of(
            night.stay.lat, night.stay.lon, reading.places, reading.airports, table
        )
        if found.code is None:
            _count(year["unknown"], night.day, _stay_lines(night.stay))
            continue
        bucket = year["countries"].setdefault(
            found.code, {"country": found.code, **_bucket(), "by": Counter()}
        )
        _count(bucket, night.day, _stay_lines(night.stay))
        bucket["by"][found.method] += 1
    out = _head("countries", reading)
    out["method"] = country_table.METHOD_TEXT
    out["years"] = []
    for key in sorted(years):
        entry = years[key]
        entry["countries"] = sorted(
            ({**c, "by": dict(c["by"])} for c in entry["countries"].values()),
            key=lambda c: (-c["days"], c["country"]),
        )
        out["years"].append(entry)
    return out


def _bucket() -> dict[str, Any]:
    return {"days": 0, "dates": [], "lines": []}


def _count(bucket: dict[str, Any], day: str, lines: list[str]) -> None:
    bucket["days"] += 1
    bucket["dates"].append(day)
    bucket["lines"].extend(lines)


# -- flights ------------------------------------------------------------------------------------------------


def flights(reading: Reading) -> dict[str, Any]:
    """Count, kilometres (great-circle between the airports table's coordinates), long-haul
    flights (over `LONG_HAUL_KM`) and counts by evidence, per year, from the flight lines
    standing in the window (RFC 0013 rule 4). A flight whose airport the table does not know
    is counted and listed with `km` null, under `unmeasured`."""
    standing = flight_lines.standing(reading.of_kind(flight_lines.KIND))
    years: dict[str, dict[str, Any]] = {}
    for line in sorted(
        standing.values(), key=lambda line: (str(line["payload"].get("date")), int(line["seq"]))
    ):
        payload = line["payload"]
        date = str(payload.get("date") or line["at"][:10])
        year = years.setdefault(
            _year_of(date),
            {
                "year": _year_of(date),
                "count": 0,
                "km": 0.0,
                "long_haul": 0,
                "unmeasured": 0,
                "by_evidence": Counter(),
                "flights": [],
                "lines": [],
            },
        )
        origin, destination = (_code(payload.get(end)) for end in ("from", "to"))
        km = _km(payload, reading)
        evidence = str(payload.get("evidence") or "")
        year["count"] += 1
        if km is None:
            year["unmeasured"] += 1
        else:
            year["km"] += km
            if km > LONG_HAUL_KM:
                year["long_haul"] += 1
        year["by_evidence"][evidence] += 1
        year["flights"].append(
            {
                "date": date,
                "carrier": payload.get("carrier"),
                "number": payload.get("number"),
                "from": origin,
                "to": destination,
                "km": None if km is None else round(km),
                "evidence": evidence,
                "role": payload.get("role"),
                "lines": [str(line["id"])],
            }
        )
        year["lines"].append(str(line["id"]))
    out = _head("flights", reading)
    out["long_haul_km"] = int(LONG_HAUL_KM)
    out["years"] = [
        {**years[y], "km": round(years[y]["km"]), "by_evidence": dict(years[y]["by_evidence"])}
        for y in sorted(years)
    ]
    return out


def _code(ref: object) -> str | None:
    if not isinstance(ref, dict):
        return None
    code = ref.get("iata") or ref.get("icao")
    return str(code) if code else None


def _km(payload: dict[str, Any], reading: Reading) -> float | None:
    ends = []
    for end in ("from", "to"):
        code = _code(payload.get(end))
        airport = reading.airports.get(code) if code else None
        if airport is None:
            return None
        ends.append(airport)
    a, b = ends
    return flight_lines.distance_km(a.lat, a.lon, b.lat, b.lon)


# -- nights ------------------------------------------------------------------------------------------------


def nights(reading: Reading) -> dict[str, Any]:
    """Home, away and in-transit nights per year, the nights aboard each asset, and the longest
    trip: the longest run of consecutive nights not at home. Without a place of kind `home` in
    places.json every night is away, and the rollup says so."""
    years: dict[str, dict[str, Any]] = {}
    for night in reading.nights:
        year = years.setdefault(
            _year_of(night.day),
            {
                "year": _year_of(night.day),
                "home": 0,
                "away": 0,
                "in_transit": 0,
                "aboard": Counter(),
                "lines": [],
            },
        )
        if night.stay is None:
            year["in_transit"] += 1
        elif night.home:
            year["home"] += 1
        else:
            year["away"] += 1
        if night.stay is not None and night.stay.aboard:
            year["aboard"][night.stay.aboard] += 1
        year["lines"].extend(_stay_lines(night.stay))
    out = _head("nights", reading)
    if not named_places.home_places(reading.places):
        out["warning"] = "no place of kind home in places.json: every night counts as away"
    out["years"] = []
    for key in sorted(years):
        entry = years[key]
        entry["aboard"] = dict(entry["aboard"])
        entry["longest_trip"] = _longest_trip([n for n in reading.nights if _year_of(n.day) == key])
        out["years"].append(entry)
    return out


def _longest_trip(nights_of_year: Sequence[stays.Night]) -> dict[str, Any] | None:
    best: list[stays.Night] = []
    run: list[stays.Night] = []
    for night in nights_of_year:
        if night.home:
            best, run = max(best, run, key=len), []
        else:
            run.append(night)
    best = max(best, run, key=len)
    if not best:
        return None
    lines = [id_ for n in best for id_ in _stay_lines(n.stay)]
    return {"start": best[0].day, "end": best[-1].day, "nights": len(best), "lines": lines}


# -- places -------------------------------------------------------------------------------------------------


def places(reading: Reading) -> dict[str, Any]:
    """Per named place (places.json) and per asset (assets.json), per year: stays, hours, first
    and last visit, the nights (assets), and the people present, confirmed, through the with
    module. An asset's stays are the owner's stays aboard it."""
    years: dict[str, dict[str, Any]] = {}
    days_of = _days_of_lines(reading)
    for stay in reading.owner_stays:
        day = stay.start.astimezone(reading.tz).date().isoformat()
        end_day = stay.end.astimezone(reading.tz).date().isoformat()
        year = years.setdefault(_year_of(day), {"year": _year_of(day), "places": {}, "assets": {}})
        who = [
            c
            for c in present.company(stay, reading.lines, reading.identities)
            if c.status == present.CONFIRMED
        ]
        who_days = {c: {days_of.get(id_, day) for id_ in c.lines} for c in who}
        if stay.place is not None:
            place = next((p for p in reading.places if p.name == stay.place), None)
            entry = year["places"].setdefault(
                stay.place, {"place": stay.place, "kind": place.kind if place else None, **_visits()}
            )
            _visit(entry, stay, day, end_day, who, who_days)
        if stay.aboard is not None:
            asset = reading.assets.get(stay.aboard)
            entry = year["assets"].setdefault(
                stay.aboard,
                {
                    "asset": stay.aboard,
                    "name": asset.name if asset else None,
                    "kind": asset.kind if asset else None,
                    **_visits(),
                    "nights": 0,
                },
            )
            _visit(entry, stay, day, end_day, who, who_days)
    for night in reading.nights:
        if night.stay is not None and night.stay.aboard:
            aboard = years.get(_year_of(night.day), {"assets": {}})["assets"].get(night.stay.aboard)
            if aboard is not None:
                aboard["nights"] += 1
    out = _head("places", reading)
    out["years"] = []
    for key in sorted(years):
        entry = years[key]
        out["years"].append(
            {
                "year": key,
                "places": [
                    _finish_visits(v) for v in sorted(entry["places"].values(), key=lambda v: -v["hours"])
                ],
                "assets": [
                    _finish_visits(v) for v in sorted(entry["assets"].values(), key=lambda v: -v["hours"])
                ],
            }
        )
    return out


def _visits() -> dict[str, Any]:
    return {"stays": 0, "hours": 0.0, "first": None, "last": None, "people": {}, "lines": []}


def _days_of_lines(reading: Reading) -> dict[str, str]:
    """line id → its local day, for the evidence lines a companion rests on."""
    return {str(line["id"]): reading.day_of(line) for line in reading.lines if line.get("kind") in EVIDENCE}


EVIDENCE = ("event", "transcript", "note", "photo")


def _visit(
    entry: dict[str, Any],
    stay: stays.Segment,
    day: str,
    end_day: str,
    who: Sequence[present.Companion],
    who_days: Mapping[present.Companion, set[str]],
) -> None:
    entry["stays"] += 1
    entry["hours"] += stay.duration_s / 3600
    entry["first"] = day if entry["first"] is None else min(entry["first"], day)
    entry["last"] = end_day if entry["last"] is None else max(entry["last"], end_day)
    entry["lines"].extend(_stay_lines(stay))
    for c in who:
        person = entry["people"].setdefault(
            (c.person, c.name), {"id": c.person, "name": c.name, "stays": 0, "days": set(), "lines": []}
        )
        person["stays"] += 1
        person["days"].update(who_days[c])
        person["lines"].extend(c.lines)


def _finish_visits(entry: dict[str, Any]) -> dict[str, Any]:
    people = sorted(entry["people"].values(), key=lambda p: (-len(p["days"]), p["name"]))
    return {
        **entry,
        "hours": round(entry["hours"], 1),
        "people": [{**p, "days": len(p["days"]), "lines": list(dict.fromkeys(p["lines"]))} for p in people],
    }


# -- people -------------------------------------------------------------------------------------------------


def people(reading: Reading) -> dict[str, Any]:
    """Per resolved person, per year: days together (days with confirmed company), the last real
    contact (the last such day), the places shared (named places, `aboard <asset>`, else the
    stay's coordinates), confirmed and proposed evidence counts, and the lines. Names that
    resolve to no person are listed apart, under `unresolved`."""
    years: dict[str, dict[str, Any]] = {}
    days_of = _days_of_lines(reading)
    for stay in reading.owner_stays:
        for c in present.present(stay, reading.lines, reading.identities):
            day = days_of.get(c.line, stay.start.astimezone(reading.tz).date().isoformat())
            year = years.setdefault(_year_of(day), {"year": _year_of(day), "people": {}, "unresolved": {}})
            bucket = year["people"] if c.person else year["unresolved"]
            entry = bucket.setdefault(
                c.person or c.name.casefold(),
                {
                    "id": c.person,
                    "name": c.name,
                    "days": set(),
                    "last_contact": None,
                    "places": [],
                    "confirmed": 0,
                    "proposed": 0,
                    "lines": [],
                },
            )
            entry["lines"].append(c.line)
            if c.status == present.CONFIRMED:
                entry["confirmed"] += 1
                entry["days"].add(day)
                entry["last_contact"] = (
                    day if entry["last_contact"] is None else max(entry["last_contact"], day)
                )
                where = _where(stay)
                if where not in entry["places"]:
                    entry["places"].append(where)
            else:
                entry["proposed"] += 1
    out = _head("people", reading)
    out["years"] = []
    for key in sorted(years):
        entry = years[key]
        out["years"].append(
            {
                "year": key,
                "people": [_finish_person(p) for p in sorted(entry["people"].values(), key=_person_order)],
                "unresolved": [
                    _finish_person(p) for p in sorted(entry["unresolved"].values(), key=_person_order)
                ],
            }
        )
    return out


def _person_order(p: dict[str, Any]) -> tuple[int, str, str]:
    return (-len(p["days"]), p["last_contact"] or "", p["name"])


def _finish_person(p: dict[str, Any]) -> dict[str, Any]:
    return {**p, "days": len(p["days"]), "lines": list(dict.fromkeys(p["lines"]))}


def _where(stay: stays.Segment) -> str:
    if stay.place:
        return stay.place
    if stay.aboard:
        return f"aboard {stay.aboard}"
    return f"{stay.lat:.4f},{stay.lon:.4f}" if stay.lat is not None and stay.lon is not None else "somewhere"


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The rollup as a few lines of text: one per year."""
    window = data["window"]
    yield f"{data['kind']} {window['since']} {EN_DASH} {window['until']}" if window["since"] else data["kind"]
    if data.get("warning"):
        yield f"  ({data['warning']})"
    if not data["years"]:
        yield "  nothing in the window"
        return
    for year in data["years"]:
        yield from _year_rows(data["kind"], year)
    if data["kind"] == "countries":
        yield f"  method: {data['method']}"


def _year_rows(kind: str, year: dict[str, Any]) -> Iterator[str]:
    if kind == "countries":
        parts = [f"{c['country']} {_plural(c['days'], 'day')}" for c in year["countries"]]
        parts.append(f"in transit {year['in_transit']['days']}")
        if year["unknown"]["days"]:
            parts.append(f"unknown {year['unknown']['days']}")
        yield f"  {year['year']}  {' · '.join(parts)}"
    elif kind == "flights":
        evidence = ", ".join(f"{k} {v}" for k, v in sorted(year["by_evidence"].items()))
        parts = [_plural(year["count"], "flight"), f"{year['km']:,} km", f"{year['long_haul']} long-haul"]
        if year["unmeasured"]:
            parts.append(f"{year['unmeasured']} unmeasured")
        parts.append(evidence)
        yield f"  {year['year']}  {' · '.join(parts)}"
        for f in year["flights"]:
            km = "" if f["km"] is None else f" · {f['km']:,} km"
            route = f"{f['from']} {ARROW} {f['to']}"
            yield f"        {f['date']}  {f['carrier']} {f['number']}  {route}{km} · {f['evidence']}"
    elif kind == "nights":
        parts = [f"{year['home']} home", f"{year['away']} away", f"{year['in_transit']} in transit"]
        for asset, n in sorted(year["aboard"].items()):
            parts.append(f"{_plural(n, 'night')} aboard {asset}")
        trip = year["longest_trip"]
        if trip:
            parts.append(
                f"longest trip {trip['start']} {EN_DASH} {trip['end']} ({_plural(trip['nights'], 'night')})"
            )
        yield f"  {year['year']}  {' · '.join(parts)}"
    elif kind == "places":
        yield f"  {year['year']}"
        for v in year["places"]:
            yield _visit_row(v["place"], v.get("kind"), v)
        for v in year["assets"]:
            name = f"{v['name']} ({v['asset']})" if v.get("name") else v["asset"]
            yield _visit_row(name, v.get("kind"), v, nights=v["nights"])
    else:
        yield f"  {year['year']}"
        for p in [*year["people"], *year["unresolved"]]:
            parts = [
                _plural(p["days"], "day"),
                f"last {p['last_contact']}" if p["last_contact"] else "never confirmed",
                ", ".join(p["places"]) if p["places"] else "nowhere",
                f"{p['confirmed']} confirmed, {p['proposed']} proposed",
            ]
            yield f"        {p['name']:<24} {' · '.join(parts)}"


def _visit_row(name: str, kind: str | None, v: dict[str, Any], nights: int | None = None) -> str:
    parts = [_plural(v["stays"], "stay"), f"{v['hours']:g} h", f"{v['first']} {EN_DASH} {v['last']}"]
    if nights is not None:
        parts.append(_plural(nights, "night"))
    if v["people"]:
        parts.append("with " + ", ".join(p["name"] for p in v["people"]))
    head = f"{name} ({kind})" if kind else name
    return f"        {head:<28} {' · '.join(parts)}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
