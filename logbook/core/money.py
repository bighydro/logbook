"""The money slot (RFC 0043 §11, §12): what a day, or a window of days, paid and was paid — the
`transaction/v1` lines (RFC 0021) of the local days [start, end], each with its merchant and amount,
and the totals per currency, read as the ledger reads them (`ledger.standing`: a correction in the
place of the line it supersedes; a retracted line out; a line the source marks deleted listed, marked
and never summed; a receipt's own line that a payment source's line holds out, named as that
payment's `receipt`, `ledger.held_of`). It writes nothing (ADR 0013), and receipt mails are not read
here.

**When no payment source covers the window**, it says so from the record's own lines and sums
nothing: a payment source covers the days from its first transaction line to its last (a retracted
line covers nothing), so a day after
the last says `No payment source covers this day — the last ends <date>`, a day before the first
`… — the first begins <date>`, and a record with none `… — the record holds no payment lines`. A day
inside the sources' span with no transaction says `No card lines for this day`, never a zero. A window
that runs past either end lists what it holds and names the days past it. Each line is on the local day
of its instant, the day the window is cut by.

**Tier 3**: every transaction line is (RFC 0021, ADR 0016), and so is where the lines end, since it
is read from them: through a gate (`tiers`) without 3 nothing of it is shown, not a line, a total or
a date, and the reading says why (`HIDDEN`).

**Cost**: the window's transaction lines through the (kind, day_local) index, the span of the kind as
one aggregate on it, and at each end of the span one day's lines (more only when the lines there are
retracted, doubling the days read until one stands)."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from . import day_start, ledger
from .chain import Line
from .export import parse_day
from .index import Index
from .store import Logbook, retractions

KIND = ledger.KIND
TIER = 3  # a transaction/v1 line's tier (RFC 0021)
HIDDEN = "money is tier 3, and this reads no tier 3"
NONE_PAID = "No card lines for this day"
NO_SOURCE = "No payment source covers {days} — {where}"


@dataclass(frozen=True)
class Payment:
    """One transaction: its day, merchant, amount (signed from the owner's side) and currency."""

    day: str
    at: str
    merchant: str | None
    amount: float
    currency: str
    deleted: bool
    source: str
    line: str
    receipt: str | None = None  # the receipt's line this payment's evidence is (`ledger.held_of`)

    def to_json(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "at": self.at,
            "merchant": self.merchant,
            "amount": self.amount,
            "currency": self.currency,
            "deleted": self.deleted,
            "source": self.source,
            "line": self.line,
            "receipt": self.receipt,
        }


@dataclass(frozen=True)
class Money:
    """The window's payments, their totals per currency (deleted ones aside), whether a payment
    source covers the whole window, and the sentence to say instead of a sum (None: nothing to say)."""

    start: str
    end: str
    payments: list[Payment] = field(default_factory=list)
    totals: dict[str, dict[str, float]] = field(default_factory=dict)
    covered: bool = False
    said: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "tier": TIER,
            "payments": [p.to_json() for p in self.payments],
            "totals": self.totals or None,  # never an empty sum
            "covered": self.covered,
            "said": self.said,
        }


def money_in(lb: Logbook, start: str, end: str, tiers: Sequence[int] | None = None) -> Money:
    """The `transaction/v1` lines of the local days [start, end], through the gate of `tiers` (None:
    every tier). `ValueError` for a day that is not one or a window that runs backwards."""
    first, last = parse_day(start), parse_day(end)
    if last < first:
        raise ValueError(f"the window {start} to {end} runs backwards")
    start, end = first.isoformat(), last.isoformat()
    if tiers is not None and TIER not in tiers:
        return Money(start, end, said=HIDDEN)
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        lines = [x for x in idx.by_kind(KIND, start, end) if str(x.get("id")) not in retracted]
        held = ledger.held_through(ledger.held_of(idx), tiers)
        span = idx.span(KIND)
        if span is not None:
            span = _standing_span(idx, retracted, days, *span)
    by_payment = ledger.receipts_of(held)
    payments = [
        _payment(line, days, by_payment.get(str(line.get("id"))))
        for line in ledger.standing(lines)
        if str(line.get("id")) not in held
    ]
    payments.sort(key=lambda p: (p.day, p.at, p.line))
    totals = _totals(payments)
    one = start == end
    if span is None:
        return Money(start, end, payments, totals, said=_no_source(one, "the record holds no payment lines"))
    since, until = span
    if end < since or start > until:
        where = f"the last ends {until}" if start > until else f"the first begins {since}"
        return Money(start, end, payments, totals, said=_no_source(one, where))
    gaps: list[str] = []
    if start < since:
        before = (parse_day(since) - timedelta(days=1)).isoformat()
        gaps.append(f"{_days(start, before)} — the first begins {since}")
    if end > until:
        after = (parse_day(until) + timedelta(days=1)).isoformat()
        gaps.append(f"{_days(after, end)} — the last ends {until}")
    if gaps:
        return Money(start, end, payments, totals, said=f"No payment source covers {'; nor '.join(gaps)}")
    said = None if payments else NONE_PAID if one else "No card lines for these days"
    return Money(start, end, payments, totals, True, said)


def _days(first: str, last: str) -> str:
    return first if first == last else f"{first} to {last}"


def _standing_span(
    idx: Index, retracted: Collection[str], days: day_start.DayStart, since: str, until: str
) -> tuple[str, str] | None:
    """The first and last local day with a transaction line that is not retracted, inside the span
    the index gives for every one of them (`since`, `until`): a retracted line at either end (a
    mis-dated import taken back) covers nothing. Each end is found from the index's own outward,
    reading one day's lines, then two days', four, …, until a window holds a standing line; None when
    no line stands."""
    last = _edge(idx, retracted, days, since, until, latest=True)
    if last is None:
        return None
    first = _edge(idx, retracted, days, since, last, latest=False)
    return (first or last), last


def _edge(
    idx: Index, retracted: Collection[str], days: day_start.DayStart, since: str, until: str, latest: bool
) -> str | None:
    low, high = parse_day(since), parse_day(until)
    width = 1
    while True:
        if latest:
            a, b = max(low, high - timedelta(days=width - 1)), high
        else:
            a, b = low, min(high, low + timedelta(days=width - 1))
        found = [
            days.day_of(str(x["at"]))
            for x in idx.by_kind(KIND, a.isoformat(), b.isoformat())
            if str(x.get("id")) not in retracted
        ]
        if found:
            return max(found) if latest else min(found)
        if (latest and a == low) or (not latest and b == high):
            return None
        width *= 2


def _no_source(one: bool, where: str) -> str:
    return NO_SOURCE.format(days="this day" if one else "these days", where=where)


def _payment(line: Line, days: day_start.DayStart, held: ledger.Held | None = None) -> Payment:
    """One transaction line read, on the local day of its instant: the day the window is cut by (a
    source that files by the day puts `at` at that day's local midnight, RFC 0021 rule 5)."""
    payload = line.get("payload") or {}
    day = days.day_of(str(line["at"]))
    found = payload.get("extra")
    extra: dict[str, Any] = found if isinstance(found, dict) else {}
    amount = payload.get("amount")
    merchant = payload.get("merchant")
    return Payment(
        day=day,
        at=str(line.get("at") or ""),
        merchant=" ".join(merchant.split()) if isinstance(merchant, str) and merchant.strip() else None,
        amount=float(amount) if isinstance(amount, int | float) and not isinstance(amount, bool) else 0.0,
        currency=str(payload.get("currency") or "XXX"),
        deleted=extra.get("deleted") is True,
        source=str(line.get("source") or ""),
        line=str(line.get("id")),
        receipt=None if held is None else held.receipt,
    )


def _totals(payments: Sequence[Payment]) -> dict[str, dict[str, float]]:
    """Per currency, the spent, the received and the net, deleted payments aside; nothing when none."""
    out: dict[str, dict[str, float]] = {}
    for p in payments:
        if p.deleted:
            continue
        bucket = out.setdefault(p.currency, {"spent": 0.0, "received": 0.0, "net": 0.0})
        bucket["spent" if p.amount < 0 else "received"] += p.amount
        bucket["net"] += p.amount
    return {c: {k: round(v, 2) for k, v in b.items()} for c, b in sorted(out.items())}
