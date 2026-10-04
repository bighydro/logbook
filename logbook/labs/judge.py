"""`logbook promises --judge`: a local instruct model reads each candidate the rules found and says
whether it is a commitment, by whom, to whom, what, by when and how sure it is.

The rules (`logbook.contrib.promises`) over-propose by design: on a real record most of their candidates
are conversational ("I'll have a look", "we'll see"). The judge is a second pass over the same
candidates, never a new extractor: it adds a `Judgement` to a proposal and changes neither the
proposal, its id nor what `promises done` writes. Each candidate is shown with the two sentences
either side of it, its speaker as the report names them, the day, the title and the names the
record resolves in that line, and answers one JSON object at temperature 0.

**Nothing leaves the machine.** The engine is `mlx-lm` on Apple silicon, an optional extra
(`openlogbook[judge]`) imported only when `--judge` runs, with a small 4-bit instruct model
(`DEFAULT_MODEL`; `--model` names another). While it runs the Hugging Face hub is told it is
offline (`transcribe.offline`), so no socket is opened for any reason; a model not on the machine
stops the command with the one flag that fetches it, `--fetch-model`, as `transcribe` has it.

A judgement is kept in the record, outside the chain, in `policy/promises-cache.json` keyed by the
candidate's id, with the engine and model that gave it: a candidate is judged once, however often
the command runs and whatever model is set later. The cache is written after every verdict, so an
interrupted run keeps what it did. The chain is never written here; only `promises done` appends."""

from __future__ import annotations

import importlib
import json
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from platform import machine
from typing import Any, Protocol

from ..contrib.promises import OWNER, THRESHOLD, UNKNOWN, Judgement, Proposal, Report
from ..core.store import now_utc
from . import transcribe

DEFAULT_MODEL = "mlx-community/Qwen2.5-7B-Instruct-4bit"
EXTRA = "openlogbook[judge]"
CACHE_FILE = PurePosixPath("policy/promises-cache.json")  # record-relative, beside the other policy files
CACHE_VERSION = 1
MAX_TOKENS = 240
MARK = "> "  # the candidate's line in the prompt; every other context line starts with two spaces
KEYS = ("is_commitment", "by", "to", "what", "due", "confidence")

SYSTEM = (
    "You read one sentence from a personal record (a meeting transcript or a note) and judge whether "
    "it is a real commitment: a specific thing a specific person said they will do, or must do, for "
    'someone. Conversational phrases are not commitments: "we\'ll see", "I\'ll have a look", '
    '"let me think", "I\'ll be honest", filler, hypotheticals, questions, and a sentence whose '
    "speaker is reporting what someone else will do.\n"
    "Answer with one JSON object and nothing else:\n"
    '{"is_commitment": true or false, "by": "owner" or a name from the list or "unknown", '
    '"to": "owner" or a name from the list or "unknown", "what": the commitment in one short line '
    'in the speaker\'s own words, "due": "YYYY-MM-DD" or null, "confidence": a number from 0 to 1}\n'
    '"owner" is the person whose record this is, shown as "you" in the context. A date is '
    "resolved against the day the sentence was said; when the words name no day, due is null. "
    'When unsure who, use "unknown".'
)


class EngineMissing(Exception):
    """No judge engine is installed."""


class ModelMissing(Exception):
    """The model is not on this machine and the run was not told to fetch it."""


class CacheError(Exception):
    """The cache file is not the documented shape."""


class Engine(Protocol):
    """A local instruct model: `answer` is its text for one chat, sampled at temperature 0."""

    name: str
    model: str

    def ready(self) -> bool: ...
    def fetch(self) -> None: ...
    def answer(self, messages: Sequence[Mapping[str, str]]) -> str: ...


@dataclass
class Judged:
    """What one `--judge` run did."""

    engine: str
    model: str
    candidates: int  # unjudged candidates when the run began
    judged: int = 0
    unparsed: int = 0  # answers with no whole verdict in them; not cached, tried again next run

    def to_json(self) -> dict[str, Any]:
        return {
            "engine": self.engine,
            "model": self.model,
            "candidates": self.candidates,
            "judged": self.judged,
            "unparsed": self.unparsed,
        }


# -- the prompt ------------------------------------------------------------------------------------


def messages_of(p: Proposal, owner: str | None) -> list[dict[str, str]]:
    """The chat for one candidate: the system message above, and the candidate marked `> ` among
    the sentences around it, each with who said it, after the owner's name, the names the record
    resolves in the line, the day and the title."""
    who = p.speaker.display() if p.speaker is not None else "?"
    head = [
        f'Owner of the record: {owner or "unknown"} ("you" below).',
        "Names resolved in this conversation: " + (", ".join(p.names) if p.names else "none") + ".",
        f"{'Transcript' if p.kind == 'transcript' else 'Note'}"
        + (f" “{p.title}”" if p.title else "")
        + f", said on {p.day}.",
        "",
        "Context, the candidate sentence marked with `>`:",
    ]
    context = [f"  {s.speaker}: {s.text}" for s in p.before]
    context.append(f"{MARK}{who}: {p.match.quote}")
    context += [f"  {s.speaker}: {s.text}" for s in p.after]
    tail = ["", "Judge the marked sentence. One JSON object, nothing else."]
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "\n".join(head + context + tail)},
    ]


def candidate_of(messages: Sequence[Mapping[str, str]]) -> str:
    """The marked line of a chat built by `messages_of`, without the mark (for tests and fakes)."""
    for line in messages[-1]["content"].splitlines():
        if line.startswith(MARK):
            return line[len(MARK) :]
    return ""


# -- the answer ------------------------------------------------------------------------------------

_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse(text: str) -> dict[str, Any] | None:
    """The first JSON object in a model's answer, fences and prose aside, or None."""
    for m in _OBJECT.finditer(text):
        try:
            data = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def judgement_of(text: str, model: str, at: str, engine: str = "") -> Judgement | None:
    """The verdict in an answer, or None when any field is missing or not what it should be:
    `is_commitment` a boolean (or its word), `by` and `to` strings (`owner`, a name, `unknown`),
    `what` a string, `due` a `YYYY-MM-DD` day or null (an empty string is null), `confidence` a
    number in 0 to 1."""
    data = parse(text)
    if data is None or any(key not in data for key in KEYS):
        return None
    is_commitment = _bool(data["is_commitment"])
    confidence = _number(data["confidence"])
    by, to, what = data["by"], data["to"], data["what"]
    due = data["due"]
    if is_commitment is None or confidence is None or not 0 <= confidence <= 1:
        return None
    if not all(isinstance(v, str) for v in (by, to, what)):
        return None
    if due is not None and not isinstance(due, str):
        return None
    due = (due or "").strip() or None
    if due is not None:
        if not _DAY.match(due):
            return None
        try:
            date.fromisoformat(due)
        except ValueError:
            return None
    return Judgement(
        is_commitment,
        _who(by),
        _who(to),
        " ".join(str(what).split()),
        due,
        round(confidence, 3),
        model,
        at,
        engine,
    )


def _bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().casefold() in ("true", "false", "yes", "no"):
        return value.strip().casefold() in ("true", "yes")
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _who(value: str) -> str:
    name = " ".join(value.split())
    if name.casefold() in ("owner", "you", "me", "the owner"):
        return OWNER
    return name if name and name.casefold() not in ("unknown", "none", "null", "?") else UNKNOWN


# -- the cache -------------------------------------------------------------------------------------


def cache_path(root: Path) -> Path:
    return Path(root).joinpath(*CACHE_FILE.parts)


def read_cache(root: Path) -> dict[str, Judgement]:
    """candidate id → its judgement, from `policy/promises-cache.json`; empty when there is no file;
    CacheError naming the file when it is not JSON or not the documented shape. An entry that is not
    a whole judgement is left out, never a traceback."""
    path = cache_path(root)
    if not path.is_file():
        return {}
    shape = f'{path} must be {{"version": {CACHE_VERSION}, "judgements": {{"<id>": {{...}}}}}}'
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise CacheError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("judgements"), dict):
        raise CacheError(shape)
    out: dict[str, Judgement] = {}
    for pid, entry in data["judgements"].items():
        if not isinstance(pid, str) or not isinstance(entry, dict):
            continue
        found = judgement_of(
            json.dumps(entry), str(entry.get("model") or ""), str(entry.get("judged_at") or ""),
            str(entry.get("engine") or ""),
        )  # fmt: skip
        if found is not None:
            out[pid] = found
    return out


def write_cache(root: Path, judgements: Mapping[str, Judgement]) -> Path:
    """The whole cache, written once and atomically (a temp file beside it, then replaced), the
    ids sorted so two writes of the same verdicts are the same bytes."""
    path = cache_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": CACHE_VERSION,
        "judgements": {pid: judgements[pid].to_json() for pid in sorted(judgements)},
    }
    text = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(text.encode("utf-8"))
    os.replace(temp, path)
    return path


# -- the run ---------------------------------------------------------------------------------------


def run(
    root: Path,
    report: Report,
    engine: Engine,
    *,
    limit: int | None = None,
    fetch_model: bool = False,
    progress: Callable[[str], None] | None = None,
    clock: Callable[[], str] = now_utc,
) -> Judged:
    """Judge every candidate of `report` that the cache holds no verdict for, oldest first, at most
    `limit`; the cache is rewritten after each verdict. `progress` gets one line per candidate.
    Nothing is appended to the chain."""
    kept = read_cache(root)
    todo = [p for p in report.proposals if p.id not in kept]
    judged = Judged(engine.name, engine.model, len(todo))
    if limit is not None:
        todo = todo[: max(0, limit)]
    if not todo:
        return judged
    if not engine.ready():
        if not fetch_model:
            raise ModelMissing(
                f"model {engine.model!r} is not on this machine; run once with --fetch-model to download it"
                " (the only time this command uses the network)"
            )
        engine.fetch()
    total = len(todo)
    with transcribe.offline():
        for n, p in enumerate(todo, 1):
            verdict = judgement_of(
                engine.answer(messages_of(p, report.owner)), engine.model, clock(), engine.name
            )
            if verdict is None:
                judged.unparsed += 1
            else:
                kept[p.id] = verdict
                judged.judged += 1
                write_cache(root, kept)
            if progress is not None:
                progress(f"  {n}/{total}  {_progress(p, verdict)}")
    return judged


def _progress(p: Proposal, verdict: Judgement | None) -> str:
    who = p.speaker.display() if p.speaker is not None else "?"
    quote = p.match.quote if len(p.match.quote) <= 60 else p.match.quote[:59].rstrip() + "…"
    if verdict is None:
        said = "no verdict in the answer"
    elif verdict.shows():
        said = f"commitment {verdict.confidence:g}"
    elif verdict.is_commitment:
        said = f"commitment {verdict.confidence:g}, below {THRESHOLD:g}"
    else:
        said = f"no {verdict.confidence:g}"
    return f"{who}  “{quote}”  {said}"


# -- the engine ------------------------------------------------------------------------------------


def detect(
    model: str = DEFAULT_MODEL,
    importer: Callable[[str], Any] = importlib.import_module,
    platform: tuple[str, str] | None = None,
) -> Engine:
    """The engine this machine has: `mlx-lm`, when it is installed; EngineMissing naming the extra
    and the platform when it is not."""
    try:
        module = importer(MlxLm.module)
    except ImportError:
        here = platform or (sys.platform, machine())
        where = "" if here == ("darwin", "arm64") else f"; this is {here[0]}/{here[1]}, not Apple silicon"
        raise EngineMissing(
            f"no judge engine is installed; install {EXTRA} (mlx-lm, which runs on Apple silicon only{where})"
        ) from None
    return MlxLm(model, module, importer)


class MlxLm:
    """Apple's MLX language-model runner: any instruct model the hub serves in MLX format, by its
    repository name; sampled greedily (temperature 0) for at most `MAX_TOKENS` tokens per answer."""

    name = "mlx-lm"
    module = "mlx_lm"

    def __init__(self, model: str, mlx: Any, importer: Callable[[str], Any]) -> None:
        self.model, self._mlx, self._import = model, mlx, importer
        self._loaded: tuple[Any, Any] | None = None

    def ready(self) -> bool:
        return transcribe.cached(self._import, self.model)

    def fetch(self) -> None:
        transcribe.download(self._import, self.model)

    def answer(self, messages: Sequence[Mapping[str, str]]) -> str:
        if self._loaded is None:
            self._loaded = self._mlx.load(self.model)
        model, tokenizer = self._loaded
        prompt = tokenizer.apply_chat_template(
            [dict(m) for m in messages], add_generation_prompt=True, tokenize=False
        )
        sampler = self._import("mlx_lm.sample_utils").make_sampler(temp=0.0)
        return str(
            self._mlx.generate(
                model, tokenizer, prompt=prompt, max_tokens=MAX_TOKENS, sampler=sampler, verbose=False
            )
        )
