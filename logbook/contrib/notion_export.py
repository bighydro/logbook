"""`logbook export notion OUT [--since DAY] [--include-unsigned] [--dry-run]`: the record's facts for the
owner's Notion, as a crossing (docs/export-notion.md).

Hermes keeps the owner's Notion workspace; the record feeds it the way `export crossing` feeds Hermes:
this command writes one folder and stops. It matches nothing on the Notion side, asks Notion nothing
and creates nothing there; a separate program carries the folder later. What may leave is the
`notion` entry of `policy/crossing.json` (ADR 0016), held against today: a record whose file does not
name it, or whose entry has expired, lets nothing leave and says so in one sentence. Tier 3 never
leaves, whatever the entry says.

**The gate.** Every line a fact rests on passes the entry's ceiling and, as in every crossing, the
signed-day gate (RFC 0034): only the lines of days the owner has signed, unless the entry says
`"include_unsigned": true` and the owner types `--include-unsigned`. A retracted line counts for
nothing. Every event rests on lines written in the window (from the start of `--since`, default the
record's first day, to the read time) that pass the gate; an idea's current status is a state, read
from every status line the gate lets through, whatever its day, and a person's days together are a
total, read over the whole record to the read time through the same gate. The lines that bind a name to a ref,
`resolution/v1` and `entity/v1`, are the crossing's overlay (RFC 0005): from any day, held to the
ceiling, not to the signature, as `export crossing` ships them. A day together rests on its evidence
line, and a promise's speaker and counterpart are resolved through the same gate
(`promises.extract(admit=...)`).

**The body.** `manifest.json` is the envelope: `export_id` (a UUIDv7, one per run), `as_of` (the read
time), `read_head` (the head the facts were read at), `policy` (the entry's name and version,
`policy.version`) and `signed_only`, with the window, the counts, what was left out and the list of
the other files. Three sections, one file each, each matched on the Notion side by its key alone:

- `persons.json`: every person the record names who had any contact in the window (`people`: a
  message, a call, a mail, a calendar entry, a recording, a tagged face or a day together), by the
  record's person id, with the `identities` the resolution lines hold (email, phone, handle) and the
  `facts`: the last contact (its date and kind), the days together over the whole record
  (`days_together`, `first_together`, `last_together`), and the promises open both ways said in the
  window and in the 365 days before the read time, in a conversation the person is a direct party to
  (`Proposal.parties`), the owner's own or the person's own and never a request (`PROMISE_ROLES`), one
  whole sentence and never a quoted line, a pasted chat line or a whole chat message
  (`whole_sentence`), newest first, ten a side (`promises`: the sentence as it quotes it, its date,
  the line it was read in), the rest counted (`promises_more`). No message, mail or transcript text
  but that one sentence. The person's `page` is the facts as German lines, emitted whole: the writer
  replaces the page, never merges it.
- `ideas.json`: every idea whose entity has a Notion page ref (`page`, `notion:<id>`), with its
  current status (tier 2), the reason note for it when there is one, and a dated entry in German per
  status line written in the window, superseded or not, the owner's own words quoted as written.
- `orgs.json`: every org with a domain (its registered domain, as the record keys an org), touched in
  the window by a mail or a calendar entry through that domain: the days it was touched and a dated
  entry per day. Never an org's status, reason,
  portfolio tag or money: those are tier 3 (RFC 0037 §8), and companies reach the family as a printed
  export, never through Notion.

Anything without a key (a person with no email, phone or handle; an idea with no Notion page; an org
with no domain) is left out and counted. A quoted sentence that names money is left out and counted;
a promise that talks of money without a figure (a payment, an invoice, a transfer, a price) too.
No model runs: every German word is a template here, and the owner's words are quoted, never
paraphrased.

**The folder** is built from nothing beside OUT and replaces it whole (`crossing.place`, #280), so
nothing of an earlier run is left in it; OUT that holds anything but an earlier export of this
command is refused unless `--force`. Then one `crossing/v1` line (RFC 0011), destination `notion`,
says what left; it is the only write to the record and goes through `Logbook.append`. A dry run
counts and writes nothing."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from .. import __version__
from ..core import crossing, day_start, people, policy, present, reading, signing, stays
from ..core.chain import Line
from ..core.day_start import DayStart
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.store import HEAD_MOVED, HeadMoved, Logbook, retractions, uuid7
from . import entities, people_drift
from . import promises as promise_reader

DESTINATION = policy.NOTION_DESTINATION
SCHEMA = "notion-export/v1"  # the manifest's schema: an earlier folder of this command is replaced
SCHEMAS = frozenset({SCHEMA})
MANIFEST_FILE = crossing.MANIFEST_FILE
PERSONS_FILE, IDEAS_FILE, ORGS_FILE = "persons.json", "ideas.json", "orgs.json"
TIERS = (1, 2)  # what may leave for Notion under the highest entry; tier 3 never does
IDENTITY_KINDS = frozenset({"email", "phone", "handle"})  # what a person is matched on in Notion
NOTION_PAGE = "notion:"
STATUS_LABEL = "status"  # the label of the note a status reason is written as (RFC 0037 §10.5)
TOGETHER = "together"  # a last contact that was a day together, not a line of one kind
# on one day, the contact that names it: being together, then a call, a message, a recording, a
# calendar entry, a mail, a tagged face
CONTACT_ORDER = (TOGETHER, "call", "message", "transcript", "event", "mail", "photo")
CONTACT_WORDS = {
    TOGETHER: "Treffen",
    "call": "Anruf",
    "message": "Nachricht",
    "transcript": "Gespräch",
    "event": "Termin",
    "mail": "E-Mail",
    "photo": "Foto",
}
STATUS_WORDS = {  # an idea's dispositions (RFC 0037 §10.3) in German, the word itself beside it
    "spark": "Funke",
    "exploring": "in Erkundung",
    "build": "im Bau",
    "built": "gebaut",
    "killed": "verworfen",
}
PROMISE_DAYS = 365  # a promise on a page was said in the year before the read time
PROMISES_SHOWN = 10  # a side of a page lists the newest ten; the rest are counted ("und N weitere")
# A promise on a page is what the promises reader reads as the owner's own or the person's own, never a
# request: someone asking is not someone promising (`people_drift.promises_with` reads a request the
# person writes as owed by the owner).
PROMISE_ROLES = frozenset({promise_reader.PROMISE, promise_reader.THEIRS})
# A sentence that is no sentence of the owner's or the person's: a line quoted from what they answer
# (`> …`), a line of a chat pasted whole (`[12.09.26, 15:10] Ola: …`), or a run of more than
# `SENTENCE_WORDS` words with no full stop in it, which is a whole chat message, not a sentence.
QUOTED_LINE = re.compile(r"^\s*[>|]")
CHAT_STAMP = re.compile(r"^\[?\d{1,4}[./-]\d{1,2}[./-]\d{1,4},?\s+\d{1,2}[:.]\d{2}")
SENTENCE_WORDS = 40
DASH = "\u2014"  # between an entry's date and its text
EN_DASH = "\u2013"  # a bullet on a person's page, and a span of days
OPEN_QUOTE, CLOSE_QUOTE = "\u201e", "\u201c"  # German quotes, low then high
# Money in a sentence, as people write it: a currency sign, a currency code or word ("NOK", "MNOK",
# "NOK5000", "500kr", "kroner", "euros", "quid"), a Norwegian price ("300,-") or a figure with a
# magnitude ("250k", "5 mill", "2 mrd"). A code or word may touch a digit but not another letter. A
# sentence that holds any of them is left out of the bundle and counted: leaving out a sentence costs a
# line on a page, letting money through is what the crossing must never do.
_CODES = r"[kmb]?(?:nok|sek|dkk|eur|usd|gbp|chf)|btc|eth"
_WORDS = r"kr|kroner|krone|kronor|øre|euros?|cents?|dollars?|pounds?|pence|quid|bucks"
_MAGNITUDE = r"k|mill|million|millions|millioner|mrd|milliard|milliarder|bn|billion|billions"
_LETTER_BEFORE, _LETTER_AFTER = r"(?<![^\W\d_])", r"(?![^\W\d_])"  # not touching a letter
MONEY = re.compile(
    rf"[€$£¥]|{_LETTER_BEFORE}(?:{_CODES}|{_WORDS}){_LETTER_AFTER}|\d\s*,-"
    rf"|\d[\d.,']*\s?(?:{_MAGNITUDE}){_LETTER_AFTER}",
    re.IGNORECASE,
)
# Talk of money with no figure in it, which `MONEY` cannot see: a payment, an invoice, a transfer, a
# price, in German and English, each word in the forms a sentence gives it ("Ich überweise dir das
# morgen", "send me the invoice"). Money stays out of Notion: that is the owner's rule. A promise that
# holds one of these words is left out of a person's page and facts and counted under
# `sentences_with_money`, as one with a sum is (`talks_money`); an idea's reason is held to `MONEY`
# alone. A word may close a longer one where German builds one (`Anzahlung`, `Kaufpreis`).
MONEY_WORDS = (
    r"(?:an|aus|be|ein|ge|nach|zurück)?zahl(?:e|en|st|t|te|ten|test|tet)",  # zahlen, bezahle, gezahlt
    r"\w*zahlung(?:en|s\w*)?",  # Zahlung, Anzahlung, Zahlungsfrist
    r"(?:ab|end|gut|schluss|teil|vor)?rechnung(?:en|s\w*)?",  # Rechnung, Abrechnung; not Berechnung
    r"überw(?:eis|ies)\w*",  # überweisen, überweise, Überweisung, überwiesen
    r"\w*preis(?:e|en|es|liste\w*)?",  # Preis, Kaufpreis, Preisliste
    r"geld(?:er|es)?",
    r"kost(?:en|et|est)",
    r"(?:pre|re)?pay(?:s|ing|ment|ments|able|back|out|pal)?",
    r"(?:pre|re|un)?paid",
    r"invoic(?:e|es|ed|ing)",
    r"transfer(?:s|red|ring)?",
    r"wir(?:e|es|ed|ing)",
    r"pric(?:e|es|ed|ing)",
    r"money",
    r"cost(?:s|ing)?",
)
MONEY_TALK = re.compile(rf"{_LETTER_BEFORE}(?:{'|'.join(MONEY_WORDS)}){_LETTER_AFTER}", re.IGNORECASE)


class NotionError(ValueError):
    """A request the policy or the record refuses; the message is one sentence and says why."""


def now() -> datetime:
    """The read time: `as_of`, and the crossing line's `at`. Tests replace it."""
    return datetime.now(UTC)


def stamp(at: datetime) -> str:
    return at.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def german(day: str) -> str:
    """`2026-09-20` as German writes a date: `20.09.2026`."""
    found = date.fromisoformat(day)
    return f"{found.day:02d}.{found.month:02d}.{found.year}"


def quoted(text: str) -> str:
    return f"{OPEN_QUOTE}{text}{CLOSE_QUOTE}"


def names_money(text: str) -> bool:
    return MONEY.search(text) is not None


def talks_money(text: str) -> bool:
    """A sum or a currency (`names_money`), or a word of `MONEY_WORDS`: a promise either way stays
    home."""
    return names_money(text) or MONEY_TALK.search(text) is not None


# -- the request -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Request:
    """One run, checked against the policy: the entry as it counts today, the window of local days
    `[since, until]` (until is the day of `as_of`), the read time and whether the signed-day gate
    holds."""

    entry: policy.Ceiling
    since: str
    until: str
    as_of: str
    signed_only: bool

    @property
    def tiers(self) -> tuple[int, ...]:
        return tuple(t for t in TIERS if t <= self.entry.max_tier)

    @property
    def version(self) -> str:
        return policy.version(self.entry)


def request(
    lb: Logbook, since: str | None, include_unsigned: bool = False, at: datetime | None = None
) -> Request:
    """Hold the run against the `notion` entry: refused when the file names none, when it has expired,
    and when `--include-unsigned` is asked for and the entry does not allow it. `since` is a local
    day, `YYYY-MM-DD`; without it the window opens on the record's first day."""
    try:
        entry = policy.notion_entry(lb.root)
    except policy.PolicyError as e:
        raise NotionError(str(e)) from e
    if include_unsigned and not entry.include_unsigned:
        raise NotionError(
            f"--include-unsigned needs {json.dumps({policy.INCLUDE_UNSIGNED: True})} in the {DESTINATION!r}"
            f" entry of {policy.policy_path(lb.root)}; without it only signed days leave for Notion"
        )
    read_at = (at or now()).astimezone(UTC).replace(microsecond=0)
    days = day_start.of(lb.meta)
    today = days.day(read_at).isoformat()
    if since is None:
        span = reading.record_span(lb)
        first = span[0] if span is not None else today
    else:
        try:
            first = parse_day(since).isoformat()
        except ValueError:
            raise NotionError(f"--since takes a day, YYYY-MM-DD, not {since!r}") from None
    if first > today:
        raise NotionError(f"--since {first} is after today, {today}; nothing has happened there yet")
    return Request(entry, min(first, today), today, stamp(read_at), not include_unsigned)


# -- the gate --------------------------------------------------------------------------------------------


@dataclass
class Gate:
    """What a line must pass before a fact may rest on it: a tier the request crosses, a signed day
    unless the gate is lifted, no retraction, and an instant before the read time (RFC 0011: the
    window is `from` <= `at` < `to`). The lines that bind names (`resolution/v1`, `entity/v1`) are
    the overlay and are held to the tier alone, as a crossing ships them. Every line is counted once,
    by what became of it, for the crossing line's `counts`."""

    tiers: frozenset[int]
    signed: frozenset[str] | None  # None: the gate is lifted
    days: DayStart
    retracted: frozenset[str]
    before: datetime  # the read time, `as_of`
    passed: dict[str, tuple[int, str]] = field(default_factory=dict)  # a fact's line → (tier, kind)
    bound: set[str] = field(default_factory=set)  # overlay lines let through
    above_tier: set[str] = field(default_factory=set)
    unsigned: set[str] = field(default_factory=set)
    overlay_held: set[str] = field(default_factory=set)

    def overlay(self, line: Line) -> bool:
        line_id = str(line.get("id"))
        if int(line.get("tier", 0)) not in self.tiers:
            self.overlay_held.add(line_id)
            return False
        self.bound.add(line_id)
        return True

    def fact(self, line: Line) -> bool:
        line_id = str(line.get("id"))
        at = stays.instant(line.get("at"))
        if line_id in self.retracted or at is None or at >= self.before:
            return False
        tier = int(line.get("tier", 0))
        if tier not in self.tiers:
            self.above_tier.add(line_id)
            return False
        if self.signed is not None and self.days.day(at).isoformat() not in self.signed:
            self.unsigned.add(line_id)
            return False
        self.passed[line_id] = (tier, str(line.get("kind")))
        return True

    def admit(self, line: Line) -> bool:
        """For a reader that takes one gate for both: the overlay's rule for a resolution line, the
        fact's for everything else."""
        return self.overlay(line) if line.get("kind") == "resolution" else self.fact(line)

    def counts(self) -> dict[str, int]:
        return {"above_tier": len(self.above_tier), "unsigned": len(self.unsigned)}

    def lines(self) -> dict[str, Any]:
        """RFC 0011's `counts`, in the crossing's shape, of the lines read through the gate: `logged`
        the lines a fact could rest on, `crossed` those it let through (the folder carries facts read
        off them, never the lines), `held_back` the rest; the overlay as `resolutions`. No file of the
        store is copied, so the attachments are zero."""
        held = self.above_tier | self.unsigned
        return {
            "logged": len(self.passed) + len(held),
            "crossed": len(self.passed),
            "held_back": len(held),
            "held_back_unsigned": len(self.unsigned),
            "by_tier": {
                str(t): sum(1 for tier, _ in self.passed.values() if tier == t) for t in policy.TIERS
            },
            "by_kind": dict(sorted(Counter(kind for _, kind in self.passed.values()).items())),
            "resolutions": len(self.bound),
            "resolutions_held_back": len(self.overlay_held),
            "attachments": {"included": 0, "bytes": 0, "missing": 0},
        }


def gate(lb: Logbook, req: Request) -> Gate:
    meta = lb.meta
    with lb.index() as idx:
        retracted = frozenset(retractions(idx.retractions()))
        signed = frozenset(signing.gate(idx, str(meta["owner_id"]))[0]) if req.signed_only else None
    before = datetime.fromisoformat(req.as_of.replace("Z", "+00:00"))
    return Gate(frozenset(req.tiers), signed, day_start.of(meta), retracted, before)


# -- the sections ----------------------------------------------------------------------------------------


@dataclass
class Built:
    """What one run would hand over: the three sections, what was left out for want of a key or for
    naming money, and what the gate held back."""

    persons: list[dict[str, Any]]
    ideas: list[dict[str, Any]]
    orgs: list[dict[str, Any]]
    left_out: dict[str, int]
    held_back: dict[str, int]
    lines: dict[str, Any]  # RFC 0011's counts of the lines read through the gate (`Gate.lines`)

    def sections(self) -> dict[str, int]:
        """How wide the pages' two long sections are, in totals: the lines of the days together and the
        pages they are on; the lines of the promises, the promises listed and those past the cap."""
        together = [len(_together_lines(p["facts"])) for p in self.persons]
        facts = [p["facts"] for p in self.persons]
        return {
            "together": sum(together),
            "together_pages": sum(1 for n in together if n),
            "promise_lines": sum(len(_promise_lines(f)) for f in facts),
            "listed": sum(len(found) for f in facts for found in f["promises"].values()),
            "more": sum(n for f in facts for n in f["promises_more"].values()),
        }

    def counts(self) -> dict[str, Any]:
        return {
            "persons": len(self.persons),
            "ideas": len(self.ideas),
            "orgs": len(self.orgs),
            "entries": {
                "ideas": sum(len(i["entries"]) for i in self.ideas),
                "orgs": sum(len(o["entries"]) for o in self.orgs),
            },
        }


def build(lb: Logbook, req: Request, airports: Airports | None = None) -> Built:
    """Read the record through the gate and compose the three sections. Writes nothing."""
    g = gate(lb, req)
    left: dict[str, int] = {
        "persons_without_identity": 0,
        "ideas_without_page": 0,
        "orgs_without_domain": 0,
        "sentences_with_money": 0,
    }
    report = people.read(lb, req.since, req.until, airports, admit=g.admit)
    together = _together(lb, req, g, report, airports)
    persons = _persons(lb, req, g, report, together, left)
    with lb.index() as idx:
        marks = idx.retractions()
        bound = [line for line in [*idx.resolutions(), *idx.by_kind(entities.ENTITY)] if g.overlay(line)]
        known = entities.canonical([*marks, *bound])
        ideas = _ideas(idx, req, g, known, marks, left)
        orgs = _orgs(lb, idx, req, g, known, report.owner, left)
    return Built(persons, ideas, orgs, left, g.counts(), g.lines())


def _together(
    lb: Logbook, req: Request, g: Gate, report: people.Report, airports: Airports | None
) -> dict[str, list[str]]:
    """The days together of everyone heard in the window, over their whole history in the record (from
    its first day to the read time, through the same gate), oldest first: a total, as an idea's status
    is a state, so a narrow window never blanks it. A day together rests on its evidence lines, which
    the gate counts as crossed; nothing else the longer read lets through informs a fact, so nothing
    else of it is counted."""
    span = reading.record_span(lb)
    first = span[0] if span is not None else req.since
    heard = {person.entity for person in report.people}
    if first >= req.since:
        return {p.entity: p.days for p in report.people if p.days}
    wide = replace(g, passed={}, bound=set(), above_tier=set(), unsigned=set(), overlay_held=set())
    whole = people.read(lb, first, req.until, airports, admit=wide.admit)
    out: dict[str, list[str]] = {}
    for entity in sorted(heard):
        person = whole.known.get(entity)
        if person is None or not person.days:
            continue
        out[entity] = person.days
        for shared in person.shared.values():
            for line_id in shared.lines:
                if line_id in wide.passed:
                    g.passed[line_id] = wide.passed[line_id]
    return out


def _persons(
    lb: Logbook,
    req: Request,
    g: Gate,
    report: people.Report,
    together: Mapping[str, list[str]],
    left: dict[str, int],
) -> list[dict[str, Any]]:
    """Everyone heard in the window who has a key, with the facts of their page: the last contact in
    the window, the days together over the whole record, and the open promises said in the window and
    in the `PROMISE_DAYS` before the read time, in a conversation the person is a direct party to
    (`Proposal.parties`: a direct chat, a mail both are on and no list sent, a call they spoke in; a
    mail's quoted part is never read), the owner's own or the person's own in one whole sentence
    (`_a_promise`), newest first, `PROMISES_SHOWN` a side and the rest counted."""
    heard = list(report.people)
    cutoff = datetime.fromisoformat(req.as_of.replace("Z", "+00:00")) - timedelta(days=PROMISE_DAYS)
    since = max(req.since, g.days.day(cutoff).isoformat())
    owed = people_drift.promises_with(lb, heard, admit=g.admit, since=since, until=req.until)
    sides = (promise_reader.OWED_BY_OWNER, promise_reader.OWED_TO_OWNER)
    out = []
    for person in sorted(heard, key=lambda p: p.entity):
        identities = sorted({ref for ref in person.refs if ref[0] in IDENTITY_KINDS})
        if not identities:
            left["persons_without_identity"] += 1
            continue
        found: dict[str, list[tuple[datetime, int, dict[str, str]]]] = {side: [] for side in sides}
        for proposal, mine in owed.get(person.entity, []):
            at = stays.instant(proposal.at)
            if at is None or at < cutoff or person.entity not in proposal.parties:
                continue
            sentence = proposal.match.quote
            if talks_money(sentence):
                left["sentences_with_money"] += 1
                continue
            if not _a_promise(proposal):
                continue
            side = promise_reader.OWED_BY_OWNER if mine else promise_reader.OWED_TO_OWNER
            said = {"sentence": sentence, "date": proposal.day, "line": proposal.line}
            found[side].append((at, proposal.seq, said))
        newest = {
            side: [said for *_, said in sorted(found[side], key=lambda f: f[:2], reverse=True)]
            for side in sides
        }
        days = together.get(person.entity, [])
        facts = {
            "last_contact": _last_contact(person),
            "days_together": len(days),
            "first_together": days[0] if days else None,
            "last_together": days[-1] if days else None,
            "promises": {side: newest[side][:PROMISES_SHOWN] for side in sides},
            "promises_more": {side: max(0, len(newest[side]) - PROMISES_SHOWN) for side in sides},
        }
        out.append(
            {
                "id": person.entity,
                "identities": [{"kind": kind, "value": value} for kind, value in identities],
                "facts": facts,
                "page": list(_person_page(req, facts)),
            }
        )
    return out


def _a_promise(p: promise_reader.Proposal) -> bool:
    """Whether a proposal is a promise for a page: the owner's own or the person's own words (a request
    is someone asking, not a promise), in one whole sentence (`whole_sentence`)."""
    return p.role in PROMISE_ROLES and whole_sentence(p.match.quote)


def whole_sentence(quote: str) -> bool:
    """Whether a quote is one sentence of the owner's or the person's: not a line quoted in a reply,
    not a chat line pasted with its time stamp, not a run of more than `SENTENCE_WORDS` words."""
    return not (QUOTED_LINE.match(quote) or CHAT_STAMP.match(quote) or len(quote.split()) > SENTENCE_WORDS)


def _last_contact(person: people.Person) -> dict[str, str] | None:
    """The last day of any contact in the window, and what it was: a day together, else the kind of
    the line, by `CONTACT_ORDER` when several fell on that day."""
    found = [(c.last, people.KIND_OF[name]) for name, c in person.channels.items() if c.last]
    found += [(day, TOGETHER) for day in person.days]
    if not found:
        return None
    last = max(day for day, _kind in found)
    kinds = {kind for day, kind in found if day == last}
    return {"date": last, "kind": next(kind for kind in CONTACT_ORDER if kind in kinds)}


def _person_page(req: Request, facts: Mapping[str, Any]) -> Iterator[str]:
    """The person's facts as the lines of a page, in German, whole."""
    yield f"Stand: {german(req.until)}, aus dem Logbuch"
    contact = facts["last_contact"]
    if contact is None:
        yield f"Letzter Kontakt: keiner seit {german(req.since)}"
    else:
        yield f"Letzter Kontakt: {german(contact['date'])} ({CONTACT_WORDS[contact['kind']]})"
    yield from _together_lines(facts)
    yield from _promise_lines(facts)


def _together_lines(facts: Mapping[str, Any]) -> list[str]:
    """The days together over the whole record, with the first and the last; none on the page of a
    person with no day together."""
    if not facts["days_together"]:
        return []
    return [
        f"Tage zusammen: {facts['days_together']}"
        f" (zuerst {german(facts['first_together'])}, zuletzt {german(facts['last_together'])})"
    ]


def _promise_lines(facts: Mapping[str, Any]) -> list[str]:
    """Each side's open promises, newest first, as the facts list them, then how many more there are."""
    out = []
    for side, title in (
        (promise_reader.OWED_BY_OWNER, "Offene Versprechen von mir"),
        (promise_reader.OWED_TO_OWNER, "Offene Versprechen an mich"),
    ):
        found = facts["promises"][side]
        if not found:
            out.append(f"{title}: keine")
            continue
        out.append(f"{title}:")
        for promise in found:
            out.append(f"{EN_DASH} {quoted(promise['sentence'])} ({german(promise['date'])})")
        more = facts["promises_more"][side]
        if more:
            out.append(f"und {more} weitere")
    return out


def _ideas(
    idx: Any,
    req: Request,
    g: Gate,
    known: Mapping[tuple[str, str], entities.Entity],
    marks: list[Line],
    left: dict[str, int],
) -> list[dict[str, Any]]:
    """Every idea with a Notion page ref: its current status, a state, as the gate lets it be read
    (the last standing status line it lets through, whatever its day, so a narrow window never blanks
    a status), the reason note for it, and an entry per status line written in the window, superseded
    or not, dated the day it took effect (`since`, else the line's day): the history the writer
    appends, one entry per line, once. An org's status is never read."""
    status_lines = [
        line
        for line in idx.by_kind(entities.STATUS)
        if entities.kind_of((line.get("payload") or {}).get("entity")) == entities.IDEA and g.fact(line)
    ]
    history = entities.statuses([*marks, *status_lines])
    written: dict[tuple[str, str], list[entities.Status]] = {}  # every line, whatever supersedes it
    for line in status_lines:
        if not req.since <= g.days.day_of(str(line.get("at"))) <= req.until:
            continue
        for key, found in entities.statuses([line]).items():
            written.setdefault(key, []).extend(found)
    named = {str(line["id"]): (line.get("payload") or {}).get("note") for line in status_lines}
    notes, noted = _reason_notes(idx, g)
    local = g.days.day_of
    reasons: dict[str, dict[str, str] | None] = {}  # by status line, read once (a money reason counts once)

    def reason_of(status: entities.Status) -> dict[str, str] | None:
        if status.line not in reasons:
            reasons[status.line] = _reason(status, named.get(status.line), notes, noted, left)
        return reasons[status.line]

    out = []
    for (kind, entity_id), entity in sorted(known.items()):
        if kind != entities.IDEA:
            continue
        pages = [
            value for ref_kind, value in entity.refs if ref_kind == "page" and value.startswith(NOTION_PAGE)
        ]
        if not pages:
            left["ideas_without_page"] += 1
            continue
        entries = []
        for status in written.get((entities.IDEA, entity_id), []):
            day = status.day(local)  # chosen by the day the line was written, dated by when it took effect
            reason = reason_of(status)
            word = STATUS_WORDS.get(status.status, status.status)
            text = f"{german(day)} {DASH} Status: {word} ({status.status})."
            if reason is not None:
                text += f" Begründung: {quoted(reason['text'])}"
            lines = [status.line] + (
                [reason["line"]] if reason is not None and reason["line"] != status.line else []
            )
            entries.append({"id": status.line, "date": day, "text": text, "lines": lines})
        found = history.get((entities.IDEA, entity_id), [])
        current = found[-1] if found else None
        out.append(
            {
                "page": pages[0],
                "status": None
                if current is None
                else {"status": current.status, "since": current.day(local), "line": current.line},
                "reason": None if current is None else reason_of(current),
                "entries": sorted(entries, key=lambda e: (e["date"], e["id"])),
            }
        )
    return sorted(out, key=lambda i: i["page"])


def _reason_notes(idx: Any, g: Gate) -> tuple[dict[str, Line], set[str]]:
    """The status notes the gate lets through, by the status line they were written with (the note's
    `extra.status`) and by their own id; and the status lines any note of the record names, passed
    or not, so that a reason held back is never read off the status line instead."""
    passed: dict[str, Line] = {}
    noted: set[str] = set()
    for line in idx.by_kind("note"):
        payload = line.get("payload") or {}
        labels = payload.get("labels")
        if not isinstance(labels, list) or STATUS_LABEL not in labels:
            continue
        extra = payload.get("extra")
        status = extra.get("status") if isinstance(extra, dict) else None
        if isinstance(status, str):
            noted.add(status)
        noted.add(str(line["id"]))
        if g.fact(line):
            if isinstance(status, str):
                passed[status] = line
            passed[str(line["id"])] = line
    return passed, noted


def _reason(
    status: entities.Status,
    note_id: object,
    notes: Mapping[str, Line],
    noted: set[str],
    left: dict[str, int],
) -> dict[str, str] | None:
    """The owner's words on why, verbatim: the note written with the status line when the gate lets it
    through; the status line's own `reason` only when no note of the record carries it. A reason
    that names money is left out and counted."""
    note = notes.get(status.line) or (notes.get(note_id) if isinstance(note_id, str) else None)
    found: dict[str, str] | None = None
    if note is not None:
        text = (note.get("payload") or {}).get("text")
        if isinstance(text, str) and text.strip():
            found = {"text": text, "line": str(note["id"])}
    elif status.line not in noted and not (isinstance(note_id, str) and note_id in noted) and status.reason:
        found = {"text": status.reason, "line": status.line}
    if found is not None and names_money(found["text"]):
        left["sentences_with_money"] += 1
        return None
    return found


def _orgs(
    lb: Logbook,
    idx: Any,
    req: Request,
    g: Gate,
    known: Mapping[tuple[str, str], entities.Entity],
    owner: present.Owner,
    left: dict[str, int],
) -> list[dict[str, Any]]:
    """Every org with a domain that a mail or a calendar entry in the window touched through it: the
    days, and an entry per day. Its status, reason, tags and the ledger are never read."""
    try:
        settings = entities.read_settings(lb.root)
    except entities.EntityError as e:
        raise NotionError(str(e)) from e
    domains: dict[str, str] = {}
    for (kind, entity_id), entity in sorted(known.items()):
        if kind != entities.ORG:
            continue
        own = [  # keyed as the record keys an org (`entities.key_of`): by the registered domain
            entities.registered_domain(value, settings.public_suffixes) or value.strip().lower()
            for ref_kind, value in entity.refs
            if ref_kind == "domain" and value.strip()
        ]
        if not own:
            left["orgs_without_domain"] += 1
            continue
        for domain in own:
            domains.setdefault(domain, entity_id)
    touched: dict[str, set[str]] = {}
    for kind in ("mail", "event"):
        superseded = idx.superseded(kind)
        for line in idx.of_kind(kind, req.since, req.until):
            if str(line.get("id")) in superseded:
                continue
            day = g.days.day_of(str(line.get("at")))
            if not req.since <= day <= req.until:
                continue
            hit = {
                d
                for address in _addresses(kind, line.get("payload") or {})
                if ("email", address) not in owner.refs
                if (d := entities.registered_domain(address.rsplit("@", 1)[1], settings.public_suffixes))
                in domains
            }
            if hit and g.fact(line):
                for domain in hit:
                    touched.setdefault(domain, set()).add(day)
    out = []
    for domain in sorted(touched):
        days = sorted(touched[domain])
        out.append(
            {
                "domain": domain,
                "touched": days,
                "last_touch": days[-1],
                "entries": [
                    {"id": f"{domain}/{day}", "date": day, "text": f"{german(day)} {DASH} Kontakt."}
                    for day in days
                ],
            }
        )
    return out


def _addresses(kind: str, payload: Mapping[str, Any]) -> Iterator[str]:
    """The addresses on a mail's headers, or a calendar entry's attendees who did not decline and its
    organizer, lower-cased."""
    if kind == "mail":
        for header in ("from", "to", "cc", "bcc"):
            value = payload.get(header)
            for address in value if isinstance(value, list) else [value]:
                email = address.get("email") if isinstance(address, dict) else None
                if isinstance(email, str) and "@" in email:
                    yield email.strip().casefold()
        return
    attendees = payload.get("attendees")
    refs = (
        [a.get("ref") for a in attendees if isinstance(a, dict) and a.get("response") != "declined"]
        if isinstance(attendees, list)
        else []
    )
    for ref in [*refs, payload.get("organizer")]:
        if isinstance(ref, dict) and ref.get("kind") == "email" and isinstance(ref.get("value"), str):
            value = ref["value"].strip().casefold()
            if "@" in value:
                yield value


# -- the folder and the line -----------------------------------------------------------------------------


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
    return {
        "schema": SCHEMA,
        "export_id": export_id,
        "as_of": req.as_of,
        "read_head": head,
        "policy": {"name": DESTINATION, "version": req.version},
        "signed_only": req.signed_only,
        "window": {"since": req.since, "until": req.until},
        "tiers": list(req.tiers),
        "counts": built.counts(),
        "left_out": dict(built.left_out),
        "held_back": dict(built.held_back),
        "tool": {"name": "openlogbook", "version": __version__},
    }


def check_target(lb: Logbook, out: Path, force: bool = False) -> None:
    """Refuse OUT before anything is read or written: a file, a folder that holds anything and no
    earlier export of this command (unless `force`), the record or a folder in it outside `export/`."""
    try:
        crossing.check_target(out, force, lb.root, SCHEMAS)
    except crossing.CrossingError as e:
        raise NotionError(str(e)) from e


def export(
    lb: Logbook, req: Request, out: Path, force: bool = False, airports: Airports | None = None
) -> tuple[Built, Result]:
    """Read, write the folder fresh, append the crossing line: under one hold of the writer lock, so
    the head the facts were read at is the head the line follows. A crash between the folder and the
    line leaves a folder no line names, which the next run replaces."""
    check_target(lb, out, force)
    with lb.writer("export notion"):
        read = lb.meta
        head = str(read["head"])
        built = build(lb, req, airports)
        export_id = uuid7()
        manifest = manifest_of(req, built, export_id, head)
        files = {
            PERSONS_FILE: _json({"persons": built.persons}),
            IDEAS_FILE: _json({"ideas": built.ideas}),
            ORGS_FILE: _json({"orgs": built.orgs}),
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
            raise NotionError(str(e)) from e
        package_sha256 = hashlib.sha256(raw).hexdigest()
        line = record(lb, req, built, export_id, head, package_sha256)
    return built, Result(Path(out), manifest, package_sha256, line)


def record(lb: Logbook, req: Request, built: Built, export_id: str, head: str, package_sha256: str) -> Line:
    """The one `crossing/v1` line (RFC 0011, ADR 0016 rule 4): the destination, the window from the
    start of the first day to the read time, the tiers, the counts, the entry in force and the digest
    of the manifest. The only write to the log this command makes."""
    start = day_start.of(lb.meta).span(req.since)[0]
    return lb.append(
        at=req.as_of,
        source=crossing.SOURCE,
        kind=crossing.KIND,
        tier=1,
        payload={
            "schema": crossing.LINE_SCHEMA,
            "destination": DESTINATION,
            "bundle_id": export_id,
            "window": {"from": stamp(start), "to": req.as_of},
            "tiers": list(req.tiers),
            "counts": built.lines,
            "policy": {
                "file": policy.POLICY_FILE.as_posix(),
                "max_tier": req.entry.max_tier,
                "signed_only": req.signed_only,
                "version": req.version,
            },
            "logbook_head": head,
            "package_sha256": package_sha256,
            "extra": {
                "notion": {
                    "schema": SCHEMA,
                    "counts": built.counts(),
                    "window": {"since": req.since, "until": req.until},
                    "left_out": dict(built.left_out),
                    "held_back": dict(built.held_back),
                }
            },
        },
        recorded_at=req.as_of,
    )


# -- the console -----------------------------------------------------------------------------------------


def rows(req: Request, built: Built) -> Iterator[str]:
    """What a run hands over and what it left out, for the dry run and the real one alike."""
    c = built.counts()
    ideas, orgs = (_plural(c["entries"][k], "entry", "entries") for k in ("ideas", "orgs"))
    yield f"  persons: {c['persons']}   ideas: {c['ideas']} ({ideas})   orgs: {c['orgs']} ({orgs})"
    left = built.left_out
    missing = [
        _plural(left["persons_without_identity"], "person") + " without an email, phone or handle",
        _plural(left["ideas_without_page"], "idea") + " without a Notion page",
        _plural(left["orgs_without_domain"], "org") + " without a domain",
        _plural(left["sentences_with_money"], "sentence") + " naming money",
    ]
    yield "  left out: " + "; ".join(missing)
    sizes = built.sections()
    yield (
        f"  pages: days together: {_plural(sizes['together'], 'line')}"
        f" on {_plural(sizes['together_pages'], 'page')};"
        f" promises: {_plural(sizes['promise_lines'], 'line')} ({sizes['listed']} listed,"
        f" {sizes['more']} more not listed)"
    )
    held = built.held_back
    gate_word = "unsigned days" if req.signed_only else "unsigned days (the gate is lifted)"
    yield (
        f"  held back: {_plural(held['above_tier'], 'line')} above tier {max(req.tiers)},"
        f" {_plural(held['unsigned'], 'line')} on {gate_word}"
    )
    if req.signed_only and held["unsigned"]:
        yield (
            "  (`logbook day sign YYYY-MM-DD` signs a day; the entry's include_unsigned and"
            " --include-unsigned lift the gate)"
        )
    if max(req.tiers) < 2:
        yield "  the entry's max_tier is 1: names, addresses, ideas and orgs are tier 2 and stay home"


def _plural(n: int, noun: str, plural: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (plural or noun + 's')}"


def describe(req: Request) -> str:
    gate_text = "signed days only" if req.signed_only else "signed and unsigned days"
    tiers = ",".join(map(str, req.tiers))
    return f"{DESTINATION}, {req.since} {EN_DASH} {req.until}, tiers {tiers}, {gate_text}"
