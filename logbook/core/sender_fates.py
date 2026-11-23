"""Hold's sender fates (RFC 0042 §4, RFC 0037 §10 as amended 20 November 2026, RFC 0045 §4): what the
owner decided about one sender of mail, an address or a domain: `keep` or `let-go`.

**The line.** One `status/v1` line of RFC 0037 §10, `source` `manual`, tier 2, on a Hold item of sort
`sender`: `entity` is `{type: "item", id: "sender:<email|domain>:<value>", registry: "logbook"}`, the
value folded (an address or a host in lower case, a host's trailing dot dropped), `label` the address
or the domain as written into the id, `status` `keep` or `let-go`, `proposed_by` `owner`. A `let-go`
carries its `reason`, as RFC 0037 asks of every `let-go`. A reason, when given, is first written as one
`note/v1` (RFC 0010: tier 2, label `status`, the entity under `extra.entity`, never the fate) and then
the status line, whose `note` names it (RFC 0037 §10.5), so the owner's words are on the day and in
`search`. The line names the standing fate it replaces in `supersedes`; nothing is ever deleted.

**The writer** (`write`, `logbook hold sender ADDRESS_OR_DOMAIN --keep | --let-go --reason TEXT`, and
the Day page's keep tick when it comes) reads the standing fates and appends under one hold of the
writer lock, the head read again before the first line; a fate equal to the standing one is refused,
so the record says each decision once.

**The reader** (`of`, `read`): per sender, the last fate line in chain order that is not retracted
(RFC 0003); a retracted line counts for nothing and the one before it stands again. `Fates.let_go` is
RFC 0045's `Rule.let_go`; `Fates.kept` is the senders the owner kept, the exception the crossing's
all-except-junk mode reads. A sender let go is let go whatever keeps it, as RFC 0045's all-except-junk
amendment has it: an address kept on a domain let go is still let go (`Fates.fate`); keep the domain,
or let the address alone go. A sealed line this machine cannot open is no fate. Fates are read at every
tier: they are the owner's word on what may cross, never what crosses."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import day_start, notes
from .chain import Line, is_sealed
from .resolve import Ref
from .store import RETRACTION, HeadMoved, Logbook, retractions

KIND, SCHEMA = "status", "status/v1"
ITEM, SORT, REGISTRY, SOURCE = "item", "sender", "logbook", "manual"
TIER = 2  # RFC 0042 §3: an item's lines are tier 2, as an idea's, a place's or an asset's status is
KEEP, LET_GO = "keep", "let-go"
FATES = (KEEP, LET_GO)
EMAIL, DOMAIN = "email", "domain"
NOTE_LABEL = "status"  # RFC 0037 §10.5: the one label of the note carrying a status's reason
OWNER = "owner"
HOST = re.compile(
    r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
LOCAL = re.compile(r"^[^\s@]{1,64}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID = re.compile(r"^sender:(email|domain):(\S+)$")
HEAD_MOVED = (
    "the record's head moved from seq {was} to seq {now} while the fates were read, so the line would"
    " rest on a record it did not read; nothing was written"
)


class FateError(ValueError):
    """A fate the record refuses; the message is one sentence and nothing is written."""


# -- the sender ---------------------------------------------------------------------------------------


def sender(text: str) -> Ref:
    """The sender `text` names, as a ref: `("email", address)` for an address, `("domain", host)` for a
    host, both folded; `FateError` for anything else."""
    value = " ".join(str(text).split()).casefold()
    if " " in value or not value:
        raise FateError(f"{text!r} is no sender: give an address (letters@news.example.org) or a domain")
    if "@" in value:
        local, _, host = value.rpartition("@")
        host = host.rstrip(".")
        if not LOCAL.match(local) or not HOST.match(host):
            raise FateError(f"{text!r} is no address: give one like letters@news.example.org")
        return EMAIL, f"{local}@{host}"
    host = value.rstrip(".")
    if not HOST.match(host):
        raise FateError(f"{text!r} is no domain: give one like news.example.org, or an address")
    return DOMAIN, host


def item_id(ref: Ref) -> str:
    return f"{SORT}:{ref[0]}:{ref[1]}"


def ref_of(entity_id: object) -> Ref | None:
    """The sender an item id names (`sender:email:…`, `sender:domain:…`), checked; None otherwise."""
    found = ID.match(entity_id) if isinstance(entity_id, str) else None
    if found is None:
        return None
    try:
        ref = sender(found.group(2))
    except FateError:
        return None
    return ref if ref == (found.group(1), found.group(2)) else None


def entity(ref: Ref) -> dict[str, str]:
    return {"type": ITEM, "id": item_id(ref), "registry": REGISTRY}


# -- the profile --------------------------------------------------------------------------------------


def payload(
    ref: Ref,
    fate: str,
    reason: str | None = None,
    note: str | None = None,
    supersedes: str | None = None,
    head: str | None = None,
) -> dict[str, Any]:
    """A sender's `status/v1` payload (RFC 0037 §10.2 with the type `item`, RFC 0042 §4)."""
    found: dict[str, Any] = {"schema": SCHEMA, "entity": entity(ref), "label": ref[1], "status": fate}
    if reason is not None:
        found["reason"] = reason
    if note is not None:
        found["note"] = note
    found["proposed_by"] = OWNER
    if supersedes is not None:
        found["supersedes"] = supersedes
    if head is not None:
        found["logbook_head"] = head
    return found


def problems(found: Mapping[str, Any]) -> list[str]:
    """Every way `found` is not a sender's `status/v1`, in words; empty when it is one. Read by
    `entities.validate_status` for every line whose entity is an `item`."""
    said: list[str] = []
    if found.get("schema") != SCHEMA:
        said.append(f"schema is {found.get('schema')!r}, not {SCHEMA!r}")
    item = found.get("entity")
    if not isinstance(item, dict) or item.get("type") != ITEM:
        return [*said, "entity must be an item {type: item, id, registry}"]
    if item.get("registry") != REGISTRY:
        said.append(f"entity.registry must be {REGISTRY!r}, not {item.get('registry')!r}")
    if ref_of(item.get("id")) is None:
        said.append(
            "entity.id of an item must name its sort and its sender, folded: sender:email:ADDRESS or"
            f" sender:domain:HOST, not {item.get('id')!r}"
        )
    status = found.get("status")
    if status not in FATES:
        said.append(f"status {status!r} is not one of a sender's fates: {', '.join(FATES)}")
    reason = found.get("reason")
    if "reason" in found and (not isinstance(reason, str) or not reason.strip()):
        said.append("reason must be the owner's words")
    if status == LET_GO and not (isinstance(reason, str) and reason.strip()):
        said.append("a status of let-go must say why: reason")
    for key, what in (
        ("note", "the id of the note/v1 line written with this one"),
        ("label", "the sender at the time"),
        ("supersedes", "the id of the fate line this replaces"),
    ):
        if key in found and (not isinstance(found[key], str) or not found[key]):
            said.append(f"{key} must be {what}")
    if "note" in found and "reason" not in found:
        said.append("note names the note that carries the reason; a status without a reason has none")
    if found.get("proposed_by") not in ("dream", OWNER):
        said.append("proposed_by must be one of dream, owner")
    head = found.get("logbook_head")
    if "logbook_head" in found and (not isinstance(head, str) or not HEX64.match(head)):
        said.append("logbook_head must be the head the fate was read against, 64 lowercase hex")
    for key in ("portfolio", "until", "amount", "currency", "price", "value"):
        if key in found:
            said.append(f"{key}: a sender's fate carries none")
    return said


# -- the reader ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Fate:
    ref: Ref
    fate: str
    line: str
    seq: int
    at: str
    reason: str | None = None


@dataclass(frozen=True)
class Fates:
    """The standing fates: the senders kept and the senders let go, `email` or `domain` refs."""

    kept: frozenset[Ref] = frozenset()
    let_go: frozenset[Ref] = frozenset()
    standing: Mapping[Ref, Fate] = field(default_factory=dict)

    def fate(self, address: str) -> str | None:
        return fate_of(address, self.kept, self.let_go)


def fate_of(address: str, kept: frozenset[Ref], let_go: frozenset[Ref]) -> str | None:
    """The fate that stands for one address, as RFC 0045's rule reads the two sets: `let-go` when the
    address or its host is let go, whatever keeps either; else `keep` when either is kept; else None."""
    folded = " ".join(address.split()).casefold()
    host = folded.rpartition("@")[2].strip(". ")
    refs = {(EMAIL, folded), (EMAIL, address.strip().lower()), (DOMAIN, host)}
    if refs & let_go:
        return LET_GO
    return KEEP if refs & kept else None


def of(lb: Logbook, lines: Iterable[Line]) -> Fates:
    """The standing fates from `lines`: the status lines and the retractions, in any order, as the
    index holds them (a sealed one is opened when this machine can; one it cannot is no fate)."""
    ordered = sorted(lines, key=lambda line: int(line["seq"]))
    retracted = retractions(line for line in ordered if line.get("kind") == RETRACTION)
    last: dict[Ref, Fate] = {}
    for line in ordered:
        if line.get("kind") != KIND or str(line.get("id")) in retracted:
            continue
        if is_sealed(line):
            try:
                line = lb.opened(line)
            except Exception:
                continue
        body = line.get("payload")
        item = body.get("entity") if isinstance(body, dict) else None
        if not isinstance(body, dict) or not isinstance(item, dict) or item.get("type") != ITEM:
            continue
        if body.get("schema") != SCHEMA or problems(body):
            continue
        ref = ref_of(item.get("id"))
        if ref is None:
            continue
        reason = body.get("reason")
        last[ref] = Fate(
            ref,
            str(body["status"]),
            str(line["id"]),
            int(line["seq"]),
            str(line.get("at")),
            reason if isinstance(reason, str) else None,
        )
    return Fates(
        frozenset(ref for ref, f in last.items() if f.fate == KEEP),
        frozenset(ref for ref, f in last.items() if f.fate == LET_GO),
        last,
    )


def read(lb: Logbook) -> Fates:
    """The record's standing fates, read through the index."""
    with lb.index() as idx:
        return of(lb, [*idx.retractions(), *idx.by_kind(KIND)])


# -- the writer ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Written:
    ref: Ref
    fate: str
    reason: str | None
    line: Line
    note: Line | None
    supersedes: str | None

    def to_json(self) -> dict[str, Any]:
        return {
            "sender": {"kind": self.ref[0], "value": self.ref[1]},
            "fate": self.fate,
            "reason": self.reason,
            "line": str(self.line["id"]),
            "note": None if self.note is None else str(self.note["id"]),
            "supersedes": self.supersedes,
        }


def check(fate: str, reason: str | None) -> str | None:
    """The fate and its reason as they would be written (the reason's words collapsed); `FateError`
    when the fate is not a sender's or a let-go says no why."""
    if fate not in FATES:
        raise FateError(f"{fate!r} is not a sender's fate; one of {', '.join(FATES)}")
    if reason is not None:
        reason = " ".join(reason.split())
        if not reason:
            raise FateError("--reason is empty; say why, or leave it out")
    if fate == LET_GO and reason is None:
        raise FateError('a sender let go must say why: --reason "…"')
    return reason


def write(lb: Logbook, text: str, fate: str, reason: str | None = None, at: str | None = None) -> Written:
    """One fate for the sender `text` names, the reason first as a note when given, under one hold of
    the writer lock (re-entered when the caller already holds it, as the Day page's keep and sign does);
    refused, nothing written, when the fate is not one or is the one that stands. `at` is the moment in
    UTC; now by default."""
    ref = sender(text)
    reason = check(fate, reason)
    with lb.writer():
        meta = lb.meta
        days = day_start.of(meta)
        today = notes.today_in(days)
        stamp = at if at is not None else notes.moment(today, str(meta["timezone"]), None, today, days)
        standing = read(lb).standing.get(ref)
        if standing is not None and standing.fate == fate and (reason is None or reason == standing.reason):
            day = days.day_of(standing.at)
            raise FateError(f"{ref[1]} is {'kept' if fate == KEEP else 'let go'} since {day} already")
        supersedes = None if standing is None else standing.line
        head = str(meta["head"])
        if problems(payload(ref, fate, reason, "0" if reason is not None else None, supersedes, head)):
            raise FateError(problems(payload(ref, fate, reason, None, supersedes, head))[0])
        now = lb.meta
        if now["head"] != meta["head"]:
            raise HeadMoved(HEAD_MOVED.format(was=meta["seq"], now=now["seq"]))
        note = None
        if reason is not None:  # first the note, then the line naming it (RFC 0037 §10.5)
            note = lb.append(
                at=stamp,
                source=SOURCE,
                kind=notes.KIND,
                tier=notes.TIER,
                payload={
                    "schema": notes.SCHEMA,
                    "text": reason,
                    "labels": [NOTE_LABEL],
                    "extra": {"entity": entity(ref)},
                },
            )
        body = payload(ref, fate, reason, None if note is None else str(note["id"]), supersedes, head)
        line = lb.append(at=stamp, source=SOURCE, kind=KIND, tier=TIER, payload=body)
    return Written(ref, fate, reason, line, note, supersedes)
