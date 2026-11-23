"""Held back (RFC 0045, all except junk; RFC 0043 §5, Keep and sign): what a day's mail the owner's own
junk rules hold back, shown at the close of the Day page beside Keep and sign, and the senders the owner
keeps from it.

**The reading** (`read`). For every destination whose entry in `policy/crossing.json` has a `mail_junk`
rule, in the file's order: the day's mail that rule holds back as junk (`peoples_mail.Rule.junk`: by
category or by label), and only when the day held some. A mail held because its sender was let go in
Hold is not offered: the owner decided that sender already (`logbook hold sender … --keep` reverses it).
Two groups, never a person's name in either:

- **first-time senders** (`peoples_mail.Rule.first_times`: an address that never wrote before, no
  no-reply address, no list, never the owner): each mail as its sender's address and its subject;
- **the other senders**, one row each, by address, or by domain when two or more addresses of one
  domain were held: how many mails. A person of the record is never held by a junk rule, so no row is a
  person's; a sender is shown by its address or its domain, never by a resolved name.

The destination is a heading, with no number beside it. Everything is read through the page's gate
(`tiers`, `reading.crossing`): the day's mail, the resolutions the rule asks, the earlier mail that decides
a first time, and an org's portfolio only where the gate reads tier 3. Nothing is fetched and nothing is
written. A policy file that cannot be read (`policy/crossing.json`, `policy/owner.json`) fails closed: the
reading carries the sentence that says why and offers nothing.

**The keep** (`checked`, `write`). A sender ticked is kept: one `keep` fate (`sender_fates.write`), so
that day's mail from them crosses with the day's bundle under all except junk, and their later mail too.
`checked` refuses, before anything is written, a sender the day did not hold back and one kept already;
`write` writes each fate under the writer lock the caller holds, in the order asked, at the moment Keep
and sign writes its notes (`keep.moment`)."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, cast

from ..core import day_start, peoples_mail, policy, reading, sender_fates
from ..core.chain import Line, is_sealed
from ..core.index import Index
from ..core.resolve import Ref
from ..core.store import Logbook, retractions

TIER3 = 3


class HeldError(ValueError):
    """A sender asked to be kept that the record refuses; one sentence, nothing written."""


@dataclass(frozen=True)
class FirstTime:
    id: str
    sender: str
    subject: str


@dataclass(frozen=True)
class Sender:
    ref: Ref  # ("email", address) or ("domain", host)
    mails: int


@dataclass(frozen=True)
class Held:
    destination: str
    first: tuple[FirstTime, ...] = ()
    others: tuple[Sender, ...] = ()
    problem: str | None = None  # this destination's rule cannot be read: nothing offered

    @property
    def any(self) -> bool:
        return bool(self.first or self.others or self.problem)


@dataclass(frozen=True)
class Reading:
    day: str
    held: tuple[Held, ...] = ()
    problem: str | None = None  # a policy file that cannot be read: the whole section fails closed

    @property
    def offered(self) -> frozenset[Ref]:
        """The senders a keep tick may name: every first-time sender by address, every other row."""
        found: set[Ref] = set()
        for h in self.held:
            found.update((sender_fates.EMAIL, f.sender) for f in h.first)
            found.update(s.ref for s in h.others)
        return frozenset(found)

    @property
    def digest(self) -> str:
        """What the page offered, as one string the form carries back: a form whose senders are no
        longer those the day holds back is stale."""
        text = "\n".join(f"{kind}:{value}" for kind, value in sorted(self.offered))
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] if text else ""

    @property
    def shown(self) -> bool:
        return self.problem is not None or any(h.any for h in self.held)


class _Gated:
    """The three reads `Rule.first_times` makes of an index, through the gate `tiers`."""

    def __init__(self, idx: Index, tiers: Sequence[int] | None):
        self.idx, self.tiers = idx, tiers

    def retractions(self) -> list[Line]:
        return self.idx.retractions()

    def superseded(self, kind: str) -> Any:
        return self.idx.superseded(kind)

    def of_kind(self, kind: str, first: str | None, last: str | None) -> list[Line]:
        return list(reading.crossing(self.idx.of_kind(kind, first, last), self.tiers))


def read(lb: Logbook, day: str, tiers: Sequence[int] | None = None) -> Reading:
    """The day's mail held back, per destination with a `mail_junk` rule, through the gate `tiers` (None:
    every tier, the command's); an empty reading when no destination has a rule or the day held nothing."""
    try:
        destinations = peoples_mail.junk_destinations(lb.root)
    except policy.PolicyError as e:
        return Reading(day, problem=f"the mail held back cannot be read: {e}")
    if not destinations:
        return Reading(day)
    rules: dict[str, peoples_mail.Junk] = {}
    unread: dict[str, str] = {}
    for destination in destinations:
        try:
            rule = peoples_mail.junk_of(lb.root, destination)
        except policy.PolicyError as e:
            unread[destination] = f"its mail_junk rule cannot be read, so nothing is offered: {e}"
            continue
        if rule is not None:
            rules[destination] = rule
    portfolio: frozenset[Ref] = frozenset()
    if tiers is None or TIER3 in {int(t) for t in tiers}:
        from . import orgs  # an org's portfolio is tier 3: read only where the gate reads it

        portfolio = orgs.portfolio_refs(lb)
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        marks = idx.retractions()
        fates = peoples_mail.fates(lb, idx, marks)
        try:
            judge = peoples_mail.Rule.of(
                lb,
                marks,
                reading.crossing(idx.resolutions(), tiers),
                let_go=fates.let_go,
                kept=fates.kept,
                portfolio=portfolio,
            )
        except policy.PolicyError as e:  # policy/owner.json: who the owner is decides who is a person
            return Reading(day, problem=f"the mail held back cannot be read: {e}")
        retracted = frozenset(retractions(marks))
        mails = [
            line
            for line in reading.crossing(
                (
                    line
                    for line, _day in peoples_mail._standing(
                        idx, peoples_mail.KIND, day, day, retracted, days
                    )
                ),
                tiers,
            )
            if not is_sealed(line)
        ]
        first = judge.first_times(cast(Index, _Gated(idx, tiers)), mails, day) if rules else frozenset()
        verdicts = {name: judge.verdicts(idx, mails, rule, first) for name, rule in rules.items()}
    by_id = {str(line["id"]): line for line in mails}
    held = []
    for destination in destinations:
        if destination in unread:
            held.append(Held(destination, problem=unread[destination]))
        elif destination in verdicts:
            held.append(_grouped(destination, verdicts[destination], by_id))
    return Reading(day, tuple(h for h in held if h.any))


def _grouped(destination: str, verdicts: Iterable[peoples_mail.Verdict], by_id: dict[str, Line]) -> Held:
    junk = [v for v in verdicts if v.reason in (peoples_mail.JUNK_CATEGORY, peoples_mail.JUNK_LABEL)]
    senders = {v.id: _sender(by_id[v.id]) for v in junk}
    new = {senders[v.id] for v in junk if v.first_time and senders[v.id] is not None}
    first = tuple(
        FirstTime(v.id, str(senders[v.id]), _subject(by_id[v.id])) for v in junk if senders[v.id] in new
    )
    rest = [senders[v.id] for v in junk if senders[v.id] not in new and senders[v.id] is not None]
    hosts: dict[str, set[str]] = {}
    for address in rest:
        hosts.setdefault(_host(str(address)), set()).add(str(address))
    counts: dict[Ref, int] = {}
    for address in rest:
        host = _host(str(address))
        ref: Ref = (sender_fates.DOMAIN, host) if len(hosts[host]) > 1 else (sender_fates.EMAIL, str(address))
        counts[ref] = counts.get(ref, 0) + 1
    others = tuple(Sender(ref, n) for ref, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])))
    return Held(destination, first, others)


def _sender(line: Line) -> str | None:
    payload = line.get("payload")
    value = payload.get("from") if isinstance(payload, dict) else None
    email = value.get("email") if isinstance(value, dict) else None
    if not isinstance(email, str) or not email.strip():
        return None
    try:
        kind, address = sender_fates.sender(email)
    except sender_fates.FateError:
        return None
    return address if kind == sender_fates.EMAIL else None


def _host(address: str) -> str:
    return address.rpartition("@")[2]


def _subject(line: Line) -> str:
    payload = line.get("payload")
    subject = payload.get("subject") if isinstance(payload, dict) else None
    return " ".join(subject.split()) if isinstance(subject, str) else ""


def refs(values: Iterable[str]) -> list[Ref]:
    """The senders a form or `--keep-sender` names, each an address or a domain, folded, once each in
    the order given (`sender_fates.sender`); `HeldError` for one that is neither."""
    found: list[Ref] = []
    for value in values:
        value = value.strip()
        if not value:
            continue
        kind, _, rest = value.partition(":")
        text = rest if kind in (sender_fates.EMAIL, sender_fates.DOMAIN) and rest else value
        try:
            ref = sender_fates.sender(text)
        except sender_fates.FateError as e:
            raise HeldError(str(e)) from e
        if ref not in found:
            found.append(ref)
    return found


def checked(lb: Logbook, day: str, asked: Sequence[Ref], tiers: Sequence[int] | None = None) -> list[Ref]:
    """`asked`, every one a sender the day held back (`read`, through `tiers`) and none kept already;
    `HeldError` names the first that is not, before anything is written."""
    if not asked:
        return []
    found = read(lb, day, tiers)
    if found.problem is not None:
        raise HeldError(f"{found.problem}; nothing was written")
    offered = found.offered
    standing = sender_fates.read(lb).standing
    for ref in asked:
        if ref not in offered:
            raise HeldError(f"{ref[1]} held nothing back on {day}; nothing was written")
        fate = standing.get(ref)
        if fate is not None and fate.fate == sender_fates.KEEP:
            raise HeldError(f"{ref[1]} is kept already; nothing was written")
    return list(asked)


def write(lb: Logbook, kept: Sequence[Ref], at: str) -> list[Line]:
    """One `keep` fate per sender, in order, at `at` (UTC), under the writer lock (re-entered)."""
    with lb.writer():
        return [sender_fates.write(lb, ref[1], sender_fates.KEEP, None, at=at).line for ref in kept]


def to_json(found: Reading) -> dict[str, Any]:
    return {
        "day": found.day,
        "problem": found.problem,
        "held": [
            {
                "destination": h.destination,
                "problem": h.problem,
                "first_time": [{"id": f.id, "sender": f.sender, "subject": f.subject} for f in h.first],
                "senders": [{"kind": s.ref[0], "value": s.ref[1], "mails": s.mails} for s in h.others],
            }
            for h in found.held
        ],
    }


def wrote_text(line: Line) -> str:
    """What the command says of a fate it wrote: the sender kept, never a count beside it."""
    return f"kept {line['payload']['label']}: its mail crosses from now on, as #{line['seq']} status/v1"
