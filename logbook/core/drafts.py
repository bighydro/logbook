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
the ids it read (`read_ids_sha256`), which `dream --catch-up` compares, and the version of the
crossing entry it was dreamed under (`policy_version`, `policy.version`: the SHA-256 of the entry's
`max_tier`, `until` and `model`).

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
word, as it hides every line above its gate. `doctor` lists the days whose standing draft is withheld
(`withheld`), and `dream --catch-up` dreams them again under the entry when it allows any tier."""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from . import policy
from .chain import Line
from .index import Index
from .store import retractions

KIND = "draft"
SCHEMA = "draft/v1"
UNIT_DAY = "day"
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
HEAD_SHORT = 8  # `read at bb97e90d`: the first 8 hex of the head
ID_SHORT = 8  # an evidence id shortened to its last 8 characters in text
LANGUAGE = re.compile(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*\Z")  # a BCP 47 tag, loosely
SHA256_HEX = 64
NOT_ON_DAY = "evidence names a line that is not on the day"
NOT_ON_JOURNEY = "evidence names a line that is not of the journey"
UNIT_JOURNEY = "journey"
NOT_A_SEGMENT = "a segment is {text, evidence} or {text, unsupported: true}, nothing else"
SUPERSEDED_BY_POLICY = "superseded by policy"  # the Day's row for a draft the dream entry no longer allows
DOT = " · "


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
    if "extra" in payload and not isinstance(payload["extra"], dict):
        problems.append("extra must be an object")
    return problems


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

    def why_not(self, tier: int) -> str:
        """Why a draft of `tier` is withheld, in words, for the Day and `doctor`."""
        if self.reason is not None:
            return self.reason
        return (
            f"tier {tier}, above max_tier {self.max_tier} of the {policy.DREAM_DESTINATION!r} entry;"
            " `dream --catch-up` dreams the day again under it"
        )


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


def by_unit(lines: Iterable[Line], retracted: Collection[str], unit: str) -> dict[str, list[Line]]:
    """The draft lines of another unit than the day (`by_day`'s), not retracted, by each subject
    they name, each subject's in `at` then `seq` order: a `subject` that is a string is one, an
    array names every entry in it (a journey's draft names the lines or the derived id it is about,
    `trip:<first day>:<last day>`, RFC 0036); a line whose payload is not a draft's is left out."""
    found: dict[str, list[Line]] = {}
    for line in lines:
        payload = line.get("payload") or {}
        if line.get("kind") != KIND or payload.get("schema") != SCHEMA or payload.get("unit") != unit:
            continue
        if str(line["id"]) in retracted:
            continue
        named = payload.get("subject")
        subjects = [named] if isinstance(named, str) else named if isinstance(named, list) else []
        for subject in dict.fromkeys(s for s in subjects if isinstance(s, str)):
            found.setdefault(subject, []).append(line)
    for subject in found:
        found[subject].sort(key=lambda line: (str(line["at"]), int(line["seq"])))
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
    read through the index, with its evidence checked against the day's lines, how many times the
    day was dreamed and when last; None when the day has none. Through the gate `tiers` when given:
    a draft above it is not seen, as a reader under a ceiling never sees it. Through `allowed`, the
    `dream` entry today, when given: a draft above it is not seen either, and when the standing
    draft is one of those, a reader that holds the whole record (no `tiers`) gets the row that says
    so (`withheld_json`), never its text; None otherwise."""
    retracted = retractions(idx.retractions())
    found = of_day(idx.by_kind(KIND), retracted, day)
    if tiers is not None:
        gate = {int(t) for t in tiers}
        found = [line for line in found if int(line.get("tier", 0)) in gate]
    shown = found if allowed is None else [line for line in found if allowed.allows(line)]
    withheld = None
    if allowed is not None and tiers is None:
        top = standing(found)
        if top is not None and not allowed.allows(top):
            withheld = withheld_json(top, allowed)
    latest = standing(shown)
    if latest is None:
        return None, withheld
    on_day = {str(line["id"]) for line in idx.day(day) if str(line["id"]) not in retracted}
    return day_json(latest, shown, on_day), withheld


def withheld_json(line: Line, allowed: Allowed) -> dict[str, Any]:
    """The row a Day carries for a standing draft the `dream` entry no longer allows: the line, its
    tier, the entry's `max_tier` today and why, in words. Nothing of what the draft says."""
    tier = int(line.get("tier") or 0)
    return {
        "line": str(line["id"]),
        "seq": int(line["seq"]),
        "tier": tier,
        "max_tier": allowed.max_tier,
        "why": allowed.why_not(tier),
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


def day_json(
    line: Line, found: Sequence[Line], on_day: Collection[str] | None, missing: str = NOT_ON_DAY
) -> dict[str, Any]:
    """The standing draft as the Day carries it: the line, its source and model, when it was
    written, what it read, its segments each with `supported` and, when a reader holding the
    record found the evidence not on the day, `why`; the ids of the earlier drafts newest first,
    how many times the day was dreamed and the day it was last. Another unit's page reads its
    draft the same way, `on_day` the unit's lines and `missing` its own words for an id outside
    them (`NOT_ON_JOURNEY`)."""
    payload = line.get("payload") or {}
    tz = ZoneInfo(str(line.get("tz") or "UTC"))
    problems = validate(payload)
    segments = [
        segment_json(s, on_day, missing) for s in (payload.get("segments") or []) if isinstance(s, dict)
    ]
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
        "supersedes": payload.get("supersedes"),
        "earlier": earlier,
        "dreamed": len(found),
        "last": _instant(last).astimezone(tz).date().isoformat(),
        "malformed": problems,
    }


def segment_json(
    segment: Mapping[str, Any], on_day: Collection[str] | None, missing: str = NOT_ON_DAY
) -> dict[str, Any]:
    """One segment with its verdict: supported when every evidence id is a line of the day (when
    the reader holds the day; any id otherwise); else unsupported with `why` (`missing`)."""
    shape = segment_shape(segment)
    text = str(segment.get("text") or "").strip()
    if shape == SUPPORTED:
        evidence = [str(e) for e in segment["evidence"]]
        if any(on_day is not None and e not in on_day for e in evidence):
            return {"text": text, "evidence": evidence, "supported": False, "why": missing}
        return {"text": text, "evidence": evidence, "supported": True, "why": None}
    if shape == UNSUPPORTED:
        return {"text": text, "evidence": [], "supported": False, "why": None}
    return {"text": text or "(no text)", "evidence": [], "supported": False, "why": NOT_A_SEGMENT}


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
    if payload.get("supersedes"):
        parts.append("supersedes an earlier draft")
    return DOT.join(parts)


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
