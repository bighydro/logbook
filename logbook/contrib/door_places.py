"""The Places door of the Library (RFC 0047 §4.4): where a life has happened, and where it goes next.

`/places` is the door. From the top: the head, "Places" and one line in pencil; **the globe**, on a dark
card, drawn here as one inline `<svg>` (an orthographic disc turned so that home is near the centre, a
faint graticule, the coastlines when `logbook.json` names the offline map file, `setup map`, and the
graticule alone without it; the named places as dots, home a light one with a soft glow; the trips as
arcs from home, the lived ones muted and solid, the ones ahead warm, dashed and labelled; labels for at
most `LABELS_MOST` places); under it **the time scrubber**, the years of the owner's life as links every
five years and a GET form with a range, so `/places?at=YYYY` turns the globe to that year (its places
bright, its trips as arcs, the rest faint); **Next**, the trips and visits ahead (`ahead`); **Your
places**, the named places, home first, then by the days spent there in the last year (the order only,
never the count), each with what it is in the owner's words (`words`: "Home" for a home, else the tags
`places.json` gives it) or a pencil placeholder linking to the place's page. `Site.page_places` puts the
register of `places.json` and the review queue of `setup places review` under it, as they were.

`/places/ID` is one place (`page_place`): its name, what it is, the days there as a strip over the
years (each day a link to its Day; a year of more than `RUN_FROM` days there as its runs, each a link
to its first day), the people who were there with you, ordered by closeness (days together in the last
year, then the last contact, then how long known; a link to each one's thread, never a number), and the
trips that passed through it. An ID is the place's name as a slug (`site.slug`), `review` taken.

Where it reads from, every reading one the Library keeps already (`read`, once per head and day,
`Site.shared`):

- **the places, their days and the trips lived**: the World's bundle (`world.build`, the reading
  `/world` makes, by year, the closed years kept beside the index), over the same window and gate.
  A day at a place is a local day one of the owner's stays there touches; a **trip** is a run of nights
  whose stay was away from every home (`HOME_M`, or aboard), its place the stay of most nights in it.
- **who was there**: the people of the whole record (`people.read_whole`, kept beside the index), a
  person at a place on a day they shared a stay there with you; through a gate, `people.read` with
  every line it rests on held to the gate's tiers, as the Promises shelf reads them.
- **what comes next** (`ahead`): the calendar's entries from today to `AHEAD_DAYS` on (`event/v1`
  standing, not cancelled, through the gate): a flight out (`Flight to <city>`) opens a trip there,
  which the entries that follow join until a flight home or `OPEN_DAYS` without one; an entry located
  `AWAY_KM` or more from home (at a named place, or by its coordinates) is a visit; who goes is the
  attendees, by the names the record gives them. And the plan's trips (`plan`, the `trips` database of
  `policy/notion.json`), dated on or after today. Each links to its span on Life, `/life?trip=F/L`.

The rules of every door hold: a lower tier never shows a higher tier's line, name or count (the gate
is the Site's `tiers`); no number stands beside a person's name, in the text, a title or a label; the
page writes nothing, carries no script and fetches nothing; and what a rule inferred is set in pencil
with the rule named on hover. A static site (`export site`) reads the record's last day as its today,
so its pages are a function of the record, and draws no form."""

from __future__ import annotations

import functools
import itertools
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from ..core import day_start, people, places, stays
from ..core.chain import Line
from ..core.flights import Airports
from ..core.store import retractions
from . import plan, world
from .map import MapError, map_file, mvt
from .map.pmtiles import PMTiles

if TYPE_CHECKING:
    from .serve import Site

LABELS_MOST = 8  # the globe names at most this many places
LABEL_CHAR, LABEL_HIGH = 11.0, 20.0  # a label's letter and line, in the SVG's units, at its phone size
HOME_M = 400.0  # a night this close to a home is a night at home (the trips reader's home region)
AWAY_KM = 50.0  # an entry ahead this far from home is a trip or a visit; an airport nearer is home's
AHEAD_DAYS = 365  # what the calendar holds this far ahead is read
OPEN_DAYS = 14  # a flight out with no flight home: the trip is held open this long
AHEAD_SHOWN = 7  # rows of Next
ARCS_MOST = 40  # arcs on the globe at most, the latest first
RUN_FROM = 60  # a year with more days at a place than this is drawn as its runs on the place's page
YEAR_LINKS_EVERY = 5
LAST_YEAR_DAYS = 365
SIZE, RADIUS = 560.0, 262.0  # the globe's square and its disc, in the SVG's units
TILT = 10.0  # degrees: the globe turned this far south of home, so home sits just above the centre
STEP = 3.0  # degrees between the graticule's points
COAST_ZOOM_MOST, COAST_TILES_MOST = 3, 64  # the map file's coastlines: its first zoom, if this coarse
RESERVED = ("review",)  # a place's id never one of the door's own addresses
MONTHS = (
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
)  # fmt: skip
EN_DASH, DOT = "\u2013", " \u00b7 "
FLIGHT = re.compile(r"^\s*(?:flight|flug|fly|flyg)\s+(?:to|til|nach|till)\s+(.+?)\s*(?:\(|$)", re.I)
LEAD = "Where your life has happened, and where it goes next."
PLACEHOLDER = "[what it holds for you]"
PLACEHOLDER_TITLE = (
    "Not said yet: a tag on the place in places.json is shown here, in your words"
    " (the Places door's placeholder)"
)
AHEAD_TITLE = "Read from your calendar: a flight out and what follows it, or an entry away from home"
PLAN_TITLE = "Read from your plan: a row of the trips database"
NOTHING_AHEAD = (
    "Nothing ahead yet. Trips appear here when your calendar or your plan holds one away from home."
)
NO_PLACES = (
    "No places yet. Name the places you return to in the review below, or with `logbook setup places add`."
)
NOBODY = "Nobody yet. People appear here once the calendar, a photo or your own words put them here with you."
NO_DAYS = "No day here yet. A day appears once one of your stays is at this place."
NO_TRIPS = "No trip through it yet. A trip appears once you spend a night away from home here."
FROM_HOME = "Every trip starts here; each shows on the places it reaches."
QUIET = "Nothing recorded in {year} yet: the globe fills in as the record reaches back."

STYLE = """
.door-places{background:var(--paper,#F4F1EA);color:var(--ink,#16181D);border-radius:22px;
padding:28px 20px;margin:0 0 1.5rem;font-family:Inter,system-ui,sans-serif;font-size:15px;line-height:1.5}
.door-places a{color:var(--ink,#16181D);text-decoration:none}
.door-places h1{font-family:'Instrument Serif',Georgia,serif;font-size:40px;font-weight:400;
line-height:1.05;margin:0}
.door-places h2.mono{font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;font-weight:500;
line-height:1.4;text-transform:uppercase;
letter-spacing:.13em;color:var(--pencil,#62666D);margin:0 0 12px}
.door-places .lead,.door-places .pencil-line{color:var(--pencil,#62666D);margin:6px 0 0}
.door-places .lead{font-size:17px;margin-bottom:24px}
.door-places .pencil{color:var(--pencil,#62666D);border-bottom:1px dotted var(--pencil-rule,#8C8F95)}
.door-places .grid{display:block}
.door-places .card{background:var(--surface,#FBFAF6);border:1px solid var(--line,#E3DED3);
border-radius:18px;
padding:20px;margin:0 0 16px}
.door-places .globe-card{background:#0E141B;color:var(--paper,#F4F1EA);border-radius:24px;padding:12px 8px;
margin:0 0 16px}
.door-places .globe-card .pencil-line{color:var(--muted,#C9C4B8)}
.door-places .globe-card a{color:var(--paper,#F4F1EA)}
.door-places svg.globe{display:block;width:100%;max-width:100%;height:auto;margin:0 auto}
.door-places svg.globe .disc{fill:#16202B;stroke:#2A3644;stroke-width:1}
.door-places svg.globe .graticule{fill:none;stroke:#C9C4B8;stroke-opacity:.12;stroke-width:.7}
.door-places svg.globe .coast{fill:none;stroke:#C9C4B8;stroke-opacity:.5;stroke-width:.9;
stroke-linejoin:round}
.door-places svg.globe .place .dot{fill:#C9C4B8}
.door-places svg.globe .place.home .dot{fill:#F4F1EA}
.door-places svg.globe .place.home .glow{fill:#F4F1EA}
.door-places svg.globe .place.faint{opacity:.28}
.door-places svg.globe .place.bright .dot{fill:#F4F1EA}
.door-places svg.globe .arc{fill:none;stroke-linecap:round}
.door-places svg.globe .arc.past{stroke:#C9C4B8;stroke-opacity:.55;stroke-width:1.4}
.door-places svg.globe .arc.next{stroke:#F2A27E;stroke-width:1.8}
.door-places svg.globe .end{fill:#C9C4B8}
.door-places svg.globe .end.next{fill:#F2A27E}
.door-places svg.globe text{font-family:Inter,system-ui,sans-serif;font-size:16px;fill:#C9C4B8;
paint-order:stroke;stroke:#0E141B;stroke-width:4px;stroke-linejoin:round}
.door-places svg.globe text.faint{opacity:.4}
.door-places svg.globe text.home{fill:#F4F1EA}
.door-places svg.globe text.next{fill:#F2A27E}
.door-places .scrub-years,.door-places .globe-card .pencil-line,.door-places form.scrub{padding:0 8px}
.door-places .scrub-years{display:flex;flex-wrap:wrap;gap:4px 14px;margin:14px 0 8px;
font-family:'JetBrains Mono',ui-monospace,monospace;font-size:12px;line-height:1.4}
.door-places .scrub-years a{display:inline-block;min-height:44px;line-height:44px;
color:var(--muted,#C9C4B8)}
.door-places .scrub-years a[aria-current=true]{color:#F2A27E}
.door-places form.scrub{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:4px 0 8px}
.door-places form.scrub input[type=range]{flex:1 1 10rem;min-width:0;min-height:44px;accent-color:#F2A27E;
background:none;border:0;padding:0}
.door-places form.scrub button{min-height:44px;padding:0 22px;border-radius:23px;border:1px solid #C9C4B8;
background:none;color:var(--paper,#F4F1EA);font-family:Inter,system-ui,sans-serif;font-size:15px;
font-weight:500}
.door-places .globe-card .pencil-line{font-size:13px}
.door-places ol.rows{list-style:none;margin:0;padding:0}
.door-places ol.rows li{border-top:1px solid var(--line-soft,#ECE7DD);padding:0}
.door-places ol.rows li:first-child{border-top:0}
.door-places a.moment{display:block;padding:12px 0;min-height:44px}
.door-places .where{display:block;font-family:'Instrument Serif',Georgia,serif;font-size:24px;
font-weight:400;line-height:1.2;color:var(--ink,#16181D)}
.door-places .when{display:block;font-size:13px;color:var(--pencil,#62666D);margin-top:2px}
.door-places ol.mine li{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;
gap:2px 12px;padding:10px 0}
.door-places a.place-name{font-family:'Instrument Serif',Georgia,serif;font-size:24px;font-weight:400;
line-height:1.2;min-height:44px;
display:inline-block;line-height:44px}
.door-places .what{font-size:13px;color:var(--ink,#16181D)}
.door-places .lead .what,.door-places .lead .pencil{font-size:18px}
.door-places .empty{color:var(--pencil,#62666D);margin:0}
.door-places p.crumb{margin:0 0 12px;font-size:13px}
.door-places p.crumb a{color:var(--pencil,#62666D);display:inline-block;min-height:44px;line-height:44px}
.door-places .strip{margin:0;padding:0;list-style:none}
.door-places .strip li{display:flex;gap:12px;align-items:center;padding:4px 0}
.door-places .strip .y{flex:none;width:3rem;font-family:'JetBrains Mono',ui-monospace,monospace;
font-size:12px;
color:var(--pencil,#62666D)}
.door-places svg.days{display:block;flex:1 1 10rem;min-width:0;max-width:100%;height:22px}
.door-places svg.days rect{fill:var(--pencil-rule,#8C8F95)}
.door-places svg.days rect.base{fill:var(--tint,#EDE8DE)}
.door-places ul.people{list-style:none;margin:0;padding:0;display:flex;flex-wrap:wrap;gap:8px}
.door-places ul.people a{display:inline-block;min-height:44px;line-height:44px;padding:0 18px;
border:1px solid var(--line,#E3DED3);border-radius:23px;background:var(--surface,#FBFAF6)}
details.register{margin:0 0 1rem}
@media (min-width:56rem){
.door-places{padding:36px}
.door-places h1{font-size:72px}
.door-places .grid{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:24px;
align-items:start}
.door-places .card{padding:28px}
.door-places .globe-card{padding:20px}
}
@media (max-width:40rem){.door-places{border-radius:18px}
.door-places svg.globe text{font-size:22px}
.door-places .scrub-years a.half{display:none}}
"""


# -- what is read ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Place:
    """A named place of `places.json`, as the door shows it: its id (`/places/ID`), its words."""

    id: str
    name: str
    lat: float
    lon: float
    kind: str
    tags: tuple[str, ...]

    @property
    def home(self) -> bool:
        return self.kind == places.HOME

    @property
    def words(self) -> str | None:
        """What it is in the owner's words: "Home" for a home, and the tags `places.json` gives it."""
        said = (["Home"] if self.home else []) + [t for t in self.tags if t.strip()]
        return ", ".join(dict.fromkeys(said)) or None


@dataclass(frozen=True)
class Trip:
    """A span away: lived (from the nights) or ahead (from the calendar or the plan)."""

    first: str  # local days, inclusive
    last: str
    name: str  # where, in words
    lat: float | None
    lon: float | None
    ahead: bool = False
    people: tuple[str, ...] = ()  # names, never counted
    places: frozenset[str] = frozenset()  # the named places' ids its days touched
    said: str = ""  # where it was read, on hover

    @property
    def link(self) -> str:
        return f"/life?trip={self.first}/{self.last}"


@dataclass
class Reading:
    today: str
    places: list[Place]
    days: dict[str, list[str]]  # place id → the local days there, in order
    trips: list[Trip]  # lived, the latest first
    ahead: list[Trip]  # the soonest first
    first_year: int
    gated: bool = False
    coast: list[list[tuple[float, float]]] = field(default_factory=list)  # (lon, lat) lines


def place_ids(found: Iterable[places.Place]) -> dict[str, str]:
    """name → the place's id: its name as a slug, the first of two that fold alike keeping it."""
    from .site import slug  # the export's own rule; imported here, since the site builds on serve

    taken = set(RESERVED)
    out: dict[str, str] = {}
    for p in found:
        stem = slug(p.name)
        candidate, n = stem, 1
        while candidate in taken:
            n += 1
            candidate = f"{stem}-{n}"
        taken.add(candidate)
        out[p.name] = candidate
    return out


def today_of(site: Site) -> str:
    """The owner's today; for a static site, the record's last day, so its pages are the record's."""
    if site.static:
        whole = site._record_days()
        if whole is not None:
            return whole[1]
    return site._today_of()


def read(site: Site) -> Reading:
    """The door's reading of the record as it stands, once per head and day (`Site.shared`)."""
    today = today_of(site)
    key = ("door places", None if site.tiers is None else tuple(site.tiers), today)
    return site.shared(key, lambda: _read(site, today))


def _read(site: Site, today: str) -> Reading:
    lb = site.lb
    named = places.read(lb.root)
    ids = place_ids(named)
    shown = [Place(ids[p.name], p.name, p.lat, p.lon, p.kind, tuple(p.tags)) for p in named]
    whole = site._record_days()
    first_year = int(whole[0][:4]) if whole else int(today[:4])
    reading = Reading(today, shown, {p.id: [] for p in shown}, [], [], first_year)
    reading.gated = site.tiers is not None
    reading.coast = coastlines(lb.meta)
    bundle = _bundle(site, today)
    if bundle is not None:
        reading.days, reading.trips = _lived(bundle, shown, site, ids)
    reading.ahead = ahead(site, today, shown, _directory(site))
    return reading


def people_at(site: Site, reading: Reading) -> dict[str, list[tuple[str, str]]]:
    """Who was at each place with you, the closest first: read for a place's page alone, so the door
    reads the people of the whole record only when a place is opened (`Site.shared`, once per head)."""
    key = ("door places people", None if site.tiers is None else tuple(site.tiers), reading.today)

    def found() -> dict[str, list[tuple[str, str]]]:
        report = _people(site)
        return {} if report is None else _people_at(report, reading.places, reading.today)

    return site.shared(key, found)


def _directory(site: Site) -> people.Report:
    """Who is who: the resolution lines alone (`people.directory`), which name an attendee ahead."""
    return site.shared(("door places directory",), lambda: people.directory(site.lb))


def _bundle(site: Site, today: str) -> Mapping[str, Any] | None:
    """The World's bundle of the record's window (the request `/world` makes), through the gate."""
    tiers = None if site.tiers is None else tuple(sorted({int(t) for t in site.tiers}))
    try:
        req = world.request(site.lb, None, None, tiers, today=today)
        if req is None:
            return None
        return site.shared(("world bundle", req), lambda: world.build(site.lb, req, site.airports).bundle)
    except world.WorldError:
        return None  # the policy lets nothing of it cross: the graticule and the names alone


def _lived(
    bundle: Mapping[str, Any], shown: Sequence[Place], site: Site, ids: Mapping[str, str]
) -> tuple[dict[str, list[str]], list[Trip]]:
    """The days at each place, and the trips: runs of nights away from every home."""
    bounds = day_start.of(site.lb.meta)
    start = bounds.span(str(bundle["window"]["from"]))[0]
    by_bundle = {str(p["id"]): ids.get(str(p["name"])) for p in bundle.get("places", [])}
    assets = {str(a["id"]): str(a.get("name") or a["id"]) for a in bundle.get("assets", [])}
    homes = [p for p in shown if p.home]
    days: dict[str, set[str]] = {p.id: set() for p in shown}
    nights: dict[str, dict[str, Any]] = {}  # night's day → its stay
    on_day: dict[str, set[str]] = {}  # day → the places its stays touched
    for s in bundle.get("stays", []):
        at = start + timedelta(minutes=int(s["t0"]))
        end = start + timedelta(minutes=int(s["t1"]))
        first, last = bounds.day(at), bounds.day(end - timedelta(seconds=1)) if end > at else bounds.day(at)
        pid = by_bundle.get(str(s.get("place"))) if s.get("place") else None
        d = first
        while d <= last:
            if pid is not None:
                days[pid].add(d.isoformat())
                on_day.setdefault(d.isoformat(), set()).add(pid)
            d += timedelta(days=1)
        if s.get("night"):
            d = first
            while d <= last:
                night = bounds.span(d)[1] + timedelta(hours=3)  # the small hours after the day
                if at <= night < end:
                    nights[d.isoformat()] = s
                d += timedelta(days=1)
    trips: list[Trip] = []
    run: list[tuple[str, dict[str, Any]]] = []

    def away(s: Mapping[str, Any]) -> bool:
        if s.get("aboard"):
            return True
        return not any(
            places.distance_m(float(s["lat"]), float(s["lon"]), h.lat, h.lon) <= HOME_M for h in homes
        )

    def close() -> None:
        if not run:
            return
        counted: dict[int, int] = {}
        for _day, s in run:
            counted[id(s)] = counted.get(id(s), 0) + 1
        stays_of = {id(s): s for _day, s in run}
        best = max(stays_of.values(), key=lambda s: (counted[id(s)], _km_from(s, homes)))
        first, last = run[0][0], run[-1][0]
        touched = frozenset(
            pid
            for d in _days(first, (date.fromisoformat(last) + timedelta(days=1)).isoformat())
            for pid in on_day.get(d, set())
            if not any(p.id == pid and p.home for p in shown)
        )
        trips.append(
            Trip(first, last, _stay_name(best, by_bundle, shown, assets, site.airports), float(best["lat"]),
                 float(best["lon"]), places=touched)
        )  # fmt: skip
        run.clear()

    if homes:  # without a home nothing is away (the trips reader's rule)
        for day in sorted(nights):
            s = nights[day]
            if not away(s):
                close()
                continue
            if run and (date.fromisoformat(day) - date.fromisoformat(run[-1][0])).days != 1:
                close()
            run.append((day, s))
        close()
    trips.sort(key=lambda t: t.first, reverse=True)
    return {pid: sorted(found) for pid, found in days.items()}, trips


def _km_from(s: Mapping[str, Any], homes: Sequence[Place]) -> float:
    if not homes:
        return 0.0
    return min(places.distance_m(float(s["lat"]), float(s["lon"]), h.lat, h.lon) for h in homes) / 1000


def _stay_name(
    s: Mapping[str, Any],
    by_bundle: Mapping[str, str | None],
    shown: Sequence[Place],
    assets: Mapping[str, str],
    airports: Airports,
) -> str:
    """How a trip names where it went: the named place, aboard the asset, the city, else the spot."""
    pid = by_bundle.get(str(s.get("place"))) if s.get("place") else None
    for p in shown:
        if p.id == pid:
            return p.name
    if s.get("aboard"):
        return f"aboard {assets.get(str(s['aboard']), str(s['aboard']))}"
    from ..core import trips as trips_reader

    city = trips_reader.city_near(float(s["lat"]), float(s["lon"]), airports)
    return city or f"{float(s['lat']):.2f}, {float(s['lon']):.2f}"


def _days(first: str, last: str) -> Iterable[str]:
    d, end = date.fromisoformat(first), date.fromisoformat(last)
    while d <= end:
        yield d.isoformat()
        d += timedelta(days=1)


def _people(site: Site) -> people.Report | None:
    """The people of the whole record: the kept reading; through a gate, every line it rests on held to
    the gate's tiers (as the Promises shelf reads its gated record)."""
    if site.tiers is None:
        return site.shared(("people whole",), lambda: people.read_whole(site.lb, site.airports))
    allowed = {int(t) for t in site.tiers}

    def admit(line: Line) -> bool:
        return int(line.get("tier") or 0) in allowed

    def gated() -> people.Report | None:
        whole = site._record_days()
        if whole is None:
            return None
        return people.read(site.lb, whole[0], whole[1], site.airports, admit=admit)

    return site.shared(("people gated", tuple(sorted(allowed))), gated)


def _closeness(person: people.Person, today: str) -> tuple[Any, ...]:
    """Closeness, as the People door orders it: days together in the last year, then the last contact,
    then how long known; never shown, only the order."""
    since = (date.fromisoformat(today) - timedelta(days=LAST_YEAR_DAYS)).isoformat()
    recent = sum(1 for d in person.days if since <= d <= today)
    last = person.last_contact or ""
    first = person.first_contact or "9999"
    return (-recent, _desc(last), first, person.name.casefold())


def _desc(day: str) -> str:
    return "".join(chr(ord("9") - ord(c) + ord("0")) if c.isdigit() else c for c in day) if day else "~"


def _people_at(report: people.Report, shown: Sequence[Place], today: str) -> dict[str, list[tuple[str, str]]]:
    by_name = {p.name: p.id for p in shown}
    found: dict[str, list[people.Person]] = {p.id: [] for p in shown}
    for person in report.people:
        for pid in dict.fromkeys(by_name[s.where] for s in person.shared.values() if s.where in by_name):
            found[pid].append(person)
    return {
        pid: [(p.entity, p.name) for p in sorted(folk, key=lambda p: _closeness(p, today))]
        for pid, folk in found.items()
    }


# -- what comes next ----------------------------------------------------------------------------------------


def ahead(site: Site, today: str, shown: Sequence[Place], report: people.Report | None) -> list[Trip]:
    """The trips and visits ahead: the calendar's, then the plan's, the soonest first."""
    homes = [p for p in shown if p.home] or list(shown[:1])
    found = _calendar_ahead(site, today, shown, homes, report) + _plan_ahead(site, today, shown)
    found.sort(key=lambda t: (t.first, t.last, t.name.casefold()))
    return found


def _fold(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if not unicodedata.combining(c))


def _calendar_ahead(
    site: Site, today: str, shown: Sequence[Place], homes: Sequence[Place], report: people.Report | None
) -> list[Trip]:
    if not homes:
        return []
    lb = site.lb
    bounds = day_start.of(lb.meta)
    last = (date.fromisoformat(today) + timedelta(days=AHEAD_DAYS)).isoformat()
    allowed = None if site.tiers is None else {int(t) for t in site.tiers}
    with lb.index() as idx:
        entries = idx.by_kind("event", today, last)
        gone = set(retractions(idx.retractions())) | set(idx.superseded("event"))
    by_name = {_fold(p.name): p for p in shown}
    owner = {str(e).casefold() for e in lb.meta.get("owner_emails") or []}
    labels = _labels(report, allowed)
    home = homes[0]
    out: list[Trip] = []
    open_: dict[str, Any] | None = None

    def close() -> None:
        nonlocal open_
        if open_ is not None:
            out.append(Trip(open_["first"], open_["last"], open_["name"], open_["lat"], open_["lon"], True,
                            tuple(open_["people"]), said=AHEAD_TITLE))  # fmt: skip
        open_ = None

    rows = []
    for line in entries:
        payload = line.get("payload") or {}
        if not isinstance(payload, dict) or str(line.get("id")) in gone or line.get("source") == plan.SOURCE:
            continue
        if payload.get("status") == "cancelled" or (
            allowed is not None and int(line.get("tier") or 0) not in allowed
        ):
            continue
        at, end = stays.instant(line.get("at")), stays.instant(line.get("end"))
        if at is None:
            continue
        begins = bounds.day(at)
        ends = bounds.day(end - timedelta(seconds=1)) if end is not None and end > at else begins
        if begins.isoformat() < today:
            continue
        rows.append((at, begins.isoformat(), max(begins, ends).isoformat(), payload))
    rows.sort(key=lambda r: r[0])
    for _at, first, last_day, payload in rows:
        who = _who(payload, labels, owner)
        title = str(payload.get("title") or "")
        flight = FLIGHT.match(title)
        if flight is not None:
            name = flight.group(1).strip()
            spot = _spot_of(name, by_name, site.airports)
            if spot is not None and places.distance_m(spot[0], spot[1], home.lat, home.lon) <= AWAY_KM * 1000:
                if open_ is not None:
                    open_["last"] = max(open_["last"], first)
                close()
                continue
            close()
            open_ = {"first": first, "last": last_day, "name": name, "people": list(who),
                     "lat": spot[0] if spot else None, "lon": spot[1] if spot else None}  # fmt: skip
            continue
        located = _located(payload, by_name)
        if located is not None:
            name, lat, lon = located
            if places.distance_m(lat, lon, home.lat, home.lon) < AWAY_KM * 1000:
                if open_ is not None and first > open_["last"]:
                    close()  # back home
                continue
            if open_ is not None and _days_between(open_["last"], first) <= OPEN_DAYS:
                open_["last"] = max(open_["last"], last_day)
                open_["people"] += [n for n in who if n not in open_["people"]]
                continue
            close()
            out.append(Trip(first, last_day, name, lat, lon, True, tuple(who), said=AHEAD_TITLE))
            continue
        if open_ is not None and _days_between(open_["last"], first) <= OPEN_DAYS:
            open_["last"] = max(open_["last"], last_day)
            open_["people"] += [n for n in who if n not in open_["people"]]
    close()
    return out


def _days_between(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def _located(payload: Mapping[str, Any], by_name: Mapping[str, Place]) -> tuple[str, float, float] | None:
    """Where an entry is: a named place its `location` names, else its coordinates."""
    where = payload.get("location")
    if isinstance(where, str) and (p := by_name.get(_fold(where.strip()))) is not None:
        return p.name, p.lat, p.lon
    extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
    spot = extra.get("location") if isinstance(extra, dict) else None
    if isinstance(spot, dict):
        try:
            lat, lon = float(spot["latitude"]), float(spot["longitude"])
        except (KeyError, TypeError, ValueError):
            return None
        name = where.strip() if isinstance(where, str) and where.strip() else f"{lat:.2f}, {lon:.2f}"
        return name, lat, lon
    return None


def _spot_of(name: str, by_name: Mapping[str, Place], airports: Airports) -> tuple[float, float] | None:
    """Where a flight's city is: a named place of that name, else its largest airport's city."""
    p = by_name.get(_fold(name))
    if p is not None:
        return p.lat, p.lon
    found = _cities(airports).get(_fold(name))
    return found


@functools.cache
def _cities(airports: Airports) -> dict[str, tuple[float, float]]:
    """The airports' cities, folded, each at its largest airport with scheduled traffic."""
    out: dict[str, tuple[float, float, int]] = {}
    rank = {"large_airport": 2, "medium_airport": 1}
    for airport, _km in airports.within(0.0, 0.0, 30_000.0):
        city = getattr(airport, "city", "") or ""
        if not city or not airport.scheduled:
            continue
        key = _fold(city)
        r = rank.get(airport.type, 0)
        if key not in out or r > out[key][2]:
            out[key] = (airport.lat, airport.lon, r)
    return {k: (v[0], v[1]) for k, v in out.items()}


def _labels(report: people.Report | None, allowed: set[int] | None = None) -> dict[str, str]:
    """An address or a number → the name the record gives the person it belongs to."""
    if report is None:
        return {}
    out: dict[str, str] = {}
    for person in report.known.values():
        if allowed is not None and person.tier not in allowed:
            continue  # named by a line above the gate: the attendee's own name, if the entry gives one
        for _kind, value in person.refs:
            out[str(value).casefold()] = person.name
    return out


def _who(payload: Mapping[str, Any], labels: Mapping[str, str], owner: set[str]) -> list[str]:
    """The attendees who go, by the names the record gives them; never the owner, never a decline."""
    out: list[str] = []
    for a in payload.get("attendees") or []:
        if not isinstance(a, dict) or a.get("response") == "declined":
            continue
        ref = a.get("ref") if isinstance(a.get("ref"), dict) else {}
        value = str(ref.get("value") or "").casefold() if isinstance(ref, dict) else ""
        if value and value in owner:
            continue
        name = labels.get(value) or (str(a.get("name")) if a.get("name") else None)
        if name and name not in out:
            out.append(name)
    return out


def _plan_ahead(site: Site, today: str, shown: Sequence[Place]) -> list[Trip]:
    """The plan's trips dated on or after today: tier 1, so every gate reads them."""
    if site.tiers is not None and plan.TIER not in site.tiers:
        return []
    try:
        mapping = plan.read_mapping(site.lb.root)
    except plan.PlanError:
        return []
    if mapping is None or "trips" not in mapping.databases:
        return []
    bounds = day_start.of(site.lb.meta)
    lines, retracted = plan.notion_lines(site.lb)
    by_name = {_fold(p.name): p for p in shown}
    out = []
    for row in plan.rows_of(lines, retracted).values():
        if row.archived or mapping.role_of(row.database) != "trips":
            continue
        span = plan._span(row, mapping, bounds, "trips")
        if span is None or span[1] < today:
            continue
        name = row.title or "a trip"
        spot = _spot_of(name, by_name, site.airports)
        out.append(Trip(span[0], span[1], name, spot[0] if spot else None, spot[1] if spot else None, True,
                        said=PLAN_TITLE))  # fmt: skip
    return out


# -- the map file's coastlines ------------------------------------------------------------------------------


def coastlines(meta: Mapping[str, Any]) -> list[list[tuple[float, float]]]:
    """The coastlines of the map file `logbook.json` names, as (lon, lat) lines; none without one, or
    when the file is not one this reader reads, or its first zoom is too fine for a globe."""
    try:
        path = map_file(meta)
        st = path.stat()
    except (MapError, OSError):
        return []
    return _coast(str(path), st.st_mtime_ns, st.st_size)


@functools.lru_cache(maxsize=4)
def _coast(path: str, _mtime: int, _size: int) -> list[list[tuple[float, float]]]:
    try:
        with PMTiles(Path(path)) as archive:
            h = archive.header
            z = h.min_zoom
            if z > COAST_ZOOM_MOST:
                return []
            n = 1 << z
            x0, y0 = _tile_of(h.min_lon, h.max_lat, n)
            x1, y1 = _tile_of(h.max_lon, h.min_lat, n)
            tiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)][:COAST_TILES_MOST]
            out: list[list[tuple[float, float]]] = []
            for layer_name in ("earth", "water"):
                for x, y in tiles:
                    data = archive.tile(z, x, y)
                    if data is None:
                        continue
                    for layer in mvt.decode(data, only=(layer_name,)):
                        for feature in layer.features:
                            if feature.type != mvt.POLYGON:
                                continue
                            for ring in feature.geometry:
                                out += _ring_lines(ring, layer.extent, x, y, n)
                if out:
                    return out
            return out
    except (MapError, OSError):
        return []


def _tile_of(lon: float, lat: float, n: int) -> tuple[int, int]:
    lat = max(-85.0511, min(85.0511, lat))
    s = math.sin(math.radians(lat))
    wx, wy = (lon + 180.0) / 360.0, 0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)
    return min(n - 1, max(0, int(wx * n))), min(n - 1, max(0, int(wy * n)))


def _ring_lines(
    ring: Sequence[tuple[int, int]], extent: int, tx: int, ty: int, n: int
) -> list[list[tuple[float, float]]]:
    """A polygon's ring as lines of (lon, lat), cut where it runs along the tile's own edge."""
    points = [*ring, ring[0]] if ring else []
    lines: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []

    def edge(a: tuple[int, int], b: tuple[int, int]) -> bool:
        return any((a[i] <= 0 and b[i] <= 0) or (a[i] >= extent and b[i] >= extent) for i in (0, 1))

    def lonlat(p: tuple[int, int]) -> tuple[float, float]:
        wx, wy = (tx + p[0] / extent) / n, (ty + p[1] / extent) / n
        return wx * 360.0 - 180.0, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * wy))))

    for a, b in itertools.pairwise(points):
        if edge(a, b):
            if len(current) > 1:
                lines.append(current)
            current = []
            continue
        if not current:
            current = [lonlat(a)]
        current.append(lonlat(b))
    if len(current) > 1:
        lines.append(current)
    return lines


# -- the globe ----------------------------------------------------------------------------------------------


class Globe:
    """An orthographic projection centred on (`lat`, `lon`), in the SVG's units."""

    def __init__(self, lat: float, lon: float) -> None:
        self.lat0, self.lon0 = math.radians(lat), math.radians(lon)
        self.c = SIZE / 2

    def at(self, lat: float, lon: float) -> tuple[float, float] | None:
        """The point on the disc, or None on the far side."""
        phi, lam = math.radians(lat), math.radians(lon) - self.lon0
        cos_c = math.sin(self.lat0) * math.sin(phi) + math.cos(self.lat0) * math.cos(phi) * math.cos(lam)
        if cos_c < 0:
            return None
        x = RADIUS * math.cos(phi) * math.sin(lam)
        y = RADIUS * (
            math.cos(self.lat0) * math.sin(phi) - math.sin(self.lat0) * math.cos(phi) * math.cos(lam)
        )
        return self.c + x, self.c - y

    def path(self, lines: Iterable[Sequence[tuple[float, float]]], least: float = 0.0) -> str:
        """`M … L …` of every visible run of every line of (lon, lat), a point kept when it is `least`
        away from the last kept."""
        out: list[str] = []
        for line in lines:
            run: list[tuple[float, float]] = []
            for lon, lat in line:
                p = self.at(lat, lon)
                if p is None:
                    if len(run) > 1:
                        out.append(_d(run))
                    run = []
                    continue
                if run and least and math.dist(run[-1], p) < least:
                    continue
                run.append(p)
            if len(run) > 1:
                out.append(_d(run))
        return " ".join(out)


def _d(run: Sequence[tuple[float, float]]) -> str:
    head, *rest = run
    return f"M{head[0]:.1f},{head[1]:.1f}" + "".join(f"L{x:.1f},{y:.1f}" for x, y in rest)


def _graticule() -> list[list[tuple[float, float]]]:
    lines: list[list[tuple[float, float]]] = []
    steps = int(180 / STEP)
    for lon in range(-180, 180, 30):
        lines.append([(float(lon), -90 + i * STEP) for i in range(steps + 1)])
    for lat in range(-60, 61, 30):
        lines.append([(-180 + i * STEP, float(lat)) for i in range(int(360 / STEP) + 1)])
    return lines


def _centre(reading: Reading, year: int | None) -> Place | None:
    """The home the globe turns to: the home of most days that year (the last year without one)."""
    homes = [p for p in reading.places if p.home] or reading.places
    if not homes:
        return None
    if year is not None:
        lo, hi = f"{year}-01-01", f"{year}-12-31"
    else:
        hi = reading.today
        lo = (date.fromisoformat(hi) - timedelta(days=LAST_YEAR_DAYS)).isoformat()
    return max(homes, key=lambda p: (sum(1 for d in reading.days.get(p.id, []) if lo <= d <= hi), p.home))


def _in(days: Sequence[str], lo: str, hi: str) -> int:
    return sum(1 for d in days if lo <= d <= hi)


def globe_svg(reading: Reading, year: int | None) -> str:
    """The globe as one inline `<svg>` (the module's docstring)."""
    home = _centre(reading, year)
    g = Globe(max(-60.0, min(60.0, home.lat - TILT)), home.lon) if home else Globe(40.0, 10.0)
    c = SIZE / 2
    if year is not None:
        lo, hi = f"{year}-01-01", f"{year}-12-31"
    else:
        hi = reading.today
        lo = (date.fromisoformat(hi) - timedelta(days=LAST_YEAR_DAYS)).isoformat()
    parts = [f'<circle class="disc" cx="{c:.1f}" cy="{c:.1f}" r="{RADIUS:.1f}"/>']
    parts.append(f'<path class="graticule" d="{g.path(_graticule())}"/>')
    if reading.coast:
        drawn = g.path(reading.coast, least=1.5)
        if drawn:
            parts.append(f'<path class="coast" d="{drawn}"/>')
    lived = [t for t in reading.trips if t.first <= hi and t.last >= lo][:ARCS_MOST]
    if year is None:
        coming = list(reading.ahead)
    else:
        coming = [t for t in reading.ahead if t.first[:4] <= str(year) <= t.last[:4]]
    lived = [t for t in lived if not any(n.first <= t.last and t.first <= n.last for n in coming)]
    labels: list[tuple[float, float, str, str]] = []  # the point, the words, the class
    if home is not None:
        start = g.at(home.lat, home.lon)
        for trip, cls in [*((t, "past") for t in lived), *((t, "next") for t in coming[:ARCS_MOST])]:
            if trip.lat is None or trip.lon is None or start is None:
                continue
            end = g.at(trip.lat, trip.lon)
            if end is None or math.dist(start, end) < 1:
                continue
            parts.append(_arc(start, end, cls, c))
            if cls == "next":
                labels.append(
                    (end[0], end[1], f"{trip.name}{DOT}{_day_words(trip.first, reading.today)}", "next")
                )
    ordered = sorted(
        reading.places,
        key=lambda p: (
            not p.home or p is not home,
            -_in(reading.days.get(p.id, []), lo, hi),
            p.name.casefold(),
        ),
    )
    dots = []
    for p in ordered:
        spot = g.at(p.lat, p.lon)
        if spot is None:
            continue
        there = _in(reading.days.get(p.id, []), lo, hi) > 0
        cls = "place home" if p is home else "place"
        if year is not None:
            cls += " bright" if there else " faint"
        x, y = spot
        if p is home:
            glow = "".join(
                f'<circle class="glow" cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill-opacity="{o}"/>'
                for r, o in ((18, ".06"), (12, ".1"), (8, ".18"))
            )
            dots.append(f'<g class="{cls}">{glow}<circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="5"/></g>')
        else:
            dots.append(f'<g class="{cls}"><circle class="dot" cx="{x:.1f}" cy="{y:.1f}" r="3"/></g>')
        if p is home or there or year is None:
            faint = " faint" if year is not None and not there else ""
            labels.append((x, y, p.name, ("home" if p is home else "place") + faint))
    placed = _placed(sorted(labels, key=lambda lab: {"home": 0, "next": 1}.get(lab[3].split()[0], 2)))
    texts = [
        f'<text class="label {cls}" x="{x:.1f}" y="{y:.1f}"'
        + (' text-anchor="end"' if anchor == "end" else "")
        + f">{escape(words)}</text>"
        for x, y, anchor, words, cls in placed
    ]
    turned = f"turned to {home.name}" if home else "with no home named yet"
    when = f" in {year}" if year is not None else ""
    said = f"A globe of your places{when}, {turned}: the places as dots and your trips as arcs from home."
    return (
        f'<svg class="globe" viewBox="0 0 {SIZE:.0f} {SIZE:.0f}" role="img" aria-label="{escape(said)}"'
        ' xmlns="http://www.w3.org/2000/svg">' + "".join(parts) + "".join(dots) + "".join(texts) + "</svg>"
    )


def _placed(
    labels: Sequence[tuple[float, float, str, str]],
) -> list[tuple[float, float, str, str, str]]:
    """At most `LABELS_MOST` labels, each beside its point (right, left, below, above, the first that
    is free), none over another already placed: (x, y, anchor, words, class)."""
    out: list[tuple[float, float, str, str, str]] = []
    boxes: list[tuple[float, float, float, float]] = []
    for x, y, words, cls in labels:
        if len(out) >= LABELS_MOST:
            break
        width = LABEL_CHAR * len(words) + 4
        for tx, ty, anchor in ((x + 9, y + 6, "start"), (x - 9, y + 6, "end"), (x + 6, y + 26, "start"),
                               (x + 6, y - 12, "start")):  # fmt: skip
            x0 = tx - width if anchor == "end" else tx
            box = (x0, ty - LABEL_HIGH, x0 + width, ty + 4)
            if box[0] < 0 or box[2] > SIZE or box[1] < 0 or box[3] > SIZE:
                continue
            if any(box[0] < b[2] and b[0] < box[2] and box[1] < b[3] and b[1] < box[3] for b in boxes):
                continue
            boxes.append(box)
            out.append((tx, ty, anchor, words, cls))
            break
    return out


def _arc(a: tuple[float, float], b: tuple[float, float], cls: str, c: float) -> str:
    """A curve from `a` to `b` lifted to one side of its chord, the side away from the disc's centre,
    as a flight's arc is drawn."""
    mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    chord = math.dist(a, b) or 1.0
    nx, ny = -(b[1] - a[1]) / chord, (b[0] - a[0]) / chord
    if nx * (mx - c) + ny * (my - c) < 0 or (abs(mx - c) < 1 and abs(my - c) < 1 and ny > 0):
        nx, ny = -nx, -ny
    lift = max(8.0, (0.46 if cls == "next" else 0.3) * chord)  # a trip ahead apart from one lived
    qx, qy = mx + nx * lift, my + ny * lift
    dash = ' stroke-dasharray="5 5"' if cls == "next" else ""
    return (
        f'<path class="arc {cls}"{dash} d="M{a[0]:.1f},{a[1]:.1f} Q{qx:.1f},{qy:.1f} {b[0]:.1f},{b[1]:.1f}"/>'
        f'<circle class="end {cls}" cx="{b[0]:.1f}" cy="{b[1]:.1f}" r="2.5"/>'
    )


# -- words --------------------------------------------------------------------------------------------------


def _day_words(day: str, today: str) -> str:
    d = date.fromisoformat(day)
    year = "" if d.year == int(today[:4]) else f" {d.year}"
    return f"{d.day} {MONTHS[d.month - 1]}{year}"


def span_words(first: str, last: str, today: str | None = None) -> str:
    """`15\u201316 June`, `30 June \u2013 2 July`; the year when it is not today's, and always without
    `today`."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    shown = today is None or a.year != int(today[:4]) or b.year != a.year
    year = f" {b.year}" if shown else ""
    if a == b:
        return f"{a.day} {MONTHS[a.month - 1]}{year}"
    if a.year != b.year:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year} {EN_DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    if a.month == b.month:
        return f"{a.day}{EN_DASH}{b.day} {MONTHS[a.month - 1]}{year}"
    return f"{a.day} {MONTHS[a.month - 1]} {EN_DASH} {b.day} {MONTHS[b.month - 1]}{year}"


def _with(names: Sequence[str]) -> str:
    """`with Ola Nordmann and Kari Nordmann`: names only, joined by words, never counted."""
    if not names:
        return ""
    if len(names) == 1:
        return f"with {names[0]}"
    return f"with {', '.join(names[:-1])} and {names[-1]}"


# -- the door -----------------------------------------------------------------------------------------------


def life_years(site: Site, reading: Reading) -> tuple[int, int]:
    """The owner's life bounds (`life` in `logbook.json`, the Life door's setting), else the record's
    first year to next year."""
    found = site.lb.meta.get("life")
    if isinstance(found, dict):
        try:
            a, b = int(str(found["from"])[:4]), int(str(found["to"])[:4])
            if a <= b:
                return a, b
        except (KeyError, ValueError):
            pass
    return reading.first_year, int(reading.today[:4]) + 1


def door(site: Site, year: str | None = None) -> str:
    """The door's part of `/places`: the head, the globe and its scrubber, Next and Your places; the
    register and the queue follow it in `Site.page_places`."""
    reading = read(site)
    first, last = life_years(site, reading)
    at = int(year) if year is not None else None
    out = [
        '<div class="door-places">\n',
        f'<div class="head"><h1>Places</h1>\n<p class="lead">{escape(LEAD)}</p></div>\n',
        '<div class="grid">\n<section class="globe-card" aria-label="The globe">\n',
        globe_svg(reading, at),
        "\n",
        _scrubber(site, reading, first, last, at),
        "</section>\n<div>\n",
        _next(site, reading),
        _mine(site, reading),
        "</div>\n</div>\n</div>\n<!-- /door-places -->\n",
    ]
    return "".join(out)


def _scrubber(site: Site, reading: Reading, first: int, last: int, at: int | None) -> str:
    today = date.fromisoformat(reading.today)
    where = f"{at}" if at is not None else f"{MONTHS[today.month - 1]} {today.year}"
    quiet = at is not None and not any(_in(d, f"{at}-01-01", f"{at}-12-31") for d in reading.days.values())
    quiet = quiet and not any(t.first[:4] <= str(at) <= t.last[:4] for t in [*reading.trips, *reading.ahead])
    lines = (
        (f'<p class="pencil-line">{escape(QUIET.format(year=at))}</p>\n' if quiet else "")
        + f'<p class="pencil-line">Your life, from {first}</p>\n'
        f'<p class="pencil-line">{escape(where)}{DOT}choose a year to travel in time</p>\n'
    )
    if site.static:
        return lines
    years = [first, *(y for y in range(first + 1, last) if y % YEAR_LINKS_EVERY == 0), last]
    years = list(dict.fromkeys(years))
    ends = (first, last)
    links = "".join(
        f'<a href="/places?at={y}"'
        + (' class="half"' if y not in ends and y % (2 * YEAR_LINKS_EVERY) else "")
        + (' aria-current="true"' if y == at else "")
        + f">{y}</a>"
        for y in years
    )
    value = at if at is not None else today.year
    value = max(first, min(last, value))
    ticks = "".join(f'<option value="{y}"></option>' for y in years)
    return (
        f'<div class="scrub-years" role="navigation" aria-label="The years of your life">{links}</div>\n'
        '<form class="scrub" method="get" action="/places">'
        f'<input type="range" name="at" min="{first}" max="{last}" step="1" value="{value}"'
        ' list="door-places-years" aria-label="the year">'
        f'<datalist id="door-places-years">{ticks}</datalist>'
        "<button>Go</button></form>\n" + lines
    )


def _next(site: Site, reading: Reading) -> str:
    out = ['<section class="card next">\n<h2 class="mono">Next</h2>\n']
    shown = reading.ahead[:AHEAD_SHOWN]
    if not shown:
        out.append(f'<p class="empty">{escape(NOTHING_AHEAD)}</p>\n</section>\n')
        return "".join(out)
    out.append('<ol class="rows">\n')
    for t in shown:
        when = span_words(t.first, t.last, reading.today)
        if t.people:
            when += f"{DOT}{_with(t.people)}"
        inner = f'<span class="where">{escape(t.name)}</span><span class="when">{escape(when)}</span>'
        href = site.href(t.link)
        if href is None:
            out.append(f'<li><span class="moment" title="{escape(t.said)}">{inner}</span></li>\n')
        else:
            out.append(
                f'<li><a class="moment" href="{escape(href)}" title="{escape(t.said)}">{inner}</a></li>\n'
            )
    out.append("</ol>\n</section>\n")
    return "".join(out)


def ordered(reading: Reading) -> list[Place]:
    """Your places: home first, then by the days there in the last year, then all told, then by name."""
    lo = (date.fromisoformat(reading.today) - timedelta(days=LAST_YEAR_DAYS)).isoformat()
    centre = _centre(reading, None)
    return sorted(
        reading.places,
        key=lambda p: (
            p is not centre,
            not p.home,
            -_in(reading.days.get(p.id, []), lo, reading.today),
            -len(reading.days.get(p.id, [])),
            p.name.casefold(),
        ),
    )


def _what(site: Site, p: Place) -> str:
    if p.words:
        return f'<span class="what">{escape(p.words)}</span>'
    href = site.href(f"/places/{p.id}#what")
    if href is None:
        return f'<span class="pencil" title="{escape(PLACEHOLDER_TITLE)}">{escape(PLACEHOLDER)}</span>'
    title = escape(PLACEHOLDER_TITLE)
    return f'<a class="pencil" href="{escape(href)}" title="{title}">{escape(PLACEHOLDER)}</a>'


def _mine(site: Site, reading: Reading) -> str:
    out = ['<section class="card mine">\n<h2 class="mono">Your places</h2>\n']
    if not reading.places:
        out.append(f'<p class="empty">{escape(NO_PLACES)}</p>\n</section>\n')
        return "".join(out)
    out.append('<ol class="rows mine">\n')
    for p in ordered(reading):
        href = site.href(f"/places/{p.id}")
        name = (
            f'<a class="place-name" href="{escape(href)}">{escape(p.name)}</a>'
            if href is not None
            else f'<span class="place-name">{escape(p.name)}</span>'
        )
        out.append(f"<li>{name}{_what(site, p)}</li>\n")
    out.append("</ol>\n</section>\n")
    return "".join(out)


# -- one place ----------------------------------------------------------------------------------------------


def page_place(site: Site, place_id: str) -> str:
    """`/places/ID`: one place (the module's docstring)."""
    from .serve import NotFound  # the server's own answer for a path with no page

    reading = read(site)
    found = next((p for p in reading.places if p.id == place_id), None)
    if found is None:
        raise NotFound(f"no place {place_id} in places.json")
    days = reading.days.get(found.id, [])
    what = _what(site, found)
    out = [
        '<div class="door-places place-page">\n',
        f'<p class="crumb">{site.link("&larr; Places", "/places")}</p>\n',
        f'<div class="head"><h1>{escape(found.name)}</h1>\n<p class="lead" id="what">{what}</p></div>\n',
        '<section class="card">\n<h2 class="mono">The days there</h2>\n',
        _strip(site, found, days) if days else f'<p class="empty">{escape(NO_DAYS)}</p>\n',
        "</section>\n",
        '<section class="card">\n<h2 class="mono">Who was there with you</h2>\n',
        _folk(site, people_at(site, reading).get(found.id, [])),
        "</section>\n",
        '<section class="card">\n<h2 class="mono">Trips through it</h2>\n',
        _through(site, reading, found),
        "</section>\n",
    ]
    if not found.words:
        out.append(
            '<p class="pencil-line">What it holds for you is yours to say: a tag on it in places.json'
            " is shown here and on Places, in your words.</p>\n"
        )
    out.append("</div>\n")
    return site.document(found.name, "".join(out), style=STYLE)


def _strip(site: Site, p: Place, days: Sequence[str]) -> str:
    """The days there, a row a year, the latest first: each day a link to its Day, or a busy year's runs."""
    by_year: dict[int, list[date]] = {}
    for d in days:
        day = date.fromisoformat(d)
        by_year.setdefault(day.year, []).append(day)
    out = ['<ol class="strip">\n']
    for year in sorted(by_year, reverse=True):
        found = by_year[year]
        marks = []
        runs = _runs(found) if len(found) > RUN_FROM else [(d, d) for d in found]
        for a, b in runs:
            x = (a - date(year, 1, 1)).days
            w = max(2, (b - a).days + 1)
            rect = f'<rect x="{x}" y="2" width="{w}" height="18"/>'
            href = site.href(f"/day/{a.isoformat()}")
            words = span_words(a.isoformat(), b.isoformat())
            if href is None:
                marks.append(f"<g><title>{escape(words)}</title>{rect}</g>")
            else:
                marks.append(f'<a href="{escape(href)}"><title>{escape(words)}</title>{rect}</a>')
        said = f"Your days at {p.name} in {year}"
        out.append(
            f'<li><span class="y">{year}</span>'
            '<svg class="days" viewBox="0 0 367 22" preserveAspectRatio="none"'
            f' role="img" aria-label="{escape(said)}" xmlns="http://www.w3.org/2000/svg">'
            f'<rect class="base" x="0" y="10" width="367" height="2"/>{"".join(marks)}</svg></li>\n'
        )
    out.append("</ol>\n")
    return "".join(out)


def _runs(found: Sequence[date]) -> list[tuple[date, date]]:
    runs: list[tuple[date, date]] = []
    for d in sorted(found):
        if runs and (d - runs[-1][1]).days == 1:
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


def _folk(site: Site, folk: Sequence[tuple[str, str]]) -> str:
    if not folk:
        return f'<p class="empty">{escape(NOBODY)}</p>\n'
    items = "".join(
        f"<li>{site.link(escape(name), '/people/' + quote(entity, safe=''))}</li>" for entity, name in folk
    )
    return f'<ul class="people">{items}</ul>\n'


def _through(site: Site, reading: Reading, p: Place) -> str:
    """The trips that passed through the place, the latest first: each its days to the return day, in
    the serif, and in pencil where else it went."""
    found = [t for t in reading.trips if p.id in t.places]
    if not found:
        return f'<p class="empty">{escape(FROM_HOME if p.home else NO_TRIPS)}</p>\n'
    names = {q.id: q.name for q in reading.places}
    out = ['<ol class="rows">\n']
    for t in found:
        back = (date.fromisoformat(t.last) + timedelta(days=1)).isoformat()
        elsewhere = [names[i] for i in sorted(t.places) if i != p.id and i in names]
        if t.name != p.name and t.name not in elsewhere:
            elsewhere.insert(0, t.name)
        nights = "the night" if t.first == t.last else "the nights"
        said = f"also {', '.join(elsewhere)}" if elsewhere else f"{nights} at {p.name}"
        inner = (
            f'<span class="where">{escape(span_words(t.first, back))}</span>'
            f'<span class="when">{escape(said)}</span>'
        )
        href = site.href(t.link)
        out.append(
            f'<li><a class="moment" href="{escape(href)}">{inner}</a></li>\n'
            if href is not None
            else f'<li><span class="moment">{inner}</span></li>\n'
        )
    out.append("</ol>\n")
    return "".join(out)
