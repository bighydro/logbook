"""Receipts proposed as payments (RFC 0043 §12, the money bridge): until a payment source covers a day,
the receipt mails the record already holds are proposed as payments, and the owner confirms each in
review (`logbook review receipts`). The ledger stays the truth (`docs/ledger.md`); this is the bridge.

**What is read.** The record's `mail/v1` lines (RFC 0015), read only, through the index (`of_kind`,
the window's days alone; `since` defaults to `SINCE_DAYS` before today). A mail line keeps `from`
(`{email, name?}`), `subject` when the message has one, and `body` when the road kept one (the
`text/plain` part, else the HTML stripped, at most 64 KB): the subject is read always, the body only
when the line keeps one, and nothing else of the message is asked for. Nothing is looked up.

**A receipt candidate** is a received mail whose sender is a merchant and whose text carries an
amount with a currency and an order or receipt marker (`MARKERS`, `REFUNDS`). A merchant is a sender
the record does not name as a person (RFC 0006: an address a `resolution/v1` line resolves to a
person, or the owner's own, is never one), at an order or no-reply address (`ROLES`) or on a domain
an org of the Manifest binds (`entities.bindings`); an org there is a plus to the confidence, and its
name the merchant's. Else the merchant is the display name, the generic words out, else the first
label of the sender's registered domain, else `a sender` (a host with no registered domain, an
address with no domain). The queue names a merchant by its domain (the sender's registered domain)
and never shows a sender's address: not in its rows, not in its JSON, not as a merchant.

**The amount** is read by rules, never by a model (`amounts`): a currency code or symbol (`CODES`,
`SYMBOLS`) before or after a number in the common forms (`CHF 1'234.50`, `€ 12,90`, `$12.90`, `NOK
1 840`, `1.234,50 EUR`, `99.- CHF`); `kr` alone names three currencies and is no currency, as the
Google Wallet reader rules; a number glued to a word, after a number and a space, or that a code
and a number follow is none. A total is preferred over the line items (`choose`): the largest amount
the words before it (on its line, else the line above) call the total and not a subtotal, tax or
shipping; else the subject's; else the one amount the text names; else the largest, with less
confidence. A refund (the subject's word, the chosen amount's own words, or a minus on it; never a
footer's `non-refundable`) is money in: amounts are signed from the owner's side as RFC 0021 rule 2
signs them, a purchase negative and a refund positive. Every rule is linear in the text.

**Already in the record.** A candidate whose currency and signed amount match a standing
`transaction/v1` line within `NEAR` (two days) of the mail, its merchant naming the line's or the
line's naming its, is shown as already in the record with the line that holds it, never numbered and
never written. A receipt's own accepted line is matched the same way against the other sources: when
a payment source later delivers the same payment, the queue lists the pair as covered (one source
line covers one receipt, paired as `ledger.receipts_held` pairs them for every reader that sums the
ledger, which counts the pair once already); the source's line wins, and the receipt's line is the
one to take back, `logbook repair retract SEQ`, which the
row prints (a superseding line would be a second payment; docs/receipts.md says what an amendment of
RFC 0021 would do instead).

**What is written**, and only when the owner says (`accept`, `reject`): an accepted candidate is one
`transaction/v1` line through `Logbook.append`, tier 3 (money, always), source and `provider`
`receipts`, `at` the mail's, `raw_id` the mail line's id, `extra.from` the mail line's id. Within one
batch, a second candidate of the same merchant, day, currency and amount is the same payment: it is
refused, counted (`duplicate`) and never written. A rejected candidate is one `receipt-review/v1` line
labelled `not-a-payment`, tier 3 like the payments (the owner's answer; a `note/v1` is tier 2 by RFC
0010, so the no is a profile of its own, as a scene's is in RFC 0040 §5), its text `not a payment`,
naming no amount, no currency and no merchant, and `extra.from` the mail line's id. A mail with an
accepted line or a standing no is never proposed again; a retracted no proposes it again. The
queue's output is a tier-3 reader's: a reader whose tiers leave out 3 gets nothing
(`Report.withheld`)."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from ..core import day_start, ledger, policy, present, resolve, sealing, stays
from ..core.chain import Line, is_sealed
from ..core.index import Index
from ..core.store import Logbook, now_utc, retractions
from . import entities

KIND = "receipts"  # the review's kind
SOURCE = "receipts"  # the source of every line this writes
PROVIDER = "receipts"
TRANSACTION, TRANSACTION_SCHEMA = "transaction", "transaction/v1"
MAIL = "mail"
REVIEW, REVIEW_SCHEMA = "receipt-review", "receipt-review/v1"  # the owner's no, tier 3
NOT_A_PAYMENT = "not-a-payment"  # the no's label
NO_TEXT = "not a payment"  # the no's words: no amount, no currency, no merchant
TIER = 3  # RFC 0021: money, always
SINCE_DAYS = 90
NEAR = ledger.NEAR  # the rule a reader that sums the ledger holds a receipt to (`ledger.same_payment`)
CENT = ledger.CENT

CODES = ("CHF", "EUR", "NOK", "USD", "GBP", "SEK", "DKK", "ISK", "PLN", "CAD", "AUD", "NZD", "JPY")
SYMBOLS = {"€": "EUR", "$": "USD", "US$": "USD", "£": "GBP"}
ROLES = frozenset(
    {
        "billing", "bestilling", "confirm", "confirmation", "donotreply", "faktura", "invoice", "invoices",
        "kvittering", "noreply", "order", "orders", "ordre", "payment", "payments", "purchase", "purchases",
        "receipt", "receipts", "sales", "shop", "store",
    }
)  # fmt: skip
GENERIC = ledger.GENERIC
NO_SENDER = "a sender"  # the merchant of a sender whose name and domain give none
MARKERS = (  # each from a word's start; `reçu` to its end too, so `recurring` is none
    r"receipt", r"your order", r"order (?:#|no\.?|number|confirmation|confirmed)", r"thank(?:s| you) for your"
    r" (?:order|purchase)", r"invoice", r"payment (?:received|confirmation|confirmed)", r"kvittering",
    r"ordrebekreftelse", r"ordrenummer", r"din bestilling", r"bestillingsnummer", r"quittung",
    r"bestellbest[aä]tigung", r"bestellnummer", r"ihre bestellung", r"rechnung", r"re[cç]us?\b",
    r"votre commande", r"confirmation de commande", r"facture",
)  # fmt: skip
REFUNDS = (
    r"refund", r"refusjon", r"tilbakebetal", r"r[uü]ckerstattung", r"gutschrift", r"rembours", r"credit note",
)  # fmt: skip
NOT_REFUNDS = (  # what a receipt says of refunds without being one
    r"non-?refundable", r"\brefundable", r"refund policy", r"refunds? (?:are|is) not", r"no refunds?",
    r"refunds? within",
)  # fmt: skip
TOTALS = (
    r"total", r"sum\b", r"summe", r"å betale", r"betalt", r"amount (?:paid|charged|due)", r"charged",
    r"you paid", r"du betalte", r"gesamt", r"endbetrag", r"montant",
)  # fmt: skip
NOT_TOTALS = (
    r"sub-?total", r"delsum", r"zwischensumme", r"sous-total", r"\bmva\b", r"\bvat\b", r"mwst", r"\btva\b",
    r"\btax\b", r"shipping", r"frakt", r"versand", r"discount", r"rabatt", r"savings?",
)  # fmt: skip

_MARKER = re.compile(rf"\b(?:{'|'.join(MARKERS)})", re.IGNORECASE)
_REFUND = re.compile(rf"\b(?:{'|'.join(REFUNDS)})", re.IGNORECASE)
_NOT_REFUND = re.compile("|".join(NOT_REFUNDS), re.IGNORECASE)
_TOTAL = re.compile("|".join(TOTALS), re.IGNORECASE)
_NOT_TOTAL = re.compile("|".join(NOT_TOTALS), re.IGNORECASE)
_INCLUDED = re.compile(  # `Total incl. VAT`, `Sum inkl. mva`: a total that names its tax
    r"\b(?:incl|inkl|excl|exkl|including|excluding|inc|zzgl)\.?\s+(?:vat|mva|mwst|tva|tax|moms)\b",
    re.IGNORECASE,
)
_SEP = "[ '\u2019\u00a0\u202f.,]"  # what groups thousands: a space, an apostrophe, a point, a comma
_NUMBER = rf"\d{{1,3}}(?:{_SEP}\d{{3}}){{1,4}}(?:[.,]\d{{1,2}})?|\d{{1,12}}(?:[.,]\d{{1,2}})?"  # bounded
_TAIL = r"(?:[.,][-\u2013])?"  # `99.-`, `12,-`: whole francs, whole crowns
_CURRENCY = "|".join([*CODES, r"US\$", "€", r"\$", "£"])
_GAP = "[ \u00a0\u202f]?"
# a code first (`CHF 12.90`), or a number first (`12,90 €`): never a number after a digit and a space
# (`07700 900123`) or inside a word (`XY1234`), nor one a code then a number follows (`5531 NOK 1 840`)
_AMOUNT = re.compile(
    rf"(?:(?<!\w)(?P<minus1>[-\u2212]))?(?<![A-Za-z])(?P<cur1>{_CURRENCY})(?![A-Za-z]){_GAP}"
    rf"(?P<minus2>[-\u2212])?(?P<num1>{_NUMBER}){_TAIL}"
    rf"|(?:(?<!\w)(?P<minus3>[-\u2212]))?(?<![\w.,'])(?<!\d[ \u00a0\u202f'])(?P<num2>{_NUMBER}){_TAIL}"
    rf"{_GAP}(?P<cur2>{_CURRENCY})(?![A-Za-z])(?!{_GAP}[-\u2212]?\d)"
)


class ReviewError(ValueError):
    """What the receipts queue cannot act on; the message says why and nothing is written."""


@dataclass(frozen=True)
class Amount:
    """One amount with its currency as a text names it: `value` unsigned, `minus` when the text signs it."""

    value: float
    currency: str
    minus: bool
    text: str


@dataclass(frozen=True)
class Chosen:
    """The amount a receipt's text says was paid, and how it was chosen."""

    amount: Amount
    refund: bool
    total: bool  # on a total line
    in_subject: bool  # no total line: the subject's amount
    only: bool  # the one amount the text names
    subject: bool  # the marker is in the subject

    @property
    def signed(self) -> float:
        """From the owner's side (RFC 0021 rule 2): a purchase negative, a refund positive."""
        return self.amount.value if self.refund else -self.amount.value


@dataclass(frozen=True)
class Held:
    """The standing transaction line that already holds a payment."""

    line: str
    seq: int
    source: str
    merchant: str | None

    def to_json(self) -> dict[str, Any]:
        return {"line": self.line, "seq": self.seq, "source": self.source, "merchant": self.merchant}


@dataclass(frozen=True)
class Candidate:
    """One receipt mail proposed as a payment; `number` None when the record already holds it."""

    number: int | None
    mail: str  # the mail line's id
    at: str  # the mail's time
    day: str
    domain: str  # the sender's registered domain: the merchant's, never the address
    merchant: str
    amount: float  # signed from the owner's side
    currency: str
    refund: bool
    confidence: float
    why: tuple[str, ...]
    keys: tuple[str, ...]  # the merchant's names, folded, as the dedupe compares them
    held_by: Held | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "mail": self.mail,
            "at": self.at,
            "day": self.day,
            "domain": self.domain,
            "merchant": self.merchant,
            "amount": self.amount,
            "currency": self.currency,
            "refund": self.refund,
            "confidence": self.confidence,
            "why": list(self.why),
            "held_by": None if self.held_by is None else self.held_by.to_json(),
        }


@dataclass(frozen=True)
class Covered:
    """A receipt's accepted line whose payment a payment source now holds: the source's line wins."""

    line: str
    seq: int
    mail: str | None
    day: str
    merchant: str | None
    amount: float
    currency: str
    held_by: Held

    def to_json(self) -> dict[str, Any]:
        return {
            "line": self.line,
            "seq": self.seq,
            "mail": self.mail,
            "day": self.day,
            "merchant": self.merchant,
            "amount": self.amount,
            "currency": self.currency,
            "held_by": self.held_by.to_json(),
        }


@dataclass
class Report:
    since: str
    proposals: list[Candidate] = field(default_factory=list)
    already: list[Candidate] = field(default_factory=list)
    covered: list[Covered] = field(default_factory=list)
    accepted: int = 0
    rejected: int = 0
    read: int = 0  # the mail lines read
    withheld: bool = False  # the reader's tiers leave out 3: nothing of the queue is shown

    @property
    def tier(self) -> int | None:
        return None if self.withheld else TIER

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": KIND,
            "tier": self.tier,
            "since": self.since,
            "withheld": self.withheld,
            "read": self.read,
            "accepted": self.accepted,
            "rejected": self.rejected,
            "proposals": [p.to_json() for p in self.proposals],
            "already": [p.to_json() for p in self.already],
            "covered": [c.to_json() for c in self.covered],
        }


@dataclass(frozen=True)
class Written:
    verdict: str  # accepted, rejected, or duplicate: refused in its batch, no line
    candidate: Candidate
    line: Line | None
    same_as: int | None = None  # a duplicate's: the number of the proposal written in its place

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.candidate.number,
            "verdict": self.verdict,
            "mail": self.candidate.mail,
            "line": None if self.line is None else str(self.line["id"]),
            "seq": None if self.line is None else int(self.line["seq"]),
            "tier": None if self.line is None else int(self.line["tier"]),
            "same_as": self.same_as,
        }


# -- the rules ---------------------------------------------------------------------------------------------


def amounts(text: str) -> list[Amount]:
    """Every amount with a currency `text` names, in the order it names them."""
    return [a for a, _start, _end in _spans(text)]


def _spans(text: str) -> Iterable[tuple[Amount, int, int]]:
    for m in _AMOUNT.finditer(text):
        code = m.group("cur1") or m.group("cur2")
        number = m.group("num1") or m.group("num2")
        minus = bool(m.group("minus1") or m.group("minus2") or m.group("minus3"))
        found = Amount(_value(number), SYMBOLS.get(code, code), minus, m.group(0).strip())
        if found.value > 0:
            yield found, m.start(), m.end()


def _value(number: str) -> float:
    """`1'234.50`, `1 840`, `1.234,50`, `12,90`: the last point or comma before one or two digits at
    the end is the decimal mark, every other mark groups thousands."""
    digits = re.sub(_SEP.replace(".,", ""), "", number)
    m = re.fullmatch(r"(.*?)[.,](\d{1,2})", digits)
    whole, cents = (m.group(1), m.group(2)) if m else (digits, "")
    whole = re.sub("[.,]", "", whole)
    return round(float(f"{whole or 0}.{cents or 0}"), 2)


def is_total(label: str) -> bool:
    """Whether the words before an amount call it the total: `Total`, `Sum inkl. mva`, `Totalt å
    betale`; never `Subtotal`, `VAT`, `Shipping`, `Total savings`."""
    if _TOTAL.search(label) is None:
        return False
    return _NOT_TOTAL.search(_INCLUDED.sub(" ", label)) is None


def refunded(text: str) -> bool:
    """Whether `text` says money came back: a refund word, not `non-refundable` or `refund policy`."""
    return _REFUND.search(_NOT_REFUND.sub(" ", text)) is not None


def choose(subject: str | None, body: str | None) -> Chosen | None:
    """The amount a receipt's subject and body say was paid, or None when they are no receipt: no
    order or receipt marker, or no amount with a currency. A total over the line items: an amount is
    one when the words before it on its line (the line above, when none) say so. A refund when the
    subject says so, or the chosen amount's own words do, or a minus is on it."""
    head, text = subject or "", body or ""
    whole = f"{head}\n{text}"
    if _MARKER.search(whole) is None and not refunded(whole):
        return None
    lines = [head, *text.splitlines()]
    found: list[tuple[int, Amount, str]] = []  # the line, the amount, the words before it
    above = ""
    for i, line in enumerate(lines):
        start = 0
        for amount, at, end in _spans(line):
            label = line[start:at]
            if start == 0 and not label.strip() and i > 0:
                label = above
            found.append((i, amount, label))
            start = end
        if line.strip():
            above = line
    if not found:
        return None
    totals = [(a, label) for i, a, label in found if i > 0 and is_total(label)]
    named = {(a.value, a.currency) for _, a, _ in found}
    in_subject = False
    if totals:
        chosen, label = max(totals, key=lambda t: t[0].value)
    elif any(i == 0 for i, _, _ in found):
        chosen, label = next((a, label) for i, a, label in found if i == 0)
        in_subject = True
    else:
        chosen, label = max(((a, label) for _, a, label in found), key=lambda t: t[0].value)
    refund = refunded(head) or refunded(label) or chosen.minus
    marked = _MARKER.search(head) is not None or refunded(head)
    return Chosen(chosen, refund, bool(totals), in_subject, len(named) == 1, marked)


def local_part(email: str) -> str:
    return email.rsplit("@", 1)[0].split("+", 1)[0].casefold()


def domain_of(email: str) -> str:
    return email.rsplit("@", 1)[1].casefold() if "@" in email else ""


def role(email: str) -> bool:
    """An order or no-reply address: `orders@`, `no-reply@`, `kvittering@`, `receipts@` …"""
    local = local_part(email).replace("_", "-")
    if any(local.startswith(word) for word in ("noreply", "no-reply", "donotreply", "do-not-reply")):
        return True
    return any(word in ROLES for word in re.split(r"[-.]", local))


def merchant_of(sender: Mapping[str, Any], org: str | None = None, suffixes: Iterable[str] = ()) -> str:
    """The merchant's name: the Manifest's org on the domain, else the display name with the generic
    words out, else the first label of the sender's registered domain, else `a sender` (`x@localhost`,
    an address with no domain): a label shown to a reader, never the address."""
    if org:
        return org
    name = sender.get("name")
    if isinstance(name, str):
        kept = [w for w in name.split() if entities.fold(w).strip(".,:;") not in GENERIC and "@" not in w]
        if kept:
            return " ".join(kept)
    registered = entities.registered_domain(domain_of(str(sender.get("email") or "")), suffixes)
    label = registered.split(".", 1)[0] if registered else ""
    return label[:1].upper() + label[1:] if label else NO_SENDER


fold = ledger.merchant_key  # letters and digits alone, folded: `FJORDKIOSK AS` → `fjordkioskas`
same_merchant = ledger.same_merchant  # a candidate's folded name in the line's merchant, or the line's in it


# -- the reading -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Money:
    line: str
    seq: int
    source: str
    at: datetime
    amount: float
    currency: str
    merchant: str | None
    mail: str | None  # a receipt's own: the mail it was read from


def read(
    lb: Logbook,
    since: str | None = None,
    today: date | None = None,
    tiers: Collection[int] | None = None,
) -> Report:
    """The queue at the record's head: every receipt candidate among the mails of `since` (a day,
    `YYYY-MM-DD`; `SINCE_DAYS` before today when None) to today, numbered from 1 in time order, those
    the record already holds apart, and the receipts' lines a payment source now covers. Writes
    nothing. A reader whose `tiers` leave out 3 gets an empty report, `withheld`."""
    days = day_start.of(lb.meta)
    today = today or days.today(datetime.now(UTC))
    first = _since(since, today)
    if tiers is not None and TIER not in {int(t) for t in tiers}:
        return Report(first, withheld=True)
    report = Report(first)
    with lb.index() as idx:
        marks = idx.retractions()
        retracted = frozenset(retractions(marks))
        identities = resolve.identities_from([*marks, *idx.resolutions()])
        owner = present.owner_of(
            str(lb.meta.get("owner_id") or ""),
            [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
            policy.owner_aliases(lb.root),
            identities,
        )
        settings = entities.read_settings(lb.root)
        orgs = _orgs(idx, marks)
        money = _money(lb, idx, retracted, _day_before(first, NEAR.days))
        noes = _noes(lb, idx, retracted)
        mails = list(_opened(lb, _standing(idx, MAIL, retracted, first, source=None)))
        pairs = ledger.held_through(ledger.held_of(idx), tiers)  # as every reader that sums the ledger
        payers = idx.by_ids({h.payment for h in pairs.values()})
    own = {m.mail for m in money if m.source == SOURCE and m.mail}
    report.accepted = len({m for m in own if m in {str(line["id"]) for line in mails}})
    report.rejected = len({m for m in noes if m in {str(line["id"]) for line in mails}})
    report.read = len(mails)
    found: list[Candidate] = []
    for line in sorted(mails, key=lambda line: (str(line["at"]), int(line["seq"]))):
        mail_id = str(line["id"])
        if mail_id in own or mail_id in noes:
            continue
        candidate = _candidate(line, days, identities, owner, orgs, settings.public_suffixes)
        if candidate is None:
            continue
        held = _held(candidate.keys, candidate.amount, candidate.currency, line["at"], money, mail_id)
        if held is not None:
            report.already.append(_with(candidate, None, held))
        else:
            found.append(candidate)
    report.proposals = [_with(c, n, None) for n, c in enumerate(found, start=1)]
    for m in money:
        pair = pairs.get(m.line) if m.source == SOURCE else None
        payer = payers.get(pair.payment) if pair is not None else None
        if payer is not None:
            merchant = _dict(payer.get("payload")).get("merchant")
            held = Held(
                str(payer["id"]),
                int(payer["seq"]),
                str(payer.get("source") or ""),
                merchant if isinstance(merchant, str) else None,
            )
            report.covered.append(
                Covered(
                    m.line, m.seq, m.mail, days.day(m.at).isoformat(), m.merchant, m.amount, m.currency, held
                )
            )
    return report


def _since(since: str | None, today: date) -> str:
    if since is None:
        return (today - timedelta(days=SINCE_DAYS)).isoformat()
    try:
        return date.fromisoformat(since.strip()).isoformat()
    except ValueError:
        raise ReviewError(f"--since takes a day: YYYY-MM-DD, not {since!r}") from None


def _day_before(day: str, n: int) -> str:
    return (date.fromisoformat(day) - timedelta(days=n)).isoformat()


def _standing(
    idx: Index, kind: str, retracted: Collection[str], first_day: str | None, source: str | None
) -> Iterable[Line]:
    superseded = idx.superseded(kind)
    for line in idx.of_kind(kind, first_day=first_day, source=source):
        line_id = str(line.get("id"))
        if line_id not in retracted and line_id not in superseded:
            yield line


def _opened(lb: Logbook, lines: Iterable[Line]) -> Iterable[Line]:
    """The lines as a reader shows them; a sealed line this machine cannot open is never silently left
    out: IdentityRequired names the identity it needs, nothing proposed."""
    shut = 0
    found = []
    for line in lines:
        if is_sealed(line):
            shut += 1
            continue
        found.append(line)
    if shut:
        raise sealing.IdentityRequired(
            f"{shut} line{'s' if shut != 1 else ''} the receipts queue reads {'are' if shut != 1 else 'is'}"
            f" sealed and {'do' if shut != 1 else 'does'} not open on this machine (RFC 0029); none at"
            f" {lb.identity_file}: pass --identity-file or set LOGBOOK_IDENTITY_FILE"
        )
    return found


def _orgs(idx: Index, marks: Sequence[Line]) -> dict[str, str]:
    """Registered domain → the name of the Manifest's org that binds it."""
    lines = [*marks, *idx.resolutions(), *idx.by_kind(entities.ENTITY)]
    known = {(e.kind, e.id): e.label for e in entities.canonical(lines).values()}
    found: dict[str, str] = {}
    for (ref_kind, value), (kind, entity_id) in entities.bindings(lines).items():
        if ref_kind == "domain" and kind == entities.ORG:
            found[value.casefold()] = known.get((kind, entity_id)) or entity_id
    return found


def _money(lb: Logbook, idx: Index, retracted: Collection[str], first_day: str) -> list[_Money]:
    """The standing transaction lines from `first_day` on, and every receipt's own line."""
    seen: dict[str, _Money] = {}
    lines = [
        *_standing(idx, TRANSACTION, retracted, first_day, None),
        *_standing(idx, TRANSACTION, retracted, None, SOURCE),
    ]
    for line in _opened(lb, lines):
        payload = _dict(line.get("payload"))
        at = stays.instant(line.get("at"))
        amount = payload.get("amount")
        if at is None or not isinstance(amount, int | float) or isinstance(amount, bool):
            continue
        extra = _dict(payload.get("extra"))
        if extra.get("deleted") is True:
            continue
        mail = extra.get("from") if line.get("source") == SOURCE else None
        seen[str(line["id"])] = _Money(
            str(line["id"]),
            int(line["seq"]),
            str(line.get("source") or ""),
            at,
            float(amount),
            str(payload.get("currency") or "").upper(),
            payload.get("merchant") if isinstance(payload.get("merchant"), str) else None,
            mail if isinstance(mail, str) else None,
        )
    return sorted(seen.values(), key=lambda m: m.seq)


def _noes(lb: Logbook, idx: Index, retracted: Collection[str]) -> set[str]:
    """The mails the owner said are not a payment: the standing `receipt-review/v1` lines labelled so,
    by mail id."""
    found = set()
    for line in _opened(lb, _standing(idx, REVIEW, retracted, None, SOURCE)):
        payload = _dict(line.get("payload"))
        labels = payload.get("labels")
        mail = _dict(payload.get("extra")).get("from")
        is_no = (
            payload.get("schema") == REVIEW_SCHEMA and isinstance(labels, list) and NOT_A_PAYMENT in labels
        )
        if is_no and isinstance(mail, str):
            found.add(mail)
    return found


def _candidate(
    line: Line,
    days: day_start.DayStart,
    identities: Mapping[resolve.Ref, resolve.Identity],
    owner: present.Owner,
    orgs: Mapping[str, str],
    suffixes: Iterable[str],
) -> Candidate | None:
    payload = _dict(line.get("payload"))
    sender = payload.get("from")
    at = stays.instant(line.get("at"))
    if payload.get("direction") == "sent" or not isinstance(sender, dict) or at is None:
        return None
    email = str(sender.get("email") or "").strip().casefold()
    if "@" not in email:
        return None
    ref = ("email", email)
    if ref in owner.refs:
        return None
    who = identities.get(ref)
    if who is not None and who.entity is not None and who.type in present.PERSON_TYPES:
        return None  # a person the record names is no merchant
    suffixes = list(suffixes)
    registered = entities.registered_domain(domain_of(email), suffixes) or domain_of(email)
    org = orgs.get(registered) or orgs.get(domain_of(email))
    is_role = role(email)
    if not is_role and org is None:
        return None
    subject = payload.get("subject") if isinstance(payload.get("subject"), str) else None
    body = payload.get("body") if isinstance(payload.get("body"), str) else None
    chosen = choose(subject, body)
    if chosen is None:
        return None
    why = []
    confidence = 0.4
    if is_role:
        why.append("an order or no-reply address")
        confidence += 0.1
    if org is not None:
        why.append("org in the Manifest")
        confidence += 0.15
    if chosen.total:
        why.append("a total")
        confidence += 0.2
    elif chosen.in_subject:
        why.append("the subject's amount")
        confidence += 0.2
    elif chosen.only:
        why.append("the one amount")
        confidence += 0.1
    else:
        why.append("the largest of several amounts")
        confidence -= 0.1
    if chosen.subject:
        why.append("the subject says so")
        confidence += 0.1
    if chosen.refund:
        why.append("a refund")
    if body is None:
        why.append("subject only: the line keeps no body")
    merchant = merchant_of(sender, org, suffixes)
    names = (merchant if merchant != NO_SENDER else "", registered.split(".", 1)[0])
    keys = tuple(dict.fromkeys(k for k in map(fold, names) if k))
    return Candidate(
        None,
        str(line["id"]),
        str(line["at"]),
        days.day(at).isoformat(),
        registered,
        merchant,
        chosen.signed,
        chosen.amount.currency,
        chosen.refund,
        round(min(max(confidence, 0.05), 0.95), 2),
        tuple(why),
        keys,
    )


def _held(
    keys: Sequence[str], amount: float, currency: str, at: object, money: Iterable[_Money], mail: str | None
) -> Held | None:
    """The first standing transaction line that holds this payment: the same currency, the same signed
    amount, within `NEAR`, the same merchant; a receipt's own line for the same mail is not another."""
    instant = at if isinstance(at, datetime) else stays.instant(at)
    if instant is None:
        return None
    for m in money:
        if m.mail is not None and m.mail == mail:
            continue
        if m.currency != currency or abs(m.amount - amount) > CENT or abs(m.at - instant) > NEAR:
            continue
        if same_merchant(keys, m.merchant):
            return Held(m.line, m.seq, m.source, m.merchant)
    return None


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _with(c: Candidate, number: int | None, held: Held | None) -> Candidate:
    return Candidate(
        number, c.mail, c.at, c.day, c.domain, c.merchant, c.amount, c.currency, c.refund, c.confidence,
        c.why, c.keys, held,
    )  # fmt: skip


# -- the sitting's hands -----------------------------------------------------------------------------------


def numbers(text: Sequence[str] | None) -> list[int]:
    """`N[,N]`, given once or more, to the numbers in order, each once."""
    found: list[int] = []
    for piece in text or ():
        for word in piece.split(","):
            word = word.strip()
            if not word:
                continue
            if not word.isdigit() or int(word) < 1:
                raise ReviewError(
                    f"not a proposal number: {word!r}; `review receipts` lists them, numbered from 1"
                )
            if int(word) not in found:
                found.append(int(word))
    return found


def pick(report: Report, wanted: Sequence[int]) -> list[Candidate]:
    by_number = {p.number: p for p in report.proposals}
    missing = [n for n in wanted if n not in by_number]
    if missing:
        have = f"{len(report.proposals)} proposal{'' if len(report.proposals) == 1 else 's'}"
        raise ReviewError(
            f"no proposal {', '.join(map(str, missing))}; the queue has {have} (one already in the record"
            " is never one), `review receipts` lists them"
        )
    return [by_number[n] for n in wanted]


def accept(lb: Logbook, report: Report, chosen: Iterable[Candidate]) -> list[Written]:
    """One tier-3 `transaction/v1` line per candidate, through `Logbook.append`; a second candidate of
    the same merchant, day, currency and amount in the batch is the same payment, refused and counted
    as a `duplicate`, never written. Under the writer lock,
    the mails are asked again first for a standing receipt's line (another sitting may have written
    one since the queue was read): when one has, nothing is written. A retracted line holds nothing."""
    chosen = list(chosen)
    if not chosen:
        return []
    written = []
    with lb.writer():
        held = accepted(lb)
        twice = [c for c in chosen if c.mail in held]
        if twice:
            raise ReviewError(
                f"proposal {', '.join(str(c.number) for c in twice)} has a payment line already"
                f" (#{', #'.join(str(held[c.mail]) for c in twice)}), written since the queue was read;"
                " `review receipts` lists it again"
            )
        first: dict[tuple[str, str, str, float], Candidate] = {}
        for c in chosen:
            who = fold(c.merchant) if c.merchant != NO_SENDER else f"@{c.domain}"  # two unnamed are two
            key = (who, c.day, c.currency, round(c.amount, 2))
            if key in first:
                written.append(Written("duplicate", c, None, first[key].number))
                continue
            first[key] = c
            payload: dict[str, Any] = {
                "schema": TRANSACTION_SCHEMA,
                "raw_id": c.mail,
                "amount": c.amount,
                "currency": c.currency,
                "merchant": c.merchant,
                "provider": PROVIDER,
                "extra": {
                    "from": c.mail,
                    "confidence": c.confidence,
                    **({"refund": True} if c.refund else {}),
                },
            }
            line = lb.append(at=c.at, source=SOURCE, kind=TRANSACTION, tier=TIER, payload=payload)
            written.append(Written("accepted", c, line))
    return written


def accepted(lb: Logbook) -> dict[str, int]:
    """Mail line id → the seq of its standing receipt's line."""
    found: dict[str, int] = {}
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        for line in _opened(lb, _standing(idx, TRANSACTION, retracted, None, SOURCE)):
            mail = _dict(_dict(line.get("payload")).get("extra")).get("from")
            if isinstance(mail, str):
                found[mail] = int(line["seq"])
    return found


def reject(lb: Logbook, report: Report, rejected: Iterable[Candidate]) -> list[Written]:
    """One `receipt-review/v1` line per candidate, through `Logbook.append`: tier 3 like the payments,
    now, labelled `not-a-payment`, its words naming no amount, no currency and no merchant,
    `extra.from` the mail line's id."""
    written = []
    for c in rejected:
        payload = {
            "schema": REVIEW_SCHEMA,
            "text": NO_TEXT,
            "labels": [NOT_A_PAYMENT],
            "extra": {"from": c.mail},
        }
        line = lb.append(at=now_utc(), source=SOURCE, kind=REVIEW, tier=TIER, payload=payload)
        written.append(Written("rejected", c, line))
    return written


# -- what is printed ---------------------------------------------------------------------------------------


def money_text(amount: float, currency: str) -> str:
    return f"{currency} {amount:+,.2f}".replace(",", "\u2009")


def rows(report: Report) -> Iterable[str]:
    if report.withheld:
        yield "the receipts queue is tier 3: this reader's tiers leave it out"
        return
    s = "" if len(report.proposals) == 1 else "s"
    yield (
        f"{len(report.proposals)} receipt{s} proposed · {len(report.already)} already in the record ·"
        f" {report.accepted} accepted · {report.rejected} not a payment · since {report.since} · tier {TIER}"
    )
    for p in report.proposals:
        yield (
            f"{p.number:>3}  {p.day}  {p.merchant}  {money_text(p.amount, p.currency)}"
            f"{'  refund' if p.refund else ''}  {p.confidence:.2f}"
        )
        yield f"       {p.domain} · {' · '.join(p.why)}"
    for p in report.already:
        held = p.held_by
        assert held is not None
        yield (
            f"  —  {p.day}  {p.merchant}  {money_text(p.amount, p.currency)}  already in the record:"
            f" {held.source} #{held.seq}"
        )
    for c in report.covered:
        yield (
            f"  —  {c.day}  {c.merchant or ''}  {money_text(c.amount, c.currency)}  receipt #{c.seq} is"
            f" covered by {c.held_by.source} #{c.held_by.seq}, which wins: logbook repair retract {c.seq}"
            f' "covered by {c.held_by.source} #{c.held_by.seq}"'
        )
    if report.proposals:
        yield "--accept N,N writes each as a payment; --reject N writes that it is not one; both tier 3"
    else:
        yield "no receipt waits to be confirmed"


def written_rows(written: Sequence[Written]) -> Iterable[str]:
    for w in written:
        c = w.candidate
        if w.line is None:
            yield (
                f"     {c.number}  {c.merchant}  {money_text(c.amount, c.currency)}: the same payment as"
                f" {w.same_as} in this batch, not written"
            )
        elif w.verdict == "accepted":
            yield (
                f"#{w.line['seq']}  {c.number}  {c.merchant}  {money_text(c.amount, c.currency)}:"
                " a payment (tier 3)"
            )
        else:
            yield f"#{w.line['seq']}  {c.number}  {c.merchant}: not a payment (tier 3), never proposed again"
    duplicates = sum(1 for w in written if w.verdict == "duplicate")
    if duplicates:
        yield f"{duplicates} duplicate{'' if duplicates == 1 else 's'} refused"
