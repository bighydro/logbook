"""Open-Meteo → weather/v1 (RFC 0026), live: the daily weather of the places the owner's days were spent at.

`logbook sync weather [--since DAY] [--until DAY] [--dry-run]` and nothing else calls this: no
reader does, and `sync --all` leaves it out unless the owner sets `LOGBOOK_WEATHER=1` (the
`sync.env` the schedule reads). The command derives the clusters — one local day and one place to a
tenth of a degree (`logbook.weather.clusters`) — and `pull` fetches the daily values for each from
Open-Meteo's free historical archive (`archive-api.open-meteo.com`, no key), or from the forecast
API for the last `RECENT_DAYS` (the archive runs a few days behind). One request covers one cluster
and a run of days: the days a cluster needs are sorted and split where a gap exceeds `GAP_DAYS` or
a run would exceed `MAX_RANGE_DAYS`, so a fortnight at one place is one request, not fourteen.
Between requests `pull` waits `PAUSE_S` (polite to a free service that asks for under 600 calls a
minute). Stdlib urllib, no dependency.

Privacy: the only coordinates in a URL are the clusters' rounded ones (`url` formats them with one
decimal), and the only thing the service learns is that someone asked about a 10 km square on some
days. No identifier, no key, no referrer; the User-Agent names this project. The cache
(`<root>/inbox/weather/<lat>_<lon>/<day>.json`) keeps every day a response carried, under the
rounded coordinates, so a re-run never refetches; a day the provider had no values for is not cached
and is counted (`skipped_no_data`), so it is asked again another time. A request that fails is one
line in `failed` (`sync` prints it, exits 1 and keeps the watermark where it was); the other
requests still go out. Network happens only inside `pull` (ADR 0012)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as clock
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import urlencode
from urllib.request import Request as HttpRequest
from urllib.request import urlopen
from zoneinfo import ZoneInfo

from .. import __version__
from ..core.weather import KIND, SCHEMA, SOURCE, Cluster

__all__ = [
    "ARCHIVE",
    "DAILY",
    "ENV",
    "FORECAST",
    "KIND",
    "NAME",
    "Config",
    "Request",
    "cached",
    "configure",
    "draft",
    "outstanding",
    "plan",
    "pull",
    "url",
    "watermark",
]

NAME = SOURCE
ENV = (
    "LOGBOOK_WEATHER",
)  # `1`, `on`, `yes` or `true` lists the source in `sync --all`; nothing else reads it
UNIT = "requests"  # what `sync` counts in its progress lines
ON = frozenset({"1", "on", "yes", "true"})
OFF = frozenset({"0", "off", "no", "false"})
ARCHIVE, FORECAST = "archive", "forecast"
URLS = {
    ARCHIVE: "https://archive-api.open-meteo.com/v1/archive",
    FORECAST: "https://api.open-meteo.com/v1/forecast",
}
DAILY = (
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "wind_speed_10m_max",
    "weather_code",
    "sunrise",
    "sunset",
)
FIELD_OF = {  # the payload's field for each daily variable
    "temperature_2m_min": "t_min_c",
    "temperature_2m_max": "t_max_c",
    "precipitation_sum": "precipitation_mm",
    "wind_speed_10m_max": "wind_max_kmh",
    "weather_code": "weather_code",
    "sunrise": "sunrise",
    "sunset": "sunset",
}
VALUED = (
    "t_min_c",
    "t_max_c",
    "precipitation_mm",
    "wind_max_kmh",
    "weather_code",
)  # a day with none is empty
RECENT_DAYS = 7  # days this recent come from the forecast API; the archive runs behind
GAP_DAYS = 7  # needed days this far apart still share one request
MAX_RANGE_DAYS = 366  # a request never spans more
PAUSE_S = 1.0  # between requests
TIMEOUT_S = 60
CACHE_DIR = PurePosixPath("inbox/weather")  # record-relative
PROVIDER = "open-meteo"
EVIDENCE = "external"
NO_DATA = "skipped_no_data"
USER_AGENT = f"openlogbook/{__version__} (+https://github.com/bighydro/logbook)"
sleep = time.sleep  # a test replaces it


@dataclass(frozen=True)
class Config:
    pause_s: float = PAUSE_S


def configure(env: Mapping[str, str]) -> Config | None:
    """Config when LOGBOOK_WEATHER is on; None when it is absent, empty or off. `sync weather` by name
    never asks: the variable only lists the source in `sync --all`. Raises ValueError for a value
    that is neither on nor off."""
    raw = env.get(ENV[0], "").strip().lower()
    if not raw or raw in OFF:
        return None
    if raw not in ON:
        raise ValueError(f"{ENV[0]} must be 1 or 0 (on or off), not {raw!r}")
    return Config()


class Request(NamedTuple):
    """One GET: one cluster's coordinates, a run of days, the API that serves them."""

    lat: float
    lon: float
    start: str
    end: str
    api: str

    @property
    def days(self) -> list[str]:
        a, b = date.fromisoformat(self.start), date.fromisoformat(self.end)
        return [date.fromordinal(o).isoformat() for o in range(a.toordinal(), b.toordinal() + 1)]


def watermark(draft: dict[str, Any]) -> str | None:
    """The line's local day: `sync weather` keeps the last day it covered."""
    day = (draft.get("payload") or {}).get("day")
    return str(day) if day is not None else None


# -- the plan ----------------------------------------------------------------------------------------------


def plan(needed: Iterable[Cluster], today: date) -> list[Request]:
    """The requests that cover `needed`: per cluster and API, the days sorted and split where a gap
    exceeds `GAP_DAYS` or a run `MAX_RANGE_DAYS`; in order of coordinates, then start."""
    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()
    by_place: dict[tuple[float, float, str], list[date]] = {}
    for c in set(needed):
        api = FORECAST if c.day >= recent else ARCHIVE
        by_place.setdefault((c.lat, c.lon, api), []).append(date.fromisoformat(c.day))
    out: list[Request] = []
    for (lat, lon, api), days in by_place.items():
        run: list[date] = []
        for day in sorted(days):
            if run and ((day - run[-1]).days > GAP_DAYS or (day - run[0]).days >= MAX_RANGE_DAYS):
                out.append(Request(lat, lon, run[0].isoformat(), run[-1].isoformat(), api))
                run = []
            run.append(day)
        if run:
            out.append(Request(lat, lon, run[0].isoformat(), run[-1].isoformat(), api))
    return sorted(out, key=lambda r: (r.lat, r.lon, r.start))


def url(request: Request, tz: str) -> str:
    """The request's URL: the coordinates with one decimal, never more, the days as dates, the
    daily variables and the record's zone (the days are the owner's local days)."""
    query = {
        "latitude": _one_decimal(request.lat),
        "longitude": _one_decimal(request.lon),
        "start_date": request.start,
        "end_date": request.end,
        "daily": ",".join(DAILY),
        "timezone": tz,
    }
    return f"{URLS[request.api]}?{urlencode(query, safe=',')}"


def _one_decimal(value: float) -> str:
    text = f"{round(value, 1):.1f}"
    return "0.0" if text == "-0.0" else text


# -- the cache ---------------------------------------------------------------------------------------------


def cache_path(cache: Path, cluster: Cluster) -> Path:
    return cache / f"{_one_decimal(cluster.lat)}_{_one_decimal(cluster.lon)}" / f"{cluster.day}.json"


def cached(cache: Path, cluster: Cluster) -> dict[str, Any] | None:
    """The cached values of a cluster-day, `{"values": {...}, "dataset": ...}`, or None; a file that
    is not what this version wrote reads as absent."""
    path = cache_path(cache, cluster)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("values"), dict):
        return None
    return data


def outstanding(clusters: Iterable[Cluster], cache: Path) -> list[Cluster]:
    """The clusters the cache has nothing for, in order."""
    return [c for c in clusters if cached(cache, c) is None]


def _write_cache(cache: Path, cluster: Cluster, values: Mapping[str, Any], dataset: str) -> None:
    path = cache_path(cache, cluster)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "day": cluster.day,
        "lat": cluster.lat,
        "lon": cluster.lon,
        "dataset": dataset,
        "provider": PROVIDER,
        "fetched_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "values": dict(values),
    }
    path.write_bytes((json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8"))


# -- the pull ----------------------------------------------------------------------------------------------


def pull(
    config: Config,
    since: str | None = None,
    progress: Callable[[int, float], None] | None = None,
    counts: dict[str, int] | None = None,
    clusters: Sequence[Cluster] = (),
    cache: Path | None = None,
    timezone: str = "UTC",
    failed: list[str] | None = None,
    today: date | None = None,
) -> Iterator[dict[str, Any]]:
    """One weather/v1 draft per cluster, in cluster order (day, then coordinates): from the cache
    when it has the day, else fetched — the requests of `plan` one after the other with `PAUSE_S`
    between, every day of each response cached. `since` is the protocol's; the clusters are the
    window. A request that fails is one line in `failed` and its clusters have no draft this run.
    A day the provider has no values for is counted under `skipped_no_data` and not cached.
    `progress(requests_so_far, elapsed_seconds)` after every request."""
    counts = counts if counts is not None else {}
    counts.setdefault(NO_DATA, 0)
    cache = cache if cache is not None else Path(*CACHE_DIR.parts)
    today = today if today is not None else datetime.now(ZoneInfo(timezone)).date()
    have: dict[Cluster, tuple[dict[str, Any], str]] = {}
    needed: list[Cluster] = []
    for c in clusters:
        hit = cached(cache, c)
        if hit is None:
            needed.append(c)
        else:
            have[c] = (dict(hit["values"]), str(hit.get("dataset") or ARCHIVE))
    started = time.monotonic()
    unreached: set[Cluster] = set()  # the clusters of a request that failed: not data the provider lacks
    for i, request in enumerate(plan(needed, today)):
        if i:
            sleep(config.pause_s)
        try:
            days = fetch(request, timezone)
        except (OSError, ValueError) as e:
            place = f"{_one_decimal(request.lat)},{_one_decimal(request.lon)}"
            where = f"{place} {request.start} \u2013 {request.end}"
            if failed is not None:
                failed.append(f"{where}: {e}")
            unreached.update(Cluster(day, request.lat, request.lon) for day in request.days)
            days = {}
        if progress is not None:
            progress(i + 1, time.monotonic() - started)
        for day, values in days.items():
            c = Cluster(day, request.lat, request.lon)
            if not any(values.get(k) is not None for k in VALUED):
                continue
            _write_cache(cache, c, values, request.api)
            have[c] = (values, request.api)
    for c in clusters:
        if c in have:
            values, dataset = have[c]
            yield draft(c, values, timezone, dataset)
        elif c not in unreached:
            counts[NO_DATA] += 1


def fetch(request: Request, tz: str) -> dict[str, dict[str, Any]]:
    """One GET; the response's days as `{day: payload fields}`. The only network call in this module.
    Raises OSError (urllib's) or ValueError (a body that is not a daily answer)."""
    req = HttpRequest(url(request, tz), headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT_S) as response:
        body = response.read()
    return parse(body, tz)


def parse(body: bytes, tz: str) -> dict[str, dict[str, Any]]:
    """The days of one response, each day's values in the payload's fields and units: Celsius,
    millimetres, km/h, the WMO code as an integer, sunrise and sunset as RFC3339 UTC."""
    try:
        doc = json.loads(body.decode("utf-8"), parse_constant=lambda _name: None)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(
            f"expected a JSON object with daily values, got something that is not JSON ({e})"
        ) from None
    if not isinstance(doc, dict):
        raise ValueError(f"expected a JSON object with daily values, got a JSON {type(doc).__name__}")
    if doc.get("error"):
        raise ValueError(str(doc.get("reason") or "the provider reported an error"))
    daily = doc.get("daily")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise ValueError("expected a JSON object with daily values under `daily`")
    out: dict[str, dict[str, Any]] = {}
    for i, day in enumerate(daily["time"]):
        if not isinstance(day, str):
            continue
        values: dict[str, Any] = {}
        for variable, field in FIELD_OF.items():
            column = daily.get(variable)
            raw = column[i] if isinstance(column, list) and i < len(column) else None
            values[field] = _value(field, raw, tz)
        out[day[:10]] = values
    return out


def _value(field: str, raw: object, tz: str) -> Any:
    if raw is None or isinstance(raw, bool):
        return None
    if field in ("sunrise", "sunset"):
        return _instant(raw, tz)
    if not isinstance(raw, int | float):
        return None
    if field == "weather_code":
        return int(raw)
    return float(raw)


def _instant(raw: object, tz: str) -> str | None:
    """A local wall-clock stamp as the provider gives it (`2026-06-16T04:00`, in the zone asked
    for) as RFC3339 UTC; None when it is not one."""
    if not isinstance(raw, str):
        return None
    try:
        local = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo(tz))
    return local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def draft(cluster: Cluster, values: Mapping[str, Any], tz: str, dataset: str) -> dict[str, Any]:
    """The line draft for one cluster-day: `at` the local day's start, `end` the next day's, the
    payload the values with the rounded coordinates, `raw_id` `<day>@<lat>,<lon>`."""
    start = datetime.combine(date.fromisoformat(cluster.day), clock.min, tzinfo=ZoneInfo(tz))
    lat, lon = _one_decimal(cluster.lat), _one_decimal(cluster.lon)
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"{cluster.day}@{lat},{lon}",
        "day": cluster.day,
        "lat": float(lat),
        "lon": float(lon),
    }
    for field in FIELD_OF.values():
        payload[field] = values.get(field)
    payload["evidence"] = EVIDENCE
    payload["provider"] = PROVIDER
    payload["dataset"] = dataset
    return {
        "at": _stamp(start),
        "end": _stamp(start + timedelta(days=1)),
        "tz": tz,
        "source": SOURCE,
        "kind": KIND,
        "tier": 1,
        "payload": payload,
    }


def _stamp(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
