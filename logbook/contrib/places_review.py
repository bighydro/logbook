"""Observed places, the review queue and the owner's say — `logbook setup places review`.

The record has two layers of places, as it has two of people (`people review`). An **observed**
place is a spot the owner's track comes back to: a cluster of the owner's stays. A **named** place
is one the owner has given a name, an entry of `places.json`. Nothing here invents a third store:
the named places are read as every reader reads them, and a naming is what `places name` writes.

**The table.** Observed places are the place rows of the index's derived table,
`observed_entities` in `index.sqlite` (RFC 0037), read through its view `observed_places`. The
owner's stays of the whole record (`reading.owner_track`: from the index alone, so two million
points are read in seconds) are taken in order of hours, most first; a stay joins the
nearest cluster whose anchor — its first stay, the one with the most hours — lies within
`CLUSTER_M`, **75 m** by default (`--radius`), else it anchors a cluster of its own. An anchor, not
a running centre, as the stays themselves are clustered, so a row of stays along a quay does not
drift into one place. Each cluster carries its **visits** (its stays), its **nights** (the nights
whose overnight stay, as `day` picks it, is one of its stays), its **first** and **last** (the first
stay's start, the last stay's end), its total **hours**, its centre (the mean of its stays' centres
weighted by hours), its **spread** (the distance from the centre within which 95% of its hours
lie), the named place it lies in (the one most of its hours were at, else the one whose radius holds
its centre), the asset most of its hours were aboard, and the **names** the record holds for the
spot. The rows are built from the lines, stamped with the head, the zone, the radius and the digests
of `places.json`, `assets.json` and `policy/stays.json` (in `observed_entities_meta`), served while
the stamp holds and built again when it does not; its shape is checked with `PRAGMA table_info`
and a table of another shape is built again. Nothing is stored in the record.

**The names.** Only what the record already holds, from any source; each name counts under the
source that said it:

- **Google Timeline**: a `placeVisit` of the archive's Semantic Location History names its place
  (`location.name`, else `location.address`); any Timeline visit whose semantic type is home or work
  (`TYPE_HOME`, `INFERRED_WORK`, `Home`) says `Home` or `Work`. The phones' own exports name nothing
  else: they carry a place id and a type, never a name.
- **Photos**: a photo line's `extra.place`, as its library named the spot: `name`, else the first
  of `names` (the areas Photos put it in), else `address`, else `city` (all Immich has).
- **Calendar**: the `location` of a timed entry, not cancelled, held during one of the cluster's
  stays (overlapping it for half its length or more); its first line, as written. An entry whose
  own coordinates lie farther than 1 km from the cluster, and an online meeting (a URL, Zoom, Teams,
  Meet, Webex, Skype, FaceTime), name nothing; an all-day entry names no hour, so no stay.
- **Dawarich**: what its reverse geocoder wrote on the first and last point of a stay
  (`extra.place.name`, else the street and number), once per stay.

A shared location sent in iMessage or WhatsApp would count as well, but the adapters keep no
coordinates for one, so none is read. A name with coordinates names the cluster nearest them within
`MATCH_M` (150 m), preferring one with a stay at that hour; a name without names the cluster of the
stay its line falls in.

**Nothing leaves the machine.** No geocoder is asked, online or off: a spot has a name here only when
a source wrote one into a line. Where none did, the proposal is a blank for the owner to fill. The one
thing the owner may add is `--ask-photos` (`places_photos`): the names their own photo libraries hold
for the photos already in the record, asked by asset id, counted as `library` evidence (`immich ×12:
Havbyen`), weighed as a photo line's place is; this module never asks anything itself.

**The queue.** One proposal per observed place at no named place, ranked by nights, then hours,
then the first visit, numbered from 1. Its name is the one the evidence weighs most — a Timeline
name or a calendar location counts 3 a line, a photo's or Dawarich's name 2, a city or a Timeline
semantic type 1 — passing over a name already in `places.json` and one rejected for this spot. Each
carries its evidence (which source said which name, how often) and the radius accepting it would
write. `--near PLACE` lists the proposals within 5 km of a named place or of `lat,lon`, and `--top N`
the first N, keeping the queue's numbers. The evidence is shown folded (`groups`): the addresses one
source wrote along one street are one line ("Plattformveien", 38 addresses, 217 stays), since a
reverse geocoder names every house number a track passes, and three lines are shown, the rest counted
("… and N more"); `--verbose` prints every name on its own. `logbook serve`'s Places page shows the
same folding, from the same code.

**The owner's say.** Nothing is accepted on its own. `--accept N[,N]` writes each place into
`places.json` — the cluster's centre, its fitted radius, kind `other` — and puts the naming in the
record as `places name` does, one `note/v1` line through `Logbook.append` (`places.name`).
`--name N "…"` accepts with the owner's own name. `--reject N[,N]` puts the pair — the spot and the
name proposed, or the blank — in the record as one `entity-review/v1` line of type place (RFC 0037,
decision 3 of 13 October 2026: its `ref` the spot's `centre`, its `label` the name, its `evidence` the
stays' lines, its tier the highest of theirs and never under 2), under the writer lock; the Places
page of `logbook serve` rejects through the same `reject`. That name is not proposed for that spot
again, and a rejected blank keeps the spot out of the queue until a source names it; retract the line
and the pair returns. `state/places-review.json` is a cache of those lines, rebuilt from them whenever
the record has moved, never the truth: deleting it changes nothing a reader shows. A no it holds from
before 0.7, when the pairs were kept there and never as lines, counts until `--migrate-rejects` writes
it as a line, once (`migrate_rejects`). Every number is checked before anything is written. On a
terminal, `review` asks for each proposal: y, n, or a name (`logbook.commands.places`).

**The fitted radius.** The spread and 75 m for the scatter of one stay's own fixes, rounded up to
5 m, between 75 and 300 m; drawn back, to the whole metre, so that the circle stays out of every
named place's own, though never below 50 m. A place whose centre lies inside a named place's
circle is refused: it is that place already."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from ..core import assets, day_start, kept, places, reading, stays
from ..core.chain import Line
from ..core.export import day_range
from ..core.index import Index
from ..core.places import Place
from ..core.store import RETRACTION, Logbook, now_utc
from . import entities

CLUSTER_M = 75.0  # a stay this close to a cluster's anchor is at that spot
MATCH_M = 150.0  # a name with coordinates this close to a cluster's centre names it
EVENT_NEAR_M = 1000.0  # a calendar entry located farther than this from the cluster is about elsewhere
SPREAD_SHARE = 0.95  # the spread: the distance within which this share of a cluster's hours lie
FIT_MARGIN_M, FIT_STEP_M, FIT_MIN_M, FIT_MAX_M, FIT_FLOOR_M = 75.0, 5.0, 75.0, 300.0, 50.0
NEAR_KM = 5.0  # `--near`: within this of the place
TABLE = "observed_places"  # the view of the place rows of `observed_entities` (RFC 0037)
OBSERVED_KIND = "place"
TABLE_VERSION = "1"
COLUMNS = (
    "id",
    "lat",
    "lon",
    "visits",
    "nights",
    "hours",
    "first",
    "last",
    "spread_m",
    "place",
    "aboard",
    "names",
    "lines",
)
STATE_FILE = PurePosixPath("state/places-review.json")  # record-relative: a cache of the lines
MIGRATED_FROM = str(STATE_FILE)  # `extra.migrated_from` of a line `--migrate-rejects` wrote
TIMELINE_SEGMENTS = {"visit:": "visit", "placeVisit:": "placeVisit"}  # raw_id prefix → `extra.segment`
FACT_GROUPS = (*(f"timeline:{prefix}" for prefix in TIMELINE_SEGMENTS), "photo", "event")  # names, in order
KEPT_FILE, KEPT_VERSION = "places-whole.json", 1  # the owner's stays and what the lines name (`_kept`)
MARGIN_DAYS = 3  # the last days read are read again: a point or evidence late by this is brought forward
LOOKBACK_DAYS, LOOKBACK_MOST = 32, 512  # how far before them the owner's track is read again
SEGMENT_PLAIN = (
    "kind", "subject", "points", "lat", "lon", "place", "attached", "promoted", "aboard", "distance_m",
    "mode", "first_line", "last_line", "first_seq", "last_seq",
)  # fmt: skip
# a line's weight for a specific name; `library` is a photo whose library was asked (`places_photos`)
WEIGHTS = {"timeline": 3, "calendar": 3, "photo": 2, "dawarich": 2, "library": 2}
COARSE = ("city", "type")  # grades that weigh 1 whatever said them
UNITS = {"timeline": "visit", "photo": "photo", "calendar": "event", "dawarich": "stay", "library": "photo"}
ORIGINS = tuple(UNITS)
SAMPLES = 3  # line ids kept per name, as evidence
TYPES = {"HOME": "Home", "WORK": "Work"}  # a Timeline semantic type, its prefixes off, → a name
ONLINE = re.compile(
    r"://|\bzoom\b|\bteams\b|google meet|meet\.google|\bwebex\b|\bskype\b|\bfacetime\b|\bwhereby\b", re.I
)
LIBRARY_LABELS = {"immich": "immich", "apple-photos": "photos"}  # a library asked, as the evidence says it
BLANK = "____"
SHOWN = 3  # evidence lines shown before "… and N more"
HOUSE_NUMBER = re.compile(r"^\d+[a-zA-Z]?(?:[-/]\d+[a-zA-Z]?)?$")  # 12, 12B, 12-14, 12/3
EN_DASH = "\u2013"
NOT_EQUAL = "\u2260"


class ReviewError(ValueError):
    """A number, a name or a place the review cannot act on; nothing was written."""


# -- what the record holds ---------------------------------------------------------------------------------


@dataclass
class Name:
    """One name one source gave a spot: how many of its lines said it (visits, photos, events, or
    for Dawarich stays), and a few of their ids."""

    origin: str  # timeline, photo, calendar, dawarich, library
    source: str  # the lines' `source`
    name: str
    grade: str  # name, address, city or type
    count: int = 0
    lines: list[str] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return 1 if self.grade in COARSE else WEIGHTS[self.origin]

    @property
    def unit(self) -> str:
        return UNITS[self.origin]

    def to_json(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "origin": self.origin,
            "name": self.name,
            "grade": self.grade,
            "count": self.count,
            "unit": self.unit,
            "lines": list(self.lines),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> Name:
        return cls(
            str(data["origin"]),
            str(data["source"]),
            str(data["name"]),
            str(data["grade"]),
            int(data["count"]),
            [str(x) for x in data["lines"]],
        )


@dataclass(frozen=True)
class Observed:
    """One observed place: a cluster of the owner's stays (the module's docstring)."""

    id: str
    lat: float
    lon: float
    visits: int
    nights: int
    hours: float
    first: str
    last: str
    spread_m: float
    place: str | None
    aboard: str | None
    names: list[Name]
    lines: list[str]  # the first stay's first line, the last stay's last line

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "lat": round(self.lat, 6),
            "lon": round(self.lon, 6),
            "visits": self.visits,
            "nights": self.nights,
            "hours": round(self.hours, 2),
            "first": self.first,
            "last": self.last,
            "spread_m": round(self.spread_m, 1),
            "place": self.place,
            "aboard": self.aboard,
            "evidence": [n.to_json() for n in self.names],
            "lines": list(self.lines),
        }

    def _row(self) -> dict[str, Any]:
        """The row of `observed_entities` (`Index.store_observed`) the view reads back as `COLUMNS`:
        the spot's centre is its key, the named place it lies in its entity."""
        return {
            "key_kind": "centre",
            "key_value": self.id.removeprefix("place:"),
            "name": self.names[0].name if self.names else None,
            "entity": self.place,
            "labels": json.dumps([n.to_json() for n in self.names], ensure_ascii=False),
            "first": self.first,
            "last": self.last,
            "count": self.visits,
            "samples": json.dumps(self.lines),
            "lat": self.lat,
            "lon": self.lon,
            "nights": self.nights,
            "hours": self.hours,
            "spread_m": self.spread_m,
            "aboard": self.aboard,
        }

    @classmethod
    def _from_row(cls, row: Sequence[Any]) -> Observed:
        id_, lat, lon, visits, nights, hours, first, last, spread, place, aboard, names, lines = row
        return cls(
            str(id_),
            float(lat),
            float(lon),
            int(visits),
            int(nights),
            float(hours),
            str(first),
            str(last),
            float(spread),
            None if place is None else str(place),
            None if aboard is None else str(aboard),
            [Name.from_json(n) for n in json.loads(names)],
            [str(x) for x in json.loads(lines)],
        )


def observed(lb: Logbook, cluster_m: float = CLUSTER_M) -> list[Observed]:
    """Every observed place of the record, from the index's derived table: served while its stamp
    holds, built from the lines and stored otherwise. Writes nothing to the record. The stamp's head
    is the one the index holds when the reading starts (`Index.indexed`): a table built while a writer
    is between `logbook.json` and the index is stamped with no later head than it read."""
    with lb.index() as idx:
        stamp = _stamp(lb, cluster_m, idx.indexed()[1])
        if _table_current(idx, stamp):
            rows = idx.db.execute(f"SELECT {', '.join(COLUMNS)} FROM {TABLE} ORDER BY rowid").fetchall()
            return [Observed._from_row(row) for row in rows]
    found = build(lb, cluster_m)
    with lb.index() as idx:
        idx.store_observed(OBSERVED_KIND, [o._row() for o in found], stamp)
    return found


def _stamp(lb: Logbook, cluster_m: float, head: str) -> dict[str, str]:
    meta = lb.meta
    return {
        "head": head,
        "timezone": str(meta["timezone"]),
        "version": TABLE_VERSION,
        "cluster_m": repr(float(cluster_m)),
        "places": _digest(places.path_of(lb.root)),
        "assets": _digest(assets.assets_path(lb.root)),
        "settings": _digest(stays.settings_path(lb.root)),
    }


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return ""


def _table_current(idx: Index, stamp: Mapping[str, str]) -> bool:
    """Whether the view is there, of the shape this module reads, and its rows stamped as asked."""
    try:
        columns = {str(row[1]) for row in idx.db.execute(f"PRAGMA table_info({TABLE})")}
    except sqlite3.DatabaseError:
        return False
    return set(COLUMNS) <= columns and idx.observed_stamp(OBSERVED_KIND) == dict(stamp)


def build(lb: Logbook, cluster_m: float = CLUSTER_M) -> list[Observed]:
    """The pure read: the owner's stays of the whole record clustered by spot, each cluster with its
    counts and the names the record holds for it, ranked (nights, then hours, then the first visit).
    The stays and what the lines name are kept beside the index and brought forward (`_kept`)."""
    span = reading.record_days(lb, "location")
    if span is None:
        return []
    whole, facts = _kept(lb, span)
    bounds = day_start.of(lb.meta)
    settings = stays.read_settings(lb.root)
    known = stays.read_places(lb.root, settings.radius_m)
    found = [s for s in whole if s.lat is not None and s.lon is not None]
    groups = cluster(found, cluster_m)
    nights = nights_of(found, day_range(*span), bounds.zone, settings)
    clusters = [_cluster_of(group, nights, known) for group in groups]
    names = _Names(clusters, groups, cluster_m)
    if clusters:
        for group in FACT_GROUPS:
            for fact in facts.get(group, []):
                names.apply(fact)
        names.dawarich(lb)
    out = [replace_names(c, names.of(n)) for n, c in enumerate(clusters)]
    out.sort(key=lambda o: (-o.nights, -o.hours, o.first, o.id))
    return out


# -- kept between readings -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fact:
    """What one line names, before it is put to a cluster: by its point and hour (`by_place`), or by
    its hour alone (`by_time`); an event located too far from the cluster it falls in names nothing."""

    origin: str  # timeline, photo, calendar
    source: str
    line: str
    names: tuple[tuple[str, str], ...]  # (name, grade), in the order they are added
    lat: float | None
    lon: float | None
    start: datetime | None
    end: datetime | None
    near: tuple[float, float] | None = None  # an event's own point

    def to_json(self) -> list[Any]:
        return [
            self.origin, self.source, self.line, [list(n) for n in self.names], self.lat, self.lon,
            None if self.start is None else self.start.isoformat(),
            None if self.end is None else self.end.isoformat(),
            None if self.near is None else list(self.near),
        ]  # fmt: skip

    @classmethod
    def from_json(cls, v: Sequence[Any]) -> _Fact:
        origin, source, line, names, lat, lon, start, end, near = v
        return cls(
            str(origin), str(source), str(line), tuple((str(a), str(b)) for a, b in names), lat, lon,
            None if start is None else datetime.fromisoformat(start),
            None if end is None else datetime.fromisoformat(end),
            None if near is None else (float(near[0]), float(near[1])),
        )  # fmt: skip


def _fact(group: str, line: Line) -> _Fact | None:
    """The names a line gives, as `_Names` puts them to a cluster; None when it gives none."""
    payload = line.get("payload") or {}
    source = str(line.get("source") or "")
    line_id = str(line.get("id"))
    if group == "photo":
        extra = payload.get("extra")
        found = photo_name(extra.get("place") if isinstance(extra, dict) else None)
        at = stays.instant(line.get("at"))
        if found is None or at is None:
            return None
        lat, lon = _coordinates(payload.get("lat"), payload.get("lon"))
        return _Fact("photo", source, line_id, (found,), lat, lon, at, None)
    if group == "event":
        if payload.get("all_day") is not False or payload.get("status") == "cancelled":
            return None
        text = payload.get("location")
        if not _text(text):
            return None
        where = str(text).strip().splitlines()[0].strip()
        start, end = stays.instant(line.get("at")), stays.instant(line.get("end"))
        if not where or ONLINE.search(where) or start is None:
            return None
        extra = payload.get("extra")
        located = extra.get("location") if isinstance(extra, dict) else None
        near = None
        if isinstance(located, dict):
            lat, lon = _coordinates(located.get("latitude"), located.get("longitude"))
            near = None if lat is None or lon is None else (lat, lon)
        return _Fact("calendar", source, line_id, ((where, "name"),), None, None, start, end, near)
    extra = payload.get("extra")
    if not isinstance(extra, dict) or extra.get("edge") != "start":
        return None
    segment = extra.get("segment")
    if segment not in TIMELINE_SEGMENTS.values():
        return None
    lat, lon = _coordinates(payload.get("lat"), payload.get("lon"))
    if lat is None or lon is None:
        return None
    start, end = stays.instant(extra.get("segment_start")), stays.instant(extra.get("segment_end"))
    item = _dict(extra.get(segment))
    names: list[tuple[str, str]] = []
    if segment == "placeVisit":
        visited = _dict(item.get("location"))
        if _text(visited.get("name")):
            names.append((str(visited["name"]), "name"))
        elif _text(visited.get("address")):
            names.append((str(visited["address"]), "address"))
        semantic = visited.get("semanticType")
    else:
        semantic = _dict(item.get("topCandidate")).get("semanticType")
    typed = _semantic(semantic)
    if typed:
        names.append((typed, "type"))
    return _Fact("timeline", source, line_id, tuple(names), lat, lon, start, end) if names else None


def _fact_lines(
    idx: Index, group: str, first: str, last: str, where: str = "", args: Sequence[Any] = ()
) -> Iterator[tuple[str, int, Line]]:
    """(file, offset, line) of every line of `group` whose local day is in [first, last] and matches
    `where`, in file order, standing (not retracted, and a photo or an event not superseded)."""
    if group.startswith("timeline:"):
        cut = "kind = 'location' AND source = ? AND raw_id GLOB ?"
        cut_args: tuple[Any, ...] = (places.TIMELINE_SOURCE, group.removeprefix("timeline:") + "*")
        gone = set(idx.superseded(RETRACTION))
    else:
        cut, cut_args = "kind = ?", (group,)
        gone = set(idx.superseded(RETRACTION)) | set(idx.superseded(group))
    found = idx.db.execute(
        f"SELECT file, offset FROM lines WHERE {cut} AND day_local BETWEEN ? AND ?{where}"
        " ORDER BY file, offset",
        (*cut_args, first, last, *args),
    ).fetchall()
    for (file, offset), line in zip(found, idx.read([(str(f), int(o)) for f, o in found]), strict=True):
        if str(line.get("id")) not in gone:
            yield str(file), int(offset), line


def _kept(lb: Logbook, span: tuple[str, str]) -> tuple[list[stays.Segment], dict[str, list[_Fact]]]:
    """The owner's stays of the whole record and what the lines name, by group in file order: kept
    beside the index (`KEPT_FILE`) and brought forward (`_forward`) while all that came since is that:
    no retraction, no photo or event that supersedes another, no point or evidence on a day before
    the last `MARGIN_DAYS` read, under the same code and settings; read from every line otherwise."""
    first, last = span
    path = kept.path(lb, KEPT_FILE)
    stamp = kept.stamp(lb, str(KEPT_VERSION), kept.code_digest(__file__))
    held = kept.load(path)
    found = None
    ours = held is not None and held.get("version") == KEPT_VERSION and held.get("stamp") == stamp
    if held is not None and ours and held.get("first") == first and str(held.get("last")) <= last:
        found = _forward(lb, held, span)
    if found is None:
        found = _whole(lb, span)
    memo, whole, facts = found
    kept.save(path, {"version": KEPT_VERSION, "stamp": stamp, **memo})
    return whole, facts


def _whole(
    lb: Logbook, span: tuple[str, str]
) -> tuple[dict[str, Any], list[stays.Segment], dict[str, list[_Fact]]]:
    first, last = span
    end = _next_day(last)
    with lb.index() as idx:
        seq, head = idx.indexed()
    whole = reading.owner_track(lb, first, last).stays
    facts: dict[str, list[tuple[str, int, _Fact]]] = {}
    with lb.index() as idx:
        for group in FACT_GROUPS:
            facts[group] = [
                (f, o, fact)
                for f, o, line in _fact_lines(idx, group, first, end, " AND seq <= ?", (seq,))
                if (fact := _fact(group, line)) is not None
            ]
    return (
        _memo(span, seq, head, whole, facts),
        whole,
        {g: [f for _f, _o, f in found] for g, found in facts.items()},
    )


def _memo(
    span: tuple[str, str],
    seq: int,
    head: str,
    whole: Sequence[stays.Segment],
    facts: Mapping[str, Sequence[tuple[str, int, _Fact]]],
) -> dict[str, Any]:
    cut = max(span[0], (date.fromisoformat(span[1]) - timedelta(days=MARGIN_DAYS)).isoformat())
    return {
        "first": span[0],
        "last": span[1],
        "cut": cut,
        "seq": seq,
        "head": head,
        "stays": [_segment_json(s) for s in whole],
        "facts": {g: [[f, o, fact.to_json()] for f, o, fact in found] for g, found in facts.items()},
    }


def _forward(
    lb: Logbook, held: Mapping[str, Any], span: tuple[str, str]
) -> tuple[dict[str, Any], list[stays.Segment], dict[str, list[_Fact]]] | None:
    """The kept stays and names brought to the record as it stands (`_kept`), or None."""
    first, last = span
    since, cut, before = int(held["seq"]), str(held["cut"]), str(held["last"])
    with lb.index() as idx:
        seq, head = idx.indexed()
        if not kept.read_on(idx, held, {}, (RETRACTION,)):
            return None
        appended = idx.appended(since)
        if any(appended.get(kind, ("", 0, 0))[2] for kind in ("photo", "event")):
            return None  # a photo or an event read already, superseded
        if any(appended[k][0] < cut for k in ("location", *stays.EVIDENCE) if k in appended):
            return None  # a point or evidence on a day read whole already
        try:
            kept_stays = [_segment_from(v) for v in held["stays"]]
            kept_facts = {
                g: [(str(f), int(o), _Fact.from_json(v)) for f, o, v in held["facts"][g]] for g in FACT_GROUPS
            }
        except (KeyError, TypeError, ValueError):
            return None
        end, old_end = _next_day(last), _next_day(before)
        facts: dict[str, list[tuple[str, int, _Fact]]] = {}
        for group in FACT_GROUPS:
            new = [
                (f, o, fact)
                for f, o, line in _fact_lines(
                    idx,
                    group,
                    first,
                    end,
                    " AND ((seq > ? AND seq <= ?) OR (seq <= ? AND day_local > ?))",
                    (since, seq, since, old_end),
                )
                if (fact := _fact(group, line)) is not None
            ]
            facts[group] = sorted([*kept_facts[group], *new], key=lambda t: (t[0], t[1]))
    whole = _spliced(lb, kept_stays, first, cut, last)
    if whole is None:
        return None
    return (
        _memo(span, seq, head, whole, facts),
        whole,
        {g: [f for _f, _o, f in found] for g, found in facts.items()},
    )


def _spliced(
    lb: Logbook, kept_stays: Sequence[stays.Segment], first: str, cut: str, last: str
) -> list[stays.Segment] | None:
    """The whole track's stays: the kept ones before the second stay of the track read from far
    enough before `cut` (`LOOKBACK_DAYS`, then twice as far, up to `LOOKBACK_MOST`), and that track's
    from there. The first stay of a track read from a day may be cut short by it; from the second on,
    the stays are the whole record's (`tests/test_places_kept.py`). None past `LOOKBACK_MOST`."""
    begins = day_start.of(lb.meta).span(cut)[0]
    back = LOOKBACK_DAYS
    while True:
        start = max(first, (date.fromisoformat(cut) - timedelta(days=back)).isoformat())
        part = reading.owner_track(lb, start, last).stays
        if start == first:
            return part
        if len(part) >= 2 and part[1].start < begins:
            anchor = part[1].start
            return [s for s in kept_stays if s.start < anchor] + part[1:]
        if back >= LOOKBACK_MOST:
            return None
        back *= 2


def _segment_json(s: stays.Segment) -> dict[str, Any]:
    return {
        **{k: getattr(s, k) for k in SEGMENT_PLAIN},
        "start": s.start.isoformat(),
        "end": s.end.isoformat(),
        "airports": list(s.airports),
        "inside": [_segment_json(i) for i in s.inside],
    }


def _segment_from(v: Mapping[str, Any]) -> stays.Segment:
    return stays.Segment(
        **{k: v[k] for k in SEGMENT_PLAIN},
        start=datetime.fromisoformat(v["start"]),
        end=datetime.fromisoformat(v["end"]),
        airports=tuple(v["airports"]),
        inside=tuple(_segment_from(i) for i in v["inside"]),
    )


def replace_names(o: Observed, names: list[Name]) -> Observed:
    return Observed(
        o.id, o.lat, o.lon, o.visits, o.nights, o.hours, o.first, o.last, o.spread_m, o.place, o.aboard,
        names, o.lines,
    )  # fmt: skip


# -- clustering --------------------------------------------------------------------------------------------


class _Grid:
    """Points in cells a fixed number of metres of latitude tall, for `within` a few cells of one."""

    def __init__(self, cell_m: float):
        self.cell_m = cell_m
        self.step = cell_m / 111_320
        self.cells: dict[tuple[int, int], list[tuple[float, float, int]]] = {}

    def _key(self, lat: float, lon: float) -> tuple[int, int]:
        return math.floor(lat / self.step), math.floor(lon / self.step)

    def add(self, lat: float, lon: float, value: int) -> None:
        self.cells.setdefault(self._key(lat, lon), []).append((lat, lon, value))

    def within(self, lat: float, lon: float, metres: float) -> list[tuple[float, int]]:
        """(distance, value) of every point within `metres`, nearest first. A degree of longitude
        shrinks with the latitude, so the search is wider in cells than it is tall."""
        rows = math.ceil(metres / self.cell_m) + 1
        cols = math.ceil(rows / max(math.cos(math.radians(lat)), 0.01))
        row, col = self._key(lat, lon)
        found = []
        for r in range(row - rows, row + rows + 1):
            for c in range(col - cols, col + cols + 1):
                for plat, plon, value in self.cells.get((r, c), ()):
                    m = places.distance_m(lat, lon, plat, plon)
                    if m <= metres:
                        found.append((m, value))
        found.sort()
        return found


def _weight_s(s: stays.Segment) -> float:
    """A stay's weight: its seconds, a minute at least, so a stay of no length still counts."""
    return max(float(s.duration_s), 60.0)


def cluster(found: Sequence[stays.Segment], cluster_m: float = CLUSTER_M) -> list[list[stays.Segment]]:
    """The stays grouped by spot: in order of length, longest first, each joins the nearest group
    whose anchor (its first stay) lies within `cluster_m`, else starts one. Each group in time order."""
    grid = _Grid(cluster_m)
    groups: list[list[stays.Segment]] = []
    for s in sorted(found, key=lambda s: (-s.duration_s, s.start)):
        assert s.lat is not None and s.lon is not None
        near = grid.within(s.lat, s.lon, cluster_m)
        if near:
            groups[near[0][1]].append(s)
            continue
        grid.add(s.lat, s.lon, len(groups))
        groups.append([s])
    for group in groups:
        group.sort(key=lambda s: s.start)
    return groups


def nights_of(
    found: Sequence[stays.Segment], days: Sequence[str], tz: ZoneInfo, settings: stays.Settings
) -> Counter[str]:
    """stay id → the nights it holds: per day, the stay with the longest overlap of the night window
    when that reaches the stay minimum, a run aboard one asset counting whole and the night going to
    the inner stay that held most of it (`stays.night`, read from the stays alone)."""
    folded = stays.fold(sorted(found, key=lambda s: s.start))
    starts = [s.start for s in folded]
    held: Counter[str] = Counter()
    for day in days:
        start, end = stays.night_window(day, tz, settings)

        def overlap_s(s: stays.Segment, start: datetime = start, end: datetime = end) -> float:
            return (min(s.end, end) - max(s.start, start)).total_seconds()

        best, best_overlap = None, 0.0
        i = max(bisect_right(starts, start) - 1, 0)
        while i < len(folded) and folded[i].start < end:
            if folded[i].kind == stays.STAY and (overlap := overlap_s(folded[i])) > best_overlap:
                best, best_overlap = folded[i], overlap
            i += 1
        if best is None or best_overlap < settings.stay_min_s:
            continue
        inner = max(best.inside, key=overlap_s) if best.inside else best
        held[inner.id] += 1
    return held


def _cluster_of(group: Sequence[stays.Segment], nights: Counter[str], known: Sequence[Place]) -> Observed:
    total = sum(_weight_s(s) for s in group)
    lat = sum((s.lat or 0.0) * _weight_s(s) for s in group) / total
    lon = sum((s.lon or 0.0) * _weight_s(s) for s in group) / total
    return Observed(
        id=f"place:{lat:.4f},{lon:.4f}",
        lat=lat,
        lon=lon,
        visits=len(group),
        nights=sum(nights.get(s.id, 0) for s in group),
        hours=sum(s.duration_s for s in group) / 3600,
        first=stays.instant_text(group[0].start),
        last=stays.instant_text(max(s.end for s in group)),
        spread_m=_spread(group, lat, lon),
        place=_majority(group, lambda s: s.place) or _holding(lat, lon, known),
        aboard=_majority(group, lambda s: s.aboard),
        names=[],
        lines=[x for x in (group[0].first_line, group[-1].last_line) if x],
    )


def _spread(group: Sequence[stays.Segment], lat: float, lon: float) -> float:
    pairs = sorted((places.distance_m(lat, lon, s.lat or 0.0, s.lon or 0.0), _weight_s(s)) for s in group)
    total = sum(w for _m, w in pairs)
    held = 0.0
    for m, w in pairs:
        held += w
        if held >= SPREAD_SHARE * total:
            return m
    return pairs[-1][0]


def _majority(group: Sequence[stays.Segment], key: Any) -> str | None:
    """The value of `key` most of the group's hours carry, when that is half of them or more."""
    hours: dict[str, float] = {}
    for s in group:
        if (value := key(s)) is not None:
            hours[value] = hours.get(value, 0.0) + _weight_s(s)
    if not hours:
        return None
    value, held = max(hours.items(), key=lambda kv: (kv[1], kv[0]))
    return value if held * 2 >= sum(_weight_s(s) for s in group) else None


def _holding(lat: float, lon: float, known: Iterable[Place]) -> str | None:
    """The named place whose radius holds the point (the nearest of them), else None."""
    best: tuple[float, str] | None = None
    for p in known:
        m = places.distance_m(lat, lon, p.lat, p.lon)
        if m <= p.radius_m and (best is None or m < best[0]):
            best = (m, p.name)
    return None if best is None else best[1]


# -- the names ---------------------------------------------------------------------------------------------


class _Names:
    """The names the record holds, gathered per cluster (the module's docstring)."""

    def __init__(
        self, clusters: Sequence[Observed], groups: Sequence[Sequence[stays.Segment]], cluster_m: float
    ):
        self.clusters = clusters
        self.grid = _Grid(cluster_m)
        for n, c in enumerate(clusters):
            self.grid.add(c.lat, c.lon, n)
        self.stays = sorted((s for group in groups for s in group), key=lambda s: s.start)
        self.starts = [s.start for s in self.stays]
        self.cluster_of = {s.id: n for n, group in enumerate(groups) for s in group}
        self.found: dict[int, dict[tuple[str, str, str, str], Name]] = {}
        self.counted: set[tuple[int, str, str, str]] = set()  # (cluster, stay, name, origin) once each

    def of(self, n: int) -> list[Name]:
        return ranked(self.found.get(n, {}).values())

    def add(self, n: int | None, origin: str, source: str, name: str, grade: str, line: Line) -> None:
        if n is None or not name.strip():
            return
        name = " ".join(name.split())
        entry = self.found.setdefault(n, {}).setdefault(
            (origin, source, name.casefold(), grade), Name(origin, source, name, grade)
        )
        entry.count += 1
        if len(entry.lines) < SAMPLES:
            entry.lines.append(str(line.get("id")))

    # -- where a line falls --

    def overlapping(self, start: datetime, end: datetime) -> list[tuple[float, stays.Segment]]:
        """(seconds of overlap, stay) for every stay overlapping [start, end]; for an instant, the
        stay that holds it."""
        out = []
        i = max(bisect_right(self.starts, start) - 1, 0)
        while i < len(self.stays) and self.stays[i].start <= end:
            s = self.stays[i]
            if s.start <= end and s.end >= start:
                out.append(((min(s.end, end) - max(s.start, start)).total_seconds(), s))
            i += 1
        return out

    def by_place(self, lat: float, lon: float, start: datetime | None, end: datetime | None) -> int | None:
        """The cluster nearest a named point within `MATCH_M`, one with a stay at that hour first."""
        near = self.grid.within(lat, lon, MATCH_M)
        if not near:
            return None
        if start is not None:
            busy = {self.cluster_of[s.id] for _o, s in self.overlapping(start, end or start)}
            for _m, n in near:
                if n in busy:
                    return n
        return near[0][1]

    def by_time(self, start: datetime, end: datetime | None) -> stays.Segment | None:
        """The stay a line without coordinates falls in: the one holding its instant, or for a span
        the one it overlaps for half its length or more."""
        if end is None or end <= start:
            held = [s for _o, s in self.overlapping(start, start)]
            return held[0] if held else None
        found = self.overlapping(start, end)
        if not found:
            return None
        overlap, s = max(found, key=lambda pair: pair[0])
        return s if overlap * 2 >= (end - start).total_seconds() else None

    # -- the sources --

    def apply(self, fact: _Fact) -> None:
        """What one line names, put to the cluster it falls in (`_fact`)."""
        if fact.origin == "calendar":
            assert fact.start is not None
            stay = self.by_time(fact.start, fact.end)
            if stay is None:
                return
            n: int | None = self.cluster_of[stay.id]
            if fact.near is not None:
                c = self.clusters[self.cluster_of[stay.id]]
                if places.distance_m(fact.near[0], fact.near[1], c.lat, c.lon) > EVENT_NEAR_M:
                    return
        elif fact.lat is not None and fact.lon is not None:  # a photo's instant, a visit's span
            n = self.by_place(
                fact.lat, fact.lon, fact.start, fact.start if fact.origin == "photo" else fact.end
            )
        else:  # a photo without coordinates: the stay its instant falls in
            assert fact.start is not None
            stay = self.by_time(fact.start, None)
            n = None if stay is None else self.cluster_of[stay.id]
        for name, grade in fact.names:
            self.add(n, fact.origin, fact.source, name, grade, {"id": fact.line})

    def dawarich(self, lb: Logbook) -> None:
        """The names Dawarich gave the first and last point of a stay (`_dawarich`)."""
        edges = {seq: s for s in self.stays for seq in (s.first_seq, s.last_seq) if seq is not None}
        with lb.index() as idx:
            retracted = set(idx.superseded(RETRACTION))
            wanted = sorted(edges)
            theirs: list[int] = []
            for n in range(0, len(wanted), 500):
                chunk = wanted[n : n + 500]
                theirs += [
                    int(seq)
                    for (seq,) in idx.db.execute(
                        f"SELECT seq FROM lines WHERE seq IN ({', '.join('?' * len(chunk))})"
                        " AND source = 'dawarich'",
                        chunk,
                    )
                ]
            for seq, line in sorted(idx.by_seqs(theirs).items()):
                if str(line.get("id")) not in retracted:
                    self._dawarich(line, edges[seq])

    def _dawarich(self, line: Line, stay: stays.Segment) -> None:
        extra = (line.get("payload") or {}).get("extra")
        place = extra.get("place") if isinstance(extra, dict) else None
        if not isinstance(place, dict):
            return
        if _text(place.get("name")):
            name, grade = str(place["name"]), "name"
        elif _text(place.get("street")):
            name = " ".join(str(place[k]).strip() for k in ("street", "housenumber") if _text(place.get(k)))
            grade = "address"
        else:
            return
        n = self.cluster_of.get(stay.id)
        key = (n if n is not None else -1, stay.id, name.casefold(), "dawarich")
        if key in self.counted:
            return
        self.counted.add(key)
        self.add(n, "dawarich", "dawarich", name, grade, line)


def ranked(names: Iterable[Name]) -> list[Name]:
    """Names weightiest first (`Name.weight` a line), then by origin, then by name and source."""
    return sorted(
        names, key=lambda x: (-x.weight * x.count, ORIGINS.index(x.origin), x.name.casefold(), x.source)
    )


def photo_name(place: object) -> tuple[str, str] | None:
    """(name, grade) of the place a photo's library named (`extra.place`): `name`, else the first of
    `names` (the areas Photos put it in), else `address`, else `city` (all Immich has); None for
    anything that names nothing."""
    if not isinstance(place, dict):
        return None
    names = place.get("names")
    first_name = names[0] if isinstance(names, list) and names else None
    return next(
        (
            (str(value), grade)
            for value, grade in (
                (place.get("name"), "name"),
                (first_name, "name"),
                (place.get("address"), "address"),
                (place.get("city"), "city"),
            )
            if _text(value)
        ),
        None,
    )


def _semantic(value: object) -> str | None:
    """`TYPE_HOME`, `INFERRED_HOME`, `HOME`, `Home` → `Home`; work alike; anything else None."""
    if not isinstance(value, str):
        return None
    bare = value.strip().upper().removeprefix("TYPE_").removeprefix("INFERRED_")
    return TYPES.get(bare)


def _coordinates(lat: object, lon: object) -> tuple[float | None, float | None]:
    ok = all(isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon))
    if not ok:
        return None, None
    assert isinstance(lat, int | float) and isinstance(lon, int | float)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None, None
    return float(lat), float(lon)


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _next_day(day: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


# -- the queue ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    number: int
    observed: Observed
    name: str | None  # None: no source names the spot, or every name it has is taken or rejected
    radius_m: float  # what accepting it would write, against the named places as they stand
    nearest: tuple[Place, float] | None

    @property
    def id(self) -> str:
        return self.observed.id

    @property
    def lat(self) -> float:
        return self.observed.lat

    @property
    def lon(self) -> float:
        return self.observed.lon

    def to_json(self) -> dict[str, Any]:
        out = {"number": self.number, **self.observed.to_json(), "name": self.name, "radius_m": self.radius_m}
        out["nearest"] = (
            None
            if self.nearest is None
            else {
                "name": self.nearest[0].name,
                "kind": self.nearest[0].kind,
                "metres": round(self.nearest[1]),
            }
        )
        return out


@dataclass(frozen=True)
class Report:
    observed: list[Observed]
    proposals: list[Proposal]
    named: int  # observed places at a named place
    held_back: int  # observed places at no named place whose blank was rejected
    places: list[Place]
    tz: ZoneInfo
    cluster_m: float
    head: str

    def to_json(self, shown: Sequence[Proposal] | None = None) -> dict[str, Any]:
        return {
            "observed": len(self.observed),
            "named": self.named,
            "held_back": self.held_back,
            "radius_m": _number(self.cluster_m),
            "head": self.head,
            "proposals": [p.to_json() for p in (self.proposals if shown is None else shown)],
        }


def read(lb: Logbook, cluster_m: float = CLUSTER_M) -> Report:
    """The queue of the record as it stands: the observed places through the index's table, the
    named places and the rejections as they are now. Writes nothing to the record."""
    if not cluster_m > 0:
        raise ReviewError(f"--radius must be a positive number of metres, not {cluster_m:g}")
    tz = ZoneInfo(str(lb.meta["timezone"]))
    found = observed(lb, cluster_m)
    known = stays.read_places(lb.root, stays.read_settings(lb.root).radius_m)
    taken = {p.name.casefold() for p in known}
    rejected = rejections(lb)
    proposals: list[Proposal] = []
    named = held_back = 0
    for o in found:
        if o.place is not None:
            named += 1
            continue
        refused = refused_at(rejected, o.lat, o.lon, cluster_m)
        name = choose(o.names, taken, refused)
        if name is None and None in refused:
            held_back += 1
            continue
        proposals.append(
            Proposal(
                len(proposals) + 1,
                o,
                name,
                fit_radius(o.spread_m, o.lat, o.lon, known),
                places.nearest(o.lat, o.lon, known),
            )
        )
    return Report(found, proposals, named, held_back, known, tz, cluster_m, str(lb.meta["head"]))


def refused_at(rejected: Iterable[Rejection], lat: float, lon: float, cluster_m: float) -> set[str | None]:
    """The names (None for the blank) the owner rejected for the spot at lat, lon."""
    return {r.name for r in rejected if places.distance_m(lat, lon, r.lat, r.lon) <= cluster_m}


def choose(names: Sequence[Name], taken: set[str], refused: set[str | None]) -> str | None:
    """The name the evidence weighs most (`Name.weight` a line), a name taken or refused passed
    over; spelled as its weightiest source spelt it. None when there is none left."""
    score: Counter[str] = Counter()
    spelling: dict[str, str] = {}
    for n in names:  # weightiest first (`_Names.of`)
        key = n.name.casefold()
        score[key] += n.weight * n.count
        spelling.setdefault(key, n.name)
    refused_keys = {r.casefold() for r in refused if r is not None}
    for key, _score in sorted(score.items(), key=lambda kv: (-kv[1], kv[0])):
        if key not in taken and key not in refused_keys:
            return spelling[key]
    return None


def fit_radius(spread_m: float, lat: float, lon: float, known: Iterable[Place]) -> float:
    """The radius a place accepted here gets (the module's docstring): the spread and 75 m, up to
    5 m, between 75 and 300 m; drawn back to the edge of any named place it would reach into, to the
    whole metre, never below 50 m."""
    radius = math.ceil((spread_m + FIT_MARGIN_M) / FIT_STEP_M) * FIT_STEP_M
    radius = min(max(radius, FIT_MIN_M), FIT_MAX_M)
    for p in known:
        room = places.distance_m(lat, lon, p.lat, p.lon) - p.radius_m
        if room < radius:
            radius = max(float(math.floor(room)), FIT_FLOOR_M)
    return float(radius)


def near(report: Report, where: str) -> list[Proposal]:
    """The proposals within `NEAR_KM` of a named place (case aside) or of `lat,lon`, in queue order."""
    named = next((p for p in report.places if p.name.casefold() == where.strip().casefold()), None)
    if named is not None:
        lat, lon = named.lat, named.lon
    else:
        try:
            lat, lon = places.parse_stay_id(where)
        except ValueError as e:
            known = ", ".join(p.name for p in report.places) or "none"
            raise ReviewError(
                f"--near: {where!r} is neither a named place (places: {known}) nor lat,lon"
            ) from e
    return [p for p in report.proposals if places.distance_m(lat, lon, p.lat, p.lon) <= NEAR_KM * 1000]


def numbers(text: Sequence[str] | None) -> list[int]:
    """`N[,N]`, given once or more, to the numbers in order, each once; `ReviewError` on a word
    that is not a number from 1."""
    found: list[int] = []
    for piece in text or ():
        for word in piece.split(","):
            word = word.strip()
            if not word:
                continue
            if not word.isdigit() or int(word) < 1:
                raise ReviewError(
                    f"not a proposal number: {word!r}; `places review` lists them, numbered from 1"
                )
            if int(word) not in found:
                found.append(int(word))
    return found


def pick(report: Report, wanted: Sequence[int]) -> list[Proposal]:
    """The proposals these numbers name; `ReviewError` on one the queue does not have."""
    by_number = {p.number: p for p in report.proposals}
    missing = [n for n in wanted if n not in by_number]
    if missing:
        have = _plural(len(report.proposals), "proposal")
        raise ReviewError(
            f"no proposal {', '.join(map(str, missing))}; the queue has {have}, `places review` lists them"
        )
    return [by_number[n] for n in wanted]


# -- the owner's say ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Written:
    proposal: Proposal
    verdict: str  # `accepted` or `rejected`
    name: str | None
    place: Place | None = None
    line: Line | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.proposal.number,
            "id": self.proposal.id,
            "verdict": self.verdict,
            "name": self.name,
            "place": None if self.place is None else {"name": self.place.name, **self.place.to_json()},
            "line": None if self.line is None else str(self.line["id"]),
        }


def accept(lb: Logbook, chosen: Sequence[tuple[Proposal, str | None]]) -> list[Written]:
    """Each proposal accepted, with its own name or the one given: a place at the cluster's centre
    with its fitted radius, against the named places as they stand now (one accepted earlier in the
    batch among them), and the naming in the record (`places.name`). Every one is checked before
    the first is written."""
    known = places.read(lb.root, stays.read_settings(lb.root).radius_m)
    plans: list[tuple[Proposal, Place]] = []
    for p, given in chosen:
        name = " ".join((given if given is not None else p.name or "").split())
        if not name:
            raise ReviewError(f'proposal {p.number} has no name; give it one: --name {p.number} "…"')
        taken = next((q.name for q in known if q.name.casefold() == name.casefold()), None)
        if taken is not None:
            raise ReviewError(
                f'{taken!r} is already a place; give proposal {p.number} another: --name {p.number} "…"'
            )
        holder = _holding(p.lat, p.lon, known)
        if holder is not None:
            raise ReviewError(f"proposal {p.number} lies inside {holder!r} already")
        place = Place(
            name, round(p.lat, 6), round(p.lon, 6), fit_radius(p.observed.spread_m, p.lat, p.lon, known)
        )
        plans.append((p, place.check()))
        known.append(place)
    written = []
    for p, place in plans:
        line = places.name(lb, place)
        written.append(Written(p, "accepted", place.name, place, line))
    return written


@dataclass(frozen=True)
class Rejection:
    lat: float
    lon: float
    name: str | None


def centre(lat: float, lon: float) -> str:
    """A spot's `centre` ref value, `lat,lon` to six decimals, as the state file kept the pair."""
    return f"{lat:.6f},{lon:.6f}"


def reject(lb: Logbook, proposals: Sequence[Proposal]) -> list[Written]:
    """Each proposal rejected: one `entity-review/v1` line of type place through `Logbook.append` —
    the spot's centre and the name proposed, or the blank, citing the stays' lines, at the highest
    of their tiers and never under 2 — under one hold of the writer lock, so the pair is never
    proposed again; then the cache in `state/places-review.json` is rebuilt from the lines."""
    at = now_utc()
    written = []
    with lb.writer():
        head = str(lb.meta["head"])
        with lb.index() as idx:
            tiers = {
                line_id: int(line.get("tier", 0))
                for line_id, line in idx.by_ids(i for p in proposals for i in p.observed.lines).items()
            }
        for p in proposals:
            evidence = list(p.observed.lines)
            cited = [tiers[i] for i in evidence if i in tiers]
            line = _no(lb, at, head, p.lat, p.lon, p.name, evidence, {"review": p.id}, cited)
            written.append(Written(p, "rejected", p.name, line=line))
    rejections(lb)
    return written


def _write_state(path: Path, state: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes((json.dumps(state, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    os.replace(temporary, path)


def _no(
    lb: Logbook,
    at: str,
    head: str,
    lat: float,
    lon: float,
    name: str | None,
    evidence: list[str],
    extra: dict[str, Any],
    cited: Iterable[int] = (),
) -> Line:
    """One `entity-review/v1` line of type place: `cited` the tiers of the `evidence` lines the record
    has, so the line's tier is the highest of them and never under 2 (`entities.review_tier`)."""
    payload = entities.review_payload(
        entities.PLACE,
        ("centre", centre(lat, lon)),
        label=name,
        evidence=evidence,
        head=head,
        raw_id=f"review:{entities.DIFFERENT}:place:{centre(lat, lon)}:{name or ''}",
        extra=extra,
    )
    problems = entities.validate_entity_review(payload)
    if problems:
        raise ReviewError(problems[0])
    return lb.append(
        at=at,
        source=entities.SOURCE,
        kind=entities.ENTITY_REVIEW,
        tier=entities.review_tier(cited),
        payload=payload,
    )


def state_path(root: Path) -> Path:
    return Path(root).joinpath(*STATE_FILE.parts)


def _state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"rejected": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise ReviewError(f"{path} is not JSON: {e}") from e
    rows = data.get("rejected") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ReviewError(f'{path} must be {{"rejected": [{{"lat", "lon", "name"}}, ...]}}')
    return {**data, "rejected": rows}


def _pair(row: object) -> tuple[str, str | None] | None:
    """(centre, the name casefolded, or None for the blank) of one state row; None when it is not one."""
    if not isinstance(row, dict):
        return None
    lat, lon = _coordinates(row.get("lat"), row.get("lon"))
    name = row.get("name")
    if lat is None or lon is None or not (name is None or isinstance(name, str)):
        return None
    return centre(lat, lon), None if name is None else name.casefold()


def _lines_rows(lb: Logbook) -> list[dict[str, Any]]:
    """The standing place noes of the record, as rows of the state file, each naming its line."""
    with lb.index() as idx:
        noes = entities.reviews([*idx.retractions(), *idx.by_kind(entities.ENTITY_REVIEW)])
    rows = []
    for no in noes:
        if no.kind != entities.PLACE or no.ref[0] != "centre" or no.entity is not None:
            continue
        try:
            lat, lon = (float(x) for x in no.ref[1].split(","))
        except ValueError:
            continue
        rows.append(
            {"lat": lat, "lon": lon, "name": no.label, "id": f"place:{lat:.4f},{lon:.4f}",
             "rejected_at": no.at, "line": no.line}
        )  # fmt: skip
    return rows


def legacy(root: Path) -> list[dict[str, Any]]:
    """The rows of `state/places-review.json` that are no line yet: written there before 0.7."""
    return [
        row for row in _state(state_path(root))["rejected"] if isinstance(row, dict) and "line" not in row
    ]


def rejections(lb: Logbook) -> list[Rejection]:
    """The pairs the owner rejected: the cache when it was rebuilt at this head, else rebuilt now
    from the standing `entity-review/v1` lines of type place and the rows from before 0.7 that no
    line holds yet. The file is written only when it exists or has something to hold."""
    path = state_path(lb.root)
    state = _state(path)
    head = str(lb.meta["head"])
    if state.get("head") != head:
        rows = _lines_rows(lb)
        held = {_pair(row) for row in rows}
        rows = [row for row in state["rejected"] if isinstance(row, dict) and "line" not in row
                and _pair(row) not in held] + rows  # fmt: skip
        if path.exists() or rows:
            _write_state(path, {**state, "head": head, "rejected": rows})
    return _rejected(lb.root)


def _rejected(root: Path) -> list[Rejection]:
    """The pairs the cache holds (`rejections` keeps it current; `places_photos` reads it after it)."""
    found = []
    for row in _state(state_path(root))["rejected"]:
        if not isinstance(row, dict):
            continue
        lat, lon = _coordinates(row.get("lat"), row.get("lon"))
        name = row.get("name")
        if lat is not None and lon is not None and (name is None or isinstance(name, str)):
            found.append(Rejection(lat, lon, name))
    return found


@dataclass(frozen=True)
class Migrated:
    written: list[Line]
    already: int  # rows a standing line holds already
    skipped: int  # rows that are not a pair

    def to_json(self) -> dict[str, Any]:
        return {
            "written": [str(line["id"]) for line in self.written],
            "already": self.already,
            "skipped": self.skipped,
        }


def migrate_rejects(lb: Logbook) -> Migrated:
    """`places review --migrate-rejects`: every no `state/places-review.json` holds from before
    0.7 written once as an `entity-review/v1` line of type place, at the moment it was said
    (`rejected_at`), under one hold of the writer lock; a pair a standing line holds already is
    passed over, so a second run writes nothing. Then the file is rebuilt from the lines."""
    written: list[Line] = []
    already = skipped = 0
    with lb.writer():
        held = {_pair(row) for row in _lines_rows(lb)}
        head = str(lb.meta["head"])
        for row in legacy(lb.root):
            pair = _pair(row)
            if pair is None:
                skipped += 1
                continue
            if pair in held:
                already += 1
                continue
            held.add(pair)
            lat, lon = _coordinates(row.get("lat"), row.get("lon"))
            assert lat is not None and lon is not None
            said = row.get("rejected_at")
            at = said if isinstance(said, str) and stays.instant(said) is not None else now_utc()
            extra = {
                "migrated_from": MIGRATED_FROM,
                "review": str(row.get("id") or f"place:{lat:.4f},{lon:.4f}"),
            }
            written.append(_no(lb, at, head, lat, lon, row.get("name"), [], extra))
        rejections(lb)
    return Migrated(written, already, skipped)


# -- the evidence, folded ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Group:
    """One line of evidence: a name one source gave the spot, or the addresses one source wrote
    along one street, folded (`addresses` is how many; `count` their lines, as for a name). Two
    renderings share it: the CLI's text (`group_text`) and the Places page of `logbook serve`."""

    origin: str
    source: str
    name: str  # the name, or the street
    grade: str
    count: int
    unit: str
    addresses: int = 0  # 0 for a name; for a street, the addresses folded into it (two or more)
    names: tuple[Name, ...] = ()

    @property
    def score(self) -> int:
        return sum(n.weight * n.count for n in self.names)


def street_of(address: str) -> str | None:
    """The street of an address with a house number — `Plattformveien 12`, `12B Bøyeveien,
    Nordsjøen`, `Plattformveien 12-14` — the part before the first comma with the number
    taken out; None when there is no number (nothing to fold) or nothing else."""
    first = address.split(",")[0].strip()
    words = first.split()
    kept = [w for w in words if not HOUSE_NUMBER.match(w)]
    if len(kept) == len(words) or not kept:
        return None
    return " ".join(kept)


def groups(names: Sequence[Name]) -> list[Group]:
    """The evidence folded: every address-grade name with a house number joins the group of its
    street (per source), and a street with two addresses or more is one line; every other name
    is a line of its own. Ordered as the names are: by weight, then origin, then name."""
    streets: dict[tuple[str, str, str], list[Name]] = {}
    out: list[Group] = []
    for n in names:
        street = street_of(n.name) if n.grade == "address" else None
        if street is None:
            out.append(Group(n.origin, n.source, n.name, n.grade, n.count, n.unit, 0, (n,)))
            continue
        streets.setdefault((n.origin, n.source, street.casefold()), []).append(n)
    for (origin, source, _key), members in streets.items():
        if len(members) == 1:
            n = members[0]
            out.append(Group(n.origin, n.source, n.name, n.grade, n.count, n.unit, 0, (n,)))
            continue
        street = street_of(members[0].name) or members[0].name
        count = sum(n.count for n in members)
        out.append(
            Group(origin, source, street, "address", count, members[0].unit, len(members), tuple(members))
        )
    out.sort(key=lambda g: (-g.score, ORIGINS.index(g.origin), g.name.casefold(), g.source))  # as `ranked`
    return out


def group_text(g: Group) -> str:
    """`google-takeout timeline: "Hytta" (3 visits)`, `immich: "Nordsjøen" (1 photo, city)`, for a
    street `dawarich: "Plattformveien" (38 addresses, 217 stays)`, and for a library asked
    (`places_photos`) `immich ×12: Havbyen`, `photos ×3: Plattformen`. The one rendering: the CLI
    prints these lines and the Places page of `logbook serve` lists them."""
    if g.origin == "library":  # asked now (`places_photos`), not read from a line
        label = LIBRARY_LABELS.get(g.source, g.source)
        folded = f" ({_plural(g.addresses, 'address', 'addresses')})" if g.addresses else ""
        return f"{label} ×{g.count}: {g.name}{folded}"
    who = f"{g.source} timeline" if g.origin == "timeline" else g.source
    if g.addresses:
        return (
            f'{who}: "{g.name}" ({_plural(g.addresses, "address", "addresses")}, {_plural(g.count, g.unit)})'
        )
    grade = "" if g.grade == "name" else f", {g.grade}"
    return f'{who}: "{g.name}" ({_plural(g.count, g.unit)}{grade})'


def evidence_lines(names: Sequence[Name], verbose: bool = False) -> list[str]:
    """One line per group, folded and ordered (`groups`); with `verbose`, one per name."""
    if verbose:
        return [
            group_text(Group(n.origin, n.source, n.name, n.grade, n.count, n.unit, 0, (n,))) for n in names
        ]
    return [group_text(g) for g in groups(names)]


# -- text --------------------------------------------------------------------------------------------------


def rows(report: Report, shown: Sequence[Proposal], verbose: bool = False) -> Iterator[str]:
    """The queue: a head, then per proposal one line with the spot, its counts and the name proposed
    (a blank where no source knows one), and one with the evidence, folded unless `verbose`; then
    what to do."""
    yield head(report)
    if not report.observed:
        return
    if not shown:
        yield "nothing to review here"
        return
    width = len(str(max(p.number for p in shown)))
    for p in shown:
        yield f"  {p.number:>{width}}  {summary(p, report.tz)} → {p.name or BLANK}"
        yield f"  {' ' * width}      {evidence_text(p.observed.names, verbose)}"
    yield 'nothing written: `setup places review --accept N[,N]`, `--name N "…"`, or `--reject N[,N]`'


def head(report: Report) -> str:
    if not report.observed:
        return "no places observed: the record has no stays yet"
    text = f"{_plural(len(report.observed), 'place')} observed · {report.named} named"
    text += f" · {len(report.proposals)} to review, by nights then hours"
    if report.held_back:
        text += f" · {report.held_back} held back"
    return text


def summary(p: Proposal, tz: ZoneInfo) -> str:
    o = p.observed
    first = (stays.instant(o.first) or datetime.min).astimezone(tz).date().isoformat()
    last = (stays.instant(o.last) or datetime.min).astimezone(tz).date().isoformat()
    parts = [
        f"{o.lat:.4f},{o.lon:.4f}",
        _plural(o.visits, "visit"),
        _plural(o.nights, "night"),
        f"{o.hours:.1f} h",
        f"{first} {EN_DASH} {last}",
    ]
    if o.aboard:
        parts.append(f"aboard {o.aboard}")
    if p.nearest is not None and p.nearest[1] <= NEAR_KM * 1000:
        parts.append(f"{_distance(p.nearest[1])} from {p.nearest[0].name}")
    return " · ".join(parts)


def evidence_text(names: Sequence[Name], verbose: bool = False) -> str:
    """The evidence on one line: the first `SHOWN` folded lines and how many more; with `verbose`
    every name, as before the folding."""
    if not names:
        return "no source names it"
    lines = evidence_lines(names, verbose)
    if verbose or len(lines) <= SHOWN:
        return " · ".join(lines)
    return " · ".join([*lines[:SHOWN], f"… and {len(lines) - SHOWN} more"])


def written_rows(written: Iterable[Written]) -> Iterator[str]:
    for w in written:
        if w.verdict == "accepted" and w.place is not None:
            seq = f" (#{w.line['seq']})" if w.line is not None else ""
            yield (
                f"accepted {w.proposal.number} → {w.place.name}: {w.place.lat:.6f},{w.place.lon:.6f},"
                f" {_number(w.place.radius_m)} m{seq}"
            )
        else:
            name = w.name or BLANK
            yield f"rejected {w.proposal.number} {NOT_EQUAL} {name}: not proposed for this spot again"


def _distance(metres: float) -> str:
    return f"{metres:.0f} m" if metres < 1000 else f"{metres / 1000:.1f} km"


def _number(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {plural or noun + 's'}"
