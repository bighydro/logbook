"""`logbook rollup <kind>`: the record summed up per year — countries, flights, nights, places,
people — from one reading of the window (`reading.read`), and per month or week — health — from
the health lines of the window. Every number carries, under `lines`, the ids of the lines it
came from: for a stay, the ids of its first and last location line (a stay is one unbroken run
of one subject's points, so the two ids name the run); for a flight, the flight line standing;
for a person, the lines that put them there; for a night's sleep, its stages. Readers derive and
never append (ADR 0013); the same record gives the same rollup."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from . import apps as app_table
from . import countries as country_table
from . import flights as flight_lines
from . import health as health_lines
from . import ledger, present, stays, trips
from . import places as named_places
from .chain import Line
from .export import day_range
from .index import local_date
from .reading import Reading, window_json
from .store import retractions

KINDS = ("countries", "flights", "nights", "places", "people", "money", "health", "attention")
PERIODS = ("month", "week")
YEAR = "year"  # attention's default period; health's is the month
APPS_TOP = 20  # the apps a period lists in text; the JSON has them all
LONG_HAUL_KM = 3500.0
EN_DASH = "\u2013"
EM_DASH = "\u2014"
ARROW = "\u2192"


def _year_of(day: str) -> str:
    return day[:4]


def _stay_lines(stay: stays.Segment | None) -> list[str]:
    if stay is None:
        return []
    return [id_ for id_ in (stay.first_line, stay.last_line) if id_]


def _head(kind: str, reading: Reading) -> dict[str, Any]:
    return {"kind": kind, "window": window_json(reading)}


def empty(kind: str, by: str | None = None) -> dict[str, Any]:
    """The rollup of a record with no lines."""
    window: dict[str, Any] = {"since": None, "until": None, "days": []}
    if kind == "health":
        return {"kind": kind, "window": window, "by": by or "month", "periods": []}
    if kind == "attention":
        return {
            "kind": kind,
            "window": window,
            "by": by or YEAR,
            "categories": list(app_table.CATEGORIES),
            "periods": [],
        }
    return {"kind": kind, "window": window, "years": []}


# -- countries --------------------------------------------------------------------------------------------


def countries(reading: Reading, table: country_table.Countries | None = None) -> dict[str, Any]:
    """Days per country per year from the overnight stay's position (aboard an asset, where it
    lay for the longest part of the night); in-transit nights and nights whose country is unknown
    listed separately. The method is reported with the numbers."""
    table = table or country_table.Countries.load()
    years: dict[str, dict[str, Any]] = {}
    for night in reading.nights:
        year = years.setdefault(
            _year_of(night.day),
            {"year": _year_of(night.day), "countries": {}, "in_transit": _bucket(), "unknown": _bucket()},
        )
        position = night.position
        if night.stay is None or position is None:
            _count(year["in_transit"], night.day, [])
            continue
        found = country_table.country_of(position[0], position[1], reading.places, reading.airports, table)
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

UNNAMED_TOP = 5  # the unnamed clusters a year lists, by hours


def places(reading: Reading, with_table: bool = False) -> dict[str, Any]:
    """Per named place (places.json), per year: stays, hours, nights (the days whose overnight stay
    is there), first and last visit, and the people confirmed present through the with module,
    each with their stays, days and nights there. Then `aboard`, per asset (assets.json), the same
    way: a stay aboard is one run of the owner's stays and moves aboard it (`stays.fold`), however
    the asset moved inside it, its hours the run's whole span, its nights the nights whose
    overnight stay was aboard. Then the top `UNNAMED_TOP` unnamed clusters — the owner's stays at
    no named place, the berths and anchorages inside a stay aboard among them, grouped as `places
    propose` groups them and ranked by hours — the same way, each under the stay id `places name`
    takes; a night aboard counts at the anchorage the asset lay at. The stays come from one
    derivation of the window and the company of each from the evidence of its days
    (`present.Evidence`); nothing is read per place. `with_table` adds the place × person table
    under `with`."""
    years: dict[str, dict[str, Any]] = {}
    evidence = present.Evidence(reading.lines, reading.tz)
    days_of = _days_of_lines(reading)
    company: dict[str, _Company] = {}
    stay_year: dict[str, str] = {}
    unnamed_stays: dict[str, list[stays.Segment]] = {}

    def year_and_company(stay: stays.Segment) -> tuple[dict[str, Any], str, str]:
        day, end_day = _local_days(stay, reading)
        key = _year_of(day)
        year = years.setdefault(key, {"year": key, "places": {}, "aboard": {}, "unnamed": {}})
        who = [
            c
            for c in present.company(
                stay, evidence.near(stay), reading.identities, reading.places, reading.owner
            )
            if c.status == present.CONFIRMED
        ]
        company[stay.id] = _Company(who, {c: {days_of.get(id_, day) for id_ in c.lines} for c in who})
        stay_year[stay.id] = key
        return year, day, end_day

    for stay in reading.owner_stays:
        year, day, end_day = year_and_company(stay)
        if stay.place is not None:
            place = next((p for p in reading.places if p.name == stay.place), None)
            entry = year["places"].setdefault(
                stay.place,
                {"place": stay.place, "kind": place.kind if place else None, **_visits(), "nights": 0},
            )
            _visit(entry, stay, day, end_day, company[stay.id])
        elif stay.lat is not None and stay.lon is not None:
            unnamed_stays.setdefault(stay_year[stay.id], []).append(stay)
    for stay in reading.derived.folded:
        if stay.kind != stays.STAY or stay.aboard is None or not stay.inside:
            continue
        year, day, end_day = year_and_company(stay)
        asset = reading.assets.get(stay.aboard)
        entry = year["aboard"].setdefault(
            stay.aboard,
            {
                "asset": stay.aboard,
                "name": asset.name if asset else None,
                "kind": asset.kind if asset else None,
                **_visits(),
                "nights": 0,
            },
        )
        _visit(entry, stay, day, end_day, company[stay.id])
    cluster_of = _unnamed(years, unnamed_stays, company, reading)
    for night in reading.nights:
        slept, lay = night.stay, night.innermost
        if slept is None or lay is None:
            continue
        if slept.aboard is not None and slept.id in company:
            _night(years[stay_year[slept.id]]["aboard"][slept.aboard], night.day, company[slept.id])
        if lay.id not in company:
            continue  # a passage the owner was aboard for: it is at no place
        year = years[stay_year[lay.id]]
        found = company[lay.id]
        if lay.place is not None:
            _night(year["places"][lay.place], night.day, found)
        elif lay.id in cluster_of:
            _night(cluster_of[lay.id], night.day, found)
    out = _head("places", reading)
    out["unnamed_top"] = UNNAMED_TOP
    out["years"] = []
    for key in sorted(years):
        entry = years[key]
        year_out = {
            "year": key,
            "places": [
                _finish_visits(v) for v in sorted(entry["places"].values(), key=lambda v: -v["hours"])
            ],
            "aboard": [
                _finish_visits(v) for v in sorted(entry["aboard"].values(), key=lambda v: -v["hours"])
            ],
            "unnamed": [
                _finish_visits(v) for v in sorted(entry["unnamed"].values(), key=lambda v: -v["hours"])
            ],
        }
        if with_table:
            year_out["with"] = _with_rows(year_out)
        out["years"].append(year_out)
    return out


@dataclass(frozen=True)
class _Company:
    """The people confirmed at one stay, and the local days each one's evidence is dated."""

    who: list[present.Companion]
    days: Mapping[present.Companion, set[str]]


def _local_days(stay: stays.Segment, reading: Reading) -> tuple[str, str]:
    return (
        stay.start.astimezone(reading.tz).date().isoformat(),
        stay.end.astimezone(reading.tz).date().isoformat(),
    )


def _unnamed(
    years: Mapping[str, dict[str, Any]],
    unnamed_stays: Mapping[str, Sequence[stays.Segment]],
    company: Mapping[str, _Company],
    reading: Reading,
) -> dict[str, dict[str, Any]]:
    """Fill each year's `unnamed` with its top clusters and return stay id → cluster entry for the
    stays those clusters hold. The grouping is `places.propose`'s (within `GROUP_M` of a group's
    first stay, ranked by hours) with no timeline visits, so a cluster here is the proposal there."""
    cluster_of: dict[str, dict[str, Any]] = {}
    for key, found in unnamed_stays.items():
        by_id = {s.id: s for s in found}
        proposals = named_places.propose(
            [
                named_places.Stay(
                    s.id,
                    s.start,
                    s.end,
                    s.lat or 0.0,
                    s.lon or 0.0,
                    s.aboard,
                    s.first_line,
                    s.last_line,
                    s.points,
                )
                for s in found
            ],
            reading.places,
            [],
        )
        for proposal in proposals[:UNNAMED_TOP]:
            near = proposal.nearest
            entry: dict[str, Any] = {
                "id": proposal.id,
                "lat": round(proposal.lat, 6),
                "lon": round(proposal.lon, 6),
                "label": unnamed_label(proposal.lat, proposal.lon, proposal.aboard, reading),
                "aboard": proposal.aboard,
                "nearest": None
                if near is None
                else {"name": near[0].name, "kind": near[0].kind, "metres": round(near[1])},
                "city": trips.city_near(proposal.lat, proposal.lon, reading.airports),
                **_visits(),
                "nights": 0,
            }
            for member in proposal.stays:
                stay = by_id[member.id]
                day, end_day = _local_days(stay, reading)
                _visit(entry, stay, day, end_day, company[stay.id])
                cluster_of[stay.id] = entry
            years[key]["unnamed"][proposal.id] = entry
    return cluster_of


def unnamed_label(lat: float, lon: float, aboard: str | None, reading: Reading) -> str:
    """How an unnamed place reads: its coordinates; `aboard <asset>` when it is; `near <place>,
    x km` for a named place within `trips.NEAR_KM`; else the city of the nearest large airport in
    parentheses, the `trips` route's rule."""
    label = f"{lat:.4f},{lon:.4f}"
    if aboard:
        label += f" aboard {aboard}"
    near = named_places.nearest(lat, lon, reading.places)
    if near is not None and near[1] <= trips.NEAR_KM * 1000:
        return f"{label} near {near[0].name}, {near[1] / 1000:.1f} km"
    city = trips.city_near(lat, lon, reading.airports)
    return f"{label} ({city})" if city else label


def _visits() -> dict[str, Any]:
    return {"stays": 0, "hours": 0.0, "first": None, "last": None, "people": {}, "lines": []}


def _days_of_lines(reading: Reading) -> dict[str, str]:
    """line id → its local day, for the evidence lines a companion rests on."""
    return {
        str(line["id"]): reading.day_of(line)
        for line in reading.lines
        if line.get("kind") in present.EVIDENCE_KINDS
    }


def _visit(entry: dict[str, Any], stay: stays.Segment, day: str, end_day: str, found: _Company) -> None:
    entry["stays"] += 1
    entry["hours"] += stay.duration_s / 3600
    entry["first"] = day if entry["first"] is None else min(entry["first"], day)
    entry["last"] = end_day if entry["last"] is None else max(entry["last"], end_day)
    entry["lines"].extend(_stay_lines(stay))
    for c in found.who:
        person = _person_at(entry, c)
        person["stays"] += 1
        person["days"].update(found.days[c])
        person["lines"].extend(c.lines)


def _night(entry: dict[str, Any], day: str, found: _Company) -> None:
    """One night at the entry's place; and one for each person whose evidence there is dated the
    night's day — a dinner on the 16th is the night of the 16th together, not every night of the
    stay."""
    entry["nights"] += 1
    for c in found.who:
        if day in found.days[c]:
            _person_at(entry, c)["nights"] += 1


def _person_at(entry: dict[str, Any], c: present.Companion) -> dict[str, Any]:
    person: dict[str, Any] = entry["people"].setdefault(
        (c.person, c.name),
        {"id": c.person, "name": c.name, "stays": 0, "days": set(), "nights": 0, "lines": []},
    )
    return person


def _finish_visits(entry: dict[str, Any]) -> dict[str, Any]:
    people = sorted(entry["people"].values(), key=lambda p: (-len(p["days"]), p["name"]))
    return {
        **entry,
        "hours": round(entry["hours"], 1),
        "people": [{**p, "days": len(p["days"]), "lines": list(dict.fromkeys(p["lines"]))} for p in people],
    }


def _with_rows(year: dict[str, Any]) -> list[dict[str, Any]]:
    """The place × person table of one year: a row per person per place, the places in the order
    the rollup lists them (named, aboard, unnamed), the people by days there."""
    rows: list[dict[str, Any]] = []
    for kind, key, entries in (
        ("place", "place", year["places"]),
        ("asset", "asset", year["aboard"]),
        ("unnamed", "id", year["unnamed"]),
    ):
        for entry in entries:
            for p in entry["people"]:
                rows.append(
                    {
                        "place": entry[key],
                        "label": _entry_label(kind, entry),
                        "kind": kind,
                        "id": p["id"],
                        "name": p["name"],
                        "stays": p["stays"],
                        "days": p["days"],
                        "nights": p["nights"],
                        "lines": p["lines"],
                    }
                )
    return rows


def _entry_label(kind: str, entry: dict[str, Any]) -> str:
    if kind == "place":
        return str(entry["place"])
    if kind == "asset":
        return f"{entry['name']} ({entry['asset']})" if entry.get("name") else str(entry["asset"])
    return str(entry["label"])


# -- people -------------------------------------------------------------------------------------------------


def people(reading: Reading) -> dict[str, Any]:
    """Per resolved person, per year, from the confirmed set of the with module only — a timed
    calendar entry's attendee, a transcript's speaker, a note's `with <name>`; never the owner,
    and a proposal (a tagged face, an all-day entry's attendee) is not a day together: days
    together (days with confirmed evidence, by the evidence's own day), nights together (nights
    whose overnight stay the person was confirmed at on that day), the stays shared, the last real
    contact (the last such day), the places shared (named places, `aboard <asset>`, else the
    unnamed place's label), the confirmed evidence count and the lines. A confirmed name the
    record resolves to no person (an attendee with a display name and no resolution line) is
    listed apart, under `unresolved`."""
    years: dict[str, dict[str, Any]] = {}
    evidence = present.Evidence(reading.lines, reading.tz)
    days_of = _days_of_lines(reading)
    at_stay: dict[str, dict[tuple[str, str], set[str]]] = {}  # stay id → (year, key) → evidence days
    for stay in reading.owner_stays:
        stay_day, _end_day = _local_days(stay, reading)
        found = present.present(stay, evidence.near(stay), reading.identities, reading.places, reading.owner)
        for c in found:
            if c.status != present.CONFIRMED:
                continue
            day = days_of.get(c.line, stay_day)
            year = years.setdefault(_year_of(day), {"year": _year_of(day), "people": {}, "unresolved": {}})
            bucket = year["people"] if c.person else year["unresolved"]
            key = c.person or c.name.casefold()
            entry = bucket.setdefault(
                key,
                {
                    "id": c.person,
                    "name": c.name,
                    "days": set(),
                    "nights": 0,
                    "stays": set(),
                    "last_contact": None,
                    "places": [],
                    "confirmed": 0,
                    "lines": [],
                },
            )
            entry["lines"].append(c.line)
            entry["confirmed"] += 1
            entry["days"].add(day)
            entry["stays"].add(stay.id)
            entry["last_contact"] = day if entry["last_contact"] is None else max(entry["last_contact"], day)
            where = _where(stay, reading)
            if where not in entry["places"]:
                entry["places"].append(where)
            at_stay.setdefault(stay.id, {}).setdefault((_year_of(day), key), set()).add(day)
    for night in reading.nights:
        lay = night.innermost  # the night's place: the inner stay of a night aboard, else the stay
        if lay is None:
            continue
        for (year_key, key), days in at_stay.get(lay.id, {}).items():
            if night.day not in days:
                continue
            year = years[year_key]
            entry = year["people"].get(key) or year["unresolved"].get(key)
            if entry is not None:
                entry["nights"] += 1
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
    return {**p, "days": len(p["days"]), "stays": len(p["stays"]), "lines": list(dict.fromkeys(p["lines"]))}


def _where(stay: stays.Segment, reading: Reading) -> str:
    if stay.place:
        return stay.place
    if stay.aboard:
        return f"aboard {stay.aboard}"
    if stay.lat is None or stay.lon is None:
        return "somewhere"
    return unnamed_label(stay.lat, stay.lon, None, reading)


# -- health -------------------------------------------------------------------------------------------------


def health(lines: Iterable[Line], tz: str, first: str, last: str, by: str = "month") -> dict[str, Any]:
    """Sleep, steps, resting heart rate and HRV per calendar month or ISO week of the window
    `[first, last]`, from the day rows of `health.summary` (RFC 0014 rules 4 and 5; a correction
    that `supersedes` a line wins, the latest when there are several; a retracted line is out;
    units as stored, a resting rate in count/s read in bpm). `lines` are the health lines whose
    local day is in the window or the day before it (the night that ends on the first day starts
    then), with the retraction lines beside them. Per period: `sleep` the mean of the nights'
    hours and how many nights had a line; `steps` the mean of the days' counts and how many days;
    `resting_hr` the mean, lowest and highest of the days' resting rates in bpm and how many days;
    `hrv` the mean of the days' SDNN in ms and how many days. Every period the window touches is
    listed, and a field no day of it has a line for is None — never a zero."""
    if by not in PERIODS:
        raise ValueError(f"--by is month or week, not {by!r}")
    days = day_range(first, last)
    rows = {row["day"]: row for row in health_lines.summary(lines, tz) if first <= row["day"] <= last}
    periods: dict[str, dict[str, Any]] = {}
    for day in days:
        key = _period(day, by)
        entry = periods.setdefault(key, {"period": key, "first": day, "last": day, "rows": []})
        entry["last"] = day
        if day in rows:
            entry["rows"].append(rows[day])
    out: dict[str, Any] = {
        "kind": "health",
        "window": {"since": first, "until": last, "days": days},
        "by": by,
        "periods": [],
    }
    for entry in periods.values():
        found: list[dict[str, Any]] = entry.pop("rows")
        out["periods"].append({**entry, **health_summary(found)})
    return out


def health_summary(found: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One period's `sleep`, `steps`, `resting_hr` and `hrv` over the day rows of `health.summary`
    it holds (the rule above); a field no row has a value for is None. The trip page sums a trip's
    span with it."""
    return {
        "sleep": _mean_of(found, "sleep_h", "mean_h", "nights", 1),
        "steps": _mean_of(found, "steps", "mean", "days"),
        "resting_hr": _spread_of(found, "resting_hr"),
        "hrv": _mean_of(found, "hrv", "mean_ms", "days"),
    }


def _period(day: str, by: str) -> str:
    """`2026` for a year; `2026-06` for a month; `2026-W23` for an ISO week (the year is the ISO
    year, so the first days of January can belong to the old year's last week)."""
    if by == YEAR:
        return day[:4]
    if by == "month":
        return day[:7]
    year, week, _weekday = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


# -- attention ----------------------------------------------------------------------------------------------


def attention(
    lines: Iterable[Line],
    tz: str,
    first: str,
    last: str,
    by: str | None = None,
    table: app_table.Apps | None = None,
) -> dict[str, Any]:
    """Hours by app and by category per year (`by` None), calendar month or ISO week of the window
    `[first, last]`, from the `app-use` lines standing: a retracted line is out, and so is one
    another app-use line `supersedes`. `lines` are the app-use lines whose local day is in the
    window, with the retraction lines beside them. An app is its bundle id (the Mac's Safari and the
    phone's are two rows); its name is the owner's (`policy/apps.json`), else the built-in table's,
    else what the line itself carries; its category the owner's, else the built-in table's, else a
    hint in the id, else `other` (`apps.Apps`). A line's seconds are its `extra.duration_s`, else
    its span. Every period the window touches is listed; one with no line has no categories and no
    apps, never a zero per category; a period with lines carries every category, a category no app
    of the period falls in at zero."""
    if by is not None and by not in PERIODS:
        raise ValueError(f"--by is month or week, not {by!r}")
    by = by or YEAR
    table = table or app_table.Apps()
    days = day_range(first, last)
    periods: dict[str, dict[str, Any]] = {}
    for day in days:
        key = _period(day, by)
        entry = periods.setdefault(key, {"period": key, "first": day, "last": day, "apps": {}})
        entry["last"] = day
    for line in _app_use_standing(lines):
        payload = line["payload"]
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        bundle_id = str(extra.get("bundle_id") or payload.get("title") or "")
        if not bundle_id:
            continue
        day = local_date(str(line["at"]), tz)
        if not first <= day <= last:
            continue
        seconds = _seconds(line, extra)
        if seconds <= 0:
            continue
        device = str(extra.get("device") or "unknown")
        app: dict[str, Any] = periods[_period(day, by)]["apps"].setdefault(
            bundle_id,
            {
                "bundle_id": bundle_id,
                "named": None,
                "seconds": 0,
                "sessions": 0,
                "devices": Counter(),
                "lines": [],
            },
        )
        app["seconds"] += seconds
        app["sessions"] += 1
        app["devices"][device] += seconds
        app["lines"].append(str(line["id"]))
        if app["named"] is None and isinstance(extra.get("app"), str) and extra["app"]:
            app["named"] = extra["app"]
    out: dict[str, Any] = {
        "kind": "attention",
        "window": {"since": first, "until": last, "days": days},
        "by": by,
        "categories": list(app_table.CATEGORIES),
        "periods": [_attention_period(entry, table) for entry in periods.values()],
    }
    return out


def _app_use_standing(lines: Iterable[Line]) -> list[Line]:
    """The app-use lines standing: not retracted, not superseded by another app-use line."""
    found = list(lines)
    retracted = retractions(found)
    kept = [line for line in found if line.get("kind") == app_table.KIND and str(line["id"]) not in retracted]
    superseded = {
        str(line["payload"]["supersedes"])
        for line in kept
        if isinstance(line["payload"].get("supersedes"), str)
    }
    return [line for line in kept if str(line["id"]) not in superseded]


def _seconds(line: Line, extra: Mapping[str, Any]) -> int:
    duration = extra.get("duration_s")
    if isinstance(duration, int | float) and not isinstance(duration, bool):
        return int(duration)
    start, end = stays.instant(line.get("at")), stays.instant(line.get("end"))
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds())


def _attention_period(entry: dict[str, Any], table: app_table.Apps) -> dict[str, Any]:
    found: dict[str, dict[str, Any]] = entry.pop("apps")
    apps_out = []
    for app in sorted(found.values(), key=lambda a: (-a["seconds"], a["bundle_id"])):
        bundle_id = app["bundle_id"]
        apps_out.append(
            {
                "bundle_id": bundle_id,
                "app": table.name(bundle_id) or app["named"],
                "category": table.category(bundle_id),
                "hours": _hours(app["seconds"]),
                "seconds": app["seconds"],
                "sessions": app["sessions"],
                "devices": dict(app["devices"]),
                "lines": app["lines"],
            }
        )
    total = sum(a["seconds"] for a in apps_out)
    by_category: dict[str, Any] | None = None
    if apps_out:
        by_category = {}
        for category in app_table.CATEGORIES:
            seconds = sum(a["seconds"] for a in apps_out if a["category"] == category)
            by_category[category] = {"hours": _hours(seconds), "seconds": seconds}
    return {**entry, "hours": _hours(total), "seconds": total, "by_category": by_category, "apps": apps_out}


def _hours(seconds: int) -> float:
    return round(seconds / 3600, 1)


def _values(found: Sequence[dict[str, Any]], field: str) -> tuple[list[float], list[str]]:
    rows = [row for row in found if row[field] is not None]
    return [float(row[field]) for row in rows], [id_ for row in rows for id_ in row["by"][field]]


def _mean_of(
    found: Sequence[dict[str, Any]], field: str, mean: str, count: str, decimals: int = 0
) -> dict[str, Any] | None:
    values, ids = _values(found, field)
    if not values:
        return None
    average = sum(values) / len(values)
    return {mean: round(average, decimals) if decimals else round(average), count: len(values), "lines": ids}


def _spread_of(found: Sequence[dict[str, Any]], field: str) -> dict[str, Any] | None:
    values, ids = _values(found, field)
    if not values:
        return None
    return {
        "mean": round(sum(values) / len(values)),
        "min": round(min(values)),
        "max": round(max(values)),
        "days": len(values),
        "lines": ids,
    }


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The rollup as a few lines of text: one per year, or per period for health."""
    window = data["window"]
    head = data["kind"]
    if window["since"]:
        head = f"{head} {window['since']} {EN_DASH} {window['until']}"
    if data["kind"] in ("health", "attention"):
        yield f"{head} · by {data['by']}"
        if not data["periods"]:
            yield "  nothing in the window"
        for period in data["periods"]:
            if data["kind"] == "health":
                yield _period_row(period)
            else:
                yield from _attention_rows(period)
        return
    if data["years"] and "with" in data["years"][0]:
        head += " · with"
    yield head
    if data.get("warning"):
        yield f"  ({data['warning']})"
    if not data["years"]:
        yield "  nothing in the window"
        return
    for year in data["years"]:
        yield from _year_rows(data["kind"], year)
    if data["kind"] == "countries":
        yield f"  method: {data['method']}"


def _period_row(period: dict[str, Any]) -> str:
    """One period: `sleep 6.5 h (2 nights) · 2,125 steps (2 days) · resting 57 bpm (54 to 60, 2 days)
    · hrv 45 ms (1 day)`, the range with an en dash; a field with no line is an em dash, never a zero."""
    sleep, steps, resting, hrv = (period[k] for k in ("sleep", "steps", "resting_hr", "hrv"))
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
    return f"  {period['period']}  {' · '.join(parts)}"


def _attention_rows(period: dict[str, Any]) -> Iterator[str]:
    """One period: the hours with every category's share, then the apps by hours (`APPS_TOP` at
    most, the rest counted); a period with no line is an em dash."""
    if period["by_category"] is None:
        yield f"  {period['period']}  {EM_DASH}"
        return
    shares = " · ".join(f"{c} {v['hours']:.1f} h" for c, v in period["by_category"].items())
    yield f"  {period['period']}  {period['hours']:.1f} h · {shares}"
    shown = period["apps"][:APPS_TOP]
    width = max(24, *(len(a["app"] or a["bundle_id"]) for a in shown)) if shown else 24
    for a in shown:
        parts = [f"{a['hours']:.1f} h", a["category"], _plural(a["sessions"], "session"), a["bundle_id"]]
        yield f"        {a['app'] or a['bundle_id']:<{width}} {' · '.join(parts)}"
    rest = len(period["apps"]) - len(shown)
    if rest > 0:
        yield f"        +{_plural(rest, 'more app')}"


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
            name = f"{f['carrier']} {f['number']}  " if f["number"] else ""
            yield f"        {f['date']}  {name}{route}{km} · {f['evidence']}"
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
    elif kind == "money":
        yield from ledger.rollup_rows(year)
    elif kind == "places" and "with" in year:
        yield f"  {year['year']}"
        yield from _with_table(year["with"])
    elif kind == "places":
        yield f"  {year['year']}"
        heads = [
            *(_entry_head(v["place"], v.get("kind")) for v in year["places"]),
            *(_entry_head(_entry_label("asset", v), v.get("kind")) for v in year["aboard"]),
            *(v["label"] for v in year["unnamed"]),
        ]
        width = max(28, *(len(h) for h in heads)) if heads else 28
        for v in year["places"]:
            yield _visit_row(_entry_head(v["place"], v.get("kind")), v, width, nights=v["nights"] or None)
        if year["aboard"]:
            yield "        aboard, by hours (a stay is one run aboard, whatever the asset did inside it):"
        for v in year["aboard"]:
            yield _visit_row(
                _entry_head(_entry_label("asset", v), v.get("kind")), v, width, nights=v["nights"]
            )
        if year["unnamed"]:
            yield "        unnamed, by hours (the ids `places name` takes):"
        for v in year["unnamed"]:
            yield _visit_row(v["label"], v, width, nights=v["nights"] or None) + f"   {v['id']}"
    else:
        yield f"  {year['year']}"
        for p in [*year["people"], *year["unresolved"]]:
            parts = [
                _plural(p["days"], "day"),
                _plural(p["nights"], "night"),
                f"last {p['last_contact']}",
                ", ".join(p["places"]) if p["places"] else "nowhere",
                f"{p['confirmed']} confirmed",
            ]
            yield f"        {p['name']:<24} {' · '.join(parts)}"


def _entry_head(name: str, kind: str | None) -> str:
    return f"{name} ({kind})" if kind else name


def _visit_row(head: str, v: dict[str, Any], width: int, nights: int | None = None) -> str:
    parts = [_plural(v["stays"], "stay"), f"{v['hours']:g} h", f"{v['first']} {EN_DASH} {v['last']}"]
    if nights is not None:
        parts.insert(0, _plural(nights, "night"))
    if v["people"]:
        parts.append("with " + ", ".join(p["name"] for p in v["people"]))
    return f"        {head:<{width}} {' · '.join(parts)}"


def _with_table(table: Sequence[dict[str, Any]]) -> Iterator[str]:
    if not table:
        yield "        nobody confirmed at any place"
        return
    width = max(28, *(len(r["label"]) for r in table))
    yield f"        {'place':<{width}} {'person':<24} {'stays':>5} {'days':>5} {'nights':>6}"
    for r in table:
        yield f"        {r['label']:<{width}} {r['name']:<24} {r['stays']:>5} {r['days']:>5} {r['nights']:>6}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
