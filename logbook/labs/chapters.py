"""`logbook lab chapters`: the record segmented into chapters, as a table of contents.

One reading of the window (`reading.read`). A chapter opens where one of three things happens:

- **the home region changes.** A home region is a place of kind `home` in `places.json`. When a
  home entry carries `since` or `until` (local days, `YYYY-MM-DD`; keys `logbook places` keeps
  when it rewrites the file), the captain's dates decide and `home_history` is `places.json`. When
  none does, the nights decide: a home place becomes the home of the time when it holds
  `min_home_nights` nights at home before the current home holds that many again, and the chapter
  opens on the first of those nights; a shorter run (five nights at the parents', who are a home
  place too) is a visit. `home_history` is then `inferred`.
- **the track goes quiet.** A run of `min_gap_days` or more local days with no `location/v1` line
  of the owner's is a chapter of kind `gap`; the sources that still spoke in it are counted under
  `still_spoke`. The stay reader treats a silent tracker as stillness, so the nights of a gap are
  usually "at home" — the chapter says the track saw nothing, not that nothing happened.
- **a long trip.** A trip (SPEC §3.2.6) of `min_trip_nights` nights or more is a chapter of kind
  `trip`; the home chapter resumes on the return day.

Every other day belongs to the home chapter of the time. Each chapter carries its dates, its
nights (home, away, in transit), the days the track covers, the top places (named places of the
owner's stays inside it, the home of the time left out, by hours) and the top people (the confirmed
company of those stays, by days together), each with its lines; `opened_by` says what opened it
and names the lines. Without a place of kind `home` nothing is home, there are no trips, only the
gaps split the record, and the reader says so (`warning`). Nothing is written; no connection is
opened."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import places as named_places
from .. import present, stays, trips
from ..places import Place, PlaceError
from ..reading import Reading, window_json

MIN_TRIP_NIGHTS = 21
MIN_GAP_DAYS = 7
MIN_HOME_NIGHTS = 14
TOP = 5  # places and people listed per chapter
HOME, TRIP, GAP = "home", "trip", "gap"
LOCATION = "location"
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EN_DASH = "\u2013"
ARROW = "\u2192"
MIDDLE_DOT = "\u00b7"


@dataclass(frozen=True)
class Settings:
    min_trip_nights: int = MIN_TRIP_NIGHTS
    min_gap_days: int = MIN_GAP_DAYS
    min_home_nights: int = MIN_HOME_NIGHTS

    def check(self) -> Settings:
        for name, value in self.to_json().items():
            if value < 1:
                raise ValueError(f"--{name.replace('_', '-')} must be at least 1, not {value}")
        return self

    def to_json(self) -> dict[str, int]:
        return {
            "min_trip_nights": self.min_trip_nights,
            "min_gap_days": self.min_gap_days,
            "min_home_nights": self.min_home_nights,
        }


@dataclass(frozen=True)
class HomeSpan:
    """A home place's dates in `places.json`: `since` and `until` local days, either open."""

    name: str
    since: str | None
    until: str | None

    def holds(self, day: str) -> bool:
        return (self.since is None or self.since <= day) and (self.until is None or day <= self.until)


def home_history(root: Path, places: Sequence[Place]) -> list[HomeSpan]:
    """The dated home places of `places.json`: those of kind `home` whose entry carries `since` or
    `until`. None when no entry does. PlaceError, naming the file and the entry, for a date that
    is not a `YYYY-MM-DD` day or a span that runs backwards."""
    path = named_places.path_of(root)
    if not path.exists():
        return []
    document = json.loads(path.read_text(encoding="utf-8"))
    homes = {p.name for p in named_places.home_places(places)}
    found: list[HomeSpan] = []
    for name, entry in document.items():
        if name not in homes or not isinstance(entry, dict):
            continue
        since, until = (_day_field(entry, key, name, path) for key in ("since", "until"))
        if since is None and until is None:
            continue
        if since is not None and until is not None and until < since:
            raise PlaceError(f"{path}: {name!r}: until {until} is before since {since}")
        found.append(HomeSpan(str(name), since, until))
    return found


def _day_field(entry: dict[str, Any], key: str, name: str, path: Path) -> str | None:
    value = entry.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not DAY.match(value):
        raise PlaceError(f"{path}: {name!r}: {key} must be a date (YYYY-MM-DD), not {value!r}")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as e:
        raise PlaceError(f"{path}: {name!r}: {key} must be a date (YYYY-MM-DD), not {value!r}") from e


# -- the reading --------------------------------------------------------------------------------------------


def chapters(reading: Reading, settings: Settings | None = None) -> dict[str, Any]:
    """The JSON-ready report: `window`, `home_history` (`places.json`, `inferred` or None), `settings`,
    `chapters` and, without a home place, `warning`."""
    settings = (settings or Settings()).check()
    nights = {n.day: n for n in reading.nights}
    homes = named_places.home_places(reading.places)
    history = home_history(reading.lb.root, reading.places)
    home_of_night = {n.day: _home_place(n, reading.places) for n in reading.nights}
    if history:
        home_by_day, how = _dated_homes(reading.days, history, home_of_night), "places.json"
    elif homes:
        home_by_day, how = _inferred_homes(reading.days, home_of_night, settings.min_home_nights), "inferred"
    else:
        home_by_day, how = dict.fromkeys(reading.days), None
    located = _located_days(reading)
    gaps = _runs(reading.days, lambda day: day not in located, settings.min_gap_days)
    found_trips, warning = trips.trips(reading)
    long_trips = [t for t in found_trips if t.nights >= settings.min_trip_nights]
    label: dict[str, tuple[str, Any]] = {}  # day → what it belongs to, gaps over trips over the home
    stretch = 0
    previous: object = object()  # never a home, so the first day opens a stretch
    for day in reading.days:
        if home_by_day[day] != previous:
            stretch += 1
        previous = home_by_day[day]
        label[day] = (HOME, stretch)
    for trip in long_trips:
        for day in _between(trip.start, trip.end):
            if day in label:
                label[day] = (TRIP, trip.id)
    for i, (first, last) in enumerate(gaps):
        for day in _between(first, last):
            label[day] = (GAP, i)
    by_trip = {t.id: t for t in long_trips}
    runs: list[list[str]] = []
    for day in reading.days:
        if runs and label[runs[-1][-1]] == label[day]:
            runs[-1].append(day)
        else:
            runs.append([day])
    evidence = present.Evidence(reading.lines, reading.tz)
    days_of = {str(line["id"]): reading.day_of(line) for line in reading.lines}
    by_day: dict[str, list[Any]] = {}
    for line in reading.lines:
        by_day.setdefault(days_of[str(line["id"])], []).append(line)
    out: list[dict[str, Any]] = []
    for n, days in enumerate(runs, 1):
        kind, what = label[days[0]]
        entry = _chapter(n, kind, days, home_by_day[days[0]], nights, located, reading, evidence, days_of)
        if kind == TRIP:
            trip = by_trip[what]
            entry["trip"] = {"id": trip.id, "route": list(trip.route), "places": list(trip.places)}
            entry["title"] = "trip: " + (", ".join(trip.places) or f" {ARROW} ".join(trip.route) or "away")
        elif kind == GAP:
            spoke = Counter(str(line.get("source")) for day in days for line in by_day.get(day, ()))
            entry["still_spoke"] = dict(sorted(spoke.items()))
            entry["title"] = f"gap: no track for {_plural(len(days), 'day')}"
        else:
            entry["title"] = f"home: {entry['home']}" if entry["home"] else "home unknown"
        entry["opened_by"] = _opened_by(entry, out[-1] if out else None, how, reading, nights)
        out.append(entry)
    report: dict[str, Any] = {
        "window": window_json(reading),
        "home_history": how,
        "settings": settings.to_json(),
        "chapters": [_ordered(c) for c in out],
    }
    if warning:
        report["warning"] = warning
    return report


def empty(settings: Settings | None = None) -> dict[str, Any]:
    return {
        "window": None,
        "home_history": None,
        "settings": (settings or Settings()).to_json(),
        "chapters": [],
    }


def _ordered(c: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "n",
        "kind",
        "title",
        "start",
        "end",
        "days",
        "home",
        "nights",
        "located_days",
        "still_spoke",
        "trip",
        "places",
        "people",
        "opened_by",
        "lines",
    )
    return {key: c.get(key) for key in keys}


def _chapter(
    n: int,
    kind: str,
    days: list[str],
    home: str | None,
    nights: dict[str, stays.Night],
    located: set[str],
    reading: Reading,
    evidence: present.Evidence,
    days_of: dict[str, str],
) -> dict[str, Any]:
    first, last = days[0], days[-1]
    own = [nights[d] for d in days if d in nights]
    start = datetime.combine(date.fromisoformat(first), datetime.min.time(), tzinfo=reading.tz)
    end = datetime.combine(
        date.fromisoformat(last) + timedelta(days=1), datetime.min.time(), tzinfo=reading.tz
    )
    inside = [s for s in reading.owner_stays if s.start < end and s.end > start]
    nights_at: Counter[str] = Counter()
    for night in own:
        lay = night.innermost
        if lay is not None and lay.place:
            nights_at[lay.place] += 1
    places: dict[str, dict[str, Any]] = {}
    people: dict[tuple[str | None, str], dict[str, Any]] = {}
    for stay in inside:
        if stay.place and stay.place != home:
            entry = places.setdefault(
                stay.place, {"name": stay.place, "hours": 0.0, "stays": 0, "nights": 0, "lines": []}
            )
            overlap = (min(stay.end, end) - max(stay.start, start)).total_seconds()
            entry["hours"] += overlap / 3600
            entry["stays"] += 1
            entry["lines"] += [id_ for id_ in (stay.first_line, stay.last_line) if id_]
        for c in present.present(
            stay, evidence.near(stay), reading.identities, reading.places, reading.owner
        ):
            if c.status != present.CONFIRMED:
                continue
            day = days_of.get(c.line, first)
            if not first <= day <= last:
                continue
            key = (c.person, "" if c.person else c.name.casefold())
            who = people.setdefault(key, {"person": c.person, "name": c.name, "days": set(), "lines": []})
            who["days"].add(day)
            who["lines"].append(c.line)
    for name, entry in places.items():
        entry["nights"] = nights_at.get(name, 0)
        entry["hours"] = round(entry["hours"], 1)
        entry["lines"] = list(dict.fromkeys(entry["lines"]))
    top_places = sorted(places.values(), key=lambda p: (-p["hours"], -p["nights"], p["name"]))[:TOP]
    top_people = sorted(
        ({**p, "days": len(p["days"]), "lines": list(dict.fromkeys(p["lines"]))} for p in people.values()),
        key=lambda p: (-p["days"], p["name"]),
    )[:TOP]
    with_stay = [night.stay for night in own if night.stay is not None]
    lines = [
        id_
        for id_ in (
            with_stay[0].first_line if with_stay else None,
            with_stay[-1].last_line if with_stay else None,
        )
        if id_
    ]
    return {
        "n": n,
        "kind": kind,
        "start": first,
        "end": last,
        "days": len(days),
        "home": home,
        "nights": {
            "total": len(own),
            "home": sum(1 for x in own if x.home),
            "away": sum(1 for x in own if not x.home and not x.in_transit),
            "in_transit": sum(1 for x in own if x.in_transit),
        },
        "located_days": sum(1 for d in days if d in located),
        "still_spoke": None,
        "trip": None,
        "places": top_places,
        "people": top_people,
        "lines": list(dict.fromkeys(lines)),
    }


def _opened_by(
    c: dict[str, Any],
    before: dict[str, Any] | None,
    how: str | None,
    reading: Reading,
    nights: dict[str, stays.Night],
) -> dict[str, Any]:
    """What opened the chapter, and the lines that show it: the first point of its first night's
    stay; for a gap, the last point before it and the first after."""
    first_night = nights.get(c["start"])
    first_point = (
        [first_night.stay.first_line]
        if first_night and first_night.stay and first_night.stay.first_line
        else []
    )
    if before is None:
        return {"kind": "record start", "detail": "the first day of the window", "lines": first_point}
    if c["kind"] == GAP:
        spoke = ", ".join(f"{s} {n}" for s, n in c["still_spoke"].items()) or "nothing"
        detail = f"no location line for {_plural(c['days'], 'day')}; still spoke: {spoke}"
        return {"kind": "track gap", "detail": detail, "lines": _around_gap(c["start"], c["end"], reading)}
    if c["kind"] == TRIP:
        return {
            "kind": "trip",
            "detail": f"{_plural(c['nights']['total'], 'night')} away: {c['title'][6:]}",
            "lines": first_point,
        }
    if before["home"] != c["home"] and c["home"] is not None and before["home"] is not None:
        by = "dated in places.json" if how == "places.json" else "inferred from the nights"
        return {
            "kind": "home change",
            "detail": f"{before['home']} {ARROW} {c['home']}, {by}",
            "lines": first_point,
        }
    if before["kind"] == GAP:
        detail = f"the first location line after {_plural(before['days'], 'day')} without one"
        return {"kind": "track resumes", "detail": detail, "lines": first_point}
    if before["kind"] == TRIP:
        detail = f"home after {_plural(before['nights']['total'], 'night')} away"
        return {"kind": "return", "detail": detail, "lines": first_point}
    return {"kind": "home change", "detail": f"{before['home']} {ARROW} {c['home']}", "lines": first_point}


def _around_gap(first: str, last: str, reading: Reading) -> list[str]:
    before = after = None
    for line in reading.lines:
        if line.get("kind") != LOCATION or line.get("payload", {}).get("subject"):
            continue
        day = reading.day_of(line)
        if day < first:
            before = str(line["id"])
        elif day > last and after is None:
            after = str(line["id"])
    return [id_ for id_ in (before, after) if id_]


# -- the home of the time -----------------------------------------------------------------------------------


def _home_place(night: stays.Night, places: Sequence[Place]) -> str | None:
    """The home place a night at home lies in: the stay's named place when that is a home, else the
    home whose radius holds its centre, else the nearest home within `stays.HOME_NEAR_M` (the night
    rule of SPEC §3.2.3 rule 8); None for a night away or in transit."""
    stay = night.stay
    if stay is None or not night.home:
        return None
    if stay.place:
        named = named_places.by_name(places).get(stay.place)
        if named is not None and named.kind == named_places.HOME:
            return named.name
    if stay.lat is None or stay.lon is None:
        return None
    inside = named_places.at_home(stay.lat, stay.lon, places)
    if inside is not None:
        return inside.name
    near = [
        (named_places.distance_m(stay.lat, stay.lon, h.lat, h.lon), h.name)
        for h in named_places.home_places(places)
    ]
    close = [(d, name) for d, name in near if d <= stays.HOME_NEAR_M]
    return min(close)[1] if close else None


def _dated_homes(
    days: Sequence[str], history: Sequence[HomeSpan], home_of_night: dict[str, str | None]
) -> dict[str, str | None]:
    """Per day, the dated home in force (the latest `since` among those holding the day); a day
    no dated home holds takes the home the nights of its undated stretch slept at most."""
    out: dict[str, str | None] = {}
    undated: list[str] = []

    def flush() -> None:
        if not undated:
            return
        slept = Counter(home_of_night[d] for d in undated if home_of_night.get(d))
        name = slept.most_common(1)[0][0] if slept else None
        out.update(dict.fromkeys(undated, name))
        undated.clear()

    for day in days:
        holding = [h for h in history if h.holds(day)]
        if holding:
            flush()
            out[day] = max(holding, key=lambda h: h.since or "").name
        else:
            undated.append(day)
    flush()
    return out


def _inferred_homes(
    days: Sequence[str], home_of_night: dict[str, str | None], min_nights: int
) -> dict[str, str | None]:
    """Per day, the home of the time by the nights: a place becomes the home when it holds
    `min_nights` nights at home before the current home holds that many again (the counts start
    over whenever the current home does), and the change dates from the first of those nights.
    Before any place has, the first to do so is the home from the start; when none ever does,
    the place with most nights is."""
    current: str | None = None
    changes: list[tuple[str, str]] = []  # (day, new home)
    counts: Counter[str] = Counter()
    first_at: dict[str, str] = {}
    for day in days:
        place = home_of_night.get(day)
        if place is None:
            continue
        counts[place] += 1
        first_at.setdefault(place, day)
        if counts[place] < min_nights:
            continue
        if place != current:
            changes.append((days[0] if current is None else first_at[place], place))
            current = place
        counts, first_at = Counter(), {}
    if not changes:
        slept = Counter(p for p in home_of_night.values() if p)
        return dict.fromkeys(days, slept.most_common(1)[0][0] if slept else None)
    out: dict[str, str | None] = {}
    home: str | None = changes[0][1]
    pending = list(changes)
    for day in days:
        while pending and pending[0][0] <= day:
            home = pending.pop(0)[1]
        out[day] = home
    return out


# -- helpers ------------------------------------------------------------------------------------------------


def _located_days(reading: Reading) -> set[str]:
    return {
        reading.day_of(line)
        for line in reading.lines
        if line.get("kind") == LOCATION and not line.get("payload", {}).get("subject")
    }


def _runs(days: Sequence[str], test: Any, at_least: int) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    run: list[str] = []
    for day in [*days, None]:
        if day is not None and test(day):
            run.append(day)
            continue
        if len(run) >= at_least:
            found.append((run[0], run[-1]))
        run = []
    return found


def _between(first: str, last: str) -> list[str]:
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


# -- the text -----------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """A table of contents: one row per chapter."""
    window = data["window"]
    if window is None:
        yield "chapters: no days"
        return
    how = {
        "places.json": "home history dated in places.json",
        "inferred": "home history inferred from the nights",
        None: "no place of kind home",
    }[data["home_history"]]
    found = data["chapters"]
    head = f"chapters {window['since']} {EN_DASH} {window['until']}: {_plural(len(found), 'chapter')} ({how})"
    if data.get("warning"):
        head += f"; {data['warning']}"
    yield head
    width = max((len(c["title"]) for c in found), default=0)
    for c in found:
        count = _plural(c["days"], "day") if c["kind"] == GAP else _plural(c["nights"]["total"], "night")
        parts = []
        if c["kind"] == GAP:
            spoke = ", ".join(f"{s} {n}" for s, n in c["still_spoke"].items())
            parts.append(f"still spoke: {spoke}" if spoke else "nothing spoke")
        else:
            aside = [
                f"{c['nights'][k]} {k.replace('_', ' ')}" for k in ("away", "in_transit") if c["nights"][k]
            ]
            if aside and c["kind"] != TRIP:
                parts.append(", ".join(aside))
            if c["places"]:
                parts.append("places " + ", ".join(f"{p['name']} {p['hours']:g} h" for p in c["places"]))
            if c["people"]:
                parts.append("with " + ", ".join(f"{p['name']} {p['days']} d" for p in c["people"]))
        tail = f"  {f' {MIDDLE_DOT} '.join(parts)}" if parts else ""
        yield f"{c['n']:>4}  {c['start']} {EN_DASH} {c['end']}  {count:>10}  {c['title']:<{width}}{tail}"
