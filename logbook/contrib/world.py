"""`logbook export world [--out DIR] [--from DATE --to DATE] [--tier 1|1,2|1,2,3]`: the record as a globe
you can scrub, one self-contained HTML page; the Library serves the same page at `/world`.

The page draws on a canvas (no WebGL, no library): the world's outline from the land table bundled
with the package (`logbook/tables/land.json`, Natural Earth's 1:110m land polygons, public domain,
written by `scripts/make_land.py` under `LAND_BYTES`), the named places of `places.json` as anchors,
the assets of `assets.json` as dots moving along their own tracks (their `location/v1` lines, ADR
0018), the owner's stays as dots, the journeys (`journey/v1` and `trip/v1`, RFC 0020) as tracks, and
under it a time scrubber that moves everything: an asset's dot is where its track puts it at that
minute, the owner's is the stay they were in (aboard, it rides with the boat), a journey under way is
drawn as far as it has come. A standing `chapter/v1` line (RFC 0036) is a band on the scrubber.
Clicking an anchor or an asset shows its page summary — nights, journeys, photos, the first and last
day — counted from the whole reading, as `logbook show place|asset` counts them: a night at a place
is a night whose stay lay there, a night aboard is the asset's; a journey counts for the places at its
ends and for its asset; a photo for the place of the owner's stay it was taken in and for the asset
the owner was aboard, a passage included.

Everything is in the page when it is written. The record's part is one JSON block (`world/1`,
`bundle_of` reads it back) at most `CAP_BYTES`; the land table is another, the script a third, and
nothing is fetched: no URL is in the page, and the file carries a Content-Security-Policy that lets
the one script run by its hash and nothing load from anywhere (the Library sends the same policy as a
header). When the record does not fit, the tracks are thinned first (one fix per `TRACK_STEP_MIN`
minutes at most, then ten, twenty, … to one a day; a fix is kept when the asset has moved
`MOVED_M` since the last one kept, every `HOLD_MIN` when it has not, and at both ends of a silence),
then the shortest stays are left out (never a night's); the counts are never thinned, and a record
that still does not fit is refused, naming `--from` and `--to`. `validate` checks that every id the
bundle refers to is in it — a stay's place and asset, a journey's asset and places, a summary's
subject — and a page that fails it is never written.

No coordinate in the page is more precise than the record's own. A place is as `places.json` spells
it, a fix and a journey's route as their line does, to `POINT_DECIMALS` at most; a stay's centre,
which the stays reader computes, to the fewest decimals any of the owner's points inside it carries,
and to `CENTRE_DECIMALS` at most (the precision of the stay's own id).

It is an export and tier-gated like one (ADR 0016): the record is read through `reading.read(...,
tiers)`, a year at a time, so a line whose tier is not asked for is not a stay, not a track, not a
count; the chapters, read from the whole record since a chapter is named after it begins, pass the
same gate. The default is tiers 1 and 2, under the `world` entry of `policy/crossing.json` (2 when the
file does not name it; tier 3 needs the entry). The page says how many lines it held back. Every
export appends one `crossing/v1` line (RFC 0011) with the destination `world`, the window, the counts
and the digest of the page, through `Logbook.append`; nothing else is written to the record. The page
is a function of the record's lines and settings alone (no head, no clock), so a re-run that changes
nothing rewrites nothing."""

from __future__ import annotations

import base64
import hashlib
import json
import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from functools import cache
from html import escape
from importlib import resources
from pathlib import Path
from typing import Any

from ..core import crossing, day_start, policy, reading, stays
from ..core.assets import IDENTIFIERS, Asset
from ..core.chain import Line
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.places import Place, distance_m
from ..core.store import RETRACTION, Logbook, retractions, uuid7
from .vault import digest, write

DESTINATION = policy.WORLD_DESTINATION
FILE_NAME = "world.html"
FORMAT = "world/1"  # the shape of the page's own JSON block; not a profile of the record
CAP_BYTES = 1_000_000  # the record's JSON in the page, at most (the land table and the script beside it)
LAND_BYTES = 48 * 1024  # the vendored land table, at most
TRACK_STEP_MIN = 5  # an asset's track: one fix per five minutes at most, before the cap asks for fewer
TRACK_STEP_MAX = 1440  # one a day: as thin as a track goes
HOLD_MIN = 360  # an asset that has not moved: one fix every six hours still kept
GAP_MIN = 720  # two fixes further apart than this: the asset unseen between them, no line drawn
MOVED_M = 100.0  # this far from the last fix kept, an asset has moved
STAY_CUTS_H = (0, 1, 3, 6, 12)  # then the stays shorter than this left out, a night's never
POINT_DECIMALS = 5  # about a metre: no coordinate in the page has more, and none more than its source
CENTRE_DECIMALS = 4  # a stay's centre: as its derived id spells it, and no more than its points
PATH_POINTS = 500  # a journey's route, at most
JOURNEY_KINDS = ("journey", "trip")  # RFC 0031: readers accept both spellings
JOURNEY_SCHEMAS = ("journey/v1", "trip/v1")
CHAPTER, CHAPTER_SCHEMA = "chapter", "chapter/v1"
PHOTO = "photo"
TIER_SETS = {"1": (1,), "1,2": (1, 2), "1,2,3": (1, 2, 3)}
DEFAULT_TIERS = (1, 2)
PLACE_ID, ASSET_ID = "place:", "asset:"
EN_DASH, ARROW, DOT = "\u2013", "\u2192", " \u00b7 "
MAP_CREDIT = "the map: Natural Earth 1:110m land, public domain"


class WorldError(ValueError):
    """A request the record or the policy refuses, or a page that would not fit; the message says why."""


# -- the request --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """One page, checked against the policy: the local days it covers and the tiers asked for."""

    first: str  # local days, inclusive
    last: str
    tiers: tuple[int, ...]
    max_tier: int

    @property
    def chunks(self) -> list[tuple[str, str]]:
        """The window a calendar year at a time: what one reading holds."""
        a, b = date.fromisoformat(self.first), date.fromisoformat(self.last)
        return [
            (max(a, date(y, 1, 1)).isoformat(), min(b, date(y, 12, 31)).isoformat())
            for y in range(a.year, b.year + 1)
        ]


def parse_tiers(text: str) -> tuple[int, ...]:
    """`--tier 1`, `1,2` or `1,2,3`."""
    key = ",".join(part.strip() for part in text.split(","))
    if key not in TIER_SETS:
        raise WorldError(f"--tier must be 1, 1,2 or 1,2,3, not {text!r}")
    return TIER_SETS[key]


def request(
    lb: Logbook, first: str | None = None, last: str | None = None, tiers: tuple[int, ...] | None = None
) -> Request | None:
    """The page asked for, held against the policy: `tiers` (default 1 and 2, as far as the ceiling
    goes) under the ceiling for `world`, which is refused naming the file; `first` and `last` (local
    days, default the record's first and last day with a line that observes one, `reading.record_span`)
    checked. None when the record has no such day."""
    try:
        max_tier = policy.world_ceiling(lb.root)
    except policy.PolicyError as e:
        raise WorldError(str(e)) from e
    path = policy.policy_path(lb.root)
    if tiers is None:
        tiers = tuple(t for t in DEFAULT_TIERS if t <= max_tier)
        if not tiers:
            raise WorldError(
                f"{path} allows max_tier {max_tier} for {DESTINATION!r}"
                f"{policy.expiry_note(lb.root, DESTINATION)}, so nothing crosses to the page"
            )
    elif max(tiers) > max_tier:
        raise WorldError(
            f"--tier {','.join(map(str, tiers))} is above the ceiling for {DESTINATION!r}: {path} allows"
            f" max_tier {max_tier}{policy.expiry_note(lb.root, DESTINATION)}; "
            f'add {{"{DESTINATION}": {{"max_tier": {max(tiers)}}}}} to it if that is what you want'
        )
    for flag, given in (("--from", first), ("--to", last)):
        if given is not None:
            try:
                parse_day(given)
            except ValueError as e:
                raise WorldError(f"{flag}: {e}") from e
    whole = reading.record_span(lb)
    if whole is None:
        return None
    since, until = first or whole[0], last or whole[1]
    if since > until:
        raise WorldError(f"--from {since} is after --to {until}")
    return Request(since, until, tuple(tiers), max_tier)


def default_out(lb: Logbook) -> Path:
    return lb.root / "export" / DESTINATION


# -- precision ----------------------------------------------------------------------------------------------


def decimals(value: float) -> int:
    """The decimals the record spells `value` with: what its JSON number carried."""
    text = repr(float(value))
    if "e" in text or "E" in text:
        exponent = Decimal(text).as_tuple().exponent
        return max(0, -int(exponent)) if isinstance(exponent, int) else 0
    fraction = text.partition(".")[2]
    return 0 if fraction == "0" else len(fraction)


def own(value: float, at_most: int = POINT_DECIMALS) -> float:
    """`value` at no more decimals than its own, and `at_most`."""
    return round(float(value), min(decimals(value), at_most))


def _coordinate(value: object, low: float, high: float) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) and low <= number <= high else None


def _position(lat: object, lon: object) -> tuple[float, float] | None:
    a, b = _coordinate(lat, -90, 90), _coordinate(lon, -180, 180)
    return None if a is None or b is None else (a, b)


# -- what one page holds ------------------------------------------------------------------------------------


@dataclass
class _Fix:
    at: datetime
    seq: int
    lat: float
    lon: float


@dataclass
class _Stay:
    start: datetime
    end: datetime
    lat: float
    lon: float
    place: str | None
    aboard: str | None
    night: bool


@dataclass
class _Tally:
    """One place's or asset's summary, as the readings add it up."""

    nights: int = 0
    photos: set[str] = field(default_factory=set)
    first: str | None = None
    last: str | None = None

    def seen(self, first: str, last: str) -> None:
        self.first = first if self.first is None else min(self.first, first)
        self.last = last if self.last is None else max(self.last, last)


@dataclass(frozen=True)
class Build:
    """What one page holds, before anything is written: the bundle, its JSON as the page embeds it,
    the page as the export writes it, and the counts the crossing line records."""

    request: Request
    bundle: dict[str, Any]
    json: str
    page: bytes
    logged: int
    crossed: int
    by_tier: dict[str, int]
    by_kind: dict[str, int]
    held_by_kind: dict[str, int]

    @property
    def held_back(self) -> int:
        return self.logged - self.crossed

    def counts(self) -> dict[str, Any]:
        """RFC 0011's `counts`: a page carries no resolution overlay and copies no attachment."""
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
    """Reads the record a year at a time through the gate and gathers what the page draws and counts."""

    def __init__(self, lb: Logbook, req: Request, airports: Airports) -> None:
        self.lb, self.req, self.airports = lb, req, airports
        self.bounds = day_start.of(lb.meta)
        self.start = self.bounds.span(req.first)[0]
        self.end = self.bounds.span(req.last)[1]
        self.minutes = round((self.end - self.start).total_seconds() / 60)
        self.places: list[Place] = []
        self.registry: dict[str, Asset] = {}
        self.owner_points: list[tuple[datetime, int]] = []  # each of the owner's fixes and its decimals
        self._sorted_points: list[tuple[datetime, int]] | None = None
        self._times: list[datetime] = []
        self.fixes: dict[str, dict[int, _Fix]] = {}  # subject → minute → its first fix, inside the window
        self.held_fixes: Counter[str] = Counter()  # subject → the fixes the readings held, each once
        self.stays: list[_Stay] = []
        self.journey_lines: dict[str, Line] = {}
        self.chapters: list[dict[str, Any]] = []
        self.place_tally: dict[str, _Tally] = {}
        self.asset_tally: dict[str, _Tally] = {}
        self.logged = self.crossed = 0
        self.by_tier: Counter[int] = Counter()
        self.by_kind: Counter[str] = Counter()
        self.held_by_kind: Counter[str] = Counter()

    # -- reading --

    def read(self) -> None:
        for first, last in self.req.chunks:
            self._take(reading.read(self.lb, first, last, self.airports, self.req.tiers))
        self._read_chapters()
        self._count()

    def _take(self, rd: reading.Reading) -> None:
        self.places = list(rd.places)
        self.registry = dict(rd.assets)
        for line in rd.lines:
            kind = line.get("kind")
            if kind == "location":
                self._fix(line, rd)
            elif (
                kind in JOURNEY_KINDS
                and (line.get("payload") or {}).get("schema") in JOURNEY_SCHEMAS
                and self._inside(line)
            ):
                self.journey_lines[str(line["id"])] = line
        nights = {
            (n.stay.start, n.stay.end)
            for n in rd.nights
            if n.stay is not None and rd.first <= n.day <= rd.last
        }
        for s in rd.derived.folded:
            if s.kind != stays.STAY or s.subject is not None or s.lat is None or s.lon is None:
                continue
            start, end = max(s.start, self.start), min(s.end, self.end)
            if start >= end:
                continue
            self.stays.append(_Stay(start, end, s.lat, s.lon, s.place, s.aboard, (s.start, s.end) in nights))
        for n in rd.nights:
            if n.stay is None:
                continue
            inner = n.innermost
            if inner is not None and inner.place is not None:
                self.place_tally.setdefault(inner.place, _Tally()).nights += 1
            if n.aboard is not None:
                self.asset_tally.setdefault(n.aboard, _Tally()).nights += 1
        owner = sorted(rd.owner_stays, key=lambda s: s.start)
        owner_starts = [s.start for s in owner]
        last = self.end - timedelta(seconds=1)  # the window's last instant: its end is the next day's start
        for s in owner:
            if s.place is not None and s.start < self.end and s.end > self.start:
                first_day, last_day = self._day(max(s.start, self.start)), self._day(min(s.end, last))
                self.place_tally.setdefault(s.place, _Tally()).seen(first_day, last_day)
        aboard = sorted(
            (s for s in rd.derived.folded if s.subject is None and s.aboard is not None),
            key=lambda s: s.start,
        )
        aboard_starts = [s.start for s in aboard]
        for line in rd.of_kind(PHOTO):
            at = stays.instant(line.get("at"))
            if at is None or not self.start <= at < self.end:
                continue
            here = _containing(owner, owner_starts, at)
            if here is not None and here.place is not None:
                self.place_tally.setdefault(here.place, _Tally()).photos.add(str(line["id"]))
            on = _containing(aboard, aboard_starts, at)
            if on is not None and on.aboard is not None:
                self.asset_tally.setdefault(on.aboard, _Tally()).photos.add(str(line["id"]))

    def _fix(self, line: Line, rd: reading.Reading) -> None:
        """One location line of the window: the owner's, for the precision of the stays' centres; an
        asset's, the first of its minute kept (a receiver may report every few seconds, and a track is
        never drawn finer than `TRACK_STEP_MIN`). Counted once, by the reading whose day it is on (the
        readings overlap by the night after their last day)."""
        payload = line.get("payload") or {}
        found = _position(payload.get("lat"), payload.get("lon"))
        at = stays.instant(line.get("at"))
        if found is None or at is None or not self.start <= at < self.end:
            return
        subject = payload.get("subject")
        if not isinstance(subject, str) or not subject:
            self.owner_points.append((at, min(decimals(found[0]), decimals(found[1]))))
            return
        if rd.first <= self._day(at) <= rd.last:
            self.held_fixes[subject] += 1
        fix = _Fix(at, int(line["seq"]), own(found[0]), own(found[1]))
        minutes = self.fixes.setdefault(subject, {})
        kept = minutes.get(minute := self._minute(at))
        if kept is None or (fix.at, fix.seq) < (kept.at, kept.seq):
            minutes[minute] = fix

    def _inside(self, line: Line) -> bool:
        """Whether a line's `at` is in the window (a reading holds the night after its last day too)."""
        at = stays.instant(line.get("at"))
        return at is not None and self.start <= at < self.end

    def _read_chapters(self) -> None:
        """The standing chapters (RFC 0036 rule 2) whose stretch meets the window, read from the whole
        record — a chapter is named after it begins — through the same gate as the readings."""
        with self.lb.index() as idx:
            found = idx.by_kind(CHAPTER)
            retracted = retractions(idx.retractions())
        lines = [
            line
            for line in reading.crossing(found, self.req.tiers)
            if str(line["id"]) not in retracted
            and (line.get("payload") or {}).get("schema") == CHAPTER_SCHEMA
        ]
        superseded = {
            str(line["payload"].get("supersedes")) for line in lines if line["payload"].get("supersedes")
        }
        for line in lines:
            if str(line["id"]) in superseded:
                continue
            payload = line["payload"]
            name, since, until = payload.get("name"), payload.get("from"), payload.get("to")
            if not isinstance(name, str) or not name.strip() or not _is_day(since):
                continue
            if until is not None and not _is_day(until):
                continue
            if since > self.req.last or (until is not None and until < self.req.first):
                continue
            t0 = max(0, self._minute(self.bounds.span(since)[0]))
            t1 = (
                self.minutes if until is None else min(self.minutes, self._minute(self.bounds.span(until)[1]))
            )
            self.chapters.append(
                {"id": str(line["id"]), "name": name, "from": since, "to": until, "t0": t0, "t1": t1}
            )
        self.chapters.sort(key=lambda c: (c["t0"], c["id"]))

    def _count(self) -> None:
        """Every line of the window, crossing or held back, from the index's columns."""
        with self.lb.index() as idx:
            found = idx.window(stays.instant_text(self.start), stays.instant_text(self.end))
        for place in found:
            at = stays.instant(place.at)
            if place.kind == RETRACTION or at is None or not self.start <= at < self.end:
                continue
            self.logged += 1
            if place.tier in self.req.tiers:
                self.crossed += 1
                self.by_tier[place.tier] += 1
                self.by_kind[place.kind] += 1
            else:
                self.held_by_kind[place.kind] += 1

    # -- the bundle --

    def bundle(self, step: int, cut_h: int) -> dict[str, Any]:
        """The page's JSON at one thinning: the tracks at one fix per `step` minutes at most, the stays
        shorter than `cut_h` hours left out (a night's never)."""
        hold = max(HOLD_MIN, step)
        gap = max(GAP_MIN, 2 * hold)
        place_ids = {p.name: PLACE_ID + p.name for p in self.places}
        journeys = self._journeys(place_ids)
        subjects = self._subjects(journeys)
        assets = []
        kept = 0
        for subject in subjects:
            track = self._thin(subject, step, hold, gap)
            kept += len(track) // 3
            registered = self.registry.get(subject)
            assets.append(
                {
                    "id": ASSET_ID + subject,
                    "name": registered.name if registered else subject,
                    "kind": registered.kind if registered else None,
                    "track": track,
                }
            )
        merged = self._merged_stays()
        shown = [s for s in merged if s.night or (s.end - s.start).total_seconds() >= cut_h * 3600]
        return {
            "format": FORMAT,
            "window": {
                "from": self.req.first,
                "to": self.req.last,
                "tz": str(self.bounds.zone),
                "day_start": self.bounds.text,
                "start": int(self.start.timestamp()),
                "minutes": self.minutes,
                "gap_min": gap,
            },
            "tiers": list(self.req.tiers),
            "places": [
                {
                    "id": place_ids[p.name],
                    "name": p.name,
                    "kind": p.kind,
                    "lat": own(p.lat),
                    "lon": own(p.lon),
                    "radius_m": round(p.radius_m),
                }
                for p in self.places
            ],
            "assets": assets,
            "stays": [self._stay_json(s, place_ids) for s in shown],
            "journeys": [j["json"] for j in journeys],
            "chapters": self.chapters,
            "summaries": self._summaries(place_ids, journeys, subjects),
            "held_back": {
                "lines": self.logged - self.crossed,
                "by_kind": dict(sorted(self.held_by_kind.items())),
            },
            "thinned": {
                "track_step_min": step,
                "stays_under_h": cut_h,
                "fixes": {"kept": kept, "of": sum(self.held_fixes.values())},
                "stays_left_out": len(merged) - len(shown),
            },
        }

    def _subjects(self, journeys: Sequence[Mapping[str, Any]]) -> list[str]:
        """Every asset of the registry in its order, then any other subject the window's lines name
        (ADR 0018 rule 4: a subject the registry no longer names is still shown, under its id)."""
        named = set(self.fixes) | {str(j["subject"]) for j in journeys if j["subject"]}
        named |= {s.aboard for s in self.stays if s.aboard}
        return [*self.registry, *sorted(named - set(self.registry))]

    def _thin(self, subject: str, step: int, hold: int, gap: int) -> list[float | int]:
        """One asset's track as the page holds it, `[minute, lat, lon, …]`: a fix is kept when it is
        `step` minutes after the last one kept and the asset has moved `MOVED_M` since (the fix before
        it too, so a departure is not smeared over the hours at anchor), or `hold` minutes after it
        whatever; the first and the last, and both ends of a silence longer than `gap`, always."""
        fixes = sorted(self.fixes.get(subject, {}).values(), key=lambda f: (f.at, f.seq))
        kept: list[_Fix] = []
        for i, f in enumerate(fixes):
            last = kept[-1] if kept else None
            silence_before = i > 0 and (f.at - fixes[i - 1].at).total_seconds() > gap * 60
            silence_after = i + 1 < len(fixes) and (fixes[i + 1].at - f.at).total_seconds() > gap * 60
            if last is None or silence_before or silence_after or i == len(fixes) - 1:
                kept.append(f)
                continue
            since = (f.at - last.at).total_seconds() / 60
            if since < step:
                continue
            if distance_m(last.lat, last.lon, f.lat, f.lon) >= MOVED_M:
                before = fixes[i - 1]
                if before is not last and (before.at - last.at).total_seconds() / 60 >= step:
                    kept.append(before)
                kept.append(f)
            elif since >= hold:
                kept.append(f)
        out: list[float | int] = []
        for f in kept:
            out += [self._minute(f.at), f.lat, f.lon]
        return out

    def _merged_stays(self) -> list[_Stay]:
        """The owner's stays in time order; the two halves of a stay a year's end cut (the readings
        overlap by the night after their last day) are one again."""
        out: list[_Stay] = []
        for s in sorted(self.stays, key=lambda s: (s.start, s.end)):
            if out:
                prev = out[-1]
                same = prev.place == s.place and prev.aboard == s.aboard
                near = distance_m(prev.lat, prev.lon, s.lat, s.lon) <= 2 * stays.HOME_NEAR_M
                if s.start <= prev.end and same and near:
                    prev.end = max(prev.end, s.end)
                    prev.night = prev.night or s.night
                    continue
            out.append(_Stay(s.start, s.end, s.lat, s.lon, s.place, s.aboard, s.night))
        return out

    def _stay_json(self, s: _Stay, place_ids: Mapping[str, str]) -> dict[str, Any]:
        digits = min(CENTRE_DECIMALS, self._decimals_inside(s.start, s.end))
        return {
            "t0": self._minute(s.start),
            "t1": self._minute(s.end),
            "lat": round(s.lat, digits),
            "lon": round(s.lon, digits),
            "place": place_ids.get(s.place) if s.place else None,
            "aboard": ASSET_ID + s.aboard if s.aboard else None,
            "night": s.night,
        }

    def _decimals_inside(self, start: datetime, end: datetime) -> int:
        """The fewest decimals any of the owner's fixes from `start` to `end` carries: the precision
        the stay's centre may have. A stay with none inside (it cannot happen: a stay is its points)
        is held to the fewest of the whole window, and to 2 when there is none at all."""
        if self._sorted_points is None:
            self._sorted_points = sorted(self.owner_points)
            self._times = [at for at, _d in self._sorted_points]
        points = self._sorted_points
        i, j = bisect_left(self._times, start), bisect_right(self._times, end)
        inside = [d for _at, d in points[i:j]] or [d for _at, d in points] or [2]
        return min(inside)

    def _journeys(self, place_ids: Mapping[str, str]) -> list[dict[str, Any]]:
        """The standing journeys of the window: not superseded by a later one (RFC 0020 `supersedes`),
        not cancelled, in time order, each with its route, its asset and the places at its ends."""
        lines = list(self.journey_lines.values())
        superseded = {str(p["supersedes"]) for line in lines if (p := line["payload"]).get("supersedes")}
        out = []
        for line in sorted(
            lines, key=lambda line: (stays.instant(line.get("at")) or self.start, line["seq"])
        ):
            payload = line["payload"]
            if str(line["id"]) in superseded or payload.get("status") == "cancelled":
                continue
            at, end = stays.instant(line.get("at")), stays.instant(line.get("end"))
            if at is None:
                continue
            ends = [e if isinstance(e, dict) else {} for e in (payload.get("from"), payload.get("to"))]
            subject = payload.get("subject") if isinstance(payload.get("subject"), str) else None
            names = [str(e.get("name")) for e in ends if isinstance(e.get("name"), str) and e.get("name")]
            name = payload.get("name") if isinstance(payload.get("name"), str) else None
            out.append(
                {
                    "subject": subject or None,
                    "json": {
                        "id": str(line["id"]),
                        "name": name or f" {ARROW} ".join(names) or str(payload.get("mode") or "journey"),
                        "mode": payload.get("mode") if isinstance(payload.get("mode"), str) else None,
                        "subject": ASSET_ID + subject if subject else None,
                        "t0": self._minute(at),
                        "t1": None if end is None else self._minute(end),
                        "path": _path(payload, ends),
                        "places": self._ends_at(ends, place_ids),
                    },
                }
            )
        return out

    def _ends_at(self, ends: Sequence[Mapping[str, Any]], place_ids: Mapping[str, str]) -> list[str]:
        """The places a journey starts and ends at: by the name its line gives, or by its position
        inside the place's radius."""
        found: list[str] = []
        for e in ends:
            name = e.get("name")
            spot = _position(e.get("latitude"), e.get("longitude"))
            for p in self.places:
                by_name = isinstance(name, str) and name.strip().casefold() == p.name.casefold()
                by_spot = spot is not None and distance_m(spot[0], spot[1], p.lat, p.lon) <= p.radius_m
                if (by_name or by_spot) and place_ids[p.name] not in found:
                    found.append(place_ids[p.name])
        return found

    def _summaries(
        self, place_ids: Mapping[str, str], journeys: Sequence[Mapping[str, Any]], subjects: Sequence[str]
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for p in self.places:
            tally = self.place_tally.get(p.name, _Tally())
            out[place_ids[p.name]] = {
                "name": p.name,
                "kind": p.kind,
                "nights": tally.nights,
                "journeys": sum(1 for j in journeys if place_ids[p.name] in j["json"]["places"]),
                "photos": len(tally.photos),
                "first": tally.first,
                "last": tally.last,
            }
        for subject in subjects:
            tally = self.asset_tally.get(subject, _Tally())
            registered = self.registry.get(subject)
            fixes = [f.at for f in self.fixes.get(subject, {}).values()]
            out[ASSET_ID + subject] = {
                "name": registered.name if registered else subject,
                "kind": registered.kind if registered else None,
                "identifiers": {k: v for k in IDENTIFIERS if registered and (v := getattr(registered, k))},
                "nights": tally.nights,
                "journeys": sum(1 for j in journeys if j["subject"] == subject),
                "photos": len(tally.photos),
                "first": self._day(min(fixes)) if fixes else None,
                "last": self._day(max(fixes)) if fixes else None,
            }
        return out

    # -- helpers --

    def _minute(self, instant: datetime) -> int:
        return round((instant - self.start).total_seconds() / 60)

    def _day(self, instant: datetime) -> str:
        return self.bounds.day(instant).isoformat()


def _containing(
    segments: Sequence[stays.Segment], starts: Sequence[datetime], at: datetime
) -> stays.Segment | None:
    """The segment of `segments` (in time order, none overlapping; `starts` their starts) whose span
    holds `at`, ends included, as `logbook show place` counts a photo."""
    i = bisect_right(starts, at) - 1
    return segments[i] if i >= 0 and segments[i].start <= at <= segments[i].end else None


def _path(payload: Mapping[str, Any], ends: Sequence[Mapping[str, Any]]) -> list[float]:
    """A journey's route as `[lat, lon, …]`: its `geometry` when the line carries a LineString, else its
    two ends, else the one end it has (a parking), else nothing; at most `PATH_POINTS`."""
    points: list[tuple[float, float]] = []
    geometry = payload.get("geometry")
    if isinstance(geometry, dict) and geometry.get("type") == "LineString":
        for pair in geometry.get("coordinates") or []:
            if isinstance(pair, list | tuple) and len(pair) >= 2 and (found := _position(pair[1], pair[0])):
                points.append(found)
    if len(points) < 2:
        points = [found for e in ends if (found := _position(e.get("latitude"), e.get("longitude")))]
    if len(points) > PATH_POINTS:
        stride = math.ceil(len(points) / PATH_POINTS)
        points = [*points[:-1:stride], points[-1]]
    return [own(v) for point in points for v in point]


def _is_day(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parse_day(value)
    except ValueError:
        return False
    return True


# -- the JSON, checked --------------------------------------------------------------------------------------


def to_json(bundle: Mapping[str, Any]) -> str:
    """The bundle as the page embeds it: compact, and safe inside a script element (`<`, `>` and `&`
    escaped, as JSON allows)."""
    text = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"))
    return text.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def validate(bundle: Mapping[str, Any]) -> list[str]:
    """What is wrong with the bundle, one sentence each; empty when every id it refers to is in it — a
    stay's place and asset, a journey's asset and places, a summary's subject — no id is given twice,
    every place and asset has its summary and every coordinate is on the earth."""
    problems: list[str] = []
    places = [str(p["id"]) for p in bundle.get("places", [])]
    assets = [str(a["id"]) for a in bundle.get("assets", [])]
    for what, ids in (
        ("place", places),
        ("asset", assets),
        ("journey", [str(j["id"]) for j in bundle.get("journeys", [])]),
        ("chapter", [str(c["id"]) for c in bundle.get("chapters", [])]),
    ):
        for found, n in Counter(ids).items():
            if n > 1:
                problems.append(f"the {what} {found!r} is given {n} times")
    known_places, known_assets = set(places), set(assets)
    for n, s in enumerate(bundle.get("stays", [])):
        if s.get("place") is not None and s["place"] not in known_places:
            problems.append(f"stay {n} names {s['place']!r}, which is no place of the page")
        if s.get("aboard") is not None and s["aboard"] not in known_assets:
            problems.append(f"stay {n} is aboard {s['aboard']!r}, which is no asset of the page")
        if _position(s.get("lat"), s.get("lon")) is None:
            problems.append(f"stay {n} is not on the earth")
    for j in bundle.get("journeys", []):
        if j.get("subject") is not None and j["subject"] not in known_assets:
            problems.append(f"journey {j['id']} is {j['subject']!r}'s, which is no asset of the page")
        for p in j.get("places", []):
            if p not in known_places:
                problems.append(f"journey {j['id']} ends at {p!r}, which is no place of the page")
        path = j.get("path", [])
        if len(path) % 2 or any(_position(a, b) is None for a, b in zip(path[0::2], path[1::2], strict=True)):
            problems.append(f"journey {j['id']} has a route off the earth")
    for a in bundle.get("assets", []):
        track = a.get("track", [])
        if len(track) % 3 or any(
            _position(lat, lon) is None for lat, lon in zip(track[1::3], track[2::3], strict=True)
        ):
            problems.append(f"the track of {a['id']!r} is off the earth")
    for p in bundle.get("places", []):
        if _position(p.get("lat"), p.get("lon")) is None:
            problems.append(f"the place {p['id']!r} is not on the earth")
    summaries = bundle.get("summaries", {})
    for found in [*places, *assets]:
        if found not in summaries:
            problems.append(f"{found!r} has no summary")
    for key in summaries:
        if key not in known_places | known_assets:
            problems.append(f"the summary of {key!r} names nothing on the page")
    return problems


def build(lb: Logbook, req: Request, airports: Airports | None = None) -> Build:
    """Read the record and make the page; nothing is written. `WorldError` when the page would not fit
    under `CAP_BYTES` however thin, or (a bug) refers to an id it does not hold; `stays.SettingsError`
    when the record's settings, places or assets file is not what it should be."""
    builder = _Builder(lb, req, airports or Airports.load())
    builder.read()
    steps = [TRACK_STEP_MIN]
    while steps[-1] < TRACK_STEP_MAX:
        steps.append(min(TRACK_STEP_MAX, steps[-1] * 2))
    tries = [(step, 0) for step in steps] + [(TRACK_STEP_MAX, cut) for cut in STAY_CUTS_H[1:]]
    for step, cut in tries:
        bundle = builder.bundle(step, cut)
        text = to_json(bundle)
        if len(text.encode("utf-8")) <= CAP_BYTES:
            break
    else:
        size = len(text.encode("utf-8"))
        raise WorldError(
            f"the page of {req.first} {EN_DASH} {req.last} is {size:,} bytes even with the tracks at one fix"
            f" a day and the stays under {STAY_CUTS_H[-1]} h left out, over the cap of {CAP_BYTES:,};"
            " narrow it with --from and --to"
        )
    problems = validate(bundle)
    if problems:
        raise WorldError("the page refers to what it does not hold: " + "; ".join(problems))
    return Build(
        req,
        bundle,
        text,
        page(text, standalone=True).encode("utf-8"),
        builder.logged,
        builder.crossed,
        {str(t): builder.by_tier.get(t, 0) for t in policy.TIERS},
        dict(sorted(builder.by_kind.items())),
        dict(sorted(builder.held_by_kind.items())),
    )


# -- the page -----------------------------------------------------------------------------------------------


@cache
def land_json() -> str:
    """The vendored land table as the page embeds it."""
    return (resources.files("logbook") / "tables" / "land.json").read_text(encoding="utf-8").strip()


def land() -> dict[str, Any]:
    found: dict[str, Any] = json.loads(land_json())
    return found


def embedded_json(page_text: str) -> str:
    """The record's JSON block of a page, as it is written there."""
    head = '<script type="application/json" id="world">'
    start = page_text.index(head) + len(head)
    return page_text[start : page_text.index("</script>", start)]


def bundle_of(page_text: str) -> dict[str, Any]:
    """The record's JSON of a page, read back."""
    found: dict[str, Any] = json.loads(embedded_json(page_text))
    return found


SCRIPT = (resources.files("logbook") / "contrib" / "world.js").read_text(encoding="utf-8")  # the one script
SCRIPT_HASH = "sha256-" + base64.b64encode(hashlib.sha256(SCRIPT.encode("utf-8")).digest()).decode()
POLICY = (  # the exported file's own Content-Security-Policy: the one script by its hash, nothing fetched
    f"default-src 'none'; script-src '{SCRIPT_HASH}'; style-src 'unsafe-inline'; base-uri 'none';"
    " form-action 'none'"
)

STYLE = """
:root{color-scheme:light dark;--fg:#1c1c1c;--bg:#fff;--mute:#6a6a6a;--line:#ddd;--accent:#2f5d7c;
--space:#eef0f2;--ocean:#d9e6ef;--land:#f3efe4;--coast:#93a3ae;--grid:rgba(47,93,124,.14);--stay:#2e8b57;
--you:#c0392b;--journey:#c0652a;--yacht:#1f7f9a;--aircraft:#7a4fb5;--car:#8a6d1f;--asset:#555;
--place:#2f5d7c;--band1:#cddbe6;--band2:#e8dccd}
@media (prefers-color-scheme:dark){:root{--fg:#e8e8e8;--bg:#141414;--mute:#9b9b9b;--line:#333;
--accent:#8fb8d6;--space:#0c0f12;--ocean:#142330;--land:#2b2d2a;--coast:#5b6a74;--grid:rgba(143,184,214,.13);
--stay:#5fbf8a;--you:#ff6b5a;--journey:#e8935a;--yacht:#5cc3dd;--aircraft:#b58cf0;--car:#d4b25a;
--asset:#aaa;--place:#8fb8d6;--band1:#2b3c4a;--band2:#4a3b2b}}
html,body{height:100%}
body{margin:0;font:14px/1.4 system-ui,sans-serif;color:var(--fg);background:var(--bg);display:flex;
flex-direction:column}
header{padding:.4rem 1rem;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:.2rem 1rem;
align-items:baseline}
header nav a{margin-right:.8rem;color:var(--accent);text-decoration:none}
h1{font-size:1.05rem;margin:0}
h1 small{color:var(--mute);font-weight:400;font-size:.85em}
#readout{margin:0;color:var(--mute);flex:1 1 20rem}
main{flex:1;position:relative;min-height:18rem;overflow:hidden}
#globe{position:absolute;inset:0;width:100%;height:100%;touch-action:none;cursor:grab}
#globe:active{cursor:grabbing}
#tools{position:absolute;top:.5rem;right:.5rem;display:flex;gap:.3rem}
#list{position:absolute;top:.5rem;left:.5rem;max-height:calc(100% - 3rem);overflow:auto;list-style:none;
margin:0;padding:0;display:flex;flex-direction:column;gap:.2rem;align-items:flex-start}
#panel{position:absolute;top:2.6rem;right:.5rem;width:17rem;max-height:calc(100% - 3.5rem);overflow:auto;
background:var(--bg);border:1px solid var(--line);border-radius:4px;padding:.5rem .7rem}
#panel h2{font-size:1rem;margin:0 0 .4rem}
#panel dl{display:grid;grid-template-columns:max-content 1fr;gap:.15rem .7rem;margin:0}
#panel dt{color:var(--mute)}
#panel dd{margin:0;font-variant-numeric:tabular-nums}
#panel .close{float:right}
#credit{position:absolute;bottom:.3rem;right:.6rem;margin:0;color:var(--mute);font-size:.75rem}
footer{border-top:1px solid var(--line);padding:.4rem 1rem;display:flex;gap:.7rem;align-items:center}
.scrub{flex:1;min-width:0}
#bands{display:block;width:100%;height:34px;cursor:pointer}
#time{display:block;width:100%;margin:0}
#clock{font-variant-numeric:tabular-nums;white-space:nowrap;color:var(--mute);min-width:11rem;text-align:right}
button{font:inherit;padding:.15rem .55rem;background:var(--bg);color:var(--fg);border:1px solid var(--line);
border-radius:3px;cursor:pointer}
noscript table{border-collapse:collapse;margin:1rem}
noscript th,noscript td{text-align:left;padding:.2rem .6rem;border-bottom:1px solid var(--line)}
@media (max-width:40rem){#list{display:none}#clock{min-width:0}}
"""


def page(json_text: str, nav: str = "", standalone: bool = True) -> str:
    """The page around the record's JSON: the canvas, the scrubber, the land table, the script.
    `standalone` (the exported file) carries the Content-Security-Policy in a meta element, since a
    file has no headers; the Library sends it as one and passes its navigation as `nav`."""
    bundle = json.loads(json_text)
    window = bundle["window"]
    tiers = ",".join(map(str, bundle["tiers"]))
    span = window["from"] if window["from"] == window["to"] else f"{window['from']} {EN_DASH} {window['to']}"
    head = f"{span}{DOT}tier {tiers}{DOT}{window['tz']}"
    held = bundle["held_back"]["lines"]
    if held:
        head += f"{DOT}held back: {_plural(held, 'line')} above tier {max(bundle['tiers'])}"
    policy_meta = f'<meta http-equiv="Content-Security-Policy" content="{POLICY}">\n' if standalone else ""
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{policy_meta}"
        "<title>The world · Logbook</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n"
        f"<header>{f'<nav>{nav}</nav>' if nav else ''}"
        f"<h1>The world <small>{escape(head)}</small></h1>"
        '<p id="readout" aria-live="polite"></p></header>\n'
        "<main>\n"
        '<canvas id="globe" aria-label="the globe: the named places, the assets on their tracks, the stays'
        ' and the journeys at the time the scrubber shows; drag to turn it, scroll to zoom"></canvas>\n'
        '<ul id="list" aria-label="the places and the assets"></ul>\n'
        '<div id="tools"><button id="zoom-in" aria-label="zoom in">+</button>'
        '<button id="zoom-out" aria-label="zoom out">\u2212</button>'
        '<button id="fit">fit</button><button id="whole">globe</button></div>\n'
        '<aside id="panel" aria-live="polite" hidden></aside>\n'
        f'<p id="credit">{escape(MAP_CREDIT)}{DOT}nothing here is fetched</p>\n'
        f"{_noscript(bundle)}"
        "</main>\n"
        '<footer><button id="play">play</button><div class="scrub">'
        '<canvas id="bands" aria-hidden="true"></canvas>'
        f'<input id="time" type="range" min="0" max="{int(window["minutes"])}" step="1" value="0"'
        ' aria-label="the time the globe shows"></div><span id="clock"></span></footer>\n'
        f'<script type="application/json" id="land">{land_json()}</script>\n'
        f'<script type="application/json" id="world">{json_text}</script>\n'
        f"<script>{SCRIPT}</script>\n"
        "</body>\n</html>\n"
    )


def _noscript(bundle: Mapping[str, Any]) -> str:
    """The summaries as a table, for a browser that runs no script."""
    rows = []
    for key, s in bundle["summaries"].items():
        what = "asset" if key.startswith(ASSET_ID) else "place"
        cells = [
            s["name"],
            f"{what}, {s['kind']}" if s["kind"] else what,
            s["nights"],
            s["journeys"],
            s["photos"],
        ]
        rows.append("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in cells) + "</tr>")
    return (
        "<noscript><p>The globe draws with the page's one script. Its summaries:</p><table>"
        "<tr><th>name</th><th>what</th><th>nights</th><th>journeys</th><th>photos</th></tr>"
        f"{''.join(rows)}</table></noscript>\n"
    )


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


# -- writing, and the line that says it left -----------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    path: Path
    written: bool
    sha256: str  # of the folder as written: the page's digest and name, hashed as a vault's folder is
    line: Line  # the crossing/v1 line appended


def export(lb: Logbook, built: Build, folder: Path, generated_at: str) -> Result:
    """Write the page, then append the crossing line: in that order, so a crash leaves at worst a page
    no line names, and the next run writes the same page again and does name it."""
    policy.write_default(lb.root)  # the first export writes the default; an existing file is kept
    req, bundle = built.request, built.bundle
    head = str(lb.meta["head"])
    files = {FILE_NAME: built.page}
    written, _unchanged = write(folder, files)
    sha256 = digest(files)
    bounds = day_start.of(lb.meta)
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
                "from": stays.instant_text(bounds.span(req.first)[0]),
                "to": stays.instant_text(bounds.span(req.last)[1]),
            },
            "tiers": list(req.tiers),
            "counts": built.counts(),
            "policy": {"file": policy.POLICY_FILE.as_posix(), "max_tier": req.max_tier},
            "logbook_head": head,
            "package_sha256": sha256,
            "extra": {
                "world": {
                    "bytes": len(built.page),
                    "json_bytes": len(built.json.encode("utf-8")),
                    "places": len(bundle["places"]),
                    "assets": len(bundle["assets"]),
                    "stays": len(bundle["stays"]),
                    "journeys": len(bundle["journeys"]),
                    "chapters": len(bundle["chapters"]),
                    "thinned": bundle["thinned"],
                    "written": bool(written),
                }
            },
        },
        recorded_at=generated_at,
    )
    return Result(Path(folder) / FILE_NAME, bool(written), sha256, line)


def _summary_lines(built: Build) -> Iterable[str]:
    """What the console says about a page beyond its first line."""
    b = built.bundle
    fixes = b["thinned"]["fixes"]
    yield (
        f"  {_plural(len(b['places']), 'place')}, {_plural(len(b['assets']), 'asset')}"
        f" ({fixes['kept']:,} of {fixes['of']:,} fixes drawn), {_plural(len(b['stays']), 'stay')},"
        f" {_plural(len(b['journeys']), 'journey')}, {_plural(len(b['chapters']), 'chapter')};"
        f" {len(built.json.encode('utf-8')):,} bytes of JSON, the cap {CAP_BYTES:,}"
    )
    thinned = b["thinned"]
    if thinned["track_step_min"] > TRACK_STEP_MIN or thinned["stays_left_out"]:
        text = f"  thinned to fit: tracks at one fix per {thinned['track_step_min']} min at most"
        if thinned["stays_left_out"]:
            text += (
                f", {_plural(thinned['stays_left_out'], 'stay')} under {thinned['stays_under_h']} h left out"
            )
        yield text
    if built.held_back:
        by_kind = ", ".join(f"{kind} {n}" for kind, n in built.held_by_kind.items())
        top = max(built.request.tiers)
        yield f"  held back: {_plural(built.held_back, 'line')} above tier {top} ({by_kind})"


def console(built: Build, result: Result) -> Iterator[str]:
    """The lines `export world` prints."""
    req = built.request
    days = (date.fromisoformat(req.last) - date.fromisoformat(req.first)).days + 1
    tiers = ",".join(map(str, req.tiers))
    window = f"{req.first} {EN_DASH} {req.last}"
    yield f"world: {_plural(days, 'day')} {window}, tier {tiers} {ARROW} {result.path}"
    yield from _summary_lines(built)
    state = "written" if result.written else "unchanged"
    seq, sha = result.line["seq"], result.sha256[:12]
    yield f"  recorded as #{seq} {crossing.LINE_SCHEMA}, page sha256 {sha}… ({state})"


def library_page(
    lb: Logbook, first: str | None, last: str | None, nav: str, airports: Airports
) -> str | None:
    """The Library's `/world`: the page the export writes by default (the same request, the same
    JSON), with the Library's navigation and the policy left to the header; None for a record with
    no day."""
    req = request(lb, first, last)
    if req is None:
        return None
    built = build(lb, req, airports)
    return page(built.json, nav=nav, standalone=False)
