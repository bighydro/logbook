"""The same person named twice or more — `logbook people merge`.

A record gets its people from several roads (RFC 0006): the phone's address book mints an entity
per card, a Takeout export mints one per vCard it cannot match, and the owner names a calendar
attendee, a mail sender or a transcript speaker by hand. The same person can end up as two or
three entities, each with its own refs, each heard separately by `people`. This module finds
them, proposes the merge with the evidence, and, only when the owner says so, writes it.

**Finding.** Every entity the resolution lines name as a `person`, never the owner, is a
candidate: its label, every ref that resolves to it (through the alias walk), the sources that
wrote those lines and their tiers. Two candidates are the same person when

- a **phone** meets: a ref of each spells the same E.164 number — a `phone` ref as written, one
  entered without a country code read with `LOGBOOK_DIAL_PREFIX` as the adapters read it
  (`adapters.phone.normalise`), or a WhatsApp JID handle (`447700900001@s.whatsapp.net`);
- an **email** meets: an `email` ref of each, or a `handle` that is an address, is the same
  address, case aside;
- their **names** are the same name and they share a channel: the labels have the same words in
  any order, case, accents and punctuation aside (`Nordmann, Kari` is `Kari Nordmann`), or one
  spells a first name by its initial (`K. Nordmann`), both with two words at least — a first name
  alone names anyone, and one letter off (`Anna`, `Anne`) is another person — and both are heard
  on one of the `people` reader's channels (both through mail, both in transcripts). A name alone
  is not enough.

A ref resolves to one entity only, so a phone or an address never meets itself: what meets is two
spellings of one identifier, which is exactly what a second import leaves behind. Matches are
joined (a phone between A and B and an address between B and C is one proposal of three); the
**primary** is the candidate with the most refs, then the most lines heard, then the one minted
first; the others are secondary. A proposal's id is a digest of its entity ids, so it is the same
on every run until something changes.

**Merging.** Nothing is retracted and no raw line is touched. Per secondary ref whose own line
names the entity, one `resolution/v1` line with `alias_of` the primary's ref (one whose line
names the primary, a phone before an address): the ref and every ref already aliased to it then
resolve to the primary through the ordinary walk (RFC 0006 rule 6), which `people`, `person`,
the with module and every reader take. The new line `supersedes` the line it replaces, carries
both as `evidence`, the primary's label, `method` `owner` (the owner applied it), the head the
proposal was read against, and under `extra` the proposal id, the two entities and what matched.
A ref whose existing alias chain would run past `resolve.MAX_HOPS` after the merge gets its own
line instead of relying on the walk. Only `Logbook.append` writes.

**Review.** `--export-review FILE` is one CSV row per (proposal, secondary) with an empty
`apply` column; the owner marks `yes` (or `y`, `x`, `true`, `1`) and `--apply-review FILE` applies
the marked rows, each as the merge of its secondary into its primary, saying which rows were
already merged and refusing a row it cannot place before anything is written."""

from __future__ import annotations

import csv
import hashlib
import os
import re
import unicodedata
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core import people, reading, resolve
from ..core.chain import Line
from ..core.resolve import Identity, Ref
from ..core.store import Logbook, now_utc
from .adapters import phone as phones
from .adapters.ios_contacts import DIAL_PREFIX_ENV

SCHEMA = "resolution/v1"
SOURCE = "manual"
METHOD = "owner"
PHONE = re.compile(r"^\+\d{6,15}$")
WHATSAPP_JID = re.compile(r"^(\d{6,15})@s\.whatsapp\.net$")
ADDRESS = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
KIND_ORDER = ("phone", "email", "handle", "provider_id")  # which of the primary's refs to alias to
MARKED = frozenset({"y", "yes", "x", "true", "1", "merge"})
COLUMNS = (
    "proposal",
    "apply",
    "primary_id",
    "primary",
    "primary_refs",
    "secondary_id",
    "secondary",
    "secondary_refs",
    "matched",
)
FOLD = str.maketrans({"ø": "o", "æ": "ae", "ð": "d", "đ": "d", "ł": "l", "œ": "oe", "þ": "th"})
EN_DASH = "\u2013"


class MergeError(ValueError):
    """A proposal id or a review row the record cannot act on; nothing was written."""


# -- what the record names -----------------------------------------------------------------------------------


@dataclass
class Candidate:
    """One person entity as the resolution lines mint it: the label of the line that minted it
    (the first standing entity line, by seq), every ref that resolves to it with that ref's own
    standing line, the sources of those lines, the highest tier among them, the seq the entity
    was first named at, and how many lines the `people` reader heard it on, per channel."""

    entity: str
    label: str
    refs: list[Ref] = field(default_factory=list)  # in the order their lines were written
    lines: dict[Ref, Line] = field(default_factory=dict)
    channels: dict[str, int] = field(default_factory=dict)

    @property
    def sources(self) -> list[str]:
        return sorted({str(line.get("source")) for line in self.lines.values()})

    @property
    def tier(self) -> int:
        return max((int(line.get("tier", 0)) for line in self.lines.values()), default=0)

    @property
    def first_seq(self) -> int:
        return min((int(line["seq"]) for line in self.lines.values()), default=0)

    @property
    def heard(self) -> int:
        return sum(self.channels.values())

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.entity,
            "name": self.label,
            "refs": [{"kind": k, "value": v} for k, v in self.refs],
            "sources": self.sources,
            "channels": dict(self.channels),
        }


@dataclass(frozen=True)
class Match:
    """Why two candidates are one person: `kind` is `phone`, `email` or `name`; `value` the number,
    the address, or the two labels; `refs` the ref of each that met, in the proposal's order;
    `channels` the channels both are heard on (a name match needs one)."""

    kind: str
    value: str
    entities: tuple[str, str]
    refs: tuple[Ref, Ref]
    channels: tuple[str, ...] = ()

    def ordered(self, order: Mapping[str, int]) -> Match:
        if order.get(self.entities[0], 0) <= order.get(self.entities[1], 0):
            return self
        return Match(
            self.kind,
            self.value,
            (self.entities[1], self.entities[0]),
            (self.refs[1], self.refs[0]),
            self.channels,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "value": self.value,
            "entities": list(self.entities),
            "refs": [{"kind": k, "value": v} for k, v in self.refs],
            "channels": list(self.channels),
        }


@dataclass
class Proposal:
    id: str
    primary: Candidate
    secondary: list[Candidate]
    matches: list[Match]

    @property
    def tier(self) -> int:
        return max(c.tier for c in (self.primary, *self.secondary))

    def matched(self, secondary: Candidate) -> list[Match]:
        return [m for m in self.matches if secondary.entity in m.entities]

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tier": self.tier,
            "primary": self.primary.to_json(),
            "secondary": [c.to_json() for c in self.secondary],
            "matches": [m.to_json() for m in self.matches],
        }


@dataclass(frozen=True)
class Report:
    proposals: list[Proposal]
    candidates: dict[str, Candidate]  # every person the record names, by entity id
    standing: dict[Ref, Line]
    identities: dict[Ref, Identity]
    head: str

    @property
    def tier(self) -> int | None:
        return max((p.tier for p in self.proposals), default=None)

    def to_json(self) -> dict[str, Any]:
        return {"tier": self.tier, "proposals": [p.to_json() for p in self.proposals]}


# -- reading -------------------------------------------------------------------------------------------------


def read(lb: Logbook) -> Report:
    """The proposals of the record at its head. Reads the resolution and retraction lines through
    the index and the channels through the `people` reader over the whole record; writes nothing.
    Raises what `people.read` raises."""
    with lb.index() as idx:
        lines = [*idx.retractions(), *idx.resolutions()]
    standing = resolve.standing(lines)
    identities = resolve.identities_from(lines)
    window = reading.record_days(lb)
    owner: frozenset[str] = frozenset()
    channels: dict[str, dict[str, int]] = {}
    if window is not None:
        report = people.read(lb, *window)
        owner = report.owner.entities
        channels = {
            entity: {name: c.lines for name, c in person.channels.items() if c.lines}
            for entity, person in report.known.items()
        }
    candidates = candidates_from(standing, identities, owner, channels)
    prefix = os.environ.get(DIAL_PREFIX_ENV, "").strip()
    proposals = propose(candidates, prefix)
    return Report(proposals, candidates, standing, identities, str(lb.meta["head"]))


def candidates_from(
    standing: Mapping[Ref, Line],
    identities: Mapping[Ref, Identity],
    owner: frozenset[str],
    channels: Mapping[str, Mapping[str, int]] | None = None,
) -> dict[str, Candidate]:
    """Every person entity the resolution lines name, never the owner's, with its refs in the
    order their standing lines were written and the label of the line that minted it."""
    found: dict[str, Candidate] = {}
    channels = channels or {}
    by_seq = sorted(identities.items(), key=lambda item: int(standing[item[0]]["seq"]))
    for ref, who in by_seq:
        if not who.entity or who.type != "person" or who.entity in owner:
            continue
        line = standing[ref]
        candidate = found.get(who.entity)
        if candidate is None:
            candidate = found[who.entity] = Candidate(
                who.entity, "", channels=dict(channels.get(who.entity, {}))
            )
        candidate.refs.append(ref)
        candidate.lines[ref] = line
        label = (line.get("payload") or {}).get("label")
        if (
            not candidate.label
            and "entity" in (line.get("payload") or {})
            and isinstance(label, str)
            and label
        ):
            candidate.label = label
    for candidate in found.values():
        if not candidate.label:
            labels = [
                who.label for ref, who in identities.items() if who.entity == candidate.entity and who.label
            ]
            candidate.label = labels[0] if labels else candidate.entity
    return found


# -- matching ------------------------------------------------------------------------------------------------


def propose(candidates: Mapping[str, Candidate], prefix: str = "") -> list[Proposal]:
    """The pure function: candidates to proposals, each a group of two or more joined by the
    matches above, primary first, in the order the primaries were minted."""
    matches = [*_exact(candidates, prefix), *_by_name(candidates)]
    parent = {entity: entity for entity in candidates}

    def root(entity: str) -> str:
        while parent[entity] != entity:
            parent[entity] = parent[parent[entity]]
            entity = parent[entity]
        return entity

    for m in matches:
        a, b = root(m.entities[0]), root(m.entities[1])
        if a != b:
            parent[b] = a
    groups: dict[str, list[Candidate]] = {}
    for entity, candidate in candidates.items():
        groups.setdefault(root(entity), []).append(candidate)
    proposals = []
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda c: (-len(c.refs), -c.heard, c.first_seq))
        primary, secondary = members[0], sorted(members[1:], key=lambda c: c.first_seq)
        order = {c.entity: n for n, c in enumerate((primary, *secondary))}
        ids = {c.entity for c in members}
        own = [m.ordered(order) for m in matches if m.entities[0] in ids]
        own.sort(key=lambda m: (order[m.entities[0]], order[m.entities[1]], m.kind, m.value))
        proposals.append(Proposal(proposal_id(ids), primary, secondary, own))
    proposals.sort(key=lambda p: p.primary.first_seq)
    return proposals


def proposal_id(entities: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(entities)).encode("utf-8")).hexdigest()[:16]


def _exact(candidates: Mapping[str, Candidate], prefix: str) -> Iterator[Match]:
    """A phone or an address two candidates spell: one match per (key, pair of candidates), the
    first ref of each that spells it."""
    holders: dict[tuple[str, str], list[tuple[str, Ref]]] = {}
    for candidate in candidates.values():
        seen: set[tuple[str, str]] = set()
        for ref in candidate.refs:
            for key in (_phone_key(ref, prefix), _email_key(ref)):
                if key is None or key in seen:
                    continue
                seen.add(key)
                holders.setdefault(key, []).append((candidate.entity, ref))
    for (kind, value), found in holders.items():
        for n, (a, ref_a) in enumerate(found):
            for b, ref_b in found[n + 1 :]:
                yield Match(kind, value, (a, b), (ref_a, ref_b))


def _phone_key(ref: Ref, prefix: str) -> tuple[str, str] | None:
    kind, value = ref
    if kind == "phone":
        number, flagged = phones.normalise(value, prefix)
        return ("phone", number) if number and not flagged and PHONE.match(number) else None
    if kind == "handle":
        jid = WHATSAPP_JID.match(value)
        return ("phone", f"+{jid.group(1)}") if jid else None
    return None


def _email_key(ref: Ref) -> tuple[str, str] | None:
    kind, value = ref
    address = value.strip().casefold()
    if kind == "email" and address:
        return ("email", address)
    if kind == "handle" and ADDRESS.match(address):
        return ("email", address)
    return None


def _by_name(candidates: Mapping[str, Candidate]) -> Iterator[Match]:
    """Two candidates with the same name, both heard on one channel at least."""
    ordered = sorted(candidates.values(), key=lambda c: c.first_seq)
    for n, a in enumerate(ordered):
        if not a.channels:
            continue
        for b in ordered[n + 1 :]:
            shared = tuple(sorted(set(a.channels) & set(b.channels), key=people.CHANNELS.index))
            if shared and similar_names(a.label, b.label):
                yield Match(
                    "name", f"{a.label} ~ {b.label}", (a.entity, b.entity), (a.refs[0], b.refs[0]), shared
                )


def similar_names(a: str, b: str) -> bool:
    """Whether two labels are one name: the same words in any order, case, accents and
    punctuation aside, or the same words in order with a first name spelled by its initial on
    one side; two words at least on both sides, and never a word one letter off."""
    words_a, words_b = _words(a), _words(b)
    if len(words_a) < 2 or len(words_b) < 2:
        return False
    if sorted(words_a) == sorted(words_b):
        return True
    if len(words_a) != len(words_b):
        return False
    pairs = list(zip(words_a, words_b, strict=True))
    initial = all(
        x == y or (len(x) == 1 and y.startswith(x)) or (len(y) == 1 and x.startswith(y)) for x, y in pairs
    )
    return initial and any(x == y for x, y in pairs)


def _words(label: str) -> list[str]:
    text = unicodedata.normalize("NFKD", label.casefold()).translate(FOLD)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]|_", " ", text).split()


# -- applying ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Applied:
    proposal: str
    into: Candidate
    merged: list[Candidate]
    lines: list[Line]

    def to_json(self) -> dict[str, Any]:
        return {
            "proposal": self.proposal,
            "into": {"id": self.into.entity, "name": self.into.label},
            "from": [{"id": c.entity, "name": c.label} for c in self.merged],
            "lines": [str(line["id"]) for line in self.lines],
        }


def apply(lb: Logbook, report: Report, ids: Sequence[str]) -> list[Applied]:
    """The proposals `ids` name, each secondary aliased to its primary; every id is checked
    before the first line is written. `MergeError` names an id that is no proposal."""
    by_id = {p.id: p for p in report.proposals}
    unknown = [id_ for id_ in ids if id_ not in by_id]
    if unknown:
        raise MergeError(
            f"no proposal {', '.join(unknown)}; `logbook people merge --propose` lists them with their ids"
        )
    applied = []
    for id_ in dict.fromkeys(ids):
        proposal = by_id[id_]
        lines = []
        for secondary in proposal.secondary:
            lines.extend(merge(lb, report, proposal.primary, secondary, id_, proposal.matched(secondary)))
        applied.append(Applied(id_, proposal.primary, list(proposal.secondary), lines))
    return applied


def merge(
    lb: Logbook,
    report: Report,
    primary: Candidate,
    secondary: Candidate,
    proposal: str,
    matched: Sequence[Match],
) -> list[Line]:
    """The lines that make `secondary` the same person as `primary`, appended: one alias per ref
    of the secondary that names it (or whose chain would run past `MAX_HOPS`), of the tier of
    the evidence (the two candidates' lines)."""
    target = _target(primary)
    tier = max(primary.tier, secondary.tier)
    at = now_utc()
    written = []
    for ref in secondary.refs:
        own = secondary.lines[ref]
        if "entity" not in (own.get("payload") or {}):
            hops = len(resolve.walk(ref, report.standing)) - 1
            if hops + 1 <= resolve.MAX_HOPS:
                continue  # follows its alias to the ref aliased below
        payload: dict[str, Any] = {
            "schema": SCHEMA,
            "ref": {"kind": ref[0], "value": ref[1]},
            "alias_of": {"kind": target[0], "value": target[1]},
            "label": primary.label,
            "method": METHOD,
            "evidence": [str(own["id"]), str(primary.lines[target]["id"])],
            "supersedes": str(own["id"]),
            "logbook_head": report.head,
            "raw_id": f"merge:{proposal}:{ref[0]}:{ref[1]}",
            "extra": {
                "merge": proposal,
                "from": secondary.entity,
                "into": primary.entity,
                "matched": [f"{m.kind} {m.value}" for m in matched],
            },
        }
        written.append(lb.append(at=at, source=SOURCE, kind="resolution", tier=tier, payload=payload))
    return written


def _target(primary: Candidate) -> Ref:
    """The primary's ref to alias to: one whose own line names the entity, a phone before an
    address, the earliest written among those."""
    named = [ref for ref in primary.refs if "entity" in (primary.lines[ref].get("payload") or {})]
    if not named:
        raise MergeError(f"{primary.label} ({primary.entity}) has no line of its own to alias to")

    def order(ref: Ref) -> tuple[int, int]:
        kind = KIND_ORDER.index(ref[0]) if ref[0] in KIND_ORDER else len(KIND_ORDER)
        return kind, int(primary.lines[ref]["seq"])

    return min(named, key=order)


# -- the review file -----------------------------------------------------------------------------------------


def export_review(report: Report, path: Path) -> int:
    """One row per (proposal, secondary), `apply` empty for the owner to mark; the rows written."""
    n = 0
    with Path(path).open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for p in report.proposals:
            for secondary in p.secondary:
                writer.writerow(
                    {
                        "proposal": p.id,
                        "apply": "",
                        "primary_id": p.primary.entity,
                        "primary": p.primary.label,
                        "primary_refs": _refs_text(p.primary.refs),
                        "secondary_id": secondary.entity,
                        "secondary": secondary.label,
                        "secondary_refs": _refs_text(secondary.refs),
                        "matched": "; ".join(match_text(m) for m in p.matched(secondary)),
                    }
                )
                n += 1
    return n


@dataclass(frozen=True)
class Row:
    line: int  # of the file, the header being 1
    proposal: str
    primary: str
    secondary: str
    marked: bool
    secondary_refs: tuple[Ref, ...]


def read_review(path: Path) -> list[Row]:
    """Every row of a review file; `MergeError` when the file is not one (`primary_id`,
    `secondary_id` and `apply` columns), or cannot be read."""
    try:
        with Path(path).open(encoding="utf-8", newline="") as fh:
            reader = csv.DictReader(fh)
            columns = reader.fieldnames or []
            missing = [c for c in ("primary_id", "secondary_id", "apply") if c not in columns]
            if missing:
                raise MergeError(f"{path}: not a review file; no {', '.join(missing)} column")
            rows = []
            for n, row in enumerate(reader, start=2):
                rows.append(
                    Row(
                        n,
                        (row.get("proposal") or "").strip(),
                        (row.get("primary_id") or "").strip(),
                        (row.get("secondary_id") or "").strip(),
                        (row.get("apply") or "").strip().casefold() in MARKED,
                        _refs_of(row.get("secondary_refs") or ""),
                    )
                )
    except OSError as e:
        raise MergeError(f"{path}: {e.strerror or e}") from e
    except csv.Error as e:
        raise MergeError(f"{path}: not a CSV file ({e})") from e
    return rows


def apply_review(lb: Logbook, report: Report, rows: Sequence[Row]) -> tuple[list[Applied], list[Row]]:
    """The marked rows applied, each the merge of its secondary into its primary, after every
    row is placed: (applied, the rows skipped as already merged). `MergeError` on a row whose
    primary is nobody, whose secondary is nobody and not already merged into that primary, or
    that names one entity twice; nothing is then written."""
    plans: list[Row] = []
    done: list[Row] = []
    for row in rows:
        if not row.marked:
            continue
        if row.primary not in report.candidates:
            raise MergeError(f"row {row.line}: {row.primary or '(no primary_id)'} is nobody the record names")
        if row.secondary == row.primary:
            raise MergeError(f"row {row.line}: primary and secondary are the same entity")
        if row.secondary not in report.candidates:
            resolved = {
                report.identities[ref].entity for ref in row.secondary_refs if ref in report.identities
            }
            if row.secondary_refs and resolved == {row.primary}:
                done.append(row)
                continue
            raise MergeError(
                f"row {row.line}: {row.secondary or '(no secondary_id)'} is nobody the record names"
            )
        plans.append(row)
    applied = []
    for row in plans:
        primary, secondary = report.candidates[row.primary], report.candidates[row.secondary]
        proposal = next(
            (p for p in report.proposals if secondary.entity in {c.entity for c in p.secondary}), None
        )
        matched = proposal.matched(secondary) if proposal is not None and proposal.primary is primary else []
        id_ = row.proposal or proposal_id((primary.entity, secondary.entity))
        lines = merge(lb, report, primary, secondary, id_, matched)
        applied.append(Applied(id_, primary, [secondary], lines))
    return applied, done


def _refs_text(refs: Iterable[Ref]) -> str:
    return "; ".join(f"{kind}:{value}" for kind, value in refs)


def _refs_of(text: str) -> tuple[Ref, ...]:
    found = []
    for part in text.split(";"):
        kind, colon, value = part.strip().partition(":")
        if colon and kind and value:
            found.append((kind, value))
    return tuple(found)


# -- text ----------------------------------------------------------------------------------------------------


def match_text(m: Match) -> str:
    text = f"{m.kind} {m.value}"
    return f"{text} ({', '.join(m.channels)})" if m.channels else text


def rows(report: Report) -> Iterator[str]:
    """The proposals, one block each: the id, the primary and the secondaries, then each match
    with the refs that met and the lines that wrote them."""
    if not report.proposals:
        yield "no proposals: nobody is named twice"
        return
    named = sum(1 + len(p.secondary) for p in report.proposals)
    head = f"{_plural(len(report.proposals), 'proposal')} · {named} people named twice or more"
    yield f"{head} · tier {report.tier}"
    for p in report.proposals:
        yield f"  {p.id}  {p.primary.label} ← {', '.join(c.label for c in p.secondary)}"
        by_id = {c.entity: c for c in (p.primary, *p.secondary)}
        for m in p.matches:
            if m.kind == "name":
                yield f"    name {m.value} · both on {', '.join(m.channels)}"
                continue
            met = " · ".join(
                _ref_text(by_id[entity], ref) for entity, ref in zip(m.entities, m.refs, strict=True)
            )
            yield f"    {m.kind} {m.value}: {met}"
    yield "nothing merged: `people merge --apply ID...`, or `--export-review FILE`, mark, `--apply-review`"


def _ref_text(candidate: Candidate, ref: Ref) -> str:
    line = candidate.lines[ref]
    return f"{ref[1]} ({line.get('source')}, seq {line['seq']})"


def applied_rows(applied: Iterable[Applied]) -> Iterator[str]:
    for a in applied:
        seqs = [int(line["seq"]) for line in a.lines]
        span = (
            ""
            if not seqs
            else f" (seq {seqs[0]})"
            if len(seqs) == 1
            else f" (seq {seqs[0]}{EN_DASH}{seqs[-1]})"
        )
        merged = ", ".join(c.label for c in a.merged)
        yield f"merged {merged} → {a.into.label}: {_plural(len(seqs), 'line')}{span}"


def _plural(n: int, noun: str) -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"
