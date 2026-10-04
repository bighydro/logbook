"""Transcripts as text: the speaker turns of a WebVTT, SRT, Markdown, plain-text or JSON transcript,
and how to read them back out of a `transcript/v1` line's attachment (RFC 0004).

The `transcript` adapter (`logbook.contrib.adapters.transcript`) turns a file into a line with this
parser and stores the text; the readers that need the words again, `search` (indexing the text)
and `promises` (reading commitments), take them from here. Pure: nothing here knows the record,
except `turns_of`, which reads one attachment of a given logbook and never writes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any
from zoneinfo import ZoneInfo

from .chain import Line
from .store import Logbook

TIMING = re.compile(r"(?:(\d+):)?(\d\d):(\d\d)[.,](\d{1,3})")


ARROW = "-->"


VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>")


TAG = re.compile(r"</?[^>]+>")


SPEAKER = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?[*_]{0,2}([^:*_\n]{1,60}?)[*_]{0,2}:[*_]{0,2}\s+(\S.*)$")


HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")


EMAIL_IN = re.compile(r"^(.*?)\s*[<(]\s*([^\s<>()]+@[^\s<>()]+)\s*[>)]\s*$")


@dataclass(frozen=True)
class Turn:
    """One speaker turn as the source labels it; `speaker` None when the source names nobody."""

    speaker: str | None
    text: str


@dataclass
class Parsed:
    """What a transcript file says, before it is a line."""

    format: str
    turns: list[Turn] = field(default_factory=list)
    title: str | None = None
    started_at: str | None = None  # RFC3339 UTC, when the file says
    ended_at: str | None = None
    duration_s: float | None = None  # from cue offsets, when the file has them
    named: list[dict[str, Any]] = field(default_factory=list)  # participants the front matter names

    @property
    def participants(self) -> list[dict[str, Any]]:
        """Front-matter participants first, then every speaker label not among them, in order of
        first appearance. Source-native, never resolved."""
        return participants(self.turns, self.named)


def parse_text(text: str, fmt: str) -> Parsed:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if fmt == "vtt":
        return _cues(text, "vtt")
    if fmt == "srt":
        return _cues(text, "srt")
    return _prose(text, fmt)


def counts_of(turns: list[Turn], at: str | None, end: str | None) -> dict[str, Any]:
    """`turns`, `speakers`, `unattributed` (when any) and `duration_s` (when both ends are known)."""
    out: dict[str, Any] = {"turns": len(turns), "speakers": len({t.speaker for t in turns if t.speaker})}
    unattributed = sum(1 for t in turns if not t.speaker)
    if unattributed:
        out["unattributed"] = unattributed
    if at and end:
        out["duration_s"] = (_parse_stamp(end) - _parse_stamp(at)).total_seconds()
    return out


def participants(turns: list[Turn], named: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    out = list(named or [])
    seen = {str(p.get("name")) for p in out}
    for t in turns:
        if t.speaker and t.speaker not in seen:
            seen.add(t.speaker)
            out.append({"name": t.speaker})
    return out


def _cues(text: str, fmt: str) -> Parsed:
    parsed = Parsed(format=fmt)
    last_end: float | None = None
    for block in re.split(r"\n{2,}", text.strip("\n")):
        lines = [line for line in block.split("\n") if line.strip()]
        if not lines or lines[0].startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
            continue
        timing = next((i for i, line in enumerate(lines) if ARROW in line), None)
        if timing is None:
            continue
        end_offset = _end_offset(lines[timing])
        if end_offset is not None and (last_end is None or end_offset > last_end):
            last_end = end_offset
        body = " ".join(line.strip() for line in lines[timing + 1 :])
        voice = VOICE.search(body)
        body = TAG.sub("", body).strip()
        speaker: str | None = None
        if voice:
            speaker = voice.group(1).strip()
        else:
            speaker, body = _split_speaker(body)
        if body:
            parsed.turns.append(Turn(speaker, body))
    parsed.duration_s = last_end
    return parsed


def _end_offset(timing: str) -> float | None:
    """The cue's end, in seconds from the start of the recording."""
    _start, _, rest = timing.partition(ARROW)
    m = TIMING.search(rest)
    if m is None:
        return None
    hours, minutes, seconds, fraction = m.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds) + int(fraction.ljust(3, "0")) / 1000


def _split_speaker(text: str) -> tuple[str | None, str]:
    m = SPEAKER.match(text)
    if m is None:
        return None, text.strip()
    return m.group(1).strip(), m.group(2).strip()


def _prose(text: str, fmt: str) -> Parsed:
    parsed = Parsed(format=fmt)
    body = _front_matter(text, parsed)
    current: Turn | None = None
    for raw in body.split("\n"):
        line = raw.strip()
        if not line:
            current = None
            continue
        heading = HEADING.match(line)
        if heading:
            if parsed.title is None:
                parsed.title = heading.group(1)
            current = None
            continue
        speaker, said = _split_speaker(line)
        if speaker is None and current is not None:
            current = Turn(current.speaker, f"{current.text} {said}")
            parsed.turns[-1] = current
            continue
        current = Turn(speaker, said)
        parsed.turns.append(current)
    return parsed


def _front_matter(text: str, parsed: Parsed) -> str:
    """Read a leading `---` block into `parsed`; the rest of the text."""
    if not text.startswith("---\n"):
        return text
    close = text.find("\n---", 4)
    if close < 0:
        return text
    block, rest = text[4:close], text[close + 4 :]
    key: str | None = None
    for raw in block.split("\n"):
        if not raw.strip():
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key == "participants":
            parsed.named.append(_participant(item.group(1).strip()))
            continue
        name, sep, value = raw.partition(":")
        if not sep:
            continue
        key, value = name.strip().lower(), value.strip()
        if key == "title" and value:
            parsed.title = value.strip("\"'")
        elif key in ("started_at", "start", "at") and value:
            parsed.started_at = _stamp_of(value, None)
        elif key in ("ended_at", "end") and value:
            parsed.ended_at = _stamp_of(value, None)
        elif key == "participants" and value:
            parsed.named.extend(_participant(p.strip()) for p in value.strip("[]").split(",") if p.strip())
    return rest.lstrip("\n")


def _participant(text: str) -> dict[str, Any]:
    m = EMAIL_IN.match(text)
    if m and m.group(1).strip():
        return {"name": m.group(1).strip(), "email": m.group(2)}
    if m:
        return {"name": m.group(2), "email": m.group(2)}
    return {"name": text.strip("\"'")}


def _stamp_of(value: str, timezone: str | None) -> str | None:
    """`value` as RFC3339 UTC; a zone-less time is read in `timezone` (UTC when none)."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone) if timezone else UTC)
    return _format_stamp(parsed)


def _parse_stamp(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)


def _format_stamp(when: datetime) -> str:
    when = when.astimezone(UTC)
    if when.microsecond:
        return f"{when:%Y-%m-%dT%H:%M:%S}.{when.microsecond // 1000:03d}Z"
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


_DIGEST = re.compile(r"[0-9a-f]{64}")  # an attachment's name (SPEC §1.1)


def turns_of(lb: Logbook, line: Line) -> list[Turn] | None:
    """The speaker turns of a transcript line's text from the attachment store, by its media type:
    WebVTT and SRT cues, Granola's JSON segments, or `Speaker: text` prose and plain text (the file
    adapter's own parsers). None when the line names no text or the file is not in the store."""
    content = (line.get("payload") or {}).get("content")
    if not isinstance(content, dict):
        return None
    sha256 = content.get("sha256")
    rel = PurePosixPath(content["path"]) if isinstance(content.get("path"), str) else None
    if isinstance(sha256, str) and _DIGEST.fullmatch(sha256):
        path = lb.root / "attachments" / sha256
    elif rel is not None and rel.parts and not rel.is_absolute() and ".." not in rel.parts:
        path = lb.root.joinpath(*rel.parts)  # inside the record, never beyond it
    else:
        return None
    if not path.is_file():
        return None
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    media = str(content.get("media_type") or "").split(";")[0].strip().casefold()
    if media == "text/vtt":
        return parse_text(text, "vtt").turns
    if media in ("application/x-subrip", "text/srt"):
        return parse_text(text, "srt").turns
    if media == "application/json":
        return _json_turns(text)
    return parse_text(text, "text").turns


def _json_turns(text: str) -> list[Turn]:
    """Granola's segments (`{speaker: {name|diarization_label|attribution}, text}`), or any JSON
    object carrying such a list under `segments` or `turns`; anything else has no turns."""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("segments") or data.get("turns") or []
    if not isinstance(data, list):
        return []
    turns = []
    for segment in data:
        if not isinstance(segment, dict):
            continue
        said = segment.get("text")
        if not isinstance(said, str) or not said.strip():
            continue
        turns.append(Turn(_json_label(segment.get("speaker")), said))
    return turns


def _json_label(speaker: object) -> str | None:
    if isinstance(speaker, str):
        return speaker.strip() or None
    if not isinstance(speaker, dict):
        return None
    for key in ("name", "diarization_label", "attribution", "label"):
        value = speaker.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
