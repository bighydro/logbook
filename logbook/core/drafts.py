"""The draft (RFC 0036, `draft/v1`): what a model wrote about a unit of the record, every sentence
pointing at the lines it rests on or marked unsupported.

A draft is a proposal. Nothing in it is a fact of the record until the owner confirms it through an
act of their own: a signed day (RFC 0034), a note (RFC 0010), a review or a star. This module fixes
the line and reads it back; what writes one is `logbook.contrib.dream` (`logbook dream day`). Nothing
here writes.

The payload: `unit` (`day` here), `subject` (the local day), `read_head` (the record's head when the
model read), `read_count` (how many lines of the unit it read, under the ceiling it read under),
`language` (a BCP 47 tag) and `segments`, in order, each `{text, evidence: [line ids]}` or `{text,
unsupported: true}` and nothing else (`segment_shape`). `supersedes` names the earlier draft of the
same unit this one replaces. `extra` keeps what the writer wants to say about its run: the prompt's
name, the part of the dream each segment belongs to (`parts`, one word per segment: the day in a
paragraph, the threads it moved, the questions, the people and promises proposed) and the digest of
the ids it read (`read_ids_sha256`), which `dream --catch-up` compares, the version of the
crossing entry it was dreamed under (`policy_version`, `policy.version`: the SHA-256 of the entry's
`max_tier`, `until` and `model`), and how many proposals the writer dropped and why (`dropped`).

**Proposals.** Beside its text a draft MAY carry `proposals`: what the model thinks happened and the
owner may confirm, each one object, kind `event` the only kind so far (`proposal_shape`): `{kind:
"event", title, start, end, place, people, evidence}`, `start` before `end`, both RFC 3339 UTC with a
`Z`; `place` a named place of `places.json` by its name or an observed place by its id
(`place:<lat>,<lon>`, as `places review` names a cluster), or null; `people` canonical person ids
(the entity ids the resolution lines name, never the owner); `evidence` the line ids it rests on. A
proposal is numbered by its place in the list, from 1. It is never an event line: the owner's
`--accept` (`day sign`, `day reflect --sign`) makes it one, an `event/v1` line, source `owner`, whose
`raw_id` is `<draft id>/<number>` and whose `extra.from` names the draft (`confirmations`); the Day
then shows the proposal confirmed and the event among the day's events.

**A transcript's synthesis** (`logbook transcript synthesize`, `logbook.contrib.synthesis`) is a
draft of unit `event` whose `subject` is `[<the transcript line's id>]`. A transcript's utterances
are not lines of their own (`transcript/v1` keeps the text in one attachment, RFC 0004), so every
supported segment's `evidence` is the transcript line, and which utterances it rests on is kept
beside the segments: `extra.segments`, one object per segment, `{part, utterances: [{n, offset?}],
assignee?, due?: {phrase, date}}`, `part` one of `SYNTHESIS_PARTS` (actions on top), `n` the
utterance's place in the transcript as `transcripts.turns_of` reads it, from 1, and `offset` where
it is in the recording (`20:05`) when the source says. Like every draft it records the version of
the `dream` entry it was made under (`extra.policy_version`), and it follows the policy as every
draft does (below). `by_transcript` finds the syntheses as `by_day` finds the days' drafts, and
`for_transcripts` gives the Day the standing synthesis of each of its transcripts through the same
rule as `for_day` (`through`), every evidence id checked against the transcript. A synthesis is the
call's draft, never the day's (amendment 1: one standing draft per unit): `by_day`, `for_day` and
`withheld` read unit `day` alone, so a synthesis neither replaces nor shadows the day's draft.

**The standing draft** of a day is its latest `draft` line, by `at` then `seq`, that is not retracted
and not named in a later draft's `supersedes`; the earlier ones stay in the record and the Day lists
their ids. A reader that holds the record checks every evidence id against the day's lines: an id
that is not on the day makes the segment unsupported and says why (rule 6); a segment of neither
documented shape is unsupported and the line is said to be malformed. A reader never prints an
unsupported segment as plain prose between two supported ones: in text it is set apart with a
leading `~` and the word `unsupported` after it.

**Derived material follows the policy, not the head.** A draft is what a model wrote from lines the
`dream` entry of `policy/crossing.json` let cross to it, so a reader shows it only while the entry
still allows its tier (`allowed`): a draft above the entry's `max_tier` today (lowered since, expired,
removed, or a file that is not a policy) is withheld, whatever the head, and the standing draft among
the ones the entry allows is shown in its place, if there is one. The line stays in the record. The
Day of a reader that holds the whole record says so in one row, `superseded by policy` and why, and
nothing of the draft's text (`withheld_json`); a reader through a gate of its own hides it without a
word, as it hides every line above its gate. A withheld draft's proposals are withheld with it: the Day
shows none and `--accept` names none, and the draft shown in its place brings its own; an event the
owner confirmed from it before stays, an owner's line like any other. A call's synthesis is held the
same way, by the same rule (`through`), and its row goes under the call's own row on the Day
(`syntheses_withheld`), never in the day's draft's place. `doctor` lists the days whose standing draft
is withheld (`withheld`), and `dream --catch-up` dreams them again under the entry when it allows any
tier."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import policy, resolve
from .chain import Line
from .index import Index
from .store import retractions

KIND = "draft"
SCHEMA = "draft/v1"
UNIT_DAY = "day"
UNIT_EVENT = "event"  # a transcript's synthesis: the call is the unit, its line the subject
UNITS = ("day", "journey", "event", "week", "month", "year", "chapter")
SOURCE_PREFIX = "model:"  # `source` names the model as its runner names it; never `manual`
SUPPORTED, UNSUPPORTED, MALFORMED = "supported", "unsupported", "malformed"
PARTS = ("day", "threads", "questions", "people", "promises")  # the parts of a dream, in order
PART_LABELS = {
    "day": "day",
    "threads": "thread",
    "questions": "question",
    "people": "people",
    "promises": "promise",
}
# the parts of a transcript's synthesis, in order: actions on top (`logbook transcript synthesize`)
SYNTHESIS_PARTS = ("actions", "topics", "decisions", "open_threads", "personal")
SYNTHESIS_LABELS = {
    "actions": "action",
    "topics": "topic",
    "decisions": "decision",
    "open_threads": "open",
    "personal": "personal",
}
SYNTHESIS_NOUNS = {
    "actions": ("action", "actions"),
    "topics": ("topic", "topics"),
    "decisions": ("decision", "decisions"),
    "open_threads": ("open thread", "open threads"),
    "personal": ("personal", "personal"),
}
HEAD_SHORT = 8  # `read at bb97e90d`: the first 8 hex of the head
ID_SHORT = 8  # an evidence id shortened to its last 8 characters in text
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*\Z")  # a BCP 47 tag, loosely
SHA256_HEX = 64
NOT_ON_DAY = "evidence names a line that is not on the day"
NOT_THE_TRANSCRIPT = "evidence names a line that is not the transcript"
WHOLE = "the transcript"  # a segment that rests on the transcript line and on no utterance of it
NOT_A_SEGMENT = "a segment is {text, evidence} or {text, unsupported: true}, nothing else"
SUPERSEDED_BY_POLICY = "superseded by policy"  # the Day's row for a draft the dream entry no longer allows
DOT = " · "
EN_DASH = "\u2013"
PROPOSALS = "proposals"  # the payload key of what a draft proposes beside its text
EVENT = "event"  # the one kind of proposal so far: an event the owner may confirm into an event/v1 line
EVENT_KIND = "event"  # the line a confirmed proposal becomes
OWNER = "owner"  # its source: the owner confirmed it, the model only proposed it
CLUSTER = "place:"  # an observed place's id, `place:<lat>,<lon>`, as `places review` names a cluster
PROPOSAL_KEYS = frozenset({"kind", "title", "start", "end", "place", "people", "evidence"})
NOT_A_PROPOSAL = (
    "a proposal is {kind: event, title, start, end, place, people, evidence}: start before end, both UTC"
    " with a Z, people and evidence lists of ids, evidence not empty"
)
UTC_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z\Z")


class DraftError(ValueError):
    """A draft the record refuses; the message says what and nothing is written."""


# -- the shape ------------------------------------------------------------------------------------------


def segment_shape(segment: object) -> str:
    """`supported` for `{text, evidence: [ids]}`, `unsupported` for `{text, unsupported: true}`,
    `malformed` for anything else: both keys, neither, an empty evidence, a false mark, an empty
    text, or an evidence entry that is not a string."""
    if not isinstance(segment, dict):
        return MALFORMED
    text = segment.get("text")
    if not isinstance(text, str) or not text.strip():
        return MALFORMED
    has_evidence, has_mark = "evidence" in segment, "unsupported" in segment
    if has_evidence and not has_mark:
        evidence = segment["evidence"]
        if isinstance(evidence, list) and evidence and all(isinstance(e, str) and e for e in evidence):
            return SUPPORTED
        return MALFORMED
    if has_mark and not has_evidence and segment["unsupported"] is True:
        return UNSUPPORTED
    return MALFORMED


def validate(payload: Mapping[str, Any]) -> list[str]:
    """Every way the payload is not a `draft/v1`, in words; empty when it is one. A writer refuses
    a payload with any problem; a reader keeps reading and says the line is malformed."""
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append(f"schema is {payload.get('schema')!r}, not {SCHEMA!r}")
    if payload.get("unit") not in UNITS:
        problems.append(f"unit must be one of {', '.join(UNITS)}")
    subject = payload.get("subject")
    if payload.get("unit") == UNIT_DAY:
        try:
            datetime.strptime(str(subject), "%Y-%m-%d")
        except ValueError:
            problems.append(f"subject {subject!r} is not a local day, YYYY-MM-DD")
    elif not isinstance(subject, str) and not (
        isinstance(subject, list) and subject and all(isinstance(s, str) for s in subject)
    ):
        problems.append("subject must be a string or a non-empty list of line ids")
    head = payload.get("read_head")
    if not isinstance(head, str) or len(head) != SHA256_HEX or not all(c in "0123456789abcdef" for c in head):
        problems.append("read_head must be the record's head, 64 lowercase hex characters")
    count = payload.get("read_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        problems.append("read_count must be how many lines of the unit the model read")
    language = payload.get("language")
    if not isinstance(language, str) or not LANGUAGE.match(language):
        problems.append("language must be a BCP 47 tag, en or nb")
    segments = payload.get("segments")
    if not isinstance(segments, list) or not segments:
        problems.append("segments must be a non-empty list")
    else:
        bad = [i for i, segment in enumerate(segments) if segment_shape(segment) == MALFORMED]
        if bad:
            problems.append(f"segment {bad[0] + 1} is malformed: {NOT_A_SEGMENT}")
    if "supersedes" in payload and (not isinstance(payload["supersedes"], str) or not payload["supersedes"]):
        problems.append("supersedes must be the id of the earlier draft")
    if PROPOSALS in payload:
        proposals = payload[PROPOSALS]
        if not isinstance(proposals, list):
            problems.append("proposals must be a list")
        else:
            bad = [i for i, proposal in enumerate(proposals) if not proposal_shape(proposal)]
            if bad:
                problems.append(f"proposal {bad[0] + 1} is malformed: {NOT_A_PROPOSAL}")
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    return problems


def proposal_shape(proposal: object) -> bool:
    """Whether `proposal` is an event proposal of the documented shape (`NOT_A_PROPOSAL`): nothing
    but its keys, a title, a span in UTC that runs forward, a place that is a non-empty string or
    null, a list of person ids and a non-empty list of line ids."""
    if not isinstance(proposal, dict) or not set(proposal) <= PROPOSAL_KEYS:
        return False
    if proposal.get("kind") != EVENT:
        return False
    title, start, end = proposal.get("title"), proposal.get("start"), proposal.get("end")
    if not isinstance(title, str) or not title.strip():
        return False
    if not all(isinstance(t, str) and UTC_STAMP.match(t) for t in (start, end)):
        return False
    if _instant(str(start)) >= _instant(str(end)):
        return False
    place = proposal.get("place")
    if place is not None and (not isinstance(place, str) or not place.strip()):
        return False
    people, evidence = proposal.get("people"), proposal.get("evidence")
    if not isinstance(people, list) or not all(isinstance(p, str) and p for p in people):
        return False
    return isinstance(evidence, list) and bool(evidence) and all(isinstance(e, str) and e for e in evidence)


# -- the policy it follows ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Allowed:
    """What the `dream` entry of the crossing policy lets a reader show today of what the dream
    wrote: the drafts at or under `max_tier`. `max_tier` is 0 when the file names no entry, when the
    entry has expired, or when the file is not a policy, and `reason` then says which; None when the
    entry is in force."""

    max_tier: int
    reason: str | None = None

    def allows(self, line: Line) -> bool:
        return int(line.get("tier") or 0) <= self.max_tier

    def why_not(self, tier: int, unit: str = UNIT_DAY) -> str:
        """Why a draft of `tier` is withheld, in words, for the Day and `doctor`. A day is dreamed
        again under the entry; a call's synthesis is of the call's tier, so the call is above the
        entry as well and stays home (`synthesis.gate`) until the entry allows it again."""
        if self.reason is not None:
            return self.reason
        found = f"tier {tier}, above max_tier {self.max_tier} of the {policy.DREAM_DESTINATION!r} entry"
        if unit == UNIT_EVENT:
            return f"{found}; the call stays home until the entry allows its tier"
        return f"{found}; `dream --catch-up` dreams the day again under it"


def allowed(root: Path) -> Allowed:
    """The `dream` entry of `root`'s policy as the readers of drafts hold them against it today.
    Never raises: a file that is not a policy withholds every draft and says why, so the Day still
    reads."""
    name = policy.POLICY_FILE.as_posix()
    try:
        entry = policy.dream_today(root)
    except policy.PolicyError as e:
        return Allowed(policy.EXPIRED_TIER, f"{e}; no draft is shown until it is")
    if entry is None:
        return Allowed(
            policy.EXPIRED_TIER, f"{name} names no {policy.DREAM_DESTINATION!r} entry; no draft is shown"
        )
    if entry.expired and entry.until is not None:
        return Allowed(
            policy.EXPIRED_TIER,
            f"the {policy.DREAM_DESTINATION!r} entry expired on {entry.until.isoformat()} and counts as"
            f" max_tier 0; nothing it allowed is shown until {name} gives it a new until",
        )
    return Allowed(entry.max_tier)


def model_of(source: object) -> str:
    """`qwen2.5-7b-instruct` from `model:qwen2.5-7b-instruct`; the source as given when it is not
    a model's."""
    text = str(source)
    return text[len(SOURCE_PREFIX) :] if text.startswith(SOURCE_PREFIX) else text


# -- the standing draft -----------------------------------------------------------------------------------


def of_day(lines: Iterable[Line], retracted: Collection[str], day: str) -> list[Line]:
    """The draft lines of the day, unit `day` and subject `day`, not retracted, in `at` then `seq`
    order; a line whose payload is not a draft's is left out."""
    return by_day(lines, retracted).get(day, [])


def by_day(lines: Iterable[Line], retracted: Collection[str]) -> dict[str, list[Line]]:
    """The draft lines of unit `day`, not retracted, by the day they are about, each day's in `at`
    then `seq` order; a line whose payload is not a draft's (a sealed one this machine cannot open
    among them) is left out."""
    found: dict[str, list[Line]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA:
            continue
        subject = payload.get("subject")
        if payload.get("unit") != UNIT_DAY or not isinstance(subject, str):
            continue
        if str(line["id"]) in retracted:
            continue
        found.setdefault(subject, []).append(line)
    for day in found:
        found[day].sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    return found


def standing(found: Sequence[Line]) -> Line | None:
    """Rule 2: the latest draft not named in a later draft's `supersedes`; None when there is none."""
    if not found:
        return None
    replaced = {
        str((line.get("payload") or {}).get("supersedes"))
        for line in found
        if isinstance((line.get("payload") or {}).get("supersedes"), str)
    }
    kept = [line for line in found if str(line["id"]) not in replaced]
    return kept[-1] if kept else found[-1]


def for_day(
    idx: Index, day: str, tiers: Sequence[int] | None = None, allowed: Allowed | None = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """The Day's `draft` block and its `draft_withheld` row. The draft: the standing draft of `day`
    read through the index, with its evidence checked against the day's lines, its proposals with
    their people's names and the event lines that confirmed them (`confirmations`), how many times the
    day was dreamed and when last; None when the day has none. Through the gate `tiers` when given:
    a draft above it is not seen, as a reader under a ceiling never sees it. Through `allowed`, the
    `dream` entry today, when given: a draft above it is not seen either, and when the standing
    draft is one of those, a reader that holds the whole record (no `tiers`) gets the row that says
    so (`withheld_json`), never its text or its proposals; None otherwise."""
    retracted = retractions(idx.retractions())
    shown, withheld = through(of_day(idx.by_kind(KIND), retracted, day), tiers, allowed)
    latest = standing(shown)
    if latest is None:
        return None, withheld
    lines = idx.day(day)
    on_day = {str(line["id"]) for line in lines if str(line["id"]) not in retracted}
    names: dict[str, str] = {}
    if (latest.get("payload") or {}).get(PROPOSALS):
        names = person_names(resolve.identities_from([*idx.retractions(), *idx.resolutions()]))
    confirmed = confirmations(lines, retracted, str(latest["id"]))
    return day_json(latest, shown, on_day, names, confirmed), withheld


def through(
    found: Sequence[Line], tiers: Sequence[int] | None = None, allowed: Allowed | None = None
) -> tuple[list[Line], dict[str, Any] | None]:
    """The drafts of one unit (a day's, a call's) a reader may show, and the row for a standing draft
    it may not: the one rule `for_day` and `for_transcripts` read through. Through the gate `tiers`
    when given, a draft above it is not seen. Through `allowed`, the `dream` entry today, when given,
    a draft above it is not seen either, and when the standing draft is one of those, a reader that
    holds the whole record (no `tiers`) gets the row that says so (`withheld_json`); None otherwise."""
    if tiers is not None:
        gate = {int(t) for t in tiers}
        found = [line for line in found if int(line.get("tier", 0)) in gate]
    shown = list(found) if allowed is None else [line for line in found if allowed.allows(line)]
    withheld = None
    if allowed is not None and tiers is None:
        top = standing(found)
        if top is not None and not allowed.allows(top):
            withheld = withheld_json(top, allowed)
    return shown, withheld


def withheld_json(line: Line, allowed: Allowed) -> dict[str, Any]:
    """The row a Day carries for a standing draft the `dream` entry no longer allows: the line, its
    tier, the entry's `max_tier` today and why, in words. Nothing of what the draft says."""
    tier = int(line.get("tier") or 0)
    return {
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "tier": tier,
        "max_tier": allowed.max_tier,
        "why": allowed.why_not(tier, str((line.get("payload") or {}).get("unit"))),
    }


def withheld_text(row: Mapping[str, Any]) -> str:
    """`superseded by policy: tier 3, above max_tier 2 of the 'dream' entry; ...`"""
    return f"{SUPERSEDED_BY_POLICY}: {row['why']}"


def withheld(lines: Iterable[Line], retracted: Collection[str], allowed: Allowed) -> list[Line]:
    """The standing draft of every day whose standing draft `allowed` withholds, in day order: what
    `doctor` lists."""
    out = []
    for _day, found in sorted(by_day(lines, retracted).items()):
        top = standing(found)
        if top is not None and not allowed.allows(top):
            out.append(top)
    return out


def person_names(identities: Mapping[resolve.Ref, resolve.Identity]) -> dict[str, str]:
    """entity id → the first label a resolution gives it, for every person the record resolves."""
    found: dict[str, str] = {}
    for who in identities.values():
        if who.entity and who.label and who.type in (None, "person"):
            found.setdefault(who.entity, who.label)
    return found


def confirmations(lines: Iterable[Line], retracted: Collection[str], draft: str) -> dict[int, dict[str, Any]]:
    """number → `{line, seq}` of the event line that confirmed each of the draft's proposals: an
    `event` line, source `owner`, not retracted, whose `extra.from` is the draft and whose `raw_id`
    is `<draft>/<number>`; the latest one when the owner confirmed it twice."""
    found: dict[int, dict[str, Any]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != EVENT_KIND or line.get("source") != OWNER or str(line["id"]) in retracted:
            continue
        extra = payload.get("extra")
        raw_id = str(payload.get("raw_id") or "")
        if not isinstance(extra, dict) or extra.get("from") != draft or not raw_id.startswith(f"{draft}/"):
            continue
        number = raw_id[len(draft) + 1 :]
        if number.isdigit():
            found[int(number)] = {"line": str(line["id"]), "seq": int(line["seq"])}
    return found


def day_json(
    line: Line,
    found: Sequence[Line],
    on_day: Collection[str] | None,
    names: Mapping[str, str] | None = None,
    confirmed: Mapping[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The standing draft as the Day carries it: the line, its source and model, when it was
    written, what it read, its segments each with `supported` and, when a reader holding the
    record found the evidence not on the day, `why`; its proposals (`proposals_json`, the people by
    `names`, each with the event line that `confirmed` it); the ids of the earlier drafts newest
    first, how many times the day was dreamed and the day it was last."""
    payload = line.get("payload") or {}
    tz = ZoneInfo(str(line.get("tz") or "UTC"))
    problems = validate(payload)
    segments = [segment_json(s, on_day) for s in (payload.get("segments") or []) if isinstance(s, dict)]
    parts = (payload.get("extra") or {}).get("parts") if isinstance(payload.get("extra"), dict) else None
    if isinstance(parts, list) and len(parts) == len(segments):
        for segment, part in zip(segments, parts, strict=True):
            segment["part"] = str(part) if part in PARTS else None
    else:
        for segment in segments:
            segment["part"] = None
    earlier = [str(other["id"]) for other in reversed(found) if other["id"] != line["id"]]
    last = max((str(other["at"]) for other in found), default=str(line["at"]))
    return {
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "source": str(line.get("source")),
        "model": model_of(line.get("source")),
        "tier": line.get("tier"),
        "at": str(line["at"]),
        "read_head": payload.get("read_head"),
        "read_count": payload.get("read_count"),
        "language": payload.get("language"),
        "segments": segments,
        "unsupported": sum(1 for s in segments if not s["supported"]),
        "proposals": proposals_json(payload, on_day, tz, names or {}, confirmed or {}),
        "supersedes": payload.get("supersedes"),
        "earlier": earlier,
        "dreamed": len(found),
        "last": _instant(last).astimezone(tz).date().isoformat(),
        "malformed": problems,
    }


def segment_json(
    segment: Mapping[str, Any], on_day: Collection[str] | None, not_on: str = NOT_ON_DAY
) -> dict[str, Any]:
    """One segment with its verdict: supported when every evidence id is a line of the day (when
    the reader holds the day; any id otherwise), or of the unit `on_day` names; else unsupported with
    `why`, `not_on` when an id is not among them."""
    shape = segment_shape(segment)
    text = str(segment.get("text") or "").strip()
    if shape == SUPPORTED:
        evidence = [str(e) for e in segment["evidence"]]
        missing = [e for e in evidence if on_day is not None and e not in on_day]
        if missing:
            return {"text": text, "evidence": evidence, "supported": False, "why": not_on}
        return {"text": text, "evidence": evidence, "supported": True, "why": None}
    if shape == UNSUPPORTED:
        return {"text": text, "evidence": [], "supported": False, "why": None}
    return {"text": text or "(no text)", "evidence": [], "supported": False, "why": NOT_A_SEGMENT}


def proposals_json(
    payload: Mapping[str, Any],
    on_day: Collection[str] | None,
    tz: ZoneInfo,
    names: Mapping[str, str],
    confirmed: Mapping[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """The draft's event proposals as a reader shows them, each numbered by its place in the list
    (a malformed one is left out, and its number with it): the title, the span in UTC and in `tz`,
    the place and where that is in words, the people by id and name, the evidence, `supported` when
    every evidence id is a line of the day (when the reader holds the day), else `why`; and
    `confirmed`, the event line that confirmed it, or None."""
    found = payload.get(PROPOSALS)
    out: list[dict[str, Any]] = []
    for n, proposal in enumerate(found if isinstance(found, list) else [], 1):
        if not proposal_shape(proposal):
            continue
        evidence = [str(e) for e in proposal["evidence"]]
        missing = on_day is not None and any(e not in on_day for e in evidence)
        place = proposal.get("place")
        out.append(
            {
                "number": n,
                "kind": EVENT,
                "title": " ".join(str(proposal["title"]).split()),
                "start": proposal["start"],
                "end": proposal["end"],
                "start_local": _instant(proposal["start"]).astimezone(tz).isoformat(timespec="seconds"),
                "end_local": _instant(proposal["end"]).astimezone(tz).isoformat(timespec="seconds"),
                "place": place,
                "where": where_of(place),
                "people": [{"id": p, "name": names.get(p)} for p in proposal["people"]],
                "evidence": evidence,
                "supported": not missing,
                "why": NOT_ON_DAY if missing else None,
                "confirmed": confirmed.get(n),
            }
        )
    return out


def where_of(place: object) -> str | None:
    """A proposal's place in words: a named place's name; an observed place's coordinates."""
    if not isinstance(place, str) or not place:
        return None
    return place[len(CLUSTER) :] if place.startswith(CLUSTER) else place


def cluster_coordinates(place: str) -> tuple[float, float] | None:
    """(lat, lon) of an observed place's id, `place:59.9200,10.7400`; None for any other place."""
    if not place.startswith(CLUSTER):
        return None
    try:
        lat, lon = (float(part) for part in place[len(CLUSTER) :].split(","))
    except ValueError:
        return None
    return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None


# -- a transcript's synthesis ------------------------------------------------------------------------------


def subject_ids(payload: Mapping[str, Any]) -> list[str]:
    """The ids a draft's `subject` names: the list, or the one string; empty for anything else."""
    subject = payload.get("subject")
    if isinstance(subject, str):
        return [subject]
    if isinstance(subject, list):
        return [str(s) for s in subject if isinstance(s, str)]
    return []


def by_transcript(lines: Iterable[Line], retracted: Collection[str]) -> dict[str, list[Line]]:
    """The syntheses, as `by_day` gives the days' drafts: the draft lines of unit `event` whose
    subject is one line's id alone (a transcript's), not retracted, by that id, each one's in `at`
    then `seq` order; a line whose payload is not a draft's is left out."""
    found: dict[str, list[Line]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA or payload.get("unit") != UNIT_EVENT:
            continue
        subject = subject_ids(payload)
        if len(subject) != 1 or str(line["id"]) in retracted:
            continue
        found.setdefault(subject[0], []).append(line)
    for transcript in found:
        found[transcript].sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    return found


def for_transcripts(
    idx: Index, transcripts: Sequence[str], tiers: Sequence[int] | None = None, allowed: Allowed | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The Day's `syntheses` and its `syntheses_withheld` rows, read through the rule `for_day` reads
    a day's draft through (`through`). The syntheses: the standing synthesis of each of these
    transcript lines that has one, in the order given, each with its evidence checked against its
    transcript (`synthesis_json`). Through the gate `tiers` when given, a synthesis above it is not
    seen; through `allowed`, the `dream` entry today, one above the entry is not seen either, and a
    reader that holds the whole record gets the row for a standing synthesis the entry withholds, the
    transcript's id first (`withheld_json`), never its text."""
    if not transcripts:
        return [], []
    by = by_transcript(idx.by_kind(KIND), retractions(idx.retractions()))
    out, held = [], []
    for transcript in transcripts:
        shown, withheld = through(by.get(transcript, []), tiers, allowed)
        latest = standing(shown)
        if latest is not None:
            out.append(synthesis_json(latest, shown, transcript))
        if withheld is not None:
            held.append({"transcript": transcript, **withheld})
    return out, held


def synthesis_json(line: Line, found: Sequence[Line], transcript: str) -> dict[str, Any]:
    """A transcript's standing synthesis as the Day carries it: the transcript it is of, the draft
    line, its source and model, what it read, its segments (`synthesis_segments`), how many of each
    part and how many unsupported, the earlier syntheses newest first and how many there were."""
    payload = line.get("payload") or {}
    tz = ZoneInfo(str(line.get("tz") or "UTC"))
    segments = synthesis_segments(payload, {transcript})
    found_extra = payload.get("extra")
    extra: Mapping[str, Any] = found_extra if isinstance(found_extra, dict) else {}
    last = max((str(other["at"]) for other in found), default=str(line["at"]))
    return {
        "transcript": transcript,
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "source": str(line.get("source")),
        "model": model_of(line.get("source")),
        "tier": line.get("tier"),
        "at": str(line["at"]),
        "read_head": payload.get("read_head"),
        "language": payload.get("language"),
        "utterances": extra.get("utterances"),
        "segments": segments,
        "counts": {part: sum(1 for s in segments if s["part"] == part) for part in SYNTHESIS_PARTS},
        "unsupported": sum(1 for s in segments if not s["supported"]),
        "supersedes": payload.get("supersedes"),
        "earlier": [str(other["id"]) for other in reversed(found) if other["id"] != line["id"]],
        "synthesized": len(found),
        "last": _instant(last).astimezone(tz).date().isoformat(),
        "malformed": validate(payload),
    }


def synthesis_segments(
    payload: Mapping[str, Any], transcript: Collection[str] | None
) -> list[dict[str, Any]]:
    """The segments of a synthesis with their verdict (`segment_json`, the transcript's id the only
    evidence a segment may name when `transcript` is given) and what `extra.segments` keeps of each:
    `part`, `utterances` (`[{n, offset}]`), `assignee` and `due` (`{phrase, date}`), each None or
    empty when the line does not say."""
    found = payload.get("segments")
    raw = [s for s in found if isinstance(s, dict)] if isinstance(found, list) else []
    found_extra = payload.get("extra")
    extra: Mapping[str, Any] = found_extra if isinstance(found_extra, dict) else {}
    details = extra.get("segments")
    if not isinstance(details, list) or len(details) != len(raw):
        details = [{}] * len(raw)
    out = []
    for segment, detail in zip(raw, details, strict=True):
        shown = segment_json(segment, transcript, NOT_THE_TRANSCRIPT)
        detail = detail if isinstance(detail, dict) else {}
        part = detail.get("part")
        shown["part"] = part if part in SYNTHESIS_PARTS else None
        shown["utterances"] = [
            {"n": u["n"], "offset": u.get("offset") if isinstance(u.get("offset"), str) else None}
            for u in detail.get("utterances") or []
            if isinstance(u, dict) and isinstance(u.get("n"), int) and not isinstance(u.get("n"), bool)
        ]
        assignee = detail.get("assignee")
        shown["assignee"] = assignee if isinstance(assignee, str) and assignee else None
        due = detail.get("due")
        shown["due"] = (
            {
                "phrase": str(due.get("phrase") or ""),
                "date": due.get("date") if isinstance(due.get("date"), str) else None,
            }
            if isinstance(due, dict) and due.get("phrase")
            else None
        )
        out.append(shown)
    return out


def synthesis_summary(block: Mapping[str, Any]) -> str:
    """`synthesis · 1 action, 2 topics, 1 decision, 1 open thread, 1 personal · model:qwen2.5-7b-instruct`,
    the Day's one row for a synthesis, collapsed; with `· N unsupported` when any is."""
    counts = block.get("counts") or {}
    found = [
        f"{n} {SYNTHESIS_NOUNS[part][0 if n == 1 else 1]}"
        for part in SYNTHESIS_PARTS
        if (n := int(counts.get(part) or 0))
    ]
    parts = ["synthesis", ", ".join(found) or "no items"]
    if block.get("unsupported"):
        parts.append(f"{block['unsupported']} unsupported")
    if block.get("malformed"):
        parts.append("malformed")
    parts.append(str(block["source"]))
    return DOT.join(parts)


def is_withheld(block: Mapping[str, Any]) -> bool:
    """Whether a block of the Day's is the row of a draft the `dream` entry withholds (`withheld_json`:
    no segments, the reason why) rather than a draft it shows."""
    return "segments" not in block and "why" in block


def synthesis_row(block: Mapping[str, Any]) -> str:
    """The one row under a call on the Day: its synthesis, collapsed (`synthesis_summary`), or, for a
    synthesis the `dream` entry withholds, `superseded by policy` and why (`withheld_text`)."""
    return withheld_text(block) if is_withheld(block) else synthesis_summary(block)


def synthesis_rows(segments: Sequence[Mapping[str, Any]], indent: str = "    ") -> Iterator[str]:
    """The segments of a synthesis, one per row: the part's word, the text, an action's assignee and
    due hint (`assignment_text`), then where in the call it rests (`where_text`); an unsupported one
    starts with `~` and ends with the word."""
    for segment in segments:
        label = SYNTHESIS_LABELS.get(str(segment.get("part")), "")
        mark = "  " if segment["supported"] else "~ "
        assigned = assignment_text(segment)
        who = f"  {assigned}" if assigned else ""
        if segment["supported"]:
            tail = f"[{where_text(segment)}]"
        else:
            tail = UNSUPPORTED if not segment.get("why") else f"{UNSUPPORTED}: {segment['why']}"
        yield f"{indent}{mark}{label:<9} {segment['text']}{who}  {tail}"


def assignment_text(segment: Mapping[str, Any]) -> str:
    """`→ Ola Nordmann · due by Friday (2026-06-12?)`: an action's assignee and due hint, the date a
    reading of the words (SPEC §3.2.10 rule 4); empty when the segment names neither."""
    parts = []
    if segment.get("assignee"):
        parts.append(f"→ {segment['assignee']}")
    due = segment.get("due")
    if due:
        parts.append(f"due {due['phrase']}" + (f" ({due['date']}?)" if due.get("date") else ""))
    return DOT.join(parts)


def where_text(segment: Mapping[str, Any]) -> str:
    """Where in the call a segment rests: `02:10, 20:05`, `u3, u17` when the recording gives no time,
    `the transcript` when it rests on the line and no utterance of it."""
    return ", ".join(utterance_text(u) for u in segment.get("utterances") or []) or WHOLE


def utterance_text(utterance: Mapping[str, Any]) -> str:
    """`20:05` where the recording gives the utterance's time, else `u17`."""
    return str(utterance["offset"]) if utterance.get("offset") else f"u{utterance['n']}"


# -- text ------------------------------------------------------------------------------------------------


def head_text(draft: Mapping[str, Any], word: bool = True) -> str:
    """`draft · model:qwen2.5-7b-instruct · read at bb97e90d · 5 lines · dreamed 2×, last on
    2026-06-14 · 1 unsupported`; without the leading word when the row's label says it."""
    head = str(draft.get("read_head") or "")[:HEAD_SHORT]
    n = draft.get("read_count")
    parts = [
        *(["draft"] if word else []),
        str(draft["source"]),
        f"read at {head}",
        f"{n} line{'s' if n != 1 else ''}",
        f"dreamed {draft['dreamed']}×, last on {draft['last']}",
    ]
    if draft["unsupported"]:
        parts.append(f"{draft['unsupported']} unsupported")
    proposals = draft.get("proposals") or []
    if proposals:
        confirmed = sum(1 for p in proposals if p.get("confirmed"))
        n = len(proposals)
        parts.append(
            f"{n} proposed event{'s' if n != 1 else ''}" + (f", {confirmed} confirmed" if confirmed else "")
        )
    if draft.get("malformed"):
        parts.append("malformed: " + "; ".join(draft["malformed"]))
    return DOT.join(parts)


def rows(draft: Mapping[str, Any], indent: str = "    ") -> Iterator[str]:
    """The segments, one per row: the part's word, the text, then the evidence ids shortened; an
    unsupported one starts with `~` and ends with `unsupported` (and why, when a reader found
    out), never run into the prose around it."""
    for segment in draft["segments"]:
        label = PART_LABELS.get(str(segment.get("part")), "") if segment.get("part") else ""
        mark = "  " if segment["supported"] else "~ "
        if segment["supported"]:
            tail = "[" + ", ".join(short_id(e) for e in segment["evidence"]) + "]"
        else:
            tail = UNSUPPORTED if not segment.get("why") else f"{UNSUPPORTED}: {segment['why']}"
        yield f"{indent}{mark}{label:<9} {segment['text']}  {tail}"
    yield from proposal_rows(draft.get("proposals") or [], indent)


def proposal_rows(proposals: Iterable[Mapping[str, Any]], indent: str = "    ") -> Iterator[str]:
    """One row per proposed event, after the segments: `event N`, the span, the title, the place and
    the people; then `proposed` and the evidence, set apart with a leading `?` (greyed on the page),
    or `confirmed as #seq` once the owner accepted it, or `~` and `unsupported` when a reader found
    its evidence not on the day."""
    for p in proposals:
        label = f"event {p['number']}"
        if p.get("confirmed"):
            mark, tail = "  ", f"confirmed as #{p['confirmed']['seq']}"
        elif not p["supported"]:
            mark, tail = "~ ", f"{UNSUPPORTED}: {p['why']}" if p.get("why") else UNSUPPORTED
        else:
            mark, tail = "? ", "proposed  [" + ", ".join(short_id(e) for e in p["evidence"]) + "]"
        yield f"{indent}{mark}{label:<9} {proposal_text(p)}  {tail}"


def proposal_text(p: Mapping[str, Any]) -> str:
    """The span (the two clocks with an en dash between), the title, the place, the people:
    `19:30` to `22:10  Dinner with Kari Nordmann · Bistro Eksempel · with Kari Nordmann`."""
    clock = f"{str(p['start_local'])[11:16]}{EN_DASH}{str(p['end_local'])[11:16]}"
    parts = [f"{clock}  {p['title']}"]
    if p.get("where"):
        parts.append(str(p["where"]))
    people = [str(who.get("name") or who["id"]) for who in p.get("people") or []]
    if people:
        parts.append("with " + ", ".join(people))
    return DOT.join(parts)


def short_id(line_id: str) -> str:
    return f"…{line_id[-ID_SHORT:]}" if len(line_id) > ID_SHORT else line_id


def row_text(payload: Mapping[str, Any]) -> str:
    """The row `show` prints for a draft line: `draft of day 2026-06-13 · 5 lines read at bb97e90d
    · 7 segments, 1 unsupported`."""
    found = payload.get("segments")
    segments: list[Any] = found if isinstance(found, list) else []
    unsupported = sum(1 for s in segments if segment_shape(s) != SUPPORTED)
    head = str(payload.get("read_head") or "")[:HEAD_SHORT]
    subject = payload.get("subject")
    subject_text = ", ".join(subject) if isinstance(subject, list) else str(subject)
    n = payload.get("read_count")
    parts = [
        f"draft of {payload.get('unit')} {subject_text}",
        f"{n} line{'s' if n != 1 else ''} read at {head}",
        f"{len(segments)} segment{'s' if len(segments) != 1 else ''}"
        + (f", {unsupported} unsupported" if unsupported else ""),
    ]
    proposals = payload.get(PROPOSALS)
    if isinstance(proposals, list) and proposals:
        parts.append(f"{len(proposals)} proposed event{'s' if len(proposals) != 1 else ''}")
    if payload.get("supersedes"):
        parts.append("supersedes an earlier draft")
    return DOT.join(parts)


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
