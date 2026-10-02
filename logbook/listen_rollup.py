"""`logbook rollup listen`: listening summed up per year from the `listen/v1` lines standing (RFC
0019) — listens, hours, skips, the top artists by hours, hours by month — in `rollup.py`'s manner
but beside it, so the listening rollup grows without touching the others. A reader (ADR 0013):
derived from the record at its head, never written; every number carries the ids of its lines
under `--json`; the same record gives the same rollup."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .chain import Line
from .export import day_range
from .store import RETRACTION, retractions

KIND = "listen"
TOP_ARTISTS = 10
EN_DASH = "\u2013"
EM_DASH = "\u2014"


def empty() -> dict[str, Any]:
    """The rollup of a record with no listen."""
    return {"kind": KIND, "window": {"since": None, "until": None, "days": []}, "years": []}


def standing(lines: Iterable[Line]) -> list[Line]:
    """The listen lines not retracted and not superseded by another listen line, in chain order.
    Of several lines that supersede the same line, the latest stands."""
    kept = list(lines)
    retracted = retractions(line for line in kept if line.get("kind") == RETRACTION)
    live = [line for line in kept if line.get("kind") == KIND and str(line.get("id")) not in retracted]
    latest: dict[str, str] = {}  # superseded id → the id of the last line that supersedes it
    for line in live:
        over = (line.get("payload") or {}).get("supersedes")
        if isinstance(over, str):
            latest[over] = str(line.get("id"))
    out: list[Line] = []
    for line in live:
        over = (line.get("payload") or {}).get("supersedes")
        if str(line.get("id")) in latest:
            continue  # corrected by a later line
        if isinstance(over, str) and latest.get(over) != str(line.get("id")):
            continue  # an earlier correction of a line corrected again
        out.append(line)
    return out


def listen(lines: Iterable[Line], tz: str, first: str, last: str) -> dict[str, Any]:
    """Per calendar year of the window `[first, last]` (local days in `tz`): `listens`, the hours
    played (`played_s` summed; a line with no playhead is a listen with no hours, counted under
    `untimed`), `skipped` (lines whose `extra.skipped` is true), `by_service`, `episodes` (the
    podcast lines, their hours and ids), `top_artists` (the tracks' performers, as spelled, by hours
    then listens, the first `TOP_ARTISTS`) and `months`: every month the window touches, with its
    listens, hours, skips and line ids — a month with no listen has zero listens and is printed as
    a dash, never a zero. `lines` are the listen lines of the window with the retraction lines
    beside them; a correction that `supersedes` a line wins, a retracted line is out."""
    zone = ZoneInfo(tz)
    days = day_range(first, last)
    years: dict[str, dict[str, Any]] = {}
    for day in days:
        year = years.setdefault(day[:4], _year(day[:4]))
        month = year["months"].setdefault(day[:7], _month(day[:7], day))
        month["last"] = day
    for line in standing(lines):
        day = _local_day(str(line.get("at", "")), zone) or ""
        if not first <= day <= last or day[:4] not in years:
            continue
        payload = line.get("payload") or {}
        seconds = _number(payload.get("played_s"))
        skipped = bool((payload.get("extra") or {}).get("skipped") is True)
        id_ = str(line.get("id"))
        year = years[day[:4]]
        month = year["months"][day[:7]]
        for bucket in (year, month):
            bucket["listens"] += 1
            bucket["played_s"] += seconds or 0.0
            bucket["skipped"] += skipped
            bucket["lines"].append(id_)
        if seconds is None:
            year["untimed"] += 1
        year["by_service"][str(payload.get("service") or line.get("source"))] += 1
        if payload.get("media") == "episode":
            _tally(year["episodes"], seconds, id_)
        elif artist := " ".join(str(payload.get("artist") or "").split()):
            _tally(
                year["artists"].setdefault(
                    artist, {"artist": artist, "listens": 0, "played_s": 0.0, "lines": []}
                ),
                seconds,
                id_,
            )
    out: dict[str, Any] = {"kind": KIND, "window": {"since": first, "until": last, "days": days}, "years": []}
    for key in sorted(years):
        out["years"].append(_finish_year(years[key]))
    return out


def _year(year: str) -> dict[str, Any]:
    return {
        "year": year,
        "listens": 0,
        "played_s": 0.0,
        "skipped": 0,
        "untimed": 0,
        "lines": [],
        "by_service": Counter(),
        "episodes": {"listens": 0, "played_s": 0.0, "lines": []},
        "artists": {},
        "months": {},
    }


def _month(month: str, day: str) -> dict[str, Any]:
    return {
        "month": month,
        "first": day,
        "last": day,
        "listens": 0,
        "played_s": 0.0,
        "skipped": 0,
        "lines": [],
    }


def _tally(bucket: dict[str, Any], seconds: float | None, id_: str) -> None:
    bucket["listens"] += 1
    bucket["played_s"] += seconds or 0.0
    bucket["lines"].append(id_)


def _finish_year(year: dict[str, Any]) -> dict[str, Any]:
    artists = sorted(year.pop("artists").values(), key=lambda a: (-a["played_s"], -a["listens"], a["artist"]))
    months = [_finish(m) for m in year.pop("months").values()]
    by_service = dict(sorted(year.pop("by_service").items(), key=lambda kv: (-kv[1], kv[0])))
    year["episodes"] = _finish(year["episodes"])
    out = _finish(year)
    out["by_service"] = by_service
    out["top_artists"] = [_finish(a) for a in artists[:TOP_ARTISTS]]
    out["months"] = months
    return out


def _finish(bucket: dict[str, Any]) -> dict[str, Any]:
    """`played_s` as a number (whole when it is), `hours` to one decimal, the keys in a fixed order."""
    seconds = round(float(bucket["played_s"]), 3)
    out = {k: v for k, v in bucket.items() if k != "lines"}
    out["played_s"] = int(seconds) if seconds.is_integer() else seconds
    out["hours"] = round(seconds / 3600, 1)
    out["lines"] = bucket["lines"]
    return out


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _local_day(at: str, zone: ZoneInfo) -> str | None:
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        return None
    return when.astimezone(zone).date().isoformat()


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The rollup as text: one line per year, then its top artists and its months."""
    window = data["window"]
    head = data["kind"]
    if window["since"]:
        head = f"{head} {window['since']} {EN_DASH} {window['until']}"
    yield head
    if not data["years"]:
        yield "  nothing in the window"
        return
    for year in data["years"]:
        parts = [_plural(year["listens"], "listen"), f"{year['hours']:.1f} h"]
        if year["skipped"]:
            parts.append(f"{year['skipped']} skipped")
        if year["untimed"]:
            parts.append(f"{year['untimed']} without a playhead")
        if year["episodes"]["listens"]:
            parts.append(_plural(year["episodes"]["listens"], "episode"))
        if year["by_service"]:
            parts.append(", ".join(f"{k} {v}" for k, v in year["by_service"].items()))
        yield f"  {year['year']}  {' · '.join(parts)}"
        if year["top_artists"]:
            yield "        top artists"
            width = max(28, *(len(a["artist"]) for a in year["top_artists"]))
            for a in year["top_artists"]:
                hours = f"{a['hours']:.1f} h"
                yield f"          {a['artist']:<{width}} {hours} · {_plural(a['listens'], 'listen')}"
        yield "        by month"
        for m in year["months"]:
            if not m["listens"]:
                yield f"          {m['month']}  {EM_DASH}"
                continue
            parts = [f"{m['hours']:.1f} h", _plural(m["listens"], "listen")]
            if m["skipped"]:
                parts.append(f"{m['skipped']} skipped")
            yield f"          {m['month']}  {' · '.join(parts)}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
