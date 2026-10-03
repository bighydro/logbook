"""Apple Wallet passes → flight/v1 for air boarding passes (RFC 0013, evidence `declared`), event/v1
for event tickets and for train, boat and bus passes (RFC 0009); coupons, store cards and generic
passes counted and skipped unless they carry a `relevantDate`, then one event/v1 each.

A pass is a `.pkpass`: a zip of `pass.json`, `manifest.json`, a signature and images, or — as an
iPhone keeps them under `Library/Passes/Cards/<id>.pkpass/` and as `logbook import-backup` copies
them out (`apple-wallet/`) — the same files unpacked in a folder. The input is one of those, a
`pass.json`, or a folder of either. **`pass.json` is the one file read.** The images are never
opened, `manifest.json` and the signature are never read, and the Passes app's own database
(`nav.db`, `passes23.sqlite`) is never read either: it holds Wallet's cache of the same passes and
the owner's card order, nothing a pass does not say. `pass.json` is UTF-8 (with or without a BOM) or
UTF-16 with one; a trailing comma is forgiven; anything else is counted (`skipped_unreadable`).

**What is read** of a pass: `passTypeIdentifier` and `serialNumber` (for `raw_id`, hashed, below),
`organizationName`, `description`, `relevantDate` (and the first of `relevantDates`), the style key
(`boardingPass`, `eventTicket`, `coupon`, `storeCard`, `generic`) with its `transitType`, the front
fields (`headerFields`, `primaryFields`, `secondaryFields`, `auxiliaryFields`: each field's `key`,
`label` and `value`), and these semantic tags: `airlineCode`, `flightCode`, `flightNumber`,
`departureAirportCode`, `destinationAirportCode`, `originalDepartureDate`, `originalArrivalDate`,
`departureStationName`, `destinationStationName`, `eventName`, `venueName`, `eventStartDate` (or
`eventStartDateInfo.date`), `eventEndDate`.

**What is deliberately never read:** the barcode (`barcode`, `barcodes`: an IATA BCBP message
carries the passenger's name and the booking reference, and a ticket's carries the ticket's secret),
`backFields` (terms, contacts, the booking reference, the frequent-flyer number), `nfc`,
`authenticationToken`, `webServiceURL`, `userInfo`, `beacons`, `locations`, `expirationDate`, the
`voided` flag, every semantic tag not listed above (`passengerName`, `confirmationNumber`,
`membershipProgramNumber`, `seats` …), and any front field whose key or label names a person or a
credential (passenger, name, holder, member, booking, order, ticket number …). Nothing from a field
is copied wholesale: a line carries only the values the mapping below names.

**An air boarding pass is a flight** (`transitType` `PKTransitTypeAir`, the default), evidence
`declared`: the airline's word for a seat it sold, not a tracker's record of a flight that flew.
Field keys differ per airline, so every value is found by its field's key *or* label, split into
words and matched case-insensitively: the origin from a field saying origin, from, dep, departure or
outbound and the destination from one saying destination, to, arr, arrival or inbound — of the
three-letter upper-case tokens in the value (`OSL`, `Oslo (OSL)`, `NEW YORK JFK`), else in the
label, the one the airports table knows, else the last — after the semantic tags' airport codes,
before the first two codes among the plain fields (Apple's layout); the carrier and
number from the semantic tags (`airlineCode` + `flightNumber`, or `flightCode`), else a field saying
flight (`XY 561`, `YZ0562`, or a bare `561` with the carrier from a field saying airline, carrier or
operator). The date is the local date of the scheduled departure when the pass names one (the
semantic `originalDepartureDate`, else a field saying departure whose value is a timestamp), else
`relevantDate`'s own date, else a field saying date whose value carries a year (`2026-03-14`,
`14.03.2026`, `14 Mar 2026`, `14MAR26`); a pass with none is counted (`skipped_no_date`), never
placed by a file time. The scheduled arrival comes from `originalArrivalDate`, else a field saying
arrival with a timestamp. `relevantDate` — boarding for one airline, departure for another — is kept
under `extra.relevant_date` and is the line's `at` when no schedule is known, never a scheduled
time. The seat (a field saying seat) and the class (class, cabin, compartment, fare) go under `extra`
with the airline's name as `extra.organization`. A pass with no route or no flight number is counted
(`skipped_no_flight`). Carrier and airports are spelled through the flights tables (RFC 0013 rule 5).

**A ticket is an event.** An `eventTicket` is one `event/v1` line: the title from the semantic
`eventName`, else a field saying event, title or show, else the first primary field that names no
person; the venue as `location`, from `venueName` or a field saying venue, location, where or place;
`at` from `relevantDate`, else `eventStartDate`, else a field saying start, doors, time or date (a
day with no clock makes an all-day line); `end` from `eventEndDate` or a field saying end. A
`boardingPass` for a train, a boat or a bus is an event titled `origin → destination`, with
`extra.transit_type`, its seat and class, `at` and `end` from `relevantDate` and the fields saying
departure and arrival. A coupon, a store card or a generic pass with a `relevantDate` is an event
titled with the issuer's name, `extra.pass_style` saying which; without one it is counted
(`skipped_coupons`, `skipped_store_cards`, `skipped_generic_passes`). `calendar` is the pass type
and the issuer. A ticket with no date is counted (`skipped_no_date`).

`raw_id` is `wallet:<16 hex of sha256(passTypeIdentifier, serialNumber)>@<digest of the mapped
line>`: the serial identifies the pass across devices and can be a booking reference, so it is
hashed, never carried. The same pass again appends nothing; a pass the airline updated (the same
serial, a new `relevantDate`, a new seat) is a new observation of the same flight, and
`flights.reconcile` folds it into the line that stands and supersedes it (RFC 0013 rules 3 and 6);
a tracker's export of the flight supersedes both. Pure: files read once, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import flights
from ..flights import Airlines, Airports

NAME = "apple-wallet"
EVENT_KIND = "event"
EVENT_SCHEMA = "event/v1"
TIER = 1  # SPEC §4: a flight and a plan are the owner's own movement and time
PASS_JSON = "pass.json"
STYLES = ("boardingPass", "eventTicket", "coupon", "storeCard", "generic")
SKIPPED_STYLE = {
    "storeCard": "skipped_store_cards",
    "coupon": "skipped_coupons",
    "generic": "skipped_generic_passes",
}
FRONT = ("headerFields", "primaryFields", "secondaryFields", "auxiliaryFields")
AIR = "PKTransitTypeAir"
YEAR_FLOOR = 1990
YEARS_AHEAD = 2
TRAILING_COMMA = re.compile(r",(\s*[}\]])")
CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
WORD = re.compile(r"[a-z]+|\d+")

# -- the roles a field plays, by the words of its key or its label ----------------------------------------
ORIGIN = re.compile(r"\b(origin|from|dep|depart|departs|departure|departing|outbound|von)\b")
DESTINATION = re.compile(r"\b(destination|dest|to|arr|arrive|arrives|arrival|arriving|inbound|nach)\b")
FLIGHT = re.compile(r"\b(flight|flt|fltno|flug|vuelo|vol)\b")
CARRIER = re.compile(r"\b(carrier|airline|operator|operated)\b")
DATE = re.compile(r"\b(date|datum|day)\b")
DEPARTURE = re.compile(r"\b(dep|depart|departs|departure|departing|std|abflug)\b")
ARRIVAL = re.compile(r"\b(arr|arrive|arrives|arrival|arriving|sta|ankunft)\b")
SEAT = re.compile(r"\b(seat|sitz)\b")
CLASS = re.compile(r"\b(class|cabin|compartment|fare|klasse)\b")
VENUE = re.compile(r"\b(venue|location|where|place|stadium|arena|theatre|theater|hall|cinema|address)\b")
TITLE = re.compile(r"\b(event|title|show|performance|headline|match|film|movie|concert)\b")
START = re.compile(r"\b(start|starts|begins|doors|when|time|date|datum|kickoff|showtime)\b")
END = re.compile(r"\b(end|ends|until|finish|finishes)\b")
# A field whose key or label names the owner or a credential: never a title, never anything.
PRIVATE = re.compile(
    r"\b(passenger|pax|attendee|holder|member|guest|customer|buyer|purchaser|travell?er|registered"
    r"|name|pnr|booking|reservation|confirmation|reference|locator|order|ticket|barcode|token|eticket"
    r"|document|sequence|seq|frequent|loyalty|email|phone|contact)\b"
)
CODE = re.compile(r"(?<![A-Z])[A-Z]{3}(?![A-Z])")
DESIGNATOR = re.compile(r"(?<![A-Z0-9])([A-Z][A-Z0-9]|[0-9][A-Z])[ -]?0*(\d{1,4})([A-Z])?(?![A-Z0-9])")
BARE_NUMBER = re.compile(r"^0*(\d{1,4})([A-Z])?$")
MONTHS = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
DATED = (  # text that carries a date with its year; groups are (day, month, year) or ISO
    re.compile(r"(?<!\d)(\d{1,2})([A-Za-z]{3})(\d{4}|\d{2})(?!\d)"),  # 31OCT24, 05JUN2023
    re.compile(r"(?<!\d)(\d{1,2})\.?\s+([A-Za-z]{3})[A-Za-z]*\.?,?\s+(\d{4})(?!\d)"),  # 04 Nov 2023
    re.compile(r"([A-Za-z]{3})[A-Za-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)"),  # May 15, 2025
    re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"),  # 2023-05-14
    re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?![\d.])"),  # 28.01.20, 30.09.2017
)


@dataclass(frozen=True)
class Field:
    """One front field: its text, and the words of its key and label for the roles above."""

    key: str
    label: str
    text: str
    instant: datetime | None = field(default=None, compare=False)

    def says(self, role: re.Pattern[str]) -> bool:
        return bool(role.search(self.key) or role.search(self.label))

    @property
    def codes(self) -> list[str]:
        """The three-letter upper-case tokens of the value, else of the label: `Oslo (OSL)` → OSL,
        `NEW YORK JFK` → NEW, JFK (the route takes the one the airports table knows)."""
        return CODE.findall(self.text) or CODE.findall(self.label.upper())


def raw_prefix(pass_type_id: str, serial: str) -> str:
    """`wallet:<16 hex>`: the pass by its type and serial, which identify it across devices, without
    carrying either (a serial can be a booking reference)."""
    return "wallet:" + hashlib.sha256(f"{pass_type_id}\0{serial}".encode()).hexdigest()[:16]


def sniff(path: Path) -> bool:
    """A `.pkpass` (zip or unpacked folder), a `pass.json`, or a folder holding either. Never raises."""
    try:
        return next(_pass_files(Path(path)), None) is not None
    except (OSError, ValueError, zipfile.BadZipFile):
        return False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    airports: Airports | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One flight/v1 draft per air boarding pass and one event/v1 draft per ticket, transit pass or
    dated card, in name order. `since` is RFC3339 UTC; drafts whose `at` is before it are not
    yielded. `counts` tallies `skipped_unreadable`, `skipped_unknown_style`, `skipped_no_flight`,
    `skipped_no_date`, `skipped_store_cards`, `skipped_coupons` and `skipped_generic_passes`.
    `timezone` is the record's zone, for a ticket whose date names no zone; `airports` the table to
    look codes up in (default: the built-in)."""
    counts = counts if counts is not None else {}
    airports = airports or Airports.load()
    airlines = Airlines.load()
    for _label, data in _pass_files(Path(path)):
        pass_ = _load(data)
        if pass_ is None:
            _count(counts, "skipped_unreadable")
            continue
        draft = _draft(pass_, counts, airports, airlines, timezone)
        if draft is not None and not (since and draft["at"] < since):
            yield draft


# -- files --------------------------------------------------------------------------------------------------


def _pass_files(path: Path) -> Iterator[tuple[str, bytes]]:
    """(label, the bytes of pass.json) for every pass at `path`, in name order."""
    if path.is_file():
        if path.name == PASS_JSON:
            yield path.parent.name, path.read_bytes()
        elif zipfile.is_zipfile(path):
            yield from _from_zip(path)
        return
    if not path.is_dir():
        return
    if (path / PASS_JSON).is_file():
        yield path.name, (path / PASS_JSON).read_bytes()
        return
    for child in sorted(path.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir() and (child / PASS_JSON).is_file():
            yield child.name, (child / PASS_JSON).read_bytes()
        elif child.is_file() and child.suffix == ".pkpass" and zipfile.is_zipfile(child):
            yield from _from_zip(child)


def _from_zip(path: Path) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as z:
        if PASS_JSON in z.namelist():
            yield path.name, z.read(PASS_JSON)


def _load(data: bytes) -> dict[str, Any] | None:
    """The pass object: UTF-8 (BOM or not) or UTF-16 with a BOM; a trailing comma forgiven."""
    encoding = "utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
    try:
        text = data.decode(encoding)
    except UnicodeDecodeError:
        return None
    for attempt in (text, TRAILING_COMMA.sub(r"\1", text)):
        try:
            obj = json.loads(attempt)
        except ValueError:
            continue
        return obj if isinstance(obj, dict) else None
    return None


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


# -- one pass -----------------------------------------------------------------------------------------------


def _draft(
    pass_: dict[str, Any],
    counts: dict[str, int],
    airports: Airports,
    airlines: Airlines,
    timezone: str | None,
) -> dict[str, Any] | None:
    style = next((s for s in STYLES if isinstance(pass_.get(s), dict)), None)
    if style is None:
        _count(counts, "skipped_unknown_style")
        return None
    body: dict[str, Any] = pass_[style]
    found = _relevant(pass_)
    relevant, relevant_text = found if found is not None else (None, None)
    if style in SKIPPED_STYLE and relevant is None:
        _count(counts, SKIPPED_STYLE[style])
        return None
    prefix = raw_prefix(str(pass_.get("passTypeIdentifier", "")), str(pass_.get("serialNumber", "")))
    front = _fields(body, timezone)
    semantics = _dict(pass_.get("semantics"))
    if style == "boardingPass" and body.get("transitType", AIR) == AIR:
        return _flight(pass_, front, relevant_text, semantics, prefix, counts, airports, airlines, timezone)
    draft = _event(pass_, body, style, front, relevant_text, semantics, prefix, timezone)
    if draft is None:
        _count(counts, "skipped_no_date")
    return draft


def _fields(body: dict[str, Any], timezone: str | None) -> list[Field]:
    """The front fields with a text value, header to auxiliary, in order; never the back."""
    out: list[Field] = []
    for section in FRONT:
        for f in body.get(section) or []:
            if not isinstance(f, dict) or not isinstance(f.get("key"), str):
                continue
            value = f.get("value")
            if value is None or isinstance(value, bool):
                continue
            text = str(value).strip()
            if not text:
                continue
            label = f.get("label")
            words = _words(label) if isinstance(label, str) else ""
            out.append(Field(_words(f["key"]), words, text, _instant(text, timezone)))
    return out


def _words(name: str) -> str:
    """`departureDate` → `departure date`, `event-name` → `event name`: words to match roles on."""
    return " ".join(WORD.findall(CAMEL.sub(" ", name).lower()))


def _text(semantics: dict[str, Any], tag: str) -> str | None:
    value = semantics.get(tag)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _relevant(pass_: dict[str, Any]) -> tuple[datetime, str] | None:
    """`relevantDate`, else the first of `relevantDates`, as an instant with a plausible year (a
    year of 2093 is a placeholder the issuer wrote, not an instant), with the text it was read from."""
    candidates: list[object] = [pass_.get("relevantDate")]
    dates = pass_.get("relevantDates")
    if isinstance(dates, list) and dates and isinstance(dates[0], dict):
        candidates.extend([dates[0].get("startDate"), dates[0].get("date")])
    for value in candidates:
        instant = _instant(value)
        if instant is not None and _plausible(instant.year):
            return instant, str(value).strip()
    return None


def _first(front: list[Field], role: re.Pattern[str], *, timed: bool | None = None) -> Field | None:
    """The first front field in `role`; `timed` True wants a timestamp value, False a plain one."""
    for f in front:
        if timed is not None and (f.instant is not None) != timed:
            continue
        if f.says(role):
            return f
    return None


# -- air boarding passes ------------------------------------------------------------------------------------


def _flight(
    pass_: dict[str, Any],
    front: list[Field],
    relevant_text: str | None,
    semantics: dict[str, Any],
    prefix: str,
    counts: dict[str, int],
    airports: Airports,
    airlines: Airlines,
    timezone: str | None,
) -> dict[str, Any] | None:
    route = _route(front, semantics, airports)
    designator = _designator(front, semantics)
    if route is None or designator is None:
        _count(counts, "skipped_no_flight")
        return None
    origin, destination = route
    carrier, number = designator
    relevant = _instant(relevant_text)
    departure = _instant(semantics.get("originalDepartureDate")) or _timed(front, DEPARTURE)
    arrival = _instant(semantics.get("originalArrivalDate")) or _timed(front, ARRIVAL)
    airport = airports.get(origin)
    zone = ZoneInfo(airport.tz) if airport is not None and airport.tz else None
    day: date | None
    if departure is not None:
        day = (departure.astimezone(zone) if zone else departure).date()
    elif relevant is not None:
        day = relevant.date()
    else:
        dated = _first(front, DATE, timed=False)
        day = _dated(dated.text) if dated is not None else None
    if day is None or not _plausible(day.year):
        _count(counts, "skipped_no_date")
        return None
    times: dict[str, str | None] = {}
    if departure is not None:
        times["scheduled_departure"] = _utc(departure)
    if arrival is not None:
        times["scheduled_arrival"] = _utc(arrival)
    extra = _extra(pass_, front, relevant_text)
    carrier = airlines.iata(carrier)
    from_ = flights.airport_ref(origin, airports)
    to = flights.airport_ref(destination, airports)
    mapped = (day.isoformat(), carrier, number, from_, to, times, extra)
    draft = flights.build(
        source=NAME,
        raw_id=f"{prefix}@{flights.digest(*mapped)}",
        airports=airports,
        date=day.isoformat(),
        carrier=carrier,
        number=number,
        carrier_icao=airlines.icao(carrier),
        from_=from_,
        to=to,
        extra=extra,
        times=times,
    )
    if departure is None and relevant is not None:
        local_day = relevant.astimezone(zone).date() if zone else relevant.date()
        if abs((local_day - day).days) <= 1:
            draft["at"] = _utc(relevant)
    if draft["tz"] is None:
        draft["tz"] = timezone
    return draft


def _route(front: list[Field], semantics: dict[str, Any], airports: Airports) -> tuple[str, str] | None:
    """(origin, destination) codes: the semantic tags, else the fields that say so, else the first
    two codes among the other plain fields (Apple's own layout puts the route in the primary ones).
    Of several codes in one field (`NEW YORK JFK`) the one the airports table knows, else the last."""
    tagged = (_text(semantics, "departureAirportCode"), _text(semantics, "destinationAirportCode"))
    if tagged[0] and tagged[1]:
        return tagged[0].upper(), tagged[1].upper()
    untimed = [f for f in front if f.instant is None and not f.says(DATE)]
    origin = next((c for f in untimed if f.says(ORIGIN) and (c := _code(f, airports))), None)
    destination = next((c for f in untimed if f.says(DESTINATION) and (c := _code(f, airports))), None)
    if origin and destination:
        return origin, destination
    codes: list[str] = []
    for f in untimed:
        if any(f.says(role) for role in (ORIGIN, DESTINATION, FLIGHT, SEAT, CLASS, PRIVATE)):
            continue
        code = _code(f, airports)
        if code and code not in codes:
            codes.append(code)
    return (codes[0], codes[1]) if len(codes) >= 2 else None


def _code(f: Field, airports: Airports) -> str | None:
    codes = f.codes
    return next((c for c in codes if airports.get(c) is not None), codes[-1] if codes else None)


def _designator(front: list[Field], semantics: dict[str, Any]) -> tuple[str, str] | None:
    """(carrier, number): the semantic tags, else a field saying flight, with the carrier from a
    field saying airline when the flight field holds the number alone."""
    code = _text(semantics, "airlineCode")
    number = _text(semantics, "flightNumber")
    if code and number and (m := BARE_NUMBER.fullmatch(number.upper())):
        return code.upper(), f"{int(m.group(1))}{m.group(2) or ''}"
    flight_code = _text(semantics, "flightCode")
    if flight_code and (m := DESIGNATOR.search(flight_code.upper())):
        return m.group(1), f"{int(m.group(2))}{m.group(3) or ''}"
    for f in front:
        if f.instant is not None or not f.says(FLIGHT):
            continue
        text = f.text.upper()
        if m := DESIGNATOR.search(text):
            return m.group(1), f"{int(m.group(2))}{m.group(3) or ''}"
        if m := BARE_NUMBER.fullmatch(text):
            named = [c.text.upper() for c in front if c.says(CARRIER) and c.instant is None]
            carrier = next((c for c in [code, *named] if c and 2 <= len(c) <= 3), None)
            if carrier:
                return carrier.upper(), f"{int(m.group(1))}{m.group(2) or ''}"
    return None


def _timed(front: list[Field], role: re.Pattern[str]) -> datetime | None:
    f = _first(front, role, timed=True)
    return f.instant if f is not None else None


def _extra(pass_: dict[str, Any], front: list[Field], relevant_text: str | None) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if isinstance(pass_.get("organizationName"), str) and pass_["organizationName"].strip():
        extra["organization"] = pass_["organizationName"].strip()
    seat = _first(front, SEAT, timed=False)
    if seat is not None:
        extra["seat"] = seat.text
    class_ = _first(front, CLASS, timed=False)
    if class_ is not None:
        extra["class"] = class_.text
    if relevant_text:
        extra["relevant_date"] = relevant_text
    return extra


# -- tickets, transit passes, dated cards ----------------------------------------------------------------


def _event(
    pass_: dict[str, Any],
    body: dict[str, Any],
    style: str,
    front: list[Field],
    relevant_text: str | None,
    semantics: dict[str, Any],
    prefix: str,
    timezone: str | None,
) -> dict[str, Any] | None:
    relevant = _instant(relevant_text)
    transit = body.get("transitType") if isinstance(body.get("transitType"), str) else None
    organization = pass_.get("organizationName") if isinstance(pass_.get("organizationName"), str) else None
    description = pass_.get("description") if isinstance(pass_.get("description"), str) else None
    all_day = False
    location: str | None = None
    end: datetime | None = None
    if style == "boardingPass":
        title = _journey(front, semantics)
        start = relevant or _instant(semantics.get("originalDepartureDate")) or _timed(front, DEPARTURE)
        end = _instant(semantics.get("originalArrivalDate")) or _timed(front, ARRIVAL)
    elif style == "eventTicket":
        title = _title(front, body, semantics, description)
        start_info = _dict(semantics.get("eventStartDateInfo"))
        start = (
            relevant
            or _instant(semantics.get("eventStartDate"))
            or _instant(start_info.get("date"))
            or _timed(front, START)
        )
        if start is None:
            dated = _first(front, START, timed=False)
            day = _dated(dated.text) if dated is not None else None
            if day is not None and _plausible(day.year):
                start = datetime.combine(day, datetime.min.time(), ZoneInfo(timezone or "UTC"))
                all_day = True
        end = _instant(semantics.get("eventEndDate")) or _timed(front, END)
        location = _text(semantics, "venueName")
        if location is None:
            venue = _first(front, VENUE, timed=False)
            location = venue.text if venue is not None else None
    else:  # a coupon, a store card or a generic pass with a relevantDate: the issuer's moment
        title = organization or description
        start = relevant
    if start is None:
        return None
    if all_day and end is None:
        end = start + timedelta(days=1)
    extra: dict[str, Any] = {"pass_style": style}
    if transit:
        extra["transit_type"] = transit.removeprefix("PKTransitType").lower()
    extra.update(_extra(pass_, front, relevant_text))
    at = _utc(start)
    end_text = _utc(end) if end is not None else None
    mapped = (title, at, end_text, location, extra)
    payload: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "raw_id": f"{prefix}@{flights.digest(*mapped)}",
        "all_day": all_day,
    }
    if title:
        payload["title"] = title
    payload["calendar"] = {"id": pass_.get("passTypeIdentifier"), "name": organization}
    if location:
        payload["location"] = location
    payload["extra"] = extra
    return {
        "at": at,
        "end": end_text,
        "tz": timezone,
        "source": NAME,
        "kind": EVENT_KIND,
        "tier": TIER,
        "payload": payload,
    }


def _journey(front: list[Field], semantics: dict[str, Any]) -> str | None:
    """`Oslo S → Bergen` for a train, a boat or a bus: the station names the semantic tags give,
    else the fields saying origin and destination, as text."""
    origin = _text(semantics, "departureStationName")
    destination = _text(semantics, "destinationStationName")
    if origin is None or destination is None:
        untimed = [f for f in front if f.instant is None and not f.says(DATE) and not f.says(PRIVATE)]
        here = next((f for f in untimed if f.says(ORIGIN)), None)
        there = next((f for f in untimed if f.says(DESTINATION)), None)
        if here is not None and there is not None:
            origin, destination = here.text, there.text
    return f"{origin} → {destination}" if origin and destination else None


def _title(
    front: list[Field], body: dict[str, Any], semantics: dict[str, Any], description: str | None
) -> str | None:
    named = _text(semantics, "eventName")
    if named:
        return named
    titled = next((f for f in front if f.instant is None and f.says(TITLE) and not f.says(PRIVATE)), None)
    if titled is not None:
        return titled.text
    for section in ("primaryFields", "headerFields"):
        for f in _fields({section: body.get(section)}, None):
            if f.instant is None and not f.says(PRIVATE) and not f.says(START) and _dated(f.text) is None:
                return f.text
    return description


# -- dates --------------------------------------------------------------------------------------------------


def _instant(value: object, timezone: str | None = None) -> datetime | None:
    """An ISO 8601 timestamp as an aware datetime; a zone-less one in `timezone` when given, else
    None. Not a bare date."""
    if not isinstance(value, str) or "T" not in value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if timezone is None:
            return None
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
    return parsed


def _utc(instant: datetime) -> str:
    return instant.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _plausible(year: int) -> bool:
    return YEAR_FLOOR <= year <= date.today().year + YEARS_AHEAD


def _dated(text: str) -> date | None:
    """The first date with a year in free text, else None."""
    for pattern in DATED:
        m = pattern.search(text)
        if m is None:
            continue
        a, b, c = m.groups()
        try:
            if pattern is DATED[3]:
                return date(int(a), int(b), int(c))
            if pattern is DATED[2]:
                month, day, year = MONTHS.get(a.lower()), int(b), int(c)
            elif pattern is DATED[4]:
                day, month, year = int(a), int(b), int(c)
            else:
                day, month, year = int(a), MONTHS.get(b.lower()), int(c)
            if month is None:
                continue
            if year < 100:
                year += 2000
            return date(year, month, day)
        except ValueError:
            continue
    return None
