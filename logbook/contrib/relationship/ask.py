"""`people ask NAME QUESTION` (EXPERIMENTAL, slice 1; README.md beside this file): a question about one
person answered from their derived store by a model, every cited id resolved against the record.
Nothing is written: an answer is never a line of the record and never kept.

Serving checks again what ingesting checked, against the record and never the store alone: the
`relationship` entry as it counts today (none, no `until` or expired, and nothing is read, served or
sent), the store read under that same entry and at the record's head (`reader.check`), and the
authorized input set read again from the record through the entry's gate (`reader.read`: the ceiling,
the signed days). A message of the store whose line is not in that set is withheld, never served,
however it got there; the store is disposable and may be stale or edited (`serve`).

The model (`Model`) is given the person's label, the window, the question and the served lines, each
with its id, instant, kind, speakers by label, words and the promises read in them (`reader.promises`),
and nothing else; it answers with segments `{text, evidence}`, as a `draft/v1` segment is. `MODEL` is
None by default, which is the endpoint the dream uses (`model.Cloud`, LOGBOOK_DREAM_*), under the
`relationship` entry's own `model` when it names one; the tests set a stub or fake the endpoint. Each id
a segment cites is resolved against the set: a line of the set is printed with its instant, kind,
source and speakers; any other id, a line of the record or not, is marked unsupported with the reason,
and so is a segment that cites nothing or that the model marked unsupported. A segment is supported only
when it cites and every id it cites resolves; the text prints the supported ones in order and the rest
under `unsupported`."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...core.store import Logbook
from ..model_client import Transport
from . import model as cloud
from . import reader
from .reader import RelationshipError


@dataclass(frozen=True)
class Question:
    """What the model is given: nothing of the record but the served lines and the person's label."""

    person: str
    window: tuple[str, str]
    question: str
    lines: list[dict[str, Any]]  # {id, at, kind, speakers, text}, and `promises` when it holds any


Model = Callable[[Question], Sequence[Mapping[str, Any]]]  # segments: {text, evidence: [line id]}
MODEL: Model | None = None  # None: the endpoint (`model.Cloud`); the tests set a stub


@dataclass(frozen=True)
class Served:
    """What may cross for one person today: the entry, the store, the set read again from the record,
    the served lines in the store's order and how many of the store's messages were withheld."""

    entry: reader.Entry
    store: reader.Derived
    found: reader.InputSet
    lines: list[dict[str, Any]]
    withheld: int


@dataclass(frozen=True)
class Answer:
    person: str
    label: str
    window: tuple[str, str]
    question: str
    read_head: str
    served: int
    withheld: int  # messages of the store whose line is not in the set read again now
    segments: list[dict[str, Any]]
    model: str | None = None  # the model's name, when the model says it
    max_tier: int | None = None  # the ceiling it was served under
    tier: int | None = None  # the highest tier read: an answer is derived from the lines it was given

    @property
    def unsupported(self) -> list[dict[str, Any]]:
        return [s for s in self.segments if not s["supported"]]

    def to_json(self) -> dict[str, Any]:
        return {
            "person": {"id": self.person, "name": self.label},
            "window": {"from": self.window[0], "to": self.window[1]},
            "question": self.question,
            "model": self.model,
            "max_tier": self.max_tier,
            "tier": self.tier,
            "read_head": self.read_head,
            "served": self.served,
            "withheld": self.withheld,
            "answer": self.segments,
            "segments": [_draft_segment(s) for s in self.segments],
            "unsupported": len(self.unsupported),
        }


def _draft_segment(segment: Mapping[str, Any]) -> dict[str, Any]:
    """A segment in the `draft/v1` shape: `{text, evidence: [ids]}` when supported, else `{text,
    unsupported: true}`, so an answer reads as a draft does."""
    if segment["supported"]:
        return {"text": segment["text"], "evidence": [c["id"] for c in segment["evidence"]]}
    return {"text": segment["text"], "unsupported": True}


def serve(lb: Logbook, name: str) -> Served:
    """The lines of the person `name` means that may cross to a model today, from their store: refused
    in one sentence when the entry, the person or the store does not allow it. A message is served only
    when its line is in the set read again now through the entry's gate, and with the record's own
    tier at or under the ceiling, and with the record's words for it, never the store's (a store edited
    by hand may hold any text); the rest are withheld and counted."""
    current = reader.entry(lb.root)
    entity, label = reader.identify(lb, name, current.max_tier)
    store = reader.load(lb, entity)
    if store is None:
        raise RelationshipError(
            f"no derived store for {label}; run `logbook people ingest {name!r} --window FROM TO` first"
        )
    reader.check(lb, store, current)
    first, last = store.window
    found = reader.read(lb, entity, first, last, current.max_tier, current.include_unsigned)
    allowed = found.by_line()
    said = reader.promises(lb, found, current.max_tier)
    served: list[dict[str, Any]] = []
    withheld = 0
    for message in store.messages:
        line = store.lines.get(str(message.get("id")))
        item = allowed.get(line) if line is not None else None
        if item is None or item.tier > current.max_tier:
            withheld += 1
            continue
        speakers = [found.peers[s] for s in item.speakers]
        shown: dict[str, Any] = {
            "id": line,
            "at": item.at,
            "kind": item.kind,
            "speakers": speakers,
            "text": item.text,
        }
        if said.get(item.line):
            shown["promises"] = said[item.line]
        served.append(shown)
    return Served(current, store, found, served, withheld)


def ask(
    lb: Logbook,
    name: str,
    question: str,
    model: Model | None = None,
    env: Mapping[str, str] | None = None,
    transport: Transport | None = None,
    say: Callable[[str], None] | None = None,
) -> Answer:
    """The answer to `question` about the person `name` means, from their store; refused in one
    sentence when the entry, the endpoint, the person or the store does not allow it, before anything
    is sent. `AnswerFailed` when the model was asked and its answer failed."""
    current = reader.entry(lb.root)  # first: without the entry nothing is read and nothing is sent
    if not question.strip():
        raise RelationshipError("the question is empty")
    model = model or MODEL or cloud.Cloud(cloud.endpoint(current, env), transport, say)
    got = serve(lb, name)
    found = got.found
    first, last = found.first, found.last
    answer = model(Question(found.label, (first, last), question, got.lines))
    if not isinstance(answer, list | tuple):
        raise cloud.AnswerFailed("the model's answer is not a list of segments; nothing is shown")
    segments = [
        _segment(s, found) for s in answer if isinstance(s, Mapping) and str(s.get("text") or "").strip()
    ]
    if not segments:
        raise cloud.AnswerFailed("the model's answer holds no segment with text; nothing is shown")
    return Answer(
        found.person,
        found.label,
        (first, last),
        question,
        str(got.store.manifest.get("read_head")),
        len(got.lines),
        got.withheld,
        segments,
        getattr(model, "name", None),
        got.entry.max_tier,
        found.tier,
    )


def _segment(segment: Mapping[str, Any], found: reader.InputSet) -> dict[str, Any]:
    allowed = found.by_line()
    evidence = segment.get("evidence")
    cited: list[dict[str, Any]] = []
    for id_ in dict.fromkeys(str(e) for e in (evidence if isinstance(evidence, list) else [])):
        item = allowed.get(id_)
        if item is None:
            cited.append(
                {"id": id_, "line": None, "why": f"not one of {found.label}'s lines in {found.span}"}
            )
            continue
        speakers = [found.peers[s] for s in item.speakers]
        line = {"at": item.at, "kind": item.kind, "source": item.source, "speakers": speakers}
        cited.append({"id": id_, "line": line, "why": None})
    marked = segment.get("unsupported") not in (None, False)  # the model's own mark, however it wrote it
    supported = bool(cited) and not marked and all(c["why"] is None for c in cited)
    if supported:
        why = None
    elif marked:
        why, cited = "the model says it rests on no line", []
    else:
        why = "cites nothing" if not cited else "cites a line outside the set"
    return {"text": str(segment["text"]).strip(), "supported": supported, "why": why, "evidence": cited}


def rows(answer: Answer) -> Iterator[str]:
    """The answer as text: the head, the question, each supported segment with its cited lines under
    it; then, under `unsupported`, every segment that rests on no line of the set, set apart with `~`,
    with why, and each id that does not resolve said so."""
    head = f"{answer.label} · {answer.window[0]} {reader.EN_DASH} {answer.window[1]} · {answer.served} lines"
    head += f" served · read at {answer.read_head[:8]}"
    if answer.withheld:
        head += f" · {answer.withheld} withheld"
    yield head if answer.model is None else f"{head} · model:{answer.model}"
    yield f"Q  {answer.question}"
    for s in answer.segments:
        if not s["supported"]:
            continue
        yield f"  {s['text']}"
        for c in s["evidence"]:
            line = c["line"]
            said = [line["at"], line["kind"], line["source"], ", ".join(line["speakers"])]
            yield f"      {c['id']}  {' · '.join(x for x in said if x)}"
    if not answer.unsupported:
        return
    yield f"unsupported: no line of {answer.label}'s in the window shows these"
    for s in answer.unsupported:
        yield f"  ~ {s['text']}"
        if not s["evidence"]:
            yield f"      unsupported: {s['why']}"
        for c in s["evidence"]:
            if c["line"] is None:
                yield f"      unsupported: {c['id']} is {c['why']}"
            else:
                yield f"      {c['id']}  cited beside a line outside the set"
    yield "  an answer is a proposal, read from the lines above; nothing of it is written"
