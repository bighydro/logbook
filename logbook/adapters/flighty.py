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

**The app's own store.** An iPhone backup carries Flighty's database, `MainFlightyDatabase.db` in
the app's container (`AppDomain-com.flightyapp.flighty`); `logbook import-backup` copies it out
(source `flighty`) and runs this adapter on the copy, and `sniff` knows it by its tables. The same
mapping reads it (ADR 0017): `Flight` (one row per flight: `number`, the airports and airline by
id, gate and runway times — original, estimated, actual — as Unix seconds, terminals, gates, the
aircraft's model and tail number, `isCancelled`) joined to `UserFlight` (only the owner's flights,
`isMyFlight`, not deleted), `Airport` (IATA, ICAO, zone), `Airline` (IATA, ICAO) and the owner's
`Ticket` (seat, seat position, cabin, reason; the `pnr` column is never read). Original gate and
runway times are the scheduled ones, actual the actual; estimates are not kept. `date` is the local
date of the scheduled gate departure in the origin's zone, the store's own when the shipped table
does not know the airport. A flight whose actual arrival airport is not the scheduled one carries
`diverted_to`. `raw_id` is the store's flight id with the same digest the export gets, so a flight
in both the backup and a CSV export is one observation and the second appends nothing; when one
carries more (an actual time the other lacks) it is a new observation of the same flight and the
merge supersedes the earlier line. Opened `mode=ro`, `immutable=1`; no network.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
SQLITE_HEADER = b"SQLite format 3\x00"
STORE_TABLES = ("Flight", "UserFlight", "Airport", "Airline")
STORE_TIMES = {  # Flight column → flight/v1 field; estimates are not observations
    "departureScheduleGateOriginal": "scheduled_departure",
    "departureScheduleGateActual": "actual_departure",
    "departureScheduleRunwayOriginal": "scheduled_takeoff",
    "departureScheduleRunwayActual": "actual_takeoff",
    "arrivalScheduleRunwayOriginal": "scheduled_landing",
    "arrivalScheduleRunwayActual": "actual_landing",
    "arrivalScheduleGateOriginal": "scheduled_arrival",
    "arrivalScheduleGateActual": "actual_arrival",
}
STORE_EXTRA = {  # Flight / Ticket column → the export's extra key, so the digests agree
    "departureTerminal": "departure_terminal",
    "departureGate": "departure_gate",
    "arrivalTerminal": "arrival_terminal",
    "arrivalGate": "arrival_gate",
    "seatNumber": "seat",
    "seatPosition": "seat_type",
    "cabinClass": "cabin",
    "flightReason": "reason",
}
STORE_COLUMNS = (  # of Flight; one the store lacks reads as NULL
    "id",
    "number",
    "airlineId",
    "departureAirportId",
    "scheduledArrivalAirportId",
    "actualArrivalAirportId",
    "isCancelled",
    "equipmentModelName",
    "equipmentTailNumber",
    "departureTerminal",
    "departureGate",
    "arrivalTerminal",
    "arrivalGate",
    *STORE_TIMES,
)
TICKET_COLUMNS = ("seatNumber", "seatPosition", "cabinClass", "flightReason")  # never `pnr`


def sniff(path: Path) -> bool:
    """A CSV whose header has the five essential columns, or the app's own SQLite store. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            head = fh.read(SNIFF_BYTES)
        if head.startswith(SQLITE_HEADER):
            return _is_store(path)
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
    if _is_sqlite(Path(path)):
        for line in _store_drafts(Path(path), airports, airlines, counts):
            if not (since and line["at"] < since):
                yield line
        return
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


# -- the app's own store -----------------------------------------------------------------------------------


def _is_sqlite(path: Path) -> bool:
    try:
        with path.open("rb") as fh:
            return fh.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _is_store(path: Path) -> bool:
    try:
        con = _open(path)
    except sqlite3.Error:
        return False
    try:
        return all(t in _tables(con) for t in STORE_TABLES)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    return {str(name) for (name,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def _store_drafts(
    path: Path, airports: Airports, airlines: Airlines, counts: dict[str, int]
) -> Iterator[dict[str, Any]]:
    """One draft per flight of the owner's in `MainFlightyDatabase.db`, in scheduled-departure order."""
    con = _open(path)
    try:
        have = _columns(con, "Flight")
        select = [f"f.{c}" if c in have else f"NULL AS {c}" for c in STORE_COLUMNS]
        ticket = "Ticket" in _tables(con)
        ticket_have = _columns(con, "Ticket") if ticket else set()
        select += [f"t.{c}" if c in ticket_have else f"NULL AS {c}" for c in TICKET_COLUMNS]
        joins = [
            "JOIN UserFlight u ON u.flightId = f.id AND u.isMyFlight = 1 AND u.deleted IS NULL",
            "LEFT JOIN Airport da ON da.id = f.departureAirportId",
            "LEFT JOIN Airport sa ON sa.id = f.scheduledArrivalAirportId",
            "LEFT JOIN Airport aa ON aa.id = f.actualArrivalAirportId",
            "LEFT JOIN Airline al ON al.id = f.airlineId",
        ]
        if ticket:
            joins.append(
                "LEFT JOIN Ticket t ON t.flightId = f.id AND t.userId = u.userId AND t.deleted IS NULL"
            )
        select += [
            "da.iata AS from_iata", "da.icao AS from_icao", "da.timeZoneIdentifier AS from_tz",
            "sa.iata AS to_iata", "sa.icao AS to_icao",
            "aa.iata AS actual_iata", "aa.icao AS actual_icao",
            "al.iata AS airline_iata", "al.icao AS airline_icao",
        ]  # fmt: skip
        names = [c.split(" AS ")[-1].split(".")[-1] for c in select]
        query = (
            f"SELECT {', '.join(select)} FROM Flight f {' '.join(joins)} WHERE f.deleted IS NULL"
            " ORDER BY f.departureScheduleGateOriginal, f.id"
        )
        seen: set[str] = set()
        for row in con.execute(query):
            values = dict(zip(names, row, strict=True))
            if values["id"] in seen:
                continue  # a second ticket row for the same flight
            seen.add(str(values["id"]))
            draft = _store_draft(values, airports, airlines, counts)
            if draft is not None:
                yield draft
    finally:
        con.close()


def _store_draft(
    values: dict[str, Any], airports: Airports, airlines: Airlines, counts: dict[str, int]
) -> dict[str, Any] | None:
    code = str(values.get("airline_iata") or values.get("airline_icao") or "").upper()
    number = _number(str(values.get("number") or ""), code, airlines)
    if not code or number is None:
        _count(counts, "skipped_no_designator")
        return None
    origin = str(values.get("from_iata") or values.get("from_icao") or "").upper()
    destination = str(values.get("to_iata") or values.get("to_icao") or "").upper()
    if not origin or not destination:
        _count(counts, "skipped_no_route")
        return None
    times: dict[str, str | None] = {}
    for column, field in STORE_TIMES.items():
        seconds = values.get(column)
        if isinstance(seconds, int | float) and not isinstance(seconds, bool) and seconds > 0:
            times[field] = datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    departed = times.get("scheduled_departure") or times.get("actual_departure")
    if departed is None:
        _count(counts, "skipped_no_date")
        return None
    zone = _zone(origin, airports) or (
        values.get("from_tz") if isinstance(values.get("from_tz"), str) else None
    )
    if zone is None:
        _count(counts, "no_airport_zone")
    try:
        day = (
            datetime.fromisoformat(departed.replace("Z", "+00:00")).astimezone(ZoneInfo(zone or "UTC")).date()
        )
    except (ValueError, KeyError):
        day = datetime.fromisoformat(departed.replace("Z", "+00:00")).date()
    carrier = airlines.iata(code)
    from_ = _store_ref(values.get("from_iata"), values.get("from_icao"), airports)
    to = _store_ref(values.get("to_iata"), values.get("to_icao"), airports)
    actual = _store_ref(values.get("actual_iata"), values.get("actual_icao"), airports)
    diverted_to = actual if actual and actual != to else None
    aircraft = {
        k: v
        for k, v in (
            ("type", str(values.get("equipmentModelName") or "")),
            ("registration", str(values.get("equipmentTailNumber") or "").upper()),
        )
        if v
    }
    extra: dict[str, Any] = {}
    for column, field in STORE_EXTRA.items():
        value = values.get(column)
        if isinstance(value, str) and value.strip():
            extra[field] = value.strip()
    cancelled = bool(values.get("isCancelled"))
    mapped = (day.isoformat(), carrier, number, from_, to, diverted_to, times, aircraft, cancelled, extra)
    draft = flights.build(
        source=NAME,
        raw_id=f"{values['id']}@{flights.digest(*mapped)}",
        airports=airports,
        date=day.isoformat(),
        carrier=carrier,
        number=number,
        carrier_icao=airlines.icao(code)
        or (str(values["airline_icao"]) if values.get("airline_icao") else None),
        from_=from_,
        to=to,
        diverted_to=diverted_to,
        aircraft=aircraft or None,
        cancelled=True if cancelled else None,
        extra=extra or None,
        times=times,
    )
    if draft["tz"] is None and zone:
        draft["tz"] = zone
    return draft


def _store_ref(iata: object, icao: object, airports: Airports) -> dict[str, str]:
    """`{iata, icao}` as the shipped table spells the airport, else as the store does."""
    code = str(iata or icao or "").upper()
    if not code:
        return {}
    if airports.get(code) is not None:
        return flights.airport_ref(code, airports)
    ref: dict[str, str] = {}
    if iata:
        ref["iata"] = str(iata).upper()
    if icao:
        ref["icao"] = str(icao).upper()
    return ref
