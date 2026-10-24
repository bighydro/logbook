"""The ledger: the record's money read back in context — `logbook ledger [--month YYYY-MM | --trip
ID] [--json]` and `logbook rollup money`.

A `transaction/v1` line (RFC 0021) is one movement of money as the app recorded it: an amount in a
currency, a merchant, the app's own category. It is tier 3, and it never crosses (RFC 0005, ADR
0016). What the line does not say is where the owner was: the ledger says it. Every transaction of
the window is placed at the stay the owner was in at its instant (`stays.derive`, the same stays the
Day and the trips read): the place's name when the stay is at a named place, `aboard <asset>` when
it is aboard one, else the coordinates with what is near, the rule the trips' route uses
(`trips.coordinates_label`); and the country of that stay, by `rollup countries`' rule. A
transaction the source files by the day only (`date` given and `at` that day's local midnight,
RFC 0021 rule 5) has no instant: it is placed by the day, at the stay that held the longest part of
the day, and says so (`by: "day"`). A transaction at an instant the track does not cover is
nowhere, and says so. Each transaction is then in its trip when its day is inside one
(`trips.trips`: the first day to the return day), and the trips of the window are listed with
their spend.

A shared expense (Splitwise, `extra.members`) shows its shares per person: each member's ref
resolved through the record's resolution lines (RFC 0006, `present.resolve_ref`) to the person it
names, else the name the app shows; the owner's own member is `you`. A photo library's face tag
is never a resolution here: a member is a person the record names, or the app's word.

Amounts are in the line's currency, signed from the owner's side (negative out, positive in), and
nothing is converted: every total is per currency. A transaction the source marks deleted
(`extra.deleted`) is listed, marked, and never counted or summed. A correction that `supersedes` an
earlier line stands in its place; a retracted line is out. `rollup money` sums the same entries per
year: by month, by country, by the source's category (the merchant class, as the app spells it)
when any line has one. The Day's `spend` line is the day's totals and merchants (`spend`).

Readers derive and never append (ADR 0013); the same record gives the same ledger."""

from __future__ import annotations

import unicodedata
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from . import countries as country_table
from . import present, stays, trips
from .chain import Line
from .index import Index
from .reading import Reading, window_json
from .resolve import Identity, Ref
from .store import retractions

KIND = "transaction"
SCHEMA = "transaction/v1"
RECEIPTS = "receipts"  # the source of a receipt's own line, `logbook review receipts` (RFC 0043 §12)
NEAR = timedelta(days=2)  # how far apart a receipt and the payment source's line of one payment may be
CENT = 0.005
GENERIC = frozenset(
    {
        "billing", "customer", "do", "donotreply", "no", "no-reply", "noreply", "not", "notifications",
        "order", "orders", "receipt", "receipts", "reply", "sales", "service", "shop", "store", "support",
        "team", "the",
        "asender",  # `a sender`, the merchant of a receipt whose sender has no name and no domain, folded
    }
)  # fmt: skip  # words that name no merchant
BY_INSTANT, BY_DAY = "instant", "day"
MERCHANTS_MAX = 4  # the merchants a Day's spend line names
EN_DASH = "\u2013"
DOT = " · "
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Share:
    """One member's share of a shared expense."""

    person: str | None  # the entity the member's ref resolves to, when it does
    name: str  # the person's label, else the name the app shows; `you` for the owner
    owner: bool
    paid: float
    owed: float

    def to_json(self) -> dict[str, Any]:
        return {
            "person": self.person,
            "name": self.name,
            "owner": self.owner,
            "paid": self.paid,
            "owed": self.owed,
        }


@dataclass(frozen=True)
class Where:
    """The stay a transaction is placed at."""

    stay: str  # the stay's derived id
    label: str  # how it reads: the place's name, `aboard <asset>`, or the coordinates with what is near
    place: str | None  # the named place, when the stay is at one
    aboard: str | None  # the asset id, when the stay is aboard one
    country: str | None  # ISO 3166-1 alpha-2, by the countries rollup's rule; None when unknown
    by: str  # `instant`: the stay held the transaction's instant; `day`: the day's longest stay

    def to_json(self) -> dict[str, Any]:
        return {
            "stay": self.stay,
            "label": self.label,
            "place": self.place,
            "aboard": self.aboard,
            "country": self.country,
            "by": self.by,
        }


@dataclass(frozen=True)
class Entry:
    """One transaction in context."""

    line: str
    at: str
    day: str  # the local day: the source's `date` when it gives one, else the day of `at`
    amount: float
    currency: str
    merchant: str | None
    category: str | None
    provider: str
    source: str
    account: str | None
    status: str | None
    note: str | None
    deleted: bool
    cost: float | None  # a shared expense's total
    shares: tuple[Share, ...]
    where: Where | None
    trip: str | None
    receipt: str | None = None  # the line of the receipt this payment's evidence is (`receipts_held`)

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "at": self.at,
            "amount": self.amount,
            "currency": self.currency,
            "merchant": self.merchant,
            "category": self.category,
            "provider": self.provider,
            "source": self.source,
            "account": self.account,
            "status": self.status,
            "note": self.note,
            "deleted": self.deleted,
            "cost": self.cost,
            "shares": [s.to_json() for s in self.shares],
            "where": None if self.where is None else self.where.to_json(),
            "trip": self.trip,
            "receipt": self.receipt,
            "lines": [self.line],
        }


@dataclass(frozen=True)
class Ledger:
    reading: Reading
    entries: list[Entry]  # in day order, then by `at`, then chain order
    trips: list[trips.Trip]

    def to_json(self) -> dict[str, Any]:
        days: dict[str, list[Entry]] = {}
        for e in self.entries:
            days.setdefault(e.day, []).append(e)
        by_trip: dict[str, list[Entry]] = {}
        for e in self.entries:
            if e.trip is not None:
                by_trip.setdefault(e.trip, []).append(e)
        return {
            "window": window_json(self.reading),
            "tz": str(self.reading.tz),
            "count": sum(1 for e in self.entries if not e.deleted),
            "deleted": sum(1 for e in self.entries if e.deleted),
            "totals": totals(self.entries),
            "days": [
                {
                    "day": day,
                    "weekday": WEEKDAYS[date.fromisoformat(day).weekday()],
                    "count": sum(1 for e in found if not e.deleted),
                    "totals": totals(found),
                    "transactions": [e.to_json() for e in found],
                }
                for day, found in days.items()
            ],
            "trips": [
                {
                    "id": t.id,
                    "start": t.start,
                    "end": t.end,
                    "until": t.until,
                    "route": list(t.route),
                    "count": sum(1 for e in by_trip.get(t.id, []) if not e.deleted),
                    "totals": totals(by_trip.get(t.id, [])),
                    "lines": [e.line for e in by_trip.get(t.id, [])],
                }
                for t in self.trips
            ],
        }


def empty() -> dict[str, Any]:
    """The ledger of a record with no transactions in the window."""
    return {"window": None, "tz": None, "count": 0, "deleted": 0, "totals": {}, "days": [], "trips": []}


# -- the reading --------------------------------------------------------------------------------------------


def ledger(reading: Reading, table: country_table.Countries | None = None) -> Ledger:
    """The ledger of the reading's window: every transaction line standing, placed and in its trip; a
    receipt's line a payment source's line holds is that payment's evidence, never a second one."""
    table = table or country_table.Countries.load()
    found, _warning = trips.trips(reading)
    lines = standing(reading.of_kind(KIND))
    held = held_in(reading, lines)
    by_payment = receipts_of(held)
    lines = [line for line in lines if str(line["id"]) not in held]
    order = {str(line["id"]): i for i, line in enumerate(lines)}
    entries = [
        replace(e, receipt=by_payment[e.line].receipt) if e.line in by_payment else e
        for e in (_entry(line, reading, found, table) for line in lines)
    ]
    entries.sort(key=lambda e: (e.day, e.at, order[e.line]))
    return Ledger(reading, entries, found)


def ordered(lines: Sequence[Line]) -> list[Line]:
    return sorted(lines, key=lambda line: int(line.get("seq", 0)))


def standing(lines: Sequence[Line]) -> list[Line]:
    """The transaction lines standing: a line another line's payload `supersedes` is out, the
    correction in its place (SPEC §3); the latest correction wins. Retracted lines are already out
    of a reading."""
    superseded = {
        str(p["supersedes"])
        for line in lines
        if isinstance(p := line.get("payload"), dict) and isinstance(p.get("supersedes"), str)
    }
    return [line for line in ordered(lines) if str(line.get("id")) not in superseded]


# -- a receipt and its payment -------------------------------------------------------------------------------


@dataclass(frozen=True)
class Held:
    """A receipt's own line (`logbook review receipts`, RFC 0043 §12) and the payment source's line that
    holds the same payment: the source's line is the payment, the receipt's its evidence."""

    receipt: str  # the receipt's line id
    mail: str | None  # the mail it was read from
    payment: str  # the payment source's line id
    tiers: frozenset[int] = frozenset({3})  # the two lines' tiers: a reader shows the pair through both


@dataclass(frozen=True)
class _Paid:
    line: str
    source: str
    tier: int
    at: datetime
    cents: int  # the signed amount in hundredths, as two are compared (`CENT`)
    currency: str
    merchant: str | None
    mail: str | None


def merchant_key(text: str) -> str:
    """A merchant's name as two are compared: letters and digits alone, folded (`FJORDKIOSK AS` →
    `fjordkioskas`)."""
    return "".join(c for c in unicodedata.normalize("NFKC", text).casefold() if c.isalnum())


def same_merchant(keys: Iterable[str], merchant: object) -> bool:
    """Whether one of a receipt's folded names is in the line's merchant, or the line's in it; a name
    shorter than three letters or a generic word (`GENERIC`) matches nothing."""
    if not isinstance(merchant, str):
        return False
    other = merchant_key(merchant)
    if len(other) < 3:
        return False
    return any(len(k) >= 3 and k not in GENERIC and (k in other or other in k) for k in keys)


def receipts_held(lines: Sequence[Line]) -> dict[str, Held]:
    """Among transaction `lines`, each receipt's line (source `RECEIPTS`) that a payment source's line
    holds, by the receipt's line id: the same currency, the same signed amount, within `NEAR`, the same
    merchant (`same_merchant`). One source line holds one receipt, the nearest pairs in time taken
    first (on a tie, the earlier receipt's, then the earlier source line), so two dinners of one price
    are two payments until the source has delivered both. A superseded line, or one the source marks
    deleted, holds nothing and is held by nothing."""
    found = [p for line in standing([x for x in lines if x.get("kind") == KIND]) if (p := _paid(line))]
    paying: dict[tuple[str, int], list[_Paid]] = {}
    for p in found:
        if p.source != RECEIPTS:
            paying.setdefault((p.currency, p.cents), []).append(p)
    order = {p.line: i for i, p in enumerate(found)}  # chain order
    candidates = []
    for r in found:
        if r.source != RECEIPTS:
            continue
        keys = (merchant_key(r.merchant),) if r.merchant else ()
        for p in paying.get((r.currency, r.cents), ()):
            if abs(p.at - r.at) <= NEAR and same_merchant(keys, p.merchant):
                candidates.append((abs(p.at - r.at), order[r.line], order[p.line], r, p))
    taken: set[str] = set()
    held: dict[str, Held] = {}
    for _apart, _r, _p, r, p in sorted(candidates, key=lambda c: c[:3]):
        if r.line not in held and p.line not in taken:
            taken.add(p.line)
            held[r.line] = Held(r.line, r.mail, p.line, frozenset({r.tier, p.tier}))
    return held


_HELD: dict[tuple[str, int, str], dict[str, Held]] = {}  # the record's pairs at a head, a few records


def held_of(idx: Index) -> dict[str, Held]:
    """`receipts_held` over the whole record (`idx`): every standing receipt's line and every standing
    transaction line within `NEAR` of one, so the pairs are the same whichever window a reader cuts
    (a card that posts two days after its receipt is one payment, on the card's day, in a day's window
    and a week's). Receipts' lines are few: they and the days about them are read through the (kind,
    day_local) index, once per head of the record."""
    meta = idx.lb.meta
    key = (str(idx.lb.root), int(meta.get("seq") or 0), str(meta.get("head") or ""))
    if key in _HELD:
        return _HELD[key]
    retracted = retractions(idx.retractions())
    receipts = [x for x in idx.of_kind(KIND, source=RECEIPTS) if str(x.get("id")) not in retracted]
    days = sorted({at.date() for x in receipts if (at := stays.instant(x.get("at")))})
    reach = NEAR + timedelta(days=1)  # a local day is at most a day from the UTC one
    spans: list[list[date]] = []
    for d in days:
        if spans and d - reach <= spans[-1][1]:
            spans[-1][1] = d + reach
        else:
            spans.append([d - reach, d + reach])
    near = {str(x.get("id")): x for x in receipts}
    for first, last in spans:
        for x in idx.by_kind(KIND, first.isoformat(), last.isoformat()):
            if str(x.get("id")) not in retracted:
                near[str(x.get("id"))] = x
    held = receipts_held(list(near.values()))
    if len(_HELD) >= 8:
        _HELD.clear()
    _HELD[key] = held
    return held


def held_through(held: Mapping[str, Held], tiers: Collection[int] | None) -> dict[str, Held]:
    """The pairs a reader of `tiers` (None: every tier) sees: those whose two lines it reads both."""
    if tiers is None:
        return dict(held)
    gate = {int(t) for t in tiers}
    return {k: h for k, h in held.items() if h.tiers <= gate}


def held_in(reading: Reading, lines: Sequence[Line]) -> dict[str, Held]:
    """`held_of` through the reading's gate, for a reader whose window holds the transaction `lines`;
    nothing is read when it holds none."""
    if not any(line.get("kind") == KIND for line in lines):
        return {}
    with reading.lb.index() as idx:
        return held_through(held_of(idx), reading.tiers)


def receipts_of(held: Mapping[str, Held]) -> dict[str, Held]:
    """The same pairs by the payment source's line id."""
    return {h.payment: h for h in held.values()}


def _paid(line: Mapping[str, Any]) -> _Paid | None:
    """A transaction line as `receipts_held` compares it; None for a line with no instant, no amount or
    no currency, or one the source marks deleted."""
    payload = _dict(line.get("payload"))
    at = stays.instant(line.get("at"))
    amount = payload.get("amount")
    currency = str(payload.get("currency") or "").strip().upper()
    if at is None or isinstance(amount, bool) or not isinstance(amount, int | float) or not currency:
        return None
    extra = _dict(payload.get("extra"))
    if extra.get("deleted") is True:
        return None
    merchant, mail = payload.get("merchant"), extra.get("from")
    return _Paid(
        str(line.get("id")),
        str(line.get("source") or ""),
        int(line.get("tier") or 1),
        at,
        round(float(amount) / (2 * CENT)),
        currency,
        merchant if isinstance(merchant, str) else None,
        _text(mail) if line.get("source") == RECEIPTS else None,
    )


def _entry(
    line: Line, reading: Reading, found: Sequence[trips.Trip], table: country_table.Countries
) -> Entry:
    payload = _dict(line.get("payload"))
    extra = _dict(payload.get("extra"))
    at = stays.instant(line.get("at"))
    filed = (
        payload.get("date") if isinstance(payload.get("date"), str) and _is_day(payload.get("date")) else None
    )
    day = filed or (reading.day_start.day(at).isoformat() if at is not None else str(line["at"])[:10])
    where = _where(at, day, filed, reading, table)
    trip = next((t.id for t in found if t.start <= day <= t.until), None)
    cost = extra.get("cost")
    return Entry(
        line=str(line["id"]),
        at=str(line["at"]),
        day=day,
        amount=_number(payload.get("amount")),
        currency=str(payload.get("currency") or "XXX"),
        merchant=_text(payload.get("merchant")),
        category=_text(payload.get("category")),
        provider=str(payload.get("provider") or line.get("source") or ""),
        source=str(line.get("source") or ""),
        account=_text(payload.get("account")),
        status=_text(payload.get("status")),
        note=_text(payload.get("note")),
        deleted=extra.get("deleted") is True,
        cost=float(cost) if isinstance(cost, int | float) and not isinstance(cost, bool) else None,
        shares=tuple(shares(extra, reading.identities, reading.owner)),
        where=where,
        trip=trip,
    )


def _where(
    at: datetime | None, day: str, filed: str | None, reading: Reading, table: country_table.Countries
) -> Where | None:
    """The stay a transaction is at: the owner's stay holding its instant; by the day's longest
    stay when the source keeps the day only (`filed`, and `at` is that day's local midnight)."""
    if at is None:
        return None
    by = BY_INSTANT
    day_start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=reading.tz)
    day_end = day_start + timedelta(days=1)
    if filed is not None and at == day_start:
        by = BY_DAY
        stay = max(
            (s for s in reading.derived.folded if _owner_stay(s) and s.start < day_end and s.end > day_start),
            key=lambda s: (min(s.end, day_end) - max(s.start, day_start), -s.start.timestamp()),
            default=None,
        )
    else:
        stay = next((s for s in reading.derived.folded if _owner_stay(s) and s.start <= at <= s.end), None)
    if stay is None:
        return None
    inner = (
        next((s for s in stay.inside if s.kind == stays.STAY and s.start <= at <= s.end), None)
        if by == BY_INSTANT
        else None
    )
    place = (inner.place if inner is not None else None) or stay.place
    if place is not None:
        label = place
    elif stay.aboard is not None:
        label = f"aboard {trips.asset_name(stay.aboard, reading.assets)}"
    elif stay.lat is not None and stay.lon is not None:
        label = trips.coordinates_label(stay.lat, stay.lon, reading.places, reading.airports)
    else:
        label = "somewhere"
    position = inner if inner is not None and inner.lat is not None else stay
    country = None
    if position.lat is not None and position.lon is not None:
        country = country_table.country_of(
            position.lat, position.lon, reading.places, reading.airports, table
        ).code
    return Where(stay.id, label, place, stay.aboard, country, by)


def _owner_stay(s: stays.Segment) -> bool:
    return s.subject is None and s.kind == stays.STAY


def shares(extra: Mapping[str, Any], identities: Mapping[Ref, Identity], owner: present.Owner) -> list[Share]:
    """The members of a shared expense (`extra.members`, RFC 0021 rule 3), each resolved through the
    record's resolution lines to the person it names, else the name the app shows; the owner's own
    member is `you`. A member that is not an object, or has neither a ref nor a name, is skipped."""
    members = extra.get("members")
    if not isinstance(members, list):
        return []
    found = []
    for member in members:
        if not isinstance(member, dict):
            continue
        ref = _ref(member.get("ref"))
        given = _text(member.get("name"))
        person, label = present.resolve_ref(ref, identities) if ref is not None else (None, None)
        is_owner = (person is not None and person in owner.entities) or (
            ref is not None and (ref[0], _normal(ref[1]) if ref[0] == "email" else ref[1]) in owner.refs
        )
        name = "you" if is_owner else label or given or (f"{ref[0]}:{ref[1]}" if ref is not None else None)
        if name is None:
            continue
        if is_owner and not person:
            person = min((e for e in owner.entities if e), default=None)  # the owner's own entity id
        found.append(
            Share(person or None, name, is_owner, _number(member.get("paid")), _number(member.get("owed")))
        )
    return found


def totals(entries: Sequence[Entry]) -> dict[str, dict[str, float]]:
    """Per currency: what went out (`spent`, negative), what came in (`received`) and the net, over
    the entries that count (a deleted one never does). Nothing is converted."""
    out: dict[str, dict[str, float]] = {}
    for e in entries:
        if e.deleted:
            continue
        bucket = out.setdefault(e.currency, {"spent": 0.0, "received": 0.0, "net": 0.0})
        bucket["spent" if e.amount < 0 else "received"] += e.amount
        bucket["net"] += e.amount
    return {currency: {k: round(v, 2) for k, v in bucket.items()} for currency, bucket in sorted(out.items())}


# -- the Day's spend -----------------------------------------------------------------------------------------


def spend(
    lines: Sequence[Line], tz_day: str, held: Mapping[str, Held] | None = None
) -> dict[str, Any] | None:
    """The Day's spend from the day's transaction lines: how many count, how many are deleted, the
    totals per currency, the merchants in order, the lines; None when the day has none. A receipt's
    line in `held` (`held_in`) is its payment's evidence and not a payment: on the day of the
    payment it holds, `receipts` names it (`line`, `mail`, `of` the payment's line), a key the Day
    has only when a receipt stands behind one of its payments."""
    held = held or {}
    found = [
        line
        for line in standing([line for line in lines if line.get("kind") == KIND])
        if str(line.get("id")) not in held
    ]
    if not found:
        return None
    by_payment = receipts_of(held)
    entries = []
    for line in found:
        payload = _dict(line.get("payload"))
        extra = _dict(payload.get("extra"))
        entries.append(
            Entry(
                line=str(line["id"]),
                at=str(line["at"]),
                day=tz_day,
                amount=_number(payload.get("amount")),
                currency=str(payload.get("currency") or "XXX"),
                merchant=_text(payload.get("merchant")),
                category=None,
                provider="",
                source="",
                account=None,
                status=None,
                note=None,
                deleted=extra.get("deleted") is True,
                cost=None,
                shares=(),
                where=None,
                trip=None,
            )
        )
    row: dict[str, Any] = {
        "count": sum(1 for e in entries if not e.deleted),
        "deleted": sum(1 for e in entries if e.deleted),
        "totals": totals(entries),
        "merchants": list(dict.fromkeys(e.merchant for e in entries if e.merchant and not e.deleted)),
        "lines": [e.line for e in entries],
    }
    evidence = [by_payment[e.line] for e in entries if e.line in by_payment]
    if evidence:  # only on a day a receipt stands behind a payment: the Day's object is otherwise unchanged
        row["receipts"] = [{"line": h.receipt, "mail": h.mail, "of": h.payment} for h in evidence]
    return row


def spend_text(row: Mapping[str, Any]) -> str:
    """`EUR -307.50 · 2 transactions · Hotel Musterhof, Zunfthaus Beispiel`; `1 deleted` alone when
    nothing counts."""
    parts = [f"{c} {money(t['net'])}" for c, t in row["totals"].items()]
    if row["count"]:
        parts.append(_plural(row["count"], "transaction"))
    if row["deleted"]:
        parts.append(f"{row['deleted']} deleted")
    receipts = len(row.get("receipts") or ())
    if receipts:
        parts.append("1 with its receipt" if receipts == 1 else f"{receipts} with their receipts")
    merchants = row["merchants"]
    if merchants:
        names = ", ".join(merchants[:MERCHANTS_MAX])
        if len(merchants) > MERCHANTS_MAX:
            names += f" +{len(merchants) - MERCHANTS_MAX}"
        parts.append(names)
    return DOT.join(parts)


# -- rollup money -------------------------------------------------------------------------------------------


def money(amount: float) -> str:
    return f"{amount:,.2f}"


def rollup(reading: Reading, table: country_table.Countries | None = None) -> dict[str, Any]:
    """`rollup money`: per year, the transactions that count and the deleted ones, the totals per
    currency, then the same by month, by country (the country of the stay each is placed at; the
    unplaced under `null`) and by the source's category when any line has one. Every bucket
    carries its line ids."""
    book = ledger(reading, table)
    years: dict[str, dict[str, Any]] = {}
    for e in book.entries:
        year = years.setdefault(
            e.day[:4],
            {"year": e.day[:4], "entries": [], "months": {}, "countries": {}, "categories": {}},
        )
        year["entries"].append(e)
        year["months"].setdefault(e.day[:7], []).append(e)
        if e.deleted:
            continue
        year["countries"].setdefault(e.where.country if e.where else None, []).append(e)
        if e.category is not None:
            year["categories"].setdefault(e.category, []).append(e)
    out: dict[str, Any] = {"kind": "money", "window": window_json(reading), "years": []}
    for key in sorted(years):
        year = years[key]
        entries: list[Entry] = year["entries"]
        out["years"].append(
            {
                "year": key,
                "count": sum(1 for e in entries if not e.deleted),
                "deleted": sum(1 for e in entries if e.deleted),
                "totals": totals(entries),
                "by_month": [_bucket("month", m, found) for m, found in sorted(year["months"].items())],
                "by_country": [
                    _bucket("country", c, found)
                    for c, found in sorted(
                        year["countries"].items(), key=lambda kv: (-len(kv[1]), kv[0] or "~")
                    )
                ],
                "by_category": [
                    _bucket("category", c, found)
                    for c, found in sorted(
                        year["categories"].items(), key=lambda kv: (-len(kv[1]), kv[0].casefold())
                    )
                ],
                "lines": [e.line for e in entries],
            }
        )
    return out


def _bucket(key: str, name: str | None, found: Sequence[Entry]) -> dict[str, Any]:
    return {
        key: name,
        "count": sum(1 for e in found if not e.deleted),
        "deleted": sum(1 for e in found if e.deleted),
        "totals": totals(found),
        "lines": [e.line for e in found],
    }


def rollup_rows(year: dict[str, Any]) -> Iterator[str]:
    """One year of `rollup money` as text: the year's line, then a line per month, per country
    and, when any line has one, per category."""
    yield f"  {year['year']}  {_counts_text(year)}"
    if year["by_month"]:
        yield "        by month:"
    for m in year["by_month"]:
        yield f"        {m['month']:<14} {_counts_text(m)}"
    if year["by_country"]:
        yield "        by country (of the stay each transaction is placed at):"
    for c in year["by_country"]:
        yield f"        {c['country'] or 'unplaced':<14} {_counts_text(c)}"
    if year["by_category"]:
        yield "        by category (the source's own):"
    for c in year["by_category"]:
        yield f"        {c['category']:<14} {_counts_text(c)}"


def _counts_text(bucket: Mapping[str, Any]) -> str:
    parts = [_plural(bucket["count"], "transaction")]
    if bucket.get("deleted"):
        parts.append(f"{bucket['deleted']} deleted")
    parts += [_totals_text(c, t) for c, t in bucket["totals"].items()]
    return DOT.join(parts)


def _totals_text(currency: str, t: Mapping[str, float]) -> str:
    """`NOK 44,785.00 (in 45,000.00, out -215.00)`; the net alone when money went one way."""
    text = f"{currency} {money(t['net'])}"
    if t["received"] and t["spent"]:
        text += f" (in {money(t['received'])}, out {money(t['spent'])})"
    return text


# -- text ----------------------------------------------------------------------------------------------------


def rows(data: dict[str, Any]) -> Iterator[str]:
    """The ledger as text: the window's head, each day with its transactions, then the trips."""
    window = data["window"]
    if window is None or not data["days"]:
        yield "ledger: no transactions" + (
            "" if window is None else f" {window['since']} {EN_DASH} {window['until']}"
        )
        return
    yield f"ledger {window['since']} {EN_DASH} {window['until']}: {_counts_text(data)}"
    for day in data["days"]:
        head = f"  {day['day']}  {day['weekday']}"
        if day["totals"]:
            head += DOT + DOT.join(f"{c} {money(t['net'])}" for c, t in day["totals"].items())
        yield head
        for t in day["transactions"]:
            yield _entry_row(t, str(data.get("tz") or ""))
    if data["trips"]:
        yield "  trips"
    for t in data["trips"]:
        parts = [
            _plural(t["count"], "transaction"),
            *(f"{c} {money(x['net'])}" for c, x in t["totals"].items()),
        ]
        route = f" {trips.ARROW} ".join(t["route"]) if t["route"] else "route unknown"
        yield f"    {t['start']} {EN_DASH} {t['end']}  {route}{DOT}{DOT.join(parts)}"


def _entry_row(t: dict[str, Any], tz: str) -> str:
    clock = _clock(t["at"], tz)
    parts = [t["merchant"] or "(no merchant)"]
    where = t["where"]
    if where is None:
        parts.append("nowhere")
    else:
        parts.append(f"at {where['label']}" if not where["label"].startswith("aboard ") else where["label"])
        if where["by"] == BY_DAY:
            parts[-1] += " (by day)"
    if t["category"]:
        parts.append(t["category"])
    parts.append(t["provider"] or t["source"])
    if t["trip"]:
        _prefix, start, end = t["trip"].split(":")
        parts.append(f"trip {start} {EN_DASH} {end}")
    if t["shares"]:
        parts.append(
            (f"split {len(t['shares'])} ways: " if len(t["shares"]) > 1 else "shares: ")
            + ", ".join(
                f"{s['name']} {money(s['owed'])}" + (f" (paid {money(s['paid'])})" if s["paid"] else "")
                for s in t["shares"]
            )
        )
    if t["deleted"]:
        parts.append("deleted")
    if t.get("receipt"):
        parts.append("with its receipt")
    amount = f"{t['currency']} {money(t['amount'])}"
    return f"    {clock}  {amount}  {DOT.join(parts)}"


def _clock(stamp: str, tz: str) -> str:
    at = stays.instant(stamp)
    if at is None or not tz:
        return "     "
    return at.astimezone(ZoneInfo(tz)).strftime("%H:%M")


# -- helpers ------------------------------------------------------------------------------------------------


def _is_day(text: object) -> bool:
    try:
        date.fromisoformat(str(text))
    except ValueError:
        return False
    return len(str(text)) == 10


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else 0.0


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    if not isinstance(kind, str) or not isinstance(ref_value, str) or not ref_value:
        return None
    return kind, ref_value


def _normal(text: str) -> str:
    return " ".join(text.split()).casefold()


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
