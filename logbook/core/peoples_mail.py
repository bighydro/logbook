"""People's mail (RFC 0045): the one rule for which mail is a person's, read by the Day page and the
crossing alike — `logbook people mail`, and the mail filter of `export crossing` — and by `promises`,
which reads a request in a mail only when it is a person's mail.

A mail line (`mail/v1`, RFC 0015) is **a person's mail** when someone the record names as a person is
on it: the sender (`from`) of a mail received, any recipient (`to`, `cc`, `bcc`) of a mail sent; and its
sender has not been let go in Hold. "Names as a person" is the readers' sense (`present`): an address
with a standing resolution (RFC 0006) to an entity whose type is `person` or none, never the owner.
What is not a person, and the reason a mail is other mail, in the order the reader asks:

- `agent`: the machine mark (`logbook.core.machine`), `extra.machine` or an agent `extra.counterpart`,
  or a sender resolved to an entity of type `agent`; no mail writer sets either mark today;
- `no_reply`: a received mail whose sender matches `NO_REPLY_ADDRESS`, whatever a resolution says;
- `let_go`: a sender, by address or domain, in `Rule.let_go`, the senders Hold let go (RFC 0042 §4).
  Hold writes no fate yet, so the set is empty and removes nothing;
- `no_person`: nobody the record names as a person where the rule looks (a company, a stranger, a
  person in cc of a mail received);
- `sealed`: a sealed mail this machine cannot open (`Logbook.opened`): never guessed to be anyone's.

`extra.gmail_category` and `extra.list`, when a line carries them, are shown as evidence, never a
rule of the reader's.

**All except junk** (RFC 0045, amendment of 20 November 2026) is a crossing's third mail mode: every mail
crosses but a received one the owner's own rule calls junk, the `mail_junk` entry of one destination in
`policy/crossing.json` (`Junk`). Here the category and the labels are part of a rule the owner wrote for one
crossing, never a rule of the reader's. `Rule.junk` says why one mail stays home (`let_go`, `junk_category`,
`junk_label`) or None; a person of the record (§1), a label of `never_labels`, an invitation platform
(`INVITATION_SENDERS`), a sender bound to an org in a portfolio (`Rule.portfolio`, given by the caller: core
reads no org) and a sender Hold keeps (`Rule.kept`, empty until Hold writes fates) spare a mail; a sender let
go is held whatever spares it. `Rule.first_times` says which received mails are a first-time sender's.
`replies_owed` reads people's mail, direct messages and calls for the replies a day owes (RFC 0043 §4.5).
Everything is read through the index and nothing is written; no address leaves this module but inside the
lines themselves."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import day_start, machine, policy, present, reading, resolve, stays
from .chain import Line, is_sealed
from .export import parse_day
from .index import Index
from .people import PHONE, WHATSAPP_DIRECT
from .resolve import Identity, Ref
from .store import Logbook, retractions

KIND = "mail"
RECEIVED, SENT = "received", "sent"
PERSON, OTHER = "person", "other"
AGENT, NO_REPLY, LET_GO, NO_PERSON = "agent", "no_reply", "let_go", "no_person"
SEALED = "sealed"  # a sealed line this machine has no key to open: listed, and said, never guessed
REASONS = (NO_PERSON, NO_REPLY, AGENT, LET_GO, SEALED)  # the order the counts list them in
RECIPIENTS = ("to", "cc", "bcc")
# RFC 0045, all except junk: an invitation platform's mail is never junk, whatever the owner's rule says; a
# domain here, or any domain under one (`mail.evite.com`). A change to the list is a change to the RFC.
INVITATION_SENDERS = (
    "paperlesspost.com",
    "evite.com",
    "partiful.com",
    "lu.ma",
    "eventbrite.com",
    "greenvelope.com",
    "punchbowl.com",
    "zola.com",
    "withjoy.com",
)
JUNK_KEY = "mail_junk"  # a destination's entry in policy/crossing.json: the owner's rule for junk mail
JUNK_FIELDS = ("categories", "labels", "never_labels")
JUNK_CATEGORY, JUNK_LABEL = "junk_category", "junk_label"
HELD_REASONS = (LET_GO, JUNK_CATEGORY, JUNK_LABEL)  # why a mail stays home under all except junk, in order
# RFC 0045 §2: a no-reply address is never a person. `present.SYSTEM_ADDRESS` (the calendar's own,
# `no-reply`, `reservations`, `invite`) and the bulk senders' local parts, each alone or followed by `+`,
# `-` or `.` and more
NO_REPLY_ADDRESS = re.compile(r"^(do-?not-?reply|mailer-daemon|postmaster|bounces?|notifications?)(@|[.+-])")
CATEGORY = re.compile(r"[a-z_]{1,24}")  # Gmail's tab as a word (#341), never anything longer
DEFAULT_DAYS = 30  # `people mail` without --since: the 30 days ending --until
WEEK = 7  # a reply is owed once the last word is older than this many days (RFC 0045 §5)
LOOKBACK = 90  # replies_owed reads the 90 days ending the day


def no_reply(address: str) -> bool:
    """Whether an address is a no-reply one (RFC 0045 §2, item 2)."""
    folded = address.strip().casefold()
    return bool(present.SYSTEM_ADDRESS.search(folded) or NO_REPLY_ADDRESS.search(folded))


def _domain(address: str) -> str:
    return address.strip().rpartition("@")[2].casefold().strip(". ")


def _and_above(domain: str) -> list[str]:
    """A domain and every domain it is under, down to two labels: `a.b.example.org`, `b.example.org`,
    `example.org`."""
    labels = domain.split(".")
    return [".".join(labels[i:]) for i in range(max(len(labels) - 1, 1))]


def invitation(address: str) -> bool:
    """Whether an address is an invitation platform's (`INVITATION_SENDERS`): its domain is one of the
    list's, or under one."""
    return any(d in INVITATION_SENDERS for d in _and_above(_domain(address)))


@dataclass(frozen=True)
class Junk:
    """The owner's rule for junk mail, one destination's `mail_junk` entry: the Gmail categories and the
    labels that call a received mail junk, and the labels that say it is worth a look whatever else
    (`never_labels`). Each is compared case aside. The label names are the owner's mailbox's; Logbook
    names none of them."""

    categories: frozenset[str] = frozenset()
    labels: frozenset[str] = frozenset()
    never_labels: frozenset[str] = frozenset()

    @classmethod
    def of(cls, value: object, where: str) -> Junk:
        """The entry as written: `{"categories": [...], "labels": [...], "never_labels": [...]}`, each
        key optional, each a list of words; anything else is refused naming `where`
        (`policy.PolicyError`), so a misspelt key never quietly lets more or less cross."""
        if not isinstance(value, dict):
            shape = '{"categories": [...], "labels": [...], "never_labels": [...]}'
            raise policy.PolicyError(f'{where}: "{JUNK_KEY}" must be {shape}')
        unknown = sorted(set(value) - set(JUNK_FIELDS))
        if unknown:
            raise policy.PolicyError(
                f'{where}: "{JUNK_KEY}" has a key {unknown[0]!r} it does not know; its keys are'
                f" {', '.join(JUNK_FIELDS)}"
            )
        found: dict[str, frozenset[str]] = {}
        for key in JUNK_FIELDS:
            words = value.get(key, [])
            if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
                raise policy.PolicyError(f'{where}: "{JUNK_KEY}" has a {key} that is not a list of names')
            found[key] = frozenset(_fold(w) for w in words)
        return cls(found["categories"], found["labels"], found["never_labels"])

    def signal(self, payload: Mapping[str, Any]) -> str | None:
        """Why the rule calls a mail junk, before any exception: its category is one of `categories`
        (`junk_category`), else one of its labels is one of `labels` (`junk_label`); None for neither,
        and for a mail with no category and no label."""
        extra = payload.get("extra")
        category = extra.get("gmail_category") if isinstance(extra, dict) else None
        if isinstance(category, str) and _fold(category) in self.categories:
            return JUNK_CATEGORY
        return JUNK_LABEL if _labels(payload) & self.labels else None

    def spared(self, payload: Mapping[str, Any]) -> bool:
        """Whether one of the mail's labels is one of `never_labels`."""
        return bool(_labels(payload) & self.never_labels)


def _fold(word: str) -> str:
    return " ".join(word.split()).casefold()


def _labels(payload: Mapping[str, Any]) -> frozenset[str]:
    found = payload.get("labels")
    return (
        frozenset(_fold(w) for w in found if isinstance(w, str)) if isinstance(found, list) else frozenset()
    )


def junk_of(root: Path, destination: str) -> Junk | None:
    """The `mail_junk` rule of `destination`'s entry in `policy/crossing.json`, or None when the entry
    has none (or the file names no such destination); `policy.PolicyError` for one that is not a rule."""
    entry = policy.read(root).get(destination)
    if not isinstance(entry, dict) or JUNK_KEY not in entry:
        return None
    return Junk.of(entry[JUNK_KEY], f"{policy.policy_path(root)}: {destination!r}")


def junk_destinations(root: Path) -> list[str]:
    """The destinations whose entry in `policy/crossing.json` has a `mail_junk` rule, in the file's order."""
    return [d for d, entry in policy.read(root).items() if isinstance(entry, dict) and JUNK_KEY in entry]


@dataclass(frozen=True)
class Verdict:
    """One mail under the owner's junk rule: `reason` why it stays home (`HELD_REASONS`), None when it
    crosses, and whether it is a first-time sender's (`Rule.first_times`). Never an address."""

    id: str
    reason: str | None
    first_time: bool

    @property
    def held(self) -> bool:
        return self.reason is not None

    def to_json(self) -> dict[str, Any]:
        return {"id": self.id, "held": self.held, "reason": self.reason, "first_time": self.first_time}


def held_counts(verdicts: Iterable[Verdict]) -> dict[str, Any]:
    """How many mails the rule holds back, by reason, and how many of those are a first-time sender's:
    counts only."""
    held = [v for v in verdicts if v.held]
    return {
        "held": len(held),
        "by_reason": {r: sum(1 for v in held if v.reason == r) for r in HELD_REASONS},
        "first_time": sum(1 for v in held if v.first_time),
    }


@dataclass(frozen=True)
class Classed:
    """One mail line, classed: a person's mail (`people` the ids that make it so) or other mail
    (`reason`); `evidence` the MAY keys of #341 when the line carries them, never an address."""

    id: str
    at: str
    day: str
    direction: str
    people: tuple[str, ...]
    reason: str | None
    evidence: Mapping[str, Any] = field(default_factory=dict)

    @property
    def person(self) -> bool:
        return self.reason is None

    @property
    def cls(self) -> str:
        return PERSON if self.person else OTHER

    def to_json(self) -> dict[str, Any]:
        found: dict[str, Any] = {"id": self.id, "at": self.at, "day": self.day, "direction": self.direction}
        found["class"] = self.cls
        if self.person:
            found["people"] = list(self.people)
        else:
            found["reason"] = self.reason
        if self.evidence:
            found["evidence"] = dict(self.evidence)
        return found


@dataclass(frozen=True)
class Rule:
    """The rule over one record's resolutions: who is a person, who is the owner, and who Hold let go
    (`let_go`, `email` or `domain` refs; empty until Hold writes fates, RFC 0045 §4). For the junk rule
    (`junk`): the senders Hold keeps (`kept`, the same refs; empty until Hold writes fates), and the refs
    bound to an org in a portfolio (`portfolio`, `email` or `domain`; the caller reads them, core reads
    no org, and a caller that gives none holds such a mail back rather than send it)."""

    identities: Mapping[Ref, Identity]
    owner: present.Owner
    let_go: frozenset[Ref] = frozenset()
    kept: frozenset[Ref] = frozenset()
    portfolio: frozenset[Ref] = frozenset()

    @classmethod
    def of(
        cls,
        lb: Logbook,
        marks: Iterable[Line],
        resolutions: Iterable[Line],
        let_go: frozenset[Ref] = frozenset(),
        kept: frozenset[Ref] = frozenset(),
        portfolio: frozenset[Ref] = frozenset(),
    ) -> Rule:
        """From the retraction and resolution lines (opened), `logbook.json` and `policy/owner.json`
        (`policy.PolicyError` when that file is not what it should be)."""
        identities = resolve.identities_from([*marks, *resolutions])
        owner = present.owner_of(
            str(lb.meta.get("owner_id") or ""),
            [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
            policy.owner_aliases(lb.root),
            identities,
        )
        return cls(identities, owner, let_go, kept, portfolio)

    def identity(self, ref: Ref) -> Identity | None:
        """What a ref resolves to; an address both ways the record spells one (`crossing._named`)."""
        if ref[0] != "email":
            return self.identities.get(ref)
        value = ref[1].strip()
        return self.identities.get(("email", value.lower())) or self.identities.get(
            ("email", value.casefold())
        )

    def person(self, ref: Ref | None) -> str | None:
        """The person a ref names, never the owner; None for anyone else, a company or an agent."""
        who = None if ref is None else self.identity(ref)
        if who is None or not who.entity or who.type not in present.PERSON_TYPES:
            return None
        return None if who.entity in self.owner.entities else who.entity

    def owners(self, address: str) -> bool:
        if ("email", " ".join(address.split()).casefold()) in self.owner.refs:
            return True
        who = self.identity(("email", address))
        return who is not None and who.entity in self.owner.entities

    def direction(self, payload: Mapping[str, Any], sender: str | None) -> str:
        """`direction` as the line says it, else sent when its `from` is the owner's (RFC 0045 §1)."""
        direction = payload.get("direction")
        if direction in (RECEIVED, SENT):
            return str(direction)
        return SENT if sender is not None and self.owners(sender) else RECEIVED

    def classify(self, line: Line, day: str = "") -> Classed:
        payload = line.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        sender = _address(payload.get("from"))
        direction = self.direction(payload, sender)
        people: tuple[str, ...] = ()
        if is_sealed(line):
            reason: str | None = SEALED
        elif machine.is_machine(payload) or machine.with_agent(payload):
            reason = AGENT
        elif direction == RECEIVED:
            reason, people = self._received(sender)
        else:
            found = [self.person(("email", a)) for a in _recipients(payload) if not no_reply(a)]
            people = tuple(dict.fromkeys(p for p in found if p is not None))
            reason = None if people else NO_PERSON
        return Classed(
            str(line.get("id")), str(line.get("at")), day, str(direction), people, reason, _evidence(payload)
        )

    def _received(self, sender: str | None) -> tuple[str | None, tuple[str, ...]]:
        if sender is None:
            return NO_PERSON, ()
        if no_reply(sender):
            return NO_REPLY, ()
        if self._among(sender, self.let_go):
            return LET_GO, ()
        who = self.identity(("email", sender))
        if who is not None and who.type == machine.AGENT:
            return AGENT, ()
        person = self.person(("email", sender))
        return (None, (person,)) if person is not None else (NO_PERSON, ())

    @staticmethod
    def _among(sender: str, refs: frozenset[Ref], above: bool = False) -> bool:
        """Whether `refs` hold the sender's address (either spelling) or its domain (`above`: or any
        domain it is under)."""
        domain = _domain(sender)
        domains = _and_above(domain) if above else [domain]
        found = {("email", sender.lower()), ("email", sender.casefold()), *(("domain", d) for d in domains)}
        return bool(refs & found)

    def junk(self, line: Line, rule: Junk) -> str | None:
        """Why a mail stays home under the owner's junk rule (`HELD_REASONS`), or None when it crosses.
        A sent mail always crosses. A received one whose sender Hold let go is held, whatever else
        (`let_go`). Otherwise it is held only when the rule calls it junk (`Junk.signal`: its category,
        else a label) and nothing spares it: its sender a person of the record (§1: the sender alone,
        never the owner, never a no-reply address), one of its labels in `never_labels`, its sender an
        invitation platform (`invitation`), bound to an org in a portfolio (`portfolio`, the domain or
        any domain it is under) or kept by Hold (`kept`). A mail of no other kind is never held."""
        if line.get("kind") != KIND:
            return None
        payload = line.get("payload")
        payload = payload if isinstance(payload, dict) else {}
        sender = _address(payload.get("from"))
        if self.direction(payload, sender) != RECEIVED:
            return None
        if sender is not None and self._among(sender, self.let_go):
            return LET_GO
        signal = rule.signal(payload)
        if signal is None or rule.spared(payload):
            return None
        if sender is None:
            return signal
        if (
            self._received(sender)[0] is None
            or invitation(sender)
            or self._among(sender, self.portfolio, above=True)
            or self._among(sender, self.kept)
        ):
            return None
        return signal

    def first_times(self, idx: Index, lines: Iterable[Line], last_day: str | None = None) -> frozenset[str]:
        """The ids of the received mails among `lines` that may be a new person writing: the sender is
        not a no-reply address nor the owner's, the mail carries no list mark (`extra.list`), and no
        standing mail line of the record from that address is earlier (by its `at`, then its seq).
        Reads every mail line the index serves up to `last_day` (a local day no line of `lines` is
        after; None: every one), once (a gated index serves its gate's); writes nothing."""
        wanted: dict[str, list[tuple[datetime, int, str]]] = {}
        for line in lines:
            payload = line.get("payload")
            payload = payload if isinstance(payload, dict) else {}
            sender = _address(payload.get("from"))
            extra = payload.get("extra")
            listed = isinstance(extra, dict) and bool(extra.get("list"))
            at = stays.instant(line.get("at"))
            if (
                line.get("kind") != KIND
                or sender is None
                or at is None
                or listed
                or no_reply(sender)
                or self.owners(sender)
                or self.direction(payload, sender) != RECEIVED
            ):
                continue
            wanted.setdefault(sender.casefold(), []).append((at, int(line.get("seq") or 0), str(line["id"])))
        if not wanted:
            return frozenset()
        retracted = frozenset(retractions(idx.retractions()))
        superseded = idx.superseded(KIND)
        earliest: dict[str, tuple[datetime, int]] = {}
        for line in idx.of_kind(KIND, None, last_day):
            id_ = str(line.get("id"))
            payload = line.get("payload")
            sender = _address(payload.get("from")) if isinstance(payload, dict) else None
            at = stays.instant(line.get("at"))
            if sender is None or at is None or id_ in retracted or id_ in superseded:
                continue
            key = sender.casefold()
            if key in wanted:
                when = (at, int(line.get("seq") or 0))
                if key not in earliest or when < earliest[key]:
                    earliest[key] = when
        return frozenset(
            id_
            for key, found in wanted.items()
            for at, seq, id_ in found
            if key not in earliest or (at, seq) <= earliest[key]
        )

    def verdicts(
        self, idx: Index, lines: Iterable[Line], rule: Junk, first: frozenset[str] | None = None
    ) -> list[Verdict]:
        """Each mail among `lines` under the owner's junk rule (`junk`), with its first-time flag
        (`first`, else `first_times` of them), in the order given."""
        mails = [line for line in lines if line.get("kind") == KIND]
        first = self.first_times(idx, mails) if first is None else first
        return [Verdict(str(m["id"]), self.junk(m, rule), str(m["id"]) in first) for m in mails]


def _address(value: object) -> str | None:
    email = value.get("email") if isinstance(value, dict) else None
    return email.strip() if isinstance(email, str) and email.strip() else None


def _recipients(payload: Mapping[str, Any]) -> Iterator[str]:
    for header in RECIPIENTS:
        value = payload.get(header)
        for who in value if isinstance(value, list) else [value]:
            address = _address(who)
            if address is not None:
                yield address


def _evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    """`extra.gmail_category` as its word and `extra.list` as `true` (RFC 0045 §3): never the
    headers' values, which hold addresses and links."""
    extra = payload.get("extra")
    if not isinstance(extra, dict):
        return {}
    found: dict[str, Any] = {}
    category = extra.get("gmail_category")
    if isinstance(category, str) and CATEGORY.fullmatch(category):
        found["gmail_category"] = category
    if extra.get("list"):
        found["list"] = True
    return found


# -- the window ---------------------------------------------------------------------------------------------


@dataclass
class Report:
    first: str
    last: str
    mails: list[Classed]

    def counts(self) -> dict[str, Any]:
        mine = [c for c in self.mails if c.person]
        by_reason = {r: sum(1 for c in self.mails if c.reason == r) for r in REASONS}
        return {
            "mail": len(self.mails),
            "person": len(mine),
            "received": sum(1 for c in mine if c.direction == RECEIVED),
            "sent": sum(1 for c in mine if c.direction == SENT),
            "people": len({p for c in mine for p in c.people}),
            "other": len(self.mails) - len(mine),
            "by_reason": by_reason,
        }

    def to_json(self) -> dict[str, Any]:
        return {
            "window": {"first": self.first, "last": self.last},
            "counts": self.counts(),
            "let_go": "none yet: Hold writes no fates",
            "mails": [c.to_json() for c in self.mails],
        }


def read(lb: Logbook, first: str, last: str) -> Report:
    """Every mail line of the local days `[first, last]` that stands, in file order, classed; the
    resolutions read once, the window's mail through the (kind, day_local) index."""
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        marks = idx.retractions()
        rule = Rule.of(lb, marks, idx.resolutions())
        retracted = frozenset(retractions(marks))
        mails = [rule.classify(line, day) for line, day in _standing(idx, KIND, first, last, retracted, days)]
    return Report(first, last, mails)


def day_verdicts(
    lb: Logbook,
    day: str,
    rules: Mapping[str, Junk],
    kept: frozenset[Ref] = frozenset(),
    portfolio: frozenset[Ref] = frozenset(),
) -> dict[str, list[Verdict]]:
    """Destination → every mail line of the local `day` that stands, under that destination's junk
    rule (`Rule.junk`), each with its first-time flag (read once, for every rule); read through
    `lb.index()`, so a gated record (the door's) judges only the lines its gate shows. `kept` and
    `portfolio` as `Rule` takes them."""
    if not rules:
        return {}
    days = day_start.of(lb.meta)
    with lb.index() as idx:
        marks = idx.retractions()
        judge = Rule.of(lb, marks, idx.resolutions(), kept=kept, portfolio=portfolio)
        retracted = frozenset(retractions(marks))
        mails = [line for line, _day in _standing(idx, KIND, day, day, retracted, days)]
        first = judge.first_times(idx, mails, day)
        return {name: judge.verdicts(idx, mails, rule, first) for name, rule in rules.items()}


def window(today: date, since: str | None, until: str | None) -> tuple[str, str]:
    """`--since`/`--until` as local days (ValueError for one that is not a day): by default the
    `DEFAULT_DAYS` days ending `until`, itself today by default."""
    last = parse_day(until) if until else today
    first = parse_day(since) if since else last - timedelta(days=DEFAULT_DAYS - 1)
    if last < first:
        raise ValueError(f"the window runs backwards: --since {first} --until {last}")
    return first.isoformat(), last.isoformat()


def _standing(
    idx: Index, kind: str, first: str, last: str, retracted: frozenset[str], days: day_start.DayStart
) -> Iterator[tuple[Line, str]]:
    """The lines of `kind` on the local days `[first, last]`, not retracted, not superseded, each
    with its day; a line whose `at` does not read is passed over (SPEC §5)."""
    superseded = idx.superseded(kind)
    for line in idx.of_kind(kind, first, last):
        id_ = str(line.get("id"))
        at = stays.instant(line.get("at"))
        if id_ in retracted or id_ in superseded or at is None:
            continue
        day = days.day(at).isoformat()
        if first <= day <= last:
            yield line, day


# -- replies owed (RFC 0043 §4.5) ------------------------------------------------------------------------


@dataclass(frozen=True)
class Owed:
    """A reply the owner owes a person: their lines since the owner's last word, in time order."""

    person: str
    lines: tuple[str, ...]
    last_at: str


@dataclass(frozen=True)
class _Word:
    at: str
    id: str
    theirs: bool


def replies_owed(lb: Logbook, day: str, tiers: Sequence[int] | None = None) -> list[Owed]:
    """For each person the record names: over the `LOOKBACK` days ending `day`, their direct messages
    (never a group's, never an agent's), people's mail (`Rule`) and calls; when the latest word is
    theirs (a message from them, a mail they sent, a call from them not answered) and older than `WEEK`
    days before `day`, the reply is owed. A message, a mail or a call of the owner's, and a call the
    owner answered, is the owner's word. Longest owed first. Through the gate `tiers` (the Day page's,
    RFC 0043 §4.5): a line above it is no word, either way, and a person only a resolution above it
    names is nobody; None reads every tier."""
    end = parse_day(day)
    first = (end - timedelta(days=LOOKBACK - 1)).isoformat()
    days = day_start.of(lb.meta)
    words: dict[str, list[_Word]] = {}

    def gated(found: Iterable[tuple[Line, str]]) -> Iterator[tuple[Line, str]]:
        allowed = None if tiers is None else {int(t) for t in tiers}
        return (pair for pair in found if allowed is None or int(pair[0].get("tier") or 0) in allowed)

    with lb.index() as idx:
        marks = idx.retractions()
        rule = Rule.of(lb, marks, reading.crossing(idx.resolutions(), tiers))
        retracted = frozenset(retractions(marks))
        _messages(rule, gated(_standing(idx, "message", first, day, retracted, days)), words)
        for line, _day in gated(_standing(idx, KIND, first, day, retracted, days)):
            classed = rule.classify(line)
            for person in classed.people if classed.person else ():
                words.setdefault(person, []).append(
                    _Word(classed.at, classed.id, classed.direction == RECEIVED)
                )
        for line, _day in gated(_standing(idx, "call", first, day, retracted, days)):
            payload = line.get("payload") or {}
            caller = rule.person(_ref(payload.get("counterparty")))
            if caller is not None:
                theirs = payload.get("direction") == "incoming" and payload.get("answered") is not True
                words.setdefault(caller, []).append(_Word(str(line["at"]), str(line["id"]), theirs))
    owed: list[Owed] = []
    for person, said in words.items():
        said.sort(key=_when)
        if not said[-1].theirs:
            continue
        last_day = date.fromisoformat(days.day_of(said[-1].at))
        if (end - last_day).days <= WEEK:
            continue
        mine = [i for i, w in enumerate(said) if not w.theirs]
        since = mine[-1] + 1 if mine else 0
        owed.append(Owed(person, tuple(w.id for w in said[since:]), said[-1].at))
    return sorted(owed, key=lambda o: (_when(_Word(o.last_at, "", True)), o.person))


def _when(word: _Word) -> tuple[datetime, str]:
    """A word's place in time; every `at` here parsed already (`_standing`), the fallback is a type's."""
    return stays.instant(word.at) or datetime.min.replace(tzinfo=UTC), word.id


def _messages(rule: Rule, lines: Iterable[tuple[Line, str]], words: dict[str, list[_Word]]) -> None:
    """The direct chats' words, each chat given to the one person who wrote in it, or, when no line
    in it names who wrote it, to the person its id names (as `people` reads a chat)."""
    chats: dict[str, tuple[set[str | None], list[_Word]]] = {}
    for line, _day in lines:
        payload = line.get("payload") or {}
        if machine.is_machine(payload) or machine.with_agent(payload):
            continue
        chat = payload.get("chat")
        if isinstance(chat, str):  # SPEC §3.2: a string chat is a direct chat's name
            chat_id = chat
        elif isinstance(chat, dict) and chat.get("type") == "direct" and chat.get("id"):
            chat_id = str(chat["id"])
        else:
            continue
        senders, said = chats.setdefault(chat_id, (set(), []))
        theirs = payload.get("from_me") is not True
        if theirs:
            senders.add(rule.person(_ref(payload.get("sender"))))
        said.append(_Word(str(line.get("at")), str(line.get("id")), theirs))
    for chat_id, (senders, said) in chats.items():
        people = {p for p in senders if p is not None}
        person = next(iter(people)) if len(people) == 1 else None
        if person is None and not people:
            person = rule.person(_chat_ref(chat_id))
        if person is not None:
            words.setdefault(person, []).extend(said)


def _ref(value: object) -> Ref | None:
    if not isinstance(value, dict):
        return None
    kind, ref_value = value.get("kind"), value.get("value")
    return (kind, ref_value) if isinstance(kind, str) and isinstance(ref_value, str) and ref_value else None


def _chat_ref(chat_id: str) -> Ref | None:
    """The ref a direct chat's id names, as `people` reads it: a WhatsApp JID is a phone, an address
    or a number as such is itself."""
    jid = WHATSAPP_DIRECT.match(chat_id)
    if jid is not None:
        return ("phone", f"+{jid.group(1)}")
    if PHONE.match(chat_id):
        return ("phone", chat_id)
    if "@" in chat_id:
        return ("email", chat_id.strip().casefold())
    return None
