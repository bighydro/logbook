"""The weather of the owner's days: where to ask for it, and the `weather/v1` lines (RFC 0026) read back.

Two halves, both pure. `clusters(lb, first, last)` is what `logbook sync weather` asks the network
about: for every local day of the window, the owner's overnight stay (`stays.night`, the Day's
"night after") and every stay of `STAY_MIN_S` (three hours) or longer that touches the day, each
coordinate rounded to `DECIMALS` (one, about 10 km), deduped on `(day, lat, lon)`. The stays come
from the index alone (`reading.owner_track`, in chunks), so a long record is clustered without a
line read from the files. A stay aboard an asset counts by its anchorages (`Segment.inside`) as well
as by its centre. The rounding is the privacy boundary: nothing finer than a tenth of a degree is
ever put in a request, and the adapter (`adapters.weather`) builds its URLs from these clusters only.

The reader half takes the record's `weather` lines standing (a retracted line is out) and gives the
readers their rows: `by_day` per local day (the payload's `day`), `day_row` for the Day — one row,
the cluster of the night when the night has one, else the first, with every cluster of the day under
`places` — and `span` for a window (`year`, `trips`): the coldest and warmest day, the precipitation
summed over the days (the wettest cluster of a day, so two clusters never count one rain twice), the
wet days (1 mm or more), the strongest wind, and how many of the window's days have a line. `text`
and `span_text` are the one-line forms. Nothing here opens the network or writes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, time, timedelta
from typing import Any, NamedTuple, TypeGuard
from zoneinfo import ZoneInfo

from . import reading, stays
from .chain import Line
from .store import RETRACTION, Logbook, retractions

KIND = "weather"
SCHEMA = "weather/v1"
SOURCE = "weather"
STAY_MIN_S = 3 * 3600  # a stay this long on a day asks for that place's weather
DECIMALS = 1  # a tenth of a degree, about 10 km: the coarsest grid that still names the valley
WET_MM = 1.0  # a day with this much precipitation or more is a wet day
CHUNK_DAYS = 62  # days of the owner's track clustered per reading
FIELDS = ("t_min_c", "t_max_c", "precipitation_mm", "wind_max_kmh", "weather_code", "sunrise", "sunset")
EN_DASH = "\u2013"
DOT = " · "

# WMO code table 4677 as Open-Meteo reports it, in a word or two each.
CODES: dict[int, str] = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "heavy freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with heavy hail",
}


class Cluster(NamedTuple):
    """One place on one day, to a tenth of a degree: what one weather line is about."""

    day: str
    lat: float
    lon: float


# -- where the owner was ----------------------------------------------------------------------------------


def round_coordinate(value: float) -> float:
    """A coordinate to `DECIMALS` places, never `-0.0`: the only form of a coordinate that leaves
    the machine."""
    rounded = round(float(value), DECIMALS)
    return 0.0 if rounded == 0 else rounded


def clusters(lb: Logbook, first: str, last: str) -> list[Cluster]:
    """The clusters of `[first, last]` (local days, inclusive), in day order then by coordinates,
    each once. Raises `stays.SettingsError` as `reading.owner_track` does; writes nothing."""
    found: set[Cluster] = set()
    tz = ZoneInfo(str(lb.meta["timezone"]))
    for chunk_first, chunk_last in _chunks(first, last, CHUNK_DAYS):
        track = reading.owner_track(lb, chunk_first, chunk_last)
        folded = stays.fold(track.stays)
        for day in track.days:
            found.update(of_day(day, folded, tz, track.settings, track.places))
    return sorted(found)


def of_day(
    day: str,
    folded: Sequence[stays.Segment],
    tz: ZoneInfo,
    settings: stays.Settings,
    places: Sequence[Any] = (),
) -> set[Cluster]:
    """The clusters of one day from the owner's folded stays: the night's position and every stay
    (a stay aboard, and the anchorages inside it) of `STAY_MIN_S` or longer that overlaps the day."""
    out: set[Cluster] = set()
    night = stays.night(folded, day, tz, settings, places)
    if night.position is not None:
        out.add(Cluster(day, round_coordinate(night.position[0]), round_coordinate(night.position[1])))
    start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=tz)
    end = start + timedelta(days=1)
    for s in folded:
        for candidate in (s, *s.inside):
            if candidate.kind != stays.STAY or candidate.lat is None or candidate.lon is None:
                continue
            if candidate.duration_s < STAY_MIN_S or candidate.start >= end or candidate.end <= start:
                continue
            out.add(Cluster(day, round_coordinate(candidate.lat), round_coordinate(candidate.lon)))
    return out


def _chunks(first: str, last: str, size: int) -> list[tuple[str, str]]:
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    out = []
    while a <= b:
        stop = min(b, a + timedelta(days=size - 1))
        out.append((a.isoformat(), stop.isoformat()))
        a = stop + timedelta(days=1)
    return out


# -- the lines read back ------------------------------------------------------------------------------------


def standing(lines: Iterable[Line]) -> list[Line]:
    """The weather lines not retracted, in chain order."""
    kept = sorted(lines, key=lambda line: int(line.get("seq", 0)))
    retracted = retractions(line for line in kept if line.get("kind") == RETRACTION)
    return [line for line in kept if line.get("kind") == KIND and str(line.get("id")) not in retracted]


def by_day(lines: Iterable[Line]) -> dict[str, list[dict[str, Any]]]:
    """The standing lines as rows per local day (the payload's `day`), each row the payload's
    fields with the line's id under `line`; a line without a day or coordinates is left out."""
    out: dict[str, list[dict[str, Any]]] = {}
    for line in standing(lines):
        payload = line.get("payload") or {}
        day, lat, lon = payload.get("day"), payload.get("lat"), payload.get("lon")
        if not isinstance(day, str) or not _number(lat) or not _number(lon):
            continue
        row: dict[str, Any] = {"day": day, "lat": float(lat), "lon": float(lon), "line": str(line.get("id"))}
        for key in FIELDS:
            value = payload.get(key)
            row[key] = value if _number(value) or isinstance(value, str) else None
        row["description"] = describe(row["weather_code"])
        out.setdefault(day, []).append(row)
    return out


def day_row(rows: Sequence[Mapping[str, Any]], night: tuple[float, float] | None) -> dict[str, Any] | None:
    """The Day's one row: the cluster the night was spent in when the day has one, else the first,
    with every cluster of the day under `places` (the chosen one first); None for a day with none."""
    if not rows:
        return None
    chosen = rows[0]
    if night is not None:
        wanted = (round_coordinate(night[0]), round_coordinate(night[1]))
        chosen = next((r for r in rows if (r["lat"], r["lon"]) == wanted), rows[0])
    others = [r for r in rows if r is not chosen]
    return {**chosen, "places": [dict(chosen), *(dict(r) for r in others)]}


def span(days: Mapping[str, Sequence[Mapping[str, Any]]], window: Sequence[str]) -> dict[str, Any] | None:
    """The summary of the window's days: see the module docstring. None when no day of the window
    has a row."""
    t_min = t_max = wind = None
    precipitation = 0.0
    wet = 0
    with_lines = 0
    lines: list[str] = []
    for day in window:
        rows = days.get(day, [])
        if not rows:
            continue
        lines += [str(r["line"]) for r in rows]
        with_lines += 1
        for r in rows:
            t_min = _extreme(t_min, r["t_min_c"], day, min)
            t_max = _extreme(t_max, r["t_max_c"], day, max)
            wind = _extreme(wind, r["wind_max_kmh"], day, max)
        wettest = max(
            (float(r["precipitation_mm"]) for r in rows if _number(r["precipitation_mm"])), default=None
        )
        if wettest is not None:
            precipitation += wettest
            wet += wettest >= WET_MM
    if not lines:
        return None
    return {
        "days": with_lines,
        "of": len(window),
        "t_min": t_min,
        "t_max": t_max,
        "precipitation_mm": round(precipitation, 1),
        "wet_days": wet,
        "wind_max": wind,
        "lines": lines,
    }


def _extreme(current: dict[str, Any] | None, value: object, day: str, pick: Any) -> dict[str, Any] | None:
    if not _number(value):
        return current
    number = float(value)
    if current is None or pick(current["value"], number) != current["value"]:
        return {"value": number, "day": day}
    return current


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def describe(code: object) -> str | None:
    """The WMO code in a word or two; None for a code the table does not know."""
    return CODES.get(int(code)) if _number(code) else None


# -- text ----------------------------------------------------------------------------------------------------


def text(row: Mapping[str, Any], tz: str) -> str:
    """`3°-12° · 4.2 mm · wind 31 km/h · overcast · sun 07:12-17:03`, then `· 2 places` when the day
    has more than one cluster; a field with no value is left out."""
    parts = []
    lo, hi = row.get("t_min_c"), row.get("t_max_c")
    if _number(lo) and _number(hi):
        parts.append(f"{_degrees(lo)}{EN_DASH}{_degrees(hi)}")
    elif _number(lo):
        parts.append(f"min {_degrees(lo)}")
    elif _number(hi):
        parts.append(f"max {_degrees(hi)}")
    if _number(row.get("precipitation_mm")):
        parts.append(f"{mm(row['precipitation_mm'])} mm")
    if _number(row.get("wind_max_kmh")):
        parts.append(f"wind {round(float(row['wind_max_kmh']))} km/h")
    if row.get("description"):
        parts.append(str(row["description"]))
    sunrise, sunset = row.get("sunrise"), row.get("sunset")
    if isinstance(sunrise, str) and isinstance(sunset, str):
        parts.append(f"sun {_clock(sunrise, tz)}{EN_DASH}{_clock(sunset, tz)}")
    places = row.get("places") or []
    if len(places) > 1:
        parts.append(f"{len(places)} places")
    return DOT.join(parts) if parts else "no values"


def span_text(summary: Mapping[str, Any]) -> str:
    """`-5°-10° · 13 mm, 2 wet days · wind up to 80 km/h · 3 of 4 days`."""
    parts = []
    lo, hi = summary.get("t_min"), summary.get("t_max")
    if lo and hi:
        parts.append(f"{_degrees(lo['value'])}{EN_DASH}{_degrees(hi['value'])}")
    wet = int(summary.get("wet_days") or 0)
    parts.append(f"{mm(summary['precipitation_mm'])} mm, {wet} wet {'day' if wet == 1 else 'days'}")
    if summary.get("wind_max"):
        parts.append(f"wind up to {round(float(summary['wind_max']['value']))} km/h")
    parts.append(f"{summary['days']} of {summary['of']} {'day' if summary['of'] == 1 else 'days'}")
    return DOT.join(parts)


def mm(value: object) -> str:
    """Millimetres to one decimal, `13` rather than `13.0`."""
    text_ = f"{float(value):.1f}"  # type: ignore[arg-type]
    return text_[:-2] if text_.endswith(".0") else text_


def _degrees(value: object) -> str:
    return f"{round(float(value)):d}°"  # type: ignore[arg-type]


def _clock(stamp: str, tz: str) -> str:
    try:
        instant = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return stamp
    return instant.astimezone(ZoneInfo(tz)).strftime("%H:%M")
