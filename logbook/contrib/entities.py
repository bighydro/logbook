"""The entities of RFC 0037 — a person, an org, an idea, an asset, a place — as the record holds them:
three payload profiles, the readers that fold them, and the owner's settings for them.

**`entity/v1`** is the canonical thing: `{type, id, registry}`, a label, and the refs the line binds
to it. Persons bind through `resolution/v1` (RFC 0006, frozen) and never here: a person's `entity/v1`
line carries no refs. An org, an idea, an asset and a place bind through `entity/v1` only. A
`resolution/v1` line of type `company`, the frozen word, is read as an org and never rewritten
(`LEGACY`). The line is `source` `manual` and tier 2, and never cites a tier-3 line: a merchant is
bound as a `merchant` ref, a folded string, so no org's name is sealed with the money (`entity_line`).

**`entity-review/v1`** is every no the owner says at review, for every kind: the observed thing is not
the entity proposed (`verdict` `different`), or not the new one the proposal named (its `entity`
then carries `type` alone, its `label` the name), or, a blank rejected, not anything yet. People
review writes it for a person from now on; a `people-review/v1` line (RFC 0035) is read as one of
type person, forever (`reviews`). A place's no is a line too (`places review --reject`), its `ref`
the spot's centre. Its tier is the highest of its evidence and never under 2, a decision (SPEC §4);
3 when it cites a `transaction/v1` line.

**`status/v1`** is what the owner decided about an org, an idea, a place or an asset, at a point in
time: one of the kind's dispositions (`DISPOSITIONS`), no money on the line. Its tier is the kind's
(`status_tier`, RFC 0037 §8): 3 for an org, whose dispositions describe a position in money, so the
line may cite tier-3 evidence; 2 for an idea, a place or an asset, which never cites a tier-3 line.
A person has no status, and a goal is reviewed by RFC 0036's `review/v1`. The current status is the last line
standing; any may follow any. A status that closes a registry entry (a place let go, an asset sold or
let go) closes it with `until`, the line's local day (`entity_status`); the entry is never deleted.

**Readers' rules** (`policy/entities.json`, `Settings`): a status line with a reason that answers a
proposal of another disposition (`proposal.status`) mutes proposals of that disposition for that
entity for `mute_days` (365) while it is the current status (`muted`); a `hold` older than three
years and an `exploring` older than two are stale (`stale`). Neither is ever a line.

Nothing here writes; `entity_status` and the review queues write through `Logbook.append`."""

from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..core import assets, notes, places, resolve
from ..core.chain import Line
from ..core.store import RETRACTION, retractions

ENTITY, ENTITY_REVIEW, STATUS = "entity", "entity-review", "status"  # the lines' `kind`
STATUS_NOTE_LABEL = "status"  # the one label of the note/v1 carrying a status's reason (§10.5)
ENTITY_SCHEMA, ENTITY_REVIEW_SCHEMA, STATUS_SCHEMA = "entity/v1", "entity-review/v1", "status/v1"
PEOPLE_REVIEW, PEOPLE_REVIEW_SCHEMA = "people-review", "people-review/v1"  # RFC 0035: read forever
RESOLUTION = resolve.RESOLUTION
SOURCE, REGISTRY, METHOD = "manual", "logbook", "owner"
TIER = 2  # entity/v1 of every kind, and status/v1 of an idea, a place or an asset (decisions 8 and 10)
MONEY_TIER = 3  # a tier-3 line: what an entity/v1 line never cites
PERSON, ORG, IDEA, ASSET, PLACE = "person", "org", "idea", "asset", "place"
STATUS_TIERS = {ORG: MONEY_TIER}  # a status/v1 line's tier by kind, TIER for the rest (RFC 0037 §8)
KINDS = (PERSON, ORG, IDEA, ASSET, PLACE)
LEGACY = {"company": ORG}  # resolution/v1's frozen word for an org (decision 12)
RESOLUTION_REFS = ("email", "phone", "handle", "provider_id", "device_id", "domain", "line")  # RFC 0006
ADDED_REFS = ("repo", "page", "title", "group", "merchant", "mmsi", "icao24", "registration", "place")
REF_KINDS = RESOLUTION_REFS + ADDED_REFS
# an observed thing's strongest identifier (an entity-review/v1 `ref`) may also be a person's folded
# `name` (RFC 0035), a spot's `centre` (`lat,lon`) or an asset's `subject` id
OBSERVED_REFS = (*REF_KINDS, "name", "centre", "subject", "speaker")  # speaker: a voice (RFC 0038 §4.4)
DIFFERENT = "different"
DISPOSITIONS: dict[str, tuple[str, ...]] = {
    ORG: ("hold", "add", "sell", "let-go", "exited", "passed"),
    IDEA: ("spark", "exploring", "build", "built", "killed"),
    PLACE: ("let-go",),
    ASSET: ("sold", "let-go"),
}
REASON_REQUIRED = frozenset({"passed", "let-go", "killed"})
CLOSING: dict[str, tuple[str, ...]] = {PLACE: ("let-go",), ASSET: ("sold", "let-go")}  # close with `until`
PROPOSED_BY = ("dream", "owner")
NO_STATUS = {
    PERSON: "a person has no status (RFC 0037): people are reviewed, never disposed of",
    "goal": "a goal is reviewed by review/v1 (RFC 0036), not given a status",
}
UUID_TEXT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ARTICLES = frozenset({"the", "a", "an"})
LEGAL_FORMS = frozenset({"as", "asa", "ltd", "inc", "gmbh", "ab"})  # set aside when org names are compared
WORD = re.compile(r"\w+")

POLICY_FILE = Path("policy") / "entities.json"
# RFC 0037 §4.6's default; the file extends it. `example.org` is a family's provider in the synthetic
# record and names nobody's org.
PUBLIC_MAIL_PROVIDERS = (
    "gmail.com",
    "outlook.com",
    "hotmail.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "yahoo.com",
    "example.org",
)
CODE_HOSTS = ("github.com", "gitlab.com", "codeberg.org")
# the suffixes under which one label more is one party: two-label public suffixes, and the names
# RFC 2606 reserves for documentation, whose every subdomain stands for a party of its own
PUBLIC_SUFFIXES = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "com.br",
        "co.za",
        "co.in",
        "com.mx",
        "com.sg",
        "example.org",
        "example.com",
        "example.net",
    }
)
MUTE_DAYS = 365
STALE_DAYS = {"hold": 3 * 365, "exploring": 2 * 365}

Ref = tuple[str, str]


class EntityError(ValueError):
    """A line, an entity or a setting the record refuses; the message says why, nothing is written."""


# -- words ------------------------------------------------------------------------------------------------


def fold(text: str) -> str:
    """NFKC, case folded, whitespace collapsed: how a key, a name or a group is compared (§8)."""
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def words(text: str, articles: bool = True) -> list[str]:
    """The folded words of `text`, punctuation aside; with `articles` False, `the`, `a`, `an` out."""
    found = WORD.findall(fold(text))
    return found if articles else [w for w in found if w not in ARTICLES]


def org_name(text: str) -> tuple[str, ...]:
    """An org's name for comparing: its folded words sorted, the legal forms out (`Nordmann Verft AS`
    is `Nordmann Verft`)."""
    return tuple(sorted(w for w in words(text) if w not in LEGAL_FORMS))


def title_key(text: str) -> str:
    """A title's words folded and sorted, the articles out: `The Fjord Kiosk` → `fjord kiosk`."""
    return " ".join(sorted(words(text, articles=False)))


def registered_domain(host: str, extra: Iterable[str] = ()) -> str | None:
    """The public suffix plus one label, lower-cased: `nordmann-verft.example` from
    `post.nordmann-verft.example`, `fjord.co.uk` from `mail.fjord.co.uk`, `verft.example.org` from
    `post.verft.example.org`; None for a bare suffix or nothing domain-shaped. Read from the
    two-label suffixes this module carries and `extra` (the settings'), never from the network."""
    labels = [part for part in host.strip().strip(".").lower().split(".") if part]
    if len(labels) < 2 or not all(re.fullmatch(r"[a-z0-9-]+", part) for part in labels):
        return None
    suffixes = PUBLIC_SUFFIXES | {s.strip(".").lower() for s in extra}
    if ".".join(labels[-2:]) in suffixes:
        return ".".join(labels[-3:]) if len(labels) >= 3 else ".".join(labels[-2:])
    return ".".join(labels[-2:])


# -- the profiles: validation ---------------------------------------------------------------------------


def _ref_problems(value: object, field_name: str, kinds: Sequence[str]) -> list[str]:
    if not isinstance(value, dict):
        return [f"{field_name} must be an object {{kind, value}}"]
    kind, text = value.get("kind"), value.get("value")
    problems = []
    if kind not in kinds:
        problems.append(f"{field_name}.kind {kind!r} is not one of {', '.join(kinds)}")
    if not isinstance(text, str) or not text.strip():
        problems.append(f"{field_name}.value must be a non-empty string")
    return problems


def _strings(payload: Mapping[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if key in payload and (not isinstance(value, list) or not all(isinstance(v, str) and v for v in value)):
        return [f"{key} must be a list of strings"]
    return []


def _maybe_string(payload: Mapping[str, Any], key: str, what: str) -> list[str]:
    if key in payload and (not isinstance(payload[key], str) or not payload[key]):
        return [f"{key} must be {what}"]
    return []


def _head(payload: Mapping[str, Any]) -> list[str]:
    head = payload.get("logbook_head")
    if "logbook_head" in payload and (not isinstance(head, str) or not HEX64.match(head)):
        return ["logbook_head must be the head the proposal was read against, 64 lowercase hex"]
    return []


def entity_id_problems(kind: object, entity_id: object) -> list[str]:
    """The id rule of `entity/v1` (§3.2): a UUIDv7 minted in this record for an org or an idea, the
    UUID a resolution minted for a person, the name `places.json` spells for a place, the id
    `assets.json` holds for an asset."""
    if not isinstance(entity_id, str) or not entity_id:
        return ["entity.id must be a non-empty string"]
    if kind in (ORG, IDEA):
        if not UUID_TEXT.match(entity_id) or uuid.UUID(entity_id).version != 7:
            return [f"entity.id of an {kind} must be a UUIDv7 minted in this record, not {entity_id!r}"]
    elif kind == PERSON:
        if not UUID_TEXT.match(entity_id):
            return [f"entity.id of a person must be the UUID its resolution minted, not {entity_id!r}"]
    elif kind == ASSET and not assets.ID_PATTERN.match(entity_id):
        return [f"entity.id of an asset must be its assets.json id, not {entity_id!r}"]
    elif kind == PLACE and not entity_id.strip():
        return ["entity.id of a place must be its name in places.json"]
    return []


def _entity_problems(value: object, kinds: Sequence[str], need_id: bool = True) -> list[str]:
    if not isinstance(value, dict):
        return ["entity must be an object {type, id, registry}"]
    kind = value.get("type")
    if kind not in kinds:
        return [f"entity.type {kind!r} is not one of {', '.join(kinds)}"]
    if not need_id and set(value) == {"type"}:
        return []
    problems = entity_id_problems(kind, value.get("id"))
    if value.get("registry") != REGISTRY:
        problems.append(f"entity.registry must be {REGISTRY!r}, not {value.get('registry')!r}")
    return problems


def validate_entity(payload: Mapping[str, Any]) -> list[str]:
    """Every way `payload` is not an `entity/v1` (RFC 0037 §3.2, decision 1), in words; empty when
    it is one. A writer refuses a payload with any problem; a reader keeps reading."""
    problems: list[str] = []
    if payload.get("schema") != ENTITY_SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {ENTITY_SCHEMA!r}")
    problems += _entity_problems(payload.get("entity"), KINDS)
    if not isinstance(payload.get("label"), str) or not str(payload.get("label")).strip():
        problems.append("label must be the name, a non-empty string")
    refs = payload.get("refs")
    if "refs" in payload:
        if not isinstance(refs, list):
            problems.append("refs must be a list of {kind, value}")
        else:
            for n, ref in enumerate(refs):
                problems += _ref_problems(ref, f"refs[{n}]", REF_KINDS)
            entity = payload.get("entity")
            if refs and isinstance(entity, dict) and entity.get("type") == PERSON:
                problems.append("a person's refs bind through resolution/v1: refs must be empty")
    problems += _strings(payload, "aliases")
    keys = payload.get("keys")
    if "keys" in payload and (
        not isinstance(keys, dict) or not all(isinstance(v, str) and v for v in keys.values())
    ):
        problems.append("keys must be an object of strings, the dedupe key of §8 per kind")
    problems += _maybe_string(payload, "method", "a string, `owner`")
    problems += _strings(payload, "evidence")
    problems += _maybe_string(payload, "supersedes", "the id of the entity/v1 line this replaces")
    problems += _head(payload)
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    return problems


def validate_entity_review(payload: Mapping[str, Any]) -> list[str]:
    """Every way `payload` is not an `entity-review/v1` (RFC 0035's shape for every kind; decisions
    2 and 3), in words; empty when it is one."""
    problems: list[str] = []
    if payload.get("schema") != ENTITY_REVIEW_SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {ENTITY_REVIEW_SCHEMA!r}")
    if payload.get("verdict") != DIFFERENT:
        problems.append(f"verdict must be {DIFFERENT!r}; a same is a binding line, never this")
    problems += _ref_problems(payload.get("ref"), "ref", OBSERVED_REFS)
    refs = payload.get("refs")
    if "refs" in payload:
        if not isinstance(refs, list):
            problems.append("refs must be a list of {kind, value}")
        else:
            for n, ref in enumerate(refs):
                problems += _ref_problems(ref, f"refs[{n}]", OBSERVED_REFS)
    problems += _strings(payload, "observed")
    problems += _entity_problems(payload.get("entity"), KINDS, need_id=False)
    entity = payload.get("entity")
    if isinstance(entity, dict) and set(entity) == {"type"} and entity.get("type") == PERSON:
        problems.append("a person's no names the canonical person: entity needs its id and registry")
    problems += _maybe_string(payload, "label", "the entity's label, or the new name the proposal gave")
    problems += _maybe_string(payload, "method", "a string, `owner`")
    problems += _strings(payload, "evidence")
    problems += _head(payload)
    problems += _maybe_string(payload, "raw_id", "a string")
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    return problems


def validate_status(payload: Mapping[str, Any]) -> list[str]:
    """Every way `payload` is not a `status/v1` (RFC 0037 §9.2; decisions 5, 10 and 11), in words;
    empty when it is one. `note` is checked when present and never required: a line with a reason
    written before the writer put the note first has none, and stays valid (§10.5)."""
    problems: list[str] = []
    if payload.get("schema") != STATUS_SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {STATUS_SCHEMA!r}")
    problems += _entity_problems(payload.get("entity"), tuple(DISPOSITIONS))
    entity = payload.get("entity")
    kind = entity.get("type") if isinstance(entity, dict) else None
    status = payload.get("status")
    if kind in DISPOSITIONS and status not in DISPOSITIONS[kind]:
        problems.append(f"status {status!r} is not one of an {kind}'s: {', '.join(DISPOSITIONS[str(kind)])}")
    reason = payload.get("reason")
    if "reason" in payload and (not isinstance(reason, str) or not reason.strip()):
        problems.append("reason must be the owner's words")
    if status in REASON_REQUIRED and not (isinstance(reason, str) and reason.strip()):
        problems.append(f"a status of {status} must say why: reason")
    problems += _maybe_string(payload, "note", "the id of the note/v1 line written with this one")
    if "note" in payload and kind == ORG:
        problems.append("note: an org's reason stays on its tier-3 line, never a note (RFC 0037 §10.5)")
    elif "note" in payload and "reason" not in payload:
        problems.append("note names the note that carries the reason; a status without a reason has none")
    problems += _maybe_string(payload, "label", "the entity's label at the time")
    if payload.get("proposed_by") not in PROPOSED_BY:
        problems.append(f"proposed_by must be one of {', '.join(PROPOSED_BY)}")
    proposal = payload.get("proposal")
    if "proposal" in payload:
        if not isinstance(proposal, dict) or not isinstance(proposal.get("status"), str):
            problems.append("proposal must be an object {status, score?, because?}")
        elif kind in DISPOSITIONS and proposal["status"] not in DISPOSITIONS[kind]:
            problems.append(f"proposal.status {proposal['status']!r} is not an {kind}'s disposition")
    since = payload.get("since")
    if "since" in payload and (not isinstance(since, str) or not DAY.match(since)):
        problems.append("since must be a local day, YYYY-MM-DD")
    problems += _strings(payload, "evidence")
    problems += _maybe_string(payload, "supersedes", "the id of the status line this replaces")
    problems += _head(payload)
    for money in ("amount", "currency", "price", "value"):
        if money in payload:
            problems.append(f"{money}: no money on a status line (decision 10); the ledger holds it")
    return problems


VALIDATORS = {
    ENTITY_SCHEMA: validate_entity,
    ENTITY_REVIEW_SCHEMA: validate_entity_review,
    STATUS_SCHEMA: validate_status,
}


def status_tier(kind: str) -> int:
    """A `status/v1` line's tier for an entity of `kind` (RFC 0037 §8, the owner's decision of 13
    October 2026): 3 for an org, whose `hold`, `add`, `sell` and `exited` describe a position in
    money and whose `passed` and `let-go` would otherwise give that away by contrast; 2 for an idea,
    a place or an asset, a decision about one's own work, place or craft."""
    return STATUS_TIERS.get(kind, TIER)


def reason_note(kind: str) -> bool:
    """Whether a status reason about an entity of `kind` is also written as a `note/v1` (RFC 0037
    §10.5): only when the status line's tier is no higher than a note's, which RFC 0010 fixes at 2
    (MUST), so the note shows nothing the line keeps higher. An org's status is tier 3, so its
    reason stays on the line and no note is ever its reason."""
    return status_tier(kind) <= notes.TIER


def tier_problems(schema: str, tier: int, cited: Mapping[str, int], kind: str | None = None) -> list[str]:
    """The tier rules (decisions 8 and 10; RFC 0037 §8) against the tiers of the lines a payload
    cites (`cited`: line id → tier, the ones the record holds), each problem naming the rule for the
    kind: an `entity/v1` line is tier 2 for every kind and never cites a tier-3 line; a `status/v1`
    line is its kind's tier (`status_tier`: 3 about an org, which may cite tier-3 evidence; 2 about
    an idea, a place or an asset, which never cites a tier-3 line); an `entity-review/v1` is the
    highest tier of its evidence and at least 2, so 3 when it cites a transaction/v1 line."""
    money = sorted(line_id for line_id, t in cited.items() if t >= MONEY_TIER)
    if schema == ENTITY_SCHEMA:
        about = "" if kind is None else f" of kind {kind}"
        problems = [] if tier == TIER else [f"{_a(schema)} line{about} is tier {TIER}, not {tier}"]
        if money:
            problems.append(
                f"{_a(schema)} line{about} never cites a tier-3 line ({money[0]} is tier 3): bind a merchant"
                " as a `merchant` ref, and the ledger is read at the page, within its ceiling"
            )
        return problems
    if schema == STATUS_SCHEMA:
        wanted = status_tier(kind) if kind is not None else TIER
        about = f"about {_an(kind)}" if kind is not None else "about an idea, a place or an asset"
        why = "" if kind != ORG else ": its dispositions describe a position in money"
        problems = [] if tier == wanted else [f"{_a(schema)} line {about} is tier {wanted}, not {tier}{why}"]
        if money and wanted < MONEY_TIER:
            problems.append(
                f"{_a(schema)} line {about} never cites a tier-3 line ({money[0]} is tier 3): no money on"
                " the line, and the ledger is read at the page, within its ceiling"
            )
        return problems
    if schema == ENTITY_REVIEW_SCHEMA:
        wanted = review_tier(cited.values())
        return (
            [] if tier == wanted else [f"an {schema} line citing this evidence is tier {wanted}, not {tier}"]
        )
    return []


def _a(schema: str) -> str:
    return f"{'an' if schema[0] in 'aeiou' else 'a'} {schema}"


def _an(kind: str) -> str:
    return f"{'an' if kind[0] in 'aeiou' else 'a'} {kind}"


def review_tier(cited: Iterable[int]) -> int:
    """An entity-review/v1 line's tier: the highest of its evidence, never under 2 (a decision)."""
    return max([TIER, *cited])


# -- the profiles: building ----------------------------------------------------------------------------


def entity_ref(kind: str, entity_id: str) -> dict[str, str]:
    return {"type": kind, "id": entity_id, "registry": REGISTRY}


def entity_payload(
    kind: str,
    entity_id: str,
    label: str,
    refs: Sequence[Ref] = (),
    aliases: Sequence[str] = (),
    key: str | None = None,
    evidence: Sequence[str] = (),
    head: str | None = None,
    supersedes: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """An `entity/v1` payload as `review KIND --accept` writes it: `method` `owner`, the refs it
    binds, the dedupe key under `keys`, the optional fields only when given."""
    payload: dict[str, Any] = {"schema": ENTITY_SCHEMA, "entity": entity_ref(kind, entity_id), "label": label}
    if aliases:
        payload["aliases"] = list(aliases)
    if refs:
        payload["refs"] = [{"kind": k, "value": v} for k, v in refs]
    if key is not None:
        payload["keys"] = {kind: key}
    payload["method"] = METHOD
    if evidence:
        payload["evidence"] = list(evidence)
    if supersedes is not None:
        payload["supersedes"] = supersedes
    if head is not None:
        payload["logbook_head"] = head
    if extra:
        payload["extra"] = dict(extra)
    return payload


def review_payload(
    kind: str,
    ref: Ref,
    refs: Sequence[Ref] = (),
    observed: Sequence[str] = (),
    entity_id: str | None = None,
    label: str | None = None,
    evidence: Sequence[str] = (),
    head: str | None = None,
    raw_id: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """An `entity-review/v1` payload: the observed thing (`ref`, its `refs` as written, the names
    it was `observed` under) is not the entity `entity_id` of `kind`, or, without one, not the new
    entity the proposal named (`label`), or not anything yet (a blank)."""
    payload: dict[str, Any] = {
        "schema": ENTITY_REVIEW_SCHEMA,
        "verdict": DIFFERENT,
        "ref": {"kind": ref[0], "value": ref[1]},
    }
    if refs:
        payload["refs"] = [{"kind": k, "value": v} for k, v in refs]
    if observed:
        payload["observed"] = list(observed)
    payload["entity"] = entity_ref(kind, entity_id) if entity_id is not None else {"type": kind}
    if label is not None:
        payload["label"] = label
    payload["method"] = METHOD
    if evidence:
        payload["evidence"] = list(evidence)
    if head is not None:
        payload["logbook_head"] = head
    if raw_id is not None:
        payload["raw_id"] = raw_id
    if extra:
        payload["extra"] = dict(extra)
    return payload


def status_payload(
    kind: str,
    entity_id: str,
    label: str | None,
    status: str,
    reason: str | None = None,
    proposed_by: str = METHOD,
    proposal: Mapping[str, Any] | None = None,
    since: str | None = None,
    evidence: Sequence[str] = (),
    supersedes: str | None = None,
    head: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """A `status/v1` payload: the owner's disposition of one entity, with the reason when given and
    `note`, the id of the `note/v1` line written before it with the same words (RFC 0037 §10.5)."""
    payload: dict[str, Any] = {"schema": STATUS_SCHEMA, "entity": entity_ref(kind, entity_id)}
    if label is not None:
        payload["label"] = label
    payload["status"] = status
    if reason is not None:
        payload["reason"] = reason
    if note is not None:
        payload["note"] = note
    payload["proposed_by"] = proposed_by
    if proposal is not None:
        payload["proposal"] = dict(proposal)
    if since is not None:
        payload["since"] = since
    if evidence:
        payload["evidence"] = list(evidence)
    if supersedes is not None:
        payload["supersedes"] = supersedes
    if head is not None:
        payload["logbook_head"] = head
    return payload


# -- the dedupe keys (§8) ------------------------------------------------------------------------------


def key_of(
    kind: str, refs: Iterable[Ref], entity_id: str | None = None, label: str | None = None
) -> str | None:
    """The one dedupe key of an entity of `kind` from the refs it carries, strongest first (§8):
    a person's `email:`, `phone:`, `name:`; an org's `domain:`, `repo-org:`, `group:`, `merchant:`;
    an idea's `page:`, `repo:`, `title:`; a place's `place:` (its name); an asset's `mmsi:`,
    `icao24:`, `registration:`, `subject:` (its id). None when nothing gives one."""
    found: dict[str, str] = {}  # the first ref of each kind, as written
    for k, v in refs:
        found.setdefault(k, v)
    if kind == PERSON:
        for name in ("email", "phone", "name"):
            if name in found:
                value = fold(found[name]) if name != "phone" else found[name].strip()
                return f"{name}:{value}"
        return None
    if kind == ORG:
        if "domain" in found:
            domain = registered_domain(found["domain"]) or fold(found["domain"])
            return f"domain:{domain}"
        repo = found.get("repo")
        if repo is not None and (org := repo_org(repo)) is not None:
            return f"repo-org:{org}"
        for name in ("group", "merchant"):
            if name in found:
                return f"{name}:{fold(found[name])}"
        return None
    if kind == IDEA:
        if "page" in found:
            return f"page:{found['page'].strip()}"
        repo = found.get("repo")
        if repo is not None and repo.strip("/").count("/") >= 2:
            return f"repo:{repo.strip('/').lower()}"
        if "title" in found and (key := title_key(found["title"])):
            return f"title:{key}"
        if label and (key := title_key(label)):
            return f"title:{key}"
        return None
    if kind == PLACE:
        place = found.get("place") or entity_id or label
        return None if not place else f"place:{fold(place)}"
    if kind == ASSET:
        if "mmsi" in found:
            return f"mmsi:{found['mmsi'].strip()}"
        if "icao24" in found:
            return f"icao24:{found['icao24'].strip().lower()}"
        if "registration" in found:
            return f"registration:{registration_key(found['registration'])}"
        subject = found.get("subject") or entity_id
        return None if not subject else f"subject:{subject}"
    return None


def repo_org(value: str) -> str | None:
    """`github.com/nordmann-verft` from `github.com/nordmann-verft/kiosk`: host and first segment."""
    parts = [p for p in value.strip().strip("/").lower().split("/") if p]
    return "/".join(parts[:2]) if len(parts) >= 2 else None


def registration_key(value: str) -> str:
    """A registration folded, the hyphens and spaces out: `ZZ-ABC` and `zz abc` are `zzabc`."""
    return re.sub(r"[\s-]+", "", fold(value))


# -- the canonical entities ----------------------------------------------------------------------------


@dataclass
class Entity:
    """One canonical entity: what the standing lines (and, for a place or an asset, its registry
    entry) say it is. `lines` are the ids of the lines that name it, oldest first."""

    kind: str
    id: str
    label: str
    aliases: list[str] = field(default_factory=list)
    refs: list[Ref] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    registry: bool = False  # a places.json or assets.json entry
    until: str | None = None  # the entry's `until` as the file holds it

    @property
    def key(self) -> str | None:
        return key_of(self.kind, self.refs, self.id, self.label)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "aliases": list(self.aliases),
            "refs": [{"kind": k, "value": v} for k, v in self.refs],
            "key": self.key,
            "lines": list(self.lines),
            "registry": self.registry,
            "until": self.until,
        }


def kind_of(entity: object) -> str | None:
    """The kind an `entity` object names: its `type`, a legacy `company` read as `org`."""
    if not isinstance(entity, dict):
        return None
    kind = entity.get("type")
    if not isinstance(kind, str):
        return None
    kind = LEGACY.get(kind, kind)
    return kind if kind in KINDS else None


def standing(lines: Iterable[Line], kind: str) -> list[Line]:
    """The lines of `kind` standing, in chain order: not retracted, and not named by another
    standing line of the kind in `supersedes` (a retracted line's `supersedes` counts for nothing,
    so the one it replaced stands again)."""
    ordered = sorted(lines, key=lambda line: int(line["seq"]))
    retracted = retractions(line for line in ordered if line.get("kind") == RETRACTION)
    live = [line for line in ordered if line.get("kind") == kind and str(line["id"]) not in retracted]
    replaced = {
        str(value)
        for line in live
        if isinstance(value := (line.get("payload") or {}).get("supersedes"), str) and value
    }
    return [line for line in live if str(line["id"]) not in replaced]


def canonical(lines: Iterable[Line]) -> dict[tuple[str, str], Entity]:
    """(kind, id) → Entity for every entity the record's lines name: the standing `entity/v1`
    lines, and the `resolution/v1` lines through RFC 0006's lookup, a `company` read as an org.
    The label is the first standing line's; a later line adds refs and aliases, never removes one.
    `lines` are the entity, resolution and retraction lines, in any order."""
    lines = list(lines)
    found: dict[tuple[str, str], Entity] = {}
    for line in standing(lines, ENTITY):
        payload = line.get("payload") or {}
        if payload.get("schema") != ENTITY_SCHEMA:
            continue
        kind = kind_of(payload.get("entity"))
        entity_id = (payload.get("entity") or {}).get("id")
        label = payload.get("label")
        if kind is None or not isinstance(entity_id, str) or not entity_id or not isinstance(label, str):
            continue
        entity = found.setdefault((kind, entity_id), Entity(kind, entity_id, label))
        entity.lines.append(str(line["id"]))
        for alias in payload.get("aliases") or []:
            if isinstance(alias, str) and alias not in entity.aliases:
                entity.aliases.append(alias)
        if kind == PERSON:
            continue  # a person's refs bind through resolution/v1 alone (decision 1)
        for ref in _refs(payload.get("refs")):
            if ref not in entity.refs:
                entity.refs.append(ref)
    marks = [line for line in lines if line.get("kind") == RETRACTION]
    resolutions = [line for line in lines if line.get("kind") == RESOLUTION]
    last = resolve.standing([*marks, *resolutions])
    for ref, who in resolve.identities_from([*marks, *resolutions]).items():
        kind = LEGACY.get(who.type or "", who.type or "")
        if who.entity is None or kind not in (PERSON, ORG):
            continue
        entity = found.setdefault((kind, who.entity), Entity(kind, who.entity, who.label or who.entity))
        if ref not in entity.refs:
            entity.refs.append(ref)
        line_id = str(last[ref]["id"])
        if line_id not in entity.lines:
            entity.lines.append(line_id)
    return found


def bindings(lines: Iterable[Line]) -> dict[Ref, tuple[str, str]]:
    """Ref → (kind, id), one lookup over two profiles (§3.4 rule 2): the entity named by the last
    standing line that binds the ref, an `entity/v1` line by its `refs` or a `resolution/v1` line
    by RFC 0006's walk (a `company` read as an org)."""
    lines = list(lines)
    found: dict[Ref, tuple[int, str, str]] = {}
    for line in standing(lines, ENTITY):
        payload = line.get("payload") or {}
        kind = kind_of(payload.get("entity"))
        entity_id = (payload.get("entity") or {}).get("id")
        if kind is None or kind == PERSON or not isinstance(entity_id, str):
            continue
        for ref in _refs(payload.get("refs")):
            found[ref] = (int(line["seq"]), kind, entity_id)
    marks = [line for line in lines if line.get("kind") == RETRACTION]
    resolutions = [line for line in lines if line.get("kind") == RESOLUTION]
    last = resolve.standing([*marks, *resolutions])
    for ref, who in resolve.identities_from([*marks, *resolutions]).items():
        kind = LEGACY.get(who.type or "", who.type or "")
        if who.entity is None or kind not in KINDS:
            continue
        seq = int(last[ref]["seq"])
        if ref not in found or found[ref][0] < seq:
            found[ref] = (seq, kind, who.entity)
    return {ref: (kind, entity_id) for ref, (_seq, kind, entity_id) in found.items()}


def registry(root: Path) -> dict[tuple[str, str], Entity]:
    """The places and assets the registry files name, as entities: a place under its name, an
    asset under its id with its identifiers as refs; `until` as each entry holds it."""
    found: dict[tuple[str, str], Entity] = {}
    document = _json_file(places.path_of(root))
    for place in places.read(root):
        entry = document.get(place.name) if isinstance(document, dict) else None
        until = (
            entry.get("until") if isinstance(entry, dict) and isinstance(entry.get("until"), str) else None
        )
        found[(PLACE, place.name)] = Entity(PLACE, place.name, place.name, refs=[("place", place.name)],
                                            registry=True, until=until)  # fmt: skip
    raw = _json_file(assets.assets_path(root))
    entries = raw.get("assets") if isinstance(raw, dict) else None
    untils = {
        str(e["id"]): str(e["until"])
        for e in (entries if isinstance(entries, list) else [])
        if isinstance(e, dict) and isinstance(e.get("id"), str) and isinstance(e.get("until"), str)
    }
    for asset in assets.read(root):
        refs = [(k, str(getattr(asset, k))) for k in assets.IDENTIFIERS if getattr(asset, k) is not None]
        found[(ASSET, asset.id)] = Entity(ASSET, asset.id, asset.name, refs=refs, registry=True,
                                          until=untils.get(asset.id))  # fmt: skip
    return found


def known(lines: Iterable[Line], root: Path) -> dict[tuple[str, str], Entity]:
    """Every canonical entity: the lines' (`canonical`), with the registry's places and assets
    folded in (an `entity/v1` line for one adds its refs to the entry's)."""
    found = registry(root)
    for key, entity in canonical(lines).items():
        if key in found:
            entry = found[key]
            entry.lines.extend(x for x in entity.lines if x not in entry.lines)
            entry.refs.extend(r for r in entity.refs if r not in entry.refs)
            entry.aliases.extend(a for a in entity.aliases if a not in entry.aliases)
        else:
            found[key] = entity
    return found


def lookup(found: Mapping[tuple[str, str], Entity], kind: str, text: str) -> Entity:
    """The one entity of `kind` that `text` names, tried in order (§6): a ref (`kind:value`, or a
    value one of its refs carries), an id, a label or an alias (case aside), for an org the same
    with the legal forms aside, a word of a label.
    `EntityError` naming the candidates when none or several."""
    pool = [e for (k, _id), e in sorted(found.items()) if k == kind]
    wanted = text.strip()
    if not wanted:
        raise EntityError(f"name an {kind}")
    kind_value = wanted.split(":", 1)
    tries: list[Callable[[Entity], bool]] = [
        lambda e: len(kind_value) == 2 and (kind_value[0], kind_value[1]) in e.refs,
        lambda e: any(fold(v) == fold(wanted) for _k, v in e.refs),
        lambda e: e.id == wanted,
        lambda e: fold(e.label) == fold(wanted) or any(fold(a) == fold(wanted) for a in e.aliases),
        lambda e: (
            kind == ORG
            and bool(org_name(wanted))
            and org_name(wanted) in {org_name(n) for n in (e.label, *e.aliases)}
        ),
        lambda e: len(words(wanted)) == 1 and words(wanted)[0] in words(e.label),
    ]
    for test in tries:
        hits = [e for e in pool if test(e)]
        if len(hits) == 1:
            return hits[0]
        if len(hits) > 1:
            names = ", ".join(f"{e.label} ({e.id})" for e in hits[:5])
            raise EntityError(f"{wanted!r} names {len(hits)} {kind}s: {names}; say which by id")
    have = ", ".join(e.label for e in pool[:8]) or "none yet"
    raise EntityError(f"no {kind} is {wanted!r} (the record's {kind}s: {have})")


def _refs(value: object) -> list[Ref]:
    found: list[Ref] = []
    for item in value if isinstance(value, list) else []:
        if (
            isinstance(item, dict)
            and isinstance(item.get("kind"), str)
            and isinstance(item.get("value"), str)
        ):
            found.append((str(item["kind"]), str(item["value"])))
    return found


def _json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise EntityError(f"{path} is not JSON: {e}") from e


# -- the owner's noes ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Review:
    """One standing no: the observed thing (`ref`, and the identifiers it was seen as) is not the
    entity `entity` of `kind` — or, with `entity` None, not the new one named `label`, or (no label
    either) not anything yet."""

    kind: str
    ref: Ref
    refs: frozenset[Ref]
    entity: str | None
    label: str | None
    line: str
    at: str

    def holds(self, identifiers: Iterable[Ref], entity: str | None = None) -> bool:
        """Whether this no covers an observed thing seen as `identifiers`, against `entity`."""
        seen = set(identifiers)
        return self.entity == entity and (self.ref in seen or bool(self.refs & seen))


def reviews(lines: Iterable[Line]) -> list[Review]:
    """The standing noes of the record, in chain order: every `entity-review/v1` line with verdict
    `different`, and every `people-review/v1` line (RFC 0035), read as one of type person.
    `lines` are the review lines and the retractions, in any order."""
    lines = sorted(lines, key=lambda line: int(line["seq"]))
    retracted = retractions(line for line in lines if line.get("kind") == RETRACTION)
    found: list[Review] = []
    for line in lines:
        if line.get("kind") == RETRACTION or str(line["id"]) in retracted:
            continue
        payload = line.get("payload") or {}
        schema = payload.get("schema")
        if schema not in (ENTITY_REVIEW_SCHEMA, PEOPLE_REVIEW_SCHEMA) or payload.get("verdict") != DIFFERENT:
            continue
        entity = payload.get("entity")
        kind = PERSON if schema == PEOPLE_REVIEW_SCHEMA else kind_of(entity)
        ref = next(iter(_refs([payload.get("ref")])), None)
        if kind is None or ref is None:
            continue
        entity_id = entity.get("id") if isinstance(entity, dict) else None
        if kind == PERSON and not (isinstance(entity_id, str) and entity_id):
            continue
        label = payload.get("label")
        found.append(
            Review(
                kind,
                ref,
                frozenset(_refs(payload.get("refs"))),
                entity_id if isinstance(entity_id, str) and entity_id else None,
                label if isinstance(label, str) and label else None,
                str(line["id"]),
                str(line.get("at")),
            )
        )
    return found


# -- statuses -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Status:
    """One standing `status/v1` line, read."""

    kind: str
    entity: str
    label: str | None
    status: str
    reason: str | None
    proposed_by: str | None
    proposal: str | None  # the disposition the dream proposed, when the line answers one
    since: str | None
    at: str
    line: str
    seq: int
    note: str | None = None  # the id of the note/v1 carrying the reason, when there is one (§10.5)

    def day(self, local: Any) -> str:
        """The local day the status took effect: `since`, else the line's day under `local`."""
        return self.since if self.since is not None else str(local(self.at))

    def to_json(self, local: Any) -> dict[str, Any]:
        return {
            "status": self.status,
            "since": self.day(local),
            "reason": self.reason,
            "proposed_by": self.proposed_by,
            "proposal": self.proposal,
            "label": self.label,
            "line": self.line,
            "note": self.note,
        }


def statuses(lines: Iterable[Line]) -> dict[tuple[str, str], list[Status]]:
    """(kind, id) → the standing status lines of each entity, in chain order; the last is its
    current status. `lines` are the status lines, the retractions and the status notes, in any order.

    A status's reason note is the one its `note` field names (RFC 0037 §10.5: the note is written
    first, the status line after it names it). A line written before the writer kept that order has
    no `note` field: its note came after it and names it under `extra.status`, and is read so, so a
    pair already in a record keeps its meaning. Either way a retracted note is no reason note, and
    an org's line is never joined to one (its reason stays on the line)."""
    lines = list(lines)
    retracted = retractions(line for line in lines if line.get("kind") == RETRACTION)
    named = {
        str(extra["status"]): str(note["id"])
        for note in standing(lines, notes.KIND)
        if notes.labelled(note, STATUS_NOTE_LABEL)
        and isinstance(extra := (note.get("payload") or {}).get("extra"), dict)
        and isinstance(extra.get("status"), str)
    }
    found: dict[tuple[str, str], list[Status]] = {}
    for line in standing(lines, STATUS):
        payload = line.get("payload") or {}
        if payload.get("schema") != STATUS_SCHEMA:
            continue
        kind = kind_of(payload.get("entity"))
        entity_id = (payload.get("entity") or {}).get("id")
        status = payload.get("status")
        if kind not in DISPOSITIONS or not isinstance(entity_id, str) or status not in DISPOSITIONS[kind]:
            continue
        proposal = payload.get("proposal")
        proposed = proposal.get("status") if isinstance(proposal, dict) else None
        note = _text(payload.get("note")) or named.get(str(line["id"]))
        if note in retracted or not reason_note(kind):
            note = None
        found.setdefault((kind, entity_id), []).append(
            Status(
                kind,
                entity_id,
                _text(payload.get("label")),
                str(status),
                _text(payload.get("reason")),
                _text(payload.get("proposed_by")),
                proposed if isinstance(proposed, str) else None,
                _text(payload.get("since")),
                str(line.get("at")),
                str(line["id"]),
                int(line["seq"]),
                note,
            )
        )
    return found


def muted(
    history: Sequence[Status], disposition: str, on: date, local: Any, days: int = MUTE_DAYS
) -> Status | None:
    """The line that mutes the dream's proposals of `disposition` for this entity on `on`, or None
    (decision 6, a reader's rule): the current status, when it has a reason and answers a proposal
    of `disposition` with another status, within `days` of its day. There is no "never" line."""
    if not history:
        return None
    current = history[-1]
    if current.reason is None or current.proposal != disposition or current.status == disposition:
        return None
    start = date.fromisoformat(current.day(local))
    return current if start <= on < start + timedelta(days=days) else None


def stale(
    current: Status,
    on: date,
    local: Any,
    limits: Mapping[str, int] = STALE_DAYS,
    last_touch: str | None = None,
) -> bool:
    """Whether the current status has aged past the reader's limit for it (decision 9: a `hold`
    over three years, an `exploring` over two, `policy/entities.json` `stale_days`): neither the
    status nor, when the reader knows it, the entity's last touch (`last_touch`, a local day) falls
    within that many days of `on` (RFC 0037 §10.6)."""
    limit = limits.get(current.status)
    if limit is None:
        return False
    latest = max(current.day(local), last_touch or "")
    return (on - date.fromisoformat(latest)).days > limit


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


# -- settings (§4.6) ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    public_mail_providers: frozenset[str] = frozenset(PUBLIC_MAIL_PROVIDERS)
    public_suffixes: frozenset[str] = frozenset()
    code_hosts: tuple[str, ...] = CODE_HOSTS
    merchant_min_lines: int = 3
    title_min_lines: int = 2
    registration_min_flights: int = 3
    mute_days: int = MUTE_DAYS
    stale_days: Mapping[str, int] = field(default_factory=lambda: dict(STALE_DAYS))


def settings_path(root: Path) -> Path:
    return Path(root).joinpath(*POLICY_FILE.parts)


def read_settings(root: Path) -> Settings:
    """`policy/entities.json`, read each run and never a line: its provider list and suffixes extend
    the defaults, its numbers replace them. An absent file is the defaults; `EntityError` naming
    the file and the key when a value is not what it should be."""
    path = settings_path(root)
    data = _json_file(path)
    if not isinstance(data, dict):
        raise EntityError(f"{path} must be an object")

    def names(key: str) -> list[str]:
        value = data.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
            raise EntityError(f"{path}: {key} must be a list of names")
        return [v.strip().lower() for v in value]

    def number(key: str, default: int) -> int:
        value = data.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise EntityError(f"{path}: {key} must be a whole number from 1")
        return value

    stale_days = data.get("stale_days", STALE_DAYS)
    if not isinstance(stale_days, dict) or not all(
        isinstance(v, int) and not isinstance(v, bool) and v >= 1 for v in stale_days.values()
    ):
        raise EntityError(f"{path}: stale_days must map a status to a whole number of days")
    hosts = names("code_hosts") if "code_hosts" in data else list(CODE_HOSTS)
    return Settings(
        frozenset(PUBLIC_MAIL_PROVIDERS) | frozenset(names("public_mail_providers")),
        frozenset(names("public_suffixes")),
        tuple(hosts),
        number("merchant_min_lines", 3),
        number("title_min_lines", 2),
        number("registration_min_flights", 3),
        number("mute_days", MUTE_DAYS),
        {**STALE_DAYS, **{str(k): int(v) for k, v in stale_days.items()}},
    )
