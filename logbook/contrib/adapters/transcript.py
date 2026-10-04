"""Transcript files → transcript/v1 (RFC 0004): the universal file adapter, and the one mapping every
transcript source shares (ADR 0017).

Reads, by content:

- **JSON in transcript/v1 shape** — the interchange format for any tool: one object per file with the
  envelope fields `at`, `end`, `tz`, `source`, `tier` and a `payload` whose `schema` is
  `transcript/v1` (what `logbook export` writes for such a line, minus the chain fields). The payload
  is kept as given; `content` may be a SPEC §1.1 reference (kept, nothing stored) or
  `{"media_type", "text"}` with the text inline, which is stored and replaced by its reference.
- **WebVTT** and **SRT** — every cue is a turn; the speaker is the VTT voice tag (`<v Name>`) or a
  leading `Name:`, else unknown. The cues' offsets give the duration; the start comes from `--at`
  or from a date and time in the file name (`2026-03-01T13-00-00Z …`, Zoom's
  `GMT20260301-130000_…`, `2026-03-01 1300 …` in the record's zone, a bare date at local midnight).
- **Markdown / plain text** — `Speaker: text` lines, a following line continuing the turn, a blank
  line ending it; an optional front-matter block gives `title`, `started_at`, `ended_at` and
  `participants` (`Name <email>`); a `# heading` is the title when the front matter has none.
  Never sniffed (too loose): only `logbook add transcript <file>` reads them.

The line's `content` is the file's own bytes, stored once under their digest (SPEC §1.1) and
`raw_id` is `<source>:<sha256 of those bytes>` unless the JSON brings one, so the same file added
twice, from anywhere, is one line. Tier 3 by default: a transcript carries other people's words in
full. Speakers stay as the source labels them; nothing is resolved here (RFC 0004). Pure: reads the
file, makes no network call; the only writing is through the `store` callback `logbook add` hands
it, into the attachment store.

`draft(...)` is the mapping a live puller of the same source uses (`granola` does), so a transcript
exported by hand and the same one pulled by API are one line with one `raw_id`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from ...core.attachments import reference

NAME = "transcript"
KIND = "transcript"
TIER = 3
SCHEMA = "transcript/v1"
DEFAULT_SOURCE = "manual"  # RFC 0004's provider for a transcript nobody's API produced

MEDIA_TYPES = {
    "vtt": "text/vtt",
    "srt": "text/plain",
    "markdown": "text/markdown",
    "text": "text/plain",
    "json": "application/json",
}
NO_START = "skipped_no_start"
NOT_TRANSCRIPT = "skipped_not_transcript"
SNIFF_BYTES = 4096

TIMING = re.compile(r"(?:(\d+):)?(\d\d):(\d\d)[.,](\d{1,3})")
ARROW = "-->"
SRT_HEAD = re.compile(r"^\s*\d+\s*\r?\n\d\d:\d\d:\d\d,\d{3}\s*-->")
VOICE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>")
TAG = re.compile(r"</?[^>]+>")
# `[00:12:30] **Name:** text`, `Name: text`; a name is short and has no colon
SPEAKER = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?[*_]{0,2}([^:*_\n]{1,60}?)[*_]{0,2}:[*_]{0,2}\s+(\S.*)$")
HEADING = re.compile(r"^#{1,6}\s+(.*\S)\s*$")
EMAIL_IN = re.compile(r"^(.*?)\s*[<(]\s*([^\s<>()]+@[^\s<>()]+)\s*[>)]\s*$")
# a start in the file name: ISO-ish date and time, Zoom's GMT stamp, or a bare date
NAME_STAMP = re.compile(
    r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?:[T _](\d{2})[-:.h]?(\d{2})(?:[-:.m]?(\d{2}))?\s*(Z|UTC)?)?(?!\d)"
)
ZOOM_STAMP = re.compile(r"GMT(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})")


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


def sniff(path: Path) -> bool:
    """A WebVTT file, an SRT file, or a JSON object in transcript/v1 shape. Markdown and plain text
    are never claimed: `logbook add transcript <file>` names them."""
    path = Path(path)
    if not path.is_file():
        return False
    try:
        with path.open("rb") as fh:
            head = fh.read(SNIFF_BYTES)
        text = head.decode("utf-8", errors="replace").lstrip("\ufeff")
        if text.startswith("WEBVTT") or SRT_HEAD.match(text):
            return True
        if text.lstrip().startswith("{") and SCHEMA in text:
            return _json_kind(json.loads(path.read_text(encoding="utf-8"))) is not None
    except (OSError, ValueError):
        return False
    return False


def run(
    path: Path,
    since: str | None = None,
    counts: dict[str, int] | None = None,
    timezone: str | None = None,
    source: str | None = None,
    tier: int | None = None,
    at: str | None = None,
    store: Callable[[bytes], object] | None = None,
) -> Iterator[dict[str, Any]]:
    """One transcript/v1 line draft per transcript file under `path` (a file, or a folder read in
    name order, hidden files skipped). `source` names the provider (default: the JSON's own, else
    `manual`); `tier` overrides 3; `at` is the start for a file that carries none; `timezone` reads
    zone-less times; `store` is called with the content bytes just before each line is yielded."""
    counts = counts if counts is not None else {}
    path = Path(path)
    files = (
        [path]
        if path.is_file()
        else sorted(f for f in path.iterdir() if f.is_file() and not f.name.startswith("."))
    )
    for file in files:
        result = _file(file, counts, timezone, source, tier, at)
        if result is None:
            continue
        line, data = result
        if since and line["at"] < since:
            continue
        if store is not None and data is not None:
            store(data)
        yield line


def parse(path: Path) -> Parsed:
    """The turns and metadata of a WebVTT, SRT, Markdown or plain-text file."""
    path = Path(path)
    data = path.read_bytes()
    return parse_text(data.decode("utf-8-sig"), _format(path, data) or "text")


def parse_text(text: str, fmt: str) -> Parsed:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if fmt == "vtt":
        return _cues(text, "vtt")
    if fmt == "srt":
        return _cues(text, "srt")
    return _prose(text, fmt)


def draft(
    *,
    source: str,
    at: str,
    end: str | None,
    raw_id: str,
    content: dict[str, Any],
    turns: list[Turn],
    tier: int = TIER,
    title: str | None = None,
    participants: list[dict[str, Any]] | None = None,
    language: str | None = None,
    source_uri: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The one mapping from a transcript to a transcript/v1 line draft, for the file adapter and for
    every live puller: `content` is the §1.1 reference to the text, `turns` are only counted (and
    name the participants when none are given), `extra` gets `turns`, `speakers`, `unattributed`
    (when any) and `duration_s` (when `end` is known)."""
    payload: dict[str, Any] = {"schema": SCHEMA, "provider": source, "raw_id": raw_id}
    if title:
        payload["title"] = title
    payload["participants"] = participants if participants is not None else _speakers(turns)
    if language:
        payload["language"] = language
    payload["content"] = content
    if source_uri:
        payload["source_uri"] = source_uri
    payload["extra"] = {**(extra or {}), **counts_of(turns, at, end)}
    return {
        "at": at,
        "end": end,
        "tz": None,
        "source": source,
        "kind": KIND,
        "tier": tier,
        "payload": payload,
    }


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


def _speakers(turns: list[Turn]) -> list[dict[str, Any]]:
    return participants(turns, None)


# -- one file -------------------------------------------------------------------------------------


def _file(
    file: Path,
    counts: dict[str, int],
    timezone: str | None,
    source: str | None,
    tier: int | None,
    at: str | None,
) -> tuple[dict[str, Any], bytes | None] | None:
    """The draft for one file and the bytes to store, or None (counted) when it is not a transcript
    or has no start."""
    data = file.read_bytes()
    fmt = _format(file, data)
    if fmt == "json":
        return _json(file, data, counts, timezone, source, tier)
    if fmt is None:
        _count(counts, NOT_TRANSCRIPT)
        return None
    parsed = parse_text(data.decode("utf-8-sig"), fmt)
    start = _stamp_of(at, timezone) if at else parsed.started_at or _name_stamp(file.name, timezone)
    if start is None:
        _count(counts, NO_START)
        return None
    end = parsed.ended_at
    if end is None and parsed.duration_s is not None:
        end = _format_stamp(_parse_stamp(start) + timedelta(seconds=parsed.duration_s))
    provider = source or DEFAULT_SOURCE
    line = draft(
        source=provider,
        at=start,
        end=end,
        raw_id=f"{provider}:{reference(data, MEDIA_TYPES[fmt])['sha256']}",
        content=reference(data, MEDIA_TYPES[fmt]),
        turns=parsed.turns,
        tier=tier or TIER,
        title=parsed.title,
        participants=parsed.participants,
        extra={"format": fmt, "file": file.name},
    )
    return line, data


def _json(
    file: Path,
    data: bytes,
    counts: dict[str, int],
    timezone: str | None,
    source: str | None,
    tier: int | None,
) -> tuple[dict[str, Any], bytes | None] | None:
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        _count(counts, NOT_TRANSCRIPT)
        return None
    kind = _json_kind(obj)
    if kind is None:
        _count(counts, NOT_TRANSCRIPT)
        return None
    if kind == "payload" or not isinstance(obj.get("at"), str):  # a bare payload has no time
        _count(counts, NO_START)
        return None
    payload = dict(obj["payload"])
    provider = source or (obj.get("source") if isinstance(obj.get("source"), str) else None)
    provider = provider or (payload.get("provider") if isinstance(payload.get("provider"), str) else None)
    provider = provider or DEFAULT_SOURCE
    payload.setdefault("provider", provider)
    at = _stamp_of(obj["at"], timezone)
    end = _stamp_of(obj["end"], timezone) if isinstance(obj.get("end"), str) else None
    if at is None:
        _count(counts, NO_START)
        return None
    to_store: bytes | None = None
    content = payload.get("content")
    if isinstance(content, dict) and isinstance(content.get("text"), str):
        media_type = str(content.get("media_type") or MEDIA_TYPES["markdown"])
        to_store = content["text"].encode("utf-8")
        payload["content"] = reference(to_store, media_type)
        fmt = "markdown" if media_type == "text/markdown" else "text"
        parsed = parse_text(content["text"], fmt)
        payload.setdefault("participants", parsed.participants)
        payload["extra"] = {
            "format": "json",
            **(payload.get("extra") or {}),
            **counts_of(parsed.turns, at, end),
        }
    payload.setdefault("raw_id", f"{provider}:{reference(data, MEDIA_TYPES['json'])['sha256']}")
    line = {
        "at": at,
        "end": end,
        "tz": obj.get("tz") if isinstance(obj.get("tz"), str) else None,
        "source": provider,
        "kind": KIND,
        "tier": tier or (obj["tier"] if obj.get("tier") in (1, 2, 3) else TIER),
        "payload": payload,
    }
    return line, to_store


def _json_kind(obj: object) -> str | None:
    """'draft' for an object with a transcript/v1 payload, 'payload' for a bare one, else None."""
    if not isinstance(obj, dict):
        return None
    payload = obj.get("payload")
    if isinstance(payload, dict) and payload.get("schema") == SCHEMA:
        return "draft"
    if obj.get("schema") == SCHEMA:
        return "payload"
    return None


def _format(file: Path, data: bytes) -> str | None:
    head = data[:SNIFF_BYTES].decode("utf-8", errors="replace").lstrip("\ufeff")
    if head.startswith("WEBVTT"):
        return "vtt"
    if SRT_HEAD.match(head):
        return "srt"
    if head.lstrip().startswith("{"):
        return "json"
    suffix = file.suffix.lower()
    if suffix in (".md", ".markdown"):
        return "markdown"
    if suffix in (".txt", ".text", "") or _is_text(data):
        return "text"
    return None


def _is_text(data: bytes) -> bool:
    try:
        data[:SNIFF_BYTES].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return b"\x00" not in data[:SNIFF_BYTES]


def _count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


# -- cues: WebVTT and SRT --------------------------------------------------------------------------


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


# -- prose: Markdown and plain text ------------------------------------------------------------------


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


# -- times -----------------------------------------------------------------------------------------


def _stamp_of(value: str, timezone: str | None) -> str | None:
    """`value` as RFC3339 UTC; a zone-less time is read in `timezone` (UTC when none)."""
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone) if timezone else UTC)
    return _format_stamp(parsed)


def _name_stamp(name: str, timezone: str | None) -> str | None:
    """A start written in the file name, or None."""
    zoom = ZOOM_STAMP.search(name)
    if zoom:
        y, mo, d, h, mi, s = (int(g) for g in zoom.groups())
        return _build(y, mo, d, h, mi, s, UTC)
    m = NAME_STAMP.search(name)
    if m is None:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    h, mi, s = int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0)
    zone = UTC if m.group(7) else (ZoneInfo(timezone) if timezone else UTC)
    return _build(y, mo, d, h, mi, s, zone)


def _build(y: int, mo: int, d: int, h: int, mi: int, s: int, zone: Any) -> str | None:
    try:
        return _format_stamp(datetime(y, mo, d, h, mi, s, tzinfo=zone))
    except ValueError:
        return None


def _parse_stamp(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(UTC)


def _format_stamp(when: datetime) -> str:
    when = when.astimezone(UTC)
    if when.microsecond:
        return f"{when:%Y-%m-%dT%H:%M:%S}.{when.microsecond // 1000:03d}Z"
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")
