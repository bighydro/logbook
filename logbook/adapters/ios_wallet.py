"""Apple Wallet passes → flight/v1 for air boarding passes (RFC 0013, evidence `tracked`), event/v1
for event tickets and every other boarding pass (RFC 0009); loyalty cards, coupons and generic passes
skipped and counted.

A pass is a `.pkpass`: a zip with a `pass.json` inside, or — as an iPhone keeps them under
`Library/Passes/Cards/<id>.pkpass/` and as `logbook import-backup` copies them out (`ios-wallet/`) —
the same files unpacked in a folder. The input is one of those, a `pass.json`, or a folder of either.
`pass.json` is UTF-8 (with or without a BOM) or UTF-16 with one; a file with a trailing comma is
read as if it had none; anything else is counted (`skipped_unreadable`). The pass's style is the one
of `boardingPass`, `eventTicket`, `coupon`, `storeCard`, `generic` it carries.

**An air boarding pass is a flight.** The airline's barcode is an IATA BCBP message (Resolution 792)
and is the one place every airline spells the flight the same way: after the format code `M`, the
number of legs, twenty characters of passenger name and the e-ticket flag, each leg is a fixed
record — PNR (7), from (3), to (3), carrier (3), flight number (5), day of the year (3), compartment
(1), seat (4), check-in sequence (5), status (1) and the length of a variable field (2, hex) that is
skipped to reach the next leg. One flight line per leg. The front fields are the fallback for a pass
with no barcode: the first two three-letter codes among the primary fields are the route, a field
whose key says `flight` and whose value is `XY 561` the designator; a pass with neither is counted
(`skipped_no_flight`).

The barcode gives the day of the year, not the year. The year is the first plausible one (1990 to
two years ahead) among: `relevantDate`, `relevantDates`, `expirationDate`, the semantic tags'
`originalDepartureDate`, and any field whose text carries a date with a year (`31OCT24`,
`04 Nov 2023`, `May 15 2025`, `2023-05-14`, `28.01.20`). The flight's date is then the barcode's
day in whichever of that year and its neighbours puts it nearest the hint (a pass expiring on
3 January is for a flight on 31 December). A pass with no such hint cannot be placed and is counted
(`skipped_no_year`), never guessed: the phone's file times are not evidence, they move with a
restore.

Times: only the semantic tags name a schedule (`originalDepartureDate` → `scheduled_departure`,
`originalArrivalDate` → `scheduled_arrival`). `relevantDate` is the instant Wallet surfaces the pass —
boarding for one airline, departure for another — so it is kept under `extra.relevant_date` and
becomes the first leg's `at` when no schedule is known, but it is never written as a scheduled time.
Carrier and airports go through the flights tables as Flighty's export does (RFC 0013 rule 5); the
seat, the compartment, the gate and the terminal are kept under `extra`, with `voided` when the pass
was. The PNR, the passenger's name, the barcode, the ticket number: never (RFC 0013 *Payload*).
`raw_id` is `wallet:<16 hex of the pass type and serial>@<digest of the mapped leg>`: the same pass
again appends nothing, a pass Wallet updated (a new seat) is a new observation of the same flight
(rule 6), and a Flighty export of that flight supersedes it with the merge (rule 3).

**A ticket is an event.** An `eventTicket`, and a `boardingPass` for a bus, a boat or a train, is one
`event/v1` line: `at` from `relevantDate`, else the semantic tags' event start, else a field whose
value is a timestamp, else a dated field (then an all-day event); `end` from the semantic tags' end
or a field whose key says arrival or end; the title from the semantic tags, else the pass's first
primary field (`event-name`, `product`, …), else its description — for a bus or boat, `origin →
destination`; `location` from the semantic tags' venue or a field whose key says venue, location,
address or cinema; `calendar` is the pass type and the issuer. The pass's `locations` go under
`extra.locations`, its front fields under `extra.fields` — except any whose key says name,
passenger, attendee, member, buyer, order, booking, code, number or token, which hold the owner's
name or a credential. Back fields (terms, contacts) are never kept. A ticket with no date at all is
counted (`skipped_no_date`). Pure: files read once, no network.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .. import flights
from ..flights import Airlines, Airports

NAME = "ios-wallet"
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
BACK = "backFields"
AIR = "PKTransitTypeAir"
YEAR_FLOOR = 1990
YEARS_AHEAD = 2
# Field keys whose value is the owner's name or a credential to the booking: never kept.
PRIVATE = re.compile(
    r"passenger|pax|attendee|member|buyer|purchaser|registered|holder|guest|customer|travell?er|^name$"
    r"|^primary$|^secondary$|^auxiliary$"  # the generic keys, which hold the member's name
    r"|code|order|reservation|booking|document|pnr|token|etix|eticket|filekey|number|contact",
    re.I,
)
VENUE = re.compile(r"venue|location|address|cinema|place|theat", re.I)
END = re.compile(r"arriv|end", re.I)
FLIGHT_KEY = re.compile(r"flight|vuelo|flug|vol", re.I)
DESIGNATOR = re.compile(r"([A-Z][A-Z0-9]|[0-9][A-Z]|[A-Z]{3})\s?0*(\d{1,4})([A-Z])?")
CODE = re.compile(r"^([A-Z]{3})$|\(([A-Z]{3})\)")
NUMBER = re.compile(r"0*(\d{1,4})([A-Z])?")
TRAILING_COMMA = re.compile(r",(\s*[}\]])")
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
class Leg:
    """One leg of a BCBP message, without the items that identify the passenger or the booking."""

    origin: str
    destination: str
    carrier: str
    number: str
    day_of_year: int
    compartment: str
    seat: str


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
    """One flight/v1 draft per air boarding-pass leg and one event/v1 draft per ticket, in name order.
    `since` is RFC3339 UTC; drafts whose `at` is before it are not yielded. `counts` tallies
    `skipped_unreadable`, `skipped_no_year`, `skipped_no_flight`, `skipped_no_date`,
    `skipped_store_cards`, `skipped_coupons`, `skipped_generic_passes` and `skipped_unknown_style`.
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
        for draft in _drafts(pass_, counts, airports, airlines, timezone):
            if since and draft["at"] < since:
                continue
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
        names = {n for n in z.namelist() if n == PASS_JSON or n.endswith("/" + PASS_JSON)}
        if PASS_JSON in names:
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


def _drafts(
    pass_: dict[str, Any],
    counts: dict[str, int],
    airports: Airports,
    airlines: Airlines,
    timezone: str | None,
) -> Iterator[dict[str, Any]]:
    style = next((s for s in STYLES if isinstance(pass_.get(s), dict)), None)
    if style is None:
        _count(counts, "skipped_unknown_style")
        return
    if style in SKIPPED_STYLE:
        _count(counts, SKIPPED_STYLE[style])
        return
    body: dict[str, Any] = pass_[style]
    prefix = raw_prefix(str(pass_.get("passTypeIdentifier", "")), str(pass_.get("serialNumber", "")))
    if style == "boardingPass" and body.get("transitType", AIR) == AIR:
        yield from _flights(pass_, body, prefix, counts, airports, airlines, timezone)
    else:
        draft = _event(pass_, body, style, prefix, timezone)
        if draft is None:
            _count(counts, "skipped_no_date")
        else:
            yield draft


def _fields(body: dict[str, Any], sections: tuple[str, ...] = FRONT) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for section in sections:
        for f in body.get(section) or []:
            if isinstance(f, dict) and isinstance(f.get("key"), str):
                out.append(f)
    return out


def _text(field: dict[str, Any]) -> str | None:
    value = field.get("value")
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    return text or None


def _dict(value: object) -> dict[str, Any]:
    """`value` when it is an object, else an empty one."""
    return value if isinstance(value, dict) else {}


# -- air boarding passes ------------------------------------------------------------------------------------


def _flights(
    pass_: dict[str, Any],
    body: dict[str, Any],
    prefix: str,
    counts: dict[str, int],
    airports: Airports,
    airlines: Airlines,
    timezone: str | None,
) -> Iterator[dict[str, Any]]:
    front = _fields(body)
    legs = parse_bcbp(_barcode_message(pass_)) or _legs_from_fields(front)
    if not legs:
        _count(counts, "skipped_no_flight")
        return
    semantics = _dict(pass_.get("semantics"))
    relevant = _instant(pass_.get("relevantDate"))
    if relevant is not None and not _plausible(relevant.year):
        relevant = None  # a year of 2093 is a placeholder the airline wrote, not an instant
    relevant_text = pass_.get("relevantDate") if relevant is not None else None
    hint = _year_hint(pass_, body, semantics, relevant)
    if hint is None:
        _count(counts, "skipped_no_year")
        return
    times: dict[str, str | None] = {}
    for tag, field in (
        ("originalDepartureDate", "scheduled_departure"),
        ("originalArrivalDate", "scheduled_arrival"),
    ):
        instant = _instant(semantics.get(tag))
        if instant is not None:
            times[field] = _utc(instant)
    by_key = {f["key"].lower(): _text(f) for f in front}
    gate = by_key.get("gate")
    terminal = next((v for k, v in by_key.items() if "terminal" in k and "gate" not in k and v), None)
    for index, leg in enumerate(legs):
        day = _place_day(leg.day_of_year, hint)
        if day is None:
            _count(counts, "skipped_no_year")
            continue
        extra: dict[str, Any] = {"organization": pass_.get("organizationName")}
        seat = leg.seat or by_key.get("seat")
        if seat:
            extra["seat"] = seat
        if leg.compartment:
            extra["compartment"] = leg.compartment
        if gate and gate != "-":
            extra["gate"] = gate
        if terminal:
            extra["terminal"] = terminal
        if relevant_text:
            extra["relevant_date"] = relevant_text
        if pass_.get("voided") is True:
            extra["voided"] = True
        extra = {k: v for k, v in extra.items() if v}
        carrier = airlines.iata(leg.carrier)
        from_ = flights.airport_ref(leg.origin, airports)
        to = flights.airport_ref(leg.destination, airports)
        leg_times = times if index == 0 else {}
        mapped = (day.isoformat(), carrier, leg.number, from_, to, leg_times, extra)
        draft = flights.build(
            source=NAME,
            raw_id=f"{prefix}@{flights.digest(*mapped)}",
            airports=airports,
            date=day.isoformat(),
            carrier=carrier,
            number=leg.number,
            carrier_icao=airlines.icao(leg.carrier),
            from_=from_,
            to=to,
            extra=extra or None,
            times=leg_times,
        )
        if index == 0 and relevant is not None and not leg_times:
            local_day = relevant.astimezone(ZoneInfo(draft["tz"])).date() if draft["tz"] else relevant.date()
            if abs((local_day - day).days) <= 1:
                draft["at"] = _utc(relevant)
        if draft["tz"] is None:
            draft["tz"] = timezone
        yield draft


def parse_bcbp(message: str | None) -> list[Leg]:
    """The legs of an IATA BCBP message, or [] when the text is not one. The name, the PNR, the
    sequence number and the variable fields are read past and never returned."""
    if not message or len(message) < 60 or message[0] != "M" or not message[1].isdigit():
        return []
    legs: list[Leg] = []
    pos = 23  # format (1), legs (1), name (20), e-ticket flag (1)
    for _ in range(int(message[1])):
        record = message[pos : pos + 37]
        if len(record) < 37:
            break
        origin, destination, carrier = record[7:10].strip(), record[10:13].strip(), record[13:16].strip()
        number = _number(record[16:21])
        julian, compartment, seat, size = (
            record[21:24],
            record[24].strip(),
            record[25:29].strip(),
            record[35:37],
        )
        if not (origin.isalpha() and destination.isalpha() and carrier and number and julian.isdigit()):
            break
        legs.append(
            Leg(origin.upper(), destination.upper(), carrier.upper(), number, int(julian), compartment, seat)
        )
        try:
            pos += 37 + int(size, 16)
        except ValueError:
            break
    return legs


def _barcode_message(pass_: dict[str, Any]) -> str | None:
    barcodes = pass_.get("barcodes")
    if not isinstance(barcodes, list):
        barcodes = [pass_.get("barcode")]
    for b in barcodes:
        if isinstance(b, dict) and isinstance(b.get("message"), str):
            return str(b["message"])
    return None


def _number(text: str) -> str | None:
    """`0561 `, `561A` → the number without leading zeros, with its suffix."""
    m = NUMBER.fullmatch(text.strip().upper())
    return None if m is None else f"{int(m.group(1))}{m.group(2) or ''}"


def _legs_from_fields(front: list[dict[str, Any]]) -> list[Leg]:
    """A pass without a barcode: the route from the primary fields' codes, the flight from a field
    whose key says flight. The day of the year is 0: the date is the hint's own."""
    codes: list[str] = []
    for f in front:
        text = _text(f)
        if text is None:
            continue
        m = CODE.search(text)
        if m is not None and (m.group(1) or m.group(2)) not in codes:
            codes.append(m.group(1) or m.group(2))
    designator = None
    for f in front:
        text = _text(f)
        if text is not None and FLIGHT_KEY.search(f["key"]):
            m = DESIGNATOR.fullmatch(text.upper().replace("-", " "))
            if m is not None:
                designator = (m.group(1), f"{int(m.group(2))}{m.group(3) or ''}")
                break
    if len(codes) < 2 or designator is None:
        return []
    seat = next((t for f in front if f["key"].lower() == "seat" and (t := _text(f))), "")
    return [Leg(codes[0], codes[1], designator[0], designator[1], 0, "", seat)]


def _year_hint(
    pass_: dict[str, Any], body: dict[str, Any], semantics: dict[str, Any], relevant: datetime | None
) -> date | None:
    """The first plausible date among the pass's dated values, in order of trust."""
    candidates: list[date | None] = [relevant.date() if relevant else None]
    relevant_dates = pass_.get("relevantDates")
    if isinstance(relevant_dates, list):
        for rd in relevant_dates:
            if isinstance(rd, dict):
                instant = _instant(rd.get("startDate") or rd.get("date"))
                candidates.append(instant.date() if instant else None)
    expiry = _instant(pass_.get("expirationDate"))
    candidates.append(expiry.date() if expiry else None)
    departure = _instant(semantics.get("originalDepartureDate"))
    candidates.append(departure.date() if departure else None)
    for f in _fields(body, (*FRONT, BACK)):
        text = _text(f)
        if text is None:
            continue
        instant = _instant(text)
        candidates.append(instant.date() if instant else _dated(text))
    return next((d for d in candidates if d is not None and _plausible(d.year)), None)


def _plausible(year: int) -> bool:
    return YEAR_FLOOR <= year <= date.today().year + YEARS_AHEAD


def _place_day(day_of_year: int, hint: date) -> date | None:
    """The date with that day of the year nearest `hint`, in the hint's year or a neighbour; the
    hint itself when the day is 0 (a pass read from its fields)."""
    if day_of_year == 0:
        return hint
    candidates: list[date] = []
    for year in (hint.year - 1, hint.year, hint.year + 1):
        candidate = date(year, 1, 1) + timedelta(days=day_of_year - 1)
        if candidate.year == year:
            candidates.append(candidate)
    return min(candidates, key=lambda d: abs((d - hint).days), default=None)


# -- tickets and other boarding passes ----------------------------------------------------------------------


def _event(
    pass_: dict[str, Any], body: dict[str, Any], style: str, prefix: str, timezone: str | None
) -> dict[str, Any] | None:
    semantics = _dict(pass_.get("semantics"))
    front = _fields(body)
    start_info = _dict(semantics.get("eventStartDateInfo"))
    start = (
        _instant(pass_.get("relevantDate"))
        or _instant(start_info.get("date"))
        or _instant(semantics.get("eventStartDate"))
        or _instant(semantics.get("originalDepartureDate"))
    )
    all_day = False
    if start is None:
        for f in front:
            text = _text(f)
            if text is None:
                continue
            start = _instant(text, timezone)
            if start is not None:
                break
            day = _dated(text)
            if day is not None and _plausible(day.year):
                start = datetime.combine(day, datetime.min.time(), ZoneInfo(timezone or "UTC"))
                all_day = True
                break
    if start is None:
        return None
    end = _instant(semantics.get("eventEndDate")) or _instant(semantics.get("originalArrivalDate"))
    if end is None:
        for f in front:
            if END.search(f["key"]) and (text := _text(f)):
                end = _instant(text, timezone)
                if end is not None:
                    break
    if all_day and end is None:
        end = start + timedelta(days=1)
    transit = body.get("transitType") if isinstance(body.get("transitType"), str) else None
    primary = [t for f in _fields(body, ("primaryFields",)) if (t := _text(f)) and _instant(t) is None]
    description = pass_.get("description") if isinstance(pass_.get("description"), str) else None
    if isinstance(semantics.get("eventName"), str):
        title: str | None = str(semantics["eventName"])
    elif style == "boardingPass" and len(primary) >= 2:
        title = f"{primary[0]} → {primary[1]}"
    else:
        header = [t for f in _fields(body, ("headerFields",)) if (t := _text(f)) and _instant(t) is None]
        title = next(iter(primary), None) or next(iter(header), None) or pass_.get("logoText") or description
    location = semantics.get("venueName") if isinstance(semantics.get("venueName"), str) else None
    if location is None:
        location = next((t for f in front if VENUE.search(f["key"]) and (t := _text(f))), None)
    fields = {f["key"]: t for f in front if not PRIVATE.search(f["key"]) and (t := _text(f))}
    locations = _locations(pass_.get("locations"))
    if not locations and isinstance(semantics.get("venueLocation"), dict):
        locations = _locations([_dict(semantics.get("venueLocation"))])
    extra: dict[str, Any] = {"pass_style": style}
    if transit:
        extra["transit_type"] = transit.removeprefix("PKTransitType").lower()
    if isinstance(pass_.get("organizationName"), str):
        extra["organization"] = pass_["organizationName"]
    if description:
        extra["description"] = description
    if fields:
        extra["fields"] = fields
    if locations:
        extra["locations"] = locations
    if pass_.get("voided") is True:
        extra["voided"] = True
    at = _utc(start)
    end_text = _utc(end) if end is not None else None
    mapped = (title, at, end_text, location, fields, locations)
    payload: dict[str, Any] = {
        "schema": EVENT_SCHEMA,
        "raw_id": f"{prefix}@{flights.digest(*mapped)}",
        "all_day": all_day,
    }
    if title:
        payload["title"] = title
    payload["calendar"] = {"id": pass_.get("passTypeIdentifier"), "name": pass_.get("organizationName")}
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


def _locations(value: object) -> list[dict[str, float]]:
    out: list[dict[str, float]] = []
    if isinstance(value, list):
        for loc in value[:5]:
            if isinstance(loc, dict):
                try:
                    out.append({"latitude": float(loc["latitude"]), "longitude": float(loc["longitude"])})
                except (KeyError, TypeError, ValueError):
                    continue
    return out


# -- dates -----------------------------------------------------------------------------------------------


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
