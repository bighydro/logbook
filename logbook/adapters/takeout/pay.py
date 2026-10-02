"""Google Takeout Google Pay/ → transaction/v1 (RFC 0021) for the transactions, event/v1 (RFC 0009) for
the passes that are tickets.

Takeout writes `Takeout/Google Pay/Google transactions/transactions_<account>.csv` — `Time`,
`Transaction ID`, `Description`, `Product`, `Payment Method`, `Status`, `Amount`, `Fee`, `Net Amount`,
the amount as text with the currency in it (`-129.00 NOK`, `NOK 2450.00`, `€4,99`) — and
`Takeout/Google Pay/Passes/<id>.json`, one JSON per pass in Wallet, with `classType` (`EVENT_TICKET`,
`TRANSIT`, `FLIGHT`, `LOYALTY`, `OFFER`, `GIFT_CARD`), `state`, `issuerName` and the fields of its
class. Google renames and reorders the CSV columns between exports, so they are found by what the
header says, not by position; a pass is read by looking for the keys a ticket has, wherever its class
nests them. The input is the `Google Pay/` folder, either folder under it, one CSV or one pass.

**A transaction is a line**: kind `transaction`, tier 3 (RFC 0021: money, always; `--tier` is not an
option of this adapter), source `google-takeout`, `provider` `google-pay`, `at` the `Time` in UTC,
`tz` the record's zone, `raw_id` `pay:<Transaction ID>`. `amount` is signed from the owner's side
(rule 2): the sign the text carries when it has one, else negative — money left — unless the status,
product or description says refund, received, reversal or credit. `currency` is the ISO code in the
amount text, or the symbol's code (`€` EUR, `£` GBP, `$` USD); `kr` names three currencies, so a row
with no code is skipped and counted (`skipped_no_currency`), as is a row with no amount or no time.
`merchant` is the description, `account` the payment method as shown (a masked card), `status`
`posted` for Completed, `pending` for Pending, else the word lower-cased; `date` the day in the
record's zone when it differs from the UTC day. The product, the amount text as written, the fee and
the net amount go under `extra`.

**A ticket is an event**: an `EVENT_TICKET`, a `TRANSIT` pass or a `FLIGHT` pass is one `event/v1`
line, tier 1, kind `event`: `at` from the pass's start (`dateTime.start`, `validTimeInterval.start`,
a local scheduled departure), `end` from its end when it has one; a local time with no zone is read
in the record's zone and `extra.local_times` says so. The title is the event name, else `origin →
destination` (a flight as `XY 561 OSL → ZRH`); `location` the venue's name and address; `calendar`
the pass class and the issuer. `raw_id` is `pay-pass:<id>`. The class, the state, the seat, the gate,
the terminal and the transit type go under `extra`. The ticket holder's name, the passenger's name,
an account id: never. A loyalty card, an offer and a gift card are not lines, counted; a ticket with
no date is counted (`skipped_no_date`). Pure: no network, never writes the source.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import SOURCE, times
from .meet import columns

NAME = "google-takeout-pay"
FOLDER = "Google Pay"
PROVIDER = "google-pay"
TRANSACTION_KIND = "transaction"
TRANSACTION_TIER = 3
TRANSACTION_SCHEMA = "transaction/v1"
EVENT_KIND = "event"
EVENT_TIER = 1
EVENT_SCHEMA = "event/v1"

SNIFF_BYTES = 4096
COLUMNS = {
    "time": ("time",),
    "id": ("transaction", "id"),
    "description": ("description",),
    "product": ("product",),
    "method": ("payment", "method"),
    "status": ("status",),
    "amount": ("amount",),
    "fee": ("fee",),
    "net": ("net",),
}
REQUIRED = ("time", "id", "amount")
CODE = re.compile(r"\b([A-Z]{3})\b")
SYMBOLS = {"€": "EUR", "£": "GBP", "$": "USD"}
NUMBER = re.compile(r"[-+]?\d[\d.,]*")
INCOMING = ("refund", "received", "reversal", "credit")
STATUS = {"completed": "posted", "pending": "pending"}

TICKETS = ("EVENT_TICKET", "TRANSIT", "FLIGHT")
SKIPPED_CLASS = {
    "LOYALTY": "skipped_store_cards",
    "OFFER": "skipped_coupons",
    "GIFT_CARD": "skipped_gift_cards",
}
CLASS_KEYS = ("classType", "class_type", "passType")
KNOWN_CLASSES = frozenset(("EVENT_TICKET", "TRANSIT", "FLIGHT", "LOYALTY", "OFFER", "GIFT_CARD", "GENERIC"))
PASS_MARKS = ("id", "state", "issuerName")  # a pass has at least one of these beside its class
START_KEYS = (
    "dateTime.start",
    "validTimeInterval.start",
    "startDateTime",
    "start",
    "localScheduledDepartureDateTime",
    "localEstimatedOrActualDepartureDateTime",
)
END_KEYS = (
    "dateTime.end",
    "validTimeInterval.end",
    "endDateTime",
    "end",
    "localEstimatedOrActualArrivalDateTime",
    "localScheduledArrivalDateTime",
)
TITLE_KEYS = ("eventName", "title", "name", "header")
NEVER = ("name", "passenger", "holder", "account", "member", "barcode", "ticketnumber", "confirmation", "pnr")


def sniff(path: Path) -> bool:
    """A Pay transactions CSV, a pass JSON, or a folder holding either directly or one folder down.
    Never raises."""
    path = Path(path)
    try:
        return bool(_files(path)) if path.is_dir() else _kind_of(path) is not None
    except OSError:
        return False


def _kind_of(path: Path) -> str | None:
    """`transactions`, `pass` or None, from the file's name and first bytes."""
    if not path.is_file():
        return None
    suffix = path.suffix.lower()
    if suffix not in (".csv", ".json"):
        return None
    with path.open("rb") as fh:
        head = fh.read(SNIFF_BYTES)
    if suffix == ".csv":
        header = head.split(b"\n", 1)[0].lower()
        return (
            "transactions" if b"transaction" in header and b"amount" in header and b"time" in header else None
        )
    if head.lstrip().startswith(b"{") and _pass(path) is not None:
        return "pass"
    return None


def _pass(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not _class(data) or not any(k in data for k in PASS_MARKS):
        return None
    return data


def _class(data: dict[str, Any]) -> str:
    """The pass's class from a class key; a bare `type` counts only when it names a known class, so a
    GeoJSON `type` never makes a file a pass."""
    for key in CLASS_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    value = data.get("type")
    if isinstance(value, str) and value.strip().upper() in KNOWN_CLASSES:
        return value.strip().upper()
    return ""


def _files(folder: Path) -> list[Path]:
    found = [f for f in sorted(folder.iterdir()) if _kind_of(f) is not None]
    for sub in sorted(d for d in folder.iterdir() if d.is_dir()):
        found.extend(f for f in sorted(sub.iterdir()) if _kind_of(f) is not None)
    return found


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
) -> Iterator[dict[str, Any]]:
    """One transaction/v1 line draft per row of the transactions CSV and one event/v1 draft per ticket
    pass at or under `path`, oldest first. `since` is RFC3339 UTC; `timezone` is the record's zone."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = [path] if path.is_file() else _files(path)
    tz = timezone or "UTC"
    drafts: list[dict[str, Any]] = []
    for file in files:
        kind = _kind_of(file)
        if kind == "transactions":
            drafts.extend(_transactions(file, tz, counts))
        elif kind == "pass":
            draft = _ticket(file, tz, counts)
            if draft is not None:
                drafts.append(draft)
    for draft in sorted(drafts, key=lambda d: (d["at"], d["payload"]["raw_id"])):
        if since is None or draft["at"] >= since:
            yield draft


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _transactions(file: Path, tz: str, counts: dict[str, int]) -> Iterator[dict[str, Any]]:
    with file.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            return
        at_col = columns(header, COLUMNS)
        if any(field not in at_col for field in REQUIRED):
            return

        def cell(row: list[str], field: str) -> str:
            i = at_col.get(field)
            return row[i].strip() if i is not None and i < len(row) else ""

        for row in reader:
            if not any(c.strip() for c in row):
                continue
            at, _spelled = times.parse(cell(row, "time"))
            if at is None:
                _count(counts, "skipped_no_timestamp")
                continue
            text = cell(row, "amount")
            description, product, status = cell(row, "description"), cell(row, "product"), cell(row, "status")
            amount = _amount(text, incoming=_incoming(status, product, description))
            if amount is None:
                _count(counts, "skipped_no_amount")
                continue
            currency = _currency(text)
            if not currency:
                _count(counts, "skipped_no_currency")
                continue
            raw_id = f"pay:{cell(row, 'id')}"
            payload: dict[str, Any] = {
                "schema": TRANSACTION_SCHEMA,
                "raw_id": raw_id,
                "amount": amount,
                "currency": currency,
            }
            if description:
                payload["merchant"] = " ".join(description.split())
            local_day = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date()
            if local_day.isoformat() != at[:10]:
                payload["date"] = local_day.isoformat()
            if method := cell(row, "method"):
                payload["account"] = method
            payload["provider"] = PROVIDER
            if status:
                payload["status"] = STATUS.get(status.lower(), status.lower())
            extra: dict[str, Any] = {}
            if product:
                extra["product"] = product
            extra["amount_text"] = text
            if fee := cell(row, "fee"):
                extra["fee"] = fee
            if net := cell(row, "net"):
                extra["net_amount"] = net
            payload["extra"] = extra
            yield _line(at, None, tz, TRANSACTION_KIND, TRANSACTION_TIER, payload)


def _incoming(*texts: str) -> bool:
    lowered = " ".join(texts).lower()
    return any(word in lowered for word in INCOMING)


def _amount(text: str, incoming: bool) -> float | None:
    """The signed number in an amount text: the sign it carries, else negative unless `incoming`.
    `€4,99` is 4.99; `1.234,56` and `1,234.56` are both 1234.56."""
    m = NUMBER.search(text.replace(chr(0x2212), "-"))  # a typographic minus sign
    if m is None:
        return None
    body = m.group(0)
    sign = -1.0 if body.startswith("-") else 1.0 if body.startswith("+") else (1.0 if incoming else -1.0)
    digits = body.lstrip("+-")
    if "," in digits and "." in digits:
        decimal = "," if digits.rfind(",") > digits.rfind(".") else "."
        digits = digits.replace("." if decimal == "," else ",", "").replace(",", ".")
    elif "," in digits:
        head, _, tail = digits.rpartition(",")
        digits = f"{head.replace(',', '')}.{tail}" if len(tail) in (1, 2) else digits.replace(",", "")
    try:
        return sign * float(digits)
    except ValueError:
        return None


def _currency(text: str) -> str:
    m = CODE.search(text)
    if m:
        return m.group(1)
    return next((code for symbol, code in SYMBOLS.items() if symbol in text), "")


def _ticket(file: Path, tz: str, counts: dict[str, int]) -> dict[str, Any] | None:
    data = _pass(file)
    if data is None:
        return None
    kind = _class(data)
    if kind not in TICKETS:
        _count(counts, SKIPPED_CLASS.get(kind, "skipped_unknown_style"))
        return None
    flat = _flatten(data)
    start, start_local = _when(flat, START_KEYS, tz)
    if start is None:
        _count(counts, "skipped_no_date")
        return None
    end, end_local = _when(flat, END_KEYS, tz)
    pass_id = str(data.get("id") or "").strip()
    title = _title(data, flat)
    raw_id = (
        f"pay-pass:{pass_id}"
        if pass_id
        else f"pay-pass:{hashlib.sha256(f'{title}|{start}'.encode()).hexdigest()[:16]}"
    )
    payload: dict[str, Any] = {"schema": EVENT_SCHEMA, "raw_id": raw_id}
    if title:
        payload["title"] = title
    calendar: dict[str, str] = {"id": f"{PROVIDER}:{kind.lower()}"}
    issuer = " ".join(str(data.get("issuerName") or data.get("issuer") or "").split())
    if issuer:
        calendar["name"] = issuer
    payload["calendar"] = calendar
    payload["all_day"] = False
    location = _location(data)
    if location:
        payload["location"] = location
    extra: dict[str, Any] = {"pass_type": kind}
    if state := str(data.get("state") or "").strip():
        extra["state"] = state
    if (seat := _seat(data)) is not None:
        extra["seat"] = seat
    for key in ("gate", "terminal"):
        value = flat.get(f"origin.{key}")
        if isinstance(value, str) and value.strip():
            extra[key] = value.strip()
    if transit := str(data.get("transitType") or "").strip():
        extra["transit_type"] = transit
    if start_local or end_local:
        extra["local_times"] = True
    payload["extra"] = extra
    return _line(start, end, tz, EVENT_KIND, EVENT_TIER, payload)


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def _when(flat: dict[str, Any], keys: tuple[str, ...], tz: str) -> tuple[str | None, bool]:
    """(instant in UTC, whether it was a local time with no zone) for the first of `keys` found."""
    for key in keys:
        value = flat.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            when = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            at, _spelled = times.parse(value)
            if at is not None:
                return at, False
            continue
        if when.tzinfo is None:
            return when.replace(tzinfo=ZoneInfo(tz)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), True
        return when.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), False
    return None, False


def _title(data: dict[str, Any], flat: dict[str, Any]) -> str:
    for key in TITLE_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    flight = _flight(flat)
    origin = _place(data.get("origin"))
    destination = _place(data.get("destination"))
    route = f"{origin} → {destination}" if origin and destination else origin or destination
    return " ".join(part for part in (flight, route) if part)


def _flight(flat: dict[str, Any]) -> str:
    carrier = next((str(v) for k, v in flat.items() if k.lower().endswith("carrieriatacode") and v), "")
    number = next((str(v) for k, v in flat.items() if k.lower().endswith("flightnumber") and v), "")
    return f"{carrier} {number}".strip()


def _place(value: object) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        for key in ("name", "airportIataCode", "stationName", "code"):
            if isinstance(value.get(key), str) and value[key].strip():
                return " ".join(str(value[key]).split())
    return ""


def _location(data: dict[str, Any]) -> str:
    venue: dict[str, Any] = data["venue"] if isinstance(data.get("venue"), dict) else {}
    parts = [" ".join(str(venue.get(k) or "").split()) for k in ("name", "address")]
    if not any(parts) and isinstance(data.get("location"), str):
        parts = [" ".join(str(data["location"]).split())]
    return ", ".join(p for p in parts if p)


def _seat(data: dict[str, Any]) -> object:
    seating = data.get("boardingAndSeatingInfo")
    if isinstance(seating, dict) and seating.get("seatNumber"):
        return str(seating["seatNumber"])
    info = data.get("seatInfo")
    if isinstance(info, dict):
        kept = {k: str(v) for k, v in info.items() if isinstance(v, str | int) and v != ""}
        return kept or None
    return None


def _line(at: str, end: str | None, tz: str, kind: str, tier: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"at": at, "end": end, "tz": tz, "source": SOURCE, "kind": kind, "tier": tier, "payload": payload}
