"""The dream of a journey (`logbook dream journey ID`, and `dream --catch-up` the morning after one
closes): a model reads one journey of the record whole and writes one `draft/v1` line about it
(RFC 0036, unit `journey`), the trip as a whole, the days that stood out, the places with their
hours, who was on it, what was decided and promised, the photos it would star and one name it
proposes, every sentence pointing at the lines it came from. A proposal, as every draft: the captain
names a journey (`logbook add --trip`) and stars a photo; the dream only proposes both.

It runs on the dream's engine (`logbook.contrib.dream`) under the same `dream` entry of
`policy/crossing.json` and the same endpoint, and it is held to the same rules: the journey is read
through the entry's ceiling (`trip_page.locate` over a gated reading), so no line above it is read,
named or counted; every sentence cites lines of the journey or is marked unsupported, and more than
30 % unsupported refuses the answer; a figure in a sentence must be one the code computed from the
lines it cites (`dream.hold_numbers`), else the sentence is marked; the draft's tier is the highest
tier among the lines it read, and it records the version of the entry it was dreamed under.

**What it reads.** A journey is a trip (`logbook.core.trips`, ADR 0019): a run of nights away from
home, derived and never written, its id `trip:<first day>:<last day>`. Its lines are every line of
its days, the first day to the return day, under the ceiling (`dream.lines_of_days`), and beside them
the standing synthesis of each of its calls the entry allows (`drafts.for_transcripts`, the one rule,
`drafts.through`), whose decisions are given as the call's (`drafted`) and whose lines count among
what it read. The material: the journey's bounds, route, places and nights; each day's timeline from
the Day reader with the hours of each stay (`dream.days_of`); the hours at each place; the flights;
the canonical people confirmed on it; the messages by counterpart, counted, never their text; the
notes; the promises made on its days (`journeys.promises_on`, those whose line is read); the photos,
the ones already starred apart; and the captain's name for it, when there is one.

**Once, after it closes.** A journey is dreamed only once it has closed: its return day is before
today and the night after it was spent at home (`closed`). A journey still away, or whose last night
the record does not yet place, is refused (`NotClosed`), so the dream never reads half a trip.
`--catch-up` dreams each journey that closed on one of the days it looks at, the morning after (the
06:00 close); after that the re-dream rule is the day's (`dream.why_again`): its lines under the
ceiling today another count or set than the standing draft read, the standing draft above the entry's
`max_tier` today, or dreamed under another version of the entry; else it is unchanged and nothing is
sent. `dream journey ID` dreams it again on demand; the same model at the same head under the same
entry writes nothing (RFC 0036 rule 1).

**The line.** `unit` `journey`; `subject` the journey's id, then the ids of the lines the trip rests
on (`Trip.lines`: each night's stay, its flights, the companions'), so the Journeys reader finds it by
the id (`drafts.by_unit`, `journeys.draft_of`); `read_count` the journey's own lines it read and
`extra.read_ids_sha256` the digest of everything it read, `extra.read_beside` how many beside them;
`extra.parts` the part of each segment (`drafts.JOURNEY_PARTS`); `extra.star` the photo lines its
`photos` sentences propose to star, never one starred already; `extra.name` the name it proposes, one
at most (more are dropped and counted under `extra.dropped`); `extra.marked` the sentences the number
rule marked."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from string import Template
from typing import Any

from ..core import drafts, keepers, notes, policy, reading, stays, trips
from ..core.chain import Line
from ..core.export import day_range
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.store import HeadMoved, Logbook, retractions
from . import dream, journeys, trip_page
from .dream import DreamError, Material, Outcome
from .model_client import Transport

PROMPT_FILE = Path(__file__).with_name("dream-journey-prompt.md")
PROMPT_NAME = "dream-journey/1"  # kept under `extra.prompt`, so a draft says which prompt wrote it
PHOTO = "photo"
PHOTOS_GIVEN = 40  # the photos given as candidates to star, at most: the owner's favourites first
STARS = 6  # the photos a draft proposes to star, at most
REFS = 12  # the references an item carries, at most; its count is always whole
NAMES = 1  # the names a draft proposes: one
MORE_THAN_ONE_NAME = "more than one name"
STARRED_ALREADY = "a photo starred already"
NOT_A_PHOTO = "not a photo of the journey"


class NotClosed(DreamError):
    """The journey has not closed: it is still away, or the record does not yet place the night
    after its return day at home. Nothing is read and nothing is sent."""


@dataclass(frozen=True)
class Read:
    """What the dream read of a journey: the material and the ids of the lines it read beside the
    journey's own (its calls' syntheses), which count toward the tier, the count and the digest."""

    made: Material
    trip: trips.Trip
    photos: frozenset[str]  # the journey's photo lines read, the only lines a star may name
    starred: frozenset[str]  # of those, the ones a keeper already stars
    beside: int = 0  # the lines it read beside the journey's own (its calls' syntheses): `extra.read_beside`


# -- the journey ----------------------------------------------------------------------------------------


def locate(
    lb: Logbook, ref: str, found: policy.Ceiling, airports: Airports | None = None
) -> tuple[Reading, trips.Trip]:
    """The journey `ref` names (its id, or any day of it) in a reading through the entry's ceiling;
    `ValueError` as `trip_page.locate` raises it."""
    tiers = dream.tiers_of(found)
    return trip_page.locate(lb, trip_page.parse_ref(ref), airports or Airports.load(), tiers, names_at=tiers)


def closed(rd: Reading, trip: trips.Trip, today: date) -> bool:
    """Whether the journey has closed: its return day is before `today` and the reading places the
    night after it at home. A night the record does not place, in transit or away, is not a close."""
    night = rd.night_after(trip.until)
    return trip.until < today.isoformat() and night is not None and night.home


def refuse_open(rd: Reading, trip: trips.Trip, today: date) -> None:
    """`NotClosed`, in one sentence, unless the journey has closed (`closed`)."""
    if closed(rd, trip, today):
        return
    if trip.until >= today.isoformat():
        why = f"it comes home on {trip.until}, which is not over"
    else:
        why = f"the record does not place the night after {trip.until} at home yet"
    raise NotClosed(f"{trip.id} has not closed: {why}; a journey is dreamed once, after it closes")


def standing_of(lb: Logbook, trip: trips.Trip) -> Line | None:
    """The journey's standing draft, by its id, whatever the entry allows (rule 2): the one a new
    draft supersedes."""
    with lb.index() as idx:
        found = drafts.by_unit(idx.by_kind(drafts.KIND), retractions(idx.retractions()), drafts.UNIT_JOURNEY)
    return drafts.standing(found.get(trip.id, []))


# -- the material -----------------------------------------------------------------------------------------


def material(lb: Logbook, rd: Reading, trip: trips.Trip, found: policy.Ceiling) -> Read:
    """The journey's material under the entry's ceiling (the module's docstring); `rd` is a reading
    through the ceiling (`locate`)."""
    tiers = dream.tiers_of(found)
    on = dream.lines_of_days(rd, trip.start, trip.until)
    ids = {str(line["id"]) for line in on}
    calls = [str(line["id"]) for line in on if line.get("kind") == "transcript"]
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        known = dream.names_for(lb, found, idx)
        names, identities = known.labels, known.identities
        syntheses, _held = drafts.for_transcripts(idx, calls, tiers, drafts.allowed(lb.root))
        named = journeys.names_in(idx.by_kind(notes.KIND, trip.start, trip.until), retracted)
        stars = keepers.standing([*reading.crossing(idx.by_kind(keepers.KIND), tiers), *idx.retractions()])
    read = ids | {str(s["line"]) for s in syntheses}
    tier = max(
        [int(line.get("tier", 1)) for line in on] + [int(s.get("tier") or 1) for s in syntheses], default=1
    )
    made = Material(
        day=trip.id,
        unit=drafts.UNIT_JOURNEY,
        tier=tier,
        read_count=len(ids),  # the lines of the unit (RFC 0036 rule 5); the digest covers all it read
        read_head=str(lb.meta["head"]),
        read_ids_sha256=dream.digest(read),
        language=dream.language_of(dream._texts(on)),
        data={},
        ids=ids,
        zone=rd.tz,
        canonical=known.canonical(lb),
        identities=identities,
        withheld=known.withheld,
    )
    photos = [line for line in on if line.get("kind") == PHOTO]
    starred = {p for p in (keepers.photo_id_of(k) for k in stars) if p} & {str(line["id"]) for line in photos}
    days, places = dream.days_of(rd, day_range(trip.start, trip.until), made)
    nights = journeys.nights_of(trip, rd)
    name = journeys.name_of(trip, named, rd.day_start)
    made.data = {
        "journey": {
            "id": trip.id,
            "first_day": trip.start,
            "last_night": trip.end,
            "return_day": trip.until,
            "nights": trip.nights,
            "nights_in_transit": trip.in_transit,
            "route": list(trip.route),
            "places": list(trip.places),
            "aboard": trip.names.get(trip.asset, trip.asset) if trip.asset else None,
            "named": name.text if name is not None and name.line in ids else None,
            "ref": made.refs_of(i for n in nights for i in n["lines"])[:REFS],
        },
        "max_tier": found.max_tier,
        "days": days,
        "places": places,
        "flights": [
            {
                "flight": f"{f['carrier']} {f['number']} {f['from']} to {f['to']}",
                "day": f["date"],
                "ref": made.refs_of(f["lines"]),
            }
            for f in trip.flights
            if any(i in ids for i in f["lines"])
        ],
        "people": [
            {"id": c.person, "name": made.canonical[c.person], "ref": made.refs_of(c.lines)[:REFS]}
            for c in trip.people
            if c.person is not None and made.person(c.person) is not None and made.refs_of(c.lines)
        ],
        "messages": _counted(dream._messages(on, names, made)),
        "notes": dream._notes(on, made),
        "decisions": _decisions(syntheses, made),
        "promises": _promises(journeys.promises_on(lb, trip, tiers), made),
        "photos": {
            "count": len(photos),
            "ref": made.refs_of(str(line["id"]) for line in photos)[:REFS],
            "candidates": _candidates(photos, starred, rd, made),
            "starred": made.refs_of(sorted(starred)),
        },
    }
    made.tier = max(made.tier, known.tier_in(made.data))  # a name read is read (R2)
    return Read(
        made, trip, frozenset(str(line["id"]) for line in photos), frozenset(starred), len(read - ids)
    )


def _counted(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The messages by counterpart with their count and references, never their text: a journey is
    told by where it went and who was there, and a fortnight of chat is not the model's to read."""
    out = []
    for entry in messages:
        kept = {k: v for k, v in entry.items() if k != "texts"}
        kept["ref"] = list(entry["ref"])[:REFS]
        out.append(kept)
    return out


def _decisions(syntheses: list[dict[str, Any]], made: Material) -> list[dict[str, Any]]:
    """The decisions of the journey's calls, each as its call's standing synthesis has it (`drafted`,
    a model's words) under the call's own reference; only the supported ones."""
    out = []
    for block in syntheses:
        ref = made.refs_of([str(block["transcript"])])
        for segment in block["segments"]:
            if (
                segment["part"] == "decisions"
                and segment["supported"]
                and ref
                and not made.withholds(segment["text"])
            ):
                out.append({"drafted": segment["text"], "ref": ref})
    return out


def _promises(found: list[dict[str, Any]], made: Material) -> list[dict[str, Any]]:
    """The promises made on the journey's days whose line it read, in the promise reader's words."""
    out = []
    for p in found:
        ref = made.refs_of([str(p["line"])])
        if not ref:
            continue  # a promise read from a line above the ceiling is not the model's to see
        out.append(
            {
                "day": p["day"],
                "role": p["role"],
                "counterpart": made.name_of(p["counterpart"]),
                "quote": p["quote"],
                "status": p["status"],
                "due": p["due"],
                "ref": ref,
            }
        )
    return out


def _candidates(photos: list[Line], starred: set[str], rd: Reading, made: Material) -> list[dict[str, Any]]:
    """The photos it may propose to star, at most `PHOTOS_GIVEN`: the owner's favourites first, then
    one per day in turn, never one a keeper stars already; each with its day and how many faces."""
    left = [line for line in photos if str(line["id"]) not in starred]
    favourite = [line for line in left if ((line.get("payload") or {}).get("extra") or {}).get("favorite")]
    rest = [line for line in left if line not in favourite]
    by_day: dict[str, list[Line]] = {}
    for line in rest:
        by_day.setdefault(rd.day_of(line), []).append(line)
    spread: list[Line] = []
    while any(by_day.values()):
        for day in sorted(by_day):
            if by_day[day]:
                spread.append(by_day[day].pop(0))
    out = []
    for line in [*favourite, *spread][:PHOTOS_GIVEN]:
        payload = line.get("payload") or {}
        item: dict[str, Any] = {"day": rd.day_of(line), "ref": made.refs_of([str(line["id"])])}
        if line in favourite:
            item["favorite"] = True
        if isinstance(payload.get("people"), list) and payload["people"]:
            item["faces"] = len(payload["people"])
        out.append(item)
    return out


# -- the prompt and the answer ---------------------------------------------------------------------------


def prompt(read: Read) -> list[dict[str, str]]:
    """The two messages the model gets: the journey's prompt with its bounds and language filled in,
    and the material as JSON."""
    made, trip = read.made, read.trip
    system = Template(PROMPT_FILE.read_text(encoding="utf-8")).safe_substitute(
        journey=trip.id,
        first=trip.start,
        nights=f"{trip.nights} night{'s' if trip.nights != 1 else ''}",
        until=trip.until,
        tz=str(made.zone),
        language=made.language,
        language_name=dream.LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def shape(found: Mapping[str, Any], read: Read) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The answer as a draft has it: the segments in the parts' order (`dream.segments_of`), one
    name at most, the number rule held (`dream.hold_numbers`), no figure beside a person
    (`dream.hold_names`, in the day's order), the evidence rule's share checked again; and what `extra`
    keeps of it: `parts`, `star`, `name`, `dropped`, `marked`."""
    made = read.made
    segments, parts = dream.segments_of(found, made, drafts.JOURNEY_PARTS, strict=True)
    dropped: dict[str, int] = {}
    names = [i for i, part in enumerate(parts) if part == "name"]
    if len(names) > NAMES:
        for i in reversed(names[NAMES:]):
            del segments[i], parts[i]
        dropped[MORE_THAN_ONE_NAME] = len(names) - NAMES
    marked: dict[str, int] = {}
    unbacked = dream.hold_numbers(segments, made.data, made)
    if unbacked:
        marked[dream.UNBACKED] = unbacked
    beside = dream.hold_names(segments, made)  # no number beside a person, whatever the lines give
    if beside:
        marked[dream.BESIDE_A_NAME] = beside
    dream.share_of(segments, made.unit)
    extra: dict[str, Any] = {"parts": parts}
    star: list[str] = []
    for segment, part in zip(segments, parts, strict=True):
        if part != "photos" or "evidence" not in segment:
            continue
        for line_id in segment["evidence"]:
            if line_id in read.photos and line_id not in read.starred and line_id not in star:
                star.append(line_id)
    if star:
        extra["star"] = star[:STARS]
    name = next((s for s, p in zip(segments, parts, strict=True) if p == "name" and "evidence" in s), None)
    if name is not None:
        extra["name"] = name["text"]
    if dropped:
        extra["dropped"] = dropped
    if marked:
        extra["marked"] = marked
    return segments, extra


# -- the dream --------------------------------------------------------------------------------------------


def run(
    lb: Logbook,
    ref: str,
    env: Mapping[str, str] | None = None,
    airports: Airports | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    today: date | None = None,
    located: tuple[Reading, trips.Trip] | None = None,
    read: Read | None = None,
) -> dream.Dream:
    """Dream the journey `ref` names: the policy, the endpoint, the journey through the ceiling
    (`located` when the caller found it already), the close (`NotClosed`), the material (`read` when
    the caller built it under the lock already), the model's turn, the checks, and one `draft/v1`
    line appended under the writer lock unless `dry_run`. `DreamError` says why nothing was written,
    `ValueError` when no journey is there; `HeadMoved` when the record moved under the reading."""
    found = dream.ceiling(lb)
    ep = dream.endpoint(found, env)
    today = today or dream.today()
    with lb.writer():
        rd, trip = located or locate(lb, ref, found, airports)
        refuse_open(rd, trip, today)
        read = read or material(lb, rd, trip, found)
        made = read.made
        if made.read_count == 0:
            raise DreamError(f"{trip.id} has no line under max_tier {found.max_tier}; nothing to dream")
        latest = standing_of(lb, trip)
        source = drafts.SOURCE_PREFIX + ep.model
        version = policy.version(found)
        if not dry_run:
            dream.refuse_same(latest, source, made, version)
        messages = prompt(read)
        if say is not None:
            say(messages[0]["content"])
            say(messages[1]["content"])
        answer, found_answer = dream.ask(ep, messages, transport)
        segments, kept = shape(found_answer, read)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_JOURNEY,
            "subject": list(dict.fromkeys([trip.id, *trip.lines])),
            "read_head": made.read_head,
            "read_count": made.read_count,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                **kept,
                "read_ids_sha256": made.read_ids_sha256,
                "read_beside": read.beside,
                "policy_version": version,
            },
        }
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        dream.valid(payload)
        if dry_run:
            return dream.Dream(trip.id, None, payload, made.tier, messages, answer)
        line = dream.append(lb, made, source, payload)
    return dream.Dream(trip.id, line, payload, made.tier, messages, answer)


# -- catch-up ---------------------------------------------------------------------------------------------


def changed_since(
    lb: Logbook, rd: Reading, trip: trips.Trip, found: policy.Ceiling
) -> tuple[bool, str, Read]:
    """Whether a closed journey needs dreaming, by the day's rule (`dream.why_again`): no draft yet,
    a standing draft the entry no longer stands behind, or what it would read today is not what the
    standing draft read. The material is returned so a caller that dreams does not read twice."""
    read = material(lb, rd, trip, found)
    latest = standing_of(lb, trip)
    if latest is None:
        return True, "closed, no draft yet", read
    why = dream.why_again(latest, found, read.made.read_count, read.made.read_ids_sha256)
    if why is not None:
        return True, why, read
    return False, f"unchanged since #{latest['seq']}", read


def catch_up(
    lb: Logbook,
    days: int,
    today: date,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    airports: Airports | None = None,
) -> list[Outcome]:
    """Dream each journey that closed on one of the last `days` days (its return day among them and
    the night after it at home), when it needs it (`changed_since`); one `Outcome` per journey, in
    the order they came home. A journey still away is not looked at. The policy and the endpoint are
    checked once: a refusal there is `DreamError`."""
    found = dream.ceiling(lb)
    dream.endpoint(found, env)
    window = dream.days_to_catch_up(today, days)
    airports = airports or Airports.load()
    out: list[Outcome] = []
    with lb.writer():
        try:
            rd = reading.read(
                lb, window[0], window[-1], airports, dream.tiers_of(found), names_at=dream.tiers_of(found)
            )
        except (ValueError, stays.SettingsError) as e:
            return [Outcome("journeys", "refused", str(e))]
        found_trips, warning = trips.trips(rd)
        if warning:
            return out
        for trip in found_trips:
            if not window[0] <= trip.until <= window[-1] or not closed(rd, trip, today):
                continue
            out.append(_catch_up_one(lb, rd, trip, found, env, transport, airports, today))
    return out


def _catch_up_one(
    lb: Logbook,
    rd: Reading,
    trip: trips.Trip,
    found: policy.Ceiling,
    env: Mapping[str, str] | None,
    transport: Transport | None,
    airports: Airports,
    today: date,
) -> Outcome:
    try:
        if trip.start == rd.first:  # it may have begun before the days looked at: read it whole
            rd, trip = locate(lb, trip.end, found, airports)
        needed, why, read = changed_since(lb, rd, trip, found)
        if not needed:
            return Outcome(trip.id, "unchanged", why)
        dreamed = run(
            lb, trip.id, env, airports, transport=transport, today=today, located=(rd, trip), read=read
        )
        return Outcome(trip.id, "dreamed", dream.detail_of(dreamed, why))
    except (DreamError, HeadMoved, ValueError, stays.SettingsError) as e:
        return Outcome(trip.id, "refused", str(e))
