"""`people ask NAME QUESTION` (EXPERIMENTAL, slice 0; README.md beside this file): a question about one
person answered from their derived store, every cited id resolved against the record. Nothing is written.

Serving checks again what ingesting checked, against the record and never the store alone: the
`relationship` entry as it counts today (none, no `until` or expired, and nothing is served), the store
read under that same entry and at the record's head (`reader.check`), and the authorized input set read
again from the record under the entry's ceiling. A message of the store whose line is not in that set
is withheld, never served, however it got there; the store is disposable and may be stale or edited.

The model (`Model`) is given the person's label, the window, the question and the served lines, each
with its id, instant, kind, speakers by label and words; it answers with segments `{text, evidence}`,
as a `draft/v1` segment is. Each id a segment cites is resolved against the set: a line of the set is
printed with its instant, kind, source and speakers; any other id, a line of the record or not, is
marked unsupported with the reason, and so is a segment that cites nothing. A segment is supported only
when it cites and every id it cites resolves. No model is wired yet: `MODEL` is None and `ask` refuses
until a later slice wires one; the tests set a stub."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ...core.store import Logbook
from . import reader
from .reader import RelationshipError


@dataclass(frozen=True)
class Question:
    """What the model is given: nothing of the record but the served lines and the person's label."""

    person: str
    window: tuple[str, str]
    question: str
    lines: list[dict[str, Any]]  # {id, at, kind, speakers, text}


Model = Callable[[Question], Sequence[Mapping[str, Any]]]  # segments: {text, evidence: [line id]}
MODEL: Model | None = None  # no model is wired yet


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

    def to_json(self) -> dict[str, Any]:
        return {
            "person": {"id": self.person, "name": self.label},
            "window": {"from": self.window[0], "to": self.window[1]},
            "question": self.question,
            "read_head": self.read_head,
            "served": self.served,
            "withheld": self.withheld,
            "answer": self.segments,
        }


def ask(lb: Logbook, name: str, question: str, model: Model | None = None) -> Answer:
    """The answer to `question` about the person `name` means, from their store; refused in one
    sentence when the entry, the model, the person or the store does not allow it."""
    current = reader.entry(lb.root)
    model = model or MODEL
    if model is None:
        raise RelationshipError(
            "no model is wired to the relationship reader yet; slice 0 is the acceptance test"
            " (logbook/contrib/relationship/README.md)"
        )
    if not question.strip():
        raise RelationshipError("the question is empty")
    entity, label = reader.identify(lb, name)
    store = reader.load(lb, entity)
    if store is None:
        raise RelationshipError(
            f"no derived store for {label}; run `logbook people ingest {name!r} --window FROM TO` first"
        )
    reader.check(lb, store, current)
    first, last = store.window
    found = reader.read(lb, entity, first, last, current.max_tier)
    allowed = found.by_line()
    served: list[dict[str, Any]] = []
    withheld = 0
    for message in store.messages:
        line = store.lines.get(str(message.get("id")))
        if line is None or line not in allowed:
            withheld += 1
            continue
        speakers = [store.peers[s] for s in message.get("speakers") or [] if s in store.peers]
        at, kind, text = message.get("at"), message.get("kind"), message.get("text")
        served.append({"id": line, "at": at, "kind": kind, "speakers": speakers, "text": text})
    answer = model(Question(found.label, (first, last), question, served))
    if not isinstance(answer, list | tuple):
        raise RelationshipError("the model's answer is not a list of segments; nothing is shown")
    segments = [
        _segment(s, found) for s in answer if isinstance(s, Mapping) and str(s.get("text") or "").strip()
    ]
    return Answer(
        entity,
        found.label,
        (first, last),
        question,
        str(store.manifest.get("read_head")),
        len(served),
        withheld,
        segments,
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
    supported = bool(cited) and all(c["why"] is None for c in cited)
    why = None if supported else "cites nothing" if not cited else "cites a line outside the set"
    return {"text": str(segment["text"]).strip(), "supported": supported, "why": why, "evidence": cited}


def rows(answer: Answer) -> Iterator[str]:
    """The answer as text: the head, the question, each segment with its cited lines under it; an
    unsupported segment set apart with `~`, and each id that does not resolve said so."""
    head = f"{answer.label} · {answer.window[0]} {reader.EN_DASH} {answer.window[1]} · {answer.served} lines"
    head += f" served · read at {answer.read_head[:8]}"
    yield head if not answer.withheld else f"{head} · {answer.withheld} withheld"
    yield f"Q  {answer.question}"
    for s in answer.segments:
        yield f"  {s['text']}" if s["supported"] else f"  ~ {s['text']}"
        if not s["evidence"]:
            yield f"      unsupported: {s['why']}"
        for c in s["evidence"]:
            line = c["line"]
            if line is None:
                yield f"      unsupported: {c['id']} is {c['why']}"
                continue
            said = [line["at"], line["kind"], line["source"], ", ".join(line["speakers"])]
            yield f"      {c['id']}  {' · '.join(x for x in said if x)}"
