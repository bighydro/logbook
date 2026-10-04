"""Days: a window of the record read back one line per day — `logbook days --from DATE --to DATE`.

A line per day: the date and weekday; where the night was spent (the Day's night after: a named
place, `aboard <asset>`, the home place a night within 400 m of it lies by (`stays.HOME_NEAR_M`),
or the coordinates with `near <place>, x km` for a named place within 5 km (`trips.NEAR_KM`) or
the city of the nearest large airport, and the country when the night is away; `in transit` when
no stay reaches the minimum; `no location` when the day has no location line at all, since
nothing then says the owner moved); the kilometres
moved (every move that started on the day, a flight's included; aboard an asset, the passages);
the flights of the day (`XY 561 OSL→ZRH`, with their evidence under `--json`); the stays (a stay
or a run aboard an asset; a stop is not one) with how many lines are attached across the day's
rows; the people confirmed present (never the owner; a proposed face is not counted); the health
triple when the day has one; and a gap marker naming every usual source with no standing line
that day. A source is usual when it has a line on at least `USUAL_SHARE` of the window's logged
days (four in five: the tracker, the watch, the boat's AIS, the messages; not the photos or the
notes, which come every other day) — one aggregate on the index (`Index.source_days`), nothing
read from the files — so a tracker that fell silent for a day is seen, and a calendar that spoke
once is not missed daily.

Every line is the Day's own (`day.of_reading`): the window is read in chunks of `CHUNK_DAYS`
through one `reading.read` each, with the day before the chunk so its first day has its night
before and the chunk's health lines in one indexed query; then each day of the chunk is asked of
that reading and summarised here. A year is a dozen readings, not one per day, and the lines
stream out as each chunk is read; under `--json` one object per line (JSON Lines), so a year
streams as text does. Nothing is written. ADR 0013: derived is disposable."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from datetime import date, timedelta
from typing import Any

from . import day as day_reader
from . import health, reading, stays, story
from .chain import Line
from .export import day_range
from .flights import Airports
from .reading import Reading
from .store import Logbook

CHUNK_DAYS = 31  # days per reading
USUAL_SHARE = 0.8  # a source with a line on this share of the window's logged days is usual
STAYS = (stays.STAY, day_reader.ABOARD)  # the rows counted as stays
LOCATION = "location"  # the kind of line that says where the owner was; a day with none is `no location`
NIGHT_WIDTH = 28
ARROW = day_reader.ARROW
DOT = day_reader.DOT


def usual_sources(lb: Logbook, first: str, last: str, tiers: Sequence[int] | None = None) -> list[str]:
    """The sources with a line on at least `USUAL_SHARE` of the local days in [first, last] that
    have any line, sorted; none when no day has one. With `tiers`, counted over the lines of those
    tiers only, so a gated reading's days are not all gaps in a source the gate holds back."""
    with lb.index() as idx:
        logged, per_source = idx.source_days(first, last, tiers)
    if not logged:
        return []
    return sorted(source for source, n in per_source.items() if n >= logged * USUAL_SHARE)


def read(
    lb: Logbook,
    first: str,
    last: str,
    airports: Airports | None = None,
    chunk_days: int = CHUNK_DAYS,
    tiers: Sequence[int] | None = None,
) -> Iterator[dict[str, Any]]:
    """One JSON-ready object per day of [first, last], oldest first, as each chunk's reading is
    done; through the gate `tiers` when given (`reading.read`), the health and story lines and the
    usual sources included. `ValueError` for a day that is not one or a range that runs backwards;
    `stays.SettingsError` when the record's settings, places or assets file is not what it should
    be. Nothing is written."""
    window = day_range(first, last)
    if chunk_days < 1:
        raise ValueError(f"chunk_days must be at least 1, not {chunk_days}")
    usual = usual_sources(lb, first, last, tiers)
    airports = airports or Airports.load()
    for start in range(0, len(window), chunk_days):
        chunk = window[start : start + chunk_days]
        before = (date.fromisoformat(chunk[0]) - timedelta(days=1)).isoformat()
        rd = reading.read(lb, before, chunk[-1], airports, tiers)
        with lb.index() as idx:
            found = reading.crossing(idx.by_kind(health.KIND, before, chunk[-1]), tiers)
            told = story.standing(reading.crossing(idx.by_kind(story.KIND), tiers), rd.retracted)
        health_of = day_reader.health_rows(found, rd)
        by_day = _by_day(rd)
        for day in chunk:
            lines = by_day.get(day, [])
            data = day_reader.of_reading(rd, day, health_of.get(day), lines, stories=told)
            yield summarise(data, usual, any(line.get("kind") == LOCATION for line in lines))


def _by_day(rd: Reading) -> dict[str, list[Line]]:
    """The reading's lines by local day, in chain order, so each day's are picked once."""
    out: dict[str, list[Line]] = {}
    for line in rd.lines:
        at = stays.instant(line.get("at"))
        if at is not None:
            out.setdefault(at.astimezone(rd.tz).date().isoformat(), []).append(line)
    return out


def summarise(data: Mapping[str, Any], usual: Sequence[str], located: bool = True) -> dict[str, Any]:
    """One Day (`day.read`) as its line: the night after (`located`: whether the day has any
    location line, so a night in transit on a day without one reads `no location`), the country,
    the metres moved, the flights, the stays and attachments, the people confirmed, the health
    row, the sources, and the usual sources with no line on the day."""
    night = data["nights"]["after"]
    timeline = [e for e in data["timeline"] if e["kind"] != day_reader.FLIGHT]
    stay_rows = [e for e in timeline if e["kind"] in STAYS]
    attached = [sum(n for n, _noun in day_reader.counts(e.get("attached"))) for e in timeline]
    people: dict[str, str] = {}
    for e in timeline:
        for c in (e.get("with") or {}).get("confirmed", []):
            people.setdefault(str(c["person"] or c["name"]), str(c["name"]))
    spoke = {str(s["source"]) for s in data["sources"]}
    return {
        "day": data["day"],
        "weekday": data["weekday"],
        "night": {
            **{k: night[k] for k in ("where", "home", "aboard", "in_transit", "stay")},
            "located": located,
        },
        "country": data["country"]["code"],
        "moved_m": round(_moved(timeline)),
        "flights": [
            {k: f[k] for k in ("carrier", "number", "from", "to", "evidence", "line")}
            for f in data["flights"]
        ],
        "stays": {
            "count": len(stay_rows),
            "attached": sum(attached),
            "with_attachments": sum(
                1 for e, n in zip(timeline, attached, strict=True) if n and e in stay_rows
            ),
        },
        "people": {"confirmed": len(people), "names": list(people.values())},
        "health": data["health"],
        "sources": data["sources"],
        "gaps": [source for source in usual if source not in spoke],
    }


def _moved(timeline: Sequence[Mapping[str, Any]]) -> float:
    """The metres of every move that started on the day (its real start is its start within the
    day), the passages inside a run aboard an asset counted the same way, so a move across midnight
    counts once, on the day it began."""
    metres = 0.0
    for e in timeline:
        rows = e["inside"] if e["kind"] == day_reader.ABOARD else [e]
        for r in rows:
            if r["kind"] == stays.MOVE and r["start"] == r["within_day"]["start"]:
                metres += r["distance_m"] or 0
    return metres


# -- text ----------------------------------------------------------------------------------------------------


def row(r: Mapping[str, Any]) -> str:
    """The day as one line: date, weekday, the night, the kilometres, then the flights, the stays,
    the people, the health triple and the gap marker, the empty parts out."""
    head = f"{r['day']}  {r['weekday'][:3]}  {night_text(r):<{NIGHT_WIDTH}}  {km_text(r['moved_m']):>9}"
    return f"{head}  {DOT.join(parts(r))}".rstrip()


def parts(r: Mapping[str, Any]) -> list[str]:
    """The line's parts after the kilometres: the flights, the stays, the people, the health
    triple and the gap marker, the empty ones out."""
    found: list[str] = []
    if r["flights"]:
        found.append(", ".join(flight_text(f) for f in r["flights"]))
    if r["sources"]:
        found.append(stays_text(r["stays"]))
    else:
        found.append("nothing logged")
    if r["people"]["confirmed"]:
        found.append(f"with {r['people']['confirmed']}")
    if r["health"] is not None:
        found.append(day_reader.health_text(r["health"]))
    if r["gaps"]:
        found.append("gap " + ", ".join(r["gaps"]))
    return found


def night_text(r: Mapping[str, Any]) -> str:
    night = r["night"]
    if night["in_transit"]:
        return "in transit" if night.get("located", True) else "no location"
    where = str(night["where"])
    if night["home"] or r["country"] is None:
        return where
    return f"{where} {r['country']}"


def flight_text(f: Mapping[str, Any]) -> str:
    route = f"{f['from'] or '?'}{ARROW}{f['to'] or '?'}"
    return f"{f['carrier']} {f['number']} {route}" if f["carrier"] and f["number"] else route


def stays_text(s: Mapping[str, Any]) -> str:
    text = f"{s['count']} {'stay' if s['count'] == 1 else 'stays'}"
    return f"{text} ({s['attached']} attached)" if s["attached"] else text


def km_text(metres: float) -> str:
    km = metres / 1000
    return f"{km:.1f} km" if km < 100 else f"{km:,.0f} km"
