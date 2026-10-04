"""`logbook export site <folder> [--tier 1|1,2]`: the readers as a folder of static HTML.

The record read back as a site a browser opens from a folder or a web server: one Year page per year
(the page `logbook year --html` writes), every Trip page (`logbook trip --html`, the map inside), a
Days index per year (`logbook serve`'s `/days` table, one row per day the record covers), the places
(`/places`) and the people — an index, and a page per person confirmed present with the years
together and the trips — and a root page that lists the years. Every page is one file with one
inline stylesheet: no script, no image, no font, no stylesheet link, nothing fetched, and every link a
relative path to another file in the folder, so the site reads the same from a file manager, under
any prefix on any web server, or in twenty years. It is `serve` written down: the same renderers
(`serve.Site` with `href`, `year.html`, `trip_page.html`), with the site's navigation above each page.

It is an export, and it is tier-gated exactly like the vault (ADR 0016): the readers read the record
through `reading.read(..., tiers)`, so a line whose tier is not in `--tier` (`1` by default, `1,2`
when `policy/crossing.json` names `site` with a ceiling of 2, never 3) is in no page — not a row, not
a night, not a companion, not a count — and the root page says how many lines were held back. The
resolution lines, the record's name overlay, are read whole as the vault reads them: the gate is on
the line that puts someone somewhere (a calendar entry, a transcript, a note), never on the line that
names them, so a tier-1 site names whoever a tier-1 line confirms present and nobody else. (The MCP
server's gate, `mcp_server.GatedIndex`, holds the resolution lines back too; an agent reading a
private record and a page the owner publishes are not the same crossing.) Health and money are tier
3 and never go to a site. Every run appends one `crossing/v1` line (RFC 0011) with the destination
`site`, the window, the counts and the digest of the folder as written, so the record shows it left;
nothing else is written to the record, and that one write goes through `Logbook.append`.

Re-running rewrites only the files whose content changed and deletes nothing: every page is a
function of the record's lines and settings alone — no head (the Year's and the Trip's footers name
none here, since the crossing line a run appends would move it), no timestamp — so a year that did
not change is a file that did not change, and a file beside the pages (`CNAME`, `.nojekyll`) is never
touched. The window is the whole record: every year with a line, from the first day to the last."""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from ..core import crossing, policy, stays
from ..core import year as year_reader
from ..core.chain import Line
from ..core.flights import Airports
from ..core.store import Logbook, uuid7
from . import serve, trip_page
from .vault import digest, write

__all__ = ["digest", "write"]  # the folder is written and digested as a vault is

DESTINATION = policy.SITE_DESTINATION
TIER_SETS = {"1": (1,), "1,2": (1, 2)}  # tier 3 never goes to a site
YEARS, DAYS, TRIPS, PLACES, PEOPLE = "years", "days", "trips", "places", "people"
INDEX = "index.html"
TRIPS_PAGE, PLACES_PAGE, PEOPLE_PAGE = "trips.html", "places.html", "people.html"
PAGE_NOUNS = {  # a kind of page, singular and plural, for the console
    YEARS: ("year", "years"),
    DAYS: ("days index", "days indexes"),
    TRIPS: ("trip", "trips"),
    PLACES: ("places page", "places page"),
    PEOPLE: ("person", "people"),
}
UNNAMED = "unnamed"
RETRACTION = "retraction"
BOOKKEEPING = frozenset({crossing.KIND, RETRACTION, "resolution", "migration"})  # lines about the record
EN_DASH, ARROW, DOT = year_reader.EN_DASH, year_reader.ARROW, year_reader.DOT


class SiteError(ValueError):
    """A request the record or the policy refuses; the message says why and names the file."""


# -- the request --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """One export, checked against the policy: the record's days and the tiers asked for."""

    since: str  # local days, inclusive: the record's first and last
    until: str
    tiers: tuple[int, ...]
    max_tier: int

    @property
    def years(self) -> list[str]:
        return [str(y) for y in range(int(self.since[:4]), int(self.until[:4]) + 1)]

    def window(self, year: str) -> tuple[str, str]:
        """The year's days inside the record's."""
        return max(f"{year}-01-01", self.since), min(f"{year}-12-31", self.until)


def parse_tiers(text: str) -> tuple[int, ...]:
    """`--tier 1` or `1,2`; `1,2,3` is refused, since tier 3 never goes to a site."""
    key = ",".join(part.strip() for part in text.split(","))
    if key not in TIER_SETS:
        raise SiteError(f"--tier must be 1 or 1,2, not {text!r}; tier 3 never goes to a site")
    return TIER_SETS[key]


def request(lb: Logbook, tiers: tuple[int, ...]) -> Request | None:
    """The whole record, from the first day with a line to the last (a year before the track began
    has its Days index, and its Year page says what the Year reader says of it), held against the
    policy: a tier above the ceiling for `site` is refused naming the file. None when the record has
    no day at all."""
    whole = record_span(lb)
    if whole is None:
        return None
    try:
        max_tier = policy.site_ceiling(lb.root)
    except policy.PolicyError as e:
        raise SiteError(str(e)) from e
    if max(tiers) > max_tier:
        raise SiteError(
            f"--tier {','.join(map(str, tiers))} is above the ceiling for {DESTINATION!r}: "
            f"{policy.policy_path(lb.root)} allows max_tier {max_tier}; "
            f'add {{"{DESTINATION}": {{"max_tier": {max(tiers)}}}}} to it if that is what you want'
        )
    return Request(whole[0], whole[1], tiers, max_tier)


def record_span(lb: Logbook) -> tuple[str, str] | None:
    """The first and last local day with a line that observes a day — every kind but the record's
    own bookkeeping: a crossing (the line each export appends, dated the day it ran), a retraction, a
    resolution (the name overlay) and a migration — so that a run does not move the window of the
    next. None when the record has no such line."""
    with lb.index() as idx:
        spans = [idx.span(str(row["kind"])) for row in idx.kinds() if row["kind"] not in BOOKKEEPING]
    found = [span for span in spans if span is not None]
    if not found:
        return None
    return min(a for a, _b in found), max(b for _a, b in found)


# -- names: file stems and relative paths -------------------------------------------------------------------

NOT_SLUG = re.compile(r"[^a-z0-9]+")
# letters NFKD does not decompose, mapped by hand before the accents are dropped
LETTERS = str.maketrans({"ø": "o", "æ": "ae", "ß": "ss", "đ": "d", "ð": "d", "þ": "th", "ł": "l"})


def slug(name: str) -> str:
    """A page's file stem from a name: lower-case ASCII letters and digits, runs of anything else one
    dash (accents dropped, `Zürich café` → `zurich-cafe`, `Bjørn` → `bjorn`), `unnamed` for nothing.
    A URL on any server and a file name on any platform, with no percent-encoding to get wrong."""
    folded = unicodedata.normalize("NFKD", name.casefold().translate(LETTERS))
    text = NOT_SLUG.sub("-", folded.encode("ascii", "ignore").decode("ascii")).strip("-")
    return text or UNNAMED


class Slugs:
    """The stems claimed so far in one folder: two names that fold to one slug are two pages, the
    second `-2`, the third `-3`. Claiming a name again gives the stem it got."""

    def __init__(self) -> None:
        self._stems: dict[str, str] = {}
        self._taken: set[str] = set()

    def claim(self, name: str) -> str:
        if name in self._stems:
            return self._stems[name]
        stem = slug(name)
        candidate, n = stem, 1
        while candidate in self._taken:
            n += 1
            candidate = f"{stem}-{n}"
        self._stems[name] = candidate
        self._taken.add(candidate)
        return candidate


def relative(src: str, dst: str) -> str:
    """The relative link from page `src` to page `dst`, both folder-relative posix paths."""
    up = len(PurePosixPath(src).parent.parts)
    parts = PurePosixPath(dst).parts
    here = PurePosixPath(src).parent.parts
    common = 0
    while common < min(up, len(parts) - 1) and here[common] == parts[common]:
        common += 1
    return "/".join(("..",) * (up - common) + parts[common:])


def trip_stem(trip_id: str) -> str:
    """`trip:2026-06-15:2026-06-17` → `trip-2026-06-15-2026-06-17`."""
    return trip_id.replace(":", "-")


# -- what one export renders --------------------------------------------------------------------------------


@dataclass
class PersonPage:
    key: str  # the entity id, or `name:<name>` for someone the record names without an entity
    name: str
    years: dict[str, dict[str, Any]] = field(default_factory=dict)  # year → the Year's entry for them
    trips: list[str] = field(default_factory=list)  # trip ids, in order

    @property
    def days(self) -> int:
        return sum(int(y["days"]) for y in self.years.values())

    @property
    def nights(self) -> int:
        return sum(int(y["nights"]) for y in self.years.values())

    @property
    def last_contact(self) -> str:
        return max((str(y["last_contact"] or "") for y in self.years.values()), default="")

    @property
    def span(self) -> str:
        """The first year to the last, one year, or nothing for someone confirmed on a trip and on no Year."""
        if not self.years:
            return ""
        return f"{min(self.years)} {EN_DASH} {max(self.years)}" if len(self.years) > 1 else min(self.years)


@dataclass(frozen=True)
class Build:
    """What one export renders, before anything is written: the files by folder-relative posix path."""

    files: dict[str, bytes]
    pages: dict[str, int]  # per kind of page
    years: int
    logged: int
    crossed: int
    by_tier: dict[str, int]
    by_kind: dict[str, int]
    held_by_kind: dict[str, int]
    warnings: list[str]

    @property
    def held_back(self) -> int:
        return self.logged - self.crossed

    def counts(self) -> dict[str, Any]:
        """RFC 0011's `counts`, in the crossing's shape: a site carries no resolution overlay of its
        own and copies no attachment, so those are zero."""
        return {
            "logged": self.logged,
            "crossed": self.crossed,
            "held_back": self.held_back,
            "by_tier": dict(self.by_tier),
            "by_kind": dict(self.by_kind),
            "resolutions": 0,
            "resolutions_held_back": 0,
            "attachments": {"included": 0, "bytes": 0, "missing": 0},
        }


class _Builder:
    """Reads the record a year at a time through the gate and accumulates the pages; `files()`
    renders them."""

    def __init__(self, lb: Logbook, req: Request, airports: Airports | None) -> None:
        self.lb = lb
        self.req = req
        self.airports = airports or Airports.load()
        self.tz = ZoneInfo(str(lb.meta["timezone"]))
        self.years: dict[str, dict[str, Any]] = {}  # year → `year.read`
        self.days_logged: dict[str, int] = {}  # year → days with a line that crosses
        self.trips: dict[str, dict[str, Any]] = {}  # trip id → `trip_page.read`
        self.trip_of: dict[str, str] = {}  # the id a Year listed (clipped at New Year) → the page's id
        self.people: dict[str, PersonPage] = {}
        self.slugs = Slugs()
        self.warnings: list[str] = []
        self.logged = 0
        self.crossed = 0
        self.by_tier: Counter[int] = Counter()
        self.by_kind: Counter[str] = Counter()
        self.held_by_kind: Counter[str] = Counter()
        footer = (
            f"exported from the record{DOT}tier {','.join(map(str, req.tiers))}{DOT}{escape(str(self.tz))}"
            f"{DOT}nothing here is fetched"
        )
        self.view = serve.Site(lb, self.airports, tiers=req.tiers, href=lambda _path: None, footer=footer)

    # -- reading --

    def read(self) -> None:
        for year in self.req.years:
            first, last = self.req.window(year)
            self._count(first, last)
            data = year_reader.read(self.lb, year, self.airports, self.req.tiers)
            data["head"] = ""  # the page is a function of the lines, never of the head
            self.years[year] = data
            for listed in data["trips"]:
                self._trip(listed)
            for p in data["people"]:
                self._person(p["id"], str(p["name"])).years[year] = p
        for trip in self.trips.values():
            for c in trip["people"]["confirmed"]:
                person = self._person(c["id"], str(c["name"]))
                if trip["id"] not in person.trips:
                    person.trips.append(str(trip["id"]))

    def _count(self, first: str, last: str) -> None:
        """Every line of the window's days, crossing or held back, from the index's columns."""
        since, until = _midnight(first, self.tz), _midnight(_day_after(last), self.tz)
        a, b = stays.instant(since), stays.instant(until)
        with self.lb.index() as idx:
            places = idx.window(since, until)
            logged, _per_source = idx.source_days(first, last, self.req.tiers)
        self.days_logged[first[:4]] = logged
        for place in places:
            at = stays.instant(place.at)
            if place.kind == RETRACTION or at is None or a is None or b is None or not a <= at < b:
                continue
            self.logged += 1
            if place.tier in self.req.tiers:
                self.crossed += 1
                self.by_tier[place.tier] += 1
                self.by_kind[place.kind] += 1
            else:
                self.held_by_kind[place.kind] += 1

    def _trip(self, listed: Mapping[str, Any]) -> None:
        """The Trip page of a trip a Year lists, read whole from its first day (a Year clips a trip
        at New Year; the page is the whole run)."""
        if str(listed["id"]) in self.trip_of:
            return
        try:
            page = trip_page.read(self.lb, str(listed["start"]), self.airports, self.req.tiers)
        except ValueError as e:  # a run the trips reader sees in a year but cannot place on its own
            self.warnings.append(f"trip {listed['id']}: no page: {e}")
            return
        page["head"] = ""
        self.trip_of[str(listed["id"])] = str(page["id"])
        self.trips.setdefault(str(page["id"]), page)

    def _person(self, entity: object, name: str) -> PersonPage:
        key = str(entity) if entity else f"name:{name}"
        page = self.people.get(key)
        if page is None:
            page = self.people[key] = PersonPage(key, name)
            self.slugs.claim(name)
        return page

    # -- paths and links --

    def year_path(self, year: str) -> str:
        return f"{YEARS}/{year}.html"

    def days_path(self, year: str) -> str:
        return f"{DAYS}/{year}.html"

    def trip_path(self, trip_id: str) -> str:
        return f"{TRIPS}/{trip_stem(trip_id)}.html"

    def person_path(self, page: PersonPage) -> str:
        return f"{PEOPLE}/{self.slugs.claim(page.name)}.html"

    def _a(self, here: str, path: str, text: str) -> str:
        """A link from page `here` to page `path`, `text` escaped here."""
        return f'<a href="{escape(relative(here, path))}">{escape(text)}</a>'

    def nav(self, here: str, *extra: str) -> str:
        """The site's navigation from page `here`: the root, the trips, the places, the people, and
        whatever `extra` the page adds (already marked up)."""
        links = [
            ("Logbook", INDEX),
            ("trips", TRIPS_PAGE),
            ("places", PLACES_PAGE),
            ("people", PEOPLE_PAGE),
        ]
        out = "".join(f'<a href="{escape(relative(here, path))}">{text}</a>' for text, path in links)
        return out + "".join(extra)

    def links(self, here: str) -> dict[str, str]:
        """Every link a Year or a Trip page may make: a trip's dates to its page (by the id the Year
        listed, and by the page's own), a person's name to their page."""
        out = {listed: relative(here, self.trip_path(page_id)) for listed, page_id in self.trip_of.items()}
        out |= {page_id: relative(here, self.trip_path(page_id)) for page_id in self.trips}
        for page in self.people.values():
            out.setdefault(f"person:{page.name}", relative(here, self.person_path(page)))
        return out

    # -- rendering --

    def files(self) -> dict[str, bytes]:
        out: dict[str, str] = {}
        years = list(self.years)
        for n, year in enumerate(years):
            here = self.year_path(year)
            pager = [self._a(here, self.days_path(year), f"days of {year}")]
            if n:
                pager.append(self._a(here, self.year_path(years[n - 1]), f"← {years[n - 1]}"))
            if n + 1 < len(years):
                pager.append(self._a(here, self.year_path(years[n + 1]), f"{years[n + 1]} →"))
            out[here] = year_reader.html(self.years[year], self.nav(here, *pager), self.links(here))
            out[self.days_path(year)] = self._days_index(year)
        for trip_id, data in self.trips.items():
            here = self.trip_path(trip_id)
            year = str(data["start"])[:4]
            pager = [self._a(here, self.year_path(year), year)]
            out[here] = trip_page.html(data, self.nav(here, *pager), self.links(here))
        out[TRIPS_PAGE] = self._trips_index()
        out[PLACES_PAGE] = self._places()
        out[PEOPLE_PAGE] = self._people_index()
        for page in self.people.values():
            out[self.person_path(page)] = self._person_page(page)
        out[INDEX] = self._root()
        return {path: text.encode("utf-8") for path, text in out.items()}

    def _document(self, here: str, title: str, body: str) -> str:
        self.view.nav = self.nav(here)
        return self.view.document(title, body)

    def _days_index(self, year: str) -> str:
        here = self.days_path(year)
        first, last = self.req.window(year)
        self.view.nav = self.nav(here, f'<a href="{escape(relative(here, self.year_path(year)))}">{year}</a>')
        return self.view.page_days(first, last)

    def _places(self) -> str:
        self.view.nav = self.nav(PLACES_PAGE)
        return self.view.page_places()

    def _trips_index(self) -> str:
        here = TRIPS_PAGE
        found = sorted(self.trips.values(), key=lambda t: (str(t["start"]), str(t["id"])))
        body = f"<h1>Trips <small>{_plural(len(found), 'trip')}</small></h1>\n"
        if not found:
            body += "<p>no trips: no run of nights away from home</p>\n"
            return self._document(here, "trips", body)
        rows: list[list[serve.Cell]] = []
        for t in found:
            nights = _plural(int(t["nights"]), "night")
            aboard = [a for a in t["nights_aboard"] if a["asset"] == t["asset"]]
            if aboard:
                nights += f" aboard {aboard[0]['name']}"
            if t["in_transit"]:
                nights += f" ({t['in_transit']} in transit)"
            flights = []
            for label, key in (("in", "flights_in"), ("out", "flights_out")):
                for f in t[key]:
                    name = f"{f['carrier']} {f['number']} " if f["number"] else ""
                    flights.append(f"{label} {name}{f['from']} {ARROW} {f['to']}")
            route = [str(s["label"]) for s in t["route"]]
            people = [str(c["name"]) for c in t["people"]["confirmed"]]
            dates = f"{t['start']} {EN_DASH} {t['end']}"
            rows.append(
                [
                    (f'<a href="{escape(relative(here, self.trip_path(str(t["id"]))))}">{dates}</a>', "day"),
                    escape(nights),
                    escape(f" {ARROW} ".join(route)) if route else '<span class="mute">unknown</span>',
                    escape(", ".join(flights)),
                    escape(", ".join(str(p) for p in t["places"])),
                    self._people_links(here, people),
                ]
            )
        body += serve._table(["days", "nights", "route", "flights", "places", "with"], rows)
        return self._document(here, "trips", body)

    def _people_links(self, here: str, names: Iterable[str]) -> str:
        by_name = {page.name: page for page in self.people.values()}
        out = []
        for name in names:
            page = by_name.get(name)
            if page is None:
                out.append(escape(name))
            else:
                out.append(f'<a href="{escape(relative(here, self.person_path(page)))}">{escape(name)}</a>')
        return ", ".join(out)

    def _people_index(self) -> str:
        here = PEOPLE_PAGE
        found = sorted(self.people.values(), key=lambda p: (-p.days, p.name))
        body = f"<h1>People <small>{_plural(len(found), 'person', 'people')} confirmed present</small></h1>\n"
        if not found:
            body += "<p>nobody: no line that crosses confirms anyone present</p>\n"
            return self._document(here, "people", body)
        rows: list[list[serve.Cell]] = [
            [
                self._people_links(here, [p.name]),
                serve._num(p.days),
                serve._num(p.nights),
                escape(p.span),
                escape(p.last_contact),
                serve._num(len(p.trips)),
            ]
            for p in found
        ]
        body += serve._table(
            ["person", ("days", "num"), ("nights", "num"), "years", "last", ("trips", "num")], rows
        )
        return self._document(here, "people", body)

    def _person_page(self, page: PersonPage) -> str:
        here = self.person_path(page)
        head = [_plural(page.days, "day") + " together", _plural(page.nights, "night")]
        if page.span:
            head.append(page.span)
        if page.last_contact:
            head.append(f"last {page.last_contact}")
        body = f"<h1>{escape(page.name)}</h1>\n<p>{escape(DOT.join(head))}</p>\n<h2>Years</h2>\n"
        if not page.years:
            body += '<p class="mute">on no Year: confirmed present on a trip alone</p>\n'
        rows: list[list[serve.Cell]] = []
        for year, entry in sorted(page.years.items()):
            rows.append(
                [
                    (f'<a href="{escape(relative(here, self.year_path(year)))}">{year}</a>', "day"),
                    serve._num(int(entry["days"])),
                    serve._num(int(entry["nights"])),
                    serve._num(int(entry["stays"])),
                    escape(str(entry["last_contact"] or "")),
                    escape(", ".join(str(p) for p in entry["places"])),
                ]
            )
        if rows:
            body += serve._table(
                ["year", ("days", "num"), ("nights", "num"), ("stays", "num"), "last", "places"], rows
            )
        body += "<h2>Trips</h2>\n"
        if page.trips:
            body += '<ul class="plain">\n'
            for trip_id in page.trips:
                t = self.trips[trip_id]
                dates = f"{t['start']} {EN_DASH} {t['end']}"
                body += (
                    f'<li><a href="{escape(relative(here, self.trip_path(trip_id)))}">{dates}</a>'
                    f"{DOT}{_plural(int(t['nights']), 'night')}</li>\n"
                )
            body += "</ul>\n"
        else:
            body += '<p class="mute">none</p>\n'
        return self._document(here, page.name, body)

    def _root(self) -> str:
        here = INDEX
        tiers = ",".join(map(str, self.req.tiers))
        body = (
            "<h1>Logbook</h1>\n"
            f"<p>{self.crossed:,} lines, {self.req.since} {EN_DASH} {self.req.until} ({escape(str(self.tz))})"
            f"{DOT}tier {tiers}"
            + (
                f"{DOT}held back: {self.held_back:,} lines above tier {max(self.req.tiers)}"
                if self.held_back
                else ""
            )
            + "</p>\n<h2>Years</h2>\n"
        )
        rows: list[list[serve.Cell]] = []
        for year, data in self.years.items():
            trips = [self.trip_of.get(str(t["id"])) for t in data["trips"]]
            rows.append(
                [
                    (f'<a href="{escape(relative(here, self.year_path(year)))}">{year}</a>', "day"),
                    (
                        f'<a href="{escape(relative(here, self.days_path(year)))}">'
                        f"{self.days_logged.get(year, 0):,}</a>",
                        "num",
                    ),
                    serve._num(len({t for t in trips if t})),
                    serve._num(int(data["nights"]["away"])),
                    serve._num(len(data["people"])),
                ]
            )
        body += serve._table(
            ["year", ("days", "num"), ("trips", "num"), ("nights away", "num"), ("people", "num")], rows
        )
        body += (
            '<ul class="plain">\n'
            f'<li><a href="{TRIPS_PAGE}">Trips</a>: every run of nights away,'
            f" {_plural(len(self.trips), 'page')}.</li>\n"
            f'<li><a href="{PLACES_PAGE}">Places</a>: the named places of the record.</li>\n'
            f'<li><a href="{PEOPLE_PAGE}">People</a>: {_plural(len(self.people), "person", "people")}'
            " confirmed present.</li>\n</ul>\n"
        )
        for warning in self.warnings:
            body += f'<p class="mute">{escape(warning)}</p>\n'
        return self._document(here, "Logbook", body)

    @property
    def held_back(self) -> int:
        return self.logged - self.crossed


def build(lb: Logbook, req: Request, airports: Airports | None = None) -> Build:
    """Read the record and render every page; nothing is written. `stays.SettingsError` when the
    record's settings, places or assets file is not what it should be."""
    builder = _Builder(lb, req, airports)
    builder.read()
    files = builder.files()
    pages = {
        YEARS: len(builder.years),
        DAYS: len(builder.years),
        TRIPS: len(builder.trips),
        PLACES: 1,
        PEOPLE: len(builder.people),
    }
    return Build(
        files,
        pages,
        len(builder.years),
        builder.logged,
        builder.crossed,
        {str(t): builder.by_tier.get(t, 0) for t in policy.TIERS},
        dict(sorted(builder.by_kind.items())),
        dict(sorted(builder.held_by_kind.items())),
        list(builder.warnings),
    )


# -- writing, and the line that says it left -----------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    folder: Path
    written: int
    unchanged: int
    sha256: str  # of the folder as written: every file's digest and path, in path order
    line: Line  # the crossing/v1 line appended


def export(lb: Logbook, req: Request, built: Build, folder: Path, generated_at: str) -> Result:
    """Write the folder, then append the crossing line: in that order, so a crash leaves at worst a
    folder no line names, and the next run writes the same files again and does name it."""
    policy.write_default(lb.root)  # the first export writes the default; an existing file is kept
    head = str(lb.meta["head"])
    written, unchanged = write(folder, built.files)
    sha256 = digest(built.files)
    line = lb.append(
        at=generated_at,
        source=crossing.SOURCE,
        kind=crossing.KIND,
        tier=1,
        payload={
            "schema": crossing.LINE_SCHEMA,
            "destination": DESTINATION,
            "bundle_id": uuid7(),
            "window": {
                "from": _midnight(req.since, ZoneInfo(str(lb.meta["timezone"]))),
                "to": _midnight(_day_after(req.until), ZoneInfo(str(lb.meta["timezone"]))),
            },
            "tiers": list(req.tiers),
            "counts": built.counts(),
            "policy": {"file": policy.POLICY_FILE.as_posix(), "max_tier": req.max_tier},
            "logbook_head": head,
            "package_sha256": sha256,
            "extra": {
                "site": {
                    "years": built.years,
                    "pages": dict(built.pages),
                    "files": {"written": written, "unchanged": unchanged, "total": len(built.files)},
                }
            },
        },
        recorded_at=generated_at,
    )
    return Result(Path(folder), written, unchanged, sha256, line)


# -- helpers -----------------------------------------------------------------------------------------------


def _day_after(day: str) -> str:
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def _midnight(day: str, tz: ZoneInfo) -> str:
    local = datetime.combine(date.fromisoformat(day), time.min, tzinfo=tz)
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {plural or noun + 's'}"
