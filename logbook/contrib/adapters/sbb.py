"""The SBB Mobile app's stores → journey/v1 (RFC 0020; `trip/v1` renamed by RFC 0031), mode `transit`, `sbb`.

Two stores from an iPhone backup carry what the owner bought and travelled:

    SbbMobile.db  (`AppDomainGroup-group.ch.sbb.SBBMobile`)
        TicketGroups      one row per purchase: groupId, orderItemIds (a JSON list), travelDate, validFrom
                          and validUntil (`YYYY-MM-DD HH-MM`, Swiss local time), the title's first and
                          last segment (the stations), tripType, the ticket type line, the number of persons
        PurchasedTickets  one row per ticket: orderItemId (joins the group), refundState, travelClass,
                          nativeTicket_price_amount and _currency, nativeTicket_productName — and the
                          traveller's name, date of birth, QR code, order reference, the rendered ticket,
                          none of which is read
    ch.sbb.coredata.pasttrips.sqlite  (`AppDomain-5Q4J53EFRC.com.sbb.ch`, Documents/)
        ZMYTRIP           one row per saved journey whose day has passed: ZVERBINDUNG, the connection as
                          the app's JSON (abfahrt/ankunft, abfahrtDate `dd.MM.yyyy`, abfahrtTime `HH:mm`,
                          transfers, realtimeInfo with the actual clocks, verbindungSections: one per leg
                          with its stations, coordinates in degrees, clocks and transportBezeichnung —
                          oevIcon ZUG/BUS/TRAM/SCHIFF, transportText `IC 8`)

`logbook import-backup` copies both out as `sbb/` and runs on `SbbMobile.db`; `run` takes either store
and reads the other beside it when it is there. A ticket group is one line (`raw_id` `ticket:<groupId>`,
`extra.observed` `ticket`): `at`/`end` the validity window — the day the ticket was for, not the hour the
owner travelled —, `from`/`to` the stations named on the ticket, `price` the sum of its tickets' amounts
as a decimal string with the currency, `status` `cancelled` when every ticket was refunded, the ticket
type, trip type, class, travel date and head count under `extra`; tier 3 when it carries a price (RFC
0020), else 1. A past journey is one line (`raw_id` `trip:<verbindungId>`, `extra.observed`
`journey`): `at`/`end` the planned departure and arrival, `from`/`to` the stations with their
coordinates, and under `extra` the transfers, the actual clocks when the app kept them, whether it
crossed a border, and the legs (`from`, `to`, `start`, `end`, `mode`, `line`); tier 1. The two are
not joined here: a ticket's validity and a journey's clocks are different observations, and matching
them is a reader's or an engine's step.

Clocks are Swiss local time (the app's own, also for a leg abroad) converted to UTC through
`Europe/Zurich`, which is also every line's `tz`. A group without a validity window and a journey
whose JSON does not parse or has no departure are skipped and counted. Pure: opened `mode=ro`,
`immutable=1`; no network.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

NAME = "sbb"
KIND = "journey"  # RFC 0031: the written form of RFC 0020 since 2026-10-05; readers accept `trip` too
SCHEMA = "journey/v1"
MODE = "transit"
PROVIDER = "sbb"
TIER = 1
TIER_WITH_PRICE = 3  # RFC 0020: a producer that carries a price sets 3

SQLITE_HEADER = b"SQLite format 3\x00"
ZONE_NAME = "Europe/Zurich"
ZONE = ZoneInfo(ZONE_NAME)
MOBILE_STORE = "SbbMobile.db"
TRIPS_STORE = "ch.sbb.coredata.pasttrips.sqlite"
MOBILE_TABLES = ("PurchasedTickets", "TicketGroups")
TRIPS_TABLES = ("ZMYTRIP",)
TICKET_COLUMNS = (
    "orderItemId",
    "refundState",
    "travelClass",
    "nativeTicket_price_amount",
    "nativeTicket_price_currency",
    "nativeTicket_productName",
)
GROUP_COLUMNS = (
    "groupId",
    "orderItemIds",
    "travelDate",
    "validFrom",
    "validUntil",
    "displayInfo_titleLine_firstSegment",
    "displayInfo_titleLine_lastSegment",
    "displayInfo_titleLine_tripType",
    "displayInfo_ticketTypeLine",
    "displayInfo_additionalInfoLine",
    "travelGroup_numberOfPersons",
)
NOT_REFUNDED = "NORMAL"
MODES = {
    "ZUG": "train",
    "BUS": "bus",
    "TRAM": "tram",
    "SCHIFF": "ferry",
    "METRO": "metro",
    "FUNICULAR": "funicular",
}
WALK = "walk"


def sniff(path: Path) -> bool:
    """SBB Mobile's ticket store or its past-trips store. Never raises."""
    path = Path(path)
    try:
        if not path.is_file():
            return False
        with path.open("rb") as fh:
            if fh.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                return False
        con = _open(path)
    except (OSError, ValueError, sqlite3.Error):
        return False
    try:
        tables = _tables(con)
        return all(t in tables for t in MOBILE_TABLES) or all(t in tables for t in TRIPS_TABLES)
    except sqlite3.Error:
        return False
    finally:
        con.close()


def _open(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: SQLite neither locks the file nor writes a journal beside it."""
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro&immutable=1", uri=True)


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(name) for (name,) in rows}


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f"PRAGMA table_info({table})")}


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    tier: int | None = None,
) -> Iterator[dict[str, Any]]:
    """One journey/v1 line per ticket group and per past journey, in `at` order.

    `since` is RFC3339 UTC; lines with `at` before it are not yielded. `counts` tallies
    `skipped_no_start` and `skipped_unreadable_json`. `tier` overrides the profile's (1, or 3 with a
    price)."""
    path = Path(path)
    counts = counts if counts is not None else {}
    lines: list[dict[str, Any]] = []
    for store in _stores(path):
        if not store.is_file():
            continue
        try:
            con = _open(store)
        except (OSError, ValueError, sqlite3.Error):
            continue
        try:
            tables = _tables(con)
            if all(t in tables for t in MOBILE_TABLES):
                lines.extend(_tickets(con, counts, tier))
            elif all(t in tables for t in TRIPS_TABLES):
                lines.extend(_journeys(con, counts, tier))
        except sqlite3.Error:
            continue
        finally:
            con.close()
    lines.sort(key=lambda line: (line["at"], line["payload"]["raw_id"]))
    for line in lines:
        if since and line["at"] < since:
            continue
        yield line


def _stores(path: Path) -> list[Path]:
    """The store given and its partner beside it, when the name is one of the two the app uses."""
    partners = {MOBILE_STORE: TRIPS_STORE, TRIPS_STORE: MOBILE_STORE}
    other = partners.get(path.name)
    return [path, path.with_name(other)] if other else [path]


# -- tickets -----------------------------------------------------------------------------------------


def _tickets(con: sqlite3.Connection, counts: dict[str, int], tier: int | None) -> Iterator[dict[str, Any]]:
    present = _columns(con, "PurchasedTickets")
    select = ", ".join(c if c in present else f"NULL AS {c}" for c in TICKET_COLUMNS)
    tickets: dict[str, dict[str, Any]] = {}
    for row in con.execute(f"SELECT {select} FROM PurchasedTickets"):
        values = dict(zip(TICKET_COLUMNS, row, strict=True))
        order_item = _text(values.get("orderItemId"))
        if order_item:
            tickets[order_item] = values
    present = _columns(con, "TicketGroups")
    select = ", ".join(c if c in present else f"NULL AS {c}" for c in GROUP_COLUMNS)
    for row in con.execute(f"SELECT {select} FROM TicketGroups ORDER BY validFrom, groupId"):
        group = dict(zip(GROUP_COLUMNS, row, strict=True))
        line = _ticket_line(group, tickets, counts, tier)
        if line is not None:
            yield line


def _ticket_line(
    group: dict[str, Any], tickets: dict[str, dict[str, Any]], counts: dict[str, int], tier: int | None
) -> dict[str, Any] | None:
    start = _validity(group.get("validFrom"))
    if start is None:
        _count(counts, "skipped_no_start")
        return None
    end = _validity(group.get("validUntil"))
    if end is not None and end <= start:
        end = None
    group_id = _text(group.get("groupId"))
    own = [tickets[item] for item in _order_items(group.get("orderItemIds")) if item in tickets]
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"ticket:{group_id}",
        "mode": MODE,
        "provider": PROVIDER,
    }
    origin = _text(group.get("displayInfo_titleLine_firstSegment"))
    destination = _text(group.get("displayInfo_titleLine_lastSegment"))
    payload["from"] = {"name": origin or destination or "?"}
    payload["to"] = {"name": destination or origin or "?"}
    price = _price(own)
    if price is not None:
        payload["price"] = price
    if own and all(_text(t.get("refundState")).upper() not in ("", NOT_REFUNDED) for t in own):
        payload["status"] = "cancelled"
    extra: dict[str, Any] = {"observed": "ticket"}
    travel_date = _text(group.get("travelDate"))
    if travel_date:
        extra["travel_date"] = travel_date
    ticket_type = _text(group.get("displayInfo_ticketTypeLine")) or _first(own, "nativeTicket_productName")
    if ticket_type:
        extra["ticket_type"] = ticket_type
    trip_type = _text(group.get("displayInfo_titleLine_tripType")).lower()
    if trip_type:
        extra["trip_type"] = trip_type
    classes = {_text(t.get("travelClass")).lower() for t in own if _text(t.get("travelClass"))}
    if len(classes) == 1:
        extra["travel_class"] = classes.pop()
    persons = group.get("travelGroup_numberOfPersons")
    if isinstance(persons, int) and not isinstance(persons, bool) and persons > 0:
        extra["persons"] = persons
    if own:
        extra["tickets"] = len(own)
    note = _text(group.get("displayInfo_additionalInfoLine"))
    if note:
        extra["note"] = note
    payload["extra"] = extra
    return _line(start, end, payload, tier if tier is not None else (TIER_WITH_PRICE if price else TIER))


def _order_items(value: object) -> list[str]:
    """The group's order item ids: a JSON list kept as a blob or text."""
    text = _text(value)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return []
    return [str(item) for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _price(tickets: list[dict[str, Any]]) -> dict[str, str] | None:
    """The sum of the tickets' amounts when every priced ticket shares one currency, as RFC 0020
    wants it: a decimal string and an ISO 4217 code."""
    amounts: list[float] = []
    currencies: set[str] = set()
    for t in tickets:
        amount = t.get("nativeTicket_price_amount")
        if isinstance(amount, bool) or not isinstance(amount, int | float):
            continue
        currency = _text(t.get("nativeTicket_price_currency")).upper()
        if not currency:
            continue
        amounts.append(float(amount))
        currencies.add(currency)
    if not amounts or len(currencies) != 1:
        return None
    return {"amount": f"{sum(amounts):.2f}", "currency": currencies.pop()}


def _first(tickets: list[dict[str, Any]], column: str) -> str:
    for t in tickets:
        text = _text(t.get(column))
        if text:
            return text
    return ""


def _validity(value: object) -> datetime | None:
    """`YYYY-MM-DD HH-MM` in Swiss local time → an aware instant."""
    text = _text(value)
    try:
        return datetime.strptime(text, "%Y-%m-%d %H-%M").replace(tzinfo=ZONE)
    except ValueError:
        return None


# -- journeys ----------------------------------------------------------------------------------------


def _journeys(con: sqlite3.Connection, counts: dict[str, int], tier: int | None) -> Iterator[dict[str, Any]]:
    columns = _columns(con, "ZMYTRIP")
    if "ZVERBINDUNG" not in columns:
        return
    for pk, text in con.execute("SELECT Z_PK, ZVERBINDUNG FROM ZMYTRIP ORDER BY Z_PK"):
        try:
            data = json.loads(_text(text))
        except ValueError:
            _count(counts, "skipped_unreadable_json")
            continue
        if not isinstance(data, dict):
            _count(counts, "skipped_unreadable_json")
            continue
        line = _journey_line(data, pk, counts, tier)
        if line is not None:
            yield line


def _journey_line(
    data: dict[str, Any], pk: object, counts: dict[str, int], tier: int | None
) -> dict[str, Any] | None:
    start = _clock(data.get("abfahrtDate"), data.get("abfahrtTime"))
    if start is None:
        _count(counts, "skipped_no_start")
        return None
    end = _clock(data.get("ankunftDate"), data.get("ankunftTime"))
    if end is not None and end <= start:
        end = None
    sections = [s for s in data.get("verbindungSections") or [] if isinstance(s, dict)]
    first = sections[0] if sections else {}
    last = sections[-1] if sections else {}
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "raw_id": f"trip:{_text(data.get('verbindungId')) or f'row{pk}'}",
        "mode": MODE,
        "provider": PROVIDER,
        "from": _place(
            _text(data.get("abfahrt")) or _text(first.get("abfahrtName")), first.get("abfahrtKoordinaten")
        ),
        "to": _place(
            _text(data.get("ankunft")) or _text(last.get("ankunftName")), last.get("ankunftKoordinaten")
        ),
    }
    extra: dict[str, Any] = {"observed": "journey"}
    transfers = data.get("transfers")
    if isinstance(transfers, int) and not isinstance(transfers, bool):
        extra["transfers"] = transfers
    realtime = data.get("realtimeInfo")
    if isinstance(realtime, dict):
        actual_start = _clock(realtime.get("abfahrtIstDatum"), realtime.get("abfahrtIstZeit"))
        actual_end = _clock(realtime.get("ankunftIstDatum"), realtime.get("ankunftIstZeit"))
        if actual_start is not None and actual_start != start:
            extra["actual_start"] = _stamp(actual_start)
        if actual_end is not None and end is not None and actual_end != end:
            extra["actual_end"] = _stamp(actual_end)
    if data.get("isInternationalVerbindung") is True:
        extra["international"] = True
    legs = [leg for leg in (_leg(s) for s in sections) if leg is not None]
    if legs:
        extra["legs"] = legs
    payload["extra"] = extra
    return _line(start, end, payload, tier if tier is not None else TIER)


def _leg(section: dict[str, Any]) -> dict[str, Any] | None:
    start = _clock(section.get("abfahrtDatum"), section.get("abfahrtTime"))
    end = _clock(section.get("ankunftDatum"), section.get("ankunftTime"))
    leg: dict[str, Any] = {}
    if _text(section.get("abfahrtName")):
        leg["from"] = _text(section.get("abfahrtName"))
    if _text(section.get("ankunftName")):
        leg["to"] = _text(section.get("ankunftName"))
    if start is not None:
        leg["start"] = _stamp(start)
    if end is not None:
        leg["end"] = _stamp(end)
    transport = section.get("transportBezeichnung")
    if isinstance(transport, dict):
        icon = _text(transport.get("oevIcon")).upper()
        leg["mode"] = MODES.get(icon, icon.lower() or WALK)
        line_name = _text(transport.get("transportText")) or _text(transport.get("transportLabel"))
        if line_name:
            leg["line"] = line_name
    else:
        leg["mode"] = WALK
    return leg or None


def _place(name: str, coordinates: object) -> dict[str, Any]:
    place: dict[str, Any] = {"name": name or "?"}
    if isinstance(coordinates, dict):
        lat = _number(coordinates.get("latitudeInDegrees"))
        lon = _number(coordinates.get("longitudeInDegrees"))
        if (
            lat is not None
            and lon is not None
            and -90 <= lat <= 90
            and -180 <= lon <= 180
            and (lat, lon) != (0, 0)
        ):
            place["latitude"], place["longitude"] = _round(lat), _round(lon)
    return place


def _clock(day: object, time_of_day: object) -> datetime | None:
    """`dd.MM.yyyy` and `HH:mm`, Swiss local time → an aware instant; None when either is missing."""
    day_text, clock_text = _text(day), _text(time_of_day)
    if not day_text or not clock_text:
        return None
    try:
        return datetime.strptime(f"{day_text} {clock_text}", "%d.%m.%Y %H:%M").replace(tzinfo=ZONE)
    except ValueError:
        return None


# -- shared ------------------------------------------------------------------------------------------


def _line(start: datetime, end: datetime | None, payload: dict[str, Any], tier: int) -> dict[str, Any]:
    return {
        "at": _stamp(start),
        "end": _stamp(end) if end is not None else None,
        "tz": ZONE_NAME,
        "source": NAME,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _text(value: object) -> str:
    if isinstance(value, bytes | bytearray | memoryview):
        try:
            return bytes(value).decode("utf-8").strip()
        except UnicodeDecodeError:
            return ""
    return value.strip() if isinstance(value, str) else ""


def _number(value: object) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _round(value: int | float) -> int | float:
    rounded = round(float(value), 6)
    return int(rounded) if rounded == int(rounded) else rounded


def _stamp(when: datetime) -> str:
    return when.astimezone(UTC).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"
