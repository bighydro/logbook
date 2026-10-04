"""`logbook transcribe voice-memos`: the local transcription step RFC 0023 leaves to later.

For every standing `voice-memo/v1` line whose audio is in the attachment store, one `transcript/v1`
line (RFC 0004) through the one transcript mapping (`transcript.draft`, ADR 0017):

- `raw_id` is the memo's own `raw_id`, so a memo is transcribed once however often the command runs
  (the `(source, raw_id)` dedupe of `append_many`, checked here first so no audio is decoded twice);
- `payload.provenance` is `{source, engine, model}` — `source` the memo line's `id`, the engine and
  model that heard it — and `extra.recording` the memo's `raw_id`, as RFC 0023 says;
- `content` is the text, one segment per line, a `text/plain` attachment (SPEC §1.1), never inline;
- `language` is what the engine detected on the first chunk and was then told to keep;
- `at`, `end`, `tz` and `title` are the memo's; tier 2 (RFC 0004), or the memo's when that is higher.

A memo that is retracted, or that another line `supersedes`, is not transcribed; the transcript of
the standing line points at the standing line. The transcript never carries `supersedes`: the memo
stays what it was, the transcript sits beside it.

**Nothing leaves the machine.** The engines run locally — `mlx-whisper` on Apple silicon, else
`faster-whisper`, each an optional extra (`openlogbook[transcribe]`) imported only when the command
runs — and while they run the Hugging Face hub is told it is offline (`HF_HUB_OFFLINE`), so no socket
is opened for any reason. A model not yet on the machine stops the command with the one flag that
fetches it, `--fetch-model`, which downloads the model before the first chunk and nothing else, ever.

Long recordings are read in fixed windows of `CHUNK_S` seconds, so a two-hour memo never sits in an
engine's context at once; segment times are offset by the window's start. A memo whose audio holds
no words is skipped and counted.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from platform import machine
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from .adapters import transcript
from .core import attachments
from .core.chain import Line
from .core.store import Logbook

SOURCE = "transcription"  # the `source` of every transcript this command writes, whatever the engine
MEMO_KIND = "voice-memo"
MEDIA_TYPE = "text/plain"
TIER = 2  # RFC 0004: spoken personal content
DEFAULT_MODEL = "small"
CHUNK_S = 600.0  # ten minutes of audio per engine call
SAMPLE_RATE = 16_000  # what both engines decode to
EXTRA = "openlogbook[transcribe]"
OFFLINE = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")

NO_AUDIO = "skipped_no_audio"
RETRACTED = "skipped_retracted"
SUPERSEDED = "skipped_superseded"
NO_SPEECH = "skipped_no_speech"
PHRASES = {
    NO_AUDIO: "without their audio in the store (import with --attachments)",
    RETRACTED: "retracted",
    SUPERSEDED: "superseded by a later line",
    NO_SPEECH: "with no words in them",
}


class EngineMissing(Exception):
    """No transcription engine is installed."""


class ModelMissing(Exception):
    """The model is not on this machine and the run was not told to fetch it."""


@dataclass(frozen=True)
class Segment:
    start: float  # seconds from the start of the recording
    end: float
    text: str


@dataclass(frozen=True)
class Result:
    """What an engine heard in one window of audio."""

    segments: list[Segment]
    language: str  # BCP-47-ish, as the engine names it (`en`, `nb`)


class Engine(Protocol):
    """A local speech-to-text engine. `load` decodes a file to mono samples at `rate`; `transcribe`
    hears one window of them, in `language` when told, detecting it when not."""

    name: str
    model: str

    def ready(self) -> bool: ...
    def fetch(self) -> None: ...
    def load(self, path: Path) -> tuple[Sequence[float], int]: ...
    def transcribe(self, samples: Sequence[float], rate: int, language: str | None) -> Result: ...


@dataclass(frozen=True)
class Memo:
    """A standing voice-memo line with its audio in the store: what one run has to do."""

    line: Line
    audio: Path

    @property
    def id(self) -> str:
        return str(self.line["id"])

    @property
    def raw_id(self) -> str:
        return str(self.line["payload"]["raw_id"])

    @property
    def title(self) -> str:
        return str(self.line["payload"].get("title") or "voice memo")

    @property
    def at(self) -> str:
        return str(self.line["at"])


@dataclass(frozen=True)
class Done:
    memo: Memo
    language: str
    words: int
    seconds: float  # how long the engine took


@dataclass
class Report:
    found: int  # memos to transcribe when the run began
    already: int  # memos a transcript already stands for
    counts: dict[str, int]  # what was skipped and why
    memos: list[Memo]  # the ones found, in time order
    dry_run: bool
    written: int = 0
    done: list[Done] = field(default_factory=list)


def run(
    lb: Logbook,
    engine: Engine | None,
    since: str | None = None,
    dry_run: bool = False,
    fetch_model: bool = False,
    chunk_s: float = CHUNK_S,
    progress: Callable[[str], None] | None = None,
) -> Report:
    """Transcribe every standing voice memo from local day `since` on whose audio is in the store
    and that has no transcript yet; a line is appended per memo as soon as it is heard, so an
    interrupted run keeps what it did and the next run carries on. `dry_run` lists and writes
    nothing (no engine needed). `progress` gets one line per memo."""
    counts: dict[str, int] = {}
    memos, already = _standing(lb, since, counts)
    report = Report(len(memos), already, counts, memos, dry_run)
    if dry_run or not memos:
        return report
    if engine is None:
        raise EngineMissing(f"no transcription engine; install {EXTRA}")
    if not engine.ready():
        if not fetch_model:
            raise ModelMissing(
                f"model {engine.model!r} is not on this machine; run once with --fetch-model to download it"
                " (the only time this command uses the network)"
            )
        engine.fetch()
    zone = ZoneInfo(str(lb.meta["timezone"]))
    with offline():
        report.written = lb.append_many(_drafts(lb, engine, memos, chunk_s, report, zone, progress))
    return report


def chunks(samples: int, rate: int, chunk_s: float) -> list[tuple[int, int]]:
    """Fixed windows of `chunk_s` seconds over `samples` samples at `rate`, as (start, end) sample
    offsets; the last may be short; none for no audio."""
    size = max(1, int(rate * chunk_s))
    return [(start, min(start + size, samples)) for start in range(0, samples, size)]


def describe(report: Report) -> str:
    """The closing lines of the command: what was done, what already was, what was skipped."""
    memos = _plural(report.found if report.dry_run else report.written, "voice memo")
    already = f" ({report.already} already transcribed)" if report.already else ""
    if report.dry_run:
        head = f"dry run: {memos} would be transcribed{already}; nothing written"
    else:
        head = f"transcribed {memos}{already}"
    skipped = [f"{n:,} {PHRASES.get(key, key)}" for key, n in report.counts.items() if n]
    return head + (f"\n  skipped {', '.join(skipped)}" if skipped else "")


# -- the memos -------------------------------------------------------------------------------------


def _standing(lb: Logbook, since: str | None, counts: dict[str, int]) -> tuple[list[Memo], int]:
    """The memos to transcribe, in time order, and how many already have a transcript. A retracted
    memo, one another line supersedes, and one whose audio is not in the store are counted."""
    with lb.index() as idx:
        hidden = {str((r.get("payload") or {}).get("supersedes")) for r in idx.retractions()}
        superseded = idx.superseded(MEMO_KIND)
        lines = sorted(idx.by_kind(MEMO_KIND, first_day=since), key=lambda line: (line["at"], line["seq"]))
        keys = {(SOURCE, str(line["payload"]["raw_id"])) for line in lines if line["payload"].get("raw_id")}
        done = idx.existing(keys) if keys else set()
    memos: list[Memo] = []
    already = 0
    for line in lines:
        payload = line.get("payload") or {}
        raw_id = payload.get("raw_id")
        if raw_id is None:
            continue
        if line["id"] in hidden:
            _count(counts, RETRACTED)
        elif line["id"] in superseded:
            _count(counts, SUPERSEDED)
        elif (SOURCE, str(raw_id)) in done:
            already += 1
        else:
            audio = _audio(lb, payload)
            if audio is None:
                _count(counts, NO_AUDIO)
            else:
                memos.append(Memo(line, audio))
    return memos, already


def _audio(lb: Logbook, payload: dict[str, Any]) -> Path | None:
    """The memo's audio in the §1.1 store, or None: a `media` with a `path` whose file is there."""
    media = payload.get("media")
    if not isinstance(media, dict) or not isinstance(media.get("path"), str):
        return None
    parts = Path(media["path"]).parts
    if len(parts) != 2 or parts[0] != attachments.DIR:
        return None
    file = lb.root / parts[0] / parts[1]
    return file if file.is_file() else None


# -- the transcripts -------------------------------------------------------------------------------


def _drafts(
    lb: Logbook,
    engine: Engine,
    memos: list[Memo],
    chunk_s: float,
    report: Report,
    zone: ZoneInfo,
    progress: Callable[[str], None] | None,
) -> Iterator[dict[str, Any]]:
    for memo in memos:
        started = time.monotonic()
        text, language, windows, segments = _hear(engine, memo.audio, chunk_s)
        seconds = time.monotonic() - started
        if not segments:
            _count(report.counts, NO_SPEECH)
            if progress is not None:
                progress(f"  {_clock(memo.at, zone)}  {memo.title}: no words heard ({seconds:.1f}s)")
            continue
        data = text.encode("utf-8")
        lb.attach(data)
        words = len(text.split())
        report.done.append(Done(memo, language, words, seconds))
        if progress is not None:
            heard = f"{_plural(words, 'word')}, {language}, {seconds:.1f}s"
            progress(f"  {_clock(memo.at, zone)}  {memo.title}: {heard}")
        yield _draft(memo, engine, data, language, len(windows), len(segments))


def _hear(
    engine: Engine, audio: Path, chunk_s: float
) -> tuple[str, str, list[tuple[int, int]], list[Segment]]:
    """The text of one recording, window by window; the language detected on the first window is
    asked of every later one, so a recording is heard in one language."""
    samples, rate = engine.load(audio)
    windows = chunks(len(samples), rate, chunk_s)
    language: str | None = None
    segments: list[Segment] = []
    for start, end in windows:
        result = engine.transcribe(samples[start:end], rate, language)
        language = language or (result.language or None)
        offset = start / rate
        segments += [
            Segment(s.start + offset, s.end + offset, s.text.strip())
            for s in result.segments
            if s.text.strip()
        ]
    text = "".join(f"{s.text}\n" for s in segments)
    return text, language or "", windows, segments


def _draft(
    memo: Memo, engine: Engine, data: bytes, language: str, windows: int, segments: int
) -> dict[str, Any]:
    line = memo.line
    draft = transcript.draft(
        source=SOURCE,
        at=memo.at,
        end=line.get("end") if isinstance(line.get("end"), str) else None,
        raw_id=memo.raw_id,
        content=attachments.reference(data, MEDIA_TYPE),
        turns=[],
        tier=max(TIER, int(line["tier"])),
        title=line["payload"].get("title") or None,
        participants=[],
        language=language or None,
        extra={"recording": memo.raw_id, "chunks": windows, "segments": segments, "format": "text"},
    )
    draft["tz"] = line.get("tz")
    draft["payload"]["provider"] = engine.name  # RFC 0004: the tool that produced the text
    draft["payload"]["provenance"] = {"source": memo.id, "engine": engine.name, "model": engine.model}
    return draft


# -- engines ---------------------------------------------------------------------------------------


def detect(
    model: str = DEFAULT_MODEL,
    importer: Callable[[str], Any] = importlib.import_module,
    platform: tuple[str, str] | None = None,
) -> Engine:
    """The engine this machine has: `mlx-whisper` first on Apple silicon, `faster-whisper` wherever
    it is installed; EngineMissing, naming the extra, when neither is."""
    here = platform or (sys.platform, machine())
    candidates: list[type[MlxWhisper] | type[FasterWhisper]] = (
        [MlxWhisper, FasterWhisper] if here == ("darwin", "arm64") else [FasterWhisper, MlxWhisper]
    )
    for engine in candidates:
        try:
            module = importer(engine.module)
        except ImportError:
            continue
        return engine(model, module, importer)
    raise EngineMissing(
        f"no transcription engine is installed; install {EXTRA} (mlx-whisper on Apple silicon,"
        " faster-whisper elsewhere; mlx-whisper decodes audio with ffmpeg, which must be on the PATH)"
    )


class MlxWhisper:
    """Apple's MLX port of Whisper: models from `mlx-community/whisper-<size>-mlx`."""

    name = "mlx-whisper"
    module = "mlx_whisper"

    def __init__(self, model: str, mlx: Any, importer: Callable[[str], Any]) -> None:
        self.model, self._mlx, self._import = model, mlx, importer
        self.repo_id = self.repo(model)

    @staticmethod
    def repo(model: str) -> str:
        return model if "/" in model else f"mlx-community/whisper-{model}-mlx"

    def ready(self) -> bool:
        return cached(self._import, self.repo_id)

    def fetch(self) -> None:
        download(self._import, self.repo_id)

    def load(self, path: Path) -> tuple[Sequence[float], int]:
        audio = self._import("mlx_whisper.audio")
        samples: Sequence[float] = audio.load_audio(str(path))
        return samples, int(getattr(audio, "SAMPLE_RATE", SAMPLE_RATE))

    def transcribe(self, samples: Sequence[float], rate: int, language: str | None) -> Result:
        options: dict[str, Any] = {"path_or_hf_repo": self.repo_id, "verbose": False}
        if language:
            options["language"] = language
        out = self._mlx.transcribe(samples, **options)
        segments = [
            Segment(float(s.get("start", 0.0)), float(s.get("end", 0.0)), str(s.get("text", "")))
            for s in out.get("segments", [])
        ]
        return Result(segments, str(out.get("language") or language or ""))


class FasterWhisper:
    """CTranslate2's Whisper: models from `Systran/faster-whisper-<size>`."""

    name = "faster-whisper"
    module = "faster_whisper"

    def __init__(self, model: str, fw: Any, importer: Callable[[str], Any]) -> None:
        self.model, self._fw, self._import = model, fw, importer
        self.repo_id = self.repo(model)
        self._loaded: Any = None

    @staticmethod
    def repo(model: str) -> str:
        return model if "/" in model else f"Systran/faster-whisper-{model}"

    def ready(self) -> bool:
        return cached(self._import, self.repo_id)

    def fetch(self) -> None:
        download(self._import, self.repo_id)

    def load(self, path: Path) -> tuple[Sequence[float], int]:
        samples: Sequence[float] = self._fw.decode_audio(str(path), sampling_rate=SAMPLE_RATE)
        return samples, SAMPLE_RATE

    def transcribe(self, samples: Sequence[float], rate: int, language: str | None) -> Result:
        if self._loaded is None:
            self._loaded = self._fw.WhisperModel(self.repo_id, local_files_only=True)
        found, info = self._loaded.transcribe(samples, language=language)
        segments = [
            Segment(float(s.start), float(s.end), str(s.text)) for s in found
        ]  # a generator: heard here
        return Result(segments, str(getattr(info, "language", None) or language or ""))


def cached(importer: Callable[[str], Any], repo_id: str) -> bool:
    """Whether the hub's cache on this machine holds the model; asked without the network."""
    hub = importer("huggingface_hub")
    try:
        hub.snapshot_download(repo_id, local_files_only=True)
    except Exception:  # the hub raises its own family of errors; any of them means "not here"
        return False
    return True


def download(importer: Callable[[str], Any], repo_id: str) -> None:
    hub = importer("huggingface_hub")
    hub.snapshot_download(repo_id)


class offline:
    """While transcribing, the hub is offline: the engines never reach out, whatever they would do."""

    def __enter__(self) -> None:
        self.before = {name: os.environ.get(name) for name in OFFLINE}
        for name in OFFLINE:
            os.environ[name] = "1"

    def __exit__(self, *exc: object) -> None:
        for name, value in self.before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


# -- small things ----------------------------------------------------------------------------------


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def _plural(n: int, noun: str) -> str:
    return f"{n:,} {noun}" if n == 1 else f"{n:,} {noun}s"


def _clock(at: str, zone: ZoneInfo) -> str:
    try:
        when = datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(zone)
    except ValueError:
        return at
    return when.strftime("%Y-%m-%d %H:%M")
