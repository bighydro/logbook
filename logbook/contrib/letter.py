"""`logbook export letter FROM TO`: a range of signed days read back, one HTML file to print or hand to
someone and the same content as Markdown (docs/letter.md).

**What is in it.** A front page in the owner's words (`--front FILE`, verbatim), then one page per unit
of the range (`--unit`: a day, an ISO week, a calendar month, or a journey, the trip reader's run of
nights away). Per unit: the story of the unit's standing draft when the dream wrote one, in pencil and
marked as a model's, with the model's name (only its story part, `STORY_PARTS`, only the segments that
name their evidence, and only when every day the draft is about goes in); the owner's reflection of each
day in her words, in ink (one through the door is shown with its source, as the Day shows it); the
starred lines with the star's note, and the starred photos, embedded when the record's own store holds a
JPEG or PNG (`day_photos.opened`) that, stripped of what the camera wrote beside the pixels (`strip`:
EXIF and its position, XMP, comments), is at most `PHOTO_MAX_BYTES`; named otherwise, and never copied
beside the letter; the goal reviews standing on its days (`goals.reviews_on`); the people confirmed or
stated present, by name and never with a number beside it; the places stayed at and the flights, in
words. The month card (`--unit month --card`) is one page per month and nothing else: the starred photo
of each starred day as a grid, how many days were signed, the goals kept (reviewed `done` in the month),
the people, and one sentence of the owner's, the first of the longest signed reflection of the month.

**The crossing.** A letter leaves the record, so it is a crossing like every export (ADR 0016): the
`letter` entry of `policy/crossing.json`, read and never written here, held against today; a record
whose file names none, or whose entry has expired, lets nothing leave and says so in one sentence.
Its ceiling gates every line the letter reads (`reading.read`, the drafts, the stars, the goals, the
name overlay), and tier 3 never goes unless the owner types `--tier 1,2,3` under an entry of 3. A
draft also follows the `dream` entry it was written under (`drafts.allowed`), as on the Day. Only
signed days go in (RFC 0034) unless `--unsigned`. `manifest.json` says what went in and what stayed
home, counts only, and names the person the letter is for (`--to`). Then one `crossing/v1` line
(RFC 0011), destination `letter`, says it left: the only write to the record, through
`Logbook.append`, under one hold of the writer lock with the head read again first.

**The page.** One self-contained document: one inline stylesheet, no script, nothing fetched (a
photo is a `data:` URI), system fonts only, a Content-Security-Policy that loads nothing. Set for
print in the browser: `@page` A5 or US letter (`--paper`), a page break before each unit, the three
hands of RFC 0043 — the owner's words in a serif (ink), the record in the system face, numbers in
mono — and the model's story apart in pencil. It reads at phone width first (390 px) and has no
control to touch.

**Cost.** One reading per 31 days of the range (`reading.read`, located through the index; a journey
letter reads its range once, as the trip reader needs it whole), and per kind the letter quotes one
indexed query of the range; nothing scans the log. The drafts, the goals and the name overlay are read
whole, as the Day reads them: one line per unit dreamed, per goal, per name. A letter with no page (no
signed day in the range) is refused before anything is written."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from html import escape
from pathlib import Path
from typing import Any

from .. import __version__
from ..core import crossing, day_start, drafts, goals, notes, policy, reading, signing, stars, stays
from ..core import day as day_reader
from ..core import trips as trip_reader
from ..core.chain import Line
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.reading import Reading
from ..core.store import HEAD_MOVED, HeadMoved, Logbook, retractions, uuid7
from . import day_photos, journeys, print_layout

DESTINATION = "letter"
SCHEMA = "letter/v1"  # the manifest's schema: an earlier folder of this command is replaced
SCHEMAS = frozenset({SCHEMA})
MANIFEST_FILE = crossing.MANIFEST_FILE
HTML_FILE, MARKDOWN_FILE = "letter.html", "letter.md"
DAY, JOURNEY, WEEK, MONTH = "day", "journey", "week", "month"
UNITS = (DAY, JOURNEY, WEEK, MONTH)
PAPERS = {"a5": "A5", "letter": "letter"}  # `--paper` → the `@page` size
TIERS = (1, 2)  # what a letter carries under the highest entry unless the owner types tier 3
PHOTO_MAX_BYTES = 256 * 1024  # a photo larger than this is named, never embedded (docs/letter.md)
CHUNK_DAYS = 31  # days per reading, as `days` reads a window
# a draft's story: a day's `story` part (RFC 0043 §4.3, dream-day/4) or its `day` part (dream-day/3)
STORY_PARTS = {DAY: ("story", "day"), JOURNEY: ("journey",), WEEK: ("time", "personal")}
KEPT = "done"  # a goal kept: reviewed done
TO_TIER = 2  # the crossing line's tier when `--to` names the person: a name is tier 2
OWN_HAND = ("reflect", "manual")  # a reflection the owner wrote: `day reflect`, the Day page; set in ink
EMBEDDED = ("image/jpeg", "image/png")  # what the letter can strip of its metadata and embed
MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)
EN_DASH, ARROW, DOT = "\u2013", "\u2192", " \u00b7 "
SENTENCE = re.compile(r".+?[.!?\u2026](?=\s|$)|.+$", re.S)  # a sentence: up to its end mark, or the rest
COORDINATES = re.compile(r"^-?\d+\.\d+,-?\d+\.\d+")  # a stay nothing names: no words to give it
CSP = "default-src 'none'; img-src data:; style-src 'unsafe-inline'"


class LetterError(ValueError):
    """A request the policy or the record refuses; the message is one sentence and says why."""


def now() -> datetime:
    """The read time: `as_of`, and the crossing line's `at`. Tests replace it."""
    return datetime.now(UTC)


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# -- the request -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """One run, checked against the policy: the `letter` entry as it counts today, the local days
    `[first, last]`, the unit, the tiers, whether only signed days go in, and what the owner gave."""

    entry: policy.Ceiling
    first: str
    last: str
    unit: str
    tiers: tuple[int, ...]
    signed_only: bool
    as_of: str
    title: str
    paper: str = "a5"
    card: bool = False
    to: str | None = None
    front: str | None = None

    @property
    def version(self) -> str:
        return policy.version(self.entry)


def entry(root: Path) -> policy.Ceiling:
    """The `letter` entry of the policy, held against today; refused in one sentence when the file
    names none or the entry has expired, saying what to write."""
    path = policy.policy_path(root)
    try:
        if DESTINATION not in policy.read(root):
            raise LetterError(
                f"{path} names no {json.dumps(DESTINATION)} entry, so no letter leaves; add"
                f' {{"{DESTINATION}": {{"max_tier": 2}}}} to it to allow the export'
            )
        found = next(c for c in policy.ceilings(root) if c.destination == DESTINATION)
    except policy.PolicyError as e:
        raise LetterError(str(e)) from e
    if found.expired and found.until is not None:
        raise LetterError(
            f"{path}: the {json.dumps(DESTINATION)} entry expired on {found.until.isoformat()} and counts"
            " as max_tier 0, so no letter leaves; write a new until there or remove the entry"
        )
    return found


def request(
    lb: Logbook,
    first: str | None,
    last: str | None,
    unit: str | None = None,
    tiers: str | None = None,
    unsigned: bool = False,
    to: str | None = None,
    title: str | None = None,
    front: str | Path | None = None,
    paper: str | None = None,
    card: bool = False,
    at: datetime | None = None,
) -> Request:
    """Check the run: the range, the unit, the paper, the front page, then the `letter` entry and the
    tiers under it. Nothing is read from the record but the policy file."""
    if first is None or last is None:
        raise LetterError("export letter takes two days, FROM TO, each YYYY-MM-DD")
    try:
        a, b = parse_day(first), parse_day(last)
    except ValueError as e:
        raise LetterError(f"export letter takes FROM TO as days, YYYY-MM-DD: {e}") from None
    if a > b:
        raise LetterError(f"FROM {a.isoformat()} is after TO {b.isoformat()}; the range runs forwards")
    unit = unit or DAY
    if unit not in UNITS:
        raise LetterError(f"--unit is one of {', '.join(UNITS)}, not {unit!r}")
    if card and unit != MONTH:
        raise LetterError("--card is the month card: it takes --unit month")
    paper = (paper or "a5").lower()
    if paper not in PAPERS:
        raise LetterError(f"--paper is a5 or letter, not {paper!r}")
    words = None
    if front is not None:
        try:
            words = Path(front).expanduser().read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise LetterError(
                f"--front {front} cannot be read: {getattr(e, 'strerror', None) or e}"
            ) from None
    for_whom = " ".join((to or "").split()) or None
    found = entry(lb.root)
    if tiers is None:
        crossed = tuple(t for t in TIERS if t <= found.max_tier)
    else:
        try:
            crossed = crossing.parse_tiers(tiers)
        except crossing.CrossingError as e:
            raise LetterError(str(e)) from None
        if max(crossed) > found.max_tier:
            raise LetterError(
                f"--tier {tiers} is above the {json.dumps(DESTINATION)} entry of"
                f" {policy.policy_path(lb.root)}, which allows max_tier {found.max_tier};"
                " raise it there if that is what you want"
            )
    read_at = (at or now()).astimezone(UTC).replace(microsecond=0)
    heading = " ".join((title or "").split()) or span_words(a, b)
    return Request(
        found,
        a.isoformat(),
        b.isoformat(),
        unit,
        crossed,
        not unsigned,
        stamp(read_at),
        heading,
        paper,
        card,
        for_whom,
        words,
    )


# -- words for days ------------------------------------------------------------------------------------


def day_words(d: date) -> str:
    """`Monday 8 June 2026`."""
    return f"{day_reader.WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


def span_words(a: date, b: date) -> str:
    """`8 June 2026`; a span with an en dash between its ends, the month and the year said once where
    the ends share them: `8 \u2013 21 June 2026`, `29 June \u2013 5 July 2026`."""
    if a == b:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year}"
    if a.year != b.year:
        return f"{a.day} {MONTHS[a.month - 1]} {a.year} {EN_DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    if a.month != b.month:
        return f"{a.day} {MONTHS[a.month - 1]} {EN_DASH} {b.day} {MONTHS[b.month - 1]} {b.year}"
    return f"{a.day} {EN_DASH} {b.day} {MONTHS[a.month - 1]} {a.year}"


def first_sentence(text: str) -> str:
    """The first sentence of `text`: up to and with its first `.`, `!`, `?` or `…` followed by a space
    or the end, else the whole first paragraph."""
    paragraph = next((p.strip() for p in text.splitlines() if p.strip()), "")
    found = SENTENCE.match(paragraph)
    return found.group(0).strip() if found else paragraph


# -- what the letter holds ------------------------------------------------------------------------------


@dataclass
class Photo:
    day: str
    name: str
    media_type: str | None = None
    data: bytes | None = None  # None: named, not embedded

    def uri(self) -> str | None:
        if self.data is None or self.media_type is None:
            return None
        return f"data:{self.media_type};base64,{base64.b64encode(self.data).decode('ascii')}"


@dataclass
class Story:
    model: str
    segments: list[str]


@dataclass
class Unit:
    """One page of the letter: its key (a day, `2026-W25`, `2026-06`, a journey's id), its heading and
    the days of the range it holds that went in, and what those days carry."""

    key: str
    heading: str
    days: list[str] = field(default_factory=list)
    span: list[str] = field(default_factory=list)  # every day the unit is about, in the range or not
    story: Story | None = None
    reflections: list[dict[str, str]] = field(default_factory=list)  # {day, text, source}
    starred: list[dict[str, Any]] = field(default_factory=list)  # {day, kind, title, note}
    photos: list[Photo] = field(default_factory=list)
    reviews: list[dict[str, Any]] = field(default_factory=list)  # {day, goal, disposition, period, note}
    people: list[str] = field(default_factory=list)
    places: list[str] = field(default_factory=list)
    flights: list[str] = field(default_factory=list)
    signed_days: set[str] = field(default_factory=set)  # those of its days that are signed

    @property
    def signed(self) -> int:
        """How many of its days are signed: the card says it."""
        return len(self.signed_days)


@dataclass
class Built:
    """What one run hands over: the units in order, and what stayed home, counted."""

    units: list[Unit]
    days_in: int
    held: Counter[str]
    crossed: dict[str, tuple[int, str]]  # the lines quoted or shown → (tier, kind)
    above: set[str]  # the lines of the parts' kinds held back above the ceiling
    unsigned: set[str]  # the lines of the parts' kinds on the days left out unsigned
    resolutions: int

    def counts(self) -> dict[str, Any]:
        photos = [p for u in self.units for p in u.photos]
        return {
            "units": len(self.units),
            "days": self.days_in,
            "reflections": sum(len(u.reflections) for u in self.units),
            "stories": sum(1 for u in self.units if u.story is not None),
            "starred": sum(len(u.starred) for u in self.units),
            "photos": len(photos),
            "reviews": sum(len(u.reviews) for u in self.units),
        }

    def photos(self) -> dict[str, int]:
        found = [p for u in self.units for p in u.photos]
        return {
            "embedded": sum(1 for p in found if p.data is not None),
            "named": sum(1 for p in found if p.data is None),
        }

    def held_back(self) -> dict[str, int]:
        return {"above_tier": len(self.above), **dict(sorted(self.held.items()))}

    def lines(self) -> dict[str, Any]:
        """RFC 0011's `counts`, in the crossing's shape: `crossed` the lines the letter quotes or shows,
        `held_back` the lines of those kinds the gate kept home; the name overlay as `resolutions`. No
        file of the store is copied beside it: a photo inside the page is counted under `included`."""
        held = self.above | self.unsigned
        photos = [p for u in self.units for p in u.photos if p.data is not None]
        return {
            "logged": len(self.crossed) + len(held),
            "crossed": len(self.crossed),
            "held_back": len(held),
            "held_back_unsigned": len(self.unsigned),
            "by_tier": {
                str(t): sum(1 for tier, _ in self.crossed.values() if tier == t) for t in policy.TIERS
            },
            "by_kind": dict(sorted(Counter(kind for _, kind in self.crossed.values()).items())),
            "resolutions": self.resolutions,
            "attachments": {
                "included": len(photos),
                "bytes": sum(len(p.data or b"") for p in photos),
                "missing": 0,
            },
        }


QUOTED = ("note", stars.KIND, "keeper", "photo", goals.REVIEW, drafts.KIND, "flight")  # the parts' kinds


def build(lb: Logbook, req: Request, airports: Airports | None = None) -> Built:
    """Read the range through the gate and compose the units. Writes nothing."""
    airports = airports or Airports.load()
    meta = lb.meta
    owner, tz = str(meta["owner_id"]), str(meta["timezone"])
    days = day_start.of(meta)
    gate = req.tiers
    window = _days(req.first, req.last)
    held: Counter[str] = Counter()
    crossed: dict[str, tuple[int, str]] = {}
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        signed = signing.gate(idx, owner)[0]
        every_draft = idx.by_kind(drafts.KIND)
        goal_lines = reading.crossing(idx.by_kind(goals.KIND), gate)
        names, resolutions = _names(idx.resolutions(), retracted, gate)
        quoted = [line for kind in QUOTED for line in idx.by_kind(kind, req.first, req.last)]
    included = [d for d in window if not req.signed_only or d in signed]
    held["unsigned_days"] = len(window) - len(included)
    allowed = drafts.allowed(lb.root)
    per_day: dict[str, dict[str, Any]] = {}

    def take(rd: Reading, chunk: Sequence[str], wanted: set[str]) -> None:
        by_day: dict[str, list[Line]] = {}
        for line in rd.lines:
            at = str(line.get("at") or "")
            if at:
                by_day.setdefault(days.day_of(at), []).append(line)
        for d in chunk:
            if d in wanted:
                per_day[d] = _day(rd, d, by_day.get(d, []), names, goal_lines, retracted, tz, held, crossed)

    if req.unit == JOURNEY:  # the trip reader needs the range whole: one reading, the journeys first
        rd = reading.read(lb, _before(window[0]), window[-1], airports, gate)
        units = _units(req, included, trip_reader.trips(rd)[0], lb, retracted, days)
        inside = {d for u in units for d in u.days}
        held["outside_journey_days"] = len(included) - len(inside)
        take(rd, window, inside)
    else:
        units = _units(req, included, [], lb, retracted, days)
        inside = set(included)
        for start in range(0, len(window), CHUNK_DAYS):
            chunk = window[start : start + CHUNK_DAYS]
            if inside.intersection(chunk):
                take(reading.read(lb, _before(chunk[0]), chunk[-1], airports, gate), chunk, inside)
    above = {
        str(line["id"])
        for line in quoted
        if int(line.get("tier", 0)) not in gate and days.day_of(str(line["at"])) in inside
    }
    unsigned = {str(line["id"]) for line in quoted if days.day_of(str(line["at"])) not in set(included)}

    starred = stars.listed(lb, req.first, req.last, gate)
    with lb.index() as idx:
        lines = idx.by_ids(s["line"] for s in starred if s["day"] in inside)
    for s in starred:
        marked = lines.get(s["line"])
        if s["day"] not in inside or marked is None:
            continue
        crossed[s["star"]] = (int(marked.get("tier", 0)), str(stars.KIND))
        crossed[s["line"]] = (int(marked.get("tier", 0)), str(marked.get("kind")))
        if s["kind"] == day_photos.KIND:
            per_day[s["day"]]["photos"].append(_photo(lb, marked, s["day"], held))
        else:
            words = (marked.get("payload") or {}).get("text") if s["kind"] == "note" else None
            title = " ".join(words.split()) if isinstance(words, str) and words.strip() else s["title"]
            per_day[s["day"]]["starred"].append(
                {"day": s["day"], "kind": s["kind"], "title": title, "note": s["note"]}
            )

    signed_in = {d for d in included if d in signed}
    for u in units:
        if req.unit == JOURNEY:  # a journey's heading names the places of its days that go in
            u.heading = u.heading.replace(JOURNEY_ROUTE, _route(u, per_day))
        u.signed_days = {d for d in u.days if d in signed_in}
        for d in u.days:
            got = per_day[d]
            u.reflections += got["reflections"]
            u.starred += got["starred"]
            u.photos += got["photos"]
            u.reviews += got["reviews"]
            u.people += [n for n in got["people"] if n not in u.people]
            u.places += [p for p in got["places"] if not u.places or u.places[-1] != p]
            u.flights += got["flights"]
        if req.card:
            continue
        if not set(u.span) <= set(included):  # a draft of the unit rests on days that do not go in
            held["stories_beyond_the_letter"] += 1
            continue
        u.story = _story(req, u, every_draft, retracted, allowed, held, crossed)
    return Built(units, sum(len(u.days) for u in units), held, crossed, above, unsigned, resolutions)


def _before(day: str) -> str:
    """The day before `day`: a reading starts there, so the first day has its night before."""
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def _days(first: str, last: str) -> list[str]:
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    return [(a + timedelta(days=n)).isoformat() for n in range((b - a).days + 1)]


def _names(
    found: Iterable[Line], retracted: Mapping[str, Any], gate: Sequence[int]
) -> tuple[dict[str, str], int]:
    """The name overlay under the ceiling: each person's label from the latest resolution line the gate
    lets through, by the entity id the readers carry; and how many such lines there were. A name only a
    line above the ceiling gives stays home, and its person with it."""
    names: dict[str, str] = {}
    n = 0
    for line in sorted(found, key=lambda line: int(line["seq"])):
        if str(line["id"]) in retracted or int(line.get("tier", 0)) not in gate:
            continue
        payload = line.get("payload") or {}
        entity, label = payload.get("entity"), payload.get("label")
        if (
            isinstance(entity, dict)
            and entity.get("type") == "person"
            and isinstance(label, str)
            and label.strip()
        ):
            names[str(entity.get("id"))] = label.strip()
            n += 1
    return names, n


def _day(
    rd: Reading,
    d: str,
    lines: Sequence[Line],
    names: Mapping[str, str],
    goal_lines: Sequence[Line],
    retracted: Mapping[str, Any],
    tz: str,
    held: Counter[str],
    crossed: dict[str, tuple[int, str]],
) -> dict[str, Any]:
    """One day's parts from a reading through the gate: the reflection, the reviews, the people, the
    places and the flights. The stars and the story are read beside it."""
    data = day_reader.of_reading(rd, d, None, lines)
    tier_of = {str(line["id"]): int(line.get("tier", 0)) for line in lines}
    reflected = notes.standing(lines, notes.REFLECTION, retracted)
    for line in reflected[-1:]:
        crossed[str(line["id"])] = (int(line["tier"]), "note")
    reviews = goals.reviews_on(d, lines, goal_lines, retracted, tz)
    for row in reviews:
        crossed[str(row["line"])] = (tier_of.get(str(row["line"]), goals.TIER), goals.REVIEW)
    people: list[str] = []
    for c in day_reader.company_of_day(
        {"timeline": data["timeline"], "stated": day_reader.stated_of(lines, retracted)}
    ):
        name = names.get(str(c.get("person"))) if c.get("person") else None
        if name is None and c.get("stated"):
            name = str(c.get("name") or "").strip() or None
        if name is None:
            held["people_unnamed"] += 1
        elif name not in people:
            people.append(name)
    places: list[str] = []
    for entry in data["timeline"]:
        if entry["kind"] == day_reader.FLIGHT:
            continue
        where = _place_words(entry)
        if where is not None and (not places or places[-1] != where):
            places.append(where)
    flights = []
    for f in data["flights"]:
        crossed[str(f["line"])] = (tier_of.get(str(f["line"]), 1), "flight")
        number = " ".join(str(x) for x in (f.get("carrier"), f.get("number")) if x)
        route = f"{f.get('from') or '?'} {ARROW} {f.get('to') or '?'}"
        flights.append(f"{number} {route}".strip())
    return {
        "reflections": [
            {
                "day": d,
                "text": str((line.get("payload") or {}).get("text") or ""),
                "source": str(line.get("source")),
            }
            for line in reflected[-1:]
        ],
        "reviews": [
            {
                "day": d,
                "goal": row.get("goal_text") or "",
                "disposition": row.get("disposition"),
                "period": row.get("period"),
                "note": row.get("note"),
            }
            for row in reviews
        ],
        "people": people,
        "places": places,
        "flights": flights,
        "starred": [],
        "photos": [],
    }


def _place_words(entry: Mapping[str, Any]) -> str | None:
    """A stay in words: its named place, the asset it was aboard, else what names the point (`near
    Cabin`, `Zurich`); a move, or a stay nothing names, is no place."""
    if entry.get("kind") not in (stays.STAY, day_reader.ABOARD):
        return None
    if entry.get("place"):
        return str(entry["place"])
    where = trip_reader.route_name(str(entry.get("where") or ""))
    if not where or COORDINATES.match(where):
        return None
    return re.sub(r", \d+(\.\d+)? km$", "", where)


def _photo(lb: Logbook, line: Line, d: str, held: Counter[str]) -> Photo:
    name = stars.title(line)
    found = day_photos.opened(lb, line)
    if found is None:
        held["photos_not_here"] += 1
        return Photo(d, name)
    stored, data = found
    plain = strip(data, stored.media_type)
    if plain is None:
        held["photos_not_stripped"] += 1
        return Photo(d, name)
    if len(plain) > PHOTO_MAX_BYTES:
        held["photos_over_cap"] += 1
        return Photo(d, name)
    return Photo(d, name, stored.media_type, plain)


JPEG_KEPT = frozenset({0xE0})  # of the APPn segments, only JFIF's; EXIF, XMP, ICC and the rest go
PNG_KEPT = frozenset({b"IHDR", b"PLTE", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"IDAT", b"IEND"})


def strip(data: bytes, media_type: str) -> bytes | None:
    """The photo's pixels with what the camera wrote beside them taken out: a JPEG without its APP1 to
    APP15 segments (EXIF and its position, XMP, the maker's notes) and comments, a PNG with only the
    chunks that draw it (no text, no `eXIf`, no time). None for any other type, or for bytes that are
    not the shape their type says: such a photo is named, never embedded. No pixel is changed."""
    if media_type == "image/jpeg":
        return _strip_jpeg(data)
    if media_type == "image/png":
        return _strip_png(data)
    return None


def _strip_jpeg(data: bytes) -> bytes | None:
    if not data.startswith(b"\xff\xd8"):
        return None
    out, at = bytearray(b"\xff\xd8"), 2
    while at + 4 <= len(data):
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if marker == 0xDA:  # start of scan: the image data to the end, as it is
            return bytes(out + data[at:])
        size = int.from_bytes(data[at + 2 : at + 4], "big")
        if size < 2 or at + 2 + size > len(data):
            return None
        if not (0xE1 <= marker <= 0xEF or marker == 0xFE):  # APP1-APP15 and COM are what is left out
            out += data[at : at + 2 + size]
        at += 2 + size
    return None


def _strip_png(data: bytes) -> bytes | None:
    signature = b"\x89PNG\r\n\x1a\n"
    if not data.startswith(signature):
        return None
    out, at = bytearray(signature), len(signature)
    while at + 12 <= len(data):
        size = int.from_bytes(data[at : at + 4], "big")
        kind = data[at + 4 : at + 8]
        end = at + 12 + size
        if end > len(data):
            return None
        if kind in PNG_KEPT:
            out += data[at:end]
        if kind == b"IEND":
            return bytes(out)
        at = end
    return None


def _units(
    req: Request,
    included: Sequence[str],
    found_trips: Sequence[trip_reader.Trip],
    lb: Logbook,
    retracted: Mapping[str, Any],
    days: day_start.DayStart,
) -> list[Unit]:
    if req.unit == DAY:
        return [Unit(d, day_words(date.fromisoformat(d)), [d], [d]) for d in included]
    if req.unit in (WEEK, MONTH):
        grouped: dict[str, Unit] = {}
        for d in included:
            when = date.fromisoformat(d)
            if req.unit == WEEK:
                year, week, _ = when.isocalendar()
                key = f"{year}-W{week:02d}"
            else:
                key = f"{when.year}-{when.month:02d}"
            grouped.setdefault(key, Unit(key, "")).days.append(d)
        for key, u in grouped.items():
            a, b = date.fromisoformat(u.days[0]), date.fromisoformat(u.days[-1])
            if req.unit == WEEK:
                u.heading = f"Week {int(key[-2:])}{DOT}{span_words(a, b)}"
                monday = a - timedelta(days=a.weekday())
                u.span = _days(monday.isoformat(), (monday + timedelta(days=6)).isoformat())
            else:
                u.heading = f"{MONTHS[a.month - 1]} {a.year}"
                last = (a.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
                u.span = _days(a.replace(day=1).isoformat(), last.isoformat())
        return list(grouped.values())
    with lb.index() as idx:
        named = journeys.names_in(
            reading.crossing(idx.by_kind(notes.KIND, req.first, req.last), req.tiers), frozenset(retracted)
        )
    out = []
    inside = set(included)
    taken: set[str] = set()
    for trip in found_trips:
        held = [d for d in included if trip.start <= d <= trip.until and d not in taken]
        if not held:
            continue
        taken.update(held)
        name = journeys.name_of(trip, [n for n in named if days.day_of(str(n["at"])) in inside], days)
        title = name.text if name is not None else JOURNEY_ROUTE
        a, b = date.fromisoformat(held[0]), date.fromisoformat(held[-1])
        out.append(Unit(trip.id, f"{title}{DOT}{span_words(a, b)}", held, _days(trip.start, trip.until)))
    return out


JOURNEY_ROUTE = "\x00route\x00"  # where a journey's heading names its places, once its days are read


def _route(u: Unit, per_day: Mapping[str, Mapping[str, Any]]) -> str:
    """A journey with no name, named by the places of its days that go in: `Home → Zurich → Home`."""
    places = [p for d in u.days for p in per_day[d]["places"]]
    return f" {ARROW} ".join(dict.fromkeys(places)) or "A journey"


def _story(
    req: Request,
    u: Unit,
    every_draft: Sequence[Line],
    retracted: Mapping[str, Any],
    allowed: drafts.Allowed,
    held: Counter[str],
    crossed: dict[str, tuple[int, str]],
) -> Story | None:
    """The story of the unit's standing draft, by the Day's rule (`drafts.through`: the gate and the
    `dream` entry): its story part's segments that name their evidence; None when the dream wrote none
    or none may go."""
    if req.unit == DAY:
        found = drafts.by_day(every_draft, retracted).get(u.key, [])
    else:
        found = drafts.by_unit(every_draft, retracted, req.unit).get(u.key, [])
    if not found:
        return None
    gated = [line for line in found if int(line.get("tier", 0)) in req.tiers]
    if not gated:
        held["drafts_above_tier"] += 1
        return None
    shown, _ = drafts.through(gated, None, allowed)
    latest = drafts.standing(shown)
    if latest is None:
        held["drafts_held_by_the_dream_entry"] += 1
        return None
    payload = latest.get("payload") or {}
    segments = [s for s in payload.get("segments") or [] if isinstance(s, dict)]
    parts = (payload.get("extra") or {}).get("parts") if isinstance(payload.get("extra"), dict) else None
    story_parts = STORY_PARTS.get(req.unit)
    if not (isinstance(parts, list) and len(parts) == len(segments) and story_parts):
        held["drafts_without_a_story"] += 1  # a draft that says no part is a story is not one
        return None
    segments = [s for s, part in zip(segments, parts, strict=True) if part in story_parts]
    told = []
    for s in segments:
        if s.get("evidence") and isinstance(s.get("text"), str) and s["text"].strip():
            told.append(s["text"].strip())
        else:
            held["segments_unsupported"] += 1
    if not told:
        return None
    crossed[str(latest["id"])] = (int(latest.get("tier", 0)), drafts.KIND)
    return Story(drafts.model_of(latest.get("source")), told)


# -- the month card ------------------------------------------------------------------------------------


def card_of(u: Unit) -> dict[str, Any]:
    """What a month's card holds and nothing else: the first photo embedded of each starred day, the
    days signed, the goals kept, the people, and the first sentence of the longest reflection of a
    signed day (`Unit.reflections` holds only the days that went in; under `--unsigned` those of the
    signed days still choose)."""
    photos: dict[str, Photo] = {}
    for p in u.photos:
        if p.data is not None:
            photos.setdefault(p.day, p)
    kept = list(dict.fromkeys(str(r["goal"]) for r in u.reviews if r["disposition"] == KEPT and r["goal"]))
    signed = [
        (r["day"], r["text"]) for r in u.reflections if r["day"] in u.signed_days and r["source"] in OWN_HAND
    ]
    longest = min(signed, key=lambda r: (-len(r[1]), r[0])) if signed else None  # the earliest of equals
    return {
        "photos": [photos[d] for d in sorted(photos)],
        "signed": u.signed,
        "kept": kept,
        "people": list(u.people),
        "sentence": first_sentence(longest[1]) if longest else None,
    }


# -- the page ------------------------------------------------------------------------------------------


def stylesheet(paper: str) -> str:
    """The letter's one stylesheet: the paper and its margins, a page per unit, the three hands of the
    Day page (ink in a serif, the record in the system face, numbers in mono) and the pencil apart;
    system fonts only. Phone width first: nothing is wider than the screen, nothing is fixed."""
    L = print_layout
    size = PAPERS[paper]
    return f"""
@page {{ size: {size}; margin: 14mm 12mm 16mm 12mm; }}
:root {{ color-scheme: light; }}
html {{ background: {L.PAPER}; }}
body {{ margin: 0 auto; max-width: 40rem; padding: 1rem; color: {L.INK}; background: {L.PAPER};
  font: 1rem/1.45 {L.FONT_LABEL}; overflow-wrap: break-word; }}
h1, h2 {{ font-family: {L.FONT_LABEL}; font-weight: 600; margin: 0 0 .5rem; }}
h1 {{ font-size: 1.6rem; }}
h2 {{ font-size: 1.25rem; }}
h3 {{ font-family: {L.FONT_LABEL}; font-size: .8rem; font-weight: 600; line-height: 1.3;
  text-transform: uppercase; color: {L.MUTED}; margin: 1rem 0 .3rem; }}
section {{ margin: 0 0 2rem; }}
section.unit {{ break-before: page; page-break-before: always; }}
.ink {{ font-family: {L.FONT_TEXT}; font-size: 1.05rem; line-height: 1.55; }}
.ink p {{ margin: 0 0 .6rem; }}
.n, time {{ font-family: {L.FONT_MONO}; font-size: .85em; font-variant-numeric: tabular-nums; }}
.pencil {{ color: #555; border-left: 2px dotted {L.RULE}; padding: 0 0 0 .8rem; margin: .5rem 0 1rem;
  font-family: {L.FONT_TEXT}; font-style: italic; }}
.pencil .who {{ font-family: {L.FONT_LABEL}; font-style: normal; font-size: .75rem; color: {L.MUTED};
  display: block; margin-bottom: .3rem; }}
ul {{ margin: 0 0 .5rem; padding-left: 1.1rem; }}
li {{ margin: .15rem 0; }}
.mute {{ color: {L.MUTED}; }}
figure {{ margin: .5rem 0; break-inside: avoid; }}
figure img {{ display: block; max-width: 100%; height: auto; }}
figcaption {{ font-size: .75rem; color: {L.MUTED}; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(7rem, 1fr)); gap: .4rem; }}
.grid img {{ width: 100%; max-width: 100%; height: auto; display: block; }}
@media (max-width: 30rem) {{ body {{ padding: .75rem; }} .grid {{ grid-template-columns: repeat(2, 1fr); }} }}
@media print {{ body {{ max-width: none; padding: 0; font-size: 10pt; }} }}
"""


def html(req: Request, built: Built) -> str:
    """The letter as one HTML document: the front page, then a section per unit."""
    title = escape(req.title)
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f'<meta http-equiv="Content-Security-Policy" content="{CSP}">',
        f"<title>{title}</title>",
        f"<style>{stylesheet(req.paper)}</style>",
        "</head>",
        "<body>",
        '<section class="front">',
        f"<h1>{title}</h1>",
    ]
    if req.to:
        parts.append(f'<p class="mute">for {escape(req.to)}</p>')
    if req.front:
        parts.append('<div class="ink">')
        parts += [f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in _paragraphs(req.front)]
        parts.append("</div>")
    parts.append("</section>")
    for u in built.units:
        parts += list(_card_html(u) if req.card else _unit_html(u))
    parts += ["</body>", "</html>"]
    return "\n".join(parts) + "\n"


def _paragraphs(text: str) -> list[str]:
    """The front page's paragraphs, as the owner wrote them: blank lines between, the lines kept."""
    return [p.strip("\n") for p in re.split(r"\n\s*\n", text.replace("\r\n", "\n")) if p.strip()]


def _unit_html(u: Unit) -> Iterator[str]:
    yield f'<section class="unit" id="{escape(u.key)}">'
    yield f"<h2>{escape(u.heading)}</h2>"
    if u.story is not None:
        yield '<div class="pencil">'
        who = f"pencil{DOT}a model's draft, not the owner's words{DOT}model {escape(u.story.model)}"
        yield f'<span class="who">{who}</span>'
        yield "".join(f"<p>{escape(s)}</p>" for s in u.story.segments)
        yield "</div>"
    for r in u.reflections:
        if len(u.days) > 1:
            yield f"<h3>{escape(day_words(date.fromisoformat(r['day'])))}</h3>"
        own = r["source"] in OWN_HAND
        yield (
            '<div class="ink">'
            if own
            else f'<div class="said"><p class="mute">through {escape(r["source"])}</p>'
        )
        yield "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in _paragraphs(r["text"]))
        yield "</div>"
    if u.starred:
        yield "<h3>Starred</h3>"
        yield "<ul>" + "".join(f"<li>{_starred_text(s, escape)}</li>" for s in u.starred) + "</ul>"
    if u.photos:
        yield "<h3>Photos</h3>"
        for p in u.photos:
            src = p.uri()
            if src is None:
                yield f'<p class="mute">{escape(p.name)}</p>'
            else:
                name = escape(p.name)
                yield f'<figure><img src="{src}" alt="{name}"><figcaption>{name}</figcaption></figure>'
    if u.reviews:
        yield "<h3>Goals</h3>"
        yield "<ul>" + "".join(f"<li>{escape(_review_text(r))}</li>" for r in u.reviews) + "</ul>"
    if u.people:
        yield "<h3>With</h3>"
        yield f"<p>{escape(', '.join(u.people))}</p>"
    if u.places or u.flights:
        yield "<h3>Where</h3>"
        if u.places:
            yield f"<p>{escape(f' {ARROW} '.join(u.places))}</p>"
        if u.flights:
            yield "<ul>" + "".join(f'<li class="n">{escape(f)}</li>' for f in u.flights) + "</ul>"
    yield "</section>"


def _card_html(u: Unit) -> Iterator[str]:
    c = card_of(u)
    yield f'<section class="unit card" id="{escape(u.key)}">'
    yield f"<h2>{escape(u.heading)}</h2>"
    if c["photos"]:
        yield (
            '<div class="grid">'
            + "".join(f'<img src="{p.uri()}" alt="{escape(p.name)}">' for p in c["photos"])
            + "</div>"
        )
    yield f'<p><span class="n">{c["signed"]}</span> {_days_word(c["signed"])} signed</p>'
    if c["kept"]:
        yield "<h3>Goals kept</h3>"
        yield "<ul>" + "".join(f"<li>{escape(g)}</li>" for g in c["kept"]) + "</ul>"
    if c["people"]:
        yield "<h3>With</h3>"
        yield f"<p>{escape(', '.join(c['people']))}</p>"
    if c["sentence"]:
        yield f'<blockquote class="ink"><p>{escape(c["sentence"])}</p></blockquote>'
    yield "</section>"


def _days_word(n: int) -> str:
    return "day" if n == 1 else "days"


def _starred_text(s: Mapping[str, Any], quote: Any = str) -> str:
    title = quote(str(s["title"]))
    return f"{title}{DOT}{quote(str(s['note']))}" if s.get("note") else title


def _review_text(r: Mapping[str, Any]) -> str:
    out = f"{r['goal']}{DOT}{r['disposition']}{DOT}{r['period']}"
    return f"{out}{DOT}{r['note']}" if r.get("note") else out


def markdown(req: Request, built: Built) -> str:
    """The same letter as Markdown: the same front page and the same units with the same parts. Every
    word the record gives is escaped (`md`), so no line of it is read as HTML or as a heading; the front
    page is the owner's file as written."""
    out = [f"# {md(req.title)}", ""]
    if req.to:
        out += [f"*for {md(req.to)}*", ""]
    if req.front:
        out += [req.front.replace("\r\n", "\n").strip("\n"), ""]
    for u in built.units:
        out += list(_card_md(u) if req.card else _unit_md(u))
    return "\n".join(out).rstrip("\n") + "\n"


MD_SPECIAL = re.compile(r"([\\`*_\[\]<>|])")
MD_LEADING = re.compile(r"^(\s*)([#>+\-=]|\d+[.)])")


def md(text: str) -> str:
    """`text` on one line for Markdown, read as text: the whitespace folded, every character Markdown or
    HTML reads as markup escaped, and a leading mark that would open a heading, a quote or a list too."""
    line = MD_SPECIAL.sub(r"\\\1", " ".join(str(text).split()))
    return MD_LEADING.sub(r"\1\\\2", line)


def _md_image(p: Photo) -> str:
    return f"![{md(p.name)}]({p.uri()})"


def _unit_md(u: Unit) -> Iterator[str]:
    yield f"## {md(u.heading)}"
    yield ""
    if u.story is not None:
        yield f"*Pencil{DOT}a model's draft, not the owner's words{DOT}model {md(u.story.model)}*"
        yield ""
        for s in u.story.segments:
            yield f"> {md(s)}"
        yield ""
    for r in u.reflections:
        if len(u.days) > 1:
            yield f"### {day_words(date.fromisoformat(r['day']))}"
            yield ""
        if r["source"] not in OWN_HAND:
            yield f"*through {md(r['source'])}*"
            yield ""
        for p in _paragraphs(r["text"]):
            yield "  \n".join(md(line) for line in p.split("\n"))
            yield ""
    if u.starred:
        yield "### Starred"
        yield ""
        yield from (f"- {_starred_text(s, md)}" for s in u.starred)
        yield ""
    if u.photos:
        yield "### Photos"
        yield ""
        for photo in u.photos:
            yield _md_image(photo) if photo.data is not None else f"- {md(photo.name)}"
        yield ""
    if u.reviews:
        yield "### Goals"
        yield ""
        yield from (f"- {md(_review_text(r))}" for r in u.reviews)
        yield ""
    if u.people:
        yield "### With"
        yield ""
        yield md(", ".join(u.people))
        yield ""
    if u.places or u.flights:
        yield "### Where"
        yield ""
        if u.places:
            yield md(f" {ARROW} ".join(u.places))
            yield ""
        yield from (f"- {md(f)}" for f in u.flights)
        if u.flights:
            yield ""


def _card_md(u: Unit) -> Iterator[str]:
    c = card_of(u)
    yield f"## {md(u.heading)}"
    yield ""
    for p in c["photos"]:
        yield _md_image(p)
    if c["photos"]:
        yield ""
    yield f"{c['signed']} {_days_word(c['signed'])} signed"
    yield ""
    if c["kept"]:
        yield "### Goals kept"
        yield ""
        yield from (f"- {md(g)}" for g in c["kept"])
        yield ""
    if c["people"]:
        yield "### With"
        yield ""
        yield md(", ".join(c["people"]))
        yield ""
    if c["sentence"]:
        yield f"> {md(c['sentence'])}"
        yield ""


# -- the folder and the line ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Result:
    out: Path
    manifest: dict[str, Any]
    package_sha256: str  # of manifest.json's bytes; the manifest names every other file's digest
    line: Line  # the crossing/v1 line appended


def _json(data: object) -> bytes:
    """Encoded once, written as these bytes and hashed as these bytes (CRLF never creeps in)."""
    return (json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def manifest_of(req: Request, built: Built, export_id: str, head: str) -> dict[str, Any]:
    """What went in and what stayed home, counts only; the person it is for by the name the owner gave."""
    days = {"in": built.days_in, "unsigned": built.held["unsigned_days"]}
    if req.unit == JOURNEY:
        days["outside_journey"] = built.held["outside_journey_days"]
    return {
        "schema": SCHEMA,
        "export_id": export_id,
        "as_of": req.as_of,
        "read_head": head,
        "policy": {"name": DESTINATION, "version": req.version, "max_tier": req.entry.max_tier},
        "to": req.to,
        "signed_only": req.signed_only,
        "window": {"from": req.first, "to": req.last},
        "tiers": list(req.tiers),
        "units": {"unit": req.unit, "count": len(built.units)},
        "unit_keys": [u.key for u in built.units],
        "card": req.card,
        "paper": req.paper,
        "days": days,
        "counts": built.counts(),
        "photos": built.photos(),
        "photo_max_bytes": PHOTO_MAX_BYTES,
        "held_back": built.held_back(),
        "tool": {"name": "openlogbook", "version": __version__},
    }


def check_target(lb: Logbook, out: Path, force: bool = False) -> None:
    """Refuse OUT before anything is read or written: a file, a folder that holds anything and no
    earlier letter (unless `force`), the record or a folder in it outside `export/`."""
    try:
        crossing.check_target(out, force, lb.root, SCHEMAS)
    except crossing.CrossingError as e:
        raise LetterError(str(e)) from e


def default_out(lb: Logbook, req: Request) -> Path:
    """`<root>/export/letter/<FROM>_<TO>_<unit>` (`_card` after it for the month card), replaced by the
    next letter of the same range and shape."""
    shape = f"{req.unit}_card" if req.card else req.unit
    return lb.root / crossing.EXPORT_DIR / DESTINATION / f"{req.first}_{req.last}_{shape}"


def export(
    lb: Logbook, req: Request, out: Path, force: bool = False, airports: Airports | None = None
) -> tuple[Built, Result]:
    """Read, write the folder fresh, append the crossing line: under one hold of the writer lock, so
    the head the letter was read at is the head the line follows. A crash between the folder and the
    line leaves a folder no line names, which the next run replaces."""
    check_target(lb, out, force)
    with lb.writer("export letter"):
        read = lb.meta
        head = str(read["head"])
        built = build(lb, req, airports)
        if not built.units:
            raise LetterError(empty(req))
        export_id = uuid7()
        manifest = manifest_of(req, built, export_id, head)
        files = {
            HTML_FILE: html(req, built).encode("utf-8"),
            MARKDOWN_FILE: markdown(req, built).encode("utf-8"),
        }

        def fill(folder: Path) -> bytes:
            listing = []
            for name, raw in sorted(files.items()):
                (folder / name).write_bytes(raw)
                listing.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
            manifest[crossing.FILES_FIELD] = listing
            raw = _json(manifest)
            (folder / MANIFEST_FILE).write_bytes(raw)
            return raw

        meta = lb.meta
        if str(meta["head"]) != head:
            raise HeadMoved(HEAD_MOVED.format(was=read["seq"], now=meta["seq"]))
        try:
            raw = crossing.place(out, fill, lb.root, force, SCHEMAS)
        except crossing.CrossingError as e:
            raise LetterError(str(e)) from e
        package_sha256 = hashlib.sha256(raw).hexdigest()
        line = record(lb, req, built, export_id, head, package_sha256)
    return built, Result(Path(out), manifest, package_sha256, line)


def empty(req: Request) -> str:
    """Why a letter with no page is not written: one sentence."""
    what = "signed day" if req.signed_only else "day"
    where = " inside a journey" if req.unit == JOURNEY else ""
    return (
        f"no {what}{where} of {req.first} {EN_DASH} {req.last} goes in, so no letter leaves and nothing is"
        " written; `logbook day sign YYYY-MM-DD` signs a day"
    )


def record(lb: Logbook, req: Request, built: Built, export_id: str, head: str, package_sha256: str) -> Line:
    """The one `crossing/v1` line (RFC 0011, ADR 0016 rule 4): the destination, the window from the
    start of the first day to the end of the last, the tiers, the counts, the entry in force, the
    digest of the manifest, and who the letter is for. Tier 1, as every export's line, and tier 2
    (`TO_TIER`) when `--to` names the person it is for: a name is tier 2 in the record, and the line
    goes where its words may (the owner's answer, 21 October 2026). The only write to the log this
    command makes."""
    bounds = day_start.of(lb.meta)
    start, end = bounds.span(req.first)[0], bounds.span(req.last)[1]
    return lb.append(
        at=req.as_of,
        source=crossing.SOURCE,
        kind=crossing.KIND,
        tier=TO_TIER if req.to else 1,
        payload={
            "schema": crossing.LINE_SCHEMA,
            "destination": DESTINATION,
            "bundle_id": export_id,
            "window": {"from": stamp(start), "to": stamp(end)},
            "tiers": list(req.tiers),
            "counts": built.lines(),
            "policy": {
                "file": policy.POLICY_FILE.as_posix(),
                "max_tier": req.entry.max_tier,
                "signed_only": req.signed_only,
                "version": req.version,
            },
            "logbook_head": head,
            "package_sha256": package_sha256,
            "extra": {
                "letter": {
                    "schema": SCHEMA,
                    "to": req.to,
                    "unit": req.unit,
                    "card": req.card,
                    "window": {"from": req.first, "to": req.last},
                    "counts": built.counts(),
                    "held_back": built.held_back(),
                }
            },
        },
        recorded_at=req.as_of,
    )


# -- the console -----------------------------------------------------------------------------------------


def rows(req: Request, built: Built) -> Iterator[str]:
    """What a run hands over and what stayed home, for the dry run and the real one alike."""
    c, p, h = built.counts(), built.photos(), built.held_back()
    unit = req.unit + (" card" if req.card else "")
    yield f"  units: {_plural(c['units'], unit)}" + (
        "" if req.unit == DAY else f" over {_plural(c['days'], 'day')}"
    )
    yield (
        f"  in: {_plural(c['reflections'], 'reflection')}, {_plural(c['stories'], 'story', 'stories')},"
        f" {_plural(c['starred'], 'starred line')}, {_plural(p['embedded'], 'photo')} embedded and"
        f" {p['named']} named, {_plural(c['reviews'], 'review')}"
    )
    yield (
        f"  stayed home: {_plural(h['above_tier'], 'line')} above tier {max(req.tiers)},"
        f" {_plural(h.get('unsigned_days', 0), 'unsigned day')}"
        + (
            f", {_plural(h['drafts_above_tier'], 'draft')} above tier {max(req.tiers)}"
            if h.get("drafts_above_tier")
            else ""
        )
        + (
            f", {_plural(h['drafts_held_by_the_dream_entry'], 'draft')} the dream entry holds"
            if h.get("drafts_held_by_the_dream_entry")
            else ""
        )
        + (f", {_plural(h['photos_over_cap'], 'photo')} over the cap" if h.get("photos_over_cap") else "")
        + (
            f", {_plural(h['photos_not_here'], 'photo')} not on this machine"
            if h.get("photos_not_here")
            else ""
        )
        + (
            f", {_plural(h['outside_journey_days'], 'day')} outside a journey"
            if h.get("outside_journey_days")
            else ""
        )
    )
    if req.signed_only and h.get("unsigned_days"):
        yield "  (`logbook day sign YYYY-MM-DD` signs a day; --unsigned takes the unsigned days too)"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


def describe(req: Request) -> str:
    gate_text = "signed days only" if req.signed_only else "signed and unsigned days"
    tiers = ",".join(map(str, req.tiers))
    whom = f", for {req.to}" if req.to else ""
    return f"{DESTINATION}, {req.first} {EN_DASH} {req.last}, tiers {tiers}, {gate_text}{whom}"
