"""The voices of a recording (RFC 0038 §2): the anonymous labels a diarizer's turns get, which voice
each text segment of a transcript is, how much of the recording was spoken over, the spans file, and
how a reader shows the voices a `transcript/v1` line carries.

- A **turn** is the diarizer's own: one voice speaking from `start` to `end`, seconds from the start
  of the recording; turns of different voices overlap where the people did.
- A **label** is anonymous and only means something inside its line: `S1`, `S2`, … for the voices of
  one channel, numbered by first speech (the pipeline's `SPEAKER_00` says nothing about order);
  `mic` and `system` for a channel that holds one voice, `mic.1`, `mic.2`, … for one that holds
  several (§2.4). A label matches `^[^#\\n]{1,64}$`, so a `speaker` ref splits at its first `#`.
- A text **segment** goes to the voice that speaks most of it: of its words when the engine gave
  word times, else of its span; a tie goes to the voice that spoke first in the recording; `None`
  when nobody spoke in it. The other voices that speak in the segment for a second or more are its
  `overlap` (§2.6), counted over the segment's span, words or not, because what is spoken over is
  what a crossing must hold back.
- A voice's **seconds** are its own speech (the union of its turns): two voices that overlap for a
  minute both count the minute, and `overlap_s` is how much of the recording that was.

The **spans file** (§2.3) is one JSON object, `{format, content, segments, turns}`, stored once
under its digest: a `segments` entry per segment of the content file, in its order, and the
diarizer's turns. Its bytes are `json.dumps` with sorted keys and no spaces, every time in seconds
from the line's `at` to two decimals, so the same voices heard in the same text give the same file,
the same digest and, for `derive speakers`, the same `raw_id`.

Readers take a line's voices through `voices`, which never fails on a payload it cannot read (SPEC
§5): an entry it cannot read is skipped. The owner is shown only from `from_me`, a statement of
the source, as `you`; every other voice by the name the source displayed, else its label. Nothing
here binds a voice to a person: that is a `resolution/v1` line of RFC 0038 §3, not this module.

Pure: no record, no model, no network."""

from __future__ import annotations

import json
import math
import re
from bisect import bisect_right
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from . import transcripts

FORMAT = "speaker-spans/1"
MEDIA_TYPE = "application/json"
LABEL = re.compile(r"[^#\n]{1,64}")
MIC, SYSTEM = "mic", "system"
CHANNELS = (MIC, SYSTEM)  # the channels a source can name, in no particular order
OVERLAP_MIN_S = 1.0  # §2.3: a voice is in a segment's `overlap` when it speaks a second or more of it
OWNER = "you"  # how a reader shows the voice the source puts on the owner's own microphone
MINUTE = 60.0

Interval = tuple[float, float]


@dataclass(frozen=True)
class VoiceTurn:
    """One turn of one voice: `start` and `end` in seconds from the start of the recording."""

    start: float
    end: float
    voice: str


@dataclass(frozen=True)
class Span:
    """A text segment's times, in seconds from the start of the recording, and its words' times
    when the engine gave them."""

    start: float
    end: float
    words: tuple[Interval, ...] = ()


@dataclass(frozen=True)
class Assigned:
    """Whose a segment is: the voice that speaks most of it (None when nobody does), and the other
    voices that speak in it for a second or more, in order of first speech."""

    speaker: str | None
    overlap: tuple[str, ...] = ()


def is_label(value: object) -> bool:
    return isinstance(value, str) and LABEL.fullmatch(value) is not None


# -- labels ---------------------------------------------------------------------------------------


def label_room(heard: Iterable[tuple[float, float, str]]) -> list[VoiceTurn]:
    """The turns of one channel, as a diarizer names them, labelled `S1`, `S2`, … by first speech.
    A turn with no length is no speech: it names no voice."""
    turns = _spoken(heard)
    names: dict[str, str] = {}
    for _start, _end, raw in turns:
        names.setdefault(raw, f"S{len(names) + 1}")
    return [VoiceTurn(start, end, names[raw]) for start, end, raw in turns]


def label_channels(by_channel: Mapping[str, Iterable[tuple[float, float, str]]]) -> list[VoiceTurn]:
    """The turns of each channel (`mic`, `system`), as a diarizer names them within it: a channel in
    which one voice speaks is labelled by the channel, one in which several do `<channel>.1`,
    `<channel>.2`, … by first speech within it. All the turns, in time order."""
    out: list[VoiceTurn] = []
    for channel, heard in by_channel.items():
        turns = _spoken(heard)
        raws: list[str] = []
        for _start, _end, raw in turns:
            if raw not in raws:
                raws.append(raw)
        names = (
            {raws[0]: channel} if len(raws) == 1 else {raw: f"{channel}.{i}" for i, raw in enumerate(raws, 1)}
        )
        out += [VoiceTurn(start, end, names[raw]) for start, end, raw in turns]
    return sorted(out, key=lambda t: (t.start, t.end, t.voice))


def order(turns: Iterable[VoiceTurn]) -> list[str]:
    """The voices in order of first speech (a tie by label)."""
    first: dict[str, float] = {}
    for t in turns:
        if t.voice not in first or t.start < first[t.voice]:
            first[t.voice] = t.start
    return sorted(first, key=lambda voice: (first[voice], voice))


def _spoken(heard: Iterable[tuple[float, float, str]]) -> list[tuple[float, float, str]]:
    return sorted(
        ((float(start), float(end), str(raw)) for start, end, raw in heard if float(end) > float(start)),
        key=lambda t: (t[0], t[1], t[2]),
    )


# -- seconds and overlap --------------------------------------------------------------------------


def seconds(turns: Iterable[VoiceTurn]) -> dict[str, float]:
    """Each voice's own speech, in seconds: the union of its turns, in order of first speech."""
    turns = list(turns)
    merged = _merged(turns)
    return {voice: sum(end - start for start, end in merged[voice]) for voice in order(turns)}


def overlap_seconds(turns: Iterable[VoiceTurn]) -> float:
    """The seconds in which two voices or more speak at once, each such second counted once."""
    events: list[tuple[float, int]] = []
    for intervals in _merged(list(turns)).values():
        for start, end in intervals:
            events += [(start, 1), (end, -1)]
    events.sort(key=lambda e: (e[0], e[1]))  # an end before a start at the same instant
    total, active, since = 0.0, 0, 0.0
    for when, step in events:
        if active >= 2:
            total += when - since
        active += step
        since = when
    return total


def _merged(turns: Sequence[VoiceTurn]) -> dict[str, list[Interval]]:
    """Each voice's turns as sorted, disjoint intervals."""
    by_voice: dict[str, list[Interval]] = {}
    for t in sorted(turns, key=lambda t: (t.start, t.end)):
        intervals = by_voice.setdefault(t.voice, [])
        if intervals and t.start <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], t.end))
        else:
            intervals.append((t.start, t.end))
    return by_voice


def _inside(intervals: Sequence[Interval], ends: Sequence[float], start: float, end: float) -> float:
    """How much of `[start, end]` the sorted, disjoint `intervals` cover (`ends` their ends)."""
    total = 0.0
    for i in range(bisect_right(ends, start), len(intervals)):
        a, b = intervals[i]
        if a >= end:
            break
        total += max(0.0, min(b, end) - max(a, start))
    return total


# -- the segments ---------------------------------------------------------------------------------


def assign(
    spans: Sequence[Span], turns: Sequence[VoiceTurn], given: Sequence[str | None] | None = None
) -> list[Assigned]:
    """Each segment's voice and overlap (the module's rules). `given` is each segment's voice as a
    source already says it (a provider that labels its own segments): it stands, and only the
    overlap is reckoned."""
    voices = order(turns)
    merged = _merged(turns)
    ends = {voice: [b for _a, b in merged[voice]] for voice in voices}

    def heard(windows: Iterable[Interval]) -> dict[str, float]:
        windows = list(windows)
        return {v: sum(_inside(merged[v], ends[v], a, b) for a, b in windows) for v in voices}

    out: list[Assigned] = []
    for i, span in enumerate(spans):
        around = heard([(span.start, span.end)])
        by_words = heard(span.words) if span.words else around
        speaker = given[i] if given is not None else _most(voices, by_words) or _most(voices, around)
        overlap = (
            tuple(v for v in voices if v != speaker and around.get(v, 0.0) >= OVERLAP_MIN_S)
            if speaker
            else ()
        )
        out.append(Assigned(speaker, overlap))
    return out


def _most(voices: Sequence[str], measure: Mapping[str, float]) -> str | None:
    """The voice with the most, the first of a tie; None when nobody has any."""
    best: str | None = None
    for voice in voices:
        if measure[voice] > 0 and (best is None or measure[voice] > measure[best]):
            best = voice
    return best


# -- the line's fields ----------------------------------------------------------------------------


def speakers_field(
    voices: Sequence[str],
    assigned: Sequence[Assigned],
    spoken: Mapping[str, float] | None,
    *,
    channels: Mapping[str, str] | None = None,
    from_me: str | None = None,
    names: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """`payload.speakers`: one entry per voice, in the order given (first speech): `label`,
    `seconds` (from `spoken`, absent when the source gave no times), `turns` (the segments that are
    the voice's), `channel`, `from_me` and `name` where given."""
    counts: dict[str, int] = {}
    for a in assigned:
        if a.speaker is not None:
            counts[a.speaker] = counts.get(a.speaker, 0) + 1
    out: list[dict[str, Any]] = []
    for voice in voices:
        entry: dict[str, Any] = {"label": voice}
        if spoken is not None:
            entry["seconds"] = _two(spoken.get(voice, 0.0))
        entry["turns"] = counts.get(voice, 0)
        if channels and voice in channels:
            entry["channel"] = channels[voice]
        if from_me is not None and voice == from_me:
            entry["from_me"] = True
        if names and names.get(voice):
            entry["name"] = names[voice]
        out.append(entry)
    return out


def diarization_field(
    engine: str,
    channels: int,
    *,
    model: str | None = None,
    audio: str | None = None,
    overlap_s: float | None = None,
    spans: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """`payload.diarization`: how the labels were made, the keys given and in RFC 0038's order."""
    out: dict[str, Any] = {"engine": engine}
    if model:
        out["model"] = model
    if audio:
        out["audio"] = audio
    out["channels"] = channels
    if overlap_s is not None:
        out["overlap_s"] = _two(overlap_s)
    if spans is not None:
        out["spans"] = dict(spans)
    return out


# -- the spans file -------------------------------------------------------------------------------


def spans_document(
    content: str,
    spans: Sequence[Span],
    assigned: Sequence[Assigned],
    turns: Sequence[VoiceTurn],
    offset: float = 0.0,
) -> dict[str, Any]:
    """The spans file of a content file whose digest is `content`: a segment per entry of `spans`
    (one per segment of the content, in its order) and the turns, every time less `offset` (the
    line's `at`, in seconds from the start of the recording)."""
    segments: list[dict[str, Any]] = []
    for span, found in zip(spans, assigned, strict=True):
        entry: dict[str, Any] = {
            "from": _two(span.start - offset),
            "to": _two(span.end - offset),
            "speaker": found.speaker,
        }
        if found.overlap:
            entry["overlap"] = list(found.overlap)
        segments.append(entry)
    return {
        "format": FORMAT,
        "content": content,
        "segments": segments,
        "turns": [
            {"from": _two(t.start - offset), "to": _two(t.end - offset), "speaker": t.voice}
            for t in sorted(turns, key=lambda t: (t.start, t.end, t.voice))
        ],
    }


def spans_bytes(document: Mapping[str, Any]) -> bytes:
    """The spans file's bytes: one way, so the same document is the same digest."""
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def segment_count(data: bytes, media_type: str) -> int | None:
    """How many segments a content file has, by its media type (§2.3): the non-empty lines of
    `text/plain` (one segment a line, as `derive transcripts` writes it) unless the text is SRT, the
    cues of WebVTT and SRT, the elements of a JSON segments array, the turns of Markdown as RFC
    0004's readers parse them. None for a file that is none of these."""
    try:
        text = data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError:
        return None
    media = media_type.split(";")[0].strip().casefold()
    if media == "application/json":
        try:
            found = json.loads(text)
        except ValueError:
            return None
        if isinstance(found, dict):
            found = found.get("segments", found.get("turns"))
        return len(found) if isinstance(found, list) else None
    if media == "text/vtt":
        return len(transcripts.parse_text(text, "vtt").turns)
    if media in ("application/x-subrip", "text/srt") or (media == "text/plain" and _SRT.match(text)):
        return len(transcripts.parse_text(text, "srt").turns)
    if media == "text/markdown":
        return len(transcripts.parse_text(text, "markdown").turns)
    if media == "text/plain":
        return sum(1 for line in text.split("\n") if line.strip())
    return None


_SRT = re.compile(r"^\s*\d+\s*\n\d\d:\d\d:\d\d,\d{3}\s*-->")


def _two(value: float) -> float:
    """Seconds to two decimals, never `-0.0`."""
    return round(value, 2) + 0.0


# -- reading a line's voices back -----------------------------------------------------------------


@dataclass(frozen=True)
class Voice:
    """One voice of a line as a reader takes it."""

    label: str
    seconds: float | None
    turns: int | None
    channel: str | None
    from_me: bool
    name: str | None

    @property
    def shown(self) -> str:
        """`you` from `from_me`; else the name the source displayed; else the label."""
        return OWNER if self.from_me else (self.name or self.label)


def voices(payload: Mapping[str, Any]) -> list[Voice]:
    """The voices of a transcript line's payload, the entries a reader cannot read skipped; none
    when the line has no `speakers` (a transcript as RFC 0004 defines it)."""
    found = payload.get("speakers")
    if not isinstance(found, list):
        return []
    out: list[Voice] = []
    for entry in found:
        if not isinstance(entry, dict) or not is_label(entry.get("label")):
            continue
        out.append(
            Voice(
                label=str(entry["label"]),
                seconds=_number(entry.get("seconds")),
                turns=entry["turns"] if _count(entry.get("turns")) else None,
                channel=entry["channel"]
                if isinstance(entry.get("channel"), str) and entry["channel"]
                else None,
                from_me=entry.get("from_me") is True,
                name=entry["name"] if isinstance(entry.get("name"), str) and entry["name"].strip() else None,
            )
        )
    return out


def voice_text(voice: Voice) -> str:
    """`you 31 min`, `S2 14 min`, `S3 42 s`; the voice alone when the line gives no seconds."""
    if voice.seconds is None:
        return voice.shown
    return f"{voice.shown} {duration_text(voice.seconds)}"


def duration_text(value: float) -> str:
    return f"{value / MINUTE:.0f} min" if value >= MINUTE else f"{value:.0f} s"


def row_text(payload: Mapping[str, Any]) -> str:
    """The voices of a line in one run, `you 31 min · S2 14 min`; empty for a line without them."""
    return " · ".join(voice_text(v) for v in voices(payload))


def to_json(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The voices as a reader's JSON gives them, in the shape RFC 0038 §3.4 names, ahead of the
    attributions that will fill it: `person`, `basis` and `consent` are null until a line binds the
    voice (build 2); `owner` is true only from `from_me`, whose basis is the channel."""
    return [
        {
            "label": v.label,
            "person": None,
            "name": v.name,
            "seconds": v.seconds,
            "basis": "channel" if v.from_me else None,
            "consent": None,
            "owner": v.from_me,
        }
        for v in voices(payload)
    ]


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0
