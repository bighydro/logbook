"""`logbook serve [--port N]`: the record read in a browser, from this machine only.

A reader (ADR 0013) with another output: server-rendered HTML in place of text, one page per
reader the commands already have. `/day/YYYY-MM-DD` is the Day (`day.read`) as a timeline, each
row's attachments and company folded under a toggle; `/days?from=&to=` is a window one row per
day (`days.read`), each row a link to its Day; `/trips?year=` the trips of a year (`trips.trips`
over one `reading.read`); `/places` the named places of `places.json`; `/assets` the registered
assets and the last fix of each (`asset_status.read`); `/gaps` where each source went quiet
(`gaps.report`). Every page is built from the index and the readers, so a Day renders in the time
`logbook day` takes whatever the record's length, and nothing is written: every request is a GET
answered from the record at its head.

Three rules, each enforced here and tested in `tests/test_serve.py`:

- The server binds 127.0.0.1 and refuses any other host (`HostError`, raised before a socket is
  opened), so the record is readable from this machine and nowhere else. It never resolves a
  name, not even its own.
- A page is one HTML document with one inline stylesheet: no script, no font, no image, no
  stylesheet link, and no reference to any URL but the server's own paths. The
  Content-Security-Policy header says the same to the browser, so nothing a payload carried could
  make a page fetch from elsewhere even if the escaping here were wrong.
- Read-only. The pages call the readers; the readers never write (not even `policy/stays.json`).

The text grammar is the commands' own (`day.span_text`, `days.night_text`, `gaps.runs`, …), so a
row reads here as it prints there."""

from __future__ import annotations

import re
import socketserver
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import parse_qs
from zoneinfo import ZoneInfo

from . import asset_status, assets, gaps, places, reading, stays, trips, weather
from . import day as day_reader
from . import days as days_reader
from .export import parse_day
from .flights import Airports
from .store import Logbook

HOST = "127.0.0.1"  # the one host the server binds; anything else is refused
PORT = 8765
WINDOW_DAYS = 14  # `/days` without a window: the record's last fortnight
HEAD_CHARS = 12
CSP = "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'"
DAY_PATH = re.compile(r"^/day/(\d{4}-\d{2}-\d{2})$")
YEAR = re.compile(r"^\d{4}$")
EN_DASH, ARROW, DOT = day_reader.EN_DASH, day_reader.ARROW, day_reader.DOT
HTML = "text/html; charset=utf-8"
Cell = str | tuple[str, str]  # a table cell: text, or (text, css class)

STYLE = """
:root{color-scheme:light dark;--fg:#1c1c1c;--bg:#fff;--mute:#6a6a6a;--line:#ddd;--accent:#2f5d7c}
@media (prefers-color-scheme:dark){
:root{--fg:#e8e8e8;--bg:#141414;--mute:#9b9b9b;--line:#333;--accent:#8fb8d6}}
body{margin:0;font:15px/1.45 system-ui,sans-serif;color:var(--fg);background:var(--bg)}
header{border-bottom:1px solid var(--line);padding:.6rem 1rem}
nav a{margin-right:1rem;color:var(--accent);text-decoration:none}
nav a:first-child{font-weight:600}
main{max-width:66rem;margin:0 auto;padding:1rem}
footer{color:var(--mute);font-size:.85rem;padding:1rem;border-top:1px solid var(--line)}
a{color:var(--accent)}
h1{margin:.2rem 0 .6rem}
h1 small{color:var(--mute);font-weight:400;font-size:.6em}
h2{font-size:1.1rem;margin:1.4rem 0 .5rem}
table{border-collapse:collapse;width:100%}
th,td{text-align:left;padding:.3rem .5rem;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mute);font-weight:500}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
td.day{white-space:nowrap}
dl.header{display:grid;grid-template-columns:max-content 1fr;gap:.2rem 1rem;margin:0 0 1rem}
dl.header dt{color:var(--mute)}
dl.header dd{margin:0}
ol.timeline,ol.inside,ul.attached,ul.unplaced,ul.plain{list-style:none;padding:0;margin:0}
.row{padding:.4rem 0;border-bottom:1px solid var(--line)}
.clock{display:inline-block;min-width:7.5rem;font-variant-numeric:tabular-nums;color:var(--mute)}
.kind{display:inline-block;min-width:5.5rem;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em;color:var(--mute)}
.row.stay>.kind{color:#2e8b57}
.row.move>.kind{color:#3a6ec4}
.row.flight>.kind{color:#c0652a}
.row.aboard>.kind{color:#1f7f9a}
.row.gap>.kind{color:#c43b3b}
ol.inside{margin:.3rem 0 0 2rem}
ol.inside .row{border:0;padding:.15rem 0}
details{margin:.3rem 0 0 7.5rem}
summary{cursor:pointer;color:var(--accent)}
ul.attached{margin:.3rem 0 0 1rem}
ul.attached li,ul.unplaced li{padding:.15rem 0}
p.with{margin:.3rem 0 0 1rem;color:var(--mute)}
form.window{display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin:0 0 1rem}
input,button{font:inherit;padding:.2rem .4rem;background:var(--bg);color:var(--fg);
border:1px solid var(--line);border-radius:3px}
p.pager,p.mute,.mute{color:var(--mute)}
"""

NAV = (
    '<a href="/">Logbook</a><a href="/days">days</a><a href="/trips">trips</a>'
    '<a href="/places">places</a><a href="/assets">assets</a><a href="/gaps">gaps</a>'
)


class HostError(ValueError):
    """A host other than 127.0.0.1 was asked for."""


class NotFound(Exception):
    """No page at this path."""


class Response(NamedTuple):
    status: int
    body: bytes
    content_type: str = HTML

    @property
    def headers(self) -> dict[str, str]:
        found = {
            "Content-Type": self.content_type,
            "Content-Security-Policy": CSP,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        }
        if self.status != 204:
            found["Content-Length"] = str(len(self.body))
        return found


# -- the site --------------------------------------------------------------------------------------------


class Site:
    """The pages of one record. `respond(path, query)` is pure: the same record at the same head
    and the same request give the same page. The airports table is loaded once, here."""

    def __init__(
        self, lb: Logbook, airports: Airports | None = None, now: Callable[[], datetime] | None = None
    ):
        self.lb = lb
        self.airports = airports or Airports.load()
        self.now = now or (lambda: datetime.now(UTC))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(str(self.lb.meta["timezone"]))

    def respond(self, path: str, query: str = "") -> Response:
        if path == "/favicon.ico":
            return Response(204, b"", "image/x-icon")
        params = {k: v[-1] for k, v in parse_qs(query, keep_blank_values=True).items()}
        try:
            return Response(200, self._page(path, params).encode("utf-8"))
        except NotFound:
            return self._error(404, f"no page at {path}")
        except (stays.SettingsError, places.PlaceError, assets.AssetError) as e:
            return self._error(500, str(e))
        except ValueError as e:  # a day that is not one, a window that runs backwards, a year that is not
            return self._error(400, str(e))

    def _page(self, path: str, params: Mapping[str, str]) -> str:
        if path == "/":
            return self.page_index()
        if (m := DAY_PATH.match(path)) is not None:
            return self.page_day(m.group(1), expanded=params.get("open") == "1")
        if path == "/days":
            return self.page_days(params.get("from") or None, params.get("to") or None)
        if path == "/trips":
            return self.page_trips(params.get("year") or None)
        if path == "/places":
            return self.page_places()
        if path == "/assets":
            return self.page_assets()
        if path == "/gaps":
            return self.page_gaps(params.get("since") or None)
        raise NotFound(path)

    def _error(self, status: int, message: str) -> Response:
        body = f"<h1>{status}</h1>\n<p>{escape(message)}</p>\n"
        return Response(status, self._document(str(status), body).encode("utf-8"))

    def _document(self, title: str, body: str) -> str:
        meta = self.lb.meta
        head = str(meta.get("head") or "")[:HEAD_CHARS]
        footer = (
            f"read-only{DOT}head <code>{escape(head)}…</code>{DOT}{escape(str(meta.get('timezone')))}"
            f"{DOT}nothing here leaves this machine"
        )
        return (
            "<!doctype html>\n"
            '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{escape(title)} · Logbook</title>\n"
            f"<style>{STYLE}</style>\n</head>\n<body>\n"
            f"<header><nav>{NAV}</nav></header>\n<main>\n{body}</main>\n"
            f"<footer>{footer}</footer>\n</body>\n</html>\n"
        )

    def _whole(self) -> tuple[str, str] | None:
        """The days the owner's track covers, else any line's; None for an empty record."""
        return reading.record_days(self.lb, "location") or reading.record_days(self.lb)

    # -- / --------------------------------------------------------------------------------------------------

    def page_index(self) -> str:
        with self.lb.index() as idx:
            total, first, last = idx.totals()
        whole = self._whole()
        parts = ["<h1>Logbook</h1>\n"]
        if whole is None or first is None or last is None:
            parts.append("<p>The record has no lines yet.</p>\n")
            return self._document("Logbook", "".join(parts))
        tz = self.tz
        parts.append(
            f"<p>{total:,} lines, {escape(_local_day(first, tz))} {EN_DASH} {escape(_local_day(last, tz))}"
            f" ({escape(str(tz))}).</p>\n"
        )
        a, b = _last_window(whole)
        year = whole[1][:4]
        parts.append(
            '<ul class="plain">\n'
            f'<li><a href="/day/{whole[1]}">The last day</a>, {whole[1]}: the Day as a timeline.</li>\n'
            f'<li><a href="/days?from={a}&amp;to={b}">The last fortnight</a>, one row per day.</li>\n'
            f'<li><a href="/trips?year={year}">Trips of {year}</a>: runs of nights away.</li>\n'
            '<li><a href="/places">Places</a>: the named places of the record.</li>\n'
            '<li><a href="/assets">Assets</a>: the assets tracked and the last fix of each.</li>\n'
            '<li><a href="/gaps">Gaps</a>: where each source went quiet.</li>\n'
            "</ul>\n"
        )
        return self._document("Logbook", "".join(parts))

    # -- /day/YYYY-MM-DD ------------------------------------------------------------------------------------

    def page_day(self, day: str, expanded: bool = False) -> str:
        """The Day; with `expanded` every toggle is open, so a page prints or saves whole."""
        data = day_reader.read(self.lb, day, self.airports)
        tz = ZoneInfo(data["tz"])
        d = date.fromisoformat(day)
        before, after = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat()
        a, b = (d - timedelta(days=6)).isoformat(), (d + timedelta(days=7)).isoformat()
        parts = [
            f"<h1>{day} <small>{escape(data['weekday'])}</small></h1>\n",
            f'<p class="pager"><a href="/day/{before}">← {before}</a>{DOT}'
            f'<a href="/days?from={a}&amp;to={b}">the fortnight around</a>{DOT}'
            + (
                f'<a href="/day/{day}">collapse all</a>'
                if expanded
                else f'<a href="/day/{day}?open=1">expand all</a>'
            )
            + f'{DOT}<a href="/day/{after}">{after} →</a></p>\n',
            '<dl class="header">\n',
            _dt("night before", day_reader.night_text(data["nights"]["before"])),
            _dt("night after", day_reader.night_text(data["nights"]["after"])),
            _dt("country", day_reader.country_text(data["country"])),
        ]
        if data["all_day"]:
            parts.append(
                _dt("all day", ", ".join(a["title"] + day_reader.sources_text(a) for a in data["all_day"]))
            )
        parts.append("</dl>\n<h2>Timeline</h2>\n")
        if data["timeline"]:
            parts.append('<ol class="timeline">\n')
            parts.extend(_entry_html(entry, tz, expanded=expanded) for entry in data["timeline"])
            parts.append("</ol>\n")
        else:
            parts.append('<p class="mute">nothing logged</p>\n')
        if data["unplaced"]:
            parts.append('<h2>Unplaced</h2>\n<ul class="unplaced">\n')
            for item in data["unplaced"]:
                span = day_reader.span_text(item["at"], item["end"], tz)
                parts.append(
                    f'<li title="line {escape(item["line"])}"><span class="clock">{escape(span)}</span> '
                    f'<span class="kind">{escape(item["kind"])}</span> '
                    f"{escape(item['title'] + day_reader.sources_text(item))}</li>\n"
                )
            parts.append("</ul>\n")
        parts.append(f"<h2>Health</h2>\n<p>{escape(day_reader.health_text(data['health']))}</p>\n")
        if data.get("weather"):
            parts.append(f"<h2>Weather</h2>\n<p>{escape(weather.text(data['weather'], data['tz']))}</p>\n")
        parts.append("<h2>Sources</h2>\n")
        if data["sources"]:
            rows: list[list[Cell]] = [
                [
                    escape(s["source"]),
                    _num(s["lines"]),
                    escape(_clock(s["first"], tz)),
                    escape(_clock(s["newest"], tz)),
                ]
                for s in data["sources"]
            ]
            parts.append(_table(["source", ("lines", "num"), "first", "last"], rows))
        else:
            parts.append('<p class="mute">none</p>\n')
        return self._document(f"{day} {data['weekday']}", "".join(parts))

    # -- /days ----------------------------------------------------------------------------------------------

    def page_days(self, first: str | None, last: str | None) -> str:
        whole = self._whole()
        if whole is None:
            return self._document("days", "<h1>Days</h1>\n<p>no days: the record has no lines</p>\n")
        if last is None:
            last = whole[1] if first is None else _clip(first, WINDOW_DAYS - 1, whole)
        else:
            last = parse_day(last).isoformat()
        first = _clip(last, -(WINDOW_DAYS - 1), whole) if first is None else parse_day(first).isoformat()
        rows: list[list[Cell]] = []
        for r in days_reader.read(self.lb, first, last, self.airports):
            people = ", ".join(r["people"]["names"])
            rows.append(
                [
                    (f'<a href="/day/{r["day"]}">{r["day"]}</a>', "day"),
                    escape(r["weekday"][:3]),
                    escape(days_reader.night_text(r)),
                    (escape(days_reader.km_text(r["moved_m"])), "num"),
                    escape(", ".join(days_reader.flight_text(f) for f in r["flights"])),
                    escape(days_reader.stays_text(r["stays"]) if r["sources"] else "nothing logged"),
                    escape(people),
                    escape(day_reader.health_text(r["health"]) if r["health"] is not None else ""),
                    escape(", ".join(r["gaps"])),
                ]
            )
        span = (date.fromisoformat(last) - date.fromisoformat(first)).days + 1
        earlier = (
            (date.fromisoformat(first) - timedelta(days=span)).isoformat(),
            (date.fromisoformat(first) - timedelta(days=1)).isoformat(),
        )
        later = (
            (date.fromisoformat(last) + timedelta(days=1)).isoformat(),
            (date.fromisoformat(last) + timedelta(days=span)).isoformat(),
        )
        body = (
            f"<h1>Days <small>{first} {EN_DASH} {last}</small></h1>\n"
            f'<form class="window" action="/days" method="get">'
            f'<label>from <input type="date" name="from" value="{first}"></label> '
            f'<label>to <input type="date" name="to" value="{last}"></label> '
            f"<button>show</button></form>\n"
            f'<p class="pager"><a href="/days?from={earlier[0]}&amp;to={earlier[1]}">← earlier</a>{DOT}'
            f'<a href="/days?from={later[0]}&amp;to={later[1]}">later →</a>{DOT}'
            f"the record runs {whole[0]} {EN_DASH} {whole[1]}</p>\n"
        )
        body += _table(
            ["day", "", "night", ("moved", "num"), "flights", "stays", "with", "health", "gaps"], rows
        )
        return self._document(f"days {first} {EN_DASH} {last}", body)

    # -- /trips ---------------------------------------------------------------------------------------------

    def page_trips(self, year: str | None) -> str:
        whole = self._whole()
        if whole is None:
            return self._document("trips", "<h1>Trips</h1>\n<p>no trips: the record has no days</p>\n")
        year = year or whole[1][:4]
        if not YEAR.fullmatch(year):
            raise ValueError(f"not a year (YYYY): {year!r}")
        years = range(int(whole[0][:4]), int(whole[1][:4]) + 1)
        links = DOT.join(
            f"<b>{y}</b>" if str(y) == year else f'<a href="/trips?year={y}">{y}</a>' for y in years
        )
        parts = [f"<h1>Trips <small>{year}</small></h1>\n", f'<p class="pager">{links}</p>\n']
        first, last = max(f"{year}-01-01", whole[0]), min(f"{year}-12-31", whole[1])
        if last < first:
            parts.append(f"<p>no days in {year}: the record runs {whole[0]} {EN_DASH} {whole[1]}</p>\n")
            return self._document(f"trips {year}", "".join(parts))
        rd = reading.read(self.lb, first, last, self.airports)
        found, warning = trips.trips(rd)
        if warning:
            parts.append(f"<p>{escape(warning)}</p>\n")
        elif not found:
            parts.append(f"<p>no trips {first} {EN_DASH} {last}</p>\n")
        else:
            parts.append(
                _table(
                    ["days", "nights", "route", "flights", "places", "with"],
                    [_trip_row(t, rd) for t in found],
                )
            )
        return self._document(f"trips {year}", "".join(parts))

    # -- /places, /assets, /gaps ----------------------------------------------------------------------------

    def page_places(self) -> str:
        found = places.read(self.lb.root)
        body = "<h1>Places</h1>\n"
        if not found:
            body += (
                f"<p>no places ({escape(places.PLACES_FILE)}): `logbook places add` or `places propose`</p>\n"
            )
            return self._document("places", body)
        rows: list[list[Cell]] = [
            [
                escape(p.name),
                (f"{p.lat:.4f},{p.lon:.4f}", "num"),
                (escape(_number(p.radius_m)) + " m", "num"),
                escape(p.kind),
                escape(", ".join(p.tags)),
                escape(p.country or ""),
            ]
            for p in found
        ]
        body += _table(["name", ("position", "num"), ("radius", "num"), "kind", "tags", "country"], rows)
        return self._document("places", body)

    def page_assets(self) -> str:
        registry = assets.read(self.lb.root)
        body = "<h1>Assets</h1>\n"
        if not registry:
            body += f"<p>no assets registered ({escape(assets.ASSETS_FILE)}); `logbook assets add`</p>\n"
            return self._document("assets", body)
        named = places.read(self.lb.root)
        statuses = asset_status.read(self.lb, registry, named, self.now())
        tz = self.tz
        rows: list[list[Cell]] = []
        for status in statuses:
            asset, fix = status.asset, status.fix
            ids = ", ".join(f"{k} {v}" for k in assets.IDENTIFIERS if (v := getattr(asset, k)) is not None)
            row: list[Cell] = [escape(asset.id), escape(asset.kind), escape(asset.name), escape(ids)]
            if fix is None:
                row += [("no fix yet", ""), "", "", "", ""]
            else:
                near = "" if fix.near is None else f"near {fix.near[0]}, {_metres(fix.near[1])}"
                row += [
                    escape(_clock(fix.at, tz)),
                    (f"{fix.lat:.4f},{fix.lon:.4f}", "num"),
                    escape(near),
                    ("" if fix.speed_mps is None else f"{fix.speed_mps:.1f} m/s", "num"),
                    escape(asset_status.age_text(fix.age_s)),
                ]
            rows.append(row)
        body += _table(
            [
                "id",
                "kind",
                "name",
                "identifiers",
                "last fix",
                ("position", "num"),
                "near",
                ("speed", "num"),
                "age",
            ],
            rows,
        )
        return self._document("assets", body)

    def page_gaps(self, since: str | None) -> str:
        data = gaps.report(self.lb, since=since)
        tz = ZoneInfo(data["timezone"])
        body = (
            "<h1>Gaps <small>where each source went quiet</small></h1>\n"
            f'<form class="window" action="/gaps" method="get">'
            f'<label>since <input type="date" name="since" value="{escape(data["since"] or "")}"></label> '
            "<button>show</button></form>\n"
        )
        if not data["sources"]:
            body += "<p>no lines</p>\n"
            return self._document("gaps", body)
        rows: list[list[Cell]] = []
        for s in data["sources"]:
            if s["lines"] == 0:
                rows.append([escape(s["source"]), ("0", "num"), "", "", "no lines", ("0", "num"), ""])
                continue
            silence = s["silence"]
            if silence["to"] is None:
                stretch = f"{gaps.duration(silence['seconds'])} since {_clock(silence['from'], tz)}"
            else:
                ends = f"{_clock(silence['from'], tz)} {ARROW} {_clock(silence['to'], tz)}"
                stretch = f"{gaps.duration(silence['seconds'])} {ends}"
            missing = s["missing_days"]
            rows.append(
                [
                    escape(s["source"]),
                    _num(s["lines"]),
                    escape(_clock(s["first"], tz)),
                    escape(_clock(s["last"], tz)),
                    escape(stretch),
                    _num(len(missing)),
                    escape(gaps.runs(missing)),
                ]
            )
        body += _table(
            ["source", ("lines", "num"), "first", "last", "longest silence", ("missing days", "num"), ""],
            rows,
        )
        span = f"since {data['since']}" if data["since"] else "since each source's first line"
        body += (
            f'<p class="mute">{escape(span)}, today {escape(data["today"])} ({escape(data["timezone"])});'
            " counted through the index, every line, retracted or not</p>\n"
        )
        return self._document("gaps", body)


# -- the Day's rows ---------------------------------------------------------------------------------------


def _entry_html(entry: Mapping[str, Any], tz: ZoneInfo, inside: bool = False, expanded: bool = False) -> str:
    """One timeline row: the clock, the kind, what it was; then an `aboard` entry's inner rows;
    then, behind a toggle, the attachments by name and the company. The grammar is `day.rows`'."""
    if entry["kind"] == day_reader.FLIGHT:
        route = f"{entry['carrier']} {entry['number']}  {entry['from']} {ARROW} {entry['to']}"
        clock = day_reader.span_text(entry["start"], entry["end"], tz)
        return (
            f'<li class="row flight" title="line {escape(str(entry["line"]))}">'
            f'<span class="clock">{escape(clock)}</span> <span class="kind">flight</span> '
            f"{escape(route)}{DOT}{escape(str(entry['evidence']))}</li>\n"
        )
    clock = day_reader.span_text(entry["within_day"]["start"], entry["within_day"]["end"], tz, clip=True)
    kind = day_reader.GAP if entry["gap"] else str(entry["kind"])
    parts: list[str] = []
    if entry["kind"] == day_reader.ABOARD:
        asset = entry["asset"]
        head = asset["name"] + (f" ({asset['kind']})" if asset["kind"] else "")
        parts = [head, day_reader.duration_text(entry["within_day"]["duration_s"])]
    elif entry["kind"] == stays.MOVE:
        parts = [day_reader.duration_text(entry["within_day"]["duration_s"])]
        if entry["gap"]:
            parts.append("no points")
            parts.append(day_reader.distance_text(entry["distance_m"] or 0))
        else:
            parts.insert(0, day_reader.distance_text(entry["distance_m"] or 0))
            parts.append(entry["mode"] or "mode unknown")
            if entry["airports"]:
                parts.append(f"{entry['airports'][0]} {ARROW} {entry['airports'][1]}")
            if entry.get("aboard") and not inside:
                parts.append(f"aboard {entry['aboard']}")
    else:
        parts = [str(entry["where"]), day_reader.duration_text(entry["within_day"]["duration_s"])]
        if entry.get("aboard") and not inside:
            parts.append(f"aboard {entry['aboard']}")
    counts = day_reader.counts(entry.get("attached"))
    company = entry.get("with") or {}
    confirmed, proposed = company.get("confirmed") or [], company.get("proposed") or []
    if not counts and not confirmed and not proposed and entry["kind"] == stays.STOP and not inside:
        parts.append("nothing attached")
    out = [
        f'<li class="row {escape(kind)}"><span class="clock">{escape(clock)}</span> '
        f'<span class="kind">{escape(kind)}</span> {escape(DOT.join(parts))}'
    ]
    if entry.get("inside"):
        out.append('\n<ol class="inside">\n')
        out.extend(
            _entry_html({**s, "attached": None, "with": None}, tz, inside=True, expanded=expanded)
            for s in entry["inside"]
        )
        out.append("</ol>")
    if counts or confirmed or proposed:
        summary = ", ".join(_plural(n, noun) for n, noun in counts)
        if confirmed or proposed:
            n = len(confirmed) + len(proposed)
            summary = f"{summary}{DOT}with {n}" if summary else f"with {n}"
        out.append(f"\n<details{' open' if expanded else ''}><summary>{escape(summary)}</summary>\n")
        out.append(_attached_html(entry.get("attached"), tz))
        if confirmed or proposed:
            text = ", ".join(day_reader.companion_text(c) for c in confirmed)
            more = ", ".join(day_reader.companion_text(c) for c in proposed)
            if more:
                text = f"{text}{DOT}proposed {more}" if text else f"proposed {more}"
            out.append(f'<p class="with">with {escape(text)}</p>\n')
        out.append("</details>")
    out.append("</li>\n")
    return "".join(out)


def _attached_html(attached: Mapping[str, Any] | None, tz: ZoneInfo) -> str:
    if not attached:
        return ""
    items: list[tuple[str, str, Sequence[str]]] = []  # kind, text, the lines it points at
    for e in attached["events"]:
        span = day_reader.span_text(e["start"], e["end"], tz)
        items.append(("event", f"{e['title']} {span}{day_reader.sources_text(e)}", e["lines"]))
    for t in attached["transcripts"]:
        items.append(("transcript", t["title"], [t["line"]]))
    for n in attached["notes"]:
        items.append(("note", n["text"], [n["line"]]))
    for m in attached["mail"]:
        items.append(("mail", f"{m['subject']} ({_plural(m['messages'], 'message')})", m["lines"]))
    for c in attached["calls"]:
        items.append(("call", day_reader.call_text(c), [c["line"]]))
    for k in attached["keepers"]:
        items.append(("keeper", f"{k['name']} ({k['lane']})", [k["line"]]))
    for key, noun in (("messages", "message"), ("photos", "photo")):
        if attached[key]["count"]:
            items.append((key, _plural(attached[key]["count"], noun), attached[key]["lines"]))
    if not items:
        return ""
    out = ['<ul class="attached">\n']
    for kind, text, lines in items:
        title = " ".join(lines[:3]) + (" …" if len(lines) > 3 else "")
        out.append(
            f'<li title="{escape(_plural(len(lines), "line"))}: {escape(title)}">'
            f'<span class="kind">{escape(kind)}</span> {escape(text)}</li>\n'
        )
    out.append("</ul>\n")
    return "".join(out)


def _trip_row(trip: trips.Trip, rd: reading.Reading) -> list[Cell]:
    nights = _plural(trip.nights, "night")
    if trip.asset:
        asset = rd.assets.get(trip.asset)
        nights += f" aboard {asset.name if asset else trip.asset}"
    if trip.in_transit:
        nights += f" ({trip.in_transit} in transit)"
    flights = []
    for label, found in (("in", trip.flights_in), ("out", trip.flights_out)):
        for f in found:
            name = f"{f['carrier']} {f['number']} " if f["number"] else ""
            flights.append(f"{label} {name}{f['from']} {ARROW} {f['to']}")
    return [
        (
            f'<a href="/days?from={trip.start}&amp;to={trip.until}">{trip.start} {EN_DASH} {trip.end}</a>',
            "day",
        ),
        escape(nights),
        escape(f" {ARROW} ".join(trip.route)) if trip.route else '<span class="mute">unknown</span>',
        escape(", ".join(flights)),
        escape(", ".join(trip.places)),
        escape(", ".join(c.name for c in trip.people)),
    ]


# -- fragments --------------------------------------------------------------------------------------------


def _table(head: Sequence[Cell], rows: Iterable[Sequence[Cell]]) -> str:
    """A table from cells already escaped (or marked up): a cell is text, or (text, css class)."""
    out = ["<table>\n<thead><tr>"]
    for cell in head:
        text, cls = cell if isinstance(cell, tuple) else (cell, "")
        out.append(f'<th class="{cls}">{text}</th>' if cls else f"<th>{text}</th>")
    out.append("</tr></thead>\n<tbody>\n")
    for row in rows:
        out.append("<tr>")
        for cell in row:
            text, cls = cell if isinstance(cell, tuple) else (cell, "")
            out.append(f'<td class="{cls}">{text}</td>' if cls else f"<td>{text}</td>")
        out.append("</tr>\n")
    out.append("</tbody>\n</table>\n")
    return "".join(out)


def _dt(term: str, text: str) -> str:
    return f"<dt>{escape(term)}</dt><dd>{escape(text)}</dd>\n"


def _num(n: int) -> Cell:
    return (f"{n:,}", "num")


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def _metres(m: float) -> str:
    return f"{m:.0f} m" if m < 1000 else f"{m / 1000:.1f} km"


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def _clock(stamp: str, tz: ZoneInfo) -> str:
    return _instant(stamp).astimezone(tz).strftime("%Y-%m-%d %H:%M")


def _local_day(stamp: str, tz: ZoneInfo) -> str:
    return _instant(stamp).astimezone(tz).date().isoformat()


def _clip(day: str, days: int, whole: tuple[str, str]) -> str:
    """`day` moved by `days`, kept inside the record's days."""
    moved = (parse_day(day) + timedelta(days=days)).isoformat()
    return min(max(moved, whole[0]), whole[1])


def _last_window(whole: tuple[str, str]) -> tuple[str, str]:
    return _clip(whole[1], -(WINDOW_DAYS - 1), whole), whole[1]


# -- the server -------------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "logbook"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._answer(body=True)

    def do_HEAD(self) -> None:
        self._answer(body=False)

    def _answer(self, body: bool) -> None:
        assert isinstance(self.server, Server)
        path, _, query = self.path.partition("?")
        response = self.server.site.respond(path, query)
        self.send_response(response.status)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if body and response.status != 204:
            self.wfile.write(response.body)


class Server(ThreadingHTTPServer):
    """A loopback-only HTTP server over one `Site`. Never resolves a name: `HTTPServer.server_bind`
    would look up the host's fully qualified name, and this one does not."""

    daemon_threads = True

    def __init__(self, port: int, site: Site):
        self.site = site
        super().__init__((HOST, port), Handler)

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def make_server(lb: Logbook, host: str = HOST, port: int = PORT, airports: Airports | None = None) -> Server:
    """The server, bound and ready to `serve_forever`. `HostError` for any host but 127.0.0.1,
    before a socket is opened; OSError when the port is taken."""
    if host != HOST:
        raise HostError(
            f"serve binds {HOST} only, never {host!r}: the record is read from this machine, "
            "and nothing here leaves it"
        )
    return Server(port, Site(lb, airports))


def serve(
    lb: Logbook,
    host: str = HOST,
    port: int = PORT,
    airports: Airports | None = None,
    announce: Callable[[str], None] = print,
) -> None:
    """Serve the record until Ctrl-C. `HostError` and OSError as `make_server`."""
    server = make_server(lb, host, port, airports)
    try:
        bound = server.server_address[1]
        announce(f"serving {_shown(lb.root)} at http://{HOST}:{bound}/  (Ctrl-C to stop; nothing is written)")
        server.serve_forever()
    except KeyboardInterrupt:
        announce("stopped")
    finally:
        server.server_close()


def _shown(root: Path) -> str:
    """The record's folder as `~/Logbook` when it is under the home directory, never the user name."""
    try:
        return "~/" + root.resolve().relative_to(Path.home().resolve()).as_posix()
    except (ValueError, OSError):
        return str(root)
