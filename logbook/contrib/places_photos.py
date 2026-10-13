"""Ask the photos — `logbook setup places review --ask-photos`.

`places review` names a spot only from what the record's lines say, and most photo lines say nothing:
they were imported before the Immich and Apple Photos adapters kept the place their library named, and
the record is append-only, so a re-import writes none of them again. The libraries still know. This
module asks them about the photos already in the record, and offers what they say as evidence beside
the record's own, counted by how many photos said it: `immich ×12: Havbyen`, `photos ×3: Plattformen`.

**Which places.** The proposals shown (after `--near` and `--top`), or the ones an `--accept` or
`--reject` names (`--name` gives the owner's own): those whose proposal is a blank, and with `--all`
the ones that have a name too. The queue and its numbers are #255's, built before anything is asked,
so a number means the same with the flag and without it.

**Which photos.** The record's photo lines of `immich` and `apple-photos` that are not retracted or
superseded, carry coordinates and an asset id, and carry no `extra.place` of their own (one that does
is counted by `places review` already). A photo is at the observed place whose centre is nearest it
within `MATCH_M` (150 m), the distance a photo line's own place name is matched over. Per place and
library, the `LIMIT` (50, `--limit N`) nearest its centre, nearest first.

**Asking.** Immich by asset id through the adapter's own client (`immich.places`: `GET
/api/assets/{id}`, the configured host and key, `asset.read`, one request at a time, at most
`immich.LOOKUPS_PER_S` a second): **the asset ids go to the owner's own server and nothing else does —
no coordinate, no name, never a geocoder.** Apple Photos from the library on this machine
(`apple_photos.places`, its reverse-location data, `~/Pictures/Photos Library.photoslibrary` or
`--photos-library PATH`), read-only. A source the owner disabled in `policy/import.json`, an Immich
without its two variables and a library that is not there are said and passed over. Before anything is
asked, one line per library says how many photos it will be asked about, how many the cache answers,
and where the rest go. A library that fails is said once, with how many photos were not asked; the
review goes on with the others.

**What it says.** An answer is read as `places review` reads a photo line's `extra.place`
(`places_review.photo_name`): Photos' area name or address weighs 2 a photo, a city (all Immich has) 1.
The names join the proposal's evidence under the origin `library` and the proposal's name is chosen
again (`places_review.choose`), a name taken or rejected passed over as before. No line is written:
accepting a name is `--accept`, as it always was.

**The cache.** Every answer — a place, no place, no such asset — is kept in
`state/places-photos.json` beside the record, keyed by library and asset id, for `CACHE_TTL_DAYS`
(30 days); a second review within them asks nothing again. A failure is never kept. The file is
bookkeeping, as the rest of `state/` is: deleting it only means the next review asks again."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePath, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from ..core import policy
from ..core.store import RETRACTION, Logbook
from . import adapters, places_review
from .adapters import apple_photos, immich
from .places_review import MATCH_M, SAMPLES, Name, Proposal, Report

LIMIT = 50  # photos per place and library, the nearest its centre first
CACHE_FILE = PurePosixPath("state/places-photos.json")  # record-relative: bookkeeping, never a line
CACHE_TTL_DAYS = 30
CACHE_VERSION = 1
LIBRARIES = (immich.NAME, apple_photos.NAME)  # asked in this order
MISSING = {immich.NAME: "not on the server", apple_photos.NAME: "not in the library"}
PROGRESS_EVERY = 100  # Immich lookups between two progress lines


@dataclass(frozen=True)
class Photo:
    """A photo line of the record to ask its library about."""

    number: int  # the proposal it is at
    library: str  # immich, apple-photos
    asset_id: str
    line: str  # the line's id, as evidence
    metres: float  # from the place's centre


@dataclass(frozen=True)
class Answer:
    found: bool  # False: the library holds no such asset
    place: dict[str, Any] | None  # what it named, as `extra.place` keeps it; None: nothing


@dataclass
class Outcome:
    """What one library was asked, and what it said."""

    library: str
    where: str  # the Immich host, or the Photos store
    photos: int = 0
    cached: int = 0
    asked: int = 0
    named: int = 0
    none: int = 0
    missing: int = 0
    not_asked: int = 0
    failed: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "library": self.library,
            "where": self.where,
            "photos": self.photos,
            "cached": self.cached,
            "asked": self.asked,
            "named": self.named,
            "none": self.none,
            "missing": self.missing,
            "not_asked": self.not_asked,
            "failed": self.failed,
        }


def store_of(path: str | Path | None) -> Path:
    """The Photos store `--photos-library` names, else the one a Mac keeps under the home folder."""
    folder = Path(path).expanduser() if path else Path.home().joinpath(*apple_photos.DEFAULT_LIBRARY)
    return apple_photos.library_store(folder)


def shown(path: Path) -> str:
    """A path as the owner's lines say it: under the home folder as `~/…`."""
    try:
        return str(PurePath("~") / Path(path).relative_to(Path.home()))
    except ValueError:
        return str(path)


def cache_path(root: Path) -> Path:
    return Path(root).joinpath(*CACHE_FILE.parts)


# -- the photos -------------------------------------------------------------------------------------------


def photos(lb: Logbook, report: Report, targets: Sequence[Proposal], limit: int = LIMIT) -> list[Photo]:
    """The photo lines to ask about (the module's docstring), per place and library the `limit`
    nearest its centre: in queue order, then library, then nearest first."""
    if not targets or limit <= 0:
        return []
    every = places_review._Grid(MATCH_M)
    for n, o in enumerate(report.observed):
        every.add(o.lat, o.lon, n)
    wanted = {(p.observed.id, p.observed.lat, p.observed.lon): p.number for p in targets}
    number_of = {n: wanted.get((o.id, o.lat, o.lon)) for n, o in enumerate(report.observed)}
    near = places_review._Grid(MATCH_M)
    for p in targets:
        near.add(p.lat, p.lon, p.number)
    found: dict[tuple[int, str], dict[str, tuple[float, str]]] = {}
    with lb.index() as idx:
        gone = set(idx.superseded(RETRACTION)) | set(idx.superseded("photo"))
        for library in LIBRARIES:
            for line in idx.of_kind("photo", source=library):
                candidate = _candidate(line, gone)
                if candidate is None:
                    continue
                asset_id, lat, lon = candidate
                if not near.within(lat, lon, MATCH_M):
                    continue
                metres, n = every.within(lat, lon, MATCH_M)[0]
                number = number_of.get(n)
                if number is None:  # nearer another place, one not asked about
                    continue
                assets = found.setdefault((number, library), {})
                held = assets.get(asset_id)
                if held is None or (metres, str(line["id"])) < held:
                    assets[asset_id] = (metres, str(line["id"]))
    out: list[Photo] = []
    for (number, library), assets in sorted(
        found.items(), key=lambda kv: (kv[0][0], LIBRARIES.index(kv[0][1]))
    ):
        nearest = sorted(assets.items(), key=lambda kv: (kv[1][0], kv[1][1], kv[0]))[:limit]
        out += [Photo(number, library, asset_id, line_id, metres) for asset_id, (metres, line_id) in nearest]
    return out


def _candidate(line: Mapping[str, Any], gone: set[str]) -> tuple[str, float, float] | None:
    """(asset id, lat, lon) of a photo line its library can be asked about, else None."""
    if str(line.get("id")) in gone:
        return None
    payload = line.get("payload")
    if not isinstance(payload, dict):
        return None
    extra = payload.get("extra")
    if isinstance(extra, dict) and "place" in extra:  # the record holds its library's answer already
        return None
    lat, lon = places_review._coordinates(payload.get("lat"), payload.get("lon"))
    asset_id = payload.get("asset_id") or payload.get("raw_id")
    if lat is None or lon is None or not isinstance(asset_id, str) or not asset_id.strip():
        return None
    return asset_id.strip(), lat, lon


# -- asking -----------------------------------------------------------------------------------------------


def ask(
    lb: Logbook,
    report: Report,
    shown: Sequence[Proposal],
    *,
    every: bool = False,
    limit: int = LIMIT,
    env: Mapping[str, str] | None = None,
    library: str | Path | None = None,
    say: Callable[[str], None] = print,
    now: datetime | None = None,
) -> tuple[Report, list[Outcome]]:
    """The report with the photo evidence added to the proposals of `shown` that are blanks (all of
    them with `every`), and what each library was asked; `say` is told the cost first and what came
    back after. Writes nothing to the record; the answers go to the cache."""
    targets = [p for p in shown if every or p.name is None]
    if not targets:
        if shown:
            say("asking the photos: every place shown has a name already; --all asks about those too")
        else:
            say("asking the photos: no place shown to ask about")
        return report, []
    places_text = places_review._plural(len(targets), "place")
    if limit <= 0:
        say(f"asking the photos about {places_text}: --limit {limit} asks about no photo")
        return report, []
    found = photos(lb, report, targets, limit)
    if not found:
        say(
            f"asking the photos about {places_text}: no photo of the record without a place name lies at them"
        )
        return report, []
    say(
        f"asking the photos about {places_text}: up to {limit} photos at each from each library,"
        " the nearest its centre first"
    )
    cache = Cache(lb.root, now or datetime.now(UTC))
    answers: dict[tuple[str, str], Answer] = {}
    disabled = _disabled(lb.root)
    config = immich.configure(os.environ if env is None else env)
    store = store_of(library)
    plans: list[tuple[Outcome, list[str], str | None]] = []
    for name in LIBRARIES:
        ids = list(dict.fromkeys(p.asset_id for p in found if p.library == name))
        if not ids:
            continue
        if name == immich.NAME:
            where = "" if config is None else urlsplit(config.url).netloc or config.url
        else:
            where = str(store)
        outcome = Outcome(name, where, photos=len(ids))
        todo = []
        for asset_id in ids:
            hit = cache.get(name, asset_id)
            if hit is None:
                todo.append(asset_id)
            else:
                answers[(name, asset_id)] = hit
                outcome.cached += 1
        reason = _unaskable(name, disabled, config, store) if todo else None
        say(_plan_text(outcome, todo, reason, store))
        plans.append((outcome, todo, reason))
    try:
        for outcome, todo, reason in plans:
            if todo and reason is None:
                _lookup(outcome, todo, config, store, answers, cache, say)
            elif todo:
                outcome.not_asked = len(todo)
            _tally(outcome, found, answers)
            if outcome.cached or outcome.asked:
                say(_result_text(outcome))
    finally:
        cache.save()
    return _with_photos(lb, report, targets, found, answers), [o for o, _todo, _reason in plans]


def _disabled(root: Path) -> dict[str, str]:
    """The sources the owner disabled in `policy/import.json`, by adapter name; read, never written."""
    listed = policy.read_disabled(root)
    return {adapters.ALIASES.get(name, name): reason for name, reason in listed.items()}


def _unaskable(
    name: str, disabled: Mapping[str, str], config: immich.Config | None, store: Path
) -> str | None:
    """Why a library cannot be asked this time, or None when it can."""
    if name in disabled:
        return f"{name} is disabled in {policy.IMPORT_FILE} ({disabled[name]})"
    if name == immich.NAME and config is None:
        return f"set {' and '.join(immich.ENV)}"
    if name == apple_photos.NAME and not store.is_file():
        return f"no Photos library at {shown(store)} (--photos-library PATH)"
    return None


def _plan_text(outcome: Outcome, todo: Sequence[str], reason: str | None, store: Path) -> str:
    label = places_review.LIBRARY_LABELS[outcome.library]
    text = f"  {label}: {places_review._plural(outcome.photos, 'photo')}"
    if outcome.cached:
        text += f", {outcome.cached} answered from the cache"
    if not todo:
        return f"{text}; nothing to ask"
    if reason is not None:
        return f"{text}; {len(todo)} not asked: {reason}"
    if outcome.library == immich.NAME:
        rate = immich.LOOKUPS_PER_S
        ids = places_review._plural(len(todo), "asset id")
        return (
            f"{text}; sending {ids} to {outcome.where}, nothing else,"
            f" at most {rate:g} a second (about {_duration(len(todo) / rate)})"
        )
    which = "their places" if len(todo) == outcome.photos else f"the places of the other {len(todo)}"
    return f"{text}; reading {which} from the library at {shown(store)}, on this machine"


def _duration(seconds: float) -> str:
    return f"{math.ceil(seconds)} s" if seconds < 120 else f"{math.ceil(seconds / 60)} min"


def _lookup(
    outcome: Outcome,
    todo: Sequence[str],
    config: immich.Config | None,
    store: Path,
    answers: dict[tuple[str, str], Answer],
    cache: Cache,
    say: Callable[[str], None],
) -> None:
    """Ask one library about `todo`; every answer into `answers` and the cache. A failure is said
    once and ends the asking of that library."""
    name = outcome.library
    try:
        if name == immich.NAME:
            assert config is not None
            started = time.monotonic()
            for asset_id, place in immich.places(config, todo):
                answer = Answer(place is not None, place or None)
                answers[(name, asset_id)] = answer
                cache.put(name, asset_id, answer)
                outcome.asked += 1
                if outcome.asked % PROGRESS_EVERY == 0 and outcome.asked < len(todo):
                    elapsed = time.monotonic() - started
                    say(f"  immich: {outcome.asked:,} of {len(todo):,} asked in {elapsed:,.0f}s")
        else:
            held = apple_photos.places(store, todo)
            for asset_id in todo:
                answer = Answer(asset_id in held, held.get(asset_id) or None)
                answers[(name, asset_id)] = answer
                cache.put(name, asset_id, answer)
            outcome.asked = len(todo)
    except (OSError, ValueError, sqlite3.Error) as e:
        outcome.failed = str(e) or type(e).__name__
        outcome.not_asked = len(todo) - outcome.asked
        label = places_review.LIBRARY_LABELS[name]
        say(
            f"  {label} at {outcome.where} failed: {outcome.failed};"
            f" {places_review._plural(outcome.not_asked, 'photo')} not asked, the review goes on without them"
        )


def _tally(outcome: Outcome, found: Sequence[Photo], answers: Mapping[tuple[str, str], Answer]) -> None:
    for asset_id in dict.fromkeys(p.asset_id for p in found if p.library == outcome.library):
        answer = answers.get((outcome.library, asset_id))
        if answer is None:
            continue
        if not answer.found:
            outcome.missing += 1
        elif places_review.photo_name(answer.place) is None:
            outcome.none += 1
        else:
            outcome.named += 1


def _result_text(outcome: Outcome) -> str:
    text = f"  {places_review.LIBRARY_LABELS[outcome.library]}: {outcome.named} named a place"
    if outcome.none:
        text += f", {outcome.none} no place"
    if outcome.missing:
        text += f", {outcome.missing} {MISSING[outcome.library]}"
    return text


def _with_photos(
    lb: Logbook,
    report: Report,
    targets: Sequence[Proposal],
    found: Sequence[Photo],
    answers: Mapping[tuple[str, str], Answer],
) -> Report:
    """The report with each target's photo names in its evidence and its name chosen again."""
    said: dict[int, dict[tuple[str, str, str], Name]] = {}
    for photo in found:  # nearest first: the evidence's line ids are the nearest photos'
        answer = answers.get((photo.library, photo.asset_id))
        named = places_review.photo_name(answer.place) if answer is not None else None
        if named is None:
            continue
        name, grade = " ".join(named[0].split()), named[1]
        entry = said.setdefault(photo.number, {}).setdefault(
            (photo.library, name.casefold(), grade), Name("library", photo.library, name, grade)
        )
        entry.count += 1
        if len(entry.lines) < SAMPLES:
            entry.lines.append(photo.line)
    if not said:
        return report
    taken = {p.name.casefold() for p in report.places}
    rejected = places_review.rejections(lb.root)
    asked = {p.number for p in targets}
    proposals = []
    for p in report.proposals:
        extra = said.get(p.number) if p.number in asked else None
        if not extra:
            proposals.append(p)
            continue
        names = places_review.ranked([*p.observed.names, *extra.values()])
        refused = places_review.refused_at(rejected, p.lat, p.lon, report.cluster_m)
        proposals.append(
            replace(
                p,
                observed=places_review.replace_names(p.observed, names),
                name=places_review.choose(names, taken, refused),
            )
        )
    return replace(report, proposals=proposals)


# -- the cache --------------------------------------------------------------------------------------------


class Cache:
    """The answers kept in `state/places-photos.json`: library → asset id → `{"at", "found", "place"}`,
    each good for `CACHE_TTL_DAYS`. A file that is not what this version writes reads as empty."""

    def __init__(self, root: Path, now: datetime) -> None:
        self.path = cache_path(root)
        self.now = now
        self.answers: dict[str, dict[str, dict[str, Any]]] = {}
        self.changed = False
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
            stored = data.get("answers")
            if isinstance(stored, dict):
                self.answers = {
                    str(name): {str(k): v for k, v in rows.items() if isinstance(v, dict)}
                    for name, rows in stored.items()
                    if isinstance(rows, dict)
                }

    def _fresh(self, row: Mapping[str, Any]) -> bool:
        try:
            at = datetime.fromisoformat(str(row.get("at")).replace("Z", "+00:00"))
        except ValueError:
            return False
        if at.tzinfo is None:
            return False
        return timedelta(0) <= self.now - at < timedelta(days=CACHE_TTL_DAYS)

    def get(self, library: str, asset_id: str) -> Answer | None:
        row = self.answers.get(library, {}).get(asset_id)
        if row is None or not self._fresh(row) or not isinstance(row.get("found"), bool):
            return None
        place = row.get("place")
        return Answer(bool(row["found"]), place if isinstance(place, dict) else None)

    def put(self, library: str, asset_id: str, answer: Answer) -> None:
        self.answers.setdefault(library, {})[asset_id] = {
            "at": self.now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "found": answer.found,
            "place": answer.place,
        }
        self.changed = True

    def save(self) -> None:
        """Written when an answer was added, every stale one dropped; atomically."""
        if not self.changed:
            return
        kept = {
            name: {k: row for k, row in sorted(rows.items()) if self._fresh(row)}
            for name, rows in sorted(self.answers.items())
        }
        data = {"version": CACHE_VERSION, "ttl_days": CACHE_TTL_DAYS, "answers": kept}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf-8"))
        os.replace(temporary, self.path)
