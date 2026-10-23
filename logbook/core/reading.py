"""One reading of the record over a window of local days, for every reader that derives from it.

`read(lb, first, last)` loads the window's lines through the index (from the first day's start, its
local midnight unless `day_start` says otherwise (RFC 0036), to the end of the last day or of the
night after it, whichever is later, so the last night is inside it), the
settings, places and assets of the record, derives the stays (`stays.derive`) and the night of
each day, resolves the names of the record's refs (`resolve`) and the owner's own identities
(`present.owner_of`). Readers — `rollup`, `trips`, the pages — take a `Reading` and compute; none
of them writes. A reading is a function of the record at one head: the same record, the same
reading.

`owner_track(lb, first, last)` is the narrow reading `places propose` takes: the owner's stays of
the same window, clustered from what the index serves without a line read from the files — the
owner's points and the registered assets' (`Index.locations`), the evidence that promotes a stay
(`Index.evidence`), the retracted ids (`Index.superseded`) — so two years of a record of millions
of lines are read in seconds. The only lines read whole are the Google Timeline visits, found
through the index by their `raw_id`, and the events of a source that is not a calendar
(`Index.of_kind`, one source at a time): whether such an event promotes depends on what its payload
carries (`stays.somewhere`), which the index's columns do not hold. A calendar's entries promote
whatever they carry and are never read. The same window and the same rules as `read`, so the stays
are the same stays.

`read(..., tiers=(1,))` is the same reading through a gate (ADR 0016): only the lines whose tier is
in `tiers` are in it, so every stay, night, trip, companion and count a reader derives from it comes
from lines that cross, and a line held back is not a row, not a night and not a name. The
resolution lines are read whole either way: they are the record's name overlay (a `ref` to an entity),
never a row of their own, and the gate is on the line that puts someone somewhere, as the vault and
a crossing apply it. The retractions too: a hidden line stays hidden. `crossing(lines, tiers)` is
the same gate for the lines a reader takes beside the reading (health, stories)."""

from __future__ import annotations

import functools
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import assets, attribution, day_start, places, policy, present, resolve, stays
from .chain import Line
from .day_start import DayStart
from .export import day_range
from .flights import Airports
from .index import EvidenceRow, Index, LocationRow
from .places import TimelineVisit
from .store import RETRACTION, Logbook, retractions

EVENT = "event"  # the one evidence kind whose lines are read whole (`stays.somewhere`)
fromisoformat = (
    datetime.fromisoformat
)  # a bound method, looked up once for a comprehension over a million rows


@dataclass(frozen=True)
class Reading:
    lb: Logbook
    tz: ZoneInfo
    first: str  # local days, inclusive
    last: str
    days: list[str]
    lines: list[Line]  # the window's lines standing (retracted ones out), retractions aside, in chain order
    settings: stays.Settings
    places: list[places.Place]
    assets: dict[str, assets.Asset]
    derived: stays.Derived
    nights: list[stays.Night]
    names: dict[resolve.Ref, str]
    identities: dict[resolve.Ref, resolve.Identity]
    airports: Airports
    day_start: DayStart  # the record's zone and where its day begins (RFC 0036)
    owner: present.Owner = field(default_factory=lambda: present.Owner(frozenset(), frozenset(), frozenset()))
    retracted: dict[str, Line] = field(default_factory=dict)
    tiers: tuple[int, ...] | None = None  # the gate the reading was read through; None is every tier
    # the gate a voice's name is held to (RFC 0038 §3.4) when it is not `tiers`: an export that reads
    # the record whole and gates line by line (the vault, a trip bundle) sets it to the tiers it sends
    voice_tiers: tuple[int, ...] | None = None
    # the night after the last day when it is not the last day's own (a day that begins at or after the
    # night's start, RFC 0036): not one of `nights`, which are the window's days', and empty at midnight
    nights_after: list[stays.Night] = field(default_factory=list)
    points: list[stays.Point] | None = None  # read from the index (`read(kinds=)`): every subject's points

    @property
    def voice_gate(self) -> tuple[int, ...] | None:
        """The tiers a voice's name is shown through: `voice_tiers` when set, else the reading's gate."""
        return self.tiers if self.voice_tiers is None else self.voice_tiers

    @property
    def owner_stays(self) -> list[stays.Segment]:
        return [s for s in self.derived.segments if s.subject is None and s.kind == stays.STAY]

    @property
    def segments(self) -> list[stays.Segment]:
        return self.derived.segments

    def night_of(self, day: str) -> stays.Night | None:
        """The night whose window starts on `day` (`stays.night_window`)."""
        return next((n for n in (*self.nights, *self.nights_after) if n.day == day), None)

    def night_after(self, day: str) -> stays.Night | None:
        """The night that follows `day` under the record's `day_start`: the night of `day` unless the
        day begins at or after the night's start (`day_start.DayStart.night_after`)."""
        return self.night_of(self.day_start.night_after(day, self.settings.night[0]))

    def night_before(self, day: str) -> stays.Night | None:
        return self.night_of(self.day_start.night_before(day, self.settings.night[0]))

    def day_of(self, line: Line) -> str:
        """The local day of a line under the record's `day_start`."""
        return self.day_start.day_of(str(line["at"]))

    def of_kind(self, kind: str) -> list[Line]:
        return [line for line in self.lines if line.get("kind") == kind]

    @functools.cached_property
    def voices(self) -> attribution.Voices:
        """The transcripts' voices joined to who they are (RFC 0038 §3.4), one join for the reading:
        a Day asks per transcript, and the people's labels are taken once. Through the reading's gate:
        a name learned above it is `a named voice`."""
        return attribution.Voices(self.identities, self.owner.entities, self.owner.id, self.voice_gate)

    @functools.cached_property
    def by_kind(self) -> Mapping[str, tuple[Line, ...]]:
        """The window's lines by kind, in chain order, grouped once: a reader that asks each day of a
        long reading for one kind (the Day's weather, under a `day_start` on the day before's page)
        walks the lines once, not once a day."""
        found: dict[str, list[Line]] = {}
        for line in self.lines:
            found.setdefault(str(line.get("kind")), []).append(line)
        return {kind: tuple(lines) for kind, lines in found.items()}


@dataclass(frozen=True)
class OwnerTrack:
    """The owner's stays of a window, from the index alone (`owner_track`)."""

    lb: Logbook
    tz: ZoneInfo
    first: str  # local days, inclusive
    last: str
    days: list[str]
    settings: stays.Settings
    places: list[places.Place]
    assets: dict[str, assets.Asset]
    stays: list[stays.Segment]  # the owner's stays, in time order (stops and moves left out)
    timeline_visits: list[TimelineVisit]
    noise_points: int
    day_start: DayStart  # the record's zone and where its day begins (RFC 0036)
    retracted: frozenset[str] = frozenset()  # the ids of the retracted lines of the record


def record_days(lb: Logbook, kind: str | None = None) -> tuple[str, str] | None:
    """The first and last local day the record has a line of `kind` on (any line when None);
    None when it has none. A reader of the owner's track asks for `location`, so that a
    resolution written before the first point does not open the window on empty days."""
    with lb.index() as idx:
        return idx.span(kind)


# the kinds of line that are about the record, not about a day: a crossing (the line each export appends,
# dated the day it ran), a retraction, a resolution (the name overlay) and a migration
BOOKKEEPING = frozenset({"crossing", RETRACTION, "resolution", "migration"})


def record_span(lb: Logbook) -> tuple[str, str] | None:
    """The first and last local day with a line that observes a day — every kind but the record's
    own bookkeeping (`BOOKKEEPING`) — so that an export's run does not move the window of the next
    (`export site`, `export world`). None when the record has no such line."""
    with lb.index() as idx:
        spans = [idx.span(str(row["kind"])) for row in idx.kinds() if row["kind"] not in BOOKKEEPING]
    found = [span for span in spans if span is not None]
    if not found:
        return None
    return min(a for a, _b in found), max(b for _a, b in found)


def crossing(lines: Iterable[Line], tiers: Sequence[int] | None) -> list[Line]:
    """The lines whose tier is in `tiers`; every line when `tiers` is None."""
    if tiers is None:
        return list(lines)
    allowed = {int(t) for t in tiers}
    return [line for line in lines if int(line.get("tier") or 0) in allowed]


def read(
    lb: Logbook,
    first: str,
    last: str,
    airports: Airports | None = None,
    tiers: Sequence[int] | None = None,
    kinds: Sequence[str] | None = None,
) -> Reading:
    """The reading of `[first, last]` (local days, inclusive); through the gate `tiers` when given
    (the module's docstring). Raises `stays.SettingsError` when the settings, the places or the
    assets file is not what it should be. The settings file is never written here. With `kinds`, the
    reading of a reader that needs only those lines (the world's): its lines are those of `kinds`
    alone, and the stays are derived from the index's own columns, every subject's points and the
    owner's evidence, as from the lines (`_tracked`; `points` holds the window's points)."""
    bounds = day_start.of(lb.meta)  # DayStartError for a boundary this reader cannot parse (RFC 0036)
    tz = bounds.zone
    settings = stays.read_settings(lb.root)
    known = stays.read_places(lb.root, settings.radius_m)
    registered = stays.read_assets(lb.root)
    airports = airports or Airports.load()
    days = day_range(first, last)
    start, end, spill, nights_of = _window(bounds, first, last, settings)
    points: list[stays.Point] | None = None
    with lb.index() as idx:
        if kinds is None:
            found = crossing((line for _day, line in idx.between(first, spill)), tiers)
        else:
            found = crossing((line for kind in kinds for line in idx.of_kind(kind, first, spill)), tiers)
            tracks, evidence = _tracked(idx, first, spill, start, end, tiers)
            points = [p for track in tracks.values() for p in track if p.at < end]
        marks = idx.retractions()  # from every file: a retraction applies wherever its line is
        resolutions = idx.resolutions()
    retracted = retractions(marks)
    window = [
        line
        for line in found
        if line["kind"] != RETRACTION
        and ((at := stays.instant(line["at"])) is not None and start <= at < end)
    ]
    window.sort(key=lambda line: int(line["seq"]))
    assets_kinds = {k: v.kind for k, v in registered.items()}
    if kinds is None:
        following = _first_points_after(found, end)
        derived = stays.derive(
            [*window, *following, *marks], settings, known, assets_kinds, str(tz), airports
        )
    else:
        derived = stays.derive_tracks(tracks, evidence, settings, known, assets_kinds, str(tz), airports)
    night = stays.Nights(derived.segments, tz, settings, known).of  # the stays folded once, not once a day
    nights = [night(day) for day in days]
    nights_after = [night(day) for day in nights_of if day > last]
    standing = [line for line in window if str(line["id"]) not in retracted]
    identities = resolve.identities_from([*marks, *resolutions])
    names = {ref: who.label for ref, who in identities.items() if who.label}
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    return Reading(
        lb=lb,
        tz=tz,
        first=first,
        last=last,
        days=days,
        lines=standing,
        settings=settings,
        places=known,
        assets=registered,
        derived=derived,
        nights=nights,
        names=names,
        identities=identities,
        airports=airports,
        day_start=bounds,
        owner=owner,
        retracted=retracted,
        tiers=None if tiers is None else tuple(int(t) for t in tiers),
        nights_after=nights_after,
        points=points,
    )


def owner_track(lb: Logbook, first: str, last: str, airports: Airports | None = None) -> OwnerTrack:
    """The owner's stays of `[first, last]` (local days, inclusive), the window `read` takes, from
    the index alone. The points are the owner's and those of every asset `assets.json` names, so a
    stay aboard one says so; another subject's track is not read (it has no stays here and names
    nothing the owner can be aboard). Raises `stays.SettingsError` as `read` does; writes nothing."""
    bounds = day_start.of(lb.meta)
    tz = bounds.zone
    settings = stays.read_settings(lb.root)
    known = stays.read_places(lb.root, settings.radius_m)
    registered = stays.read_assets(lb.root)
    days = day_range(first, last)
    start, end, spill, _nights = _window(bounds, first, last, settings)
    with lb.index() as idx:
        tracks = {
            subject: _track(idx.locations(first, spill, subject), subject, start, end)
            for subject in (None, *sorted(registered))
        }
        retracted = frozenset(idx.superseded(RETRACTION))
        evidence = _evidence(_somewhere(idx, first, spill, retracted), start, end)
        derived = stays.derive_tracks(
            {subject: track for subject, track in tracks.items() if track},
            evidence,
            settings,
            known,
            {k: v.kind for k, v in registered.items()},
            str(tz),
            airports,
            subjects=[None],
        )
        found = [s for s in derived.segments if s.subject is None and s.kind == stays.STAY]
        ids = idx.ids(seq for s in found for seq in (s.first_seq, s.last_seq) if seq is not None)
        visits = idx.of_source("location", places.TIMELINE_SOURCE, first, spill, places.TIMELINE_VISIT_RAW_ID)
    standing = [
        line
        for line in visits
        if str(line["id"]) not in retracted
        and ((at := stays.instant(line["at"])) is not None and start <= at < end)
    ]
    return OwnerTrack(
        lb=lb,
        tz=tz,
        first=first,
        last=last,
        days=days,
        settings=settings,
        places=known,
        assets=registered,
        stays=[
            replace(s, first_line=ids.get(s.first_seq or -1), last_line=ids.get(s.last_seq or -1))
            for s in found
        ],
        timeline_visits=places.timeline_visits(standing),
        noise_points=derived.noise_points,
        day_start=bounds,
        retracted=retracted,
    )


def _window(
    bounds: DayStart, first: str, last: str, settings: stays.Settings
) -> tuple[datetime, datetime, str, list[str]]:
    """The instants a reading of `[first, last]` holds — from the first day's start to the end of the
    last day or of the night after it, whichever is later — the last local day the index is asked for
    (the one that holds that end: the points after it are there for `_first_points_after`), and the
    nights to derive, the night after the last day among them. Under midnight that is the first day's
    midnight, the morning after the last day and the nights of the window's days, as it always was."""
    start = bounds.span(first)[0]
    night = bounds.night_after(last, settings.night[0])
    _night_start, night_end = stays.night_window(night, bounds.zone, settings)
    end = max(night_end, bounds.span(last)[1])
    spill = max(bounds.day(end), date.fromisoformat(last) + timedelta(days=1)).isoformat()
    nights = day_range(first, max(last, night))
    return start, end, spill, nights


def _track(rows: list[LocationRow], subject: str | None, start: datetime, end: datetime) -> list[stays.Point]:
    """One subject's points of the window and the first point at or after its end: what a stay that
    runs past the window lasts until (`stays._until`), so the night at home is seen when the
    tracker's first word of the morning comes after the night's end. The rows are the days' and a
    day more (`spill`), so that point is there when the tracker spoke that day. Not sorted here:
    `stays.derive_tracks` puts each track in time order once."""
    try:
        points = [stays.Point(fromisoformat(at), lat, lon, subject, seq) for seq, at, lat, lon in rows]
    except (
        ValueError
    ):  # a stamp the index holds that is not RFC3339: the line is skipped, as `derive` skips it
        points = [
            stays.Point(at, lat, lon, subject, seq)
            for seq, text, lat, lon in rows
            if (at := stays.instant(text)) is not None
        ]
    window = [p for p in points if start <= p.at < end]
    after = [p for p in points if p.at >= end]
    if after:
        window.append(min(after, key=lambda p: (p.at, p.seq)))
    return window


def _evidence(rows: list[EvidenceRow], start: datetime, end: datetime) -> list[stays.Evidence]:
    """The window's evidence as `stays.derive` reads it: a line whose `at` is not a stamp is skipped."""
    try:
        found = [
            stays.Evidence(fromisoformat(at), None if end_ is None else fromisoformat(end_), kind)
            for kind, at, end_ in rows
        ]
    except ValueError:
        found = [
            stays.Evidence(at, stays.instant(end_), kind)
            for kind, text, end_ in rows
            if (at := stays.instant(text)) is not None
        ]
    return [e for e in found if start <= e.at < end]


def _somewhere(
    idx: Index, first: str, last: str, retracted: frozenset[str], tiers: Sequence[int] | None = None
) -> list[EvidenceRow]:
    """The evidence rows of [first, last] that promote, as `stays.derive` takes them from the lines:
    every row of the evidence kinds from the index's columns, less the events that happened nowhere
    (`stays.somewhere`). Those can only be told by their payload, so the events of each source in the
    window that is not a calendar are read whole (through `Index.of_kind`, which a gated index cuts as
    it cuts `Index.evidence`), and one row is set aside per standing line of them that carries no
    place and no people; a calendar's are never read."""
    rows = idx.evidence(stays.EVIDENCE, first, last, tiers)
    _days, present = idx.kind_source_days(first, last, (EVENT,), tiers)
    nowhere: Counter[tuple[str, str | None]] = Counter()
    for _kind, source in sorted(present):
        if source in stays.CALENDARS:
            continue
        for line in crossing(idx.of_kind(EVENT, first, last, source), tiers):
            if str(line.get("id")) not in retracted and not stays.somewhere(line):
                end = line.get("end")
                nowhere[(str(line.get("at")), end if isinstance(end, str) and end else None)] += 1
    kept: list[EvidenceRow] = []
    for row in rows:
        kind, at, end_ = row
        if kind == EVENT and nowhere[(at, end_)] > 0:
            nowhere[(at, end_)] -= 1
            continue
        kept.append(row)
    return kept


def _tracked(
    idx: Index, first: str, spill: str, start: datetime, end: datetime, tiers: Sequence[int] | None
) -> tuple[dict[str | None, list[stays.Point]], list[stays.Evidence]]:
    """What `stays.derive` takes from the lines of a window, from the index's own columns: every
    subject's points of the window and, per subject, the first location line at or after its end
    (`_first_points_after`: a point only when it has one and stands), and the owner's evidence
    (`_somewhere`); through the gate `tiers`."""
    rows = idx.location_rows(first, spill, tiers)
    tracks: dict[str | None, list[stays.Point]] = {}
    after: dict[str | None, tuple[datetime, int, stays.Point | None]] = {}
    for seq, line_id, text, lat, lon, subject, gone in rows:
        at = stays.instant(text)
        if at is None or at < start:
            continue
        point = (
            None if gone or lat is None or lon is None else stays.Point(at, lat, lon, subject, seq, line_id)
        )
        if at < end:
            if point is not None:
                tracks.setdefault(subject, []).append(point)
        elif subject not in after or at < after[subject][0]:
            after[subject] = (at, seq, point)
    for subject, (_at, _seq, point) in after.items():
        if point is not None:
            tracks.setdefault(subject, []).append(point)
    retracted = frozenset(idx.superseded(RETRACTION))
    return tracks, _evidence(_somewhere(idx, first, spill, retracted, tiers), start, end)


def _first_points_after(lines: list[Line], end: datetime) -> list[Line]:
    """Per subject, the first location line at or after `end` among `lines` (the index gave the
    day after the window too): the point a stay that runs past the window's end lasts until, so the
    night at home is seen when the tracker's first word of the morning comes after the night's end
    (`stays._until`). It is given to the derivation only; it is not a line of the window."""
    first: dict[str | None, Line] = {}
    for line in lines:
        if line.get("kind") != "location":
            continue
        at = stays.instant(line.get("at"))
        if at is None or at < end:
            continue
        subject = (line.get("payload") or {}).get("subject")
        key = subject if isinstance(subject, str) and subject else None
        kept = first.get(key)
        if kept is None or at < (stays.instant(kept["at"]) or at):
            first[key] = line
    return list(first.values())


def window_json(reading: Reading | OwnerTrack) -> Mapping[str, object]:
    return {
        "since": reading.first,
        "until": reading.last,
        "days": reading.days,
    }
