"""The timeline's reader (RFC 0043 §11, §12): the record's moments at five zooms — a day, an ISO week, a
month, a year and all years — for `/timeline` and `logbook show timeline [--json]`.

A **moment** is a stay of note: one of the owner's stays (`stays.STAY`; a stop with evidence is already
promoted to one) or a run aboard an asset (`stays.fold`), as the Day lists them. A moment says:

- its **place**: the name `places.json` gives it, else the stay's label (`aboard <asset>`, an airport,
  coordinates with what is near), as the Day reads it;
- its **class** (`places.class_of`), the colour of a night spent there: `home`, `family`, `aboard`, `away`;
- its **time** and duration, its real span and the part of it on the day;
- its **people**, from the with module the Day reads (`present.company`): the confirmed in one list, the
  proposed in another, each with its reasons in words — `invited` (a calendar's attendee), `spoke` (a
  recording), `you said` (the owner's note), `face on photos` (a library's face). No proposer is new
  here; a proposal is never shown as confirmed. A person is a name and its reasons, never a number;
- its **photos**, the owner's own camera first (`provenance` `camera`), the starred first within each;
- what passed **during** its window, placed by time and never by subject: the messages by conversation
  (who and on which network, never how many), the calls (who and which way, never how long), the
  sessions with an agent (a transcript with a machine participant: the owner's words, and the agent's
  marked as machine text), the mail threads, the notes and the calendar's entries;
- **paid** (tier 3, a slot): the `transaction/v1` lines standing whose instant lies in the window, with
  the merchant. When no payment source covers the day (the day lies outside the first and last day any
  source has a transaction line on), the day says `No payment source covers this day` and the last day
  one does. A reading through a gate without tier 3 has no slot at all: not empty, absent.

Every zoom reads through the gate `tiers` (`reading.crossing`, as every reader holds them) and says the
highest tier it read. Day and week read the lines of their days (`reading.read`, as the Day does); month,
year and life read the owner's track from the index alone (`reading.owner_track`) and count photos and
signatures from the index's columns, so no zoom past the week opens a month file for its lines. Life
reads who was there once for the whole record: the with module's confirmed company at each of the
owner's stays, from the calendar entries, recordings and notes alone (`_who_was_there`), by name, never
with a count beside a name.

Nothing here writes; the same record at the same head gives the same timeline (ADR 0013)."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Any

from . import day as day_reader
from . import ledger, machine, policy, present, reading, resolve, signing, stars, stays
from . import places as named_places
from .chain import Line
from .export import day_range, parse_day
from .flights import Airports
from .index import RETRACTED, Index
from .store import Logbook, retractions
from .transcripts import turns_of

ZOOMS = ("day", "week", "month", "year", "life")
DAY, WEEK, MONTH, YEAR, LIFE = ZOOMS
WEEK_TEXT = re.compile(r"^(\d{4})-W(\d{2})$")
MONTH_TEXT = re.compile(r"^(\d{4})-(\d{2})$")
YEAR_TEXT = re.compile(r"^\d{4}$")
MONEY_TIER = 3  # `transaction/v1` is tier 3 (RFC 0021): its slot is there only when the gate reads it
NO_PAYMENT = "No payment source covers this day"
IN_TRANSIT = "in transit"  # a night no stay held long enough (`stays.night`), `rollup nights`' word
CLASS_WORDS = {  # how a count of nights reads: "home 21 · the family's places 4 · aboard 6 · away 3"
    "home": "home",
    "family": "the family's places",
    "aboard": "aboard",
    "away": "away",
    IN_TRANSIT: IN_TRANSIT,
}
CONFIRMING = ("event", "transcript", "note")  # the evidence that can confirm company (`present`)
ARROWS = f" {day_reader.ARROW} "  # a flight's airports, `OSL → ZRH`
FACES = "face on photos"  # a face's reason, however many photos: no number beside a person
CAMERA = "camera"  # a photo's `provenance` when the owner's own camera took it
WORDS_SHOWN = 3  # an agent session's turns of each side a moment carries; the rest are on its line
WORDS_CHARS = 280
DOT = day_reader.DOT


# -- the zooms: which window a key names ------------------------------------------------------------------


def window(zoom: str, key: str | None) -> tuple[str, str]:
    """The first and last local day a zoom's key names (`2026-06-08`, `2026-W24`, `2026-06`, `2026`);
    ValueError for a key that is not one, or a zoom that takes none (`life`)."""
    if zoom == DAY and key is not None:
        d = parse_day(key)
        return d.isoformat(), d.isoformat()
    if zoom == WEEK and key is not None and (m := WEEK_TEXT.match(key)):
        try:
            monday = date.fromisocalendar(int(m.group(1)), int(m.group(2)), 1)
        except ValueError as e:
            raise ValueError(f"not a week (YYYY-Www): {key!r}") from e
        return monday.isoformat(), (monday + timedelta(days=6)).isoformat()
    if zoom == MONTH and key is not None and (m := MONTH_TEXT.match(key)) and 1 <= int(m.group(2)) <= 12:
        first = date(int(m.group(1)), int(m.group(2)), 1)
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        return first.isoformat(), last.isoformat()
    if zoom == YEAR and key is not None and YEAR_TEXT.match(key):
        return f"{key}-01-01", f"{key}-12-31"
    shape = {DAY: "YYYY-MM-DD", WEEK: "YYYY-Www", MONTH: "YYYY-MM", YEAR: "YYYY"}.get(zoom)
    if shape is None:
        raise ValueError(f"a zoom is one of {', '.join(ZOOMS)}; {zoom!r} names no window")
    raise ValueError(f"not a {zoom} ({shape}): {key!r}")


def week_of(day: str) -> str:
    """The ISO week a day is in, as the week zoom names it: `2026-W24`."""
    year, week, _ = date.fromisoformat(day).isocalendar()
    return f"{year}-W{week:02d}"


def read(
    lb: Logbook,
    zoom: str,
    key: str | None = None,
    airports: Airports | None = None,
    tiers: Sequence[int] | None = None,
) -> dict[str, Any]:
    """The timeline at `zoom` for `key` as one JSON-ready object (`day_of`, `week_of_days`, `month_of`,
    `year_of`, `life_of`). ValueError for a key that is not one; `stays.SettingsError` and
    `places.PlaceError` as the readers raise them."""
    if zoom == LIFE:
        return life_of(lb, airports, tiers)
    first, last = window(zoom, key)
    if zoom == DAY:
        return day_of(lb, first, airports, tiers)
    if zoom == WEEK:
        return week_of_days(lb, str(key), first, last, airports, tiers)
    if zoom == MONTH:
        return month_of(lb, str(key), first, last, airports, tiers)
    return year_of(lb, str(key), airports, tiers)


# -- a day: its moments and the moves between them ------------------------------------------------------


def day_of(
    lb: Logbook, day: str, airports: Airports | None = None, tiers: Sequence[int] | None = None
) -> dict[str, Any]:
    """The day's moments and the moves between them, in the Day's order, from one reading of the day
    and the day before (`reading.read`, the Day's), with the night after's class and the track the
    Day page draws (`track`: each row's kind, position and whether it is a gap)."""
    d = parse_day(day)
    rd = reading.read(lb, (d - timedelta(days=1)).isoformat(), day, airports, tiers)
    lines = day_reader.day_lines(rd, d)
    data = day_reader.of_reading(rd, day, None, lines)
    given = named_places.classes(lb.root)
    money = _money_of_day(lb, day, rd)
    by_id = {str(line["id"]): line for line in lines}
    starred = _starred(lb, day, tiers)
    items: list[dict[str, Any]] = []
    for entry in data["timeline"]:
        if entry["kind"] in (stays.STAY, day_reader.ABOARD):
            items.append(_moment(lb, entry, rd, by_id, given, starred, money))
        elif entry["kind"] == stays.MOVE:
            items.append(_move(entry, rd))
        elif entry["kind"] == day_reader.FLIGHT:
            items.append(_flight(entry, rd))
    out: dict[str, Any] = {
        "zoom": DAY,
        "day": day,
        "weekday": data["weekday"],
        "tz": data["tz"],
        "week": week_of(day),
        "night": _night(rd.night_after(day), rd.places, given, rd),
        "items": items,
        "track": [
            {"kind": e["kind"], "lat": e.get("lat"), "lon": e.get("lon"), "gap": bool(e.get("gap"))}
            for e in data["timeline"]
        ],
        "tier": max((int(line.get("tier") or 0) for line in lines), default=None),
    }
    if money is not None:  # tier 3 read: the day's slot; otherwise no key at all
        placed = {t["line"] for i in items for t in (i.get("money") or {}).get("paid", ())}
        out["money"] = {k: v for k, v in money.items() if k != "lines"}
        out["money"]["elsewhere"] = [  # by the day only, or at an instant no moment holds (a move)
            {k: v for k, v in t.items() if k != "by"} for t in money["lines"] if t["line"] not in placed
        ]
    return out


def _moment(
    lb: Logbook,
    entry: Mapping[str, Any],
    rd: reading.Reading,
    lines: Mapping[str, Line],
    given: Mapping[str, str],
    starred: Mapping[str, object],
    money: Mapping[str, Any] | None,
) -> dict[str, Any]:
    attached = entry.get("attached") or {}
    named = next((p for p in rd.places if p.name == entry.get("place")), None)
    photos = [i for i in (attached.get("photos") or {}).get("lines", ()) if i in lines]
    own = [i for i in photos if (lines[i].get("payload") or {}).get("provenance") == CAMERA]
    others = [i for i in photos if i not in own]
    start, end = _at(entry["within_day"]["start"]), _at(entry["within_day"]["end"])
    out: dict[str, Any] = {
        "kind": "moment",
        "id": entry["id"],
        "aboard": entry.get("aboard"),
        "place": entry.get("where") or "somewhere",
        "named": named is not None or entry["kind"] == day_reader.ABOARD,
        "class": _class_of(entry, rd, given),
        "start": entry["start"],
        "end": entry["end"],
        "start_local": entry["start_local"],
        "end_local": entry["end_local"],
        "within_day": dict(entry["within_day"]),
        "span": _span(entry["within_day"], rd),
        "duration_s": entry["duration_s"],
        "people": _people(entry.get("with") or {}),
        "photos": _starred_first(own, starred) + _starred_first(others, starred),
        "during": _during(lb, attached, lines, rd),
    }
    if money is not None:
        paid = [t for t in money["lines"] if t["by"] == ledger.BY_INSTANT and start <= _at(t["at"]) < end]
        out["money"] = {"paid": [{k: v for k, v in t.items() if k != "by"} for t in paid]}
        if not money["covered"]:
            out["money"]["said"] = NO_PAYMENT
    return out


def _class_of(entry: Mapping[str, Any], rd: reading.Reading, given: Mapping[str, str]) -> str:
    """A Day row's class (`places.class_of`): its named place's, home when the stay lies within reach
    of a home place (`stays.is_home`, the night rule), aboard on an asset, else away. The day and the
    week both ask here, so one stay has one class on both."""
    named = next((p for p in rd.places if p.name == entry.get("place")), None)
    home = (
        entry.get("lat") is not None
        and entry.get("lon") is not None
        and stays.is_home(
            stays.Segment(
                kind=stays.STAY,
                subject=None,
                start=_at(entry["start"]),
                end=_at(entry["end"]),
                points=0,
                lat=float(entry["lat"]),
                lon=float(entry["lon"]),
                place=entry.get("place"),
            ),
            rd.places,
        )
    )
    return named_places.class_of(named, entry.get("aboard"), given, home=bool(home))


def _move(entry: Mapping[str, Any], rd: reading.Reading) -> dict[str, Any]:
    return {
        "kind": day_reader.GAP if entry.get("gap") else stays.MOVE,
        "start": entry["start"],
        "end": entry["end"],
        "start_local": entry["start_local"],
        "end_local": entry["end_local"],
        "within_day": dict(entry["within_day"]),
        "span": _span(entry["within_day"], rd),
        "duration_s": entry["duration_s"],
        "mode": entry.get("mode"),
        "distance_m": entry.get("distance_m"),
        "airports": list(entry.get("airports") or ()),
    }


def _flight(entry: Mapping[str, Any], rd: reading.Reading) -> dict[str, Any]:
    return {
        "kind": day_reader.FLIGHT,
        "start": entry["start"],
        "end": entry["end"],
        "start_local": entry["start_local"],
        "end_local": entry["end_local"],
        "span": day_reader.span_text(entry["start"], entry["end"], rd.tz),
        "flight": " ".join(str(p) for p in (entry.get("carrier"), entry.get("number")) if p),
        "airports": [c for c in (entry.get("from"), entry.get("to")) if c],
        "line": entry["line"],
    }


def _people(found: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """The with module's company of a stay, as the timeline says it: names, and the reasons in words;
    the confirmed and the proposed never in one list."""
    return {
        status: [
            {"name": str(c["name"]), "person": c.get("person"), "because": because(c.get("reasons") or ())}
            for c in found.get(status) or ()
        ]
        for status in ("confirmed", "proposed")
    }


def because(reasons: Sequence[str]) -> list[str]:
    """The with module's reasons (`present`) in the timeline's words, each once: `invited`, `spoke`,
    `you said`, `face on photos` (however many: no number beside a person); a reason it does not know,
    as it is."""
    words: list[str] = []
    faces = False
    for reason in reasons:
        if reason.startswith("face "):
            faces = True
            continue
        word = (
            "invited"
            if reason.startswith("attendee of ")
            else "spoke"
            if reason.startswith("spoke in ")
            else "you said"
            if reason.startswith("note says with ")
            else reason
        )
        if word not in words:
            words.append(word)
    if faces:
        words.append(FACES)
    return words


def _during(
    lb: Logbook, attached: Mapping[str, Any], lines: Mapping[str, Line], rd: reading.Reading
) -> dict[str, list[dict[str, Any]]]:
    """What passed during the moment's window, by kind, from the lines the Day placed inside it."""
    messages = [lines[i] for i in (attached.get("messages") or {}).get("lines", ()) if i in lines]
    conversations = []
    for c in day_reader.conversations(messages, rd.names):
        agent = any(machine.with_agent(lines[m["line"]].get("payload") or {}) for m in c["messages"])
        conversations.append(
            {
                "with": c["counterpart"],
                "network": c["network"],
                "group": c["group"],
                "agent": agent,
                "lines": [m["line"] for m in c["messages"]],
            }
        )
    agents, recordings = [], []
    for t in attached.get("transcripts") or ():
        line = lines.get(t["line"])
        parts = ((line or {}).get("payload") or {}).get("participants")
        if (
            line is not None
            and isinstance(parts, list)
            and any(machine.is_machine_participant(p) for p in parts)
        ):
            agents.append(_session(lb, line, parts))
        else:
            recordings.append({"title": t["title"], "line": t["line"]})
    return {
        "messages": conversations,
        "calls": [  # who and which way, never how long: no number beside a person
            {k: c[k] for k in ("who", "direction", "answered", "line")} for c in attached.get("calls") or ()
        ],
        "agents": agents,
        "recordings": recordings,
        "mail": [
            {"subject": m["subject"], "messages": m["messages"], "lines": list(m["lines"])}
            for m in attached.get("mail") or ()
        ],
        "notes": [dict(n) for n in attached.get("notes") or ()],
        "events": [
            {"title": e["title"], "start": e["start"], "end": e.get("end"), "line": e["line"]}
            for e in attached.get("events") or ()
        ],
    }


def _session(lb: Logbook, line: Line, parts: Sequence[Any]) -> dict[str, Any]:
    """A session with an agent: the owner's words (their turns) and the agent's, marked as machine
    text; each side's first `WORDS_SHOWN` turns, the whole on the line."""
    payload = line.get("payload") or {}
    turns = turns_of(lb, line) or []
    mine = machine.human_turns(turns, parts)
    machines = machine.labels(parts)
    theirs = [
        t for t in turns if t.speaker is not None and " ".join(t.speaker.split()).casefold() in machines
    ]
    agent = machine.agent_of(payload) or {}
    return {
        "title": str(payload.get("title") or "a session"),
        "source": str(line.get("source") or ""),
        "agent": str(agent.get("name") or line.get("source") or "an agent"),
        "owner": [_cut(t.text) for t in mine[:WORDS_SHOWN]],
        "machine": [_cut(t.text) for t in theirs[:WORDS_SHOWN]],
        "line": str(line["id"]),
    }


def _cut(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= WORDS_CHARS else text[: WORDS_CHARS - 1] + "…"


def _starred(lb: Logbook, day: str, tiers: Sequence[int] | None) -> dict[str, object]:
    """The stars standing on the day's lines (RFC 0041), to put a starred photo first."""
    with lb.index() as idx:
        marks = reading.crossing(
            [*idx.by_kind(stars.KIND, day, day), *idx.by_kind("keeper", day, day)], tiers
        )
        retracted = idx.superseded("retraction")
    return dict(stars.standing(marks, retracted))


def _starred_first(ids: Sequence[str], starred: Mapping[str, object]) -> list[str]:
    return [i for i in ids if i in starred] + [i for i in ids if i not in starred]


def _money_of_day(lb: Logbook, day: str, rd: reading.Reading) -> dict[str, Any] | None:
    """The day's money slot, or None when the reading's gate does not read tier 3: the transactions
    standing on the day (merchant, amount, currency), and whether a payment source covers it — the day
    lies between the first and last day any source has a transaction line on (`Index.span`) — with
    that last day."""
    if rd.tiers is not None and MONEY_TIER not in rd.tiers:
        return None
    span = _days_span(lb, ledger.KIND, rd.tiers)
    on_day = [line for line in ledger.standing(rd.of_kind(ledger.KIND)) if rd.day_of(line) == day]
    paid = []
    for line in on_day:
        payload = line.get("payload") or {}
        if (payload.get("extra") or {}).get("deleted") is True:
            continue
        # filed by the day only (RFC 0021 rule 5): a date given and `at` that day's local midnight
        midnight = datetime.combine(date.fromisoformat(day), time.min, tzinfo=rd.tz)
        filed = isinstance(payload.get("date"), str) and stays.instant(line.get("at")) == midnight
        paid.append(
            {
                "merchant": str(payload.get("merchant") or "a payment"),
                "amount": payload.get("amount"),
                "currency": str(payload.get("currency") or ""),
                "at": str(line["at"]),
                "by": ledger.BY_DAY if filed else ledger.BY_INSTANT,
                "line": str(line["id"]),
            }
        )
    covered = span is not None and span[0] <= day <= span[1]
    out: dict[str, Any] = {"covered": covered, "lines": paid}
    if not covered:
        out["said"] = NO_PAYMENT
        out["last_covered"] = None if span is None else span[1]
    return out


def _night(
    night: stays.Night | None,
    known: Sequence[named_places.Place],
    given: Mapping[str, str],
    rd: reading.Reading | reading.OwnerTrack,
) -> dict[str, Any]:
    """A night's class and where it was: `in transit` when no stay held it."""
    if night is None or night.stay is None:
        return {"class": IN_TRANSIT, "where": None}
    return {"class": night_class(night, known, given), "where": _night_where(night, rd)}


def night_class(night: stays.Night, known: Sequence[named_places.Place], given: Mapping[str, str]) -> str:
    """The class of a night (`places.class_of`): aboard when aboard an asset, else its named place's
    class, else home by the night rule (`stays.is_home`), else away; `in transit` with no stay."""
    if night.stay is None:
        return IN_TRANSIT
    named = next((p for p in known if p.name == night.stay.place), None)
    return named_places.class_of(named, night.aboard, given, home=night.home)


def _night_where(night: stays.Night, rd: reading.Reading | reading.OwnerTrack) -> str | None:
    stay = night.stay
    if stay is None:
        return None
    if night.aboard is not None:
        asset = rd.assets.get(night.aboard)
        return f"aboard {asset.name if asset else night.aboard}"
    if stay.place:
        return stay.place
    if night.home:
        near = named_places.nearest(stay.lat or 0.0, stay.lon or 0.0, named_places.home_places(rd.places))
        if near is not None:
            return near[0].name
    return None if stay.lat is None or stay.lon is None else f"{stay.lat:.4f},{stay.lon:.4f}"


def _span(within: Mapping[str, Any], rd: reading.Reading) -> str:
    """The part of a row on the day, local: `10:30-16:10`, `00:00-24:00` for a whole day."""
    return day_reader.span_text(within["start"], within["end"], rd.tz, clip=True)


def _at(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


# -- a week: a line per day ------------------------------------------------------------------------------


def week_of_days(
    lb: Logbook,
    key: str,
    first: str,
    last: str,
    airports: Airports | None = None,
    tiers: Sequence[int] | None = None,
) -> dict[str, Any]:
    """A line per day of the ISO week: its night's class and where, and its moments as chips (place,
    time, class, the confirmed by name), from one reading of the week and the day before it."""
    before = (date.fromisoformat(first) - timedelta(days=1)).isoformat()
    rd = reading.read(lb, before, last, airports, tiers)
    given = named_places.classes(lb.root)
    days = []
    tier: int | None = None
    for day in day_range(first, last):
        lines = day_reader.day_lines(rd, date.fromisoformat(day))
        data = day_reader.of_reading(rd, day, None, lines)
        chips = []
        for entry in data["timeline"]:
            if entry["kind"] not in (stays.STAY, day_reader.ABOARD):
                continue
            chips.append(
                {
                    "place": entry.get("where") or "somewhere",
                    "class": _class_of(entry, rd, given),
                    "start_local": entry["start_local"],
                    "end_local": entry["end_local"],
                    "within_day": dict(entry["within_day"]),
                    "span": _span(entry["within_day"], rd),
                    "people": [str(c["name"]) for c in (entry.get("with") or {}).get("confirmed") or ()],
                }
            )
        found = max((int(line.get("tier") or 0) for line in lines), default=None)
        tier = found if tier is None else max(tier, found or 0)
        days.append(
            {
                "day": day,
                "weekday": data["weekday"],
                "night": _night(rd.night_after(day), rd.places, given, rd),
                "moments": chips,
            }
        )
    return {"zoom": WEEK, "week": key, "first": first, "last": last, "days": days, "tier": tier}


# -- a month and a year: nights, photos and signatures from the index ----------------------------------


def _track(
    lb: Logbook, first: str, last: str, airports: Airports | None, tiers: Sequence[int] | None
) -> reading.OwnerTrack:
    """The owner's track of the window through the gate: from the index alone (`reading.owner_track`)
    when the gate reads every location line of it, none when it reads none, and otherwise the stays of
    a reading of the window through the gate (`reading.read`), slower and as exact."""
    track = reading.owner_track(lb, first, last, airports)
    if tiers is None:
        return track
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()  # a night runs into the next day
    with lb.index() as idx:
        found = {
            int(t)
            for (t,) in idx.db.execute(
                "SELECT DISTINCT tier FROM lines WHERE kind = 'location' AND day_local BETWEEN ? AND ?",
                (first, spill),
            )
        }
    if found <= {int(t) for t in tiers}:
        return track
    if not found & {int(t) for t in tiers}:
        return replace(track, stays=[])
    return replace(track, stays=reading.read(lb, first, last, airports, tiers).owner_stays)


def _days_span(lb: Logbook, kind: str, tiers: Sequence[int] | None) -> tuple[str, str] | None:
    """The first and last local day a standing line of `kind` the gate reads is on: the index alone."""
    where = f"kind = ? AND id NOT IN ({RETRACTED})"
    params: list[object] = [kind]
    if tiers is not None:
        where += f" AND tier IN ({','.join('?' * len(tiers))})"
        params += [int(t) for t in tiers]
    with lb.index() as idx:
        found = idx.db.execute(
            f"SELECT min(day_local), max(day_local) FROM lines WHERE {where}", params
        ).fetchone()
    return None if found is None or found[0] is None else (str(found[0]), str(found[1]))


def _nights(
    lb: Logbook, first: str, last: str, airports: Airports | None, tiers: Sequence[int] | None
) -> tuple[reading.OwnerTrack, dict[str, stays.Night]]:
    """The owner's track of the window through the gate (`_track`) and the night after each day."""
    track = _track(lb, first, last, airports, tiers)
    nights = stays.Nights(track.stays, track.tz, track.settings, track.places)
    night_start = track.settings.night[0]
    return track, {
        day: nights.of(track.day_start.night_after(day, night_start)) for day in day_range(first, last)
    }


def _counted(
    idx: Index, kind: str, first: str, last: str, tiers: Sequence[int] | None
) -> tuple[Counter[str], int | None]:
    """The standing lines of `kind` per local day in [first, last] through the gate, and the highest
    tier among them: the index's columns, nothing read from the files."""
    where = f"kind = ? AND day_local BETWEEN ? AND ? AND id NOT IN ({RETRACTED})"
    params: list[object] = [kind, first, last]
    if tiers is not None:
        where += f" AND tier IN ({','.join('?' * len(tiers))})"
        params += [int(t) for t in tiers]
    found = idx.db.execute(
        f"SELECT day_local, count(*), max(tier) FROM lines WHERE {where} GROUP BY day_local", params
    ).fetchall()
    return Counter({str(d): int(n) for d, n, _t in found}), max((int(t) for _d, _n, t in found), default=None)


def _signed(lb: Logbook, tiers: Sequence[int] | None) -> set[str]:
    """The days a standing signature names (RFC 0034); none through a gate that does not read it."""
    with lb.index() as idx:
        found = signing.standing(idx, str(lb.meta.get("owner_id") or "") or None)
    return {day for day, line in found.items() if tiers is None or int(line.get("tier") or 0) in tiers}


def _days_of(
    lb: Logbook,
    first: str,
    last: str,
    airports: Airports | None,
    tiers: Sequence[int] | None,
) -> tuple[list[dict[str, Any]], int | None, reading.OwnerTrack, dict[str, stays.Night]]:
    """Each day of the window: its night's class and where (a day inside the span of the owner's track
    the gate reads; none outside it), its photos, whether it is signed."""
    given = named_places.classes(lb.root)
    track, nights = _nights(lb, first, last, airports, tiers)
    span = _days_span(lb, "location", tiers)
    with lb.index() as idx:
        photos, photo_tier = _counted(idx, "photo", first, last, tiers)
        _logged, location_tier = _counted(idx, "location", first, last, tiers)
    signed = _signed(lb, tiers)
    out = []
    for day in day_range(first, last):
        night = nights[day]
        tracked = span is not None and span[0] <= day <= span[1]
        out.append(
            {
                "day": day,
                "night": _night(night, track.places, given, track) if tracked else None,
                "photos": photos.get(day, 0),
                "signed": day in signed,
            }
        )
    tier = max((t for t in (photo_tier, location_tier) if t is not None), default=None)
    return out, tier, track, nights


def counts(days: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """The nights of `days` by class, in `CLASS_WORDS`' order, a class with none left out."""
    found = Counter(d["night"]["class"] for d in days if d.get("night"))
    return {c: found[c] for c in CLASS_WORDS if found[c]}


def counts_text(found: Mapping[str, int]) -> str:
    """`home 21 · the family's places 4 · aboard 6 · away 3`; `no nights` when there are none."""
    return DOT.join(f"{CLASS_WORDS[c]} {n}" for c, n in found.items()) or "no nights"


def month_of(
    lb: Logbook,
    key: str,
    first: str,
    last: str,
    airports: Airports | None = None,
    tiers: Sequence[int] | None = None,
) -> dict[str, Any]:
    """A calendar of the month: each day its night's class, its photos, signed or open; the nights
    counted by class."""
    days, tier, _track, _nights = _days_of(lb, first, last, airports, tiers)
    return {
        "zoom": MONTH,
        "month": key,
        "first": first,
        "last": last,
        "nights": counts(days),
        "signed": sum(1 for d in days if d["signed"]),
        "photos": sum(int(d["photos"]) for d in days),
        "days": days,
        "tier": tier,
    }


def year_of(
    lb: Logbook, key: str, airports: Airports | None = None, tiers: Sequence[int] | None = None
) -> dict[str, Any]:
    """Twelve months as a strip (each its nights by class, photos and signed days) and the journeys as
    bands: the runs of nights away from home (`trips`' rule: a run whose every night is in transit
    places nothing), each with its first and last day, its nights and the place most of them were at."""
    first, last = window(YEAR, key)
    days, tier, track, nights = _days_of(lb, first, last, airports, tiers)
    months = []
    for n in range(1, 13):
        prefix = f"{key}-{n:02d}"
        of_month = [d for d in days if d["day"].startswith(prefix)]
        months.append(
            {
                "month": prefix,
                "nights": counts(of_month),
                "photos": sum(int(d["photos"]) for d in of_month),
                "signed": sum(1 for d in of_month if d["signed"]),
            }
        )
    return {
        "zoom": YEAR,
        "year": key,
        "nights": counts(days),
        "months": months,
        "journeys": _bands(days, nights, track),
        "tier": tier,
    }


def _bands(
    days: Sequence[Mapping[str, Any]], nights: Mapping[str, stays.Night], track: reading.OwnerTrack
) -> list[dict[str, Any]]:
    if not named_places.home_places(track.places):
        return []  # nothing is away from a home the record does not have
    found: list[dict[str, Any]] = []
    run: list[Mapping[str, Any]] = []
    for d in [*days, None]:
        if d is not None and d.get("night") and not nights[d["day"]].home:
            run.append(d)
            continue
        if run and any(nights[r["day"]].stay is not None for r in run):
            where = Counter(r["night"]["where"] for r in run if r["night"]["where"])
            found.append(
                {
                    "first": run[0]["day"],
                    "last": run[-1]["day"],
                    "nights": len(run),
                    "where": where.most_common(1)[0][0] if where else None,
                    "classes": counts(run),
                    "class": max(counts(run).items(), key=lambda kv: kv[1])[0],  # most of its nights
                }
            )
        run = []
    return found


# -- all years: per place and per vessel ----------------------------------------------------------------


def life_of(
    lb: Logbook, airports: Airports | None = None, tiers: Sequence[int] | None = None
) -> dict[str, Any]:
    """All years: per named place, its visits (a run of the owner's stays there, no stay elsewhere
    between), the years and who was there; per vessel (an asset the owner was aboard), the nights
    aboard, the passages (the runs aboard, `stays.fold`), the years and who was aboard. Who was there is
    the people the record confirms at those stays (the with module's confirmed set, `_who_was_there`),
    names only, the most often there first and never with a count beside a name."""
    whole = _days_span(lb, "location", tiers)
    if whole is None:
        return {
            "zoom": LIFE,
            "first": None,
            "last": None,
            "nights": {},
            "places": [],
            "vessels": [],
            "tier": None,
        }
    first, last = whole
    given = named_places.classes(lb.root)
    days, tier, track, nights = _days_of(lb, first, last, airports, tiers)
    at_place, people_tier = _who_was_there(lb, track, first, last, tiers)
    known = {p.name: p for p in track.places}
    visits: dict[str, list[str]] = {}  # place → the first day of each visit
    previous: str | None = None
    for stay in track.stays:  # an unnamed stay (a walk's stop, a bench) neither starts nor breaks a visit
        if stay.aboard is None and stay.place is None:
            continue
        here = stay.place if stay.aboard is None else None
        if here is not None and here != previous:
            visits.setdefault(here, []).append(track.day_start.day(stay.start).isoformat())
        previous = here
    places_out = [
        {
            "place": name,
            "class": named_places.class_of(known.get(name), None, given),
            "visits": len(found),
            "first": found[0],
            "last": found[-1],
            "years": sorted({d[:4] for d in found}),
            "people": [n for n, _ in at_place.get(name, Counter()).most_common()],
        }
        for name, found in sorted(visits.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    runs: dict[str, list[stays.Segment]] = {}
    for stay in stays.fold(track.stays):
        if stay.aboard is not None:
            runs.setdefault(stay.aboard, []).append(stay)
    aboard_nights = Counter(n.aboard for n in nights.values() if n.aboard is not None)
    vessels = []
    for asset_id, found_runs in sorted(runs.items(), key=lambda kv: (-aboard_nights[kv[0]], kv[0])):
        asset = track.assets.get(asset_id)
        vessels.append(
            {
                "asset": asset_id,
                "name": asset.name if asset else asset_id,
                "nights": aboard_nights[asset_id],
                "passages": len(found_runs),
                "first": track.day_start.day(found_runs[0].start).isoformat(),
                "years": sorted({track.day_start.day(s.start).isoformat()[:4] for s in found_runs}),
                "people": [n for n, _ in at_place.get(f"aboard {asset_id}", Counter()).most_common()],
            }
        )
    return {
        "zoom": LIFE,
        "first": first,
        "last": last,
        "nights": counts(days),
        "places": places_out,
        "vessels": vessels,
        "tier": max((t for t in (tier, people_tier) if t is not None), default=None),
    }


def _who_was_there(
    lb: Logbook, track: reading.OwnerTrack, first: str, last: str, tiers: Sequence[int] | None
) -> tuple[dict[str, Counter[str]], int | None]:
    """Who the with module confirms at each of the owner's stays (`present.company`, the rule the
    Day and `people` read by), by where: a named place's name or `aboard <asset id>`, each person by
    name and how often, for an order and never to be shown. Only the kinds that can confirm someone
    are read (`present.EVIDENCE_KINDS` but photos, whose faces only propose), standing and through the
    gate, streamed from the index: never the record's messages and mail, which place nobody. And the
    highest tier among the lines that confirmed someone."""
    spill = (date.fromisoformat(last) + timedelta(days=1)).isoformat()  # a stay's night runs into it
    with lb.index() as idx:
        marks = idx.retractions()
        resolutions = reading.crossing(idx.resolutions(), tiers)
        retracted = frozenset(retractions(marks))
        lines: list[Line] = []
        for kind in CONFIRMING:
            superseded = idx.superseded(kind)
            lines.extend(
                line
                for line in reading.crossing(idx.of_kind(kind, first, spill), tiers)
                if str(line.get("id")) not in retracted and str(line.get("id")) not in superseded
            )
    identities = resolve.identities_from([*marks, *resolutions])
    owner = present.owner_of(
        str(lb.meta.get("owner_id") or ""),
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    tiers_of = {str(line["id"]): int(line.get("tier") or 0) for line in lines}
    near = present.Evidence(lines, track.tz)
    found: dict[str, Counter[str]] = {}
    tier: int | None = None
    for stay in track.stays:
        if stay.place is None and stay.aboard is None:
            continue  # an unnamed place has no row of its own here
        where = f"aboard {stay.aboard}" if stay.aboard is not None else str(stay.place)
        for c in present.company(stay, near.near(stay), identities, track.places, owner):
            if c.status != present.CONFIRMED or c.person is None:
                continue
            found.setdefault(where, Counter())[c.name] += 1
            tier = max([*(tiers_of.get(i, 0) for i in c.lines), *([tier] if tier is not None else [])])
    return found, tier


# -- the text: `logbook show timeline` without --json ---------------------------------------------------


def rows(data: Mapping[str, Any]) -> Iterator[str]:
    """The timeline as text, one line per row, as the page's folded lines read."""
    zoom = data["zoom"]
    if zoom == DAY:
        night = data["night"]
        yield f"{data['day']}  {data['weekday']}{DOT}night {night['class']}" + (
            f" ({night['where']})" if night.get("where") else ""
        )
        if "money" in data and not data["money"]["covered"]:
            yield f"  {money_gap_text(data['money'])}"
        for item in data["items"]:
            yield f"  {item_text(item)}"
        if not data["items"]:
            yield "  no moment: no stay on this day"
    elif zoom == WEEK:
        yield f"{data['week']}  {data['first']} {day_reader.EN_DASH} {data['last']}"
        for d in data["days"]:
            chips = ", ".join(f"{c['place']} {c['span']}" for c in d["moments"])
            yield f"  {d['day']} {d['weekday'][:3]}  night {d['night']['class']}{DOT}{chips or 'no moment'}"
    elif zoom == MONTH:
        yield f"{data['month']}  {counts_text(data['nights'])}{DOT}{tally_text(data)}"
        for d in data["days"]:
            night = d["night"]["class"] if d["night"] else "no track"
            yield f"  {d['day']}  {night}{DOT}{_plural(d['photos'], 'photo')}{DOT}{signed_text(d)}"
    elif zoom == YEAR:
        yield f"{data['year']}  {counts_text(data['nights'])}"
        for m in data["months"]:
            yield f"  {m['month']}  {counts_text(m['nights'])}{DOT}{tally_text(m)}"
        for j in data["journeys"]:
            yield f"  journey  {j['first']} {day_reader.EN_DASH} {j['last']}{DOT}{j['where'] or 'away'}"
    else:
        span = f"{data['first']} {day_reader.EN_DASH} {data['last']}"
        yield f"all years  {span}{DOT}{counts_text(data['nights'])}"
        for p in data["places"]:
            yield f"  {place_text(p)}" + (f"{DOT}with {', '.join(p['people'])}" if p["people"] else "")
        for v in data["vessels"]:
            yield f"  {vessel_text(v)}" + (f"{DOT}with {', '.join(v['people'])}" if v["people"] else "")


def item_text(item: Mapping[str, Any]) -> str:
    """One item of a day folded to one line: a moment as `Saltbu · 19:30-22:40 · 6 photos · 2
    conversations · with Ola, Kari, Per?`, the people last and after the word `with`, so no number
    ever stands beside a name; a move as its span, mode and distance."""
    span = item["span"]
    if item["kind"] == day_reader.FLIGHT:  # a word first: a row under a name never opens on a number
        return DOT.join(
            p for p in (f"flight {item['flight']}".rstrip(), ARROWS.join(item["airports"]), span) if p
        )
    if item["kind"] == day_reader.GAP:
        return f"a gap in the track{DOT}{span}"
    if item["kind"] != "moment":
        far = day_reader.distance_text(item["distance_m"]) if item.get("distance_m") else ""
        return DOT.join(p for p in (item.get("mode") or "move", span, far) if p)
    parts = [item["place"], span]
    if item["photos"]:
        parts.append(_plural(len(item["photos"]), "photo"))
    talk = len(item["during"]["messages"]) + len(item["during"]["agents"])
    if talk:
        parts.append(_plural(talk, "conversation"))
    for kind, noun in (("calls", "call"), ("mail", "mail thread"), ("notes", "note")):
        if item["during"][kind]:
            parts.append(_plural(len(item["during"][kind]), noun))
    if item.get("money", {}).get("paid"):
        parts.append("paid " + ", ".join(t["merchant"] for t in item["money"]["paid"]))
    names = [p["name"] for p in item["people"]["confirmed"]]
    names += [f"{p['name']}?" for p in item["people"]["proposed"]]
    if names:
        parts.append("with " + ", ".join(names))
    return DOT.join(parts)


def conversation_text(c: Mapping[str, Any]) -> str:
    """A conversation during a moment: who and where, `Kari Nordmann · iMessage`; never how many."""
    return f"{c['with']}{DOT}{c['network']}" + (f"{DOT}an agent" if c.get("agent") else "")


def call_text(c: Mapping[str, Any]) -> str:
    """A call during a moment: who and which way, `Ola Nordmann · call out`; never how long."""
    outgoing = c.get("direction") == "outgoing"
    way = (
        ("call out" if outgoing else "call in")
        if c.get("answered")
        else ("no answer" if outgoing else "missed")
    )
    return f"{c['who']}{DOT}{way}"


def tally_text(found: Mapping[str, Any]) -> str:
    """A month's photos and signed days: `17 photos · 3 signed`."""
    return f"{_plural(int(found['photos']), 'photo')}{DOT}{found['signed']} signed"


def signed_text(day: Mapping[str, Any]) -> str:
    return "signed" if day["signed"] else "open"


def money_gap_text(money: Mapping[str, Any]) -> str:
    last = money.get("last_covered")
    return f"{NO_PAYMENT}" + (f"; the last day one covers is {last}" if last else "; no source has a payment")


def place_text(p: Mapping[str, Any]) -> str:
    """`Saltbu · 23 visits since 2014`."""
    return f"{p['place']}{DOT}{_plural(p['visits'], 'visit')} since {p['first'][:4]}"


def vessel_text(v: Mapping[str, Any]) -> str:
    """`aboard Solvind · 41 nights on 9 passages`."""
    return f"aboard {v['name']}{DOT}{_plural(v['nights'], 'night')} on {_plural(v['passages'], 'passage')}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}{'' if n == 1 else 's'}"
