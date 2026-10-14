"""The synthesis of a transcript (`logbook transcript synthesize ID|--day DAY`): a model reads one
`transcript/v1` line, a call, and writes one `draft/v1` line about it (RFC 0036, `logbook.core.drafts`),
unit `event`, subject the transcript line's id: the actions proposed, on top, each with its assignee and
due hint; the topics, consolidated across the whole call; the decisions, settled and not merely
discussed; the open threads; and a short personal part. Every item points at the utterances it rests
on, or is marked unsupported. A synthesis is a proposal; the transcript is the record.

It runs on the dream's engine (`logbook.contrib.dream`): the same `dream` entry of
`policy/crossing.json` (its `max_tier` the ceiling, its `until`, its optional `model`), the same
endpoint (`LOGBOOK_DREAM_ENDPOINT`, `LOGBOOK_DREAM_MODEL`, `LOGBOOK_DREAM_KEY`), the same reading of
the answer and the same refusal when more than 30 % of it rests on nothing. A transcript whose tier is
above the ceiling stays on this machine: nothing of it is read or sent (`HeldBack`).

What the model sees (`material`) is the call and nothing else: a header (reference `T`: the title,
the provider, the day, the start and end, the participants by name, never an address) and every
utterance in order as `transcripts.turns_of` reads it from the attachment store, each with its
reference `U1`, `U2`, ..., its speaker as the transcript labels them and, when the recording says,
its time into the call (`20:05`). The prompt is `synthesis-prompt.md` beside this module
(docs/synthesis-prompt.md explains it): a fixed schema of five parts, and the work-only rule. The
filter is the prompt's: the whole call reaches the model, and the model is told that anything
personal goes to the short personal part and nowhere else; no code decides what is personal.

**Evidence.** A transcript's utterances are not lines of their own (RFC 0004 keeps the text in one
attachment), so the `evidence` of every supported segment is the transcript line's id, and which
utterances it rests on is kept beside the segments under `extra.segments` (`{part, utterances: [{n,
offset}], assignee?, due?}`, `logbook.core.drafts`). Every reference of the answer is checked: `T`,
the transcript's own id, or `U<n>` for an utterance the material gave; an item that cites anything
else, alone or beside good references, is unsupported (RFC 0036 rule 6). Topics the model names twice
are one topic (`merge`): their texts joined, their utterances united.

The draft's tier is the transcript's (the one line read; `read_count` 1), `read_head` the head when the
model read, and like every draft it records the version of the entry it was made under
(`extra.policy_version`, `policy.version`). The whole run holds the writer lock and the head is read
again before the append: `HeadMoved` and nothing written when it moved. A transcript the same model
synthesized under the same prompt and the same entry is unchanged: nothing is sent and the standing
synthesis is shown (`--again` asks once more); another model, another entry, or `--again`, writes a
new line whose `supersedes` names the standing one. A synthesis is a draft and follows the policy as
every draft does: the readers withhold one above the entry today (`drafts.for_transcripts`).
`catch_up` synthesizes the transcripts of the days `dream --catch-up` covers that have no synthesis
yet, or whose synthesis was made under another version of the entry, what the 06:00 close runs."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from string import Template
from typing import Any

from ..core import day_start, drafts, policy
from ..core.chain import Line
from ..core.day import WEEKDAYS
from ..core.export import parse_day
from ..core.index import Index
from ..core.store import HeadMoved, Logbook, now_utc, retractions
from ..core.transcripts import Turn, turns_of
from . import dream, model_client
from .dream import AnswerError, DreamError, Outcome
from .model_client import Transport
from .promises import due_of

KIND = "transcript"
PROMPT_FILE = Path(__file__).with_name("synthesis-prompt.md")
PROMPT_NAME = "transcript-synthesis/1"  # kept under `extra.prompt`, so a draft says which prompt wrote it
TRANSCRIPT_REF = "T"
UTTERANCE = re.compile(r"U([1-9][0-9]*)\Z")
UTTERANCE_CHARS = 2000  # one utterance's text in the material, at most; every utterance is given
SUFFIX_MIN = 8  # the Day and `show` shorten an id to its last 8 characters
ISO_DAY = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
SYNTHESIZED, DRY_RUN, UNCHANGED = "synthesized", "dry run", "unchanged"
HELD_BACK, NO_TEXT, REFUSED = "held back", "no text", "refused"
STATES = (SYNTHESIZED, DRY_RUN, UNCHANGED, HELD_BACK, NO_TEXT, REFUSED)  # the order a summary counts them
HEAD_MOVED = (
    "the record's head moved from {was} to {now} while the model read the transcript, so the draft would"
    " not say what it read; nothing was written, synthesize it again"
)
PROPOSAL = "a synthesis is a proposal: the transcript is the record"


class HeldBack(DreamError):
    """The transcript's tier is above the `dream` entry's ceiling: it stays home, nothing is sent."""


class NoText(DreamError):
    """The transcript's text is not in the attachment store, or holds no utterance."""


@dataclass
class Material:
    """What the model is given about one transcript, and what the record keeps about that reading."""

    transcript: Line
    day: str
    tier: int  # the transcript's: the draft's tier
    read_head: str
    language: str
    turns: list[Turn]
    data: dict[str, Any] = field(default_factory=dict)  # the JSON the prompt carries


@dataclass(frozen=True)
class Synthesis:
    """What a synthesis of one transcript came to: `state` (`synthesized`, `dry run`, `unchanged`),
    the draft line written or, unchanged, the standing one (None under `--dry-run`), its payload, its
    tier, the prompt's messages and the model's raw answer (empty when nothing was sent)."""

    transcript: Line
    state: str
    line: Line | None
    payload: dict[str, Any]
    tier: int
    messages: list[dict[str, str]] = field(default_factory=list)
    answer: str = ""


@dataclass(frozen=True)
class Tried:
    """One transcript of a day: what came of it, and the synthesis or the reason it has none."""

    transcript: Line
    state: str
    synthesis: Synthesis | None = None
    detail: str = ""


# -- naming a transcript ------------------------------------------------------------------------------------


def find(lb: Logbook, name: str) -> Line:
    """The transcript line `name` names: its id, `#seq`, or the last eight or more characters of its id
    as the Day and `show` shorten it (`…a1b2c3d4`). `DreamError` when it names no line, a line that is
    not a transcript, or more than one transcript."""
    text = name.strip().lstrip("…")
    with lb.index() as idx:
        if text.startswith("#") and text[1:].isdigit():
            line = idx.by_seq(int(text[1:]))
        else:
            line = idx.by_id(text)
            if line is None and len(text) >= SUFFIX_MIN:
                found = [t for t in idx.by_kind(KIND) if str(t["id"]).endswith(text)]
                if len(found) > 1:
                    raise DreamError(f"{name} ends {len(found)} transcript ids; give more of the id")
                line = found[0] if found else None
    if line is None:
        raise DreamError(
            f"no line {name} in the record; name a transcript by its id, #seq or the last 8 characters"
            " of its id"
        )
    if line.get("kind") != KIND:
        raise DreamError(f"line {name} is a {line.get('kind')} line, not a transcript")
    return line


def of_day(lb: Logbook, day: str) -> list[Line]:
    """The transcripts standing on a local day (not retracted, not superseded), in `at` order."""
    day = parse_day(day).isoformat()
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        superseded = idx.superseded(KIND)
        found = [
            line
            for line in idx.by_kind(KIND, day, day)
            if str(line["id"]) not in retracted and str(line["id"]) not in superseded
        ]
    return sorted(found, key=lambda line: (str(line["at"]), int(line["seq"])))


def title_of(line: Line) -> str:
    title = (line.get("payload") or {}).get("title")
    return str(title) if isinstance(title, str) and title.strip() else "a recording"


def head_of(lb: Logbook, line: Line) -> str:
    """`2026-06-10 10:00 “Yard plans”`: a transcript as a row names it, in the record's zone."""
    bounds = day_start.of(lb.meta)
    at = _instant(str(line["at"])).astimezone(bounds.zone)
    return f"{bounds.day_of(str(line['at']))} {at:%H:%M} “{title_of(line)}”"


# -- the material -------------------------------------------------------------------------------------------


def gate(line: Line, found: policy.Ceiling) -> None:
    """`HeldBack` when the transcript's tier is above the entry's ceiling: nothing of it is read."""
    tier = int(line.get("tier") or 0)
    if tier > found.max_tier:
        raise HeldBack(
            f"the transcript is tier {tier} and the {policy.DREAM_DESTINATION!r} entry's max_tier is"
            f" {found.max_tier}, so it stays on this machine; nothing was sent"
        )


def material(lb: Logbook, line: Line, found: policy.Ceiling) -> Material:
    """The call as the model is given it: the header and every utterance with its reference, under
    the entry's ceiling (`gate` first). `NoText` when the text is not in the store or is empty."""
    gate(line, found)
    turns = turns_of(lb, line)
    if turns is None:
        raise NoText(
            "its text is not in the attachment store (or is sealed and this machine has no identity);"
            " nothing to synthesize"
        )
    if not turns:
        raise NoText("its text holds no utterance; nothing to synthesize")
    payload = line.get("payload") or {}
    bounds = day_start.of(lb.meta)
    at = _instant(str(line["at"]))
    end = _instant(str(line["end"])) if line.get("end") else None
    local = at.astimezone(bounds.zone)
    day = bounds.day_of(str(line["at"]))
    found_names = payload.get("participants")
    participants = [
        str(p["name"])
        for p in (found_names if isinstance(found_names, list) else [])
        if isinstance(p, dict) and isinstance(p.get("name"), str) and p["name"].strip()
    ]
    header: dict[str, Any] = {
        "ref": TRANSCRIPT_REF,
        "title": title_of(line),
        "provider": str(payload.get("provider") or line.get("source") or ""),
        "day": day,
        "weekday": WEEKDAYS[date.fromisoformat(day).weekday()],
        "tz": str(lb.meta["timezone"]),
        "start": f"{local:%H:%M}",
        "end": f"{end.astimezone(bounds.zone):%H:%M}" if end is not None else None,
        "minutes": round((end - at).total_seconds() / 60) if end is not None else None,
        "participants": participants,
        "utterances": len(turns),
    }
    utterances = []
    for n, turn in enumerate(turns, 1):
        said: dict[str, Any] = {"ref": f"U{n}"}
        if turn.start_s is not None:
            said["at"] = offset_text(turn.start_s)
        said["speaker"] = turn.speaker or "unknown"
        said["text"] = _clip(turn.text, UTTERANCE_CHARS)
        utterances.append(said)
    return Material(
        transcript=line,
        day=day,
        tier=int(line.get("tier") or 1),
        read_head=str(lb.meta["head"]),
        language=dream.language_of([header["title"], *(t.text for t in turns)]),
        turns=turns,
        data={"transcript": header, "utterances": utterances},
    )


def offset_text(seconds: float) -> str:
    """`02:10`, or `1:02:10` past the first hour: where an utterance is in the recording."""
    whole = max(int(seconds), 0)
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _clip(text: str, chars: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= chars else text[: chars - 1] + "…"


# -- the prompt and the answer ------------------------------------------------------------------------------


def prompt(made: Material) -> list[dict[str, str]]:
    """The two messages the model gets: the prompt file with the call and the language filled in, and
    the material as JSON."""
    header = made.data["transcript"]
    system = Template(PROMPT_FILE.read_text(encoding="utf-8")).safe_substitute(
        title=header["title"],
        weekday=header["weekday"],
        day=header["day"],
        tz=header["tz"],
        utterances=str(header["utterances"]),
        language=made.language,
        language_name=dream.LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


@dataclass
class _Item:
    part: str
    text: str
    utterances: list[int]
    supported: bool
    topic: str | None = None
    assignee: str | None = None
    due: str | None = None


def segments_of(
    found: Mapping[str, Any], made: Material
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The answer's segments in the parts' order, actions on top, and what `extra.segments` keeps of
    each. A supported segment is `{text, evidence: [the transcript's id]}`, an unsupported one `{text,
    unsupported: true}`; an item without text is dropped; topics named twice are one (`merge`). More
    than `dream.UNSUPPORTED_SHARE` unsupported, or no segment at all, is `AnswerError`."""
    items: list[_Item] = []
    for part in drafts.SYNTHESIS_PARTS:
        raw = found.get(part)
        if not isinstance(raw, list):
            continue
        for value in raw:
            item = _item(part, value, made)
            if item is not None:
                items.append(item)
    items = merge(items)
    if not items:
        raise AnswerError("the model's answer holds no item with text; nothing was written")
    unsupported = sum(1 for item in items if not item.supported)
    if unsupported / len(items) > dream.UNSUPPORTED_SHARE:
        raise AnswerError(
            f"{unsupported} of {len(items)} segments rest on no line of the transcript, more than"
            f" {round(dream.UNSUPPORTED_SHARE * 100)} %; the answer is refused and nothing was written"
        )
    transcript = str(made.transcript["id"])
    day = date.fromisoformat(made.day)
    segments: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    for item in items:
        text = f"{item.topic}: {item.text}" if item.topic else item.text
        segment = (
            {"text": text, "evidence": [transcript]}
            if item.supported
            else {"text": text, "unsupported": True}
        )
        segments.append(segment)
        detail: dict[str, Any] = {
            "part": item.part,
            "utterances": [_utterance(n, made.turns) for n in item.utterances] if item.supported else [],
        }
        if item.part == "actions":
            detail["assignee"] = item.assignee
            due = None if item.due is None else {"phrase": item.due, "date": _due_date(item.due, day)}
            detail["due"] = due
        details.append(detail)
    return segments, details


def _item(part: str, value: object, made: Material) -> _Item | None:
    if isinstance(value, str):
        value = {"text": value}
    if not isinstance(value, dict):
        return None
    text = " ".join(str(value.get("text") or "").split())
    if not text:
        return None
    evidence = value.get("evidence")
    refs = [evidence] if isinstance(evidence, str) else evidence if isinstance(evidence, list) else []
    transcript = str(made.transcript["id"])
    utterances: list[int] = []
    whole = foreign = False
    for ref in refs:
        key = str(ref).strip()
        m = UTTERANCE.match(key)
        if key in (TRANSCRIPT_REF, transcript):
            whole = True
        elif m is not None and int(m.group(1)) <= len(made.turns):
            if int(m.group(1)) not in utterances:
                utterances.append(int(m.group(1)))
        else:
            foreign = True  # a reference the material never gave: the item rests on nothing it can show
    supported = (bool(utterances) or whole) and not foreign and value.get("unsupported") is not True
    topic = " ".join(str(value.get("topic") or "").split()) if part == "topics" else ""
    return _Item(
        part=part,
        text=text,
        utterances=sorted(utterances) if supported else [],
        supported=supported,
        topic=topic or None,
        assignee=_words(value.get("assignee")) if part == "actions" else None,
        due=_words(value.get("due")) if part == "actions" else None,
    )


def merge(items: list[_Item]) -> list[_Item]:
    """Topics named twice, case and spacing aside, are one topic: the first keeps its place, the
    later one's text is added to it and its utterances joined to its own. Only supported topics are
    merged, so a text that rests on nothing never joins one that rests on something."""
    out: list[_Item] = []
    seen: dict[str, _Item] = {}
    for item in items:
        key = (item.topic or "").casefold()
        first = seen.get(key) if item.part == "topics" and key and item.supported else None
        if first is not None:
            if item.text not in first.text:
                first.text = f"{first.text} {item.text}"
            first.utterances = sorted({*first.utterances, *item.utterances})
            continue
        if item.part == "topics" and key and item.supported:
            seen[key] = item
        out.append(item)
    return out


def _words(value: object) -> str | None:
    text = " ".join(str(value).split()) if isinstance(value, str) else ""
    return None if not text or text.casefold() in ("null", "none", "nobody", "unknown") else text


def _utterance(n: int, turns: Sequence[Turn]) -> dict[str, Any]:
    start = turns[n - 1].start_s
    return {"n": n} if start is None else {"n": n, "offset": offset_text(start)}


def _due_date(phrase: str, day: date) -> str | None:
    """The day a due phrase names, counted from the day of the call (`promises.due_of`, SPEC §3.2.10
    rule 4); a date the model already wrote as `YYYY-MM-DD` is taken as it is."""
    if ISO_DAY.match(phrase):
        return phrase
    found = due_of(phrase, day)
    return None if found is None else found.isoformat()


# -- the synthesis ------------------------------------------------------------------------------------------


def standing_of(idx: Index, line: Line) -> Line | None:
    """The transcript's standing synthesis, None when it has none; `DreamError` for a transcript that
    is retracted or superseded, which is not the call as the record stands."""
    transcript = str(line["id"])
    retracted = retractions(idx.retractions())
    if transcript in retracted:
        raise DreamError("the transcript is retracted; nothing to synthesize")
    by = idx.superseded(KIND).get(transcript)
    if by is not None:
        raise DreamError(f"the transcript is superseded by #{by}; synthesize that one")
    found = drafts.by_transcript(idx.by_kind(drafts.KIND), retracted).get(transcript, [])
    return drafts.standing(found)


def synthesize(
    lb: Logbook,
    line: Line,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    again: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    found: policy.Ceiling | None = None,
) -> Synthesis:
    """Synthesize one transcript: the policy (`found` when the caller checked it already), the
    endpoint, the gate, the material, the model's turn, the check, and one `draft/v1` line appended
    under the writer lock unless `dry_run`. A transcript the same model synthesized under this prompt
    is `unchanged` and nothing is sent, unless `again`. `DreamError` (`HeldBack`, `NoText`,
    `AnswerError`) says why nothing was written; `HeadMoved` when the record moved under the reading."""
    found = found or dream.ceiling(lb)
    ep = dream.endpoint(found, env)
    source = drafts.SOURCE_PREFIX + ep.model
    with lb.writer():
        with lb.index() as idx:
            current = idx.by_id(str(line["id"])) or line
            latest = standing_of(idx, current)
        gate(current, found)
        if latest is not None and not again and _same(latest, source, found):
            kept = latest.get("payload") or {}
            return Synthesis(current, UNCHANGED, latest, dict(kept), int(latest.get("tier") or 1))
        made = material(lb, current, found)
        messages = prompt(made)
        if say is not None:
            say(messages[0]["content"])
            say(messages[1]["content"])
        try:
            answer = model_client.complete(ep, messages, transport=transport)
        except model_client.ModelError as e:
            raise AnswerError(str(e)) from e
        segments, details = segments_of(dream.parse(answer), made)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_EVENT,
            "subject": [str(current["id"])],
            "read_head": made.read_head,
            "read_count": 1,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                "utterances": len(made.turns),
                "segments": details,
                "policy_version": policy.version(found),
            },
        }
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        problems = drafts.validate(payload)
        if problems:
            raise AnswerError(f"the draft would not be a {drafts.SCHEMA}: {problems[0]}; nothing was written")
        if dry_run:
            return Synthesis(current, DRY_RUN, None, payload, made.tier, messages, answer)
        head = str(lb.meta.get("head"))
        if head != made.read_head:
            raise HeadMoved(HEAD_MOVED.format(was=made.read_head[:8], now=head[:8]))
        written = lb.append(at=now_utc(), source=source, kind=drafts.KIND, tier=made.tier, payload=payload)
    return Synthesis(current, SYNTHESIZED, written, payload, made.tier, messages, answer)


def _same(latest: Line, source: str, found: policy.Ceiling) -> bool:
    """Whether the standing synthesis is this model's under this prompt and the entry still stands
    behind it (`outdated`): then the call is unchanged (RFC 0036 rule 1, as the dream has it)."""
    extra = (latest.get("payload") or {}).get("extra")
    return (
        latest.get("source") == source
        and isinstance(extra, dict)
        and extra.get("prompt") == PROMPT_NAME
        and outdated(latest, found) is None
    )


def outdated(latest: Line, found: policy.Ceiling) -> str | None:
    """Why the `dream` entry no longer stands behind a standing synthesis, in words; None when it
    does. Its tier above the entry's `max_tier` today, or made under another version of the entry
    (`extra.policy_version`): derived material follows the policy, not the head. A synthesis that
    names no version is held to its tier alone."""
    tier = int(latest.get("tier") or 0)
    if tier > found.max_tier:
        return f"synthesized at tier {tier}, above max_tier {found.max_tier} now"
    extra = (latest.get("payload") or {}).get("extra")
    kept = extra.get("policy_version") if isinstance(extra, dict) else None
    if isinstance(kept, str) and kept != policy.version(found):
        return f"synthesized under another {policy.DREAM_DESTINATION} entry"
    return None


def synthesize_day(
    lb: Logbook,
    day: str,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    again: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
) -> list[Tried]:
    """Synthesize each transcript of a local day, one `Tried` each, in `at` order. The policy and the
    endpoint are checked once, before any transcript: a refusal there is `DreamError`."""
    found = dream.ceiling(lb)
    dream.endpoint(found, env)
    out: list[Tried] = []
    with lb.writer():  # one holder for the whole day; each transcript's head is its own
        for line in of_day(lb, day):
            out.append(_try(lb, line, found, env, dry_run, again, transport, say))
    return out


def _try(
    lb: Logbook,
    line: Line,
    found: policy.Ceiling,
    env: Mapping[str, str] | None,
    dry_run: bool,
    again: bool,
    transport: Transport | None,
    say: Callable[[str], None] | None,
) -> Tried:
    try:
        made = synthesize(lb, line, env, dry_run, again, transport, say, found)
    except HeldBack as e:
        return Tried(line, HELD_BACK, detail=str(e))
    except NoText as e:
        return Tried(line, NO_TEXT, detail=str(e))
    except (DreamError, HeadMoved, ValueError) as e:
        return Tried(line, REFUSED, detail=str(e))
    return Tried(line, made.state, made)


# -- catch-up -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class CaughtUp:
    """What the catch-up did to the transcripts: one `Outcome` per transcript sent, and how many were
    held back by the ceiling or had no text."""

    outcomes: list[Outcome]
    max_tier: int
    held_back: int = 0
    no_text: int = 0


def catch_up(
    lb: Logbook,
    days: Sequence[str],
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> CaughtUp:
    """Synthesize each transcript of `days` that has no synthesis yet, by any model, or whose standing
    synthesis the entry no longer stands behind (`outdated`: made under another version of it), as
    `dream --catch-up` dreams such a day again; one `Outcome` per transcript sent, oldest first (the
    06:00 close). A transcript above the ceiling, or without its text, is counted and never sent; one
    synthesized already under the entry is left alone. The policy and the endpoint are checked once:
    a refusal there is `DreamError`."""
    found = dream.ceiling(lb)
    dream.endpoint(found, env)
    outcomes: list[Outcome] = []
    held = missing = 0
    with lb.writer():
        for day in days:
            for line in of_day(lb, day):
                if int(line.get("tier") or 0) > found.max_tier:
                    held += 1
                    continue
                with lb.index() as idx:
                    try:
                        latest = standing_of(idx, line)
                    except DreamError:
                        continue
                why = None if latest is None else outdated(latest, found)
                if latest is not None and why is None:
                    continue
                tried = _try(lb, line, found, env, False, False, transport, None)
                if tried.state == NO_TEXT:
                    missing += 1
                elif tried.state == SYNTHESIZED and tried.synthesis is not None:
                    detail = detail_of(tried.synthesis) + (drafts.DOT + why if why else "")
                    outcomes.append(Outcome(day, SYNTHESIZED, detail))
                else:
                    outcomes.append(Outcome(day, REFUSED, f"“{title_of(line)}”: {tried.detail}"))
    return CaughtUp(outcomes, found.max_tier, held, missing)


def detail_of(made: Synthesis) -> str:
    """`#45 · “Yard plans” · 6 segments, 1 unsupported`: one synthesis in a catch-up's row."""
    segments = made.payload.get("segments") or []
    n = len(segments)
    unsupported = sum(1 for s in segments if isinstance(s, dict) and s.get("unsupported"))
    seq = f"#{made.line['seq']}" if made.line is not None else "dry run"
    counts = f"{n} segment{'s' if n != 1 else ''}" + (f", {unsupported} unsupported" if unsupported else "")
    return drafts.DOT.join([seq, f"“{title_of(made.transcript)}”", counts])


def _instant(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
