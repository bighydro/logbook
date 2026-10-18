"""The model the relationship reader asks (EXPERIMENTAL, slice 1; README.md beside this file).

Until the owner's own hardware runs one, the model is the cloud model the dream uses, through the
same endpoint and the same three variables (`logbook.contrib.model_client`: LOGBOOK_DREAM_ENDPOINT,
LOGBOOK_DREAM_MODEL, LOGBOOK_DREAM_KEY), under the reader's own entry, `relationship` in
`policy/crossing.json`, never the `dream` entry. The entry's `model`, when it names one, is the one
model a person may go to, and an environment that names another is refused (`endpoint`), as the
dream refuses it. A Honcho service on the owner's machine may later stand behind this same boundary:
`ask.Model` is a function from a `Question` to segments, and nothing else of the reader knows what
answers it.

**What crosses** is the `Question` and nothing else: the person's label, the window, the owner's
question and the served lines (`ask.serve`), each as a reference `L1`, `L2`, ... standing for one line
id, with its instant, kind, the speakers by label, its words and the promises read in them. The model
never sees a line id, so it cannot cite a plausible one it was not given; a reference it was not given
is kept as it wrote it, which no line of the set is, so the reader marks the segment unsupported.

**The answer** is one JSON object `{"answer": [segment, ...]}` (a bare list is taken too), each
segment `{text, evidence: [L1, ...]}` or `{text, unsupported: true}`, the `draft/v1` segment shape.

**The key never shows.** The endpoint may echo the bearer token in an error (a 401's message often
quotes it); every error said from here has the key, and its last eight characters, replaced by
`<key>` (`scrub`). The prompt `--show-prompt` prints is the two messages' text, never a header."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import Any

from .. import model_client
from ..model_client import Endpoint, Transport
from .reader import ENTRY, Entry, RelationshipError

PROMPT_FILE = Path(__file__).with_name("ask-prompt.md")
PROMPT_NAME = "relationship-ask/1"
KEY_SHOWN = "<key>"
KEY_TAIL = 8  # the last characters of a key an error may quote alone (`...a1b2c3d4`)


class AnswerFailed(RelationshipError):
    """The question was sent and the answer failed: the endpoint could not be reached, refused it, or
    answered something that is not the segments. Nothing is shown and nothing is written."""


def scrub(text: str, key: str | None) -> str:
    """`text` with the key, and its last `KEY_TAIL` characters, replaced by `KEY_SHOWN`."""
    if not key:
        return text
    text = text.replace(key, KEY_SHOWN)
    if len(key) > KEY_TAIL:
        text = text.replace(key[-KEY_TAIL:], KEY_SHOWN)
    return text


def endpoint(current: Entry, env: Mapping[str, str] | None = None) -> Endpoint:
    """The endpoint from the environment (`env`, else the process's), the entry's `model` winning
    when it names one; an environment that names another model is refused, since the entry is a
    ceiling, not a default. A refusal names the variable, never its value."""
    env = os.environ if env is None else env
    try:
        made = model_client.from_env(env, current.model)
    except model_client.ModelError as e:
        raise RelationshipError(scrub(str(e), env.get(model_client.KEY_ENV))) from None
    named = (env.get(model_client.MODEL_ENV) or "").strip()
    if current.model and named and named != current.model:
        raise RelationshipError(
            f"the {ENTRY!r} entry names the model {current.model!r} and {model_client.MODEL_ENV} says"
            f" {named!r}; make them agree"
        )
    return made


def material(question: Any) -> tuple[dict[str, Any], dict[str, str]]:
    """The question as the model reads it, and the references: `L1` -> line id, in the order served."""
    refs: dict[str, str] = {}
    lines = []
    for n, line in enumerate(question.lines, 1):
        ref = f"L{n}"
        refs[ref] = str(line["id"])
        shown: dict[str, Any] = {"ref": ref, "at": line["at"], "kind": line["kind"]}
        shown |= {"speakers": list(line["speakers"]), "text": line["text"]}
        if line.get("promises"):
            shown["promises"] = [dict(p) for p in line["promises"]]
        lines.append(shown)
    data = {
        "person": question.person,
        "window": {"from": question.window[0], "to": question.window[1]},
        "question": question.question,
        "lines": lines,
    }
    return data, refs


def prompt(question: Any, data: Mapping[str, Any], file: Path = PROMPT_FILE) -> list[dict[str, str]]:
    """The two messages: the prompt with the person and the window filled in, and the material."""
    system = Template(file.read_text(encoding="utf-8")).safe_substitute(
        person=question.person, first=question.window[0], last=question.window[1]
    )
    user = json.dumps(data, ensure_ascii=False, indent=1)
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse(answer: str, key: str = "answer") -> list[Any]:
    """The list of segments under `key` in the model's answer (a bare list is taken too);
    `AnswerFailed` when there is none."""
    from ..dream import AnswerError
    from ..dream import parse as parse_object

    text = answer.strip()
    if text.startswith("["):
        try:
            found = json.loads(text)
        except ValueError:
            found = None
        if isinstance(found, list):
            return found
    try:
        obj = parse_object(text)
    except AnswerError:
        raise AnswerFailed("the model's answer is not one JSON object; nothing is shown") from None
    items = obj.get(key)
    if not isinstance(items, list):
        raise AnswerFailed(f"the model's answer has no {key!r} list of segments; nothing is shown")
    return items


def segments(items: Sequence[Any], refs: Mapping[str, str]) -> list[dict[str, Any]]:
    """The segments with each reference turned into its line id (a full id of the set is taken as
    it is); a reference the material did not give is kept as written, so it resolves to no line. A
    segment the model marked unsupported keeps no evidence."""
    out: list[dict[str, Any]] = []
    for item in items:
        if isinstance(item, str):
            item = {"text": item}
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        if item.get("unsupported") not in (None, False):  # `true`, or `"true"`: the model's own mark
            out.append({"text": item["text"], "evidence": [], "unsupported": True})
            continue
        evidence = item.get("evidence")
        cited = [str(e).strip() for e in evidence] if isinstance(evidence, list) else []
        out.append({"text": item["text"], "evidence": [refs.get(c, c) for c in cited]})
    return out


@dataclass
class Cloud:
    """`ask.Model` for the endpoint: one completion per question. `say`, when given, is handed the
    two messages before they are sent (`--show-prompt`)."""

    endpoint: Endpoint
    transport: Transport | None = None
    say: Any = None
    sent: list[list[dict[str, str]]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.endpoint.model

    def __call__(self, question: Any) -> list[dict[str, Any]]:
        data, refs = material(question)
        messages = prompt(question, data)
        if self.say is not None:
            for message in messages:
                self.say(message["content"])
        self.sent.append(messages)
        try:
            answer = model_client.complete(self.endpoint, messages, transport=self.transport)
        except model_client.ModelError as e:
            raise AnswerFailed(scrub(str(e), self.endpoint.key)) from None
        return segments(parse(answer), refs)
