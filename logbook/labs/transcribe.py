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

**Voices** (RFC 0038 §2). When the diarizer and its models are on this machine (`diarize.detect`),
the same run, on the samples the engine decoded, separates the voices and the line gains `speakers`
and `diarization`: each line of the text is given the voice that speaks most of it (of its words,
when the engine was asked for word times), the spans file goes into the attachment store beside the
text (`logbook.core.speakers`). A memo whose source keeps a call's sides apart says so on its line,
`extra.channels` naming the file's channels in order (`["mic", "system"]`); such a file is diarized a
channel at a time, and the microphone's voice is `from_me` when it is alone in its channel. Any other
recording, a stereo memo included, is one room. Without the diarizer the line is today's, and the run
says once, at the end, `speakers: not separated (logbook setup speakers --fetch-model)`.

**Heard again** (`derive speakers`, RFC 0038 §2.8). A standing transcript with no `speakers`, whose
recording (`provenance.source`, a voice memo not retracted) has its audio in the store, is heard again
by the Whisper model that heard it and separated: the text has to be heard again, because a plain-text
transcript keeps no times and the labels need them. The result is a new line that `supersedes` the
old one, with the old line's `source`, `at`, `end`, `tz` and title and `raw_id` `<old raw_id>#speakers@
<the first 12 hex of the spans file's digest>`: the same voices heard in the same text are the same
spans, the same key, and the `(source, raw_id)` dedupe writes nothing twice. A line that is retracted
supersedes nothing. What it costs is said before anything is written (`cost`): the signed days whose
page changes, and the promises closed on the old lines, which are proposed again from the new ones.
"""

from __future__ import annotations

import importlib
import os
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from platform import machine
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from ..contrib.adapters import transcript
from ..core import attachments, speakers
from ..core.chain import Line
from ..core.store import Logbook
from . import diarize

SOURCE = "transcription"  # the `source` of every transcript this command writes, whatever the engine
MEMO_KIND = "voice-memo"
MEDIA_TYPE = "text/plain"
TIER = 2  # RFC 0004: spoken personal content
DEFAULT_MODEL = "small"
CHUNK_S = 600.0  # ten minutes of audio per engine call
SAMPLE_RATE = 16_000  # what both engines decode to
EXTRA = "openlogbook[transcribe]"
OFFLINE = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")

CHANNELS_KEY = "channels"  # `extra.channels` of a memo whose source keeps a call's sides apart
TRANSCRIPT_KIND = "transcript"
SPEAKERS_KEY = "#speakers@"  # `<old raw_id>#speakers@<12 hex>`, the key of a transcript heard again
SPANS_KEY_HEX = 12

NO_AUDIO = "skipped_no_audio"
RETRACTED = "skipped_retracted"
SUPERSEDED = "skipped_superseded"
NO_SPEECH = "skipped_no_speech"
NO_RECORDING = "skipped_no_recording"
RECORDING_RETRACTED = "skipped_recording_retracted"
RECORDING_SUPERSEDED = "skipped_recording_superseded"
PHRASES = {
    NO_AUDIO: "without their audio in the store (import with --attachments)",
    RETRACTED: "retracted",
    SUPERSEDED: "superseded by a later line",
    NO_SPEECH: "with no words in them",
    NO_RECORDING: "with no recording of their own in the record (a provider's, a file's)",
    RECORDING_RETRACTED: "whose recording was retracted",
    RECORDING_SUPERSEDED: "whose recording a later line supersedes",
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
    words: tuple[tuple[float, float], ...] = ()  # each word's start and end, when the engine gave them


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
    separate: bool = True  # whether the run was to separate voices (`--no-speakers` says not)
    diarizer: str | None = None  # the diarizer that ran, None when none was on this machine
    separated: int = 0  # memos whose voices were separated
    voiceless: int = 0  # memos heard in which the diarizer found no voice
    rooms: int = 0  # memos whose source named two channels the diarizer could not read apart: one room
    unlabelled: int = 0  # memos whose text's lines could not be numbered as heard: written without voices


@dataclass(frozen=True)
class Hearing:
    """One recording heard: its text, one segment a line, the language, the windows, the segments,
    and the samples the engine decoded, for the diarizer to hear the same audio."""

    text: str
    language: str
    windows: list[tuple[int, int]]
    segments: list[Segment]
    samples: Sequence[float]
    rate: int


@dataclass(frozen=True)
class Voices:
    """The voices of one recording: the turns, labelled; for a recording whose sides were kept
    apart, the channel of each voice and the one that is `from_me`; how many channels it has."""

    turns: list[speakers.VoiceTurn]
    channels: int = 1
    channel_of: dict[str, str] | None = None
    from_me: str | None = None
    unread: bool = False  # the source named two channels the diarizer could not read apart


def run(
    lb: Logbook,
    engine: Engine | None,
    since: str | None = None,
    dry_run: bool = False,
    fetch_model: bool = False,
    chunk_s: float = CHUNK_S,
    progress: Callable[[str], None] | None = None,
    diarizer: diarize.Diarizer | None = None,
    separate: bool = True,
) -> Report:
    """Transcribe every standing voice memo from local day `since` on whose audio is in the store
    and that has no transcript yet; a line is appended per memo as soon as it is heard, so an
    interrupted run keeps what it did and the next run carries on. `dry_run` lists and writes
    nothing (no engine needed). `progress` gets one line per memo. With `diarizer` (and `separate`,
    the default) each memo's voices are separated in the same run; `separate` False is
    `--no-speakers`: no diarizer is used and nothing is said of voices."""
    counts: dict[str, int] = {}
    memos, already = _standing(lb, since, counts)
    diarizer = diarizer if separate else None
    report = Report(len(memos), already, counts, memos, dry_run, separate=separate)
    report.diarizer = diarizer.name if diarizer is not None else None
    if dry_run or not memos:
        return report
    if engine is None:
        raise EngineMissing(f"no transcription engine; install {EXTRA}")
    _ready(engine, fetch_model)
    zone = ZoneInfo(str(lb.meta["timezone"]))
    with diarize.quiet():  # the hub offline, and pyannote's usage reporting off, for the whole run
        report.written = lb.append_many(_drafts(lb, engine, memos, chunk_s, report, zone, progress, diarizer))
    return report


def hear(engine: Engine, audio: Path, fetch_model: bool = False, chunk_s: float = CHUNK_S) -> Result:
    """One recording heard by `engine` on this machine, window by window, with the hub offline: the
    segments with words in them and the language detected, for a caller that writes its own line
    (`logbook day reflect`). The model must be on this machine unless `fetch_model` (ModelMissing)."""
    _ready(engine, fetch_model)
    with diarize.quiet():  # the hub offline, its own switch included, whoever imported it first
        heard = _hear(engine, audio, chunk_s)
    return Result(heard.segments, heard.language)


def _ready(engine: Engine, fetch_model: bool) -> None:
    """The model on this machine, fetched first when `fetch_model` says so; else ModelMissing."""
    if engine.ready():
        return
    if not fetch_model:
        raise ModelMissing(
            f"model {engine.model!r} is not on this machine; run once with --fetch-model to download it"
            " (the only time this command uses the network)"
        )
    engine.fetch()


def chunks(samples: int, rate: int, chunk_s: float) -> list[tuple[int, int]]:
    """Fixed windows of `chunk_s` seconds over `samples` samples at `rate`, as (start, end) sample
    offsets; the last may be short; none for no audio."""
    size = max(1, int(rate * chunk_s))
    return [(start, min(start + size, samples)) for start in range(0, samples, size)]


def describe(report: Report) -> str:
    """The closing lines of the command: what was done, what already was, what was skipped; then,
    for a run that heard a memo and was to separate voices, how many it separated, or, with no
    diarizer on this machine, the one sentence that says so and names the command that fetches it."""
    memos = _plural(report.found if report.dry_run else report.written, "voice memo")
    already = f" ({report.already} already transcribed)" if report.already else ""
    if report.dry_run:
        head = f"dry run: {memos} would be transcribed{already}; nothing written"
    else:
        head = f"transcribed {memos}{already}"
    skipped = [f"{n:,} {PHRASES.get(key, key)}" for key, n in report.counts.items() if n]
    text = head + (f"\n  skipped {', '.join(skipped)}" if skipped else "")
    if report.dry_run or not report.done or not report.separate:
        return text
    if report.diarizer is None:
        return f"{text}\n{diarize.NOT_SEPARATED}"
    said = f"  voices separated in {_plural(report.separated, 'voice memo')}"
    if report.voiceless:
        said += f"; no voice found in {report.voiceless:,}"
    return f"{text}\n{said}{_heard_text(report.rooms, report.unlabelled)}"


def _heard_text(rooms: int, unlabelled: int) -> str:
    """What a run that separated voices could not do as asked, a line each; nothing when nothing."""
    out = ""
    if rooms:
        out += f"\n  heard as one room, the two channels its source named not read apart: {rooms:,}"
    if unlabelled:
        out += f"\n  voices heard, the text's lines not numbered as heard, so not written: {unlabelled:,}"
    return out


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
    diarizer: diarize.Diarizer | None = None,
) -> Iterator[dict[str, Any]]:
    for memo in memos:
        started = time.monotonic()
        voices: Voices | None = None
        with lb.attachment(memo.audio.name) as audio:  # the plaintext, when the store holds it sealed
            heard = _hear(engine, audio, chunk_s)
            if diarizer is not None and heard.segments:
                voices = separate_voices(diarizer, heard, audio, channels_of(memo.line))
        seconds = time.monotonic() - started
        if not heard.segments:
            _count(report.counts, NO_SPEECH)
            if progress is not None:
                progress(f"  {_clock(memo.at, zone)}  {memo.title}: no words heard ({seconds:.1f}s)")
            continue
        data = heard.text.encode("utf-8")
        lb.attach(data)  # a transcript is tier 2 or higher: sealed when the record names recipients
        words = len(heard.text.split())
        report.done.append(Done(memo, heard.language, words, seconds))
        draft = _draft(memo, engine, data, heard.language, len(heard.windows), len(heard.segments))
        said = ""
        if voices is not None and voices.unread:
            report.rooms += 1
        labelled = (
            label(draft, voices, heard.segments, data, diarizer, memo)
            if voices is not None and voices.turns and diarizer is not None
            else None
        )
        if labelled is not None:
            lb.attach(labelled)  # the spans file, sealed as the text is
            report.separated += 1
            said = f", {_plural(len(draft['payload']['speakers']), 'voice')}"
        elif voices is not None and voices.turns:
            report.unlabelled += 1
            said = ", voices not written"
        elif voices is not None:
            report.voiceless += 1
            said = ", no voice found"
        if progress is not None:
            text = f"{_plural(words, 'word')}, {heard.language}{said}, {seconds:.1f}s"
            progress(f"  {_clock(memo.at, zone)}  {memo.title}: {text}")
        yield draft


def _hear(engine: Engine, audio: Path, chunk_s: float) -> Hearing:
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
            Segment(
                s.start + offset,
                s.end + offset,
                s.text.strip(),
                tuple((a + offset, b + offset) for a, b in s.words),
            )
            for s in result.segments
            if s.text.strip()
        ]
    text = "".join(f"{s.text}\n" for s in segments)
    return Hearing(text, language or "", windows, segments, samples, rate)


# -- the voices ------------------------------------------------------------------------------------


def channels_of(line: Line) -> list[str] | None:
    """The channels a memo's source names, in the file's order, when it keeps a call's sides apart:
    `extra.channels`, `mic` and `system` each once. None for anything else: one room."""
    extra = (line.get("payload") or {}).get("extra")
    said = extra.get(CHANNELS_KEY) if isinstance(extra, dict) else None
    if isinstance(said, list) and sorted(map(str, said)) == sorted(speakers.CHANNELS) and len(said) == 2:
        return [str(name) for name in said]
    return None


def separate_voices(
    diarizer: diarize.Diarizer,
    heard: Hearing,
    audio: Path,
    channels: list[str] | None,
    hint: int | None = None,
) -> Voices:
    """The voices of a recording. A room: the samples the engine decoded, heard once, `hint` the
    number of voices the owner says it held. A recording whose source names its channels: each
    channel heard on its own, labelled by the channel; the microphone's voice is `from_me` when it
    is the one voice there. A file that does not hold the channels its source named is a room."""
    if channels is not None:
        try:
            apart, rate = diarizer.channels(audio)
        except Exception:  # a decoder that cannot keep this file's channels apart: it is heard as a room
            apart, rate = [], 0
        if len(apart) == len(channels):
            turns = speakers.label_channels(
                {name: diarizer.diarize(samples, rate) for name, samples in zip(channels, apart, strict=True)}
            )
            voices = speakers.order(turns)
            channel_of = {voice: voice.split(".")[0] for voice in voices}
            return Voices(turns, len(channels), channel_of, speakers.MIC if speakers.MIC in voices else None)
    turns = speakers.label_room(diarizer.diarize(heard.samples, heard.rate, hint))
    return Voices(turns, unread=channels is not None)


def label(
    draft: dict[str, Any],
    voices: Voices,
    segments: Sequence[Segment],
    data: bytes,
    diarizer: diarize.Diarizer,
    memo: Memo,
) -> bytes | None:
    """`speakers` and `diarization` on `draft`, the transcript of `memo` whose text is `data`; the
    spans file's bytes, for the caller to store. A segment whose text holds several lines is a
    segment per line of the content, each with the segment's times, so the spans number the lines.
    None, and `draft` untouched, when they would not number the segments a reader counts in the text
    (`speakers.segment_count`: a text that happens to read as SRT): a spans file must never be wrong."""
    spans = [
        speakers.Span(s.start, s.end, s.words)
        for s in segments
        for part in s.text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if part.strip()
    ]
    if speakers.segment_count(data, MEDIA_TYPE) != len(spans):
        return None
    assigned = speakers.assign(spans, voices.turns)
    content = draft["payload"]["content"]["sha256"]
    spans_data = speakers.spans_bytes(speakers.spans_document(content, spans, assigned, voices.turns))
    payload = draft["payload"]
    payload["speakers"] = speakers.speakers_field(
        speakers.order(voices.turns),
        assigned,
        speakers.seconds(voices.turns),
        channels=voices.channel_of,
        from_me=voices.from_me,
    )
    media = (memo.line.get("payload") or {}).get("media") or {}
    payload["diarization"] = speakers.diarization_field(
        diarizer.name,
        voices.channels,
        model=diarizer.model,
        audio=media.get("sha256") if isinstance(media.get("sha256"), str) else None,
        overlap_s=speakers.overlap_seconds(voices.turns),
        spans=attachments.reference(spans_data, speakers.MEDIA_TYPE),
    )
    return spans_data


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


# -- heard again: derive speakers --------------------------------------------------------------------


@dataclass(frozen=True)
class Unseparated:
    """A standing transcript whose voices were never separated, its recording, and the Whisper model
    that heard it."""

    line: Line
    memo: Memo
    model: str

    @property
    def id(self) -> str:
        return str(self.line["id"])


@dataclass
class Again:
    """What `derive speakers` found and did."""

    found: list[Unseparated]  # in time order
    already: int  # standing transcripts whose voices are separated already
    counts: dict[str, int]  # what cannot be heard again, and why
    signed: list[str]  # the signed local days whose page a new line would change
    promises: int  # promises closed on the transcripts found, which a new line proposes again
    dry_run: bool = False
    written: int = 0
    same: int = 0  # heard again into the same spans: the key is in the record, nothing written
    voiceless: int = 0  # heard again with no voice found: nothing written
    rooms: int = 0  # two channels named by the source, not read apart: heard as one room
    unlabelled: int = 0  # voices heard but the text's lines not numbered as heard: nothing written


def unseparated(lb: Logbook, since: str | None = None, dry_run: bool = False) -> Again:
    """The standing transcripts from local day `since` on with no `speakers` whose recording's audio
    is in the store, in time order; the ones that cannot be heard again counted; what writing their
    new lines would cost. Reads the index; writes nothing."""
    from ..contrib.promises import closes
    from ..core import day_start, signing, stays
    from ..core.store import retractions

    counts: dict[str, int] = {}
    with lb.index() as idx:
        retracted = retractions(idx.retractions())
        every = idx.by_kind(TRANSCRIPT_KIND)
        window = idx.by_kind(TRANSCRIPT_KIND, first_day=since) if since else every
        sources = {_provenance(line).get("source") for line in window}
        memos = idx.by_ids(str(s) for s in sources if isinstance(s, str))
        signatures = signing.standing(idx, str(lb.meta.get("owner_id") or "") or None)
        tasks = idx.by_kind("task")
        memo_superseded = idx.superseded(MEMO_KIND)
    replaced = {  # a line a standing transcript supersedes; a retracted one supersedes nothing
        str(line["payload"]["supersedes"])
        for line in every
        if str(line["id"]) not in retracted and isinstance((line.get("payload") or {}).get("supersedes"), str)
    }
    separated = {  # the recordings a standing line has separated already, whatever the day
        str(_provenance(line).get("source"))
        for line in every
        if (line.get("payload") or {}).get("speakers")
        and str(line["id"]) not in retracted
        and str(line["id"]) not in replaced
    }
    found: list[Unseparated] = []
    already = 0
    for line in sorted(window, key=lambda line: (str(line["at"]), int(line["seq"]))):
        payload = line.get("payload") or {}
        if str(line["id"]) in retracted or str(line["id"]) in replaced:
            continue
        provenance = _provenance(line)
        source = str(provenance.get("source"))
        if payload.get("speakers") or source in separated or source in {item.memo.id for item in found}:
            already += 1  # one recording, one line with its voices: never two standing for it
            continue
        memo = memos.get(source)
        if memo is None or memo.get("kind") != MEMO_KIND or not (memo.get("payload") or {}).get("raw_id"):
            _count(counts, NO_RECORDING)
        elif str(memo["id"]) in retracted:
            _count(counts, RECORDING_RETRACTED)
        elif str(memo["id"]) in memo_superseded:
            _count(counts, RECORDING_SUPERSEDED)
        elif (audio := _audio(lb, memo.get("payload") or {})) is None:
            _count(counts, NO_AUDIO)
        else:
            model = provenance.get("model")
            found.append(Unseparated(line, Memo(memo, audio), str(model) if model else DEFAULT_MODEL))
    bounds = day_start.of(lb.meta)
    days = {
        bounds.day(at).isoformat() for item in found if (at := stays.instant(item.line["at"])) is not None
    }
    ids = {item.id for item in found}
    by_id = {str(task["id"]): task for task in tasks}
    closed = [
        task_id
        for task_id in closes(tasks, retracted).values()
        if str((((by_id.get(task_id) or {}).get("payload") or {}).get("extra") or {}).get("origin")) in ids
    ]
    return Again(found, already, counts, sorted(days & set(signatures)), len(closed), dry_run)


def cost(report: Again) -> list[str]:
    """What writing the new lines changes, said before anything is written (RFC 0038 §2.8)."""
    said: list[str] = []
    if report.signed:
        said.append(
            f"signed days whose page changes: {', '.join(report.signed)}; each signature reads"
            " page_matches false until the day is signed again (logbook day sign DAY)"
        )
    if report.promises:
        said.append(
            f"{_plural(report.promises, 'promise')} closed on these transcripts will be proposed again"
            " from the new lines, a promise's id being its line's; `promises done ID` closes one again"
        )
    return said


def rehear(
    lb: Logbook,
    report: Again,
    engine_for: Callable[[str], Engine],
    diarizer: diarize.Diarizer,
    hint: int | None = None,
    chunk_s: float = CHUNK_S,
    progress: Callable[[str], None] | None = None,
) -> Again:
    """Hear each transcript `unseparated` found again and separate its voices, a new line each that
    supersedes the old one; `engine_for(model)` gives the engine for a Whisper model, and every
    model must be on this machine before anything is heard (ModelMissing). `hint` is the number of
    voices the owner says a room held. A line is appended as soon as it is heard."""
    engines: dict[str, Engine] = {}
    for item in report.found:
        if item.model not in engines:
            engines[item.model] = engine_for(item.model)
            _ready(engines[item.model], fetch_model=False)
    if not report.found:
        return report
    zone = ZoneInfo(str(lb.meta["timezone"]))

    def same(_draft: dict[str, Any]) -> None:
        report.same += 1

    with diarize.quiet():
        report.written = lb.append_many(
            _again(lb, report, engines, diarizer, hint, chunk_s, zone, progress), skipped=same
        )
    return report


def _again(
    lb: Logbook,
    report: Again,
    engines: Mapping[str, Engine],
    diarizer: diarize.Diarizer,
    hint: int | None,
    chunk_s: float,
    zone: ZoneInfo,
    progress: Callable[[str], None] | None,
) -> Iterator[dict[str, Any]]:
    for item in report.found:
        engine, memo, old = engines[item.model], item.memo, item.line
        started = time.monotonic()
        voices: Voices | None = None
        with lb.attachment(memo.audio.name) as audio:
            heard = _hear(engine, audio, chunk_s)
            if heard.segments:
                voices = separate_voices(diarizer, heard, audio, channels_of(memo.line), hint)
        seconds = time.monotonic() - started
        title = str((old.get("payload") or {}).get("title") or memo.title)
        if voices is not None and voices.unread:
            report.rooms += 1
        if voices is None or not voices.turns:
            if voices is None:
                _count(report.counts, NO_SPEECH)
            else:
                report.voiceless += 1
            if progress is not None:
                said = "no words heard" if voices is None else "no voice found"
                progress(f"  {_clock(str(old['at']), zone)}  {title}: {said} ({seconds:.1f}s)")
            continue
        data = heard.text.encode("utf-8")
        draft = _draft(memo, engine, data, heard.language, len(heard.windows), len(heard.segments))
        spans = label(draft, voices, heard.segments, data, diarizer, memo)
        if spans is None:
            report.unlabelled += 1
            if progress is not None:
                progress(f"  {_clock(str(old['at']), zone)}  {title}: voices not written ({seconds:.1f}s)")
            continue
        payload = draft["payload"]
        if (old.get("payload") or {}).get("title"):  # the old line's title; else the memo's, as at ingest
            payload["title"] = str(old["payload"]["title"])
        old_raw_id = (old.get("payload") or {}).get("raw_id") or memo.raw_id
        key = payload["diarization"]["spans"]["sha256"][:SPANS_KEY_HEX]
        payload["raw_id"] = f"{old_raw_id}{SPEAKERS_KEY}{key}"
        payload["supersedes"] = str(old["id"])
        draft.update(at=old["at"], end=old.get("end"), tz=old.get("tz"), source=old["source"])
        draft["tier"] = max(int(draft["tier"]), int(old["tier"]))
        lb.attach(data)
        lb.attach(spans)
        if progress is not None:
            voices_said = _plural(len(payload["speakers"]), "voice")
            progress(f"  {_clock(str(old['at']), zone)}  {title}: {voices_said}, {seconds:.1f}s")
        yield draft


def found_rows(report: Again, zone: ZoneInfo) -> list[str]:
    """A row per transcript `unseparated` found, its local time and title, for a dry run."""
    rows = []
    for item in report.found:
        title = (item.line.get("payload") or {}).get("title") or item.memo.title
        rows.append(f"  {_clock(str(item.line['at']), zone)}  {title}")
    return rows


def describe_again(report: Again) -> str:
    """The closing lines of `derive speakers`."""
    already = f" ({report.already:,} separated already)" if report.already else ""
    if not report.found:
        text = f"nothing to separate{already}"
    elif report.dry_run:
        text = (
            f"dry run: the voices of {_plural(len(report.found), 'transcript')} would be separated, each a"
            f" new line superseding the one heard before{already}; nothing written"
        )
    else:
        if report.written:
            text = (
                f"separated the voices of {_plural(report.written, 'transcript')}, each a new line"
                f" superseding the one heard before{already}"
            )
        else:
            text = f"heard {_plural(len(report.found), 'transcript')} again; nothing written{already}"
        if report.same:
            text += f"\n  heard the same as before, nothing written: {report.same:,}"
        if report.voiceless:
            text += f"\n  no voice found, nothing written: {report.voiceless:,}"
        text += _heard_text(report.rooms, report.unlabelled)
    skipped = [f"{n:,} {PHRASES.get(key, key)}" for key, n in report.counts.items() if n]
    return text + (f"\n  not heard again: {', '.join(skipped)}" if skipped else "")


def _provenance(line: Line) -> dict[str, Any]:
    found = (line.get("payload") or {}).get("provenance")
    return found if isinstance(found, dict) else {}


# -- engines ---------------------------------------------------------------------------------------


def detect(
    model: str = DEFAULT_MODEL,
    importer: Callable[[str], Any] = importlib.import_module,
    platform: tuple[str, str] | None = None,
    words: bool = False,
) -> Engine:
    """The engine this machine has: `mlx-whisper` first on Apple silicon, `faster-whisper` wherever
    it is installed; EngineMissing, naming the extra, when neither is. `words` asks it for each
    word's times, which a run that separates voices assigns by."""
    here = platform or (sys.platform, machine())
    candidates: list[type[MlxWhisper] | type[FasterWhisper]] = (
        [MlxWhisper, FasterWhisper] if here == ("darwin", "arm64") else [FasterWhisper, MlxWhisper]
    )
    for engine in candidates:
        try:
            module = importer(engine.module)
        except ImportError:
            continue
        return engine(model, module, importer, words)
    raise EngineMissing(
        f"no transcription engine is installed; install {EXTRA} (mlx-whisper on Apple silicon,"
        " faster-whisper elsewhere; mlx-whisper decodes audio with ffmpeg, which must be on the PATH)"
    )


class MlxWhisper:
    """Apple's MLX port of Whisper: models from `mlx-community/whisper-<size>-mlx`."""

    name = "mlx-whisper"
    module = "mlx_whisper"

    def __init__(self, model: str, mlx: Any, importer: Callable[[str], Any], words: bool = False) -> None:
        self.model, self._mlx, self._import, self.words = model, mlx, importer, words
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
        if self.words:
            options["word_timestamps"] = True
        out = self._mlx.transcribe(samples, **options)
        segments = [
            Segment(
                float(s.get("start", 0.0)),
                float(s.get("end", 0.0)),
                str(s.get("text", "")),
                tuple((float(w["start"]), float(w["end"])) for w in s.get("words") or ()),
            )
            for s in out.get("segments", [])
        ]
        return Result(segments, str(out.get("language") or language or ""))


class FasterWhisper:
    """CTranslate2's Whisper: models from `Systran/faster-whisper-<size>`."""

    name = "faster-whisper"
    module = "faster_whisper"

    def __init__(self, model: str, fw: Any, importer: Callable[[str], Any], words: bool = False) -> None:
        self.model, self._fw, self._import, self.words = model, fw, importer, words
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
        found, info = self._loaded.transcribe(samples, language=language, word_timestamps=self.words)
        segments = [  # a generator: heard here
            Segment(
                float(s.start),
                float(s.end),
                str(s.text),
                tuple((float(w.start), float(w.end)) for w in (getattr(s, "words", None) or ())),
            )
            for s in found
        ]
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
