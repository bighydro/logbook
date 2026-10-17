"""The voiceprint registry (RFC 0038 §5): `voiceprints.age` in the record folder, beside `places.json`.

A **voiceprint** is an embedding of a voice: a vector the speaker model computes from the audio, close
to the vectors of the same voice in other recordings. It is biometric, so everything here follows
from that (§5.1, §5.3):

- the registry is one file, `voiceprints.age`, an age file (RFC 0029 §7's form) of one JSON document
  sealed to the record's own recipients, replaced whole on each write: written sealed to a temporary
  name beside it, then renamed over it, so a crash leaves the old file or the new one, never half;
  plaintext is never written to disk;
- a record that names no recipients keeps no registry on disk: the review hears the voices it
  compares for the run, in memory (`in_memory`), and forgets them on exit;
- it holds ids, vectors and seconds: no audio, no words, no names;
- it is a cache (ADR 0001), never the record: made from the audio attachments the transcripts'
  `diarization.audio` name and the standing attributions, and thrown away without loss. `verify`
  ignores it, `backup` leaves it out, and no crossing, page, bundle, vault, site, MCP answer, dream
  or export reads it: nothing opens it but the review, the commands that write it (`derive
  transcripts`, `derive speakers`, `setup speakers --rebuild`) and `doctor`, which says it exists,
  when and with which model it was built and for how many people, never what is in it.

The document, `voiceprints/1`:

    {"format": "voiceprints/1", "model": …, "model_sha256": …, "dim": 256, "head": …,
     "people": {<entity id>: {"voiceprint": [...], "clean_s": …, "from": [<speaker ref>, …],
                              "voices": {<speaker ref>: {"embedding": [...], "clean_s": …}}}},
     "voices": {<speaker ref>: {"embedding": [...], "clean_s": …}}}

`people` holds, per entity id, the voiceprint (the centre of the person's clean-speech embeddings,
weighted by their clean seconds), the clean seconds it rests on and the `speaker` refs it was built
from, each with its own embedding: so that a voiceprint is recomputed from the refs that stand, at
every write, by the review too, which loads no model. `voices` holds each voice not yet named, so
the review compares without loading a model.

**Clean speech** is the moments of a voice's turns (the spans file's `turns`, §2.3) in which it speaks
alone, each piece two seconds at least; a voice with less than `min_clean_s` of it is neither
embedded nor held (§5.5).

**Who is held** (§5.4, §5.5), from the standing transcripts and the standing attributions:
- the owner: every voice with `from_me` no line binds elsewhere and every voice bound to the owner,
  under `owner_id`, enrolled without a question and without a line;
- a person: every voice bound to them;
- an unnamed person: only with `enrol_unnamed` (default false: a stranger the owner would not name
  is not recognised next time either);
- a voice not yet named: in `voices`;
- an entity under `forget`: never, neither their voiceprint nor their voices.

**Writes.** `update` makes the file what the record says now: a voice whose transcript or whose
attribution no longer stands leaves at the next write, because each voiceprint is recomputed from the
refs that stand. With an embedder (`derive transcripts`, `derive speakers`, `setup speakers
--rebuild`) it also hears every voice it should hold and does not, so after such a write the file is
exactly what a rebuild makes; an embedder whose model or digest is not the file's rebuilds it all
(two models' vectors are not comparable). Without one (an answer in the review) it can only regroup
what it holds; a voice that returns to the queue from `unnamed` or `forget`, whose embedding the file
let go, waits for the next write that hears.

Determinism: every vector is unit length and rounded to `DECIMALS`, every sum is `math.fsum` (exact,
so the order of the terms does not matter), and the embedding of a voice is a function of the audio,
the spans file and the label alone, all three immutable; so a registry kept a write at a time and one
rebuilt from the same record are the same document.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import sys
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from . import attribution, policy, present, resolve, sealing, speakers
from .chain import AGE_MAGIC, Line
from .store import retractions

if TYPE_CHECKING:
    from .store import Logbook

FILE = "voiceprints.age"
FORMAT = "voiceprints/1"
MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"  # the configured embedding model (`diarize.EMBEDDING`)
CLEAN_PIECE_S = 2.0  # §5.1: a piece of clean speech is two seconds at least
DECIMALS = 6  # every number of a vector, so a vector is the same however often it is written
FULL = 70  # §4.3: `same voice`, at a similarity of `match` or more
SETTINGS_FILE = ("policy", "speakers.json")
DEFAULTS: dict[str, Any] = {
    "match": 0.75,
    "floor": 0.5,
    "min_clean_s": 8,
    "text_confidence_cap": 0.6,
    "enrol_unnamed": False,
    "forget": [],
}


class SettingsError(ValueError):
    """`policy/speakers.json` is not what it should be: one sentence naming the file and the key."""


class RegistryError(ValueError):
    """`voiceprints.age` cannot be read or written: one sentence, nothing in it shown."""


#: what a write can refuse with, each one sentence: the settings, the file, the owner's aliases
PROBLEMS: tuple[type[ValueError], ...] = (SettingsError, RegistryError, policy.PolicyError)


# -- the settings (§5.5) --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Settings:
    """`policy/speakers.json`, read each run, never a line."""

    match: float = 0.75
    floor: float = 0.5
    min_clean_s: float = 8.0
    text_confidence_cap: float = 0.6
    enrol_unnamed: bool = False
    forget: frozenset[str] = frozenset()


def settings(root: Path) -> Settings:
    """The settings: the RFC's defaults for a key the file does not have, or a record without the
    file; SettingsError, one sentence naming the file, for one that is not what it should be."""
    name = "/".join(SETTINGS_FILE)
    path = Path(root).joinpath(*SETTINGS_FILE)
    if not path.is_file():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise SettingsError(f"{name} is not JSON: {e}") from e
    if not isinstance(data, dict):
        raise SettingsError(f"{name} must be one object, as {json.dumps(DEFAULTS)}")
    unknown = sorted(set(data) - set(DEFAULTS))
    if unknown:
        raise SettingsError(f"{name}: {unknown[0]!r} is no setting; the settings are {', '.join(DEFAULTS)}")
    found = {**DEFAULTS, **data}
    for key in ("match", "floor", "text_confidence_cap"):
        if not _number(found[key]) or not 0 <= float(found[key]) <= 1:
            raise SettingsError(f"{name}: {key} must be a number from 0 to 1")
    if float(found["floor"]) >= float(found["match"]):
        raise SettingsError(
            f"{name}: floor must be below match, the similarity at which a voice scores {FULL}"
        )
    if not _number(found["min_clean_s"]) or float(found["min_clean_s"]) < 0:
        raise SettingsError(f"{name}: min_clean_s must be seconds, 0 or more")
    if not isinstance(found["enrol_unnamed"], bool):
        raise SettingsError(f"{name}: enrol_unnamed must be true or false")
    forget = found["forget"]  # any non-empty string: an id that is no one's simply matches no one
    if not isinstance(forget, list) or not all(isinstance(e, str) and e for e in forget):
        raise SettingsError(f"{name}: forget must be a list of entity ids, as `people --json` gives them")
    return Settings(
        float(found["match"]),
        float(found["floor"]),
        float(found["min_clean_s"]),
        float(found["text_confidence_cap"]),
        bool(found["enrol_unnamed"]),
        frozenset(forget),
    )


# -- vectors --------------------------------------------------------------------------------------------


Vector = tuple[float, ...]


def unit(values: Iterable[object], dim: int | None = None) -> Vector:
    """`values` as a unit vector, each number rounded to `DECIMALS`; ValueError for a vector that is
    not one (a number that is not finite, the wrong length, all zeros)."""
    found = list(values)
    if not found or not all(_number(v) for v in found):
        raise ValueError("an embedding is a list of finite numbers")
    if dim is not None and len(found) != dim:
        raise ValueError(f"an embedding of {len(found)} numbers, not {dim}")
    numbers = [float(v) for v in found]  # type: ignore[arg-type]
    norm = math.sqrt(math.fsum(v * v for v in numbers))
    if norm == 0.0:
        raise ValueError("an embedding of zeros")
    return tuple(round(v / norm, DECIMALS) + 0.0 for v in numbers)


def similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """The cosine of two vectors; 0 for vectors of different lengths or no length."""
    if len(a) != len(b) or not a:
        return 0.0
    na = math.sqrt(math.fsum(x * x for x in a))
    nb = math.sqrt(math.fsum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return math.fsum(x * y for x, y in zip(a, b, strict=True)) / (na * nb)


def centre(embeddings: Iterable[Embedded]) -> Vector:
    """The centre of embeddings, each weighted by its clean seconds (equally when none has any):
    a unit vector, as `unit` makes one. `math.fsum` adds exactly, so the order does not matter."""
    found = list(embeddings)
    if not found:
        raise ValueError("the centre of no embedding")
    weights = [e.clean_s for e in found]
    if math.fsum(weights) <= 0:
        weights = [1.0] * len(found)
    dim = len(found[0].embedding)
    summed = [math.fsum(w * e.embedding[i] for w, e in zip(weights, found, strict=True)) for i in range(dim)]
    if not any(summed):  # voices that cancel out exactly: the centre is the one with the most clean speech
        heaviest = max(range(len(found)), key=lambda i: (weights[i], found[i].embedding))
        return found[heaviest].embedding
    return unit(summed)


def points(sim: float, config: Settings) -> int:
    """§4.3: `FULL` at a similarity of `match` or more, falling in a straight line to 0 at `floor`,
    nothing below it."""
    if sim >= config.match:
        return FULL
    if sim <= config.floor:
        return 0
    return math.floor(FULL * (sim - config.floor) / (config.match - config.floor) + 0.5)


# -- clean speech ---------------------------------------------------------------------------------------


Piece = tuple[float, float]


def clean_pieces(document: Mapping[str, Any], label: str, least: float = CLEAN_PIECE_S) -> list[Piece]:
    """The voice's clean speech in a spans file (§2.3): its turns, less every moment another voice
    speaks, each piece `least` seconds or more (at the file's two decimals), in time order. Seconds
    from the line's `at`, which is the start of the recording."""
    turns = document.get("turns")
    mine: list[Piece] = []
    others: list[Piece] = []
    for t in turns if isinstance(turns, list) else []:
        if not isinstance(t, dict) or not _number(t.get("from")) or not _number(t.get("to")):
            continue
        span = (float(t["from"]), float(t["to"]))
        if span[1] > span[0] and span[0] >= 0:
            (mine if t.get("speaker") == label else others).append(span)
    talking = _merged(others)
    return [
        (a, b)
        for start, end in _merged(mine)
        for a, b in _less(start, end, talking)
        if round(b - a, 2) >= least
    ]


def clean_seconds(pieces: Iterable[Piece]) -> float:
    return round(math.fsum(b - a for a, b in pieces), 2) + 0.0


def _merged(spans: Iterable[Piece]) -> list[Piece]:
    out: list[Piece] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _less(start: float, end: float, others: Sequence[Piece]) -> list[Piece]:
    """`[start, end]` less the sorted, disjoint `others`."""
    out: list[Piece] = []
    for a, b in others:
        if b <= start or a >= end:
            continue
        if a > start:
            out.append((start, a))
        start = max(start, b)
        if start >= end:
            return out
    if start < end:
        out.append((start, end))
    return out


# -- the document ---------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Embedded:
    """One voice's embedding (a unit vector) and the clean seconds it was cut from; its repr shows
    no number of the vector."""

    embedding: Vector = field(repr=False)
    clean_s: float = field(repr=False)

    def to_json(self) -> dict[str, Any]:
        return {"embedding": list(self.embedding), "clean_s": self.clean_s}


@dataclass(frozen=True)
class Voiceprint:
    """One entity's voiceprint: the centre of its voices' embeddings, the clean seconds, the voices;
    its repr shows no number of the vector."""

    voiceprint: Vector = field(repr=False)
    clean_s: float = field(repr=False)
    voices: Mapping[str, Embedded] = field(repr=False)

    @property
    def refs(self) -> list[str]:
        return sorted(self.voices)


@dataclass
class Registry:
    """The registry's document, as written or as the review reads it."""

    model: str
    model_sha256: str
    dim: int
    head: str
    people: dict[str, Voiceprint] = field(default_factory=dict)
    voices: dict[str, Embedded] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Counts and the model, never a number of a vector: a registry printed by accident (a
        traceback, a debugger, a log) shows nothing of anyone's voice."""
        return f"Registry({self.model}, {len(self.people)} people, {len(self.voices)} voices not yet named)"

    def pool(self) -> dict[str, Embedded]:
        """Every voice the document holds, named or not: what a write recomputes from."""
        found = dict(self.voices)
        for print_ in self.people.values():
            found.update(print_.voices)
        return found

    def to_json(self) -> dict[str, Any]:
        return {
            "format": FORMAT,
            "model": self.model,
            "model_sha256": self.model_sha256,
            "dim": self.dim,
            "head": self.head,
            "people": {
                entity: {
                    "voiceprint": list(p.voiceprint),
                    "clean_s": p.clean_s,
                    "from": p.refs,
                    "voices": {ref: p.voices[ref].to_json() for ref in p.refs},
                }
                for entity, p in sorted(self.people.items())
            },
            "voices": {ref: self.voices[ref].to_json() for ref in sorted(self.voices)},
        }

    def to_bytes(self) -> bytes:
        return json.dumps(self.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    @classmethod
    def from_json(cls, data: object) -> Registry:
        """The document read back; RegistryError, naming nothing in it, for one that is not
        `voiceprints/1`."""
        if not isinstance(data, dict) or data.get("format") != FORMAT:
            raise RegistryError(f"{FILE} is not a {FORMAT} document")
        model, digest, dim, head = (data.get(k) for k in ("model", "model_sha256", "dim", "head"))
        if (
            not isinstance(model, str)
            or not model
            or not isinstance(digest, str)
            or not isinstance(head, str)
        ):
            raise RegistryError(f"{FILE} names no model")
        if not isinstance(dim, int) or isinstance(dim, bool) or dim < 1:
            raise RegistryError(f"{FILE} has no dimension")
        try:
            voices = {str(ref): _embedded(v, dim) for ref, v in _object(data.get("voices")).items()}
            people: dict[str, Voiceprint] = {}
            for entity, p in _object(data.get("people")).items():
                p = _object(p)
                held = {str(ref): _embedded(v, dim) for ref, v in _object(p.get("voices")).items()}
                if not held or sorted(held) != p.get("from"):
                    raise ValueError("a voiceprint that rests on no voice")
                people[str(entity)] = Voiceprint(
                    _vector(p.get("voiceprint"), dim), _seconds(p.get("clean_s")), held
                )
        except ValueError as e:
            raise RegistryError(f"{FILE} is not a {FORMAT} document ({_shape(e)})") from None
        return cls(model, digest, dim, head, people, voices)


def _object(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("an object expected")
    return value


def _embedded(value: object, dim: int) -> Embedded:
    found = _object(value)
    return Embedded(_vector(found.get("embedding"), dim), _seconds(found.get("clean_s")))


def _vector(value: object, dim: int) -> Vector:
    """A vector as it was written: checked, never made a unit vector again, which could move its
    last decimal and make a registry read back differ from the one written."""
    if not isinstance(value, list) or len(value) != dim or not all(_number(v) for v in value):
        raise ValueError("a vector of the wrong shape")
    return tuple(float(v) for v in value)


def _seconds(value: object) -> float:
    if not _number(value) or float(value) < 0:  # type: ignore[arg-type]
        raise ValueError("seconds expected")
    return float(value)  # type: ignore[arg-type]


def _shape(error: ValueError) -> str:
    """What was wrong, never a number of the document."""
    text = str(error)
    return text if not any(c.isdigit() for c in text) else "a vector of the wrong shape"


# -- who is held ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Holder:
    """Whose a standing voice is: `entity` None for a voice not yet named; `unnamed` for a person
    the owner declined to name."""

    entity: str | None
    unnamed: bool = False


def holders(heard: Iterable[tuple[Line, attribution.Heard]], owner_id: str | None) -> dict[str, Holder]:
    """`speaker` ref → its holder, for the voices of the standing transcripts as the readers join
    them (`attribution.Voices`): the owner's voices under `owner_id` (the source's `from_me`, or a
    line binding the owner), a person's under theirs, an unnamed person's marked, the rest not yet
    named."""
    found: dict[str, Holder] = {}
    for _line, h in heard:
        if h.state == attribution.OWNER:
            found[h.ref] = Holder(owner_id or h.entity)
        elif h.state == attribution.PERSON:
            found[h.ref] = Holder(h.entity)
        elif h.state == attribution.UNNAMED:
            found[h.ref] = Holder(h.entity, unnamed=True)
        else:
            found[h.ref] = Holder(None)
    return found


def held(holder: Holder | None, config: Settings) -> bool:
    """Whether the registry holds a voice of this holder (§5.4, §5.5): a voice not yet named, the
    owner's and a person's, an unnamed person's only with `enrol_unnamed`, never one of an entity
    under `forget`."""
    if holder is None:
        return False
    if holder.entity is not None and holder.entity in config.forget:
        return False
    return not holder.unnamed or config.enrol_unnamed


def view(
    pool: Mapping[str, Embedded],
    who: Mapping[str, Holder],
    config: Settings,
    *,
    model: str,
    model_sha256: str,
    dim: int,
    head: str,
) -> Registry:
    """The document the record says now, from the embeddings `pool` holds: every voice of a standing
    transcript that is held (`held`) and has `min_clean_s` of clean speech, a voice not yet named in
    `voices`, the others grouped by entity, each voiceprint the centre of its voices. A voice the
    pool does not hold is not in it."""
    voices: dict[str, Embedded] = {}
    grouped: dict[str, dict[str, Embedded]] = {}
    for ref in sorted(pool):
        holder = who.get(ref)
        embedded = pool[ref]
        if not held(holder, config) or embedded.clean_s < config.min_clean_s:
            continue
        assert holder is not None
        if holder.entity is None:
            voices[ref] = embedded
        else:
            grouped.setdefault(holder.entity, {})[ref] = embedded
    people = {
        entity: Voiceprint(
            centre(found[ref] for ref in sorted(found)),
            clean_seconds((0.0, found[ref].clean_s) for ref in sorted(found)),
            dict(sorted(found.items())),
        )
        for entity, found in sorted(grouped.items())
    }
    return Registry(model, model_sha256, dim, head, people, voices)


# -- the record's voices --------------------------------------------------------------------------------


def standing_voices(lb: Logbook) -> tuple[list[tuple[Line, attribution.Heard]], str | None]:
    """The voices of the standing transcripts (not retracted, not superseded by one heard again)
    joined to who they are, as `review speakers` reads them; and the record's `owner_id`."""
    with lb.index() as idx:
        marks = idx.retractions()
        resolutions = idx.resolutions()
        retracted = retractions(marks)
        heard_again = idx.superseded("transcript")
        by = idx.ids(heard_again.values())
        superseded = {old for old, seq in heard_again.items() if by.get(seq) not in retracted}
        transcripts = [
            line
            for line in idx.by_kind("transcript")
            if str(line["id"]) not in retracted and str(line["id"]) not in superseded
        ]
    identities = resolve.identities_from([*marks, *resolutions])
    owner_id = str(lb.meta.get("owner_id") or "") or None
    owner = present.owner_of(
        owner_id or "",
        [str(e) for e in lb.meta.get("owner_emails") or [] if isinstance(e, str)],
        policy.owner_aliases(lb.root),
        identities,
    )
    voices = attribution.Voices(identities, owner.entities, owner.id)
    return [(line, h) for line in transcripts for h in voices.of(line)], owner_id


# -- hearing --------------------------------------------------------------------------------------------


class Embedder(Protocol):
    """A local speaker-embedding model. `load` decodes a recording to mono samples; `embed` answers
    one vector for the voice speaking in `pieces` (seconds from the start) of them. `model` and
    `digest` name the model and its weights, `dim` the length of its vectors."""

    @property
    def model(self) -> str: ...
    @property
    def digest(self) -> str: ...
    @property
    def dim(self) -> int: ...

    def load(self, path: Path) -> tuple[Sequence[float], int]: ...
    def embed(self, samples: Sequence[float], rate: int, pieces: Sequence[Piece]) -> Sequence[float]: ...


NO_AUDIO = "no_audio"  # recordings whose audio is not in the store (§2.7: counted, skipped)
NO_SPANS = "no_spans"  # recordings whose spans file is not in the store, or not theirs
UNHEARD = "unheard"  # voices the model gave no vector for


@dataclass
class Heard:
    """What one hearing did: the embeddings made, and what it could not hear and why."""

    found: dict[str, Embedded] = field(default_factory=dict)
    skipped: dict[str, int] = field(default_factory=dict)

    def count(self, key: str, n: int = 1) -> None:
        self.skipped[key] = self.skipped.get(key, 0) + n


def hear(
    lb: Logbook,
    embedder: Embedder,
    heard: Sequence[tuple[Line, attribution.Heard]],
    who: Mapping[str, Holder],
    have: Iterable[str],
    config: Settings,
    progress: Callable[[str], None] | None = None,
) -> Heard:
    """Embed every voice of `heard` the registry holds (`held`) and `have` does not, from its
    recording's audio, decoded once per recording by the embedder, cut to its clean speech by the
    spans file. A recording without its audio or its spans file is counted and skipped."""
    out = Heard()
    have = set(have)
    by_line: dict[str, tuple[Line, list[str]]] = {}
    for line, h in heard:
        if h.ref in have or not held(who.get(h.ref), config):
            continue
        by_line.setdefault(str(line["id"]), (line, []))[1].append(h.label)
    for line, labels in by_line.values():
        audio = _audio(lb, line)
        if audio is None:  # §2.7: a recording whose audio is gone is skipped and counted
            out.count(NO_AUDIO)
            continue
        document = _spans(lb, line)
        if document is None:
            out.count(NO_SPANS)
            continue
        wanted = {}
        for label in labels:
            pieces = clean_pieces(document, label)
            seconds = clean_seconds(pieces)
            if pieces and seconds >= config.min_clean_s:
                wanted[label] = (pieces, seconds)
        if not wanted:
            continue
        try:
            with lb.attachment(audio) as path:
                samples, rate = embedder.load(path)
        except (OSError, sealing.SealError):
            out.count(NO_AUDIO)  # in the store and not to be opened here: as good as gone (§2.7)
            continue
        for label, (pieces, seconds) in wanted.items():
            try:
                vector = unit(embedder.embed(samples, rate, pieces), embedder.dim)
            except ValueError:
                out.count(UNHEARD)
                continue
            out.found[attribution.ref_value(str(line["id"]), label)] = Embedded(vector, seconds)
        if progress is not None:
            progress(f"  heard {len(wanted)} voice(s) of {_title(line)}")
    return out


def _spans(lb: Logbook, line: Line) -> dict[str, Any] | None:
    """The line's spans file when it is in the store and labels the line's own text."""
    payload = line.get("payload") or {}
    diarization = payload.get("diarization")
    spans = diarization.get("spans") if isinstance(diarization, dict) else None
    sha = spans.get("sha256") if isinstance(spans, dict) else None
    if not speakers.is_digest(sha) or not (lb.root / "attachments" / str(sha)).is_file():
        return None
    try:
        document = json.loads(lb.attachment_bytes(str(sha)).decode("utf-8"))
    except (OSError, ValueError, sealing.SealError):
        return None
    content = payload.get("content")
    if not isinstance(document, dict) or document.get("format") != speakers.FORMAT:
        return None
    if isinstance(content, dict) and document.get("content") != content.get("sha256"):
        return None
    return document


def _audio(lb: Logbook, line: Line) -> str | None:
    diarization = (line.get("payload") or {}).get("diarization")
    audio = diarization.get("audio") if isinstance(diarization, dict) else None
    if not speakers.is_digest(audio):
        return None
    return str(audio) if (lb.root / "attachments" / str(audio)).is_file() else None


def _title(line: Line) -> str:
    title = (line.get("payload") or {}).get("title")
    return f'"{title}"' if isinstance(title, str) and title.strip() else f"#{line.get('seq')}"


# -- the file -------------------------------------------------------------------------------------------


def path_of(root: Path) -> Path:
    return Path(root) / FILE


def read(lb: Logbook) -> Registry | None:
    """The registry, opened with this machine's identity; None when there is no file. RegistryError
    for a file this machine cannot open, or that is not a `voiceprints/1` document (never a plain
    one: the registry is never written unsealed, and a plain file under its name is not it)."""
    path = path_of(lb.root)
    if not path.is_file():
        return None
    try:
        data = path.read_bytes()
    except OSError as e:  # unreadable here, or being replaced by another process (Windows)
        raise RegistryError(f"{FILE} could not be read: {e.strerror or type(e).__name__}") from None
    if not data.startswith(AGE_MAGIC):
        raise RegistryError(f"{FILE} is not sealed; it is not a registry this record wrote")
    identities = lb.identities
    if not identities:
        raise RegistryError(f"{FILE} is sealed and this machine has no identity to open it with")
    try:
        plain = sealing.open_sealed_bytes(data, identities)
    except (sealing.SealError, sealing.MissingExtra) as e:
        said = (str(e).splitlines() or [""])[
            0
        ]  # pyrage's text for a cut file runs to a second line of advice
        raise RegistryError(f"{FILE} does not open: {said}") from None
    try:
        document = json.loads(plain.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RegistryError(f"{FILE} opens to something that is not JSON") from None
    return Registry.from_json(document)


_WRITING = threading.RLock()  # one write of this process at a time: the writer lock re-enters for its
# threads; re-entrant, so a reseal and a key change hold it across the writes they make


def writing() -> AbstractContextManager[bool]:
    """Held by a change of the record's recipients (`logbook key`) for the whole change: the writer
    lock re-enters for every thread of a process (the Library answers in threads), so this is what
    keeps another thread's write from sealing the registry to the list of a moment in between."""
    return _WRITING


def write(lb: Logbook, registry: Registry, recipients: Sequence[str] | None = None) -> Path:
    """Seal the document to the record's recipients (or to `recipients`, for a reseal) and put it in
    place whole: the sealed bytes to a temporary name beside the file, flushed to the disk, then
    renamed over it, so a crash leaves the old file or the new one and never half of either; the
    plaintext never touches the disk. A temporary file an earlier, interrupted write left is
    removed first. The caller holds the writer lock (one process at a time); `_WRITING` makes it
    one thread at a time, since the lock re-enters for every thread of a process and the temporary
    name is the process's; the recipients are read and sealed to under it, so a key change, which
    holds it throughout (`writing`), is never undone by a write that read the list before it.
    RegistryError for a record that names no recipients."""
    target = path_of(lb.root)
    tmp = target.with_name(f".{FILE}.{os.getpid()}.tmp")
    with _WRITING:
        recipients = list(recipients) if recipients is not None else lb.recipients
        if not recipients:
            raise RegistryError("this record names no recipients, so it keeps no registry on disk")
        sealed = sealing.seal_bytes(registry.to_bytes(), recipients)
        if not sealed.startswith(AGE_MAGIC):  # never: but the registry is never written in the clear
            raise RegistryError(f"{FILE} would not be sealed; nothing written")
        _remove_temporary(target.parent)
        try:
            with tmp.open("wb") as fh:
                fh.write(sealed)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
        _sync_folder(target.parent)
    return target


def _sync_folder(folder: Path) -> None:
    """Flush the folder's entries after the rename, so the new name is on the disk with the bytes
    it points at and a power loss cannot put the old file back. Nothing on Windows, which cannot
    open a folder for fsync; nothing said on a filesystem that refuses (the file is in place)."""
    if sys.platform == "win32":
        return
    with contextlib.suppress(OSError):
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _remove_temporary(folder: Path) -> None:
    """Every temporary file a write left (one killed between its bytes and the rename): sealed
    bytes, sealed to the recipients of their moment."""
    for stale in folder.glob(f".{FILE}.*.tmp"):
        stale.unlink(missing_ok=True)


def reseal(lb: Logbook, recipients: Sequence[str]) -> str | None:
    """The registry sealed again to `recipients` when the record's change (`logbook key
    add-recipient`, `remove-recipient`; RFC 0029 §6.4), as every sealed line and file is. The
    caller holds the writer lock across this and the record's reseal, and calls it before the
    record's when a recipient goes and after it when one comes, so the file never opens with an
    identity the record does not name. Whatever stops it, a KeyboardInterrupt too, leaves the file
    sealed to `recipients` or gone: a file this machine cannot open or seal again is removed, a
    cache the next write that hears makes again, and so is every temporary file a killed write
    left. What was done, in a few words; None when there is no file. RegistryError, naming the
    file and why, when it can be neither sealed again nor removed: the file as it was."""
    path = path_of(lb.root)
    with lb.writer(), _WRITING:
        try:
            _remove_temporary(path.parent)
        except OSError as e:
            raise RegistryError(
                f"a temporary file of {FILE} could not be removed ({e.strerror or type(e).__name__}):"
                f" delete every .{FILE}.*.tmp in the record folder"
            ) from None
        if path.is_symlink():  # not the registry: never read through, never written through
            try:
                _remove(path)
            except OSError as e:
                raise RegistryError(
                    f"{FILE} is a link that could not be removed ({e.strerror or type(e).__name__}):"
                    " delete it; `logbook setup speakers --rebuild` makes the registry again"
                ) from None
            return (
                f"{FILE} was a link to another file: the link is removed and what it pointed at is left as it"
                " was (delete it if it holds a registry); `setup speakers --rebuild` makes it again"
            )
        if not path.is_file():
            return None
        try:
            found = read(lb)
            if found is None:
                return None
            write(lb, found, recipients)
            return f"{FILE} sealed again to the new recipients"
        except (RegistryError, OSError, sealing.SealError, sealing.MissingExtra, ValueError):
            pass  # not to be opened or sealed again here: it goes, rather than stay sealed to the old list
        except BaseException:  # an interrupt, or anything else, half way: the file goes, then the error
            with contextlib.suppress(OSError):
                _remove(path)
            raise
        try:
            _remove(path)
        except OSError as e:
            raise RegistryError(
                f"{FILE} could be neither sealed again nor removed ({e.strerror or type(e).__name__}):"
                " close what holds it open, or delete it; `logbook setup speakers --rebuild` makes it again"
            ) from None
    return f"{FILE} removed: it could not be sealed again here; `setup speakers --rebuild` makes it again"


def _remove(path: Path) -> None:
    """The file gone, and its entry with it on the disk."""
    path.unlink(missing_ok=True)
    _sync_folder(path.parent)


# -- a write --------------------------------------------------------------------------------------------


@dataclass
class Summary:
    """What one write did, said without a number of the document."""

    state: str  # written, rebuilt, no recipients, no identity, no registry, unreadable
    people: int = 0
    voices: int = 0  # voices not yet named it holds
    heard: int = 0  # voices embedded by this write
    skipped: dict[str, int] = field(default_factory=dict)
    owner: bool = False  # whether it holds the owner's voiceprint
    reason: str | None = None  # why it did not write, or why it rebuilt

    @property
    def written(self) -> bool:
        return self.state in (WRITTEN, REBUILT)


WRITTEN, REBUILT = "written", "rebuilt"
#: what a write answers on a machine without the identity, and `doctor` with it: nothing is written there
NEEDS_IDENTITY = f"no identity on this machine, and {FILE} is sealed to the record's recipients and needs one"
NO_RECIPIENTS, NO_IDENTITY, NO_REGISTRY, UNREADABLE = (
    "no recipients",
    "no identity",
    "no registry",
    "unreadable",
)


def update(
    lb: Logbook,
    embedder: Embedder | None = None,
    *,
    rebuild: bool = False,
    progress: Callable[[str], None] | None = None,
) -> Summary:
    """Make the file what the record says now (the module's **Writes**). With `embedder`, every voice
    it should hold and does not is heard, and a file of another model or digest, one that will not
    open, or `rebuild`, is made again from nothing; without, the voices it holds are regrouped, a
    voice whose transcript or attribution no longer stands leaves, and a record with no file gets
    none. Nothing for a record that names no recipients, or on a machine without the identity. The
    hearing is done before the writer lock is taken, the file read again and written under it.
    SettingsError for `policy/speakers.json`, RegistryError when the file cannot be sealed."""
    if rebuild and embedder is None:
        raise RegistryError(f"{FILE} is made again from the audio, which needs the embedding model")
    if not lb.recipients:
        return Summary(NO_RECIPIENTS)
    if not lb.identities:
        return Summary(NO_IDENTITY, reason=NEEDS_IDENTITY)
    config = settings(lb.root)
    before, broken = _read_quietly(lb)
    if embedder is None and before is None:
        return Summary(UNREADABLE if broken else NO_REGISTRY, reason=broken)
    if embedder is not None:
        model, digest, dim = embedder.model, embedder.digest, embedder.dim
    else:
        assert before is not None
        model, digest, dim = before.model, before.model_sha256, before.dim
    same = before is not None and (before.model, before.model_sha256, before.dim) == (model, digest, dim)
    again = rebuild or not same  # without an embedder `before` is the model: always the same
    heard, owner_id = standing_voices(lb)
    found = Heard()
    if embedder is not None:
        have = () if again or before is None else before.pool()
        found = hear(lb, embedder, heard, holders(heard, owner_id), have, config, progress)
    with lb.writer():
        heard, owner_id = standing_voices(lb)  # what stands now, should a line have come in meanwhile
        pool: dict[str, Embedded] = {}
        if not again:  # the file as it is now: another write may have heard more meanwhile
            now, _broken = _read_quietly(lb)
            if now is not None and (now.model, now.model_sha256, now.dim) == (model, digest, dim):
                pool = now.pool()
        pool.update(found.found)
        head = str(lb.meta.get("head") or "")
        document = view(
            pool, holders(heard, owner_id), config, model=model, model_sha256=digest, dim=dim, head=head
        )
        try:
            write(lb, document)
        except RegistryError:
            raise
        except (sealing.SealError, sealing.MissingExtra, ValueError) as e:
            raise RegistryError(f"{FILE} could not be sealed to the record's recipients: {e}") from None
        except OSError as e:  # a full disk; on Windows, a reader holding the old file while it is replaced
            raise RegistryError(
                f"{FILE} could not be written: {e.strerror or e}; the file is as it was"
            ) from None
    if broken:
        reason: str | None = broken
    elif again and before is not None and not rebuild:
        reason = "the model changed"
    else:
        reason = None
    return Summary(
        REBUILT if (again and before is not None) or broken else WRITTEN,
        len(document.people),
        len(document.voices),
        len(found.found),
        found.skipped,
        bool(owner_id and owner_id in document.people),
        reason,
    )


def _read_quietly(lb: Logbook) -> tuple[Registry | None, str | None]:
    """The registry and None, or None and why it cannot be read."""
    try:
        return read(lb), None
    except RegistryError as e:
        return None, str(e)


def in_memory(
    lb: Logbook,
    embedder: Embedder,
    heard: Sequence[tuple[Line, attribution.Heard]],
    owner_id: str | None,
    config: Settings,
) -> Registry:
    """For a record that names no recipients (§5.1): the document the review compares with, heard
    for this run from the audio, kept in memory, never written."""
    who = holders(heard, owner_id)
    found = hear(lb, embedder, heard, who, (), config)
    return view(
        found.found,
        who,
        config,
        model=embedder.model,
        model_sha256=embedder.digest,
        dim=embedder.dim,
        head=str(lb.meta.get("head") or ""),
    )


# -- what doctor and setup say --------------------------------------------------------------------------


@dataclass(frozen=True)
class About:
    """What may be said of the file: that it is there, when it was written, and, opened, with which
    model and for how many people; never a number of its content."""

    built: datetime  # when it was written, from the file
    model: str | None = None  # None when this machine cannot open it
    people: int | None = None
    voices: int | None = None
    owner: bool = False
    error: str | None = None


def about(lb: Logbook) -> About | None:
    path = path_of(lb.root)
    if not path.is_file():
        return None
    built = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    try:
        found = read(lb)
    except RegistryError as e:
        return About(built, error=str(e))
    assert found is not None
    owner_id = str(lb.meta.get("owner_id") or "")
    return About(built, found.model, len(found.people), len(found.voices), owner_id in found.people)


def describe(summary: Summary) -> str | None:
    """One line for a command's closing words: what the write did, in counts; None when the record
    keeps no registry (no recipients), which a write says nothing of."""
    if summary.state == NO_RECIPIENTS:
        return None
    if not summary.written:
        return f"voiceprints: not written: {summary.reason or summary.state}"
    people = f"{summary.people} {'person' if summary.people == 1 else 'people'}"
    if summary.owner:
        people += ", you among them"
    said = (
        f"voiceprints: {_count(summary.heard, 'voice')} heard; {people},"
        f" {_count(summary.voices, 'voice')} not yet named"
    )
    if summary.state == REBUILT:
        said += f"; made again ({summary.reason})" if summary.reason else "; made again from the record"
    gone = summary.skipped.get(NO_AUDIO, 0)
    if gone:
        said += f"; {_count(gone, 'recording')} without its audio in the store skipped"
    for key, what in ((NO_SPANS, "without its spans file"), (UNHEARD, "the model gave no vector for")):
        if summary.skipped.get(key):
            said += f"; {summary.skipped[key]} {what}"
    return said


def about_text(found: About, tz: Any) -> str:
    """What `doctor` and `setup speakers` say of the file: when it was written and, opened, with
    which model and for how many people; never a number of it."""
    built = found.built.astimezone(tz).strftime("%Y-%m-%d %H:%M")
    if found.error is not None:
        return f"{FILE} written {built}; {found.error}"
    people = f"{found.people} {'person' if found.people == 1 else 'people'}"
    if found.owner:
        people += ", you among them"
    waiting = _count(found.voices or 0, "voice")
    return f"{FILE} written {built} with {found.model}, for {people}; {waiting} not yet named"


def _count(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
