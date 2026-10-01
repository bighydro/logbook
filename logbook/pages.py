"""The pages: `logbook show person|asset|place <name>`, read from the whole record.

A person page is the arc of a relationship: first and last contact, days together per year, the
places shared, the open commitments (a placeholder until `commitment/v1` lines are read) and the
last ten stays shared. An asset page: the trips aboard, the nights aboard, the people aboard, and
the summary of the asset's own track (its AIS or ADS-B positions as stays and moves) when the
record holds one. A place page: visits, hours, first and last, per year, the people met there,
the photos taken there (photo lines inside a stay at the place), the last visits. All of it is
derived from one reading of the record (`reading.read`) through the stays, the with module and
the trips; nothing is written."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import present, stays, trips
from .reading import Reading
from .resolve import Identity, Ref

LAST_STAYS = 10
EN_DASH = "\u2013"
COMMITMENTS_NOTE = "open commitments wait for a reader of commitment/v1 lines (RFC 0007); none are read yet"


class PageError(ValueError):
    """The page's subject is not in the record."""


# -- person -------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Who:
    entity: str
    label: str
    refs: tuple[Ref, ...]


def find_person(name: str, identities: Mapping[Ref, Identity]) -> Who:
    """The person `name` means: an entity id, a label (case aside), or a unique first name.
    PageError when nobody or several."""
    people: dict[str, tuple[str, list[Ref]]] = {}
    for ref, who in identities.items():
        if who.entity and who.type in present.PERSON_TYPES:
            people.setdefault(who.entity, (who.label or who.entity, []))[1].append(ref)
    wanted = " ".join(name.split()).casefold()
    if name in people:
        return Who(name, people[name][0], tuple(people[name][1]))
    exact = [e for e, (label, _) in people.items() if " ".join(label.split()).casefold() == wanted]
    loose = [e for e, (label, _) in people.items() if label.split()[0].casefold() == wanted.split(" ")[0]]
    found = exact if len(exact) == 1 else loose if len(loose) == 1 and not exact else []
    if not found:
        if len(exact) > 1 or len(loose) > 1:
            raise PageError(
                f"{name!r} names several people: {', '.join(people[e][0] for e in exact or loose)}"
            )
        raise PageError(f"{name!r} is nobody the record's resolution lines name")
    [entity] = found
    return Who(entity, people[entity][0], tuple(people[entity][1]))


def person(reading: Reading, name: str) -> dict[str, Any]:
    who = find_person(name, reading.identities)
    days_of = _days_of_lines(reading)
    shared: list[dict[str, Any]] = []
    days: set[str] = set()
    places: list[str] = []
    proposed = 0
    for stay in reading.owner_stays:
        proposed += sum(
            1
            for p in present.present(stay, reading.lines, reading.identities, reading.places)
            if p.person == who.entity and p.status == present.PROPOSED
        )
        for c in present.company(stay, reading.lines, reading.identities, reading.places):
            if c.person != who.entity:
                continue
            evidence_days = {days_of.get(id_, _day(stay, reading)) for id_ in c.lines}
            if c.status == present.CONFIRMED:
                days |= evidence_days
                where = _where(stay)
                if where not in places:
                    places.append(where)
            shared.append(
                {
                    "stay": stay.id,
                    "start": stays.instant_text(stay.start),
                    "end": stays.instant_text(stay.end),
                    "day": _day(stay, reading),
                    "where": _where(stay),
                    "status": c.status,
                    "confidence": c.confidence,
                    "sources": list(c.sources),
                    "reasons": list(c.reasons),
                    "lines": list(c.lines),
                }
            )
    shared.sort(key=lambda s: s["start"], reverse=True)
    by_year = Counter(day[:4] for day in days)
    return {
        "page": "person",
        "id": who.entity,
        "name": who.label,
        "refs": [{"kind": k, "value": v} for k, v in who.refs],
        "first_contact": min(days) if days else None,
        "last_contact": max(days) if days else None,
        "days_together": dict(sorted(by_year.items())),
        "places": places,
        "proposed": proposed,
        "commitments": {"open": [], "note": COMMITMENTS_NOTE},
        "shared_stays": shared[:LAST_STAYS],
        "stays": len(shared),
        "lines": list(dict.fromkeys(id_ for s in shared for id_ in s["lines"])),
    }


# -- asset --------------------------------------------------------------------------------------------------


def asset(reading: Reading, asset_id: str) -> dict[str, Any]:
    registered = reading.assets.get(asset_id)
    if registered is None:
        raise PageError(f"{asset_id!r} is not in assets.json; `logbook assets list`")
    found, _warning = trips.trips(reading)
    aboard = [s for s in reading.owner_stays if s.aboard == asset_id]
    people = _people(aboard, reading)
    nights = sum(1 for n in reading.nights if n.stay is not None and n.stay.aboard == asset_id)
    own = [s for s in reading.segments if s.subject == asset_id]
    track = None
    if own:
        moves = [s for s in own if s.kind == stays.MOVE]
        track = {
            "points": sum(s.points for s in own if s.kind != stays.MOVE),
            "stays": sum(1 for s in own if s.kind == stays.STAY),
            "stops": sum(1 for s in own if s.kind == stays.STOP),
            "moves": len(moves),
            "distance_m": round(sum(s.distance_m or 0 for s in moves)),
            "first": stays.instant_text(own[0].start),
            "last": stays.instant_text(own[-1].end),
            "lines": [id_ for id_ in (own[0].first_line, own[-1].last_line) if id_],
        }
    return {
        "page": "asset",
        "id": asset_id,
        "name": registered.name,
        "kind": registered.kind,
        "trips": [t.to_json() for t in found if t.asset == asset_id],
        "nights": nights,
        "stays_aboard": len(aboard),
        "hours_aboard": round(sum(s.duration_s for s in aboard) / 3600, 1),
        "people": people,
        "track": track,
        "lines": list(dict.fromkeys(id_ for s in aboard for id_ in _stay_lines(s))),
    }


# -- place --------------------------------------------------------------------------------------------------


def place(reading: Reading, name: str) -> dict[str, Any]:
    wanted = next((p for p in reading.places if p.name.casefold() == name.strip().casefold()), None)
    if wanted is None:
        raise PageError(f"{name!r} is not in places.json; `logbook places list`")
    visits = [s for s in reading.owner_stays if s.place == wanted.name]
    photos = [line for line in reading.of_kind("photo") if _inside_any(line, visits)]
    by_year: dict[str, dict[str, Any]] = {}
    for s in visits:
        year = by_year.setdefault(_day(s, reading)[:4], {"visits": 0, "hours": 0.0})
        year["visits"] += 1
        year["hours"] += s.duration_s / 3600
    last = sorted(visits, key=lambda s: s.start, reverse=True)[:LAST_STAYS]
    return {
        "page": "place",
        "name": wanted.name,
        "kind": wanted.kind,
        "tags": list(wanted.tags),
        "lat": wanted.lat,
        "lon": wanted.lon,
        "radius_m": wanted.radius_m,
        "visits": len(visits),
        "hours": round(sum(s.duration_s for s in visits) / 3600, 1),
        "first": _day(visits[0], reading) if visits else None,
        "last": max(_end_day(s, reading) for s in visits) if visits else None,
        "by_year": {
            y: {"visits": v["visits"], "hours": round(v["hours"], 1)} for y, v in sorted(by_year.items())
        },
        "people": _people(visits, reading),
        "photos": len(photos),
        "photo_lines": [str(line["id"]) for line in photos],
        "last_visits": [
            {
                "stay": s.id,
                "start": stays.instant_text(s.start),
                "end": stays.instant_text(s.end),
                "day": _day(s, reading),
                "hours": round(s.duration_s / 3600, 1),
                "aboard": s.aboard,
                "lines": _stay_lines(s),
            }
            for s in last
        ],
        "lines": [id_ for s in visits for id_ in _stay_lines(s)],
    }


# -- helpers ----------------------------------------------------------------------------------------------


def _inside_any(line: Mapping[str, Any], visits: Sequence[stays.Segment]) -> bool:
    at = stays.instant(line.get("at"))
    return at is not None and any(s.start <= at <= s.end for s in visits)


def _day(stay: stays.Segment, reading: Reading) -> str:
    return stay.start.astimezone(reading.tz).date().isoformat()


def _end_day(stay: stays.Segment, reading: Reading) -> str:
    return stay.end.astimezone(reading.tz).date().isoformat()


def _where(stay: stays.Segment) -> str:
    if stay.place:
        return stay.place
    if stay.aboard:
        return f"aboard {stay.aboard}"
    return f"{stay.lat:.4f},{stay.lon:.4f}" if stay.lat is not None and stay.lon is not None else "somewhere"


def _stay_lines(stay: stays.Segment) -> list[str]:
    return [id_ for id_ in (stay.first_line, stay.last_line) if id_]


def _days_of_lines(reading: Reading) -> dict[str, str]:
    return {str(line["id"]): reading.day_of(line) for line in reading.lines if line.get("kind") in EVIDENCE}


EVIDENCE = ("event", "transcript", "note", "photo")


def _people(visits: Sequence[stays.Segment], reading: Reading) -> list[dict[str, Any]]:
    """The people confirmed present across `visits`, with their days and lines, most days first."""
    days_of = _days_of_lines(reading)
    found: dict[tuple[str | None, str], dict[str, Any]] = {}
    for stay in visits:
        for c in present.company(stay, reading.lines, reading.identities, reading.places):
            if c.status != present.CONFIRMED:
                continue
            entry = found.setdefault(
                (c.person, "" if c.person else c.name.casefold()),
                {"id": c.person, "name": c.name, "days": set(), "lines": []},
            )
            entry["days"].update(days_of.get(id_, _day(stay, reading)) for id_ in c.lines)
            entry["lines"].extend(c.lines)
    people = [{**e, "days": len(e["days"]), "lines": list(dict.fromkeys(e["lines"]))} for e in found.values()]
    return sorted(people, key=lambda p: (-p["days"], p["name"]))


# -- text ----------------------------------------------------------------------------------------------------


def rows(page: dict[str, Any]) -> Iterator[str]:
    if page["page"] == "person":
        yield from _person_rows(page)
    elif page["page"] == "asset":
        yield from _asset_rows(page)
    else:
        yield from _place_rows(page)


def _person_rows(p: dict[str, Any]) -> Iterator[str]:
    yield f"{p['name']}  ({', '.join(r['value'] for r in p['refs'])})"
    if p["first_contact"]:
        yield f"  first contact {p['first_contact']} · last {p['last_contact']}"
    else:
        yield "  no confirmed contact yet" + (f" ({p['proposed']} proposed)" if p["proposed"] else "")
    for year, n in p["days_together"].items():
        yield f"  {year}  {_plural(n, 'day')} together"
    if p["places"]:
        yield f"  places  {', '.join(p['places'])}"
    yield f"  commitments  none open ({p['commitments']['note']})"
    if p["shared_stays"]:
        yield f"  last {_plural(len(p['shared_stays']), 'shared stay')}"
        for s in p["shared_stays"]:
            mark = "" if s["status"] == present.CONFIRMED else " (proposed)"
            yield f"    {s['day']}  {s['where']} · {', '.join(s['reasons'])}{mark}"


def _asset_rows(p: dict[str, Any]) -> Iterator[str]:
    yield f"{p['name']}  ({p['id']}, {p['kind']})"
    aboard = [
        _plural(p["nights"], "night") + " aboard",
        _plural(p["stays_aboard"], "stay"),
        f"{p['hours_aboard']:g} h",
    ]
    yield f"  {' · '.join(aboard)}"
    if p["trips"]:
        yield f"  {_plural(len(p['trips']), 'trip')} aboard"
        for t in p["trips"]:
            route = " \u2192 ".join(t["route"])
            yield f"    {t['start']} {EN_DASH} {t['end']}  {_plural(t['nights'], 'night')} · {route}"
    if p["people"]:
        yield "  with  " + ", ".join(f"{who['name']} ({_plural(who['days'], 'day')})" for who in p["people"])
    track = p["track"]
    if track is None:
        yield "  no track of its own in the record (no location lines with this subject)"
    else:
        parts = [
            f"{track['points']} points",
            _plural(track["stays"], "stay"),
            _plural(track["moves"], "move"),
            f"{track['distance_m'] / 1000:.1f} km",
            f"{track['first'][:10]} {EN_DASH} {track['last'][:10]}",
        ]
        yield f"  track  {' · '.join(parts)}"


def _place_rows(p: dict[str, Any]) -> Iterator[str]:
    head = f"{p['name']}  ({p['kind']}"
    head += f", {', '.join(p['tags'])})" if p["tags"] else ")"
    yield head
    if not p["visits"]:
        yield "  never visited"
        return
    yield f"  {_plural(p['visits'], 'visit')} · {p['hours']:g} h · {p['first']} {EN_DASH} {p['last']}"
    for year, v in p["by_year"].items():
        yield f"  {year}  {_plural(v['visits'], 'visit')} · {v['hours']:g} h"
    if p["people"]:
        yield "  with  " + ", ".join(f"{who['name']} ({_plural(who['days'], 'day')})" for who in p["people"])
    yield f"  {_plural(p['photos'], 'photo')}"
    yield f"  last {_plural(len(p['last_visits']), 'visit')}"
    for v in p["last_visits"]:
        aboard = f" · aboard {v['aboard']}" if v["aboard"] else ""
        yield f"    {v['day']}  {v['hours']:g} h{aboard}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


PAGES = ("person", "asset", "place")
