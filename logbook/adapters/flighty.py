"""Flighty CSV export → flight/v1 (RFC 0013), evidence `tracked`.

Flighty (Settings → Account Data → Export Your Flights) mails one CSV with these columns:

    Date, Airline, Flight, From, To, Dep Terminal, Dep Gate, Arr Terminal, Arr Gate, Canceled,
    Diverted To, Gate Departure (Scheduled), Gate Departure (Actual), Take off (Scheduled),
    Take off (Actual), Landing (Scheduled), Landing (Actual), Gate Arrival (Scheduled),
    Gate Arrival (Actual), Aircraft Type Name, Tail Number, PNR, Seat, Seat Type, Cabin Class,
    Flight Reason, Notes, Flight Flighty ID, Airline Flighty ID, Departure Airport Flighty ID,
    Arrival Airport Flighty ID, Diverted To Airport Flighty ID, Aircraft Type Flighty ID

Only `Date`, `Airline`, `Flight`, `From` and `To` are needed; every other column is optional and
its absence leaves the field absent (RFC 0013: never a guess). `Airline` is an ICAO designator
(`SWR`) in Flighty's own exports and an IATA one (`LX`) in some others; either is spelled as IATA
through the airlines table. `Flight` may repeat the carrier (`LX1210`); it is stripped.

Times are wall-clock at the airport with no offset (`2026-09-27T07:05`): departure and take-off at
`From`, landing and arrival at `To` — or at `Diverted To` when the flight was diverted — converted
to UTC with the airports table's zone. A time that carries `Z` or an offset is converted as it says.
An airport the table does not know leaves its times as text under `extra.<field>_local` and is
counted (`no_airport_zone`); `--airports` names a file that adds it. An arrival before its
departure is kept as given and counted (rule 7).

`raw_id` is the row's `Flight Flighty ID` (else the flight key) with a digest of the mapped row
(rule 6): an unchanged re-export appends nothing, an export that later carries the actual times is a
new observation that supersedes the earlier line (`flights.reconcile`). The PNR and the Notes are
never kept. Pure: one pass over the file, no network.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

from .. import flights
from ..flights import Airlines, Airports

NAME = "flighty"
KIND = flights.KIND
TIER = flights.TIER

ESSENTIAL = ("Date", "Airline", "Flight", "From", "To")
TIME_COLUMNS = {  # column → (field, which end's zone converts it)
    "Gate Departure (Scheduled)": ("scheduled_departure", "from"),
    "Gate Departure (Actual)": ("actual_departure", "from"),
    "Take off (Scheduled)": ("scheduled_takeoff", "from"),
    "Take off (Actual)": ("actual_takeoff", "from"),
    "Landing (Scheduled)": ("scheduled_landing", "to"),
    "Landing (Actual)": ("actual_landing", "to"),
    "Gate Arrival (Scheduled)": ("scheduled_arrival", "to"),
    "Gate Arrival (Actual)": ("actual_arrival", "to"),
}
EXTRA_COLUMNS = {
    "Dep Terminal": "departure_terminal",
    "Dep Gate": "departure_gate",
    "Arr Terminal": "arrival_terminal",
    "Arr Gate": "arrival_gate",
    "Seat": "seat",
    "Seat Type": "seat_type",
    "Cabin Class": "cabin",
    "Flight Reason": "reason",
}
NEVER = ("PNR", "Notes")  # a booking credential and the owner's words: never in the line
TRUE = ("true", "yes", "1")
SNIFF_BYTES = 4096
DIGITS = re.compile(r"0*(\d{1,4})([A-Z])?")


def sniff(path: Path) -> bool:
    """A CSV whose header has the five essential columns. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            head = fh.read(SNIFF_BYTES)
        header = head.decode("utf-8-sig", errors="replace").splitlines()[0] if head else ""
        columns = {c.strip() for c in next(csv.reader(io.StringIO(header)), [])}
        return all(c in columns for c in ESSENTIAL)
    except (OSError, ValueError, csv.Error):
        return False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    airports: Airports | None = None,
) -> Iterator[dict[str, Any]]:
    """One flight/v1 draft per row, in file order. `since` is RFC3339 UTC; rows whose `at` is
    before it are not yielded. `counts` tallies `skipped_no_date`, `skipped_bad_date`,
    `skipped_no_designator`, `skipped_no_route`, and notes `no_airport_zone` and
    `arrival_before_departure`. `airports` is the table to convert with (default: the built-in)."""
    counts = counts if counts is not None else {}
    airports = airports or Airports.load()
    airlines = Airlines.load()
    with Path(path).open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            draft = _draft(
                {(k or "").strip(): (v or "").strip() for k, v in row.items()}, airports, airlines, counts
            )
            if draft is not None and not (since and draft["at"] < since):
                yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _draft(
    row: dict[str, str], airports: Airports, airlines: Airlines, counts: dict[str, int]
) -> dict[str, Any] | None:
    day = row.get("Date", "")
    if not day:
        _count(counts, "skipped_no_date")
        return None
    try:
        day = date.fromisoformat(day).isoformat()
    except ValueError:
        _count(counts, "skipped_bad_date")
        return None
    code = row.get("Airline", "").upper()
    number = _number(row.get("Flight", ""), code, airlines)
    if not code or number is None:
        _count(counts, "skipped_no_designator")
        return None
    origin, destination = row.get("From", "").upper(), row.get("To", "").upper()
    if not origin or not destination:
        _count(counts, "skipped_no_route")
        return None
    carrier = airlines.iata(code)
    from_, to = flights.airport_ref(origin, airports), flights.airport_ref(destination, airports)
    diverted = row.get("Diverted To", "").upper()
    diverted_to = flights.airport_ref(diverted, airports) if diverted else None
    zones = {"from": _zone(origin, airports), "to": _zone(diverted or destination, airports)}
    times: dict[str, str | None] = {}
    extra: dict[str, Any] = {}
    unknown_zone = False
    for column, (field, end) in TIME_COLUMNS.items():
        local = row.get(column, "")
        if not local:
            continue
        zone = zones[end]
        if zone is None and not _has_zone(local):
            extra[f"{field}_local"] = local
            unknown_zone = True
            continue
        try:
            times[field] = flights.local_to_utc(local, zone or "UTC")
        except ValueError:
            extra[f"{field}_local"] = local
    if unknown_zone:
        _count(counts, "no_airport_zone")
    departed = times.get("actual_departure") or times.get("scheduled_departure")
    arrived = times.get("actual_arrival") or times.get("scheduled_arrival")
    if departed and arrived and arrived < departed:
        _count(counts, "arrival_before_departure")
    aircraft = {
        k: v
        for k, v in (
            ("type", row.get("Aircraft Type Name", "")),
            ("registration", row.get("Tail Number", "").upper()),
        )
        if v
    }
    for column, field in EXTRA_COLUMNS.items():
        if row.get(column):
            extra[field] = row[column]
    cancelled = row.get("Canceled", "").lower() in TRUE
    mapped = (day, carrier, number, from_, to, diverted_to, times, aircraft, cancelled, extra)
    stable = row.get("Flight Flighty ID") or flights.key_text((day, carrier, number))
    return flights.build(
        source=NAME,
        raw_id=f"{stable}@{flights.digest(*mapped)}",
        airports=airports,
        date=day,
        carrier=carrier,
        number=number,
        carrier_icao=airlines.icao(code),
        from_=from_,
        to=to,
        diverted_to=diverted_to,
        aircraft=aircraft or None,
        cancelled=True if cancelled else None,
        extra=extra or None,
        times=times,
    )


def _number(text: str, code: str, airlines: Airlines) -> str | None:
    """`561`, `0561`, `LX1210`, `SWR 1210` → the number without the carrier and its leading zeros."""
    text = text.strip().upper()
    for prefix in (code, airlines.iata(code), airlines.icao(code) or ""):
        if prefix and text.startswith(prefix):
            text = text[len(prefix) :].strip()
            break
    m = DIGITS.fullmatch(text)
    return None if m is None else f"{int(m.group(1))}{m.group(2) or ''}"


def _zone(code: str, airports: Airports) -> str | None:
    airport = airports.get(code)
    return airport.tz if airport is not None else None


def _has_zone(local: str) -> bool:
    return local.endswith("Z") or re.search(r"[+-]\d\d:?\d\d$", local) is not None
