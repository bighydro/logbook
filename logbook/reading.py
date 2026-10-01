"""One reading of the record over a window of local days, for every reader that derives from it.

`read(lb, first, last)` loads the window's lines through the index (from the first day's local
midnight to the end of the night after the last day, so the last night is inside it), the
settings, places and assets of the record, derives the stays (`stays.derive`) and the night of
each day, resolves the names of the record's refs (`resolve`) and the owner's own identities
(`present.owner_of`). Readers — `places propose`,
`rollup`, `trips`, the pages — take a `Reading` and compute; none of them writes. A reading is a
function of the record at one head: the same record, the same reading."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import assets, places, policy, present, resolve, stays
from .chain import Line
from .export import day_range
from .flights import Airports
from .index import local_date
from .store import RETRACTION, Logbook, retractions


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


def window_json(reading: Reading) -> Mapping[str, object]:
    return {
        "since": reading.first,
        "until": reading.last,
        "days": reading.days,
    }
