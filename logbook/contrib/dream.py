"""The dream (`logbook dream day DAY`, `logbook dream --catch-up`): a model reads one day of the
record and writes one `draft/v1` line about it (RFC 0036, `logbook.core.drafts`), the day in a
paragraph, the threads it moved, two questions for the owner's reflection, and proposals, the
people it thinks were there and the promises it thinks were made, every sentence pointing at the
lines it came from. The dream is a proposal; the owner's signature and notes are the facts.

Sending a day to a model is a crossing like any other, so it is governed by `policy/crossing.json`
(ADR 0016, ADR 0022): the `dream` entry's `max_tier` is the ceiling the day is read under, its
`until` the last day it holds, and its optional `model` the one model the day may go to. No entry,
or an expired one, and the dream refuses in one sentence and nothing leaves the machine.

What the model sees (`material`) is the Day as the day reader shows it under that ceiling
(`day.read(..., tiers)`): the nights, the stays and moves with what attached to each and who was
there, the flights, what is unplaced, the health line when tier 3 is allowed; then the day's
messages by counterpart with their count and, since a message line is in the reading only when its
tier is under the ceiling, their text; the notes in full; the commitments on the day; and the
owner's note on signing it. Never a raw line above the ceiling. Every item carries a reference
(`L1`, `L2`, ...) that stands for one line id of the day, so the model cites references and the
record keeps ids. The prompt is `dream-prompt.md` beside this module (docs/dream-prompt.md explains
it); it asks for one JSON object of segments `{text, evidence}` and says which language to write in:
the language most of the day's own text is in (`language_of`).

The answer is checked before anything is written (`segments_of`): a segment whose every reference
is one the material gave is supported and carries the ids; one with a reference the day does not
have, or none, is marked unsupported; a segment without text is dropped. When more than
`UNSUPPORTED_SHARE` of the segments are unsupported the answer is refused and nothing is written.
The draft's tier is the highest tier among the lines it read, not the lines it cited (RFC 0036);
`read_count` is how many it read; `read_head` the record's head at that moment. The whole dream,
reading, the model's turn and the write, runs inside the record's writer lock (`Logbook.writer`,
#237), and the head is read again before the append: a head that moved is `HeadMoved` and nothing
is written. Dreaming a day again writes a new line whose `supersedes` names the standing draft; the
same model at the same head under the same entry writes nothing and says so (RFC 0036 rule 1). The
dream never writes a note, a signature or a review. Every draft records the version of the entry it
was dreamed under (`extra.policy_version`, `policy.version`: the SHA-256 of its `max_tier`, `until`
and `model`).

`--catch-up` dreams each of the last N days that has no draft, or whose lines today differ from
what the standing draft read (its `read_count`, and the digest of the ids it read, kept under
`extra.read_ids_sha256`), or whose standing draft the entry no longer stands behind: its tier above
the entry's `max_tier` today, or dreamed under another version of the entry. Derived material follows
the policy, not the head, so a lowered ceiling or a moved `until` is a change of the day as much as a
new line is, and the day is dreamed again under the entry as it is now, superseding the old draft.
An expired entry dreams nothing (the refusal before any day); the readers withhold what it allowed
(`drafts.allowed`). One line per day; what the morning schedule calls."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from string import Template
from typing import Any

from ..core import day as day_reader
from ..core import drafts, policy, reading, resolve
from ..core.chain import Line
from ..core.export import parse_day
from ..core.flights import Airports
from ..core.resolve import Ref
from ..core.store import HeadMoved, Logbook, now_utc, retractions
from . import model_client
from .model_client import Endpoint, Transport
from .promises import chat_ref

PROMPT_FILE = Path(__file__).with_name("dream-prompt.md")
PROMPT_NAME = "dream-day/1"  # kept under `extra.prompt`, so a draft says which prompt wrote it
UNSUPPORTED_SHARE = 0.30  # more than this share of segments unsupported: refused, nothing written
TEXT_CHARS = 400  # a message's text in the material, at most
NOTE_CHARS = 1500  # a note's text in the material, at most
MESSAGES_PER_COUNTERPART = 25  # the texts given per counterpart; the count is always whole
EXCLUDED_KINDS = frozenset({"retraction", "signed-day", drafts.KIND, "crossing"})  # never material
DEFAULT_LANGUAGE = "en"
DOT = " \u00b7 "
HEAD_MOVED = (
    "the record's head moved from {was} to {now} while the model read the day, so the draft would not"
    " say what it read; nothing was written, dream the day again"
)
LANGUAGE_NAMES = {"en": "English", "nb": "Norwegian", "de": "German", "fr": "French", "es": "Spanish"}
# the commonest short words of each language the dream recognises, matched whole and lower-cased
STOPWORDS: dict[str, frozenset[str]] = {
    "en": frozenset(
        {"the", "and", "with", "for", "was", "were", "from", "this", "that", "have", "not", "you"}
    )
    | frozenset({"are", "at", "on", "of", "to", "in"}),
    "nb": frozenset({"og", "med", "for", "var", "fra", "det", "den", "har", "ikke", "jeg", "du", "er"})
    | frozenset({"på", "til", "av", "som", "en", "et", "ei"}),
    "de": frozenset({"und", "mit", "für", "war", "aus", "das", "der", "die", "hat", "nicht", "ich", "du"})
    | frozenset({"ist", "auf", "zu", "von", "ein", "eine"}),
    "fr": frozenset({"et", "avec", "pour", "était", "dans", "le", "la", "les", "est", "pas", "je", "tu"})
    | frozenset({"sur", "une", "un", "des", "du", "au"}),
    "es": frozenset({"y", "con", "para", "era", "desde", "el", "la", "los", "las", "es", "no", "yo"})
    | frozenset({"tú", "en", "una", "un", "del", "al", "que"}),
}
WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


class DreamError(ValueError):
    """The dream refuses: the policy, the endpoint, the day or the answer; one sentence, nothing
    written."""


class AnswerError(DreamError):
    """The model answered and the answer failed: not reachable, not JSON, no segment, or too many
    unsupported; the day was sent and nothing was written."""


@dataclass
class Material:
    """What the model is given about one day, and what the record keeps about that reading."""

    day: str
    tier: int  # the highest tier among the lines read: the draft's tier
    read_count: int
    read_head: str
    read_ids_sha256: str
    language: str
    data: dict[str, Any]  # the JSON the prompt carries
    refs: dict[str, str] = field(default_factory=dict)  # `L1` -> line id
    ids: set[str] = field(default_factory=set)  # every line id read on the day
    _by_id: dict[str, str] = field(default_factory=dict)  # line id -> `L1`

    def ref_of(self, line_id: str | None) -> str | None:
        """The reference that stands for a line of the day, minted on first use; None for a line
        that is not on the day (the night before's), which the model cannot cite."""
        if not line_id or line_id not in self.ids:
            return None
        found = self._by_id.get(line_id)
        if found is not None:
            return found
        ref = f"L{len(self.refs) + 1}"
        self.refs[ref] = line_id
        self._by_id[line_id] = ref
        return ref

    def refs_of(self, ids: Iterable[str | None]) -> list[str]:
        return [ref for ref in (self.ref_of(i) for i in ids) if ref is not None]


@dataclass(frozen=True)
class Dream:
    """What a dream of one day came to: the draft line written (None under `--dry-run`), the
    payload, the prompt's messages and the model's raw answer."""

    day: str
    line: Line | None
    payload: dict[str, Any]
    tier: int
    messages: list[dict[str, str]]
    answer: str


@dataclass(frozen=True)
class Outcome:
    """One row of `--catch-up`: the day, what happened (`dreamed`, `unchanged`, `empty`, `refused`)
    and the detail."""

    day: str
    state: str
    detail: str


# -- the policy and the endpoint -------------------------------------------------------------------------


def ceiling(lb: Logbook) -> policy.Ceiling:
    """The `dream` entry of the crossing policy as it counts today; `DreamError` when there is
    none, when it has expired, or when the file is not a policy."""
    try:
        return policy.dream_entry(lb.root)
    except policy.PolicyError as e:
        raise DreamError(str(e)) from e


def endpoint(found: policy.Ceiling, env: Mapping[str, str] | None = None) -> Endpoint:
    """The model endpoint from the environment (`env`, else the process's), the policy's `model`
    winning when the entry names one; an environment that names another model is refused, since
    the entry is a ceiling, not a default."""
    env = os.environ if env is None else env
    try:
        made = model_client.from_env(env, found.model)
    except model_client.ModelError as e:
        raise DreamError(str(e)) from e
    named = (env.get(model_client.MODEL_ENV) or "").strip()
    if found.model and named and named != found.model:
        raise DreamError(
            f"{policy.POLICY_FILE.as_posix()} names the model {found.model!r} for"
            f" {policy.DREAM_DESTINATION!r} and {model_client.MODEL_ENV} says {named!r}; make them agree"
        )
    return made


# -- the material -----------------------------------------------------------------------------------------


def material(lb: Logbook, day: str, found: policy.Ceiling, airports: Airports | None = None) -> Material:
    """The day's material under the entry's ceiling: the Day as the reader shows it through the
    gate, the messages by counterpart, the notes, the commitments and the signing note, each item
    with its reference. The lines read are the day's lines under the ceiling, the kinds that are
    about the record rather than the day left out (`EXCLUDED_KINDS`)."""
    day = parse_day(day).isoformat()
    tiers = tuple(range(1, found.max_tier + 1))
    data = day_reader.read(lb, day, airports, tiers)
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        on_day = [
            line
            for line in reading.crossing(idx.day(day), tiers)
            if str(line["id"]) not in retracted and line.get("kind") not in EXCLUDED_KINDS
        ]
        names = resolve.labels(lb, idx)
    on_day.sort(key=lambda line: (str(line["at"]), int(line["seq"])))
    ids = {str(line["id"]) for line in on_day}
    digest = hashlib.sha256("\n".join(sorted(ids)).encode("utf-8")).hexdigest()
    tier = max((int(line.get("tier", 1)) for line in on_day), default=1)
    texts = _texts(on_day)
    made = Material(
        day=day,
        tier=tier,
        read_count=len(on_day),
        read_head=str(lb.meta["head"]),
        read_ids_sha256=digest,
        language=language_of(texts),
        data={},
        ids=ids,
    )
    made.data = _data(data, on_day, names, made, found.max_tier)
    return made


def _texts(lines: Iterable[Line]) -> list[str]:
    """The day's own words: notes, message texts, event titles, mail subjects, transcript titles."""
    out = []
    for line in lines:
        payload = line.get("payload") or {}
        for key in ("text", "title", "subject"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                out.append(value)
    return out


def language_of(texts: Iterable[str]) -> str:
    """The language most of the day's text is in, by counting each language's commonest words;
    `en` when nothing decides it."""
    words = Counter(w.lower() for text in texts for w in WORD.findall(text))
    scores = {tag: sum(n for w, n in words.items() if w in stop) for tag, stop in STOPWORDS.items()}
    best = max(scores.values(), default=0)
    if best == 0:
        return DEFAULT_LANGUAGE
    winners = sorted(tag for tag, score in scores.items() if score == best)
    return DEFAULT_LANGUAGE if DEFAULT_LANGUAGE in winners else winners[0]


def _data(
    data: Mapping[str, Any], on_day: Sequence[Line], names: Mapping[Ref, str], made: Material, max_tier: int
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "day": data["day"],
        "weekday": data["weekday"],
        "tz": data["tz"],
        "max_tier": max_tier,
        "night_before": _night(data["nights"]["before"], made),
        "night_after": _night(data["nights"]["after"], made),
        "country": data["country"].get("code"),
        "all_day": [
            {"title": a["title"], "ref": made.refs_of(a.get("lines") or [a["line"]])} for a in data["all_day"]
        ],
        "timeline": [_entry(e, made) for e in data["timeline"]],
        "unplaced": [
            {
                "kind": u["kind"],
                "at": u["at"],
                "title": u["title"],
                "ref": made.refs_of(u.get("lines") or [u["line"]]),
            }
            for u in data["unplaced"]
        ],
        "messages": _messages(on_day, names, made),
        "notes": _notes(on_day, made),
        "commitments": _commitments(on_day, names, made),
    }
    if data.get("health"):
        out["health"] = day_reader.health_text(data["health"])
    signed = data.get("signed")
    if isinstance(signed, dict):
        out["signed"] = {"at": signed["at"], "note": signed.get("note")}
    return out


def _night(night: Mapping[str, Any], made: Material) -> dict[str, Any]:
    if night["in_transit"]:
        return {"where": "in transit"}
    return {
        "where": night["where"],
        "home": night["home"],
        "ref": made.refs_of(night.get("lines") or []),
    }


def _entry(entry: Mapping[str, Any], made: Material) -> dict[str, Any]:
    if entry["kind"] == day_reader.FLIGHT:
        return {
            "kind": "flight",
            "start": entry["start_local"],
            "end": entry["end_local"],
            "flight": f"{entry['carrier']} {entry['number']} {entry['from']} to {entry['to']}",
            "ref": made.refs_of([entry["line"]]),
        }
    lines = entry.get("lines") or {}
    out: dict[str, Any] = {
        "kind": "gap" if entry.get("gap") else entry["kind"],
        "start": entry["start_local"],
        "end": entry["end_local"],
        "where": entry.get("where"),
        "ref": made.refs_of([lines.get("first"), lines.get("last")]),
    }
    if entry["kind"] == "move" and entry.get("mode"):
        out["mode"] = entry["mode"]
    if entry.get("airports"):
        out["airports"] = list(entry["airports"])
    attached = entry.get("attached")
    if attached:
        out["events"] = [
            {"title": e["title"], "ref": made.refs_of(e.get("lines") or [e["line"]])}
            for e in attached["events"]
        ]
        out["transcripts"] = [
            {"title": t["title"], "ref": made.refs_of([t["line"]])} for t in attached["transcripts"]
        ]
        out["mail"] = [
            {"subject": m["subject"], "messages": m["messages"], "ref": made.refs_of(m["lines"])}
            for m in attached["mail"]
        ]
        out["calls"] = [
            {
                "who": c["who"],
                "direction": c["direction"],
                "answered": c["answered"],
                "ref": made.refs_of([c["line"]]),
            }
            for c in attached["calls"]
        ]
        out["photos"] = {
            "count": attached["photos"]["count"],
            "ref": made.refs_of(attached["photos"]["lines"][:12]),
        }
        out["keepers"] = [{"name": k["name"], "ref": made.refs_of([k["line"]])} for k in attached["keepers"]]
        for key in ("events", "transcripts", "mail", "calls", "keepers"):
            if not out[key]:
                del out[key]
        if not out["photos"]["count"]:
            del out["photos"]
    company = entry.get("with")
    if company and (company["confirmed"] or company["proposed"]):
        out["with"] = {
            "confirmed": [{"name": c["name"], "ref": made.refs_of(c["lines"])} for c in company["confirmed"]],
            "proposed": [{"name": c["name"], "ref": made.refs_of(c["lines"])} for c in company["proposed"]],
        }
    inside = entry.get("inside")
    if inside:
        out["inside"] = [_entry({**s, "attached": None, "with": None}, made) for s in inside]
    return out


def _chat_key(payload: Mapping[str, Any]) -> tuple[bool, str, str]:
    """(direct, key, name) of a message's chat: a string `chat` is a direct chat's name (SPEC
    §3.2); a direct chat is one counterpart whichever way its messages went."""
    chat = payload.get("chat")
    if isinstance(chat, str):
        chat = {"type": "direct", "name": chat}
    elif not isinstance(chat, dict):
        chat = {}
    name = str(chat.get("name") or "")
    key = str(chat.get("id") or name)
    return chat.get("type") in (None, "direct"), key, name


def _counterpart(payload: Mapping[str, Any], names: Mapping[Ref, str]) -> str | None:
    """The other party of a direct chat as the record names them: the resolved sender of a message
    not from the owner, else the name the source showed for it, else the ref the chat's id names
    (`chat_ref`) resolved; None when nothing in this message says."""
    direct, key, _name = _chat_key(payload)
    sender = payload.get("sender")
    if direct and not payload.get("from_me") and isinstance(sender, dict):
        kind, value = sender.get("kind"), sender.get("value")
        if isinstance(kind, str) and isinstance(value, str) and (kind, value) in names:
            return names[(kind, value)]
        own = sender.get("name")
        if isinstance(own, str) and own:
            return own
    ref = chat_ref(key) if direct else None
    if ref is not None and ref in names:
        return names[ref]
    return None


def _messages(on_day: Sequence[Line], names: Mapping[Ref, str], made: Material) -> list[dict[str, Any]]:
    """The day's messages by counterpart, a direct chat one counterpart and a group its name: the
    count, the references, and the texts (a message in the reading is under the ceiling, so its
    text may be read), at most MESSAGES_PER_COUNTERPART of them, each shortened to TEXT_CHARS."""
    by: dict[str, dict[str, Any]] = {}
    for line in on_day:
        if line.get("kind") != "message":
            continue
        payload = line.get("payload") or {}
        direct, key, name = _chat_key(payload)
        entry = by.setdefault(
            ("direct:" if direct else "group:") + key,
            {
                "counterpart": None,
                "count": 0,
                "ref": [],
                "texts": [],
                "group": not direct,
                "chat": name or key,
            },
        )
        entry["count"] += 1
        if entry["counterpart"] is None:
            entry["counterpart"] = _counterpart(payload, names)
        ref = made.ref_of(str(line["id"]))
        entry["ref"].append(ref)
        text = payload.get("text")
        if len(entry["texts"]) < MESSAGES_PER_COUNTERPART:
            body = (
                text
                if isinstance(text, str) and text.strip()
                else f"[{payload.get('media_kind') or 'media'}]"
            )
            entry["texts"].append(
                {"ref": ref, "from_me": bool(payload.get("from_me")), "text": _clip(body, TEXT_CHARS)}
            )
    out = []
    for entry in by.values():
        chat = entry.pop("chat")
        if entry["counterpart"] is None:
            entry["counterpart"] = f"{chat} (group)" if entry["group"] else (chat or "withheld")
        elif entry["group"]:
            entry["counterpart"] = f"{chat} (group)"
        out.append(entry)
    return sorted(out, key=lambda e: (-e["count"], e["counterpart"]))


def _notes(on_day: Sequence[Line], made: Material) -> list[dict[str, Any]]:
    return [
        {
            "ref": made.ref_of(str(line["id"])),
            "text": _clip(str((line.get("payload") or {}).get("text") or ""), NOTE_CHARS),
        }
        for line in on_day
        if line.get("kind") == "note" and (line.get("payload") or {}).get("text")
    ]


def _commitments(on_day: Sequence[Line], names: Mapping[Ref, str], made: Material) -> list[dict[str, Any]]:
    out = []
    for line in on_day:
        if line.get("kind") != "commitment":
            continue
        payload = line.get("payload") or {}
        who = payload.get("counterparty")
        label = None
        if isinstance(who, dict) and isinstance(who.get("kind"), str) and isinstance(who.get("value"), str):
            label = names.get((who["kind"], who["value"])) or who["value"]
        out.append(
            {
                "ref": made.ref_of(str(line["id"])),
                "text": _clip(str(payload.get("text") or ""), TEXT_CHARS),
                "direction": payload.get("direction"),
                "counterparty": label,
                "due": payload.get("due"),
            }
        )
    return out


def _clip(text: str, chars: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= chars else text[: chars - 1] + "…"


# -- the prompt and the answer ---------------------------------------------------------------------------


def prompt(made: Material) -> list[dict[str, str]]:
    """The two messages the model gets: the prompt file with the day and the language filled in,
    and the material as JSON."""
    template = Template(PROMPT_FILE.read_text(encoding="utf-8"))
    system = template.safe_substitute(
        day=made.day,
        weekday=made.data.get("weekday", ""),
        tz=made.data.get("tz", ""),
        language=made.language,
        language_name=LANGUAGE_NAMES.get(made.language, made.language),
    )
    user = json.dumps(made.data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse(answer: str) -> dict[str, Any]:
    """The JSON object in the model's answer: the whole text, or the text inside a code fence, or
    the span from the first `{` to the last `}`; `DreamError` when there is none."""
    text = answer.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    candidates.append(text)
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{") : text.rindex("}") + 1])
    for candidate in candidates:
        try:
            found = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(found, dict):
            return found
    raise AnswerError("the model's answer is not one JSON object; nothing was written")


def segments_of(found: Mapping[str, Any], made: Material) -> tuple[list[dict[str, Any]], list[str]]:
    """The answer's segments in the parts' order, each `{text, evidence: [ids]}` when every
    reference is one the material gave (a full line id of the day is taken too), else `{text,
    unsupported: true}`; and the part of each. A segment without text is dropped. More than
    `UNSUPPORTED_SHARE` unsupported, or no segment at all, is `DreamError`."""
    segments: list[dict[str, Any]] = []
    parts: list[str] = []
    for part in drafts.PARTS:
        items = found.get(part)
        if not isinstance(items, list):
            continue
        for item in items:
            segment = _segment(item, made)
            if segment is None:
                continue
            segments.append(segment)
            parts.append(part)
    if not segments:
        raise AnswerError("the model's answer holds no segment with text; nothing was written")
    unsupported = sum(1 for s in segments if s.get("unsupported"))
    if unsupported / len(segments) > UNSUPPORTED_SHARE:
        raise AnswerError(
            f"{unsupported} of {len(segments)} segments rest on no line of the day, more than"
            f" {round(UNSUPPORTED_SHARE * 100)} %; the answer is refused and nothing was written"
        )
    return segments, parts


def _segment(item: object, made: Material) -> dict[str, Any] | None:
    if isinstance(item, str):
        item = {"text": item}
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    if not isinstance(text, str) or not text.strip():
        return None
    text = " ".join(text.split())
    evidence = item.get("evidence")
    ids: list[str] = []
    if isinstance(evidence, list):
        for ref in evidence:
            key = str(ref).strip()
            line_id = made.refs.get(key) or (key if key in made.ids else None)
            if line_id is not None and line_id not in ids:
                ids.append(line_id)
    if ids and item.get("unsupported") is not True:
        return {"text": text, "evidence": ids}
    return {"text": text, "unsupported": True}


# -- the dream --------------------------------------------------------------------------------------------


def dream(
    lb: Logbook,
    day: str,
    env: Mapping[str, str] | None = None,
    airports: Airports | None = None,
    dry_run: bool = False,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
    made: Material | None = None,
) -> Dream:
    """Dream `day`: the policy, the endpoint, the material (`made` when the caller built it under
    the lock already), the model's turn, the check, and one `draft/v1` line appended under the
    writer lock unless `dry_run`. `DreamError` says why a dream is refused; `HeadMoved` when the
    record moved under the reading."""
    found = ceiling(lb)
    ep = endpoint(found, env)
    with lb.writer():
        if made is None:
            made = material(lb, day, found, airports)
        if made.read_count == 0:
            raise DreamError(f"{made.day} has no line under max_tier {found.max_tier}; nothing to dream")
        with lb.index() as idx:
            earlier = drafts.of_day(idx.by_kind(drafts.KIND), retractions(idx.retractions()), made.day)
        latest = drafts.standing(earlier)
        source = drafts.SOURCE_PREFIX + ep.model
        version = policy.version(found)
        if latest is not None and not dry_run:
            payload_before = latest.get("payload") or {}
            kept = _policy_version(payload_before)
            if (
                latest.get("source") == source
                and payload_before.get("read_head") == made.read_head
                and (kept is None or kept == version)  # a draft that names no entry: the head decides
            ):
                raise DreamError(
                    f"{made.day} was dreamed by {source} at this head already (#{latest['seq']}); the record"
                    " has not moved, so there is nothing new to dream"
                )
        messages = prompt(made)
        if say is not None:
            say(messages[0]["content"])
            say(messages[1]["content"])
        try:
            answer = model_client.complete(ep, messages, transport=transport)
        except model_client.ModelError as e:
            raise AnswerError(str(e)) from e
        segments, parts = segments_of(parse(answer), made)
        payload: dict[str, Any] = {
            "schema": drafts.SCHEMA,
            "unit": drafts.UNIT_DAY,
            "subject": made.day,
            "read_head": made.read_head,
            "read_count": made.read_count,
            "language": made.language,
            "segments": segments,
            "extra": {
                "prompt": PROMPT_NAME,
                "parts": parts,
                "read_ids_sha256": made.read_ids_sha256,
                "policy_version": version,
            },
        }
        if latest is not None:
            payload["supersedes"] = str(latest["id"])
        problems = drafts.validate(payload)
        if problems:
            raise AnswerError(f"the draft would not be a {drafts.SCHEMA}: {problems[0]}; nothing was written")
        if dry_run:
            return Dream(made.day, None, payload, made.tier, messages, answer)
        current = lb.meta
        if str(current.get("head")) != made.read_head:
            raise HeadMoved(HEAD_MOVED.format(was=made.read_head[:8], now=str(current.get("head"))[:8]))
        line = lb.append(at=now_utc(), source=source, kind=drafts.KIND, tier=made.tier, payload=payload)
    return Dream(made.day, line, payload, made.tier, messages, answer)


# -- catch-up ----------------------------------------------------------------------------------------------


def today() -> date:
    """The day a catch-up counts back from: this machine's date."""
    return date.today()


def days_to_catch_up(today: date, days: int) -> list[str]:
    """The last `days` local days before today, oldest first; today is still being written."""
    return [(today - timedelta(days=n)).isoformat() for n in range(days, 0, -1)]


def _policy_version(payload: Mapping[str, Any]) -> str | None:
    """The version of the entry a draft was dreamed under, None for a draft that names none."""
    extra = payload.get("extra")
    kept = extra.get("policy_version") if isinstance(extra, dict) else None
    return kept if isinstance(kept, str) else None


def changed_since(lb: Logbook, day: str, found: policy.Ceiling) -> tuple[bool, str, Material | None]:
    """Whether `day` needs dreaming: no draft; a standing draft the entry no longer stands behind
    (its tier above the entry's `max_tier` today, or dreamed under another version of the entry: a
    draft follows the policy, not the head); or the lines under the ceiling today are not what the
    standing draft read (its count, and the digest of ids when it kept one). The material is
    returned so a caller that dreams does not read twice; None for an empty day."""
    made = material(lb, day, found)
    if made.read_count == 0:
        return False, "nothing logged", None
    with lb.index() as idx:
        earlier = drafts.of_day(idx.by_kind(drafts.KIND), retractions(idx.retractions()), made.day)
    latest = drafts.standing(earlier)
    if latest is None:
        return True, "no draft yet", made
    payload = latest.get("payload") or {}
    tier = int(latest.get("tier") or 0)
    if tier > found.max_tier:
        return True, f"dreamed at tier {tier}, above max_tier {found.max_tier} now", made
    version = _policy_version(payload)
    if version is not None and version != policy.version(found):
        return True, f"dreamed under another {policy.DREAM_DESTINATION} entry", made
    extra = payload.get("extra")
    kept = extra.get("read_ids_sha256") if isinstance(extra, dict) else None
    if payload.get("read_count") != made.read_count:
        return True, f"{made.read_count} lines now, {payload.get('read_count')} when last dreamed", made
    if isinstance(kept, str) and kept != made.read_ids_sha256:
        return True, "the day's lines are not the ones last dreamed", made
    return False, f"unchanged since #{latest['seq']}", made


def catch_up(
    lb: Logbook,
    days: int,
    today: date | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
) -> list[Outcome]:
    """Dream each of the last `days` days that needs it; one `Outcome` per day, oldest first. The
    policy and the endpoint are checked once, before any day: a refusal there is `DreamError`."""
    found = ceiling(lb)
    endpoint(found, env)
    out: list[Outcome] = []
    with lb.writer():  # one holder for the whole run, as `sync` holds it: each day's head is its own
        for day in days_to_catch_up(today or date.today(), days):
            out.append(_catch_up_day(lb, day, found, env, transport))
    return out


def _catch_up_day(
    lb: Logbook, day: str, found: policy.Ceiling, env: Mapping[str, str] | None, transport: Transport | None
) -> Outcome:
    try:
        needed, why, made = changed_since(lb, day, found)
        if made is None:
            return Outcome(day, "empty", why)
        if not needed:
            return Outcome(day, "unchanged", why)
        dreamed = dream(lb, day, env, transport=transport, made=made)
        line = dreamed.line
        n = len(dreamed.payload["segments"])
        unsupported = sum(1 for s in dreamed.payload["segments"] if s.get("unsupported"))
        detail = f"#{line['seq'] if line else '?'}{DOT}{why}{DOT}{n} segments" + (
            f", {unsupported} unsupported" if unsupported else ""
        )
        return Outcome(day, "dreamed", detail)
    except (DreamError, HeadMoved, ValueError) as e:
        return Outcome(day, "refused", str(e))
