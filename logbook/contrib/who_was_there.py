"""Who was there, as acts: the owner's word on a stretch of days and on the people who live with them
(RFC 0043 §11, *Who was there*, and §12, *Lives with*), each a `note/v1` line in the owner's words, tier
2, source `manual`, through the one note path (`notes.write`), and the readers of those notes.

- **With, across a stretch**: `logbook with --from D1 --to D2 NAME…` states the people present on every
  day of the stretch, one `with` note per person per day, each written by the function `logbook with`
  uses for one day (`presence.state`), at the clock of that day's **longest stay**: the middle of the
  part of the stay that falls on the day, so the note lies inside the stay and the with module reads it
  there (SPEC §3.2.5 rule 3). A day with no stay is stated as `logbook with` states it without a clock
  (noon, or now for today). Everything is checked before the first line is written: a stretch longer
  than `MAX_DAYS`, a day still to come, a name that is nobody, several people or the owner each refuse
  the whole stretch in one sentence, and nothing is written. All the days are written under one hold of
  the writer lock (`Logbook.writer` re-enters for each day's `presence.state`). A person already stated
  on a day is not stated on it again.
- **Not with**: `logbook people not-with NAME --from D1 --to D2`, one note labelled `not-with`, the
  person's id and the stretch under `extra` (`person`, `from`, `to`): the proposals of that person on
  those days are set aside (the review-with queue, `review_with`).
- **Lives with**: `logbook people lives-with NAME --from D [--until D]`, a note labelled `lives-with`
  (`person`, `from`, `until` when given; `--until` alone ends the standing one): at a home stay that
  person is with the owner without asking, so the queue never asks; away from home their faces propose
  as anyone's do.
- **Lives in**: `logbook people lives-in NAME CITY [--from D]`, a note labelled `lives-in` (`person`,
  `city`, `from`): the person's city, for *your people in this city* (`review_with.people_in_city`).
  The latest standing one of a person is where they live.

Each note is written on the day the owner says it (now), its text `<label>: <name>, …` so that no
reader parses it as company: the with module reads `with <Name>` in a note's words, and the colon
after the label keeps these out of it. A reader never parses the text: only the label and `extra`
say what a note states. The relation notes are read from the owner's manual notes through the index
(`Index.of_kind`, kind `note`, source `manual`), one sweep of those lines and no others; a retracted
note stands no more.

**The owner's own camera** (`own_camera`): a photo proposes a face for presence only when the owner's
own camera took it. What each library keeps of that (`docs/who-was-there.md`): Apple Photos keeps how
the asset arrived, `provenance` (`camera`, `received`, `screenshot`, `other`) and `extra.imported_by`
(1 and 2 the back and the front camera; 3, 8 and 13 another app, AirDrop or sharing, shared with you);
Immich keeps `provenance` from the EXIF (a make and model and an original capture time, or a live
pair) and the camera's make and model, but not which of the server's users or devices uploaded it;
Google Takeout keeps the origin (`mobileUpload` is `camera`, a shared album `received`). So a photo is
the owner's own camera's when its `provenance` is `camera` and nothing it keeps says it was received.
Nothing here reads a file but the record's, and nothing is fetched."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from ..core import day_start, notes, people, presence, reading, stays
from ..core.chain import Line
from ..core.export import parse_day
from ..core.store import Logbook, retractions

MAX_DAYS = 60  # the longest stretch one statement covers
NOT_WITH, LIVES_WITH, LIVES_IN = notes.NOT_WITH, notes.LIVES_WITH, notes.LIVES_IN
LABELS = (NOT_WITH, LIVES_WITH, LIVES_IN)
SOURCE = presence.SOURCE  # the owner's word
CAMERA = "camera"
RECEIVED = "received"
RECEIVED_IMPORTS = frozenset({3, 8, 13})  # Apple Photos' ZIMPORTEDBY: another app, AirDrop or sharing, shared
EN_DASH = "\N{EN DASH}"


class CompanyError(ValueError):
    """A statement the record refuses; the message is one sentence and nothing is written."""


def refused(e: presence.WithError) -> CompanyError:
    """A name `presence.resolve` refuses, as one sentence: its reason, then the hint after a colon."""
    return CompanyError(str(e).replace("; nothing was written. ", "; nothing was written: ").rstrip("."))


def resolve(names: Sequence[str], report: people.Report) -> list[people.Person]:
    """`presence.resolve`, its refusal one sentence (`refused`)."""
    try:
        return presence.resolve(names, report)
    except presence.WithError as e:
        raise refused(e) from e


# -- the stretch -------------------------------------------------------------------------------------------


def days_of(first: str, last: str) -> list[str]:
    """The local days from `first` to `last`, both inclusive. `CompanyError` for a stretch that runs
    backwards or is longer than `MAX_DAYS`."""
    try:
        start, end = parse_day(first), parse_day(last)
    except ValueError as e:
        raise CompanyError(f"{e}; nothing was written") from e
    if end < start:
        raise CompanyError(f"--to {end} is before --from {start}; nothing was written")
    count = (end - start).days + 1
    if count > MAX_DAYS:
        raise CompanyError(
            f"{start} {EN_DASH} {end} is {count} days, longer than {MAX_DAYS}; say a stretch of"
            f" {MAX_DAYS} days or fewer, nothing was written"
        )
    return [(start + timedelta(days=n)).isoformat() for n in range(count)]


def longest_stay(
    day: str, found: Sequence[stays.Segment], days: day_start.DayStart, now: datetime
) -> str | None:
    """The clock (`HH:MM`, on the record's clock) in the middle of the part of the day's longest stay
    that falls on the day and has already happened; None when no stay touches the day."""
    start, end = days.span(day)
    end = min(end, now.astimezone(days.zone))
    best: tuple[float, datetime, datetime] | None = None
    for stay in found:
        lo, hi = max(stay.start, start), min(stay.end, end)
        length = (hi - lo).total_seconds()
        if length > 0 and (best is None or length > best[0]):
            best = (length, lo, hi)
    if best is None:
        return None
    middle = best[1] + (best[2] - best[1]) / 2
    return middle.astimezone(days.zone).strftime("%H:%M")


@dataclass(frozen=True)
class DayStated:
    """One day of a stretch: the clock it was stated at (None: the day had no stay) and who."""

    day: str
    at: str | None
    stated: list[presence.Stated]

    def to_json(self) -> dict[str, Any]:
        return {"day": self.day, "at": self.at, "stated": [s.to_json() for s in self.stated]}


def with_stretch(
    lb: Logbook, first: str, last: str, names: Sequence[str], now: datetime | None = None
) -> list[DayStated]:
    """`with_days` over every day from `first` to `last` (at most `MAX_DAYS`)."""
    return with_days(lb, days_of(first, last), names, now)


def with_days(
    lb: Logbook,
    wanted: Iterable[str],
    names: Sequence[str],
    now: datetime | None = None,
    report: people.Report | None = None,
) -> list[DayStated]:
    """State `names` present on each of the days `wanted`, one `with` note per person per day, at the
    day's longest stay, through `presence.state`, all under one hold of the writer lock. Every day and
    every name is checked before the first line is written; `CompanyError` (one sentence) and nothing
    written otherwise. A person already stated on a day is not stated on it again. `report` is the
    people directory when the caller read it under the same hold of the lock."""
    clock = now if now is not None else datetime.now(UTC)
    chosen = sorted({parse_day(d).isoformat() for d in wanted})
    if not chosen:
        raise CompanyError("name at least one day; nothing was written")
    if len(chosen) > MAX_DAYS:
        raise CompanyError(f"{len(chosen)} days is more than {MAX_DAYS}; nothing was written")
    with lb.writer():
        days = day_start.of(lb.meta)
        report = report if report is not None else people.directory(lb)
        persons = resolve(names, report)
        track = reading.owner_track(lb, chosen[0], chosen[-1])
        plan: list[tuple[str, str | None, list[people.Person]]] = []
        with lb.index() as idx:
            retracted = retractions(idx.retractions())
            for day in chosen:
                at = longest_stay(day, track.stays, days, clock)
                try:
                    presence.moment(day, at, days, clock)
                except presence.WithError as e:
                    raise CompanyError(f"{e}; nothing was written") from e
                already = {presence.person_of(line) for line in presence.stated(idx.day(day), retracted)}
                plan.append((day, at, [p for p in persons if p.entity not in already]))
        out = []
        for day, at, todo in plan:
            stated = (
                presence.state(lb, day, [p.entity for p in todo], at, now=clock, report=report)
                if todo
                else []
            )
            skipped = [presence.Stated(p.entity, p.name, None) for p in persons if p not in todo]
            out.append(DayStated(day, at, [*stated, *skipped]))
    return out


# -- the relation notes ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Span:
    """A stretch of local days a relation holds on, `until` None while it still holds."""

    since: str | None
    until: str | None
    line: str

    def holds(self, day: str) -> bool:
        return (self.since is None or self.since <= day) and (self.until is None or day <= self.until)


@dataclass(frozen=True)
class Home:
    """Where a person lives, in the owner's words: the city, since when, the note."""

    city: str
    since: str | None
    line: str


@dataclass
class Relations:
    """The standing relation notes of the record, per person: the stretches the owner said they were
    not with them, the stretches they live with the owner, and the city they live in (the latest)."""

    not_with: dict[str, list[Span]] = field(default_factory=dict)
    lives_with: dict[str, list[Span]] = field(default_factory=dict)
    lives_in: dict[str, Home] = field(default_factory=dict)

    def not_with_on(self, person: str, day: str) -> bool:
        return any(span.holds(day) for span in self.not_with.get(person, ()))

    def lives_with_on(self, person: str, day: str) -> bool:
        return any(span.holds(day) for span in self.lives_with.get(person, ()))

    def to_json(self) -> dict[str, Any]:
        def spans(found: Mapping[str, list[Span]]) -> dict[str, list[dict[str, Any]]]:
            return {
                p: [{"from": s.since, "until": s.until, "line": s.line} for s in found[p]]
                for p in sorted(found)
            }

        return {
            "not_with": spans(self.not_with),
            "lives_with": spans(self.lives_with),
            "lives_in": {
                p: {"city": h.city, "from": h.since, "line": h.line} for p, h in sorted(self.lives_in.items())
            },
        }


def relations_of(lines: Iterable[Line], retracted: Iterable[str] = ()) -> Relations:
    """The relations `lines` state (any lines; the labelled notes among them count), retracted ones
    left out, read in the record's order: a `lives-with` note with `from` opens a stretch, one with
    only `until` closes every open one of the person; a later `lives-in` is where the person lives now."""
    gone = frozenset(retracted)
    found = Relations()
    for line in sorted(lines, key=lambda line: int(line.get("seq", 0))):
        if str(line.get("id")) in gone or line.get("kind") != notes.KIND:
            continue
        extra = (line.get("payload") or {}).get("extra")
        person = extra.get("person") if isinstance(extra, dict) else None
        if not isinstance(person, str) or not person or not isinstance(extra, dict):
            continue
        since, until = _day(extra.get("from")), _day(extra.get("until"))
        if notes.labelled(line, NOT_WITH):
            to = _day(extra.get("to"))
            if since is not None and to is not None:
                found.not_with.setdefault(person, []).append(Span(since, to, str(line["id"])))
        elif notes.labelled(line, LIVES_WITH):
            spans = found.lives_with.setdefault(person, [])
            if since is not None:
                spans.append(Span(since, until, str(line["id"])))
            elif until is not None:
                spans[:] = [Span(s.since, until, s.line) if s.until is None else s for s in spans]
        elif notes.labelled(line, LIVES_IN):
            city = extra.get("city")
            if isinstance(city, str) and city.strip():
                found.lives_in[person] = Home(" ".join(city.split()), since, str(line["id"]))
    return found


def relations(lb: Logbook) -> Relations:
    """The record's relations: its owner's manual notes, one sweep through the index."""
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        lines = [line for line in idx.of_kind(notes.KIND, source=SOURCE) if _relation(line)]
    return relations_of(lines, retracted)


def _relation(line: Line) -> bool:
    return any(notes.labelled(line, label) for label in LABELS)


def _day(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_day(value).isoformat()
    except ValueError:
        return None


# -- the relation acts -------------------------------------------------------------------------------------


def not_with(lb: Logbook, name: str, first: str, last: str, now: datetime | None = None) -> Line:
    """One note labelled `not-with`: `name`'s person was not with the owner from `first` to `last`.
    `CompanyError` for a name that is nobody, several people or the owner, or a stretch that runs
    backwards; nothing is written then."""
    since, to = _span(first, last)
    return _write(
        lb,
        name,
        NOT_WITH,
        lambda label: f"{NOT_WITH}: {label}, {since} to {to}",
        {"from": since, "to": to},
        now,
    )


def lives_with(
    lb: Logbook, name: str, since: str | None = None, until: str | None = None, now: datetime | None = None
) -> Line:
    """One note labelled `lives-with`: from `since` (default today), until `until` when given; with
    `until` alone, the end of the standing stretch. `CompanyError` as `not_with`."""
    clock = now if now is not None else datetime.now(UTC)
    today = day_start.of(lb.meta).today(clock).isoformat()
    if since is None and until is None:
        since = today
    start = _given(since, "--from") if since is not None else None
    end = _given(until, "--until") if until is not None else None
    if start is not None and end is not None and end < start:
        raise CompanyError(f"--until {end} is before --from {start}; nothing was written")
    if start is None and end is not None:
        with lb.writer():
            (person,) = resolve([name], people.directory(lb))
            if not any(span.until is None for span in relations(lb).lives_with.get(person.entity, ())):
                raise CompanyError(
                    f"{person.name} has no standing lives-with to end; say --from D to begin one,"
                    " nothing was written"
                )
            return _lives_with(lb, name, start, end, now)
    return _lives_with(lb, name, start, end, now)


def _lives_with(lb: Logbook, name: str, start: str | None, end: str | None, now: datetime | None) -> Line:
    extra: dict[str, Any] = {}
    words = []
    if start is not None:
        extra["from"] = start
        words.append(f"from {start}")
    if end is not None:
        extra["until"] = end
        words.append(f"until {end}")
    return _write(lb, name, LIVES_WITH, lambda label: f"{LIVES_WITH}: {label}, {' '.join(words)}", extra, now)


def lives_in(
    lb: Logbook, name: str, city: str, since: str | None = None, now: datetime | None = None
) -> Line:
    """One note labelled `lives-in`: `name`'s person lives in `city`, from `since` (default today).
    `CompanyError` as `not_with`, and for a city with no words."""
    place = " ".join(str(city).split())
    if not place:
        raise CompanyError("name the city; nothing was written")
    clock = now if now is not None else datetime.now(UTC)
    start = _given(since, "--from") if since is not None else day_start.of(lb.meta).today(clock).isoformat()
    return _write(
        lb, name, LIVES_IN, lambda label: f"{LIVES_IN}: {label}, {place}", {"city": place, "from": start}, now
    )


def _span(first: str, last: str) -> tuple[str, str]:
    since, to = _given(first, "--from"), _given(last, "--to")
    if to < since:
        raise CompanyError(f"--to {to} is before --from {since}; nothing was written")
    return since, to


def _given(value: str, flag: str) -> str:
    try:
        return parse_day(value).isoformat()
    except ValueError as e:
        raise CompanyError(f"{flag} {value!r}: {e}; nothing was written") from e


def _write(
    lb: Logbook,
    name: str,
    label: str,
    text: Any,
    extra: Mapping[str, Any],
    now: datetime | None,
) -> Line:
    """The relation note: `name` resolved as `logbook with` resolves it, written on today through
    `notes.write`, under the writer lock."""
    clock = now if now is not None else datetime.now(UTC)
    with lb.writer():
        (person,) = resolve([name], people.directory(lb))
        today = day_start.of(lb.meta).today(clock).isoformat()
        at = clock.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        return notes.write(
            lb,
            today,
            text(person.name),
            label,
            SOURCE,
            at=at,
            today=today,
            extra={"person": person.entity, **extra},
        )


# -- the owner's own camera ----------------------------------------------------------------------------------


def own_camera(line: Line) -> bool:
    """Whether a `photo/v1` line was taken by the owner's own camera, as far as its library says: its
    `provenance` is `camera`, and no import it keeps says it was received (Apple Photos'
    `extra.imported_by` 3, 8 or 13: another app, AirDrop or sharing, shared with you). Only such a
    photo proposes a face for presence."""
    if line.get("kind") != "photo":
        return False
    payload = line.get("payload") or {}
    if payload.get("provenance") != CAMERA:
        return False
    extra = payload.get("extra")
    imported = extra.get("imported_by") if isinstance(extra, dict) else None
    return not (isinstance(imported, int) and not isinstance(imported, bool) and imported in RECEIVED_IMPORTS)


def today_of(lb: Logbook, now: datetime | None = None) -> str:
    """The record's today, `YYYY-MM-DD`, under its zone and `day_start`."""
    return day_start.of(lb.meta).today(now if now is not None else datetime.now(UTC)).isoformat()
