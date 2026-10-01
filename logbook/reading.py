"""One reading of the record over a window of local days, for every reader that derives from it.

`read(lb, first, last)` loads the window's lines through the index (from the first day's local
midnight to the end of the night after the last day, so the last night is inside it), the
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
through the index by their `raw_id`. The same window and the same rules as `read`, so the stays
are the same stays."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import assets, places, policy, present, resolve, stays
from .chain import Line
from .export import day_range
from .flights import Airports
from .index import EvidenceRow, LocationRow, local_date
from .places import TimelineVisit
from .store import RETRACTION, Logbook, retractions

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
    owner: present.Owner = field(default_factory=lambda: present.Owner(frozenset(), frozenset(), frozenset()))
    retracted: dict[str, Line] = field(default_factory=dict)

    @property
    def owner_stays(self) -> list[stays.Segment]:
        return [s for s in self.derived.segments if s.subject is None and s.kind == stays.STAY]

    @property
    def segments(self) -> list[stays.Segment]:
        return self.derived.segments

    def night_of(self, day: str) -> stays.Night | None:
        return next((n for n in self.nights if n.day == day), None)

    def day_of(self, line: Line) -> str:
        return local_date(str(line["at"]), str(self.tz))

    def of_kind(self, kind: str) -> list[Line]:
        return [line for line in self.lines if line.get("kind") == kind]


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
    retracted: frozenset[str] = frozenset()  # the ids of the retracted lines of the record


def record_days(lb: Logbook, kind: str | None = None) -> tuple[str, str] | None:
    """The first and last local day the record has a line of `kind` on (any line when None);
    None when it has none. A reader of the owner's track asks for `location`, so that a
    resolution written before the first point does not open the window on empty days."""
    with lb.index() as idx:
        return idx.span(kind)


def read(lb: Logbook, first: str, last: str, airports: Airports | None = None) -> Reading:
    """The reading of `[first, last]` (local days, inclusive). Raises `stays.SettingsError` when the
    settings, the places or the assets file is not what it should be. The settings file is never
    written here."""
    tz = ZoneInfo(str(lb.meta["timezone"]))
    settings = stays.read_settings(lb.root)
    known = stays.read_places(lb.root, settings.radius_m)
    registered = stays.read_assets(lb.root)
    airports = airports or Airports.load()
    days = day_range(first, last)
    start = datetime.combine(date.fromisoformat(first), datetime.min.time(), tzinfo=tz)
    _night_start, end = stays.night_window(last, tz, settings)
    with lb.index() as idx:
        spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
        found = [line for _day, line in idx.between(first, spill)]
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
    following = _first_points_after(found, end)
    derived = stays.derive(
        [*window, *following, *marks],
        settings,
        known,
        {k: v.kind for k, v in registered.items()},
        str(tz),
        airports,
    )
    nights = [stays.night(derived.segments, day, tz, settings, known) for day in days]
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
        owner=owner,
        retracted=retracted,
    )


def owner_track(lb: Logbook, first: str, last: str, airports: Airports | None = None) -> OwnerTrack:
    """The owner's stays of `[first, last]` (local days, inclusive), the window `read` takes, from
    the index alone. The points are the owner's and those of every asset `assets.json` names, so a
    stay aboard one says so; another subject's track is not read (it has no stays here and names
    nothing the owner can be aboard). Raises `stays.SettingsError` as `read` does; writes nothing."""
    tz = ZoneInfo(str(lb.meta["timezone"]))
    settings = stays.read_settings(lb.root)
    known = stays.read_places(lb.root, settings.radius_m)
    registered = stays.read_assets(lb.root)
    days = day_range(first, last)
    start = datetime.combine(date.fromisoformat(first), datetime.min.time(), tzinfo=tz)
    _night_start, end = stays.night_window(last, tz, settings)
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    with lb.index() as idx:
        tracks = {
            subject: _track(idx.locations(first, spill, subject), subject, start, end)
            for subject in (None, *sorted(registered))
        }
        evidence = _evidence(idx.evidence(stays.EVIDENCE, first, spill), start, end)
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
        retracted = frozenset(idx.superseded(RETRACTION))
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
        retracted=retracted,
    )


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
