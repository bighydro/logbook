"""Who spoke when, heard on this machine (RFC 0038 §2.1, §2.9): the diarizer `derive transcripts` and
`derive speakers` run beside the Whisper engine, and the one command that downloads its models.

The engine is pyannote.audio's pretrained pipeline `pyannote/speaker-diarization-3.1`, which runs on
the CPU and on Apple silicon through torch behind either Whisper engine. It is part of the
`openlogbook[transcribe]` extra and imported only when a command runs. The pipeline reads two more
models, `pyannote/segmentation-3.0` and the embedding model `pyannote/wespeaker-voxceleb-resnet34-LM`;
all three are gated on Hugging Face behind accepting their conditions, and all three must be in the
hub's cache on this machine before a run can separate voices.

**Nothing leaves the machine.** A run that diarizes does it inside `quiet()`: the hub is offline
(`HF_HUB_OFFLINE`, `TRANSFORMERS_OFFLINE`, as `transcribe` has it) so no model is fetched, and
pyannote.audio's own usage reporting, which its 4.x releases switch on by default and send to
pyannote's server, is switched off (`PYANNOTE_METRICS_ENABLED=0`) before the package is imported.
`huggingface_hub` reads `HF_HUB_OFFLINE` once, when it is first imported, and asks the constant it
made on every request; so `quiet()` sets that constant too, for the block, and on the way out puts
back what it was, or, for a hub first imported inside the block, what the environment now says. The
hub is offline inside, whichever code imported it first, and a download outside (the Whisper model
`derive transcripts --fetch-model` fetches) is not refused for having followed one.
Whether the models are here is asked of the hub's cache with `local_files_only`, which opens nothing.
`detect` answers None when the package or a model is missing, and the run then transcribes as it
always did and says once `speakers: not separated (logbook setup speakers --fetch-model)`.

**The one download** is `fetch`, behind `logbook setup speakers --fetch-model` and nothing else: the
three repositories into the hub's cache, with the owner's own access token read from `HF_TOKEN` for
those requests only. The token is never written, never printed, never part of a message; when the
hub refuses (the conditions not accepted, no token, a token of another account) `Refused` names the
page to accept them on.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ENGINE = "pyannote"  # `diarization.engine`
MODEL = "pyannote/speaker-diarization-3.1"  # `diarization.model`
SEGMENTATION = "pyannote/segmentation-3.0"
EMBEDDING = "pyannote/wespeaker-voxceleb-resnet34-LM"
MODELS = (MODEL, SEGMENTATION, EMBEDDING)  # what the pipeline reads; all three gated, all three fetched
MODULE = "pyannote.audio"
HUB = "huggingface_hub"
EXTRA = "openlogbook[transcribe]"
TOKEN = "HF_TOKEN"  # the owner's own access token, read by `fetch` alone
PAGE = "https://huggingface.co/{repo}"
SAMPLE_RATE = 16_000
FETCH = "logbook setup speakers --fetch-model"
NOT_SEPARATED = f"speakers: not separated ({FETCH})"
HUB_CONSTANTS = "huggingface_hub.constants"  # where the hub keeps the offline switch it read at import
QUIET = {
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
    "PYANNOTE_METRICS_ENABLED": "0",  # pyannote.audio 4 reports usage to otel.pyannote.ai unless told not to
}

Importer = Callable[[str], Any]
Heard = tuple[float, float, str]  # a turn as the diarizer names it: start, end, its own speaker id


class Diarizer(Protocol):
    """A local diarizer. `diarize` hears one channel's samples and answers its turns, the speakers
    named its own way; `speakers` is a hint that the recording held that many voices. `channels`
    decodes a file keeping its channels apart, for a recording whose source says they are."""

    name: str
    model: str

    def diarize(self, samples: Sequence[float], rate: int, speakers: int | None = None) -> list[Heard]: ...
    def channels(self, path: Path) -> tuple[list[Sequence[float]], int]: ...


class Refused(Exception):
    """The hub would not hand over a model: its conditions not accepted, or no token that may."""

    def __init__(self, repo: str) -> None:
        super().__init__(
            f"the Hugging Face hub refused {repo}: accept its conditions at {PAGE.format(repo=repo)} while"
            f" signed in, then set {TOKEN} to a read token of that account for this one command"
        )
        self.repo = repo


class ModelsMissing(Exception):
    """The cache said the models were here and the pipeline could not load them from it (a fetch
    that was interrupted, a cache written by an older hub): one sentence naming the fetch."""

    def __init__(self) -> None:
        super().__init__(
            f"the speaker models in the Hugging Face cache are not whole; {FETCH} fetches them again"
        )


@dataclass(frozen=True)
class Status:
    """What is on this machine: the engine's version (None when it is not installed) and, for each
    model the pipeline reads, whether the hub's cache holds it."""

    version: str | None
    models: dict[str, bool]

    @property
    def ready(self) -> bool:
        return self.version is not None and all(self.models.values())


@contextmanager
def quiet() -> Iterator[None]:
    """The hub offline and pyannote's usage reporting off, for the length of the block, the hub's
    own switch included (the module's docstring); the variables and the switch as they were
    afterwards. Entered before pyannote.audio is first imported, since it reads its switch then."""
    before = {name: os.environ.get(name) for name in QUIET}
    constants = sys.modules.get(HUB_CONSTANTS)
    was = getattr(constants, "HF_HUB_OFFLINE", None)
    os.environ.update(QUIET)
    if constants is not None:
        setattr(constants, "HF_HUB_OFFLINE", True)  # noqa: B010
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        now = sys.modules.get(HUB_CONSTANTS)
        if now is not None and hasattr(now, "HF_HUB_OFFLINE"):
            if now is constants and isinstance(was, bool):
                setattr(now, "HF_HUB_OFFLINE", was)  # noqa: B010 - a module's attribute, not ours
            else:  # imported inside the block: what it would have read outside it
                outside = os.environ.get("HF_HUB_OFFLINE") or os.environ.get("TRANSFORMERS_OFFLINE")
                setattr(now, "HF_HUB_OFFLINE", _truthy(outside))  # noqa: B010


def _truthy(value: str | None) -> bool:
    """As the hub reads its variables."""
    return value is not None and value.strip().upper() in ("1", "ON", "YES", "TRUE")


def status(importer: Importer = importlib.import_module) -> Status:
    """The engine and the models on this machine; no socket (`quiet`, `local_files_only`)."""
    with quiet():
        try:
            module = importer(MODULE)
        except ImportError:
            return Status(None, {repo: False for repo in MODELS})
        try:
            hub = importer(HUB)
        except ImportError:
            return Status(_version(module), {repo: False for repo in MODELS})
        return Status(_version(module), {repo: _cached(hub, repo) for repo in MODELS})


def detect(importer: Importer = importlib.import_module) -> Diarizer | None:
    """The diarizer when the engine and every model are on this machine, else None (the run then
    says `NOT_SEPARATED`). Never downloads anything."""
    return Pyannote(importer) if status(importer).ready else None


def fetch(
    env: Mapping[str, str],
    importer: Importer = importlib.import_module,
    progress: Callable[[str], None] | None = None,
) -> list[str]:
    """The one network event: each model the pipeline reads into the hub's cache, with the token in
    `env[HF_TOKEN]` when there is one, for these requests only. The repositories fetched; `Refused`
    when the hub refuses one; ImportError when the extra is not installed."""
    hub = importer(HUB)
    token = env.get(TOKEN) or None
    fetched: list[str] = []
    for repo in MODELS:
        if progress is not None:
            progress(repo)
        try:
            hub.snapshot_download(repo, token=token)
        except Exception as e:  # the hub's own family of errors; which ones mean "refused" is below
            if _refused(e):
                raise Refused(repo) from None
            raise OSError(f"the Hugging Face hub could not hand over {repo} ({type(e).__name__})") from None
        fetched.append(repo)
    return fetched


def _refused(error: BaseException | None) -> bool:
    """A gated repository whose conditions are not accepted, or a token that may not read it; the
    hub sometimes wraps the refusal (`LocalEntryNotFoundError ... from` it), so its causes count."""
    seen: set[int] = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        names = {klass.__name__ for klass in type(error).__mro__}
        if names & {"GatedRepoError", "RepositoryNotFoundError"}:
            return True
        response = getattr(error, "response", None)
        if getattr(response, "status_code", None) in (401, 403):
            return True
        error = error.__cause__ or error.__context__
    return False


def _cached(hub: Any, repo: str) -> bool:
    try:
        hub.snapshot_download(repo, local_files_only=True)
    except Exception:  # the hub raises its own family of errors; any of them means "not here"
        return False
    return True


def _version(module: Any) -> str:
    return str(getattr(module, "__version__", "") or "installed")


class Pyannote:
    """pyannote.audio's pretrained pipeline, loaded once from the hub's cache with the hub offline."""

    name = ENGINE
    model = MODEL

    def __init__(self, importer: Importer = importlib.import_module) -> None:
        self._import = importer
        self._pipeline: Any = None

    def diarize(self, samples: Sequence[float], rate: int, speakers: int | None = None) -> list[Heard]:
        numpy, torch = self._import("numpy"), self._import("torch")
        with quiet():
            if self._pipeline is None:
                try:
                    self._pipeline = self._import(MODULE).Pipeline.from_pretrained(MODEL)
                except OSError:  # the hub's LocalEntryNotFoundError is a FileNotFoundError
                    raise ModelsMissing() from None
                if self._pipeline is None:  # 4.x answers None for a checkpoint it cannot find
                    raise ModelsMissing()
            waveform = torch.from_numpy(numpy.asarray(samples, dtype=numpy.float32).reshape(1, -1))
            options = {"num_speakers": speakers} if speakers else {}
            found = self._pipeline({"waveform": waveform, "sample_rate": rate}, **options)
        annotation = getattr(found, "speaker_diarization", found)  # 4.x answers an object, 3.x the annotation
        return [
            (float(segment.start), float(segment.end), str(label))
            for segment, _track, label in annotation.itertracks(yield_label=True)
        ]

    def channels(self, path: Path) -> tuple[list[Sequence[float]], int]:
        with quiet():
            audio = self._import(MODULE).Audio(sample_rate=SAMPLE_RATE, mono=None)
            waveform, rate = audio(str(path))
        return [waveform[i].numpy() for i in range(int(waveform.shape[0]))], int(rate)
